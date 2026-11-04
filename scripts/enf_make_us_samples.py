"""GUI demo clips for the US references: SIMULATED recordings (mic_chain) cut from real logs.
Each WAV's true start time is in samples.json. Not used for validation (different times)."""
import datetime as dt
import json
import os
import sys

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from provenance_fx.enf import us_refs as U  # noqa: E402
from provenance_fx.enf.simulate import mic_chain  # noqa: E402
_DATA = __import__("os").environ.get("PROVENANCE_DATA", __import__("os").path.expanduser("~/provenance-data"))

OUT = os.path.join(_DATA, "us/samples")
CLIPS = [  # id, source key, start UTC, seconds, seed
    ("wecc2024", "zenodo_wecc_2024", "2024-10-08T14:20:00", 900, 11),
    ("ng2026", "nategriff_wecc", "2026-04-15T17:05:00", 900, 12),
    ("phx2022", "pigott_phx_2022", "2022-07-20T03:10:00", 900, 13),
]


def main():
    meta = {}
    for cid, key, start, dur, seed in CLIPS:
        r = U.load(key)
        r = r.to_1s() if r.step != 1 else r
        t = dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc).timestamp()
        others = [U.load(k) for k in (["nategriff_ei", "nategriff_ercot", "nategriff_quebec"] if key.startswith("nategriff") else [])]
        while True:   # first 15 min from `start` (5 min steps) where every needed log is >98 % complete
            i = int(t - r.t0)
            seg = r.f[i:i + dur].astype(float)
            ok = np.isfinite(seg)
            if ok.mean() > 0.98 and all(np.isfinite(o.f[int(t - o.t0):int(t - o.t0) + dur + 3600]).mean() > 0.9 for o in others):
                break
            t += 300
        start = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        seg = np.interp(np.arange(dur), np.where(ok)[0], seg[ok])
        rng = np.random.default_rng(seed)
        sr, x, p = mic_chain(seg, rng, snr_db=-2.0, stall=False, interferer=False, nominal=60, profile="phone_highpass")
        y = resample_poly(x, 8, 1)
        y = (y / np.max(np.abs(y)) * 0.8 * 32767).astype(np.int16)
        path = os.path.join(OUT, f"sim_{cid}.wav")
        wavfile.write(path, 8000, y)
        meta[cid] = dict(path=path, true_start_utc=start, source=key, seconds=dur, mic_chain=p)
        print(cid, path, p)
    json.dump(meta, open(os.path.join(OUT, "samples.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
