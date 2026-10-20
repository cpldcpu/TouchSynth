"""Generate the backplane PCB from backplane.py (run with KiCad's bundled Python: pcbnew).

  <KiCad 10>/bin/python.exe gen_pcb_bp.py [--route]   place (and route)
  <KiCad 10>/bin/python.exe gen_pcb_bp.py --repair    rip up around open connections and re-route
  <KiCad 10>/bin/python.exe gen_pcb_bp.py --finish    one more routing pass on the saved board
  <KiCad 10>/bin/python.exe gen_pcb_bp.py --art       redo the silkscreen (pcb_art_bp.py) and the DNP / BOM flags
                                                      on the routed board

Board 100 x 100 mm, 4 layers (pcb_place_bp.LAYERS; docs/backplane.md 6 and 7): all parts on F.Cu, signals on F.Cu
and B.Cu, In1 solid GND, In2 +3V3 under the controller strip and GND under the slot area (the summing band on B.Cu
sits against it); GND pours on the outer layers. LAYERS = 2 builds the 2-layer variant (outer GND pours only). Placement: pcb_place_bp.py (anchors for the
structured parts, greedy blocks for the rest). Before Freerouting the +5 V trunk and rail, the voice bus in the
socket field, the per-slot audio fan-out and the summing band (B.Cu) are drawn and locked; every GND SMD pad gets
its via to the bottom pour. GND is its own net class, which Freerouting skips (-inc): the pours, the stitch vias
and the island bridging (pcb_gnd.py) connect it. The voice card's routing helpers come from gen_pcb.py.
"""
import os, sys, math, subprocess
os.environ["BOARD"] = "backplane"
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board as B
import gen_pcb as G
import pcb_place_bp as PB
import pcb_art_bp as AB

D = B.D
PARTS = {p.ref: p for p in D.PARTS}
MM = pcbnew.FromMM
V = pcbnew.VECTOR2I_MM
PCB = G.PCB if PB.LAYERS == 4 else G.PCB.replace(".kicad_pcb", "_2l.kicad_pcb")    # BP_LAYERS=2: the check variant
G.PCB = PCB
G.PP, G.W, G.H = PB, PB.W, PB.H
G.PLANES_IN2 = PB.PLANES_IN2 if PB.LAYERS == 4 else {}
G.PLANE_NETS = ("GND", "+3V3") if PB.LAYERS == 4 else ("GND",)
G.POWER_NETS = {"GND", "+5V", "+5V_IN", "+3V3", "VA_MIX", "VDDA", "VBUS_C", "VBUS_HOST", "+5V_EXT", "+5V_SEL"}
G.TRACK, G.CLEAR = 0.2, 0.2

TRACK, CLEAR = 0.2, 0.2                          # JLCPCB 2-layer standard (backplane.md 7.1)
VIA_D, VIA_DRILL = 0.6, 0.3
SUPPLY = {"+5V": 0.6, "+5V_IN": 0.6, "+5V_SEL": 0.6, "+5V_EXT": 0.6, "VBUS_C": 0.5, "VBUS_HOST": 0.5,
          "+3V3": 0.4, "VA_MIX": 0.3, "VDDA": 0.3}
RAIL_W, TRUNK_W = 0.4, 1.0
GND_CLASS = "GNDPOUR"


