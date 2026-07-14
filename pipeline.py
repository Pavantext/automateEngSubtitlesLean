#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — Lean one-pass Telugu SBV/SRT -> English review workbook.

Reusable core shared by the CLI (cli.py) and the web app (app.py).
Uses Azure OpenAI. Configure via environment variables (see .env.example):

    AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
    AZURE_OPENAI_API_KEY=...
    AZURE_OPENAI_API_VERSION=2024-10-21
    AZURE_OPENAI_DEPLOYMENT=your-deployment-name

Produces:
    - master review workbook (.xlsx)
    - discourse brief (.md)
    - raw translation (.json)
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from openpyxl.styles import Alignment, Font, PatternFill

try:
    from openai import AzureOpenAI
except Exception:  # pragma: no cover - import guard
    AzureOpenAI = None  # type: ignore

DEFAULT_CHUNK_SIZE = 40
DEFAULT_OVERLAP = 3
DEFAULT_SKILL_FILE = "SKILL_v4_1_lean_subtitle_review_pipeline.md"

# progress(message) -> None. Optional hook so callers (web UI) can show status.
ProgressFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


@dataclass
class Cue:
    number: int
    start: str
    end: str
    telugu: str

    @property
    def timecode(self) -> str:
        return f"{self.start} --> {self.end}"


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _ts_sbv_to_srt(ts: str) -> str:
    ts = ts.strip()
    h, m, rest = ts.split(":")
    rest = rest.replace(".", ",")
    return f"{int(h):02d}:{m}:{rest}"


def _normalize_srt_ts(ts: str) -> str:
    ts = ts.strip().replace(".", ",")
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return f"{int(h):02d}:{m}:{s}"
    return ts


def parse_source_text(raw: str) -> List[Cue]:
    """Parse SBV or SRT subtitle text into ordered cues."""
    raw = raw.lstrip("﻿")
    blocks = [b for b in re.split(r"\r?\n\r?\n", raw) if b.strip()]
    cues: List[Cue] = []

    for idx, block in enumerate(blocks, 1):
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip() != ""]
        if not lines:
            continue

        if lines[0].strip().isdigit():
            timing_line = lines[1].strip()
            text_lines = lines[2:]
        else:
            timing_line = lines[0].strip()
            text_lines = lines[1:]

        if "-->" in timing_line:
            start_raw, end_raw = [x.strip() for x in timing_line.split("-->", 1)]
            start = _normalize_srt_ts(start_raw)
            end = _normalize_srt_ts(end_raw)
        else:
            if "," not in timing_line:
                raise ValueError(f"Could not parse timing at block {idx}: {timing_line!r}")
            start_raw, end_raw = timing_line.split(",", 1)
            start = _ts_sbv_to_srt(start_raw)
            end = _ts_sbv_to_srt(end_raw)

        cues.append(Cue(number=idx, start=start, end=end, telugu="\n".join(text_lines).strip()))

    return [Cue(i, c.start, c.end, c.telugu) for i, c in enumerate(cues, 1)]


def parse_source(path: Path) -> List[Cue]:
    return parse_source_text(Path(path).read_text(encoding="utf-8-sig"))


def safe_stem(name: str) -> str:
    stem = Path(name).stem
    return re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "subtitle"


def load_skill_text(skill_path: Optional[Path]) -> str:
    if skill_path and Path(skill_path).exists():
        return Path(skill_path).read_text(encoding="utf-8")
    default = Path(__file__).parent / DEFAULT_SKILL_FILE
    if default.exists():
        return default.read_text(encoding="utf-8")
    here = Path.cwd() / "SKILL.md"
    if here.exists():
        return here.read_text(encoding="utf-8")
    return "Follow the subtitle translation skill strictly."


def cues_to_text(cues: Iterable[Cue]) -> str:
    return "\n".join(
        f"{c.number}. [{c.timecode}] {' / '.join(c.telugu.splitlines())}"
        for c in cues
    )


