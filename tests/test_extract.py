from sehatscribe.extract import extract_note
from sehatscribe.models import DxStatus, Role
from sehatscribe.speakers import classify_role, parse_text_transcript


def names(items):
    return {i.name for i in items}


def test_fever_subjective(fever_tx):
    n = extract_note(fever_tx)
    assert names(n.symptoms) == {"fever", "headache", "body ache"}
    fever = next(s for s in n.symptoms if s.name == "fever")
    assert fever.duration_days == 3
    assert fever.reported_by == Role.CAREGIVER  # daughter spoke for the patient
    assert "worse at night" in fever.modifiers
    assert set(n.negatives) == {"vomiting", "diarrhoea"}
    assert [h.drug for h in n.home_medications] == ["paracetamol"]


def test_fever_objective_assessment_plan(fever_tx):
    n = extract_note(fever_tx)
    v = n.vitals
    assert (v.bp_systolic, v.bp_diastolic, v.temperature_f, v.spo2) == (128, 84, 101.2, 97)
    status = {d.name: d.status for d in n.diagnoses}
    assert status == {"viral fever": DxStatus.PROVISIONAL, "malaria": DxStatus.SUSPECTED, "dengue": DxStatus.SUSPECTED}
    assert len(n.medications) == 1
    m = n.medications[0]
    assert (m.drug, m.dose, m.frequency_per_day, m.duration_days) == ("paracetamol", 650, 3, 3)
    assert n.investigations == ["Malaria rapid diagnostic test", "Complete blood count"]
    assert n.advice == ["Increase oral fluids", "Rest"]
    assert n.follow_up_days == 2


def test_diabetes_shared_duration_and_glucose(diabetes_tx):
    n = extract_note(diabetes_tx)
    meds = {m.drug: m for m in n.medications}
    assert meds["metformin"].frequency_per_day == 2 and meds["metformin"].duration_days == 30
    assert meds["amlodipine"].frequency_per_day == 1 and meds["amlodipine"].duration_days == 30
    assert n.vitals.glucose_mg_dl == 168 and n.vitals.glucose_context == "fasting"
    assert all(s.duration_days == 60 for s in n.symptoms)  # "Do mahine se" answers the doctor's question
    assert {d.status for d in n.diagnoses} == {DxStatus.CONFIRMED}
    assert n.follow_up_days == 30


def test_unlabelled_roles_are_inferred(dengue_tx):
    roles = [u.speaker for u in dengue_tx.utterances]
    assert roles[0] == Role.DOCTOR and roles[1] == Role.PATIENT
    assert all(u.role_inferred for u in dengue_tx.utterances)
    n = extract_note(dengue_tx)
    assert "rash" in names(n.symptoms)  # confirmed by "Haan" answer
    assert "retro-orbital pain" in names(n.symptoms)


def test_classifier_detects_caregiver():
    assert classify_role("Inko raat ko bukhar aata hai") == Role.CAREGIVER
    assert classify_role("Kitne din se hai?") == Role.DOCTOR
    assert classify_role("Mujhe khansi hai") == Role.PATIENT


def test_devanagari_and_units():
    tx = parse_text_transcript("मरीज़: तीन दिन से बुखार है\nDOCTOR: Temperature 38.5, paracetamol 500 mg bd x 5 days")
    n = extract_note(tx)
    assert n.symptoms[0].name == "fever" and n.symptoms[0].duration_days == 3
    assert n.vitals.temperature_f == 101.3  # 38.5 °C converted
    m = n.medications[0]
    assert (m.dose, m.frequency_per_day, m.duration_days) == (500, 2, 5)


def test_drug_mentioned_without_dosing_is_not_an_order():
    tx = parse_text_transcript("DOCTOR: Crocin li thi kya?\nPATIENT: Haan")
    assert extract_note(tx).medications == []
