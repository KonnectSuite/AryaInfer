"""serve/test_engine_flags.py - does the settings catalog still match the engines on disk?

The settings page renders `serve/configschema.py`, not a live `--help` parse: a page that asked the engine at
render time would be slow and would still be wrong for the engine that is not installed.  The price is drift -
a flag added to (or renamed in) an engine never reaches the page.  This test pays that price back: it runs each
installed engine's own help, extracts the flags it advertises, and compares them with the catalog.

Opt-in on purpose.  It needs the engines present and a help screen that answers without a GPU, so the normal
suite never starts one:

    set STRATA_FLAG_DRIFT=1
    python -m unittest serve.test_engine_flags -v

Without the variable every test skips, so CI and a machine without engines stay green.  Set
`STRATA_FLAG_DRIFT=strict` to also fail on catalogue flags the engine does not list - correct for a release
check, too noisy while a flag is only conditionally shown.
"""
from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path

import serve.configschema as schema
from serve import engines as engine_mod

ROOT = Path(__file__).resolve().parents[1]
MODE = os.environ.get("STRATA_FLAG_DRIFT", "").strip().lower()
FLAG_RE = re.compile(r"--[a-z0-9][a-z0-9-]*")
# a help screen that never prints a flag list (poly's shipped binary is silent) cannot be compared
MIN_FLAGS = 5


def _help_text(exe: Path) -> str:
    """Everything an engine prints for --help: strata writes its help to stderr, inkling to stdout."""
    try:
        run = subprocess.run([str(exe), "--help"], capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (run.stdout or "") + "\n" + (run.stderr or "")


def _flags(text: str) -> set[str]:
    return set(FLAG_RE.findall(text))


def installed() -> list[tuple[str, Path]]:
    """(family, executable) for every engine the inventory resolves to a real file."""
    found: list[tuple[str, Path]] = []
    for rec in engine_mod.inventory(ROOT):
        binary = rec.get("binary")
        directory = rec.get("dir")
        if not binary or not directory:
            continue
        exe = (ROOT / directory / binary)
        if not exe.is_file():
            continue
        found.append((schema.engine_family(binary), exe))
    return found


@unittest.skipUnless(MODE, "set STRATA_FLAG_DRIFT=1 to run against the installed engines")
class EngineFlagDrift(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engines = installed()
        cls.help: dict[str, tuple[Path, set[str]]] = {}
        for family, exe in cls.engines:
            if family in cls.help:
                continue                       # one engine per family is enough: they share the flag surface
            flags = _flags(_help_text(exe))
            if len(flags) >= MIN_FLAGS:
                cls.help[family] = (exe, flags)

    def test_an_engine_answered(self) -> None:
        """A run that compared nothing is a green tick over no evidence."""
        self.assertTrue(self.help, f"no engine answered --help with a flag list under {ROOT}")

    def test_every_advertised_flag_is_in_the_catalog(self) -> None:
        """A flag the engine advertises but the catalog has never heard of is a setting the page cannot show.

        Two answers are acceptable for a listed flag: it is a setting (`ENGINE_FLAGS`) or it is recorded in
        `NOT_EDITABLE` with a reason.  Anything else fails, so a flag an engine gains tomorrow cannot slip past.
        """
        unknown: dict[str, list[str]] = {}
        for family, (exe, flags) in self.help.items():
            excused = schema.NOT_EDITABLE.get(family) or {}
            missing = sorted(f for f in flags if f not in schema.ENGINE_FLAGS and f not in excused)
            if missing:
                unknown[family] = missing
        self.assertEqual(unknown, {},
                         "flags that are neither in ENGINE_FLAGS nor recorded in NOT_EDITABLE: "
                         f"{unknown}")

    def test_excused_flags_are_not_also_settings(self) -> None:
        """`NOT_EDITABLE` is where a flag waits, not where it lives: promoting one must delete its excuse."""
        both: dict[str, list[str]] = {}
        for family, excused in schema.NOT_EDITABLE.items():
            overlap = sorted(f for f in excused if f in schema.ENGINE_FLAGS)
            if overlap:
                both[family] = overlap
        self.assertEqual(both, {},
                         f"flags listed as not-editable that the catalog also renders: {both}")

    def test_the_family_set_covers_what_the_engine_lists(self) -> None:
        """ENGINE_FLAGS_OF is what decides which cards a family sees; a gap there hides a working setting."""
        gaps: dict[str, list[str]] = {}
        for family, (_exe, flags) in self.help.items():
            known = schema.ENGINE_FLAGS_OF.get(family) or frozenset()
            extra = schema.EXTRA_ACCEPTED.get(family) or frozenset()
            missing = sorted(f for f in flags if f not in known and f not in extra)
            if missing:
                gaps[family] = missing
        self.assertEqual(gaps, {}, f"flags the engine takes that ENGINE_FLAGS_OF lacks: {gaps}")

    def test_strict_mode_reports_catalog_flags_the_engine_does_not_list(self) -> None:
        """The other direction: a catalogue flag no engine lists is either new, conditionally shown, or gone."""
        if MODE != "strict":
            self.skipTest("set STRATA_FLAG_DRIFT=strict to check the other direction")
        stale: dict[str, list[str]] = {}
        for family, (exe, flags) in self.help.items():
            known = set(schema.ENGINE_FLAGS_OF.get(family) or ()) | set(schema.EXTRA_ACCEPTED.get(family) or ())
            listed = sorted(f for f in known if f not in flags)
            if listed:
                stale[family] = listed
        self.assertEqual(stale, {}, f"flags in the catalog that this engine does not list: {stale}")


if __name__ == "__main__":
    unittest.main()