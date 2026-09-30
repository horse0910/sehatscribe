# Architecture

```
            ┌──────────────── HP AI PC (Snapdragon X series) ────────────────┐
 mic ──► │ Browser UI ──► FastAPI (127.0.0.1)                              │
            │                   │                                             │
 UNO Q ───► │  /api/devices/vitals (token)                                  │
 vitals pod │                   ▼                                             │
            │  1 Capture ─► 2 ASR ─► 3 Speaker roles ─► 4 Drafting ─► 5 Safety │
            │   (temp file,   faster-whisper   labels / rule     Genie Llama     grounding +
            │    deleted)     (CPU) → NPU      classifier        3.2 3B (NPU)    dose rules
            │                                                    ORT GenAI
            │                                                    rules engine
            │                   ▼                                             │
            │  6 Doctor review & PIN sign-off ─► 7 FHIR R4 bundle / summary  │
            │                   ▼                                             │
            │        Encrypted SQLite (Fernet) + audit log                    │
            └────────────────────────────────────────────────────────────────┘
```

## Modules

| Module | Responsibility |
|---|---|
| `speakers.py` | Parses labelled transcripts; classifies unlabelled utterances as doctor / patient / caregiver |
| `asr.py` | Speech-to-text interface; `faster-whisper` backend; NPU backend slot |
| `lexicon.py` | Hindi / Hinglish / English clinical vocabulary, number words, SNOMED CT & ICD-10 codes |
| `extract/rules.py` | Deterministic SOAP extraction (symptoms + negation + duration, vitals, diagnoses with status, orders) |
| `extract/llm.py` | Extract-only prompt, Genie (NPU) and ONNX Runtime GenAI backends, JSON recovery and normalisation |
| `safety.py` | Grounding filter and dose / condition rules (`data/safety_rules.json`) |
| `pipeline.py` | Orchestration, engine fallback, device-vitals merge, timings |
| `fhir.py` | FHIR R4 `document` bundle modelled on ABDM OPConsultRecord |
| `summary.py` | Patient summary in Hindi / English |
| `store.py` | Encrypted persistence, doctor PINs (PBKDF2), audit log |
| `api.py` | Local REST API and static web UI |
| `edge/` | Arduino UNO Q vitals pod (MCU sketch + Linux app) and a simulator |

## Design decisions

- **Extraction, not generation.** The model may only restate what was said. `ground_note` removes any drug, test or diagnosis that is not in the transcript, which bounds hallucination regardless of model quality.
- **Rule engine as the floor.** Every machine gets a working, explainable scribe; the NPU makes it better, it is never required.
- **Measured numbers win.** Vitals are taken from regex over the transcript or from the device pod, never from the LLM.
- **Doctor in control.** Flags inform, they do not block; only signed notes export; signed notes are immutable.
- **Privacy by construction.** Local-only server, consent gate, audio never written beyond a temp file, encryption at rest, audit trail.

## Data flow for one consultation

1. `POST /api/encounters` (consent required) →
2. `POST /transcript` or `/audio` →
3. `POST /draft` → note + flags + engine + timings →
4. `PUT /note` (edits, re-check) →
5. `POST /sign` (doctor ID + PIN) →
6. `GET /fhir` and `GET /summary?lang=hi`
