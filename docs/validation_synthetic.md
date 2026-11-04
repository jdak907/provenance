# Validation across random synthetic scenes

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
