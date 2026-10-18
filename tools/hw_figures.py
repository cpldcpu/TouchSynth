#!/usr/bin/env python3
"""Board 1 bring-up figures: measured results (docs/results/hw_board1_*.csv and raw captures in
docs/results/hw_board1/, written by tools/hwtest.py) next to the simulation references (docs/results/s*.csv).

  python hw_figures.py [board]          default board1; writes docs/figures/hw_<board>_*.pdf/.png

Figures (same style as the simulation figures, sim/lib/plotstyle.py):
  hw_<board>_dco   T4/T5: pitch error and saw amplitude vs note (S1)
  hw_<board>_vcf   T7/T6/T8: self-oscillation tracking (S3), resonance threshold, low-pass harmonics
  hw_<board>_vca   T9/T10/T11: gain law (S4), thump vs trim code, CV step settling (S2)
  hw_<board>_hum   T12: spectrum at VCAOUT, VCA open and closed (S7)
Loopback scaling as in hwtest.py: PD5 = 0.6 x VCAOUT, 12-bit ADC referenced to +5V (5.028 V on board 1).
"""
import os, re, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "sim", "lib"))
import plotstyle as ps                                    # noqa: E402  (sets the rcParams)

BOARD = sys.argv[1] if len(sys.argv) > 1 else "board1"
RES = os.path.join(ROOT, "docs", "results")
RAW = os.path.join(RES, f"hw_{BOARD}")
VDD, FS, LB = 5.028, 4095, 0.6
LSB = VDD / FS / LB                                       # V at VCAOUT per ADC count (2.05 mV)
REF = 1.33 / 2                                            # 1.33 Vpp nominal output, peak (S7 / T12 reference)


def csv(name):
    return np.genfromtxt(os.path.join(RES, name + ".csv"), delimiter=",", names=True)


def raw(name):
    """Raw loopback capture: (sample period in s, VCAOUT in V)."""
    path = os.path.join(RAW, name + ".csv")
    us = int(re.search(r"period (\d+) us", open(path, encoding="utf-8").readline()).group(1))
    return us * 1e-6, np.loadtxt(path) * LSB


def note_ticks(ax, lo, hi):
    ns = [n for n in range(lo, hi + 1) if n % 12 == 0]
    ax.set_xticks(ns)
    ax.set_xticklabels([f"C{n // 12 - 1}" for n in ns])


# ---------------------------------------------------------------------------------------------------- DCO
def fig_dco():
    d, s = csv(f"hw_{BOARD}_dco"), csv("s1_dco")
    f, ax = ps.fig(2, 1, aspect=0.66)
    ax[0].axhspan(-1, 1, color=ps.C[2], alpha=0.08, lw=0)
    ax[0].plot(d["midi"], d["cents"], "o-", color=ps.C[0], label="board 1")
    for y in (-1, 1):
        ax[0].axhline(y, color=ps.C[6], lw=0.6, ls="--")
    ax[0].set(xlabel="note", ylabel="pitch error [cent]", ylim=(-1.3, 1.3))
    ax[0].text(0.03, 0.84, "limit $\\pm$1 cent", transform=ax[0].transAxes, fontsize=7, va="top")
    note_ticks(ax[0], 24, 108)
    a = d["saw_vpp_vcaout"]
    ax[1].axhspan(-5, 5, color=ps.C[2], alpha=0.08, lw=0)
    ax[1].plot(d["midi"], 100 * (a / a.mean() - 1), "o-", color=ps.C[0], label="board 1 (VCAOUT, no cal.)")
    for k, ls, lab in (("amp_8v6", "--", "S1, 8.6 V"), ("amp_11v6", ":", "S1, 11.6 V")):
        ax[1].plot(s["midi"], 100 * (s[k] / s[k].mean() - 1), ls, color=ps.C[1], label=lab)
    for y in (-5, 5):
        ax[1].axhline(y, color=ps.C[6], lw=0.6, ls="--")
    ax[1].set(xlabel="note", ylabel="saw ampl. re mean [%]", ylim=(-13, 6))
    note_ticks(ax[1], 24, 108)
    ax[1].legend(loc="lower center", fontsize=6.5)
    ps.label_panels(ax)
    f.tight_layout()
    ps.save(f, f"hw_{BOARD}_dco")
    print(f"dco: pitch {d['cents'].min():+.2f} ... {d['cents'].max():+.2f} cent; saw {a.mean() * 1e3:.0f} mVpp, "
          f"{100 * (a.min() / a.mean() - 1):+.2f} / {100 * (a.max() / a.mean() - 1):+.2f} %")


