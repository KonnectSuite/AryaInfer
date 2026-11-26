"""A Basalt model in the registry (serve/models.py) and as an engine the server classifies (serve/server.py).

The container is written by this test, so no 70 GB file and no GPU are involved: what is checked is that a
`strata-*.json` pointing at a `.basalt` gets its backend, name, quantization, context, draft head and footprint
from the file itself, and that the server knows this engine keeps no SAVE/RESTORE sessions.

    python -m unittest serve.test_models_basalt -v
"""
from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import basalt_model as bm  # noqa: E402
from serve import models as registry  # noqa: E402
from serve import server as S  # noqa: E402

META = {
    "format": "basalt", "version": 2, "name": "Qwen3.8-Flash-Next UD-IQ1_S",
    "gguf_kv": {"general.architecture": "qwen4exp", "general.size_label": "512x56B", "general.file_type": 24,
                "qwen4exp.context_length": 262144, "qwen4exp.expert_count": 512, "qwen4exp.block_count": 48,
                "general.sampling": {"temp": 0.6, "top_k": 20, "top_p": 0.95}},
    "mtp": {"draft_vocab": "mtp/draft_vocab"},
}
TOKENIZER = {"vocab.json": b'["a"]', "merges.txt": b"a b\n", "token_type.json": b"[0]",
             "tokenizer.json": b'{"model": "gpt2"}', "chat_template.jinja": b"{{ messages }}"}


def basalt(path: Path, meta: dict | None = None, **sections: bytes) -> Path:
    """A `.basalt` in Basalt's own layout: header, 64-byte-padded section table, then the sections."""
    parts = {"meta": json.dumps(meta or META).encode(), "dense": b"d" * 1000, "experts": b"e" * 2000,
             **{"tokenizer/" + n: v for n, v in TOKENIZER.items()}, **sections}
    body, table, offset = b"", [], bm.HEADER_BYTES
    for name, data in parts.items():
        table.append((name, offset, len(data)))
        body += data
        offset += len(data)
    head = bm.HEADER.pack(bm.MAGIC, bm.VERSION, len(table), bm.HEADER_BYTES + len(body), b"\0" * 40)
    for name, off, size in table:
        raw = name.encode() + b"\0" * (64 - len(name.encode()))
        head += bm.ENTRY.pack(raw, off, size, b"\0" * 32, b"\0" * 16)
    path.write_bytes(head.ljust(bm.HEADER_BYTES, b"\0") + body)
    return path


def install(root: Path, name: str = "basalt-ud-iq1_s", *, exe: str = "basalt.exe",
            model: Path | None = None) -> Path:
    """A Basalt model as tools/basalt_import.py leaves it: a container, its tokenizer and its run config."""
    model = model or basalt(root / "Qwen3.8-FN-UD-IQ1_S.basalt")
    tok = root / name / "tokenizer"
    bm.open_container(model).export_tokenizer(tok)
    engine = root / "bin" / exe
    engine.parent.mkdir(parents=True, exist_ok=True)
    engine.write_text("")
    cfg = root / f"strata-{name}.json"
    cfg.write_text(json.dumps({
        "exe": str(engine), "cwd": str(root), "tokenizer": str(tok), "model_name": name,
        "args": ["--model", str(model), "--gpu", "0", "--max-context", "131072", "--kv", "q4_0",
                 "--resident-experts", "--suffix-draft", "3"],
        "arch": "qwen4exp", "gpu": 0,
    }))
    return cfg


