"""Benchmark the SehatScribe pipeline on this machine.

    python scripts/benchmark.py                  # rule engine on the sample consults
    python scripts/benchmark.py --engine genie   # Llama 3.2 3B on the Hexagon NPU
    python scripts/benchmark.py --audio consult.wav

Prints a Markdown table you can paste into the submission's benchmark report.
Targets (HP OmniBook X, Snapdragon X Elite): ASR RTF <= 0.2, LLM >= 15 tok/s,
consult end -> draft <= 30 s.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sehatscribe.config import Settings  # noqa: E402
from sehatscribe.pipeline import draft_note  # noqa: E402
from sehatscribe.runtime import runtime_report  # noqa: E402
from sehatscribe.speakers import parse_text_transcript  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--engine", default="rules", choices=["rules", "auto", "genie", "ort-genai"])
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--audio", help="Also time speech-to-text on this file")
    args = p.parse_args()

    settings = Settings()
    settings.llm_engine = args.engine
    rt = runtime_report()
    print(f"Platform: {rt['platform']} | arm64={rt['arm64']} | QNN NPU={rt['qnn_npu_available']}\n")
    print("| Sample | Engine | Median draft (ms) | LLM tok/s | Flags |")
    print("|---|---|---|---|---|")
    for sample in sorted((ROOT / "samples").glob("*.txt")):
        tx = parse_text_transcript(sample.read_text(encoding="utf-8"))
        times, res = [], None
        for _ in range(args.runs):
            t0 = time.perf_counter()
            res = draft_note(tx, settings)
            times.append((time.perf_counter() - t0) * 1000)
        tps = f"{res.llm_tokens_per_s:.1f}" if res.llm_tokens_per_s else "–"
        print(f"| {sample.stem} | {res.engine} | {statistics.median(times):.1f} | {tps} | {len(res.flags)} |")

    if args.audio:
        from sehatscribe.asr import get_asr_backend

        backend = get_asr_backend()
        if backend is None:
            print("\nNo ASR engine installed (pip install -r requirements-asr.txt)")
            return
        r = backend.transcribe(args.audio)
        print(f"\nASR {backend.name}: audio {r.audio_seconds:.1f}s, wall {r.wall_seconds:.1f}s, RTF {r.real_time_factor:.2f}")


if __name__ == "__main__":
    main()
