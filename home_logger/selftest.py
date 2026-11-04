#!/usr/bin/env python3
"""Quick checks that the home logger is measuring the real grid, with a correct UTC clock.

  python3 selftest.py ~/gridfreq/gridfreq_2026-11-03.csv [--fnet]

1. Clock: asks chrony whether the Pi is locked to GPS PPS and how far off it is.
2. Numbers: mean should sit within ~20 mHz of 60 Hz; the spread over a day is typically 10-25 mHz;
   second-to-second steps are typically 1-3 mHz. A dead input gives 0 rows or exactly 60.000000.
3. Minute pattern: US West frequency dips slightly at the start of every clock minute (battery and
   UPS controllers synced to internet time; Hartmann et al. 2025). After a few hours of data the
   average shape over the minute should show its low point in the first ~15 seconds. If the dip sits
   elsewhere, the timestamps are offset.
4. --fnet: downloads the public FNET/GridEye frequency gauge image (University of Tennessee, read-only
   public page) next to your latest reading, so you can compare by eye: they should agree within a few mHz.
   Rob Ruark's public MQTT dashboard (robruark.com/projects/grid_frequency/AI/) is a second live check.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import os

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_csv import rows  # noqa: E402

FNET_GAUGE = "https://fnetpublic.utk.edu/freqgauge.php"


def stats(path):
    t, f = [], []
    for ti, fi, cyc, flags, sync in rows(path):
        if 59.5 < fi < 60.5:
            t.append(ti); f.append(fi)
    t, f = np.array(t), np.array(f)
    out = dict(rows=len(f))
    if len(f) < 10:
        return out, t, f
    d = np.diff(f)[np.diff(t) == 1]
    out.update(mean_hz=round(float(f.mean()), 5), std_mhz=round(float(f.std() * 1000), 2),
               step_std_mhz=round(float(d.std() * 1000), 2) if len(d) else None,
               coverage_pct=round(float(100 * len(f) / (t[-1] - t[0] + 1)), 1),
               flat=bool(np.ptp(f) < 1e-4))
    return out, t, f


def minute_pattern(t, f):
    if len(f) < 3 * 3600:
        return None
    # remove slow drift (5 min running mean), then average by second of minute
    k = 301
    pad = np.pad(f, k // 2, mode="edge")
    slow = np.convolve(pad, np.ones(k) / k, "valid")
    r = f - slow
    s = np.bincount(t % 60, weights=r, minlength=60) / np.maximum(np.bincount(t % 60, minlength=60), 1)
    return dict(lowest_second=int(np.argmin(s)), depth_mhz=round(float((s.max() - s.min()) * 1000), 3),
                profile_mhz=[round(float(v * 1000), 3) for v in s])


def chrony():
    try:
        out = subprocess.run(["chronyc", "tracking"], capture_output=True, text=True, timeout=5).stdout
    except Exception as e:
        return f"chronyc not available ({e})"
    keep = [ln for ln in out.splitlines() if ln.split(":")[0].strip() in ("Reference ID", "System time", "Leap status")]
    return "; ".join(x.strip() for x in keep) or out.strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--fnet", action="store_true", help="also fetch the public FNET gauge image to compare by eye")
    a = ap.parse_args(argv)
    print("clock:", chrony())
    st, t, f = stats(a.csv)
    print("numbers:", st)
    ok = True
    if st["rows"] < 10:
        print("FAIL: almost no data. Check the optocoupler wiring and that the Pico prints F lines (screen /dev/ttyACM0).")
        return 1
    if st.get("flat"):
        print("FAIL: the frequency never changes. The counter is not seeing mains pulses."); ok = False
    if abs(st["mean_hz"] - 60) > 0.03:
        print("WARN: mean is more than 30 mHz from 60 Hz. Check the GPS PPS (clock calibration) and the CAL/NOPPS flags."); ok = False
    if not (3 <= st["std_mhz"] <= 40):
        print("WARN: unusual spread for the Western grid (expect about 10-25 mHz over a day)."); ok = False
    if st.get("step_std_mhz") and st["step_std_mhz"] > 6:
        print("WARN: second-to-second steps are noisy (> 6 mHz). Look for a bouncing input (GLITCH flags)."); ok = False
    mp = minute_pattern(t, f)
    if mp:
        print("minute pattern: lowest at second", mp["lowest_second"], "of the minute, depth", mp["depth_mhz"], "mHz")
        if not (mp["lowest_second"] <= 20 or mp["lowest_second"] >= 55):
            print("WARN: the start-of-minute dip is not near second 0; timestamps may be offset (or too little data).")
    else:
        print("minute pattern: needs at least 3 hours of data")
    if a.fnet:
        import urllib.request
        last = f"{t[-1]} -> {f[-1]:.4f} Hz"
        try:
            req = urllib.request.Request(FNET_GAUGE, headers={"User-Agent": "gridfreq-selftest"})
            html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
            open("/tmp/fnet_gauge.html", "wb").write(html.encode())
            print(f"FNET page saved to /tmp/fnet_gauge.html (open it in a browser; compare the WECC value with your latest reading {last})")
        except Exception as e:
            print("could not fetch the FNET page:", e)
    print("RESULT:", "looks good" if ok else "check the warnings above")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
