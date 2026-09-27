"""Generate the TouchSynth PCB from design.py (run with KiCad's bundled Python: pcbnew).

  "C:/Users/.../KiCad/10.0/bin/python.exe" gen_pcb.py [--route]

Board 100 x 100 mm, 2 layers. Fixed placement for keys, LEDs, connectors, test points and mounting holes;
functional clusters (schematic groups) are packed into an analog region (left) and a digital region (right).
Footprints carry deterministic schematic paths, so 'Update PCB from Schematic' keeps working.
With --route the board is exported to Specctra DSN, routed by Freerouting, re-imported and the zones filled.
"""
import os, sys, math, subprocess, uuid as _uuid
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design as D
import sexp as S

OUT = os.path.join(HERE, "touchsynth")
PCB = os.path.join(OUT, "touchsynth.kicad_pcb")
FPDIR = S.FPDIR
PROJ_LIB = os.path.join(OUT, "TouchSynth.pretty")
NS = _uuid.UUID("7a1f3c2e-5b8d-4e6f-9a0b-1c2d3e4f5a6b")
MM = pcbnew.FromMM
W, H = 100.0, 100.0


def duid(*parts):
    return str(_uuid.uuid5(NS, "/".join(str(p) for p in parts)))


# ------------------------------------------------------------------ fixed geometry
KEYS = D.KEYS
WHITE = [k for k in KEYS[:13] if "#" not in k]
BLACK = [k for k in KEYS[:13] if "#" in k]
WX0, WPITCH, WY = 8.25, 10.5, 83.5            # white key centres
BY = 67.0                                     # black key row
FX, FYS = 93.5, (65.75, 76.225, 86.7)         # function pads SHIFT, -, +: frames flush with the keybed
LED_Y = 60.0


def key_name(p):
    return KEYS[int(p.pins["1"].split("_")[1]) - 1]


def key_xy(k):
    if k in WHITE:
        return WX0 + WPITCH * WHITE.index(k), WY
    if k in BLACK:
        left = KEYS[KEYS.index(k) - 1]            # the white key to the left
        return WX0 + WPITCH * WHITE.index(left) + WPITCH / 2, BY
    return FX, FYS[("SHIFT", "-", "+").index(k)]


ANALOG = (3.5, 10.5, 59.5, 50.5)
DIGITAL = (61.0, 10.5, 97.0, 50.5)
ANALOG_ORDER = [
    "Input, reverse protection, 5 V", "References: VREF 4.5 V, VBIAS 1.5 V, V25 2.5 V", "Ladder bias chain",
    "Transistor ladder (4 poles)", "Mixer", "Output instrumentation amplifier (G = 11)",
    "CV_CUT filter and exponential converter", "CV_AMP filter and V-to-I converter", "Integrator and reset",
    "CV_RES filter and V-to-I converter", "Resonance VCA and difference amplifier",
    "CV_VCA filter and V-to-I converter", "VCA core and offset trim", "Difference amplifier, line out",
    "Audio loopback to PD5",
]
DIGITAL_ORDER = [
    "MCU (CH32V003 / CH32V002, hand-soldered)", "MIDI in (DNP)", "Touch multiplexers",
    "Shift registers (LEDs + trim DAC)", "VCA trim DAC (8-bit R-2R)",
]
CONNECTORS = {"PWR 9-12V": (9.4, 5.0), "LINE OUT": (66.0, 5.0), "MIDI IN": (77.0, 5.0), "SWIO": (85.0, 5.0)}
SCOPE_GND = {"left": (20.0, 5.0), "right": (57.0, 5.0)}   # well clear of the headers
PIN_NAMES = {"VIN": "+", "GND": "-", "LINEOUT": "OUT", "+5V": "5V", "MIDI_4": "4", "MIDI_5": "5"}
# In2.Cu: "NET@region" -> polygon (0.5 mm gaps between the regions): VP under the analog area, +5V under the
# right column and the keys I/O row (L shape), GND under the keyboard
PLANES_IN2 = {
    "VP@analog": [(0.3, 0.3), (75.25, 0.3), (75.25, 44.75), (0.3, 44.75)],
    "+5V@digital": [(75.75, 0.3), (99.7, 0.3), (99.7, 54.0), (0.3, 54.0), (0.3, 45.25), (75.75, 45.25)],
    "GND@keys": [(0.3, 54.5), (99.7, 54.5), (99.7, 99.7), (0.3, 99.7)],
}


def in_poly(pts, x, y, margin=0.0):
    """point inside the polygon and at least `margin` away from its edges"""
    inside = False
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
        if margin:
            dx, dy = x1 - x0, y1 - y0
            t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy)))
            if math.hypot(x - x0 - t * dx, y - y0 - t * dy) < margin:
                return False
    return inside
HOLES = [(4.0, 4.0), (96.0, 4.0), (4.0, 96.0), (96.0, 96.0)]


# ------------------------------------------------------------------ board helpers
def kicad_net_names():
    """design net -> net name as KiCad's schematic netlist calls it (e.g. '/dco/DCO_INT' for local nets)"""
    path = os.path.join(OUT, "touchsynth.net")
    doc = S.parse(open(path, encoding="utf-8").read())
    pin_net = {(p.ref, pin): n for p in D.PARTS for pin, n in p.pins.items()}
    out = {}
    for n in S.find(S.find1(doc, "nets"), "net"):
        name = str(S.find1(n, "name")[1])
        for node in S.find(n, "node"):
            key = (str(S.find1(node, "ref")[1]), str(S.find1(node, "pin")[1]))
            if key in pin_net:
                out[pin_net[key]] = name
                break
    return out


