"""Compare the arms of a bench.py sweep against that sweep's baseline arms.

    python .tune/analyze.py .tune/results/phase1.json

Prints one row per arm and case: prefill tok/s, decode tok/s and draft acceptance,
with the delta against the median baseline. Arms whose tag starts with "p1-base" or
"baseline" form the baseline set, so a sweep can repeat the baseline at the end to
measure drift instead of pretending the machine was still.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def md(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0


def pct(value: float, base: float) -> str:
    if not base:
        return "   -  "
    return f"{(value - base) / base * 100:+6.1f}%"


def main() -> int:
    path = Path(sys.argv[1])
    payload = json.loads(path.read_text(encoding="utf-8"))
    arms = payload["arms"]
    if not arms:
        print("no arms")
        return 1
    cases = list(arms[0]["cases"])
    base_tags = [t for t in (sys.argv[2].split(",") if len(sys.argv) > 2 else []) if t]
    if base_tags:
        base_arms = [a for a in arms if a["tag"] in base_tags]
    else:
        base_arms = [a for a in arms if a["tag"].startswith(("p1-base", "baseline", "base"))]
    if not base_arms:
        print("no baseline arm (name one as the second argument, or tag it p1-base/baseline/base)")
        return 1

    def series(arm: dict, case: str, key: str) -> float:
        entry = arm["cases"].get(case) or {}
        return entry.get(key) or 0.0

    base = {c: {k: md([series(a, c, k) for a in base_arms])
                for k in ("prefill_tok_s", "decode_tok_s", "draft_accept")} for c in cases}

    print(f"sweep: {path}  when={payload.get('when')}  reps={payload.get('reps')}")
    print(f"baseline arms: {', '.join(a['tag'] for a in base_arms)}")
    print()
    header = f"{'arm':<18}{'engine':>10}{'slots':>7}{'chunk':>7}"
    for c in cases:
        header += f"{c + ' pp':>12}{'dpp':>8}{c + ' dec':>12}{'ddec':>8}"
    print(header)
    print("-" * len(header))
    for a in arms:
        slots = a.get("engine_info", {}).get("expert_slots", "?")
        engine = Path(str(a.get("exe", ""))).parent.name or "-"
        row = f"{a['tag']:<18}{engine:>10}{str(slots):>7}"
        first_chunk = a["cases"][cases[0]].get("chunk")
        row += f"{str(first_chunk):>7}"
        for c in cases:
            pp, dec = series(a, c, "prefill_tok_s"), series(a, c, "decode_tok_s")
            row += f"{pp:>12.0f}{pct(pp, base[c]['prefill_tok_s']):>8}"
            row += f"{dec:>12.1f}{pct(dec, base[c]['decode_tok_s']):>8}"
        print(row)
    print()
    print("acceptance (median over reps):")
    for a in arms:
        acc = "  ".join(f"{c}={series(a, c, 'draft_accept'):.3f}" for c in cases)
        print(f"  {a['tag']:<18} {acc}")
    if not payload.get("complete", False):
        print("\nWARNING: sweep incomplete - only the arms above were measured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
