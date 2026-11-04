# Scope: an ENF (power-grid hum) tab for Provenance

Prepared Tuesday, November 3, 2026. This is a proposal only. No Provenance code has been changed. Sources and evidence are in `enf_research.md`, and the paper numbers in brackets below refer to its bibliography.

## 1. What the tab would answer

1. **Is there grid hum in this file?** Yes or no, with a confidence, per harmonic.
2. **Which grid?** 50 versus 60 Hz is certain. US Eastern, Western or Texas is a probability. Inside a grid, the answer is "not determinable" unless special reference data exist.
3. **When was it recorded?** Only if we hold reference data covering the right days. The output is a ranked list of start times, each with a match score and how unusual that score is.
4. **Was it edited?** Possible cut and splice points, from jumps in the hum's phase or frequency.
5. **Privacy check:** "Does my recording leak its time and grid?" and "Does a notch filter fix it?" This mirrors the existing Doppler audit tab.

It would not give a distance or radius from a power station. Every generator on a grid shares one frequency, so that quantity doesn't exist (see `enf_research.md`, section 5).

## 2. How it combines with the Doppler results

- **Time first, then place.** A confident ENF timestamp turns the Doppler search's unknown multi-hour window into a window of a few minutes. That makes the ADS-B search much faster and removes most false flight pairs.
- **Grid as a fence.** The grid answer limits the map search box to that interconnection's footprint. A boundary polygon would be needed; a candidate source is the US federal HIFLD or EIA interconnection map [VERIFY license].
- **Cross-check.** The Doppler winner's flyover times must agree with the ENF time, and its location must lie inside the ENF grid. If they disagree, the report flags it in red rather than silently picking one.
- **One combined privacy verdict.** For example: "This file reveals: grid (high confidence), time (only if a reference exists), position (via planes, medium)."
- **Order of operations.** ENF must read the raw audio. Provenance's current steady-tone removal (the 60-second running median) and the clean-up step's hum removal delete exactly the hum ENF needs. The ENF tab will always use the untouched track and say so on screen.

## 3. Proposed design

### 3.1 New modules (Python, NumPy and SciPy only for the core)

| Module | Job | Method and source |
|---|---|---|
| `provenance_fx/enf/extract_audio.py` | Raw audio to an ENF trace, one value per second, plus a per-second confidence | 1. Downsample to about 1 kHz. 2. Auto-pick 50 or 60 Hz from harmonic energy. 3. Band-pass each harmonic (1 to 7 times nominal). 4. STFT with 8–16 s frames, 1 s hop, zero padding and quadratic peak interpolation. 5. Estimate local SNR per harmonic [8]. 6. Keep only the harmonics whose traces agree with each other, a simplified version of [14]. 7. SNR-weighted combining [8]. 8. Dynamic-programming ridge tracking [10]. Optional high-resolution refinement (ESPRIT) for clips under 2 minutes [7]. |
| `provenance_fx/enf/detect.py` | "Is ENF present?" gate | The detector from [15], plus checks that harmonics agree and that the trace looks like the grid (an AR-model fit). |
| `provenance_fx/enf/extract_video.py` | Video to an ENF trace | ffmpeg decodes luminance. A static-region mask removes moving parts [30]. Two paths: (a) frame mean, for when the aliased frequency is non-zero, with a warning at exactly 30 or 60 frames per second in 60 Hz grids; (b) the rolling-shutter row signal with periodic zeroing-out [33], using a camera read-out-time table or the estimator in [35]. |
| `provenance_fx/enf/reference.py` | Load and cache reference data | Adapters: NESO monthly CSV (GB, free, from 2014); power-grid-frequency.org and OSF CSVs; Fingrid; ENF-WHU references; SP Cup power recordings (computed into traces); a generic CSV importer with time-zone handling; "my reference recorder" logs. FNET only if access is granted. All times stored internally in UTC. |
| `provenance_fx/enf/match.py` | Find the start time | 1. FFT-based normalised cross-correlation of the trace against the reference, coarse then fine. 2. Search a small clock-drift range (about ±100 parts per million) [18]. 3. Report the top candidates with correlation, the gap to the next-best match, and a null-distribution p-value from random reference segments, per the reliability findings in [20]. |
| `provenance_fx/enf/tamper.py` | Find edit points | Phase-continuity analysis [23] and instantaneous-frequency jumps [24]. Flags are shown as "possible edit," never as proof. |
| `provenance_fx/enf/gridid.py` | Grid classification | Features from [42] (mean, variance, range, wavelet variances, AR coefficients) feed a small classifier (scikit-learn, logistic regression or SVM), trained on SP Cup 2016 data. Separate models for audio and for power recordings, as the winning teams used. |
| `provenance_fx/enf/audit.py` | Privacy check | Measure the ENF SNR per harmonic. Apply notch filters or replacement. Re-run the detector and matcher to show whether time and grid are still recoverable. |
| `provenance_fx/enf/simulate.py` | Synthetic test data | AR(1) ENF generator [16, 20]. Harmonic hum synthesis with chosen SNR per harmonic, a 100 Hz phone-style high-pass, codec round-trips through ffmpeg (AAC, MP3, Opus), recorder movement, and splices. |

