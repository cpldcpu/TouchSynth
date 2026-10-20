"""Silkscreen of the backplane PCB (called from gen_pcb_bp.py after placement, or with --art on a routed board).

Front: title and rev under the cards, slot numbers with a small waveform each (the sockets mark pin 1 themselves),
connector and jumper names, LED names. Back (no parts there; mirrored to read from the back): title block, the
cards' constant-power pan law with the 8 voices spread over the stereo field, a summing-amplifier glyph (8 inputs,
one bus per channel), one waveform per slot aligned with its socket, the socket pinout beside slot 1 and the
plug-in notes along the south guide band. Text at least 0.8 mm high with 0.15 mm strokes (JLCPCB minimum).
"""
import math
import pcbnew
import board as B
import pcb_place_bp as PB
from pcb_art import seg, poly, text, resonant_saw, LINE, TEXT, DATE, URL

D = B.D
W = PB.W
SOCKET_PINS = {1: "+5V", 2: "+5V", 3: "GND", 4: "GND", 5: "L", 6: "AGND", 7: "R", 8: "GND", 9: "SYNC", 10: "RX",
               11: "TX", 12: "NRST", 13: "GND", 14: "SWIO", 15: "CLK", 16: "GND"}


# ------------------------------------------------------------------ waveforms (normalised to -1 ... 1)
def _saw(p):
    return 1.0 - 2.0 * (p % 1.0)


def wave(kind, n=160, periods=2.0):
    """one of the eight slot motifs: list of values over `periods` periods"""
    if kind == "reso":
        v = resonant_saw(n=n, periods=periods)
        return v
    out = []
    for i in range(n):
        p = periods * i / (n - 1)
        if kind == "saw":
            v = _saw(p)
        elif kind == "square":
            v = 1.0 if p % 1.0 < 0.5 else -1.0
        elif kind == "tri":
            q = p % 1.0
            v = 4 * q - 1 if q < 0.5 else 3 - 4 * q
        elif kind == "pulse":
            v = 1.0 if p % 1.0 < 0.2 else -1.0
        elif kind == "sine":
            v = math.sin(2 * math.pi * p)
        elif kind == "sync":                                 # hard sync: a 1.6x saw reset every master period
            v = _saw(1.6 * (p % 1.0))
        else:                                                # "super": three detuned saws
            v = (_saw(p) + _saw(p * 1.07 + 0.3) + _saw(p * 0.94 + 0.6)) / 3 * 1.6
        out.append(max(-1.0, min(1.0, v)))
    return out


SLOT_WAVES = ("saw", "square", "tri", "pulse", "reso", "sine", "sync", "super")


def wave_pts(kind, x0, x1, yc, amp, n=160):
    """polyline of a waveform; square-ish waves get vertical edges"""
    v = wave(kind, n)
    pts = [(x0 + (x1 - x0) * i / (len(v) - 1), yc - amp * y) for i, y in enumerate(v)]
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        if abs(b[1] - a[1]) > amp * 0.8:                     # a jump: draw it as a vertical edge
            out.append((b[0], a[1]))
        out.append(b)
    return out


