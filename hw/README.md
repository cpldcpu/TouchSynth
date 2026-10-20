# Hardware generator scripts (KiCad 10)

Everything here is generated from Python; edit the sources, not the `.kicad_sch` files. The scripts serve several
boards; `BOARD` selects one (`board.py`):

| `BOARD` | Design | Output | Status |
|---|---|---|---|
| `voice` (default) | `voice.py`: the voice card (docs/spec.md section 3) | `voice/` | schematic generated, hand-laid out (`layouts_voice.py`) and checked; PCB generated and routed (`voice/voice.kicad_pcb`, 50 × 50 mm, 4 layers, DRC clean, stereo pan stage S13 A) |
| `backplane` | `backplane.py`: the backplane and controller (docs/backplane.md) | `backplane/` | schematic hand-laid out (`layouts_backplane.py`) and checked (mixer against S12 `--bus2`); PCB generated and routed (`gen_pcb_bp.py`, 100 × 100 mm, 4 layers: In1 GND, In2 +3V3 / GND; DRC clean); host port fitted, slot 1 convertible to an effects slot (backplane.md 5.1) |
| `touchsynth` | `design.py`: TouchSynth rev 0.1, for reference | `touchsynth/` (its KiCad project is on `master`) | |

| File | Role |
|---|---|
| `voice.py`, `design.py` | single source of truth per board: parts (value, footprint, LCSC, sim name), nets, sheets, groups; `voice.py` also maps its simulation netlist (S13 variant A on S10 v5c) to its nets |
| `board.py` | board selection (`BOARD`), project name, power nets, layout module |
| `lcsc.py` | picks JLCPCB basic / promotional parts for passives (voltage rating >= 2x working voltage; C0G on request) |
| `layouts_voice.py`, `layouts_backplane.py`, `layouts.py` | hand-drawn sheet layouts of the voice card, the backplane and rev 0.1; `layouts_none.py`: none (every part auto-placed, only the PWR_FLAGs drawn) |
| `draw.py` | drawing layer: geometric connectivity, auto-labels for split nets, short detection, junctions |
| `gen_sch2.py` | writes the schematic (`<board>/*.kicad_sch`) — **use this one** |
| `gen_sch.py` | v1 generator (label-only layout); its writer functions are reused by v2 |
| `check_netlist.py` | exports the KiCad netlist and compares it with the design |
| `check_sim.py` | compares the design with its ngspice netlist (nodes and values of every simulated element) |
| `gen_pcb.py` | voice card PCB (KiCad's Python): places from `pcb_place.py`, adds zones and silkscreen; `--route` adds plane vias, routes with Freerouting (`FREEROUTING_JAR`, else `tools/` or `archive/tools/freerouting-1.9.0.jar`), stitches, rips up and repairs open nets (20–30 min per pass; Freerouting's results vary between runs); `--repair`, `--finish`, `--polish` (re-route the listed analog nets), `--art` (front silk on a routed board), `--corridor` |
| `pcb_place.py` | floorplan: anchors, blocks, In2 plane polygons, edge routes (SWIO), pre-routes, polish list |
| `gen_pcb_bp.py`, `pcb_place_bp.py`, `pcb_art_bp.py` | backplane PCB (4 layers; `BP_LAYERS=2` routes the same placement on 2 as a check): generator with the locked pre-routes (+5 V trunk and rail, bus in the socket field, audio fan-out, summing band on B.Cu), GND as its own net class skipped by Freerouting; floorplan; silkscreen art (`--art` redoes it and the DNP / BOM flags on a routed board) |
| `pcb_figures.py` | layer plots and 3D renders of a board into `docs/figures/<board>_pcb/` |
| `pcb_art.py` | silkscreen, front and back |
| `pcb_gnd.py`, `pcb_maze.py` | GND island bridging, grid maze router for leftover connections |
| `fab.py` | JLCPCB gerbers, drill, BOM, CPL into `<board>/production/` (gitignored) |
| `lib/TouchSynth.pretty` | rev 0.1 touch-key footprints |

```
python gen_sch2.py && kicad-cli sch erc voice/voice.kicad_sch && python check_netlist.py && python check_sim.py
<KiCad 10>/bin/python.exe gen_pcb.py --route && kicad-cli pcb drc --schematic-parity voice/voice.kicad_pcb && python fab.py
```

The backplane (about an hour of routing; `BP_LAYERS=2` routes the same placement on two layers into
`backplane/backplane_2l.kicad_pcb`, as a check):

```
export BOARD=backplane
python gen_sch2.py && kicad-cli sch erc backplane/backplane.kicad_sch && python check_netlist.py && python check_sim.py
<KiCad 10>/bin/python.exe gen_pcb_bp.py --route && <KiCad 10>/bin/python.exe gen_pcb_bp.py --art
kicad-cli pcb drc --schematic-parity backplane/backplane.kicad_pcb && python pcb_figures.py && python fab.py
```

PCB figures for the docs (layer plots, 3D renders into `docs/figures/<board>_pcb/`): `python pcb_figures.py`.

After a schematic change, export the PDF for the docs (from the repository root):
`kicad-cli sch export pdf -o docs/schematics/<board>.pdf hw/<board>/<board>.kicad_sch`.

The rev 0.1 PCB scripts are on `master`.
