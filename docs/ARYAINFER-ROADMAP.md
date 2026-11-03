# AryaInfer roadmap: Qwen3.8 27B at NInfer-class speed

Written 2026-11-03 after the AQ3 work. All "here" numbers are measured on this host (i9-14900KF, RTX 4070 Ti SUPER
16 GB, 66 SMs, 672 GB/s, Windows 11) with `tools/qwen38_force_bench.py`, q4_0 KV, `STRATA_GDN_MMA=1`, greedy, 256
tokens; details in [QWEN38-27B.md](QWEN38-27B.md). NInfer numbers are from roofkid/ninfer-4080's README (RTX 4080,
76 SMs, 717 GB/s), not measured here. Effort figures are estimates, not measurements.

## 1. Where we are and where the target is

| | Here, IQ3_XXS mix | Here, AQ3 | NInfer 4080 | Target on this card |
|---|---:|---:|---:|---:|
| Prompt read, 8K | 1,239 | 1,229 (batch 2048) | 2,754 | ~2,400 |
| Prompt read, 32K | 1,105 | 1,063 (batch 2048) | 2,460 | ~2,100 |
| Prompt read, ~128K | 662 | 583 (batch 1024) | 1,917 (98K) | ~1,600 |
| Writing, 8K, MTP, no n-gram | 67.0 | 88.3 | 150.5 | ~130 |
| Writing, 32K | 69.0 | 80.5 | 141.7 | ~120 |
| Writing, ~128K | 56.9 | 68.4 | 122.2 (98K) | ~100 |

The target is about 85-90% of NInfer: fewer SMs and less bandwidth on this card. NInfer's headline 300-385 tok/s
writing includes n-gram drafting on a repetitive test text; compare against its `--ngram off` column.

## 2. Why we are slow: what the measurements say

1. **A one-token pass costs 22.7 ms** at 8K (IQ3_XXS mix): 427 GB/s, 64% of the card's bandwidth. A pass that reads
   ~10.5 GB of weights at 85% of bandwidth would take ~18 ms.
2. **Each extra verify row costs 3.4-5.6 ms** (15-25% of a pass). Verify rows go through `native_mmvq`, which is
   ALU-bound on IQ3's codebook. NInfer's speed requires rows that cost well under 1 ms.
3. **Deeper drafts lose** with today's row cost: windows 3-8 read 65.9 -> 42.6 tok/s against the policy's 67.0;
   accepted tokens go from 171 to only 184 of 256 (8K). Depth pays only once rows are nearly free.
4. **Prompt reading is dequant-bound.** IQ3 MMQ is limited by its codebook; AQ3 is currently expanded to Q8_0 for
   every batch (the whole model written and read again), which is why AQ3 ties only at batch 2048.
5. **Long-context slowdown is not yet attributed.** Writing drops ~15% from 8K to 128K, reading ~45%. Attention
   (`fattn.cu`), GDN and the KV format are suspects; no profiler has been run.

So the gap is in **four kernels**, not in the engine's structure: the 1-token GEMV, the 2-16 token verify product,
the prompt GEMM, and long-context attention.

## 3. Keep the engine or redesign?

**Recommendation: keep `aryainfer` and rebuild its hot path for this model.** Do not start a new engine.

What `aryainfer` already has that a new engine would have to rebuild first, before getting faster:
the GGUF loader and arena, Qwen3.8's GDN layers (with the chunked MMA prefill kernel), full attention with q4_0/q8_0
KV and flash attention, MTP drafting with an acceptance-driven policy, n-gram/suffix drafting, CUDA graphs, prefix
reuse and conversation cache, the serve protocol, vision handoff, and the Python server/WebUI integration. That is most
of an engine, and it is correct today. NInfer's own changes listed in its README are almost all kernels and
quantization formats.

What changes is **ownership of the hot path**: a dedicated Qwen3.8-27B dense path in aryainfer with its own kernels,
instead of routing through generic ggml kernels shared with every other model.

When a full redesign *would* be right: if profiling (step P0) shows the per-pass overhead outside the matmuls
(launches, syncs, small kernels between them) is over ~25% of a pass and CUDA graphs cannot remove it. Then the
answer is a fused per-layer megakernel design, which is a new forward pass, still inside aryainfer's shell.

### The shape of the redesign inside aryainfer

```
src/arya/                       new, built only into aryainfer
  aq3.hpp                       format constants (moved from prefill_f16.hpp)
  aq3_gemv.cu                   T = 1..4: bandwidth-optimal GEMV
  aq3_verify.cu                 T = 2..16: int8 tensor-core product (mma.sync m16n8k32)
  aq3_gemm.cu                   T >= 64: pipelined int8 tensor-core GEMM, fused epilogues
  fused.cu                      norm+quantize, SwiGLU+quantize, residual adds fused into neighbours
  qwen38_dense.cpp              the forward pass for this model (replaces Qwen35's dense path under aryainfer)
tools/aryainfer_gsq3_convert.py exists
tools/qwen38_force_bench.py     exists; grows a --profile mode
```

`Engine::lin` keeps a single AQ3 branch that dispatches by token count: 1-4 -> GEMV, 5-16 -> verify MMA,
>= 64 -> GEMM (the 17-63 band picks the faster of verify/GEMM by measurement).

