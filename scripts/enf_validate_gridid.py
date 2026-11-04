"""Before/after validation of the time-unknown grid classifier (v1 legacy vs v2).

Sets:
  sim    ENF extracted from simulated recordings of real grid logs (sim_library.npz);
         v2 numbers are out-of-fold by DAY (GroupKFold), v1 was trained on other data.
  whu    130 real ENF-WHU H1 recordings (China, 50 Hz). v2 is retrained with the WHU days that
         belong to each test recording held out (4 folds), so it never saw that day.
  uk     real UK recordings (GB truth), never used in training.
Rule for "confident": v1 = top prob >= 70 % and clip >= 300 s (its own verdict rule);
v2 = its abstain rule (threshold from CV, clip >= 300 s, <40 % gaps, hum present).
Writes validation_runs/enf_gridid_validation.json
"""
import json
import os
import re
import sys
from multiprocessing import Pool

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import enf_build_grid_profiles as B  # noqa: E402
import legacy_gridid_v1 as V1  # noqa: E402
from enf_real_clips import CLIPS, trace  # noqa: E402
from provenance_fx.enf import gridid as V2  # noqa: E402
from provenance_fx.enf.extract import EnfTrace, extract_enf  # noqa: E402
from provenance_fx.enf.media import load_raw  # noqa: E402
_DATA = __import__("os").environ.get("PROVENANCE_DATA", __import__("os").path.expanduser("~/provenance-data"))

WHU = os.path.join(_DATA, "ENF-WHU-Dataset/ENF-WHU-Dataset")
V1MAP = {"China (Central grid, Wuhan)": "CHINA", "Continental Europe": "CE", "GB (Great Britain)": "GB",
         "Nordic": "NORDIC", "US Eastern Interconnection": "US-EAST", "US Texas (ERCOT)": "US-TEXAS",
         "US Western Interconnection": "US-WEST"}


def mk(t, f, nominal):
    return EnfTrace(t=np.asarray(t, float), f=np.asarray(f, float), snr_db=np.zeros(len(t)), nominal=nominal,
                    harmonics_used=[], harmonic_snr_db={}, harmonic_corr={})


def v1_pred(tr, nominal):
    r = V1.classify(tr, nominal)
    if not r.get("best"):
        return None, 0.0, False
    p = r["probs"][r["best"]]
    return V1MAP[r["best"]], p, bool(p >= 0.7 and tr.duration >= 300)


def v2_pred(tr, nominal, profiles=None, det=None):
    r = V2.classify(tr, nominal, profiles=profiles, det=det)
    return r["best"], (r["probs"] or {}).get(r["best"], 0.0), r["decision"] != "unknown"


def summarize(rows):
    n = len(rows)
    conf = [r for r in rows if r["confident"]]
    return dict(n=n, forced_accuracy=round(np.mean([r["pred"] == r["truth"] for r in rows]), 3) if n else None,
                answered=len(conf), abstain_rate=round(1 - len(conf) / n, 3) if n else None,
                answered_accuracy=round(np.mean([r["pred"] == r["truth"] for r in conf]), 3) if conf else None,
                wrong_confident=sum(r["pred"] != r["truth"] for r in conf))


def whu_trace(i):
    p = os.path.join(ROOT, "validation_runs", "traces", f"whu_{i:03d}.npz")
    if os.path.exists(p):
        z = np.load(p)
        return i, z["t"], z["f"]
    sr, x, _ = load_raw(os.path.join(WHU, "H1", f"{i:03d}.wav"))
    tr = extract_enf(x, sr, nominal=50)
    np.savez(p, t=tr.t, f=tr.f)
    return i, tr.t, tr.f


def whu_day_of():
    out = {}
    for fn in os.listdir(os.path.join(WHU, "H1_ref_one_day")):
        m = re.match(r"(\d+)(?:-(\d+))?_ref\.wav", fn)
        a = int(m.group(1)); b = int(m.group(2) or a)
        for i in range(a, b + 1):
            out[i] = fn
    return out


