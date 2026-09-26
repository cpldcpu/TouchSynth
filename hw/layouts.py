"""Hand-designed sheet layouts for gen_sch2.py. Coordinates in mm (U = 2.54 mm grid).

Parts are found by their simulation name (sim), test points by net, decoupling caps by note, so layouts survive
reference renumbering. Anything not placed here is auto-placed; nets left split are auto-labelled by gen_sch2.
"""
import design as D
from draw import U

PAPER = {"touch_led": ("A2", (594, 420))}
EXTRA = {}
PWM = {"A": "PWM_AMP", "C": "PWM_CUT", "R": "PWM_RES", "V": "PWM_VCA"}


def ref(sim):
    for p in D.PARTS:
        if p.sim and sim in p.sim.split("/"):
            return p.ref
    raise KeyError(sim)


def tp(net):
    return [p.ref for p in D.PARTS if p.lib_id == "Connector:TestPoint" and p.pins["1"] == net][0]


def dec(u):
    return [p.ref for p in D.PARTS if p.note == f"decoupling {u}"][0]


def by(pred):
    return [p.ref for p in D.PARTS if pred(p)][0]


def vcap(sh, r, x, ytop, gnd=True, fields="right"):
    """vertical 2-pin part with pin 1 at (x, ytop); returns the pin-2 point; optional GND at pin 2"""
    sh.place(r, x, ytop + 3.81, 0, fields=fields)
    if gnd:
        sh.gnd((r, 2))
    return sh.P(r, 2)


def hpart(sh, r, x1, y, fields="above", flip=False):
    """horizontal 2-pin part with pin 1 at (x1, y) (pin 2 at x1 + 7.62), or pin 2 first if flip"""
    sh.place(r, x1 + 3.81, y, 270 if flip else 90, fields=fields)
    return sh.P(r, 1 if flip else 2)


def tps(sh, nets, x, y, step=20.32):
    for i, n in enumerate(nets):
        sh.place(tp(n), x + i * step, y, fields="right")


def supply(sh, u, unit, x, y, cap):
    """op-amp supply unit with V+ label, GND and a decoupling cap to the right"""
    sh.place(u, x, y, unit=unit, fields="left")
    pins = sh.placed[-1].pins
    vp = [p for n, p in pins.items() if D.PARTS[[q.ref for q in D.PARTS].index(u)].pins[n] == "VP"][0][:2]
    vm = [p for n, p in pins.items() if D.PARTS[[q.ref for q in D.PARTS].index(u)].pins[n] == "GND"][0][:2]
    sh.lbl(vp, "VP", (0, -1), stub=U)
    sh.gnd(vm)
    sh.w(vp, (vp[0] + 10.16, vp[1]))
    vcap(sh, cap, vp[0] + 10.16, vp[1])


# ============================================================================ power
def sheet_power(sh):
    W = 405
    sh.heading("Input, reverse protection, 5 V", 15, 30, W)
    y = 55.88
    j1 = by(lambda p: p.value == "PWR 9-12V")
    sh.place(j1, 40.64, y, mirror="y", fields="above")
    d1 = ref("DREV")
    sh.place(d1, 60.96, y, 180, fields="above")                    # A left, K right
    sh.w((j1, 1), (d1, 2))
    sh.w((j1, 2), (48.26, y + U)); sh.gnd((48.26, y + U))
    sh.flag((48.26, y + U), "GND")
    u1 = ref("XREG")
    sh.place(u1, 124.46, y, fields="above")
    sh.w((d1, 1), (u1, 3))
    for i, sim in enumerate(("CBULK", "CHF")):
        vcap(sh, ref(sim), 76.2 + i * 10.16, y)
    sh.flag((99.06, y), "VP")
    sh.lbl((106.68, y), "VP", (0, -1), stub=2 * U)
    sh.gnd((u1, 2))
    x5 = sh.P(u1, 1)[0]
    sh.w((u1, 1), (x5 + 30.48, y))
    for i, sim in enumerate(("C5", "C5B")):
        vcap(sh, ref(sim), x5 + 10.16 + i * 10.16, y)
    sh.v5((x5 + 30.48, y))

    sh.heading("References: VREF 4.5 V (buffered), VBIAS 1.5 V, V25 2.5 V", 15, 78, W)
    x, yt = 30.48, 88.9
    rv1, rv2, cvr = ref("RV1"), ref("RV2"), ref("CVR")
    sh.place(rv1, x, yt + 3.81, fields="right"); sh.v5((rv1, 1))
    yn = sh.P(rv1, 2)[1] + U
    sh.w((rv1, 2), (x, yn))
    vcap(sh, rv2, x, yn)
    sh.w((x, yn), (x + 10.16, yn))
    vcap(sh, cvr, x + 10.16, yn)
    u2 = ref("XVREF")
    sh.place(u2, 63.5, yn + U, unit=1, fields="above")            # + at (55.88, yn)
    sh.w((x + 10.16, yn), (u2, 3))
    o, m = sh.P(u2, 1), sh.P(u2, 2)
    sh.w(o, (o[0] + U, o[1]), (o[0] + U, m[1] + 2 * U), (m[0] - U, m[1] + 2 * U), (m[0] - U, m[1]), m)
    xs = o[0] + 10.16
    sh.w((o[0] + U, o[1]), (xs + 12.7, o[1]))
    sh.lbl((xs + 12.7, o[1]), "VREF", (1, 0))
    p = vcap(sh, ref("RSN"), xs, o[1], gnd=False)
    vcap(sh, ref("CSN"), xs, p[1])
    supply(sh, u2, 3, 124.46, yn + U, dec(u2))
    for k, (ra, rb, cc, net) in enumerate((("RB1A", "RB1B", "CBIA", "VBIAS"), ("R25A", "R25B", "C25", "V25"))):
        x = 175.26 + k * 50.8
        a, b, c = ref(ra), ref(rb), ref(cc)
        sh.place(a, x, yt + 3.81, fields="right"); sh.v5((a, 1))
        sh.w((a, 2), (x, yn))
        vcap(sh, b, x, yn)
        sh.w((x, yn), (x + 10.16, yn), (x + 22.86, yn))
        vcap(sh, c, x + 10.16, yn)
        sh.lbl((x + 22.86, yn), net, (1, 0))

    sh.heading("Ladder bias chain (from V+; VB0...VB4 = 2.4...6.4 V at V+ = 8.6 V)", 15, 134, 200)
    x, ytop = 50.8, 146.05
    sh.lbl((x, ytop), "VP", (0, -1), stub=U)
    chain = [("RB5", "VB4", "CB4"), ("RB4", "VB3", "CB3"), ("RB3", "VB2", "CB2"), ("RB2", "VB1", "CB1"),
             ("RB1", "VB0", "CB0"), ("RB0", None, None)]
    yp = ytop
    for sim, tap, cap in chain:
        r = ref(sim)
        sh.place(r, x, yp + 3.81, fields="right")
        yb = sh.P(r, 2)[1]
        if tap is None:
            sh.gnd((r, 2))
            break
        sh.w((r, 2), (x, yb + U))
        sh.w((x, yb), (x - 12.7, yb)); sh.lbl((x - 12.7, yb), tap, (-1, 0))
        sh.w((x, yb), (x + 12.7, yb))
        hpart(sh, ref(cap), x + 12.7, yb, fields="above")
        sh.gnd((ref(cap), 2))
        yp = yb + U
    sh.heading("Test points", 215, 134, W)
    tps(sh, ("GND", "VP", "+5V", "VREF", "VBIAS", "V25", "VB0", "VB2", "VB4"), 222.25, 152.4, 20.32)


