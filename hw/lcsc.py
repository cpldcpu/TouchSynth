"""Pick JLCPCB basic / promotional-extended parts for passives from the extracted parts list."""
import os, csv, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_rows = list(csv.DictReader(open(os.path.join(ROOT, "parts", "jlcpcb_basic_and_promotional_parts.csv"),
                                 encoding="utf-8")))


def _attrs(r):
    return dict(x.split("=", 1) for x in r["attributes"].split("; ") if "=" in x)


def _volts(s):
    m = re.match(r"([\d.]+)\s*(k?)V", s or "")
    return float(m.group(1)) * (1000 if m.group(2) else 1) if m else 0.0


def r_value_str(v):
    """'4.7k' -> '4.7kΩ', '1M' -> '1MΩ', '10' -> '10Ω'"""
    return v + "Ω"


def pick_r(value, pkg="0603"):
    want = r_value_str(value)
    c = [r for r in _rows if r["subcategory"] == "Chip Resistor - Surface Mount" and r["package"] == pkg
         and _attrs(r).get("Resistance") == want]
    c.sort(key=lambda r: (r["library"] != "basic", -int(r["stock"] or 0)))
    if not c:
        raise KeyError(f"no {pkg} resistor {value}")
    return c[0]["lcsc"], pkg


def pick_c(value, vmin, pkgs=("0603", "0805", "1206")):
    """value like '100n', '4.7u'; vmin = minimum voltage rating (use >= 2x working voltage)."""
    want = value.replace("u", "uF").replace("n", "nF").replace("p", "pF")
    for pkg in pkgs:
        c = [r for r in _rows if r["subcategory"].startswith("Multilayer") and r["package"] == pkg
             and _attrs(r).get("Capacitance") == want and _volts(_attrs(r).get("Voltage Rating")) >= vmin]
        c.sort(key=lambda r: (r["library"] != "basic", -int(r["stock"] or 0)))
        if c:
            return c[0]["lcsc"], pkg
    raise KeyError(f"no capacitor {value} >= {vmin} V")


def info(lcsc):
    r = [r for r in _rows if r["lcsc"] == lcsc]
    return r[0] if r else None
