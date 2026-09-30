"""Speech-to-text backends.

* ``FasterWhisperBackend`` — multilingual Whisper via CTranslate2 on CPU. Works
  today on Windows on Snapdragon (x64 emulation or native ARM64 where wheels
  exist), Linux and macOS.
* NPU path (roadmap, week 2–4 of the build plan): Whisper exported from
  Qualcomm AI Hub and run through ONNX Runtime's QNN execution provider. The
  interface below is what that backend will implement.

Audio is never persisted: callers pass a temporary file that is deleted as
soon as transcription finishes (see ``pipeline.transcribe_audio``).
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Protocol

from .models import Role, Transcript, Utterance
from .speakers import assign_roles


@dataclass
class ASRResult:
    transcript: Transcript
    audio_seconds: float
    wall_seconds: float

    @property
    def real_time_factor(self) -> float | None:
        return self.wall_seconds / self.audio_seconds if self.audio_seconds else None


class ASRBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def transcribe(self, path: str, language: str | None = None) -> ASRResult: ...


class FasterWhisperBackend:
    name = "faster-whisper-cpu"

    def __init__(self, model: str | None = None):
        self.model_name = model or os.environ.get("SEHAT_WHISPER_MODEL", "small")
        self._model = None

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    def transcribe(self, path: str, language: str | None = None) -> ASRResult:
        from faster_whisper import WhisperModel

        if self._model is None:
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        t0 = time.perf_counter()
        segments, info = self._model.transcribe(path, language=language, vad_filter=True, beam_size=1)
        utts = []
        for s in segments:
            conf = round(math.exp(s.avg_logprob), 3) if s.avg_logprob is not None else None
            utts.append(Utterance(speaker=Role.UNKNOWN, text=s.text.strip(), start=s.start, end=s.end, confidence=conf))
        wall = time.perf_counter() - t0
        tx = Transcript(utterances=assign_roles(utts), language=info.language or (language or "hi"), source="audio")
        return ASRResult(transcript=tx, audio_seconds=float(info.duration or 0), wall_seconds=wall)


def get_asr_backend() -> ASRBackend | None:
    backend = FasterWhisperBackend()
    return backend if backend.available() else None
