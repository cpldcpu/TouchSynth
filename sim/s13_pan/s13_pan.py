"""S13 - stereo pan on the voice card: two audio outputs (L, R) per card with a firmware-controlled pan.

Built on the S10 card netlist (variant v5c, the card as built, and v5c46, the same at 4.6 V); S10's own variants
and results stay unchanged. Op-amps: Microchip's MCP6001/2 macromodel by reference (temp/, see s10_5v.py), PSpice
compatibility mode; solver retries with a time limit and a sanity check of the operating point (the vendor model
occasionally converges to a wrong solution with eight or nine instances).

Variant A, current steering (stacked): each VCA collector feeds the emitters of a steering pair (QSL1/QSR1 on
QA1's collector, QSL2/QSR2 on QA2's; two BC847BS). The L bases sit on VREF, the R bases on VBR = VREF + p, p set
by the PC5 PWM (TIM2 CH1, 187.5 kHz carrier) through a passive network (VREF 3k, PWM 27k, +3V3 24k, 1 uF to
ground: p = -143 ... +149 mV for 0 ... 100 % duty, centre at 49 %, 66 Hz). L = alpha (I1 - I2),
R = (1 - alpha) (I1 - I2), alpha = 1 / (1 + exp(-p / VT)): a linear law, L + R constant; the firmware raises the VCA CV towards the centre
for constant power. Re-biasing for the stack: the VCA pair's bases move from VREF to VBV = 1.89 V (divider
2.4k / 7.5k from VREF, 1 uF), the V->I scales with them (R4 7.5k -> 3.0k: CV 0 ... 0.74 V; R_E 2.2k -> 1.2k: the
same 0.6 mA tail), the trim's ground return RTRF 2M -> 5.1M (keeps the trim centred at mid code). Loads 4.7k as
before, now on the steering collectors; both difference amps 10k / 30k (gain 3.0 instead of 2.2: constant power
puts each channel at -3 dB in the centre, so the gain makes up for it), 33k from both inputs to ground as on the
card. R: a new MCP6002 (unit A; unit B spare), 100 R, 10 uF, 100k bleeder.

Variant B, dual VCA (parallel pairs): a second pair QB1/QB2 on the same vin1/vin2, its own V->I (LM324 unit A,
which buffered VBIAS; VBIAS moves to the new MCP6002's unit B), its own CV network (S2 LIN, R4 7.5k) from PC5,
its own 4.7k loads and difference amp (10k / 22k, 33k to ground; the new MCP6002 unit A). L from CV_VCA (TIM1 CH4),
R from PC5. The trim (vin2) is shared: it can null one pair only (L), the R pair keeps its offset.

Tests, per variant, at 5.0 V and 4.6 V: DC headroom (S10 method: worst V_CE of every transistor over the CV
corners, here with the pan / R CV corners as well), pan law, THD at full drive, noise and signal-to-noise
(20 Hz - 20 kHz), CV feedthrough (output step with no audio, with the firmware's trim; 1 mV offsets in the
untrimmed parts), supply rejection, analog current, the PWM CV path (ripple at the outputs), parts and area.

  python s13_pan.py           results: docs/results/s13_pan.csv, docs/figures/s13_pan.(pdf|png)
"""
import os, re, subprocess, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "s10_5v"), os.path.join(HERE, "..", "lib")]
import s10_5v as T                                        # noqa: E402
import spice                                              # noqa: E402
import plotstyle as ps                                    # noqa: E402
import voice                                              # noqa: E402

OUT = os.path.join(HERE, "out")
OUT_M = os.path.join(OUT, "mcp")
if "v5c" not in T.VARIANTS or not T.VARIANTS["v5c"].get("vendor"):
    sys.exit("S13 needs S10's v5c with Microchip's MCP6002 model (temp/mcp6001_model/, see s10_5v.py)")
SUP = {"5V0": T.VARIANTS["v5c"], "4V6": T.VARIANTS["v5c46"]}
V33 = 3.3                                                 # MCU supply: PWM full scale
VT = 1.380649e-23 * 300.15 / 1.602176634e-19

# ------------------------------------------------------------------ variant A component values
A = dict(rbv1="2.4k", rbv2="7.5k", r4v="3k", rev="1.2k", rtrf="5.1Meg", rl="4.7k", rg="30k",
         rpa="3k", rpb="27k", rpc="24k", cpn="1u")
# ------------------------------------------------------------------ variant B component values
B = dict(r4w="7.5k", rew="2.2k", rl="4.7k", rg="22k")


def wdir():
    os.makedirs(OUT_M, exist_ok=True)
    with open(os.path.join(OUT_M, ".spiceinit"), "w", newline="\n") as fh:
        fh.write("set ngbehavior=ps\n")
    return OUT_M


# S10's solver retries, the node set first (with S13's bias nodes): with eight or nine vendor-model instances the
# plain operating point often fails, and the 'noopiter' retry can take a minute; the circuit stays the same.
NODESET = ".nodeset v(vref)=2.5 v(vrdn)=2.5 v(vbias)=1.0"
RETRY = (NODESET + "\n", NODESET + " v(vbv)=1.89 v(vbr)=2.5\n", ".options rshunt=1e10\n",
         NODESET + "\n.options gmin=1e-12\n", "", NODESET + "\n.options rshunt=1e10\n",
         NODESET + " v(vcaout)=2.5 v(lpf)=2.5\n", ".options rshunt=1e9\n", NODESET + "\n.options gmin=1e-11\n",
         ".options noopiter\n")


def spice_run(text, name, limit):
    """spice.run with a time limit inside WSL: a failing operating point can iterate for a minute before it gives
    up, a converging one takes about a second."""
    d = wdir()
    text = text.replace("{MODELS}", spice.wsl_path(spice.MODELS)).replace("{OUT}", spice.wsl_path(d))
    with open(os.path.join(d, name + ".cir"), "w", newline="\n") as fh:
        fh.write(text)
    cmd = ["wsl", "-e", "bash", "-lc", f"cd '{spice.wsl_path(d)}' && timeout {limit} ngspice -b '{name}.cir' 2>&1;"
                                       " echo EXIT=$?"]
    log = subprocess.run(cmd, capture_output=True, text=True).stdout
    with open(os.path.join(d, name + ".log"), "w", newline="\n") as fh:
        fh.write(log)
    bad = ("bail out", "error on line", "simulation interrupted", "fatal", "no such", "cannot", "singular",
           "timestep too small", "exit=124")
    if any(b in log.lower() for b in bad) or "EXIT=0" not in log:
        raise RuntimeError(f"ngspice failed for {name}:\n{log[-2000:]}")
    return log


