# TouchSynth — Verification & Validation Plan

Status: draft v0.1 (2026-09-26). Limits come from the ngspice results in [sim_report.md](sim_report.md)
(S1–S7); they are set with margin for component tolerances. Update the limits once the first board
has been characterised.

## 1. Strategy

| Level | What | How | Who |
|---|---|---|---|
| L0 Design verification | circuit meets spec in simulation | ngspice S1–S7 (`sim/`) | done before layout |
| L1 Assembly / bring-up | board is built right, rails and bias are sane | DMM on test points, current-limited supply | manual |
| L2 Functional verification | each block meets its sim-derived limits | test firmware + audio loopback ADC, driven over SWIO by `minichlink` | automated (Claude via minichlink) |
| L3 Calibration | per-board constants stored in flash | same firmware, calibration commands | automated |
| L4 Validation | it is a playable, good-sounding instrument | playing tests, listening, long-run stability | user |

## 2. Test infrastructure

### 2.1 Hardware provisions (must be in the schematic/layout)

- **Audio loopback** VCA output → 10 k / 30 k divider + 1 nF → **PD5 (ADC A5)**. Range 0.5…4.5 V for the full
  output swing (S6 checks this node stays inside 0…5 V).
- **Temperature sensor** MMBT3904 (diode-connected) thermally coupled to the expo pair → **PD4 (ADC A7)**.
- **Trim DAC** 3rd 74HC595 in the LED chain → 8-bit R-2R (100 k / 200 k) → VCA offset injection.
- **74HC595 LATCH on PD7**: NRST disabled in option bytes by the firmware on first boot (flashing via
  SWIO keeps working; recovery via minichlink power-cycle unlock if needed).
- **Test pads** (1 mm, bottom side, labelled): GND, V+, +5V, VREF, VBIAS, V25, VB0…VB4, TAIL, SAW, LPF,
  VCAOUT, RESOUT, XAMP, XCUT (bC), XRES, XVCA, VTRIM, TEMP.
- **SWIO header** 3 pads (GND, SWIO, +5V) for WCH-LinkE.

### 2.2 Test firmware (`firmware/synthtest/`, ch32fun)

A text command interface over the SWIO debug channel (`printf` / `handle_debug_input`, used with
`minichlink -T`). No UART or USB needed. Commands (all integers, 12-bit CV codes):

| Command | Action |
|---|---|
| `id` | chip type (V003/V002), firmware version, flash calibration block |
| `note <midi>` / `off` | start/stop the DCO at a MIDI note (exact TIM2 period) |
| `wave <saw> <pulse> <sub> <noise> [pw]` | enable waveforms (0/1), pulse width 0…1023 |
| `cv <amp\|cut\|res\|vca> <code>` | set a PWM CV directly (bypasses envelopes) |
| `trim <0..255>` | write the VCA trim DAC |
| `leds <hex16>` | set the 16 LEDs |
| `cap <n> <rate>` | capture n samples of the audio loopback (PD5) at a given rate, dump as hex |
| `temp` | read PD4 (oversampled), print mV and °C estimate |
| `touch [n]` | dump raw touch readings of all 16 pads (n samples each) |
| `selftest` | run T1…T12 below, print PASS/FAIL table |
| `cal <dco\|vcf\|vca\|touch>` / `calsave` | run a calibration and store constants in flash |

Host side: `tools/synthtest.py` (Windows Python) wraps `minichlink.exe -T` (prebuilt in
`firmware/ch32fun/minichlink/`, WinUSB driver on the WCH-LinkE interface 1), sends commands, parses the
dumps, computes FFTs and compares against the limits below. Results go to `docs/results/hw_<board>.csv`
so they can be plotted next to the simulation data.

## 3. L1 — Bring-up (MCU not fitted, then fitted)

Supply: lab supply 9.0 V, current limit 100 mA.

| # | Step | Expected (sim) | Limit |
|---|---|---|---|
| B1 | visual / continuity: no bridges on TSSOP-20, CD4051, 74HC595 | — | — |
| B2 | reverse polarity 9 V for 1 s | I < 1 mA | pass |
| B3 | input current, no MCU | ≈ 10 mA analog + 78L05 Iq (S3 op: 10 mA) | 5…25 mA |
| B4 | V+ at 9 V in | 8.6 V | 8.4…8.8 V |
| B5 | +5V | 5.0 V | 4.8…5.2 V |
| B6 | VREF | 4.50 V (1 k / 9.1 k) | 4.45…4.55 V |
| B7 | VB0…VB4 at V+ = 8.6 V | 2.40 / 3.40 / 4.40 / 5.40 / 6.40 V | ±3 % |
| B8 | TAIL (ladder emitters) | 1.86 V | 1.7…2.0 V |
| B9 | LPF (INA output, no signal) | 4.50 V | 4.3…4.7 V |
| B10 | VCAOUT | 4.50 V | 4.3…4.7 V |
| B11 | fit MCU, flash `synthtest`, `id` answers | — | — |
| B12 | input current with MCU, LEDs off | +5…8 mA | < 40 mA |

