# Devlog

The TouchSynth rev 0.1 log (concept to board 1 bring-up, demo pieces, PWM DAC and the kettle) is on `master`
(`docs/devlog.md`). This log starts where the polyphonic design split off.

## 1. From TouchSynth to a polyphonic synth (2026-10-18)

Starting point: TouchSynth rev 0.1, a monophonic synth with an analog DCO, a transistor ladder and a
differential-pair VCA, controlled by a CH32V006. The idea: use that voice as one card and put 4–8 of them, each
with its own MCU, on a backplane.

Steps on the way (all on branch `polyphonic_hw`, commit 17536f3 holds the state before this fork):

- **Voice bus:** UART broadcast plus a SYNC line, not SPI (pin and DMA constraints of the V006's TSSOP-20);
  per-slot resets for enumeration. The voices synchronise their HSI to the controller: board 1 measured
  0.21 % per HSITRIM step and an HSI flicker of about 2e-4 (0.35 cent rms), unaffected by the LDO settings.
- **DCO or DAC:** in the model, the existing DAC (15.6 kHz, 8 bit) aliased badly with an open filter. One sample
  per carrier period removes the interpolation images; at 187.5 kHz with second-order sigma-delta, 7 bit reach
  the quality of an ideal DAC. Implemented on board 1: three oscillators (saw / pulse, polyBLEP) at 184 cycles
  per sample, after moving the pitch conversion from soft-float to tables and running the loop in blocks from
  SRAM. The kettle moved to the same carrier. On board 1 the DAC saw and the DCO saw measure the same (C2–C7,
  inharmonic content within ±2 dB, same closed-VCA floor). Decision: DAC only.
- **5 V:** S10 redesigned the analog core for a single 5 V supply: MCP6002 for the TL072s, a CJ431 reference
  (VREF, buffered VBIAS), the MCU on a 3.3 V LDO (the PWM outputs are duty × VDD), a new ladder bias chain and
  10 nF ladder capacitors. With Microchip's MCP6002 model it matches rev 0.1 within about 1–2 dB, at 3.6 mA
  instead of 9.1 mA.
- **Controller:** played from a computer over USB (USB-MIDI, CDC); CH32V203 for its crystal (USB and master
  clock) and two ADCs (USB audio of the mix as an option).
- **Model fix:** the behavioural model's saw had its polyBLEP at the start of the reset pulse instead of its end
  (high notes aliased at about −21 dB in every rev 0.1 render).

Decisions after the fork: 8 slots on the backplane, populated as cards are built; small voice cards with the
backplane connector on one edge and LEDs plus debug connectors on the opposite edge; the voice MCU is the
CH32V006 in QFN-32 (own stock; the board 1 pin map carries over, 13 GPIO spare). The dual-PWM DAC becomes an
assembly option (first planned at 93.75 kHz for half the CPU load; corrected in section 2: on the 187.5 kHz
carrier). Slot addresses come
from the enumeration over the per-slot resets. Not used: the V006's internal op-amp, an expo temperature sensor,
a separate UART console, a voltage-controlled reconstruction filter (the firmware shapes everything below
Nyquist; the filter only removes carrier and images, so its cutoff is fixed to the sample rate).

The rev 0.1 tree (report, S1–S7, KiCad project, tools for the report) is kept locally in `archive/`
(gitignored) and on `master`.

## 2. Reconstruction filter, dual PWM, USB pins (2026-10-18)

- **S11:** the DAC's reconstruction filter on the 5 V core. A unity-gain 2-pole Sallen-Key at 30 kHz takes the
  187.5 kHz carrier to −74 dB at the line out (−42 dB without), droop 0.8 dB at 20 kHz; 240 kΩ into the mixer gives
  the DAC the drive of rev 0.1's saw.
- **Model change and an open question:** the behavioural model band-limited the PWM's per-period values to half
  the carrier rate, which hid the sample-and-hold images of a 93.75 kHz carrier; it now holds each period's value
  (as on the pin). With that, the 93.75 kHz variants drop to −22 to −38 dB in the three-oscillator voice and
  93.75 kHz samples on the 187.5 kHz carrier reach −57 to −67 dB, against −82 to −92 dB for dual PWM at full rate.
  Checks: not quantisation (−99 dB), not the in-band droop (pre-emphasis changes nothing); the images reach the
  ladder at about −68 dB, which in a real differential pair cannot produce in-band products anywhere near that
  level. Most likely the simulated ladder (192 kHz, images near its Nyquist rate) creates them; a run at a higher
  model rate was not possible (the model's calibration is tied to 192 kHz). Not decisive in practice: all values
  are near or below the analog noise floor. Decisions: dual PWM at the 187.5 kHz carrier (the carrier filtering
  alone favours it; S11: a 93.75 kHz carrier leaves −39 dB at the line out), half rate as a firmware mode; record
  both modes on the first card.
- **Dual-PWM calibration:** with 7 + 7 bit a 1 % ratio error costs about −82 dB; overlapping low-byte span
  (1.2 MΩ) plus a measured ratio from a null test over the card's own loopback (spec 3.5).
- **MCP6002 input transition:** the INA inputs (4.04–4.24 V) stay above it; the VCA difference amp crosses it
  during attacks and gets matched resistors to ground.
- **CH32V203 C8T6:** USBD on PA11/PA12 and USBFS (host) on PB6/PB7: device to the computer and host for a MIDI
  keyboard at once.
- **Board 1, V006 DMA:** CV dither by TIM1 DMA burst works; the interrupt it replaces cost ~9 % of the CPU (an
  earlier estimate of 28 % came from a busy-loop measurement that depends on code alignment in flash). TIM1_UP and
  USART1_RX share DMA channel 5, so the burst uses the CC3 request on the update event (CCDS = 1, channel 6); DAC
  (ch2), CV burst (ch6) and a USART1 RX ring (ch5) ran together without errors (spec 3.2).
- **Voice MCU back to the TSSOP-20:** enough CH32V006F8P7 at hand, hand-soldered. Board 1's pin map carries over
  as it is, with KiCad's CH32V003 TSSOP-20 symbol (same pinout); the QFN-32's extra pins are not needed: two LEDs on
  PD0 and PC3, the self-test option on PA2 and PD2, the clock option on PA1, PC5 spare. With the TSSOP-20 the SPI
  question is the same as before: the pins fit (remap 4 with software NSS), DMA does not (SPI1_RX on the DAC's
  channel), so the bus stays UART + SYNC.
- **Mechanics and controls:** cards about 60 × 45 mm with 4 layers at 10 mm slot pitch (parts on one side, at most
  about 6 mm high), backplane 2 layers within 100 × 100 mm; no controls on the instrument, USB only.
- **Bus protocol proposal (bus.md):** synchronisation over latency. Each card runs its control tick on the SYNC
  edges and scales its oscillators to the measured frame period; every event carries its execution frame and is
  sent two frames ahead; what a card computes in frame n reaches its outputs at frame n + D, the DAC switch exact
  to one carrier period. With 256-period DAC buffer halves (instead of 1024) D = 4 frames: 6–7 ms from MIDI to sound,
  a few µs between cards, 3 KB of RAM freed. Side finding: at 1 Mbaud the V006's USART divider (3.0, 1/16
  resolution) cannot fine-tune the baud rate; the HSITRIM trim alone gives ±0.1 %.
- **Board 1, DAC loading and half rate:** both dual-PWM mechanisms work (a TIM2 DMA burst on TIM2_UP, or a
  second request on ch7), exact in register read-back and on the pins. Better: one DMA request per carrier period.
  TIM2 has no repetition counter, but in centre-aligned mode 2 (CMS = 10) a CC3 compare at 64 requests only on the
  up-count, and the value then loads at the top, so the pulse stays symmetric. 1 byte per period instead of 2
  (single PWM), 3 instead of 4–6 (dual, as a burst from the same request); it needs DMA ch1, so the ADC runs
  without DMA. Also found: the current DAC's pulses are symmetric only because its first request happens to fall
  on a bottom update. Half rate saves 28 % of the CPU; on the hardware its only measurable cost is the polyBLEP
  saw's aliasing at 93.75 kHz, −48.5 to −51 dB re the fundamental at C5–C7, nothing below C5 or in the
  three-oscillator tunes. That is oscillator aliasing, which S9b leaves out (it band-limits the oscillators); the
  model's −57 to −67 dB stays unexplained but has no counterpart on the hardware. Full rate stays the default.
  Short buffer halves underran because board 1's main loop stalls for 4–10 ms: the new firmware renders in the DMA
  interrupt.
- **Voice card schematic:** `hw/voice.py` describes the card; the rev 0.1 generator now takes the board as a parameter
  (`hw/board.py`). Making it buildable from the JLCPCB lists changed a few values: the Sallen-Key became 11k / 11k with
  C1 = 2 × 330 pF and C2 = 330 pF (the only C0G values near the range: 100 pF, 330 pF, 2.2 nF), 31 kHz; the
  low-byte resistor 1M + 330k; the 220 µF rail capacitor (not on the lists) three 100 µF X5R ceramics with 22 Ω.
  Also settled: the VCA trim from a PWM pin (680k), 33k from both VCA difference-amp inputs to ground (inputs now
  2.44–3.13 V, below the MCP6002's transition), a 10k / 10 µF filter behind the CJ431, 100 Ω output isolation,
  the programmer's 5 V through a Schottky diode, 100 Ω bus series resistors with a SYNC pull-down for standalone
  detection. The CJ431's SOT-23 pinout is the TL432's (1 REF, 2 K, 3 A), not KiCad's TL431DBZ. S10 variant v5c is
  the card's netlist: within 1 dB of v5m everywhere, 8 dB better supply rejection at 100 Hz, and fully working at
  4.6 V; `hw/check_sim.py` checks all 134 simulated elements against the schematic. The vendor op-amp model's DC
  solution became marginal with seven instances; S10 now retries with other solver settings.
- **Voice firmware phase 1 (board 1):** the DAC loads once per period (format 4, DMA ch1; dual PWM as a build
  option), from 256-period halves rendered in the DMA interrupt at the low preemption level, so main-loop stalls
  no longer matter and the control tick still enters within 28 cycles. Touch UI removed. 0 overruns over the test
  tunes, 175 cycles per period for 3 oscillators, worst render 87 % of a half: about 13 % CPU remains for bus and
  sync (the CV DMA burst will add about 9 %). 6.9 KB static RAM, 540 B of stack never used; level and inharmonic
  content as before. Found on the way: a kettle strike blocks the DAC for 8.5 ms (soft-float coefficients in the
  tick); and the half-rate experiment build played high notes at half level, so its comparison holds only up to
  C5 (half rate: −51 against −56 dB aliasing at C5).
- **S12, backplane mixer:** two MCP6002 summing amplifiers on a CJ431 VREF, constant-power pan over the 8 slots at
  0.35 per card; 8 cards in phase reach 4.05 Vpp, 1.7 dB below clipping. The pseudo-differential input mirrors each
  slot's network from AUDIO_GND onto the + input (45 dB ground rejection typical, 29 dB worst case with 1 %
  resistors). Two surprises: the card's 100 kΩ line-out bleeder would pull the 2.5 V summing nodes (a 10 µF input
  capacitor per slot fixes it), and the MCP6002 alone rejects supply noise poorly at a noise gain of 3.8 (a
  47 Ω / 22 µF rail filter). USB audio: ADCs at 384 kHz, where the DAC carrier does not alias into the band.
