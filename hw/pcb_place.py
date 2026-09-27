"""Signal-flow floorplan for the TouchSynth PCB (used by gen_pcb.py).

Anchors (ICs, transistor ladder, pairs, connectors ...) get explicit positions. Every other part is assigned to a
block rectangle and placed greedily: parts most connected to what is already placed go first, each to the free
spot in its block that minimises the distance from its pads to the pads it connects to.
"""
import design as D

# ---- floorplan (board 100 x 100, keys below y = 54):
#   analog area   x 3 ... 75,  y 9 ... 45   (signal-flow blocks, below)
#   right column  x 75 ... 97.5: MIDI in (top), trim DAC next to the VCA, MCU
#   keys I/O row  x 3 ... 97.5, y 45 ... 53.5: touch muxes and LED shift registers right above their keys
# The analog blocks were first laid out in a 58.5 x 44.5 area; they are mapped affinely onto 72 x 36.
# Blocks tile the area with shared edges; parts keep STREET off every edge so the silkscreen frame can run
# along it, and each block reserves a title tab in its top-left corner.
_ANALOG_SRC = {
    "pwr":    (3.0, 9.0, 21.75, 23.5),
    "refdco": (3.0, 23.5, 21.75, 50.5),
    "ladder": (21.75, 9.0, 37.0, 39.5),
    "expo":   (21.75, 39.5, 37.0, 50.5),
    "ina":    (37.0, 9.0, 49.0, 22.0),
    "res":    (37.0, 22.0, 49.0, 37.5),
    "vca":    (49.0, 9.0, 61.5, 37.5),
    "cv":     (37.0, 37.5, 61.5, 50.5),
}
_SRC = (3.0, 9.0, 61.5, 50.5)                   # source frame of the analog layout
ANALOG = (3.0, 9.0, 75.0, 45.0)
IO_ROW = (3.0, 45.0, 97.5, 53.5)
RIGHT = (75.0, 9.0, 97.5, 45.0)


def ax(x):
    return ANALOG[0] + (x - _SRC[0]) * (ANALOG[2] - ANALOG[0]) / (_SRC[2] - _SRC[0])


def ay(y):
    return ANALOG[1] + (y - _SRC[1]) * (ANALOG[3] - ANALOG[1]) / (_SRC[3] - _SRC[1])


BLOCKS = {k: (ax(x0), ay(y0), ax(x1), ay(y1)) for k, (x0, y0, x1, y1) in _ANALOG_SRC.items()}
BLOCKS.update({
    "midi": (75.0, 9.0, 97.5, 20.0),
    "dac":  (75.0, 20.0, 86.0, 45.0),
    "mcu":  (86.0, 20.0, 97.5, 45.0),
    "io":   IO_ROW,
})
LABELS = {
    "pwr": "POWER", "refdco": "REF + DCO", "ladder": "LADDER VCF", "expo": "EXPO", "ina": "OUT AMP",
    "res": "RESONANCE", "vca": "VCA + OUT", "cv": "CV FILTERS", "mcu": "MCU", "midi": "MIDI IN (DNP)",
    "dac": "TRIM DAC", "io": "KEYS I/O",
}


def side_rect(blk):
    """area a block may spill into when it is full (never across the analog / digital boundary)"""
    if blk in _ANALOG_SRC:
        return ANALOG
    return IO_ROW if blk == "io" else RIGHT


STREET = 0.35
TAB_H = 0.8                                      # title text height


def tab_rect(blk):
    """reserved title area: top-left corner inside the block"""
    x0, y0, x1, y1 = BLOCKS[blk]
    return (x0 + 0.6, y0 + STREET, x0 + 0.6 + len(LABELS[blk]) * TAB_H * 0.9 + 0.3, y0 + STREET + TAB_H + 0.4)


def place_rect(blk):
    x0, y0, x1, y1 = BLOCKS[blk]
    return (x0 + STREET, y0 + STREET, x1 - STREET, y1 - STREET)


GROUP_BLOCK = {
    "Input, reverse protection, 5 V": "pwr",
    "References: VREF 4.5 V, VBIAS 1.5 V, V25 2.5 V": "refdco",
    "CV_AMP filter and V-to-I converter": "refdco",
    "Integrator and reset": "refdco",
    "Ladder bias chain": "ladder",
    "Transistor ladder (4 poles)": "ladder",
    "Mixer": "ladder",
    "CV_CUT filter and exponential converter": "expo",
    "Output instrumentation amplifier (G = 11)": "ina",
    "Resonance VCA and difference amplifier": "res",
    "CV_RES filter and V-to-I converter": "cv",
    "CV_VCA filter and V-to-I converter": "cv",
    "VCA core and offset trim": "vca",
    "Difference amplifier, line out": "vca",
    "Audio loopback to PD5": "vca",
    "MCU (CH32V003 / CH32V002, hand-soldered)": "mcu",
    "Programming (WCH-LinkE)": "mcu",
    "MIDI in (DNP)": "midi",
    "Shift registers (LEDs + trim DAC)": "io",
    "VCA trim DAC (8-bit R-2R)": "dac",
    "Touch multiplexers": "io",
}
# per-part overrides (by sim name): parts that electrically belong elsewhere than their schematic group
SIM_BLOCK = {
    "RB1A": "expo", "RB1B": "expo", "CBIA": "expo", "R25A": "expo", "R25B": "expo", "C25": "expo",
    "R1C": "cv", "C1C": "cv", "R2C": "cv", "C2C": "cv",
    "QVR": "res", "REVR": "res", "RBVR": "cv",
    "QVV": "vca", "REVV": "vca", "ROFFV": "vca", "RBVV": "cv",
    "QVA": "refdco", "REVA": "refdco", "RBVA": "refdco",
}


