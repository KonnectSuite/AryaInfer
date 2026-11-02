"""Tests for setup's Qwen3.8 27B family (docs/QWEN38-27B.md): the family's files and hashes, and the context a card
can hold - no GPU, no network, nothing installed.

    python -m unittest tools.test_setup_qwen38
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import setup  # noqa: E402


class Family(unittest.TestCase):
    """The family is complete enough for setup, --custom-gguf and the registry: every file it names is pinned."""

    def setUp(self):
        self.fam = setup.FAMILIES["qwen38"]
        self.models = setup.family_models("qwen38")

    def test_it_is_a_dense_poly_family_with_vision(self):
        self.assertTrue(self.fam["dense"])
        self.assertEqual(self.fam["engine"], "poly")
        self.assertIs(self.fam["vision"], True)
        self.assertEqual(self.fam["shards"], 1)

    def test_every_model_names_a_file_whose_size_and_hash_are_pinned(self):
        for name, d in self.models.items():
            file = setup.model_file(self.fam, name, 1)
            self.assertIn(file, d["sha256"], name)
            size, sha = d["sha256"][file]
            self.assertGreater(size, 8e9)
            self.assertEqual(len(sha), 64)
            self.assertAlmostEqual(d["download_gb"], size / 1e9, delta=0.02)

    def test_the_image_encoder_is_pinned(self):
        name = self.fam["mmproj"]
        self.assertIn(name, self.fam["sha256"])
        self.assertEqual(self.fam["sha256"][name][1],
                         "13cb7bebccbd04afc8f4090cb949ecf8937cdf7377c5799b1a0c594e7c0d3e16")

    def test_the_repository_revision_is_pinned(self):
        self.assertIn("ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF", setup.HF_REVISIONS)

    def test_the_architecture_maps_back_to_the_family(self):
        # --custom-gguf reads a GGUF's general.architecture and looks the title up in FAMILIES
        from strata_inspect import POLY_ARCHS
        self.assertEqual(POLY_ARCHS["qwen35"], self.fam["title"])
        self.assertEqual(setup.POLY_GGUF_ARCHS["qwen38"], ("qwen35",))


class Plan(unittest.TestCase):
    """The context a card gets is the measured one: 16 GB reaches 200K on the smaller file and 96K on the bigger."""

    def setUp(self):
        self.fam = setup.FAMILIES["qwen38"]

    def test_16_gb_reaches_200k_on_iq2_s(self):
        p = setup.dense_poly_plan(self.fam, "IQ2_S", 16.0)
        self.assertEqual((p["kv"], p["context"], p["batch"], p["fits"]), ("q4_0", 204800, 256, True))
        # measured peak at 200K on the 16 GB host: 15,942 MiB (docs/QWEN38-27B.md)
        self.assertLessEqual(p["need_mib"], 16 * 1024)
        self.assertGreater(p["need_mib"], 15_500)

    def test_16_gb_on_iq3_xxs_stops_at_the_measured_96k(self):
        p = setup.dense_poly_plan(self.fam, "IQ3_XXS", 16.0)
        self.assertEqual((p["context"], p["batch"]), (98304, 1024))
        # measured peak at 96K: 15,351 MiB
        self.assertAlmostEqual(p["need_mib"], 15351, delta=60)

    def test_a_12_gb_card_does_not_fit_either_file(self):
        for model in ("IQ2_S", "IQ3_XXS"):
            self.assertFalse(setup.dense_poly_plan(self.fam, model, 12.0)["fits"], model)

    def test_a_bigger_card_still_respects_what_was_measured(self):
        p = setup.dense_poly_plan(self.fam, "IQ3_XXS", 32.0)
        self.assertEqual(p["context"], 98304)


class Routing(unittest.TestCase):
    """poly_setup hands a dense family to its own steps (no experts, no expert cache, no draft model)."""

    def test_poly_setup_routes_a_dense_family(self):
        calls = []

        def fake_dense(a, family, fam, *rest):
            calls.append((family, fam["title"]))
            return 0
        orig = setup.dense_poly_setup
        setup.dense_poly_setup = fake_dense
        try:
            a = type("A", (), {"model": None})()
            setup.poly_setup(a, "qwen38", {"vram_gb": 16.0, "index": 0, "count": 1}, False, 13, False, 64.0,
                             Path("."), [], 8080, None)
        finally:
            setup.dense_poly_setup = orig
        self.assertEqual(calls, [("qwen38", "Qwen3.8 27B")])


DOWNLOADS = Path(r"C:\AI\Strata-data\models\qwen38-27b")
DOWNLOAD = DOWNLOADS / "Qwen3.8-27B-GSQ-RCO-IQ2_S-mtp.gguf"


@unittest.skipUnless((DOWNLOADS / "Qwen3.8-27B-GSQ-RCO-IQ2_S-mtp.gguf").is_file(), "the IQ2_S file is not on this PC")
class Config(unittest.TestCase):
    """Steps 3 to 7 of the dense install, with the engine step mocked and the files this PC already has: the run
    config it writes is the one the measured server used (docs/QWEN38-27B.md)."""

    def setUp(self):
        self.tmp = Path(__import__("tempfile").mkdtemp(prefix="qwen38-setup-"))
        self.saved = {k: getattr(setup, k) for k in (
            "pip_install", "get_llama_cpp", "get_poly_prebuilt", "build_engine_poly", "build_engine_poly_hip",
            "engine_lib_dirs", "write_run_script", "offer_tray", "start", "write_setup_config", "download")}

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(setup, k, v)

    def args(self, **over):
        a = type("A", (), dict(
            family="qwen38", model="IQ2_S", context=None, kv=None, gguf_dir=str(DOWNLOADS), build=False,
            yes=True, vision=None, vision_tokens=None, vram_reserve_mib=None, host=None, api_key=None, browser=None,
            parallel=None, no_start=True, data_dir=str(self.tmp / "data"), models_dir=str(self.tmp / "models"),
            gpu=0, _custom_gguf_shards=[DOWNLOAD]))()
        for k, v in over.items():
            setattr(a, k, v)
        return a

    def run_setup(self, a, vram=16.0):
        cfg_file = setup.ROOT / "strata-qwen38-iq2_s.json"
        cfg_file.unlink(missing_ok=True)
        written = {}
        setup.pip_install = lambda *x, **k: 0
        def _no_download(*x, **k):
            raise AssertionError("this test must not download anything")
        setup.download = _no_download
        setup.get_llama_cpp = lambda *x, **k: setup.ROOT / "third_party" / "llama.cpp"
        setup.get_poly_prebuilt = lambda *x, **k: None
        setup.build_engine_poly = lambda *x, **k: setup.ROOT / "build"
        setup.build_engine_poly_hip = lambda *x, **k: setup.ROOT / "build"
        setup.engine_lib_dirs = lambda *x, **k: []
        setup.write_run_script = lambda *x, **k: Path("START-qwen38.bat")
        setup.offer_tray = lambda *x, **k: None
        setup.start = lambda *x, **k: 0
        setup.write_setup_config = lambda path, cfg, earlier: (written.update(cfg), Path(path).write_text(
            __import__("json").dumps(cfg, indent=1), encoding="utf-8"))
        out = setup.dense_poly_setup(a, "qwen38", setup.FAMILIES["qwen38"],
                                     {"vram_gb": vram, "index": 0, "count": 1, "name": "RTX 4070 Ti SUPER"},
                                     False, 13, False, 64.0, self.tmp / "data", [], 8080, None)
        cfg_file.unlink(missing_ok=True)
        return out, written

    def test_the_config_is_the_measured_200k_one(self):
        out, cfg = self.run_setup(self.args())
        self.assertEqual(out, 0)
        a = cfg["args"]
        self.assertEqual(a[a.index("--max-context") + 1], "204800")
        self.assertEqual(a[a.index("--kv") + 1], "q4_0")
        self.assertEqual(a[a.index("--prompt-batch") + 1], "256")
        self.assertEqual(cfg["model_name"], "qwen3.8-27b-iq2_s")
        self.assertEqual(cfg["port"], 8080)
        self.assertTrue(cfg["tokenizer"].endswith("tokenizer"))
        self.assertTrue((Path(cfg["tokenizer"]) / "vocab.json").is_file())
        self.assertEqual(cfg["vision"]["min_tokens"], 1024)
        self.assertTrue(cfg["vision"]["mmproj"].endswith("mmproj-Qwen3.8-27B-BF16.gguf"))
        self.assertIs(cfg["vision"]["gpu"], True)

    def test_a_context_past_what_fits_is_refused(self):
        with self.assertRaises(SystemExit):
            self.run_setup(self.args(context=262144))

    def test_a_12_gb_card_is_refused_with_what_to_do(self):
        with self.assertRaises(SystemExit):
            self.run_setup(self.args(), vram=12.0)

if __name__ == "__main__":
    unittest.main()