- **MIDI and patches (midi.md):** multitimbral, as the more flexible choice: up to 8 parts, each with a MIDI channel,
  key range, a mask of card slots (which also sets its stereo place), a mode (poly, mono, legato, unison, drum kit)
  and a patch. Patches are 64 16-bit parameters plus a name, stored on the controller (library in flash, working
  copies in SRAM); every card keeps 4 patch slots, so parts sharing cards and drum kits switch sounds with a timed
  PATCH_SELECT instead of resending 150 bytes. Standard CCs for the common controls, NRPN for every parameter,
  SysEx and CDC for librarians. A first set of 23 programs, mostly the rev 0.1 presets ported from the analog DCO
  to the DAC oscillators.
- **Voice card sheets drawn:** all six sheets hand-laid out (`hw/layouts_voice.py`), checks unchanged (ERC clean,
  netlist and simulation cross-check). The review against the firmware found that the voice firmware still drives
  board 1's pins: PD4 and PC4 are push-pull outputs there but SYNC_IN and the loopback ADC input on the card, so
  the card needs its own board definition before its first power-up.
- **One op-amp package less:** the VBIAS buffer moved to the LM324's spare unit (1.0 V is well inside its input
  range; the buffer itself is needed, the expo divider's CV current would move a bare divider by up to 0.6 V),
  so the filter op-amp shares the VREF buffer's MCP6002: three MCP6002 instead of four. VREF keeps its buffer
  (behind the CJ431's noise filter; the difference amps need a low-impedance reference). The net V25 (VREF / 2,
  the expo reference transistor's collector voltage, named after rev 0.1's 2.5 V) is now VEXP_REF.
