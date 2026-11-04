# Validation

There are two parts. Part 1 checks the tool against the author's own reference recording and real ADS-B data, and compares the result with his stated answer. Part 2 checks it against simulated scenes where the true location is known exactly.

## Part 1: the author's reference recording

### What was linked

- The video description links the full raw recording: "Unknown location - raw audio", https://youtu.be/4CxVxuMVkMc. It is 1 hour long and was uploaded November 1, 2026 by colsto.
- The pinned comment only links his Discord and recommends Benn Jordan's channel. It has no data or code.
- No code, ADS-B extract, or coordinates file is linked. The author's answer had to be read from the video itself.

### The author's stated answer

These were read from frames of the video at about 23:55 to 24:00. Copies of the frames are in `reference_validation/author_frames/`.

- Two-event result, flight pair combo 1 of 7: 40.876466, -73.524951. His combined score was 20.48; the runner-up scored 15.25.
- One-minute, known-time result: 40.877922, -73.531941.
- His two answers are about 610 m apart.
- His stated accuracy is "within ~100 m" (from the description) and "within a couple hundred feet" (from the narration).
- The location is on the North Shore of Long Island, New York, on a bank by the water. This comes from the coordinates; the place name is never said in the video. [VERIFY] the exact site.
- The date is September 8. The year is assumed to be 2026, because both uploads are from 2026 and his flight IDs match a recent dataset. [VERIFY]

### What my tool measured from the recording

The two flyovers are clearly visible. A crop of the spectrogram is in `reference_validation/reference_spectrogram_crops.png`.

| Event | Window in the uploaded hour | Base pitch | Fitted speed (range) | Fitted closest slant distance (range) | Heard closest approach |
|---|---|---|---|---|---|
| 1 | 2090 to 2225 s | 113 Hz | 133 m/s (107 to 187) | 5.6 km (3.1 to 10.0) | 2155 s |
| 2 | 3040 to 3088 s | 136 Hz | 90 m/s (72 to 125) | 2.1 km (1.1 to 3.7) | 3071 s |

- The measured gap is 916 seconds. The author says 920. That is a match.
- His panels show the same two curves at about 5,750 s and 6,670 s of elapsed time, which suggests the YouTube upload is one hour taken from a longer recording, starting roughly an hour in. This is my inference. [VERIFY]

### ADS-B data used

- Source: the free adsb.lol daily archive for 2026-09-08 (open data, ODbL). It is about 3.9 GB, and it was downloaded without any account.
- I filtered it to a New York metro box. That gave 3,948 aircraft and about 1.78 million position reports, saved as `reference_validation/adsb_nyc_2026-09-08.csv`.
- I added a converter for this data format: `provenance_fx/readsb_hist.py`.

### Search setup, and its honest limits

- Search box: latitude 40.60 to 41.10, longitude -73.90 to -73.20, which is about 55 by 59 km. I picked a box around the region of the answer because a search of the whole continental US is beyond this box's memory and time. This is the "you know roughly what area" case the author describes. It is not a blind US-wide search.
- Time window: the whole day, UTC. The recording time was treated as unknown.
- Terrain: no DEM was available, so the ground was taken as flat at 5 m, with the microphone 4 m up.

### First result (before the ranking changes): mismatch at rank 1, match at rank 4

