"""Silkscreen of the voice card PCB (called from gen_pcb.py after placement).

Front: title, rev and date at the debug edge, pin names of the debug-edge headers, LED names, J1 pin 1, short block
labels where there is room, test-point names (footprint values), references of the ICs, transistors and connectors.
Back (no parts there): title and project URL, a ladder-filter motif (resonant sawtooth through the ladder,
its response family), the J1 pinout aligned with its pins and the plug-in orientation, mirrored to read from the back.
Text at least 0.8 mm high with 0.15 mm strokes (JLCPCB minimum).
"""
import datetime, math
import pcbnew
import board as B
import pcb_place as PP

MM = pcbnew.FromMM
V = pcbnew.VECTOR2I_MM
W, H = PP.W, PP.H

LINE = 0.15                     # silk line width (JLCPCB minimum ~0.15)
TEXT = 0.8                      # smallest silk text height (JLCPCB: 0.8 mm at 0.15 mm stroke)


# ------------------------------------------------------------------ primitives
def seg(board, layer, a, b, w=LINE):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(*a)); s.SetEnd(V(*b))
    s.SetLayer(layer); s.SetWidth(MM(w))
    board.Add(s)
    return s


def poly(board, layer, pts, w=LINE):
    for a, b in zip(pts, pts[1:]):
        seg(board, layer, a, b, w)


def text(board, layer, s, x, y, size, thick=None, rot=0, just="c", italic=False, mirror=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s); t.SetLayer(layer)
    t.SetTextSize(V(size, size)); t.SetTextThickness(MM(thick or max(0.15, size * 0.15)))
    t.SetPosition(V(x, y)); t.SetTextAngleDegrees(rot)
    t.SetHorizJustify({"l": pcbnew.GR_TEXT_H_ALIGN_LEFT, "c": pcbnew.GR_TEXT_H_ALIGN_CENTER,
                       "r": pcbnew.GR_TEXT_H_ALIGN_RIGHT}[just])
    t.SetItalic(italic); t.SetMirrored(mirror)
    board.Add(t)
    return t


def bbox_mm(item):
    b = item.GetBoundingBox()
    return (pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()), pcbnew.ToMM(b.GetBottom()))


def hits(r, obst, m=0.0):
    return any(r[0] - m < o[2] and o[0] < r[2] + m and r[1] - m < o[3] and o[1] < r[3] + m for o in obst)


def pad_boxes(board):
    out = []
    for p in board.GetPads():
        out.append(bbox_mm(p))
    return out


# ------------------------------------------------------------------ front labels
PIN_NAMES = {"+5V_PRG": "5V", "SWIO": "SWIO", "GND": "GND", "AUDIO_L": "L", "AUDIO_R": "R"}
LED_NAMES = {"power": "PWR", "playing": "PLAY", "status": "STAT"}
BLOCK_LABELS = {"ladder": "LADDER", "ina": "INA", "res": "RES", "vca": "VCA", "dif": "DIFF", "out": "OUT",
                "dac": "DAC", "ref": "REF", "mcu": "MCU", "lm": "EXPO", "cv": "CV", "pwr": "PWR"}
DATE = datetime.date.today().isoformat()          # generation date, as on the schematic title blocks


def labels(board, fps):
    """title, pin names below the debug-edge headers, LED names, pin-1 mark of J1 (the areas are kept free by the
    placer: pcb_place.SILK)"""
    L = pcbnew.F_SilkS
    x0, y0, x1, y1 = PP.SILK["title"]
    text(board, L, "TouchSynth Poly — voice", (x0 + x1) / 2, y0 + 0.75, 0.9, 0.15, italic=True)
    text(board, L, f"rev {B.REV}  {DATE}", (x0 + x1) / 2, y0 + 2.2, TEXT)
    for p, fp in fps.values():
        if p.ref.startswith("J") and p.value in ("SWIO", "LINE OUT"):
            for pad in fp.Pads():
                s = PIN_NAMES.get(p.pins[pad.GetNumber()], p.pins[pad.GetNumber()])
                dy = 2.95 if pad.GetNumber() == "2" and len(fp.Pads()) == 3 else 1.95     # staggered: 2.54 mm pitch
                x, y = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y) + dy
                text(board, L, s, x, y, TEXT)                    # below the pad
        if p.lib_id == "Device:LED":
            x = pcbnew.ToMM(fp.GetPosition().x)
            text(board, L, LED_NAMES[p.note], x, PP.SILK["leds"][3] - TEXT / 2 + 0.15, TEXT)
        if p.value == "BACKPLANE":                                # pin 1 mark beside pin 1, clear of pads
            pad = [q for q in fp.Pads() if q.GetNumber() == "1"][0]
            px, py = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
            obst = pad_boxes(board) + [bbox_mm(g) for g in fp.GraphicalItems() if g.GetLayer() == L]
            for dx, dy in ((2.3, 0.0), (2.3, -1.6), (1.27, -1.9), (0.0, -1.9)):
                r = (px + dx - 0.45, py + dy - 0.55, px + dx + 0.45, py + dy + 0.55)
                if not hits(r, obst, 0.2):
                    text(board, L, "1", px + dx, py + dy, TEXT)
                    break                                     # else: the footprint's pin-1 corner mark only


