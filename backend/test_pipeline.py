"""Quick end-to-end test: upload sample.wav and poll until done."""
import json
import sys
import time

import requests

BASE = "http://127.0.0.1:8000"

# 1. Health
h = requests.get(f"{BASE}/health")
print("Health:", h.status_code, h.text)
assert h.status_code == 200, "Server not running!"

# 2. Upload
with open("sample.wav", "rb") as f:
    r = requests.post(f"{BASE}/transcriptions", files={"file": ("sample.wav", f, "audio/wav")})
print("Upload:", r.status_code, r.text)
assert r.status_code == 202
job_id = r.json()["job_id"]

# 3. Poll
for i in range(40):
    time.sleep(5)
    r2 = requests.get(f"{BASE}/transcriptions/{job_id}")
    data = r2.json()
    status = data["status"]
    print(f"Poll {i+1}: {status}")
    if status in ("completed", "failed"):
        print(json.dumps(data, indent=2))
        sys.exit(0 if status == "completed" else 1)

print("Timed out waiting for transcription.")
sys.exit(1)
