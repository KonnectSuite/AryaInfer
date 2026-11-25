"""The Inkling-2-Mini engine as the fork's server sees it.

Its own shape engine program (`strata-inkling`) speaks the same engine protocol as the
other Strata engines; the difference that matters here is its wire dialect: channel
tokens (`<|content_thinking|>`, `<|content_text|>`, ...) instead of `<think>`.
"""
from __future__ import annotations

from pathlib import Path

ARCH = "inkling2_loop"
EXE_PREFIX = "strata-inkling"
END_TEXTS = ("<|content_model_end_sampling|>", "<|endoftext|>")


def _base(exe) -> str:
    return str(exe or "").replace("\\", "/").rsplit("/", 1)[-1].lower()


def is_inkling(cfg: dict | None) -> bool:
    if not isinstance(cfg, dict):
        return False
    if cfg.get("arch") == ARCH:
        return True
    return is_inkling_exe(cfg.get("exe"))


def is_inkling_exe(exe) -> bool:
    return _base(exe).startswith(EXE_PREFIX)


def literal_tags(tokenizer) -> list[str]:
    types = getattr(tokenizer, "token_types", None) or []
    toks = getattr(tokenizer, "tokens", None) or []
    return [toks[i] for i, ty in enumerate(types) if ty == 4 and i < len(toks)]


def end_ids(tokenizer) -> set[int]:
    ids = set()
    for text in END_TEXTS:
        got = tokenizer.encode(text, parse_special=True)
        if len(got) == 1:
            ids.add(int(got[0]))
    return ids


def encode_path(path) -> str:
    """A path in the engine's `image=` sampling key."""
    return str(path).replace("%", "%25").replace(" ", "%20")


def write_images(sources, load, normalize, cancel=None, folder=None) -> list[str]:
    """Normalized request images, one unique file each, for the engine's `image=` keys."""
    import hashlib
    import secrets
    import tempfile
    base = Path(folder) if folder else Path(tempfile.gettempdir()) / "strata-inkling-images"
    base.mkdir(parents=True, exist_ok=True)
    nonce = secrets.token_hex(6)
    out: list[str] = []
    try:
        for idx, src in enumerate(sources):
            if cancel is not None and cancel.is_set():
                raise ValueError("the request was cancelled")
            data = normalize(src if isinstance(src, bytes) else load(src))
            ext = (".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg" if data[:3] == b"\xff\xd8\xff"
                   else ".bmp" if data[:2] == b"BM" else ".gif" if data[:3] == b"GIF" else ".img")
            p = base / f"{hashlib.sha256(data).hexdigest()[:24]}-{nonce}-{idx}{ext}"
            p.write_bytes(data)
            out.append(str(p))
    except Exception:
        for p in out:
            Path(p).unlink(missing_ok=True)
        raise
    return out


def model_path(cfg: dict) -> Path | None:
    args = cfg.get("args") or []
    for key in ("--native", "--model"):
        if key in args and args.index(key) + 1 < len(args):
            return Path(args[args.index(key) + 1])
    return None
