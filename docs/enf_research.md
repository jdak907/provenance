# ENF research: using power-grid hum to tell when, and roughly where, a recording was made

Prepared Tuesday, November 3, 2026, for the Provenance ENF tab. Research only. No Provenance code was changed.

Every paper below was checked against Crossref or the publisher page: title, authors, year, venue, and DOI. Anything I could not confirm is marked [VERIFY].

## 1. The idea in plain language

The power grid does not run at exactly 60 hertz. It drifts up and down by a few hundredths of a hertz as supply and demand change. Every outlet on the same interconnection shares that drift, at the same moment. Engineers call the drifting value the electric network frequency, or ENF.

Recordings often pick up that drift.
- **Audio:** a faint hum from fridges, fans, transformers, chargers, and lights, or electrical pickup in a recorder that's plugged in. The hum sits at 60 Hz and at its multiples: 120, 180, 240 Hz, and so on.
- **Video:** mains-powered lights flicker at twice the line frequency, 120 Hz in the US. A phone camera's rolling shutter reads the image one row at a time, so that flicker shows up as faint moving bands.

If you pull the drift out of a recording and slide it along a logged record of grid frequency, the best match tells you when the recording was made, often to within a few seconds. The way the drift behaves also hints at which grid you were on. Inside one grid, location is only coarse.

This is a timestamp-and-grid tool, not a position tool. In the US the interconnections are the Eastern, the Western (WECC), the Texas (ERCOT) grid, and Quebec. Jeff, if you record in the Los Angeles area, you are on the Western Interconnection.

## 2. Annotated bibliography

### 2.1 Surveys and starting points

1. **Ngharamike, E., Ang, L.-M., Seng, K. P., Wang, M. (2023).** "ENF Based Digital Multimedia Forensics: Survey, Application, Challenges and Future Work." IEEE Access, vol. 11, pp. 101241–101272. https://doi.org/10.1109/ACCESS.2023.3312181
   - This is the broadest recent survey. It covers reference databases, estimation methods, audio, video and single-image extraction, the factors that affect embedding, and applications. Read it first. It is open access.
2. **Cui, S., Mao, M., Lin, X., Kang, X. (2019).** "Survey on Analysis and Applications of Electric Network Frequency (ENF) Signals in Image and Video." Journal of Applied Sciences (Shanghai University), vol. 37, no. 5, p. 573. Publisher page: https://www.jas.shu.edu.cn/EN/10.3969/j.issn.0255-8297.2019.05.001 (the DOI 10.3969/j.issn.0255-8297.2019.05.001 is not in Crossref, so whether it resolves is [VERIFY]).
   - A survey focused on video and images. It is in Chinese with an English abstract.
3. **Wu, M., Hajj-Ahmad, A., Kirchner, M., Ren, Y., Zhang, C., Campisi, P. (2016).** "Location Signatures That You Don't See: Highlights from the IEEE Signal Processing Cup 2016 Student Competition." IEEE Signal Processing Magazine, vol. 33, no. 5, pp. 149–156. https://doi.org/10.1109/MSP.2016.2581738 (free copy: https://par.nsf.gov/servlets/purl/10462650)
   - A friendly overview of grid-of-origin classification. It describes the features the winning teams used and a cheap reference circuit.
4. **Grigoras, C. (2005).** "Digital audio recording analysis: the Electric Network Frequency (ENF) Criterion." International Journal of Speech, Language and the Law, 12(1), pp. 63–76. https://doi.org/10.1558/sll.2005.12.1.63
   - This is the founding forensic paper. It introduced the idea of matching recorded hum against a logged frequency database.
5. **Grigoras, C. (2007).** "Applications of ENF criterion in forensic audio, video, computer and telecommunication analysis." Forensic Science International, 167(2–3), pp. 136–145. https://doi.org/10.1016/j.forsciint.2006.06.033
6. **Cooper, A. J. (2009, issue dated 2009, Crossref lists 2010).** "An automated approach to the Electric Network Frequency (ENF) criterion: theory and practice." International Journal of Speech, Language and the Law, 16(2), pp. 193–218. https://doi.org/10.1558/ijsll.v16i2.193
   - An early automated pipeline from a working forensic lab.

### 2.2 Getting the ENF trace out of audio (extraction)

The baseline method is the short-time Fourier transform (STFT): take a few seconds of audio at a time, find the peak near 60 Hz or one of its multiples, and refine the peak by interpolation. The papers below improve on it for short or noisy clips.

7. **Hajj-Ahmad, A., Garg, R., Wu, M. (2012).** "Instantaneous Frequency Estimation and Localization for ENF Signals." APSIPA Annual Summit and Conference, December 2012. Listed on the University of Maryland MAST page: https://mast.umd.edu/research.php?t=enf. DOI not found [VERIFY].
   - It compares STFT with the high-resolution subspace methods MUSIC and ESPRIT. Those win on short frames and at low signal-to-noise.
