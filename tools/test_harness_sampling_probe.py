"""tools/test_harness_sampling_probe.py - the fixture checks fail closed on canned answers.

No GPU and no server: every check function gets the answer a correct model would write
and one a lazy or truncated model would write, and the pair must flip pass and fail.
The point is the gate, not the model - a check that passes a bad answer is worse than
no check, because a tuning table would then trust it.

    python -m unittest tools.test_harness_sampling_probe
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_sampling_probe as probe   # noqa: E402


GOOD_HTML = """<!doctype html>
<html><head><title>Northline Bikes</title><style>body{font-family:sans-serif}
header{position:sticky;top:0} .card{padding:1rem}</style></head>
<body><header><nav><a href="#s">Services</a><a href="#p">Prices</a><a href="#a">About</a>
<a href="#c">Contact</a></nav></header>
<section class="hero"><h1>Northline Bikes</h1><p>Repairs done right.</p>
<button onclick="scroll()">Book now</button></section>
<section><div class="card">Tune-up</div><div class="card">Wheel true</div>
<div class="card">Brakes</div></section>
<table><tr><td>Tune-up</td><td>45</td></tr><tr><td>Wheel</td><td>25</td></tr>
<tr><td>Brakes</td><td>30</td></tr></table>
<footer>Contact: northline@example.com</footer></body></html>""" + ("x" * 1600)

BAD_HTML_SHORT = "<!doctype html><html><head><title>Northline Bikes</title></head><body>coming soon</body></html>"
BAD_HTML_UNBALANCED = GOOD_HTML.replace("</div>", "", 1)


GOOD_GAME = """<!doctype html><html><head><title>Memory</title></head><body>
<div id="grid"></div><button id="restart">Restart</button><script>
const cards = [1,1,2,2,3,3,4,4,5,5,6,6];
function flip(){}
document.querySelectorAll('.card').forEach(c => c.addEventListener('click', flip));
document.getElementById('restart').addEventListener('click', () => reset());
</script></body></html>""" + ("pad " * 500)


GOOD_PY = """```python
import tkinter as tk
from tkinter import messagebox

def to_f():
    try:
        c = float(entry.get())
        result.config(text=f"{(c*9/5)+32:.1f} F")
    except ValueError:
        messagebox.showerror("Bad input", "enter a number")

root = tk.Tk()
root.title("Unit Converter")
entry = tk.Entry(root); entry.pack()
tk.Button(root, text="C to F", command=to_f).pack()
result = tk.Label(root); result.pack()
root.mainloop()
```"""

BAD_PY_NOCOMPILE = GOOD_PY.replace("try:", "try", 1)
BAD_PY_NOLOOP = GOOD_PY.replace("root = tk.Tk()", "root = None").replace("root.mainloop()", "# done")


GOOD_EMAIL = """Subject: Rate update on March 3

Dear Ms. Alvarez,

Thank you for the wonderful work we have shared over these years. I am writing to let
you know that our hourly rate will move from $120 to $138 effective March 3. Nothing
else about how we work together changes.

I would be glad to set up a call this month to talk through the projects in flight and
answer any questions.

With appreciation,
Jordan"""

BAD_EMAIL_NOFIGURES = GOOD_EMAIL.replace("$120 to $138", "going up soon")
BAD_EMAIL_NOCALL = GOOD_EMAIL.replace("set up a call", "write back")


GOOD_QUOTE = """QUOTE - Blue Harbor Cafe

Item                  Qty  Unit price   Line total
Counter stools        12   149.00       1788.00
Custom oak bar top    1    1250.00      1250.00
Pendant lights        5    19.90        99.50

Subtotal                            3137.50
VAT (19%)                           596.13
Grand total                         3733.63"""

BAD_QUOTE_MATH = GOOD_QUOTE.replace("3137.50", "3137.00")
BAD_QUOTE_NOTOTAL = GOOD_QUOTE.replace("3733.63", "3700.00")


GOOD_MINUTES = """Decisions
- Deploy on May 6
- API freeze starts Monday night

