"""Figures for blog posts -> docs/figures/blog/ (SVG, and PNG at 2x, in light and dark).

  signal_chain_*   block diagram of the voice: audio path, resonance feedback and what the MCU controls
  vcf_arch_*       the filter as blocks: mixer, ladder, output amplifier, resonance and cutoff control
  vcf_ladder_*     ladder core with mixer, output amplifier and bias chain (hw/design.py, sheet "vcf")
  vcf_control_*    exponential converter and resonance amplifier (sheets "vcf" and "resonance")
  vca_*            VCA core, tail-current source, line output, loopback and the R-2R trim DAC (sheet "vca")
  dco_*            the DCO redrawn for reading: V-to-I current sink on the left, integrator with reset on the
                   right. Values and nets as in hw/design.py, sheet "dco".

Needs playwright and Edge (only to rasterise the SVGs):  python tools/blog_figures.py
"""
import math
import os
from playwright.sync_api import sync_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "docs", "figures", "blog")
THEMES = {
    "light": dict(bg="#FFFFFF", ink="#1B2420", mut="#5B6A62", acc="#1E6B47", cop="#A8601F", fill="#EEF3F0"),
    "dark": dict(bg="#161D1A", ink="#E4EAE6", mut="#97A69E", acc="#5CC08E", cop="#D9955A", fill="#202A26"),
}


