# Community benchmark on NVIDIA GeForce RTX 4070 Ti SUPER

Measured on 2026-11-19 with `tools/strata_bench.py` (suite 1, 3 runs per test, medians with ranges). Speeds are the engine's own timings; first-token times are measured by the client over HTTP. Speed only: no correctness check was run.

## Hardware and software

- GPU and VRAM: NVIDIA GeForce RTX 4070 Ti SUPER, 16 GiB VRAM
- CPU: Intel(R) Core(TM) i9-14900KF (24 cores, 32 threads); installed RAM: 63.8 GiB; storage: not measured
- OS: Windows 11 (10.0.26200); GPU driver: 621.24; CUDA: not read
- AryaStrata: project 0.1.45, commit 128ec6aa; engine 0.1.62
- Background workloads and power limits: not recorded

## Model and configuration

- Model and quantization: qwen3.8-flash-next-iq3_xxs
- Context: 262144 tokens; parallel slots: 1
- Settings: the install's own configuration, unchanged; thinking off for the suite; temperature 0

```text
strata.exe --pack iq3_xxs --native Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf --ple-gguf Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00002-of-00002.gguf --expert-profile expert-profile.bin --expert-cache auto --prefill auto --spec 4 --mtp rt --kv int8 --max-context 262144 --kv-resident 32768 --conversation-cache-mib 4096 --vram-reserve-mib 2048 --vision --pcie-frac 0.20 --spec-min-p 0.70 --pool-workers 15 --adapt-every 1 --adapt-swaps 160 --adapt-decay 0.97 --draft dflash2 --draft-model Qwen3.8-Flash-Next.dflash2.pack --draft-cap 8
```

Environment of the config: `STRATA_ARENA_PIN_GIB=auto`

## Method

Run by `python tools/strata_bench.py --long` against the HTTP API of a AryaStrata server (started by the benchmark from the install configuration); model loading is not timed. One warm-up chat and a 1K prompt are discarded first. Every prompt starts with a unique tag, so the conversation cache cannot help the fresh-prompt tests.

- short chat: the three questions of `tools/ab_engine.py`, up to 100 new tokens, 3 runs
- 4K / 16K prompts: generated word lists sized by a calibration request, 24 new tokens, 3 fresh prompts each
- agent session: system prompt and four tools, then 5 turns that each add about 1500 words of a project file and continue from the model's own earlier answers (the way agent clients resend a conversation), 64 new tokens per turn, 3 sessions; the cache numbers come from the answer's usage (`cached_tokens`) and timings (`prompt_n`)
- concurrency (when run): N requests sent at the same moment, total tokens over the wall time of the burst, latency over all requests

## Results

| Configuration | Actual prompt tokens | Reused tokens | Generated tokens | Runs | Prompt tok/s median and range | Decode tok/s median and range | TTFT seconds median and range |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| short chat | 46 (43-51) | 0 | 100 (100-100) | 9 | not measured | 100.2 (84.8-124.5) | 0.38 (0.33-0.43) |
| 4K prompt, fresh | 4019 (4019-4019) | 0 (0-0) | 24 cap | 3 | 1949.7 (1935.4-1957.1) | not measured | 2.11 (2.08-2.11) |
| 16K prompt, fresh | 16058 (16058-16058) | 0 (0-0) | 24 cap | 3 | 3334.3 (3333.7-3380.3) | not measured | 4.84 (4.79-4.86) |
| 32K prompt, fresh | 32049 (32049-32049) | 0 (0-0) | 24 cap | 3 | 3447.2 (3441.6-3449.3) | not measured | 9.35 (9.34-9.37) |
| agent session, follow-up turns | 16186 (16180-16216) at the last turn | see below | up to 64 | 3 | see below | 97.5 (90.6-127.0) | 2.01 (1.64-2.06) |

Ranges are the lowest and highest of the runs; `Runs` counts requests that returned a token.

### Agent session (conversation cache)

Cache hit over the follow-up turns: 69.4 % (69.3-69.4); earlier-turn tokens read again per session: 5 (5-5) (earlier turns that the cache did not hold; the 15337 (15337-15338) new tokens of the files are read once); first turn (nothing cached) first token: 1.25 s (1.11-1.27).

| Turn (run 1) | Prompt tokens | Reused | Read | Prompt tok/s | First token (s) | Decode tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 609 | 0 | 609 | 558.8 | 1.115 | 64.6 |
| 1 | 4243 | 623 | 3620 | 1788.5 | 2.059 | 93.8 |
| 2 | 6459 | 4306 | 2153 | 1287.3 | 1.71 | 92.5 |
| 3 | 10058 | 6522 | 3536 | 1748.2 | 2.064 | 104.7 |
| 4 | 13063 | 10110 | 2953 | 1493.6 | 2.011 | 127.0 |
| 5 | 16180 | 13100 | 3080 | 1565.6 | 2.006 | 102.3 |

Per-request data: `results.json`. Engine log lines from the start: `engine-log-excerpt.txt` (when this run started the server).

## Correctness and limitations

Not measured: this is a speed suite. The conversation uses the model's own replies, so token counts differ a little between runs. Machine details come from the server, `nvidia-smi`/`rocm-smi` and the OS; background load and power limits are not recorded. Total time of the suite: 108 s.
