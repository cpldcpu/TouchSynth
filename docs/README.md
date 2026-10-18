# docs

| Document | Content |
|---|---|
| [design.md](design.md) | Requirements, partitioning, budgets, interfaces, verification plan, status and open points. |
| [bus.md](bus.md) | Voice bus protocol: frame clock, timed events, presentation delay, packets, messages, enumeration. |
| [spec.md](spec.md) | Architecture: voice cards (CH32V006, digital oscillators, 5 V analog core) on a USB backplane (CH32V203), pin maps, connectors, mixer, voice bus, clock synchronisation, decisions and open points. |
| [devlog.md](devlog.md) | Development log since the fork from TouchSynth rev 0.1. |

## Results (`results/`)

| File | Content |
|---|---|
| `s8_dac.csv` | S8: the pulse output as a PWM DAC through the rev 0.1 voice (edge vs centre-aligned, interpolation) |
| `s9_osc.csv` | S9: inharmonic content of an open-filter saw, analog DCO against DAC variants (model) |
| `s9_moog.csv` | S9b: three-oscillator voice, residual against an ideal DAC (model) |
| `s10_5v.csv` | S10: the analog voice core at 5 V against rev 0.1 (headroom, cutoff, resonance, THD, noise, supply rejection) |
| `s11_recon.csv` | S11: the DAC's reconstruction filter and mixer resistor on the 5 V core (carrier at the line out, droop) |
| `hw_board1_dco_vs_dac.csv` | board 1: saw C2–C7 from the DCO and from the DAC, level and inharmonic content |
| `hw_board1_hsitrim.csv` | board 1: CH32V006 HSITRIM step and range |
| `hw_board1_half_rate.csv` | board 1: oscillators at full (187.5 kHz) and half rate (93.75 kHz): inharmonic content of the three-oscillator tunes, single-saw aliasing C2–C7 against the polyBLEP prediction |
| `hw_board1_hsi_jitter.csv` | board 1: HSI period jitter, Allan deviation, LDO settings |
| `s1_cal.csv`, `s3_*.csv`, `s4_vca_gain.csv`, `behav_cal.csv` | rev 0.1 calibration, still read by the behavioural model and `firmware/voice/gen_tables.py` until the 5 V core is characterised |

## Figures (`figures/`)

`s9_osc` (DCO vs DAC spectrograms, model), `s9_hw` (board 1 three-oscillator takes vs model), `s9_hwcmp`
(DCO vs DAC on board 1), `s10_5v` (5 V core: cutoff and THD).

## Audio (`audio/`)

- `s9_osc/`: model renders of the oscillator variants (`a_dco` … `h_dac_188k_rc`), the three-oscillator voice
  (`moog_*`), board 1 takes against the model (`hw_moog_*`, `model_moog_*`), DCO against DAC on board 1
  (`cmp_*`), the kettle on the 187.5 kHz carrier (`hw_kettle_188k`), full against half rate on board 1
  (`hw_full_rate_*`, `hw_half_rate_*`).
- `suite_moog_hw.mp3`: the TouchSynth suite recorded on board 1 with the Toccata's top voice on the
  three-oscillator DAC voice.
