# SehatScribe — Product Brief

**Offline, multilingual AI clinical scribe for India's outpatient departments, built for Snapdragon®-powered HP AI PCs.**

| | |
|---|---|
| **Version** | MVP v0.1 (Snapdragon AI Lab Build & Present Challenge) |
| **Owner** | Harsh Agrawal, MBA, IIM Sirmaur |
| **Status** | MVP built; clinical pilot not yet started |
| **Last updated** | September 2026 |

---

## 1. Problem

Primary-care consultations in India average about **2 minutes** (BMJ Open, 2017), and clinicians in government OPDs often handle **200+ visits a day**. In that window the doctor must take a history (often from a family member speaking for the patient), examine, decide, prescribe and write it all down, usually by hand.

The consequences:

- **Lost information.** Caregiver input, pertinent negatives and vitals are skipped or scribbled.
- **Unusable records.** Handwritten slips are illegible and never reach the patient's ABHA health record, despite ABDM rails being in place (94 crore+ ABHA IDs, 2.72 lakh facilities on ABDM-enabled software, July 2026).
- **No safety net.** No dose-range or contraindication check at the point of prescribing.
- **Cloud AI scribes don't fit.** They need reliable internet, send patient voice off-site (a growing liability as DPDP Act obligations take full effect in May 2027), and are English-first.

## 2. Solution

SehatScribe listens to the consultation, separates the doctor, patient and caregiver, and drafts a structured **SOAP note** with a **prescription, investigations, advice and follow-up**. It checks doses against rules, lets the doctor edit and sign, then exports a **FHIR R4 record** for ABHA and prints or reads out a **patient summary in their own language**.

Everything runs **on the device**. The heavy models (speech-to-text, the clinical LLM) are targeted at the **Hexagon NPU** of Snapdragon X-series HP PCs, so it works offline, on battery, all shift, and patient audio never leaves the machine.

## 3. Users

| Persona | Role | Needs |
|---|---|---|
| **Dr. Meera** (primary) | Medical Officer at a PHC, 120–150 patients/day, Hindi/Awadhi | Hands-free notes, local language, zero setup, works offline |
| **Ramesh + daughter** | Patient and caregiver | Understand the advice; a record they can carry via ABHA |
| **District health IT** | Deploys and supports | Easy install, no cloud dependency, DPDP-safe, auditable |

## 4. Goals and non-goals

**Goals (MVP)**
1. Turn a consult transcript or recording into a structured draft note in seconds, fully offline.
2. Handle Hindi/Hinglish, three-way (triadic) conversations and pertinent negatives.
3. Keep the doctor in control: nothing is final until they review and sign.
4. Produce a standards-based FHIR R4 bundle modelled on ABDM's OPConsult record.
5. Show a clear path to NPU acceleration on Snapdragon.

**Non-goals (MVP)**
- Diagnosis or treatment recommendation. SehatScribe **documents** what the clinician said; it does not suggest diagnoses.
- Live ABDM gateway integration (sandbox onboarding is a Phase 1 item).
- Full NRCES FHIR profile conformance, Windows Hello sign-off, IndicTrans2 translation (roadmap).

## 5. MVP scope

| Area | In MVP v0.1 | Next |
|---|---|---|
| **Input** | Pasted/uploaded transcript; audio upload or in-browser recording | Continuous ambient capture |
| **Speech-to-text** | `faster-whisper` on CPU (multilingual) | Whisper from Qualcomm AI Hub on the NPU via ONNX Runtime QNN EP |
| **Speakers** | Labelled transcripts + rule-based role classifier (doctor / patient / caregiver) | pyannote diarization on the NPU |
| **Note drafting** | Deterministic Hinglish rule engine (default); Llama 3.2 3B via **Qualcomm Genie** (NPU) or ONNX Runtime GenAI, with automatic fallback | Fine-tuned clinical extraction model |
| **Safety** | Grounding check (drops anything not said); dose-range and dengue/NSAID rules | Full Standard Treatment Guidelines rule set |
| **Output** | Editable SOAP note; FHIR R4 document bundle; Hindi/English patient summary | 10 Indian languages; print layout |
| **Vitals** | Device API + Arduino UNO Q reference app + simulator | Certified BP/SpO₂ sensors |
| **Privacy** | Consent gate; encrypted local store; audio never persisted; PIN sign-off; audit log | Windows Hello; DPAPI key storage |

## 6. Key user stories

1. *As a doctor,* I record or paste the consult and get a draft SOAP note so I can keep my eyes on the patient.
2. *As a doctor,* I see which statements came from the caregiver, so history isn't misattributed.
3. *As a doctor,* I'm warned when a dose exceeds the limit or a drug is risky for the suspected condition.
4. *As a doctor,* I edit and sign the note with my PIN; only signed notes export.
5. *As a patient,* I get my advice in Hindi.
6. *As a facility,* I export a FHIR bundle to push to the patient's ABHA record.
7. *As IT,* I confirm no audio is stored and every sign/export is logged.

## 7. Requirements

**Functional**
- F1 Consent must be recorded before any transcript is processed.
- F2 Extract symptoms (with duration and negation), vitals, suspected/confirmed diagnoses, medication orders (dose, frequency, duration), investigations, advice, follow-up.
- F3 Every extracted item must be traceable to the transcript (grounding).
- F4 Safety flags shown with severity; the doctor can still sign (the doctor decides).
- F5 Signed notes are immutable; edits after signing require a new version.
- F6 FHIR export only for signed notes.

**Non-functional**
- N1 Works with **no network**.
- N2 Patient audio is processed in memory/temp storage and deleted after transcription.
- N3 Stored records are encrypted at rest.
- N4 Targets on HP OmniBook X (Snapdragon X Elite): ASR real-time factor ≤ 0.2; LLM ≥ 15 tokens/s; consult end → draft ≤ 30 s. *(To be measured; see `scripts/benchmark.py`.)*

## 8. Success metrics (pilot)

| Metric | Target |
|---|---|
| Documentation time per patient | −70% vs baseline |
| SOAP fields completed | ≥ 90% |
| Doctor edits per note | ≤ 3 |
| Word error rate, Hindi | ≤ 20% |
| Notes pushed to ABHA | ≥ 80% of signed notes |

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| ASR errors (accents, noise) | Low-confidence highlighting; doctor review; consented fine-tuning |
| LLM hallucination | Extract-only prompt; grounding filter; rules fallback; mandatory sign-off |
| Medical-device regulation | Positioned as documentation aid, not diagnosis; early CDSCO consultation |
| Data breach on device | Encryption at rest, PIN sign-off, no audio retention, audit log |
| Clinician adoption | 10-minute onboarding; clinic champion model |

## 10. Release plan

| Phase | When | Scope |
|---|---|---|
| MVP v0.1 | Now | This repository |
| NPU build | +4 weeks | Whisper + Llama on Hexagon NPU; benchmarks on HP OmniBook |
| Pilot | Q1 2027 | 3 PHCs, 1 district |
| State | H2 2027 | 100 facilities, 10 languages |
| Scale | 2028 | 5,000 facilities |

## 11. Open questions

- Which state NHM will host the pilot, and can it provide ABDM sandbox credentials?
- Which BP/SpO₂ sensor modules are acceptable for the vitals pod in a clinical setting?
- Consent language and retention policy to be confirmed with a DPDP counsel.
