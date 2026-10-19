"""Hand-designed sheet layouts of the voice card (voice.py) for gen_sch2.py. Coordinates in mm (U = 2.54 mm grid).

Same approach as layouts.py (rev 0.1): parts are found by their simulation name (sim), test points by net,
decoupling caps by note, the rest by value / note / nets, so layouts survive reference renumbering. Anything not
placed here would be auto-placed; nets left split are auto-labelled by gen_sch2.
"""
import voice as D
from draw import U

PAPER = {}
# MCU sheet: the MCU pins, the backplane connector and the bus resistors are joined by labels; drawn as global
# labels like the cross-sheet nets around them, so the label stacks at the MCU pins stay uniform
GLOBAL = {"LED_PLAY", "LED_STAT", "SYNC_IN", "RX_IN", "TX_OUT", "NRST", "SWIO", "CLK_SEL", "ST_VB0", "ST_RAIL",
          "SYNC", "RX", "TX", "CLK_IN"}
PWM = {"R": "PWM_RES", "V": "PWM_VCA"}


def ref(sim):
    for p in D.PARTS:
        if p.sim and sim in p.sim.split("/"):
            return p.ref
    raise KeyError(sim)


def tp(net, k=0):
    return [p.ref for p in D.PARTS if p.lib_id == "Connector:TestPoint" and p.pins["1"] == net][k]


def dec(u):
    return [p.ref for p in D.PARTS if p.note == f"decoupling {u}"][0]


def by(pred):
    return [p.ref for p in D.PARTS if pred(p)][0]


def note(s):
    return by(lambda p: p.note == s)


def nets(**pins):
    """the part whose pins carry exactly these nets (pin number -> net), e.g. nets(_1="RX", _2="RX_IN")"""
    want = {k.lstrip("_"): v for k, v in pins.items()}
    return by(lambda p: p.pins == want)


def vcap(sh, r, x, ytop, gnd=True, fields="right"):
    """vertical 2-pin part with pin 1 at (x, ytop); returns the pin-2 point; optional GND at pin 2"""
    sh.place(r, x, ytop + 3.81, 0, fields=fields)
    if gnd:
        sh.gnd((r, 2))
    return sh.P(r, 2)


def vup(sh, r, x, ybot, fields="right"):
    """vertical 2-pin part with pin 1 at (x, ybot), pin 2 above; returns the pin-2 point"""
    sh.place(r, x, ybot - 3.81, 180, fields=fields)
    return sh.P(r, 2)


def hpart(sh, r, x1, y, fields="above", flip=False):
    """horizontal 2-pin part with pin 1 at (x1, y) (pin 2 at x1 + 7.62), or pin 2 first if flip"""
    sh.place(r, x1 + 3.81, y, 270 if flip else 90, fields=fields)
    return sh.P(r, 1 if flip else 2)


def va(sh, p, stub=U):
    """analog rail: global label VA above p"""
    sh.lbl(p, "VA", (0, -1), stub=stub)


def v33(sh, p, stub=0.0):
    p = sh._pt(p)
    if stub:
        q = (p[0], p[1] - stub); sh.w(p, q); p = q
    sh.pwr(p, "+3V3", (0, -1))


def tpx(sh, net, p, k=0, up=2 * U, fields="right"):
    """test point above the wire point p (wired down to it); nothing if voice.py has no such test point"""
    if len([q for q in D.PARTS if q.lib_id == "Connector:TestPoint" and q.pins["1"] == net]) <= k:
        return
    t = tp(net, k)
    sh.place(t, p[0], p[1] - up, fields=fields)
    sh.w((t, 1), p)


def supply(sh, u, unit, x, y, cap, fields=(-15.24, -1.27)):
    """op-amp supply unit: VA label on V+, GND on V-, decoupling cap from V+ to GND to the right"""
    sh.place(u, x, y, unit=unit, fields=fields)
    part = D.PARTS[[q.ref for q in D.PARTS].index(u)]
    pins = sh.placed[-1].pins
    vp = [p for n, p in pins.items() if part.pins[n] == "VA"][0][:2]
    vm = [p for n, p in pins.items() if part.pins[n] == "GND"][0][:2]
    va(sh, vp)
    sh.gnd(vm)
    sh.w(vp, (vp[0] + 7.62, vp[1]))
    vcap(sh, cap, vp[0] + 7.62, vp[1])


def follower(sh, u, unit, x, y, pins, below=True):
    """op-amp unit at (x, y) wired as a voltage follower (output loop below the '-' input); pins = (in+, in-, out).
    Returns (in+, out) points."""
    sh.place(u, x, y, unit=unit, fields="above")
    ip, im, o = (sh.P(u, k) for k in pins)
    yl = im[1] + 5.08
    sh.w(o, (o[0] + U, o[1]), (o[0] + U, yl), (im[0] - U, yl), (im[0] - U, im[1]), im)
    return ip, (o[0] + U, o[1])


