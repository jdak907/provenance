"""Video light-flicker ENF (phase 2) on small SIMULATED renders: rolling shutter, read-out search, the aliased
frame-mean path, abstain cases, keyframe-pumping guard, audio-vs-picture agreement and the CLI/API flags."""
import json
import os
import shutil
import subprocess
import sys

import numpy as np
import pytest

from provenance_fx.enf import video as V
from provenance_fx.enf.extract import EnfTrace
from provenance_fx.enf.simulate import random_grid

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                reason="needs ffmpeg")
SMALL = dict(H=144, W=192, preset="ultrafast", seconds=75)


def _render(tmp_path, name, f, **kw):
    from provenance_fx.enf.video_sim import render_video
    p = str(tmp_path / name)
    render_video(p, f, **{**SMALL, **kw})
    return p


def _score(tr, f):
    ok = np.isfinite(tr.f)
    tt = np.clip(np.round(tr.t[ok]).astype(int), 0, len(f) - 1)
    return float(np.corrcoef(tr.f[ok], f[tt])[0, 1]), float(np.sqrt(np.mean((tr.f[ok] - f[tt]) ** 2)) * 1000)


@pytest.fixture(scope="module")
def grid60():
    return random_grid(120, nominal=60, seed=11)


def test_alias_and_constants():
    assert abs(V.alias_of(120, 30)) < 1e-9                 # exact 30 fps on 60 Hz: alias at 0 -> refused
    assert abs(abs(V.alias_of(120, 30000 / 1001)) - 0.1199) < 1e-3
    assert abs(abs(V.alias_of(100, 30000 / 1001)) - 10.0899) < 1e-3
    assert abs(V.alias_of(100, 25)) < 1e-9


def test_rolling_shutter_searched_readout(tmp_path, grid60):
    p = _render(tmp_path, "rs.mp4", grid60, fps="30000/1001", readout_ms=25, seed=1, gop=60)
    r = V.analyze_video(p)
    assert r["path_used"] == "rolling shutter" and r["nominal"] == 60
    assert r["presence"]["verdict"] in ("present", "weak")
    assert abs(r["readout_ms"] - 25) < 1.0 and r["readout_source"] == "searched" and r["band_seen"]
    rr, rmse = _score(r["_trace_any"], grid60)
    assert rr > 0.8 and rmse < 10


def test_rolling_shutter_entered_readout(tmp_path, grid60):
    p = _render(tmp_path, "rs30.mp4", grid60, fps="30", readout_ms=20, seed=2, gop=60)
    r = V.analyze_video(p, readout_ms=20, nominal=60)
    assert r["path_used"] == "rolling shutter" and r["readout_source"] == "entered"
    assert r["readout_search"] is None
    rr, _ = _score(r["_trace_any"], grid60)
    assert rr > 0.8


def test_global_shutter_alias_50hz(tmp_path):
    f = random_grid(120, nominal=50, seed=12)
    p = _render(tmp_path, "gs.mp4", f, fps="30000/1001", readout_ms=0, seed=3)
    r = V.analyze_video(p)
    assert r["path_used"] == "frame mean" and r["nominal"] == 50 and abs(abs(r["alias_hz"]) - 10.09) < 0.01
    assert r["presence"]["verdict"] in ("present", "weak")
    rr, _ = _score(r["_trace_any"], f)
    assert rr > 0.7


@pytest.mark.parametrize("kw", [dict(flicker=False), dict(exposure_s=1 / 120), dict(readout_ms=0, fps="30")],
                         ids=["no-flicker", "anti-banding", "global-30fps-alias-0"])
def test_abstains(tmp_path, grid60, kw):
    p = _render(tmp_path, "neg.mp4", grid60, **{**dict(fps="30000/1001", readout_ms=25, seed=4), **kw})
    r = V.analyze_video(p)
    assert r["presence"]["verdict"] == "absent", r["presence"]
    assert r["_trace"] is None


def test_too_short(tmp_path, grid60):
    p = _render(tmp_path, "short.mp4", grid60, seconds=12, fps="30", readout_ms=20)
    r = V.analyze_video(p)
    assert "too short" in r["status"] and r["presence"]["verdict"] == "absent"


