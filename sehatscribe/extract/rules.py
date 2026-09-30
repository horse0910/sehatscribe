"""Deterministic Hinglish/Hindi/English clinical extractor.

This is the default drafting engine: fast, explainable, fully offline and
runs anywhere (CPU). The LLM engines in ``extract.llm`` produce the same
``SoapNote`` and are always passed through ``ground_note`` so the model can
only keep facts that were actually spoken.
"""

from __future__ import annotations

import re

from ..lexicon import (
    ADVICE,
    AFFIRMATION_TERMS,
    DIAGNOSES,
    DRUGS,
    DURATION_RE,
    DX_CONFIRMED_CUES,
    DX_PROVISIONAL_CUES,
    DX_SUSPECTED_CUES,
    FREQUENCY_PATTERNS,
    INVESTIGATIONS,
    MODIFIERS,
    NEGATION_TERMS,
    NUM_RE,
    SYMPTOMS,
    UNIT_DAYS,
    find_terms,
    term_pattern,
    to_number,
)
from ..models import (
    Diagnosis,
    DxStatus,
    HomeMedication,
    MedicationOrder,
    Role,
    SoapNote,
    Symptom,
    Transcript,
    Vitals,
)

# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def durations_in(text: str) -> list[tuple[int, float]]:
    """Return (position, days) for each duration phrase in text."""
    out = []
    for m in DURATION_RE.finditer(text):
        n = to_number(m.group(1))
        unit = UNIT_DAYS.get(m.group(2).lower())
        if n is not None and unit:
            out.append((m.start(), n * unit))
    return out


def _is_negated(text: str, match_end: int, window_words: int = 4) -> bool:
    tail = text[match_end:].split()[:window_words]
    tail_text = " ".join(tail)
    return any(term_pattern(n).search(tail_text) for n in NEGATION_TERMS)


def _starts_with(text: str, terms: list[str]) -> bool:
    head = " ".join(text.split()[:2])
    return any(term_pattern(t).match(head) for t in terms)


def _clauses(text: str) -> list[str]:
    parts = re.split(r"[,.;!?]|\s+(?:par|lekin|but|however|magar)\s+", text)
    return [p.strip() for p in parts if p.strip()]


# --------------------------------------------------------------------------- #
# Subjective
# --------------------------------------------------------------------------- #


def extract_symptoms(tx: Transcript) -> tuple[list[Symptom], list[str]]:
    found: dict[str, Symptom] = {}
    negatives: set[str] = set()
    utts = tx.utterances

    for i, u in enumerate(utts):
        text = _norm(u.text)

        if u.speaker == Role.DOCTOR:
            # Q&A: "Ulti ya dast hua?" -> next non-doctor reply decides.
            if not text.endswith("?"):
                continue
            asked = [name for name, c in SYMPTOMS.items() if find_terms(text, c["terms"])]
            reply = next((v for v in utts[i + 1 :] if v.speaker != Role.DOCTOR), None)
            if not asked or reply is None:
                continue
            rtext = _norm(reply.text)
            if _starts_with(rtext, NEGATION_TERMS):
                # Only symptoms not explicitly affirmed elsewhere in the reply
                for name in asked:
                    if not find_terms(rtext, SYMPTOMS[name]["terms"]) or _is_negated(rtext, 0, 99):
                        negatives.add(name)
            elif _starts_with(rtext, AFFIRMATION_TERMS):
                for name in asked:
                    found.setdefault(name, Symptom(name=name, snomed=SYMPTOMS[name]["snomed"], reported_by=reply.speaker))
            continue

        durs = durations_in(text)
        # A bare duration answer ("Do mahine se.") dates the symptoms already reported.
        if durs and not any(find_terms(text, c["terms"]) for c in SYMPTOMS.values()):
            for sym in found.values():
                if sym.duration_days is None:
                    sym.duration_days = durs[0][1]
            continue
        for name, concept in SYMPTOMS.items():
            hits = find_terms(text, concept["terms"])
            if not hits:
                continue
            hit = min(hits, key=lambda m: m.start())
            if _is_negated(text, hit.end()):
                negatives.add(name)
                continue
            sym = found.get(name) or Symptom(name=name, snomed=concept["snomed"], reported_by=u.speaker)
            if durs and sym.duration_days is None:
                sym.duration_days = durs[0][1]
            for mod, terms in MODIFIERS.items():
                if find_terms(text, terms) and mod not in sym.modifiers:
                    sym.modifiers.append(mod)
            found[name] = sym

    # "tez" alone is a modifier only when fever is present
    for name, sym in found.items():
        if name != "fever" and "high grade" in sym.modifiers:
            sym.modifiers.remove("high grade")
    negatives -= set(found)
    return list(found.values()), sorted(negatives)


