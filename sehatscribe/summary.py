"""Patient-facing summary in the patient's language.

MVP ships English and Hindi templates. Other Indian languages are planned via
IndicTrans2 running on the NPU; templates keep the output deterministic and
reviewable in the meantime.
"""

from __future__ import annotations

from .models import SoapNote

HI = {
    "symptoms": {
        "fever": "बुखार", "headache": "सिर दर्द", "cough": "खांसी", "runny nose": "जुकाम", "sore throat": "गले में दर्द",
        "body ache": "बदन दर्द", "vomiting": "उल्टी", "diarrhoea": "दस्त", "abdominal pain": "पेट दर्द",
        "breathlessness": "सांस फूलना", "chest pain": "सीने में दर्द", "weakness": "कमज़ोरी", "dizziness": "चक्कर",
        "burning urination": "पेशाब में जलन", "frequent urination": "बार-बार पेशाब", "excessive thirst": "ज़्यादा प्यास",
        "rash": "दाने", "itching": "खुजली", "retro-orbital pain": "आंखों के पीछे दर्द",
    },
    "drugs": {
        "paracetamol": "पैरासिटामोल", "ibuprofen": "आइबुप्रोफेन", "diclofenac": "डाइक्लोफेनाक", "amoxicillin": "एमोक्सिसिलिन",
        "azithromycin": "एज़िथ्रोमाइसिन", "metformin": "मेटफॉर्मिन", "amlodipine": "एम्लोडिपीन", "cetirizine": "सेट्रिज़िन",
        "ondansetron": "ओंडानसेट्रॉन", "pantoprazole": "पैंटोप्राज़ोल", "ors": "ओआरएस घोल",
    },
    "freq": {1: "दिन में 1 बार", 2: "दिन में 2 बार", 3: "दिन में 3 बार", 4: "दिन में 4 बार"},
    "tests": {
        "Malaria rapid diagnostic test": "मलेरिया की जांच", "Complete blood count": "खून की पूरी जांच (CBC)",
        "Dengue NS1 antigen": "डेंगू की जांच (NS1)", "Widal test": "टाइफाइड की जांच (विडाल)", "HbA1c": "3 महीने की शुगर जांच (HbA1c)",
        "Urine routine": "पेशाब की जांच", "Blood glucose": "शुगर की जांच", "Chest X-ray": "छाती का एक्स-रे",
    },
    "advice": {
        "Increase oral fluids": "पानी और तरल ज़्यादा पिएं", "Rest": "आराम करें", "Reduce salt intake": "नमक कम खाएं",
        "Reduce sugar intake": "मीठा कम खाएं", "Daily brisk walk": "रोज़ तेज़ चलें", "Sponge the body for high fever": "तेज़ बुखार में गीली पट्टी करें",
    },
}

EN_FREQ = {1: "once a day", 2: "twice a day", 3: "three times a day", 4: "four times a day"}


def _med_line_en(m) -> str:
    parts = [m.drug.title()]
    if m.dose:
        parts.append(f"{m.dose:g} {m.unit}")
    parts.append("only when needed" if m.prn else EN_FREQ.get(m.frequency_per_day or 0, ""))
    if m.duration_days:
        parts.append(f"for {m.duration_days} days")
    return " ".join(p for p in parts if p)


def _med_line_hi(m) -> str:
    parts = [HI["drugs"].get(m.drug, m.drug)]
    if m.dose:
        parts.append(f"{m.dose:g} {m.unit}")
    parts.append("ज़रूरत होने पर ही" if m.prn else HI["freq"].get(m.frequency_per_day or 0, ""))
    if m.duration_days:
        parts.append(f"{m.duration_days} दिन तक")
    return " ".join(p for p in parts if p)


def patient_summary(note: SoapNote, language: str = "hi") -> dict:
    if language == "hi":
        lines = []
        if note.symptoms:
            lines.append("आपकी तकलीफ़: " + ", ".join(HI["symptoms"].get(s.name, s.name) for s in note.symptoms) + "।")
        if note.medications:
            lines.append("दवाइयाँ:")
            lines += [f"• {_med_line_hi(m)}" for m in note.medications]
        if note.investigations:
            lines.append("जांच: " + ", ".join(HI["tests"].get(t, t) for t in note.investigations) + "।")
        if note.advice:
            lines.append("सलाह: " + ", ".join(HI["advice"].get(a, a) for a in note.advice) + "।")
        if note.follow_up_days:
            lines.append(f"{note.follow_up_days} दिन बाद दोबारा दिखाएं।")
        lines.append("तबीयत ज़्यादा बिगड़े तो तुरंत अस्पताल आएं।")
        return {"language": "hi", "lines": lines}

    lines = []
    if note.symptoms:
        lines.append("Your complaints: " + ", ".join(s.name for s in note.symptoms) + ".")
    if note.medications:
        lines.append("Medicines:")
        lines += [f"• {_med_line_en(m)}" for m in note.medications]
    if note.investigations:
        lines.append("Tests: " + ", ".join(note.investigations) + ".")
    if note.advice:
        lines.append("Advice: " + ", ".join(a.lower() for a in note.advice) + ".")
    if note.follow_up_days:
        lines.append(f"Come back after {note.follow_up_days} days.")
    lines.append("If you feel worse, come to the hospital immediately.")
    return {"language": "en", "lines": lines}
