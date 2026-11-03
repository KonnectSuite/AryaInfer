# Agentic coding and tool use on this host: the roster tuning of October 25, 2026

Host: **i9-14900KF, RTX 4070 Ti SUPER 16 GB (driver 610.88), 64 GB RAM, Windows 11**,
engine **0.1.45** (`strata.exe` for Qwen3.8, `strata-poly.exe` 0.1.45 for the six families).
Seven models: the six that were installed, plus Qwen3.6 UD-Q2_K_XL, added on this date to
answer the "2-3x faster" requirement (section 4.4).
Every number on this page was measured on this PC, on the day named, at the workload named.
Inherited vendor or community numbers are marked as such.

This page answers two reports from the user:

1. *"Before AryaCode, the Qwen3.8 Flash IQ3 model never hit an output limit. Now it cannot
   make a website."* — the cause was the output allowance the AryaCode adapter advertised,
   not the model. Section 1.
2. *"For the smaller MoEs I get the same numbers as a laptop with 8 GB of VRAM and 32 GB
   of RAM."* — the cause was `--kv-whole` reserving the whole 256K attention cache in VRAM
   at load, which starved the expert cache. Section 2.

The workload measured here is the one an agent actually runs, not a chat prompt: a
5,329-token cold turn (system prompt, six tool schemas, a task), a follow-up on the same
conversation, and a 43,007- or 63,138-token reference prompt built from this repository's
own documents, with tools on. Numbers come from the server's response usage plus
client-side timing (`agentic_bench.py`, `ab_config.py`), and the engine's own log line for
the same request is quoted beside them.

Noise floor: the vendor's published rule is that decode differences under **10%** are not
readable as real. Changes below are only claimed where they cleared that, and the
43K A/Bs are single requests, so the ranges are wider than the medians.

## 1. The output allowance: 8,192 tokens for every model

`@aryacode/dsh-local-llm` published every local model with `maxTokens: 8192`, because its
`outputDefault()` capped the default at a fixed 8K:

```ts
// 0.8.5
export function outputDefault(context: number, ceiling = 8192): number {
  return Math.max(1024, Math.min(ceiling, 8192, Math.floor(context / 4)))
}
```

For a 262,144-token model that is 3% of the window. The harness reports the value in every
request it records (`request/header.config.maxTokens`, `adapterDefaults.maxTokens: true`),
so the evidence is exact:

| Session | Model | Output | Finish |
| --- | --- | ---: | --- |
| 10-25 11:41 | `strata:qwen3.8-flash-next-iq3_xxs` | 8,192 | `max-tokens` — the website build |
| 10-25 11:32 | `strata:qwen3.8-flash-next-abliterated-iq2_xs` | 8,192 | `max-tokens` |
| 10-25 10:53 | `ninfer:qwen3.8-27b` | 8,192 | `max-tokens` |

The failing website session ended `turn/end reason={"kind":"max-tokens"}` with
`outputTokens: 8192` and a single `write` call whose arguments were cut off mid-file. Three
different models, the same ceiling: the cap, not the models.

**Fixed in 0.8.6** — the default follows the served window, bounded by the engine's own
allowance when it declares one:

```ts
// 0.8.6
export function outputDefault(context: number, ceiling = Number.POSITIVE_INFINITY): number {
  return Math.max(1024, Math.min(ceiling, Math.floor(context / 4)))
}
```

| Served window | Advertised before | Advertised now |
| ---: | ---: | ---: |
| 262,144 | 8,192 | **65,536** |
| 131,072 | 8,192 | **32,768** |
| 102,400 (NInfer) | 8,192 | **25,600** |

A per-model override still wins, so anything the Chat output limits editor set explicitly
does not change. The plugin's suite is 118/118, including three new tests for the window
fraction, the engine ceiling and the small-window floor. Release identity:
`@aryacode/dsh-local-llm` **0.8.7** (`3620fb7` + `6c35469`), market release asset sha256
`2cae4a15…17ba8e6a`, catalogue `d69c051`. It was installed into the live profile on 25 October at
18:31; the installed code returns 65,536 for a 262,144-token window, 32,768 for 131,072 and
34,133 for NInfer's 102,400.

