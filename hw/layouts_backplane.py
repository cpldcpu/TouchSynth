"""Hand-designed sheet layouts of the backplane (backplane.py) for gen_sch2.py. Coordinates in mm (U = 2.54 mm grid).

Same approach as layouts_voice.py: parts are found by their simulation name (sim), test points by net, decoupling
caps by note, the rest by reference (fixed by docs/backplane.md), value, note or nets, so layouts survive
renumbering. Anything not placed here would be auto-placed; nets left split are auto-labelled by gen_sch2. The
PWR_FLAGs of backplane.FLAG_SHEETS are drawn on the rails of their sheets.
"""
import backplane as D
from draw import U

PAPER = {}
ROOT_GRID = (2, 130, 65, 115, 50, 58)                   # root page: 2 x 2 sheet symbols, titles wrapped
# drawn as global labels like the cross-sheet nets around them, so the label stacks stay uniform: on the bus sheet
# the bus nets at the slot sockets, on the MCU sheet the local nets at the controller and flash pins
GLOBAL = {"SYNC", "BCAST", "CLK", "FX_P14", "FX_P15", "FX_RET_L", "FX_RET_R"} | {f"NRST_{k}" for k in range(1, D.SLOTS + 1)} | \
    {"PC15", "PB0", "PB14", "LED_ACT", "BOOT0", "SPI_MISO", "FLASH_CS_N", "FLASH_WP_N", "FLASH_HOLD_N"}
PART = {p.ref: p for p in D.PARTS}


def ref(sim):
    for p in D.PARTS:
        if p.sim and sim in p.sim.split("/"):
            return p.ref
    raise KeyError(sim)


def tp(net, k=0):
    return [p.ref for p in D.PARTS if p.lib_id == "Connector:TestPoint" and p.pins["1"] == net][k]


def by(pred):
    return [p.ref for p in D.PARTS if pred(p)][0]


def note(s, k=0):
    return [p.ref for p in D.PARTS if p.note == s][k]


def nets(**pins):
    """the part whose pins carry exactly these nets (pin number -> net), e.g. nets(_1="CC1", _2="GND")"""
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


def v33(sh, p, stub=0.0):
    p = sh._pt(p)
    if stub:
        q = (p[0], p[1] - stub); sh.w(p, q); p = q
    sh.pwr(p, "+3V3", (0, -1))


def stub(sh, p, d, net, n=2):
    """wire of n grid steps from p in direction d, ending in a label (or a power symbol for supply nets)"""
    p = sh._pt(p)
    q = (p[0] + d[0] * n * U, p[1] + d[1] * n * U)
    sh.w(p, q)
    if net in D.POWER:
        sh.pwr(q, net, d)
    else:
        sh.lbl(q, net, d)
    return q


def tpx(sh, net, p, k=0, up=2 * U, fields="right"):
    """test point above the wire point p (wired down to it)"""
    t = tp(net, k)
    sh.place(t, p[0], p[1] - up, fields=fields)
    sh.w((t, 1), p)


def stub_w(sh, p, n, horiz=False):
    """wire from p by n mm (down, or right if horiz; negative: up / left); returns the end point"""
    p = sh._pt(p)
    q = (p[0] + n, p[1]) if horiz else (p[0], p[1] + n)
    sh.w(p, q)
    return q


def led_chain(sh, r, d, x, ytop, gnd=True):
    """series resistor r (pin 1 on top at (x, ytop)) above the LED d (anode up), the anode net labelled in the gap;
    returns the cathode end, one grid step below the cathode (GND there if gnd)"""
    p = vcap(sh, r, x, ytop, gnd=False)
    a = (p[0], p[1] + U)
    sh.w(p, a)
    sh.place(d, x, a[1] + 3.81, 90, fields="right")
    sh.lbl(a, PART[r].pins["2"], (1, 0))
    k = sh.P(d, 1)
    k2 = (k[0], k[1] + U)                                         # clear of the LED's arrows
    sh.w(k, k2)
    if gnd:
        sh.gnd(k2)
    return k2


def gnd_flag(sh, x, y):
    """stand-alone PWR_FLAG on GND (flag at (x, y), ground symbol 5.08 below)"""
    sh.flag((x, y), "GND")
    sh.w((x, y), (x, y + 5.08))
    sh.gnd((x, y + 5.08))


