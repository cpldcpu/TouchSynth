"""Signal-flow floorplan for the TouchSynth PCB (used by gen_pcb.py).

Anchors (ICs, transistor ladder, pairs, connectors ...) get explicit positions. Every other part is assigned to a
block rectangle and placed greedily: parts most connected to what is already placed go first, each to the free
spot in its block that minimises the distance from its pads to the pads it connects to.
"""
import design as D

# ---- block rectangles (x0, y0, x1, y1), board 100 x 100, keyboard below y = 51. The blocks tile the circuit area
# with shared edges; parts keep STREET off every edge so the silkscreen frame can run along it, and each block
# reserves a title tab in its top-left corner.
BLOCKS = {
    "pwr":    (3.0, 9.0, 21.75, 23.5),
    "refdco": (3.0, 23.5, 21.75, 50.5),
    "ladder": (21.75, 9.0, 37.0, 39.5),
    "expo":   (21.75, 39.5, 37.0, 50.5),
    "ina":    (37.0, 9.0, 49.0, 22.0),
    "res":    (37.0, 22.0, 49.0, 37.5),
    "vca":    (49.0, 9.0, 61.5, 37.5),
    "cv":     (37.0, 37.5, 61.5, 50.5),
    "mcu":    (61.5, 9.0, 80.0, 23.0),
    "midi":   (80.0, 9.0, 97.5, 23.0),
    "sr":     (61.5, 23.0, 97.5, 40.0),
    "mux":    (61.5, 40.0, 97.5, 50.5),
}
LABELS = {
    "pwr": "POWER", "refdco": "REF + DCO", "ladder": "LADDER VCF", "expo": "EXPO", "ina": "OUT AMP",
    "res": "RESONANCE", "vca": "VCA + OUT", "cv": "CV FILTERS", "mcu": "MCU", "midi": "MIDI IN (DNP)",
    "sr": "SHIFT REG + TRIM DAC", "mux": "TOUCH MUX",
}
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
    "Shift registers (LEDs + trim DAC)": "sr",
    "VCA trim DAC (8-bit R-2R)": "sr",
    "Touch multiplexers": "mux",
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
    a[by_sim("DREV")] = (10.0, 12.5, 0)
    a[by_sim("XREG")] = (8.5, 18.0, 0)
    a[by(lambda p: p.sim == "XVREF/XDCO")] = (12.0, 33.0, 0)
    a[by_sim("MRST")] = (18.8, 31.0, 0)
    # ladder column (pairs P4 ... P0 from top) and the expo pair right below the tail
    for k, sim in enumerate(("Q9", "Q7", "Q5", "Q3", "Q1")):
        a[by_sim(sim)] = (31.0, 13.0 + k * 5.4, 0)
    a[by_sim("QEA")] = (31.0, 42.0, 0)
    a[by(lambda p: p.sim == "XINA1/XINA2")] = (43.0, 15.5, 0)
    a[by_sim("QR1")] = (41.5, 29.5, 0)
    a[by(lambda p: p.sim == "XRDIF/XDIF")] = (53.5, 28.5, 0)
    a[by_sim("QA1")] = (53.5, 15.0, 0)
    a[by(lambda p: p.lib_id.endswith("LM324"))] = (54.0, 44.5, 90)
    a[by(lambda p: p.lib_id.startswith("MCU_WCH"))] = (71.0, 17.0, 0)
    a[by(lambda p: p.lib_id == "Isolator:LTV-817S")] = (89.5, 17.5, 0)
    srs = sorted([p.ref for p in D.PARTS if p.lib_id == "74xx:74HC595"], key=lambda r: int(r[1:]))
    for i, r in enumerate(srs):
        a[r] = (68.0 + i * 11.5, 31.5, 90)
    muxes = sorted([p.ref for p in D.PARTS if p.lib_id == "4xxx:4051"], key=lambda r: int(r[1:]))
    for i, r in enumerate(muxes):
        a[r] = (69.0 + i * 15.0, 45.5, 90)
    return a


def block_of(p):
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
        return "mux"
    if p.note == "74HC595 decoupling":
        return "sr"
    if p.note == "output bleeder":
        return "vca"
    return GROUP_BLOCK.get(p.group)
