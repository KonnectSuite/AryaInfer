# Draft-depth / drafting arms for aryainfer (run from the repo root):
#   python tools/qwen38_force_bench.py 8192,32768 default=0 f4=4
#   python tools/qwen38_force_bench.py 8192,32768 --extra "--lookup-chain 7" chain7=0
import argparse, json, os, re, shlex, subprocess, sys, threading, time
sys.path.insert(0, "tools")
from strata_tokenizer import Tokenizer

DEFAULT_EXE = os.environ.get("QWEN38_EXE") or os.path.abspath("build-arya/aryainfer.exe")
DEFAULT_MODEL = os.environ.get("QWEN38_MODEL") or r"C:\AI\Strata-data\models\qwen38-27b\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf"
DEFAULT_PATH = r"C:\AI\Strata-data\cuda\13.1.2\bin\x64;C:\AI\Strata-data\cuda\13.1.2\bin"
FILLER = ("The harbor fills with fog each morning, and the cranes move slowly along the water while the crews check "
          "the ropes and the tide tables.  Every crate has a number painted on its side, and the ledger keeps a line "
          "for each one.  ")
TAIL = ("Now write a long, detailed technical explanation of how a bicycle drivetrain works, covering the chain, the "
        "cassette, the derailleurs, the chainrings and the shifters, in at least six paragraphs. Do not stop early.")


def prompt_ids(tok, tokens, prompt_text=None):
    if prompt_text is not None:
        return tok.encode(prompt_text)[:tokens]
    n = len(tok.encode(FILLER)); tail = tok.encode(TAIL)
    reps = max(1, (tokens - len(tail)) // n)
    return (tok.encode(FILLER * reps + TAIL))[:tokens]


def run(exe, model, ctx, extra, max_new, tokens, kv, prompt_batch, timeout, env=None, prompt_text=None):
    tok = Tokenizer.from_gguf(model)
    ids = prompt_ids(tok, min(tokens, ctx - max_new - 8), prompt_text)
    line_txt = "GEN %d temperature=0 %s\n" % (max_new, ",".join(map(str, ids)))
    cmd = [exe, "--model", model, "--serve", "--max-context", str(ctx), "--kv", kv,
           "--prompt-batch", prompt_batch, "--report-drafts", *extra]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", bufsize=1,
                         env={**os.environ, "PATH": DEFAULT_PATH + ";" + os.environ.get("PATH", ""),
                              "STRATA_GDN_MMA": "1", **(env or {})})
    stats = {}
    def rd():
        for line in p.stderr:
            if "strata serve: prompt " in line:
                m = re.search(r"prompt (\d+) tokens = (\d+) reused \+ (\d+) read in ([\d.]+) ms \(([\d.]+) tok/s\), "
                              r"(\d+) generated in ([\d.]+) ms \(([\d.]+) tok/s\)", line)
                if m:
                    stats.update(prompt=int(m.group(1)), prefill_ms=float(m.group(4)), prefill=float(m.group(5)),
                                 generated=int(m.group(6)), decode_ms=float(m.group(7)), decode=float(m.group(8)))
                if "drafts by pos:" in line: stats["pos"] = line.split("pos:", 1)[1].strip()
                m = re.search(r"drafts accepted (\d+) of (\d+)", line)
                if m:
                    stats.update(accepted=int(m.group(1)), offered=int(m.group(2)))
    def wr():
        try:
            p.stdin.write(line_txt); p.stdin.flush()
        except OSError:
            pass
    toks = []
    def ro():
        for line in p.stdout:
            if line.startswith("T "): toks.append(int(line[2:]))
    threading.Thread(target=ro, daemon=True).start()
    threading.Thread(target=rd, daemon=True).start()
    time.sleep(2.5)
    threading.Thread(target=wr, daemon=True).start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and "decode" not in stats and p.poll() is None:
        time.sleep(0.2)
    time.sleep(0.3)
    p.kill(); time.sleep(0.2)
    stats["text"] = tok.decode(toks)[:160].replace(chr(10), " ")
    return stats


def main(argv):
    ap = argparse.ArgumentParser(description="Draft-depth and drafting arms for aryainfer")
    ap.add_argument("contexts", help="comma-separated context sizes, e.g. 8192,32768")
    ap.add_argument("arms", nargs="*", help="name=forced-guesses; 0 leaves STRATA_FORCE_GUESSES unset")
    ap.add_argument("--exe", default=DEFAULT_EXE)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--kv", default="q4_0")
    ap.add_argument("--prompt-batch", default=os.environ.get("PB", "512"))
    ap.add_argument("--max-new", type=int, default=256)
    ap.add_argument("--tokens-from-ctx", type=int, default=400)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--extra", action="append", default=[],
                    help="extra engine arguments; repeatable, each value shell-split")
    ap.add_argument("--prompt-file", help="use this UTF-8 text instead of the tiled filler prompt")
    ap.add_argument("--json", action="store_true", help="one JSON object per arm")
    args = ap.parse_args(argv)

    extra = []
    for chunk in args.extra:
        extra.extend(shlex.split(chunk))
    prompt_text = None
    if args.prompt_file:
        with open(args.prompt_file, encoding="utf-8") as f:
            prompt_text = f.read()
    arms = [a.split("=", 1) for a in args.arms] or [("default", "0")]

    for ctx in map(int, args.contexts.split(",")):
        for name, force in arms:
            env = {"STRATA_FORCE_GUESSES": force} if force != "0" else {}
            s = run(args.exe, args.model, ctx, extra, args.max_new, ctx - args.tokens_from_ctx,
                    args.kv, args.prompt_batch, args.timeout, env, prompt_text)
            row = {"ctx": ctx, "arm": name, "force_guesses": force, "extra": extra, **s}
            if args.json:
                print(json.dumps(row), flush=True)
            else:
                print("ctx %6d %-8s prefill %8s decode %6s acc %s/%s | %s" % (
                    ctx, name, s.get("prefill"), s.get("decode"), s.get("accepted"),
                    s.get("offered"), s.get("pos")), flush=True)
            if os.environ.get("SHOW_TEXT"):
                print("   ", s.get("text"), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
