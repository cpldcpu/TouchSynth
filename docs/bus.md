# TouchSynth Poly: voice bus protocol

Status: proposal 0.1 (2026-10-18). Physical layer and the reasons for UART + SYNC: [spec.md](spec.md) section 5;
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
| NRST, SWIO | per slot, controller GPIOs | reset / enumeration, programming (spec 4) |

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
| 1024 periods (5.5 ms, now) | 10.9 ms | 12 frames | 4 KB |
| 256 periods (1.37 ms, proposed) | 2.7 ms | 4 frames | 1 KB |

Proposal: `H` = 256, `D` = 4. It frees 3 KB of RAM (with once-per-period loading the ring is only 0.5 KB, 1.5 KB
for dual PWM; spec 3.2) and costs only the per-half overhead, which is small because the renderer works in
32-period blocks anyway (to measure). A 1.37 ms half must never wait for the main loop: on board 1 the main loop
stalls for 4–10 ms (console, UI), and short halves underran there. The renderer therefore runs in the DMA
half-transfer interrupt at the lowest priority, the SYNC tick above it, the DAC DMA itself needs no CPU. If `V_n` is
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
error. Decoded content:

```
controller → cards:  dst  type  [frame]  payload...  crc8
card → controller:   src  type            payload...  crc8
```

| Field | Meaning |
|---|---|
| `dst` | voice bitmask: bit k = the card with address k (0…7); 0xFF = all; 0x00 = unaddressed cards (enumeration) |
| `src` | the replying card's address |
| `type` | message type; unknown types are ignored (forward compatibility) |
| `frame` | timed messages only: low 8 bits of the execution frame, read relative to the card's frame counter (−128…+127). Late (negative): executed at the next tick and counted; more than 32 frames ahead: dropped |
| `crc8` | CRC-8 (polynomial 0x07) over the decoded bytes; packets with a bad CRC are dropped and counted |

Multi-byte values are little-endian. Pitch is in 1/256 semitone (MIDI note × 256 + bend); the card's oscillator
tables (1/16 semitone) take the top bits.

## 5. Messages

### 5.1 Controller → cards

| Type | Name | Timed | Payload | Use |
|---|---|---|---|---|
| 0x01 | FRAME | | frame u16 | first packet after every SYNC edge; cards check their frame counter (a mismatch resynchronises it and is counted) |
| 0x02 | CONFIG | | `D` u8, `L` u8, tuning i16 (1/256 semitone), flags u8 | system settings; sent after enumeration and on change |
| 0x03 | ASSIGN | | address u8 | to `dst` 0x00: the one released, unaddressed card takes the address and answers HELLO |
| 0x10 | NOTE_ON | yes | pitch u16, velocity u8, flags u8 | flags: retrigger envelopes, reset oscillator phase, legato (glide from the current pitch) |
| 0x11 | NOTE_OFF | yes | velocity u8 | release |
| 0x12 | PITCH | yes | pitch u16 | new pitch of a sounding voice (glide target, per-voice bend) |
| 0x13 | VOICE_STATE | yes | gate u8, pitch u16 | refresh: "at this frame the voice is gated / not gated at this pitch"; the card corrects itself if it differs (repairs a lost NOTE_ON or NOTE_OFF) |
| 0x20 | CTRL | yes | id u8, value i16 | performance controls, usually to all: pitch bend, mod wheel, aftertouch, expression, tempo, LFO phase reset |
| 0x21 | PARAM | yes | id u8, value i16 | one patch parameter (live edit) |
| 0x22 | PATCH_DATA | | offset u8, count u8, values i16 × count | into the shadow patch; a whole patch spread over several frames |
| 0x23 | PATCH_COMMIT | yes | | shadow patch becomes active at this frame: a program change hits all addressed voices on the same tick |
| 0x30 | REQUEST | | what u8, arg u8 | to one card: STATUS, CAL_DATA (block `arg`), HELLO |
| 0x31 | CALIBRATE | yes | what u8 | loopback calibration (the voice mutes itself, answers STATUS "busy" until done) |

Unison: one NOTE_ON with several bits in `dst`; each card applies its own detune (patch parameter × its address).

### 5.2 Card → controller (only in reply)

| Type | Name | Payload |
|---|---|---|
| 0x80 | HELLO | chip unique ID (from the V006's electronic signature), firmware version u16, capabilities u8 (dual-PWM fitted, ...) |
| 0x81 | STATUS | flags u8 (synced, calibrated, busy, standalone), HSITRIM u8, clock error i16 (ppm, from `P̄`), counters u8 each: CRC errors, late events, frame slips, late ticks, DAC underruns; CPU load u8 (%) |
| 0x82 | CAL_DATA | block u8, calibration values |

Only one REQUEST or ASSIGN is outstanding at a time; the card answers as soon as it has parsed it (within 2 frames),
the controller times out after 5 frames. The return line needs no time slots: it is separate from the broadcast line
and only one card is ever asked.

The chip ID lets the controller keep each card's calibration and identity even if cards change slots.

### 5.3 Bandwidth

1 Mbaud 8N1 = 100 bytes per frame. Encoded sizes (with COBS overhead and delimiter): FRAME 7 bytes, NOTE_ON 10,
CTRL 9, PATCH_DATA 7 + 2 per value. An 8-voice chord with FRAME is 87 bytes: one frame. A 64-parameter program
change is about 150 bytes over 2–3 frames before its COMMIT. Idle frames carry the refreshes: VOICE_STATE for one
voice every 6 ms (each voice every 50 ms) and a slow round-robin resend of the active patch, so a lost PARAM also
heals.

## 6. Sequences

**Power-up and enumeration.** The controller starts SYNC and FRAME, holds all NRST lines low and then, slot by slot:

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
a single missed edge does not glitch, mutes its VCA after 10 ms without SYNC and re-locks when SYNC returns. A
controller reset pulls all NRST lines anyway.

**Calibration.** CALIBRATE (timed) → the card mutes and runs its loopback routine → the controller polls STATUS
until "busy" clears → reads CAL_DATA blocks and stores them by chip ID. The calibration itself stays on the card
(it needs the card's ADC and DAC); the controller only keeps a copy.

**Firmware update** goes over SWIO, not over the bus (spec 4).

## 7. Card resources

| Item | Size |
|---|---|
| RX DMA ring (USART1 RX, ch5) | 256 bytes (2.5 frames at full load); parsed in the SYNC tick, at most 100 bytes per tick (a few % of the CPU) |
| Event queue (timed events waiting for their frame) | 16 × 8 bytes |
| Voice state queue `V_n` and CV delay line | `D` + 1 entries × about 24 bytes |
| Shadow patch | the patch size (about 128 bytes) |

## 8. Open points

- Parameter and controller IDs (the patch layout of the new voice firmware).
- Measure the per-half overhead with `H` = 256 and the tick's run time with parsing (board 1).
- Whether the renderer's block split at `b_n` is cheap enough; otherwise the 32-period block boundary (171 µs)
  is the alignment, still far below audibility for chords.
- The V006's unique ID length and location (electronic signature registers).
- Whether 2 Mbaud on the broadcast line is needed (no, at the sizes above).
