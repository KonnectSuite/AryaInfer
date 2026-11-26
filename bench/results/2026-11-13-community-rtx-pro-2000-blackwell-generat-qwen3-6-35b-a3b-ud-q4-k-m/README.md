# Community benchmark on NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU

Measured on 2026-11-13 with `tools/strata_bench.py` (suite 1, 3 runs per test, medians with ranges). Speeds are the engine's own timings; first-token times are measured by the client over HTTP. Speed only: no correctness check was run.

## Hardware and software

- GPU and VRAM: NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU, 8 GiB VRAM
- CPU: Intel(R) Core(TM) Ultra 7 265H (16 cores, 16 threads); installed RAM: 63.4 GiB; storage: not measured
- OS: Windows 11 (10.0.26300); GPU driver: 597.01; CUDA: 13.2
- AryaStrata: project 0.1.45, commit 4a37767c; engine 0.1.45
- Background workloads and power limits: not recorded

## Model and configuration

- Model and quantization: qwen3.6-35b-a3b-ud-q4_k_m
- Context: 204800 tokens; parallel slots: 1
- Settings: the install's own configuration, unchanged; thinking off for the suite; temperature 0

```text
strata-poly.exe --model Qwen3.6-35B-A3B-UD-Q4_K_M.gguf --max-context 204800 --expert-profile expert-profile.txt --conversation-cache-mib auto --tail-skip 0 --threads 10 --kv q8_0 --prompt-batch 2048 --vram-reserve-mib 512
```

## Method

Run by `python tools/strata_bench.py` against the HTTP API of a AryaStrata server (started by the benchmark from the install configuration); model loading is not timed. One warm-up chat and a 1K prompt are discarded first. Every prompt starts with a unique tag, so the conversation cache cannot help the fresh-prompt tests.

- short chat: the three questions of `tools/ab_engine.py`, up to 100 new tokens, 3 runs
- 4K / 16K prompts: generated word lists sized by a calibration request, 24 new tokens, 3 fresh prompts each
- agent session: system prompt and four tools, then 5 turns that each add about 1500 words of a project file and continue from the model's own earlier answers (the way agent clients resend a conversation), 64 new tokens per turn, 3 sessions; the cache numbers come from the answer's usage (`cached_tokens`) and timings (`prompt_n`)
- concurrency (when run): N requests sent at the same moment, total tokens over the wall time of the burst, latency over all requests

## Results

| Configuration | Actual prompt tokens | Reused tokens | Generated tokens | Runs | Prompt tok/s median and range | Decode tok/s median and range | TTFT seconds median and range |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| short chat | 46 (43-51) | 0 | 100 (100-100) | 9 | not measured | 63.6 (54.9-79.5) | 0.43 (0.39-0.48) |
| 4K prompt, fresh | 4019 (4019-4019) | 0 (0-0) | 24 cap | 3 | 575.6 (348.2-797.5) | not measured | 7.01 (5.07-11.58) |
| 16K prompt, fresh | 16058 (16058-16058) | 0 (0-0) | 24 cap | 3 | 1295.7 (218.7-1368.7) | not measured | 12.42 (11.77-73.46) |
| agent session, follow-up turns | 16154 (16136-16162) at the last turn | see below | up to 64 | 3 | see below | 16.9 (7.9-31.7) | 6.04 (3.66-11.26) |

Ranges are the lowest and highest of the runs; `Runs` counts requests that returned a token.

### Agent session (conversation cache)

Cache hit over the follow-up turns: 68.8 % (68.8-68.8); earlier-turn tokens read again per session: 266 (249-275) (earlier turns that the cache did not hold; the 15313 (15313-15314) new tokens of the files are read once); first turn (nothing cached) first token: 8.06 s (2.08-9.38).

| Turn (run 1) | Prompt tokens | Reused | Read | Prompt tok/s | First token (s) | Decode tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 609 | 0 | 609 | 296.0 | 2.083 | 34.8 |
| 1 | 4254 | 602 | 3652 | 1004.9 | 3.659 | 31.7 |
| 2 | 6453 | 4247 | 2206 | 509.2 | 4.378 | 9.1 |
| 3 | 10044 | 6446 | 3598 | 401.6 | 9.104 | 7.9 |
| 4 | 13036 | 10037 | 2999 | 271.4 | 11.26 | 12.2 |
| 5 | 16162 | 13029 | 3133 | 453.9 | 7.022 | 13.7 |

Per-request data: `results.json`. Engine log lines from the start: `engine-log-excerpt.txt` (when this run started the server).

## Correctness and limitations

Not measured: this is a speed suite. The conversation uses the model's own replies, so token counts differ a little between runs. Machine details come from the server, `nvidia-smi`/`rocm-smi` and the OS; background load and power limits are not recorded. Total time of the suite: 317 s.
