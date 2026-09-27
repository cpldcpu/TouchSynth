"""Generate the KiCad 10 schematic (root + one sheet per block) from design.py.

Connections are made with a short wire stub on every pin ending in a net label (local label for nets that stay
on one sheet, global label for nets shared between sheets, power symbols for GND and +5V). Symbols are copied
from the KiCad standard libraries into each sheet's lib_symbols.
"""
import os, sys, uuid, math, datetime
import sexp as S
from sexp import Q
import design as D

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "touchsynth")
PROJECT = "touchsynth"
VERSION = "20250114"
GRID = 1.27
STUB = 2.54
POWER_SYMS = {"GND": "power:GND", "+5V": "power:+5V"}
CHAR_W = 1.05          # approx. width of a 1.27 mm label character


FIELD_ANGLE = {90: "90", 270: "90"}


def uid():
    return Q(str(uuid.uuid4()))


def g(v):
    return round(round(v / GRID) * GRID, 4)


def fmt(v):
    return f"{v:.4f}".rstrip("0").rstrip(".")


def rot_xy(x, y, rot):
    a = math.radians(rot)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


OUTWARD = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}   # pin angle (after rotation) -> outward (sch coords)


def place_pins(sym, unit, rot):
    """pins of a unit in schematic-relative coordinates: (num, dx, dy, outward_dir, etype, hidden)."""
    res = []
    for u, num, nm, x, y, ang, ln, et, hid in S.pins(sym):
        if u not in (0, unit):
            continue
        rx, ry = rot_xy(x, y, rot)
        a = int(round((ang + rot) % 360))
        res.append((num, rx, -ry, OUTWARD[a], et, hid))
    return res


