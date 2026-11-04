#!/usr/bin/env python3
"""Convert grid-frequency logs to the Provenance reference CSV (time_utc,frequency_hz,...).

Inputs it understands:
  * this project's daily CSVs (gridfreq_YYYY-MM-DD.csv or .csv.gz): re-checked and merged
  * jp3141/60Hz logs ('YYYY-mm-dd HH:MM:SS.fff, Ticks, Cycles, Frequency, ...'), local clock time:
    pass --tz-hours (Pigott's Phoenix log is -7, MST)
  * raw Pico lines saved with a timestamp prefix: '<unix_seconds> F,n,cycles,clk,freq,ppm,flags'
Rows outside 59.5..60.5 Hz, or with flags NOPPS (unless --keep-nopps), are dropped.

  python3 convert_csv.py ~/gridfreq/gridfreq_2026-11-0*.csv* -o west_home_nov.csv
  python3 convert_csv.py 60Hz.log.gz --tz-hours -7 -o pigott.csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import re
import sys

JP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?),\s*\d+,\s*(\d+),\s*([0-9.]+),")
PICO = re.compile(r"^(\d+(?:\.\d+)?)\s+F,\d+,(\d+),\d+,([0-9.]+),[-0-9.]+,(\S+)")


def _open(p):
    return gzip.open(p, "rt", errors="replace") if p.endswith(".gz") else open(p, errors="replace")


def rows(path, tz_hours=0.0, keep_nopps=False):
    """Yield (unix_second, frequency_hz, cycles, flags, clock_sync)."""
    with _open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or ln.startswith("#") or ln.startswith("time"):
                continue
            if ln[:4].isdigit() and "T" in ln[:11] and ln[10] == "T":         # our own CSV
                p = ln.split(",")
                t = dt.datetime.fromisoformat(p[0].replace("Z", "+00:00")).timestamp()
                f = float(p[1]) if p[1] else float("nan")
                flags = p[3] if len(p) > 3 else "OK"
                yield int(t), f, int(p[2]) if len(p) > 2 and p[2] else 0, flags, p[4] if len(p) > 4 else ""
                continue
            m = JP.match(ln)
            if m:
                t = dt.datetime.fromisoformat(m.group(1)).replace(tzinfo=dt.timezone.utc).timestamp() - tz_hours * 3600
                f, cyc = float(m.group(3)), int(m.group(2))
                span = cyc / f if f > 0 else 1.0           # the row covers the cycles counted since the last request
                yield int(round(t - span)), f, cyc, "OK", "local-clock"
                continue
            m = PICO.match(ln)
            if m:
                yield int(round(float(m.group(1)))) - 1, float(m.group(3)), int(m.group(2)), m.group(4), ""


def convert(paths, out, tz_hours=0.0, keep_nopps=False):
    seen = {}
    for p in paths:
        for t, f, cyc, flags, sync in rows(p, tz_hours, keep_nopps):
            if not (59.5 < f < 60.5):
                continue
            if "NOPPS" in flags and not keep_nopps:
                continue
            seen[t] = (f, cyc, flags, sync)
    with open(out, "w") as fh:
        fh.write("time_utc,frequency_hz,cycles,flags,clock_sync\n")
        for t in sorted(seen):
            f, cyc, flags, sync = seen[t]
            fh.write(f"{dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},{f:.6f},{cyc},{flags},{sync}\n")
    return len(seen)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--tz-hours", type=float, default=0.0, help="UTC offset of local-clock logs (Phoenix: -7)")
    ap.add_argument("--keep-nopps", action="store_true")
    a = ap.parse_args(argv)
    n = convert(a.inputs, a.out, a.tz_hours, a.keep_nopps)
    print(f"wrote {n} rows to {a.out}")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
