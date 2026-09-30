"""LLM drafting engines for Snapdragon PCs.

Two on-device backends produce the same ``SoapNote`` as the rule engine:

* ``GenieBackend`` — Qualcomm Genie runtime running Llama 3.2 3B Instruct
  exported from Qualcomm AI Hub, executed on the Hexagon NPU. It shells out to
  ``genie-t2t-run`` with the bundle's ``genie_config.json``.
* ``OrtGenAIBackend`` — ONNX Runtime GenAI (``onnxruntime-genai``), which can
  use the QNN execution provider on Snapdragon or run on CPU elsewhere.

The model is asked to *extract*, never to infer. Whatever it returns is
validated with pydantic, normalised to the lexicon, grounded against the
transcript (``safety.ground_note``) and, on any failure, the pipeline falls
back to the deterministic rule engine.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..lexicon import DIAGNOSES, DRUGS
from ..models import Role, SoapNote, Transcript

SYSTEM_PROMPT = """You are a clinical documentation assistant for Indian outpatient clinics.
Extract ONLY facts explicitly stated in the consultation transcript. Never add a diagnosis,
drug, dose or test that was not said. The transcript may be in Hindi, Hinglish or English;
write the note in English. Speakers are labelled DOCTOR, PATIENT or CAREGIVER; keep track of
who reported each symptom. Return a single JSON object and nothing else, matching this schema:
{"symptoms":[{"name":str,"duration_days":number|null,"modifiers":[str],"reported_by":"patient"|"caregiver"}],
 "negatives":[str],
 "vitals":{"bp_systolic":int|null,"bp_diastolic":int|null,"temperature_f":number|null,"spo2":int|null,"pulse":int|null,"weight_kg":number|null,"glucose_mg_dl":int|null},
 "diagnoses":[{"name":str,"status":"suspected"|"provisional"|"confirmed"}],
 "medications":[{"drug":str (generic name),"dose":number|null,"unit":"mg"|"ml","frequency_per_day":int|null,"prn":bool,"duration_days":int|null}],
 "investigations":[str],"advice":[str],"follow_up_days":int|null}"""


def build_user_prompt(tx: Transcript) -> str:
    lines = [f"{u.speaker.value.upper()}: {u.text}" for u in tx.utterances if u.speaker != Role.UNKNOWN]
    return "Consultation transcript:\n" + "\n".join(lines) + "\n\nJSON:"


def llama3_chat(system: str, user: str) -> str:
    return (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        f"{system}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        f"{user}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def extract_json(text: str) -> dict:
    """Return the first balanced JSON object found in text."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("No JSON object in model output")


def _canonical_drug(name: str) -> str:
    n = name.strip().lower()
    for generic, forms in DRUGS.items():
        if n == generic or n in forms:
            return generic
    return n


def _canonical_dx(name: str) -> str:
    n = name.strip().lower()
    for canon, c in DIAGNOSES.items():
        if n == canon or n in c["terms"]:
            return canon
    return n


def note_from_llm_json(data: dict, engine: str) -> SoapNote:
    data = dict(data)
    for m in data.get("medications") or []:
        m["drug"] = _canonical_drug(m.get("drug", ""))
    for d in data.get("diagnoses") or []:
        d["name"] = _canonical_dx(d.get("name", ""))
        c = DIAGNOSES.get(d["name"])
        if c:
            d.setdefault("snomed", c["snomed"])
            d.setdefault("icd10", c["icd10"])
    data["vitals"] = {**(data.get("vitals") or {}), "source": "transcript"}
    data["generated_by"] = engine
    return SoapNote.model_validate(data)


@dataclass
class LLMResult:
    text: str
    seconds: float
    tokens: int | None = None

    @property
    def tokens_per_second(self) -> float | None:
        return self.tokens / self.seconds if self.tokens and self.seconds else None


class LLMBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def generate(self, prompt: str, max_tokens: int = 700) -> LLMResult: ...


class GenieBackend:
    """Llama 3.2 3B on the Hexagon NPU via Qualcomm Genie (AI Hub export)."""

    name = "genie-npu"

    def __init__(self, config: str | None = None, exe: str | None = None, timeout: int = 120):
        self.config = config or os.environ.get("SEHAT_GENIE_CONFIG", "")
        self.exe = exe or os.environ.get("SEHAT_GENIE_EXE", "genie-t2t-run")
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.config) and Path(self.config).is_file() and shutil.which(self.exe) is not None

    def generate(self, prompt: str, max_tokens: int = 700) -> LLMResult:
        t0 = time.perf_counter()
        proc = subprocess.run(
            [self.exe, "-c", self.config, "-p", prompt],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout,
            cwd=str(Path(self.config).parent),
        )
        dt = time.perf_counter() - t0
        if proc.returncode != 0:
            raise RuntimeError(f"genie-t2t-run failed: {proc.stderr.strip()[:300]}")
        out = proc.stdout
        m = re.search(r"\[BEGIN\]:(.*?)(?:\[END\]|$)", out, re.S)
        return LLMResult(text=(m.group(1) if m else out).strip(), seconds=dt)


class OrtGenAIBackend:
    """ONNX Runtime GenAI model folder (QNN EP on Snapdragon, CPU elsewhere)."""

    name = "ort-genai"

    def __init__(self, model_dir: str | None = None):
        self.model_dir = model_dir or os.environ.get("SEHAT_ORT_MODEL_DIR", "")
        self._model = None
        self._tok = None

    def available(self) -> bool:
        if not self.model_dir or not Path(self.model_dir).is_dir():
            return False
        try:
            import onnxruntime_genai  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        import onnxruntime_genai as og

        if self._model is None:
            self._model = og.Model(self.model_dir)
            self._tok = og.Tokenizer(self._model)
        return og

    def generate(self, prompt: str, max_tokens: int = 700) -> LLMResult:
        og = self._load()
        ids = self._tok.encode(prompt)
        params = og.GeneratorParams(self._model)
        params.set_search_options(max_length=len(ids) + max_tokens, do_sample=False)
        gen = og.Generator(self._model, params)
        gen.append_tokens(ids)
        t0 = time.perf_counter()
        n = 0
        while not gen.is_done():
            gen.generate_next_token()
            n += 1
        dt = time.perf_counter() - t0
        new_tokens = gen.get_sequence(0)[len(ids) :]
        return LLMResult(text=self._tok.decode(new_tokens), seconds=dt, tokens=n)


def get_backend(name: str) -> LLMBackend | None:
    if name == "genie":
        return GenieBackend()
    if name == "ort-genai":
        return OrtGenAIBackend()
    return None


def draft_with_llm(tx: Transcript, backend: LLMBackend) -> tuple[SoapNote, LLMResult]:
    prompt = llama3_chat(SYSTEM_PROMPT, build_user_prompt(tx))
    result = backend.generate(prompt)
    note = note_from_llm_json(extract_json(result.text), engine=backend.name)
    return note, result
