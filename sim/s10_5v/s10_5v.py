"""S10 - the analog voice on a single 5 V supply (design study for the poly voice module, DAC-only).

Two variants of the same voice core (CV networks, expo converter, ladder + INA, resonance VCA, main VCA,
line out), run through the same tests:
  v12   rev 0.1 at the minimum rail V+ = 8.6 V (9 V input minus the SS14), TL072, VREF 4.5 V, bias chain
        2k2 / 4 x 1k / 2k4 (stage spacing ~1 V)
  v5    single 5 V: rail-to-rail MCP6002 (behavioural model: GBW 1 MHz, 0.6 V/us, 28 nV/rtHz) for all TL072
        positions, VREF 2.5 V (divider + buffer from the 5 V), bias chain 1k2 / 4 x 1k2 / 3k9 (VB0 1.97 V,
        spacing 0.6 V), V->I converters scaled to the lower node voltages (same tail currents):
        resonance R4 15k -> 5k6, R_E 6k2 -> 3k6; VCA R4 15k -> 3k9, R_E 4k7 -> 2k2
  v5r   v5 with clean references and a regulated MCU supply: VREF 2.5 V from a CJ431 shunt reference (fed by
        1k from the 5 V, ripple ~ Z_out / 1k = -74 dB) and buffered; V25 1.25 V and VBIAS 1.0 V (buffered: the
        CV current into the expo divider would otherwise shift it) divided from VREF (expo reference current and the VCA anti-offset current from VREF, not the rail); the MCU on a
        3.3 V LDO, so the PWM CVs (and the DAC) span 0...3.3 V: expo divider 33k -> 18k, LIN dividers
        R4 12k (resonance) and 7k5 (VCA); bias chain 620 / 4 x 1k5 / 3k3 (VB0 1.66 V, spacing 0.76 V: the
        rungs keep ~0.1 V of reverse V_CB; at 0.6 V they touch saturation and distort), which VBIAS 1.0 V allows
        (expo emitter ~0.4 V); ladder capacitors 33n -> 10n with RREF 470k (the same cutoffs at 1/3.3 of the
        tail current, so the expo op-amp keeps room at the top); analog rail through 10 R + 220 uF.
  v5m   v5r with Microchip's MCP6001/2/4 macromodel (REV G) for all MCP6002 positions, incl. its noise model.
        Licensed for use with Microchip parts, so not in the repository: unzip MCP6001_MM_G.zip (microchip.com,
        MCP6002, simulation models) to temp/mcp6001_model/; runs in PSpice compatibility mode (out/mcp).
        Without it, v5m is skipped. The model has one NMOS input pair: no input crossover, no distortion detail.
CV values below are fractions of the PWM full scale (5 V, or 3.3 V for v5r and v5m).
Tests: DC headroom (worst V_CE per transistor over the CV corners), cutoff vs CV_CUT, resonance peaks and the
self-oscillation threshold, THD vs drive at the line out, output noise (op-amps as behavioural models with their
input noise as a series resistor, in both variants), supply rejection, supply current.

  python s10_5v.py            results: docs/results/s10_5v.csv, docs/figures/s10_5v.(pdf|png)
"""
import os, re, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import spice                                              # noqa: E402
import plotstyle as ps                                    # noqa: E402
import voice                                              # noqa: E402

OUT = os.path.join(HERE, "out")
OUT_M = os.path.join(OUT, "mcp")                           # PSpice compatibility mode for the vendor model
MCP_LIB = os.path.join(HERE, "..", "..", "temp", "mcp6001_model", "MCP6001.txt")
KT4 = 4 * 1.380649e-23 * 300


def rn(en):
    """Series resistor with the thermal noise of an op-amp's input voltage noise en [V/rtHz]."""
    return en ** 2 / KT4


# behavioural op-amp: transconductance with slew limit into an integrator (GBW, SR), DC gain 1e5, output within
# 20 mV of the rails, integrator clamped near the rails (no wind-up); noiseless (the noise is added outside)
OPB = """
.subckt OPB inp inn vpos vneg out gbw=1e6 sr=0.6e6 iq=100u
.param cc=1n
.param imax={sr*cc}
.param gm={6.2831853*gbw*cc}
Bmid mid 0 V=(v(vpos)+v(vneg))/2
Bg 0 n1 I={imax}*tanh({gm}*v(inp,inn)/{imax})
Cc n1 mid {cc}
Rg n1 mid {1e5/gm} noisy=0
D1 n1 vpos DLIM
D2 vneg n1 DLIM
Bo no 0 V=min(max(v(n1), v(vneg)+0.02), v(vpos)-0.02)
Ro no out 100 noisy=0
Biq vpos vneg I={iq}*tanh(max(v(vpos,vneg),0))
.model DLIM D(IS=1e-12 N=1)
.ends
"""