def build_windows(cues: List[Cue], chunk_size: int) -> List[Tuple[int, int]]:
    windows = []
    start = 1
    while start <= len(cues):
        end = min(len(cues), start + chunk_size - 1)
        windows.append((start, end))
        start = end + 1
    return windows


# --------------------------------------------------------------------------- #
# Azure OpenAI client
# --------------------------------------------------------------------------- #
def get_client() -> Any:
    if AzureOpenAI is None:
        raise RuntimeError("openai package is not installed. Run: pip install openai")

    load_dotenv()
    load_dotenv(".env.local")

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION") or "2024-10-21"

    if not endpoint or not api_key:
        raise RuntimeError(
            "Missing Azure OpenAI config. Set AZURE_OPENAI_ENDPOINT and "
            "AZURE_OPENAI_API_KEY (see .env.example)."
        )

    return AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)


def resolve_deployment(model: Optional[str] = None) -> str:
    deployment = model or os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if not deployment:
        raise RuntimeError(
            "No model/deployment set. Provide --model or set AZURE_OPENAI_DEPLOYMENT."
        )
    return deployment


def response_text(resp: Any) -> str:
    try:
        if hasattr(resp, "choices") and resp.choices:
            return resp.choices[0].message.content or ""
    except Exception:
        pass
    if hasattr(resp, "output_text") and resp.output_text:
        return resp.output_text
    return str(resp)


def call_model(client: Any, model: str, system: str, user: str) -> str:
    # Temperature intentionally omitted: some Azure deployments only accept the default.
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return response_text(resp).strip()
        except Exception as err:  # retry with backoff
            last_err = err
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Model call failed: {last_err}")


def extract_json_array(text: str) -> List[Dict[str, Any]]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            raise ValueError(f"Model did not return JSON array. Output starts:\n{text[:500]}")
        data = json.loads(m.group(0))

    if not isinstance(data, list):
        raise ValueError("Model JSON output was not a list.")
    return data


# --------------------------------------------------------------------------- #
# Translation
# --------------------------------------------------------------------------- #
def make_discourse_brief(client: Any, model: str, skill_text: str, cues: List[Cue]) -> str:
    system = "Create concise context briefs for Telugu-to-English subtitle translation."
    user = f"""
SKILL:
{skill_text}

Create a concise discourse brief for the Telugu episode below.

Include only what helps translation:
- teaching flow
- questions/doubts/prayers/reflections
- examples/analogies
- Sanskrit terms or quotations
- speaker perspective/voice notes
- opening and closing/sign-off cues
- likely cue-boundary risks

Keep it concise. Do not translate cue-by-cue.

TELUGU CUES:
{cues_to_text(cues)}
"""
    return call_model(client, model, system, user)


def translate_chunk(
    client: Any,
    model: str,
    skill_text: str,
    discourse_brief: str,
    cues: List[Cue],
    start: int,
    end: int,
    overlap: int,
) -> List[Dict[str, Any]]:
    before = cues[max(0, start - 1 - overlap): start - 1]
    core = cues[start - 1: end]
    after = cues[end: min(len(cues), end + overlap)]

    system = "You are a faithful Telugu-to-English subtitle translator. Return only valid JSON."
    user = f"""
SKILL:
{skill_text}

DISCOURSE BRIEF:
{discourse_brief}

CONTEXT BEFORE:
{cues_to_text(before) if before else "(none)"}

CORE CUES TO TRANSLATE:
{cues_to_text(core)}

CONTEXT AFTER:
{cues_to_text(after) if after else "(none)"}

TASK:
Translate ONLY the core cues.

Return a JSON array with exactly one object per core cue.

Required object shape:
{{
  "cue_number": 1,
  "english": "English translation here"
}}

Rules:
- Follow SKILL.md strictly.
- Use the Telugu cue as source of truth.
- Translate every core cue; do not leave English blank.
- Do not skip, merge, absorb, reorder, or renumber cues.
- Use context only to avoid drift; do not translate context cues.
- Preserve meaning, teaching intent, examples, questions, Sanskrit terms, and tone.
- Use plain natural spoken English, not literary or dramatic prose.
- Do not intensify ordinary Telugu wording unless Telugu clearly requires it.
- Preserve speaker perspective. If Telugu voices a person's own question, prayer, doubt, or reflection directly, preserve that perspective in English.
- Do not introduce quoted inner speech unless Telugu clearly presents direct speech or quoted thought.
- Use required colon transliteration for Sanskrit names, terms, salutations, and verses wherever they appear.
- Use Markdown asterisks for Sanskrit technical terms and quotations where appropriate.
- Preserve closing/sign-off phrases such as *Jai Sri:manna:ra:yana*.
- Return cue numbers only from {start} to {end}.
"""
    data = extract_json_array(call_model(client, model, system, user))
    expected = list(range(start, end + 1))
    got = [int(x.get("cue_number", -1)) for x in data]
    if got != expected:
        raise ValueError(f"Chunk {start}-{end} cue mismatch. Got {got}, expected {expected}")
    return data