def sane(log):
    """The operating point printed first (CHECK in run()): VREF at 2.5 V and the difference amps near VREF. The
    vendor model occasionally converges to a wrong solution (an output stuck near a rail)."""
    val = {}
    for m in re.finditer(r"^v\((vref|vcaout|vcaoutr)\)\s*=\s*([-\d.e+]+)", log, re.M):
        val.setdefault(m.group(1), float(m.group(2)))
    return (abs(val.get("vref", 0) - 2.5) < 0.05 and abs(val.get("vcaout", 0) - 2.5) < 0.3 and
            abs(val.get("vcaoutr", 2.5) - 2.5) < 0.3)


def srun(net, name):
    """Run with solver retries (the vendor model's DC solution is marginal with many instances); a run whose
    operating point fails the sanity check counts as failed."""
    limit = 150 if "\ntran " in net else 20 if ("\nnoise " in net or "\nac dec" in net) else 4
    opts = [o for o in RETRY if "v(vbv)" not in o or "vbv" in net]
    for k, opt in enumerate(opts):
        try:
            log = spice_run(f"* S13 {name}\n{opt}{net}", name, limit)
            if sane(log):
                return log
            if k == len(opts) - 1:
                raise RuntimeError(f"{name}: no sane operating point")
        except RuntimeError:
            if k == len(opts) - 1:
                raise


def diffamp(tag, cp, cm, out, rg, oa, rnz, line):
    """Second difference amp (as the card's VCA one): out = VREF - G (V(cm) - V(cp)), 100 R, 10 uF, bleeder, load."""
    return f"""RD1{tag} {cm} dm{tag} 10k
RD2{tag} dm{tag} {out} {rg}
RD3{tag} {cp} dp{tag} 10k
RD4{tag} dp{tag} vref {rg}
RD5{tag} dp{tag} 0 33k
RD6{tag} dm{tag} 0 33k
RNZ{tag} dp{tag} dpz{tag} {rnz}
XDIF{tag} dpz{tag} dm{tag} vp 0 {out} {oa}
RISO{tag} {out} vco{tag} 100
COUT{tag} vco{tag} {line} 10u
RLOAD{tag} {line} 0 10k
RBL{tag} {line} 0 100k
"""


def card(var, v, noise=False, cvcut=None, cvres=0.0, cvvca=V33, pan=0.5, cvr=V33, saw="DC 0 AC 1", vp_ac=0,
         trim=T.DAC_MID, vos_a=0.0, vos_s=0.0, vos_b=0.0, pan_ac=0, cvr_ac=0, cvv_ac=0):
    """Card netlist. var 'A' (steering), 'B' (dual VCA) or 'M' (S10 v5c unchanged: today's mono card).
    cvvca: CV_VCA (TIM1 CH4 average, 0...3.3 V); pan: PC5 duty (A); cvr: PC5 average (B, the R level CV).
    vos_a: VCA pair offset (trimmed by the firmware), vos_s: steering mismatch (A, between the two steering
    pairs), vos_b: R pair offset (B, untrimmed). Outputs: lineout (L), lineoutr (R)."""
    cvcut = V33 if cvcut is None else cvcut
    oa = v["oa_noise"] if noise else v["oa"]
    rnz = f"{T.rn(v['en']):.0f}" if noise and not v.get("vendor") else "1m"
    s = T.core(v, noise=noise, cvcut=cvcut, cvres=cvres, cvvca=cvvca, saw=saw, vp_ac=vp_ac)
    s = s.replace(f"VTRP trp 0 {T.DAC_MID}", f"VTRP trp 0 {trim:.6f}")
    s = s.replace("VOSV vin2m vin2 0.0", f"VOSV vin2m vin2 {vos_a:.6g}")
    if cvv_ac:
        s = s.replace(f"VVCA cvv 0 {cvvca}", f"VVCA cvv 0 DC {cvvca} AC {cvv_ac}")
    if var == "M":
        return s
    if var == "A":
        a = A
        s = s.replace("RVB1 vin1 vref 1k", "RVB1 vin1 vbv 1k").replace("RVB2 vin2 vref 1k", "RVB2 vin2 vbv 1k")
        s = s.replace("RTRF vin1 0 2Meg", f"RTRF vin1 0 {a['rtrf']}")
        s = s.replace("R4V xv 0 7.5k", f"R4V xv 0 {a['r4v']}").replace("REVV veV 0 2.2k", f"REVV veV 0 {a['rev']}")
        s = s.replace("RVC1 vp vc1 4.7k\n", "").replace("RVC2 vp vc2 4.7k\n", "")
        s = s.replace("RD1 vc1 dm 10k", "RD1 vl1 dm 10k").replace("RD3 vc2 dp 10k", "RD3 vl2 dp 10k")
        s = s.replace("RD2 dm vcaout 22k", f"RD2 dm vcaout {a['rg']}").replace("RD4 dp vref 22k", f"RD4 dp vref {a['rg']}")
        s += f"""* ---- S13 A: VCA base bias, steering pairs, pan network, R difference amp
RBV1 vref vbv {a['rbv1']}
RBV2 vbv 0 {a['rbv2']}
CBV vbv 0 1u
QSL1 vl1 vref vc1 BC847B
QSR1 vr1 vbrs vc1 BC847B
VOSS vbrs vbr {vos_s:.6g}
QSL2 vl2 vref vc2 BC847B
QSR2 vr2 vbr vc2 BC847B
RVC1 vp vl1 {a['rl']}
RVC2 vp vl2 {a['rl']}
RVR1 vp vr1 {a['rl']}
RVR2 vp vr2 {a['rl']}
VPAN pan 0 DC {pan * V33:.6f} AC {pan_ac}
V33 v33 0 {V33}
RPA vref vbr {a['rpa']}
RPB pan vbr {a['rpb']}
RPC v33 vbr {a['rpc']}
CPN vbr 0 {a['cpn']}
"""
        s += diffamp("R", "vr2", "vr1", "vcaoutr", a["rg"], oa, rnz, "lineoutr")
        s += "XSPR vref spo vp 0 spo " + oa + "\n"           # new MCP6002's unit B: spare (follower on VREF)
        return s
    b = B
    s = s.replace("XVB vbd vbias vp 0 vbias LM324", f"XVB vbd vbias vp 0 vbias {oa}")   # VBIAS -> MCP6002 B
    s += f"""* ---- S13 B: second pair on vin1 / vin2, own V->I (LM324 unit A), loads, difference amp
QB1 vbc1 vin1 vtailw BC847B
QB2 vbc2 vin2b vtailw BC847B
VOSB vin2b vin2 {vos_b:.6g}
RVC3 vp vbc1 {b['rl']}
RVC4 vp vbc2 {b['rl']}
VCVR cvw 0 DC {cvr} AC {cvr_ac}
"""
    s += voice.CVNET_LIN.format(n="W", src="cvw", x="xw").replace("R4W xw 0 15k", f"R4W xw 0 {b['r4w']}")
    s += voice.VI.format(n="W", x="xw", col="vtailw", re=b["rew"])
    s += "ROFFW vref veW 240k\n"
    s += diffamp("R", "vbc2", "vbc1", "vcaoutr", b["rg"], oa, rnz, "lineoutr")
    return s


