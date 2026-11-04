"""Validate ENF timestamping on the real ENF-WHU recordings (MIT license, Wuhan, 50 Hz).

Ground truth (per the dataset README): match each clean H1_ref/NNN_ref.wav inside its
24 h H1_ref_one_day reference; that lag is the true position. We then match the noisy
phone/recorder audio H1/NNN.wav (raw, untouched) inside the same 24 h and report the error.
H0 recordings (no ENF) are negative controls for the detector and the matcher.

Usage: python scripts/enf_validate_whu.py [--root DIR] [--jobs 4] [--out validation_runs/enf_whu.json]
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provenance_fx.enf import detect_enf, extract_enf, hum_scan, load_raw  # noqa: E402
from provenance_fx.enf import match as M  # noqa: E402
from provenance_fx.enf import reference as R  # noqa: E402
_DATA = __import__("os").environ.get("PROVENANCE_DATA", __import__("os").path.expanduser("~/provenance-data"))

CACHE = os.path.expanduser("~/.cache/provenance/enf/whu")


def day_ref(path):
    os.makedirs(CACHE, exist_ok=True)
    npz = os.path.join(CACHE, os.path.basename(path) + ".npz")
    if os.path.exists(npz):
        z = np.load(npz)
        return R.Reference(float(z["t0"]), 1.0, z["f"], os.path.basename(path), 50, True, "wav", 1.0)
    r = R.from_wav(path)
    np.savez(npz, t0=r.t0, f=r.f)
    return r


def day_files(root):
    out = {}
    for fn in os.listdir(os.path.join(root, "H1_ref_one_day")):
        m = re.match(r"(\d+)(?:-(\d+))?_ref\.wav", fn)
        a = int(m.group(1)); b = int(m.group(2) or a)
        for i in range(a, b + 1):
            out[i] = os.path.join(root, "H1_ref_one_day", fn)
    return out


def one(args):
    root, i, dayp = args
    t0 = time.time()
    day = day_ref(dayp)
    sr, x, _ = load_raw(os.path.join(root, "H1_ref", f"{i:03d}_ref.wav"))
    tref = extract_enf(x, sr, nominal=50, harmonics=[1])
    gt = M.match(tref, day)
    sr, x, _ = load_raw(os.path.join(root, "H1", f"{i:03d}.wav"))
    scan = hum_scan(x, sr)
    tr = extract_enf(x, sr, nominal=50)
    det = detect_enf(tr)
    m = M.match(tr, day)
    # also: what if we only had the first 2 minutes?
    k = int(120 / tr.hop_s)
    from provenance_fx.enf.extract import EnfTrace
    short = EnfTrace(tr.t[:k], tr.f[:k], tr.snr_db[:k], 50, tr.harmonics_used, tr.harmonic_snr_db, tr.harmonic_corr)
    ms = M.match(short, day)
    return dict(id=i, duration=round(len(x) / sr, 1), truth_s=gt["start_time"], truth_ncc=gt["ncc"],
                est_s=m["start_time"], err_s=m["start_time"] - gt["start_time"], ncc=m["ncc"],
                second=m["second_ncc"], label=m["label"], p_false=m["p_false"], rmse_mhz=m["rmse_mhz"],
                detect=det["verdict"], det_score=det["score"], harmonics=tr.harmonics_used,
                scan_nominal=scan["nominal"], short_err_s=ms["start_time"] - gt["start_time"],
                short_label=ms["label"], short_ncc=ms["ncc"], secs=round(time.time() - t0, 1))


def neg(args):
    root, fn, dayp = args
    day = day_ref(dayp)
    sr, x, _ = load_raw(os.path.join(root, "H0", fn))
    tr = extract_enf(x, sr, nominal=50)
    det = detect_enf(tr)
    m = M.match(tr, day)
    return dict(file=fn, duration=round(len(x) / sr, 1), detect=det["verdict"], det_score=det["score"],
                ncc=m["ncc"], label=m["label"], p_false=m["p_false"], reasons=det["reasons"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(_DATA, "ENF-WHU-Dataset/ENF-WHU-Dataset"))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--ids", default="1-130")
    ap.add_argument("--out", default="validation_runs/enf_whu.json")
    a = ap.parse_args()
    lo, hi = map(int, a.ids.split("-"))
    days = day_files(a.root)
    uniq = sorted(set(days.values()))
    with ProcessPoolExecutor(a.jobs) as ex:     # warm the 24 h reference cache first
        list(ex.map(day_ref, uniq))
        print("day references ready", flush=True)
        pos = list(ex.map(one, [(a.root, i, days[i]) for i in range(lo, hi + 1)]))
        h0 = sorted(os.listdir(os.path.join(a.root, "H0")))
        negs = list(ex.map(neg, [(a.root, fn, days[(j % 130) + 1]) for j, fn in enumerate(h0)]))
    errs = np.array([abs(p["err_s"]) for p in pos])
    summ = dict(n=len(pos), within_10s=int((errs <= 10).sum()), within_60s=int((errs <= 60).sum()),
                median_abs_err_s=float(np.median(errs)),
                strong=sum(p["label"] == "strong" for p in pos),
                strong_correct=sum(p["label"] == "strong" and abs(p["err_s"]) <= 10 for p in pos),
                moderate=sum(p["label"] == "moderate" for p in pos),
                moderate_correct=sum(p["label"] == "moderate" and abs(p["err_s"]) <= 10 for p in pos),
                short2min_within_10s=int(sum(abs(p["short_err_s"]) <= 10 for p in pos)),
                short2min_confident_wrong=int(sum(p["short_label"] in ("strong", "moderate") and abs(p["short_err_s"]) > 10 for p in pos)),
                detect_present_h1=sum(p["detect"] == "present" for p in pos),
                h0_n=len(negs), h0_detect_present=sum(n["detect"] == "present" for n in negs),
                h0_confident_match=sum(n["label"] in ("strong", "moderate") for n in negs))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(dict(summary=summ, positives=pos, negatives=negs), open(a.out, "w"), indent=1, default=float)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
