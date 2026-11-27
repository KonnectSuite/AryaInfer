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


def manifest(root: Path | None = None) -> dict:
    """engines.json as the installer reads it.  `root` defaults to this checkout, so a test can point it elsewhere."""
    path = (Path(root) if root is not None else ROOT) / "engines.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
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


TRACKED = r"^strata-.+\.json$"
BACKUP = ".control-center-backup-"


def _custom(root: Path, claimed: list[tuple], taken: set[str]) -> list[dict]:
    r"""Engines a run config points at that engines.json does not pin.

    A `.basalt` model (or any other binary a person points a run config at) is not in the manifest: nothing installs
    it, no release is pinned, and repair leaves it alone.  Leaving it off this page would describe a checkout that is
    not the one running, so it gets a card of its own - its own build, with what a BUILD.json beside it says, if
    anything.  `claimed` holds the (resolved parent, binary name) of the manifest engines so one binary is not
    reported twice, and `taken` holds their keys so a config that runs the same engine out of another folder (an
    absolute `C:\...\engines\strata-0.1.67\strata.exe`, say) gets a key of its own instead of a second card the page
    cannot tell apart.
    """
    import re
    out = []
    for cfg_path in sorted(root.glob("strata-*.json")):
        if BACKUP in cfg_path.name or not re.match(TRACKED, cfg_path.name):
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        exe = str(cfg.get("exe") or "") if isinstance(cfg, dict) else ""
        if not exe:
            continue
        p = Path(exe)
        if not p.is_absolute():
            p = Path(cfg.get("cwd") or root) / p
        try:
            resolved = p.resolve()
            parent = resolved.parent
        except OSError:
            resolved, parent = p, p.parent
        if any(parent == owner and p.name.lower() == name for owner, name in claimed):
            continue
        if any(entry["binary"].lower() == p.name.lower() for entry in out):
            continue
        build = _build_json(parent) or _build_json(parent.parent)
        exists = p.is_file()
        key = resolved.stem.lower()
        if key in taken or any(entry["key"] == key for entry in out):
            # same engine name out of another folder: name the folder, so `strata` stays the pinned card and
            # `strata-0.1.67` is the build a run config actually starts
            folder = parent.name.lower()
            key = folder if folder.startswith(key) and folder != key else f"{key}-{folder}"
        out.append({
            "key": key,
            "title": resolved.stem.replace("-", " ").replace("_", " ").title(),
            "binary": p.name,
            "dir": str(parent),
            "path": str(resolved),
            "required": False,
            "manual": True,
            "custom": True,
            "version": "",
            "min_version": "",
            "upstream": "",
            "release": "",
            "assets": {},
            "status": "custom" if exists else "missing",
            "installed_version": str(build["version"]) if build and build.get("version") else "",
            "archs": build.get("archs") if build else None,
            "cuda": build.get("cuda") if build else None,
            "source": build.get("source") if build else None,
            "core": None,
            "core_commit": None,
        })
    return out


def inventory(root: Path = ROOT) -> list[dict]:
    """The Engines view's list: every engine of engines.json with its manifest facts and installed state."""
    data = manifest(root)
    engines = data.get("engines") or {}
    out = []
    claimed = []                    # (resolved install dir, binary name) of the manifest engines, for _custom()
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
        claimed.append((install_dir.resolve(), binary.lower()))
        out.append(entry)
    out.extend(_custom(Path(root), claimed, {str(k) for k in engines}))
    # a stable order the page can rely on: required first, then the pinned engines by key, then a person's own builds
    return sorted(out, key=lambda e: (not e["required"], bool(e.get("custom")), e["key"]))


def as_view(root: Path = ROOT) -> dict:
    data = manifest(root)
    return {"release": data.get("release"), "updated": data.get("updated"),
            "engines": inventory(root)}


if __name__ == "__main__":
    import sys
    for e in inventory():
        mark = {"current": " ", "outdated": "!", "missing": "-", "manual": "m", "unknown": "?"}[e["status"]]
        extra = f" ({e['installed_version']})" if e["installed_version"] else ""
        print(f"{mark} {e['key']:8s} {e['version']:8s}{extra:10s} required={e['required']} manual={e['manual']}")
    sys.exit(0)