# ============================================================================ power
def sheet_power(sh):
    W = 405
    sh.heading("5 V input, analog rail, 3.3 V for the MCU", 15, 30, 180)
    y = 55.88
    d1 = by(lambda p: p.value == "B5819W")
    sh.lbl((25.4, y), "+5V_PRG", (-1, 0))
    sh.place(d1, 38.1, y, 180, fields="above")                     # A (from the programmer) left, K right
    sh.w((25.4, y), (d1, 2))
    sh.text("programmer (WCH-LinkE)", 15.24, y + 5.08, 1.27, False)
    x5 = sh.P(d1, 1)[0]
    sh.w((d1, 1), (x5 + 30.48, y))
    sh.v5((x5 + 6.35, y), stub=U)
    sh.flag((x5 + 13.97, y), "+5V")
    sh.text("from the backplane", x5 + 1.27, y + 3.81, 1.27, False)
    rf = ref("RFILT")
    p = hpart(sh, rf, x5 + 30.48, y)
    xa = p[0]
    sh.w(p, (xa + 45.72, y))
    for i in (1, 2, 3):
        vcap(sh, ref(f"CFILT{i}"), xa + 7.62 + (i - 1) * 10.16, y)
    sh.flag((xa + 35.56, y), "VA")
    tpx(sh, "VA", (xa + 40.64, y))
    sh.lbl((xa + 45.72, y), "VA", (1, 0))
    # 3.3 V LDO for the MCU, fed from +5V (not from VA)
    y2 = 86.36
    xb = x5 + 21.59
    sh.w((xb, y), (xb, y2))
    u1 = by(lambda p: p.lib_id.startswith("Regulator_Linear"))
    sh.place(u1, xb + 27.94, y2, fields="above")                   # VI at xb + 20.32
    sh.w((xb, y2), (u1, 3))
    vcap(sh, note("LDO input"), xb + 10.16, y2)
    sh.gnd((u1, 1))
    xo = sh.P(u1, 2)[0]
    sh.w((u1, 2), (xo + 25.4, y2))
    vcap(sh, note("LDO output"), xo + 7.62, y2)
    tpx(sh, "+3V3", (xo + 15.24, y2), fields="left")
    v33(sh, (xo + 25.4, y2))
    # ground test point and flag
    g = (40.64, y2 + 7.62)
    sh.place(tp("GND"), 33.02, g[1], fields="left")
    sh.w((tp("GND"), 1), g)
    sh.gnd(g)
    sh.flag(g, "GND")

    # ---- references
    sh.heading("References: VREF 2.5 V (CJ431, buffered), VBIAS 1.0 V (LM324 follower), VEXP_REF 1.25 V", 15, 108, 260)
    x = 33.02
    r2 = note("CJ431 feed, about 2.5 mA")
    sh.place(r2, x, 124.46, fields="right")                        # pin 1 at 120.65
    va(sh, (r2, 1))
    u2 = by(lambda p: p.value == "CJ431")
    yn = sh.P(r2, 2)[1] + U
    sh.place(u2, x, yn + 7.62, rot=90, fields="right")             # K top, A bottom, REF left
    sh.w((r2, 2), (u2, 2))
    rp = sh.P(u2, 1)
    sh.w(rp, (rp[0] - U, rp[1]), (rp[0] - U, yn), (x, yn))          # REF tied to K: 2.5 V
    sh.gnd((u2, 3))
    sh.w((x, yn), (x + 15.24, yn))
    sh.lbl((x + 3.81, yn), "VREF431", (1, 0))
    p = hpart(sh, ref("RFREF"), x + 15.24, yn)
    sh.w(p, (p[0] + 17.78, yn))
    sh.lbl((p[0] + 1.27, yn), "VREF_F", (1, 0))
    vcap(sh, ref("CFREF"), p[0] + 10.16, yn, fields="left")
    u3 = ref("XVREF")
    ip, o = follower(sh, u3, 1, p[0] + 25.4, yn + U, (3, 2, 1))    # + at (p + 17.78, yn)
    xr = o[0] + 116.84
    sh.w(o, (xr, o[1]))
    sh.lbl((xr, o[1]), "VREF", (1, 0))
    tpx(sh, "VREF", (o[0] + 7.62, o[1]))
    # VEXP_REF = VREF / 2: collector voltage of the expo reference transistor (unbuffered), VBIAS divider
    yv = o[1]
    for k, (ra, rb, cc, net) in enumerate((("R25A", "R25B", "C25", "VEXP_REF"), ("RBA", "RBB", "CBI", None))):
        xd = o[0] + 20.32 + k * 38.1
        a, b, c = ref(ra), ref(rb), ref(cc)
        sh.place(a, xd, yv + 3.81, fields="right")
        yd = sh.P(a, 2)[1] + U
        sh.w((a, 2), (xd, yd))
        vcap(sh, b, xd, yd)
        sh.w((xd, yd), (xd + 10.16, yd))
        vcap(sh, c, xd + 10.16, yd)
        if net:
            sh.w((xd + 10.16, yd), (xd + 22.86, yd))
            tpx(sh, "VEXP_REF", (xd + 17.78, yd))
            sh.lbl((xd + 22.86, yd), net, (1, 0))
    # VBIAS buffer: LM324 unit A
    sh.w((xd + 10.16, yd), (xd + 25.4, yd))
    sh.lbl((xd + 11.43, yd), "VBIAS_DIV", (1, 0))
    ip2, o2 = follower(sh, ref("XVB"), 1, xd + 33.02, yd + U, (3, 2, 1))
    sh.w(o2, (o2[0] + 17.78, o2[1]))
    tpx(sh, "VBIAS", (o2[0] + 7.62, o2[1]))
    sh.lbl((o2[0] + 17.78, o2[1]), "VBIAS", (1, 0))
    supply(sh, u3, 3, 254.0, yn + 12.7, dec(u3))

    # ---- ladder bias chain
    sh.heading("Ladder bias chain (from VA: VB0...VB4 = 1.7...4.4 V)", 275, 30, W)
    x, ytop = 335.28, 45.72
    va(sh, (x, ytop))
    chain = [("RB5", "VB4", "CB4"), ("RB4", "VB3", "CB3"), ("RB3", "VB2", "CB2"), ("RB2", "VB1", "CB1"),
             ("RB1", "VB0", "CB0"), ("RB0", None, None)]
    yp, taps = ytop, []
    for sim, tap, cap in chain:
        r = ref(sim)
        sh.place(r, x, yp + 3.81, fields="right")
        yb = sh.P(r, 2)[1]
        if tap is None:
            sh.gnd((r, 2))
            break
        sh.w((r, 2), (x, yb + U))
        sh.w((x, yb), (x - 20.32, yb)); sh.lbl((x - 20.32, yb), tap, (-1, 0))
        if tap in ("VB0", "VB2", "VB4"):
            tpx(sh, tap, (x - 10.16, yb), fields="left")
        sh.w((x, yb), (x + 12.7, yb))
        hpart(sh, ref(cap), x + 12.7, yb, fields="above")
        sh.w((ref(cap), 2), (x + 25.4, yb))                        # caps to a common ground line
        taps.append(yb)
        yp = yb + U
    sh.w((x + 25.4, taps[0]), (x + 25.4, taps[-1] + 5.08))
    sh.gnd((x + 25.4, taps[-1] + 5.08))


# ============================================================================ MCU
def stub(sh, p, d, net, n=2):
    """wire of n grid steps from p in direction d, ending in a label (or a power symbol for supply nets)"""
    q = (p[0] + d[0] * n * U, p[1] + d[1] * n * U)
    sh.w(p, q)
    if net in ("GND", "+5V", "+3V3"):
        sh.pwr(q, net, d)
    else:
        sh.lbl(q, net, d)
    return q


def bus_row(sh, r, x, y, left, right, flip=False, tpnet=None, pull=None):
    """label left -> horizontal resistor -> node -> label right; pull = (part, 'up' or 'down', supply)"""
    sh.lbl((x, y), left, (-1, 0))
    sh.w((x, y), (x + 5.08, y))
    p = hpart(sh, r, x + 5.08, y, flip=flip)
    xe = p[0] + 25.4
    sh.w(p, (xe, y))
    sh.lbl((xe, y), right, (1, 0))
    if pull:
        rp, way, net = pull
        if way == "down":
            vcap(sh, rp, p[0] + 7.62, y, gnd=(net == "GND"))
        else:
            vup(sh, rp, p[0] + 7.62, y)
            v33(sh, (rp, 2))
    if tpnet:
        tpx(sh, tpnet, (p[0] + 15.24, y))
    return p


def tp_lbl(sh, net, x, y, k=0):
    """test point at (x, y) with a short wire to a label on its right"""
    sh.place(tp(net, k), x, y, fields="left")
    sh.w((x, y), (x + 7.62, y))
    sh.lbl((x + 7.62, y), net, (1, 0))