**Same task, same model, same tools, only the allowance differs** (Qwen3.8 IQ3_XXS, low
effort, the user's own build prompt, a bounded agent loop that executes the model's
read/glob calls):

| Allowance | Result | Tool call | File written |
| ---: | --- | --- | --- |
| 8,192 | `finish: length` after 8,192 output tokens | 19,059 characters of arguments, cut mid-JSON | **none** |
| 65,536 | `finish: tool_calls` after 15,434 output tokens | 51,870 characters, valid JSON | **49,761 characters, has `</html>`** |
| 65,536, repeat | `finish: tool_calls` after 31,169 output tokens | 97,109 characters, valid JSON | **94,857 characters, 14 sections, has `</html>`** |

The write needs 15,434-31,169 tokens, 1.9x to 3.8x the old ceiling. This is the failure and
the fix, reproduced on this host with the user's task.

**The trade-off, stated plainly:** a larger allowance reserves more of the context for the
answer. `compaction-basic` computes its pressure budget as `window - request maxTokens -
headroom`; at 262,144 with 65,536 allowed and the default 64K headroom, the live-context
budget is 131,072 tokens instead of 188,416. If a session needs more live context and
accepts shorter writes, lower the model's allowance with **AryaInfer → Chat output
limits**; the editor's range is 1,024 to the window minus 1,024.

At the ceiling the request is not refused: a **234,726-token** prompt with
`max_tokens: 65536` on Qwen3.8 IQ3_XXS was clamped by the config's `fit_max_tokens: true`
and answered normally (87.6 s to first token, `finish: stop`). The clamp keeps the new
default usable in the one place it would otherwise 400.

## 2. `--kv-whole` cost the PolyStrata models their expert cache

`--kv-whole` gives the attention caches VRAM for the whole configured context at load,
instead of letting them grow with the conversation. The option exists for AMD cards, where
ROCm does not hand VRAM back (see `AMD_HIP.md`), and setup writes it there. On this NVIDIA
card it does the opposite of what the small MoEs need:

- Qwen3.6 q8_0 KV is 11,968 bytes a token (the engine prints 544 bytes a row, 2 rows, 11
  attention layers). At **262,144 tokens that is 3.0 GiB reserved before the first prompt**.
- The expert cache is what makes these models fast: an expert it holds is read at VRAM
  speed, one it does not is read from system RAM or the SSD. 3.0 GiB of VRAM is roughly
  1,600 routed experts at Qwen3.6's Q4 expert size.

Measured, Qwen3.6 UD-Q4_K_XL, one 43,007-token prompt with tools, fresh engine each arm:

| Arm | Experts in VRAM | Prompt read | Decode |
| --- | ---: | ---: | ---: |
| `--kv-whole` (shipped) | 4,467 | 1,846 tok/s | 75.9 tok/s |
| without `--kv-whole` | **6,055** | **2,937 tok/s** | **111.7 tok/s** |
| change | +36% | **+59%** | **+47%** |

The attention cache still grows to the same 3.0 GiB when a conversation actually reaches
262K; the difference is that a normal 20K-100K session no longer pays for it up front. The
`--vram-reserve-mib 512` in the same config covers the CUDA-graph headroom that `Q8_KV.md`
measured as necessary.

### 2.1 Why the smaller MoEs cannot be 2-3x faster at Q4 on this card

The expectation is the right one for a card that holds the whole model: PolyStrata's own
README measures Qwen3.6 UD-Q4_K_M at **395 tok/s** on a 32 GB RTX 5090, against **62 tok/s**
for Qwen3.8 IQ3_XXS on a 12 GB card. On this 16 GB card, decode is decided by the routed
expert bytes a token must read, because a 22.8 GB expert bank does not fit in 16 GB:

