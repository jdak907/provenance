"""Re-run the author's reference recording under a named configuration and score it.

Prints and appends to reference_validation/eval_runs.jsonl: the rank of the author's
flight pair (CST1219 + EGE93) and the distance from his stated answer.
Usage: python scripts/reference_eval.py NAME [v1|v2] [--flat] [--ev2 3040-3088]
"""
import argparse
import json
import math
import time

from provenance_fx.cli import do_locate

AUTHOR = (40.876466, -73.524951)
PAIR = ("CST1219", "EGE93")


def dist(a, b):
    R = 6371008.8
    la = math.radians((a[0] + b[0]) / 2)
    return math.hypot(math.radians(a[0] - b[0]) * R, math.radians(a[1] - b[1]) * R * math.cos(la))


ap = argparse.ArgumentParser()
ap.add_argument("name")
ap.add_argument("version", choices=["v1", "v2"])
ap.add_argument("--flat", action="store_true")
ap.add_argument("--ev2", default="3040-3088")
ap.add_argument("--audio", default="raw/reference_recording.wav")
a = ap.parse_args()
e2 = tuple(float(v) for v in a.ev2.split("-"))
if a.version == "v1":
    kw = dict(steady_window_s=None, search_overrides=dict(contrast_hz=0.0, normalise_events=False))
else:
    kw = dict(steady_window_s=60.0, search_overrides=dict(contrast_hz=4.0, normalise_events=True))
dem = "reference_validation/flat_5m.json" if a.flat else "reference_validation/dem_terrarium_z12.npz"
t = time.time()
res, s = do_locate(a.audio, "reference_validation/adsb_nyc_2026-09-08.csv", dem,
                   [40.60, 41.10, -73.90, -73.20], (1788825600.0, 1788912000.0),
                   f"reference_validation/runs/{a.name}", events=[(2090, 2225), e2], fmin=85, fmax=185,
                   obs_height=4, max_gap_s=300, log=lambda *x: None, **kw)
rank = None
pair_pt = None
for r in res.ranking:
    if (r["callsign1"], r["callsign2"]) == PAIR:
        rank, pair_pt = r["rank"], (r["lat"], r["lon"])
        break
out = dict(name=a.name, version=a.version, dem="flat 5 m" if a.flat else "AWS terrain z12", ev2=a.ev2,
           audio=a.audio, top=(res.best["fine_lat"], res.best["fine_lon"]),
           top_pair=(res.best["callsign1"], res.best["callsign2"]),
           top_error_m=round(dist((res.best["fine_lat"], res.best["fine_lon"]), AUTHOR)),
           author_pair_rank=rank,
           author_pair_error_m=round(dist(pair_pt, AUTHOR)) if pair_pt else None,
           margin=round(res.best.get("margin_over_second", float("nan")), 3),
           top3=[(r["callsign1"], r["callsign2"], round(r["total"], 3)) for r in res.ranking[:3]],
           secs=round(time.time() - t))
print(json.dumps(out))
open("reference_validation/eval_runs.jsonl", "a").write(json.dumps(out) + "\n")
