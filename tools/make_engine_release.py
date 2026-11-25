#!/usr/bin/env python3
"""Package the fork's Windows x64 CUDA 13 `aryainfer` engine for `engines.json`.

The upstream Strata and PolyStrata engines are published by their own projects.  AryaInfer's
`aryainfer` target is this fork's build of the pinned PolyStrata sources, so its binary has no
upstream release to point at.  This script takes the portable build in `build-arya/`, adds the
cuBLAS DLLs the executable loads, writes the BUILD.json that setup and the server read, and makes
the zip pinned by the `arya` entry in `engines.json`.

Typical use, from the repository root after a portable build:

    python tools/make_engine_release.py
    python tools/make_engine_release.py --publish

`--publish` needs GitHub CLI login for KonnectSuite/AryaInfer.  It uploads the zip and the
BUILD.json to the `engines-2026.11` release; the release and the `engines.json` hash stay under
the maintainer's control (this script only prints the values to fill in, unless --update-manifest
is given).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RELEASE = "engines-2026.11"
DEFAULT_VERSION = "0.1.45"
ARCHS = [75, 80, 86, 89, 120]
DLLS = ("cublas64_13.dll", "cublasLt64_13.dll")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(16 << 20), b""):
            h.update(block)
    return h.hexdigest()


def default_cuda() -> Path:
    env = os.environ.get("STRATA_CUDA_DIR") or os.environ.get("CUDA_PATH")
    if env:
        return Path(env)
    # The maintainer's toolkit, when no CUDA_PATH is set.
    return Path(r"C:\AI\Strata-data\cuda\13.1.2")


def find_toolkit_dlls(cuda: Path) -> dict[str, Path]:
    """The cuBLAS DLLs the executable loads, from a CUDA toolkit's bin folders.

    CUDA 13 puts the redistributables in bin/x64 and the legacy names in bin; try both so a
    normal `CUDA_PATH` install and the maintainer's layout both work.
    """
    found: dict[str, Path] = {}
    for name in DLLS:
        for folder in (cuda / "bin" / "x64", cuda / "bin"):
            p = folder / name
            if p.is_file():
                found[name] = p
                break
        else:
            raise SystemExit(f"missing {name} under {cuda}; pass --cuda <toolkit>")
    return found


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def package(args) -> Path:
    build = Path(args.build_dir)
    exe = build / "aryainfer.exe"
    if not exe.is_file():
        raise SystemExit(
            f"no {exe}; build it first:\n"
            f"  cmake -S . -B {build} -G Ninja -DSTRATA_ENABLE_CUDA=ON "
            f"-DSTRATA_PORTABLE=ON -DSTRATA_BUILD_TESTS=OFF "
            f"-DCMAKE_CUDA_ARCHITECTURES={';'.join(map(str, ARCHS))}\n"
            f"  cmake --build {build} --target aryainfer --parallel"
        )
    dlls = find_toolkit_dlls(Path(args.cuda))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"aryainfer-windows-x64-cuda13.zip"
    if archive.exists():
        archive.unlink()

    with tempfile.TemporaryDirectory(prefix="arya-release-") as tmp:
        stage = Path(tmp) / "engine"
        stage.mkdir()
        shutil.copy2(exe, stage / "aryainfer.exe")
        for p in dlls.values():
            shutil.copy2(p, stage / p.name)
        meta = {
            "version": args.version,
            "source": "fork-release",
            "binary": "aryainfer.exe",
            "archs": ARCHS,
            "cuda": "13.0",
            "ptx": False,
            "lib_dirs": [],
            "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "commit": git_commit(),
        }
        (stage / "BUILD.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
        # Keep BUILD.json first, then the executable, so a human opening the zip sees what it is.
        order = ["BUILD.json", "aryainfer.exe", *DLLS]
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for name in order:
                z.write(stage / name, arcname=name)
    return archive


def write_checksum(archive: Path) -> Path:
    digest = sha256(archive)
    side = archive.with_suffix(archive.suffix + ".sha256")
    side.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    return side


def update_manifest(archive: Path, release: str) -> None:
    """Fill the `arya` entry with the published asset, size and hash (after the upload)."""
    path = ROOT / "engines.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rec = data["engines"]["arya"]
    asset = archive.name
    rec.pop("pending", None)
    rec["assets"] = {
        "windows-cuda13": {
            "url": f"https://github.com/KonnectSuite/AryaInfer/releases/download/{release}/{asset}",
            "asset": asset,
            "size": archive.stat().st_size,
            "sha256": sha256(archive),
        }
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def publish(archive: Path, release: str) -> None:
    gh = shutil.which("gh")
    if not gh:
        raise SystemExit("--publish needs GitHub CLI (gh) on PATH")
    view = subprocess.run([gh, "release", "view", release], cwd=ROOT, capture_output=True, text=True)
    if view.returncode != 0:
        subprocess.run(
            [gh, "release", "create", release,
             "--title", f"AryaInfer engines {release}",
             "--notes", "AryaInfer `aryainfer` engine (portable Windows x64, CUDA 13). "
                        "The upstream Strata and PolyStrata engines are published by their own projects."],
            cwd=ROOT, check=True,
        )
    subprocess.run([gh, "release", "upload", release, str(archive), "--clobber"], cwd=ROOT, check=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build-dir", default=str(ROOT / "build-arya"),
                    help="folder holding aryainfer.exe (default: build-arya)")
    ap.add_argument("--cuda", default=str(default_cuda()), help="CUDA toolkit with cuBLAS DLLs")
    ap.add_argument("--version", default=DEFAULT_VERSION, help="engine version in BUILD.json")
    ap.add_argument("--release", default=DEFAULT_RELEASE, help="GitHub release tag")
    ap.add_argument("--out", default=str(ROOT / "dist" / DEFAULT_RELEASE),
                    help="folder for the zip (default: dist/engines-2026.11)")
    ap.add_argument("--publish", action="store_true", help="upload to the GitHub release")
    ap.add_argument("--update-manifest", action="store_true",
                    help="write the published size/hash into engines.json (after upload)")
    args = ap.parse_args(argv)

    archive = package(args)
    side = write_checksum(archive)
    size = archive.stat().st_size
    digest = sha256(archive)
    print(f"archive: {archive}")
    print(f"size:    {size:,} bytes")
    print(f"sha256:  {digest}")
    print(f"sums:    {side}")
    print()
    print("Pin it in engines.json (or rerun with --update-manifest after publishing):")
    print(f'  "size": {size},')
    print(f'  "sha256": "{digest}"')
    if args.publish:
        publish(archive, args.release)
        print(f"published: https://github.com/KonnectSuite/AryaInfer/releases/tag/{args.release}")
        if args.update_manifest:
            update_manifest(archive, args.release)
            print("engines.json updated")
    elif args.update_manifest:
        print("not updated: --update-manifest needs --publish (the URL must exist first)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
