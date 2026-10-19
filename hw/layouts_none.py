"""Empty layout set: every part is auto-placed (first schematic of a new board, before hand layouts exist).
Only the PWR_FLAGs for the supply nets are drawn (top right of the power sheet, or of the sheets named in the
design's FLAG_SHEETS for local supply nets)."""
from board import D, RAIL, POWER

PAPER = {}


def _flags(sh, nets):
    for i, net in enumerate(nets):
        p = (300.0 + i * 20.32, 20.32)
        q = (p[0], p[1] + 5.08)
        sh.flag(p, net)
        sh.w(p, q)
        if net in POWER:
            sh.pwr(q, net, (0, 1))
        else:
            sh.lbl(q, net, (0, 1))


FLAG_SHEETS = getattr(D, "FLAG_SHEETS", {"power": getattr(D, "FLAGS", ("GND", RAIL))})   # supply nets no
EXTRA = {name: [lambda sh, n=nets: _flags(sh, n)] for name, nets in FLAG_SHEETS.items() if name in D.SHEETS}
                                                                                         # power-output pin drives
