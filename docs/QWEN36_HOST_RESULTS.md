# Qwen3.6 Q4 versus Q8: AryaInfer host results

Both installed templates support thinking Off/On. Historical `low` requests
enable native thinking; Low/Medium/High are aliases in AryaAI, not three
distinct strengths. See the [connection audit](ARYAAI_CONNECTION_AUDIT.md).

Measured on the i9-14900KF, RTX 4070 Ti SUPER 16 GB, 64 GB RAM Windows host. AryaInfer is a fork of PolyStrata, which is a fork of Niko1221's original Strata.

Both model quants use the source-matched PolyStrata backend, a 262,144-token context with the whole Q8_0 KV cache allocated, GPU vision at up to 1,024 image tokens, one conversation slot, and tail skipping disabled. Q8 model weights and Q8 KV cache are separate choices.

**Daily coding-agent choice on this host: Q4.** Both quants completed the checks,
but Q4 had lower median bounded-task latency and substantially more RAM headroom.
Q8 remains a working higher-precision weight option. These small fixtures reached
a quality ceiling on both quants; they do not establish equal general coding
quality or a quality advantage for either one.

The installed profiles retain **15 CPU threads, window 8, prompt batch 512,
Q8_0 KV, GPU vision, and one conversation slot**. Neither tuning candidate was
retained. Q4's candidate did not improve the confirmation median. Q8's candidate
had a small median lead but did not consistently beat the paired baseline runs.
Exact host profiles are saved as [Q4](../bench/results/2026-10-17-qwen36-poly-256k/profiles/Q4.json)
and [Q8](../bench/results/2026-10-17-qwen36-poly-256k/profiles/Q8.json); adjust paths
when reproducing on another checkout.

| Model | Baseline decode tok/s | Candidate decode tok/s | Selected threads / window | Coding none | Coding low | Image checks | Long recall | Long coding + image |
|---|---:|---:|---|---|---|---|---|---|
| Q4 | 151.2 | 150.8 | 15 / 8 | 18/18 | 18/18 | 12/12 | 6/6 | 3/3 |
| Q8 | 97.2 | 100.1 | 15 / 8 | 18/18 | 18/18 | 12/12 | 6/6 | 3/3 |

The short-speed columns are medians of the two confirmation-run medians, each
drawn from six short coding prompts. Q8's baseline runs varied from 79.9 to
114.6 tokens/s, so its small candidate median lead was not treated as reliable.
All tuning uses the same full context allocation and vision configuration.
Quality checks are reported separately from speed. Each 18-session coding count
is six bounded fixtures repeated three times, not 18 independent tasks.

The coding suites use bounded Python fixtures and executable checks, not a real repository or an overall coding-quality score. The long coding test adds repeated repository excerpts and an image; it reports image-ID recognition separately. Recall uses three facts in repeated source excerpts and is not a general long-code comprehension score. A configured 262K capacity is distinct from the actual prompt token counts recorded in the raw reports.

The native Strata Qwen3.6 backend failed at 262K and 192K on this host; the separate PolyStrata backend is used here. RAM conversation checkpoints are not active KV streaming from RAM. Quantized KV may change answers. No claim of equivalence to FP32 KV is made.

[Raw results](../bench/results/2026-10-17-qwen36-poly-256k/summary.json)

## Choose a model in AryaAI

In the AryaAI development build, select one of these installed models. Reload
the app's model list if the updated entries are not visible.

| Choice | Exact model ID | Weight quantization | When to use it on this host |
|---|---|---|---|
| Q4 | `qwen3.6-35b-a3b-ud-q4_k_xl` | UD-Q4_K_XL | Recommended daily coding-agent profile; more measured RAM headroom |
| Q8 | `qwen3.6-35b-a3b-q8_0` | Q8_0 | Higher-precision weight comparison; very little RAM headroom in these trials |

Both profiles support text and image input, advertise 262,144 context tokens
and 8,192 output tokens to the development adapter, and use the same compressed
Q8_0 KV cache. The output limit is part of the total context budget, not extra
capacity beyond it. Leave room for image tokens, message formatting, generated
answers and subsequent tool results when assembling an agent conversation.

The largest measured text recall input was **254,191 tokens**. The combined
coding-and-image test began around **230,827 input tokens**, leaving more room
for its tool loop. Both ran with the full 262,144-token cache allocated and
vision enabled; a successful text recall trial does not establish image-and-tool
performance at that same input length.

For small edits like the measured fixtures, start with reasoning off. Low
reasoning passed the same fixture checks but took longer. Keep either setting
available for harder work; these results do not establish its quality there.
See [AryaAI connection settings](ARYAAI_DSH.md) for the integration details.

## Long-input performance

Fresh three-fact recall prompts, three runs per length and quant; medians below. Vision was loaded throughout.
The recall answers were about 53 tokens. These rates and the short-prompt tuning
rates measure different workloads; compare the quants within a workload.

