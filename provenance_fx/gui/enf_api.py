"""ENF tab endpoints. Always analyses the RAW audio track (never Provenance's cleaned audio)."""
from __future__ import annotations

import os
import threading
import shutil
import time
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from provenance_fx.enf.reference import DATA as _DATA  # noqa: E402

router = APIRouter(prefix="/api/enf")
ENF = {}          # eid -> dict(path, name, dir, meta, last)
WHU = os.path.join(_DATA, "ENF-WHU-Dataset/ENF-WHU-Dataset")
LIVE = os.path.join(_DATA, "live_uk")
US = os.path.join(_DATA, "us/samples")
VIDEO = os.path.join(_DATA, "video_samples")   # simulated flicker videos (scripts/enf_make_video_samples.py)


def _ctx():
    from . import server
    return server


def _dir():
    d = os.path.join(_ctx().DATA, "enf")
    os.makedirs(d, exist_ok=True)
    return d


def _whu_dayref(i):
    """24 h WHU mains reference as cached NPZ (built from the WAV on first use)."""
    import re
    import numpy as np
    from ..enf import reference as R
    for fn in os.listdir(os.path.join(WHU, "H1_ref_one_day")):
        m = re.match(r"(\d+)(?:-(\d+))?_ref\.wav", fn)
        if m and int(m.group(1)) <= i <= int(m.group(2) or m.group(1)):
            cache = os.path.expanduser(f"~/.cache/provenance/enf/whu/{fn}.npz")
            out = os.path.join(_dir(), f"whu_{fn}.npz")
            if not os.path.exists(out):
                if not os.path.exists(cache):
                    r = R.from_wav(os.path.join(WHU, "H1_ref_one_day", fn))
                    os.makedirs(os.path.dirname(cache), exist_ok=True)
                    np.savez(cache, t0=r.t0, f=r.f)
                z = np.load(cache)
                np.savez(out, t0=z["t0"], step=1.0, f=z["f"], nominal=50, relative=True, name=f"ENF-WHU 24 h mains ({fn})")
            return out
    return None