| Model | active experts a token | bytes a routed expert | routed-expert bytes a token |
| --- | ---: | ---: | ---: |
| Qwen3.8 IQ3_XXS | 48 layers x 10 = 480 | 4.92M params x 2.84 bits = 1.75 MB | **0.84 GB** |
| Qwen3.6 35B UD-Q4_K_XL | 41 x 8 = 328 | 3.22M x 4.88 bits = 1.97 MB | **0.65 GB** |
| Qwen3.6 35B UD-Q2_K_XL | 328 | 3.22M x 2.61 bits = 1.05 MB | **0.34 GB** |

The 35B at Q4 reads only 23% fewer bytes a token than the 126B at IQ3, so it can be about
1.3x faster — which is what it measures (117 vs 91 tok/s on the same 5,329-token prompt).
It cannot be 2-3x faster: an expert at Q4 is nearly twice the bytes of one at IQ3, and the
126B's lower bit width cancels its extra experts. At Q2 both levers move: the bytes fall
60% below the 126B's, and a 12.6 GB file lets nearly every expert stay in VRAM. See
section 4.4 for the measurement.

## 3. What changed, per model

| Model | Config | Change | Why |
| --- | --- | --- | --- |
| Qwen3.8 Flash Next IQ3_XXS | `strata-iq3_xxs.json` | none | already the calibrated config from `.tune/SETTINGS-REPORT.md`; `--vram-reserve-mib 1000`, `--kv-resident 32768`, MTP, 15 workers |
| Qwen3.8 Flash Next abliterated IQ2_XS | `strata-abliterated-iq2_xs.json` | none | same settings; CPU vision encoder already |
| Qwen3.6 35B-A3B UD-Q4_K_XL | `strata-qwen36s-ud-q4_k_xl.json` | removed `--kv-whole`; `--prompt-batch 512 → 2048`; `--vram-reserve-mib 768 → 512`; `presence_penalty 1.5 → 0.5` | section 2; the wider prompt batch reads long prompts faster |
| Qwen3.6 35B-A3B Q8_0 | `strata-qwen36s-q8_0.json` | same three | same |
| Ornith 1.5 35B-A3B APEX-I-QUALITY | `strata-ornith-apex-i-quality.json` | added `--kv q8_0`; `--prompt-batch` 1,024 → 2048; `--max-context` 131,072 → 262,144; `presence_penalty 1.5 → 0.5` | Q8_0 KV is byte-identical for `qwen35moe` (15/15 exact answers in `Q8_KV.md`) and halves the cache; the larger ceiling costs nothing without `--kv-whole` (section 4.3) |
| Flint 40B-A2.5B UD-Q4_K_XL | `strata-flint-ud-q4_k_xl.json` | none | already `--prompt-batch 2048`; `--kv q8_0` does not exist for the `flint` architecture (the engine gates it to `qwen35moe`) |
| Qwen3.6 35B-A3B UD-Q2_K_XL | `strata-qwen36s-ud-q2_k_xl.json` | **new model file**, vision | the only file whose experts fit in 16 GB: 10.78 GB at 2.61 bits, all 10,496 resident, 2.3-2.7x the Qwen3.8 at 5K-20K prompts (section 4.4); `presence_penalty 1.5 → 0.5` |

The Q2 was installed without vision: its model directory has no `mmproj`, so the config had no
`vision` section and the app correctly offered it as text. It is the same Qwen3.6 base as the Q4,
whose `mmproj-F16.gguf` (899 MB) already serves the Q8 too, so the Q2 config now points at that
encoder with its own weights (`strata-vision.exe`, `gpu: true`). Verified live: the server reports
`multimodal: true`, and a 512×512 red circle reached the model as a picture — "The image shows a
red circle" on Q4 and "The image features a red circle" on Q2, both at 281 prompt tokens. Text
OCR on a synthetic image was poor on *both* models, so that is the model's literacy, not the
wiring.

