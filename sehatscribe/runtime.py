"""Hardware and runtime detection: what can accelerate AI on this machine."""

from __future__ import annotations

import platform
import shutil
from functools import lru_cache

from .asr import FasterWhisperBackend
from .extract.llm import GenieBackend, OrtGenAIBackend


@lru_cache(maxsize=1)
def onnx_providers() -> list[str]:
    try:
        import onnxruntime as ort
    except ImportError:
        return []
    return list(ort.get_available_providers())


def runtime_report() -> dict:
    providers = onnx_providers()
    machine = platform.machine().lower()
    genie = GenieBackend()
    ort_genai = OrtGenAIBackend()
    return {
        "platform": platform.platform(),
        "machine": machine,
        "arm64": machine in ("arm64", "aarch64"),
        "onnxruntime_providers": providers,
        "qnn_npu_available": "QNNExecutionProvider" in providers,
        "genie_cli_found": shutil.which(genie.exe) is not None,
        "engines": {
            "asr": "faster-whisper-cpu" if FasterWhisperBackend().available() else None,
            "llm_genie_npu": genie.available(),
            "llm_ort_genai": ort_genai.available(),
            "rules": True,
        },
    }
