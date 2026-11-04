"""Validate video light-flicker ENF on SIMULATED videos driven by REAL grid logs.

Each clip: provenance_fx.enf.video_sim.render_video (textured lamp-lit room, rolling or global shutter, sensor noise,
optional pans / hand-held jitter / auto-exposure steps, H.264 through ffmpeg) with the lamp flicker phase integrated
from a real 1 s grid log: Zenodo WECC 2024 (US West, 60 Hz), NESO GB 2024 and Energy-Charts CE 2024 (50 Hz).
The picture is analysed with provenance_fx.enf.video.analyze_video (no audio), then raced with the same grid race
and rules as audio, with windows of +-10 min and +-1 h. Nothing is re-tuned on these results.

Part V  camera configurations x clip length (2, 5, 10 min), plus no-flicker / anti-banding / inverter controls.
Part S  audio + picture: genuine clips vs clips whose sound after the midpoint is taken from 11 h later (splice).

SIMULATED IS NOT REAL: the renderer encodes our own assumptions about cameras (row order, constant read-out,
linear sensor, x264 settings). Real-camera numbers may be worse.
Rows are appended to validation_runs/enf_video_runs.jsonl as they finish (resumable);
the summary goes to validation_runs/enf_video.json.
"""
import datetime as dt
import json
import os
import sys
import tempfile
import time
import zlib
from multiprocessing import Pool

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from provenance_fx.enf import grids as G  # noqa: E402
from provenance_fx.enf import race as RC  # noqa: E402
from provenance_fx.enf import reference as R  # noqa: E402
from provenance_fx.enf import us_refs as U  # noqa: E402
from provenance_fx.enf import video as V  # noqa: E402
from provenance_fx.enf.video_sim import render_video  # noqa: E402

OUT = os.path.join(ROOT, "validation_runs")
RUNS = os.path.join(OUT, "enf_video_runs.jsonl")
LENGTHS = tuple(int(x) for x in os.environ.get("VVAL_LENGTHS", "120,300,600").split(","))
WINDOWS = (600, 3600)
WECC_DAYS = [dt.date(2024, m, d) for m in (2, 5, 9, 10) for d in (5, 12, 19, 26)]
GB_MONTHS = [(2024, 2), (2024, 4), (2024, 5), (2024, 6), (2024, 9), (2024, 10)]
CE_DAYS = [dt.date(2024, 4, 17), dt.date(2024, 5, 22), dt.date(2024, 9, 11), dt.date(2024, 10, 23)]

# name: (grid kind, render kwargs, expected: 'flicker' or 'none')
CONFIGS = {
    "rs2997_25ms": ("wecc", dict(fps="30000/1001", readout_ms=25), "flicker"),
    "rs30_20ms": ("wecc", dict(fps="30", readout_ms=20), "flicker"),
    "rs2997_crf30": ("wecc", dict(fps="30000/1001", readout_ms=25, crf=30), "flicker"),
    "rs2997_crf18_gop60": ("wecc", dict(fps="30000/1001", readout_ms=25, crf=18, gop=60), "flicker"),
    "rs2997_depth1pct": ("wecc", dict(fps="30000/1001", readout_ms=16, mod_depth=0.01), "flicker"),
    "rs2997_handheld": ("wecc", dict(fps="30000/1001", readout_ms=25, pans=3, jitter_px=0.3, exposure_steps=2), "flicker"),
    "gs2997_alias012": ("wecc", dict(fps="30000/1001", readout_ms=0), "flicker"),
    "rs25_gb_30ms": ("gb", dict(fps="25", readout_ms=30), "flicker"),
    "gs2997_gb_alias10": ("gb", dict(fps="30000/1001", readout_ms=0), "flicker"),
    "rs30_ce_25ms": ("ce", dict(fps="30", readout_ms=25), "flicker"),
    "ctl_noflicker": ("wecc", dict(fps="30000/1001", readout_ms=25, flicker=False), "none"),
    "ctl_antiband": ("wecc", dict(fps="30000/1001", readout_ms=25, exposure_s=1 / 120), "none"),
    "ctl_inverter": ("wecc", dict(fps="30000/1001", readout_ms=25, fixed_flicker_hz=120.0), "none"),
}
TRUTH_GRID = {"wecc": "US-WEST", "gb": "GB", "ce": "CE"}
_REF = {}


def ref_for(kind, key):
    k = (kind, key)
    if k not in _REF:
        if kind == "wecc":
            r = U.load("zenodo_wecc_2024")
            _REF[k] = r.to_1s() if r.step != 1 else r
        elif kind == "gb":
            _REF[k] = R.neso_month(*key).to_1s()
        elif kind == "ce":
            _REF[k] = G.energy_charts_day(key)
    return _REF[k]