New dependency: scikit-learn, for grid ID only. Optional: libhum (LGPL) as a GPU-accelerated cross-check, never required.

### 3.2 GUI: a third tab, "Grid hum (ENF)"

It uses the same dark theme, the same loaded file and the same job runner, and it follows the existing five-step layout.

1. **Detect.** Spectrogram strips one hertz wide around each harmonic (60, 120 … 420 Hz, or the 50 Hz family), each with an SNR badge, plus a "hum found or not found" verdict. If the tab sees that a cleaned file was loaded, it says it is using the raw track.
2. **Extract.** A plot of the ENF trace over time, with harmonic check-boxes and a confidence band. Shows each harmonic's trace faintly and the combined trace boldly, so you can see agreement.
3. **Reference.** Pick a source (NESO, OSF, CSV upload, my recorder log, sample data), the date range to search, and the time zone. It shows coverage gaps on a timeline.
4. **Match and tamper.** A correlation-versus-time plot with the top candidate times listed in both your local time and UTC. An overlay of trace and reference at the best match. Possible edit points are marked on the waveform.
5. **Grid and combine.** A probability bar chart for each grid. A "Send time window to Doppler search" button, and a combined privacy verdict.
- Exports: Markdown report section, JSON, and the trace as CSV.

### 3.3 Data sources to use

- **Build and prove the matcher:** NESO GB 1-second data. It is free, has 12 years of history, and its license allows reuse.
- **Prove extraction on real noisy audio:** ENF-WHU, 130 recordings with ground-truth references, MIT license.
- **Prove grid ID, including US West, East and Texas:** SP Cup 2016 (IEEE DataPort, CC-BY), whose ground-truth labels are published.
- **Prove video:** the Choi et al. rolling-shutter dataset on IEEE DataPort.
- **US Western timestamping, for your own recordings:** start a local reference recorder now. A commercial AC-to-AC wall adapter feeds a resistor divider into a USB sound card, logged with NTP or GPS time. That's about $30–60 of parts [estimate]. No public free history exists, so recordings made before logging starts can be grid-identified and edit-checked but not timestamped. Request FNET/GridEye access in parallel if history matters.

## 4. Effort estimate

This is a rough planning estimate in focused engineering days, not a promise.

| Phase | What ships | Estimate |
|---|---|---|
| 1. Minimum useful version | Audio extraction, the detector, CSV and NESO references, matching, the privacy audit, the GUI tab steps 1–4 for audio, and synthetic plus NESO tests | 7–10 days |
| 2. Validation on real data | ENF-WHU benchmark, a recording-length study, codec study, report section | 3–4 days |
| 3. Grid ID | SP Cup training and evaluation, the GUI bar chart, the grid fence on the Doppler map | 3–5 days |
| 4. Edit detection | Phase and frequency splice detection, with tests on synthetic splices | 2–3 days |
| 5. Video | Frame-mean and rolling-shutter paths, static mask, read-out-time handling, tests on the Choi dataset | 5–8 days |
| 6. Doppler fusion | Time-window hand-off, cross-check, combined verdict | 2–3 days |
| **Total** | | **About 22–33 days.** The minimum version alone is 7–10. |

## 5. Risks

