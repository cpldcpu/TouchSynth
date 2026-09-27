"""Schematic generator v2: hand-designed sheet layouts (layouts.py) drawn with wires, auto-completed with labels.

Any unit a layout does not place is auto-placed in a spare area, so the schematic is always complete; the
netlist check (check_netlist.py) verifies the result against design.py.
"""
import os, datetime
import sexp as S
from sexp import Q
import design as D
import draw as W
import gen_sch as G
import layouts as LAY
import uuid as _uuid

NS = _uuid.UUID("7a1f3c2e-5b8d-4e6f-9a0b-1c2d3e4f5a6b")


def duid(*parts):
    """deterministic UUID (stable across regenerations, used to link PCB footprints to symbols)"""
    return str(_uuid.uuid5(NS, "/".join(str(p) for p in parts)))

OUT = G.OUT


def units_by_sheet():
    res = {n: [] for n in D.SHEETS}
    net_sheets = {}
    for p in D.PARTS:
        sym = S.get_symbol(p.lib_id)
        pinmap = {num: u for u, num, *_ in S.pins(sym)}
        us = sorted({pinmap[k] for k in p.pins if k in pinmap} | ({1} if S.units(sym) == 1 else set()))
        for u in us:
            u = max(u, 1)
            sh = p.unit_sheets.get(u, p.sheet)
            res[sh].append((p, u))
            for pin, n in p.pins.items():
                if pinmap.get(pin, 1) in (u, 0):
                    net_sheets.setdefault(n, set()).add(sh)
    glob = {n for n, s in net_sheets.items() if len(s) > 1 and n not in W.POWER} | {"VP"}
    return res, glob


def default_fields(pl):
    two = len(pl.pins) == 2 and pl.part.lib_id.startswith("Device:")
    if two and pl.rot in (90, 270):
        return "above"
    return "right"


def autoplace(sh, todo, W_, y0):
    x, y, rowh = 20.0, y0, 0.0
    for p, u in todo:
        sym = S.get_symbol(p.lib_id)
        two = len([x_ for x_ in S.pins(sym) if x_[0] in (0, 1)]) == 2 and p.lib_id.startswith("Device:") \
            and p.lib_id != "Device:LED"
        rot = 90 if two else 0
        probe = W.Placed(p, u, 0, 0, rot, None)
        bx0, by0, bx1, by1 = probe.box
        lab = max([len(n) for n in p.pins.values()] + [3]) * W.CHAR_W + 6
        w = (bx1 - bx0) + 2 * lab + 4
        h = (by1 - by0) + 2 * lab * (0 if two else 0.5) + 12
        if x + w > W_ - 20:
            x, y, rowh = 20.0, y + rowh, 0.0
        sh.place(p.ref, x + lab - bx0, y + 6 - by0, rot=rot, unit=u)
        x += w; rowh = max(rowh, h)


def write_sheet(sh, gsheet, paper):
    gs = gsheet
    for pl in sh.placed:
        p = pl.part
        side = sh.fields.get((p.ref, pl.unit)) or default_fields(pl)
        x0, y0, x1, y1 = pl.box
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if side == "right":
            fr, fv, just = (x1 + 1.3, cy - 0.7), (x1 + 1.3, cy + 1.5), "left"
        elif side == "left":
            fr, fv, just = (x0 - 1.3, cy - 0.7), (x0 - 1.3, cy + 1.5), "right"
        elif side == "below":
            fr, fv, just = (x0, y1 + 2.2), (x0, y1 + 4.1), "left"
        else:
            fr, fv, just = (x0, y0 - 3.2), (x0, y0 - 1.3), "left"
        X, Y = pl.x, pl.y
        if pl.mirror == "y":                      # KiCad mirrors field justification with the symbol
            just = {"left": "right", "right": "left"}[just]
        props = [("Reference", p.ref, fr[0], fr[1], False, just), ("Value", p.value, fv[0], fv[1], False, just),
                 ("Footprint", p.fp, X, Y, True, None), ("Datasheet", "", X, Y, True, None),
                 ("LCSC", p.lcsc or "", X, Y, True, None), ("Sim", p.sim or "", X, Y, True, None)]
        if p.note:
            props.append(("Note", p.note, X, Y, True, None))
        gs.lib(p.lib_id)
        G.symbol_instance(gs, p.lib_id, p.ref, p.value, X, Y, pl.rot, pl.unit, props, list(pl.pins.keys()),
                          dnp=p.dnp, bom=p.bom, uuid_=duid("sym", p.ref, pl.unit))
        if pl.mirror:
            gs.items[-1].insert(4, ["mirror", pl.mirror])
    for a, b in sh.wires:
        G.wire(gs, a[0], a[1], b[0], b[1])
    for net, p, d, k in sh.labels:
        G.net_label(gs, net, p[0], p[1], d)
    for net, p, d in sh.powers:
        G.net_label(gs, net, p[0], p[1], d)
    for i, (net, (x, y)) in enumerate(sh.flags):
        ref = f"#FLG{gs.idx:02d}{i + 1:02d}"
        gs.lib("power:PWR_FLAG")
        G.symbol_instance(gs, "power:PWR_FLAG", ref, "PWR_FLAG", x, y, 0, 1,
                          [("Reference", ref, x, y - 5, True, None), ("Value", "PWR_FLAG", x, y - 3.5, False, None),
                           ("Footprint", "", x, y, True, None), ("Datasheet", "", x, y, True, None)], ["1"],
                          bom=False, board=True)
    for x, y in sh.ncs:
        G.no_connect(gs, x, y)
    for x, y in sh.junctions():
        gs.items.append(["junction", ["at", G.fmt(x), G.fmt(y)], ["diameter", "0"], ["color", "0", "0", "0", "0"],
                         ["uuid", G.uid()]])
    for s, x, y, size, bold in sh.texts:
        eff = ["effects", ["font", ["size", G.fmt(size), G.fmt(size)]] + ([["thickness", "0.3"], ["bold", "yes"]] if bold else []),
               ["justify", "left", "bottom"]]
        gs.items.append(["text", Q(s), ["exclude_from_sim", "no"], ["at", G.fmt(x), G.fmt(y), "0"], eff, ["uuid", G.uid()]])
    for x1, y1, x2, y2 in sh.lines:
        gs.items.append(["polyline", ["pts", ["xy", G.fmt(x1), G.fmt(y1)], ["xy", G.fmt(x2), G.fmt(y2)]],
                         ["stroke", ["width", "0.15"], ["type", "dash"]], ["fill", ["type", "none"]], ["uuid", G.uid()]])


