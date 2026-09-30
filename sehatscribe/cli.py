"""Command-line interface: `sehatscribe serve | demo | add-doctor | runtime`."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from .config import Settings


def _print_note(res) -> None:
    n = res.note
    print(f"\nEngine: {res.engine}   timings (ms): " + ", ".join(f"{k}={v:.1f}" for k, v in res.timings_ms.items()))
    print("\nS  Symptoms:")
    for s in n.symptoms:
        extra = [f"{s.duration_days:g} days" if s.duration_days else "", ", ".join(s.modifiers), f"per {s.reported_by.value}"]
        print(f"   - {s.name} ({'; '.join(e for e in extra if e)})")
    if n.negatives:
        print(f"   Denies: {', '.join(n.negatives)}")
    if n.home_medications:
        print("   Already taken: " + ", ".join(f"{h.drug} ({h.mentioned_as})" for h in n.home_medications))
    v = n.vitals.model_dump(exclude_none=True, exclude={"source"})
    print("O  Vitals: " + (", ".join(f"{k}={val}" for k, val in v.items()) or "none"))
    print("A  " + ("; ".join(f"{d.name} [{d.status.value}]" for d in n.diagnoses) or "No diagnosis stated"))
    print("P  Medications:")
    for m in n.medications:
        freq = "PRN" if m.prn else f"{m.frequency_per_day}x/day" if m.frequency_per_day else "?"
        print(f"   - {m.drug} {m.dose:g} {m.unit} {freq} x {m.duration_days or '?'} days" if m.dose else f"   - {m.drug} (dose?)")
    if n.investigations:
        print("   Investigations: " + ", ".join(n.investigations))
    if n.advice:
        print("   Advice: " + ", ".join(n.advice))
    if n.follow_up_days:
        print(f"   Follow-up: {n.follow_up_days} days")
    if res.flags:
        print("\nSafety flags:")
        for f in res.flags:
            print(f"   [{f.severity.value.upper()}] {f.message}")


def cmd_demo(args) -> int:
    from .fhir import build_bundle
    from .models import Consent, Encounter, EncounterStatus
    from .pipeline import draft_note
    from .speakers import parse_text_transcript
    from .summary import patient_summary

    settings = Settings()
    settings.llm_engine = args.engine
    tx = parse_text_transcript(Path(args.transcript).read_text(encoding="utf-8"))
    res = draft_note(tx, settings)
    _print_note(res)
    print("\nPatient summary (Hindi):")
    for line in patient_summary(res.note, "hi")["lines"]:
        print("   " + line)
    if args.fhir:
        enc = Encounter(id="demo", consent=Consent(given=True), transcript=tx, note=res.note,
                        status=EncounterStatus.SIGNED, signed_by="Demo Doctor")
        Path(args.fhir).write_text(json.dumps(build_bundle(enc), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nFHIR bundle written to {args.fhir}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .api import create_app

    print(f"SehatScribe running at http://{args.host}:{args.port}  (Ctrl+C to stop)")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_add_doctor(args) -> int:
    from .store import Store

    s = Settings()
    pin = getpass.getpass("PIN (4-12 digits): ")
    if pin != getpass.getpass("Repeat PIN: "):
        print("PINs do not match", file=sys.stderr)
        return 1
    Store(s.db_path, s.key_path).set_doctor_pin(args.doctor_id, args.name, pin)
    print(f"Doctor '{args.doctor_id}' saved in {s.data_dir}")
    return 0


def cmd_runtime(_args) -> int:
    from .runtime import runtime_report

    print(json.dumps(runtime_report(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows consoles often default to a legacy code page that cannot print Hindi.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="sehatscribe", description="Offline AI clinical scribe for Snapdragon PCs")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Run the local web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_serve)

    d = sub.add_parser("demo", help="Draft a note from a transcript file")
    d.add_argument("transcript")
    d.add_argument("--engine", default="auto", choices=["auto", "rules", "genie", "ort-genai"])
    d.add_argument("--fhir", help="Write the FHIR bundle to this path")
    d.set_defaults(func=cmd_demo)

    a = sub.add_parser("add-doctor", help="Create or reset a doctor's signing PIN")
    a.add_argument("doctor_id")
    a.add_argument("--name", required=True)
    a.set_defaults(func=cmd_add_doctor)

    r = sub.add_parser("runtime", help="Show NPU / engine availability")
    r.set_defaults(func=cmd_runtime)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