- **Card orientation:** the backplane connector moves to a short (45 mm) edge: the cards stand 60 mm tall and cover
  45 mm of backplane depth instead of 60 (backplane about 95 × 85 mm). The taller card wants card guides at the top.
- **Card size target:** at most 50 × 50 mm on 4 layers (fallback: 2 layers, about 50 × 60 mm). Courtyard estimate
  from the footprints: about 1320 mm² with 0603 passives (53 % of 50 × 50), about 1000 mm² with 0402 (40 %).
- **Controller plan (controller.md):** the computer plays the synth over USB-MIDI, so a MIDI DIN input is only a
  footprint for hardware without USB. Power from USB-C or an external 5 V header (jumper-selected, no diode drop).
  The V203 is programmed over SWD with the WCH-LinkE during development; its factory bootloader (BOOT0, over USB or
  USART1) allows updates without a programmer. First bench setup: a V203 development board as controller with
  board 1 as one voice.
- **Voice card PCB:** 50 × 50 mm, 4 layers (signals and parts on top, solid GND, split supply planes VA / +3V3 /
  +5V, signals on the bottom), routed by Freerouting with repair passes, DRC clean. 0603 passives did not fit at
  this size (ten parts found no place before routing), so the passives went to 0402 where the lists have them;
  test points 22 → 13. With the connector at the bottom and the parts facing you, pin 1 of J1 lands on the right,
  which put the analog core on the right and the MCU on the left. Space for the stereo pan stage is reserved
  beside J1. Silkscreen with labels on top, artwork and the J1 pinout on the bottom.