Actions
- Dana owns the deployment runbook
- Ian to price two additional staging VMs by Friday
- Move the standup earlier next week

Open questions
- Whether the staging budget covers two more VMs"""

BAD_MINUTES = "We decided to deploy May 6. Dana owns the runbook. Budget still unclear."


GOOD_LOG = """Added:
- a1b9c2d add CSV export to the reports screen
- c9d0e1b add dark mode toggle in settings

Fixed:
- f4e2d1a fix crash when a filter date was empty
- b2c3d4e fix slow search on large catalogs"""

BAD_LOG_LOST_HASH = GOOD_LOG.replace("c9d0e1b", "xxxxxxx")
BAD_LOG_NOGROUPS = "Release 1.4.0 shipped four changes including CSV export."


class FixtureChecks(unittest.TestCase):
    def pairs(self):
        return [
            ("web_page", GOOD_HTML, BAD_HTML_SHORT, BAD_HTML_UNBALANCED),
            ("game_memory", GOOD_GAME, BAD_HTML_SHORT, GOOD_HTML),
            ("gui_converter", GOOD_PY, BAD_PY_NOCOMPILE, BAD_PY_NOLOOP),
            ("email_rate", GOOD_EMAIL, BAD_EMAIL_NOFIGURES, BAD_EMAIL_NOCALL),
            ("quote_cafe", GOOD_QUOTE, BAD_QUOTE_MATH, BAD_QUOTE_NOTOTAL),
            ("minutes_notes", GOOD_MINUTES, BAD_MINUTES, GOOD_EMAIL),
            ("changelog_140", GOOD_LOG, BAD_LOG_LOST_HASH, BAD_LOG_NOGROUPS),
        ]

    def test_good_passes_and_bad_fails(self):
        for name, good, bad1, bad2 in self.pairs():
            prompt, check, _cap = probe.SUITES["artifact"].get(name) or probe.SUITES["writing"].get(name)
            ok, why = check(good)
            self.assertTrue(ok, f"{name}: good answer rejected ({why})")
            for bad in (bad1, bad2):
                ok, why = check(bad)
                self.assertFalse(ok, f"{name}: bad answer accepted ({bad[:40]!r})")

    def test_truncation_is_always_a_fail(self):
        # a body() capped mid-document must never look like a pass: the html gate wants
        # the closing tag, the quote gate wants the totals line.
        ok, _ = probe.SUITES["artifact"]["web_page"][1](GOOD_HTML[:900])
        self.assertFalse(ok)
        ok, _ = probe.SUITES["writing"]["quote_cafe"][1](GOOD_QUOTE[:80])
        self.assertFalse(ok)


class Body(unittest.TestCase):
    def test_config_set_sends_no_sampling_keys(self):
        b = probe.body("m", [{"role": "user", "content": "x"}], None, 900)
        self.assertNotIn("temperature", json.dumps(b))
        self.assertEqual(b["reasoning_effort"], "off")

    def test_named_set_merges_onto_the_wire(self):
        b = probe.body("m", [{"role": "user", "content": "x"}], probe.SETS["precise"], 900)
        self.assertEqual(b["temperature"], 0.3)
        self.assertEqual(b["top_k"], 20)
        self.assertEqual(b["reasoning_effort"], "off")

    def test_sets_cover_the_documented_values(self):
        self.assertEqual(probe.SETS["coding"]["temperature"], 0.6)
        self.assertEqual(probe.SETS["coding"]["top_p"], 0.95)
        self.assertIsNone(probe.SETS["config"])


class Boilerplate(unittest.TestCase):
    def test_rep4_ignores_short_answers_and_flags_loops(self):
        self.assertEqual(probe._rep4("one two three"), 0.0)
        looped = ("very long tail of tokens is here " * 30)
        varied = " ".join(f"token number {i} differs each time" for i in range(30))
        self.assertGreater(probe._rep4(looped), 0.5)
        self.assertLess(probe._rep4(varied), probe._rep4(looped))


if __name__ == "__main__":
    unittest.main(verbosity=2)
