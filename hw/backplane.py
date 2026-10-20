"""TouchSynth Poly backplane: controller (CH32V203), power, USB device and host, voice bus, 8 slots, stereo mixer.

Single source of truth for schematic and PCB, following docs/backplane.md (proposal 0.2): pin map (section 3.2),
NRST through a 74HC595 (3.5), power path with the soft start as an unfitted option (4.1), host port (4.2), the S12
two-bus mixer (5), connectors (6.4), SPI flash footprint (6.5). The mixer parts carry their ngspice names from S12
(sim/s12_mixer/s12_mixer.py --bus2, build2() copy 0); check_sim.py compares the two.

Supplies: VBUS_C (USB-C) or +5V_EXT (J4), chosen by JP1, through F1 to +5V_IN; +5V (the slot rail) behind the
0 R bypass of the soft-start switch; +3V3 from an XC6206 for the MCU and logic; VDDA behind a ferrite; VA_MIX the
mixer op-amp rail (47 R + 22 uF from +5V); VBUS_HOST behind the current-limited switch.
"""
from collections import OrderedDict
import lcsc as L

PROJECT = "backplane"
TITLE = "TouchSynth Poly backplane"
REV = "0.1"
COPPER_LAYERS = 4                               # backplane.md 7.1 (fab.py: gerber layer list); as pcb_place_bp.LAYERS
POWER = {"GND": "power:GND", "+5V": "power:+5V", "+3V3": "power:+3V3"}
RAIL = "+5V_IN"                                 # always a global label (input rail ahead of the slot rail)
FLAG_SHEETS = {"power": ("GND", "VBUS_C", "+5V_EXT", "+5V_IN", "+5V"),   # PWR_FLAGs: supplies no power-output
               "mcu": ("VDDA",), "mixer": ("VA_MIX",)}                 # pin drives (+3V3: LDO, VBUS_HOST: U4)
FLAGS = sum(FLAG_SHEETS.values(), ())
LAYOUTS = "layouts_backplane"                   # hand-drawn sheet layouts (power, mcu, bus, mixer)
SLOTS = 8
FX_SLOT = 1                    # the effects slot (pins 15 / 14 switchable to the mix sends, end of file)

SHEETS = OrderedDict([
    ("power", "Power entry, 3.3 V, soft start (option), USB-C device port, USB-A host port"),
    ("mcu", "Controller CH32V203, clock, programming, UART, MIDI in (option), SPI flash (option), LEDs"),
    ("bus", "Voice bus, NRST shift register, SWIO pull-ups, slot sockets"),
    ("mixer", "Two-bus stereo mixer (S12), line out, ADC taps"),
])

FP = dict(
    R0603="Resistor_SMD:R_0603_1608Metric", C0603="Capacitor_SMD:C_0603_1608Metric",
    C0805="Capacitor_SMD:C_0805_2012Metric", C1206="Capacitor_SMD:C_1206_3216Metric",
    R1206="Resistor_SMD:R_1206_3216Metric", RN4="Resistor_SMD:R_Array_Convex_4x0603",
    SOT23="Package_TO_SOT_SMD:SOT-23", SOT235="Package_TO_SOT_SMD:SOT-23-5", SOT236="Package_TO_SOT_SMD:SOT-23-6",
    SO8="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", SO8W="Package_SO:SOIC-8_5.3x5.3mm_P1.27mm",
    SO16="Package_SO:SOIC-16_3.9x9.9mm_P1.27mm", LQFP48="Package_QFP:LQFP-48_7x7mm_P0.5mm",
    LED="LED_SMD:LED_0603_1608Metric", SOD123="Diode_SMD:D_SOD-123", SMA="Diode_SMD:D_SMA",
    FUSE="Fuse:Fuse_1206_3216Metric", FB="Inductor_SMD:L_0603_1608Metric",
    XTAL="Crystal:Crystal_SMD_5032-2Pin_5.0x3.2mm", OPTO="Package_DIP:SMDIP-4_W9.53mm",
    SW="Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", TP="TestPoint:TestPoint_Pad_D1.0mm",
    USBC="Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
    USBA="Connector_USB:USB_A_Molex_67643_Horizontal", JACK="Connector_Audio:Jack_3.5mm_CUI_SJ1-3523N_Horizontal",
    SOCK="Connector_PinSocket_2.54mm:PinSocket_2x08_P2.54mm_Vertical",
    HDR2="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    HDR3="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
    HDR4="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
)


