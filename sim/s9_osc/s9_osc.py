"""S9 - analog DCO against digital oscillators on the PWM DAC (behavioural model, design study for the poly voice).

The same notes and patches play through several oscillator sources; filter, VCA and line out are the same model:
  a_dco          the analog integrator saw (rev 0.1)
  b_dac_now      DAC mode as on board 1: 15.625 kHz samples, 8 bit, centre-aligned 93.75 kHz carrier, linear
                 interpolation, first-order error feedback; the ladder is the reconstruction filter
  c_dac_94k      firmware-only change: one sample per carrier period (93.75 kHz, no interpolation), 8 bit
  d_dac_94k_rc   c plus a 2-pole reconstruction filter (Butterworth, 15 kHz) before the mixer
  e_dac_dual_rc  d with dual PWM (high and low byte summed 256:1, 16 bit, 1 % ratio error not corrected)
  f_dac_375k_rc  375 kHz carrier (6 bit, 65 levels), 93.75 kHz samples linearly interpolated over 4 carrier
                 periods, second-order sigma-delta (error feedback, NTF (1 - z^-1)^2), the 2-pole filter
  g_dac_188k     firmware-only: 187.5 kHz carrier (7 bit, 129 levels), one 187.5 kHz sample per carrier period
                 (no interpolation), second-order sigma-delta
  h_dac_188k_rc  g plus the 2-pole filter
Quantisation is not the limit (6 or 7 bit with second-order noise shaping equal an ideal DAC within 1 dB here);
the sampling images are: they intermodulate in the ladder and VCA into the audio band. Linear interpolation at
46.875 kHz samples leaves a floor of about -45 dB, at 93.75 kHz about -46 to -60 dB (with the carrier's own
sample-and-hold images, which the model shows since 2026-10-18); one sample per carrier period
at 187.5 kHz comes within a few dB of the DCO.
The digital saw is the DCO's own waveform, ideally band-limited to the DAC's Nyquist frequency (the best a
mip-mapped wavetable can do; a real one adds a little interpolation error). All DAC variants have the saw's level
at the mixer, so loudness and ladder drive match. Not modelled: carrier crosstalk past the filter and VCA
(board 1: 5.8 mV at the line out), board noise (board 1: about -55 dB), analog imperfections of the DCO.

Program (one file per variant): open-filter scale C2..C7, open-filter glide C3 -> C7, acid bass, filter sweep with
resonance, lead. Metric (G2..C7): inharmonic content (aliasing + quantisation noise) of each scale note, the energy away
from the note's harmonics relative to the total, 20 Hz - 20 kHz.

Output: docs/audio/s9_osc/<variant>.mp3, docs/figures/s9_osc.(pdf|png), docs/results/s9_osc.csv
"""
import os, sys, subprocess, wave
import numpy as np
from numba import njit
from scipy.signal import resample_poly
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "behav"), os.path.join(HERE, "..", "lib")]
import behav as B                                         # noqa: E402
from behav import ADSR                                    # noqa: E402
import plotstyle as ps                                    # noqa: E402

OUT = os.path.join(HERE, "out")
AUD = os.path.join(B.ROOT, "docs", "audio", "s9_osc")
FULL_SCALE = 2.0                                          # 2 V line out = 0 dBFS (as docs/audio/features)
F_CAR = 48e6 / 512                                        # 93.75 kHz centre-aligned carrier (ARR 256)
F_CAR2 = 48e6 / 256                                       # 187.5 kHz (ARR 128)
F_CAR4 = 48e6 / 128                                       # 375 kHz (ARR 64)
HEAD = 0.95                                               # digital saw peak re DAC full scale
P_SAW = B.A_TGT * B.A_SAW / HEAD                          # DAC swing at the mixer for the saw's level
RC = 15e3

