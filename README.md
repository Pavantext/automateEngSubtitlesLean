# Telugu → English Subtitle Review Pipeline

Lean, one-pass tool that turns a Telugu `.sbv`/`.srt` subtitle file into an
**English review workbook** (Excel), plus a discourse brief and raw JSON.
Translation runs on **Azure OpenAI**. Comes with a CLI and a responsive web UI
(works on desktop, Android, and iOS browsers).

> The AI output is a **first-pass draft for human review** — a reviewer must
> check every cue before publishing.

## What you get per run

| Artifact | File | Purpose |
|---|---|---|
| Review workbook | `*_master_review.xlsx` | Cue #, timecode, Telugu, AI English, blank "Human Review Correction" column |
| Discourse brief | `*_discourse_brief.md` | Concise context the model builds before translating |
| Raw translation | `*_translation_raw.json` | Machine-readable translations |

## Project layout

```
pipeline.py    Core translation logic (reusable, Azure OpenAI)
cli.py         Command-line interface
app.py         FastAPI backend + serves the web UI
static/        Responsive single-page web UI
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
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
APP_PASSWORD=choose-a-long-random-password
```

`.env` is git-ignored and must never be committed.

## 2. Run the web app

```bash
python app.py
# open http://localhost:8000
```

Enter the `APP_PASSWORD`, choose a subtitle file, and download the workbook when
the job finishes. Progress updates live while it runs.

## 3. Or use the CLI

```bash
python cli.py translate "CH 05 _EP 11.sbv" --out-dir out_v4_1_lean
python cli.py validate-workbook "CH 05 _EP 11.sbv" out_v4_1_lean/CH_05__EP_11_master_review.xlsx
```

Options: `--model` (Azure deployment override), `--chunk-size` (default 40),
`--overlap` (default 3), `--skill` (skill markdown file).

## 4. Deploy to Render

1. Push this repo to GitHub (see below).
2. In [Render](https://render.com): **New + → Blueprint**, pick this repo.
   Render reads `render.yaml`.
3. When prompted, set the secret env vars: `AZURE_OPENAI_ENDPOINT`,
   `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `APP_PASSWORD`.
4. Deploy. Your app is live at `https://<name>.onrender.com` over HTTPS.

> Free tier sleeps after inactivity and has an ephemeral disk (finished job
> files are cleared on restart — download promptly). Fine for a private tool.

## Security notes

- Access is gated by a single shared `APP_PASSWORD`. Use a long random value and
  always serve over HTTPS (Render does this automatically).
- The Azure key lives only in server environment variables, never in the repo.
- If a key is ever committed or shared, **rotate it immediately**.