# ============================================================================ power
def sheet_power(sh):
    W = 405
    # ---- USB-C device port
    sh.heading("USB-C device port (USBD: MIDI, CDC)", 15, 30, 140)
    j1 = "J1"
    sh.place(j1, 35.56, 91.44, fields=(-15.24, -22.86))
    vb = sh.P(j1, "A4")
    yv = 71.12                                                    # VBUS_C line to JP1
    xd = vb[0] + U
    sh.w(vb, (xd, vb[1]), (xd, yv))
    # CC: 5.1k sink resistors to ground (staggered); the ESD array on labels
    for net, x in (("CC1", 60.96), ("CC2", 73.66)):
        p = sh.P(j1, {"CC1": "A5", "CC2": "B5"}[net])
        sh.w(p, (x, p[1]))
        sh.lbl((p[0] + U, p[1]), net, (1, 0))
        q = hpart(sh, nets(_1=net, _2="GND"), x, p[1])
        sh.pwr(q, "GND", (1, 0))
    # D-, D+: both rows of the reversible plug joined, 0 R series positions, labels to the controller
    for pa, pb, net, xe in (("A7", "B7", "USBC_DM", 104.14), ("A6", "B6", "USBC_DP", 129.54)):
        a, b = sh.P(j1, pa), sh.P(j1, pb)
        sh.w(b, (xd, b[1]), (xd, a[1]))
        sh.w(a, (86.36, a[1]))
        sh.lbl((xd + 5.08, a[1]), net, (1, 0))
        usbd = net.replace("USBC", "USBD")
        q = hpart(sh, nets(_1=net, _2=usbd), 86.36, a[1], fields="above" if net.endswith("DM") else "below")
        sh.w(q, (xe, q[1]))
        sh.lbl((xe, q[1]), usbd, (1, 0))
    v33(sh, vup(sh, nets(_1="USBD_DP", _2="+3V3"), 121.92, sh.P(j1, "A6")[1]))
    sh.text("R9: D+ pull-up option (DNP)", 111.76, 104.14, 1.27, False)
    g, s = sh.P(j1, "A1"), sh.P(j1, "SH")
    sh.w(s, (s[0], g[1] + U), (g[0], g[1] + U), g)
    sh.gnd((g[0], g[1] + U))
    sh.text("SBU1, SBU2 open; shield to GND", 20.32, 125.73, 1.27, False)
    # ESD array on the connector side of the 0 R positions
    u3 = "U3"
    sh.place(u3, 76.2, 132.08, fields=(15.24, -13.97))
    for pin, net, d in ((1, "USBC_DM", (-1, 0)), (3, "USBC_DP", (-1, 0)), (4, "CC1", (1, 0)), (6, "CC2", (1, 0))):
        stub(sh, (u3, pin), d, net)
    vp = sh.P(u3, 5)
    sh.w(vp, (vp[0], vp[1] - U), (vp[0] + 7.62, vp[1] - U))
    sh.lbl((vp[0] + 7.62, vp[1] - U), "VBUS_C", (1, 0))
    sh.gnd((u3, 2))
    # VBUS sense divider
    xs = 144.78
    p = vcap(sh, nets(_1="VBUS_C", _2="VBUS_DET"), xs, yv, gnd=False)
    vcap(sh, nets(_1="VBUS_DET", _2="GND"), xs, p[1])
    sh.w(p, (xs - 5.08, p[1]))
    sh.lbl((xs - 5.08, p[1]), "VBUS_DET", (-1, 0))
    sh.flag((63.5, yv), "VBUS_C")

    # ---- power entry: JP1 selects USB-C or the external 5 V, polyfuse, TVS
    sh.heading("Power entry: USB-C VBUS or external 5 V (JP1), polyfuse, TVS", 150, 30, 262)
    yr = 60.96                                                    # +5V_IN rail
    xj = 185.42
    sh.place("JP1", xj, yr, rot=90, fields="left")                # 3 (+5V_EXT) top, 1 (VBUS_C) bottom, 2 right
    sh.w((xd, yv), (xj, yv), ("JP1", 1))
    sh.lbl((xd + 20.32, yv), "VBUS_C", (1, 0))
    sh.place("J4", 152.4, 45.72, mirror="y", fields="left")      # pins on the right
    sh.w(("J4", 1), (xj, 45.72), ("JP1", 3))
    sh.lbl((162.56, 45.72), "+5V_EXT", (1, 0))
    sh.flag((177.8, 45.72), "+5V_EXT")
    g = sh.P("J4", 2)
    sh.w(g, (g[0] + U, g[1])); sh.gnd((g[0] + U, g[1]))
    sh.text("external 5 V", 142.24, 53.34, 1.27, False)
    p2 = sh.P("JP1", 2)
    sh.place("F1", 200.66, yr, rot=90, fields="above")
    sh.w(p2, ("F1", 1))
    sh.lbl(p2, "+5V_SEL", (1, 0))
    sh.place("D1", 213.36, yr + 3.81, rot=270, fields="left")     # K on the rail, A to GND
    sh.gnd(("D1", 2))
    vcap(sh, note("+5V_IN bulk"), 223.52, yr)
    sh.flag((231.14, yr), "+5V_IN")
    gnd_flag(sh, 254.0, 81.28)
    sh.text("JP1 1-2: USB-C, 2-3: external 5 V (no diode drop)", 157.48, 81.28, 1.27, False)
    sh.text("F1: PTC, 0.75 A hold; D1: TVS, a reversed supply trips F1", 157.48, 85.09, 1.27, False)

    # ---- 3.3 V
    sh.heading("3.3 V for the controller and the logic", 243.84, 99.06, 330)
    yl = 116.84
    xd2 = 238.76
    sh.w((xd2, yr), (xd2, yl))
    sh.lbl((233.68, yl), "+5V_IN", (-1, 0))
    sh.place("U2", 266.7, yl, fields="above")
    sh.w((233.68, yl), ("U2", 3))
    vcap(sh, note("LDO input"), 248.92, yl)
    sh.gnd(("U2", 1))
    xv = sh.P("U2", 2)[0]
    sh.w(("U2", 2), (xv + 38.1, yl))
    vcap(sh, note("LDO output"), xv + 7.62, yl)
    vcap(sh, note("+3V3 bulk"), xv + 17.78, yl)
    led_chain(sh, note("power LED series"), by(lambda q: q.note == "power"), xv + 27.94, yl)
    v33(sh, (xv + 38.1, yl))

    # ---- slot rail: soft start (DNP) in parallel with the fitted 0 R bypass
    sh.heading("Slot rail: soft start (option, not fitted) bridged by 0 R", 270, 30, W)
    ys, yg = yr - 10.16, yr - 17.78
    xa, xq, xb = 271.78, 287.02, 302.26
    sh.place("Q1", xq, ys - U, rot=270, fields=(-3.81, -11.43))  # S left, D right, G on top
    vup(sh, note("soft start R_GS"), xa, ys, fields="left")
    sh.w(("Q1", 2), (xa, ys), (xa, yr))
    sh.w(("Q1", 3), (xb, ys), (xb, yr))
    vcap(sh, note("soft start C_GD"), xb, yg, gnd=False)
    vcap(sh, note("soft start R_G"), xb + 10.16, yg)
    sh.w((xa, yg), (xb + 10.16, yg))
    sh.lbl((xa + 1.27, yg), "SS_G", (1, 0))
    rb = by(lambda q: q.note and q.note.startswith("R_BYP"))
    p = hpart(sh, rb, xq - 3.81, yr, fields="below")
    sh.w(("F1", 2), (rb, 1))
    x5 = xb + 45.72
    sh.w(p, (x5, yr))
    vcap(sh, note("slot rail bulk", 0), xb + 20.32, yr)
    vcap(sh, note("slot rail bulk", 1), xb + 30.48, yr)
    sh.flag((xb + 38.1, yr), "+5V")
    sh.v5((x5, yr))
    sh.text("+5V: the slot rail (sockets, mixer)", x5 + 2.54, yr + 1.27, 1.27, False)
    sh.text("soft start (DNP): Q1, R_GS 1M, R_G 220k, C_GD 100n, about 40 ms ramp;", 275.59, 81.28, 1.27, False)
    sh.text("fit them and remove the 0 R bypass R2", 275.59, 85.09, 1.27, False)

    # ---- USB-A host port
    sh.heading("USB-A host port (USBFS: class-compliant MIDI keyboards), 0.5 A switch", 15, 157.48, W)
    yh = 175.26
    u4 = "U4"
    sh.place(u4, 60.96, yh + U, fields="above")
    sh.lbl((25.4, yh), "+5V_IN", (-1, 0))
    sh.w((25.4, yh), (u4, 5))
    vcap(sh, note("host switch input"), 40.64, yh)
    sh.gnd((u4, 2))
    en = sh.P(u4, 4)
    ye = en[1] + 10.16
    sh.w(en, (en[0] - U, en[1]), (en[0] - U, ye), (25.4, ye))
    sh.lbl((25.4, ye), "HOST_EN", (-1, 0))
    vcap(sh, note("host port off until the firmware enables it"), 35.56, ye)
    # fault output: pull-up and fault LED to +3V3
    fl = sh.P(u4, 3)
    yf = ye + 15.24
    sh.w(fl, (fl[0] + U, fl[1]), (fl[0] + U, yf), (fl[0] + 38.1, yf))
    sh.lbl((fl[0] + 38.1, yf), "HOST_FLT_N", (1, 0))
    v33(sh, vup(sh, note("fault pull-up"), fl[0] + 12.7, yf))
    r14, d3 = note("fault LED series"), by(lambda q: q.note == "host port fault")
    led_chain(sh, r14, d3, fl[0] + 25.4, yf - 20.32, gnd=False)
    v33(sh, (r14, 1))
    # VBUS_HOST
    xh = sh.P(u4, 1)[0]
    xj2 = 228.6
    sh.place("J2", xj2, yh + 5.08, mirror="y", fields="right")   # pins on the left
    sh.w((u4, 1), ("J2", 1))
    sh.lbl((xh + 2.54, yh), "VBUS_HOST", (1, 0))
    vcap(sh, note("host VBUS", 0), xh + 40.64, yh)
    vcap(sh, note("host VBUS", 1), xh + 50.8, yh)
    led_chain(sh, note("host power LED series"), by(lambda q: q.note == "host port powered"), xh + 60.96, yh)
    g, s = sh.P("J2", 4), sh.P("J2", "SH")
    sh.w(s, (s[0], g[1] + U), (g[0], g[1] + U), g)
    sh.gnd((g[0], g[1] + U))
    dp, dm = sh.P("J2", 3), sh.P("J2", 2)
    sh.w(dp, (dp[0] - 10.16, dp[1]))
    sh.lbl((dp[0] - 10.16, dp[1]), "USBH_DP", (-1, 0))
    sh.w(dm, (dm[0] - 5.08, dm[1]), (dm[0] - 5.08, dm[1] + 5.08), (dm[0] - 10.16, dm[1] + 5.08))
    sh.lbl((dm[0] - 10.16, dm[1] + 5.08), "USBH_DM", (-1, 0))
    # host ESD, VP on the VBUS_HOST line
    u5 = "U5"
    sh.place(u5, 177.8, yh + 17.78, fields=(-20.32, -10.16))
    sh.w((u5, 5), (177.8, yh))
    for pin, net in ((1, "USBH_DM"), (3, "USBH_DP")):
        stub(sh, (u5, pin), (-1, 0), net)
    sh.gnd((u5, 2))
    # D-, D+ pull-down options
    for k, net in enumerate(("USBH_DM", "USBH_DP")):
        y = yh + 35.56 + k * 10.16
        sh.lbl((215.9, y), net, (-1, 0))
        q = hpart(sh, nets(_1=net, _2="GND"), 215.9, y)
        sh.pwr(q, "GND", (1, 0))
    sh.text("host pull-downs (option, DNP): USBFS has them inside", 195.58, yh + 55.88, 1.27, False)


