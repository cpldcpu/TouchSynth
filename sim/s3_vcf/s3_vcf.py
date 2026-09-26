"""S3 - 4-pole transistor ladder VCF with expo cutoff control and diff-pair resonance VCA."""
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import spice
import plotstyle as ps
import voice

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

CLAD = "33n"
RE_RES = "6.2k"
RC_RES = "10k"
FB_POL = os.environ.get("FBPOL", "a")
RFB = os.environ.get("RFB", "22k")
FBN, FBP = ("rc1", "rc2") if FB_POL == "a" else ("rc2", "rc1")

COMMON = """
VPLUS vp 0 {vp}
V5 v5 0 5
VREF vref 0 4.5
VBIAS vbias 0 1.5
V25 v25 0 2.5
VCUT cvc 0 {cvcut}
VRES cvr 0 {cvres}
RRX1 cvr xres 10k
RRX2 xres 0 15k
""" + voice.BIAS + voice.EXPO.format(cvcut="cvc") + voice.LADDER.format(clad=CLAD) \
    + voice.MIXER.format(saw="saw", pulse="pulse", sub="sub", noise="noise") \
    + voice.VI.format(n="R", x="xres", col="rtail", re=RE_RES) \
    + voice.RESVCA.format(fbneg=FBN, fbpos=FBP, rfb=RFB)

AC_NET = """* S3 AC cut={cvcut} res={cvres}
{PRE}
.temp {temp}
""" + COMMON + """
VSAW saw 0 DC 5.5 AC 1
VPUL pulse 0 2.5
VSUB sub 0 2.5
VNOI noise 0 2.5
{CTRL}
op
print i(VPLUS) v(tail) v(ee) v(n4a) v(n4b) v(lpf) v(oa) v(rtail) v(rc1) v(rc2) v(resout) v(veR)
ac dec 100 5 200k
wrdata {{OUT}}/{name}.dat vdb(lpf) vp(lpf) vdb(bin1)
.endc
.end
"""

TR_NET = """* S3 transient cut={cvcut} res={cvres}
{PRE}
""" + COMMON + """
VSAW saw 0 PULSE(4.5 6.5 0 {tr} 1u 0 {T})
VPUL pulse 0 2.5
VSUB sub 0 2.5
VNOI noise 0 PULSE(2.5 5 1m 100n 100n 20u 1)
{CTRL}
tran 2u {tstop} 0 2u
wrdata {{OUT}}/{name}.dat v(lpf) v(saw)
.endc
.end
"""


def ac(cvcut, cvres, vp=8.6, temp=25, tag=""):
    name = f"ac_c{cvcut}_r{cvres}_v{vp}_t{temp}{tag}".replace(".", "p")
    log = spice.run(AC_NET.format(PRE=spice.PREAMBLE, CTRL=spice.CTRL_HEAD, cvcut=cvcut, cvres=cvres, vp=vp,
                                  temp=temp, name=name), OUT, name)
    d = spice.load(os.path.join(OUT, name + ".dat"))
    return d["frequency"], d["vdb(lpf)"] - d["vdb(bin1)"], d["vp(lpf)"], log


def tran(cvcut, cvres, f=110, tstop=0.06, vp=8.6, tag=""):
    name = f"tr_c{cvcut}_r{cvres}{tag}".replace(".", "p")
    T = 1 / f
    spice.run(TR_NET.format(PRE=spice.PREAMBLE, CTRL=spice.CTRL_HEAD, cvcut=cvcut, cvres=cvres, vp=vp,
                            T=T, tr=T - 3e-6, tstop=tstop, name=name), OUT, name)
    d = spice.load(os.path.join(OUT, name + ".dat"))
    return d["time"], d["v(lpf)"], d["v(saw)"]


def f3db(f, db):
    """-3 dB point re the 20-40 Hz passband (or the lowest points if cutoff is lower), log-interpolated."""
    ref = db[:5].max() if f3db_guess(f, db) < 60 else db[(f > 20) & (f < 40)].mean()
    i = np.where((db < ref - 3) & (f > 8))[0]
    if not len(i):
        return np.nan
    k = i[0]
    x0, x1, y0, y1 = np.log10(f[k - 1]), np.log10(f[k]), db[k - 1], db[k]
    return 10 ** (x0 + (ref - 3 - y0) * (x1 - x0) / (y1 - y0))


