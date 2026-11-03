# AryaStrata

AryaStrata is KonnectSuite's fork of [PolyStrata](https://github.com/VecSzn/PolyStrata),
which is a fork of [Niko1221's original Strata](https://github.com/Niko1221/Strata).
See [credits](../CREDITS.md). This fork will
track configuration and changes against measurements on our own hardware.
Inherited benchmark reports remain attributed to their original machines and authors.

## First target machine

Detected locally on October 17, 2026. The user confirmed this PC as the target,
with coding and local coding agents as the first priority.

| Component | Detected hardware |
| --- | --- |
| CPU | Intel Core i9-14900KF, 24 cores, 32 logical processors |
| GPU | NVIDIA GeForce RTX 4070 Ti SUPER |
| GPU memory | 16,376 MiB reported by NVIDIA |
| NVIDIA driver | 610.88 |
| System memory | 63.82 GiB reported by Windows |
| Storage | WD Blue SN580 2TB SSD, 1,863.02 GiB capacity |
| OS | Windows 11 Home, version 10.0.26200 |

The initial inspection found Python 3.11 installed. CMake and nvcc were not
found on PATH; this does not establish whether they are installed elsewhere.
NVIDIA reported about 14,899 MiB of GPU memory occupied during inspection.
That is an observation of an active desktop, not a benchmark or available-memory target.

Starting source revision: `dc2080ba16d7f9f644cd01c3d5ff3237b2ae0f85`. On October 23, 2026 the tree merged
PolyStrata 0.1.45-poly.3 (`f096adb0`) as `986a4fe2`, which brought Flint 40B-A2.5B, the `STRATA_GDN_MMA`
linear-attention kernel, `--check-batch`, `--kv int8` and the setup fixes.

## Establish our baseline

The [Qwen3.6 Q4/Q8 host comparison](QWEN36_HOST_RESULTS.md) validates both
quants on PolyStrata's backend at 262,144-token capacity with GPU vision and
Q8-compressed KV. Each passed 36 bounded coding sessions, 12 image checks,
6 recall trials, 3 long-context coding/image sessions, and 3 development DSH
adapter checks. The longest text input was 254,191 tokens; the combined
coding/image input began at about 230,827 tokens, leaving room for tool turns.
Both retained 15 CPU threads and window 8 after the tuning sweep. Q4 is the
practical daily-agent choice here: less RAM pressure and lower median fixture
latency. Q8 completed the tests but briefly left only 0.10 GiB of RAM available.
These are bounded host checks, not a general coding-quality ranking.

[MiniCPM-V 4.7 Q4_K_M](MINICPMV_HOST_RESULTS.md) is also validated at
262,144-token capacity with GPU vision and Q8_0 KV. The corrected coding suite
passed 18/18 sessions with low reasoning and 16/18 with reasoning off; both
modes passed all three long coding/image sessions and reported all image IDs.
Twelve image checks, six recall trials and three development DSH adapter checks
passed. The longest text input was 254,191 tokens; the first combined
coding/image input was 230,715 tokens. The original restricted-validator runs
remain archived and are not the published coding scores.

[Ornith 1.5 APEX-I-QUALITY](MODEL_ROSTER_HOST_RESULTS.md) was installed on the
same host at 262,144-token capacity with GPU vision and Q8_0 KV. Low reasoning
passed 18/18 bounded coding sessions, versus 16/18 off. All 12 image checks,
6 recall trials, 3 combined coding/image sessions with their image IDs, and
3 development DSH adapter checks passed. Retained settings are 15 CPU threads
and window 8; the paired speed difference was below the selection threshold.
Near-full text recall took a median 246.4 seconds to first token. The first
cold coding/image fixture took 528.1 seconds for its complete tool loop;
later fixtures reused the source prefix. These are different workloads. This
file has since been replaced by its 8-bit version, below.

**Gemma 4 26B-A4B UD-Q4_K_M** was measured at 262,144-token capacity with GPU vision. Coding off passed 16/18 and low passed 13/18; recall passed 6/6 and the development adapter passed 3/3. Long coding passed 2/3. Image checks passed 12/12; exact image-ID results are separate in the report.

**Tiel Coder 35B-A3B UD-Q4_K_XL** was measured at 262,144-token capacity with GPU vision. Coding off passed 16/18 and low passed 18/18; recall passed 6/6 and the development adapter passed 3/3. Long coding passed 3/3. Image checks passed 8/12; exact image-ID results are separate in the report.

**LFM2.5-24B-A2B UD-Q4_K_XL** was measured at 131,072-token capacity with text input only. Native-thinking coding at 4K output passed 18/18; recall passed 2/6 and the development adapter passed 3/3. Long coding passed 0/3. This model does not accept images. Initial forced-off failures remain archived.

Gemma output-budget tuning is reported separately from the standard 1,400-token coding tests. Tiel has measured screenshot transcription misses; do not treat vision support as perfect OCR. These are bounded fixtures, not general repository-level quality scores.

Gemma's separate low-reasoning probe at 4,096 output tokens passed 18/18 short coding sessions and 2/3 long coding/image sessions. The original smaller-budget failures remain in the report.

1. Target confirmed: this Windows PC, for coding and local coding agents.
2. Choose one model and quantization using [AI_SETUP.md](AI_SETUP.md) and
   [BACKENDS.md](BACKENDS.md). Confirm the download size and destination before setup.
3. Install and run the existing engine first. Keep the API on `127.0.0.1`.
4. Check available RAM, SSD space and VRAM immediately before running. Identify
   other GPU workloads with the user before stopping anything.
5. Verify a real response and a representative task. Record correctness as well as speed.
6. Save raw measurements under `bench/results/<date>-aryastrata-<workload>/`.
   Record source revision, engine version/build, model file and revision, launch
   settings, actual prompt/output token counts, warm/cold state, prompt processing,
   time to first token, generation speed, peak RAM/VRAM, and errors.
7. Repeat each case at least three times and report medians. Change one setting
   at a time, comparing the modified build to a same-day unmodified baseline.

For coding-agent validation, target the model's supported full context and record
the actual input length separately from allocated capacity. Short prompts are
useful diagnostics, but do not establish long-context coding-agent performance.
Keep vision enabled during validation for image-capable profiles. Treat untested
settings as an experiment plan, not a measured optimum.
Follow [COMMUNITY_BENCHMARKS.md](COMMUNITY_BENCHMARKS.md) for reporting conventions.

## Flint 40B-A2.5B, October 23, 2026

Flint came in with the PolyStrata 0.1.45-poly.3 merge. It runs here at the full 262,144-token context its GGUF
declares (`flint.context_length`), not the 131,072 the installer's context menu tops out at; the config was
written with `--context 262144`.

Hardware and settings: i9-14900KF, RTX 4070 Ti SUPER 16 GB, 63.82 GiB RAM, Windows 11; ready-made `strata-poly`
0.1.45 (poly.3, CUDA 13.0, `src 38ce288cd08729a0`); `flint-UD-Q4_K_XL.gguf`, 25.1 GB, SHA-256 verified;
`--prompt-batch 2048`, `--threads 15`, conversation cache 8,192 MiB.

| Prompt read | Time to first token | Prefill | Write |
| ---: | ---: | ---: | ---: |
| 8,143 tokens | 2.3 s | 3,707 tok/s | 121 tok/s |
| 32,311 tokens | 8.1 s | 4,036 tok/s | 93 tok/s |
| 129,323 tokens | 58.7 s | 2,227 tok/s | 58 tok/s |
| 242,606 tokens | 170.1 s | 1,430 tok/s | 22 tok/s |

Median of three runs at 8K, 32K and 129K and of two at 243K, greedy, 128 tokens of output. Every request began
with a unique prefix, so the prompt cache held 0 tokens in all eleven runs and each read is a full prefill.
Prompt sizes are the engine's own `prompt_n`. The filler is synthetic: these are speed measurements, not a
coding-quality result.

Writes slow as the prompt grows because the attention cache takes the VRAM the expert cache had: 6,217 of
12,032 routed experts sat in VRAM at load, about 5,492 (10.18 GiB) at 32K, 3,423 (6.56 GiB) at 129K and 1,457
(2.94 GiB) at 243K. The engine traded them without an error; no run ran out of memory.

Not tested here: any coding or recall suite, tool loops, quality at 256K, and several requests at once. Flint
reads text only. Raw numbers and the script that produced them:
[bench/results/2026-10-23-aryastrata-flint-256k/](../bench/results/2026-10-23-aryastrata-flint-256k/README.md).

## The 8-bit model set, October 18, 2026

The 4-bit files for Ornith 1.5, Tiel Coder, MiniCPM-V 4.7, Gemma 4 and LFM2.5 were replaced with 8-bit files of the
same families, and the 4-bit profiles were uninstalled: 104.1 GB of model folders, packs and run configs removed.
Qwen3.6-35B-A3B UD-Q4_K_XL was kept for further testing and the native Qwen3.8 IQ3_XXS because it runs the first
engine. The measurements above stay as the record for the files that are no longer installed; the
[8-bit host report](Q8_HOST_RESULTS.md) carries what is installed now.

- Ornith 1.5 Q8_0 is the faster file on this card, not the slower one: 107.8 against 92.4 tok/s for short-chat
  decoding, first token 0.278 against 0.324 s, 4K prompt 1,358 against 1,279 tok/s, 16K prompt 2,615 against 2,429,
  at the same 68.2 % expert cache hit. It is the only family with a 4-bit and an 8-bit measurement on this host.
- The other four 8-bit files measure 96.8 tok/s (LFM2.5), 83.2 (MiniCPM-V 4.7), 82.6 (Tiel Coder, tuned) and 68.0
  (Gemma 4) on the same suite. Tiel Coder is the only family whose settings changed: `--tail-skip 6` took it from
  66.3 to 82.6 tok/s decode, reproduced in three runs, and the same knob was measured and declined on the other
  four because their gains did not survive a re-run.
- Bounded checks on the installed 8-bit set: coding 9/9 on the four families that ran the fixed suite, images 12/12
  on three with Tiel at 8/12 on its known build-ID miss, and recall passing at 65,536 and 131,072 sent tokens on
  four. LFM2.5 answers 18/18 coding sessions only with its native-thinking settings and a 4,096-token budget, and
  finds 1 of 6 recall facts against the 4-bit file's 2 of 6: six prompts cannot rank those two files.
- These 8-bit files were downloaded by hand. [setup.py](../setup.py) still offers 4-bit, 3-bit, APEX and 6-bit sizes
  for four of the five families, so a fresh setup on another PC will not install the set described here.
- MiniCPM-V 4.7 does use its draft block on this host, at 41 of 79 guesses accepted; the backend table's older
  "answers one token at a time" row was wrong for the 8-bit file.

## Additional model deployment

The original deferred Tiel Q3/32K plan was superseded by the user-selected
Q4-or-higher installation and full-native-context validation. Model downloads
are kept outside the checkout in `C:\AI\Strata-data`; the installed run profiles
remain in the checkout. See the [model roster report](MODEL_ROSTER_HOST_RESULTS.md)
for exact profiles, model fingerprints, measured failures and reproduction steps.

## Existing model migration (October 17, 2026)

The user requested removal of the old installations while preserving reusable
downloads. The old Strata engine and Python environment and the Ornith llama.cpp
runtime were removed (2.67 GiB total); their dedicated launchers were renamed
with `.disabled-aryastrata-20261017`. Models, vision files, prepared packs,
settings, old source code and prior benchmark artifacts were preserved in place.

- `C:\AI\Strata-data`: Qwen3.8 IQ3_XXS, both GGUF shards, plus existing auxiliary data.
- `C:\AI\Ornith35\models`: Ornith 1.5 Q4_K_M and its vision projector.

At the initial migration inspection, Qwen's files matched the supported native model path. Ornith's architecture was
supported, but that preserved Q4_K_M file had not been load-tested. The new tested Ornith deployment uses APEX-I-QUALITY.
That initial recommendation was superseded by the measured deployments above. No model files
were moved or redownloaded. The local removal inventory is saved under
`local-data/runtime-removal-inventory.json` (ignored by Git).

## New-fork results

AryaStrata's first Qwen inference checks passed on October 17, 2026:

- Release engine 0.1.45 (CUDA 13.0, including sm_89) installed in this checkout.
- Existing Qwen3.8 IQ3_XXS shards, prepared pack and MTP data reused in place.
- Local server: `http://127.0.0.1:8080`, OpenAI base URL `/v1`, model
  `qwen3.8-flash-next-iq3_xxs`.
- Context 32,768; int8 KV; MTP on; 15 expert workers; vision off.
- `--vram-reserve-mib 1500`: the initial unreserved start warned of 184 MiB free;
  after restarting with the reserve, the engine reported 1,151 MiB free.
- Health and model-list endpoints confirmed the model loaded.
- A short coding request returned `def add(a, b): return a + b` (formatted across
  two lines). A second request returned a structured `read_file` tool call with
  `{"path":"README.md"}`. No actual tool was executed by that check.
- Local response records are under the ignored `local-data` folder. These are
  smoke checks, not a speed benchmark or a full coding-agent evaluation.

Start again with `run-iq3_xxs.bat` in this checkout (only when the current server
is stopped). Runtime configuration is in the ignored `strata-iq3_xxs.json`.
The server runs as a hidden background process. Its PID is in
`local-data/qwen-server.pid`; the current validation server log is
`local-data/tuned262-server.log` and its engine log is `local-data/tuned262-engine.log`.

FreeToken was also uninstalled at the user's request: its dedicated WSL Python
environment at `/opt/arya-freetoken/venv` was removed, with its package inventory
saved beside it. Its 22 GB Qwen3.6 NVFP4 download remains under
`/opt/arya-freetoken/models/qwen36-nvfp4`; compatibility with this engine has not
been tested. No FreeToken startup service or running server was found.

## Measured profile and results, October 17, 2026

The initial 32K setup above is a historical smoke check. The current measured
profile uses the old installation's **262,144-token ceiling**:

```text
--max-context 262144 --kv int8 --kv-resident 32768
--vram-reserve-mib 1792 --pool-workers 15
--pcie-frac 0.20 --spec 4 --spec-min-p 0.70
--adapt-every 1 --adapt-swaps 80 --adapt-decay 0.97
```

MTP and default suffix drafting are enabled; the engine reports lookup windows up
to 6. Vision was off during these benchmarks. `fit_max_tokens` is enabled. Calibration is saved using setup's
per-hardware/per-model/per-context settings format so updates can retain it.

The same-day 262K-ceiling API comparison measured **76.4 â†’ 86.1 tokens/s** for
short chat and **86.8 â†’ 95.6 tokens/s** for agent-style generation. Fresh 32K
prompt processing was **2,933.7 â†’ 2,915.0 tokens/s**, with about **11 seconds** to
first token. Agent follow-up latency was essentially unchanged at about **2.1 s**.
Three repetitions were used; the full report preserves ranges and sample counts.

The old configuration already used PCIe 0.20, draft floor 0.70 and 15 workers.
The calibration favored 80 cache swaps over its old 160. This is not an old-engine
versus new-engine measurement, and no custom engine build is claimed.

All **18 small read/edit/test coding sessions**, **3 development DSH adapter
streaming/replay checks**, and **12 three-fact recall trials** passed. The largest
recall inputs were **258,300 actual tokens**, three runs, with median first-token
latency **101.6 seconds**. This validates those retrieval trials, not arbitrary
reasoning or large-repository coding at that size.

The development DSH profile now selects the same Qwen model with its full context,
**8,192-token output capability** and text/image input (vision enabled after the text benchmarks). Its low-thinking preference
was preserved. Details and the adapter-test boundary: [AryaAI DSH](ARYAAI_DSH.md).

[Full benchmark and raw records](../bench/results/2026-10-17-aryastrata-qwen38-iq3xxs/README.md).

The existing
[RTX 4070 Ti SUPER report](../bench/results/2026-10-05-community-rtx-4070-ti-super/README.md)
used a Ryzen CPU and Linux; its numbers are reference data, not results from this PC.
Hardware-specific engine defaults should change only after a repeatable improvement
is measured here.

## Vision enabled after the text benchmarks

GPU vision is enabled with the existing BF16 Qwen3.8 Flash Next projector and
`strata-vision.exe`, up to 1,024 image tokens per picture. Context remains
262,144, with the same text tuning settings. The development DSH model now
advertises both text and image input. A local synthetic shapes/text image was
correctly described in 2.11 seconds through the image-input chat API. This is a
smoke check, not a vision benchmark or a remeasurement of text speed with vision
loaded. [Vision check and raw response](../bench/results/2026-10-17-aryastrata-qwen38-vision/README.md).

## Legacy engine removal, October 17, 2026

After the earlier migration preserved reusable files, the owner requested clean
removal of Ollama, standalone llama.cpp and FreeToken **including their models**.
Ollama 0.40.4 was uninstalled with its registered uninstaller; its user model
store, update cache and obsolete user PATH entry were removed. The old llama.cpp
Ornith Q4_K_M weights and vision projector, separate conversion checkout/runtime,
and FreeToken WSL model store were deleted. Historical reports were retained.

The removed Windows paths contained approximately **31.53 GiB**, and the
FreeToken directory in Ubuntu approximately **21.85 GiB**, about **53.38 GiB**
combined. These are file-byte totals; deleting files in WSL does not necessarily
shrink its Windows virtual disk immediately. No WSL disk compaction was run.

The active AryaStrata Qwen downloads, pack, tokenizer, MTP data and vision
projector were preserved. Its server remained loaded with image input enabled
and a 262,144-token context ceiling after cleanup. NInfer and image-generation
applications were outside this removal. Repository dependencies and historical
source integrations are not standalone installed inference engines.