- **S13, stereo pan on the card:** current steering (two more BC847BS on the VCA collectors, pan voltage from PC5
  through an RC network) against a second complete VCA. Steering chosen: one envelope CV (the fine 10 + 2-bit one),
  calibration from the existing loopback, fewer parts. Its cost: the VCA re-biased (bases at 1.89 V), a fourth
  MCP6002, a linear pan law corrected in firmware (constant power, the level capped at 70.6 % at hard pan), and a
  click of about 27 mV per mV of steering-pair mismatch at the centre (none at hard pan). Connector: AUDIO_L on pin
  5, AUDIO_R on pin 7 (GND moved to pin 16), line out 1×3. The vendor op-amp model needed bounded solver attempts
  and sanity checks on every operating point (once it converged to a wrong one).
- **S12 again, two buses:** no fixed pan resistors; 56k per slot and channel, one shared 10 µF mirror capacitor
  per slot on AUDIO_GND (4.7 µF would halve the low-frequency ground rejection). 8 hard-panned cards stay 1.9 dB
  below clipping; L/R crosstalk drops below −105 dB, since separate L/R pins remove the path through empty slots.
- **Bench: V203 development board as controller, WCH CH32V006 evaluation board (QFN-32) as one voice.**
  The V203 runs `firmware/bench_ctrl` from its 8 MHz crystal: SYNC (1 kHz, PA8), the voice bus on USART3
  (PB10 / PB11), NRST, and an Ardulink-compatible SWIO bridge on USART1 for minichlink (`-C ardulink`); the
  voice firmware has a card build (`make BOARD=card`: the card's pin map, SYNC timestamps on PD4). Results: the
  V006 counts the SYNC edges exactly and its HSI sits within ±0.03 % of the crystal at factory trim, wandering by
  ±200–250 ppm; the DAC runs on the card build. Still open: the bus wire landed on PA2 instead of PD6 (found by
  holding the line low and reading all V006 ports), and the SWIO bridge needs a pull-up (none on the line: every
  read was 0), which the backplane gets for every slot.
- **Backplane proposal (backplane.md):** 95 × 85 mm, 2 layers. The CH32V203's 37 GPIO are all assigned (bench
  pins kept: USART3 for the bus, SYNC on PA8, USART1 free for the bootloader). MCO cannot feed CLK_IN: the V006's
  PLL is a fixed ×2 and needs 24 MHz, which TIM3 CH4 gives (144 / 6) locked to the crystal. A soft start in front of
  the slot rail (8 cards would draw about 1.8 A at plug-in), SWIO pull-ups per slot, no backplane SWIO header.
  About 150 assembled parts, 4–5 USD per board in JLCPCB parts; the host-port current switch is not on the lists.
