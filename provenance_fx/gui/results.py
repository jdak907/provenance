"""Turn a SearchResult into a JSON payload for the browser."""
from __future__ import annotations

import numpy as np

from ..search import _ground, model_curves
from .render import thin


def candidate_curves(res, spec, events, dem, i):
    """Modelled curves for candidate index i, placed on the audio timeline as scored."""
    c, p = res.candidates, res.params
    obs = np.array([[c["x"][i], c["y"][i],
                     float(_ground(res.frame, dem, c["x"][i], c["y"][i])) + p.obs_height_m]])
    hop = spec.hop
    out = []
    base = td1 = None
    for k, e in enumerate(events):
        fidx = int(c["fa"][i] if k == 0 else c["fb"][i])
        if fidx < 0:
            break
        fi = res.flight_index[fidx]
        half = (e.t_end - e.t_start) * 0.75 + 20
        T = int(2 * half / hop) | 1
        tau = (np.arange(T) - T // 2) * hop
        td, fm = model_curves(fi, obs, e.f0, tau, p, res.epoch)
        kk = c["k1"][i] if k == 0 else c["k2"][i]
        if k == 0:
            base = (e.t_cpa if p.known_clip_start is None
                    else td[0] + res.epoch - p.known_clip_start) + c["dt1"][i]
            td1 = td[0]
            place = base
        else:
            place = base + (td[0] - td1)
        out.append(thin(place + tau, kk * fm[0], 500))
    return out


def track_latlon(res, fidx, n=400):
    fi = res.flight_index[fidx]
    lat, lon = res.frame.to_latlon(fi.P[:, 0], fi.P[:, 1])
    step = max(1, len(lat) // n)
    return [[round(float(a), 5), round(float(b), 5)] for a, b in zip(lat[::step], lon[::step])]


def confidence(r_total, next_total):
    gap = r_total - next_total
    rel = gap / max(abs(r_total), 1e-9)
    if rel > 0.15:
        return "high"
    if rel > 0.05:
        return "medium"
    return "low"


def build_payload(res, spec, events, ridges, dem, top_n=10, heat_n=4000):
    c = res.candidates
    if not res.ranking:
        return dict(ok=False, stages=res.stages, message="No candidate survived the filters.")
    ranking = []
    totals = [r["total"] for r in res.ranking]
    for j, r in enumerate(res.ranking[:25]):
        nxt = totals[j + 1] if j + 1 < len(totals) else 0.0
        item = {k: v for k, v in r.items()}
        # Rank 1: how clearly it beats the runner-up. Others: how close they come to rank 1.
        if j == 0:
            item["confidence"] = confidence(r["total"], nxt)
        else:
            item["confidence"] = "medium" if r["total"] >= 0.9 * totals[0] else "low"
        if j < top_n:
            item["curves"] = candidate_curves(res, spec, events, dem, r["idx"])
            item["track1"] = track_latlon(res, int(c["fa"][r["idx"]]))
            fb = int(c["fb"][r["idx"]])
            item["track2"] = track_latlon(res, fb) if fb >= 0 else []
        ranking.append(item)
    order = np.argsort(-c["total"])[:heat_n]
    tot = c["total"][order]
    lo, hi = float(np.min(tot)), float(np.max(tot))
    heat = [[round(float(c["lat"][i]), 5), round(float(c["lon"][i]), 5),
             round((float(c["total"][i]) - lo) / max(hi - lo, 1e-9), 3)] for i in order]
    fn = res.fine
    ftot = fn["total"]
    flo, fhi = float(np.min(ftot)), float(np.max(ftot))
    fine = [[round(float(a), 6), round(float(b), 6), round((float(v) - flo) / max(fhi - flo, 1e-9), 3)]
            for a, b, v in zip(fn["lat"], fn["lon"], ftot)]
    best = dict(res.best)
    best["confidence"] = ranking[0]["confidence"]
    return dict(
        ok=True, mode=res.mode, best=best, ranking=ranking, alternatives=res.alternatives,
        stages=[[n, int(v)] for n, v in res.stages], timings=res.timings, heat=heat, fine=fine,
        fine_step_m=res.params.fine_m,
        events=[dict(e.to_dict(), ridge=thin(r[0], r[1], 500)) for e, r in zip(events, ridges)],
        bbox=list(res.params.bbox),
    )