## 4. L2 — Functional tests (automated, `selftest`)

Default conditions: 9 V in, room temperature, CV codes from the calibration defaults.

| ID | Block | Procedure | Pass limit | Sim ref |
|---|---|---|---|---|
| T1 | LEDs / 595 chain | walking-one pattern, user confirms; trim DAC walk shifts VCAOUT DC (VCA open, no signal) monotonically | monotonic, > 20 mV span | — |
| T2 | Touch | 256 readings per pad, untouched: mean, σ; user touches each pad in turn | σ < 2 LSB (V003) / 6 LSB (V002); touch Δ > 10 σ | S5: Δ(5 pF) ≥ 14.8 / 57 LSB |
| T3 | Touch scan rate | time a full 16-pad scan | ≥ 200 Hz | S5: 1.4 kHz |
| T4 | DCO frequency | filter open, VCA open, `cap` + zero-crossing / FFT at C2, C4, C6 | error < 1 cent | S1 (timer exact) |
| T5 | DCO amplitude flatness | loopback amplitude C1…C8 with default CV law | spread ±5 % after `cal dco` | S1: −3.4 / +0.9 % |
| T6 | VCF self-oscillation threshold | DCO off, CV_RES ramp, detect sustained oscillation | 2.7…3.5 V | S3: 3.05 V |
| T7 | VCF tracking | self-oscillation frequency at CV_CUT = 1…4.5 V | slope 1.94 ± 0.2 oct/V, monotonic | S3: 1.94 oct/V |
| T8 | VCF lowpass | 110 Hz saw, CV_CUT at 1 kHz: harmonic 10 vs harmonic 1 | within ±3 dB of sim | S3 |
| T9 | VCA gain law | 1 kHz filtered saw, CV_VCA sweep | monotonic, max gain within ±2 dB of sim | S4: +7 dB |
| T10 | VCA thump | CV_VCA 0→full steps without signal, before/after `cal vca` | after cal < 3 mV step at line out | S4: 90 → 0.6 mV |
| T11 | CV settling | VCA step response seen at loopback | 1 % in < 2.5 ms | S2: 1.5 ms |
| T12 | Hum / noise | VCA open, DCO off, 1 s capture, spectrum | 100 Hz < sim + 6 dB; broadband < −60 dB re 1.33 Vpp | S7 |
| T13 | Temperature sensor | reading vs room temperature | ±5 K after 1-point cal | — |
| T14 | MIDI in | external MIDI keyboard: note on/off, pitch bend, CC | all received | — |

## 5. L3 — Calibration constants (stored in the 256 B user flash area)

| Constant | Method | Expected |
|---|---|---|
| `dco_gain` | measure saw amplitude at C4, scale CV_AMP law | 0.95…1.05 (sim 1/0.978) |
| `vcf_oct_per_v`, `vcf_offset` | self-oscillation frequency at two CV_CUT codes | 1.94 oct/V |
| `vcf_tc` | log frequency and temperature during warm-up | ≈ −13 cent/K |
| `vca_trim` | 2-point null of the thump (S4 procedure) | code 30…230 |
| `touch_base[16]`, `touch_thr[16]` | untouched mean + k·σ | — |

## 6. L4 — Validation (user)

| ID | Criterion | Method |
|---|---|---|
| V1 | Every key triggers reliably, no ghost notes, no double triggers | play chromatic runs, glissandi, fast repeats for 5 min |
| V2 | Touch-to-sound latency feels immediate | < 10 ms (firmware timestamp from touch detect to gate) |
| V3 | Tuning holds | play A4 against a tuner after 1 min and 30 min: DCO < 2 cent; filter self-osc drift compensated < 20 cent |
| V4 | Parameters are reachable and understandable with SHIFT/−/+ and the LEDs | user walkthrough of all parameters |
| V5 | Sound: bass, lead, resonant sweeps, self-oscillation usable | listening; compare with `docs/audio/s6_voice.wav` |
| V6 | Works on 9 V battery and 12 V adapter; no audible hum with a typical adapter | listening + T12 |
| V7 | MIDI playable from a keyboard / DAW | play |

## 7. Traceability (spec → sim → test)

| Spec item | Sim | HW test |
|---|---|---|
| DCO range and amplitude ±5 % | S1 | T4, T5 |
| CV ripple < −70 dB, settling < 2 ms | S2 | T11 |
| VCF cutoff 30 Hz…15 kHz, 24 dB/oct, resonance to self-osc. | S3 | T6, T7, T8 |
| VCA ≥ 70 dB off, low thump | S4 | T9, T10 |
| Touch Δ ≥ 5 × noise, scan ≥ 200 Hz | S5 | T2, T3, V1, V2 |
| Full voice | S6 | V5 |
| Power 9–12 V, ripple | S7 | B2–B5, T12, V6 |
