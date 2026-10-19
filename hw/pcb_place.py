"""Signal-flow floorplan of the voice card PCB (used by gen_pcb.py; docs/spec.md 3.3, card format).

Board W x H, top edge (y = 0) = debug edge: LEDs, programming header J2 (left, above the MCU) and line-out header
J3 (right: L, R, GND); bottom edge = backplane connector J1 (2x8 right-angle, pins protruding past the edge). Both
side edges keep GUIDE mm free of parts for the card guides. From bottom to top: analog core and outputs, ladder, MCU,
DAC filter, references and supply input, LEDs and headers.

Anchors (connectors, ICs, transistor pairs) get explicit positions. Every other part is assigned to a block
rectangle and placed greedily (gen_pcb.greedy_place): parts most connected to what is already placed go first, each
to the free spot in its block that minimises the distance from its pads to the pads it connects to.

J1 seen from the top with its body at the bottom edge has pin 1 on the right: the right half of J1 carries the
supply and the audio (pins 1-8: AUDIO_L pin 5, AUDIO_R pin 7), the left half the voice bus (pins 9-16). So the
analog core, the outputs and the supply input sit on the right, the bus and the MCU on the left. The stereo pan
stage (S13 variant A) sits with the VCA: the steering pairs on the VCA pair's collectors, the R difference amp and
both output stages in the corner beside J1 pins 1-8; the pan PWM's RC (PC5) at the MCU.
"""
from board import D

W, H = 50.0, 50.0
GUIDE = 1.5                                      # free of parts along both side edges (card guides)
XL, XR = GUIDE, W - GUIDE

# ---- floorplan (y down from the debug edge)
#   y  0 ...  6.4  debug edge: LEDs, J2 (programming, above the MCU), title, J3 (line out L / R)
#   y  6.4 ... 21  MCU (left), RC stages at the PWM pins, DAC filter + VREF op-amp, references, supply input
#   y 21 ... 30.5  bias chain + ladder (input stage left, output stage right), INA, resonance VCA
#   y 30.5 ... 44  LM324 with the expo pair and both V-to-I transistors around it, CV filters (left); VCA core,
#                  steering pairs and pan bias (centre); difference amps L (right)
#   y 41.5 ... 50  bus parts (left of J1), J1, R difference amp and both output stages (right of J1)
BLOCKS = {
    "top":    (XL, 0.3, 39.5, 6.4),
    "mcu":    (XL, 6.4, 14.5, 21.0),
    "pwm":    (14.5, 6.4, 21.0, 21.0),
    "dac":    (21.0, 6.4, 28.5, 21.0),
    "ref":    (28.5, 6.4, 37.0, 19.0),
    "pwr":    (37.0, 6.4, XR, 21.0),           # LDO, supply input (RFILT, 3 x 100 uF), programmer diode
    "ladder": (XL, 21.0, 27.5, 30.5),
    "ina":    (27.5, 19.0, 35.0, 30.5),
    "res":    (35.0, 21.0, XR, 30.5),
    "cv":     (XL, 30.5, 7.0, H - 1.3),        # CV filters down the left edge beside the LM324, into the corner
    "lm":     (XL, 30.5, 21.0, 41.4),          # LM324 with the expo pair and both V-to-I transistors
    "vca":    (21.0, 30.5, 36.0, 42.0),        # VCA core, steering pairs, VCA base bias, pan bias end
    "dif":    (36.0, 30.5, XR, 41.2),          # difference amps (resonance, VCA L), output stage L
    "out":    (35.6, 41.2, XR, H - 0.3),        # R difference amp, output stage R (corner beside J1 pins 1-8)
    "bus":    (XL, 41.4, 15.4, H - 1.3),       # bottom 1 mm: the SWIO edge track (F.Cu)
}
RESERVED = {}
# silkscreen kept free of parts: title at the debug edge, LED names below the LEDs
SILK = {
    "title": (19.8, 0.3, 39.2, 3.4),
    "leds":  (XL, 2.1, 11.6, 3.0),
}
USABLE = (XL, 0.3, XR, H - 0.3)                  # spill-over area for every block
STREET = 0.15                                    # parts keep this far off the block edges

