"""Local HTTP API and web UI server.

Binds to 127.0.0.1 by default: the app is meant to run on the doctor's own
PC. To accept vitals from the Arduino UNO Q pod over Wi-Fi, run with
``--host 0.0.0.0`` and set ``SEHAT_DEVICE_TOKEN``.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings
from .fhir import build_bundle
from .models import Consent, Encounter, EncounterStatus, SoapNote, Vitals
from .pipeline import draft_note, transcribe_bytes
from .runtime import runtime_report
from .safety import check_note
from .speakers import parse_text_transcript
from .store import Store, note_fingerprint
from .summary import patient_summary

# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #


class NewEncounter(BaseModel):
    patient_name: Optional[str] = Field(None, max_length=120)
    patient_age: Optional[int] = Field(None, ge=0, le=130)
    patient_sex: Optional[str] = Field(None, pattern="^(male|female|other)$")
    abha_number: Optional[str] = Field(None, pattern=r"^[0-9\-]{14,17}$")
    language: str = Field("hi", pattern="^[a-z]{2}$")
    consent_given: bool


class TranscriptIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=50_000)


class NoteIn(BaseModel):
    note: SoapNote


class SignIn(BaseModel):
    doctor_id: str
    pin: str


class DoctorIn(BaseModel):
    doctor_id: str = Field(..., min_length=2, max_length=40, pattern=r"^[\w.\-]+$")
    display_name: str = Field(..., min_length=2, max_length=80)
    pin: str = Field(..., min_length=4, max_length=12, pattern=r"^\d+$")


class DeviceVitals(BaseModel):
    device_id: str = Field("uno-q-pod", max_length=40)
    bp_systolic: Optional[int] = Field(None, ge=50, le=260)
    bp_diastolic: Optional[int] = Field(None, ge=30, le=160)
    temperature_f: Optional[float] = Field(None, ge=90, le=110)
    spo2: Optional[int] = Field(None, ge=50, le=100)
    pulse: Optional[int] = Field(None, ge=20, le=250)


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.db_path, settings.key_path)
    latest_vitals: dict = {}  # device reading kept in memory only

    app = FastAPI(title="SehatScribe", version=__version__, docs_url="/api/docs")
    app.state.store = store
    app.state.settings = settings

    def load(encounter_id: str) -> Encounter:
        enc = store.get(encounter_id)
        if enc is None:
            raise HTTPException(404, "Encounter not found")
        return enc

    def editable(enc: Encounter) -> None:
        if enc.status == EncounterStatus.SIGNED:
            raise HTTPException(409, "Encounter is signed and can no longer be changed")

    # -- system --------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "llm_engine": settings.llm_engine,
                "doctors_configured": store.has_doctors(), "runtime": runtime_report()}

    @app.post("/api/doctors", status_code=201)
    def create_first_doctor(body: DoctorIn):
        # Bootstrap only: further doctors are added with the CLI on the device.
        if store.has_doctors():
            raise HTTPException(403, "A doctor is already set up. Use `sehatscribe add-doctor` on this PC.")
        store.set_doctor_pin(body.doctor_id, body.display_name, body.pin)
        store.audit(body.doctor_id, "doctor.created")
        return {"doctor_id": body.doctor_id}

    # -- encounters ----------------------------------------------------------
    @app.post("/api/encounters", status_code=201)
    def create_encounter(body: NewEncounter):
        if not body.consent_given:
            raise HTTPException(403, "Patient consent is required before recording or processing a consultation.")
        enc = Encounter(
            id=uuid.uuid4().hex[:12],
            patient_name=body.patient_name,
            patient_age=body.patient_age,
            patient_sex=body.patient_sex,
            abha_number=body.abha_number,
            language=body.language,
            consent=Consent(given=True, language=body.language),
        )
        store.save(enc)
        store.audit("clinic", "encounter.created", enc.id)
        return enc

    @app.get("/api/encounters")
    def list_encounters(limit: int = Query(30, ge=1, le=200)):
        return [
            {"id": e.id, "created_at": e.created_at, "status": e.status, "patient_name": e.patient_name}
            for e in store.list(limit)
        ]

    @app.get("/api/encounters/{encounter_id}")
    def get_encounter(enc: Encounter = Depends(load)):
        return enc

    @app.post("/api/encounters/{encounter_id}/transcript")
    def add_transcript(body: TranscriptIn, enc: Encounter = Depends(load)):
        editable(enc)
        enc.transcript = parse_text_transcript(body.text, language=enc.language)
        store.save(enc)
        return enc.transcript

    @app.post("/api/encounters/{encounter_id}/audio")
    async def add_audio(enc: Encounter = Depends(load), audio: UploadFile = File(...)):
        editable(enc)
        data = await audio.read()
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, "Audio file too large")
        suffix = Path(audio.filename or "audio.webm").suffix[:8]
        try:
            tx, meta = transcribe_bytes(data, suffix, None if enc.language == "auto" else enc.language)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        finally:
            del data  # audio is never persisted
        enc.transcript = tx
        store.save(enc)
        store.audit("clinic", "audio.transcribed", enc.id)
        return {"transcript": tx, "asr": meta}

    @app.post("/api/encounters/{encounter_id}/draft")
    def draft(enc: Encounter = Depends(load)):
        editable(enc)
        if not enc.transcript or not enc.transcript.utterances:
            raise HTTPException(400, "Add a transcript or recording first")
        device = None
        if latest_vitals and time.time() - latest_vitals["ts"] <= settings.vitals_max_age_s:
            device = latest_vitals["vitals"]
        res = draft_note(enc.transcript, settings, device_vitals=device)
        enc.note, enc.flags, enc.status = res.note, res.flags, EncounterStatus.DRAFTED
        store.save(enc)
        store.audit("clinic", f"note.drafted:{res.engine}", enc.id)
        return {"note": res.note, "flags": res.flags, "engine": res.engine,
                "timings_ms": res.timings_ms, "llm_tokens_per_s": res.llm_tokens_per_s}

    @app.put("/api/encounters/{encounter_id}/note")
    def update_note(body: NoteIn, enc: Encounter = Depends(load)):
        editable(enc)
        enc.note = body.note
        enc.flags = check_note(body.note)
        enc.status = EncounterStatus.DRAFTED
        store.save(enc)
        store.audit("clinic", "note.edited", enc.id)
        return {"note": enc.note, "flags": enc.flags}

    @app.post("/api/encounters/{encounter_id}/sign")
    def sign(body: SignIn, enc: Encounter = Depends(load)):
        editable(enc)
        if enc.note is None:
            raise HTTPException(400, "Draft a note before signing")
        name = store.verify_doctor(body.doctor_id, body.pin)
        if name is None:
            store.audit(body.doctor_id, "sign.failed", enc.id)
            raise HTTPException(401, "Invalid doctor ID or PIN")
        enc.signed_by, enc.signed_at = name, datetime.now(timezone.utc)
        enc.status = EncounterStatus.SIGNED
        enc.note_hash = note_fingerprint(enc)
        store.save(enc)
        store.audit(body.doctor_id, "note.signed", enc.id)
        return {"status": enc.status, "signed_by": name, "signed_at": enc.signed_at, "note_hash": enc.note_hash}

    @app.get("/api/encounters/{encounter_id}/fhir")
    def export_fhir(enc: Encounter = Depends(load)):
        if enc.status != EncounterStatus.SIGNED:
            raise HTTPException(409, "Only signed notes can be exported")
        store.audit(enc.signed_by or "clinic", "fhir.exported", enc.id)
        return JSONResponse(build_bundle(enc), media_type="application/fhir+json",
                            headers={"Content-Disposition": f'attachment; filename="opconsult-{enc.id}.json"'})

    @app.get("/api/encounters/{encounter_id}/summary")
    def summary(lang: str = Query("hi", pattern="^(hi|en)$"), enc: Encounter = Depends(load)):
        if enc.note is None:
            raise HTTPException(400, "No note yet")
        return patient_summary(enc.note, lang)

    @app.get("/api/audit")
    def audit(limit: int = Query(100, ge=1, le=1000)):
        return store.audit_log(limit)

    # -- vitals pod ----------------------------------------------------------
    @app.post("/api/devices/vitals", status_code=202)
    def device_vitals(body: DeviceVitals, x_device_token: str = Header("")):
        if not settings.device_token or x_device_token != settings.device_token:
            raise HTTPException(401, "Device token missing or invalid")
        latest_vitals.update(ts=time.time(), device=body.device_id,
                             vitals=Vitals(**body.model_dump(exclude={"device_id"}), source="device"))
        return {"accepted": True}

    @app.get("/api/devices/vitals/latest")
    def latest_device_vitals():
        if not latest_vitals:
            return {"vitals": None}
        age = time.time() - latest_vitals["ts"]
        return {"vitals": latest_vitals["vitals"], "device": latest_vitals["device"], "age_s": round(age, 1),
                "fresh": age <= settings.vitals_max_age_s}

    # -- web UI --------------------------------------------------------------
    web_dir = Path(str(resources.files("sehatscribe").joinpath("web")))
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(web_dir / "index.html")

    return app
