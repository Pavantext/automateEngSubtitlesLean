#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcribe.py — Telugu audio (.mp3/.m4a/.wav/...) -> timed subtitle cues.

Uses Azure AI Speech fast transcription (te-IN), which returns every word with its
timestamp. Words are grouped into subtitle-sized cues at the speaker's natural
pauses (<= 7 s per cue, per the Netflix Timed Text Style Guide).

Azure Speech is not offered in South India; Central India (Pune) supports fast
transcription and keeps audio in-region. Configure via environment variables:

    AZURE_SPEECH_KEY=...              key of the Speech resource (Standard S0 tier)
    AZURE_SPEECH_REGION=centralindia  or AZURE_SPEECH_ENDPOINT=https://<name>.cognitiveservices.azure.com
    AZURE_SPEECH_MODEL=               empty = standard model (GA);
                                      MAI-Transcribe-2 = Microsoft's newer model (preview)

Each cue carries the recognizer's confidence so the editor can point the human
reviewer at the cues most likely to contain recognition errors.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests
from dotenv import load_dotenv

import pipeline

MAX_CUE_SEC = 7.0               # Netflix: max 7 s per subtitle event (after padding)
MIN_CUE_SEC = 5 / 6             # Netflix: min 5/6 s per subtitle event
TARGET_MIN_SEC = 2.0            # keep merging short phrases until a cue is this long
SENTENCE_PAUSE_SEC = 0.7        # a pause this long ends a cue (once >= TARGET_MIN_SEC)
MAX_MERGE_GAP_SEC = 1.5         # never merge words across a longer silence
LEAD_IN_SEC = 0.1
LEAD_OUT_SEC = 0.25
MAX_SPEECH_SEC = MAX_CUE_SEC - LEAD_IN_SEC - LEAD_OUT_SEC
MAX_CUE_CHARS = 90              # about two subtitle lines of Telugu
# Azure scores whole phrases (~20 s of speech), in a narrow band: on a 26-minute
# discourse the median was 0.81 and the weakest tenth scored <= 0.77.
LOW_CONFIDENCE = 0.77           # cues below this are highlighted for review
SENTENCE_END = (".", "?", "!", "।", "॥")

DEFAULT_REGION = "centralindia"
API_VERSION = "2025-10-15"      # adds phrase lists and MAI-Transcribe to fast transcription
REQUEST_TIMEOUT_SEC = 1800

ProgressFn = Callable[[str], None]
Segment = Tuple[float, float]


def _noop(_msg: str) -> None:
    pass


# --------------------------------------------------------------------------- #
# Audio conversion
# --------------------------------------------------------------------------- #
def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # bundled static ffmpeg (used on hosts without ffmpeg)

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as err:  # pragma: no cover - depends on host
        raise RuntimeError("ffmpeg not found. Install ffmpeg or `pip install imageio-ffmpeg`.") from err


