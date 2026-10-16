"""
AI Audio Transcription Pipeline — main.py
==========================================
FastAPI service that accepts audio uploads, transcribes them with the
open-source Whisper model, and returns timestamped segments.

Design highlights
-----------------
* Async upload endpoint returns 202 immediately; transcription runs in a
  background task so the caller is never blocked.
* Audio normalisation: every upload is converted to a 16-kHz mono WAV before
  Whisper sees it, which handles MP3, M4A, OGG and FLAC transparently.
* Long-audio chunking: files longer than CHUNK_SECONDS are split into
  overlapping chunks so memory usage stays predictable regardless of
  file size.
* In-memory job store is fine for a demo; the README documents the
  production path (Celery + Redis + PostgreSQL).
"""

import math
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List

import whisper
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


# ---------------------------------------------------------------------------
# FFmpeg auto-detection (Windows)
# ---------------------------------------------------------------------------
def _ensure_ffmpeg() -> None:
    """
    Ensure ffmpeg.exe is on PATH for Whisper and pydub.
    Runs a recursive search through common Windows install locations so the
    server works even when launched from a terminal that hasn't picked up
    the updated PATH yet (e.g. winget installs FFmpeg into a deeply nested
    versioned folder that only appears in new terminal sessions).
    """
    import subprocess

    # 1. Already on PATH — nothing to do.
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        print("[ffmpeg] Found on PATH — OK.")
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # 2. Recursive search in common install roots.
    localappdata = os.environ.get("LOCALAPPDATA", "")
    search_roots = [
        Path(localappdata) / "Microsoft" / "WinGet" / "Packages",
        Path("C:/ProgramData/chocolatey/bin"),
        Path("C:/ffmpeg"),
        Path("C:/Program Files/ffmpeg"),
        Path("C:/Program Files (x86)/ffmpeg"),
    ]

    for root in search_roots:
        if not root.exists():
            continue
        # glob('**/ffmpeg.exe') searches at any depth under root
        for match in root.glob("**/ffmpeg.exe"):
            bin_dir = str(match.parent)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
            print(f"[ffmpeg] Found at {bin_dir} — added to PATH.")
            return

    print(
        "[ffmpeg] WARNING: ffmpeg.exe not found.\n"
        "  Install from https://ffmpeg.org/download.html and add its bin/ folder to PATH.\n"
        "  Or run:  winget install Gyan.FFmpeg  then open a NEW terminal."
    )


_ensure_ffmpeg()



# ---------------------------------------------------------------------------
# Configuration (all can be overridden via environment variables)
# ---------------------------------------------------------------------------
BASE_DIR = Path(os.getenv("AUDIO_DATA_DIR", "data"))
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Whisper model size: tiny | base | small | medium | large
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")

# Audio longer than this (seconds) is split into overlapping chunks.
CHUNK_SECONDS = int(os.getenv("CHUNK_SECONDS", "600"))   # 10 minutes
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "5"))     # 5-second overlap

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}

# ---------------------------------------------------------------------------
# App and global state
# ---------------------------------------------------------------------------
app = FastAPI(
    title="AI Audio Transcription Pipeline",
    version="1.0.0",
    description=(
        "Upload an audio file and get back a full transcript plus per-segment "
        "timestamps. Uses OpenAI Whisper for inference."
    ),
)

# Allow the static frontend (opened from file:// or any local dev server) to
# call the API without browser CORS errors.  Restrict origins in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Demo-only in-memory job store.
# In production: PostgreSQL row per job, Celery worker queue.
jobs: Dict[str, Dict[str, Any]] = {}

_model = None  # loaded lazily and cached


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_model() -> whisper.Whisper:
    """Load the Whisper model once and reuse it for all requests."""
    global _model
    if _model is None:
        _model = whisper.load_model(WHISPER_MODEL_SIZE)
    return _model