def head(v):
    return T.head(v)


def run(name, v, analysis, var="A", **kw):
    check = "op\nprint v(vref) v(vcaout)" + (" v(vcaoutr)" if var != "M" else "") + "\n"
    return srun(f"{head(v)}\n{card(var, v, **kw)}\n{spice.CTRL_HEAD}\n{check}{analysis}\n.endc\n.end\n", name)


def opv(name, v, nodes, var="A", extra="", **kw):
    log = run(name, v, "op\nprint " + " ".join(f"v({n})" for n in nodes) + " i(VPLUS)" + extra, var=var, **kw)
    val = {m.group(1).lower(): float(m.group(2)) for m in re.finditer(r"v\((\w+)\)\s*=\s*([-\d.e+]+)", log)}
    val["vp"] = val.get("vp", v["vp"])
    val["i"] = -float(re.search(r"i\(vplus\)\s*=\s*([-\d.e+]+)", log, re.I).group(1))
    return val, log


def outs(var):
    return ["lineout"] if var == "M" else ["lineout", "lineoutr"]


def tagname(*a):
    return "_".join(str(x) for x in a).replace(".", "p").replace("-", "m")


# ------------------------------------------------------------------ 1. DC headroom (S10 method)
VCE_A = dict(T.VCE, **{"QA2 VCA pair": ("vc2", "vtail"), "QSL1 steer L1": ("vl1", "vc1"),
                       "QSR1 steer R1": ("vr1", "vc1"), "QSL2 steer L2": ("vl2", "vc2"),
                       "QSR2 steer R2": ("vr2", "vc2")})
VCE_B = dict(T.VCE, **{"QA2 VCA pair": ("vc2", "vtail"), "QB1 R pair": ("vbc1", "vtailw"),
                       "QB2 R pair": ("vbc2", "vtailw"), "QVW R V->I": ("vtailw", "vew")})


def headroom(var, sup, v):
    """Worst V_CE per transistor over the CV corners: CV_CUT 0 / mid / full, CV_RES 0 / full, CV_VCA 0 / full and
    the pan (A: duty 0 / 50 / 100 %) or the R level CV (B: 0 / full). Also the difference-amp input range."""
    vce = VCE_A if var == "A" else VCE_B
    nodes = sorted({n for ab in vce.values() for n in ab} | {"dp", "dm", "dpr", "dmr"})
    worst = {k: (np.inf, None) for k in vce}
    cur, dps = [], []
    xs = (0.0, 0.5, 1.0) if var == "A" else (0.0, V33)
    for cc in (0.0, V33 / 2, V33):
        for cr in (0.0, V33):
            for cv in (0.0, V33):
                for x in xs:
                    kw = dict(pan=x) if var == "A" else dict(cvr=x)
                    val, _ = opv(tagname("hr", var, sup, cc, cr, cv, x), v, nodes, var, cvcut=cc, cvres=cr,
                                 cvvca=cv, **kw)
                    cur.append(val["i"])
                    dps += [val[n] for n in ("dp", "dm", "dpr", "dmr")]
                    for k, (a, b) in vce.items():
                        d = val[a.lower()] - val[b.lower()]
                        if d < worst[k][0]:
                            worst[k] = (d, (cc, cr, cv, x))
    return worst, max(cur), (min(dps), max(dps))


# ------------------------------------------------------------------ 2. pan law (AC gain at 1 kHz)
PANS = (0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 1.0)
CVS = (0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.2, 1.65, 2.0, 2.4, 2.8, 3.0, 3.3)    # PWM averages [V]


def ac1k(name, v, var, **kw):
    """|gain| at 1 kHz from the DAC pin to each line out (filter open, resonance off)."""
    log = run(name, v, "ac lin 1 1k 1k\nprint " + " ".join(f"vm({o})" for o in outs(var)), var=var, cvcut=V33,
              cvres=0.0, saw="DC 0 AC 1", **kw)
    return [float(re.search(rf"vm\({o}\)\s*=\s*([-\d.e+]+)", log).group(1)) for o in outs(var)]


def inv(cvs, f, target):
    """CV for a relative gain target on the monotonic curve f(cv) (linear interpolation)."""
    return float(np.interp(target, f, cvs))


def db(x):
    return 20 * np.log10(np.abs(x))


# ------------------------------------------------------------------ 3./4. THD and noise
def thd(name, v, var, **kw):
    """2 Vpp drive (S10: full DAC scale), 1 kHz, filter open: THD and line-out Vpp per channel."""
    an = "tran 2u 40m 0 2u\n" + "".join(f"fourier 1k v({o})\nmeas tran pp_{o} PP v({o}) from=30m to=40m\n"
                                         for o in outs(var))
    log = run(name, v, an, var=var, cvcut=V33, cvres=0.0, saw=f"SIN(0 {T.DAC_MID} 1k)", **kw)
    t = [float(x) for x in re.findall(r"THD:\s*([\d.e+-]+)", log)]
    pp = [float(re.search(rf"pp_{o}\s*=\s*([\d.e+-]+)", log).group(1)) for o in outs(var)]
    return t, pp


def noise(name, v, var, out, **kw):
    """Output noise 20 Hz - 20 kHz at one line out (S10's method; the vendor model's own noise)."""
    log = run(name, v, f"noise v({out}) VSAW dec 20 20 20k\nsetplot noise2\nprint onoise_total", var=var,
              noise=True, cvcut=V33, cvres=0.0, saw="DC 0 AC 1", **kw)
    return float(re.search(r"onoise_total\s*=\s*([\d.e+-]+)", log).group(1))