class Part:
    def __init__(self, ref, lib_id, value, fp, pins, sheet, lcsc=None, dnp=False, bom=True, sim=None, note=None):
        self.ref, self.lib_id, self.value, self.fp, self.pins = ref, lib_id, value, fp, pins
        self.sheet, self.lcsc, self.dnp, self.bom, self.sim, self.note = sheet, lcsc, dnp, bom, sim, note
        self.unit_sheets = {}          # unit number -> sheet (for op-amp units used in several blocks)
        self.group = _group
        self.unit_groups = {}          # unit number -> group heading on that sheet


PARTS = []
_count = {}
_fixed = set()                         # references given explicitly (connectors, ICs: the names of backplane.md)
_sheet = None
_group = None


def sheet(name):
    global _sheet
    _sheet = name


def group(name):
    """Start a named sub-block (drawn as its own row group with a heading)."""
    global _group
    _group = name


def _ref(prefix):
    while True:
        _count[prefix] = _count.get(prefix, 0) + 1
        r = f"{prefix}{_count[prefix]}"
        if r not in _fixed:
            return r


def add(prefix, lib_id, value, fp, pins, ref=None, **kw):
    if ref:
        assert ref not in {p.ref for p in PARTS}, ref
        _fixed.add(ref)
    p = Part(ref or _ref(prefix), lib_id, value, fp, {str(k): v for k, v in pins.items()}, _sheet, **kw)
    PARTS.append(p)
    return p


# references fixed by docs/backplane.md (reserved before any automatic numbering)
_fixed |= {f"U{i}" for i in range(1, 10)} | {f"J{i}" for i in list(range(1, 8)) + list(range(10, 18))} | \
    {"JP1", "JP2", "JP3", "F1", "D1", "Q1", "Y1", "SW1"}


def R(sim, value, a, b, pkg="0603", **kw):
    code, pkg = L.pick_r(value, pkg)
    return add("R", "Device:R", value, FP["R" + pkg], {1: a, 2: b}, lcsc=code, sim=sim, **kw)


def C(sim, value, a, b, vwork, tc=None, pkgs=("0603", "0805", "1206"), **kw):
    code, pkg = L.pick_c(value, 2 * vwork, pkgs=pkgs, tc=tc)
    return add("C", "Device:C", value.replace("u", "µ"), FP["C" + pkg], {1: a, 2: b}, lcsc=code, sim=sim, **kw)


def RN(value, lcsc, pairs, note=None):
    """4 x 0603 resistor array (convex): pairs = [(a, b)] * 4 for R1 ... R4."""
    pins = {}
    for k, (a, b) in enumerate(pairs):
        pins[1 + k], pins[8 - k] = a, b
    return add("RN", "Device:R_Pack04", value, FP["RN4"], pins, lcsc=lcsc, note=note)


def LED(color, a, k, note, **kw):
    return add("D", "Device:LED", color, FP["LED"], {2: a, 1: k}, lcsc={"red": "C2286", "yellow": "C89811"}[color],
               note=note, **kw)


def MCP6002(ref, sim, a, b, note=None):
    """a, b = (in+, in-, out) for units A and B; powered from VA_MIX, 100 nF decoupling."""
    p = add("U", "Amplifier_Operational:MCP6002-xSN", "MCP6002", FP["SO8"],
            {3: a[0], 2: a[1], 1: a[2], 5: b[0], 6: b[1], 7: b[2], 8: "VA_MIX", 4: "GND"}, ref=ref, lcsc="C7377",
            sim=sim, note=note)
    C(None, "100n", "VA_MIX", "GND", 5, note=f"decoupling {ref}")
    return p


def TP(net, note=None):
    return add("TP", "Connector:TestPoint", net, FP["TP"], {1: net}, bom=False, note=note)


def HDR(ref, n, value, pins, note=None, dnp=False):
    return add("J", f"Connector_Generic:Conn_01x{n:02d}", value, FP[f"HDR{n}"], dict(enumerate(pins, 1)), ref=ref,
               bom=False, note=note, dnp=dnp)


