"""Convert a readsb / adsb.lol globe_history day archive into Provenance's ADS-B CSV.

adsb.lol publishes each day as an open-data (ODbL) GitHub release, split into
tar parts. Stream them through this script without unpacking to disk:

    cat v2026.09.08-planes-readsb-prod-0.tar.* | \
        python -m provenance_fx.readsb_hist --bbox 40.3,41.4,-74.5,-72.8 --out adsb_box.csv

Each traces/xx/trace_full_<icao>.json is gzip JSON with a base `timestamp`, the
aircraft type `t`, and rows [dt, lat, lon, alt_baro_ft|"ground", gs, track, flags,
vrate, details, source, alt_geom_ft, ...]. Geometric altitude is used when present,
otherwise barometric. Ground rows are dropped.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import tarfile

FT = 0.3048


def convert(stream, bbox, out_path, t_range=None, log=print):
    la0, la1, lo0, lo1 = bbox
    n_files = n_ac = n_rows = 0
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "icao24", "callsign", "typecode", "lat", "lon", "alt_m"])
        with tarfile.open(fileobj=stream, mode="r|") as tf:
            for m in tf:
                if not (m.isfile() and "/traces/" in m.name and m.name.endswith(".json")):
                    continue
                n_files += 1
                raw = tf.extractfile(m).read()
                try:
                    d = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
                except Exception:
                    continue
                base = float(d.get("timestamp", 0))
                icao = str(d.get("icao", "")).lower()
                typ = d.get("t") or ""
                rows = []
                cs = ""
                for r in d.get("trace", []):
                    lat, lon = r[1], r[2]
                    if lat is None or lon is None or not (la0 <= lat <= la1 and lo0 <= lon <= lo1):
                        continue
                    alt = r[10] if len(r) > 10 and isinstance(r[10], (int, float)) else r[3]
                    if not isinstance(alt, (int, float)):
                        continue
                    t = base + float(r[0])
                    if t_range and not (t_range[0] <= t <= t_range[1]):
                        continue
                    if isinstance(r[8], dict) and r[8].get("flight"):
                        cs = r[8]["flight"].strip()
                    rows.append((t, lat, lon, alt * FT))
                if rows:
                    n_ac += 1
                    for t, lat, lon, alt in rows:
                        w.writerow([f"{t:.2f}", icao, cs, typ, f"{lat:.6f}", f"{lon:.6f}", f"{alt:.1f}"])
                    n_rows += len(rows)
                if n_files % 10000 == 0:
                    log(f"  {n_files} trace files read, {n_ac} aircraft in box")
    log(f"done: {n_files} trace files, {n_ac} aircraft in box, {n_rows} rows -> {out_path}")
    return n_ac, n_rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bbox", required=True, help="lat_min,lat_max,lon_min,lon_max")
    ap.add_argument("--out", required=True)
    ap.add_argument("--archive", help="tar file (default: read the tar stream from stdin)")
    a = ap.parse_args(argv)
    bbox = [float(v) for v in a.bbox.split(",")]
    src = open(a.archive, "rb") if a.archive else sys.stdin.buffer
    convert(src, bbox, a.out)


if __name__ == "__main__":
    main()