- **Voice card with the stereo pan stage:** schematic (190 parts, ERC clean, all 158 simulated elements match
  S13's netlist) and a new 50 × 50 mm layout: corners and the left edge in use, the R difference amp and both output
  stages beside J1, SWIO pre-routed along the edges, the VCA collectors pre-routed into the steering pairs. Six full
  Freerouting passes with repair rounds; the best is DRC clean. Several analog tracks got much shorter (the expo
  reference 41 → 14 mm, the VCA collectors 36 → 5 mm); VREF grew to 128 mm, now reaching the R amp, which a VREF
  region on In2 would fix. J1: AUDIO_L 5, AUDIO_GND 6, AUDIO_R 7, GND 16; line out 1×3.
- **Paraphonic cards (DOPE.MOD in the emulator):** the one-note-per-card cover kept 48 % of the notes and sounded
  thin. With each card's three oscillators as three notes (own pitch, waveform and digital level each, through the
  shared ladder) 8 cards play 24 notes: 91 % of the notes and 99.5 % of the synthesisable energy of a 28-channel
  module, instruments grouped by card. A sample engine on the same paraphonic allocation would come close to the
  original (loudness correlation 0.98 against 0.84 for the synth), but needs more flash than a card has. Generic
  code: `sim/behav/para.py`, `tools/mod2events.py --per-card 3 --group`; the song renders stay private.
- **Supply margin and inrush:** the card works fully down to about 4.3 V on its analog rail (below, full cutoff
  with full resonance saturates the expo and resonance V→I transistors; the audio path itself holds to 4.0 V), so
  RFILT stays 22 Ω (0.1 V drop): the drop is permanent (the analog current), not only during inrush. Inrush: each
  card's 22 Ω limits it to about 230 mA (1.8 A for 8 cards, a few ms); the backplane keeps a soft-start footprint,
  unpopulated. An inductor would not help (it slows the edge, not the charge, and rings with the capacitors).
- **Backplane decisions:** 100 × 100 mm; an SPI flash footprint (W25Q128 / BY25D16ASTIG, unpopulated) on SPI1, the
  8 NRST lines through a 74HC595 on the same bus to free the pins.
- **Voice bus on the bench (bus.md 9):** the card build receives the bus at 1 Mbaud (COBS, CRC-8, timed events,
  patch slots, VOICE_STATE repair), takes its control tick from SYNC and answers HELLO / STATUS / COUNTERS; the V203
  bench controller sends FRAME, enumerates the card by chip ID and turns MIDI-like commands into timed packets.
  Measured from the SYNC edge of the execution frame to the note on the DAC pin: D frames + 8–9 µs (4.008 ms, spread
  8 µs over 10 notes), L − 1 + D from the transmitting frame. The modal strike went to fixed point (soft float took
  longer than a DAC buffer half in the tick); three-oscillator patches with vibrato leave too little CPU for dense
  traffic (about 40 missed buffer halves per 20 s at 16 notes per second; two oscillators and the modal patch none).
  The bench return line needs a push-pull bench build (no pull-up).
