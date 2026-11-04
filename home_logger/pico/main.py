# Grid frequency counter for a Raspberry Pi Pico (RP2040) or Pico 2 (RP2350), MicroPython.
#
# Same idea as jp3141/60Hz (Teensy 3.2): count WHOLE mains cycles against a fast crystal clock,
# and calibrate that clock with the GPS 1 pulse-per-second signal.
#   GP2  <- mains pulses from the optocoupler (one rising edge per 60 Hz cycle)
#   GP3  <- GPS PPS (rising edge at the start of each UTC second)
#   USB  -> Raspberry Pi 5 (power + serial /dev/ttyACM0)
# Every PPS the Pico prints one line for the second that just ended:
#   F,<n>,<cycles>,<clock_cycles>,<freq_hz>,<clock_ppm>,<flags>
# flags: OK | NOPPS (GPS pulse missing: timed by the Pico's own clock with the last calibration)
#        | CAL (still calibrating, first ~16 s) | GLITCH (a noise edge was merged)
# STATUS: written from the RP2040 datasheet and MicroPython docs; NOT yet run on real hardware [VERIFY].
import machine
import micropython
import rp2
import time
from machine import Pin

MAINS_PIN = 2
PPS_PIN = 3
NOMINAL = 60
FILTER_S = 16            # clock calibration time constant (jp3141 uses 16 s)
micropython.alloc_emergency_exception_buf(100)


@rp2.asm_pio()
def edge_timestamp():
    # Free-running down counter X, 1 count per 2 system clocks. On every rising edge of the
    # jmp pin, push X. The edge costs 3 un-counted clocks, a constant corrected on the host side.
    mov(x, invert(null))
    wrap_target()
    label("low")
    jmp(pin, "rise")
    jmp(x_dec, "low")
    label("rise")
    mov(isr, x)
    push(noblock)
    label("high")
    jmp(x_dec, "h2")
    label("h2")
    jmp(pin, "high")
    wrap()


SYS = machine.freq()
sm = rp2.StateMachine(0, edge_timestamp, freq=SYS, jmp_pin=Pin(MAINS_PIN, Pin.IN, Pin.PULL_UP),
                      in_base=Pin(MAINS_PIN))
pps_us = [0, 0]          # [ticks_us at last PPS, count]


def on_pps(p):
    pps_us[0] = time.ticks_us()
    pps_us[1] += 1


Pin(PPS_PIN, Pin.IN).irq(on_pps, Pin.IRQ_RISING, hard=True)
led = Pin("LED", Pin.OUT)


def main():
    sm.active(1)
    last_x = None
    cyc, clk, glitch = 0, 0, False
    pend = 0                       # clocks of a too-short (noise) period carried into the next one
    min_clk = SYS / NOMINAL * 0.8
    seen_pps, last_pps_us = pps_us[1], None
    ppm = 0.0
    n = 0
    t_self = time.ticks_us()
    while True:
        while sm.rx_fifo():
            x = sm.get()
            if x == 0xFFFFFFFF:     # counter wrap (every ~69 s) pushes a dummy value: ignore
                continue
            if last_x is not None:
                d = 2 * ((last_x - x) & 0xFFFFFFFF) + 3 + pend
                if d < min_clk:        # noise edge: merge into the next period
                    pend = d
                    glitch = True
                else:
                    pend = 0
                    cyc += 1
                    clk += d
            last_x = x
        now_pps = pps_us[1]
        timed_out = time.ticks_diff(time.ticks_us(), t_self) > 1_500_000
        if now_pps != seen_pps or timed_out:
            if now_pps != seen_pps:
                t = pps_us[0]
                if last_pps_us is not None and now_pps == seen_pps + 1:
                    dt = time.ticks_diff(t, last_pps_us)            # microseconds of the Pico clock per GPS second
                    if 999_000 < dt < 1_001_000:
                        e = (dt - 1_000_000)                     # ppm
                        k = 1.0 / min(FILTER_S, n + 1)
                        ppm += k * (e - ppm)
                last_pps_us, seen_pps, t_self = t, now_pps, t
                flag = "CAL" if n < FILTER_S else "OK"
            else:
                t_self = time.ticks_add(t_self, 1_000_000)
                flag = "NOPPS"
            if glitch:
                flag += "|GLITCH"
            f = cyc * SYS * (1 + ppm * 1e-6) / clk if clk else 0.0
            print("F,%d,%d,%d,%.6f,%.3f,%s" % (n, cyc, clk, f, ppm, flag))
            led.toggle()
            n += 1
            cyc, clk, glitch = 0, 0, False


main()