# ============================================================================ shared: CV filter + V->I
def cv_vi(sh, n, x0, y, opamp, unit, pins, re_sim, extra_emitter=None):
    """PWM label -> 1k/100n -> 4k7/33n -> 4k7/(15k||22n) -> LM324 follower -> NPN (collector up) with Re.
    pins = (in+, in-, out) of the op-amp unit. Returns the collector point."""
    sh.lbl((x0, y), PWM[n], (-1, 0))
    r1, c1, r2, c2, r3, r4, c3 = (ref(f"{k}{n}") for k in ("R1", "C1", "R2", "C2", "R3", "R4", "C3"))
    p = hpart(sh, r1, x0, y)
    sh.w(p, (p[0] + U, y)); vcap(sh, c1, p[0] + U, y)
    p = hpart(sh, r2, p[0] + U, y)
    sh.w(p, (p[0] + U, y)); vcap(sh, c2, p[0] + U, y)
    p = hpart(sh, r3, p[0] + U, y)
    xn = p[0] + U
    sh.w(p, (xn + 7.62, y))
    vcap(sh, r4, xn, y); vcap(sh, c3, xn + 7.62, y)
    xo = xn + 25.4
    sh.place(opamp, xo, y + U, unit=unit, fields="above")        # + input at (xo - 7.62, y)
    sh.w((xn + 7.62, y), (opamp, pins[0]))
    out = sh.P(opamp, pins[2])
    sh.w(out, (out[0] + U, out[1]))
    pb = hpart(sh, ref(f"RBV{n}"), out[0] + U, out[1])
    q = ref(f"QV{n}")
    sh.place(q, pb[0] + 5.08, pb[1], fields="right")             # base at pb
    e = sh.P(q, 2)
    mi = sh.P(opamp, pins[1])
    yb = e[1] + 5.08
    sh.w(mi, (mi[0] - U, mi[1]), (mi[0] - U, yb), (e[0], yb), e)
    vcap(sh, ref(re_sim), e[0], yb)
    if extra_emitter:
        rx = ref(extra_emitter)
        sh.w((e[0], yb), (e[0] + 10.16, yb))
        sh.place(rx, e[0] + 10.16, yb - 3.81, fields="right")
        sh.v5((rx, 1))
    return sh.P(q, 3)


def diff_amp(sh, opamp, unit, pins, r_in_m, r_fb, r_in_p, r_ref, x, y, net_m, net_p, ref_net="VREF"):
    """4-resistor difference amplifier, op-amp mirrored so '-' is on top. Inputs labelled net_m / net_p on the left,
    feedback above, reference resistor below. Returns the output point (after a short stub)."""
    sh.place(opamp, x, y, unit=unit, mirror="x", fields="below")
    ip, im, o = (sh.P(opamp, k) for k in pins)
    p = hpart(sh, ref(r_in_m), im[0] - 12.7, im[1]); sh.w(p, im)
    sh.lbl(sh.P(ref(r_in_m), 1), net_m, (-1, 0), stub=U)
    p = hpart(sh, ref(r_in_p), ip[0] - 12.7, ip[1]); sh.w(p, ip)
    sh.lbl(sh.P(ref(r_in_p), 1), net_p, (-1, 0), stub=U)
    xm = im[0] - U
    yt = im[1] - 7.62
    rf = ref(r_fb)
    pr = hpart(sh, rf, xm + U, yt)                     # pin 1 left (the '-' node), pin 2 right (output)
    sh.w((xm, im[1]), (xm, yt), sh.P(rf, 1))
    sh.w(pr, (o[0] + U, yt), (o[0] + U, o[1]), o)
    rr = ref(r_ref)
    xp = ip[0] - U
    sh.place(rr, xp, ip[1] + 3.81 + U, 0, fields="left")
    sh.w((xp, ip[1]), (rr, 1))
    sh.lbl((rr, 2), ref_net, (0, 1), stub=U)
    return (o[0] + U, o[1])


