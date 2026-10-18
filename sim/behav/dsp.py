"""Digital voices on the pulse output used as a PWM DAC (mirrors the firmware's DAC mode).

TIM2 runs centre-aligned over 2 x 256 ticks: a 93.75 kHz carrier with 8-bit duty and symmetric pulses; the DMA
loads the duty from a ring buffer. The firmware synthesises at FS_DAC = 15.625 kHz, interpolates linearly from
the previous sample over the UPS = 6 carrier periods of a sample, and quantises each period's duty with
first-order error feedback (noise shaping), so the average follows the signal with sub-LSB accuracy.
The ladder filter is the reconstruction filter (sim/s8_dac).

Voices:
  modal  a bank of two-pole resonators per stroke, one per drum mode (ratio to the note, level, decay time),
         excited by a raised-cosine mallet pulse; strokes on the same note add up (a restruck drum), a stroke on a
         new note takes the oldest of `voices` banks. The sum passes a cubic soft clipper before the encoder.
"""
import numpy as np
from numba import njit
from scipy.signal import lfilter

F_TIM, ARR, UPS = 48e6, 256, 6
F_CAR = F_TIM / (2 * ARR)               # 93.75 kHz (centre-aligned)
FS_DAC = F_CAR / UPS                    # 15.625 kHz (drum modes stay below 2 kHz)


@njit(cache=True)
def _encode(v):
    out = np.empty(v.shape[0], np.int32)
    err = 0.0
    for i in range(v.shape[0]):
        q = int(round(v[i] + err))
        q = min(ARR - 1, max(0, q))
        err += v[i] - q
        out[i] = q
    return out


def encode(x):
    """Samples -1...1 at FS_DAC -> duty codes 0...255 per carrier period: linear interpolation from the
    previous sample over UPS periods (as the firmware), error feedback."""
    c = (np.clip(np.asarray(x, float), -1, 1) + 1) / 2 * (ARR - 1)
    prev = np.concatenate([[(ARR - 1) / 2], c[:-1]])
    v = (prev[:, None] + (c - prev)[:, None] * (np.arange(1, UPS + 1) / UPS)[None, :]).ravel()
    return _encode(v)


def mtof(m):
    return 440.0 * 2 ** ((np.asarray(m, float) - 69) / 12)


def mallet(ms):
    """Raised-cosine contact pulse of `ms` milliseconds, unit sum (a soft felt mallet low-passes the modes)."""
    n = max(1, int(round(ms * 1e-3 * FS_DAC)))
    p = 0.5 - 0.5 * np.cos(2 * np.pi * (np.arange(n) + 0.5) / n)
    return p / p.sum()


def modal_stroke(f0, modes, n, exc):
    """Response of one resonator bank (modes: (ratio, level dB, decay time constant s)) to excitation exc."""
    x = np.zeros(n)
    x[:min(n, len(exc))] = exc[:n]
    y = np.zeros(n)
    for ratio, lvl_db, tau in modes:
        f = f0 * ratio
        if f >= 0.45 * FS_DAC:
            continue
        w = 2 * np.pi * f / FS_DAC
        r = np.exp(-1.0 / (tau * FS_DAC))
        b = 10 ** (lvl_db / 20) * np.sin(w)          # impulse response amplitude = 10^(dB/20)
        y += lfilter([b], [1.0, -2 * r * np.cos(w), r * r], x)
    return y


def render(notes, p, t_end):
    """notes: (t_on, dur, midi, overrides) sorted; p['dsp'] = dict(kind, ...). Returns samples at FS_DAC."""
    d = p["dsp"]
    n = int(t_end * FS_DAC) + 1
    out = np.zeros(n)
    if d["kind"] != "modal":
        raise ValueError(d["kind"])
    exc = mallet(d.get("mallet_ms", 3.0))
    banks = []                                           # [(note, start index)] in use, oldest first
    starts = []
    for t_on, dur, m, ov in notes:
        a = int(t_on * FS_DAC)
        vel = (ov or {}).get("vol", p.get("vol", 0.9))      # firmware: patch vol, or the accent's vol
        starts.append((a, m, min(1.0, vel)))
    starts.sort()
    fade = int(0.005 * FS_DAC)
    for i, (a, m, vel) in enumerate(starts):
        # end of this stroke: when its bank is taken by a different note (voice stealing)
        live = [m]
        end = n
        for b, m2, _ in starts[i + 1:]:
            if m2 not in live:
                live.append(m2)
                if len(live) > d.get("voices", 2):
                    end = b
                    break
        seg = modal_stroke(mtof(m), d["modes"], end - a, exc * vel)
        if end < n:
            seg[-fade:] *= np.linspace(1, 0, min(fade, len(seg)))
        out[a:end] += seg
    return softclip(out * d.get("gain", 0.5))


def softclip(x):
    """Cubic soft clipper (as the firmware): 1.5 x - 0.5 x^3 up to |x| = 1, then 1; linear-ish below 0.5."""
    x = np.clip(x, -1, 1)
    return 1.5 * x - 0.5 * x ** 3