def load_fp(fpid):
    lib, name = fpid.split(":")
    path = PROJ_LIB if lib == "TouchSynth" else os.path.join(FPDIR, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise RuntimeError(f"footprint {fpid} not found")
    return fp


def size_of(fp):
    bb = fp.GetBoundingBox(False)
    return pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())


def set_field(fp, name, value):
    try:
        fp.SetField(name, value)
    except Exception:
        f = pcbnew.PCB_FIELD(fp, fp.GetFieldCount(), name)
        f.SetText(value); f.SetVisible(False)
        fp.AddField(f)
    f = fp.GetField(name)
    if f is not None:
        f.SetVisible(False)
        f.SetLayer(pcbnew.F_Fab)


def units_and_sheets():
    """ref -> (sheet, lowest unit) for footprint paths"""
    res = {}
    for p in D.PARTS:
        sym = S.get_symbol(p.lib_id)
        pinmap = {num: u for u, num, *_ in S.pins(sym)}
        us = sorted({max(pinmap[k], 1) for k in p.pins if k in pinmap} | ({1} if S.units(sym) == 1 else set()))
        u = us[0]
        res[p.ref] = (p.unit_sheets.get(u, p.sheet), u)
    return res


def add_rect(board, layer, x0, y0, x1, y1, width=0.1):
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I_MM(*a)); s.SetEnd(pcbnew.VECTOR2I_MM(*b))
        s.SetLayer(layer); s.SetWidth(MM(width))
        board.Add(s)


def zone(board, layer, pts, net=None, rule_area=False, name=""):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    ol = z.Outline()
    ol.NewOutline()
    for x, y in pts:
        ol.Append(MM(x), MM(y))
    if rule_area:
        z.SetIsRuleArea(True)
        for m in ("SetDoNotAllowZoneFills", "SetDoNotAllowCopperPour"):
            if hasattr(z, m):
                getattr(z, m)(True)
        z.SetDoNotAllowTracks(False); z.SetDoNotAllowVias(False); z.SetDoNotAllowPads(False)
        if hasattr(z, "SetDoNotAllowFootprints"):
            z.SetDoNotAllowFootprints(False)
    else:
        z.SetNet(net)
        z.SetLocalClearance(MM(0.2))
        z.SetMinThickness(MM(0.2))
        z.SetThermalReliefGap(MM(0.25))
        z.SetThermalReliefSpokeWidth(MM(0.4))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    if name:
        z.SetZoneName(name)
    board.Add(z)
    return z


# ------------------------------------------------------------------ cluster packing
def cluster(items, target_w, gap=0.35):
    """items: [(fp, w, h)]. Row packing; returns [(fp, dx, dy)] (centre offsets), width, height."""
    out, x, y, rowh, wmax = [], 0.0, 0.0, 0.0, 0.0
    for fp, w, h in items:
        if x > 0 and x + w > target_w:
            x, y, rowh = 0.0, y + rowh + gap, 0.0
        out.append((fp, x + w / 2, y + h / 2))
        x += w + gap; rowh = max(rowh, h); wmax = max(wmax, x)
    return out, wmax, y + rowh


def pack_region(clusters, region, gap=1.0):
    """skyline packing of clusters (kept in order as far as possible): each cluster goes where its top edge
    ends up lowest (ties: leftmost). Returns {name: (x0, y0)} and the overflow in mm."""
    x0, y0, x1, y1 = region
    sky = [(x0, x1 - x0, y0)]                       # segments (x, width, y)
    pos, over = {}, 0.0
    for name, pl, w, h in clusters:
        w2, best = w + gap, None
        xs = sorted({s[0] for s in sky} | {x1 - w2})
        for x in xs:
            if x < x0 - 1e-6 or x + w2 > x1 + 1e-6:
                continue
            top = max(s[2] for s in sky if s[0] < x + w2 - 1e-6 and s[0] + s[1] > x + 1e-6)
            if best is None or top < best[1] - 1e-6 or (abs(top - best[1]) < 1e-6 and x < best[0]):
                best = (x, top)
        x, top = best
        pos[name] = (x, top)
        ny = top + h + gap
        over = max(over, ny - gap - y1)
        new = []
        for sx, sw, sy in sky:
            if sx + sw <= x + 1e-6 or sx >= x + w2 - 1e-6:
                new.append((sx, sw, sy)); continue
            if sx < x:
                new.append((sx, x - sx, sy))
            if sx + sw > x + w2:
                new.append((x + w2, sx + sw - x - w2, sy))
        new.append((x, w2, ny))
        sky = sorted(new)
    return pos, over


def order_by_connectivity(parts):
    """largest part first, then greedy by shared nets"""
    parts = sorted(parts, key=lambda p: -len(p.pins))
    if not parts:
        return parts
    done, rest = [parts[0]], parts[1:]
    while rest:
        nets = {n for p in done[-3:] for n in p.pins.values() if n not in ("GND", "VP", "+5V")}
        best = max(rest, key=lambda p: len(nets & set(p.pins.values())))
        done.append(best); rest.remove(best)
    return done