## 4. The plan, in order, with a gate after each step

Every step: one engine at a time, `nvidia-smi` empty first, the bench table at 8K / 32K / 128K, greedy text checked
against the previous build, results into `QWEN38-27B.md`, one commit. Do not start the next step until the gate holds.

### P0. Profile first (small)
- Install Nsight Systems; add `--profile` to the bench to run `nsys profile --capture-range=cudaProfilerApi`
  around one prompt batch and 20 decode rounds (add `cudaProfilerStart/Stop` under `ARYAINFER_ENGINE`).
- Output: a per-kernel time table for one prompt batch and one decode round at 8K and 128K, split into matmul /
  attention / GDN / other.
- **Gate:** we know what share of a pass each class takes, and what grows with depth. This decides P4's priority and
  whether the megakernel question in section 3 is live.

### P1. Native AQ3 prompt GEMM (biggest single gain; large)
- Option A (try first, cheaper): add AQ3 as a tile loader in the vendored MMQ (`mmq.cuh` `load_tiles_*`), reusing
  `aq3_q8_0_kernel`'s unpack, so MMQ reads 3.125-bit weights directly; no expansion pass.
- Option B (if A is capped by MMQ's structure): own GEMM. 128x128 tiles, 3-4 stage `cp.async` pipeline for the
  weight tile, unpack to int8 in shared memory, `mma.sync.m16n8k32.s8.s32`, activations quantized to int8 per 32
  (q8_1) once per layer, scale applied in the epilogue; epilogue fusions: SwiGLU for gate/up (one GEMM of the
  concatenated matrix), residual add for down/o_proj.
- Also: concatenate gate+up into one AQ3 matrix in the converter (one launch, activations read once).
- **Gate:** prompt read at 32K >= 1,800 tok/s at batch 512, and the VRAM at 128K no higher than today.

### P2. Verify-row product (the decode unlock; medium-large)
- `aq3_verify.cu`: for T = 2..16 tokens, int8 `mma.sync` with the token dimension as N (8 or 16), weights streamed
  once from global memory with 16-byte loads, unpacked in registers. Goal: T=8 costs <= 1.3x T=1.
- Faster T=1 GEMV: lanes on consecutive 16-byte chunks (coalesced), two rows a warp, scales hoisted; goal >= 85%
  of 672 GB/s.
- Fuse RMSNorm + q8_1 quantize ahead of each matmul group, SwiGLU + quantize ahead of down.
- **Gate:** one-token pass <= 19 ms at 8K, extra row <= 0.8 ms. Re-run `STRATA_FORCE_GUESSES` 3..8.

### P3. Drafting re-tune (small)
- With cheap rows, depth should now pay: re-measure acceptance per position (fix `--report-drafts` so the serve
  path prints `drafts by pos`), then make the policy's row-cost model use the new measured costs. Expected: 3-4
  guesses a round become the norm (NInfer runs MTP3).
- Turn on the n-gram chain (`--lookup-chain`) by default for code-like prompts and measure on real code, not filler.
- **Gate:** writing >= 120 tok/s at 8K with n-gram off, and real coding prompts >= 150.

### P4. Long context (medium; priority set by P0)
- Decode attention at 128K: split-K partitions derived from the SM count (66), q4_0 K/V dequant pipelined with the
  dot products; check the GDN gating kernels for fixed grid sizes (NInfer changed theirs from 128 to the runtime SM
  count).
- Prefill attention at depth: chunked prefill of 1-2K tokens with the KV already written in the target format.
- Optional, only if VRAM blocks a bigger prompt batch: a 4-bit rotated KV format (NInfer's `rk4v4`).
- **Gate:** writing at 128K >= 85% of writing at 8K; reading at 128K >= 1,500.

### P5. Make it the default (small)
- Perplexity of AQ3 vs the IQ3_XXS mix on a fixed 100K-token text; a short coding eval.
- `qwen3.8-27b-aq3` becomes the recommended entry; prompt batch chosen by measured VRAM at 128K.
- Optional: a DFlash-style draft model is out of scope until P3's numbers are in.

## 5. Rough effort

| Step | Size | Expected effect |
|---|---|---|
| P0 profile | small | decides P4, settles the megakernel question |
| P1 prompt GEMM | large | reading ~1.1K -> ~2K tok/s |
| P2 verify + GEMV | medium-large | writing ~80 -> ~100, enables P3 |
| P3 drafting | small | writing ~100 -> ~120-130 |
| P4 long context | medium | holds the gains at 128K |
| P5 default | small | the user gets it by default |

Order matters: P2 before P3 (drafting depth only pays with cheap rows), P0 before P4. P1 and P2 are independent and
can be split across sessions.

## 6. Rules carried forward

- Changes live under `ARYAINFER_ENGINE` / `src/arya/`; `strata-poly` and `strata.exe` stay upstream-mergeable.
- A new path is opt-in until measured faster; existing model entries stay byte-identical.
- The Python sandbox here cannot write under `C:\AI`; write to `build-env\` and move by hand.
- Benchmarks: stop the server and every engine first.
