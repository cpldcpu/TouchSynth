"""Schematic drawing layer: place symbols, draw wires, then auto-complete connectivity with labels.

Coordinates are in mm (use U = 2.54 for grid steps). After a sheet is drawn, `complete()` computes the
geometric connectivity (KiCad rules: pins, wire ends and labels that coincide connect; a wire end or pin lying on
a wire segment connects to it; crossings don't), compares it with design.py, adds net labels where a design net
is still split (global labels for nets shared between sheets), adds junctions, and raises on any short.
"""
import math
import sexp as S
import design as D

U = 2.54
GRID = 1.27
STUB = 2.54
CHAR_W = 1.05
POWER = {"GND": "power:GND", "+5V": "power:+5V"}
OUTWARD = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}
PARTS = {p.ref: p for p in D.PARTS}


def snap(v):
    return round(round(v / GRID) * GRID, 4)


def _rot(x, y, r):
    a = math.radians(r)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


class Placed:
    def __init__(self, part, unit, x, y, rot, mirror):
        self.part, self.unit, self.x, self.y, self.rot, self.mirror = part, unit, x, y, rot, mirror
        sym = S.get_symbol(part.lib_id)
        self.pins = {}
        for u, num, nm, px, py, ang, ln, et, hid in S.pins(sym):
            if u not in (0, unit):
                continue
            if mirror == "y":
                px, ang = -px, (180 - ang) % 360
            elif mirror == "x":
                py, ang = -py, (-ang) % 360
            rx, ry = _rot(px, py, rot)
            a = int(round((ang + rot) % 360))
            self.pins[num] = (snap(x + rx), snap(y - ry), OUTWARD[a])
        x0, y0, x1, y1 = S.bbox(sym, unit)
        pts = []
        for bx, by in ((x0, y0), (x0, y1), (x1, y0), (x1, y1)):
            if mirror == "y":
                bx = -bx
            elif mirror == "x":
                by = -by
            rx, ry = _rot(bx, by, rot)
            pts.append((x + rx, y - ry))
        self.box = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