8. **Hajj-Ahmad, A., Garg, R., Wu, M. (2013).** "Spectrum Combining for ENF Signal Estimation." IEEE Signal Processing Letters, 20(9), pp. 885–888. https://doi.org/10.1109/LSP.2013.2272523
   - This is weighted harmonic combining. It adds the spectra of several harmonics, weighting each by its local signal-to-noise ratio. It is the core method I recommend for Provenance.
9. **Bykhovsky, D., Cohen, A. (2013).** "Electrical Network Frequency (ENF) Maximum-Likelihood Estimation Via a Multitone Harmonic Model." IEEE Transactions on Information Forensics and Security (TIFS), 8(5), pp. 744–753. https://doi.org/10.1109/TIFS.2013.2253462
   - Maximum-likelihood estimation across all harmonics. It is the best choice when the noise is even across them.
10. **Ojowu, O., Karlsson, J., Li, J., Liu, Y. (2012).** "ENF Extraction From Digital Recordings Using Adaptive Techniques and Frequency Tracking." IEEE TIFS, 7(4), pp. 1330–1338. https://doi.org/10.1109/TIFS.2012.2197391
    - It uses a high-resolution adaptive estimator called TRIAA, plus dynamic-programming tracking that exploits how slowly the ENF changes.
11. **Fu, L., Markham, P. N., Conners, R. W., Liu, Y. (2013).** "An Improved Discrete Fourier Transform-Based Algorithm for Electric Network Frequency Extraction." IEEE TIFS, 8(7), pp. 1173–1181. https://doi.org/10.1109/TIFS.2013.2265088
12. **Dosiek, L. (2015).** "Extracting Electrical Network Frequency From Digital Recordings Using Frequency Demodulation." IEEE Signal Processing Letters, 22(6), pp. 691–695. https://doi.org/10.1109/LSP.2014.2368516
13. **Hua, G., Zhang, H. (2020).** "ENF Signal Enhancement in Audio Recordings." IEEE TIFS, vol. 15, pp. 1868–1878. https://doi.org/10.1109/TIFS.2019.2952264
    - A denoising step, called the robust filtering algorithm, that runs before estimation.
14. **Hua, G., Liao, H., Zhang, H., Ye, D., Ma, J. (2021).** "Robust ENF Estimation Based on Harmonic Enhancement and Maximum Weight Clique." IEEE TIFS, vol. 16, pp. 3874–3887. https://doi.org/10.1109/TIFS.2021.3099697 (preprint: https://arxiv.org/abs/2011.03414)
    - The main lesson: in real recordings, adding every harmonic can make results worse. Pick the harmonics whose traces agree with each other. It introduced the ENF-WHU dataset.
15. **Hua, G., Liao, H., Wang, Q., Zhang, H., Ye, D. (2021).** "Detection of Electric Network Frequency in Audio Recordings: From Theory to Practical Detectors." IEEE TIFS, vol. 16, pp. 236–248. https://doi.org/10.1109/TIFS.2020.3009579
    - It answers "is there usable ENF in this file at all?" That question should gate every later step.

### 2.3 Matching against a reference (timestamping)

16. **Garg, R., Varna, A. L., Wu, M. (2012).** "Modeling and Analysis of Electric Network Frequency Signal for Timestamp Verification." IEEE WIFS 2012, pp. 67–72. https://doi.org/10.1109/WIFS.2012.6412627
    - It models the ENF as an autoregressive process and matches on its innovations, meaning the unpredictable part, which sharpens the match.
17. **Liu, Y., Yuan, Z., Markham, P. N., Conners, R. W., Liu, Y. (2012).** "Application of Power System Frequency for Digital Audio Authentication." IEEE Transactions on Power Delivery, 27(4), pp. 1820–1828. https://doi.org/10.1109/TPWRD.2012.2198892
    - The FNET group's paper on using its own US measurements as the forensic reference.
18. **Hua, G., Goh, J., Thing, V. L. L. (2014).** "A Dynamic Matching Algorithm for Audio Timestamp Identification Using the ENF Criterion." IEEE TIFS, 9(7), pp. 1045–1055. https://doi.org/10.1109/TIFS.2014.2321228
    - It handles the small clock drift between a cheap recorder and true time.
