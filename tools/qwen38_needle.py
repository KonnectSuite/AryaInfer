"""tools/qwen38_needle.py - a needle at a measured context length, through the server's chat API.

Builds a prompt of about --tokens tokens of filler, hides one sentence in the middle, asks for it at the end, and
prints what came back with the usage the server reports.  It is the ladder's probe: run it at 32K, 64K, 88K and so
on and the answer either carries the needle or does not, and the prompt tokens say how much context was read.

    python tools/qwen38_needle.py --model qwen38-27b-iq3_xxs --tokens 60000

The server must be up with a run config whose context is at least --tokens plus the answer.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

FILLER = (
    "The harbor fills with fog each morning, and the cranes move slowly along the water while the crews "
    "check the ropes and the tide tables.  Every crate has a number painted on its side, and the ledger "
    "keeps a line for each one.  The office window looks over the pier, and the lamps come on before the "
    "boats do.  Nobody hurries at this hour, and the radios carry the same three words back and forth.  "
)


def build(tokenizer_dir: str, tokens: int, needle: str, question: str) -> str:
    """Filler of about `tokens` tokens with the needle at its middle, then the question."""
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    from strata_tokenizer import Tokenizer
    tok = Tokenizer.from_dir(tokenizer_dir)
    unit = max(1, len(tok.encode(FILLER)))
    body = FILLER * max(1, tokens // unit)
    half = len(body) // 2
    cut = body.find("\n", half)
    cut = half if cut < 0 else cut
    text = body[:cut] + "\n\n" + needle + "\n\n" + body[cut:] + "\n\nQuestion: " + question
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8081")
    ap.add_argument("--model", default="qwen38-27b-iq3_xxs")
    ap.add_argument("--tokenizer", default=r"C:\AI\Strata-data\models\qwen38-27b\tokenizer")
    ap.add_argument("--tokens", type=int, default=60000, help="the filler's size; the whole prompt is this plus a little")
    ap.add_argument("--needle", default="The passphrase of the vault is VULTURE-7319.")
    ap.add_argument("--question", default="What is the passphrase of the vault? Answer with the passphrase only.")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--timeout", type=float, default=3600.0)
    a = ap.parse_args()
    text = build(a.tokenizer, a.tokens, a.needle, a.question)
    body = json.dumps({"model": a.model, "temperature": 0, "max_tokens": a.max_tokens,
                       "messages": [{"role": "user", "content": text}]}).encode()
    req = urllib.request.Request(a.base_url + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=a.timeout) as r:
        out = json.loads(r.read())
    took = time.monotonic() - started
    message = ((out.get("choices") or [{}])[0].get("message") or {})
    answer = message.get("content") or message.get("reasoning_content") or ""
    usage = out.get("usage") or {}
    print(f"prompt tokens {usage.get('prompt_tokens')}, completion {usage.get('completion_tokens')}, {took:.1f} s")
    print("answer:", answer.strip()[-300:])
    print("needle found:", "VULTURE-7319" in answer)
    return 0 if "VULTURE-7319" in answer else 1


if __name__ == "__main__":
    sys.exit(main())
