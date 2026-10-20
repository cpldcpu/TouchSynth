"""Floorplan of the backplane PCB (used by gen_pcb_bp.py; docs/backplane.md sections 6 and 7).

KiCad coordinates: origin at the north-west corner (the rear edge, y = 0), y to the south; backplane.md counts y
from the south edge, so doc y = 100 - KiCad y. The rear edge carries the USB connectors (USB-A J2, USB-C J1)
and SWD J5, the east edge the power entry (JP1, J4), the west edge the line-out jack J3 beside the mixer. The slot
row runs along x at the south: slot k has its socket centre at x = 20 + 10 (k - 1); socket pin 1 at the south-west
corner (KiCad rotation 180), odd pins on the west row. The cards cover KiCad y = 45 ... 95; the card-guide bands (y 42.5-46.5 and 93.5-97.5) stay free of
parts. The controller strip is y = 0 ... 42.

Structured parts get explicit positions (anchors): connectors, ICs, the slot sockets and every slot's 7 mixer
parts and supply capacitor. The rest goes greedily into the blocks below (gen_pcb.greedy_place).

Pre-routes (gen_pcb_bp.py, locked before Freerouting), all on F.Cu unless noted:
- +5 V: trunk down the east margin (x = 97.8, 1.0 mm) from the soft-start bypass, past the two bulk capacitors,
  rail along y = RAIL_Y (0.4 mm) to the mixer, one stub per socket pin 1 / 2 and per slot capacitor.
- voice bus inside the socket field, one track per gap between pin positions (backplane.md 7.3): SYNC gap 4|5,
  BCAST 5|6, RETURN 6|7, CLK 7|8, each with a short jog to its pin.
- audio fan-out per slot: AUDIO_L (pin 5) and AUDIO_R (pin 7) south outside the west row, AUDIO_GND (pin 6)
  between the rows, into the 0805 input capacitors that straddle the rail; on to the 56k resistors and through a
  via each onto the summing band.
- summing band on B.Cu (y 86.75 ... 91.95): L-, L+ | R+, R- with GND guard tracks; bottom pour kept out of it.
"""
import os
from board import D

W, H = 100.0, 100.0
GUIDE = 0.0                                      # gen_pcb.stitch: no card-guide strips along the side edges
LAYERS = int(os.environ.get("BP_LAYERS", "4"))  # 4 (0.3: In1 GND, In2 +3V3 under the strip / GND under the slots)
                                                 # or 2 (outer GND pours only): BP_LAYERS=2 routes the same placement
                                                 # into backplane_2l.kicad_pcb, as a check
STRIP_Y = 42.0                                   # In2 split between the controller strip and the slot area
PLANES_IN2 = {"+3V3@strip": [(0.3, 0.3), (W - 0.3, 0.3), (W - 0.3, STRIP_Y - 0.25), (0.3, STRIP_Y - 0.25)],
              "GND@slots": [(0.3, STRIP_Y + 0.25), (W - 0.3, STRIP_Y + 0.25), (W - 0.3, H - 0.3), (0.3, H - 0.3)]}

SLOT_X = [20.0 + 10.0 * k for k in range(8)]     # socket centre per slot (slot k at SLOT_X[k - 1])
PIN1_Y = 78.9                                    # socket pin 1 (doc y 21.1); positions 2 ... 8 at -2.54 each
RAIL_Y = 82.5                                    # +5 V rail (between the pads of the 0805 input capacitors)
TRUNK_X = 97.8                                   # +5 V trunk down the east margin
RES_Y = 85.8                                     # the per-slot 56k resistors
BAND = {"SUM_LN": 87.6, "SUM_LP": 88.5, "SUM_RP": 90.2, "SUM_RN": 91.1}     # summing band, B.Cu
GUARDS = (86.75, 89.35, 91.95)                   # GND guard tracks around and between the pairs
BAND_X0 = 12.5                                   # west end of the band (vias up to the mixer)
GUIDE_BANDS = ((7.0, 42.5, 93.0, 46.5), (7.0, 93.5, 93.0, 97.5))   # card-guide rails: no parts (holes excepted)
HOLES = ((3.5, 3.5), (96.5, 3.5), (3.5, 96.5), (96.5, 96.5))  # M3 mounting holes (6 mm keep-out)


def gap_y(n):
    """y of the gap between socket pin positions n and n + 1"""
    return PIN1_Y - 2.54 * (n - 0.5)


