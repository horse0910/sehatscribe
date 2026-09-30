# Running SehatScribe's AI on the Snapdragon NPU

SehatScribe runs everywhere with its rule engine. On a Snapdragon X-series HP PC
you can move the clinical LLM onto the **Hexagon NPU**. The app picks it up
automatically (`SEHAT_LLM=auto` tries Genie → ONNX Runtime GenAI → rules).

> These steps follow Qualcomm's public tooling. Tool names and flags change
> between releases, so check the linked pages for the current versions.

## Option A — Llama 3.2 3B via Qualcomm Genie (recommended)

1. **Install the Qualcomm AI Runtime (QAIRT) SDK** on the Windows on Snapdragon PC.
   It provides `genie-t2t-run.exe`. Add its `bin\aarch64-windows-msvc` folder to `PATH`.
2. **Export the model from Qualcomm AI Hub** (needs a free AI Hub account and
   acceptance of the Llama 3.2 licence). Follow the *LLM on Genie* tutorial:
   <https://github.com/quic/ai-hub-apps/tree/main/tutorials/llm_on_genie>.
   Choose `llama_v3_2_3b_instruct` and the Snapdragon X Elite / X Plus chipset.
   The tutorial produces a bundle folder with context binaries, the tokenizer
   and a `genie_config.json`.
3. **Point SehatScribe at the bundle**:

   ```powershell
   $env:SEHAT_GENIE_CONFIG = "C:\models\genie_bundle\genie_config.json"
   sehatscribe runtime      # "llm_genie_npu": true
   sehatscribe serve
   ```

4. **Measure** with `python scripts/benchmark.py --engine genie` and record the
   tokens/s and draft time in your submission.

## Option B — ONNX Runtime GenAI

1. `pip install -r requirements-npu.txt` (ARM64 Python on Windows).
2. Place an ONNX Runtime GenAI model folder (for example a Llama 3.2 3B or
   Phi-3.5-mini build configured for the QNN execution provider) on disk.
3. `set SEHAT_ORT_MODEL_DIR=C:\models\llama-3.2-3b-ort` and restart the app.

## Speech-to-text

v0.1 transcribes on the CPU with `faster-whisper`
(`pip install -r requirements-asr.txt`; choose the size with
`SEHAT_WHISPER_MODEL=small|medium`). Moving Whisper to the NPU (AI Hub export +
ONNX Runtime QNN EP) is the next milestone. The `ASRBackend` interface in
`sehatscribe/asr.py` is the integration point.

## Safety whatever the engine

LLM output is always normalised, grounded against the transcript (anything not
spoken is removed and flagged) and dose-checked. If the model errors or returns
invalid JSON, SehatScribe falls back to the rule engine and tells the doctor.
