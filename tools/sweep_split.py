#!/usr/bin/env python3
"""Sweep the layer split across two GPUs and keep only the placement this host measures fast.

    .venv\\Scripts\\python.exe tools\\sweep_split.py --gpus 0,1 --long
    .venv\\Scripts\\python.exe tools\\sweep_split.py --gpus 0,1 --dry-run        (print the configs, bench nothing)

Every variant is the SAME config (same model, same args) with only the GPU placement changed, benched by
tools/strata_bench.py (3 runs per test, medians) into the usual bench/results/<date>-community-.../ folder.
Reads docs/MULTI_GPU.md: on an unequal pair, sweep layer_split once; on an x16 + x4 rig the auto placement can
move off the balanced split, so STRATA_SPLIT_UNIFORM=1 with "gpu_order": "as_given" is a variant too.

Run it AFTER the second card is in, and with NO server already listening on the config's port - strata_bench
would otherwise bench the server that is already running instead of the variant.  The script refuses when the
port is busy.  Standard library only.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWEEP = ROOT / "bench" / "sweep"
RESULTS = ROOT / "bench" / "results"


# ----------------------------------------------------------------------------------------------- gpu discovery
def gpus() -> list[dict]:
    """nvidia-smi -> [{index, name, total_mib}].  The indices are what "gpu" in the config means."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"  nvidia-smi did not run: {e}")
        return []
    rows = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            rows.append({"index": int(parts[0]), "name": parts[1], "total_mib": int(parts[2])})
    return rows


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_free(port: int, seconds: int = 180) -> bool:
    """A server strata_bench started takes a while to close; wait instead of benching the wrong thing."""
    end = time.time() + seconds
    while time.time() < end:
        if not port_busy(port):
            return True
        time.sleep(3)
    return False


# ------------------------------------------------------------------------------------------------- variants
def variant(base: dict, label: str, gpu: list[int], split, order: str | None,
            uniform: bool, later_reserve: int | None) -> dict:
    cfg = copy.deepcopy(base)
    cfg["gpu"] = gpu
    cfg["gpus_asked"] = True
    cfg.pop("layer_split", None)
    cfg.pop("gpu_order", None)
    if len(gpu) > 1:
        cfg["layer_split"] = "auto" if split is None else str(split)
        if order:
            cfg["gpu_order"] = order
        if uniform:
            cfg.setdefault("env", {})["STRATA_SPLIT_UNIFORM"] = "1"
        if later_reserve is not None:
            args = list(cfg.get("args", []))
            if "--vram-reserve-later-mib" not in args:
                args += ["--vram-reserve-later-mib", str(later_reserve)]
            cfg["args"] = args
    return {"label": label, "cfg": cfg}


def build_variants(base: dict, gpu: list[int], single: int | None, k_min: int, k_max: int,
                   k_step: int, uniform: bool, later_reserve: int | None) -> list[dict]:
    out: list[dict] = []
    if single is not None:
        out.append(variant(base, f"single-{single}", [single], None, None, False, None))
    out.append(variant(base, "auto", gpu, None, None, False, later_reserve))
    out.append(variant(base, "auto-as-given", gpu, None, "as_given", False, later_reserve))
    if uniform:
        out.append(variant(base, "auto-uniform", gpu, None, "as_given", True, later_reserve))
    for k in range(k_min, k_max + 1, k_step):
        out.append(variant(base, f"split-{k}", gpu, k, "as_given", False, later_reserve))
    return out


# --------------------------------------------------------------------------------------------------- benching
def run_bench(cfg_path: Path, long: bool) -> tuple[int, Path | None]:
    before = {p for p in RESULTS.glob("*") if p.is_dir()}
    cmd = [sys.executable, str(ROOT / "tools" / "strata_bench.py"), "--config", str(cfg_path)]
    if long:
        cmd.append("--long")
    rc = subprocess.run(cmd).returncode
    after = {p for p in RESULTS.glob("*") if p.is_dir()} - before
    return rc, (max(after, key=lambda p: p.stat().st_mtime) if after else None)


