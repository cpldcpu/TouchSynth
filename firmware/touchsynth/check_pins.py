"""Consistency check: firmware pin constants (board.h) against the circuit (hw/design.py + KiCad symbol)
and against the timer / ADC functions of both chip families under the chosen remaps.

  python check_pins.py

Remap tables: CH32V003 from ch32fun/ch32v003hw.h (AFIO_PCFR1_TIM1/2_REMAP_PARTIALREMAP1 comments);
CH32V002/V00x from the CH32V002 datasheet V1.7, table 2-1 (suffix _n = AFIO remap value n).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "hw"))
import design as D                                    # noqa: E402
import sexp as S                                      # noqa: E402

# firmware constant -> design net
NETS = {"PIN_LATCH": "LATCH", "PIN_AUDIO": "ADC_AUDIO", "PIN_MIDI_RX": "MIDI_RX", "PIN_TOUCH_B": "TOUCH_B",
        "PIN_TOUCH_A": "TOUCH_A", "PIN_NOISE": "NOISE", "PIN_CV_RES": "PWM_RES", "PIN_SUB": "SUB",
        "PIN_PULSE": "PULSE", "PIN_S0_DATA": "S0_DATA", "PIN_S1_CLK": "S1_CLK", "PIN_DCO_RST": "DCO_RST",
        "PIN_CV_AMP": "PWM_AMP", "PIN_CV_CUT": "PWM_CUT", "PIN_S2": "S2", "PIN_CV_VCA": "PWM_VCA"}
# peripheral function the firmware uses on that pin (hw.c: cv_code[0..3] -> TIM1 CH1..CH4, TIM2 CH1 reset, CH2 pulse)
FUNC = {"PIN_CV_AMP": "TIM1_CH1", "PIN_CV_CUT": "TIM1_CH2", "PIN_CV_RES": "TIM1_CH3", "PIN_CV_VCA": "TIM1_CH4",
        "PIN_DCO_RST": "TIM2_CH1", "PIN_PULSE": "TIM2_CH2", "PIN_MIDI_RX": "USART1_RX",
        "PIN_TOUCH_A": "ADC_IN0", "PIN_TOUCH_B": "ADC_IN1", "PIN_AUDIO": "ADC_IN5"}
# pin functions under the remaps set in board.h
REMAP = {
    "CH32V003 (TIM1 remap 01, TIM2 remap 01)": {
        "TIM1_CH1": "PC6", "TIM1_CH2": "PC7", "TIM1_CH3": "PC0", "TIM1_CH4": "PD3",
        "TIM2_CH1": "PC5", "TIM2_CH2": "PC2", "USART1_RX": "PD6",
        "ADC_IN0": "PA2", "ADC_IN1": "PA1", "ADC_IN5": "PD5"},
    "CH32V00x (TIM1_RM 0010, TIM2_RM 010)": {
        "TIM1_CH1": "PC6", "TIM1_CH2": "PC7", "TIM1_CH3": "PC0", "TIM1_CH4": "PD3",   # TIM1_CHn_2
        "TIM2_CH1": "PC5", "TIM2_CH2": "PC2",                                         # TIM2_CH1_ETR_2, TIM2_CH2_2
        "USART1_RX": "PD6", "ADC_IN0": "PA2", "ADC_IN1": "PA1", "ADC_IN5": "PD5"},
}


def main():
    src = open(os.path.join(HERE, "board.h"), encoding="utf-8").read()
    fw = dict(re.findall(r"#define (PIN_\w+)\s+(P[A-D]\d)", src))
    adc = dict(re.findall(r"#define ADC_CH_(\w+)\s+(\d+)", src))
    mcu = [p for p in D.PARTS if p.lib_id.startswith("MCU_WCH")][0]
    port_of_pin = {num: name for _, num, name, *_ in S.pins(S.get_symbol(mcu.lib_id))}
    port_of_net = {net: port_of_pin[num] for num, net in mcu.pins.items()}
    errors = 0
    print(f"{'constant':13s} {'port':5s} {'net':10s} {'function':10s} " + " ".join(f"{k[:8]:8s}" for k in REMAP))
    for const, net in NETS.items():
        port = fw.get(const)
        ok = port == port_of_net.get(net)
        func = FUNC.get(const, "GPIO")
        cols = []
        for name, table in REMAP.items():
            if func == "GPIO":
                cols.append("gpio")
            elif table.get(func) == port:
                cols.append("ok")
            else:
                cols.append("FAIL")
                errors += 1
        if not ok:
            errors += 1
        print(f"{const:13s} {port or '-':5s} {net:10s} {func:10s} " + " ".join(f"{c:8s}" for c in cols)
              + ("" if ok else f"   <-- design has {net} on {port_of_net.get(net)}"))
    for key, ch in (("TOUCH_A", "ADC_IN0"), ("TOUCH_B", "ADC_IN1"), ("AUDIO", "ADC_IN5")):
        if f"ADC_IN{adc[key]}" != ch:
            print(f"ADC_CH_{key} = {adc[key]} but the pin is {ch}")
            errors += 1
    unused = sorted(set(port_of_net.values()) - set(fw.values()) - {"VDD", "VSS", "PD1", "PD7"})
    print("MCU ports not used by the firmware:", ", ".join(unused) or "none")
    print("RESULT:", "OK" if errors == 0 else f"{errors} error(s)")
    return errors


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