def body_box(sym, unit, rot):
    x0, y0, x1, y1 = S.bbox(sym, unit)
    pts = [rot_xy(x, y, rot) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    xs = [p[0] for p in pts]; ys = [-p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def label_len(net):
    return len(net) * CHAR_W + 3.0


class Sheet:
    def __init__(self, name, title, global_nets):
        self.name, self.title, self.globals = name, title, global_nets
        self.items, self.libs, self.pwr = [], {}, 0
        self.uuid = uid()

    def lib(self, lib_id):
        if lib_id not in self.libs:
            self.libs[lib_id] = S.get_symbol(lib_id)
        return self.libs[lib_id]


def symbol_instance(sh, lib_id, ref, value, x, y, rot, unit, props, pins, dnp=False, bom=True, board=True, uuid_=None):
    sym = [ "symbol", ["lib_id", Q(lib_id)], ["at", fmt(x), fmt(y), str(rot)], ["unit", str(unit)],
            ["exclude_from_sim", "no"], ["in_bom", "yes" if bom else "no"], ["on_board", "yes" if board else "no"],
            ["dnp", "yes" if dnp else "no"], ["uuid", Q(uuid_) if uuid_ else uid()] ]
    for name, val, px, py, hide, just in props:
        eff = ["effects", ["font", ["size", "1.27", "1.27"]]]
        fang = FIELD_ANGLE.get(rot, "0")
        if just:
            eff.append(["justify", just])
        if hide:
            eff.append(["hide", "yes"])
        sym.append(["property", Q(name), Q(val), ["at", fmt(px), fmt(py), fang], eff])
    for p in pins:
        sym.append(["pin", Q(p), ["uuid", uid()]])
    sym.append(["instances", ["project", Q(PROJECT), ["path", Q(sh.path), ["reference", Q(ref)], ["unit", str(unit)]]]])
    sh.items.append(sym)


def wire(sh, x1, y1, x2, y2):
    sh.items.append(["wire", ["pts", ["xy", fmt(x1), fmt(y1)], ["xy", fmt(x2), fmt(y2)]],
                     ["stroke", ["width", "0"], ["type", "default"]], ["uuid", uid()]])


def net_label(sh, net, x, y, d):
    rot = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[d]
    if net in POWER_SYMS:
        lib_id = POWER_SYMS[net]
        sh.lib(lib_id)
        # GND body hangs "down" (lib -y), +5V body points "up"; rotate so the body points outward
        prot = ({(0, 1): 0, (1, 0): 90, (0, -1): 180, (-1, 0): 270} if net == "GND"
                else {(0, -1): 0, (-1, 0): 90, (0, 1): 180, (1, 0): 270})[d]
        sh.pwr += 1
        ref = f"#PWR{sh.idx:02d}{sh.pwr:03d}"
        tx, ty = x + d[0] * 5.0, y + d[1] * 5.0
        symbol_instance(sh, lib_id, ref, net, x, y, prot, 1,
                        [("Reference", ref, x, y, True, None), ("Value", net, tx, ty, False, None),
                         ("Footprint", "", x, y, True, None), ("Datasheet", "", x, y, True, None)], ["1"],
                        bom=False, board=True)
        return
    just = "left" if rot in (0, 90) else "right"
    if net in sh.globals:
        sh.items.append(["global_label", Q(net), ["shape", "passive"], ["at", fmt(x), fmt(y), str(rot)],
                         ["fields_autoplaced", "yes"],
                         ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", just]], ["uuid", uid()],
                         ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"), ["at", fmt(x), fmt(y), "0"],
                          ["effects", ["font", ["size", "1.27", "1.27"]], ["hide", "yes"]]]])
    else:
        sh.items.append(["label", Q(net), ["at", fmt(x), fmt(y), str(rot)],
                         ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", just, "bottom"]],
                         ["uuid", uid()]])


def no_connect(sh, x, y):
    sh.items.append(["no_connect", ["at", fmt(x), fmt(y)], ["uuid", uid()]])


def build():
    os.makedirs(OUT, exist_ok=True)
    nets = D.nets()
    net_sheets = {}
    units_of = []            # (part, unit, sheet)
    for p in D.PARTS:
        sym = S.get_symbol(p.lib_id)
        pinmap = {num: u for u, num, *_ in S.pins(sym)}
        for u in sorted({pinmap[k] for k in p.pins if k in pinmap} | ({1} if S.units(sym) == 1 else set())):
            sheet = p.unit_sheets.get(u, p.sheet)
            units_of.append((p, max(u, 1), sheet))
            for pin, n in p.pins.items():
                if pinmap.get(pin, 1) in (u, 0):
                    net_sheets.setdefault(n, set()).add(sheet)
    global_nets = {n for n, s in net_sheets.items() if len(s) > 1 and n not in POWER_SYMS}
    global_nets |= {"VP"}
    root_uuid = uid()
    sheets = {}
    for i, (name, title) in enumerate(D.SHEETS.items()):
        sh = Sheet(name, title, global_nets)
        sh.idx = i + 1
        sh.path = f"/{root_uuid}/{sh.uuid}"
        sheets[name] = sh

    # ---- place units: rows grouped by sub-block (heading per group), shelf packing, rows spread over the page
    per_sheet = {n: [] for n in sheets}
    for p, u, sname in units_of:
        per_sheet[sname].append((p, u, p.unit_groups.get(u, p.group) or ""))
    flags = [("#FLG01", "GND"), ("#FLG02", "VP")]          # PWR_FLAGs on the power sheet
    papers = {}
    HEAD = 7.0
    for sname, lst in per_sheet.items():
        sh = sheets[sname]
        order = []
        for _, _, grp in lst:
            if grp not in order:
                order.append(grp)
        lst = sorted(lst, key=lambda t: order.index(t[2]))
        cells = []
        for p, u, grp in lst:
            sym = sh.lib(p.lib_id)
            rot = 90 if len([x for x in S.pins(sym) if x[0] in (0, 1)]) == 2 and p.lib_id.startswith("Device:")                 and p.lib_id != "Device:LED" else 0
            pins = place_pins(sym, u, rot)
            box = body_box(sym, u, rot)
            ext = {(-1, 0): 0.0, (1, 0): 0.0, (0, -1): 0.0, (0, 1): 0.0}
            for num, dx, dy, d, et, hid in pins:
                net = p.pins.get(num)
                if net is None:
                    continue
                l = STUB + (0 if net.startswith("NC_") else (5.0 if net in POWER_SYMS else label_len(net)))
                ext[d] = max(ext[d], l)
            xs = [pp[1] for pp in pins] + [box[0], box[2]]
            ys = [pp[2] for pp in pins] + [box[1], box[3]]
            left, right = min(xs) - ext[(-1, 0)], max(xs) + ext[(1, 0)]
            top, bot = min(ys) - ext[(0, -1)], max(ys) + ext[(0, 1)]
            fw = max(len(p.ref), len(p.value)) * CHAR_W + 1.0
            # fields go where no pins point: above (default), else right, else left, else above everything
            dirs = {d for (_, _, _, d, _, _) in pins}
            if (0, -1) not in dirs:
                fld = ("above", box[0], min(ys) - 3.6, min(ys) - 1.6)
                top = min(top, min(ys) - 5.5)
                right = max(right, box[0] + fw)
            elif (1, 0) not in dirs:
                fld = ("right", max(xs) + 1.5, box[1] + 1.5, box[1] + 3.4)
                right = max(right, max(xs) + 1.5 + fw)
            elif (-1, 0) not in dirs:
                fld = ("left", min(xs) - 1.5 - fw, box[1] + 1.5, box[1] + 3.4)
                left = min(left, min(xs) - 1.5 - fw)
            else:
                fld = ("above", box[0] + 2.54, top - 3.6, top - 1.6)
                top -= 5.5
            w = max(right - left, 11.0)
            cells.append(dict(p=p, u=u, grp=grp, rot=rot, pins=pins, box=box, left=left, right=left + w,
                              top=top, bot=bot, fld=fld))
        for paper, (W, H) in (("A3", (420, 297)), ("A2", (594, 420)), ("A1", (841, 594))):
            rows, cur, x, grp = [], None, 15.0, None
            for c in cells:
                w = c["right"] - c["left"] + 3.0
                if cur is None or c["grp"] != grp or x + w > W - 15:
                    cur = dict(cells=[], head=c["grp"] if c["grp"] != grp else None, h=0.0)
                    rows.append(cur); x = 15.0; grp = c["grp"]
                c["x0"] = x
                cur["cells"].append(c)
                cur["h"] = max(cur["h"], c["bot"] - c["top"] + 3.0)
                x += w
            total = sum(r["h"] + (HEAD if r["head"] is not None else 0) for r in rows)
            if 28 + total < H - 45:
                break
        spare = (H - 45) - 28 - total
        gap = min(12.0, spare / max(1, len(rows)))
        papers[sname] = paper
        sh.items.append(["text", Q(f"{sh.title}"), ["exclude_from_sim", "no"], ["at", "15", "18", "0"],
                         ["effects", ["font", ["size", "3", "3"], ["thickness", "0.6"], ["bold", "yes"]],
                          ["justify", "left", "bottom"]], ["uuid", uid()]])
        y = 26.0
        for r in rows:
            if r["head"] is not None:
                y += 2.0
                sh.items.append(["text", Q(r["head"]), ["exclude_from_sim", "no"], ["at", "15", fmt(g(y + 3)), "0"],
                                 ["effects", ["font", ["size", "2", "2"], ["thickness", "0.3"], ["bold", "yes"]],
                                  ["justify", "left", "bottom"]], ["uuid", uid()]])
                sh.items.append(["polyline", ["pts", ["xy", "15", fmt(g(y + 4))], ["xy", fmt(W - 15), fmt(g(y + 4))]],
                                 ["stroke", ["width", "0.15"], ["type", "dash"]], ["fill", ["type", "none"]],
                                 ["uuid", uid()]])
                y += HEAD - 2.0
            for c in r["cells"]:
                X, Y = g(c["x0"] - c["left"]), g(y - c["top"])
                p, u, rot, pins, box = c["p"], c["u"], c["rot"], c["pins"], c["box"]
                side, fx, fy1, fy2 = c["fld"]
                just = "left"
                props = [("Reference", p.ref, X + fx, Y + fy1, False, just),
                         ("Value", p.value, X + fx, Y + fy2, False, just),
                         ("Footprint", p.fp, X, Y, True, None), ("Datasheet", "", X, Y, True, None),
                         ("LCSC", p.lcsc or "", X, Y, True, None), ("Sim", p.sim or "", X, Y, True, None)]
                if p.note:
                    props.append(("Note", p.note, X, Y, True, None))
                symbol_instance(sh, p.lib_id, p.ref, p.value, X, Y, rot, u, props, [pp[0] for pp in pins],
                                dnp=p.dnp, bom=p.bom)
                for num, dx, dy, d, et, hid in pins:
                    net = p.pins.get(num)
                    tx, ty = X + dx, Y + dy
                    if net is None or net.startswith("NC_"):
                        no_connect(sh, tx, ty)
                        continue
                    ex, ey = tx + d[0] * STUB, ty + d[1] * STUB
                    wire(sh, tx, ty, ex, ey)
                    net_label(sh, net, ex, ey, d)
            y += r["h"] + gap
        if sname == "power":
            for i, (ref, net) in enumerate(flags):
                X, Y = g(W - 120 + i * 25), g(20)
                sh.lib("power:PWR_FLAG")
                symbol_instance(sh, "power:PWR_FLAG", ref, "PWR_FLAG", X, Y, 0, 1,
                                [("Reference", ref, X, Y - 5, True, None), ("Value", "PWR_FLAG", X, Y - 4, False, None),
                                 ("Footprint", "", X, Y, True, None), ("Datasheet", "", X, Y, True, None)], ["1"],
                                bom=False, board=True)
                wire(sh, X, Y, X, Y + STUB)
                net_label(sh, net, X, Y + STUB, (0, 1))

    # ---- write sheets
    today = datetime.date.today().isoformat()
    for sname, sh in sheets.items():
        doc = ["kicad_sch", ["version", VERSION], ["generator", Q("touchsynth_gen")], ["generator_version", Q("10.0")],
               ["uuid", sh.uuid], ["paper", Q(papers[sname])],
               ["title_block", ["title", Q(f"TouchSynth — {sh.title}")], ["date", Q(today)], ["rev", Q("0.1")],
                ["comment", "1", Q("Generated by hw/gen_sch.py from hw/design.py — edit the design, not this file")]],
               ["lib_symbols"] + list(sh.libs.values())] + sh.items
        with open(os.path.join(OUT, f"{sname}.kicad_sch"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(S.dump(doc) + "\n")
    # ---- root sheet
    items = []
    for i, (sname, sh) in enumerate(sheets.items()):
        x, y = 20 + (i % 4) * 95, 40 + (i // 4) * 70
        items.append(["sheet", ["at", fmt(x), fmt(y)], ["size", "80", "45"], ["exclude_from_sim", "no"],
                      ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"], ["fields_autoplaced", "yes"],
                      ["stroke", ["width", "0.1524"], ["type", "solid"]], ["fill", ["color", "0", "0", "0", "0.0000"]],
                      ["uuid", sh.uuid],
                      ["property", Q("Sheetname"), Q(sname), ["at", fmt(x), fmt(y - 0.7), "0"],
                       ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", "left", "bottom"]]],
                      ["property", Q("Sheetfile"), Q(f"{sname}.kicad_sch"), ["at", fmt(x), fmt(y + 45.6), "0"],
                       ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", "left", "top"]]],
                      ["instances", ["project", Q(PROJECT), ["path", Q(f"/{root_uuid}"), ["page", Q(str(i + 2))]]]]])
        items.append(["text", Q(sh.title), ["exclude_from_sim", "no"], ["at", fmt(x + 3), fmt(y + 22), "0"],
                      ["effects", ["font", ["size", "1.8", "1.8"]], ["justify", "left", "bottom"]], ["uuid", uid()]])
    items.append(["text", Q("TouchSynth — MCU-controlled analog mono synth (CH32V003/V002)"), ["exclude_from_sim", "no"],
                  ["at", "20", "25", "0"], ["effects", ["font", ["size", "4", "4"], ["thickness", "0.8"], ["bold", "yes"]],
                                            ["justify", "left", "bottom"]], ["uuid", uid()]])
    root = ["kicad_sch", ["version", VERSION], ["generator", Q("touchsynth_gen")], ["generator_version", Q("10.0")],
            ["uuid", root_uuid], ["paper", Q("A4")],
            ["title_block", ["title", Q("TouchSynth")], ["date", Q(today)], ["rev", Q("0.1")]],
            ["lib_symbols"]] + items + [["sheet_instances", ["path", Q("/"), ["page", Q("1")]]]]
    with open(os.path.join(OUT, f"{PROJECT}.kicad_sch"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(S.dump(root) + "\n")
    pro = os.path.join(OUT, f"{PROJECT}.kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w", encoding="utf-8", newline="\n") as fh:
            fh.write('{\n  "meta": {\n    "filename": "%s.kicad_pro",\n    "version": 3\n  }\n}\n' % PROJECT)
    print("sheets:", {k: papers[k] for k in papers}, "| global nets:", len(global_nets))


if __name__ == "__main__":
    build()