# ------------------------------------------------------------------ front
def front(board, F, pad_xy):
    S = pcbnew.F_SilkS
    text(board, S, "TouchSynth Poly backplane", 64.0, 48.8, 2.0, 0.3, italic=True)
    text(board, S, f"rev {B.REV}  {DATE}  {URL}", 64.0, 51.3, 1.0, 0.15)
    for k in range(1, 9):
        x = PB.SLOT_X[k - 1]
        text(board, S, str(k), x + 2.6, 57.9, 1.6, 0.25)
        poly(board, S, wave_pts(SLOT_WAVES[k - 1], x - 3.4, x + 1.2, 56.6, 1.1, 90))
    text(board, S, "card part side faces west (toward slot 1); pin 1 = south-west", 56.0, 96.0, TEXT)
    pos = F["J3"].GetPosition()
    text(board, S, "LINE OUT", pcbnew.ToMM(pos.x) + 3.5, pcbnew.ToMM(pos.y) - 7.6, 1.0, 0.15)
    for ref, names, dx, dy in (("J5", ("3V3", "DIO", "CLK", "GND"), -2.6, 0.0), ("J6", ("GND", "TX", "RX"), -2.4, 0.0),
                               ("J7", ("4", "5", "SH"), 0.0, 1.9)):
        for i, nm in enumerate(names, 1):
            x, y = pad_xy(F[ref], str(i))
            text(board, S, nm, x + dx, y + dy, TEXT)
    for ref, label, dx, dy in (("J5", "SWD", 0.0, -1.7), ("J6", "UART", 0.0, -1.9), ("J7", "MIDI IN", -4.4, 0.0)):
        x, y = pad_xy(F[ref], "1")
        text(board, S, label, x + dx, y + dy, 0.9, 0.15)
    x, y = pad_xy(F["JP2"], "1")
    text(board, S, "BOOT", x, y - 1.9, TEXT)
    x, y = pad_xy(F["JP2"], "3")
    text(board, S, "RUN", x, y - 1.9, TEXT)
    x, y = pad_xy(F["JP1"], "1")                    # supply jumper: USB (pins 1-2) or EXT (2-3, from J4)
    text(board, S, "USB", x - 0.6, y - 1.9, TEXT)
    x3, y3 = pad_xy(F["JP1"], "3")
    x4, y4 = pad_xy(F["J4"], "1")
    text(board, S, "EXT 5V", x - 1.2, (y3 + y4) / 2, TEXT)      # between JP1 pin 3 and J4 pin 1 (+5V_EXT)
    x, y = pad_xy(F["J4"], "2")
    text(board, S, "GND", x - 0.6, y + 1.9, TEXT)
    leds = {p.note: p.ref for p in D.PARTS if p.lib_id == "Device:LED"}
    for note, label in (("power", "PWR"), ("activity", "ACT"), ("host port fault", "FLT"),
                        ("host port powered", "HOST")):
        pos = F[leds[note]].GetPosition()
        text(board, S, label, pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y) + 2.2, TEXT)
    pos = F["SW1"].GetPosition()
    text(board, S, "RESET", pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y) + 3.9, TEXT)
    pos = F["U7"].GetPosition()                     # SPI flash (not fitted): named between its pad rows
    text(board, S, "SPI", pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y) - 0.75, 0.8, 0.15)
    text(board, S, "FLASH", pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y) + 0.75, 0.8, 0.15)
    x, y = pad_xy(F["J1"], "A6")
    text(board, S, "USB", pcbnew.ToMM(F["J1"].GetPosition().x), y + 2.4, 1.0)
    # connectors with a descriptive label: their references on the fab layer only
    for ref in ("J3", "J4", "J5", "J6", "J7", "JP1", "JP2", "JP3", "SW1") + tuple(f"J{9 + k}" for k in range(1, 9)):
        F[ref].Reference().SetLayer(pcbnew.F_Fab)


