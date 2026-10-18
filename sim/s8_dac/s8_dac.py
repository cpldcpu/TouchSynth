"""S8 - pulse output as a PWM audio DAC: the encoded pulse pin (8-bit duty, 15.625 kHz samples, first-order noise
shaping) through the real mixer (470k into 10k, 1 uF coupling), ladder, VCA and line out; the saw is parked (DCO
held in reset). A 1 kHz test sine at -3 dBFS, cutoff 20 kHz and 5 kHz, for these sources (VARIANTS):
  edge_zoh    TIM2 edge-aligned at 187.5 kHz, each sample held for 12 periods (the first firmware version)
  center_zoh  TIM2 centre-aligned at 93.75 kHz (symmetric pulses), each sample held for 6 periods
  center_lin  centre-aligned, linear interpolation from the previous sample over the 6 periods (the firmware)
  ideal       the pulse node carries the continuous signal 5 V * duty, linear between samples (an ideal DAC)
Checks: level vs. ideal, harmonics, carrier residue, the first sampling image (FS_DAC - 1 kHz) and the noise in
20 Hz - 20 kHz without the tone, harmonics and images. Results: docs/results/s8_dac.csv.
"""
import os, sys, csv
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "lib"), os.path.join(HERE, "..", "s6_voice")]
import spice                                              # noqa: E402
import voice                                              # noqa: E402
import s6_voice as S6                                     # noqa: E402

OUT = os.path.join(HERE, "out")
RES = os.path.join(HERE, "..", "..", "docs", "results")
F_TIM, ARR = 48e6, 256                                    # 8-bit PWM
FS_DAC = 15625.0                                          # sample rate (as the firmware)
T_END, T_SKIP = 0.02, 0.008
F_SIG, A_SIG = 1000.0, 0.7                                # sine at 0.7 of full scale (-3 dBFS)
# PWM variants: carrier, periods per sample, pulse shape, sample interpolation
VARIANTS = {
    "edge_zoh":   dict(f_car=F_TIM / ARR, ups=12, center=False, interp=False),       # firmware until 2026-10-18
    "center_zoh": dict(f_car=F_TIM / (2 * ARR), ups=6, center=True, interp=False),   # symmetric pulses only
    "center_lin": dict(f_car=F_TIM / (2 * ARR), ups=6, center=True, interp=True),    # symmetric + interpolation
}


def encode(x, ups, interp):
    """Samples in -1...1 at FS_DAC -> duty codes 0...255 per carrier period: held (zero-order) or linearly
    interpolated from the previous sample over `ups` periods, with first-order error feedback (noise shaping)
    so the time average follows the target with sub-LSB accuracy."""
    c = (np.asarray(x) + 1) / 2 * (ARR - 1)
    if interp:
        prev = np.concatenate([[c[0]], c[:-1]])
        v = (prev[:, None] + (c - prev)[:, None] * (np.arange(1, ups + 1) / ups)[None, :]).ravel()
    else:
        v = np.repeat(c, ups)
    out, err = np.empty(len(v), int), 0.0
    for i, s_ in enumerate(v):
        q = int(min(ARR - 1, max(0, round(s_ + err))))
        err += s_ - q
        out[i] = q
    return out


def stimulus():
    n = int(T_END * FS_DAC)
    x = A_SIG * np.sin(2 * np.pi * F_SIG * np.arange(n) / FS_DAC)
    pts = {}
    for name, v in VARIANTS.items():
        T = 1 / v["f_car"]
        pwm = [(0.0, 2.5)]                                # start at the mean: no coupling-capacitor transient
        for i, c in enumerate(encode(x, v["ups"], v["interp"])):
            t = 1e-6 + i * T
            if c == 0:
                pwm += [(t, 0.0)]
                continue
            a_, b_ = ((T - c / ARR * T) / 2, (T + c / ARR * T) / 2) if v["center"] else (0.0, c / ARR * T)
            pwm += [(t + a_, 0.0), (t + a_ + 5e-9, 5.0), (t + b_, 5.0), (t + b_ + 5e-9, 0.0)]
        pts[name] = pwm
    pts["ideal"] = [(0.0, 2.5)] + [(1e-6 + i / FS_DAC, 5.0 * (c + 0.5) / ARR)
                                   for i, c in enumerate(np.round((x + 1) / 2 * (ARR - 1)).astype(int))]
    return pts


