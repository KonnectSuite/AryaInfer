"""Bounded local coding-agent evaluation through the OpenAI-compatible API.

Each session must read a fixture, edit it through a tool, and run its tests.
This evaluates the model/API tool loop, not the AryaAI desktop UI or SWE-bench.
Generated Python is syntax-checked and restricted, then tested in a timed child.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CASES = [
    {"name": "merge_sorted", "source": "def merge_sorted(a, b):\n    return list(a) + list(b)\n",
     "request": "Fix merge_sorted(a, b): return the sorted merge of two sorted integer lists. Preserve duplicates, handle empty inputs, and do not mutate either input.",
     "tests": "a=[1,3,3]; b=[2,3,4]; assert merge_sorted(a,b)==[1,2,3,3,3,4]; assert a==[1,3,3] and b==[2,3,4]; assert merge_sorted([],[])==[]; assert merge_sorted([],[-2,0])==[-2,0]; assert merge_sorted([-4,-1],[0])==[-4,-1,0]"},
    {"name": "chunked", "source": "def chunked(values, size):\n    return [values]\n",
     "request": "Fix chunked(values, size): return consecutive list chunks of at most size, preserve ordering, return [] for empty input, and raise ValueError for size <= 0. Do not mutate values.",
     "tests": "a=[1,2,3,4,5]; assert chunked(a,2)==[[1,2],[3,4],[5]]; assert a==[1,2,3,4,5]; assert chunked([],3)==[]; assert chunked([1],10)==[[1]]; assert chunked([1,2],1)==[[1],[2]]\nfor size in [0,-1]:\n    try: chunked([],size)\n    except ValueError: pass\n    else: raise AssertionError('invalid size accepted')"},
    {"name": "parse_pairs", "source": "def parse_pairs(lines):\n    return {}\n",
     "request": "Fix parse_pairs(lines): skip blank lines, split each other line on its first '=', strip whitespace from key/value, reject missing '=' or empty key with ValueError, preserve '=' in values, and let later duplicate keys win. Do not mutate input.",
     "tests": "a=[' x = a=b ', '', 'x=c', ' y = 2 ']; assert parse_pairs(a)=={'x':'c','y':'2'}; assert a==[' x = a=b ', '', 'x=c', ' y = 2 ']; assert parse_pairs([])=={}; assert parse_pairs(['key='])=={'key':''}\nfor lines in [['bad'],[' =x']]:\n    try: parse_pairs(lines)\n    except ValueError: pass\n    else: raise AssertionError('invalid line accepted')"},
]

APP_CASES = [
    {"name": "trim_history", "source": "def trim_history(messages, budget):\n    return list(messages)\n",
     "request": "Fix trim_history(messages, budget). Each message is a dict with integer cost. Validate budget and every cost are nonnegative, otherwise raise ValueError. Return the longest contiguous suffix of messages whose summed cost fits budget, in original order; never skip an oversized newer message to keep an older one. Include zero-cost messages when they are in that suffix. Do not mutate the input or its dicts.",
     "tests": "a=[{'cost':2,'text':'a'},{'cost':3,'text':'b'},{'cost':1,'text':'c'}]; assert trim_history(a,4)==a[1:]; assert trim_history(a,6)==a; assert trim_history(a,0)==[]; assert a==[{'cost':2,'text':'a'},{'cost':3,'text':'b'},{'cost':1,'text':'c'}]; assert trim_history([],0)==[]; assert trim_history([{'cost':1},{'cost':9}],3)==[]; assert trim_history([{'cost':0},{'cost':0}],0)==[{'cost':0},{'cost':0}]\nfor messages,budget in [([], -1),([{'cost':-1},{'cost':10}],0)]:\n    try: trim_history(messages,budget)\n    except ValueError: pass\n    else: raise AssertionError('negative cost or budget accepted')"},
    {"name": "merge_tool_results", "source": "def merge_tool_results(calls, results):\n    return list(results)\n",
     "request": "Fix merge_tool_results(calls, results). Calls and results are dicts with an id. Return one dict per call in call order: {'id': id, 'status':'done', 'content': content} when a result exists, otherwise {'id':id, 'status':'pending'}. The last result for an id wins; missing content defaults to ''. Ignore results with unknown ids. Reject duplicate call ids with ValueError. Do not mutate either input.",
     "tests": "calls=[{'id':'b'},{'id':'a'},{'id':'c'}]; results=[{'id':'a','content':'old'},{'id':'x','content':'ignore'},{'id':'b'},{'id':'a','content':'new'}]; assert merge_tool_results(calls,results)==[{'id':'b','status':'done','content':''},{'id':'a','status':'done','content':'new'},{'id':'c','status':'pending'}]; assert calls==[{'id':'b'},{'id':'a'},{'id':'c'}]; assert results[0]['content']=='old'; assert merge_tool_results([],results)==[]; assert merge_tool_results([{'id':'x'}],[])==[{'id':'x','status':'pending'}]\ntry: merge_tool_results([{'id':'a'},{'id':'a'}],[])\nexcept ValueError: pass\nelse: raise AssertionError('duplicate call accepted')"},
    {"name": "summarize_usage", "source": "def summarize_usage(events):\n    return {'input':0, 'output':0}\n",
     "request": "Fix summarize_usage(events). Events have request_id and optional nonnegative integer input/output token counts, which are cumulative snapshots for that request. For each request, keep the maximum seen input and output counts independently, then sum across requests. Missing counts mean 0. Reject any negative count with ValueError. Return {'input':total, 'output':total}; do not mutate events.",
     "tests": "a=[{'request_id':'a','input':10,'output':1},{'request_id':'b','input':5,'output':2},{'request_id':'a','input':8,'output':4},{'request_id':'a','input':10,'output':4},{'request_id':'c'}]; assert summarize_usage(a)=={'input':15,'output':6}; assert a[0]=={'request_id':'a','input':10,'output':1}; assert summarize_usage([])=={'input':0,'output':0}; assert summarize_usage([{'request_id':'x','output':3},{'request_id':'x','input':2}])=={'input':2,'output':3}\nfor event in [{'request_id':'x','input':-1},{'request_id':'x','output':-2}]:\n    try: summarize_usage([event])\n    except ValueError: pass\n    else: raise AssertionError('negative token count accepted')"},
]

TOOLS = [{"type": "function", "function": {"name": name, "description": desc,
          "parameters": {"type": "object", "properties": props, "required": required,
                         "additionalProperties": False}}}
         for name, desc, props, required in [
             ("read_file", "Read the fixture module.py", {"path": {"type": "string"}}, ["path"]),
             ("write_file", "Replace module.py with the corrected Python code",
              {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
             ("run_tests", "Run the fixture's regression tests", {}, []),
         ]]


def validate(source):
    tree = ast.parse(source)
    banned = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef,
              ast.Global, ast.Nonlocal, ast.With, ast.AsyncWith)
    # Normal container/string operations are part of the fixture vocabulary.
    # Rejecting set.add or dict.values turned valid solutions into harness failures.
    # Keep introspection, imports and I/O unavailable rather than requiring one
    # particular implementation style for these pure functions.
    attrs = {"append", "extend", "split", "strip", "items", "get", "lower", "isdigit", "copy",
             "add", "discard", "remove", "pop", "clear", "keys", "values", "setdefault", "update",
             "sort", "reverse", "count", "index", "startswith", "endswith", "join", "replace",
             "rstrip", "lstrip", "isspace", "upper", "casefold", "splitlines", "partition", "rsplit",
             "union", "intersection", "difference", "issubset", "issuperset", "isdisjoint"}
    for node in ast.walk(tree):
        if isinstance(node, banned):
            raise ValueError("Only standalone Python functions without imports are allowed")
        if isinstance(node, ast.Name) and (node.id.startswith("__") or node.id in
                {"open", "exec", "eval", "compile", "getattr", "setattr", "globals", "locals", "vars", "input", "breakpoint"}):
            raise ValueError("Forbidden name")
        if isinstance(node, ast.Attribute) and node.attr not in attrs:
            raise ValueError("Unsupported attribute: " + node.attr)
    return tree


def check(source, tests):
    try:
        validate(source)
        body = ("scope={'__builtins__':{k:__builtins__[k] for k in "
                "('len','range','enumerate','sorted','list','dict','tuple','min','max','ValueError','TypeError','AssertionError','StopIteration','int','str','float','zip','bool','sum','any','all','abs','isinstance','reversed','set','iter','next','map','filter')}}\n"
                "exec(" + repr(source) + ",scope)\nexec(" + repr(tests) + ",scope)\n")
        # __builtins__ is a module when the interpreter runs -c.
        body = "import builtins\n__builtins__=vars(builtins)\n" + body
        result = subprocess.run([sys.executable, "-I", "-c", body],
                                capture_output=True, text=True, timeout=5)
        return {"passed": result.returncode == 0, "detail": result.stderr[-1800:]}
    except Exception as exc:
        return {"passed": False, "detail": str(exc)}


def request(base, messages, think, model="qwen3.8-flash-next-iq3_xxs", sampling=None):
    payload = {"model": model, "messages": messages,
               "tools": TOOLS, "max_tokens": 1400,
               "reasoning_effort": think}
    # sampling None keeps the historical arm exactly: greedy, whatever the served config says.
    # A dict replaces the pinned temperature so a sampler A/B can put the whole set on the wire.
    payload.update({"temperature": 0} if sampling is None else sampling)
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=240) as response:
        result = json.load(response)
    return result, time.monotonic() - start


def session(base, case, run, think, model="qwen3.8-flash-next-iq3_xxs", sampling=None):
    messages = [{"role": "system", "content":
        "You are a coding agent in a bounded Python fixture. Read module.py, fix it with write_file, then run_tests. "
        "Only standalone functions, no imports, no classes, no filesystem or networking code. "
        "Use tools rather than merely describing a patch. After tests pass, give a short summary."},
        {"role": "user", "content": f"Session {case['name']}-{run}-{think}. {case['request']}"}]
    source, read, wrote, passed = case["source"], False, False, False
    trace, calls = [], []
    start = time.monotonic()
    for turn in range(9):
        result, secs = request(base, messages, think, model, sampling)
        msg = result["choices"][0]["message"]
        trace.append({"turn": turn, "seconds": secs, "response": result})
        messages.append(msg)
        if not msg.get("tool_calls"):
            break
        for call in msg["tool_calls"]:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"])
                if name == "read_file" and args.get("path") == "module.py":
                    read = True
                    output = {"content": source}
                elif name == "write_file" and args.get("path") == "module.py" and read:
                    validate(args["content"])
                    source, wrote = args["content"], True
                    output = {"written": True}
                elif name == "run_tests" and wrote:
                    output = check(source, case["tests"])
                    passed = output["passed"]
                else:
                    output = {"error": "Read module.py first, write module.py, then run_tests; no other paths allowed"}
            except Exception as exc:
                output = {"error": str(exc)}
            calls.append({"name": name, "result": output})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(output)})
    final_check = check(source, case["tests"])
    return {"case": case["name"], "run": run, "think": think,
            "passed": bool(read and wrote and passed and final_check["passed"]), "final_check": final_check,
            "seconds": time.monotonic() - start, "calls": calls, "source": source, "trace": trace}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--think", default="none")
    ap.add_argument("--model", default="qwen3.8-flash-next-iq3_xxs")
    ap.add_argument("--suite", choices=("core", "agent-app", "all"), default="core")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = []
    cases = CASES if a.suite == "core" else APP_CASES if a.suite == "agent-app" else CASES + APP_CASES
    for run in range(a.runs):
        for case in cases:
            try:
                row = session(a.url, case, run, a.think, a.model)
            except Exception as exc:
                row = {"case": case["name"], "run": run, "think": a.think, "passed": False, "error": str(exc)}
            rows.append(row)
            Path(a.out).write_text(json.dumps({"tool": __file__, "model": a.model, "suite": a.suite, "results": rows}, indent=2), encoding="utf-8")
            print(case["name"], run, "PASS" if row["passed"] else "FAIL", round(row.get("seconds", 0), 2), flush=True)
    return int(not all(row["passed"] for row in rows))


if __name__ == "__main__":
    sys.exit(main())
