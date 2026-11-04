"""One-call ENF analysis used by the CLI and the GUI. Always on the RAW audio track."""
from __future__ import annotations

import datetime as dt
import time

import numpy as np

from . import audit as A
from . import gridid
from . import match as M
from . import race as RACE
from . import reference as R
from .extract import detect_enf, extract_enf, hum_scan
from .media import load_raw


def parse_time(s):
    if s is None or s == "":
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        v = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if v.tzinfo is None:
            v = v.replace(tzinfo=dt.timezone.utc)
        return v.timestamp()


MAX_RACE_WINDOW_S = 3 * 86400
MAX_GRID_WINDOW_S = 400 * 86400
LONG_REF_S = 40 * 86400
META_SLACK_S = 3600.0


def window_from_meta(meta, duration):
    """Search window for the recording START from file metadata (creation_time and friends).

    creation_time is written by most phones/cameras, usually in UTC and usually at the START,
    but some devices write the END, or local time labelled as UTC. So the window spans
    [t - duration - 1 h, t + 1 h]. Returns (start, end, label) or None.
    """
    tags = (meta or {}).get("tags") or {}
    for k in ("com.apple.quicktime.creationdate", "creation_time", "date"):
        v = tags.get(k)
        if not v:
            continue
        try:
            t = parse_time(str(v).strip())
        except Exception:
            continue
        if t and t > 946684800:  # after 2000-01-01; filters 1970/1904 placeholder dates
            return t - duration - META_SLACK_S, t + META_SLACK_S, f"file metadata {k}={v}"
    return None


def get_reference(kind="gb", path=None, start=None, end=None, nominal=None, log=None):
    """kind: gb (NESO + Elexon) | grid:<GRID> (any built-in grid log, e.g. grid:US-WEST) | file | none."""
    if kind == "none":
        return None
    if kind.startswith("grid:"):
        from . import grids as G
        g = kind.split(":", 1)[1]
        if g not in G.GRIDS:
            raise ValueError(f"unknown grid {g}")
        if start is None or end is None:
            raise ValueError("a built-in grid reference needs a search window (start and end, UTC)")
        if end - start > MAX_GRID_WINDOW_S:
            raise ValueError("search window longer than ~13 months; narrow it")
        ref = G.grid_reference(g, start, end, log=log)
        if ref is None:
            raise ValueError(f"no {G.GRIDS[g]['name']} log covers that window (see the coverage table)")
        return ref
    if kind == "file":
        if not path:
            raise ValueError("choose a reference file")
        ref = R.load_any(path, nominal=nominal)
        if not ref.relative and (start or end):
            ref = ref.slice(start, end)
        return ref
    if start is None or end is None:
        raise ValueError("the built-in GB reference needs a search window (start and end, UTC)")
    if end - start > 62 * 86400:
        raise ValueError("search window longer than ~2 months; narrow it")
    return R.gb_reference(start, end, log=log)