# ------------------------------------------------------------------ 5. CV feedthrough (DC steps, no audio)
def dc(name, v, var, **kw):
    val, _ = opv(name, v, ["vcaout"] + (["vcaoutr"] if var != "M" else []), var, **kw)
    return val["vcaout"], val.get("vcaoutr", np.nan)


def trim_null(tag, v, var, on, off, ch=0, **kw):
    """The firmware's trim: VCA trim PWM average [V] that nulls channel ch's step between the CV settings off -> on
    (the step is linear in the trim voltage)."""
    st = []
    for t in (1.0, 2.3):
        a = dc(tagname("tr", tag, t, "on"), v, var, trim=t, **on, **kw)[ch]
        b = dc(tagname("tr", tag, t, "off"), v, var, trim=t, **off, **kw)[ch]
        st.append(a - b)
    return 1.0 - st[0] * 1.3 / (st[1] - st[0])


# ------------------------------------------------------------------ 6./8. AC: supply rejection, CV ripple
def acrun(name, v, var, vecs, fmin=5, fmax=100e3, ppd=50, **kw):
    run(name, v, f"ac dec {ppd} {fmin} {fmax}\nwrdata {{OUT}}/{name}.dat " + " ".join(f"vm({x})" for x in vecs),
        var=var, **kw)
    return spice.load(os.path.join(wdir(), name + ".dat"))


def at(d, key, f0):
    return float(10 ** np.interp(np.log10(f0), np.log10(d["frequency"]), np.log10(d[key])))


F_CAR, F_DITH, F_TIM1 = 187.5e3, 187.5e3 / 16, 46.875e3   # TIM2 carrier, 16-step dither pattern, TIM1 CV carrier
A_CAR = 4 / np.pi * V33 / 2                               # PWM fundamental at 50 % duty [V peak]
A_DITH = 4 / np.pi * V33 / 128 / 2                        # dither pattern (1 LSB square) fundamental [V peak]

# ------------------------------------------------------------------ 7. parts and area
CRTYD = {"0603": 4.32, "SOT-363": 6.38, "SOT-23": 13.12, "SOIC-8": 39.96}   # KiCad courtyards [mm^2]
# (refs, value, package, LCSC, count, function)
PARTS_A = [
    ("QSL1/QSR1, QSL2/QSR2", "BC847BS", "SOT-363", "C41375126", 2, "steering pairs on VCA_C1 and VCA_C2"),
    ("U (XDIFR; unit B spare)", "MCP6002", "SOIC-8", "C7377", 1, "R difference amp"),
    ("C", "100n", "0603", "C14663", 1, "decoupling of the new MCP6002"),
    ("RVR1, RVR2", "4.7k", "0603", "C23162", 2, "R collector loads"),
    ("RD1R, RD3R", "10k", "0603", "C25804", 2, "R difference amp inputs"),
    ("RD2R, RD4R", "30k", "0603", "C22984", 2, "R difference amp feedback / reference"),
    ("RD5R, RD6R", "33k", "0603", "C4216", 2, "R difference amp inputs to GND (input range)"),
    ("RISOR", "100", "0603", "C22775", 1, "R output isolation"),
    ("COUTR", "10u", "0603", "C19702", 1, "R output coupling (10 V X5R)"),
    ("RBLR", "100k", "0603", "C25803", 1, "R line-out bleeder"),
    ("RBV1", "2.4k", "0603", "C22940", 1, "VCA base bias VBV from VREF"),
    ("RBV2", "7.5k", "0603", "C23234", 1, "VCA base bias VBV to GND"),
    ("CBV", "1u", "0603", "C15849", 1, "VBV decoupling"),
    ("RPA", "3k", "0603", "C4211", 1, "pan network: VREF to VBR"),
    ("RPB", "27k", "0603", "C22967", 1, "pan network: PC5 PWM to VBR"),
    ("RPC", "24k", "0603", "C23352", 1, "pan network: +3V3 to VBR (centres the range)"),
    ("CPN", "1u", "0603", "C15849", 1, "pan filter (66 Hz)"),
]
CHANGED_A = [("R4V", "7.5k", "3k", "C4211"), ("REVV", "2.2k", "1.2k", "C22765"), ("RTRF", "2M", "5.1M", "C13320"),
             ("RD2, RD4", "22k", "30k", "C22984")]
PARTS_B = [
    ("QB1/QB2", "BC847BS", "SOT-363", "C41375126", 1, "R pair on VCA_IN1 / VCA_IN2"),
    ("QVW", "MMBT3904", "SOT-23", "C20526", 1, "R V->I transistor (LM324 unit A)"),
    ("U (XDIFR, XVB)", "MCP6002", "SOIC-8", "C7377", 1, "R difference amp; unit B: VBIAS buffer (from the LM324)"),
    ("C", "100n", "0603", "C14663", 1, "decoupling of the new MCP6002"),
    ("R1W, RBVW", "1k", "0603", "C21190", 2, "R CV network; V->I base resistor"),
    ("C1W", "100n", "0603", "C14663", 1, "R CV network"),
    ("R2W, R3W", "4.7k", "0603", "C23162", 2, "R CV network"),
    ("C2W", "33n", "0603", "C21117", 1, "R CV network"),
    ("R4W", "7.5k", "0603", "C23234", 1, "R CV network"),
    ("C3W", "22n", "0603", "C21122", 1, "R CV network"),
    ("REVW", "2.2k", "0603", "C4190", 1, "R V->I R_E"),
    ("ROFFW", "240k", "0603", "C4197", 1, "R V->I anti-offset from VREF"),
    ("RVC3, RVC4", "4.7k", "0603", "C23162", 2, "R collector loads"),
    ("RD1R, RD3R", "10k", "0603", "C25804", 2, "R difference amp inputs"),
    ("RD2R, RD4R", "22k", "0603", "C31850", 2, "R difference amp feedback / reference"),
    ("RD5R, RD6R", "33k", "0603", "C4216", 2, "R difference amp inputs to GND"),
    ("RISOR", "100", "0603", "C22775", 1, "R output isolation"),
    ("COUTR", "10u", "0603", "C19702", 1, "R output coupling"),
    ("RBLR", "100k", "0603", "C25803", 1, "R line-out bleeder"),
    ("RLB3", "10k", "0603", "C25804", 1, "R into the loopback (L + R summed at PC4)"),
]


def area(parts):
    n = sum(p[4] for p in parts)
    return n, sum(CRTYD[p[2]] * p[4] for p in parts)


