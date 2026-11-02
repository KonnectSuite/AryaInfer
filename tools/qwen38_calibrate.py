"""tools/qwen38_calibrate.py - sampling calibration for the Qwen3.8 27B models, tuned for coding (AryaCode).

For each candidate sampling set it drives code and instruction prompts through a running strata server and measures
what actually goes wrong in practice:

  * length       - the reply hit max_tokens (a model that could not stop)
  * loops        - a 12-token shingle repeated 3 times or more, or the same non-empty line three times
  * code         - for the Python prompts, the last ```python block is extracted and run: it has to exit 0
  * adherence    - "answer with just the number" prompts must contain nothing but the right number
  * diversity    - distinct 4-gram ratio over the whole reply

Usage, with a server already serving the model for the given id:

    python tools/qwen38_calibrate.py --base-url http://127.0.0.1:8081 --model qwen3.8-27b-iq3_xxs
    python tools/qwen38_calibrate.py --base-url http://127.0.0.1:8081 --model qwen3.8-27b-iq2_s --sets coding
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from pathlib import Path

PROMPTS = [
    {"id": "py-word-count", "kind": "run", "text":
     "Write a Python function word_count(text) that returns a dict of lowercase word to count. Then test it with "
     "assert word_count('A b a') == {'a': 2, 'b': 1}. Return only the code in one python block."},
    {"id": "py-merge", "kind": "run", "text":
     "Write a Python function that merges two sorted lists into one sorted list without calling sort(). Test it with "
     "assert merge([1, 3, 5], [2, 4]) == [1, 2, 3, 4, 5]. Return only the code in one python block."},
    {"id": "py-parse-json", "kind": "run", "text":
     "Write a Python function that reads a JSON list of numbers and returns the median. Test it with "
     "assert median_json('[1, 3, 2]') == 2. Return only the code in one python block."},
    {"id": "refactor", "kind": "code", "text":
     "Refactor this Python so it is clear and handles an empty list:\n\ndef avg(xs):\n    t = 0\n    for i in "
     "range(len(xs)):\n        t = t + xs[i]\n    return t / len(xs)\nReturn only the new function in one python "
     "block."},
    {"id": "bugfix", "kind": "code", "text":
     "This Python has a bug: it should return the last N items but returns the first N.\n\ndef tail(xs, n):\n    "
     "return xs[:n]\nFix it and return only the corrected function in one python block."},
    {"id": "csharp", "kind": "code", "text":
     "Write a C# method static int Add(int a, int b) that returns the sum, plus a unit test method using Assert. "
     "Return only the C# code in one csharp block."},
    {"id": "sql", "kind": "code", "text":
     "Write a SQL query that returns each customer's name and their total order amount, highest first, for customers "
     "with more than one order. Return only the SQL in one sql block."},
    {"id": "adherence-number", "kind": "only", "text":
     "What is 17 times 23? Answer with the number only, no words.", "expect": r"^\s*391\s*$"},
    {"id": "adherence-list", "kind": "only", "text":
     "Name exactly three prime numbers below 10, separated by commas, nothing else.", "expect": r"^\s*[2357]+\s*,\s*"
     r"[2357]+\s*,\s*[2357]+\s*$"},
    {"id": "grounding", "kind": "only", "text":
     "Read this and answer with just the port number:\n\nserver config: host=127.0.0.1 port=8477 workers=4\n\nPort?",
     "expect": r"^\s*8477\s*$"},
]

SETS = {
    # no sampling fields at all: whatever the run config (or the model-card preset) says applies
    "config": {},
    # what the installed MoE entries use (their run configs: 1.0 / 0.95 / 20 / 0.5)
    "moe": {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "presence_penalty": 0.5},
    # the family's general-purpose thinking set (what the 35B-A3B card uses)
    "general": {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "presence_penalty": 1.5},
    # the card's precise-coding set
    "coding": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "presence_penalty": 0.0},
    # coding set with the anti-loop penalty that stopped the 27B's repeats
    "coding-loop": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "presence_penalty": 1.5},
    # the coding set with the MoE entries' light penalty: code accuracy without a loop window
    "coding-0.5": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "presence_penalty": 0.5},
    # a middle ground: slightly hotter with a lighter penalty
    "balanced": {"temperature": 0.7, "top_p": 0.9, "top_k": 20, "presence_penalty": 0.8},
    # control: greedy, which is what the server serves today with no preset
    "greedy": {"temperature": 0.0},
}


def post(base: str, body: dict, timeout: float = 1200) -> dict:
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def text_of(out: dict) -> str:
    """The answer itself: the thinking stream is not part of it."""
    msg = (out.get("choices") or [{}])[0].get("message") or {}
    return msg.get("content") or ""


def all_of(out: dict) -> str:
    """The answer and the thinking after it, for the loop metrics: both streams can repeat."""
    msg = (out.get("choices") or [{}])[0].get("message") or {}
    return "\n".join(x for x in (msg.get("content"), msg.get("reasoning_content")) if x)


def loop_score(text: str) -> tuple[int, float]:
    """The most times a 12-token shingle repeats, and the share of non-empty lines that repeat."""
    toks = re.findall(r"\S+", text)
    shingles = Counter(tuple(toks[i:i + 12]) for i in range(max(0, len(toks) - 11)))
    worst = max(shingles.values(), default=0)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    dup = (len(lines) - len(set(lines))) / len(lines) if lines else 0.0
    return worst, dup


def distinct4(text: str) -> float:
    toks = re.findall(r"\S+", text)
    grams = [tuple(toks[i:i + 4]) for i in range(max(0, len(toks) - 3))]
    return len(set(grams)) / len(grams) if grams else 0.0


def run_python(block: str) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(block)
        path = f.name
    try:
        r = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    finally:
        Path(path).unlink(missing_ok=True)


def code_ok(kind: str, text: str) -> bool | None:
    if kind == "run":
        m = list(re.finditer(r"```(?:python)?\s*\n(.*?)```", text, re.S))
        return run_python(m[-1].group(1)) if m else False
    if kind == "code":
        return "```" in text and len(text) > 40
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8081")
    ap.add_argument("--model", required=True)
    ap.add_argument("--sets", default=",".join(SETS))
    ap.add_argument("--max-tokens", type=int, default=300)
    ap.add_argument("--budget", type=int, default=1536, help="reasoning_budget_tokens sent with each request")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    names = [s.strip() for s in a.sets.split(",") if s.strip() in SETS]
    rows = []
    for name in names:
        s = SETS[name]
        print(f"\n=== {a.model}  set {name}: {s}")
        for p in PROMPTS:
            body = {"model": a.model, "max_tokens": a.max_tokens, "messages": [{"role": "user", "content": p["text"]}],
                    "reasoning_budget_tokens": a.budget, **s}
            t0 = time.monotonic()
            try:
                out = post(a.base_url, body)
            except Exception as exc:                     # a refused request is a result too
                print(f"  {p['id']:<20} request failed: {exc}")
                rows.append({"model": a.model, "set": name, "prompt": p["id"], "error": str(exc)})
                continue
            answer = text_of(out)
            everything = all_of(out)
            finish = (out.get("choices") or [{}])[0].get("finish_reason")
            usage = out.get("usage") or {}
            worst, dup = loop_score(everything)
            row = {"model": a.model, "set": name, "prompt": p["id"], "finish": finish,
                   "tokens": usage.get("completion_tokens"), "secs": round(time.monotonic() - t0, 1),
                   "loop_shingle": worst, "line_dup": round(dup, 2), "distinct4": round(distinct4(everything), 2),
                   "empty_answer": not answer.strip(), "think_chars": len(everything) - len(answer),
                   "code_ok": code_ok(p["kind"], answer or everything)}
            if p["kind"] == "only":
                row["adherence"] = bool(re.match(p["expect"], answer.strip(), re.S))
            rows.append(row)
            print(f"  {p['id']:<20} finish={finish:<8} tokens={row['tokens']:<4} shingle={worst} "
                  f"lines_dup={row['line_dup']:<5} d4={row['distinct4']} code={row['code_ok']} "
                  f"adherence={row.get('adherence', '-')} {row['secs']}s")

    # summary a set at a time
    print(f"\n=== summary {a.model}")
    print(f"{'set':<13}{'reqs':>5}{'length':>8}{'loops':>7}{'code_ok':>9}{'adherence':>11}{'mean_d4':>9}")
    by = {}
    for r in rows:
        by.setdefault(r["set"], []).append(r)
    for name, rs in by.items():
        n = len(rs)
        length = sum(1 for r in rs if r.get("finish") == "length")
        loops = sum(1 for r in rs if (r.get("loop_shingle") or 0) >= 3 or (r.get("line_dup") or 0) >= 0.5)
        code = [r["code_ok"] for r in rs if r.get("code_ok") is not None]
        adh = [r["adherence"] for r in rs if r.get("adherence") is not None]
        d4 = sum(r.get("distinct4") or 0 for r in rs) / n
        print(f"{name:<13}{n:>5}{length:>8}{loops:>7}{str(sum(code)) + '/' + str(len(code)):>9}"
              f"{str(sum(adh)) + '/' + str(len(adh)):>11}{d4:>9.2f}")
        by[name] = rs
    if a.out:
        Path(a.out).write_text(json.dumps({"rows": rows}, indent=1), encoding="utf-8")
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
