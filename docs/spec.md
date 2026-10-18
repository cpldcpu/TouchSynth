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
| Controller | CH32V203 (USB-MIDI, CDC; USB audio of the mix via its ADCs as an option) | section 4 |
| Slots | 8 on the backplane, populated as cards are built | |
| Card format | small cards; backplane connector on one edge, LEDs and debug connectors (SWIO, line out) on the opposite edge | section 3.3 |
| Voice MCU | CH32V006K8U7 (QFN-32, own stock); the board 1 pin map carries over, reset on PA7 | section 3.2 |
| DAC variants | standard: one PWM, 187.5 kHz, second-order error feedback; assembly option: dual PWM (high + low byte, 256:1) at 93.75 kHz, same quality at half the oscillator CPU load | S9b |
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
| PWM DAC | TIM2 CH2, 187.5 kHz, 7 bit, error feedback (dsp.c); option: dual PWM with TIM2 CH4 as low byte (two resistors, 256:1) at 93.75 kHz | was the pulse output |
| Reconstruction filter | 2-pole Sallen-Key, MCP6002 half, fixed cutoff tied to the sample rate: ~15 kHz cuts the 187.5 kHz carrier ~44 dB; with the dual-PWM option (93.75 kHz carrier) ~12 kHz or a third pole. Not voltage-controlled: everything below Nyquist is shaped in firmware, the filter only removes carrier and images | new (rev 0.1 earmark: carrier crosstalk) |
| Mixer into the ladder | the filtered DAC through ~150 kΩ, the saw's former weight (470 kΩ cost 3–10 dB of signal-to-noise on board 1) | |
| Expo converter | as rev 0.1, VBIAS 1.0 V (buffered), V25 1.25 V, RREF 470 kΩ from VREF, divider 18k / 1k5 | S10 v5r |
| Ladder | 4 poles, 10 nF, bias chain 620 Ω / 4 × 1.5 kΩ / 3.3 kΩ from the analog rail (VB0 1.66 V, spacing 0.76 V) | 33 nF; 2k2 / 4 × 1k / 2k4 |
| INA, difference amps, references | MCP6002 (rail-to-rail) in all TL072 positions: VREF and VBIAS buffers, INA (2), resonance and VCA difference amps, reconstruction filter = 7 units, 4 × MCP6002 | 3 × TL072 |
| V→I converters | LM324 (expo, resonance, VCA; 1 unit spare); resonance R4 12k / R_E 3k6, VCA R4 7k5 / R_E 2k2; VCA anti-offset 240k from VREF | 4 units used |
| VCA trim | TIM1 CH1 (the former CV_AMP channel) + 2-pole RC into the 1 MΩ injection | R-2R DAC + 74HC595 |
| CV PWM | TIM1, 46.9 kHz, 10 bit + 2-bit dither, 0–3.3 V; dither by DMA burst instead of the 46.9 kHz interrupt (frees ~28 % CPU; to be confirmed on the V006) | interrupt, 0–5 V |
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
here), PA4 and PD7 are separate pins (shorted inside the TSSOP-20), and 13 GPIO stay free.

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
| 9 | PC0 | TIM1 CH3 → CV_RES | 26 | PD4 | SYNC in (EXTI) |
| 10 | PC1 | TIM2 CH4 → DAC low byte (dual-PWM option) | 27 | PD5 | USART1 TX → return line |
| 11 | PC2 | TIM2 CH2 → PWM DAC | 28 | PD6 | USART1 RX ← broadcast |
| 12–16 | PB2, PA3, PB1, PB0, PC3 | spare | 29–32 | PB5, PB6, PD7, PA4 | spare |

The order of pins 12–16 and 29–32 follows the datasheet drawing (CH32V006 DS V2.0, figure 2-1); check it against
the KiCad symbol before layout.

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

## 4. Backplane

- **Controller:** CH32V203 (LQFP-48: enough pins for 8 slots), 8 MHz crystal, PLL 144 MHz. The crystal also sets
  the pitch of the whole synth (the voices synchronise to it, section 6).
- **USB:** USB-C, full-speed device (USBFS): composite of
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
- **USB MIDI keyboards:** through the computer (the synth is a USB-MIDI device; the DAW or the OS routes any
  keyboard to it), or standalone through a second USB port as host for class-compliant MIDI devices, which the
  backplane then powers (typically 50–200 mA). The V203 has two USB controllers (USBD device only, USBFS
  host/device); whether the 48-pin C8T6 brings them out on separate pins needs the datasheet. Alternatives: a
  CH32V305/V307 (high-speed and full-speed USB, I2S) or a small second MCU as USB host.
- **Optional:** MIDI DIN in (opto, to a USART RX), a few status LEDs. No touch keyboard: the synth is played from
  the computer.

### Controller choice

| | CH32V203 (C8T6) | CH32X035 / X033 |
|---|---|---|
| Core | QingKe V4B, 144 MHz | QingKe V4C, 48 MHz |
| USB | full-speed device (USBFS and USBD), isochronous endpoints (USB audio) | full-speed host/device + USB PD / Type-C PHY (X035) |
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

## 8. Open points

- MCP6002 input behaviour near the top rail (INA inputs at ~4.1 V): datasheet curve or bench test; if needed,
  lower the ladder's top bias by ~0.3 V.
- CV dither by DMA burst on the V006 (TIM1 DMA burst support, DMA channel next to USART1_RX).
- V006 DMA request table: USART1_RX channel, conflicts with TIM2_UP (DAC).
- USB stack on the V203: MIDI + CDC first; isochronous audio second.
- SWIO programming from the controller (protocol timing on the V203).
- Card dimensions, connector type and backplane mechanics (card guides, slot pitch).
- USB host for MIDI keyboards: V203 pin-out (USBD and USBFS on separate pins?) or a CH32V305/V307.
- Reconstruction filter and DAC mixer resistor: simulate with the ladder input (S8/S10 style).
- First build: one voice card at 5 V on the bench (programmer-powered), before the backplane.
