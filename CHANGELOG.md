# Changelog

All notable changes. Dates are in 2026.

## [0.2.0] - 2026-11-03

### ENF · video light flicker
- Video files: the picture's mains light flicker (100 or 120 Hz) is analysed beside the sound.
- Rolling-shutter path: every row is a time sample; per-frame band fit, read-out time entered or searched (4 ms to one frame, contrast in dB), idle period reported, per-GOP codec offsets removed, phase-slope tracking.
- Global-shutter path: aliased frame brightness; refuses when the alias is near 0 Hz or sits on the keyframe rhythm (keyframe-pumping guard).
- Static-scene checks: motion (frame to frame and 1 s lag, keyframe spikes ignored), exposure jumps, bright quiet columns. Variable-frame-rate files use the measured mean rate.
- Presence check that abstains with no flicker; the picture gets its own grid race and time match with the same rules; video-only files use the picture as the main source.
- Audio-versus-picture agreement with lag, offset and per-piece checks: agree, agree with an offset, partly disagree (splice hint), disagree (dub or tamper hint).
- CLI: `provenance enf FILE --video auto|on|off --readout-ms MS`; new plots `enf_video.png`, `enf_video_grid_race.png`.
- GUI: video controls, picture panel, simulated video samples, Help section "Video light flicker".
- Validation on simulated videos from real grid logs, and on two real CC BY 4.0 phone videos (Zenodo 3549379). See `docs/enf_validation.md`, section 15.
- Fix: GUI results with NaN values no longer fail to load.

### Documentation and credit (zip rebuilt 2026-11-03)
- README: new "Origin and acknowledgements" section crediting colsto's two videos, and stating that Provenance is an independent reimplementation with no copied code.
- README: full numbered References list in IEEE style (104 entries in seven groups), with DOIs or links checked against doi.org, Crossref, DataCite, arXiv, Zenodo and the FDSN; in-text [n] citations added to Methods sections 1 to 12.
- New CITATION.cff.
- DATA_SOURCES.md aligned with the references: seismic network DOIs, licences, and the correct authors of the US Zenodo record (De Din, Carta and Hartmann).

## [0.1.0] - 2026-11-03

First packaged release.

### Acoustic Locate
- Doppler physics with emission-time model and straight-line closed form.
- Spectrogram with steady-tone suppression (60 s running median), ridge tracing and event detection.
- Per-flyover least-squares fit with ranges.
- Location search: candidate grid, CPA tables, timing and silence-between-events filters, locked Doppler contrast scoring (±4 Hz) with per-event normalisation, three-pass refinement.
- Free terrain (AWS Terrain Tiles), adsb.lol/readsb archive converter, SBS input.
- Real-data reference test: author's flight pair ranked first, best spot 86 m from his answer (search box around the right area; second flyover window set by eye).
- Leak Check with high-pass test.

### ENF · mains hum
- Multi-harmonic ENF extraction (harmonics 1 to 7, QIFFT, SNR weighting, DP ridge), hum detector, raw-audio-only pipeline for audio and video.
- Masked NCC matching with level gate, drift search, effective-sample significance and labels; continuity check and timeline-break warning.
- Grid race across GB, Continental Europe, Nordic, US West, US East, US Texas, Quebec, with decisive/likely/abstain rules and segment fallback.
- Statistical fallback classifier v2 (calibrated, abstains).
- US references: Zenodo WECC 2024 and East 2023, Pigott Phoenix 2022, nate-griff FNET scrape, home logger. The Zenodo reader also accepts a plain extracted CSV.
- US West reference rebuilt from public seismometers (`enf-rebuild`) and a live SeedLink collector (`enf-collect`) with watchdog, held windows and saved trust state.

### GUI
- Local single-page GUI with tabs Acoustic Locate, Acoustic Locate · Leak Check, ENF · mains hum, and a new **Help** tab with a step-by-step walkthrough, limits, CLI equivalents and troubleshooting.

### Project
- Renamed from *flyloc* to **Provenance** (distribution `provenance-forensics`, package `provenance_fx`, command `provenance`; the PyPI name `provenance` is taken).
- Data paths made portable through `PROVENANCE_DATA`.
- Packaging: README with methods and validation, DATA_SOURCES.md, CONTRIBUTING.md, MIT licence (placeholder), CI workflow, Makefile.

## Unreleased
- (nothing yet)
