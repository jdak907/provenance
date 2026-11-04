"""Run the full demo on several random scenes and write validation_synthetic.md.

Usage: python scripts/validate.py [seed ...]   (default seeds 1-8)
"""
import json
import os
import sys
import time

from provenance_fx.cli import do_demo

seeds = [int(s) for s in sys.argv[1:]] or list(range(1, 9))
rows = []
for s in seeds:
    t = time.time()
    out = f"validation_runs/seed{s}"
    ok, s1, s2 = do_demo(out, s, log=lambda *a: None)
    rows.append(dict(seed=s, two=s1.get("error_m", float("nan")),
                     two_pair_ok=s1.get("best", {}).get("flight1", "").startswith("c00001")
                     and s1.get("best", {}).get("flight2", "").startswith("c00002"),
                     margin=s1.get("best", {}).get("margin_over_second", float("nan")),
                     one=s2.get("error_m", float("nan")),
                     one_alt=s2.get("error_best_or_close_alternative_m", float("nan")),
                     secs=time.time() - t))
    print(rows[-1], flush=True)

L = ["# Validation across random synthetic scenes\n",
     "Each scene: 60 by 60 km box, 6 hours of traffic (about 500 flights, half known jets, plus a busy "
     "airport), a hidden listener, a 21-minute clip with two faint propeller flyovers 920 s apart, and a "
     "one-minute clip with a known start time.\n",
     "| Seed | Two-event error (m) | Right flight pair | Lead over runner-up | One-minute error (m) | "
     "One-minute, best or near-tie alternative (m) | Run time (s) |",
     "|---|---|---|---|---|---|---|"]
for r in rows:
    L.append(f"| {r['seed']} | {r['two']:.0f} | {'yes' if r['two_pair_ok'] else 'no'} | {r['margin']:.2f} | "
             f"{r['one']:.0f} | {r['one_alt']:.0f} | {r['secs']:.0f} |")
n = len(rows)
L.append(f"\nTwo-event mode within 150 m: {sum(r['two'] < 150 for r in rows)} of {n}.")
L.append(f"One-minute mode, top answer within 150 m: {sum(r['one'] < 150 for r in rows)} of {n}.")
L.append(f"One-minute mode, truth within 150 m of the top answer or a listed near-tie alternative: "
         f"{sum(r['one_alt'] < 150 for r in rows)} of {n}.")
open("validation_synthetic.md", "w").write("\n".join(L) + "\n")
print("\n".join(L))
