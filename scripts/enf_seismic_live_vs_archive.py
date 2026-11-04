"""Compare the live collector's rows with an archive rebuild of the same day (same stations, separate path).
Usage: python scripts/enf_seismic_live_vs_archive.py LIVE_CSV ARCHIVE_CSV_GZ [--after HH:MM]
Live rows are those written by `provenance enf-collect` (the archive-merged part of today's file is excluded by --after)."""
import csv, datetime as dt, gzip, json, sys
import numpy as np


def read(p):
    op = gzip.open if p.endswith(".gz") else open
    out = {}
    with op(p, "rt") as fh:
        for row in csv.DictReader(fh):
            out[row["time_utc"]] = (float(row["f_hz"]), int(row["n_sources"]))
    return out


live, arch = read(sys.argv[1]), read(sys.argv[2])
after = sys.argv[sys.argv.index("--after") + 1] if "--after" in sys.argv else "00:00"
keys = sorted(k for k in live if k[11:16] >= after and k in arch)
a = np.array([live[k][0] for k in keys]); b = np.array([arch[k][0] for k in keys])
d = (a - b) * 1000
lags = {L: float(np.corrcoef(a[max(0, L):len(a) + min(0, L)], b[max(0, -L):len(b) - max(0, L)])[0, 1]) for L in range(-3, 4)}
res = dict(seconds_compared=len(keys), first=keys[0] if keys else None, last=keys[-1] if keys else None,
           r=round(float(np.corrcoef(a, b)[0, 1]), 4), rmse_mhz=round(float(np.sqrt(np.mean(d ** 2))), 2),
           p95_abs_mhz=round(float(np.percentile(np.abs(d), 95)), 2), bias_mhz=round(float(d.mean()), 2),
           best_lag_s=max(lags, key=lags.get), live_median_stations=float(np.median([live[k][1] for k in keys])))
print(json.dumps(res, indent=1))