# ------------------------------------------------------------------ greedy placement
POWER_NETS = {"GND", "VP", "+5V"}


def tp_label_w(p):
    return 0.4 + len(p.value) * 0.8


def _geom(fp, rot):
    """bbox (relative to position) and pad offsets for a rotation"""
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(pcbnew.VECTOR2I_MM(0, 0))
    bb = fp.GetBoundingBox(False)
    box = (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))
    pads = [(pd.GetNumber(), pcbnew.ToMM(pd.GetPosition().x), pcbnew.ToMM(pd.GetPosition().y)) for pd in fp.Pads()]
    return box, pads


def greedy_place(board, fps, placed, step=0.5, clr=0.3):
    import pcb_place as PP
    rects = []
    padpos = {}                                        # net -> [(x, y)]
    def add_placed(p, fp):
        bb = fp.GetBoundingBox(False)
        r = (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))
        if p.lib_id == "Connector:TestPoint" and not (p.note or "").startswith("scope ground"):
            cy = pcbnew.ToMM(fp.GetPosition().y)                      # keep the label area free as well
            r = (r[0], min(r[1], cy - 0.55), r[2] + tp_label_w(p), max(r[3], cy + 0.55))
        rects.append(r)
        for pd in fp.Pads():
            n = p.pins.get(pd.GetNumber())
            if n:
                padpos.setdefault(n, []).append((pcbnew.ToMM(pd.GetPosition().x), pcbnew.ToMM(pd.GetPosition().y)))
    for ref in placed:
        add_placed(*fps[ref])
    for blk in PP.BLOCKS:                              # reserved title tabs
        t = PP.tab_rect(blk)
        for r in rects:
            if r[0] < t[2] and t[0] < r[2] and r[1] < t[3] and t[1] < r[3]:
                print(f"WARNING: a fixed part overlaps the {blk} title tab")
        rects.append(t)
    for h in [f for f in board.GetFootprints() if f.GetReference().startswith("H")]:
        bb = h.GetBoundingBox(False)
        rects.append((pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetRight()),
                      pcbnew.ToMM(bb.GetBottom())))
    todo = [fps[r][0] for r in fps if r not in placed]
    # decoupling caps: target = the supply pin of their IC
    dec_target, dec_block = {}, {}
    for p in todo:
        ic = PP.dec_ic(p)
        if ic:                                          # target: the IC pin on the cap's supply net
            icp, icfp = fps[ic]
            dec_block[p.ref] = PP.block_of(icp)
            supply = [n for n in p.pins.values() if n != "GND"][0]
            for pd in icfp.Pads():
                if icp.pins.get(pd.GetNumber()) == supply:
                    dec_target[p.ref] = (pcbnew.ToMM(pd.GetPosition().x), pcbnew.ToMM(pd.GetPosition().y))
    while todo:
        def links(p):
            return sum(1 for n in p.pins.values() if n not in POWER_NETS and n in padpos)
        p = max(todo, key=lambda q: (q.ref in dec_target, links(q), len(q.pins)))
        todo.remove(p)
        fp = fps[p.ref][1]
        blk = PP.block_of(p)
        if blk is None:
            tx, ty = dec_target[p.ref]
            b = PP.place_rect(dec_block[p.ref])
            region = (max(tx - 7, b[0]), max(ty - 7, b[1]), min(tx + 7, b[2]), min(ty + 7, b[3]))
        else:
            region = PP.place_rect(blk)
        rots = (0, 90) if len(p.pins) <= 3 else (0, 90, 180, 270)
        if p.lib_id == "Connector:TestPoint":
            rots = (0,)
        geoms = {r: _geom(fp, r) for r in rots}
        if p.lib_id == "Connector:TestPoint":             # reserve the net-name label right of the pad
            (bx0, by0, bx1, by1), pads = geoms[0]
            geoms[0] = ((bx0, min(by0, -0.55), bx1 + tp_label_w(p), max(by1, 0.55)), pads)
        sx0, sy0, sx1, sy1 = PP.side_rect(blk if blk else dec_block[p.ref])   # never across analog / digital
        sx0, sy0, sx1, sy1 = sx0 + PP.STREET, sy0 + PP.STREET, sx1 - PP.STREET, sy1 - PP.STREET
        regions = [region] + [(max(region[0] - g_, sx0), max(region[1] - g_, sy0), min(region[2] + g_, sx1),
                               min(region[3] + g_, sy1)) for g_ in (3.0, 8.0, 20.0)]   # fallback: spill over
        if p.lib_id == "Connector:TestPoint":
            regions.append((23.0, 2.2, 47.0, 7.8))         # last resort: the free strip on the top edge
        for region in regions:
            near = [r for r in rects if r[2] > region[0] - 8 and r[0] < region[2] + 8 and r[3] > region[1] - 8
                    and r[1] < region[3] + 8]
            best = None
            x0, y0, x1, y1 = region
            nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
            for rot, (box, pads) in geoms.items():
                for i in range(nx):
                    x = x0 + i * step
                    if x + box[0] < x0 - 0.01 or x + box[2] > x1 + 0.01:
                        continue
                    for j in range(ny):
                        y = y0 + j * step
                        if y + box[1] < y0 - 0.01 or y + box[3] > y1 + 0.01:
                            continue
                        bx0, by0, bx1, by1 = x + box[0] - clr, y + box[1] - clr, x + box[2] + clr, y + box[3] + clr
                        if any(bx0 < r[2] and r[0] < bx1 and by0 < r[3] and r[1] < by1 for r in near):
                            continue
                        cost = 0.0
                        if p.ref in dec_target:
                            tx, ty = dec_target[p.ref]
                            cost = min(math.hypot(x + px - tx, y + py - ty) for num, px, py in pads)
                        else:
                            for num, px, py in pads:
                                n = p.pins.get(num)
                                if n in POWER_NETS or n not in padpos:
                                    continue
                                cost += min(math.hypot(x + px - qx, y + py - qy) for qx, qy in padpos[n])
                        cost += 0.001 * (x + y)                    # tie-break: top-left
                        if best is None or cost < best[0]:
                            best = (cost, x, y, rot)
            if best is not None:
                break
        if best is None:
            print(f"WARNING: no space for {p.ref} ({p.value}) in block {blk}")
            continue
        _, x, y, rot = best
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(pcbnew.VECTOR2I_MM(x, y))
        add_placed(p, fp)
        near.append(rects[-1])


