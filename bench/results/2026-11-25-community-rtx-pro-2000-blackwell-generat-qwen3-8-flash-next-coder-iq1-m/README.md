# Community benchmark on NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU

Measured on 2026-11-25 with `tools/strata_bench.py` (suite 1, 3 runs per test, medians with ranges). Speeds are the engine's own timings; first-token times are measured by the client over HTTP. Speed only: no correctness check was run.

## Hardware and software

- GPU and VRAM: NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU, 8 GiB VRAM
- CPU: Intel(R) Core(TM) Ultra 7 265H (16 cores, 16 threads); installed RAM: 63.4 GiB; storage: not measured
- OS: Windows 11 (10.0.26300); GPU driver: 597.01; CUDA: 13.2
- AryaStrata: project 0.1.45, commit 7aae1810; engine 0.1.63
- Background workloads and power limits: not recorded

## Model and configuration

- Model and quantization: qwen3.8-flash-next-coder-iq1_m
- Context: 172032 tokens; parallel slots: 1
- Settings: the install's own configuration, unchanged; thinking off for the suite; temperature 0

```text
strata-0.1.63.exe --pack coder-iq1_m --native Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf --ple-gguf Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf --expert-profile expert-profile-coder.bin --expert-cache auto --prefill auto --spec 4 --spec-min-p 0.5 --mtp rt --conversation-cache-mib 4096 --max-context 172032 --kv k8v4 --kv-resident 32768 --vision --vram-reserve-mib 300 --pool-workers 10
```

Environment of the config: `STRATA_MTP_KEEP=1`

## Method

Run by `python tools/strata_bench.py` against the HTTP API of a AryaStrata server (started by the benchmark from the install configuration); model loading is not timed. One warm-up chat and a 1K prompt are discarded first. Every prompt starts with a unique tag, so the conversation cache cannot help the fresh-prompt tests.

- short chat: the three questions of `tools/ab_engine.py`, up to 100 new tokens, 3 runs
- 4K / 16K prompts: generated word lists sized by a calibration request, 24 new tokens, 3 fresh prompts each
- agent session: system prompt and four tools, then 5 turns that each add about 1500 words of a project file and continue from the model's own earlier answers (the way agent clients resend a conversation), 64 new tokens per turn, 3 sessions; the cache numbers come from the answer's usage (`cached_tokens`) and timings (`prompt_n`)
- concurrency (when run): N requests sent at the same moment, total tokens over the wall time of the burst, latency over all requests

## Results

| Configuration | Actual prompt tokens | Reused tokens | Generated tokens | Runs | Prompt tok/s median and range | Decode tok/s median and range | TTFT seconds median and range |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| short chat | 46 (43-51) | 0 | 100 (100-100) | 9 | not measured | 28.3 (23.2-32.1) | 0.76 (0.64-0.85) |
| 4K prompt, fresh | 4019 (4019-4019) | 0 (0-0) | 24 cap | 3 | 451.8 (446.5-465.8) | not measured | 8.95 (8.68-9.05) |
| 16K prompt, fresh | 16058 (16058-16058) | 0 (0-0) | 24 cap | 3 | 437.4 (421.1-442.9) | not measured | 36.80 (36.33-38.23) |
| agent session, follow-up turns | 16533 (16529-16570) at the last turn | see below | up to 64 | 3 | see below | 29.6 (14.7-37.3) | 11.70 (7.04-14.03) |

Ranges are the lowest and highest of the runs; `Runs` counts requests that returned a token.

### Agent session (conversation cache)

Cache hit over the follow-up turns: 69.4 % (69.4-69.4); earlier-turn tokens read again per session: 5 (5-5) (earlier turns that the cache did not hold; the 15672 (15671-15673) new tokens of the files are read once); first turn (nothing cached) first token: 2.90 s (2.86-2.95).

| Turn (run 1) | Prompt tokens | Reused | Read | Prompt tok/s | First token (s) | Decode tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 609 | 0 | 609 | 215.1 | 2.896 | 21.4 |
| 1 | 4448 | 634 | 3814 | 288.9 | 13.266 | 29.9 |
| 2 | 6664 | 4511 | 2153 | 268.2 | 8.1 | 25.4 |
| 3 | 10263 | 6727 | 3536 | 283.0 | 12.564 | 22.0 |
| 4 | 13247 | 10294 | 2953 | 270.3 | 11.006 | 30.4 |
| 5 | 16529 | 13309 | 3220 | 256.6 | 12.614 | 26.1 |

Per-request data: `results.json`. Engine log lines from the start: `engine-log-excerpt.txt` (when this run started the server).

## Correctness and limitations

Not measured: this is a speed suite. The conversation uses the model's own replies, so token counts differ a little between runs. Machine details come from the server, `nvidia-smi`/`rocm-smi` and the OS; background load and power limits are not recorded. Total time of the suite: 404 s.