# =========================================================================== power, USB ports
sheet("power")
group("Power entry: USB-C VBUS or external 5 V (JP1), polyfuse, TVS")
HDR("J4", 2, "EXT 5V", ("+5V_EXT", "GND"), note="external 5 V, >= 1 A adapter (hand-soldered)")
add("JP", "Jumper:Jumper_3_Open", "SUPPLY", FP["HDR3"], {1: "VBUS_C", 2: "+5V_SEL", 3: "+5V_EXT"}, ref="JP1",
    bom=False, note="1-2: USB-C, 2-3: external 5 V (no diode drop)")
add("F", "Device:Polyfuse", "0.75A", FP["FUSE"], {1: "+5V_SEL", 2: "+5V_IN"}, ref="F1", bom=False,
    note="PTC, I_hold 0.75 A, I_trip 1.5 A (e.g. Bourns MF-MSMF075), hand-soldered: not on the lists")
add("D", "Device:D_Zener", "SMAJ5.0A", FP["SMA"], {1: "+5V_IN", 2: "GND"}, ref="D1", lcsc="C2925443",
    note="unidirectional TVS: overvoltage or a reversed supply makes F1 trip")
C(None, "10u", "+5V_IN", "GND", 5, note="+5V_IN bulk")
group("3.3 V for the controller and the logic")
add("U", "Regulator_Linear:XC6206PxxxMR", "XC6206P332MR", FP["SOT23"], {3: "+5V_IN", 2: "+3V3", 1: "GND"},
    ref="U2", lcsc="C5446")
C(None, "1u", "+5V_IN", "GND", 5, note="LDO input")
C(None, "1u", "+3V3", "GND", 3.3, note="LDO output")
C(None, "10u", "+3V3", "GND", 3.3, note="+3V3 bulk")
R(None, "2.2k", "+3V3", "LED_PWR_A", note="power LED series")
LED("red", "LED_PWR_A", "GND", "power")
group("Slot rail: soft start (option, not fitted) bridged by 0 R")
R(None, "0", "+5V_IN", "+5V", pkg="1206", note="R_BYP: soft-start bypass, fitted (remove when Q1 is fitted)")
add("Q", "Transistor_FET:AO3401A", "AO3401A", FP["SOT23"], {1: "SS_G", 2: "+5V_IN", 3: "+5V"}, ref="Q1",
    lcsc="C15127", dnp=True, note="P-channel soft start, about 40 ms ramp (hand estimate; simulate first: S14)")
R(None, "1M", "+5V_IN", "SS_G", dnp=True, note="soft start R_GS")
R(None, "220k", "SS_G", "GND", dnp=True, note="soft start R_G")
C(None, "100n", "SS_G", "+5V", 5, dnp=True, note="soft start C_GD")
C(None, "47u", "+5V", "GND", 5, note="slot rail bulk")
C(None, "47u", "+5V", "GND", 5, note="slot rail bulk")

group("USB-C device port (USBD: MIDI, CDC)")
add("J", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C", FP["USBC"],
    {"A1": "GND", "B1": "GND", "A12": "GND", "B12": "GND", "A4": "VBUS_C", "A9": "VBUS_C", "B4": "VBUS_C",
     "B9": "VBUS_C", "A5": "CC1", "B5": "CC2", "A6": "USBC_DP", "B6": "USBC_DP", "A7": "USBC_DM", "B7": "USBC_DM",
     "A8": "NC_SBU1", "B8": "NC_SBU2", "SH": "GND"}, ref="J1", bom=False, note="GCT USB4105, hand-soldered")
R(None, "5.1k", "CC1", "GND", note="sink: CC1")
R(None, "5.1k", "CC2", "GND", note="sink: CC2")
add("U", "Power_Protection:SRV05-4", "SRV05-4", FP["SOT236"],
    {1: "USBC_DM", 3: "USBC_DP", 4: "CC1", 6: "CC2", 5: "VBUS_C", 2: "GND"}, ref="U3", lcsc="C7420376",
    note="ESD on D-, D+, CC1, CC2 (SRV05-4A C20615829 was nearly out of stock on 2026-10-20)")
