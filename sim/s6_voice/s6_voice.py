"""S6 - full voice: DCO -> mixer -> ladder VCF (+resonance) -> VCA -> line out, driven by a Python model
of the firmware (TIM2 periods quantised at 48 MHz, 1 kHz CV update, ADSR envelopes). Output rendered to WAV.

CVs are applied as their PWM averages through the real S2 filter networks (ripple verified separately in S2).
"""
import os, sys, csv, wave
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import spice
import plotstyle as ps
import voice

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
ROOT = os.path.dirname(os.path.dirname(HERE))
RES = os.path.join(ROOT, "docs", "results")
FS_WAV = 48000
T_CV = 1e-3            # firmware control-rate tick
TP_RESET = 3e-6

# ---- calibrations from S1 / S3 / S4 ------------------------------------------------
C_INT, RE_DCO, K_DIV, A_TGT = 10e-9, 33e3, voice.LIN_RATIO, 2.0


def cv_amp(f):
    return min(5.0, A_TGT * C_INT / (1 / f - TP_RESET) * RE_DCO / K_DIV * GAIN_CAL)


def load_csv(name):
    with open(os.path.join(RES, name + ".csv")) as fh:
        r = list(csv.reader(fh))
    return r[0], np.array([[float(x) for x in row] for row in r[1:]])


GAIN_CAL = 1 / load_csv("s1_cal")[1][0, 0]
RES_THR = load_csv("s3_cal")[1][0, 0]
_, cut = load_csv("s3_cutoff")                     # cv_cut_v, f3db_hz
CUT_CV, CUT_F = cut[:, 0], cut[:, 1]
_, vg = load_csv("s4_vca_gain")                    # cv_vca_v, nominal dB, ...
VCA_CV, VCA_AMP = vg[:, 0], 10 ** ((vg[:, 1] - vg[-1, 1]) / 20)


def cv_cut(fc):
    return float(np.interp(np.log2(np.clip(fc, CUT_F[0], CUT_F[-1])), np.log2(CUT_F), CUT_CV))


def cv_vca(a):
    """Inverse VCA law: linear amplitude 0..1 -> CV."""
    return 0.0 if a <= 1e-4 else float(np.interp(a, VCA_AMP, VCA_CV))


def adsr(t, t_on, t_off, a, d, s, r):
    if t < t_on:
        return 0.0
    if t_off is None or t < t_off:
        x = t - t_on
        return x / a if x < a else s + (1 - s) * np.exp(-(x - a) / d)
    lvl = adsr(t_off - 1e-9, t_on, None, a, d, s, r)
    return lvl * np.exp(-(t - t_off) / r)


# ---- score ---------------------------------------------------------------------------
def mtof(m):
    return 440 * 2 ** ((m - 69) / 12)


# (start, dur, midi, waves) ; part 1: bass line with filter envelope; part 2: held note + resonant sweep
NOTES = [(0.00 + i * 0.25, 0.20, m, ("saw", "sub")) for i, m in enumerate([45, 48, 52, 57, 55, 52, 50, 48])]
NOTES += [(2.05, 1.85, 33, ("saw", "pulse"))]
T_END = 4.0


