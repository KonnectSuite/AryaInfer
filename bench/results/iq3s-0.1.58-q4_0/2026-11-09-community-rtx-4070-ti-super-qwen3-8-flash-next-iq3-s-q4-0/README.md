# Community benchmark on NVIDIA GeForce RTX 4070 Ti SUPER

Measured on 2026-11-09 with `tools/strata_bench.py` (suite 1, 3 runs per test, medians with ranges). Speeds are the engine's own timings; first-token times are measured by the client over HTTP. Speed only: no correctness check was run.

## Hardware and software

- GPU and VRAM: NVIDIA GeForce RTX 4070 Ti SUPER, 16 GiB VRAM
- CPU: Intel(R) Core(TM) i9-14900KF (24 cores, 32 threads); installed RAM: 63.8 GiB; storage: not measured
- OS: Windows 11 (10.0.26200); GPU driver: 610.88; CUDA: not read
- AryaStrata: project 0.1.45, commit ab354b88; engine 0.1.58
- Background workloads and power limits: not recorded

## Model and configuration

- Model and quantization: qwen3.8-flash-next-iq3_s-q4_0
- Context: 262144 tokens; parallel slots: 1
- Settings: the install's own configuration, unchanged; thinking off for the suite; temperature 0

```text
strata.exe --pack iq3_s --native Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf --ple-gguf Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf --expert-profile expert-profile.bin --expert-cache auto --prefill auto --spec 4 --mtp rt --max-context 262144 --kv q4_0 --vision --vram-reserve-mib 700 --pcie-frac 0.20 --spec-min-p 0.50 --adapt-every 1 --adapt-swaps 80 --adapt-decay 0.97 --draft dflash2 --draft-model Qwen3.8-Flash-Next.dflash2.pack
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
| short chat | 46 (43-51) | 0 | 100 (100-100) | 9 | not measured | 74.7 (68.7-106.9) | 0.43 (0.39-0.51) |
| 4K prompt, fresh | 4019 (4019-4019) | 0 (0-0) | 24 cap | 3 | 1732.0 (1713.6-1737.8) | not measured | 2.36 (2.34-2.39) |
| 16K prompt, fresh | 16058 (16058-16058) | 0 (0-0) | 24 cap | 3 | 2746.8 (2724.6-2748.9) | not measured | 5.89 (5.88-5.93) |
| 32K prompt, fresh | 32049 (32049-32049) | 0 (0-0) | 24 cap | 3 | 2788.1 (2784.3-2789.0) | not measured | 11.55 (11.54-11.56) |
| agent session, follow-up turns | 16163 (16144-16180) at the last turn | see below | up to 64 | 3 | see below | 82.2 (66.6-97.8) | 2.34 (1.99-2.44) |

Ranges are the lowest and highest of the runs; `Runs` counts requests that returned a token.

### Agent session (conversation cache)

Cache hit over the follow-up turns: 69.2 % (69.2-69.3); earlier-turn tokens read again per session: 73 (4-74) (earlier turns that the cache did not hold; the 15320 (15320-15321) new tokens of the files are read once); first turn (nothing cached) first token: 1.22 s (1.19-1.25).

| Turn (run 1) | Prompt tokens | Reused | Read | Prompt tok/s | First token (s) | Decode tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 609 | 0 | 609 | 523.3 | 1.194 | 58.6 |
| 1 | 4253 | 634 | 3619 | 1542.1 | 2.398 | 73.7 |
| 2 | 6469 | 4317 | 2152 | 1083.4 | 2.036 | 80.0 |
| 3 | 10067 | 6462 | 3605 | 1539.6 | 2.394 | 71.9 |
| 4 | 13054 | 10116 | 2938 | 1230.8 | 2.435 | 92.3 |
| 5 | 16163 | 13084 | 3079 | 1351.4 | 2.339 | 73.6 |

Per-request data: `results.json`. Engine log lines from the start: `engine-log-excerpt.txt` (when this run started the server).

## Correctness and limitations

Not measured: this is a speed suite. The conversation uses the model's own replies, so token counts differ a little between runs. Machine details come from the server, `nvidia-smi`/`rocm-smi` and the OS; background load and power limits are not recorded. Total time of the suite: 129 s.