R(None, "0", "USBC_DM", "USBD_DM", note="D- series position")
R(None, "0", "USBC_DP", "USBD_DP", note="D+ series position")
R(None, "1.5k", "USBD_DP", "+3V3", dnp=True, note="D+ pull-up option (the USBD pull-up is expected inside)")
R(None, "22k", "VBUS_C", "VBUS_DET", note="VBUS sense: 3.0 V at 5.0 V")
R(None, "33k", "VBUS_DET", "GND", note="VBUS sense divider")

group("USB-A host port (USBFS: class-compliant MIDI keyboards), 0.5 A switch")
HOST = dict()                  # host port fitted (user decision 2026-10-20; 2026-10-19: not fitted); U4, J2 by hand
add("U", "Power_Management:TPS2051CDBV", "TPS2051C", FP["SOT235"],
    {5: "+5V_IN", 1: "VBUS_HOST", 2: "GND", 4: "HOST_EN", 3: "HOST_FLT_N"}, ref="U4", bom=False, **HOST,
    note="0.5 A current-limited switch, enable active high, open-drain fault; hand-soldered: not on the lists")
C(None, "1u", "+5V_IN", "GND", 5, note="host switch input", **HOST)
C(None, "47u", "VBUS_HOST", "GND", 5, note="host VBUS", **HOST)
C(None, "47u", "VBUS_HOST", "GND", 5, note="host VBUS", **HOST)
R(None, "100k", "HOST_EN", "GND", note="host port off until the firmware enables it", **HOST)
R(None, "10k", "HOST_FLT_N", "+3V3", note="fault pull-up", **HOST)
R(None, "1k", "+3V3", "LED_FLT_A", note="fault LED series", **HOST)
LED("red", "LED_FLT_A", "HOST_FLT_N", "host port fault", **HOST)
R(None, "2.2k", "VBUS_HOST", "LED_HOST_A", note="host power LED series", **HOST)
LED("yellow", "LED_HOST_A", "GND", "host port powered", **HOST)
add("J", "Connector:USB_A", "USB-A", FP["USBA"], {1: "VBUS_HOST", 2: "USBH_DM", 3: "USBH_DP", 4: "GND", "SH": "GND"},
    ref="J2", bom=False, **HOST, note="right-angle THT receptacle, hand-soldered")
add("U", "Power_Protection:SRV05-4", "SRV05-4", FP["SOT236"],
    {1: "USBH_DM", 3: "USBH_DP", 4: "NC_ESD3", 6: "NC_ESD4", 5: "VBUS_HOST", 2: "GND"}, ref="U5", lcsc="C7420376",
    note="ESD on the host D-, D+", **HOST)
R(None, "15k", "USBH_DM", "GND", dnp=True, note="host pull-down option (USBFS pull-downs expected inside)")
R(None, "15k", "USBH_DP", "GND", dnp=True, note="host pull-down option")

# =========================================================================== controller
sheet("mcu")
group("CH32V203C8T6 (hand-soldered), decoupling, reset")
MCU = {1: "+3V3", 2: "SR_LATCH", 3: "SR_OE_N", 4: "PC15", 5: "OSC_IN", 6: "OSC_OUT", 7: "MCU_NRST", 8: "GND",
       9: "VDDA", 10: "ADC_L", 11: "ADC_R", 18: "PB0", 19: "CLK_O", 20: "LED_ACT", 21: "BCAST_O", 22: "RETURN",
       23: "GND", 24: "+3V3", 27: "PB14", 28: "VBUS_DET", 29: "SYNC_O", 30: "UART_TX", 31: "UART_RX",
       32: "USBD_DM", 33: "USBD_DP", 34: "SWDIO", 35: "GND", 36: "+3V3", 37: "SWCLK", 38: "FLASH_CS_N",
       39: "SPI_SCK", 40: "SPI_MISO", 41: "SPI_MOSI", 42: "USBH_DM", 43: "USBH_DP", 44: "BOOT0", 45: "HOST_EN",
       46: "HOST_FLT_N", 47: "GND", 48: "+3V3"}
SWIO_PIN = {1: 12, 2: 13, 3: 14, 4: 15, 5: 16, 6: 17, 7: 25, 8: 26}     # PA2 ... PA7, PB12, PB13
MCU.update({pin: f"SWIO_{k}" for k, pin in SWIO_PIN.items()})
add("U", "MCU_WCH_RiscV:CH32V203CxTx", "CH32V203C8T6", FP["LQFP48"], MCU, ref="U1", bom=False,
    note="own stock, hand-soldered; SPI1 remap 1 (PA15/PB3/PB4/PB5); TIM3 CH4 (PB1) = 24 MHz CLK option")
