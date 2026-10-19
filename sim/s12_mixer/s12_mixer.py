"""S12 - the stereo mixer of the TouchSynth Poly backplane (single 5 V, MCP6002, CJ431 2.5 V reference).

Topology, per channel (L, R): an inverting summing amplifier biased on VREF = 2.5 V (CJ431 fed by 2.2k from the
5 V, RC 10k / 10 uF, MCP6002 follower). Each slot k feeds both channels through two resistors (fixed pan position,
constant-power law): AUDIO_OUT_k -> C_in (10 uF, backplane) -> R_kL -> L summing node, -> R_kR -> R summing node.
The input capacitor keeps the mixer's DC independent of the card: the card as built (hw/voice.py, S10 v5c) has a
100k line-out bleeder to its ground, which would otherwise pull DC from the 2.5 V summing nodes (simulated: the
output moves from 2.5 V to 4.05 V with 8 cards).

Pseudo-differential input: the + input of each summing amplifier gets a mirror of its - network, referenced to
the cards' AUDIO_GND instead of their AUDIO_OUT: AUDIO_GND_k -> C'_k (4.7 uF, the mirror of the card's 10 uF in
series with C_in) -> node Y_k -> R_kL -> L + input, -> R_kR -> R + input; Rf' || Cf' (= Rf || Cf) from the + input
to VREF. Then out = VREF - sum_k g_k (AUDIO_OUT_k - AUDIO_GND_k) with g_k = Rf / R_k, for any set of populated
slots (an empty slot drops out of both networks at once), and the DC stays at VREF (both sides AC coupled).
Alternative ("shared"): one mirror capacitor per channel (AUDIO_GND_k -> R_k -> node X -> 10 uF -> + input) saves
six capacitors but matches the cards' coupling time constants only on average (worse below ~1 kHz).
The op-amps run from the 5 V through 47R + 22 uF (supply rejection); the CJ431 is fed from the 5 V directly.
Output: 220R + 10 uF to the 3.5 mm jack (100k bleed); test load 10k + 1 nF cable. ADC tap: divider 15k / 27k
(0...5 V -> 0...3.2 V, VREF -> 1.61 V) with 330 pF C0G to ground, into the CH32V203's ADC1 / ADC2.

The card is modelled as an ideal source behind its output impedance (closed-loop op-amp + 100R isolation, from an
AC run of the S10 core), its 10 uF output capacitor and its 100k bleeder; the card's level (DAC full scale, VCA
open) and noise come from S10 (variant v5c, the card as built, else v5m / v5r). Op-amps: Microchip's MCP6001
macromodel for the
nominal runs (licensed for Microchip parts only, so it stays in temp/, see s10_5v.py; one netlist per circuit, its
operating point does not converge reliably with many copies; Gear integration in the transients), the behavioural
OPB for the tolerance copies (many circuit copies in one netlist).

Tests: pan law and gains, DC operating point, headroom (1...8 cards in phase, transient THD, swing into the load),
frequency response, noise (20 Hz - 20 kHz, unweighted and A-weighted; 1 and 8 cards), ground rejection of the
pseudo-differential input (1 % resistors worst case and Monte Carlo, +-20 % capacitor mismatch, against a shared
mirror capacitor and no compensation), crosstalk (slot to slot, L to R, empty slots), ADC path (alias frequencies of
the DAC carrier, anti-alias attenuation, level, noise against the quantisation), supply current and rejection.

Two-bus variant ("--bus2", for the stereo cards of S13; VREF there from the controller's +3V3 instead of the CJ431:
divider 10k / 27k with 10 uF and a second stage 10k / 10 uF, unbuffered, 2.41 V; compared with one RC stage and with
the CJ431 + follower in section 9 of the run): each card has two outputs, AUDIO_L (pin 5) and AUDIO_R
(pin 7), each the card's difference amp -> 100R -> 10 uF -> 100k bleeder to the card's ground, plus AUDIO_GND
(pin 6). The pan is on the card (S13 variant A: L = alpha I, R = (1 - alpha) I, the firmware raises CV_VCA towards
the centre for constant power and caps it at 70.6 % at hard pan), so the mixer has no fixed pan: every slot feeds
AUDIO_L_k -> 10 uF -> 56k -> L sum and AUDIO_R_k -> 10 uF -> 56k -> R sum, Rf 20k || 47 pF (0.357 per card).
Mirror network, one capacitor per slot shared by L and R: AUDIO_GND_k -> C_G -> Y_k -> 56k to each + input. Each
mirror branch then sees C_G / 2, so C_G = 10 uF mirrors the card's 10 uF in series with C_in (5 uF per channel);
the 4.7 uF of the one-output mixer would mirror only 2.35 uF per channel (compared here, with one 4.7 uF per slot and
channel as a third option). Card levels and noise come from docs/results/s13_pan.csv. Same tests as above for the
worst cases of the stereo card (8 cards hard left at the capped level, 8 cards in the centre).

  python s12_mixer.py         results: docs/results/s12_mixer.csv, docs/figures/s12_mixer.(pdf|png)
  python s12_mixer.py --bus2  results: docs/results/s12_mixer_2bus.csv, docs/figures/s12_mixer_2bus.(pdf|png)
"""
import csv, os, re, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "s10_5v"), os.path.join(HERE, "..", "lib")]
import s10_5v as T                                        # noqa: E402
import spice                                              # noqa: E402
import plotstyle as ps                                    # noqa: E402

ROOT = os.path.join(HERE, "..", "..")
OUT = os.path.join(HERE, "out")
OUT_M = os.path.join(OUT, "mcp")
VM = T.VARIANTS.get("v5m")                                # vendor model variant (None if not installed)
VB = T.VARIANTS["v5r"]
VC = T.VARIANTS.get("v5c")                                # the voice card as built (hw/voice.py), if S10 has it
CARDV = VC or VM or VB
OA_N = "MCP6001" if VM else "OPB"                          # op-amp of the nominal runs
N = 8                                                     # slots
RF = 20e3                                                 # feedback resistor (= Rf' on the + side)
CF = 47e-12                                               # feedback capacitor (C0G), fc 169 kHz
GSUM = 2.8                                                # sum of the gains per channel: 8 cards x 0.35
SPREAD = 0.75                                             # pan spread: 1 = hard left ... hard right
CCARD = 10e-6                                             # card's output capacitor (S10: COUT)
CIN = 10e-6                                               # mixer input capacitor per slot (backplane)
CARD = dict(ro=1.0, l=0.29e-3, vdc=2.4, bleed=None)       # card output stage, filled from S10 in main()
CG = 4.7e-6                                               # mirror capacitor per slot (variant "card"): the card's
                                                          # 10 uF in series with the mixer's 10 uF input C
CX = 10e-6                                                # shared mirror capacitor per channel (variant "shared")
VARIANT = "card"                                          # proposed pseudo-differential input (mirror C per slot)
R_SUP, C_SUP = 47, 22e-6                                  # op-amp rail filter from the 5 V
R_LO, C_LO, R_BLEED, R_LOAD, C_CABLE = 220, 10e-6, 100e3, 10e3, 1e-9
R_A1, R_A2, C_A = 15e3, 27e3, 330e-12                     # ADC divider and anti-alias capacitor
R_K431, Z_KA = 2.2e3, 0.2                                 # CJ431 feed resistor, dynamic impedance (typ.)
EN_431 = 300e-9                                           # assumed CJ431 noise density [V/rtHz] (not specified)
R_RF, C_RF = 10e3, 10e-6                                  # reference filter
R_VA, R_VB, C_VR = 10e3, 27e3, 10e-6                      # two-bus VREF from the MCU's +3V3: 2.41 V, 2.2 Hz
R_VC, C_VR2 = 10e3, 10e-6                                 # second RC stage ("v33rc2"): 1.6 Hz
V33, LDO_PSRR_DB = 3.3, 50.0                              # XC6206 ripple rejection, assumed flat (datasheet: about
                                                          # 50 dB at 1 kHz, not read here); its noise is left out
FS_ADC = 384e3                                            # proposed ADC rate (8 x 48 kHz)
F_CAR = 187.5e3                                           # voice DAC carrier
VDDA, NBIT = 3.3, 12
TOL_R, TOL_C = 0.01, 0.20
FREQS = (20, 50, 100, 1e3, 1e4, 2e4)


# ------------------------------------------------------------------ inputs from S10 and the parts list
def s10_value(q):
    rows = list(csv.reader(open(os.path.join(ps.DATADIR, "s10_5v.csv"))))
    val = {(r[0], r[1]): float(r[2]) for r in rows[1:]}
    for tag in ("v5c", "v5m", "v5r"):
        if (tag, q) in val:
            return val[(tag, q)]


CARD_VPP = s10_value("lineout_vpp_drive2.0")              # card full level: DAC full scale, VCA open [Vpp]
CARD_NZ = s10_value("noise_uv_cv5.0") * 1e-6              # card's line-out noise 20 Hz - 20 kHz [V rms]


E24 = (1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5,
       8.2, 9.1)