SAMPLES = [
    dict(id="whu120", name="ENF-WHU #120 · Wuhan, China (50 Hz)",
         note="Real 10-min recording, MIT license. Matched inside its 24 h mains reference; truth known.",
         path=f"{WHU}/H1/120.wav", ref="whu", whu=120),
    dict(id="whu003", name="ENF-WHU #003 · Wuhan (harder, noisy)",
         note="8-min recording with faint hum; 24 h mains reference.", path=f"{WHU}/H1/003.wav", ref="whu", whu=3),
    dict(id="lhr", name="Heathrow live cam audio · London (GB, 50 Hz)",
         note="30 min captured 2026-11-03 16:17:14 UTC from a public 24/7 stream; GB reference (Elexon 15 s).",
         path=f"{LIVE}/rec_SgvpyjQX_HM.m4a", ref="gb", start="2026-11-03T15:17:00", end="2026-11-03T17:17:00"),
    dict(id="us_race", name="US West 2024 · simulated phone clip · grid race ±1 h",
         note="SIMULATED: 15 min cut from the real Zenodo 2024 WECC log (true start 2024-10-08 14:20:00 UTC), pushed through "
              "the mic simulator. Races US grids plus GB / CE / Nordic as controls.",
         path=f"{US}/sim_wecc2024.wav", ref="none", start="2024-10-08T13:20:00", end="2024-10-08T15:20:00", nominal=60,
         cross_nominal=True),
    dict(id="us_seis", name="US West 2024 · seismic log alone · grid race ±1 h",
         note="SIMULATED: 15 min cut from Zenodo on 2024-04-17 (true start 18:40:00 UTC, a held-out test day), raced with the "
              "Zenodo log LEFT OUT, so US West is covered only by the seismometer consensus 'US West (seismic)'.",
         path=f"{US}/sim_wecc2024_seis.wav", ref="none", start="2024-04-17T17:40:00", end="2024-04-17T19:40:00", nominal=60,
         cross_nominal=True, exclude=["zenodo_wecc_2024"]),
    dict(id="us_live", name="US West today · clip vs the live seismic collector",
         note="SIMULATED: 25 min built from an archive rebuild of 2026-11-03 (true start 21:12:00 UTC), raced against the "
              "file that `provenance enf-collect` wrote live on this computer. Same stations, so this checks loading, not accuracy.",
         path=f"{US}/sim_live_20261103.wav", ref="none", start="2026-11-03T20:40:00", end="2026-11-03T21:45:00", nominal=60,
         cross_nominal=True),
    dict(id="us_find", name="US West 2024 · find the time in 10 months (no hint)",
         note="Same simulated clip, matched against ALL of the 2024 WECC log (Jan 16 to Nov 18). Truth: 2024-10-08 14:20:00 UTC.",
         path=f"{US}/sim_wecc2024.wav", ref="grid:US-WEST", start="2024-01-16T23:40:00", end="2024-11-18T13:00:00", nominal=60,
         race=False),
    dict(id="us_4way", name="US 2026 · four-way race on the FNET gauge scrape (low trust)",
         note="SIMULATED from the nate-griff FNET scrape (true start 2026-04-15 18:05:00 UTC). West, East, Texas and Quebec "
              "all have logs then, so this is a real four-way race; the answer is capped at 'likely' (low-trust source).",
         path=f"{US}/sim_ng2026.wav", ref="none", start="2026-04-15T17:05:00", end="2026-04-15T19:05:00", nominal=60),
    dict(id="us_phx", name="Phoenix 2022 · Pigott 5 s log, clock-offset search",
         note="SIMULATED from John Pigott's Phoenix log (true start 2022-07-20 03:10:00 UTC). The log's clock offset (MST) "
              "was inferred, so the race also tries -1 h, +1 h and +7 h.",
         path=f"{US}/sim_phx2022.wav", ref="none", start="2022-07-20T02:10:00", end="2022-07-20T04:10:00", nominal=60),
    dict(id="york", name="York railcam VIDEO · inverter hum (negative)",
         note="6-min mp4: clear 50 Hz hum that does NOT follow the grid (sits at 50.00 Hz).",
         path=f"{LIVE}/video_4P2n_wCQAHo.mp4", ref="gb", start="2026-11-03T15:18:00", end="2026-11-03T17:18:00"),
    dict(id="ribble", name="Ribblehead railcam archive · Yorkshire (GB), 2025-05-06",
         note="20 min of an archived UK live stream; blind search over 2 days of NESO 1 s data.",
         path=os.path.join(_DATA, "railcam_vod/vod_vSOuVeHI2KY.m4a"), ref="gb",
         start="2025-05-05T09:41:00", end="2025-05-07T09:41:00"),
    dict(id="race_sampler", name="Grid race · Railcam UK Sampler archive (2025-06-25)",
         note="20 min of an archived UK stream. Window ±2 h around YouTube's time; races GB (NESO) vs Continental Europe "
              "(Energy-Charts) vs Nordic (Fingrid).",
         path=os.path.join(_DATA, "railcam_vod/vod_dQze_bvWgaw.m4a"), ref="none",
         start="2025-06-25T16:58:41", end="2025-06-25T20:58:41", nominal=50),
    dict(id="race_lhr", name="Grid race · Heathrow live audio (±1 h)",
         note="Live capture 2026-11-03 16:17 UTC. Races GB (Elexon) vs Continental Europe; Nordic not published yet.",
         path=f"{LIVE}/rec_SgvpyjQX_HM.m4a", ref="none", start="2026-11-03T15:17:00", end="2026-11-03T17:17:00"),
    dict(id="vid_av", name="VIDEO · US West 2024 · lamp flicker + hum agree",
         note="SIMULATED 6-min phone-style video (29.97 fps, rolling shutter 25 ms, H.264) of a lamp-lit room, flicker and hum "
              "both from the real Zenodo WECC log. True start 2024-05-12 18:00:00 UTC. Picture and sound should agree.",
         path=f"{VIDEO}/vid_wecc_av.mp4", ref="none", start="2024-05-12T17:50:00", end="2024-05-12T18:10:00"),
    dict(id="vid_splice", name="VIDEO · audio replaced after 3 min (splice test)",
         note="SIMULATED: same picture as above, but the sound after 180 s comes from 11 hours later. The picture race still "
              "works; audio vs picture should say 'partly disagree'.",
         path=f"{VIDEO}/vid_wecc_splice.mp4", ref="none", start="2024-05-12T17:50:00", end="2024-05-12T18:10:00"),
    dict(id="vid_silent", name="VIDEO · no audio track · picture only (30 fps, read-out entered)",
         note="SIMULATED silent video, exactly 30 fps, read-out 20 ms (entered). True start 2024-09-19 03:30:00 UTC, US West.",
         path=f"{VIDEO}/vid_wecc_silent.mp4", ref="none", start="2024-09-19T03:20:00", end="2024-09-19T03:40:00",
         readout_ms=20),
    dict(id="vid_gb_global", name="VIDEO · GB 2024 · global shutter (aliased flicker)",
         note="SIMULATED global-shutter camera at 29.97 fps on a 50 Hz grid: the 100 Hz flicker aliases to about 10.09 Hz in "
              "the frame brightness. NESO log, true start 2024-09-14 20:15:00 UTC.",
         path=f"{VIDEO}/vid_gb_global.mp4", ref="none", start="2024-09-14T20:05:00", end="2024-09-14T20:25:00"),
    dict(id="vid_antiband", name="VIDEO · anti-banding exposure 1/120 s (picture should abstain)",
         note="SIMULATED: exposure set to exactly 1/120 s, which averages the flicker out. The hum still dates it; the picture "
              "should abstain.",
         path=f"{VIDEO}/vid_wecc_antiband.mp4", ref="none", start="2024-05-12T17:50:00", end="2024-05-12T18:10:00"),
    dict(id="whu_h0", name="ENF-WHU O05 · no mains hum (negative)",
         note="Control recording without ENF.", path=f"{WHU}/H0/O05.wav", ref="whu", whu=5),
]


