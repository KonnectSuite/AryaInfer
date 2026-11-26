# Community benchmark on NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU

Measured on 2026-11-26 with `tools/strata_bench.py` (suite 1, 3 runs per test, medians with ranges). Speeds are the engine's own timings; first-token times are measured by the client over HTTP. Speed only: no correctness check was run.

## Hardware and software

- GPU and VRAM: NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU, 8 GiB VRAM
- CPU: Intel(R) Core(TM) Ultra 7 265H (16 cores, 16 threads); installed RAM: 63.4 GiB; storage: not measured
- OS: Windows 11 (10.0.26300); GPU driver: 597.01; CUDA: 13.2
- AryaStrata: project 0.1.45, commit 91a8f068; engine 0.5.7
- Background workloads and power limits: not recorded

## Model and configuration

- Model and quantization: basalt-qwen38-ud-iq1_s
- Context: 131072 tokens; parallel slots: 1
- Settings: the install's own configuration, unchanged; thinking off for the suite; temperature 0

```text
basalt.exe --model Qwen3.8-FN-UD-IQ1_S.basalt --gpu 0 --max-context 131072 --kv q4_0 --resident-experts --suffix-draft 3 --vram-reserve-mib 320 --ram-reserve-mib 4096
```

## Method

Run by `python tools/strata_bench.py` against the HTTP API of a AryaStrata server (already running); model loading is not timed. One warm-up chat and a 1K prompt are discarded first. Every prompt starts with a unique tag, so the conversation cache cannot help the fresh-prompt tests.

- short chat: the three questions of `tools/ab_engine.py`, up to 100 new tokens, 3 runs
- 4K / 16K prompts: generated word lists sized by a calibration request, 24 new tokens, 3 fresh prompts each
- agent session: system prompt and four tools, then 5 turns that each add about 1500 words of a project file and continue from the model's own earlier answers (the way agent clients resend a conversation), 64 new tokens per turn, 3 sessions; the cache numbers come from the answer's usage (`cached_tokens`) and timings (`prompt_n`)
- concurrency (when run): N requests sent at the same moment, total tokens over the wall time of the burst, latency over all requests

## Results

| Configuration | Actual prompt tokens | Reused tokens | Generated tokens | Runs | Prompt tok/s median and range | Decode tok/s median and range | TTFT seconds median and range |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| short chat | 46 (43-51) | 0 | 100 (100-100) | 9 | not measured | 55.9 (52.3-69.2) | 0.51 (0.45-0.55) |
| 4K prompt, fresh | 4019 (4019-4019) | 0 (0-0) | 24 cap | 3 | 1218.2 (1213.4-1219.1) | not measured | 3.37 (3.37-3.40) |
| 16K prompt, fresh | 16058 (16058-16058) | 0 (0-0) | 24 cap | 3 | 1211.3 (1210.3-1211.7) | not measured | 13.36 (13.33-13.37) |
| agent session, follow-up turns | 16515 (16474-16516) at the last turn | see below | up to 64 | 3 | see below | 45.5 (31.8-55.1) | 3.80 (2.32-4.23) |

Ranges are the lowest and highest of the runs; `Runs` counts requests that returned a token.

### Agent session (conversation cache)

Cache hit over the follow-up turns: 69.3 % (69.3-69.3); earlier-turn tokens read again per session: 5 (5-5) (earlier turns that the cache did not hold; the 15671 (15670-15671) new tokens of the files are read once); first turn (nothing cached) first token: 1.22 s (1.21-1.24).

| Turn (run 1) | Prompt tokens | Reused | Read | Prompt tok/s | First token (s) | Decode tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 609 | 0 | 609 | 542.6 | 1.219 | 36.0 |
| 1 | 4434 | 620 | 3814 | 922.0 | 4.234 | 45.1 |
| 2 | 6650 | 4497 | 2153 | 902.2 | 2.47 | 48.8 |
| 3 | 10249 | 6713 | 3536 | 889.3 | 4.077 | 42.4 |
| 4 | 13250 | 10297 | 2953 | 839.9 | 3.603 | 47.6 |
| 5 | 16515 | 13295 | 3220 | 866.8 | 3.802 | 42.6 |

Per-request data: `results.json`. Engine log lines from the load and two requests: `engine-log-excerpt.txt` (copied by hand from the server's own log, `strata-basalt-qwen38-ud-iq1_s.log`).

## The same prompts against Basalt's own server

This engine is Basalt's, and Basalt ships a server of its own, so the question this
record answers is what managing it through `serve/server.py` costs. Both servers
were driven by the same binary with the same values (`--max-context 131072 --kv
q4_0 --resident-experts --suffix-draft 3 --vram-reserve-mib 320 --ram-reserve-mib
4096`) and the same scratch client, which sent a short, a 4.2K and a 16.7K prompt
twice to each with a unique tail per run so nothing was cached. The client counted
prompt tokens itself with `tools/strata_tokenizer.py` against the same tokenizer,
because this server cannot report `usage` on a streamed answer. Measured on
2026-11-26, project commit `91a8f068`.

| Server | 4K prompt tok/s | 16K prompt tok/s | 16K first token | Decode tok/s |
| --- | --- | --- | --- | --- |
| Basalt's own (`serve/server.py` in the basalt checkout) | 1,071.4 / 1,059.0 | 1,066.5 / 1,059.1 | 15.69 / 15.80 s | 47.4-66.9 |
| This server (`serve/server.py` here) | 1,058.7 / 1,058.7 | 1,076.1 / 1,063.3 | 15.55 / 15.73 s | 50.8-66.9 |

The gap between the two servers is smaller than the gap between two runs on the
same server, in every column. That is the measurement being reported: no cost
beyond run-to-run noise, not "equal to three decimals".

`tools/strata_bench.py` was not pointed at Basalt's own server because it requires
`/health` to answer `service: strata`, and that server answers `service: basalt` -
a guard worth keeping rather than defeating.

## Correctness and limitations

Not measured: this is a speed suite. The conversation uses the model's own replies, so token counts differ a little between runs. Machine details come from the server, `nvidia-smi`/`rocm-smi` and the OS; background load and power limits are not recorded. Total time of the suite: 150 s.