# ------------------------------------------------------------------ build
def build(route=False, passes=30):
    board = pcbnew.NewBoard(PCB)
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(4)
    board.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)   # planes: Freerouting keeps signals on F.Cu / B.Cu
    board.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_POWER)
    try:
        nc = ds.m_NetSettings.GetDefaultNetclass()
        nc.SetTrackWidth(MM(0.25)); nc.SetClearance(MM(0.2))
        nc.SetViaDiameter(MM(0.6)); nc.SetViaDrill(MM(0.3))
    except Exception as e:
        print("netclass settings:", e)
    add_rect(board, pcbnew.Edge_Cuts, 0, 0, W, H, 0.1)

    kname = kicad_net_names()
    nets = {}
    for n in sorted({n for p in D.PARTS for n in p.pins.values()}):
        ni = pcbnew.NETINFO_ITEM(board, kname.get(n, n))
        board.Add(ni)
        nets[n] = ni

    paths = units_and_sheets()
    fps = {}
    for p in D.PARTS:
        fp = load_fp(p.fp)
        lib_, name_ = p.fp.split(":")
        fp.SetFPID(pcbnew.LIB_ID(lib_, name_))
        fp.SetReference(p.ref)
        fp.SetValue(p.value)
        sheet, unit = paths[p.ref]
        fp.SetPath(pcbnew.KIID_PATH(f"/{duid('sheet', sheet)}/{duid('sym', p.ref, unit)}"))
        try:
            fp.SetSheetname(sheet); fp.SetSheetfile(f"{sheet}.kicad_sch")
        except Exception:
            pass
        set_field(fp, "LCSC", p.lcsc or "")
        set_field(fp, "Sim", p.sim or "")
        if p.note:
            set_field(fp, "Note", p.note)
        if p.dnp:
            fp.SetDNP(True)
        if not p.bom:
            fp.SetExcludedFromBOM(True); fp.SetExcludedFromPosFiles(True)
        for pad in fp.Pads():
            n = p.pins.get(pad.GetNumber())
            if n:
                pad.SetNet(nets[n])
        ref_ = fp.Reference()
        ref_.SetTextSize(pcbnew.VECTOR2I_MM(0.8, 0.8)); ref_.SetTextThickness(MM(0.15))
        big = p.lib_id.split(":")[0] in ("Amplifier_Operational", "4xxx", "74xx", "MCU_WCH_RiscV", "Isolator",
                                          "Regulator_Linear", "Connector_Generic", "Transistor_BJT",
                                          "Transistor_FET")
        if not big:
            ref_.SetLayer(pcbnew.F_Fab)           # passives: references on the fab layer only
        if p.lib_id == "Connector:TestPoint":
            ref_.SetLayer(pcbnew.F_Fab)
            v = fp.Value(); v.SetLayer(pcbnew.F_SilkS); v.SetVisible(True)
            v.SetTextSize(pcbnew.VECTOR2I_MM(0.8, 0.8)); v.SetTextThickness(MM(0.15))
            v.SetPosition(pcbnew.VECTOR2I_MM(0, 1.5))
        board.Add(fp)
        fps[p.ref] = (p, fp)

    def put(ref, x, y, rot=0.0):
        fp = fps[ref][1]
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(pcbnew.VECTOR2I_MM(x, y))

    placed = set()
    # keys, LEDs, LED resistor arrays
    for p, fp in fps.values():
        if p.ref.startswith("KEY"):
            k = KEYS[int(p.pins["1"].split("_")[1]) - 1]
            put(p.ref, *key_xy(k)); placed.add(p.ref)
            fp.SetLocked(True)
            for pad in fp.Pads():
                pad.SetLocalClearance(MM(1.0))
            fp.Reference().SetVisible(False)
            kt = pcbnew.PCB_TEXT(board)
            kt.SetText(k); kt.SetLayer(pcbnew.F_SilkS)
            kt.SetTextSize(pcbnew.VECTOR2I_MM(1.5, 1.5)); kt.SetTextThickness(MM(0.25))
            kx, ky = key_xy(k)
            kt.SetPosition(pcbnew.VECTOR2I_MM(kx, ky + (4.0 if k in WHITE else 3.6 if k in BLACK else 2.2)))
            board.Add(kt)
    leds = [p for p, fp in fps.values() if p.lib_id == "Device:LED"]
    for p in leds:
        i = int(p.pins["2"].split("LED_A")[1])
        k = KEYS[i]
        x, y = key_xy(k)
        if k in ("SHIFT", "-", "+"):
            put(p.ref, x - 5.6, y, 90)
        else:
            put(p.ref, x, LED_Y, 0)
        placed.add(p.ref)
    # series resistors: vertical, directly above each LED's anode, pad 2 (LED_A) towards the LED
    for p in leds:
        i = int(p.pins["2"].split("LED_A")[1])
        r = [q for q, _ in fps.values() if q.note == f"LED {i} series"][0]
        anode = [pd for pd in fps[p.ref][1].Pads() if pd.GetNumber() == "2"][0].GetPosition()
        ax, ay = pcbnew.ToMM(anode.x), pcbnew.ToMM(anode.y)
        vertical_led = KEYS[i] in ("SHIFT", "-", "+")
        put(r.ref, ax, ay - (2.21 if vertical_led else 2.6), 270)
        pads = {pd.GetNumber(): pcbnew.ToMM(pd.GetPosition().y) for pd in fps[r.ref][1].Pads()}
        if pads["2"] < pads["1"]:
            put(r.ref, ax, ay - (2.21 if vertical_led else 2.6), 90)
        placed.add(r.ref)
    # connectors, test points, holes
    for p, fp in fps.values():
        if p.value in CONNECTORS:
            x, y = CONNECTORS[p.value]
            put(p.ref, x, y, 90); placed.add(p.ref)
            fp.Reference().SetLayer(pcbnew.F_Fab)
            v = fp.Value(); v.SetLayer(pcbnew.F_SilkS); v.SetVisible(True)
            v.SetTextSize(pcbnew.VECTOR2I_MM(0.8, 0.8)); v.SetTextThickness(MM(0.15)); v.SetTextAngleDegrees(0)
            xs = [pad.GetPosition().x for pad in fp.Pads()]
            v.SetPosition(pcbnew.VECTOR2I((min(xs) + max(xs)) // 2, MM(y - 2.3)))
            for pad in fp.Pads():
                net = p.pins[pad.GetNumber()]
                pt = pcbnew.PCB_TEXT(board)
                pt.SetText(PIN_NAMES.get(net, net)); pt.SetLayer(pcbnew.F_SilkS)
                pt.SetTextSize(pcbnew.VECTOR2I_MM(0.8, 0.8)); pt.SetTextThickness(MM(0.15))
                pt.SetPosition(pcbnew.VECTOR2I(pad.GetPosition().x, MM(y + 2.0)))
                board.Add(pt)
    # scope ground pins on the top edge (the SMD test points are placed inside their blocks, see greedy_place)
    for p, fp in fps.values():
        if p.note and p.note.startswith("scope ground"):
            x, y = SCOPE_GND[p.note.split()[-1]]
            put(p.ref, x, y); placed.add(p.ref)
            fp.Value().SetPosition(pcbnew.VECTOR2I_MM(x, y - 2.3))
    for i, (x, y) in enumerate(HOLES):
        h = load_fp("MountingHole:MountingHole_3.2mm_M3")
        h.SetReference(f"H{i + 1}"); h.SetValue("M3")
        h.Reference().SetVisible(False)
        try:
            h.SetBoardOnly(True)
        except Exception:
            pass
        h.SetPosition(pcbnew.VECTOR2I_MM(x, y))
        board.Add(h)

    # ---- anchors + greedy connectivity placement per block (pcb_place.py)
    import pcb_place as PP
    for ref, (x, y, rot) in PP.anchors().items():
        put(ref, x, y, rot); placed.add(ref)
    greedy_place(board, fps, placed)
    for p, fp in fps.values():                        # test point labels: right of the pad
        if p.lib_id == "Connector:TestPoint" and not (p.note or "").startswith("scope ground"):
            v = fp.Value()
            v.SetKeepUpright(False); v.SetTextAngleDegrees(0)
            v.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
            pos = fp.GetPosition()
            v.SetPosition(pcbnew.VECTOR2I(pos.x + MM(0.95), pos.y))

    # vias inside the touch pads (touch lines run on B.Cu); no F.Cu tracks across the keyboard
    for p, fp in fps.values():
        if p.ref.startswith("KEY"):
            pad = list(fp.Pads())[0]
            ph = pcbnew.ToMM(pad.GetSize().y)
            x = pcbnew.ToMM(fp.GetPosition().x); y = pcbnew.ToMM(fp.GetPosition().y)
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I_MM(x, y - ph / 2 + 1.2))
            v.SetDrill(MM(0.3)); v.SetWidth(MM(0.6))
            v.SetNet(nets[p.pins["1"]])
            board.Add(v)
    # (a strip between the white keys and the function pads stays open for the function-key LEDs)
    for x0, x1 in ((0.5, 87.1), (88.7, 99.5)):
        kz = zone(board, pcbnew.F_Cu, [(x0, 61.0), (x1, 61.0), (x1, 99.5), (x0, 99.5)], rule_area=True)
        kz.SetDoNotAllowTracks(True)
        if hasattr(kz, "SetDoNotAllowZoneFills"):
            kz.SetDoNotAllowZoneFills(False)
    for x0, y0, x1, y1 in ((0, 0, W, 1.0), (0, H - 1.0, W, H), (0, 0, 1.0, H), (W - 1.0, 0, W, H)):
        for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
            ez = zone(board, layer, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], rule_area=True)
            ez.SetDoNotAllowTracks(True); ez.SetDoNotAllowVias(True)
            if hasattr(ez, "SetDoNotAllowZoneFills"):
                ez.SetDoNotAllowZoneFills(False)

    # zones: GND pour both layers; no pour under touch pads on the bottom layer
    edge = [(0.3, 0.3), (W - 0.3, 0.3), (W - 0.3, H - 0.3), (0.3, H - 0.3)]
    zone(board, pcbnew.F_Cu, edge, nets["GND"], name="GND_F")
    zone(board, pcbnew.B_Cu, edge, nets["GND"], name="GND_B")
    zone(board, pcbnew.In1_Cu, edge, nets["GND"], name="GND_IN1")          # solid ground plane
    for name, pts in PLANES_IN2.items():                                    # split power plane
        zone(board, pcbnew.In2_Cu, pts, nets[name.split("@")[0]], name=name.replace("@", "_IN2_"))
    # below each touch pad: no pour; no foreign tracks either (crosstalk) except in a 2.4 mm strip at the top of
    # the pad where the key's own via sits and its touch line arrives
    for p, fp in fps.values():
        if p.ref.startswith("KEY"):
            bb = fp.GetBoundingBox(False)
            x0, y0 = pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop())
            x1, y1 = pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom())
            ys = pcbnew.ToMM(list(fp.Pads())[0].GetBoundingBox().GetTop()) + 2.4
            zone(board, pcbnew.B_Cu, [(x0, y0), (x1, y0), (x1, ys), (x0, ys)], rule_area=True, name=KEY_AREA)
            kk = zone(board, pcbnew.B_Cu, [(x0, ys), (x1, ys), (x1, y1), (x0, y1)], rule_area=True, name=KEY_KEEPOUT)
            kk.SetDoNotAllowTracks(True); kk.SetDoNotAllowVias(True)
            for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):                # no plane under the pad (sensitivity)
                zone(board, layer, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], rule_area=True, name="KEY_CUTOUT")

    # silkscreen art: block frames, keybed, bottom strip, back side
    import pcb_art as A
    A.place_refs(board)
    A.block_frames(board)
    kb = []
    for p, fp in fps.values():
        if p.ref.startswith("KEY") and key_name(p) not in ("SHIFT", "-", "+"):
            pad = list(fp.Pads())[0]
            b = pad.GetBoundingBox()
            kb.append((pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()),
                       pcbnew.ToMM(b.GetBottom()), "#" in key_name(p)))
    A.keybed(board, kb)
    A.bottom_strip(board, 91.6, 98.6)
    A.back(board, 55.0)

    pcbnew.SaveBoard(PCB, board)
    print("saved", PCB)
    if route:
        do_route(board, passes)