class Sheet:
    def __init__(self, name):
        self.name = name
        self.placed = []            # Placed
        self.wires = []             # ((x1,y1),(x2,y2))
        self.labels = []            # (net, (x,y), dir, kind)  kind: local/global
        self.powers = []            # (net, (x,y), dir)
        self.texts = []             # (text, x, y, size, bold)
        self.lines = []             # decorative (x1,y1,x2,y2)
        self.fields = {}            # (ref, unit) -> ('right'|'left'|'above'|'below')
        self.ncs = []
        self.flags = []             # (net, (x, y)) PWR_FLAG symbols (pin at point, body above)

    # ---------------------------------------------------------------- placement
    def place(self, ref, x, y, rot=0, unit=1, mirror=None, fields=None):
        p = PARTS[ref]
        pl = Placed(p, unit, snap(x), snap(y), rot, mirror)
        self.placed.append(pl)
        if fields:
            self.fields[(ref, unit)] = fields
        return pl

    def P(self, ref, pin):
        for pl in self.placed:
            if pl.part.ref == ref and str(pin) in pl.pins:
                return pl.pins[str(pin)][:2]
        raise KeyError(f"{ref}.{pin} not placed on sheet {self.name}")

    # ---------------------------------------------------------------- drawing
    def w(self, *pts):
        pts = [self._pt(p) for p in pts]
        for a, b in zip(pts, pts[1:]):
            if a != b:
                assert a[0] == b[0] or a[1] == b[1], f"non-orthogonal wire {a}-{b} on {self.name}"
                self.wires.append((a, b))

    def hv(self, a, b):
        """wire a -> b, horizontal first"""
        a, b = self._pt(a), self._pt(b)
        self.w(a, (b[0], a[1]), b)

    def vh(self, a, b):
        a, b = self._pt(a), self._pt(b)
        self.w(a, (a[0], b[1]), b)

    def _pt(self, p):
        if isinstance(p, tuple) and len(p) == 2 and isinstance(p[0], str):
            return self.P(*p)
        return (snap(p[0]), snap(p[1]))

    def pwr(self, p, net, d=None):
        p = self._pt(p)
        d = d or ((0, 1) if net == "GND" else (0, -1))
        self.powers.append((net, p, d))

    def gnd(self, p, stub=0.0):
        p = self._pt(p)
        if stub:
            q = (p[0], snap(p[1] + stub)); self.w(p, q); p = q
        self.pwr(p, "GND", (0, 1))

    def v5(self, p, stub=0.0):
        p = self._pt(p)
        if stub:
            q = (p[0], snap(p[1] - stub)); self.w(p, q); p = q
        self.pwr(p, "+5V", (0, -1))

    def lbl(self, p, net, d=(1, 0), stub=0.0):
        p = self._pt(p)
        if stub:
            q = (snap(p[0] + d[0] * stub), snap(p[1] + d[1] * stub)); self.w(p, q); p = q
        self.labels.append((net, p, d, None))

    def flag(self, p, net):
        """PWR_FLAG with its pin at p (drawn above); p must be on the net."""
        self.flags.append((net, self._pt(p)))

    def text(self, s, x, y, size=2.0, bold=True):
        self.texts.append((s, x, y, size, bold))

    def heading(self, s, x, y, x2):
        self.text(s, x, y, 2.0, True)
        self.lines.append((x, y + 1.2, x2, y + 1.2))

    # ---------------------------------------------------------------- connectivity
    def _nodes(self):
        """points: pins, wire ends, labels, powers; returns union-find over point keys plus pin map."""
        parent = {}

        def f(a):
            parent.setdefault(a, a)
            while parent[a] != a:
                parent[a] = parent[parent[a]]; a = parent[a]
            return a

        def un(a, b):
            parent[f(a)] = f(b)

        pts = set()
        pinpts = {}
        for pl in self.placed:
            for num, (x, y, d) in pl.pins.items():
                pinpts.setdefault((x, y), []).append((pl.part.ref, num))
                pts.add((x, y))
        for a, b in self.wires:
            pts.add(a); pts.add(b); un(a, b)
        for net, p, d, k in self.labels:
            pts.add(p)
        for net, p, d in self.powers:
            pts.add(p)
        for p in pts:
            f(p)
        # points lying on wire segments
        for a, b in self.wires:
            for p in pts:
                if p in (a, b):
                    continue
                if (a[0] == b[0] == p[0] and min(a[1], b[1]) < p[1] < max(a[1], b[1])) or \
                   (a[1] == b[1] == p[1] and min(a[0], b[0]) < p[0] < max(a[0], b[0])):
                    un(p, a)
        # same-named labels / powers on this sheet
        byname = {}
        for net, p, d, k in self.labels:
            byname.setdefault(net, []).append(p)
        for net, p, d in self.powers:
            byname.setdefault("PWR:" + net, []).append(p)
        for ps in byname.values():
            for p in ps[1:]:
                un(p, ps[0])
        return f, pinpts

    def complete(self, global_nets):
        """Add labels for split nets, NC markers, junctions; raise on shorts."""
        f, pinpts = self._nodes()
        # pin -> net (design)
        pin_net = {}
        for pl in self.placed:
            for num in pl.pins:
                pin_net[(pl.part.ref, num, pl.unit)] = pl.part.pins.get(num)
        groups = {}
        for (x, y), lst in pinpts.items():
            for ref, num in lst:
                net = PARTS[ref].pins.get(num)
                groups.setdefault(f((x, y)), set()).add(net)
        for root, nets in groups.items():
            real = {n for n in nets if n is not None}
            if len(real) > 1:
                raise RuntimeError(f"short on sheet {self.name}: {sorted(real)}")
        # label presence per root
        has = {}
        for net, p, d, k in self.labels:
            has.setdefault(f(p), set()).add(net)
        for net, p, d in self.powers:
            has.setdefault(f(p), set()).add(net)
        wired = set()
        for a, b in self.wires:
            wired.add(a); wired.add(b)
        # every design net present on this sheet: all its groups here must be joined or labelled
        net_groups = {}
        for pl in self.placed:
            for num, (x, y, d) in pl.pins.items():
                net = pl.part.pins.get(num)
                if net is None or net.startswith("NC_"):
                    if (x, y) not in wired:
                        self.ncs.append((x, y))
                    continue
                net_groups.setdefault(net, {}).setdefault(f((x, y)), []).append((pl, num, x, y, d))
        added = 0
        for net, gs in net_groups.items():
            need = len(gs) > 1 or net in global_nets or net in POWER
            if not need:
                continue
            for root, members in gs.items():
                if net in has.get(root, set()):
                    continue
                # attach to a pin without a wire if possible, else to the first pin
                free = [m for m in members if (m[2], m[3]) not in wired] or members
                pl, num, x, y, d = free[0]
                q = (snap(x + d[0] * STUB), snap(y + d[1] * STUB))
                if (x, y) not in wired or q != (x, y):
                    self.wires.append(((x, y), q))
                if net in POWER:
                    self.powers.append((net, q, d))
                else:
                    self.labels.append((net, q, d, None))
                added += 1
        return added

    def split_wires(self):
        """Split wires at every pin tip, label, power/flag point or wire end lying inside them (KiCad only
        connects at wire end points)."""
        pts = set()
        for pl in self.placed:
            for num, (x, y, d) in pl.pins.items():
                pts.add((x, y))
        for a, b in self.wires:
            pts.add(a); pts.add(b)
        for net, p, d, k in self.labels:
            pts.add(p)
        for net, p, d in self.powers:
            pts.add(p)
        for net, p in self.flags:
            pts.add(p)
        out = []
        for a, b in self.wires:
            inner = [p for p in pts if p not in (a, b) and (
                (a[0] == b[0] == p[0] and min(a[1], b[1]) < p[1] < max(a[1], b[1])) or
                (a[1] == b[1] == p[1] and min(a[0], b[0]) < p[0] < max(a[0], b[0])))]
            seq = sorted([a, b] + inner, key=lambda p: (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2)
            out += [(p, q) for p, q in zip(seq, seq[1:]) if p != q]
        self.wires = out

    def junctions(self):
        pts = {}
        for a, b in self.wires:
            for p in (a, b):
                pts[p] = pts.get(p, 0) + 1
        for pl in self.placed:
            for num, (x, y, d) in pl.pins.items():
                if (x, y) in pts:
                    pts[(x, y)] += 1
        out = [p for p, n in pts.items() if n >= 3]
        for a, b in self.wires:
            for p in list(pts):
                if p in (a, b):
                    continue
                if (a[0] == b[0] == p[0] and min(a[1], b[1]) < p[1] < max(a[1], b[1])) or \
                   (a[1] == b[1] == p[1] and min(a[0], b[0]) < p[0] < max(a[0], b[0])):
                    out.append(p)
        return sorted(set(out))