class Svg:
    def __init__(self):
        self.o = []

    def wire(self, *pts, cls="w"):
        self.o.append(f'<polyline class="{cls}" points="{" ".join(f"{x},{y}" for x, y in pts)}"/>')

    def dot(self, x, y):
        self.o.append(f'<circle class="dot" cx="{x}" cy="{y}" r="4.5"/>')

    def text(self, x, y, s, anchor="start", cls="v"):
        self.o.append(f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">{s}</text>')

    # ---- schematic symbols
    def r_h(self, x1, x2, y, val):
        m = (x1 + x2) / 2
        self.wire((x1, y), (m - 28, y)); self.wire((m + 28, y), (x2, y))
        self.o.append(f'<rect class="part" x="{m - 28}" y="{y - 10}" width="56" height="20"/>')
        self.text(m, y - 18, val, "middle")

    def r_v(self, x, y1, y2, val):
        m = (y1 + y2) / 2
        self.wire((x, y1), (x, m - 28)); self.wire((x, m + 28), (x, y2))
        self.o.append(f'<rect class="part" x="{x - 10}" y="{m - 28}" width="20" height="56"/>')
        self.text(x + 18, m + 5, val)

    def c_v(self, x, y1, y2, val):
        m = (y1 + y2) / 2
        self.wire((x, y1), (x, m - 5)); self.wire((x, m + 5), (x, y2))
        self.wire((x - 15, m - 5), (x + 15, m - 5), cls="w plate"); self.wire((x - 15, m + 5), (x + 15, m + 5), cls="w plate")
        self.text(x + 22, m + 5, val)

    def c_h(self, x1, x2, y, val):
        m = (x1 + x2) / 2
        self.wire((x1, y), (m - 5, y)); self.wire((m + 5, y), (x2, y))
        self.wire((m - 5, y - 15), (m - 5, y + 15), cls="w plate"); self.wire((m + 5, y - 15), (m + 5, y + 15), cls="w plate")
        self.text(m, y - 24, val, "middle")

    def gnd(self, x, y):
        for i, hw in enumerate((14, 9, 4)):
            self.wire((x - hw, y + 6 * i), (x + hw, y + 6 * i))

    def opamp(self, x, y_top, y_bot, top_sign, flip=False, label=None):
        """Inputs at (x, y_top) and (x, y_bot); output at (x + 100, middle), or (x - 100, middle) if flipped."""
        m, d = (y_top + y_bot) / 2, (-1 if flip else 1)
        self.o.append(f'<polygon class="part" points="{x},{m - 60} {x},{m + 60} {x + 100 * d},{m}"/>')
        signs = ("+", "\u2212") if top_sign == "+" else ("\u2212", "+")
        anchor = "end" if flip else "start"
        self.text(x + 9 * d, y_top + 6, signs[0], anchor, "sg"); self.text(x + 9 * d, y_bot + 6, signs[1], anchor, "sg")
        if label:
            self.text(x + 26 * d, m + 5, label, anchor, "in")

    def npn(self, bx, by, flip=False):
        """Base lead ends at (bx, by); collector at (bx +- 50, by - 30), emitter at (bx +- 50, by + 30)."""
        d = -1 if flip else 1
        self.wire((bx, by), (bx + 20 * d, by))
        self.wire((bx + 20 * d, by - 20), (bx + 20 * d, by + 20), cls="w plate")
        self.wire((bx + 20 * d, by - 9), (bx + 50 * d, by - 30)); self.wire((bx + 20 * d, by + 9), (bx + 50 * d, by + 30))
        self.o.append(f'<polygon class="dot" points="{bx + 50 * d},{by + 30} {bx + 36 * d},{by + 27} {bx + 42 * d},{by + 17}"/>')

    def isource(self, x, y):
        """Current source (arrow down), circle centred at (x, y), terminals at y - 22 and y + 22."""
        self.o.append(f'<circle class="part" cx="{x}" cy="{y}" r="22"/>')
        self.wire((x, y - 12), (x, y + 4))
        self.o.append(f'<polygon class="dot" points="{x - 6},{y + 2} {x + 6},{y + 2} {x},{y + 13}"/>')

    def sbox(self, x1, x2, yc, title, h=60):
        self.o.append(f'<rect class="part" x="{x1}" y="{yc - h / 2}" width="{x2 - x1}" height="{h}" rx="4"/>')
        self.text((x1 + x2) / 2, yc + 5, title, "middle", "bs")

    def nmos_h(self, x, y):
        """Channel between (x - 18, y) and (x + 18, y); gate lead ends at (x, y - 40)."""
        self.wire((x - 18, y), (x - 18, y - 16)); self.wire((x + 18, y), (x + 18, y - 16))
        self.wire((x - 26, y - 16), (x + 26, y - 16), cls="w plate")
        self.wire((x - 20, y - 25), (x + 20, y - 25), cls="w plate")
        self.wire((x, y - 25), (x, y - 40))

    def arrow_down(self, x, y):
        self.o.append(f'<polygon class="cop" points="{x - 7},{y - 8} {x + 7},{y - 8} {x},{y + 8}"/>')

    # ---- block diagram
    def box(self, x1, x2, yc, title, sub, h=70):
        self.o.append(f'<rect class="part" x="{x1}" y="{yc - h / 2}" width="{x2 - x1}" height="{h}" rx="5"/>')
        m = (x1 + x2) / 2
        self.text(m, yc - 3, title, "middle", "bt"); self.text(m, yc + 18, sub, "middle", "n")

    def arrow(self, *pts, cls="w", head="dot"):
        """Polyline with an arrowhead at its end (last segment horizontal or vertical)."""
        (xa, ya), (xb, yb) = pts[-2], pts[-1]
        dx, dy = (xb > xa) - (xb < xa), (yb > ya) - (yb < ya)
        self.wire(*pts[:-1], (xb - 9 * dx, yb - 9 * dy), cls=cls)
        px, py = -dy, dx
        self.o.append(f'<polygon class="{head}" points="{xb},{yb} {xb - 13 * dx + 6 * px},{yb - 13 * dy + 6 * py} '
                      f'{xb - 13 * dx - 6 * px},{yb - 13 * dy - 6 * py}"/>')


def page(s, c, w, h):
    css = f"""
    text{{font-family:"Segoe UI",Arial,Helvetica,sans-serif;fill:{c['ink']}}}
    .w{{fill:none;stroke:{c['ink']};stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}}
    .plate{{stroke-width:3.4}}
    .ctl{{stroke:{c['cop']}}} .dashed{{stroke-dasharray:7 6}}
    .part{{fill:{c['fill']};stroke:{c['ink']};stroke-width:2.2;stroke-linejoin:round}}
    .dot{{fill:{c['ink']}}}
    .ax{{fill:none;stroke:{c['mut']};stroke-width:1.5}} .dash{{stroke-dasharray:5 5}}
    .saw{{fill:none;stroke:{c['acc']};stroke-width:3;stroke-linejoin:round}}
    .v{{font-size:16px}}
    .n{{font-size:15px;fill:{c['mut']}}}
    .net{{font-size:16px;font-weight:600;fill:{c['acc']}}}
    .bt{{font-size:19px;font-weight:600;fill:{c['acc']}}}
    .sg{{font-size:19px;font-weight:600}}
    .in{{font-size:13px;fill:{c['mut']}}}
    .bs{{font-size:15px;font-weight:600}}
    .grp{{fill:none;stroke:{c['mut']};stroke-width:1.5;stroke-dasharray:6 5}}
    .h{{font-size:15px;font-weight:700;letter-spacing:1.6px;fill:{c['cop']}}}
    .cop{{fill:{c['cop']};font-size:16px;font-weight:600}}
    """
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'<style>{css}</style><rect width="{w}" height="{h}" fill="{c["bg"]}"/>' + "".join(s.o) + "</svg>")