19. **Hua, G. (2018).** "Error Analysis of Forensic ENF Matching." IEEE WIFS 2018, pp. 1–7. https://doi.org/10.1109/WIFS.2018.8630786
20. **Hua, G., Wang, Q., Ye, D., Zhang, H. (2020).** "Reliability of Power System Frequency on Times-Stamping Digital Recordings." arXiv:2011.00176. https://arxiv.org/abs/2011.00176. Whether it was published in a journal is [VERIFY].
    - This is the most practical paper for setting user expectations. See section 5.
21. **Huijbregtse, M., Geradts, Z. (2009).** "Using the ENF Criterion for Determining the Time of Recording of Short Digital Audio Recordings." IWCF 2009, Lecture Notes in Computer Science, pp. 116–124. https://doi.org/10.1007/978-3-642-03521-0_11
22. **Maiberger, R., Gusakov, Y., Routtenberg, T. (2025).** "Empirical Evaluation of ENF Extraction Methods for Accurate Timestamping in Multimedia Forensics." 59th Conference on Information Sciences and Systems (CISS 2025). https://doi.org/10.1109/CISS64860.2025.10944719
    - A recent head-to-head comparison of extraction and correlation choices on real data. It is useful for picking defaults.

### 2.4 Detecting edits and splices

23. **Rodríguez, D. P. N., Apolinário, J. A., Biscainho, L. W. P. (2010).** "Audio Authenticity: Detecting ENF Discontinuity With High Precision Phase Analysis." IEEE TIFS, 5(3), pp. 534–543. https://doi.org/10.1109/TIFS.2010.2051270
    - A cut or an insertion causes a jump in the hum's phase. This paper finds those jumps, with about 6 percent equal error rate on its test set.
24. **Esquef, P. A. A., Apolinário, J. A., Biscainho, L. W. P. (2014).** "Edit Detection in Speech Recordings via Instantaneous Electric Network Frequency Variations." IEEE TIFS, 9(12), pp. 2314–2326. https://doi.org/10.1109/TIFS.2014.2363524
25. **Reis, P. M. G. I., Lustosa da Costa, J. P. C., Miranda, R. K., Del Galdo, G. (2017).** "ESPRIT-Hilbert-Based Audio Tampering Detection With SVM Classifier for Forensic Analysis via Electrical Network Frequency." IEEE TIFS, 12(4), pp. 853–864. https://doi.org/10.1109/TIFS.2016.2636095
26. **Hua, G., Zhang, Y., Goh, J., Thing, V. L. L. (2016).** "Audio Authentication by Exploring the Absolute-Error-Map of ENF Signals." IEEE TIFS, 11(5), pp. 1003–1016. https://doi.org/10.1109/TIFS.2016.2516824
27. **Zinemanas, P., Fuentes, M., Cancela, P., Apolinário, J. A. (2018).** "An ENF-Based Audio Authenticity Method Robust to MP3 Compression." Circuits, Systems, and Signal Processing, 37(11), pp. 4973–4992. https://doi.org/10.1007/s00034-018-0793-9

### 2.5 ENF from video and images

28. **Garg, R., Varna, A. L., Hajj-Ahmad, A., Wu, M. (2013).** "'Seeing' ENF: Power-Signature-Based Timestamp for Digital Multimedia via Optical Sensing and Signal Processing." IEEE TIFS, 8(9), pp. 1417–1432. https://doi.org/10.1109/TIFS.2013.2272217. The earlier conference version is ACM Multimedia 2011: https://user.eng.umd.edu/~minwu/research/public_paper/Conf11/ACM_MM11_ENF_GargVarnaWu.pdf
    - It showed that indoor-light flicker carries the ENF into video. In the conference experiment, a 29.97 frames-per-second US video put the aliased 120 Hz flicker at about 0.12 Hz and timestamped it to roughly 8 seconds.
29. **Su, H., Hajj-Ahmad, A., Garg, R., Wu, M. (2014).** "Exploiting Rolling Shutter for ENF Signal Extraction from Video." IEEE ICIP 2014, pp. 5367–5371. https://doi.org/10.1109/ICIP.2014.7026086 (PDF: https://www.mast.umd.edu/files/paper_ENF/conf_paper11_ICIP14.pdf)
    - It treats each image row as its own time sample, which raises the effective sampling rate from 30 per second to thousands per second. It also models the idle gap between frames and handles moving scenes.