def create_workbook(df: pd.DataFrame, out_path: Path) -> None:
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Review")
        ws = writer.book["Review"]

        widths = {"A": 12, "B": 30, "C": 64, "D": 66, "E": 48}
        for col, width in widths.items():
            ws.column_dimensions[col].width = width

        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E79")

        ws.freeze_panes = "A2"


def build_rows(cues: List[Cue], all_items: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for cue in cues:
        english = str(all_items[cue.number].get("english", "") or "").strip()
        if not english:
            raise RuntimeError(
                f"AI returned blank English for cue {cue.number}; automated blanks are not allowed."
            )
        rows.append({
            "Cue Number": cue.number,
            "Timecode": cue.timecode,
            "Telugu Cue": cue.telugu,
            "AI Generated English Cue": english,
            "Human Review Correction": "",
        })
    return rows


def translate_cues(
    cues: List[Cue],
    *,
    skill_text: str,
    model: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    progress: ProgressFn = _noop,
) -> Dict[str, Any]:
    """Run the full translation pass over parsed cues.

    Returns a dict with keys: brief, rows, all_items.
    """
    if not cues:
        raise RuntimeError("No cues parsed.")

    client = get_client()
    deployment = resolve_deployment(model)

    progress(f"Parsed {len(cues)} cues. Building discourse brief...")
    brief = make_discourse_brief(client, deployment, skill_text, cues)

    all_items: Dict[int, Dict[str, Any]] = {}
    windows = build_windows(cues, chunk_size)
    for i, (start, end) in enumerate(windows, 1):
        progress(f"Translating cues {start}-{end} (chunk {i}/{len(windows)})...")
        items = translate_chunk(
            client, deployment, skill_text, brief, cues, start, end, overlap
        )
        for item in items:
            all_items[int(item["cue_number"])] = item

    missing = [c.number for c in cues if c.number not in all_items]
    if missing:
        raise RuntimeError(f"Missing translated cues: {missing}")

    progress("Assembling review workbook...")
    rows = build_rows(cues, all_items)
    return {"brief": brief, "rows": rows, "all_items": all_items}


def translate_to_files(
    *,
    source_text: str,
    source_name: str,
    out_dir: Path,
    skill_text: str,
    model: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    progress: ProgressFn = _noop,
) -> Dict[str, Path]:
    """Parse, translate, and write brief/workbook/raw JSON to out_dir.

    Returns a dict of artifact name -> path.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cues = parse_source_text(source_text)
    result = translate_cues(
        cues,
        skill_text=skill_text,
        model=model,
        chunk_size=chunk_size,
        overlap=overlap,
        progress=progress,
    )

    stem = safe_stem(source_name)
    brief_path = out_dir / f"{stem}_discourse_brief.md"
    workbook_path = out_dir / f"{stem}_master_review.xlsx"
    raw_path = out_dir / f"{stem}_translation_raw.json"

    brief_path.write_text(result["brief"], encoding="utf-8")
    create_workbook(pd.DataFrame(result["rows"]), workbook_path)
    raw_path.write_text(
        json.dumps(result["all_items"], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    progress("Done.")
    return {"brief": brief_path, "workbook": workbook_path, "raw": raw_path}
