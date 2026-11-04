"""ENF (mains hum) tests: synthetic hum with a known answer, CSV readers, video input, GUI API."""
import io
import os
import shutil
import subprocess
import tempfile
import time

import numpy as np
import pytest
from scipy.io import wavfile

from provenance_fx.enf import detect_enf, extract_enf, hum_scan, load_raw
from provenance_fx.enf import match as M
from provenance_fx.enf import reference as R
from provenance_fx.enf import simulate as SIM
from provenance_fx.enf import audit as A

T0 = 1788000000.0  # a fixed UTC epoch for the fake reference


def _ref(hours=1.0, nominal=50, seed=3):
    f = SIM.random_grid(hours * 3600, nominal, seed=seed)
    return R.Reference(T0, 1.0, f, "fake grid", nominal, False, "test", 1.0), f


def test_hum_scan_and_extract_track_truth():
    ref, f = _ref(0.25)
    sr, x = SIM.hum_audio(f[100:700], noise=0.05, seed=2)
    s = hum_scan(x, sr)
    assert s["nominal"] == 50
    tr = extract_enf(x, sr, nominal=50)
    smooth = np.convolve(f[100:700], np.ones(8) / 8, "same")      # 8 s analysis frames
    truth = np.interp(tr.t, np.arange(600), smooth)
    ok = np.isfinite(tr.f)
    err = np.abs(tr.f[ok] - truth[ok])
    assert ok.mean() > 0.9 and np.median(err) < 0.003
    assert detect_enf(tr)["verdict"] == "present"


def test_60hz_family_detected():
    f = SIM.random_grid(400, 60, seed=5)
    sr, x = SIM.hum_audio(f, noise=0.05, seed=1)
    assert hum_scan(x, sr)["nominal"] == 60


def test_match_finds_time_and_guards():
    ref, f = _ref(1.0)
    start = 1234
    sr, x = SIM.hum_audio(f[start:start + 600], noise=0.08, seed=4, clock_ppm=30)
    tr = extract_enf(x, sr, nominal=50)
    m = M.match(tr, ref)
    assert abs(m["start_time"] - (T0 + start)) <= 2.0
    assert m["label"] in ("strong", "moderate")
    assert M.continuity(tr, ref, m)["verdict"] == "continuous"
    # 60 s clip: never labelled confident, whatever r is
    sr, x = SIM.hum_audio(f[start:start + 60], noise=0.08, seed=4)
    ms = M.match(extract_enf(x, sr, nominal=50), ref)
    assert ms["label"] == "unreliable (too short)"
    assert any("unreliable" in w for w in ms["warnings"])


def test_noise_is_not_enf():
    ref, _ = _ref(1.0)
    rng = np.random.default_rng(0)
    x = rng.normal(0, 0.1, 8000 * 400)
    tr = extract_enf(x, 8000, nominal=50)
    assert detect_enf(tr)["verdict"] != "present"
    m = M.match(tr, ref)
    assert m["label"] not in ("strong", "moderate")


def test_csv_readers(tmp_path):
    p = tmp_path / "neso.csv"
    p.write_text("dtm,f\n2026-09-01,50.010\n2026-09-01 00:00:01,50.012\n2026-09-01 00:00:03,50.02\n")
    r = R.from_csv(str(p))
    assert r.nominal == 50 and not r.relative and len(r.f) == 4 and np.isnan(r.f[2])
    assert r.label_time(r.t0).startswith("2026-09-01 00:00:00")
    q = tmp_path / "osf.csv"
    q.write_text("Time;f60_US_UT01;QI_US_UT01\n2019-05-19 02:54:06;3.0;0\n2019-05-19 02:54:07;-12.5;0\n"
                 "2019-05-19 02:54:08;1.0;2\n")
    u = R.from_csv(str(q))
    assert u.nominal == 60 and abs(u.f[1] - 59.9875) < 1e-9 and np.isnan(u.f[2])
    v = tmp_path / "unix.csv"
    v.write_text("timestamp,frequency\n1788000000,59.99\n1788000001,60.01\n")
    w = R.from_csv(str(v))
    assert w.nominal == 60 and w.t0 == 1788000000


