#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cli.py — command-line entry point for the lean subtitle review pipeline.

Examples:
    python cli.py translate "CH 05 _EP 11.sbv" --out-dir out_v4_1_lean
    python cli.py validate-workbook "CH 05 _EP 11.sbv" out_v4_1_lean/CH_05__EP_11_master_review.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

import pipeline


def cmd_translate(args: argparse.Namespace) -> None:
    source = Path(args.source)
    skill_text = pipeline.load_skill_text(Path(args.skill) if args.skill else None)
    artifacts = pipeline.translate_to_files(
        source_text=source.read_text(encoding="utf-8-sig"),
        source_name=source.name,
        out_dir=Path(args.out_dir),
        skill_text=skill_text,
        model=args.model,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        progress=lambda msg: print(msg),
    )
    print("\nDONE")
    print(f"Discourse brief: {artifacts['brief']}")
    print(f"Master review workbook: {artifacts['workbook']}")
    print(f"Raw JSON: {artifacts['raw']}")


def cmd_validate_workbook(args: argparse.Namespace) -> None:
    cues = pipeline.parse_source(Path(args.source))
    df = pd.read_excel(args.workbook)

    ok = True
    if len(df) != len(cues):
        print(f"FAIL cue count: workbook {len(df)} vs source {len(cues)}")
        ok = False

    for cue in cues:
        row = df[df["Cue Number"] == cue.number]
        if row.empty:
            print(f"FAIL missing cue {cue.number}")
            ok = False
            continue
        row = row.iloc[0]
        if str(row["Timecode"]).strip() != cue.timecode:
            print(f"FAIL timecode mismatch cue {cue.number}")
            ok = False
        if str(row["Telugu Cue"]).strip() != cue.telugu.strip():
            print(f"WARN Telugu text differs cue {cue.number}")

    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lean one-pass Telugu subtitle review workbook automation (Azure OpenAI)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("translate", help="Create review workbook from Telugu SBV/SRT")
    p.add_argument("source")
    p.add_argument("--out-dir", default="out_v4_1_lean")
    p.add_argument("--skill", default=pipeline.DEFAULT_SKILL_FILE)
    p.add_argument("--model", default=None, help="Azure deployment name (overrides env)")
    p.add_argument("--chunk-size", type=int, default=pipeline.DEFAULT_CHUNK_SIZE)
    p.add_argument("--overlap", type=int, default=pipeline.DEFAULT_OVERLAP)
    p.set_defaults(func=cmd_translate)

    p = sub.add_parser("validate-workbook", help="Validate workbook against source")
    p.add_argument("source")
    p.add_argument("workbook")
    p.set_defaults(func=cmd_validate_workbook)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