def pair(sh, sim, x, y, gap=20.32, fields=("left", "right")):
    """BC847BS as a differential pair: unit 1 at x, unit 2 mirrored at x + gap; returns pins dict"""
    q = ref(sim)
    sh.place(q, x, y, unit=1, fields=fields[0])
    sh.place(q, x + gap, y, unit=2, mirror="y", fields=fields[1])
    return q, {k: sh.P(q, k) for k in (1, 2, 3, 4, 5, 6)}


# ============================================================================ DCO
def sheet_dco(sh):
    W = 405
    sh.heading("CV_AMP: PWM filter and V-to-I converter (charge current proportional to the note frequency)",
               15, 30, W)
    lm = by(lambda p: p.lib_id.endswith("LM324"))
    col = cv_vi(sh, "A", 30.48, 55.88, lm, 1, (3, 2, 1), "REVA")
    sh.lbl(col, "DCO_INT", (0, -1), stub=U)
    sh.heading("Integrator (TL072) with 2N7002 reset and NPN gate level shifter", 15, 95, W)
    u = by(lambda p: p.sim == "XDCO/XDIF")
    xo, yo = 180.34, 166.37
    sh.place(u, xo, yo, unit=1, mirror="x", fields="below")        # '-' on top
    ip, im, o = sh.P(u, 3), sh.P(u, 2), sh.P(u, 1)
    sh.lbl(ip, "VREF", (-1, 0), stub=5.08)
    xl, xr = im[0] - 5.08, o[0] + 5.08
    ci, m = ref("CI"), ref("MRST")
    yc = im[1] - 12.7
    sh.place(ci, (xl + xr) / 2, yc, 270, fields="above")          # pin 1 (SAW) right, pin 2 (INT) left
    sh.place(m, (xl + xr) / 2, yc - 17.78, 270, fields="right")    # S left, D right, G top
    sh.w(im, (xl, im[1]), (xl, sh.P(m, 2)[1]), (m, 2))
    sh.w((xl, yc), (ci, 2))
    sh.w(o, (xr, o[1]), (xr, sh.P(m, 3)[1]), (m, 3))
    sh.w((xr, yc), (ci, 1))
    sh.w((xl, im[1]), (xl - 10.16, im[1])); sh.lbl((xl - 10.16, im[1]), "DCO_INT", (-1, 0))
    sh.w((xr, o[1]), (xr + 25.4, o[1])); sh.lbl((xr + 25.4, o[1]), "SAW", (1, 0))
    t = tp("SAW"); sh.place(t, xr + 12.7, o[1] - 2 * U, fields="right"); sh.w((t, 1), (xr + 12.7, o[1]))
    g = sh.P(m, 1)
    rgs, rgp, qls, rlsb = ref("RGS"), ref("RGP"), ref("QLS"), ref("RLSB")
    sh.place(rgs, g[0], g[1] - 3.81, 0, fields="right")           # pin 2 at the gate
    gd = sh.P(rgs, 1)
    xq = gd[0] - 25.4
    sh.w(gd, (xq, gd[1]))
    sh.place(rgp, xq, gd[1] - 3.81, 0, fields="left")             # pin 2 at GD, pin 1 up to VP
    sh.lbl((rgp, 1), "VP", (0, -1), stub=U)
    sh.place(qls, xq - 2.54, gd[1] + 5.08, fields="left")          # collector at GD
    sh.gnd((qls, 2))
    b = sh.P(qls, 1)
    p0 = (b[0] - 7.62, b[1])
    hpart(sh, rlsb, p0[0], p0[1])
    sh.lbl(p0, "DCO_RST", (-1, 0), stub=U)
    supply(sh, u, 3, 300.0, 160.0, dec(u))
    tps(sh, ("XAMP",), 330.2, 60.96)