# ------------------------------------------------------------------ back
def back(board):
    """coordinates as seen from the back (x_back = W - x_top; mx() maps them to the board), so that the art reads
    from the back. Placed where the back has no through-hole pads: the title block between the sockets and the
    south guide rail (only tented band vias there), the two plots behind the east part of the controller strip,
    the socket pinout in the gap between slot 1 and the line-out jack"""
    L = pcbnew.B_SilkS
    mx = lambda x: W - x

    def t(s, x, y, size, **kw):
        return text(board, L, s, mx(x), y, size, mirror=True, **kw)

    def pl(pts, w=LINE):
        poly(board, L, [(mx(x), y) for x, y in pts], w)

    def circle(xc, yc, r, w=LINE, n=16):
        pl([(xc + r * math.cos(2 * math.pi * i / n), yc + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)], w)

    # title block between the sockets and the south guide rail
    t("TouchSynth Poly", 50.0, 84.6, 3.2, thick=0.45, italic=True)
    t("backplane  -  8 voices  -  USB MIDI", 50.0, 88.6, 1.2, thick=0.18)
    t(f"rev {B.REV}  -  {DATE}  -  CH32V203, {getattr(D, 'COPPER_LAYERS', 2)} layers  -  {URL}", 50.0, 90.8, 1.0,
      thick=0.15)

    # constant-power pan law (left) with the 8 voices spread over the stereo field
    x0, x1, y0, y1 = 6.0, 29.0, 16.0, 25.0
    pl([(x0, y0 - 0.5), (x0, y1), (x1 + 0.6, y1)])                      # axes
    pl([(x0 - 0.5, y0 + 0.3), (x0, y0 - 0.5), (x0 + 0.5, y0 + 0.3)])
    cl = [(x0 + (x1 - x0) * i / 60, y1 - (y1 - y0) * math.cos(math.pi / 2 * i / 60)) for i in range(61)]
    cr = [(x0 + (x1 - x0) * i / 60, y1 - (y1 - y0) * math.sin(math.pi / 2 * i / 60)) for i in range(61)]
    pl(cl, 0.2); pl(cr, 0.2)
    for k in range(8):
        pan = (k + 0.5) / 8
        x = x0 + (x1 - x0) * pan
        circle(x, y1 - (y1 - y0) * math.cos(math.pi / 2 * pan), 0.45)
        circle(x, y1 - (y1 - y0) * math.sin(math.pi / 2 * pan), 0.45)
        pl([(x, y1), (x, y1 + 0.5)])
    t("L", x0 + 1.2, y0 - 1.3, TEXT); t("R", x1, y0 - 1.3, TEXT)
    t("pan: cos / sin, 8 voices", (x0 + x1) / 2, y1 + 1.5, TEXT)

    # summing amplifier glyph: 8 inputs through resistors onto one node, inverting amp, L / R out
    gx, gy0, gy1 = 4.5, 29.5, 39.0
    node_x = gx + 7.5
    for k in range(8):
        y = gy0 + (gy1 - gy0) * k / 7
        pl(wave_pts(SLOT_WAVES[k], gx, gx + 2.6, y, 0.45, 40), LINE)
        zig = [(gx + 3.2, y), (gx + 3.6, y)] + [(gx + 3.9 + 0.3 * i, y + (0.4 if i % 2 == 0 else -0.4))
                                                for i in range(6)] + [(gx + 5.7, y), (node_x, y)]
        pl(zig)
    pl([(node_x, gy0), (node_x, gy1)], 0.2)
    ym = (gy0 + gy1) / 2
    pl([(node_x, ym), (node_x + 2.0, ym)])
    ax = node_x + 2.0
    pl([(ax, ym - 3.2), (ax, ym + 3.2), (ax + 5.4, ym), (ax, ym - 3.2)], 0.2)        # op-amp triangle
    t("-", ax + 1.0, ym - 1.2, TEXT); t("+", ax + 1.0, ym + 1.4, TEXT)
    pl([(ax + 5.4, ym), (ax + 8.6, ym)])
    pl([(ax + 7.9, ym - 0.6), (ax + 8.6, ym), (ax + 7.9, ym + 0.6)])
    pl([(ax + 6.6, ym), (ax + 6.6, ym - 4.6), (node_x + 1.0, ym - 4.6), (node_x + 1.0, ym)])   # feedback
    t("L / R", ax + 11.6, ym, 1.0)
    t("two buses, AUDIO_GND mirrored", gx + 10.0, gy1 + 1.9, TEXT)

    # one waveform per slot, aligned with its socket (between the strip and the sockets)
    for k in range(1, 9):
        x = W - PB.SLOT_X[k - 1]
        pl(wave_pts(SLOT_WAVES[k - 1], x - 3.6, x + 3.6, 53.0, 1.7), 0.2)
        t(f"VOICE {k}", x, 57.3, TEXT)

    # socket pinout as a small drawing behind the MCU (no through-hole pads there): seen from the back the odd row
    # is on the right, pin 1 at the bottom
    cx, ytop = 47.0, 18.0
    t("socket pinout (seen from this side)", cx, ytop - 2.6, TEXT)
    for pos in range(1, 9):
        y = ytop + 2.54 * (8 - pos)
        o, e = 2 * pos - 1, 2 * pos
        for x, n in ((cx + 1.27, o), (cx - 1.27, e)):
            if n == 1:
                pl([(x - 0.6, y - 0.6), (x + 0.6, y - 0.6), (x + 0.6, y + 0.6), (x - 0.6, y + 0.6), (x - 0.6, y - 0.6)])
            else:
                circle(x, y, 0.6)
        t(f"{o} {SOCKET_PINS[o]}", cx + 5.6, y, TEXT)
        t(f"{SOCKET_PINS[e]} {e}", cx - 5.6, y, TEXT)
    t("card part side toward slot 1", cx, ytop + 2.54 * 7 + 2.4, TEXT)

    # plug-in notes along the south guide band
    t("8 slots, 10 mm pitch  -  card part side toward slot 1  -  pin 1: square pad, south-west  -  "
      "no hot-plugging", 50.0, 95.8, TEXT)