# f_car, samples per carrier period (ups), code levels and full-scale count, noise-shaping order, dual PWM, filter
V8 = dict(f_car=F_CAR, levels=256, full=255, order=1, dual=False, recon_fc=None)
V6 = dict(f_car=F_CAR4, ups=4, levels=65, full=64, order=2, dual=False, recon_fc=None)
V7 = dict(f_car=F_CAR2, ups=1, levels=129, full=128, order=2, dual=False, recon_fc=None)
VARIANTS = {
    "a_dco": None,
    "b_dac_now": dict(V8, ups=6),
    "c_dac_94k": dict(V8, ups=1),
    "d_dac_94k_rc": dict(V8, ups=1, recon_fc=RC),
    "e_dac_dual_rc": dict(V8, ups=1, levels=65536, dual=True, mismatch=0.01, recon_fc=RC),
    "f_dac_375k_rc": dict(V6, recon_fc=RC),
    "g_dac_188k": dict(V7),
    "h_dac_188k_rc": dict(V7, recon_fc=RC),
}
LABEL = {"a_dco": "analog DCO", "b_dac_now": "DAC now (15.6 kHz, 8 bit)", "c_dac_94k": "93.75 kHz, 8 bit",
         "d_dac_94k_rc": "93.75 kHz, 8 bit, filter", "e_dac_dual_rc": "93.75 kHz, dual PWM 16 bit, filter",
         "f_dac_375k_rc": "375 kHz, 6 bit, SDM2, interpolated, filter",
         "g_dac_188k": "187.5 kHz, 7 bit, SDM2", "h_dac_188k_rc": "187.5 kHz, 7 bit, SDM2, filter"}

OPEN = dict(cutoff=16000.0, res=0.0, env_amt=0.0, aenv=ADSR(0.005, 0.2, 1.0, 0.1), vol=0.8)
SCALE = [36, 43, 48, 55, 60, 67, 72, 79, 84, 91, 96]
STEP = 0.4


def seq(ms, step, gate=0.9, t0=0.05):
    return [(t0 + i * step, step * gate, m) for i, m in enumerate(ms)]


def sweep(t, p):
    x = np.clip((t - 0.3) / 4.4, 0, 1)
    return dict(cutoff=150.0 * (12000.0 / 150.0) ** (1 - abs(2 * x - 1)))


SEGMENTS = [
    ("scale", OPEN, seq(SCALE, STEP), len(SCALE) * STEP + 0.2, None),
    ("glide", dict(OPEN, glide=0.7), [(0.05, 0.4, 48), (0.45, 3.0, 96)], 3.6, None),
    ("acid", dict(cutoff=350.0, env_amt=3.2, res=0.6, fenv=ADSR(0.001, 0.15, 0.0, 0.05),
                  aenv=ADSR(0.002, 0.2, 0.6, 0.05), vol=0.8),
     seq([36, 36, 48, 36, 39, 36, 46, 48] * 2, 0.115, 0.7), 2.0, None),
    ("sweep", dict(res=0.45, aenv=ADSR(0.01, 0.2, 1.0, 0.2), vol=0.8), [(0.05, 4.8, 40)], 5.2, sweep),
    ("lead", dict(cutoff=5000.0, res=0.2, glide=0.03, aenv=ADSR(0.005, 0.2, 0.9, 0.1), vol=0.8),
     seq([72, 76, 79, 84, 83, 79, 76, 74, 72], 0.25, 0.85), 2.6, None),
]
GAP = 0.4


@njit(cache=True)
def _quantise(v, levels, order):
    """Error-feedback quantiser at the carrier rate (v in 0..levels-1 -> integer codes), noise transfer
    function (1 - z^-1)^order, order 1 or 2."""
    out = np.empty(v.shape[0], np.int64)
    e1 = e2 = 0.0
    for i in range(v.shape[0]):
        w = v[i] + e1 if order == 1 else v[i] + 2.0 * e1 - e2
        q = min(levels - 1, max(0, int(round(w))))
        e2 = e1
        e1 = w - q
        out[i] = q
    return out


def encode(x, v):
    """Samples -1..1 at f_car/ups -> duty 0..1 per carrier period; linear interpolation from the previous sample
    over `ups` periods (as the firmware). Dual PWM: 16-bit code as high byte + low byte / 256, the low byte's
    weight off by `mismatch`."""
    ups, levels = v["ups"], v["levels"]
    c = (np.clip(x, -1, 1) + 1) / 2 * (levels - 1)
    prev = np.concatenate([[c[0]], c[:-1]])
    u = (prev[:, None] + (c - prev)[:, None] * (np.arange(1, ups + 1) / ups)[None, :]).ravel()
    q = _quantise(u, levels, v["order"])
    if v["dual"]:
        return ((q >> 8) + (q & 255) / 256.0 * (1.0 + v.get("mismatch", 0.0))) / 256.0
    return q / v["full"]