# ============================================================================ resonance
def sheet_resonance(sh):
    W = 405
    sh.heading("CV_RES: PWM filter and V-to-I converter (tail current of the resonance VCA)", 15, 30, W)
    lm = by(lambda p: p.lib_id.endswith("LM324"))
    col = cv_vi(sh, "R", 30.48, 55.88, lm, 4, (12, 13, 14), "REVR")
    sh.lbl(col, "RES_TAIL", (0, -1), stub=U)
    sh.heading("Resonance VCA: differential pair, difference amplifier, AC-coupled feedback into the ladder (BIN2)",
               15, 95, W)
    y = 147.32
    q, P = pair(sh, "QR1", 110.49, y, gap=25.4)
    yt = P[1][1] + 5.08
    sh.w(P[1], (P[1][0], yt), (P[4][0], yt), P[4])
    xm = (P[1][0] + P[4][0]) / 2
    sh.w((xm, yt), (xm, yt + 5.08)); sh.lbl((xm, yt + 5.08), "RES_TAIL", (0, 1))
    cri, rra, rrb1, rrb2 = ref("CRI"), ref("RRA"), ref("RRB1"), ref("RRB2")
    b1, b2 = P[2], P[5]
    x1 = b1[0] - 5.08 - 7.62
    hpart(sh, rra, x1, b1[1]); sh.w(sh.P(rra, 2), b1)
    hpart(sh, cri, x1 - 10.16, b1[1]); sh.w(sh.P(cri, 2), (x1, b1[1]))
    sh.lbl(sh.P(cri, 1), "LPF", (-1, 0), stub=U)
    xb = b1[0] - U
    sh.place(rrb1, xb, b1[1] + 3.81 + 2 * U, 0, fields="left"); sh.w((xb, b1[1]), (rrb1, 1))
    sh.lbl((rrb1, 2), "VB2", (0, 1), stub=U)
    sh.w(b2, (b2[0] + 5.08, b2[1]))
    sh.place(rrb2, b2[0] + 5.08, b2[1] + 3.81 + 2 * U, 0, fields="right"); sh.w((b2[0] + 5.08, b2[1]), (rrb2, 1))
    sh.lbl((rrb2, 2), "VB2", (0, 1), stub=U)
    rrc1, rrc2 = ref("RRC1"), ref("RRC2")
    for rr, c, net, fl in ((rrc1, P[6], "RES_C1", "left"), (rrc2, P[3], "RES_C2", "right")):
        sh.place(rr, c[0], c[1] - 5.08 - 3.81, 0, fields=fl); sh.w(c, (rr, 2))
        sh.lbl((rr, 1), "VP", (0, -1), stub=U)
        d = (-1, 0) if net == "RES_C1" else (1, 0)
        sh.w((c[0], c[1] - U), (c[0] + d[0] * 7.62, c[1] - U)); sh.lbl((c[0] + d[0] * 7.62, c[1] - U), net, d)
    u = by(lambda p: p.sim == "XVREF/XRDIF")
    out = diff_amp(sh, u, 2, (5, 6, 7), "RRD1", "RRD2", "RRD3", "RRD4", 238.76, 137.16, "RES_C1", "RES_C2")
    crf, rrf = ref("CRF"), ref("RRF")
    sh.w(out, (out[0] + 7.62, out[1]))
    p = hpart(sh, crf, out[0] + 7.62, out[1])
    p = hpart(sh, rrf, p[0] + U, p[1]); sh.w(sh.P(crf, 2), sh.P(rrf, 1))
    sh.lbl(p, "BIN2", (1, 0), stub=U)
    t = tp("RESOUT"); sh.place(t, out[0] + 3.81, out[1] - 2 * U, fields="left")
    sh.w((t, 1), (out[0] + 3.81, out[1]))
    tps(sh, ("XRES",), 330.2, 60.96)


