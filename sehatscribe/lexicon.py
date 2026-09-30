"""Clinical lexicon for Hindi, Hinglish (romanised Hindi) and English.

Each concept maps spoken variants to a canonical English name and, where we
have one, a SNOMED CT / ICD-10 code. Codes are provided for interoperability
and must be validated against the SNOMED CT India release before clinical use.
"""

from __future__ import annotations

import re
from functools import lru_cache

# --------------------------------------------------------------------------- #
# Matching helpers
# --------------------------------------------------------------------------- #

# \b does not work reliably with Devanagari (matras are not \w), so we define
# our own boundary: not preceded/followed by a Latin word char or Devanagari.
_B_BEFORE = r"(?<![\wऀ-ॿ])"
_B_AFTER = r"(?![\wऀ-ॿ])"


@lru_cache(maxsize=2048)
def term_pattern(term: str) -> re.Pattern[str]:
    parts = [re.escape(p) for p in term.split()]
    return re.compile(_B_BEFORE + r"\s+".join(parts) + _B_AFTER, re.IGNORECASE)


def find_terms(text: str, terms: list[str]) -> list[re.Match[str]]:
    hits: list[re.Match[str]] = []
    for t in terms:
        hits.extend(term_pattern(t).finditer(text))
    return hits


# --------------------------------------------------------------------------- #
# Numbers
# --------------------------------------------------------------------------- #

NUMBER_WORDS: dict[str, int] = {
    # Hinglish
    "ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "chhah": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "barah": 12, "pandrah": 15, "bees": 20,
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "fourteen": 14, "fifteen": 15, "twenty": 20,
    # Devanagari
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "सात": 7,
    "आठ": 8, "नौ": 9, "दस": 10,
}

NUM_RE = r"(\d+(?:\.\d+)?|" + "|".join(sorted(map(re.escape, NUMBER_WORDS), key=len, reverse=True)) + ")"


def to_number(token: str) -> float | None:
    token = token.strip().lower()
    if not token:
        return None
    try:
        return float(token)
    except ValueError:
        return NUMBER_WORDS.get(token)


