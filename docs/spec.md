# TouchSynth — MCU-controlled analog mono synth

Status: draft v0.2 (2026-09-26) — updated after simulations S1–S7, see [sim_report.md](sim_report.md)

## 1. Goal

A small analog monophonic synthesizer on one 2-layer PCB, built from JLCPCB **Basic** and
**Promotional Extended** parts (no feeder loading fee, Economic PCBA). No potentiometers and no
mechanical switches: everything is played and edited through capacitive touch pads and set by
the MCU through PWM-derived control voltages.

Parts outside the JLCPCB lists:

| Part | How |
|---|---|
| CH32V003F4P6 or CH32V002F4P6 (TSSOP-20) | from own stock, hand-soldered (footprint DNP in BOM) |
| Power, audio out, MIDI, SWIO | bare pads / 2.54 mm THT footprints, hand-soldered if wanted |

## 2. Block diagram

```
 9–12 V pads ─► SS14 ─► V+ (analog) ─► bias chain VB0..VB4 (ladder)
                     └► 78L05 ─► +5 V (MCU, CD4051, 74HC595, LEDs) ─► VREF 4.5 V (TL072 buffer), VBIAS, V25

 CH32V00x
  ├─ TIM2 CH1 ─► NPN level shift ─► 2N7002 reset ─► DCO: TL072 integrator (10 nF) ──► SAW 4.5…6.5 V
  ├─ TIM2 CH2 ─► PULSE (variable width) ─────────────────────────────┐
  ├─ GPIO     ─► SUB (−1 oct, toggled in TIM2 update ISR) ───────────┤ resistor mixer
  ├─ GPIO     ─► NOISE (LFSR) ───────────────────────────────────────┤ (150 k / 470 k → 10 k)
  │                                                    SAW ──────────┘   │ 1 µF
  ├─ TIM1 CH1..4 PWM (10 bit, 46.9 kHz, 2-bit Σ-Δ dither) ─► 3-pole RC ─►
  │     CV_AMP → LM324 V→I → DCO charge current
  │     CV_CUT → expo converter (LM324 + BC847BS) → ladder tail current
  │     CV_RES → LM324 V→I → resonance diff pair → TL072 diff amp → feedback
  │     CV_VCA → LM324 V→I → VCA diff pair (+470 k anti-offset)
  │                                                                      ▼
  │                  4-pole transistor ladder (5 × BC847BS, 4 × 33 nF) → TL072 2-op-amp INA (G = 11)
  │                                                                      ▼
  │             VCA: BC847BS diff pair + TL072 diff amp, offset trim from R-2R DAC ─► line out
  ├─ ADC A0/A1 + S0..S2 ◄─ 2× CD4051 ◄─ 16 touch pads (13 keys + SHIFT, −, +)
  ├─ S0/S1 (shared) + LATCH ─► 3× 74HC595 ─► 16 LEDs + 8-bit R-2R trim DAC
  ├─ ADC A5 (PD5) ◄─ audio loopback (VCA out, divider 0.75)
  ├─ ADC A7 (PD4) ◄─ temperature diode (MMBT3904 at the expo pair)
  └─ USART RX ◄─ LTV-817 ◄─ MIDI in
```

## 3. Functional requirements

### 3.1 Sound
| Block | Requirement |
|---|---|
| DCO | Pitch from timer, range ≥ C1 (32.7 Hz) … C7 (2093 Hz); saw amplitude constant within ±5 % across range via CV_AMP (charging current ∝ f) |
| Waveforms | saw, pulse with firmware PWM, sub-oscillator (−1 oct square), noise; firmware enables/disables each |
| VCF | 24 dB/oct transistor ladder; cutoff ≈ 30 Hz … 15 kHz from CV_CUT via hardware expo converter (≈ 1.9 oct/V); resonance 0 … self-oscillation from CV_RES; firmware temperature compensation from the PD4 sensor |
| VCA | ≥ 70 dB attenuation when closed; envelope in firmware via CV_VCA; CV feedthrough nulled by firmware-calibrated trim DAC |
| Output | line level ≈ 1 V pp into ≥ 10 kΩ, AC-coupled, referenced to GND |
| Control voltages | 4 × PWM from TIM1, 10 bit @ 46.9 kHz + 2-bit Σ-Δ dither (DMA burst) = 12 bit; residual ripple on CV < −70 dB of full scale; settling < 2 ms (fast envelope attack) |

### 3.2 User interface
- 13 touch keys C…C in piano layout + 3 touch pads SHIFT, −, +.
- SHIFT + key selects a parameter; − / + change it; the 16 LEDs show the selection and the value as a bar.
- Parameters (firmware): waveform mix, pulse width, cutoff, resonance, filter env amount,
  A/D/S/R (amp), A/D (filter), LFO rate/depth/target, glide, octave, arpeggiator, presets.
- MIDI in: note on/off, pitch bend, CC for all parameters.

