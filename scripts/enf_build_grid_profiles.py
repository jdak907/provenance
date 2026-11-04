"""Train the v2 fallback grid classifier on ENF extracted from simulated recordings.

Data: validation_runs/sim_library.npz (scripts/enf_sim_library.py).
Model: multinomial logistic regression per nominal family, features from provenance_fx.enf.gridid.
Validation: GroupKFold by DAY (a whole day of a grid log is held out together), so the
numbers say how it does on days it never saw. Probabilities are temperature-calibrated on
the out-of-fold predictions; the abstain threshold is the lowest top-probability at which
held-out answered accuracy reaches TARGET.
Writes provenance_fx/enf/grid_profiles.json and validation_runs/enf_gridid_cv.json.
"""
import json
import os
import sys

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from provenance_fx.enf import gridid  # noqa: E402
_DATA = __import__("os").environ.get("PROVENANCE_DATA", __import__("os").path.expanduser("~/provenance-data"))

TARGET = 0.90
LIB = os.path.join(ROOT, "validation_runs", "sim_library.npz")
FAMILIES = {50: ["GB", "CE", "NORDIC", "CHINA"], 60: ["US-WEST", "US-TEXAS", "US-EAST"]}


def grid1s(it):
    t = it["t"] - it["t"][0]
    n = int(round(t[-1])) + 1
    tt = np.arange(n, dtype=float)
    ok = np.isfinite(it["f"])
    if ok.sum() < 2:
        return np.full(n, np.nan)
    q = np.interp(tt, t[ok], it["f"][ok])
    near = np.clip(np.searchsorted(t, tt), 0, len(t) - 1)
    q[~ok[near]] = np.nan
    return q


WHU_ROOT = os.path.join(_DATA, "ENF-WHU-Dataset/ENF-WHU-Dataset")


def whu_real_items():
    """Real ENF-WHU H1 recordings (China) as extracted traces, grouped by their reference day.
    Training on some real microphone ENF anchors the China class; other classes have no free
    labelled real recordings, so they rely on the simulation."""
    import glob
    import re
    if not os.path.isdir(os.path.join(WHU_ROOT, "H1_ref_one_day")):
        return []
    dayof = {}
    for fn in os.listdir(os.path.join(WHU_ROOT, "H1_ref_one_day")):
        m = re.match(r"(\d+)(?:-(\d+))?_ref\.wav", fn)
        a = int(m.group(1)); b2 = int(m.group(2) or a)
        for i in range(a, b2 + 1):
            dayof[i] = fn
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "validation_runs", "traces", "whu_*.npz"))):
        i = int(os.path.basename(p)[4:7])
        z = np.load(p)
        out.append(dict(grid="CHINA", group=f"whu:{dayof.get(i, 'none')}.npz:", t=z["t"], f=z["f"],
                        dur=float(z["t"][-1] - z["t"][0]), real=True, id=i))
    return out


def dataset(items, nominal, exclude=()):
    X, y, g, dur, keep = [], [], [], [], []
    for i, it in enumerate(items):
        if it["grid"] not in FAMILIES[nominal] or i in exclude:
            continue
        fv = gridid.features(grid1s(it), nominal)
        if fv is None or not np.all(np.isfinite(fv)):
            continue
        X.append(fv); y.append(it["grid"]); g.append(it["group"]); dur.append(it["dur"]); keep.append(i)
    return np.array(X), np.array(y), np.array(g), np.array(dur), keep


def fit(X, y, C):
    sc = StandardScaler().fit(X)
    lr = LogisticRegression(C=C, max_iter=5000).fit(sc.transform(X), y)
    return sc, lr


def oof(X, y, g, C, k=5):
    P = np.zeros((len(y), len(np.unique(y))))
    L = np.zeros_like(P)
    for tr, te in GroupKFold(k).split(X, y, g):
        sc, lr = fit(X[tr], y[tr], C)
        L[te] = lr.decision_function(sc.transform(X[te]))
        P[te] = lr.predict_proba(sc.transform(X[te]))
    return L, lr.classes_