# ============================================================================ MCU
def sheet_mcu(sh):
    W = 405
    part = PART["U1"]
    xm, ym = 205.74, 137.16
    sh.heading("CH32V203C8T6 (hand-soldered), decoupling, reset", 140, 30, 275)
    sh.place("U1", xm, ym, fields=(5.08, 46.99))
    special = {"7", "44", "5", "6", "30", "31", "34", "37", "1", "9", "24", "36", "48", "8", "23", "35", "47"}
    for num, net in part.pins.items():
        if num in special:
            continue
        x, y = sh.P("U1", num)
        stub(sh, (x, y), (-1, 0) if x < xm else (1, 0), net)
    sh.lbl(sh.P("U1", 44), "BOOT0", (-1, 0), stub=2 * U)
    # supply: VBAT and the three VDD on the +3V3 bar with one 100 nF each, VDDA behind the ferrite
    yb, ya = ym - 63.5, ym - 43.18
    xv = [sh.P("U1", k)[0] for k in (1, 24, 36, 48)]
    for k in (1, 24, 36, 48):
        sh.w(("U1", k), (sh.P("U1", k)[0], yb))
    xf = xm + 60.96
    sh.w((xv[0] - 7.62, yb), (xf, yb))
    v33(sh, (xv[0] - 7.62, yb))
    for i, pin in enumerate((24, 36, 48, "VBAT")):
        c = note(f"MCU decoupling VDD pin {pin}" if pin != "VBAT" else "MCU decoupling VBAT")
        vcap(sh, c, xm + 12.7 + i * 10.16, yb)
    fb = by(lambda q: q.note == "VDDA filter")
    sh.place(fb, xf, yb + U, fields="right")
    va = sh.P("U1", 9)
    sh.w(va, (va[0], ya), (xf, ya), (fb, 2))
    sh.lbl((va[0] + U, ya), "VDDA", (1, 0))
    sh.flag((va[0] + 17.78, ya), "VDDA")
    vcap(sh, note("VDDA", 0), xf - 22.86, ya)
    vcap(sh, note("VDDA", 1), xf - 12.7, ya)
    g, ga = sh.P("U1", 23), sh.P("U1", 8)
    sh.w(g, (g[0], g[1] + U), (ga[0], g[1] + U), ga)
    sh.gnd((g[0], g[1] + U))
    # reset: filter cap and push button
    rs = sh.P("U1", 7)
    yr = ym - 66.04
    sh.w(rs, (rs[0] - 5.08, rs[1]), (rs[0] - 5.08, yr), (rs[0] - 38.1, yr))
    sh.lbl((rs[0] - 33.02, yr), "MCU_NRST", (1, 0))
    sh.place("SW1", rs[0] - 38.1, yr + 5.08, rot=270, fields="left")   # 1 (NRST) top, 2 (GND) bottom
    sh.gnd(("SW1", 2))
    vcap(sh, note("reset filter"), rs[0] - 17.78, yr)
    sh.text("RESET: the controller only; the 595", rs[0] - 50.8, yr + 20.32, 1.27, False)
    sh.text("outputs go off, the cards keep running", rs[0] - 50.8, yr + 24.13, 1.27, False)
    sh.text("SPI1 remap 1 (PA15, PB3, PB4, PB5); TIM3 CH4 (PB1) = 24 MHz CLK option", xm - 50.8, ym + 60.96, 1.27,
            False)

    # ---- crystal
    sh.heading("8 MHz crystal (PLL x 18 = 144 MHz)", 15, 99.06, 137)
    oi, oo = sh.P("U1", 5), sh.P("U1", 6)
    yy = oo[1] + 10.16
    xl, xr = 107.95, 123.19
    sh.place("Y1", (xl + xr) / 2, yy, fields="below")
    sh.w(oi, (xl, oi[1]), (xl, yy), ("Y1", 1))
    sh.w(oo, (xr, oo[1]), (xr, yy), ("Y1", 2))
    sh.lbl((xr + 12.7, oi[1]), "OSC_IN", (1, 0))
    sh.lbl((xr + 12.7, oo[1]), "OSC_OUT", (1, 0))
    vcap(sh, nets(_1="OSC_IN", _2="GND"), xl, yy, fields="left")
    vcap(sh, nets(_1="OSC_OUT", _2="GND"), xr, yy)
    sh.text("X50328MSB2GI: 20 pF load, 2 x 30 pF with the strays", 66.04, yy + 22.86, 1.27, False)

    # ---- MIDI DIN in (option)
    sh.heading("MIDI DIN in (option, not fitted): opto into PA10 through JP3", 15, 30, 137)
    X, Y = 83.82, 60.96
    sh.place("U9", X, Y, fields="above")
    sh.place("J7", 25.4, Y, mirror="y", fields="left")            # pins on the right
    a1, a2 = sh.P("U9", 1), sh.P("U9", 2)
    p = sh.P("J7", 1)
    sh.w(p, (p[0] + 12.7, p[1]))
    sh.lbl((p[0] + 3.81, p[1]), "MIDI_4", (1, 0))
    q = hpart(sh, nets(_1="MIDI_4", _2="MIDI_LA"), p[0] + 12.7, p[1])
    sh.w(q, a1)
    sh.lbl((q[0] + 1.27, q[1]), "MIDI_LA", (1, 0))
    p5 = sh.P("J7", 2)
    y5 = a2[1] + 5.08
    sh.w(p5, (p5[0] + 7.62, p5[1]), (p5[0] + 7.62, y5), (a2[0] - U, y5), (a2[0] - U, a2[1]), a2)
    sh.lbl((p5[0] + 10.16, y5), "MIDI_5", (1, 0))
    dd = by(lambda q_: q_.lib_id == "Diode:1N4148W")
    sh.place(dd, a2[0] - 10.16, q[1] + 3.81, rot=270, fields="left")   # K on MIDI_LA, A on MIDI_5
    sh.w((dd, 2), (a2[0] - 10.16, y5))
    g3 = sh.P("J7", 3)
    sh.w(g3, (g3[0] + U, g3[1])); sh.gnd((g3[0] + U, g3[1]))
    sh.gnd(stub_w(sh, sh.P("U9", 3), 5.08))
    c4 = sh.P("U9", 4)
    jp = "JP3"
    sh.place(jp, c4[0] + 27.94, c4[1], fields="above")
    sh.w(c4, (jp, 1))
    sh.lbl((c4[0] + 1.27, c4[1]), "MIDI_RX", (1, 0))
    v33(sh, vup(sh, nets(_1="MIDI_RX", _2="+3V3"), c4[0] + 12.7, c4[1], fields="right"))
    stub(sh, (jp, 2), (1, 0), "UART_RX")
    sh.text("DIN pin 4, pin 5, shield (panel jack on wires); LTV-817S: speed at 3.3 V unverified (6N138 by hand)",
            20.32, Y + 20.32, 1.27, False)
    sh.text("JP3: fit only for DIN MIDI (USART1 RX then not available to J6)", 20.32, Y + 24.13, 1.27, False)

    # ---- programming: UART and SWD headers on the controller pins, BOOT0
    sh.heading("Programming: SWD (WCH-LinkE), BOOT0, USART1 (bootloader, debug)", 285, 99.06, W)
    tx, rx = sh.P("U1", 30), sh.P("U1", 31)
    xj6 = 304.8
    sh.place("J6", xj6, tx[1], fields="right")
    sh.w(tx, ("J6", 2)); sh.w(rx, ("J6", 3))
    sh.lbl((tx[0] + 33.02, tx[1]), "UART_TX", (1, 0))
    sh.lbl((rx[0] + 33.02, rx[1]), "UART_RX", (1, 0))
    g = sh.P("J6", 1)
    sh.w(g, (g[0] - U, g[1])); sh.pwr((g[0] - U, g[1]), "GND", (-1, 0))
    dio, clk = sh.P("U1", 34), sh.P("U1", 37)
    xj5 = 342.9
    sh.place("J5", xj5, dio[1], fields="right")
    sh.w(dio, ("J5", 2)); sh.w(clk, ("J5", 3))
    sh.lbl((dio[0] + 33.02, dio[1]), "SWDIO", (1, 0))
    sh.lbl((clk[0] + 33.02, clk[1]), "SWCLK", (1, 0))
    v33(sh, stub_w(sh, sh.P("J5", 1), -U, horiz=True))
    sh.gnd(stub_w(sh, sh.P("J5", 4), -U, horiz=True))
    sh.text("J6 USART1: GND, TX (PA9), RX (PA10); 5 V adapters are fine (FT pins)", 289.56, 118.11, 1.27, False)
    sh.text("J5 WCH-LinkE: 3V3, SWDIO, SWCLK, GND", 289.56, 152.4, 1.27, False)
    # BOOT0 jumper
    yb0 = 177.8
    sh.place("JP2", 330.2, yb0, fields=(-2.54, -10.16))         # 1 (+3V3) left, 3 (GND) right, 2 (BOOT0) down
    v33(sh, stub_w(sh, sh.P("JP2", 1), -U, horiz=True))
    sh.pwr(stub_w(sh, sh.P("JP2", 3), U, horiz=True), "GND", (1, 0))
    b = sh.P("JP2", 2)
    yb1 = b[1] + 5.08
    sh.w(b, (b[0], yb1), (b[0] - 25.4, yb1))
    sh.lbl((b[0] - 25.4, yb1), "BOOT0", (-1, 0))
    vcap(sh, nets(_1="BOOT0", _2="GND"), b[0] - 12.7, yb1)
    sh.text("JP2 1-2: system bootloader (USART1, USB); open or 2-3: run from flash", 289.56, yb1 + 20.32, 1.27,
            False)

    # ---- SPI flash, activity LED, free pins
    sh.heading("SPI flash (footprint only), activity LED, free pins", 15, 200.66, 290)
    u7 = "U7"
    xu, yu = 48.26, 233.68
    sh.place(u7, xu, yu, fields=(12.7, 10.16))
    for pin in (1, 6, 5, 2, 3, 7):
        stub(sh, (u7, pin), (-1, 0), PART[u7].pins[str(pin)])
    vc = sh.P(u7, 8)
    ytop = vc[1] - 7.62
    sh.w(vc, (vc[0], ytop), (vc[0] + 15.24, ytop))
    v33(sh, (vc[0], ytop))
    vcap(sh, by(lambda q_: q_.note == "flash decoupling"), vc[0] + 15.24, ytop)
    sh.gnd((u7, 4))
    # pull-ups: CS (deselected while the MCU boots), WP and HOLD idle
    xp, yp = 78.74, 213.36
    sh.w((xp - 5.08, yp), (xp + 20.32, yp))
    v33(sh, (xp - 5.08, yp))
    for i, net in enumerate(("FLASH_CS_N", "FLASH_WP_N", "FLASH_HOLD_N")):
        r = nets(_1=net, _2="+3V3")
        sh.place(r, xp + i * 10.16, yp + 3.81, 180, fields="right")     # pin 2 (+3V3) up
        sh.lbl((r, 1), net, (0, 1), stub=U)
    # activity LED on PB2 (= BOOT1: pull-down)
    xl0, yl0 = 132.08, 215.9
    sh.lbl((xl0, yl0), "LED_ACT", (-1, 0))
    sh.w((xl0, yl0), (xl0 + 7.62, yl0))
    vcap(sh, nets(_1="LED_ACT", _2="GND"), xl0 + 5.08, yl0)
    p = hpart(sh, nets(_1="LED_ACT", _2="LED_ACT_A"), xl0 + 7.62, yl0)
    d6 = by(lambda q_: q_.note == "activity")
    sh.place(d6, p[0] + 17.78, yl0, rot=180, fields="above")        # A left, K right
    sh.w(p, (d6, 2))
    sh.lbl((p[0] + 1.27, yl0), "LED_ACT_A", (1, 0))
    k = sh.P(d6, 1)
    sh.w(k, (k[0] + 5.08, yl0)); sh.gnd((k[0] + 5.08, yl0))
    sh.text("PB2 = BOOT1: low at reset", xl0 - 7.62, yl0 + 20.32, 1.27, False)
    # test points
    xt = 205.74
    for i, net in enumerate(("PC15", "PB0", "PB14")):
        x = xt + i * 15.24
        sh.place(tp(net), x, 220.98, fields="right")
        sh.lbl(sh.P(tp(net), 1), net, (0, 1), stub=U)
    for i, net in enumerate(("+3V3", "+5V", "GND")):
        x = xt + i * 15.24
        t = tp(net)
        if net == "GND":
            sh.place(t, x, 238.76, fields="right")
            sh.gnd((t, 1), stub=U)
        else:
            sh.place(t, x, 246.38, rot=180, fields="right")             # body below, rail symbol above
            sh.pwr(stub_w(sh, (t, 1), -U), net, (0, -1))
    sh.text("free pins and rails", xt - 2.54, 210.82, 1.27, False)


