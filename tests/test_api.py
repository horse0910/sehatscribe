import pytest
from fastapi.testclient import TestClient

from sehatscribe.api import create_app

FEVER = (
    "DOCTOR: Kya takleef hai?\n"
    "DAUGHTER: Papa ko teen din se bukhar hai.\n"
    "DOCTOR: BP 128/84. Dengue ka shak hai. CBC karwaiye.\n"
    "DOCTOR: Ibuprofen 400 mg din mein teen baar, teen din tak."
)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    app.state.store.set_doctor_pin("dr.meera", "Dr. Meera Y.", "4321")
    return TestClient(app)


def start(client, **kw):
    body = {"patient_name": "Ramesh", "language": "hi", "consent_given": True, **kw}
    return client.post("/api/encounters", json=body)


def test_health(client):
    r = client.get("/api/health").json()
    assert r["status"] == "ok" and r["doctors_configured"] is True
    assert "qnn_npu_available" in r["runtime"]


def test_consent_is_required(client):
    assert start(client, consent_given=False).status_code == 403


def test_full_flow(client):
    enc = start(client).json()
    eid = enc["id"]
    tx = client.post(f"/api/encounters/{eid}/transcript", json={"text": FEVER}).json()
    assert tx["utterances"][1]["speaker"] == "caregiver"

    d = client.post(f"/api/encounters/{eid}/draft").json()
    assert d["engine"] == "rules"
    assert any(f["code"] == "NSAID_IN_DENGUE" for f in d["flags"])

    # doctor switches ibuprofen to paracetamol and re-checks
    note = d["note"]
    note["medications"][0].update(drug="paracetamol", dose=650)
    r = client.put(f"/api/encounters/{eid}/note", json={"note": note}).json()
    assert not any(f["code"] == "NSAID_IN_DENGUE" for f in r["flags"])

    assert client.get(f"/api/encounters/{eid}/fhir").status_code == 409  # not signed yet
    assert client.post(f"/api/encounters/{eid}/sign", json={"doctor_id": "dr.meera", "pin": "0000"}).status_code == 401
    s = client.post(f"/api/encounters/{eid}/sign", json={"doctor_id": "dr.meera", "pin": "4321"}).json()
    assert s["signed_by"] == "Dr. Meera Y." and len(s["note_hash"]) == 64

    # signed notes are immutable
    assert client.put(f"/api/encounters/{eid}/note", json={"note": note}).status_code == 409
    b = client.get(f"/api/encounters/{eid}/fhir")
    assert b.status_code == 200 and b.json()["type"] == "document"

    summ = client.get(f"/api/encounters/{eid}/summary?lang=hi").json()
    assert any("पैरासिटामोल" in line for line in summ["lines"])

    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert {"encounter.created", "note.signed", "sign.failed", "fhir.exported"} <= set(actions)


def test_device_vitals_merge(client):
    assert client.post("/api/devices/vitals", json={"spo2": 96}).status_code == 401
    r = client.post("/api/devices/vitals", json={"spo2": 96, "pulse": 88, "temperature_f": 100.4},
                    headers={"X-Device-Token": "test-token"})
    assert r.status_code == 202
    eid = start(client).json()["id"]
    client.post(f"/api/encounters/{eid}/transcript", json={"text": FEVER})
    v = client.post(f"/api/encounters/{eid}/draft").json()["note"]["vitals"]
    assert (v["spo2"], v["pulse"], v["bp_systolic"]) == (96, 88, 128)
    assert v["source"] == "device+transcript"


def test_bootstrap_doctor_only_once(client):
    r = client.post("/api/doctors", json={"doctor_id": "x.y", "display_name": "X Y", "pin": "1234"})
    assert r.status_code == 403


def test_data_encrypted_at_rest(client, settings):
    eid = start(client, patient_name="Sunita Devi").json()["id"]
    client.post(f"/api/encounters/{eid}/transcript", json={"text": FEVER})
    raw = settings.db_path.read_bytes()
    assert b"Sunita" not in raw and b"bukhar" not in raw


def test_audio_without_asr_engine_returns_503(client, monkeypatch):
    import sehatscribe.pipeline as pipeline

    monkeypatch.setattr(pipeline, "get_asr_backend", lambda: None)
    eid = start(client).json()["id"]
    r = client.post(f"/api/encounters/{eid}/audio", files={"audio": ("a.wav", b"RIFF0000", "audio/wav")})
    assert r.status_code == 503


def test_web_ui_served(client):
    assert "SehatScribe" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
