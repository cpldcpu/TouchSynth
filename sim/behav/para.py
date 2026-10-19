"""Paraphonic voice card: the card's oscillators (3 on the TouchSynth Poly voice) play independent notes, each with its own
pitch, waveform and level envelope, are mixed digitally and go through the card's one DAC, ladder filter and VCA.

The firmware model is the DAC path of dsp.py / behav.py (sim/s9_osc): one sample per period of the 187.5 kHz carrier, 7-bit
duty with second-order error feedback (dsp._sdm2), reconstructed by the ladder (behav.analog with ev['dac']). What is new is
only the oscillator side. Each oscillator is a list of *segments* (one note, or part of one, after the other, never
overlapping); a segment holds its control curves on the firmware's 1 ms control grid:

    dict(t0   = start time (s),
         wave = 'saw' | 'pulse' | 'noise' | 'sample',
         f    = per ms: oscillator frequency (Hz); for 'sample' the read rate in sample bytes per second,
         lvl  = per ms: level 0...1 (linear in between, as a block-wise level ramp in the firmware),
         pw   = pulse width 0...1 (number, or per ms) (pulse only),
         data = sample bytes as floats -1...1, pos0 = start position, loop = (start, length) or None (sample only),
         ramp = (fade in, fade out) in s, default (0.0005, 0.0015) (the first / last ms of a note are a short ramp),
         pan, cut, res = optional per ms (pan 0...255; filter cutoff in Hz, resonance 0...1 and digital high-pass corner in Hz (hp) that the note sets; the card
                         takes the values of its loudest sounding oscillator, card_param))

Waves: saw / pulse are the polyBLEP oscillators of dsp.render_osc (pulse = difference of two saws, zero mean); noise is the
16-bit LFSR of the DCO's noise source (taps 0 2 3 5) read at `noise_rate` (default 93.75 kHz), bits as +-1, an
oscillator slot of its own; sample plays 8-bit sample data at an arbitrary rate with linear interpolation, looping
(sim: the carrier-rate read; firmware: a 16.16 position, two byte loads and one multiply per sample).

paraphonic() returns (ev, cv, info) for behav.analog(): the digital sum (optionally a 12 dB/oct high pass `hp`, a
firmware filter that the voice does not have in the analog part) is scaled to a peak of 0.9 of full scale for the best use
of the 7 bits (`gain` = 'auto'), and the VCA takes the difference back (vca = nominal x ref / gain), so every card keeps the
same nominal level scale `ref`. The VCA is a gate over the sounding oscillators (+2 ms before, 6 ms after) by default.
"""
import numpy as np
from numba import njit
from scipy.signal import lfilter

import behav as B
import dsp

F_CAR = dsp.F_CAR
ARR = dsp.ARR
KPMS = F_CAR / 1000.0                    # carrier periods per control step (187.5)


@njit(cache=True)
def _lfsr(n, seed):
    out = np.empty(n, np.int8)
    s = seed
    for i in range(n):
        bit = ((s >> 0) ^ (s >> 2) ^ (s >> 3) ^ (s >> 5)) & 1
        s = (s >> 1) | (bit << 15)
        out[i] = s & 1
    return out


@njit(cache=True)
def _hp2(x, w):
    """Two cascaded one-pole high passes (12 dB/oct) with a corner of w/(2 pi) x carrier rate per sample (w = 0: through)."""
    n = x.shape[0]
    y = np.empty(n, np.float32)
    px = py1 = py2 = 0.0
    for i in range(n):
        a = 1.0 / (1.0 + w[i])
        v = a * (py1 + x[i] - px)           # stage 1
        px2 = py1
        py1 = v
        u = a * (py2 + v - px2)             # stage 2
        py2 = u
        px = x[i]
        y[i] = u
    return y


def _grid(seg):
    """Carrier-period index of the segment start, number of periods, control index and fraction of each period."""
    K = len(seg["f"])
    i0 = int(round(seg["t0"] * F_CAR))
    n = int(round(K * KPMS))
    u = (np.arange(n) + 0.5) / KPMS
    k = np.minimum(u.astype(np.int64), K - 1)
    return i0, n, k, u - np.floor(u)