def sheet_mcu(sh):
    W = 405
    sh.heading("MCU (CH32V006F8P7, hand-soldered)", 15, 30, 150)
    u = by(lambda p: p.lib_id.startswith("MCU_WCH"))
    part = D.PARTS[[q.ref for q in D.PARTS].index(u)]
    xm, ym = 78.74, 91.44
    sh.place(u, xm, ym, fields=(3.81, 22.86))
    for num in range(1, 21):
        if num in (7, 9):
            continue
        x, y = sh.P(u, num)
        stub(sh, (x, y), (-1, 0) if x < xm else (1, 0), part.pins[str(num)])
    sh.gnd((u, 7))
    vdd = sh.P(u, 9)
    yv = vdd[1] - 12.7
    sh.w(vdd, (vdd[0], yv - U))
    v33(sh, (vdd[0], yv - U))
    sh.w((vdd[0], yv), (vdd[0] + 20.32, yv))
    vcap(sh, note("MCU decoupling"), vdd[0] + 10.16, yv)
    vcap(sh, note("MCU bulk"), vdd[0] + 20.32, yv)
    sh.text("PWM_PAN (PC5, TIM2 CH1): pan bias, vca sheet", 20.32, 132.08, 1.27, False)
    sh.text("TIM1_RM 0010 (CH1...CH4 = PC6, PC7, PC0, PD3), TIM2_RM 010 (CH1 = PC5, CH2 = PC2, CH4 = PC1)", 20.32,
            135.89, 1.27, False)
    sh.text("USART1 default (TX PD5 open drain, RX PD6); PA4 is bonded to PD7 (NRST): never an output", 20.32,
            139.7, 1.27, False)

    # ---- backplane connector
    sh.heading("Backplane connector and voice bus", 160, 30, W)
    j1 = by(lambda p: p.value == "BACKPLANE")
    jp = D.PARTS[[q.ref for q in D.PARTS].index(j1)]
    xj, yj = 200.66, 71.12
    sh.place(j1, xj, yj, fields="above")
    for num in range(1, 17):
        net = jp.pins[str(num)]
        x, y = sh.P(j1, num)
        d = (-1, 0) if x < xj else (1, 0)
        if net.startswith("NC_"):
            continue
        if net == "+5V":
            q = (x + d[0] * 5.08, y)
            sh.w((x, y), q)
            sh.v5(q)
        elif net == "GND" and num in (4, 6, 8):                  # adjacent ground pins: joined (6 = AUDIO_GND)
            sh.w((x, y), (x + U, y))
        elif net == "GND":
            sh.w((x, y), (x + d[0] * U, y))
            sh.pwr((x + d[0] * U, y), "GND", d)
        else:
            stub(sh, (x, y), d, net, n=4)
    g4, g8 = sh.P(j1, 4), sh.P(j1, 8)
    sh.w((g4[0] + U, g4[1]), (g8[0] + U, g8[1]))
    sh.pwr((g4[0] + U, sh.P(j1, 6)[1]), "GND", (1, 0))
    sh.text("pin 6 = AUDIO_GND (from the line-out ground)", xj - 12.7, yj + 17.78, 1.27, False)
    # bus series resistors, pull-ups / pull-downs
    xb = 254.0
    bus_row(sh, nets(_1="RX", _2="RX_IN"), xb, 55.88, "RX", "RX_IN",
            pull=(nets(_1="RX_IN", _2="+3V3"), "up", "+3V3"))
    bus_row(sh, nets(_1="SYNC", _2="SYNC_IN"), xb, 71.12, "SYNC", "SYNC_IN", tpnet="SYNC_IN",
            pull=(nets(_1="SYNC_IN", _2="GND"), "down", "GND"))
    bus_row(sh, nets(_1="TX_OUT", _2="TX"), xb, 91.44, "TX", "TX_OUT", flip=True)
    y = 104.14
    sh.lbl((xb, y), "NRST", (-1, 0))
    sh.w((xb, y), (xb + 38.1, y))
    sh.lbl((xb + 38.1, y), "NRST", (1, 0))
    vcap(sh, note("NRST filter (option)"), xb + 12.7, y)
    tpx(sh, "NRST", (xb + 22.86, y))
    sh.text("RX idle high and SYNC low when unplugged (standalone detection); TX: PD5 open drain, pull-up on the "
            "backplane", xb - 7.62, 124.46, 1.27, False)

    # ---- programming and line out
    sh.heading("Programming (WCH-LinkE) and line out", 15, 150, 150)
    j2 = by(lambda p: p.value == "SWIO")
    y = 175.26
    sh.place(j2, 33.02, y, mirror="y", fields="left")              # pins on the right: +5V_PRG, SWIO, GND
    p1, p2, p3 = sh.P(j2, 1), sh.P(j2, 2), sh.P(j2, 3)
    sh.w(p1, (p1[0] + 20.32, p1[1])); sh.lbl((p1[0] + 20.32, p1[1]), "+5V_PRG", (1, 0))
    sh.w(p2, (p2[0] + 20.32, p2[1])); sh.lbl((p2[0] + 20.32, p2[1]), "SWIO", (1, 0))
    sh.w(p3, (p3[0] + 5.08, p3[1])); sh.gnd((p3[0] + 5.08, p3[1]))
    t = tp("SWIO")
    sh.place(t, p2[0] + 12.7, p2[1] + 7.62, rot=180, fields="right")    # body below the wire
    sh.w((t, 1), (p2[0] + 12.7, p2[1]))
    j3 = by(lambda p: p.value == "LINE OUT")
    sh.place(j3, 99.06, y, mirror="y", fields="left")
    q1, q2, q3 = sh.P(j3, 1), sh.P(j3, 2), sh.P(j3, 3)
    sh.w(q1, (q1[0] + 15.24, q1[1])); sh.lbl((q1[0] + 15.24, q1[1]), "AUDIO_L", (1, 0))
    sh.w(q2, (q2[0] + 15.24, q2[1])); sh.lbl((q2[0] + 15.24, q2[1]), "AUDIO_R", (1, 0))
    sh.w(q3, (q3[0] + 5.08, q3[1])); sh.gnd((q3[0] + 5.08, q3[1]))
    sh.text("two 1x3 right-angle headers on the debug edge (line out: L, R, GND)", 20.32, 200.66, 1.27, False)

    # ---- LEDs
    sh.heading("LEDs (debug edge)", 160, 150, 270)
    rows = [("power LED series", None), ("playing LED series", "LED_PLAY"), ("status LED series", "LED_STAT")]
    for i, (n, net) in enumerate(rows):
        y = 170.18 + i * 12.7
        x1 = 187.96
        r = note(n)
        rp = D.PARTS[[q.ref for q in D.PARTS].index(r)]
        if net:
            sh.lbl((x1, y), net, (-1, 0))
        else:
            sh.w((x1 - 5.08, y), (x1, y))
            v33(sh, (x1 - 5.08, y))
        a = hpart(sh, r, x1, y)
        led = by(lambda p: p.lib_id == "Device:LED" and p.pins["2"] == rp.pins["2"])
        sh.place(led, a[0] + 20.32, y, rot=180, fields="above")      # A left, K right
        sh.w(a, sh.P(led, 2))
        sh.lbl((a[0] + 2.54, y), rp.pins["2"], (1, 0))
        k = sh.P(led, 1)
        sh.w(k, (k[0] + 5.08, y)); sh.gnd((k[0] + 5.08, y))

    # ---- options
    sh.heading("Options (not fitted, DNP)", 280, 150, W)
    x1 = 302.26
    for i, (r, a, b) in enumerate(((nets(_1="CLK_IN", _2="CLK_SEL"), "CLK_IN", "CLK_SEL"),
                                   (nets(_1="VB0", _2="ST_VB0"), "VB0", "ST_VB0"),
                                   (nets(_1="VA", _2="ST_RAIL"), "VA", "ST_RAIL"))):
        y = 170.18 + i * 12.7
        sh.lbl((x1, y), a, (-1, 0))
        p = hpart(sh, r, x1, y)
        sh.w(p, (p[0] + 20.32, y))
        sh.lbl((p[0] + 20.32, y), b, (1, 0))
        if b == "ST_RAIL":
            vcap(sh, nets(_1="ST_RAIL", _2="GND"), p[0] + 7.62, y)
    sh.text("CLK_IN: external clock from the backplane MCO (fallback, spec 6)", 285.75, 215.9, 1.27, False)
    sh.text("ST_VB0, ST_RAIL: self-test of the ladder bias and the analog rail / 2 at power-up", 285.75, 219.71,
            1.27, False)


