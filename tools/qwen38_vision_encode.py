r"""tools/qwen38_vision_encode.py - one image through `strata-vision`, for a strata-poly smoke or measure.

strata-vision is llama.cpp's mtmd behind a line protocol (serve/server.py's Vision class runs it the same way):
it prints READY, then each `ENC <image> <out>` line writes the image's embeddings to <out> and answers `OK <n>`,
where n is the number of tokens those embeddings stand for.  The paths are relative to the encoder's directory, so
this tool works in one that has no spaces (an ENC line is split at spaces).

    python tools/qwen38_vision_encode.py --image CARD.png --out card.sve
    -> "OK 576 -> C:\...\card.sve"

The file is what `strata-poly --images card.sve --image-pad <pad id>` reads; every run of the pad id in --tokens
becomes one row of it.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINES = Path(r"C:\AI\Strata-data\engines\strata-0.1.59")


def encode(exe: Path, mmproj: Path, model: Path, image: Path, out: Path, max_tokens: int = 1024,
           min_tokens: int = 1024, gpu: bool = True, ready_s: float = 180.0, encode_s: float = 180.0) -> int:
    """Start the encoder in a scratch directory, encode one image, stop it.  Returns the token count."""
    work = Path(tempfile.mkdtemp(prefix="qwen38-vision-", dir=Path(tempfile.gettempdir())))
    if " " in str(work):                      # an ENC line is split at spaces (#480)
        work = Path(r"C:\ProgramData\qwen38-vision-work")
        work.mkdir(parents=True, exist_ok=True)
    try:
        img = work / "image.png"
        shutil.copyfile(image, img)
        emb = work / "image.sve"
        args = [str(exe), "--mmproj", str(mmproj), "--model", str(model)]
        if gpu:
            args.append("--gpu")
        if max_tokens:
            args += ["--max-tokens", str(max_tokens)]
        if min_tokens:                       # mtmd refuses a Qwen-VL mmproj under 1024 image tokens
            args += ["--min-tokens", str(min_tokens)]
        env = None
        if ENGINES.is_dir():
            import os
            env = dict(os.environ)
            env["PATH"] = str(ENGINES) + os.pathsep + env.get("PATH", "")
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=str(work), env=env)

        def read_until(prefixes: tuple[str, ...], seconds: float) -> str:
            """The first stdout line that starts with one of `prefixes`; an empty string on timeout or exit."""
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                line = proc.stdout.readline()
                if line:
                    line = line.strip()
                    if line.startswith(prefixes):
                        return line
                    continue
                if proc.poll() is not None:
                    return ""
            return ""

        def why() -> str:
            try:
                return (proc.stderr.read() or "").strip()[-400:]
            except Exception:
                return ""

        ready = read_until(("READY",), ready_s)
        if not ready:
            raise SystemExit("the encoder did not start: " + (why() or "(no line)"))
        proc.stdin.write(f"ENC {img.name} {emb.name}\n")
        proc.stdin.flush()
        answer = read_until(("OK", "ERR"), encode_s)
        try:
            proc.stdin.write("QUIT\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        if not answer.startswith("OK"):
            raise SystemExit("the encoder did not read the image: " + (answer or why() or "(no line)"))
        count = int(answer.split()[1])
        shutil.copyfile(emb, out)
        return count
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", default=str(ENGINES / "strata-vision.exe"))
    ap.add_argument("--mmproj", default=r"C:\AI\Strata-data\models\qwen38-27b\mmproj-Qwen3.8-27B-BF16.gguf")
    ap.add_argument("--model", default=r"C:\AI\Strata-data\models\qwen38-27b\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf")
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--min-tokens", type=int, default=1024)
    ap.add_argument("--cpu", action="store_true", help="encode on the CPU (no --gpu)")
    a = ap.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    count = encode(Path(a.exe), Path(a.mmproj), Path(a.model), Path(a.image), out,
                   max_tokens=a.max_tokens, min_tokens=a.min_tokens, gpu=not a.cpu)
    print(f"OK {count} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
