# TouchSynth Poly: voice bus protocol

Status: 0.2 (2026-10-19), implemented and tested on the bench (section 9); proposal 0.1 of 2026-10-18 extended. Physical
layer and the reasons for UART + SYNC: [spec.md](spec.md) section 5;
clock trimming: spec section 6; requirements: [design.md](design.md).

## 1. Goals

1. **Synchronisation first:** every card turns the same event into sound at the same moment, to within a few
   microseconds, independent of when the bytes reach it, how busy it is or where it is in its DAC buffer. Pitch is
   locked to the controller's crystal, with no long-term drift between voices.
2. **Fixed latency instead of minimal latency:** a constant delay of a few milliseconds is accepted; jitter
   between voices is not.
3. **Simple and robust:** broadcast without acknowledgements; lost packets are repaired by periodic state
   refreshes; one card talks at a time on the return line, and only when asked.

## 2. Physical layer

| Line | Driver | Electrical |
|---|---|---|
| BCAST (card RX) | controller USART TX, push-pull | 1 Mbaud 8N1, 33 Ω series resistor at the controller |
| RETURN (card TX) | the addressed card only, open drain | 1 kΩ pull-up to 3.3 V on the backplane (about 150 pF on the bus: 0.3 µs rise time against a 1 µs bit) |
| SYNC | controller timer output, push-pull | 1 kHz square; the rising edge starts a frame |
| NRST, SWIO | per slot: NRST driven directly by a 74HC595 on the controller's SPI (no pull-downs: the cards may run until the controller resets them), SWIO from controller GPIOs | reset / enumeration, programming (spec 4, backplane.md) |

At 1 Mbaud a card's USART divider is 3.0 (48 MHz / 16), and the V006's divider resolution (1/16) cannot correct the
clock by itself. The baud accuracy therefore comes from the HSITRIM coarse trim: within ±0.1 % of the crystal,
plus 0.02 % HSI wander, far inside the UART's ±2 %. Before the trim the HSI may be off by up to 2 %, so a card does not
listen to the bus until it has trimmed (section 6).

## 3. Time base

**Frame:** the 1 ms between two rising SYNC edges, numbered by the controller (`FRAME` message, 16 bit, wrapping).
All timing in the protocol is in frames. Finer timestamps would gain nothing: USB-MIDI delivers events in 1 ms USB
frames without timestamps.

On each card:

- **Control tick = SYNC edge.** The SYNC interrupt (EXTI on PD4) replaces SysTick as the 1 kHz control tick
  (envelopes, LFOs, glide, CV laws: `synth_tick` of rev 0.1). All cards therefore compute their envelopes and
  LFOs on the same ticks, from the same events; global LFOs take their phase from the frame number and stay
  phase-locked across voices without messages.
- **Frame position in the DAC stream:** the SYNC interrupt also reads the DAC's DMA position, giving the carrier
  period `s_n` at which frame `n` began, and keeps a filtered estimate `P̄` of carrier periods per frame
  (nominal 187.5).
- **Pitch lock:** the oscillator phase steps are scaled by 187.5 / `P̄`, so the pitch follows the crystal, not the
  HSI. Long term the voices cannot drift apart; what remains is the HSI's own short-term wander (0.35 cent rms,
  measured on board 1), which the scaling follows only with its averaging time. The shared clock (CLK_IN) removes
  that too, if it turns out to be audible.

### 3.1 Presentation delay

Everything tick `n` computes appears at the card's outputs at frame `n + D`, on every card:

- **Oscillators (DAC):** tick `n` stores the voice state `V_n` (phase steps, waveform parameters, gate) in a
  queue. The renderer uses `V_n` for the carrier periods from `b_n = s_n + D × P̄` on; it splits its 32-period
  block at `b_n`, so the switch is exact to one carrier period (5.3 µs).
- **CVs (cutoff, resonance, VCA, VCA trim):** tick `n` stores `CV_n` in a delay line; tick `n + D` loads it into the
  TIM1 burst table.

`D` must cover the DAC's render lead (two buffer halves) plus the tick's run time:

| DAC buffer half `H` | Render lead | `D` | Ring RAM (single PWM) |
|---|---|---|---|
| 1024 periods (5.5 ms, rev 0.1) | 10.9 ms | 12 frames | 4 KB |
| 256 periods (1.37 ms, voice firmware) | 2.7 ms | 4 frames | 1 KB |

