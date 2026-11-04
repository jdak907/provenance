"""Figures and a Markdown report for a search run."""
from __future__ import annotations

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .physics import naive_frequency, straight_line_curve  # noqa: E402
from .search import SearchResult, model_curves  # noqa: E402


def _crop(spec, t0, t1, f0, f1):
    tm = (spec.t >= t0) & (spec.t <= t1)
    fm = (spec.f >= f0) & (spec.f <= f1)
    return spec.t[tm], spec.f[fm], spec.bright[np.ix_(fm, tm)]


def plot_events(spec, events, ridges, path):
    n = len(events)
    fig, axes = plt.subplots(1, n + 1, figsize=(6 * (n + 1), 4.2),
                             gridspec_kw={"width_ratios": [2] + [1] * n})
    ax = axes[0]
    ax.pcolormesh(spec.t, spec.f, spec.bright, vmin=0, vmax=6, shading="auto", cmap="magma")
    ax.set_ylim(spec.f[0], min(spec.f[-1], 300))
    ax.set_title("Whole clip, zoomed to the low band")
    ax.set_xlabel("seconds into audio"); ax.set_ylabel("Hz")
    for e in events:
        ax.axvspan(e.t_start, e.t_end, color="cyan", alpha=0.12)
        ax.text(e.t_start, spec.f[0] + 5, e.name, color="cyan")
    for k, (e, r) in enumerate(zip(events, ridges)):
        ax = axes[k + 1]
        hi = min(spec.f[-1], 1.6 * e.f0 * 343 / (343 - e.speed_range[1]))
        t, f, B = _crop(spec, e.t_start, e.t_end, max(spec.f[0], 0.5 * e.f0), hi)
        ax.pcolormesh(t, f, B, vmin=0, vmax=6, shading="auto", cmap="magma")
        ax.plot(r[0], r[1], ".", ms=1.5, color="cyan", label="traced ridge")
        tt = np.linspace(e.t_start, e.t_end, 400)
        ax.plot(tt, straight_line_curve(tt, e.f0, e.speed, e.slant_cpa, e.t_cpa), "w--", lw=1,
                label=f"straight-line fit: {e.speed:.0f} m/s, {e.slant_cpa:.0f} m")
        ax.set_title(f"{e.name}: base pitch {e.f0:.1f} Hz")
        ax.legend(loc="upper right", fontsize=7)
        ax.set_xlabel("seconds into audio")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def plot_funnel(res: SearchResult, path):
    names = [s[0] for s in res.stages]
    vals = [max(1, s[1]) for s in res.stages]
    fig, ax = plt.subplots(figsize=(9, 0.45 * len(names) + 1))
    ax.barh(range(len(names))[::-1], vals, color="#3b82f6")
    ax.set_yticks(range(len(names))[::-1]); ax.set_yticklabels(names, fontsize=8)
    ax.set_xscale("log"); ax.set_xlabel("count (log scale)")
    for i, v in enumerate(vals):
        ax.text(v, len(names) - 1 - i, f" {v:,}", va="center", fontsize=8)
    ax.set_title("Search funnel")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def plot_scores(res: SearchResult, path):
    c = res.candidates
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    if res.mode == "two-event":
        ax.scatter(c["s1"], c["s2"], s=4, c="0.75", label="all candidates")
        b = [r["idx"] for r in res.ranking]
        ax.scatter(c["s1"][b], c["s2"][b], s=22, c="#2563eb", label="best per flight pair")
        ax.scatter(c["s1"][b[0]], c["s2"][b[0]], s=120, marker="*", c="#dc2626", label="winner")
        ax.set_xlabel("event 1 score"); ax.set_ylabel("event 2 score (locked)")
    else:
        b = [r["idx"] for r in res.ranking]
        ax.hist(c["s1"], bins=60, color="0.7", label="all candidates")
        ax.hist(c["s1"][b], bins=60, color="#2563eb", alpha=0.8, label="best per flight")
        ax.axvline(c["s1"][b[0]], color="#dc2626", label="winner")
        ax.set_xlabel("score (right is better)")
    ax.legend(fontsize=8); ax.set_title("Candidate scores")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def plot_map(res: SearchResult, path, truth=None):
    c = res.candidates
    f = res.frame
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    ax = axes[0]
    sc = ax.scatter(c["x"] / 1000, c["y"] / 1000, c=c["total"], s=6, cmap="viridis")
    plt.colorbar(sc, ax=ax, label="score")
    best = res.ranking[0]
    for key, col in (("fa", "#f97316"), ("fb", "#ec4899")):
        fi_idx = int(c[key][best["idx"]])
        if fi_idx < 0:
            continue
        fi = res.flight_index[fi_idx]
        ax.plot(fi.P[:, 0] / 1000, fi.P[:, 1] / 1000, color=col, lw=1,
                label=f"{fi.track.callsign or fi.track.flight_id} ({fi.track.typecode or '?'})")
    bx, by = f.to_xy(best["lat"], best["lon"])
    ax.plot(bx / 1000, by / 1000, "r*", ms=14, label="best candidate")
    if truth:
        tx, ty = f.to_xy(truth["observer_lat"], truth["observer_lon"])
        ax.plot(tx / 1000, ty / 1000, "kx", ms=12, mew=2, label="hidden truth")
    lim = np.array(f.to_xy(res.params.bbox[0], res.params.bbox[2])) / 1000
    lim2 = np.array(f.to_xy(res.params.bbox[1], res.params.bbox[3])) / 1000
    ax.set_xlim(lim[0], lim2[0]); ax.set_ylim(lim[1], lim2[1])
    ax.set_aspect("equal"); ax.set_xlabel("km east"); ax.set_ylabel("km north")
    ax.legend(fontsize=7, loc="lower left"); ax.set_title("Scored candidates in the search box")
    ax = axes[1]
    fn = res.fine
    Z = fn["total"].reshape(fn["shape"])
    X = fn["x"].reshape(fn["shape"]); Y = fn["y"].reshape(fn["shape"])
    cx, cy = X.mean(), Y.mean()
    im = ax.pcolormesh(X - cx, Y - cy, Z, shading="auto", cmap="inferno")
    plt.colorbar(im, ax=ax, label="locked score")
    fx, fy = f.to_xy(fn["best_lat"], fn["best_lon"])
    ax.plot(fx - cx, fy - cy, "c*", ms=14, label="fine best")
    if truth:
        ax.plot(tx - cx, ty - cy, "wx", ms=12, mew=2, label="hidden truth")
    ax.set_aspect("equal"); ax.set_xlabel("metres"); ax.set_ylabel("metres")
    ax.legend(fontsize=7); ax.set_title(f"Fine {res.params.fine_m:.0f} m pass, winning flight(s) only")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def plot_best_fit(res: SearchResult, spec, events, path, dem):
    """Spectrogram crops with the modelled curve of the top two flight pairs overlaid."""
    from .search import _ground
    c, p = res.candidates, res.params
    n_ev = len(events)
    picks = [r["idx"] for r in res.ranking[:2]]
    fig, axes = plt.subplots(len(picks), n_ev, figsize=(6.5 * n_ev, 3.8 * len(picks)), squeeze=False)
    hop = spec.hop
    for row, i in enumerate(picks):
        obs = np.array([[c["x"][i], c["y"][i],
                         float(_ground(res.frame, dem, c["x"][i], c["y"][i])) + p.obs_height_m]])
        base = None
        td1 = None
        for k, e in enumerate(events):
            fidx = int(c["fa"][i] if k == 0 else c["fb"][i])
            fi = res.flight_index[fidx]
            half = (e.t_end - e.t_start)
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
            ax = axes[row, k]
            hi = min(spec.f[-1], 1.6 * e.f0 * 343 / (343 - e.speed_range[1]))
            t, f, B = _crop(spec, e.t_start, e.t_end, max(spec.f[0], 0.5 * e.f0), hi)
            ax.pcolormesh(t, f, B, vmin=0, vmax=6, shading="auto", cmap="magma")
            ax.plot(place + tau, kk * fm[0], color="cyan", lw=1.2, alpha=0.8)
            ax.set_xlim(e.t_start, e.t_end)
            sc = c["s1"][i] if k == 0 else c["s2"][i]
            ax.set_title(f"rank {row + 1}, {e.name}: {fi.track.callsign or fi.track.flight_id}, "
                         f"score {sc:.2f}", fontsize=9)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def plot_naive_vs_correct(res: SearchResult, spec, events, path, dem):
    """The video's key warning: using radial velocity at reception time gives a WRONG curve."""
    from .search import _ground
    c, p = res.candidates, res.params
    i = res.ranking[0]["idx"]
    e = events[0]
    fi = res.flight_index[int(c["fa"][i])]
    obs = np.array([c["x"][i], c["y"][i],
                    float(_ground(res.frame, dem, c["x"][i], c["y"][i])) + p.obs_height_m])
    hop = spec.hop
    T = int(2 * (e.t_end - e.t_start) / hop) | 1
    tau = (np.arange(T) - T // 2) * hop
    td, fm = model_curves(fi, obs[None], e.f0, tau, p, res.epoch)
    t_rx = td[0] + res.epoch + tau
    fn = naive_frequency(fi.model, obs[None].repeat(T, 0), t_rx, e.f0, p.c)
    base = (e.t_cpa if p.known_clip_start is None else td[0] + res.epoch - p.known_clip_start)
    base += c["dt1"][i]
    k = c["k1"][i]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    hi = min(spec.f[-1], 1.6 * e.f0 * 343 / (343 - e.speed_range[1]))
    t, f, B = _crop(spec, e.t_start, e.t_end, max(spec.f[0], 0.5 * e.f0), hi)
    ax.pcolormesh(t, f, B, vmin=0, vmax=6, shading="auto", cmap="gray_r")
    ax.plot(base + tau, k * fm[0], color="#16a34a", lw=1.6, label="correct: velocity at emission time")
    ax.plot(base + tau, k * fn, color="#dc2626", lw=1.2, ls="--",
            label="wrong: velocity at reception time")
    ax.set_xlim(e.t_start, e.t_end)
    ax.legend(fontsize=8); ax.set_xlabel("seconds into audio"); ax.set_ylabel("Hz")
    ax.set_title("Same flight, same listener: emission-time model vs naive model")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def _dist_m(frame, a, b):
    ax, ay = frame.to_xy(*a)
    bx, by = frame.to_xy(*b)
    return float(np.hypot(ax - bx, ay - by))


def write_report(out_dir, res: SearchResult, spec, events, ridges, dem, inputs: dict, truth=None):
    os.makedirs(out_dir, exist_ok=True)
    figs = {}
    plot_events(spec, events, ridges, os.path.join(out_dir, "fig_events.png")); figs["events"] = "fig_events.png"
    plot_funnel(res, os.path.join(out_dir, "fig_funnel.png"))
    if res.ranking:
        plot_scores(res, os.path.join(out_dir, "fig_scores.png"))
        plot_map(res, os.path.join(out_dir, "fig_map.png"), truth)
        plot_best_fit(res, spec, events, os.path.join(out_dir, "fig_best_fit.png"), dem)
        plot_naive_vs_correct(res, spec, events, os.path.join(out_dir, "fig_naive_vs_correct.png"), dem)

    L = []
    L.append(f"# Flyover geolocation report ({res.mode} mode)\n")
    L.append("## Inputs\n")
    for k, v in inputs.items():
        L.append(f"- {k}: {v}")
    L.append("\n## What the audio says\n")
    L.append("| Event | Window (s) | Base pitch (Hz) | Speed (m/s) | Closest slant distance (m) | "
             "Heard CPA (s) | Fit error (Hz) |")
    L.append("|---|---|---|---|---|---|---|")
    for e in events:
        L.append(f"| {e.name} | {e.t_start:.0f} to {e.t_end:.0f} | {e.f0:.1f} | {e.speed:.0f} "
                 f"({e.speed_range[0]:.0f} to {e.speed_range[1]:.0f}) | {e.slant_cpa:.0f} "
                 f"({e.slant_range[0]:.0f} to {e.slant_range[1]:.0f}) | {e.t_cpa:.1f} | {e.rms_hz:.1f} |")
    if len(events) > 1:
        L.append(f"\nGap between the two heard closest approaches: {events[1].t_cpa - events[0].t_cpa:.1f} seconds.")
    L.append("\n![events](fig_events.png)\n")
    L.append("## Search funnel\n")
    L.append("| Stage | Count |\n|---|---|")
    for n, v in res.stages:
        L.append(f"| {n} | {v:,} |")
    L.append("\n![funnel](fig_funnel.png)\n")
    if not res.ranking:
        L.append("No candidate survived. Widen the search box, the time window, or the ranges.\n")
    else:
        b = res.best
        L.append("## Result\n")
        L.append(f"- Best location (fine pass): {b['fine_lat']:.5f}, {b['fine_lon']:.5f}")
        L.append(f"- Map link: https://www.google.com/maps?q={b['fine_lat']:.5f},{b['fine_lon']:.5f}")
        L.append(f"- Flights matched: {b['callsign1'] or b['flight1']} ({b['type1'] or 'type unknown'})"
                 + (f" and {b['callsign2'] or b['flight2']} ({b['type2'] or 'type unknown'})" if b['flight2'] else ""))
        L.append(f"- Combined score {b['total']:.2f}; lead over the next flight pair "
                 f"{b.get('margin_over_second', float('nan')):.2f}")
        conf = "high" if b.get("margin_over_second", 0) > 0.5 else (
            "medium" if b.get("margin_over_second", 0) > 0.15 else "low (near tie, check the runner-up)")
        L.append(f"- Confidence: {conf}")
        close_alts = [a for a in res.alternatives if a["score_ratio"] > 0.9]
        if close_alts:
            L.append("- Ambiguity: other spots fit the same flight(s) nearly as well. With one flyover, a "
                     "point mirrored across the flight path hears almost the same curve. Check these too:")
            for a in close_alts:
                L.append(f"  - {a['lat']:.5f}, {a['lon']:.5f}: {a['dist_from_best_m']:.0f} m away, "
                         f"score {a['total']:.2f} ({100 * a['score_ratio']:.0f} percent of the best)")
        if truth:
            err = _dist_m(res.frame, (b["fine_lat"], b["fine_lon"]),
                          (truth["observer_lat"], truth["observer_lon"]))
            err_c = _dist_m(res.frame, (b["lat"], b["lon"]),
                            (truth["observer_lat"], truth["observer_lon"]))
            L.append(f"- Check against hidden truth: fine-pass error {err:.0f} m "
                     f"(100 m grid winner was {err_c:.0f} m off).")
            for a in close_alts:
                e_a = _dist_m(res.frame, (a["lat"], a["lon"]), (truth["observer_lat"], truth["observer_lon"]))
                L.append(f"  - listed alternative at {a['lat']:.5f}, {a['lon']:.5f} is {e_a:.0f} m from truth")
        L.append("\n### Top flight pairs\n")
        L.append("| Rank | Lat | Lon | Event 1 | Event 2 | Total | Flights |")
        L.append("|---|---|---|---|---|---|---|")
        for r in res.ranking[:10]:
            L.append(f"| {r['rank']} | {r['lat']:.5f} | {r['lon']:.5f} | {r['s1']:.2f} | {r['s2']:.2f} | "
                     f"{r['total']:.2f} | {r['callsign1'] or r['flight1']}"
                     + (f" + {r['callsign2'] or r['flight2']}" if r['flight2'] else "") + " |")
        L.append("\n![scores](fig_scores.png)\n\n![map](fig_map.png)\n\n![fit](fig_best_fit.png)\n")
        L.append("![naive](fig_naive_vs_correct.png)\n")
    L.append("## Timing\n")
    L.append(", ".join(f"{k} {v}" for k, v in res.timings.items()))
    L.append("\n## Caveats\n")
    L.append("- Wind, temperature (speed of sound), barometric versus geometric altitude, and "
             "ADS-B gaps all bend the curves. Treat the result as a lead to check, not proof.")
    L.append("- Use only on recordings you own or are authorised to analyse.")
    open(os.path.join(out_dir, "report.md"), "w").write("\n".join(L) + "\n")
    summary = dict(mode=res.mode, best=res.best, stages=res.stages, timings=res.timings,
                   alternatives=[{k: v for k, v in a.items() if k != "idx"} for a in res.alternatives],
                   ranking=[{k: v for k, v in r.items() if k != "idx"} for r in res.ranking[:10]])
    if truth and res.ranking:
        summary["error_m"] = _dist_m(res.frame, (res.best["fine_lat"], res.best["fine_lon"]),
                                     (truth["observer_lat"], truth["observer_lon"]))
        cands = [summary["error_m"]] + [
            _dist_m(res.frame, (a["lat"], a["lon"]), (truth["observer_lat"], truth["observer_lon"]))
            for a in res.alternatives if a["score_ratio"] > 0.9]
        summary["error_best_or_close_alternative_m"] = float(min(cands))
    json.dump(summary, open(os.path.join(out_dir, "result.json"), "w"), indent=2, default=float)
    return summary