def firmware():
    """Return PWL lists for all MCU-driven nodes."""
    reset, pulse, sub = [(0, 5.0)], [(0, 0.0)], [(0, 0.0)]
    starts = [n[0] for n in NOTES]
    k = 0
    for i, (t0, dur, m, waves) in enumerate(NOTES):
        f = mtof(m)
        psc = 1 if 48e6 / f < 65536 else int(np.ceil(48e6 / f / 65536))
        arr = round(48e6 / psc / f)
        T = psc * arr / 48e6                        # quantised period
        t_end = starts[i + 1] if i + 1 < len(starts) else T_END   # mono: the next note takes over the timer
        t = t0 + 1e-3
        while t + T < t_end:
            reset += [(t, 5.0), (t + 5e-9, 0.0), (t + TP_RESET, 0.0), (t + TP_RESET + 5e-9, 5.0)]
            if "pulse" in waves:
                pw = 0.5 - 0.35 * np.sin(2 * np.pi * 0.7 * (t - t0))   # firmware LFO on pulse width
                pulse += [(t, 0.0), (t + 5e-9, 5.0), (t + pw * T, 5.0), (t + pw * T + 5e-9, 0.0)]
            lvl = (5.0 if k % 2 == 0 else 0.0) if "sub" in waves else 0.0
            sub += [(t, sub[-1][1]), (t + 5e-9, lvl)]
            t += T
            k += 1
    # control-rate CVs
    ts = np.arange(0, T_END, T_CV)
    amp, cutv, resv, vcav = [], [], [], []
    for t in ts:
        active = [n for n in NOTES if n[0] <= t < n[0] + n[1] + 0.25]
        n = active[-1] if active else NOTES[0]
        t0, dur, m, waves = n
        amp.append(cv_amp(mtof(m)))
        if t < 2.0:
            fenv = adsr(t, t0, t0 + dur, 0.002, 0.08, 0.0, 0.05)
            fc = 180 * 2 ** (5.0 * fenv)
            res = 0.85 * RES_THR
            aenv = adsr(t, t0, t0 + dur, 0.003, 0.15, 0.6, 0.04)
        else:
            x = (t - 2.05) / 1.85
            fc = 60 * 2 ** (7 * np.sin(np.pi * np.clip(x, 0, 1)))         # slow sweep up and down
            res = 0.97 * RES_THR
            aenv = adsr(t, t0, t0 + dur, 0.01, 0.3, 0.9, 0.08)
        cutv.append(cv_cut(fc)); resv.append(res); vcav.append(cv_vca(0.9 * aenv))
    return reset, pulse, sub, ts, amp, cutv, resv, vcav


def pwl(name, node, pts):
    clean = []
    for t, v in sorted(pts, key=lambda p: p[0]):
        if clean and t <= clean[-1][0] + 1e-10:
            continue
        clean.append((t, v))
    pts = clean
    body = " ".join(f"{t:.9g} {v:.6g}" for t, v in pts)
    # wrap long lines for ngspice
    toks, lines, cur = body.split(" "), [], []
    for i in range(0, len(toks), 2):
        cur += toks[i:i + 2]
        if len(cur) >= 16:
            lines.append("+ " + " ".join(cur)); cur = []
    if cur:
        lines.append("+ " + " ".join(cur))
    return f"{name} {node} 0 PWL(\n" + "\n".join(lines) + "\n+ )\n"


def netlist():
    reset, pulse, sub, ts, amp, cutv, resv, vcav = firmware()
    stairs = lambda vals: [p for t, v in zip(ts, vals) for p in ((t, v), (t + T_CV - 1e-6, v))]
    n = f"""* S6 full voice
{spice.PREAMBLE}
VPLUS vp 0 9.6
V5 v5 0 5
VREF vref 0 4.5
VBIAS vbias 0 1.5
V25 v25 0 2.5
{voice.BIAS}
* ---- DCO ----
{voice.CVNET_LIN.format(n='A', src='cva', x='xamp')}
XUA xamp veA vp 0 uoA LM324
RBA uoA bqA 1k
QVA n bqA veA MMBT3904
REA veA 0 33k
XDCO vref n vp 0 saw TL072
CI saw n 10n
MRST saw g n 2N7002
RGS gd g 2.2k
RGP vp gd 10k
QLS gd b2 0 MMBT3904
RLSB mcu b2 4.7k
* ---- filter ----
{voice.CVNET_EXP.format(n='C', src='cvc')}
{voice.EXPO.format(cvcut='bC')}
{voice.LADDER.format(clad='33n')}
{voice.MIXER.format(saw='saw', pulse='pls', sub='sub', noise='noi')}
VNOI noi 0 0
{voice.CVNET_LIN.format(n='R', src='cvr', x='xres')}
{voice.VI.format(n='R', x='xres', col='rtail', re='6.2k')}
{voice.RESVCA.format(fbneg='rc1', fbpos='rc2', rfb='22k')}
* ---- VCA + loopback to PD5 ----
{voice.CVNET_LIN.format(n='V', src='cvv', x='xvv')}
{voice.VCA.format(inp='lpf', vbe_off=0, rc2='4.7k', n='V', x='xvv', rg='22k')}
VTR vdac 0 2.025
RDAC vdac vtrim 100k
RLB1 vcaout adca 10k
RLB2 adca 0 15k
CLB adca 0 1n
* ---- MCU / firmware stimulus ----
{pwl('VMCU', 'mcu', reset)}{pwl('VPLS', 'pls', pulse)}{pwl('VSUB', 'sub', sub)}
{pwl('VCVA', 'cva', stairs(amp))}{pwl('VCVC', 'cvc', stairs(cutv))}{pwl('VCVR', 'cvr', stairs(resv))}{pwl('VCVV', 'cvv', stairs(vcav))}
{spice.CTRL_HEAD}
option reltol=2e-3
tran 10u {T_END} 0 10u
linearize v(lineout) v(saw) v(lpf) v(adca) v(xvv) v(bC)
wrdata {{OUT}}/voice.dat v(lineout) v(saw) v(lpf) v(adca) v(xvv) v(bC)
.endc
.end
"""
    return n


