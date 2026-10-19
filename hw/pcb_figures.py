"""PCB figures for the docs: layer plots and 3D renders of the board selected by BOARD, into
docs/figures/<project>_pcb/ (kicad-cli; PDF pages rasterised with PyMuPDF).

  BOARD=backplane python pcb_figures.py

Layer plots (top view unless noted): top (F.Cu + silk + outline), fcu, bcu, inner layers of a 4-layer board (in1,
in2), silk (front silkscreen), bsilk (back silkscreen, mirrored: as seen from the back), place (silk, fab and
courtyards of the front). 3D renders: render_top, render_bottom, render_iso.
"""
import os, subprocess, tempfile
import fitz
import board as B
import sexp as S

CLI = S.KICAD_CLI
PCB = os.path.join(B.OUT, f"{B.PROJECT}.kicad_pcb")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "figures",
                   f"{B.PROJECT}_pcb")
DPI = 190
TWO = getattr(B.D, "COPPER_LAYERS", 4) == 2

PLOTS = {"top": ("F.Cu,F.SilkS,Edge.Cuts", False), "fcu": ("F.Cu,Edge.Cuts", False),
         "bcu": ("B.Cu,Edge.Cuts", False), "silk": ("F.SilkS,Edge.Cuts", False),
         "bsilk": ("B.SilkS,Edge.Cuts", True), "place": ("F.SilkS,F.Fab,F.CrtYd,Edge.Cuts", False)}
if not TWO:
    PLOTS.update({"in1": ("In1.Cu,Edge.Cuts", False), "in2": ("In2.Cu,Edge.Cuts", False)})
RENDERS = {"render_top": ["--side", "top", "-w", "1600", "-h", "1600"],
           "render_bottom": ["--side", "bottom", "-w", "1600", "-h", "1600"],
           "render_iso": ["--side", "top", "--rotate", "-40,0,30", "--perspective", "--zoom", "0.8", "-w", "1800",
                          "-h", "1300"]}


def run(*args):
    r = subprocess.run([CLI, *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stdout + r.stderr)


def plot(name, layers, mirror, tmp):
    pdf = os.path.join(tmp, f"{name}.pdf")
    run("pcb", "export", "pdf", "--mode-single", "-l", layers, "--drill-shape-opt", "2",
        *(["--mirror"] if mirror else []), "-o", pdf, PCB)
    page = fitz.open(pdf)[0]
    r = fitz.Rect()
    for d in page.get_drawings():                        # crop to the drawn content (the board and what overhangs)
        r |= d["rect"]
    page.get_pixmap(dpi=DPI, clip=r + (-4, -4, 4, 4)).save(os.path.join(OUT, f"{name}.png"))


def main():
    os.makedirs(OUT, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, (layers, mirror) in PLOTS.items():
            plot(name, layers, mirror, tmp)
            print("plot", name)
    for name, args in RENDERS.items():
        run("pcb", "render", "--quality", "high", "--background", "opaque", *args,
            "-o", os.path.join(OUT, f"{name}.png"), PCB)
        print("render", name)
    print("figures in", OUT)


if __name__ == "__main__":
    main()