| Model | Approximate prompt | Actual input tokens, median | Prefill tok/s | First token, s | Decode tok/s | Recall |
|---|---:|---:|---:|---:|---:|---|
| Q4 | 131,072 | 131,031 | 1,404.3 | 93.4 | 73.8 | 3/3 |
| Q4 | 253,952 | 254,191 | 973.1 | 261.4 | 43.1 | 3/3 |
| Q8 | 131,072 | 131,031 | 1,404.5 | 93.4 | 52.2 | 3/3 |
| Q8 | 253,952 | 254,191 | 1,008.9 | 252.1 | 44.9 | 3/3 |

## Coding latency and resource observations

Times are complete fixture sessions, including tool loops. Resource peaks cover tuning and validation, not model-file size.
RAM use includes Windows and other desktop processes. Q8 briefly left only
0.10 GiB available during a recall trial and 0.25 GiB during combined coding.
The tests completed, but paging was not measured; this is not evidence that all
Q8 work stayed in physical RAM without SSD activity.

| Model | Coding none, median s | Coding low, median s | Long coding, median s | Image ID reported in long coding | Peak RAM used, GiB | Least RAM available, GiB | Peak GPU allocation, MiB |
|---|---:|---:|---:|---|---:|---:|---:|
| Q4 | 5.07 | 8.07 | 89.72 | 3/3 | 50.46 | 13.35 | 16,008 |
| Q8 | 6.99 | 12.63 | 100.71 | 3/3 | 63.72 | 0.10 | 15,926 |

For these small edits, reasoning off passed the same checks with lower median
latency than low reasoning. Low reasoning remains available; harder-task quality
was not established here. The development app's existing default-model and
thinking preferences were preserved rather than globally replaced.

Both installed model IDs also passed **3/3 streaming and tool-result replay
checks** through the AryaAI development adapter, `dsh-llm-pi-ai` 0.2.0-rc.2:
[Q4 records](../bench/results/2026-10-17-qwen36-poly-256k/Q4/dsh-adapter.json),
[Q8 records](../bench/results/2026-10-17-qwen36-poly-256k/Q8/dsh-adapter.json).
This validates the adapter path, not every native desktop workflow. The
development profile advertises 262,144 context tokens, 8,192 output tokens,
and text/image input for both models.

The long coding harness supplies approximately 229K tokens of repeated source excerpts plus an image before the task; its subsequent tool turns reuse that prefix. Its first turn is cold relative to that prefix. It does not prove coding quality across an entire real repository. Image-ID reporting is independent of code-test success.

## Reproduce the validation

Select the installed model profile with the PolyStrata executable and its recorded arguments. Keep the server bound to 127.0.0.1 and stop other inference and download jobs during measurements. With the selected model loaded, use:

```powershell
.\.venv\Scripts\python.exe tools/arya_context_bench.py --tokenizer <tokenizer-directory> --lengths 131072,253952 --runs 3 --out context.json
.\.venv\Scripts\python.exe tools/arya_agent_bench.py --model <model-id> --suite all --think none --runs 3 --out agent-none.json
.\.venv\Scripts\python.exe tools/arya_agent_bench.py --model <model-id> --suite all --think low --runs 3 --out agent-low.json
.\.venv\Scripts\python.exe tools/arya_vision_bench.py --model <model-id> --runs 3 --out vision
.\.venv\Scripts\python.exe tools/arya_long_agent_bench.py --model <model-id> --tokenizer <tokenizer-directory> --tokens 229376 --runs 1 --out long-agent
```

A power interruption occurred after Q4 calibration, coding and image checks, three 128K recall trials, and the first near-256K recall trial. Completed records were preserved. Both model SHA-256 hashes were rechecked after restart; the interrupted uncompleted trial was resumed. Telemetry retains both sessions.

## Combined long-context coding and image sessions

Each quant starts with a cold source-and-image prefix for its first fixture; later fixtures may reuse that prefix. These are different tasks, not independent repetitions of one task. The table reports observed cache reuse rather than assuming it.

| Model | Fixture | Complete session, s | First-call cached input tokens | Code tests | Image ID reported |
|---|---|---:|---:|---|---|
| Q4 | trim_history | 410.73 | 0 | pass | yes |
| Q4 | merge_tool_results | 89.72 | 208896 | pass | yes |
| Q4 | summarize_usage | 57.01 | 208896 | pass | yes |
| Q8 | trim_history | 526.38 | 0 | pass | yes |
| Q8 | merge_tool_results | 77.24 | 208896 | pass | yes |
| Q8 | summarize_usage | 100.71 | 208896 | pass | yes |

The tuning sweep varied CPU threads and speculative window size. Prompt batching remained fixed at 512; other prefill batch sizes and KV formats were not tuned in this comparison. The speed-selection threshold is an empirical rule on a small sample, not a statistical confidence claim.

The image checks are synthetic OCR, chart, shape and multiple-image smoke checks,
not a general vision-accuracy benchmark. Batch concurrency, real-repository coding
benchmarks, and FP16-versus-Q8 KV accuracy comparisons were not measured. The
image-containing coding prompt began around 230,827 tokens; the 254,191-token
recall prompt contained text, with the vision encoder loaded. Neither number is
an assertion that a 262,144-token input still leaves room for output or tool turns.