Proposal: `H` = 256, `D` = 4. It frees 3 KB of RAM (with once-per-period loading the ring is only 0.5 KB, 1.5 KB
for dual PWM; spec 3.2) and costs only the per-half overhead, which is small because the renderer works in
32-period blocks anyway. A 1.37 ms half must never wait for the main loop (on board 1 it stalls for 4–10 ms:
console, UI), so the renderer runs in the DMA1 ch1 half/complete-transfer interrupt at the low preemption level
(INTSYSCR.INESTEN, IPRIOR 0x80), the control tick above it. Measured on board 1: the tick enters within 27–28
cycles while a render runs (without nesting it waited up to 45 k cycles); the worst render took 57.3 k of 65.5 k
cycles (87 %), at least 32 periods of slack, 0 overruns over tunes 33–40 with the console polled; the per-half
overhead is below 1 % (175 against 179 cycles per period at 256- and 32-period calls). The modal patch uses
252-period halves (21 samples of 12 periods); with the bus, H must be the same for all patches. If `V_n` is
not ready in time (a late tick), the renderer keeps `V_{n−1}` and counts the event.

What limits the alignment between cards: the SYNC timestamp (EXTI entry, < 1 µs jitter), the block split (one
carrier period) and the prediction of `b_n` from `P̄` over `D` frames (HSI wander 2e-4 × 750 periods, a fraction
of a period). Together a few microseconds.

### 3.2 Scheduling and latency

The controller stamps every timed event with the frame in which the cards execute it: the current frame plus a
**bus lead** `L` (2 frames: one to transmit, one for the cards to parse). Total latency from a MIDI event to sound:

  arrival → frame `a + L` (tick on all cards) → frame `a + L + D` (sound) = **6 to 7 ms** with `D` = 4.

Because events carry their execution frame, a burst that takes longer than one frame to send (a program change, an
8-voice chord plus controllers) is spread over the frames before its deadline without affecting timing. Only if
the queue exceeds the lead does the controller push events to a later frame (counted, and a reason to raise `L`).

## 4. Packet format

Packets are COBS-encoded and terminated by 0x00, so a receiver resynchronises at the next zero byte after any
error. *[2026-10-19]* A packet may also begin with a 0x00 (the cards' replies do, so the controller resynchronises even
after noise on the return line); empty packets are ignored. The card accepts packets of up to 64 decoded bytes.
Decoded content:

```
controller → cards:  dst  type  [frame]  payload...  crc8
card → controller:   src  type            payload...  crc8
```

| Field | Meaning |
|---|---|
| `dst` | voice bitmask: bit k = the card with address k (0…7); 0xFF = all; 0x00 = unaddressed cards (enumeration). *[2026-10-19]* 0xFF also reaches unaddressed cards (a card that was never enumerated still plays) |
| `src` | the replying card's address |
| `type` | message type; unknown types are ignored (forward compatibility) |
| `frame` | timed messages only: low 8 bits of the execution frame, read relative to the card's frame counter (−128…+127). Late (negative): executed at the next tick and counted; more than 32 frames ahead: dropped. *[2026-10-19]* "The next tick" is the tick that parses the event: it runs there at once |
| `crc8` | CRC-8 (polynomial 0x07) over the decoded bytes; packets with a bad CRC are dropped and counted. *[2026-10-19]* Initial value 0, MSB first, no final XOR (CRC-8/SMBUS, check value 0xF4 for "123456789"): the CRC over a whole packet including its CRC byte is 0 |

Multi-byte values are little-endian. Pitch is in 1/256 semitone (MIDI note × 256 + bend); the card's oscillator
tables (1/16 semitone) take the top bits.

## 5. Messages

### 5.1 Controller → cards

| Type | Name | Timed | Payload | Use |
|---|---|---|---|---|
| 0x01 | FRAME | | frame u16 | first packet after every SYNC edge; cards check their frame counter (a mismatch resynchronises it and is counted) |
| 0x02 | CONFIG | | `D` u8, `L` u8, tuning i16 (1/256 semitone), flags u8 | system settings; sent after enumeration and on change |
| 0x03 | ASSIGN | | address u8 | to `dst` 0x00: the one released, unaddressed card takes the address and answers HELLO |
| 0x10 | NOTE_ON | yes | pitch u16, velocity u8, flags u8 | flags: retrigger envelopes, reset oscillator phase, legato (glide from the current pitch). *[2026-10-19]* bit 0 retrigger (envelopes from zero; else the attack starts from the current level), bit 1 reset the oscillator phases, bit 2 legato |
| 0x11 | NOTE_OFF | yes | velocity u8 | release |
| 0x12 | PITCH | yes | pitch u16 | new pitch of a sounding voice (glide target, per-voice bend) |
| 0x13 | VOICE_STATE | yes | gate u8, pitch u16 | refresh: "at this frame the voice is gated / not gated at this pitch"; the card corrects itself if it differs (repairs a lost NOTE_ON or NOTE_OFF) |
| 0x20 | CTRL | yes | id u8, value i16 | performance controls of a part, to its voices: 0 pitch bend (−8192…+8191), 1 mod wheel, 2 channel pressure, 3 expression (0–16383), 4 tempo (0.01 BPM), 5 LFO phase reset |
| 0x21 | PARAM | yes | id u8, value i16 | one parameter of the active patch (live edit), IDs 0–63 as in [midi.md](midi.md) section 4; IDs 64–79 per-voice settings (part volume, unison index, CC offsets) |
| 0x22 | PATCH_DATA | | slot u8, offset u8, count u8, values i16 × count | into one of the card's 4 patch slots (not the active one); a whole patch spread over several frames |
| 0x23 | PATCH_SELECT | yes | slot u8 | this slot becomes the active patch at this frame: a program change hits all addressed voices on the same tick; also used before a NOTE_ON when a voice changes parts or plays another kit sound (midi.md 2) |
| 0x24 | PATCH_PRESET | | slot u8, preset u8 | *[2026-10-19]* interim, until PATCH_DATA is mapped onto the voice engine: one of the card firmware's built-in presets into a patch slot (the bench uses program number = preset index) |
| 0x30 | REQUEST | | what u8, arg u8 | to one card: STATUS, CAL_DATA (block `arg`), HELLO. *[2026-10-19]* what: 0 STATUS, 1 CAL_DATA, 2 HELLO, 3 COUNTERS (arg 1: clear the maxima after the reply). To `dst` 0x00 the unaddressed card answers |
| 0x31 | CALIBRATE | yes | what u8 | loopback calibration (the voice mutes itself, answers STATUS "busy" until done) |

