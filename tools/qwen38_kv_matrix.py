"""tools/qwen38_kv_matrix.py - the same greedy answers on fp16, q8_0 and q4_0 KV caches.

The engine's cache formats differ only in how a key and a value are stored, so a greedy answer that is the same on
all three is the check that the 4-bit reader (and the store beside it) agree with the fp16 path.  Runs one prompt at
a time, 24 tokens each, and prints the ids per format and whether they match.

    python tools/qwen38_kv_matrix.py --prompts 3
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from strata_tokenizer import Tokenizer  # noqa: E402

ROOT = TOOLS.parent
PROMPTS = [
    "Hello! In one sentence, what are you?",
    "Write the first 20 digits of pi, separated by spaces.",
    "Name three colours and the hex code of each.",
    "What is 17 times 23? Answer with the number only.",
    "Write a haiku about a bicycle.",
]


def run(exe: Path, model: Path, ids: str, kv: str, max_new: int, env: dict) -> str:
    out = subprocess.run([str(exe), "--model", str(model), "--tokens", ids, "--max-new", str(max_new),
                          "--max-context", "4096", "--kv", kv, "--temperature", "0"],
                         capture_output=True, text=True, env=env)
    if out.returncode != 0:
        why = (out.stderr or out.stdout).strip().splitlines()
        return "ERR exit " + str(out.returncode) + (": " + why[-1][:120] if why else "")
    for line in reversed(out.stdout.splitlines()):
        if line and line[0].isdigit() and "," in line:
            return line.strip()
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", default=str(ROOT / "build" / "strata-poly.exe"))
    ap.add_argument("--model", default=r"C:\AI\Strata-data\models\qwen38-27b\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf")
    ap.add_argument("--prompts", type=int, default=len(PROMPTS))
    ap.add_argument("--max-new", type=int, default=24)
    ap.add_argument("--cuda-bin", default=r"C:\AI\Strata-data\cuda\13.1.2\bin;C:\AI\Strata-data\cuda\13.1.2\bin\x64",
                    help="CUDA runtime DLL folders the engine needs on PATH")
    a = ap.parse_args()
    env = dict(os.environ)
    env["PATH"] = a.cuda_bin + os.pathsep + env.get("PATH", "")
    tok = Tokenizer.from_gguf(a.model)
    ok_all = 0
    for i, text in enumerate(PROMPTS[: a.prompts], 1):
        ids = ",".join(map(str, tok.encode(text)))
        answers = {kv: run(Path(a.exe), Path(a.model), ids, kv, a.max_new, env) for kv in ("fp16", "q8_0", "q4_0")}
        same = answers["fp16"] == answers["q8_0"] == answers["q4_0"] and not answers["fp16"].startswith("ERR")
        ok_all += 1 if same else 0
        print(f"prompt {i}: {text!r}")
        print(f"  same ids on fp16, q8_0 and q4_0: {same}")
        if not same:
            for kv, v in answers.items():
                print(f"  {kv}: {v}")
        else:
            print("  ids: " + answers["fp16"])
    print(f"{ok_all} of {min(a.prompts, len(PROMPTS))} prompts agree across the three cache formats")
    return 0 if ok_all == min(a.prompts, len(PROMPTS)) else 1


if __name__ == "__main__":
    sys.exit(main())