def render_segment(patch, notes, t_end, auto):
    ev, cv = B.firmware(notes, patch, t_end, auto)
    y_a, sig = B.analog(ev, cv)
    out = {"a_dco": y_a}
    x = (sig["saw"] - B.A_TGT / 2) / (B.A_TGT / 2) * HEAD     # the DCO's saw, -1..1 at FS
    ev2 = dict(ev, reset=np.array([]))
    cv2 = dict(cv, amp=np.zeros_like(cv["amp"]))
    for name, v in VARIANTS.items():
        if v is None:
            continue
        fr = Fraction(v["f_car"] / v["ups"] / B.FS).limit_denominator(10000)
        xd = resample_poly(x, fr.numerator, fr.denominator, window=("kaiser", 10.0))     # ideal band limit at the sample rate / 2
        ev2["dac"] = encode(xd, v)
        ev2["dac_cfg"] = dict(f_car=v["f_car"], levels=1.0, p=P_SAW, recon_fc=v["recon_fc"])
        out[name] = B.analog(ev2, cv2)[0]
    return out


def inharmonic_db(y, f0, fs=B.FS_OUT):
    """Energy away from the harmonics of f0 (+-1.5 % or 6 bins) re the total, 20 Hz - 20 kHz (4-term
    Blackman-Harris window, sidelobes -92 dB, so leakage of the harmonics stays below the measured floor)."""
    from scipy.signal.windows import blackmanharris
    w = blackmanharris(len(y))
    S = np.abs(np.fft.rfft(y * w)) ** 2
    f = np.fft.rfftfreq(len(y), 1 / fs)
    band = (f > 20) & (f < 20e3)
    h = np.round(f / f0)
    tol = np.maximum(0.015 * f0, 6 * fs / len(y))
    harm = (h >= 1) & (np.abs(f - h * f0) <= tol)
    return 10 * np.log10(S[band & ~harm].sum() / S[band].sum())


def write_audio(name, y):
    os.makedirs(OUT, exist_ok=True); os.makedirs(AUD, exist_ok=True)
    wav = os.path.join(OUT, name + ".wav")
    pcm = np.int16(np.clip(y / FULL_SCALE, -1, 1) * 32767)
    with wave.open(wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(B.FS_OUT); w.writeframes(pcm.tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-codec:a", "libmp3lame", "-q:a", "2",
                    os.path.join(AUD, name + ".mp3")], check=True)


def figure(glide):
    import matplotlib.pyplot as plt
    from scipy.signal import spectrogram
    f, axes = ps.fig(2, 4, aspect=0.5, sharex=True, sharey=True)
    for ax, (name, y) in zip(axes.flat, glide.items()):
        fq, tt, S = spectrogram(y, B.FS_OUT, nperseg=2048, noverlap=1792)
        ax.pcolormesh(tt, fq / 1000, 10 * np.log10(S + 1e-14), shading="auto", cmap="magma", vmin=-130, vmax=-40,
                      rasterized=True)
        ax.set_title(LABEL[name], fontsize=8)
        ax.grid(False)
    for ax in axes[-1]:
        ax.set_xlabel("$t$ [s]")
    for ax in axes[:, 0]:
        ax.set_ylabel("$f$ [kHz]")
    axes[0, 0].set_ylim(0, 20)
    ps.label_panels(axes)
    f.tight_layout()
    ps.save(f, "s9_osc")
    plt.close(f)


def main():
    full = {k: [] for k in VARIANTS}
    glide = None
    rows = []
    for seg, patch, notes, t_end, auto in SEGMENTS:
        print("segment", seg)
        ys = render_segment(patch, notes, t_end, auto)
        if seg == "glide":
            glide = ys
        if seg == "scale":
            for i, m in enumerate(SCALE):                # steady part of each note; C2 is skipped: its
                if m < 40:                               # harmonics are too dense for a 0.22 s window
                    continue
                a, b = int((0.05 + i * STEP + 0.12) * B.FS_OUT), int((0.05 + i * STEP + 0.34) * B.FS_OUT)
                f0 = float(B.mtof(m))
                rows.append([m, round(f0, 2)] + [round(inharmonic_db(ys[k][a:b], f0), 1) for k in VARIANTS])
        for k in VARIANTS:
            full[k] += [ys[k], np.zeros(int(GAP * B.FS_OUT))]
    for k in VARIANTS:
        write_audio(k, np.concatenate(full[k]))
    ps.save_csv("s9_osc", ["midi", "f0_hz"] + [f"inharm_db_{k}" for k in VARIANTS], rows)
    figure(glide)
    print(f"{'note':>5s} {'f0':>8s} " + " ".join(f"{k:>10s}" for k in VARIANTS))
    for r in rows:
        print(f"{r[0]:5d} {r[1]:8.1f} " + " ".join(f"{v:10.1f}" for v in r[2:]))


if __name__ == "__main__":
    main()