# ============================================================================ DAC
def sheet_dac(sh):
    sh.heading("Reconstruction filter (2-pole Sallen-Key, Butterworth, 31 kHz, C0G)", 15, 30, 135)
    y = 71.12
    sh.lbl((25.4, y), "PWM_DAC", (-1, 0))
    sh.w((25.4, y), (30.48, y))
    p = hpart(sh, ref("RSK1"), 30.48, y)                          # SK1 at 38.1
    xs1 = p[0] + 7.62
    sh.w(p, (xs1 + 7.62, y))
    sh.lbl((p[0] + 1.27, y), "SK1", (1, 0))
    p = hpart(sh, ref("RSK2"), xs1 + 7.62, y)                     # SK2
    u = ref("XSK")
    sh.place(u, p[0] + 27.94, y + U, unit=2, fields="above")       # + at (p + 20.32, y); unit A buffers VREF
    ip, im, o = sh.P(u, 5), sh.P(u, 6), sh.P(u, 7)
    sh.w(p, ip)
    sh.lbl((p[0] + 1.27, y), "SK2", (1, 0))
    vcap(sh, ref("CSK2"), p[0] + 7.62, y)
    yl = im[1] + 7.62
    sh.w(o, (o[0] + U, o[1]), (o[0] + U, yl), (im[0] - U, yl), (im[0] - U, im[1]), im)
    # C1 = 2 x 330 pF from SK1 to the output
    yc1, yc2 = y - 17.78, y - 27.94
    xc = xs1 + 15.24
    sh.w((xs1, y), (xs1, yc2), (xc, yc2))
    sh.w((xs1, yc1), (xc, yc1))
    hpart(sh, ref("CSK1A"), xc, yc1)
    hpart(sh, ref("CSK1B"), xc, yc2)
    xf = o[0] + 7.62
    sh.w((xc + 7.62, yc2), (xc + 12.7, yc2), (xc + 12.7, yc1))
    sh.w((xc + 7.62, yc1), (xf, yc1), (xf, o[1]))
    sh.w((o[0] + U, o[1]), (xf + 20.32, o[1]))
    tpx(sh, "DAC_F", (xf + 7.62, o[1]))
    sh.lbl((xf + 11.43, o[1]), "DAC_F", (1, 0))
    sh.text("unity gain; C1 = 2 x 330 pF (feedback), C2 = 330 pF, all C0G; fc = 31 kHz", 20.32, y + 22.86, 1.27,
            False)
    sh.text("op-amp: the second unit of the VREF buffer's MCP6002 (supply on the power sheet)", 20.32, y + 26.67,
            1.27, False)

    # ---- mixer
    sh.heading("Mixer into the ladder input", 145, 30, 260)
    xm = xf + 20.32
    p = hpart(sh, ref("RMIX"), xm, o[1])
    sh.w(p, (p[0] + 10.16, o[1]))
    sh.lbl((p[0] + 1.27, o[1]), "MIX", (1, 0))
    rmx = ref("RMX")
    sh.place(rmx, p[0] + 5.08, o[1] + 3.81, fields="right")
    sh.lbl((rmx, 2), "VB0", (0, 1), stub=U)
    q = hpart(sh, ref("CMX"), p[0] + 10.16, o[1])
    sh.w(q, (q[0] + 10.16, o[1]))
    sh.lbl((q[0] + 10.16, o[1]), "BIN1", (1, 0))
    sh.text("DAC 0...3.3 V through 240k, biased to VB0, AC-coupled into the ladder input (vcf)", xm - 2.54,
            o[1] + 22.86, 1.27, False)

    # ---- dual-PWM option
    sh.heading("Dual-PWM option: low byte (TIM2 CH4) into the filter input, 1.33 MΩ = 120.9 x 11k (overlap, spec 3.5)",
               15, 150, 260)
    y = 172.72
    sh.lbl((25.4, y), "PWM_LO", (-1, 0))
    sh.w((25.4, y), (30.48, y))
    p = hpart(sh, nets(_1="PWM_LO", _2="LO_A"), 30.48, y)
    sh.w(p, (p[0] + 7.62, y))
    sh.lbl((p[0] + 1.27, y), "LO_A", (1, 0))
    p = hpart(sh, nets(_1="LO_A", _2="SK1"), p[0] + 7.62, y)
    sh.w(p, (p[0] + 7.62, y))
    sh.lbl((p[0] + 7.62, y), "SK1", (1, 0))
    sh.text("not fitted (DNP): the default build drives only TIM2 CH2", 20.32, y + 10.16, 1.27, False)