def design_rules(board):
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(PB.LAYERS)
    if PB.LAYERS == 4:                                # planes: Freerouting keeps signals on F.Cu / B.Cu
        board.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)
        board.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_POWER)
    ds.SetBoardThickness(MM(1.6))
    ds.m_CopperEdgeClearance = MM(0.3)
    ds.m_TrackMinWidth = MM(TRACK)
    ds.m_MinClearance = MM(CLEAR)
    ds.m_ViasMinSize = MM(0.5)
    ds.m_MinThroughDrill = MM(0.3)
    ds.m_ViasMinAnnularWidth = MM(0.13)
    ds.m_HoleToHoleMin = MM(0.25)
    ds.m_HoleClearance = MM(0.18)                  # the USB-C footprint's pads sit 0.19 mm from its NPTH pegs
    ds.m_MinSilkTextHeight = MM(0.8)
    ds.m_MinSilkTextThickness = MM(0.15)
    ds.m_TentViasFront = ds.m_TentViasBack = True
    ds.m_MinResolvedSpokes = 1
    ns = ds.m_NetSettings
    nc = ns.GetDefaultNetclass()
    nc.SetTrackWidth(MM(TRACK)); nc.SetClearance(MM(CLEAR))
    nc.SetViaDiameter(MM(VIA_D)); nc.SetViaDrill(MM(VIA_DRILL))
    for w in sorted(set(SUPPLY.values())):
        c = pcbnew.NETCLASS(f"Supply{int(w * 100):03d}")
        c.SetTrackWidth(MM(w)); c.SetClearance(MM(CLEAR))
        c.SetViaDiameter(MM(0.8 if w >= 0.5 else VIA_D)); c.SetViaDrill(MM(0.4 if w >= 0.5 else VIA_DRILL))
        ns.SetNetclass(c.GetName(), c)
    for n, w in SUPPLY.items():
        ns.SetNetclassPatternAssignment(n, f"Supply{int(w * 100):03d}")
    g = pcbnew.NETCLASS(GND_CLASS)
    g.SetTrackWidth(MM(0.4)); g.SetClearance(MM(CLEAR)); g.SetViaDiameter(MM(VIA_D)); g.SetViaDrill(MM(VIA_DRILL))
    ns.SetNetclass(GND_CLASS, g)
    ns.SetNetclassPatternAssignment("GND", GND_CLASS)


# ------------------------------------------------------------------ copper helpers
def track(board, net, a, b, w=TRACK, layer=pcbnew.F_Cu, lock=True):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(*a)); t.SetEnd(V(*b)); t.SetWidth(MM(w)); t.SetLayer(layer); t.SetNet(net); t.SetLocked(lock)
    board.Add(t)
    return t


def path(board, net, pts, w=TRACK, layer=pcbnew.F_Cu):
    for a, b in zip(pts, pts[1:]):
        track(board, net, a, b, w, layer)


def via(board, net, p, d=VIA_D, drill=VIA_DRILL):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(*p)); v.SetDrill(MM(drill)); v.SetWidth(MM(d)); v.SetNet(net); v.SetLocked(True)
    board.Add(v)
    return v


def pad_xy(fp, num):
    pd = [p for p in fp.Pads() if p.GetNumber() == num][0]
    return pcbnew.ToMM(pd.GetPosition().x), pcbnew.ToMM(pd.GetPosition().y)


def net_of(board, name):
    kname = G.kicad_net_names()
    return board.FindNet(kname.get(name, name))


