# TouchSynth Poly

A polyphonic analog synthesizer with up to 8 voices, played and edited from a computer over USB. Each voice is a
small plug-in card: a CH32V006 generates the oscillators digitally on a PWM DAC (187.5 kHz, sigma-delta) and
controls an analog transistor-ladder filter and VCA. A backplane with a CH32V203 holds the USB interface
(USB-MIDI), the voice bus, the 5 V supply and the stereo mixer.

**Status (2026-10-20):** both boards are designed, simulated and laid out, nothing of the new hardware is built
yet: the voice card (50 × 50 mm, 4 layers) and the backplane (100 × 100 mm, 4 layers; USB-C device and USB-A host
port, slot 1 convertible to an effects slot) are routed and DRC clean. The voice bus runs on the bench (a CH32V203
development board as controller, a CH32V006 evaluation board as voice card, plus 7 virtual voices for load tests):
every patch, three oscillators included, plays under 8-voice bus load without a dropout; the controller is a
USB-MIDI + CDC device there, and a USB-MIDI host for keyboards works in a self-loop. The voice firmware's oscillator
engine was developed on TouchSynth board 1 (rev 0.1). The design report collects it all, including the software
requirements and architecture (drafts for review):
[docs/report/touchsynth_poly_report.pdf](docs/report/touchsynth_poly_report.pdf).

This project is a fork of [TouchSynth](https://github.com/cpldcpu/TouchSynth) (rev 0.1: a monophonic touch synth
with an analog DCO), whose history is on `master`; it is to move to its own repository, TouchSynthPoly (the
name the boards' silkscreen already carries). The digital oscillators were developed and measured on its
board 1; the analog filter and VCA are its circuits, redesigned for a single 5 V supply.

Design: cpldcpu & Claude Opus 5.5.

## Documents

| Document | Content |
|---|---|
| [docs/report/touchsynth_poly_report.pdf](docs/report/touchsynth_poly_report.pdf) | design report (LaTeX, 81 pages): architecture, both boards, simulations, voice bus, software requirements and architecture, firmware, verification, BOM, schematics |
| [docs/design.md](docs/design.md) | requirements, architecture, budgets, verification plan, open points |
| [docs/backplane.md](docs/backplane.md) | backplane / controller PCB (0.3, drawn in KiCad) |
| [docs/controller.md](docs/controller.md) | controller plan (hardware, firmware, development path) |
| [docs/midi.md](docs/midi.md) | MIDI implementation, parts and patches (proposal) |
| [docs/bus.md](docs/bus.md) | voice bus protocol, as built and measured on the bench (section 9) |
| [docs/spec.md](docs/spec.md) | architecture: voice card, backplane, voice bus, clock synchronisation, decisions, open points |
| [app/](app/README.md) | browser app: editor, librarian, setup, card status, console; with an emulator of the instrument |
| [docs/sysex.md](docs/sysex.md) | SysEx and NRPN protocol of the host software (draft) |
| [docs/devlog.md](docs/devlog.md) | development log since the fork |
| [docs/README.md](docs/README.md) | index of the documents, schematics, results, figures and audio |

## Repository layout

```
docs/        specification, devlog, results (CSV), figures, schematics (PDF), the design report, audio examples
sim/         ngspice studies (S8 PWM DAC, S9 oscillators, S10 5 V analog core, S11 reconstruction filter, S12 mixer,
             S13 stereo pan) and the behavioural model
firmware/    voice/: CH32V006 voice card firmware (bus receiver, voice engine, PWM DAC); bench_ctrl/: CH32V203
             bench controller (bus master, USB-MIDI + CDC, USB-MIDI host, SWIO programmer); ch32fun (git submodule)
app/         browser app (editor, librarian, console) with an emulator of the instrument
hw/          schematic / PCB generators (KiCad 10) of the voice card and the backplane; rev 0.1 for reference
parts/       JLCPCB Basic / Promotional Extended part lists
tools/       bench tools: voice bus and USB tests, SWIO console, oscilloscope recording, hardware tests, mixing
```

Constraints: JLCPCB Basic and Promotional Extended parts only, except the backplane's CH32V203 (assembled from a
JLCPCB personal stock); the voice MCUs (own stock), headers and connectors hand-soldered.