# ============================================================================ VCF
def sheet_vcf(sh):
    W = 405
    sh.heading("CV_CUT filter and exponential converter (tail current of the ladder)", 15, 30, 250)
    y = 55.88
    sh.lbl((30.48, y), "PWM_CUT", (-1, 0))
    r1, c1, r2, c2, r33, r12, c12 = (ref(s) for s in ("R1C", "C1C", "R2C", "C2C", "R33X", "R12X", "C12X"))
    p = hpart(sh, r1, 30.48, y); sh.w(p, (p[0] + 10.16, y)); vcap(sh, c1, p[0] + 5.08, y)
    sh.lbl((p[0] + 1.27, y), "CVC_A", (1, 0))
    p = hpart(sh, r2, p[0] + 10.16, y); sh.w(p, (p[0] + 5.08, y)); vcap(sh, c2, p[0] + 5.08, y)
    xin = p[0] + 5.08
    tpx(sh, "XCUT_IN", (xin + 5.08, y))
    p = hpart(sh, r33, xin + 17.78, y); sh.w((xin, y), (xin + 17.78, y))
    sh.lbl((xin + 7.62, y), "XCUT_IN", (1, 0))
    xx = p[0] + 5.08
    sh.w(p, (xx + 30.48, y))
    vcap(sh, r12, xx, y, gnd=False); sh.lbl((r12, 2), "VBIAS", (0, 1), stub=U)
    vcap(sh, c12, xx + 10.16, y, gnd=False); sh.lbl((c12, 2), "VBIAS", (0, 1), stub=U)
    sh.lbl((xx + 15.24, y), "XCUT", (1, 0))
    # expo pair: QEA (reference, base at VBIAS), QEB (output, base at XCUT), both bases left
    qe = ref("QEA")
    xq = xx + 50.8
    sh.place(qe, xq, 86.36, unit=1, fields="right")                  # QEA
    sh.place(qe, xq + 22.86, y, unit=2, fields="right")               # QEB, base on the XCUT line
    sh.w((xx + 30.48, y), sh.P(qe, 5))
    ea, eb = sh.P(qe, 1), sh.P(qe, 4)
    sh.lbl(sh.P(qe, 2), "VBIAS", (-1, 0), stub=5.08)
    ye = ea[1] + 7.62
    sh.w(ea, (ea[0], ye), (eb[0], ye), eb)
    sh.lbl(sh.P(qe, 3), "TAIL", (0, -1), stub=U)
    # reference current: VREF -> 470k -> collector of QEA = inverting input of LM324 unit C
    ca = sh.P(qe, 6)
    rref = ref("RREF")
    sh.place(rref, ca[0], ca[1] - 3.81 - U, 0, fields="left"); sh.w(ca, (rref, 2))
    sh.lbl((rref, 1), "VREF", (0, -1), stub=U)
    lm = by(lambda p: p.lib_id.endswith("LM324"))
    xo = ca[0] + 45.72
    sh.place(lm, xo, ca[1] - U + 5.08, unit=3, mirror="x", fields="below")    # inverting input on top
    im, ip, o = sh.P(lm, 9), sh.P(lm, 10), sh.P(lm, 8)
    sh.w((ca[0], ca[1] - U), (im[0] - 10.16, ca[1] - U), (im[0] - 10.16, im[1]), im)
    sh.lbl((ca[0] + 2.54, ca[1] - U), "EXPO_NA", (1, 0))
    sh.lbl(ip, "VEXP_REF", (-1, 0), stub=5.08)
    cexp, rexp = ref("CEXP"), ref("REXP")
    yc = im[1] - 10.16
    hpart(sh, cexp, im[0] - 5.08, yc, flip=True)                       # pin 2 (NA) left, pin 1 (OUT) right
    sh.w((im[0] - 10.16, im[1]), (im[0] - 10.16, yc), sh.P(cexp, 2))
    sh.w(sh.P(cexp, 1), (o[0] + U, yc), (o[0] + U, o[1]), o)
    # output -> 1k -> emitters
    sh.w((o[0] + U, o[1]), (o[0] + U, ye + 7.62))
    hpart(sh, rexp, o[0] + U - 7.62, ye + 7.62, flip=True)             # pin 1 (OUT) right, pin 2 (E) left
    sh.w(sh.P(rexp, 2), ((ea[0] + eb[0]) / 2, ye + 7.62), ((ea[0] + eb[0]) / 2, ye))
    # LM324: supply
    supply(sh, lm, 5, 210.82, 142.24, by(lambda p: p.note == "LM324 decoupling"))
    sh.text("LM324 unit A: VBIAS buffer (power); units B and D: VCA and resonance V-to-I", 132.08, 160.02, 1.27,
            False)

    # ---- ladder
    sh.heading("Transistor ladder (4 poles, 4 x 10 nF), bias from VB0...VB4", 262, 30, W)
    xa, y0 = 335.28, 200.66
    gap = 30.48
    stages = ["Q1", "Q3", "Q5", "Q7", "Q9"]
    caps = ["CL1", "CL2", "CL3", "CL4"]
    ys = [y0 - k * 22.86 for k in range(5)]
    for k, sim in enumerate(stages):
        q = ref(sim)
        sh.place(q, xa, ys[k], unit=1, fields="right")
        sh.place(q, xa + gap, ys[k], unit=2, mirror="y", fields="left")
        e1_, b1_ = sh.P(q, 1), sh.P(q, 2)
        e2_, b2_ = sh.P(q, 4), sh.P(q, 5)
        if k == 0:
            yt = e1_[1] + U
            sh.w(e1_, (e1_[0], yt), (e2_[0], yt), e2_)
            xm = (e1_[0] + e2_[0]) / 2
            sh.w((xm, yt), (xm, yt + 5.08)); sh.lbl((xm, yt + 5.08), "TAIL", (0, 1))
            t = tp("TAIL")
            sh.place(t, xm + 7.62, yt + 5.08, rot=180, fields="right")     # body below the wire
            sh.w((t, 1), (xm + 7.62, yt)); sh.w((xm, yt), (xm + 7.62, yt))
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
        if k == 4:
            va(sh, sh.P(q, 6)); va(sh, sh.P(q, 3))
    # top nodes N4A / N4B to the instrumentation amplifier
    q3, q4 = ref("Q7"), ref("Q9")
    n4a = (sh.P(q3, 6)[0], (sh.P(q3, 6)[1] + sh.P(q4, 1)[1]) / 2)
    n4b = (sh.P(q3, 3)[0], n4a[1])
    sh.w(n4a, (n4a[0] - 12.7, n4a[1])); sh.lbl((n4a[0] - 12.7, n4a[1]), "N4A", (-1, 0))
    sh.w(n4b, (n4b[0] + 12.7, n4b[1])); sh.lbl((n4b[0] + 12.7, n4b[1]), "N4B", (1, 0))
    # inputs: BIN1 (mixer, dac sheet), BIN2 (resonance feedback), both biased to VB0
    q0 = ref("Q1")
    b1_, b2_ = sh.P(q0, 2), sh.P(q0, 5)
    rbi1, rbi2 = ref("RBI1"), ref("RBI2")
    sh.w(b1_, (b1_[0] - 17.78, b1_[1])); sh.lbl((b1_[0] - 17.78, b1_[1]), "BIN1", (-1, 0))
    sh.place(rbi1, b1_[0] - 7.62, b1_[1] + 3.81 + U, 0, fields="left"); sh.w((b1_[0] - 7.62, b1_[1]), (rbi1, 1))
    sh.lbl((rbi1, 2), "VB0", (0, 1), stub=U)
    sh.w(b2_, (b2_[0] + 17.78, b2_[1])); sh.lbl((b2_[0] + 17.78, b2_[1]), "BIN2", (1, 0))
    sh.place(rbi2, b2_[0] + 7.62, b2_[1] + 3.81 + U, 0, fields="right"); sh.w((b2_[0] + 7.62, b2_[1]), (rbi2, 1))
    sh.lbl((rbi2, 2), "VB0", (0, 1), stub=U)

    # ---- instrumentation amplifier (two op-amp INA, G = 11)
    sh.heading("Output instrumentation amplifier across the top capacitor (G = 11, referenced to VREF)", 15, 175, 250)
    u = ref("XINA1")
    sh.place(u, 60.96, 210.82, unit=1, fields="above")
    sh.place(u, 132.08, 210.82, unit=2, fields="above")
    pa, ma, oa = sh.P(u, 3), sh.P(u, 2), sh.P(u, 1)
    pb, mb, ob = sh.P(u, 5), sh.P(u, 6), sh.P(u, 7)
    sh.lbl(pa, "N4A", (-1, 0), stub=7.62)
    sh.lbl(pb, "N4B", (-1, 0), stub=5.08)
    ri1, ri2, ri3, ri4 = ref("RI1"), ref("RI2"), ref("RI3"), ref("RI4")
    xm = ma[0] - U
    sh.w(ma, (xm, ma[1]), (xm, ma[1] + 7.62))
    hpart(sh, ri2, xm, ma[1] + 7.62, flip=True); sh.w(sh.P(ri2, 1), (oa[0] + U, ma[1] + 7.62), (oa[0] + U, oa[1]), oa)
    sh.w((xm, ma[1] + 7.62), (xm, ma[1] + 12.7))
    sh.place(ri1, xm, ma[1] + 12.7 + 3.81, 0, fields="left"); sh.lbl((ri1, 2), "VREF", (0, 1), stub=U)
    sh.w((oa[0] + U, oa[1]), (oa[0] + 12.7, oa[1]))
    hpart(sh, ri3, oa[0] + 12.7, oa[1]); sh.w(sh.P(ri3, 2), (mb[0] - U, oa[1]), (mb[0] - U, mb[1]), mb)
    xmb = mb[0] - U
    sh.w((xmb, mb[1]), (xmb, mb[1] + 7.62))
    hpart(sh, ri4, xmb, mb[1] + 7.62, flip=True)
    sh.w(sh.P(ri4, 1), (ob[0] + U, mb[1] + 7.62), (ob[0] + U, ob[1]), ob)
    sh.w((ob[0] + U, ob[1]), (ob[0] + 20.32, ob[1])); sh.lbl((ob[0] + 20.32, ob[1]), "LPF", (1, 0))
    tpx(sh, "LPF", (ob[0] + 10.16, ob[1]))
    supply(sh, u, 3, 205.74, 210.82, dec(u))


