"""Validate the US references in the grid race and in time finding (simulated recordings).

Clips are cut from real logs and pushed through provenance_fx.enf.simulate.mic_chain (random harmonics, hum SNR
-22..+10 dB, recorder clock error, noise bursts, interferer tones, stream stalls) and the normal extractor,
exactly like the earlier sim library. Nothing here re-tunes thresholds: the race rule was fixed on the
2025-26 European + 2019 US library, so every 2024 WECC segment is held out.

A  WECC 2024 (Zenodo, QI=0 only): 16 days in Feb/May/Sep/Oct 2024; races vs every grid with a log at that
   time. Same-nominal race (US grids only; only US-WEST is covered in 2024) and cross-nominal race
   (adds GB / CE / Nordic as controls). Controls: GB, CE, Nordic clips from the same days and no-hum clips.
   Windows +-10 min, +-1 h, +-6 h.
B  2026 four-way US race on the FNET gauge scrape (WECC / EI / ERCOT / Quebec, all low trust).
C  Pigott Phoenix 2022 (5 s): race with the clock-offset search; does it pick the inferred MST offset?
D  Time finding: WECC clips searched against ALL of the 2024 WECC log (10 months) with no time hint.
Writes validation_runs/enf_us.json and validation_runs/enf_us_sim.npz.
"""
import datetime as dt
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from provenance_fx.enf import grids as G  # noqa: E402
from provenance_fx.enf import match as M  # noqa: E402
from provenance_fx.enf import race as RC  # noqa: E402
from provenance_fx.enf import reference as R  # noqa: E402
from provenance_fx.enf import us_refs as U  # noqa: E402
from provenance_fx.enf.extract import EnfTrace, extract_enf  # noqa: E402
from provenance_fx.enf.simulate import mic_chain  # noqa: E402

OUT = os.path.join(ROOT, "validation_runs")
MONTHS = [(2024, 2), (2024, 5), (2024, 9), (2024, 10)]
DAYS = [dt.date(y, m, d) for y, m in MONTHS for d in (5, 12, 19, 26)]
NG_DAYS = [dt.date(2026, 3, 22) + dt.timedelta(days=5 * i) for i in range(10)]
PG_DAYS = [dt.date(2022, 3, 10) + dt.timedelta(days=30 * i) for i in range(10)]
WINDOWS = (600, 3600, 6 * 3600)
_REF = {}


def ref_for(kind, key):
    k = (kind, key)
    if k not in _REF:
        if kind == "us":
            r = U.load(key)
            _REF[k] = r.to_1s() if r.step != 1 else r
        elif kind == "neso":
            _REF[k] = R.neso_month(*key).to_1s()
        elif kind == "fingrid":
            _REF[k] = G.fingrid_month(*key)
        elif kind == "ce":
            _REF[k] = G.energy_charts_day(key)
    return _REF[k]


def pick(job):
    idx, grid, kind, key, seed, day, part = job
    rng = np.random.default_rng(seed)
    ref = ref_for(kind, key)
    dur = int(rng.uniform(180, 1200))
    f = ref.f
    a = int(dt.datetime.combine(day, dt.time(0), dt.timezone.utc).timestamp() - ref.t0)
    for _ in range(300):
        i0 = int(rng.integers(max(0, a), max(1, min(len(f) - dur - 1, a + 86400 - dur))))
        seg = f[i0:i0 + dur].astype(float)
        if np.isfinite(seg).mean() > 0.97:
            break
    else:
        return None
    ok = np.isfinite(seg)
    seg = np.interp(np.arange(dur), np.where(ok)[0], seg[ok])
    nominal = 60 if grid.startswith("US") or grid == "QUEBEC" else 50
    try:
        if grid == "NONE":
            sr = 1000
            x = rng.normal(0, 1, dur * sr)
            if rng.random() < 0.5:
                x += 0.3 * np.sin(2 * np.pi * (120 + rng.uniform(-0.1, 0.1)) * np.arange(dur * sr) / sr)
            params = dict(profile="none", snr_db=None, clock_ppm=0, stall=False, interferer=True)
        else:
            sr, x, params = mic_chain(seg, rng, nominal=nominal)
        tr = extract_enf(x, sr, 60 if grid == "NONE" else nominal)
    except ValueError:
        return None
    return dict(idx=idx, grid=grid, part=part, t_start=float(ref.t0 + i0), dur=dur, nominal=nominal if grid != "NONE" else 60,
                t=tr.t.astype(np.float32), f=tr.f.astype(np.float64), snr=tr.snr_db.astype(np.float32),
                **{"p_" + k: v for k, v in params.items()})


