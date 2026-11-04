#!/usr/bin/env python3
"""Make Provenance use your home logs as the 'US West (home)' reference.

Reads daily CSVs (or a converted CSV) and writes one NPZ per UTC day into Provenance's cache
(~/.cache/provenance/enf/us/home/, or $PROVENANCE_HOME_LOGS). Provenance's grid race then includes them in
the US-WEST log, and 'Built-in grid log: US West' can search them. Only rows whose clock was locked
to GPS PPS are used unless you pass --allow-ntp (NTP-only time is ~10 ms, fine for ENF, but flagged).

  python3 import_to_provenance.py ~/gridfreq/gridfreq_*.csv*
  python3 import_to_provenance.py --from-dir ~/uploads/gridfreq   # after a sync
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_csv import rows  # noqa: E402

DEFAULT = os.environ.get("PROVENANCE_HOME_LOGS", os.path.expanduser("~/.cache/provenance/enf/us/home"))


def import_logs(paths, out_dir=DEFAULT, allow_ntp=False):
    days = {}
    skipped = 0
    for p in paths:
        for t, f, cyc, flags, sync in rows(p):
            if not (59.5 < f < 60.5) or "NOPPS" in flags:
                skipped += 1
                continue
            if sync not in ("pps", "") and not (allow_ntp and sync == "ntp"):
                skipped += 1
                continue
            days.setdefault(t // 86400, {})[t] = f
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for d, vals in sorted(days.items()):
        t0 = d * 86400
        f = np.full(86400, np.nan, np.float32)
        for t, v in vals.items():
            f[t - t0] = v
        p = os.path.join(out_dir, f"home_{np.datetime64(int(t0), 's').astype('datetime64[D]')}.npz")
        if os.path.exists(p):                      # merge with what was imported before
            old = np.load(p)["f"]
            f = np.where(np.isfinite(f), f, old)
        np.savez_compressed(p, t0=float(t0), step=1.0, f=f, source="US West (home)")
        written.append((p, int(np.isfinite(f).sum())))
    return written, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*")
    ap.add_argument("--from-dir")
    ap.add_argument("--out-dir", default=DEFAULT)
    ap.add_argument("--allow-ntp", action="store_true")
    a = ap.parse_args(argv)
    paths = list(a.inputs)
    if a.from_dir:
        paths += sorted(glob.glob(os.path.join(a.from_dir, "gridfreq_*.csv*")))
    if not paths:
        ap.error("no input files")
    written, skipped = import_logs(paths, a.out_dir, a.allow_ntp)
    for p, n in written:
        print(f"{p}: {n} s ({n / 864:.1f} % of the day)")
    print(f"{len(written)} day file(s); {skipped} rows skipped (out of range, no PPS, or clock not locked)")
    print("Restart Provenance (or the GUI) to pick up new days. They appear as 'US West (home)' in the coverage table.")


if __name__ == "__main__":
    main()