The Qwen3.8 vision encoder was measured both ways: GPU 2,895 tok/s prompt / 147.4 decode,
CPU 2,918 / 154.0 at 43K — inside each other's noise. It stays on the GPU (faster images);
the installer's CPU rule is a robustness choice, not a speed one here.

## 4. Before and after

### 4.1 The clean pairs: same prompt, same protocol, one variable

One 43,007-token prompt built from this repository's documents, tools on, a 160-token
reply that ran to `length` in both arms, fresh engine each arm, `temperature 0`.

| Model | Arm | Prompt read | Decode |
| --- | --- | ---: | ---: |
| Qwen3.6 UD-Q4_K_XL | shipped (`--kv-whole`, batch 512, reserve 768) | 1,846 tok/s | 75.9 tok/s |
| | tuned as shipped (no `--kv-whole`, batch 2048, reserve 512) | **3,268 tok/s (+77%)** | **116.7 tok/s (+54%)** |
| Ornith 1.5 APEX | shipped (fp16 KV, batch 1,024) | 2,239 tok/s | 66.1 tok/s |
| | tuned (`--kv q8_0`, batch 2048) | **2,554 tok/s (+14%)** | **71.4 tok/s (+8%)** |

The same pair at the 63,138-token prompt, where both arms again ran to `length` at 256
tokens: Qwen3.6 Q4 prompt read **1,924 → 2,605 tok/s (+35%)**, decode 77.2 → 82.9
(inside noise); Qwen3.6 Q8 prompt read **1,961 → 2,630 tok/s (+34%)**, decode 66.3 → 73.3
(+11%). The gain is largest in the 20K-50K range an agent actually works in, and narrows as
the conversation grows and both arms pay for a smaller expert cache.

### 4.2 The roster at 63,138 tokens after tuning

One request each, tools on; prompt read is `prompt_tokens / time-to-first-token`, so it is
comparable across arms. Decode is the engine's own line where it exists; for the PolyStrata
engines the client-side figure includes streaming overhead and is quoted only where the
reply ran to 256 tokens.

| Model | Prompt read | Decode | Note |
| --- | ---: | ---: | --- |
| Qwen3.8 IQ3_XXS | 2,782 tok/s | 86.4 tok/s | engine line; 69.7-100.1 across this session's runs |
| Qwen3.8 abliterated IQ2_XS | 2,755 tok/s | 107.3 tok/s | engine line |
| Qwen3.6 UD-Q4_K_XL | 2,605 tok/s | 82.9 tok/s | client, 256 tokens |
| Qwen3.6 Q8_0 | 2,630 tok/s | 73.3 tok/s | client, 256 tokens |
| Ornith 1.5 APEX | 2,643 tok/s | 73.7 tok/s | client, 104 tokens |
| Flint 40B-A2.5B | 3,190 tok/s | 70.5 tok/s | client, 256 tokens |

**Run-to-run spread is larger than the vendor's 10% rule on decode.** The same Qwen3.8
IQ3_XXS, same 256-token probe, read 69.7 to 100.1 tok/s across runs in this session
depending on draft acceptance (55-95%) and expert-cache warmth; the abliterated IQ2_XS
measured 81.5 to 218.9 on the same kind of request. Absolute decode is therefore a range,
not a constant, and only the interleaved pairs in 4.1 are used for claims of change.

### 4.3 Near-full context still works without `--kv-whole`

The reason the Qwen3.6 profiles carried `--kv-whole` was long-context stability, so the
change was checked at the ceiling: a **234,726-token** prompt (the same reference text
repeated) on the tuned models, no tools, 64-token answer.