# In2.Cu supply planes: "NET@region" -> polygon (0.5 mm gaps). +3V3 under the MCU and the debug edge, +5V in a
# strip along the right edge (part-free card-guide strip), along the bottom edge and up to J1 pin 2, VA under the
# analog part.
_T, _M, _S = 6.9, 21.25, 46.8                    # +3V3 band bottom, MCU area bottom, +5V strip left edge
PLANES_IN2 = {
    "+3V3@digital": [(0.3, 0.3), (_S - 0.5, 0.3), (_S - 0.5, _T), (15.0, _T), (15.0, _M), (0.3, _M)],
    "+5V@edge": [(_S, 0.3), (W - 0.3, 0.3), (W - 0.3, H - 0.3), (32.6, H - 0.3), (32.6, 44.9), (35.2, 44.9),
                 (35.2, 48.2), (_S, 48.2)],
    "VA@analog": [(15.5, _T + 0.5), (_S - 0.5, _T + 0.5), (_S - 0.5, 47.7), (35.7, 47.7), (35.7, 44.4),
                  (32.1, 44.4), (32.1, H - 0.3), (0.3, H - 0.3), (0.3, _M + 0.5), (15.5, _M + 0.5)],
}


def by_sim(sim):
    for p in D.PARTS:
        if p.sim and sim in p.sim.split("/"):
            return p.ref
    raise KeyError(sim)


def by(pred):
    return [p.ref for p in D.PARTS if pred(p)][0]


def j1_pin1():
    """J1 origin (pin 1): the body's outer face (6.58 mm from the pin-1 row) flush with the bottom edge"""
    return W / 2 + 3.5 * 2.54, H - 6.58


J2_X, J3_X = 13.2, 41.4                          # pin 1 of the debug-edge headers (pins 2.54 mm to the right)
HDR_Y = 4.04


def anchors():
    """ref -> (x, y, rot)"""
    a = {}
    a[by(lambda p: p.value == "BACKPLANE")] = (*j1_pin1(), 270)            # body down, pin 1 on the right
    a[by(lambda p: p.value == "SWIO")] = (J2_X, HDR_Y, 90)                 # body up, pin 1 on the left
    a[by(lambda p: p.value == "LINE OUT")] = (J3_X, HDR_Y, 90)
    for k, note in enumerate(("power", "playing", "status")):
        a[by(lambda p, n=note: p.lib_id == "Device:LED" and p.note == n)] = (3.2 + 3.1 * k, 1.25, 0)
    a[by(lambda p: p.lib_id.startswith("MCU_WCH"))] = (9.5, 13.8, 0)       # PWM pins (11-20) face right
    a[by(lambda p: p.sim == "XVREF/XSK")] = (25.5, 13.5, 180)              # unit B (filter) faces the MCU
    a[by(lambda p: p.sim == "XINA1/XINA2")] = (31.2, 25.8, 270)            # inputs at the ladder end
    a[by(lambda p: p.sim == "XRDIF/XDIF")] = (41.0, 35.2, 180)           # VCA L unit left, resonance unit right
    a[by(lambda p: p.sim == "XDIFR/XSPR")] = (43.0, 45.7, 0)              # R unit (pins 1-3) faces the VCA
    a[by(lambda p: p.lib_id.endswith("LM324"))] = (12.0, 37.4, 90)        # units D (RES), C (expo) on top, B (VCA)
    a[by(lambda p: p.lib_id.startswith("Regulator_Linear"))] = (44.5, 12.0, 0)   # bottom right
    a[by(lambda p: p.lib_id.startswith("Reference_Voltage"))] = (33.0, 10.5, 0)
    for k, sim in enumerate(("Q1", "Q3", "Q5", "Q7", "Q9")):              # ladder row, input stage on the left
        a[by_sim(sim)] = (6.8 + 4.9 * k, 25.8, 0)                    # room for a via between pairs
    a[by_sim("QEA")] = (14.6, 32.4, 0)                                     # above the expo unit (pins 8-10)
    a[by_sim("QVR")] = (8.6, 31.9, 0)                                      # above the RES unit (pins 12-14)
    a[by_sim("QVV")] = (19.0, 39.6, 0)                                     # right of the VCA unit (pins 5-7)
    a[by_sim("QR1")] = (39.5, 25.8, 0)
    a[by_sim("QA1")] = (28.4, 36.4, 90)                                    # VCA pair: C1 top left, C2 bottom right
    a[by_sim("QSL1")] = (25.6, 33.4, 0)                                    # steering pair 1: emitters at C1
    a[by_sim("QSL2")] = (31.4, 39.2, 0)                                    # steering pair 2: emitters at C2
    return a


