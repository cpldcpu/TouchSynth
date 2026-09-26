"""Behavioural model of the TouchSynth voice (fast, Python/numba), calibrated against ngspice S1-S7.

Two layers, mirroring the real system:
  Firmware  : patch parameters -> note/timer events, pulse widths, sub/noise GPIO, 12-bit CVs @ 1 kHz
  Analog    : band-limited DCO/pulse/sub/noise (edge lists + polyBLEP), S2 CV filters, mixer + coupling,
              Moog ladder (tanh stages, resonance diff pair), VCA diff pair law from S4, output coupling.
Internal rate 192 kHz, output 48 kHz.
"""
import os, csv
import numpy as np
from scipy.signal import lfilter, resample_poly, bilinear
from numba import njit
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import voice

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES = os.path.join(ROOT, "docs", "results")
FS = 192_000
FS_OUT = 48_000
VT = 0.02585
TP_RESET = 3e-6
F_TIM = 48e6
T_CV = 1e-3

# ---------------------------------------------------------------- calibration data (from SPICE)
def _csv(name):
    with open(os.path.join(RES, name + ".csv"), encoding="utf-8") as fh:
        r = list(csv.reader(fh))
    return np.array([[float(x) for x in row[:4]] for row in r[1:]])

_cut = _csv("s3_cutoff")
CUT_CV, CUT_F = _cut[:, 0], _cut[:, 1]           # CV_CUT -> -3 dB frequency
_vg = _csv("s4_vca_gain")
VCA_CV, VCA_DB = _vg[:, 0], _vg[:, 1]              # CV_VCA -> small-signal gain [dB]
VCA_LIN = 10 ** (VCA_DB / 20)
RES_THRESH = _csv("s3_cal")[0, 0]                  # CV_RES at self-oscillation (S3)


def _k_table():
    """Resonance loop gain k(CV_RES): below threshold inverted from the S3 AC peak heights with the ideal
    4-pole ladder |H(fp)|/|H(0)|; k = 4 at the transient threshold; above it a fitted slope (K_SLOPE)."""
    w = np.logspace(-2, 1, 8000)
    ks = np.linspace(0, 3.995, 800)
    pr = np.array([20 * np.log10(np.abs(1 / ((1 + 1j * w) ** 4 + k)).max() * (1 + k)) for k in ks])
    pk = _csv("s3_res_peaks")
    cv = np.concatenate([[0.0], pk[:, 0], [RES_THRESH]])
    kk = np.concatenate([[0.0], np.interp(pk[:, 1], pr, ks), [4.0]])
    keep = cv <= RES_THRESH
    return cv[keep], kk[keep]


K_CV, K_K = _k_table()
K_SLOPE = 1.0          # dk/dV above threshold; fitted in validate.py (behav_cal.csv)


def k_of_cv(cv):
    cv = np.asarray(cv, float)
    return np.where(cv <= RES_THRESH, np.interp(cv, K_CV, K_K), 4.0 + K_SLOPE * (cv - RES_THRESH))

# DCO (S1): I = CV * K_DIV / RE, amplitude = I * T / C ; firmware gain calibration
C_INT, RE_DCO, K_DIV, A_TGT = 10e-9, 33e3, voice.LIN_RATIO, 2.0
GAIN_ERR = _csv("s1_cal")[0, 0]

# mixer (Thevenin of the mixer node, 1 uF / 15 k coupling into the ladder input)
A_SAW, A_DIG = 4.85 / 155.0, 4.85 / 475.0
F_MIX_HP = 10.6
INA_G = 11.0
VCA_ATT = 34.0
F_OUT_HP = 1.6


def cv_quant(v, bits=12):
    q = (2 ** bits - 1)
    return np.round(np.clip(v, 0, 5) / 5 * q) / q * 5


def cv_amp_for(f):
    return np.minimum(5.0, A_TGT * C_INT / (1 / np.asarray(f) - TP_RESET) * RE_DCO / K_DIV / GAIN_ERR)


def cv_cut_for(fc):
    return np.interp(np.log2(np.clip(fc, CUT_F[0], CUT_F[-1])), np.log2(CUT_F), CUT_CV)


def cv_vca_for(a):
    """linear amplitude 0..1 (re full gain) -> CV (inverse of the S4 law)"""
    a = np.asarray(a, float)
    rel = VCA_LIN / VCA_LIN[-1]
    return np.where(a <= 1e-5, 0.0, np.interp(a, rel, VCA_CV))


