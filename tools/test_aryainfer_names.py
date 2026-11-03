#!/usr/bin/env python3
"""The docs say AryaInfer where they mean this fork.  A text that means the project this one is built on names it
by a link or as "the Strata project": tools/aryainfer_names.py leaves those alone, together with every URL, folder
name, file name and saved path it would otherwise rewrite, and a code span or a fenced block a reader copies.

    python -m unittest tools.test_aryainfer_names
"""
from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import aryainfer_names as N  # noqa: E402


class Names(unittest.TestCase):
    def test_examples(self):
        N.demo()

    def test_nothing_is_left_to_rename(self):
        files = io.StringIO()
        try:
            with mock.patch.object(sys, "argv", ["aryainfer_names.py", "--check"]), \
                    contextlib.redirect_stdout(files), contextlib.redirect_stderr(io.StringIO()):
                left = N.main()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("the tool lists the files with git: this is no checkout")
        self.assertEqual(left, 0, "python tools/aryainfer_names.py --check lists:\n" + files.getvalue())

    def test_the_links_follow_the_renamed_doc(self):
        self.assertTrue((ROOT / "docs" / "ARYAINFER.md").is_file())
        self.assertFalse((ROOT / "docs" / "ARYASTRATA.md").exists())
        self.assertIn("[host findings](ARYAINFER.md)", N.rename_links("[host findings](ARYASTRATA.md)"))

    def test_line_endings_survive(self):
        """The pass rewrites words, not line endings: the docs mix LF and CRLF."""
        for name in ("docs/DETAILS.md", "docs/models/qwen38.zh-CN.md"):
            path = ROOT / name
            if not path.is_file():
                continue
            text = N.read_text(path)
            out = N.rename(text)
            self.assertEqual(out.count("\r\n"), text.count("\r\n"), name)
            self.assertEqual(out.count("\n"), text.count("\n"), name)


if __name__ == "__main__":
    unittest.main()
