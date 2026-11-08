# Qwen3.5-4B — the small model that can live beside ComfyUI

This is a second, much smaller text model for the desktop: Unsloth's `Qwen/Qwen3.5-4B` Q4_K_M
GGUF running on the dense `qwen35` path of the AryaInfer engine, intended to stay loaded while
ComfyUI holds the rest of the card. It is an addition: no existing run config or model file was
changed, and the default model is still whatever `strata-*.json` the server is started with.

## Why a dense 4B and not one of the installed models

A Qwen-Image-2.1 workflow keeps the unet (6.76 GB, int8), the VAE (0.63 GB) and the text encoder
(5.88 GB) on the card. Every installed model is 10.4 GB of weights or more; a 27B or a 35B-A3B
cannot share 16.38 GB with that, and when the engine sizes itself against too little free VRAM it
quietly runs partly on the CPU (the measured 30 tok/s instead of 57-95). A 2.55 GiB model with a
64K cache takes 4.5 GiB and leaves the rest to ComfyUI.

## What is on disk

| File | Size |
| --- | --- |
| `C:\AI\Strata-data\models\qwen35-4b\Qwen3.5-4B-Q4_K_M.gguf` | 2,740,937,888 B |
| `C:\AI\Strata-data\models\qwen35-4b\mmproj-F16.gguf` | 672,423,616 B |
| `C:\AI\Strata-data\packs\qwen35-4b\tokenizer\` | 5 files, built from the GGUF |
| `strata-qwen35-4b.json` | run config: `aryainfer.exe`, 64K context, `--kv q4_0`, CPU vision |
| `models.json` | one added entry, `qwen3.5-4b` |

Sizes are the HTTP byte counts from Hugging Face, checked against the local files.

## Measured on this machine (2026-11-06, RTX 4070 Ti SUPER, 16,376 MiB)

All with ComfyUI 0.37.4 up on 8188 and the model on its own server on 8083.

- **Resident size**: 5,092 MiB of used VRAM minus the 611 MiB baseline = 4.48 GiB.
- **Chat speed**: a 20-token prompt decoded at 163 tok/s (0.30 s to first token); a 67-token
  prompt at 157 tok/s with a 400-token answer in 2.72 s; with ComfyUI holding its models,
  the same two prompts ran at 142 and 141 tok/s.
- **Image turn**: 1,063-token prompt (1,036 image tokens from a 640x480 PNG) — 7.77 s to the
  first token while the CPU encoder ran, 156 tok/s after; once the picture is encoded, a
  follow-up turn cost 0.20 s to first token at 140 tok/s.
- **Same-second co-residency**: a 1024 cutout through ComfyUI's API took **28.1 s** with the
  4B engine resident (ComfyUI pages its unet through DynamicVRAM), **8.1 s** with the engine
  unloaded, and **100.2 s** when ComfyUI's text encoder was forced onto the CPU. Peak while
  both were live: 13,850 MiB used of 16,376 MiB.
- **CPU text encoder is a bad trade**: 100 s per image instead of 28 s. The profile edit that
  moved it to the CPU was tried and reverted; the encoder stays on the GPU.

The image times include ComfyUI's own load of the 5.88 GB encoder the first time; a warm
second image with the engine unloaded took 8.1 s.

## What was checked before loading

- **Tensor set**: all 426 tensors of the Q4_K_M file compared name by name and shape by shape
  against what `src/poly/qwen35.cpp` `load_layer` asks for: 0 mismatches. 24 Gated DeltaNet
  layers and 8 gated-attention layers (`full_attention_interval` 4), qkv 2560x8192, k/v
  2560x1024, ssm conv kernel 4, state 128, group 16, rope dimension sections [11,11,10,0]
  (`tmp\install-fit\check-tensors.py` reads the GGUF, not the engine).
- **Tokenizer pack**: `tools\strata_tokenizer.py --check` — vocab 248,320, merges 247,587,
  `pre` qwen35, 16/16 round trips, `<|im_start|>` 248045, `<|im_end|>` 248046.
- **No MTP block**: no `nextn`, `eh_proj`, `enorm`, `hnorm` or `blk.32.*` tensors, so
  `--no-draft` is not needed and nothing is guessed ahead.
- **Chat template**: the pack's `chat_template.jinja` renders DSH-style tool calls whose
  `arguments` arrive as a JSON string as `<parameter=…>` values, and defaults to thinking off
  (`tmp\slm\render_check.py` runs it through the server's own Jinja environment). The stock
  template skipped those arguments; the stock Qwen3.8 template raises
  `TypeError: Can only get pairs from a mapping` on them.

## Running it

Engine alone (8083 so it cannot collide with the resident server):

```
cd C:\Users\KNPhu\AryaCode\KonnectSuite\AryaInfer
.venv\Scripts\python.exe -m serve.server --engine strata --config strata-qwen35-4b.json --port 8083
```

Then `http://127.0.0.1:8083/v1/chat/completions` with `"model": "qwen3.5-4b"`.

With the desktop: the Control Center lists it as **AryaStrata Qwen3.5 4B Q4_K_M - 64K vision
(pairs with ComfyUI)** and `POST /api/models/load {"model": "qwen3.5-4b"}` switches to it
without a restart. Loading a text model asks ComfyUI to free its memory first (`POST /free`), so
the first ComfyUI image after a switch pays for a reload.

Two ways to live with the card:

- **Chat-first** (the config as shipped): the 4B stays resident, ComfyUI pages its unet — an
  image costs 28 s instead of 8 s, chat is instant.
- **Image-first**: unload the 4B from the Control Center when you are generating (or set
  `idle_unload_s` in the run config so it drops after a quiet spell); images go back to 8 s and
  the next chat turn pays a few seconds to reload.

The engine line in `strata-qwen35-4b.json` uses `aryainfer.exe` (the same engine that serves
Qwen3.8 27B) because `engine-poly\strata-poly.exe` refuses `--kv q4_0` for a dense `qwen35`
model; `STRATA_GDN_MMA=1` and the `strata-0.1.54` lib directory mirror the Qwen3.8 27B config,
and the vision encoder is the `strata-0.1.54` build with `gpu: false`.

## The ComfyUI side

No profile change is needed or left in place: all twelve `CLIPLoader` nodes in the two copies of
the Qwen Image workflow lists are back at `"device": "default"` (the profile is byte-identical to
`cordis.patch.yml.bak-clip-cpu`, verified with a line diff). ComfyUI absorbs the smaller card with
`DynamicVRAM`, which pages unet weights, and needs no flags. If images matter more than keeping
text resident, `--vram-headroom 5` in Desktop's "Startup Arguments" makes ComfyUI leave room
instead of paging.
