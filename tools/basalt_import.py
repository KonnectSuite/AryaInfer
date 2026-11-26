"""Install a Basalt `.basalt` model as an AryaInfer run config, so one server starts and switches it.

AryaInfer starts every model from a `strata-*.json` run config beside the server: the engine binary, its
arguments, a tokenizer directory and a log path.  A Basalt model needs three things this tool arranges:

1. **Its tokenizer as a directory.**  `.basalt` carries the tokenizer inside (`tokenizer/vocab.json` and
   friends); AryaInfer's server loads a directory, so the sections are written out under
   `<packs>\\<name>\\tokenizer`.
2. **Its cwd.**  `basalt.exe` resolves `--expert-profile` against `data/profiles` relative to the working
   directory, so the config's `cwd` is the Basalt source tree the binary lives in.
3. **Its flags.**  `--from-config` copies what the user already runs by hand (`official_config.json`), so the
   imported model behaves exactly like the standalone server did; the file's own sampling is the fallback.

Nothing here is Basalt code and nothing is downloaded: it reads the file's header (`tools/basalt_model.py`),
writes the tokenizer and one run config.  Run it again with `--force` to re-import after replacing the file.

    python tools/basalt_import.py --model <basalt-main>\\models\\x.basalt \\
        --exe <basalt-main>\\bin\\basalt.exe --from-config <basalt-main>\\official_config.json \\
        --name basalt-qwen38-ud-iq1_s
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import basalt_model  # noqa: E402

DEFAULT_PACKS = Path(r"C:\Users\kphung\AryaCode\KonnectSuite\PolyStrata-data\packs")
# the CUDA runtime the engine links against, as this host's other run configs carry it
CUDA_BIN = (r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.5\bin",
            r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.5\bin\x64")


def slug(text: str) -> str:
    """A model name as an id: lower case, one dash between words, underscores kept (as the other ids do)."""
    out, dash = [], False
    for ch in text.lower():
        if ch.isalnum() or ch == "_":
            out.append(ch)
            dash = False
        elif not dash:
            out.append("-")
            dash = True
    return "".join(out).strip("-")


def default_name(model: basalt_model.Container) -> str:
    """`basalt-` + the model's own name, less the family prefix and the file extension noise."""
    raw = str(model.summary()["name"] or model.path.stem)
    low = raw.lower()
    for prefix in ("qwen3.8-flash-next", "qwen3-8-flash-next", "qwen3.8", "qwen3-8"):
        if low.startswith(prefix):
            raw = raw[len(prefix):]
            break
    return "basalt-" + slug(raw)


def from_config(path: Path) -> tuple[dict, dict, str | None]:
    """The engine settings of a Basalt `--config` file: (engine, first model, alias of that model)."""
    cfg = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    models = cfg.get("models") or []
    first = models[0] if models and isinstance(models[0], dict) else {}
    return cfg.get("engine") or {}, first, (first.get("model") if isinstance(first, dict) else None)


def build_args(model: basalt_model.Container, *, engine: dict, first: dict,
               gpu: int, max_context: int | None, kv: str | None) -> list[str]:
    """The engine words, in the order the file's own server passes them."""
    s = model.summary()
    args: list[str] = ["--model", str(model.path), "--gpu", str(gpu)]
    ctx = max_context if max_context is not None else (first.get("max-context") or s["context"] or 131072)
    args += ["--max-context", str(int(ctx))]
    kv = kv or first.get("kv") or "q4_0"
    args += ["--kv", str(kv)]
    if engine.get("resident-experts"):
        args += ["--resident-experts"]
    # the draft head is the model's own MTP section: a model without one must not be asked for drafts
    if s["mtp"] and engine.get("suffix-draft"):
        args += ["--suffix-draft", str(int(engine["suffix-draft"]))]
    if engine.get("vram-reserve-mib") is not None:
        args += ["--vram-reserve-mib", str(int(engine["vram-reserve-mib"]))]
    if engine.get("ram-reserve-mib") is not None:
        args += ["--ram-reserve-mib", str(int(engine["ram-reserve-mib"]))]
    # Deliberately NOT passed in v1: `--vision` makes the engine load its own image encoder, and AryaInfer
    # cannot send it an image yet (it spawns a separate encoder for a dict vision config, which this lane has
    # none of).  Switching the encoder on would cost VRAM for a feature the server would never use.  The
    # section is there (`vision/mmproj`, 0.91 GB) for the follow-up that teaches the server the in-engine path.
    return args