def pin_xy(k, n):
    """socket pin n of slot k"""
    x = SLOT_X[k - 1] + (-1.27 if n % 2 else 1.27)
    return x, PIN1_Y - 2.54 * ((n + 1) // 2 - 1)


MX, MY = 52.0, 24.4                              # the MCU in the middle of the controller strip
BUS_GAP = {"SYNC": (4, 9), "BCAST": (5, 10), "RETURN": (6, 11), "CLK": (7, 15)}    # net -> (gap, pin)

# per-slot parts: note suffix -> (dx from the socket centre, y, rotation); the 0805 / 0603 pad 1 faces north at 270
SLOT_PARTS = {
    "C_IN_L": (-2.47, RAIL_Y, 270), "C_IN_R": (-4.6, RAIL_Y, 270), "C_G (mirror)": (0.0, RAIL_Y, 270),
    "R_IN_L": (-2.47, RES_Y, 270), "R_IN_R": (-4.6, RES_Y, 270), "R_P_L": (-0.9, RES_Y, 270),
    "R_P_R": (0.9, RES_Y, 270), "supply": (2.7, 84.6, 270),   # supply: south of the rail, pad 1 (+5V) north
}
RES_NET = {"R_IN_L": "SUM_LN", "R_P_L": "SUM_LP", "R_P_R": "SUM_RP", "R_IN_R": "SUM_RN"}

# greedy blocks (x0, y0, x1, y1)
BLOCKS = {                                       # one disjoint region per function across the whole strip
    "leds":    (8.0, 0.5, 22.0, 10.0),            # PWR / ACT LED resistors (reset button between)
    "host":    (26.0, 0.5, 42.2, 13.8),           # USB-A host port (not fitted), west of J2
    "midi":    (1.0, 12.0, 18.0, 42.3),           # MIDI in (not fitted): the north-west corner
    "flash":   (18.0, 10.0, 33.0, 18.4),          # flash pull-ups and decoupling, above U7
    "nrst":    (14.0, 24.8, 33.0, 32.0),          # 595 decoupling and OE pull-up, between U7 and U6
    "mcu":     (33.2, 18.4, 40.6, 36.4),          # reset filter, VDDA ferrite, BOOT0 / BOOT1 pull-downs and the ADC
    "adc":     (33.2, 18.4, 40.6, 36.4),          # dividers: one column west of the crystal (pins 7 ... 11)
    "swio":    (34.0, MY + 12.2, 52.0, 42.3),     # below the MCU's fan-out zone
    "bus":     (52.0, MY + 12.2, 76.0, 42.3),     # bus series resistors, RETURN pull-up, bus test points
    "tps":     (68.0, 20.0, 76.0, 34.0),          # test points of the free MCU pins
    "usbc":    (58.0, 9.0, 82.0, 20.0),           # USB-C passives and ESD, below J1
    "power":   (76.0, 20.0, 96.0, 42.3),          # LDO, bulk, soft start (not fitted), supply test points
    "lineout": (11.6, 47.0, 16.4, 67.0),          # line-out stage beside the jack, toward slot 1
    "mixc":    (1.0, 66.8, 14.6, 93.0),           # summing amps' feedback, VREF filter, rail filter: at U8
    "vref":    (1.0, 66.8, 14.6, 93.0),
}
RESERVED = {"guide_n": GUIDE_BANDS[0], "guide_s": GUIDE_BANDS[1], "slots": (16.5, 46.5, 96.5, 93.5),
            "band_west": (BAND_X0 - 0.9, GUARDS[0] - 0.6, 14.6, GUARDS[-1] + 0.6),      # the band's vias up
            "mcu_ring": (MX - 7.4, MY - 8.5, MX + 11.0, MY + 12.0),   # MCU fan-out: only the anchored decoupling,
                                                                     # the host ESD inside; the crystal and its
                                                                     # load capacitors just west of it
            **{f"hole{i}": (x - 3.4, y - 3.4, x + 3.4, y + 3.4) for i, (x, y) in enumerate(HOLES)}}
SILK = {"title": (34.0, 47.5, 94.0, 52.0)}
USABLE = (0.6, 0.6, W - 0.6, H - 0.6)
STREET = 0.15
BLOCK_CLEARANCE = {"lineout": 0.4, "mixc": 0.5, "vref": 0.5, "host": 0.6, "flash": 0.6, "mcu": 0.8, "adc": 0.8}
CLEARANCE = 1.2                                  # greedy placement: at least this much between part courtyards


def by(pred):
    return [p.ref for p in D.PARTS if pred(p)][0]


def by_note(note):
    return by(lambda p: p.note == note)


def anchors():
    """ref -> (x, y, rot)"""
    a = {"U1": (MX, MY, 0),                      # USBD pins 32/33 east, USBFS 42/43 north, slot lines south
         "J2": (MX + 2.5, 12.0, 180),             # USB-A (not fitted), mouth on the rear edge, above pins 42/43
         "U5": (MX - 0.2, 16.9, 270),             # host ESD on the pair: IO1 (D-) east, IO2 (D+) west
         "J1": (MX + 14.0, 3.675, 180),           # USB-C, mouth on the rear edge (PCB edge line at local y 3.675)
         "J5": (MX + 22.0, 3.0, 90),              # SWD: 3V3, SWDIO, SWCLK, GND from west to east
         "U7": (26.0, 21.5, 0),                   # flash (not fitted) and the 595 west of the MCU
         "U6": (24.0, 36.0, 90),                  # 595: outputs QB ... QH along the south side
         "JP1": (97.6, 25.5, 0), "J4": (97.6, 36.0, 0),   # supply jumper (USB / EXT), external 5 V
         "F1": (93.8, 28.0, 270), "D1": (93.6, 33.8, 270),   # pad 1 north: +5V_SEL -> F1 -> +5V_IN, TVS
         "U2": (89.6, 29.0, 0),                   # LDO (its capacitors target its pins: anchor it)
         "J6": (MX + 14.0, 27.0, 0),              # UART, vertical, east of the MCU
         "J7": (8.0, 30.0, 90),                   # MIDI in (not fitted), north-west
         "JP2": (35.0, 16.0, 90),                 # BOOT0: 3V3 / BOOT0 / GND
         "Y1": (MX - 9.5, MY - 0.2, 90),          # crystal at pins 5 / 6, 2.4 mm fan-out room
         "SW1": (24.0, 4.0, 0),                   # reset button at the rear edge
         "U4": (38.0, 9.0, 0),                    # host switch (not fitted) west of J2
         "J3": (3.3, 60.0, 270),                  # line out on the west edge north of the mixer, mouth west
         "U8": (8.0, 88.0, 0)}
    a[by_note("R_BYP: soft-start bypass, fitted (remove when Q1 is fitted)")] = (94.6, 39.6, 270)   # pad 2 south
    for y, ref in zip((48.9, 53.8), [p.ref for p in D.PARTS if p.note == "slot rail bulk"]):
        a[ref] = (95.7, y, 270)                  # beside the trunk, east of slot 8's card; pad 1 (+5V) north
    rsup = [p.ref for p in D.PARTS if p.sim == "RSUP0"][0]
    a[rsup] = (12.6, RAIL_Y, 180)                # west end of the +5 V rail: pad 1 (+5V) east
    # MCU decoupling right at its supply pins (relative to U1: VDD 48 / VSS 47 top left, VBAT 1, VDD 36 / VSS 35
    # right, VDD 24 / VSS 23 bottom, VDDA 9 / VSSA 8 left below the crystal); pad 1 (+3V3 / VDDA) toward the pin
    for note, (dx, dy, rot) in (("MCU decoupling VDD pin 48", (-5.2, -6.6, 180)),     # about 1 mm of fan-out room; pin 48
                                                                                     # cap west: a channel to U5 for pins 44-46
                                ("MCU decoupling VBAT", (-7.6, -4.8, 180)),           # between the pins and the caps
                                ("MCU decoupling VDD pin 36", (7.4, -3.0, 270)),
                                ("MCU decoupling VDD pin 24", (2.6, 7.4, 180)), ("VDDA", (-8.2, 5.0, 180))):
        a[[p.ref for p in D.PARTS if p.note == note and p.pins["1"] != "VDDA" or
           (note == "VDDA" and p.note == note and p.value == "100n")][0]] = (MX + dx, MY + dy, rot)
    a[[p.ref for p in D.PARTS if p.note == "VDDA" and p.value == "1µ"][0]] = (MX - 11.4, MY + 5.0, 180)
    for note, x in (("power", 14.0), ("activity", 17.0), ("host port fault", 32.0), ("host port powered", 35.0)):
        a[by(lambda p, n=note: p.lib_id == "Device:LED" and p.note == n)] = (x, 2.0, 270)
    # effects slot (slot 1 pins 15 / 14): the 0 R / 220 R pairs above the line-out stage, west of socket 1; 0 R
    # pad 1 (CLK, SWIO_1) north, 220 R pad 1 (MIX_L, MIX_R) south toward the line-out stage
    for note, (x, y, rot) in (("effects slot: CLK to slot 1 pin 15", (14.5, 53.2, 270)),
                              ("effects slot: send L to slot 1 pin 15", (12.5, 53.2, 90)),
                              ("effects slot: SWIO_1 to slot 1 pin 14", (14.5, 49.3, 270)),
                              ("effects slot: send R to slot 1 pin 14", (12.5, 49.3, 90)),
                              ("effects slot: return L", (10.4, 49.3, 270)),      # loop-through returns: north of
                              ("effects slot: return R", (8.4, 49.3, 270))):      # the jack, LO_L / LO_R pad south
        a[by(lambda p, n=note: p.note and p.note.startswith(n))] = (x, y, rot)
    for k in range(1, 9):
        x = SLOT_X[k - 1]
        a[f"J{9 + k}"] = (x - 1.27, PIN1_Y, 180)
        for suffix, (dx, y, rot) in SLOT_PARTS.items():
            note = f"slot {k} {suffix}" if suffix != "supply" else f"slot {k} supply"
            a[by_note(note)] = (x + dx, y, rot)
    return a


GROUP_BLOCK = {
    "Power entry: USB-C VBUS or external 5 V (JP1), polyfuse, TVS": "power",
    "3.3 V for the controller and the logic": "power",
    "Slot rail: soft start (option, not fitted) bridged by 0 R": "power",
    "USB-C device port (USBD: MIDI, CDC)": "usbc",
    "USB-A host port (USBFS: class-compliant MIDI keyboards), 0.5 A switch": "host",
    "CH32V203C8T6 (hand-soldered), decoupling, reset": "mcu",
    "8 MHz crystal (PLL x 18 = 144 MHz)": "mcu",
    "Programming: SWD (WCH-LinkE), BOOT0, USART1 (bootloader, debug)": "mcu",
    "MIDI DIN in (option, not fitted): opto into PA10 through JP3": "midi",
    "SPI flash (footprint only), activity LED, free pins": "flash",
    "Bus drivers: broadcast, return, SYNC, 24 MHz clock (option)": "bus",
    "NRST: 74HC595 drives each card's NRST directly (outputs off at reset: the cards run freely)": "nrst",
    "SWIO pull-ups (1 k each: the one-wire protocol samples 0.6 us after an edge)": "swio",
    "Slot sockets (2 x 8 female, vertical; card part side faces west)": "bus",
    "Op-amp rail and VREF 2.41 V (divider from the controller's +3V3, two RC stages, unbuffered)": "mixc",
    "Summing amplifiers (inverting, + side mirrored to VREF): out = VREF - 0.357 x sum(AUDIO_x - AUDIO_GND)": "mixc",
    "Line out (3.5 mm stereo) and ADC taps (USB audio)": "lineout",
}
NOTE_BLOCK = {"VREF": "vref", "power LED series": "leds", "activity LED series": "leds", "fault LED series": "host",
              "host power LED series": "host", "PB2 = BOOT1": "mcu", "ADC": "adc", "VBUS sense": "usbc",
              "free MCU pin": "tps"}
TP_BLOCK = {"+3V3": "power", "+5V": "power", "GND": "power", "SYNC": "bus", "BCAST": "bus", "RETURN": "bus",
            "VREF": "vref", "MIX_L": "mixc", "MIX_R": "mixc"}
DEC = {"MCU decoupling VDD pin 24": ("U1", "24"), "MCU decoupling VDD pin 36": ("U1", "36"),
       "MCU decoupling VDD pin 48": ("U1", "48"), "MCU decoupling VBAT": ("U1", "1"), "VDDA": ("U1", "9"),
       "reset filter": ("U1", "7"), "595 decoupling": ("U6", "16"), "flash decoupling": ("U7", "8"),
       "LDO input": ("U2", "3"), "LDO output": ("U2", "2"), "+3V3 bulk": ("U2", "2"), "+5V_IN bulk": ("U2", "3"),
       "host switch input": ("U4", "5"), "host VBUS": ("U4", "1")}


def place_rect(blk):
    x0, y0, x1, y1 = BLOCKS[blk]
    return (x0 + STREET, y0 + STREET, x1 - STREET, y1 - STREET)


def dec_ic(p):
    if p.note in DEC:
        return DEC[p.note][0]
    if p.note and p.note.startswith("decoupling "):
        return p.note.split()[1]
    if p.note == "crystal load":
        return "Y1"
    return None


def dec_pin(p):
    if p.note in DEC:
        return DEC[p.note][1]
    if p.note == "crystal load":
        return {"OSC_IN": "1", "OSC_OUT": "2"}[p.pins["1"]]
    return None


def block_of(p):
    if p.lib_id == "Connector:TestPoint":
        if p.note == "free MCU pin":
            return "tps"
        return TP_BLOCK.get(p.pins["1"], "mcu" if p.sheet == "mcu" else None)
    if p.sim and p.sim[:3] in ("RA1", "RA2") or (p.sim or "").startswith("CA"):
        return "adc"                              # ADC dividers at the MCU (backplane.md 5)
    for k, b in NOTE_BLOCK.items():
        if p.note and p.note.startswith(k):
            return b
    if p.note and p.note.startswith("decoupling "):
        return None
    if p.group == "SPI flash (footprint only), activity LED, free pins" and p.pins.get("1", "").startswith("LED"):
        return "leds"
    return GROUP_BLOCK.get(p.group)