# ============================================================================ VCA
def sheet_vca(sh):
    W = 405
    sh.heading("CV_VCA: PWM filter and V-to-I converter (470k pull-up guarantees zero current at CV = 0)",
               15, 30, W)
    lm = by(lambda p: p.lib_id.endswith("LM324"))
    col = cv_vi(sh, "V", 30.48, 55.88, lm, 2, (5, 6, 7), "REVV", extra_emitter="ROFFV")
    sh.lbl(col, "VCA_TAIL", (0, -1), stub=U)
    sh.heading("VCA: differential pair with offset trim, difference amplifier, line out, audio loopback", 15, 95, W)
    y = 147.32
    q, P = pair(sh, "QA1", 110.49, y, gap=25.4)
    yt = P[1][1] + 5.08
    sh.w(P[1], (P[1][0], yt), (P[4][0], yt), P[4])
    xm = (P[1][0] + P[4][0]) / 2
    sh.w((xm, yt), (xm, yt + 5.08)); sh.lbl((xm, yt + 5.08), "VCA_TAIL", (0, 1))
    cvi, rva, rvb1, rvb2, rtrm, rtrf = (ref(s) for s in ("CVI", "RVA", "RVB1", "RVB2", "RTRM", "RTRF"))
    b1, b2 = P[2], P[5]
    x1 = b1[0] - 5.08 - 7.62
    hpart(sh, rva, x1, b1[1]); sh.w(sh.P(rva, 2), b1)
    hpart(sh, cvi, x1 - 10.16, b1[1]); sh.w(sh.P(cvi, 2), (x1, b1[1]))
    sh.lbl(sh.P(cvi, 1), "LPF", (-1, 0), stub=U)
    xb = b1[0] - U
    sh.place(rvb1, xb, b1[1] + 3.81 + 2 * U, 0, fields="left"); sh.w((xb, b1[1]), (rvb1, 1))
    sh.lbl((rvb1, 2), "VREF", (0, 1), stub=U)
    sh.w((xb, b1[1] + U), (xb - 7.62, b1[1] + U))
    sh.place(rtrf, xb - 7.62, b1[1] + U + 3.81, 0, fields="left"); sh.gnd((rtrf, 2))
    sh.w(b2, (b2[0] + 12.7, b2[1]))
    sh.place(rvb2, b2[0] + 5.08, b2[1] + 3.81 + 2 * U, 0, fields="left"); sh.w((b2[0] + 5.08, b2[1]), (rvb2, 1))
    sh.lbl((rvb2, 2), "VREF", (0, 1), stub=U)
    hpart(sh, rtrm, b2[0] + 12.7, b2[1], flip=True)                # pin 2 (base side) left, pin 1 (VTRIM) right
    sh.lbl(sh.P(rtrm, 1), "VTRIM", (1, 0), stub=U)
    rvc1, rvc2 = ref("RVC1"), ref("RVC2")
    for rr, c, net, fl in ((rvc1, P[6], "VCA_C1", "left"), (rvc2, P[3], "VCA_C2", "right")):
        sh.place(rr, c[0], c[1] - 5.08 - 3.81, 0, fields=fl); sh.w(c, (rr, 2))
        sh.lbl((rr, 1), "VP", (0, -1), stub=U)
        d = (-1, 0) if net == "VCA_C1" else (1, 0)
        sh.w((c[0], c[1] - U), (c[0] + d[0] * 7.62, c[1] - U)); sh.lbl((c[0] + d[0] * 7.62, c[1] - U), net, d)
    u = by(lambda p: p.sim == "XDCO/XDIF")
    out = diff_amp(sh, u, 2, (5, 6, 7), "RD1", "RD2", "RD3", "RD4", 238.76, 137.16, "VCA_C1", "VCA_C2")
    cout = ref("COUT")
    xo = out[0] + 17.78
    sh.w(out, (xo, out[1]))
    p = hpart(sh, cout, xo, out[1])
    jn = by(lambda p: p.value == "LINE OUT")
    rbl = by(lambda p: p.note == "output bleeder")
    sh.w(p, (p[0] + 12.7, out[1]))
    vcap(sh, rbl, p[0] + 5.08, out[1])
    sh.place(jn, p[0] + 20.32, out[1], fields="right")             # pin 1 at (p + 15.24)
    sh.w((p[0] + 12.7, out[1]), (jn, 1))
    sh.gnd((jn, 2))
    t = tp("VCAOUT"); sh.place(t, out[0] + 5.08, out[1] - 2 * U, fields="left"); sh.w((t, 1), (out[0] + 5.08, out[1]))
    # loopback divider to PD5
    xl = out[0] + 10.16
    rlb1, rlb2, clb = ref("RLB1"), ref("RLB2"), ref("CLB")
    sh.place(rlb1, xl, out[1] + 3.81 + U, 0, fields="left"); sh.w((xl, out[1]), (rlb1, 1))
    yl = sh.P(rlb1, 2)[1]
    sh.w((xl, yl), (xl + 25.4, yl))
    vcap(sh, rlb2, xl + 7.62, yl); vcap(sh, clb, xl + 15.24, yl)
    sh.lbl((xl + 25.4, yl), "ADC_AUDIO", (1, 0))
    sh.place(dec(u), 386.08, 60.96, fields="right")
    tps(sh, ("XVCA", "VTRIM"), 322.58, 55.88)


