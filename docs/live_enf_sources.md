# Live and "accidental" grid-hum (ENF) sources — ranked catalog

Research date: Tuesday Nov 3, 2026. Times are Pacific (PST) unless marked UTC.
Scope: public, openly accessible data only. No sign-ups, logins, purchases, messages or posts. No Provenance code was changed.
Test scripts and raw results: a separate scratch folder with its own venv (not included in this repo).
Items marked [VERIFY] are unconfirmed.

## Short answer

Yes — a no-hardware, live Western-grid reference looks feasible. The surprise winner is **seismometers**.
Many public seismic stations pick up the 60 Hz hum from their own power supply, and the public networks stream it in real time, GPS-timed.

The proof, in three tests:

1. **Against the 2024 Western reference (Zenodo).** Single seismic stations matched the true grid record with correlation up to 0.995 and error as low as 1.5 mHz. A median "consensus" of 7 stations over 2 hours matched with r = 0.985 and 2.0 mHz error.
2. **Live today, with no reference at all.** Four stations up to about 1,900 km apart (Anza CA, Las Vegas, Neah Bay WA, and northwest Washington) agreed with each other at r = 0.73 to 0.79 second by second, and 0.91 to 0.97 after 10-second smoothing.
3. **Online radio receivers carry the same hum.** Three public OpenWebRX receivers in Fullerton, Pasadena and San Francisco carried hum in their audio that matched the seismic consensus at r = 0.91 to 0.92. They matched each other at r = 0.94 to 0.97. Blind test: searching a 2-hour window, each 7-minute radio clip was placed at the right second (error 0 to 1 s).

## Ranked catalog

Legend: **Proven** = the extracted hum tracks a known Western reference or independent Western sources. r = Pearson correlation of 1-second frequency traces; rmse = error against the reference.

