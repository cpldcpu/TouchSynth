# TouchSynth Poly: controller plan

Status: plan 0.1 (2026-10-18). The controller is the CH32V203C8T6 on the backplane. Requirements:
[design.md](design.md) (F1–F4, F6, F10, P8–P11); backplane hardware: [spec.md](spec.md) section 4; voice bus:
[bus.md](bus.md); MIDI and patches: [midi.md](midi.md).

## 1. Hardware

| Block | Plan |
|---|---|
| MCU | CH32V203C8T6 (LQFP-48, 64 KB flash, 20 KB SRAM, 144 MHz), 8 MHz crystal; XC6206 3.3 V |
| USB device | USB-C (sink: 5.1 kΩ on CC1 / CC2), ESD protection, USBD on PA11 / PA12. The computer sees a class-compliant USB-MIDI device plus a CDC serial port: the computer plays and edits the synth over MIDI, no separate MIDI connection needed |
| USB host | USB-A on USBFS (PB6 / PB7) for class-compliant MIDI keyboards; VBUS through a current-limited switch (part to choose from the JLCPCB lists). *[2026-10-20]* TPS2051C, fitted (backplane.md 4.2); host driver: section 6 |
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
| Dense traffic over CDC | `bustest.py stress` over CDC: 99 notes/s (40 % more than over USART1), no bus errors; card DAC underruns as over USART1 (bus.md 9.3, the three-oscillator patch; one with the modal switch); *[2026-10-20]* none since the render rewrite (bus.md 9.5) |
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

## 6. USB host, as built and measured *[2026-10-20]*

Feasibility check for the backplane's host port (backplane.md 4.2: USB-A J2 on USBFS PB6 / PB7, TPS2051C with
HOST_EN on PB8 and HOST_FLT_N on PB9), on the development board. Its USB-C goes to the same USBFS.

**Driver.** `firmware/bench_ctrl/usbhost.c` (`make USBH=1`; `usbhost.h`) is a minimal USB-MIDI host. The register
handling follows WCH's CH32V20x EVT example USBFS/HOST_KM (Apache-2.0), rewritten as a non-blocking state machine:
- Root port only, no hubs, full and low speed.
- Attach debounce 100 ms, bus reset 15 ms, then speed from the D− level and 20 ms of reset recovery.
- Enumeration: device descriptor (8, then 18 bytes), SET_ADDRESS, configuration descriptor (up to 512 bytes),
  product string, SET_CONFIGURATION. SET_INTERFACE only if the MIDI interface is an alternate setting.
- The first Audio / MIDI Streaming interface with an IN endpoint (bulk or interrupt) is used, plus its OUT endpoint.
- **Polling:** the IN endpoint is polled at most once per USB frame, and only right after the host's SOF flag and
  not later than 700 µs into the frame. SOF and the TIM1 SYNC frame come from the same crystal, so their phase is
  constant after each port enable and is measured then.
- **Handshakes:** DATA0 / DATA1 kept per endpoint. A NAK waits for the next frame. A repeated packet (wrong
  toggle) is dropped. A STALL is cleared (CLEAR_FEATURE, DATA0).
- **Detach:** the attach level, a pending DETECT event, or the hardware clearing UH_PORT_EN. With the level alone, a
  300 ms detach was missed while the main loop was blocked.
- **No interrupt:** everything runs in the main loop (`idle()`), and the USBFS interrupt stays off. The frame
  interrupt keeps its priority and nothing takes a critical section.
- **Port power:** HOST_EN goes high only after the host mode is set up. HOST_FLT_N low for 2 ms switches the port
  off; it is retried after 1, 2, 4, 8 s.
- Received USB-MIDI packets enter the same MIDI → bus path as the device's: one packet is one command, timed for the
  frame of the publish + L, with a running status of its own. SysEx is only counted.
- In this build the USB device (MIDI + CDC) runs on USBD, PA11 / PA12 (`usbdev.c`). The default build is unchanged
  (USB device on USBFS).

Bench commands:

| Command | Function |
|---|---|
| `H` | host status |
| `h 0` / `h 1` / `h 2` | port power off / on / re-enumerate |
| `h 3` | pull-down probe |
| `h 4` | the device's descriptors |
| `h 5` | a packet to the device's MIDI OUT |
| `I` | a packet on this controller's own USB-MIDI IN endpoint |

Tests: `tools/hosttest.py`.