# ============================================================================ VCF
def sheet_vcf(sh):
    W = 405
    sh.heading("CV_CUT: PWM filter and exponential converter (tail current of the ladder)", 15, 30, 250)
    y = 55.88
    sh.lbl((30.48, y), "PWM_CUT", (-1, 0))
    r1, c1, r2, c2, r33, r12, c12 = (ref(s) for s in ("R1C", "C1C", "R2C", "C2C", "R33X", "R12X", "C12X"))
    p = hpart(sh, r1, 30.48, y); sh.w(p, (p[0] + U, y)); vcap(sh, c1, p[0] + U, y)
    p = hpart(sh, r2, p[0] + U, y); sh.w(p, (p[0] + U, y)); vcap(sh, c2, p[0] + U, y)
    xin = p[0] + U
    t = tp("XCUT_IN"); sh.place(t, xin + 5.08, y - 2 * U, fields="right"); sh.w((t, 1), (xin + 5.08, y))
    p = hpart(sh, r33, xin + 10.16, y); sh.w((xin, y), (xin + 10.16, y))
    xx = p[0] + 5.08
    sh.w(p, (xx + 30.48, y))
    vcap(sh, r12, xx, y, gnd=False); sh.lbl((r12, 2), "VBIAS", (0, 1), stub=U)
    vcap(sh, c12, xx + 10.16, y, gnd=False); sh.lbl((c12, 2), "VBIAS", (0, 1), stub=U)
    # expo pair: QEA (reference, base at VBIAS), QEB (output, base at XCUT) - both bases left
    qe = ref("QEA")
    xq = xx + 50.8
    sh.place(qe, xq, 86.36, unit=1, fields="left")                   # QEA
    sh.place(qe, xq + 22.86, y, unit=2, fields="right")               # QEB, base on the XCUT line
    sh.w((xx + 30.48, y), sh.P(qe, 5))
    ea, eb = sh.P(qe, 1), sh.P(qe, 4)
    ba = sh.P(qe, 2)
    sh.lbl(ba, "VBIAS", (-1, 0), stub=U)
    ye = ea[1] + 7.62
    sh.w(ea, (ea[0], ye), (eb[0], ye), eb)
    sh.lbl(sh.P(qe, 3), "TAIL", (0, -1), stub=U)
    # reference current: +5V -> 300k -> collector of QEA = inverting input of the LM324 unit C
    ca = sh.P(qe, 6)
    rref = ref("RREF")
    sh.place(rref, ca[0], ca[1] - 3.81 - U, 0, fields="left"); sh.w(ca, (rref, 2)); sh.v5((rref, 1))
    lm = by(lambda p: p.lib_id.endswith("LM324"))
    xo = ca[0] + 45.72
    sh.place(lm, xo, ca[1] - U + 5.08, unit=3, mirror="x", fields="below")   # '-' on top at ca[1]-U ... see below
    im, ip, o = sh.P(lm, 9), sh.P(lm, 10), sh.P(lm, 8)
    sh.w((ca[0], ca[1] - U), (im[0] - 10.16, ca[1] - U), (im[0] - 10.16, im[1]), im)
    sh.lbl(ip, "V25", (-1, 0), stub=5.08)
    cexp, rexp = ref("CEXP"), ref("REXP")
    yc = im[1] - 10.16
    hpart(sh, cexp, im[0] - 5.08 + 1.27 * 0, yc, flip=True)          # pin 2 (NA) left, pin 1 (OUT) right
    sh.w((im[0] - 10.16, im[1]), (im[0] - 10.16, yc), sh.P(cexp, 2))
    sh.w(sh.P(cexp, 1), (o[0] + U, yc), (o[0] + U, o[1]), o)
    # output -> 1k -> emitters
    sh.w((o[0] + U, o[1]), (o[0] + U, ye + 7.62))
    hpart(sh, rexp, o[0] + U - 7.62, ye + 7.62, flip=True)            # pin 1 (OUT) right, pin 2 (E) left
    sh.w(sh.P(rexp, 2), ((ea[0] + eb[0]) / 2, ye + 7.62), ((ea[0] + eb[0]) / 2, ye))
    supply(sh, lm, 5, 228.6, 142.24, by(lambda p: p.note == "LM324 decoupling"))

    # ---- ladder
    sh.heading("Transistor ladder (4 poles, 4 x 33 nF), bias from VB0...VB4, mixer", 262, 30, W)
    xa, y0 = 340.36, 200.66
    gap = 30.48
    stages = ["Q1", "Q3", "Q5", "Q7", "Q9"]
    caps = ["CL1", "CL2", "CL3", "CL4"]
    ys = [y0 - k * 22.86 for k in range(5)]
    for k, sim in enumerate(stages):
        q = ref(sim)
        sh.place(q, xa, ys[k], unit=1, fields="right")
        sh.place(q, xa + gap, ys[k], unit=2, mirror="y", fields="left")
        c1_, e1_, b1_ = sh.P(q, 6), sh.P(q, 1), sh.P(q, 2)
        c2_, e2_, b2_ = sh.P(q, 3), sh.P(q, 4), sh.P(q, 5)
        if k == 0:
            yt = e1_[1] + U
            sh.w(e1_, (e1_[0], yt), (e2_[0], yt), e2_)
            xm = (e1_[0] + e2_[0]) / 2
            sh.w((xm, yt), (xm, yt + 5.08)); sh.lbl((xm, yt + 5.08), "TAIL", (0, 1))
            t = tp("TAIL"); sh.place(t, xm + 7.62, yt + 5.08, fields="right"); sh.w((t, 1), (xm + 7.62, yt))
            sh.w((xm, yt), (xm + 7.62, yt))
        else:
            sh.lbl(b1_, f"VB{k}", (-1, 0), stub=U)
            sh.lbl(b2_, f"VB{k}", (1, 0), stub=U)
            pq = ref(stages[k - 1])
            pc1, pc2 = sh.P(pq, 6), sh.P(pq, 3)
            sh.w(pc1, e1_); sh.w(pc2, e2_)
            yc = (pc1[1] + e1_[1]) / 2
            cc = ref(caps[k - 1])
            sh.place(cc, (pc1[0] + pc2[0]) / 2, yc, 90, fields="above")
            sh.w((pc1[0], yc), (cc, 1)); sh.w((cc, 2), (pc2[0], yc))
            sh.lbl((pc1[0], yc), f"N{k}A", (-1, 0), stub=0) if False else None
        if k == 4:
            sh.lbl(c1_, "VP", (0, -1), stub=U); sh.lbl(c2_, "VP", (0, -1), stub=U)
    # top nodes N4A / N4B to the instrumentation amplifier
    q3, q4 = ref("Q7"), ref("Q9")
    n4a = ((sh.P(q3, 6)[0]), (sh.P(q3, 6)[1] + sh.P(q4, 1)[1]) / 2)
    n4b = ((sh.P(q3, 3)[0]), n4a[1])
    sh.w(n4a, (n4a[0] - 12.7, n4a[1])); sh.lbl((n4a[0] - 12.7, n4a[1]), "N4A", (-1, 0))
    sh.w(n4b, (n4b[0] + 12.7, n4b[1])); sh.lbl((n4b[0] + 12.7, n4b[1]), "N4B", (1, 0))
    # input bias and mixer
    q0 = ref("Q1")
    b1_, b2_ = sh.P(q0, 2), sh.P(q0, 5)
    rbi1, rbi2 = ref("RBI1"), ref("RBI2")
    sh.w(b1_, (b1_[0] - 7.62, b1_[1]))
    sh.place(rbi1, b1_[0] - 7.62, b1_[1] + 3.81 + U, 0, fields="left"); sh.w((b1_[0] - 7.62, b1_[1]), (rbi1, 1))
    sh.lbl((rbi1, 2), "VB0", (0, 1), stub=U)
    sh.w(b2_, (b2_[0] + 7.62, b2_[1]))
    sh.place(rbi2, b2_[0] + 7.62, b2_[1] + 3.81 + U, 0, fields="right"); sh.w((b2_[0] + 7.62, b2_[1]), (rbi2, 1))
    sh.lbl((rbi2, 2), "VB0", (0, 1), stub=U)
    sh.w((b2_[0] + 7.62, b2_[1]), (b2_[0] + 17.78, b2_[1])); sh.lbl((b2_[0] + 17.78, b2_[1]), "BIN2", (1, 0))
    cmx = ref("CMX")
    xmx = b1_[0] - 7.62 - 17.78
    hpart(sh, cmx, xmx, b1_[1]); sh.w(sh.P(cmx, 2), (b1_[0] - 7.62, b1_[1]))
    srcs = [("RMS", "SAW"), ("RMP", "PULSE"), ("RMU", "SUB"), ("RMN", "NOISE")]
    xr = xmx - 25.4
    for i, (sim, net) in enumerate(srcs):
        yy = b1_[1] - 22.86 + i * 7.62
        r = ref(sim)
        hpart(sh, r, xr - 7.62, yy)
        sh.lbl(sh.P(r, 1), net, (-1, 0), stub=U)
        sh.w(sh.P(r, 2), (xr + U, yy))
    sh.w((xr + U, b1_[1] - 22.86), (xr + U, b1_[1]), sh.P(cmx, 1))
    rmx = ref("RMX")
    sh.w((xr + U, b1_[1]), (xr + U, b1_[1] + U))
    sh.place(rmx, xr + U, b1_[1] + U + 3.81, 0, fields="left")
    sh.lbl((rmx, 2), "VB0", (0, 1), stub=U)

    # ---- instrumentation amplifier (two op-amp INA, G = 11)
    sh.heading("Output instrumentation amplifier across the top capacitor (G = 11, referenced to VREF)", 15, 175, 250)
    u = by(lambda p: p.sim == "XINA1/XINA2")
    sh.place(u, 60.96, 210.82, unit=1, fields="above")
    sh.place(u, 132.08, 210.82, unit=2, fields="above")
    pa, ma, oa = sh.P(u, 3), sh.P(u, 2), sh.P(u, 1)
    pb, mb, ob = sh.P(u, 5), sh.P(u, 6), sh.P(u, 7)
    sh.lbl(pa, "N4A", (-1, 0), stub=7.62)
    sh.lbl(pb, "N4B", (-1, 0), stub=5.08)
    ri1, ri2, ri3, ri4 = ref("RI1"), ref("RI2"), ref("RI3"), ref("RI4")
    # RI1: '-'A to VREF (below), RI2: OA to '-'A (feedback below)
    xm = ma[0] - U
    sh.w(ma, (xm, ma[1]), (xm, ma[1] + 7.62))
    hpart(sh, ri2, xm, ma[1] + 7.62, flip=True); sh.w(sh.P(ri2, 1), (oa[0] + U, ma[1] + 7.62), (oa[0] + U, oa[1]), oa)
    sh.w((xm, ma[1] + 7.62), (xm, ma[1] + 12.7))
    sh.place(ri1, xm, ma[1] + 12.7 + 3.81, 0, fields="left"); sh.lbl((ri1, 2), "VREF", (0, 1), stub=U)
    # RI3: OA -> '-'B, RI4: LPF (out B) -> '-'B
    sh.w((oa[0] + U, oa[1]), (oa[0] + 12.7, oa[1]))
    hpart(sh, ri3, oa[0] + 12.7, oa[1]); sh.w(sh.P(ri3, 2), (mb[0] - U, oa[1]), (mb[0] - U, mb[1]), mb)
    xmb = mb[0] - U
    sh.w((xmb, mb[1]), (xmb, mb[1] + 7.62))
    hpart(sh, ri4, xmb, mb[1] + 7.62, flip=True)
    sh.w(sh.P(ri4, 1), (ob[0] + U, mb[1] + 7.62), (ob[0] + U, ob[1]), ob)
    sh.w((ob[0] + U, ob[1]), (ob[0] + 20.32, ob[1])); sh.lbl((ob[0] + 20.32, ob[1]), "LPF", (1, 0))
    t = tp("LPF"); sh.place(t, ob[0] + 10.16, ob[1] - 2 * U, fields="right"); sh.w((t, 1), (ob[0] + 10.16, ob[1]))
    supply(sh, u, 3, 205.74, 210.82, dec(u))