30. **Vatansever, S., Dirik, A. E., Memon, N. (2017).** "Detecting the Presence of ENF Signal in Digital Videos: A Superpixel-Based Approach." IEEE Signal Processing Letters, 24(10), pp. 1463–1467. https://doi.org/10.1109/LSP.2017.2741440
31. **Vatansever, S., Dirik, A. E., Memon, N. (2019).** "Analysis of Rolling Shutter Effect on ENF-Based Video Forensics." IEEE TIFS, 14(9), pp. 2262–2275. https://doi.org/10.1109/TIFS.2019.2895540
32. **Vatansever, S., Dirik, A. E., Memon, N. (2019).** "Factors Affecting ENF Based Time-of-Recording Estimation for Video." IEEE ICASSP 2019. https://doi.org/10.1109/ICASSP.2019.8682419
33. **Choi, J., Wong, C.-W., Su, H., Wu, M. (2023).** "Analysis of ENF Signal Extraction From Videos Acquired by Rolling Shutters." IEEE TIFS, vol. 18, pp. 4229–4242. https://doi.org/10.1109/TIFS.2023.3287132
    - The current best explanation of video ENF. Its "periodic zeroing-out" method needs the camera's row read-out time but gives cleaner traces. MATLAB code and a dataset are public; see section 4.
34. **Han, H., Jeon, Y., Song, B.-K., Yoon, J. W. (2022).** "A Phase-Based Approach for ENF Signal Extraction From Rolling Shutter Videos." IEEE Signal Processing Letters, vol. 29, pp. 1724–1728. https://doi.org/10.1109/LSP.2022.3189306
35. **Hajj-Ahmad, A., Berkovich, A., Wu, M. (2016).** "Exploiting Power Signatures for Camera Forensics." IEEE Signal Processing Letters, 23(5), pp. 713–717. https://doi.org/10.1109/LSP.2016.2537201
    - It estimates a camera's read-out time from the flicker, which is the number the Choi method needs.
36. **Ferrara, P., Sanchez, I., Draper-Gil, G., Junklewitz, H., Beslay, L. (2021).** "A MUSIC Spectrum Combining Approach for ENF-based Video Timestamping." IEEE IWBF 2021. https://doi.org/10.1109/IWBF50991.2021.9465094
37. **Fernández-Menduiña, S., Pérez-González, F. (2020).** "Temporal Localization of Non-Static Digital Videos Using the Electrical Network Frequency." IEEE Signal Processing Letters, vol. 27, pp. 745–749. https://doi.org/10.1109/LSP.2020.2988145
38. **Frijters, G., Geradts, Z. J. M. H. (2022).** "Use of electric network frequency presence in video material for time estimation." Journal of Forensic Sciences, 67(3), pp. 1021–1032. https://doi.org/10.1111/1556-4029.15003
    - A smartphone study of different light sources. Halogen and incandescent bulbs worked best. LEDs worked only in ideal conditions.
39. **Wong, C.-W., Hajj-Ahmad, A., Wu, M. (2018).** "Invisible Geo-Location Signature in a Single Image." IEEE ICASSP 2018, pp. 1987–1991. https://doi.org/10.1109/ICASSP.2018.8461717
    - It tells 50 Hz from 60 Hz in a single rolling-shutter photo.
40. **Su, H., Hajj-Ahmad, A., Wong, C.-W., Garg, R., Wu, M. (2014).** "ENF Signal Induced by Power Grid: A New Modality for Video Synchronization." ACM Workshop on Immersive Media Experiences, pp. 13–18. https://doi.org/10.1145/2660579.2660588
41. **Su, H., Hajj-Ahmad, A., Wu, M., Oard, D. W. (2014).** "Exploring the Use of ENF for Multimedia Synchronization." IEEE ICASSP 2014, pp. 4613–4617. https://doi.org/10.1109/ICASSP.2014.6854476

### 2.6 Location: which grid, and where inside it

42. **Hajj-Ahmad, A., Garg, R., Wu, M. (2015).** "ENF-Based Region-of-Recording Identification for Media Signals." IEEE TIFS, 10(6), pp. 1125–1136. https://doi.org/10.1109/TIFS.2015.2398367
    - It identifies which grid a recording came from with no reference data from the same time. It uses statistics of the trace (mean, variance, range, wavelet variances, AR-model coefficients) in a machine-learning classifier. This is the basis for the SP Cup.
43. **Hajj-Ahmad, A., Garg, R., Wu, M. (2013).** "ENF Based Location Classification of Sensor Recordings." IEEE WIFS 2013, pp. 138–143. https://doi.org/10.1109/WIFS.2013.6707808
44. **Garg, R., Hajj-Ahmad, A., Wu, M. (2013).** "Geo-location Estimation from Electrical Network Frequency Signals." IEEE ICASSP 2013, pp. 2862–2866. https://doi.org/10.1109/ICASSP.2013.6638180 (PDF: https://www.mast.umd.edu/files/paper_ENF/conf_paper6_ICASSP13.pdf)
    - It uses power-line data from the US Eastern grid. Similarity between two sites' ENF falls off with distance, so comparing a trace against several "anchor" sensors narrows the location. It reports 90 percent accuracy under certain conditions. These were clean outlet measurements, not media recordings.
