# AudioScribe — AI Audio Transcription Pipeline

> Upload any audio file → get back a full transcript with per-segment timestamps in seconds.  
> Built with **Python · FastAPI · OpenAI Whisper** · vanilla HTML/CSS/JS frontend.

---

## Table of Contents

1. [What this project does](#what-this-project-does)
2. [Tech stack](#tech-stack)
3. [System prerequisites](#system-prerequisites)
4. [Running the project](#running-the-project)
5. [Project structure](#project-structure)
6. [API reference](#api-reference)
7. [Configuration](#configuration)
8. [Design decisions](#design-decisions)
9. [Demo video](#demo-video)
10. [Limitations: demo vs production](#limitations-demo-vs-production)

---

## What this project does

AudioScribe is a **fully local** transcription pipeline with three parts:

| Layer | What it does |
|-------|-------------|
| **Backend (FastAPI)** | Receives audio uploads, normalises the format, runs Whisper inference, returns timestamped transcript |
| **Frontend (Browser)** | Drag-and-drop upload, live progress bar, transcript display, built-in audio player that syncs highlighted segments during playback |
| **API** | RESTful, self-documented at `/docs` |

---

## Tech stack

| Concern | Choice | Reason |
|---------|--------|--------|
| API framework | FastAPI | Async, auto OpenAPI docs, best-in-class DX |
| Speech-to-text | OpenAI Whisper (`base` model) | Local, open-source, no API key, 99+ languages |
| Audio handling | pydub + FFmpeg | Format-agnostic conversion and chunking |
| Frontend | Vanilla HTML / CSS / JS | Zero build step, works from `file://` |

---

## System prerequisites

Install these **before** cloning:

### 1. Python 3.10 or newer
Download from [python.org](https://www.python.org/downloads/).  
Verify: `python --version`

### 2. FFmpeg (required — Whisper and pydub both need it)

FFmpeg handles audio decoding for every non-WAV format (MP3, M4A, OGG, FLAC, WebM).  
Without it you will see `[WinError 2] The system cannot find the file specified`.

**Windows — easiest way:**
```powershell
winget install Gyan.FFmpeg
```
Then **open a new terminal** (winget adds FFmpeg to your user PATH, which only takes effect in a fresh session).

> **Note:** The backend auto-detects FFmpeg from the WinGet install location even when the PATH has not been refreshed, so the server still works from the same terminal. But a fresh terminal is cleaner.

**macOS:**
```bash
brew install ffmpeg
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install ffmpeg
```

Verify: `ffmpeg -version`

### 3. Git
Download from [git-scm.com](https://git-scm.com/).  
Verify: `git --version`

---

## Running the project

### Step 1 — Start the backend

```powershell
cd backend

# Create virtual environment
py -3.11 -m venv .venv        # Windows
# python3 -m venv .venv       # macOS / Linux

# Activate
.\.venv\Scripts\Activate.ps1  # Windows PowerShell
# source .venv/bin/activate   # macOS / Linux

# Install dependencies
pip install -r requirements.txt
```

> **PowerShell execution policy error?**  
> Run without activation:
> ```powershell
> .\.venv\Scripts\python.exe -m pip install -r requirements.txt
> .\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
> ```

```powershell
# Start the API server
uvicorn app.main:app --reload --port 8000
```

The API is live at **http://127.0.0.1:8000**  
Interactive docs: **http://127.0.0.1:8000/docs**

> **First start:** Whisper downloads the `base` model weights (~145 MB) to  
> `~/.cache/whisper` (macOS/Linux) or `%USERPROFILE%\.cache\whisper` (Windows).  
> This happens once. Every run after that loads instantly.

### Step 2 — Open the frontend

Open a second terminal (or just double-click the file):

```powershell
# From the project root:
Start-Process "frontend\index.html"

# If you are already inside the frontend folder:
Start-Process "index.html"
```

Or simply open `frontend/index.html` directly in Chrome / Edge / Firefox.

The header shows a **green "API online"** dot when the backend is reachable.

### Step 3 — Transcribe audio

**Via the UI:**
1. Drag and drop an audio file onto the upload area (or click *browse files*)
2. Click **Transcribe Audio**
3. Watch the progress bar — results appear with full transcript + timestamped segments
4. Use the **audio player** to listen back — clicking any segment jumps to that timestamp

**Via the API directly:**
```bash
# Upload
curl -X POST "http://127.0.0.1:8000/transcriptions" -F "file=@recording.wav"
# → {"job_id": "abc-123", "status": "pending"}

# Poll for result
curl "http://127.0.0.1:8000/transcriptions/abc-123"
```

**Use the included test WAV** (no real audio needed):
```powershell
cd backend
python generate_sample.py   # copies harvard.wav → sample.wav
```
Then upload `backend/sample.wav` from the UI.

---

## Project structure

```
AudioScribe/
├── backend/
│   ├── app/
│   │   ├── __init__.py          # Python package marker
│   │   └── main.py              # FastAPI app + full transcription pipeline
│   ├── .venv/                   # virtual environment (git-ignored)
│   ├── data/uploads/            # saved audio files (git-ignored)
│   ├── harvard.wav              # sample speech audio for testing
│   ├── generate_sample.py       # copies harvard.wav → sample.wav for testing
│   ├── run_and_test.py          # self-contained end-to-end test runner
│   ├── test_pipeline.py         # lightweight API test (server must be running)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── index.html               # open this in your browser
│   ├── style.css                # dark glassmorphism design
│   └── app.js                   # upload, polling, audio player, segment sync
├── .gitignore
├── AudioScribe.mp4              # walkthrough video — how the project works
└── README.md
```

---

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Liveness check — returns `{"status":"ok","model":"base"}` |
| `POST` | `/transcriptions` | Upload audio → `202 Accepted` + `job_id` |
| `GET` | `/transcriptions/{job_id}` | Poll status; returns transcript when done |
| `GET` | `/transcriptions/{job_id}/audio` | Stream / play back the uploaded audio |
| `GET` | `/transcriptions` | List all jobs (demo only) |

**Supported formats:** WAV · MP3 · M4A · OGG · FLAC · WebM

**Completed job response:**
```json
{
  "job_id": "abc-123",
  "status": "completed",
  "filename": "recording.mp3",
  "audio_url": "/transcriptions/abc-123/audio",
  "language": "en",
  "text": "The stale smell of old beer lingers.",
  "segments": [
    { "start": 0.0, "end": 4.0, "text": "The stale smell of old beer lingers." },
    { "start": 4.5, "end": 7.2, "text": "It takes heat to bring out the odor." }
  ],
  "chunk_count": 1,
  "error": null
}
```

---

## Configuration

Copy `backend/.env.example` to `backend/.env` and adjust:

| Variable | Default | Description |
|----------|---------|-------------|
| `WHISPER_MODEL` | `base` | `tiny` · `base` · `small` · `medium` · `large` |
| `AUDIO_DATA_DIR` | `data` | Directory where uploaded files are saved |
| `CHUNK_SECONDS` | `600` | Max chunk length in seconds for long-audio splitting |
| `CHUNK_OVERLAP` | `5` | Overlap between chunks (prevents word cutoff) |

> **Model tradeoffs:** `tiny` — fastest, lowest RAM (~1 GB). `base` — good accuracy, ~1.5 GB RAM. `small` / `medium` — higher accuracy, more RAM. `large` — best accuracy, ~10 GB RAM.

---

## Design decisions

### Why FastAPI?
FastAPI gives async request handling out of the box, automatic OpenAPI documentation at `/docs`, and Pydantic validation — all with minimal boilerplate. The async upload endpoint returns `202 Accepted` immediately while transcription runs in a background task, so the HTTP connection is never held open for the duration of Whisper inference.

### Why OpenAI Whisper (local)?
- **No API key required** — works fully offline after first model download
- **Multi-language support** — auto-detects language from audio
- **Native timestamps** — `.transcribe()` returns segment-level `start`/`end` timestamps natively; no post-processing needed
- **Open-source** — inspectable, no vendor lock-in, free to use

### Why pydub + FFmpeg for format handling?
Pydub provides a clean Python API over FFmpeg. Every uploaded file (regardless of format) is converted to **16 kHz mono WAV** before Whisper sees it. This makes the transcription code completely format-agnostic. If pydub is unavailable, Whisper falls back to calling FFmpeg directly — two layers of resilience.

### Why the 202 Accepted pattern (async job)?
Whisper inference can take several seconds to minutes depending on audio length and hardware. Holding an HTTP connection open for that long would timeout reverse proxies and frustrate users. Instead:
1. Upload → validate → save file → return `job_id` in under 100ms
2. Client polls `GET /transcriptions/{job_id}` every 3 seconds
3. Result appears when ready

This is the same pattern used by production services like OpenAI's Batch API.

### Why in-memory job store (demo)?
A `dict` is sufficient to demonstrate the pipeline without operational overhead. The README and code comments document the production migration path (PostgreSQL for job state, Redis + Celery for the queue). Swapping the store does not require any change to the API contract.

### Why chunk-based processing for long audio?
Loading a 2-hour audio file fully into RAM would exhaust memory on typical developer machines. The pipeline splits files longer than `CHUNK_SECONDS` (default 10 min) into overlapping chunks:
- **Overlap** prevents words at chunk boundaries from being cut off
- Each chunk is transcribed independently
- Timestamps are offset and deduplicated before merging

### Why vanilla HTML/CSS/JS for the frontend?
- Zero build tools — just open `index.html` in a browser
- No framework dependencies to install or update
- Portable: runs from `file://` or any static host

---

## Demo video

A short walkthrough video (AudioScribe.mp4) is included at the root of the repository. It covers:
- What the project does and how it is structured
- Starting the backend and opening the frontend
- Uploading an audio file and reading the transcript with timestamps
- The audio playback and segment sync feature

To watch: open AudioScribe.mp4 with any video player (Windows Media Player, VLC, etc.).
---

## Limitations: demo vs production

| Concern | Demo (this repo) | Production |
|---------|-----------------|------------|
| Job store | In-memory Python dict | PostgreSQL |
| Worker queue | FastAPI BackgroundTasks | Celery + Redis |
| Audio storage | Local `data/uploads/` | Object storage (S3/GCS) |
| Auth | None | API keys / OAuth 2.0 |
| Retries | None | Celery retry + dead-letter queue |
| Monitoring | Print statements | OpenTelemetry + Prometheus + Grafana |
| Scaling | Single process | Horizontal worker pods |
| Model cache | Process memory | Shared model server (Triton / TorchServe) |