def chain_svg(c):
    s = Svg()
    ya, yr, ym = 70, 175, 300                      # audio row, resonance row, top of the MCU box
    # audio path
    s.box(40, 180, ya, "DCO", "saw integrator")
    s.box(240, 360, ya, "Mixer", "passive")
    s.box(420, 620, ya, "Ladder VCF", "24 dB/oct")
    s.box(680, 820, ya, "Output amp", "gain 11")
    s.box(900, 1040, ya, "VCA", "differential pair")
    s.arrow((180, ya), (240, ya)); s.arrow((360, ya), (420, ya)); s.arrow((620, ya), (680, ya))
    s.arrow((820, ya), (900, ya)); s.arrow((1040, ya), (1150, ya))
    s.text(1160, ya - 3, "LINE OUT", cls="net"); s.text(1160, ya + 18, "1.2 Vpp", cls="n")
    # resonance feedback: filter output -> gain cell -> second ladder input
    s.dot(860, ya)
    s.arrow((860, ya), (860, yr), (800, yr))
    s.box(640, 800, yr, "Resonance", "feedback gain", h=64)
    s.arrow((640, yr), (570, yr), (570, ya + 35))
    # what the MCU controls
    for x, top, lines in ((110, ya + 35, ("reset pulse", "CV_AMP")), (300, ya + 35, ("pulse, sub,", "noise")),
                          (480, ya + 35, ("CV_CUT",)), (720, yr + 32, ("CV_RES",)),
                          (970, ya + 35, ("CV_VCA", "8-bit trim"))):
        s.arrow((x, ym), (x, top), cls="w ctl", head="cop")
        for i, t in enumerate(lines):
            s.text(x + 12, ym - 38 + 20 * i + (10 if len(lines) == 1 else 0), t, cls="cop")
    s.dot(1090, ya)
    s.arrow((1090, ya), (1090, ym), cls="w ctl dashed", head="cop")
    s.text(1102, ym - 38, "loopback", cls="cop"); s.text(1102, ym - 18, "to the ADC", cls="cop")
    s.o.append(f'<rect class="part" x="40" y="{ym}" width="1190" height="76" rx="5"/>')
    s.text(60, ym + 32, "CH32V microcontroller", cls="bt")
    s.text(60, ym + 56, "TIM2: pitch · TIM1: four 12-bit PWM control voltages · envelopes, LFO, glide and "
                        "arpeggiator at 1 kHz · 16 touch pads · 16 LEDs", cls="n")
    return page(s, c, 1270, 400)


def dco_svg(c):
    s = Svg()
    # ---- inset: what the circuit produces
    s.text(30, 44, "SAW OUTPUT", cls="h")
    s.wire((100, 80), (100, 210), (450, 210), cls="ax")
    s.wire((100, 90), (450, 90), cls="ax dash")
    s.text(90, 95, "6.5 V", "end", "n"); s.text(90, 215, "4.5 V", "end", "n")
    pts = [(100, 210)]
    for k in range(3):
        pts += [(200 + 100 * k, 90), (200 + 100 * k, 210)]
    pts.append((440, 162))
    s.wire(*pts, cls="saw")
    s.wire((202, 230), (298, 230), cls="ax"); s.wire((200, 222), (200, 238), cls="ax"); s.wire((300, 222), (300, 238), cls="ax")
    s.text(250, 252, "T = 1 / f", "middle", "n")
    s.text(307, 150, "reset", cls="n")
    s.text(100, 294, 'I = A · C / (T − t<tspan dy="5" font-size="12">reset</tspan><tspan dy="-5">)</tspan>'
                     ': the same amplitude A at every pitch', cls="n")

    # ---- left: CV_AMP filter and V-to-I converter (current sink)
    ys = 430
    s.text(30, 360, "CURRENT SINK (V → I)", cls="h")
    s.text(30, ys - 14, "PWM_AMP", cls="net"); s.text(30, ys + 24, "TIM1 PWM", cls="n")
    s.wire((30, ys), (110, ys))
    s.r_h(110, 220, ys, "1k"); s.r_h(220, 330, ys, "4.7k"); s.r_h(330, 440, ys, "4.7k")
    s.wire((440, ys), (590, ys))
    for x, val in ((220, "100n"), (330, "33n"), (518, "22n")):
        s.dot(x, ys); s.c_v(x, ys, 510, val); s.gnd(x, 510)
    s.dot(440, ys); s.r_v(440, ys, 510, "15k"); s.gnd(440, 510)
    s.text(470, ys - 14, "XAMP", "middle", "net")
    s.opamp(590, 430, 490, "+"); s.text(590, 388, "¼ LM324")
    s.r_h(690, 790, 460, "1k"); s.npn(790, 460); s.text(856, 466, "MMBT3904")
    s.wire((840, 490), (840, 540)); s.dot(840, 540)
    s.wire((840, 540), (572, 540), (572, 490), (590, 490))
    s.r_v(840, 540, 620, "33k"); s.gnd(840, 620)
    s.wire((840, 430), (840, 360), (990, 360))
    s.arrow_down(840, 394); s.text(856, 392, "I = V(XAMP) / 33k", cls="cop")
    s.text(856, 413, "∝ note frequency", cls="n")
    s.text(915, 348, "DCO_INT", "middle", "net")

    # ---- right: integrator with reset switch and level shifter
    s.text(1130, 44, "INTEGRATOR WITH RESET", cls="h")
    s.dot(990, 360); s.wire((990, 360), (1050, 360))
    s.opamp(1050, 360, 420, "-"); s.text(1090, 332, "½ TL072")
    s.wire((1050, 420), (1020, 420), (1020, 460)); s.text(1020, 482, "VREF 4.5 V", "middle", "net")
    s.wire((1150, 390), (1270, 390)); s.dot(1210, 390)
    s.text(1280, 386, "SAW", cls="net"); s.text(1280, 408, "4.5…6.5 V", cls="n")
    s.wire((990, 360), (990, 200), (1082, 200)); s.wire((1118, 200), (1210, 200), (1210, 390))
    s.dot(990, 280); s.dot(1210, 280); s.c_h(990, 1210, 280, "10n")
    s.nmos_h(1100, 200); s.text(1136, 178, "2N7002")
    s.wire((1100, 160), (1100, 120)); s.r_h(980, 1100, 120, "2.2k")
    s.wire((980, 120), (900, 120)); s.dot(900, 120)
    s.r_v(900, 50, 120, "10k"); s.text(900, 38, "VP (9–12 V)", "middle", "net")
    s.wire((900, 120), (900, 150)); s.npn(850, 180); s.text(916, 184, "MMBT3904")
    s.wire((900, 210), (900, 225)); s.gnd(900, 225)
    s.r_h(740, 850, 180, "4.7k")
    s.text(730, 176, "DCO_RST", "end", "net"); s.text(730, 198, "TIM2 CH1, 3 µs pulse per period", "end", "n")
    return page(s, c, 1370, 650)


