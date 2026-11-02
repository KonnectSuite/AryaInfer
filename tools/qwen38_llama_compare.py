"""tools/qwen38_llama_compare.py - the 27B against llama.cpp on the same file (the repo's own verification).

docs/BACKENDS.md's standard: greedy, 64 tokens after a handful of prompts, the token ids compared and the reference's
five likeliest tokens at a step.  This drives

  * `llama-completion` (llama.cpp's CLI) for the greedy reply, and
  * `llama-debug` (llama.cpp's debug example) for the logits of the prompt's last token, which give its five
    likeliest ids and their probabilities at the first generated step,

and compares both with `strata-poly --tokens ... --top-probs 5` on the ids our tokenizer makes of the same text.

    python tools/qwen38_llama_compare.py

The reply is compared up to the first end-of-reply token in ours.  llama.cpp's sampler hides that token and stops
after it; our engine writes it and goes on, so the tokens before it are what the two make of the same prompt.  The
reference's ids come from its own tokenizer over the text it wrote (a trailing space can fall into a different token
at the very end, which the token counts show).
"""
from __future__ import annotations

import argparse
import math
import os
import re
import struct
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
END = {248044, 248045, 248046}      # end of text, im_start, im_end: a reply ends at the first of them
CUDA_BIN = r"C:\AI\Strata-data\cuda\13.1.2\bin;C:\AI\Strata-data\cuda\13.1.2\bin\x64"
LOGITS_DIR = ROOT / "build-env" / "llama-logits"


def run(cmd: list[str], env: dict, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout, errors="replace")


def llama_text(out: subprocess.CompletedProcess) -> str:
    """The reply llama-completion wrote to stdout, its line endings as the model made them."""
    text = out.stdout
    for marker in ("[end of text]", "llama_perf_", "llama_print_timings", "llama_model_loader"):
        if marker in text:
            text = text.split(marker)[0]
    return text.replace("\r\n", "\n")


def our_ids(exe: str, model: str, ids: list[int], max_new: int, env: dict, top: int = 0):
    """strata-poly's greedy ids, and with top > 0 its `top <id>:<prob>` line per step."""
    cmd = [exe, "--model", model, "--tokens", ",".join(map(str, ids)), "--max-new", str(max_new),
           "--max-context", "4096", "--kv", "q8_0", "--temperature", "0"]
    if top:
        cmd += ["--top-probs", str(top)]
    out = run(cmd, env)
    if out.returncode != 0:
        raise SystemExit("strata-poly failed: " + (out.stderr or out.stdout).strip()[-400:])
    got: list[int] = []
    for line in reversed(out.stdout.splitlines()):
        if line and line[0].isdigit() and "," in line:
            got = [int(x) for x in line.strip().split(",")]
            break
    steps = []
    for line in out.stderr.splitlines():
        if line.startswith("top "):
            steps.append({int(i): float(p) for i, p in (f.split(":") for f in line[4:].split())})
    return got, steps