- My top answer was 40.95073, -73.30049, matched to flights GPD668 (PC12) and FTO381 (C208). That is about 20.6 km from the author's answer. Confidence was flagged as low: it led the next flight pair by only 0.10.
- The author's spot was found, but not on top. At rank 4, my tool lists 40.87789, -73.52193, matched to CST1219 (a Pilatus PC-12 turboprop) and EGE93 (a Beechcraft King Air 350). That point is about 300 m from his two-event answer and about 840 m from his one-minute answer.
- An independent check confirms this pair. Of the 498 flights that passed within 10 km of his coordinates that day, only one pair satisfies every filter: CST1219 passed about 6.1 km away at 137 m/s, and its sound arrived at 20:53:25 UTC. EGE93 followed 923 seconds later, about 3.6 km away at 104 m/s, with no other aircraft within 2.5 km in between. CST1219 and EGE93 are therefore very likely his flights 1100069709 and 1100048665, which are IDs from his own dataset. [VERIFY]
- Scores for the true pair: event 1 scored 2.56, the best of any pair in the top 10. Event 2 scored 1.86, which is weak. The top four totals sit within 0.22 of each other. The author's scoring, by contrast, separated the winner cleanly.
- The first run used a stricter rule: no other close flight at any time in the hour. That run threw out the true spot entirely, because other aircraft were audible earlier in the hour. One example is a Boeing 767 that passed about 1.2 km from his coordinates at 20:23 UTC. I changed the default to the video's rule, silence only between the two events. That change moved the true pair from absent to rank 4.


### After the ranking changes (November 2, 2026)

I made three changes to the scoring and added terrain.
1. **Steady-tone suppression.** A running median per frequency over 60 seconds is subtracted before ridge tracing and scoring. This removed the 160 Hz and 108 Hz lines from the analysis spectrogram.
2. **Contrast scoring.** A candidate curve now scores its brightness minus the brightness 4 Hz above and below it. A curve that only runs through a loud, broad patch, or along a hum, no longer scores.
3. **Per-event normalisation.** Each event's score is divided by the score of the line actually traced in the audio. This keeps a loud event 1 from swamping a faint event 2.
4. **Free terrain.** `--dem auto` downloads AWS Terrain Tiles (zoom 12, about 30 m). The terrain is used for the listener's ground height, which feeds the slant distance and the sound delay.

I ran every combination on the same audio and the same ADS-B extract. Each run took about 5 minutes. The raw records are in `reference_validation/eval_runs.jsonl`. "Event 2 window" is the stretch of audio scored for the second flyover.

| Run | Scoring | Terrain | Event 2 window (s) | Rank of the author's pair | Error of that pair's spot vs the author's answer | Error of my top pick | Lead of #1 over #2 |
|---|---|---|---|---|---|---|---|
| Before (v1_baseline) | old | flat 5 m | 3040–3088 | 4 | 300 m | 20,590 m | 0.10 of 4.4 (2%) |
| v2_flat | new | flat 5 m | 3040–3088 | 5 | 301 m | 20,623 m | 0.04 (2%) |
| v2_all | new | AWS z12 | 3040–3088 | 5 | 301 m | 20,623 m | 0.04 (2%) |
| v1_wide_ev2 | old | flat 5 m | 3035–3110 | **1** | 160 m | **110 m** | 0.84 of 4.68 (18%) |
| v2_wide_flat | new | flat 5 m | 3035–3110 | **1** | 80 m | **86 m** | 0.55 of 1.79 (31%) |
| **After (v2_wide_ev2)** | new | AWS z12 | 3035–3110 | **1** | **80 m** | **86 m** | 0.55 of 1.79 (31%) |

The headline result is that the tool now ranks the author's flight pair first, CST1219 (PC-12) and EGE93 (King Air 350). The best estimate is 40.87677, -73.52401, which is **86 m from his stated answer** (40.876466, -73.524951). Before the changes, the top pick was 20.6 km away and his pair ranked 4th. The GUI run, driven end to end in a headless browser, gave the same answer: 86 m, confidence high.

The table also shows which change mattered.
- **The event 2 window was the biggest factor.** Steady-tone suppression made the second flyover visible from about 3035 s to 3110 s, so I widened the scored window from 3040–3088 to that range. With the wider window, even the old scoring ranks the right pair first. With the old narrow window, neither version does. I chose the window by eye from the cleaned spectrogram, as the author did in the video. The automatic event detector does not yet find this faint second event by itself. [VERIFY]
- **The new scoring sharpened the answer.** With the same wide window, the new scoring moved the best spot from 110 m to 86 m from the author's answer. The pair's own spot moved from 160 m to 80 m away, and the lead over the runner-up grew from 18% to 31%. Steady-tone energy no longer rewards wrong candidates. The runner-up pairs now score about 1.2 against 1.79.
- **Terrain made no measurable difference here.** The answer site is about 1.4 m above sea level and the surrounding area is low. The flat 5 m assumption was already close. Terrain should matter more in hilly areas; the synthetic scenes use hilly terrain and depend on it.

