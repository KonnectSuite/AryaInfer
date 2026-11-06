"""tools/plc_sampling_probe.py - sampling calibration for PLC and HMI coding.

AryaCode does industrial work: IEC 61131-3 Structured Text, Studio 5000 ladder (NeutralText
and L5X), and FactoryTalk View ME expressions.  This probe asks for that work and checks the
answer mechanically, so a sampling set is judged by what it produced, not by how it looks.

    python tools/plc_sampling_probe.py --base-url http://127.0.0.1:8080 \
        --model qwen3.8-27b-turbo-iq3xxs --sets coding,coding-0.5 --out build-env/plc-turbo.json

Each fixture returns (ok, why): `ok` needs every required token and an absence of the wrong
dialect.  `truncated` and `empty` are recorded separately so a length failure cannot pass as
a wrong answer.  Thinking is switched off per request: this measures sampling, not reasoning.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

# name -> (prompt, check)
FIXTURES = {}


def fixture(name, prompt):
    def reg(fn):
        FIXTURES[name] = (prompt, fn)
        return fn
    return reg


def _all(code, *needles):
    missing = [n for n in needles if n.lower() not in code.lower()]
    return (not missing), ("missing: " + ", ".join(missing) if missing else "")


def _blocks(text):
    """The fenced blocks, or the whole text when the model answered without fences."""
    got = re.findall(r"```[a-zA-Z0-9+#]*\n(.*?)```", text, re.S)
    return "\n".join(got) if got else text


@fixture("st_seal_in", "Write IEC 61131-3 Structured Text for a motor start/stop circuit with a seal-in and a "
                      "start timeout: inputs Start, Stop, Fault (BOOL); output Run (BOOL). A TON named StartTimer "
                      "with a 5 second preset runs while Start is held and Run is false. Return only the code.")
def _st_seal_in(text):
    code = _blocks(text)
    ok, why = _all(code, "TON", "T#5", "Start", "Stop", "Run")
    if ok and re.search(r"XIC\(|OTE\(|XIO\(", code):
        ok, why = False, "ladder instruction in Structured Text"
    return ok, why


@fixture("st_scale", "Write an IEC 61131-3 Structured Text function ScalePct that converts an analog input AI_RAW "
                     "(INT, 27648 counts full scale) to percent 0.0..100.0 as REAL, clamped, assuming 4 mA is 0 % "
                     "and 20 mA is 100 %. Return only the code.")
def _st_scale(text):
    code = _blocks(text)
    ok, why = _all(code, "27648", "100.0", "REAL")
    if ok and not re.search(r"Min\(|Max\(|LIMIT|IF ", code, re.I):
        ok, why = False, "no clamp"
    return ok, why


@fixture("st_bits", "Write IEC 61131-3 Structured Text that copies bit 5 of Word (DINT) into Flag (BOOL) and sets "
                    "bit 7 of Word without changing the other bits. Return only the code.")
def _st_bits(text):
    code = _blocks(text)
    ok, why = _all(code, "Word", "Flag")
    if not ok:
        return ok, why
    # 32, 16#20 and Word.5 all address bit 5; 128 and 16#80 all set bit 7
    if not re.search(r"16#0*20\b|2#100000\b|\b32\b|\.5\b", code):
        return False, "no bit 5 mask (32 / 16#20 / .5)"
    if not re.search(r"16#0*80\b|2#10000000\b|\b128\b", code):
        return False, "no bit 7 set (128 / 16#80)"
    if not re.search(r"\bAND\b|\bOR\b|BOOL\(|>", code, re.I):
        return False, "no boolean operation"
    return True, ""


@fixture("ld_rung", "Write exactly one Studio 5000 ladder rung in NeutralText for a motor that seals in on Start, "
                    "drops on Stop or Fault, and drives Run; tags Start, Stop, Fault, Run. Return only the rung text, "
                    "ending with a semicolon.")
def _ld_rung(text):
    code = _blocks(text).strip().strip("`").strip()
    ok, why = _all(code, "XIC(Start)", "XIO(Stop)", "OTE(Run)")
    if ok and not code.endswith(";"):
        ok, why = False, "rung does not end with ;"
    if ok and code.count("(") != code.count(")"):
        ok, why = False, "unbalanced parentheses"
    if ok and "\n" in code.strip():
        ok, why = False, "more than one rung"
    return ok, why


@fixture("l5x_xml", "Produce a Studio 5000 L5X <Rung> element, Number=\"0\" Type=\"N\", whose <Text> child holds "
                    "the rung text XIC(Start)OTE(Run); as its text content, plus a <Comment>. Return only the XML, "
                    "no wrapper, no fences.")
def _l5x_xml(text):
    code = _blocks(text).strip().strip("`").strip()
    start = code.find("<Rung")
    if start < 0:
        return False, "no <Rung> element"
    code = code[start:]
    try:
        el = ET.fromstring(code)
    except ET.ParseError as exc:
        return False, f"XML does not parse: {exc}"
    if el.get("Number") != "0" or el.get("Type") != "N":
        return False, "Rung attributes are not Number/Type as asked"
    text_el = el.find("Text")
    if text_el is None or "XIC(Start)" not in (text_el.text or ""):
        return False, "<Text> missing or does not hold the logic"
    if el.find("Comment") is None:
        return False, "no <Comment>"
    return True, ""


@fixture("hmi_vis", "FactoryTalk View ME: give the visibility expression for a button that is shown only while "
                    "Auto is off and Running is on (tags Auto, Running). Return only the expression.")
def _hmi_vis(text):
    code = _blocks(text).strip()
    ok, why = _all(code, "{Auto}", "{Running}")
    if ok and not re.search(r"=\s*0|=\s*false|NOT\s*\{?\s*Auto", code, re.I):
        ok, why = False, "no negated Auto test"
    if ok and not re.search(r"\bAND\b|&&", code, re.I):
        ok, why = False, "no AND"
    if ok and re.search(r"\bif\b", code, re.I):
        ok, why = False, "statement where an expression was asked for"
    return ok, why


@fixture("hmi_alarm", "FactoryTalk View ME: write the message text for a high-tank-level alarm that shows the live "
                      "level and the setpoint, using the application's placeholder syntax for tag values. One line.")
def _hmi_alarm(text):
    line = _blocks(text).strip().strip("`").strip()
    if "\n" in line.strip():
        return False, "more than one line"
    ok, why = _all(line, "Tank")
    if ok and not re.search(r"\{/[^}]+\}", line):
        ok, why = False, "no {/Tag} placeholder"
    if ok and not re.search(r"(high|level)", line, re.I):
        ok, why = False, "message does not say what happened"
    return ok, why


@fixture("st_case", "Write IEC 61131-3 Structured Text CASE state machine with states 0 Idle, 10 Filling, 20 Done, "
                    "driven by Level (REAL) and a 30 second watchdog timer that resets on every state change. "
                    "Return only the code.")
def _st_case(text):
    code = _blocks(text)
    ok, why = _all(code, "CASE", "END_CASE", "0:", "10:", "20:")
    if ok and not re.search(r"TON|Watchdog|WatchDog", code, re.I):
        ok, why = False, "no watchdog timer"
    if ok and not re.search(r"30|T#30", code):
        ok, why = False, "no 30 second preset"
    return ok, why


SETS = {
    "coding": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "presence_penalty": 0.0},
    "coding-0.5": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "presence_penalty": 0.5},
    "family": {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "presence_penalty": 0.5},
    "precise": {"temperature": 0.3, "top_p": 0.9, "top_k": 20, "presence_penalty": 0.0},
}


def ask(base, model, text, sampling, max_tokens, timeout):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": text}],
        "max_tokens": max_tokens,
        "reasoning_effort": "off",
        "stream": False,
        **sampling,
    }
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    ch = out["choices"][0]
    msg = ch.get("message") or {}
    return {
        "text": msg.get("content") or "",
        "reasoning": msg.get("reasoning_content") or msg.get("reasoning") or "",
        "finish": ch.get("finish_reason"),
        "usage": out.get("usage") or {},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--model", required=True)
    ap.add_argument("--sets", default="coding,coding-0.5")
    ap.add_argument("--only", default="", help="comma-separated fixture names")
    ap.add_argument("--max-tokens", type=int, default=700)
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    names = [n for n in (a.only.split(",") if a.only else FIXTURES)]
    bad = [n for n in names if n not in FIXTURES]
    if bad:
        raise SystemExit("unknown fixture(s): " + ", ".join(bad))
    sets = [s.strip() for s in a.sets.split(",") if s.strip() in SETS]
    if not sets:
        raise SystemExit("no known set in " + a.sets)

    report = {"model": a.model, "base_url": a.base_url, "fixtures": names, "runs": []}
    for set_name in sets:
        sampling = SETS[set_name]
        passed, secs_all, truncated = 0, 0.0, 0
        print(f"\n=== {a.model} · {set_name} {sampling}")
        for name in names:
            prompt, check = FIXTURES[name]
            t0 = time.monotonic()
            try:
                r = ask(a.base_url, a.model, prompt, sampling, a.max_tokens, a.timeout)
            except Exception as exc:                                  # noqa: BLE001
                print(f"  {name:<12} ERROR {exc}")
                report["runs"].append({"set": set_name, "fixture": name, "error": str(exc)})
                continue
            secs = time.monotonic() - t0
            secs_all += secs
            ok, why = False, "empty answer"
            if r["text"].strip():
                ok, why = check(r["text"])
            if r["finish"] == "length":
                truncated += 1
                ok, why = False, "truncated at max_tokens"
            passed += 1 if ok else 0
            print(f"  {name:<12} {'PASS' if ok else 'FAIL':<4} {secs:5.1f}s  "
                  f"{len(r['text']):5d} chars  {why}")
            report["runs"].append({
                "set": set_name, "fixture": name, "ok": bool(ok), "why": why, "secs": round(secs, 1),
                "chars": len(r["text"]), "finish": r["finish"], "usage": r["usage"],
                "answer": r["text"] if not ok else None,
            })
        total = len(names)
        print(f"  -> {passed}/{total} pass, {truncated} truncated, {secs_all:.0f}s "
              f"({secs_all / max(total, 1):.1f}s each)")
        report["runs"].append({"set": set_name, "summary": {
            "pass": passed, "total": total, "truncated": truncated, "secs": round(secs_all, 1)}})

    if a.out:
        from pathlib import Path
        Path(a.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