GROUP_BLOCK = {
    "5 V input, analog rail, 3.3 V for the MCU": "pwr",
    "References: VREF 2.5 V (CJ431, buffered), VBIAS 1.0 V (LM324 follower), VEXP_REF 1.25 V": "ref",
    "Ladder bias chain": "ladder",
    "MCU (CH32V006F8P7, hand-soldered)": "mcu",
    "Backplane connector and voice bus": "mcu",
    "Programming (WCH-LinkE) and line out": "top",
    "LEDs (debug edge)": "top",
    "Options (not fitted)": "mcu",
    "Reconstruction filter (2-pole Sallen-Key, Butterworth, 31 kHz, C0G)": "dac",
    "Dual-PWM option: low byte (TIM2 CH4) into the filter input, 1.33 MΩ = 120.9 x 11k (overlap, spec 3.5)": "pwm",
    "Mixer into the ladder input": "ladder",              # DAC_F (low impedance) runs, not BIN1
    "CV_CUT filter and exponential converter": "lm",
    "Transistor ladder (4 poles)": "ladder",
    "Output instrumentation amplifier (G = 11)": "ina",
    "CV_RES filter and V-to-I converter": "cv",
    "Resonance VCA and difference amplifier": "res",
    "CV_VCA filter and V-to-I converter": "cv",
    "VCA trim (TIM1 CH1 PWM, 2-pole RC, 680k into vin2)": "pwm",   # VTRIM (1 uF) runs, not the PWM
    "VCA core": "vca",
    "Pan: steering pairs on the VCA collectors, pan bias from PC5 (TIM2 CH1)": "vca",
    "Difference amplifiers (resonance, VCA L), line out L": "dif",
    "R difference amplifier (G = 3.0), line out R": "out",
    "Audio loopback to PC4 (ADC A2)": "mcu",              # ADC_AUDIO runs (RLB1 stays at VCAOUT: SIM_BLOCK)
}
# per-part overrides (by sim name): first RC stage at the PWM pin, parts that belong to another block electrically
SIM_BLOCK = {
    "R1C": "pwm", "C1C": "pwm", "R1R": "mcu", "C1R": "mcu", "R1V": "pwm", "C1V": "pwm",     # PWM_RES: pin 10, left
    "RSK1": "pwm", "RPB": "pwm", "RPC": "pwm",           # pan: PWM and +3V3 legs at PC5, PAN_B (1 uF end) runs
    "R2C": "cv", "C2C": "cv",
    "REVR": "lm", "RBVR": "lm", "REVV": "lm", "RBVV": "lm", "ROFFV": "lm",
    "RBA": "ref", "RBB": "ref", "R25A": "ref", "R25B": "ref",    # VBIAS / VEXP_REF dividers at VREF, their 1 uF
    "CBI": "lm", "C25": "lm",                                    # at the LM324 inputs (the DC node runs)
    "R33X": "lm", "R12X": "lm", "C12X": "lm", "RREF": "lm", "REXP": "lm", "CEXP": "lm",
    "RRF": "ladder", "CRF": "ladder", "COUT": "dif", "RBL": "dif", "RISO": "dif", "RLB1": "dif",
    "RFILT": "pwr", "XVREF": "dac",
}
NOTE_BLOCK = {"programmer 5 V": "pwr", "LDO input": "pwr", "LDO output": "pwr", "bus series": "bus",
              "MCU decoupling": "mcu", "MCU bulk": "mcu", "LM324 decoupling": "lm", "output bleeder": "out",
              "isolates the op-amp": "out", "option: R into the loopback": "out"}