def pick_segment(kind, rng, dur):
    if kind == "wecc":
        day = WECC_DAYS[rng.integers(len(WECC_DAYS))]; key = None
    elif kind == "gb":
        key = GB_MONTHS[rng.integers(len(GB_MONTHS))]; day = dt.date(key[0], key[1], int(rng.integers(1, 28)))
    else:
        key = day = CE_DAYS[rng.integers(len(CE_DAYS))]
    ref = ref_for(kind, key)
    a = int(dt.datetime.combine(day, dt.time(0), dt.timezone.utc).timestamp() - ref.t0)
    for _ in range(300):
        i0 = int(rng.integers(max(0, a), max(1, min(len(ref.f) - dur - 2, a + 86400 - dur))))
        seg = ref.f[i0:i0 + dur + 60].astype(float)
        if np.isfinite(seg).mean() > 0.97:
            ok = np.isfinite(seg)
            return float(ref.t0 + i0), np.interp(np.arange(len(seg)), np.where(ok)[0], seg[ok]), ref, i0
    return None, None, None, None


def score_trace(tr, f):
    if tr is None:
        return None, None, 0.0
    ok = np.isfinite(tr.f)
    if ok.sum() < 20:
        return None, None, float(ok.mean())
    tt = np.clip(np.round(tr.t[ok]).astype(int), 0, len(f) - 1)
    return (round(float(np.corrcoef(tr.f[ok], f[tt])[0, 1]), 3),
            round(float(np.sqrt(np.mean((tr.f[ok] - f[tt]) ** 2)) * 1000), 2), round(float(ok.mean()), 3))


def race_rows(tr, det, t_start, truth, rng):
    rows = []
    for W in WINDOWS:
        if tr is None:
            rows.append(dict(window_s=W, decision="abstain", winner=None, timing_error_s=None, reason="no video trace"))
            continue
        c = t_start + rng.uniform(-W, W)
        r = RC.grid_race(tr, c - W, c + W, allow_download=False, det=det)
        top = r["ranking"][0] if r["ranking"] else {}
        rows.append(dict(window_s=W, decision=r["decision"], winner=r["winner"], margin=r.get("margin"),
                         covered=[x["grid"] for x in r["ranking"]],
                         top_r=top.get("r"), timing_error_s=(round(top["start_time"] - t_start, 1) if top else None)))
    return rows


def job_v(args):
    idx, cfg, L, seed = args
    kind, kw, expect = CONFIGS[cfg]
    rng = np.random.default_rng(seed)
    t_start, f, ref, i0 = pick_segment(kind, rng, L)
    if f is None:
        return None
    p = os.path.join(tempfile.gettempdir(), f"vval_{idx}.mp4")
    t0 = time.time()
    try:
        render_video(p, f, seconds=L, seed=seed, **kw)
        r = V.analyze_video(p)
    finally:
        if os.path.exists(p):
            os.unlink(p)
    det = None
    if r.get("detect"):
        det = dict(r["detect"], verdict=r["presence"]["verdict"])
    tr = r.get("_trace")
    rr, rmse, valid = score_trace(r.get("_trace_any"), f)
    truth = TRUTH_GRID[kind] if expect == "flicker" else "NONE"
    row = dict(part="V", idx=idx, cfg=cfg, length_s=L, seed=seed, truth=truth, t_start=t_start,
               verdict=r["presence"]["verdict"], path=r.get("path_used"), nominal=r.get("nominal"),
               readout_true=kw.get("readout_ms"), readout_est=r.get("readout_ms"), readout_source=r.get("readout_source"),
               band_contrast_db=(r.get("readout_search") or {}).get("contrast_db"), dropped=r.get("dropped"),
               gop_s=(r.get("keyframes") or {}).get("gop_s"), r=rr, rmse_mhz=rmse, valid=valid,
               races=race_rows(tr, det, t_start, truth, rng), secs=round(time.time() - t0, 1))
    return row


