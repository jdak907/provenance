# Design: live ENF aggregator ("gridwatch") — a no-hardware grid reference for Provenance

Date: Tuesday Nov 3, 2026. Status: design only. No Provenance code changed.
Evidence behind every choice is in `live_enf_sources.md`.

## Goal
Keep a running, second-by-second record of grid frequency for each grid (Western first, then Texas and Eastern). Build it only from public sources that pick up grid hum by accident, check them against each other, and store the result in a format Provenance's ENF tab can load like any other reference.

## Sources, by tier
- **Tier A, the backbone: seismic stations over SeedLink.** Live and GPS-timed, with an archive for backfill. Start with the stations that proved out: PB.B088, NN.HYDE, UW.MKAH, UW.WRMB. Add MB.YBMT, UI.MGOO, UW.HOMA and the other PB borehole stations whenever they are streaming.
  - Run a weekly "discovery" scan of the Western station list to find new hum-carrying channels. About 3% of sampled channels qualify.
  - One WSS connection carries all channels (`wss://rtserve.earthscope.org/seedlink`). EarthScope allows up to 5.
  - Backfill gaps from FDSN dataselect. That needs a free EarthScope account after Dec 15, 2026. Jeff signs up himself if wanted; I did not create one.
- **Tier B, independent cross-checks: OpenWebRX receivers** that showed hum (Fullerton, Pasadena, San Francisco).
  - Use them part-time, for example 10 minutes an hour, rather than holding a listener slot 24/7. Ask operators before any continuous use.
  - Never switch a receiver's band profile.
- **Tier C, optional:**
  - KGRID raw data, if the owner grants access by email (the best true reference, March 2024 on).
  - KiwiSDR or WebSDR from a normal home connection.
  - Your own logger later, if wanted.
- **Ground truth for testing:** Zenodo 2024 Western, and the GB, Nordic and continental Europe grid files Provenance already loads.

## Pipeline
1. **Ingest** (one worker per source type):
   - Seismic: SeedLink client → 60-second miniSEED chunks in memory.
   - Radio: OpenWebRX websocket → IMA-ADPCM decode → 12 kHz audio. Wall-clock timestamps come from packet arrival, with a running linear fit to remove the sound-card rate error.
   - Raw waveforms are thrown away after extraction. Optionally keep a 1-hour ring buffer for debugging.
2. **Extract**, per source, every second:
   - Pick the hum line: 60 Hz at 200 samples/s, the 40 Hz alias at 100 samples/s (sign flipped), or 120/180 Hz for radio audio.
   - Track it with Provenance's own `extract_enf` (8 s frame, 1 s hop). The prototype uses an equivalent tracker in `enfkit.py`.
   - Convert to grid Hz, so each source outputs (t_utc, f_hz, snr_db).
   - Drop seconds with SNR under 6 dB.
3. **Verify each source** (rolling 10-minute window):
   - Compare against the leave-one-out median of the other sources: correlation, best lag, and rms difference.
   - A source becomes **trusted** when r ≥ 0.75 at lag 0 ± 2 s for 3 windows in a row. It becomes **suspect** below 0.5, and is dropped after 30 minutes as suspect.
   - This catches look-alike lines (instrument tones, inverters, receivers on a different grid). In testing these looked convincing on a spectrum but didn't track.
   - Each source's steady time offset (for example the −1 s seen against Zenodo) is learned and corrected.
4. **Consensus**, per second, per grid:
   - Median of trusted sources after rejecting outliers more than 15 mHz from the median, weighted by recent agreement.
   - Store the consensus, the number of sources, and the spread (median absolute deviation) as a quality flag.
   - No trusted source means NaN, not interpolation.
   - Assign grids from station coordinates using a simple polygon (Western, Texas, Eastern, Québec). The verify step also confirms it: a Texas station never agrees with the Western median.
5. **Store**:
   - One file per grid per UTC day: `refs/live/<grid>/YYYY-MM-DD.csv.gz`.
   - Columns: `time_utc, f_hz, n_sources, spread_mhz, quality`.
   - Provenance's `reference.from_csv` reads this layout already.
   - A Parquet copy with per-source traces supports audits.
6. **Serve to Provenance**:
   - A loader picks the matching day files for a recording's time window and concatenates them, through the same path as the GB and Zenodo references.
   - The grid race then gains a live "US-West" entry, plus Texas and East once those have sources.
7. **Monitor**:
   - A small status page or log shows sources up, trusted count, consensus coverage, and the daily match against any truth available.
   - Alert when trusted sources drop below 3.

## Expected quality (from today's tests)
- Seven seismic stations against the true 2024 grid: r = 0.985, 2.0 mHz error.
- Live today, four stations: each matched the others' median at r ≈ 0.80–0.84.
- Three hum-carrying radio clips, 7 minutes each, were placed in time to within 0–1 s over a 2-hour search.
- Gaps and outages: coverage was 100% in the tested windows. Per-station dropouts happen, so aim for 6+ trusted sources [VERIFY over weeks].
- Live latency: 2–5 s on SeedLink.

## Storage and bandwidth
- **Stored output:** each grid day is 86,400 rows. That's about 1–2 MB a day compressed, under 1 GB a year per grid. Per-source traces add about 0.5 MB per source per day.
- **Ingest bandwidth** (not stored):
  - About 20–30 MB a day per 200-samples/s seismic channel, so about 300 MB a day for 10 channels. Well inside EarthScope limits.
  - About 0.5 GB a day per radio receiver if run continuously. That's another reason to run radios part-time.
- **Compute:** one Raspberry Pi 5 or the box handles 20 sources easily. Extraction is a narrow-band FFT per second per source.

## Effort estimate (mine)
| Step | Days |
|---|---|
| SeedLink-over-WSS ingest with reconnects and backfill | 2–3 |
| OpenWebRX ingest (part-time schedule, clock fit) | 1–2 |
| Extraction using Provenance's tracker, per-source offset calibration | 1–2 |
| Verification, consensus, grid assignment | 2 |
| Storage, Provenance loader, grid-race entry | 1–2 |
| Validation: rebuild Mar–Nov 2024 from archive and score against Zenodo; weekly discovery scan | 2–3 |
| **Total** | **about 9–14 days** |

A cheap first win, about 2–3 days: a "rebuild history" job. It turns FDSN archive data into a Western reference for any past date, back many years, where good stations existed. That gives Provenance Western references outside the Zenodo 2024 window, not just going forward.

## Rules and limits to keep
- **EarthScope:** use SeedLink for live data, and never poll dataselect for it. Keep to at most 5 connections. Cite network DOIs. An account is needed for archive pulls after Dec 15, 2026.
- **Raspberry Shake:** don't redistribute; real-time is paid. Not useful for ENF anyway.
- **OpenWebRX/KiwiSDR/WebSDR:** behave like one polite listener. Use part-time, never retune profiles, and ask before continuous use.
- **KGRID:** robots.txt disallows the data pages. Only use it with the owner's permission.
- **YouTube, EarthCam, Broadcastify:** don't record them automatically.
- **Privacy:** only grid frequency is kept. No audio is stored, and no listener lists are read.

## Open questions [VERIFY]
- Whether anonymous SeedLink stays open after the Dec 15, 2026 EarthScope account change.
- Long-run uptime of the best hum-carrying stations. Some PB borehole stations had no data on the days I tried after early 2024.
- Whether the Texas and Eastern grids get the same seismic coverage. Texas stations show strong hum, which looks promising.