KEY_AREA = "KEY_NOPOUR"
KEY_KEEPOUT = "KEY_KEEPOUT"


def key_areas(board):
    """the no-pour areas under the touch pads (B.Cu); older boards: unnamed B.Cu rule areas that allow tracks"""
    return [z for z in board.Zones() if z.GetIsRuleArea() and (z.GetZoneName() == KEY_AREA or (
        not z.GetZoneName() and z.GetLayer() == pcbnew.B_Cu and not z.GetDoNotAllowTracks()))]


def freeroute(board, passes):
    """one Freerouting run on the whole board (existing tracks are kept as the starting point). The key no-pour
    areas are removed meanwhile: the DSN export would turn them into full keep-outs and block the touch lines."""
    held = key_areas(board)
    for z in held:
        board.Remove(z)                                # detached, re-added unchanged after the import
    dsn = os.path.join(OUT, "touchsynth.dsn")
    ses = os.path.join(OUT, "touchsynth.ses")
    print("DSN export:", pcbnew.ExportSpecctraDSN(board, dsn))
    jar = os.path.join(os.path.dirname(HERE), "tools", "freerouting-1.9.0.jar")
    subprocess.run(["java", "-jar", jar, "-de", dsn, "-do", ses, "-mp", str(passes), "-mt", "0", "-dct", "0"], check=True)
    print("SES import:", pcbnew.ImportSpecctraSES(board, ses))
    for z in held:
        board.Add(z)