def block_labels(board):
    """short function names in a free spot of each block (after placement, before routing)"""
    obst = [bbox_mm(f) for f in board.GetFootprints()] + pad_boxes(board)
    obst = [(o[0], max(o[1], 0.0), o[2], min(o[3], H)) for o in obst]
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.F_SilkS:
            obst.append(bbox_mm(d))
    obst += list(PP.RESERVED.values())
    for blk, s in BLOCK_LABELS.items():
        if blk in PP.SILK:                                 # a spot kept free by the placer
            x0, y0, x1, y1 = PP.SILK[blk]
            text(board, pcbnew.F_SilkS, s, (x0 + x1) / 2, (y0 + y1) / 2, TEXT)
            continue
        bx0, by0, bx1, by1 = PP.BLOCKS[blk]
        bx0, by0, bx1, by1 = bx0 - 2.0, by0 - 2.0, bx1 + 2.0, by1 + 2.0  # may reach a little past the block
        probe = text(board, pcbnew.F_SilkS, s, 0, 0, TEXT)
        r = bbox_mm(probe)                                 # KiCad's box includes line spacing: use the glyph width
        tw, th = r[2] - r[0] - 0.5, TEXT + 0.2
        board.Remove(probe)
        best = None
        y = by0 + th / 2 + 0.1
        while y < by1 - th / 2:
            x = bx0 + tw / 2 + 0.1
            while x < bx1 - tw / 2:
                r = (x - tw / 2, y - th / 2, x + tw / 2, y + th / 2)
                if r[0] > PP.GUIDE and r[2] < W - PP.GUIDE and r[1] > 0.4 and r[3] < H - 0.4 and                         not hits(r, obst, 0.15):
                    d = (x - bx0) + (y - by0)                      # prefer the (inner) top-left corner
                    d += 30.0 * (min(x - bx0, bx1 - x, y - by0, by1 - y) < 2.0 + tw / 2)
                    if best is None or d < best[0]:
                        best = (d, x, y, r)
                x += 0.25
            y += 0.25
        if best:
            text(board, pcbnew.F_SilkS, s, best[1], best[2], TEXT)
            obst.append(best[3])
        else:
            print(f"art: no room for the block label {s}")


# ------------------------------------------------------------------ reference designators
def place_refs(board):
    """move every silkscreen reference (ICs, transistors, connectors) to a free spot next to its part"""
    fps = [f for f in board.GetFootprints() if f.Reference().IsVisible()
           and f.Reference().GetLayer() == pcbnew.F_SilkS]
    boxes = {}
    for f in board.GetFootprints():
        b = f.GetBoundingBox(False)
        boxes[f.GetReference()] = (pcbnew.ToMM(b.GetLeft()), max(0.0, pcbnew.ToMM(b.GetTop())),
                                   pcbnew.ToMM(b.GetRight()), min(H, pcbnew.ToMM(b.GetBottom())))
    obst = list(boxes.values()) + pad_boxes(board)
    for f in board.GetFootprints():
        v = f.Value()
        if v.IsVisible() and v.GetLayer() == pcbnew.F_SilkS:
            obst.append(bbox_mm(v))
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.F_SilkS and isinstance(d, pcbnew.PCB_TEXT):
            obst.append(bbox_mm(d))
    for f in sorted(fps, key=lambda f: f.GetReference()):
        t = f.Reference()
        t.SetKeepUpright(False); t.SetTextAngleDegrees(0)
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        x0, y0, x1, y1 = boxes[f.GetReference()]
        if f.GetReference().startswith("J"):                  # headers: below the pads / above J1
            pads = [bbox_mm(p) for p in f.Pads()]
            x0, y0 = min(p[0] for p in pads), min(p[1] for p in pads)
            x1, y1 = max(p[2] for p in pads), max(p[3] for p in pads)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        th = pcbnew.ToMM(t.GetTextSize().y)
        tw = len(t.GetText()) * th * 0.8
        cands = [(cx, cy)] if (x1 - x0) > tw + 1.0 and (y1 - y0) > 3.0 and not f.GetReference().startswith("J") \
            else []                                           # large parts: inside the body outline first
        for d in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
            for sx in (1, -1):
                cands += [(cx + sx * d, y0 - th / 2 - 0.2), (cx + sx * d, y1 + th / 2 + 0.2)]
            for sy in (1, -1):
                cands += [(x0 - tw / 2 - 0.25, cy + sy * d), (x1 + tw / 2 + 0.25, cy + sy * d)]
        own = [p for p in pad_boxes(board)]
        for x, y in cands:
            r = (x - tw / 2, y - th / 2, x + tw / 2, y + th / 2)
            inside_body = (x, y) == (cx, cy) and cands[0] == (cx, cy)
            o = [b for b in obst if b != boxes[f.GetReference()]] if inside_body else obst
            if r[0] > 0.4 and r[2] < W - 0.4 and r[1] > 0.4 and r[3] < H - 0.4 and not hits(r, o, 0.15):
                t.SetPosition(V(x, y))
                obst.append(r)
                break
        else:
            t.SetLayer(pcbnew.F_Fab)                       # no room: reference on the fab drawing only
            print(f"art: reference of {f.GetReference()} moved to F.Fab (no free spot)")


