# TouchSynth Poly: SysEx and NRPN protocol (host software)

Status: draft 0.1 (2026-10-20). Implemented by the browser app's emulator (`app/js/emulator.js`); the controller
firmware is to implement the same. Background: design report, sections "Host software" (requirements HS1–HS11,
architecture); [midi.md](midi.md) (parts, MIDI implementation, parameters). The parameter IDs, ranges and names
come from [params.json](params.json).

Everything musical goes over MIDI, so any MIDI host (a DAW, a librarian) reaches it: live parameter changes as
NRPN, everything else as SysEx. The CDC port carries only maintenance (firmware images, the console bridge).

## 1. NRPN: live parameter changes

On the MIDI channel of a part, to that part's edit buffer (the patch the part plays; not stored until STORE):

```
Bn 63 00     NRPN MSB = 0
Bn 62 id     NRPN LSB = parameter ID (0-63 patch, 64-79 per voice)
Bn 06 msb    data entry MSB  } 14-bit d = msb << 7 | lsb, 0 ... 16383
Bn 26 lsb    data entry LSB  } the value is applied when the LSB arrives
```

`d` spans the parameter's full range: `value = min + round(d × (max − min) / 16383)`; the host sends
`d = round((value − min) × 16383 / (max − min))`, which round-trips exactly for every integer value.

Program change on a part's channel selects that part's program (0–63) and loads it into its edit buffer.

## 2. SysEx framing

```
F0 7D 54 50 dev cmd data... F7
```

- `7D`: the non-commercial manufacturer ID; `54 50` ("TP"): the instrument; `dev`: device number 0–126, 127 =
  any (the host uses 127; the instrument answers with its own, 0 by default).
- `cmd`: the message (section 3). Requests carry the low command numbers; a reply has the same layout whichever side
  sends it, so a dump sent to the instrument writes.
- Values: 7-bit bytes only. Signed 16-bit values as three bytes, least significant first:
  `v & 0x7F, (v >> 7) & 0x7F, (v >> 14) & 0x03` (two's complement over 16 bits). Unsigned bytes 0–127 as one byte.
  Names: 16 ASCII characters 0x20–0x7E, padded with spaces.

## 3. Messages

| cmd | Name | Direction | Data |
|---|---|---|---|
| 0x01 | PATCH_REQ | host → | `slot`: 0–63 program, 0x40 + p edit buffer of part p (0–7) |
| 0x02 | PATCH_DUMP | both | `slot`, name (16), 64 values (3 bytes each, IDs 0–63; unused IDs 0) |
| 0x03 | STORE | host → | `part`, `program`: the part's edit buffer into a program; reply ACK |
| 0x04 | NAMES_REQ | host → | – |
| 0x05 | NAMES | → host | 64 names (16 each) |
| 0x10 | SETUP_REQ | host → | – |
| 0x11 | SETUP_DUMP | both | 8 part records (10 bytes each), tuning (3 bytes, 1/256 semitone), flags (1) |
| 0x20 | CARDS_REQ | host → | – |
| 0x21 | CARDS | → host | 8 card records (slots 1–8, 37 bytes each) |
| 0x22 | CALIBRATE | host → | slot mask (2 bytes: bits 0–6 = slots 1–7, bit 0 of the second = slot 8); reply ACK |
| 0x7E | ACK | → host | `cmd` acknowledged, `status` (0 ok, 1 unknown command, 2 bad data, 3 busy) |

Part record (10 bytes): channel (0 = off, 1–16), key low, key high, slot mask low 7 bits, slot mask bit 7, mode (0
poly, 1 mono, 2 legato, 3 unison, 4 kit), program (0–63), volume (0–127), transpose + 64 (−48 … +48), pan (0 left,
64 centre, 127 right).

Card record (37 bytes): present (0/1), kind (0 voice, 1 effects), chip ID as 16 nibbles (most significant first),
firmware version (3), capabilities (1, bit 0 dual PWM), bus state (1: 0 standalone, 1 trim, 2 listen, 3 synced,
4 SYNC lost), clock error in ppm (3), CPU load in % (1), CRC errors (3), late events (3), DAC underruns (3), flags
(1: bit 0 calibrated, bit 1 calibration running).

## 4. Universal messages

The universal identity request `F0 7E 7F 06 01 F7` is answered with `F0 7E dev 06 02 7D 00 00 00 00 v1 v2 v3 v4 F7`
(family and model 0; the firmware version in the last four bytes); the bench controller does this already
(controller.md 5).

## 5. Open

- Bank dumps as 64 PATCH_DUMPs (the app does this now) or a dedicated message; setups beyond the active one.
- Kit maps (midi.md 2.1), MIDI clock and global settings in SETUP_DUMP.
- Flow control: the instrument processes a SysEx within a frame or two; the app spaces bulk messages by 10 ms.
- The maintenance commands on CDC (firmware images, console bridge): with the controller firmware.