def stitch_planes(board):
    stitch_gnd(board, "GND")
    for name, pts in PLANES_IN2.items():
        net = name.split("@")[0]
        if net != "GND":
            stitch_gnd(board, net, pts)


def stitch_gnd(board, netname="GND", region=None, clr=0.22, via_d=0.6, drill=0.3, tw=0.3):
    """give every SMD pad of `netname` (inside `region`, if given) a short track to its own via into the plane
    (skips pads that already have a via of the net within 1.2 mm or where no candidate spot keeps the
    clearance). Runs before routing; the vias and tracks are locked so Freerouting keeps them."""
    gnd = board.FindNet(netname)
    SC, SS = pcbnew.SHAPE_CIRCLE, pcbnew.SHAPE_SEGMENT
    areas = [z for z in board.Zones() if z.GetIsRuleArea()]
    items = []                                              # (bbox mm, item) of other-net copper
    def bb(it):
        b = it.GetBoundingBox()
        return (pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()), pcbnew.ToMM(b.GetBottom()))
    for it in list(board.GetPads()) + list(board.GetTracks()):
        if it.GetNetCode() != gnd.GetNetCode():
            items.append((bb(it), it))
    gvias = [(pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y)) for t in board.GetTracks()
             if t.GetClass() == "PCB_VIA" and t.GetNetCode() == gnd.GetNetCode()]
    for fp in board.GetFootprints():
        if fp.GetReference().startswith(("KEY", "H")):
            continue
        for pad in fp.Pads():
            if pad.GetNetCode() != gnd.GetNetCode() or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            px, py = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
            if py > 60.0:                                   # function-key LEDs: keyboard area, F.Cu pour
                continue
            if region and not in_poly(region, px, py, 0.8):
                continue
            if any(math.hypot(px - vx, py - vy) < 1.2 for vx, vy in gvias):
                continue
            half = max(pcbnew.ToMM(pad.GetSize().x), pcbnew.ToMM(pad.GetSize().y)) / 2
            done = False
            for d in (half + 0.45, half + 0.7, half + 1.0, half + 1.4, half + 1.9):
                for k in range(16):
                    a = 2 * math.pi * k / 16
                    cx, cy = px + d * math.cos(a), py + d * math.sin(a)
                    if not (2.0 < cx < W - 2.0 and 2.0 < cy < H - 2.0):
                        continue
                    if region and not in_poly(region, cx, cy, 0.8):
                        continue
                    if any(z.Outline().Contains(pcbnew.VECTOR2I_MM(cx, cy)) for z in areas):
                        continue
                    via_s = SC(pcbnew.VECTOR2I_MM(cx, cy), MM(via_d / 2))
                    trk_s = SS(pcbnew.VECTOR2I_MM(px, py), pcbnew.VECTOR2I_MM(cx, cy), MM(tw))
                    box = (min(px, cx) - 1.5, min(py, cy) - 1.5, max(px, cx) + 1.5, max(py, cy) + 1.5)
                    bad = False
                    for (x0, y0, x1, y1), it in items:
                        if x1 < box[0] or x0 > box[2] or y1 < box[1] or y0 > box[3]:
                            continue
                        for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                            if not it.IsOnLayer(layer):
                                continue
                            sh = it.GetEffectiveShape(layer)
                            if sh.Collide(via_s, MM(clr)) or (layer == pcbnew.F_Cu and sh.Collide(trk_s, MM(clr))):
                                bad = True
                                break
                        if bad:
                            break
                    if bad:
                        continue
                    v = pcbnew.PCB_VIA(board)
                    v.SetPosition(pcbnew.VECTOR2I_MM(cx, cy)); v.SetDrill(MM(drill)); v.SetWidth(MM(via_d))
                    v.SetNet(gnd); v.SetLocked(True); board.Add(v)
                    t = pcbnew.PCB_TRACK(board)
                    t.SetStart(pcbnew.VECTOR2I_MM(px, py)); t.SetEnd(pcbnew.VECTOR2I_MM(cx, cy))
                    t.SetWidth(MM(tw)); t.SetLayer(pcbnew.F_Cu); t.SetNet(gnd); t.SetLocked(True); board.Add(t)
                    items.append(((cx - 0.3, cy - 0.3, cx + 0.3, cy + 0.3), v))   # same net, but keeps later vias apart
                    gvias.append((cx, cy))
                    done = True
                    break
                if done:
                    break
            if not done:
                print(f"stitch: no via spot for {fp.GetReference()} pad {pad.GetNumber()}")
    print(f"stitch vias {netname}:", len(gvias))