def _grid_stage(tr, det, nom, x, sr, scan, nominal, win, win_src, race, cross_nominal, log, allow_switch=True):
    """Statistical grid hint + grid race (when a window is known) + the final grid answer."""
    grid = gridid.classify(tr, nom, det=det)
    race_res = None
    if race and win is not None:
        if win[1] - win[0] > MAX_RACE_WINDOW_S:
            race_res = dict(decision="abstain", winner=None, ranking=[], not_covered=[], window=list(win),
                            reason="time window longer than 3 days: narrow it to run the grid race")
        else:
            log(f"grid race over {win_src}")
            try:
                race_res = RACE.grid_race(tr, win[0], win[1], nominal=nom, log=log, det=det, cross_nominal=cross_nominal)
                # hum family unclear and no user choice: race the other family too and keep the one that wins
                if allow_switch and x is not None and not nominal and not scan["nominal"] and not race_res.get("winner"):
                    alt = 60 if nom == 50 else 50
                    log(f"hum family unclear: also racing {alt} Hz grids")
                    tr2 = extract_enf(x, sr, nominal=alt, log=log)
                    det2 = detect_enf(tr2, scan)
                    r2 = RACE.grid_race(tr2, win[0], win[1], nominal=alt, log=log, det=det2)
                    if r2.get("winner"):
                        nom, tr, det, race_res = alt, tr2, det2, r2
                        grid = gridid.classify(tr, nom, det=det)
                        log(f"switched to {alt} Hz: the {alt} Hz race found a winner")
            except Exception as e:  # network or data trouble: report, do not crash
                race_res = dict(decision="abstain", winner=None, ranking=[], not_covered=[], window=list(win),
                                reason=f"grid race failed: {type(e).__name__}: {e}")
        race_res["window_source"] = win_src
    if race_res and race_res.get("winner"):
        from .grids import GRIDS
        final = dict(grid=race_res["winner"], name=GRIDS[race_res["winner"]]["name"], method="grid race",
                     confidence=race_res["decision"], reason=race_res["reason"])
    elif race_res and len(race_res.get("ranking") or []) >= 2 and grid.get("decision") not in (None, "unknown"):
        final = dict(grid=None, name=f"{nom} Hz family, grid unknown", method="none", confidence="unknown",
                     reason=("the grid race found no grid whose log this hum follows (" + race_res.get("reason", "") +
                             f"); the statistical hint ({grid['decision']}) is not trusted against that"))
    elif grid.get("decision") not in (None, "unknown"):
        final = dict(grid=grid["decision"], name=gridid.NAMES.get(grid["decision"], grid["decision"]),
                     method="statistics", confidence="hint", reason=grid["verdict"])
    else:
        final = dict(grid=None, name=f"{nom} Hz family, grid unknown", method="none", confidence="unknown",
                     reason=(race_res or {}).get("reason") or grid.get("verdict"))
    return tr, det, nom, grid, race_res, final


def _match_stage(tr, ref, start, end, log):
    if ref is None:
        return None, None, None
    try:
        if not ref.relative and len(ref.f) * ref.step > LONG_REF_S:
            m = M.match_long(tr, ref, start=start, end=end, log=log)
        else:
            m = M.match(tr, ref, start=start if ref.relative is False else None, log=log)
        c = M.continuity(tr, ref, m)
        M.apply_continuity(m, c)
        return m, c, None
    except Exception as e:
        log("match skipped: " + f"{type(e).__name__}: {e}")
        return None, None, f"{type(e).__name__}: {e}"


def _window(start, end, use_meta_time, meta, dur):
    if start is not None and end is not None:
        return (start, end), "search window you entered"
    if use_meta_time:
        wm = window_from_meta(meta, dur)
        if wm:
            return (wm[0], wm[1]), wm[2]
    return None, None


def _ref(ref_kind, ref_path, start, end, dur, nom, log):
    if ref_kind == "none":
        return None, None
    try:
        ref = get_reference(ref_kind, ref_path, start, None if end is None else end + dur + 60, nom, log)
        log(f"reference: {ref.info()}")
        return ref, None
    except Exception as e:  # report, do not crash
        log("reference unavailable: " + f"{type(e).__name__}: {e}")
        return None, f"{type(e).__name__}: {e}"


