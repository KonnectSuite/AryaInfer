# Engines

AryaInfer is one inference space with five engine backends behind it. You start
one server, open one web app, and use one OpenAI- or Anthropic-compatible API;
the model you pick decides which backend runs. Switching models is a config
change (`switch_on_request`), not a different program to learn.

The Python server (`serve/server.py`) owns everything around the model:
the chat template, the thinking effort and its budget, tools, images, prompt
cache lookup keys and the streaming parser. An engine only turns prompt token
ids into new token ids, over the same line protocol. That is why a GGUF MoE
runner, the native Qwen engine, our AQ3 build and a ported NInfer core can sit
in the same roster.

## The five backends

| Backend | Binary | Source | Models on this host | Context | Vision |
| --- | --- | --- | --- | ---: | --- |
| **Strata** (native Qwen engine) | `strata.exe` 0.1.67 | [Niko1221/Strata](https://github.com/Niko1221/Strata) | Qwen3.8-Flash-Next IQ3_S, Gyro-M | 262,144, int8 KV | `strata-vision.exe` + mmproj, GPU |
| **Strata Inkling** | `engine-inkling\strata-inkling.exe`, built here from 0.1.68 | [Niko1221/Strata](https://github.com/Niko1221/Strata) | Inkling-2-Mini SQ-15 | 65,536, host KV offload | native vision encoder |
| **PolyStrata** (`strata-poly`) | `engine-poly\strata-poly.exe` 0.1.66 | `src/poly`, from [VecSzn/PolyStrata](https://github.com/simplexai-labs/PolyStrata) | Qwen3.6-35B-A3B UD-Q4_K_XL and abliterated, Ornith 1.5 APEX, and the GGUF families in [BACKENDS.md](BACKENDS.md) | 262,144, q8_0 KV | `strata-vision.exe` + mmproj, GPU |
| **AryaInfer** (fork build) | `engine-arya\aryainfer.exe` 0.1.45 | `src/poly` fork target, from [KonnectSuite/AryaInfer](https://github.com/KonnectSuite/AryaInfer); CUDA `sm_89`; AQ3 kernels in `src/poly/prefill_f16.cu` | Qwen3.8-27B AQ3 (GSQ 3-bit), Qwen3.8-27B Turbo IQ3_XXS, Qwen3.5-4B Q4_K_M | 131,072 (27B), 65,536 (4B), q4_0 KV | `strata-vision.exe` + mmproj, CPU |
| **AryaNInfer** (ported core) | `engine-ninfer\arya-ninfer.exe` 0.1.0 | [roofkid/ninfer-4080](https://github.com/roofkid/ninfer-4080) at `rtx4080-port` commit `2469b57`, plus `engine-ninfer/shim/main.cpp` | Qwen3.8-27B GSQ3 `.ninfer` | 131,072, rk4v4-e8 KV | external `.sve` embeddings from `strata-vision.exe`, CPU |

All five are configured per model in a `strata-*.json` run config: `exe`,
`args`, `tokenizer`, `sampling`, `reasoning_effort`, `reasoning_budget_by_effort`,
`vision`, `switch_on_request`. Nothing about the API, the web app or the tools
changes when the engine does.

The web app edits those files on the Settings page: each row carries the flag it
writes, the engine's documented default, a hint and a Reset, the engine's
environment variables are rows rather than hand-typed JSON, and the catalog only
offers a flag to an engine that takes it. [SETTINGS.md](SETTINGS.md) lists what
each control does and how the catalog stays honest as the engines change.

### Who owns which engine

| Engine | Built and released by | AryaInfer's part |
| --- | --- | --- |
| Strata | [Niko1221/Strata](https://github.com/Niko1221/Strata) — [releases](https://github.com/Niko1221/Strata/releases) | installs the pinned binary from `engines.json`; no source changes |
| Strata Inkling | [Niko1221/Strata](https://github.com/Niko1221/Strata) — [releases](https://github.com/Niko1221/Strata/releases) | builds it here from the vendored 0.1.68 sources (`engine-inkling/`). Measured against the 0.1.67 release it is the same engine at short context; what made Inkling 2 Mini usable was the K/V and expert budget in the run config, which 0.1.67 could also set. Having the source means the next such question is a patch, not a wait: [INKLING.md](INKLING.md) |
| PolyStrata (`strata-poly`) | [VecSzn/PolyStrata](https://github.com/simplexai-labs/PolyStrata) — [releases](https://github.com/simplexai-labs/PolyStrata/releases) | installs the pinned binary; `strata-poly` stays upstream-identical |
| AryaInfer (`aryainfer`) | this fork — [AryaInfer releases](https://github.com/KonnectSuite/AryaInfer/releases) | our build of the pinned PolyStrata source, with the AQ3/q4_0 changes behind `ARYAINFER_ENGINE` |
| AryaNInfer (`arya-ninfer`) | core by [roofkid](https://github.com/roofkid/ninfer-4080), shim/patches by this fork | manual build; the core stays pinned at `2469b57` |

The source snapshot in this checkout is still Strata `v0.1.45` / PolyStrata
`0.1.45-poly.9` (`upstream.json`). `--build` compiles that pin, so it produces
0.1.45 engines; the default install takes the current upstream binaries pinned in
`engines.json` (Strata 0.1.67, PolyStrata 0.1.66) and builds Strata Inkling 0.1.68
from `engine-inkling/src`. Updating the source pin is a separate merge, not
something this installer pretends happened.

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

- Strata, Strata Inkling and PolyStrata implement it natively (`--serve`);
- `aryainfer` is the same `src/poly` tree built with the AQ3/Turbo kernels;
- `engine-ninfer` is a small C++ shim over NInfer's `Engine` API
  (`prepare_tokens` / `prepare_tokens_with_vision` + `submit`), with a vendored
  patch that exposes the accepted token ids to the streaming sink.

## Choosing a model, not an engine

The roster is the `strata-*.json` files next to the config you start with
(`/api/models` lists them). Today's measured host profiles:

| Model | Engine | Context | Why it is here |
| --- | --- | ---: | --- |
| `qwen3.8-flash-next-gyro-m` | Strata 0.1.67 | 262,144 | Gyro-M TQ2_0 (~92 GB); 61.6 tok/s decode, 270 tok/s prompt, 262K vision |
| `inkling-2-mini-sq-15` | Strata Inkling 0.1.68 (built here) | 65,536 | Native Inkling 2 Mini SQ-15 (~14.3 GB); 52.9 tok/s decode at 8K, 48.9 at 32K, 2,122 / 1,843 tok/s prefill; native encoder |
| `qwen3.8-27b-aq3` | AryaInfer | 131,072 | Dense 27B quality at 3-bit codes, 1.2K tok/s prompt reads |
| `qwen3.8-27b-ninfer` | AryaNInfer | 114,688 | Highest measured prefill on this card (2,039 tok/s at 8K); 131,072 overruns a 16 GiB card with vision |
| `qwen3.6-35b-a3b-ud-q4_k_xl` | PolyStrata | 262,144 | Best validated 35B MoE for agent work |
| `qwen3.6-35b-a3b-abliterated` | PolyStrata | 262,144 | Unrestricted 35B variant |
| `ornith-1.5-35b-a3b-apex-i-quality` | PolyStrata | 262,144 | 18/18 bounded coding with low reasoning |
| `qwen3.8-27b-turbo-iq3xxs` | AryaInfer | 131,072 | Daily-driver 27B with MTP |
| `inkling-2-mini-ud-q4_k_xl` | PolyStrata 0.1.66 | 262,144 | Unsloth UD-Q4_K_XL text fallback; 262K, vision via `mmproj-F16.gguf` |
| `qwen3.5-4b` | AryaInfer | 65,536 | Small, fast, vision-capable |

## Measured on this host

Every number below was measured on the machine in [ARYAINFER.md](ARYAINFER.md)
(i9-14900KF, RTX 4070 Ti SUPER 16 GB, 64 GB RAM, Windows 11). Workloads differ:
the Flash-Next and AQ3 rows read JSON/HTTP requests, the NInfer row reads a
fixed token corpus, and the 35B rows read long synthetic prompts. Compare
within a row, not across engines.

Two installed profiles have **no speed row here**: Qwen3.8-27B Turbo IQ3_XXS,
Qwen3.5-4B Q4_K_M. They run daily on this host; their speeds were not re-measured
on the current engine builds, so no number is claimed for them. Swift 1.5 IQ3_XXS
and Swift 1.5 Abliterated IQ3_XXS had no row either and no longer have files
here: the plain Swift config was dropped on 2026-11-13 and the abliterated
shards, expert pack, MTP layer and run config were uninstalled on 2026-11-25
([ARYAINFER.md](ARYAINFER.md)); the rows in
[PLC_SAMPLING.md](PLC_SAMPLING.md) and [host-tuning](host-tuning/README.md) stay
as their record. The Swift 1.5 IQ3_XXS headline against a cloud API is documented
in
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

### Strata 0.1.62 baseline (November 19, 2026) - Qwen3.8-Flash-Next IQ3_XXS

Engine 0.1.62 with `--draft-cap 8` (upstream release v0.2.16). Cold prompts,
one different prompt per request, interleaved A/B, medians of five (two at
96K); the full record is under
[`bench/results/iq3_xxs-0.1.62-draft-cap-8/`](../bench/results/iq3_xxs-0.1.62-draft-cap-8/2026-11-19-arya-infer-rtx-4070-ti-super-qwen3-8-flash-next-iq3-xxs/README.md).

| Prompt | Prefill | vs 0.1.59 | Decode | vs 0.1.59 |
| ---: | ---: | ---: | ---: | ---: |
| 4K | 2,021 tok/s | -2.8% | 127.9 tok/s | +19.3% |
| 16K | 3,319 tok/s | +20.4% | 109.4 tok/s | -4.5% |
| 32K | 3,417 tok/s | +5.3% | 95.7 tok/s | +-0 |
| 96K | 3,412 tok/s | +5.2% | 94.9 tok/s | +31.3% |

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

`rk4v4-e8` KV, MTP draft 3, `--max-context 114688`, repeated-id corpus so the
draft acceptance is 96-100% (optimistic for prose). The numbers below were
measured at 131,072, which needs 3,355,516,160 bytes of runtime reservation and
does not fit a 16 GiB card that also drives a desktop; the shipped entry runs
114,688 and starts reliably. `--host-kv-mib` pins host memory at startup, so it
is 12,288 MiB here, not the 245,760 MiB the 57,018-token reuse measurement used.

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
(245,760 there, which pins 240 GiB of RAM and so only fits a host that large).
Limits and measurements: [NINFER.md](NINFER.md).

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
