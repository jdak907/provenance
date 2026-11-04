"""ADS-B flight track loading, cleaning and smooth interpolation.

Supported inputs
- A simple CSV (the format the simulator writes, and close to OpenSky state vectors):
  time, icao24, callsign, typecode, lat, lon, and one of alt_m / geoaltitude / baroaltitude
  (metres) or alt_ft / altitude (feet). time may be Unix seconds or ISO 8601.
- SBS-1 / BaseStation lines (dump1090 or readsb port 30003). Good for a home RTL-SDR receiver.
"""
from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import CubicSpline, make_smoothing_spline

from .geo import LocalFrame

FT = 0.3048

# ICAO type designators that are jets. The video filtered OUT known jets rather than
# filtering IN known props, because type tables have gaps. We do the same.
# This list is deliberately partial; extend it with --jet-types FILE. [VERIFY completeness]
JET_TYPES = set(
    """
A318 A319 A320 A321 A19N A20N A21N A332 A333 A338 A339 A342 A343 A345 A346 A359 A35K A388 BCS1 BCS3
B712 B717 B721 B722 B732 B733 B734 B735 B736 B737 B738 B739 B37M B38M B39M B3XM B752 B753 B762 B763 B764
B772 B773 B77L B77W B778 B779 B788 B789 B78X B744 B748 B74S MD11 MD80 MD81 MD82 MD83 MD87 MD88 MD90 DC10
E135 E145 E170 E175 E190 E195 E290 E295 E35L E45X E50P E55P E545 E550 CRJ1 CRJ2 CRJ7 CRJ9 CRJX
C25A C25B C25C C25M C500 C501 C510 C525 C550 C551 C560 C56X C650 C680 C68A C700 C750 F2TH F900 FA10 FA20
FA50 FA7X FA8X GLF2 GLF3 GLF4 GLF5 GLF6 G150 G200 G280 GL5T GL7T GLEX H25A H25B H25C HA4T HDJT LJ23 LJ24
LJ25 LJ31 LJ35 LJ40 LJ45 LJ55 LJ60 LJ70 LJ75 CL30 CL35 CL60 PC24 PRM1 SF50 EA50 BE40 C17 C5M KC10 K35R
E75L E75S GA5C GA6C GA7C GA8C GL6T FA6X C25 B748 B744 A35K A124 A306 A30B A310 MD11 B762 E135 E145
""".split()
)


@dataclass
class Track:
    """One aircraft's ADS-B samples. Times are Unix seconds (UTC)."""

    flight_id: str
    icao24: str
    callsign: str
    typecode: str
    t: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    alt_m: np.ndarray  # metres above mean sea level

    @property
    def is_known_jet(self) -> bool:
        return self.typecode.upper() in JET_TYPES


class TrackModel:
    """Smooth position and velocity of one track in a local frame.

    Uses a penalised smoothing spline per axis, so velocity (the derivative)
    is not dominated by ADS-B position quantisation noise.
    """

    # Smoothing strength. 100 matched cross-validation on 1 s ADS-B with ~4 m noise.
    # Pass lam=None to let the spline pick it per track (slower, about 0.2 s per track).
    LAM = 100.0

    def __init__(self, track: Track, frame: LocalFrame, smooth: bool = True, lam="default"):
        lam = self.LAM if lam == "default" else lam
        self.track = track
        x, y = frame.to_xy(track.lat, track.lon)
        z = track.alt_m.astype(float)
        t = track.t.astype(float)
        self.t0, self.t1 = float(t[0]), float(t[-1])
        self._splines = []
        for arr in (x, y, z):
            if smooth and len(t) >= 6:
                try:
                    s = make_smoothing_spline(t, arr, lam=lam)
                except Exception:
                    s = CubicSpline(t, arr)
            else:
                s = CubicSpline(t, arr) if len(t) >= 2 else None
            self._splines.append(s)
        self._d = [s.derivative() for s in self._splines]

    def pos(self, t):
        t = np.asarray(t, dtype=float)
        out = np.stack([s(t) for s in self._splines], axis=-1)
        bad = (t < self.t0) | (t > self.t1)
        if np.any(bad):
            out[bad] = np.nan
        return out

    def vel(self, t):
        t = np.asarray(t, dtype=float)
        out = np.stack([d(t) for d in self._d], axis=-1)
        bad = (t < self.t0) | (t > self.t1)
        if np.any(bad):
            out[bad] = np.nan
        return out


def _parse_time(s: str) -> float:
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        pass
    s = s.replace("Z", "+00:00")
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.timestamp()


