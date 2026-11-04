"""Smoke test of the GUI backend through FastAPI's TestClient (no browser)."""
import io
import os
import tempfile
import time

import numpy as np
import pytest
from scipy.io import wavfile

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


def test_upload_spec_clean_audit():
    os.environ["PROVENANCE_GUI_DATA"] = tempfile.mkdtemp()
    from fastapi.testclient import TestClient
    from provenance_fx.gui.server import app

    c = TestClient(app)
    assert c.get("/").status_code == 200
    assert any(s["id"] == "demo" for s in c.get("/api/samples").json())
    sr = 8000
    t = np.arange(90 * sr) / sr
    x = (0.2 * np.sin(2 * np.pi * 120 * t) * 32767).astype(np.int16)
    buf = io.BytesIO(); wavfile.write(buf, sr, x)
    r = c.post("/api/upload", files={"file": ("t.wav", buf.getvalue(), "audio/wav")}).json()
    sid = r["session"]["id"]
    assert abs(r["session"]["duration"] - 90) < 0.5
    png = c.get(f"/api/spec.png?sid={sid}&t0=0&t1=90&w=300&h=100")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"

    def wait(job):
        for _ in range(200):
            j = c.get(f"/api/jobs/{job}").json()
            if j["status"] != "running":
                return j
            time.sleep(0.1)
        raise AssertionError("job timed out")

    j = wait(c.post("/api/clean", json={"sid": sid, "highpass_hz": 50}).json()["job"])
    assert j["status"] == "done" and j["result"]["session"]["has_clean"]
    j = wait(c.post("/api/audit", json={"sid": sid}).json()["job"])
    assert j["status"] == "done" and j["result"]["level"] in ("LOW", "MEDIUM", "HIGH")
