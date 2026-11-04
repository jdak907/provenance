"""ENF (electric network frequency) analysis for Provenance.

Mains hum (50 or 60 Hz and its harmonics) drifts with the power grid. The drift
pattern can date a recording and hint at which grid it came from.

Rule: ENF code always reads the RAW audio track. Provenance's cleanup step removes
steady tones, which deletes the hum, so never feed it cleaned audio.

For your own recordings and privacy awareness.
"""
from .media import load_raw, probe_media, video_flicker_enf  # noqa: F401
from .extract import hum_scan, extract_enf, detect_enf  # noqa: F401