def _level(seg, n, k, fr):
    lv = np.asarray(seg["lvl"], float)
    nxt = np.concatenate([lv[1:], lv[-1:]])
    x = lv[k] * (1 - fr) + nxt[k] * fr
    fi, fo = seg.get("ramp", (0.0005, 0.0015))
    ni, no = max(1, int(fi * F_CAR)), max(1, int(fo * F_CAR))
    x[:ni] *= np.linspace(0, 1, min(ni, n), endpoint=False)
    x[max(0, n - no):] *= np.linspace(1, 0, min(no, n))
    return x


def segment_signal(seg, noise=None, noise_rate=93750.0):
    """One segment -> (first carrier index, samples at the carrier rate)."""
    i0, n, k, fr = _grid(seg)
    f = np.asarray(seg["f"], float)[k]
    lv = _level(seg, n, k, fr)
    w = seg["wave"]
    if w in ("saw", "pulse"):
        dt = np.minimum(f / F_CAR, 0.45)
        ph = (seg.get("phase0", 0.0) + np.cumsum(dt)) % 1.0
        s = dsp.saw_blep(ph, dt)
        if w == "pulse":
            pw = seg.get("pw", 0.5)
            pw = np.asarray(pw, float)[k] if np.ndim(pw) else pw
            s = (s - dsp.saw_blep((ph + pw) % 1.0, dt)) / 2
    elif w == "noise":
        j = ((i0 + np.arange(n)) * (noise_rate / F_CAR)).astype(np.int64) % len(noise)
        s = 2.0 * noise[j] - 1.0
    elif w == "sample":
        d = seg["data"]
        pos = seg.get("pos0", 0.0) + np.concatenate([[0.0], np.cumsum(f[:-1] / F_CAR)])
        lp = seg.get("loop")
        if lp is not None and lp[1] > 2:
            end = lp[0] + lp[1]
            pos = np.where(pos >= end, lp[0] + (pos - lp[0]) % lp[1], pos)
            ok = np.ones(n, bool)
        else:
            ok = pos < len(d) - 1
        pos = np.where(ok, pos, 0.0)
        a = pos.astype(np.int64)
        b = np.minimum(a + 1, len(d) - 1)
        x = (pos - a)
        s = (d[a] * (1 - x) + d[b] * x) * ok
    else:
        raise ValueError(w)
    return i0, (s * lv).astype(np.float32)


def card_signal(tracks, t_end, hp=None, noise_rate=93750.0, seed=0xACE1):
    """tracks: list (per oscillator) of lists of segments. Returns the digital sum at the carrier rate (float32)."""
    n = int(t_end * F_CAR)
    acc = np.zeros(n, np.float32)
    nz = None
    if any(sg["wave"] == "noise" for tr in tracks for sg in tr):
        nz = _lfsr(int(t_end * noise_rate) + 10, seed).astype(np.float32)
    for o, tr in enumerate(tracks):
        nzo = None if nz is None else np.roll(nz, 20011 * o)
        for sg in tr:
            i0, y = segment_signal(sg, nzo, noise_rate)
            a, b = max(0, i0), min(n, i0 + len(y))
            if b > a:
                acc[a:b] += y[a - i0:b - i0]
    if hp is not None and np.any(np.asarray(hp) > 0):
        hpv = np.broadcast_to(np.asarray(hp, float), (max(1, int(np.ceil(t_end * 1000)) + 2),)) if np.ndim(hp) == 0 else np.asarray(hp, float)
        k = np.minimum((np.arange(n) / KPMS).astype(np.int64), len(hpv) - 1)
        acc = _hp2(acc, (2 * np.pi * hpv[k] / F_CAR).astype(np.float64))
    return acc


def level_track(tracks, n_ms):
    """Per ms: the highest oscillator level of the card (a control curve for the cutoff or the VCA to follow)."""
    out = np.zeros(n_ms)
    for tr in tracks:
        for sg in tr:
            k0 = int(round(sg["t0"] * 1000))
            lv = np.asarray(sg["lvl"], float)
            a, b = max(0, k0), min(n_ms, k0 + len(lv))
            if b > a:
                out[a:b] = np.maximum(out[a:b], lv[a - k0:b - k0])
    return out