def parts():
    """0603 1 % resistors of the JLCPCB Basic / Promotional Extended lists: {ohms: (lcsc, library)}."""
    out = {}
    with open(os.path.join(ROOT, "parts", "jlcpcb_basic_and_promotional_parts.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["category"] != "Chip Resistor - Surface Mount" or r["package"] != "0603":
                continue
            a = dict(kv.split("=", 1) for kv in r["attributes"].split("; ") if "=" in kv)
            m = re.match(r"([\d.]+)([kM]?)", a.get("Resistance", ""))
            if a.get("Tolerance") != "±1%" or not m:
                continue
            v = float(m.group(1)) * {"": 1, "k": 1e3, "M": 1e6}[m.group(2)]
            if v <= 0 or round(v / 10 ** np.floor(np.log10(v)), 2) not in E24:
                continue
            if v not in out or r["library"] == "basic":
                out[v] = (r["lcsc"], r["library"])
    return out


RES = parts()


def pick(r):
    return min(RES, key=lambda v: abs(np.log(v / r)))


def pan():
    """Constant-power pan law: slot k at angle theta_k, g_L = A cos, g_R = A sin; sum of g per channel = GSUM."""
    th = np.pi / 4 * (1 + SPREAD * (2 * np.arange(N) / (N - 1) - 1))
    a = GSUM / np.cos(th).sum()
    rl = [pick(RF / (a * np.cos(t))) for t in th]
    rr = [pick(RF / (a * np.sin(t))) for t in th]
    return th, a, rl, rr


TH, A_PAN, RL, RR = pan()
GL, GR = RF / np.array(RL), RF / np.array(RR)


# ------------------------------------------------------------------ card output impedance (S10 core)
def card_zout():
    """Card output impedance before its 10 uF (closed-loop MCP6002 difference amp, plus RISO on the as-built card),
    from the S10 core: 1 A AC injected there, the line-out node left open."""
    v = CARDV
    s = T.core(v, cvcut=5.0 * T.fs(v), cvres=0.0, cvvca=5.0 * T.fs(v), saw="DC 0 AC 0")
    node = "vco" if v.get("card") else "vcaout"
    s = s.replace("RLOAD lineout 0 10k", "RLOAD lineout 0 1G").replace("RBL lineout 0 100k", "RBL lineout 0 1G")
    s += f"IZ 0 {node} DC 0 AC 1\n"
    net = (f"* S12 card output impedance\n{T.head(v)}\n{s}\n{spice.CTRL_HEAD}\nop\nprint v(vcaout)\n"
           f"ac dec 10 10 100k\nwrdata {{OUT}}/s12_zout.dat vr({node}) vi({node})\n.endc\n.end\n")
    log = spice.run(net, wdir(v.get("vendor")), "s12_zout")
    vdc = float(re.search(r"v\(vcaout\)\s*=\s*([-\d.e+]+)", log).group(1))
    d = spice.load(os.path.join(wdir(v.get("vendor")), "s12_zout.dat"))
    z = d[f"vr({node})"] + 1j * d[f"vi({node})"]
    return vdc, at(d["frequency"], z, 1e3), at(d["frequency"], z, 2e4)


def wdir(vendor):
    if vendor:
        os.makedirs(OUT_M, exist_ok=True)
        with open(os.path.join(OUT_M, ".spiceinit"), "w", newline="\n") as fh:
            fh.write("set ngbehavior=ps\n")
        return OUT_M
    os.makedirs(OUT, exist_ok=True)
    return OUT


# ------------------------------------------------------------------ netlist
def nominal(**kw):
    c = dict(pop=list(range(N)), sig={}, gnd={}, rl=list(RL), rr=list(RR), rlp=list(RL), rrp=list(RR), ref="cj431",
             vdd=5.0,
             rf={"l": RF, "r": RF}, rfp={"l": RF, "r": RF}, cf=CF, cg=[CG] * N, cc=[CCARD] * N, cx={"l": CX, "r": CX}, variant=VARIANT,
             cin=[CIN] * N, incap=True, oa=OA_N, ideal_ref=False, bleed=CARD["bleed"], vdd_ac=0, inj=0,
             noise=False, vdc_card=CARD["vdc"], ro=CARD["ro"], zl=CARD["l"])
    c.update(kw)
    return c


def supply_ref(n, c):
    """Op-amp rail and VREF, shared by both bus variants. ref 'cj431': CJ431 from the 5 V, RC, MCP6002 follower +
    spare half; 'v33': divider 10k / 27k from the controller's +3V3 (XC6206 LDO) with 10 uF, unbuffered (the + inputs
    are VREF's only DC load)."""
    oa, s = c["oa"], []
    nz = c["noise"] and oa == "OPB"                         # behavioural op-amp: input noise as a resistor
    s += [f"VDD{n} v5_{n} 0 DC {c['vdd']} AC {c['vdd_ac']}", f"RSUP{n} v5_{n} va_{n} {R_SUP}",
          f"CSUP{n} va_{n} 0 {C_SUP:.3g}"]                # op-amp rail; the CJ431 is fed from the 5 V
    if c["ideal_ref"]:
        s.append(f"VREFI{n} vref_{n} 0 2.5")
    elif c["ref"] in ("v33", "v33rc2"):                     # v33_ac: ripple on the +3V3 rail itself (MCU load)
        vd = f"vrd_{n}" if c["ref"] == "v33rc2" else f"vref_{n}"
        s += [f"V33{n} v33_{n} 0 DC {V33} AC {c['vdd_ac'] * 10 ** (-LDO_PSRR_DB / 20) + c.get('v33_ac', 0):.4g}",
              f"RVA{n} v33_{n} {vd} {R_VA:.0f}", f"RVB{n} {vd} 0 {R_VB:.0f}", f"CVR{n} {vd} 0 {C_VR:.3g}"]
        if c["ref"] == "v33rc2":
            s += [f"RVC{n} {vd} vref_{n} {R_VC:.0f}", f"CVRB{n} vref_{n} 0 {C_VR2:.3g}"]
    else:
        s += [f"B431{n} k431_{n} 0 V=2.5+{Z_KA / R_K431:.4g}*(v(v5_{n})-5)",
              f"RNZK{n} nzk_{n} 0 {T.rn(EN_431):.4g}", f"ENZK{n} k431n_{n} k431_{n} nzk_{n} 0 1",
              f"RRF{n} k431n_{n} vraw_{n} {R_RF:.0f}", f"CRF{n} vraw_{n} 0 {C_RF:.3g}"]
        xin = f"vraw_{n}"
        if nz:
            s.append(f"RNZR{n} vraw_{n} vrawz_{n} {T.rn(28e-9):.0f}")
            xin = f"vrawz_{n}"
        s += [f"XREF{n} {xin} vref_{n} va_{n} 0 vref_{n} {oa}",
              f"XSPARE{n} vref_{n} spo_{n} va_{n} 0 spo_{n} {oa}",
              f"RK431{n} v5_{n} k431i_{n} {R_K431:.0f}",     # CJ431 bias current (only for the supply current)
              f"VK431{n} k431i_{n} 0 2.5"]
    return s


def out_stage(n, c, ch):
    """Summing amplifier of channel ch (+ side Rf' || Cf' to VREF), line out (220R, 10 uF, bleeder, 10k + 1 nF
    test load) and the ADC tap (15k / 27k, 330 pF), shared by both bus variants."""
    oa = c["oa"]
    pin = f"p{ch}_{n}"
    s = []
    if c["noise"] and oa == "OPB":
        s.append(f"RNZ{ch}{n} p{ch}_{n} pz{ch}_{n} {T.rn(28e-9):.0f}")
        pin = f"pz{ch}_{n}"
    s += [f"X{ch}{n} {pin} n{ch}_{n} va_{n} 0 o{ch}_{n} {oa}",
          f"RF{ch}{n} o{ch}_{n} n{ch}_{n} {c['rf'][ch]:.6g}", f"CF{ch}{n} o{ch}_{n} n{ch}_{n} {c['cf']:.4g}",
          f"RFP{ch}{n} vref_{n} p{ch}_{n} {c['rfp'][ch]:.6g}", f"CFP{ch}{n} vref_{n} p{ch}_{n} {c['cf']:.4g}",
          f"ROS{ch}{n} o{ch}_{n} lo{ch}_{n} {R_LO}", f"COL{ch}{n} lo{ch}_{n} j{ch}_{n} {C_LO:.3g}",
          f"RBL{ch}{n} j{ch}_{n} 0 {R_BLEED:.0f}", f"RLD{ch}{n} j{ch}_{n} 0 {R_LOAD:.0f} noisy=0",
          f"CCB{ch}{n} j{ch}_{n} 0 {C_CABLE:.3g}",
          f"RA1{ch}{n} o{ch}_{n} a{ch}_{n} {R_A1:.0f}", f"RA2{ch}{n} a{ch}_{n} 0 {R_A2:.0f}",
          f"CA{ch}{n} a{ch}_{n} 0 {C_A:.3g}"]
    return s


def build(n, c):
    """One complete copy (cards + mixer), nodes suffixed _n."""
    if c.get("bus2"):
        return build2(n, c)
    s = [f"* ---- copy {n}"] + supply_ref(n, c)
    for k in range(N):
        if k in c["pop"]:                                  # card: source behind R + L (closed-loop Zout), 10 uF
            sig = c["sig"].get(k, 0)
            src = f"DC {c['vdc_card']} SIN({c['vdc_card']} {sig[1]} 1k) AC 0" if isinstance(sig, tuple) else \
                f"DC {c['vdc_card']} AC {sig}"
            s += [f"VG{k}_{n} g{k}_{n} 0 DC 0 AC {c['gnd'].get(k, 0)}", f"VS{k}_{n} s{k}_{n} g{k}_{n} {src}",
                  f"RO{k}_{n} s{k}_{n} so{k}_{n} {c['ro']:.4g} noisy=0",
                  f"LO{k}_{n} so{k}_{n} sl{k}_{n} {c['zl']:.3g}",
                  f"CC{k}_{n} sl{k}_{n} ao{k}_{n} {c['cc'][k]:.4g}"]
            ag = f"g{k}_{n}"
            if c["bleed"]:
                s.append(f"RBC{k}_{n} ao{k}_{n} g{k}_{n} {c['bleed']:.4g} noisy=0")   # card's line-out bleeder
            elif c["incap"]:                               # no bleeder: leakage keeps the node between the Cs defined
                s.append(f"RBC{k}_{n} ao{k}_{n} g{k}_{n} 1G noisy=0")
            if c["incap"]:                                 # mixer input capacitor (backplane)
                s.append(f"CIN{k}_{n} ao{k}_{n} ai{k}_{n} {c['cin'][k]:.4g}")
        else:                                              # empty slot: AUDIO_OUT and AUDIO_GND pins open (the
            ag = None                                      # mirror C' of variant "card" then carries nothing)

        for ch, rv, rvp in (("l", c["rl"][k], c["rlp"][k]), ("r", c["rr"][k], c["rrp"][k])):
            pin = f"ai{k}_{n}" if c["incap"] else f"ao{k}_{n}"   # empty slot: the open pin's C carries nothing
            s.append(f"RI{ch}{k}_{n} {pin} n{ch}_{n} {rv:.6g}")
            if c["variant"] == "card":
                s.append(f"RP{ch}{k}_{n} y{k}_{n} p{ch}_{n} {rvp:.6g}")
            elif c["variant"] == "shared":                 # empty slot: R'_kL and R'_kR in series, X_L to X_R
                s.append(f"RP{ch}{k}_{n} {ag or f'ag{k}_{n}'} x{ch}_{n} {rvp:.6g}")
        if c["variant"] == "card" and ag:
            s.append(f"CG{k}_{n} {ag} y{k}_{n} {c['cg'][k]:.4g}")
    for ch in ("l", "r"):
        s += out_stage(n, c, ch)
        if c["variant"] == "shared":
            s += [f"CX{ch}{n} x{ch}_{n} p{ch}_{n} {c['cx'][ch]:.3g}", f"RXG{ch}{n} x{ch}_{n} 0 1G"]
    if c["inj"]:                                           # L -> R test: a source into the L summing node only
        s += [f"VINJ{n} inj_{n} vref_{n} DC 0 AC {c['inj']}", f"RINJ{n} inj_{n} cinj_{n} 1",
              f"CINJ{n} cinj_{n} ninjx_{n} 10u", f"RINJ2{n} ninjx_{n} nl_{n} {RF / 0.5:.0f}"]
    return "\n".join(s) + "\n"


def netlist(name, copies, vendor, ctrl):
    head = T.head(VM) if vendor else T.head(VB)
    body = "".join(build(n, c) for n, c in enumerate(copies))
    return f"* S12 {name}\n{head}\n{body}\n{spice.CTRL_HEAD}\n{ctrl}\n.endc\n.end\n"


def ac(name, copies, nodes, vendor, fmin=10, fmax=1e6, ppd=20):
    """AC run of all copies; returns frequency and {(copy, node): complex array}. With the vendor model each copy
    runs as its own netlist (its operating point does not converge reliably with many copies in one)."""
    vend = vendor and VM is not None
    if vend and len(copies) > 1:
        res = {}
        for n, c in enumerate(copies):
            f, r = ac(f"{name}_c{n}", [c], nodes, vendor, fmin, fmax, ppd)
            res.update({(n, nd): v for (_, nd), v in r.items()})
        return f, res
    vecs = [f"{p}({nd}_{n})" for n in range(len(copies)) for nd in nodes for p in ("vr", "vi")]
    ctrl = f"ac dec {ppd} {fmin} {fmax}\n"
    chunks = [vecs[i:i + 40] for i in range(0, len(vecs), 40)]
    for i, ch in enumerate(chunks):
        ctrl += f"wrdata {{OUT}}/{name}_{i}.dat {' '.join(ch)}\n"
    spice.run(netlist(name, copies, vend, ctrl), wdir(vend), name)
    res, f = {}, None
    for i in range(len(chunks)):
        d = spice.load(os.path.join(wdir(vend), f"{name}_{i}.dat"))
        f = d["frequency"]
        for k, v in d.items():
            m = re.match(r"vr\((\w+)_(\d+)\)", k)
            if m:
                res[(int(m.group(2)), m.group(1))] = v + 1j * d[k.replace("vr(", "vi(")]
    return f, res


def at(f, y, f0):
    """Complex value at f0 (log interpolation of the real and imaginary parts)."""
    lf = np.log10(f)
    return np.interp(np.log10(f0), lf, y.real) + 1j * np.interp(np.log10(f0), lf, y.imag)


def db(x):
    return 20 * np.log10(np.abs(x))


# ------------------------------------------------------------------ noise helpers
def a_weight(f):
    f2 = f ** 2
    ra = 12194 ** 2 * f2 ** 2 / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2)) * (f2 + 12194 ** 2))
    return ra * 10 ** (2.0 / 20)


def integrate(f, sp, lo=20, hi=20e3, weight=False):
    """rms of a noise density spectrum [V/rtHz] between lo and hi (log-log interpolated)."""
    g = np.geomspace(lo, hi, 4000)
    s = 10 ** np.interp(np.log10(g), np.log10(f), np.log10(sp))
    if weight:
        s = s * a_weight(g)
    return float(np.sqrt((getattr(np, "trapezoid", None) or np.trapz)(s ** 2, g)))


def noise_run(name, copy, out_node, src, vendor, fmax=20e3):
    vend = vendor and VM is not None
    ctrl = (f"noise v({out_node}_0) {src}_0 dec 40 10 {fmax:.6g}\nsetplot noise1\n"
            f"wrdata {{OUT}}/{name}.dat onoise_spectrum\n")
    spice.run(netlist(name, [copy], vend, ctrl), wdir(vend), name)
    d = spice.load(os.path.join(wdir(vend), name + ".dat"))
    return d["frequency"], d["onoise_spectrum"]