def softmax(L, T):
    z = L / T
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def metrics(P, y, classes, thr, dur=None, min_dur=0):
    pred = classes[P.argmax(1)]
    top = P.max(1)
    ans = top >= thr
    if dur is not None:
        ans &= dur >= min_dur
    right = pred == y
    return dict(n=int(len(y)), accuracy_forced=float(right.mean()), abstain_rate=float(1 - ans.mean()),
                answered_accuracy=float(right[ans].mean()) if ans.any() else 0.0,
                wrong_confident=int((~right & ans).sum()), wrong_confident_rate=float((~right & ans).mean()),
                threshold=float(thr))


def main():
    items = list(np.load(LIB, allow_pickle=True)["items"])
    if not os.environ.get("PROVENANCE_NO_REAL_WHU"):
        items += whu_real_items()
    profiles, report = {}, {}
    for nominal, classes in FAMILIES.items():
        X, y, g, dur, _ = dataset(items, nominal)
        best = None
        for C in (0.03, 0.1, 0.3, 1.0, 3.0):
            L, cl = oof(X, y, g, C)
            P = softmax(L, 1.0)
            nll = -np.mean(np.log(P[np.arange(len(y)), np.searchsorted(cl, y)] + 1e-12))
            acc = float((cl[P.argmax(1)] == y).mean())
            print(nominal, "C", C, "oof acc", round(acc, 3), "nll", round(nll, 3))
            if best is None or nll < best[0]:
                best = (nll, C, L, cl)
        _, C, L, cl = best
        yi = np.searchsorted(cl, y)
        T = minimize_scalar(lambda T: -np.mean(np.log(softmax(L, T)[np.arange(len(y)), yi] + 1e-12)),
                            bounds=(0.2, 5), method="bounded").x
        P = softmax(L, T)
        thr = 1.0
        for t in np.arange(0.4, 0.99, 0.01):
            m = metrics(P, y, cl, t, dur, 300)
            if m["answered_accuracy"] >= TARGET and m["abstain_rate"] < 0.95:
                thr = float(t)
                break
        cvm = metrics(P, y, cl, thr, dur, 300)
        cvm.update(C=C, temperature=round(float(T), 3), groups=int(len(set(g))),
                   per_class={c: dict(n=int((y == c).sum()), recall_forced=float((cl[P.argmax(1)][y == c] == c).mean()))
                              for c in cl},
                   confusion={c: {c2: int(((y == c) & (cl[P.argmax(1)] == c2)).sum()) for c2 in cl} for c in cl},
                   by_duration={f"{a}-{b}s": metrics(P[(dur >= a) & (dur < b)], y[(dur >= a) & (dur < b)], cl, thr)
                                for a, b in ((180, 300), (300, 600), (600, 900), (900, 1201))})
        print(nominal, json.dumps({k: v for k, v in cvm.items() if k not in ("confusion", "by_duration", "per_class")}))
        sc, lr = fit(X, y, C)
        coef = lr.coef_
        icpt = lr.intercept_
        if len(cl) == 2:
            coef = np.vstack([-coef[0] / 2, coef[0] / 2]); icpt = np.array([-icpt[0] / 2, icpt[0] / 2])
        profiles[str(nominal)] = dict(
            classes=[str(c) for c in cl], features=gridid.FEATURES, mean=sc.mean_.tolist(), scale=sc.scale_.tolist(),
            coef=coef.tolist(), intercept=icpt.tolist(), temperature=float(T), abstain_below=thr, min_duration_s=300,
            # out-of-distribution limits: 98th percentile of the training traces' fine-scale noise
            ood_max={k: float(np.percentile(X[:, gridid.FEATURES.index(k)], 98)) for k in ("log_d1", "log_d2", "log_w8")},
            cv={k: cvm[k] for k in ("n", "accuracy_forced", "abstain_rate", "answered_accuracy", "wrong_confident_rate", "groups")},
            trained_on="ENF extracted from simulated recordings (mic_chain) of: NESO GB 8 months, Fingrid Nordic 8 months, "
                       "Energy-Charts CE 32 days + OSF FR/PL/IT, OSF GB01/SE01, WHU China 28 days (simulated + 130 real WHU recordings), OSF US UT/TX/FL")
        report[str(nominal)] = cvm
    json.dump(profiles, open(gridid.PROFILE_PATH, "w"), indent=1)
    json.dump(report, open(os.path.join(ROOT, "validation_runs", "enf_gridid_cv.json"), "w"), indent=1)
    print("wrote", gridid.PROFILE_PATH)


if __name__ == "__main__":
    main()