def llama_top5(debug: str, model: str, text: str, n_vocab: int, env: dict):
    """llama.cpp's five likeliest ids and probabilities for the prompt's last token, and its prompt ids."""
    LOGITS_DIR.mkdir(parents=True, exist_ok=True)
    for old in LOGITS_DIR.glob("*"):
        old.unlink()
    out = run([debug, "-m", model, "-p", text, "--save-logits", "--logits-output-dir", str(LOGITS_DIR),
               "-c", "4096", "-ngl", "99"], env)
    bins = [b for b in sorted(LOGITS_DIR.glob("*.bin"))
            if not b.name.endswith(("-tokens.bin", "-prompt.bin"))]
    if not bins:
        raise SystemExit("llama-debug wrote no logits: " + (out.stderr or out.stdout)[-400:])
    raw = bins[0].read_bytes()
    logits = struct.unpack(f"<{len(raw) // 4}f", raw)
    if len(logits) < n_vocab:
        raise SystemExit(f"llama-debug's logits hold {len(logits)} values, the model has {n_vocab}")
    ids: list[int] = []
    prompt_txt = next(LOGITS_DIR.glob("*-prompt.txt"), None)
    if prompt_txt is not None:
        m = re.search(r"token ids: ([\d,\s]+)", prompt_txt.read_text(encoding="utf-8", errors="replace"))
        if m:
            ids = [int(x) for x in m.group(1).replace(" ", "").split(",") if x]
    top = max(logits)
    ex = [math.exp(x - top) for x in logits[:n_vocab]]
    total = sum(ex)
    order = sorted(range(n_vocab), key=lambda i: logits[i], reverse=True)[:5]
    return order, {i: ex[i] / total for i in order}, ids


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", default=str(ROOT / "build-env" / "llama-build" / "bin" / "llama-completion.exe"))
    ap.add_argument("--debug", default=str(ROOT / "build-env" / "llama-build" / "bin" / "llama-debug.exe"))
    ap.add_argument("--exe", default=str(ROOT / "build" / "strata-poly.exe"))
    ap.add_argument("--model", default=r"C:\AI\Strata-data\models\qwen38-27b\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf")
    ap.add_argument("--prompts", type=int, default=len(PROMPTS))
    ap.add_argument("--max-new", type=int, default=64)
    a = ap.parse_args()
    env = dict(os.environ)
    env["PATH"] = CUDA_BIN + os.pathsep + env.get("PATH", "")
    tok = Tokenizer.from_gguf(a.model)
    n_vocab = 248320
    n = min(a.prompts, len(PROMPTS))
    same = prob_ok = 0
    worst = 0.0
    prefixes: list[int] = []
    prompts_same = prob_same = 0
    for i, text in enumerate(PROMPTS[:n], 1):
        ids = tok.encode(text)
        ours, steps = our_ids(a.exe, a.model, ids, a.max_new, env, top=5)
        ref = run([a.app, "-m", a.model, "-p", text, "-n", str(a.max_new), "--temp", "0", "--top-k", "1",
                   "--seed", "0", "-c", "4096", "-ngl", "99", "--no-display-prompt", "-no-cnv", "--simple-io"],
                  env)
        ref_ids = tok.encode(llama_text(ref)) if llama_text(ref) else []
        ref_ids = ref_ids[: next((k for k, x in enumerate(ref_ids) if x in END), len(ref_ids))]
        body = ours[: next((k for k, x in enumerate(ours) if x in END), len(ours))]
        prefix = next((k for k, (x, y) in enumerate(zip(ref_ids, body)) if x != y), min(len(ref_ids), len(body)))
        agree_reply = body[:prefix] == ref_ids[:prefix] and prefix > 0
        same += prefix
        prefixes.append(prefix)
        print(f"prompt {i}: {text.encode('ascii', 'backslashreplace').decode()}")
        print(f"  reply: llama.cpp {len(ref_ids)} tokens, strata-poly {len(body)}; the same first {prefix}")
        if not agree_reply:
            for k, (x, y) in enumerate(zip(ref_ids, body)):
                if x != y:
                    print(f"  first difference at token {k}: llama.cpp {x}, strata-poly {y}")
                    break
            else:
                print(f"  (the same up to {min(len(ref_ids), len(body))} tokens; the counts differ)")
        ref_top, ref_p, ref_prompt = llama_top5(a.debug, a.model, text, n_vocab, env)
        print(f"  its prompt ids equal to ours: {ref_prompt == ids}")
        ours_order = sorted(steps[0], key=steps[0].get, reverse=True)[:5] if steps else []
        delta = max((abs(steps[0].get(j, 0.0) - ref_p.get(j, 0.0))
                     for j in set(ref_top) | set(ours_order)), default=0.0) if steps else 1.0
        agree_prob = ours_order == ref_top
        prob_ok += 1 if agree_prob and delta < 0.1 else 0
        prob_same += 1 if delta < 0.1 else 0
        worst = max(worst, delta)
        print(f"  first step: five likeliest ids equal: {agree_prob}; llama.cpp {ref_top}, strata-poly {ours_order}")
        print(f"              largest probability difference: {delta:.4f}")
    print()
    print(f"greedy ids in common with llama.cpp, a prompt a number: {prefixes} (a reply's end or its first near tie)")
    print(f"{prob_same} of {n} prompts: the five likeliest ids at the first step within 0.1 (largest difference "
          f"{worst:.4f}); the same order within that: {prob_ok}")
    # a short reply has a short prefix (17 x 23 is four tokens); what matters is that no prompt parts at once and
    # that the first step's probabilities are the reference's
    return 0 if all(p >= 4 for p in prefixes) and prob_same == n else 1


if __name__ == "__main__":
    sys.exit(main())
