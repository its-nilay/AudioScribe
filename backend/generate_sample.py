"""
generate_sample.py
==================
Creates a synthetic WAV audio file that Whisper can transcribe.

This script uses only the Python standard library (wave + struct), so it
works without any extra dependencies.  It generates a 440 Hz sine wave
(A4 note) lasting a few seconds, which Whisper will typically transcribe
as silence or light noise — enough to prove the pipeline works end-to-end.

Usage
-----
    python generate_sample.py            # creates sample.wav in the current dir
    python generate_sample.py my_test.wav
"""

import math
import shutil
import struct
import sys
import wave
from pathlib import Path


def generate_sine_wav(
    path: Path,
    frequency: float = 440.0,
    duration: float = 3.0,
    sample_rate: int = 16000,
    amplitude: float = 0.3,
) -> None:
    """Write a mono 16-bit PCM WAV file containing a sine wave."""
    n_samples = int(sample_rate * duration)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)          # mono
        wf.setsampwidth(2)          # 16-bit
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            value = amplitude * math.sin(2 * math.pi * frequency * i / sample_rate)
            # Convert float [-1, 1] → int16 range
            packed = struct.pack("<h", int(value * 32767))
            wf.writeframes(packed)


def main() -> None:
    src = Path(__file__).resolve().parent / "harvard.wav"
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample.wav")
    if src.exists():
        shutil.copyfile(src, out)
    else:
        generate_sine_wav(out)
    print(f"Generated: {out.resolve()}  ({out.stat().st_size:,} bytes)")
    print()
    print("Test the API:")
    print(f'  1. curl -X POST "http://127.0.0.1:8000/transcriptions" -F "file=@{out}"')
    print('  2. curl "http://127.0.0.1:8000/transcriptions/<job_id>"')


if __name__ == "__main__":
    main()