def card_param(tracks, n_ms, key, default=0.0):
    """A card has one value of each analog parameter (pan, cutoff, resonance): per ms the one set by the loudest sounding
    oscillator's note (segments with `key` as a per-ms curve), held while the card is silent."""
    best, out = np.full(n_ms, -1.0), np.full(n_ms, np.nan)
    for tr in tracks:
        for sg in tr:
            if key not in sg:
                continue
            k0 = int(round(sg["t0"] * 1000))
            lv = np.asarray(sg["lvl"], float)
            v = np.asarray(sg[key], float)
            a, b = max(0, k0), min(n_ms, k0 + len(lv))
            if b <= a:
                continue
            lv, v = lv[a - k0:b - k0], v[a - k0:b - k0]
            win = (lv > 1e-6) & (lv > best[a:b])
            best[a:b] = np.where(win, lv, best[a:b])
            out[a:b] = np.where(win, v, out[a:b])
    ok = ~np.isnan(out)
    if not ok.any():
        return np.full(n_ms, default)
    idx = np.where(ok, np.arange(n_ms), 0)
    np.maximum.accumulate(idx, out=idx)
    out = out[idx]
    out[:int(np.argmax(ok))] = out[int(np.argmax(ok))]
    return out


def card_pan(tracks, n_ms, default=128.0):
    """Pan stage: the pan of the loudest sounding oscillator's note (card_param)."""
    return card_param(tracks, n_ms, "pan", default)


def paraphonic(tracks, t_end, cut, res=0.0, vca="gate", gain="auto", ref=0.15, hp=None, noise_rate=93750.0):
    """tracks as card_signal; cut: Hz (number or per ms), res: 0...1 of the self-oscillation point (number or per ms),
    hp: corner of the digital 12 dB/oct high pass on the sum, Hz (number or per ms; None / 0: off; it is a firmware
    filter, the analog part has none), vca: 'gate', 'open' or per ms linear 0...1 (before the gain compensation).
    Returns (ev, cv, info) for behav.analog."""
    x = card_signal(tracks, t_end, hp, noise_rate)
    peak = float(np.abs(x).max())
    g = 0.9 / peak if gain == "auto" and peak > 0 else (1.0 if gain == "auto" else float(gain))
    codes = dsp._sdm2((np.clip(x * g, -1, 1) + 1) / 2 * ARR, ARR + 1)
    n_ms = int(np.ceil(t_end * 1000)) + 2
    lv = level_track(tracks, n_ms)
    if isinstance(vca, str) and vca == "gate":
        on = (lv > 1e-3).astype(float)
        va = (np.convolve(on, np.ones(9))[2:2 + n_ms] > 0).astype(float)    # open 2 ms early, closed 6 ms late
    elif isinstance(vca, str) and vca == "open":
        va = np.ones(n_ms)
    else:
        va = np.resize(np.asarray(vca, float), n_ms)
    cutv = np.resize(np.asarray(cut, float), n_ms)
    resv = np.resize(np.asarray(res, float), n_ms)
    cv = dict(amp=np.zeros(n_ms), cut=B.cv_quant(B.cv_cut_for(cutv)), res=B.cv_quant(resv * B.RES_THRESH),
              vca=B.cv_quant(B.cv_vca_for(np.clip(va * ref / g, 0, 1))))
    ev = dict(t_end=t_end, reset=np.array([]), pulse=(np.array([]), np.array([])), sub=(np.array([]), np.array([])),
              noise=(np.array([]), np.array([])), dac=codes)
    info = dict(gain=g, peak=peak, rms_in=float(np.sqrt(np.mean(x.astype(np.float64) ** 2))), ref=ref,
                vca_limited=bool((va * ref / g).max() > 1.0))
    return ev, cv, info


def render_card(tracks, t_end, cut, **kw):
    """Convenience: paraphonic() through behav.analog. Returns (line-out voltage at 48 kHz, info)."""
    ev, cv, info = paraphonic(tracks, t_end, cut, **kw)
    y, _ = B.analog(ev, cv)
    return y.astype(np.float32), info
