"""serve/engines.py - the engines the installer knows, and which of them are installed.

The Engines view reads this (GET /api/engines): one entry per engine of engines.json, its pinned version and
upstream release, and its installed state read from the engine's BUILD.json beside its binary.  Nothing here
downloads or builds an engine - repair is a separate, opt-in server action that runs setup.py.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "engines.json"


def _parts(v) -> list:
    import re
    return re.split(r"[^0-9]+", str(v).strip())


def version_tuple(v) -> tuple:
    """(0, 1, 67) from '0.1.67' or '0.1.45-poly.9' (the suffix is dropped for comparisons)."""
    return tuple(int(x) for x in _parts(v) if x.isdigit())


def manifest() -> dict:
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"schema": 1, "release": None, "engines": {}}
    return data if isinstance(data, dict) else {"schema": 1, "release": None, "engines": {}}


def _build_json(install_dir: Path) -> dict | None:
    f = install_dir / "BUILD.json"
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _installed(install_dir: Path, binary: str) -> dict:
    """{status, installed_version, archs, cuda, source, core, core_commit} for one install dir."""
    build = _build_json(install_dir)
    exe = install_dir / binary
    if not exe.is_file():
        # the binary is the truth of "installed"; BUILD.json alone (e.g. after a failed install) is not an engine
        return {"status": "missing", "installed_version": None, "archs": None, "cuda": None,
                "source": None, "core": None, "core_commit": None}
    if build is None or not build.get("version"):
        return {"status": "unknown", "installed_version": None, "archs": build.get("archs") if build else None,
                "cuda": build.get("cuda") if build else None, "source": build.get("source") if build else None,
                "core": None, "core_commit": None}
    return {"status": "installed", "installed_version": str(build["version"]),
            "archs": build.get("archs"), "cuda": build.get("cuda"),
            "source": build.get("source"), "core": build.get("core"), "core_commit": build.get("core_commit")}


def inventory(root: Path = ROOT) -> list[dict]:
    """The Engines view's list: every engine of engines.json with its manifest facts and installed state."""
    data = manifest()
    engines = data.get("engines") or {}
    out = []
    for key, rec in engines.items():
        if not isinstance(rec, dict):
            continue
        binary = str(rec.get("binary") or "")
        d = str(rec.get("dir") or f"engine-{key}")
        install_dir = Path(root) / d
        state = _installed(install_dir, binary)
        manual = bool(rec.get("manual"))
        min_v = str(rec.get("min_version") or rec.get("version") or "")
        entry = {
            "key": key,
            "title": rec.get("title") or key,
            "binary": binary,
            "dir": d,
            "required": bool(rec.get("required")),
            "manual": manual,
            "version": str(rec.get("version") or ""),       # the pinned version
            "min_version": min_v,
            "upstream": rec.get("upstream") or "",
            "release": rec.get("release") or "",
            "assets": {k: {"asset": v.get("asset"), "size": v.get("size"), "sha256": v.get("sha256")}
                       for k, v in (rec.get("assets") or {}).items() if isinstance(v, dict)},
            **state,
        }
        # status: manual engines are installed by hand (never auto-downloaded); the rest are current / outdated /
        # missing / unknown by comparing the installed BUILD.json version to the pinned minimum.
        if state["status"] == "missing":
            entry["status"] = "missing"
        elif state["status"] == "unknown":
            entry["status"] = "unknown"
        elif manual:
            entry["status"] = "manual" if state["status"] == "installed" else "missing"
        elif state["status"] == "installed":
            installed = version_tuple(state["installed_version"])
            minimum = version_tuple(min_v)
            entry["status"] = "outdated" if (minimum and installed < minimum) else "current"
        out.append(entry)
    # a stable order the page can rely on: required first, then by key
    return sorted(out, key=lambda e: (not e["required"], e["key"]))


def as_view(root: Path = ROOT) -> dict:
    data = manifest()
    return {"release": data.get("release"), "updated": data.get("updated"),
            "engines": inventory(root)}


if __name__ == "__main__":
    import sys
    for e in inventory():
        mark = {"current": " ", "outdated": "!", "missing": "-", "manual": "m", "unknown": "?"}[e["status"]]
        extra = f" ({e['installed_version']})" if e["installed_version"] else ""
        print(f"{mark} {e['key']:8s} {e['version']:8s}{extra:10s} required={e['required']} manual={e['manual']}")
    sys.exit(0)
