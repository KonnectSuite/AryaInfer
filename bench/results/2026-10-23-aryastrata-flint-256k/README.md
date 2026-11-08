# Flint 40B-A2.5B UD-Q4_K_XL at 262,144 tokens on the AryaStrata host

Measured October 23, 2026 (America/New_York). AryaStrata is a fork of [PolyStrata](https://github.com/simplexai-labs/PolyStrata),
a fork of [Niko1221's original Strata](https://github.com/Niko1221/Strata). These are measurements on our own host,
using the ready-made upstream `strata-poly` engine 0.1.45 (poly.3); no custom engine build or engine-code speedup is
claimed.

## Host and model

- Intel Core i9-14900KF, 24 physical cores / 32 logical processors; 8 performance + 16 efficiency cores. 15 CPU
  threads for the experts outside VRAM.
- NVIDIA GeForce RTX 4070 Ti SUPER, 16,376 MiB VRAM; driver 610.88. Display active, ordinary desktop processes
  running; no clock locking or driver changes.
- 63.82 GiB usable system memory; Windows 11 Home 10.0.26200; WD Blue SN580 2 TB SSD.
- `flint-UD-Q4_K_XL.gguf`, 25,054,688,704 bytes, SHA-256 `63c2ecc461ca545134b670c660e76fa20f47240f8d39b6510bfd21c4dd6e072f`
  (Unsloth, pinned to their 2026-10-21 commit). Downloaded and verified on this host on the same day.
- Ready-made `strata-poly` 0.1.45 (poly.3), CUDA 13.0, `BUILD.json` `src 38ce288cd08729a0`, for sm_75/80/86/89/120.
  The binary was downloaded from PolyStrata's release and its SHA-256 checked by the installer.

## Configuration

```text
--max-context 262144 --prompt-batch 2048 --threads 15 --conversation-cache-mib 8192
```

The GGUF declares `flint.context_length = 262144`. The installer's context menu stops at 131,072, so the config was
written with `--context 262144`. The engine itself enforces only a minimum of 16 tokens, no maximum. A ceiling is not
a claim that every task succeeds at that length; this file tests speed and recall of a full read, not task quality.

## Method

Each case sends one user message of synthetic filler (repeated vocabulary plus random numbers) followed by a fixed
instruction, and asks for the single word `DONE`. Every message begins with a unique nonce, so no conversation or
prefix cache can be reused: the engine reported `cache_n = 0` in all eleven runs, and every read is a full prefill.

- Streaming request through `POST /v1/chat/completions`, `stream_options.include_usage`, `temperature 0`,
  `max_tokens 128`.
- Prefill and write speeds are the engine's own `timings.prompt_per_second` and `timings.predicted_per_second`.
  Time to first token is the client's, from request to the first streamed delta.
- Prompt sizes are the engine's `prompt_n`, not the requested size.
- Three runs at 8K, 32K and 129K; two at 243K, because each of those reads takes about three minutes. Medians are
  reported with the observed range.

## Results

| Prompt read (median) | Time to first token | Prefill | Write |
| ---: | ---: | ---: | ---: |
| 8,143 tokens | 2.25 s (2.24–2.41) | 3,707 tok/s (3,437–3,710; n=3) | 121.2 tok/s (119.9–121.6; n=3) |
| 32,311 tokens | 8.08 s (7.97–8.14) | 4,036 tok/s (4,006–4,088; n=3) | 93.2 tok/s (91.9–95.2; n=3) |
| 129,323 tokens | 58.73 s (58.24–58.97) | 2,227 tok/s (2,200–2,229; n=3) | 57.8 tok/s (56.7–58.6; n=3) |
| 242,606 tokens | 170.05 s (169.71–170.39) | 1,430 tok/s (1,427–1,433; n=2) | 21.8 tok/s (n=2) |

The 8K prefill median sits below the 32K one because the first 8K run was cold (3,437 tok/s against 3,707 and 3,710
after it). Read as: prompt processing is about 4,000 tok/s up to 32K, about 2,200 at 129K and about 1,400 at 243K.

Every run answered `DONE` and stopped at 36 to 49 tokens, well inside the 128 limit.

## What the VRAM did

The attention cache grows with the prompt and takes the VRAM the expert cache had. Routed experts in VRAM, from the
engine log:

| Prompt | Experts in VRAM | Expert cache |
| ---: | ---: | ---: |
| load (32K config) | 6,217 of 12,032 | 11.10 GiB |
| 32K | ~5,492 | 10.18 GiB |
| 129K | 3,423 | 6.56 GiB |
| 243K | 1,457 | 2.94 GiB |

The engine traded experts for cache without an error, and no run ran out of memory. The fall in write speed with
prompt length follows from this: fewer experts stay on the card, so more of each token's routing is served from
system RAM. The conversation cache parked each finished conversation rather than dropping it (1.5 s to park the
242,596-token one).

## Limits

- Speed only. No coding suite, no recall or needle test, no tool loop. Flint's instruction following was exercised
  only to the extent of answering `DONE`.
- One request at a time. `--parallel` was not enabled and several clients were not tried.
- Flint reads text only; no image path exists for it.
- The desktop was in ordinary use during the runs; nothing else was deliberately run on the GPU, but this is not an
  idle-machine measurement.
- A single host. These numbers describe this PC, not the model on other hardware.

## Files

- `results.json`: the eleven raw runs, one object each.
- `bench-flint-256k.py`: the script, with the filler and the timing extraction.