def main():
    os.makedirs(OUT, exist_ok=True)
    if not os.environ.get("PLOT_ONLY"):
        spice.run(netlist(), OUT, "voice", timeout=7200)
    d = spice.load(os.path.join(OUT, "voice.dat"))
    t = d["time"]
    tw = np.arange(0, T_END, 1 / FS_WAV)
    y = np.interp(tw, t, d["v(lineout)"])
    y -= np.mean(y[tw > 0.05])
    peak = np.max(np.abs(y[tw > 0.02]))
    y[tw < 0.02] *= np.linspace(0, 1, np.sum(tw < 0.02))      # hide the power-on settling
    pcm = np.int16(np.clip(y / peak * 0.89, -1, 1) * 32767)
    wavpath = os.path.join(ROOT, "docs", "audio", "s6_voice.wav")
    os.makedirs(os.path.dirname(wavpath), exist_ok=True)
    with wave.open(wavpath, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS_WAV); w.writeframes(pcm.tobytes())
    adc = d["v(adca)"]
    print(f"line out peak {peak:.2f} V ({2*peak:.2f} Vpp); loopback ADC node range {adc[t>0.05].min():.2f} .. "
          f"{adc[t>0.05].max():.2f} V (must stay within 0..5 V)")
    print("WAV:", wavpath)

    # figure: (a) overview, (b) spectrogram, (c) detail of one note
    import matplotlib.pyplot as plt
    f, ax = plt.subplots(3, 1, figsize=(ps.FULL, 6.2), gridspec_kw=dict(height_ratios=[1, 1.2, 1]))
    ax[0].plot(t, d["v(lineout)"], color=ps.C[0], lw=0.4)
    ax[0].set(xlabel="$t$ [s]", ylabel="line out [V]", xlim=(0, T_END))
    from scipy.signal import spectrogram
    fq, tt, S = spectrogram(y, FS_WAV, nperseg=2048, noverlap=1536)
    ax[1].pcolormesh(tt, fq, 10 * np.log10(S + 1e-12), shading="auto", cmap="magma", vmin=-110, vmax=-40,
                     rasterized=True)
    ax[1].set(xlabel="$t$ [s]", ylabel="$f$ [Hz]", ylim=(0, 6000)); ax[1].grid(False)
    sel = (t > 0.75) & (t < 0.80)
    ax[2].plot((t[sel] - 0.75) * 1e3, d["v(saw)"][sel] - 5.5, color=ps.C[6], lw=0.7, label="DCO saw (offset)")
    ax[2].plot((t[sel] - 0.75) * 1e3, d["v(lpf)"][sel] - 4.5, color=ps.C[1], label="VCF out")
    ax[2].plot((t[sel] - 0.75) * 1e3, d["v(lineout)"][sel], color=ps.C[0], label="line out")
    ax[2].set(xlabel="$t$ [ms] (from 0.75 s)", ylabel="[V]")
    ax[2].legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3)
    for i, a in enumerate(ax):
        a.text(-0.08, 1.0, f"({chr(97 + i)})", transform=a.transAxes, fontsize=9, va="bottom")
    f.tight_layout()
    ps.save(f, "s6_voice")
    ps.save_csv("s6_voice", ["line_out_peak_v", "adc_loop_min_v", "adc_loop_max_v"],
                [[peak, adc[t > 0.05].min(), adc[t > 0.05].max()]])


if __name__ == "__main__":
    main()
