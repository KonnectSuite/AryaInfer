# Qwen3.8 27B (ISTA-DASLab GSQ-RCO) on strata-poly

A dense Qwen3.8 model for AryaStrata's second engine.  It is Qwen35's model with one dense FFN where the routed
experts are (llama.cpp calls the architecture `qwen35`), so the engine runs it through the same layers, the same
gated delta net, the same 3-axis vision rope and the same block that guesses ahead - with no router anywhere.

Everything below marked "measured" was read off this host; everything marked "projection" is arithmetic on those
measurements and has not been run.

## The files

Measured 2026-11-02 from the Hugging Face tree API (revision `d562806dbafae37109975e970aae91b43e73b440`) and the
downloaded files' SHA-256 on this host.

| file | bytes | SHA-256 |
| --- | --- | --- |
| `Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf` | 10,442,827,840 | `63f29a2189a6b4cc31f81e093d3856ad293a5583114439f41ae1ed7af4093262` |
| `Qwen3.8-27B-GSQ-RCO-IQ2_S-mtp.gguf` | 9,607,981,120 | `e6406238a5cc0043775cd1963b6f9e5b8707400276e38d9fde742304906b1330` |
| `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` | 12,120,016,960 | `58fd8267...` (not downloaded) |
| `Qwen3.8-27B-GSQ-RCO-IQ2_XS-mtp.gguf` | 8,771,311,680 | `f3369f8d...` (not downloaded) |
| `mmproj-Qwen3.8-27B-BF16.gguf` | 931,146,528 | `13cb7bebccbd04afc8f4090cb949ecf8937cdf7377c5799b1a0c594e7c0d3e16` |