- **Voice bus with 8 voices, one card (bus.md 9.5):** the bench controller treats voices 1–7 as populated, allocates
  notes over all 8 and drives the bus from a load generator; the card discards the others' traffic. The bus sizes
  match the calculation; with `L` = 2 anything beyond 88 bytes of events per frame is late by whole frames (a legato
  chord change, controllers on 8 parts), saturation at about 86 bytes per frame. The card's CPU broke first: parsing
  cost 128 cycles per byte, foreign or not, and a two-oscillator patch missed 1300 DAC halves in 10 s under foreign
  traffic; dropping foreign packets at their address byte and an in-place decoder brought that to none (three
  oscillators still miss). Notes ahead of controllers in the controller kept the card's notes on time (4.010 ms,
  spread 5 µs) under a 72 B/frame controller flood that made them 1–2 frames late before; per-voice records halve
  chords. 2 Mbaud works on the bench but puts a burst into one tick of every card.
- **USB on the bench controller (controller.md 5) [2026-10-19]:** the V203 enumerates as a composite USB-MIDI + CDC
  device; USB-MIDI packets enter the MIDI → bus path where `e` does, the CDC port carries every bench command (the
  bus tests pass 17/17 over it, the Ardulink bridge too). The development board's USB-C turned out to be wired to
  USBFS (PB6 / PB7), so it runs on ch32fun's fsusb.c; an own USBD driver for the backplane's PA11 / PA12 builds but
  is untested. USB packet → note 5.0–6.0 ms (`D` = 4, `L` = 2), SYNC unchanged under USB traffic (< 1 ns), soft
  re-plug and V203 reset re-enumerate in under 0.7 s. The bench build's 10 KB memory map let the stack run into
  `.bss` (resets under load): now the C8T6's 20 KB. The USBD pull-up is switchable, its strength unproven (keep the
  1.5 kΩ footprint). With the lab user in the audio group the USB-MIDI endpoints pass through ALSA too: all bus
  checks as USB-MIDI, USB → note 5.0–6.0 ms, floods without loss (beyond the bus capacity the events arrive late,
  as expected), SYNC unchanged under a MIDI flood.
- **DAC render four to five times cheaper (bus.md 9.3, 9.5) [2026-10-20]:** measured on the V006 that a store costs
  3 cycles, a load 2, a taken branch 3, `mul` 1; the oscillators now run together between their polyBLEP regions
  (a saw is a phase shift and a multiply there, a pulse a constant), one store per sample, the hot loops in assembly
  where RV32E's 16 registers defeated the compiler; the error feedback needs one compare instead of four clamps; the
  modal resonators sit interleaved with alternating outputs. Bit-exact with the old renderer (a host test against
  the previous revision, and render-check hashes on the card). Three oscillators 44 k → 8–12 k cycles per buffer
  half, the modal patch 38 k → 21 k; the CV dithering moved from a 46.875 kHz interrupt to a DMA burst. Under 8-voice
  bus load and the stress test no patch misses a half (slack ≥ 99 periods, three oscillators ≥ 154), the CPU load
  with three oscillators is 23 % (was 91 %), and 650–680 bytes of stack stay free (156). A restriction of the
  three-oscillator mode to one waveform was not needed: it would change the existing presets and save nothing.
  The occasional half "missed" at a patch change was a render preempted by the DAC restart and checked against the
  new ring: no longer counted.
- **Pre-order software checks; software requirements and architecture [2026-10-20]:** the card firmware's pin map
  (`board.h`) agrees with the schematic netlist pin for pin. On the bench V006: the option bytes read USER = 0xF7, so
  PD7 is NRST by default (RST_MODE = 10b, reference manual 18.5), which the 74HC595 reset path relies on; the four CV
  PWMs toggle on PC6, PC7, PC0 and PD3 (TIM1 remap 0010b); TIM2 CH1, enabled by hand, drives PC5 beside the running
  DAC, so the pan PWM needs only firmware. Still to run before ordering: the return line open drain with a 1 kΩ
  pull-up (the bench always used `BUS_TX_PP`) and a push-pull NRST reset into the card. The design report gained a
  software requirements section (60 requirements with source, verification and status) and a software architecture
  section (context, decisions, card and controller views), both drafts for review.