V12 = dict(vp=8.6, vref=4.5, rb=("2.2k", "1k", "2.4k"), r4res="15k", reres="6.2k", r4vca="15k", revca="4.7k",
           oa="TL072", oa_noise="OPB gbw=3e6 sr=13e6 iq=1.4m", en=18e-9, shared5=False)
V5 = dict(vp=5.0, vref=2.5, rb=("1.2k", "1.2k", "3.9k"), r4res="5.6k", reres="3.6k", r4vca="3.9k", revca="2.2k",
          oa="OPB", oa_noise="OPB", en=28e-9, shared5=True)
V5R = dict(V5, ref431=True, cvmax=3.3, r4res="12k", r4vca="7.5k", r33x="18k", rb=("620", "1.5k", "3.3k"),
           clad="10n", rref="470k", railfilt=True)
V5M = dict(V5R, oa="MCP6001", oa_noise="MCP6001", vendor=True)
VARIANTS = {"v12": V12, "v5": V5, "v5r": V5R}
if os.path.exists(MCP_LIB):
    VARIANTS["v5m"] = V5M


def core(v, noise=False, cvcut=2.5, cvres=0.0, cvvca=5.0, saw="DC 0 AC 1", vp_ac=0, vref_ac=False):
    """Voice core netlist for variant v. noise: behavioural op-amps with noise resistors (both variants)."""
    oa = v["oa_noise"] if noise else v["oa"]
    rnz = f"{rn(v['en']):.0f}" if noise and not v.get("vendor") else "1m"   # vendor model: own noise
    oa_inst = oa                                           # 'OPB gbw=.. sr=..': parameters follow the name
    ra, rm, r0 = v["rb"]
    if v.get("railfilt"):                                  # analog rail: 10 R + 220 uF from the 5 V input
        s = f"VPLUS vin 0 DC {v['vp']} AC {vp_ac}\nRFILT vin vp 10\nCFILT vp 0 220u\n"
    else:
        s = f"VPLUS vp 0 DC {v['vp']} AC {vp_ac}\n"
    if v.get("ref431"):                                    # CJ431 2.5 V, buffered; V25 and VBIAS from it
        s += """VLINK v5 vp 0
BREF vr431 0 V=2.5+2e-4*(v(vp)-5)
RNZREF vr431 vrdn {rnz}
XVREF vrdn vref vp 0 vref {oa}
RBA vref vbd 15k
RBB vbd 0 10k
CBI vbd 0 1u
XVB vbd vbias vp 0 vbias {oa}
R25A vref v25 10k
R25B v25 0 10k
C25 v25 0 1u
""".format(rnz=rnz, oa=oa_inst)
    elif v["shared5"]:                                       # one 5 V rail: references derived from it
        s += """VLINK v5 vp 0
RR1 vp vrd 10k
RR2 vrd 0 10k
CR vrd 0 10u
RNZREF vrd vrdn {rnz}
XVREF vrdn vref vp 0 vref {oa}
RBA vp vbias 3.3k
RBB vbias 0 1.5k
CBI vbias 0 1u
R25A vp v25 10k
R25B v25 0 10k
C25 v25 0 1u
""".format(rnz=rnz, oa=oa_inst)
    else:                                                  # rev 0.1: references from the regulated 5 V
        s += f"V5 v5 0 5\nVREF vref 0 {v['vref']}\nVBIAS vbias 0 1.5\nV25 v25 0 2.5\n"
    s += f"""RB5 vp vb4 {ra}
RB4 vb4 vb3 {rm}
RB3 vb3 vb2 {rm}
RB2 vb2 vb1 {rm}
RB1 vb1 vb0 {rm}
RB0 vb0 0 {r0}
CB4 vb4 0 10u
CB3 vb3 0 10u
CB2 vb2 0 10u
CB1 vb1 0 10u
CB0 vb0 0 10u
VCUT cvc 0 {cvcut}
VRES cvr 0 {cvres}
VVCA cvv 0 {cvvca}
"""
    s += voice.CVNET_EXP.format(n="C", src="cvc")
    s += voice.CVNET_LIN.format(n="R", src="cvr", x="xres").replace("R4R xres 0 15k", f"R4R xres 0 {v['r4res']}")
    s += voice.CVNET_LIN.format(n="V", src="cvv", x="xv").replace("R4V xv 0 15k", f"R4V xv 0 {v['r4vca']}")
    expo = voice.EXPO.format(cvcut="bC")
    if v.get("ref431"):
        expo = expo.replace("R33X bC xcut 33k", f"R33X bC xcut {v['r33x']}").replace(
            "RREF v5 na 300k", f"RREF vref na {v.get('rref', '150k')}")
    s += expo
    lad = voice.LADDER.format(clad=v.get("clad", "33n"))
    lad = lad.replace("XINA1 n4a ia vp 0 oa TL072", f"RNZ1 n4a n4az {rnz}\nXINA1 n4az ia vp 0 oa {oa_inst}")
    lad = lad.replace("XINA2 n4b ib vp 0 lpf TL072", f"RNZ2 n4b n4bz {rnz}\nXINA2 n4bz ib vp 0 lpf {oa_inst}")
    s += lad
    s += f"""VSAW saw 0 {saw}
VPUL pulse 0 2.5
VSUB sub 0 2.5
VNOI noise 0 2.5
"""
    s += voice.MIXER.format(saw="saw", pulse="pulse", sub="sub", noise="noise")
    s += voice.VI.format(n="R", x="xres", col="rtail", re=v["reres"])
    res = voice.RESVCA.format(fbneg="rc1", fbpos="rc2", rfb="22k")
    res = res.replace("XRDIF rdp rdm vp 0 resout TL072", f"RNZ3 rdp rdpz {rnz}\nXRDIF rdpz rdm vp 0 resout {oa_inst}")
    s += res
    vca = voice.VCA.format(inp="lpf", vbe_off=0.0, rc2="4.7k", n="V", x="xv", rg="22k")
    vca = vca.replace("REVV veV 0 4.7k", f"REVV veV 0 {v['revca']}")
    if v.get("ref431"):                                    # anti-offset current from VREF (same 10 uA at CV 0)
        vca = vca.replace("ROFFV v5 veV 470k", "ROFFV vref veV 240k")
    vca = vca.replace("XDIF dp dm vp 0 vcaout TL072", f"RNZ4 dp dpz {rnz}\nXDIF dpz dm vp 0 vcaout {oa_inst}")
    s += vca + "RDAC vref vtrim 100k\n"                    # trim DAC at mid code
    return s