# ============================================================================ MCU
def sheet_mcu(sh):
    W = 405
    sh.heading("MCU: CH32V003F4P6 or CH32V002F4P6 (TSSOP-20, hand-soldered, not placed by JLCPCB)", 15, 30, 250)
    u = by(lambda p: p.lib_id.startswith("MCU_WCH"))
    sh.place(u, 101.6, 101.6, fields="above")
    c15 = by(lambda p: p.note == "MCU decoupling")
    c16 = by(lambda p: p.note == "MCU bulk")
    vdd = sh.P(u, 9)
    sh.v5(vdd, stub=U) if False else None
    sh.heading("Programming (WCH-LinkE, SWIO)", 270, 30, W)
    j2 = by(lambda p: p.value == "SWIO")
    sh.place(j2, 300.0, 55.88, mirror="y", fields="left")
    sh.place(c15, 180.34, 55.88, fields="right"); sh.place(c16, 195.58, 55.88, fields="right")
    sh.heading("MIDI in (not populated in rev 0.1)", 15, 190, W)
    j3 = by(lambda p: p.value == "MIDI IN")
    y = 215.9
    sh.place(j3, 35.56, y, mirror="y", fields="above")               # pin 1 (MIDI_4) at y, pin 2 below
    rin = by(lambda p: p.pins == {"1": "MIDI_4", "2": "MIDI_A"})
    dm = by(lambda p: p.lib_id == "Diode:1N4148W")
    opto = by(lambda p: p.lib_id == "Isolator:LTV-817S")
    rpu = by(lambda p: p.pins == {"1": "+5V", "2": "MIDI_RX"})
    p = hpart(sh, rin, sh.P(j3, 1)[0] + 5.08, y); sh.w((j3, 1), sh.P(rin, 1))
    sh.place(opto, p[0] + 30.48, y + U, fields="above")               # pin 1 (anode) at (p+22.86, y)
    a, k = sh.P(opto, 1), sh.P(opto, 2)
    sh.w(p, a)
    xr_ = k[0] - 7.62
    yr = y + 7.62                                                     # return (MIDI_5) line below
    j2p = sh.P(j3, 2)
    sh.w(j2p, (j2p[0] + 5.08, j2p[1]), (j2p[0] + 5.08, yr), (xr_, yr), (xr_, k[1]), k)
    sh.place(dm, p[0] + 5.08, y + 3.81, 270, fields="left")          # K on the MIDI_A line, A on the return
    col, em = sh.P(opto, 4), sh.P(opto, 3)
    sh.gnd(em, stub=0)
    sh.w(col, (col[0] + 10.16, col[1]))
    sh.place(rpu, col[0] + 10.16, col[1] - 3.81, 0, fields="right"); sh.v5((rpu, 1))
    sh.w((col[0] + 10.16, col[1]), (col[0] + 20.32, col[1])); sh.lbl((col[0] + 20.32, col[1]), "MIDI_RX", (1, 0))
    tps(sh, ("NRST",), 300.0, 101.6)