The first two and the mmproj are at `C:\AI\Strata-data\models\qwen38-27b\` on this host, their SHA-256 checked.

## The model's shape (measured from the file headers)

`tools/qwen38_gate1_dump.py` reads a 128 MiB range of the file (the header is well inside it) and prints these.

| key | value |
| --- | --- |
| `general.architecture` | `qwen35` (llama.cpp's dense Qwen3.8/3.5; the MoE sibling is `qwen35moe`) |
| blocks | 65: layers 0-63, then one block that guesses ahead (`nextn_predict_layers` 1) |
| embedding / FFN | 5120 / 17408, no expert keys at all |
| attention | 24 heads, 4 KV heads, key = value = 256, rope 64 with sections 11,11,10,0, theta 1e7 |
| full attention | layers 3, 7, ... 63 (16 of 64); the other 48 are gated delta net |
| gated delta net | state 128, 16 key heads, 48 value heads, inner 6144, conv kernel 4 |
| vocabulary | 248320, tokenizer `gpt2` embedded in the file |
| draft block (block 64) | full attention, dense FFN, `nextn.eh_proj` [10240, 5120] Q6_K |
| vision | a separate `clip` mmproj: 27 blocks, image 768, patch 16, width 1152, projection 5120, projector `qwen3vl_merger`, 461 M parameters, BF16 |

A 768-pixel image is 48 x 48 patches, merged 2 x 2, so one full-resolution image is 576 tokens.

## What the engine does with it

`Engine::open()` reads `general.architecture`; `qwen35` now says "Qwen35, dense" and calls `load_shape(false)`, so the
expert keys are not looked for and every MoE hook stays off (no layer sets `Layer::moe`).  `Qwen35` then reads
`feed_forward_length` for its dense FFN and uploads `ffn_gate`/`ffn_up`/`ffn_down` a layer in place of the experts,
and `layer_head()` runs the FFN and adds it to the residual itself, because `step()` runs no `layer_tail()` for a
layer that routes to no experts.  The draft block (block 64) is dense too, and the same code path serves it.

Types the dense arena's MVP path reads are kept as they are; `IQ1_S` is not one of them (`native_mmvq` has no
`vec_dot_iq1_s_q8_1`), so `Engine::upload()` converts those matrices to BF16 at load, which is 376 MiB of the IQ3_XXS
file's weights (+839 MiB for IQ2_S).  Prompt batches run through MMQ, which has a tile for every type in either file.
That is the one known weight-arena cost of these files; porting the IQ1_S dot to `iq_kernels.cu` would take it back
and is left as a later change.

## Measured on this host

RTX 4070 Ti SUPER 16 GB, i9-14900KF, 96 GB RAM, Windows 11, 2026-11-02.  Built with the CUDA 13.1.2 redist toolkit
(`build-env/configure-cuda.cmd`: nvcc 13.1.115, cicc from `cuda_tileiras`, libdevice from `libnvvm`, MSVC 14.44 host
compiler, `sm_89`).

* The IQ3_XXS file loads in 3.0 s (4K context) and 8.4 s (32K context), and the engine prints
  `0 of 0 routed experts in VRAM (0.0 GiB), 32 CPU threads` - the dense path, with no expert cache.
* 10 prompt tokens at 51.4 tok/s and 8 generated tokens at 28.3 tok/s (4K context, `--no-graphs --window 1`,
  fp16 KV).  The same run with `--kv q8_0` gave the same 8 token ids at 55.8 / 31.0 tok/s.
* `--kv q8_0` is accepted for the dense file (1088 bytes of cache a row: 32 Q8_0 blocks of 34 bytes).
* The generated ids for `Hello! In one sentence, what are you?` were the same with fp16 and q8_0 KV:
  `271,40,1044,264,30894,321,23739,14791`.
* With its draft block on (window 8, CUDA graphs), 16 tokens came out at 53.4 tok/s and 8 of 12 guesses were
  right; the first 8 ids were the same as the run with no guesses.
* A picture: a 768-pixel rendered card (`CARD NUMBER 4711`) went through `strata-vision` with the 27B mmproj
  (1024 image tokens, mtmd's Qwen-VL minimum), then through the engine as `--images card.sve --image-pad 248056`
  at 32K context, q8_0 KV.  1,047 prompt tokens at 152.4 tok/s, 66 generated tokens at 82.4 tok/s, 46 of 49
  guesses right, peak VRAM 14,078 MiB.  The answer read the card: `The image clearly shows a large blue number
  "4711" under the label "CARD NUMBER"` and answered `4711`.

Through the server (`serve/server.py` with `strata-qwen3.8-27b-iq3_xxs.json`, port 8081, vision encoder resident):

| prompt | read | needle `VULTURE-7319` | decode | peak VRAM |
| --- | --- | --- | --- | --- |
| 2,932 tokens | 0.27 s warm (1.3 s the second time, 19.4 s cold) | found | 60 tok/s | - |
| a picture through the server's OpenAI API | the card's 1,024 tokens + the question = 1,091 prompt tokens | - | - | -
|  | the answer is 4711 | | | |
| 30,079 tokens | 208 s (145 tok/s) | found | 43.6 tok/s | 14,997 MiB |
| 62,028 tokens | does not finish | - | - | 15,945 MiB, then about 11 tok/s |

The 62K prompt is the card's limit, and it is past it: the read reached 28,672 tokens in 700 s and then advanced
about 1,024 tokens every 110 s, with 382 MiB free.  With the caches given their whole `--max-context` at load
(65,536 tokens is 2.1 GiB) and the vision encoder resident (0.87 GiB), 32K is the configuration that holds on this
file and this card.  A 32K run of the same file without the server measured 14,078 MiB, and the 30K needle above
settled at 14,921-14,997 MiB.

## The images ladder, measured (2026-11-02)

All through the server (`serve/server.py`), vision encoder resident, needle `VULTURE-7319` asked at the end of the
prompt, greedy.  The q4_0 cache is `--kv q4_0` (18,432 bytes a token instead of q8_0's 34,816).

| file | context asked | prompt tokens | needle | prefill | decode | peak VRAM |
| --- | --- | --- | --- | --- | --- | --- |
| IQ3_XXS, q8_0 | 32K | 30,079 | found | 983.7 tok/s | 44.4 tok/s | 14,948 MiB |
| IQ3_XXS, q4_0 | 32K (picture: card 4711) | 1,047 | - | 1,077.8 tok/s | 80.6 tok/s | - |
| IQ3_XXS, q4_0 | 64K | 64,077 | found | 842.9 tok/s | 33.3 tok/s | 15,015 MiB |
| IQ3_XXS, q4_0 | 96K | 96,026 | found | 639.4 tok/s | 28.5 tok/s | 15,351 MiB |
| IQ3_XXS, q4_0 | 120K | 120,056 | **stalled** at 94,208 | - | - | 15,939 MiB |
| IQ3_XXS, q4_0, `--prompt-batch 256` | 128K | 128,024 | **found** | 574.9 tok/s | 51.6 tok/s | 15,661 MiB |
| IQ2_S, q4_0 | 128K | 128,066 | found | 548.4 tok/s | 22.2 tok/s | 15,749 MiB |
| IQ2_S, q4_0, `--prompt-batch 256` | 200K | 200,069 | **found** | 440.0 tok/s | 5.3 tok/s | 15,942 MiB |

The 4-bit cache is what makes 64K and up fit at all: with q8_0 the 62K attempt on IQ3_XXS stalled at 28.7K tokens.
The 120K stall on IQ3_XXS was not the cache but the default 1,024-token prompt batch: its scratch is about 1.4 MiB a
token, and dropping to `--prompt-batch 256` frees enough for 128K on the same file (measured 2026-11-02: 15,661 MiB
peak, needle found).  The 200K run sits 434 MiB from the card's limit, so it wants the smaller file *and* the smaller
prompt batch.  Decode at 200K is 5.3 tok/s on the generic kernel; the group-6 kernel below is what raised it.

### After the group-6 decode kernel (NInfer's geometry idea, 2026-11-02)

The flash-decoding kernel (dec) had been written for groups of 8 or 16 heads a KV head, which this model's 24 over
4 is not, so its decode ran on the generic ttend kernels.  NInfer's decode kernel takes its GQA geometry - group
size, token tile - as a template parameter and masks the padded rows; ours needed only the same: dec_fits() now
accepts a group of 6 and dec_q8/dec_q4/dec_f16 dispatch to 
un_dec<KV, 6>.  Re-measured through the same
server, same files, same needles:

| context | decode before | decode after | prefill after | needle |
| --- | --- | --- | --- | --- |
| 30,079 (q8_0) | 44.4 tok/s | **57.6 tok/s** (1.30x) | 991.5 tok/s | found |
| 64,077 (q4_0) | 33.3 tok/s | **55.7 tok/s** (1.67x) | 818.8 tok/s | found |
| 200,069 (q4_0) | 5.3 tok/s | **14.6 tok/s** (2.75x) | 417.3 tok/s | found |

The cache formats against each other: `tools/qwen38_kv_matrix.py` runs five prompts 24 tokens each, greedy, on
fp16, q8_0 and q4_0 caches - and all five give **the same token ids on all three** (a greeting, the first 20 digits of
pi, three colours with hex codes, 17 x 23 answered as 391, and a haiku).  A 4-bit cache that changed the answer would
show there.

## Prefill: the prompt path (the one big win so far)

`Engine::alloc()` made its MMQ handle (`mmq_`, llama.cpp's `mul_mat_q`) only when a layer with routed experts asked
for it.  A dense model has no such layer, so `lin()` never took the matrix-matrix branch: every prompt batch went
through `native_mmvq` eight tokens a launch, and each launch reads the whole matrix again - about 130 reads of a
1,024-token batch's weights per matrix.  The handle is now created for a model with no experts at all
(`n_moe_ == 0 && n_expert_ == 0`, so kolibri1 and every MoE file keep the old path byte for byte).

Measured through the server on the same 30,079-token needle, same card, same file:

| | read | needle |
| --- | --- | --- |
| before | 208,539 ms (144.2 tok/s) | found |
| after | 30,576 ms (983.7 tok/s) | found |

6.8 times the prompt speed, and the greedy answer is unchanged: the 16-token smoke gives the same ids before and
after the change (`271,40,1044,264,30894,321,23739,14791,17313,5995,...`).  Decode did not move (43.5 -> 44.4 tok/s
at that context): it is not a matrix product but a bandwidth walk of the weights.

## Why decode is where it is

Decode reads the dense weights once a step (10.4 GB in this file) and, past 4,096 positions of context, the whole
cache as well (3.7 GB of q4_0 at 200K).  With the group-6 kernel of the section above, a step at 200K therefore moves
about 14 GB in 68 ms - 206 GB/s, or a third of the card's 672.  At 30K the same step is 10.4 GB + 0.55 GB in 17 ms,
about 640 GB/s, which is the bandwidth ceiling: short-context decode has nothing left to win.  The long-context gap
is the kernel's arithmetic, not the bytes: NInfer's INT8/FP8 decode on an RTX 5090 moves 16 GiB of weights and 8.6 GB
of FP8 cache at 260K in 17 ms (1,456 GB/s, 81% of its peak) because Q-K runs on integer tensor cores (mma_s8) with
one scale a 64-value group and P-V on FP16 tensor cores over values dequantized once a tile.  Ours converts each
nibble scalar-wise in the loop; doing the same integer-MMA layout is the next step, and NInfer's published design
(the sources read on 2026-11-02) is the reference for it.

## Calibrated for coding (AryaCode), 2026-11-02

The 27B had no sampling preset - the server serves greedy until a request or a config says otherwise - so two entries
were built and calibrated rather than guessed: `qwen3.8-27b-iq3_xxs` (IQ3_XXS, 64K, q4_0) and `qwen3.8-27b-iq2_s`
(IQ2_S, 200K, q4_0), named like the installed MoE entries ("AryaStrata <family> <size> <quant> - <N>K vision",
`reasoning_loop_recovery: recover`, the old ids kept as aliases).

`tools/qwen38_calibrate.py` drives ten probes through the server - three Python tasks whose code is executed, a
refactor, a bugfix, a C# and a SQL task, and three "answer with only the value" prompts - and
`build-env/loopbait.py` adds the repetition bait (forty near-identical functions, sixty identical lines, a 300-item
count).  Measured per sampling set (500-token answers, thinking budget 1536):

| set | truncations | loops | code runs | answer-only |
| --- | --- | --- | --- | --- |
| temperature 0.6, top_p 0.95, top_k 20 (the card's coding set) | 0 | 0 | 7/7 | 3/3 |
| the same with presence_penalty 0.5 | 0 | 0 | 7/7 | 2/3 |
| the same with presence_penalty 1.5 | 1 | 0 | 6/7 | 3/3 |
| temperature 1.0, top_p 0.95, top_k 20, presence_penalty 0.5 | 1 | 0 | 6/7 | 3/3 |
| greedy (how it was served before) | 0 | 0 | 7/7 | 3/3 |

Both files chose the coding set, which is also what the model card recommends for precise coding.  The loop bait
confirmed what the tables say: no 12-token sequence repeats unless the prompt asks for it, the "repeat this line 60
times" request stops on its own, and the only `length` finishes are output budgets running out mid-file - never a
repeating stream.

Shipped in both configs: `sampling` temperature 0.6, top_p 0.95, top_k 20; `reasoning_budget_tokens` 1536 (a plan, not
a ramble); `reasoning_loop_recovery: "recover"`; and the repeat-stop guard the server already applies.  A request that
names its own sampling still wins, so a client that wants greedy can ask for it.

Verified after the change: two identical requests naming no sampling fields come back different (the config's 0.6 is
in effect, not greedy), "17 times 23, the number only" returns exactly `391`, and the 14,059-token needle is found at
1,098.9 tok/s reading.

## Thinking modes: off, low, medium, high (2026-11-02)

The model's own chat template reads `reasoning_effort` with three graded values and `enable_thinking` for off, so the
server offers all four levels and maps them to the template's vocabulary (`high` -> `xhigh`, `off` ->
`enable_thinking: false`).  `tools/qwen38_thinking.py` measures what each level actually does: six probes, two of them
hard (a two-way price comparison and a non-trivial palindrome task whose generated code is executed), answers capped at
900 tokens, each level under its own ceiling (below).

| level | Q3 (IQ3_XXS) probes | Q3 thinking | Q2 (IQ2_S) probes | Q2 thinking |
| --- | --- | --- | --- | --- |
| off | 4/6 | none | 5/6 | none |
| low | 6/6 | 826 chars | 6/6 | 862 chars |
| medium | 6/6 | 840 chars | 6/6 | 847 chars |
| high | 6/6 | 893 chars | 6/6 | 983 chars |

So thinking is what carries the hard probes: with it off the model still answers the easy ones but misses one or two
of the hard ones, and every graded level passes all six on both files.  How much it thinks does not vary much between
low and high on probes this size - the template's own instruction is doing the steering, not a budget - so a
first-cut `reasoning_budget_tokens` of 1536 was checked for clipping and did not bind: a long planning prompt thought
about 800-900 tokens at every budget tried (1536, 4096 and none), and the only `length` finishes were the answer
running past its own max_tokens.

The budgets were then made per level (`reasoning_budget_by_effort`): off 0, low 4,000, medium 8,000, high 10,000 -
the ladder a reviewer of this work recommended, and a ceiling rather than a target.  Measured per level on the hard
palindrome task (max_tokens 12,000 so the answer-room rule does not trim the level): off 0 tokens of thinking, low 346,
medium 368, high 322 - all four produced runnable code, and the ceilings were nowhere near reached.  The server's log
shows the applied cap per request ("thinking: ... of budget 8000", "capped at 9000 of max_tokens 12000 ... (budget
10000)"), so the ladder is visible at run time.

Shipped in both configs: `reasoning_effort: "medium"` for requests that name no level, the per-level ceilings above,
and the loop guard (`reasoning_loop_recovery: "recover"` plus the repeat-stop tokens the server already applies).
Verified after the change on both files: a request naming no level thinks (medium applied), `off` returns in 0.1-0.2 s
with no thinking at all, low/medium/high each think and every one of them answered 37 x 41 as exactly `1517`, and the
one repetition the probe set flags is a repeated `while` line in generated code, not a runaway stream.

## Prefill: what was tried and measured (2026-11-02)

Prefill is the one phase at the integer tiles' ceiling: 1,064 tok/s at 20,051 tokens, 1,102 at 14,059, flat across
prompt batches of 512, 1,024 and 2,048 (1,071 / 1,103 / 1,089 tok/s) and unmoved by the cache's format (q4_0 against
q8_0: 0.1 %).  llama.cpp's own binary, same file, same card, reads 15,000 tokens at 1,304 tok/s - so the engine is at
81 % of the reference that shares its kernels, and both are on the same instruction class: IQ3_XXS comes down
ggml_cuda_dp4a on CUDA cores, while AryaNinfer dequantizes its 3-bit groups and multiplies on FP16 tensor cores.

The tensor-core route was built and measured three ways rather than assumed.  llama.cpp's per-type dequantizers
(convert.cu, ggml_get_to_fp16_cuda) turned a matrix into a half buffer and cuBLAS's FP16 product replaced the integer
tiles for a batch: **827.3 tok/s** on the 20,051-token prompt against MMQ's 1,064.3.  Rewriting the dequantization as
eight warps a CTA over llama.cpp's dequantize_iq3_xxs arithmetic gave **979.0**; adding 2,048-token batches, **1,030.9**
at 14,059 tokens against MMQ's 1,102.6.  Every variant lost, and the path was reverted.

The cause is the shape of the work: the conversion runs again for every batch, so a prompt dequantizes all 10.4 GB of
weights once per 1,024 tokens and writes them again as halves.  The matrix product itself was the fast part (the 20K
prompt's 1.08 PFLOP in about 13 s of the 24 s run, roughly 83 TFLOPS), while the conversion of the same weights over
and over is what the tensor cores could not pay for.  llama.cpp's 1,304 comes from the same cuBLAS route with its own
dequantization and 2,048-row batches; ours, at the batch sizes this card has VRAM for, does not reach it.

What would close the gap is the fused design AryaNinfer uses: the 3-bit tile dequantized in shared memory inside the
matrix product, so weights cross the bus once per prompt rather than once per batch.  That is a new kernel - a tiled
matmul over IQ3_XXS with the dequant in its inner loop - not a wiring change, and it is not in this tree.

## Against AryaNinfer on this host (the same model, the same card, 2026-11-02)

Our own fork of the sm_89 NInfer (KonnectSuite/AryaNinfer, upstream roofkid/ninfer-4080) runs the same model from
roofkid's GSQ3 artifact, so it is the reference for the engine's speed rather than a different design on paper.  The
same 20,051-token prompt and 64 greedy tokens, both engines alone on the card:

| | AryaNinfer (GSQ3, rk4v4-e8 KV) | strata-poly (IQ3_XXS, q8_0 KV) |
| --- | --- | --- |
| prefill | **2,000 tok/s** (10.0 s) | 1,064 tok/s (18.8 s) |
| decode | **173.5 tok/s** (363 ms) | 72.0 tok/s (889 ms), 75.5 after the deeper window |
| tokens a model pass | **7.0** (MTP 91.5%, n-gram 90.9%) | ~3.5 (48 of 55 guesses accepted) |
| time a pass | 40 ms | 44 ms |

The two gaps have different causes, both measured:

- **Decode is tokens a pass, not time a pass**: the pass costs nearly the same on both engines (40 vs 44 ms); theirs
  commits seven tokens from one pass (MTP3 plus its n-gram chain), ours three and a half.  Raising the block's guess
  ceiling from 4 tokens a window to 8 (the policy still times whether each deeper guess pays) moved ours from 72.0 to
  75.5 tok/s; --lookup 8 moved nothing, because our chain is MTP-dominated while theirs drafts whole n-gram chains.
- **Prefill is the matmul's instruction class**: IQ3_XXS comes down ggml_cuda_dp4a in the vendored kernels - CUDA
  cores - while AryaNinfer dequantizes its 3-bit groups and multiplies on FP16 tensor cores.  That it is not attention
  was checked here: the same prompt with a q4_0 cache instead of q8_0 changed prefill by 0.1% (992.8 against 991.5
  tok/s).

What would close the rest: a tensor-core (FP16 MMA) matrix path for the 3-bit weights with the dequant on the fly -
AryaNinfer's Q3G128_F16S and packed kernels - and a cheaper draft pass (their dedicated draft head and chained n-gram
proposals), which is where the seven tokens a pass come from.

## Against llama.cpp (the repo's own verification standard)

`tools/qwen38_llama_compare.py` drives llama.cpp's own binaries - built from `third_party/llama.cpp` with the same
CUDA toolkit (`build-env/build-llama.cmd`: llama-completion for the reply, llama-debug --save-logits for the
logits of the prompt's last token) - against strata-poly on this file, five prompts, greedy, 64 tokens.

Measured 2026-11-02 (IQ3_XXS-mtp, q8_0 cache, this host):

- **Its tokenization is ours to the id** on all five prompts (	oken ids: 9419, 0, 733, ... for the first).
- **Its five likeliest ids at the first step are ours within 0.0031**, the order exact on three of the five; where
  the order differs it is the fifth-place token, at a tie (0.0007 and 0.0031 of probability).
- **The replies are the same up to the first near tie**: 30 tokens and then the reply's end on the greeting (30 on
  our side is the end-of-reply token, which llama.cpp's sampler hides and stops at), 58 on the colours, 27 on the
  haiku, 33 on pi, and all 4 tokens of the short arithmetic answer (17 x 23 is 391 on both).

That is the same shape the other rows of docs/BACKENDS.md have: two correct implementations part where a near tie
falls the other way, because activations are quantized to 8 bits at every quantized matrix in a layout each kernel
chooses.

## The 4-bit cache: what is in and why it had to go where it did

--kv q4_0 is ggml's Q4_0 block (a fp16 scale and 16 bytes of nibbles for 32 values; value = (nibble - 8) * d), and
the store side follows llama.cpp: d = max / -8, nibbles of rint(x / d + 8), the low nibble the block's first 16.

What landed:
- Kvq4 (include/strata/poly/kernels.hpp), store_q4() / store_q4_at() (src/poly/kernels.cu).
- The generic decode path, which is the one this model uses: ttn_score_kernel<KV> and ttn_value_kernel<KV> take
  a KV of 0 fp16, 1 q8_0, 2 q4_0; a q4 value is read with q4_code() (the byte v % 16 of its 32-value block, the
  low nibble under 16).  dequant_q4_kernel() beside dequant_q8_kernel() does the same for ttend_batch()'s fp16
  workspace, so a prompt batch reads a q4 cache too.
- ttend() / ttend_batch() take a kvmode; Qwen35 passes 2 for a q4 cache.  The cache allocation, the
  checkpoint save/load of rows, and ttn_store() are sized half of q8_0's codes.
- The flash path has q4 support as well (dequant_q4_kernel + 
un<Group, KV>, attn_q4(), and on the decode side
  dec_kernel<MT, KV, Group> with a 
ib4() that turns a q4 byte into the int8 code the tensor cores take:
  
ibble + 120 is (nibble - 8) ^ 0x80, which i8pair() biases down).  **This model never takes it**: the flash
  kernels need a group of 8 or 16 heads a KV head and the 27B has 24 over 4, **6 a group**.

A bug the work turned up, fixed: the softmax writes the value weights transposed for ttn_value_t_kernel, and a q4
value kernel reads them in place - so with a prompt batch of 32 or more (where the transposed copy fits) the answer
came out as repeated tokens.  ttend() now keeps the plain layout whenever kvmode == 2.

Correctness: the 16-token greedy answer on Hello! In one sentence, what are you? is **token for token the same on
q8_0 and q4_0** (271,40,1044,264,30894,321,23739,14791,17313,5995,310,1438,488,440,264,6669), and the picture test
reads the card and answers 4711 on both.

## Where it stands

Done and measured on this host:

- The engine: dense qwen35 in strata-poly - Engine::open() dispatch, load_shape(false), the dense FFN, the
  draft block's dense branch (Engine::draft_ffn(), whose default is the MoE sequence the block always ran), and the
  prompt-batch MMQ handle for a model with no experts (6.8x the prompt speed).  CUDA sm_89 build, verified by the
  smokes and the needles above.
- The 4-bit cache: --kv q4_0 on the generic attention path (which is the one this model takes, 6 heads a group),
  with the flash path carried too.  The greedy answer is identical to q8_0's, token for token.
- Context: 32K q8_0 and 64K, 96K, 128K and **200,069 tokens** on q4, each with the needle found.  The 120K attempt at
  the default batch stalled, which was the batch's scratch, not the cache: 128K on the same file fits with
  `--prompt-batch 256` (measured 574.9 tok/s reading, 51.6 writing, 15,661 MiB).
- Vision: the 27B mmproj loads in strata-vision (llama.cpp mtmd, --min-tokens 1024), the engine takes its .sve
  through --images/--image-pad, and the server answers picture questions on both caches.
- Registry: serve/models.py knows qwen35; models.json lists the two entries; two run configs are in the repository
  root, named the way the MoE families are - "AryaStrata Qwen3.8 27B IQ3_XXS - 128K vision"
  (`strata-qwen3.8-27b-iq3_xxs.json`, 131,072 tokens on q4_0 with `--prompt-batch 256`) and "AryaStrata Qwen3.8 27B IQ2_S - 200K vision"
  (`strata-qwen3.8-27b-iq2_s.json`, 204,800 tokens, q4_0, `--prompt-batch 256`); the tokenizer was extracted from the
  file with `tools/strata_tokenizer.py`.

The installer: setup.py --family qwen38 is in, with dense_poly_setup() for a model with no experts (poly_setup() hands a dense family to it).  It pins the repository revision (d562806d...), the two files and the image encoder by size and SHA-256, and it plans the card from the measurements above: dense_poly_plan() gives a 16 GB card 200K with a q4_0 cache and --prompt-batch 256 on IQ2_S (predicted 16,020 MiB, measured 15,942) and 96K on IQ3_XXS (predicted 15,352, measured 15,351), refuses a context past what was measured, and refuses a 12 GB card with what to do instead.  tools/test_setup_qwen38.py covers the family, the plan and the whole config it writes (the engine step mocked, the real file on disk), and the repo's own setup tests (pins, config, custom-gguf, menu, golden, gguf-models) stay green.

Known limits, measured: decode at 200K is 14.6 tok/s on the group-6 flash kernel (5.3 on the generic one it replaced),
and NInfer's integer-MMA attention is the reference for the rest of that gap.
The docs/BACKENDS.md row and its evidence row (the section above), and the README row, are in.  Not done here, and
why: the agentic coding
suite (tools/arya_agent_bench.py - eighteen live sessions, hours of them; no claim of it is made for this model) and a
release build of strata-poly that includes the dense qwen35 work, without which the installer only helps on a machine
that can compile it (that is the release step).

## Speculative decoding: baseline and instrumentation (2026-11-02)

`tools/qwen38_spec_bench.py` drives the engine over its own stdin protocol (`GEN`), which is how the server feeds long
prompts without Windows' command-line limit.  Greedy (`temperature=0`), q4_0 cache, 256 new tokens, a filler prompt
ending in a request for a long answer.  `--report-drafts` now prints the acceptance at each guess position and the
round count, so the policy's choices can be checked against what actually happens.

| context | prompt | prefill | decode | tokens/round | accept by position (0..6) |
| --- | --- | --- | --- | --- | --- |
| 8K | 7,897 | 1,179 tok/s | 72.4 tok/s | 3.12 | .846 .787 .822 1.00 1.00 1.00 .80 |
| 32K | 31,997 | 1,016 tok/s | 65.5 tok/s | 3.05 | .800 .642 .659 .737 .909 .875 .857 |
| 64K | 63,997 | 843 tok/s | 64.1 tok/s | 2.98 | .840 .830 .711 .789 .857 1.00 1.00 |

The deep positions' rates rest on few rounds (4-19), so read them as indicative, not settled.  Two things stand out:

- the adaptive window settles at about 2.6 guesses a round, so positions 3-6 are reached only a handful of times;
- the first guess is accepted 0.80-0.85 of the time and the second 0.64-0.83, which is the EAGLE tree's point: it
  keeps alternatives alive at the first branch instead of spending the window on a chain that dies at position 2.

With these measured rates the EAGLE width formula (expected tokens `1 + Σ A_d` against the measured round time)
predicts 4.6-5.6 tokens for a window of 6-7 tokens against today's 3.0, which is exactly what Phase 1 and the tree
have to buy back against its extra cost.

## The measured width (Phase 1, opt-in)

`--spec-width measured` chooses the window from what the rounds measured instead of from the block's own
probabilities: a window of w tokens is expected to write `1 + A_0 + ... + A_{w-2}`, where `A_d` is the chance the
guesses through position d are all right (the rounds' own count, the position below's measured rate until the depth
has samples), over the measured time of a round of that window.  The counters print with `--report-drafts`.

Measured 2026-11-02, Q3 IQ3_XXS, q4_0 cache, 256 new tokens, same prompts as the baseline:

| context | default (block probabilities) | measured width |
| --- | --- | --- |
| 8K | 72.4 tok/s, 3.12 tokens/round | 63.8 tok/s, 2.25 tokens/round |
| 32K | 65.5 tok/s, 3.05 tokens/round | 65.2 tok/s, 2.64 tokens/round |
| 64K | 64.1 tok/s, 2.98 tokens/round | 62.1 tok/s, 2.64 tokens/round |

The measured width does not pay, so it stays opt-in and the default path is unchanged (re-measured after the change:
72.1 / 65.5 / 61.3 tok/s at 8K / 32K / 64K).  The reason shows in the counters: the default rule drafts deeper only
when the block is confident, and on exactly those rounds the second guess is accepted 0.79 of the time, while the
measured rule's uniform exploration measures 0.64.  Unconditional acceptance is the wrong statistic for a policy that
selects its rounds on confidence; the next version has to keep acceptance per confidence bucket, so that a guess the
block calls likely is weighed by what guesses like it did.

## The draft block's window (Phase 2, opt-in)

`--draft-window N` has the block that guesses ahead read only the last N tokens of context; the target's verification
is untouched.  The block proposes the next few tokens, and at a long context the cache beyond them is most of what
asking it costs.

Measured 2026-11-02, Q3 IQ3_XXS, q4_0 cache, 256 new tokens, same prompts:

| context | default (all of it) | window 2048 | window 8192 |
| --- | --- | --- | --- |
| 32K | 65.5 tok/s | 68.1 tok/s | - |
| 64K | 64.1 and 61.3 tok/s (two runs) | 66.3 tok/s | 66.6 tok/s |
| 128K | 60.7 tok/s | 57.9 tok/s | 62.4 tok/s |

Acceptance at 128K, by guess position: default .838 .817 .761 .800; window 2048 .835 .789 .644 .600; window 8192
.877 .797 .698 .696.  So 2048 saves the draft's reads but loses more in acceptance than it saves, while 8192 keeps
most of the acceptance and reads an eighth of the cache.

The differences are small: the same default 64K run measured 64.1 and 61.3 tok/s, so this host's round-to-round
variance is about 4%.  The window stays off (0) until a repeated measurement shows it plainly; when it is turned on,
8192 is the value to use.

## The tree (Phase 3, opt-in): built, exact, and not faster yet

`--tree K,D` guesses as a tree: K children a row (1-2) and D deep (1-2).  The block drafts it depth first, so its own
causal attention is the tree's mask (a sibling reuses its depth's row after its subtree's logits are taken).  The
target verifies every row in one pass: each row has its own cache row, stands at `pos() + depth` for the rotary
embedding, and sees the committed rows, itself and its ancestors, never a sibling.  The 48 gated delta net layers keep
a state for each row (from its parent's, the root's from the committed state), so the committed state is never touched;
`keep_tree()` commits the accepted path by replaying it, and rewrites the draft block's rows for it.

Correctness, which has to hold before anything else:

- a chain-shaped tree (`--check-tree`) gives the window's own top token at every row;
- `--check-topk` has the k likeliest head agreeing with the top-1, and the tree's own drafting path landing on the
  same guess;
- a real tree (`--tree 2,2`) generated the same 24 greedy tokens as the chain on the test prompt.

Speed, 2026-11-02, Q3 IQ3_XXS, q4_0 cache, 8K prompt, 128 new tokens:

| setting | decode | tokens/round | verify a round |
| --- | --- | --- | --- |
| chain (default) | 72.4 tok/s | 3.12 | ~39 ms |
| tree 2,2 (7 rows) | 22.7 tok/s | 2.61 | 65 ms |
| tree 2,1 (3 rows) | 28.8 tok/s | 2.30 | 38 ms |

The verify's cost is the gated delta net, per row: each row copies its parent's 3 MB state in every one of the 48 GDN
layers, and the recurrence runs a kernel a row.  The masked attention is 1-2 ms of it, and recording the layers'
launches (the graph replay) took the verify from 75 to 65 ms.  The tree's own drafting is not the cost (8-22 ms for
7 rows against the chain's 3-5 ms for 3 guesses).

So the tree stays off by default: with the state copies it costs more than the tokens it adds.  To make it pay, two
kernels would need writing, in this order:

1. the GDN recurrence for a tree's rows as one kernel over a state table (a parent index per row, no copies) - the
   per-row copies are what the measurements attribute the time to;
2. the ancestor mask in the `fdec` decode-attention kernel, so a tree's rows verify at the chain's kernel speed.

Until those exist the chain is the default and the benchmarks above are the case against turning the tree on.

## What the measurements came to (2026-11-02)

Round cost by window width, 8K prompt, Q3 IQ3_XXS, q4_0 cache, 128 new tokens:

| window | round | tokens/round | decode |
| --- | --- | --- | --- |
| 2 | 29.6 ms | 1.80 | 60.9 tok/s |
| 3 | 36.2 ms | 2.33 | 64.3 tok/s |
| 4 | 39.7 ms | 2.78 | 70.1 tok/s |
| 6 | 45.0 ms | 3.05 | 67.8 tok/s |
| adaptive (default) | ~43 ms | 3.12 | 71.8-72.4 tok/s |

A one-token step with no guesses is 23.8 ms (42.1 tok/s), close to the weights' bandwidth floor, so the marginal row
of a verify costs about 5 ms.  A guess pays when it adds more than about 5 ms of expected tokens; a tree's extra rows
add a token only when the main branch fails, and on this model they measure 1.5-2 ms of expected tokens.  That is the
arithmetic against the tree, and it does not depend on the tree's kernels: the EAGLE-4 tree wins on data-center
hardware where a verify row is cheap relative to a token, not on one 16 GB card where it costs a third of the weights'
pass.

Draft vocabulary, 8K: 65,536 rows 70.7 tok/s (3.20 tokens/round), 98,304 68.6 (3.12), the default 131,072 71.8 (3.1),
and 65,536 at 32K 68.0 against the default's 65.5-66.3.  The draft head is not the round's cost; the tuning window is
inside the run-to-run noise.

Phase 4 notes:

- the recorded layers' graph key already carries the window width (`key{block_pass_ ? -n : n}`), so no change was
  needed there;
- an L2 prefetch of the next matrix was assessed and not pursued: the per-row marginal is compute and L2-bound, and
  EAGLE-4's own warm-up is measured on a B300 whose L2 is far larger than this card's;
- a persisted cost profile was not needed: the policy re-learns its round times within the first ~30 rounds of an
  answer, which the 128-token benchmarks do not show as a loss.

What remains, if the tree is ever the priority: the GDN recurrence for a tree's rows as one kernel over a state table
(the per-row copies are the measured cost), and the ancestor mask in the `fdec` decode-attention kernel.  Even then
the arithmetic above says the tree would have to add more than ~5 ms of tokens per row to pay.