def test_user_csv_reference_round_trip(tmp_path):
    ref, f = _ref(0.5, nominal=60, seed=9)
    lines = ["time,frequency"] + [f"{int(T0 + i)},{v:.5f}" for i, v in enumerate(f)]
    p = tmp_path / "my_logger.csv"
    p.write_text("\n".join(lines))
    r2 = R.from_csv(str(p))
    sr, x = SIM.hum_audio(f[500:1000], noise=0.05, seed=3)
    m = M.match(extract_enf(x, sr, nominal=60), r2)
    assert abs(m["start_time"] - (T0 + 500)) <= 2.0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
def test_video_input_uses_audio_track(tmp_path):
    ref, f = _ref(0.2)
    sr, x = SIM.hum_audio(f[0:200], noise=0.05, seed=7)
    wav = tmp_path / "a.wav"
    wavfile.write(str(wav), sr, (x / np.max(np.abs(x)) * 0.8 * 32767).astype(np.int16))
    mp4 = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=5",
                    "-i", str(wav), "-shortest", "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k", str(mp4)],
                   check=True)
    sr2, y, info = load_raw(str(mp4))
    assert info["has_video"] and info["n_audio"] == 1
    assert abs(len(y) / sr2 - 200) < 1.5
    assert hum_scan(y, sr2)["nominal"] == 50
    from provenance_fx.enf.media import video_flicker_enf
    vr = video_flicker_enf(str(mp4))        # phase 2: a black picture carries no light flicker -> abstain
    assert vr["available"] is True and vr["presence"]["verdict"] == "absent"


def test_privacy_verdict_levels():
    lo = A.verdict(dict(nominal=None), dict(verdict="absent"), 600)
    assert lo["level"] == "LOW"
    hi = A.verdict(dict(nominal=50), dict(verdict="present", flat=False), 900,
                   meta=dict(tags={"creation_time": "2026-01-01T00:00:00Z"}))
    assert hi["level"] == "HIGH" and any("metadata" in s for s in hi["lines"])


