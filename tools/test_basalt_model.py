"""The `.basalt` reader and the importer, checked against a container this test writes itself.

No model file of 70 GB and no GPU: `make_container()` lays out Basalt's format exactly as its own writer does
(a 64 KiB header, 128-byte entries whose names are padded to 64 bytes, sections after the header), and the
reader must accept that and refuse everything else.  The importer's pure parts are checked too: the name it
derives, the engine words it builds, and whose sampling wins.

    python -m unittest tools.test_basalt_model
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
import basalt_import as imp  # noqa: E402
import basalt_model as bm  # noqa: E402

META = {
    "format": "basalt", "version": 2, "name": "Qwen3.8-Flash-Next UD-IQ1_S",
    "gguf_kv": {"general.architecture": "qwen4exp", "general.size_label": "512x56B", "general.file_type": 24,
                "qwen4exp.context_length": 262144, "qwen4exp.expert_count": 512, "qwen4exp.block_count": 48,
                "general.sampling": {"temp": 0.6, "top_k": 20, "top_p": 0.95}},
    "mtp": {"draft_vocab": "mtp/draft_vocab"}, "license": "apache-2.0",
}
TOKENIZER = {"vocab.json": b'["a", "b"]', "merges.txt": b"a b\n", "token_type.json": b"[0, 1]",
             "tokenizer.json": b'{"model": "gpt2"}', "chat_template.jinja": b"{{ messages }}"}


def make_container(path: Path, sections: dict[str, bytes], *, magic: bytes = bm.MAGIC,
                   version: int = 2, pad: bytes = b"\0") -> Path:
    """Write a container the way Basalt's writer does: header, table, then the sections."""
    names = list(sections)
    body, table = b"", []
    offset = bm.HEADER_BYTES
    for name in names:
        data = sections[name]
        table.append((name, offset, len(data)))
        body += data
        offset += len(data)
    header = bm.HEADER.pack(magic, version, len(names), bm.HEADER_BYTES + len(body), b"\0" * 40)
    for name, off, size in table:
        # 64 bytes exactly, as the file has it: the name, then NULs (or spaces, on the real files)
        raw = name.encode() + pad * (64 - len(name.encode()))
        header += bm.ENTRY.pack(raw, off, size, b"\0" * 32, b"\0" * 16)
    path.write_bytes(header.ljust(bm.HEADER_BYTES, b"\0") + body)
    return path


def tokenizer_sections() -> dict[str, bytes]:
    return {"tokenizer/" + n: data for n, data in TOKENIZER.items()}


