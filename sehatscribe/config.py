"""Settings, resolved from environment variables with safe offline defaults."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "SehatScribe"
    return Path.home() / ".sehatscribe"


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("SEHAT_DATA_DIR") or default_data_dir()))
    # "auto" tries Genie (NPU) -> ONNX Runtime GenAI -> rules. "rules" is fully deterministic.
    llm_engine: str = field(default_factory=lambda: os.environ.get("SEHAT_LLM", "auto"))
    # Shared secret the Arduino UNO Q vitals pod sends in the X-Device-Token header.
    device_token: str = field(default_factory=lambda: os.environ.get("SEHAT_DEVICE_TOKEN", ""))
    # Vitals from the pod are attached to an encounter if newer than this.
    vitals_max_age_s: int = field(default_factory=lambda: int(os.environ.get("SEHAT_VITALS_MAX_AGE_S", "900")))
    max_upload_mb: int = 50

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sehatscribe.db"

    @property
    def key_path(self) -> Path:
        return self.data_dir / "sehatscribe.key"