def card_noise_spectrum():
    """The card's own line-out noise spectrum (S10 core, filter open, VCA full, 10k load)."""
    v = CARDV
    net = (f"* S12 card noise\n{T.head(v)}\n{T.core(v, noise=True, cvcut=5.0 * T.fs(v), cvres=0.0, cvvca=5.0 * T.fs(v))}"
           f"\n{spice.CTRL_HEAD}\nnoise v(lineout) VSAW dec 40 10 20k\nsetplot noise1\n"
           f"wrdata {{OUT}}/s12_cardnz.dat onoise_spectrum\n.endc\n.end\n")
    spice.run(net, wdir(v.get("vendor")), "s12_cardnz")
    d = spice.load(os.path.join(wdir(v.get("vendor")), "s12_cardnz.dat"))
    return d["frequency"], d["onoise_spectrum"]


# ------------------------------------------------------------------ tests
def headroom():
    """Transient, 1 kHz sines in phase on the leftmost n cards (largest L gains), level x full level."""
    cases = [(n, 1.0) for n in (1, 2, 4, 8)] + [(8, s) for s in (1.1, 1.2, 1.25, 1.3, 1.4, 2.0)]
    ctrl = ("option method=gear\ntran 1u 5m 0 1u\nmeas tran mx MAX v(ol_0) from=3m to=5m\nmeas tran mn MIN v(ol_0) from=3m to=5m\n"
            "meas tran jx PP v(jl_0) from=3m to=5m\nmeas tran ax MAX v(al_0) from=3m to=5m\n"
            "meas tran an MIN v(al_0) from=3m to=5m\nfourier 1k v(ol_0)\n")
    out = []
    for n, s in cases:                                     # one netlist per case (the vendor model's transient
        name = f"s12_tran_n{n}_x{s:.2f}".replace(".", "p")   # stalls with many copies in one netlist)
        c = nominal(pop=list(range(n)), sig={k: ("tran", s * CARD_VPP / 2) for k in range(n)})
        log = spice.run(netlist(name, [c], VM is not None, ctrl), wdir(VM), name)
        g = lambda k: float(re.search(rf"^{k}\s*=\s*([-\d.e+]+)", log, re.M | re.I).group(1))
        out.append(dict(n=n, s=s, mx=g("mx"), mn=g("mn"), jpp=g("jx"), ax=g("ax"), an=g("an"),
                        thd=float(re.search(r"THD:\s*([\d.e+-]+)", log).group(1)), pred=s * CARD_VPP * GL[:n].sum()))
    return out


def dc_op():
    copies = [nominal(), nominal(incap=False, bleed=None), nominal(incap=False, bleed=1e6),
              nominal(incap=False, bleed=100e3)]
    nodes = ["ol", "or", "pl", "nl", "vref", "al", "ao0", "xl" if VARIANT == "shared" else "y0", "va"]
    ctrl = "op\nprint " + " ".join(f"v({nd}_{i})" for i in range(len(copies)) for nd in nodes) + " i(vdd0)\n"
    log = spice.run(netlist("s12_op", copies, VM is not None, ctrl), wdir(VM), "s12_op")
    val = {m.group(1): float(m.group(2)) for m in re.finditer(r"v\((\w+)\)\s*=\s*([-\d.e+]+)", log)}
    i0 = -float(re.search(r"i\(vdd0\)\s*=\s*([-\d.e+]+)", log, re.I).group(1))
    return val, i0


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    add = lambda q, v: rows.append([q, round(float(v), 4) if isinstance(v, (float, np.floating)) else v])
    print("op-amp model:", "Microchip MCP6001/2 (vendor)" if VM else "behavioural OPB")

    # --- card output (S10)
    vdc, z1k, z20k = card_zout()
    CARD.update(ro=max(z1k.real, 1.0), l=max(z20k.imag, 1e-3) / (2 * np.pi * 2e4), vdc=round(vdc, 3),
                bleed=100e3 if CARDV.get("card") else None)
    print(f"card ({'v5c, as built' if CARDV.get('card') else 'v5m/v5r'}): full level {CARD_VPP:.3f} Vpp, noise "
          f"{CARD_NZ * 1e6:.1f} uV; vcaout DC {vdc:.3f} V, Zout {abs(z1k):.1f} ohm @1k, {abs(z20k):.1f} ohm @20k "
          f"(R {CARD['ro']:.1f} ohm + L {CARD['l'] * 1e3:.2f} mH) behind {CCARD * 1e6:.0f} uF, line-out bleeder "
          f"{CARD['bleed']} ohm to card GND")
    add("card_full_vpp", CARD_VPP), add("card_noise_uv", CARD_NZ * 1e6), add("card_vcaout_dc_v", vdc)
    add("card_zout_ohm_1k", abs(z1k)), add("card_zout_ohm_20k", abs(z20k))

    # --- pan law and values
    print(f"pan: constant power, spread {SPREAD}, A = {A_PAN:.3f}, Rf = Rf' = {RF / 1e3:.0f}k")
    for k in range(N):
        bal = db(GL[k] / GR[k])
        print(f"  slot {k}: angle {np.degrees(TH[k]):5.1f} deg  R_L {RL[k] / 1e3:6.1f}k ({RES[RL[k]][0]})  "
              f"R_R {RR[k] / 1e3:6.1f}k ({RES[RR[k]][0]})  g_L {GL[k]:.3f} g_R {GR[k]:.3f}  L-R {bal:+.1f} dB  "
              f"power {db(np.hypot(GL[k], GR[k])):.2f} dB")
        add(f"slot{k}_rl_k", RL[k] / 1e3), add(f"slot{k}_rr_k", RR[k] / 1e3)
        add(f"slot{k}_gl", GL[k]), add(f"slot{k}_gr", GR[k]), add(f"slot{k}_balance_db", bal)
    print(f"  sum of gains: L {GL.sum():.3f}, R {GR.sum():.3f} (per card {GL.sum() / N:.3f}); noise gain with 8 "
          f"cards {1 + GL.sum():.2f}, with slot 0 alone {1 + GL[0]:.2f}")
    add("gain_sum_l", GL.sum()), add("gain_sum_r", GR.sum()), add("noise_gain_8", 1 + GL.sum())

    # --- 1. DC and headroom
    val, idd = dc_op()
    print(f"DC: out L {val['ol_0']:.4f} V, R {val['or_0']:.4f} V, VREF {val['vref_0']:.4f} V, + in {val['pl_0']:.4f},"
          f" - in {val['nl_0']:.4f}, ADC {val['al_0']:.4f} V, AUDIO_OUT pin {val['ao0_0']:.4f} V; "
          f"supply {idd * 1e3:.2f} mA")
    print(f"    without the mixer's input capacitors (card C only), out L: no bleeder {val['ol_1']:.3f} V, "
          f"1 MOhm bleeder on every card {val['ol_2']:.3f} V, 100k (as built) {val['ol_3']:.3f} V")
    for q, v in (("dc_out_l_v", val["ol_0"]), ("dc_out_r_v", val["or_0"]), ("dc_vref_v", val["vref_0"]),
                 ("dc_adc_v", val["al_0"]), ("dc_pin_v", val["ao0_0"]), ("dc_out_l_nocin_nobleed_v", val["ol_1"]),
                 ("dc_out_l_nocin_bleed1M_v", val["ol_2"]), ("dc_out_l_nocin_bleed100k_v", val["ol_3"]),
                 ("supply_ma", idd * 1e3)):
        add(q, v)
    hr = headroom()
    for h in hr:
        print(f"  {h['n']} cards x {h['s']:.2f}: L out {h['mn']:.3f} ... {h['mx']:.3f} V ({h['mx'] - h['mn']:.3f} Vpp,"
              f" linear {h['pred']:.3f}), THD {h['thd']:.3f} %, line out {h['jpp']:.3f} Vpp, ADC {h['an']:.3f} ... "
              f"{h['ax']:.3f} V")
        tag = f"n{h['n']}_x{h['s']:.2f}"
        add(f"out_vpp_{tag}", h["mx"] - h["mn"]), add(f"out_min_v_{tag}", h["mn"]), add(f"out_max_v_{tag}", h["mx"])
        add(f"thd_pct_{tag}", h["thd"]), add(f"lineout_vpp_{tag}", h["jpp"])
        add(f"adc_min_v_{tag}", h["an"]), add(f"adc_max_v_{tag}", h["ax"])
    od = [h for h in hr if h["n"] == 8 and h["s"] >= 1.0]
    s1 = next((h["s"] for h in od if h["thd"] > 1.0), np.nan)
    sw = max(h["mx"] for h in hr) - min(h["mn"] for h in hr)
    full8 = hr[3]["mx"] - hr[3]["mn"]
    print(f"  swing at 2x overdrive {sw:.3f} Vpp; 8 cards in phase {full8:.3f} Vpp -> margin to the swing "
          f"{db(sw / full8):.1f} dB; THD > 1 % from {s1}x full level")
    add("swing_vpp", sw), add("margin_8_db", db(sw / full8)), add("thd1pct_at_x", s1)

    # --- 2. frequency response, gains of every slot
    f, r = ac("s12_fr", [nominal(sig={k: 1}) for k in range(N)], ["jl", "jr", "ol", "al", "ao1"], True,
              fmin=5, fmax=2e6)
    f1, r1 = ac("s12_fr1", [nominal(pop=[0], sig={0: 1})], ["jl"], True, fmin=5, fmax=2e6)
    r[(8, "jl")] = np.interp(f, f1, r1[(0, "jl")].real) + 1j * np.interp(f, f1, r1[(0, "jl")].imag)
    ref = at(f, r[(0, "jl")], 1e3)
    fr = {x: db(at(f, r[(0, "jl")], x) / ref) for x in (20, 20e3)}
    fr1 = {x: db(at(f, r[(8, "jl")], x) / at(f, r[(8, "jl")], 1e3)) for x in (20, 20e3)}
    print(f"line out re 1 kHz (8 cards): 20 Hz {fr[20]:.2f} dB, 20 kHz {fr[20e3]:.2f} dB; 1 card: "
          f"{fr1[20]:.2f} / {fr1[20e3]:.2f} dB; peak {db(np.abs(r[(0, 'jl')]).max() / abs(ref)):.2f} dB")
    add("fr_20hz_db", fr[20]), add("fr_20khz_db", fr[20e3]), add("fr1_20hz_db", fr1[20]), add("fr1_20khz_db", fr1[20e3])
    add("fr_peak_db", db(np.abs(r[(0, "jl")]).max() / abs(ref)))
    for k in range(N):
        gl, gr = abs(at(f, r[(k, "jl")], 1e3)), abs(at(f, r[(k, "jr")], 1e3))
        add(f"slot{k}_gl_sim", gl), add(f"slot{k}_gr_sim", gr)
    # slot-to-slot: card 0 driven, voltage at slot 1's AUDIO_OUT pin
    xs = {x: db(at(f, r[(0, "ao1")], x)) for x in (1e3, 20e3)}
    print(f"slot 0 -> slot 1 pin (card present): 1 kHz {xs[1e3]:.1f} dB, 20 kHz {xs[20e3]:.1f} dB")
    add("xtalk_slot_pin_1k_db", xs[1e3]), add("xtalk_slot_pin_20k_db", xs[20e3])
    hadc = r[(0, "al")] / at(f, r[(0, "al")], 1e3)
    fig_fr = (f, db(r[(0, "jl")] / ref), db(hadc))

    # --- 3. noise
    fc_, cn = card_noise_spectrum()
    card_u, card_a = integrate(fc_, cn), integrate(fc_, cn, weight=True)
    print(f"card's own noise (S10 core): {card_u * 1e6:.1f} uV unweighted, {card_a * 1e6:.1f} uV A-weighted")
    add("card_noise_s12_uv", card_u * 1e6), add("card_noise_a_uv", card_a * 1e6)
    for tag, pop in (("1", [0]), ("8", list(range(N)))):
        fn, sp = noise_run(f"s12_nz{tag}", nominal(pop=pop, sig={0: 1}, noise=True), "jl", "vs0", True)
        mu, ma = integrate(fn, sp), integrate(fn, sp, weight=True)
        cu, ca = GL[0] * card_u, GL[0] * card_a                # one card (slot 0) at its level
        allu = np.sqrt(mu ** 2 + (GL[pop] ** 2).sum() * card_u ** 2)
        print(f"  mixer noise, {tag} card(s) populated: {mu * 1e6:.2f} uV ({ma * 1e6:.2f} uV A); slot 0's card at "
              f"the line out {cu * 1e6:.1f} uV ({ca * 1e6:.1f} uV A): mixer adds {10 * np.log10(1 + (mu / cu) ** 2):.2f} dB"
              f" ({10 * np.log10(1 + (ma / ca) ** 2):.2f} dB A); all populated cards + mixer {allu * 1e6:.1f} uV")
        add(f"mixer_noise_uv_{tag}", mu * 1e6), add(f"mixer_noise_a_uv_{tag}", ma * 1e6)
        add(f"mixer_adds_db_{tag}", 10 * np.log10(1 + (mu / cu) ** 2))
        add(f"mixer_adds_a_db_{tag}", 10 * np.log10(1 + (ma / ca) ** 2)), add(f"total_noise_uv_{tag}", allu * 1e6)
        fdens = float(10 ** np.interp(3, np.log10(fn), np.log10(sp)))
        print(f"    mixer noise density at 1 kHz {fdens * 1e9:.0f} nV/rtHz (noise gain {1 + GL[pop].sum():.2f})")
        add(f"mixer_noise_nv_1k_{tag}", fdens * 1e9)

    # --- 4. ground rejection
    gr_rows = ground(rows, add)

    # --- 5. crosstalk L -> R
    cases = [("8 cards", list(range(N))), ("4 cards", [0, 2, 4, 6]), ("no cards", [])]
    copies = [nominal(pop=p, inj=1) for _, p in cases]
    f, r = ac("s12_lr", copies, ["jl", "jr"], True)
    for i, (t, _) in enumerate(cases):
        x = {fx: db(at(f, r[(i, "jr")], fx) / at(f, r[(i, "jl")], fx)) for fx in (1e3, 1e4, 2e4)}
        print(f"L -> R crosstalk, {t}: 1 kHz {x[1e3]:.1f} dB, 10 kHz {x[1e4]:.1f} dB, 20 kHz {x[2e4]:.1f} dB")
        for fx in x:
            add(f"xtalk_lr_{t.split()[0]}cards_{fx / 1e3:g}k_db", x[fx])

    # --- 6. ADC path
    adc(rows, add, fig_fr)

    # --- 7. supply rejection
    f, r = ac("s12_psrr", [nominal(vdd_ac=1)], ["jl", "al"], True)
    p = {x: db(at(f, r[(0, "jl")], x)) for x in (100, 1e3, 1e4)}
    print(f"supply -> line out: 100 Hz {p[100]:.1f} dB, 1 kHz {p[1e3]:.1f} dB, 10 kHz {p[1e4]:.1f} dB")
    for x in p:
        add(f"psrr_db_{x:g}hz", p[x])

    ps.save_csv("s12_mixer", ["quantity", "value"], rows)
    figure(fig_fr, gr_rows)


