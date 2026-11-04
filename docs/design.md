# Design: Provenance, the flyover geolocator

## Purpose

Provenance estimates where an audio recording was made, using the faint Doppler curves of propeller planes flying over, matched against ADS-B flight history. It re-implements, end to end, the method in the colsto video "I discovered a sound that leaks your exact location". The video's creator released no code.

It has two jobs.
1. Locate: given a recording, the ADS-B history, a terrain model, a search box, and a time window, rank candidate locations.
2. Audit: given a recording, say whether it carries this kind of location clue, and test whether a mitigation actually removes it.

It ships with a simulator, so the whole pipeline can be proven against a hidden ground truth without any outside data.

## Why this design

The video is about one specific pipeline, so the program is that pipeline, with each video step as its own module. Python fits: the video used Python, and the work is numerical (NumPy, SciPy, Matplotlib). There is no web service and no database; it is a command-line tool that writes a Markdown report with figures, which suits how you already keep deliverables.

## Architecture

The pipeline runs left to right.

audio file, then spectrogram, then event detection and ridge trace, then a straight-line Doppler fit per event (speed, distance, heard closest-approach time, base pitch, each with a range).

ADS-B file, then cleaned track segments, then smooth position and velocity splines, then closest-approach tables against a 200 metre grid that uses the terrain model for ground height.

Both streams meet in the search: speed and distance filter, time-gap filter, silence filter, densify to 100 metres, model the exact curve each candidate would hear, locked scoring, best per flight pair, a fine 25 metre pass around the winner, then the report.

## Components

| Module | What it does |
|---|---|
| `provenance_fx/geo.py` | Local east-north metre frame. Terrain model (DEM) from .npz, GeoTIFF (optional rasterio), or a flat height. |
| `provenance_fx/adsb.py` | Loads ADS-B from CSV (simulator or OpenSky-style) or SBS-1 BaseStation logs (dump1090 or readsb port 30003). Splits tracks at gaps. Smoothing-spline position and velocity. Known-jet type list, used to filter jets out. |
| `provenance_fx/physics.py` | Doppler equation. Emission-time solver (heard time equals emit time plus distance over c). Exact heard-pitch model on a real track. The deliberately wrong "naive" model for comparison. Closed-form straight-line curve. |
| `provenance_fx/spectro.py` | Low-band, high-resolution spectrogram. Steady-tone suppression: a running 60-second median per frequency is subtracted, so part-time hums are removed too. Harmonic-aware ridge tracing by dynamic programming. Adaptive event detection. |
| `provenance_fx/measure.py` | Fits the straight-line curve to a traced ridge. Returns values plus generous ranges, as the video does. |
| `provenance_fx/search.py` | Grid, closest-approach tables, the three filters, densifying, locked two-event scoring, ranking, near-tie alternatives, fine pass. Scoring is contrast-based: brightness on the curve minus brightness 4 Hz to either side. Each event is normalised by the score of its own traced ridge. |
| `provenance_fx/dem_fetch.py` | Free terrain: downloads and caches AWS Terrain Tiles (Terrarium PNG, zoom 12) for the box. Sea-floor depths are clamped to 0 m. |
| `provenance_fx/cleanup.py` | Optional audio clean-up for the GUI: trim, high-pass and low-pass, steady-tone removal and noise reduction by spectral subtraction, and gain. |
| `provenance_fx/gui/` | Local web GUI. A FastAPI server bound to 127.0.0.1 runs jobs in background threads; the browser polls them. The single-page front end uses a canvas spectrogram viewer and Leaflet. |
| `provenance_fx/report.py` | Figures (events, funnel, score scatter, map plus fine heat map, best-fit overlays, naive versus correct) and `report.md` plus `result.json`. |
| `provenance_fx/audit.py` | Privacy check and high-pass mitigation test. |
| `provenance_fx/simulate.py` | Synthetic scene: terrain, about 500 flights over 6 hours including a busy airport, noisy and quantised ADS-B, a hidden listener, a 21-minute clip and a one-minute clip. |
| `provenance_fx/cli.py` | Commands: demo, simulate, measure, locate (`--dem auto`), audit, gui. |

## Key methods, matched to the video