#### A better copy of the audio?

No lossless version is available. YouTube offers the reference video's audio only in lossy formats: Opus at about 102 kb/s (format 251, the one used), AAC at about 129 kb/s (format 140), and lower-rate versions of each. Neither is the original file. The AAC copy is a different lossy encoding, not a cleaner one, so I did not re-run on it. The author does not link an original WAV in the description or the pinned comment. [VERIFY] whether he would share one if asked.

### What limited the first run

1. Event 2 scoring. The second curve is short and faint in the uploaded audio, and it sits next to steady tones at about 160 Hz and 108 Hz. My brightness score picks up those tones for wrong candidates. My traced-line residual was polluted by the same tones, so it did not help either. The author's scoring clearly handled this better.
2. Audio quality. The YouTube upload is Opus-compressed, which smears faint low tones. The author worked from the original file.
3. No terrain model, and no wind or temperature correction.
4. Sparse ADS-B. Archive positions arrive every few seconds to tens of seconds, rather than every second, so the modelled curves are smoother guesses.
5. ADS-B history itself was not a blocker for this date. adsb.lol had the full day for free. It would be a blocker for dates or areas with poor community receiver coverage.

### Bottom line

After the changes, the tool reproduces the author's result. It ranks his flight pair first, puts the best spot 86 m from his answer, and gives the correct 920-second gap between the flyovers (it measured 916 s). It leads the runner-up clearly, by 31%.

Two caveats.
- The search box was about 55 by 59 km around the right area, not the whole US.
- The second flyover's window was set by eye from the cleaned spectrogram. On this test, the tool works as an expert-assisted locator; it is not yet a fully automatic one.

## Part 2: simulated scenes with known truth (re-run after the ranking changes, November 2, 2026)
Each scene: 60 by 60 km box, 6 hours of traffic (about 500 flights, half known jets, plus a busy airport), a hidden listener, a 21-minute clip with two faint propeller flyovers 920 s apart, and a one-minute clip with a known start time.

| Seed | Two-event error (m) | Right flight pair | Lead over runner-up | One-minute error (m) | One-minute, best or near-tie alternative (m) | Run time (s) |
|---|---|---|---|---|---|---|
| 1 | 22 | yes | 0.26 | 39 | 39 | 110 |
| 2 | 79 | yes | 0.36 | 173 | 173 | 67 |
| 3 | 62 | yes | 0.09 | 45 | 45 | 116 |
| 4 | 31 | yes | 0.36 | 1177 | 144 | 85 |
| 5 | 75 | yes | 0.25 | 101 | 101 | 185 |
| 6 | 32 | yes | 0.46 | 2777 | 12 | 70 |
| 7 | 20 | yes | 0.37 | 110 | 110 | 67 |
| 8 | 32 | yes | 0.06 | 109 | 109 | 73 |

Two-event mode within 150 m: 8 of 8.
One-minute mode, top answer within 150 m: 5 of 8.
One-minute mode, truth within 150 m of the top answer or a listed near-tie alternative: 7 of 8.

Compared with the run before the changes:
- **Two events:** still 8 of 8 within 150 m. The median error is unchanged at about 32 m, but the spread is wider: 20 to 79 m now, against 15 to 66 m before. The lead over the runner-up is smaller on several seeds, with seed 8 at 0.06 and seed 3 at 0.09. This is because the new scores are on a smaller scale (contrast and per-event normalisation). On the real recording, the lead grew relative to the score.
- **One minute:** top answer within 150 m is still 5 of 8. Including near-tie alternatives, it improved from 6 of 8 to 7 of 8. Seed 1 went from 10.8 km off to 39 m.
- The raw records are in `validation_runs/` and `validation_synthetic.md`.
