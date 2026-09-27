"""Silkscreen artwork for the TouchSynth PCB (called from gen_pcb.py after placement).

Front: a dashed frame with a title tab around every functional block, a keybed outline with hatched black keys,
and a bottom strip with the logo, a resonant sawtooth and the ladder-filter response family.
Back: logo, signal-flow diagram and a few facts (mirrored so it reads correctly from the back).
"""
import math
import pcbnew
import design as D
import pcb_place as PP

MM = pcbnew.FromMM
V = pcbnew.VECTOR2I_MM
W = 100.0

LINE = 0.15                     # silk line width (JLCPCB minimum ~0.15)


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
    t.SetTextSize(V(size, size)); t.SetTextThickness(MM(thick or size * 0.15))
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


# ------------------------------------------------------------------ obstacles (front silk must avoid them)
def obstacles(board):
    obst = []
    for fp in board.GetFootprints():
        if fp.GetReference().startswith("KEY"):
            continue                                       # silk on the (mask-covered) touch pads is fine
        b = fp.GetBoundingBox(False)
        obst.append((pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()),
                     pcbnew.ToMM(b.GetBottom())))
        for t in (fp.Reference(), fp.Value()):
            if t.IsVisible() and t.GetLayer() == pcbnew.F_SilkS:
                obst.append(bbox_mm(t))
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.F_SilkS and isinstance(d, pcbnew.PCB_TEXT):
            obst.append(bbox_mm(d))
    return obst


def cut(a, b, obst, m=0.2):
    """parts of the axis-parallel segment a-b that stay clear of the obstacle boxes"""
    horiz = a[1] == b[1]
    lo, hi = (min(a[0], b[0]), max(a[0], b[0])) if horiz else (min(a[1], b[1]), max(a[1], b[1]))
    c = a[1] if horiz else a[0]
    blocked = []
    for o in obst:
        if horiz and o[1] - m < c < o[3] + m:
            blocked.append((o[0] - m, o[2] + m))
        elif not horiz and o[0] - m < c < o[2] + m:
            blocked.append((o[1] - m, o[3] + m))
    free, pos = [], lo
    for s, e in sorted(blocked):
        if s > pos:
            free.append((pos, min(s, hi)))
        pos = max(pos, e)
        if pos >= hi:
            break
    if pos < hi:
        free.append((pos, hi))
    return [((s, c), (e, c)) if horiz else ((c, s), (c, e)) for s, e in free if e - s > 0.3]


def dashed(board, a, b, obst, on=1.0, off=0.6):
    for p, q in cut(a, b, obst):
        L = math.dist(p, q)
        ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
        s = 0.0
        while s < L - 0.2:
            e = min(s + on, L)
            seg(board, pcbnew.F_SilkS, (p[0] + ux * s, p[1] + uy * s), (p[0] + ux * e, p[1] + uy * e))
            s = e + off


# ------------------------------------------------------------------ reference designators
def place_refs(board):
    """move every silkscreen reference (ICs, transistors) to a free spot next to its part"""
    fps = [f for f in board.GetFootprints() if f.Reference().IsVisible()
           and f.Reference().GetLayer() == pcbnew.F_SilkS and not f.GetReference().startswith("KEY")]
    boxes = {}
    for f in board.GetFootprints():
        b = f.GetBoundingBox(False)
        boxes[f.GetReference()] = (pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()),
                                   pcbnew.ToMM(b.GetBottom()))
    obst = list(boxes.values()) + [PP.tab_rect(b) for b in PP.BLOCKS]
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
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        th = pcbnew.ToMM(t.GetTextSize().y)
        tw = len(t.GetText()) * th * 0.9
        cands = []
        for d in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
            for sx in (1, -1):
                cands += [(cx + sx * d, y0 - th / 2 - 0.25), (cx + sx * d, y1 + th / 2 + 0.25)]
            for sy in (1, -1):
                cands += [(x0 - tw / 2 - 0.3, cy + sy * d), (x1 + tw / 2 + 0.3, cy + sy * d)]
        for x, y in cands:
            r = (x - tw / 2, y - th / 2, x + tw / 2, y + th / 2)
            if r[0] > 1.2 and r[2] < W - 1.2 and not hits(r, obst, 0.15):
                t.SetPosition(V(x, y))
                obst.append(r)
                break
        else:
            t.SetLayer(pcbnew.F_Fab)                       # no room: reference on the fab drawing only
            print(f"art: reference of {f.GetReference()} moved to F.Fab (no free spot)")


