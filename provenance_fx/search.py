"""The location search: candidate grid -> CPA tables -> filters -> locked Doppler scoring.

Stages (mirrors the video):
 1. Lay a grid (default 200 m) over the search box.
 2. For every flight and nearby grid point, find the closest point of approach (CPA),
    its 3D slant distance (using the DEM for ground height) and the DELAYED CPA time
    (when that closest point is heard: t_cpa + distance / c).
 3. Filter: propeller-capable flights (known jets removed), speed and slant distance
    inside each event's measured range, delayed-CPA offset between the two events equal
    to the offset in the audio, and SILENCE: no other flight passes close while the clip runs.
 4. Densify survivors to 100 m, model the exact Doppler curve each candidate would hear
    from the real ADS-B geometry (emission-time correct), and score it against the spectrogram.
    Event 1 is swept in time and base pitch; event 2 is LOCKED to event 1 by flight geometry
    and only swept in base pitch.
 5. Keep the best point per flight pair, rank, then do a fine 25 m pass around the winner.
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree

from .adsb import Track, TrackModel
from .geo import DEM, LocalFrame
from .measure import EventMeasurement
from .physics import C_DEFAULT, heard_frequency
from .spectro import Spectrogram, tolerant_brightness


@dataclass
class SearchParams:
    bbox: tuple                      # lat_min, lat_max, lon_min, lon_max
    t_window: tuple                  # unix seconds: earliest and latest possible event time
    grid_m: float = 200.0
    refine_m: float = 100.0
    fine_m: float = 25.0
    fine_radius_m: float = 400.0
    max_range_m: float = 10000.0
    obs_height_m: float = 2.0
    offset_tol_s: float = 8.0
    silence_radius_m: float = 2500.0
    silence_margin_s: float = 45.0
    silence_scope: str = "between"          # "between" the two events (video) or whole "clip"
    contrast_hz: float = 4.0                # 0 = plain brightness (v1); >0 = on-curve minus off-curve
    normalise_events: bool = True           # divide each event's score by its traced ridge's score
    exclude_known_jets: bool = True
    c: float = C_DEFAULT
    time_sweep_s: float = 5.0
    time_step_s: float = 0.5
    f0_steps: int = 9
    known_clip_start: float | None = None   # unix time of audio t=0, if known
    known_time_tol_s: float = 30.0          # filter tolerance on delayed CPA time
    clock_tol_s: float = 2.0                # scoring sweep when the clock is known
    log: callable = print


@dataclass
class FlightIndex:
    track: Track
    model: TrackModel
    ts: np.ndarray
    P: np.ndarray
    is_jet: bool


@dataclass
class SearchResult:
    frame: LocalFrame
    mode: str
    stages: list = field(default_factory=list)       # (name, count) funnel
    candidates: dict = field(default_factory=dict)   # arrays for every scored candidate
    ranking: list = field(default_factory=list)      # best per flight pair / flight
    best: dict = field(default_factory=dict)
    fine: dict = field(default_factory=dict)
    flights: dict = field(default_factory=dict)
    flight_index: list = field(default_factory=list)
    alternatives: list = field(default_factory=list)
    epoch: float = 0.0
    params: object = None
    timings: dict = field(default_factory=dict)


# ---------------------------------------------------------------- helpers

def _grid(frame, bbox, step):
    x0, y0 = frame.to_xy(bbox[0], bbox[2])
    x1, y1 = frame.to_xy(bbox[1], bbox[3])
    xs = np.arange(float(x0), float(x1) + 1e-6, step)
    ys = np.arange(float(y0), float(y1) + 1e-6, step)
    X, Y = np.meshgrid(xs, ys)
    return X.ravel(), Y.ravel()


def _ground(frame, dem, x, y):
    lat, lon = frame.to_latlon(x, y)
    return dem.elevation(lat, lon)


def _cpa_local(fi: FlightIndex, obs, center_idx, half=40):
    """CPA near a guessed sample index. obs (n,3), center_idx (n,). Returns t_cpa, d_cpa, edge flag."""
    n = len(center_idx)
    offs = np.arange(-half, half + 1)
    idx = np.clip(center_idx[:, None] + offs[None, :], 0, len(fi.ts) - 1)
    D = np.linalg.norm(fi.P[idx] - obs[:, None, :], axis=-1)
    j = np.argmin(D, axis=1)
    rows = np.arange(n)
    jj = np.clip(j, 1, D.shape[1] - 2)
    a, b, c = D[rows, jj - 1], D[rows, jj], D[rows, jj + 1]
    den = a - 2 * b + c
    with np.errstate(invalid="ignore", divide="ignore"):
        off = np.where(np.abs(den) > 1e-9, 0.5 * (a - c) / den, 0.0)
    off = np.clip(off, -1, 1)
    gi = idx[rows, jj]
    dt = fi.ts[1] - fi.ts[0] if len(fi.ts) > 1 else 1.0
    t_cpa = fi.ts[gi] + off * dt
    d_cpa = b - 0.25 * (a - c) * off
    edge = (gi <= 0) | (gi >= len(fi.ts) - 1)
    return t_cpa, d_cpa, gi, edge


def _keys(g, t):
    return g.astype(np.float64) * 1e6 + t


def _count_in(sorted_keys, lo, hi):
    return np.searchsorted(sorted_keys, hi, "right") - np.searchsorted(sorted_keys, lo, "left")


# ---------------------------------------------------------------- main entry

def locate(tracks: list[Track], dem: DEM, spec: Spectrogram, events: list[EventMeasurement],
           ridges: list, audio_duration: float, p: SearchParams) -> SearchResult:
    log = p.log
    T0 = _time.time()
    lat_c = 0.5 * (p.bbox[0] + p.bbox[1])
    lon_c = 0.5 * (p.bbox[2] + p.bbox[3])
    frame = LocalFrame(lat_c, lon_c)
    mode = "two-event" if len(events) >= 2 else "one-event"
    if mode == "one-event" and p.known_clip_start is None:
        log("WARNING: one event and no known recording time; expect many ties.")
    epoch = p.t_window[0] - 7200.0
    res = SearchResult(frame=frame, mode=mode, epoch=epoch, params=p)

    gx, gy = _grid(frame, p.bbox, p.grid_m)
    gz = _ground(frame, dem, gx, gy) + p.obs_height_m
    G = np.stack([gx, gy, gz], axis=-1)
    tree = cKDTree(G[:, :2])
    res.stages.append(("grid points", len(gx)))
    log(f"grid: {len(gx):,} points at {p.grid_m:.0f} m")

    # ---- flights in space/time
    xb0, yb0 = frame.to_xy(p.bbox[0], p.bbox[2])
    xb1, yb1 = frame.to_xy(p.bbox[1], p.bbox[3])
    pad_t = 1800.0
    flights: list[FlightIndex] = []
    for tr in tracks:
        if tr.t[-1] < p.t_window[0] - pad_t or tr.t[0] > p.t_window[1] + pad_t + audio_duration:
            continue
        x, y = frame.to_xy(tr.lat, tr.lon)
        r = p.max_range_m
        if x.max() < xb0 - r or x.min() > xb1 + r or y.max() < yb0 - r or y.min() > yb1 + r:
            continue
        m = TrackModel(tr, frame)
        ts = np.arange(m.t0, m.t1, 1.0)
        if len(ts) < 10:
            continue
        P = m.pos(ts)
        flights.append(FlightIndex(tr, m, ts, P, tr.is_known_jet))
    res.stages.append(("flights in space/time window", len(flights)))
    log(f"flights in window: {len(flights)} ({sum(f.is_jet for f in flights)} known jets)")

    # ---- CPA tables
    # Only distances that some filter can use need storing: the silence radius and the
    # widest measured slant-distance range. Everything else is capped by max_range_m.
    keep_r = min(p.max_range_m, max([p.silence_radius_m] + [e.slant_range[1] for e in events]))
    ent = {k: [] for k in ("g", "f", "tdel", "d", "spd", "gi")}
    for fidx, fi in enumerate(flights):
        # Known jets only matter for the silence filter, so search them to that radius only.
        r_f = p.silence_radius_m if (fi.is_jet and p.exclude_known_jets) else keep_r
        coarse = np.arange(0, len(fi.ts), 10)
        Pc = fi.P[coarse]
        near = tree.query_ball_point(Pc[:, :2], r=r_f + 800)
        gset = np.unique(np.concatenate([np.asarray(a, dtype=np.int64) for a in near])) if len(near) else []
        if len(gset) == 0:
            continue
        ctree = cKDTree(Pc[:, :2])
        _, j = ctree.query(G[gset, :2])
        t_cpa, d_cpa, gi, edge = _cpa_local(fi, G[gset], coarse[j], half=15)
        ok = (~edge) & (d_cpa <= r_f)
        if not ok.any():
            continue
        spd_all = np.linalg.norm(fi.model.vel(t_cpa), axis=-1)
        # keep a row if it can serve the silence filter or some event's speed window
        useful = d_cpa <= p.silence_radius_m
        for e in events:
            useful |= (spd_all >= e.speed_range[0]) & (spd_all <= e.speed_range[1])
        ok &= useful
        if not ok.any():
            continue
        v = fi.model.vel(t_cpa[ok])
        ent["g"].append(gset[ok])
        ent["f"].append(np.full(ok.sum(), fidx, dtype=np.int32))
        ent["tdel"].append(t_cpa[ok] + d_cpa[ok] / p.c - epoch)
        ent["d"].append(d_cpa[ok].astype(np.float32))
        ent["spd"].append(np.linalg.norm(v, axis=-1).astype(np.float32))
        ent["gi"].append(gi[ok].astype(np.int32))
    E = {k: np.concatenate(v) if v else np.array([]) for k, v in ent.items()}
    res.stages.append(("(grid point, flight) CPA pairs within range", len(E["g"])))
    log(f"CPA table: {len(E['g']):,} (point, flight) pairs")
    res.timings["cpa_tables_s"] = round(_time.time() - T0, 1)
    is_jet = np.array([f.is_jet for f in flights])

    t_lo, t_hi = p.t_window[0] - epoch, p.t_window[1] - epoch

    def event_mask(e: EventMeasurement):
        m = (E["spd"] >= e.speed_range[0]) & (E["spd"] <= e.speed_range[1])
        m &= (E["d"] >= e.slant_range[0]) & (E["d"] <= e.slant_range[1])
        if p.exclude_known_jets:
            m &= ~is_jet[E["f"]]
        if p.known_clip_start is not None:
            tc = p.known_clip_start + e.t_cpa - epoch
            m &= np.abs(E["tdel"] - tc) <= p.known_time_tol_s
        else:
            m &= (E["tdel"] >= t_lo) & (E["tdel"] <= t_hi + audio_duration)
        return np.nonzero(m)[0]

    e1 = events[0]
    i1 = event_mask(e1)
    res.stages.append((f"{e1.name}: speed + slant-distance match", len(np.unique(E['g'][i1]))))
    log(f"{e1.name}: {len(i1):,} matching (point, flight) pairs")

    # silence table: any flight (jets too) passing within silence radius
    sm = E["d"] <= p.silence_radius_m
    s_keys = np.sort(_keys(E["g"][sm], E["tdel"][sm]))

    if mode == "two-event":
        e2 = events[1]
        i2 = event_mask(e2)
        res.stages.append((f"{e2.name}: speed + slant-distance match", len(np.unique(E['g'][i2]))))
        delta = e2.t_cpa - e1.t_cpa
        k2 = _keys(E["g"][i2], E["tdel"][i2])
        order = np.argsort(k2)
        k2s, i2s = k2[order], i2[order]
        k1 = _keys(E["g"][i1], E["tdel"][i1])
        lo = np.searchsorted(k2s, k1 + delta - p.offset_tol_s, "left")
        hi = np.searchsorted(k2s, k1 + delta + p.offset_tol_s, "right")
        cnt = hi - lo
        a_idx = np.repeat(i1, cnt)
        b_idx = i2s[np.concatenate([np.arange(l, h) for l, h in zip(lo, hi)]) if cnt.sum() else []]
        diff = E["f"][a_idx] != E["f"][b_idx]
        a_idx, b_idx = a_idx[diff], b_idx[diff]
        res.stages.append(("time-offset filter (both events, right gap)", len(np.unique(E['g'][a_idx]))))
        log(f"offset filter: {len(np.unique(E['g'][a_idx])):,} points")
        g = E["g"][a_idx]
        t1, t2 = E["tdel"][a_idx], E["tdel"][b_idx]
        mg = p.silence_margin_s
        if p.silence_scope == "clip":
            # strict: nothing else close at any time while the clip runs
            w_lo = t1 - e1.t_cpa
            w_hi = t1 - e1.t_cpa + audio_duration
            noisy = (_count_in(s_keys, _keys(g, w_lo), _keys(g, w_hi))
                     - _count_in(s_keys, _keys(g, t1 - mg), _keys(g, t1 + mg))
                     - _count_in(s_keys, _keys(g, t2 - mg), _keys(g, t2 + mg)))
        else:
            # as in the video: nothing else close BETWEEN the two events
            noisy = _count_in(s_keys, _keys(g, t1 + mg), _keys(g, t2 - mg))
        quiet = noisy <= 0
        a_idx, b_idx = a_idx[quiet], b_idx[quiet]
        res.stages.append(("silence filter (no other close flight between the events)",
                           len(np.unique(E['g'][a_idx]))))
        log(f"silence filter: {len(np.unique(E['g'][a_idx])):,} points")
        combos = np.unique(np.stack([E["g"][a_idx], E["f"][a_idx], E["f"][b_idx]], 1), axis=0)
        seeds = [(int(gg), int(fa), int(fb)) for gg, fa, fb in combos]
    else:
        g = E["g"][i1]
        t1 = E["tdel"][i1]
        w_lo = t1 - e1.t_cpa
        w_hi = w_lo + audio_duration
        mg = p.silence_margin_s
        noisy = (_count_in(s_keys, _keys(g, w_lo), _keys(g, w_hi))
                 - _count_in(s_keys, _keys(g, t1 - mg), _keys(g, t1 + mg)))
        i1q = i1[noisy <= 0]
        res.stages.append(("silence filter (no other close flight during clip)",
                           len(np.unique(E['g'][i1q]))))
        combos = np.unique(np.stack([E["g"][i1q], E["f"][i1q]], 1), axis=0)
        seeds = [(int(gg), int(fa), -1) for gg, fa in combos]

    if not seeds:
        log("No candidates survived the filters.")
        res.timings["total_s"] = round(_time.time() - T0, 1)
        return res

    # ---- densify to refine_m around each surviving coarse point
    o = p.refine_m
    offs = [(dx, dy) for dx in (-o, 0, o) for dy in (-o, 0, o)]
    seen = set()
    cx, cy, fa_l, fb_l = [], [], [], []
    for gg, fa, fb in seeds:
        for dx, dy in offs:
            x = gx[gg] + dx
            y = gy[gg] + dy
            key = (round(x / o), round(y / o), fa, fb)
            if key in seen:
                continue
            seen.add(key)
            cx.append(x); cy.append(y); fa_l.append(fa); fb_l.append(fb)
    cx, cy = np.array(cx), np.array(cy)
    fa_a, fb_a = np.array(fa_l), np.array(fb_l)
    cz = _ground(frame, dem, cx, cy) + p.obs_height_m
    C = np.stack([cx, cy, cz], -1)
    res.stages.append((f"candidates after densifying to {p.refine_m:.0f} m", len(cx)))
    log(f"scoring {len(cx):,} candidates")

    scores = score_candidates(flights, C, fa_a, fb_a, spec, events, ridges, p, epoch)
    res.timings["scoring_s"] = round(_time.time() - T0 - res.timings["cpa_tables_s"], 1)

    lat, lon = frame.to_latlon(cx, cy)
    res.candidates = dict(x=cx, y=cy, lat=lat, lon=lon, fa=fa_a, fb=fb_a, **scores)
    res.flights = {i: f.track for i, f in enumerate(flights)}
    res.flight_index = flights

    # best per flight pair
    total = scores["total"]
    pair_best = {}
    for i in np.argsort(-total):
        key = (int(fa_a[i]), int(fb_a[i]))
        if key not in pair_best:
            pair_best[key] = i
    ranked = sorted(pair_best.values(), key=lambda i: -total[i])
    res.ranking = [
        dict(rank=r + 1, lat=float(lat[i]), lon=float(lon[i]), total=float(total[i]),
             s1=float(scores["s1"][i]), s2=float(scores["s2"][i]),
             flight1=flights[fa_a[i]].track.flight_id, callsign1=flights[fa_a[i]].track.callsign,
             type1=flights[fa_a[i]].track.typecode,
             flight2=flights[fb_a[i]].track.flight_id if fb_a[i] >= 0 else "",
             callsign2=flights[fb_a[i]].track.callsign if fb_a[i] >= 0 else "",
             type2=flights[fb_a[i]].track.typecode if fb_a[i] >= 0 else "",
             idx=int(i))
        for r, i in enumerate(ranked[:25])
    ]
    best_i = ranked[0]
    res.best = dict(res.ranking[0])
    # Other separate spots that fit the SAME flight(s) almost as well. With one flight, a
    # point mirrored across the flight path hears nearly the same curve, so this matters.
    same = np.nonzero((fa_a == fa_a[best_i]) & (fb_a == fb_a[best_i]))[0]
    same = same[np.argsort(-total[same])]
    alts = []
    for i in same:
        if all(np.hypot(cx[i] - cx[j], cy[i] - cy[j]) > 500 for j in [best_i] + [a["idx"] for a in alts]):
            alts.append(dict(idx=int(i), lat=float(lat[i]), lon=float(lon[i]), total=float(total[i]),
                             dist_from_best_m=float(np.hypot(cx[i] - cx[best_i], cy[i] - cy[best_i])),
                             score_ratio=float(total[i] / total[best_i]) if total[best_i] else 0.0))
        if len(alts) >= 3:
            break
    res.alternatives = alts
    if len(ranked) > 1:
        res.best["margin_over_second"] = float(total[best_i] - total[ranked[1]])

    # ---- fine pass around the winner, same flight pair only
    fr = p.fine_radius_m
    xs = np.arange(-fr, fr + 1e-6, p.fine_m)
    FX, FY = np.meshgrid(cx[best_i] + xs, cy[best_i] + xs)
    fxv, fyv = FX.ravel(), FY.ravel()
    fz = _ground(frame, dem, fxv, fyv) + p.obs_height_m
    FC = np.stack([fxv, fyv, fz], -1)
    n = len(fxv)
    fsc = score_candidates(flights, FC, np.full(n, fa_a[best_i]), np.full(n, fb_a[best_i]), spec,
                           events, ridges, p, epoch)
    j = int(np.argmax(fsc["total"]))
    flat, flon = frame.to_latlon(fxv, fyv)
    tot = fsc["total"]
    top = tot >= np.percentile(tot, 98)
    w = tot[top] - tot[top].min() + 1e-9
    res.fine = dict(x=fxv, y=fyv, lat=flat, lon=flon, total=tot, shape=FX.shape,
                    best_lat=float(flat[j]), best_lon=float(flon[j]),
                    centroid_lat=float(np.sum(flat[top] * w) / w.sum()),
                    centroid_lon=float(np.sum(flon[top] * w) / w.sum()),
                    best_detail={k: (v[j] if hasattr(v, "__len__") else v) for k, v in fsc.items()})
    res.best["fine_lat"] = res.fine["best_lat"]
    res.best["fine_lon"] = res.fine["best_lon"]
    res.timings["total_s"] = round(_time.time() - T0, 1)
    log(f"done in {res.timings['total_s']} s")
    return res


def dict_override(p: SearchParams, **kw) -> SearchParams:
    from dataclasses import replace
    return replace(p, **kw)


# ---------------------------------------------------------------- scoring

def model_curves(fi: FlightIndex, obs, f0, tau, p: SearchParams, epoch):
    """Delayed CPA (relative to epoch) and the modelled pitch curve on a tau grid around it."""
    tree = cKDTree(fi.P[::5, :2])
    _, j = tree.query(obs[:, :2])
    t_cpa, d_cpa, gi, edge = _cpa_local(fi, obs, j * 5, half=40)
    tdel = t_cpa + d_cpa / p.c
    t_rx = tdel[:, None] + tau[None, :]
    freq, r, te = heard_frequency(fi.model, obs[:, None, :], t_rx, f0, p.c)
    return tdel - epoch, freq


def _bright_score(Bt, spec, fm, place, ks, ev, off_hz: float = 0.0):
    """Mean brightness along k*fm placed so tau=0 sits at audio time `place`.

    With off_hz > 0 the score is a CONTRAST: brightness on the curve minus the mean
    brightness off_hz above and below it. A wrong curve that merely runs through a
    noisy or broadband patch no longer scores well; only a thin bright line under the
    curve does. fm: (n,T) Hz on tau grid; place: (n,) seconds.
    Returns the best score and best base-pitch scale k per row.
    """
    n, T = fm.shape
    hop = spec.hop
    nF, nT = Bt.shape
    tau = (np.arange(T) - T // 2) * hop
    s = place[:, None] + tau[None, :]
    col = np.rint((s - spec.t[0]) / hop).astype(int)
    inwin = (s >= ev.t_start) & (s <= ev.t_end) & (col >= 0) & (col < nT)
    col = np.clip(col, 0, nT - 1)
    best = np.full(n, -np.inf)
    bestk = np.ones(n)
    nvalid = np.maximum(inwin.sum(1), 1)
    off = int(round(off_hz / spec.df)) if off_hz else 0

    def gather(fb):
        ok = inwin & np.isfinite(fb) & (fb >= 0) & (fb < nF)
        fbi = np.clip(np.nan_to_num(fb), 0, nF - 1).astype(int)
        return np.where(ok, Bt[fbi, col], 0.0)

    for k in ks:
        fb = np.rint((k * fm - spec.f[0]) / spec.df)
        on = gather(fb)
        if off:
            on = on - 0.5 * (gather(fb + off) + gather(fb - off))
        val = on.sum(1) / nvalid
        upd = val > best
        best[upd] = val[upd]
        bestk[upd] = k
    return best, bestk


def ridge_reference(Bt, spec, ridge, ev, off_hz: float = 0.0):
    """Score of the traced ridge itself, used to put both events on the same scale."""
    times, freqs, strength = ridge
    fm = freqs[None, :]
    # place the ridge on its own times: tau grid = frame offsets from the middle frame
    T = len(times)
    place = np.array([times[T // 2]])
    sc, _ = _bright_score(Bt, spec, fm, place, [1.0], ev, off_hz)
    return max(float(sc[0]), 1e-6)


def _trace_score(fm, place, ridge, ks_range, hop):
    """Weighted RMS (Hz) between modelled curve and traced ridge, best base-pitch scale."""
    times, freqs, strength = ridge
    n, T = fm.shape
    tau = (np.arange(T) - T // 2) * hop
    pos = (times[None, :] - place[:, None] - tau[0]) / hop
    i0 = np.clip(np.floor(pos).astype(int), 0, T - 2)
    fr = np.clip(pos - i0, 0, 1)
    rows = np.arange(n)[:, None]
    g = fm[rows, i0] * (1 - fr) + fm[rows, i0 + 1] * fr
    w = np.sqrt(np.clip(strength, 0, None))[None, :] * np.isfinite(g)
    g = np.nan_to_num(g)
    k = (w * freqs * g).sum(1) / np.maximum((w * g * g).sum(1), 1e-9)
    k = np.clip(k, ks_range[0], ks_range[1])
    r = freqs[None, :] - k[:, None] * g
    return np.sqrt((w * r * r).sum(1) / np.maximum(w.sum(1), 1e-9))


def score_candidates(flights, C, fa, fb, spec, events, ridges, p: SearchParams, epoch):
    """Locked two-event (or single-event) scoring for candidate points C (n,3)."""
    n = len(C)
    Bt = tolerant_brightness(spec, 1)
    hop = spec.hop
    out = {k: np.full(n, np.nan) for k in ("s1", "s2", "total", "trace1", "trace2", "dt1", "k1", "k2")}
    e1 = events[0]
    e2 = events[1] if len(events) > 1 else None
    half1 = max(e1.t_cpa - e1.t_start, e1.t_end - e1.t_cpa) + p.time_sweep_s + 5
    T1 = int(2 * half1 / hop) | 1
    tau1 = (np.arange(T1) - T1 // 2) * hop
    if e2 is not None:
        half2 = max(e2.t_cpa - e2.t_start, e2.t_end - e2.t_cpa) + p.offset_tol_s + 5
        T2 = int(2 * half2 / hop) | 1
        tau2 = (np.arange(T2) - T2 // 2) * hop
    if p.known_clip_start is None:
        # unknown recording time: place event 1 at its measured CPA, sweep for measurement error
        sweep = np.arange(-p.time_sweep_s, p.time_sweep_s + 1e-9, p.time_step_s)
    else:
        # known clock: placement is LOCKED to absolute time, sweep only for clock error
        sweep = np.arange(-p.clock_tol_s, p.clock_tol_s + 1e-9, p.time_step_s)
    ks1 = np.linspace(1 - e1.f0_rel_tol, 1 + e1.f0_rel_tol, p.f0_steps)
    ks2 = np.linspace(1 - e2.f0_rel_tol, 1 + e2.f0_rel_tol, p.f0_steps) if e2 else None

    # group by flight pair so each flight model is evaluated in batches
    pairs = {}
    for i in range(n):
        pairs.setdefault((int(fa[i]), int(fb[i])), []).append(i)
    for (a, b), idx in pairs.items():
        idx = np.array(idx)
        for s in range(0, len(idx), 1500):
            sl = idx[s:s + 1500]
            td1, fm1 = model_curves(flights[a], C[sl], e1.f0, tau1, p, epoch)
            if p.known_clip_start is None:
                base1 = np.full(len(sl), e1.t_cpa)
            else:
                base1 = td1 + epoch - p.known_clip_start
            # stage 1: trace residual with best time shift
            best_tr = np.full(len(sl), np.inf)
            best_dt = np.zeros(len(sl))
            for d in sweep:
                tr = _trace_score(fm1, base1 + d, ridges[0],
                                  (ks1[0], ks1[-1]), hop)
                upd = tr < best_tr
                best_tr[upd] = tr[upd]
                best_dt[upd] = d
            out["trace1"][sl] = best_tr
            out["dt1"][sl] = best_dt
            if e2 is not None:
                td2, fm2 = model_curves(flights[b], C[sl], e2.f0, tau2, p, epoch)
                place2 = base1 + best_dt + (td2 - td1)
                out["trace2"][sl] = _trace_score(fm2, place2, ridges[1], (ks2[0], ks2[-1]), hop)
            # stage 2: brightness (the video's method: sum of pixel brightness under the curve)
            bs = np.full(len(sl), -np.inf)
            bk = np.ones(len(sl))
            bdt = np.zeros(len(sl))
            for d in sweep:
                sc, kk = _bright_score(Bt, spec, fm1, base1 + d, ks1, e1, p.contrast_hz)
                upd = sc > bs
                bs[upd], bk[upd], bdt[upd] = sc[upd], kk[upd], d
            out["s1"][sl], out["k1"][sl], out["dt1"][sl] = bs, bk, bdt
            if e2 is not None:
                place2 = base1 + bdt + (td2 - td1)   # LOCKED to event 1 by geometry
                sc2, kk2 = _bright_score(Bt, spec, fm2, place2, ks2, e2, p.contrast_hz)
                out["s2"][sl], out["k2"][sl] = sc2, kk2
    out["s2"] = np.nan_to_num(out["s2"], nan=0.0)
    if p.normalise_events:
        # 1.0 means "as bright and thin as the traced line itself" for each event, so a
        # faint second flyover counts as much as a loud first one.
        out["s1"] = out["s1"] / ridge_reference(Bt, spec, ridges[0], e1, p.contrast_hz)
        if e2 is not None:
            out["s2"] = out["s2"] / ridge_reference(Bt, spec, ridges[1], e2, p.contrast_hz)
    out["total"] = out["s1"] + out["s2"]
    return out