def wdir(v):
    if v.get("vendor"):
        os.makedirs(OUT_M, exist_ok=True)
        with open(os.path.join(OUT_M, ".spiceinit"), "w", newline="\n") as fh:
            fh.write("set ngbehavior=ps\n")
        return OUT_M
    return OUT


def head(v):
    return spice.PREAMBLE + OPB + (f".include {spice.wsl_path(MCP_LIB)}\n"         # vendor recommendation:
                                   ".options gmin=1e-13 itl1=2000 itl6=500\n"        # small GMIN; more DC iterations
                                   if v.get("vendor") else "")


def run(name, v, analysis, **kw):
    net = f"* S10 {name}\n{head(v)}\n{core(v, **kw)}\n{spice.CTRL_HEAD}\n{analysis}\n.endc\n.end\n"
    return spice.run(net, wdir(v), name)


# ------------------------------------------------------------------ DC headroom
VCE = {"Q1 input pair": ("n1a", "tail"), "Q3 rung 1": ("n2a", "n1a"), "Q5 rung 2": ("n3a", "n2a"),
       "Q7 rung 3": ("n4a", "n3a"), "Q9 top pair": ("vp", "n4a"), "QEB expo": ("tail", "ee"),
       "QR1 res pair": ("rc1", "rtail"), "QVR res V->I": ("rtail", "veR"), "QA1 VCA pair": ("vc1", "vtail"),
       "QVV VCA V->I": ("vtail", "veV")}


def fs(v):
    return v.get("cvmax", 5.0) / 5.0


def headroom(tag, v):
    nodes = sorted({n for a in VCE.values() for n in a} | {"lpf", "oa", "vcaout", "resout", "vref"})
    worst = {k: (np.inf, None) for k in VCE}
    cur = []
    kf = fs(v)
    for cc in (0.0, 2.5 * kf, 5.0 * kf):
        for cr in (0.0, 5.0 * kf):
            for cv in (0.0, 5.0 * kf):
                name = f"op_{tag}_c{cc}_r{cr}_v{cv}".replace(".", "p")
                log = run(name, v, "op\nprint " + " ".join(f"v({n})" for n in nodes) + " i(VPLUS)",
                          cvcut=cc, cvres=cr, cvvca=cv)
                val = {m.group(1): float(m.group(2)) for m in re.finditer(r"v\((\w+)\)\s*=\s*([-\d.e+]+)", log)}
                val["vp"] = v["vp"]
                cur.append(-float(re.search(r"i\(vplus\)\s*=\s*([-\d.e+]+)", log, re.I).group(1)))
                for k, (a, b) in VCE.items():
                    d = val[a.lower()] - val[b.lower()]
                    if d < worst[k][0]:
                        worst[k] = (d, (cc, cr, cv))
    return worst, max(cur)


