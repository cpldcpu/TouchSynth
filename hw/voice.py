"""TouchSynth Poly voice card: complete design description (single source of truth for schematic and PCB).

Circuit: docs/spec.md section 3 (signal path, pin map, connectors). Every analog part carries its ngspice name
('sim' field) from the S10 variant v5c netlist (sim/s10_5v/s10_5v.py, core()), which includes the S11
reconstruction filter; check_sim.py compares the two. Nets used on more than one sheet become global labels.

Supplies: +5V from the backplane (or the programmer, through a Schottky diode), VA = the analog rail behind
22 R + 3 x 100 uF, +3V3 from an XC6206 for the MCU (its PWM outputs are the CVs and the DAC: duty x 3.3 V).
"""
from collections import OrderedDict
import lcsc as L

PROJECT = "voice"
TITLE = "TouchSynth Poly voice card"
REV = "0.1"
POWER = {"GND": "power:GND", "+5V": "power:+5V", "+3V3": "power:+3V3"}
RAIL = "VA"                                     # always a global label (analog rail)
FLAGS = ("GND", "+5V", "VA")                    # PWR_FLAGs: supplies from connectors / passives (+3V3: LDO)
LAYOUTS = "layouts_voice"                       # hand-drawn sheet layouts

SHEETS = OrderedDict([
    ("power", "Supply, references and ladder bias"),
    ("mcu", "MCU, backplane, programming, LEDs"),
    ("dac", "PWM DAC reconstruction filter and mixer"),
    ("vcf", "CV_CUT, expo converter, ladder filter"),
    ("resonance", "CV_RES and resonance VCA"),
    ("vca", "CV_VCA, VCA trim, VCA, output and loopback"),
])