# ============================================================================ shared: CV filter + V->I
def cv_vi(sh, n, x0, y, opamp, unit, pins, extra_emitter=None):
    """PWM label -> 1k/100n -> 4k7/33n -> 4k7/(R4||22n) -> LM324 follower -> NPN (collector up) with Re.
    pins = (in+, in-, out) of the op-amp unit. Returns the collector point."""
    sh.lbl((x0, y), PWM[n], (-1, 0))
    r1, c1, r2, c2, r3, r4, c3 = (ref(f"{k}{n}") for k in ("R1", "C1", "R2", "C2", "R3", "R4", "C3"))
    p = hpart(sh, r1, x0, y)
    sh.w(p, (p[0] + 10.16, y)); vcap(sh, c1, p[0] + 5.08, y)
    sh.lbl((p[0] + 1.27, y), f"CV{n}_A", (1, 0))
    p = hpart(sh, r2, p[0] + 10.16, y)
    sh.w(p, (p[0] + 10.16, y)); vcap(sh, c2, p[0] + 5.08, y)
    sh.lbl((p[0] + 1.27, y), f"CV{n}_B", (1, 0))
    p = hpart(sh, r3, p[0] + 10.16, y)
    xn = p[0] + 5.08
    sh.w(p, (xn + 22.86, y))
    vcap(sh, r4, xn, y, fields="left"); vcap(sh, c3, xn + 7.62, y)
    x_net = "XRES" if n == "R" else "XVCA"
    tpx(sh, x_net, (xn + 15.24, y))
    xo = xn + 30.48
    sh.place(opamp, xo, y + U, unit=unit, fields="above")        # + input at (xo - 7.62, y)
    out = sh.P(opamp, pins[2])
    sh.w(out, (out[0] + 10.16, out[1]))
    sh.lbl((out[0] + 1.27, out[1]), f"VI{n}_OUT", (1, 0))
    pb = hpart(sh, ref(f"RBV{n}"), out[0] + 10.16, out[1])
    q = ref(f"QV{n}")
    sh.place(q, pb[0] + 12.7, pb[1], fields="right")             # base at pb + 7.62
    sh.w(pb, (q, 1))
    sh.lbl((pb[0] + 1.27, pb[1]), f"VI{n}_B", (1, 0))
    e = sh.P(q, 2)
    mi = sh.P(opamp, pins[1])
    yb = e[1] + 5.08
    sh.w(mi, (mi[0] - U, mi[1]), (mi[0] - U, yb), (e[0], yb), e)
    vcap(sh, ref(f"REV{n}"), e[0], yb)
    if extra_emitter:
        rx = ref(extra_emitter)
        sh.w((e[0], yb), (e[0] + 17.78, yb))
        sh.place(rx, e[0] + 17.78, yb - 3.81, fields="right")
        sh.lbl((rx, 1), "VREF", (0, -1), stub=U)
    return sh.P(q, 3)


def pair(sh, sim, x, y, gap=25.4, f2=None):
    """BC847BS as a differential pair: unit 1 at x, unit 2 mirrored at x + gap (fields between the two, or at
    the offset f2 from unit 2); returns the part and its pins"""
    q = ref(sim)
    sh.place(q, x, y, unit=1, fields=(3.81, -3.81))
    sh.place(q, x + gap, y, unit=2, mirror="y", fields=f2 or (10.16 - gap, 3.81))
    return q, {k: sh.P(q, k) for k in (1, 2, 3, 4, 5, 6)}


def loads(sh, P, rc1, rc2, c_net, stub=10.16):
    """collector resistors to VA above both collectors of a pair (pins P), collector labels c_net % 1|2 outwards"""
    for k, rr, c, fl, d in ((1, rc1, P[6], "left", (-1, 0)), (2, rc2, P[3], "right", (1, 0))):
        sh.place(rr, c[0], c[1] - 5.08 - 3.81, 0, fields=fl); sh.w(c, (rr, 2))
        va(sh, (rr, 1))
        e = (c[0] + d[0] * stub, c[1] - U)
        sh.w((c[0], c[1] - U), e); sh.lbl(e, c_net % k, d)


def pair_core(sh, sim, x, y, rc1, rc2, c_net, tail, cin, rin, rb1, rb2, bias, in_net, ri_net, gap=25.4, f2=None):
    """differential pair with emitters to the tail label; collector resistors to VA and collector labels
    c_net % 1|2 (rc1 = None: collectors left open, for a stacked stage); base 1: LPF -> cin -> rin -> base, both
    bases biased through rb1 / rb2. Returns (pins, base-1 drop x)."""
    q, P = pair(sh, sim, x, y, gap, f2)
    yt = P[1][1] + 5.08
    sh.w(P[1], (P[1][0], yt), (P[4][0], yt), P[4])
    xm = (P[1][0] + P[4][0]) / 2
    sh.w((xm, yt), (xm, yt + 5.08)); sh.lbl((xm, yt + 5.08), tail, (0, 1))
    if rc1:
        loads(sh, P, rc1, rc2, c_net)
    b1, b2 = P[2], P[5]
    x1 = b1[0] - 12.7
    sh.w(b1, (x1, b1[1]))
    sh.lbl((x1 + 1.27, b1[1]), in_net % 1, (1, 0))
    p = hpart(sh, rin, x1 - 7.62, b1[1])
    sh.w((x1 - 7.62, b1[1]), (x1 - 17.78, b1[1]))
    sh.lbl((x1 - 16.51, b1[1]), ri_net, (1, 0))
    hpart(sh, cin, x1 - 25.4, b1[1])
    sh.lbl(sh.P(cin, 1), "LPF", (-1, 0), stub=U)
    xd = b1[0] - 10.16
    sh.place(rb1, xd, b1[1] + 3.81 + 2 * U, 0, fields="right"); sh.w((xd, b1[1]), (rb1, 1))
    sh.lbl((rb1, 2), bias, (0, 1), stub=U)
    xd2 = b2[0] + 10.16
    sh.w(b2, (xd2, b2[1]))
    sh.lbl((b2[0] + 1.27, b2[1]), in_net % 2, (1, 0))
    sh.place(rb2, xd2, b2[1] + 3.81 + 2 * U, 0, fields="right"); sh.w((xd2, b2[1]), (rb2, 1))
    sh.lbl((rb2, 2), bias, (0, 1), stub=U)
    return P, xd