_DEC_KIND = {"MCU decoupling": lambda q: q.lib_id.startswith("MCU_WCH"),
             "MCU bulk": lambda q: q.lib_id.startswith("MCU_WCH"),
             "LM324 decoupling": lambda q: q.lib_id.endswith("LM324"),
             "LDO input": lambda q: q.lib_id.startswith("Regulator_Linear"),
             "LDO output": lambda q: q.lib_id.startswith("Regulator_Linear")}

# long digital lines along the edges, pre-routed and locked before Freerouting: net -> (layer, points) runs, joined
# by vias where the layer changes; (value, pin) is a connector pad. SWIO: J1 pin 14 under the J1 body (F.Cu) to the
# corner, up the left edge (B.Cu) to the programming header's pin 2.
EDGE_ROUTES = {
    "SWIO": [("F.Cu", [("BACKPLANE", "14"), (18.65, 49.2), (2.0, 49.2)]),
             ("B.Cu", [(2.0, 49.2), (2.0, 5.75), (J2_X + 2.54, 5.75), ("SWIO", "2")])],
}


# nets routed around the board interior (maze router, locked; the rectangle is a temporary keep-out on both outer
# layers). Tried for the loopback {"ADC_AUDIO": (14.5, 8.2, 45.6, 48.5)}: the 50 x 50 mm board then leaves nets open;
# Freerouting takes it up the right edge and across the reference row, clear of the ladder.
CORRIDORS = {}

# short analog links routed first (maze router, locked) so Freerouting cannot detour them: the VCA collectors into
# the emitters of the steering pairs (diagonal pads of the SOT-363). More nets here (the expo and V-to-I feedback
# nodes) crowd the LM324 area and leave nets open.
PRE_ROUTE = ("VCA_C1", "VCA_C2")
# analog nets re-routed once more after routing (gen_pcb.py --polish) when the repair rounds left them long
POLISH = ("PAN_B", "VCA_R1", "VCA_R2", "VIV_E", "VEXP_REF", "VBIAS_DIV", "VTRIM", "CVV_A", "RESOUT", "VREF")


def place_rect(blk):
    x0, y0, x1, y1 = BLOCKS[blk]
    return (x0 + STREET, y0 + STREET, x1 - STREET, y1 - STREET)


def dec_ic(p):
    """ref of the IC a decoupling capacitor belongs to (the +3V3 test point: the LDO)"""
    if p.lib_id == "Connector:TestPoint" and p.pins["1"] == "+3V3":
        return by(lambda q: q.lib_id.startswith("Regulator_Linear"))
    if not p.note:
        return None
    if p.note.startswith("decoupling "):
        return p.note.split()[1]
    if p.note in _DEC_KIND:
        return [q.ref for q in D.PARTS if _DEC_KIND[p.note](q)][0]
    return None


def block_of(p):
    if p.lib_id == "Connector:TestPoint":
        return tp_block(p)
    return _block_of(p)


TP_BLOCK = {"+3V3": "pwr", "VA": "top", "GND": "top", "VREF": "vca", "SWIO": "mcu", "NRST": "mcu", "VCAOUT": "dif",
            "VCAR_OUT": "out"}


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
        if b is None and dec_ic(q):
            b = _block_of([r for r in D.PARTS if r.ref == dec_ic(q)][0])
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
    for k, b in NOTE_BLOCK.items():
        if p.note and p.note.startswith(k):
            return b
    return GROUP_BLOCK.get(p.group)
