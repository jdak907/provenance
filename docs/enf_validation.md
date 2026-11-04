# ENF validation (real data, failures included)

Sections 1 to 5 are the Phase 1 timestamp tests. Sections 6 to 12 cover the grid identification work: the grid race (time roughly known), the rebuilt statistical fallback (time unknown), and before/after numbers for both.

Run on 2026-11-03 with the code in `provenance_fx/enf/`. The raw numbers are in `validation_runs/enf_whu.json` and `validation_runs/enf_vod.json`. Times are UTC unless marked PT (America/Los_Angeles, UTC-8 today). The data inventory is in `$PROVENANCE_DATA/INVENTORY.md` (a local data inventory; not in this repo).

## 1. ENF-WHU (130 real recordings, Wuhan, 50 Hz) — best ground truth
Script: `python scripts/enf_validate_whu.py --jobs 6`. Each noisy recording (H1, 268–954 s long, raw audio) is searched across its full 24 h mains log. The truth is the lag of the clean H1_ref clip in that same log, which is the dataset's own method.

| Measure | Result |
|---|---|
| Within 10 s of the truth | **84 / 130 (65 %)** |
| Median error of those hits | 1.5 s (90th percentile 3.5 s) |
| Labelled "strong" | 37, of which **36 right** |
| Labelled "moderate" | 17, of which 16 right |
| Labelled "weak" | 29, of which 23 right |
| Labelled "no match" | 47, of which 9 right |
| Confident but wrong | 2. #28 ("strong", r = 0.89) and #13 ("moderate", r = 0.77) |
| Detector says "present" on H1 | 97 / 130 |
| H0 no-ENF controls (50) flagged "present" | **0** |
| H0 controls with a confident match | **0** |
| First 2 minutes only: right within 10 s | 35 / 130. The short-clip guard labelled every 2-minute result "unreliable", so none came out confident but wrong |

What this means: a "strong" label is trustworthy here (97 %). About a third of the WHU clips have hum too faint to date, and the tool says so instead of guessing. Published WHU results with stronger estimators reach similar or higher hit rates [VERIFY against Hua 2021 tables].

## 2. Heathrow live stream, GB grid — true trace-back with a known clock
- I captured 30 min of public live-cam audio, starting 2026-11-03 16:17:14 UTC (08:17:14 PT).
- Reference: the Elexon BMRS FREQ feed. It's real time but only has 15 s resolution. NESO's 1 s file for November won't be published until about December [VERIFY].
- Search window: 2 to 8 hours of the reference, blind.
- Best fit: **16:16:58–59 UTC**. That means stream latency of about 15 s, which is plausible for YouTube live.
- Match quality: r = 0.80–0.89, but the runner-up is close (0.83 over the 8 h window). The tool therefore labels it **"weak"**, with a false-match chance of 0.16–0.43.
- Honest reading: the right answer comes out top, but at 15 s reference resolution the tool can't yet prove it. Re-run against NESO 1 s data once November is published; that should firm it up.
- Continuity check flags "possible gaps", which fits live-stream hiccups.

## 3. Railcam UK live captures (York North, Crewe, Sampler) — failure
- Hum at 100 Hz visibly follows the grid for about the first 13 minutes (see `validation_runs/enf_live_uk_traces_vs_elexon.png`). After that, the streams stalled: only about 1190 s of audio arrived over 30 min of wall clock.
- Matching failed for both the full files and the first 700 s alone (r 0.31–0.67, "no match").
- Cause: noisy single-harmonic traces plus a 15 s reference. Not solved in Phase 1.

## 4. York South railcam video (mp4, video + audio) — correct negative
- The audio track was pulled from the video with ffmpeg and analysed raw.
- Strong 50/100/150/200 Hz lines (up to 18 dB), but they sit at 50.00 Hz while the GB grid was at 50.11 Hz.
- That points to a crystal-locked source (an inverter or UPS), not the mains.
- Matching gives only "weak" or "no match" at random times, which is correct. The flatness rule did not fire because the hum wanders about ±0.02 Hz, so the detector still says "present" or "weak". This is a known limit: without a reference, non-grid hum can look like ENF.

## 5. Archived UK live streams vs NESO 1 s — blind, 48 h window
Ground truth is the YouTube `release_timestamp` + 300 s.

