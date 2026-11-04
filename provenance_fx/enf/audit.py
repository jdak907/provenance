"""Privacy verdict: does this recording leak its time or its grid through mains hum?"""
from __future__ import annotations


def verdict(scan: dict, det: dict, duration: float, match: dict | None = None, grid: dict | None = None,
            meta: dict | None = None, nominal: int | None = None) -> dict:
    lines, level = [], "LOW"
    tags = (meta or {}).get("tags") or {}
    time_tags = {k: v for k, v in tags.items() if "creation" in k.lower() or k.lower() == "date"}
    loc_tags = {k: v for k, v in tags.items() if "location" in k.lower()}
    if time_tags:
        lines.append(f"File metadata already states a time: {time_tags}. Strip metadata before sharing.")
        level = "HIGH"
    if loc_tags:
        lines.append(f"File metadata holds a location: {loc_tags}. Strip metadata before sharing.")
        level = "HIGH"
    v = det.get("verdict")
    nom = scan.get("nominal") or (nominal if v in ("present", "weak") else None)
    if v == "absent" or not nom:
        lines.append("No usable mains hum found: the audio does not leak a grid or a time by ENF.")
    else:
        lines.append(f"Mains hum at {nom} Hz is audible to analysis: this alone reveals the "
                     f"{'50' if nom == 50 else '60'} Hz family of grids (a coarse region).")
        lvl = "MEDIUM"
        if det.get("flat"):
            lines.append("The hum barely moves in frequency, so it is probably from a crystal-locked source "
                         "(inverter, UPS). It is unlikely to date the recording.")
        elif v == "present" and duration >= 300:
            lines.append(f"Clean drift over {duration / 60:.0f} minutes: anyone with that grid's frequency log "
                         "could probably date this recording to within seconds, IF the hum comes from the grid (a reference match proves it; inverter or UPS hum does not).")
            lvl = "HIGH"
        elif v == "present":
            lines.append(f"Clear drift but only {duration:.0f} s long: dating is possible but error-prone.")
        else:
            lines.append("Weak drift: dating would be unreliable, but a better extractor might still try.")
        if level != "HIGH":
            level = lvl
    if match:
        lab = match.get("label")
        if lab in ("strong", "moderate"):
            lines.append(f"Matched against {match['reference']['name']}: {match['start_label']} "
                         f"(r={match['ncc']}, {lab}). The time leak is demonstrated, not just possible.")
            level = "HIGH"
        else:
            lines.append(f"No confident match against {match['reference']['name']} ({lab}).")
    if grid and grid.get("verdict"):
        lines.append("Grid guess: " + grid["verdict"])
    fix = []
    if nom:
        fix.append(f"notch {nom} Hz and its harmonics up to ~{nom * 8} Hz (a plain high-pass often leaves "
                   "higher harmonics behind), or add masking noise in those bands")
        fix.append("record on battery power away from mains wiring, transformers and lights")
    if time_tags or loc_tags:
        fix.append("strip container metadata (for example: ffmpeg -i in -map_metadata -1 -c copy out)")
    return dict(level=level, lines=lines, fixes=fix)
