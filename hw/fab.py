"""JLCPCB fabrication outputs: gerbers + drill (zip), BOM and CPL in JLCPCB format.

  python fab.py        (uses kicad-cli; writes hw/touchsynth/production/)

Rotation corrections follow the common KiCad -> JLCPCB conventions; always check the placement preview on
the JLCPCB order page (especially SOT-23 / SOT-363 / SOT-89 / diodes / LEDs).
"""
import os, re, csv, subprocess, zipfile, shutil
import design as D
import sexp as S

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.join(HERE, "touchsynth")
PCB = os.path.join(PRJ, "touchsynth.kicad_pcb")
OUT = os.path.join(PRJ, "production")
CLI = S.KICAD_CLI

ROT = [(r"^SOT-23", 180), (r"^SOT-363", 180), (r"^SOT-89", 180), (r"^SOIC-", 270), (r"^TSSOP-", 270),
       (r"^SMDIP-", 270), (r"^R_Array_Convex", 90)]
LAYERS = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"


def run(*args):
    r = subprocess.run([CLI, *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stdout + r.stderr)


def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    gdir = os.path.join(OUT, "gerbers")
    os.makedirs(gdir)
    run("pcb", "export", "gerbers", "--layers", LAYERS, "--no-protel-ext", "-o", gdir + os.sep, PCB)
    run("pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm", "--generate-map",
        "--map-format", "gerberx2", "-o", gdir + os.sep, PCB)
    zpath = os.path.join(OUT, "touchsynth_gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gdir)):
            z.write(os.path.join(gdir, f), f)
    # positions from KiCad (mm, top side), then JLCPCB CPL with rotation corrections
    pos = os.path.join(OUT, "pos_kicad.csv")
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "front", "--exclude-dnp", "-o", pos,
        PCB)
    parts = {p.ref: p for p in D.PARTS}
    placed = []
    with open(pos, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ref = r["Ref"]
            p = parts.get(ref)
            if p is None or not p.lcsc or p.dnp or not p.bom:
                continue
            fpname = p.fp.split(":")[1]
            rot = float(r["Rot"])
            for pat, add in ROT:
                if re.search(pat, fpname):
                    rot = (rot + add) % 360
                    break
            placed.append((ref, float(r["PosX"]), float(r["PosY"]), rot))
    with open(os.path.join(OUT, "touchsynth_cpl.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for ref, x, y, rot in placed:
            w.writerow([ref, f"{x:.3f}mm", f"{y:.3f}mm", "Top", f"{rot:.0f}"])
    refs = {r for r, *_ in placed}
    groups = {}
    for p in D.PARTS:
        if p.ref in refs:
            groups.setdefault((p.value, p.fp.split(":")[1], p.lcsc), []).append(p.ref)
    with open(os.path.join(OUT, "touchsynth_bom.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC"])
        for (val, fp, lcsc), rs in sorted(groups.items(), key=lambda kv: kv[1][0]):
            w.writerow([val, ",".join(sorted(rs, key=lambda r: (re.sub(r"\d", "", r), int(re.sub(r"\D", "", r))))),
                        fp, lcsc])
    print(f"gerbers: {zpath}")
    print(f"BOM: {len(groups)} lines, {len(refs)} placements; CPL written")
    excluded = [p.ref for p in D.PARTS if p.ref not in refs]
    print("not assembled:", ", ".join(excluded))


if __name__ == "__main__":
    main()