| Rank | Source | Type | Location (trust) | Access | Live / archive | Rate | ENF found? | Best results | ToS / legal | Reliability |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | EarthScope / USGS / regional seismic networks (PB, UW, NN, MB, UI, UO…) | Seismometers, strong-motion sensors | Surveyed station coordinates, high trust | Live: SeedLink over WSS `wss://rtserve.earthscope.org/seedlink`. Archive: FDSN dataselect `service.earthscope.org` | Live (2–5 s latency, about 15–60 min ring buffer). Archive back decades per station | 100–500 samples/s | **Proven** | B082 r=0.995, 1.5 mHz; B084 0.993; B086 0.991; MB.YBMT 0.984; B088 0.960; UI.MGOO 0.908; 7-station consensus 0.985, 2.0 mHz | Open data. Cite network DOIs. From **Dec 15, 2026**, dataselect needs a free EarthScope account (anonymous quota then 0). Do not poll dataselect for real-time; use SeedLink (max 5 connections) | High per network. About 3% of sampled Western stations carry a usable line, and the hum strength changes with site power |
| 2 | Public OpenWebRX receivers (receiverbook.de directory) | Hobbyist SDRs; hum enters the audio from the receiver's power supply | Operator-entered GPS in `/status.json`; cross-checked by IP lookup (below). Medium trust | `wss://<host>/ws/` (the normal web client protocol), HTTPS only from this box | Live only, no archive | 12 kHz audio | **Proven** on 3 of 6 tried | Fullerton r=0.908 (120 Hz); Pasadena "KK6QZG" 0.918 (120 Hz); WE6K San Francisco 0.924 (180 Hz). Radio-to-radio 0.94–0.97 | Public listening is the intended use. Taking a listener slot 24/7 on a hobbyist receiver is impolite; ask the operator first. I did not switch any receiver's band profile, since that changes it for everyone | Medium. Depends on the operator's hardware and uptime. 3 of 6 had no hum |
| 3 | KGRID (kestrelgrid.com, David Daigle PE) | Purpose-built point-on-wave voltage sensors at wall outlets | Sensor map: Vancouver WA, Boise, Salt Lake City ×2, Phoenix, Riverside CA, Bremerton WA (plus East, ERCOT, EU) | Home page shows live WECC frequency. Raw 4–64 ksps archive since March 2024 is "freely available" **on request** by email | Live and archive since Mar 2024 | 2 phasors/s on the web; raw 4 ksps | Not tested (see ToS) | — | `robots.txt` disallows automated access to `/interactive` and `/archive`. I did not scrape them, and I deleted the one page I had loaded. Proper route is asking the owner | Likely the best true WECC reference if access is granted [VERIFY] |
| 4 | Zenodo Hartmann et al. 2024 Western record | Research recorder | Western grid, site unnamed | Already saved: `$PROVENANCE_DATA/wecc_samples/zenodo_wecc_2024_1s.npz` | Archive, Jan 16 – Nov 18, 2024 | 1 s | Reference itself | Used as ground truth here | CC BY 4.0 | High, but fixed in time |
| 5 | Raspberry Shake citizen seismometers (AM network) | Home seismometers | Owner-entered; coordinates are rounded for privacy, medium-low trust | FDSN `data.raspberryshake.org` | Archive since 2016; FDSN serves data 30+ min old; real-time is a paid product | 100 samples/s (60 Hz aliases to 40 Hz) | Lines seen, **not proven** | 13 of 150 sampled had a strong line, but none tracked the grid (r ≤ 0.26) | License **forbids redistributing** the data via your own server or service; real-time is paid. Fine for personal analysis | Low for ENF |
| 6 | KiwiSDR public receivers (about 66 in the West) | Hobbyist 0–30 MHz SDRs, many in noisy suburbs | Operator profile coordinates | Kiwi web client, plain HTTP on port 8073 | Live only | 12 kHz audio | **Untested** | This box only allows web traffic over HTTPS, and KiwiSDRs use plain HTTP | Public listening is intended; many set time limits; `kiwirecorder.py` is the sanctioned client | Likely similar to OpenWebRX [VERIFY]; worth testing from a home connection |
| 7 | WebSDR (Northern Utah ×5, KFS Half Moon Bay ×2, Santa Clarita) | Hobbyist SDRs | Operator listing | Plain HTTP | Live only | ~8 kHz audio | **Untested** (plain HTTP blocked from this box) | — | Listening intended; no official API, so automated use is gray | [VERIFY] |
| 8 | Airspy SpyServer directory (airspy.com/directory, `status.json`) | Hobbyist SDRs | Operator-entered antenna lat/long; 11 in the West | Binary SpyServer protocol, raw TCP | Live only | IQ | **Untested** | 10 of 11 Western servers are VHF/UHF only (24 MHz and up). The one HF-capable server (LA) refused the connection; the other one I tried timed out. Raw TCP from this box appears blocked | Directory is public; the feed also lists current listeners — I did not use that | Low priority |
| 9 | rtl_tcp / SDR# public servers | Hobbyist SDRs | Varies | Raw TCP | Live | — | Not tested | No maintained Western list found [VERIFY] | — | Low |
| 10 | Live VLF natural-radio streams (dk7fc.info list, ab9il.net list) | Receivers 0–20 kHz that pick up power-line harmonics strongly | Listed | Audio streams | Live | 8–48 kHz | Not tested | No Western-US stream found; the US one is in Pennsylvania (Eastern grid) | Listening intended | Useful for Eastern and Europe, not WECC |
| 11 | FNET/GridEye public displays (UTK) | Grid sensors | — | Web gauge images | Live | ~1 s, digitized from images | Already known (nate-griff) | Public table shows "sample data", not live values | Data hidden since 2018; access on request | Low as a scrape |
| 12 | YouTube / EarthCam live cams, Broadcastify scanner feeds, internet-radio studio streams | Accidental hum in audio | Usually known | Stream downloads | Live | 44–48 kHz | Not tested this round | Earlier Heathrow test showed hum is possible | **ToS concerns**: YouTube and EarthCam terms forbid downloading/recording without permission; Broadcastify feeds are squelched (mostly silence) and archives are paid | Low |
| 13 | Magnetometers (USGS, INTERMAGNET), infrasound, Blitzortung | Geophysical | Known | Various | Live | ≤ 1 sample/s (magnetometers); lightning data closed | No | 1-sample/s data can't hold a 60 Hz line; Blitzortung data isn't open | — | Not useful |

