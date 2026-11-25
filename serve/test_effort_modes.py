"""The thinking-effort surface: per-model levels, the instruction for templates that ignore the level, and off.

Run: python -m unittest serve.test_effort_modes -v
"""
import json
import unittest
from pathlib import Path

from serve import models as registry  # noqa: E402
from serve.frontend import (ChatTemplate, effort_levels, openai_to_messages, with_effort_instruction)  # noqa: E402


class Levels(unittest.TestCase):
    def test_a_template_that_reads_enable_thinking_offers_off(self):
        self.assertEqual(effort_levels("{% if enable_thinking is false %}x{% endif %}", True),
                         ["off", "low", "medium", "high"])

    def test_a_model_that_always_thinks_offers_no_off(self):
        # Flint's template has neither switch: it cannot stop thinking, so Off must not be offered.
        self.assertEqual(effort_levels("<|im_start|>{{ messages }}", True), ["low", "medium", "high"])

    def test_no_system_turn_means_no_levels(self):
        # A template that cannot render a system role cannot carry the instruction either.
        self.assertEqual(effort_levels("no switches at all", False), [])


class Instruction(unittest.TestCase):
    def test_prepended_to_the_existing_system_turn(self):
        messages = [{"role": "system", "content": "Be brief."},
                    {"role": "user", "content": "hi"}]
        out = with_effort_instruction(messages, "low")
        self.assertTrue(out[0]["content"].startswith("Reasoning effort is set to low."))
        self.assertTrue(out[0]["content"].endswith("Be brief."))
        self.assertEqual(out[1], messages[1])

    def test_a_system_turn_is_added_when_there_is_none(self):
        out = with_effort_instruction([{"role": "user", "content": "hi"}], "xhigh")
        self.assertEqual(out[0]["role"], "system")
        self.assertIn("xhigh", out[0]["content"])
        self.assertEqual(out[1], {"role": "user", "content": "hi"})

    def test_off_and_unknown_levels_add_nothing(self):
        messages = [{"role": "user", "content": "hi"}]
        self.assertIs(with_effort_instruction(messages, "none"), messages)
        self.assertEqual(with_effort_instruction(messages, "none"), messages)

    def test_list_content_keeps_its_parts(self):
        messages = [{"role": "system", "content": [{"type": "text", "text": "Rules."}]},
                    {"role": "user", "content": "hi"}]
        out = with_effort_instruction(messages, "medium")
        self.assertEqual(out[0]["content"][0]["type"], "text")
        self.assertIn("Reasoning effort is set to medium", out[0]["content"][0]["text"])


class Request(unittest.TestCase):
    def test_a_top_level_enable_thinking_false_is_off(self):
        _messages, _tools, kwargs = openai_to_messages(
            {"messages": [{"role": "user", "content": "hi"}], "enable_thinking": False})
        self.assertEqual(kwargs, {"enable_thinking": False})

    def test_the_level_survives_as_kwargs(self):
        _messages, _tools, kwargs = openai_to_messages(
            {"messages": [{"role": "user", "content": "hi"}], "reasoning_effort": "high"})
        self.assertEqual(kwargs, {"reasoning_effort": "xhigh"})

    def test_an_explicit_reasoning_effort_false_is_off(self):
        _messages, _tools, kwargs = openai_to_messages(
            {"messages": [{"role": "user", "content": "hi"}], "reasoning_effort": False})
        self.assertEqual(kwargs, {"enable_thinking": False})


class Templates(unittest.TestCase):
    """The two template families this host serves, through ChatTemplate's own detection."""

    def _template(self, path):
        return ChatTemplate(path)
    def test_qwen38_template_reads_the_level(self):
        template = self._template(r"C:\AI\Strata-data\packs\iq3_xxs\tokenizer\chat_template.jinja")
        self.assertTrue(template.supports_reasoning_effort)
        self.assertTrue(template.supports_enable_thinking)

    def test_qwen36_template_does_not_read_the_level(self):
        template = self._template(r"C:\AI\Strata-data\packs\qwen36s-ud-q4_k_xl\tokenizer\chat_template.jinja")
        self.assertFalse(template.supports_reasoning_effort)
        self.assertTrue(template.supports_enable_thinking)

    def test_flint_template_reads_neither(self):
        path = r"C:\AI\Strata-data\packs\flint-ud-q4_k_xl\tokenizer\chat_template.jinja"
        if not Path(path).is_file():
            self.skipTest("Flint is not installed on this machine")
        template = self._template(path)
        self.assertFalse(template.supports_reasoning_effort)
        self.assertFalse(template.supports_enable_thinking)


class Registry(unittest.TestCase):
    """What /api/models and /v1/models publish, per installed model, from the config's own tokenizer."""

    ROOT = Path(__file__).resolve().parent.parent  # the repo this test lives in

    def _efforts(self, model_id):
        for path in sorted(self.ROOT.glob("strata-*.json")):
            cfg = json.loads(path.read_text(encoding="utf-8-sig"))
            if cfg.get("model_name") == model_id:
                entry = registry.describe(path)
                return (entry or {}).get("efforts")
        return None

    def test_every_installed_model_publishes_its_levels(self):
        configs = sorted(self.ROOT.glob("strata-*.json"))
        if not configs:
            self.skipTest("no installed model configs on this machine")
        for path in configs:
            cfg = json.loads(path.read_text(encoding="utf-8-sig"))
            model_id = cfg.get("model_name") or path.stem
            efforts = self._efforts(model_id)
            self.assertTrue(efforts, f"{model_id} publishes no levels")
            graded = efforts[1:] if efforts[0] == "off" else efforts
            self.assertEqual(graded, ["low", "medium", "high"], model_id)
            self.assertIn(efforts[0], ("off", "low"), model_id)

    def test_the_models_that_cannot_stop_thinking_offer_no_off(self):
        flint = self._efforts("flint-40b-a2.5b-ud-q4_k_xl")
        if flint is None:
            self.skipTest("Flint is not installed here")
        self.assertNotIn("off", flint)
        self.assertEqual(self._efforts("qwen3.8-flash-next-iq3_xxs"), ["off", "low", "medium", "high"])


if __name__ == "__main__":
    unittest.main()