def silk_boxes(board):
    """bounding boxes (mm) of the board-level silkscreen art and text on both sides (vias would punch holes)"""
    out = []
    for d in board.GetDrawings():
        if d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            b = d.GetBoundingBox()
            out.append((pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()),
                        pcbnew.ToMM(b.GetBottom())))
    return out


def stitch_grid(board, pitch=2.5, via_d=0.6, drill=0.3):
    """GND vias on a grid wherever both pours are filled around the spot: ties pour islands of the two layers
    together (call after a zone fill)."""
    gnd = board.FindNet("GND")
    fills = {}
    for z in board.Zones():
        if not z.GetIsRuleArea() and z.GetNetCode() == gnd.GetNetCode():
            fills[z.GetLayer()] = z.GetFilledPolysList(z.GetLayer())
    novia = [z for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    vias = [(pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y)) for t in board.GetTracks()
            if t.GetClass() == "PCB_VIA"]
    silk = silk_boxes(board)
    n = 0
    r = via_d / 2 + 0.1
    ring = [(r * math.cos(k * math.pi / 4), r * math.sin(k * math.pi / 4)) for k in range(8)] + [(0, 0)]
    y = 2.0
    while y < H - 2.0:
        x = 2.0
        while x < W - 2.0:
            ok = all(fills[L].Contains(pcbnew.VECTOR2I_MM(x + dx, y + dy)) for L in (pcbnew.F_Cu, pcbnew.B_Cu)
                     for dx, dy in ring)
            ok = ok and not any(z.Outline().Contains(pcbnew.VECTOR2I_MM(x, y)) for z in novia)
            ok = ok and all(math.hypot(x - vx, y - vy) > 1.2 for vx, vy in vias)
            ok = ok and all(math.hypot(x - hx, y - hy) > 3.3 for hx, hy in HOLES)
            ok = ok and not any(b[0] - r < x < b[2] + r and b[1] - r < y < b[3] + r for b in silk)
            if ok:
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I_MM(x, y)); v.SetDrill(MM(drill)); v.SetWidth(MM(via_d))
                v.SetNet(gnd); board.Add(v)
                vias.append((x, y)); n += 1
            x += pitch
        y += pitch
    print("grid stitch vias:", n)


