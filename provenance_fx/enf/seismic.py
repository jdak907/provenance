"""Seismic grid-frequency reference: public seismometers that pick up 60 Hz mains hum.

Many seismic stations record a faint 60 Hz line from their own power supply. The stations are
GPS-timed and the networks publish the data openly, so several stations that agree with one another
give a second-by-second record of grid frequency. This module:

  * fetches waveforms from public FDSN dataselect services over HTTPS (archive), or takes records
    from the live SeedLink collector (provenance_fx/enf/seismic_live.py),
  * extracts the hum line at 1 s (8 s Hann frame, 1 s hop, complex demodulation + zoom FFT,
    parabolic peak), converts aliases and harmonics to grid Hz, drops seconds under 6 dB SNR,
  * verifies every station against the leave-one-out median of the others in 10-minute windows
    (live_enf_aggregator_design.md: trusted at r >= 0.75 within 2 s of its learned lag for 3 windows
    in a row; suspect under 0.5; dropped after 30 minutes suspect),
  * takes a weighted median of trusted stations per second, rejecting anything more than 15 mHz
    from the median, and stores n_sources and the spread,
  * writes one file per grid per UTC day: <SEISMIC_DIR>/<GRID>/YYYY-MM-DD.csv.gz with columns
    time_utc,f_hz,n_sources,spread_mhz,quality  (Provenance's CSV reader and us_refs both load it).

Data: EarthScope (formerly IRIS DMC) FDSN web services, networks PB, UW, NN, MB, UI, UO, TX, NX.
Cite the network DOIs listed in NETWORK_DOIS. From 2026-12-15 EarthScope's dataselect requires a free
account for archive downloads [VERIFY]; this code never signs in. Raspberry Shake (AM) is excluded
on purpose: its licence forbids redistributing the data.
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import os
import time
import urllib.error
import urllib.request
import warnings

import numpy as np
from scipy.signal import resample_poly

from . import mseed
from . import reference as R

SEISMIC_DIR = os.environ.get("PROVENANCE_SEISMIC_DIR", os.path.join(R.CACHE, "us", "seismic"))
TRACK_CACHE = os.path.join(R.CACHE, "seismic_tracks")
FDSN = {"default": "https://service.earthscope.org", "CI": "https://service.scedc.caltech.edu",
        "BK": "https://service.ncedc.org", "NC": "https://service.ncedc.org"}
UA = {"User-Agent": "provenance-enf-seismic/0.1 (grid frequency research; contact via project README)"}
EXCLUDED_NETWORKS = {"AM"}   # Raspberry Shake: licence forbids redistribution; real-time is paid

NETWORK_DOIS = {
    "PB": "Plate Boundary Observatory Borehole Seismic Network (EarthScope), no DOI listed [VERIFY]",
    "UW": "10.7914/SN/UW (Pacific Northwest Seismic Network, Univ. of Washington)",
    "NN": "10.7914/SN/NN (Nevada Seismological Laboratory)",
    "MB": "10.7914/SN/MB (Montana Regional Seismic Network)",
    "UI": "University of Idaho network, DOI [VERIFY]",
    "UO": "10.7914/SN/UO (University of Oregon)",
    "TX": "10.7914/SN/TX (Texas Seismological Network, TexNet)",
    "NX": "Nanometrics research network, DOI [VERIFY]",
}

# The stations that carried a usable hum line in the 2024 and 2026-11-03 tests (live_enf_sources.md).
# grid comes from the station's location (assign_grid) and is re-checked by the agreement gate.
STATIONS = [
    # sid,               lat,       lon,        harmonic, note
    ("PB.B082..HHZ", 33.598183, -116.596008, 1, "Anza area borehole; no data on 2026-11-03"),
    ("PB.B084..HHZ", 33.611568, -116.456367, 1, "Anza area borehole"),
    ("PB.B086..HHZ", 33.5575, -116.531, 1, "Anza area borehole"),
    ("PB.B088..HHZ", 33.37495, -116.62052, 1, "Anza area borehole; live 2026-11-03"),
    ("MB.YBMT.01.EHZ", 47.86333, -114.0115, 1, "NW Montana"),
    ("UI.MGOO.01.HHZ", 47.649085, -117.149717, 1, "Spokane area"),
    ("UW.WRMB..HNZ", 48.1749, -122.35219, 1, "NW Washington"),
    ("UW.HOMA..HNZ", 47.35767, -122.03033, 1, "Seattle area"),
    ("UW.MKAH..HNZ", 48.3707, -124.5891, 1, "Neah Bay WA; live 2026-11-03"),
    ("NN.HYDE..HNZ", 36.1609, -115.1931, 1, "Las Vegas NV; live 2026-11-03"),
    ("UW.OZET..HNZ", 48.15762, -124.66909, 1, "Olympic coast WA, weaker"),
    ("UO.DAYS..HNZ", 42.97009, -123.16634, 1, "SW Oregon, weaker"),
    ("MB.OVMT.01.EHZ", 47.06433, -112.9967, 1, "W Montana, weaker"),
    ("TX.PB46.00.HHZ", 31.706947, -103.475133, 1, "Permian Basin TX (ERCOT)"),
    ("TX.PB23.00.HHZ", 31.66404, -104.07276, 2, "Pecos TX (ERCOT), 120 Hz line"),
    ("TX.PB47.00.HHZ", 31.741433, -103.3351, 3, "Permian Basin TX (ERCOT), 180 Hz line"),
]

# Rough interconnection outlines (lon, lat). Coarse on purpose: the agreement gate catches mistakes.
_POLY = {
    "US-TEXAS": [(-106.6, 31.8), (-103.0, 32.0), (-103.0, 36.5), (-100.0, 36.5), (-100.0, 34.6), (-94.0, 33.6),
                 (-93.6, 31.0), (-93.8, 29.7), (-97.1, 25.9), (-99.5, 27.5), (-101.4, 29.8), (-104.5, 29.6)],
    "QUEBEC": [(-79.5, 45.0), (-74.5, 45.0), (-71.0, 45.0), (-64.0, 48.0), (-57.0, 51.5), (-64.0, 60.0),
               (-79.5, 62.5)],
}
_WEST_LON = -104.5   # west of this (and outside Texas) is the Western Interconnection, roughly [VERIFY]


def _inside(lon, lat, poly):
    n, c = len(poly), False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1 + 1e-12) + x1:
            c = not c
    return c


def assign_grid(lat, lon):
    if _inside(lon, lat, _POLY["US-TEXAS"]):
        return "US-TEXAS"
    if _inside(lon, lat, _POLY["QUEBEC"]):
        return "QUEBEC"
    return "US-WEST" if lon < _WEST_LON else "US-EAST"


def stations_for(grid):
    return [s for s in STATIONS if assign_grid(s[1], s[2]) == grid and s[0].split(".")[0] not in EXCLUDED_NETWORKS]


def harmonic_of(sid):
    for s in STATIONS:
        if s[0] == sid:
            return s[3]
    return 1


# ---------------------------------------------------------------- fetch (archive)

def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def fetch_fdsn(sid, t0, t1, timeout=180, retries=3, log=None):
    """Raw miniSEED bytes from the public FDSN dataselect service (HTTPS), or b'' if no data."""
    net, sta, loc, cha = sid.split(".")
    if net in EXCLUDED_NETWORKS:
        raise ValueError(f"{net} is excluded (licence)")
    base = FDSN.get(net, FDSN["default"])
    url = (f"{base}/fdsnws/dataselect/1/query?net={net}&sta={sta}&loc={loc or '--'}&cha={cha}"
           f"&start={_iso(t0)}&end={_iso(t1)}&nodata=404")
    for k in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (204, 404):
                return b""
            if e.code in (401, 403):
                raise RuntimeError(f"{sid}: archive needs an account now (HTTP {e.code}); not signing in")
            err = e
        except Exception as e:  # timeouts, resets
            err = e
        time.sleep(5 * (k + 1))
    if log:
        log(f"{sid}: fetch failed {err}")
    return b""


# ---------------------------------------------------------------- extraction

FRAME_S = 8.0
DEC_FS = 10.0          # complex baseband rate after demodulation
PAD = 8
MIN_SNR_DB = 6.0


def alias_of(fs, harmonic, nominal=60):
    """Where harmonic k of the mains appears at sample rate fs: (centre Hz, sign)."""
    f = (harmonic * nominal) % fs
    s = 1
    if f > fs / 2:
        f, s = fs - f, -1
    return f, s


def track_segment(seg, harmonic=1, nominal=60, half=None):
    """Per-second hum frequency of one contiguous waveform segment.
    Returns (t_int, f_grid_hz, snr_db): t_int are integer UTC seconds at the frame centres."""
    fs = seg.fs
    fc, sign = alias_of(fs, harmonic, nominal)
    half = half or 0.12 * harmonic
    if len(seg.data) < (FRAME_S + 2) * fs or fc < 1 or fc > fs / 2 - 1:
        return np.zeros(0, int), np.zeros(0), np.zeros(0)
    x = seg.data - np.mean(seg.data)
    n = np.arange(len(x))
    z = x * np.exp(-2j * np.pi * fc * n / fs)
    q = fs / DEC_FS
    if abs(q - round(q)) > 1e-6:
        from fractions import Fraction
        fr = Fraction(DEC_FS / fs).limit_denominator(200)   # e.g. a 997.8 Hz fitted audio rate
        up, down = max(1, fr.numerator), max(1, fr.denominator)
    else:
        up, down = 1, int(round(q))
    zd = resample_poly(z, up, down)
    fsd = fs * up / down
    nf = int(round(FRAME_S * fsd))
    nfft = nf * PAD
    t_first = int(np.ceil(seg.start + FRAME_S / 2))
    t_last = int(np.floor(seg.start + (len(zd) - nf) / fsd + FRAME_S / 2))
    if t_last < t_first:
        return np.zeros(0, int), np.zeros(0), np.zeros(0)
    T = np.arange(t_first, t_last + 1)
    k0 = np.round((T - FRAME_S / 2 - seg.start) * fsd).astype(int)
    k0 = k0[(k0 >= 0) & (k0 + nf <= len(zd))]
    T = T[:len(k0)]
    win = np.hanning(nf)
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fsd))
    band = np.where(np.abs(freqs) <= half)[0]
    wide = np.abs(freqs) <= min(3.0, fsd / 2 * 0.9)
    df = freqs[1] - freqs[0]
    F = np.empty(len(T))
    S = np.empty(len(T))
    for a in range(0, len(T), 2048):
        idx = k0[a:a + 2048, None] + np.arange(nf)[None, :]
        P = np.abs(np.fft.fftshift(np.fft.fft(zd[idx] * win, nfft, axis=1), axes=1)) ** 2
        Pb = P[:, band]
        j = np.argmax(Pb, axis=1)
        jj = band[j]
        lo = np.log(P[np.arange(len(jj)), np.clip(jj - 1, 0, nfft - 1)] + 1e-30)
        mid = np.log(P[np.arange(len(jj)), jj] + 1e-30)
        hi = np.log(P[np.arange(len(jj)), np.clip(jj + 1, 0, nfft - 1)] + 1e-30)
        den = lo - 2 * mid + hi
        d = np.where(np.abs(den) > 1e-12, 0.5 * (lo - hi) / np.where(np.abs(den) > 1e-12, den, 1), 0.0)
        d = np.clip(d, -0.5, 0.5)
        F[a:a + len(jj)] = freqs[jj] + d * df
        S[a:a + len(jj)] = 10 * np.log10(P[np.arange(len(jj)), jj] / (np.median(P[:, wide], axis=1) + 1e-30) + 1e-30)
    f_grid = nominal + sign * F / harmonic
    return T.astype(np.int64), f_grid, S


def tracks_on_grid(segs, t0, n, harmonic=1, nominal=60, min_snr=MIN_SNR_DB):
    """Put the per-second tracks of several segments of one station onto a 1 s grid [t0, t0+n)."""
    f = np.full(n, np.nan)
    snr = np.full(n, np.nan)
    for s in segs:
        T, F, S = track_segment(s, harmonic, nominal)
        i = T - int(t0)
        m = (i >= 0) & (i < n)
        f[i[m]] = F[m]
        snr[i[m]] = S[m]
    f[~(snr >= min_snr)] = np.nan
    f[np.abs(f - nominal) > 0.5] = np.nan
    return f, snr


def station_day(sid, day, lead_s=1800, chunk_s=3 * 3600, log=None, use_cache=True):
    """1 s hum track of one station for UTC `day` (date), with `lead_s` extra on both sides.
    Cached as NPZ (frequency and SNR only; waveforms are not kept)."""
    os.makedirs(TRACK_CACHE, exist_ok=True)
    p = os.path.join(TRACK_CACHE, f"{sid}_{day.isoformat()}_{lead_s}.npz")
    t0 = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp()) - lead_s
    n = 86400 + 2 * lead_s
    # a cache written before the day (plus lead and an hour of archive latency) was over is partial: refetch
    if use_cache and os.path.exists(p) and os.path.getmtime(p) > t0 + n + 3600:
        z = np.load(p)
        return int(z["t0"]), z["f"].astype(float), z["snr"].astype(float)
    f = np.full(n, np.nan)
    snr = np.full(n, np.nan)
    h = harmonic_of(sid)
    for a in range(t0, t0 + n, chunk_s):
        b = min(a + chunk_s, t0 + n)
        raw = fetch_fdsn(sid, a - 10, b + 10, log=log)   # 10 s overlap so frames at the edges are complete
        if not raw:
            continue
        segs = mseed.read_segments(raw)
        ff, ss = tracks_on_grid(segs, a, b - a, h)
        f[a - t0:b - t0] = ff
        snr[a - t0:b - t0] = ss
    np.savez_compressed(p, t0=t0, f=f.astype(np.float32), snr=snr.astype(np.float32))
    return t0, f, snr


# ---------------------------------------------------------------- verification and consensus

WINDOW_S = 600
R_TRUST = 0.75
R_SUSPECT = 0.50
LAG_TOL_S = 2
MAX_LAG_S = 5
TRUST_WINDOWS = 3
DROP_AFTER_WINDOWS = 3        # 30 minutes suspect
RECHECK_WINDOWS = 6           # a dropped source is re-tested once an hour
OUTLIER_HZ = 0.015
MIN_VALID = 0.5
# The gate correlates lightly smoothed tracks (5 s moving mean). Each station's own tracking noise is
# white from second to second while the grid's wander is shared, so smoothing lifts r for real matches
# (0.6-0.8 raw -> 0.9+ in the 2026-11-03 live test) without helping look-alike lines, which do not
# follow the grid at any time scale. Output values are never smoothed.
GATE_SMOOTH_S = 5
# Seismic frame centres vs the Zenodo 2024 time labels: learned on the tuning days (scripts/
# enf_seismic_validate.py, 2024-03-05 and 2024-03-12) and applied to every output second.
LABEL_SHIFT_S = 1


def _shift(x, L):
    """y[t] = x[t + L] (NaN-padded)."""
    y = np.full_like(x, np.nan)
    if L > 0:
        y[:-L] = x[L:]
    elif L < 0:
        y[-L:] = x[:L]
    else:
        y[:] = x
    return y


def corr_lag(a, b, max_lag=MAX_LAG_S, min_n=120):
    """Best Pearson r of a(t + L) against b(t), L in [-max_lag, max_lag]. Returns (r, L)."""
    best = (np.nan, 0)
    for L in range(-max_lag, max_lag + 1):
        x = _shift(a, L)
        m = np.isfinite(x) & np.isfinite(b)
        if m.sum() < min_n:
            continue
        xa, xb = x[m] - x[m].mean(), b[m] - b[m].mean()
        den = np.sqrt((xa * xa).sum() * (xb * xb).sum())
        if den <= 0:
            continue
        r = float((xa * xb).sum() / den)
        if not np.isfinite(best[0]) or r > best[0]:
            best = (r, L)
    return best


def smooth(x, n=GATE_SMOOTH_S):
    """NaN-aware centred moving mean (NaN where fewer than half the window is valid)."""
    if n <= 1:
        return x
    from scipy.ndimage import uniform_filter1d
    ok = np.isfinite(x)
    num = uniform_filter1d(np.where(ok, x, 0.0), n, mode="nearest")
    den = uniform_filter1d(ok.astype(float), n, mode="nearest")
    with np.errstate(all="ignore"):
        y = num / den
    y[den < 0.5] = np.nan
    return y


def _wmedian(vals, w):
    """Weighted median along axis 0 ignoring NaN. vals (k, n), w (k,)."""
    k, n = vals.shape
    out = np.full(n, np.nan)
    order = np.argsort(np.where(np.isfinite(vals), vals, np.inf), axis=0)
    sv = np.take_along_axis(vals, order, 0)
    sw = np.where(np.isfinite(sv), w[order], 0.0)
    cw = np.cumsum(sw, 0)
    tot = cw[-1]
    ok = tot > 0
    j = np.argmax(cw >= tot / 2, axis=0)
    out[ok] = sv[j[ok], np.arange(n)[ok]]
    return out


class Gate:
    """Per-source trust state machine (causal: used live, and for the archive with a lead-in)."""

    def __init__(self, ids):
        self.st = {i: dict(state="candidate", good=0, bad=0, since_drop=0, lag=0, lags=[], r=np.nan) for i in ids}

    def add(self, i):
        self.st.setdefault(i, dict(state="candidate", good=0, bad=0, since_drop=0, lag=0, lags=[], r=np.nan))

    def trusted(self):
        return [i for i, s in self.st.items() if s["state"] == "trusted"]

    def evaluate(self, series):
        """series: {id: 1 s array for one window}. Updates states; returns {id: (r, lag)}."""
        ids = [i for i in series if np.isfinite(series[i]).mean() >= MIN_VALID]
        res = {}
        trusted = set(self.trusted())
        for i in ids:
            s = self.st[i]
            if s["state"] == "dropped":
                s["since_drop"] += 1
                if s["since_drop"] < RECHECK_WINDOWS:
                    continue
            others = [j for j in ids if j != i and j in trusted]
            if len(others) < 2:
                others = [j for j in ids if j != i]
            if not others:
                continue
            M = np.vstack([_shift(series[j], self.st[j]["lag"]) for j in others])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                loo = np.nanmedian(M, axis=0) if len(others) > 1 else M[0]
            r, L = corr_lag(smooth(series[i]), smooth(loo))
            res[i] = (r, L)
        for i, (r, L) in res.items():
            s = self.st[i]
            s["r"] = r
            good = np.isfinite(r) and r >= R_TRUST and abs(L - s["lag"]) <= LAG_TOL_S
            bad = (not np.isfinite(r)) or r < R_SUSPECT
            if good:
                s["good"] += 1
                s["bad"] = 0
                s["lags"] = (s["lags"] + [L])[-12:]
                s["lag"] = int(np.median(s["lags"]))
                if s["state"] in ("candidate", "suspect", "dropped") and s["good"] >= TRUST_WINDOWS:
                    s["state"] = "trusted"
                elif s["state"] == "dropped":
                    s["state"] = "candidate"
                s["since_drop"] = 0
            else:
                s["good"] = 0
                if bad:
                    s["bad"] += 1
                    if s["state"] == "trusted":
                        s["state"] = "suspect"
                    if s["bad"] >= DROP_AFTER_WINDOWS:
                        s["state"] = "dropped"
                        s["since_drop"] = 0
                elif s["state"] == "trusted":
                    s["state"] = "suspect"
        return res


def consensus_window(series, use, weights, lags):
    """Weighted median per second of the `use` sources. Returns f, n, spread_mhz."""
    n = len(next(iter(series.values())))
    if not use:
        return np.full(n, np.nan), np.zeros(n, int), np.full(n, np.nan)
    V = np.vstack([_shift(series[i], lags[i]) for i in use])
    w = np.array([max(weights[i], 0.05) ** 2 for i in use])
    med = _wmedian(V, w)
    V2 = np.where(np.abs(V - med) <= OUTLIER_HZ, V, np.nan)
    med2 = _wmedian(V2, w)
    cnt = np.isfinite(V2).sum(0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        spread = np.nanmedian(np.abs(V2 - med2), axis=0) * 1000
    med2[cnt == 0] = np.nan
    return med2, cnt, spread


def build_consensus(tracks, t0, n, causal=False, lead_windows=0, log=None):
    """tracks: {id: 1 s array starting at t0, length n}. Windows of WINDOW_S.
    causal=False (archive): a source counts in a window if it passes there AND sits in a run of at
    least TRUST_WINDOWS passing windows (past or future), the offline equivalent of the live rule.
    Returns dict(f, n_sources, spread_mhz, quality, per_window=[...], states)."""
    ids = list(tracks)
    nw = int(np.ceil(n / WINDOW_S))
    gate = Gate(ids)
    evals = []
    for w in range(nw):
        a, b = w * WINDOW_S, min(n, (w + 1) * WINDOW_S)
        ser = {i: tracks[i][a:b] for i in ids}
        res = gate.evaluate(ser)
        evals.append(dict(w=w, res=res, states={i: gate.st[i]["state"] for i in ids},
                          lags={i: gate.st[i]["lag"] for i in ids}))
    passing = np.zeros((len(ids), nw), bool)
    for w, e in enumerate(evals):
        for k, i in enumerate(ids):
            r, L = e["res"].get(i, (np.nan, 0))
            passing[k, w] = np.isfinite(r) and r >= R_TRUST and abs(L - e["lags"][i]) <= LAG_TOL_S
    usable = np.zeros_like(passing)
    if causal:
        for w, e in enumerate(evals):
            for k, i in enumerate(ids):
                usable[k, w] = e["states"][i] == "trusted"
    else:
        for k in range(len(ids)):
            w = 0
            while w < nw:
                if passing[k, w]:
                    e = w
                    while e < nw and passing[k, e]:
                        e += 1
                    if e - w >= TRUST_WINDOWS:
                        usable[k, w:e] = True
                    w = e
                else:
                    w += 1
    f = np.full(n, np.nan)
    cnt = np.zeros(n, int)
    spread = np.full(n, np.nan)
    for w, e in enumerate(evals):
        a, b = w * WINDOW_S, min(n, (w + 1) * WINDOW_S)
        use = [i for k, i in enumerate(ids) if usable[k, w]]
        weights = {i: e["res"].get(i, (0.5, 0))[0] for i in use}
        ser = {i: tracks[i][a:b] for i in ids}
        fw, cw, sw = consensus_window(ser, use, weights, e["lags"])
        f[a:b], cnt[a:b], spread[a:b] = fw, cw, sw
    q = np.where(cnt >= 3, "good", np.where(cnt == 2, "fair", np.where(cnt == 1, "single", "none")))
    per_window = [dict(w=e["w"], r={i: (None if not np.isfinite(v[0]) else round(v[0], 3)) for i, v in e["res"].items()},
                       lag={i: int(v[1]) for i, v in e["res"].items()},
                       used=[i for k, i in enumerate(ids) if usable[k, e["w"]]]) for e in evals]
    return dict(f=f, n_sources=cnt, spread_mhz=spread, quality=q, per_window=per_window,
                states={i: gate.st[i]["state"] for i in ids}, lags={i: gate.st[i]["lag"] for i in ids})


# ---------------------------------------------------------------- daily files

HEADER = "time_utc,f_hz,n_sources,spread_mhz,quality\n"


def day_path(grid, day, gz=True):
    return os.path.join(SEISMIC_DIR, grid, f"{day.isoformat()}.csv" + (".gz" if gz else ""))


def write_day(grid, day, t0, f, n_src, spread, quality, meta=None):
    """Write the UTC day `day` from arrays starting at t0 (1 s). Only seconds with a value are written."""
    d0 = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp())
    i0 = d0 - int(t0)
    os.makedirs(os.path.join(SEISMIC_DIR, grid), exist_ok=True)
    lines = [HEADER]
    for k in range(86400):
        i = i0 + k
        if 0 <= i < len(f) and np.isfinite(f[i]):
            ts = dt.datetime.fromtimestamp(d0 + k, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            sp = "" if not np.isfinite(spread[i]) else f"{spread[i]:.2f}"
            lines.append(f"{ts},{f[i]:.6f},{int(n_src[i])},{sp},{quality[i]}\n")
    p = day_path(grid, day)
    tmp = p + ".tmp"
    with gzip.open(tmp, "wt") as fh:
        fh.writelines(lines)
    os.replace(tmp, p)
    if meta is not None:
        with open(os.path.join(SEISMIC_DIR, grid, f"{day.isoformat()}.json"), "w") as fh:
            json.dump(meta, fh, indent=1, default=str)
    return p, len(lines) - 1


def read_day_file(path):
    """-> (t0, f array 86400 s, n_sources array). Accepts .csv or .csv.gz in the format above."""
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as fh:
        text = fh.read()
    rows = [ln.split(",") for ln in text.splitlines()[1:] if ln and ln[0].isdigit()]
    name = os.path.basename(path).split(".")[0]
    d0 = int(dt.datetime.fromisoformat(name).replace(tzinfo=dt.timezone.utc).timestamp())
    f = np.full(86400, np.nan)
    n = np.zeros(86400, int)
    if rows:
        ts = np.array([r[0][:19] for r in rows], dtype="datetime64[s]").astype(np.int64) - d0
        v = np.array([float(r[1]) for r in rows])
        c = np.array([int(r[2] or 0) for r in rows])
        m = (ts >= 0) & (ts < 86400)
        f[ts[m]] = v[m]
        n[ts[m]] = c[m]
    return d0, f, n


def day_files(grid):
    """[(YYYY-MM-DD, [paths])]: a finished day is .csv.gz; the live collector's open day is .csv.
    When both exist (archive rebuilt, then live appended) both are read and the live rows win."""
    d = os.path.join(SEISMIC_DIR, grid)
    if not os.path.isdir(d):
        return []
    out = {}
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".csv.gz"):
            out.setdefault(fn[:-7], []).insert(0, os.path.join(d, fn))
        elif fn.endswith(".csv"):
            out.setdefault(fn[:-4], []).append(os.path.join(d, fn))
    return sorted(out.items())


_DAYCACHE = {}


def load_reference(grid, start=None, end=None, min_sources=1, label=None):
    """Reference built from the day files overlapping [start, end] (all days when None)."""
    parts = []
    for name, paths in day_files(grid):
        d0 = int(dt.datetime.fromisoformat(name).replace(tzinfo=dt.timezone.utc).timestamp())
        if start is not None and d0 + 86400 < start:
            continue
        if end is not None and d0 > end:
            continue
        f = np.full(86400, np.nan)
        n = np.zeros(86400, int)
        for p in paths:
            key = (p, os.path.getmtime(p))
            if key not in _DAYCACHE:
                _DAYCACHE[key] = read_day_file(p)
            _, fp, np_ = _DAYCACHE[key]
            m = np.isfinite(fp)
            f[m], n[m] = fp[m], np_[m]
        f = np.where(n >= min_sources, f, np.nan)
        parts.append(R.Reference(float(d0), 1.0, f, label or grid, 60, False, label or grid, 1.0))
    if not parts:
        return None
    ref = R.concat(parts, label) if len(parts) > 1 else parts[0]
    ref.source = label or grid
    return ref


def coverage_days(grid):
    return [name for name, _ in day_files(grid)]


# ---------------------------------------------------------------- archive rebuild

def rebuild_day(grid, day, stations=None, log=print, lead_s=1800, use_cache=True, fill_only=False):
    """Fetch, extract, verify and write one UTC day for `grid`. Returns summary dict.
    fill_only=True keeps every second already in that day's file(s) (for example from the live
    collector) and only fills the gaps from the archive."""
    stations = stations or [s[0] for s in stations_for(grid)]
    tracks, t0 = {}, None
    for sid in stations:
        t0_, f, snr = station_day(sid, day, lead_s=lead_s, log=log, use_cache=use_cache)
        t0 = t0_
        ok = np.isfinite(f).mean()
        log(f"  {sid}: {ok * 100:.0f}% of seconds with a hum line (SNR >= {MIN_SNR_DB:.0f} dB)")
        if ok > 0.02:
            tracks[sid] = f
    n = 86400 + 2 * lead_s
    if t0 is None:
        t0 = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp()) - lead_s
    if not tracks:
        res = dict(f=np.full(n, np.nan), n_sources=np.zeros(n, int), spread_mhz=np.full(n, np.nan),
                   quality=np.full(n, "none"), per_window=[], states={}, lags={})
    else:
        res = build_consensus(tracks, t0, n)
    t_lab = t0 + LABEL_SHIFT_S
    body = slice(lead_s, lead_s + 86400)
    cov = float(np.isfinite(res["f"][body]).mean())
    used = {}
    for pw in res["per_window"]:
        for i in pw["used"]:
            used[i] = used.get(i, 0) + 1
    meta = dict(grid=grid, day=day.isoformat(), stations=stations, coverage=cov,
                windows_used=used, final_states=res["states"], lags=res["lags"],
                median_sources=float(np.median(res["n_sources"][body])) if len(res["n_sources"]) else 0,
                label_shift_s=LABEL_SHIFT_S, built=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                data="EarthScope FDSN dataselect (public, no login); see NETWORK_DOIS")
    if fill_only:
        d0 = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp())
        for name, paths in day_files(grid):
            if name != day.isoformat():
                continue
            for pth in paths:
                _, fe, ne = read_day_file(pth)
                i0 = d0 - int(t_lab)
                m = np.isfinite(fe)
                idx = np.where(m)[0] + i0
                ok = (idx >= 0) & (idx < len(res["f"]))
                res["f"][idx[ok]] = fe[m][ok]
                res["n_sources"][idx[ok]] = ne[m][ok]
            live = day_path(grid, day, gz=False)
            if os.path.exists(live) and day < dt.datetime.now(dt.timezone.utc).date():
                os.remove(live)          # its rows are now in the merged .csv.gz
        meta["fill_only"] = True
    p, rows = write_day(grid, day, t_lab, res["f"], res["n_sources"], res["spread_mhz"], res["quality"], meta)
    log(f"{grid} {day}: {rows} s written ({cov * 100:.1f}% of the day), median {meta['median_sources']:.0f} stations -> {p}")
    meta["path"], meta["rows"] = p, rows
    meta["_res"] = res
    meta["_t0"] = t_lab
    return meta


def rebuild_range(grid, start_day, end_day, stations=None, log=print, fill_only=False):
    out = []
    d = start_day
    while d <= end_day:
        m = rebuild_day(grid, d, stations, log=log, fill_only=fill_only)
        m.pop("_res", None)
        out.append(m)
        d += dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------- command line

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Rebuild seismic grid-frequency day files from the public FDSN archive.")
    ap.add_argument("--grid", default="US-WEST", choices=("US-WEST", "US-TEXAS", "US-EAST"))
    ap.add_argument("--start", help="first UTC day, YYYY-MM-DD")
    ap.add_argument("--end", help="last UTC day (default: same as start)")
    ap.add_argument("--stations", help="comma list of NET.STA.LOC.CHA (default: the catalogue for the grid)")
    ap.add_argument("--out-dir", help="default ~/.cache/provenance/enf/us/seismic")
    ap.add_argument("--fill-only", action="store_true", help="keep existing seconds (live data), only fill gaps")
    ap.add_argument("--yesterday", action="store_true", help="shortcut: --start = yesterday (UTC)")
    a = ap.parse_args(argv)
    if a.out_dir:
        globals()["SEISMIC_DIR"] = a.out_dir
    if a.yesterday:
        a.start = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    if not a.start:
        ap.error("--start or --yesterday is required")
    d0 = dt.date.fromisoformat(a.start)
    d1 = dt.date.fromisoformat(a.end) if a.end else d0
    st = a.stations.split(",") if a.stations else None
    for m in rebuild_range(a.grid, d0, d1, st, fill_only=a.fill_only):
        print(json.dumps({k: m[k] for k in ("day", "coverage", "median_sources", "rows", "path")}))


if __name__ == "__main__":
    main()