# ------------------------------------------------------------------ pre-routes
def pre_routes(board):
    F = {f.GetReference(): f for f in board.GetFootprints()}
    by_note = {p.note: p.ref for p in D.PARTS if p.note}
    n5, gnd = net_of(board, "+5V"), net_of(board, "GND")
    # +5 V: trunk from the bypass resistor down the east margin, rail west to the mixer, stubs per slot
    bx, by = pad_xy(F[by_note["R_BYP: soft-start bypass, fitted (remove when Q1 is fitted)"]], "2")
    path(board, n5, [(bx, by), (PB.TRUNK_X, by + PB.TRUNK_X - bx), (PB.TRUNK_X, PB.RAIL_Y - 1.0),
                     (PB.TRUNK_X - 1.0, PB.RAIL_Y)], TRUNK_W)
    west = pad_xy(F[[p.ref for p in D.PARTS if p.sim == "RSUP0"][0]], "1")[0]   # the mixer's op-amp rail
    track(board, n5, (PB.TRUNK_X - 1.0, PB.RAIL_Y), (PB.SLOT_X[-1] + 5.0, PB.RAIL_Y), TRUNK_W)
    for ref in [p.ref for p in D.PARTS if p.note == "slot rail bulk"]:
        cx, cy = pad_xy(F[ref], "1")
        track(board, n5, (cx, cy), (PB.TRUNK_X, cy), 0.6)
    track(board, n5, (PB.SLOT_X[-1] + 5.0, PB.RAIL_Y), (west, PB.RAIL_Y), RAIL_W)
    for k in range(1, 9):
        x = PB.SLOT_X[k - 1]
        for n in (1, 2):
            px, py = PB.pin_xy(k, n)
            track(board, n5, (px, py), (px, PB.RAIL_Y), RAIL_W)
        cx, cy = pad_xy(F[by_note[f"slot {k} supply"]], "1")
        track(board, n5, (cx, cy), (cx, PB.RAIL_Y), RAIL_W)
        # audio fan-out: L, R outside the west row, AUDIO_GND between the rows
        part = {s: F[by_note[f"slot {k} {s}"]] for s in ("C_IN_L", "C_IN_R", "C_G (mirror)", "R_IN_L", "R_IN_R",
                                                         "R_P_L", "R_P_R")}
        nl, nr, ng = (net_of(board, f"{s}_{k}") for s in ("AUDIO_L", "AUDIO_R", "AUDIO_GND"))
        p5, p6, p7 = (PB.pin_xy(k, n) for n in (5, 6, 7))
        cl, cr, cg = (pad_xy(part[s], "1") for s in ("C_IN_L", "C_IN_R", "C_G (mirror)"))
        path(board, nl, [p5, (cl[0], p5[1]), cl])
        path(board, nr, [p7, (x - 3.1, p7[1]), (x - 3.1, 75.0), (cr[0], 75.0 + (x - 3.1 - cr[0])), cr])
        path(board, ng, [p6, (x, p6[1]), cg])
        for c, r in (("C_IN_L", "R_IN_L"), ("C_IN_R", "R_IN_R")):
            mx = [pd for pd in part[c].Pads() if pd.GetNumber() == "2"][0].GetNet()
            path(board, mx, [pad_xy(part[c], "2"), pad_xy(part[r], "1")])
        mg = [pd for pd in part["C_G (mirror)"].Pads() if pd.GetNumber() == "2"][0].GetNet()
        g2 = pad_xy(part["C_G (mirror)"], "2")
        for r in ("R_P_L", "R_P_R"):
            r1 = pad_xy(part[r], "1")
            path(board, mg, [g2, (g2[0], g2[1] + 0.35), (r1[0], r1[1] - 0.25), r1])
        for r, netname in PB.RES_NET.items():
            sx, sy = pad_xy(part[r], "2")
            nn = net_of(board, netname)
            path(board, nn, [(sx, sy), (sx, PB.BAND[netname])])
            via(board, nn, (sx, PB.BAND[netname]))
    # summing band on B.Cu, GND guards, vias up at the west end
    for netname, y in PB.BAND.items():
        nn = net_of(board, netname)
        x_end = max(pcbnew.ToMM(v.GetPosition().x) for v in board.GetTracks()
                    if v.GetClass() == "PCB_VIA" and v.GetNetCode() == nn.GetNetCode())
        track(board, nn, (PB.BAND_X0, y), (x_end, y), 0.25, pcbnew.B_Cu)
        via(board, nn, (PB.BAND_X0, y))
    gx0, gx1 = PB.BAND_X0 + 1.2, PB.SLOT_X[-1] + 4.0
    for y in PB.GUARDS:
        track(board, gnd, (gx0, y), (gx1, y), 0.25, pcbnew.B_Cu)
        for x in [gx0, gx1] + [PB.SLOT_X[k] - 7.5 for k in range(1, 8)]:
            via(board, gnd, (x, y))
    # voice bus: one track per gap of the socket field, a jog to each socket's pin
    x0 = PB.SLOT_X[0] - 4.0
    for netname, (gap, pin) in PB.BUS_GAP.items():
        nn = net_of(board, netname)
        y = PB.gap_y(gap)
        track(board, nn, (x0, y), (PB.SLOT_X[-1] + 1.27, y))
        for k in range(1, 9):
            if k == D.FX_SLOT and netname == "CLK":
                continue                              # effects slot: pin 15 through the 0 R / 220 R pair
            px, py = PB.pin_xy(k, pin)
            track(board, nn, (px, y), (px, py))
    if PB.LAYERS == 2:
        mcu_ground_star(board, F, gnd)
    print("pre-routes: +5 V trunk and rail, audio fan-out, summing band, bus in the socket field" +
          (", MCU ground star" if PB.LAYERS == 2 else ""))


