"""Build provenance_fx/enf/grid_profiles.json from public grid-frequency logs (run once).

Sources (all no-login): NESO GB 1 s (Sept 2026), OSF power-grid frequency database
(Jumar et al. 2020/2023; GB01, FR01, PL01, IT01, SE01, US_UT01, US_TX01/02, US_FL01) and
the ENF-WHU 24 h mains references (Wuhan). Windows of 300-900 s get simulated recording
noise, then 8 s frame smoothing, so profiles look like what extract_enf produces.
"""
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provenance_fx.enf import gridid  # noqa: E402
from provenance_fx.enf import reference as R  # noqa: E402
_DATA = __import__("os").environ.get("PROVENANCE_DATA", __import__("os").path.expanduser("~/provenance-data"))

OSF = os.path.join(_DATA, "osf_pgfdb")
WHU_CACHE = os.path.expanduser("~/.cache/provenance/enf/whu")

SETS = {
    50: {
        "GB (Great Britain)": [("neso", (2026, 9)), ("osf", "GB01")],
        "Continental Europe": [("osf", "FR01"), ("osf", "PL01"), ("osf", "IT01")],
        "Nordic": [("osf", "SE01")],
        "China (Central grid, Wuhan)": [("whu", None)],
    },
    60: {
        "US Western Interconnection": [("osf", "US_UT01")],
        "US Texas (ERCOT)": [("osf", "US_TX01"), ("osf", "US_TX02")],
        "US Eastern Interconnection": [("osf", "US_FL01")],
    },
}


def load(kind, arg, nominal):
    if kind == "neso":
        return [R.neso_month(*arg).f]
    if kind == "osf":
        p = os.path.join(OSF, arg, arg + ".csv")
        if not os.path.exists(p):
            print("missing", p)
            return []
        return [R.from_csv(p, nominal=nominal).f]
    if kind == "whu":
        return [np.load(p)["f"] for p in sorted(glob.glob(os.path.join(WHU_CACHE, "*.npz")))]
    return []


def windows(series, n_win, rng, nominal):
    feats = []
    tries = 0
    total = sum(len(s) for s in series)
    while len(feats) < n_win and tries < n_win * 20:
        tries += 1
        s = series[rng.choice(len(series), p=[len(x) / total for x in series])]
        L = int(rng.uniform(300, 900))
        if len(s) <= L + 10:
            continue
        i = rng.integers(0, len(s) - L)
        w = s[i:i + L].astype(float).copy()
        if np.mean(np.isfinite(w)) < 0.95:
            continue
        w = w.copy()
        w += rng.normal(0, rng.uniform(0.3, 12.0) / 1000.0, L)         # estimation noise (recordings are noisy)
        if rng.random() < 0.5:                                          # dropped frames, later bridged
            w[rng.random(L) < rng.uniform(0, 0.3)] = np.nan
        w += rng.uniform(-3, 3) / 1000.0                                # recorder clock offset
        fv = gridid.features(w, nominal)
        if fv is not None and np.all(np.isfinite(fv)):
            feats.append(fv)
    return feats


def main():
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    from sklearn.model_selection import GroupKFold, cross_val_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(1)
    out = {}
    for nominal, classes in SETS.items():
        X, y, groups = [], [], []
        trained_on = {}
        for ci, (name, srcs) in enumerate(classes.items()):
            series = []
            for kind, arg in srcs:
                series += load(kind, arg, nominal)
            if not series:
                continue
            hours = sum(len(s) for s in series) / 3600
            trained_on[name] = f"{', '.join(str(a) if a else k for k, a in srcs)} ({hours:.0f} h)"
            # two halves -> groups so CV tests on time stretches it did not train on
            halves = []
            for s in series:
                h = len(s) // 2
                halves += [s[:h], s[h:]]
            for gi, part in enumerate(halves):
                fv = windows([part], 250 // max(1, len(halves) // 2), rng, nominal)
                X += fv; y += [name] * len(fv); groups += [f"{name}-{gi % 2}"] * len(fv)
            print(nominal, name, trained_on[name], sum(1 for v in y if v == name), flush=True)
        X = np.array(X); y = np.array(y); groups = np.array([g[-1] for g in groups])
        pipe = make_pipeline(StandardScaler(), LinearDiscriminantAnalysis())
        cv = cross_val_score(pipe, X, y, groups=groups, cv=GroupKFold(2))
        pipe.fit(X, y)
        sc, lda = pipe.named_steps["standardscaler"], pipe.named_steps["lineardiscriminantanalysis"]
        out[str(nominal)] = dict(classes=list(lda.classes_), coef=lda.coef_.tolist(),
                                 intercept=lda.intercept_.tolist(), mean=sc.mean_.tolist(),
                                 scale=sc.scale_.tolist(), features=gridid.FEATURES,
                                 cv_accuracy=round(float(cv.mean()), 3), trained_on=trained_on,
                                 n_windows=int(len(y)))
        print(nominal, "CV accuracy (train one half, test other):", cv)
    json.dump(out, open(gridid.PROFILE_PATH, "w"), indent=1)
    print("wrote", gridid.PROFILE_PATH)


if __name__ == "__main__":
    main()
