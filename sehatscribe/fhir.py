"""HL7 FHIR R4 export, modelled on ABDM's OPConsultRecord document bundle.

The bundle is a ``document`` Bundle whose first entry is a Composition
(SNOMED CT 371530004, "Clinical consultation report"), followed by the
Patient, Practitioner, Encounter, Observations (vitals, LOINC), Conditions
(complaints and diagnoses) and MedicationRequests.

MVP scope: structurally valid FHIR R4. Full conformance to the NRCES ABDM
profiles (and signing with the facility's key) is a pilot-phase item.
"""

from __future__ import annotations

import html
import uuid
from datetime import datetime, timezone

from .models import DxStatus, Encounter

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
ICD10 = "http://hl7.org/fhir/sid/icd-10"
UCUM = "http://unitsofmeasure.org"


def _ref(kind: str, rid: str) -> dict:
    return {"reference": f"urn:uuid:{rid}", "type": kind}


def _entry(resource: dict) -> dict:
    return {"fullUrl": f"urn:uuid:{resource['id']}", "resource": resource}


def _vital(obs_id: str, pid: str, when: str, loinc: str, display: str, value: float, unit: str, code: str) -> dict:
    return {
        "resourceType": "Observation",
        "id": obs_id,
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
        "code": {"coding": [{"system": LOINC, "code": loinc, "display": display}], "text": display},
        "subject": _ref("Patient", pid),
        "effectiveDateTime": when,
        "valueQuantity": {"value": value, "unit": unit, "system": UCUM, "code": code},
    }


_FREQ_TEXT = {1: "once daily", 2: "twice daily", 3: "three times daily", 4: "four times daily"}