# ============================================================================ touch / LEDs
def sheet_touch_led(sh):
    W = 579
    sh.heading("Touch multiplexers (select S0...S2 shared with the 74HC595 data / clock)", 15, 30, 280)
    muxes = [p.ref for p in D.PARTS if p.lib_id == "4xxx:4051"]
    for i, m in enumerate(muxes):
        sh.place(m, 80.0 + i * 110.0, 80.0, fields="above")
        sh.place([p.ref for p in D.PARTS if p.note == "CD4051 decoupling"][i], 125.0 + i * 110.0, 55.0, fields="right")
    sh.heading("Touch pads (copper under solder mask)", 300, 30, W)
    keys = [p.ref for p in D.PARTS if p.ref.startswith("KEY")]
    for i, k in enumerate(keys):
        sh.place(k, 330.0 + (i % 8) * 30.48, 55.88 + (i // 8) * 22.86, fields="right")
    sh.heading("Shift registers (daisy-chained: LEDs 0-7, LEDs 8-15, trim DAC)", 15, 140, W)
    srs = [p.ref for p in D.PARTS if p.lib_id == "74xx:74HC595"]
    decs = [p.ref for p in D.PARTS if p.note == "74HC595 decoupling"]
    for i, s in enumerate(srs):
        sh.place(s, 80.0 + i * 120.0, 190.0, fields="above")
        sh.place(decs[i], 125.0 + i * 120.0, 160.0, fields="right")
    sh.heading("LEDs (4.7k arrays, ~0.6 mA each)", 15, 250, W)
    rns = [p.ref for p in D.PARTS if p.lib_id == "Device:R_Pack04"]
    leds = [p.ref for p in D.PARTS if p.lib_id == "Device:LED"]
    for i, rn in enumerate(rns):
        sh.place(rn, 40.0 + i * 130.0, 290.0, rot=90, fields="above")
        for j in range(4):
            sh.place(leds[4 * i + j], 75.0 + i * 130.0 + j * 0, 270.0 + j * 12.7, rot=180, fields="right")
    sh.heading("VCA trim DAC: 8-bit R-2R ladder (R = 100k, 2R = 200k), output impedance 100k", 15, 335, W)
    x0, yl = 45.72, 375.92
    term = by(lambda p: p.note == "R-2R termination")
    sh.place(term, x0, yl + 3.81, 0, fields="left"); sh.gnd((term, 2))
    xs = x0
    for q in range(8):
        r2 = by(lambda p, q=q: p.lib_id == "Device:R" and p.pins.get("1") == f"DAC_Q{q}")
        node = f"DAC_N{q}" if q < 7 else "VTRIM"
        sh.place(r2, xs, yl - 3.81 - U, 0, fields="right")
        sh.w((r2, 2), (xs, yl))
        sh.lbl((r2, 1), f"DAC_Q{q}", (0, -1), stub=U)
        if q < 7:
            r1 = by(lambda p, q=q: p.lib_id == "Device:R" and p.pins.get("1") == f"DAC_N{q}" and p.value == "100k")
            p_ = hpart(sh, r1, xs, yl)
            sh.w(p_, (p_[0] + 10.16, yl))
            xs = p_[0] + 10.16
            if q == 0:
                pass
        else:
            sh.w((xs, yl), (xs + 12.7, yl)); sh.lbl((xs + 12.7, yl), "VTRIM", (1, 0))