def perturb(c, i, rel):
    """Copy of config c with element i scaled by (1 + rel). Elements: rl/rr/rlp/rrp per slot, rf/rfp per channel,
    cg/cc per slot."""
    c = {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in c.items()}
    c[i[0]][i[1]] *= 1 + rel
    return c


ELEM_R = [(k, j) for k in ("rl", "rr", "rlp", "rrp") for j in range(N)] + [(k, ch) for k in ("rf", "rfp") for ch in "lr"]
ELEM_C = {"card": [(k, j) for k in ("cg", "cin", "cc") for j in range(N)],
          "shared": [(k, j) for k in ("cin", "cc") for j in range(N)] + [("cx", ch) for ch in "lr"]}


def ground(rows, add):
    """Ground rejection: 1 V AC between card s's AUDIO_GND (its ground) and the mixer ground, all 8 slots populated.
    Rejection = output from the ground difference / output from the same signal on AUDIO_OUT (CMRR of that input).
    Sensitivities by perturbation copies (behavioural op-amp, ideal VREF), worst case = first-order bound, typical
    = median of a Monte Carlo on the linearised sensitivities (uniform +-1 %); verified by an explicit corner."""
    fx = np.array(FREQS)
    res = {}
    # nominal with the vendor model, three input variants, slot 0 (widest pan) and slot 3 (near centre)
    copies, tags = [], []
    for var in ("card", "shared", "none"):
        for s in (0, 3):
            copies += [nominal(variant=var, gnd={s: 1}), nominal(variant=var, sig={s: 1})]
            tags.append((var, s, 8))
    for s in (0, 3):
        copies += [nominal(pop=[s], gnd={s: 1}), nominal(pop=[s], sig={s: 1})]
        tags.append((VARIANT, s, 1))
    f, r = ac("s12_gnd_nom", copies, ["jl", "jr"], True, fmin=10, fmax=1e5)
    for i, (var, s, npop) in enumerate(tags):                # output re the card's signal in its louder channel
        ch = "jl" if GL[s] >= GR[s] else "jr"
        cm = np.array([max(db(at(f, r[(2 * i, c)], x) / at(f, r[(2 * i + 1, ch)], x)) for c in ("jl", "jr"))
                       for x in fx])
        res[(var, s, npop)] = cm
        print(f"ground rejection, nominal, {var:6s} mirror, slot {s}, {npop} card(s): " +
              " ".join(f"{x:g} Hz {v:6.1f}" for x, v in zip(fx, cm)) + " dB")
        for x, v in zip(fx, cm):
            add(f"gnd_rej_nom_{var}_slot{s}_{npop}c_{x:g}hz_db", v)
    # tolerances, behavioural op-amp: per slot, nominal + every element perturbed, all slots populated
    tol = {}
    rng = np.random.default_rng(12)
    for var in ("shared", "card"):
        worst_r, typ_r, worst_c = (np.full(len(fx), -300.0) for _ in range(3))
        corner = None
        for s in range(N):
            base = nominal(oa="OPB", ideal_ref=True, variant=var, gnd={s: 1})
            cps = [base, nominal(oa="OPB", ideal_ref=True, variant=var, sig={s: 1})]
            cps += [perturb(base, e, TOL_R) for e in ELEM_R] + [perturb(base, e, TOL_C) for e in ELEM_C[var]]
            f, r = ac(f"s12_gnd_tol_{var}{s}", cps, ["jl", "jr"], False, fmin=10, fmax=1e5, ppd=10)
            sig = np.maximum(*[np.abs([at(f, r[(1, ch)], x) for x in fx]) for ch in ("jl", "jr")])
            for ch in ("jl", "jr"):
                o0 = np.array([at(f, r[(0, ch)], x) for x in fx])
                sr = np.array([[at(f, r[(2 + i, ch)], x) for x in fx] for i in range(len(ELEM_R))]) - o0
                sc = np.array([[at(f, r[(2 + len(ELEM_R) + i, ch)], x) for x in fx]
                               for i in range(len(ELEM_C[var]))]) - o0
                wr = db((np.abs(o0) + np.abs(sr).sum(0)) / sig)
                eps = rng.uniform(-1, 1, (4000, len(ELEM_R)))
                tr = db(np.median(np.abs(o0 + eps @ sr), axis=0) / sig)
                wc = db((np.abs(o0) + np.abs(sr).sum(0) + np.abs(sc).sum(0)) / sig)
                if wr[3] > worst_r[3]:                      # sign pattern that adds up the deviations at 1 kHz
                    d = sr[np.argmax(np.abs(sr[:, 3])), 3]
                    for _ in range(3):
                        sgn = np.sign((sr[:, 3] * np.conj(d)).real)
                        d = o0[3] + (sgn * sr[:, 3]).sum()
                    corner = (s, ch, sgn, wr[3])
                worst_r, typ_r, worst_c = np.maximum(worst_r, wr), np.maximum(typ_r, tr), np.maximum(worst_c, wc)
        print(f"ground rejection, {var} mirror, 1 % resistors, worst slot and channel (at " +
              ", ".join(f"{x:g}" for x in fx) + " Hz):\n    worst case " + " ".join(f"{v:.1f}" for v in worst_r) +
              " dB; typical (MC median) " + " ".join(f"{v:.1f}" for v in typ_r) +
              f" dB;\n    worst case with the capacitors at +-{TOL_C * 100:.0f} % as well: " +
              " ".join(f"{v:.1f}" for v in worst_c) + " dB")
        for x, w, t, c in zip(fx, worst_r, typ_r, worst_c):
            add(f"gnd_rej_worst_1pct_{var}_{x:g}hz_db", w), add(f"gnd_rej_typ_1pct_{var}_{x:g}hz_db", t)
            add(f"gnd_rej_worst_1pct_c20pct_{var}_{x:g}hz_db", c)
        # explicit corner (resistors at +-1 % in the worst direction at 1 kHz) to check the linear bound
        s, ch, sgn, wlin = corner
        c = nominal(oa="OPB", ideal_ref=True, variant=var, gnd={s: 1})
        for e, sg in zip(ELEM_R, sgn):
            c = perturb(c, e, TOL_R * (sg if sg != 0 else 1))
        f, r = ac(f"s12_gnd_corner_{var}", [c, nominal(oa="OPB", ideal_ref=True, variant=var, sig={s: 1})],
                  ["jl", "jr"], False, fmin=10, fmax=1e5)
        wex = db(at(f, r[(0, ch)], 1e3) / max(abs(at(f, r[(1, c_)], 1e3)) for c_ in ("jl", "jr")))
        print(f"    explicit worst corner, slot {s} {ch[1].upper()}, 1 kHz: {wex:.1f} dB (linear bound {wlin:.1f} dB)")
        add(f"gnd_rej_corner_1k_{var}_db", wex)
        tol[var] = dict(worst=worst_r, typ=typ_r, worstc=worst_c)
    lev = 10e-3 * max(GL.max(), GR.max())
    w1k = tol[VARIANT]["worst"][3]
    print(f"  10 mV ground difference on slot 0: {lev * 1e3:.2f} mV at the line out without compensation, "
          f"{lev * 10 ** (w1k / 20) * 1e6:.0f} uV worst case, "
          f"{lev * 10 ** (tol[VARIANT]['typ'][3] / 20) * 1e6:.0f} uV typical at 1 kHz")
    add("gnd_10mv_uncomp_uv", lev * 1e6), add("gnd_10mv_worst_uv", lev * 10 ** (w1k / 20) * 1e6)
    add("gnd_10mv_typ_uv", lev * 10 ** (tol[VARIANT]["typ"][3] / 20) * 1e6)
    return dict(fx=fx, tol=tol, nom=res)


