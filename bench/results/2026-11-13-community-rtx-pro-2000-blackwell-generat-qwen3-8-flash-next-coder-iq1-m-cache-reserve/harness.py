"""Measured A/B of Coder settings on THIS host, with GPU telemetry.

Why a second harness: tune_kv_ab.py measured one round per arm and the same config
produced 7.2 and 40.0 tok/s on this laptop, so a single reading cannot separate two
arms. This one records what the card was doing (clock, power, temperature) while it
measured, warms the engine first, and repeats each case twice.

    python tune_ab2.py --arms base,noreserve --cases 2k,24k --passes 2

Each arm starts its own server (strata --serve below serve/server.py), so an arm can
change any start-up flag, the engine exe, or an env var.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = pathlib.Path(r"C:\Users\kphung\AryaCode\KonnectSuite\AryaInfer")
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
PORT = 8123
OUT = pathlib.Path(r"C:\Users\kphung\AryaCode\KonnectSuite\tune_ab2.jsonl")
LOGDIR = pathlib.Path(r"C:\Users\kphung\AryaCode\KonnectSuite\tune_ab2_logs")
LOGDIR.mkdir(exist_ok=True)
BASE_CFG = ROOT / "strata-coder-iq1_m.json"

# ---------------------------------------------------------------- arms
# set: flag -> value appended/replaced.  drop: flags removed with their value.
# extend: raw argv tail.  env: extra environment.  exe: engine binary.
ARMS: dict[str, dict] = {
    "base": {"why": "the shipped config, as it is today (reserve 300, 528 slots, 0 MiB free)"},
    "res812": {"why": "the engine's own first warning: --vram-reserve-mib 812",
               "set": {"--vram-reserve-mib": "812"}},
    "res1344": {"why": "the engine's #2065 warning level: keep >=1 GiB free at request start",
                "set": {"--vram-reserve-mib": "1344"}},
    "res812_mtpq4": {"why": "free the 675 MiB of draft experts for slots instead of reserving",
                      "set": {"--vram-reserve-mib": "812"}, "extend": ["--mtp-q4", "all"]},
    "mtpq4": {"why": "draft experts as 4-bit, same reserve: ~500 MiB more cache slots",
               "extend": ["--mtp-q4", "all"]},
    "pcores": {"why": "6 P-cores instead of 10 workers on 16 cores: less heat, the GPU gets the budget",
                "set": {"--pool-workers": "6"}, "extend": ["--pool-affinity", "p-cores"]},
    "pmeas": {"why": "let the engine time all vs p-cores on the pack's own experts",
               "extend": ["--pool-affinity", "measure"]},
    "mtpq4_pcores": {"why": "both levers together",
                      "extend": ["--mtp-q4", "all", "--pool-affinity", "measure"]},
    "pcfull": {"why": "12 checkpoints spread back from the end: a rewritten history rereads less",
                "set": {"--prompt-cache": "12"}, "extend": ["--prompt-cache-spread"]},
    "lookup": {"why": "prompt-lookup drafts after the MTP's: cheap when the code repeats",
                "extend": ["--lookup-chain", "4"]},
    "shortread": {"why": "read the turn's fresh text through the decode windows",
                   "set": {"--short-read": "128"}},
    "upstream": {"why": "the newest Strata engine (0.1.59.1) instead of the fork's 0.1.45",
                 "exe": r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build\strata.exe",
                 "lib_dirs": [r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build"]},
    "up_res812": {"why": "0.1.59.1 with the reserve its own #2065 warning asks for",
                  "exe": r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build\strata.exe",
                  "lib_dirs": [r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build"],
                  "set": {"--vram-reserve-mib": "812"}},
    "up_mtpq4": {"why": "0.1.59.1, draft experts in 4-bit: the 675 MiB goes to cache slots",
                 "exe": r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build\strata.exe",
                 "lib_dirs": [r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build"],
                 "extend": ["--mtp-q4", "all"]},
    "up_res812_mtpq4": {"why": "0.1.59.1, both: reserve for the driver and the draft layer out of VRAM",
                        "exe": r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build\strata.exe",
                        "lib_dirs": [r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build"],
                        "set": {"--vram-reserve-mib": "812"}, "extend": ["--mtp-q4", "all"]},
    "up_1344_mtpq4": {"why": "0.1.59.1, the full 1 GiB free plus 4-bit draft experts",
                      "exe": r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build\strata.exe",
                      "lib_dirs": [r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build"],
                      "set": {"--vram-reserve-mib": "1344"}, "extend": ["--mtp-q4", "all"]},
    "up_pcores": {"why": "0.1.59.1, 6 P-cores: less CPU heat on a shared heatsink",
                  "exe": r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build\strata.exe",
                  "lib_dirs": [r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build"],
                  "set": {"--pool-workers": "6"}, "extend": ["--pool-affinity", "p-cores"]},
    "up_res1344": {"why": "0.1.59.1 with the >=1 GiB free the #2065 warning asks for, nothing else changed",
                   "exe": r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build\strata.exe",
                   "lib_dirs": [r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build"],
                   "set": {"--vram-reserve-mib": "1344"}},
    "up_spec0": {"why": "0.1.59.1 with speculation off: what one token per engine step is worth",
                 "exe": r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build\strata.exe",
                 "lib_dirs": [r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build"],
                 "drop": ["--spec", "--spec-min-p"]},
    "up_spec2": {"why": "0.1.59.1 with a two-token draft: less to lose when acceptance is poor",
                 "exe": r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build\strata.exe",
                 "lib_dirs": [r"C:\Users\kphung\AryaCode\KonnectSuite\strata-upstream\build"],
                 "set": {"--spec": "2"}},
}


def nvidia(query: str) -> list[float]:
    try:
        r = subprocess.run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        return [float(x) for x in r.stdout.replace("\n", ",").split(",") if x.strip()]
    except Exception:
        return []


class Telemetry:
    """Samples clock/power/temperature while a request runs; a stalled request leaves a trace."""

    def __init__(self) -> None:
        self.samples: list[tuple] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.is_set():
            v = nvidia("clocks.sm,power.draw,temperature.gpu,memory.used")
            if len(v) >= 4:
                self.samples.append(tuple(v[:4]))
            self.stop.wait(0.25)

    def __enter__(self) -> "Telemetry":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop.set()
        self.thread.join(timeout=2)

    def summary(self) -> dict:
        if not self.samples:
            return {}
        def col(i):
            return [s[i] for s in self.samples]
        return {"sm_mhz": round(statistics.median(col(0))), "sm_max": round(max(col(0))),
                "w_med": round(statistics.median(col(1)), 1), "w_max": round(max(col(1)), 1),
                "c_max": round(max(col(2))), "vram_mib": round(statistics.median(col(3)))}


def post(msgs, max_tokens, temperature=0.0) -> dict:
    body = {"messages": msgs, "max_tokens": max_tokens, "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t1 = time.time()
    with urllib.request.urlopen(req, timeout=3600) as r:
        b = json.loads(r.read().decode())
    t = b.get("timings") or {}
    u = b.get("usage") or {}
    return {"prompt_n": t.get("prompt_n"), "prompt_s": t.get("prompt_per_second"),
            "decode_n": t.get("predicted_n"), "decode_s": t.get("predicted_per_second"),
            "wait_s": round(time.time() - t1, 2),
            "text": (b["choices"][0]["message"].get("content") or "")[:300]}


_HAY = None


def haystack(n_tokens: int) -> str:
    global _HAY
    if _HAY is None:
        files = []
        for d, pat in (("docs", "*.md"), ("src", "*.cpp"), ("src", "*.cu"),
                       ("include", "*.hpp"), ("serve", "*.py")):
            files += sorted((ROOT / d).rglob(pat))
        parts = []
        for f in files:
            try:
                parts.append(f.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
        _HAY = "\n".join(parts)
    need = int(n_tokens * 3.2)
    # a different slice per size, so the 24k prompt is not the 2k one plus context
    off = (n_tokens * 7) % 60_000
    return _HAY[off:off + need]


def read_engine_log(log: pathlib.Path) -> dict:
    out: dict = {}
    if not log.exists():
        return out
    text = log.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        s = line.strip()
        if "expert cache auto:" in s:
            out["cache_auto"] = s.split("generate:", 1)[-1].strip()
        elif "MiB of VRAM free with everything loaded" in s:
            out["vram_free"] = s.split("serve:", 1)[-1].strip()
        elif "slots, " in s and "policy is" in s:
            out["slots"] = s.split("generate:", 1)[-1].strip()
        elif "decode expert cache hit rate" in s:
            out["hit_rate"] = s.split("serve:", 1)[-1].strip()
        elif "WARNING: only" in s and "MiB of VRAM free at the start" in s:
            out["page_risk"] = s.split("serve:", 1)[-1].strip()
        elif s.startswith("strata generate: expert arena") or "expert arena:" in s:
            out["arena"] = s.split("generate:", 1)[-1].strip()
    return out


def run_arm(tag: str, spec: dict, case_list: list[tuple[str, int, int]]) -> dict:
    cfg = json.loads(BASE_CFG.read_text())
    args = list(cfg["args"])
    for flag, val in (spec.get("set") or {}).items():
        if flag in args:
            args[args.index(flag) + 1] = str(val)
        else:
            args += [flag, str(val)]
    for flag in spec.get("drop") or []:
        while flag in args:
            i = args.index(flag)
            del args[i:i + (2 if not args[i + 1].startswith("--") else 1)]
    args += list(spec.get("extend") or [])
    cfg["args"] = args
    cfg["port"] = PORT
    if spec.get("exe"):
        cfg["exe"] = spec["exe"]
    if spec.get("lib_dirs"):
        cfg["lib_dirs"] = spec["lib_dirs"]
    log = LOGDIR / f"{tag}_{int(time.time())}.log"
    cfg["log"] = str(log)
    cpath = pathlib.Path(tempfile.gettempdir()) / f"ab2_{tag}.json"
    cpath.write_text(json.dumps(cfg, indent=1))

    env = dict(os.environ)
    for d in cfg.get("lib_dirs") or []:
        if pathlib.Path(d).is_dir():
            env["PATH"] = d + os.pathsep + env["PATH"]
    for k, v in (spec.get("env") or {}).items():
        env[k] = str(v)

    row: dict = {"arm": tag, "why": spec.get("why"), "argv_tail": args[len(json.loads(BASE_CFG.read_text())["args"]):],
                 "started": time.strftime("%H:%M:%S")}
    slog = LOGDIR / f"{tag}.server.log"
    with open(slog, "w", encoding="utf-8", errors="ignore") as sout:
        proc = subprocess.Popen([PY, str(ROOT / "serve" / "server.py"), "--engine", "strata",
                                 "--config", str(cpath), "--port", str(PORT)],
                                cwd=str(ROOT), env=env, stdout=sout, stderr=subprocess.STDOUT)
    try:
        t0 = time.time()
        while time.time() - t0 < 900:
            if proc.poll() is not None:
                row["error"] = f"server exited {proc.returncode}"
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=5):
                    break
            except Exception:
                time.sleep(3)
        else:
            row["error"] = "not ready in 900 s"
        if "error" not in row:
            row["ready_s"] = round(time.time() - t0, 1)
            post([{"role": "user", "content": "Say hi."}], 8)
            post([{"role": "user", "content": "Write a short Python function with a docstring."}], 48)
            for case, n, max_new in case_list:
                text = haystack(n)
                msgs = [{"role": "user", "content": text + "\n\nAnswer with the single word: OK"}]
                with Telemetry() as tel:
                    p = post(msgs, 8)
                row.setdefault(case, {})["prefill"] = p["prompt_s"]
                row[case]["prompt_n"] = p["prompt_n"]
                row[case]["prefill_wait_s"] = p["wait_s"]
                dec, wait, tel_rows = [], [], []
                for rep in range(2):
                    msgs2 = msgs + [{"role": "assistant", "content": "OK"},
                                    {"role": "user", "content": "Now write a Python function that merges two "
                                                                "lists of intervals, with docstring and asserts. "
                                                                "Do not stop early."}]
                    with Telemetry() as tel2:
                        d = post(msgs2, max_new)
                    dec.append(d["decode_s"])
                    wait.append(d["wait_s"])
                    tel_rows.append(tel2.summary())
                    msgs = msgs2 + [{"role": "assistant", "content": d["text"]}]
                row[case]["decode"] = [round(x, 2) for x in dec]
                row[case]["decode_med"] = round(statistics.median(dec), 2)
                row[case]["wait_s"] = [round(x, 1) for x in wait]
                row[case]["telemetry"] = tel_rows
                # the next turn of the same conversation: what the user waits for
                msgs3 = msgs + [{"role": "user", "content": "Thanks. Reply with one short sentence."}]
                with Telemetry() as tel3:
                    r3 = post(msgs3, 24)
                row[case]["turn_reuse_n"] = r3["prompt_n"]
                row[case]["turn_wait_s"] = r3["wait_s"]
                row[case]["turn_telemetry"] = tel3.summary()
    finally:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        time.sleep(8)
    row["log"] = read_engine_log(log)
    return row


def summarise(rows: list[dict], case_list) -> str:
    lines = []
    for case, _, _ in case_list:
        lines.append(f"\n=== {case} ===")
        lines.append(f"{'arm':<15}{'decode':>9}{'spread':>13}{'prefill':>10}{'ppwait':>8}"
                     f"{'turn':>7}{'reuse':>7}{'slots':>7}{'free':>6}{'MHz':>6}{'W':>6}")
        base = None
        for r in rows:
            c = (r.get(case) or {})
            if not c.get("decode_med"):
                lines.append(f"{r['arm']:<15}{'--':>9}  {r.get('error') or 'no data'}")
                continue
            tag = r["arm"]
            dec = c["decode_med"]
            if base is None:
                base = dec
            spread = f"{min(c['decode']):.1f}-{max(c['decode']):.1f}"
            tel = (c.get("telemetry") or [{}])[0]
            flip = r.get("log", {}).get("vram_free") or ""
            free = "".join(ch for ch in flip.split(" ")[0] if ch.isdigit())
            lines.append(f"{tag:<15}{dec:>9.2f}{spread:>13}{c.get('prefill') or 0:>10.1f}"
                         f"{c.get('prefill_wait_s') or 0:>8.1f}{c.get('turn_wait_s') or 0:>7.1f}"
                         f"{str(c.get('turn_reuse_n')):>7}{str(r.get('log', {}).get('slots', '-'))[:5]:>7}"
                         f"{free:>6}{tel.get('sm_mhz', 0):>6}{tel.get('w_med', 0):>6}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="")
    ap.add_argument("--cases", default="2k,24k")
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    wanted = [x.strip() for x in a.arms.split(",") if x.strip()] or list(ARMS)
    cases = {"1k": ("1k", 1024, 96), "2k": ("2k", 2048, 96), "4k": ("4k", 4096, 96),
             "8k": ("8k", 8192, 96), "12k": ("12k", 12288, 96), "16k": ("16k", 16384, 96),
             "20k": ("20k", 20480, 96), "24k": ("24k", 24576, 96),
             "48k": ("48k", 49152, 64), "112k": ("112k", 114000, 48)}
    case_list = [cases[c.strip()] for c in a.cases.split(",") if c.strip() in cases]
    rows: list[dict] = []
    t0 = time.time()
    for p in range(a.passes):
        order = wanted if p % 2 == 0 else wanted[::-1]
        print(f"\n#### pass {p + 1}/{a.passes}: {' -> '.join(order)}", flush=True)
        for tag in order:
            print(f"=== {tag} ({ARMS[tag].get('why', '')}) ===", flush=True)
            row = run_arm(tag, ARMS[tag], case_list)
            rows.append(row)
            with open(a.out, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            print(json.dumps({k: v for k, v in row.items() if k not in ("why",)}, indent=1), flush=True)
    print(summarise(rows, case_list), flush=True)
    print(f"\n{round((time.time() - t0) / 60, 1)} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
