"""Safety layer: grounding and prescription checks.

Two independent guards run on every draft, whichever engine produced it:

* ``ground_note`` removes any medication, investigation or diagnosis that
  cannot be traced to the words actually spoken (anti-hallucination).
* ``check_note`` raises dose-range, completeness and condition-specific flags.

Flags never block signing: the clinician stays the decision-maker.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from .lexicon import DIAGNOSES, DRUGS, INVESTIGATIONS, find_terms
from .models import SafetyFlag, Severity, SoapNote, Transcript


@lru_cache(maxsize=1)
def load_rules() -> dict:
    return json.loads(resources.files("sehatscribe.data").joinpath("safety_rules.json").read_text("utf-8"))


def ground_note(note: SoapNote, tx: Transcript) -> tuple[SoapNote, list[SafetyFlag]]:
    text = tx.full_text().lower()
    flags: list[SafetyFlag] = []

    def spoken(forms: list[str]) -> bool:
        return bool(find_terms(text, forms))

    meds = []
    for m in note.medications:
        forms = DRUGS.get(m.drug.lower(), [m.drug.lower()])
        if spoken(forms):
            meds.append(m)
        else:
            flags.append(SafetyFlag(severity=Severity.WARNING, code="UNGROUNDED_DRUG", drug=m.drug,
                                    message=f"Removed '{m.drug}': not found in the consultation."))
    invs = []
    for inv in note.investigations:
        forms = INVESTIGATIONS.get(inv, [inv.lower()])
        if spoken(forms):
            invs.append(inv)
        else:
            flags.append(SafetyFlag(severity=Severity.INFO, code="UNGROUNDED_TEST",
                                    message=f"Removed investigation '{inv}': not found in the consultation."))
    dxs = []
    for d in note.diagnoses:
        forms = DIAGNOSES.get(d.name.lower(), {}).get("terms", [d.name.lower()])
        if spoken(forms):
            dxs.append(d)
        else:
            flags.append(SafetyFlag(severity=Severity.WARNING, code="UNGROUNDED_DX",
                                    message=f"Removed diagnosis '{d.name}': the doctor did not state it."))
    grounded = note.model_copy(update={"medications": meds, "investigations": invs, "diagnoses": dxs})
    return grounded, flags


def check_note(note: SoapNote) -> list[SafetyFlag]:
    rules = load_rules()
    flags: list[SafetyFlag] = []

    for m in note.medications:
        rule = rules["drugs"].get(m.drug.lower())
        if m.dose is None:
            flags.append(SafetyFlag(severity=Severity.WARNING, code="MISSING_DOSE", drug=m.drug,
                                    message=f"{m.drug.title()}: dose not captured — please confirm."))
        if m.frequency_per_day is None and not m.prn:
            flags.append(SafetyFlag(severity=Severity.WARNING, code="MISSING_FREQUENCY", drug=m.drug,
                                    message=f"{m.drug.title()}: frequency not captured — please confirm."))
        if m.duration_days is None and not m.prn:
            flags.append(SafetyFlag(severity=Severity.INFO, code="MISSING_DURATION", drug=m.drug,
                                    message=f"{m.drug.title()}: duration not captured."))
        if not rule or m.dose is None or m.unit != "mg":
            continue
        if m.dose > rule["max_single_mg"]:
            flags.append(SafetyFlag(severity=Severity.CRITICAL, code="SINGLE_DOSE_HIGH", drug=m.drug,
                                    message=f"{m.drug.title()} {m.dose:g} mg exceeds the single-dose limit of {rule['max_single_mg']} mg."))
        if m.frequency_per_day:
            daily = m.dose * m.frequency_per_day
            if daily > rule["max_daily_mg"]:
                flags.append(SafetyFlag(severity=Severity.CRITICAL, code="DAILY_DOSE_HIGH", drug=m.drug,
                                        message=f"{m.drug.title()} {daily:g} mg/day exceeds the daily limit of {rule['max_daily_mg']} mg."))
        if m.duration_days and rule.get("max_days") and m.duration_days > rule["max_days"]:
            flags.append(SafetyFlag(severity=Severity.WARNING, code="DURATION_LONG", drug=m.drug,
                                    message=f"{m.drug.title()} for {m.duration_days} days exceeds the usual {rule['max_days']}-day course."))

    dx_names = {d.name.lower() for d in note.diagnoses}
    for cr in rules["condition_rules"]:
        if not dx_names.intersection(cr["when_diagnosis"]):
            continue
        for m in note.medications:
            if rules["drugs"].get(m.drug.lower(), {}).get("class") == cr["avoid_class"]:
                flags.append(SafetyFlag(severity=Severity(cr["severity"]), code=cr["code"], drug=m.drug,
                                        message=f"{m.drug.title()}: {cr['message']}"))
    return flags