def test_keyframe_pumping_detector():
    fps = 30000 / 1001
    n = int(fps * 120)
    k = np.arange(n)
    saw = 0.002 * ((k % 250) / 250.0)                          # brightness creeping up between keyframes
    keys = list(np.arange(0, n, 250) / fps)
    rng = np.random.default_rng(0)
    pump = V.gop_pumping(saw + rng.normal(0, 2e-5, n), fps, keys)
    assert pump["regular"] and abs(pump["gop_s"] - 250 / fps) < 0.01 and V.pump_present(pump)
    sine = 0.002 * np.cos(2 * np.pi * (fps / 250) * k / fps + np.cumsum(rng.normal(0, 0.002, n)))
    clean = V.gop_pumping(sine + rng.normal(0, 2e-5, n), fps, keys)
    assert not V.pump_present(clean)


def _tr(f, nominal=60, frame_s=8.0):
    t = np.arange(len(f), dtype=float)
    return EnfTrace(t=t, f=np.asarray(f, float), snr_db=np.full(len(f), 20.0), nominal=nominal, harmonics_used=[2],
                    harmonic_snr_db={2: 20.0}, harmonic_corr={2: 1.0}, frame_s=frame_s, hop_s=1.0)


def test_av_agreement_verdicts():
    g = random_grid(600, nominal=60, seed=21)
    h = random_grid(600, nominal=60, seed=22)
    pres = dict(verdict="present")
    a = V.av_agreement(_tr(g), _tr(g + 0.0005), pres, pres)
    assert a["verdict"] == "agree" and a["r_best"] > 0.95
    a = V.av_agreement(_tr(g), _tr(h), pres, pres)
    assert a["verdict"] in ("disagree", "partly disagree")
    sp = g.copy(); sp[300:] = h[300:]
    a = V.av_agreement(_tr(sp), _tr(g), pres, pres)
    assert a["verdict"] == "partly disagree" and "splice" in a["hint"]
    a = V.av_agreement(_tr(g), _tr(np.roll(g, 6)), pres, pres)
    assert a["verdict"] == "agree with an offset" and abs(a["best_lag_s"]) == 6
    assert V.av_agreement(None, _tr(g))["verdict"] == "not comparable"


def test_cli_video_flags(tmp_path, grid60):
    from provenance_fx import cli
    p = _render(tmp_path, "av.mp4", random_grid(200, nominal=60, seed=13), seconds=150, fps="30000/1001",
                readout_ms=25, seed=5, gop=60,
                audio_f_1s=random_grid(200, nominal=60, seed=13), audio_snr_db=5)
    out = tmp_path / "o"
    rc = subprocess.run([sys.executable, "-m", "provenance_fx.cli", "enf", p, "--ref", "none", "--no-race",
                         "--video", "on", "--readout-ms", "25", "--out", str(out)], capture_output=True, text=True,
                        cwd=os.path.dirname(os.path.dirname(os.path.abspath(cli.__file__))))
    assert rc.returncode == 0, rc.stderr[-2000:]
    assert "VIDEO FLICKER" in rc.stdout and "AUDIO vs PICTURE" in rc.stdout, rc.stdout[-1500:]
    res = json.load(open(out / "enf_result.json"))
    assert res["video"]["readout_source"] == "entered" and res["video"]["readout_ms"] == 25
    assert res["av_agreement"]["verdict"] in ("agree", "agree with an offset", "inconclusive")
    assert (out / "enf_video.png").exists()
    rc = subprocess.run([sys.executable, "-m", "provenance_fx.cli", "enf", p, "--ref", "none", "--no-race",
                         "--video", "off"], capture_output=True, text=True,
                        cwd=os.path.dirname(os.path.dirname(os.path.abspath(cli.__file__))))
    assert rc.returncode == 0 and "VIDEO FLICKER" not in rc.stdout


def test_api_request_fields():
    pytest.importorskip("fastapi")
    from provenance_fx.gui.enf_api import RunReq
    r = RunReq(eid="x", ref_kind="none", video="off", readout_ms=18.5)
    assert r.video == "off" and r.readout_ms == 18.5
    assert RunReq(eid="x", ref_kind="none").video == "auto"
