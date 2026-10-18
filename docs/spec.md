# TouchSynth Poly: specification

Status: draft 0.3 (2026-10-18), branch `polyphonic_hw`. Simulated (S9, S10) and partly tested on board 1;
nothing of the new hardware is built yet.

## 1. Goal

A polyphonic analog synthesizer with 4 to 8 voices, played and edited from a computer over USB. Each voice is an
identical plug-in card: a CH32V006 generating the oscillators digitally (PWM DAC) and the analog filter and VCA
of TouchSynth rev 0.1. A backplane holds the USB controller, the voice bus, power and the stereo mixer.
Single 5 V supply (USB-C). Voice cards can be programmed, run and debugged on their own.

Constraints as before: JLCPCB Basic and Promotional Extended parts only; MCUs (own stock), headers and
connectors hand-soldered.

### Decisions so far

| Topic | Decision | Basis |
|---|---|---|
| Oscillators | digital, on the V006's PWM DAC; no analog DCO | DCO and DAC saw measure the same on board 1 (S9d); 3 oscillators, any waveform, the kettle in firmware |
| DAC | 187.5 kHz carrier (TIM2 centre-aligned, 2 × 128), 7 bit, second-order error feedback, one sample per carrier period (oscillators) or 15.625 kHz interpolated (modal drums) | S9: images, not bits, limit the quality; implemented and recorded on board 1 |
| Supply | single 5 V; MCU on a 3.3 V LDO; CJ431 2.5 V reference | S10 (v5m: Microchip MCP6002 model) |
| Voice bus | UART broadcast + SYNC line + per-slot reset | pin and DMA constraints of the V006 |
| Controller | CH32V203C8T6, LQFP-48 (USB-MIDI, CDC; USB audio of the mix via its ADCs as an option); all slot lines (NRST, SWIO) direct, no port expanders | section 4 |
| Slots | 8 on the backplane, populated as cards are built | |
| Backplane PCB | 2 layers (voice cards: 4 layers) | section 4 |
| Card format | small cards; backplane connector on one edge, LEDs and debug connectors (SWIO, line out) on the opposite edge | section 3.3 |
| Voice MCU | CH32V006K8U7 (QFN-32, own stock); the board 1 pin map carries over, reset on PA7 | section 3.2 |
| DAC variants | standard: one PWM, 187.5 kHz, 7 bit, second-order error feedback (−67 to −87 dB in the three-oscillator model); assembly option: dual PWM (high + low byte, 7 + 7 bit, 128:1) at 187.5 kHz: −82 to −92 dB, near an ideal DAC, at about the same CPU; a firmware mode with 93.75 kHz samples interpolated on the 187.5 kHz carrier halves the oscillator CPU (model: −57 to −67 dB; not quantisation, not the in-band droop; most likely an artefact of the model's 192 kHz ladder with images near its Nyquist rate; below the analog noise floor either way; to be settled by recording both modes on the first card). The carrier stays at 187.5 kHz: a 93.75 kHz carrier reaches the line out at −39 dB through the 30 kHz filter (S11) | S9b |
| Slot addresses | by enumeration over the per-slot NRST lines; no ID pins on the card | section 5 |
| Not used | the V006's internal op-amp, a temperature sensor for the expo pair, a separate UART console | |

## 2. Overview

```
 backplane                                                  voice card (x4..8, identical)
 ───────────────────────────────────────────────            ───────────────────────────────────────────────────
 USB-C 5 V ─► fuse/TVS ─► 5V ──────────────────────────────► 5V ─► 10 R / 220 u ─► analog rail (ladder, op-amps)
                          └► 3.3 V LDO (controller)                 ├► XC6206 3.3 V ─► MCU (PWM reference)
                                                                     └► CJ431 2.5 V ─► VREF, V25, VBIAS
 CH32V203 (crystal, 144 MHz)                                voice CH32V006 (3.3 V, synchronised HSI)
   USB FS device: MIDI + CDC (+ audio in, option)             TIM2 CH2 ─► PWM DAC ─► 2-pole filter ─► mixer
   voice allocation, parameters, presets                      TIM1 CH1..4 ─► VCA trim, CV_CUT, CV_RES, CV_VCA
   USART TX ──── broadcast ──────────────────────────────►    USART RX (DMA ring)
   USART RX ◄─── shared open-drain return ◄───────────────    USART TX (enabled only when addressed)
   timer ─────── SYNC 1 kHz ─────────────────────────────►    EXTI + SysTick: clock ratio
   GPIO x8 ───── NRST per slot ──────────────────────────►    NRST (enumeration, single-voice reset)
   GPIO x8 ───── SWIO per slot (in-system programming) ──►    SWIO
 stereo mixer (MCP6002, 5 V, VREF 2.5 V) ◄── AUDIO_OUT ◄──    VCA out (AC-coupled line level)
   ├► line out L/R                                            └► loopback divider ─► ADC (calibration)
   └► ADC1/ADC2 of the CH32V203 (USB audio, option)
```

## 3. Voice card

### 3.1 Signal path and parts

| Block | Design | Against rev 0.1 |
|---|---|---|
| Oscillators | firmware: up to 3 saw / pulse oscillators (polyBLEP), modal drums, noise; 184 cycles per sample for 3 oscillators (board 1) | replaces DCO, sub, pulse, noise GPIOs |
| PWM DAC | TIM2 CH2, 187.5 kHz, 7 bit, error feedback (dsp.c); option: dual PWM with TIM2 CH4 as low byte (two resistors into the filter input, 10k and ~1.2M, calibrated in firmware, section 3.5) on the same carrier | was the pulse output |
| Reconstruction filter | unity-gain 2-pole Sallen-Key (Butterworth), MCP6002 half: 10k / 10k, C1 750 pF (feedback), C2 390 pF, fc 30 kHz. S11: the 187.5 kHz carrier at −74 dB re full scale at the line out (without: −42 dB), droop 0.04 dB at 10 kHz, 0.8 dB at 20 kHz. The dual-PWM option runs on the same 187.5 kHz carrier and uses the same filter. Fixed cutoff, not voltage-controlled: the firmware shapes everything below Nyquist, the filter only removes carrier and images | new (rev 0.1 earmark: carrier crosstalk) |
| Mixer into the ladder | the filtered DAC (0–3.3 V full scale) through 240 kΩ: the drive of rev 0.1's saw (2 Vpp through 150 kΩ), S11 (on board 1 the DAC came through 470 kΩ, 3–10 dB less signal-to-noise) | |
| Expo converter | as rev 0.1, VBIAS 1.0 V (buffered), V25 1.25 V, RREF 470 kΩ from VREF, divider 18k / 1k5 | S10 v5r |
| Ladder | 4 poles, 10 nF, bias chain 620 Ω / 4 × 1.5 kΩ / 3.3 kΩ from the analog rail (VB0 1.66 V, spacing 0.76 V) | 33 nF; 2k2 / 4 × 1k / 2k4 |
| INA, difference amps, references | MCP6002 (rail-to-rail) in all TL072 positions: VREF and VBIAS buffers, INA (2), resonance and VCA difference amps, reconstruction filter = 7 units, 4 × MCP6002 | 3 × TL072 |
| V→I converters | LM324 (expo, resonance, VCA; 1 unit spare); resonance R4 12k / R_E 3k6, VCA R4 7k5 / R_E 2k2; VCA anti-offset 240k from VREF | 4 units used |
| VCA trim | TIM1 CH1 (the former CV_AMP channel) + 2-pole RC into the 1 MΩ injection | R-2R DAC + 74HC595 |
| CV PWM | TIM1, 46.9 kHz, 10 bit + 2-bit dither, 0–3.3 V; dither by DMA burst (16-halfword circular table, 4 phases × 4 channels, into TIM1->DMAADR) instead of the 46.9 kHz interrupt: board 1 frees ~9 % of the CPU (the interrupt cost ~90 cycles per call), DAC refill −8 %, and 164 B of RAM | interrupt, 0–5 V |
| Audio loopback | divider to the 3.3 V ADC (PC4) | 5 V ADC, PD5 |
| Self-test (option) | dividers from the analog rail and the ladder bias VB0 to free ADC pins: assembly faults show at power-up | |
| Supply | 5 V in; analog rail through 10 Ω + 220 µF; XC6206 3.3 V for the MCU (the PWM outputs are duty × VDD); CJ431 2.5 V VREF | 9–12 V, SS14, 78L05 |
| LEDs | power (from 3.3 V), "playing", status (bus, errors), on the debug edge | 16 + UI |

Simulated performance of the analog core at 5 V (S10, variant v5m with Microchip's MCP6002 model, against rev 0.1
at 8.6 V): cutoff 19 Hz – 31 kHz (rev 0.1: 20 Hz – 20 kHz; trim with the expo divider), self-oscillation from the
same resonance CV, THD 0.44 % at full drive (0.58 %), signal-to-noise 68–69 dB (70 dB), supply rejection
−61 / −65 / −78 dB at 100 Hz / 1 kHz / 10 kHz (−80 / −84 / −71 dB), smallest V_CE 0.51 V, 3.6 mA analog current
(9.1 mA). Supply per card about 10 mA at 5 V (analog 3.6 mA, MCU ~5 mA, LEDs).

### 3.2 MCU pin map (CH32V006K8U7, QFN-32, 3.3 V)

The board 1 (TSSOP-20) pin functions carry over unchanged: TIM1 and TIM2 keep remap 2 (TIM1_RM = 0010,
TIM2_RM = 010), USART1 its default pins. Differences of the QFN-32: reset is PA7 (pin 4; PD7 is a plain GPIO
here), PA4 and PD7 are separate pins (shorted inside the TSSOP-20), and 14 GPIO stay free (plus PA1 without the clock option).

| Pin | Port | Function | Pin | Port | Function |
|---|---|---|---|---|---|
| 0 | VSS | GND (exposed pad) | 17 | VDD | +3.3 V |
| 1 | PB3 | spare (SWCK: 2-wire debug, if the programmer supports it) | 18 | PC4 | ADC A2 ← audio loopback |
| 2 | PA5 | spare | 19 | PC5 | spare |
| 3 | PA6 | spare | 20 | PC6 | TIM1 CH1 → VCA trim |
| 4 | PA7 | NRST ← backplane | 21 | PC7 | TIM1 CH2 → CV_CUT |
| 5 | PA0 | LED "playing" | 22 | PB4 | LED status |
| 6 | PA1 | external clock in (XI; DNP 0 Ω link), else spare | 23 | PD1 | SWIO |
| 7 | PA2 | ADC A0 ← self-test: ladder bias VB0 (option) | 24 | PD2 | ADC A3 ← self-test: analog rail / 2 (option) |
| 8 | PD0 | spare | 25 | PD3 | TIM1 CH4 → CV_VCA |
| 9 | PA3 | spare | 26 | PD4 | SYNC in (EXTI) |
| 10 | PB0 | spare | 27 | PD5 | USART1 TX → return line |
| 11 | PB1 | spare | 28 | PD6 | USART1 RX ← broadcast |
| 12 | PB2 | spare | 29 | PB5 | spare |
| 13 | PC0 | TIM1 CH3 → CV_RES | 30 | PB6 | spare |
| 14 | PC1 | TIM2 CH4 → DAC low byte (dual-PWM option) | 31 | PD7 | spare (plain GPIO on the QFN-32) |
| 15 | PC2 | TIM2 CH2 → PWM DAC | 32 | PA4 | spare |
| 16 | PC3 | spare | | | |

Pin numbers from the datasheet's pin table (CH32V006 DS V2.0, table 2-1-1, column V006K8U7). KiCad 10 has no
CH32V006 symbol: the voice card needs its own (pins as above), footprint QFN-32 4 × 4 mm, 0.4 mm pitch
(Package_DFN_QFN: QFN-32-1EP_4x4mm_P0.4mm_EP2.65x2.65mm or EP2.9x2.9mm, to match the datasheet's pad).

**DMA allocation** (CH32V00X reference manual V1.4, table 8-2; measured on board 1):

| Channel | Requests (V006) | Use |
|---|---|---|
| ch2 | SPI1_RX, TIM1_CH1, TIM2_UP | PWM DAC (TIM2_UP), the only option |
| ch4 | USART1_TX, TIM1_CH4/TRIG/COM | USART1 TX (return line), if by DMA |
| ch5 | **USART1_RX, TIM1_UP**, TIM2_CH1 | USART1 RX ring (voice bus) |
| ch6 | USART2_TX, I2C1_TX, TIM1_CH3 | CV dither burst: TIM1 with CCDS = 1 and CC3DE (request on the update event) |
| ch3, ch7, ch1 | SPI1_TX / TIM1_CH2; USART2_RX / TIM2_CH2/CH4; ADC1 / TIM3_CH3 | free (ch7: dual-PWM option, ch1: ADC) |

TIM1_UP and USART1_RX share ch5, so the burst runs on the CC3 request (ch6; ch3 via CC2DE works too). With CCDS = 1
the CCx request comes on the update event; preload (OCxPE) must stay on; enable the DMA channel before the request.
All three (DAC, CV burst, USART1 RX ring) ran together on board 1 during a tune: 1353 of 1353 bytes received, no
UART errors, no DAC overruns, CV pattern intact. The noise LFSR that lived in the TIM1 interrupt moves into the DSP.

### 3.3 Connectors

**Backplane connector**, 2×8 pin header 2.54 mm (card underside):

| Pin | Signal | Pin | Signal |
|---|---|---|---|
| 1 | +5 V | 2 | +5 V |
| 3 | GND | 4 | GND |
| 5 | AUDIO_OUT | 6 | AUDIO_GND |
| 7 | GND | 8 | GND |
| 9 | SYNC | 10 | RX (broadcast in) |
| 11 | TX (return, open drain) | 12 | NRST |
| 13 | GND | 14 | SWIO |
| 15 | CLK_IN (option) | 16 | spare |

All logic at 3.3 V (both MCUs).

**Programming header**, 1×3 (card top): +5 V, SWIO, GND, the rev 0.1 order. The WCH-LinkE's 5 V powers the whole
card (about 10 mA), analog part included, so a card runs on the bench with only the programmer attached. The
console works over SWIO as on rev 0.1.

**Line out**, 1×2 (card top): AUDIO_OUT, GND, for the scope or an amplifier in standalone operation.

**Card format:** small (target about 60 × 45 mm, 4 layers), plugged into the backplane edge-on. The backplane
connector sits on one edge; the opposite edge carries the two LEDs, the programming header and the line-out
header, so they stay reachable with all 8 cards plugged in. The analog part sits next to the backplane
connector (short audio path, away from the debug edge); the MCU and the PWM outputs sit between them, with the
reconstruction filter right at the DAC pin.

### 3.4 Standalone mode

Without SYNC pulses after reset, the voice firmware runs as a mono synth on its own HSI, controlled from the SWIO
console like board 1 (notes, tunes, patches, calibration via the loopback). The bench tools (`tools/synthtest.py`,
`hwtest.py`, `scope.py`) then work on a single card.

### 3.5 Dual-PWM option: weighting and calibration

The high byte (TIM2 CH2) enters the reconstruction filter's input through 10 kΩ, the low byte (TIM2 CH4) through
~1.2 MΩ: 7 + 7 bit on the 187.5 kHz carrier. Error sources of the weight ratio: resistor tolerance (1 %) and the
pins' output resistance (tens of Ω, 0.25–0.5 % of 10 kΩ); both pins share VDD and the timer, so the supply and the
pulse timing cancel. A ratio error ε gives a step error of ε × one high-byte step at every high-byte transition:
1 % = 1/12 800 of full scale, about −82 dB, at the option's noise floor (S9b already ran with a 1 % error). So
calibration only matters beyond ~2 %, but it is cheap:

1. **Overlap, not precision:** 1.2 MΩ instead of 128 × 10 kΩ = 1.28 MΩ makes the low byte's span ~5 % larger
   than one high-byte step, so no tolerance leaves a gap. The firmware splits each value with the measured ratio
   k (low codes per high step, e.g. 122.3): high = floor(q / k), low = round(q − high × k); one multiply and
   shift per sample.
2. **Measuring k with the card's own loopback (null method):** filter and VCA open, alternate at ~100 Hz between
   two nominally equal codes (h, 0) and (h − 1, n); the loopback ADC sees a 100 Hz square of amplitude
   ∝ (n − k), AC coupling does not matter; synchronous summation over ~0.5 s gives sign and size; bisect n
   (fractional by dithering the low byte) to ~0.1 %. Repeat at two or three values of h (linearity check),
   store k in the V006's flash. About 2 s, at power-up or on a console command.
3. **Alternative:** the filter output to a spare ADC pin, measured at DC with averaging.

## 4. Backplane

Two-layer PCB. The bottom layer is a ground pour, broken only by short crossings; the slot connectors sit in a row
with the voice bus (RX, TX, SYNC) as a straight bus along it and each slot's NRST and SWIO line fanned out
towards the controller. The sensitive parts stay small and local: the cards bring their own references and
regulators, so the backplane carries only 5 V, ground and line-level audio. The mixer and line out sit at one end,
away from the controller and USB; each card's AUDIO_OUT and AUDIO_GND run as a pair to the mixer, which takes
AUDIO_GND as its local reference (pseudo-differential input) so ground currents along the backplane do not add
to the audio. USB full-speed (12 Mbit/s) runs as a short pair from the connector to the V203; a controlled
impedance is not critical at that rate and length.

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
  and one SWIO line per slot (direct GPIOs: 16 for 8 slots), MCO to CLK_IN (option).
- **In-system programming:** the controller drives each slot's SWIO line (the 1-wire debug protocol, as the
  WCH-LinkE does); the host sends the voice firmware over CDC. Until that exists: a header with all SWIO lines.
- **Power:** USB-C 5 V (sink, 5.1 kΩ on CC), polyfuse, TVS; 8 cards × ~10 mA + controller ~30 mA ≈ 110 mA,
  well inside 500 mA. 3.3 V LDO for the controller; the cards have their own.
- **Mixer:** stereo, MCP6002 inverting summing amplifiers on a CJ431 2.5 V reference, 5 V; each card to L and R
  through two resistors (fixed pan positions), gain about 0.35 per card (8 cards in phase stay inside the rail);
  AC-coupled line out (3.5 mm jack), and an anti-alias RC into the ADCs for USB audio.
- **USB host for MIDI keyboards:** USB-A, full-speed host on USBFS (PB6/PB7, LQFP-48 pins 42/43; the V203
  datasheet's LQFP-48 pin table: USBD on PA11/PA12, USBFS on PB6/PB7, so both run at the same time). Class-
  compliant USB-MIDI keyboards and controllers play the synth without a computer; through the computer any
  keyboard works anyway (the DAW or the OS routes it to the synth's USB-MIDI device). The backplane powers the
  keyboard through a current-limited 5 V switch (typically 50–200 mA; from a 5 V adapter, or within a computer
  port's 500 mA with the synth's ~110 mA).
- **Optional:** MIDI DIN in (opto, to a USART RX), a few status LEDs. No touch keyboard: the synth is played from
  the computer.

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
  (or "all"); every card receives every byte by DMA (USART1_RX has its own DMA channel; to be confirmed in the
  V006 reference manual) and filters by address.
- **Return:** one shared line, open drain with a pull-up on the backplane. A card drives its TX only while the
  controller has addressed it with a request (calibration results, status).
- **SYNC:** a 1 kHz pulse from a controller timer. It is the timing reference for the clock synchronisation and
  marks frames.
- **Enumeration:** at power-up the controller holds all NRST lines low and releases one slot at a time. Each
  released card synchronises (section 6) and is then told its address. About 2 s for 8 slots.

SPI was considered and dropped: on the TSSOP-20 only SPI remap 4 avoids the timer pins, and its NSS pin is
CV_VCA; SPI1_RX DMA would share a channel with TIM2_UP, which DAC mode uses (V003 request table; to be
confirmed for the V006).

## 6. Clock synchronisation

The HSI is specified at ±2 % (−10 to 70 °C). Untrimmed, voices would be up to ~±25 cent apart, and UART at
8N1 would not work reliably between two chips at the limits.

1. **Coarse, at start-up:** the card timestamps SYNC edges with SysTick over ~100 periods and sets HSITRIM so its
   clock is within one trim step of the controller's. Board 1: 0.21 % per step (reference manual: ~0.25 %),
   monotonic, range −4.2 % to +2.3 % around the default 16, so the residual is at most ±0.1 % (1.8 cent)
   (docs/results/hw_board1_hsitrim.csv). Only then does it compute its baud divider (from the measured ratio, so
   the baud rate matches exactly) and start listening on RX.
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
**Fallback:** the controller outputs its clock on MCO to every slot's CLK_IN; fitting the 0 Ω link on a card
switches it to that external clock (PA1, 3–32 MHz).

## 7. Verification status

| Item | Status |
|---|---|
| Digital oscillators, 187.5 kHz DAC, CPU load | board 1: 3 oscillators at 184 cycles per sample; fills 4.3 ms of each 5.5 ms buffer half with the CV interrupt still running |
| DCO against DAC | board 1: same inharmonic content (C2–C7), same closed-VCA floor (S9d, docs/results/hw_board1_dco_vs_dac.csv) |
| 5 V analog core | simulated (S10, docs/results/s10_5v.csv); Microchip's model has no input crossover or distortion detail |
| HSITRIM, HSI jitter | measured on board 1 |
| Kettle on the 187.5 kHz carrier | board 1 |
| CV dither by TIM1 DMA burst; DMA request table | board 1: burst works (all request variants), CV pattern exact (register read-back), DAC + CV burst + USART1 RX ring together without errors or overruns |

## 8. Open points

- MCP6002 input stage transition (typically near VDD − 1.1 V; datasheet: CMRR ≥ 60 dB, typ. 76 dB, over
  −0.3 … 5.3 V, so the offset step is at most a few mV, typically < 1 mV). INA inputs: 4.04–4.24 V over the whole
  cutoff range (VB4 − Vbe), always above the transition: keep the bias (lowering it would move them into it).
  Resonance difference amp: 3.2–3.75 V, below. VCA difference amp: its inputs move from 4.22 V (VCA closed) to
  ~3.2 V (open) and cross the transition during attacks (an offset step of ~1.6 mV at the VCA output, ≈ −56 dB);
  fix: matched resistors from both inputs to GND, so they stay below ~3.5 V. Bench check on the first card.
- Dual-PWM option: both TIM2 compare values per period, by a TIM2 DMA burst on TIM2_UP (ch2: CH2CVR..CH4CVR)
  or a second request on ch7 (TIM2_CH2/CH4); to be tested.
- RAM: 8 KB is tight (a test build on board 1 kept only ~430 B of stack); the voice firmware without the touch UI
  and the tunes must free room.
- USB stack on the V203: MIDI + CDC first; isochronous audio second.
- SWIO programming from the controller (protocol timing on the V203).
- Card dimensions, connector type and backplane mechanics (card guides, slot pitch).
- USB host stack for class-compliant MIDI devices on USBFS (ch32fun has USBFS host support in its headers; a MIDI
  host driver is to be written or taken from TinyUSB).
- First build: one voice card at 5 V on the bench (programmer-powered), before the backplane.