def extract_home_medications(tx: Transcript) -> list[HomeMedication]:
    out: list[HomeMedication] = []
    for u in tx.utterances:
        if u.speaker == Role.DOCTOR:
            continue
        text = _norm(u.text)
        for generic, forms in DRUGS.items():
            for m in find_terms(text, forms):
                if not any(h.drug == generic for h in out):
                    out.append(HomeMedication(drug=generic, mentioned_as=m.group(0)))
    return out


# --------------------------------------------------------------------------- #
# Objective
# --------------------------------------------------------------------------- #

_V = r"\s*(?:is|hai|:|=|reading|level|aaya|aayi)?\s*"
_VITAL_RES = {
    "bp": re.compile(r"(?<![a-z])(?:bp|blood pressure|b\.p\.)" + _V + r"(\d{2,3})\s*(?:/|by|over)\s*(\d{2,3})"),
    "temp": re.compile(r"(?<![a-z])(?:temp|temperature|taapmaan|तापमान)" + _V + r"(\d{2,3}(?:\.\d)?)"),
    "spo2": re.compile(r"(?<![a-z])(?:spo2|sp02|spo₂|oxygen|o2|saturation)" + _V + r"(\d{2,3})"),
    "pulse": re.compile(r"(?<![a-z])(?:pulse|heart rate|hr|nabz)" + _V + r"(\d{2,3})"),
    "weight": re.compile(r"(?<![a-z])(?:weight|wazan|vajan|वजन)" + _V + r"(\d{2,3}(?:\.\d)?)"),
    "glucose": re.compile(r"(?<![a-z])(?:(fasting|random|pp|post ?prandial)\s+)?(?:sugar|glucose)" + _V + r"(\d{2,3})"),
}


def extract_vitals(tx: Transcript) -> Vitals:
    v = Vitals()
    for u in tx.utterances:
        text = _norm(u.text)
        if m := _VITAL_RES["bp"].search(text):
            v.bp_systolic, v.bp_diastolic = int(m.group(1)), int(m.group(2))
        if m := _VITAL_RES["temp"].search(text):
            t = float(m.group(1))
            v.temperature_f = t if t > 45 else round(t * 9 / 5 + 32, 1)
        if m := _VITAL_RES["spo2"].search(text):
            v.spo2 = int(m.group(1))
        if m := _VITAL_RES["pulse"].search(text):
            v.pulse = int(m.group(1))
        if m := _VITAL_RES["weight"].search(text):
            v.weight_kg = float(m.group(1))
        if m := _VITAL_RES["glucose"].search(text):
            v.glucose_mg_dl = int(m.group(2))
            if m.group(1):
                v.glucose_context = m.group(1).replace(" ", "")
    return v


# --------------------------------------------------------------------------- #
# Assessment
# --------------------------------------------------------------------------- #


def extract_diagnoses(tx: Transcript) -> list[Diagnosis]:
    out: dict[str, Diagnosis] = {}
    for u in tx.utterances:
        if u.speaker != Role.DOCTOR:
            continue
        for clause in _clauses(_norm(u.text)):
            names = [n for n, c in DIAGNOSES.items() if find_terms(clause, c["terms"])]
            if not names:
                continue
            if find_terms(clause, DX_SUSPECTED_CUES):
                status = DxStatus.SUSPECTED
            elif find_terms(clause, DX_PROVISIONAL_CUES):
                status = DxStatus.PROVISIONAL
            elif find_terms(clause, DX_CONFIRMED_CUES) or re.search(r"(?<![\w])(hai|hain|है)$", clause):
                status = DxStatus.CONFIRMED
            else:
                # Mentioned in the plan (e.g. "malaria test") is not a diagnosis
                continue
            for n in names:
                if find_terms(clause, [f"{t} test" for t in DIAGNOSES[n]["terms"]]) and status == DxStatus.CONFIRMED:
                    continue
                c = DIAGNOSES[n]
                out[n] = Diagnosis(name=n, status=status, snomed=c["snomed"], icd10=c["icd10"])
    return list(out.values())


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #

_DOSE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|iu)(?![a-z])")
_DUR_AFTER_RE = re.compile(
    r"(?<![\w\u0900-\u097F])" + NUM_RE + r"\s*(din|days?|d|hafte|weeks?|mahine|months?|दिन)(?![a-z\u0900-\u097F])",
    re.IGNORECASE,
)


