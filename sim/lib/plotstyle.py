"""Shared figure style for the TouchSynth reports (Markdown now, LaTeX later).

- Sizes match a LaTeX article text width of 6.3 in (full) / 3.1 in (half).
- Serif Computer-Modern-like mathtext, 9 pt, so figures blend with 10 pt LaTeX body text.
- No in-figure titles: captions live in the document. Panels get (a), (b) … labels instead.
- Every figure is written as vector PDF (LaTeX) and 200 dpi PNG (Markdown) to docs/figures/.
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIGDIR = os.path.join(ROOT, "docs", "figures")
DATADIR = os.path.join(ROOT, "docs", "results")

FULL = 6.3   # in
HALF = 3.1   # in

# Colour-blind-safe palette (Okabe-Ito), used in this order everywhere
C = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000"]

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["DejaVu Serif"],
    "mathtext.fontset": "cm",
    "font.size": 9,
    "axes.labelsize": 9,
    "axes.titlesize": 9,
    "legend.fontsize": 7.5,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "axes.prop_cycle": matplotlib.cycler(color=C),
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linewidth": 0.5,
    "lines.linewidth": 1.1,
    "lines.markersize": 3.5,
    "legend.frameon": False,
    "figure.dpi": 100,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "pdf.fonttype": 42,
})


def fig(ncols=1, nrows=1, width=FULL, aspect=0.62, **kw):
    """Create a figure with the report width; height = width*aspect (per row, scaled)."""
    h = width * aspect * (nrows / ncols if ncols > 1 else nrows)
    return plt.subplots(nrows, ncols, figsize=(width, h), **kw)


def label_panels(axes):
    for i, ax in enumerate(axes.flat if hasattr(axes, "flat") else axes):
        ax.text(-0.13, 1.02, f"({chr(97 + i)})", transform=ax.transAxes, fontsize=9, va="bottom")


def save(f, name):
    os.makedirs(FIGDIR, exist_ok=True)
    f.savefig(os.path.join(FIGDIR, name + ".pdf"))
    f.savefig(os.path.join(FIGDIR, name + ".png"), dpi=200)
    plt.close(f)
    return f"figures/{name}.png"


def save_csv(name, header, rows):
    os.makedirs(DATADIR, exist_ok=True)
    with open(os.path.join(DATADIR, name + ".csv"), "w", newline="\n", encoding="utf-8") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            fh.write(",".join(f"{v:.6g}" if isinstance(v, float) else str(v) for v in r) + "\n")
