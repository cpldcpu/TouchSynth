# Hardware generator scripts (KiCad 10)

Everything here is generated from Python; edit the sources, not the `.kicad_sch` files. The scripts serve several
boards; `BOARD` selects one (`board.py`):

| `BOARD` | Design | Output | Status |
|---|---|---|---|
| `voice` (default) | `voice.py`: the voice card (docs/spec.md section 3) | `voice/` | schematic generated, hand-laid out (`layouts_voice.py`) and checked, no PCB |
| `touchsynth` | `design.py`: TouchSynth rev 0.1, for reference | `touchsynth/` (its KiCad project is on `master`) | |

| File | Role |
|---|---|
| `voice.py`, `design.py` | single source of truth per board: parts (value, footprint, LCSC, sim name), nets, sheets, groups; `voice.py` also maps its simulation netlist (S10 variant v5c) to its nets |
| `board.py` | board selection (`BOARD`), project name, power nets, layout module |
| `lcsc.py` | picks JLCPCB basic / promotional parts for passives (voltage rating >= 2x working voltage; C0G on request) |
| `layouts_voice.py`, `layouts.py` | hand-drawn sheet layouts of the voice card and of rev 0.1; `layouts_none.py`: none (every part auto-placed, only the PWR_FLAGs drawn) |
| `draw.py` | drawing layer: geometric connectivity, auto-labels for split nets, short detection, junctions |
| `gen_sch2.py` | writes the schematic (`<board>/*.kicad_sch`) — **use this one** |
| `gen_sch.py` | v1 generator (label-only layout); its writer functions are reused by v2 |
| `check_netlist.py` | exports the KiCad netlist and compares it with the design |
| `check_sim.py` | compares the design with its ngspice netlist (nodes and values of every simulated element) |
| `gen_pcb.py`, `pcb_*.py`, `fab.py` | PCB generation and fabrication outputs of rev 0.1, to be adapted |
| `lib/TouchSynth.pretty` | rev 0.1 touch-key footprints |

```
python gen_sch2.py && kicad-cli sch erc voice/voice.kicad_sch && python check_netlist.py && python check_sim.py
```
