# TouchSynth Poly: controller plan

Status: plan 0.1 (2026-10-18). The controller is the CH32V203C8T6 on the backplane. Requirements:
[design.md](design.md) (F1–F4, F6, F10, P8–P11); backplane hardware: [spec.md](spec.md) section 4; voice bus:
[bus.md](bus.md); MIDI and patches: [midi.md](midi.md).

## 1. Hardware

| Block | Plan |
|---|---|
| MCU | CH32V203C8T6 (LQFP-48, 64 KB flash, 20 KB SRAM, 144 MHz), 8 MHz crystal; XC6206 3.3 V |
| USB device | USB-C (sink: 5.1 kΩ on CC1 / CC2), ESD protection, USBD on PA11 / PA12. The computer sees a class-compliant USB-MIDI device plus a CDC serial port: the computer plays and edits the synth over MIDI, no separate MIDI connection needed |
| USB host | USB-A on USBFS (PB6 / PB7) for class-compliant MIDI keyboards; VBUS through a current-limited switch (part to choose from the JLCPCB lists) |
| MIDI DIN in (not fitted) | footprint only: 3.5 mm TRS (MIDI type A) or a pin header, optocoupler with its resistors and diode (as rev 0.1's DNP MIDI input), into a free USART RX; for old hardware without USB |
| Power | USB-C VBUS, or an external 5 V on a 2-pin header (cleaner than a computer's USB 5 V). A 3-pin jumper selects the source (no diode drop: the cards' analog core wants the full 5 V). VBUS goes to a GPIO through a divider (the device enables its USB pull-up only when a computer is connected). Polyfuse and TVS on the 5 V rail. The cards filter their own analog rail (22 Ω + 3 × 100 µF, CJ431: supply rejection 66–77 dB) |
| Voice bus | USART TX (broadcast), USART RX (return, 1 kΩ pull-up), SYNC (timer output, 1 kHz), 8 × NRST through a 74HC595 on SPI1, 8 × SWIO (GPIOs, each with a 1 kΩ pull-up to 3.3 V: the cards have none), 24 MHz from TIM3 CH4 to CLK_IN (option; MCO cannot give 24 MHz) |
| Mixer, ADC tap | S12 (to be revised for L / R outputs per card if S13 adds a pan stage); ADC1 / ADC2 for USB audio |
| Programming | SWD header (SWDIO PA13, SWCLK PA14, 3.3 V, GND) for the WCH-LinkE: development and debugging (minichlink, as for the voice cards). BOOT0 jumper: the factory bootloader then reprograms the flash over USB (wchisp or WCH's ISP tool) without a programmer, the path for firmware updates in the field |
| Indicators | power LED, activity LED (MIDI / bus) |

Pin numbers come with the backplane schematic, from the datasheet's LQFP-48 table. Known: USBD PA11 / PA12, USBFS
PB6 / PB7, SWD PA13 / PA14, crystal on PD0 / PD1, BOOT0 pin. GPIO budget 34 of 37 (backplane.md 3.3).

## 2. Firmware

```
 USB device (MIDI, CDC)   USB host (MIDI)   UART MIDI (option)
          │                     │                 │
          └──────────► MIDI router: channel → parts ◄──── CDC commands, SysEx
                                  │
                 parts, voice allocator (poly / mono / legato / unison / kit), sustain
                                  │
                 bus scheduler: frame clock, timed events (lead 2 frames), refreshes
                                  │
          USART TX DMA ◄── frame queue        SYNC timer 1 kHz        USART RX ◄── replies
```

| Module | Content |
|---|---|
| Frame clock | a timer outputs SYNC (1 kHz) and interrupts at each frame start: FRAME packet, then the packets due in this frame, sent by DMA |
| USB device | composite MIDI + CDC (UAC1 audio input later); ch32fun's USB code or a TinyUSB port, to decide on the development board |
| USB host | class-compliant MIDI on USBFS; a small host driver or TinyUSB host |
| MIDI router, parts | midi.md: 8 parts, channel and key ranges, CCs, NRPN, program change, MIDI clock |
| Voice allocator | free voice, else oldest released, else oldest held, within a part's slot mask; patch slots on the cards (PATCH_SELECT) |
| Bus scheduler | bus.md: timed events, the bus lead, bandwidth per frame, VOICE_STATE and patch refreshes, requests and replies |
| Enumeration, calibration | slot by slot over NRST at power-up; calibration on request; results stored by chip ID |
| Storage | patch library (64 × 144 bytes) and setups in the V203's flash (wear-levelled pages); working copies in SRAM |
| Card programming | SWIO on each slot's line (the WCH-LinkE protocol), image streamed from the computer over CDC |
| CDC commands | patches, setups, part settings, card status, calibration, firmware update, a bridge to a card's console |

Memory estimate: USB device + host stacks 15–25 KB, application 15–20 KB, patch library and setups about 12 KB:
inside 64 KB flash; 20 KB SRAM holds the working copies, the frame queue and the USB buffers.

## 3. Development path

1. **Development board + board 1:** a V203 development board as controller, board 1 as one voice, wired by hand
   (UART TX → board 1 RX (PD6), board 1 TX (PD5) → board RX with a pull-up, SYNC → board 1 PD4, a GPIO → board 1
   NRST, GND). Board 1's PD4 / PD5 are its 74HC595 latch and loopback ADC today; the voice firmware's card build
   (with the card's pin map) runs on board 1 with those functions given up. First: SYNC frame clock and HSITRIM
   locking, then the bus receiver, then USB-MIDI → notes.
2. **USB:** MIDI + CDC device on the development board, then the host port.
3. **Backplane:** schematic and layout once the card and the mixer (S12 / S13) are settled; then 1–2 cards, then 8.

## 4. Open points

- The bootloader's USB port on the V203 (USBD on PA11 / PA12 or USBFS) and whether wchisp supports it; until then
  the WCH-LinkE over SWD.
- USB stack choice; isochronous audio support.
- The current-limited switch for the host port and the USB-C ESD part from the JLCPCB lists.
- MIDI DIN: TRS or 5-pin DIN footprint.
- SWIO programming timing from the V203 (bit-banged one-wire protocol at 144 MHz).

## 5. USB device, as built and measured *[2026-10-19]*

Bench: the V203 development board (CH32V203C8T6, 8 MHz crystal, PLL 144 MHz, USB clock PLL / 3 = 48 MHz) running
`firmware/bench_ctrl` with the voice card on the bus, its own USB-C port on the lab PC (Linux 7.0, xHCI).

**Which peripheral.** The development board wires its USB-C to **USBFS (PB6 D−, PB7 D+)**, not to USBD: with the
transceivers off, PB6 / PB7 read 0 against the GPIO pull-ups (the host's 15 kΩ pull-downs), PA11 / PA12 read 1. So
the firmware has two drivers behind one API (`usbdev.h`, shared descriptors and data paths in `usb_common.h`):
`usbdev_fs.c` on ch32fun's `extralibs/fsusb.c` (USBFS, the default build, tested here) and `usbdev.c`, an own
driver for **USBD on PA11 / PA12** (`make USB=usbd`: the backplane's device port, section 1; it builds, but there
is no host on PA11 / PA12 on this board, so it is untested). ch32fun's `usbd.c` was not used: it re-arms an OUT
endpoint after every packet (no flow control), sets `RCC->AHBPCENR = SRAM` (DMA1, the voice bus, off) and NAKs the
wrong direction after an IN packet.

**Descriptors.** USB 2.0 full speed, composite with IAD (class EF/02/01), bus powered 100 mA, ID 1209:0001 (the
pid.codes test ID, development only; `-DUSB_VID`, `-DUSB_PID` for another), strings "TouchSynth" / "TouchSynth
Poly" / the chip's unique ID. Interfaces: 0 Audio Control (no units), 1 MIDI Streaming (one cable: EP 0x01 OUT bulk
64, EP 0x82 IN bulk 64), 2 CDC ACM control (EP 0x83 interrupt, never sends, protocol 0: no modem probing), 3 CDC data
(EP 0x04 OUT, EP 0x85 IN, bulk 64). One direction per endpoint number (fsusb.c gives endpoint n buffer n). Linux
binds snd-usb-audio (card "TouchSynth Poly", one raw MIDI port each way) and cdc_acm
(`/dev/serial/by-id/usb-TouchSynth_TouchSynth_Poly_<serial>-if02`).

**MIDI.** An OUT packet (up to 16 events) is one command, exactly as the PC command `e`: the main loop turns its
events (code index → 1–3 bytes, running status of its own) into MIDI and runs `midi_events` for the frame of the
publish + L (allocator, V_PRIO and the markers included). SysEx: the universal identity request (F0 7E id 06 01 F7)
is answered on the MIDI IN endpoint (F0 7E 00 06 02 7D 00 00 00 00 00 01 00 00 F7), other SysEx is ignored.
Flow control: four packet slots; the endpoint NAKs while they are full, the host retries (nothing is dropped).
The interrupt stamps every packet (frame, µs since its SYNC edge); `U` reports arrival → publish and arrival →
execution frame edge.

**CDC.** A second command port with the full USART1 command set, the Ardulink bridge included (minichlink
`-C ardulink -c <the CDC port>` works). A command runs to its end on the port of its first byte and answers there;
a command cut off by closing the port is abandoned (the main loop continues), output to a closed port (DTR low) is
dropped. New bench commands: `U` (USB counters, latencies, stack low-water mark, reset flags), `u` (the D+ pull-up:
off, on, or a timed re-plug), `Q` (USB-MIDI packets into the MIDI path as if received), `X` (pin probe), `J` (jump
into the factory bootloader).

**Measured** (`tools/usbtest.py`, `tools/bustest.py`):

| Item | Result |
|---|---|
| Enumeration | first attempt, full speed; snd-usb-audio and cdc_acm bound; the V203 reset (minichlink `-b`): back on USB after 0.37 s, the card on the bus at once |
| Bus tests | `bustest.py all` 17/17 over USART1 and 17/17 over the CDC port (the card reset through Ardulink over CDC) |
| CDC command rate | 11 900 `e` commands/s with their replies (0.084 ms each); none lost, no card errors |
| USB → note | arrival → publish 6–37 µs (main loop); arrival → execution frame edge 1.0–2.0 ms (the rest of the arrival frame + L − 1 frames, `L` = 2); then `D` frames + 9 µs (scope, the marker test: 4.0093 ms mean, spread 6 µs): **USB packet → note 5.0–6.0 ms** with `D` = 4, `L` = 2 |
| MIDI path (injected) | bustest's notes / patch / ctrl checks pass with every message as USB-MIDI packets through the firmware's MIDI path (`Q`); the identity reply goes out on MIDI IN |
| SYNC | time interval error 0.9 ns p-p idle, 0.6 ns p-p during a CDC flood (scope, 500 MSa/s, interpolated edges: the scope's limit); the frame interrupt enters within 0–3 µs of the edge with or without USB traffic (budget cuts start at 40 µs); no shortened frames, no `tx_over` |
| Re-plug | the D+ pull-up off for 300 ms (`u`), 5 times: the host drops the device within 6–27 ms and has it back (tty) after 0.65–0.71 s; CDC works after each |
| Dense traffic over CDC | `bustest.py stress` over CDC: 99 notes/s (40 % more than over USART1), no bus errors; card DAC underruns as over USART1 (bus.md 9.3, the three-oscillator patch; one with the modal switch) |
| Resources | 20.5 KB flash, 8.0 KB SRAM; stack low-water mark 11 KB free |

**USB-MIDI through ALSA** (measured after the lab user joined the group audio, which the raw MIDI device needs):

| Test | Result |
|---|---|
| `usbtest.py midi` | identity request answered in 0.2 ms; bustest's notes / phrase / patch slots / modal / CTRL / PARAM checks pass with every message sent as USB-MIDI, card counters 0 |
| `latency --scope` | USB arrival → execution frame edge 1.03–1.99 ms (mean 1.51, expected 1–2 ms at `L` = 2), then 4.008 ms ± 5 µs to the note: **USB → note 5.0–6.0 ms** |
| `flood`, unmapped CCs | 20 000 messages at about 125 000 / s: all arrive, the endpoint holds the host off (NAK) instead of dropping |
| `flood`, notes / bend / wheel | 20 000 messages at about 9 900 / s: all arrive, none dropped; the bus saturates (79 B/frame) and the events arrive late at the card, as expected beyond about 86 B/frame (bus.md 9.5); the test reports this instead of failing |
| `jitter`, MIDI flood | SYNC period and TIE unchanged (p-p about 1 ns, the scope's resolution) with 253 000 MIDI messages; frame interrupt within 2 µs of the edge |

**Found on the way.** The bench build used ch32fun's default V203 memory map (32 KB / 10 KB, the F6P6); with USB the
stack (main's inlined reports, 1.8 KB) ran into `.bss` and the controller reset under load. The Makefile now names
the C8T6 (64 KB / 20 KB), and the reporting functions are `noinline`. `INTSYSCR` is 0 (no nesting): the USB
interrupt cannot preempt the frame interrupt, only delay it by its own length (≤ 3 µs measured).

**USBD D+ pull-up** (backplane.md 9): `EXTEN_USBD_PU_EN` switches an internal pull-up on PA12: with the transceiver
powered PA12 rises from 0 V in about 80 ns with the bit set and never without it; with the transceiver off the bit
does nothing. Its strength against a host is not shown: the powered transceiver pulls PA12 low by itself (a floating
pin falls at once), the pull-up wins against that alone but not against that plus the 40 kΩ GPIO pull-down. So keep
the 1.5 kΩ footprint until the USBD build has enumerated once (a USB cable to PA11 / PA12 of the development board,
`make USB=usbd`). USBFS needs no external pull-up (this board has none and enumerates).

**Factory bootloader:** a jump to the system flash (0x1FFF8000, `J`, clocks and peripherals reset) made a device
appear on the USBFS port that did not answer SET_ADDRESS (error −71): inconclusive. BOOT0 = 1 at reset (a jumper)
is the real test.