def analyze(path, ref_kind="gb", ref_path=None, start=None, end=None, nominal=None, log=None,
            audio=None, race=True, use_meta_time=True, cross_nominal=False, video="auto", readout_ms=None):
    """ENF analysis of the raw audio track and, for video files (video='auto' or 'on'), of the light
    flicker in the picture. The audio result stays the primary one when the file has audio; the picture
    result is reported beside it (its own race and match) with an audio-vs-picture agreement check.
    A video with no audio track uses the picture as the primary source."""
    from . import video as VID
    from .media import probe_media
    log = log or (lambda m: None)
    t0 = time.time()
    if audio is None:
        meta = probe_media(path)
        has_audio = meta.get("n_audio") != 0
        sr, x = (None, None)
        if has_audio:
            sr, x, meta = load_raw(path)
    else:
        sr, x, meta = audio
        has_audio = True
    want_video = video == "on" or (video == "auto" and meta.get("has_video"))
    if not has_audio and not want_video:
        raise ValueError("this file has no audio track; turn video analysis on to use the picture's light flicker")
    vres = None
    if want_video:
        try:
            vres = VID.analyze_video(path, nominal=nominal, readout_ms=readout_ms, log=log)
        except Exception as e:
            vres = dict(available=False, status=f"video analysis failed: {type(e).__name__}: {e}", path_used=None)
            log(vres["status"])
    vtr = (vres or {}).get("_trace")
    vdet0 = None
    if vtr is not None:      # the video verdict is the presence check (detector + band cue), not the bare detector
        vdet0 = dict(vres["detect"], verdict=vres["presence"]["verdict"],
                     reasons=list(vres["presence"]["reasons"]) + list(vres["detect"].get("reasons", []))[:3])
    if has_audio:
        dur = len(x) / sr
        log(f"raw audio: {dur:.0f} s at {sr} Hz" + (" (audio track pulled from a video)" if meta.get("has_video") else ""))
        scan = hum_scan(x, sr)
        log("hum scan: " + scan["note"])
        ref, ref_err = _ref(ref_kind, ref_path, start, end, dur, nominal or scan["nominal"], log)
        # nominal: user choice > clear hum family > the reference's grid > best guess
        nom = nominal or scan["nominal"] or (ref.nominal if ref is not None else None) or scan["guess"]
        if ref is not None and ref.nominal != nom:
            log(f"warning: reference is {ref.nominal} Hz but the hum looks like {nom} Hz")
        tr = extract_enf(x, sr, nominal=nom, log=log)
        det = detect_enf(tr, scan)
        log(f"ENF detector: {det['verdict']} (score {det['score']})")
        primary = "audio"
    else:
        dur = float(meta.get("duration") or ((vres or {}).get("n_frames", 0) / ((vres or {}).get("info") or {}).get("fps", 30)))
        primary = "video"
        vn = (vres or {}).get("nominal")
        scan = dict(nominal=vn, guess=vn or 50, note="no audio track: the picture's light flicker is used", max_snr_db=0.0,
                    score50=0.0, score60=0.0, lines50=[], lines60=[])
        if vtr is None:
            res = dict(file=path, duration=dur, sr=None, meta=meta, scan=scan, primary_source="video",
                       detect=dict(verdict="absent", score=0.0, reasons=[(vres or {}).get("status", "no flicker")]),
                       grid=dict(decision="unknown", verdict="no usable ENF"), race=None, trace=None, match=None,
                       continuity=None, video=_video_public(vres), av_agreement=None,
                       grid_final=dict(grid=None, name="unknown", method="none", confidence="unknown",
                                       reason="no audio track and no usable light flicker"))
            res["privacy"] = A.verdict(scan, res["detect"], dur, None, None, meta, nominal=None)
            res["privacy"]["lines"].insert(0, "No audio track, and the picture shows no usable light flicker.")
            res["elapsed_s"] = round(time.time() - t0, 1)
            res.update(_trace_obj=None, _ref_obj=None, _race=None, _video=vres)
            return res
        tr, det, nom = vtr, vdet0, vres["nominal"]
        ref, ref_err = _ref(ref_kind, ref_path, start, end, dur, nom, log)
    win, win_src = _window(start, end, use_meta_time, meta, dur)
    tr, det, nom, grid, race_res, final = _grid_stage(tr, det, nom, x, sr, scan, nominal, win, win_src, race,
                                                      cross_nominal, log, allow_switch=has_audio)
    m, cont, merr = _match_stage(tr, ref, start, end, log)
    res = dict(file=path, duration=dur, sr=sr, meta=meta, scan=scan, detect=det, grid=grid, grid_final=final,
               race=None if race_res is None else RACE.public(race_res), primary_source=primary,
               trace=tr.to_dict(max_points=3000), match=m, continuity=cont)
    if ref_err or merr:
        res["match_error"] = ref_err or merr
    # ---- the picture, beside the audio
    vpub = _video_public(vres)
    agree = None
    if has_audio and vtr is not None:
        vnom = vres["nominal"]
        log(f"video flicker: racing the picture's ENF ({vnom} Hz) on its own")
        _, vdet, _, vgrid, vrace, vfinal = _grid_stage(vtr, vdet0, vnom, None, None, scan, vnom, win, win_src,
                                                       race, cross_nominal, log, allow_switch=False)
        vref = ref if (ref is not None and ref.nominal == vnom) else None
        vm, vc, _ = _match_stage(vtr, vref, start, end, log) if vref is not None else (None, None, None)
        vpub.update(race=None if vrace is None else RACE.public(vrace), grid_final=vfinal, match=vm, continuity=vc,
                    trace=vtr.to_dict(max_points=3000))
        vres["_race"] = vrace
        vres["_match"] = vm
        agree = VID.av_agreement(tr, vtr, det, vdet0)
        agree = {k: v for k, v in agree.items() if not k.startswith("_")} | {"_raw": agree}
        # cross-check the two answers
        notes = []
        if final.get("grid") and vfinal.get("grid") and final["grid"] != vfinal["grid"] and \
                final.get("confidence") in ("likely", "decisive") and vfinal.get("confidence") in ("likely", "decisive"):
            notes.append(f"audio says {final['name']} but the picture says {vfinal['name']}: the sound and the picture "
                         "may come from different places (dub / splice hint)")
        if m and vm and m.get("label") in ("strong", "moderate") and vm.get("label") in ("strong", "moderate"):
            dts = float(vm["start_time"]) - float(m["start_time"])
            if abs(dts) > 5:
                notes.append(f"audio and picture both match the reference, but {dts:+.0f} s apart: re-laid sound or an edit")
        agree["cross_checks"] = notes
        log(f"audio vs picture: {agree['verdict']}")
    elif not has_audio and vtr is not None:
        vpub.update(trace=None)    # it is the primary trace already
    res["video"] = vpub
    res["av_agreement"] = None if agree is None else {k: v for k, v in agree.items() if k != "_raw"}
    res["privacy"] = A.verdict(scan, det, dur, m, grid, meta, nominal=nom)
    if race_res and race_res.get("winner"):
        res["privacy"]["lines"].insert(0, f"Grid race: the {'hum' if has_audio else 'light flicker'} follows the "
                                          f"{final['name']} grid ({race_res['decision']}). That alone places the recording in that grid's region.")
    if vtr is not None:
        res["privacy"]["lines"].append("The picture also carries mains light flicker (" + vres["path_used"] +
                                       "): muting or replacing the sound does NOT remove this time and grid clue.")
        res["privacy"]["fixes"].append("for video: film under daylight or battery / DC lighting, or use an exposure of "
                                       f"exactly 1/{2 * vres['nominal']} s (or a multiple) so the camera averages the flicker out")
    if not has_audio:
        res["privacy"]["lines"].insert(0, "No audio track: this result comes from the picture's light flicker.")
    res["elapsed_s"] = round(time.time() - t0, 1)
    res["_trace_obj"] = tr
    res["_ref_obj"] = ref
    res["_race"] = race_res
    res["_video"] = vres
    res["_agree"] = None if agree is None else agree.get("_raw")
    return res


def _video_public(vres):
    if not vres:
        return None
    return {k: v for k, v in vres.items() if not k.startswith("_")}


def public(res):
    return {k: v for k, v in res.items() if not k.startswith("_")}