45. **Yao, W., Zhao, J., Till, M. J., You, S., Liu, Y., Cui, Y. (2017).** "Source Location Identification of Distribution-Level Electric Network Frequency Signals at Multiple Geographic Scales." IEEE Access, vol. 5, pp. 11166–11175. https://doi.org/10.1109/ACCESS.2017.2707060
    - It uses FNET/GridEye outlet data. It reports over 90 percent accuracy at about a 500-mile scale and about 91.5 percent at about 200 miles, but under 50 percent at about 2 miles. That is the clearest published evidence that within-grid location is coarse.
46. **Elmesalawy, M. M., Eissa, M. M. (2014).** "New Forensic ENF Reference Database for Media Recording Authentication Based on Harmony Search Technique Using GIS and Wide Area Frequency Measurements." IEEE TIFS, 9(4), pp. 633–644. https://doi.org/10.1109/TIFS.2014.2304838
47. **Rydin Gorjão, L., Jumar, R., Maass, H., Hagenmeyer, V., Yalcin, G. C., Kruse, J., Timme, M., Beck, C., Witthaut, D., Schäfer, B. (2020).** "Open database analysis of scaling and spatio-temporal properties of power grid frequencies." Nature Communications, 11, 6362. https://www.nature.com/articles/s41467-020-19732-7
    - Not an ENF-forensics paper, but useful physics. Inside Continental Europe, 1-second changes are nearly independent between distant sites, while trends over about 10 seconds and longer are shared grid-wide. That is why within-grid location needs sub-second, GPS-timed references, which media recordings rarely give you.
48. **Liu, Y. et al. (2016).** "Wide-Area-Measurement System Development at the Distribution Level: An FNET/GridEye Example." IEEE Transactions on Power Delivery, 31(2), pp. 721–731. https://doi.org/10.1109/TPWRD.2015.2478380
49. **Zhong, Z. et al. (2005).** "Power System Frequency Monitoring Network (FNET) Implementation." IEEE Transactions on Power Systems, 20(4), pp. 1914–1921. https://doi.org/10.1109/TPWRS.2005.857386

### 2.7 Robustness, real-world capture, and anti-forensics

50. **Hajj-Ahmad, A., Wong, C.-W., Gambino, S., Zhu, Q., Yu, M., Wu, M. (2019).** "Factors Affecting ENF Capture in Audio." IEEE TIFS, 14(2), pp. 277–288. https://doi.org/10.1109/TIFS.2018.2837645 (free copy: https://par.nsf.gov/servlets/purl/10254057)
    - The main source on capture factors. The microphone matters: some capture only the even harmonics (120 and 240 Hz) and some the odd ones (60 and 180 Hz). Where the recorder sits in the room matters, because sound waves interfere. Moving the recorder smears the trace through the Doppler effect, and walking with it in a pocket destroyed it. A strong 120 Hz line can also be something other than ENF.
51. **Fechner, N., Kirchner, M. (2014).** "The Humming Hum: Background Noise as a Carrier of ENF Artifacts in Mobile Device Audio Recordings." IMF 2014, pp. 3–13. https://doi.org/10.1109/IMF.2014.14
    - It showed that battery-powered phones pick up ENF from ambient hum, even 10 m away from the source in another room.
52. **Hua, G., Bi, G., Thing, V. L. L. (2017).** "On Practical Issues of Electric Network Frequency Based Audio Forensics." IEEE Access, vol. 5, pp. 20640–20651. https://doi.org/10.1109/ACCESS.2017.2647921
53. **Su, H., Garg, R., Hajj-Ahmad, A., Wu, M. (2013).** "ENF Analysis on Recaptured Audio Recordings." IEEE ICASSP 2013, pp. 3018–3022. https://doi.org/10.1109/ICASSP.2013.6638212
    - When audio is re-recorded, for example played and recorded again, two ENF traces can overlap.
54. **Chuang, W.-H., Garg, R., Wu, M. (2012).** "How Secure are Power Network Signature Based Time Stamps?" ACM CCS 2012, pp. 428–438. https://doi.org/10.1145/2382196.2382243
55. **Chuang, W.-H., Garg, R., Wu, M. (2013).** "Anti-Forensics and Countermeasures of Electrical Network Frequency Analysis." IEEE TIFS, 8(12), pp. 2073–2088. https://doi.org/10.1109/TIFS.2013.2285515
    - An adversary can remove the ENF or plant a fake one. The paper also shows how a careful examiner can often detect the tampering. The upshot for Provenance: ENF is evidence, not proof.
56. **Li, Y., Tan, R., Yau, D. K. Y. (2018).** "Natural Timestamps in Powerline Electromagnetic Radiation." ACM Transactions on Sensor Networks, 14(2). https://doi.org/10.1145/3199676