for pin in (24, 36, 48):
    C(None, "100n", "+3V3", "GND", 3.3, note=f"MCU decoupling VDD pin {pin}")
C(None, "100n", "+3V3", "GND", 3.3, note="MCU decoupling VBAT")
add("FB", "Device:FerriteBead_Small", "BLM18PG121SN1D", FP["FB"], {1: "+3V3", 2: "VDDA"}, lcsc="C14709",
    note="VDDA filter")
C(None, "1u", "VDDA", "GND", 3.3, note="VDDA")
C(None, "100n", "VDDA", "GND", 3.3, note="VDDA")
C(None, "100n", "MCU_NRST", "GND", 3.3, note="reset filter")
add("SW", "Switch:SW_Push", "RESET", FP["SW"], {1: "MCU_NRST", 2: "GND"}, ref="SW1", lcsc="C318884",
    note="controller reset (the 595 outputs go off; the cards keep running until reset again)")
group("8 MHz crystal (PLL x 18 = 144 MHz)")
add("Y", "Device:Crystal", "8MHz", FP["XTAL"], {1: "OSC_IN", 2: "OSC_OUT"}, ref="Y1", lcsc="C115962",
    note="X50328MSB2GI, 20 pF load, 80 R ESR")
C(None, "30p", "OSC_IN", "GND", 3.3, tc="C0G", note="crystal load")
C(None, "30p", "OSC_OUT", "GND", 3.3, tc="C0G", note="crystal load")
group("Programming: SWD (WCH-LinkE), BOOT0, USART1 (bootloader, debug)")
HDR("J5", 4, "SWD", ("+3V3", "SWDIO", "SWCLK", "GND"), note="WCH-LinkE: 3V3, SWDIO, SWCLK, GND")
add("JP", "Jumper:Jumper_3_Open", "BOOT0", FP["HDR3"], {1: "+3V3", 2: "BOOT0", 3: "GND"}, ref="JP2", bom=False,
    note="1-2: system bootloader (USART1 / USB), open or 2-3: run from flash")
R(None, "10k", "BOOT0", "GND", note="BOOT0 low by default")
HDR("J6", 3, "UART", ("GND", "UART_TX", "UART_RX"), note="USART1: GND, TX (PA9), RX (PA10); 5 V adapters are fine (FT)")
group("MIDI DIN in (option, not fitted): opto into PA10 through JP3")
HDR("J7", 3, "MIDI IN", ("MIDI_4", "MIDI_5", "GND"), note="DIN pin 4, DIN pin 5, shield (panel jack on wires)",
    dnp=True)
R(None, "220", "MIDI_4", "MIDI_LA", dnp=True, note="MIDI loop series")
add("U", "Isolator:LTV-817S", "LTV-817S", FP["OPTO"], {1: "MIDI_LA", 2: "MIDI_5", 3: "GND", 4: "MIDI_RX"},
    ref="U9", lcsc="C109227", dnp=True, note="slow for 31.25 kbaud at 3.3 V (unverified); 6N138 by hand if needed")
add("D", "Diode:1N4148W", "1N4148W", FP["SOD123"], {1: "MIDI_LA", 2: "MIDI_5"}, lcsc="C81598", dnp=True,
    note="opto LED reverse protection")
R(None, "1k", "MIDI_RX", "+3V3", dnp=True, note="opto collector pull-up")
add("JP", "Jumper:Jumper_2_Open", "MIDI", FP["HDR2"], {1: "MIDI_RX", 2: "UART_RX"}, ref="JP3", bom=False, dnp=True,
    note="fit only for DIN MIDI: USART1 RX then not available to J6")
group("SPI flash (footprint only), activity LED, free pins")
add("U", "Memory_Flash:W25Q128JVS", "W25Q128JVSIQ", FP["SO8W"],
    {1: "FLASH_CS_N", 2: "SPI_MISO", 3: "FLASH_WP_N", 4: "GND", 5: "SPI_MOSI", 6: "SPI_SCK", 7: "FLASH_HOLD_N",
     8: "+3V3"}, ref="U7", lcsc="C97521", dnp=True,
    note="SOP-8 208 mil: W25Q128JVSIQ or BY25D16ASTIG (own stock), hand-soldered later")
