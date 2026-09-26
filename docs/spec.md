# TouchSynth — MCU-controlled analog mono synth

Status: draft v0.1 (2026-09-26)

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
 9–12 V pads ─► reverse protection ─► V+ (analog) ─► mid-rail ref VMID (buffered)
                                   └► 78L05 ─► +5 V (MCU, CD4051, 74HC595, LEDs)

 CH32V00x
  ├─ TIM2 CH1 ─► reset pulse ──► DCO core: TL072 integrator + 2N7002 reset ──► SAW
  ├─ TIM2 CH2 ─► PULSE (variable width) ──────────────────────────────┐
  ├─ GPIO     ─► SUB (−1 oct, toggled in TIM2 update ISR) ────────────┤ resistor
  ├─ GPIO     ─► NOISE (LFSR) ────────────────────────────────────────┤ mixer
  │                                                    SAW ───────────┘   │
  ├─ TIM1 CH1..4 PWM ─► RC + LM324 filters ─► CV_AMP, CV_CUT, CV_RES, CV_VCA
  │                                                                       ▼
  │                        4-pole transistor ladder VCF (BC847BS) ◄─ CV_CUT, CV_RES
  │                                                                       ▼
  │                                     VCA (BJT differential pair) ◄─ CV_VCA
  │                                                                       ▼
  │                                        TL072 output buffer ─► pads / 3.5 mm jack
  ├─ ADC A0/A1 + S0..S2 ◄─ 2× CD4051 ◄─ 16 touch pads (13 keys + SHIFT, −, +)
  ├─ S0/S1 (shared) + LATCH ─► 2× 74HC595 ─► 16 LEDs (one per pad)
  └─ USART RX ◄─ LTV-817 ◄─ MIDI in
```

## 3. Functional requirements

### 3.1 Sound
| Block | Requirement |
|---|---|
| DCO | Pitch from timer, range ≥ C1 (32.7 Hz) … C7 (2093 Hz); saw amplitude constant within ±5 % across range via CV_AMP (charging current ∝ f) |
| Waveforms | saw, pulse with firmware PWM, sub-oscillator (−1 oct square), noise; firmware enables/disables each |
| VCF | 24 dB/oct transistor ladder; cutoff ≈ 30 Hz … 15 kHz from CV_CUT (linear V→I, firmware applies exp curve); resonance 0 … self-oscillation from CV_RES |
| VCA | ≥ 70 dB attenuation when closed; envelope in firmware via CV_VCA |
| Output | line level ≈ 1 V pp into ≥ 10 kΩ, AC-coupled, referenced to GND |
| Control voltages | 4 × PWM from TIM1, 12 bit @ 11.7 kHz; residual ripple on CV < −70 dB of full scale; settling < 2 ms (fast envelope attack) |

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
- Analog rail = protected V+; audio referenced to buffered VMID.
- +5 V from 78L05 for all logic (CH32V runs at 5 V; CD4051 and 74HC595 at 5 V).

## 4. MCU pin map (TSSOP-20, identical for CH32V003 / CH32V002)

| Pin | Port | Function | Pin | Port | Function |
|---|---|---|---|---|---|
| 1 | PD4 | 74HC595 LATCH | 11 | PC1 | SUB osc (GPIO) |
| 2 | PD5 | spare (ADC A5) | 12 | PC2 | TIM2 CH2 (remap 1) → PULSE |
| 3 | PD6 | USART RX ← MIDI | 13 | PC3 | mux S0 / 595 DATA |
| 4 | PD7 | NRST | 14 | PC4 | mux S1 / 595 CLK |
| 5 | PA1 | touch mux B → ADC A1 | 15 | PC5 | TIM2 CH1 (remap 1) → DCO reset |
| 6 | PA2 | touch mux A → ADC A0 | 16 | PC6 | TIM1 CH1 (remap 1) → CV_AMP |
| 7 | VSS | GND | 17 | PC7 | TIM1 CH2 (remap 1) → CV_CUT |
| 8 | PD0 | NOISE (GPIO) | 18 | PD1 | SWIO |
| 9 | VDD | +5 V | 19 | PD2 | mux S2 |
| 10 | PC0 | TIM1 CH3 (remap 1) → CV_RES | 20 | PD3 | TIM1 CH4 (remap 1) → CV_VCA |

Open: confirm TIM1/TIM2 remap-1 pin assignments are identical on CH32V002 (datasheet table 2-2).

## 5. Preliminary BOM (LCSC)

| Function | Part | LCSC | Library |
|---|---|---|---|
| Op-amp (DCO, VMID, output) | TL072CDT | C6961 | basic |
| Op-amp (CV filters) | LM324DT | C71035 | basic |
| Ladder / VCA transistors | BC847BS (dual NPN) | C41375126 | promo |
| Matched pairs (alt.) | MMDT3904 | C41375125 | promo |
| DCO reset switch | 2N7002 | C8545 | basic |
| Touch mux | CD4051BM96 | C21379 | promo |
| LED driver | 74HC595D | C5947 | basic |
| MIDI opto | LTV-817S | C109227 | basic |
| 5 V regulator | 78L05 (SOT-89) | C71136 | basic |
| Reverse protection | SS14 | C2480 | basic |
| LEDs | KT-0603R (red) | C2286 | basic |
| Passives | 0603 R / C from basic list | — | basic |

## 6. Simulation plan (ngspice-42, WSL)

| # | Model | Checks |
|---|---|---|
| S1 | DCO core | waveform, reset recovery, amplitude vs. note with CV_AMP law |
| S2 | CV PWM filters | ripple, settling, step response |
| S3 | Ladder VCF | AC response vs. CV_CUT, resonance, self-oscillation threshold, headroom |
| S4 | VCA | gain vs. CV_VCA, off-attenuation, CV feedthrough |
| S5 | Touch channel | pad + CD4051 + ADC sample cap: slope delta finger vs. no finger |
| S6 | Full voice | note sequence with envelopes → WAV file |
| S7 | Power | VMID stability, supply rejection |

## 7. Firmware

- Framework: [ch32fun](https://github.com/cnlohr/ch32fun) as git submodule `firmware/ch32fun`, `TARGET_MCU=CH32V003` or `CH32V002`
  (single code base; build verified for both on 2026-09-26 with the `cap_touch_adc` example).
- Toolchain: `riscv64-unknown-elf-gcc` in WSL; flashing with WCH-LinkE via `minichlink`.

## 8. PCB

- 2 layers, 1.6 mm, ≤ 100 × 100 mm (target ≈ 100 × 70 mm), top-side assembly only.
- Touch keyboard along the front edge, electronics behind it.
- KiCad 10.0 (per-user install in `%LOCALAPPDATA%\Programs\KiCad\10.0`, kicad-cli 10.0.6), JLCPCB design rules, LCSC field on every symbol,
  export with Fabrication Toolkit.