## 3. Reference grid-frequency data: what exists and how far back it goes

Matching needs a logged record of grid frequency covering the recording time. This is the hard part in the US.

| Source | Grid covered | Resolution | History | Access and terms | Good for |
|---|---|---|---|---|---|
| NESO (formerly National Grid ESO) System Frequency, https://www.neso.energy/data-portal/system-frequency-data | Great Britain, 50 Hz | 1 second | Monthly CSVs from April 2014 to September 2026 (153 files when I checked on Nov 3, 2026) | Free, NESO Open Data Licence, commercial use allowed with attribution ("Supported by National Energy SO Open Data"). CKAN API with rate limits. | The best free long reference anywhere. Ideal for building and testing the matcher. |
| power-grid-frequency.org and OSF database (Jumar et al. 2020, arXiv:2006.01771; https://osf.io/by5hu/) | 12 synchronous areas, including US Western (Salt Lake City) and Texas (College Station) | 1 second, GPS-timed | US Western: May 19 to 25, 2019 only (6.4 days). Texas: two short runs in May 2019 (1.4 and 3.7 days). | Free. The authors ask you to cite the paper. | US grid statistics for grid ID. Too short and too old to timestamp new recordings. |
| power-grid-frequency.org archive, TSO data (https://power-grid-frequency.org/archive-database/) | Germany (TransnetBW), France (RTE), Finland (Fingrid), GB, Denmark, Sweden, Ireland, Japan 50 Hz, and others | 0.02 to 10 seconds | For example, TransnetBW 1 s from July 2011 to March 2020; GB 2014–2019; Fingrid 0.1 s 2015–2019 | Varies by source. Fingrid is CC-BY-4.0. RTE's terms forbid reproduction. TransnetBW states no explicit licence. | European testing. |
| Gridradar, https://gridradar.net/de/api | Continental Europe | 1 second (median) | Historic data on request | Free for research, including historic downloads by SFTP. Commercial use is paid. Token API. | European references. |
| netzfrequenzmessung.de | Continental Europe (Germany) | Live, about 3 seconds | No public archive that I confirmed [VERIFY] | Live feed only | Live demo only. |
| Swissgrid current grid data | Continental Europe | Live | No historic download | Live only | Not useful for matching. |
| FNET/GridEye, University of Tennessee, https://fnetpublic.utk.edu/ | All US interconnections plus others; many sensors at ordinary outlets | Sub-second, GPS-timed | A long archive exists (they store data in openHistorian) | Not open. Data by arrangement with Prof. Yilu Liu (liu@utk.edu) or the industry consortium. The public table display "is fed from a set of sample data and does not represent the current system frequency," and since May 2018 it shows only the trend. | The only real multi-year US Western, Eastern and ERCOT archive, by request only. |
| ERCOT Real-Time System Conditions, https://www.ercot.com/content/cdr/html/real_time_system_conditions.html | Texas | Live, 3 decimals; update rate [VERIFY] | No historic frequency archive that I confirmed. ERCOT's public API archive starts December 11, 2023, but I did not confirm that it carries a frequency product [VERIFY]. | Public web page | You could log it going forward. |
| WECC System Performance Data Portal | Western | One-minute averages and quarterly statistics only | Summary only | Public | Not usable for matching, because one-minute averages are too coarse. |
| PNNL Grid Event Signature Library | Includes anonymized Eastern PMU data | PMU rate | Events only, not continuous | Public, event-based | Not a matching reference. |
| IEEE SP Cup 2016 dataset, https://doi.org/10.21227/H2159S | 9 training grids, A through I, with 12 grids in total including the finals. Grid C is the US Eastern, I the US Western, and A Texas. | Raw power and audio WAV recordings | Recorded about 2015 | IEEE DataPort, Creative Commons Attribution. The files need a (free) DataPort login [VERIFY that the free tier is enough]. Ground-truth labels are published: https://sigport.org/documents/information-mast-enf-power-signature-dataset | Training and testing grid ID, including US West versus East versus Texas. |
| ENF-WHU dataset, https://github.com/ghua-ac/ENF-WHU-Dataset | Central China Grid, 50 Hz | 130 real audio recordings, 5–16 minutes each, at 8 kHz, plus matching reference ENF at 400 Hz | Recorded about 2019–2020 | MIT licence | Testing extraction accuracy on real noisy audio against ground truth. |
| Rolling-shutter videos for ENF extraction (Choi et al.), https://ieee-dataport.org/documents/rolling-shutter-videos-enf-extraction | US, 60 Hz | Videos plus power references | About 2022 | IEEE DataPort | Testing the video extractor. |
| Your own reference recorder | Whatever grid you're on | Whatever you record | From the day you start | Free | The practical answer for the US Western grid. A commercial AC-to-AC wall adapter with a voltage divider into a USB sound card, logged with GPS or NTP time. Don't build bare mains circuits. |

### US coverage in one paragraph

**Western Interconnection:** I found no free, continuous, historic, second-by-second public archive. The options are:
- FNET/GridEye by request;
- record your own reference from today forward;
- the 6.4-day 2019 Salt Lake City set and SP Cup grid I, for grid statistics only.

**Eastern Interconnection:** the same situation. FNET by request, SP Cup grid C, and event-only PMU data.

**ERCOT:** a live page you could log going forward, plus a short 2019 OSF set and SP Cup grid A. Whether ERCOT's API archive includes frequency is [VERIFY].

The practical consequence: for US recordings made in the past, Provenance can do grid identification and splice detection without a reference. It can timestamp only recordings made after you start logging, or with data obtained from FNET.

One caution on a community tool. nate-griff/enf builds its US references by scraping FNET's public gauge image. FNET says those public values are sample data and not the real system frequency, so references built that way are probably not valid evidence [VERIFY].

## 4. Open-source code

Stars and last-push dates are from the GitHub API on Nov 3, 2026. Last-push times are given as dates only.

| Repo | Language | Licence | Activity | What it does | Notes for Provenance |
|---|---|---|---|---|---|
| robert/enf-matching, https://github.com/robert/enf-matching | Python | None stated | 101 stars, last push Jan 2024 | Minimal STFT extraction plus correlation matching, with a blog post at https://robertheaton.com/enf. Its demo uses ENF-WHU. | The clearest teaching code. No licence, so read it for ideas but don't copy it. |
| RaphaelJ/libhum, https://github.com/raphaelj/libhum | Python | LGPL-3.0 | 24 stars, last push Jan 2025 | Extraction and GPU-accelerated (CUDA or OpenCL) matching. It claims to match a 1-hour signal against 10 years in about 20 seconds on an M1. Installs with `pip install libhum`. | Could be an optional dependency. LGPL is fine as a separate library. |
| sch24r/hum-catcher, https://github.com/sch24r/hum-catcher | Python | MIT | 2 stars, last push Jan 2026 | Command-line tool with multi-harmonic STFT, flexible CSV import, coarse-to-fine matching, and an OpenCL backend. | MIT, so code can be reused with attribution. Small and young. |
| CoRoe/enf-matching, https://github.com/CoRoe/enf-matching | Python | MIT | 9 stars, last push Nov 2024 | hum.py for audio and flimmer.py for experimental video, matching against grid-operator history. | Video side is experimental. |
| nate-griff/enf, https://github.com/nate-griff/enf | Python | None stated | 1 star, last push Jul 2026 | Extraction (QIFFT, DP tracking, multitaper, multi-harmonic fusion), matching for EI, WECC, ERCOT and Quebec, a viewer, and a benchmark harness. | Good feature list to copy as ideas. No licence, and the reference data comes from FNET's public gauge (see the caution above). |
| BitEU/ENF-Extractor, https://github.com/BitEU/ENF-Extractor | Python | MIT | 1 star, last push Jul 2026 | Audio and video ENF trace extraction | New. Unreviewed. |
| deerajnagothu/pyenf_extraction, https://github.com/deerajnagothu/pyenf_extraction | Python and notebooks | CC BY-NC 4.0 per its README (GitHub shows NOASSERTION) | 22 stars, last push Mar 2026 | Audio and video extraction; video "still being tested" | Non-commercial licence. Avoid copying code. |
| CargoCultScientist/ENFormant, https://github.com/CargoCultScientist/ENFormant | Notebooks | BSD-2-Clause | 12 stars, last push Dec 2023 | Bellingcat-community sketch and notes | Notes only. |
| ghua-ac/ENF-WHU-Dataset, https://github.com/ghua-ac/ENF-WHU-Dataset | MATLAB | MIT | 36 stars, last push Jul 2023 | Dataset plus HRFA and GHSA (harmonic enhancement and selection) code | The reference implementation of Hua 2021. Can be ported. |
| cjs2094/ENF_extraction_from_videos, https://github.com/cjs2094/ENF_extraction_from_videos | MATLAB | None stated | 2 stars, last push Dec 2022 | Code for Choi et al. 2023, rolling-shutter video | The best video reference. No licence, so reimplement from the paper. |
| hyekyunghan/Phase-based-ENF-extraction-method, https://github.com/hyekyunghan/Phase-based-ENF-extraction-method | Python notebooks | None stated | 4 stars, last push Jul 2023 | Han et al. 2022 phase-based video method | Read only. |
| ckorgial/RELAX-ENF-Estimation and ckorgial/LAD-LRT-ENF-Estimation | MATLAB | MIT | 1 star each, last push Sep 2024 | Newer robust estimators (SETN 2024; IEEE Access 2024) | Optional extras. |

Bottom line: nothing mature and well-licensed covers the whole pipeline. The core math is short. I recommend writing Provenance's own NumPy and SciPy version, using libhum or hum-catcher (MIT) only as cross-checks.

## 5. Practical limits

**Recording length.** This matters most after signal quality. Hua et al. (arXiv 2020) matched against a one-week reference:
- About 5 minutes or more is reliable, given reasonable signal.
- Under 2 minutes, many false matches appear.
- Under 1 minute needs a very clean hum and a search window of hours, not weeks.
- With 8 minutes or more they reached 100 percent even with a reference 1,000 times longer than the clip.
- A 32-minute clip matched correctly within a 23-day reference.
- Most published work uses 10 minutes or more.

**Signal-to-noise.** About minus 25 dB or better at the harmonic is workable. Below about minus 30 dB nothing worked in their real-data tests.

**Timestamp accuracy.** Typically a few seconds to tens of seconds. Garg's 2011 video test was about 8 seconds. Hua's tests counted a match within 10 seconds as correct. One sample per second of ENF is plenty; finer steps don't help.

**Localization.**
- Grid identification works well: 50 versus 60 Hz is trivial, and the SP Cup teams separated US East, US West and Texas by trace statistics.
- Inside a grid, published results use clean outlet sensors: about 200 to 500 miles at roughly 90 percent accuracy, and failure at a few miles.
- For ordinary media recordings, treat within-grid location as hundreds of kilometres at best and often not possible. A radius from one power station is not physically meaningful, because every generator on a grid is locked to the same frequency.

**Phone and compressed audio.**
- Phones and voice recorders often cut off everything below about 100 Hz, and many apps do it silently. So plan on using the 120, 180, 240 and 360 Hz harmonics, not 60.
- Strong adaptive speech codecs can wipe out ENF; Hajj-Ahmad 2019 cites Adaptive Multi-Rate. Music-grade AAC and MP3 usually keep it, and Zinemanas 2018 showed MP3-robust splice detection.
- Noise suppression in calls and voice apps can remove hum [VERIFY per app].
- Outdoor recordings away from buildings often carry little or none. I ran a quick check on the author's 1-hour outdoor Long Island recording already in Provenance. It shows only weak lines at 60, 120 and 240 Hz, about 5 to 7 dB above the noise floor. The traces from different harmonics did not agree (correlation about 0.1), so a basic extractor finds no trustworthy ENF there.

**Movement.** Walking with the recorder smears the trace through the Doppler effect, and walking with it in a pocket destroyed it (Hajj-Ahmad 2019). That is the same physics Provenance already uses for planes.

**Lighting for video.**
- Incandescent and halogen bulbs work best.
- LEDs vary by driver. Well-filtered LED drivers flicker very little, and some LED and compact fluorescent cases showed no usable ENF (Frijters and Geradts 2022). Lights on inverters, battery or solar backup, or DC will not carry the grid's ENF.
- Daylight swamps the flicker.

**Video frame rate trap.** In a 60 Hz grid, lights flicker at 120 Hz. At exactly 30 or 60 frames per second, 120 Hz aliases to zero and the frame-average method fails. At 29.97 it lands near 0.12 Hz. The row-by-row rolling-shutter method avoids this, but it needs the camera's read-out time.

**Harmonics and 50 versus 60.** Check both 50 and 60 Hz families. Not every microphone shows every harmonic, so pick harmonics whose traces agree, rather than blindly using all of them (Hua 2021). Strong steady lines near 120 Hz can come from equipment rather than the grid, so confirm by cross-harmonic agreement.

**Anti-forensics.** ENF can be removed or faked (Chuang 2013), so report it as supporting evidence, not proof.

## 6. Questions I could not settle [VERIFY]

- Whether FNET/GridEye will share Western Interconnection history with an individual or a company, and on what terms.
- Whether ERCOT's public API archive includes a system-frequency product, and the refresh rate of its live page.
- Whether a free IEEE DataPort account is enough to download the SP Cup 2016 and rolling-shutter datasets.
- Whether netzfrequenzmessung.de offers a public historic archive.
- Whether Hua et al. 2020 ("Reliability of Power System Frequency...") appeared in a journal.
- The DOI for Hajj-Ahmad, Garg and Wu, APSIPA 2012.
- Whether US grid ENF statistics have drifted since the 2015 SP Cup recordings as inverter-based generation has grown, which could hurt a classifier trained on old data.