| Stream | Result |
|---|---|
| Ribblehead Station Inn, 2025-05-06 (https://www.youtube.com/watch?v=vSOuVeHI2KY) | Best fit 10:41:29 UTC vs metadata 09:41:36, **+3593 s**, r = 0.72, "weak" |
| Railcam Sampler, 2025-06-25 (https://www.youtube.com/watch?v=dQze_bvWgaw) | Best fit **+3597 s** from metadata, r = 0.82, "weak" |
| Epping Signal Cabin 2025-04-17 / 2025-05-01, Ongar 2025-05-03 | No match (faint or non-grid hum) |
| 4 Bluebell / Crowcombe streams | Audio is digital silence (the tool now says so) |

Two independent streams landing within 3–7 s of exactly one hour after the listed start is very unlikely by chance: about 2×10⁻⁴ each in a 48 h window. The most likely story is that these streams really started an hour after YouTube's listed time, perhaps from a BST/UTC mix-up when they were scheduled. I can't confirm that from here [VERIFY]. NESO's own clock is UTC: I checked it against Elexon for 2026-09-15 and the best lag was 0 s (r = 0.997).

## 6. Grid identification: summary, before vs after

"Before" is the Phase 1 grid guess (v1: a linear model trained on clean grid logs). "After" is the grid race when a rough time is known, and the v2 statistical model when it is not.
- "Answered" means the tool committed to a grid.
- "Wrong-but-confident" means it committed to the wrong one.

| Test set | Before (v1 statistics) | After: grid race (time known) | After: v2 statistics (time unknown) |
|---|---|---|---|
| Simulated recordings, 216 race clips (GB, CE, Nordic, US West, US Texas) | 53 % forced right; answered 57 %, of those 64 % right; **45 wrong-but-confident** | ±10 min window: answered 86 %, **100 % right, 0 wrong**. ±1 h: 79 %, 0 wrong. ±6 h: 70 %, 0 wrong | (clips were in training; see the next row) |
| Simulated recordings, held-out days (1,410 clips at 50 Hz, 424 at 60 Hz) | 50 Hz: 58 % forced; 70 % right when answering; 222 wrong-but-confident | n/a | 50 Hz: 74 % forced; 90 % right when answering, abstains 56 %; 62 wrong-but-confident (4.4 %). 60 Hz: 70 % forced; 90 % right when answering, abstains 52 %; 20 wrong-but-confident |
| No-hum clips (32 noise or tone-only clips) | answered 26 of 32 | **0 of 96 runs answered** | detector plus model: abstains (5 of 32 if the detector is skipped) |
| Real UK recordings with hum (8 clips; truth = GB) | 2 of 8 right; **6 wrong-but-confident** (mostly "Nordic") | default windows (±1 h live, ±2 h archive): 2 answered, both GB, 0 wrong. ±10 min (live) / ±30 min (archive): 4 answered, all GB, 0 wrong | 0 answered (all flagged as noisier than the training data); 0 wrong. A forced guess would get 4 of 8 |
| Real ENF-WHU recordings (130; truth = China; time unknown) | 47 % forced; answered 85, of those 38 % right; 53 wrong-but-confident | not possible: no absolute time, no free China log | 53 % forced; answered 47, of those 60 % right; **19 wrong-but-confident** (training held out each recording's day) |
| Non-mains inverter hum (York South) | said "GB" with 92 % | abstained (correct) | abstained (race overrides statistics) |

Bottom line: give the tool a rough time and it is usable. On simulated recordings built from real grid logs it never named a wrong grid, and it says "abstain" when the hum is too weak. Without a time it is still only a hint. It is right about 9 times in 10 when it answers, but it abstains on about half of recordings. On real noisy streams it now abstains rather than guessing wrong.

Files: `validation_runs/enf_race.json`, `validation_runs/enf_gridid_validation.json`, `validation_runs/enf_gridid_cv.json`. Scripts: `scripts/enf_validate_race.py`, `scripts/enf_validate_gridid.py`.

## 7. Grid race (time roughly known)

**How it works:**
1. Extract the recording's ENF.
2. Fetch the concurrent frequency log of every grid that has a free log for that time window.
3. Match the ENF against each one, using the same level gate and the same smoothing for all.
4. Rank the grids.

Only the grid the recorder was plugged into can line up. The wrong grids give only chance correlation, and their average frequency usually sits tens of mHz away from the hum.

**Decision rule** (tuned on the simulated runs):
- **likely:** the winner has r ≥ 0.60, a Fisher-z margin over the next grid ≥ 0.5, and a false-alarm p over the window < 0.5.
- **decisive:** r ≥ 0.80, Fisher-z margin ≥ 1.0, and p < 0.01.
- **otherwise:** abstain.
- **Only one grid covered:** the match must reach p < 0.05, and the result is never better than "likely".

The Fisher-z margin is atanh(r1) − atanh(r2). It is used instead of a plain r difference because 0.99 against 0.70 is much stronger evidence than 0.50 against 0.21.

**Segment fallback.** Live streams stall and edits cut audio, so the whole clip may not line up in one piece. In that case the race is re-run on separate 300 s pieces. It answers "likely" only if at least 2 pieces pick the same grid, at consistent times (later pieces may sit later, never earlier), and no piece picks another grid. This rescued 2 stalled UK live captures with a ±10 min window. It produced no false answers in simulation.

**Window source:**
- the window the user types in, or
- the file's creation_time (or the Apple creation date) metadata, widened to [t − duration − 1 h, t + 1 h], or
- nothing, in which case the race doesn't run.

The race is capped at 3 days.

**Hum family:** if the hum family is unclear, the race tries both 50 and 60 Hz and keeps the family that produces a winner.

### Simulated validation (648 race runs plus 96 no-hum runs)

**How the clips were made:**
- Real logs on 32 days across 2025-01 to 2026-09: GB from NESO 1 s, CE from Energy-Charts 1 s, Nordic from Fingrid 10 Hz.
- US West against US Texas from the OSF weeks in May 2019.
- Each log was turned into audio with `simulate.mic_chain`:
  - a random harmonic profile (mains-near, phone high-pass, camera buzz, or odd harmonics)
  - hum SNR from −22 to +10 dB per 8 s bin
  - clock error ±100 ppm, plus slow wander
  - 1/f noise, bursts and level changes
  - an interfering steady tone in 25 % of clips
  - stream stalls in 15 % of clips
  - clip length 3 to 20 minutes
- Each clip was then run through the normal extractor.

| Window around the true start | Answered | Right when answering | Wrong-but-confident | "Decisive" (all right) | No-hum clips answered | Median timing error |
|---|---|---|---|---|---|---|
| ±10 min | 86 % | 100 % | 0 | 130 | 0 of 32 | 0.5 s |
| ±1 h | 79 % | 100 % | 0 | 117 | 0 of 32 | 0.5 s |
| ±6 h | 70 % | 100 % | 0 | 102 | 0 of 32 | 0.5 s |

- The top-ranked grid was the true grid 96 to 97 % of the time, even before the abstain rule.
- Abstentions come from short clips (3 to 5 min: about half answered) and very low SNR.
- US West against Texas is the weakest pair. US West answered 50 to 67 % of clips and Texas 67 to 92 %, all of them right.

### Real UK recordings (truth GB)

| Clip | Hum | Default window | Result | Narrow window | Result |
|---|---|---|---|---|---|
| Heathrow live, 30 min | weak | ±1 h | **likely GB** (r 0.80; CE −1, off by 80 mHz) | ±10 min | **likely GB** |
| York North live (stalled) | present | ±1 h | abstain | ±10 min | **likely GB** (segments) |
| Crewe live (stalled) | weak | ±1 h | abstain | ±10 min | abstain |
| Sampler live (stalled) | weak | ±1 h | abstain | ±10 min | **likely GB** (segments) |
| Ribblehead archive | present | ±2 h | abstain (r 0.72 but p = 1) | ±30 min | abstain (true time is outside: see the +1 h note) |
| Sampler archive | weak | ±2 h | **likely GB** (r 0.82; CE and Nordic −1) | ±30 min | abstain (true time outside) |
| Epping archive a | weak | ±2 h | abstain (GB 0.67 vs Nordic 0.57) | ±30 min | abstain |
| Epping archive b | weak | ±2 h | abstain | ±30 min | abstain |
| York South (inverter hum, not mains) | present | ±1 h | abstain (correct) | ±10 min | abstain (correct) |
| Ongar archive (no usable hum) | absent | ±2 h | abstain (correct) | | |

- There were no wrong answers on real clips.
- Nordic could not be raced for the November 2026 live captures, because Fingrid had not published that month yet.

**Archive timing note:** in both archives that matched, the best fit sits about +3,595 s after YouTube's `release_timestamp` + 300 s. That means either the stream's real start is about 1 h after YouTube's release time, or there is a BST (UTC+1) labelling issue. [VERIFY]

## 8. Statistical fallback v2 (time unknown)

**Root cause of "GB called Nordic".** v1 was trained on clean grid logs smoothed to look like recordings. A microphone recording's ENF is different:
- it has extractor smoothing, estimation noise and gaps
- it has a recorder clock offset
- on streams, it has codec damage

When we measured the 8 real UK clips, their fine-scale variability was 3 to 4 times larger than any grid log. The v1 linear model then picked whichever class its boundaries happened to favour, which in practice was Nordic, for 6 of 8 clips.

**Fixes:**
1. **Train on what the tool actually sees.** Real grid logs are passed through the simulated microphone chain and then the real extractor (1,740 clips):
   - GB: 8 NESO months
   - Nordic: 8 Fingrid months
   - CE: 32 Energy-Charts days plus OSF FR/PL/IT
   - plus OSF GB01 and SE01, WHU China (28 days, plus the 130 real WHU recordings), and US UT/TX/FL
2. **New features:**
   - increment spread at 1 to 128 s
   - Haar wavelet variances
   - fluctuation spectrum (5 bands plus slope)
   - autocorrelation at 10, 30, 60 and 120 s
   - step kurtosis, jump and ramp fractions
   - mean offset from nominal
3. **Cross-validation by day:** GroupKFold, so a whole day of a grid's log is always held out together.
4. **Calibration and abstain rules:**
   - temperature-calibrated probabilities
   - an abstain threshold set where held-out accuracy reaches 90 % (0.69 at 50 Hz, 0.65 at 60 Hz)
   - also abstains under 300 s, with more than 40 % gaps, or with no hum
5. **Out-of-distribution gate:** the model abstains when the trace is noisier than 98 % of the training traces (fine-scale features).

Without this gate, v2 said "GB" for 6 of 8 UK clips and was right every time. But the main reason was that they were noisy, and GB is the most variable class. That is the right answer for the wrong reason, so the tool now abstains instead.

**What did not work:**
- Removing the ±20 mHz steps from the WHU day logs, thinking they were artefacts, made WHU accuracy collapse to 5 %. The real recordings follow those steps (r 0.95 with the steps, 0.5 without), so they are real signal and were kept.
- Training on simulation only (without real WHU recordings) gave 28 % on WHU, against 53 % with them.
- Gradient boosting was about 5 points better than logistic regression (79 % vs 74 % forced, 50 Hz). It isn't shipped, because the model would no longer be plain JSON, and it would add a runtime scikit-learn dependency.

**Held-out-day confusion at 50 Hz** (rows are the truth, columns the forced prediction):

| Truth | CE | China | GB | Nordic |
|---|---|---|---|---|
| CE | 240 | 27 | 24 | 40 |
| China | 24 | 317 | 34 | 35 |
| GB | 22 | 30 | 246 | 30 |
| Nordic | 47 | 31 | 29 | 234 |

**Accuracy by clip length** (50 Hz, right when answering): 3 to 5 min 68 %, 5 to 10 min 84 %, 10 to 15 min 90 %, 15 to 20 min 96 %.

## 9. Free reference coverage (no login, no key)

| Grid | Source | Period | Resolution | License |
|---|---|---|---|---|
| Great Britain | NESO frequency archive | 2014 → latest published month | 1 s | NESO Open Data Licence |
| Great Britain | Elexon BMRS FREQ | recent days | 15 s | Elexon BMRS terms [VERIFY] |
| Continental Europe | Energy-Charts API (Fraunhofer ISE, Freiburg meter) | 2022-05-01 → now (a few days missing, e.g. 2026-09-24) | 1 s | CC BY 4.0 |
| Nordic | Fingrid open data, monthly 7z archives | 2024-01 → about a month ago (2026-09 is the latest; 2023 and earlier are not at this URL) | 10 Hz, averaged to 1 s | CC BY 4.0 [VERIFY] |
| CE / Nordic / GB / US | OSF power-grid frequency database (Jumar et al.) | fixed weeks in 2019 (US Florida 2023) | 1 s | CC BY 4.0 |
| US West | Zenodo, De Din, Carta and Hartmann (10.5281/zenodo.17366693), filled-in stretches (QI=2) dropped | 2024-01-16 → 2024-11-18 | 1 s | CC BY 4.0 |
| US East | Zenodo, same authors (identical to OSF US_FL01, used only as a fallback) | 2023-06-18 → 2023-07-06 | 1 s | CC BY 4.0 |
| US West | Pigott 60Hz log, Phoenix AZ (GitHub), clock offset inferred | 2022-02-14 → 2023-02-23 | 5 s | see repo [VERIFY] |
| US West / East / Texas / Quebec | nate-griff scrape of the public FNET gauge display (GitHub), low trust | 2026-03-20 → 2026-05-12 | about 2 s | see repo [VERIFY] |

**Not covered by any free no-login source found:**
- live US grids, and US dates outside the spans above (section 13; a home logger fills this gap: `home_logger_guide.md`)
- Ireland, Baltic, Japan, China, India, Australia

**Free but needs registration (listed only, not signed up):**
- ENTSO-E Transparency API key
- Fingrid open-data API key (the monthly archives above need no key)
- gridradar.net API
- FNET/GridEye data requests

## 10. Limits

- **The race needs a time window.** Narrower is better: ±10 min answered 86 %, ±6 h answered 70 %.
- **Without metadata, the user must supply the time.** YouTube downloads carry no creation_time.
- **A sped-up or resampled recording breaks the level gate.** The race assumes the recorder's clock is within about ±200 ppm.
- **Nordic lags behind.** Fingrid publishes each month several weeks later, so recordings from the last 4 to 8 weeks can't race Nordic.
- **Elexon's 15 s resolution** forces 15 s smoothing on every grid in a race. This lowers r for recent GB recordings.
- **US coverage is patchy** (section 13): 2019 and 2023 OSF weeks, Phoenix 2022-02 to 2023-02, WECC 2024-01 to 2024-11, and the 2026-03 to 2026-05 FNET scrape. Outside those, the 60 Hz race reports "no free reference". The GUI's coverage panel shows the spans.
- **The statistical fallback is still a hint.**
  - It is about 90 % right when it answers on simulated held-out days, and about 60 % on real WHU recordings.
  - It abstains on about half of recordings, and on noisy streams.
  - Each grid comes from one or a few logging sites.
  - Its China class has only Wuhan.
- **The simulated microphone chain is a model.** It doesn't include real codecs (AAC/Opus) or room acoustics. Real stream recordings were noisier than the simulation.

## 11. [VERIFY]

- **US sources (section 13):** Zenodo recorder site and license; Pigott clock offset (inferred UTC-7 from the data, not checked against a concurrent log); nate-griff scale accuracy and the FNET display terms.

- **Fingrid time zone:** the archives are read as Finnish local time (EET/EEST, DST-aware). The first sample of 2026-09 is 2026-08-31 21:00 UTC, which is consistent with that. Not yet cross-checked against a concurrent Nordic recording; the OSF SE01 week (2019) predates the archive.
- **OSF timestamps** are assumed to be UTC.
- **Licenses:** confirm the Energy-Charts and Fingrid CC BY 4.0 terms, and the Elexon terms, before publishing results.
- **YouTube archive times:** the +1 h offset between release_timestamp and the ENF fit (section 7).
- **Energy-Charts:** a single Freiburg meter stands in for all of Continental Europe. This is fine for the synchronous grid, but a local event could differ for a few seconds.

## 12. Synthetic and unit tests
`pytest`: **58 passed** (2026-11-03, after the seismic work: 17 tests in `tests/test_seismic.py`). Before that, **41 passed**: the 31 below plus 6 US-reference tests (`tests/test_enf_us.py`) and 4 home-logger tests (`tests/test_home_logger.py`). Before the US work: **31 passed**. That is the original 18, the 9 Phase 1 ENF tests, and 4 new ones:
- the grid race picks the right one of 3 synthetic grids at the same level, and abstains on noise
- the metadata time window
- the Fingrid local-to-UTC parser
- the v2 classifier abstains on short clips and returns calibrated probabilities


## 13. US grids (added 2026-11-03)

### Sources wired in

| Source | Grid | Span (UTC) | Usable data | Step | Trust | Notes |
|---|---|---|---|---|---|---|
| Zenodo, Hartmann et al. | US West | 2024-01-16 → 2024-11-18 | 6379 h | 1 s | full | Rows flagged QI=2 (filled in) are dropped, not used. |
| Zenodo East | US East | 2023-06-18 → 2023-07-06 | 392 h | 1 s | full | Identical to OSF US_FL01 (r = 0.99999999, max diff 0.002 mHz over 445 h), so it is only a fallback when OSF is missing. |
| Pigott, Phoenix AZ | US West | 2022-02-14 → 2023-02-23 | 8587 h | 5 s | 0.9 | Clock offset inferred (below). Race tries extra shifts of -1, +1 and +7 h and pays for them in p. |
| nate-griff FNET scrape | West, East, Texas, Quebec | 2026-03-20 → 2026-05-12 | about 1100 to 1250 h each | about 2 s | low (0.5) | Clipped readings at ±49.5 mHz are masked (3 s padding). A low-trust winner is capped at "likely" and needs 1.5 times the usual margin. |
| OSF weeks | West, Texas, East | 2019 and 2023 weeks | as before | 1 s | full | unchanged |

The GUI's ENF tab now has a "Built-in grid log" reference choice (any grid), a coverage timeline plus a table of US spans, and a tick on each grid whose logs cover your search window. Screenshot: `gui_screenshots/enf_us_00_coverage.png`.

### Pigott clock offset

The log's timestamps are the logging Pi's local clock. I compared its average daily frequency profile with the 2024 WECC profile, at every offset.
- Best fit: clock = UTC-7 (Arizona time, no daylight saving), r = 0.90.
- Next best: UTC-6.83 at 0.73, UTC-6 at 0.70, UTC-8 at 0.68. Treating the clock as UTC gives -0.35.
- The top-of-the-hour pattern lines up at zero extra shift (r 0.87), and the start-of-minute dip pattern at zero shift (r 0.98).
- This is inferred, not checked against a concurrent log (none overlaps 2022), so it stays [VERIFY]. Plot: `gui_screenshots/enf_us_pigott_tz.png`; data: `validation_runs/enf_pigott_tz.json`.

### Simulated validation (`scripts/enf_validate_us.py`, `validation_runs/enf_us.json`)

Clips are cut from held-out stretches of the logs, then pushed through the simulated microphone chain (random harmonics, SNR -22 to +10 dB, recorder clock error, stalls, interference) and the normal ENF extraction. Each clip is then raced against every grid at its time with a random search window around the truth. "Confident wrong" means a likely or decisive answer naming the wrong grid. Controls: European clips at the same 2024 dates, and no-hum clips.

**Part A: WECC 2024 clips, race against West, East, Texas, GB, CE and Nordic** (96 West clips per row; 16 clips per control)

In 2024 only the US West log exists among 60 Hz grids, so a normal (60 Hz only) race has no US competitor and is capped at "likely". The cross-nominal row also races the 50 Hz European grids, shifted to 60 Hz, as a control. That shows the match is not just "any grid log fits", but it is not proof against East or Texas.

| Window | Race | West answered | West accuracy when answering | Confident wrong | Decisive | Time within 5 s |
|---|---|---|---|---|---|---|
| ±10 min | 60 Hz only | 66 % (abstain 34 %) | 100 % | 0 | 0 (capped) | 97 % |
| ±10 min | with 50 Hz controls | 76 % (abstain 24 %) | 100 % | 0 | 43 | 95 % |
| ±1 h | 60 Hz only | 56 % (abstain 44 %) | 100 % | 0 | 0 (capped) | 98 % |
| ±1 h | with 50 Hz controls | 62.5 % (abstain 37.5 %) | 100 % | 0 | 38 | 97 % |
| ±6 h | 60 Hz only | 50 % (abstain 50 %) | 100 % | 0 | 0 (capped) | 100 % |
| ±6 h | with 50 Hz controls | 53 % (abstain 47 %) | 100 % | 0 | 33 | 100 % |

Controls in the same races (answered, all correct, 0 confident wrong):
- ±10 min: CE 15/16, GB 10/16, Nordic 13/16
- ±1 h: CE 14/16, GB 10/16, Nordic 10/16
- ±6 h: CE 11/16, GB 7/16, Nordic 10/16
- No-hum clips: 0 of 16 answered in every window.

**Part B: 2026 four-way US race on the FNET scrape** (West, East, Texas, Quebec; 20 clips each, Quebec 17)

Caution: these clips are cut from the scrape itself, so the reference is the same data the clip came from. That makes it optimistic for r. It does test whether the four US logs are distinct enough to tell apart, and it tests the low-trust cap. All answers were capped at "likely" (low-trust source).

| Window | West abstain | East abstain | Texas abstain | Quebec abstain | Accuracy when answering | Confident wrong |
|---|---|---|---|---|---|---|
| ±10 min | 40 % | 10 % | 15 % | 47 % | 100 % | 0 |
| ±1 h | 40 % | 10 % | 30 % | 53 % | 100 % | 0 |
| ±6 h | 40 % | 15 % | 35 % | 53 % | 100 % | 0 |

**Part C: Phoenix 2022 (Pigott) clips, ±1 h** (30 clips): answered 60 %, all correct, 0 confident wrong, time within 5 s on all answers. All 18 answers chose no extra clock shift, which agrees with the UTC-7 inference.

Extra check (`scripts/enf_pigott_tzsearch_check.py`, `validation_runs/enf_pigott_tzsearch.json`): I deliberately set the assumed offset one hour wrong (UTC-6). The grid answer was still right in 18 of 18 answers. But the time was right in only 4; the other 14 were exactly one hour off. In a window wider than an hour, a one-hour clock error and a one-hour time error look the same. So the race now says, for this log, that the matched time could be off by the searched shifts (-7, -1 or +1 h). Trust the grid, not the hour, from the Pigott log.

**Part D: finding the time in all of WECC 2024, no time hint** (96 clips; each one searched against the whole 10-month log, about 11 s per clip)

| Clip length | Clips | Right time (within 5 s) | Labelled confident | Confident and right | Confident and wrong |
|---|---|---|---|---|---|
| under 5 min | 11 | 8 | 0 | 0 | 0 |
| 5 to 10 min | 27 | 20 | 14 | 14 | 0 |
| 10 min or more | 58 | 47 | 20 | 20 | 0 |
| all | 96 | 75 (78 %) | 34 (35 %) | 34 | 0 |

The false-match chance is multiplied by the full number of positions searched, about 26 million, so it is strict. Many correct finds (r around 0.8) are labelled "weak" because of that. When it does say confident, it was right every time in this test.

### Caveats

- Simulation, not real phone recordings in the US. No real US recording with a known time was available.
- 2024 has no East or Texas log, so the 2024 West answer is "likely, one grid checked", not proof against the other US grids. Only in 2026 (scrape, low trust) can US grids race each other.
- The 2026 test is circular (clips from the scrape itself).
- The cross-nominal control is a sanity check, not a real competitor: a recording's hum frequency already tells 50 from 60 Hz.

## 14. US West from seismometers (added 2026-11-03)

`provenance enf-rebuild` (module `provenance_fx/enf/seismic.py`) pulls public FDSN dataselect waveforms over HTTPS
from about 16 Western stations, tracks the 60 Hz hum line at 1 s, runs the agreement gate (a station must agree
with the median of the others, r ≥ 0.75 after 5 s smoothing (`R_TRUST` in the code; an earlier draft of this page said 0.80), for three 10-minute windows) and writes the median
of trusted stations to `~/.cache/provenance/enf/us/seismic/US-WEST/YYYY-MM-DD.csv.gz`. The race loads it as
"US West (seismic)", trust 0.9, so Zenodo wins where both cover. `provenance enf-collect` (`seismic_live.py`)
does the same live over one SeedLink connection (wss, port 443).

Script: `scripts/enf_seismic_validate.py`, output `validation_runs/enf_seismic.json`. Truth is the Zenodo
WECC 2024 1 s log (QI=0 rows only). Tuning days 2024-03-05 and 2024-03-12 set the 1 s label shift; the
six test days were not looked at before this run.

### Reference quality against Zenodo

r and rmse (mHz) per day. "No Anza" drops the four PB.B08x boreholes, which share one site. "Live set" is
the stations that actually streamed live on 2026-11-03.

| Day | Split | Coverage | r | rmse | 95th pct error | Median stations | No Anza r / rmse | Live set r / rmse |
|---|---|---|---|---|---|---|---|---|
| 2024-03-05 | tune | 100.0 % | 0.9962 | 1.53 | 2.99 | 9 | 0.9855 / 2.99 | 0.9852 / 3.02 |
| 2024-03-12 | tune | 100.0 % | 0.9974 | 1.54 | 3.02 | 9 | 0.9864 / 3.55 | 0.9868 / 3.47 |
| 2024-02-07 | test | 100.0 % | 0.9951 | 1.74 | 3.43 | 9 | 0.9827 / 3.29 | 0.9836 / 3.20 |
| 2024-04-17 | test | 100.0 % | 0.9955 | 1.84 | 3.69 | 8 | 0.9854 / 3.32 | 0.9868 / 3.15 |
| 2024-05-22 | test | 100.0 % | 0.9937 | 2.22 | 4.47 | 7 | 0.9875 / 3.15 | 0.9891 / 2.94 |
| 2024-06-19 | test | 100.0 % | 0.9904 | 2.17 | 4.36 | 7 | 0.9814 / 3.04 | 0.9842 / 2.79 |
| 2024-09-11 | test | 100.0 % | 0.9954 | 1.71 | 3.44 | 7 | 0.9883 / 2.75 | 0.9858 / 3.03 |
| 2024-10-23 | test | 100.0 % | 0.9943 | 1.72 | 3.41 | 8 | 0.9891 / 2.38 | 0.9887 / 2.43 |

Bias is under 0.1 mHz on every day. After the 1 s label shift the best lag still reads +1 s, but it raises
r by only about 0.0003, so timing is good to about 1 s. [VERIFY] whether a 2 s shift is better.

### Race on simulated clips: seismic in place of Zenodo

48 clips with hum plus 6 without, cut from Zenodo on the six test days (mic_chain: random harmonics,
SNR -22 to +10 dB, clock drift, stalls, interferers). Same clips raced twice: once with Zenodo as the US West log
(seismic off), once with seismic only (Zenodo off). 50 Hz grids are in the race as the cross-nominal control.

| Window | Reference | Answered | Right when answered | Confident wrong | Decisive | Start within 5 s |
|---|---|---|---|---|---|---|
| ±10 min | Zenodo | 36 / 48 | 100 % | 0 | 26 | 94 % |
| ±10 min | Seismic | 36 / 48 | 100 % | 0 | 26 | 94 % |
| ±1 h | Zenodo | 34 / 48 | 100 % | 0 | 21 | 94 % |
| ±1 h | Seismic | 34 / 48 | 100 % | 0 | 21 | 94 % |
| ±6 h | Zenodo | 32 / 48 | 100 % | 0 | 19 | 94 % |
| ±6 h | Seismic | 32 / 48 | 100 % | 0 | 18 | 94 % |

Paired, the two references answered exactly the same clips, with the same start time to within 2 s, in all
six settings. No clip was answered by only one of them. The no-hum clips: 0 of 6 answered with either.
Without the 50 Hz control in the race, the answered counts are the same for both (35, 31, 27), "likely"
only, since a single 60 Hz candidate cannot be decisive in 2024.

### Time finding with no hint

Each clip searched against all eight rebuilt seismic days (about 690,000 start positions).

First run: 38 of 48 found within 5 s; 24 labelled confident, 23 right and 1 wrong. The wrong one (clip 12,
18 minutes, r 0.955) was off by 12.1 s. It is not a seismic problem: the same clip was also 11.5 s off when
raced against Zenodo. The simulated recording has a stall (about 19 s of audio silently missing), so the
best overall fit sits on the longer stretch after the gap and the reported start moves by the missing time.

Fix: the existing continuity check (each 5-minute piece matched on its own) already saw the break. Now, when
it finds a jump and the first piece matches well (r of at least 0.8), the result also reports the start of
the first piece and adds a "timeline break" warning (GUI and CLI), saying to trust the start to tens of
seconds. `provenance_fx/enf/match.py: apply_continuity`, called from the pipeline; the global best fit is unchanged.

Re-run with the fix (`scripts/enf_seismic_validate.py --part3-only`): 40 of 48 within 5 s; 24 confident,
24 right, 0 wrong. Three clips were flagged with a break: clip 12 went from 12.1 s to 4.0 s off, clip 42
from 13.4 s to 5.0 s, clip 35 from 4.7 s to 1.0 s. The fix was checked on the same clips it was designed
from, so it is not an independent test; a stall that cuts the first piece itself is not corrected.

### Live run on this computer (2026-11-03, `provenance enf-collect`)

Ran from 21:00 to about 22:45 UTC (1:00 to 2:45 PM PST) in several stretches. All 16 stations were
accepted by the SeedLink server; 9 West stations actually sent data (the four Anza boreholes PB.B082/84/86
and UI.MGOO sent nothing live).

- Trusted West data written live: about 49 minutes (2,947 s) in windows 21:10, 21:20, 21:30, 22:10 and
  22:30 UTC, with 5 or 6 trusted stations (2 at 22:30). Logs: `validation_runs/seismic_live_run*.log`.
- Against an independent archive rebuild of the same seconds (`scripts/enf_seismic_live_vs_archive.py`,
  `validation_runs/enf_seismic_live_vs_archive.json`): 2,347 s compared, r 0.989, rmse 3.1 mHz, 95th
  percentile 7.0 mHz, bias -0.01 mHz, best lag 0 s. Same stations, so this checks the live pipeline, not
  the grid truth.
- The race loads the live file: a simulated 25-minute clip built from the archive rebuild (true start
  21:12:00 UTC) won US West against "US West (seismic)" with r 0.993 at 21:12:00 (CLI) and decisive at
  21:11:59 in the GUI. Screenshot `gui_screenshots/enf_seismic_02_live_collector_today_west_wins.png`.

Why the gaps. The development machine was paused while idle (the collector's own process clock ran
about 6 to 12 minutes behind the wall clock after each pause). A pause leaves the network connection
silently dead. Three fixes came out of this, all in `provenance_fx/enf/seismic_live.py`:
1. a watchdog reconnects after 120 s with no data, resuming from each station's last sample;
2. a window is held, not written off as empty, while the stream is behind;
3. trust states are saved (`gate_state.json`) and reused on a restart within an hour.
After a pause the trust streaks often restart, so 20 to 30 minutes after each pause wrote nothing; on
the 22:20 window the live tracks also correlated lower (r 0.66 to 0.83) than archive tracks did on the
22:00 and 22:10 windows (0.79 to 0.96, leaving out OZET). The likely cause is the half-filled windows around each pause; it was not proven.
On a computer that does not sleep this should not happen, but that has not been tested here.
`provenance enf-rebuild --fill-only` fills the holes from the archive afterwards.

### Texas and East

The three Texas stations did not pass the agreement gate with one another on the 2024 days,
so no Texas consensus was written. No East stations are validated. Both options are experimental.

### Limits

- Same grid only: this replaces a missing West log, it does not add a competitor grid.
- The test days are 2024; station health changes over time. The gate drops stations that stop agreeing.
- EarthScope says archive downloads need an account from 2026-12-15. [VERIFY] whether anonymous
  dataselect and SeedLink keep working.

## 15. Video light flicker (added 2026-11-03, version 0.2.0)

Method summary: README, Methods and math, section 12. Code: `provenance_fx/enf/video.py`, renderer `provenance_fx/enf/video_sim.py`.



**Simulated is not real.** These videos are rendered by `provenance_fx/enf/video_sim.py`: a textured, lamp-lit room filmed by a simulated rolling- or global-shutter camera, with the lamp's flicker driven by real 1-second grid logs (Zenodo WECC 2024, NESO GB 2024, Energy-Charts CE 2024), sensor noise, optional pans, hand-held jitter and exposure steps, and H.264 through ffmpeg. The renderer encodes our own assumptions about cameras. Script: `scripts/enf_validate_video.py`; results: `docs/validation_runs/enf_video.json`. One seed per camera setting at 2 and 5 minutes, plus a partial first run at 10 minutes (13 clips). The sample is small; treat the numbers as a smoke test, not a benchmark.

Extraction (correlation r and RMS error against the true grid log, for clips the tool tracked):

| Camera setting | 2 min | 5 min | 10 min |
|---|---|---|---|
| Rolling shutter, 29.97 fps, 25 ms, crf 23 | r 0.971, 1.7 mHz | abstained | r 0.974, 1.8 mHz (2 clips) |
| Rolling shutter, exactly 30 fps, 20 ms | r 0.748, 2.8 mHz | r 0.915, 2.7 mHz | r 0.789, 6.1 mHz |
| crf 18, keyframe every 60 frames | weak, wrong grid frequency | r 0.981, 1.4 mHz | r 0.990, 1.4 mHz |
| crf 30 (heavier compression) | abstained | abstained | abstained (2 clips) |
| Flicker depth 1 % | weak, wrong grid frequency | abstained | abstained (2 clips) |
| Hand-held: pans, jitter, exposure steps | weak, r 0.730 | r 0.889, 4.2 mHz | r 0.976, 2.5 mHz |
| Global shutter, 29.97 fps, 60 Hz (alias 0.12 Hz) | abstained | abstained | 1 of 2 tracked, r 0.970 |
| Rolling shutter, 25 fps, GB 50 Hz, 30 ms | abstained | r 0.986, 3.8 mHz | not run |
| Global shutter, 29.97 fps, GB 50 Hz (alias 10.09 Hz) | r 0.992, 3.4 mHz | r 0.981, 2.3 mHz | not run |
| Rolling shutter, 30 fps, CE 50 Hz, 25 ms | r 0.997, 1.3 mHz | r 0.781, 7.9 mHz | not run |

- Read-out time, when searched and bands were seen: median error 0 to 0.4 ms.
- Controls (no flicker, anti-banding exposure of 1/120 s, inverter lamp at a fixed 120 Hz): all 6 abstained.
- The two "weak, wrong grid frequency" rows picked the 50 Hz reading of a 60 Hz clip; they were labelled weak and were not raced.

Grid race on the picture alone (no sound), same rules as audio:

| Clip length | Window ±10 min | Window ±1 h |
|---|---|---|
| 2 min (10 flicker clips) | 0 answered (the race needs 3 minutes) | 0 answered |
| 5 min (10 flicker clips) | 6 answered, 6 right, 0 confident-wrong | 3 answered, 3 right, 0 wrong |
| 10 min (13 flicker clips) | 8 answered, 8 right, 0 wrong | 7 answered, 7 right, 0 wrong |
| Controls (6 clips) | 0 answered | 0 answered |

All answers were "likely"; none was "decisive". Every right answer also had the start time within 5 seconds. In 2024 only US West has a 60 Hz log, so 60 Hz races are single-grid races.

Audio versus picture (6 minute clips with sound, full pipeline): 3 genuine clips all said **agree**. Of 3 clips whose sound after 3 minutes came from 11 hours later, one said **partly disagree**, one **disagree** and one **inconclusive**. None of the spliced clips said agree.

**Real footage.** The CC BY 4.0 ENF Moving Video Database (Fernández-Menduiña and Pérez-González, University of Vigo, Zenodo 10.5281/zenodo.3549379) has phone videos with mains recordings made at the same time, on the 50 Hz Continental European grid in 2019. Two videos were tested against all 9 mains recordings in the set (`docs/validation_runs/enf_video_real_zenodo.json`):

| Video | Best-matching mains file | r | Next best r | Presence |
|---|---|---|---|---|
| MOV1_20190505_110016A (static scene) | its own, 20190505_110029 | 0.841, "moderate", 7.2 mHz RMS | 0.470 | weak (bands 4.3 dB) |
| MOV2_20190508_200450A (mostly static) | its own, 20190508_200340 | 0.978, "strong", 1.9 mHz RMS | 0.512 | weak (bands 2.2 dB, 37 % of frames dropped) |

Both picked the right mains recording. The offset within the file is less sure: MOV2 came out at 81.7 s where the file names suggest about 70 s, and MOV1 hit the edge of the search (−2 s where the names suggest about −13 s). The file-name clocks are not documented [VERIFY]. Both files are variable-frame-rate (measured 29.987 and 30.026 fps). The grid race could not be tested on them: no free CE log covers 2019. The other 7 videos in the set (2.2 to 3.5 GB each, including the fully moving MOV3 set) were not downloaded.

### Problems found and fixed during validation

- **Keyframe pumping at 29.97 fps.** x264's default of a keyframe every 250 frames gives a brightness rhythm at 0.1199 Hz, the same as the 120 Hz alias. Before the guard, a no-flicker clip and an anti-banding clip came out "weak", and a low-flicker hand-held clip "present" with r 0.10 (wrong). After the guard all three abstained.
- **Per-GOP codec offsets.** On 10-minute clips the rolling-shutter path lost about half its seconds, because each group of pictures adds a fixed pattern to the band fit. Removing each group's mean raised the tracked share on a 10-minute crf 23 test from 0.47 to 0.99 (r 0.992 before, 0.991 after, on the tracked seconds). A crf 30 clip still failed, but now abstains instead of answering weakly with 87 mHz error.
- **Keyframes counted as motion.** With a keyframe every 2 s, every keyframe was flagged as camera motion and no 4 s stretch survived. One-frame spikes on keyframes are now ignored. A 1-second-lag motion score was added because slow pans were not being detected (4 frames flagged on a clip with two pans; 165 after the change).
- **Variable frame rate.** Real phone files label 30/1 but run at 29.987 fps. The mean rate is now fitted from packet times.

### [VERIFY]

- Row read-out order (top to bottom) and a constant read-out rate on real phones; front cameras and rotated video.
- Whether frame-time jitter in real files is container rounding or real capture timing.
- Real read-out times per phone model; the search range is 4 ms to one frame.
- Keyframe behaviour of phone encoders (Apple, Qualcomm, Samsung), which differs from x264.
- The pumping guard thresholds (8 dB, 20 dB, 0.06 Hz) were set on simulated x264 clips.

### Where real tests could come from

- More of the CC BY 4.0 ENF Moving Video Database (7 videos not yet downloaded, including the moving MOV3 set).
- The IEEE DataPort rolling-shutter sets by Choi and others (DOI 10.21227/ch9h-s046 and 10.21227/ykgm-4q17): need an IEEE account, not used.
- Zenodo 10.5281/zenodo.3407735 (ENF Moving Video Database I): files restricted, not used.
- Han and others (2022) point to sample videos from their GitHub page; license not checked [VERIFY].
- Your own clips filmed next to a home logger (`home_logger/`), which gives ground truth for your own grid.
