"""Dark 'terminal' style PNGs for the ENF tab and CLI reports."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy import signal  # noqa: E402

from .extract import downsample, work_rate  # noqa: E402

BG, FG, GRID, ACC, ACC2, WARN = "#05080a", "#9cffb0", "#16332a", "#39ff88", "#36c6ff", "#ffb347"


def _style(fig, axes):
    fig.patch.set_facecolor(BG)
    for ax in np.atleast_1d(axes):
        ax.set_facecolor(BG)
        ax.tick_params(colors=FG, labelsize=8)
        for s in ax.spines.values():
            s.set_color(GRID)
        ax.grid(color=GRID, lw=0.5)
        ax.xaxis.label.set_color(FG); ax.yaxis.label.set_color(FG); ax.title.set_color(ACC)
        ax.title.set_fontfamily("monospace"); ax.title.set_fontsize(9)


def _png(fig):
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=100, facecolor=BG)
    plt.close(fig)
    return b.getvalue()


def harmonic_spectrogram(x, sr, nominal, ks=(1, 2, 3, 4), trace=None, frame_s=8.0, max_s=None):
    xd = downsample(x if max_s is None else x[: int(max_s * sr)], sr)
    fs = work_rate(sr)
    ks = [k for k in ks if k * nominal < fs / 2 - 10]
    nper = int(frame_s * fs)
    f, t, S = signal.spectrogram(xd, fs, window="hann", nperseg=nper, noverlap=nper - fs, nfft=4 * nper)
    fig, axes = plt.subplots(len(ks), 1, figsize=(11, 1.6 * len(ks) + 0.6), sharex=True)
    _style(fig, axes)
    for ax, k in zip(np.atleast_1d(axes), ks):
        fc = k * nominal
        m = (f > fc - 0.8 * k - 0.4) & (f < fc + 0.8 * k + 0.4)
        db = 10 * np.log10(S[m] + 1e-20)
        db -= np.median(db, axis=0, keepdims=True)
        ax.pcolormesh(t, f[m], db, shading="auto", cmap="viridis", vmin=0, vmax=np.percentile(db, 99.5))
        if trace is not None:
            ax.plot(trace.t, trace.f * k, color=WARN, lw=0.6, alpha=0.8)
        ax.set_ylabel(f"{fc} Hz", fontsize=8)
    np.atleast_1d(axes)[0].set_title(f"hum harmonics of {nominal} Hz (raw audio)  orange = ENF estimate x k")
    np.atleast_1d(axes)[-1].set_xlabel("seconds from start of file")
    fig.tight_layout()
    return _png(fig)


def trace_plot(trace):
    fig, ax = plt.subplots(figsize=(11, 3))
    _style(fig, ax)
    for k, v in trace.per_harmonic.items():
        if k in trace.harmonics_used:
            continue
        ax.plot(trace.t, v, lw=0.3, alpha=0.25, color=GRID)
    ax.plot(trace.t, trace.f, color=ACC, lw=1.0, label=f"ENF (harmonics {trace.harmonics_used})")
    ok = trace.f[np.isfinite(trace.f)]
    if len(ok):
        lo, hi = np.percentile(ok, 1), np.percentile(ok, 99)
        pad = max(0.01, (hi - lo) * 0.4)
        ax.set_ylim(lo - pad, hi + pad)
    ax.axhline(trace.nominal, color=WARN, lw=0.6, ls="--")
    ax.set_ylabel("Hz"); ax.set_xlabel("seconds from start of file")
    ax.set_title("ENF trace (fundamental units)")
    ax.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=8, loc="upper right")
    fig.tight_layout()
    return _png(fig)


def overlay_plot(match):
    ov = match["overlay"]
    t = np.array(ov["t"], float)
    rec = np.array([np.nan if v is None else v for v in ov["rec"]], float)
    ref = np.array([np.nan if v is None else v for v in ov["ref"]], float)
    fig, axes = plt.subplots(2, 1, figsize=(11, 5.2), gridspec_kw=dict(height_ratios=[3, 2]))
    _style(fig, axes)
    ax = axes[0]
    n = min(len(t), len(ref))
    ax.plot(t[:n], ref[:n], color=ACC2, lw=1.4, label=f"reference: {match['reference']['name']}")
    ax.plot(t[:len(rec)], rec, color=ACC, lw=0.8, label="recording (offset removed)")
    ax.set_title(f"best fit {match['start_label']}   r={match['ncc']}   {match['label'].upper()}")
    ax.set_ylabel("Hz"); ax.set_xlabel("seconds from start of file")
    ax.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=8)
    ax = axes[1]
    c = match["curve"]
    ct = np.array(c["t"], float)
    cv = np.array([np.nan if v is None else v for v in c["ncc"]], float)
    if match["relative"]:
        x = ct / 3600; ax.set_xlabel("hours into reference")
        bx = match["start_time"] / 3600
    else:
        x = (ct - ct[0]) / 3600; ax.set_xlabel(f"hours after {match['reference']['start']}")
        bx = (match["start_time"] - ct[0]) / 3600
    ax.plot(x, cv, color=FG, lw=0.6)
    ax.axvline(bx, color=WARN, lw=1)
    ax.set_ylabel("match r"); ax.set_title("match score across the search window (peak = best time)")
    fig.tight_layout()
    return _png(fig)


def race_plot(race):
    """'Grid race' chart: per-grid best correlation (bars) and correlation across the time window."""
    rows = race.get("_rows") or []
    nc = race.get("not_covered") or []
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), gridspec_kw=dict(width_ratios=[1, 1.6]))
    _style(fig, axes)
    ax = axes[0]
    names = [r["name"] for r in rows] + [g["name"] for g in nc]
    vals = [max(r["r"], -1) for r in rows] + [0] * len(nc)
    win = race.get("winner")
    cols = [(ACC if r["grid"] == win else (ACC2 if i == 0 and not win else GRID if r["r"] < 0.3 else FG))
            for i, r in enumerate(rows)] + ["#333333"] * len(nc)
    y = np.arange(len(names))[::-1]
    ax.barh(y, vals, color=cols, edgecolor=GRID)
    for yy, r in zip(y, rows):
        ax.text(max(r["r"], -1) + 0.02 if r["r"] > -0.9 else -0.98, yy, f"r={r['r']:.2f}  {r['offset_mhz']:+.0f} mHz",
                va="center", fontsize=7, color=FG, family="monospace")
    for yy in y[len(rows):]:
        ax.text(0.02, yy, "no free reference for this time", va="center", fontsize=7, color="#888888", family="monospace")
    from .race import LIKELY, DECISIVE
    ax.axvline(LIKELY["r"], color=WARN, lw=0.8, ls="--")
    ax.axvline(DECISIVE["r"], color=WARN, lw=0.8, ls=":")
    ax.set_yticks(y); ax.set_yticklabels(names, fontsize=8, color=FG)
    ax.set_xlim(-1, 1.25); ax.set_xlabel("best level-gated correlation in window")
    dec = race.get("decision", "abstain")
    ax.set_title(f"GRID RACE: {(win or 'no winner')} ({dec})")
    ax = axes[1]
    palette = [ACC, ACC2, WARN, "#ff6b9a", "#c38bff", "#ffffff"]
    for i, r in enumerate(rows):
        c = r.get("curve") or {}
        t = np.array(c.get("t") or [], float)
        v = np.array([np.nan if x is None else x for x in (c.get("ncc") or [])], float)
        if len(t):
            ax.plot((t - race["window"][0]) / 60, v, lw=0.8 if r["grid"] != win else 1.4,
                    color=palette[i % len(palette)], label=r["name"], alpha=1 if r["grid"] == win else 0.7)
    ax.set_ylim(-1, 1.05)
    ax.set_xlabel("minutes after window start (candidate recording start)")
    ax.set_ylabel("r")
    ax.set_title("r vs candidate start, per grid (-1 = hum level never fits that grid)")
    if rows:
        ax.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=7, loc="lower right")
    fig.tight_layout()
    return _png(fig)


def video_plot(vres, atr=None, agree=None, title_extra=""):
    """Light-flicker ENF from the picture, beside the audio ENF: traces (mHz from nominal), the read-out
    search (rolling shutter) and audio-vs-picture agreement per piece."""
    vtr = vres.get("_trace_any")
    fig, axes = plt.subplots(3, 1, figsize=(11, 7.4), gridspec_kw=dict(height_ratios=[3, 1.6, 1.4]))
    _style(fig, axes)
    ax = axes[0]
    if vtr is not None and len(vtr.t):
        ax.plot(vtr.t, (vtr.f - vtr.nominal) * 1000, color=WARN, lw=1.2,
                label=f"picture: light flicker / 2 ({vres.get('path_used')}, {vtr.frame_s:.0f} s window)")
    if atr is not None and len(atr.t):
        k = int(round(max(atr.frame_s, vtr.frame_s if vtr is not None else 1)))
        f = atr.f.copy()
        ok = np.isfinite(f)
        sm = np.convolve(np.nan_to_num(f - atr.nominal), np.ones(k) / k, "same") * 1000
        cnt = np.convolve(ok.astype(float), np.ones(k) / k, "same")
        sm = np.where(cnt > 0.6, sm / np.maximum(cnt, 1e-9), np.nan)
        ax.plot(atr.t, sm, color=ACC, lw=0.9, alpha=0.9, label=f"audio hum (harmonics {atr.harmonics_used}, smoothed {k} s)")
    ax.axhline(0, color=GRID, lw=0.8)
    ax.set_ylabel("mHz from nominal"); ax.set_xlabel("seconds from start of file")
    pres = (vres.get("presence") or {}).get("verdict", "?")
    ttl = f"VIDEO FLICKER ENF: {pres.upper()}"
    if agree:
        ttl += f"   audio vs picture: {agree.get('verdict')} (r={agree.get('r_best')}, lag {agree.get('best_lag_s')} s)"
    ax.set_title(ttl + title_extra)
    ax.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=8, loc="upper right")
    ax = axes[1]
    rs = vres.get("readout_search")
    if rs:
        ax.plot(rs["readout_ms_grid"], rs["power_db"], color=ACC2, lw=1)
        if vres.get("readout_ms"):
            ax.axvline(vres["readout_ms"] if vres.get("nominal") == 60 else rs["readout_ms"]["60"], color=WARN, lw=1)
        ax.set_xlabel("read-out time (ms, for a 60 Hz grid; x 1.2 for 50 Hz)"); ax.set_ylabel("band energy dB")
        ax.set_title(f"rolling-shutter read-out search: best {rs['readout_ms']['60']} ms (60 Hz) / "
                     f"{rs['readout_ms']['50']} ms (50 Hz), contrast {rs['contrast_db']} dB")
    else:
        ax.text(0.5, 0.5, f"read-out time {vres.get('readout_ms')} ms ({vres.get('readout_source')})"
                if vres.get("readout_ms") else "no read-out search", ha="center", va="center", color=FG,
                transform=ax.transAxes, family="monospace")
        ax.set_title("rolling-shutter read-out")
    ax = axes[2]
    pcs = (agree or {}).get("pieces") or []
    if pcs:
        x = [p["t"] / 60 for p in pcs]
        v = [np.nan if p["r"] is None else p["r"] for p in pcs]
        cols = [ACC if (np.isfinite(r) and r >= 0.6) else (WARN if np.isfinite(r) and r >= 0.2 else "#ff6b6b") for r in v]
        ax.bar(x, np.nan_to_num(v), width=0.8 * agree.get("piece_s", 120) / 60, color=cols, edgecolor=GRID, align="edge")
        ax.set_ylim(-1, 1); ax.axhline(0.6, color=WARN, lw=0.6, ls="--")
        ax.set_xlabel(f"minutes ({agree.get('piece_s', 120) // 60}-minute pieces)"); ax.set_ylabel("r audio vs picture")
        ax.set_title("agreement per piece (green agrees, red disagrees: a splice or replaced section shows up here)")
    else:
        ax.text(0.5, 0.5, "no audio-vs-picture comparison (need both traces)", ha="center", va="center", color=FG,
                transform=ax.transAxes, family="monospace")
    fig.tight_layout()
    return _png(fig)