def jobs():
    J, s = [], 50000

    def add(grid, kind, key, n, day, part):
        nonlocal s
        for _ in range(n):
            J.append((len(J), grid, kind, key, s, day, part)); s += 1
    for d in DAYS:
        add("US-WEST", "us", "zenodo_wecc_2024", 6, d, "A")
        add("GB", "neso", (d.year, d.month), 1, d, "A")
        add("CE", "ce", d, 1, d, "A")
        add("NORDIC", "fingrid", (d.year, d.month), 1, d, "A")
        add("NONE", "ce", d, 1, d, "A")
    for d in NG_DAYS:
        for g, k in (("US-WEST", "nategriff_wecc"), ("US-EAST", "nategriff_ei"), ("US-TEXAS", "nategriff_ercot"),
                     ("QUEBEC", "nategriff_quebec")):
            add(g, "us", k, 2, d, "B")
    for d in PG_DAYS:
        add("US-WEST", "us", "pigott_phx_2022", 3, d, "C")
    return J


def mk(it):
    return EnfTrace(t=np.asarray(it["t"], float), f=np.asarray(it["f"], float), snr_db=np.asarray(it["snr"], float),
                    nominal=int(it["nominal"]), harmonics_used=[], harmonic_snr_db={}, harmonic_corr={})


def race_one(args):
    it, W, cross, seed = args
    rng = np.random.default_rng(seed)
    tr = mk(it)
    c = it["t_start"] + rng.uniform(-W, W)
    r = RC.grid_race(tr, c - W, c + W, allow_download=False, cross_nominal=cross)
    top = r["ranking"][0] if r["ranking"] else {}
    return dict(idx=int(it["idx"]), part=it["part"], truth=it["grid"], window_s=W, cross=cross, dur=it["dur"],
                snr_db=it.get("p_snr_db"), decision=r["decision"], winner=r["winner"], margin=r["margin"],
                dz=r.get("dz"), timing_error_s=(None if not top or it["grid"] == "NONE" else round(top["start_time"] - it["t_start"], 1)),
                tz_shift_h=top.get("tz_shift_h"), covered=[x["grid"] for x in r["ranking"]],
                ranking=[{k: x[k] for k in ("grid", "r", "p_false", "trust", "tz_shift_h")} for x in r["ranking"]])


def find_one(it):
    """Part D: no time hint, search all of 2024 WECC."""
    ref = U.load("zenodo_wecc_2024")
    tr = mk(it)
    t0 = time.time()
    m = M.match_long(tr, ref)
    return dict(idx=int(it["idx"]), dur=it["dur"], snr_db=it.get("p_snr_db"), stall=bool(it.get("p_stall")),
                r=m["ncc"], second=m["second_ncc"], p_false=m["p_false"], label=m["label"],
                error_s=round(m["start_time"] - it["t_start"], 1), secs=round(time.time() - t0, 1))


