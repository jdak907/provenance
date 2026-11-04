"""FastAPI backend for the Provenance GUI. Binds to 127.0.0.1 only.

Long work (cleaning, ADS-B download, the search, the audit) runs in background
threads; the browser polls /api/jobs/{id} so the page never freezes.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import shutil
import subprocess
import threading
import time
import traceback
import urllib.request
import uuid
import zipfile

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from scipy.io import wavfile

from .. import spectro
from ..cleanup import CleanSettings, clean
from .render import spec_png, thin

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DATA = os.environ.get("PROVENANCE_GUI_DATA", os.path.join(ROOT, "gui_data"))
CACHE = os.path.expanduser("~/.cache/provenance")
os.makedirs(DATA, exist_ok=True)

app = FastAPI(title="Provenance")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SESSIONS: dict = {}
JOBS: dict = {}
SPEC_CACHE: dict = {}
LOCK = threading.Lock()

# ----------------------------------------------------------------- samples

def _samples():
    out = []
    demo = os.path.join(ROOT, "demo_run", "data")
    sc_path = os.path.join(demo, "scenario.json")
    out.append(dict(
        id="demo", name="Demo scene (simulated, hidden truth)",
        note="21-minute synthetic clip, two faint propeller flyovers, 6 hours of simulated traffic.",
        available=os.path.exists(sc_path)))
    ref = os.path.join(ROOT, "raw", "reference_recording.wav")
    out.append(dict(
        id="reference", name="Author's reference recording (Long Island, 2026-09-08)",
        note="colsto's raw 1-hour recording with real ADS-B from adsb.lol. Answer: 40.8765, -73.5250.",
        available=os.path.exists(ref) and os.path.exists(
            os.path.join(ROOT, "reference_validation", "adsb_nyc_2026-09-08.csv"))))
    return out


def _sample_settings(sid):
    if sid == "demo":
        d = os.path.join(ROOT, "demo_run", "data")
        sc = json.load(open(os.path.join(d, "scenario.json")))
        return os.path.join(d, "recording.wav"), dict(
            bbox=sc["bbox"], start=sc["search_window_unix"][0], end=sc["search_window_unix"][1],
            time_known=False, clip_start=None, adsb_mode="file", adsb_path=os.path.join(d, "adsb.csv"),
            dem_mode="file", dem_path=os.path.join(d, "dem.npz"), grid_m=200, events="", fmin=30, fmax=250,
            height=2, max_gap=60, truth=os.path.join(d, "truth_HIDDEN.json"))
    if sid == "reference":
        rv = os.path.join(ROOT, "reference_validation")
        dem = os.path.join(rv, "dem_terrarium_z12.npz")
        return os.path.join(ROOT, "raw", "reference_recording.wav"), dict(
            bbox=[40.60, 41.10, -73.90, -73.20], start=1788825600.0, end=1788912000.0, time_known=False,
            clip_start=None, adsb_mode="file", adsb_path=os.path.join(rv, "adsb_nyc_2026-09-08.csv"),
            dem_mode="file" if os.path.exists(dem) else "auto", dem_path=dem, grid_m=200,
            events="2090-2225,3035-3110", fmin=85, fmax=185, height=4, max_gap=300, truth=None,
            author_answer=[40.876466, -73.524951])
    raise HTTPException(404, "unknown sample")


# ----------------------------------------------------------------- jobs

def _new_job(kind):
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = dict(id=jid, kind=kind, status="running", progress=0.0, log=[], result=None,
                     error=None, started=time.time())
    return JOBS[jid]


def _log(job, msg, progress=None):
    stamp = time.strftime("%H:%M:%S")
    job["log"].append(f"[{stamp}] {msg}")
    if progress is not None:
        job["progress"] = max(job["progress"], float(progress))


def _run_in_thread(job, fn):
    def wrap():
        try:
            job["result"] = fn(job)
            job["status"] = "done"
            job["progress"] = 1.0
        except Exception as e:  # report, never crash the server
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"
            _log(job, "ERROR " + job["error"])
            job["log"].append(traceback.format_exc()[-1500:])
    threading.Thread(target=wrap, daemon=True).start()


@app.get("/api/jobs/{jid}")
def job_status(jid: str, since: int = 0):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    return dict(id=jid, kind=j["kind"], status=j["status"], progress=j["progress"],
                log=j["log"][since:], n_log=len(j["log"]), error=j["error"],
                result=j["result"] if j["status"] == "done" else None,
                elapsed=round(time.time() - j["started"], 1))


# ----------------------------------------------------------------- sessions and audio

def _new_session(src_path, name):
    sid = uuid.uuid4().hex[:10]
    d = os.path.join(DATA, sid)
    os.makedirs(d, exist_ok=True)
    wav = os.path.join(d, "original.wav")
    if src_path.lower().endswith(".wav"):
        sr, x = wavfile.read(src_path)
        if x.ndim > 1 or sr > 16000:
            _ffmpeg_to_wav(src_path, wav)
        else:
            shutil.copy(src_path, wav)
    else:
        _ffmpeg_to_wav(src_path, wav)
    sr, x = wavfile.read(wav)
    SESSIONS[sid] = dict(id=sid, dir=d, name=name, original=wav, cleaned=None, duration=len(x) / sr,
                         sr=int(sr), clean_settings=None, last_result=None, settings=None)
    return SESSIONS[sid]


def _ffmpeg_to_wav(src, dst):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vn", "-ac", "1", "-ar", "8000",
                        "-sample_fmt", "s16", dst], capture_output=True, text=True)
    if r.returncode != 0:
        raise HTTPException(400, f"ffmpeg could not read this file: {r.stderr[-300:]}")


def _sess(sid):
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "session not found (the server may have restarted); load the file again")
    return s


def _spec(sid, which, fmin=30.0, fmax=400.0):
    s = _sess(sid)
    path = s["cleaned"] if which == "clean" and s["cleaned"] else s["original"]
    key = (path, os.path.getmtime(path), fmin, fmax)
    with LOCK:
        if key not in SPEC_CACHE:
            sr, x = spectro.load_audio(path)
            SPEC_CACHE[key] = spectro.compute(x, sr, fmin=fmin, fmax=fmax)
            if len(SPEC_CACHE) > 6:
                SPEC_CACHE.pop(next(iter(SPEC_CACHE)))
        return SPEC_CACHE[key]


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/samples")
def samples():
    return _samples()


class SampleReq(BaseModel):
    id: str


@app.post("/api/load_sample")
def load_sample(req: SampleReq):
    if req.id == "demo" and not os.path.exists(os.path.join(ROOT, "demo_run", "data", "scenario.json")):
        from ..simulate import build_scene
        build_scene(os.path.join(ROOT, "demo_run", "data"))
    path, settings = _sample_settings(req.id)
    s = _new_session(path, os.path.basename(path))
    s["settings"] = settings
    return dict(session=_public(s), settings=settings)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    tmp = os.path.join(DATA, "upload_" + uuid.uuid4().hex[:8] + "_" + os.path.basename(file.filename or "f"))
    with open(tmp, "wb") as fh:
        while chunk := await file.read(1 << 20):
            fh.write(chunk)
    try:
        s = _new_session(tmp, file.filename)
    finally:
        os.unlink(tmp)
    return dict(session=_public(s))


@app.post("/api/upload_adsb")
async def upload_adsb(file: UploadFile = File(...)):
    d = os.path.join(DATA, "adsb_uploads")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, uuid.uuid4().hex[:6] + "_" + os.path.basename(file.filename or "adsb.csv"))
    with open(path, "wb") as fh:
        while chunk := await file.read(1 << 20):
            fh.write(chunk)
    return dict(path=path, name=file.filename)


def _public(s):
    return {k: s[k] for k in ("id", "name", "duration", "sr", "clean_settings")} | dict(
        has_clean=bool(s["cleaned"]))


@app.get("/api/spec.png")
def spec_image(sid: str, which: str = "orig", t0: float = 0, t1: float = 1e9, f0: float = 30,
               f1: float = 400, w: int = 1200, h: int = 420, mode: str = "bright"):
    sp = _spec(sid, which)
    png = spec_png(sp, t0, min(t1, sp.t[-1]), f0, f1, min(w, 2400), min(h, 1200), mode)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/audio/{sid}/{which}.wav")
def audio_file(sid: str, which: str):
    s = _sess(sid)
    path = s["cleaned"] if which == "clean" and s["cleaned"] else s["original"]
    return FileResponse(path, media_type="audio/wav")


class CleanReq(BaseModel):
    sid: str
    trim_start: float = 0.0
    trim_end: float | None = None
    highpass_hz: float = 0.0
    lowpass_hz: float = 0.0
    remove_steady: bool = True
    denoise: float = 0.0
    gain_db: float = 0.0


@app.post("/api/clean")
def do_clean(req: CleanReq):
    s = _sess(req.sid)
    st = CleanSettings(**{k: v for k, v in req.model_dump().items() if k != "sid"})
    job = _new_job("clean")

    def work(job):
        _log(job, "reading audio", 0.1)
        sr, x = wavfile.read(s["original"])
        x = x.astype(np.float64) / (np.max(np.abs(x)) or 1)
        _log(job, f"cleaning: {st.to_dict()}", 0.3)
        y, osr = clean(x, sr, st)
        out = os.path.join(s["dir"], "cleaned.wav")
        wavfile.write(out, osr, (y * 32767).astype(np.int16))
        s["cleaned"], s["clean_settings"] = out, st.to_dict()
        _log(job, "computing spectrogram", 0.8)
        _spec(req.sid, "clean")
        _log(job, f"done: {len(y) / osr:.0f} s of cleaned audio", 1.0)
        return dict(session=_public(s), trim_offset=st.trim_start)

    _run_in_thread(job, work)
    return dict(job=job["id"])


# ----------------------------------------------------------------- ADS-B from adsb.lol

def _adsblol_csv(date: str, bbox, job):
    """Download (cached) the adsb.lol day archive and cut out the search box."""
    from ..readsb_hist import convert

    y = date[:4]
    tag = f"v{date.replace('-', '.')}-planes-readsb-prod-0"
    d = os.path.join(CACHE, "adsblol", tag)
    os.makedirs(d, exist_ok=True)
    key = "_".join(f"{v:.3f}" for v in bbox)
    out = os.path.join(d, f"box_{key}.csv")
    if os.path.exists(out):
        _log(job, f"ADS-B: using cached extract {out}")
        return out
    api = f"https://api.github.com/repos/adsblol/globe_history_{y}/releases/tags/{tag}"
    with urllib.request.urlopen(api, timeout=30) as r:
        rel = json.load(r)
    assets = sorted(rel.get("assets", []), key=lambda a: a["name"])
    if not assets:
        raise RuntimeError(f"adsb.lol has no archive for {date}")
    total = sum(a["size"] for a in assets)
    got = 0
    parts = []
    for a in assets:
        dst = os.path.join(d, a["name"])
        parts.append(dst)
        if os.path.exists(dst) and os.path.getsize(dst) == a["size"]:
            got += a["size"]
            continue
        _log(job, f"ADS-B: downloading {a['name']} ({a['size'] / 1e9:.1f} GB)")
        with urllib.request.urlopen(a["browser_download_url"], timeout=60) as r, open(dst, "wb") as fh:
            while True:
                buf = r.read(1 << 22)
                if not buf:
                    break
                fh.write(buf)
                got += len(buf)
                job["progress"] = 0.05 + 0.25 * got / total
    _log(job, "ADS-B: extracting flights inside the search box (a few minutes)", 0.3)

    class Cat(io.RawIOBase):
        def __init__(self, paths):
            self.fhs = [open(p, "rb") for p in paths]
            self.i = 0

        def readable(self):
            return True

        def readinto(self, b):
            while self.i < len(self.fhs):
                n = self.fhs[self.i].readinto(b)
                if n:
                    return n
                self.i += 1
            return 0

    convert(io.BufferedReader(Cat(parts), 1 << 20), bbox, out, log=lambda m: _log(job, "ADS-B: " + m))
    return out


# ----------------------------------------------------------------- run

class RunReq(BaseModel):
    sid: str
    use_clean: bool = True
    bbox: list
    start: float
    end: float
    time_known: bool = False
    clip_start: float | None = None
    adsb_mode: str = "file"          # file | adsblol
    adsb_path: str | None = None
    adsb_date: str | None = None
    dem_mode: str = "auto"           # auto | flat | file
    dem_path: str | None = None
    grid_m: float = 200.0
    events: str = ""
    fmin: float = 30.0
    fmax: float = 250.0
    height: float = 2.0
    max_gap: float = 60.0
    truth: str | None = None


STAGE_PROGRESS = [("event", 0.35), ("loaded", 0.42), ("grid", 0.45), ("flights in window", 0.5),
                  ("CPA table", 0.65), ("offset filter", 0.7), ("silence filter", 0.72),
                  ("scoring", 0.75), ("done in", 0.92), ("BEST", 0.95)]


@app.post("/api/run")
def run(req: RunReq):
    s = _sess(req.sid)
    job = _new_job("locate")

    def work(job):
        from ..cli import do_locate
        from .results import build_payload

        audio = s["cleaned"] if (req.use_clean and s["cleaned"]) else s["original"]
        offset = (s["clean_settings"] or {}).get("trim_start", 0.0) if audio == s["cleaned"] else 0.0
        bbox = [float(v) for v in req.bbox]
        if req.adsb_mode == "adsblol":
            if not req.adsb_date:
                raise ValueError("pick a date for the adsb.lol archive")
            adsb = _adsblol_csv(req.adsb_date, bbox, job)
        else:
            if not req.adsb_path or not os.path.exists(req.adsb_path):
                raise ValueError("no ADS-B file chosen")
            adsb = req.adsb_path
        dem = {"auto": "auto", "flat": None}.get(req.dem_mode, req.dem_path)
        events = None
        if req.events.strip():
            events = []
            for part in req.events.split(","):
                a, b = part.split("-")
                events.append((float(a) - offset, float(b) - offset))
        clip_start = None
        if req.time_known and req.clip_start:
            clip_start = float(req.clip_start) + offset
        out_dir = os.path.join(s["dir"], "run_" + time.strftime("%H%M%S"))

        def log(msg):
            p = None
            for key, val in STAGE_PROGRESS:
                if str(msg).startswith(key) or key in str(msg)[:20]:
                    p = val
            _log(job, str(msg), p)

        _log(job, f"audio: {os.path.basename(audio)}  box: {bbox}", 0.32)
        res, summary = do_locate(audio, adsb, dem, bbox, (req.start, req.end), out_dir, events=events,
                                 clip_start=clip_start, truth_path=req.truth, grid_m=req.grid_m,
                                 obs_height=req.height, fmin=req.fmin, fmax=req.fmax,
                                 max_events=1 if req.time_known and events and len(events) == 1 else 2,
                                 max_gap_s=req.max_gap, log=log)
        _log(job, "building interactive results", 0.96)
        payload = build_payload(res, res.spec, res.events, res.ridges, res.dem)
        payload["time_offset"] = offset
        payload["report_dir"] = out_dir
        payload["summary_error_m"] = summary.get("error_m")
        if req.truth and os.path.exists(req.truth):
            tj = json.load(open(req.truth))
            payload["truth"] = [tj["observer_lat"], tj["observer_lon"]]
        s["last_result"] = out_dir
        json.dump(payload, open(os.path.join(out_dir, "gui_payload.json"), "w"))
        return payload

    _run_in_thread(job, work)
    return dict(job=job["id"])


@app.get("/api/export/{sid}/{kind}")
def export(sid: str, kind: str):
    s = _sess(sid)
    d = s.get("last_result")
    if not d:
        raise HTTPException(404, "run an analysis first")
    if kind == "report.md":
        return FileResponse(os.path.join(d, "report.md"), filename="provenance_report.md")
    if kind == "result.json":
        return FileResponse(os.path.join(d, "gui_payload.json"), filename="provenance_result.json")
    if kind == "map.png":
        return FileResponse(os.path.join(d, "fig_map.png"), filename="provenance_map.png")
    if kind == "report.zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in os.listdir(d):
                if f.endswith((".md", ".png", ".json")):
                    z.write(os.path.join(d, f), f)
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": "attachment; filename=provenance_report.zip"})
    raise HTTPException(404, "unknown export")


# ----------------------------------------------------------------- audit

class AuditReq(BaseModel):
    sid: str
    use_clean: bool = False
    highpass: float = 300.0


@app.post("/api/audit")
def audit(req: AuditReq):
    s = _sess(req.sid)
    job = _new_job("audit")

    def work(job):
        from .. import audit as A

        path = s["cleaned"] if (req.use_clean and s["cleaned"]) else s["original"]
        lines = []
        _log(job, "scanning for Doppler flyover curves", 0.2)
        found = A.audit(path, req.highpass or None, out=lines.append)
        sr, x = spectro.load_audio(path)
        sp = spectro.compute(x, sr)
        curves = []
        for m in found:
            r = spectro.trace_ridge(sp, m.t_start, m.t_end)
            curves.append(dict(m.to_dict(), ridge=thin(r[0], r[1], 400)))
        level = "LOW" if not found else ("HIGH" if len(found) >= 2 else "MEDIUM")
        return dict(level=level, lines=lines, curves=curves, which="clean" if path == s["cleaned"] else "orig",
                    duration=float(sp.t[-1]))

    _run_in_thread(job, work)
    return dict(job=job["id"])


from .enf_api import router as _enf_router  # noqa: E402

app.include_router(_enf_router)


def serve(host="127.0.0.1", port=8765, open_browser=True):
    import uvicorn

    if host not in ("127.0.0.1", "localhost"):
        raise SystemExit("provenance gui only binds to localhost.")
    if open_browser:
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(f"http://{host}:{port}/")).start()
    print(f"Provenance GUI on http://{host}:{port}/  (Ctrl+C to stop)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