def by_sim(sim):
    for p in D.PARTS:
        if p.sim and sim in p.sim.split("/"):
            return p.ref
    raise KeyError(sim)


def by(pred):
    return [p.ref for p in D.PARTS if pred(p)][0]


def anchors():
    """ref -> (x, y, rot)"""
    a = {}
    # analog blocks: positions in the source frame, mapped like the blocks
    a[by_sim("DREV")] = (10.0, 12.5, 0)
    a[by_sim("XREG")] = (8.5, 18.0, 0)
    a[by(lambda p: p.sim == "XVREF/XDCO")] = (12.0, 33.0, 0)
    a[by_sim("MRST")] = (18.8, 31.0, 0)
    for k, sim in enumerate(("Q9", "Q7", "Q5", "Q3", "Q1")):         # ladder column, pair P4 on top
        a[by_sim(sim)] = (31.0, 13.0 + k * 5.4, 0)
    a[by_sim("QEA")] = (31.0, 42.0, 0)
    a[by(lambda p: p.sim == "XINA1/XINA2")] = (43.0, 15.5, 0)
    a[by_sim("QR1")] = (41.5, 29.5, 0)
    a[by(lambda p: p.sim == "XRDIF/XDIF")] = (53.5, 28.5, 0)
    a[by_sim("QA1")] = (53.5, 15.0, 0)
    a[by(lambda p: p.lib_id.endswith("LM324"))] = (54.0, 44.5, 90)
    a = {r: (ax(x), ay(y), rot) for r, (x, y, rot) in a.items()}
    # right column
    a[by(lambda p: p.lib_id == "Isolator:LTV-817S")] = (86.0, 14.5, 0)
    a[by(lambda p: p.lib_id.startswith("MCU_WCH"))] = (91.75, 33.0, 0)
    srs = {p.ref: p for p in D.PARTS if p.lib_id == "74xx:74HC595"}
    dac = [r for r, p in srs.items() if any(n.startswith("DAC_Q") for n in p.pins.values())][0]
    a[dac] = (80.5, 29.0, 0)
    # keys I/O row: each chip above the keys it serves (mux A: keys 1-8, LEDs 0-7, LEDs 8-15, mux B: keys 9-16)
    yc = (IO_ROW[1] + IO_ROW[3]) / 2
    leds = sorted([r for r in srs if r != dac], key=lambda r: int(r[1:]))
    muxes = sorted([p.ref for p in D.PARTS if p.lib_id == "4xxx:4051"], key=lambda r: int(r[1:]))
    for r, x in ((muxes[0], 17.0), (leds[0], 38.0), (leds[1], 62.0), (muxes[1], 85.0)):
        a[r] = (x, yc, 90)
    return a


_DEC_KIND = {"CD4051 decoupling": lambda q: q.lib_id == "4xxx:4051",
             "74HC595 decoupling": lambda q: q.lib_id == "74xx:74HC595",
             "MCU decoupling": lambda q: q.lib_id.startswith("MCU_WCH"),
             "MCU bulk": lambda q: q.lib_id.startswith("MCU_WCH"),
             "LM324 decoupling": lambda q: q.lib_id.endswith("LM324")}


def dec_ic(p):
    """ref of the IC a decoupling capacitor belongs to (generic notes: the k-th cap goes to the k-th IC)"""
    if not p.note:
        return None
    if p.note.startswith("decoupling "):
        return p.note.split()[1]
    if p.note in _DEC_KIND:
        caps = [q.ref for q in D.PARTS if q.note == p.note]
        ics = [q.ref for q in D.PARTS if _DEC_KIND[p.note](q)]
        return ics[min(caps.index(p.ref), len(ics) - 1)]
    return None


def block_of(p):
    if p.lib_id == "Connector:TestPoint":
        return tp_block(p)
    return _block_of(p)


TP_BLOCK = {"+5V": "pwr", "VP": "pwr"}          # supply test points next to the regulator


def tp_block(p):
    """a test point goes into the block holding most pins of its net (supplies: see TP_BLOCK)"""
    net = p.pins["1"]
    if net in TP_BLOCK:
        return TP_BLOCK[net]
    count = {}
    for q in D.PARTS:
        if q is p or q.lib_id == "Connector:TestPoint":
            continue
        b = _block_of(q)
        if b is None and q.note and q.note.startswith("decoupling "):
            b = _block_of([r for r in D.PARTS if r.ref == q.note.split()[1]][0])
        if b:
            count[b] = count.get(b, 0) + sum(1 for n in q.pins.values() if n == net)
    return max(count, key=count.get) if any(count.values()) else None


def _block_of(p):
    if p.sim:
        for s in p.sim.split("/"):
            if s in SIM_BLOCK:
                return SIM_BLOCK[s]
    if p.note and p.note.startswith("decoupling "):
        return None                                # placed next to its IC (handled by the placer)
    if p.note in ("MCU decoupling", "MCU bulk"):
        return "mcu"
    if p.note == "LM324 decoupling":
        return "cv"
    if p.note == "CD4051 decoupling":
        return "io"
    if p.note == "74HC595 decoupling":               # one per 595, in design order; the DAC one goes to the DAC
        caps = [q.ref for q in D.PARTS if q.note == "74HC595 decoupling"]
        srs = [q for q in D.PARTS if q.lib_id == "74xx:74HC595"]
        sr = srs[caps.index(p.ref)]
        return "dac" if any(n.startswith("DAC_Q") for n in sr.pins.values()) else "io"
    if p.note == "output bleeder":
        return "vca"
    return GROUP_BLOCK.get(p.group)
