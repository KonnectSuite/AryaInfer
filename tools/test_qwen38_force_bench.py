r"""Checks for tools/qwen38_force_bench.py that need no model or GPU.

Run from the repo root:
    $env:PYTHONPATH = (Get-Location).Path
    .\.venv\Scripts\python.exe tools\test_qwen38_force_bench.py
"""
import unittest

import qwen38_force_bench as bench


class FakeTokenizer:
    def encode(self, text):
        return [ord(c) for c in text]


class PromptTests(unittest.TestCase):
    def test_explicit_prompt_is_truncated(self):
        self.assertEqual(bench.prompt_ids(FakeTokenizer(), 4, "abcdef"), [97, 98, 99, 100])

    def test_tiled_prompt_fills_the_request(self):
        ids = bench.prompt_ids(FakeTokenizer(), 600)
        self.assertTrue(ids)
        self.assertLessEqual(len(ids), 600)

    def test_tiled_prompt_keeps_the_task_tail(self):
        ids = bench.prompt_ids(FakeTokenizer(), 600)
        tail = bench.TAIL.encode()[-20:]
        self.assertEqual(bytes(ids[-20:]), tail)


if __name__ == "__main__":
    unittest.main()
