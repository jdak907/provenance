"""Grid race: which grid's concurrent frequency log does the recording's hum follow?

If the time of the recording is roughly known, the recording's ENF is matched against the
log of EVERY grid (same nominal) that covers the time window. Only the grid the recorder was
plugged into can line up; the others give only chance-level correlation. The decision uses
the winner's correlation, its margin over the best other grid and its own false-alarm
probability, and it ABSTAINS when nothing stands out.

Thresholds were tuned on simulated mic recordings built from real grid logs and checked
on real UK recordings (see enf_validation.md).
"""
from __future__ import annotations

import numpy as np

from . import grids as G
from .match import match

# Decision rule, tuned on 648 simulated race runs (enf_validation.md):
#   r      = winner's level-gated correlation
#   dz     = Fisher-z margin atanh(r_winner) - atanh(r_next_grid); a margin of 0.29 between 0.99 and 0.70
#            is far stronger evidence than 0.29 between 0.50 and 0.21, which plain r differences hide
#   p      = winner's own false-alarm probability over the whole search window
DECISIVE = dict(r=0.80, dz=1.0, p=0.01)
LIKELY = dict(r=0.60, dz=0.5, p=0.5)
SINGLE_GRID_P = 0.05  # when only one grid has a reference, its own match must be significant
MIN_DUR_S = 180.0
LOW_TRUST = 0.8       # a winner whose reference has trust below this (e.g. FNET gauge scrape) is capped at
LOW_TRUST_DZ = 1.5    # "likely" and needs this many times the usual Fisher-z margin


SEG_S = 300.0
SEG_AGREE_S = 120.0


def _sub(tr, a, b):
    from .extract import EnfTrace
    m = (tr.t >= tr.t[0] + a) & (tr.t < tr.t[0] + b)
    return EnfTrace(t=tr.t[m], f=tr.f[m], snr_db=tr.snr_db[m] if len(tr.snr_db) == len(tr.t) else np.zeros(m.sum()),
                    nominal=tr.nominal, harmonics_used=tr.harmonics_used, harmonic_snr_db={}, harmonic_corr={},
                    frame_s=tr.frame_s, hop_s=tr.hop_s)


def segment_race(tr, refs, start, end, common):
    """Race 300 s pieces separately. Live streams stall and edits cut audio, which breaks one
    whole-clip alignment; independent pieces that pick the same grid at consistent times are
    still strong evidence. Returns per-segment winners and an aggregate vote."""
    dur = float(tr.t[-1] - tr.t[0] + 1)
    segs = []
    for a in np.arange(0, dur - SEG_S + 1, SEG_S):
        sub = _sub(tr, a, a + SEG_S)
        if np.isfinite(sub.f).sum() < 0.6 * SEG_S:
            continue
        rows = []
        for g, ref in refs.items():
            try:
                m = match(sub, ref, start, end, smooth_s=common if common > 1.5 else None, top_k=1)
            except ValueError:
                continue
            rows.append((m["ncc"], g, m["start_time"], m["p_false"]))
        if len(rows) < 1:
            continue
        rows.sort(reverse=True)
        at = lambda v: float(np.arctanh(np.clip(v, -0.995, 0.995)))
        dz = at(rows[0][0]) - at(rows[1][0]) if len(rows) > 1 else None
        segs.append(dict(t0=float(a), grid=rows[0][1], r=round(rows[0][0], 3), dz=None if dz is None else round(dz, 3),
                         start_time=rows[0][2], p_false=rows[0][3],
                         vote=bool(rows[0][0] >= LIKELY["r"] and dz is not None and dz >= LIKELY["dz"])))
    votes = [s for s in segs if s["vote"]]
    out = dict(segments=segs, winner=None, agree=0, against=0)
    if not votes:
        return out
    grids = [s["grid"] for s in votes]
    g = max(set(grids), key=grids.count)
    mine = [s for s in votes if s["grid"] == g]
    # segments of one recording must imply the same recording start, or a LATER one for later
    # pieces (a stall or cut removes audio, so later audio sits later on the wall clock)
    mine.sort(key=lambda s: s["t0"])
    ts = [s["start_time"] for s in mine]
    chain = [1] * len(ts)
    for i in range(len(ts)):
        for j in range(i):
            if ts[j] - SEG_AGREE_S / 4 <= ts[i] <= ts[j] + max(SEG_AGREE_S, dur):
                chain[i] = max(chain[i], chain[j] + 1)
    consistent = max(chain)
    ts = np.array(ts)
    best = int(np.argmax(chain))
    out.update(winner=g, agree=consistent, against=len(votes) - len(mine), start_time=float(ts[0]))
    return out


