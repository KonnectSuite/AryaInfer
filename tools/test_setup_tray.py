"""docs/TRAY.md: the tray launcher setup writes at the end of an install, and the sign-in entry it OFFERS.

START-HERE.bat and run-<model>.bat stay the way AryaStrata has always started (AGENTS.md: a new feature is
opt-in, the default path byte-identical): setup adds AryaStrata-Tray.vbs in the install folder, the Startup-folder
entry is offered with the default OFF, and --yes / --no-start are never held up by the question - the tray icon's
own menu can turn the entry on or off later with no setup run.

    python -m unittest tools.test_setup_tray
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import setup  # noqa: E402
from serve.trayctl import AUTOSTART_NAME, autostart_path  # noqa: E402

A = SimpleNamespace(yes=False, no_start=False)
YES = SimpleNamespace(yes=True, no_start=False)
NOSTART = SimpleNamespace(yes=False, no_start=True)


def repo(d):
    """A fake install root the way setup finds one: the tray script and a venv with both python and pythonw."""
    root = Path(d)
    (root / "serve").mkdir(parents=True)
    (root / "serve" / "tray.py").write_text("# the tray icon (serve/tray.py)\n", encoding="utf-8")
    scripts = root / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_bytes(b"python")
    (scripts / "pythonw.exe").write_bytes(b"pythonw")
    return root


class TrayLauncher(unittest.TestCase):
    def test_the_launcher_starts_the_tray_with_no_window(self):
        with tempfile.TemporaryDirectory() as d:
            root = repo(d)
            with mock.patch.object(setup, "ROOT", root):
                p = setup.write_tray_launcher()
            self.assertEqual(p, root / "AryaStrata-Tray.vbs")
            text = p.read_text(encoding="utf-8")
            self.assertIn("pythonw.exe", text)                               # windowless: pythonw, not python
            self.assertIn("serve\\tray.py", text)                            # the tray script in this install
            self.assertTrue(text.rstrip().endswith(", 0, False"))           # Run window 0: no console to close

    def test_the_launcher_is_the_same_text_the_sign_in_entry_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root = repo(d)
            with mock.patch.object(setup, "ROOT", root):
                p = setup.write_tray_launcher()
            launcher = p.read_text(encoding="utf-8")
            from serve.trayctl import autostart_text, pythonw_for
            same = autostart_text(pythonw_for(root / ".venv" / "Scripts" / "python.exe"),
                                  root / "serve" / "tray.py")
            self.assertEqual(launcher, same)                                 # one text, double-click or sign-in

    def test_nothing_is_written_where_the_tray_cannot_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = repo(d)
            with mock.patch.object(setup, "ROOT", root), mock.patch.object(setup, "WIN", False):
                self.assertIsNone(setup.write_tray_launcher())               # Linux/macOS: no tray, no file
            (root / "serve" / "tray.py").unlink()
            with mock.patch.object(setup, "ROOT", root):
                self.assertIsNone(setup.write_tray_launcher())               # no script: no launcher
            self.assertFalse((root / "AryaStrata-Tray.vbs").exists())


class OfferTray(unittest.TestCase):
    def offer(self, a, reply=None, appdata=None):
        """-> (return value, the lines setup said, the ask() calls) with the install root and APPDATA faked."""
        said, asked = [], []

        def ask(question, choices, default, yes):
            asked.append((question, choices, default))
            return reply

        with tempfile.TemporaryDirectory() as d:
            root = repo(d)
            env = {"APPDATA": str(Path(d) / "appdata")} if appdata is not None else {}
            with mock.patch.object(setup, "ROOT", root), mock.patch.object(setup, "say", said.append), \
                    mock.patch.object(setup, "ask", ask), mock.patch.dict(os.environ, env, clear=False):
                p = setup.offer_tray(a)
            if appdata is not None:
                entry = autostart_path(environ={**os.environ, **env})
                return p, said, asked, (entry.read_text(encoding="utf-8") if entry and entry.exists() else None)
            return p, said, asked, None

    def test_the_launcher_is_written_and_the_entry_is_offered_default_off(self):
        p, said, asked, entry = self.offer(A, reply="n", appdata="x")
        self.assertTrue(p and p.name == "AryaStrata-Tray.vbs")
        self.assertTrue(any("docs/TRAY.md" in s for s in said))              # the line points at the how-to
        self.assertEqual(len(asked), 1)
        question, choices, default = asked[0]
        self.assertIn("sign-in", question)
        self.assertEqual((choices, default), (["y", "n"], "n"))              # opt-in: OFF is the default
        self.assertIsNone(entry)                                             # "n": no Startup entry

    def test_answering_y_writes_the_sign_in_entry_for_the_windowless_python(self):
        p, said, asked, entry = self.offer(A, reply="y", appdata="x")
        self.assertIsNotNone(entry)
        self.assertIn("pythonw.exe", entry)
        self.assertIn("tray.py", entry)
        self.assertTrue(entry.rstrip().endswith(", 0, False"))

    def test_a_answered_run_asks_nothing(self):
        for a in (YES, NOSTART):                                             # --yes, --no-start
            p, said, asked, entry = self.offer(a, appdata="x")
            self.assertTrue(p and p.name == "AryaStrata-Tray.vbs")
            self.assertEqual(asked, [])                                      # never held up by a question
            self.assertIsNone(entry)

    def test_setup_offers_the_tray_on_every_finish_of_an_install(self):
        src = (ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("\n    offer_tray(a)\n"), 3)              # the three "Next time:" exits


if __name__ == "__main__":
    unittest.main()
