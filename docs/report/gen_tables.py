"""Generate LaTeX snippets for the design report from the design data (never copy numbers by hand).

  python gen_tables.py        -> generated/bom.tex, generated/floorplan.tex, generated/stats.tex

Inputs: hw/touchsynth/production/touchsynth_bom.csv (run hw/fab.py first), the JLCPCB parts list,
hw/design.py, hw/pcb_place.py and hw/gen_pcb.py (floorplan geometry).
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "hw"))
OUT = os.path.join(HERE, "generated")

import design as D                                   # noqa: E402
import pcb_place as PP                               # noqa: E402

LIB = {"basic": "Basic", "promotional_extended": "Promo"}


def tex(s):
    return (s.replace("\\", r"\textbackslash{}").replace("&", r"\&").replace("%", r"\%").replace("_", r"\_")
             .replace("#", r"\#").replace("µ", r"\textmu{}").replace("Ω", r"$\Omega$"))


def refs_compact(refs):
    """R1,R2,R3,R5 -> R1--R3, R5"""
    by = {}
    for r in refs:
        m = re.match(r"([A-Z]+)(\d+)$", r)
        by.setdefault(m.group(1), []).append(int(m.group(2)))
    out = []
    for p, ns in sorted(by.items()):
        ns.sort()
        run = [ns[0]]
        for n in ns[1:] + [None]:
            if n is not None and n == run[-1] + 1:
                run.append(n)
                continue
            out.append(f"{p}{run[0]}" if len(run) == 1 else
                       f"{p}{run[0]}, {p}{run[1]}" if len(run) == 2 else f"{p}{run[0]}--{p}{run[-1]}")
            if n is not None:
                run = [n]
    return ", ".join(out)


def bom():
    parts = {r["lcsc"]: r for r in csv.DictReader(open(os.path.join(ROOT, "parts",
                                                   "jlcpcb_basic_and_promotional_parts.csv"), encoding="utf-8"))}
    rows, total, n = [], 0.0, 0
    for r in csv.DictReader(open(os.path.join(ROOT, "hw", "touchsynth", "production", "touchsynth_bom.csv"),
                                 encoding="utf-8")):
        refs = r["Designator"].split(",")
        p = parts[r["LCSC"]]
        price = float(p["price_usd"])
        total += price * len(refs)
        n += len(refs)
        pkg = r["Footprint"].split("_")[1] if r["Footprint"].startswith(("R_", "C_", "LED_")) else \
            r["Footprint"].split("_")[0]
        rows.append((r["Comment"], len(refs), pkg, r["LCSC"], LIB[p["library"]], price, refs))
    rows.sort(key=lambda x: ({"R": 0, "C": 1}.get(x[6][0][0], 2), x[6][0][0], -x[1]))
    lines = [r"\begin{longtable}{@{}l r l l l r p{5.2cm}@{}}",
             r"\caption{Assembled parts (JLCPCB PCBA, top side). Unit prices from the JLCPCB parts list at the "
             r"time of design.}\label{tab:bom}\\",
             r"\toprule Value & Qty & Package & LCSC & Library & USD/pc & Designators\\ \midrule\endfirsthead",
             r"\toprule Value & Qty & Package & LCSC & Library & USD/pc & Designators\\ \midrule\endhead",
             r"\bottomrule\endfoot"]
    for val, q, pkg, lcsc, lib, price, refs in rows:
        lines.append(f"{tex(val)} & {q} & {tex(pkg)} & {lcsc} & {lib} & {price:.4f} & "
                     f"{{\\footnotesize {refs_compact(refs)}}}\\\\")
    lines.append(r"\midrule")
    lines.append(f"\\multicolumn{{2}}{{@{{}}l}}{{{n} parts}} & \\multicolumn{{3}}{{l}}{{{len(rows)} BOM lines}} & "
                 f"{total:.2f} & per board (parts only)\\\\")
    lines.append(r"\end{longtable}")
    open(os.path.join(OUT, "bom.tex"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    basic = sum(1 for x in rows if x[4] == "Basic")
    return {"bomlines": len(rows), "placed": n, "partscost": f"{total:.2f}", "basiclines": basic,
            "promolines": len(rows) - basic}


def floorplan():
    """TikZ floorplan, 1 mm = 0.155 cm, y down"""
    s = 0.142
    L = [r"\begin{tikzpicture}[x=%.3fcm,y=-%.3fcm,font=\scriptsize\sffamily]" % (s, s),
         r"\draw[thick] (0,0) rectangle (100,100);"]
    colors = {"pwr": "red!12", "refdco": "orange!15", "ladder": "yellow!20", "expo": "yellow!12",
              "ina": "green!12", "res": "green!20", "vca": "teal!15", "cv": "cyan!12",
              "midi": "gray!12", "dac": "blue!12", "mcu": "blue!20", "io": "violet!15"}
    for k, (x0, y0, x1, y1) in PP.BLOCKS.items():
        L.append(f"\\filldraw[fill={colors[k]},draw=black!50] ({x0:.2f},{y0:.2f}) rectangle ({x1:.2f},{y1:.2f});")
        L.append(f"\\node[align=center,text width={(x1 - x0) * s * 0.9:.2f}cm] at ({(x0 + x1) / 2:.2f},"
                 f"{(y0 + y1) / 2:.2f}) {{{tex(PP.LABELS[k])}}};")
    # keyboard (from gen_pcb geometry)
    import importlib.util
    spec = importlib.util.spec_from_file_location("gp", os.path.join(ROOT, "hw", "gen_pcb.py"))
    src = open(os.path.join(ROOT, "hw", "gen_pcb.py"), encoding="utf-8").read()
    g = {}
    for name in ("WX0, WPITCH, WY", "BY", "FX, FYS", "LED_Y", "HOLES", "CONNECTORS"):
        m = re.search(r"^" + re.escape(name) + r" = (.+?)(?:\s+#.*)?$", src, re.M)
        exec(f"{name} = {m.group(1)}", {}, g)
    whites = [k for k in D.KEYS[:13] if "#" not in k]
    for i, k in enumerate(whites):
        x = g["WX0"] + g["WPITCH"] * i
        L.append(f"\\draw[fill=white] ({x - 4.3:.2f},77) rectangle ({x + 4.3:.2f},90);")
        L.append(f"\\node at ({x:.2f},87) {{{tex(k)}}};")
    for k in D.KEYS[:13]:
        if "#" in k:
            left = D.KEYS[D.KEYS.index(k) - 1]
            x = g["WX0"] + g["WPITCH"] * whites.index(left) + g["WPITCH"] / 2
            L.append(f"\\draw[fill=black!70] ({x - 3.25:.2f},{g['BY'] - 5:.2f}) rectangle "
                     f"({x + 3.25:.2f},{g['BY'] + 5:.2f});")
    for y, k in zip(g["FYS"], ("SHIFT", "$-$", "$+$")):
        L.append(f"\\draw[fill=white] ({g['FX'] - 3.75:.2f},{y - 3.75:.2f}) rectangle ({g['FX'] + 3.75:.2f},{y + 3.75:.2f});")
        L.append(f"\\node at ({g['FX']:.2f},{y:.2f}) {{{k}}};")
    L.append(f"\\draw[dashed,red!60!black] (3,{g['LED_Y']:.1f}) -- (97,{g['LED_Y']:.1f}) node[pos=0.46,fill=white,inner sep=1pt] {{LEDs}};")
    for x, y in g["HOLES"]:
        L.append(f"\\draw ({x},{y}) circle (1.6);")
    for name, (x, y) in g["CONNECTORS"].items():
        L.append(f"\\node[draw,fill=yellow!30,inner sep=1pt] at ({x + 1.3:.1f},{y:.1f}) {{\\tiny {tex(name)}}};")
    L.append(r"\node[font=\footnotesize\sffamily] at (50,95.5) {logo and waveform art};")
    L.append(r"\end{tikzpicture}")
    open(os.path.join(OUT, "floorplan.tex"), "w", encoding="utf-8").write("\n".join(L) + "\n")


def stats(extra):
    groups = {}
    for p in D.PARTS:
        groups[p.sheet] = groups.get(p.sheet, 0) + 1
    nets = {n for p in D.PARTS for n in p.pins.values() if not n.startswith("NC_")}
    d = dict(extra)
    d.update({"parts": len(D.PARTS), "nets": len(nets), "sheets": len(groups),
              "dnp": sum(1 for p in D.PARTS if p.dnp)})
    lines = [f"\\newcommand{{\\stat{k.capitalize()}}}{{{v}}}" for k, v in d.items()]
    open(os.path.join(OUT, "stats.tex"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return d


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    b = bom()
    floorplan()
    print(stats(b))