def netlist(pulse_pts, name, fc):
    s = S6.pwl
    return f"""* S8 PWM DAC on the pulse input ({name})
{spice.PREAMBLE}
VPLUS vp 0 9.6
V5 v5 0 5
VREF vref 0 4.5
VBIAS vbias 0 1.5
V25 v25 0 2.5
{voice.BIAS}
* ---- DCO parked: integrator held in reset (active-low reset input at 0 V) ----
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
VMCU mcu 0 0
VCVA cva 0 0
* ---- filter ----
{voice.CVNET_EXP.format(n='C', src='cvc')}
{voice.EXPO.format(cvcut='bC')}
{voice.LADDER.format(clad='33n')}
{voice.MIXER.format(saw='saw', pulse='pls', sub='sub', noise='noi')}
VNOI noi 0 0
VSUB sub 0 0
{voice.CVNET_LIN.format(n='R', src='cvr', x='xres')}
{voice.VI.format(n='R', x='xres', col='rtail', re='6.2k')}
{voice.RESVCA.format(fbneg='rc1', fbpos='rc2', rfb='22k')}
VCVR cvr 0 0
* ---- VCA ----
{voice.CVNET_LIN.format(n='V', src='cvv', x='xvv')}
{voice.VCA.format(inp='lpf', vbe_off=0, rc2='4.7k', n='V', x='xvv', rg='22k')}
VTR vdac 0 2.025
RDAC vdac vtrim 100k
VCVC cvc 0 {S6.cv_cut(fc):.4f}
VCVV cvv 0 {S6.cv_vca(0.9):.4f}
{s('VPLS', 'pls', pulse_pts)}
{spice.CTRL_HEAD}
option reltol=1e-3
tran 2u {T_END} 0 100n
linearize v(lineout)
wrdata {{OUT}}/{name}.dat v(lineout)
.endc
.end
"""


def analyse(t, y, f_car):
    m = t > T_SKIP
    t, y = t[m], y[m] - np.mean(y[m])
    n = len(y)
    X = np.abs(np.fft.rfft(y * np.hanning(n))) / (n / 4)
    f = np.fft.rfftfreq(n, t[1] - t[0])
    lvl = lambda f0, bw=150: X[(f > f0 - bw) & (f < f0 + bw)].max()
    fund = lvl(F_SIG)
    harm = [20 * np.log10(lvl(k * F_SIG) / fund) for k in range(2, 6)]
    thd = 10 * np.log10(sum(10 ** (h / 10) for h in harm))
    car = 20 * np.log10(max(lvl(f_car, 2000), 1e-12) / fund)
    img = 20 * np.log10(lvl(FS_DAC - F_SIG) / fund)          # first sampling image of the test tone
    excl = [F_SIG] + [k * F_SIG for k in range(2, 6)] + [FS_DAC - F_SIG, FS_DAC + F_SIG]
    band = (f > 20) & (f < 20000) & np.all([np.abs(f - x) > 300 for x in excl], 0)
    noise = 10 * np.log10(np.sum(X[band] ** 2) / 1.5 / fund ** 2 + 1e-30)
    return dict(fund_mv=fund * 1e3, h2=harm[0], h3=harm[1], thd=thd, carrier=car, image=img, noise=noise)


def main():
    pts = stimulus()
    rows = []
    for fc in (20000.0, 5000.0):
        res = {}
        for name, p_ in pts.items():
            tag = f"{name}_{int(fc)}"
            if not os.path.exists(os.path.join(OUT, tag + ".dat")):      # existing runs are reused
                spice.run(netlist(p_, tag, fc), OUT, tag, timeout=7200)
            d = spice.load(os.path.join(OUT, tag + ".dat"))
            res[name] = analyse(d["time"], d["v(lineout)"], VARIANTS.get(name, VARIANTS["edge_zoh"])["f_car"])
            r = res[name]
            print(f"fc {fc:5.0f} Hz {name:10s}: 1 kHz at {r['fund_mv']:6.1f} mV, H2 {r['h2']:6.1f} dB, H3 {r['h3']:6.1f} dB,"
                  f" THD {r['thd']:6.1f} dB, carrier {r['carrier']:6.1f} dB, image {r['image']:6.1f} dB,"
                  f" noise 20 Hz-20 kHz (without images) {r['noise']:6.1f} dB")
            rows.append([fc, name] + [round(v, 2) for v in r.values()])
    with open(os.path.join(RES, "s8_dac.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fc_hz", "source", "fund_mv", "h2_db", "h3_db", "thd_db", "carrier_db", "image_db", "noise_db"])
        w.writerows(rows)


if __name__ == "__main__":
    main()