def mcu_ground_star(board, F, gnd):
    """2 layers: every VSS pin (8 VSSA, 23, 35, 47) inward to a GND patch inside the pad ring (zone in build()), four
    vias down into the bottom pour (with 4 layers the In1 plane takes this over)"""
    u1 = F["U1"]
    cx, cy = pcbnew.ToMM(u1.GetPosition().x), pcbnew.ToMM(u1.GetPosition().y)
    for pin in ("8", "23", "35", "47"):
        px, py = pad_xy(u1, pin)
        ix = cx + max(-2.6, min(2.6, px - cx)) if abs(px - cx) > 4 else px
        iy = cy + max(-2.6, min(2.6, py - cy)) if abs(py - cy) > 4 else py
        track(board, gnd, (px, py), (ix, iy), 0.3)
    for dx, dy in ((-1.2, -1.2), (1.2, -1.2), (-1.2, 1.2), (1.2, 1.2)):
        via(board, gnd, (cx + dx, cy + dy))


# ------------------------------------------------------------------ silkscreen
def art(board, F):
    AB.front(board, F, pad_xy)
    AB.back(board)


def sync_attrs(board):
    """DNP and BOM / position-file flags, value and LCSC field of every footprint from the design (they change
    without a re-route)"""
    n = 0
    for f in board.GetFootprints():
        p = PARTS.get(f.GetReference())
        if p is None:
            continue
        if f.IsDNP() != p.dnp or f.IsExcludedFromBOM() != (not p.bom):
            n += 1
        f.SetDNP(p.dnp)
        f.SetExcludedFromBOM(not p.bom); f.SetExcludedFromPosFiles(not p.bom)
        if f.GetValue() != p.value:
            n += 1
            f.SetValue(p.value)
        G.set_field(f, "LCSC", p.lcsc or "")
        if p.note:
            G.set_field(f, "Note", p.note)
    print(f"footprint attributes from the design: {n} changed")


def redo_art():
    """silkscreen of the routed board again (board-level texts and drawings on both silk layers), footprint
    attributes from the design"""
    board = pcbnew.LoadBoard(PCB)
    sync_attrs(board)
    for d in list(board.GetDrawings()):
        if d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            board.Delete(d)
    art(board, {f.GetReference(): f for f in board.GetFootprints()})
    pcbnew.SaveBoard(PCB, board)
    print("silkscreen redone")


# ------------------------------------------------------------------ build
def holes(board):
    for i, (x, y) in enumerate(PB.HOLES, 1):
        fp = G.load_fp("MountingHole:MountingHole_3.2mm_M3")
        fp.SetFPID(pcbnew.LIB_ID("MountingHole", "MountingHole_3.2mm_M3"))
        fp.SetReference(f"H{i}"); fp.SetValue("M3")
        fp.SetBoardOnly(True); fp.SetExcludedFromBOM(True); fp.SetExcludedFromPosFiles(True)
        fp.Reference().SetVisible(False)
        fp.SetPosition(V(x, y)); fp.SetLocked(True)
        board.Add(fp)
        for layer in (pcbnew.F_Cu, pcbnew.B_Cu):     # no copper in the screw-head area
            pts = [(x + 3.0 * math.cos(a * math.pi / 8), y + 3.0 * math.sin(a * math.pi / 8)) for a in range(16)]
            z = G.zone(board, layer, pts, rule_area=True, name="HOLE")
            z.SetDoNotAllowTracks(True); z.SetDoNotAllowVias(True); z.SetDoNotAllowZoneFills(True)