def sampling(s: dict, first: dict) -> dict | None:
    """What the file says, unless the user's own server config overrides it."""
    if first.get("temperature") is not None or first.get("top-p") is not None:
        return {k: v for k, v in (("temperature", first.get("temperature")), ("top_p", first.get("top-p")),
                                  ("top_k", first.get("top-k"))) if v is not None}
    src = s.get("sampling") or {}
    keys = {"temperature": ("temperature", "temp"), "top_p": ("top_p", "top-p"),
            "top_k": ("top_k", "top-k")}
    out = {}
    for want, names in keys.items():
        for n in names:
            if src.get(n) is not None:
                out[want] = src[n]
                break
    return out or None


def main() -> int:
    ap = argparse.ArgumentParser(description="Install a Basalt .basalt model as an AryaInfer run config.")
    ap.add_argument("--model", type=Path, required=True, help="the .basalt file")
    ap.add_argument("--exe", type=Path, required=True, help="basalt.exe")
    ap.add_argument("--from-config", type=Path, help="a Basalt --config file to copy the engine settings from")
    ap.add_argument("--name", help="the model id (default: basalt-<its own name>)")
    ap.add_argument("--packs", type=Path, default=DEFAULT_PACKS, help="where the tokenizer directory goes")
    ap.add_argument("--root", type=Path, default=ROOT, help="the AryaInfer tree the run config is written to")
    ap.add_argument("--max-context", type=int, help="override the context (default: the config's, else the file's)")
    ap.add_argument("--kv", help="override the KV format (default: the config's, else q4_0)")
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--port", type=int, default=8081, help="the port recorded in the config (display only)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing config of the same name")
    ap.add_argument("--print-only", action="store_true", help="show the config without writing anything")
    args = ap.parse_args()

    model = basalt_model.open_container(args.model)
    exe = args.exe.resolve()
    if not exe.is_file():
        print(f"error: the engine is missing ({exe})", file=sys.stderr)
        return 2
    engine, first, _alias = from_config(args.from_config) if args.from_config else ({}, {}, None)
    name = args.name or default_name(model)
    cfg_path = args.root / f"strata-{name}.json"
    if cfg_path.exists() and not args.force and not args.print_only:
        print(f"error: {cfg_path} exists (pass --force to replace it)", file=sys.stderr)
        return 3

    s = model.summary()
    tokdir = args.packs / name / "tokenizer"
    wrote: dict[str, int] = {}
    if not args.print_only:
        wrote = model.export_tokenizer(tokdir)
    cfg = {
        "exe": str(exe),
        "args": build_args(model, engine=engine, first=first, gpu=args.gpu,
                           max_context=args.max_context, kv=args.kv),
        # the engine looks for data/profiles next to where it is run, and its cache lives under the user's home
        "cwd": str(exe.parent.parent),
        "tokenizer": str(tokdir),
        "model_name": name,
        "display_name": s["name"] or name,
        "arch": s["arch"],
        "log": str(args.root / f"strata-{name}.log"),
        "lib_dirs": [d for d in CUDA_BIN if Path(d).is_dir()],
        "port": args.port,
        "gpu": args.gpu,
        "gpus_asked": True,
    }
    smp = sampling(s, first)
    if smp:
        cfg["sampling"] = smp
    text = json.dumps(cfg, indent=1, ensure_ascii=False)
    printed = {"config": str(cfg_path), "tokenizer": str(tokdir), "tokenizer_files": wrote,
               "model": s["name"], "arch": s["arch"], "context": s["context"],
               "mtp": s["mtp"], "vision": s["vision"], "bytes": s["file_bytes"]}
    print(json.dumps(printed, indent=1))
    if args.print_only:
        print(text)
        return 0
    cfg_path.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {cfg_path}")
    print(f"start it with:  python serve/server.py --engine strata --config {cfg_path.name} --port {args.port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())