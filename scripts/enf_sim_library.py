"""Build a library of SIMULATED real-world recordings from real grid logs and extract their ENF.

Each clip: take a stretch of a real grid frequency log -> synthesise hum audio through
provenance_fx.enf.simulate.mic_chain (random harmonics, SNR, clock error, noise bursts, interferers,
stream stalls) -> run the normal extractor. The extracted traces are what the classifier is
trained on and what both modes are validated on, so training data looks like real
microphone output instead of clean grid logs (the root cause of GB being called Nordic).

Output: validation_runs/sim_library.npz (traces + labels + day groups + true start times).
"""
import datetime as dt
import glob
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provenance_fx.enf import grids as G  # noqa: E402
from provenance_fx.enf import reference as R  # noqa: E402
from provenance_fx.enf.extract import extract_enf  # noqa: E402
from provenance_fx.enf.simulate import mic_chain  # noqa: E402

MONTHS = [(2025, 1), (2025, 4), (2025, 5), (2025, 6), (2025, 8), (2025, 11), (2026, 3), (2026, 9)]
CE_DAYS = [dt.date(y, m, d) for y, m in MONTHS for d in (3, 10, 17, 24 if (y, m) != (2026, 9) else 23)]
WHU = sorted(glob.glob(os.path.expanduser("~/.cache/provenance/enf/whu/*.npz")))
OUT = os.path.join(os.path.dirname(__file__), "..", "validation_runs", "sim_library.npz")
_REF = {}


def _ref(kind, key):
    k = (kind, key)
    if k not in _REF:
        if kind == "neso":
            _REF[k] = R.neso_month(*key).to_1s()
        elif kind == "fingrid":
            _REF[k] = G.fingrid_month(*key)
        elif kind == "ce":
            _REF[k] = G.energy_charts_day(key)
        elif kind == "osf":
            _REF[k] = G._osf(key)
        elif kind == "whu":
            z = np.load(key)
            f = z["f"].astype(float)
            # note: these references show +-20 mHz steps lasting seconds to minutes. They are kept: the real
            # WHU recordings follow them (r 0.95 with steps, 0.5 after removing them), so they are real signal.
            _REF[k] = R.Reference(float(z["t0"]), 1.0, f, "WHU", 50, True, "WHU", 1.0)
    return _REF[k]


def pick(job):
    """job = (idx, grid, kind, key, seed, day_restrict, purpose)"""
    idx, grid, kind, key, seed, day, purpose = job
    rng = np.random.default_rng(seed)
    ref = _ref(kind, key)
    dur = int(rng.uniform(180, 1200))
    f = ref.f
    for _ in range(200):
        if day is not None:
            a = int((dt.datetime.combine(day, dt.time(0), dt.timezone.utc).timestamp() - ref.t0))
            i0 = int(rng.integers(max(0, a), max(1, min(len(f) - dur - 1, a + 86400 - dur))))
        else:
            i0 = int(rng.integers(0, len(f) - dur - 1))
        seg = f[i0:i0 + dur].astype(float)
        if np.isfinite(seg).mean() > 0.97:
            break
    else:
        return None
    ok = np.isfinite(seg)
    seg = np.interp(np.arange(dur), np.where(ok)[0], seg[ok])
    t_start = ref.t0 + i0
    nominal = 60 if grid.startswith("US") else 50
    if grid == "NONE":
        seg = np.full(dur, np.nan)
    try:
        if grid == "NONE":
            sr = 1000
            x = rng.normal(0, 1, dur * sr)
            if rng.random() < 0.5:  # an interferer tone only (looks like hum, is not mains)
                x += 0.3 * np.sin(2 * np.pi * (100 + rng.uniform(-0.1, 0.1)) * np.arange(dur * sr) / sr)
            params = dict(profile="none", snr_db=None, clock_ppm=0, stall=False, interferer=True)
        else:
            sr, x, params = mic_chain(seg, rng, nominal=nominal)
        tr = extract_enf(x, sr, nominal)
    except ValueError:
        return None
    day_id = (kind + ":" + (str(key) if kind != "whu" else os.path.basename(key)) + ":" +
              (dt.datetime.fromtimestamp(t_start, dt.timezone.utc).date().isoformat() if not ref.relative else ""))
    return dict(idx=idx, grid=grid, group=day_id, t_start=None if ref.relative else float(t_start),
                t=tr.t.astype(np.float32), f=tr.f.astype(np.float64), snr=tr.snr_db.astype(np.float32),
                purpose=purpose, dur=dur, **{"p_" + k: v for k, v in params.items()})


def jobs():
    J = []
    s = 1000

    def add(grid, kind, key, n, day=None, purpose="train"):
        nonlocal s
        for _ in range(n):
            J.append((len(J), grid, kind, key, s, day, purpose))
            s += 1
    # race clips: days where GB, CE and Nordic all have concurrent 1 s logs
    for d in CE_DAYS:
        add("GB", "neso", (d.year, d.month), 2, d, "race")
        add("NORDIC", "fingrid", (d.year, d.month), 2, d, "race")
        add("CE", "ce", d, 2, d, "race")
        add("NONE", "ce", d, 1, d, "race")
    # US race: Utah (West) and Texas overlap 2019-05-20..23
    for d in [dt.date(2019, 5, 20), dt.date(2019, 5, 21), dt.date(2019, 5, 22)]:
        add("US-WEST", "osf", "US_UT01", 4, d, "race")
        add("US-TEXAS", "osf", "US_TX02", 4, d, "race")
    # classifier pool (many days)
    for y, m in MONTHS:
        add("GB", "neso", (y, m), 30)
        add("NORDIC", "fingrid", (y, m), 30)
    for d in CE_DAYS:
        add("CE", "ce", d, 6, d)
    for code in ("FR01", "PL01", "IT01"):
        add("CE", "osf", code, 25)
    add("GB", "osf", "GB01", 25)
    add("NORDIC", "osf", "SE01", 40)
    for p in WHU:
        add("CHINA", "whu", p, 10)
    add("US-WEST", "osf", "US_UT01", 120)
    add("US-TEXAS", "osf", "US_TX01", 50)
    add("US-TEXAS", "osf", "US_TX02", 70)
    add("US-EAST", "osf", "US_FL01", 160)
    return J


if __name__ == "__main__":
    J = jobs()
    # group by source so each worker keeps few references in memory
    J.sort(key=lambda j: (j[2], str(j[3])))
    t0 = time.time()
    out = []
    with Pool(7) as pool:
        for i, r in enumerate(pool.imap_unordered(pick, J, chunksize=8)):
            if r:
                out.append(r)
            if i % 100 == 0:
                print(f"{i}/{len(J)} {time.time() - t0:.0f}s", flush=True)
    out.sort(key=lambda r: r["idx"])
    np.savez_compressed(OUT, items=np.array(out, dtype=object))
    print("saved", len(out), "clips to", OUT, f"{time.time() - t0:.0f}s")
