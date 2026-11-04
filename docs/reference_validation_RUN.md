# How the reference validation was run

1. Reference audio: the author's "Unknown location - raw audio" (https://youtu.be/4CxVxuMVkMc), linked in the main video's description. Downloaded with yt-dlp as mono 8 kHz WAV to `raw/reference_recording.wav` (1 hour).
2. ADS-B: the adsb.lol open-data globe_history release for 2026-09-08 (ODbL, about 3.9 GB in two tar parts, https://github.com/adsblol/globe_history_2026/releases/tag/v2026.09.08-planes-readsb-prod-0). Kept outside the project (not in this repo). Converted for a New York metro box:
   `cat part.aa part.ab | python -m provenance_fx.readsb_hist --bbox 40.3,41.4,-74.5,-72.8 --out reference_validation/adsb_nyc_2026-09-08.csv`
3. Locate:
   `provenance locate --audio raw/reference_recording.wav --adsb reference_validation/adsb_nyc_2026-09-08.csv --dem reference_validation/flat_5m.json --bbox 40.60,41.10,-73.90,-73.20 --start 2026-09-08T00:00Z --end 2026-09-09T00:00Z --events 2090-2225,3040-3088 --fmin 85 --fmax 185 --height 4 --max-gap 300 --out reference_validation/two_event`