def build(route=False, passes=40):
    board = pcbnew.NewBoard(PCB)
    design_rules(board)
    G.add_rect(board, pcbnew.Edge_Cuts, 0, 0, PB.W, PB.H, 0.1)
    nets, fps = G.make_footprints(board, big_libs=("Amplifier_Operational", "MCU_WCH_RiscV", "Regulator_Linear",
                                                   "Reference_Voltage", "Connector_Generic", "Connector",
                                                   "Connector_Audio", "74xx", "Memory_Flash", "Power_Management",
                                                   "Power_Protection", "Jumper", "Isolator"))
    placed = set()
    for ref, (x, y, rot) in PB.anchors().items():
        fp = fps[ref][1]
        fp.SetOrientationDegrees(rot); fp.SetPosition(V(x, y))
        placed.add(ref)
        if ref.startswith("J"):
            fp.SetLocked(True)
        for g in list(fp.GraphicalItems()):          # footprint outline notches (the jack): the board stays square
            if g.GetLayer() == pcbnew.Edge_Cuts:
                fp.Remove(g)
    G.greedy_place(board, fps, placed, clr=PB.CLEARANCE)
    holes(board)
    # guide bands: no footprints; summing band: no bottom pour
    for x0, y0, x1, y1 in PB.GUIDE_BANDS:
        z = G.zone(board, pcbnew.F_Cu, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], rule_area=True, name="CARD_GUIDE")
        z.SetDoNotAllowFootprints(True); z.SetDoNotAllowZoneFills(False)
    y0, y1 = PB.GUARDS[0] - 0.35, PB.GUARDS[-1] + 0.35
    z = G.zone(board, pcbnew.B_Cu, [(PB.BAND_X0 - 0.6, y0), (PB.SLOT_X[-1] + 4.6, y0), (PB.SLOT_X[-1] + 4.6, y1),
                                    (PB.BAND_X0 - 0.6, y1)], rule_area=True, name="SUMMING_BAND")
    z.SetDoNotAllowZoneFills(True)
    # MCU ground star: a GND patch on F.Cu inside the pad ring with the VSS pins and four vias; B.Cu under the package
    # stays open for routing (crossings under the chip; the vias join whatever pour remains there)
    mx, my = PB.MX, PB.MY
    if PB.LAYERS == 2:
        G.zone(board, pcbnew.F_Cu, [(mx - 3.0, my - 3.0), (mx + 3.0, my - 3.0), (mx + 3.0, my + 3.0), (mx - 3.0, my + 3.0)],
               nets["GND"], name="GND_MCU", priority=1)
    e = 0.3
    edge = [(e, e), (PB.W - e, e), (PB.W - e, PB.H - e), (e, PB.H - e)]
    G.zone(board, pcbnew.F_Cu, edge, nets["GND"], name="GND_F")
    G.zone(board, pcbnew.B_Cu, edge, nets["GND"], name="GND_B")
    if PB.LAYERS == 4:                                # In1 solid GND; In2 +3V3 under the strip, GND under the slots
        G.zone(board, pcbnew.In1_Cu, edge, nets["GND"], name="GND_IN1")
        for name, pts in PB.PLANES_IN2.items():
            G.zone(board, pcbnew.In2_Cu, pts, nets[name.split("@")[0]], name=name.replace("@", "_IN2_"))
    for z in board.Zones():                           # no floating pour slivers (inside the LQFP's pad ring etc.)
        if not z.GetIsRuleArea():
            z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    pre_routes(board)
    art(board, {r: f for r, (p, f) in fps.items()})
    pcbnew.SaveBoard(PCB, board)
    print("saved", PCB)
    if route:
        do_route(board, passes)


def freeroute(board, passes):
    """one Freerouting run (GND's net class skipped: the pours connect it)"""
    stem = os.path.splitext(PCB)[0]                  # per variant, so a 2-layer check can run beside the 4-layer board
    dsn, ses = stem + ".dsn", stem + ".ses"
    print("DSN export:", pcbnew.ExportSpecctraDSN(board, dsn))
    log = open(stem + "_route.log", "a")
    subprocess.run(["java", "-jar", G.freerouting_jar(), "-de", dsn, "-do", ses, "-mp", str(passes), "-mt", "1",
                    "-dct", "0", "-inc", GND_CLASS], check=True, stdout=log, stderr=subprocess.STDOUT)
    print("SES import:", pcbnew.ImportSpecctraSES(board, ses))


G.freeroute = freeroute                          # gen_pcb's repair / finish rounds use this one


def do_route(board, passes):
    G.stitch(board, "GND")                            # every GND SMD pad: a via into the pours / planes
    if PB.LAYERS == 4:
        G.stitch(board, "+3V3", [PB.PLANES_IN2["+3V3@strip"]])
        import pcb_maze                               # +3V3 pads outside the strip plane (the VREF divider): route them
        pcb_maze.route_leftovers(board, only=["+3V3"], lock=True)
    freeroute(board, passes)
    freeroute(board, 20)
    G.post_route(board)
    print("routed and saved")
    G.repair()


if __name__ == "__main__":
    if "--repair" in sys.argv:
        G.repair()
    elif "--art" in sys.argv:
        redo_art()
    elif "--finish" in sys.argv:
        G.finish()
    else:
        build(route="--route" in sys.argv)
