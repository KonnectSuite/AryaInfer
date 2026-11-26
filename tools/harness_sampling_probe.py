"""tools/harness_sampling_probe.py - sampling calibration for the harness's everyday work.

The PLC probe measures industrial dialects; this one measures what the coding harnesses
actually ask Qwen3.8 Flash-Next for on this PC: an agent tool loop that edits and tests a
file, a single-file website or game build, a Python GUI, and office writing (email, quote,
minutes, changelog).  Every answer is checked by what it produced - parsed, compiled, the
numbers adding up - never by how it reads.  A set is judged by its pass counts.

    python tools/harness_sampling_probe.py --model qwen3.8-flash-next-gyro-m \
        --suites artifact,writing,agent --sets config,precise,coding --passes 2 \
        --out local-data/tuning/harness-gyro.json

`--sets config` sends no sampling keys at all, so it measures what a harness that names
none sees: the served config's block.  A named set puts its whole sampler on the wire
instead, so one loaded model answers every arm.  Thinking is switched off in every
request: this measures sampling, not reasoning (tools/thinking_mode_probe.py covers the
levels).  Failures keep the answer text, passes do not, and the JSON is rewritten after
every row, so a killed run keeps what it measured.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arya_agent_bench as agent          # noqa: E402  the session loop, its fixtures


def _fenced(text):
    """The fenced blocks joined, or the whole text when the model answered bare."""
    got = re.findall(r"```[a-zA-Z0-9+#_-]*\n(.*?)```", text, re.S)
    return "\n".join(got) if got else text


def _rep4(text):
    """Share of repeated word 4-grams: a boilerplate meter, recorded, never a gate."""
    words = re.findall(r"[a-zA-Z0-9']+", text.lower())
    grams = [tuple(words[i:i + 4]) for i in range(len(words) - 3)]
    if not grams:
        return 0.0
    return round(1.0 - len(set(grams)) / len(grams), 3)


def _amounts(text):
    return [float(m.replace(",", "")) for m in re.findall(r"\d[\d,]*\.\d{2}", text)]


def _near(nums, want, tol=0.015):
    return any(abs(n - want) <= tol for n in nums)


SUITES: dict[str, dict] = {"artifact": {}, "writing": {}}


def fixture(name, prompt, check, max_tokens=1600):
    suite = "artifact" if name.startswith(("web_", "game_", "gui_")) else "writing"
    SUITES[suite][name] = (prompt, check, max_tokens)


# ---------------------------------------------------------------- artifact

fixture("web_page",
        "Build a complete single-file HTML landing page for 'Northline Bikes', a bicycle "
        "repair shop: a sticky header with four nav links, a hero with a headline and a "
        "call-to-action button, three service cards, a three-row price table, and a "
        "contact footer. All CSS inline in a <style> block. Return only the HTML.",
        lambda t: _check_html(t, need=("<!doctype html", "</html>", "<title", "Northline")),
        max_tokens=8192)

fixture("game_memory",
        "Create a memory (concentration) game as one HTML file: a 4x3 grid of cards, click "
        "to flip two, matched pairs stay open, a move counter, and a restart button. Inline "
        "CSS and JavaScript. Return only the HTML.",
        lambda t: _check_html(t, need=("<!doctype html", "</html>", "<script"),
                              any_of=("addeventlistener", "onclick"),
                              any_of2=("restart", "reset", "new game")),
        max_tokens=8192)


def _check_html(text, need, any_of=None, any_of2=None):
    code = _fenced(text).strip().lstrip("`").strip()
    low = code.lower()
    for n in need:
        if n.lower() not in low:
            return False, f"missing {n}"
    if code.count("<script") != code.count("</script>"):
        return False, "unbalanced <script> tags"
    if low.count("<div") != low.count("</div>"):
        return False, "unbalanced <div> tags"
    if any_of and not any(a in low for a in any_of):
        return False, "no event handler (" + "/".join(any_of) + ")"
    if any_of2 and not any(a in low for a in any_of2):
        return False, "no restart (" + "/".join(any_of2) + ")"
    if len(code) < 1500:
        return False, f"only {len(code)} chars of markup"
    return True, ""


fixture("gui_converter",
        "Write a Python tkinter app named 'Unit Converter': an entry field, two buttons "
        "(Celsius to Fahrenheit, Fahrenheit to Celsius), a result label, and bad input "
        "shows a message instead of crashing. Return only the code.",
        lambda t: _check_py(t, need=("tkinter",)),
        max_tokens=2000)


def _check_py(text, need=()):
    code = _fenced(text).strip().lstrip("`").strip()
    for n in need:
        if n not in code:
            return False, f"missing {n}"
    try:
        compile(code, "<fixture>", "exec")
    except SyntaxError as exc:
        return False, f"does not compile: {exc}"
    if not re.search(r"\.mainloop\(|Tk\(\)", code):
        return False, "no mainloop or Tk() window"
    if not re.search(r"messagebox|try:", code):
        return False, "nothing handles bad input"
    return True, ""


# ---------------------------------------------------------------- writing

EMAIL = ("Write a short professional email to a long-standing client, Ms. Alvarez: our "
         "hourly rate changes from $120 to $138 on March 3, thank her for the good work "
         "we share, offer a call about the projects in flight. At most 170 words. Use the "
         "exact subject line 'Rate update on March 3'. Plain text.")

fixture("email_rate", EMAIL,
        lambda t: _check_email(t), max_tokens=900)


def _check_email(text):
    low = text.lower()
    if "rate update on march 3" not in low:
        return False, "exact subject line missing"
    if "alvarez" not in low:
        return False, "no greeting to the client by name"
    if "$120" not in text or "$138" not in text:
        return False, "one of $120 / $138 missing"
    if "march 3" not in low:
        return False, "no effective date"
    if not re.search(r"thank|appreciate", low):
        return False, "no thanks"
    if "call" not in low:
        return False, "no call offer"
    if len(text.split()) > 190:
        return False, f"{len(text.split())} words over the 170 cap"
    return True, ""


QUOTE = ("Make a quote document for the client Blue Harbor Cafe: 12 counter stools at "
         "$149.00 each, 1 custom oak bar top at $1250.00, 5 pendant lights at $19.90 each. "
         "Give each line a quantity, a unit price and a line total, then a subtotal, 19% "
         "VAT and the grand total. Use decimal points (no commas inside numbers, no other "
         "currency symbols).")

fixture("quote_cafe", QUOTE,
        lambda t: _check_quote(t), max_tokens=900)


def _check_quote(text):
    nums = _amounts(text)
    if not nums:
        return False, "no money amounts at all"
    for want, label in ((1788.00, "stools line 12 x 149.00 = 1788.00"),
                        (1250.00, "bar top line 1250.00"),
                        (99.50, "pendants line 5 x 19.90 = 99.50")):
        if not _near(nums, want):
            return False, f"missing {label}"
    if not _near(nums, 3137.50):
        return False, "subtotal 3137.50 missing or wrong"
    if not _near(nums, 596.125):
        return False, "19% VAT (596.12/596.13) missing or wrong"
    if not _near(nums, 3733.625, tol=0.02):
        return False, "grand total (3733.62/3733.63) missing or wrong"
    if "blue harbor" not in text.lower():
        return False, "client name missing"
    return True, ""


NOTES = ("Turn these raw notes into clean meeting minutes with exactly the three sections "
         "'Decisions', 'Actions', 'Open questions' and bullet lines only, no prose: "
         "we said deploy May 6 - dana owns the runbook, still unsure whether the staging "
         "budget covers two more VMs, ian to price them by friday, parking lot: move the "
         "standup earlier, agreed the api freezes monday night.")

fixture("minutes_notes", NOTES,
        lambda t: _check_minutes(t), max_tokens=900)


def _check_minutes(text):
    low = text.lower()
    for sec in ("decisions", "actions", "open questions"):
        if sec not in low:
            return False, f"no '{sec}' section"
    bullets = [ln for ln in text.splitlines() if re.match(r"^\s*[-*•]", ln)]
    if len(bullets) < 5:
        return False, f"only {len(bullets)} bullet lines"
    if "dana" not in low or "ian" not in low:
        return False, "an owner is missing"
    if "may 6" not in low:
        return False, "the deploy date is missing"
    return True, ""


CHANGELOG = ("Write changelog entries for release 1.4.0 from these commit lines: "
             "'a1b9c2d add csv export to the reports screen', "
             "'f4e2d1a fix crash when a filter date was empty', "
             "'c9d0e1b add dark mode toggle in settings', "
             "'b2c3d4e fix slow search on large catalogs'. "
             "Group under exactly 'Added:' and 'Fixed:', one entry per line starting with "
             "the commit hash, imperative voice, keep every hash.")

fixture("changelog_140", CHANGELOG,
        lambda t: _check_changelog(t), max_tokens=700)


def _check_changelog(text):
    if "added:" not in text.lower() or "fixed:" not in text.lower():
        return False, "not grouped under Added: and Fixed:"
    for h in ("a1b9c2d", "f4e2d1a", "c9d0e1b", "b2c3d4e"):
        if h not in text:
            return False, f"hash {h} lost"
    lines = [ln for ln in text.splitlines() if re.search(r"\b[a-f0-9]{7}\b", ln)]
    if len(lines) < 4:
        return False, f"only {len(lines)} entries carry a hash"
    return True, ""


# ---------------------------------------------------------------- sets

SETS = {
    "config": None,                                        # send no keys: the served config decides
    "current": {"temperature": 0.7, "top_p": 0.9, "top_k": 20, "presence_penalty": 0.0},
    "precise": {"temperature": 0.3, "top_p": 0.9, "top_k": 20, "presence_penalty": 0.0},
    "coding": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "presence_penalty": 0.0},
    "balanced": {"temperature": 0.7, "top_p": 0.95, "top_k": 40, "min_p": 0.02,
                 "repetition_penalty": 1.02},
}


def body(model, messages, sampling, max_tokens, tools=None, effort="off"):
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens,
               "reasoning_effort": effort, "stream": False}
    if sampling:
        payload.update(sampling)
    if tools:
        payload["tools"] = tools
    return payload


def ask(base, model, text, sampling, max_tokens, timeout, effort="off"):
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body(model, [{"role": "user", "content": text}],
                                                     sampling, max_tokens, effort=effort)).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    ch = out["choices"][0]
    msg = ch.get("message") or {}
    return {"text": msg.get("content") or "", "finish": ch.get("finish_reason"),
            "usage": out.get("usage") or {}}


# ---------------------------------------------------------------- run

def run_suite(base, model, suite, set_name, sampling, pass_no, timeout, rows, effort="off"):
    for name, (prompt, check, max_tokens) in SUITES[suite].items():
        t0 = time.monotonic()
        try:
            r = ask(base, model, prompt, sampling, max_tokens, timeout, effort=effort)
        except Exception as exc:                                      # noqa: BLE001
            print(f"  {name:<14} ERROR {exc}", flush=True)
            rows.append({"suite": suite, "set": set_name, "pass": pass_no,
                         "fixture": name, "effort": effort, "error": str(exc)})
            continue
        secs = time.monotonic() - t0
        ok, why = (False, "empty answer")
        if r["text"].strip():
            ok, why = check(r["text"])
        if r["finish"] == "length":
            ok, why = False, "truncated at max_tokens"
        print(f"  {name:<14} {'PASS' if ok else 'FAIL':<4} {secs:6.1f}s "
              f"{len(r['text']):6d} chars  rep4={_rep4(r['text'])}  {why}", flush=True)
        rows.append({"suite": suite, "set": set_name, "pass": pass_no, "fixture": name,
                     "effort": effort,
                     "ok": bool(ok), "why": why, "secs": round(secs, 1),
                     "chars": len(r["text"]), "rep4": _rep4(r["text"]),
                     "finish": r["finish"], "usage": r["usage"],
                     "answer": None if ok else r["text"][:4000]})


def run_agent(base, model, set_name, sampling, pass_no, rows, effort="off"):
    for case in agent.CASES:
        t0 = time.monotonic()
        try:
            row = agent.session(base, case, pass_no, effort, model, sampling or None)
        except Exception as exc:                                      # noqa: BLE001
            print(f"  {case['name']:<14} ERROR {exc}", flush=True)
            rows.append({"suite": "agent", "set": set_name, "pass": pass_no,
                         "fixture": case["name"], "effort": effort, "error": str(exc)})
            continue
        print(f"  {case['name']:<14} {'PASS' if row['passed'] else 'FAIL':<4} "
              f"{time.monotonic() - t0:6.1f}s  turns={len(row['trace'])}", flush=True)
        rows.append({"suite": "agent", "set": set_name, "pass": pass_no,
                     "fixture": case["name"], "effort": effort,
                     "ok": bool(row["passed"]),
                     "secs": round(row["seconds"], 1), "turns": len(row["trace"]),
                     "calls": len(row["calls"])})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--model", required=True)
    ap.add_argument("--suites", default="artifact,writing,agent")
    ap.add_argument("--sets", default="config,precise,coding,balanced")
    ap.add_argument("--efforts", default="off",
                    help="thinking levels to arm with, comma separated: off,low,medium,high")
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    suites = [s.strip() for s in a.suites.split(",") if s.strip()]
    sets = [s.strip() for s in a.sets.split(",") if s.strip()]
    efforts = [e.strip() for e in a.efforts.split(",") if e.strip()]
    bad = ([s for s in sets if s not in SETS]
           + [s for s in suites if s not in ("artifact", "writing", "agent")]
           + [e for e in efforts if e not in ("off", "low", "medium", "high")])
    if bad:
        raise SystemExit("unknown suite, set or effort: " + ", ".join(bad))

    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []

    def save():
        out_path.write_text(json.dumps({"model": a.model, "base_url": a.base_url,
                                        "rows": rows}, indent=1), encoding="utf-8")

    for pass_no in range(a.passes):                       # passes outer, arms inner: the
        for set_name in sets:                             # same prompt sees every arm
            for effort in efforts:                        # sampling x thinking: a fixture
                sampling = SETS[set_name]                 # under every arm sees both dials
                print(f"\n=== pass {pass_no} · {set_name} · think {effort} "
                      f"{sampling if sampling else '(served config)'}")
                if "artifact" in suites:
                    run_suite(a.base_url, a.model, "artifact", set_name, sampling,
                              pass_no, a.timeout, rows, effort=effort)
                if "writing" in suites:
                    run_suite(a.base_url, a.model, "writing", set_name, sampling,
                              pass_no, a.timeout, rows, effort=effort)
                if "agent" in suites:
                    run_agent(a.base_url, a.model, set_name, sampling, pass_no, rows,
                              effort=effort)
                save()

    save()
    print(f"\nwrote {out_path} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