def vcf_arch_svg(c):
    s = Svg()
    yr, ya, ye = 110, 230, 360                     # resonance row, audio row, expo row
    for i, t in enumerate(("SAW", "PULSE", "SUB", "NOISE")):
        s.text(40, ya - 22 + 18 * i, t, cls="n")
    s.arrow((110, ya), (200, ya))
    s.box(200, 320, ya, "Mixer", "passive")
    s.arrow((320, ya), (395, ya))
    s.o.append(f'<rect class="grp" x="380" y="{ya - 50}" width="500" height="100" rx="6"/>')
    s.text(540, ya - 60, "TRANSISTOR LADDER · 24 dB/oct", cls="h")
    s.sbox(395, 515, ya, "Input pair")
    for i in range(4):
        x = 535 + 85 * i
        s.wire((x - 20 if i == 0 else x - 10, ya), (x, ya)); s.sbox(x, x + 75, ya, f"Pole {i + 1}")
    s.arrow((865, ya), (940, ya))
    s.box(940, 1090, ya, "Output amp", "differential, ×11")
    s.arrow((1090, ya), (1200, ya)); s.text(1210, ya - 3, "LPF", cls="net"); s.text(1210, ya + 18, "to the VCA", cls="n")
    # resonance feedback
    s.dot(1140, ya)
    s.arrow((1140, ya), (1140, yr), (1080, yr))
    s.box(880, 1080, yr, "Resonance amp", "gain set by CV_RES", h=64)
    s.arrow((880, yr), (455, yr), (455, ya - 30))
    s.text(470, yr - 12, "feedback into the second ladder input", cls="n")
    s.arrow((980, 30), (980, yr - 32), cls="w ctl", head="cop"); s.text(992, 48, "CV_RES", cls="cop")
    # cutoff control
    s.box(345, 565, ye, "Expo converter", "LM324 + matched pair", h=64)
    s.arrow((455, ye - 32), (455, ya + 30), cls="w ctl", head="cop")
    s.text(470, ya + 78, "tail current: sets the cutoff of all four poles", cls="cop")
    s.arrow((150, ye), (345, ye), cls="w ctl", head="cop")
    s.text(150, ye - 12, "CV_CUT", cls="cop"); s.text(150, ye + 24, "0…5 V: 20 Hz…20 kHz", cls="n")
    return page(s, c, 1310, 420)