# ------------------------------------------------------------------ back side
BP_PINS = {1: "+5V", 2: "+5V", 3: "GND", 4: "GND", 5: "AUDIO_L", 6: "AUDIO_GND", 7: "AUDIO_R", 8: "GND", 9: "SYNC",
           10: "RX", 11: "TX", 12: "NRST", 13: "GND", 14: "SWIO", 15: "CLK_IN", 16: "GND"}
URL = "github.com/cpldcpu/TouchSynthPoly"


def resonant_saw(n=400, periods=2.0, k=3.6, fc=0.05):
    """sawtooth through a 4-pole ladder (tanh stages), the last `periods` periods, normalised"""
    per = 300
    g = 1 - math.exp(-2 * math.pi * fc)
    s = [0.0] * 4
    out = []
    for i in range(int(per * (periods + 4))):
        x = 1.0 - 2.0 * ((i % per) / per)
        u = math.tanh(x - k * s[3])
        for j in range(4):
            s[j] += g * ((u if j == 0 else math.tanh(s[j - 1])) - math.tanh(s[j]))
        out.append(s[3])
    tail = out[-int(per * periods):]
    m = max(abs(v) for v in tail)
    step = max(1, len(tail) // n)
    return [v / m for v in tail[::step]]


def ladder_db(w, k):
    return 20 * math.log10(abs(1 / ((1 + complex(0, w)) ** 4 + k)))


def back(board):
    """title and URL, a ladder-filter motif (resonant sawtooth, response family), the J1
    pinout next to the connector and the plug-in orientation; mirrored so everything reads from the back.
    Coordinates are as seen from the back (mx() maps them to the board)."""
    L = pcbnew.B_SilkS
    mx = lambda x: W - x

    def t(s, x, y, size, **kw):
        return text(board, L, s, mx(x), y, size, mirror=True, **kw)

    def pl(pts, w=LINE):
        poly(board, L, [(mx(x), y) for x, y in pts], w)
    t("TouchSynth Poly", W / 2, 7.0, 2.2, thick=0.33, italic=True)       # below the debug-edge header pins
    t(f"voice card  -  rev {B.REV}  -  {DATE}", W / 2, 9.6, 1.0, thick=0.15)
    t(URL, W / 2, 11.3, 1.0, thick=0.15)
    t("4 layers: signal / GND / VA, 3V3, 5V / signal  -  no parts on this side", W / 2, 12.9, TEXT)

    # motif: a sawtooth through the ladder (left) and the ladder response for rising resonance (right)
    xa0, xa1, ya0, ya1 = 4.0, 22.0, 14.8, 20.8
    sig = resonant_saw()
    amp = (ya1 - ya0) / 2
    pl([(xa0 + (xa1 - xa0) * i / (len(sig) - 1), (ya0 + ya1) / 2 - amp * v) for i, v in enumerate(sig)][::2])
    xr0, xr1 = 26.0, 46.0
    for k in (0.0, 1.5, 2.7, 3.4, 3.8):
        pts = []
        for i in range(121):
            w = 10 ** (-1.2 + 2.2 * i / 120)
            db = max(-30.0, min(8.0, ladder_db(w, k)))
            pts.append((xr0 + (xr1 - xr0) * i / 120, ya0 + (8.0 - db) / 38.0 * (ya1 - ya0)))
        pl(pts)
    t("saw through the 4-pole ladder", (xa0 + xa1) / 2, ya1 + 1.3, TEXT)
    t("resonance up to self-oscillation", (xr0 + xr1) / 2, ya1 + 1.3, TEXT)
    # J1 pinout: one rotated label per pin column (odd, even), aligned with the pins
    x1, y1 = PP.j1_pin1()
    for k in range(8):
        x = x1 - 2.54 * k
        o, e = 2 * k + 1, 2 * k + 2
        text(board, L, f"{o} {BP_PINS[o]}  {e} {BP_PINS[e]}", x, y1 - 1.6, TEXT, rot=90, just="r", mirror=True)
    t("J1 pinout", 7.5, 37.0, TEXT)
    t("odd  even", 7.5, 38.1, TEXT)
    # orientation beside J1
    xo = 7.5
    for i, s in enumerate(("this edge", "into the", "backplane")):
        t(s, xo, 41.8 + 1.25 * i, TEXT)
    pl([(xo, 45.4), (xo, 48.9)], 0.2)
    pl([(xo - 0.7, 48.1), (xo, 48.9), (xo + 0.7, 48.1)], 0.2)
    for i, s in enumerate(("J1: 2x8 socket", "pin 1: square pad", "10 mm card pitch")):
        t(s, W - 7.5, 41.8 + 1.25 * i, TEXT)