def adc(rows, add, fig_fr):
    f, hdb = fig_fr[0], fig_fr[2]
    h = lambda x: float(np.interp(np.log10(x), np.log10(f), hdb))
    print(f"ADC path re 1 kHz: 20 kHz {h(2e4):.2f} dB, carrier 187.5 kHz {h(F_CAR):.1f} dB, "
          f"fs - 20 kHz {h(FS_ADC - 2e4):.1f} dB, fs {h(FS_ADC):.1f} dB, 2 fs - 20 kHz {h(2 * FS_ADC - 2e4):.1f} dB")
    adcclk = 12e6                                          # PCLK2 72 MHz / 6 (fADC <= 14 MHz)
    ts = max(t for t in (1.5, 7.5, 13.5, 28.5, 41.5, 55.5, 71.5, 239.5) if t + 12.5 <= adcclk / FS_ADC)
    rain = ts / (adcclk * 8e-12 * np.log(2 ** 14)) - 1e3   # datasheet: error < 1/4 LSB, no external C
    rth = R_A1 * R_A2 / (R_A1 + R_A2)
    print(f"  ADC timing at {FS_ADC / 1e3:.0f} kHz, ADCCLK 12 MHz: {adcclk / FS_ADC:.2f} cycles per sample, sample time "
          f"{ts} cycles, R_AIN max {rain / 1e3:.1f}k (source {rth / 1e3:.2f}k, plus {C_A * 1e12:.0f} pF)")
    add("adc_ts_cycles", ts), add("adc_rain_max_k", rain / 1e3), add("adc_rsource_k", rth / 1e3)
    add("adc_20khz_db", h(2e4)), add("adc_car_db", h(F_CAR)), add("adc_alias_fs_m20k_db", h(FS_ADC - 2e4))
    add("adc_alias_2fs_m20k_db", h(2 * FS_ADC - 2e4)), add("adc_fs", FS_ADC)
    # where the carrier and its harmonics land after sampling, for candidate rates (+-0.4 kHz HSI trim spread)
    # levels at the ADC
    kdiv = R_A2 / (R_A1 + R_A2)
    one = CARD_VPP * GL[0] * kdiv
    # carrier harmonics at the ADC, one card (slot 0): S11's fundamental (-74.1 dB re full scale at the line out,
    # 50 % duty), harmonic k at most 1/k of it (PWM: |sin(k pi D)| / k), the card's 30 kHz 2-pole Butterworth
    # (S11) relative to the fundamental, and the mixer + anti-alias response simulated here
    sk = lambda x: 1 / np.sqrt(1 + (x / 30e3) ** 4)
    lev = {k: -74.1 - db(k) + db(sk(k * F_CAR) / sk(F_CAR)) + h(k * F_CAR) + db(one / VDDA) for k in range(1, 5)}
    print("  carrier harmonics at the ADC (one card, upper bound): " +
          " ".join(f"k={k}: {v:.0f} dBFS" for k, v in lev.items()))
    for k, v in lev.items():
        add(f"adc_carrier_k{k}_dbfs", v)
    print("  alias of k x 187.5 kHz (+-0.4 kHz per k) after sampling; in band if < 24 kHz:")
    for fs in (192e3, 240e3, 288e3, 336e3, 384e3, 480e3):
        al = []
        for k in range(1, 5):
            x = (k * F_CAR) % fs
            al.append(min(x, fs - x))
        bad = [k + 1 for k, a in enumerate(al) if a < 24e3 + 0.4e3 * (k + 1)]
        print(f"   fs {fs / 1e3:5.0f} kHz: " + " ".join(f"{a / 1e3:6.1f}" for a in al) + " kHz" +
              (f"   in band: k = {bad}, worst {max(lev[k] for k in bad):.0f} dBFS" if bad else ""))
        for k in range(4):
            add(f"alias_fs{fs / 1e3:.0f}k_k{k + 1}_khz", al[k] / 1e3)
    eight = CARD_VPP * GL.sum() * kdiv
    print(f"  level at the ADC: one card (slot 0) {one:.3f} Vpp = {db(one / VDDA):.1f} dBFS, 8 in phase {eight:.3f} Vpp"
          f" = {db(eight / VDDA):.1f} dBFS; divider {kdiv:.4f}")
    add("adc_divider", kdiv), add("adc_1card_dbfs", db(one / VDDA)), add("adc_8cards_dbfs", db(eight / VDDA))
    # noise at the ADC: mixer (8 cards populated) in band and folded, cards in band, quantisation
    fn, sp = noise_run("s12_nzadc", nominal(sig={0: 1}, noise=True), "al", "vs0", True, fmax=4e6)
    inb = integrate(fn, sp)
    fold = np.sqrt(sum(integrate(fn, sp, max(m * FS_ADC - 2e4, 20), min(m * FS_ADC + 2e4, 3.99e6)) ** 2
                       for m in range(1, 11)))
    card1 = GL[0] * CARD_NZ * kdiv
    q = VDDA / 2 ** NBIT / np.sqrt(12) * np.sqrt(2e4 / (FS_ADC / 2))
    sig1 = one / (2 * np.sqrt(2))
    print(f"  noise at the ADC, 20 Hz - 20 kHz: mixer {inb * 1e6:.1f} uV, folded from k fs +- 20 kHz {fold * 1e6:.1f} uV,"
          f" one card {card1 * 1e6:.1f} uV, 8 cards {card1 / GL[0] * np.sqrt((GL ** 2).sum()) * 1e6:.1f} uV; "
          f"ideal 12-bit quantisation after 8x decimation {q * 1e6:.1f} uV")
    snr1 = db(sig1 / np.sqrt(inb ** 2 + fold ** 2 + card1 ** 2 + q ** 2))
    print(f"  one card at full level through the ADC: SNR {snr1:.1f} dB (card alone {db(sig1 / card1):.1f} dB); "
          f"ADC full scale over quantisation {db(VDDA / (2 * np.sqrt(2)) / q):.1f} dB")
    add("adc_noise_mixer_uv", inb * 1e6), add("adc_noise_folded_uv", fold * 1e6), add("adc_noise_card_uv", card1 * 1e6)
    add("adc_quant_uv", q * 1e6), add("adc_snr_1card_db", snr1)


def figure(fr, g):
    import matplotlib.pyplot as plt
    fig, ax = ps.fig(2, 1, aspect=0.75)
    f, lo, ad = fr
    ax[0].semilogx(f, lo, color=ps.C[0], label="line out (10k + 1 nF)")
    ax[0].semilogx(f, ad, color=ps.C[1], label="ADC pin")
    for x, lab in ((F_CAR, "carrier"), (FS_ADC, "$f_s$")):
        ax[0].axvline(x, color="0.6", lw=0.6, ls=":")
    ax[0].set(xlabel="frequency [Hz]", ylabel="gain re 1 kHz [dB]", xlim=(5, 2e6), ylim=(-40, 3))
    ax[0].legend()
    fx, t = g["fx"], g["tol"][VARIANT]
    ax[1].semilogx(fx, g["nom"][("shared", 0, 8)], "o-", color=ps.C[0], label="nominal, shared mirror C")
    ax[1].semilogx(fx, g["nom"][("card", 0, 8)], "s:", color=ps.C[5], label="nominal, mirror C per slot")
    ax[1].semilogx(fx, t["typ"], "o-", color=ps.C[2], label="1 % resistors: typical")
    ax[1].semilogx(fx, t["worst"], "o-", color=ps.C[1], label="1 % resistors: worst case")
    ax[1].semilogx(fx, t["worstc"], "o--", color=ps.C[3], label="+ capacitors ±20 %")
    ax[1].set(xlabel="frequency [Hz]", ylabel="ground rejection [dB]", ylim=(-115, -15))
    ax[1].legend(loc="lower center", fontsize=6.5)
    ps.label_panels(ax)
    fig.tight_layout()
    ps.save(fig, "s12_mixer")


# ================================================================== two-bus variant ("--bus2"): cards with L and R outputs
RI2 = 56e3                                                # input resistor per slot and bus (= mirror resistor)
G2 = RF / RI2                                             # gain per card: 0.357
CG2 = 10e-6                                               # mirror capacitor per slot, shared by L and R (see below)
MIRROR2 = "slot"                                          # proposed mirror network
POP4 = [0, 2, 4, 6]                                       # half the slots empty
REF2 = "v33rc2"                                           # VREF from the controller's +3V3, two RC stages (main2 9.)
S13 = {}                                                  # card levels and noise from S13 (variant A, 5.0 V)


def s13_load():
    rows = list(csv.reader(open(os.path.join(ps.DATADIR, "s13_pan.csv"))))
    val = {(r[0], r[1], r[2]): float(r[3]) for r in rows[1:]}
    a = lambda q: val[("A", "5V0", q)]
    mono = val[("M", "5V0", "vpp_M_L")]                   # today's mono card, full level (= S10's 1.46 Vpp)
    S13.update(mono=mono,
               hard=mono * 10 ** (a("cp_l_db_d0.00") / 20),   # hard left, CV_VCA capped (constant power): 1.38 Vpp
               centre=a("vpp_centre_L"),                      # centre, CV_VCA full: L = R = 0.98 Vpp
               uncapped=a("vpp_hardleft_L"),                  # hard left with CV_VCA full (cap missing): 1.95 Vpp
               nz_centre=a("noise_uv_centre_L") * 1e-6, nz_hard=a("noise_uv_hardleft_L") * 1e-6,
               cap_pct=a("cp_cvvca_hardl_pct"))


def nominal2(**kw):
    """Two-bus configuration. mirror: 'slot' (one capacitor per slot on AUDIO_GND, 56k to each + input), 'chan'
    (one capacitor per slot and channel), 'none' (no mirror network, + inputs on VREF through Rf' only)."""
    c = dict(bus2=True, pop=list(range(N)), sigl={}, sigr={}, gnd={}, ril=[RI2] * N, rir=[RI2] * N, ref=REF2, vdd=5.0,
             rpl=[RI2] * N, rpr=[RI2] * N, rf={"l": RF, "r": RF}, rfp={"l": RF, "r": RF}, cf=CF, mirror=MIRROR2,
             cg=[CG2] * N, cgl=[CG] * N, cgr=[CG] * N, ccl=[CCARD] * N, ccr=[CCARD] * N, cinl=[CIN] * N,
             cinr=[CIN] * N, incap=True, oa=OA_N, ideal_ref=False, bleed=CARD["bleed"], vdd_ac=0, inj=0,
             noise=False, vdc_card=CARD["vdc"], ro=CARD["ro"], zl=CARD["l"])
    c.update(kw)
    return c


def build2(n, c):
    """One copy of the two-bus mixer: each card has two outputs (AUDIO_L, AUDIO_R), each a source behind the card's
    output impedance, its 10 uF and 100k bleeder to the card's ground (AUDIO_GND); AUDIO_x_k -> C_in -> 56k -> the
    x summing node. Empty slots: the pins are open, their C_in / 56k carry nothing (left out); with the 'slot'
    mirror the empty slot's node Y_k still links the two + inputs (56k + 56k)."""
    s = [f"* ---- copy {n} (two buses)"] + supply_ref(n, c)
    mir = c["mirror"]
    for k in range(N):
        pop = k in c["pop"]
        if pop:
            s.append(f"VG{k}_{n} g{k}_{n} 0 DC 0 AC {c['gnd'].get(k, 0)}")
        for x in "lr":
            if pop:
                sig = c["sig" + x].get(k, 0)
                src = (f"DC {c['vdc_card']} SIN({c['vdc_card']} {sig[1]} 1k) AC 0" if isinstance(sig, tuple)
                       else f"DC {c['vdc_card']} AC {sig}")
                s += [f"VS{x}{k}_{n} s{x}{k}_{n} g{k}_{n} {src}",
                      f"RO{x}{k}_{n} s{x}{k}_{n} so{x}{k}_{n} {c['ro']:.4g} noisy=0",
                      f"LO{x}{k}_{n} so{x}{k}_{n} sl{x}{k}_{n} {c['zl']:.3g}",
                      f"CC{x}{k}_{n} sl{x}{k}_{n} ao{x}{k}_{n} {c['cc' + x][k]:.4g}",
                      f"RBC{x}{k}_{n} ao{x}{k}_{n} g{k}_{n} {c['bleed'] or 1e9:.4g} noisy=0"]
                if c["incap"]:
                    s.append(f"CIN{x}{k}_{n} ao{x}{k}_{n} ai{x}{k}_{n} {c['cin' + x][k]:.4g}")
                pin = f"ai{x}{k}_{n}" if c["incap"] else f"ao{x}{k}_{n}"
                s.append(f"RI{x}{k}_{n} {pin} n{x}_{n} {c['ri' + x][k]:.6g}")
                if mir == "chan":
                    s += [f"CG{x}{k}_{n} g{k}_{n} y{x}{k}_{n} {c['cg' + x][k]:.4g}",
                          f"RP{x}{k}_{n} y{x}{k}_{n} p{x}_{n} {c['rp' + x][k]:.6g}"]
            if mir == "slot":
                s.append(f"RP{x}{k}_{n} y{k}_{n} p{x}_{n} {c['rp' + x][k]:.6g}")
        if pop and mir == "slot":
            s.append(f"CG{k}_{n} g{k}_{n} y{k}_{n} {c['cg'][k]:.4g}")
    for ch in ("l", "r"):
        s += out_stage(n, c, ch)
    if c["inj"]:                                           # L -> R test: a source into the L summing node only
        s += [f"VINJ{n} inj_{n} vref_{n} DC 0 AC {c['inj']}", f"RINJ{n} inj_{n} cinj_{n} 1",
              f"CINJ{n} cinj_{n} ninjx_{n} 10u", f"RINJ2{n} ninjx_{n} nl_{n} {RF / 0.5:.0f}"]
    return "\n".join(s) + "\n"