- **Host port fitted [2026-10-20]:** user decision; the USB-A host port (J2, TPS2051C U4, ESD U5, VBUS capacitors,
  enable and fault resistors, two LEDs) is now populated: 10 more assembled parts (150), U4 and J2 hand-soldered,
  parts cost about US$ 5.3 per board, all codes already on the board and in stock. Only the two 15 kΩ host
  pull-downs stay unfitted: ch32fun's register map has a bit that disables USBFS's internal host pull-downs, so they
  exist. Schematic, PCB attributes (DRC with parity clean), fab data, renders and the report regenerated. The host
  driver is being tried on the development board, whose USB-C is the same USBFS peripheral.
- **USB host on the development board (controller.md 6) [2026-10-20]:** a minimal USB-MIDI host for USBFS in the
  bench controller (`make USBH=1`, `usbhost.c`, main loop only, one poll per USB frame after SOF; the USB device then
  on USBD). The internal D+ / D− host pull-downs exist: the GPIOs cannot reach PB6 / PB7 while USBFS is configured,
  so a pin charged with the SIE held in reset is timed after release. Against the lab PC's 15 kΩ the lines fall
  twice as fast with `UH_PD_DIS` = 0, and with `UH_PD_DIS` = 1 exactly as through the PC alone, giving about
  13–15 kΩ: the 15 kΩ footprints stay unfitted. Loop test with the controller's own USBD device jumpered onto its
  host port:
  - enumerated in 162 ms; also the first proof of the USBD driver, with its internal pull-up only;
  - bustest's MIDI checks pass through device → host → card;
  - a 32 000-event burst arrives with no loss and no errors; host OUT works; detach / re-attach works (0.57 s);
  - SYNC unaffected (TIE p-p 0.9 ns, frame interrupt ≤ 4 µs); host CPU 2.75 µs per USB frame;
  - USBD device + USBFS host together: 27.7 KB flash, 9.0 KB SRAM.

  A real keyboard (needs 5 V on the board's VBUS), low speed and the TPS2051C fault path are still untested.
- **Effects slot, new repository name [2026-10-20]:** reverb cannot run on the cards (8 KB) or the controller (no
  RAM, no DAC); it needs its own DSP and codec after the mixer. There is no room for an extra header, so slot 1 is
  convertible instead (user decision): pins 15 / 14 carry CLK / SWIO_1 through 0 Ω (fitted) or the stereo mix
  through 220 Ω (not fitted, R80 / R82); an effects card returns through the slot's audio pins (mixing in, with a
  capped loop gain because the send contains the return) or, for loop-through, on slot 1's pins 3 / 4 (GND on the
  other slots; user proposal: a voice card grounds them harmlessly) into the line-out stage instead of the mix
  (R83 / R84 not fitted; R71 / R75 removed then). Backplane re-routed for the four 0603 positions. The silkscreen of both boards names the new
  repository github.com/cpldcpu/TouchSynthPoly (the project becomes its own repository, a fork of TouchSynth;
  the move itself is still open). The backplane's flash footprint is labelled SPI FLASH. The eight conversion parts sit
  in two labelled blocks of pairs on the silkscreen (V | FX for the sends P15 / P14, V | LOOP for the line-out
  feed L / R) with the rule "FX CARD: V OUT, FX/LOOP IN"; re-routed, DRC clean.
- **Pre-order bench checks done [2026-10-20]:** the card's production build (open-drain return line, no
  `BUS_TX_PP`) with a 1 kΩ pull-up on the return line: all bus checks that need no SWIO and the stress test pass, 61
  replies with 0 CRC errors. A reset through NRST driven push-pull, as the 74HC595 does (new bench command `N` on
  PB12, `bustest.py nrst`): 3 of 3 resets re-enumerated in 0.5–0.7 s. The first try did nothing: on the bench EVT's
  QFN-32 V006 the reset pin is PA7, not PD7 (only the TSSOP-20 card has it on PD7).
