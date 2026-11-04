"""Command line interface: provenance {demo,simulate,measure,locate,audit}."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import numpy as np


def _t(s):
    try:
        return float(s)
    except ValueError:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.timestamp()


def _windows(s):
    out = []
    for part in s.split(","):
        a, b = part.split("-")
        out.append((float(a), float(b)))
    return out


def do_measure(audio, events=None, fmin=30.0, fmax=250.0, max_events=2, log=print,
               steady_window_s=60.0):
    from . import measure, spectro
    sr, x = spectro.load_audio(audio)
    spec = spectro.compute(x, sr, fmin=fmin, fmax=max(fmax, 300.0), steady_window_s=steady_window_s)
    wins = events or spectro.detect_events(spec)
    if not wins:
        wins = [(spec.t[0], spec.t[-1])]
        log("No event auto-detected; using the whole clip as one event.")
    if len(wins) > max_events:
        # keep the strongest ones, in time order
        strength = [spec.bright[:, (spec.t >= a) & (spec.t <= b)].max(0).mean() for a, b in wins]
        keep = sorted(np.argsort(strength)[::-1][:max_events])
        wins = [wins[i] for i in keep]
    ems, ridges = [], []
    for i, (a, b) in enumerate(wins):
        r = spectro.trace_ridge(spec, a, b, fmin, fmax)
        ems.append(measure.fit_event(spec, a, b, f"event{i + 1}", fmin, fmax, ridge=r))
        ridges.append(r)
        log(f"{ems[-1].name}: {a:.0f}-{b:.0f} s, f0 {ems[-1].f0:.1f} Hz, speed {ems[-1].speed:.0f} m/s "
            f"[{ems[-1].speed_range[0]:.0f}-{ems[-1].speed_range[1]:.0f}], slant {ems[-1].slant_cpa:.0f} m "
            f"[{ems[-1].slant_range[0]:.0f}-{ems[-1].slant_range[1]:.0f}], CPA heard at {ems[-1].t_cpa:.1f} s")
    return spec, ems, ridges, len(x) / sr


def do_locate(audio, adsb_path, dem_path, bbox, window, out_dir, events=None, clip_start=None,
              truth_path=None, grid_m=200.0, obs_height=2.0, c=343.0, fmin=30.0, fmax=250.0,
              max_events=2, max_gap_s=60.0, steady_window_s=60.0, search_overrides=None, log=print):
    from . import adsb, geo, report, search
    spec, ems, ridges, dur = do_measure(audio, events, fmin, fmax, max_events, log,
                                        steady_window_s=steady_window_s)
    if clip_start is not None:
        ems, ridges = ems[:max_events], ridges[:max_events]
    tracks = adsb.load_tracks(adsb_path, max_gap_s=max_gap_s)
    log(f"loaded {len(tracks)} ADS-B track segments")
    if dem_path == "auto":
        from .dem_fetch import fetch_dem
        os.makedirs(out_dir, exist_ok=True)
        dem = fetch_dem(bbox, log=log)
        dem_path = os.path.join(out_dir, "dem_auto.npz")
        dem.save(dem_path)
    else:
        dem = geo.DEM.load(dem_path) if dem_path else geo.DEM.flat(0.0)
    p = search.SearchParams(bbox=tuple(bbox), t_window=tuple(window), grid_m=grid_m,
                            obs_height_m=obs_height, c=c, known_clip_start=clip_start, log=log,
                            **(search_overrides or {}))
    res = search.locate(tracks, dem, spec, ems, ridges, dur, p)
    res.spec, res.events, res.ridges, res.dem = spec, ems, ridges, dem  # for the GUI
    truth = json.load(open(truth_path)) if truth_path else None
    inputs = {"audio": audio, "ADS-B": adsb_path, "DEM": dem_path or "flat 0 m",
              "search box (lat/lon)": ", ".join(f"{v:.4f}" for v in bbox),
              "time window (UTC)": " to ".join(dt.datetime.fromtimestamp(w, dt.timezone.utc)
                                               .strftime("%Y-%m-%d %H:%M") for w in window),
              "recording clock": (dt.datetime.fromtimestamp(clip_start, dt.timezone.utc).isoformat()
                                  if clip_start else "unknown")}
    os.makedirs(out_dir, exist_ok=True)
    json.dump([e.to_dict() for e in ems], open(os.path.join(out_dir, "measurements.json"), "w"), indent=2)
    summary = report.write_report(out_dir, res, spec, ems, ridges, dem, inputs, truth)
    if res.ranking:
        b = res.best
        log(f"BEST: {b['fine_lat']:.5f}, {b['fine_lon']:.5f}  (flights {b['flight1']} {b['flight2']})")
    if truth and "error_m" in summary:
        log(f"error vs hidden truth: {summary['error_m']:.0f} m")
    log(f"report: {os.path.join(out_dir, 'report.md')}")
    return res, summary


def do_demo(out="demo_run", seed=7, log=print):
    from .simulate import build_scene
    data = os.path.join(out, "data")
    log(f"== 1. simulating scene (seed {seed}) into {data}")
    truth, sc = build_scene(data, seed=seed)
    tp = os.path.join(data, "truth_HIDDEN.json")
    log("== 2. two-event search: unknown time (any time in the window), unknown place (whole box)")
    _, s1 = do_locate(os.path.join(data, "recording.wav"), os.path.join(data, "adsb.csv"),
                      os.path.join(data, "dem.npz"), sc["bbox"], sc["search_window_unix"],
                      os.path.join(out, "two_event"), truth_path=tp, log=log)
    log("== 3. one-minute clip, one faint flyover, known recording time")
    _, s2 = do_locate(os.path.join(data, "one_minute.wav"), os.path.join(data, "adsb.csv"),
                      os.path.join(data, "dem.npz"), sc["bbox"], sc["search_window_unix"],
                      os.path.join(out, "one_minute"), clip_start=sc["one_minute_start_unix"],
                      truth_path=tp, max_events=1, log=log)
    e1 = s1.get("error_m", 1e9)
    e2 = s2.get("error_m", 1e9)
    e2a = s2.get("error_best_or_close_alternative_m", 1e9)
    ok = e1 < 150
    note = ("" if e2 < 150 else
            " (truth is the listed mirror-image alternative; one flyover is ambiguous)" if e2a < 150 else
            " (one-minute mode missed)")
    log(f"== DEMO {'PASSED' if ok else 'FAILED'}: two-event error {e1:.0f} m (must be under 150 m); "
        f"one-minute error {e2:.0f} m{note}")
    return ok, s1, s2


def do_enf(args):
    from .enf import pipeline as P
    kind = "gb" if args.ref == "gb" else ("none" if args.ref == "none" else "file")
    start, end = P.parse_time(args.start), P.parse_time(args.end)
    res = P.analyze(args.media, kind, None if kind != "file" else args.ref, start, end, args.nominal, log=print,
                    race=not args.no_race, use_meta_time=not args.no_meta_time, video=args.video,
                    readout_ms=args.readout_ms)
    d, m = res["detect"], res["match"]
    if res.get("primary_source") == "video":
        print("\nNO AUDIO TRACK: the results below come from the picture's light flicker.")
    print(f"\nHUM: {res['scan']['note']}  |  ENF: {d['verdict']} (score {d.get('score')})")
    for r in d["reasons"]:
        print("   -", r)
    rc = res.get("race")
    if rc:
        print(f"GRID RACE ({rc.get('window_source')}): {rc['decision'].upper()}"
              + (f" -> {rc['winner']}" if rc.get("winner") else "") + f"  | {rc['reason']}")
        for i, r in enumerate(rc.get("ranking") or [], 1):
            print(f"   {i}. {r['name']:28s} r={r['r']:+.3f}  raw r={r['raw_r']}  level offset {r['offset_mhz']:+.1f} mHz  "
                  f"p_false={r['p_false']:.2g}  best start {r['best_start']}")
        for g in rc.get("not_covered") or []:
            print(f"   -  {g['name']:28s} no free reference for this time ({g['sources']})")
    else:
        print("GRID RACE: not run (no time window: give --start/--end, or the file has no creation_time)")
    print("GRID (statistics, time unknown):", res["grid"]["verdict"])
    print("GRID ANSWER:", res["grid_final"]["name"], f"[{res['grid_final']['method']}, {res['grid_final']['confidence']}]")
    if m:
        print(f"MATCH: {m['start_label']}  r={m['ncc']}  runner-up r={m['second_ncc']}  "
              f"p_false={m['p_false']:.2g}  -> {m['label'].upper()}")
        for w in m["warnings"]:
            print("   !", w)
        print("CONTINUITY:", res["continuity"]["verdict"])
    elif res.get("match_error"):
        print("MATCH: skipped:", res["match_error"])
    v = res.get("video")
    if v:
        print(f"\nVIDEO FLICKER: {v.get('status')}" + (f"  [{v['path_used']}, {v['nominal']} Hz mains" if v.get("path_used") else "")
              + (f", read-out {v['readout_ms']} ms ({v['readout_source']})" if v.get("readout_ms") else "")
              + (f", alias {v['alias_hz']} Hz" if v.get("alias_hz") is not None else "") + ("]" if v.get("path_used") else ""))
        for r in (v.get("presence") or {}).get("reasons", []):
            print("   -", r)
        vr = v.get("race")
        if vr:
            print(f"   VIDEO GRID RACE: {vr['decision'].upper()}" + (f" -> {vr['winner']}" if vr.get("winner") else "")
                  + f"  | {vr['reason']}")
        vm = v.get("match")
        if vm:
            print(f"   VIDEO MATCH: {vm['start_label']}  r={vm['ncc']}  -> {vm['label'].upper()}")
    ag = res.get("av_agreement")
    if ag:
        print(f"AUDIO vs PICTURE: {ag['verdict'].upper()}  r={ag.get('r_best')} at lag {ag.get('best_lag_s')} s, "
              f"offset {ag.get('offset_mhz')} mHz  | {ag.get('hint')}")
        for c in ag.get("cross_checks") or []:
            print("   !", c)
    print("PRIVACY:", res["privacy"]["level"])
    for ln in res["privacy"]["lines"]:
        print("   -", ln)
    if args.out:
        from .enf import plots
        from .enf.media import load_raw
        os.makedirs(args.out, exist_ok=True)
        json.dump(P.public(res), open(os.path.join(args.out, "enf_result.json"), "w"), indent=1, default=str)
        tr = res["_trace_obj"]
        if res.get("primary_source") != "video":
            sr, x, _ = load_raw(args.media)
            open(os.path.join(args.out, "enf_spectrogram.png"), "wb").write(plots.harmonic_spectrogram(x, sr, tr.nominal, trace=tr))
        if tr is not None:
            open(os.path.join(args.out, "enf_trace.png"), "wb").write(plots.trace_plot(tr))
        vres = res.get("_video")
        if vres and vres.get("candidates") is not None:
            open(os.path.join(args.out, "enf_video.png"), "wb").write(
                plots.video_plot(vres, atr=tr if res.get("primary_source") != "video" else None, agree=res.get("_agree")))
            if vres.get("_race") and vres["_race"].get("_rows"):
                open(os.path.join(args.out, "enf_video_grid_race.png"), "wb").write(plots.race_plot(vres["_race"]))
        if m:
            open(os.path.join(args.out, "enf_match.png"), "wb").write(plots.overlay_plot(m))
        if res.get("_race") and res["_race"].get("_rows"):
            open(os.path.join(args.out, "enf_grid_race.png"), "wb").write(plots.race_plot(res["_race"]))
        print("wrote", args.out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="provenance", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="simulate a scene and locate it end to end")
    d.add_argument("--out", default="demo_run"); d.add_argument("--seed", type=int, default=7)

    s = sub.add_parser("simulate", help="write a synthetic scene (ADS-B, DEM, audio, hidden truth)")
    s.add_argument("--out", default="demo_data"); s.add_argument("--seed", type=int, default=7)

    m = sub.add_parser("measure", help="find and measure Doppler flyovers in an audio file")
    m.add_argument("audio"); m.add_argument("--events", type=_windows, help="e.g. 100-220,1030-1150")
    m.add_argument("--fmin", type=float, default=30); m.add_argument("--fmax", type=float, default=250)
    m.add_argument("--out", help="write measurements.json here")

    lo = sub.add_parser("locate", help="search for where the audio was recorded")
    lo.add_argument("--audio", required=True); lo.add_argument("--adsb", required=True)
    lo.add_argument("--dem", help="'auto' (fetch free AWS terrain tiles), .npz (lats, lons, elev), "
                                   ".tif, or .json {height_m}")
    lo.add_argument("--bbox", required=True, help="lat_min,lat_max,lon_min,lon_max")
    lo.add_argument("--start", required=True, help="earliest possible time (ISO or Unix)")
    lo.add_argument("--end", required=True, help="latest possible time (ISO or Unix)")
    lo.add_argument("--clip-start", help="known UTC time of the first audio sample, if known")
    lo.add_argument("--events", type=_windows)
    lo.add_argument("--max-events", type=int, default=2)
    lo.add_argument("--grid", type=float, default=200.0)
    lo.add_argument("--height", type=float, default=2.0, help="microphone height above ground, m")
    lo.add_argument("--temp-c", type=float, help="air temperature, sets the speed of sound")
    lo.add_argument("--fmin", type=float, default=30); lo.add_argument("--fmax", type=float, default=250)
    lo.add_argument("--truth", help="optional truth json to score the answer")
    lo.add_argument("--max-gap", type=float, default=60.0,
                    help="split ADS-B tracks at gaps longer than this (s); use ~120 for sparse feeds")
    lo.add_argument("--out", default="locate_out")

    g = sub.add_parser("gui", help="launch the local web GUI (http://127.0.0.1:8765)")
    g.add_argument("--port", type=int, default=8765)
    g.add_argument("--no-browser", action="store_true")

    a = sub.add_parser("audit", help="privacy check: could this recording be located this way?")
    a.add_argument("audio"); a.add_argument("--test-highpass", type=float)

    e = sub.add_parser("enf", help="mains-hum (ENF) analysis: hum check, timestamp match, grid guess, privacy")
    e.add_argument("media", help="audio or video file (only the raw audio track is analysed)")
    e.add_argument("--ref", default="gb", help="'gb' (built-in NESO 1 s + Elexon 15 s), 'none', or a "
                                              "reference file: CSV (time,frequency), WAV of mains, NPZ")
    e.add_argument("--start", help="earliest possible recording start (ISO UTC or Unix)")
    e.add_argument("--end", help="latest possible recording start (ISO UTC or Unix)")
    e.add_argument("--nominal", type=int, choices=[50, 60], help="force 50 or 60 Hz")
    e.add_argument("--video", choices=["auto", "on", "off"], default="auto",
                   help="light-flicker ENF from the picture: auto (video files), on, off")
    e.add_argument("--readout-ms", type=float, default=None,
                   help="rolling-shutter read-out time in ms (time to read all rows); default: search it")
    e.add_argument("--no-race", action="store_true", help="skip the multi-grid race (GB, CE, Nordic, US logs)")
    e.add_argument("--no-meta-time", action="store_true",
                   help="do not take the race time window from the file's creation_time metadata")
    e.add_argument("--out", help="write enf_result.json and PNG plots here")

    c = sub.add_parser("enf-collect", help="live seismic grid-frequency collector (US West reference), runs on this computer")
    c.add_argument("--minutes", type=float, help="stop after this many minutes (default: run until Ctrl-C)")
    c.add_argument("--out-dir", help="day files go here (default ~/.cache/provenance/enf/us/seismic, where the race looks)")
    c.add_argument("--sdr-config", help="JSON list of OpenWebRX receivers for the optional part-time cross-check")
    c.add_argument("-v", "--verbose", action="store_true")
    rb = sub.add_parser("enf-rebuild", help="rebuild seismic grid-frequency day files from the public FDSN archive")
    rb.add_argument("--grid", default="US-WEST", choices=("US-WEST", "US-TEXAS", "US-EAST"))
    rb.add_argument("--start", help="first UTC day, YYYY-MM-DD")
    rb.add_argument("--end", help="last UTC day (default: same as start)")
    rb.add_argument("--yesterday", action="store_true")
    rb.add_argument("--fill-only", action="store_true", help="keep seconds already collected live; only fill gaps")
    rb.add_argument("--stations", help="comma list of NET.STA.LOC.CHA")
    rb.add_argument("--out-dir")

    args = ap.parse_args(argv)
    if args.cmd == "enf-collect":
        from .enf import seismic_live
        fw = []
        for k in ("minutes", "out_dir", "sdr_config"):
            v = getattr(args, k)
            if v is not None:
                fw += ["--" + k.replace("_", "-"), str(v)]
        return seismic_live.main(fw + (["-v"] if args.verbose else []))
    if args.cmd == "enf-rebuild":
        from .enf import seismic
        fw = ["--grid", args.grid]
        for k in ("start", "end", "stations", "out_dir"):
            v = getattr(args, k)
            if v is not None:
                fw += ["--" + k.replace("_", "-"), str(v)]
        fw += (["--yesterday"] if args.yesterday else []) + (["--fill-only"] if args.fill_only else [])
        return seismic.main(fw)
    if args.cmd == "enf":
        return do_enf(args)
    if args.cmd == "demo":
        ok, *_ = do_demo(args.out, args.seed)
        return 0 if ok else 1
    if args.cmd == "simulate":
        from .simulate import build_scene
        build_scene(args.out, seed=args.seed)
        print(f"wrote {args.out}")
        return 0
    if args.cmd == "measure":
        _, ems, _, _ = do_measure(args.audio, args.events, args.fmin, args.fmax, max_events=10)
        if args.out:
            os.makedirs(args.out, exist_ok=True)
            json.dump([e.to_dict() for e in ems], open(os.path.join(args.out, "measurements.json"), "w"), indent=2)
        return 0
    if args.cmd == "locate":
        from .physics import speed_of_sound
        c = speed_of_sound(args.temp_c) if args.temp_c is not None else 343.0
        bbox = [float(v) for v in args.bbox.split(",")]
        do_locate(args.audio, args.adsb, args.dem, bbox, (_t(args.start), _t(args.end)), args.out,
                  events=args.events, clip_start=_t(args.clip_start) if args.clip_start else None,
                  truth_path=args.truth, grid_m=args.grid, obs_height=args.height, c=c,
                  fmin=args.fmin, fmax=args.fmax, max_events=args.max_events, max_gap_s=args.max_gap)
        return 0
    if args.cmd == "gui":
        from .gui.server import serve
        serve(port=args.port, open_browser=not args.no_browser)
        return 0
    if args.cmd == "audit":
        from .audit import audit
        audit(args.audio, args.test_highpass)
        return 0


if __name__ == "__main__":
    sys.exit(main())