# ------------------------------------------------------------------ block frames with title tabs
def merged_edges():
    """shared block edges, each drawn once: [((x, y), (x, y))]"""
    hs, vs = {}, {}
    for x0, y0, x1, y1 in PP.BLOCKS.values():
        hs.setdefault(y0, []).append((x0, x1)); hs.setdefault(y1, []).append((x0, x1))
        vs.setdefault(x0, []).append((y0, y1)); vs.setdefault(x1, []).append((y0, y1))
    def merge(iv):
        out = []
        for s, e in sorted(iv):
            if out and s <= out[-1][1] + 1e-6:
                out[-1] = (out[-1][0], max(out[-1][1], e))
            else:
                out.append((s, e))
        return out
    edges = [((s, y), (e, y)) for y, iv in hs.items() for s, e in merge(iv)]
    edges += [((x, s), (x, e)) for x, iv in vs.items() for s, e in merge(iv)]
    return edges


def block_frames(board):
    obst = obstacles(board)
    for a, b in merged_edges():
        dashed(board, a, b, obst)
    for blk, label in PP.LABELS.items():
        r = PP.tab_rect(blk)
        text(board, pcbnew.F_SilkS, label, r[0] + 0.15, (r[1] + r[3]) / 2, PP.TAB_H, 0.15, just="l")


# ------------------------------------------------------------------ keyboard
def keybed(board, key_boxes):
    """piano outline: keybed frame, white-key dividers, hatched black keys; key_boxes = touch pad boxes
    [(x0, y0, x1, y1, is_black)]. The black-key footprints draw their own frame (pad + 0.5 mm)."""
    L = pcbnew.F_SilkS
    whites = sorted(k for k in key_boxes if not k[4])
    blacks = [k for k in key_boxes if k[4]]
    half = (whites[1][0] - whites[0][2]) / 2            # half the gap between white pads
    x0, x1 = whites[0][0] - half, whites[-1][2] + half
    y0 = min(k[1] for k in blacks) - 0.5                 # flush with the black-key frames
    y1 = max(k[3] for k in whites) + half
    poly(board, L, [(x1, y0), (x1, y1), (x0, y1), (x0, y0)], 0.2)
    xs = [x0] + [v for k in sorted(blacks) for v in (k[0] - 0.75, k[2] + 0.75)] + [x1]     # gap at the frames
    for a, b in zip(xs[::2], xs[1::2]):
        poly(board, L, [(a, y0), (b, y0)], 0.2)
    for a, b in zip(whites, whites[1:]):
        xd = (a[2] + b[0]) / 2
        blk = [k for k in blacks if k[0] < xd < k[2]]
        poly(board, L, [(xd, y1 - 0.25), (xd, blk[0][3] + 0.75 if blk else y0 + 0.25)], 0.2)
    for kx0, ky0, kx1, ky1, _ in blacks:                 # 45 degree hatch inside the black keys
        kx0, ky0, kx1, ky1 = kx0 + 0.35, ky0 + 0.35, kx1 - 0.35, ky1 - 3.0     # key name below the hatch
        step = 0.9
        n = int((kx1 - kx0 + ky1 - ky0) / step)
        for i in range(1, n + 1):
            d = i * step                                   # line: (x - kx0) + (ky1 - y) = d
            pa = (kx0 + max(0.0, d - (ky1 - ky0)), ky1 - min(d, ky1 - ky0))
            pb = (kx0 + min(d, kx1 - kx0), ky1 - max(0.0, d - (kx1 - kx0)))
            if math.dist(pa, pb) > 0.3:
                seg(board, L, pa, pb, 0.2)


# ------------------------------------------------------------------ waveforms
def resonant_saw(n=900, periods=3.0, k=3.7, fc=0.045):
    """sawtooth through a 4-pole ladder (tanh stages), sampled over the last `periods` periods"""
    per = 300
    total = int(per * (periods + 4))
    g = 1 - math.exp(-2 * math.pi * fc)
    s = [0.0] * 4
    out = []
    for i in range(total):
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
    s = complex(0, w)
    return 20 * math.log10(abs(1 / ((1 + s) ** 4 + k)))