class Reader(unittest.TestCase):
    def test_summary_comes_from_the_file_alone(self):
        with tempfile.TemporaryDirectory() as d:
            p = make_container(Path(d) / "m.basalt", {"dense": b"d" * 1000, "experts": b"e" * 2000,
                                                      "meta": json.dumps(META).encode(),
                                                      **tokenizer_sections(),
                                                      "mtp/dense": b"m" * 10, "vision/mmproj": b"v" * 10})
            s = bm.summary(p)
        self.assertEqual(s["arch"], "qwen4exp")
        self.assertEqual(s["context"], 262144)
        self.assertEqual(s["size_label"], "512x56B")
        self.assertEqual(s["file_type"], 24)
        self.assertEqual(s["expert_count"], 512)
        self.assertEqual(s["block_count"], 48)
        self.assertEqual(s["name"], "Qwen3.8-Flash-Next UD-IQ1_S")
        self.assertEqual((s["dense_bytes"], s["expert_bytes"]), (1000, 2000))
        self.assertTrue(s["mtp"])
        self.assertTrue(s["vision"])
        self.assertEqual(s["sampling"]["top_p"], 0.95)
        self.assertEqual(s["license"], "apache-2.0")

    def test_a_file_without_mtp_or_vision(self):
        with tempfile.TemporaryDirectory() as d:
            meta = dict(META)
            meta.pop("mtp")
            p = make_container(Path(d) / "m.basalt", {"meta": json.dumps(meta).encode(), "dense": b"d" * 10})
            s = bm.summary(p)
        self.assertFalse(s["mtp"])
        self.assertFalse(s["vision"])
        self.assertEqual(s["expert_bytes"], 0)

    def test_padded_section_names_are_stripped(self):
        """The real table pads every name to 64 bytes; a lookup of "meta" must work anyway."""
        with tempfile.TemporaryDirectory() as d:
            for pad in (b"\0", b" "):
                p = make_container(Path(d) / "m.basalt", {"meta": b"{}", "dense": b"x"}, pad=pad)
                c = bm.open_container(p)
                self.assertEqual(sorted(c.sections), ["dense", "meta"])
                self.assertTrue(c.has("meta"))
                self.assertEqual(c.read("dense"), b"x")

    def test_read_returns_the_section_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p = make_container(Path(d) / "m.basalt", {"a": b"hello", "b": b"world"})
            c = bm.open_container(p)
            self.assertEqual((c.read("a"), c.read("b")), (b"hello", b"world"))

    def test_tokenizer_files_are_the_sections_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as d:
            p = make_container(Path(d) / "m.basalt", tokenizer_sections())
            files = bm.open_container(p).tokenizer_files()
        self.assertEqual(files, {n: data for n, data in TOKENIZER.items()})

    def test_export_writes_the_directory_the_server_loads(self):
        with tempfile.TemporaryDirectory() as d:
            p = make_container(Path(d) / "m.basalt", tokenizer_sections())
            out = Path(d) / "packs" / "x" / "tokenizer"
            wrote = bm.open_container(p).export_tokenizer(out)
            on_disk = {n: (out / n).read_bytes() for n in TOKENIZER}
        self.assertEqual(wrote, {n: len(v) for n, v in TOKENIZER.items()})
        self.assertEqual(on_disk, TOKENIZER)

    def test_export_refuses_a_file_without_a_tokenizer(self):
        with tempfile.TemporaryDirectory() as d:
            p = make_container(Path(d) / "m.basalt", {"meta": b"{}", "dense": b"x"})
            with self.assertRaises(ValueError):
                bm.open_container(p).export_tokenizer(Path(d) / "out")
            self.assertFalse((Path(d) / "out" / "vocab.json").exists())   # written last, so never left behind

    def test_refusals_say_what_is_wrong(self):
        with tempfile.TemporaryDirectory() as d:
            bad_magic = make_container(Path(d) / "a.basalt", {"meta": b"{}"}, magic=b"NOTBASAL")
            with self.assertRaises(ValueError) as e:
                bm.open_container(bad_magic)
            self.assertIn("not a .basalt", str(e.exception))
            v1 = make_container(Path(d) / "b.basalt", {"meta": b"{}"}, version=1)
            with self.assertRaises(ValueError) as e:
                bm.open_container(v1)
            self.assertIn("basalt_v1_to_v2.py", str(e.exception))
            (Path(d) / "c.basalt").write_bytes(b"tiny")
            with self.assertRaises(ValueError):
                bm.open_container(Path(d) / "c.basalt")

    def test_missing_section_is_a_key_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = make_container(Path(d) / "m.basalt", {"meta": b"{}"})
            with self.assertRaises(KeyError):
                bm.open_container(p).read("experts")

    def test_the_cache_reuses_one_parse_and_notices_a_replaced_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = make_container(Path(d) / "m.basalt", {"meta": b'{"name": "one"}'})
            first = bm.open_container(p)
            self.assertIs(bm.open_container(p), first)
            p.write_bytes(p.read_bytes())                      # a rewrite with the same size and mtime is the same
            make_container(p, {"meta": b'{"name": "two!"}'})   # different size: a new parse
            second = bm.open_container(p)
            self.assertIsNot(first, second)
            self.assertEqual(second.meta["name"], "two!")


class Importer(unittest.TestCase):
    def container(self, **over) -> bm.Container:
        meta = json.loads(json.dumps(META)) | over.pop("meta", {})
        sections = {"meta": json.dumps(meta).encode(), "dense": b"d" * 10, "experts": b"e" * 10,
                    **tokenizer_sections(), **over}
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return bm.open_container(make_container(d / "m.basalt", sections))

    def test_the_default_name_drops_the_family_prefix(self):
        c = self.container()
        self.assertEqual(imp.default_name(c), "basalt-ud-iq1_s")

    def test_a_coder_name_keeps_its_own_words(self):
        c = self.container(meta={"name": "Qwen3.8-Flash-Next Coder IQ1_M"})
        self.assertEqual(imp.default_name(c), "basalt-coder-iq1_m")

    def test_engine_words_follow_the_users_own_server_config(self):
        c = self.container()
        engine = {"resident-experts": True, "suffix-draft": 3, "vram-reserve-mib": 320, "ram-reserve-mib": 4096}
        first = {"max-context": 131072, "kv": "q4_0"}
        args = imp.build_args(c, engine=engine, first=first, gpu=0, max_context=None, kv=None)
        self.assertEqual(args[:2], ["--model", str(c.path)])
        self.assertEqual(args[args.index("--max-context") + 1], "131072")
        self.assertEqual(args[args.index("--kv") + 1], "q4_0")
        self.assertEqual(args[args.index("--suffix-draft") + 1], "3")
        self.assertIn("--resident-experts", args)
        # v1 sends no --vision: the server has no in-engine image path to use it with
        self.assertNotIn("--vision", args)

    def test_a_model_without_an_mtp_section_is_not_asked_for_drafts(self):
        c = self.container(meta={"mtp": None})
        args = imp.build_args(c, engine={"suffix-draft": 3}, first={}, gpu=0, max_context=None, kv=None)
        self.assertNotIn("--suffix-draft", args)
        self.assertEqual(args[args.index("--max-context") + 1], "262144")   # the file's own context

    def test_the_users_sampling_wins_over_the_files(self):
        c = self.container()
        self.assertEqual(imp.sampling(c.summary(), {"temperature": 0.7, "top-p": 0.9, "top-k": 40}),
                         {"temperature": 0.7, "top_p": 0.9, "top_k": 40})
        self.assertEqual(imp.sampling(c.summary(), {})["temperature"], 0.6)   # general.sampling.temp


if __name__ == "__main__":
    unittest.main(verbosity=2)