### 3.3 Touch sensing
- ADC charge-slope method from ch32fun `extralibs/ch32v00x_touch.h`, one routine for both MCUs.
- 16 pads through 2 × CD4051 (shared select S0..S2), one ADC channel per mux.
- Full scan of all 16 pads ≥ 200 Hz; touch delta ≥ 5 × noise (verify in simulation, then on hardware).
- Pads ≈ 10 × 14 mm under solder mask, hatched ground around, no solid copper directly underneath.

### 3.4 Power
- Input 9–12 V DC on 2 pads, reverse-polarity protected, ≤ 60 mA typical.
- Analog rail = protected V+; audio referenced to buffered VREF = 4.5 V (derived from +5 V, independent of V+).
- +5 V from 78L05 for all logic (CH32V runs at 5 V; CD4051 and 74HC595 at 5 V).

## 4. MCU pin map (TSSOP-20, identical for CH32V003 / CH32V002)

| Pin | Port | Function | Pin | Port | Function |
|---|---|---|---|---|---|
| 1 | PD4 | ADC A7 ← temperature diode | 11 | PC1 | SUB osc (GPIO) |
| 2 | PD5 | ADC A5 ← audio loopback | 12 | PC2 | TIM2 CH2 (remap 1) → PULSE |
| 3 | PD6 | USART RX ← MIDI | 13 | PC3 | mux S0 / 595 DATA |
| 4 | PD7 | 74HC595 LATCH (NRST disabled) | 14 | PC4 | mux S1 / 595 CLK |
| 5 | PA1 | touch mux B → ADC A1 | 15 | PC5 | TIM2 CH1 (remap 1) → DCO reset |
| 6 | PA2 | touch mux A → ADC A0 | 16 | PC6 | TIM1 CH1 (remap 1) → CV_AMP |
| 7 | VSS | GND | 17 | PC7 | TIM1 CH2 (remap 1) → CV_CUT |
| 8 | PD0 | NOISE (GPIO) | 18 | PD1 | SWIO |
| 9 | VDD | +5 V | 19 | PD2 | mux S2 |
| 10 | PC0 | TIM1 CH3 (remap 1) → CV_RES | 20 | PD3 | TIM1 CH4 (remap 1) → CV_VCA |

Open: confirm TIM1/TIM2 remap-1 pin assignments and the NRST-disable option bit are identical on CH32V002.

## 5. Preliminary BOM (LCSC)

| Function | Part | Qty | LCSC | Library |
|---|---|---|---|---|
| Op-amps: DCO + VCA diff amp / ladder INA / VREF + res. diff amp | TL072CDT | 3 | C6961 | basic |
| V→I (DCO, RES, VCA), expo reference | LM324DT | 1 | C71035 | basic |
| Ladder (5), expo (1), resonance (1), VCA (1) | BC847BS (dual NPN) | 8 | C41375126 | promo |
| V→I transistors, level shift, temperature diode | MMBT3904 | 5 | C20526 | basic |
| DCO reset switch | 2N7002 | 1 | C8545 | basic |
| Touch mux | CD4051BM96 | 2 | C21379 | promo |
| LED driver + trim DAC | 74HC595D | 3 | C5947 | basic |
| MIDI opto | LTV-817S | 1 | C109227 | basic |
| 5 V regulator | 78L05 (SOT-89) | 1 | C71136 | basic |
| Reverse protection | SS14 | 1 | C2480 | basic |
| LEDs | KT-0603R (red) | 16 | C2286 | basic |
| Passives | 0603 R (1 %) / C from basic list | — | — | basic |
| MCU | CH32V003F4P6 / CH32V002F4P6 | 1 | own stock, DNP | — |

## 6. Simulation plan (ngspice-42, WSL)

| # | Model | Checks |
|---|---|---|
| S1 | DCO core | waveform, reset recovery, amplitude vs. note with CV_AMP law |
| S2 | CV PWM filters | ripple, settling, step response |
| S3 | Ladder VCF | AC response vs. CV_CUT, resonance, self-oscillation threshold, headroom |
| S4 | VCA | gain vs. CV_VCA, off-attenuation, CV feedthrough |
| S5 | Touch channel | pad + CD4051 + ADC sample cap: slope delta finger vs. no finger |
| S6 | Full voice | note sequence with envelopes → WAV file |
| S7 | Power | VREF stability, supply rejection, power-up |

Results: [sim_report.md](sim_report.md). Verification & validation: [verification_plan.md](verification_plan.md).

## 7. Firmware

- Framework: [ch32fun](https://github.com/cnlohr/ch32fun) as git submodule `firmware/ch32fun`, `TARGET_MCU=CH32V003` or `CH32V002`
  (single code base; build verified for both on 2026-09-26 with the `cap_touch_adc` example).
- Toolchain: `riscv64-unknown-elf-gcc` in WSL; flashing with WCH-LinkE via `minichlink`.

## 8. PCB

- 2 layers, 1.6 mm, ≤ 100 × 100 mm (target ≈ 100 × 70 mm), top-side assembly only.
- Touch keyboard along the front edge, electronics behind it.
- KiCad 10.0 (per-user install in `%LOCALAPPDATA%\Programs\KiCad\10.0`, kicad-cli 10.0.6), JLCPCB design rules, LCSC field on every symbol,
  export with Fabrication Toolkit.