**Internal pull-downs of USBFS (the two 15 kΩ footprints).** While the USBFS SIE is configured, in device or host
mode and even with its clock gated, the GPIO block no longer reaches PB6 / PB7: driven high as outputs they read 0.
GPIO pull-ups therefore tell nothing there. The level readings of section 5 ("PB6 / PB7 read 0 against the GPIO
pull-ups") came from such a state; the USBFS wiring itself is proven by the enumeration.

The probe (`h 3`) works as follows:
1. Hold the SIE in reset (`UC_RESET_SIE`: the pads are GPIOs then) and charge the pin to 3.3 V.
2. Release the pin as a floating input and take the SIE out of reset in the condition under test.
3. Time how long the SIE's own pin bit takes to fall. Same pin, same capacitance: the time is proportional to the
   pull-down resistance.

Measured with the lab PC on the cable (its 15 kΩ host pull-downs on both lines):

| Condition | D− | D+ |
|---|---|---|
| USBFS off, GPIO pin falling through the PC's pull-downs | 3.95 µs | 4.23 µs |
| Host mode, `UH_PD_DIS` = 1 | 3.87 µs | 4.15 µs |
| Host mode, `UH_PD_DIS` = 0 | 1.92 µs | 1.96 µs |
| Device mode, `UD_PD_DIS` = 0 / 1 | the same as host mode | the same as host mode |

With `UH_PD_DIS` = 1 the lines fall exactly as through the PC's pull-downs alone, which calibrates the method.
With `UH_PD_DIS` = 0 they fall twice as fast: R_int = 0.99 (D−) and 0.90 (D+) × R_ext. That is about 13–15 kΩ for
a 15 kΩ PC pull-down, and 12.8–24.5 kΩ over the USB tolerance of R_ext. **The internal host pull-downs exist and
are in the USB range: the 15 kΩ footprints can stay unfitted.**

The bit keeps its value (HOST_CTRL 0x00 / 0x80). In device mode the pull-downs are on as well unless `UD_PD_DIS` is
set; ch32fun's fsusb.c leaves it clear, so D+ sits at about 2.75 V instead of 3.0 V and still enumerates.

**Without a device** (the lab PC on the cable, another host):
- The host stays in "wait": no attach in more than 3 minutes, no SOF, no polling.
- `bustest.py all` passes 17/17 (twice).
- SYNC on the scope: period p-p 1.4 ns, TIE p-p 0.9 ns.
- The frame interrupt comes within 0 µs of the edge; no shortened frames, no `tx_over`.

**Loop test** (`hosttest.py loop`; no keyboard was available). The development board's USB-C was unplugged and two
jumpers wired PA11 → PB6 and PA12 → PB7, so the controller's own USB device (USBD, `usbdev.c`) sat on its own host
port. No VBUS was needed.

| Item | Result |
|---|---|
| Enumeration | 1209:0001 "TouchSynth Poly", full speed, address 1, attach (debounced) → running 162 ms; composite with IAD (167-byte configuration), MIDI streaming interface 1: IN 0x82 bulk 64, OUT 0x01 bulk 64. The first proof of the USBD driver: it enumerates with its internal pull-up only (`EXTEN_USBD_PU_EN`, no 1.5 kΩ), against this host's ~14 kΩ pull-downs |
| MIDI → card | bustest's notes / phrase / patch slots / modal / CTRL / PARAM checks pass with every message sent device → host → bus → card; card counters 0 |
| Burst | 2000 packets of 16 events (32 000 events) at the bench port's rate (158 packets/s): all received, 0 errors, 0 toggle errors, ring never full, 0 late SOF |
| Notes | 200 note on / off pairs: 400 events, card crc / late 0, gate 0 at the end |
| Host OUT | `h 5` → the device's MIDI OUT → the card (gate 1) |
| Detach / re-attach | the device's pull-up off for 300 ms: detach seen, running again 0.57 s after the pull-up went off (3 / 3); also with the main loop blocked for those 300 ms (after the fix above). `h 0` / `h 1` (port power) and `h 2` (re-enumerate) work |
| Latency | device packet ready → host arrival 34–1003 µs (mean 0.35–0.5 ms: the next poll, once per USB frame). Arrival → execution frame edge is constant within a session (1.70 ms in one, 1.86 ms in another), because SOF and SYNC share the crystal; it lies between 1 and 2 ms (at `L` = 2). So **USB packet → execution frame edge 1–3 ms (here 1.7–2.9 ms), then `D` to the note** (about 6–7 ms at `D` = 4), plus the keyboard's own scan, which was not measured |
| SYNC | during the burst: period p-p 1.2 ns, TIE p-p 0.9 ns, frame interrupt within 4 µs of the edge (the USBD interrupt), no shortened frames, no `tx_over`; `bustest.py all` 17/17 with the host running (2 polls skipped, `late_sof`, while the bus tests blocked the main loop) |
| CPU | 2.75 µs per USB frame on average (91 ms in 33 262 frames, 0.3 %), at most 7 µs per `usbh_poll` call |
| Resources | host build (USBD device + USBFS host + everything else): 27.7 KB flash, 9.0 KB SRAM, 10 KB stack free; default build 20.7 KB / 8.0 KB |

**Device and host at once.** Both are proven running together: the loop test is exactly that, USBD device and USBFS
host side by side. They use separate peripherals and buffers and share only the 48 MHz USB clock. The USBD
interrupt runs below the frame interrupt, and the host runs in the main loop. Both fit easily in the C8T6
(64 KB / 20 KB), leaving room for the application and the patch store (section 2).

**Not tested:**
- a real USB-MIDI keyboard: no device with 5 V on the development board's VBUS. On WCH's CH32V203C8T6 EVT the USB-C
  VBUS is the board's +5V net, fed only by a USB connector;
- low-speed devices: WCH's settings were taken over, including `UH_PRE_PID_EN`;
- interrupt-type MIDI endpoints (supported, untested); hubs (not supported);
- the TPS2051C fault path (PB8 / PB9 are plain GPIOs on the development board);
- VBUS behaviour (inrush into about 40 µF instead of 120 µF);
- a transaction that runs into a SOF: avoided by the 700 µs limit, so the SIE's behaviour there is unknown.

Bench note: the first open of the LinkE's UART sometimes gets no answer to the sync byte (`bench controller: no
sync`); a second open works.
