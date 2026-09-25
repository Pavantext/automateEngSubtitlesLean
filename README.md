# Telugu → English Subtitle Review Pipeline

Turns a Telugu **audio recording** or **`.sbv`/`.srt` subtitle file** into reviewed
Telugu subtitles, an AI English draft, and — after human review — final English
subtitles plus an Excel review workbook. Comes with a CLI and a responsive web UI
(works on desktop, Android, and iOS browsers).

> The AI output is a **first-pass draft for human review** — a reviewer must
> check every cue before publishing.

## Workflow (human in the loop at every stage)

```
audio (.mp3 …) ── speech-to-text ──┐
                                   ├─► 1. Telugu subtitles: human edits cues, listens to
.sbv / .srt ───────────────────────┘      low-confidence ones, downloads SBV/SRT
                                              │
                                              ▼  translate (Azure OpenAI)
                                   2. English review: human writes corrections,
                                      optional AI review flags likely errors
                                              │
                                              ▼
                                   English .srt/.sbv (corrections win) + workbook
```

Why this shape — each step follows published practice:

| Step | Practice | Source |
|---|---|---|
| Fix the Telugu transcript before translating | Recognition errors carry straight into the translation, so the source is corrected first | — |
| Cues ≤ 7 s, ≥ 5/6 s; ≤ 42 chars/line, 2 lines; ≤ 20 chars/s | Subtitle timing and reading-speed limits | [Netflix Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements), [English (USA)](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide) |
| A human post-edits every cue; the AI never overwrites | Full human post-editing of machine translation | [ISO 18587:2017](https://www.iso.org/standard/62970.html) |
| AI review uses accuracy / terminology / linguistic / style categories with minor / major / critical severity | MQM error typology | [themqm.org](https://themqm.org/error-types-2/typology/) |
| An LLM flags error spans instead of rewriting everything | GEMBA-MQM (Microsoft, WMT 2023) | [ACL Anthology](https://aclanthology.org/2023.wmt-1.64/) |

### Speech-to-text: Azure AI Speech (Central India)

Audio is transcribed by **Azure AI Speech fast transcription** with the Telugu
(`te-IN`) model. It returns every word with its timestamp; the app groups words
into subtitle-sized cues at the speaker's pauses and carries the recognizer's
confidence so the editor can sort and highlight the weakest cues for review.

- **Region:** Azure Speech is *not* available in South India; **Central India**
  supports fast transcription, and audio is processed only in the resource's region
  ([regions](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/regions)).
- **Tier:** Standard (S0). The Free (F0) tier has no fast transcription
  ([quotas](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits)).
- **Cost:** $0.36 per audio hour in Central India (Azure retail price list), e.g.
  about $0.16 for a 26-minute discourse. No monthly fee.
- **Limits:** under 5 hours and 500 MB per file (uploads are compressed to mono MP3 first).
- **Optional model:** `AZURE_SPEECH_MODEL=MAI-Transcribe-2` switches to Microsoft's
  newer model, which lists Telugu, on the same resource — it is in *public preview*
  (no SLA) ([MAI-Transcribe](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe)).
  LLM speech's other modes do not support Telugu.

## What you get per job

| Download | Purpose |
|---|---|
| Telugu `.sbv` / `.srt` | The (human-corrected) Telugu subtitles, in the formats ticked on upload |
| English `.srt` / `.sbv` | Final English: the human correction where given, else the AI draft. Sanskrit terms marked `*like this*` become `<i>italics</i>` in SRT (SBV has no styling) |
| `*_master_review.xlsx` | Cue #, timecode, Telugu, AI English, Human Review Correction; an **AI Review** sheet when that pass was run |
| `*_discourse_brief.md` | Context the model builds before translating |
| `*_translation_raw.json` | Machine-readable translations |

Jobs and their files are kept **24 hours** after upload (`RETENTION_HOURS`), are
listed under *Recent jobs*, survive server restarts, and are then deleted
automatically. A job can also be deleted immediately from its page.

## Project layout

```
pipeline.py    Parsing, SBV/SRT writing, translation, AI review, workbook (Azure OpenAI)
transcribe.py  Audio -> timed Telugu cues (Azure AI Speech fast transcription)
cli.py         Command-line interface
app.py         FastAPI backend: jobs, editor API, downloads, 24 h cleanup
static/        Responsive single-page web UI (upload, cue editor, review editor)
render.yaml    One-click Render deployment blueprint
.env.example   Template for environment variables (copy to .env)
```

## 1. Setup (local)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then edit .env with your real values
```

Fill in `.env`:

```
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_VERSION=2024-12-01-preview   # an API version, not a model date
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
AZURE_SPEECH_KEY=...                          # Speech resource (S0) for audio uploads
AZURE_SPEECH_REGION=centralindia
APP_PASSWORD=choose-a-long-random-password
```

`.env` is git-ignored and must never be committed. Audio decoding uses `ffmpeg`
from your PATH, or the copy bundled with the `imageio-ffmpeg` package.

## 2. Run the web app

```bash
python app.py
# open http://localhost:8000
```

1. Enter the `APP_PASSWORD`.
2. Upload an audio file (tick SBV and/or SRT; optionally list names/terms that
   occur in the recording) or a Telugu `.sbv`/`.srt`.
3. **Telugu subtitles** tab: play cues, fix recognition errors (start with
   *Least confident first*), adjust timings, insert/delete cues, save, download.
4. **Save & translate** → **English review** tab: type corrections where needed.
   Reading-speed and line-length warnings are shown per cue.
5. Optional **Run AI review**: flags likely errors with a suggested fix; choose
   *Use suggestion* only where you agree.
6. Download the English `.srt`/`.sbv` and the workbook.

## 3. Or use the CLI

```bash
python cli.py transcribe episode.mp3 --formats sbv,srt --out-dir out_v4_1_lean
python cli.py translate "CH 05 _EP 11.sbv" --out-dir out_v4_1_lean
python cli.py validate-workbook "CH 05 _EP 11.sbv" out_v4_1_lean/CH_05__EP_11_master_review.xlsx
```

Options: `--model` (Azure deployment override), `--chunk-size` (default 40),
`--overlap` (default 3), `--skill` (skill markdown file), `--hint` (names/terms for
speech-to-text).

## 4. Deploy to Render

1. Push this repo to GitHub.
2. In [Render](https://render.com): **New + → Blueprint**, pick this repo.
   Render reads `render.yaml`.
3. When prompted, set the secret env vars: `AZURE_OPENAI_ENDPOINT`,
   `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_SPEECH_KEY`, `APP_PASSWORD`.
4. Deploy. Your app is live at `https://<name>.onrender.com` over HTTPS.

> **Free plan caveat:** Render's free disk is wiped on every restart, deploy and
> idle spin-down (about 15 minutes without traffic), so a job can disappear before
> its 24 hours — download files when a job finishes. Full 24-hour retention needs a
> paid plan with a persistent disk (set `JOBS_DIR` to the disk's mount path). A step
> that is running when the server restarts is marked as interrupted and can be re-run.

## Security notes

- Access is gated by a single shared `APP_PASSWORD`. Use a long random value and
  always serve over HTTPS (Render does this automatically). Everyone with the
  password sees the same job list.
- The audio player uses a per-job signed token (derived from `APP_PASSWORD`),
  because browsers cannot send the password header for `<audio>` elements.
- API keys live only in server environment variables, never in the repo.
- If a key is ever committed or shared, **rotate it immediately**.