def _split_gaps(rows, max_gap_s: float, min_points: int = 6):
    """rows: list of (t, lat, lon, alt). Split into segments at gaps."""
    rows.sort(key=lambda r: r[0])
    segs, cur = [], []
    for r in rows:
        if cur and r[0] - cur[-1][0] > max_gap_s:
            segs.append(cur)
            cur = []
        if cur and r[0] <= cur[-1][0]:
            continue  # duplicate time stamp
        cur.append(r)
    if cur:
        segs.append(cur)
    return [s for s in segs if len(s) >= min_points]


def _build_tracks(per_aircraft: dict, meta: dict, max_gap_s: float) -> list[Track]:
    tracks = []
    for icao, rows in per_aircraft.items():
        callsign, typecode = meta.get(icao, ("", ""))
        for k, seg in enumerate(_split_gaps(rows, max_gap_s)):
            a = np.array(seg, dtype=float)
            tracks.append(
                Track(f"{icao}-{k}", icao, callsign, typecode, a[:, 0], a[:, 1], a[:, 2], a[:, 3])
            )
    return tracks


def load_csv(path: str, max_gap_s: float = 60.0) -> list[Track]:
    per, meta = {}, {}
    with open(path, newline="") as fh:
        rd = csv.DictReader(fh)
        cols = {c.lower(): c for c in rd.fieldnames or []}

        def col(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        c_t = col("time", "timestamp", "t")
        c_id = col("icao24", "hex", "icao", "id")
        c_cs = col("callsign", "flight")
        c_ty = col("typecode", "type", "aircraft_type")
        c_lat, c_lon = col("lat", "latitude"), col("lon", "longitude", "lng")
        c_am = col("alt_m", "geoaltitude", "baroaltitude")
        c_af = col("alt_ft", "altitude", "alt_baro")
        if not all([c_t, c_id, c_lat, c_lon]) or not (c_am or c_af):
            raise ValueError(f"{path}: need time, icao24, lat, lon and an altitude column")
        for r in rd:
            try:
                lat, lon = float(r[c_lat]), float(r[c_lon])
                alt = float(r[c_am]) if c_am and r[c_am] not in ("", None) else float(r[c_af]) * FT
                t = _parse_time(r[c_t])
            except (TypeError, ValueError):
                continue
            icao = r[c_id].strip().lower()
            per.setdefault(icao, []).append((t, lat, lon, alt))
            cs = (r.get(c_cs) or "").strip() if c_cs else ""
            ty = (r.get(c_ty) or "").strip() if c_ty else ""
            old = meta.get(icao, ("", ""))
            meta[icao] = (cs or old[0], ty or old[1])
    return _build_tracks(per, meta, max_gap_s)


def load_sbs(path: str, types_csv: str | None = None, max_gap_s: float = 60.0,
             utc_offset_hours: float = 0.0) -> list[Track]:
    """Parse SBS-1 BaseStation MSG lines (from dump1090/readsb port 30003).

    Altitude in SBS is barometric (pressure altitude, feet), not geometric height,
    so expect tens of metres of vertical error. [VERIFY] the time zone your
    decoder writes; pass utc_offset_hours if it logs local time.
    """
    types = {}
    if types_csv:
        with open(types_csv, newline="") as fh:
            for r in csv.DictReader(fh):
                types[r["icao24"].strip().lower()] = r["typecode"].strip()
    per, callsigns = {}, {}
    with open(path) as fh:
        for line in fh:
            f = line.strip().split(",")
            if len(f) < 16 or f[0] != "MSG":
                continue
            icao = f[4].strip().lower()
            if f[10].strip():
                callsigns[icao] = f[10].strip()
            if f[1] != "3" or not f[14] or not f[15] or not f[11]:
                continue
            try:
                d = dt.datetime.strptime(f"{f[6]} {f[7]}", "%Y/%m/%d %H:%M:%S.%f")
            except ValueError:
                continue
            t = d.replace(tzinfo=dt.timezone.utc).timestamp() - utc_offset_hours * 3600
            per.setdefault(icao, []).append((t, float(f[14]), float(f[15]), float(f[11]) * FT))
    meta = {k: (callsigns.get(k, ""), types.get(k, "")) for k in per}
    return _build_tracks(per, meta, max_gap_s)


def load_tracks(path: str, max_gap_s: float = 60.0, **kw) -> list[Track]:
    if path.endswith((".sbs", ".txt", ".log")):
        return load_sbs(path, max_gap_s=max_gap_s, **kw)
    return load_csv(path, max_gap_s=max_gap_s)


def write_csv(path: str, tracks: list[Track]):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "icao24", "callsign", "typecode", "lat", "lon", "alt_m"])
        for tr in tracks:
            for i in range(len(tr.t)):
                w.writerow([f"{tr.t[i]:.2f}", tr.icao24, tr.callsign, tr.typecode,
                            f"{tr.lat[i]:.6f}", f"{tr.lon[i]:.6f}", f"{tr.alt_m[i]:.1f}"])
