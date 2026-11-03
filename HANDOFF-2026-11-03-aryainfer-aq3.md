# Handoff — aryainfer: AQ3 (uniform 3-bit) weights for Qwen3.8 27B (2026-11-03)

Goal: NInfer-class speed for Qwen3.8 27B inside `aryainfer.exe` (not a port). The plan is
`C:\Users\KNPhu\.claude\plans\jaunty-bouncing-boot.md`; the earlier state is `HANDOFF-2026-11-03-qwen38-perf.md`.
The session stopped on budget before Stage 3 code started.


## UPDATE (second budget, same day): AQ3 runs end to end

- `tools/aryainfer_gsq3_convert.py` works (`--check` passes; GDN V heads reordered as llama.cpp does). Output file:
  `build-env\models\Qwen3.8-27B-GSQ3-AQ3-mtp.gguf` (the sandbox would not let Python write under `C:\AI`; move it to
  `C:\AI\Strata-data\models\qwen38-27b\` by hand). Packing is a dense little-endian 3-bit stream, NOT 10 per
  int32; the format notes below are corrected by the converter's docstring.
- Engine (all under `ARYAINFER_ENGINE`): `Engine::upload` tags I8 rows of `aq3_row_bytes(n_in)` as `kTypeAQ3` (200);
  `Engine::lin` sends n <= 8 to `aq3_gemv` (dp4a) and prompt batches to `aq3_to_q8_0` + MMQ Q8_0 (exact). Kernels in
  `src/poly/prefill_f16.cu`. The old fused wmma path for AQ3 (285 tok/s) is still there as the no-MMQ fallback.
- Measured (table in `docs/QWEN38-27B.md`): decode 88.3 vs 67.0 at 8K, 80.5 vs 69.0 at 32K. Prefill 706 at batch
  512, 1,229 at 2048 (old file 1,239 at 512): the Q8_0 expansion is the cost.

### Next, in order
1. **Native AQ3 MMQ tile loader**: add AQ3 to the vendored MMQ as a `load_tiles` variant that unpacks straight to the
   int8 tile (like Q8_0's loader, with the `aq3_q8_0_kernel` arithmetic), so no expansion pass. Expect prefill well
   above 1,239 at batch 512. Alternative if MMQ is too invasive: a cp.async-pipelined int8 `mma.sync` GEMM.
2. Faster `aq3_gemv`: coalesced 16-byte loads (lanes on consecutive blocks), 2 rows a warp; check T=1 bandwidth
   (should approach 600 GB/s; the weights are ~10.5 GB).
3. 64K/128K runs, VRAM at 128K, perplexity vs the RCO file, then a `models.json` entry `qwen3.8-27b-aq3` and a
   `docs/host-tuning/` config; copy `build-polyryainfer.exe` into `C:\AI\Strata-data\enginesrya-infer\`.
4. Stage 2 (long-context attention) needs a profiler.

## Target

NInfer-4080 (RTX 4080, 76 SMs, 717 GB/s): prefill 2,754 / 2,460 / 2,152 tok/s at 8K / 32K / 64K; MTP3 decode with
n-gram off 150 / 142 / 130. This host (4070 Ti SUPER, 66 SMs, 672 GB/s) reads 1,288 / 1,114 / ~912 and writes ~67 /
~70 / 59-66. A fair target is 85-90% of NInfer.

## Done this session

- **Stage 1 (deeper MTP drafts): negative, closed.** `STRATA_FORCE_GUESSES=N` (aryainfer only,
  `Guesses::force_width` in `src/poly/guesses.hpp`, read in `Session` in `src/poly/main.cpp`). At 8K, windows 3-8 read
  65.9 -> 42.6 tok/s against the policy's 67.0; accepted tokens barely move (171 -> 184 of 256). Table in
  `docs/QWEN38-27B.md`, harness `tools/qwen38_force_bench.py`. The policy is not the limit.
- **Diagnosis:** verify rows (2-8 tokens) go through `kernels::native_mmvq` (`Engine::lin`, `src/poly/engine.cpp`
  ~line 2311), 8 tokens a launch. With IQ3_XXS each weight needs a grid lookup + sign unpack per column, so at 8 columns
  the kernel is ALU-bound: each extra row costs 3.4-5.6 ms on a 22.7 ms pass. Prefill (MMQ) is dequant-bound for the
  same reason. Both point to one fix: a weight format that becomes int8 for free.
- **Stage 2 not started.** No Nsight on this host (`nsys` absent), so the attention share of the decay with depth
  is unmeasured. Install Nsight Systems before Stage 2, or add cudaEvent timing around `attention`/`gdn`/`lin` calls.
- **Source checkpoint downloading/downloaded** to `C:\AI\Strata-data\models\qwen38-27b-gsq3-src\`
  (`ISTA-DASLab/Qwen3.8-27B-3Bit-GSQ`, revision `b5ce0b76f60020a875dee4f6ec9d934cca4121e4`, Apache-2.0, three shards
  2.27 + 4.78 + 4.78 GB). Downloaded with plain curl from `huggingface.co/<repo>/resolve/<rev>/<file>`; check sizes
  against those numbers and against `crc32.txt`. Venv creation is blocked in this sandbox, so no `huggingface_hub`.
- ISTA-DASLab has no 2-bit Qwen3.8 27B (their list: `GSQ-RCO-GGUF`, `3Bit-GSQ`, `NVFP4-prefiller`; NVFP4 needs
  sm_120). There is a `GSQ-RCO-IQ2_S-mtp.gguf` already in `C:\AI\Strata-data\models\qwen38-27b\` if a 2-bit arm is
  ever wanted.

## Source format (measured from the files)

`compressed-tensors`, `format: pack-quantized`:
- Linear weights in `linear_attn.*`, `self_attn.*`, `mlp.*`: **int 3-bit, symmetric, group 128 along the input
  dim**, minmax observer. Tensors: `<name>.weight_packed` (I32), `<name>.weight_scale` (BF16, `[out, in/128]`),
  `<name>.weight_shape` (I64[2]). The packing is compressed-tensors' `pack_to_int32`: values stored offset
  (`q + 4`, 0..7) and **10 values per int32** (`32 // 3`) along the input dim. Verify on one tensor against
  compressed-tensors' `unpack_from_int32` before trusting this. (NInfer's card describes an "offset form with a
  shifted bit-plane transform", so check the bit order on real data, e.g. reconstruct one row of `down_proj` and
  compare its matmul with the IQ3_XXS GGUF's dequantized row; they should correlate ~0.99, not match exactly.)
- `embed_tokens` and `lm_head`: int 4-bit symmetric, group 64 (`embed_tokens.weight_packed` I32 `[248320, 640]`,
  8 per int32; `weight_scale` BF16 `[248320, 80]`).
- Unquantized (BF16): `visual.*`, `mtp.*` (one MTP layer, 15 tensors), `linear_attn.in_proj_a/b`, norms, `A_log`,
  `dt_bias`, `conv1d`.
- Dims: hidden 5120, intermediate 17408, 64 layers, full attention every 4th (24 Q heads, 4 KV heads), GDN 48 value
  / 16 key heads.

## Next steps, in order

1. **Converter** `tools/aryainfer_gsq3_convert.py`: read the safetensors (plain `struct`+`json`+numpy, no torch), unpack
   to signed int8 codes [-4, 3] and an FP16 scale per 128, and write a GGUF that is the existing
   `Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf` with every 3-bit linear replaced by a new type `AQ3_G128`. Copy all
   metadata, tokenizer, norms, MTP and other tensors from the existing GGUF so `qwen35.cpp` loads it unchanged;
   map HF names to the GGUF names it already uses (read them with `tools/strata_tokenizer.py`'s GGUF reader or
   `gguf` from the vendored llama.cpp). Suggested block (keeps 16-byte alignment): 128 values = 48 bytes of codes
   (3 bit-planes of 16 bytes, or 32 x 12-bit packs) + 2-byte fp16 scale -> 50 bytes / 128 = 3.125 bpw. Pick the
   layout that makes the kernel's unpack 2-3 instructions per 8 values (bit-planes: `(p0>>i&1)|(p1>>i&1)<<1|...`
   with `__byte_perm`/`lop3`). Pick a type id far from ggml's (e.g. 200) and guard it with `ARYAINFER_ENGINE`.
