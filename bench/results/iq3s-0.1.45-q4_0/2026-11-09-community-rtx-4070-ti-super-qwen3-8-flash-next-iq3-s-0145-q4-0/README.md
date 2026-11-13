# Community benchmark on NVIDIA GeForce RTX 4070 Ti SUPER

Measured on 2026-11-09 with `tools/strata_bench.py` (suite 1, 3 runs per test, medians with ranges). Speeds are the engine's own timings; first-token times are measured by the client over HTTP. Speed only: no correctness check was run.

## Hardware and software

- GPU and VRAM: NVIDIA GeForce RTX 4070 Ti SUPER, 16 GiB VRAM
- CPU: Intel(R) Core(TM) i9-14900KF (24 cores, 32 threads); installed RAM: 63.8 GiB; storage: not measured
- OS: Windows 11 (10.0.26200); GPU driver: 610.88; CUDA: not read
- AryaStrata: project 0.1.45, commit ab354b88; engine 0.1.45
- Background workloads and power limits: not recorded

## Model and configuration

- Model and quantization: qwen3.8-flash-next-iq3_s-0145-q4_0
- Context: 262144 tokens; parallel slots: 1
- Settings: the install's own configuration, unchanged; thinking off for the suite; temperature 0

```text
strata.exe --pack iq3_s --native Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf --ple-gguf Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf --expert-profile expert-profile.bin --expert-cache auto --prefill auto --spec 4 --mtp rt --max-context 262144 --kv q4_0 --vision --vram-reserve-mib 700 --pcie-frac 0.20 --spec-min-p 0.50 --adapt-every 1 --adapt-swaps 80 --adapt-decay 0.97
```

## Method

Run by `python tools/strata_bench.py --long` against the HTTP API of a AryaStrata server (started by the benchmark from the install configuration); model loading is not timed. One warm-up chat and a 1K prompt are discarded first. Every prompt starts with a unique tag, so the conversation cache cannot help the fresh-prompt tests.

- short chat: the three questions of `tools/ab_engine.py`, up to 100 new tokens, 3 runs
- 4K / 16K prompts: generated word lists sized by a calibration request, 24 new tokens, 3 fresh prompts each
- agent session: system prompt and four tools, then 5 turns that each add about 1500 words of a project file and continue from the model's own earlier answers (the way agent clients resend a conversation), 64 new tokens per turn, 3 sessions; the cache numbers come from the answer's usage (`cached_tokens`) and timings (`prompt_n`)
- concurrency (when run): N requests sent at the same moment, total tokens over the wall time of the burst, latency over all requests

## Results

| Configuration | Actual prompt tokens | Reused tokens | Generated tokens | Runs | Prompt tok/s median and range | Decode tok/s median and range | TTFT seconds median and range |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| short chat | 46 (43-51) | 0 | 100 (100-100) | 9 | not measured | 76.7 (74.5-91.1) | 0.44 (0.38-0.48) |
| 4K prompt, fresh | 4019 (4019-4019) | 0 (0-0) | 24 cap | 3 | 1771.5 (1764.4-1774.2) | not measured | 2.30 (2.29-2.31) |
| 16K prompt, fresh | 16058 (16058-16058) | 0 (0-0) | 24 cap | 3 | 2752.0 (2746.6-2752.2) | not measured | 5.89 (5.88-5.89) |
| 32K prompt, fresh | 32049 (32049-32049) | 0 (0-0) | 24 cap | 3 | 2791.8 (2775.7-2796.1) | not measured | 11.55 (11.52-11.60) |
| agent session, follow-up turns | 16145 (16134-16188) at the last turn | see below | up to 64 | 3 | see below | 82.4 (68.2-103.3) | 2.27 (2.21-2.33) |

Ranges are the lowest and highest of the runs; `Runs` counts requests that returned a token.

### Agent session (conversation cache)

Cache hit over the follow-up turns: 69.2 % (69.2-69.3); earlier-turn tokens read again per session: 74 (4-74) (earlier turns that the cache did not hold; the 15318 (15318-15318) new tokens of the files are read once); first turn (nothing cached) first token: 1.21 s (1.17-1.23).

| Turn (run 1) | Prompt tokens | Reused | Read | Prompt tok/s | First token (s) | Decode tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 609 | 0 | 609 | 543.2 | 1.167 | 58.6 |
| 1 | 4240 | 623 | 3617 | 1571.6 | 2.332 | 68.2 |
| 2 | 6456 | 4303 | 2153 | 984.0 | 2.24 | 81.3 |
| 3 | 10054 | 6449 | 3605 | 1574.2 | 2.322 | 92.4 |
| 4 | 13031 | 10093 | 2938 | 1307.9 | 2.279 | 87.4 |
| 5 | 16145 | 13066 | 3079 | 1387.1 | 2.271 | 103.3 |

Per-request data: `results.json`. Engine log lines from the start: `engine-log-excerpt.txt` (when this run started the server).

## Correctness and limitations

Not measured: this is a speed suite. The conversation uses the model's own replies, so token counts differ a little between runs. Machine details come from the server, `nvidia-smi`/`rocm-smi` and the OS; background load and power limits are not recorded. Total time of the suite: 128 s.