def score(rows):
    out = {}
    for key in sorted(set((r["part"], r["window_s"], r["cross"]) for r in rows)):
        rr = [r for r in rows if (r["part"], r["window_s"], r["cross"]) == key]
        res = {}
        for truth in sorted(set(r["truth"] for r in rr)):
            t = [r for r in rr if r["truth"] == truth]
            ans = [r for r in t if r["decision"] != "abstain"]
            res[truth] = dict(
                n=len(t), answered=len(ans), abstain_rate=round(1 - len(ans) / max(1, len(t)), 3),
                accuracy_all=round(sum(r["winner"] == truth for r in t) / max(1, len(t)), 3) if truth != "NONE" else None,
                answered_accuracy=(round(sum(r["winner"] == truth for r in ans) / len(ans), 3) if ans and truth != "NONE" else None),
                confident_wrong=sum(r["winner"] != truth for r in ans),
                decisive=sum(r["decision"] == "decisive" for r in t),
                decisive_wrong=sum(r["decision"] == "decisive" and r["winner"] != truth for r in t),
                timing_within_5s=(round(sum(r["timing_error_s"] is not None and abs(r["timing_error_s"]) <= 5 and r["winner"] == truth
                                            for r in ans) / max(1, len(ans)), 3) if ans and truth != "NONE" else None),
                grids_covered=sorted(set(g for r in t for g in r["covered"])))
        out[f"{key[0]} window=+-{key[1]}s cross_nominal={key[2]}"] = res
    return out


def main():
    lib = os.path.join(OUT, "enf_us_sim.npz")
    if os.path.exists(lib) and "--rebuild" not in sys.argv:
        items = list(np.load(lib, allow_pickle=True)["items"])
    else:
        J = jobs()
        J.sort(key=lambda j: (j[2], str(j[3])))
        t0 = time.time()
        with Pool(4) as pool:
            items = [r for r in pool.imap_unordered(pick, J, chunksize=4) if r]
        items.sort(key=lambda r: r["idx"])
        np.savez_compressed(lib, items=np.array(items, dtype=object))
        print("built", len(items), "clips", f"{time.time() - t0:.0f}s", flush=True)
    A = [it for it in items if it["part"] == "A"]
    B = [it for it in items if it["part"] == "B"]
    C = [it for it in items if it["part"] == "C"]
    jobs_r = []
    for it in A:
        for W in WINDOWS:
            for cross in (False, True):
                if it["grid"] in ("GB", "CE", "NORDIC") and not cross:
                    continue   # 50 Hz clips only matter as cross-nominal controls
                jobs_r.append((it, W, cross, 7 * int(it["idx"]) + W))
    for it in B:
        for W in WINDOWS:
            jobs_r.append((it, W, False, 7 * int(it["idx"]) + W))
    for it in C:
        for W in (3600,):
            jobs_r.append((it, W, False, 7 * int(it["idx"]) + W))
    t0 = time.time()
    with Pool(4) as pool:
        rows = pool.map(race_one, jobs_r, chunksize=2)
    print("races", len(rows), f"{time.time() - t0:.0f}s", flush=True)
    summary = score(rows)
    pig = [r for r in rows if r["part"] == "C"]
    summary["C tz_shift_h chosen"] = {str(k): sum(r["tz_shift_h"] == k for r in pig if r["decision"] != "abstain")
                                      for k in (0.0, -1.0, 1.0, 7.0)}
    print(json.dumps(summary, indent=1), flush=True)
    wecc = [it for it in A if it["grid"] == "US-WEST"]
    t0 = time.time()
    with Pool(3) as pool:
        finds = pool.map(find_one, wecc, chunksize=1)
    print("time finding", len(finds), f"{time.time() - t0:.0f}s", flush=True)
    fd = {}
    for lab, sel in (("all", lambda r: True), ("dur<300s", lambda r: r["dur"] < 300), ("300-600s", lambda r: 300 <= r["dur"] < 600),
                     ("600s+", lambda r: r["dur"] >= 600)):
        rr = [r for r in finds if sel(r)]
        conf = [r for r in rr if r["label"] in ("strong", "moderate")]
        fd[lab] = dict(n=len(rr), found_within_5s=sum(abs(r["error_s"]) <= 5 for r in rr),
                       confident=len(conf), confident_right=sum(abs(r["error_s"]) <= 5 for r in conf),
                       confident_wrong=sum(abs(r["error_s"]) > 5 for r in conf))
    print(json.dumps(fd, indent=1))
    json.dump(dict(summary=summary, races=rows, time_finding=dict(summary=fd, rows=finds)),
              open(os.path.join(OUT, "enf_us.json"), "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