# ============================================================================ bus
def bus_row(sh, r, x, y, left, right, tpnet=None):
    """label left -> horizontal series resistor -> line -> label right, optional test point on the line"""
    sh.lbl((x, y), left, (-1, 0))
    sh.w((x, y), (x + 5.08, y))
    p = hpart(sh, r, x + 5.08, y)
    xe = x + 55.88
    sh.w(p, (xe, y))
    sh.lbl((xe, y), right, (1, 0))
    if tpnet:
        tpx(sh, tpnet, (p[0] + 20.32, y))


def pack(sh, r, x, y, fields="above"):
    """4 x resistor array, resistors horizontal: pins 1...4 on the left (top to bottom), 8...5 on the right"""
    sh.place(r, x, y, rot=270, fields=fields)
    return [sh.P(r, k) for k in (1, 2, 3, 4)], [sh.P(r, k) for k in (8, 7, 6, 5)]


def socket(sh, j, c, x, y):
    """slot socket at (x, y): +5V pins joined over the top with the 10 uF to GND, label stubs, sideways grounds"""
    part = PART[j]
    sh.place(j, x, y, fields="below")
    p1, p2 = sh.P(j, 1), sh.P(j, 2)
    yt = y - 12.7
    sh.w(p1, (p1[0] - U, p1[1]), (p1[0] - U, yt), (p2[0] + U, yt), (p2[0] + U, p2[1]), p2)
    sh.v5((x + 1.27, yt))
    q = hpart(sh, c, p2[0] + U, yt)
    sh.pwr(q, "GND", (1, 0))
    for num in range(3, 17):
        net = part.pins[str(num)]
        p = sh.P(j, num)
        d = (-1, 0) if num % 2 else (1, 0)
        if net == "GND":
            sh.w(p, (p[0] + d[0] * U, p[1]))
            sh.pwr((p[0] + d[0] * U, p[1]), "GND", d)
        else:
            stub(sh, p, d, net, n=3)


