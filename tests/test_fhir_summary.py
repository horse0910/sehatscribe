from sehatscribe.extract import extract_note
from sehatscribe.fhir import build_bundle
from sehatscribe.models import Consent, Encounter, EncounterStatus
from sehatscribe.summary import patient_summary


def make_enc(tx):
    return Encounter(id="t1", consent=Consent(given=True), transcript=tx, note=extract_note(tx),
                     status=EncounterStatus.SIGNED, signed_by="Dr Test", patient_name="Ramesh",
                     patient_sex="male", abha_number="91-1234-5678-9012")


def test_bundle_structure(fever_tx):
    b = build_bundle(make_enc(fever_tx))
    assert b["resourceType"] == "Bundle" and b["type"] == "document"
    types = [e["resource"]["resourceType"] for e in b["entry"]]
    assert types[0] == "Composition"
    assert {"Patient", "Practitioner", "Encounter", "Observation", "Condition", "MedicationRequest"} <= set(types)
    comp = b["entry"][0]["resource"]
    assert comp["type"]["coding"][0]["code"] == "371530004"
    # every reference in the composition resolves to an entry in the bundle
    urls = {e["fullUrl"] for e in b["entry"]}
    for s in comp["section"]:
        for ref in s.get("entry", []):
            assert ref["reference"] in urls


def test_vitals_use_loinc(fever_tx):
    b = build_bundle(make_enc(fever_tx))
    loinc = {e["resource"]["code"]["coding"][0]["code"] for e in b["entry"] if e["resource"]["resourceType"] == "Observation"}
    assert {"8480-6", "8462-4", "8310-5", "59408-5"} <= loinc


def test_abha_identifier_and_escaping(fever_tx):
    enc = make_enc(fever_tx)
    enc.note.doctor_remarks = "<script>alert(1)</script>"
    b = build_bundle(enc)
    patient = next(e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "Patient")
    assert patient["identifier"][0]["value"] == "91-1234-5678-9012"
    plan = b["entry"][0]["resource"]["section"][-1]["text"]["div"]
    assert "<script>" not in plan


def test_patient_summary_hindi_and_english(fever_tx):
    n = extract_note(fever_tx)
    hi = patient_summary(n, "hi")["lines"]
    assert any("पैरासिटामोल 650 mg दिन में 3 बार 3 दिन तक" in line for line in hi)
    en = patient_summary(n, "en")["lines"]
    assert any("Paracetamol 650 mg three times a day for 3 days" in line for line in en)