def vcf_ladder_svg(c):
    s = Svg()
    xa, xb = 560, 800
    s.text(40, 44, "TRANSISTOR LADDER, 4 POLES", cls="h")
    s.text(40, 68, "five BC847BS matched pairs, four 33 nF capacitors", cls="n")
    # load pair and three rungs (bases joined, biased from the chain), input pair at the bottom
    for by, vb in ((120, "VB4"), (230, "VB3"), (340, "VB2"), (450, "VB1")):
        s.npn(xa + 50, by, flip=True); s.npn(xb - 50, by)
        s.wire((xa + 50, by), (xb - 50, by)); s.text(680, by - 8, vb, "middle", "net")
    s.npn(xa - 50, 560); s.npn(xb + 50, 560, flip=True)
    for y in (175, 285, 395, 505):
        for x in (xa, xb):
            s.wire((x, y - 25), (x, y + 25)); s.dot(x, y)
        s.c_h(xa, xb, y, "33n")
    s.wire((xa, 90), (xa, 60), (xb, 60), (xb, 90)); s.text(680, 50, "VP", "middle", "net")
    # tail current
    s.wire((xa, 590), (xa, 620), (xb, 620), (xb, 590)); s.dot(680, 620)
    s.wire((680, 620), (680, 668)); s.isource(680, 690); s.wire((680, 712), (680, 735)); s.gnd(680, 735)
    s.text(692, 648, "TAIL", cls="net")
    s.text(646, 688, "tail current from the expo converter", "end", "cop")
    s.text(646, 709, "sets the cutoff of all four poles", "end", "n")
    # mixer into BIN1
    s.text(40, 385, "MIXER", cls="h")
    for i, (name, val) in enumerate((("SAW", "150k"), ("PULSE", "470k"), ("SUB", "470k"), ("NOISE", "470k"))):
        y = 422 + 46 * i
        s.text(40, y + 5, name, cls="net"); s.r_h(110, 250, y, val)
        if i:
            s.dot(250, y)
    s.wire((250, 422), (250, 560), (290, 560))
    s.dot(290, 560); s.r_v(290, 560, 640, "10k"); s.c_h(290, 430, 560, "1µ")
    s.dot(430, 560); s.r_v(430, 560, 640, "10k"); s.wire((430, 560), (510, 560))
    s.wire((290, 640), (430, 640)); s.text(360, 662, "VB0", "middle", "net")
    s.text(470, 548, "BIN1", "middle", "n")
    # second input: resonance feedback
    s.wire((850, 560), (900, 560)); s.dot(900, 560); s.r_v(900, 560, 640, "10k"); s.text(900, 662, "VB0", "middle", "net")
    s.r_h(900, 1030, 560, "22k"); s.c_h(1030, 1130, 560, "4.7µ")
    s.text(1140, 556, "RESOUT", cls="net"); s.text(1140, 578, "resonance feedback", cls="n")
    s.text(875, 548, "BIN2", "middle", "n")
    # output amplifier: two-op-amp instrumentation amplifier
    s.text(970, 464, "OUTPUT AMPLIFIER, GAIN 11", cls="h")
    s.wire((xb, 175), (940, 175), (940, 200), (1000, 200))
    s.opamp(1000, 200, 260, "+", label="TL072")
    s.wire((1000, 260), (970, 260), (970, 330)); s.wire((1100, 230), (1140, 230), (1140, 330))
    s.r_h(970, 1140, 330, "100k"); s.dot(970, 330); s.dot(1140, 230)
    s.arrow((1140, 230), (1140, 110)); s.text(1140, 96, "LPF", "middle", "net"); s.text(1154, 126, "to the VCA", cls="n")
    s.wire((xa, 175), (500, 175), (500, 30), (1310, 30), (1310, 200), (1370, 200))
    s.opamp(1370, 200, 260, "+", label="TL072")
    s.wire((1370, 260), (1340, 260), (1340, 330)); s.r_h(1340, 1510, 330, "10k")
    s.wire((1470, 230), (1510, 230), (1510, 410)); s.dot(1510, 330)
    s.r_h(970, 1510, 410, "10k"); s.wire((970, 410), (970, 330))
    s.r_h(1230, 1340, 295, "100k"); s.dot(1340, 295); s.text(1222, 300, "VREF", "end", "net")
    # bias chain
    s.text(960, 694, "BIAS CHAIN", cls="h"); s.text(1090, 694, "each tap decoupled with 10 µF", cls="n")
    s.text(902, 735, "VP", "end", "net")
    xs = [910 + 95 * i for i in range(7)]
    for i, val in enumerate(("2.2k", "1k", "1k", "1k", "1k", "2.4k")):
        s.r_h(xs[i], xs[i + 1], 730, val)
        if i < 5:
            s.dot(xs[i + 1], 730); s.text(xs[i + 1], 758, f"VB{4 - i}", "middle", "net")
    s.wire((xs[6], 730), (xs[6], 745)); s.gnd(xs[6], 745)
    return page(s, c, 1560, 790)