# ---------------------------------------------------------------------------------------------------- VCF
def fig_vcf():
    t, r, h = csv(f"hw_{BOARD}_vcf_track"), csv(f"hw_{BOARD}_vcf_res"), csv(f"hw_{BOARD}_lpf_harmonics")
    s3, so = csv("s3_cutoff"), csv("s3_selfosc")
    f, ax = ps.fig(3, 1, aspect=1.05)

    # (a) T7: self-oscillation frequency vs CV_CUT (duplicate codes averaged in log frequency)
    cv = np.unique(t["cv_cut_v"])
    fq = np.array([2 ** np.mean(np.log2(t["f_hz"][t["cv_cut_v"] == c])) for c in cv])
    k, b = np.polyfit(cv, np.log2(fq), 1)
    dev = 1200 * (np.log2(fq) - (k * cv + b))
    x = np.linspace(0, 5, 50)
    ax[0].semilogy(x, 2 ** (k * x + b), "-", color=ps.C[0], lw=0.7, alpha=0.6)
    ax[0].semilogy(cv, fq, "o", color=ps.C[0], label=f"board 1 self-osc.\n({k:.2f} oct/V)")
    ax[0].semilogy(s3["cv_cut_v"], s3["f3db_hz"], "--", color=ps.C[1], label="S3 $-$3 dB cutoff\n(2.05 oct/V)")
    fso = so["f_hz"][np.argmin(np.abs(so["cv_res_v"] - 3.2))]
    ax[0].semilogy([2.5], [fso], "*", color=ps.C[1], ms=7, label="S3 self-osc. at 2.5 V")
    ax[0].set(xlabel=r"$CV_\mathrm{CUT}$ [V]", ylabel="frequency [Hz]", xlim=(0, 5), ylim=(15, 3e5))
    ax[0].legend(loc="upper left", fontsize=6.5)

    # (b) T6: oscillation amplitude vs CV_RES at the 1 kHz cutoff code
    ax[1].axvspan(2.7, 3.5, color=ps.C[2], alpha=0.08, lw=0)
    ax[1].plot(r["cv_res_v"], r["vcaout_rms_v"] * 1e3, "o-", color=ps.C[0], label="board 1")
    ax[1].axvline(3.1, color=ps.C[1], lw=0.8, ls="--", label="S3 threshold 3.1 V")
    ax[1].set(xlabel=r"$CV_\mathrm{RES}$ [V]", ylabel="VCAOUT [mV rms]", ylim=(0, 220))
    ax[1].text(3.1, 30, "limit", fontsize=7, ha="center")
    ax[1].legend(loc="center left", fontsize=6.5)

    # (c) T8: response at the harmonics of a 110 Hz saw (filtered / open filter), 4-pole fit
    fh = h["f_hz"]
    resp = h["response_db"] - h["response_db"][0]
    cand = np.linspace(500, 5000, 4501)                    # same fit as hwtest.test_lpf (harmonics 1-12)
    m4 = lambda fp, fr: -40 * np.log10(1 + (fr / fp) ** 2) + 40 * np.log10(1 + (fh[0] / fp) ** 2)
    fp = cand[int(np.argmin([np.sum((resp[:12] - m4(p, fh[:12])) ** 2) for p in cand]))]
    xf = np.linspace(fh[0], fh[-1], 200)
    ax[2].plot(fh, resp, "o", color=ps.C[0], label="board 1")
    ax[2].plot(xf, m4(fp, xf), "-", color=ps.C[1], label=f"4-pole, $f_p$ = {fp:.0f} Hz")
    ax[2].plot(fh[9], resp[9], "s", mfc="none", mec=ps.C[6], ms=6, label="harmonic 10")
    ax[2].set(xlabel="frequency [Hz]", ylabel="re harmonic 1 [dB]", ylim=(-16, 5))
    ax[2].legend(loc="lower left", fontsize=6.5)
    ps.label_panels(ax)
    f.tight_layout()
    ps.save(f, f"hw_{BOARD}_vcf")
    on = r["cv_res_v"][r["vcaout_rms_v"] > 0.05]
    off = r["cv_res_v"][r["vcaout_rms_v"] <= 0.05]
    print(f"vcf: tracking {k:.3f} oct/V over {cv.min():.2f}..{cv.max():.2f} V ({fq.min():.0f}..{fq.max():.0f} Hz), "
          f"max dev {np.abs(dev).max():.0f} cent; threshold between {off.max():.2f} and {on.min():.2f} V; "
          f"T8 fp {fp:.0f} Hz, harmonic 10 {resp[9]:+.1f} dB (fit {m4(fp, fh[9]):+.1f})")


