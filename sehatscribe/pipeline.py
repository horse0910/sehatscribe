"""End-to-end orchestration: transcript -> draft note -> safety flags."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass, field

from .asr import get_asr_backend
from .config import Settings
from .extract.llm import draft_with_llm, get_backend
from .extract.rules import extract_note
from .models import SafetyFlag, Severity, SoapNote, Transcript, Vitals
from .safety import check_note, ground_note

log = logging.getLogger("sehatscribe")


@dataclass
class DraftResult:
    note: SoapNote
    flags: list[SafetyFlag]
    engine: str
    timings_ms: dict[str, float] = field(default_factory=dict)
    llm_tokens_per_s: float | None = None


def _llm_order(engine: str) -> list[str]:
    if engine == "auto":
        return ["genie", "ort-genai"]
    if engine in ("genie", "ort-genai"):
        return [engine]
    return []


def draft_note(tx: Transcript, settings: Settings | None = None, device_vitals: Vitals | None = None) -> DraftResult:
    settings = settings or Settings()
    timings: dict[str, float] = {}
    flags: list[SafetyFlag] = []
    note: SoapNote | None = None
    engine = "rules"
    tps = None

    for name in _llm_order(settings.llm_engine):
        backend = get_backend(name)
        if backend is None or not backend.available():
            continue
        t0 = time.perf_counter()
        try:
            note, res = draft_with_llm(tx, backend)
            engine, tps = backend.name, res.tokens_per_second
            timings["llm"] = (time.perf_counter() - t0) * 1000
            break
        except Exception as exc:  # model errors must never block the doctor
            log.warning("LLM engine %s failed, falling back: %s", name, exc)
            flags.append(SafetyFlag(severity=Severity.INFO, code="LLM_FALLBACK",
                                    message=f"{backend.name} unavailable ({type(exc).__name__}); used rule engine."))

    t0 = time.perf_counter()
    rules_note = extract_note(tx)
    timings["rules"] = (time.perf_counter() - t0) * 1000
    if note is None:
        note = rules_note
    else:
        # Measured vitals are pattern-matched reliably; prefer the rule engine's numbers.
        if not rules_note.vitals.is_empty():
            note.vitals = rules_note.vitals

    if device_vitals is not None and not device_vitals.is_empty():
        merged = note.vitals.model_dump()
        for k, v in device_vitals.model_dump(exclude={"source"}).items():
            if v is not None:
                merged[k] = v
        merged["source"] = "device" if note.vitals.is_empty() else "device+transcript"
        note.vitals = Vitals.model_validate(merged)

    t0 = time.perf_counter()
    note, gflags = ground_note(note, tx)
    flags += gflags + check_note(note)
    timings["safety"] = (time.perf_counter() - t0) * 1000
    return DraftResult(note=note, flags=flags, engine=engine, timings_ms=timings, llm_tokens_per_s=tps)


def transcribe_bytes(data: bytes, suffix: str, language: str | None) -> tuple[Transcript, dict]:
    """Transcribe uploaded audio. The temp file is always deleted."""
    backend = get_asr_backend()
    if backend is None:
        raise RuntimeError("No speech-to-text engine installed. Run: pip install -r requirements-asr.txt")
    fd, path = tempfile.mkstemp(suffix=suffix or ".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        res = backend.transcribe(path, language=language)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return res.transcript, {"engine": backend.name, "audio_s": res.audio_seconds, "rtf": res.real_time_factor}