@router.get("/coverage")
def coverage():
    """Which grid logs exist for which dates, so users can see when a race is possible."""
    from ..enf import grids as G
    return G.coverage()


@router.get("/samples")
def samples():
    return [dict(id=s["id"], name=s["name"], note=s["note"], available=os.path.exists(s["path"])) for s in SAMPLES]


def _register(path, name, keep=False):
    from ..enf.media import probe_media
    eid = uuid.uuid4().hex[:10]
    d = os.path.join(_dir(), eid)
    os.makedirs(d, exist_ok=True)
    meta = probe_media(path)
    if meta.get("n_audio") == 0 and not meta.get("has_video"):
        raise HTTPException(400, "this file has no audio track and no picture")
    ENF[eid] = dict(id=eid, path=path, name=name, dir=d, meta=meta, last=None)
    return dict(id=eid, name=name, meta=meta)


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    d = os.path.join(_dir(), "uploads")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, uuid.uuid4().hex[:6] + "_" + os.path.basename(file.filename or "media"))
    with open(path, "wb") as fh:
        while chunk := await file.read(1 << 20):
            fh.write(chunk)
    return _register(path, file.filename)


@router.post("/upload_ref")
async def upload_ref(file: UploadFile = File(...)):
    d = os.path.join(_dir(), "refs")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, uuid.uuid4().hex[:6] + "_" + os.path.basename(file.filename or "ref.csv"))
    with open(path, "wb") as fh:
        while chunk := await file.read(1 << 20):
            fh.write(chunk)
    try:
        from ..enf import reference as R
        info = R.load_any(path).info()
    except Exception as e:
        raise HTTPException(400, f"could not read reference: {e}")
    return dict(path=path, name=file.filename, info=info)


class SampleReq(BaseModel):
    id: str


@router.post("/load_sample")
def load_sample(req: SampleReq):
    s = next((x for x in SAMPLES if x["id"] == req.id), None)
    if not s or not os.path.exists(s["path"]):
        raise HTTPException(404, "sample not available on this machine")
    out = _register(s["path"], os.path.basename(s["path"]))
    rk = s["ref"] if s["ref"].startswith("grid:") else {"gb": "gb", "none": "none"}.get(s["ref"], "file")
    st = dict(ref_kind=rk, start=s.get("start"), end=s.get("end"), nominal=s.get("nominal"),
              cross_nominal=bool(s.get("cross_nominal")), race=s.get("race", True), exclude_logs=s.get("exclude", []),
              video=s.get("video", "auto"), readout_ms=s.get("readout_ms"))
    if s["ref"] == "whu":
        st["ref_path"] = _whu_dayref(s["whu"])
        st["ref_name"] = os.path.basename(st["ref_path"])
    out["settings"] = st
    return out


def _clean(o):
    """JSON-safe copy: NaN / inf -> None, numpy scalars -> Python."""
    import math
    import numpy as _np
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, _np.ndarray):
        return [_clean(v) for v in o.tolist()]
    if isinstance(o, _np.generic):
        o = o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


class FromSession(BaseModel):
    sid: str


@router.post("/from_session")
def from_session(req: FromSession):
    s = _ctx()._sess(req.sid)
    # the session's original.wav: mono 8 kHz copy of the upload, never the cleaned file
    return _register(s["original"], s["name"] + " (original, not cleaned)")


class RunReq(BaseModel):
    eid: str
    ref_kind: str = "gb"        # gb | file | none
    ref_path: str | None = None
    start: str | None = None
    end: str | None = None
    nominal: int | None = None
    race: bool = True
    use_meta: bool = True
    cross_nominal: bool = False
    exclude_logs: list[str] = []   # us_refs source keys to leave out, e.g. ["zenodo_wecc_2024"] to race the seismic log alone
    video: str = "auto"            # auto | on | off: light-flicker ENF from the picture
    readout_ms: float | None = None   # rolling-shutter read-out time; blank = search it


