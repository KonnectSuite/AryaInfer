# 8-bit model set: AryaInfer host results

Measured on the i9-14900KF, RTX 4070 Ti SUPER 16 GB, 64 GB DDR5, Windows 11 (10.0.26200) host with NVIDIA
driver 610.88. AryaInfer 0.1.45, commit 4820a00e, the pre-built `strata-poly` engine. AryaInfer is a fork of
PolyStrata (VecSzn), which is a fork of Niko1221's original Strata. See [credits](../CREDITS.md).

## What changed

The installed 4-bit files for Ornith 1.5, Tiel Coder, MiniCPM-V 4.7, Gemma 4 and LFM2.5 were replaced with 8-bit
files of the same families, and their 4-bit profiles were uninstalled. Qwen3.6-35B-A3B `UD-Q4_K_XL` and the native
Qwen3.8 `IQ3_XXS` were kept: one for further testing, one because it runs the first engine. Only Ornith was measured
on both quants before the 4-bit files were removed, so it is the only pair in this report; the other four rows are
8-bit results with no 4-bit counterpart measured on this host, and none is claimed.

Every run uses the family's own run config: 262,144-token context (131,072 for LFM2.5), the whole KV cache in
`q8_0`, one conversation slot, 15 threads, and the expert profile carried over from the 4-bit pack — the profile is
an expert use count, not a size, so it describes the same routing for either file width. Gemma 4 is the exception
without a `--kv` argument, and it runs its own 0.46 GB draft model. Tiel Coder's profile adds `--tail-skip 6`, the
one change [tuning](#tuning) kept; every other family runs the settings it was installed with.

| Family | File | Size | Decode tok/s | First token | 4K prompt | 16K prompt | Agent turn decode | Agent cache hit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Ornith 1.5 35B-A3B | `Ornith-1.5-35B-Q8_0.gguf` | 37.80 GB | 107.8 | 0.278 s | 1,358 | 2,615 | 115.4 | 68.2 % |
| LFM2.5-24B-A2B | `LFM2.5-24B-A2B-Q8_0.gguf` | 25.49 GB | 96.8 | 0.214 s | 2,642 | 5,970 | 99.5 | 67.5 % |
| MiniCPM-V 4.7 35B-A3B | `MiniCPM-V-4_7-35B-A3B-Q8_0.gguf` | 36.90 GB | 83.2 | 0.263 s | 1,366 | 2,541 | 93.6 | 68.8 % |
| Gemma 4 26B-A4B | `gemma-4-26B-A4B-it-Q8_0.gguf` | 26.86 GB | 68.0 | 0.408 s | 1,736 | 3,461 | 76.9 | 67.5 % |
| Tiel Coder 35B-A3B | `Tiel-Coder-35B-A3B-UD-Q8_K_XL.gguf` | 38.45 GB | 82.6 | 0.738 s | 558 | 675 | 84.4 | 69.5 % |

Tiel Coder's row is its tuned profile; [as installed before tuning](#tuning) it measured 66.3 tok/s, 472 and 568
tok/s for the prompts, and 67.2 for the agent turn.

Decode and prompt speeds are medians from `tools/strata_bench.py --runs 3` — nine short chat answers of 100
tokens, and three runs each at roughly 4,000 and 16,000 prompt tokens. The agent figures come from the same tool's
six-turn tool session. These are bounded fixtures and engine counters, not a general quality or throughput score,
and the numbers move with the conversation cache state as the notes below say.

## Guessing ahead

Four of the five files carry a draft block, and the engine runs it: `--window 8` asks it for up to eight tokens a
step and keeps the ones that match. LFM2.5 has no block in its file, so nothing is guessed for it.

| Family | Where the block comes from | Tokens accepted in the agent session | Decode tok/s |
| --- | --- | ---: | ---: |
| Ornith 1.5 | in the model file | 460 of 594 (77.4 %) | 107.8 |
| Gemma 4 | its own `mtp-gemma-4-26B-A4B-it-Q8_0.gguf` (`--draft-model`) | 513 of 708 (72.5 %) | 68.0 |
| MiniCPM-V 4.7 | in the model file | 41 of 79 (51.9 %) | 83.2 |
| Tiel Coder | in the model file | 26 of 69 (37.7 %) | 82.6 |
| LFM2.5 | none | — | 96.8 |

Acceptance is the share of offered tokens the model agreed with, summed over the six agent sessions; it is what
speculation is worth to a family, and it is why Tiel and MiniCPM-V gain less from it than Ornith does. The table
also corrects an inherited row: MiniCPM-V 4.7 does offer drafted tokens here, where the backend table still says it
answers one token at a time.

## Ornith: the only pair measured on both quants

Both runs are the same run config, the same session, and the same day; only the model file and the pack that holds
its expert profile differ.

| Measure | APEX-I-QUALITY Q4 | Q8_0 | Change |
| --- | ---: | ---: | ---: |
| Short-chat decode | 92.4 tok/s | 107.8 tok/s | +16.7 % |
| First token | 0.324 s | 0.278 s | −14.2 % |
| 4K prompt | 1,279 tok/s | 1,358 tok/s | +6.2 % |
| 16K prompt | 2,429 tok/s | 2,615 tok/s | +7.7 % |
| Agent turn decode | 112.7 tok/s | 115.4 tok/s | +2.4 % |
| Agent cache hit | 68.19 % | 68.19 % | 0.0 |

The larger file is the faster one here: the 8-bit weights stay inside the batched integer path the engine compiles
for, and the expert cache hits the same rate either way, so the extra bytes cost nothing that this card notices.
That is one family on one card, and it is not a claim that 8-bit is faster in general — Qwen3.6's own report records
its Q4 file ahead of its Q8 file, 151.2 against 97.2 tokens/s, measured with a different suite.

## Tiel Coder needed a setting changed

As installed, Tiel decoded at 66 tok/s and read a 4,000-token prompt at 472 tok/s where Ornith does 1,358 — the
same architecture, one layer fewer, the same 256 experts and the same config shape. Three measured causes, one of
them fixable:

- **Guessed tokens**: Tiel's in-file draft block lands 26 of 69 guesses (37.7 %) where Ornith's lands 460 of 594
  (77.4 %). Speculation is most of a fast answer on this card, and a weak draft block is not something a flag fixes.
- **BF16 experts**: the `UD-Q8_K_XL` mix keeps six expert tensors, across four layers, in BF16 — 3.2 GB of its
  35.7 GB of experts. `STRATA_POLY_MMQ_TYPES` (`src/poly/mmq.cu`) has no BF16 entry, so those layers leave the
  batched expert path. A plain all-`Q8_0` file would not have them; peculiar-ragdoll publishes only UD mixes for
  the 8-bit size.
- **Expert streaming**: 12.5 GB of the card takes about 30 % of Tiel's experts, and its router spreads the four it
  picks more evenly than Ornith's, so the expert ranked last of the four is often the one that is not in VRAM and
  has to be read every token. `--tail-skip 6` leaves that one out when the window of tokens agrees it is last;
  [the tuning section](#tuning) measures what that recovered — 66.3 to 82.6 tok/s decode.

The expert cache hit is not the cause: 69.5 % in the agent session, the highest of the five.

## Quality checks

Each family ran the same bounded suites: nine coding-agent sessions (six fixtures, three runs), twelve image checks
(four fixtures, three runs), and recall at 65,536 and 131,072 actually-sent tokens.

| Family | Coding agent | Images | Recall 65,536 | Recall 131,072 |
| --- | --- | --- | :---: | :---: |
| Ornith 1.5 | 9/9 | 12/12 | PASS | PASS |
| MiniCPM-V 4.7 | 9/9 | 12/12 | PASS | PASS |
| Gemma 4 | 9/9 | 12/12 | PASS | PASS |
| Tiel Coder | 9/9 | 8/12 | PASS | PASS |
| LFM2.5 | see below | none: text only | 0/3 | 1/3 |

- **Tiel's four image misses are one repeated mistake**: asked for the build ID it answers `ARYA-507` where the
  image says `ARYA-5907`, in both the single-image and two-image fixtures. Shapes, colours, chart values, file name,
  line number and expected token were all read correctly.
- **LFM2.5 always reasons**, so the fixed-budget suites are a diagnostic rather than its deployment: at 1,400 output
  tokens per call it answers the coding fixtures with an absolute `/workspace/` path, which the fixture harness
  rejects before the edit happens. Its corrected probe is below.
- The recall rows are three prompts per length with different nonces, each carrying three facts at the 10 %, 50 %
  and 90 % points of the filler. Every failure recorded here is the middle fact; the first and last were found.
  LFM2.5's 131,072 row is 122,880 because its own context setting stops there.

### LFM2.5 with its deployment settings

The October 18 [roster report](MODEL_ROSTER_HOST_RESULTS.md#lfm-native-thinking-deployment-correction) records the
probe the 4-bit file needed: native thinking, a 4,096-token answer budget, and an explicit path contract in the
system prompt. The same three changes were replayed against the 8-bit file with the same fixtures, the same system
suffix, and recall prompts checked against their saved SHA-256 before sending.

| LFM2.5 native-thinking probe | Q4 `UD-Q4_K_XL` | Q8_0 |
| --- | ---: | ---: |
| Coding | 18/18 | 18/18 |
| Recall | 2/6 | 1/6 |
| Long agent (106,511-token repo) | 0/3 | not repeated |

Both quants answer the coding fixtures once the path contract is in the prompt, and both find the first and last
fact of the recall prompts while missing the middle one at most lengths. Two of six against one of six is not a
ranking: the roster report's own LFM rows were 2/6, and six prompts cannot separate these files.

## Tuning

One knob at a time, same file, same day, one bench run per candidate (`local-data/q8-migration/tune.py`). The
installed profile is the base row; every other column changes one argument on a copy. Tiel Coder, decode tok/s:

| candidate | base | tail-skip 6 | draft-vocab 0 | cpu-share 0 | stage-ahead 2048 | threads 24 | vram-reserve 512 | batch 1024 | window 4 | stage 4096 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| decode | 66.6 | **81.0** | 71.2 | 70.0 | 68.9 | 68.5 | 67.5 | 66.5 | 66.7 | 65.5 |
| agent turn decode | 61.7 | **77.1** | 59.9 | 62.1 | 62.2 | 63.3 | 63.2 | 60.1 | 61.5 | 63.9 |
| 16K prompt | 590 | **686** | 608 | 600 | 595 | 632 | 600 | 603 | 587 | 607 |
| first token, s | 0.81 | **0.72** | 0.77 | 1.58 | 0.78 | 0.76 | 0.78 | 0.80 | 0.80 | 0.78 |

`--tail-skip 6` is what setup already gives Qwen3.6: an expert that is not in VRAM and that every token of the
window ranks at place 7 or later among its four chosen is left out of the sum. On Tiel it is worth **+21.6 %**
decode and **+16 %** prompt reading, because Tiel is the family whose expert cache misses most, and this is the one
knob that removes work instead of moving it. It can move answers, which is why the checks below were re-run on the
tuned file rather than assumed.

Rejected: `--cpu-share 0` buys 5 % of decode for a doubled first token; `--draft-vocab 0` buys 7 % of decode and
loses 3 % of the agent turn; `--stage-mib 4096` is neutral. Two values were refused by the engine itself, worth
recording: `--window` takes 1 to 8 (or 0 for the model's own) and `--expert-swaps` takes 0 to 64.

### The same knob on the other four

Paired runs, three bench runs a side, one session each, so each row compares two profiles of one file rather than
two days:

| Family | decode, base | decode, tail-skip 6 | agent turn, base | agent turn, tail-skip 6 | Adopted |
| --- | ---: | ---: | ---: | ---: | :---: |
| Ornith 1.5 | 98.4 | 108.4 | 95.4 | 110.8 | no |
| Gemma 4 | 65.9 | 71.7 | 79.8 | 77.2 | no |
| MiniCPM-V 4.7 | 83.9 | 88.4 | 88.2 | 94.2 | no |
| LFM2.5 | 88.7 | 90.9 | 99.4 | 106.3 | no |
| Tiel Coder | 66.6 | **81.0** | 61.7 | **77.1** | yes |

Only Tiel's gain survives a second look. The paired run put Ornith 10 % ahead, but a full re-run of the same tuned
profile through the suite measured 107.6 tok/s against 107.8 for the untuned profile — and the untuned profile has
itself measured 107.8 in one session and 98.4 in another, which is the size of the effect being claimed. So Ornith
keeps its profile, and the same reasoning retires Gemma 4 (whose agent turn got slower), MiniCPM-V and LFM2.5
(both under 7 %, inside the spread). Tiel's +24.6 % was reproduced in three separate runs — 66.3 untuned, 66.6
untuned, 82.6 tuned — so it is the one that is not noise.

Turning the knob off again is one argument in the run config; nothing is baked into a pack or a model file.

## Tuned file checks

| Tiel Coder, `--tail-skip 6` | before | after |
| --- | :---: | :---: |
| Coding agent | 9/9 | 9/9 |
| Images | 8/12 | 8/12 |
| Recall 65,536 / 131,072 | PASS / PASS | PASS / PASS |

The four image misses are the same fixture and the same wrong build ID as before tuning, so tail skipping changed
nothing about what that file gets wrong. The same checks were run for Ornith on the tuned profile before its speed
gain failed to reproduce: 9/9 coding and 11/12 images, the miss being the `build-screen` fixture that also failed
once out of twelve in the untuned first pass.

## Reproducing

The scripts that produced this are kept beside the raw reports, in
[bench/results/2026-10-18-q8-migration/tool-snapshots](../bench/results/2026-10-18-q8-migration/tool-snapshots/):
`make_q8_configs.py` (the run configs, cloned from the 4-bit ones), `run_suite.py` (one family end to end),
`compare.py` (these tables from the JSON), `tune.py` (one knob at a time), `lfm_probe.py` (the LFM2.5 probe),
`set_arg.py` (changes one argument in a run config) and `draft_rates.py`. They read the model store under
`C:\AI\Strata-data` and the runner scripts in `tools/`. Raw reports are under
[bench/results/2026-10-18-q8-migration](../bench/results/2026-10-18-q8-migration/SUMMARY.md) — per-suite `results.json`
with medians, ranges and per-run rows.

The first run after the PC starts reads the model file from disk again; the engine's own docs say to run the
benchmark twice and keep the second. Every row above is a warm run, and the raw reports keep the cold ones.

## What this does not say

- Nothing here is a quality ranking between families. The fixtures are small and bounded, several sit at a ceiling,
  and four of the five rows have no 4-bit counterpart on this host to compare against.
- No number compares `strata-poly` with llama.cpp on this host. The engine's [backend
  notes](BACKENDS.md#benchmark) keep the older comparison, which was not measured here.
- Context capacity is a configuration, not a measurement: every family except LFM2.5 is configured for 262,144
  tokens, and the recall rows record the tokens actually sent.
- The installer cannot reproduce this set. `setup.py` offers 4-bit, 3-bit, APEX or 6-bit files for four of these
  five families, so these run configs, packs and downloads were assembled by hand; a setup on another PC installs
  what [AI_SETUP.md](AI_SETUP.md) describes, not what is measured here.
