"""Supplement to enf_validate_us Part C: pretend the assumed Pigott offset is wrong by one hour
(UTC-6 instead of the inferred UTC-7) and check the race's clock-shift search recovers it (expects -1 h)."""
import json, sys, numpy as np
sys.path.insert(0, "scripts")
import enf_validate_us as V
from provenance_fx.enf import us_refs as U
U.PIGOTT_TZ_H = -6.0
items = [it for it in np.load("validation_runs/enf_us_sim.npz", allow_pickle=True)["items"] if it["part"] == "C"]
rows = [V.race_one((it, 3600, False, 1000 + i)) for i, it in enumerate(items)]
ans = [r for r in rows if r["decision"] != "abstain"]
out = dict(n=len(rows), answered=len(ans), correct=sum(r["winner"] == r["truth"] for r in ans),
           shift_chosen={str(s): sum(r["tz_shift_h"] == s for r in ans) for s in (0.0, -1.0, 1.0, 7.0)},
           timing_within_5s=sum(abs(r["timing_error_s"] or 99) <= 5 for r in ans))
print(json.dumps(out, indent=1))
json.dump(dict(summary=out, rows=rows), open("validation_runs/enf_pigott_tzsearch.json", "w"), indent=1, default=str)
