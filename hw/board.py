"""Board selection for the generator and check scripts: BOARD=voice (default) or BOARD=touchsynth (rev 0.1,
design.py, kept for reference; its KiCad project is on master).

Each design module provides PARTS, SHEETS, nets() and optionally PROJECT, TITLE, REV, POWER (net -> power
symbol), RAIL (a net always drawn as a global label), LAYOUTS (module with hand-drawn sheet layouts).
"""
import importlib, os

NAME = os.environ.get("BOARD", "voice")
D = importlib.import_module({"voice": "voice", "touchsynth": "design"}[NAME])
PROJECT = getattr(D, "PROJECT", "touchsynth")
TITLE = getattr(D, "TITLE", "TouchSynth")
REV = getattr(D, "REV", "0.1")
POWER = getattr(D, "POWER", {"GND": "power:GND", "+5V": "power:+5V"})
RAIL = getattr(D, "RAIL", "VP")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), PROJECT)
LAYOUTS = importlib.import_module(getattr(D, "LAYOUTS", "layouts" if NAME == "touchsynth" else "layouts_none"))