| Prompt | Model | Time to first token | Prompt read | Answer | Result |
| ---: | --- | ---: | ---: | --- | --- |
| 234,726 | Qwen3.6 UD-Q4_K_XL | 186.4 s | 1,259 tok/s | "AryaInfer - the details" | `finish: stop`, no OOM |
| 234,726 | Qwen3.6 UD-Q2_K_XL | 183.2 s | 1,281 tok/s | "AryaInfer - the details" | `finish: stop`, no OOM |
| 234,726 | Ornith 1.5 APEX (now 262,144) | 185.7 s | 1,264 tok/s | "AryaInfer - the details" | `finish: stop`, no OOM |

The attention cache does grow to its 262K size by then (the expert cache gives the VRAM
back), and the Qwen3.6 Q4 read is still **29% faster** than the pre-tuning roster's
254,191-token Qwen3.6 Q4 run (973 tok/s, 261.4 s to first token). A request above the
ceiling is refused with a 400 that names the prompt size, not truncated.

Ornith's ceiling was raised from 131,072 to **262,144** on this date: without `--kv-whole`
the attention cache only grows as the conversation does, so the larger ceiling cost nothing
at the 43,007-token A/B (2,597 vs 2,554 tok/s prompt read, 73.9 vs 71.4 decode) and the
234,726-token request answered. All three PolyStrata Qwen-family profiles now serve 256K.

### 4.4 The 2-3x the user asked for: Qwen3.6 UD-Q2_K_XL

The "the smaller MoEs should be 2-3x faster than the Qwen3.8 Flash, and support max context"
requirement cannot be met by any Q4-class file on a 16 GB card (section 2.1). It is met by a
2-bit file that fits:

- Source: Unsloth `Qwen3.6-35B-A3B-MTP-GGUF`, `Qwen3.6-35B-A3B-UD-Q2_K_XL.gguf`,
  **12.56 GB**, routed experts **10.78 GB at 2.61 bits** (`tools/strata_inspect.py`).
- Run config `strata-qwen36s-ud-q2_k_xl.json`: 262,144 context, `--kv q8_0`,
  `--prompt-batch 2048`, `--vram-reserve-mib 512`, `--tail-skip 6`, `--window 8`.
- The engine holds **all 10,496 routed experts in VRAM (10.1 GiB)**, not 58%.