def build():
    os.makedirs(OUT, exist_ok=True)
    per, glob = units_by_sheet()
    root_uuid = G.Q(duid("root"))
    today = datetime.date.today().isoformat()
    sheets = []
    for i, (name, title) in enumerate(D.SHEETS.items()):
        sh = W.Sheet(name)
        paper, (PW, PH) = LAY.PAPER.get(name, ("A3", (420, 297)))
        sh.text(title, 15, 18, 3.0, True)
        fn = getattr(LAY, "sheet_" + name, None)
        if fn:
            fn(sh)
        done = {(pl.part.ref, pl.unit) for pl in sh.placed}
        todo = [(p, u) for p, u in per[name] if (p.ref, u) not in done]
        if todo:
            ymax = max([pl.box[3] for pl in sh.placed] + [30]) + 15
            sh.heading("Not yet laid out (auto-placed)", 15, ymax, PW - 15)
            autoplace(sh, todo, PW, ymax + 4)
        for extra in LAY.EXTRA.get(name, []):
            extra(sh)
        sh.complete(glob)
        sh.split_wires()
        gs = G.Sheet(name, title, glob)
        gs.uuid = G.Q(duid("sheet", name))
        gs.idx = i + 1
        gs.path = f"/{root_uuid}/{gs.uuid}"
        write_sheet(sh, gs, paper)
        doc = ["kicad_sch", ["version", G.VERSION], ["generator", Q("touchsynth_gen")], ["generator_version", Q("10.0")],
               ["uuid", gs.uuid], ["paper", Q(paper)],
               ["title_block", ["title", Q(f"TouchSynth — {title}")], ["date", Q(today)], ["rev", Q("0.1")],
                ["comment", "1", Q("Generated by hw/gen_sch2.py (layouts.py) from hw/design.py")]],
               ["lib_symbols"] + list(gs.libs.values())] + gs.items
        with open(os.path.join(OUT, f"{name}.kicad_sch"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(S.dump(doc) + "\n")
        sheets.append((name, title, gs, len(todo)))
    # root
    items = []
    for i, (name, title, gs, n) in enumerate(sheets):
        x, y = 20 + (i % 4) * 95, 40 + (i // 4) * 70
        items.append(["sheet", ["at", G.fmt(x), G.fmt(y)], ["size", "80", "45"], ["exclude_from_sim", "no"],
                      ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"], ["fields_autoplaced", "yes"],
                      ["stroke", ["width", "0.1524"], ["type", "solid"]], ["fill", ["color", "0", "0", "0", "0.0000"]],
                      ["uuid", gs.uuid],
                      ["property", Q("Sheetname"), Q(name), ["at", G.fmt(x), G.fmt(y - 0.7), "0"],
                       ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", "left", "bottom"]]],
                      ["property", Q("Sheetfile"), Q(f"{name}.kicad_sch"), ["at", G.fmt(x), G.fmt(y + 45.6), "0"],
                       ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", "left", "top"]]],
                      ["instances", ["project", Q(G.PROJECT), ["path", Q(f"/{root_uuid}"), ["page", Q(str(i + 2))]]]]])
        items.append(["text", Q(title), ["exclude_from_sim", "no"], ["at", G.fmt(x + 3), G.fmt(y + 22), "0"],
                      ["effects", ["font", ["size", "1.8", "1.8"]], ["justify", "left", "bottom"]], ["uuid", G.uid()]])
    items.append(["text", Q("TouchSynth — MCU-controlled analog mono synth (CH32V003/V002)"), ["exclude_from_sim", "no"],
                  ["at", "20", "25", "0"], ["effects", ["font", ["size", "4", "4"], ["thickness", "0.8"], ["bold", "yes"]],
                                            ["justify", "left", "bottom"]], ["uuid", G.uid()]])
    root = ["kicad_sch", ["version", G.VERSION], ["generator", Q("touchsynth_gen")], ["generator_version", Q("10.0")],
            ["uuid", root_uuid], ["paper", Q("A4")],
            ["title_block", ["title", Q("TouchSynth")], ["date", Q(today)], ["rev", Q("0.1")]],
            ["lib_symbols"]] + items + [["sheet_instances", ["path", Q("/"), ["page", Q("1")]]]]
    with open(os.path.join(OUT, f"{G.PROJECT}.kicad_sch"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(S.dump(root) + "\n")
    print("auto-placed units per sheet:", {n: k for n, _, _, k in sheets})


if __name__ == "__main__":
    build()