def build_bundle(enc: Encounter, practitioner_name: str = "Attending doctor") -> dict:
    if enc.note is None:
        raise ValueError("Encounter has no note")
    note = enc.note
    now = (enc.signed_at or datetime.now(timezone.utc)).isoformat()
    pid, prid, eid, cid = (str(uuid.uuid4()) for _ in range(4))

    patient: dict = {"resourceType": "Patient", "id": pid, "name": [{"text": enc.patient_name or "Unknown"}]}
    if enc.abha_number:
        patient["identifier"] = [{"system": "https://healthid.ndhm.gov.in", "value": enc.abha_number}]
    if enc.patient_sex in ("male", "female", "other"):
        patient["gender"] = enc.patient_sex

    practitioner = {"resourceType": "Practitioner", "id": prid, "name": [{"text": enc.signed_by or practitioner_name}]}
    encounter = {
        "resourceType": "Encounter",
        "id": eid,
        "status": "finished",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory"},
        "subject": _ref("Patient", pid),
        "period": {"start": enc.created_at.isoformat(), "end": now},
    }

    resources: list[dict] = []
    complaint_refs, vital_refs, dx_refs, med_refs = [], [], [], []

    for s in note.symptoms:
        rid = str(uuid.uuid4())
        coding = [{"system": SNOMED, "code": s.snomed, "display": s.name}] if s.snomed else []
        cond = {
            "resourceType": "Condition",
            "id": rid,
            "category": [{"text": "chief complaint"}],
            "code": {"coding": coding, "text": s.name + (f" ({', '.join(s.modifiers)})" if s.modifiers else "")},
            "subject": _ref("Patient", pid),
            "note": [{"text": f"Reported by {s.reported_by.value}"}],
        }
        if s.duration_days:
            cond["onsetString"] = f"{s.duration_days:g} days before consultation"
        resources.append(cond)
        complaint_refs.append(_ref("Condition", rid))

    v = note.vitals
    vit_specs = []
    if v.bp_systolic:
        vit_specs.append(("8480-6", "Systolic blood pressure", v.bp_systolic, "mmHg", "mm[Hg]"))
    if v.bp_diastolic:
        vit_specs.append(("8462-4", "Diastolic blood pressure", v.bp_diastolic, "mmHg", "mm[Hg]"))
    if v.temperature_f:
        vit_specs.append(("8310-5", "Body temperature", v.temperature_f, "degF", "[degF]"))
    if v.spo2:
        vit_specs.append(("59408-5", "Oxygen saturation by pulse oximetry", v.spo2, "%", "%"))
    if v.pulse:
        vit_specs.append(("8867-4", "Heart rate", v.pulse, "beats/min", "/min"))
    if v.weight_kg:
        vit_specs.append(("29463-7", "Body weight", v.weight_kg, "kg", "kg"))
    if v.glucose_mg_dl:
        vit_specs.append(("2339-0", f"Glucose ({v.glucose_context or 'unspecified'})", v.glucose_mg_dl, "mg/dL", "mg/dL"))
    for loinc, disp, val, unit, code in vit_specs:
        rid = str(uuid.uuid4())
        resources.append(_vital(rid, pid, now, loinc, disp, val, unit, code))
        vital_refs.append(_ref("Observation", rid))

    for d in note.diagnoses:
        rid = str(uuid.uuid4())
        coding = []
        if d.snomed:
            coding.append({"system": SNOMED, "code": d.snomed, "display": d.name})
        if d.icd10:
            coding.append({"system": ICD10, "code": d.icd10})
        verification = {"suspected": "unconfirmed", "provisional": "provisional", "confirmed": "confirmed"}[d.status.value]
        resources.append({
            "resourceType": "Condition",
            "id": rid,
            "category": [{"text": "encounter-diagnosis"}],
            "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": verification}]},
            "code": {"coding": coding, "text": d.name + (" (suspected)" if d.status == DxStatus.SUSPECTED else "")},
            "subject": _ref("Patient", pid),
        })
        dx_refs.append(_ref("Condition", rid))

    for m in note.medications:
        rid = str(uuid.uuid4())
        parts = [f"{m.dose:g} {m.unit}" if m.dose else None,
                 "as needed" if m.prn else _FREQ_TEXT.get(m.frequency_per_day or 0),
                 f"for {m.duration_days} days" if m.duration_days else None]
        dosage: dict = {"text": ", ".join(p for p in parts if p), "route": {"text": m.route}}
        if m.frequency_per_day:
            dosage["timing"] = {"repeat": {"frequency": m.frequency_per_day, "period": 1, "periodUnit": "d"}}
        if m.prn:
            dosage["asNeededBoolean"] = True
        if m.dose:
            dosage["doseAndRate"] = [{"doseQuantity": {"value": m.dose, "unit": m.unit, "system": UCUM, "code": m.unit}}]
        resources.append({
            "resourceType": "MedicationRequest",
            "id": rid,
            "status": "active",
            "intent": "order",
            "medicationCodeableConcept": {"text": m.drug},
            "subject": _ref("Patient", pid),
            "authoredOn": now,
            "requester": _ref("Practitioner", prid),
            "dosageInstruction": [dosage],
        })
        med_refs.append(_ref("MedicationRequest", rid))

    def section(title: str, loinc: str, refs: list[dict], text: str | None = None) -> dict:
        s: dict = {"title": title, "code": {"coding": [{"system": LOINC, "code": loinc}]}}
        if refs:
            s["entry"] = refs
        if text:
            s["text"] = {"status": "generated", "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{html.escape(text)}</div>'}
        if not refs and not text:
            s["emptyReason"] = {"text": "nil"}
        return s

    plan_bits = []
    if note.investigations:
        plan_bits.append("Investigations: " + "; ".join(note.investigations))
    if note.advice:
        plan_bits.append("Advice: " + "; ".join(note.advice))
    if note.follow_up_days:
        plan_bits.append(f"Follow up in {note.follow_up_days} days")
    if note.doctor_remarks:
        plan_bits.append("Remarks: " + note.doctor_remarks)
    negatives = ("Denies: " + ", ".join(note.negatives)) if note.negatives else None

    composition = {
        "resourceType": "Composition",
        "id": cid,
        "status": "final",
        "type": {"coding": [{"system": SNOMED, "code": "371530004", "display": "Clinical consultation report"}], "text": "OP Consultation"},
        "subject": _ref("Patient", pid),
        "encounter": _ref("Encounter", eid),
        "date": now,
        "author": [_ref("Practitioner", prid)],
        "title": "OP Consultation Record",
        "section": [
            section("Chief complaints", "10154-3", complaint_refs, negatives),
            section("Vital signs", "8716-3", vital_refs),
            section("Assessment", "51848-0", dx_refs),
            section("Medications", "10160-0", med_refs),
            section("Plan of care", "18776-5", [], ". ".join(plan_bits) if plan_bits else None),
        ],
    }

    entries = [composition, patient, practitioner, encounter, *resources]
    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "meta": {"lastUpdated": now},
        "identifier": {"system": "https://sehatscribe.local/encounter", "value": enc.id},
        "type": "document",
        "timestamp": now,
        "entry": [_entry(r) for r in entries],
    }