C(None, "100n", "+3V3", "GND", 3.3, note="flash decoupling")
R(None, "10k", "FLASH_CS_N", "+3V3", note="flash deselected while the MCU boots")
R(None, "10k", "FLASH_WP_N", "+3V3", note="flash WP idle")
R(None, "10k", "FLASH_HOLD_N", "+3V3", note="flash HOLD idle")
R(None, "10k", "LED_ACT", "GND", note="PB2 = BOOT1: low at reset")
R(None, "1k", "LED_ACT", "LED_ACT_A", note="activity LED series")
LED("yellow", "LED_ACT_A", "GND", "activity")
for n in ("PC15", "PB0", "PB14"):
    TP(n, note="free MCU pin")
for n in ("+3V3", "+5V", "GND"):
    TP(n)

# =========================================================================== voice bus, NRST, slots
sheet("bus")
group("Bus drivers: broadcast, return, SYNC, 24 MHz clock (option)")
R(None, "33", "BCAST_O", "BCAST", note="bus series: broadcast (USART3 TX) to every card's RX")
R(None, "1k", "RETURN", "+3V3", note="return pull-up (cards' TX open drain)")
R(None, "33", "SYNC_O", "SYNC", note="bus series: SYNC 1 kHz (TIM1 CH1)")
R(None, "33", "CLK_O", "CLK", note="bus series: 24 MHz CLK_IN option (TIM3 CH4), off by default")
group("NRST: 74HC595 drives each card's NRST directly (outputs off at reset: the cards run freely)")
NRST_Q = {1: 15, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 7}        # slot -> 595 output pin (QA ... QH); layout may permute
add("U", "74xx:74HC595", "74HC595D", FP["SO16"],
    {14: "SPI_MOSI", 11: "SPI_SCK", 12: "SR_LATCH", 13: "SR_OE_N", 10: "+3V3", 16: "+3V3", 8: "GND", 9: "NC_QH",
     **{pin: f"NRST_{k}" for k, pin in NRST_Q.items()}}, ref="U6", lcsc="C5947")
C(None, "100n", "+3V3", "GND", 3.3, note="595 decoupling")
R(None, "10k", "SR_OE_N", "+3V3", note="595 outputs off until the MCU drives OE_N (undefined at power-up)")
# no NRST pull-downs or series resistors (user decision): the cards may boot on their own at power-up, during a
# controller reset or while it sits in the bootloader; the firmware resets them through the 595 or over SWIO
group("SWIO pull-ups (1 k each: the one-wire protocol samples 0.6 us after an edge)")
for a in (1, 5):
    RN("1k", "C20197", [("+3V3", f"SWIO_{k}") for k in range(a, a + 4)], note=f"SWIO pull-ups, slots {a}-{a + 3}")
group("Slot sockets (2 x 8 female, vertical; card part side faces west)")
for k in range(1, SLOTS + 1):
    add("J", "Connector_Generic:Conn_02x08_Odd_Even", f"SLOT {k}", FP["SOCK"],
        {1: "+5V", 2: "+5V", 3: "GND" if k != FX_SLOT else "FX_RET_L", 4: "GND" if k != FX_SLOT else "FX_RET_R",
         5: f"AUDIO_L_{k}", 6: f"AUDIO_GND_{k}", 7: f"AUDIO_R_{k}", 8: "GND",
         9: "SYNC", 10: "BCAST", 11: "RETURN", 12: f"NRST_{k}", 13: "GND",
         14: f"SWIO_{k}" if k != FX_SLOT else "FX_P14", 15: "CLK" if k != FX_SLOT else "FX_P15", 16: "GND"},
        ref=f"J{9 + k}", bom=False, note="voice card socket, hand-soldered")
    C(None, "10u", "+5V", "GND", 5, note=f"slot {k} supply")
for n in ("SYNC", "BCAST", "RETURN"):
    TP(n)