def fill_and_save(board):
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    pcbnew.SaveBoard(PCB, board)


def do_route(board, passes):
    stitch_planes(board)
    import pcb_maze                                # plane-net pads outside their plane region: route them first
    pcb_maze.route_leftovers(board, only=[n.split("@")[0] for n in PLANES_IN2 if not n.startswith("GND")],
                             lock=True)
    freeroute(board, passes)                       # full route
    freeroute(board, 20)                           # second run from the result: picks up what is still open
    post_route(board)
    print("routed and saved")


def post_route(board):
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    stitch_grid(board)
    import pcb_gnd
    pcb_gnd.refill(board)
    pcb_gnd.link_islands(board, freeroute, passes=30)
    pcb_gnd.bridge_islands(board)
    import pcb_maze
    pcb_maze.route_leftovers(board)
    fill_and_save(board)


def finish():
    """one more incremental Freerouting run on the existing routed board"""
    board = pcbnew.LoadBoard(PCB)
    freeroute(board, 20)
    post_route(board)
    print("finished and saved")


def open_nets(board, skip=("GND",)):
    import pcb_gnd
    out = []
    for name in sorted({p.GetNetname() for p in board.GetPads() if p.GetNetCode() > 0}):
        if name not in skip and len(pcb_gnd.net_components(board, name)) > 1:
            out.append(name)
    return out


def ripup(board, nets, margin=1.2):
    """delete the unlocked signal copper near the straight line of every open connection of `nets`"""
    import pcb_gnd
    planes = {"GND"} | {n.split("@")[0] for n in PLANES_IN2}
    corridors = []
    for name in nets:
        comps = pcb_gnd.net_components(board, name)
        src = comps[-1]["items"]
        rest = [it for c in comps[:-1] for it in c["items"]]
        if not src or not rest:
            continue
        a, b = min(((p, q) for p in src for q in rest),
                   key=lambda pq: (pq[0].GetPosition() - pq[1].GetPosition()).EuclideanNorm())
        corridors.append(pcbnew.SHAPE_SEGMENT(a.GetPosition(), b.GetPosition(), MM(2 * margin)))
    gone = 0
    for t in list(board.GetTracks()):
        if t.IsLocked() or t.GetNetname() in planes or t.GetNetname() in nets:
            continue
        L = t.GetLayer() if t.GetClass() != "PCB_VIA" else pcbnew.F_Cu
        sh = t.GetEffectiveShape(L)
        if any(sh.Collide(c, 0) for c in corridors):
            board.Delete(t)
            gone += 1
    print(f"rip-up: {gone} track pieces removed around {len(corridors)} open connections")


def unsilk_vias(board):
    """delete free-standing GND vias (grid vias) that sit under silkscreen art or text"""
    silk = silk_boxes(board)
    ends = set()
    for t in board.GetTracks():
        if t.GetClass() != "PCB_VIA":
            ends.add((t.GetStart().x, t.GetStart().y)); ends.add((t.GetEnd().x, t.GetEnd().y))
    n = 0
    for v in list(board.GetTracks()):
        if v.GetClass() != "PCB_VIA" or v.IsLocked() or v.GetNetname() != "GND":
            continue
        p = v.GetPosition()
        if (p.x, p.y) in ends:
            continue
        x, y = pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)
        if any(b[0] - 0.45 < x < b[2] + 0.45 and b[1] - 0.45 < y < b[3] + 0.45 for b in silk):
            board.Delete(v); n += 1
    print(f"removed {n} grid vias under silkscreen")


def repair(rounds=3):
    import pcb_gnd
    board = pcbnew.LoadBoard(PCB)
    unsilk_vias(board)
    pcb_gnd.refill(board)
    for r in range(rounds):
        nets = open_nets(board)
        print(f"repair round {r}: open nets {nets}")
        if not nets:
            break
        ripup(board, nets)
        freeroute(board, 30)
        post_route(board)
        board = pcbnew.LoadBoard(PCB)
    print("repair done, open nets:", open_nets(board))


if __name__ == "__main__":
    if "--repair" in sys.argv:
        repair()
    elif "--finish" in sys.argv:
        finish()
    else:
        build(route="--route" in sys.argv)
