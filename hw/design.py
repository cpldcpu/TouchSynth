"""TouchSynth — complete design description (single source of truth for schematic and PCB).

Every analog part carries its ngspice name ('sim' field) from sim/lib/voice.py and the S1..S7 scripts, so the
schematic can be checked against the simulated netlists. Nets used on more than one sheet become global labels.
"""
from collections import OrderedDict
import lcsc as L

SHEETS = OrderedDict([
    ("power", "Power, references and ladder bias"),
    ("mcu", "MCU, programming header and MIDI in"),
    ("touch_led", "Touch pads, multiplexers, LEDs and trim DAC"),
    ("dco", "DCO and CV_AMP"),
    ("vcf", "CV_CUT, expo converter, ladder filter, mixer"),
    ("resonance", "CV_RES and resonance VCA"),
    ("vca", "CV_VCA, VCA, line out and audio loopback"),
])

FP = dict(
    R0603="Resistor_SMD:R_0603_1608Metric", C0603="Capacitor_SMD:C_0603_1608Metric",
    C0805="Capacitor_SMD:C_0805_2012Metric", C1206="Capacitor_SMD:C_1206_3216Metric",
    SOT23="Package_TO_SOT_SMD:SOT-23", SOT363="Package_TO_SOT_SMD:SOT-363_SC-70-6",
    SO8="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", SO14="Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
    SO16="Package_SO:SOIC-16_3.9x9.9mm_P1.27mm", LED="LED_SMD:LED_0603_1608Metric",
    RPACK="Resistor_SMD:R_Array_Convex_4x0603", HDR2="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    HDR3="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", TP="TestPoint:TestPoint_Pad_D1.0mm",
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


def C(sim, value, a, b, vwork, **kw):
    code, pkg = L.pick_c(value, 2 * vwork)
    return add("C", "Device:C", value.replace("u", "µ"), FP["C" + pkg], {1: a, 2: b}, lcsc=code, sim=sim, **kw)


def NPN(sim, c, b, e):
    return add("Q", "Transistor_BJT:MMBT3904", "MMBT3904", FP["SOT23"], {3: c, 1: b, 2: e}, lcsc="C20526", sim=sim)


def PAIR(sim, c1, b1, e1, c2, b2, e2):
    """BC847BS dual NPN (thermally matched pair on one die carrier)."""
    return add("Q", "Transistor_BJT:BC847BS", "BC847BS", FP["SOT363"],
               {6: c1, 2: b1, 1: e1, 3: c2, 5: b2, 4: e2}, lcsc="C41375126", sim=sim)


def TL072(sim, a, b, dec=True):
    """a, b = (in+, in-, out) for units A and B; powered from VP."""
    p = add("U", "Amplifier_Operational:TL072", "TL072", FP["SO8"],
            {3: a[0], 2: a[1], 1: a[2], 5: b[0], 6: b[1], 7: b[2], 8: "VP", 4: "GND"}, lcsc="C6961", sim=sim)
    if dec:
        C(None, "100n", "VP", "GND", 12, note=f"decoupling {p.ref}")
    return p


def CVNET_LIN(n, src, x):
    """S2 LIN network: 1k/100n -> 4k7/33n -> 4k7 / 15k||22n (DC ratio 0.591)."""
    R(f"R1{n}", "1k", src, f"CV{n}_A"); C(f"C1{n}", "100n", f"CV{n}_A", "GND", 5)
    R(f"R2{n}", "4.7k", f"CV{n}_A", f"CV{n}_B"); C(f"C2{n}", "33n", f"CV{n}_B", "GND", 5)
    R(f"R3{n}", "4.7k", f"CV{n}_B", x); R(f"R4{n}", "15k", x, "GND"); C(f"C3{n}", "22n", x, "GND", 5)


def VI(n, x, col, re_value, lm_unit):
    """LM324 unit (in+, in-, out) pins + MMBT3904: I = V(x) / Re."""
    ve, uo, bq = f"VI{n}_E", f"VI{n}_OUT", f"VI{n}_B"
    R(f"RBV{n}", "1k", uo, bq)
    NPN(f"QV{n}", col, bq, ve)
    R(f"REV{n}", re_value, ve, "GND")
    return {lm_unit[0]: x, lm_unit[1]: ve, lm_unit[2]: uo}


# =========================================================================== power
sheet("power")
group("Input, reverse protection, 5 V")
add("J", "Connector_Generic:Conn_01x02", "PWR 9-12V", FP["HDR2"], {1: "VIN", 2: "GND"}, bom=False,
    note="hand-soldered header / pads: pin 1 = +9..12 V")
add("D", "Diode:SS14", "SS14", "Diode_SMD:D_SMA", {2: "VIN", 1: "VP"}, lcsc="C2480", sim="DREV")
C("CBULK", "10u", "VP", "GND", 12)
C("CHF", "100n", "VP", "GND", 12)
add("U", "Regulator_Linear:L78L05_SOT89", "78L05", "Package_TO_SOT_SMD:SOT-89-3", {3: "VP", 2: "GND", 1: "+5V"},
    lcsc="C71136", sim="XREG")
C("C5", "1u", "+5V", "GND", 5)
C("C5B", "100n", "+5V", "GND", 5)
group("References: VREF 4.5 V, VBIAS 1.5 V, V25 2.5 V")
# VREF = 4.5 V, TL072 follower with 10R + 1u snubber; second half = resonance difference amplifier
R("RV1", "1k", "+5V", "VREF_DIV"); R("RV2", "9.1k", "VREF_DIV", "GND"); C("CVR", "10u", "VREF_DIV", "GND", 5)
TL072("XVREF/XRDIF", ("VREF_DIV", "VREF", "VREF"), ("RES_DP", "RES_DM", "RESOUT"))
PARTS[-2].unit_sheets = {2: "resonance"}
PARTS[-2].unit_groups = {2: "Resonance VCA and difference amplifier"}
R("RSN", "10", "VREF", "VREF_SN"); C("CSN", "1u", "VREF_SN", "GND", 5)
R("RB1A", "3.3k", "+5V", "VBIAS"); R("RB1B", "1.5k", "VBIAS", "GND"); C("CBIA", "1u", "VBIAS", "GND", 5)
R("R25A", "10k", "+5V", "V25"); R("R25B", "10k", "V25", "GND"); C("C25", "1u", "V25", "GND", 5)
group("Ladder bias chain")
# ladder bias chain from V+
for sim, v, a, b in [("RB5", "2.2k", "VP", "VB4"), ("RB4", "1k", "VB4", "VB3"), ("RB3", "1k", "VB3", "VB2"),
                     ("RB2", "1k", "VB2", "VB1"), ("RB1", "1k", "VB1", "VB0"), ("RB0", "2.4k", "VB0", "GND")]:
    R(sim, v, a, b)
for i, v in [(4, 9), (3, 8), (2, 7), (1, 6), (0, 4)]:
    C(f"CB{i}", "10u", f"VB{i}", "GND", v)
group("Test points")
add("TP", "Connector:TestPoint", "GND", FP["TP"], {1: "GND"}, bom=False)
for n in ("VP", "+5V", "VREF", "VBIAS", "V25", "VB0", "VB2", "VB4"):
    add("TP", "Connector:TestPoint", n, FP["TP"], {1: n}, bom=False)

# =========================================================================== MCU, SWIO, MIDI
sheet("mcu")
group("MCU (CH32V003 / CH32V002, hand-soldered)")
add("U", "MCU_WCH_RiscV:CH32V003FxPx", "CH32V003F4P6 / CH32V002F4P6", "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
    {1: "LATCH", 2: "ADC_AUDIO", 3: "MIDI_RX", 4: "NRST", 5: "TOUCH_B", 6: "TOUCH_A", 7: "GND", 8: "NOISE",
     9: "+5V", 10: "PWM_RES", 11: "SUB", 12: "PULSE", 13: "S0_DATA", 14: "S1_CLK", 15: "DCO_RST", 16: "PWM_AMP",
     17: "PWM_CUT", 18: "SWIO", 19: "S2", 20: "PWM_VCA"},
    dnp=True, note="own stock, hand-soldered; TIM1/TIM2 remap 1")
C(None, "100n", "+5V", "GND", 5, note="MCU decoupling")
C(None, "1u", "+5V", "GND", 5, note="MCU bulk")
group("Programming (WCH-LinkE)")
add("J", "Connector_Generic:Conn_01x03", "SWIO", FP["HDR3"], {1: "+5V", 2: "SWIO", 3: "GND"}, bom=False,
    note="WCH-LinkE: 5V, SWIO, GND")
add("TP", "Connector:TestPoint", "NRST", FP["TP"], {1: "NRST"}, bom=False)
group("MIDI in")
# MIDI in: current loop -> 220R -> LTV-817S LED (1N4148W reverse protection), open collector pulled up to +5 V
add("J", "Connector_Generic:Conn_01x02", "MIDI IN", FP["HDR2"], {1: "MIDI_4", 2: "MIDI_5"}, bom=False,
    note="DIN-5 pin 4 / pin 5 (or TRS)")
R(None, "220", "MIDI_4", "MIDI_A")
add("D", "Diode:1N4148W", "1N4148W", "Diode_SMD:D_SOD-123", {1: "MIDI_A", 2: "MIDI_5"}, lcsc="C81598")
add("U", "Isolator:LTV-817S", "LTV-817S", "Package_DIP:SMDIP-4_W9.53mm",
    {1: "MIDI_A", 2: "MIDI_5", 3: "GND", 4: "MIDI_RX"}, lcsc="C109227")
R(None, "470", "+5V", "MIDI_RX")

# =========================================================================== touch pads, muxes, LEDs, trim DAC
sheet("touch_led")
group("Touch multiplexers")
KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B", "C'", "SHIFT", "-", "+"]
X_PINS = [13, 14, 15, 12, 1, 5, 2, 4]            # CD4051 X0..X7
for m, com in ((0, "TOUCH_A"), (1, "TOUCH_B")):
    pins = {16: "+5V", 8: "GND", 7: "GND", 6: "GND", 11: "S0_DATA", 10: "S1_CLK", 9: "S2", 3: com}
    for ch in range(8):
        pins[X_PINS[ch]] = f"PAD_{m * 8 + ch + 1}"
    add("U", "4xxx:4051", "CD4051B", FP["SO16"], pins, lcsc="C21379")
    C(None, "100n", "+5V", "GND", 5, note="CD4051 decoupling")
group("Touch pads")
for i, k in enumerate(KEYS):
    kind = "Black" if "#" in k else ("Func" if k in ("SHIFT", "-", "+") else "White")
    add("KEY", "Connector_Generic:Conn_01x01", f"Touch {k}", f"TouchSynth:TouchPad_{kind}", {1: f"PAD_{i + 1}"}, bom=False,
        note="copper touch pad under solder mask")
group("Shift registers (LEDs + trim DAC)")
# 3 x 74HC595: LED0..15, then trim DAC. Shared data/clock with the mux select lines, latch on PD4.
Q_PINS = [15, 1, 2, 3, 4, 5, 6, 7]                # QA..QH
ser = "S0_DATA"
for k in range(3):
    pins = {16: "+5V", 8: "GND", 10: "+5V", 13: "GND", 11: "S1_CLK", 12: "LATCH", 14: ser,
            9: f"SR_CHAIN_{k + 1}" if k < 2 else "NC_SR_OUT"}
    for q in range(8):
        pins[Q_PINS[q]] = f"LED_Q{k * 8 + q}" if k < 2 else f"DAC_Q{q}"
    add("U", "74xx:74HC595", "74HC595", FP["SO16"], pins, lcsc="C5947")
    C(None, "100n", "+5V", "GND", 5, note="74HC595 decoupling")
    ser = f"SR_CHAIN_{k + 1}"
group("LEDs")
for k in range(4):                                # 4.7k arrays + LEDs (~0.6 mA each)
    add("RN", "Device:R_Pack04", "4.7k x4", FP["RPACK"],
        {1: f"LED_Q{4 * k}", 2: f"LED_Q{4 * k + 1}", 3: f"LED_Q{4 * k + 2}", 4: f"LED_Q{4 * k + 3}",
         8: f"LED_A{4 * k}", 7: f"LED_A{4 * k + 1}", 6: f"LED_A{4 * k + 2}", 5: f"LED_A{4 * k + 3}"}, lcsc="C1980")
for i in range(16):
    add("D", "Device:LED", "red", FP["LED"], {2: f"LED_A{i}", 1: "GND"}, lcsc="C2286", note=f"above key {KEYS[i]}")
group("VCA trim DAC (8-bit R-2R)")
# 8-bit R-2R DAC (R = 100k, 2R = 200k), Q0 = LSB; output VTRIM (Thevenin 100k)
R(None, "200k", "DAC_N0", "GND", note="R-2R termination")
for q in range(8):
    R(None, "200k", f"DAC_Q{q}", f"DAC_N{q}" if q < 7 else "VTRIM")
    if q < 7:
        R(None, "100k", f"DAC_N{q}", f"DAC_N{q + 1}" if q < 6 else "VTRIM")

# =========================================================================== DCO
sheet("dco")
group("CV_AMP filter and V-to-I converter")
CVNET_LIN("A", "PWM_AMP", "XAMP")
LM = {}                                            # LM324 unit pin maps collected per unit
LM.update(VI("A", "XAMP", "DCO_INT", "33k", (3, 2, 1)))
group("Integrator and reset")
C("CI", "10n", "SAW", "DCO_INT", 3)
add("Q", "Transistor_FET:2N7002", "2N7002", FP["SOT23"], {3: "SAW", 1: "DCO_GATE", 2: "DCO_INT"},
    lcsc="C8545", sim="MRST")
R("RGS", "2.2k", "DCO_GD", "DCO_GATE")
R("RGP", "10k", "VP", "DCO_GD")
NPN("QLS", "DCO_GD", "DCO_B2", "GND")
R("RLSB", "4.7k", "DCO_RST", "DCO_B2")
group("Test points")
add("TP", "Connector:TestPoint", "SAW", FP["TP"], {1: "SAW"}, bom=False)
add("TP", "Connector:TestPoint", "XAMP", FP["TP"], {1: "XAMP"}, bom=False)

# =========================================================================== VCF
sheet("vcf")
group("CV_CUT filter and exponential converter")
R("R1C", "1k", "PWM_CUT", "CVC_A"); C("C1C", "100n", "CVC_A", "GND", 5)
R("R2C", "4.7k", "CVC_A", "XCUT_IN"); C("C2C", "33n", "XCUT_IN", "GND", 5)
R("R33X", "33k", "XCUT_IN", "XCUT"); R("R12X", "1.5k", "XCUT", "VBIAS"); C("C12X", "100n", "XCUT", "VBIAS", 5)
PAIR("QEA/QEB", "EXPO_NA", "VBIAS", "EXPO_E", "TAIL", "XCUT", "EXPO_E")
R("RREF", "300k", "+5V", "EXPO_NA")
LM.update({10: "V25", 9: "EXPO_NA", 8: "EXPO_OUT"})           # LM324 unit C
R("REXP", "1k", "EXPO_OUT", "EXPO_E"); C("CEXP", "1n", "EXPO_OUT", "EXPO_NA", 12)
group("Transistor ladder (4 poles)")
# ladder: pairs P0..P4 (each pair in one BC847BS), 4 x 33 nF
PAIR("Q1/Q2", "N1A", "BIN1", "TAIL", "N1B", "BIN2", "TAIL")
PAIR("Q3/Q4", "N2A", "VB1", "N1A", "N2B", "VB1", "N1B")
PAIR("Q5/Q6", "N3A", "VB2", "N2A", "N3B", "VB2", "N2B")
PAIR("Q7/Q8", "N4A", "VB3", "N3A", "N4B", "VB3", "N3B")
PAIR("Q9/Q10", "VP", "VB4", "N4A", "VP", "VB4", "N4B")
for i in range(1, 5):
    C(f"CL{i}", "33n", f"N{i}A", f"N{i}B", 1)
R("RBI1", "10k", "BIN1", "VB0"); R("RBI2", "10k", "BIN2", "VB0")
group("Output instrumentation amplifier (G = 11)")
TL072("XINA1/XINA2", ("N4A", "INA_A", "INA_OA"), ("N4B", "INA_B", "LPF"))
R("RI1", "100k", "INA_A", "VREF"); R("RI2", "10k", "INA_OA", "INA_A")
R("RI3", "10k", "INA_OA", "INA_B"); R("RI4", "100k", "LPF", "INA_B")
group("Mixer")
# mixer
R("RMS", "150k", "SAW", "MIX"); R("RMP", "470k", "PULSE", "MIX"); R("RMU", "470k", "SUB", "MIX")
R("RMN", "470k", "NOISE", "MIX"); R("RMX", "10k", "MIX", "VB0"); C("CMX", "1u", "MIX", "BIN1", 3)
group("Test points")
for n in ("TAIL", "LPF", "XCUT_IN"):
    add("TP", "Connector:TestPoint", n, FP["TP"], {1: n}, bom=False)

# =========================================================================== resonance
sheet("resonance")
group("CV_RES filter and V-to-I converter")
CVNET_LIN("R", "PWM_RES", "XRES")
LM.update(VI("R", "XRES", "RES_TAIL", "6.2k", (12, 13, 14)))
group("Resonance VCA and difference amplifier")
C("CRI", "1u", "LPF", "RES_RI", 3); R("RRA", "120k", "RES_RI", "RES_IN1")
R("RRB1", "10k", "RES_IN1", "VB2"); R("RRB2", "10k", "RES_IN2", "VB2")
PAIR("QR1/QR2", "RES_C1", "RES_IN1", "RES_TAIL", "RES_C2", "RES_IN2", "RES_TAIL")
R("RRC1", "4.7k", "VP", "RES_C1"); R("RRC2", "4.7k", "VP", "RES_C2")
R("RRD1", "10k", "RES_C1", "RES_DM"); R("RRD2", "10k", "RES_DM", "RESOUT")
R("RRD3", "10k", "RES_C2", "RES_DP"); R("RRD4", "10k", "RES_DP", "VREF")
C("CRF", "4.7u", "RESOUT", "RES_FB", 5); R("RRF", "22k", "RES_FB", "BIN2")
group("Test points")
for n in ("XRES", "RESOUT"):
    add("TP", "Connector:TestPoint", n, FP["TP"], {1: n}, bom=False)

# =========================================================================== VCA, output, loopback
sheet("vca")
group("CV_VCA filter and V-to-I converter")
CVNET_LIN("V", "PWM_VCA", "XVCA")
LM.update(VI("V", "XVCA", "VCA_TAIL", "4.7k", (5, 6, 7)))
R("ROFFV", "470k", "+5V", "VIV_E")
group("VCA core and offset trim")
C("CVI", "1u", "LPF", "VCA_VI", 3); R("RVA", "33k", "VCA_VI", "VCA_IN1")
R("RVB1", "1k", "VCA_IN1", "VREF"); R("RVB2", "1k", "VCA_IN2", "VREF")
R("RTRM", "1M", "VTRIM", "VCA_IN2"); R("RTRF", "2M", "VCA_IN1", "GND")
PAIR("QA1/QA2", "VCA_C1", "VCA_IN1", "VCA_TAIL", "VCA_C2", "VCA_IN2", "VCA_TAIL")
R("RVC1", "4.7k", "VP", "VCA_C1"); R("RVC2", "4.7k", "VP", "VCA_C2")
R("RD1", "10k", "VCA_C1", "VCA_DM"); R("RD2", "22k", "VCA_DM", "VCAOUT")
R("RD3", "10k", "VCA_C2", "VCA_DP"); R("RD4", "22k", "VCA_DP", "VREF")
group("Difference amplifier, line out")
TL072("XDCO/XDIF", ("VREF", "DCO_INT", "SAW"), ("VCA_DP", "VCA_DM", "VCAOUT"))
PARTS[-2].unit_sheets = {1: "dco", 3: "dco"}
PARTS[-2].unit_groups = {1: "Integrator and reset", 3: "Integrator and reset"}
C("COUT", "10u", "VCAOUT", "LINEOUT", 5); R(None, "100k", "LINEOUT", "GND", note="output bleeder")
add("J", "Connector_Generic:Conn_01x02", "LINE OUT", FP["HDR2"], {1: "LINEOUT", 2: "GND"}, bom=False)
group("Audio loopback to PD5")
R("RLB1", "10k", "VCAOUT", "ADC_AUDIO"); R("RLB2", "15k", "ADC_AUDIO", "GND"); C("CLB", "1n", "ADC_AUDIO", "GND", 5)
group("Test points")
for n in ("VCAOUT", "XVCA", "VTRIM"):
    add("TP", "Connector:TestPoint", n, FP["TP"], {1: n}, bom=False)

# LM324 (all four units + supply), placed on the vcf sheet
sheet("vcf")
group("CV_CUT filter and exponential converter")
LM.update({4: "VP", 11: "GND"})
add("U", "Amplifier_Operational:LM324", "LM324", FP["SO14"], LM, lcsc="C71035",
    sim="XUA/XUEXP/XUR/XUV").unit_sheets = {1: "dco", 2: "vca", 4: "resonance"}
PARTS[-1].unit_groups = {1: "CV_AMP filter and V-to-I converter", 2: "CV_VCA filter and V-to-I converter",
                         4: "CV_RES filter and V-to-I converter"}
C(None, "100n", "VP", "GND", 12, note="LM324 decoupling")


def nets():
    out = {}
    for p in PARTS:
        for pin, n in p.pins.items():
            out.setdefault(n, []).append((p.ref, pin))
    return out


if __name__ == "__main__":
    N = nets()
    print(len(PARTS), "parts,", len(N), "nets")
    single = {n: v for n, v in N.items() if len(v) < 2}
    print("single-pin nets:", single)
    from collections import Counter
    print(Counter(p.sheet for p in PARTS))
