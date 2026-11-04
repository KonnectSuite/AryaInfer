"""tools/qwen38_spec_bench.py - measure speculative decoding of the Qwen3.8 27B on this host.

Drives one engine process over its own stdin protocol (GEN lines), which is how the server feeds long prompts without
the Windows command-line limit, and records what the plan's gates need:

  * prompt tokens, prefill ms and tok/s, generated tokens, decode ms and tok/s
  * drafts accepted of offered, and with --report-drafts the per-position acceptance
  * tokens per round (generated / rounds, rounds = the rounds that drafted at least one guess)

    python tools/qwen38_spec_bench.py --contexts 8192,32768,65536 --tokens 8000,32000,64000
    python tools/qwen38_spec_bench.py --contexts 131072 --tokens 128000 --prompt-batch 256

The prompt is filler text repeated to the requested token count; greedy (temperature 0).  One JSON row per run is
written to --out.
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from strata_tokenizer import Tokenizer  # noqa: E402

ROOT = TOOLS.parent
FILLER = ("The harbor fills with fog each morning, and the cranes move slowly along the water while the crews check "
          "the ropes and the tide tables.  Every crate has a number painted on its side, and the ledger keeps a line "
          "for each one.  ")
# the prompt has to ask for a long answer: filler alone makes the model end its turn after a token or two
TAIL = ("Now write a long, detailed technical explanation of how a bicycle drivetrain works, covering the chain, the "
        "cassette, the derailleurs, the chainrings and the shifters, in at least six paragraphs. Do not stop early.")


def prompt_ids(tok: Tokenizer, tokens: int, ask: str = "") -> list[int]:
    n = len(tok.encode(FILLER))
    tail = tok.encode(ask or TAIL)
    reps = max(1, (tokens - len(tail)) // n)
    ids = tok.encode(FILLER * reps + (ask or TAIL))
    return ids[:tokens] if tokens > 0 else ids


def parse_serve(line: str) -> dict:
    """`strata serve: prompt N tokens = R reused + P read in X ms (Y tok/s), G generated in D ms (Z tok/s)`"""
    out = {}
    m = re.search(r"prompt (\d+) tokens = (\d+) reused \+ (\d+) read in ([\d.]+) ms \(([\d.]+) tok/s\), "
                  r"(\d+) generated in ([\d.]+) ms \(([\d.]+) tok/s\)", line)
    if m:
        out.update(prompt_tokens=int(m.group(1)), reused=int(m.group(2)), read=int(m.group(3)),
                   prompt_ms=float(m.group(4)), prefill_tok_s=float(m.group(5)),
                   generated=int(m.group(6)), decode_ms=float(m.group(7)), decode_tok_s=float(m.group(8)))
    m = re.search(r"drafts accepted (\d+) of (\d+)", line)
    if m:
        out["accepted"], out["offered"] = int(m.group(1)), int(m.group(2))
    return out


def parse_by_pos(line: str) -> list[tuple[int, int]]:
    """`strata drafts by pos: a/b c/d ...; rounds N` (accepted/drafted at each guess position)."""
    out = []
    head = line.split(":", 1)[1].split(";")[0]
    for part in head.split():
        a, b = part.split("/")
        out.append((int(a), int(b)))
    return out


def run_one(exe: str, model: str, ctx: int, tokens: int, max_new: int, kv: str, pb: int, extra: list[str],
            timeout: float, ask: str = "", by_pos: bool = False, warmup: int = 0) -> dict:
    tok = Tokenizer.from_gguf(model)
    tokens = min(tokens, ctx - max_new - 8)   # the engine refuses a prompt plus output past --max-context
    ids = prompt_ids(tok, tokens, ask)
    cmd = [exe, "--model", model, "--serve", "--max-context", str(ctx), "--kv", kv, *extra]
    if by_pos:                                      # not every build has it; the base line still counts drafts
        cmd.append("--report-drafts")
    if pb:
        cmd += ["--prompt-batch", str(pb)]
    t0 = time.monotonic()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", bufsize=1)
    lines: "queue.Queue[str]" = queue.Queue()
    done = threading.Event()
    stats: dict = {}
    err_tail: list[str] = []          # the last stderr lines, so an engine that dies at once says why

    def read_err():
        for line in p.stderr:
            lines.put(line.rstrip("\n"))
            err_tail.append(line.rstrip("\n"))
            del err_tail[:-12]
            if line.startswith("strata serve: prompt"):
                stats.update(parse_serve(line))
            elif line.startswith("strata drafts by pos:"):
                stats["by_pos"] = parse_by_pos(line)
                m = re.search(r"rounds (\d+)", line)
                if m:
                    stats["rounds"] = int(m.group(1))
            if stats.get("by_pos") is not None and "decode_tok_s" in stats:
                done.set()

    def read_out():
        for line in p.stdout:
            if line.startswith("DONE "):
                stats["done"] = line.split()
                # DONE carries the same figures as the stderr summary and is flushed first, so read them here: the
                # stderr line can lose the race with this one, and the run ends as soon as this arrives.
                # DONE <produced> <prompt> <prompt ms> <decode ms> <finish> <accepted> <offered> <reused> ...
                #      <hits> <experts> 0 0 0.0 <read> 0
                f = stats["done"]
                try:
                    produced, n = int(f[1]), int(f[2])
                    prompt_ms, decode_ms = float(f[3]), float(f[4])
                    read, reused = int(f[14]), int(f[8])
                    stats.setdefault("prompt_tokens", n)
                    stats.setdefault("reused", reused)
                    stats.setdefault("read", read)
                    stats.setdefault("prompt_ms", prompt_ms)
                    stats.setdefault("generated", produced)
                    stats.setdefault("decode_ms", decode_ms)
                    stats.setdefault("finish", f[5])
                    if prompt_ms > 0:
                        stats.setdefault("prefill_tok_s", round(1000.0 * read / prompt_ms, 1))
                    if decode_ms > 0:
                        stats.setdefault("decode_tok_s", round(1000.0 * produced / decode_ms, 1))
                    if int(f[6]) or int(f[7]):
                        stats.setdefault("accepted", int(f[6]))
                        stats.setdefault("offered", int(f[7]))
                except (IndexError, ValueError):
                    pass
                done.set()

    te = threading.Thread(target=read_err, daemon=True)
    to = threading.Thread(target=read_out, daemon=True)
    te.start()
    to.start()

    def send(n_new: int, toks: list[int]):
        try:
            p.stdin.write(f"GEN {n_new} temperature=0 {','.join(map(str, toks))}\n")
            p.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    deadline = time.monotonic() + timeout            # one budget for the whole run, a warm-up included

    def wait_done() -> bool:
        while not done.is_set() and time.monotonic() < deadline and p.poll() is None:
            time.sleep(0.2)
        return done.is_set()

    if warmup:
        # A short answer first: the routed experts it touches stay in VRAM and the model's pages in the file cache, so
        # the measured request is the second one, the way a chat session meets it.
        send(warmup, ids[:64])
        wait_done()
        stats.clear()
        done.clear()
    if p.poll() is None:
        send(max_new, ids)
        wait_done()
    exited = p.poll()                 # None when the deadline ran out and the engine is still working
    try:
        p.kill()
    except OSError:
        pass
    row = {"context": ctx, "prompt_tokens_asked": len(ids), "max_new": max_new, "kv": kv,
           "wall_s": round(time.monotonic() - t0, 1), **{k: v for k, v in stats.items() if k != "done"}}
    if exited is not None:
        row["exit_code"] = exited
    if "prefill_tok_s" not in row:    # no numbers: keep what the engine said, instead of a silent empty row
        row["no_stats"] = "the engine printed no 'strata serve: prompt' line"
        if err_tail:
            row["stderr_tail"] = err_tail
    if "generated" in row and row.get("rounds"):
        row["tokens_per_round"] = round(row["generated"] / row["rounds"], 2)
    if "by_pos" in row:
        row["accept_by_pos"] = [round(a / b, 3) if b else 0.0 for a, b in row["by_pos"]]
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", default=str(ROOT / "build" / "strata-poly.exe"))
    ap.add_argument("--model", default=r"C:\AI\Strata-data\models\qwen38-27b\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf")
    ap.add_argument("--contexts", default="8192,32768,65536")
    ap.add_argument("--tokens", default="8000,32000,64000",
                    help="prompt tokens to ask for at each context (comma separated, same count as --contexts)")
    ap.add_argument("--max-new", type=int, default=256)
    ap.add_argument("--kv", default="q4_0")
    ap.add_argument("--prompt-batch", type=int, default=0)
    ap.add_argument("--extra", default="", help="more engine flags, space separated")
    ap.add_argument("--ask", default="", help="the request appended to the filler (default: the bicycle essay)")
    ap.add_argument("--drafts-by-pos", action="store_true",
                    help="pass --report-drafts (only a build that knows the flag)")
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--warmup", type=int, default=0,
                    help="tokens for a short answer sent first, so the measured request meets a warm expert cache")
    ap.add_argument("--out", default=str(ROOT / "build-env" / "spec-bench.json"))
    a = ap.parse_args()
    ctxs = [int(x) for x in a.contexts.split(",") if x.strip()]
    toks = [int(x) for x in a.tokens.split(",") if x.strip()]
    if len(toks) != len(ctxs):
        raise SystemExit("--tokens and --contexts need the same count")
    extra = [x for x in a.extra.split() if x]
    rows = []
    for ctx, n in zip(ctxs, toks):
        print(f"=== context {ctx}, prompt ~{n} tokens", flush=True)
        row = run_one(a.exe, a.model, ctx, n, a.max_new, a.kv, a.prompt_batch, extra, a.timeout, a.ask,
                      by_pos=a.drafts_by_pos, warmup=a.warmup)
        rows.append(row)
        print("  " + json.dumps(row), flush=True)
    Path(a.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("wrote", a.out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