def test_gui_enf_api(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    os.environ["PROVENANCE_GUI_DATA"] = str(tmp_path)
    from fastapi.testclient import TestClient
    from provenance_fx.gui import server
    server.DATA = str(tmp_path)
    c = TestClient(server.app)
    ref, f = _ref(0.5)
    lines = ["time,frequency"] + [f"{int(T0 + i)},{v:.5f}" for i, v in enumerate(f)]
    rr = c.post("/api/enf/upload_ref", files={"file": ("ref.csv", "\n".join(lines).encode(), "text/csv")}).json()
    sr, x = SIM.hum_audio(f[300:700], noise=0.05, seed=11)
    buf = io.BytesIO(); wavfile.write(buf, sr, (x / np.max(np.abs(x)) * 0.8 * 32767).astype(np.int16))
    up = c.post("/api/enf/upload", files={"file": ("hum.wav", buf.getvalue(), "audio/wav")}).json()
    job = c.post("/api/enf/run", json=dict(eid=up["id"], ref_kind="file", ref_path=rr["path"])).json()["job"]
    for _ in range(120):
        j = c.get(f"/api/jobs/{job}").json()
        if j["status"] != "running":
            break
        time.sleep(0.5)
    assert j["status"] == "done", j.get("error")
    res = j["result"]
    assert abs(res["match"]["start_time"] - (T0 + 300)) <= 2.0
    assert res["detect"]["verdict"] == "present"
    for k in ("spec", "trace", "match"):
        assert c.get(res["png"][k].split("?")[0]).status_code == 200
    assert isinstance(c.get("/api/enf/samples").json(), list)


# ---------------------------------------------------------------- grid race + v2 classifier

def _fake_grids(monkeypatch, t0, n):
    from provenance_fx.enf import grids as G
    from provenance_fx.enf import reference as R
    from provenance_fx.enf.simulate import random_grid
    logs = {g: random_grid(n, 50, seed=s, sigma_mhz=30) for g, s in (("GB", 11), ("CE", 12), ("NORDIC", 13))}
    # all three hover near the same level, so only the shape of the drift can separate them
    for g in logs:
        logs[g] = logs[g] - np.mean(logs[g]) + 50.0

    def fake(grid, start, end, log=None, allow_download=True):
        if grid not in logs:
            return None
        return R.Reference(t0, 1.0, logs[grid], grid, 50, False, "synthetic", 1.0).slice(start, end)
    monkeypatch.setattr(G, "grid_reference", fake)
    return logs


def test_grid_race_picks_right_grid_and_abstains_on_noise(monkeypatch):
    from provenance_fx.enf.race import grid_race
    from provenance_fx.enf.simulate import hum_audio
    t0, n = 1.75e9, 4 * 3600
    logs = _fake_grids(monkeypatch, t0, n)
    i0 = 5000
    sr, x = hum_audio(logs["CE"][i0:i0 + 600], sr=1000, noise=0.02, seed=3, clock_ppm=20)
    tr = extract_enf(x, sr, nominal=50)
    r = grid_race(tr, t0 + i0 - 1800, t0 + i0 + 1800)
    assert r["winner"] == "CE" and r["decision"] in ("likely", "decisive")
    assert abs(r["ranking"][0]["start_time"] - (t0 + i0)) < 3
    assert {x["grid"] for x in r["ranking"]} == {"GB", "CE", "NORDIC"}
    rng = np.random.default_rng(5)
    noise = rng.normal(0, 0.1, 600 * 1000)
    trn = extract_enf(noise, 1000, nominal=50)
    rn = grid_race(trn, t0 + i0 - 1800, t0 + i0 + 1800)
    assert rn["decision"] == "abstain" and rn["winner"] is None


def test_window_from_metadata():
    from provenance_fx.enf.pipeline import window_from_meta
    w = window_from_meta({"tags": {"creation_time": "2025-06-25T19:00:00.000000Z"}}, 600)
    assert w and abs(w[0] - (1750878000 - 600 - 3600)) < 1 and abs(w[1] - (1750878000 + 3600)) < 1
    assert window_from_meta({"tags": {"creation_time": "1970-01-01T00:00:00Z"}}, 600) is None
    assert window_from_meta({}, 600) is None


def test_fingrid_parser_local_time_to_utc():
    from provenance_fx.enf.grids import _fingrid_day_csv
    rows = ["Time,Value"] + [f"2025-06-10 {h:02d}:{m:02d}:{s:02d}.{ds}00,50.0{(h % 10)}" for h in (0, 12)
                             for m in (0,) for s in (0, 1) for ds in range(10)]
    t0, f = _fingrid_day_csv(("\n".join(rows) + "\n").encode())
    # 2025-06-10 00:00 Helsinki summer time = 2025-06-09 21:00 UTC
    assert t0 == 1749502800.0
    assert abs(f[0] - 50.00) < 1e-9 and np.isfinite(f[1])


def test_classifier_v2_abstains_and_reports():
    from provenance_fx.enf import gridid
    from provenance_fx.enf.simulate import random_grid, hum_audio
    sr, x = hum_audio(random_grid(200, 50, seed=4), sr=1000, noise=0.01, seed=2)
    tr = extract_enf(x, sr, nominal=50)
    g = gridid.classify(tr, 50)
    assert g["decision"] == "unknown"           # under 300 s: must abstain
    assert set(g["probs"]) == {"GB", "CE", "NORDIC", "CHINA"}
    assert abs(sum(g["probs"].values()) - 1) < 1e-6
