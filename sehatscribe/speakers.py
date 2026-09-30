"""Transcript parsing and speaker-role attribution.

Indian consultations are often *triadic*: a family member speaks for the
patient. Misattributing a caregiver's statement to the patient corrupts the
history, so every utterance carries a role.

Roles come from, in order of trust:
1. explicit labels in a typed transcript ("DOCTOR:", "Daughter:", "P:")
2. an external diarizer mapped to roles (roadmap: pyannote on the NPU)
3. the rule-based classifier below, which flags its output as inferred
"""

from __future__ import annotations

import re

from .lexicon import CAREGIVER_CUES, DOCTOR_CUES, QUESTION_WORDS, SPEAKER_LABELS, find_terms, term_pattern
from .models import Role, Transcript, Utterance

_LABEL_RE = re.compile(r"^\s*\[?([A-Za-zऀ-ॿ][\wऀ-ॿ .]{0,20}?)\]?\s*[:\-–]\s*(.+)$")


def classify_role(text: str, previous: Role | None = None) -> Role:
    """Best-effort role for an unlabelled utterance."""
    t = text.strip().lower()
    doctor = len(find_terms(t, DOCTOR_CUES))
    first = t.split()[0] if t.split() else ""
    if t.endswith("?") or first in QUESTION_WORDS:
        doctor += 2
    caregiver = len(find_terms(t, CAREGIVER_CUES))
    if doctor > caregiver and doctor >= 1:
        return Role.DOCTOR
    if caregiver >= 1:
        return Role.CAREGIVER
    # A reply to the doctor with no third-person cues: assume the patient.
    return Role.PATIENT


def parse_text_transcript(raw: str, language: str = "hi") -> Transcript:
    """Parse a typed transcript: one utterance per line, optional 'SPEAKER:' label."""
    utterances: list[Utterance] = []
    previous: Role | None = None
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        role: Role | None = None
        text = line
        m = _LABEL_RE.match(line)
        if m:
            label = m.group(1).strip().lower().rstrip(".")
            mapped = SPEAKER_LABELS.get(label) or ("doctor" if label.startswith(("dr ", "dr.", "doctor ")) else None)
            if mapped:
                role, text = Role(mapped), m.group(2).strip()
        if role is None:
            role = classify_role(text, previous)
            utterances.append(Utterance(speaker=role, text=text, role_inferred=True))
        else:
            utterances.append(Utterance(speaker=role, text=text))
        previous = role
    return Transcript(utterances=utterances, language=language, source="text")


def assign_roles(utterances: list[Utterance]) -> list[Utterance]:
    """Fill in roles for ASR output that has no speaker information."""
    out: list[Utterance] = []
    previous: Role | None = None
    for u in utterances:
        if u.speaker == Role.UNKNOWN:
            u = u.model_copy(update={"speaker": classify_role(u.text, previous), "role_inferred": True})
        out.append(u)
        previous = u.speaker
    return out


def mentions(text: str, term: str) -> bool:
    return term_pattern(term).search(text) is not None