def headroom2(cases=None, tag="", **kw):
    """Transient, 1 kHz sines in phase. 'hard': n cards hard left at x times the capped level (S13: 1.38 Vpp),
    'centre': all 8 cards in the centre (L = R = 0.98 Vpp). kw: nominal2 settings (ref, vdd), tag: run name."""
    xu = S13["uncapped"] / S13["hard"]
    cases = cases or ([("hard", n, 1.0) for n in (1, 2, 4, 8)] + [("hard", 8, x) for x in (1.1, 1.2, 1.25, 1.3)] +
                      [("hard", 8, round(xu, 2)), ("hard", 8, 2.0), ("centre", 8, 1.0), ("centre", 8, 1.5)])
    ctrl = ("option method=gear\ntran 1u 5m 0 1u\n" +
            "".join(f"meas tran mx{c} MAX v(o{c}_0) from=3m to=5m\nmeas tran mn{c} MIN v(o{c}_0) from=3m to=5m\n"
                    f"meas tran jx{c} PP v(j{c}_0) from=3m to=5m\nmeas tran ax{c} MAX v(a{c}_0) from=3m to=5m\n"
                    f"meas tran an{c} MIN v(a{c}_0) from=3m to=5m\n" for c in "lr") +
            "fourier 1k v(ol_0)\nfourier 1k v(or_0)\n")
    out = []
    for kind, n, x in cases:
        lev = (S13["hard"] if kind == "hard" else S13["centre"]) * x / 2
        sig = {k: ("tran", lev) for k in range(n)}
        # the cards' output inductance (0.37 mH, the Zout rise to 113 ohm at 20 kHz) left out: with it the vendor
        # model's transient fails to start with more than one card populated; no effect at 1 kHz
        c = nominal2(sigl=sig, sigr=sig if kind == "centre" else {}, zl=1e-9, **kw)
        name = f"s12b_tran_{kind}_n{n}_x{x:.2f}{tag}".replace(".", "p")
        log = spice.run(netlist(name, [c], VM is not None, ctrl), wdir(VM), name)
        g = lambda k: float(re.search(rf"^{k}\s*=\s*([-\d.e+]+)", log, re.M | re.I).group(1))
        thd = [float(t) for t in re.findall(r"THD:\s*([\d.e+-]+)", log)]
        h = dict(kind=kind, n=n, x=x, thd=thd[0], thdr=thd[1] if len(thd) > 1 else np.nan, pred=2 * lev * G2 * n)
        for ch in "lr":
            h.update({f"{q}{ch}": g(f"{q}{ch}") for q in ("mx", "mn", "jx", "ax", "an")})
        out.append(h)
    return out


def dc_op2(**kw):
    copies = [nominal2(**kw), nominal2(incap=False, **kw)]
    nodes = ["ol", "or", "pl", "nl", "pr", "vref", "al", "aol0", "y0", "va"]
    ctrl = "op\nprint " + " ".join(f"v({nd}_{i})" for i in range(len(copies)) for nd in nodes) + " i(vdd0)\n"
    log = spice.run(netlist("s12b_op", copies, VM is not None, ctrl), wdir(VM), "s12b_op")
    val = {m.group(1): float(m.group(2)) for m in re.finditer(r"v\((\w+)\)\s*=\s*([-\d.e+]+)", log)}
    i0 = -float(re.search(r"i\(vdd0\)\s*=\s*([-\d.e+]+)", log, re.I).group(1))
    return val, i0


ELEM2_R = ([(k, j) for k in ("ril", "rir", "rpl", "rpr") for j in range(N)] +
           [(k, ch) for k in ("rf", "rfp") for ch in "lr"])
ELEM2_C = {"slot": [(k, j) for k in ("cg", "cinl", "cinr", "ccl", "ccr") for j in range(N)],
           "chan": [(k, j) for k in ("cgl", "cgr", "cinl", "cinr", "ccl", "ccr") for j in range(N)]}
MIR2 = {"slot10": dict(mirror="slot", cg=[10e-6] * N), "slot4u7": dict(mirror="slot", cg=[4.7e-6] * N),
        "chan4u7": dict(mirror="chan"), "none": dict(mirror="none")}


def ground2(add):
    """Ground rejection as in ground(): 1 V AC on card s's AUDIO_GND against the mixer ground, all 8 slots
    populated, relative to the same 1 V on its AUDIO_L; the larger of the two channels. Mirror variants: one 10 uF
    per slot shared by L and R (proposed), the S13 proposal's 4.7 uF per slot, 4.7 uF per slot and channel, none.
    Tolerances: perturbation copies (behavioural op-amp, ideal VREF); worst case = first-order bound, typical =
    Monte Carlo median (uniform, resistors +-1 %, and resistors + capacitors +-20 %); explicit corner check."""
    fx = np.array(FREQS)
    res = {}
    copies, tags = [], []
    for var, kw in MIR2.items():
        copies += [nominal2(gnd={0: 1}, **kw), nominal2(sigl={0: 1}, **kw)]
        tags.append((var, 8))
    for var in ("slot10", "chan4u7"):
        copies += [nominal2(pop=[0], gnd={0: 1}, **MIR2[var]), nominal2(pop=[0], sigl={0: 1}, **MIR2[var])]
        tags.append((var, 1))
    f, r = ac("s12b_gnd_nom", copies, ["jl", "jr"], True, fmin=10, fmax=1e5)
    for i, (var, npop) in enumerate(tags):
        cm = np.array([max(db(at(f, r[(2 * i, c)], x) / at(f, r[(2 * i + 1, "jl")], x)) for c in ("jl", "jr"))
                       for x in fx])
        res[(var, npop)] = cm
        print(f"ground rejection, nominal, mirror {var:7s}, slot 0, {npop} card(s): " +
              " ".join(f"{x:g} Hz {v:6.1f}" for x, v in zip(fx, cm)) + " dB")
        for x, v in zip(fx, cm):
            add(f"gnd_rej_nom_{var}_{npop}c_{x:g}hz_db", v)
    tol = {}
    rng = np.random.default_rng(12)
    for var in ("slot10", "chan4u7"):
        kw = MIR2[var]
        ec = ELEM2_C[kw["mirror"]]
        worst_r, typ_r, worst_c, typ_c = (np.full(len(fx), -300.0) for _ in range(4))
        corner = None
        for s in (0, 5):                                   # all slots alike (equal gains); two as a check
            base = nominal2(oa="OPB", ideal_ref=True, gnd={s: 1}, **kw)
            cps = [base, nominal2(oa="OPB", ideal_ref=True, sigl={s: 1}, **kw)]
            cps += [perturb(base, e, TOL_R) for e in ELEM2_R] + [perturb(base, e, TOL_C) for e in ec]
            f, r = ac(f"s12b_gnd_tol_{var}{s}", cps, ["jl", "jr"], False, fmin=10, fmax=1e5, ppd=10)
            sig = np.abs([at(f, r[(1, "jl")], x) for x in fx])
            for ch in ("jl", "jr"):
                o0 = np.array([at(f, r[(0, ch)], x) for x in fx])
                sr = np.array([[at(f, r[(2 + i, ch)], x) for x in fx] for i in range(len(ELEM2_R))]) - o0
                sc = np.array([[at(f, r[(2 + len(ELEM2_R) + i, ch)], x) for x in fx] for i in range(len(ec))]) - o0
                wr = db((np.abs(o0) + np.abs(sr).sum(0)) / sig)
                wc = db((np.abs(o0) + np.abs(sr).sum(0) + np.abs(sc).sum(0)) / sig)
                er = rng.uniform(-1, 1, (4000, len(ELEM2_R)))
                ecr = rng.uniform(-1, 1, (4000, len(ec)))
                tr = db(np.median(np.abs(o0 + er @ sr), axis=0) / sig)
                tc = db(np.median(np.abs(o0 + er @ sr + ecr @ sc), axis=0) / sig)
                if wr[3] > worst_r[3]:
                    d = sr[np.argmax(np.abs(sr[:, 3])), 3]
                    for _ in range(3):
                        sgn = np.sign((sr[:, 3] * np.conj(d)).real)
                        d = o0[3] + (sgn * sr[:, 3]).sum()
                    corner = (s, ch, sgn, wr[3])
                worst_r, typ_r = np.maximum(worst_r, wr), np.maximum(typ_r, tr)
                worst_c, typ_c = np.maximum(worst_c, wc), np.maximum(typ_c, tc)
        print(f"ground rejection, mirror {var}, worst channel (at " + ", ".join(f"{x:g}" for x in fx) + " Hz):\n"
              "    1 % resistors: worst case " + " ".join(f"{v:.1f}" for v in worst_r) + " dB, typical " +
              " ".join(f"{v:.1f}" for v in typ_r) + f" dB\n    + capacitors +-{TOL_C * 100:.0f} %: worst case " +
              " ".join(f"{v:.1f}" for v in worst_c) + " dB, typical " + " ".join(f"{v:.1f}" for v in typ_c) + " dB")
        for x, w, t, wc_, tc_ in zip(fx, worst_r, typ_r, worst_c, typ_c):
            add(f"gnd_rej_worst_1pct_{var}_{x:g}hz_db", w), add(f"gnd_rej_typ_1pct_{var}_{x:g}hz_db", t)
            add(f"gnd_rej_worst_1pct_c20pct_{var}_{x:g}hz_db", wc_)
            add(f"gnd_rej_typ_1pct_c20pct_{var}_{x:g}hz_db", tc_)
        s, ch, sgn, wlin = corner
        c = nominal2(oa="OPB", ideal_ref=True, gnd={s: 1}, **kw)
        for e, sg in zip(ELEM2_R, sgn):
            c = perturb(c, e, TOL_R * (sg if sg != 0 else 1))
        f, r = ac(f"s12b_gnd_corner_{var}", [c, nominal2(oa="OPB", ideal_ref=True, sigl={s: 1}, **kw)],
                  ["jl", "jr"], False, fmin=10, fmax=1e5)
        wex = db(at(f, r[(0, ch)], 1e3) / abs(at(f, r[(1, "jl")], 1e3)))
        print(f"    explicit worst corner, slot {s} {ch[1].upper()}, 1 kHz: {wex:.1f} dB (linear bound {wlin:.1f} dB)")
        add(f"gnd_rej_corner_1k_{var}_db", wex)
        tol[var] = dict(worst=worst_r, typ=typ_r, worstc=worst_c, typc=typ_c)
    lev = 10e-3 * G2
    t = tol["slot10"]
    print(f"  10 mV ground difference on one slot: {lev * 1e3:.2f} mV at the line out without compensation, "
          f"{lev * 10 ** (t['worst'][3] / 20) * 1e6:.0f} uV worst case, {lev * 10 ** (t['typ'][3] / 20) * 1e6:.0f} uV "
          f"typical at 1 kHz")
    add("gnd_10mv_uncomp_uv", lev * 1e6), add("gnd_10mv_worst_uv", lev * 10 ** (t["worst"][3] / 20) * 1e6)
    add("gnd_10mv_typ_uv", lev * 10 ** (t["typ"][3] / 20) * 1e6)
    return dict(fx=fx, tol=tol, nom=res)


def adc2(add, fig_fr):
    f, hdb = fig_fr[0], fig_fr[2]
    h = lambda x: float(np.interp(np.log10(x), np.log10(f), hdb))
    print(f"ADC path re 1 kHz: 20 kHz {h(2e4):.2f} dB, carrier 187.5 kHz {h(F_CAR):.1f} dB, "
          f"fs - 20 kHz {h(FS_ADC - 2e4):.1f} dB, fs {h(FS_ADC):.1f} dB, 2 fs - 20 kHz {h(2 * FS_ADC - 2e4):.1f} dB")
    add("adc_20khz_db", h(2e4)), add("adc_car_db", h(F_CAR)), add("adc_alias_fs_m20k_db", h(FS_ADC - 2e4))
    add("adc_alias_2fs_m20k_db", h(2 * FS_ADC - 2e4)), add("adc_fs", FS_ADC)
    kdiv = R_A2 / (R_A1 + R_A2)
    centre, hard = (S13[q] * G2 * kdiv for q in ("centre", "hard"))
    eight = 8 * hard
    sk = lambda x: 1 / np.sqrt(1 + (x / 30e3) ** 4)       # carrier: S11 re the mono card's full level (bound)
    lev = {k: -74.1 - db(k) + db(sk(k * F_CAR) / sk(F_CAR)) + h(k * F_CAR) + db(CARD_VPP * G2 * kdiv / VDDA)
           for k in range(1, 5)}
    print("  carrier harmonics at the ADC (one card, upper bound): " +
          " ".join(f"k={k}: {v:.0f} dBFS" for k, v in lev.items()) +
          f"; at 384 kHz they land at 187.5, 9, 178.5, 18 kHz (k = 2, 4 in band, {lev[2]:.0f} / {lev[4]:.0f} dBFS)")
    for k, v in lev.items():
        add(f"adc_carrier_k{k}_dbfs", v)
    print(f"  level at the ADC: one card centre {centre:.3f} Vpp = {db(centre / VDDA):.1f} dBFS, one card hard left "
          f"{hard:.3f} Vpp = {db(hard / VDDA):.1f} dBFS, 8 hard left in phase {eight:.3f} Vpp = "
          f"{db(eight / VDDA):.1f} dBFS")
    add("adc_divider", kdiv), add("adc_1card_centre_dbfs", db(centre / VDDA))
    add("adc_1card_hard_dbfs", db(hard / VDDA)), add("adc_8cards_hard_dbfs", db(eight / VDDA))
    fn, sp = noise_run("s12b_nzadc", nominal2(sigl={0: 1}, noise=True), "al", "vsl0", True, fmax=4e6)
    inb = integrate(fn, sp)
    fold = np.sqrt(sum(integrate(fn, sp, max(m * FS_ADC - 2e4, 20), min(m * FS_ADC + 2e4, 3.99e6)) ** 2
                       for m in range(1, 11)))
    card1 = G2 * S13["nz_centre"] * kdiv
    q = VDDA / 2 ** NBIT / np.sqrt(12) * np.sqrt(2e4 / (FS_ADC / 2))
    snr1 = db(centre / (2 * np.sqrt(2)) / np.sqrt(inb ** 2 + fold ** 2 + card1 ** 2 + q ** 2))
    print(f"  noise at the ADC, 20 Hz - 20 kHz: mixer {inb * 1e6:.1f} uV, folded {fold * 1e6:.1f} uV, one card "
          f"(centre) {card1 * 1e6:.1f} uV, quantisation {q * 1e6:.1f} uV; one card centre through the ADC: SNR "
          f"{snr1:.1f} dB")
    add("adc_noise_mixer_uv", inb * 1e6), add("adc_noise_folded_uv", fold * 1e6), add("adc_noise_card_uv", card1 * 1e6)
    add("adc_quant_uv", q * 1e6), add("adc_snr_1card_centre_db", snr1)