FT_PANS = (0.0, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0)
VOS = 1e-3                                                # BC847BS pair matching (the brief's figure)


def s10_rows():
    import csv
    with open(os.path.join(ps.DATADIR, "s10_5v.csv"), encoding="utf-8") as fh:
        return {(r[0], r[1]): float(r[2]) for r in list(csv.reader(fh))[1:]}


def theta(gl, gr):
    """Pan position as the angle of (L, R): 0 = hard left, 1 = hard right."""
    return np.degrees(np.arctan2(gr, gl)) / 90


def study(sup, v, add, fig):
    s10 = s10_rows()
    s10tag = "v5c" if sup == "5V0" else "v5c46"
    print(f"===== {sup} (S10 {s10tag})")

    # ---- 1. headroom
    for var in ("A", "B"):
        worst, imax, (dlo, dhi) = headroom(var, sup, v)
        for k, (d, c) in worst.items():
            print(f"  {var} {k:16s} min V_CE {d:6.3f} V at CV cut/res/vca/{'pan' if var == 'A' else 'R'} {c}")
            add(var, sup, "vce_min_" + k.split()[0], d)
        print(f"  {var} difference-amp inputs {dlo:.2f} ... {dhi:.2f} V; analog current max {imax * 1e3:.2f} mA")
        add(var, sup, "diffamp_in_min_v", dlo), add(var, sup, "diffamp_in_max_v", dhi)
        add(var, sup, "i_supply_max_ma", imax * 1e3)
    for q in ("vce_min_QA1", "vce_min_QVV", "vce_min_QEB", "vca_dp_min_v", "vca_dp_max_v", "i_supply_max_ma"):
        add("M", sup, q, s10[(s10tag, q)])

    # ---- 2. pan law
    gm = ac1k(tagname("g", "M", sup), v, "M")[0]
    add("M", sup, "gain_1k", gm)
    gp = np.array([ac1k(tagname("gp", sup, p), v, "A", pan=p) for p in PANS])
    gl, gr = gp[:, 0], gp[:, 1]
    bal = db(gl / gr)
    pc = float(np.interp(0.0, bal[::-1], np.array(PANS)[::-1]))       # duty for L = R
    gcl, gcr = ac1k(tagname("gpc", sup), v, "A", pan=pc)
    gcv = np.array([sum(ac1k(tagname("gcv", sup, c), v, "A", pan=pc, cvvca=c)) for c in CVS])
    fa = gcv / gcv[-1]                                                # VCA law (both channels), re full
    pw_c = gcl ** 2 + gcr ** 2
    s_cp = np.minimum(np.sqrt(pw_c / (gl ** 2 + gr ** 2)), 1.0)
    cv_cp = np.array([inv(CVS, fa, s) for s in s_cp])
    chk = ac1k(tagname("gchk", sup), v, "A", pan=0.01, cvvca=cv_cp[1])
    err = 10 * np.log10((chk[0] ** 2 + chk[1] ** 2) / pw_c)
    print(f"  A: centre at duty {pc:.3f}: L {db(gcl / gm):+.2f} dB, R {db(gcr / gm):+.2f} dB re today's L "
          f"(power {10 * np.log10(pw_c / gm ** 2):+.2f} dB); hard left (1 %) L {db(gl[1] / gm):+.2f} dB")
    print(f"     separation: 0 % {db(gr[0] / gl[0]):.1f} dB, 1 % {db(gr[1] / gl[1]):.1f} dB, 99 % "
          f"{db(gl[-2] / gr[-2]):.1f} dB, 100 % {db(gl[-1] / gr[-1]):.1f} dB")
    print("     duty   L dB   R dB  (re today)  constant power: CV_VCA [V]  L dB   R dB")
    for p, a, b, c, s in zip(PANS, gl, gr, cv_cp, s_cp):
        print(f"     {p:4.2f} {db(a / gm):+6.2f} {db(b / gm):+6.2f}                   {c:5.3f} ({c / V33 * 100:5.1f} %)"
              f" {db(a * s / gm):+6.2f} {db(b * s / gm):+6.2f}")
        add("A", sup, f"pan_l_db_d{p:.2f}", db(a / gm)), add("A", sup, f"pan_r_db_d{p:.2f}", db(b / gm))
        add("A", sup, f"cp_cvvca_v_d{p:.2f}", c), add("A", sup, f"cp_l_db_d{p:.2f}", db(a * s / gm))
        add("A", sup, f"cp_r_db_d{p:.2f}", db(b * s / gm))
    print(f"     check, duty 1 % at CV_VCA {cv_cp[1]:.3f} V: power {err:+.2f} dB re the centre")
    k = list(PANS).index(0.5)
    slope = (db(gl[k + 1]) - db(gl[k - 1])) / (PANS[k + 1] - PANS[k - 1])     # dB per unit duty, L at centre
    print(f"     pan resolution (7 bit) at the centre: {abs(slope) / 128:.3f} dB per step per channel")
    for q, x in (("centre_duty", pc), ("centre_l_db", db(gcl / gm)), ("centre_r_db", db(gcr / gm)),
                 ("centre_power_db", 10 * np.log10(pw_c / gm ** 2)), ("hardl_l_db", db(gl[1] / gm)),
                 ("sep_db_d0", db(gr[0] / gl[0])), ("sep_db_d1pct", db(gr[1] / gl[1])),
                 ("sep_db_d99pct", db(gl[-2] / gr[-2])), ("sep_db_d100", db(gl[-1] / gr[-1])),
                 ("cp_check_db", err), ("pan_step_db_centre", abs(slope) / 128),
                 ("cp_cvvca_hardl_pct", cv_cp[1] / V33 * 100)):
        add("A", sup, q, x)
    for c, x in zip(CVS, fa):
        add("A", sup, f"law_db_cv{c:.2f}", db(x))
    # B: two VCA laws
    fl = np.array([ac1k(tagname("gbl", sup, c), v, "B", cvvca=c, cvr=0.0)[0] for c in CVS])
    fr = np.array([ac1k(tagname("gbr", sup, c), v, "B", cvvca=0.0, cvr=c)[1] for c in CVS])
    gbl, gbr = fl[-1], fr[-1]
    lo = ac1k(tagname("gbsep", sup), v, "B", cvvca=V33, cvr=0.0)
    ro = ac1k(tagname("gbsep2", sup), v, "B", cvvca=0.0, cvr=V33)
    cvl_c, cvr_c = inv(CVS, fl / gbl, 2 ** -0.5), inv(CVS, fr / gbr, 2 ** -0.5)
    bc = ac1k(tagname("gbc", sup), v, "B", cvvca=cvl_c, cvr=cvr_c)
    print(f"  B: full L {db(gbl / gm):+.2f} dB, R {db(gbr / gm):+.2f} dB re today's (input loading by the second "
          f"pair); separation {db(lo[1] / lo[0]):.1f} dB (R closed), {db(ro[0] / ro[1]):.1f} dB (L closed)")
    print(f"     constant-power centre: CV_VCA {cvl_c:.3f} V, CV_R {cvr_c:.3f} V: L {db(bc[0] / gm):+.2f} dB, "
          f"R {db(bc[1] / gm):+.2f} dB")
    for q, x in (("full_l_db", db(gbl / gm)), ("full_r_db", db(gbr / gm)), ("sep_db_rclosed", db(lo[1] / lo[0])),
                 ("sep_db_lclosed", db(ro[0] / ro[1])), ("cp_cvvca_v", cvl_c), ("cp_cvr_v", cvr_c),
                 ("centre_l_db", db(bc[0] / gm)), ("centre_r_db", db(bc[1] / gm)),
                 ("centre_power_db", 10 * np.log10((bc[0] ** 2 + bc[1] ** 2) / gm ** 2))):
        add("B", sup, q, x)
    for c, a, b in zip(CVS, fl, fr):
        add("B", sup, f"law_l_db_cv{c:.2f}", db(a / gbl)), add("B", sup, f"law_r_db_cv{c:.2f}", db(b / gbr))
    # level resolution of a PWM-driven VCA (B's R): 7 bit plain, 7 + 4 bit with DMA dither, TIM1's 10 + 2 bit
    res = {}
    for bits in (7, 11, 12):
        n = 2 ** bits
        lev = np.interp(np.arange(n + 1) / n * V33, (0.0,) + CVS, np.r_[0.0, fr / gbr])
        for target in (-20, -40):
            i = int(np.argmin(np.abs(db(np.maximum(lev, 1e-9)) - target)))
            res[(bits, target)] = db(lev[i + 1] / lev[i]) if lev[i] > 0 else np.inf
        first = int(np.argmax(lev > 1e-6))
        res[(bits, "min")] = db(lev[first]) if first else np.nan
    print("     level steps of a PWM-driven VCA (dB per code at -20 / -40 dB; lowest level above zero): " +
          "; ".join(f"{b} bit {res[(b, -20)]:.2f} / {res[(b, -40)]:.2f}, {res[(b, 'min')]:.0f} dB"
                    for b in (7, 11, 12)))
    for b in (7, 11, 12):
        add("B", sup, f"step_db_m20_{b}bit", res[(b, -20)]), add("B", sup, f"step_db_m40_{b}bit", res[(b, -40)])
        add("B", sup, f"min_level_db_{b}bit", res[(b, "min")])
    if sup == "5V0":
        fig.update(pans=np.array(PANS), gl=gl / gm, gr=gr / gm, s=s_cp, cv=cv_cp, pc=pc)

    # ---- 3. THD and 4. noise
    cond = {"M": ("M", {}), "A_centre": ("A", dict(pan=pc)), "A_hardleft": ("A", dict(pan=0.01)),
            "B_centre": ("B", dict(cvvca=cvl_c, cvr=cvr_c)), "B_hardleft": ("B", dict(cvvca=V33, cvr=0.0))}
    lev = {}
    for c, (var, kw) in cond.items():
        t, pp = thd(tagname("thd", sup, c), v, var, **kw)
        lev[c] = pp
        chs = "LR"[:len(pp)] if "hardleft" not in c else "L"
        print(f"  THD {c:11s}: " + ", ".join(f"{ch} {t[i]:.3f} % at {pp[i]:.3f} Vpp" for i, ch in enumerate(chs)))
        for i, ch in enumerate(chs):
            add(var, sup, f"thd_pct_{c.split('_')[-1]}_{ch}", t[i])
            add(var, sup, f"vpp_{c.split('_')[-1]}_{ch}", pp[i])
    ref_rms = lev["M"][0] / (2 * np.sqrt(2))
    for c, (var, kw) in cond.items():
        chs = ("lineout", "lineoutr")[:len(lev[c])] if "hardleft" not in c else ("lineout",)
        for i, o in enumerate(chs):
            nz = noise(tagname("nz", sup, c, o), v, var, o, **kw)
            snr = db(lev[c][i] / (2 * np.sqrt(2)) / nz)
            ch = "L" if o == "lineout" else "R"
            print(f"  noise {c:11s} {ch}: {nz * 1e6:6.1f} uV rms; SNR re its 2 Vpp-drive level {snr:.1f} dB, "
                  f"re today's full level {db(ref_rms / nz):.1f} dB")
            tc = c.split("_")[-1]
            add(var, sup, f"noise_uv_{tc}_{ch}", nz * 1e6), add(var, sup, f"snr_db_{tc}_{ch}", snr)
            add(var, sup, f"snr_re_mono_db_{tc}_{ch}", db(ref_rms / nz))

    # ---- 5. CV feedthrough: DC steps at VCAOUT / VCAOUT_R, no audio, firmware trim on L
    pk = lev["M"][0] / 2                                              # today's full-drive peak at the line out
    rel = lambda x: db(x / pk) if abs(x) > 1e-7 else -140.0
    st_m_un = (dc(tagname("ftm", sup, "on"), v, "M", vos_a=VOS, cvvca=V33)[0] -
               dc(tagname("ftm", sup, "off"), v, "M", vos_a=VOS, cvvca=0.0)[0])
    tm = trim_null(f"m{sup}", v, "M", dict(cvvca=V33), dict(cvvca=0.0), vos_a=VOS)
    st_m = (dc(tagname("ftm", sup, "ont"), v, "M", vos_a=VOS, cvvca=V33, trim=tm)[0] -
            dc(tagname("ftm", sup, "offt"), v, "M", vos_a=VOS, cvvca=0.0, trim=tm)[0])
    print(f"  feedthrough, today (1 mV pair offset): untrimmed {st_m_un * 1e3:+.1f} mV ({rel(st_m_un):.1f} dB re "
          f"full peak); trim at {tm:.3f} V: {st_m * 1e3:+.3f} mV")
    add("M", sup, "ft_untrimmed_mv", st_m_un * 1e3), add("M", sup, "ft_untrimmed_db", rel(st_m_un))
    add("M", sup, "ft_trim_v", tm), add("M", sup, "ft_trimmed_mv", st_m * 1e3)
    # A: VCA pair 1 mV (trimmed on L at hard left), steering pairs 1 mV apart (untrimmed)
    ta0 = None
    for tag, vs in (("", VOS), ("_nosteer", 0.0)):
        ta = trim_null(f"a{sup}{tag}", v, "A", dict(cvvca=V33, pan=0.0), dict(cvvca=0.0, pan=0.0), vos_a=VOS,
                       vos_s=vs)
        ta0 = ta if not tag else ta0
        on = np.array([dc(tagname("fta", sup, tag, p, "on"), v, "A", vos_a=VOS, vos_s=vs, trim=ta, cvvca=V33,
                          pan=p) for p in FT_PANS])
        off = np.array([dc(tagname("fta", sup, tag, p, "off"), v, "A", vos_a=VOS, vos_s=vs, trim=ta, cvvca=0.0,
                           pan=p) for p in FT_PANS])
        stp = on - off
        pan_l, pan_r = on[:, 0] - on[0, 0], on[:, 1] - on[0, 1]
        print(f"  feedthrough A{tag} (VCA pair 1 mV, trimmed at hard left to {ta:.3f} V; steering mismatch "
              f"{vs * 1e3:.0f} mV): VCA step L / R per pan duty: " +
              " ".join(f"{p:.2f}: {a * 1e3:+.1f}/{b * 1e3:+.1f}" for p, (a, b) in zip(FT_PANS, stp)) + " mV")
        print(f"     pan 0 -> x at VCA full: L max {np.abs(pan_l).max() * 1e3:.1f} mV, R max "
              f"{np.abs(pan_r).max() * 1e3:.1f} mV")
        mx = np.abs(stp).max()
        add("A", sup, f"ft_trim_v{tag}", ta), add("A", sup, f"ft_vca_step_max_mv{tag}", mx * 1e3)
        add("A", sup, f"ft_vca_step_max_db{tag}", rel(mx))
        add("A", sup, f"ft_vca_step_centre_l_mv{tag}", stp[FT_PANS.index(0.5), 0] * 1e3)
        add("A", sup, f"ft_vca_step_centre_r_mv{tag}", stp[FT_PANS.index(0.5), 1] * 1e3)
        add("A", sup, f"ft_vca_step_hardl_l_mv{tag}", stp[0, 0] * 1e3)
        add("A", sup, f"ft_vca_step_hardr_r_mv{tag}", stp[-1, 1] * 1e3)
        add("A", sup, f"ft_pan_step_max_mv{tag}", max(np.abs(pan_l).max(), np.abs(pan_r).max()) * 1e3)
        if not tag and sup == "5V0":                                  # thump at constant power, for the figure
            cvs = [float(np.interp(p, PANS, cv_cp)) for p in FT_PANS]
            on_cp = np.array([dc(tagname("ftacp", sup, p), v, "A", vos_a=VOS, vos_s=VOS, trim=ta, cvvca=c, pan=p)
                              for p, c in zip(FT_PANS, cvs)])
            g = [np.interp(FT_PANS, PANS, x) for x in (gl, gr)]
            fig.update(a_x=theta(*g), a_st=on_cp - off)
    # B: R pair 1 mV from the L pair (the trim, shared on vin2, nulls L only)
    tb = trim_null(f"b{sup}", v, "B", dict(cvvca=V33, cvr=0.0), dict(cvvca=0.0, cvr=0.0), vos_b=VOS)
    o00 = np.array(dc(tagname("ftb", sup, "00"), v, "B", vos_b=VOS, trim=tb, cvvca=0.0, cvr=0.0))
    o10 = np.array(dc(tagname("ftb", sup, "10"), v, "B", vos_b=VOS, trim=tb, cvvca=V33, cvr=0.0))
    o01 = np.array(dc(tagname("ftb", sup, "01"), v, "B", vos_b=VOS, trim=tb, cvvca=0.0, cvr=V33))
    o11 = np.array(dc(tagname("ftb", sup, "11"), v, "B", vos_b=VOS, trim=tb, cvvca=V33, cvr=V33))
    r_step, l_step = o01[1] - o00[1], o10[0] - o00[0]
    print(f"  feedthrough B (R pair 1 mV from the L pair; trim {tb:.3f} V nulls L): R step {r_step * 1e3:+.1f} mV "
          f"({rel(r_step):.1f} dB re full peak), with L open {(o11 - o10)[1] * 1e3:+.1f} mV; L step "
          f"{l_step * 1e3:+.3f} mV; cross: L moves {(o01 - o00)[0] * 1e3:+.2f} mV when R opens, R moves "
          f"{(o10 - o00)[1] * 1e3:+.2f} mV when L opens")
    for q, x in (("ft_trim_v", tb), ("ft_r_step_mv", r_step * 1e3), ("ft_r_step_db", rel(r_step)),
                 ("ft_r_step_lopen_mv", (o11 - o10)[1] * 1e3), ("ft_l_step_mv", l_step * 1e3),
                 ("ft_cross_l_mv", (o01 - o00)[0] * 1e3), ("ft_cross_r_mv", (o10 - o00)[1] * 1e3)):
        add("B", sup, q, x)
    if sup == "5V0":
        rs = np.array([dc(tagname("ftbr", sup, c), v, "B", vos_b=VOS, trim=tb, cvvca=0.0, cvr=c)[1] for c in CVS])
        th = np.linspace(0, 1, 21)
        cr = [inv(CVS, fr / gbr, np.sin(t * np.pi / 2)) for t in th]
        fig.update(b_x=th, b_st=np.interp(cr, (0.0,) + CVS, np.r_[o00[1], rs]) - o00[1], pk=pk)

    # ---- 6. supply rejection
    for c, (var, kw) in (("M", ("M", {})), ("A", ("A", dict(pan=pc))), ("B", ("B", {}))):
        d = acrun(tagname("psrr", sup, c), v, var, outs(var), vp_ac=1, cvcut=V33 / 2, saw="DC 0 AC 0", **kw)
        for o in outs(var):
            p3 = [db(at(d, f"vm({o})", f)) for f in (100, 1e3, 1e4)]
            ch = "L" if o == "lineout" else "R"
            print(f"  supply -> line out {c} {ch} (100 Hz, 1 kHz, 10 kHz): " + " ".join(f"{x:.1f}" for x in p3) + " dB")
            for f, x in zip((100, 1000, 10000), p3):
                add(c, sup, f"psrr_db_{f}hz_{ch}", x)

    # ---- 8. PWM CV ripple at the outputs (with the 1 mV offsets; no audio)
    d = acrun(tagname("ripa", sup), v, "A", ["vbr", "lineout", "lineoutr"], fmin=1e3, fmax=1e6, ppd=20, pan_ac=1,
              vos_a=VOS, vos_s=VOS, trim=ta0, pan=pc, saw="DC 0 AC 0")
    for f, amp, nm in ((F_CAR, A_CAR, "car"), (F_DITH, A_DITH, "dith")):
        vb = at(d, "vm(vbr)", f) * amp
        am = vb * 0.5 / VT / 2                                        # AM sideband re the signal at the centre
        ol, orr = at(d, "vm(lineout)", f) * amp, at(d, "vm(lineoutr)", f) * amp
        print(f"  A pan PWM {f / 1e3:.2f} kHz ({amp * 1e3:.1f} mV pk at the pin): VBR {vb * 1e6:.1f} uV pk, AM "
              f"sidebands {db(am):.0f} dB re the signal; at the line outs L {ol * 1e6:.2f} uV, R {orr * 1e6:.2f} uV pk")
        add("A", sup, f"rip_{nm}_vbr_uv", vb * 1e6), add("A", sup, f"rip_{nm}_am_db", db(am))
        add("A", sup, f"rip_{nm}_out_uv", max(ol, orr) * 1e6)
    xw = opv(tagname("xw", sup), v, ["xw"], "B", cvvca=cvl_c, cvr=cvr_c)[0]["xw"]
    d = acrun(tagname("ripb", sup), v, "B", ["xw", "lineoutr"], fmin=1e3, fmax=1e6, ppd=20, cvr_ac=1, vos_b=VOS,
              trim=tb, cvvca=cvl_c, cvr=cvr_c, saw="DC 0 AC 0")
    for f, amp, nm in ((F_CAR, A_CAR, "car"), (F_DITH, A_DITH, "dith")):
        vx = at(d, "vm(xw)", f) * amp
        o = at(d, "vm(lineoutr)", f) * amp
        print(f"  B R-level PWM {f / 1e3:.2f} kHz: xw {vx * 1e6:.1f} uV pk (AM sidebands {db(vx / xw / 2):.0f} dB re "
              f"the signal); at the R line out {o * 1e6:.2f} uV pk ({db(o / pk):.0f} dB re full peak)")
        add("B", sup, f"rip_{nm}_xw_uv", vx * 1e6), add("B", sup, f"rip_{nm}_am_db", db(vx / xw / 2))
        add("B", sup, f"rip_{nm}_out_uv", o * 1e6)
    d = acrun(tagname("ripm", sup), v, "M", ["xv", "lineout"], fmin=1e3, fmax=1e6, ppd=20, cvv_ac=1,
              vos_a=VOS, trim=tm, saw="DC 0 AC 0")
    o = at(d, "vm(lineout)", F_TIM1) * A_CAR
    print(f"  today: CV_VCA PWM 46.9 kHz: xv {at(d, 'vm(xv)', F_TIM1) * A_CAR * 1e6:.1f} uV pk, line out "
          f"{o * 1e6:.2f} uV pk (trimmed)")
    add("M", sup, "rip_tim1_xv_uv", at(d, "vm(xv)", F_TIM1) * A_CAR * 1e6), add("M", sup, "rip_tim1_out_uv", o * 1e6)