def _frequency(window: str) -> tuple[int | None, bool]:
    for pattern, value, prn in FREQUENCY_PATTERNS:
        m = re.search(pattern, window, re.IGNORECASE)
        if not m:
            continue
        if value == -1:
            return (int(to_number(m.group(1)) or 0) or None), False
        return value, prn
    return None, False


def extract_medications(tx: Transcript) -> list[MedicationOrder]:
    out: list[MedicationOrder] = []
    for u in tx.utterances:
        if u.speaker != Role.DOCTOR:
            continue
        text = _norm(u.text)
        hits = sorted(
            ((m.start(), m.end(), g, m.group(0)) for g, forms in DRUGS.items() for m in find_terms(text, forms)),
            key=lambda h: h[0],
        )
        added_here: list[MedicationOrder] = []
        for idx, (start, end, generic, spoken) in enumerate(hits):
            nxt = hits[idx + 1][0] if idx + 1 < len(hits) else len(text)
            window = text[end:nxt]
            # stop at sentence end
            window = re.split(r"[.;]", window)[0]
            dose = _DOSE_RE.search(window)
            freq, prn = _frequency(window)
            dur = _DUR_AFTER_RE.search(window)
            duration = None
            if dur:
                n = to_number(dur.group(1))
                unit = UNIT_DAYS.get(dur.group(2).lower(), UNIT_DAYS.get(dur.group(2).lower().rstrip("s"), 1))
                duration = int(n * unit) if n else None
            # A drug named without any dosing detail by the doctor is usually
            # a question ("koi crocin li?") rather than an order.
            if not dose and freq is None and not prn and duration is None:
                continue
            if any(o.drug == generic for o in out):
                continue
            order = MedicationOrder(
                drug=generic,
                dose=float(dose.group(1)) if dose else None,
                unit=dose.group(2) if dose else "mg",
                frequency_per_day=freq,
                prn=prn,
                duration_days=duration,
                mentioned_as=spoken if spoken != generic else None,
            )
            out.append(order)
            added_here.append(order)
        # "Metformin ... aur amlodipine ..., ek mahine tak": a duration stated
        # once at the end of the sentence applies to every drug in it.
        if len(added_here) > 1 and added_here[-1].duration_days:
            for o in added_here[:-1]:
                if o.duration_days is None:
                    o.duration_days = added_here[-1].duration_days
    return out


def extract_investigations(tx: Transcript) -> list[str]:
    out: list[str] = []
    for u in tx.utterances:
        if u.speaker != Role.DOCTOR:
            continue
        text = _norm(u.text)
        for name, terms in INVESTIGATIONS.items():
            if find_terms(text, terms) and name not in out:
                out.append(name)
    return out


def extract_advice(tx: Transcript) -> list[str]:
    out: list[str] = []
    for u in tx.utterances:
        if u.speaker != Role.DOCTOR:
            continue
        text = _norm(u.text)
        for name, terms in ADVICE.items():
            if find_terms(text, terms) and name not in out:
                out.append(name)
    return out


_FOLLOW_RE = re.compile(r"(?<![\w\u0900-\u097F])" + NUM_RE + r"\s*(din|days?|hafte|weeks?|mahine|months?|ghante|hours?)\s*(?:baad|later|after|mein)", re.I)


def extract_follow_up(tx: Transcript) -> int | None:
    for u in reversed(tx.utterances):
        if u.speaker != Role.DOCTOR:
            continue
        text = _norm(u.text)
        if m := _FOLLOW_RE.search(text):
            n = to_number(m.group(1)) or 0
            unit = m.group(2).lower()
            if unit.startswith(("ghante", "hour")):
                return max(1, round(n / 24))
            days = UNIT_DAYS.get(unit, UNIT_DAYS.get(unit.rstrip("s"), 1))
            return int(n * days)
        if re.search(r"(?:mahine|month)\s+(?:baad|later)", text):
            return 30
    return None


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def extract_note(tx: Transcript) -> SoapNote:
    symptoms, negatives = extract_symptoms(tx)
    return SoapNote(
        symptoms=symptoms,
        negatives=negatives,
        home_medications=extract_home_medications(tx),
        vitals=extract_vitals(tx),
        diagnoses=extract_diagnoses(tx),
        medications=extract_medications(tx),
        investigations=extract_investigations(tx),
        advice=extract_advice(tx),
        follow_up_days=extract_follow_up(tx),
        generated_by="rules",
    )
