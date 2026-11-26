# Flash-Next harness tuning: sampler, thinking ladder, vision floor

Measured 2026-11-25 on this host (i9-14900KF, RTX 4070 Ti SUPER 16 GB, 64 GB RAM, Windows 11 26200) against the
live server (`serve/server.py` default path) with `strata.exe` 0.1.67 from
`C:\AI\Strata-data\engines\strata-0.1.67`, serving `qwen3.8-flash-next-gyro-m` (Gyro-M TQ2_0, 262,144 context).
Goal: make the two Flash-Next run configs (`strata-iq3_s.json`, `strata-gyro-m.json`) the right settings for coding
harnesses (Cursor, AryaCode/DSH, Claude Code) and everyday writing, and prove every thinking knob actually
reaches the model.

Tools: `tools/harness_sampling_probe.py` (fixture suites below; `--sets` sweeps sampling, `--efforts` sweeps
thinking level; checks are structural, canned pairs validated by `tools/test_harness_sampling_probe.py`),
`tools/thinking_mode_probe.py`, and `tools/arya_agent_bench.py` (agent cases run through a sandboxed executor).
Raw rows: `harness-gyro-2p.json`, `harness-gyro-think.json`, `think-gyro-m.json` in this folder.

Reproduce (server running, one model loaded):

```
python tools\harness_sampling_probe.py --model qwen3.8-flash-next-gyro-m ^
    --suites artifact,writing,agent --sets config,precise,coding,balanced --passes 2 ^
    --timeout 420 --out harness-gyro-2p.json
python tools\harness_sampling_probe.py --model qwen3.8-flash-next-gyro-m ^
    --suites artifact,writing,agent --sets config --efforts off,low,medium,high ^
    --passes 1 --timeout 420 --out harness-gyro-think.json
```

## 1. Sampler A/B (thinking off on every arm, 2 passes, 10 fixtures)

Web page + memory game (8,192-token caps), GUI converter, email, quote, meeting minutes, changelog (1,024-token
caps), and the three tool-call agent cases. "T" below means the answer hit its token cap, not that it was wrong.

| Set | Passes | Failures |
| --- | ---: | --- |
| served config (0.7 / 0.9 / 20) | 20/20 | none |
| precise (0.3 / 0.9 / 20) | 19/20 | web_page T (1 of 2) |
| coding (0.6 / 0.95 / 20) | 18/20 | web_page T (2 of 2) |
| balanced (0.7 / 0.95 / 40, min_p 0.02, rep 1.02) | 18/20 | web_page T (2 of 2) |

Every arm produced correct structure on all 9 non-web fixtures; the only differentiator was how fast the web-page
answer grew past the cap (22.7k chars at config, 24.2k at coding). The served block wins outright, so it stays.

## 2. Thinking levels reach the model (config sampler, 1 pass, 10 fixtures)

| Level | Passes | web_page | email (1,024 cap) | agent cases |
| --- | ---: | --- | --- | --- |
| off | 10/10 | 132.0 s, 22,942 ch, rep-4 0.152 | 5.0 s P | 3/3 P, 4-6 turns |
| low | 10/10 | 49.5 s, 9,825 ch, rep-4 0.078 | 12.3 s P | 3/3 P, 4 turns |
| medium | 9/10 | 42.8 s, 6,827 ch, rep-4 0.050 | **T** (thinking ate the cap) | 3/3 P |
| high | 7/10 | **T** at 151.3 s | 9.2 s P | 3/3 P |

Low is the fastest arm that passed everything: it answers the same correct structures in a third of the time with
half the boilerplate, because thinking shortens and tightens the artifact. Medium and high think past the short
caps harnesses send for small requests (`email` is a 1,024-token request) and come back truncated. The single
question ladder (`think-gyro-m.json`) agrees: 1,030 / 1,689 / 3,085 thinking characters at low / medium / high on
the same arithmetic-word-problem, all four levels correct, prompt-token ids differ per level (the instruction
sentences are in the prompt), off = 0.

## 3. What shipped

Both configs (`strata-gyro-m.json`, `strata-iq3_s.json`, copies with `$DATA`/`$INSTALL` in
[docs/host-tuning](../../../docs/host-tuning/README.md)):

- `reasoning_effort`: **low** (was high). A harness that sends its own `reasoning_effort` or Anthropic
  `thinking.budget_tokens` still overrides this per request.
- `reasoning_budget_by_effort`: `{off: 0, low: 4800, medium: 9600, high: 12000}` - the measured ladder from
  `strata-iq3_xxs.json` (IQ3_S had an unrecorded 2048/8192/16384, now aligned). With `reasoning_budget_tokens`
  9600 as the fallback these are ceilings; the model's own sentence decides the length (700-2,600 used here).
- `vision.min_tokens: 1024` on both - the floor [docs/host-tuning/README.md](../../../docs/host-tuning/README.md)
  already requires; without it a small picture encodes to ~320 tokens and answers drift.
- Sampling untouched: the served 0.7 / 0.9 / 20 block was the measured winner.

## Caveats

- The ladder and levels were measured while Gyro-M was loaded; IQ3_S (same architecture, same template) carries
  the identical settings but was not reloaded today - the machine holds one 50 GB expert set at a time. Confirm
  on its next load.
- The fixture checks are structural (does the HTML parse, do the totals match, did the agent call the right
  tools), not taste. They gate correctness, not style.
- One pass per thinking level; the medium email truncation was seen once out of two sampler passes at that cap,
  and `reasoning_loop_recovery: recover` stayed on throughout.
