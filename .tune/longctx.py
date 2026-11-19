"""Does a full-context read actually work on this host? Measure it, at the sizes a coding agent uses.

Loads the engine with the config under test, then feeds prompts of the requested token counts and
reports prefill time, first-token latency, decode rate and the host memory situation during the read.
"""
from __future__ import annotations

import ctypes
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # repository root (this file lives in .tune/)
sys.path.insert(0, str(ROOT / ".tune"))

import bench                                              # noqa: E402
from strata_tokenizer import Tokenizer                    # noqa: E402


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def commit() -> tuple[float, float]:
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return st.ullTotalPageFile / 2**30, st.ullAvailPageFile / 2**30


def build_doc(tok, n: int) -> list[int]:
    """A coding-agent-shaped prompt: real repository prose plus source, ~n tokens."""
    parts = []
    for p in sorted((ROOT / "docs").glob("*.md")):
        parts.append(p.read_text(encoding="utf-8", errors="replace"))
    for p in sorted((ROOT / "src" / "core").glob("*.cpp"))[:40]:
        parts.append(p.read_text(encoding="utf-8", errors="replace"))
    body = tok.encode("\n\n".join(parts), parse_special=False)
    head = tok.encode("<|im_start|>user\nHere is our project. Read it, then answer.\n<|im_end|>\n"
                      "<|im_start|>assistant\n<think>\n\n</think>\n\n", parse_special=True)
    return head + (body * (n // max(1, len(body)) + 1))[:n]


def main() -> int:
    overrides = {}
    for item in sys.argv[1:]:
        k, _, v = item.partition("=")
        if k.startswith("--"):
            overrides[k] = v or True
    tag = "longctx" + ("-" + ",".join(f"{k}{v}" for k, v in overrides.items()) if overrides else "")
    tag = tag.replace("--", "").replace("=", "").replace(",", "_")[:60]
    sizes = [131072, 200000]

    tok = Tokenizer.from_dir(r"C:\AI\Strata-data\packs\iq3_xxs\tokenizer")
    cases = [(n, build_doc(tok, n)) for n in sizes]
    print("prompts: " + ", ".join(f"{n//1024}k" for n, _ in cases), flush=True)

    base = bench.load_base()
    args = bench.apply_overrides(base["args"], overrides)
    total, free = commit()
    print(f"commit before start: {free:.1f} of {total:.1f} GiB free", flush=True)

    eng = bench.Engine(args, tag, env_extra=None)
    print(f"engine ready in {eng.load_s:.1f}s, slots={eng.info.get('expert_slots')}, "
          f"vram_free={eng.info.get('vram_free_mib')}, max_context={eng.max_context}", flush=True)

    mem = {"samples": [], "stop": False}

    def sampler():
        while not mem["stop"]:
            t, f = commit()
            try:
                ws = next((p.WorkingSet64 for p in __import__("psutil").process_iter() if False), 0)
            except Exception:
                ws = 0
            mem["samples"].append((round(time.monotonic(), 1), round(f, 2)))
            time.sleep(1.0)

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    out = {"tag": tag, "overrides": overrides, "load_s": round(eng.load_s, 1),
           "slots": eng.info.get("expert_slots"), "max_context": eng.max_context, "cases": {}}
    try:
        for n, ids in cases:
            t0 = time.monotonic()
            m = eng.generate(ids, 32, timeout=1800)
            wall = time.monotonic() - t0
            ttft = m["prompt_ms"] / 1000.0
            rec = {"prompt_tokens": m["prompt_tokens"], "prompt_ms": m["prompt_ms"],
                   "ttft_s": round(ttft, 1), "wall_s": round(wall, 1),
                   "prefill_tok_s": m["prefill_tok_s"], "decode_tok_s": m["decode_tok_s"],
                   "finish": m["finish"], "offloaded": m.get("offloaded"),
                   "file_mb": m.get("file_mb")}
            out["cases"][f"{n // 1024}k"] = rec
            print(f"  {n//1024:>3}k in  prefill {m['prefill_tok_s']:>8.0f} tok/s  "
                  f"first token {ttft:>6.1f}s  decode {m['decode_tok_s']:>6.2f} tok/s  "
                  f"chunk {m.get('chunk')}  finish={m['finish']}", flush=True)
    finally:
        mem["stop"] = True
        eng.close()
    lows = [s[1] for s in mem["samples"]]
    out["commit_min_free_gib"] = min(lows) if lows else None
    print(f"minimum commit headroom during the run: {out['commit_min_free_gib']} GiB", flush=True)
    p = ROOT / ".tune" / "results" / f"{tag}.json"
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