# ---------------------------------------------------------------- band-limited edge rendering
def render_edges(times, levels, n, level0=0.0):
    """Digital signal from an edge list (time of change, new level) with 2-point polyBLEP."""
    times = np.asarray(times, float); levels = np.asarray(levels, float)
    idx = np.searchsorted(times * FS, np.arange(n), side="right")   # number of edges <= sample time
    lv = np.concatenate([[level0], levels])
    y = lv[idx].astype(float)
    prev = np.concatenate([[level0], levels[:-1]])
    h = levels - prev
    pos = times * FS
    n0 = np.ceil(pos).astype(int)                                    # first sample at/after the edge
    d = n0 - pos                                                      # 0 <= d < 1
    ok = (n0 >= 1) & (n0 < n)
    np.add.at(y, n0[ok], -h[ok] * (1 - d[ok]) ** 2 / 2)
    np.add.at(y, n0[ok] - 1, h[ok] * d[ok] ** 2 / 2)
    return y


def render_saw(reset_times, slope, n):
    """Integrator saw: v = integral(slope) since the end of the last reset pulse; slope in V/s per sample."""
    if len(reset_times) == 0:
        return np.zeros(n)
    cum = np.concatenate([[0.0], np.cumsum(slope) / FS])              # cum[k] = integral up to sample k
    t = np.arange(n) / FS
    starts = np.asarray(reset_times) + TP_RESET
    k = np.searchsorted(starts, t, side="right") - 1
    valid = k >= 0
    s = np.where(valid, starts[np.clip(k, 0, None)], 0.0)
    cum_s = np.interp(s * FS, np.arange(n + 1), cum)
    v = np.where(valid, cum[:n] - cum_s, 0.0)
    v = np.maximum(v, 0.0)
    # polyBLEP at each reset (jump from the value just before the reset to 0)
    pos = np.asarray(reset_times) * FS
    n0 = np.ceil(pos).astype(int)
    d = n0 - pos
    ok = (n0 >= 2) & (n0 < n)
    h = -v[np.clip(n0 - 1, 0, n - 1)] - slope[np.clip(n0 - 1, 0, n - 1)] / FS * (1 - d)
    np.add.at(v, n0[ok], -h[ok] * (1 - d[ok]) ** 2 / 2)
    np.add.at(v, n0[ok] - 1, h[ok] * d[ok] ** 2 / 2)
    return v


def cv_filter(stairs):
    """S2 3-pole RC network (poles ~1.1 kHz) applied at FS."""
    y = stairs
    for fc in (1060.0, 1060.0, 1200.0):
        a = np.exp(-2 * np.pi * fc / FS)
        y = lfilter([1 - a], [1, -a], y, zi=[y[0] * a])[0]
    return y


def hp1(x, fc):
    b, a = bilinear([1, 0], [1, 2 * np.pi * fc], FS)
    return lfilter(b, a, x)


# ---------------------------------------------------------------- ladder
@njit(cache=True)
def _ladder(u, g, kres, rsoft):
    """Moog ladder, normalised to 2*VT. u: input (normalised), g: per-sample coefficient,
    kres: small-signal loop gain (4 = self-oscillation), rsoft: tanh drive of the resonance diff pair."""
    n = u.shape[0]
    y1 = y2 = y3 = y4 = 0.0
    out = np.empty(n)
    for i in range(n):
        fb = kres[i] / rsoft * np.tanh(rsoft * y4)
        x = np.tanh(u[i] - fb)
        t1 = np.tanh(y1); t2 = np.tanh(y2); t3 = np.tanh(y3)
        y1 += g[i] * (x - t1)
        y2 += g[i] * (np.tanh(y1) - t2)
        y3 += g[i] * (np.tanh(y2) - t3)
        y4 += g[i] * (np.tanh(y3) - np.tanh(y4))
        out[i] = y4
    return out


RSOFT = 0.846   # lpf/13 at the resonance pair, normalised to 2 VT (from the circuit)
# pole frequency = f(-3 dB) / POLE_RATIO; fitted in validate.py so the self-oscillation pitch matches ngspice
try:
    POLE_RATIO, K_SLOPE = _csv("behav_cal")[0, :2]