def medians(path: Path) -> dict[str, float]:
    """Any {"median": ...} leaf in results.json, keyed by its path in the document.  Tolerant of the schema."""
    found: dict[str, float] = {}

    def walk(node, prefix):
        if isinstance(node, dict):
            if "median" in node and isinstance(node["median"], (int, float)):
                found[prefix] = float(node["median"])
            else:
                for k, v in node.items():
                    walk(v, f"{prefix}/{k}" if prefix else k)

    try:
        walk(json.loads(path.read_text(encoding="utf-8")), "")
    except (OSError, ValueError):
        pass
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="sweep the two-GPU layer split on this host")
    ap.add_argument("--base", default="strata-iq3_xxs.json", help="the config to copy (default the daily driver)")
    ap.add_argument("--gpus", required=True, help="the two GPU indices from nvidia-smi, e.g. 0,1")
    ap.add_argument("--single", type=int, default=None, help="also bench this one card alone as the baseline")
    ap.add_argument("--k-min", type=int, default=8, help="first layer of the second card, sweep start")
    ap.add_argument("--k-max", type=int, default=48, help="sweep end (a K past the model's last layer is refused)")
    ap.add_argument("--k-step", type=int, default=8)
    ap.add_argument("--later-reserve", type=int, default=512,
                    help="--vram-reserve-later-mib for the card driving no monitors (0 = leave it out)")
    ap.add_argument("--uniform", action="store_true", help="also try STRATA_SPLIT_UNIFORM=1 (x16 + x4 rigs)")
    ap.add_argument("--long", action="store_true", help="bench at 32K too (slower, and the split matters most there)")
    ap.add_argument("--dry-run", action="store_true", help="write the variant configs, bench nothing")
    a = ap.parse_args()

    base_path = (ROOT / a.base) if not Path(a.base).is_absolute() else Path(a.base)
    if not base_path.exists():
        print(f"  no config at {base_path}")
        return 1
    base = json.loads(base_path.read_text(encoding="utf-8"))
    port = int(base.get("port", 8080))
    gpu = [int(x) for x in a.gpus.split(",") if x.strip() != ""]
    if len(gpu) < 2:
        print('  --gpus needs two indices, e.g. --gpus 0,1')
        return 1

    print("\nGPUs on this host (nvidia-smi):")
    for g in gpus():
        print(f"  {g['index']}: {g['name']}  {g['total_mib']} MiB")
    print(f"\nbase config {base_path.name}: model {base.get('model')}, port {port}, "
          f"max-context {base.get('args', [])[base['args'].index('--max-context') + 1] if '--max-context' in base.get('args', []) else '?'}\n")

    variants = build_variants(base, gpu, a.single, a.k_min, a.k_max, a.k_step,
                              a.uniform, (a.later_reserve or None))
    SWEEP.mkdir(parents=True, exist_ok=True)

    if a.dry_run:
        for v in variants:
            p = SWEEP / f"strata-{v['label']}.json"
            p.write_text(json.dumps(v["cfg"], indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"  wrote {p.relative_to(ROOT)}  gpu={v['cfg'].get('gpu')} "
                  f"layer_split={v['cfg'].get('layer_split', '-')} gpu_order={v['cfg'].get('gpu_order', '-')}")
        print("\n  dry run only: nothing benched.")
        return 0

    table: list[tuple[str, dict[str, float], Path | None]] = []
    for v in variants:
        cfg_path = SWEEP / f"strata-{v['label']}.json"
        cfg_path.write_text(json.dumps(v["cfg"], indent=1, ensure_ascii=False), encoding="utf-8")
        if port_busy(port):
            print(f"\n  port {port} is still answering - a server is running. Stop it before sweeping, "
                  f"or this run would measure that server instead of {v['label']}.")
            return 2
        print(f"\n=== {v['label']}: gpu={v['cfg']['gpu']} layer_split={v['cfg'].get('layer_split', '-')} "
              f"gpu_order={v['cfg'].get('gpu_order', '-')}")
        rc, folder = run_bench(cfg_path, a.long)
        if rc != 0:
            print(f"  {v['label']} did not bench (rc {rc}) - a layer_split past the model's last layer is "
                  f"refused, so a failure here can end the K sweep.")
            continue
        table.append((v["label"], medians(folder / "results.json") if folder else {}, folder))
        wait_free(port)

    print("\n\n================ sweep summary (medians) ================")
    keys: list[str] = []
    for _, m, _ in table:
        for k in m:
            if k not in keys:
                keys.append(k)
    print(f"{'variant':18s} " + " ".join(f"{k.split('/')[-1]:>14s}" for k in keys))
    for label, m, _ in table:
        print(f"{label:18s} " + " ".join(f"{m.get(k, float('nan')):>14.1f}" for k in keys))
    print("\nFolders (each with README.md and results.json):")
    for label, _, folder in table:
        if folder:
            print(f"  {label:18s} {folder.relative_to(ROOT)}")
    if table and table[0][2]:
        best = table[0][2]
        print(f"\nCompare any two the way the repo does it, e.g.:  BENCH.bat --long --compare {best.relative_to(ROOT)}")
    print("Keep the winner: copy the winning bench/sweep/strata-<label>.json over strata-iq3_xxs.json "
          "(or point run-iq3_xxs.bat at it), and save the raw runs under bench/results/<date>-aryastrata-3090-split/ "
          "per AGENTS.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