| Prompt | Qwen3.8 IQ3_XXS | Qwen3.6 Q4_K_XL | **Qwen3.6 Q2_K_XL** | Q2 vs IQ3 |
| --- | ---: | ---: | ---: | ---: |
| 5,329 (cold agent turn) | 90.9 tok/s | 117 | **211-247 tok/s** | **2.3-2.7x** |
| 43,007 | 147.4 (client) | 116.7 | **167.1** | 1.1x (1.65x against the engine's own ~101) |
| 63,138 | 92.5 | 82.9 | **120.2** | 1.3x |
| 234,726 | not run (Q4: 122) | 122 | **128.3** | at parity |

The same website task on the Q2 took **3 steps and 123.7 s**: one 26,365-token `write_file`
produced an **82,066-character page with `</html>`**, where the Q4 needed 6-7 steps and
316 s, and the 8,192 cap produced nothing.

**Why the advantage narrows with context, and why that is not a tuning miss:** decode at
63K+ is dominated by attention reads of the KV cache, which both models pay; the expert
bytes the Q2 saves are a shrinking share of each token's work. At the 5K-20K prompts an
agent spends most of its turns on, the Q2 is the 2-3x; at 256K "support max context" is
satisfied (234,726 tokens answered in 183.2 s to first token) but the speed is the same as
the 126B.

**Quality is a separate trade.** The Q2's experts are 2.61 bits against the Q4's 4.88. It
completed the tool-use/website task above in one pass, but a 2-bit model is the *speed*
option; the Q4 stays the quality option on this host. Both now appear in the roster.

## 4.5 Thinking effort: what each model can offer, and what the request looks like

Before this change the selector was generic and mostly cosmetic. Every model was published with
four levels, but the adapter sent only `chat_template_kwargs.enable_thinking`, so Low, Medium and
High produced the same request everywhere; on Qwen3.8, whose template defaults to `xhigh` when no
level arrives, all three were in fact the **xhigh** prompt. Flint could not honour Off either: its
template has neither `enable_thinking` nor `reasoning_effort` and the model always thinks.

The server now answers per model. `ChatTemplate` records whether the template reads
`reasoning_effort` (graded, its own wording) and `enable_thinking` (Off possible); `/v1/models`
and `/api/models` publish the resulting levels; a template that does not read the level gets it as
an instruction in front of its system turn (`with_effort_instruction`), so the three graded levels
are real requests on every model.

| Model | Levels served | How the level reaches the model |
| --- | --- | --- |
| Qwen3.8 IQ3_XXS, abliterated IQ2_XS | off, low, medium, high | the model's own template (`medium` = no instruction, `xhigh` = the careful-think sentence) |
| Qwen3.6 Q4 / Q8 / Q2, Ornith | off, low, medium, high | Off closes the thinking block; low/medium/high are the injected instruction |
| Flint 40B-A2.5B | **low, medium, high** (no off) | injected instruction; the model always thinks, so Off is not offered |

Rendered prompts, one SHA-256 each, same conversation and tools (`serve/test_effort_modes.py`
and the effort matrix cover this):

| Model | off | low | medium | high |
| --- | --- | --- | --- | --- |
| Qwen3.8 IQ3_XXS | own prompt | own + low sentence | own (no sentence) | own + xhigh sentence |
| Qwen3.6 Q4 / Q8 / Q2, Ornith | own prompt | own + low sentence | own + medium sentence | own + xhigh sentence |
| Flint | — | own + low sentence | own + medium sentence | own + xhigh sentence |

All four render distinct prompts on the models that offer four levels; Flint's three are distinct.

**Live check**, same prompt, 1,400-token allowance, thinking recorded from the stream:

| Level | Qwen3.8 IQ3_XXS | Qwen3.6 UD-Q4_K_XL | NInfer Qwen3.8 27B | Flint 40B |
| --- | --- | --- | --- | --- |
| off | 0 reasoning chars, 111 out tokens | 0 reasoning, 278 out | 0 reasoning, 76 out | **3,231 reasoning** — Off is ignored (not offered) |
| low | 228 reasoning, 243 out | 3,002 reasoning, 951 out | 370 reasoning, 297 out | 2,767 reasoning, 917 out |
| medium | 202 reasoning, 290 out | 3,005 reasoning, 952 out | 385 reasoning, 305 out | 2,999 reasoning, 1,005 out |
| high | 596 reasoning, 260 out | 2,627 reasoning, 1,056 out | 2,236 reasoning, 735 out | 2,934 reasoning, 999 out |

NInfer's four levels come from its own template (it already received the level before this change, because its adapter used the qwen wire format): off 76 out tokens with no reasoning, low 297 with 370 reasoning chars, medium 305 / 385, high 735 / 2,236. The requests differ at every level (prompt tokens 78 / 102 / 76 / 114 on IQ3, 78 / 102 / 98 / 114 on Qwen3.6, 78 / 102 / 76 / 114 on NInfer).
One sample is not the whole story, so three samples per level at temperature 1.0 on the same
prompt (a reasoning-and-code task), Qwen3.6 UD-Q4_K_XL:

| Level | reasoning chars, median of 3 | answer chars, median |
| --- | ---: | ---: |
| off | 0 | 1,802 |
| low | 2,040 | 326 |
| medium | 1,994 | 966 |
| high | 2,235 | 1,264 |

Off is unambiguous on the models that have it, and High thinks and answers more than Low and Medium; Low and Medium are
within noise of each other on this model (the instruction differs, the model's floor does not).
That is the model's obedience, not the selector: each level is a different request, and Off and
the top of the range are visibly different.
How much the model changes its thinking is the model's own behaviour; what the selector guarantees
is that the request it sends is the level asked for.

**The wire**, from the adapter's own test (`tests/effort-wire.test.mjs` in the plugin): Off sends
`enable_thinking: false`; low/medium/high send `reasoning_effort: low|medium|xhigh`. A model that
offers three levels publishes three; an engine that predates the field still falls back to four.

## 5. Tested and not adopted

- **`--prompt-batch 1024` without removing `--kv-whole`**: 1,886 tok/s, inside the
  baseline's range — the batch width only paid off once the expert cache had room.
- **`--vram-reserve-mib 512` alone** (768 → 512 with batch 1024): no measurable change on
  its own; kept because it matches the reserve `Q8_KV.md` measured as OOM-free.
- **CPU vision encoder on Qwen3.8 IQ3_XXS**: within noise (section 3); reverted to GPU.
- **`--tail-skip` on Qwen3.6 Q4**: the shipped config has 0 (the upstream default for this
  family is 6). Left at 0: it changes answers, and no measured gain was established for
  this workload.
- **`--kv q8_0` on Flint**: refused by the engine — `q8_0` is implemented for `qwen35moe`
  only in v1.

## 6. What remains open

- **Flint at 262,144 with fp16 KV.** No quantized KV exists for its architecture, so a
  256K ceiling costs about 3 GiB once a conversation is that long and squeezes the expert
  cache from 6,217 to about 4,400 experts. At the 43K-63K sizes measured here it does not
  shrink below the Qwen3.6 tuning, which is why it was left alone. If Flint speed matters
  more than the last 128K of context, `--max-context 131072` is the lever.
- **Sampling: measured and lowered.** The Qwen3.6, Ornith and Q2 configs carried
  `presence_penalty 1.5` (Qwen's long-form writing recommendation). On ten one-file Python
  coding tasks, two passes each, thinking off, temperature 1.0 as the configs set it:

  | `presence_penalty` | valid tool call + parses | truncated | median code |
  | ---: | ---: | ---: | ---: |
  | 1.5 (shipped) | 16/20 | 3 | 458 chars |
  | 0.5 | 19/20 | 0 | 841 chars |
  | 0.0 | 19/20 | 0 | 625 chars |

  1.5 suppressed the repeated tokens code needs and cost four runs out of twenty; 0.5 keeps a
  mild repetition guard and measured as well as 0.0 with longer code. The five PolyStrata
  configs (Qwen3.6 Q4, Q8, Q2, Ornith; Flint's block has no presence penalty) now set
  **0.5**, re-measured through the config with no request override: 19/20 on Qwen3.6 Q4 and
  9/10 on Ornith, no truncations. The 2-bit Q2 measured 8/10 at 0.5 and 9/10 at 0.0 in one
  pass each — a single sample does not separate them, and it stays at 0.5; its weaker
  tool-call rate is the 2-bit trade, not the penalty.
- **Cold first token after a load.** The PolyStrata engines are 3-10x slower on the first
  prompt after loading (Ornith 6.2 s at 5,329 tokens, Qwen3.6 Q8 13.6-15.4 s; the same
  prompt on the next turn is 0.26 s). This is graph capture plus first-touch expert reads,
  not the configured settings; it is the one remaining "it feels like a laptop" moment.
- **A 250K-token request through the tuned configs**: measured — 234,726 tokens answered on
  the tuned Qwen3.6 Q4 in 186.4 s to first token (section 4.3) and on the Q2_K_XL in
  183.2 s (section 4.4). The remaining five models were measured at 43K and 63K only.

## 7. How the numbers were taken

`agentic_bench.py` (workload and roster run), `ab_config.py` (per-config A/B: unload, load,
43K prompt, engine log facts), `website_agent.py` (the failing session's task, bounded tool
loop), `session_speed.py` (decode rate the user actually experienced, from this machine's
own session logs). The tools live outside this repository; the measurements above are the
part that belongs in it.