UNIT_DAYS: dict[str, int] = {
    "din": 1, "dino": 1, "dinon": 1, "day": 1, "days": 1, "दिन": 1, "d": 1,
    "hafta": 7, "hafte": 7, "hafton": 7, "week": 7, "weeks": 7, "हफ्ते": 7, "हफ़्ते": 7,
    "mahina": 30, "mahine": 30, "mahino": 30, "month": 30, "months": 30, "महीने": 30,
    "saal": 365, "year": 365, "years": 365, "साल": 365,
}
UNIT_RE = "(" + "|".join(sorted(map(re.escape, UNIT_DAYS), key=len, reverse=True)) + ")"
DURATION_RE = re.compile(_B_BEFORE + NUM_RE + r"\s*" + UNIT_RE + _B_AFTER, re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Concepts
# --------------------------------------------------------------------------- #

SYMPTOMS: dict[str, dict] = {
    "fever": {"snomed": "386661006", "terms": ["bukhar", "bukhaar", "tez bukhar", "fever", "jwar", "बुखार", "ज्वर"]},
    "headache": {"snomed": "25064002", "terms": ["sar dard", "sir dard", "sar mein dard", "sir mein dard", "headache", "सिर दर्द", "सर दर्द", "सिर में दर्द"]},
    "cough": {"snomed": "49727002", "terms": ["khansi", "khaansi", "cough", "खांसी", "खाँसी"]},
    "runny nose": {"snomed": "64531003", "terms": ["zukam", "jukam", "naak beh", "runny nose", "जुकाम"]},
    "sore throat": {"snomed": "162397003", "terms": ["gale mein dard", "gala kharab", "sore throat", "गले में दर्द"]},
    "body ache": {"snomed": "68962001", "terms": ["badan dard", "body pain", "bodyache", "body ache", "बदन दर्द"]},
    "vomiting": {"snomed": "422400008", "terms": ["ulti", "ultiyan", "vomiting", "vomit", "उल्टी"]},
    "diarrhoea": {"snomed": "62315008", "terms": ["dast", "loose motion", "loose motions", "diarrhoea", "diarrhea", "दस्त"]},
    "abdominal pain": {"snomed": "21522001", "terms": ["pet dard", "pet mein dard", "stomach pain", "abdominal pain", "पेट दर्द", "पेट में दर्द"]},
    "breathlessness": {"snomed": "267036007", "terms": ["saans phoolna", "saans phool", "saans lene mein takleef", "breathless", "breathlessness", "सांस फूलना"]},
    "chest pain": {"snomed": "29857009", "terms": ["seene mein dard", "chhati mein dard", "chest pain", "सीने में दर्द"]},
    "weakness": {"snomed": "13791008", "terms": ["kamzori", "kamjori", "weakness", "कमज़ोरी", "कमजोरी"]},
    "dizziness": {"snomed": "404640003", "terms": ["chakkar", "dizziness", "dizzy", "चक्कर"]},
    "burning urination": {"snomed": "49650001", "terms": ["peshab mein jalan", "urine mein jalan", "burning urination", "पेशाब में जलन"]},
    "frequent urination": {"snomed": "28442001", "terms": ["baar baar peshab", "baar baar urine", "frequent urination", "बार बार पेशाब"]},
    "excessive thirst": {"snomed": "17173007", "terms": ["pyaas zyada", "zyada pyaas", "excessive thirst", "ज़्यादा प्यास"]},
    "rash": {"snomed": "271807003", "terms": ["daane", "dane", "rash", "chakte", "दाने"]},
    "itching": {"snomed": "418290006", "terms": ["khujli", "itching", "खुजली"]},
    "retro-orbital pain": {"snomed": None, "terms": ["aankhon ke peeche dard", "aankh ke peeche dard", "pain behind the eyes", "आंखों के पीछे दर्द"]},
}

MODIFIERS: dict[str, list[str]] = {
    "worse at night": ["raat ko zyada", "raat mein zyada", "worse at night", "रात को ज़्यादा"],
    "high grade": ["tez", "high grade", "तेज़"],
    "with chills": ["thand lag", "kapkapi", "chills", "ठंड लग"],
}

# "na" is deliberately excluded: it is a common Hindi tag particle ("hai na?").
NEGATION_TERMS = ["nahi", "nahin", "nai", "no", "not", "never", "नहीं"]
AFFIRMATION_TERMS = ["haan", "ha", "han", "ji haan", "yes", "हाँ", "हां"]

DIAGNOSES: dict[str, dict] = {
    "malaria": {"snomed": "61462000", "icd10": "B54", "terms": ["malaria", "मलेरिया"]},
    "dengue": {"snomed": "38362002", "icd10": "A90", "terms": ["dengue", "डेंगू"]},
    "typhoid fever": {"snomed": "4834000", "icd10": "A01.0", "terms": ["typhoid", "टाइफाइड"]},
    "viral fever": {"snomed": None, "icd10": None, "terms": ["viral fever", "viral bukhar", "वायरल"]},
    "urinary tract infection": {"snomed": "68566005", "icd10": "N39.0", "terms": ["uti", "urine infection", "peshab ka infection"]},
    "gastroenteritis": {"snomed": "25374005", "icd10": "A09", "terms": ["gastroenteritis", "pet ka infection"]},
    "pneumonia": {"snomed": "233604007", "icd10": "J18.9", "terms": ["pneumonia", "निमोनिया"]},
    "hypertension": {"snomed": "38341003", "icd10": "I10", "terms": ["hypertension", "high bp", "bp high", "उच्च रक्तचाप"]},
    "type 2 diabetes mellitus": {"snomed": "44054006", "icd10": "E11", "terms": ["diabetes", "sugar ki bimari", "madhumeh", "मधुमेह", "डायबिटीज"]},
    "upper respiratory tract infection": {"snomed": None, "icd10": "J06.9", "terms": ["urti", "gale ka infection", "throat infection"]},
}

DX_SUSPECTED_CUES = ["shak", "shaq", "suspect", "suspected", "rule out", "r/o", "ho sakta", "ho sakti", "possibility", "शक"]
DX_PROVISIONAL_CUES = ["lagta hai", "lag raha", "likely", "probably", "looks like", "लगता है"]
DX_CONFIRMED_CUES = ["confirmed", "diagnosed", "pakka", "report mein aaya", "positive"]

# Drugs: canonical generic -> spoken forms (generic + common Indian brands)
DRUGS: dict[str, list[str]] = {
    "paracetamol": ["paracetamol", "pcm", "crocin", "dolo", "calpol", "पैरासिटामोल"],
    "ibuprofen": ["ibuprofen", "brufen", "combiflam"],
    "diclofenac": ["diclofenac", "voveran"],
    "amoxicillin": ["amoxicillin", "amoxycillin", "mox", "novamox"],
    "azithromycin": ["azithromycin", "azithral", "azee"],
    "metformin": ["metformin", "glycomet"],
    "amlodipine": ["amlodipine", "amlong", "amlodac"],
    "cetirizine": ["cetirizine", "cetzine", "okacet"],
    "ondansetron": ["ondansetron", "emeset", "vomikind"],
    "pantoprazole": ["pantoprazole", "pan 40", "pantocid"],
    "ors": ["ors", "electral"],
}

INVESTIGATIONS: dict[str, list[str]] = {
    "Malaria rapid diagnostic test": ["malaria test", "malaria rdt", "mp test", "malaria ki jaanch", "मलेरिया जांच"],
    "Complete blood count": ["cbc", "blood count", "khoon ki jaanch"],
    "Dengue NS1 antigen": ["ns1", "dengue test"],
    "Widal test": ["widal"],
    "HbA1c": ["hba1c", "a1c"],
    "Urine routine": ["urine test", "urine routine", "peshab ki jaanch"],
    "Blood glucose": ["sugar test", "blood sugar test", "glucose test"],
    "Chest X-ray": ["x-ray", "xray", "x ray"],
}

ADVICE: dict[str, list[str]] = {
    "Increase oral fluids": ["paani zyada", "zyada paani", "fluids", "पानी ज़्यादा"],
    "Rest": ["aaram", "aram", "rest", "आराम"],
    "Reduce salt intake": ["namak kam", "less salt"],
    "Reduce sugar intake": ["cheeni kam", "meetha kam", "less sugar"],
    "Daily brisk walk": ["walk", "tahalna", "tehelna", "exercise"],
    "Sponge the body for high fever": ["geeli patti", "sponging", "sponge"],
}

# Frequency: ordered — first match wins
FREQUENCY_PATTERNS: list[tuple[str, int | None, bool]] = [
    (r"(?:din|दिन)\s+(?:mein|में)\s+" + NUM_RE + r"\s+(?:baar|बार)", -1, False),  # -1 = take the number
    (NUM_RE + r"\s+(?:baar|times)\s+(?:a\s+day|daily|roz|din)", -1, False),
    (r"\bqid\b|\bfour times\b", 4, False),
    (r"\btds\b|\btid\b|\bthrice\b|\bthree times\b", 3, False),
    (r"\bbd\b|\bbid\b|\btwice\b", 2, False),
    (r"\bod\b|\bonce\b|\bonce daily\b|\bhs\b|raat ko ek|sone se pehle", 1, False),
    (r"\bsos\b|zarurat|zaroorat|if needed|as needed|\bprn\b", None, True),
]

DOCTOR_CUES = [
    "dijiye", "lijiye", "khaiye", "karwaiye", "karaiye", "karvaiye", "aaiye", "aana", "pijiye", "kijiye",
    "dekhte hain", "check karte", "bataiye", "batao", "tablet", "mg", "test", "jaanch",
    "lagta hai", "shak", "prescribe", "take", "khana hai", "lena hai",
]
QUESTION_WORDS = ["kab", "kya", "kitne", "kitna", "kaise", "kahan", "kaun", "koi", "when", "what", "how", "any"]
CAREGIVER_CUES = [
    "inko", "inhe", "inhein", "unko", "unhe", "inki", "unki", "iski", "iska", "isko",
    "papa", "mummy", "mummi", "dadi", "dada", "nani", "nana", "beta", "beti", "bachche", "bachcha",
    "mere pati", "meri patni", "husband", "wife", "father", "mother", "my son", "my daughter",
    "ghar pe", "humne",
]
SPEAKER_LABELS: dict[str, str] = {
    # label -> role
    "doctor": "doctor", "dr": "doctor", "d": "doctor", "physician": "doctor", "डॉक्टर": "doctor",
    "patient": "patient", "pt": "patient", "p": "patient", "मरीज": "patient", "मरीज़": "patient",
    "caregiver": "caregiver", "cg": "caregiver", "attendant": "caregiver", "relative": "caregiver",
    "daughter": "caregiver", "son": "caregiver", "wife": "caregiver", "husband": "caregiver",
    "mother": "caregiver", "father": "caregiver", "beti": "caregiver", "beta": "caregiver",
}
