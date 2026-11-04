"""Validate the seismic 'US West (seismic)' reference against the Zenodo WECC 2024 1 s log.

Tuning days (used to pick LABEL_SHIFT_S and to look at thresholds): 2024-03-05, 2024-03-12 (both were
already used in the research prototype). Test days, not looked at before this run:
2024-02-07, 2024-04-17, 2024-05-22, 2024-06-19, 2024-09-11, 2024-10-23.

1. Reference quality per day: coverage, r, best lag, rmse, 95th percentile error, median stations.
   Truth: $PROVENANCE_DATA/wecc_samples/zenodo_wecc_2024_1s.npz, masked to the Zenodo rows flagged QI=0
   (us_refs cache), so filled-in stretches never count as truth.
   Variants rebuilt from the same cached station tracks: all stations; without the Anza borehole
   cluster (PB.B08x, one site); only the stations that were streaming live on 2026-11-03.
2. Race: simulated clips (provenance_fx.enf.simulate.mic_chain + extract_enf) cut from Zenodo on the TEST
   days, raced with (a) Zenodo as the US-West log (seismic disabled) and (b) the seismic reference in
   place of Zenodo (Zenodo disabled). Same clips, same windows (+-10 min, +-1 h, +-6 h), 60 Hz race and
   the cross-nominal control race. No-hum clips as a false-alarm control.
3. Time finding with no hint across all 8 rebuilt seismic days (about 8 x 86,400 positions).
Writes validation_runs/enf_seismic.json.
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
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from provenance_fx.enf import match as M  # noqa: E402
from provenance_fx.enf import race as RC  # noqa: E402
from provenance_fx.enf import seismic as S  # noqa: E402
from provenance_fx.enf import us_refs as U  # noqa: E402
import enf_validate_us as V  # noqa: E402
_DATA = __import__("os").environ.get("PROVENANCE_DATA", __import__("os").path.expanduser("~/provenance-data"))

OUT = os.path.join(ROOT, "validation_runs")
TUNE = [dt.date(2024, 3, 5), dt.date(2024, 3, 12)]
TEST = [dt.date(2024, 2, 7), dt.date(2024, 4, 17), dt.date(2024, 5, 22), dt.date(2024, 6, 19),
        dt.date(2024, 9, 11), dt.date(2024, 10, 23)]
LIVE_SET = ["PB.B088..HHZ", "NN.HYDE..HNZ", "UW.MKAH..HNZ", "UW.WRMB..HNZ", "UW.OZET..HNZ", "MB.OVMT.01.EHZ",
            "UO.DAYS..HNZ", "UW.HOMA..HNZ", "MB.YBMT.01.EHZ"]
WINDOWS = (600, 3600, 6 * 3600)


def truth_day(day):
    z = np.load(os.path.join(_DATA, "wecc_samples", "zenodo_wecc_2024_1s.npz"))
    zt0, zf = float(z["t0_utc"]), z["f_hz"].astype(float)
    d0 = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp())
    i = d0 - int(round(zt0))
    f = zf[i:i + 86400].copy() if 0 <= i else np.full(86400, np.nan)
    q = U.load("zenodo_wecc_2024")               # QI=0 rows only
    qs = q.slice(d0, d0 + 86399).f[:86400]
    f[~np.isfinite(qs)] = np.nan
    if len(f) < 86400:
        f = np.concatenate([f, np.full(86400 - len(f), np.nan)])
    return d0, f


def metrics(cons, truth):
    m = np.isfinite(cons) & np.isfinite(truth)
    out = dict(coverage=round(float(np.isfinite(cons).mean()), 4), overlap_s=int(m.sum()))
    if m.sum() < 600:
        return out
    r0 = float(np.corrcoef(cons[m], truth[m])[0, 1])
    e = cons[m] - truth[m]
    r, L = S.corr_lag(cons, truth, max_lag=5)
    # correlation after removing the slow (10 min) trend: tests the second-to-second detail the race uses
    from scipy.ndimage import uniform_filter1d
    def hp(x):
        y = np.where(np.isfinite(x), x, np.nanmean(x))
        return np.where(np.isfinite(x), y - uniform_filter1d(y, 600, mode="nearest"), np.nan)
    a, b = hp(cons), hp(truth)
    mm = np.isfinite(a) & np.isfinite(b)
    out.update(r=round(r0, 4), best_lag_s=int(L), r_best=round(float(r), 4), rmse_mhz=round(float(np.sqrt(np.mean(e ** 2)) * 1000), 2),
               p95_abs_mhz=round(float(np.percentile(np.abs(e), 95) * 1000), 2),
               bias_mhz=round(float(np.mean(e) * 1000), 2),
               r_detrended=round(float(np.corrcoef(a[mm], b[mm])[0, 1]), 4))
    return out


def part1():
    res = {}
    for day in TUNE + TEST:
        d0, truth = truth_day(day)
        lead = 1800
        tracks = {}
        per_station = {}
        for sid, *_ in S.stations_for("US-WEST"):
            t0, f, snr = S.station_day(sid, day, lead_s=lead)
            if np.isfinite(f).mean() > 0.02:
                tracks[sid] = f
            body = f[lead:lead + 86400]
            ms = metrics(S._shift(body, -S.LABEL_SHIFT_S), truth)   # station alone, same label shift
            per_station[sid] = {k: ms.get(k) for k in ("coverage", "r", "rmse_mhz")}
        row = dict(split="tune" if day in TUNE else "test", stations=per_station)
        for name, sel in (("all", lambda s: True), ("without_anza_cluster", lambda s: not s.startswith("PB.B08")),
                          ("live_2026_set", lambda s: s in LIVE_SET)):
            tr = {k: v for k, v in tracks.items() if sel(k)}
            if len(tr) < 2:
                row[name] = dict(error="fewer than 2 stations")
                continue
            c = S.build_consensus(tr, t0, 86400 + 2 * lead)
            cons = S._shift(c["f"], 0)[lead - S.LABEL_SHIFT_S:lead - S.LABEL_SHIFT_S + 86400]
            nsrc = c["n_sources"][lead - S.LABEL_SHIFT_S:lead - S.LABEL_SHIFT_S + 86400]
            mt = metrics(cons, truth)
            mt["median_sources"] = float(np.median(nsrc))
            mt["stations_used"] = sorted({i for pw in c["per_window"] for i in pw["used"]})
            row[name] = mt
        # the file actually written by the rebuilder (what the race loads)
        ref = S.load_reference("US-WEST", d0, d0 + 86399)
        row["day_file"] = metrics(ref.slice(d0, d0 + 86399).f[:86400], truth) if ref is not None else None
        res[day.isoformat()] = row
        print(day, row["split"], json.dumps({k: row[k] for k in ("all", "without_anza_cluster", "live_2026_set")}), flush=True)
    return res


def _init(disabled):
    U.DISABLED.clear()
    U.DISABLED.update(disabled)


def race_job(args):
    it, W, cross, seed, mode = args
    r = V.race_one((it, W, cross, seed))
    r["mode"] = mode
    return r


def score(rows):
    out = {}
    for key in sorted(set((r["mode"], r["window_s"], r["cross"]) for r in rows)):
        rr = [r for r in rows if (r["mode"], r["window_s"], r["cross"]) == key]
        res = {}
        for truth in sorted(set(r["truth"] for r in rr)):
            t = [r for r in rr if r["truth"] == truth]
            ans = [r for r in t if r["decision"] != "abstain"]
            res[truth] = dict(n=len(t), answered=len(ans), abstain_rate=round(1 - len(ans) / max(1, len(t)), 3),
                              answered_accuracy=(round(sum(r["winner"] == truth for r in ans) / len(ans), 3)
                                                 if ans and truth != "NONE" else None),
                              confident_wrong=sum(r["winner"] != truth for r in ans),
                              decisive=sum(r["decision"] == "decisive" for r in t),
                              timing_within_5s=(round(sum(r["timing_error_s"] is not None and abs(r["timing_error_s"]) <= 5
                                                          and r["winner"] == truth for r in ans) / max(1, len(ans)), 3)
                                                if ans and truth != "NONE" else None),
                              median_r=(round(float(np.median([r["ranking"][0]["r"] for r in ans])), 3) if ans else None))
        out[f"{key[0]} window=+-{key[1]}s cross_nominal={key[2]}"] = res
    return out


def prefetch():
    """Public no-login European logs for the cross-nominal control race on the test days."""
    from provenance_fx.enf import grids as G
    from provenance_fx.enf import reference as R
    for d in TEST:
        for k in (-1, 0, 1):
            try:
                G.energy_charts_day(d + dt.timedelta(days=k))
            except Exception as e:
                print("CE", d, e)
    for y, m in sorted({(d.year, d.month) for d in TEST}):
        for fn in (lambda: R.neso_month(y, m), lambda: G.fingrid_month(y, m)):
            try:
                fn()
            except Exception as e:
                print("month", y, m, e)


def part2():
    prefetch()
    J, s = [], 90000
    for d in TEST:
        for _ in range(8):
            J.append((len(J), "US-WEST", "us", "zenodo_wecc_2024", s, d, "S")); s += 1
        J.append((len(J), "NONE", "ce", d, s, d, "S")); s += 1
        J.append((len(J), "CE", "ce", d, s, d, "S")); s += 1
    lib = os.path.join(OUT, "enf_seismic_sim.npz")
    if os.path.exists(lib) and "--rebuild" not in sys.argv:
        items = list(np.load(lib, allow_pickle=True)["items"])
    else:
        with Pool(4) as pool:
            items = [r for r in pool.imap_unordered(V.pick, J, chunksize=2) if r]
        items.sort(key=lambda r: r["idx"])
        np.savez_compressed(lib, items=np.array(items, dtype=object))
    print("clips", len(items), flush=True)
    rows = []
    for mode, disabled in (("zenodo_reference", {"seismic_west", "seismic_texas", "seismic_east"}),
                           ("seismic_reference", {"zenodo_wecc_2024"})):
        jobs = []
        for it in items:
            for W in WINDOWS:
                for cross in (False, True):
                    if it["grid"] == "CE" and not cross:
                        continue
                    jobs.append((it, W, cross, 7 * int(it["idx"]) + W, mode))
        t0 = time.time()
        with Pool(4, initializer=_init, initargs=(disabled,)) as pool:
            rows += pool.map(race_job, jobs, chunksize=2)
        print(mode, len(jobs), f"{time.time() - t0:.0f}s", flush=True)
    # paired comparison on West clips
    pair = {}
    for W in WINDOWS:
        for cross in (False, True):
            a = {r["idx"]: r for r in rows if r["mode"] == "zenodo_reference" and r["window_s"] == W and r["cross"] == cross and r["truth"] == "US-WEST"}
            b = {r["idx"]: r for r in rows if r["mode"] == "seismic_reference" and r["window_s"] == W and r["cross"] == cross and r["truth"] == "US-WEST"}
            k = sorted(set(a) & set(b))
            pair[f"+-{W}s cross={cross}"] = dict(
                n=len(k), both_answer=sum(a[i]["decision"] != "abstain" and b[i]["decision"] != "abstain" for i in k),
                only_zenodo_answers=sum(a[i]["decision"] != "abstain" and b[i]["decision"] == "abstain" for i in k),
                only_seismic_answers=sum(a[i]["decision"] == "abstain" and b[i]["decision"] != "abstain" for i in k),
                same_start_within_2s=sum(a[i]["decision"] != "abstain" and b[i]["decision"] != "abstain" and
                                         a[i]["timing_error_s"] is not None and b[i]["timing_error_s"] is not None and
                                         abs(a[i]["timing_error_s"] - b[i]["timing_error_s"]) <= 2 for i in k))
    return items, rows, score(rows), pair


def find_job(it):
    _init({"zenodo_wecc_2024"})
    ref = S.load_reference("US-WEST", label="US West (seismic)")
    tr = V.mk(it)
    m = M.match_long(tr, ref) if (ref.t1 - ref.t0) > 40 * 86400 else M.match(tr, ref)
    raw = m["start_time"]
    if m["label"] != "no match":
        M.apply_continuity(m, M.continuity(tr, ref, m))   # same step the pipeline runs
    st = m.get("start_time_first_segment", raw)
    return dict(idx=int(it["idx"]), dur=it["dur"], r=m["ncc"], second=m["second_ncc"], p_false=m["p_false"],
                label=m["label"], error_s=round(st - it["t_start"], 1), error_raw_s=round(raw - it["t_start"], 1),
                timeline_break=bool(m.get("timeline_break")))


def part3(items):
    west = [it for it in items if it["grid"] == "US-WEST"]
    with Pool(4) as pool:
        finds = pool.map(find_job, west)
    conf = [r for r in finds if r["label"] in ("strong", "moderate")]
    return dict(n=len(finds), found_within_5s=sum(abs(r["error_s"]) <= 5 for r in finds), confident=len(conf),
                confident_right=sum(abs(r["error_s"]) <= 5 for r in conf),
                confident_wrong=sum(abs(r["error_s"]) > 5 for r in conf), rows=finds)


def main():
    t0 = time.time()
    if "--part3-only" in sys.argv:          # re-run time finding, keep parts 1-2 from the last full run
        p = os.path.join(OUT, "enf_seismic.json")
        d = json.load(open(p))
        items = list(np.load(os.path.join(OUT, "enf_seismic_sim.npz"), allow_pickle=True)["items"])
        d["time_finding"] = part3(items)
        print("time finding:", {k: v for k, v in d["time_finding"].items() if k != "rows"})
        json.dump(d, open(p, "w"), indent=1, default=float)
        return
    p1 = part1()
    items, rows, summ, pair = part2()
    print(json.dumps(summ, indent=1))
    print(json.dumps(pair, indent=1))
    p3 = part3(items)
    print("time finding:", {k: v for k, v in p3.items() if k != "rows"})
    json.dump(dict(reference_quality=p1, race_summary=summ, paired=pair, time_finding=p3, races=rows,
                   label_shift_s=S.LABEL_SHIFT_S, elapsed_s=round(time.time() - t0)),
              open(os.path.join(OUT, "enf_seismic.json"), "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