except Exception:
    POLE_RATIO = 0.435


def analog(ev, cv, rsoft=None, thump=0.0):
    """ev: dict of edge lists (reset, pulse, sub, noise); cv: dict of per-ms CV stairs (amp, cut, res, vca).
    Returns line-out voltage at FS_OUT and internal signals (at FS)."""
    rs = RSOFT if rsoft is None else rsoft
    n = int(ev["t_end"] * FS)
    def up(st):
        x = np.repeat(np.asarray(st, float), int(round(T_CV * FS)))
        x = x[:n] if len(x) >= n else np.concatenate([x, np.full(n - len(x), x[-1])])
        return cv_filter(x)
    cva, cvc, cvr, cvv = up(cv["amp"]), up(cv["cut"]), up(cv["res"]), up(cv["vca"])
    slope = cva * K_DIV / RE_DCO * GAIN_ERR / C_INT
    saw = render_saw(ev["reset"], slope, n)
    pulse = render_edges(*ev["pulse"], n) if len(ev["pulse"][0]) else np.zeros(n)
    sub = render_edges(*ev["sub"], n) if len(ev["sub"][0]) else np.zeros(n)
    noise = render_edges(*ev["noise"], n) if len(ev["noise"][0]) else np.zeros(n)
    mix = A_SAW * saw + A_DIG * (pulse + sub + noise)
    bin1 = hp1(mix, F_MIX_HP)
    bin1 = bin1 + 2e-6 * np.random.default_rng(1).standard_normal(n)   # circuit noise (starts self-oscillation)
    fp = np.interp(cvc, CUT_CV, CUT_F) / POLE_RATIO
    g = 1 - np.exp(-2 * np.pi * np.minimum(fp, 0.45 * FS) / FS)
    kres = k_of_cv(cvr)
    y4 = _ladder(bin1 / (2 * VT), g, kres, rs)
    lpf = INA_G * 2 * VT * y4
    gain = np.interp(cvv, VCA_CV, VCA_LIN)
    vin = VCA_ATT * 2 * VT
    out = gain * vin * np.tanh(lpf / vin)
    out = out + thump * (cvv / 5.0)                 # untrimmed VCA CV feedthrough (demo only)
    out = hp1(out, F_OUT_HP)
    y = resample_poly(out, 1, FS // FS_OUT)
    return y, dict(saw=saw, lpf=lpf, bin1=bin1, cvc=cvc, cvv=cvv)


# ---------------------------------------------------------------- firmware layer
def mtof(m):
    return 440.0 * 2 ** ((np.asarray(m, float) - 69) / 12)


def timer_period(f):
    psc = 1 if F_TIM / f < 65536 else int(np.ceil(F_TIM / f / 65536))
    arr = round(F_TIM / psc / f)
    return psc * arr / F_TIM


class ADSR:
    def __init__(self, a=0.005, d=0.2, s=0.7, r=0.2):
        self.a, self.d, self.s, self.r = max(a, 1e-4), max(d, 1e-4), s, max(r, 1e-4)

    def __call__(self, t, t_on, t_off):
        if t < t_on:
            return 0.0
        if t_off is None or t < t_off:
            x = t - t_on
            return x / self.a if x < self.a else self.s + (1 - self.s) * np.exp(-(x - self.a) / self.d)
        return self(t_off - 1e-9, t_on, None) * np.exp(-(t - t_off) / self.r)


DEFAULT = dict(saw=1.0, pulse=0, sub=0, noise=0, pw=0.5, cutoff=8000.0, env_amt=0.0, keytrack=0.0,
               res=0.0, fenv=ADSR(0.002, 0.3, 0.0, 0.2), aenv=ADSR(0.003, 0.3, 1.0, 0.1), glide=0.0,
               lfo_rate=5.0, lfo_pitch=0.0, lfo_cut=0.0, lfo_pw=0.0, vol=0.9, noise_rate=46875.0)


def _patch(d):
    """Accept ADSR given as ('adsr', a, d, s, r) tuples (preset files) as well as ADSR objects."""
    out = {}
    for k, v in (d or {}).items():
        out[k] = ADSR(*v[1:]) if isinstance(v, tuple) and v and v[0] == "adsr" else v
    for k in ("accent", "slide"):
        out.pop(k, None)
    return out


def firmware(notes, patch, t_end, automation=None):
    """notes: list of (t_on, dur, midi). Mono, last-note priority. automation: f(t, p) -> dict overrides.
    Returns (events, cvs) for analog()."""
    p = dict(DEFAULT); p.update(_patch(patch))
    notes = sorted([tuple(nt) if len(nt) == 4 else (*nt, {}) for nt in notes], key=lambda x: x[0])
    ts = np.arange(0, t_end, T_CV)
    cv = {k: np.zeros(len(ts)) for k in ("amp", "cut", "res", "vca")}
    pitch_track = np.zeros(len(ts)); pw_track = np.zeros(len(ts)); flags = []
    cur = None; pitch = None
    for i, t in enumerate(ts):
        q = dict(p)
        on = [nt for nt in notes if nt[0] <= t]
        held = [nt for nt in on if t < nt[0] + nt[1]]
        last = on[-1] if on else None
        if held:
            cur = held[-1]
        elif last is not None:
            cur = last
        if cur is None:
            flags.append((0, 0, 0)); continue
        t_on, dur, m, ov = cur
        q.update(_patch(ov))
        if automation:
            q.update(_patch(automation(t, q)))
        t_off = t_on + dur if not held else None
        target = float(m)
        if pitch is None:
            pitch = target
        if q["glide"] > 0:
            pitch += (target - pitch) * (1 - np.exp(-T_CV / q["glide"]))
        else:
            pitch = target
        lfo = 2 * abs(2 * ((t * q["lfo_rate"]) % 1) - 1) - 1          # triangle -1..1
        pm = pitch + q["lfo_pitch"] / 100 * lfo
        f = float(mtof(pm)); T = timer_period(f)
        pitch_track[i] = 1 / T
        fenv = q["fenv"](t, t_on, t_off); aenv = q["aenv"](t, t_on, t_off)
        fc = q["cutoff"] * 2 ** (q["env_amt"] * fenv + q["lfo_cut"] * lfo + q["keytrack"] * (pm - 60) / 12)
        cv["amp"][i] = cv_amp_for(1 / T) * q["saw"]
        cv["cut"][i] = cv_cut_for(fc)
        cv["res"][i] = q["res"] * RES_THRESH
        cv["vca"][i] = cv_vca_for(q["vol"] * aenv)
        pw_track[i] = np.clip(q["pw"] + q["lfo_pw"] * lfo, 0.03, 0.97)
        flags.append((q["pulse"], q["sub"], q["noise"]))
    for k in cv:
        cv[k] = cv_quant(cv[k])
    # timer events: the period is updated at each reset (ARR preload) from the control-rate pitch
    reset, pt, pl, st, sl = [], [], [], [], []
    t, k = 0.0, 0
    sub_lvl = 0.0
    while t < t_end:
        i = min(int(t / T_CV), len(ts) - 1)
        f = pitch_track[i]
        if f <= 0:
            t += T_CV; continue
        T = 1 / f
        reset.append(t)
        pon, son, _ = flags[i]
        if pon:
            pt += [t, t + pw_track[i] * T]; pl += [5.0, 0.0]
        sub_lvl = (5.0 if k % 2 == 0 else 0.0) if son else 0.0
        st.append(t); sl.append(sub_lvl)
        t += T; k += 1
    # noise: 16-bit LFSR clocked from the TIM1 update rate, gated by the noise flag
    nt, nl = [], []
    lfsr = 0xACE1
    tn = 0.0; dt = 1 / p["noise_rate"]
    while tn < t_end:
        i = min(int(tn / T_CV), len(ts) - 1)
        bit = ((lfsr >> 0) ^ (lfsr >> 2) ^ (lfsr >> 3) ^ (lfsr >> 5)) & 1
        lfsr = (lfsr >> 1) | (bit << 15)
        nt.append(tn); nl.append(5.0 * (lfsr & 1) if flags[i][2] else 0.0)
        tn += dt
    ev = dict(t_end=t_end, reset=np.array(reset), pulse=(np.array(pt), np.array(pl)),
              sub=(np.array(st), np.array(sl)), noise=(np.array(nt), np.array(nl)))
    return ev, cv


def render(notes, patch, t_end, automation=None, **kw):
    ev, cv = firmware(notes, patch, t_end, automation)
    return analog(ev, cv, **kw)