Unison: one NOTE_ON with several bits in `dst`; each card applies its own detune (patch parameter × its address).

*[2026-10-19]* **Per-voice records** (type | 0x40: 0x50–0x53 for NOTE_ON, NOTE_OFF, PITCH, VOICE_STATE, 0x60 / 0x61
for CTRL / PARAM): one packet for several voices with different payloads. After the frame byte (and, for CTRL / PARAM,
the ID) follows one record per set bit of `dst`, in address order: the plain message's payload (NOTE_ON 4 bytes,
NOTE_OFF 1, PITCH 2, VOICE_STATE 3, CTRL / PARAM value 2). A card takes the record at the position of its bit (the
number of set bits below it) and runs it as the plain message; equal payloads still go as one plain message with
several bits in `dst`. A chord of 8 is 38 bytes instead of 80, VOICE_STATE for 8 voices 30 instead of 72. Every
addressed card decodes the whole packet, so they pay off where they replace several packets (9.5). An unaddressed card
ignores them (counted as other).

### 5.2 Card → controller (only in reply)

| Type | Name | Payload |
|---|---|---|
| 0x80 | HELLO | chip unique ID (from the V006's electronic signature), firmware version u16, capabilities u8 (dual-PWM fitted, ...). *[2026-10-19]* The ID is 8 bytes: ESIG UNIID1, UNIID2 (0x1FFFF7E8, 0x1FFFF7EC) as two u32; UNIID3 reads 0xFFFFFFFF on the V006. It equals minichlink's "Part UUID". Capabilities: bit 0 dual PWM |
| 0x81 | STATUS | flags u8 (synced, calibrated, busy, standalone), HSITRIM u8, clock error i16 (ppm, from `P̄`), counters u8 each: CRC errors, late events, frame slips, late ticks, DAC underruns; CPU load u8 (%). *[2026-10-19]* flags bits 0 synced, 1 calibrated, 2 busy, 3 standalone; counters saturate at 255; then (extension) the bus state u8: 0 standalone, 1 trim, 2 listen, 3 synced, 4 SYNC lost |
| 0x82 | CAL_DATA | block u8, calibration values |
| 0x83 | COUNTERS | *[2026-10-19]* diagnostics (REQUEST 3), u16 each: bytes received, packets accepted, CRC errors, COBS errors, UART errors, late events, events too far ahead, event queue full, frame slips, late ticks, DAC underruns, SYNC gaps bridged, VOICE_STATE repairs, replies, other (unknown / unsupported / short), SYNC glitches; frame counter, longest tick (cycles), stack never used (bytes); u8 each: gate, preset, active slot, `D`; pitch u16; DAC render: longest (cycles), least slack (carrier periods). *[2026-10-19]* Then (extension) u16 each: the parser's mean cycles per tick (over 256 ticks) and its longest, the most bytes parsed in one tick, packets for other cards, the longest tick without the replies (a REQUEST's reply takes up to 10 k cycles) |

Only one REQUEST or ASSIGN is outstanding at a time; the card answers as soon as it has parsed it (within 2 frames),
the controller times out after 5 frames. The return line needs no time slots: it is separate from the broadcast line
and only one card is ever asked.

The chip ID lets the controller keep each card's calibration and identity even if cards change slots.

### 5.3 Bandwidth

