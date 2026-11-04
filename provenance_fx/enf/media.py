"""Read the raw audio track of an audio OR video file (ffmpeg), untouched.

No normalising filters, no hum removal, no cleanup. Only a down-mix to mono and
an optional resample (default keeps up to 8 kHz, plenty for hum harmonics).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile

import numpy as np
from scipy.io import wavfile

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".3gp", ".flv", ".wmv", ".mts"}


def probe_media(path: str) -> dict:
    """ffprobe summary: streams, duration and any creation-time tags (a privacy leak on its own)."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                            "-show_streams", path], capture_output=True, text=True, timeout=60)
        info = json.loads(r.stdout or "{}")
    except Exception:  # ffprobe missing or unreadable file
        info = {}
    streams = info.get("streams", [])
    fmt = info.get("format", {})
    has_video = any(s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) == 0
                    for s in streams)
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    tags = {}
    for src in [fmt] + streams:
        for k, v in (src.get("tags") or {}).items():
            if k.lower() in ("creation_time", "date", "com.apple.quicktime.creationdate",
                             "com.apple.quicktime.location.iso6709", "location", "encoder"):
                tags[k] = v
    return dict(
        has_video=has_video,
        n_audio=len(audio) if info else None,
        audio_codec=audio[0].get("codec_name") if audio else None,
        audio_sr=int(audio[0].get("sample_rate", 0)) if audio else None,
        duration=float(fmt.get("duration", 0) or 0),
        container=fmt.get("format_name"),
        tags=tags,
    )


def load_raw(path: str, max_sr: int = 8000):
    """Return (sr, x float64 mono, info). x is NOT peak-normalised or filtered.

    For video files only the first audio track is decoded here; the picture's light flicker is
    analysed separately by provenance_fx.enf.video.
    """
    info = probe_media(path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if info.get("n_audio") == 0:
        raise ValueError("this file has no audio track (use the video light-flicker analysis instead)")
    if path.lower().endswith(".wav"):
        try:
            sr, x = wavfile.read(path)
            if sr <= max_sr * 2:
                return int(sr), _mono(x), info
        except ValueError:
            pass
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    try:
        sr_out = min(max_sr, info.get("audio_sr") or max_sr)
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-map", "0:a:0", "-vn",
                            "-ac", "1", "-ar", str(sr_out), "-c:a", "pcm_s16le", tmp],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise ValueError("ffmpeg could not read the audio track: " + r.stderr[-300:])
        sr, x = wavfile.read(tmp)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return int(sr), _mono(x), info


def _mono(x):
    if x.dtype == np.int16:
        x = x.astype(np.float64) / 32768.0
    elif x.dtype == np.int32:
        x = x.astype(np.float64) / 2147483648.0
    elif x.dtype == np.uint8:
        x = (x.astype(np.float64) - 128) / 128.0
    else:
        x = x.astype(np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x


def video_flicker_enf(path: str, **kw):
    """Light-flicker ENF from video frames (phase 2). Thin wrapper kept for older callers:
    see provenance_fx.enf.video.analyze_video."""
    from .video import analyze_video
    r = analyze_video(path, **kw)
    return {k: v for k, v in r.items() if not k.startswith("_")}