def pick_cap(value, vmin, tc=None, pkgs=("0603", "0805")):
    """Multilayer ceramic of the JLCPCB Basic / Promotional Extended lists (as hw/lcsc.py, not imported to keep
    hw/ untouched): basic first, then stock."""
    want = value.replace("u", "uF").replace("n", "nF").replace("p", "pF")
    rows = list(csv.DictReader(open(os.path.join(ROOT, "parts", "jlcpcb_basic_and_promotional_parts.csv"),
                                    encoding="utf-8")))
    volts = lambda s: float(re.match(r"([\d.]+)", s).group(1)) if s and re.match(r"[\d.]+", s) else 0
    for pkg in pkgs:
        c = []
        for r in rows:
            if not r["subcategory"].startswith("Multilayer") or r["package"] != pkg:
                continue
            a = dict(kv.split("=", 1) for kv in r["attributes"].split("; ") if "=" in kv)
            okt = a.get("Temperature Coefficient") in ("C0G", "NP0") if tc == "C0G" else \
                a.get("Temperature Coefficient") not in ("Y5V", "Z5U")
            if a.get("Capacitance") == want and volts(a.get("Voltage Rating")) >= vmin and okt:
                c.append(r)
        c.sort(key=lambda r: (r["library"] != "basic", -int(r["stock"] or 0)))
        if c:
            return c[0]["lcsc"], pkg, c[0]["library"]
    raise KeyError(value)


def bom2():
    """Parts of the two-bus mixer: (group, ref, value, package, lcsc, library, qty)."""
    r = lambda v: (RES[pick(v)][0], "0603", RES[pick(v)][1])
    c10 = pick_cap("10u", 5)
    rows = [("slot", "C_IN L/R", "10 uF X5R", c10[1], c10[0], c10[2], 2 * N),
            ("slot", "R_IN L/R", "56k 1 %", "0603", r(RI2)[0], r(RI2)[2], 2 * N),
            ("slot", "C_G (mirror)", "10 uF X5R", c10[1], c10[0], c10[2], N),
            ("slot", "R_P L/R (mirror)", "56k 1 %", "0603", r(RI2)[0], r(RI2)[2], 2 * N)]
    cf, ca, c22, c100 = pick_cap("47p", 25, "C0G"), pick_cap("330p", 25, "C0G"), pick_cap("22u", 10), \
        pick_cap("100n", 10)
    for ref, val, part, q in (("R_F, R_F'", "20k 1 %", r(20e3), 4), ("C_F, C_F'", "47 pF C0G", cf, 4),
                              ("R_OUT", "220R 1 %", r(220), 2), ("C_OUT, C_REF", "10 uF X5R", c10, 4),
                              ("R_BLEED", "100k 1 %", r(100e3), 2), ("R_ADC1", "15k 1 %", r(15e3), 2),
                              ("R_ADC2", "27k 1 %", r(27e3), 2), ("C_ADC", "330 pF C0G", ca, 2),
                              ("R_VA, R_VB, R_VC (VREF from +3V3)", "10k, 27k, 10k 1 %", r(10e3), 3),
                              ("R_SUP", "47R 1 %", r(47), 1), ("C_SUP", "22 uF X5R", c22, 1),
                              ("C_DEC", "100 nF X7R", c100, 1)):
        lc, pkg, lib = part
        rows.append(("common", ref, val, pkg, lc, lib, q))
    rows += [("common", "U_MIX", "MCP6002T-I/SN", "SOIC-8", "C7377", "promotional_extended", 1),
             ("common", "J_OUT", "3.5 mm stereo jack", "THT", "(hand-soldered)", "-", 1)]
    return rows