- Delayed closest approach: closest-approach time plus slant distance over the speed of sound. Slant distance is 3D, using the terrain model for ground height and ADS-B altitude above sea level.
- Speed and distance filter: each event's fitted ranges. The speed range runs from 20 percent below the fit to 40 percent above it, because turns and climbs make a straight-line fit under-read true speed. Distance range runs from 0.55 to 1.8 times the fit. Both are generous on purpose.
- Time-gap filter: the second event's heard closest approach must follow the first by the measured gap, plus or minus 8 seconds.
- Silence filter: reject a point if any other flight, jets included, passes within 2.5 km between the two events (more than 45 seconds from each), as in the video. A stricter whole-clip option exists (silence_scope = "clip"), but it wrongly rejected the true spot on the real one-hour reference recording, because other planes were audible earlier in the hour.
- Exact curve: for each frame time, solve for the emission time, take the plane's velocity there from the smoothed ADS-B track, project it onto the line to the listener, and apply the Doppler equation.
- Locked scoring: event 1 is swept plus or minus 5 seconds and plus or minus 3 percent in base pitch. Event 2's placement is fixed by geometry relative to event 1, and only its base pitch is swept. The score is the mean normalised brightness under the curve, with one bin of tolerance.
- Known recording time: if the clip's start time is known, placement is locked to the clock (plus or minus 2 seconds) instead of to the measured closest approach.
- A trace score (the error in hertz against the traced ridge) is also computed, matching the video's one-minute variant. It is reported but not used for ranking.

## How to run

See README.md. The short version is: make a virtual environment, `pip install -e .`, then `provenance demo`.

## Assumptions I made

- The deliverable is a runnable research tool with a simulator, not a hosted service. The video's creator withheld code on purpose, and real nationwide ADS-B history is large and usually paid, so the demo uses synthetic data that follows the same physics.
- The default search is a regional box (60 by 60 km, 6 hours), not the whole US for a whole day. The code has no fixed size limit, but memory and time grow with the area and the amount of traffic.
- Still air, with one constant speed of sound (343 metres per second, or set by `--temp-c`).
- The listener is 2 metres above ground. Change it with `--height`.
- The sound source is the propeller's tonal base pitch. Jets are only used for the silence filter.

## Limits and known gaps

- One flyover is ambiguous. A point mirrored across the flight path hears almost the same curve. The report lists near-tie alternatives, and in testing the truth was often the listed mirror point rather than the top answer. Two flyovers, a tighter search box, or a turn in the flight path break the tie. The video reports a clean first place from one minute of audio; I could not reproduce that reliably in simulation. [VERIFY] whether his case had a turning flight.
- Not modelled: wind (it shifts apparent speed), temperature layers that bend sound, ground reflections, or Doppler from a moving microphone.
- SBS logs carry barometric altitude, not geometric, so expect tens of metres of vertical error. SBS also has no aircraft type, so you need an icao24-to-typecode CSV. [VERIFY] which aircraft database you use.
- [VERIFY] the time zone your dump1090 or readsb build writes into SBS lines. The parser assumes UTC unless told otherwise.
- The jet type list is partial. Unknown types are kept as possible propellers, which is the video's conservative choice.
- Each track segment gets a single closest approach. A plane circling over the same spot twice gets one entry. Split such tracks first.
- Simulated audio is cleaner than real life: there are no birds, cars or HVAC sweeps that also make tones. On real recordings, expect to set event windows by hand with `--events`.

- On the author's real reference recording, the tool now ranks the author's flight pair first, 86 m from his answer. Before the scoring changes it ranked 4th. This needs the second flyover's window to be set by hand (3035–3110 s); the automatic detector misses that faint event. See validation.md.
- The privacy audit's automatic curve finder is tuned on simulated audio. On the real reference recording, it reports several curves that are not clean flyovers, and it misses the two faint flyovers the author used. Treat its HIGH or LOW verdict as a prompt to look at the spectrogram, not as proof. [VERIFY]
- The GUI loads map tiles from Esri and OpenStreetMap over the internet. The audio and the results stay local.

## Responsible use

Use this on recordings you made, or have permission to analyse, and for learning or for checking your own exposure with `provenance audit`. Do not use it to find people who have not agreed to it. Nothing in this tool posts, uploads, or contacts any service; it only reads the local files you give it.
