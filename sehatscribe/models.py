"""Domain models shared by every stage of the pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, Enum):
    DOCTOR = "doctor"
    PATIENT = "patient"
    CAREGIVER = "caregiver"
    UNKNOWN = "unknown"


class Utterance(BaseModel):
    speaker: Role
    text: str
    start: Optional[float] = None  # seconds, when from audio
    end: Optional[float] = None
    confidence: Optional[float] = None  # ASR average log-prob mapped to 0..1
    role_inferred: bool = False  # True when the role came from the heuristic classifier


class Transcript(BaseModel):
    utterances: list[Utterance] = Field(default_factory=list)
    language: str = "hi"
    source: str = "text"  # "text" | "audio"

    def text_by(self, *roles: Role) -> list[str]:
        return [u.text for u in self.utterances if not roles or u.speaker in roles]

    def full_text(self) -> str:
        return "\n".join(u.text for u in self.utterances)


class Symptom(BaseModel):
    name: str
    snomed: Optional[str] = None
    duration_days: Optional[float] = None
    modifiers: list[str] = Field(default_factory=list)
    reported_by: Role = Role.PATIENT


class Vitals(BaseModel):
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    temperature_f: Optional[float] = None
    spo2: Optional[int] = None
    pulse: Optional[int] = None
    weight_kg: Optional[float] = None
    glucose_mg_dl: Optional[int] = None
    glucose_context: Optional[str] = None  # fasting | random | pp
    source: str = "transcript"  # transcript | device | manual

    def is_empty(self) -> bool:
        return all(
            getattr(self, f) is None
            for f in ("bp_systolic", "temperature_f", "spo2", "pulse", "weight_kg", "glucose_mg_dl")
        )


class DxStatus(str, Enum):
    SUSPECTED = "suspected"
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"


class Diagnosis(BaseModel):
    name: str
    status: DxStatus = DxStatus.PROVISIONAL
    snomed: Optional[str] = None
    icd10: Optional[str] = None


class MedicationOrder(BaseModel):
    drug: str
    dose: Optional[float] = None
    unit: str = "mg"
    frequency_per_day: Optional[int] = None
    prn: bool = False
    duration_days: Optional[int] = None
    route: str = "oral"
    mentioned_as: Optional[str] = None  # brand or spoken form


class HomeMedication(BaseModel):
    drug: str
    mentioned_as: str


class SoapNote(BaseModel):
    # Subjective
    symptoms: list[Symptom] = Field(default_factory=list)
    negatives: list[str] = Field(default_factory=list)
    home_medications: list[HomeMedication] = Field(default_factory=list)
    # Objective
    vitals: Vitals = Field(default_factory=Vitals)
    # Assessment
    diagnoses: list[Diagnosis] = Field(default_factory=list)
    # Plan
    medications: list[MedicationOrder] = Field(default_factory=list)
    investigations: list[str] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)
    follow_up_days: Optional[int] = None
    # Free text the doctor may add while reviewing
    doctor_remarks: str = ""
    generated_by: str = "rules"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SafetyFlag(BaseModel):
    severity: Severity
    code: str
    message: str
    drug: Optional[str] = None


class Consent(BaseModel):
    given: bool
    language: str = "hi"
    captured_at: datetime = Field(default_factory=utcnow)


class EncounterStatus(str, Enum):
    OPEN = "open"
    DRAFTED = "drafted"
    SIGNED = "signed"


class Encounter(BaseModel):
    id: str
    created_at: datetime = Field(default_factory=utcnow)
    status: EncounterStatus = EncounterStatus.OPEN
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    patient_sex: Optional[str] = None  # male | female | other
    abha_number: Optional[str] = None
    language: str = "hi"
    consent: Consent
    transcript: Optional[Transcript] = None
    note: Optional[SoapNote] = None
    flags: list[SafetyFlag] = Field(default_factory=list)
    signed_by: Optional[str] = None
    signed_at: Optional[datetime] = None
    note_hash: Optional[str] = None
