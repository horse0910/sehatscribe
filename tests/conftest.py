from pathlib import Path

import pytest

from sehatscribe.config import Settings
from sehatscribe.speakers import parse_text_transcript

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


@pytest.fixture
def fever_tx():
    return parse_text_transcript((SAMPLES / "consult_fever_hinglish.txt").read_text(encoding="utf-8"))


@pytest.fixture
def diabetes_tx():
    return parse_text_transcript((SAMPLES / "consult_diabetes_hinglish.txt").read_text(encoding="utf-8"))


@pytest.fixture
def dengue_tx():
    return parse_text_transcript((SAMPLES / "consult_dengue_unlabelled.txt").read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path):
    s = Settings(data_dir=tmp_path, llm_engine="rules", device_token="test-token")
    return s