def f3db_guess(f, db):
    i = np.where(db < db[:5].max() - 3)[0]
    return f[i[0]] if len(i) else np.inf


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    # --- cutoff sweep, resonance off -------------------------------------------
    cuts = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    sweep = {}
    for c in cuts:
        f, db, ph, log = ac(c, 0.0)
        sweep[c] = (f, db)
        # slope between 4x and 16x the -3 dB point
        fc = f3db(f, db)
        rows.append((c, fc, db[:5].mean()))
    print("CV_CUT  f-3dB   passband")
    for c, fc, pb in rows:
        print(f"{c:5.1f} {fc:9.1f} {pb:7.2f} dB")
    fcs = np.array([r[1] for r in rows])
    oct_per_v = np.polyfit(cuts[1:-1], np.log2(fcs[1:-1]), 1)[0]
    print("octaves / V:", oct_per_v)
    # slope check at mid cutoff
    f, db = sweep[2.5]
    fc = f3db(f, db)
    s = np.interp(np.log10(fc * 16), np.log10(f), db) - np.interp(np.log10(fc * 8), np.log10(f), db)
    print(f"slope one octave far above fc: {s:.1f} dB/oct")

    # --- resonance sweep at CV_CUT = 2.5 -------------------------------------------
    res_curves = {}
    for r in [0.0, 1.0, 2.0, 2.5, 2.8, 3.0]:
        f, db, ph, log = ac(2.5, r)
        res_curves[r] = (f, db)
        pk = db.max() - db[:5].mean()
        print(f"CV_RES {r}: peak {pk:.1f} dB at {f[np.argmax(db)]:.0f} Hz")

    # --- temperature drift of cutoff -------------------------------------------------
    f25 = f3db(*ac(2.5, 0.0, temp=25)[:2])
    f45 = f3db(*ac(2.5, 0.0, temp=45)[:2])
    drift = 1200 * np.log2(f45 / f25) / 20
    print(f"cutoff drift 25->45 C: {f25:.0f} -> {f45:.0f} Hz = {drift:.1f} cent/K")

    # --- supply dependence --------------------------------------------------------------
    f116 = f3db(*ac(2.5, 0.0, vp=11.6)[:2])
    print(f"cutoff at V+ 8.6: {f25:.0f} Hz, 11.6: {f116:.0f} Hz")

    np.savez(os.path.join(OUT, "s3_ac.npz"), cuts=cuts, fcs=fcs)
    ps.save_csv("s3_cutoff", ["cv_cut_v", "f3db_hz", "passband_db"], [list(r) for r in rows])

    # figures
    f_, ax = ps.fig(2, 1, aspect=0.75)
    for i, c in enumerate(cuts[::2]):
        ff, db = sweep[c]
        ax[0].semilogx(ff, db - sweep[cuts[-1]][1][:5].mean(), color=ps.C[i % 6], label=f"{c:.0f} V")
    ax[0].set(xlabel="$f$ [Hz]", ylabel="gain [dB] (re passband)", ylim=(-80, 10), xlim=(5, 2e5))
    ax[0].legend(title="$CV_\\mathrm{CUT}$", ncol=2, loc="lower left")
    for i, r in enumerate(sorted(res_curves)):
        ff, db = res_curves[r]
        ax[1].semilogx(ff, db - res_curves[0.0][1][:5].mean(), color=ps.C[i % 6], label=f"{r:.1f} V")
    ax[1].set(xlabel="$f$ [Hz]", ylabel="gain [dB] (re passband)", ylim=(-50, 30), xlim=(20, 5e4))
    ax[1].legend(title="$CV_\\mathrm{RES}$", ncol=2, loc="lower left")
    ps.label_panels(ax)
    f_.tight_layout()
    ps.save(f_, "s3_vcf_response")
    selfosc_and_waveforms()


def selfosc_and_waveforms():
    """Transient: kick the filter (noise pulse) at CV_CUT = 2.5 V, find the resonance threshold for
    sustained oscillation; then a 110 Hz saw through the filter at several settings."""
    osc = []
    for r in [2.8, 3.0, 3.2, 3.4, 3.6, 4.0, 4.5, 5.0]:
        t, v, _ = tran(2.5, r, f=1e-3, tstop=0.08, tag="_kick")   # saw frozen (period 1000 s)
        a1 = np.ptp(v[(t > 0.010) & (t < 0.015)])
        a2 = np.ptp(v[(t > 0.070) & (t < 0.080)])
        seg = v[t > 0.06]; tt = t[t > 0.06]
        zc = np.where(np.diff(np.sign(seg - seg.mean())) > 0)[0]
        fo = (len(zc) - 1) / (tt[zc[-1]] - tt[zc[0]]) if len(zc) > 2 else np.nan
        osc.append((r, a1, a2, fo, t, v))
        print(f"CV_RES {r}: amplitude 10 ms {a1*1e3:.1f} mVpp, 70 ms {a2*1e3:.1f} mVpp, f {fo:.0f} Hz")
    ps.save_csv("s3_selfosc", ["cv_res_v", "vpp_10ms", "vpp_70ms", "f_hz"], [list(o[:4]) for o in osc])

    waves = []
    for c, r in [(5.0, 0.0), (3.0, 0.0), (2.0, 0.0), (3.0, 3.0)]:
        t, v, saw = tran(c, r, f=110, tstop=0.05, tag="_saw")
        waves.append((c, r, t, v, saw))
    f_, ax = ps.fig(2, 1, aspect=0.75)
    for i, o in enumerate([o for o in osc if o[0] in (3.2, 3.6, 4.0, 5.0)]):
        r, a1, a2, fo, t, v = o
        sel = (t > 0.075) & (t < 0.0775)
        ax[0].plot((t[sel] - 0.075) * 1e3, v[sel] - v[sel].mean(), color=ps.C[i], label=f"{r:.1f} V")
    ax[0].set(xlabel="$t$ [ms] (after 75 ms)", ylabel=r"$V_\mathrm{LPF}$ (AC) [V]", ylim=(-0.25, 0.3))
    ax[0].legend(title=r"$CV_\mathrm{RES}$", loc="lower right", ncol=2)
    for i, (c, r, t, v, saw) in enumerate(waves):
        sel = (t > 0.03) & (t < 0.03 + 2 / 110)
        ax[1].plot((t[sel] - 0.03) * 1e3, v[sel] - 4.5, color=ps.C[i], label=f"{c:.0f} V / {r:.0f} V")
    ax[1].set(xlabel="$t$ [ms]", ylabel=r"$V_\mathrm{LPF}-V_\mathrm{REF}$ [V]")
    ax[1].legend(title=r"$CV_\mathrm{CUT}$ / $CV_\mathrm{RES}$", loc="lower left", fontsize=7)
    ps.label_panels(ax)
    f_.tight_layout()
    ps.save(f_, "s3_vcf_transient")


if __name__ == "__main__":
    main()