# =========================================================================== mixer
sheet("mixer")
group("Per slot: input capacitors, 56k into the summing nodes, AUDIO_GND mirror (C_G, R_P)")
for k in range(1, SLOTS + 1):
    s = k - 1                                                  # S12 slot index
    # the three input capacitors in 0805: the +5 V rail passes between their pads (backplane.md 7.4)
    C(f"CINl{s}_0", "10u", f"AUDIO_L_{k}", f"MXL_{k}", 2.5, pkgs=("0805",), note=f"slot {k} C_IN_L")
    R(f"RIl{s}_0", "56k", f"MXL_{k}", "SUM_LN", note=f"slot {k} R_IN_L")
    C(f"CINr{s}_0", "10u", f"AUDIO_R_{k}", f"MXR_{k}", 2.5, pkgs=("0805",), note=f"slot {k} C_IN_R")
    R(f"RIr{s}_0", "56k", f"MXR_{k}", "SUM_RN", note=f"slot {k} R_IN_R")
    C(f"CG{s}_0", "10u", f"AUDIO_GND_{k}", f"MXG_{k}", 2.5, pkgs=("0805",), note=f"slot {k} C_G (mirror)")
    R(f"RPl{s}_0", "56k", f"MXG_{k}", "SUM_LP", note=f"slot {k} R_P_L")
    R(f"RPr{s}_0", "56k", f"MXG_{k}", "SUM_RP", note=f"slot {k} R_P_R")
group("Op-amp rail and VREF 2.41 V (divider from the controller's +3V3, two RC stages, unbuffered)")
R("RSUP0", "47", "+5V", "VA_MIX"); C("CSUP0", "22u", "VA_MIX", "GND", 5)
# the summing amps' + inputs are VREF's only DC load (pA): no buffer; the LDO rejects low-frequency supply ripple,
# two RC stages (2.2 Hz, 1.6 Hz) the MCU's load steps on +3V3 (-72 dB at 100 Hz, -112 dB at 1 kHz to the line
# out); the ADC tap then tracks the ADC's own 3.3 V (S12 --bus2, section 9)
R("RVA0", "10k", "+3V3", "VREF_DIV", note="VREF divider (top)")
R("RVB0", "27k", "VREF_DIV", "GND", note="VREF divider (bottom)")
C("CVR0", "10u", "VREF_DIV", "GND", 2.5, note="VREF filter")
R("RVC0", "10k", "VREF_DIV", "VREF", note="VREF second RC stage")
C("CVRB0", "10u", "VREF", "GND", 2.5, note="VREF second filter")
group("Summing amplifiers (inverting, + side mirrored to VREF): out = VREF - 0.357 x sum(AUDIO_x - AUDIO_GND)")
MCP6002("U8", "XL0/XR0", ("SUM_LP", "SUM_LN", "MIX_L"), ("SUM_RP", "SUM_RN", "MIX_R"),
        note="mixer: unit A sums L, unit B sums R")
for ch in ("l", "r"):
    X = ch.upper()
    R(f"RF{ch}0", "20k", f"MIX_{X}", f"SUM_{X}N"); C(f"CF{ch}0", "47p", f"MIX_{X}", f"SUM_{X}N", 2.5, tc="C0G")
    R(f"RFP{ch}0", "20k", "VREF", f"SUM_{X}P"); C(f"CFP{ch}0", "47p", "VREF", f"SUM_{X}P", 2.5, tc="C0G")
group("Line out (3.5 mm stereo) and ADC taps (USB audio)")
for ch in ("l", "r"):
    X = ch.upper()
    R(f"ROS{ch}0", "220", f"MIX_{X}", f"LO_{X}", note="line-out series (remove for a loop-through effects card)"); C(f"COL{ch}0", "10u", f"LO_{X}", f"LINE_{X}", 2.5)
    R(f"RBL{ch}0", "100k", f"LINE_{X}", "GND", note="line-out bleeder")
    R(f"RA1{ch}0", "15k", f"MIX_{X}", f"ADC_{X}", note="ADC divider, at the MCU")
    R(f"RA2{ch}0", "27k", f"ADC_{X}", "GND", note="ADC divider, at the MCU")
    C(f"CA{ch}0", "330p", f"ADC_{X}", "GND", 3.3, tc="C0G", note="ADC anti-alias, at the MCU pin")
add("J", "Connector_Audio:AudioJack3", "LINE OUT", FP["JACK"], {"T": "LINE_L", "R": "LINE_R", "S": "GND"},
    ref="J3", bom=False, note="CUI SJ1-3523N, hand-soldered")
