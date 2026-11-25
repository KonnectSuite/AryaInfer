"""Tests for setup.py's engines.json path (no GPU, no network, nothing installed).

    python -m unittest tools.test_setup_engines
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import setup

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "engines.json").read_text(encoding="utf-8"))


def quiet(fn, *args, **kw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        return fn(*args, **kw), out.getvalue()


def engine_zip(path: Path, version="9.9.9", binary="strata.exe", extra=None) -> Path:
    payload = {
        "BUILD.json": json.dumps({"version": version, "archs": [86, 89, 120], "cuda": "13.0"}).encode(),
        binary: b"exe",
    }
    payload.update(extra or {})
    with zipfile.ZipFile(path, "w") as z:
        for name, data in payload.items():
            z.writestr(name, data)
    return path


def engine_tar(path: Path, version="9.9.9", binary="strata.exe") -> Path:
    import io as _io
    with tarfile.open(path, "w:gz") as t:
        for name, data in {"BUILD.json": json.dumps({"version": version, "archs": [86, 89, 120]}).encode(),
                           binary: b"exe"}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, _io.BytesIO(data))
    return path


class Manifest(unittest.TestCase):
    def test_schema_and_required_pins(self):
        self.assertEqual(MANIFEST["schema"], 1)
        self.assertEqual(MANIFEST["release"], "engines-2026.11")
        engines = MANIFEST["engines"]
        self.assertEqual(engines["strata"]["version"], "0.1.67")
        self.assertEqual(engines["inkling"]["version"], "0.1.67")
        self.assertEqual(engines["poly"]["version"], "0.1.66")
        self.assertEqual(engines["arya"]["version"], "0.1.45")
        self.assertEqual(engines["ninfer"]["version"], "0.1.0")
        for name in ("strata", "inkling", "poly", "arya"):
            asset = engines[name]["assets"]["windows-cuda13"]
            self.assertTrue(asset["url"].startswith("https://github.com/"))
            self.assertGreater(asset["size"], 1_000_000)
            self.assertRegex(asset["sha256"], r"^[0-9a-f]{64}$")

    def test_asset_selection(self):
        with mock.patch.object(setup, "WIN", True):
            self.assertIn("cuda13", setup.manifest_asset("strata", 13)["asset"])
            self.assertIn("cuda12", setup.manifest_asset("strata", 12)["asset"])
            self.assertEqual(setup.manifest_asset("inkling", 12)["size"], 588_490_782)
            self.assertEqual(setup.manifest_asset("arya", 13)["size"], 563_955_903)
            self.assertIsNone(setup.manifest_asset("arya", 12))        # one CUDA 13 build, no fallback


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_root = setup.ROOT
        self.old_manifest = setup.MANIFEST_PATH
        setup.ROOT = self.root
        setup.MANIFEST_PATH = self.root / "engines.json"
        self.manifest = json.loads(json.dumps(MANIFEST))
        self.manifest["engines"]["strata"].update({"pending": False, "manual": False})
        self.manifest["engines"]["strata"]["assets"]["windows-cuda13"] = {}
        self.write_manifest()
        self.gpu = {"archs": [89], "arch": 89}

    def tearDown(self):
        setup.ROOT = self.old_root
        setup.MANIFEST_PATH = self.old_manifest
        self.tmp.cleanup()

    def write_manifest(self):
        setup.MANIFEST_PATH.write_text(json.dumps(self.manifest), encoding="utf-8")

    def add_asset(self, name, archive: Path):
        data = archive.read_bytes()
        self.manifest["engines"][name]["assets"]["windows-cuda13"] = {
            "url": str(archive), "asset": archive.name, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}
        self.manifest["engines"][name]["assets"]["windows-cuda12"] = self.manifest["engines"][name]["assets"]["windows-cuda13"]
        self.write_manifest()

    def test_install_zip_and_keep_it(self):
        archive = engine_zip(self.root / "strata.zip")
        self.add_asset("strata", archive)
        with mock.patch.object(setup, "WIN", True):
            got = setup.install_manifest_engine("strata", self.gpu)
        self.assertEqual(got, self.root / "engine")
        self.assertTrue((got / "strata.exe").exists())
        self.assertEqual(json.loads((got / "BUILD.json").read_text())["version"], "9.9.9")
        # a second call does not download again
        with mock.patch.object(setup, "install_unpacked", side_effect=AssertionError("downloaded again")), \
                mock.patch.object(setup, "WIN", True):
            self.assertEqual(setup.install_manifest_engine("strata", self.gpu), got)

    def test_install_tar_gz(self):
        archive = engine_tar(self.root / "strata.tar.gz")
        self.add_asset("strata", archive)
        with mock.patch.object(setup, "WIN", True):
            got = setup.install_manifest_engine("strata", self.gpu)
        self.assertTrue((got / "strata.exe").exists())

    def test_digest_mismatch_changes_nothing(self):
        archive = engine_zip(self.root / "strata.zip")
        self.add_asset("strata", archive)
        self.manifest["engines"]["strata"]["assets"]["windows-cuda13"]["sha256"] = "0" * 64
        self.write_manifest()
        with mock.patch.object(setup, "WIN", True):
            with self.assertRaises(setup.UnverifiedEngine):
                setup.install_manifest_engine("strata", self.gpu)
        self.assertFalse((self.root / "engine" / "strata.exe").exists())

    def test_old_engine_is_not_accepted(self):
        eng = self.root / "engine"
        eng.mkdir()
        (eng / "strata.exe").write_bytes(b"old")
        (eng / "BUILD.json").write_text(json.dumps({"version": "0.1.45", "archs": [89]}))
        with mock.patch.object(setup, "WIN", True):
            folder, ver, ok, why = setup.manifest_installed("strata", self.gpu)
        self.assertFalse(ok)
        self.assertEqual(ver, "0.1.45")
        self.assertIn("older", why)

    def test_unsafe_zip_entry_is_refused(self):
        bad = self.root / "bad.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../evil.txt", b"x")
        with self.assertRaises(setup.UnverifiedEngine):
            setup._safe_extract(bad, self.root / "out")

    def test_check_engines_reports_what_is_missing(self):
        args = SimpleNamespace(check_engines=True, repair_engines=False, with_inkling=False,
                               with_ninfer=False, prebuilt=setup.PREBUILT_URL)
        with mock.patch.object(setup, "WIN", True):
            code, out = quiet(setup.engine_manifest_cli, args, self.gpu, False, 13)
        self.assertEqual(code, 1)
        self.assertIn("not installed", out)


if __name__ == "__main__":
    unittest.main()
