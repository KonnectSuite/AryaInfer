"""The tuned run configs are portable: tools/apply_host_tuning.py fills the two placeholders in and writes them out.

    python -m unittest tools.test_apply_host_tuning
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import apply_host_tuning as T  # noqa: E402


class Tuning(unittest.TestCase):
    def test_the_copies_are_json_with_placeholders_and_no_machine_path(self):
        names = T.configs()
        self.assertTrue(names, "docs/host-tuning has run configs")
        for src in names:
            text = src.read_text(encoding="utf-8")
            json.loads(text)                                    # valid JSON: the placeholders are plain strings
            self.assertIn("$INSTALL", text, src.name)
            self.assertNotIn('"C:\\\\', text, f"{src.name} carries a Windows path")

    def test_placeholders_become_the_install_and_the_data_folder(self):
        src = T.configs()[0]
        cfg = T.fill(json.loads(src.read_text(encoding="utf-8")), r"C:\AryaInfer", r"C:\AI\Strata-data")
        blob = json.dumps(cfg)
        self.assertNotIn("$INSTALL", blob)
        self.assertNotIn("$DATA", blob)
        self.assertIn("C:\\\\AryaInfer", blob)                  # escaped once, as JSON needs it

    def test_a_dry_run_writes_nothing_and_a_real_run_keeps_the_earlier_config(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d)
            same = T.configs()[0].name                              # a config the install already has
            (dest / same).write_text('{"exe": "old"}', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(T.main(["--install", d, "--data", r"C:\data", "--dry-run"]), 0)
            self.assertEqual(sorted(p.name for p in dest.iterdir()), [same])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(T.main(["--install", d, "--data", r"C:\data"]), 0)
            names = sorted(p.name for p in dest.iterdir())
            self.assertIn(same + ".bak-host-tuning", names)         # the earlier config is kept
            self.assertEqual(sorted(p.name for p in dest.glob("strata-*.json")),
                             sorted(src.name for src in T.configs()))
            self.assertTrue((dest / "local-data").is_dir())          # where the engine's log goes exists too
            blob = json.dumps(json.loads((dest / same).read_text(encoding="utf-8")))
            self.assertNotIn("$INSTALL", blob)
            self.assertNotIn("$DATA", blob)

    def test_a_missing_install_is_refused(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            T.main(["--install", str(Path(tempfile.gettempdir()) / "no-such-install-xyz"), "--data", "d"])


if __name__ == "__main__":
    unittest.main()
