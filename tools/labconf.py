"""Lab-specific settings (hosts, paths) for the bench tools, kept out of git.

Values come from the environment first, then from lab.conf next to this file (copy lab.conf.example and edit;
lab.conf is gitignored). The file holds KEY=VALUE lines, so record_parts.sh can source it as well.
"""
import os

_CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lab.conf")
_cache = None


def _load():
    global _cache
    if _cache is None:
        _cache = {}
        if os.path.exists(_CONF):
            for line in open(_CONF, encoding="utf-8"):
                line = line.split("#", 1)[0].strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    _cache[k.strip()] = v.strip().strip("'\"")
    return _cache


def get(key, default=None):
    """Setting `key`: environment, then lab.conf, then default; a missing setting without default is an error."""
    v = os.environ.get(key) or _load().get(key) or default
    if v is None:
        raise SystemExit(f"{key} is not set: copy tools/lab.conf.example to tools/lab.conf and fill it in "
                         f"(or set the environment variable {key})")
    return v