def diff_amp(sh, opamp, unit, pins, rm, rf, rp, rr, x, y, net_m, net_p, dm, dp, rgm=None, rgp=None):
    """4-resistor difference amplifier, op-amp mirrored so '-' is on top: net_m -> rm into '-' (optional rgm to
    ground), feedback rf above; the '+' node is a line below with rr (to VREF) and the optional rgp (to ground)
    hanging down, net_p -> rp from the left. Returns the output point (after a short stub)."""
    sh.place(opamp, x, y, unit=unit, mirror="x", fields="below")
    ip, im, o = (sh.P(opamp, k) for k in pins)
    rm, rf, rp, rr = ref(rm), ref(rf), ref(rp), ref(rr)
    p = hpart(sh, rm, im[0] - 30.48, im[1])
    sh.lbl(sh.P(rm, 1), net_m, (-1, 0), stub=U)
    sh.w(p, im)
    sh.lbl((p[0] + 1.27, im[1]), dm, (1, 0))
    if rgm:
        vcap(sh, ref(rgm), im[0] - 10.16, im[1], fields="left")
    xm = im[0] - U
    yt = im[1] - 7.62
    pr = hpart(sh, rf, xm + U, yt)                     # pin 1 left (the '-' node), pin 2 right (output)
    sh.w((xm, im[1]), (xm, yt), sh.P(rf, 1))
    sh.w(pr, (o[0] + U, yt), (o[0] + U, o[1]), o)
    yq = ip[1] + 12.7
    xv = ip[0] - 5.08
    xl = xv - (22.86 if rgp else 15.24)
    sh.w(ip, (xv, ip[1]), (xv, yq), (xl, yq))
    sh.lbl((xl + 1.27, yq), dp, (1, 0))
    sh.place(rr, xv - 5.08, yq + 3.81, fields="right"); sh.lbl((rr, 2), "VREF", (0, 1), stub=U)
    if rgp:
        vcap(sh, ref(rgp), xv - 15.24, yq)
    hpart(sh, rp, xl - 7.62, yq)
    sh.lbl(sh.P(rp, 1), net_p, (-1, 0), stub=U)
    return (o[0] + U, o[1])


# ============================================================================ resonance
def sheet_resonance(sh):
    W = 405
    sh.heading("CV_RES filter and V-to-I converter (tail current of the resonance VCA)", 15, 30, W)
    lm = by(lambda p: p.lib_id.endswith("LM324"))
    col = cv_vi(sh, "R", 30.48, 55.88, lm, 4, (12, 13, 14))
    sh.lbl(col, "RES_TAIL", (0, -1), stub=U)
    sh.heading("Resonance VCA and difference amplifier: AC-coupled feedback from the filter output into the ladder "
               "(BIN2)", 15, 105, W)
    y = 157.48
    pair_core(sh, "QR1", 96.52, y, ref("RRC1"), ref("RRC2"), "RES_C%d", "RES_TAIL", ref("CRI"), ref("RRA"),
              ref("RRB1"), ref("RRB2"), "VB2", "RES_IN%d", "RES_RI")
    u = ref("XRDIF")
    out = diff_amp(sh, u, 1, (3, 2, 1), "RRD1", "RRD2", "RRD3", "RRD4", 236.22, 152.4, "RES_C1", "RES_C2",
                   "RES_DM", "RES_DP")
    sh.w(out, (out[0] + 20.32, out[1]))
    tpx(sh, "RESOUT", (out[0] + 5.08, out[1]))
    sh.lbl((out[0] + 7.62, out[1]), "RESOUT", (1, 0))
    p = hpart(sh, ref("CRF"), out[0] + 20.32, out[1])
    sh.w(p, (p[0] + 10.16, p[1]))
    sh.lbl((p[0] + 1.27, p[1]), "RES_FB", (1, 0))
    p = hpart(sh, ref("RRF"), p[0] + 10.16, p[1])
    sh.lbl(p, "BIN2", (1, 0), stub=7.62)
    sh.text(f"{u} unit B (VCA difference amplifier L) and the supply unit: vca sheet", 203.2, 190.5, 1.27, False)


