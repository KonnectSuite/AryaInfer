"""Read a Basalt `.basalt` model container - no Basalt code, no ggml, no torch.

A `.basalt` file is Basalt's own artifact: one 64 KiB header holding a 128-byte section table, then
sections aligned to 2 MiB and named for what they hold (`dense`, `experts`, `gguf`, `tokenizer/vocab.json`,
`mtp/dense`, `vision/mmproj`, `meta`).  `meta` is JSON carrying the GGUF metadata of the model the file was
converted from, so the architecture, the context length, the sampling defaults and the whole tokenizer come
out of the one file.  That is why a Basalt model needs no pack directory and no `--mmproj`: everything the
server needs is in it.

The layout is Basalt's own (`include/basalt/core/model_format.hpp` writes it, `tools/model_file.py` there
reads it); this module reads the same bytes and nothing else.  It copies no Basalt source, it never reads
tensor data, and it does not write to the file.

The one trap: the section table pads each name to 64 bytes with spaces and NULs (`data\0\0...`), so a naive
lookup of `"meta"` misses.  `sections()` strips the padding once, for every name.

    python tools/basalt_model.py --info models\\Qwen3.8-FN-UD-IQ1_S.basalt
    python tools/basalt_model.py --tokenizer models\\x.basalt --out packs\\basalt-x
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from typing import Any

MAGIC = b"BASALTMF"
VERSION = 2
HEADER = struct.Struct("<8sIIQ40s")       # magic, version, section count, file size, reserved
ENTRY = struct.Struct("<64sQQ32s16s")     # name, offset, size, sha256, reserved
HEADER_BYTES = 64 << 10
SECTION_ALIGN = 2 << 20

# the tokenizer directory AryaInfer loads (vocab.json is its completeness sign) as it sits in the container
TOKENIZER_SECTIONS = ("vocab.json", "merges.txt", "token_type.json", "tokenizer.json", "chat_template.jinja")

# what a lane can say about a file it cannot fully describe; the engine's INFO line carries the truth at load
_CACHE: dict[tuple[str, int, float], "Container"] = {}


class Container:
    """One parsed `.basalt` file: its section table, and what the sections say about the model."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        st = self.path.stat()
        self.size = st.st_size
        with open(self.path, "rb") as f:
            head = f.read(HEADER_BYTES)
        if len(head) < HEADER.size:
            raise ValueError(f"the file is too short to be a .basalt container ({self.size} B)")
        magic, version, count, total, _ = HEADER.unpack_from(head, 0)
        if magic != MAGIC:
            raise ValueError(f"not a .basalt container (magic {magic!r})")
        if version != VERSION:
            raise ValueError(f"container version {version}: this reader knows version {VERSION}"
                             " (an older file is converted by Basalt's tools/migrations/basalt_v1_to_v2.py)")
        table = HEADER.size + count * ENTRY.size
        if table > len(head):
            raise ValueError(f"the section table runs past the header ({count} sections)")
        self.sections: dict[str, tuple[int, int]] = {}
        for i in range(count):
            name, offset, size, _sha, _r = ENTRY.unpack_from(head, HEADER.size + i * ENTRY.size)
            key = name.decode("utf-8", "replace").rstrip("\0 ")
            if not key:
                continue
            if offset + size > total:
                raise ValueError(f"section {key!r} runs past the end of the file")
            self.sections[key] = (offset, size)
        self.version = version
        self._meta: dict[str, Any] | None = None

    # -- bytes -------------------------------------------------------------------------------------
    def read(self, name: str) -> bytes:
        """One section's bytes (`meta`, `tokenizer/vocab.json`, ...)."""
        try:
            offset, size = self.sections[name]
        except KeyError:
            raise KeyError(f"no {name!r} section (has: {', '.join(sorted(self.sections)[:12])}...)") from None
        with open(self.path, "rb") as f:
            f.seek(offset)
            data = f.read(size)
        if len(data) != size:
            raise ValueError(f"section {name!r} is short: {len(data)} of {size} B")
        return data

    def has(self, name: str) -> bool:
        return name in self.sections

    # -- what it says --------------------------------------------------------------------------------
    @property
    def meta(self) -> dict[str, Any]:
        if self._meta is None:
            self._meta = json.loads(self.read("meta"))
            if not isinstance(self._meta, dict):
                raise ValueError("the meta section is not a JSON object")
        return self._meta

    @property
    def kv(self) -> dict[str, Any]:
        """The GGUF metadata the file was converted from (`general.architecture`, `qwen4exp.context_length`...)."""
        kv = self.meta.get("gguf_kv") or {}
        return kv if isinstance(kv, dict) else {}

    def _kv_int(self, *names: str) -> int | None:
        for n in names:
            v = self.kv.get(n)
            if isinstance(v, int):
                return v
        return None

    def summary(self) -> dict[str, Any]:
        """Everything the model registry needs, from the file alone."""
        kv, arch = self.kv, self.kv.get("general.architecture")
        ctx = self._kv_int(f"{arch}.context_length", "general.context_length") if arch else None
        dense = self.sections.get("dense", (0, 0))[1]
        experts = self.sections.get("experts", (0, 0))[1]
        return {
            "path": str(self.path), "file_bytes": self.size, "sections": len(self.sections),
            "name": self.meta.get("name"), "arch": arch,
            "context": ctx,
            "size_label": kv.get("general.size_label"),
            "file_type": self._kv_int("general.file_type"),
            "expert_count": self._kv_int(f"{arch}.expert_count", "general.expert_count") if arch else None,
            "block_count": self._kv_int(f"{arch}.block_count", "general.block_count") if arch else None,
            "sampling": kv.get("general.sampling") if isinstance(kv.get("general.sampling"), dict) else None,
            "mtp": self.has("mtp/dense") or self.meta.get("mtp") is not None,
            "vision": self.has("vision/mmproj"),
            "dense_bytes": dense, "expert_bytes": experts,
            "license": self.meta.get("license"),
        }

    # -- tokenizer -----------------------------------------------------------------------------------
    def tokenizer_files(self) -> dict[str, bytes]:
        """The tokenizer exactly as the engine sees it: the container's own sections, byte for byte."""
        return {n: self.read("tokenizer/" + n) for n in TOKENIZER_SECTIONS if self.has("tokenizer/" + n)}

    def export_tokenizer(self, out_dir: Path | str) -> dict[str, int]:
        """Write that tokenizer as the directory AryaInfer loads.  -> {name: bytes written}.

        The layout is the one `tools/strata_tokenizer.py extract()` produces and `serve/models.py`
        checks (`vocab.json`, `merges.txt`, `token_type.json`, `tokenizer.json`, `chat_template.jinja`).
        `vocab.json` is written last: setup treats it as the sign the folder is complete.
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        files = self.tokenizer_files()
        order = [n for n in TOKENIZER_SECTIONS if n != "vocab.json" and n in files] + \
                [n for n in ("vocab.json",) if n in files]
        wrote: dict[str, int] = {}
        for name in order:
            (out / name).write_bytes(files[name])
            wrote[name] = len(files[name])
        if not wrote.get("vocab.json"):
            raise ValueError(f"{self.path} carries no tokenizer to export")
        return wrote


def open_container(path: Path | str) -> Container:
    """The container for a path, parsed once per process (the section table is 64 KiB of file reads)."""
    p = Path(path).resolve()
    st = p.stat()
    key = (str(p), st.st_size, st.st_mtime)
    hit = _CACHE.get(key)
    if hit is None:
        for old in [k for k in _CACHE if k[0] == str(p)]:
            del _CACHE[old]          # a file was replaced: keep one parse per path
        hit = _CACHE[key] = Container(p)
    return hit


def summary(path: Path | str) -> dict[str, Any]:
    return open_container(path).summary()


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Read a Basalt .basalt model container.")
    ap.add_argument("path", type=Path, help="the .basalt file")
    ap.add_argument("--info", action="store_true", help="print what the file says about the model")
    ap.add_argument("--tokenizer", action="store_true", help="write its tokenizer as a directory")
    ap.add_argument("--out", type=Path, help="where --tokenizer writes (default: beside the file)")
    args = ap.parse_args()
    c = open_container(args.path)
    if args.info or not args.tokenizer:
        s = c.summary()
        print(f"format=basalt version={c.version} sections={s['sections']} bytes={s['file_bytes']}")
        print(f"name={s['name']!r} arch={s['arch']} context={s['context']} size_label={s['size_label']}"
              f" file_type={s['file_type']} experts={s['expert_count']} blocks={s['block_count']}")
        print(f"mtp={s['mtp']} vision={s['vision']} dense_bytes={s['dense_bytes']} expert_bytes={s['expert_bytes']}")
        if s["sampling"]:
            print("sampling=" + json.dumps(s["sampling"], sort_keys=True))
    if args.tokenizer:
        out = args.out or (args.path.parent / (args.path.stem + ".tokenizer"))
        wrote = c.export_tokenizer(out)
        print(f"tokenizer -> {out} " + json.dumps(wrote, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())