def convert_to_wav(src: Path) -> Path:
    """
    Convert any supported audio format to a 16-kHz mono WAV file that
    Whisper can process directly.

    Uses pydub (backed by FFmpeg) when available, otherwise falls back to
    passing the file straight to Whisper (which shells out to FFmpeg itself).

    Returns the path to use for transcription (may be the original file if
    no conversion is needed or pydub is not installed).
    """
    if src.suffix.lower() == ".wav":
        return src  # Already WAV — Whisper handles format details internally.

    wav_path = src.with_suffix(".wav")
    try:
        from pydub import AudioSegment  # optional dependency

        audio = AudioSegment.from_file(str(src))
        audio = audio.set_frame_rate(16000).set_channels(1)
        audio.export(str(wav_path), format="wav")
        return wav_path
    except ImportError:
        # pydub not installed — Whisper's own FFmpeg call will handle it.
        return src
    except Exception as exc:
        # Conversion failed — let Whisper try anyway.
        print(f"[warn] pydub conversion failed ({exc}), passing original file.")
        return src


def split_audio(wav_path: Path, chunk_sec: int, overlap_sec: int) -> List[Path]:
    """
    Split a WAV file into overlapping chunks so very long recordings do not
    exhaust memory during inference.

    Returns a list of chunk file paths in order.  If the audio is shorter
    than chunk_sec the original path is returned as a single-element list.
    """
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_wav(str(wav_path))
        duration_ms = len(audio)
        chunk_ms = chunk_sec * 1000
        overlap_ms = overlap_sec * 1000

        if duration_ms <= chunk_ms:
            return [wav_path]

        chunks: List[Path] = []
        step_ms = chunk_ms - overlap_ms
        n_chunks = math.ceil((duration_ms - overlap_ms) / step_ms)

        for i in range(n_chunks):
            start = i * step_ms
            end = min(start + chunk_ms, duration_ms)
            chunk = audio[start:end]
            chunk_path = wav_path.parent / f"{wav_path.stem}_chunk{i:04d}.wav"
            chunk.export(str(chunk_path), format="wav")
            chunks.append(chunk_path)

        return chunks
    except ImportError:
        # pydub not available — return whole file and let Whisper handle it.
        return [wav_path]


def merge_segment_lists(
    segment_groups: List[List[Dict]], offsets: List[float]
) -> List[Dict]:
    """
    Merge per-chunk segment lists into a single list with corrected timestamps.
    Duplicate segments that appear in the overlap region are deduplicated by
    keeping the first occurrence.
    """
    merged: List[Dict] = []
    seen_starts = set()

    for segments, offset in zip(segment_groups, offsets):
        for seg in segments:
            adjusted_start = round(seg["start"] + offset, 2)
            adjusted_end = round(seg["end"] + offset, 2)
            # Skip if a segment starting at the same time already exists
            # (overlap deduplication).
            if adjusted_start in seen_starts:
                continue
            seen_starts.add(adjusted_start)
            merged.append(
                {
                    "start": adjusted_start,
                    "end": adjusted_end,
                    "text": seg["text"],
                }
            )

    return sorted(merged, key=lambda s: s["start"])


# ---------------------------------------------------------------------------
# Background transcription worker
# ---------------------------------------------------------------------------