def _as_nominal(ref, nominal):
    """Cross-nominal race: shift a 50 Hz log onto 60 Hz (or back) so the level gate compares deviations."""
    if ref.nominal == nominal:
        return ref
    from .reference import Reference
    return Reference(ref.t0, ref.step, ref.f - ref.nominal + nominal, ref.name, nominal, ref.relative,
                     ref.source, ref.resolution_s, ref.trust, ref.tz_uncertain)


def grid_race(tr, start, end, nominal=None, grids=None, log=None, allow_download=True, det=None, cross_nominal=False):
    """tr: EnfTrace; start/end: unix-second window where the recording START may lie.
    cross_nominal: also race grids of the other mains frequency (a control: a 60 Hz hum cannot be on a
    50 Hz grid, but if one of them still "wins" the race is not discriminating)."""
    log = log or (lambda m: None)
    nominal = nominal or tr.nominal
    cand = [g for g, i in G.GRIDS.items() if (cross_nominal or i["nominal"] == nominal) and (grids is None or g in grids)]
    dur = float(tr.t[-1] - tr.t[0] + 1)
    refs, rows, not_covered, shifts_of = {}, [], [], {}
    a_, b_ = start - 60, end + dur + tr.t[0] + 60
    for g in cand:
        ref = G.grid_reference(g, a_, b_, log=log, allow_download=allow_download)
        if ref is None or np.isfinite(ref.f).sum() < dur * 0.8:
            not_covered.append(g)
            continue
        refs[g] = _as_nominal(ref, nominal)
        if g.startswith("US") and G.US.any_tz_uncertain(g, a_, b_):
            shifts_of[g] = (0.0,) + tuple(G.US.TZ_SEARCH_H)
    common = max([r.resolution_s for r in refs.values()] + [1.0])
    tz_used = {}
    for g in list(refs):
        ref = refs[g]
        try:
            m = match(tr, ref, start, end, smooth_s=common if common > 1.5 else None, top_k=3)
        except ValueError as e:
            not_covered.append(g)
            refs.pop(g)
            log(f"{g}: {e}")
            continue
        if g in shifts_of:   # clock offset of a tz-uncertain source: try whole-hour shifts, pay for the extra looks
            best = (m, ref, 0.0)
            for sh in shifts_of[g][1:]:
                r2 = G.grid_reference(g, a_, b_, log=log, allow_download=allow_download, tz_shift_h=sh)
                if r2 is None or np.isfinite(r2.f).sum() < dur * 0.8:
                    continue
                r2 = _as_nominal(r2, nominal)
                try:
                    m2 = match(tr, r2, start, end, smooth_s=common if common > 1.5 else None, top_k=3)
                except ValueError:
                    continue
                if m2["ncc"] > best[0]["ncc"]:
                    best = (m2, r2, sh)
            m, ref, sh = best
            m["p_false"] = float(min(1.0, m["p_false"] * len(shifts_of[g])))
            refs[g] = ref
            tz_used[g] = sh
        rows.append(dict(grid=g, name=G.GRIDS[g]["name"], source=ref.source, resolution_s=ref.resolution_s,
                         trust=ref.trust, tz_shift_h=tz_used.get(g), nominal=G.GRIDS[g]["nominal"],
                         r=m["ncc"], raw_r=m["raw_ncc_at_best"], offset_mhz=m["offset_mhz"],
                         p_false=m["p_false"], best_start=m["start_label"], start_time=m["start_time"],
                         own_gap=m["gap"], label=m["label"], curve=m["curve"], overlay=m["overlay"]))
        log(f"race {g:9s} r={m['ncc']:.3f} offset={m['offset_mhz']} mHz p_false={m['p_false']:.2g} at {m['start_label']}")
    rows.sort(key=lambda x: -x["r"])
    out = dict(window=[start, end], nominal=nominal, duration_s=round(dur, 1), common_resolution_s=common,
               ranking=[{k: v for k, v in r.items() if k not in ("curve", "overlay")} for r in rows],
               not_covered=[dict(grid=g, name=G.GRIDS[g]["name"], sources=G.GRIDS[g]["sources"]) for g in not_covered],
               decision="abstain", winner=None, margin=None, reason="")
    out["_rows"] = rows
    if not rows:
        out["reason"] = "no free reference covers this time window for any candidate grid"
        return out
    w = rows[0]
    second = rows[1]["r"] if len(rows) > 1 else None
    margin = None if second is None else round(w["r"] - max(second, -1.0), 4)
    at = lambda v: float(np.arctanh(np.clip(v, -0.995, 0.995)))
    dz = None if second is None else round(at(w["r"]) - at(second), 3)
    out["margin"] = margin
    out["dz"] = dz
    if det is not None and det.get("verdict") == "absent":
        out["reason"] = "no usable mains hum in the audio, so no grid can be identified"
        return out
    if dur < MIN_DUR_S:
        out["reason"] = f"clip is {dur:.0f} s; the race needs at least {MIN_DUR_S:.0f} s"
        return out

    low = w.get("trust", 1.0) < LOW_TRUST
    k_dz = LOW_TRUST_DZ if low else 1.0

    def ok(rule):
        if dz is None:
            return w["r"] >= rule["r"] and w["p_false"] < min(rule["p"], SINGLE_GRID_P)
        return w["r"] >= rule["r"] and w["p_false"] < rule["p"] and dz >= rule["dz"] * k_dz
    if ok(DECISIVE) and not low:
        out["decision"] = "decisive"
    elif ok(LIKELY):
        out["decision"] = "likely"
    if out["decision"] == "abstain" and dur >= 2 * SEG_S and len(refs) > 1:
        seg = segment_race(tr, refs, start, end, common)
        out["segments"] = seg
        if seg["winner"] and seg["agree"] >= 2 and seg["against"] == 0:
            out["decision"] = "likely"
            out["winner"] = seg["winner"]
            name = G.GRIDS[seg["winner"]]["name"]
            out["reason"] = (f"whole clip does not line up in one piece (stream stalls or edits?), but {seg['agree']} separate "
                             f"{SEG_S:.0f} s pieces each pick {name} at consistent times and none picks another grid")
            return out
    if out["decision"] != "abstain":
        out["winner"] = w["grid"]
        out["reason"] = (f"{w['name']} r={w['r']:.2f}" + (f", {margin:.2f} ahead of {rows[1]['name']} (Fisher-z margin {dz:.2f})" if margin is not None else "")
                         + f", false-alarm p={w['p_false']:.1g}")
        if low:
            out["reason"] += (". The winning log is a low-trust source (" + w["source"] + "), so the answer is capped at "
                              "'likely'")
        if w.get("tz_shift_h"):
            out["reason"] += f". Best fit needed a {w['tz_shift_h']:+.0f} h clock shift on the Pigott log"
        if w["grid"] in shifts_of:
            # A whole-hour error in the log's clock looks exactly like a whole-hour error in the time, so when the
            # search window is wider than an hour the grid answer stands but the time is only known modulo the shifts.
            used = w.get("tz_shift_h") or 0.0
            alts = sorted({used - s for s in shifts_of[w["grid"]]} - {0.0})
            out["time_ambiguity_h"] = alts
            out["reason"] += (". This log's clock offset is inferred, not known, so the matched time could be off by "
                              + ", ".join(f"{a:+.0f} h" for a in alts))
        if margin is None:
            out["reason"] += ". Only one grid could be checked at this time, so the others are not ruled out."
            if out["decision"] == "decisive":
                out["decision"] = "likely"
        elif w.get("nominal") != nominal:
            out["reason"] += f". Warning: the winner is a {w['nominal']} Hz grid but the hum is {nominal} Hz"
    else:
        out["reason"] = (f"no grid stands out (best {w['name']} r={w['r']:.2f}"
                         + (f", margin {margin:.2f}" if margin is not None else "") + f", p={w['p_false']:.1g})")
    return out


def public(race):
    return {k: v for k, v in race.items() if not k.startswith("_")}