def vcf_control_svg(c):
    s = Svg()
    # ================= exponential converter
    s.text(30, 44, "EXPONENTIAL CONVERTER (CUTOFF)", cls="h")
    s.text(30, 186, "PWM_CUT", cls="net"); s.text(30, 224, "TIM1 PWM", cls="n")
    s.wire((30, 200), (110, 200))
    s.r_h(110, 220, 200, "1k"); s.r_h(220, 330, 200, "4.7k"); s.r_h(330, 460, 200, "33k")
    for x, val in ((220, "100n"), (330, "33n")):
        s.dot(x, 200); s.c_v(x, 200, 280, val); s.gnd(x, 280)
    s.wire((460, 200), (600, 200))
    s.dot(460, 200); s.r_v(460, 200, 290, "1.5k"); s.dot(530, 200); s.c_v(530, 200, 290, "100n")
    s.wire((460, 290), (530, 290)); s.text(495, 314, "VBIAS", "middle", "net")
    s.text(495, 186, "XCUT", "middle", "net")
    s.text(30, 350, "the 33k / 1.5k divider scales CV_CUT for the pair: 2 octaves per volt", cls="n")
    s.npn(600, 200); s.npn(820, 200, flip=True); s.text(828, 205, "VBIAS", cls="net")
    s.text(710, 205, "BC847BS", "middle", "n")
    s.wire((650, 230), (650, 260), (770, 260), (770, 230)); s.dot(710, 260)
    s.r_v(710, 260, 350, "1k"); s.wire((710, 350), (860, 350)); s.dot(830, 350)
    s.opamp(960, 320, 380, "+", flip=True, label="LM324")
    s.wire((960, 320), (980, 320)); s.text(988, 325, "2.5 V", cls="net")
    s.wire((770, 170), (770, 110)); s.r_v(770, 46, 110, "300k"); s.text(770, 36, "+5 V", "middle", "net")
    s.dot(770, 110); s.wire((770, 110), (1100, 110), (1100, 380), (960, 380))
    s.wire((830, 350), (830, 440), (990, 440)); s.c_h(990, 1100, 440, "1n"); s.wire((1100, 440), (1100, 380)); s.dot(1100, 380)
    s.wire((650, 170), (650, 84)); s.text(650, 70, "TAIL", "middle", "net"); s.text(664, 50, "to the ladder", "end", "n")
    s.arrow_down(650, 122); s.text(634, 120, "tail current", "end", "cop")
    s.text(634, 141, "8.3 µA × exp(ΔV / V<tspan dy=\"5\" font-size=\"12\">T</tspan><tspan dy=\"-5\">)</tspan>", "end", "n")
    # simulated cutoff against the control voltage
    rows = [l.split(",") for l in open(os.path.join(ROOT, "docs", "results", "s3_cutoff.csv")).read().split()[1:]]
    x0, x1, y0, y1 = 1260, 1510, 330, 90
    fx = lambda v: x0 + (x1 - x0) * v / 5
    fy = lambda f: y0 + (y1 - y0) * (math.log10(f) - 1) / 3.5
    s.text(1200, 44, "SIMULATED CUTOFF", cls="h")
    s.wire((x0, y1), (x0, y0), (x1, y0), cls="ax")
    for f, t in ((10, "10 Hz"), (100, "100 Hz"), (1000, "1 kHz"), (10000, "10 kHz")):
        s.wire((x0 - 5, fy(f)), (x1, fy(f)), cls="ax dash" if f > 10 else "ax"); s.text(x0 - 10, fy(f) + 5, t, "end", "n")
    for v in range(6):
        s.wire((fx(v), y0), (fx(v), y0 + 5), cls="ax"); s.text(fx(v), y0 + 23, str(v), "middle", "n")
    s.text((x0 + x1) / 2, y0 + 46, "CV_CUT [V]", "middle", "n")
    pts = [(round(fx(float(r[0])), 1), round(fy(float(r[1])), 1)) for r in rows]
    s.wire(*pts, cls="saw")
    for x, y in pts:
        s.o.append(f'<circle class="dot" cx="{x}" cy="{y}" r="3.5"/>')
    s.text(1275, 112, "2.05 octaves per volt", cls="n")

    # ================= resonance amplifier
    s.text(30, 560, "RESONANCE AMPLIFIER", cls="h")
    s.text(30, 584, "a second small VCA: its gain follows the tail current set by CV_RES", cls="n")
    s.text(30, 606, "self-oscillation starts at CV_RES ≈ 3.1 V", cls="n")
    s.text(372, 685, "LPF", "end", "net"); s.text(372, 706, "filter output", "end", "n")
    s.c_h(380, 500, 680, "1µ"); s.r_h(500, 650, 680, "120k"); s.wire((650, 680), (730, 680)); s.dot(690, 680)
    s.r_v(690, 680, 760, "10k"); s.text(690, 780, "VB2", "middle", "net")
    s.npn(730, 680); s.npn(950, 680, flip=True); s.text(840, 685, "BC847BS", "middle", "n")
    s.wire((950, 680), (990, 680)); s.r_v(990, 680, 760, "10k"); s.text(990, 780, "VB2", "middle", "net")
    s.wire((780, 710), (780, 740), (900, 740), (900, 710)); s.dot(840, 740); s.wire((840, 740), (840, 820))
    # collectors, loads and difference amplifier
    s.wire((780, 650), (780, 490), (1000, 490)); s.dot(780, 600)
    s.r_h(670, 780, 600, "4.7k"); s.text(662, 605, "VP", "end", "net")
    s.wire((900, 650), (900, 550), (1000, 550)); s.dot(900, 600)
    s.r_h(900, 1010, 600, "4.7k"); s.text(1018, 605, "VP", cls="net")
    s.r_h(1000, 1110, 490, "10k"); s.wire((1110, 490), (1180, 490)); s.dot(1140, 490)
    s.r_h(1000, 1110, 550, "10k"); s.wire((1110, 550), (1180, 550)); s.dot(1140, 550)
    s.r_v(1140, 550, 640, "10k"); s.text(1140, 662, "VREF", "middle", "net")
    s.opamp(1180, 490, 550, "-", label="TL072")
    s.wire((1140, 490), (1140, 420)); s.r_h(1140, 1320, 420, "10k"); s.wire((1320, 420), (1320, 520))
    s.wire((1280, 520), (1400, 520)); s.dot(1320, 520)
    s.text(1410, 516, "RESOUT", cls="net"); s.text(1410, 538, "via 4.7 µ and 22k", cls="n")
    s.text(1410, 558, "to the ladder", cls="n")
    # CV_RES filter and V-to-I converter (tail current)
    ys = 820
    s.text(30, ys - 14, "PWM_RES", cls="net"); s.text(30, ys + 24, "TIM1 PWM", cls="n")
    s.wire((30, ys), (110, ys))
    s.r_h(110, 220, ys, "1k"); s.r_h(220, 330, ys, "4.7k"); s.r_h(330, 440, ys, "4.7k")
    s.wire((440, ys), (590, ys))
    for x, val in ((220, "100n"), (330, "33n"), (518, "22n")):
        s.dot(x, ys); s.c_v(x, ys, ys + 80, val); s.gnd(x, ys + 80)
    s.dot(440, ys); s.r_v(440, ys, ys + 80, "15k"); s.gnd(440, ys + 80)
    s.text(470, ys - 14, "XRES", "middle", "net")
    s.opamp(590, ys, ys + 60, "+", label="LM324")
    s.r_h(690, 790, ys + 30, "1k"); s.npn(790, ys + 30); s.text(856, ys + 36, "MMBT3904")
    s.wire((840, ys + 60), (840, ys + 110)); s.dot(840, ys + 110)
    s.wire((840, ys + 110), (572, ys + 110), (572, ys + 60), (590, ys + 60))
    s.r_v(840, ys + 110, ys + 190, "6.2k"); s.gnd(840, ys + 190)
    s.arrow_down(840, 786); s.text(826, 812, "I = V(XRES) / 6.2k", "end", "cop")
    return page(s, c, 1560, 1040)


