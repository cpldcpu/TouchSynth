# TouchSynth Poly: specification

Status: draft 0.4 (2026-10-18), branch `polyphonic_hw`. Simulated (S9, S10) and partly tested on board 1;
nothing of the new hardware is built yet.

## 1. Goal

A polyphonic analog synthesizer with 4 to 8 voices, played and edited from a computer over USB. Each voice is an
identical plug-in card: a CH32V006 generating the oscillators digitally (PWM DAC) and the analog filter and VCA
of TouchSynth rev 0.1. A backplane holds the USB controller, the voice bus, power and the stereo mixer.
Single 5 V supply (USB-C). Voice cards can be programmed, run and debugged on their own.

Constraints as before: JLCPCB Basic and Promotional Extended parts only; MCUs (own stock), headers and
connectors hand-soldered. *[2026-10-20]* Exception: the backplane's CH32V203C8T6 is assembled from the user's JLCPCB
personal stock (C3001172).

### Decisions so far

| Topic | Decision | Basis |
|---|---|---|
| Oscillators | digital, on the V006's PWM DAC; no analog DCO | DCO and DAC saw measure the same on board 1 (S9d); 3 oscillators, any waveform, the kettle in firmware |
| DAC | 187.5 kHz carrier (TIM2 centre-aligned, 2 × 128), 7 bit, second-order error feedback, one sample per carrier period (oscillators) or 15.625 kHz interpolated (modal drums) | S9: images, not bits, limit the quality; implemented and recorded on board 1 |
| Supply | single 5 V; MCU on a 3.3 V LDO; CJ431 2.5 V reference | S10 (v5m: Microchip MCP6002 model) |
| Voice bus | UART broadcast + SYNC line + per-slot reset; timed events on a 1 ms frame clock, fixed presentation delay | section 5, [bus.md](bus.md) |
| Controller | CH32V203C8T6, LQFP-48 (USB-MIDI, CDC; USB audio of the mix via its ADCs as an option); SWIO direct (8 GPIOs), the 8 NRST lines through a 74HC595 on SPI1 (backplane.md 3.5) | section 4 |
| Slots | 8 on the backplane, populated as cards are built | |
| Backplane PCB | 4 layers (planned as 2; backplane.md 7.1), like the voice cards | section 4 |
| Card format | at most 50 × 50 mm, 4 layers (fallback: 2 layers, about 50 × 60 mm); backplane connector on one edge (on a 50 × 60 mm card: a short edge), so the backplane stays small; LEDs and debug connectors (SWIO, line out) on the opposite edge; 10 mm slot pitch, backplane within 100 × 100 mm | section 3.3 |
| Controls | none on the instrument (no touch UI, no knobs): played and edited only over USB, from the computer or a USB-MIDI keyboard | |
| Voice MCU | CH32V006F8P7 (TSSOP-20, hand-soldered); the board 1 pin map carries over unchanged | section 3.2 |
| DAC variants | standard: one PWM, 187.5 kHz, 7 bit, second-order error feedback (−67 to −87 dB in the three-oscillator model); assembly option: dual PWM (high + low byte, 7 + 7 bit, 128:1) at 187.5 kHz: −82 to −92 dB, near an ideal DAC, at about the same CPU; a half-rate firmware mode (oscillators at 93.75 kHz, interpolated on the 187.5 kHz carrier) saves 28 % of the CPU per sample (board 1: 136 instead of 189 cycles); its cost is the polyBLEP saw's aliasing at the lower rate, −51 dB re the fundamental at C5 against −56 dB at full rate, nothing measurable below C5 (the C6/C7 and three-oscillator comparisons came from an experiment build that played those notes at half level; not repeated, as the voice firmware has no half-rate mode yet): full rate by default, half rate as a CPU reserve. The carrier stays at 187.5 kHz: a 93.75 kHz carrier reaches the line out at −39 dB through the 30 kHz filter (S11) | S9b, board 1 (docs/results/hw_board1_half_rate.csv) |
| Slot addresses | by enumeration over the per-slot NRST lines; no ID pins on the card | section 5 |
| Not used | the V006's internal op-amp, a temperature sensor for the expo pair, a separate UART console | |

## 2. Overview

```
 backplane                                                  voice card (x4..8, identical)
 ───────────────────────────────────────────────            ───────────────────────────────────────────────────
 USB-C 5 V ─► fuse/TVS ─► 5V ──────────────────────────────► 5V ─► 22 R / 3 × 100 u ─► analog rail (ladder, op-amps)
                          └► 3.3 V LDO (controller)                 ├► XC6206 3.3 V ─► MCU (PWM reference)
                                                                     └► CJ431 2.5 V ─► VREF, VEXP_REF, VBIAS
 CH32V203 (crystal, 144 MHz)                                voice CH32V006 (3.3 V, synchronised HSI)
   USB FS device: MIDI + CDC (+ audio in, option)             TIM2 CH2 ─► PWM DAC ─► 2-pole filter ─► mixer
   voice allocation, parameters, presets                      TIM1 CH1..4 ─► VCA trim, CV_CUT, CV_RES, CV_VCA
   USART TX ──── broadcast ──────────────────────────────►    USART RX (DMA ring)
   USART RX ◄─── shared open-drain return ◄───────────────    USART TX (enabled only when addressed)
   timer ─────── SYNC 1 kHz ─────────────────────────────►    EXTI + SysTick: clock ratio
   GPIO x8 ───── NRST per slot ──────────────────────────►    NRST (enumeration, single-voice reset)
   GPIO x8 ───── SWIO per slot (in-system programming) ──►    SWIO
 stereo mixer (MCP6002, 5 V, VREF 2.41 V) ◄── AUDIO_OUT ◄──    VCA out (AC-coupled line level)
   ├► line out L/R                                            └► loopback divider ─► ADC (calibration)
   └► ADC1/ADC2 of the CH32V203 (USB audio, option)
```