1 Mbaud 8N1 = 100 bytes per frame. Encoded sizes (with COBS overhead and delimiter): FRAME 7 bytes, NOTE_ON 10,
CTRL 9, PATCH_DATA 7 + 2 per value. An 8-voice chord with FRAME is 87 bytes: one frame. A 64-parameter program
change is about 150 bytes over 2–3 frames before its PATCH_SELECT. Idle frames carry the refreshes: VOICE_STATE for one
voice every 6 ms (each voice every 50 ms) and a slow round-robin resend of the active patch, so a lost PARAM also
heals.

*[2026-10-19]* Measured with 8 voices (9.5), the sizes hold to the byte (also NOTE_OFF 7, CTRL / PARAM / VOICE_STATE 9,
PATCH_DATA of 8 values 24). A frame carries 88 bytes of events after FRAME, and with `L` = 2 there is no slack: what
does not fit the next frame is late at the cards. The chord of 8 just fits; a legato chord change (8 NOTE_OFF and 8
NOTE_ON, 143 bytes) or a chord with bend, wheel and cutoff (114) is late by a frame for some voices. The VOICE_STATE
refresh of 8 voices takes 1.5 bytes per frame.

## 6. Sequences

**Power-up and enumeration.** Until the controller firmware runs (power-up, a controller reset, the bootloader,
a halted debugger) the 74HC595 outputs are off and the cards run on their own (standalone, below); they never send
unless addressed. The controller then shifts 0x00 into the 595 and enables its outputs, which resets every card,
starts SYNC and FRAME and, slot by slot:

1. Release NRST of slot k. The card boots, timestamps 100 SYNC periods (100 ms), sets HSITRIM, configures its
   USART, waits for a 0x00 delimiter and starts parsing.
2. From 120 ms on the controller sends ASSIGN (address k) to `dst` 0x00 every 10 ms; the card takes it and answers
   HELLO.
3. No HELLO within 300 ms: slot k is empty. Next slot right after HELLO or timeout.

About 1 s with 8 cards, plus 0.3 s per empty slot; then CONFIG and the patch to all. Address = slot index, so the
controller knows each voice's pan position.

**Standalone.** No SYNC edge within 200 ms of reset: the card runs on SysTick ticks as a mono synth with the SWIO
console (spec 3.4).

**SYNC lost while playing** (a controller fault without NRST): the card bridges the gap with SysTick ticks so that
a single missed edge does not glitch, mutes its VCA after 10 ms without SYNC and re-locks when SYNC returns. After a
controller reset the cards keep running (muted, without SYNC) until the restarted controller resets and enumerates
them again; a card that does not respond can also be reset over its SWIO line.