_EXCL_LOCK = threading.Lock()


@router.post("/run")
def run(req: RunReq):
    srv = _ctx()
    e = ENF.get(req.eid)
    if not e:
        raise HTTPException(404, "file not found (server restarted?); load it again")
    job = srv._new_job("enf")

    def work(job):
        from ..enf import pipeline as P
        from ..enf import plots
        from ..enf.media import load_raw

        has_audio = e["meta"].get("n_audio") != 0
        srv._log(job, f"reading raw audio of {e['name']}" if has_audio else f"{e['name']}: no audio track, using the picture", 0.05)
        audio = load_raw(e["path"]) if has_audio else None
        start, end = P.parse_time(req.start), P.parse_time(req.end)
        steps = [("video:", 0.1), ("video flicker", 0.2), ("hum scan", 0.25), ("harmonic SNR", 0.35),
                 ("ENF detector", 0.45), ("reference", 0.6), ("best fit", 0.8), ("audio vs picture", 0.88)]

        def log(m):
            p = next((v for k, v in steps if str(m).startswith(k)), None)
            srv._log(job, str(m), p)

        from ..enf import us_refs as U
        with _EXCL_LOCK:
            saved = set(U.DISABLED)
            U.DISABLED.update(k for k in req.exclude_logs if k in U.SOURCES)
            if req.exclude_logs:
                log(f"leaving out: {', '.join(sorted(U.DISABLED - saved))}")
            try:
                res = P.analyze(e["path"], req.ref_kind, req.ref_path, start, end, req.nominal, log=log, audio=audio,
                                race=req.race, use_meta_time=req.use_meta, cross_nominal=req.cross_nominal,
                                video=req.video if req.video in ("auto", "on", "off") else "auto",
                                readout_ms=req.readout_ms or None)
            finally:
                U.DISABLED.clear()
                U.DISABLED.update(saved)
        res["excluded_logs"] = list(req.exclude_logs)
        srv._log(job, "drawing plots", 0.9)
        tr = res["_trace_obj"]
        stamp = time.strftime("%H%M%S")
        files = {}
        if audio is not None:
            sr, x, _ = audio
            files["spec"] = plots.harmonic_spectrogram(x, sr, tr.nominal, trace=tr, max_s=1800)
        if tr is not None:
            files["trace"] = plots.trace_plot(tr)
        vres = res.get("_video")
        if vres and vres.get("available") and vres.get("candidates") is not None:
            files["video"] = plots.video_plot(vres, atr=tr if audio is not None else None, agree=res.get("_agree"))
            if vres.get("_race") and vres["_race"].get("_rows"):
                files["vrace"] = plots.race_plot(vres["_race"])
        if res["match"]:
            files["match"] = plots.overlay_plot(res["match"])
        if res.get("_race") and res["_race"].get("_rows"):
            files["race"] = plots.race_plot(res["_race"])
        for k, b in files.items():
            open(os.path.join(e["dir"], f"{k}.png"), "wb").write(b)
        out = P.public(res)
        out["png"] = {k: f"/api/enf/png/{e['id']}/{k}.png?v={stamp}" for k in files}
        out.pop("trace", None)
        out["trace_summary"] = None if tr is None else dict(
            harmonics_used=tr.harmonics_used, harmonic_snr_db={str(k): round(v, 1) for k, v in tr.harmonic_snr_db.items()},
            valid=round(tr.valid_fraction(), 3))
        if out.get("video"):
            out["video"].pop("trace", None)
            if out["video"].get("match"):
                out["video"]["match"] = {k: v for k, v in out["video"]["match"].items() if k not in ("overlay", "curve")}
        if out.get("match"):
            out["match"] = {k: v for k, v in out["match"].items() if k not in ("overlay", "curve")}
        out = _clean(out)
        e["last"] = out
        import json
        json.dump(out, open(os.path.join(e["dir"], "enf_result.json"), "w"), indent=1, default=str)
        return out

    srv._run_in_thread(job, work)
    return dict(job=job["id"])


@router.get("/png/{eid}/{kind}.png")
def png(eid: str, kind: str):
    e = ENF.get(eid)
    p = os.path.join(e["dir"], f"{kind}.png") if e else None
    if not p or kind not in ("spec", "trace", "match", "race", "video", "vrace") or not os.path.exists(p):
        raise HTTPException(404, "no plot")
    return Response(open(p, "rb").read(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/result/{eid}.json")
def result(eid: str):
    e = ENF.get(eid)
    if not e or not e["last"]:
        raise HTTPException(404, "run the analysis first")
    from fastapi.responses import FileResponse
    return FileResponse(os.path.join(e["dir"], "enf_result.json"), filename="provenance_enf.json")
