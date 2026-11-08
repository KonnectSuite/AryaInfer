# Engines

AryaInfer is one inference space with four engine backends behind it. You start
one server, open one web app, and use one OpenAI- or Anthropic-compatible API;
the model you pick decides which backend runs. Switching models is a config
change (`switch_on_request`), not a different program to learn.

The Python server (`serve/server.py`) owns everything around the model:
the chat template, the thinking effort and its budget, tools, images, prompt
cache lookup keys and the streaming parser. An engine only turns prompt token
ids into new token ids, over the same line protocol. That is why a GGUF MoE
runner, the native Qwen engine, our AQ3 build and a ported NInfer core can sit
in the same roster.

## The four backends

| Backend | Binary | Source | Models on this host | Context | Vision |
| --- | --- | --- | --- | ---: | --- |
| **Strata** (native Qwen engine) | `strata.exe` 0.1.58 | [Niko1221/Strata](https://github.com/Niko1221/Strata) | Qwen3.8-Flash-Next IQ3_XXS, Swift 1.5, Swift 1.5 abliterated | 262,144, int8 KV | `strata-vision.exe` + mmproj, GPU |
| **PolyStrata** (`strata-poly`) | `engine-poly\strata-poly.exe` | `src/poly`, from [VecSzn/PolyStrata](https://github.com/simplexai-labs/PolyStrata) | Qwen3.6-35B-A3B UD-Q4_K_XL and abliterated, Ornith 1.5 APEX, and the GGUF families in [BACKENDS.md](BACKENDS.md) | 262,144, q8_0 KV | `strata-vision.exe` + mmproj, GPU |
| **AryaInfer** (fork build) | `C:\AI\Strata-data\engines\arya-infer\aryainfer.exe` (repo build: `build-poly\aryainfer.exe`) | `src/poly` fork target, CUDA `sm_89`; AQ3 kernels in `src/poly/prefill_f16.cu` | Qwen3.8-27B AQ3 (GSQ 3-bit), Qwen3.8-27B Turbo IQ3_XXS, Qwen3.5-4B Q4_K_M | 131,072 (27B), 65,536 (4B), q4_0 KV | `strata-vision.exe` + mmproj, CPU |
| **NInfer** (ported) | `engine-ninfer\ninfer-engine.exe` | [roofkid/ninfer-4080](https://github.com/roofkid/ninfer-4080) at `rtx4080-port` commit `2469b57`, plus `engine-ninfer/shim/main.cpp` | Qwen3.8-27B GSQ3 `.ninfer` | 131,072, rk4v4-e8 KV | external `.sve` embeddings from `strata-vision.exe`, CPU |

All four are configured per model in a `strata-*.json` run config: `exe`,
`args`, `tokenizer`, `sampling`, `reasoning_effort`, `reasoning_budget_by_effort`,
`vision`, `switch_on_request`. Nothing about the API, the web app or the tools
changes when the engine does.

## One protocol

The server starts an engine with `--serve` and reads:

- `READY <max_context> [stop]` and `INFO key=value` at startup;
- `GEN <max_new> [sampling keys] <ids>` for text, `GENI ... <embeddings> <ids>`
  when the engine takes images as precomputed embeddings;
- `T <id>` per token, `PP <read> <total> <ms> <tok_s>` for prefill progress,
  `RESUME <n>` when a prefix was reused, and
  `DONE <generated> <prompt_tokens> <prompt_ms> <decode_ms> <finish> [...]`.

Thinking, sampling defaults, the template and tool parsing stay on the server.
The engine ABI is described in `serve/server.py` (`StrataEngine`) and each
backend implements it:

- Strata and PolyStrata implement it natively (`--serve`);
- `aryainfer` is the same `src/poly` tree built with the AQ3/Turbo kernels;
- `engine-ninfer` is a small C++ shim over NInfer's `Engine` API
  (`prepare_tokens` / `prepare_tokens_with_vision` + `submit`), with a vendored
  patch that exposes the accepted token ids to the streaming sink.

## Choosing a model, not an engine

The roster is the `strata-*.json` files next to the config you start with
(`/api/models` lists them). Today's measured host profiles:

| Model | Engine | Context | Why it is here |
| --- | --- | ---: | --- |
| `qwen3.8-flash-next-iq3_xxs` | Strata 0.1.58 | 262,144 | Fastest long-context MoE path here; DFlash2 + MTP |
| `qwen3.8-27b-aq3` | AryaInfer | 131,072 | Dense 27B quality at 3-bit codes, 1.2K tok/s prompt reads |
| `qwen3.8-27b-ninfer` | NInfer | 131,072 | Highest measured prefill on this card (2,039 tok/s at 8K) |
| `qwen3.6-35b-a3b-ud-q4_k_xl` | PolyStrata | 262,144 | Best validated 35B MoE for agent work |
| `qwen3.6-35b-a3b-abliterated` | PolyStrata | 262,144 | Unrestricted 35B variant |
| `ornith-1.5-35b-a3b-apex-i-quality` | PolyStrata | 262,144 | 18/18 bounded coding with low reasoning |
| `qwen3.8-27b-turbo-iq3xxs` | AryaInfer | 131,072 | Daily-driver 27B with MTP |
| `swift-1.5-iq3_xxs` | Strata 0.1.58 | 262,144 | Token-efficient Qwen3.8 variant, 262K vision |
| `swift-1.5-abliterated-iq3_xxs` | Strata 0.1.58 | 262,144 | Unrestricted Swift 1.5 |
| `qwen3.5-4b` | AryaInfer | 65,536 | Small, fast, vision-capable |

## Measured on this host

Every number below was measured on the machine in [ARYAINFER.md](ARYAINFER.md)
(i9-14900KF, RTX 4070 Ti SUPER 16 GB, 64 GB RAM, Windows 11). Workloads differ:
the Flash-Next and AQ3 rows read JSON/HTTP requests, the NInfer row reads a
fixed token corpus, and the 35B rows read long synthetic prompts. Compare
within a row, not across engines.

Four installed profiles have **no speed row here**: Qwen3.8-27B Turbo IQ3_XXS,
Qwen3.5-4B Q4_K_M, Swift 1.5 IQ3_XXS and Swift 1.5 Abliterated IQ3_XXS. They
run daily on this host; their speeds were not re-measured on the current
engine builds, so no number is claimed for them. The Swift 1.5 IQ3_XXS
headline against a cloud API is documented in
[BENCHMARK_GOJO_SWIFT_VS_DEEPSEEK.md](BENCHMARK_GOJO_SWIFT_VS_DEEPSEEK.md).

### Strata 0.1.58 (November 7, 2026) - Qwen3.8-Flash-Next IQ3_XXS

DFlash2, `--kv int8`, 32K resident KV, 262,144 context, temperature 0.3. One
run per row, so treat them as spot measurements rather than medians.

| Prompt | Prefill | Decode |
| ---: | ---: | ---: |
| 19 tokens | 52.6 tok/s | 86.4 tok/s |
| 4,621 tokens | 1,886.0 tok/s | 78.4 tok/s |
| 16,121 tokens | 1,336.9 tok/s | 74.4 tok/s |

On 0.1.56 the same configuration read prompts at 491-523 tok/s in the engine
log and the Monitor showed 52.8 tok/s decode around 15K, so 0.1.58 is roughly
2.7x faster at prompt reading and 40% faster at writing there. The release
notes credit the CPU/upload share following the measured CPU speed (ceiling
0.95 instead of 0.60) and a larger automatic prompt chunk.

### AryaInfer - Qwen3.8-27B AQ3

`--kv q4_0`, prompt batches of 1,024-2,048, `STRATA_GDN_MMA=1`.

| Prompt | Batch | Prefill | Decode |
| ---: | ---: | ---: | ---: |
| 8K | 2,048 | 1,229.3 tok/s | 85.1 tok/s |
| 32K | 2,048 | 1,062.5 tok/s | 80.5 tok/s |
| 130,672 tokens | 1,024 | 582.6 tok/s | 68.4 tok/s |

Full AQ3 notes, the Q8_0 expansion fix and the context ladder:
[QWEN38-27B.md](QWEN38-27B.md).

### NInfer - Qwen3.8-27B GSQ3 `.ninfer`

`rk4v4-e8` KV, MTP draft 3, `--max-context 131072`, repeated-id corpus so the
draft acceptance is 96-100% (optimistic for prose).

| Prompt | Prefill | Decode |
| ---: | ---: | ---: |
| 8,192 | 2,039 tok/s | 115.3 tok/s |
| 32,768 | 1,855 tok/s | 109.8 tok/s |
| 65,536 | 1,672 tok/s | 103.3 tok/s |
| 98,304 | 1,535 tok/s | 100.2 tok/s |
| 130,816 | 1,358 tok/s | 89.0 tok/s |

On real prose the same build wrote 74.7 tok/s with 47% acceptance. Prefix reuse
takes a repeated 1,220-token turn from 1,845 ms to 33 ms (`reused 1219`), and a
57,018-token turn from 30.1 s to 41 ms, once `--host-kv-mib` is large enough
(245,760 here). Limits and measurements: [NINFER.md](NINFER.md).

### PolyStrata - Qwen3.6-35B-A3B

| Model | Prompt (actual) | Prefill | Decode |
| --- | ---: | ---: | ---: |
| UD-Q4_K_XL | 131,031 tokens | 1,404.3 tok/s | 73.8 tok/s |
| Q8_0 | 131,031 tokens | 1,404.5 tok/s | 52.2 tok/s |

Short-prompt decode was 151.2 (Q4) and 97.2 (Q8). Coding, image and recall
results: [QWEN36_HOST_RESULTS.md](QWEN36_HOST_RESULTS.md).

## Credits

AryaInfer would not exist without the projects below. Each keeps its own
license; see [CREDITS.md](../CREDITS.md) and `LICENSE`.

- **Strata** - [Niko1221](https://github.com/Niko1221/Strata) and the Strata
  contributors: the Qwen engine, server, installer, web app and paper.
- **PolyStrata** - [VecSzn](https://github.com/simplexai-labs/PolyStrata) and its
  contributors: the `strata-poly` MoE engine, GLM 5.3 Flash, DeepSeek V4 Flash,
  the model integrations and the roster measurements.
- **NInfer** - [roofkid](https://github.com/roofkid/ninfer-4080): the
  16 GB / 100K-context Qwen3.8 engine core, its GSQ3 artifact format, MTP3 and
  DFlash2 work. The shim in `engine-ninfer/` and the patch in
  `engine-ninfer/patches/` are ours; the core is pinned at commit `2469b57`.
  NInfer in turn builds on ideas from [Neroued's ninfer](https://github.com/Neroued/ninfer).
- **Quantization and models** - [ISTA-DASLab](https://huggingface.co/ISTA-DASLab)
  for the 3-bit GSQ Qwen3.8 checkpoints, [Unsloth](https://huggingface.co/unsloth)
  for the UD quants, the Qwen team for the models, and the model-card authors of
  every GGUF in the roster.
- **Kernels and tooling** - [llama.cpp / ggml](https://github.com/ggml-org/llama.cpp)
  (MIT), [Splash](https://github.com/incoai/splash),
  [HyperQwen](https://github.com/syv-ai/HyperQwen), NVIDIA's NVTX v3.1.0 headers
  (Apache-2.0, vendored for the Windows build), and libcurl (MIT) / FFmpeg
  (LGPL) through vcpkg.
- **Interface** - the web app's MCP catalog shape follows
  [llama.cpp](https://github.com/ggml-org/llama.cpp)'s server UI (MIT), and the
  brand marks in `serve/web/mcp-icons.svg` come from
  [Simple Icons](https://simpleicons.org) (CC0 1.0).

## Adding or checking a backend

1. Produce an executable that speaks the protocol above (`--serve`).
2. Add a `strata-*.json` beside the other configs with `exe`, `args`,
   `tokenizer`, `model_name` and the capability fields (`vision`, `sampling`,
   `reasoning_budget_by_effort`).
3. Start the server with `--engine strata` (the default) and that config; it
   appears in `/api/models` and `/v1/models` immediately.
4. Measure it on this host before calling it a host result, and record the build
   hash, config, workload and raw output under `bench/results/`.

[Back to the README](../README.md) - [Host setup](ARYAINFER.md) -
[Model roster](MODELS.md)