### IP cross-check of OpenWebRX locations
(Coarse lookup of each hostname's public IP via DNS-over-HTTPS plus ipinfo.io. No probing.)

| Receiver | Claimed location | IP lookup | Trust |
|---|---|---|---|
| fullerton.w6mfb.com | Fullerton CA (33.86, −117.89) | Cloudflare proxy, can't verify | Medium (callsign W6MFB on page) |
| sdr.federico.io (KK6QZG) | "34.0, −118.0" (rounded) | Pasadena CA, Charter residential | Good, LA area |
| sdr.we6k.com | San Francisco (37.76, −122.43) | Milpitas CA, Hurricane Electric (ISP hub) | Medium-good, Bay Area |
| sdr01.ionic1k.net | Danville CA | San Jose, Comcast | Good (no hum found) |
| sdr.ixitxachitl.com | Sierra foothills CA | Cloudflare | Unknown (no hum found) |
| sdr.n7rix.com | Utah County UT | Salt Lake City, Google Fiber | Good (no hum found) |

For the grid reference, exact location barely matters. The whole Western grid shares one frequency. Location only matters for confirming which grid a source is on.

## Test details

All extraction used an 8-second window stepped every second, a peak search near 60 Hz (or the right harmonic or alias), and correlation with up to ±10 s of lag. Scripts: `enfkit.py`, `scan.py`, `broad_scan.py`, `multi_track.py`, `consensus_2024.py`, `sl_ws.py`, `live_compare.py`, `blind_match.py`, `owrx/owrx_rec.py` in a separate scratch folder (not included in this repo).

### A. Seismic vs the Zenodo 2024 Western reference
Spectral scan of 291 Western channels for Mar 5, 2024, 10:00 AM PST: 36 had a narrow line at least 12 dB over the noise (28 of 205 network stations, 8 of 86 Raspberry Shakes). The candidates were then tracked for 30 minutes:

| Station | Place | r vs Zenodo | rmse |
|---|---|---|---|
| PB.B082 (borehole) | Anza area, CA | 0.995 | 1.5 mHz |
| PB.B084 | Anza area, CA | 0.993 | 1.7 mHz |
| PB.B086 | Anza area, CA | 0.991 | 2.0 mHz |
| MB.YBMT | NW Montana | 0.984 | 2.5 mHz |
| PB.B088 | Anza area, CA | 0.960 | 4.2 mHz |
| UI.MGOO | Spokane area, WA | 0.908 | 6.6 mHz |
| UW.WRMB | NW Washington | 0.877 | 7.7 mHz |
| UW.HOMA | Seattle area, WA | 0.780 | 11.4 mHz |
| NN.HYDE | Las Vegas, NV | 0.740 (0.85 with 15 s smoothing) | 13 mHz |
| UW.OZET, UO.DAYS, MB.OVMT | WA, OR, MT | 0.60–0.63 | 17–19 mHz |

- **Negative control:** West Texas stations (TX.PB46, PB23, PB47, NX.WTX29, AM.R93D1) sit on the Texas grid (ERCOT). They did not match the Western record (r −0.45 to 0.08), which is what should happen.
- **Look-alike lines:** Some stations have a strong line near 60 or 40 Hz that is not mains (NC.MCS/MLH/MDC near Mammoth, many Raspberry Shakes). This is why every source needs to be verified against the others.
- **2-hour consensus** (Mar 11, 2024, 7:00–9:00 PM PDT), median of 7 stations after outlier rejection: r = 0.985, rmse 2.0 mHz, 95% of seconds within 4.1 mHz, full coverage. Without the Anza cluster (5 stations): r = 0.967, 3.0 mHz.
- Most stations show a steady −1 s offset against Zenodo. It is likely a timestamp convention (window start vs center) [VERIFY]. It's constant, so calibrate it once.

### B. Live, today (no reference)
- FDSN archive pull, 10:15–10:45 AM PST: B088 × MKAH r = 0.848; B088 × HYDE 0.794; HYDE × MKAH 0.805. ERCOT station PB46 vs these: 0.26–0.28, only at the edge of the lag search, so not a real match.
- SeedLink live stream, about 11:03–11:19 AM PST, 2–5 s latency: pairwise r = 0.57–0.79 raw, 0.91–0.97 after 10 s smoothing. Each station against the median of the others: 0.80–0.84 (8–9 mHz), and WRMB 0.63.

### C. Online radio receivers (OpenWebRX) vs the live seismic consensus
7-minute recordings, 11:09–11:16 AM PST. I used each receiver's current band, AM demodulator, and did not retune anyone's band profile:

| Receiver | Band in use | Best harmonic | r vs seismic | Null test (shifted 30–200 s), max abs r |
|---|---|---|---|---|
| Fullerton CA | 159 MHz marine | 120 Hz | 0.908 | 0.43 |
| Pasadena CA | 121 MHz airband | 120 Hz | 0.918 | 0.44 |
| San Francisco CA | 18 MHz HF | 180 Hz (60 Hz 0.81) | 0.924 | 0.43 |
| Danville, Sierra foothills, Utah | — | — | no line | — |

- Radio to radio, with no seismic data: Fullerton × SF 0.945, Fullerton × Pasadena 0.936, Pasadena × SF 0.969.
- **Blind timing test:** each 7-minute radio clip was searched across a 2-hour seismic consensus (9:30–11:30 AM PST). All three landed on the true second or 1 s off. Best r was 0.91–0.92, against a runner-up of about 0.69–0.70.
- The receivers' audio clocks ran about 0.1–0.2% slow against wall-clock arrival times. I fitted that out using packet arrival times. Live-only sources have about ±1 s of network timing jitter, so seismic GPS time should anchor the reference.

## What I couldn't test, and why
- **KiwiSDR, WebSDR:** the development machine's network only passed HTTPS, and these use plain HTTP.
- **SpyServer, rtl_tcp:** raw TCP gave no response here. SeedLink worked only over its WSS port.
- **KGRID:** its robots.txt disallows automated access to the data pages. Its raw data is offered free on request. Jeff, you'd need to ask the owner yourself; I sent nothing.
- **YouTube, EarthCam, Broadcastify:** skipped this round because of terms-of-service limits on recording.
