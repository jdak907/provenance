"""Validate the grid race (time roughly known) on simulated and real recordings.

sim: race clips from sim_library.npz (real GB / CE / Nordic logs on 32 days across 2025-26,
     US West vs Texas in May 2019, and no-hum noise clips). The search window is centred at a
     random offset from the true start: +-10 min, +-1 h and +-6 h.
real: UK recordings with an approximate start time (scripts/enf_real_clips.py).
The detector is NOT used for sim clips, so the race thresholds alone must reject the no-hum clips.
Writes validation_runs/enf_race.json (raw rankings, so the decision rule can be re-tuned offline).
"""
import json
import os
import sys
from multiprocessing import Pool

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from enf_real_clips import CLIPS, trace  # noqa: E402
from provenance_fx.enf import race as RC  # noqa: E402
from provenance_fx.enf.extract import EnfTrace  # noqa: E402

LIB = os.path.join(ROOT, "validation_runs", "sim_library.npz")
WINDOWS = (600, 3600, 6 * 3600)


def mk(it):
    nom = 60 if it["grid"].startswith("US") else 50
    return EnfTrace(t=np.asarray(it["t"], float), f=np.asarray(it["f"], float), snr_db=np.asarray(it["snr"], float),
                    nominal=nom, harmonics_used=[], harmonic_snr_db={}, harmonic_corr={})


def one(args):
    it, W, seed = args
    rng = np.random.default_rng(seed)
    tr = mk(it)
    c = it["t_start"] + rng.uniform(-W, W)
    r = RC.grid_race(tr, c - W, c + W, allow_download=False)
    top = r["ranking"][0] if r["ranking"] else {}
    return dict(idx=int(it["idx"]), truth=it["grid"], window_s=W, dur=it["dur"], snr_db=it.get("p_snr_db"),
                stall=bool(it.get("p_stall")), decision=r["decision"], winner=r["winner"], margin=r["margin"],
                timing_error_s=(None if not top or it["grid"] == "NONE" else round(top["start_time"] - it["t_start"], 1)),
                ranking=r["ranking"], covered=[x["grid"] for x in r["ranking"]])


def score(rows):
    out = {}
    for W in sorted(set(r["window_s"] for r in rows)):
        rr = [r for r in rows if r["window_s"] == W]
        pos = [r for r in rr if r["truth"] != "NONE"]
        neg = [r for r in rr if r["truth"] == "NONE"]
        ans = [r for r in pos if r["decision"] != "abstain"]
        out[str(W)] = dict(
            n=len(pos), answered=len(ans), abstain_rate=round(1 - len(ans) / max(1, len(pos)), 3),
            accuracy_all=round(sum(r["winner"] == r["truth"] for r in pos) / max(1, len(pos)), 3),
            answered_accuracy=round(sum(r["winner"] == r["truth"] for r in ans) / max(1, len(ans)), 3) if ans else None,
            wrong_confident=sum(r["winner"] != r["truth"] for r in ans),
            decisive=sum(r["decision"] == "decisive" for r in pos),
            decisive_wrong=sum(r["decision"] == "decisive" and r["winner"] != r["truth"] for r in pos),
            no_hum_clips=len(neg), no_hum_false_answers=sum(r["decision"] != "abstain" for r in neg),
            raw_top_is_truth=round(sum(bool(r["ranking"]) and r["ranking"][0]["grid"] == r["truth"] for r in pos) / max(1, len(pos)), 3))
    return out


def main():
    items = [it for it in np.load(LIB, allow_pickle=True)["items"] if it["purpose"] == "race"]
    jobs = [(it, W, 7 * int(it["idx"]) + W) for it in items for W in WINDOWS]
    with Pool(6) as pool:
        rows = pool.map(one, jobs, chunksize=4)
    res = dict(sim=dict(summary=score(rows), rows=rows))
    print(json.dumps(res["sim"]["summary"], indent=1))
    real = []
    for key, path, t, w, truth, note in CLIPS:
        try:
            tr, det, scan = trace(key, path)
        except ValueError as e:
            real.append(dict(id=key, note=note, error=str(e)))
            continue
        for W in (w, 600 if "live" in key else 1800):
            r = RC.grid_race(tr, t - W, t + W, det=det)
            real.append(dict(id=key, note=note, truth=truth, window_s=W, hum=det["verdict"], decision=r["decision"],
                             winner=r["winner"], margin=r["margin"], reason=r["reason"],
                             ranking=[{k: x[k] for k in ("grid", "r", "raw_r", "offset_mhz", "p_false", "best_start")} for x in r["ranking"]],
                             not_covered=[x["grid"] for x in r["not_covered"]]))
            print(key, W, det["verdict"], r["decision"], r["winner"], r["margin"], [(x["grid"], x["r"]) for x in r["ranking"]])
    res["real"] = real
    json.dump(res, open(os.path.join(ROOT, "validation_runs", "enf_race.json"), "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