class Registry(unittest.TestCase):
    def test_a_basalt_model_reads_itself(self):
        with tempfile.TemporaryDirectory() as d:
            e = registry.describe(install(Path(d)))
        self.assertEqual(e["status"], "available")
        self.assertEqual(e["backend"], "qwen4exp")
        self.assertEqual(e["display_name"], "Qwen3.8-Flash-Next UD-IQ1_S")
        self.assertEqual(e["quantization"], "UD-IQ1_S")      # from the file's name, as for a GGUF
        self.assertEqual(e["context"], 131072)               # the config's --max-context
        self.assertTrue(e["mtp"])                            # the file's mtp/dense section
        self.assertFalse(e["multimodal"])                    # v1 sends no image: the card must not offer one
        self.assertEqual(e["ram_gb"], 0.0)                   # 1,000 + 2,000 B is under a GB, and it still says so
        self.assertEqual(e["vram_gb"]["least"], 1.0)
        self.assertEqual(e["params_total"], None)            # "512x56B" states no parameter count, and is not guessed

    def test_a_model_without_a_draft_head_does_not_claim_one(self):
        meta = {k: v for k, v in META.items() if k != "mtp"}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = install(root)
            basalt(root / "Qwen3.8-FN-UD-IQ1_S.basalt", meta)     # the same path, now without mtp
            e = registry.describe(cfg)
        self.assertFalse(e["mtp"])

    def test_the_file_missing_tokenizer_and_engine_are_each_named(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = install(root)                                  # a config for a file that is then taken away
            data = json.loads(cfg.read_text())
            data["args"][1] = str(root / "gone.basalt")
            cfg.write_text(json.dumps(data))
            self.assertIn("model file is missing", registry.describe(cfg)["problem"])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = install(root)
            for p in (root / "basalt-ud-iq1_s" / "tokenizer").glob("*"):
                p.unlink()
            self.assertIn("tokenizer is missing", registry.describe(cfg)["problem"])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = install(root, exe="not-basalt.exe")
            (root / "bin" / "not-basalt.exe").unlink()
            self.assertIn("engine is missing", registry.describe(cfg)["problem"])

    def test_a_file_that_is_not_a_container_is_unavailable_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = install(root)
            (root / "Qwen3.8-FN-UD-IQ1_S.basalt").write_bytes(b"not a container")
            e = registry.describe(cfg)
        self.assertEqual(e["status"], "unavailable")
        self.assertIn("cannot be read", e["problem"])

    def test_the_other_artifact_kinds_still_take_their_own_branch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tok = root / "tok"
            tok.mkdir()
            (tok / "vocab.json").write_text("[]")
            (root / "engine").write_text("")
            pack = root / "pack"
            pack.mkdir()
            cfg = root / "strata-a.strata-model.json"
            cfg.write_text(json.dumps({"exe": str(root / "engine"), "tokenizer": str(tok),
                                       "args": ["--pack", str(pack)], "model_name": "a", "arch": "inkling2_loop"}))
            e = registry.describe(cfg)
        self.assertEqual(e["status"], "available")
        self.assertEqual(e["backend"], "inkling2_loop")
        self.assertIsNone(e["quantization"])


class Engine(unittest.TestCase):
    def test_basalt_is_its_own_engine(self):
        self.assertTrue(S.basalt_engine({"exe": r"C:\x\bin\basalt.exe"}))
        self.assertTrue(S.basalt_engine({"exe": "BASALT.EXE"}))
        self.assertFalse(S.basalt_engine({"exe": r"C:\x\engine\strata.exe"}))
        self.assertFalse(S.basalt_engine({"exe": r"C:\x\engine-poly\strata-poly.exe"}))
        self.assertFalse(S.basalt_engine({}))

    def test_basalt_has_no_disk_sessions(self):
        """SAVE would be answered with an ERR by this engine; the server must not ask for one."""
        e = S.StrataEngine(r"C:\x\bin\basalt.exe", ["--model", "m.basalt", "--max-context", "131072"], lazy=True)
        self.assertFalse(e.disk_sessions)
        self.assertEqual(e.max_context, 131072)
        self.assertEqual(e.model_path, "m.basalt")
        poly = S.StrataEngine(r"C:\x\engine-poly\strata-poly.exe", ["--model", "m.gguf"], lazy=True)
        self.assertFalse(poly.disk_sessions)
        plain = S.StrataEngine(r"C:\x\engine\strata.exe", ["--model", "m.strata"], lazy=True)
        self.assertTrue(plain.disk_sessions)


if __name__ == "__main__":
    unittest.main(verbosity=2)