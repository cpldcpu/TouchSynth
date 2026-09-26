# TouchSynth hardware (KiCad 10)

Everything here is generated from Python; edit the sources, not the `.kicad_sch` files.

| File | Role |
|---|---|
| `design.py` | single source of truth: parts (value, footprint, LCSC, sim name), nets, sheets, groups |
| `lcsc.py` | picks JLCPCB basic / promotional parts for passives (voltage rating >= 2x working voltage) |
| `layouts.py` | hand-drawn sheet layouts (placement + wires) |
| `draw.py` | drawing layer: geometric connectivity, auto-labels for split nets, short detection, junctions |
| `gen_sch2.py` | writes the schematic (`touchsynth/*.kicad_sch`) — **use this one** |
| `gen_sch.py` | v1 generator (label-only layout); its writer functions are reused by v2 |
| `check_netlist.py` | exports the KiCad netlist and compares it with `design.py` |
| `check_sim.py` | compares the design with the ngspice netlists (S6 + S7) |
| `touchsynth/TouchSynth.pretty` | touch-key footprints (copper under solder mask) |

```
python gen_sch2.py && kicad-cli sch erc touchsynth/touchsynth.kicad_sch && python check_netlist.py && python check_sim.py
```
