# Voice firmware (from TouchSynth firmware 0.1)

Firmware of the TouchSynth Poly voice card (CH32V006F8P7, `make BOARD=card`): the voice bus receiver, the voice
engine with its control tick on the bus SYNC, the CV PWM outputs and the digital oscillators on the 187.5 kHz PWM DAC
(`dsp.c`). The same sources still build for board 1 (TouchSynth rev 0.1 with a CH32V006, the default `BOARD`), which
keeps its MIDI input and the analog DCO; the rev 0.1 touch UI is gone. CV calibration is still rev 0.1's measured
data until the first card is measured.

## Voice bus (card build)

`make BOARD=card` builds the voice card's receiver of the voice bus ([docs/bus.md](../../docs/bus.md); `bus.c`). On
the bench (V203 development board as controller, `../bench_ctrl`) build with `make BOARD=card BUS_TX_PP=1`: the bench
return line has no pull-up, so the card drives PD5 push-pull while its own reply goes out (default: open drain).
*[2026-10-19]* `BUS_EARLY=0` decodes and CRC-checks foreign packets before dropping them (default: dropped at their
`dst` byte); `BUS_BAUD=2000000` runs the bus at 2 Mbaud (the bench controller must match: `make BUS_BAUD=2000000` in
`../bench_ctrl`). Load test with 8 voices (7 virtual): `tools/bustest.py load`, results in bus.md 9.5.

| Implemented | |
|---|---|
| Time base | the SYNC edge (PD4, EXTI) is the control tick; SysTick bridges missing edges (counted), the VCA mutes after 10 ms without SYNC and the card relocks; edges less than 3/4 frame after the last are ignored (glitches); no SYNC since reset: standalone on SysTick |
| Start-up | 100 SYNC periods measure the HSI, HSITRIM is corrected (up to 4 steps), then the receiver starts at the next 0x00 |
| Receiver | USART1 1 Mbaud, RX DMA ring (256 bytes), parsed in the tick (only the bytes that arrived before it): COBS, CRC-8, voice bitmask, 16 timed events queued by frame (late: run at once, > 32 ahead: dropped). *[2026-10-19]* The decoder runs over the ring in place; foreign packets are dropped at their `dst` byte and skipped to the next 0x00; per-voice records (type \| 0x40) give the card its own record |
| Messages | FRAME, CONFIG (`D`, tuning), ASSIGN, REQUEST (STATUS, HELLO, COUNTERS), NOTE_ON (flags: retrigger, phase reset, legato), NOTE_OFF, PITCH, VOICE_STATE (repairs), CTRL (bend, wheel, expression, LFO reset), PARAM (IDs mapped onto `patch_t`), PATCH_SELECT, PATCH_PRESET (interim: a firmware preset into one of 4 slots). Not yet: PATCH_DATA, CALIBRATE, CAL_DATA |
| Presentation delay | CV delay line of `D` ticks (`hw_cv_commit`); the DAC voice state `V_n` is queued with its SysTick time and the renderer switches at that carrier period (`dsp_commit`, `dsp_fill`); modal strikes computed in the tick in fixed point; pitch lock of the oscillators to the SYNC period |
| Replies | HELLO (64-bit chip ID, firmware version, capabilities), STATUS, COUNTERS (all counters, tick and render maxima, stack, voice state) by TX DMA on PD5 |

The console's `bus` command prints the bus state and counters (the console connection resets the card).
`tools/bustest.py` tests all of it on the bench (docs/bus.md section 9). Board 1 builds keep the MIDI input at
31250 Bd and have no presentation delay. The modal strike and the mallet table are fixed point now (they run in the
control tick; soft float took about 60 k cycles per strike), and the mallet table is Q16: in Q20 the taps of mallets
shorter than 32 samples overflowed 16 bit (the kettle, 16 samples, lost its middle taps), on board 1 as well. With a
DAC patch the carrier now runs from the patch select on, not only from the first note.

## Build and flash (WSL)

```
make BOARD=card BUS_TX_PP=1   # voice card on the bench (V203 controller, ../bench_ctrl); BUS_TX_PP: see above
make BOARD=card               # voice card on the backplane (return line open drain)
make                          # board 1 (CH32V006, TouchSynth rev 0.1 hardware)
python3 check_pins.py         # firmware pins vs. schematic and chip remap tables
python3 gen_tables.py         # regenerate tables.h after new simulation results / tunes
```

