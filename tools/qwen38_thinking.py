"""tools/qwen38_thinking.py - the four thinking modes, measured per model.

For each level (off, low, medium, high) it sends probes whose answers are checkable - a time arithmetic, a puzzle
with one correct draw, a multiplication, and a small Python task whose code is executed - and reports whether the
mode actually thinks, whether the answer is right, how much it thought and how long it took.

    python tools/qwen38_thinking.py --base-url http://127.0.0.1:8081 --model qwen3.8-27b-iq3_xxs
    python tools/qwen38_thinking.py --base-url http://127.0.0.1:8081 --model qwen3.8-27b-iq2_s --levels off,high
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

PROBES = [
    {"id": "time-span", "text":
     "A train leaves at 14:37 and arrives at 21:12 the next day. How many hours and minutes is the journey? "
     "Answer with the number of hours and minutes only, like '5 hours 30 minutes'.",
     "expect": r"30\s*hours?\s*35\s*minutes?", "why": "needs a day rollover"},
    {"id": "three-boxes", "text":
     "Three boxes are labelled 'apples', 'oranges' and 'mixed', and every label is wrong. Each box holds either "
     "apples, oranges, or a mix. You may draw one fruit from one box. Which box should you draw from, and why? "
     "Answer with the box label first, in the form 'draw from <label>'.", "expect": r"mixed", "why":
     "classic wrong-label deduction"},
    {"id": "multiply", "text": "What is 37 times 41? Answer with the number only.", "expect": r"^\s*1517\s*$",
     "why": "arithmetic under pressure"},
    {"id": "py-task", "text":
     "Write a Python function that returns the second largest distinct number in a list, then test it with "
     "assert second_largest([5, 1, 5, 3]) == 3. Return only the code in one python block.", "exec": True,
     "why": "small design + edge case"},
    {"id": "pen-cost", "text":
     "Pens cost $2.50 each, or $9.00 for a pack of four. What is the cheapest total for 14 pens? Answer with the "
     "number only.", "expect": r"^\s*32(\.00)?\s*$", "why": "a two-way comparison, easy to get wrong in a hurry"},
    {"id": "palindrome", "text":
     "Write a Python function pal_len(s) that returns the length of the longest palindromic substring, then test it "
     "with assert pal_len('abba') == 4 and assert pal_len('abc') == 1. Return only the code in one python block.",
     "exec": True, "why": "non-trivial algorithm: thinking should pay for itself"},
]


def post(base, body, timeout=1800):
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run_python(block):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(block)
        path = f.name
    try:
        return subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=60).returncode == 0
    except subprocess.TimeoutExpired:
        return False
    finally:
        Path(path).unlink(missing_ok=True)


def worst_shingle(text):
    toks = re.findall(r"\S+", text)
    c = Counter(tuple(toks[i:i + 12]) for i in range(max(0, len(toks) - 11)))
    return max(c.values(), default=0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8081")
    ap.add_argument("--model", required=True)
    ap.add_argument("--levels", default="off,low,medium,high")
    ap.add_argument("--max-tokens", type=int, default=700)
    ap.add_argument("--budget", type=int, default=None, help="reasoning_budget_tokens to send (0: none)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    rows = []
    for level in [x.strip() for x in a.levels.split(",") if x.strip()]:
        print(f"\n=== {a.model}  effort {level}")
        for p in PROBES:
            body = {"model": a.model, "max_tokens": a.max_tokens, "reasoning_effort": level,
                    "messages": [{"role": "user", "content": p["text"]}]}
            if a.budget is not None:
                body["reasoning_budget_tokens"] = a.budget
            t0 = time.monotonic()
            out = post(a.base_url, body)
            ch = (out.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            answer = msg.get("content") or ""
            think = msg.get("reasoning_content") or ""
            ok = None
            if p.get("expect"):
                ok = bool(re.search(p["expect"], answer, re.I | re.S))
            if p.get("exec"):
                m = list(re.finditer(r"```(?:python)?\s*\n(.*?)```", answer or think, re.S))
                ok = run_python(m[-1].group(1)) if m else False
            row = {"model": a.model, "level": level, "probe": p["id"], "think_chars": len(think),
                   "answer_chars": len(answer), "tokens": (out.get("usage") or {}).get("completion_tokens"),
                   "finish": ch.get("finish_reason"), "ok": ok, "worst12": worst_shingle(answer + think),
                   "secs": round(time.monotonic() - t0, 1)}
            rows.append(row)
            print(f"  {p['id']:<12} think={len(think):>5}c answer={len(answer):>4}c tokens={row['tokens']:<4} "
                  f"finish={str(row['finish']):<7} ok={str(ok):<5} worst12={row['worst12']:<3} {row['secs']}s")
    print(f"\n=== summary {a.model}")
    print(f"{'level':<8}{'think c':>9}{'tokens':>8}{'ok':>7}{'loops':>7}{'secs':>7}")
    by = {}
    for r in rows:
        by.setdefault(r["level"], []).append(r)
    for level, rs in by.items():
        print(f"{level:<8}{sum(r['think_chars'] for r in rs) // max(1, len(rs)):>9}"
              f"{sum(r['tokens'] or 0 for r in rs) // max(1, len(rs)):>8}"
              f"{str(sum(1 for r in rs if r['ok'])) + '/' + str(sum(1 for r in rs if r['ok'] is not None)):>7}"
              f"{sum(1 for r in rs if r['worst12'] >= 3):>7}{sum(r['secs'] for r in rs):>7.0f}")
    if a.out:
        Path(a.out).write_text(json.dumps({"rows": rows}, indent=1), encoding="utf-8")
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