def sheet_bus(sh):
    W = 405
    # ---- bus drivers
    sh.heading("Bus drivers: broadcast, return, SYNC, 24 MHz clock (option)", 15, 30, 150)
    x = 35.56
    y = 50.8
    sh.lbl((x, y), "RETURN", (-1, 0))
    sh.w((x, y), (x + 55.88, y))
    sh.lbl((x + 55.88, y), "RETURN", (1, 0))
    v33(sh, vup(sh, nets(_1="RETURN", _2="+3V3"), x + 12.7, y))
    tpx(sh, "RETURN", (x + 33.02, y))
    for k, (o, n) in enumerate((("BCAST_O", "BCAST"), ("SYNC_O", "SYNC"), ("CLK_O", "CLK"))):
        bus_row(sh, nets(_1=o, _2=n), x, y + 12.7 * (k + 1), o, n, tpnet=n if n != "CLK" else None)
    sh.text("33 R series at the driver; RETURN: the cards' TX are open drain", 20.32, 104.14, 1.27, False)

    # ---- effects slot: slot 1 pins 15 / 14
    sh.heading("Effects slot 1: pins 15 / 14 = CLK / SWIO_1 or the mix sends; pins 3 / 4 = loop-through return",
               15, 109.22, 150)
    fx = {p.pins["1"]: p.ref for p in D.PARTS if p.note and p.note.startswith("effects slot")}
    for k, (src, dst) in enumerate((("CLK", "FX_P15"), ("MIX_L", "FX_P15"), ("SWIO_1", "FX_P14"),
                                    ("MIX_R", "FX_P14"), ("FX_RET_L", "LO_L"), ("FX_RET_R", "LO_R"))):
        bus_row(sh, fx[src], x, 119.38 + 7.62 * k, src, dst)
    sh.text("effects card in slot 1: remove R79 / R81, fit R80 / R82 (the stereo mix to the card); loop-through:",
            20.32, 162.56, 1.27, False)
    sh.text("also remove the line-out 220 R from MIX_L / MIX_R (R71 / R75) and fit R83 / R84 (pins 3 / 4 to the line out)",
            20.32, 166.37, 1.27, False)

    # ---- NRST shift register
    sh.heading("NRST: 74HC595 drives each card's NRST directly (outputs off at reset: the cards run freely)", 15,
               175.26, 195)
    u6 = "U6"
    xu, yu = 60.96, 218.44
    sh.place(u6, xu, yu, fields=(-17.78, 15.24))
    xl = xu - 17.78                                               # input labels
    for pin, net in ((14, "SPI_MOSI"), (11, "SPI_SCK"), (12, "SR_LATCH"), (13, "SR_OE_N")):
        p = sh.P(u6, pin)
        sh.w(p, (xl, p[1]))
        sh.lbl((xl, p[1]), net, (-1, 0))
    # +3V3 bar on the left: VCC, SRCLR (tied high), OE_N pull-up
    xb = 25.4
    vcc = sh.P(u6, 16)
    yt = vcc[1] - 15.24
    sh.w(vcc, (vcc[0], yt), (xb, yt))
    v33(sh, (xb, yt))
    sh.w((vcc[0], yt), (vcc[0] + 10.16, yt))
    vcap(sh, by(lambda q: q.note == "595 decoupling"), vcc[0] + 10.16, yt)
    sh.w(sh.P(u6, 10), (xb, sh.P(u6, 10)[1]))
    oe = sh.P(u6, 13)
    r30 = nets(_1="SR_OE_N", _2="+3V3")
    p = vcap(sh, r30, oe[0] - 5.08, oe[1], gnd=False, fields="left")
    sh.w(p, (xb, p[1]), (xb, yt))
    sh.gnd((u6, 8))
    # outputs QA ... QH = slots 1 ... 8
    for k, pin in D.NRST_Q.items():
        stub(sh, (u6, pin), (1, 0), f"NRST_{k}", n=3)
    sh.text("QH' open; no series resistors or pull-downs on NRST", 81.28, yu + 22.86, 1.27, False)
    sh.text("the firmware resets the cards through the 595 or over SWIO", 81.28, yu + 26.67, 1.27, False)

    # ---- SWIO pull-ups
    sh.heading("SWIO pull-ups (1 k each: the one-wire protocol samples 0.6 us after an edge)", 205.74, 175.26, W)
    for k, (a, rn) in enumerate(((1, "RN1"), (5, "RN2"))):
        x0 = 228.6 + k * 50.8
        y0 = 205.74
        left, right = pack(sh, rn, x0, y0, fields="below")
        xg = left[0][0] - U
        for lp in left:
            sh.w(lp, (xg, lp[1]))
        sh.w((xg, left[-1][1]), (xg, left[0][1] - U))
        v33(sh, (xg, left[0][1] - U))
        for i, rp in enumerate(right):
            stub(sh, rp, (1, 0), f"SWIO_{a + i}")

    # ---- slot sockets
    sh.heading("Slot sockets (2 x 8 female, vertical; card part side faces west)", 160, 30, W)
    for k in range(D.SLOTS):
        j = f"J{10 + k}"
        c = note(f"slot {k + 1} supply")
        socket(sh, j, c, 182.88 + (k % 4) * 60.96, 60.96 + (k // 4) * 55.88)
    sh.text("pins 1/2 +5V, 3/4/8/13/16 GND (slot 1: 3/4 the effects return); 5, 6, 7: the card's AUDIO_L, "
            "AUDIO_GND, AUDIO_R", 165.1, 140.97, 1.27,
            False)


# ============================================================================ mixer
def follower(sh, u, unit, x, y, pins):
    """op-amp unit at (x, y) wired as a voltage follower (output loop below the '-' input); pins = (in+, in-, out).
    Returns (in+, out) points."""
    sh.place(u, x, y, unit=unit, fields="above")
    ip, im, o = (sh.P(u, k) for k in pins)
    yl = im[1] + 5.08
    sh.w(o, (o[0] + U, o[1]), (o[0] + U, yl), (im[0] - U, yl), (im[0] - U, im[1]), im)
    return ip, (o[0] + U, o[1])


def supply(sh, u, x, y, cap, label=True):
    """op-amp supply unit: V+ up (VA_MIX label, or the caller's wire), GND on V-, decoupling cap to the right"""
    sh.place(u, x, y, unit=3, fields=(-15.24, -1.27))
    vp, vm = sh.P(u, 8), sh.P(u, 4)
    if label:
        sh.lbl(vp, "VA_MIX", (0, -1), stub=U)
        sh.w(vp, (vp[0] + 7.62, vp[1]))
    sh.gnd(vm)
    vcap(sh, cap, vp[0] + 7.62, vp[1])


def cell(sh, s, x, yln, yrn):
    """mixer cell of slot s + 1: AUDIO_L (top) into the SUM_LN bus at yln, AUDIO_R (bottom) into the SUM_RN bus at
    yrn, the AUDIO_GND mirror (C_G at x + 10.16) to the SUM_LP / SUM_RP labels"""
    k = s + 1
    yt = yln - 27.94                                              # top labels
    sh.lbl((x, yt), f"AUDIO_L_{k}", (0, -1))
    sh.w((x, yt), (x, yt + U))
    vcap(sh, ref(f"CINl{s}_0"), x, yt + U, gnd=False)
    vcap(sh, ref(f"RIl{s}_0"), x, yln - 7.62, gnd=False)
    sh.w((x, yt + 10.16), (x, yln - 7.62))
    sh.lbl((x, yln - 12.7), f"MXL_{k}", (1, 0))
    xg = x + 10.16
    sh.lbl((xg, yt), f"AUDIO_GND_{k}", (0, -1))
    sh.w((xg, yt), (xg, yt + U))
    vcap(sh, ref(f"CG{s}_0"), xg, yt + U, gnd=False)
    sh.w((xg, yt + 10.16), (xg, yln - 5.08))
    sh.lbl((xg, yln - 7.62), f"MXG_{k}", (-1, 0))
    for r, y, net in ((f"RPl{s}_0", yln - 12.7, "SUM_LP"), (f"RPr{s}_0", yln - 5.08, "SUM_RP")):
        p = hpart(sh, ref(r), xg, y, fields=(-1.27, -4.45))
        sh.lbl(p, net, (1, 0), stub=U)
    vup(sh, ref(f"RIr{s}_0"), x, yrn + 7.62)                      # pin 2 on the SUM_RN bus
    sh.w((x, yrn + 7.62), (x, yrn + 12.7))
    sh.lbl((x, yrn + 10.16), f"MXR_{k}", (1, 0))
    vup(sh, ref(f"CINr{s}_0"), x, yrn + 20.32)
    sh.lbl((x, yrn + 20.32), f"AUDIO_R_{k}", (0, 1), stub=U)


def summer(sh, ch, x, y, xo):
    """inverting summer of channel ch ('l', 'r'): op-amp at (x, y) mirrored ('-' on top, on the bus line at y - 2.54),
    RF || CF above, the '+' input from the SUM_xP label with RFP || CFP to VREF below; the output line to xo.
    Returns the output point."""
    X = ch.upper()
    u, unit, pins = ("U8", 1, (3, 2, 1)) if ch == "l" else ("U8", 2, (5, 6, 7))
    sh.place(u, x, y, unit=unit, mirror="x", fields=(3.81, 7.62))
    ip, im, o = (sh.P(u, k) for k in pins)
    xm, xr = im[0] - U, o[0] + U
    for r, yy in ((ref(f"RF{ch}0"), im[1] - 10.16), (ref(f"CF{ch}0"), im[1] - 17.78)):
        hpart(sh, r, xm + 2.54, yy, flip=True)                    # pin 2 (the '-' node) left, pin 1 (out) right
        sh.w((xm, im[1]), (xm, yy), (r, 2))
        sh.w((r, 1), (xr, yy), (xr, o[1]))
    sh.w(o, (xo, o[1]))
    sh.lbl((xr + 7.62, o[1]), f"MIX_{X}", (1, 0))
    tpx(sh, f"MIX_{X}", (xr + 5.08, o[1]))
    # '+' input: SUM_xP label, RFP || CFP to VREF
    xl = ip[0] - 20.32
    sh.w(ip, (xl, ip[1]))
    sh.lbl((xl, ip[1]), f"SUM_{X}P", (-1, 0))
    yb = ip[1] + 7.62
    for r, xx, f in ((ref(f"RFP{ch}0"), ip[0] - 5.08, "right"), (ref(f"CFP{ch}0"), ip[0] - 12.7, "left")):
        vup(sh, r, xx, yb, fields=f)
    sh.w((ip[0] - 5.08, yb), (ip[0] - 5.08, yb + U), (xl, yb + U))
    sh.w((ip[0] - 12.7, yb), (ip[0] - 12.7, yb + U))
    sh.lbl((xl, yb + U), "VREF", (-1, 0))
    return (xo, o[1])


def line_out(sh, ch, x, y, xj):
    """MIX_x -> 220 R -> 10 uF -> LINE_x (100k bleeder) to the jack at xj; ADC divider tap hanging below at x"""
    X = ch.upper()
    sh.w((x, y), (x, y + 5.08))
    p = vcap(sh, ref(f"RA1{ch}0"), x, y + 5.08, gnd=False)
    sh.w(p, (p[0], p[1] + U), (p[0] + 12.7, p[1] + U))
    yd = p[1] + U
    vcap(sh, ref(f"RA2{ch}0"), x, yd, fields="left")
    vcap(sh, ref(f"CA{ch}0"), x + 7.62, yd)
    sh.lbl((x + 12.7, yd), f"ADC_{X}", (1, 0))
    sh.w((x, y), (x + 7.62, y))
    p = hpart(sh, ref(f"ROS{ch}0"), x + 7.62, y)
    sh.w(p, (p[0] + 7.62, y))
    sh.lbl((p[0] + 1.27, y), f"LO_{X}", (1, 0))
    p = hpart(sh, ref(f"COL{ch}0"), p[0] + 7.62, y)
    sh.w(p, (xj, y))
    sh.lbl((p[0] + 7.62, y), f"LINE_{X}", (1, 0))
    vcap(sh, ref(f"RBL{ch}0"), p[0] + 5.08, y)


def sheet_mixer(sh):
    W = 405
    yln, yrn = 81.28, 93.98
    sh.heading("Per slot: input capacitors, 56k into the summing nodes, AUDIO_GND mirror (C_G, R_P)", 15, 30, 250)
    xs = [25.4 + 30.48 * s for s in range(D.SLOTS)]
    for s, x in enumerate(xs):
        cell(sh, s, x, yln, yrn)
    sh.text("8 x the same cell (slot 1 ... 8 from the left)", 20.32, yrn + 38.1, 1.27, False)

    # ---- summing amplifiers
    sh.heading("Summing amplifiers (inverting)", 255, 30, 318)
    xa = 307.34
    sh.w((xs[0], yln), (xa - 7.62, yln))
    sh.lbl((xs[-1] + 15.24, yln), "SUM_LN", (1, 0))
    oL = summer(sh, "l", xa, yln + U, 330.2)
    yb = 152.4
    xv = xs[-1] + 27.94
    sh.w((xs[0], yrn), (xv, yrn), (xv, yb - U), (xa - 7.62, yb - U))
    sh.lbl((xs[-1] + 15.24, yrn), "SUM_RN", (1, 0))
    oR = summer(sh, "r", xa, yb, 330.2)
    supply(sh, "U8", 279.4, 185.42, by(lambda q: q.note == "decoupling U8"))
    sh.text("out = VREF - 0.357 x sum(AUDIO_x - AUDIO_GND_x)", 271.78, 120.65, 1.27, False)
    sh.text("+ side mirrored to VREF: the card grounds' offsets cancel", 271.78, 124.46, 1.27, False)

    # ---- line out, ADC taps
    sh.heading("Line out (3.5 mm stereo) and ADC taps (USB audio)", 322.58, 30, W)
    xj = 393.7
    yj = oL[1] + U
    sh.place("J3", xj, yj, rot=180, fields="below")               # T (L) top, R middle, S (GND) bottom
    line_out(sh, "l", oL[0], oL[1], xj - 5.08)
    line_out(sh, "r", oR[0], oR[1], xj - 17.78)
    sh.w((xj - 17.78, oR[1]), (xj - 17.78, yj), ("J3", "R"))
    s_ = sh.P("J3", "S")
    sh.w(s_, (s_[0] - U, s_[1]), (s_[0] - U, s_[1] + 5.08))
    sh.gnd((s_[0] - U, s_[1] + 5.08))
    sh.text("ADC dividers at the MCU pins (PA0, PA1): 0.64 x MIX", 322.58, yb + 38.1, 1.27, False)

    # ---- op-amp rail, VREF
    sh.heading("Op-amp rail and VREF 2.41 V (divider from the controller's +3V3, two RC stages, unbuffered)", 15, 193.04,
               250)
    x, yt = 25.4, 210.82
    v33(sh, (x, yt))
    yn = vcap(sh, note("VREF divider (top)"), x, yt, gnd=False)[1]          # divider node below the 10k
    vcap(sh, note("VREF divider (bottom)"), x, yn)
    sh.w((x, yn), (x + 10.16, yn))
    vcap(sh, note("VREF filter"), x + 10.16, yn)
    sh.w((x + 10.16, yn), (x + 25.4, yn))
    sh.lbl((x + 11.43, yn), "VREF_DIV", (1, 0))
    p = hpart(sh, note("VREF second RC stage"), x + 25.4, yn)
    sh.w(p, (p[0] + 25.4, yn))
    vcap(sh, note("VREF second filter"), p[0] + 5.08, yn)
    sh.lbl((p[0] + 25.4, yn), "VREF", (1, 0))
    tpx(sh, "VREF", (p[0] + 15.24, yn))
    sh.text("the + inputs are VREF's only DC load: no buffer; +3V3 ripple -> line out -72 dB at 100 Hz, -112 dB at "
            "1 kHz (S12 --bus2, section 9)", x, yn + 17.78, 1.27, False)
    # VA_MIX: 47 R + 22 uF from the slot rail, the op-amp supplies
    xq, yq = 200.66, 213.36
    sh.v5((xq - 5.08, yq))
    sh.w((xq - 5.08, yq), (xq, yq))
    p = hpart(sh, ref("RSUP0"), xq, yq)
    sh.w(p, (p[0] + 40.64, yq))
    sh.lbl((p[0] + 40.64, yq), "VA_MIX", (1, 0))
    vcap(sh, ref("CSUP0"), p[0] + 7.62, yq)
    sh.flag((p[0] + 15.24, yq), "VA_MIX")


EXTRA = {}