def figure(g):
    """(a) A's pan law at 5 V: linear (VCA full) and constant power with the VCA correction, all in dB re today's
    mono gain; (b) the step at the outputs when the VCA opens (no audio), constant-power settings, 1 mV offsets."""
    f, ax = ps.fig(2, 1, aspect=0.75)
    x = g["pans"] * 100
    ax[0].plot(x, db(g["gl"]), "--", color=ps.C[0], label="L, VCA full (linear law)")
    ax[0].plot(x, db(g["gr"]), "--", color=ps.C[1], label="R, VCA full")
    ax[0].plot(x, db(g["gl"] * g["s"]), "-", color=ps.C[0], label="L, constant power")
    ax[0].plot(x, db(g["gr"] * g["s"]), "-", color=ps.C[1], label="R, constant power")
    ax[0].plot(x, db(g["s"]), ":", color=ps.C[6], label="VCA correction (CV_VCA)")
    ax[0].set(xlabel="pan PWM duty on PC5 [%]", ylabel="gain re today's line out [dB]", ylim=(-50, 6), xlim=(0, 100))
    ax[0].legend(loc="lower center", fontsize=6.5)
    ax[1].plot(g["a_x"], g["a_st"][:, 0] * 1e3, "o-", color=ps.C[0], label="A: L (steering pairs 1 mV apart)")
    ax[1].plot(g["a_x"], g["a_st"][:, 1] * 1e3, "s-", color=ps.C[1], label="A: R")
    ax[1].plot(g["b_x"], g["b_st"] * 1e3, "^-", color=ps.C[2], label="B: R (R pair 1 mV, untrimmed)")
    ax[1].axhline(0, color="0.5", lw=0.6)
    ax[1].set(xlabel="pan position (0 = left, 1 = right)",
              ylabel="step at the line out [mV]", xlim=(0, 1), ylim=(-90, 75))
    ax[1].legend(loc="upper center", fontsize=6.5)
    ps.label_panels(ax)
    f.tight_layout()
    ps.save(f, "s13_pan")


def main():
    os.makedirs(OUT, exist_ok=True)
    rows, fig = [], {}
    add = lambda var, sup, q, x: rows.append([var, sup, q, round(float(x), 4) if np.isfinite(x) else x])
    for sup, v in SUP.items():
        study(sup, v, add, fig)
    for var, parts in (("A", PARTS_A), ("B", PARTS_B)):
        n, a = area(parts)
        print(f"{var}: {n} added parts, {a:.0f} mm^2 of courtyards (0603 passives); " +
              ", ".join(f"{p[4]} x {p[1]} {p[2]} ({p[3]})" for p in parts))
        add(var, "-", "parts_added", n), add(var, "-", "area_mm2", a)
        add(var, "-", "area_pct_of_50x50", a / 2500 * 100)
    print("A: changed values: " + ", ".join(f"{r} {a} -> {b} ({c})" for r, a, b, c in CHANGED_A))
    ps.save_csv("s13_pan", ["variant", "supply", "quantity", "value"], rows)
    np.save(os.path.join(OUT, "fig.npy"), fig, allow_pickle=True)
    figure(fig)


if __name__ == "__main__":
    main()


