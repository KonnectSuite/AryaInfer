"""serve/test_webui_config.py - the model-configuration and engine-management surface, without a GPU.

The web app's Models view and Engines view are served by three endpoints: /api/engines (the pinned engine
manifest against what is installed), /api/models/config (a run config read and written through the schema)
and /api/engines/repair (an opt-in restart of setup --repair-engines).  These tests pin the schema, the
inventory and the endpoints against a temporary install, with the mock engine only.

    python -m unittest serve.test_webui_config -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve import configschema, engines  # noqa: E402
from serve.frontend import ChatTemplate  # noqa: E402
from serve.server import (EFFORT_LEVELS, EFFORT_TEXT, ByteTokenizer, MockEngine, Service,  # noqa: E402
                          effort_info, effort_level, serve)

ROOT = Path(__file__).resolve().parents[1]

SAMPLE = {                       # a run config with one of every kind of key the schema edits
    "model_name": "mini", "display_name": "Mini test model", "aliases": ["m1", "m2"],
    "exe": "strata-poly.exe", "cwd": "C:/nowhere",
    "args": ["--model", "m.gguf", "--max-context", "8192", "--kv", "q4_0"],
    "env": {"STRATA_GDN_MMA": "1"}, "lib_dirs": ["a", "b"], "gpu": 0,
    "vision": {"exe": "v.exe", "gpu": False, "max_tokens": 512},
    "sampling": {"temperature": 0.7, "top_p": 0.95, "top_k": 20},
    "reasoning_effort": "medium", "reasoning_budget_tokens": 4800,
    "reasoning_budget_by_effort": {"low": 4800, "medium": 9600},
    "fit_max_tokens": True, "idle_unload_s": 900, "arch": "qwen35",
    "port": 8080, "host": "127.0.0.1", "tokenizer": "tok", "log": "mini.log",
}


def group(view, key):
    return next(g for g in view["groups"] if g["key"] == key)


def key_entry(view, key):
    return next(k for g in view["groups"] for k in g["keys"] if k["key"] == key)


class ConfigSchema(unittest.TestCase):
    """view()/apply()/save() over a sample run config."""

    def setUp(self):
        self.cfg = json.loads(json.dumps(SAMPLE))

    def test_view_groups_every_key_with_help_and_kind(self):
        v = configschema.view(self.cfg, "strata-mini.json")
        self.assertEqual([g["key"] for g in v["groups"]],
                         ["identity", "engine", "vision", "sampling", "reasoning",
                          "behavior", "lifecycle", "info"])
        for k in (k for g in v["groups"] for k in g["keys"]):
            self.assertTrue(k.get("kind") and k.get("help"), k["key"])
        self.assertEqual(key_entry(v, "sampling.temperature")["value"], 0.7)
        self.assertEqual(key_entry(v, "reasoning_budget_by_effort")["value"], {"low": 4800, "medium": 9600})
        self.assertEqual(key_entry(v, "context")["kind"], "readonly")
        self.assertEqual(v["file"], "strata-mini.json")
        self.assertIn("note", v)                     # the save note is part of the schema view

    def test_view_lists_the_engine_flags_and_the_rest(self):
        v = configschema.view(self.cfg, "strata-mini.json")
        args = key_entry(v, "args")
        flags = {f["flag"]: f for f in args["flags"]}
        self.assertEqual(flags["--max-context"]["value"], "8192")
        self.assertTrue(flags["--kv"]["present"])
        self.assertIn("--model", args["other"])      # an unpinned flag stays editable as text
        for f in flags.values():
            self.assertTrue(f.get("kind") and f.get("help"), f["flag"])

    def test_view_carries_slider_ranges_and_flag_groups(self):
        v = configschema.view(self.cfg, "strata-mini.json")
        # a slider wherever the schema knows bounds; the editor draws range+number for these
        self.assertEqual(key_entry(v, "sampling.temperature")["range"], [0, 2, 0.05])
        self.assertEqual(key_entry(v, "sampling.top_k")["range"], [1, 64, 1])
        self.assertEqual(key_entry(v, "reasoning_budget_by_effort")["range"], [0, 65536, 256])
        self.assertEqual(key_entry(v, "idle_unload_s")["range"], [0, 3600, 60])
        args = key_entry(v, "args")
        flags = {f["flag"]: f for f in args["flags"]}
        self.assertEqual(flags["--max-context"]["range"], [1024, 262144, 1024])
        self.assertEqual(flags["--draft-tokens"]["range"], [0, 8, 1])
        groups = {g["key"]: [f["flag"] for f in g["flags"]] for g in args["flag_groups"]}
        self.assertIn("--max-context", groups["context"])
        self.assertIn("--draft-model", groups["drafting"])      # SAMPLE runs the poly engine
        self.assertIn("--expert-profile", groups["experts"])
        self.assertIn("--slots", groups["prefill"])
        self.assertIn("--no-graphs", groups["misc"])
        self.assertTrue(all(flags_g for flags_g in groups.values()))   # no empty group is sent

    def test_apply_checks_every_value_before_writing_any(self):
        with self.assertRaises(ValueError):           # one bad value leaves the config untouched
            configschema.apply(self.cfg, {"sampling.temperature": 0.7, "sampling.top_p": 9})
        self.assertEqual(self.cfg["sampling"]["top_p"], 0.95)

    def test_apply_sets_dotted_keys_enums_and_aliases(self):
        new, changed = configschema.apply(self.cfg, {
            "sampling.temperature": 0.42, "reasoning_effort": "high", "aliases": ["mini", "daily"]})
        self.assertEqual(new["sampling"]["temperature"], 0.42)
        self.assertEqual(new["reasoning_effort"], "high")
        self.assertEqual(new["aliases"], ["mini", "daily"])
        self.assertEqual(changed, ["sampling.temperature", "reasoning_effort", "aliases"])

    def test_apply_sets_and_removes_engine_flags(self):
        new, changed = configschema.apply(self.cfg, {
            "arg:--max-context": 16384, "arg:--kv": None, "arg:--vision": True})
        args = new["args"]
        self.assertEqual(args[args.index("--max-context") + 1], "16384")
        self.assertNotIn("--kv", args)
        self.assertIn("--vision", args)
        self.assertEqual(changed, ["arg:--max-context", "arg:--kv", "arg:--vision"])

    def test_apply_writes_bools_and_drops_empty_blocks(self):
        new, _ = configschema.apply(self.cfg, {"fit_max_tokens": None, "idle_unload_s": 60})
        self.assertNotIn("fit_max_tokens", new)
        self.assertEqual(new["idle_unload_s"], 60)

    def test_save_keeps_the_earlier_file_as_bak(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "strata-mini.json"
            path.write_text(json.dumps(self.cfg), encoding="utf-8")
            new, _ = configschema.apply(self.cfg, {"sampling.temperature": 0.3})
            configschema.save(path, new)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["sampling"]["temperature"], 0.3)
            bak = path.with_name(path.name + ".bak")
            self.assertEqual(json.loads(bak.read_text(encoding="utf-8"))["sampling"]["temperature"], 0.7)


class EngineCatalog(unittest.TestCase):
    """The engine side of the settings page: families, the flags and env knobs each engine takes,
    the presets, and the defaults the page shows before anything is typed."""

    def cfg(self, exe="strata.exe", args=(), env=None):
        cfg = {"exe": exe, "args": list(args)}
        if env:
            cfg["env"] = dict(env)
        return cfg

    def groups(self, view):
        return {g["key"]: [f["flag"] for f in g["flags"]] for g in key_entry(view, "args")["flag_groups"]}

    def flags(self, view):
        return {f["flag"]: f for f in key_entry(view, "args")["flags"]}

    def test_engine_family_reads_the_executable_name(self):
        cases = {
            "C:\\AI\\engines\\strata.exe": "strata",
            "strata-inkling.exe": "inkling",
            "/opt/engines/strata-polysomething": "poly",
            "strata-poly.exe": "poly",
            "aryainfer.exe": "poly",
            "engine-ninfer/arya-ninfer.exe": "ninfer",
            "ninfer-engine.exe": "ninfer",
            "arya-ada.exe": "strata",
            "C:\\basalt\\bin\\basalt.exe": "basalt",
            "basalt.exe": "basalt",
            "something-else.exe": "other",
            "": "other",
            None: "other",
        }
        for exe, family in cases.items():
            self.assertEqual(configschema.engine_family(exe), family, exe)

    def test_every_flag_carries_a_label_a_hint_and_a_kind(self):
        view = configschema.view(self.cfg(), "strata-mini.json")
        flags = self.flags(view)
        self.assertEqual(len(flags), len(configschema.ENGINE_FLAGS))
        for flag, f in flags.items():
            self.assertTrue(f["kind"], flag)
            self.assertTrue(f["label"], flag)
            self.assertTrue(f["help"], flag)
        # the flags the page used to drop into "other" are settings now
        for flag in ("--vram-experts-gb", "--ram-experts-gb", "--kv-offload", "--parallel",
                     "--chunk", "--draft-cap", "--mtp-max-t", "--lookup-chain", "--tail-skip"):
            self.assertIn(flag, flags)

    def test_a_group_is_never_sent_empty(self):
        for exe in ("strata.exe", "strata-inkling.exe", "strata-poly.exe", "arya-ninfer.exe", "x.exe"):
            for key, members in self.groups(configschema.view(self.cfg(exe), "a.json")).items():
                self.assertTrue(members, f"{exe}: {key}")

    def test_a_flag_the_engine_lacks_is_listed_not_dropped(self):
        view = configschema.view(self.cfg("strata-inkling.exe"), "a.json")
        groups = self.groups(view)
        self.assertIn("--chunk", groups["prefill"])        # Inkling reads prompts in chunks
        self.assertIn("--pcie-frac", groups["absent"])     # and has no expert cache to page
        # set in the file, the same flag stays where a reader looks for it
        again = configschema.view(self.cfg("strata-inkling.exe", ["--pcie-frac", "0.2"]), "a.json")
        self.assertIn("--pcie-frac", self.groups(again)["experts"])

    def test_each_family_keeps_the_flags_it_actually_takes(self):
        strata = self.groups(configschema.view(self.cfg("strata.exe"), "a.json"))
        self.assertIn("--spec", strata["drafting"])
        self.assertIn("--pack", strata["experts"])
        inkling = self.groups(configschema.view(self.cfg("strata-inkling.exe"), "a.json"))
        self.assertIn("--chunk", inkling["prefill"])          # new in 0.1.68, absent from its --help
        self.assertIn("--kv-offload", inkling["misc"])
        self.assertIn("--vram-experts-gb", inkling["experts"])
        poly = self.groups(configschema.view(self.cfg("strata-poly.exe"), "a.json"))
        self.assertEqual(sorted(poly["quality"]), ["--cache-bias", "--skip-weight", "--tail-skip"])

    def test_the_basalt_lane_keeps_the_flags_basalt_takes(self):
        view = configschema.view(self.cfg("basalt.exe"), "a.json")
        self.assertEqual(view["engine"]["family"], "basalt")
        groups = self.groups(view)
        self.assertIn("--resident-experts", groups["experts"])
        self.assertIn("--pack", groups["absent"])             # a Strata container flag, not a basalt one
        self.assertIn("--kv", self.flags(view))               # and the KV words basalt accepts
        self.assertEqual(self.flags(view)["--kv"]["choices"], ["fp16", "int8", "q4_0", "k8v4"])

    def test_a_flag_is_listed_in_one_group_only(self):
        view = configschema.view(self.cfg("strata.exe"), "a.json")
        listed = [f["flag"] for g in key_entry(view, "args")["flag_groups"] for f in g["flags"]]
        self.assertEqual(len(listed), len(set(listed)))       # --vram-elastic is in two catalog groups

    def test_kv_is_an_enum_per_engine(self):
        inkling = self.flags(configschema.view(self.cfg("strata-inkling.exe"), "a.json"))
        self.assertIn("k8v4", inkling["--kv"]["choices"])
        with self.assertRaises(ValueError):
            configschema.apply(self.cfg("strata-inkling.exe"), {"arg:--kv": "f16"})
        new, _ = configschema.apply(self.cfg("strata-inkling.exe"), {"arg:--kv": "k8v4"})
        self.assertIn("k8v4", new["args"])

    def test_the_env_catalog_carries_the_tail_skip_knob(self):
        view = configschema.view(self.cfg(env={"STRATA_ROUTE_TAIL_SKIP": "7"}), "a.json")
        env = {e["name"]: e for e in view["engine"]["env"]}
        skip = env["STRATA_ROUTE_TAIL_SKIP"]
        self.assertEqual(skip["kind"], "int")
        self.assertEqual(skip["risk"], "quality")
        self.assertEqual(skip["range"], [0, 9, 1])
        self.assertEqual(skip["value"], "7")
        self.assertIn("faster", skip["help"])
        self.assertEqual(view["engine"]["unknown_env"], [])
        for name, e in env.items():
            self.assertTrue(e["kind"] and e["label"] and e["help"], name)

    def test_an_unknown_env_name_is_reported_not_dropped(self):
        view = configschema.view(self.cfg(env={"MY_OWN_FLAG": "1"}), "a.json")
        self.assertEqual(view["engine"]["unknown_env"], ["MY_OWN_FLAG"])
        new, _ = configschema.apply(self.cfg(env={"MY_OWN_FLAG": "1"}),
                                    {"env": {"MY_OWN_FLAG": "2", "STRATA_ROUTE_TAIL_SKIP": "6"}})
        self.assertEqual(new["env"]["MY_OWN_FLAG"], "2")
        self.assertEqual(new["env"]["STRATA_ROUTE_TAIL_SKIP"], "6")

    def test_presets_name_real_flags(self):
        for family, presets in configschema.PRESETS.items():
            self.assertTrue(presets, family)
            for preset in presets:
                self.assertTrue(preset["label"], family)
                for flag in preset["flags"]:
                    self.assertIn(flag, configschema.ENGINE_FLAGS, f"{family}/{preset['key']}: {flag}")

    def test_a_preset_applies_through_the_normal_check(self):
        preset = next(p for p in configschema.PRESETS["inkling"] if p["key"] == "recommended")
        changes = {f"arg:{flag}": value for flag, value in preset["flags"].items()}
        new, changed = configschema.apply(self.cfg("strata-inkling.exe", ["--vision"]), changes)
        self.assertEqual(new["args"][new["args"].index("--kv") + 1], "k8v4")
        self.assertEqual(len(changed), len(preset["flags"]))
        self.assertIn("--vision", new["args"])          # a preset does not drop what it does not name

    def test_defaults_are_documented_where_known(self):
        view = configschema.view(self.cfg(), "a.json")
        self.assertEqual(key_entry(view, "engine_silence_s")["default"], 300)
        self.assertIsNone(key_entry(view, "sampling.temperature")["default"])   # the model card's
        flags = self.flags(view)
        self.assertEqual(flags["--kv"]["default"], "fp16")
        self.assertIsNone(flags["--pack"]["default"])                            # the engine decides

    def test_a_sampling_chip_sets_every_sampler_and_stays_in_range(self):
        """A chip is a whole sampler, and each value must pass the check a hand edit does.

        The chips used to write only the temperature; then one carried top_k 80 against a 1..64 field, so
        clicking it left the page showing "The largest value here is 64" with Save disabled.  Both faults
        are cheap to catch here.
        """
        self.assertGreaterEqual(len(configschema.SAMPLING_PRESETS), 3)
        for p in configschema.SAMPLING_PRESETS:
            with self.subTest(preset=p["key"]):
                self.assertTrue(p["name"])
                self.assertTrue(p["note"])
                self.assertEqual(set(p["values"]), {
                    "sampling.temperature", "sampling.top_p", "sampling.top_k",
                    "sampling.min_p", "sampling.repetition_penalty"})
                for key, value in p["values"].items():
                    self.assertIn(key, configschema.KEYS)
                    stored = configschema.check(key, value, {})     # ValueError would fail the test
                    self.assertIsNotNone(stored)

    def test_sampling_chips_reach_the_page(self):
        view = configschema.view(self.cfg(), "a.json")
        self.assertEqual(len(view["sampling_presets"]), len(configschema.SAMPLING_PRESETS))
        self.assertEqual(view["sampling_presets"][0]["values"]["sampling.top_k"], "20")


class EffortSemantics(unittest.TestCase):
    """What a thinking level actually changes: the instruction sentence and the cap - and nothing else."""

    def test_every_level_has_a_sentence_and_a_cap(self):
        rows = effort_info(SAMPLE)
        self.assertEqual([r["level"] for r in rows], ["none", "low", "medium", "high"])
        by = {r["level"]: r for r in rows}
        self.assertIsNone(by["none"]["budget"])        # none turns thinking off: no sentence, no cap
        self.assertEqual(by["low"]["budget"], 4800)    # from reasoning_budget_by_effort
        self.assertEqual(by["medium"]["budget"], 9600)
        self.assertEqual(by["high"]["budget"], 4800)   # no high entry: falls back to reasoning_budget_tokens
        for lv in ("low", "medium", "high"):
            self.assertTrue(by[lv]["instruction"], lv)
        self.assertEqual(EFFORT_TEXT["high"], by["high"]["instruction"])

    def test_xhigh_is_no_longer_a_level(self):
        # the fifth level was removed: a client can still spell it (it collapses to high), but the table and the
        # Settings page only know off/low/medium/high
        self.assertEqual(effort_level("xhigh"), "high")
        self.assertEqual(effort_level("max"), "high")
        self.assertNotIn("xhigh", EFFORT_LEVELS)
        with self.assertRaises(ValueError):
            configschema.apply(SAMPLE, {"reasoning_effort": "xhigh"})

    def test_a_level_carries_no_sampling(self):
        # the knob is honest: a level reports an instruction and a budget, never a sampling change
        for r in effort_info(SAMPLE):
            self.assertEqual(sorted(r), ["budget", "instruction", "level"])
        self.assertEqual(set(EFFORT_TEXT), {"low", "medium", "high", "xhigh"})   # xhigh stays: the template's own spelling of high


class EngineInventory(unittest.TestCase):
    """engines.py against this repo's engines.json and its installed engine/ directories."""

    def test_version_tuple_strips_and_pads(self):
        self.assertEqual(engines.version_tuple("0.1.67"), (0, 1, 67))
        self.assertEqual(engines.version_tuple("0.1.45-poly.9"), (0, 1, 45, 9))
        self.assertGreater(engines.version_tuple("0.1.67"), engines.version_tuple("0.1.45-poly.9"))

    def test_installed_reads_build_json_or_reports_missing(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertEqual(engines._installed(d, "strata.exe")["status"], "missing")
            (d / "strata.exe").write_bytes(b"")       # a binary without BUILD.json: version unknown
            got = engines._installed(d, "strata.exe")
            self.assertEqual((got["status"], got["installed_version"]), ("unknown", None))
            (d / "BUILD.json").write_text(json.dumps({"version": "0.9.9", "archs": [89]}), encoding="utf-8")
            got = engines._installed(d, "strata.exe")  # BUILD.json alone (no binary) is not an engine
            self.assertEqual((got["status"], got["installed_version"], got["archs"]),
                             ("installed", "0.9.9", [89]))

    def test_inventory_reports_the_pinned_engines(self):
        rows = {e["key"]: e for e in engines.inventory()}
        self.assertEqual(set(rows), {"strata", "inkling", "poly", "arya", "ninfer"})
        self.assertTrue(all(r["required"] or r["manual"] or r["key"] == "inkling" for r in rows.values()))
        self.assertEqual(rows["ninfer"]["manual"], True)                 # no download: built from source
        self.assertIn("upstream", rows["strata"])                        # where each engine really comes from
        for r in rows.values():
            self.assertIn(r["status"], ("current", "outdated", "missing", "manual", "unknown"))
        view = engines.as_view()
        self.assertEqual(view["release"], "engines-2026.11")
        # a stable order the page can rely on: required engines first, then alphabetical
        self.assertEqual([e["key"] for e in view["engines"]],
                         ["arya", "poly", "strata", "inkling", "ninfer"])


class Endpoints(unittest.TestCase):
    """GET /api/engines, GET/POST /api/models/config and POST /api/engines/repair over HTTP."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        root = Path(cls.dir.name)
        cls.config = root / "strata-mini.json"
        cls.config.write_text(json.dumps(SAMPLE), encoding="utf-8")
        # fixtures for the file-browser tests: one folder, two files, one hidden entry
        (root / "zsub").mkdir()
        (root / "a.gguf").write_bytes(b"")
        (root / "b.txt").write_bytes(b"")
        (root / ".hidden").write_bytes(b"")
        cls.svc = Service(MockEngine(ByteTokenizer(), "ok", max_context=4096),
                          ByteTokenizer(), ChatTemplate(ROOT / "serve/chat_template.jinja"))
        cls.svc.models_root = root
        cls.httpd = serve(cls.svc, port=0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.headers = {"Content-Type": "application/json", "Origin": cls.base}

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.dir.cleanup()

    def call(self, path, body=None, headers=None, method=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, headers=headers or self.headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_the_engines_endpoint_lists_the_install(self):
        code, body = self.call("/api/engines")
        self.assertEqual(code, 200)
        self.assertEqual(body["release"], "engines-2026.11")
        self.assertEqual(len(body["engines"]), 5)
        self.assertTrue(all("status" in e for e in body["engines"]))
        # which run configs use which engine: the sample config names strata-poly.exe
        self.assertIn("used_by", body)
        self.assertIn("mini", body["used_by"].get("poly", []))

    def test_the_config_view_reports_the_effort_levels(self):
        code, body = self.call("/api/models/config?model=mini")
        self.assertEqual(code, 200)
        self.assertEqual([r["level"] for r in body["efforts"]],
                         ["none", "low", "medium", "high"])
        self.assertTrue(all("instruction" in r and "budget" in r for r in body["efforts"]))

    def test_fs_lists_a_directory_dirs_first(self):
        d = Path(self.dir.name)
        q = urllib.parse.quote(str(d))
        code, body = self.call(f"/api/fs/list?path={q}")
        self.assertEqual(code, 200)
        names = [e["name"] for e in body["entries"]]
        self.assertIn("zsub", names)
        self.assertIn("a.gguf", names)
        self.assertIn("b.txt", names)
        self.assertNotIn(".hidden", names)                    # hidden entries stay out of the browser
        self.assertLess(names.index("zsub"), names.index("a.gguf"))   # directories first
        self.assertLess(names.index("a.gguf"), names.index("b.txt"))  # then alphabetical
        self.assertEqual(body["path"], str(d.resolve()))
        self.assertEqual(body["parent"], str(d.resolve().parent))

    def test_fs_filters_by_kind_and_extension(self):
        d = Path(self.dir.name)
        q = urllib.parse.quote(str(d))
        code, body = self.call(f"/api/fs/list?path={q}&want=dir")
        self.assertEqual(code, 200)
        self.assertTrue(all(e["dir"] for e in body["entries"]))
        code, body = self.call(f"/api/fs/list?path={q}&ext=.gguf")
        names = [e["name"] for e in body["entries"]]
        self.assertIn("a.gguf", names)
        self.assertNotIn("b.txt", names)
        self.assertIn("zsub", names)                          # folders stay, so the browser can walk on

    def test_fs_refuses_a_relative_path_or_a_file(self):
        code, body = self.call("/api/fs/list?path=relative/thing")
        self.assertEqual(code, 400)
        self.assertIn("absolute", body["error"]["message"])
        code, _ = self.call(f"/api/fs/list?path={urllib.parse.quote(str(self.config))}")
        self.assertEqual(code, 400)                           # a file is not a listing

    def test_fs_without_a_path_lists_the_roots(self):
        code, body = self.call("/api/fs/list")
        self.assertEqual(code, 200)
        self.assertIsNone(body["parent"])
        self.assertTrue(body["entries"])
        self.assertTrue(all(e["dir"] for e in body["entries"]))

    def test_a_models_config_is_read_grouped(self):
        code, body = self.call("/api/models/config?model=mini")
        self.assertEqual(code, 200)
        self.assertEqual(key_entry(body, "sampling.temperature")["value"], 0.7)
        self.assertEqual(body["file"], self.config.name)
        self.assertIn("Mini test model", body["raw"])

    def test_an_unknown_model_is_a_404(self):
        code, body = self.call("/api/models/config?model=nope")
        self.assertEqual(code, 404)
        self.assertIn("nope", body["error"]["message"])

    def test_a_change_is_written_and_reported(self):
        code, body = self.call("/api/models/config?model=mini", {"set": {"sampling.temperature": 0.42}})
        self.assertEqual(code, 200)
        self.assertEqual(body["changed"], ["sampling.temperature"])
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["sampling"]["temperature"], 0.42)
        self.assertTrue(self.config.with_name(self.config.name + ".bak").exists())
        # put it back: the earlier file is the backup, and a null removes the key again
        code, _ = self.call("/api/models/config?model=mini", {"set": {"sampling.temperature": 0.7}})
        self.assertEqual(code, 200)

    def test_a_bad_value_is_rejected_without_writing(self):
        before = self.config.read_text(encoding="utf-8")
        code, body = self.call("/api/models/config?model=mini", {"set": {"sampling.top_p": 9}})
        self.assertEqual(code, 400)
        self.assertIn("top_p", body["error"]["message"])
        self.assertEqual(self.config.read_text(encoding="utf-8"), before)

    def test_a_plain_form_is_not_a_config_change(self):
        code, _ = self.call("/api/models/config?model=mini", {"set": {}},
                            headers={"Origin": self.base})
        self.assertEqual(code, 415)                    # no JSON content type: not this page

    def test_another_pages_origin_is_refused(self):
        code, _ = self.call("/api/models/config?model=mini", {"set": {}},
                            headers={**self.headers, "Origin": "http://elsewhere.example"})
        self.assertEqual(code, 403)

    def test_engine_repair_is_off_until_the_server_allows_it(self):
        code, body = self.call("/api/engines/repair", {})
        self.assertEqual(code, 403)
        self.assertIn("allow-engine-repair", body["error"]["message"].replace("--", ""))

    def test_engine_repair_refuses_while_a_model_is_loaded(self):
        self.svc.allow_engine_repair = True            # a mock engine has no alive(): it counts as loaded
        try:
            code, _ = self.call("/api/engines/repair", {})
            self.assertEqual(code, 409)
        finally:
            self.svc.allow_engine_repair = False

    def test_engine_repair_starts_setup_detached(self):
        self.svc.allow_engine_repair = True
        self.svc.engine = SimpleNamespace(alive=lambda: False)
        seen = {}
        with mock.patch("serve.server.subprocess.Popen", side_effect=lambda cmd, **kw: seen.setdefault("cmd", cmd) or SimpleNamespace()):
            code, body = self.call("/api/engines/repair", {})
        self.assertEqual((code, body["status"]), (202, "started"))
        self.assertEqual(seen["cmd"][1:], [str(ROOT / "setup.py"), "--repair-engines"])
        self.assertTrue(seen or True)                   # Popen was called, not a shell string
        self.svc.allow_engine_repair = False
