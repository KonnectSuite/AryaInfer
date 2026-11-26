"""Verify and A/B the 2026-11-20 engine update on this host (PolyStrata poly.10 + the installed Strata 0.1.63).

Two modes:
    python ab_poly_2026_11_20.py serve   the shipped config exactly as START-HERE starts it (port 8080)
    python ab_poly_2026_11_20.py ab      interleaved old (engine-backup-0.1.59.1) vs new (engine-poly) poly build

Every arm starts its own server, so an arm can swap the engine binary.  The card's clock, power and
temperature are sampled while each request runs, because on this laptop a single reading is worth little
(docs/HOST-RTX-PRO-2000-LAPTOP.md, "How much one number here is worth").
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import statistics
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import zlib

ROOT = pathlib.Path(r"C:\Users\kphung\AryaCode\KonnectSuite\AryaInfer")
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
BASE_CFG = ROOT / "strata-qwen36-200k.json"
BACKUP = pathlib.Path(r"C:\Users\kphung\AryaCode\KonnectSuite\AryaInfer\engine-backup-0.1.59.1\poly\strata-poly.exe")
INSTALLED = ROOT / "engine-poly" / "strata-poly.exe"
LOGDIR = pathlib.Path(r"C:\Users\kphung\AryaCode\KonnectSuite\poly-update-2026-11-20")
LOGDIR.mkdir(exist_ok=True)
OUT = LOGDIR / "rows.jsonl"


def nvidia(query: str) -> list[float]:
    try:
        r = subprocess.run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        return [float(x) for x in r.stdout.replace("\n", ",").split(",") if x.strip()]
    except Exception:
        return []


class Telemetry:
    def __init__(self) -> None:
        self.samples: list[tuple] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.is_set():
            v = nvidia("clocks.sm,power.draw,temperature.gpu")
            if len(v) >= 3:
                self.samples.append(tuple(v[:3]))
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
        col = lambda i: [s[i] for s in self.samples]
        return {"sm_med": round(statistics.median(col(0))), "w_med": round(statistics.median(col(1)), 1),
                "c_max": round(max(col(2)))}


def post(msgs, max_tokens, timeout=1800) -> dict:
    body = {"messages": msgs, "max_tokens": max_tokens, "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t1 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = json.loads(r.read().decode())
    t = b.get("timings") or {}
    msg = b["choices"][0]["message"]
    return {"prompt_n": t.get("prompt_n"), "prompt_s": t.get("prompt_per_second"),
            "decode_n": t.get("predicted_n"), "decode_s": t.get("predicted_per_second"),
            "wait_s": round(time.time() - t1, 2),
            "text": (msg.get("content") or "")[:200]}


def png(w=96, h=96, rgb=(200, 30, 30)) -> str:
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return base64.b64encode(data).decode()


HAY = None


def haystack(n_tokens: int) -> str:
    global HAY
    if HAY is None:
        files = []
        for d, pat in (("docs", "*.md"), ("serve", "*.py"), ("src", "*.cpp")):
            files += sorted((ROOT / d).rglob(pat))
        parts = []
        for f in files:
            try:
                parts.append(f.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
        HAY = "\n".join(parts)
    return HAY[: int(n_tokens * 3.2)]


def engine_log(path: pathlib.Path) -> dict:
    out: dict = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if "READY" in s and "max" not in out:
            out["ready"] = s[:160]
        elif "MiB of VRAM free with everything loaded" in s:
            out["vram_free"] = s[:160]
        elif "expert cache" in s and "slots" in s:
            out["cache"] = s[:200]
        elif "experts" in s and "VRAM" in s and "cache" not in out:
            out["experts"] = s[:200]
    return out


PORT = 8080
ENV_EXTRA: dict = {}


def serve_arm(tag: str, exe: pathlib.Path | None, port: int, cases, image: bool = False) -> dict:
    global PORT
    PORT = port
    cfg = json.loads(BASE_CFG.read_text(encoding="utf-8"))
    cfg["port"] = port
    log = LOGDIR / ("%s_%d.log" % (tag, int(time.time())))
    cfg["log"] = str(log)
    if exe is not None:
        cfg["exe"] = str(exe)
    cpath = LOGDIR / ("%s.config.json" % tag)
    cpath.write_text(json.dumps(cfg, indent=1), encoding="utf-8")

    env = dict(os.environ)
    env.update(ENV_EXTRA)
    for d in cfg.get("lib_dirs") or []:
        if pathlib.Path(d).is_dir():
            env["PATH"] = d + os.pathsep + env["PATH"]

    before = nvidia("memory.used")
    row: dict = {"arm": tag, "exe": cfg["exe"], "exe_bytes": (pathlib.Path(cfg["exe"]).stat().st_size
                                                              if pathlib.Path(cfg["exe"]).exists() else None),
                 "vram_used_before_mib": before[0] if before else None,
                 "started": time.strftime("%H:%M:%S")}
    slog = LOGDIR / ("%s.server.log" % tag)
    with open(slog, "w", encoding="utf-8", errors="ignore") as sout:
        proc = subprocess.Popen([PY, str(ROOT / "serve" / "server.py"), "--engine", "strata",
                                 "--config", str(cpath), "--port", str(port)],
                                cwd=str(ROOT), env=env, stdout=sout, stderr=subprocess.STDOUT)
    try:
        t0 = time.time()
        while time.time() - t0 < 900:
            if proc.poll() is not None:
                row["error"] = "server exited %s" % proc.returncode
                break
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % port, timeout=5):
                    break
            except Exception:
                time.sleep(3)
        else:
            row["error"] = "not ready in 900 s"
        if "error" not in row:
            row["ready_s"] = round(time.time() - t0, 1)
            row["engine_log_after_ready"] = engine_log(log)
            row["warmup"] = post([{"role": "user", "content": "Say hi."}], 8)
            for case, n, max_new in cases:
                msgs = [{"role": "user", "content": haystack(n) + "\n\nAnswer with the single word: OK"}]
                with Telemetry() as tel:
                    p = post(msgs, 8)
                c = {"prompt_n": p["prompt_n"], "prefill_tok_s": p["prompt_s"],
                     "prefill_wait_s": p["wait_s"], "prefill_telemetry": tel.summary()}
                msgs2 = msgs + [{"role": "assistant", "content": "OK"},
                                {"role": "user", "content": "Write a Python function that merges two lists of "
                                                            "intervals, with a docstring and asserts. Do not stop early."}]
                dec, tel_rows = [], []
                for _ in range(2):
                    with Telemetry() as t2:
                        d = post(msgs2, max_new)
                    dec.append(d["decode_s"])
                    tel_rows.append(t2.summary())
                c["decode_tok_s"] = [round(x, 2) for x in dec]
                c["decode_med"] = round(statistics.median(dec), 2)
                c["decode_telemetry"] = tel_rows
                c["sample_text"] = d["text"][:120]
                row[case] = c
            if image:
                data_uri = "data:image/png;base64," + png()
                msgs = [{"role": "user", "content": [
                    {"type": "text", "text": "What colour is this image? One word."},
                    {"type": "image_url", "image_url": {"url": data_uri}}]}]
                try:
                    with Telemetry() as t3:
                        r = post(msgs, 24, timeout=1800)
                    row["image"] = {"ok": True, "prompt_n": r["prompt_n"], "wait_s": r["wait_s"],
                                    "text": r["text"], "telemetry": t3.summary()}
                except Exception as e:  # the encoder path is what is under test
                    row["image"] = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
            row["engine_log_after_run"] = engine_log(log)
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        stop_t0 = time.time()
        while time.time() - stop_t0 < 60 and nvidia("memory.used") and nvidia("memory.used")[0] > 500:
            time.sleep(2)
    return row


CASES = [("short", 64, 64), ("mid", 512, 64)]


def main() -> int:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "serve").lower()
    rows: list[dict] = []
    if mode == "serve":
        rows.append(serve_arm("serve-8080", None, 8080, CASES, image=True))
    elif mode == "cool":
        # the GPU reaches 89 C after a few minutes of this and drops to a few hundred MHz, so each arm here
        # starts from a rested card: the run deliberately takes longer than the interleaved one
        order = [("new", INSTALLED), ("old", BACKUP), ("new", INSTALLED), ("old", BACKUP)]
        for i, (tag, exe) in enumerate(order):
            if not exe.exists():
                print("missing %s" % exe, flush=True)
                continue
            print("resting 120 s before %s-%d" % (tag, i), flush=True)
            time.sleep(120)
            rows.append(serve_arm("%s-cool-%d" % (tag, i), exe, 8124, CASES, image=(tag == "new" and i == 0)))
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(rows[-1]) + "\n")
    else:
        order = [("new", INSTALLED), ("old", BACKUP), ("old", BACKUP), ("new", INSTALLED)]
        for i, (tag, exe) in enumerate(order):
            if not exe.exists():
                print("missing %s" % exe, flush=True)
                continue
            rows.append(serve_arm("%s-%d" % (tag, i), exe, 8124, CASES, image=(tag == "new" and i == 0)))
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(rows[-1]) + "\n")
    for r in rows:
        print("\n=== %s (%s) ===" % (r["arm"], r.get("exe_bytes")), flush=True)
        if r.get("error"):
            print("  ERROR %s" % r["error"], flush=True)
            continue
        print("  ready %.1f s, warmup %.2f tok/s" % (r["ready_s"], (r.get("warmup") or {}).get("decode_s") or 0),
              flush=True)
        for case, _, _ in CASES:
            c = r.get(case) or {}
            print("  %-6s prefill %s tok in %.1f s (%s tok/s) decode %s tok/s %s %s" % (
                case, c.get("prompt_n"), c.get("prefill_wait_s") or 0, c.get("prefill_tok_s"),
                c.get("decode_med"), c.get("decode_tok_s"), (c.get("decode_telemetry") or [{}])[0]), flush=True)
        print("  log: %s" % json.dumps(r.get("engine_log_after_run") or r.get("engine_log_after_ready")), flush=True)
        if "image" in r:
            print("  image: %s" % json.dumps(r["image"])[:300], flush=True)
    if mode == "serve":
        with open(LOGDIR / "rows.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rows[0]) + "\n")
    return 0 if all(not r.get("error") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
