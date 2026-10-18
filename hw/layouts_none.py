"""Empty layout set: every part is auto-placed (first schematic of a new board, before hand layouts exist).
Only the PWR_FLAGs for the supply nets are drawn (top right of the power sheet)."""
from board import D, RAIL, POWER

PAPER = {}


def _flags(sh):
    nets = getattr(D, "FLAGS", ("GND", RAIL))          # supply nets no power-output pin drives
    for i, net in enumerate(nets):
        p = (300.0 + i * 20.32, 20.32)
        q = (p[0], p[1] + 5.08)
        sh.flag(p, net)
        sh.w(p, q)
        if net in POWER:
            sh.pwr(q, net, (0, 1))
        else:
            sh.lbl(q, net, (0, 1))


EXTRA = {"power": [_flags]} if "power" in D.SHEETS else {}