def bottom_strip(board, y_top, y_bot):
    L = pcbnew.F_SilkS
    yc = (y_top + y_bot) / 2
    # logo
    text(board, L, "TouchSynth", 50.0, yc - 0.9, 2.4, 0.4, italic=True)
    text(board, L, "analog mono synth  -  rev 0.1", 50.0, yc + 2.2, 0.8, 0.15)
    # left: sawtooth -> resonant ladder output
    xs0, xs1 = 8.0, 34.0
    sig = resonant_saw()
    amp = (y_bot - y_top) / 2 - 0.4
    pts = [(xs0 + (xs1 - xs0) * i / (len(sig) - 1), yc - amp * v) for i, v in enumerate(sig)]
    poly(board, L, pts[::3] + [pts[-1]], 0.15)
    # right: 4-pole ladder magnitude response for rising resonance, log frequency
    xr0, xr1 = 66.0, 92.0
    db_top, db_bot = 8.0, -30.0
    for k in (0.0, 1.5, 2.7, 3.4, 3.8):
        pts = []
        for i in range(161):
            w = 10 ** (-1.2 + 2.2 * i / 160)
            db = max(db_bot, min(db_top, ladder_db(w, k)))
            pts.append((xr0 + (xr1 - xr0) * i / 160, y_top + (db_top - db) / (db_top - db_bot) * (y_bot - y_top)))
        poly(board, L, pts)


# ------------------------------------------------------------------ back side
def back(board, y0):
    L = pcbnew.B_SilkS
    mx = lambda x: W - x                               # mirror: reads left-to-right from the back
    def t(s, x, y, size, **kw):
        return text(board, L, s, mx(x), y, size, mirror=True, **kw)
    def box(x0, yb0, x1, yb1, label, sub=None):
        poly(board, L, [(mx(x0), yb0), (mx(x1), yb0), (mx(x1), yb1), (mx(x0), yb1), (mx(x0), yb0)], 0.2)
        t(label, (x0 + x1) / 2, (yb0 + yb1) / 2 - (0.9 if sub else 0), 1.6, thick=0.25)
        if sub:
            t(sub, (x0 + x1) / 2, (yb0 + yb1) / 2 + 1.5, 0.9, thick=0.15)
    def arrow(a, b):
        poly(board, L, [(mx(a[0]), a[1]), (mx(b[0]), b[1])], 0.2)
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        for da in (2.6, -2.6):
            p = (b[0] + 1.2 * math.cos(ang + da), b[1] + 1.2 * math.sin(ang + da))
            poly(board, L, [(mx(b[0]), b[1]), (mx(p[0]), p[1])], 0.2)

    t("TouchSynth", 50.0, y0 + 4.0, 4.0, thick=0.6, italic=True)
    t("an MCU-controlled analog mono synth", 50.0, y0 + 8.0, 1.2, thick=0.18)
    # signal flow
    yb = y0 + 13.0
    bw, bh, gap = 16.0, 7.0, 6.0
    xs = [8.0 + i * (bw + gap) for i in range(4)]
    names = [("DCO", "reset integrator"), ("VCF", "4-pole ladder"), ("VCA", "BJT diff pair"), ("OUT", "line level")]
    for x, (n, s) in zip(xs, names):
        box(x, yb, x + bw, yb + bh, n, s)
    for x in xs[:3]:
        arrow((x + bw, yb + bh / 2), (x + bw + gap, yb + bh / 2))
    # resonance feedback loop over the VCF
    xv = xs[1]
    poly(board, L, [(mx(xv + bw - 3), yb), (mx(xv + bw - 3), yb - 2.2), (mx(xv + 3), yb - 2.2)], 0.2)
    arrow((xv + 3, yb - 2.2), (xv + 3, yb))
    t("resonance", xv + bw / 2, yb - 3.2, 0.9, thick=0.15)
    # MCU below, CVs up
    ym = yb + bh + 8.0
    box(xs[0], ym, xs[2] + bw, ym + bh, "CH32V003 / V002", "PWM CVs, touch sensing, LEDs, demo tunes")
    for x, lab in ((xs[0], "pitch"), (xs[1], "cutoff, res"), (xs[2], "level")):
        arrow((x + bw / 2, ym), (x + bw / 2, yb + bh))
        t(lab, x + bw / 2 + 0.8, ym - 3.9, 0.9, thick=0.15, just="l")
    poly(board, L, [(mx(xs[3] + bw / 2), yb + bh), (mx(xs[3] + bw / 2), ym + bh / 2)], 0.2)
    arrow((xs[3] + bw / 2, ym + bh / 2), (xs[2] + bw, ym + bh / 2))
    t("loopback", xs[3] + bw / 2 + 0.8, ym - 3.9, 0.9, thick=0.15, just="l")
    back_facts(board, ym + bh + 2.8)


FACTS = ["supply 9-12 V DC  |  16 touch keys  |  SWIO: WCH-LinkE / minichlink",
         "simulated in ngspice, laid out in KiCad 10, firmware on ch32fun",
         "rev 0.1  |  2026-09-27  |  design: cpldcpu & Claude Opus 5.5"]


def back_facts(board, y):
    for i, f in enumerate(FACTS):
        text(board, pcbnew.B_SilkS, f, W - 50.0, y + i * 1.8, 1.0, 0.15, mirror=True)
