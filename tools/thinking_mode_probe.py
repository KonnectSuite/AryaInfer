"""tools/thinking_mode_probe.py - do the four thinking levels actually reach the model?

For one model it sends the same PLC question five times: at off, low, medium, high and with
no level at all (the config's own default).  Each answer is recorded with the reasoning text
the server streamed, the prompt the template rendered (prompt tokens), and whether the small
PLC answer is right.

The levels differ in the request if either the reasoning text or the rendered prompt changes;
off is only real when it produced no reasoning at all.

    python tools/thinking_mode_probe.py --base-url http://127.0.0.1:8080 \
        --model qwen3.6-35b-a3b-ud-q4_k_xl --out build-env/think-ud-q4.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request

QUESTION = (
    "A tank level transmitter is scaled 4-20 mA to 0-100 %. The high level alarm setpoint is 70 % and the alarm "
    "uses a 2 % deadband. In at most 90 words: at what percentage does the alarm turn on, at what percentage does "
    "it turn off, then give exactly one IEC 61131-3 Structured Text line implementing it with a REAL variable "
    "Level and a BOOL variable Alarm."
)
LEVELS = ["off", "low", "medium", "high", "default"]


def ask(base, model, level, budget, max_tokens, timeout):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": QUESTION}],
        "max_tokens": max_tokens,
        "stream": False,
    }
    if level != "default":
        body["reasoning_effort"] = level
    if budget > 0:
        body["reasoning_budget_tokens"] = budget
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    ch = out["choices"][0]
    msg = ch.get("message") or {}
    usage = out.get("usage") or {}
    return {
        "reasoning": msg.get("reasoning_content") or msg.get("reasoning") or "",
        "content": msg.get("content") or "",
        "finish": ch.get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
    }


def right(content):
    """The answer must name 70 as the on point and 68 as the off point (70 - 2)."""
    return bool(re.search(r"\b70\b", content)) and bool(re.search(r"\b68\b", content))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--model", required=True)
    ap.add_argument("--levels", default=",".join(LEVELS))
    ap.add_argument("--budget", type=int, default=512, help="reasoning_budget_tokens per request (0: config)")
    ap.add_argument("--max-tokens", type=int, default=900)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    levels = [x.strip() for x in a.levels.split(",") if x.strip() in LEVELS]
    rows = []
    print(f"\n=== {a.model}  (budget {a.budget or 'from config'})")
    print(f"{'level':<9}{'reason chars':>13}{'answer chars':>13}{'prompt tok':>11}{'secs':>7}{'finish':>10}  right")
    for level in levels:
        t0 = time.monotonic()
        try:
            r = ask(a.base_url, a.model, level, a.budget, a.max_tokens, a.timeout)
        except Exception as exc:                                       # noqa: BLE001
            print(f"{level:<9}  ERROR {exc}")
            rows.append({"level": level, "error": str(exc)})
            continue
        secs = time.monotonic() - t0
        ok = right(r["content"])
        print(f"{level:<9}{len(r['reasoning']):>13}{len(r['content']):>13}"
              f"{str(r['prompt_tokens']):>11}{secs:>7.1f}{str(r['finish']):>10}  {'yes' if ok else 'no'}")
        rows.append({"level": level, **{k: v for k, v in r.items() if k != "content"},
                     "reason_chars": len(r["reasoning"]), "answer_chars": len(r["content"]),
                     "secs": round(secs, 1), "right": ok, "content": r["content"]})

    # verdicts
    by = {r["level"]: r for r in rows if "error" not in r}
    verdicts = {}
    if "off" in by:
        verdicts["off_is_quiet"] = by["off"]["reason_chars"] == 0
    graded = [lv for lv in ("low", "medium", "high") if lv in by]
    if graded:
        verdicts["graded_think"] = all(by[lv]["reason_chars"] > 0 for lv in graded)
    prompts = {lv: by[lv]["prompt_tokens"] for lv in by}
    verdicts["distinct_prompts"] = len(set(v for v in prompts.values() if v is not None)) > 1
    verdicts["prompts"] = prompts
    if "default" in by:
        verdicts["default_thinks"] = by["default"]["reason_chars"] > 0
    verdicts["questions_right"] = {lv: by[lv]["right"] for lv in by}
    print("\n  verdicts: " + json.dumps(verdicts))
    doc = {"model": a.model, "budget": a.budget, "question": QUESTION, "rows": rows, "verdicts": verdicts}
    if a.out:
        from pathlib import Path
        Path(a.out).write_text(json.dumps(doc, indent=1), encoding="utf-8")
        print(f"  wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
