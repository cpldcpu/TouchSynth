"""Tiny helper: run ngspice (WSL) in batch mode and load `wrdata` output."""
import os
import subprocess
import numpy as np

SIM_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(SIM_ROOT, "models", "models.lib")


def wsl_path(p):
    p = os.path.abspath(p).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def run(netlist_text, workdir, name, timeout=3600):
    """Write <name>.cir into workdir, run ngspice -b, return stdout log."""
    os.makedirs(workdir, exist_ok=True)
    text = netlist_text.replace("{MODELS}", wsl_path(MODELS)).replace("{OUT}", wsl_path(workdir))
    cir = os.path.join(workdir, name + ".cir")
    with open(cir, "w", newline="\n") as f:
        f.write(text)
    cmd = ["wsl", "-e", "bash", "-lc", f"cd '{wsl_path(workdir)}' && ngspice -b '{name}.cir' 2>&1"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    log = res.stdout
    with open(os.path.join(workdir, name + ".log"), "w", newline="\n") as f:
        f.write(log)
    low = log.lower()
    bad = ("bail out", "error on line", "simulation interrupted", "fatal", "no such", "cannot", "singular",
           "timestep too small")
    if any(b in low for b in bad):
        raise RuntimeError(f"ngspice failed for {name}:\n{log[-3000:]}")
    return log


def load(path):
    """Load a wrdata file written with wr_singlescale + wr_vecnames. Returns dict of arrays."""
    with open(path) as f:
        header = f.readline().split()
    data = np.loadtxt(path, skiprows=1, ndmin=2)
    return {h: data[:, i] for i, h in enumerate(header)}


PREAMBLE = """
.include {MODELS}
.options savecurrents=0
"""

CTRL_HEAD = """
.control
set wr_singlescale
set wr_vecnames
set filetype=ascii
option numdgt=7
"""
