import json

from sehatscribe.extract import extract_note
from sehatscribe.extract.llm import extract_json, note_from_llm_json
from sehatscribe.models import MedicationOrder, Severity
from sehatscribe.pipeline import draft_note
from sehatscribe.safety import check_note, ground_note


def codes(flags):
    return {f.code for f in flags}


def test_nsaid_in_suspected_dengue_is_critical(dengue_tx):
    flags = check_note(extract_note(dengue_tx))
    crit = [f for f in flags if f.code == "NSAID_IN_DENGUE"]
    assert crit and crit[0].severity == Severity.CRITICAL


def test_dose_limits(fever_tx):
    n = extract_note(fever_tx)
    n.medications = [MedicationOrder(drug="paracetamol", dose=1500, frequency_per_day=4, duration_days=3)]
    assert {"SINGLE_DOSE_HIGH", "DAILY_DOSE_HIGH"} <= codes(check_note(n))


def test_missing_fields_flagged(fever_tx):
    n = extract_note(fever_tx)
    n.medications = [MedicationOrder(drug="amoxicillin")]
    assert {"MISSING_DOSE", "MISSING_FREQUENCY", "MISSING_DURATION"} <= codes(check_note(n))


def test_clean_note_has_no_flags(fever_tx):
    assert check_note(extract_note(fever_tx)) == []


def test_grounding_removes_hallucinations(fever_tx):
    n = extract_note(fever_tx)
    n.medications.append(MedicationOrder(drug="azithromycin", dose=500, frequency_per_day=1, duration_days=3))
    n.investigations.append("Chest X-ray")
    grounded, flags = ground_note(n, fever_tx)
    assert [m.drug for m in grounded.medications] == ["paracetamol"]
    assert "Chest X-ray" not in grounded.investigations
    assert {"UNGROUNDED_DRUG", "UNGROUNDED_TEST"} <= codes(flags)


def test_extract_json_tolerates_chatter():
    text = 'Sure! Here is the note:\n```json\n{"a": {"b": "x}y"}, "c": [1]}\n```\nDone.'
    assert extract_json(text) == {"a": {"b": "x}y"}, "c": [1]}


class FakeLLM:
    """Stands in for Llama on the NPU and hallucinates one drug."""

    name = "fake-npu"

    def available(self):
        return True

    def generate(self, prompt, max_tokens=700):
        from sehatscribe.extract.llm import LLMResult

        data = {
            "symptoms": [{"name": "fever", "duration_days": 3, "modifiers": [], "reported_by": "caregiver"}],
            "negatives": ["vomiting"],
            "vitals": {"bp_systolic": 120, "bp_diastolic": 80},
            "diagnoses": [{"name": "Malaria", "status": "suspected"}],
            "medications": [
                {"drug": "Crocin", "dose": 650, "unit": "mg", "frequency_per_day": 3, "prn": False, "duration_days": 3},
                {"drug": "Azithromycin", "dose": 500, "unit": "mg", "frequency_per_day": 1, "prn": False, "duration_days": 3},
            ],
            "investigations": ["Complete blood count"],
            "advice": ["Rest"],
            "follow_up_days": 2,
        }
        return LLMResult(text="[BEGIN]: " + json.dumps(data), seconds=1.0, tokens=200)


def test_llm_path_is_normalised_grounded_and_uses_measured_vitals(fever_tx, settings, monkeypatch):
    import sehatscribe.pipeline as pipeline

    monkeypatch.setattr(pipeline, "get_backend", lambda name: FakeLLM())
    settings.llm_engine = "auto"
    res = draft_note(fever_tx, settings)
    assert res.engine == "fake-npu" and res.llm_tokens_per_s == 200
    assert [m.drug for m in res.note.medications] == ["paracetamol"]  # brand normalised, hallucination dropped
    assert "UNGROUNDED_DRUG" in codes(res.flags)
    assert res.note.diagnoses[0].icd10 == "B54"
    assert res.note.vitals.bp_systolic == 128  # transcript numbers win over the model's


def test_llm_failure_falls_back_to_rules(fever_tx, settings, monkeypatch):
    import sehatscribe.pipeline as pipeline

    class Broken(FakeLLM):
        def generate(self, prompt, max_tokens=700):
            raise TimeoutError("npu busy")

    monkeypatch.setattr(pipeline, "get_backend", lambda name: Broken())
    settings.llm_engine = "genie"
    res = draft_note(fever_tx, settings)
    assert res.engine == "rules" and "LLM_FALLBACK" in codes(res.flags)


def test_note_from_llm_json_validates():
    n = note_from_llm_json({"medications": [{"drug": "Dolo", "dose": 650}]}, engine="x")
    assert n.medications[0].drug == "paracetamol"