# ---------------------------------------------------------------------------------------------------- VCA
def trim_steps():
    """(trim code, closed, open) ADC means from the trim walk / fine logs ('adc 5 mean' after 'cv vca 0/4095')."""
    out = {}
    for name in ("trim_walk", "trim_fine"):
        trim = vca = None
        for line in open(os.path.join(RAW, name + ".txt"), encoding="utf-8"):
            m = re.match(r"> trim (\d+)", line)
            if m:
                trim = int(m.group(1))
            m = re.match(r"> cv vca (\d+)", line)
            if m:
                vca = int(m.group(1))
            m = re.match(r"adc 5 mean (\d+)", line)
            if m and vca in (0, 4095):
                out.setdefault(trim, {0: [], 4095: []})[vca].append(int(m.group(1)))
    codes = sorted(out)
    return (np.array(codes), np.array([np.mean(out[c][0]) for c in codes]),
            np.array([np.mean(out[c][4095]) for c in codes]))


def dc_step(name):
    """CV_VCA DC step (trim 255, no signal): t [ms], 9-sample smoothed VCAOUT, initial, final value."""
    ts, v = raw(name)
    s = np.convolve(v, np.ones(9) / 9, mode="same")
    t = np.arange(len(v)) * ts * 1e3
    ini, fin = v[:3].mean(), v[-400:].mean()
    return t[5:-5], s[5:-5], ini, fin


def fig_vca():
    g, s4 = csv(f"hw_{BOARD}_vca_gain"), csv("s4_vca_gain")
    f, ax = ps.fig(2, 2, aspect=0.62)
    ax = ax.flatten()

    # (a) T9 gain law re full gain
    ax[0].plot(s4["cv_vca_v"], s4["nominal"] - s4["nominal"][-1], "--", color=ps.C[1], label="S4 (nominal)")
    ax[0].plot(g["cv_vca_v"], g["gain_re_full_db"], "o", color=ps.C[0], label="board 1, 1046 Hz saw")
    ax[0].annotate("measurement floor", (0, g["gain_re_full_db"][0]), (0.9, -62), fontsize=7,
                   arrowprops=dict(arrowstyle="-", lw=0.5))
    ax[0].set(xlabel=r"$CV_\mathrm{VCA}$ [V]", ylabel="gain re full [dB]", ylim=(-90, 5))
    ax[0].legend(loc="center right")

    # (b) T10 thump vs trim code (VCAOUT DC step closed -> open), T1 trim-DAC walk
    codes, closed, opened = trim_steps()
    step = (opened - closed) * LSB * 1e3
    ax[1].axhspan(-3, 3, color=ps.C[2], alpha=0.15, lw=0, label="limit $\\pm$3 mV")
    ax[1].plot(codes, step, "o-", color=ps.C[0], label="board 1")
    ax[1].axvline(104, color=ps.C[6], lw=0.6, ls=":")
    ax[1].text(110, -160, "cal. code 104", fontsize=7)
    ax[1].set(xlabel="trim DAC code", ylabel="VCA step [mV]", xlim=(-8, 263))
    ax[1].legend(loc="upper right")

    # (c), (d) T11: DC step through the VCA CV filter, opening and closing
    for i, (name, lab) in enumerate((("vca_dcstep_up", "opening (0 $\\to$ 5 V)"),
                                     ("vca_dcstep_down", "closing (5 $\\to$ 0 V)"))):
        t, s, ini, fin = dc_step(name)
        ax[2].plot(t, (s - ini) / (fin - ini), color=ps.C[i], label=lab)
        ax[3].plot(t, 100 * (s - fin) / abs(fin - ini) * np.sign(ini - fin), color=ps.C[i], lw=0.9, label=lab)
    for a in (ax[2], ax[3]):
        a.axvline(1.3, color=ps.C[6], lw=0.6, ls="--")
    ax[2].text(1.4, 0.6, "S2: 1 % in 1.3 ms", fontsize=7)
    ax[2].set(xlabel="$t$ [ms]", ylabel="normalised step", xlim=(0, 5), ylim=(-0.05, 1.1))
    ax[2].legend(loc="lower right")
    ax[3].axhspan(-1, 1, color=ps.C[2], alpha=0.15, lw=0)
    ax[3].set(xlabel="$t$ [ms]", ylabel="remaining error [% of step]", xlim=(0, 20.5), ylim=(-2, 8))
    ax[3].legend(loc="upper right")
    ps.label_panels(ax)
    f.tight_layout()
    ps.save(f, f"hw_{BOARD}_vca")
    d = g["gain_re_full_db"] - g["sim_re_full_db"]
    m = g["cv_vca_v"] >= 0.25
    print(f"vca: gain law vs S4 (CV >= 0.25 V) {d[m].min():+.2f} ... {d[m].max():+.2f} dB; off {g['gain_re_full_db'][0]:.1f} dB; "
          f"VCA-open DC {opened[0]:.0f} (trim {codes[0]}) ... {opened[-1]:.0f} counts (trim {codes[-1]}), "
          f"span {(opened.max() - opened.min()) * LSB * 1e3:.0f} mV; thump at trim 128 "
          f"{step[codes == 128][0]:+.1f} mV, at 104 {step[codes == 104][0]:+.1f} mV")
    for name in ("vca_dcstep_up", "vca_dcstep_down"):
        t, s, ini, fin = dc_step(name)
        e = np.abs(s - fin) / abs(fin - ini)
        out = np.where(e > 0.01)[0]
        e2 = np.where(e > 0.02)[0]
        print(f"  {name}: step {(fin - ini) * 1e3:+.1f} mV, 1 % after {t[out[-1]]:.2f} ms, 2 % after {t[e2[-1]]:.2f} ms")