## 3. Voice card

### 3.1 Signal path and parts

| Block | Design | Against rev 0.1 |
|---|---|---|
| Oscillators | firmware: up to 3 saw / pulse oscillators (polyBLEP), modal drums, noise; 184 cycles per sample for 3 oscillators (board 1); *[2026-10-20]* 31–47 after the render rewrite (bench card, bus.md 9.5) | replaces DCO, sub, pulse, noise GPIOs |
| PWM DAC | TIM2 CH2, 187.5 kHz, 7 bit, error feedback (dsp.c); option: dual PWM with TIM2 CH4 as low byte (into the filter input through 1M + 330k = 1.33 MΩ next to the filter's 11k, calibrated in firmware, section 3.5) on the same carrier | was the pulse output |
| Reconstruction filter | unity-gain 2-pole Sallen-Key (Butterworth), MCP6002 half: 11k / 11k, C1 2 × 330 pF (feedback), C2 330 pF, all C0G (the C0G values on the JLCPCB lists near this range are 100 pF, 330 pF and 2.2 nF), fc 31 kHz. S11 (10k, 750 pF, 375 pF, 30 kHz): the 187.5 kHz carrier at −74 dB re full scale at the line out (without: −42 dB), droop 0.04 dB at 10 kHz, 0.8 dB at 20 kHz. The dual-PWM option runs on the same 187.5 kHz carrier and uses the same filter. Fixed cutoff, not voltage-controlled: the firmware shapes everything below Nyquist, the filter only removes carrier and images | new (rev 0.1 earmark: carrier crosstalk) |
| Mixer into the ladder | the filtered DAC (0–3.3 V full scale) through 240 kΩ: the drive of rev 0.1's saw (2 Vpp through 150 kΩ), S11 (on board 1 the DAC came through 470 kΩ, 3–10 dB less signal-to-noise) | |
| Expo converter | as rev 0.1, VBIAS 1.0 V (buffered), VEXP_REF 1.25 V (VREF / 2: the expo op-amp holds the reference transistor's collector there; rev 0.1: V25 = 2.5 V), RREF 470 kΩ from VREF, divider 18k / 1k5 | S10 v5r |
| Ladder | 4 poles, 10 nF, bias chain 620 Ω / 4 × 1.5 kΩ / 3.3 kΩ from the analog rail (VB0 1.66 V, spacing 0.76 V) | 33 nF; 2k2 / 4 × 1k / 2k4 |
| INA, difference amps, references | MCP6002 (rail-to-rail): VREF buffer, INA (2), resonance and VCA difference amps, reconstruction filter = 6 units, 3 × MCP6002 (VREF + filter, INA, difference amps) | 3 × TL072 |
| V→I converters, VBIAS | LM324: expo, resonance and VCA converters, and the VBIAS buffer (1.0 V, inside the LM324's input range; it must stay buffered, the expo divider's CV current would move a bare divider by up to 0.6 V); resonance R4 12k / R_E 3k6, VCA R4 7k5 / R_E 2k2; VCA anti-offset 240k from VREF | 4 units used |
| VCA trim | TIM1 CH1 (the former CV_AMP channel) through 2 × (10k, 1 µF) and 680k into vin2, 5.1M from vin1 to ground (RTRF): ±2.4 mV at the pair's input around mid scale | R-2R DAC + 74HC595, 1M |
| Stereo pan (S13, variant A) | current steering on the VCA collectors: two BC847BS steering pairs, L bases on VREF, R bases on PAN_B = VREF − 143…+149 mV from PC5 (TIM2 CH1 PWM through 27k, with 24k to +3V3 and 3k to VREF, 1 µF: 66 Hz, centre at 49 % duty); L = α·ΔI, R = (1−α)·ΔI (linear law; the firmware raises CV_VCA towards the centre for constant power and caps it at 70.6 % at hard pan). VCA bases on VCA_BIAS 1.89 V (2.4k / 7.5k from VREF, 1 µF), R4V 3k, R_E 1.2k (the same 0.6 mA tail), RTRF 5.1M; 4.7k loads; both difference amps 10k / 30k (G = 3.0), 33k to ground; a fourth MCP6002 (R amp; unit B a follower on VREF), 100 Ω, 10 µF, 100k. S13 at 5 V and 4.6 V: centre −3.5 dB per channel, separation 47–50 dB, THD 0.47 %, SNR 68.8 dB, smallest V_CE 0.50 V, 4.7 mA analog. A steering-pair mismatch gives ±27 mV of click per mV at the centre (opposite in L and R), none at hard pan | new (mono out) |
| CV PWM | TIM1, 46.9 kHz, 10 bit + 2-bit dither, 0–3.3 V; dither by DMA burst (16-halfword circular table, 4 phases × 4 channels, into TIM1->DMAADR) instead of the 46.9 kHz interrupt: board 1 frees ~9 % of the CPU (the interrupt cost ~90 cycles per call), DAC refill −8 %, and 164 B of RAM | interrupt, 0–5 V |
| Audio loopback | divider to the 3.3 V ADC (PC4) | 5 V ADC, PD5 |
| Self-test (option) | dividers from the analog rail and the ladder bias VB0 to free ADC pins: assembly faults show at power-up | |
| Supply | 5 V in; analog rail VA through 22 Ω + 3 × 100 µF X5R 1206 (about 35 µF each at 5 V; no 220 µF part on the JLCPCB lists, ceramics instead of tantalums at 79 % of their rating); XC6206 3.3 V for the MCU (the PWM outputs are duty × VDD); CJ431 2.5 V VREF (1k feed, 10k / 10 µF filter before the buffer); the programmer's 5 V through a B5819W (no back-feeding into the backplane; the card then runs at about 4.6 V, simulated) | 9–12 V, SS14, 78L05 |
| LEDs | power (from 3.3 V), "playing", status (bus, errors), on the debug edge | 16 + UI |

Simulated performance of the analog core at 5 V (S10, variant v5m with Microchip's MCP6002 model, against rev 0.1
at 8.6 V): cutoff 19 Hz – 31 kHz (rev 0.1: 20 Hz – 20 kHz; trim with the expo divider), self-oscillation from the
same resonance CV, THD 0.44 % at full drive (0.58 %), signal-to-noise 68–69 dB (70 dB), supply rejection
−61 / −65 / −78 dB at 100 Hz / 1 kHz / 10 kHz (−80 / −84 / −71 dB), smallest V_CE 0.51 V, 3.6 mA analog current
(9.1 mA). Supply per card about 10 mA at 5 V (analog 3.6 mA, MCU ~5 mA, LEDs).

The card as built (S10 variant v5c: the DAC chain, the supply and reference filters, the VCA trim and the
difference-amp resistors above; hw/check_sim.py checks the schematic against this netlist): cutoff 19 Hz –
30.5 kHz, resonance and self-oscillation unchanged, THD 0.47 %, signal-to-noise 68.8–69.4 dB, supply rejection
−69 / −66 / −77 dB (the CJ431 filter gains 8 dB at 100 Hz), smallest V_CE 0.50 V, VCA difference-amp inputs
2.44–3.13 V, 3.9 mA. At 4.6 V (programmer power) the same figures, smallest V_CE 0.37 V. Lower supplies (S13 card
with behavioural op-amps): the audio path holds down to 4.0 V (THD and levels unchanged), but the extreme CV corners
(full cutoff with full resonance) saturate the expo and resonance V→I transistors below about 4.3 V on the analog
rail (V_CE 0.30 V at 4.4 V, 0.23 V at 4.2 V, 0.13 V at 4.0 V). With RFILT 22 Ω (0.1 V drop at 4.7 mA) full
function needs about 4.4 V at the card's input: USB's 4.75 V minimum with typical cable loss; on weak ports the
external 5 V input. RFILT stays 22 Ω (47 Ω would halve the inrush but cost 0.22 V permanently).

### 3.2 MCU pin map (CH32V006F8P7, TSSOP-20, 3.3 V)

The board 1 pin functions carry over unchanged: TIM1 and TIM2 keep remap 2 (TIM1_RM = 0010, TIM2_RM = 010),
USART1 its default pins. Reset is PD7 (pin 4; PA4 is bonded to the same pin inside the TSSOP-20, so it is never
configured as an output). All 18 GPIO are assigned or reserved (PC5: pan PWM).

| Pin | Port | Function | Pin | Port | Function |
|---|---|---|---|---|---|
| 1 | PD4 | SYNC in (EXTI) | 20 | PD3 | TIM1 CH4 → CV_VCA |
| 2 | PD5 | USART1 TX → return line | 19 | PD2 | ADC A3 ← self-test: analog rail / 2 (option) |
| 3 | PD6 | USART1 RX ← broadcast | 18 | PD1 | SWIO |
| 4 | PD7 | NRST ← backplane | 17 | PC7 | TIM1 CH2 → CV_CUT |
| 5 | PA1 | external clock in (XI; DNP 0 Ω link), else spare | 16 | PC6 | TIM1 CH1 → VCA trim |
| 6 | PA2 | ADC A0 ← self-test: ladder bias VB0 (option) | 15 | PC5 | TIM2 CH1 → pan (PAN_B) |
| 7 | VSS | GND | 14 | PC4 | ADC A2 ← audio loopback |
| 8 | PD0 | LED "playing" | 13 | PC3 | LED status |
| 9 | VDD | +3.3 V | 12 | PC2 | TIM2 CH2 → PWM DAC |
| 10 | PC0 | TIM1 CH3 → CV_RES | 11 | PC1 | TIM2 CH4 → DAC low byte (dual-PWM option) |

Pin numbers from the datasheet's pinout (CH32V006 DS V2.0, CH32V006F8P7); the TSSOP-20 pinout matches the
CH32V003's, so KiCad's `MCU_WCH_RiscV:CH32V003FxPx` symbol and `Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm` (as on
rev 0.1) fit without a custom symbol. Hand-soldered.

**DMA allocation** (CH32V00X reference manual V1.4, table 8-2; measured on board 1):

| Channel | Requests (V006) | Use |
|---|---|---|
| ch1 | ADC1, TIM2_CH3 | PWM DAC: TIM2 CC3 request once per carrier period (CMS = 10), 1 byte per period into CH2CVR; dual option: a TIM2 DMA burst from the same request (CH2, CH3, CH4: 3 bytes per period) |
| ch2 | SPI1_RX, TIM1_CH1, TIM2_UP | free (rev 0.1: the DAC on TIM2_UP, two requests per period) |
| ch4 | USART1_TX, TIM1_CH4/TRIG/COM | USART1 TX (return line), if by DMA |
| ch5 | **USART1_RX, TIM1_UP**, TIM2_CH1 | USART1 RX ring (voice bus) |
| ch6 | USART2_TX, I2C1_TX, TIM1_CH3 | CV dither burst: TIM1 with CCDS = 1 and CC3DE (request on the update event) |
| ch3, ch7 | SPI1_TX / TIM1_CH2; USART2_RX / TIM2_CH2/CH4 | free (ch7: dual PWM if the DAC stays on TIM2_UP) |

The ADC (loopback calibration, self-test) runs without DMA, by interrupt or polling: calibration mutes the voice,
so the CPU is free then.

TIM1_UP and USART1_RX share ch5, so the burst runs on the CC3 request (ch6; ch3 via CC2DE works too). With CCDS = 1
the CCx request comes on the update event; preload (OCxPE) must stay on; enable the DMA channel before the request.
All three (DAC, CV burst, USART1 RX ring) ran together on board 1 during a tune: 1353 of 1353 bytes received, no
UART errors, no DAC overruns, CV pattern intact. The noise LFSR that lived in the TIM1 interrupt moves into the DSP.

**DAC loading** (board 1, register read-back synchronised to the update flag and pin timing; all formats exact):

| Format | Mechanism | Bytes per period | Transfers/s | Cycles per period (3 osc, one build) |
|---|---|---|---|---|
| 0 (rev 0.1, removed from the voice firmware) | TIM2_UP on ch2 → CH2CVR, each code twice | 2 | 375 000 | 189 |
| 4 (voice firmware) | CMS = 10, CC3 at 64 → ch1 → CH2CVR: written on the up-count, loaded at the top, the pulse around the bottom stays symmetric | 1 | 187 500 | 184 |
| 3 (voice firmware, `DAC_DUAL=1`) | as 4, a TIM2 burst (DMACFGR, DBA = CH2CVR, 3 transfers) writes [hi, 64, lo] | 3 | 562 500 | 190 |
| 2 (dual) | ch2 TIM2_UP → CH2CVR and ch7 TIM2_CH4 (CCDS = 1) → CH4CVR, started in one DMAINTENR write | 4 | 750 000 | 187 |
| 1 (dual) | TIM2 burst on TIM2_UP: [hi, 64, lo] twice per period | 6 | 1 125 000 | 196 |

With CMS = 01 the request falls on the down-count and every pulse comes out asymmetric; CMS = 11 requests twice per
period. The dual split is high = v >> 8, low = round((v & 255) × k / 256), one multiply. Format 0 has a start-up
dependency: its pulses are symmetric only if the first request falls on a bottom update, which the current code
reaches by chance (more than 128 cycles between CEN and UDE); waiting for CTLR1.DIR = 1 before UDE fixes it. The
voice firmware uses format 4 (dual: format 3); in its build the 3 oscillators take 175 cycles per period (dual PWM:
141, its split has no error feedback; *[2026-10-20]* after the render rewrite 31–47 cycles per period, bus.md 9.5). Start sequence (hw_dac_start): TIM2 reset through RCC, configured while
stopped, preloads loaded with UG, flags cleared; the DMA channel armed and CC3DE set with the counter at 0; CEN
last. On board 1, 1000 starts (format 4) and 470 (format 3), after DCO mode, an ADC conversion or a running DAC: no
transfer before the first compare, exactly one entry at the first request, read-back exact over 2.0 M and 0.96 M
requests (an early experiment once transferred 49 bytes at start; the reset removes any stale request). The
format 3 burst is complete by CNT 82 (request at 64, top at 128).

### 3.3 Connectors

**Backplane connector**, 2×8 pin header 2.54 mm (card underside):

| Pin | Signal | Pin | Signal |
|---|---|---|---|
| 1 | +5 V | 2 | +5 V |
| 3 | GND | 4 | GND |
| 5 | AUDIO_L | 6 | AUDIO_GND |
| 7 | AUDIO_R | 8 | GND |
| 9 | SYNC | 10 | RX (broadcast in) |
| 11 | TX (return, open drain) | 12 | NRST |
| 13 | GND | 14 | SWIO |
| 15 | CLK_IN (option) | 16 | GND |

All logic at 3.3 V (both MCUs). *[2026-10-20]* On the backplane, slot 1's pins 15 and 14 can carry the stereo mix
(send L / R, through 220 Ω) instead of CLK and SWIO, and its pins 3 / 4 are the effects card's loop-through
return instead of GND, for an effects card in that slot (backplane.md 5.1); a voice card ignores pin 15 (not-fitted
link), needs SWIO only for programming, and grounds pins 3 / 4 harmlessly.

**Programming header**, 1×3 (card top, left, above the MCU): +5 V, SWIO, GND, the rev 0.1 order. The WCH-LinkE's 5 V
powers the whole
card (about 10 mA), analog part included, so a card runs on the bench with only the programmer attached. The
console works over SWIO as on rev 0.1.

**Line out**, 1×3 (card top, right): AUDIO_L, AUDIO_R, GND, for the scope or an amplifier in standalone operation.

**Card format:** 50 × 50 mm, 4 layers: F.Cu signals and all parts; In1 solid GND; In2 supply planes (VA under the
analog part, +3V3 under the MCU and the debug edge, +5V in a strip along the right and bottom edges); B.Cu signals
only. JLCPCB standard rules (0.15 / 0.15 mm, supplies 0.3 mm, vias 0.3 / 0.6 mm, tented). Passives 0402 where the
JLCPCB lists have the value (0603 did not fit: ten parts found no place at 50 × 50 mm); 11k, 240k, 2M, 3.6k, 620,
680k, 3k, 30k, 5.1M, the 33 nF and the 10 µF bias capacitors at 3.7–4.4 V stay 0603. 13 test points.

The backplane connector (2×8 right-angle male header, 20 mm long) sits centred on the bottom edge, body flush with
the edge, pins protruding, and plugs into a vertical 2×8 socket on the backplane at 10 mm pitch. Seen from the
parts side with the connector down, **pin 1 is on the right**: the supply and audio pins (1–8) are on the right
half, the bus (9–16) on the left, so the analog core and the supply input sit on the right and the MCU on the left.
The top edge carries the three LEDs,
the programming header and the line-out header (right-angle, pointing out of the edge). All parts on the top side,
at most about 6 mm high; 1.5 mm along both side edges stays free of parts for the card guides. From bottom to top:
analog core, MCU and DAC filter, LEDs and headers. The R difference amp and both output stages sit beside J1
pins 1–8, the steering pairs on the VCA pair; SWIO runs along the left and bottom edges (pre-routed). AUDIO_GND
(pin 6) reaches both output bleeders' ground pads (one track). VREF (128 mm) and the VBIAS divider
node (102 mm, filtered DC) are long tracks: candidates for a VREF region on In2 in the next revision. Silkscreen: name,
rev, labels for
headers, LEDs, test points and blocks on the top; artwork, the J1 pinout and the project URL on the bottom.

### 3.4 Standalone mode

Without SYNC pulses after reset, the voice firmware runs as a mono synth on its own HSI, controlled from the SWIO
console like board 1 (notes, tunes, patches, calibration via the loopback). The bench tools (`tools/synthtest.py`,
`hwtest.py`, `scope.py`) then work on a single card.

### 3.5 Dual-PWM option: weighting and calibration

The high byte (TIM2 CH2) enters the reconstruction filter's input through its 11 kΩ, the low byte (TIM2 CH4)
through 1 MΩ + 330 kΩ = 1.33 MΩ: 7 + 7 bit on the 187.5 kHz carrier. Error sources of the weight ratio: resistor
tolerance (1 %) and the pins' output resistance (tens of Ω, 0.25–0.5 % of 11 kΩ); both pins share VDD and the timer, so
the supply and the
pulse timing cancel. A ratio error ε gives a step error of ε × one high-byte step at every high-byte transition:
1 % = 1/12 800 of full scale, about −82 dB, at the option's noise floor (S9b already ran with a 1 % error). So
calibration only matters beyond ~2 %, but it is cheap:

1. **Overlap, not precision:** 1.33 MΩ instead of 128 × 11 kΩ = 1.41 MΩ makes the low byte's span ~6 % larger
   than one high-byte step, so no tolerance leaves a gap. The firmware splits each value with the measured ratio
   k (low codes per high step, e.g. 120.9): high = floor(q / k), low = round(q − high × k); one multiply and
   shift per sample.
2. **Measuring k with the card's own loopback (null method):** filter and VCA open, alternate at ~100 Hz between
   two nominally equal codes (h, 0) and (h − 1, n); the loopback ADC sees a 100 Hz square of amplitude
   ∝ (n − k), AC coupling does not matter; synchronous summation over ~0.5 s gives sign and size; bisect n
   (fractional by dithering the low byte) to ~0.1 %. Repeat at two or three values of h (linearity check),
   store k in the V006's flash. About 2 s, at power-up or on a console command.
3. **Alternative:** the filter output to a spare ADC pin, measured at DC with averaging.

## 4. Backplane

Four-layer PCB (planned as two layers; backplane.md 7.1: In1 GND, In2 +3V3 under the controller strip and GND
under the slots). The slot connectors sit in a row
with the voice bus (RX, TX, SYNC) as a straight bus along it and each slot's NRST and SWIO line fanned out
towards the controller. The sensitive parts stay small and local: the cards bring their own references and
regulators, so the backplane carries only 5 V, ground and line-level audio. The mixer and line out sit at one end,
away from the controller and USB; each card's AUDIO_L, AUDIO_R and AUDIO_GND run as a group to the mixer, which takes
AUDIO_GND as its local reference (pseudo-differential input) so ground currents along the backplane do not add
to the audio. USB full-speed (12 Mbit/s) runs as a short pair from the connector to the V203; a controlled
impedance is not critical at that rate and length.

- **Size:** 100 × 100 mm (backplane.md): the slot row is 8 × 10 mm long, with the cards (at most 50 mm deep)
  standing over it; controller, USB connectors and power take a strip of about 40 mm along one side.
  Low parts (the mixer's per-slot resistors, decoupling) fit between the sockets under the cards.
- **Controller:** CH32V203 (LQFP-48: enough pins for 8 slots), 8 MHz crystal, PLL 144 MHz. The crystal also sets
  the pitch of the whole synth (the voices synchronise to it, section 6).
- **USB device:** USB-C, full-speed, on USBD (PA11/PA12, LQFP-48 pins 32/33): composite of
  - **USB-MIDI** (class compliant, no driver): notes, controllers, program changes; voice allocation on the
    controller (poly, unison, split / layer);
  - **CDC serial:** configuration, presets, firmware update of the controller and, through SWIO, of the voice
    cards; a bridge to each card's console;
  - **USB audio in** (option, UAC1, 48 kHz / 16 bit stereo): the mix, digitised by the V203's two ADCs in
    dual mode, oversampled and decimated in firmware. A recording path without the oscilloscope; the internal
    ADC limits it to roughly 60–70 dB, about the synth's own noise floor.
- **Voice bus:** USART TX (broadcast), USART RX (open-drain return, pull-up), SYNC (timer output, 1 kHz), one NRST
  line per slot from a 74HC595 on SPI1 and one SWIO line per slot (8 direct GPIOs), a 24 MHz clock to CLK_IN (option:
  TIM3 CH4,
  144 MHz / 6, locked to the crystal; MCO cannot give 24 MHz, and the V006's PLL is a fixed ×2).
- **In-system programming:** the controller drives each slot's SWIO line (the 1-wire debug protocol, as the
  WCH-LinkE does); the host sends the voice firmware over CDC. Until that exists each card's own programming
  header serves (reachable with the cards plugged in); no extra SWIO header on the backplane.
  Each slot's SWIO line needs a 1 kΩ pull-up to 3.3 V on the backplane: the card has none (on the bench the
  WCH-LinkE provides it), and the protocol samples about 0.6 µs after each edge (bench: without it every read is 0).
  The controller itself: SWD header for the WCH-LinkE, and a BOOT0 jumper for the V203's factory bootloader (flash
  over USB or USART1, no programmer needed).
- **Power:** USB-C 5 V (sink, 5.1 kΩ on CC), or an external 5 V on a 2-pin header (for when the computer's USB
  supply is noisy); a 3-pin jumper selects the source (no diode drop); polyfuse, TVS; VBUS sensed on a GPIO.
  8 cards × ~10 mA + controller ~30 mA ≈ 110 mA, well inside 500 mA. 3.3 V LDO for the controller; the cards have
  their own.
- **Mixer** (S12, two buses, docs/results/s12_mixer_2bus.csv; the earlier one-output version with fixed pan
  positions in s12_mixer.csv): stereo, two MCP6002 inverting summing amplifiers (one package) on VREF 2.41 V (10 kΩ / 27
  kΩ
  from the controller's +3V3 with 10 µF and a second 10 kΩ / 10 µF stage, unbuffered; 0.2 had a CJ431 and a
  follower), op-amp rail through 47 Ω /
  22 µF. The pan is
  on the cards (S13), so the mixer has no fixed pan.
  - Each slot: AUDIO_L → 10 µF → 56k into L, AUDIO_R → 10 µF → 56k into R (the input capacitors keep the cards'
    100 kΩ bleeders off the 2.5 V summing nodes); Rf = 20 kΩ ∥ 47 pF C0G: 0.357 per card, the same for every slot.
  - Pseudo-differential input: AUDIO_GND → one 10 µF per slot, shared by L and R (each channel sees 5 µF, as the
    card's 10 µF in series with the input 10 µF) → 56k to each + input; 20 kΩ ∥ 47 pF from each + input to VREF.
    So out = VREF − 0.357 Σ (AUDIO_x_k − AUDIO_GND_k) for any set of populated slots.
  - Line out: 220 Ω + 10 µF to the 3.5 mm jack, 100 kΩ bleeder. ADC tap: 15k / 27k with 330 pF C0G into ADC1 /
    ADC2, dual mode at 384 kHz (the 187.5 kHz carrier does not fold into the band), decimated by 8.
  - Simulated: 8 cards hard left in phase at the capped level (1.38 Vpp each) give 3.95 Vpp, 2.0 dB below
    clipping; 8 centred cards 2.79 Vpp per channel (5.0 dB). Without the firmware cap on CV_VCA (1.95 Vpp per card)
    8 hard-panned cards clip. A centred voice is about 4 dB quieter than with the one-output mixer (the gain is
    sized for 8 hard-panned cards); the cards' own signal-to-noise is unchanged. Flat 20 Hz – 20 kHz (−0.1 dB);
    mixer noise 8–17 µV (+0.6 dB on one centred card with 8 slots fitted); ground rejection 45 dB typical, 29 dB
    worst case with 1 % resistors (26 dB at 20 Hz with capacitors ±20 %); L/R crosstalk below −105 dB with or
    without empty slots; supply rejection −71 dB; 0.34 mA. USB audio: one centred card at −23 dBFS, 8 hard-panned
    cards at −2.3 dBFS.
  - 7 parts per slot (56) plus 30 (VREF from +3V3 through two RC stages, no CJ431; backplane.md 5), about 45 mm² per
    slot (one row of 0603 parts between two sockets); the 3.5 mm
    jack is hand-soldered. Route each channel's − and + feed side by side (pickup common to both).
- **USB host for MIDI keyboards:** USB-A, full-speed host on USBFS (PB6/PB7, LQFP-48 pins 42/43; the V203
  datasheet's LQFP-48 pin table: USBD on PA11/PA12, USBFS on PB6/PB7, so both run at the same time). Class-
  compliant USB-MIDI keyboards and controllers play the synth without a computer; through the computer any
  keyboard works anyway (the DAW or the OS routes it to the synth's USB-MIDI device). The backplane powers the
  keyboard through a current-limited 5 V switch (typically 50–200 mA; from a 5 V adapter, or within a computer
  port's 500 mA with the synth's ~110 mA).
- **Optional (not fitted at first):** MIDI DIN in (3.5 mm TRS or DIN footprint, optocoupler, to a USART RX), for
  hardware without USB; the computer needs no separate connection, it plays the synth over USB-MIDI. Status LEDs.
  No touch keyboard: the synth is played from the computer. Controller plan: [controller.md](controller.md).

### Controller choice

| | CH32V203 (C8T6) | CH32X035 / X033 |
|---|---|---|
| Core | QingKe V4B, 144 MHz | QingKe V4C, 48 MHz |
| USB | USBD (device, PA11/PA12) and USBFS (host/device, PB6/PB7) on separate pins: device to the computer and host for a keyboard at once; isochronous endpoints (USB audio) | full-speed host/device + USB PD / Type-C PHY (X035) |
| Clock for USB | crystal + PLL | internal 48 MHz: whether USB works crystal-less needs checking |
| ADC | 2 × 12 bit, dual mode (stereo capture) | 12 bit, OPA/PGA |
| I2S | none (so no external audio codec) | none |
| Firmware | ch32fun USBFS examples, TinyUSB port | ch32fun (USB PD sink example) |

The V203 fits better: a crystal for USB and for the synth's master clock, two ADCs for stereo capture, and CPU for
USB audio decimation. The X035's USB PD is not needed at 5 V and ~110 mA. To check: the X033's USB (the X035
datasheet covers both), and isochronous transfers with the chosen USB stack.

## 5. Communication

- **Broadcast:** controller USART TX to the RX of all cards, 8N1, 1 Mbaud or more. Messages carry a voice address
  (or "all"); every card receives every byte by DMA (USART1_RX on channel 5, tested on board 1 together with the
  DAC and the CV burst) and filters by address.
- **Return:** one shared line, open drain with a pull-up on the backplane. A card drives its TX only while the
  controller has addressed it with a request (calibration results, status).
- **SYNC:** a 1 kHz pulse from a controller timer. It is the timing reference for the clock synchronisation and
  marks frames.
- **Enumeration:** at power-up the controller holds all NRST lines low and releases one slot at a time. Each
  released card synchronises (section 6) and is then told its address. About 1 s for 8 cards plus 0.3 s per empty
  slot (bus.md 6).

The protocol (frames, timed events, presentation delay, packets, enumeration) is in [bus.md](bus.md).

SPI was considered and dropped. Pins alone would allow it: remap 4 (SCK PD4, MISO PD5, MOSI PD6) takes the
UART and SYNC pins, with software NSS (its hardware NSS pin, PD3, is CV_VCA) and SYNC moved to PC5. The obstacle is
DMA: SPI1_RX shares channel 2 with TIM2_UP, which feeds the DAC (reference manual table 8-2), so SPI would only
work with per-byte receive interrupts during the DSP loop, or with the DAC moved to the TIM2_CH2/CH4 request on
channel 7. UART needs the HSI trimmed first (section 6), which the voices need for their pitch anyway.

## 6. Clock synchronisation

The HSI is specified at ±2 % (−10 to 70 °C). Untrimmed, voices would be up to ~±25 cent apart, and UART at
8N1 would not work reliably between two chips at the limits.

1. **Coarse, at start-up:** the card timestamps SYNC edges with SysTick over ~100 periods and sets HSITRIM so its
   clock is within one trim step of the controller's. Board 1: 0.21 % per step (reference manual: ~0.25 %),
   monotonic, range −4.2 % to +2.3 % around the default 16, so the residual is at most ±0.1 % (1.8 cent)
   (docs/results/hw_board1_hsitrim.csv). Only then does it start listening on RX: at 1 Mbaud the USART divider is fixed
   (3.0, resolution 1/16), so the
   baud accuracy comes from this trim (bus.md 2).
2. **Fine, continuous:** the card keeps measuring the SYNC period and scales its oscillators' phase steps by the
   ratio (the oscillator tables are in 1/16 semitone; the scaling is exact arithmetic). This tracks temperature
   drift. The HSI also wanders by itself (board 1: flicker frequency noise, Allan deviation about 2e-4 from 1 ms
   to 0.5 s, i.e. 0.35 cent rms; no LDO setting changes it; docs/results/hw_board1_hsi_jitter.csv). A 100 ms
   measurement scatters by 0.02–0.03 %; wander faster than the measurement window stays, as a slight independent
   pitch wander of each voice (analog-VCO-like). The shared clock (fallback) would remove it. The core regulator
   setting shifts the HSI (LDO_MODE 1 or 3: −0.7 %), so it must not change after trimming.

The controller's crystal sets the pitch of the whole synth.

After the coarse trim, the voices' carriers (46.9 kHz CV PWM, 187.5 kHz DAC) can still differ by up to one HSITRIM
step, a beat of up to ~100 / 400 Hz if carrier ripple from several voices meets a nonlinearity. The CV filters
and the DAC's reconstruction filter hold the carriers far below the signal, so this is not expected to matter.
**Fallback:** the controller outputs a 24 MHz clock (TIM3 CH4: 144 MHz / 6, from the crystal) to every slot's
CLK_IN; fitting the 0 Ω link on a card switches it to that external clock (PA1, XI). 24 MHz because the V006's PLL
multiplies by exactly 2 (48 MHz); the V203's MCO can only give 8 or 72 MHz.

## 7. Verification status

| Item | Status |
|---|---|
| Digital oscillators, 187.5 kHz DAC, CPU load | board 1: 3 oscillators at 184 cycles per sample; fills 4.3 ms of each 5.5 ms buffer half with the CV interrupt still running |
| DCO against DAC | board 1: same inharmonic content (C2–C7), same closed-VCA floor (S9d, docs/results/hw_board1_dco_vs_dac.csv) |
| 5 V analog core | simulated (S10, docs/results/s10_5v.csv); Microchip's model has no input crossover or distortion detail |
| HSITRIM, HSI jitter | measured on board 1 |
| Kettle on the 187.5 kHz carrier | board 1 |
| Voice card PCB (hw/gen_pcb.py: 50 × 50 mm, 4 layers, routed) | DRC 0 errors, 0 unconnected, schematic parity OK |
| Voice card schematic (hw/voice.py, hand-laid out in hw/layouts_voice.py) | ERC clean; KiCad netlist = design (114 nets); all 158 simulated elements match S13 variant A on S10 v5c |
| DAC loading formats (single and dual PWM, once or twice per period), half rate | board 1: all formats exact in read-back and on the pins; half rate: polyBLEP aliasing at C5 (−51 against −56 dB re the fundamental); the takes above C5 came from a faulty experiment build (docs/results/hw_board1_half_rate.csv) |
| Voice firmware phase 1: format 4, 256-period halves rendered in the DMA interrupt, touch UI removed | board 1: 0 overruns over tunes 33–40, worst render 87 % of a half, control tick enters within 28 cycles during a render, 6.9 KB static RAM, same level and inharmonic content as the committed firmware (docs/results/hw_board1_fw_phase1.csv) |
| CV dither by TIM1 DMA burst; DMA request table | board 1: burst works (all request variants), CV pattern exact (register read-back), DAC + CV burst + USART1 RX ring together without errors or overruns |

## 8. Open points

- MCP6002 input stage transition (typically near VDD − 1.1 V; datasheet: CMRR ≥ 60 dB, typ. 76 dB, over
  −0.3 … 5.3 V, so the offset step is at most a few mV, typically < 1 mV). INA inputs: 4.04–4.24 V over the whole
  cutoff range (VB4 − Vbe), always above the transition: keep the bias (lowering it would move them into it).
  Resonance difference amp: 3.2–3.75 V, below. VCA difference amp: its inputs move from 4.22 V (VCA closed) to
  ~3.2 V (open) and cross the transition during attacks (an offset step of ~1.6 mV at the VCA output, ≈ −56 dB);
  fixed in the card: 33k from both inputs to GND (matched, so the gain stays), inputs now 2.44–3.13 V (S10 v5c).
  Bench check on the first card.
- DAC formats 4 and 3 (once per period, ch1): a start sequence that cannot pick up a stale request; the ADC
  without DMA.
- Dual PWM's audio benefit is still unmeasured (board 1 has no low-byte resistor): first card.
- Spare pins: none left on the TSSOP-20 since PC5 drives the pan (PA1 only without the clock option).
- RAM: 8 KB is tight (a test build on board 1 kept only ~430 B of stack); the voice firmware without the touch UI
  and the tunes must free room.
- USB stack on the V203: MIDI + CDC first; isochronous audio second.
- SWIO programming from the controller (protocol timing on the V203).
- Bulk capacitor type for the 6 mm height limit (section 3.3); card guides or an enclosure to hold the cards.
- USB host stack for class-compliant MIDI devices on USBFS (ch32fun has USBFS host support in its headers; a MIDI
  host driver is to be written or taken from TinyUSB).
- First build: one voice card at 5 V on the bench (programmer-powered), before the backplane.