def job_s(args):
    """Audio + picture through the full pipeline; half the clips get the sound after the midpoint from 11 h later."""
    from provenance_fx.enf import pipeline as P
    idx, spliced, seed = args
    rng = np.random.default_rng(seed)
    L = 360
    t_start, f, ref, i0 = pick_segment("wecc", rng, L)
    other = ref.f[i0 + 11 * 3600:i0 + 11 * 3600 + len(f)].astype(float)
    ok = np.isfinite(other)
    if f is None or ok.mean() < 0.97:
        return None
    other = np.interp(np.arange(len(other)), np.where(ok)[0], other[ok])
    fa = f.copy()
    if spliced:
        fa[L // 2:] = other[L // 2:]
    p = os.path.join(tempfile.gettempdir(), f"vsplice_{idx}.mp4")
    t0 = time.time()
    try:
        render_video(p, f, seconds=L, seed=seed, fps="30000/1001", readout_ms=25, audio_f_1s=fa,
                     audio_snr_db=float(rng.uniform(-5, 5)))
        res = P.analyze(p, "none", None, t_start - 600, t_start + 600, None, race=True)
    finally:
        if os.path.exists(p):
            os.unlink(p)
    ag = res.get("av_agreement") or {}
    v = res.get("video") or {}
    return dict(part="S", idx=idx, spliced=spliced, seed=seed, t_start=t_start, audio_verdict=res["detect"]["verdict"],
                video_verdict=(v.get("presence") or {}).get("verdict"), agreement=ag.get("verdict"), r_best=ag.get("r_best"),
                lag=ag.get("best_lag_s"), pieces=[p_["r"] for p_ in ag.get("pieces") or []],
                audio_race=(res.get("race") or {}).get("decision"), audio_winner=(res.get("race") or {}).get("winner"),
                video_race=(v.get("race") or {}).get("decision"), video_winner=(v.get("race") or {}).get("winner"),
                cross_checks=ag.get("cross_checks"), secs=round(time.time() - t0, 1))


def run(fn_args):
    fn, a = fn_args
    try:
        return (job_v if fn == "V" else job_s)(a)
    except Exception as e:  # keep going; report the failure
        return dict(part=fn, idx=a[0], error=f"{type(e).__name__}: {e}")


def all_jobs(n_seeds):
    J = []
    for cfg in CONFIGS:
        for L in LENGTHS:
            for s in range(n_seeds):
                seed = zlib.crc32(f"{cfg}|{L}|{s}".encode()) % 100000
                J.append(("V", (f"{cfg}-{L}-{s}", cfg, L, seed)))
    for s in range(6):
        J.append(("S", (f"S-{s}", s % 2 == 1, 7000 + s)))
    return J


def summarize(rows):
    V_ = [r for r in rows if r.get("part") == "V" and "error" not in r]
    out = {"extraction (flicker configs)": {}, "presence": {}, "race": {}}
    for cfg in CONFIGS:
        for L in LENGTHS:
            rr = [r for r in V_ if r["cfg"] == cfg and r["length_s"] == L]
            if not rr:
                continue
            key = f"{cfg} {L}s"
            out["presence"][key] = {v: sum(r["verdict"] == v for r in rr) for v in ("present", "weak", "absent")}
            if CONFIGS[cfg][2] == "flicker":
                good = [r for r in rr if r["r"] is not None and r["verdict"] != "absent"]
                ro = [abs(r["readout_est"] - r["readout_true"]) for r in rr
                      if r["readout_true"] and r["readout_est"] and r["path"] == "rolling shutter"]
                out["extraction (flicker configs)"][key] = dict(
                    n=len(rr), tracked=len(good),
                    median_r=None if not good else round(float(np.median([r["r"] for r in good])), 3),
                    median_rmse_mhz=None if not good else round(float(np.median([r["rmse_mhz"] for r in good])), 2),
                    median_readout_err_ms=None if not ro else round(float(np.median(ro)), 2))
    for W in WINDOWS:
        for lab, sel in (("flicker", lambda r: r["truth"] != "NONE"), ("controls", lambda r: r["truth"] == "NONE")):
            for L in LENGTHS:
                rr = [(r, x) for r in V_ if sel(r) and r["length_s"] == L for x in r["races"] if x["window_s"] == W]
                ans = [(r, x) for r, x in rr if x["decision"] != "abstain"]
                right = [(r, x) for r, x in ans if x["winner"] == r["truth"]]
                out["race"][f"+-{W}s {lab} {L}s"] = dict(
                    n=len(rr), answered=len(ans), right=len(right), confident_wrong=len(ans) - len(right),
                    decisive=sum(x["decision"] == "decisive" for _, x in rr),
                    timing_within_5s=sum(x["timing_error_s"] is not None and abs(x["timing_error_s"]) <= 5 for _, x in right))
    S = [r for r in rows if r.get("part") == "S" and "error" not in r]
    out["audio vs picture"] = dict(
        genuine={v: sum(r["agreement"] == v for r in S if not r["spliced"]) for v in sorted(set(r["agreement"] for r in S))},
        spliced={v: sum(r["agreement"] == v for r in S if r["spliced"]) for v in sorted(set(r["agreement"] for r in S))})
    out["errors"] = [r for r in rows if "error" in r]
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    n_seeds = int(os.environ.get("VVAL_SEEDS", "2"))
    done = {}
    if os.path.exists(RUNS):
        for ln in open(RUNS):
            try:
                r = json.loads(ln); done[r["idx"]] = r
            except Exception:
                pass
    J = [j for j in all_jobs(n_seeds) if (j[0] == "S" or j[1][2] in LENGTHS) and j[1][0] not in done or "error" in done[j[1][0]]]
    J.sort(key=lambda j: -(j[1][2] if j[0] == "V" else 360))       # long clips first
    print(f"{len(done)} done, {len(J)} to run", flush=True)
    t0 = time.time()
    with Pool(int(os.environ.get("VVAL_PROCS", "7"))) as pool, open(RUNS, "a") as fh:
        for row in pool.imap_unordered(run, J):
            if row:
                fh.write(json.dumps(row, default=float) + "\n"); fh.flush()
                done[row["idx"]] = row
                print(f"[{time.time() - t0:.0f}s] {row['idx']}: " + (row.get("error") or
                      f"{row.get('verdict', row.get('agreement'))} r={row.get('r', row.get('r_best'))}"), flush=True)
    rows = list(done.values())
    summary = summarize(rows)
    json.dump(dict(note="SIMULATED videos driven by real grid logs; not real camera footage.", summary=summary, rows=rows),
              open(os.path.join(OUT, "enf_video.json"), "w"), indent=1, default=float)
    print(json.dumps(summary, indent=1, default=float))


if __name__ == "__main__":
    main()