**Calibration.** CALIBRATE (timed) → the card mutes and runs its loopback routine → the controller polls STATUS
until "busy" clears → reads CAL_DATA blocks and stores them by chip ID. The calibration itself stays on the card
(it needs the card's ADC and DAC); the controller only keeps a copy.

**Firmware update** goes over SWIO, not over the bus (spec 4).

## 7. Card resources

| Item | Size |
|---|---|
| RX DMA ring (USART1 RX, ch5) | 256 bytes (2.5 frames at full load); parsed in the SYNC tick, at most 100 bytes per tick (a few % of the CPU). *[2026-10-19]* Measured: 1 k cycles per tick for FRAME alone, 3–4 k (6–8 %) with 70 foreign bytes per frame, 100–125 cycles per fully decoded byte (9.5) |
| Event queue (timed events waiting for their frame) | 16 × 8 bytes |
| Voice state queue `V_n` and CV delay line | `D` + 1 entries × about 24 bytes |
| Patch slots | 4 × 128 bytes (the active patch and up to 3 more: kits, parts sharing cards) |

## 8. Open points

- Parameter IDs: [midi.md](midi.md) section 4 (proposal); CTRL IDs above.
- Measure the per-half overhead with `H` = 256 and the tick's run time with parsing (board 1). *[2026-10-19]* The tick
  with parsing, measured on the V006 bench (section 9.3).
- Whether the renderer's block split at `b_n` is cheap enough; otherwise the 32-period block boundary (171 µs)
  is the alignment, still far below audibility for chords.
- ~~The V006's unique ID length and location (electronic signature registers).~~ *[2026-10-19]* 64 bit at 0x1FFFF7E8
  (5.2).
- *[2026-10-19]* CPU budget with the bus: the DAC render of the three-oscillator and the modal patches leaves too little
  time for the tick under dense traffic (section 9.3).
- Whether 2 Mbaud on the broadcast line is needed (no, at the sizes above). *[2026-10-19]* It works on the bench, but
  concentrates a burst into one tick of every card (9.5); not before the cards parse outside the tick.
- *[2026-10-19]* Parsing in the card's main loop (below the DAC render): bus traffic could then delay events but never
  cost a DAC buffer half; needs `L` = 3. Coalescing of queued controller values in the controller (9.5).
- *[2026-10-19]* Only with 8 real cards: the electrical load on BCAST, RETURN and SYNC, the NRST enumeration, the
  alignment of a chord across cards, each card's CPU under its own and the others' traffic (9.5 emulates 7 voices).

## 9. Implementation notes (bench firmware, 2026-10-19)

*[2026-10-19]* Card: `firmware/voice` (`make BOARD=card`, `bus.c`); controller stand-in: `firmware/bench_ctrl`
(CH32V203 development board); tests: `tools/bustest.py`. One card, address 0.

### 9.1 Clarifications

- **Parsing in the tick.** The tick parses only the bytes that arrived before it began (the RX ring position is taken
  at its start). A slow tick (one that builds a reply takes up to 0.2 ms) would otherwise read the next frame's FRAME
  and count a slip.
- **FRAME check.** FRAME(f) is parsed at tick f + 1 and consistent if the counter reads f + 1. A SysTick tick that
  bridges a missing SYNC edge runs 0.25 ms after it, when that frame's own FRAME has already arrived: there a counter
  reading f or f + 1 is consistent. The counter is 16 bit and wraps.
- **SYNC glitch filter.** The card ignores SYNC rising edges less than 3/4 frame after the last one (counted). On the
  bench they occur at the falling edge of SYNC (0.5 ms), about one per 2–3 s while the DAC runs (none without it).
- **Enumeration without NRST (bench).** The controller asks address 0 for HELLO first (a card that kept its address
  answers), else sends ASSIGN; while running it repeats ASSIGN to `dst` 0x00 every 500 ms so that a card reset over
  SWIO is found and configured again. With NRST (backplane) the 500 ms ASSIGN is not needed.
- **HSI trim.** One HSITRIM step is about +0.19 % up and −0.25 % down on the bench V006 (trim 18: +3711 ppm,
  14: −4970 ppm against SYNC); a card started at trim 19 corrected itself to 16 in one step. The bench HSI is within
  ±0.06 % at the factory trim, so no step is taken normally.

### 9.2 Presentation delay as built

- CVs: hw_cv_set stages the codes; once per tick a delay line of `D` + 1 entries loads those of `D` ticks ago into the
  TIM1 PWM (the VCA trim is not delayed).
- DAC: the tick queues `V_n` (pitch, gate, phase reset, staged modal strikes) with `b_n = t_n + D × P̄` in SysTick
  cycles (SysTick and TIM2 both count HCLK, so the ring entry the DMA loads at any time follows from the SysTick time;
  no DMA position needs reading). The renderer splits its half at the period of `b_n`: oscillators exact to one
  carrier period, the modal engine at the nearest sample (12 periods, 64 µs). Strikes are computed in the tick
  (fixed point, 5.5 k cycles for 17 modes) and start at their `V_n`. A `V_n` equal to the last one is not queued.
  The carrier runs from the PATCH_SELECT of a DAC patch on (before, the engine started it with the first note).
- Pitch lock: the oscillator phase steps are scaled by 48000 / `P̄` (HCLK cycles per SYNC period, filtered over
  about 64 frames).

### 9.3 Bench results

- SYNC edge of the execution frame to the first DAC period of the note (scope, NOTE_ON with phase reset): 4.008 ms
  mean with `D` = 4 (10 notes, spread 8 µs), 3.008 ms with `D` = 3, 6.009 ms with `D` = 6; from the SYNC edge of
  the frame that transmits the event: 5.008 ms with `L` = 2, 6.009 ms with `L` = 3. The 8–9 µs above `D` frames are
  one to two carrier periods.
- CRC: a corrupted NOTE_ON is dropped and counted, a VOICE_STATE refresh restores the note within 50 frames.
- 1 Mbaud on both lines, 28 k packets in 20 s with notes, bend and controllers every 14 ms: no CRC, COBS, UART, late
  or slip errors.
- Tick run time (V006, 48 MHz): synth_tick 1.1 k cycles, the `V_n` commit 0.4–1 k, plus the parsing; a modal strike
  5.5 k; a REQUEST with its reply up to 10 k; PATCH_SELECT of the modal patch 24 k (the DAC restarts with its
  252-period halves; the mallet table by a sine recurrence).
- CPU load (tick and DAC render): 3 % without a DAC patch (8 % under the stress traffic), 80 % with two oscillators
  or the modal patch, 90 % with three oscillators. The render alone takes up to 49 k (modal) and 59 k (three
  oscillators) of the 64.5 k cycles of a buffer half, and the ticks that preempt it add to that. At 16 notes per
  second, each with bend, a cutoff PARAM and the mod wheel, the two-oscillator and the modal patch miss no half in
  20 s; the three-oscillator patch misses 33–49 (the wheel's vibrato changes its `V_n` every tick; none without
  traffic), and a switch to the modal patch occasionally costs one half. Open: a cheaper oscillator render or CV
  PWM interrupt, or at most two oscillators per voice.
- *[2026-10-20]* After the render rewrite (9.5, end): CPU load 8 % without a DAC patch, 25 % with two oscillators,
  23 % with three (moog_bass; moog_open 21 %), 32–43 % with the modal patch and two ringing banks (was 8, 82, 91, 88,
  59–79 % in the same probe: a held note, refresh traffic). The render takes 6.5–12 k cycles of the 65.5 k of a
  half with oscillators and 21 k with the modal patch; the CV dithering no longer interrupts. The stress test with
  three oscillators misses nothing (slack ≥ 157 periods). The half "missed" at a patch change was a counting
  artefact: a PATCH_SELECT tick that stops or restarts the DAC preempts a render, which then checked its end against
  the new DMA ring; such a render is no longer counted (the mixed stress test: 0 in 8 runs, before 1 in about every
  other run; slack ≥ 96 periods, the modal PATCH_SELECT tick 27 k cycles).

### 9.4 Bench deviations

- The return line has no 1 kΩ pull-up on the bench (only the V203's internal ~40 kΩ, far too slow for 1 Mbaud: every
  reply arrived corrupted). The bench card build (`BUS_TX_PP=1`) drives PD5 push-pull while its own reply goes out
  and releases it afterwards; the default build is open drain as above.
- PATCH_DATA and CALIBRATE are not implemented; PATCH_PRESET stands in for PATCH_DATA. PARAM maps the IDs that exist
  in the current voice engine (20 glide, 28 vibrato, 32–35 filter, 38–45 envelopes, 47 volume); CTRL implements bend
  (fixed ±2 semitones), mod wheel (up to 50 cent extra vibrato), expression and LFO phase reset.

### 9.5 Eight voices with one card (load test)

*[2026-10-19]* With `V` the bench controller treats voices 1–7 as populated (no HELLO expected, nobody answers) and
sends all their traffic; the card is voice 0 and discards the rest. Notes are allocated as in [midi.md](midi.md) 2
(one poly part: the voice holding the same note, else the oldest released, else the oldest held one) or go to 8
single-voice parts (MIDI channel k → voice k). A generator in the controller plays chords and controller sweeps
through the same MIDI path. The refreshes cover every voice (VOICE_STATE every 50 / 8 frames, PATCH_PRESET every 200);
PATCH_DATA (8 values) can go to the virtual voices as load. `tools/bustest.py load` and `bustest.py latency --load`;
1 Mbaud, `D` = 4, `L` = 2, the card on lead_dac (two oscillators) unless stated.

**Bus.** The peak bytes per frame equal the sizes from sections 4 and 5 (FRAME included):

| Burst (one MIDI command: one execution frame) | Bytes | Frames | Late at `L` = 2 | With per-voice records |
|---|---|---|---|---|
| chord of 8 | 87 | 1 | 0 | 45, 0 |
| legato chord change (8 NOTE_OFF, 8 NOTE_ON) | 143 | 2 | 5 packets by 1 frame | 52, 0 |
| chord + bend, wheel, cutoff, one part | 114 | 2 | 3 by 1 | 72, 0 |
| chord + bend, wheel, cutoff, 8 parts | 303 | 4 | 24 by up to 3 | 114, 1 by 1 |
| VOICE_STATE refresh, 8 voices | 9 every 6 frames: 1.5 per frame | | | 30 every 50: 0.6 |
| PATCH_DATA, 8 values | 24 (one every 16 frames: 1.5 per frame) | | | |

Sustained: 8 single-voice parts, chords every 250 frames, bend, wheel and cutoff on every part every N frames
(late packets per 5 s; V_PRIO and per-voice records: below):

| N (events / s) | Bytes / frame | Frames at the budget | Late, `L` = 2 | `L` = 3 | V_PRIO: notes late | Per-voice records: bytes / frame, late |
|---|---|---|---|---|---|---|
| 8 (3000) | 35 | 25 % | 9 495 | 3 825 | 0 | 16, 5 |
| 4 (6000) | 62 | 50 % | 18 993 | 7 650 | 0 | 25, 10 |
| 3 (8000) | 79 | 66 % | 25 489 | 10 374 | 0 | 30, 7 |
| 2 (12000) | 86, saturated | 98 % | 45 148 (by up to 16 frames) | 45 124 | 0 | 42, 0 |
| 1 (24000) | 86, saturated | 98 % | 45 240 | | 0 | 75, saturated |

One poly part (the default setup) needs little: chords with the three controllers every 5 frames take 14 bytes per
frame, nothing late (each controller is one packet to the part's bitmask). The limits: anything beyond one frame of
events is late by whole frames (`L` = 2), so a controller step on 8 parts (216 bytes) is late even at a 30-byte
average; at about 86 bytes per frame (79 of events) the bus saturates, the backlog grows without limit and the
refreshes, which only use idle room, stop.

**Card.** Its CPU breaks first. Parsing in the tick cost about 128 cycles per byte (COBS, CRC, then the address
check; the V006 runs from flash with 2 wait states), for foreign bytes as for its own. Foreign traffic of 71 bytes per
frame (7 virtual parts, controllers every 3 frames; the card holds a note; DAC buffer halves missed in 10 s):

| Patch | No traffic: missed, slack_min | Before | Early discard | Early discard + in-place parser |
|---|---|---|---|---|
| lead_dac (2 oscillators) | 0, 38–43 periods | 1 297 | 0 | 0 |
| kettle (modal) | 0, 85 | 0 | 0 | 0 |
| moog_bass (3 oscillators) | 1–3, 4–11 | 6 263 (and 459 late `V_n`) | 2 231 | 1 003–1 748 |
| init (no DAC) | – | 0 | 0 | 0 |
| Parser, cycles per tick: mean, longest | 1.0 k, 3.2 k | 8.8 k, 11.7 k | 4.9 k, 6.6 k | 3.0–4.1 k, 5.8 k |

The tick without replies: 7 k cycles without traffic, 9 k under this load. Free stack at least 156 bytes (172 before).
As one of 8 poly voices (14 bytes per frame) lead_dac and kettle miss nothing, moog_bass 18–372 halves in 10 s. A fully
decoded byte still costs 100–125 cycles, a foreign packet 300–450.

*[2026-10-20]* **Render rewrite.** Instruction costs measured on the V006 from RAM: ALU and `mul` 1 cycle, `mulh(u)`
1–1.25, `lw` 2, `sw` 3, a taken branch 3. The oscillators now render together in runs between their polyBLEP regions
(there a saw is `(ph >> 16) l`, a pulse a constant): one store per sample instead of a load and a store per
oscillator, the run loops and the modal free-ringing loop in assembly (the compiler reloaded values from the stack
with RV32E's 16 registers); the error feedback keeps the error + ½ code, so one compare replaces the four clamps; the
modal resonators are interleaved with alternating outputs (one store instead of two); the samples within one step of
a wrap take the full polyBLEP (in RAM). The CV dithering moved from the 46.875 kHz TIM1 interrupt to a DMA burst at
each TIM1 update (DMA1 ch2), the render interrupt lost its three software divisions, the COUNTERS reply its stack
scan (the main loop keeps the value). Output bit-exact with the old renderer (firmware/voice/test/render_test.py, and
the card's render-check hashes). Render cycles per buffer half (console `bench`, interrupts off), step by step:

| Step | moog_bass (3 osc), note 48 | lead_dac (2 osc), note 48 | kettle (modal, 2 banks) |
|---|---|---|---|
| before | 44.2 k (at note 84 too) | 37.1 k | 38.2 k |
| runs between the polyBLEP regions, error feedback with one compare, block buffer off the stack | 16.8 k | 13.0 k | 35.5 k |
| run loops unrolled by four | 14.3 k | 11.1 k | |
| `-O2` for the render functions (cold paths out of line) | 12.8 k | 9.0 k | |
| oscillators fused, one store per sample, run loops in assembly | 8.3 k | 7.1 k | |
| edge samples in RAM, runs end exactly at a region | 8.0–9.0 k (note 84: 11.9 k) | 6.7–7.5 k (9.6 k) | |
| resonators interleaved, alternating outputs; interpolation by two | | | 22.9 k |
| free ringing in assembly, `-Os` | | | 20.7 k |

Without a note the oscillator render takes 1.8 k (16.3 k). Not in the table: the TIM1 interrupt took about 7 k cycles
of every half (64 interrupts of about 110 cycles, from its instructions and the costs above), the divisions about
1.5 k. Under load (10 s each, the card holds a note; missed halves, fill_max in cycles including the preempting ticks,
slack_min in periods; before → after):

| Patch | No traffic | Foreign traffic (71 B/frame) | One of 8 poly voices | Stress 20 s (`--progs 17`) |
|---|---|---|---|---|
| lead_dac (2 osc) | 0, 59.9 k, 22 → 0, 15.7–20.7 k, 175–195 | 0, 65.5 k, 12 → 0, 18.4–24.1 k, 162–184 | 0, 58.6 k, 23 → 0, 19.8–23.7 k, 164–179 | |
| kettle (modal) | 0, 42.8 k, 85 → 0, 23.1–26.0 k, 150–162 | 0, 46.2 k, 71 → 0, 23.4–27.4 k, 145–161 | 1, 64.7 k, 16 → 0, 35.3–39.2 k, 99–114 | |
| moog_bass (3 osc) | 1, 65.5 k, 4 → 0, 18.4–23.5 k, 164–184 | 1 796, 65.5 k, 1 → 0, 24.0–26.2 k, 154–162 | 33, 65.5 k, 1 → 0, 21.7–25.3 k, 157–171 | 188, 65.5 k, 1 → 0, 22.8–25.3 k, 157–167 |

(after: three runs.) Free stack 156 → 656–680 bytes under all of it (about 340 with the console): the console's command function is no
longer inlined into `main`, the oscillators' block buffer and the mallet table share `hw_scratch` after the DAC ring,
the TIM1 interrupt's code left RAM, and `hw_scratch` shrank from 3584 to 2560 bytes (console captures: 1280 samples)
to make room for the 2.3 KB of render code in RAM. A three-oscillator mode restricted to one waveform would not pay:
three saws take 12.1 k per half on the general path (a dedicated loop about 8 k), three pulses 7.1 k (15.3 k at note 84,
two edges each), the existing three-oscillator presets (2 saws and a pulse an octave down) 8–9 k, and all of them
(programs 17, 18, 19, 24) would change sound.

**Latency** (scope, the SYNC edge of the execution frame to the note on PC2, 10 notes):

| Load | Mean | Spread |
|---|---|---|
| none (5 notes) | 4.0088 ms | 4.8 µs |
| 7 parts, controllers every 3 frames (72 bytes per frame), the card's NOTE_ON alone | 4.91 ms: 4, 5 or 6 ms | 2.0 ms |
| the same, `L` = 3 | 4.41 ms: 4 or 5 ms | 1.0 ms |
| the same, per-voice records (29 bytes per frame) | 4.0097 ms | 5.4 µs |
| the same, V_PRIO | 4.0096 ms | 4.6 µs |
| the card's note in a chord of 8 (one command), the part's controllers every 3 frames | 4.0078 ms | 6.7 µs |

On time, the latency does not depend on the load (`D` frames and one or two carrier periods); a late event is late by
whole frames.

**Implemented** (both sides keep the old behaviour as an option):

- Card: foreign packets are dropped at their `dst` byte, before the CRC, and skipped to the next 0x00 (`BUS_EARLY`,
  default; a damaged `dst` loses the packet, as a CRC error would); the COBS decoder runs over the RX ring in place,
  its state in registers (87 bytes: 11.1 k → 5.2 k cycles); per-voice records (5.1); the COUNTERS extension (5.2).
- Controller: per-voice records (`V` flag 8: the NOTE_ON / NOTE_OFF / CTRL / PARAM of one command, the VOICE_STATE of
  all voices); two queues (`V` flag 16, V_PRIO): CTRL and PARAM wait behind notes, the refreshes go between them and
  no longer starve; the lateness of every timed packet is counted (`L`). Two bench faults found on the way: a
  command's events were encoded with interrupts off, which delayed the frame interrupt so that its last bytes missed
  the next edge (a lost frame, events late by 2–3 frames); they are now staged and published in one step. The PC
  port receives by DMA (the USART holds one byte; the generator runs while the main loop waits).

**2 Mbaud** (`make BUS_BAUD=2000000` on both: dividers 24 = 1.5 on the V006, 36 on the V203, both exact): works on the
bench wiring, all 17 tests, no CRC or UART errors. Bursts up to 190 bytes fit one frame (a legato chord change is on
time), the bus saturates at 183 bytes per frame. But a burst now reaches the cards in one tick (193 bytes: parser
13.3 k, tick 17 k cycles), and lead_dac misses 90–440 halves per 5 s even at a 35-byte average (none at 1 Mbaud).

**Recommendations:**

1. Notes ahead of controllers (V_PRIO) in the controller: no protocol change, notes on time under any controller
   load. Controllers may then be late; coalescing (a queued CTRL / PARAM of the same voice and ID takes the new value
   instead of a new packet) would also bound the backlog.
2. Per-voice records for chords (NOTE_ON, NOTE_OFF) and the VOICE_STATE refresh: half the bytes, a legato chord
   change in one frame. For controllers on several parts they save bus time, but every card decodes the whole packet
   (11.6 k cycles at 91 bytes against 5.8 k with early discard), and a two-oscillator card misses a few halves (2–20
   per 5–10 s run) where per-voice packets miss none.
3. `L` = 3 where per-voice records are not used for legato chords and multi-part controllers: one frame of slack,
   7–8 ms latency.
4. 1 Mbaud until the cards parse outside the tick (8, open points).
5. Three-oscillator patches stay outside the CPU budget with the bus (4–11 periods of slack without traffic): a
   cheaper render or two oscillators per voice (9.3). *[2026-10-20]* Done: with the render rewrite they keep at
   least 154 periods of slack under all the load above (end of 9.5).
6. The refresh rates can stay: 1.5 bytes per frame for 8 voices; a whole patch per part and second as PATCH_DATA about
   1.5 more.