def train_profiles(items, exclude_groups):
    """Retrain v2 (same recipe) without some groups; used for the WHU held-out-day test."""
    import tempfile
    extra = [] if os.environ.get("PROVENANCE_NO_REAL_WHU") else B.whu_real_items()
    keep = [it for it in items + extra if it["group"] not in exclude_groups]
    prof = json.load(open(V2.PROFILE_PATH))
    X, y, g, dur, _ = B.dataset(keep, 50)
    m = prof["50"]
    sc, lr = B.fit(X, y, B.json.load(open(os.path.join(ROOT, "validation_runs", "enf_gridid_cv.json")))["50"]["C"])
    p2 = dict(prof)
    p2["50"] = dict(m, ood_max={k: float(np.percentile(X[:, V2.FEATURES.index(k)], 98)) for k in ("log_d1", "log_d2", "log_w8")}, mean=sc.mean_.tolist(), scale=sc.scale_.tolist(), coef=lr.coef_.tolist(),
                    intercept=lr.intercept_.tolist(), classes=[str(c) for c in lr.classes_])
    return p2


def main():
    items = list(np.load(B.LIB, allow_pickle=True)["items"])
    res = {}
    # ---- sim (v1 on everything; v2 out-of-fold from the training CV)
    rows_v1 = {50: [], 60: []}
    for it in items:
        if it["grid"] == "NONE":
            continue
        nom = 60 if it["grid"].startswith("US") else 50
        tr = mk(it["t"], it["f"], nom)
        p, pr, c = v1_pred(tr, nom)
        rows_v1[nom].append(dict(truth=it["grid"], pred=p, p=pr, confident=c))
    cv = json.load(open(os.path.join(ROOT, "validation_runs", "enf_gridid_cv.json")))
    res["sim"] = {str(n): dict(v1=summarize(rows_v1[n]),
                               v2=dict(n=cv[str(n)]["n"], forced_accuracy=round(cv[str(n)]["accuracy_forced"], 3),
                                       abstain_rate=round(cv[str(n)]["abstain_rate"], 3),
                                       answered_accuracy=round(cv[str(n)]["answered_accuracy"], 3),
                                       wrong_confident=cv[str(n)]["wrong_confident"]))
                  for n in (50, 60)}
    print("sim", json.dumps(res["sim"]))
    # ---- WHU real recordings
    with Pool(7) as pool:
        whu = sorted(pool.map(whu_trace, range(1, 131)))
    dayof = whu_day_of()
    days = sorted(set(dayof.values()))
    folds = [days[k::4] for k in range(4)]
    rows1, rows2 = [], []
    for fold in folds:
        excl = {f"whu:{d}.npz:" for d in fold} | ({"whu:none.npz:"} if fold is folds[0] else set())
        prof = train_profiles(items, excl)
        for i, t, f in whu:
            if dayof.get(i) not in fold and not (dayof.get(i) is None and fold is folds[0]):
                continue
            tr = mk(t, f, 50)
            p, pr, c = v1_pred(tr, 50)
            rows1.append(dict(id=i, truth="CHINA", pred=p, p=round(pr, 3), confident=c))
            p, pr, c = v2_pred(tr, 50, profiles=prof)
            rows2.append(dict(id=i, truth="CHINA", pred=p, p=round(pr, 3), confident=c))
    res["whu"] = dict(v1=summarize(rows1), v2=summarize(rows2))
    print("whu", json.dumps(res["whu"]))
    # ---- UK real clips
    rows1, rows2 = [], []
    for key, path, t, w, truth, note in CLIPS:
        try:
            tr, det, scan = trace(key, path)
        except ValueError as e:
            continue
        p, pr, c = v1_pred(tr, 50)
        rows1.append(dict(id=key, truth=truth, pred=p, p=round(pr, 3), confident=c, hum=det["verdict"]))
        p, pr, c = v2_pred(tr, 50, det=det)
        rows2.append(dict(id=key, truth=truth, pred=p, p=round(pr, 3), confident=c, hum=det["verdict"]))
    hum = lambda rows: [r for r in rows if r["hum"] != "absent" and r["id"] != "york_south_live"]
    res["uk"] = dict(v1=summarize(hum(rows1)), v2=summarize(hum(rows2)), rows_v1=rows1, rows_v2=rows2)
    print("uk", json.dumps({k: res["uk"][k] for k in ("v1", "v2")}))
    for a, b in zip(rows1, rows2):
        print(f"  {a['id']:18s} hum={a['hum']:8s} v1={a['pred']} {a['p']:.2f}{'*' if a['confident'] else ''}  v2={b['pred']} {b['p']:.2f}{'*' if b['confident'] else ''}")
    json.dump(res, open(os.path.join(ROOT, "validation_runs", "enf_gridid_validation.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