# ------------------------------------------------------------------ AC: cutoff, resonance, supply rejection
def ac_curve(tag, v, cvcut, cvres, vp_ac=0):
    name = f"ac_{tag}_c{cvcut}_r{cvres}_p{vp_ac}".replace(".", "p")
    saw = "DC 0 AC 0" if vp_ac else "DC 0 AC 1"
    run(name, v, f"ac dec 50 5 100k\nwrdata {{OUT}}/{name}.dat vdb(lpf) vdb(bin1) vdb(lineout)",
        cvcut=cvcut, cvres=cvres, cvvca=5.0 * fs(v), saw=saw, vp_ac=vp_ac)
    d = spice.load(os.path.join(wdir(v), name + ".dat"))
    return d["frequency"], d["vdb(lpf)"] - d["vdb(bin1)"], d["vdb(lineout)"]


def f3db(f, g):
    ref = g[(f > 5) & (f < 10)].max() if g[0] < g.max() - 3 else g[:5].mean()
    i = np.where((g < ref - 3) & (f > 6))[0]
    if not len(i):
        return np.nan
    k = i[0]
    return 10 ** np.interp(ref - 3, [g[k], g[k - 1]], [np.log10(f[k]), np.log10(f[k - 1])])


# ------------------------------------------------------------------ transients
def selfosc_net(tag, v, cvres):
    name = f"so_{tag}_r{cvres}".replace(".", "p")
    net = core(v, cvcut=2.5 * fs(v), cvres=cvres * fs(v), saw="DC 0").replace("VNOI noise 0 2.5",
                                                               "VNOI noise 0 PULSE(2.5 5 1m 1u 1u 20u 1)")
    spice.run(f"* S10 {name}\n{head(v)}\n{net}\n{spice.CTRL_HEAD}\ntran 2u 80m 0 2u\n"
              f"wrdata {{OUT}}/{name}.dat v(lpf)\n.endc\n.end\n", wdir(v), name)
    d = spice.load(os.path.join(wdir(v), name + ".dat"))
    t, y = d["time"], d["v(lpf)"]
    a1 = np.ptp(y[(t > 0.010) & (t < 0.015)])
    a2 = np.ptp(y[(t > 0.070) & (t < 0.080)])
    return a1, a2


def thd(tag, v, amp):
    """1 kHz sine of amp Vpp on the mixer's saw input (2 Vpp = a full DCO saw), filter open, VCA full."""
    name = f"thd_{tag}_a{amp}".replace(".", "p")
    log = run(name, v, "tran 2u 40m 0 2u\nfourier 1k v(lineout)\nmeas tran vpp PP v(lineout) from=30m to=40m\n"
                       "meas tran lpp PP v(lpf) from=30m to=40m", cvcut=5.0 * fs(v), cvres=0.0, cvvca=5.0 * fs(v),
              saw=f"SIN(0 {amp / 2} 1k)")
    t = float(re.search(r"THD:\s*([\d.e+-]+)", log).group(1))
    vpp = float(re.search(r"vpp\s*=\s*([\d.e+-]+)", log).group(1))
    lpp = float(re.search(r"lpp\s*=\s*([\d.e+-]+)", log).group(1))
    return t, vpp, lpp


def noise(tag, v, cvcut):
    """Output noise 20 Hz - 20 kHz at the line out (VCA full), op-amps behavioural with their input noise."""
    name = f"nz_{tag}_c{cvcut}".replace(".", "p")
    log = run(name, v, "noise v(lineout) VSAW dec 20 20 20k\nsetplot noise2\nprint onoise_total",
              noise=True, cvcut=cvcut * fs(v), cvres=0.0, cvvca=5.0 * fs(v), saw="DC 0 AC 1")
    return float(re.search(r"onoise_total\s*=\s*([\d.e+-]+)", log).group(1))


