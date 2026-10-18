"""S9b - a Minimoog-style three-oscillator voice on the PWM DAC (behavioural model).

Osc 1 saw, osc 2 saw +7 cent, osc 3 square one octave down, summed in firmware and played through the DAC,
the 2-pole reconstruction filter (15 kHz), ladder, VCA and line out. The pitch (glide, vibrato) comes from the
firmware layer of behav.py; the oscillator sum is band-limited to 20 kHz, as mip-mapped wavetables would be
(otherwise its ultrasonic content would intermodulate differently in each variant).
Variants:
  ref        ideal DAC (24 bit at 192 kHz) with the same filter: what three perfect oscillators would give
  dac94      93.75 kHz carrier, 8 bit, one sample per carrier period, first-order sigma-delta
  dac94_sdm2 as dac94 with second-order sigma-delta
  dac188     187.5 kHz carrier, 7 bit, one sample per carrier period, second-order sigma-delta
  dual94     93.75 kHz carrier, dual PWM (16 bit, 1 % ratio error), one sample per carrier period
The sum of three oscillators is scaled so its worst-case peak fits the DAC (each oscillator at 1/3).
The quantiser takes the full-resolution sum (an unlimited accumulator) and feeds its error back, so the
oscillators' own resolution does not matter. What remains is the 8-bit quantiser's noise; at 93.75 kHz (oversampling
ratio 2.3 for a 20 kHz band) first-order shaping lowers it by only ~2.6 dB, and it lies mostly at high
frequencies, so it shows with an open filter (-55 to -58 dB) and hides behind a closed one (-68 dB). At 187.5 kHz
(ratio 4.7) second-order shaping works: 7 bit reach -67 to -89 dB. An ideal DAC reaches -73 to -93 dB at 93.75 kHz
(sampling images) and -83 to -100 dB at 187.5 kHz.
Metric: the residual of each variant after the best linear fit from ref (quantisation noise, images and their
intermodulation; not delay or small response differences), re the ref level, 20 Hz - 20 kHz, per segment.

Output: docs/audio/s9_osc/moog_<variant>.mp3, docs/results/s9_moog.csv
"""
import os, sys
import numpy as np
from scipy.signal import resample_poly, butter, sosfiltfilt
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import s9_osc as S                                        # noqa: E402
from s9_osc import B, ADSR, ps                            # noqa: E402

DETUNE = 2 ** (7 / 1200)
VARIANTS = {
    "ref": dict(f_car=float(B.FS), ups=1, levels=2 ** 24, full=2 ** 24 - 1, order=1, dual=False, recon_fc=S.RC),
    "dac94": dict(S.V8, ups=1, recon_fc=S.RC),
    "dac94_sdm2": dict(S.V8, ups=1, order=2, recon_fc=S.RC),
    "dac188": dict(S.V7, recon_fc=S.RC),
    "dual94": dict(S.V8, ups=1, levels=65536, dual=True, mismatch=0.01, recon_fc=S.RC),
}
SEGMENTS = [
    ("bass", dict(saw=0.0, cutoff=250.0, env_amt=3.5, res=0.5, keytrack=0.3, fenv=ADSR(0.002, 0.18, 0.1, 0.1),
                  aenv=ADSR(0.002, 0.25, 0.7, 0.08), vol=0.8),
     S.seq([36, 36, 48, 36, 43, 36, 46, 48, 36, 36, 48, 36, 41, 43, 46, 51], 0.14, 0.75), 2.4, None),
    ("lead", dict(saw=0.0, cutoff=1800.0, env_amt=1.5, res=0.3, keytrack=0.5, glide=0.06, lfo_rate=5.5,
                  lfo_pitch=12.0, fenv=ADSR(0.01, 0.6, 0.4, 0.3), aenv=ADSR(0.01, 0.3, 0.9, 0.3), vol=0.8),
     [(0.05, 0.6, 67), (0.65, 0.3, 72), (0.95, 0.3, 74), (1.25, 0.9, 76), (2.15, 0.3, 74), (2.45, 0.3, 72),
      (2.75, 1.2, 79)], 4.3, None),
    ("open", dict(saw=0.0, cutoff=12000.0, res=0.0, aenv=ADSR(0.005, 0.2, 1.0, 0.2), vol=0.8),
     [(0.05, 1.4, 48), (1.5, 1.4, 60), (2.95, 1.4, 72)], 4.5, None),
]