def main2():
    os.makedirs(OUT, exist_ok=True)
    s13_load()
    rows = []
    add = lambda q, v: rows.append([q, round(float(v), 4) if isinstance(v, (float, np.floating, int)) else v])
    print("S12, two-bus variant; op-amp model:", "Microchip MCP6001/2 (vendor)" if VM else "behavioural OPB")
    vdc, z1k, z20k = card_zout()
    CARD.update(ro=max(z1k.real, 1.0), l=max(z20k.imag, 1e-3) / (2 * np.pi * 2e4), vdc=round(vdc, 3),
                bleed=100e3 if CARDV.get("card") else None)
    print(f"card outputs (S10 v5c output stage, both alike): Zout {abs(z1k):.1f} ohm @1k, {abs(z20k):.1f} ohm @20k, "
          f"10 uF, 100k bleeder; levels from S13 (A, 5.0 V): mono {S13['mono']:.3f} Vpp, hard pan capped "
          f"({S13['cap_pct']:.1f} % CV_VCA) {S13['hard']:.3f} Vpp, centre L = R {S13['centre']:.3f} Vpp, hard pan "
          f"uncapped {S13['uncapped']:.3f} Vpp; noise centre {S13['nz_centre'] * 1e6:.1f} uV, hard (CV full) "
          f"{S13['nz_hard'] * 1e6:.1f} uV")
    for q in ("mono", "hard", "centre", "uncapped"):
        add(f"card_{q}_vpp", S13[q])
    add("card_noise_centre_uv", S13["nz_centre"] * 1e6), add("card_noise_hard_uv", S13["nz_hard"] * 1e6)
    add("card_zout_ohm_1k", abs(z1k)), add("card_zout_ohm_20k", abs(z20k))
    print(f"values: R_in = R_P = {RI2 / 1e3:.0f}k ({RES[pick(RI2)][0]}), Rf = Rf' = {RF / 1e3:.0f}k ({RES[pick(RF)][0]}) || 47 pF:"
          f" {G2:.3f} per card, 8 x {G2:.3f} = {8 * G2:.2f} per bus, noise gain {1 + 8 * G2:.2f}; mirror "
          f"{CG2 * 1e6:.0f} uF per slot, shared by L and R")
    add("r_in_k", RI2 / 1e3), add("rf_k", RF / 1e3), add("gain_per_card", G2), add("gain_sum", 8 * G2)
    add("noise_gain_8", 1 + 8 * G2), add("cg_uf", CG2 * 1e6)

    # --- 1. DC and headroom
    val, idd = dc_op2()
    print(f"DC: out L {val['ol_0']:.4f} V, R {val['or_0']:.4f} V, VREF {val['vref_0']:.4f} V, + in L {val['pl_0']:.4f}"
          f", - in L {val['nl_0']:.4f}, ADC {val['al_0']:.4f} V, AUDIO_L pin {val['aol0_0']:.4f} V, Y_0 "
          f"{val['y0_0']:.4f} V; supply {idd * 1e3:.2f} mA; without C_in (100k bleeders): out L {val['ol_1']:.3f} V")
    for q, v in (("dc_out_l_v", val["ol_0"]), ("dc_out_r_v", val["or_0"]), ("dc_vref_v", val["vref_0"]),
                 ("dc_adc_v", val["al_0"]), ("dc_pin_v", val["aol0_0"]), ("dc_out_l_nocin_v", val["ol_1"]),
                 ("supply_ma", idd * 1e3)):
        add(q, v)
    hr = headroom2()
    for h in hr:
        print(f"  {h['kind']:6s} {h['n']} cards x {h['x']:.2f}: L {h['mnl']:.3f} ... {h['mxl']:.3f} V "
              f"({h['mxl'] - h['mnl']:.3f} Vpp, linear {h['pred']:.3f}), THD {h['thd']:.3f} %; R "
              f"{h['mxr'] - h['mnr']:.3f} Vpp" + (f", THD {h['thdr']:.3f} %" if h["kind"] == "centre" else "") +
              f"; line out L {h['jxl']:.3f} Vpp; ADC L "
              f"{h['anl']:.3f} ... {h['axl']:.3f} V")
        tag = f"{h['kind']}_n{h['n']}_x{h['x']:.2f}"
        add(f"out_vpp_{tag}", h["mxl"] - h["mnl"]), add(f"out_min_v_{tag}", h["mnl"])
        add(f"out_max_v_{tag}", h["mxl"]), add(f"thd_pct_{tag}", h["thd"]), add(f"lineout_vpp_{tag}", h["jxl"])
        add(f"adc_min_v_{tag}", h["anl"]), add(f"adc_max_v_{tag}", h["axl"])
        if h["kind"] == "centre":
            add(f"out_r_vpp_{tag}", h["mxr"] - h["mnr"]), add(f"thd_r_pct_{tag}", h["thdr"])
    hard = [h for h in hr if h["kind"] == "hard" and h["n"] == 8]
    sw = max(h["mxl"] for h in hr) - min(h["mnl"] for h in hr)
    full8 = hard[0]["mxl"] - hard[0]["mnl"]
    cen = next(h for h in hr if h["kind"] == "centre" and h["x"] == 1.0)
    s1 = next((h["x"] for h in hard if h["thd"] > 1.0), np.nan)
    print(f"  swing {sw:.3f} Vpp; 8 cards hard left in phase {full8:.3f} Vpp -> margin {db(sw / full8):.1f} dB; "
          f"8 cards centre {cen['mxl'] - cen['mnl']:.3f} Vpp -> margin {db(sw / (cen['mxl'] - cen['mnl'])):.1f} dB;"
          f" THD > 1 % from {s1}x the capped level")
    add("swing_vpp", sw), add("margin_8hard_db", db(sw / full8))
    add("margin_8centre_db", db(sw / (cen["mxl"] - cen["mnl"]))), add("thd1pct_at_x", s1)

    # --- 2. frequency response, gains, slot-to-slot
    f, r = ac("s12b_fr", [nominal2(sigl={0: 1}), nominal2(sigr={7: 1})],
              ["jl", "jr", "ol", "or", "al", "aol1", "aor1", "aor0"], True, fmin=5, fmax=2e6)
    _, r1 = ac("s12b_fr1", [nominal2(pop=[0], sigl={0: 1})], ["jl"], True, fmin=5, fmax=2e6)
    _, r4 = ac("s12b_fr4", [nominal2(pop=POP4, sigl={0: 1})], ["aol2", "aor2", "aor0"], True, fmin=5, fmax=2e6)
    r[(2, "jl")] = r1[(0, "jl")]
    r.update({(3, k[1]): v for k, v in r4.items()})
    ref = at(f, r[(0, "jl")], 1e3)
    fr = {x: db(at(f, r[(0, "jl")], x) / ref) for x in (20, 20e3)}
    fr1 = {x: db(at(f, r[(2, "jl")], x) / at(f, r[(2, "jl")], 1e3)) for x in (20, 20e3)}
    print(f"line out re 1 kHz (8 cards): 20 Hz {fr[20]:.2f} dB, 20 kHz {fr[20e3]:.2f} dB; 1 card: {fr1[20]:.2f} / "
          f"{fr1[20e3]:.2f} dB; peak {db(np.abs(r[(0, 'jl')]).max() / abs(ref)):.2f} dB")
    add("fr_20hz_db", fr[20]), add("fr_20khz_db", fr[20e3]), add("fr1_20hz_db", fr1[20]), add("fr1_20khz_db", fr1[20e3])
    add("fr_peak_db", db(np.abs(r[(0, "jl")]).max() / abs(ref)))
    gl0, gr7 = abs(at(f, r[(0, "ol")], 1e3)), abs(at(f, r[(1, "or")], 1e3))
    jl0 = abs(ref)
    print(f"  gain at 1 kHz: slot 0 L {gl0:.4f}, slot 7 R {gr7:.4f} (op-amp output; {G2:.4f} ideal), line out "
          f"{jl0:.4f}")
    add("gain_l_slot0_sim", gl0), add("gain_r_slot7_sim", gr7), add("gain_lineout_sim", jl0)
    for tag, i, pin_l, pin_r in (("8", 0, "aol1", "aor1"), ("4", 3, "aol2", "aor2")):
        xs = {(p, x): db(at(f, r[(i, p)], x)) for p in (pin_l, pin_r, "aor0") for x in (1e3, 20e3)}
        print(f"  slot 0 L driven ({tag} cards): slot {pin_l[-1]} AUDIO_L pin {xs[(pin_l, 1e3)]:.1f} / "
              f"{xs[(pin_l, 2e4)]:.1f} dB, AUDIO_R pin {xs[(pin_r, 1e3)]:.1f} / {xs[(pin_r, 2e4)]:.1f} dB, own AUDIO_R "
              f"pin {xs[('aor0', 1e3)]:.1f} / {xs[('aor0', 2e4)]:.1f} dB (1 / 20 kHz)")
        for (p, x), v in xs.items():
            add(f"xtalk_pin_{tag}cards_{'own_r' if p == 'aor0' else p[2:]}_{x / 1e3:g}k_db", v)
    hadc = r[(0, "al")] / at(f, r[(0, "al")], 1e3)
    fig_fr = (f, db(r[(0, "jl")] / ref), db(hadc))

    # --- 3. noise
    fc_, cn = card_noise_spectrum()
    aw = integrate(fc_, cn, weight=True) / integrate(fc_, cn)   # A-weighting ratio of the card's noise (S10 shape)
    cu = jl0 * S13["nz_centre"]
    for tag, pop in (("1", [0]), ("8", list(range(N)))):
        fn, sp = noise_run(f"s12b_nz{tag}", nominal2(pop=pop, sigl={0: 1}, noise=True), "jl", "vsl0", True)
        mu, ma = integrate(fn, sp), integrate(fn, sp, weight=True)
        allu = np.sqrt(mu ** 2 + len(pop) * cu ** 2)
        print(f"  mixer noise, {tag} card(s): {mu * 1e6:.2f} uV ({ma * 1e6:.2f} uV A); one card in the centre at the "
              f"line out {cu * 1e6:.1f} uV ({cu * aw * 1e6:.1f} uV A, S10's spectral shape): mixer adds "
              f"{10 * np.log10(1 + (mu / cu) ** 2):.2f} dB ({10 * np.log10(1 + (ma / (cu * aw)) ** 2):.2f} dB A); all "
              f"populated cards (centre) + mixer {allu * 1e6:.1f} uV")
        add(f"mixer_noise_uv_{tag}", mu * 1e6), add(f"mixer_noise_a_uv_{tag}", ma * 1e6)
        add(f"mixer_adds_db_{tag}", 10 * np.log10(1 + (mu / cu) ** 2))
        add(f"mixer_adds_a_db_{tag}", 10 * np.log10(1 + (ma / (cu * aw)) ** 2)), add(f"total_noise_uv_{tag}", allu * 1e6)
        fdens = float(10 ** np.interp(3, np.log10(fn), np.log10(sp)))
        add(f"mixer_noise_nv_1k_{tag}", fdens * 1e9)
    add("card_centre_noise_lineout_uv", cu * 1e6)

    # --- 4. ground rejection
    g = ground2(add)

    # --- 5. crosstalk L -> R
    cases = [("8cards", nominal2(sigl={0: 1})), ("4cards", nominal2(pop=POP4, sigl={0: 1})),
             ("1card", nominal2(pop=[0], sigl={0: 1})), ("8cards_inj", nominal2(inj=1)),
             ("4cards_inj", nominal2(pop=POP4, inj=1)), ("nocards_inj", nominal2(pop=[], inj=1)),
             ("4cards_chan", nominal2(pop=POP4, sigl={0: 1}, **MIR2["chan4u7"]))]
    f, r = ac("s12b_lr", [c for _, c in cases], ["jl", "jr"], True)
    for i, (t, _) in enumerate(cases):
        x = {fx: db(at(f, r[(i, "jr")], fx) / at(f, r[(i, "jl")], fx)) for fx in (1e3, 1e4, 2e4)}
        print(f"L -> R crosstalk, {t}: 1 kHz {x[1e3]:.1f} dB, 10 kHz {x[1e4]:.1f} dB, 20 kHz {x[2e4]:.1f} dB")
        for fx in x:
            add(f"xtalk_lr_{t}_{fx / 1e3:g}k_db", x[fx])

    # --- 6. ADC path
    adc2(add, fig_fr)

    # --- 7. supply rejection
    f, r = ac("s12b_psrr", [nominal2(vdd_ac=1)], ["jl", "al"], True)
    p = {x: db(at(f, r[(0, "jl")], x)) for x in (100, 1e3, 1e4)}
    print(f"supply -> line out: 100 Hz {p[100]:.1f} dB, 1 kHz {p[1e3]:.1f} dB, 10 kHz {p[1e4]:.1f} dB")
    for x in p:
        add(f"psrr_db_{x:g}hz", p[x])

    # --- 9. VREF: divider from the controller's +3V3 with two RC stages (the design), with one stage, and the
    # CJ431 + MCP6002 follower of 0.2; ripple on the +3V3 rail itself (MCU load steps: USB frames, the SYNC tick,
    # the activity LED) -> line out
    for ref in ("v33rc2", "v33"):
        f, r = ac(f"s12b_v33rip_{ref}", [nominal2(v33_ac=1, ref=ref)], ["jl"], True)
        rp = {x: db(at(f, r[(0, "jl")], x)) for x in (20, 100, 1e3, 1e4)}
        print(f"VREF {ref}: +3V3 ripple -> line out " + ", ".join(f"{x:g} Hz {v:.1f} dB" for x, v in rp.items()))
        for x in rp:
            add(f"vref_{ref}_rail_db_{x:g}hz", rp[x])
    for ref in ("v33rc2", "v33", "cj431"):
        f, r = ac(f"s12b_psrr_{ref}", [nominal2(vdd_ac=1, ref=ref)], ["jl"], True)
        p = {x: db(at(f, r[(0, "jl")], x)) for x in (50, 100, 1e3, 1e4)}
        fn, sp = noise_run(f"s12b_nz8_{ref}", nominal2(sigl={0: 1}, noise=True, ref=ref), "jl", "vsl0", True)
        mu = integrate(fn, sp)
        lo = headroom2([("hard", 8, 1.0), ("hard", 8, 1.2)], tag=f"_{ref}_4v6", ref=ref, vdd=4.6)
        val, _ = dc_op2(ref=ref)
        print(f"VREF {ref}: {val['vref_0']:.3f} V (ADC tap {val['al_0']:.3f} V); supply -> line out 50 Hz "
              f"{p[50]:.1f}, 100 Hz {p[100]:.1f}, 1 kHz {p[1e3]:.1f}, 10 kHz {p[1e4]:.1f} dB; mixer noise (8 slots) "
              f"{mu * 1e6:.2f} uV; at 4.6 V supply, 8 cards hard left: " +
              ", ".join(f"x{h['x']:.1f} {h['mnl']:.2f} ... {h['mxl']:.2f} V, THD {h['thd']:.2f} %" for h in lo))
        add(f"vref_{ref}_v", val["vref_0"]), add(f"vref_{ref}_adc_dc_v", val["al_0"])
        for x in p:
            add(f"vref_{ref}_psrr_db_{x:g}hz", p[x])
        add(f"vref_{ref}_noise_uv_8", mu * 1e6)
        for h in lo:
            add(f"vref_{ref}_4v6_thd_pct_x{h['x']:.1f}", h["thd"])
            add(f"vref_{ref}_4v6_out_min_v_x{h['x']:.1f}", h["mnl"]), add(f"vref_{ref}_4v6_out_max_v_x{h['x']:.1f}", h["mxl"])

    # --- 8. parts
    bom = bom2()
    print("parts (JLCPCB Basic / Promotional Extended):")
    for grp, ref, v, pkg, lc, lib, q in bom:
        print(f"  {grp:6s} {ref:18s} {v:20s} {pkg:7s} {lc:16s} {lib:21s} x{q}")
    per_slot = sum(b[6] for b in bom if b[0] == "slot") // N
    common = sum(b[6] for b in bom if b[0] == "common")
    n0603 = sum(b[6] for b in bom if b[3] == "0603")
    n0805 = sum(b[6] for b in bom if b[3] == "0805")
    # area: 0603 placed with its courtyard and a share of the routing ~ 3.2 x 2.0 mm, 0805 ~ 3.8 x 2.4, SOIC-8
    # (6.0 x 5.0 + fan-out) ~ 50 mm2, SOT-23 ~ 12 mm2; the jack (PJ-307 class) ~ 12 x 14 mm
    a_slot = sum(b[6] / N * (6.4 if b[3] == "0603" else 9.1) for b in bom if b[0] == "slot")
    a_com = sum(b[6] * {"0603": 6.4, "0805": 9.1, "SOIC-8": 50, "SOT-23": 12, "THT": 170}[b[3]]
                for b in bom if b[0] == "common")
    print(f"  {per_slot} parts per slot ({per_slot * N}), {common} common ({n0603} x 0603, {n0805} x 0805 in all); "
          f"area ~{a_slot:.0f} mm2 per slot (a 4 x 20 mm strip between two sockets at 10 mm pitch has ~80 mm2), "
          f"common ~{a_com:.0f} mm2 incl. the jack")
    add("parts_per_slot", per_slot), add("parts_slots", per_slot * N), add("parts_common", common)
    add("area_slot_mm2", a_slot), add("area_common_mm2", a_com)

    ps.save_csv("s12_mixer_2bus", ["quantity", "value"], rows)
    figure2(fig_fr, g, hr)


def figure2(fr, g, hr):
    fig, ax = ps.fig(3, 1, aspect=1.15)
    f, lo, ad = fr
    ax[0].semilogx(f, lo, color=ps.C[0], label="line out (10k + 1 nF)")
    ax[0].semilogx(f, ad, color=ps.C[1], label="ADC pin")
    for x in (F_CAR, FS_ADC - 2e4):
        ax[0].axvline(x, color="0.6", lw=0.6, ls=":")
    ax[0].set(xlabel="frequency [Hz]", ylabel="gain re 1 kHz [dB]", xlim=(5, 2e6), ylim=(-40, 3))
    ax[0].legend(fontsize=6.5)
    fx = g["fx"]
    for i, (var, lab) in enumerate((("slot4u7", "4.7 µF per slot"), ("slot10", "10 µF per slot (proposed)"),
                                    ("chan4u7", "4.7 µF per slot and channel"))):
        ax[1].semilogx(fx, g["nom"][(var, 8)], "o-", color=ps.C[i], ms=3, label=f"nominal, {lab}")
    t = g["tol"]["slot10"]
    ax[1].semilogx(fx, t["typ"], "s--", color=ps.C[2], ms=3, label="10 µF/slot, 1 % R: typical")
    ax[1].semilogx(fx, t["worst"], "s--", color=ps.C[3], ms=3, label="10 µF/slot, 1 % R: worst")
    ax[1].semilogx(fx, t["worstc"], "s:", color=ps.C[4], ms=3, label="+ C ±20 %: worst")
    ax[1].set(xlabel="frequency [Hz]", ylabel="ground rejection [dB]", ylim=(-150, -15))
    ax[1].legend(loc="lower center", fontsize=5)
    hard = [h for h in hr if h["kind"] == "hard" and h["n"] == 8]
    ax[2].plot([h["x"] for h in hard], [h["mxl"] - h["mnl"] for h in hard], "o-", color=ps.C[0], ms=3,
               label="8 cards hard left")
    ax[2].plot([h["x"] for h in hard], [h["pred"] for h in hard], ":", color="0.5", label="linear")
    ax2 = ax[2].twinx()
    ax2.semilogy([h["x"] for h in hard], [max(h["thd"], 1e-4) for h in hard], "s--", color=ps.C[1], ms=3)
    ax2.set_ylabel("THD [%]", color=ps.C[1])
    ax[2].axvline(S13["uncapped"] / S13["hard"], color="0.6", lw=0.6, ls=":")
    ax[2].set(xlabel="level re 1.38 Vpp per card", ylabel="L output [Vpp]", ylim=(3.5, 5.6))
    ax[2].legend(fontsize=6, loc="lower right")
    ps.label_panels(ax)
    fig.tight_layout()
    ps.save(fig, "s12_mixer_2bus")


if __name__ == "__main__":
    main2() if "--bus2" in sys.argv[1:] else main()