# ---------------------------------------------------------------------------------------------------- hum
def spectrum(name):
    ts, v = raw(name)
    w = np.hanning(len(v))
    sp = np.abs(np.fft.rfft((v - v.mean()) * w)) * 2 / w.sum()
    return np.fft.rfftfreq(len(v), ts), sp, np.std(v)


def fig_hum():
    s7 = csv("s7_power")
    f, ax = ps.fig(1, 1, aspect=0.36)
    fo, so, ro = spectrum("hum")
    fc, sc, rc = spectrum("noise_vca_closed")
    ax.semilogx(fc[1:], 20 * np.log10(sc[1:] / REF), color=ps.C[5], lw=0.7, label="VCA closed")
    ax.semilogx(fo[1:], 20 * np.log10(so[1:] / REF), color=ps.C[0], lw=0.8, label="VCA open, waveforms off")
    hum = s7["hum_db_re_nominal"][0]
    ax.plot([100], [hum], "*", color=ps.C[1], ms=7, label=f"S7 100 Hz hum ({hum:.0f} dB)")
    ax.hlines(hum + 6, 70, 140, color=ps.C[1], lw=0.8, ls="--", label="limit S7 + 6 dB")
    pk = lambda fr, sp, fc_: sp[max(0, np.argmin(np.abs(fr - fc_)) - 2):np.argmin(np.abs(fr - fc_)) + 3].max()
    for fr, txt in ((262, "DCO feed-through\n(262 Hz, waves off)"), (3125, "46.875 kHz\nalias")):
        k = np.argmin(np.abs(fo - fr))
        y = 20 * np.log10(so[max(0, k - 2):k + 3].max() / REF)
        ax.annotate(txt, (fo[k], y), (fo[k] * 1.25 if fr < 1000 else fo[k] / 2.6, y + 6), fontsize=6.5, va="bottom",
                    arrowprops=dict(arrowstyle="-", lw=0.5))
    ax.set(xlabel="frequency [Hz]", ylabel="dB re 1.33 V$_\\mathrm{pp}$", xlim=(5, 5000), ylim=(-140, -40))
    ax.legend(loc="lower left", ncol=2)
    f.tight_layout()
    ps.save(f, f"hw_{BOARD}_hum")
    _, _, rn = spectrum("noise_vca_open")
    db = lambda x: 20 * np.log10(x * np.sqrt(2) / REF)
    ex = np.sqrt(max(rn ** 2 - rc ** 2, 0))
    print(f"hum: 50 Hz {db(pk(fo, so, 50) / np.sqrt(2)):.1f} dB, 100 Hz {db(pk(fo, so, 100) / np.sqrt(2)):.1f} dB; rms "
          f"hum capture {ro * 1e3:.2f} mV ({db(ro):.1f} dB), open {rn * 1e3:.2f} mV ({db(rn):.1f} dB), closed "
          f"{rc * 1e3:.2f} mV ({db(rc):.1f} dB), open-closed {ex * 1e3:.2f} mV ({db(ex):.1f} dB), 0..5 kHz")
    for name, lines in (("hum", [261.6, 523.3, 784.9, 3125]), ("noise_vca_open", [1046.5, 2093, 3139.5, 4186, 3125]),
                        ("noise_vca_closed", [3125])):
        ts, v = raw(name)
        P = np.abs(np.fft.rfft(v - v.mean())) ** 2
        fr = np.fft.rfftfreq(len(v), ts)
        m = fr >= 20                                       # broadband: without DC/drift and the discrete lines
        for l in lines:
            m &= np.abs(fr - l) >= 15
        rb = np.sqrt(2 * P[m].sum() * len(P) / m.sum()) / len(v)
        print(f"  {name}: broadband (lines and < 20 Hz removed) {rb * 1e3:.2f} mV rms ({db(rb):.1f} dB)")


if __name__ == "__main__":
    fig_dco()
    fig_vcf()
    fig_vca()
    fig_hum()