- **No free US reference history.** This is the biggest risk. Timestamping US recordings depends on your own logger going forward or on FNET's goodwill. Mitigation: ship grid ID and edit detection, which need no reference, and make the logger easy.
- **Many recordings have no usable hum.** That includes outdoor recordings, phones that cut below 100 Hz, voice codecs and noise suppression, and recorders on the move. The author's outdoor test recording shows only weak, inconsistent hum. Mitigation: the detector gate, and honest "not present" results rather than forced matches.
- **False matches on short clips.** Under about 2 minutes, wrong matches look convincing. Mitigation: always report the next-best gap and a p-value, refuse to call a winner below a threshold, and encourage a narrow date window.
- **Fake 120 Hz lines.** Equipment noise can mimic ENF. Mitigation: require cross-harmonic agreement and a grid-like trace.
- **Video variability.** LED drivers, exposure settings, motion, unknown read-out time and phone stabilisation all interfere. Expect video to work mainly indoors under incandescent, halogen or flickery LED light with a static camera.
- **Grid classifier ageing.** The SP Cup data is from about 2015. Grid behaviour may have changed with more solar and batteries [VERIFY]. Mitigation: retrain with your own logger and the OSF data.
- **Anti-forensics.** ENF can be stripped or faked [55]. Mitigation: treat it as supporting evidence, and pair it with the tamper check.
- **Licenses.** The best video code has no license and some extraction code is non-commercial. Mitigation: write our own code from the papers and use MIT or LGPL tools only as external cross-checks.
- **Ethics.** Same stance as the Doppler tool: built for checking your own recordings and for privacy awareness, not for dating or locating other people's media without a legitimate reason.

## 6. Test and validation plan, using real public data

1. **Unit tests (synthetic, runs in CI).**
   - The AR(1) ENF and harmonic synthesizer recovers a known trace with error under 5 mHz at 0 dB SNR [target to confirm].
   - The phone high-pass case (no 60 Hz) still recovers the trace from the higher harmonics.
   - A known splice is detected at the right second.
   - The aliasing math for 29.97, 30, 59.94 and 60 frames per second is right.
2. **Matcher on real reference data (NESO).**
   - Cut random segments from NESO 1-second data of 1, 2, 5, 10 and 30 minutes. Add noise at several SNRs. Match against windows of a day, a week and a month.
   - Measure the hit rate within 10 seconds, and compare with the curves in Hua et al. 2020. Pass if the 10-minute, one-week case is above 95 percent at minus 20 dB.
3. **Extraction on real noisy audio (ENF-WHU).**
   - Run all 130 recordings and compare the extracted trace to the supplied reference, by correlation and error.
   - Pass if the median correlation is above 0.8 and the error is in the same range as Hua 2021's published normalised error for its best method (about 13 × 10⁻⁵) [target to confirm on our scale].
   - Then do a full time match of each recording inside a 24-hour reference built from the dataset, if its references allow it [VERIFY].
4. **Codecs.** Re-encode ENF-WHU clips through AAC 128k, MP3 128k, Opus 32k, and a voice-like AMR or Opus 12k. Record how detection and matching degrade.
5. **Grid ID (SP Cup 2016).**
   - Train on the training sets, test on the published practice and test sets with their ground truth.
   - Report accuracy overall and for US East (C), US West (I) and Texas (A). For context, compare with the competition teams' reported results [VERIFY numbers].
6. **Video (Choi et al. dataset).** Extract from their videos and compare with the supplied power references. Pass if correlation is above 0.8 on static scenes.
7. **Your own Western Interconnection check (needs your OK and a logger).**
   - Run the reference logger at home for a week.
   - Make about 10 phone and recorder clips, 2–30 minutes long, indoors near a fridge or fan, plus one or two videos under an incandescent or LED bulb. Then do a blind match.
   - This is the only way to validate US-West timestamping without FNET data.
8. **Integration with Doppler.** On the existing simulated scene, inject a synthetic ENF track with a known time. Confirm the ENF time hands the right window to the Doppler search and that it speeds the search up. Report the speed-up.

## 7. Recommended build approach

Build phases 1 and 2 first: audio only, NESO and CSV references, the detector, the audit, and the GUI tab. That gives a working, honest tool in about two weeks and proves the matcher on 12 years of real free data. Add grid ID (phase 3) next, because it is the one location-type answer that works for US recordings without any reference. Video comes last, because it is the most fragile. In parallel, start a reference logger at home and email FNET about data access; that email would be yours to send.

## 8. Decisions needed from you

1. Do you want to set up a home reference logger? If yes, I can spec the parts and safe wiring next.
2. Should I draft an email to FNET/GridEye (Prof. Yilu Liu, liu@utk.edu) asking about access to Western Interconnection history? I would draft it only; nothing would be sent without your OK.
3. Is video in scope for the first release, or audio only?
4. Is it OK to add scikit-learn as a dependency for grid ID?
