# Forced draft-depth arms for aryainfer (run from the repo root): python tools/qwen38_force_bench.py 8192,32768 default=0 f4=4
import json, os, re, subprocess, sys, threading, time
sys.path.insert(0, "tools")
from strata_tokenizer import Tokenizer

EXE = os.path.abspath("build-poly/aryainfer.exe")
os.environ["PATH"] = r"C:\AI\Strata-data\cuda\13.1.2\bin\x64;C:\AI\Strata-data\cuda\13.1.2\bin;" + os.environ["PATH"]
MODEL = r"C:\AI\Strata-data\models\qwen38-27b\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf"
FILLER = ("The harbor fills with fog each morning, and the cranes move slowly along the water while the crews check "
          "the ropes and the tide tables.  Every crate has a number painted on its side, and the ledger keeps a line "
          "for each one.  ")
TAIL = ("Now write a long, detailed technical explanation of how a bicycle drivetrain works, covering the chain, the "
        "cassette, the derailleurs, the chainrings and the shifters, in at least six paragraphs. Do not stop early.")

def prompt_ids(tok, tokens):
    n = len(tok.encode(FILLER)); tail = tok.encode(TAIL)
    reps = max(1, (tokens - len(tail)) // n)
    return (tok.encode(FILLER * reps + TAIL))[:tokens]

def run(ctx, extra, max_new=128, tokens=8000, env=None):
    tok = Tokenizer.from_gguf(MODEL)
    ids = prompt_ids(tok, min(tokens, ctx - max_new - 8))
    line_txt = "GEN %d temperature=0 %s\n" % (max_new, ",".join(map(str, ids)))
    cmd = [EXE, "--model", MODEL, "--serve", "--max-context", str(ctx), "--kv", "q4_0", "--prompt-batch", "512", "--report-drafts", *extra]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", bufsize=1,
                         env={**os.environ, "STRATA_GDN_MMA": "1", **(env or {})})
    stats = {}
    def rd():
        for line in p.stderr:
            if "strata serve: prompt " in line:
                m = re.search(r"prompt (\d+) tokens = (\d+) reused \+ (\d+) read in ([\d.]+) ms \(([\d.]+) tok/s\), "
                              r"(\d+) generated in ([\d.]+) ms \(([\d.]+) tok/s\)", line)
                if m:
                    stats.update(prompt=int(m.group(1)), prefill_ms=float(m.group(4)), prefill=float(m.group(5)),
                                 generated=int(m.group(6)), decode_ms=float(m.group(7)), decode=float(m.group(8)))
                if "drafts by pos:" in line: stats["pos"] = line.split("pos:",1)[1].strip()
                m = re.search(r"drafts accepted (\d+) of (\d+)", line)
                if m:
                    stats.update(accepted=int(m.group(1)), offered=int(m.group(2)))
    def wr():
        try:
            p.stdin.write(line_txt); p.stdin.flush()
        except OSError:
            pass
    threading.Thread(target=rd, daemon=True).start()
    time.sleep(2.5)
    threading.Thread(target=wr, daemon=True).start()
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline and "decode" not in stats and p.poll() is None:
        time.sleep(0.2)
    time.sleep(0.3)
    p.kill(); time.sleep(0.2)
    return stats


arms = [a.split("=") for a in sys.argv[2:]]
for ctx in map(int, sys.argv[1].split(",")):
    for name, force in arms:
        s = run(ctx, [], 256, ctx - 400, {"STRATA_FORCE_GUESSES": force} if force != "0" else {})
        print("ctx %6d %-8s prefill %8s decode %6s acc %s/%s | %s" % (ctx, name, s.get("prefill"), s.get("decode"),
              s.get("accepted"), s.get("offered"), s.get("pos")), flush=True)