def freq_track(reset, n):
    """Instantaneous frequency at FS from the firmware's DCO reset times (period by period)."""
    t = np.arange(n) / B.FS
    per = np.diff(reset)
    k = np.clip(np.searchsorted(reset, t, side="right") - 1, 0, len(per) - 1)
    return 1.0 / per[k]


def edges(f, n):
    """Times at which the phase of an oscillator with frequency track f crosses an integer."""
    ph = np.concatenate([[0.0], np.cumsum(f) / B.FS])
    k = np.floor(ph)
    i = np.nonzero(np.diff(k))[0]                              # crossing between sample i and i + 1
    frac = (k[i + 1] - ph[i]) / (ph[i + 1] - ph[i])
    return (i + frac) / B.FS


def oscillators(f, n):
    """Saw + saw +7 cent + square one octave down, each 0..2, summed and scaled to -HEAD..HEAD."""
    out = np.zeros(n)
    for ratio in (1.0, DETUNE):
        fr = f * ratio
        out += B.render_saw(edges(fr, n), 2.0 * fr / (1 - B.TP_RESET * fr), n)
    tq = edges(f, n)                                          # square at f/2: toggles at every period of f
    out += B.render_edges(tq, np.where(np.arange(len(tq)) % 2 == 0, 2.0, 0.0), n)
    return (out - 3.0) / 3.0 * S.HEAD


def render_segment(patch, notes, t_end, auto):
    ev, cv = B.firmware(notes, patch, t_end, auto)
    n = int(t_end * B.FS)
    x = oscillators(freq_track(ev["reset"], n), n)
    x = sosfiltfilt(butter(12, 20e3, fs=B.FS, output="sos"), x)   # wavetables carry harmonics up to 20 kHz
    ev2 = dict(ev, reset=np.array([]))
    cv2 = dict(cv, amp=np.zeros_like(cv["amp"]))
    out = {}
    for name, v in VARIANTS.items():
        fr = Fraction(v["f_car"] / v["ups"] / B.FS).limit_denominator(10000)
        xd = resample_poly(x, fr.numerator, fr.denominator, window=("kaiser", 10.0)) if fr != 1 else x
        ev2["dac"] = S.encode(xd, v)
        ev2["dac_cfg"] = dict(f_car=v["f_car"], levels=1.0, p=S.P_SAW, recon_fc=v["recon_fc"])
        out[name] = B.analog(ev2, cv2)[0]
    return out


def diff_db(y, ref, taps=33):
    """Residual of y after the best linear fit from ref (least-squares FIR, +-16 taps at 48 kHz), re the ref
    level, 20 Hz - 20 kHz: delay, gain and small response differences (interpolation, resampling) are not
    counted, only noise, images and distortion."""
    sos = butter(4, [20, 20e3], "bandpass", fs=B.FS_OUT, output="sos")
    yb, rb = sosfiltfilt(sos, y), sosfiltfilt(sos, ref)
    h = taps // 2
    A = np.stack([np.roll(rb, k) for k in range(-h, h + 1)], axis=1)[h:-h]
    c, *_ = np.linalg.lstsq(A, yb[h:-h], rcond=None)
    e = yb[h:-h] - A @ c
    return 10 * np.log10(np.mean(e ** 2) / np.mean(rb[h:-h] ** 2))


def main():
    full = {k: [] for k in VARIANTS}
    rows = []
    for seg, patch, notes, t_end, auto in SEGMENTS:
        print("segment", seg)
        ys = render_segment(patch, notes, t_end, auto)
        rows.append([seg] + [round(diff_db(ys[k], ys["ref"]), 1) for k in VARIANTS if k != "ref"])
        for k in VARIANTS:
            full[k] += [ys[k], np.zeros(int(S.GAP * B.FS_OUT))]
    for k in VARIANTS:
        S.write_audio("moog_" + k, np.concatenate(full[k]))
    ps.save_csv("s9_moog", ["segment"] + [f"diff_db_{k}" for k in VARIANTS if k != "ref"], rows)
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
