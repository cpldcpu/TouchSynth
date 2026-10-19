# TouchSynth Poly: MIDI implementation and patches

Status: proposal 0.1 (2026-10-18). Requirements: [design.md](design.md) (F2, F3, F6); voice bus: [bus.md](bus.md)
(the patch parameter IDs below are its PARAM / PATCH_DATA IDs).

## 1. Model

```
 MIDI in (USB device, USB host)        controller (CH32V203)                            voice cards
 ───────────────────────────────►  parts 1..8: channel, key range, voices,  ──bus──►  4 patch slots each,
 CDC (editor, librarian)             mode, patch                                       one active
                                     patch library (flash), working copies (SRAM)
```

- **Patch:** a sound, 64 parameters of 16 bits plus a name (16 characters): 144 bytes. Patches are data. The
  firmware on the cards defines what the parameters do; a patch never carries code or samples.
- **Part:** one instrument of the multitimbral setup: MIDI channel, key range, the voices (card slots) it may use,
  the voice mode, the patch, part volume and transpose. Up to 8 parts (no more voices than that).
- **Setup:** the 8 parts plus global settings (tuning, MIDI clock); the state of the instrument, stored like
  patches.
- **Where things live:** the controller holds the patch library (64 programs, about 9 KB in the V203's flash) and
  the setups; working copies of the active patches and parts are in its SRAM. The cards hold up to 4 patches each
  (patch slots, 4 × 128 bytes) and play the active one. Nothing is stored on the cards except their calibration.

## 2. Parts and voice assignment

| Part setting | Values |
|---|---|
| Channel | 1–16, or off |
| Key range | low and high note (splits) |
| Voices | a mask of card slots this part may use (layers: two parts on one channel) |
| Mode | poly, mono (last note), legato (mono, no retrigger, glide on overlap), unison (all voices in the mask on one note, detuned by the patch's UNISON_SPREAD), kit (section 2.1) |
| Patch | program number 1–64 (program change on the part's channel selects it) |
| Volume, transpose | 0–127; ±48 semitones |

Allocation: within its mask a part takes a free voice, otherwise steals the oldest released one, then the oldest
held one. Masks may overlap. Then the controller sends PATCH_SELECT in the same frame as the NOTE_ON when a voice
changes parts; when the patch is not in one of the card's 4 slots it first loads it with PATCH_DATA (2–3 frames),
and the note starts that much later. Disjoint masks avoid that; the default setup uses them.

Stereo position: each card pans its voice itself (S13, spec 3.1: current steering after the VCA, set by PWM), so a
part or a single voice can sit anywhere in the stereo field independent of its slot; the backplane mixer has two
buses and no fixed pan (spec 4).

**Default setup:** part 1 on channel 1, all 8 voices, poly, program 1; parts 2–8 off.

### 2.1 Kit mode (drums)

A kit part maps notes to (patch, pitch): e.g. GM drum notes 36 kick, 38 snare, 42 / 46 hats, 41–50 toms. Up to 4
different patches per kit (the card's patch slots), loaded into every card of the part's mask at setup time, so a
kit never waits for PATCH_DATA. Each note becomes PATCH_SELECT + NOTE_ON on the next free voice of the mask.

## 3. MIDI implementation

Received on each part's channel:

| Message | Function |
|---|---|
| Note on / off, velocity | notes; velocity to amplitude and filter envelope (patch: AENV_VEL, FENV_VEL) |
| Pitch bend | ± BEND_RANGE semitones (patch) |
| Channel pressure | AT_CUTOFF, AT_VIBRATO (patch) |
| Program change | the part's patch (1–64) |
| CC 1 mod wheel | adds vibrato (WHEEL_VIBRATO) and LFO depth to cutoff (WHEEL_CUTOFF) |
| CC 5 / 65 | glide time / glide on-off |
| CC 7 / 11 | part volume / expression |
| CC 64 | sustain (handled by the controller: note-offs are held back) |
| CC 71 / 74 | resonance / cutoff (relative to the patch, ±) |
| CC 72 / 73 / 75 | amplitude release / attack / decay (relative) |
| CC 76 / 77 / 78 | LFO rate / vibrato depth / LFO delay |
| CC 99 / 98, 6 / 38 | NRPN: any patch parameter by ID (MSB 0, LSB = ID), 14-bit data entry over the parameter's full range |
| CC 120 / 121 / 123 | all sound off / reset controllers / all notes off |
| Poly pressure | ignored (later: per-voice modulation, MPE) |

System: MIDI clock and start / stop (tempo for LFOs synchronised to tempo); SysEx with the non-commercial
manufacturer ID 0x7D for patch and setup dumps (DAW librarians; the same operations as over CDC).

CC changes of a parameter are relative to the patch value and are not stored in the patch; NRPN changes edit the
working copy (stored by "save" over CDC or SysEx).

## 4. Patch parameters

Values are signed 16-bit in the units given. A 7-bit CC maps 0–127 linearly onto the range; NRPN carries the
full range. Time indices (0–127) select from an exponential table, about 1 ms to 10 s (the rev 0.1 `time_coef`
law). IDs 0–63 are the patch; IDs 64–79 are per-voice settings the controller sends with PARAM (not stored in the
patch).

| ID | Name | Range, unit | Notes |
|---|---|---|---|
| 0, 6, 12 | OSCn_WAVE | 0 off, 1 saw, 2 pulse | 3 triangle, 4 sine, 5+ wavetables: later |
| 1, 7, 13 | OSCn_LEVEL | 0–127 | |
| 2, 8, 14 | OSCn_COARSE | −36…+36 semitones | a sub-oscillator is −12 |
| 3, 9, 15 | OSCn_FINE | −100…+100 cent | |
| 4, 10, 16 | OSCn_PW | 0–127 (64 = 50 %) | pulse only |
| 5, 11, 17 | OSCn_PWM | 0–127 | LFO depth on the pulse width |
| 18 | NOISE_LEVEL | 0–127 | white noise (LFSR in the DSP) |
| 19 | (reserved) | | oscillator sync, later |
| 20 | GLIDE_TIME | time index | |
| 21 | GLIDE_MODE | 0 off, 1 always, 2 legato only | |
| 22 | PENV_AMT | −48…+48 semitones | pitch envelope at the attack (drums) |
| 23 | PENV_DECAY | time index | |
| 24 | LFO_RATE | 0–127 (0.05–50 Hz), or a tempo division with LFO_SYNC 3 | |
| 25 | LFO_WAVE | 0 triangle, 1 square, 2 saw up, 3 saw down, 4 sample & hold | |
| 26 | LFO_SYNC | 0 free (per voice), 1 key (restart at note on), 2 global (frame-locked, all voices in phase), 3 tempo | global and tempo use the bus frame counter (bus.md 3) |
| 27 | LFO_DELAY | time index | fade-in after note on |
| 28 | LFO_PITCH | 0–1200 cent | vibrato |
| 29 | LFO_CUTOFF | −2048…+2048 (1/256 octave) | |
| 30 | LFO_AMP | 0–127 | tremolo |
| 31 | (reserved) | | |
| 32 | CUTOFF | 0–2560 (1/256 octave above 20 Hz) | |
| 33 | RESONANCE | 0–255 | 200 = self-oscillation threshold (calibrated per card) |
| 34 | FENV_AMT | −2560…+2560 (1/256 octave) | |
| 35 | KEYTRACK | 0–256 (256 = 1 octave per octave) | |
| 36 | FENV_VEL | 0–127 | velocity on the filter envelope amount |
| 37 | AT_CUTOFF | −2048…+2048 (1/256 octave) | channel pressure |
| 38–41 | FENV_A, _D, _S, _R | time index; S 0–127 | filter envelope |
| 42–45 | AENV_A, _D, _S, _R | time index; S 0–127 | amplitude envelope |
| 46 | AENV_VEL | 0–127 | velocity on the amplitude |
| 47 | VOLUME | 0–127 | |
| 48 | ENGINE | 0 subtractive (oscillators), 1 modal (percussion) | |
| 49 | MODAL_MODEL | index into the card's mode tables: 0 kettle, 1 tom, 2 marimba, 3 bell, ... | |
| 50 | MALLET | 0–127 (0.1 ms steps) | strike width: hardness |
| 51 | MODAL_DECAY | −64…+63 | scales the modes' decay |
| 52 | MODAL_RINGS | 1–2 | simultaneous strikes per card |
| 53 | MODAL_NOISE | 0–127 | noise burst at the strike (snares) |
| 54 | BEND_RANGE | 0–24 semitones | |
| 55 | UNISON_SPREAD | 0–100 cent | detune across the voices of a unison part |
| 56 | WHEEL_VIBRATO | 0–1200 cent | |
| 57 | WHEEL_CUTOFF | 0–2048 (1/256 octave) | LFO depth on the cutoff added by the wheel |
| 58 | AT_VIBRATO | 0–1200 cent | |
| 59–63 | (reserved) | | |
| 64 | V_PART_VOLUME | 0–127 | part volume × expression |
| 65 | V_UNISON_INDEX | −4…+4 | this voice's place in the unison spread |
| 66 | V_CC_OFFSETS | packed | the relative CC offsets (cutoff, resonance, envelope times), to be detailed |

Mapping to the existing voice firmware: most parameters are fields of rev 0.1's `patch_t` (cutoff, resonance,
envelopes, glide, LFO, pitch envelope, keytrack) and of the DSP patch (oscillators, modal modes, mallet). New: the
per-oscillator coarse / fine / PWM, noise in the DSP, LFO waves and sync, velocity and pressure routing, the modal
model index.

## 5. Program set (first version)

| # | Name | From |
|---|---|---|
| 1 | Moog Lead | moog_lead (3 oscillators) |
| 2 | Moog Bass | moog_bass |
| 3 | Open Saws | moog_open |
| 4 | Acid Bass | acid_dac |
| 5 | Lead | lead_dac (saw + sub pulse) |
| 6 | Brass | rev 0.1 brass, ported |
| 7 | Strings | rev 0.1 strings: detuned saws, slow attack |
| 8 | PWM Pad | new: pulse with LFO on the width |
| 9 | Organ | rev 0.1 organ: pulses at 0 / +12 / +19 |
| 10 | Pedal Bass | rev 0.1 pedal |
| 11 | Wind | rev 0.1 wind: noise through the resonant filter |
| 12 | Theremin | rev 0.1 theremin: glide, vibrato |
| 13 | Arp Pluck | rev 0.1 arp |
| 14 | Sweep | rev 0.1 sweep (filter FX) |
| 15 | Unison Lead | new: saws, unison mode |
| 16 | Kettle | kettle (modal) |
| 17 | Tom | new: modal |
| 18 | Marimba | new: modal |
| 19 | Bell | new: modal, inharmonic |
| 20 | Kick | rev 0.1 kick: pitch envelope on a sine-like low pass |
| 21 | Snare | rev 0.1 snare: noise + modal body |
| 22 | Hat | rev 0.1 hat: short noise (the ladder is a low-pass, so hats stay darker than a high-passed hat) |
| 23 | Drum Kit | kit part template: Kick, Snare, Hat, Tom |

Programs 24–64 empty. The rev 0.1 presets that used the analog DCO (its saw, pulse, sub and noise outputs) are
ported by expressing those sources as DAC oscillators and noise.

## 6. CDC (configuration over USB serial)

Text commands, one per line, in the style of the board 1 console: list / get / set / save patches and setups,
part settings, card status (bus statistics, calibration, clock error), calibration start, voice firmware update
(an image streamed over CDC, programmed through each slot's SWIO line), and a bridge to one card's console.
Command set to be detailed with the controller firmware.

## 7. Open points

- MPE / polyphonic aftertouch per voice (the bus already addresses single voices).
- Wavetables (OSCn_WAVE 5+): per-octave band-limited single cycles in the cards' flash, loaded over the bus.
- Tempo-synchronised envelopes and an arpeggiator on the controller.
- The relative-CC bookkeeping (ID 66) and how CC offsets interact with patch edits.
