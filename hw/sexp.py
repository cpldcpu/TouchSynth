"""Minimal S-expression reader/writer for KiCad files, plus symbol-library helpers."""
import os, re, shutil

def _kicad():
    """(install folder or None, shared library folder) of KiCad 10: KICAD_DIR (the install folder) if set, else
    the standard install locations (Windows per-user / system-wide, Linux, macOS)."""
    roots = [os.environ.get("KICAD_DIR"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "KiCad", "10.0"),
             os.path.join(os.environ.get("ProgramFiles", ""), "KiCad", "10.0")]
    for r in filter(None, roots):
        if os.path.isdir(os.path.join(r, "share", "kicad", "symbols")):
            return r, os.path.join(r, "share", "kicad")
    for share in ("/usr/share/kicad", "/usr/local/share/kicad",
                  "/Applications/KiCad/KiCad.app/Contents/SharedSupport"):
        if os.path.isdir(os.path.join(share, "symbols")):
            return None, share
    raise SystemExit("KiCad 10 libraries not found: set KICAD_DIR to the KiCad install folder")


KICAD, KICAD_SHARE = _kicad()
SYMDIR = os.path.join(KICAD_SHARE, "symbols")
FPDIR = os.path.join(KICAD_SHARE, "footprints")
_cli = os.path.join(KICAD, "bin", "kicad-cli.exe") if KICAD else None
KICAD_CLI = _cli if _cli and os.path.exists(_cli) else (shutil.which("kicad-cli") or "kicad-cli")

_tok = re.compile(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+')


class Q(str):
    """A quoted string atom (kept quoted when written back)."""


def parse(text):
    stack, cur = [], []
    for m in _tok.finditer(text):
        t = m.group(0)
        if t == "(":
            stack.append(cur); cur = []
        elif t == ")":
            done = cur; cur = stack.pop(); cur.append(done)
        elif t.startswith('"'):
            cur.append(Q(t[1:-1].replace('\\"', '"').replace("\\\\", "\\")))
        else:
            cur.append(t)
    return cur[0]


def dump(x, ind=0):
    if isinstance(x, list):
        if not x:
            return "()"
        head = x[0]
        simple = all(not isinstance(e, list) for e in x)
        if simple:
            return "(" + " ".join(dump(e) for e in x) + ")"
        s = "(" + dump(head)
        for e in x[1:]:
            if isinstance(e, list):
                s += "\n" + "\t" * (ind + 1) + dump(e, ind + 1)
            else:
                s += " " + dump(e)
        return s + "\n" + "\t" * ind + ")"
    if isinstance(x, Q):
        return '"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(x)


def find(x, key):
    return [e for e in x if isinstance(e, list) and e and e[0] == key]


def find1(x, key):
    r = find(x, key)
    return r[0] if r else None


_libcache = {}


def load_lib(lib):
    if lib not in _libcache:
        with open(os.path.join(SYMDIR, lib + ".kicad_sym"), encoding="utf-8") as fh:
            _libcache[lib] = parse(fh.read())
    return _libcache[lib]


def get_symbol(lib_id):
    """Return the flattened symbol (extends resolved) named 'lib:name' as a list, name set to lib_id."""
    lib, name = lib_id.split(":")
    L = load_lib(lib)
    syms = {s[1]: s for s in find(L, "symbol")}
    s = syms[name]
    ext = find1(s, "extends")
    if ext:
        parent = get_symbol(f"{lib}:{ext[1]}")
        pname = ext[1]
        props = {p[1]: p for p in find(s, "property")}
        out = [e for e in parent if not (isinstance(e, list) and e and e[0] == "property" and e[1] in props)]
        out = [e for e in out if not (isinstance(e, list) and e and e[0] == "symbol")]
        out = out[:2] + [props[k] for k in props] + out[2:]
        for sub in find(parent, "symbol"):
            sub = list(sub)
            sub[1] = Q(sub[1].replace(pname, name, 1))
            out.append(sub)
        for e in s:
            if isinstance(e, list) and e and e[0] in ("in_bom", "on_board", "exclude_from_sim") :
                out = [x for x in out if not (isinstance(x, list) and x and x[0] == e[0])] + [e]
        s = out
    s = list(s)
    s[1] = Q(lib_id)
    return s


def pins(sym):
    """[(unit, number, name, x, y, angle, length, etype)] from a flattened symbol (lib coordinates, y up)."""
    out = []
    for sub in find(sym, "symbol"):
        m = re.match(r".*_(\d+)_(\d+)$", sub[1])
        unit = int(m.group(1)) if m else 0
        for p in find(sub, "pin"):
            at = find1(p, "at"); ln = find1(p, "length")
            num = find1(p, "number")[1]; nm = find1(p, "name")[1]
            hidden = "hide" in p or any(isinstance(e, list) and e[:2] == ["hide", "yes"] for e in p)
            out.append((unit, str(num), str(nm), float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0,
                        float(ln[1]) if ln else 2.54, p[1], hidden))
    return out


def units(sym):
    n = 1
    for sub in find(sym, "symbol"):
        m = re.match(r".*_(\d+)_(\d+)$", sub[1])
        if m:
            n = max(n, int(m.group(1)))
    return n


def bbox(sym, unit):
    """Rough body bounding box in lib coordinates for a unit (graphics + pins)."""
    xs, ys = [], []
    for sub in find(sym, "symbol"):
        m = re.match(r".*_(\d+)_(\d+)$", sub[1])
        u = int(m.group(1)) if m else 0
        if u not in (0, unit):
            continue
        for g in sub:
            if not isinstance(g, list):
                continue
            for e in g:
                if isinstance(e, list) and e and e[0] in ("start", "end", "center", "at", "xy"):
                    try:
                        xs.append(float(e[1])); ys.append(float(e[2]))
                    except (ValueError, IndexError):
                        pass
                if isinstance(e, list) and e and e[0] == "pts":
                    for xy in find(e, "xy"):
                        xs.append(float(xy[1])); ys.append(float(xy[2]))
    if not xs:
        return (-2.54, -2.54, 2.54, 2.54)
    return (min(xs), min(ys), max(xs), max(ys))