def vca_svg(c):
    s = Svg()
    s.text(30, 44, "VCA WITH OFFSET TRIM", cls="h")
    s.text(30, 68, "the gain follows the tail current set by CV_VCA", cls="n")
    s.text(30, 90, "the trim DAC shifts one base by a few millivolts to null the control feedthrough (thump)", cls="n")
    # input, attenuated 1:34 into the first base
    s.text(352, 315, "LPF", "end", "net"); s.text(352, 336, "filter output", "end", "n")
    s.c_h(360, 470, 310, "1µ"); s.r_h(470, 600, 310, "33k"); s.wire((600, 310), (730, 310))
    s.dot(620, 310); s.r_v(620, 310, 390, "2M"); s.gnd(620, 390)
    s.dot(690, 310); s.r_v(690, 310, 390, "1k"); s.text(690, 410, "VREF", "middle", "net")
    # differential pair
    s.npn(730, 310); s.npn(950, 310, flip=True); s.text(840, 315, "BC847BS", "middle", "n")
    s.wire((780, 340), (780, 370), (900, 370), (900, 340)); s.dot(840, 370); s.wire((840, 370), (840, 450))
    # second base: bias and trim
    s.wire((950, 310), (1060, 310)); s.dot(990, 310); s.r_v(990, 310, 390, "1k"); s.text(990, 410, "VREF", "middle", "net")
    s.r_v(1060, 310, 400, "1M"); s.wire((1060, 400), (1060, 470)); s.text(1048, 462, "VTRIM", "end", "net")
    # collectors, loads and difference amplifier
    s.wire((780, 280), (780, 120), (1000, 120)); s.dot(780, 230)
    s.r_h(670, 780, 230, "4.7k"); s.text(662, 235, "VP", "end", "net")
    s.wire((900, 280), (900, 180), (1000, 180)); s.dot(900, 230)
    s.r_h(900, 1010, 230, "4.7k"); s.text(1018, 235, "VP", cls="net")
    s.r_h(1000, 1110, 120, "10k"); s.wire((1110, 120), (1180, 120)); s.dot(1140, 120)
    s.r_h(1000, 1110, 180, "10k"); s.wire((1110, 180), (1180, 180)); s.dot(1140, 180)
    s.r_v(1140, 180, 270, "22k"); s.text(1140, 292, "VREF", "middle", "net")
    s.opamp(1180, 120, 180, "-", label="TL072")
    s.wire((1140, 120), (1140, 50)); s.r_h(1140, 1320, 50, "22k"); s.wire((1320, 50), (1320, 150))
    s.wire((1280, 150), (1320, 150)); s.dot(1320, 150)
    # line output
    s.c_h(1320, 1420, 150, "10µ"); s.wire((1420, 150), (1480, 150)); s.dot(1440, 150)
    s.r_v(1440, 150, 240, "100k"); s.gnd(1440, 240)
    s.text(1490, 155, "LINE OUT", cls="net")
    # loopback divider to the ADC
    s.r_v(1320, 150, 260, "10k"); s.dot(1320, 260); s.r_v(1320, 260, 350, "15k"); s.gnd(1320, 350)
    s.wire((1320, 260), (1390, 260)); s.c_v(1390, 260, 350, "1n"); s.gnd(1390, 350)
    s.text(1306, 256, "ADC", "end", "net"); s.text(1306, 277, "loopback, PD5", "end", "n")
    # CV_VCA filter and V-to-I converter (tail current)
    ys = 450
    s.text(30, ys - 14, "PWM_VCA", cls="net"); s.text(30, ys + 24, "TIM1 PWM", cls="n")
    s.wire((30, ys), (110, ys))
    s.r_h(110, 220, ys, "1k"); s.r_h(220, 330, ys, "4.7k"); s.r_h(330, 440, ys, "4.7k")
    s.wire((440, ys), (590, ys))
    for x, val in ((220, "100n"), (330, "33n"), (518, "22n")):
        s.dot(x, ys); s.c_v(x, ys, ys + 80, val); s.gnd(x, ys + 80)
    s.dot(440, ys); s.r_v(440, ys, ys + 80, "15k"); s.gnd(440, ys + 80)
    s.text(470, ys - 14, "XVCA", "middle", "net")
    s.opamp(590, ys, ys + 60, "+", label="LM324")
    s.r_h(690, 790, ys + 30, "1k"); s.npn(790, ys + 30); s.text(856, ys + 36, "MMBT3904")
    s.wire((840, ys + 60), (840, ys + 110)); s.dot(840, ys + 110)
    s.wire((840, ys + 110), (572, ys + 110), (572, ys + 60), (590, ys + 60))
    s.r_v(840, ys + 110, ys + 190, "4.7k"); s.gnd(840, ys + 190)
    s.r_h(840, 960, ys + 110, "470k"); s.text(968, ys + 115, "+5 V", cls="net")
    s.arrow_down(840, 416); s.text(826, 442, "I = V(XVCA) / 4.7k", "end", "cop")
    # trim DAC: 8-bit R-2R on the third 74HC595
    s.text(1120, 408, "TRIM DAC, 8 BIT", cls="h")
    s.text(1120, 430, "R-2R ladder: 100k in series, 200k to each bit and to ground", cls="n")
    xs = [1060 + 70 * k for k in range(8)]
    s.o.append('<rect class="part" x="1035" y="590" width="540" height="58" rx="5"/>')
    for k, x in enumerate(xs):
        if k:
            s.r_h(xs[k - 1], x, 470, "");
        s.dot(x, 470); s.r_v(x, 470, 590, "")
        s.text(x, 612, f"Q{7 - k}", "middle", "bs")
    s.wire((xs[7], 470), (1590, 470)); s.r_v(1590, 470, 560, ""); s.gnd(1590, 560)
    s.text(1305, 636, "74HC595, third in the LED shift-register chain", "middle", "in")
    return page(s, c, 1640, 680)


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        for th, c in THEMES.items():
            for name, fn in (("signal_chain", chain_svg), ("dco", dco_svg), ("vcf_arch", vcf_arch_svg),
                             ("vcf_ladder", vcf_ladder_svg), ("vcf_control", vcf_control_svg), ("vca", vca_svg)):
                svg = fn(c)
                with open(os.path.join(OUT, f"{name}_{th}.svg"), "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(svg)
                pg = b.new_page(device_scale_factor=2)
                pg.set_content(f'<body style="margin:0">{svg}</body>')
                pg.locator("svg").screenshot(path=os.path.join(OUT, f"{name}_{th}.png"))
                pg.close()
        b.close()
    print("written", OUT)


if __name__ == "__main__":
    main()