def main():
    os.makedirs(OUT, exist_ok=True)
    rows, res = [], {}
    for tag, v in VARIANTS.items():
        print(f"===== {tag}")
        worst, i_max = headroom(tag, v)
        for k, (d, at) in worst.items():
            print(f"  {k:15s} min V_CE {d:6.3f} V at CV cut/res/vca {at}")
            rows.append([tag, "vce_min_" + k.split()[0], round(d, 3)])
        print(f"  supply current max {i_max * 1e3:.1f} mA")
        rows.append([tag, "i_supply_max_ma", round(i_max * 1e3, 2)])
        cuts = np.arange(0.0, 5.01, 0.5)
        fc = []
        for c in cuts:
            f, g, _ = ac_curve(tag, v, c * fs(v), 0.0)
            fc.append(f3db(f, g))
        print("  cutoff:", " ".join(f"{c:.1f}V:{x:.0f}" for c, x in zip(cuts, fc)))
        rows += [[tag, f"fc_hz_cv{c:.1f}", round(x, 1)] for c, x in zip(cuts, fc)]
        peaks = []
        for r in (1.0, 2.0, 2.5, 2.8):
            f, g, _ = ac_curve(tag, v, 2.5 * fs(v), r * fs(v))
            peaks.append(g.max() - g[(f > 20) & (f < 40)].mean())
        print("  resonance peaks (CV_RES 1, 2, 2.5, 2.8 V):", " ".join(f"{p:.1f}" for p in peaks), "dB")
        rows += [[tag, f"res_peak_db_cv{r}", round(p, 1)] for r, p in zip((1.0, 2.0, 2.5, 2.8), peaks)]
        thr = np.nan
        for r in (2.8, 3.0, 3.1, 3.2, 3.4, 3.6, 4.0):
            a1, a2 = selfosc_net(tag, v, r)
            if a2 > a1 and a2 > 0.005:
                thr = r
                break
        print(f"  self-oscillation from CV_RES {thr} V")
        rows.append([tag, "selfosc_cv_res", thr])
        so = selfosc_net(tag, v, 5.0)
        print(f"  self-oscillation amplitude at CV_RES 5 V: {so[1] * 1e3:.0f} mVpp at lpf")
        rows.append([tag, "selfosc_vpp_lpf_res5", round(so[1], 3)])
        th = []
        for a in (1.0, 2.0, 4.0, 8.0):
            t, vpp, lpp = thd(tag, v, a)
            th.append((a, t, vpp, lpp))
            print(f"  THD drive {a} Vpp: lpf {lpp:.2f} Vpp, line out {vpp:.2f} Vpp, THD {t:.2f} %")
            rows += [[tag, f"thd_pct_drive{a}", round(t, 3)], [tag, f"lineout_vpp_drive{a}", round(vpp, 3)]]
        for c in (5.0, 2.5):
            nz = noise(tag, v, c)
            sig = th[1][2] / (2 * np.sqrt(2))              # 2 Vpp sine drive -> line-out rms
            print(f"  noise CV_CUT {c}: {nz * 1e6:.1f} uV rms, SNR re 2 Vpp drive {20 * np.log10(sig / nz):.1f} dB")
            rows += [[tag, f"noise_uv_cv{c}", round(nz * 1e6, 2)], [tag, f"snr_db_cv{c}", round(20 * np.log10(sig / nz), 1)]]
        f, _, lo = ac_curve(tag, v, 2.5 * fs(v), 0.0, vp_ac=1)
        ps_db = [float(np.interp(x, f, lo)) for x in (100, 1000, 10000)]
        print("  supply -> line out (100 Hz, 1 kHz, 10 kHz):", " ".join(f"{p:.1f}" for p in ps_db), "dB")
        rows += [[tag, f"psrr_db_{x}hz", round(p, 1)] for x, p in zip((100, 1000, 10000), ps_db)]
        res[tag] = dict(cuts=cuts, fc=fc, th=th)
    ps.save_csv("s10_5v", ["variant", "quantity", "value"], rows)

    import matplotlib.pyplot as plt
    f, ax = ps.fig(2, 1, aspect=0.75)
    for i, (tag, r) in enumerate(res.items()):
        ax[0].semilogy(r["cuts"], r["fc"], "o-", color=ps.C[i], label=tag)
        ax[1].loglog([x[0] for x in r["th"]], [x[1] for x in r["th"]], "o-", color=ps.C[i], label=tag)
    ax[0].set(xlabel=r"$CV_\mathrm{CUT}$ [V re 5 V full scale]", ylabel="cutoff [Hz]")
    ax[1].set(xlabel="drive [Vpp] (2 = full DCO saw)", ylabel="THD at line out [%]")
    ax[1].set_xticks([1, 2, 4, 8])
    ax[1].set_xticklabels(["1", "2", "4", "8"])
    ax[1].xaxis.set_minor_formatter(plt.NullFormatter())
    for a in ax:
        a.legend()
    ps.label_panels(ax)
    f.tight_layout()
    ps.save(f, "s10_5v")


if __name__ == "__main__":
    main()