for n in ("VREF", "MIX_L", "MIX_R"):
    TP(n)

# effects slot (user decision 2026-10-20; appended last so that no other reference changes): slot FX_SLOT's pins
# 15 and 14 carry CLK and SWIO as on every slot (0 R fitted), or, for an effects card, the stereo mix as sends
# (220 R fitted instead: isolates the summing amps from the trace and the card input). The effects card returns
# its signal through the slot's AUDIO pins into the mixer like a voice (mixing in), or on pins 3 / 4 (GND on every
# other slot; a voice card grounds them, which these not-fitted positions ignore) into the line-out stage
# instead of the mix (loop-through: remove the line-out 220 R from MIX_L / MIX_R, fit the two below).
sheet("bus")
group("Effects slot 1: pins 15 / 14 = CLK / SWIO_1 or the mix sends; pins 3 / 4 = the loop-through return")
R(None, "0", "CLK", "FX_P15", note="effects slot: CLK to slot 1 pin 15 (remove for an effects card)")
R(None, "220", "MIX_L", "FX_P15", dnp=True, note="effects slot: send L to slot 1 pin 15 (fit for an effects card)")
R(None, "0", "SWIO_1", "FX_P14", note="effects slot: SWIO_1 to slot 1 pin 14 (remove for an effects card)")
R(None, "220", "MIX_R", "FX_P14", dnp=True, note="effects slot: send R to slot 1 pin 14 (fit for an effects card)")
R(None, "220", "FX_RET_L", "LO_L", dnp=True, note="effects slot: return L from slot 1 pin 3 to the line out (loop-through)")
R(None, "220", "FX_RET_R", "LO_R", dnp=True, note="effects slot: return R from slot 1 pin 4 to the line out (loop-through)")

# --------------------------------------------------------------------------- simulation cross-reference (S12 --bus2)
SIM_ONLY = {f"{e}{x}{s}_0".upper() for e in ("RO", "LO", "CC", "RBC") for x in "lr" for s in range(SLOTS)} | \
    {f"{e}{ch}0".upper() for e in ("RLD", "CCB") for ch in "lr"}          # card outputs, line-out test load
SIM_NODES = {"0": "GND", "v5_0": "+5V", "va_0": "VA_MIX", "vref_0": "VREF", "vrd_0": "VREF_DIV", "v33_0": "+3V3",
             **{f"{a}{ch}_0": f"{b}_{ch.upper()}{c}" for ch in "lr" for a, b, c in
                (("n", "SUM", "N"), ("p", "SUM", "P"), ("o", "MIX", ""), ("lo", "LO", ""), ("j", "LINE", ""),
                 ("a", "ADC", ""))}}
for s in range(SLOTS):
    k = s + 1
    SIM_NODES.update({f"g{s}_0": f"AUDIO_GND_{k}", f"y{s}_0": f"MXG_{k}"})
    for x in "lr":
        X = x.upper()
        SIM_NODES.update({f"ao{x}{s}_0": f"AUDIO_{X}_{k}", f"ai{x}{s}_0": f"MX{X}_{k}"})


def sim_netlist():
    """The S12 two-bus mixer (all 8 slots populated), copy 0, which the mixer sheet is checked against."""
    import os, sys
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:0] = [os.path.join(here, "..", "sim", "s12_mixer")]
    me = sys.modules.pop("voice", None)            # sim/lib/voice.py vs hw/voice.py (not imported here, but keep safe)
    try:
        import s12_mixer as M
    finally:
        if me is not None:
            sys.modules["voice"] = me
    return M.build2(0, M.nominal2())


def nets():
    out = {}
    for p in PARTS:
        for pin, n in p.pins.items():
            out.setdefault(n, []).append((p.ref, pin))
    return out


if __name__ == "__main__":
    N = nets()
    print(len(PARTS), "parts,", len(N), "nets")
    single = {n: v for n, v in N.items() if len(v) < 2 and not n.startswith("NC_")}
    print("single-pin nets:", single)
    from collections import Counter
    print(Counter(p.sheet for p in PARTS))
    print("fitted SMD (assembled):", sum(1 for p in PARTS if p.bom and not p.dnp and p.lcsc))