def transcribe_job(job_id: str, file_path: Path) -> None:
    """
    Run Whisper inference on the uploaded file.

    Steps
    -----
    1. Convert to WAV (handles different formats).
    2. Split into chunks if the file is long.
    3. Transcribe each chunk and merge results.
    4. Write final status + transcript back to the job dict.
    """
    jobs[job_id]["status"] = "processing"
    wav_path = file_path  # updated after conversion

    try:
        # --- Step 1: normalise format -----------------------------------
        wav_path = convert_to_wav(file_path)

        # --- Step 2: split long audio -----------------------------------
        chunks = split_audio(wav_path, CHUNK_SECONDS, CHUNK_OVERLAP)

        # --- Step 3: transcribe each chunk ------------------------------
        mdl = get_model()
        all_text_parts: List[str] = []
        all_segment_groups: List[List[Dict]] = []
        chunk_offsets: List[float] = []
        detected_language: str | None = None  # set from first chunk

        step_sec = CHUNK_SECONDS - CHUNK_OVERLAP
        for idx, chunk_path in enumerate(chunks):
            offset = idx * step_sec
            chunk_offsets.append(float(offset))
            result = mdl.transcribe(str(chunk_path))

            all_text_parts.append(result.get("text", "").strip())
            all_segment_groups.append(
                [
                    {
                        "start": float(s["start"]),
                        "end": float(s["end"]),
                        "text": s["text"].strip(),
                    }
                    for s in result.get("segments", [])
                ]
            )

            # Detect language from the first chunk only.
            if idx == 0:
                detected_language = result.get("language")

        # --- Step 4: merge results --------------------------------------
        full_text = " ".join(all_text_parts).strip()
        merged_segments = merge_segment_lists(all_segment_groups, chunk_offsets)

        jobs[job_id].update(
            status="completed",
            text=full_text,
            language=detected_language,
            segments=merged_segments,
            chunk_count=len(chunks),
        )

    except Exception as exc:
        jobs[job_id].update(status="failed", error=str(exc))

    finally:
        # Clean up temporary chunk files (not the original upload).
        if wav_path != file_path and wav_path.exists():
            try:
                wav_path.unlink()
            except OSError:
                pass
        # Clean up chunk files
        for chunk_path in UPLOAD_DIR.glob(f"{file_path.stem}_chunk*.wav"):
            try:
                chunk_path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Ops"])
def health():
    """Liveness check — returns 200 when the service is running."""
    return {"status": "ok", "model": WHISPER_MODEL_SIZE}


@app.post("/transcriptions", status_code=202, tags=["Transcription"])
async def create_transcription(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Upload an audio file and receive a job ID.

    - The response is **202 Accepted** — transcription runs asynchronously.
    - Poll `GET /transcriptions/{job_id}` for status and results.
    - Supported formats: WAV, MP3, M4A, OGG, FLAC, WebM.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file format '{suffix}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )

    job_id = str(uuid.uuid4())
    destination = UPLOAD_DIR / f"{job_id}{suffix}"

    try:
        with destination.open("wb") as out_file:
            shutil.copyfileobj(file.file, out_file)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Could not save uploaded file: {exc}")
    finally:
        await file.close()

    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "filename": file.filename,
        "audio_url": f"/transcriptions/{job_id}/audio",
        "text": None,
        "language": None,
        "segments": None,
        "chunk_count": None,
        "error": None,
    }

    background_tasks.add_task(transcribe_job, job_id, destination)
    return {"job_id": job_id, "status": "pending"}


@app.get("/transcriptions/{job_id}", tags=["Transcription"])
def get_transcription(job_id: str):
    """
    Retrieve transcription status and results.

    **status** values:
    - `pending`    — queued, not started yet
    - `processing` — Whisper is running
    - `completed`  — transcript ready
    - `failed`     — check the `error` field
    """
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Transcription job not found.")
    return job


@app.get("/transcriptions/{job_id}/audio", tags=["Transcription"])
def get_transcription_audio(job_id: str):
    """
    Stream or download the original uploaded audio file for playback.
    Supports HTTP Range requests so browsers can seek smoothly.
    """
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Transcription job not found.")

    candidates = list(UPLOAD_DIR.glob(f"{job_id}.*"))
    if not candidates:
        raise HTTPException(status_code=404, detail="Audio file not found on server.")

    audio_path = candidates[0]
    suffix = audio_path.suffix.lower()
    media_types = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".webm": "audio/webm",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(
        path=str(audio_path),
        media_type=media_type,
        filename=job.get("filename") or audio_path.name,
    )


@app.get("/transcriptions", tags=["Transcription"])
def list_transcriptions():
    """List all transcription jobs (demo only — no pagination)."""
    return list(jobs.values())
