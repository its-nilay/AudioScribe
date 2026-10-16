"""
run_and_test.py
---------------
Starts the uvicorn server as a subprocess, waits for it to be ready,
runs the end-to-end transcription test, then shuts the server down.

Usage (from the project root with the venv activated):
    python run_and_test.py
"""
import json
import os
import subprocess
import sys
import time

import requests

BASE = "http://127.0.0.1:8000"


def wait_for_server(timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main():
    # Start the server
    print("Starting uvicorn server...")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    try:
        if not wait_for_server(timeout=30):
            print("ERROR: server did not start in time.")
            server.terminate()
            sys.exit(1)

        print(f"Server running. PID={server.pid}")

        # Health check
        h = requests.get(f"{BASE}/health")
        print("Health:", h.status_code, h.json())
        assert h.status_code == 200

        # Upload
        with open("sample.wav", "rb") as f:
            r = requests.post(
                f"{BASE}/transcriptions",
                files={"file": ("sample.wav", f, "audio/wav")},
            )
        print("Upload:", r.status_code, r.text)
        assert r.status_code == 202, f"Expected 202, got {r.status_code}"
        job_id = r.json()["job_id"]

        # Poll until done
        print("Polling for result (Whisper transcription running)...")
        for i in range(60):  # up to 5 minutes
            time.sleep(5)
            r2 = requests.get(f"{BASE}/transcriptions/{job_id}")
            data = r2.json()
            status = data["status"]
            print(f"  [{i+1}] status={status}")
            if status == "completed":
                print("\n=== TRANSCRIPTION RESULT ===")
                print(json.dumps(data, indent=2))
                print("\n✅ Pipeline works end-to-end!")
                sys.exit(0)
            elif status == "failed":
                print("\n❌ Transcription failed:", data.get("error"))
                sys.exit(1)

        print("Timed out waiting for transcription.")
        sys.exit(1)

    finally:
        server.terminate()
        server.wait()
        print("Server stopped.")


if __name__ == "__main__":
    main()