def _run_ffmpeg(args: Sequence[str]) -> None:
    proc = subprocess.run([ffmpeg_exe(), "-v", "error", "-nostdin", *args], capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace").strip()[-400:]
        raise RuntimeError(f"Could not read audio file: {tail or 'ffmpeg failed'}")


def make_compact_audio(src: Path, dest: Path) -> None:
    """Small mono MP3: uploaded to Azure Speech and streamed by the in-app editor."""
    _run_ffmpeg(["-y", "-i", str(src), "-vn", "-ac", "1", "-b:a", "64k", str(dest)])


# --------------------------------------------------------------------------- #
# Azure AI Speech fast transcription
# --------------------------------------------------------------------------- #
def _speech_config() -> Tuple[str, str, str]:
    load_dotenv()
    load_dotenv(".env.local")
    key = os.getenv("AZURE_SPEECH_KEY")
    if not key:
        raise RuntimeError(
            "Audio transcription needs an Azure Speech resource. Set AZURE_SPEECH_KEY and "
            "AZURE_SPEECH_REGION (see .env.example)."
        )
    endpoint = (os.getenv("AZURE_SPEECH_ENDPOINT") or "").rstrip("/")
    if not endpoint:
        region = os.getenv("AZURE_SPEECH_REGION") or DEFAULT_REGION
        endpoint = f"https://{region}.api.cognitive.microsoft.com"
    return key, endpoint, (os.getenv("AZURE_SPEECH_MODEL") or "").strip()


def _phrases(context_hint: str) -> List[str]:
    parts = [p.strip() for chunk in context_hint.splitlines() for p in chunk.replace(";", ",").split(",")]
    return [p for p in parts if p][:500]


def build_definition(model: str, context_hint: str = "") -> Dict[str, Any]:
    definition: Dict[str, Any] = {"profanityFilterMode": "None"}
    if model:  # MAI-Transcribe (preview) runs through the same API's enhanced mode
        definition["locales"] = ["te"]
        definition["enhancedMode"] = {
            "enabled": True,
            "model": model,
            "modelOptions": {"timestamps": "word", "transcribeStyle": "verbatim"},
        }
    else:
        definition["locales"] = ["te-IN"]
    phrases = _phrases(context_hint)
    if phrases:
        definition["phraseList"] = {"phrases": phrases}
    return definition


def _error_message(resp: requests.Response) -> str:
    try:
        body = resp.json()
        err = body.get("error") or body
        msg = err.get("message") or err.get("code") or json.dumps(body)[:300]
    except ValueError:
        msg = resp.text[:300] or resp.reason
    hint = {
        401: " Check AZURE_SPEECH_KEY, and that AZURE_SPEECH_REGION matches the resource's region.",
        403: " Check that the Speech resource is on the Standard (S0) tier; fast transcription is not "
             "available on Free (F0).",
        404: " Check AZURE_SPEECH_REGION / AZURE_SPEECH_ENDPOINT (use centralindia; southindia has no Speech).",
    }.get(resp.status_code, "")
    return f"Azure Speech error {resp.status_code}: {str(msg).rstrip('.')}.{hint}"


def request_transcription(audio_path: Path, definition: Dict[str, Any]) -> Dict[str, Any]:
    key, endpoint, _ = _speech_config()
    url = f"{endpoint}/speechtotext/transcriptions:transcribe"
    for attempt in range(4):
        with open(audio_path, "rb") as audio:
            resp = requests.post(
                url,
                params={"api-version": API_VERSION},
                headers={"Ocp-Apim-Subscription-Key": key},
                files={
                    "audio": (Path(audio_path).name, audio, "audio/mpeg"),
                    "definition": (None, json.dumps(definition, ensure_ascii=False)),
                },
                timeout=REQUEST_TIMEOUT_SEC,
            )
        # Microsoft asks clients to retry 429s: the service may still be scaling up.
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(float(resp.headers.get("Retry-After") or 5 * 2 ** attempt))
            continue
        if not resp.ok:
            raise RuntimeError(_error_message(resp))
        return resp.json()
    raise RuntimeError("unreachable")


# --------------------------------------------------------------------------- #
# Words -> cues
# --------------------------------------------------------------------------- #
@dataclass
class Word:
    start: float
    end: float
    text: str
    confidence: Optional[float]
    phrase_end: bool  # Azure closes a phrase at a pause or sentence end


def words_from_response(data: Dict[str, Any]) -> List[Word]:
    words: List[Word] = []
    phrases = [p for p in data.get("phrases") or [] if p.get("channel", 0) == 0]
    for phrase in phrases:
        conf = phrase.get("confidence") or None  # MAI-Transcribe returns 0: no score
        items = phrase.get("words") or []
        if items:
            for k, w in enumerate(items):
                start = w["offsetMilliseconds"] / 1000
                end = start + w.get("durationMilliseconds", 0) / 1000
                words.append(Word(start, end, w["text"], conf, k == len(items) - 1))
            continue
        # No word timings: spread the phrase over its words by length.
        tokens = (phrase.get("text") or "").split()
        t = phrase["offsetMilliseconds"] / 1000
        span = phrase.get("durationMilliseconds", 0) / 1000
        total = sum(len(tok) for tok in tokens) or 1
        for k, tok in enumerate(tokens):
            d = span * len(tok) / total
            words.append(Word(t, t + d, tok, conf, k == len(tokens) - 1))
            t += d
    words = [w for w in words if w.text.strip()]
    words.sort(key=lambda w: w.start)
    return words


def _is_break(prev: Word, nxt: Word) -> bool:
    return (nxt.start - prev.end >= SENTENCE_PAUSE_SEC or prev.phrase_end
            or prev.text.endswith(SENTENCE_END))


def _best_cut(cur: List[Word]) -> int:
    """Where to split a cue that hit a hard limit: the longest pause, preferring
    phrase or sentence ends, leaving at least a second on the left."""
    best, best_score = len(cur), -1.0
    for i in range(1, len(cur)):
        if cur[i - 1].end - cur[0].start < 1.0:
            continue
        score = cur[i].start - cur[i - 1].end
        if cur[i - 1].phrase_end or cur[i - 1].text.endswith(SENTENCE_END + (",",)):
            score += 0.5
        if score > best_score:
            best, best_score = i, score
    return best


def group_words(words: List[Word]) -> List[List[Word]]:
    cues: List[List[Word]] = []
    cur: List[Word] = []
    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            too_long = w.end - cur[0].start > MAX_SPEECH_SEC or \
                sum(len(x.text) + 1 for x in cur) + len(w.text) > MAX_CUE_CHARS
            if gap > MAX_MERGE_GAP_SEC or (_is_break(cur[-1], w) and cur[-1].end - cur[0].start >= TARGET_MIN_SEC):
                cues.append(cur)
                cur = []
            elif too_long:
                cut = _best_cut(cur)
                cues.append(cur[:cut])
                cur = cur[cut:]
        cur.append(w)
    if cur:
        cues.append(cur)
    return cues


def pad_cues(cues: List[Segment], duration: float) -> List[Segment]:
    """Add a little lead-in/out without overlapping neighbours; enforce min duration."""
    out: List[Segment] = []
    for i, (start, end) in enumerate(cues):
        prev_end = out[-1][1] if out else 0.0
        next_start = cues[i + 1][0] if i + 1 < len(cues) else duration
        s = max(prev_end, start - LEAD_IN_SEC, 0.0)
        e = min(next_start - 0.05, end + LEAD_OUT_SEC, duration)
        if e - s < MIN_CUE_SEC:
            e = min(next_start - 0.05, s + MIN_CUE_SEC, duration)
        out.append((round(s, 3), round(max(e, s + 0.1), 3)))
    return out


def cues_from_response(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups = group_words(words_from_response(data))
    if not groups:
        return []
    duration = (data.get("durationMilliseconds") or 0) / 1000 or groups[-1][-1].end + 1
    spans = pad_cues([(g[0].start, g[-1].end) for g in groups], duration)
    cues = []
    for (start, end), group in zip(spans, groups):
        confs = [w.confidence for w in group if w.confidence is not None]
        text = " ".join(" ".join(w.text for w in group).replace("�", "").split())
        cues.append({
            "start": start,
            "end": end,
            "text": pipeline.wrap_subtitle(text),
            "confidence": round(min(confs), 3) if confs else None,
        })
    return cues


def transcribe_audio(
    audio_path: Path,
    *,
    context_hint: str = "",
    progress: ProgressFn = _noop,
) -> List[Dict[str, Any]]:
    """Compact audio file -> list of cues: {start, end (seconds), text, confidence}."""
    _, endpoint, model = _speech_config()
    size_mb = Path(audio_path).stat().st_size / (1024 * 1024)
    host = endpoint.split("//")[-1].split(".")[0]
    progress(f"Sending {size_mb:.1f} MB to Azure Speech ({model or 'standard Telugu model'}, {host})...")
    data = request_transcription(Path(audio_path), build_definition(model, context_hint))

    cues = cues_from_response(data)
    if not cues:
        raise RuntimeError("Azure Speech returned no Telugu speech for this audio.")
    minutes = (data.get("durationMilliseconds") or 0) / 60000
    low = sum(1 for c in cues if c["confidence"] is not None and c["confidence"] < LOW_CONFIDENCE)
    progress(f"Transcription done: {minutes:.1f} min of audio -> {len(cues)} cues "
             f"({low} flagged low-confidence for review).")
    return cues