FP = dict(
    R0603="Resistor_SMD:R_0603_1608Metric", C0603="Capacitor_SMD:C_0603_1608Metric",
    C0805="Capacitor_SMD:C_0805_2012Metric", C1206="Capacitor_SMD:C_1206_3216Metric",
    SOT23="Package_TO_SOT_SMD:SOT-23", SOT363="Package_TO_SOT_SMD:SOT-363_SC-70-6",
    SO8="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", SO14="Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
    TSSOP20="Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm", LED="LED_SMD:LED_0603_1608Metric",
    SOD123="Diode_SMD:D_SOD-123", TP="TestPoint:TestPoint_Pad_D1.0mm",
    BP="Connector_PinHeader_2.54mm:PinHeader_2x08_P2.54mm_Horizontal",
    HDR2="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Horizontal",
    HDR3="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Horizontal",
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
    _count[prefix] = _count.get(prefix, 0) + 1
    return f"{prefix}{_count[prefix]}"


def add(prefix, lib_id, value, fp, pins, **kw):
    p = Part(_ref(prefix), lib_id, value, fp, {str(k): v for k, v in pins.items()}, _sheet, **kw)
    PARTS.append(p)
    return p


def R(sim, value, a, b, **kw):
    code, pkg = L.pick_r(value)
    return add("R", "Device:R", value, FP["R" + pkg], {1: a, 2: b}, lcsc=code, sim=sim, **kw)


def C(sim, value, a, b, vwork, tc=None, **kw):
    code, pkg = L.pick_c(value, 2 * vwork, tc=tc)
    return add("C", "Device:C", value.replace("u", "µ"), FP["C" + pkg], {1: a, 2: b}, lcsc=code, sim=sim, **kw)


def NPN(sim, c, b, e):
    return add("Q", "Transistor_BJT:MMBT3904", "MMBT3904", FP["SOT23"], {3: c, 1: b, 2: e}, lcsc="C20526", sim=sim)


def PAIR(sim, c1, b1, e1, c2, b2, e2):
    """BC847BS dual NPN (thermally matched pair on one die carrier)."""
    return add("Q", "Transistor_BJT:BC847BS", "BC847BS", FP["SOT363"],
               {6: c1, 2: b1, 1: e1, 3: c2, 5: b2, 4: e2}, lcsc="C41375126", sim=sim)


def MCP6002(sim, a, b):
    """a, b = (in+, in-, out) for units A and B; powered from VA, 100 nF decoupling."""
    p = add("U", "Amplifier_Operational:MCP6002-xSN", "MCP6002", FP["SO8"],
            {3: a[0], 2: a[1], 1: a[2], 5: b[0], 6: b[1], 7: b[2], 8: "VA", 4: "GND"}, lcsc="C7377", sim=sim)
    C(None, "100n", "VA", "GND", 5, note=f"decoupling {p.ref}")
    return p


def CVNET_LIN(n, src, x, r4):
    """S2 LIN network from a 0...3.3 V PWM pin: 1k/100n -> 4k7/33n -> 4k7 / r4 || 22n."""
    R(f"R1{n}", "1k", src, f"CV{n}_A"); C(f"C1{n}", "100n", f"CV{n}_A", "GND", 5)
    R(f"R2{n}", "4.7k", f"CV{n}_A", f"CV{n}_B"); C(f"C2{n}", "33n", f"CV{n}_B", "GND", 5)
    R(f"R3{n}", "4.7k", f"CV{n}_B", x); R(f"R4{n}", r4, x, "GND"); C(f"C3{n}", "22n", x, "GND", 5)


def VI(n, x, col, re_value, lm_unit):
    """LM324 unit (in+, in-, out) pins + MMBT3904: I = V(x) / Re."""
    ve, uo, bq = f"VI{n}_E", f"VI{n}_OUT", f"VI{n}_B"
    R(f"RBV{n}", "1k", uo, bq)
    NPN(f"QV{n}", col, bq, ve)
    R(f"REV{n}", re_value, ve, "GND")
    return {lm_unit[0]: x, lm_unit[1]: ve, lm_unit[2]: uo}


def TP(net, note=None):
    return add("TP", "Connector:TestPoint", net, FP["TP"], {1: net}, bom=False, note=note)


# =========================================================================== supply, references, bias
sheet("power")
group("5 V input, analog rail, 3.3 V for the MCU")
# backplane +5V (connector on the mcu sheet); programmer +5V through a Schottky diode (no back-feeding)
add("D", "Device:D_Schottky", "B5819W", FP["SOD123"], {2: "+5V_PRG", 1: "+5V"}, lcsc="C8598",
    note="programmer 5 V into the card only (card then runs at about 4.6 V)")
R("RFILT", "22", "+5V", "VA")
for k in (1, 2, 3):                              # 220 uF equivalent is not on the JLCPCB lists
    add("C", "Device:C", "100µ", FP["C1206"], {1: "VA", 2: "GND"}, lcsc="C15008", sim=f"CFILT{k}",
        note="X5R 6.3 V, about 35 uF at 5 V (simulated as such)")
add("U", "Regulator_Linear:XC6206PxxxMR", "XC6206P332MR", FP["SOT23"], {3: "+5V", 2: "+3V3", 1: "GND"},
    lcsc="C5446")
C(None, "1u", "+5V", "GND", 5, note="LDO input")
C(None, "1u", "+3V3", "GND", 3.3, note="LDO output")
group("References: VREF 2.5 V (CJ431, buffered), VBIAS 1.0 V (LM324 follower), VEXP_REF 1.25 V")
R(None, "1k", "VA", "VREF431", note="CJ431 feed, about 2.5 mA")
add("U", "Reference_Voltage:TL432DBZ", "CJ431", FP["SOT23"], {1: "VREF431", 2: "VREF431", 3: "GND"},
    lcsc="C3113", note="CJ431 SOT-23 pinout: 1 REF, 2 K, 3 A (as TL432); REF tied to K: 2.5 V")
R("RFREF", "10k", "VREF431", "VREF_F"); C("CFREF", "10u", "VREF_F", "GND", 2.5)
MCP6002("XVREF/XSK", ("VREF_F", "VREF", "VREF"), ("SK2", "DAC_F", "DAC_F"))   # unit B: the DAC filter
PARTS[-2].unit_sheets = {2: "dac"}
PARTS[-2].unit_groups = {2: "Reconstruction filter (2-pole Sallen-Key, Butterworth, 31 kHz, C0G)"}
R("RBA", "15k", "VREF", "VBIAS_DIV"); R("RBB", "10k", "VBIAS_DIV", "GND"); C("CBI", "1u", "VBIAS_DIV", "GND", 2.5)
R("R25A", "10k", "VREF", "VEXP_REF"); R("R25B", "10k", "VEXP_REF", "GND"); C("C25", "1u", "VEXP_REF", "GND", 2.5)
group("Ladder bias chain")
for sim, v, a, b in [("RB5", "620", "VA", "VB4"), ("RB4", "1.5k", "VB4", "VB3"), ("RB3", "1.5k", "VB3", "VB2"),
                     ("RB2", "1.5k", "VB2", "VB1"), ("RB1", "1.5k", "VB1", "VB0"), ("RB0", "3.3k", "VB0", "GND")]:
    R(sim, v, a, b)
for i, v in [(4, 4.4), (3, 3.7), (2, 3.0), (1, 2.4), (0, 1.7)]:
    C(f"CB{i}", "10u", f"VB{i}", "GND", v)
group("Test points")
for n in ("VA", "+3V3", "VREF", "VBIAS", "VEXP_REF", "VB0", "VB2", "VB4", "GND"):
    TP(n)

# =========================================================================== MCU, connectors, LEDs
sheet("mcu")
group("MCU (CH32V006F8P7, hand-soldered)")
add("U", "MCU_WCH_RiscV:CH32V003FxPx", "CH32V006F8P7", FP["TSSOP20"],
    {1: "SYNC_IN", 2: "TX_OUT", 3: "RX_IN", 4: "NRST", 5: "CLK_SEL", 6: "ST_VB0", 7: "GND", 8: "LED_PLAY",
     9: "+3V3", 10: "PWM_RES", 11: "PWM_LO", 12: "PWM_DAC", 13: "LED_STAT", 14: "ADC_AUDIO", 15: "PC5",
     16: "PWM_TRIM", 17: "PWM_CUT", 18: "SWIO", 19: "ST_RAIL", 20: "PWM_VCA"},
    bom=False, note="own stock, hand-soldered; TIM1_RM 0010, TIM2_RM 010; PA4 bonded to PD7: never an output")
C(None, "100n", "+3V3", "GND", 3.3, note="MCU decoupling")
C(None, "1u", "+3V3", "GND", 3.3, note="MCU bulk")
group("Backplane connector and voice bus")
add("J", "Connector_Generic:Conn_02x08_Odd_Even", "BACKPLANE", FP["BP"],
    {1: "+5V", 2: "+5V", 3: "GND", 4: "GND", 5: "AUDIO_OUT", 6: "GND", 7: "GND", 8: "GND", 9: "SYNC",
     10: "RX", 11: "TX", 12: "NRST", 13: "GND", 14: "SWIO", 15: "CLK_IN", 16: "NC_BP16"},
    bom=False, note="2x8 right-angle header, card underside edge; pin 6 = AUDIO_GND: route from the line-out ground")
R(None, "100", "SYNC", "SYNC_IN", note="bus series")
R(None, "100k", "SYNC_IN", "GND", note="no SYNC edges when unplugged (standalone detection)")
R(None, "100", "RX", "RX_IN", note="bus series")
R(None, "100k", "RX_IN", "+3V3", note="RX idle high when unplugged")
R(None, "100", "TX_OUT", "TX", note="bus series; PD5 open drain, pull-up on the backplane")
C(None, "100n", "NRST", "GND", 3.3, dnp=True, note="NRST filter (option)")
group("Programming (WCH-LinkE) and line out")
add("J", "Connector_Generic:Conn_01x03", "SWIO", FP["HDR3"], {1: "+5V_PRG", 2: "SWIO", 3: "GND"}, bom=False,
    note="WCH-LinkE: 5V, SWIO, GND (right-angle, debug edge)")
add("J", "Connector_Generic:Conn_01x02", "LINE OUT", FP["HDR2"], {1: "AUDIO_OUT", 2: "GND"}, bom=False,
    note="right-angle, debug edge")
group("LEDs (debug edge)")
R(None, "2.2k", "+3V3", "LED_PWR_A", note="power LED series")
add("D", "Device:LED", "red", FP["LED"], {2: "LED_PWR_A", 1: "GND"}, lcsc="C2286", note="power")
R(None, "1k", "LED_PLAY", "LED_PLAY_A", note="playing LED series")
add("D", "Device:LED", "yellow", FP["LED"], {2: "LED_PLAY_A", 1: "GND"}, lcsc="C89811", note="playing")
R(None, "1k", "LED_STAT", "LED_STAT_A", note="status LED series")
add("D", "Device:LED", "red", FP["LED"], {2: "LED_STAT_A", 1: "GND"}, lcsc="C2286", note="status")
group("Options (not fitted)")
R(None, "0", "CLK_IN", "CLK_SEL", dnp=True, note="external clock from the backplane MCO (fallback, spec 6)")
R(None, "10k", "VB0", "ST_VB0", dnp=True, note="self-test: ladder bias VB0 to ADC A0")
R(None, "10k", "VA", "ST_RAIL", dnp=True, note="self-test: analog rail / 2 to ADC A3")
R(None, "10k", "ST_RAIL", "GND", dnp=True, note="self-test divider")
group("Test points")
for n in ("NRST", "SWIO", "PC5", "SYNC_IN"):
    TP(n)

# =========================================================================== DAC
sheet("dac")
group("Reconstruction filter (2-pole Sallen-Key, Butterworth, 31 kHz, C0G)")
R("RSK1", "11k", "PWM_DAC", "SK1"); R("RSK2", "11k", "SK1", "SK2")
C("CSK1A", "330p", "SK1", "DAC_F", 2.5, tc="C0G"); C("CSK1B", "330p", "SK1", "DAC_F", 2.5, tc="C0G")
C("CSK2", "330p", "SK2", "GND", 2.5, tc="C0G")
group("Dual-PWM option: low byte (TIM2 CH4) into the filter input, 1.33 MΩ = 120.9 x 11k (overlap, spec 3.5)")
R(None, "1M", "PWM_LO", "LO_A", dnp=True, note="dual-PWM option")
R(None, "330k", "LO_A", "SK1", dnp=True, note="dual-PWM option")
group("Mixer into the ladder input")
R("RMIX", "240k", "DAC_F", "MIX"); R("RMX", "10k", "MIX", "VB0"); C("CMX", "1u", "MIX", "BIN1", 3)
group("Test points")
TP("DAC_F")

# =========================================================================== VCF
sheet("vcf")
group("CV_CUT filter and exponential converter")
R("R1C", "1k", "PWM_CUT", "CVC_A"); C("C1C", "100n", "CVC_A", "GND", 5)
R("R2C", "4.7k", "CVC_A", "XCUT_IN"); C("C2C", "33n", "XCUT_IN", "GND", 5)
R("R33X", "18k", "XCUT_IN", "XCUT"); R("R12X", "1.5k", "XCUT", "VBIAS"); C("C12X", "100n", "XCUT", "VBIAS", 5)
PAIR("QEA/QEB", "EXPO_NA", "VBIAS", "EXPO_E", "TAIL", "XCUT", "EXPO_E")
R("RREF", "470k", "VREF", "EXPO_NA")
LM = {10: "VEXP_REF", 9: "EXPO_NA", 8: "EXPO_OUT"}                 # LM324 unit C
R("REXP", "1k", "EXPO_OUT", "EXPO_E"); C("CEXP", "1n", "EXPO_OUT", "EXPO_NA", 5)
group("Transistor ladder (4 poles)")
PAIR("Q1/Q2", "N1A", "BIN1", "TAIL", "N1B", "BIN2", "TAIL")
PAIR("Q3/Q4", "N2A", "VB1", "N1A", "N2B", "VB1", "N1B")
PAIR("Q5/Q6", "N3A", "VB2", "N2A", "N3B", "VB2", "N2B")
PAIR("Q7/Q8", "N4A", "VB3", "N3A", "N4B", "VB3", "N3B")
PAIR("Q9/Q10", "VA", "VB4", "N4A", "VA", "VB4", "N4B")
for i in range(1, 5):
    C(f"CL{i}", "10n", f"N{i}A", f"N{i}B", 1)
R("RBI1", "10k", "BIN1", "VB0"); R("RBI2", "10k", "BIN2", "VB0")
group("Output instrumentation amplifier (G = 11)")
MCP6002("XINA1/XINA2", ("N4A", "INA_A", "INA_OA"), ("N4B", "INA_B", "LPF"))
R("RI1", "100k", "INA_A", "VREF"); R("RI2", "10k", "INA_OA", "INA_A")
R("RI3", "10k", "INA_OA", "INA_B"); R("RI4", "100k", "LPF", "INA_B")
group("Test points")
for n in ("TAIL", "LPF", "XCUT_IN"):
    TP(n)

# =========================================================================== resonance
sheet("resonance")
group("CV_RES filter and V-to-I converter")
CVNET_LIN("R", "PWM_RES", "XRES", "12k")
LM.update(VI("R", "XRES", "RES_TAIL", "3.6k", (12, 13, 14)))
group("Resonance VCA and difference amplifier")
C("CRI", "1u", "LPF", "RES_RI", 3); R("RRA", "120k", "RES_RI", "RES_IN1")
R("RRB1", "10k", "RES_IN1", "VB2"); R("RRB2", "10k", "RES_IN2", "VB2")
PAIR("QR1/QR2", "RES_C1", "RES_IN1", "RES_TAIL", "RES_C2", "RES_IN2", "RES_TAIL")
R("RRC1", "4.7k", "VA", "RES_C1"); R("RRC2", "4.7k", "VA", "RES_C2")
R("RRD1", "10k", "RES_C1", "RES_DM"); R("RRD2", "10k", "RES_DM", "RESOUT")
R("RRD3", "10k", "RES_C2", "RES_DP"); R("RRD4", "10k", "RES_DP", "VREF")
C("CRF", "4.7u", "RESOUT", "RES_FB", 3); R("RRF", "22k", "RES_FB", "BIN2")
group("Test points")
for n in ("XRES", "RESOUT"):
    TP(n)

# =========================================================================== VCA, output, loopback
sheet("vca")
group("CV_VCA filter and V-to-I converter")
CVNET_LIN("V", "PWM_VCA", "XVCA", "7.5k")
LM.update(VI("V", "XVCA", "VCA_TAIL", "2.2k", (5, 6, 7)))
R("ROFFV", "240k", "VREF", "VIV_E")
group("VCA trim (TIM1 CH1 PWM, 2-pole RC, 680k into vin2)")
R("RTR1", "10k", "PWM_TRIM", "TRIM_A"); C("CTR1", "1u", "TRIM_A", "GND", 3.3)
R("RTR2", "10k", "TRIM_A", "VTRIM"); C("CTR2", "1u", "VTRIM", "GND", 3.3)
group("VCA core")
C("CVI", "1u", "LPF", "VCA_VI", 3); R("RVA", "33k", "VCA_VI", "VCA_IN1")
R("RVB1", "1k", "VCA_IN1", "VREF"); R("RVB2", "1k", "VCA_IN2", "VREF")
R("RTRM", "680k", "VTRIM", "VCA_IN2"); R("RTRF", "2M", "VCA_IN1", "GND")
PAIR("QA1/QA2", "VCA_C1", "VCA_IN1", "VCA_TAIL", "VCA_C2", "VCA_IN2", "VCA_TAIL")
R("RVC1", "4.7k", "VA", "VCA_C1"); R("RVC2", "4.7k", "VA", "VCA_C2")
group("Difference amplifiers (resonance, VCA), line out")
R("RD1", "10k", "VCA_C1", "VCA_DM"); R("RD2", "22k", "VCA_DM", "VCAOUT")
R("RD3", "10k", "VCA_C2", "VCA_DP"); R("RD4", "22k", "VCA_DP", "VREF")
R("RD5", "33k", "VCA_DP", "GND", note="matched with RD6: inputs below the MCP6002 input transition")
R("RD6", "33k", "VCA_DM", "GND", note="matched with RD5")
MCP6002("XRDIF/XDIF", ("RES_DP", "RES_DM", "RESOUT"), ("VCA_DP", "VCA_DM", "VCAOUT"))
PARTS[-2].unit_sheets = {1: "resonance"}
PARTS[-2].unit_groups = {1: "Resonance VCA and difference amplifier"}
R("RISO", "100", "VCAOUT", "VCAOUT_R", note="isolates the op-amp from cable / backplane capacitance")
C("COUT", "10u", "VCAOUT_R", "AUDIO_OUT", 2.5); R("RBL", "100k", "AUDIO_OUT", "GND", note="output bleeder")
group("Audio loopback to PC4 (ADC A2)")
R("RLB1", "10k", "VCAOUT", "ADC_AUDIO"); R("RLB2", "15k", "ADC_AUDIO", "GND")
C("CLB", "1n", "ADC_AUDIO", "GND", 3.3)
group("Test points")
for n in ("VCAOUT", "XVCA", "VTRIM"):
    TP(n)

# LM324 (all four units + supply), placed on the vcf sheet; unit A: the VBIAS buffer (power sheet)
sheet("vcf")
group("CV_CUT filter and exponential converter")
LM.update({3: "VBIAS_DIV", 2: "VBIAS", 1: "VBIAS", 4: "VA", 11: "GND"})
add("U", "Amplifier_Operational:LM324", "LM324", FP["SO14"], LM, lcsc="C71035",
    sim="XUV/XUEXP/XUR/XVB").unit_sheets = {1: "power", 2: "vca", 4: "resonance"}
PARTS[-1].unit_groups = {1: "References: VREF 2.5 V (CJ431, buffered), VBIAS 1.0 V (LM324 follower), VEXP_REF 1.25 V",
                         2: "CV_VCA filter and V-to-I converter", 4: "CV_RES filter and V-to-I converter"}
C(None, "100n", "VA", "GND", 5, note="LM324 decoupling")

# --------------------------------------------------------------------------- simulation cross-reference
SIM_UNITS = {"XVB": 1, "XUV": 2, "XUEXP": 3, "XUR": 4}                 # LM324 unit of each simulated op-amp
SIM_ONLY = {"RLOAD"}                                         # the line-out load in S10 (the mixer)
SIM_DERATED = {f"CFILT{k}": 35e-6 for k in (1, 2, 3)}         # value simulated at its 5 V bias capacitance
SIM_NODES = {
    "0": "GND", "vin": "+5V", "vp": "VA", "v5": "VA", "vr431": "VREF431", "vrf": "VREF_F", "vrdn": "VREF_F",
    "vref": "VREF", "vbd": "VBIAS_DIV", "vbias": "VBIAS", "v25": "VEXP_REF", **{f"vb{i}": f"VB{i}" for i in range(5)},
    "cvc": "PWM_CUT", "ac": "CVC_A", "bc": "XCUT_IN", "xcut": "XCUT", "na": "EXPO_NA", "ee": "EXPO_E",
    "tail": "TAIL", "uexo": "EXPO_OUT", **{f"n{i}{s}": f"N{i}{s.upper()}" for i in range(1, 5) for s in "ab"},
    "n4az": "N4A", "n4bz": "N4B", "bin1": "BIN1", "bin2": "BIN2", "ia": "INA_A", "ib": "INA_B", "oa": "INA_OA",
    "lpf": "LPF", "saw": "PWM_DAC", "sk1": "SK1", "sk2": "SK2", "skout": "DAC_F", "mx": "MIX",
    "cvr": "PWM_RES", "ar": "CVR_A", "br": "CVR_B", "xres": "XRES", "ver": "VIR_E", "uor": "VIR_OUT",
    "bqr": "VIR_B", "rtail": "RES_TAIL", "ri": "RES_RI", "rin1": "RES_IN1", "rin2": "RES_IN2", "rc1": "RES_C1",
    "rc2": "RES_C2", "rdm": "RES_DM", "rdp": "RES_DP", "rdpz": "RES_DP", "resout": "RESOUT", "rfb": "RES_FB",
    "cvv": "PWM_VCA", "av": "CVV_A", "bv": "CVV_B", "xv": "XVCA", "vev": "VIV_E", "uov": "VIV_OUT",
    "bqv": "VIV_B", "vtail": "VCA_TAIL", "vi": "VCA_VI", "vin1": "VCA_IN1", "vin2": "VCA_IN2", "vin2m": "VCA_IN2",
    "vc1": "VCA_C1", "vc2": "VCA_C2", "dm": "VCA_DM", "dp": "VCA_DP", "dpz": "VCA_DP", "vcaout": "VCAOUT",
    "vco": "VCAOUT_R", "lineout": "AUDIO_OUT", "vtrim": "VTRIM", "trp": "PWM_TRIM", "tra": "TRIM_A",
    "adca": "ADC_AUDIO"}


def sim_netlist():
    """The S10 v5c netlist this design is checked against."""
    import os, sys
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:0] = [os.path.join(here, "..", "sim", "s10_5v"), os.path.join(here, "..", "sim", "lib")]
    me = sys.modules.pop("voice", None)            # sim/lib/voice.py (netlist blocks) shares this module's name
    try:
        import s10_5v as T
    finally:
        if me is not None:
            sys.modules["voice"] = me
    return T.core(T.VARIANTS["v5c"])


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
