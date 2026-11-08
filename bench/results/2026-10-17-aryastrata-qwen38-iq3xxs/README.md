# Qwen3.8 Flash Next IQ3_XXS on the AryaStrata host

Measured October 17, 2026 (America/New_York). AryaStrata is a fork of [PolyStrata](https://github.com/simplexai-labs/PolyStrata), a fork of [Niko1221â€™s original Strata](https://github.com/Niko1221/Strata). These are measurements on our own host, using upstream release engine 0.1.45; no custom engine build or engine-code speedup is claimed.

## Host and model

- Intel Core i9-14900KF, 24 physical cores / 32 logical processors; AVX2, no AVX-512.
- NVIDIA GeForce RTX 4070 Ti SUPER, 16,376 MiB VRAM; PCIe 4.0 x16; driver 610.88.
- 63.82 GiB usable system memory (2 × 32 GiB Team Group UD5-6000 modules); ASUS PRIME Z790-V WIFI motherboard; Windows 11 Home 10.0.26200; WD Blue SN580 2 TB SSD.
- Qwen3.8-Flash-Next GSQ-RCO IQ3_XXS: existing two GGUF shards reused, 47,039,860,096 and 28,800,138,432 bytes. Existing native pack and MTP reused. Exact hashes and software identities are in `provenance.json`.
- Native Windows CUDA engine 0.1.45, CUDA runtime 13.0, sm_89. Display remains active; ordinary desktop and development-app processes remained running. No clock locking, overclocking or driver changes were applied.

## Configuration selected for this host

```text
--max-context 262144 --kv int8 --kv-resident 32768
--vram-reserve-mib 1792 --pool-workers 15
--pcie-frac 0.20 --spec 4 --spec-min-p 0.70
--adapt-every 1 --adapt-swaps 80 --adapt-decay 0.97
```

The launch requests MTP `--spec 4`; the default suffix drafter can extend lookup windows to 6, as recorded in the engine metadata. Vision is off. The server listens only on `127.0.0.1:8080`; `fit_max_tokens` is enabled. These are per-install settings, not changes to defaults for other hardware. The context ceiling restores the old installationâ€™s 262,144-token ceiling. A ceiling is not a claim that every task succeeds at that length.

## Same-context API comparison

Both runs use the same release binary, model, 262K ceiling, int8 KV, 32K resident KV, 1,792 MiB VRAM reserve and 15 workers. The baseline uses the new installationâ€™s automatic/default PCIe, draft-floor and expert-cache settings; the tuned run pins the settings above. Each starts a fresh engine, warms it, then runs the same benchmark suite. The full phases ran sequentially (baseline, then tuned), not in alternating order.

Values are medians with observed ranges and sample counts. Engine timings measure prompt/decode speeds; first-token and full-response latency are client HTTP timings. Short chat is a mixed three-question workload, including one coding prompt. Agent-style speed sessions summarize repository files with four tool schemas present; they do not execute edits. Correctness is tested separately below.

| Metric | New-install baseline, 262K ceiling | Tuned, 262K ceiling |
| --- | ---: | ---: |
| Short-chat generation, tokens/s | 76.4 (59.8â€“89.4; n=9) | 86.1 (70.0â€“105.0; n=9) |
| Short-chat first token, s | 0.447 (0.375â€“0.892; n=9) | 0.368 (0.321â€“0.771; n=9) |
| Fresh 4K prompt, tokens/s | 2058.9 (1908.1â€“2068.8; n=3) | 2037.7 (1873.9â€“2075.3; n=3) |
| Fresh 16K prompt, tokens/s | 2879.2 (2789.2â€“2951.2; n=3) | 2983.3 (2887.6â€“2983.8; n=3) |
| Fresh 32K prompt, tokens/s | 2933.7 (2898.9â€“2947.4; n=3) | 2915.0 (2913.3â€“2941.4; n=3) |
| Fresh 32K first token, s | 10.961 (10.914â€“11.093; n=3) | 11.032 (10.931â€“11.035; n=3) |
| Agent-style generation, tokens/s | 86.8 (52.1â€“110.7; n=15) | 95.6 (58.1â€“112.6; n=15) |
| Agent-style follow-up first token, s | 2.105 (1.893â€“2.278; n=15) | 2.122 (1.975â€“2.226; n=15) |
| Agent-style cache reuse, % | 66.91 (66.78â€“66.98; n=3) | 66.80 (66.80â€“67.01; n=3) |
| Extra old tokens re-read / session | 73.0 (4.0â€“74.0; n=3) | 71.0 (4.0â€“72.0; n=3) |
| Two queued clients, total tokens/s | 57.38 (54.71â€“62.07; n=3) | 55.61 (53.36â€“61.29; n=3) |
| Two queued clients, p95 response latency, s | 4.624 | 4.749 |

The observed short-chat median changed by **+12.7%**. Run ranges overlap: this is a workload-specific observation, not a universal speed guarantee. Prompt speeds and agent latency must be assessed separately; a faster short answer does not establish faster repository work. The engine still serves one request at a time: the two-client test measures queuing, not batch-parallel decoding.

The earlier 32K-ceiling smoke baseline measured 80.4 tokens/s for short chat. It uses a different ceiling and a 1,500 MiB reserve, so it is a reference, not the controlled tuning comparator.
Failed suite requests: baseline 0; tuned 0. Fresh prompt inputs were about 4,019 / 16,058 / 32,049 actual tokens; the raw records carry exact counts, reuse and output lengths. Answers were capped at 100 tokens for chat and 24 for prompt tests. Each agent-style session has six turns, up to 64 answer tokens per turn. Three sessions were run per configuration.

## Calibration evidence

The built-in calibration ran before the API comparison. It sweeps seven PCIe shares and three draft confidence floors for three rounds, then interleaves the candidate with engine defaults for confirmation. Worker/cache stages restart the engine for each candidate; their two samples are medians over three short prompts. The cache stage permits answers up to 512 tokens; early stopping and different generated text can affect its rates. This is decode calibration, not a correctness evaluation.

| Candidate | Median tokens/s | Range |
| --- | ---: | ---: |
| PCIe: 0.0 | 78.2 | 70.8â€“89.9 (n=3) |
| PCIe: 0.2 | 87.3 | 81.2â€“91.7 (n=3) |
| PCIe: 0.35 | 73.1 | 66.6â€“80.2 (n=3) |
| PCIe: 0.55 | 63.1 | 59.4â€“66.5 (n=3) |
| PCIe: 0.75 | 55.1 | 50.0â€“57.1 (n=3) |
| PCIe: 0.9 | 51.1 | 47.9â€“51.2 (n=3) |
| PCIe: 1.0 | 42.3 | 40.0â€“42.8 (n=3) |
| Draft floor: 0.3 | 78.7 | 63.2â€“83.8 (n=3) |
| Draft floor: 0.5 | 75.7 | 75.1â€“77.7 (n=3) |
| Draft floor: 0.7 | 82.5 | 80.4â€“98.6 (n=3) |
| Confirmation PCIe/floor: 0.55/0.5 | 58.6 | 58.3â€“66.5 (n=3) |
| Confirmation PCIe/floor: 0.2/0.7 | 90.6 | 86.1â€“97.1 (n=3) |
| Workers: 23 | 82.5 | 77.5â€“87.6 (n=2) |
| Workers: 15 | 91.2 | 89.9â€“92.4 (n=2) |
| Workers: 12 | 85.9 | 81.2â€“90.7 (n=2) |
| Workers: 6 | 82.1 | 81.0â€“83.3 (n=2) |
| Workers: 7 | 89.4 | 89.1â€“89.6 (n=2) |
| Cache every/swaps/decay: default | 95.9 | 89.8â€“102.0 (n=2) |
| Cache every/swaps/decay: 1/80/0.97 | 103.9 | 103.6â€“104.2 (n=2) |
| Cache every/swaps/decay: 1/160/0.97 | 96.1 | 95.3â€“96.9 (n=2) |

The old Strata configuration already pinned PCIe 0.20, draft floor 0.70 and 15 workers, with 160 cache swaps. The new calibration favored 80 swaps. This report does **not** compare the old engine binary with the new engine; neither the API baseline nor the calibration-default comparison should be presented as that claim. The old vision-enabled configuration was not benchmarked here.

## Coding-agent correctness

Three small Python bug-fix fixtures cover merging sorted lists, chunking with invalid-size checks, and parsing key/value lines. A session must read the fixture through a tool, write a fix through a tool, run its regression checks and leave passing final code. The controller supports repair after a failed test. Edits are bounded in-memory fixtures; generated functions run with restricted builtins and a five-second test-process timeout. These are not arbitrary repository changes or a SWE-bench score. Only the tuned configuration was used for these correctness checks; they are not a blind quality comparison with the baseline.

| Reasoning request | Completed read/edit/test sessions | Median session seconds |
| --- | ---: | ---: |
| none | 9/9 | 4.74 |
| low | 9/9 | 6.49 |

Each row is three fixtures Ã— three runs. These few tests cannot establish general coding quality. Use the raw traces to inspect failed or repaired attempts; reasoning settings are choices per task, not interchangeable quality guarantees. The existing development-profile reasoning preference was preserved.

## AryaAI development DSH transport

The development runtimeâ€™s actual `dsh-llm-pi-ai` adapter (0.2.0-rc.2) and `BlockAssembler` ran 3 streaming tool-call/tool-result-replay trials: **3/3 passed**. The tool result contains a known build label which the final answer must reproduce. The probe uses the same 262K context, 8,192-token output capability, gateway output-budget mode and text-only metadata as the updated profile, with reasoning off. It uses a public placeholder against loopback and reads no account credentials.
The active development desktop profile still selects provider `strata`, model `qwen3.8-flash-next-iq3_xxs`, endpoint `http://127.0.0.1:8080/v1`. Its label and capabilities were corrected, with a local backup. This is an adapter/replay test, **not** a fully exercised native desktop session, compaction, approval, recovery or large-repository workflow. The authenticated desktop API was not used.

## Long-context recall

The configured ceiling is 262,144 tokens. The ladder sizes repository-code excerpts with the real local tokenizer, hides three random deployment codes near 10%, 50% and 90% of the input, and requires all three in the answer. A changing early nonce prevents useful cross-trial prefix-cache reuse; actual cached/read counts remain in the raw records. Source corpus hashes and prompt hashes are saved. Each target runs three times, greedy, thinking off, up to 128 answer tokens.

| Target input size | Actual server prompt tokens | All three facts found | Median prompt tokens/s | Median first token, s |
| --- | --- | ---: | ---: | ---: |
| 32,768 | 32,486â€“32,486 | 3/3 | 2834.1 | 11.55 |
| 65,536 | 65,345â€“65,345 | 3/3 | 2861.2 | 22.91 |
| 131,072 | 131,031â€“131,031 | 3/3 | 2752.4 | 47.75 |
| 258,048 | 258,300â€“258,300 | 3/3 | 2550.6 | 101.56 |

This validates the listed retrieval trials, not arbitrary reasoning over an entire repository. Excerpts repeat when necessary, so this is not a diversity-controlled benchmark. A 262K total context with 8,192 tokens reserved for output leaves at most about 254K input tokens, before additional tool/system overhead; agent compaction may start earlier. The near-ceiling raw-engine trials deliberately request only 128 output tokens. No context beyond 262,144 or RoPE extension was tested.

## Resource observations

Measurements were sampled about every five seconds with psutil and NVIDIA-SMI during the 262K comparison and correctness/recall stages, not the initial 32K run or calibration. These are sampled peaks/minima, not guaranteed instantaneous maxima. GPU memory is total device usage, including the desktop; engine RSS can include mapped pages and is not the same as total system memory.

| Request phase | Max system RAM used, GiB | Min available RAM, GiB | Peak GPU memory, MiB | Peak GPU Â°C | Peak GPU W |
| --- | ---: | ---: | ---: | ---: | ---: |
| agent-low-running | 58.88 | 4.93 | 14895 | 56 | 174.57 |
| agent-none-running | 58.88 | 4.93 | 14911 | 59 | 192.77 |
| baseline262-suite-running | 59.24 | 4.57 | 15119 | 67 | 263.12 |
| context-ladder-running | 60.25 | 3.57 | 15048 | 71 | 265.17 |
| tuned262-suite-running | 59.16 | 4.65 | 15036 | 69 | 262.99 |

## Raw records and reproduction

- `baseline/`: initial 32K-ceiling reference suite.
- `baseline262/` and `tuned262/`: comparable 262K-ceiling API suites, with per-request data and captured configuration.
- `calibration.json`: candidate aggregate measurements and selected settings; `*-engine.txt` files retain sanitized native timing logs.
- `agent-none.json`, `agent-low.json`: every bounded coding session, generated code, tool results and model responses.
- `dsh-adapter.json`: native adapter streaming/replay records.
- `context-ladder.json`: every retrieval result, exact token counts, prompt hashes, corpus hash and nonces.
- `resources.jsonl`: sampled resource data; `provenance.json`: build/model/tool hashes; `selected-config.json`: sanitized installed configuration.

```powershell
# One model engine at a time. Stop the live server before standalone calibration.
.\.venv\Scripts\python.exe tools\calibrate.py strata-iq3_xxs.json
# Restore/start one desired config, then drive its HTTP API:
.\.venv\Scripts\python.exe tools\strata_bench.py --config strata-iq3_xxs.json --url http://127.0.0.1:8080 --runs 3 --clients 2 --long --out <result-folder>
.\.venv\Scripts\python.exe tools\arya_agent_bench.py --runs 3 --think none --out <agent-none.json>
.\.venv\Scripts\python.exe tools\arya_agent_bench.py --runs 3 --think low --out <agent-low.json>
node tools\arya_dsh_probe.mjs --runtime-root <development-runtime-project> --runs 3 --out <dsh-adapter.json>
.\.venv\Scripts\python.exe tools\arya_context_bench.py --tokenizer <existing-pack-tokenizer-folder> --lengths 32768,65536,131072,258048 --runs 3 --out <context-ladder.json>
```

Public records redact user/home/host names and credentials where the reporting tools can identify them. Legacy model download locations remain in the installed configuration locally; downloads were reused rather than duplicated. No cloud model, alternative quantization, vision input, true batch-parallel serving, exhaustive correctness suite, or long-running production soak is claimed.