# ============================================================================ VCA
def sheet_vca(sh):
    W = 405
    sh.heading("CV_VCA filter and V-to-I converter (240k from VREF: no current at CV = 0)", 15, 30, 258)
    lm = by(lambda p: p.lib_id.endswith("LM324"))
    col = cv_vi(sh, "V", 30.48, 55.88, lm, 2, (5, 6, 7), extra_emitter="ROFFV")
    sh.lbl(col, "VCA_TAIL", (0, -1), stub=U)
    # ---- trim
    sh.heading("VCA trim (TIM1 CH1 PWM, 2-pole RC, 680k into vin2)", 270, 30, W)
    y = 55.88
    x0 = 287.02
    sh.lbl((x0, y), "PWM_TRIM", (-1, 0))
    p = hpart(sh, ref("RTR1"), x0, y)
    sh.w(p, (p[0] + 10.16, y)); vcap(sh, ref("CTR1"), p[0] + 5.08, y)
    sh.lbl((p[0] + 1.27, y), "TRIM_A", (1, 0))
    p = hpart(sh, ref("RTR2"), p[0] + 10.16, y)
    sh.w(p, (p[0] + 22.86, y)); vcap(sh, ref("CTR2"), p[0] + 5.08, y)
    tpx(sh, "VTRIM", (p[0] + 12.7, y))
    sh.lbl((p[0] + 22.86, y), "VTRIM", (1, 0))

    # ---- pan bias: PAN_B = VREF + p, p from the PC5 PWM through a passive network (S13 variant A)
    sh.heading("Pan bias (PC5, TIM2 CH1): PAN_B = VREF -143...+149 mV, 66 Hz", 270, 76.2, W)
    yn = 96.52
    sh.lbl((x0, yn), "PWM_PAN", (-1, 0))
    p = hpart(sh, ref("RPB"), x0, yn)
    sh.w(p, (p[0] + 43.18, yn))
    rpa, rpc = ref("RPA"), ref("RPC")
    sh.place(rpa, p[0] + 7.62, yn - 3.81, fields="left")         # pin 1 (VREF) up, pin 2 on the PAN_B line
    sh.lbl((rpa, 1), "VREF", (0, -1), stub=U)
    sh.place(rpc, p[0] + 17.78, yn - 3.81, fields="right")
    v33(sh, (rpc, 1), stub=U)
    vcap(sh, ref("CPN"), p[0] + 27.94, yn)
    sh.lbl((p[0] + 43.18, yn), "PAN_B", (1, 0))
    sh.text("to the R bases of the steering pairs", p[0] + 35.56, yn + 5.08, 1.27, False)

    # ---- VCA core with the steering pairs stacked on its collectors
    sh.heading("VCA core (base bias VCA_BIAS 1.89 V) and steering pairs: L bases on VREF, R bases on PAN_B", 15, 111.76,
               195)
    y = 167.64
    P, xd = pair_core(sh, "QA1", 96.52, y, None, None, None, "VCA_TAIL", ref("CVI"), ref("RVA"),
                      ref("RVB1"), ref("RVB2"), "VCA_BIAS", "VCA_IN%d", "VCA_VI", gap=60.96,
                      f2=(-13.97, -3.81))
    rtrf, rtrm = ref("RTRF"), ref("RTRM")
    b1, b2 = P[2], P[5]
    sh.w((xd, b1[1] + U), (xd - 10.16, b1[1] + U))
    sh.place(rtrf, xd - 10.16, b1[1] + U + 3.81, 0, fields="left"); sh.gnd((rtrf, 2))
    xt = b2[0] + 10.16
    sh.w((xt, b2[1]), (xt + 5.08, b2[1]))
    hpart(sh, rtrm, xt + 5.08, b2[1], flip=True)                    # pin 2 (base side) left, pin 1 (VTRIM) right
    sh.lbl(sh.P(rtrm, 1), "VTRIM", (1, 0), stub=U)
    # steering pairs, emitters on the VCA collectors; loads 4.7k to VA, collector labels to the difference amps
    for k, sim, c in ((1, "QSL1", P[6]), (2, "QSL2", P[3])):
        q, S = pair(sh, sim, c[0] - 10.16, y - 20.32, gap=20.32, f2=(3.81, -5.08))
        ye = S[1][1] + U
        sh.w(S[1], (S[1][0], ye), (S[4][0], ye), S[4])
        sh.w((c[0], ye), c)
        sh.lbl((c[0], c[1] - U), f"VCA_C{k}", (1, 0))
        sh.lbl(S[2], "VREF", (-1, 0), stub=U)
        sh.lbl(S[5], "PAN_B", (1, 0), stub=U)
        rl, rr = (ref(f"RVC{k}"), ref(f"RVR{k}"))
        for kk, r_, cc, fl, d, net in ((1, rl, S[6], "left", (-1, 0), f"VCA_L{k}"),
                                       (2, rr, S[3], "right", (1, 0), f"VCA_R{k}")):
            sh.place(r_, cc[0], cc[1] - 5.08 - 3.81, 0, fields=fl); sh.w(cc, (r_, 2))
            va(sh, (r_, 1))
            e = (cc[0] + d[0] * 7.62, cc[1] - U)
            sh.w((cc[0], cc[1] - U), e); sh.lbl(e, net, d)
    # VCA base bias: VREF -> 2.4k / 7.5k || 1 uF
    xb, yb = 25.4, 139.7
    rbv1, rbv2 = ref("RBV1"), ref("RBV2")
    sh.place(rbv1, xb, yb - 3.81, fields="right")
    sh.lbl((rbv1, 1), "VREF", (0, -1), stub=U)
    sh.w((rbv1, 2), (xb + 25.4, yb))
    vcap(sh, rbv2, xb, yb + U, fields="right"); sh.w((xb, yb), (xb, yb + U))
    vcap(sh, ref("CBV"), xb + 10.16, yb)
    sh.lbl((xb + 25.4, yb), "VCA_BIAS", (1, 0))
    sh.text("L = a (I1 - I2), R = (1 - a) (I1 - I2), a = 1 / (1 + exp(-p / VT))", 20.32, 198.12, 1.27, False)
    sh.text("the firmware raises CV_VCA towards the centre for constant power", 20.32, 201.93, 1.27, False)

    # ---- difference amplifier L, line out L
    sh.heading("Difference amplifier L (G = 3.0) and line out L", 205, 111.76, W)
    u = ref("XDIF")
    out = diff_amp(sh, u, 2, (5, 6, 7), "RD1", "RD2", "RD3", "RD4", 261.62, 142.24, "VCA_L1", "VCA_L2",
                   "VCA_DM", "VCA_DP", rgm="RD6", rgp="RD5")
    xo = out[0] + 20.32
    sh.w(out, (xo, out[1]))
    tpx(sh, "VCAOUT", (out[0] + 5.08, out[1]))
    sh.lbl((out[0] + 7.62, out[1]), "VCAOUT", (1, 0))
    p = hpart(sh, ref("RISO"), xo, out[1])
    sh.w(p, (p[0] + 12.7, p[1]))
    sh.lbl((p[0] + 1.27, p[1]), "VCAOUT_R", (1, 0))
    p = hpart(sh, ref("COUT"), p[0] + 12.7, out[1])
    sh.w(p, (p[0] + 17.78, out[1]))
    vcap(sh, ref("RBL"), p[0] + 7.62, out[1])
    sh.lbl((p[0] + 17.78, out[1]), "AUDIO_L", (1, 0))
    sh.text("to the line-out header and J1 pin 5 (mcu)", p[0] - 10.16, out[1] - 12.7, 1.27, False)
    supply(sh, u, 3, 386.08, 172.72, dec(u))
    # loopback divider to PC4
    xl = out[0] + 12.7
    sh.heading("Audio loopback to PC4 (ADC A2)", xl + 5.08, 172.72, 360)
    rlb1, rlb2, clb = ref("RLB1"), ref("RLB2"), ref("CLB")
    sh.w((xl, out[1]), (xl, 180.34))
    sh.place(rlb1, xl, 180.34 + 3.81, fields="left")
    yl = sh.P(rlb1, 2)[1]
    sh.w((xl, yl), (xl + 33.02, yl))
    vcap(sh, rlb2, xl + 10.16, yl); vcap(sh, clb, xl + 20.32, yl)
    sh.lbl((xl + 33.02, yl), "ADC_AUDIO", (1, 0))
    sh.text("VCAOUT x 0.6 (0...3 V) for the 3.3 V ADC", xl + 2.54, yl + 15.24, 1.27, False)

    # ---- difference amplifier R, line out R
    sh.heading("Difference amplifier R (G = 3.0) and line out R", 15, 213.36, 290)
    u = ref("XDIFR")
    out = diff_amp(sh, u, 1, (3, 2, 1), "RD1R", "RD2R", "RD3R", "RD4R", 101.6, 243.84, "VCA_R1", "VCA_R2",
                   "VCAR_DM", "VCAR_DP", rgm="RD6R", rgp="RD5R")
    xo = out[0] + 20.32
    sh.w(out, (xo, out[1]))
    tpx(sh, "VCAR_OUT", (out[0] + 5.08, out[1]))
    sh.lbl((out[0] + 7.62, out[1]), "VCAR_OUT", (1, 0))
    p = hpart(sh, ref("RISOR"), xo, out[1])
    sh.w(p, (p[0] + 12.7, p[1]))
    sh.lbl((p[0] + 1.27, p[1]), "VCAR_OUT_R", (1, 0))
    p = hpart(sh, ref("COUTR"), p[0] + 12.7, out[1])
    sh.w(p, (p[0] + 17.78, out[1]))
    vcap(sh, ref("RBLR"), p[0] + 7.62, out[1])
    sh.lbl((p[0] + 17.78, out[1]), "AUDIO_R", (1, 0))
    sh.text("to the line-out header and J1 pin 7 (mcu)", p[0] - 10.16, out[1] - 12.7, 1.27, False)
    # option: R into the loopback as well
    xl = out[0] + 12.7
    rlb3 = by(lambda q: q.note and q.note.startswith("option: R into the loopback"))
    sh.w((xl, out[1]), (xl, out[1] + 7.62))
    sh.place(rlb3, xl, out[1] + 7.62 + 3.81, fields="right")
    sh.lbl((rlb3, 2), "ADC_AUDIO", (0, 1), stub=U)
    sh.text("DNP option: L + R summed at PC4", xl + 5.08, out[1] + 20.32, 1.27, False)
    # spare unit B: follower on VREF (defined state), supply
    ip, o = follower(sh, u, 2, 241.3, 233.68 + U, (5, 6, 7))
    sh.lbl(ip, "VREF", (-1, 0), stub=5.08)
    sh.text("unit B spare: follower on VREF", 223.52, 252.73, 1.27, False)
    supply(sh, u, 3, 271.78, 238.76, dec(u))


EXTRA = {}