2. **Small-T GEMV** `src/poly/aq3_gemv.cu`, T = 1..8: one warp per output row block, stream weights once, unpack to
   int8, dp4a against the existing q8_1 activations (`kernels::native_quantize_q8_1`), apply the group scale x the
   q8_1 block scale. Add it to `Engine::lin` before the `native_mmvq` loop for `w.type == AQ3_G128`. Test:
   `src/poly/aq3_test.cu` (model on `gdn_mma_test.cu`) against a CPU reference; T=1 should reach >= 80% of 672 GB/s.
3. **Prefill GEMM** `src/poly/aq3_gemm.cu`: tiles unpacked to int8 in shared memory, `mma.sync.m16n8k32.s8`,
   q8_1 activations from `Mmq::quantize`, scale in the epilogue; hook it at the `mmq_ && n >= kStageRows` branch of
   `Engine::lin`. SwiGLU fusion later.
4. Model entry `qwen3.8-27b-aq3` in `models.json` + `docs/host-tuning/strata-qwen3.8-27b-aq3.json` (copy of the arya
   config with the new file). Existing entries unchanged.
5. Measure with `tools/qwen38_force_bench.py 8192,32768,65536 default=0` (point `MODEL` at the new file), check
   perplexity against IQ3_XXS, record in `docs/QWEN38-27B.md`.
6. Then Stage 2 (long-context attention decode, SM-count-derived grids) with a profiler.

## Build and run

    build-env\build-arya.cmd    # MSVC 14.44 + CUDA 13.1.2, sm_89; output build-poly\aryainfer.exe
    python tools\qwen38_force_bench.py 8192 default=0 f4=4    # stop the server and all engines first

Copy `build-poly\aryainfer.exe` to `C:\AI\Strata-data\engines\arya-infer\aryainfer.exe` after a release-worthy build
(not done this session; the installed copy predates `STRATA_FORCE_GUESSES`, which is harmless since it is unset).