Flash a card through the bench controller's SWIO bridge: `minichlink -C ardulink -c <port> -w touchsynth.bin flash
-b`; board 1 directly with a WCH-LinkE (`make flash`). Card build: about 54 KB of 62 KB flash, 7.3 KB of 8 KB static
RAM; the stack keeps about 150-200 bytes free under bus load (bus.md 9.5): watch it when adding RAM or deep calls.

## Structure

| File | Content |
|---|---|
| `board.h` | pin maps (card: docs/spec.md 3.2; board 1: `hw/design.py` on master), timer remap codes per chip family |
| `touchsynth.c` | main loop, control tick (SYNC edge on the card, SysTick on board 1), interrupt levels |
| `hw.c` | TIM1 CV PWM with 2-bit dithering and noise LFSR (46.875 kHz interrupt), the PWM DAC (TIM2, DMA1 ch1, render interrupt), SYNC input and HSI trim, bus UART with RX / TX DMA (card) or MIDI UART (board 1), board 1's DCO, 74HC595 chain and loopback ADC |
| `bus.c` | card: voice bus receiver, timed events, presentation delay, replies (docs/bus.md) |
| `synth.c` | voice engine at 1 kHz: glide, LFO, envelopes, CV laws, percussion pitch envelope and wave switch, presets and patch slots, tune player (board 1) |
| `dsp.c` | digital voices on the PWM DAC (up to 3 oscillators, noise, modal drums in fixed point; mirrors `sim/behav/dsp.py`) |
| `console.c` | test console over SWIO (`minichlink -T`, on the bench through the bridge) |
| `tables.h` | **generated** by `gen_tables.py` from `docs/results/*.csv`, `sim/behav/tunes.py` and `pieces.py` |

The engine mirrors the firmware layer of the behavioural model (`sim/behav/behav.py`), so the audio previews in
`docs/audio/features/` are what a voice should sound like.

### DAC mode

A preset with a `dsp` entry turns PC2 into a PWM DAC: TIM2 counts up and down at 187.5 kHz (`ARR` 128, centred
pulses), its CH3 compare requests DMA1 channel 1, which loads the duty from a ring of two 256-period halves (format 4:
one byte per period; the dual-PWM format 3 with the low byte on PC1 as an option, docs/spec.md 3.5). The DMA's
half / full interrupt renders the half that has just played (`dsp_fill`) at the lowest interrupt level, so the
control tick, the CV PWM and the UART preempt it. A render that ends late counts as an underrun (console `dac`,
bus COUNTERS). CPU limits per patch type: docs/bus.md 9.5.

### Timer remaps

The pin assignment works on both families, but the remap *codes* differ:

| | CH32V003 | CH32V002 / V006 |
|---|---|---|
| TIM1 CH1–CH4 → PC6, PC7, PC0, PD3 | `TIM1_REMAP` = 01 | `TIM1_RM` = 0010 |
| TIM2 CH1, CH2 → PC5, PC2 | `TIM2_REMAP` = 01 | `TIM2_RM` = 010 |

The V00x values come from the CH32V002 datasheet (table 2-1) and are identical in the CH32V006 datasheet
(V2.0, table 2-1-1, TSSOP-20 = V006F8P7; reset pin PD7, PA4 bonded to PD7 and never used). The complementary outputs
that the same remaps put on PC3, PC4 and PD1 (SWIO!) are never enabled.

## Playing

The card plays what the controller sends over the voice bus (notes, controllers, patch selection; docs/bus.md,
docs/midi.md); on the bench `tools/bustest.py` and the bench controller's PC commands drive it. Board 1 takes MIDI
note on / off and program change on any channel (velocity >= 100 = accent). Wave is a bit mask: 1 saw, 2 pulse,
4 sub, 8 noise; resonance 13 is about the self-oscillation threshold.

## Test console (`minichlink -T`)

`id`, `status`, `bus` (card), `sync` (SYNC timestamps), `hsi` (trim), `note <midi>`, `off`, `wave <mask> [pw]`,
`preset <i>`, `tune <i>`, `cv <amp|cut|res|vca> <code>` (manual mode), `dco <midi>` (manual mode), `auto`,
`trim <0..255>`, `leds <hex>`, `dac` (DAC state, DMA position, underruns, longest render), `bench`, `adc <ch>`,
`cap <n> [us]` (loopback capture), `capcv <ch> <code> <n> [us]`, `wait <ms>`, `latch <0|1>`, `drive <port><pin>
0|1|z`, `peek <hex address>`. See the header of `console.c`; `tools/synthtest.py` drives the console from a script.
