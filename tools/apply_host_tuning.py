#!/usr/bin/env python3
"""Write this host's tuned run configs (docs/host-tuning) into an install, filling in the two placeholders.

    python tools/apply_host_tuning.py --install C:\\AryaInfer --data C:\\AI\\Strata-data
    python tools/apply_host_tuning.py --install C:\\AryaInfer --data C:\\AI\\Strata-data --dry-run

The copies carry "$INSTALL" where the clone lives and "$DATA" where setup keeps the models, packs and MTP layer, so
no machine's paths are in the repository.  A run config the install already has (strata-<model>.json) is replaced,
and the earlier one is kept beside it as <name>.bak-host-tuning.  The files are written with json, so a Windows path's
backslashes end up escaped correctly.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "host-tuning"


def fill(value, install: str, data: str):
    """Every string with the two placeholders replaced; lists and objects walked."""
    if isinstance(value, str):
        return value.replace("$INSTALL", install).replace("$DATA", data)
    if isinstance(value, list):
        return [fill(v, install, data) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, install, data) for k, v in value.items()}
    return value


def configs() -> list[Path]:
    return sorted(SRC.glob("strata-*.json"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="write the tuned run configs into an install")
    ap.add_argument("--install", required=True, help="the folder the repository is cloned into")
    ap.add_argument("--data", required=True, help="setup's data folder: models, packs and the MTP layer")
    ap.add_argument("--dry-run", action="store_true", help="say what would be written, change nothing")
    a = ap.parse_args(argv)
    dest = Path(a.install)
    if not dest.is_dir():
        sys.exit(f"[host-tuning] {dest} is not a folder")
    todo = configs()
    if not todo:
        sys.exit(f"[host-tuning] no run configs in {SRC}")
    for src in todo:
        cfg = fill(json.loads(src.read_text(encoding="utf-8")), a.install, a.data)
        target = dest / src.name
        print(f"{'(dry run) ' if a.dry_run else ''}{target}")
        if a.dry_run:
            continue
        if target.exists():
            shutil.copyfile(target, target.with_name(target.name + ".bak-host-tuning"))
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(cfg, indent=1, ensure_ascii=False) + "\n")
        log = cfg.get("log")
        if isinstance(log, str) and log:
            # the engine opens its log before it loads anything, and a fresh clone has no local-data folder
            Path(log).parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(todo)} run config{'s' * (len(todo) != 1)} {'checked' if a.dry_run else 'written'}; "
          "start the server as usual")
    return 0


if __name__ == "__main__":
    sys.exit(main())
