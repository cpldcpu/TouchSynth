# TouchSynth firmware 0.1

Firmware for the TouchSynth board (CH32V003, CH32V002 or CH32V006 in TSSOP-20), built on
[ch32fun](../ch32fun). Runs on board 1 (CH32V006); bring-up and test results are in the design report, section 10.

## Build and flash (WSL)

```
make                          # CH32V003 (default)
make TARGET_MCU=CH32V002      # or CH32V006
make flash                    # WCH-LinkE via minichlink
python3 check_pins.py         # firmware pins vs. schematic and chip remap tables
python3 gen_tables.py         # regenerate tables.h after new simulation results / tunes
```

| Target   | Flash            | Static RAM      | Tunes |
|----------|------------------|-----------------|-------|
| CH32V003 | 13.8 KB / 16 KB  | 0.7 KB / 2 KB   | 3 demos |
| CH32V002 | 13.6 KB / 16 KB  | 1.4 KB / 4 KB   | 3 demos |
| CH32V006 | 37.7 KB / 62 KB  | 4.4 KB / 8 KB   | 3 demos + 30 multitrack parts |

The multitrack parts (`sim/behav/pieces.py`, tunes 3–32 on the V006) are played one per take for the
recordings in `docs/audio/`; see `tools/record_parts.sh`.

## Structure

| File | Content |
|---|---|
| `board.h` | pin map (from `hw/design.py`), timer remap codes per chip family |
| `hw.c` | TIM1 CV PWM with 2-bit dithering and noise LFSR (46.875 kHz interrupt), TIM2 DCO reset / pulse / sub-oscillator, 74HC595 chain, CD4051 touch scan, loopback ADC capture, MIDI UART |
| `synth.c` | voice engine at 1 kHz (SysTick): glide, LFO, envelopes, CV laws, percussion pitch envelope and wave switch, tune player with control steps (cutoff / resonance ramps) |
| `ui.c` | touch keys, SHIFT / − / + editing, LED display |
| `console.c` | test console over SWIO (`minichlink -T`) |
| `tables.h` | **generated** by `gen_tables.py` from `docs/results/*.csv`, `sim/behav/tunes.py` and `pieces.py` |

The engine mirrors the firmware layer of the behavioural model (`sim/behav/behav.py`), so the audio
previews in `docs/audio/features/` are what the board should sound like.

### Timer remaps

The pin assignment works on both families, but the remap *codes* differ:

| | CH32V003 | CH32V002 / V006 |
|---|---|---|
| TIM1 CH1–CH4 → PC6, PC7, PC0, PD3 | `TIM1_REMAP` = 01 | `TIM1_RM` = 0010 |
| TIM2 CH1, CH2 → PC5, PC2 | `TIM2_REMAP` = 01 | `TIM2_RM` = 010 |

The V00x values come from the CH32V002 datasheet (table 2-1) and are identical in the CH32V006 datasheet
(V2.0, table 2-1-1, TSSOP-20 = V006F8P7; reset pin PD7, PA4 bonded to PD7 and never used). The complementary outputs that the same remaps put on
PC3, PC4 and PD1 (SWIO!) are never enabled.

## Playing

| Action | Effect |
|---|---|
| keys C … C' | play (C = C3, shifted by the octave setting) |
| − / + | octave −2 … +2, or the selected parameter 0 … 15 (LEDs show a bar) |
| SHIFT + key C … B | select a parameter: C wave, C# pulse width, D cutoff, D# resonance, E env amount, F filter decay, F# key tracking, G attack, G# decay/release, A sustain, A# glide, B vibrato |
| SHIFT tapped alone | back to octave mode |
| SHIFT + − / + | previous / next preset (16: init, acid, arp, lead, kick, snare, hat, sweep, brass, timpani, organ, pedal, strings, wind, seq, theremin) |
| SHIFT + C' | play the next demo tune (acid, prelude, ode); any key stops it |

Wave (parameter C) is a bit mask: 1 saw, 2 pulse, 4 sub, 8 noise. Resonance 13 is about the self-oscillation
threshold. MIDI in (if the parts are fitted): note on/off on any channel, velocity ≥ 100 = accent.

Keep hands off the keys for the first second after power-up: the touch baselines are measured then.

## Test console (`minichlink -T`)

`id`, `status`, `note <midi>`, `off`, `wave <mask> [pw]`, `preset <i>`, `tune <i>`, `param <k> <v>`,
`cv <amp|cut|res|vca> <code>` (manual mode), `dco <midi>` (manual mode), `auto`, `trim <0..255>`,
`leds <hex>` / `leds auto`, `touch`, `recal` (re-measure the touch baselines), `keys <0|1>` (disable the keys
for unattended recordings), `cap <n> [us]` (loopback capture, hex), `capcv <ch> <code> <n> [us]` (CV step and
capture), `adc <ch>`, `latch <0|1>` (diagnostics), `wait <ms>`. See the header of `console.c` and
`docs/verification_plan.md`. `tools/synthtest.py` drives the console from a script, `tools/hwtest.py` runs the
functional tests through it.
