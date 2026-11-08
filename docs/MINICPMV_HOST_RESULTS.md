# MiniCPM-V 4.7 35B-A3B on the AryaInfer host

The installed template supports thinking Off/On. Benchmark requests labeled
`low` enable native thinking; Low/Medium/High are aliases in AryaAI, not three
distinct strengths. See the [connection audit](ARYAAI_CONNECTION_AUDIT.md).

AryaInfer is a fork of [PolyStrata](https://github.com/simplexai-labs/PolyStrata),
which is a fork of [Niko1221's original Strata](https://github.com/Niko1221/Strata).
Original notices and credits remain in [CREDITS.md](../CREDITS.md).

Target: i9-14900KF, RTX 4070 Ti SUPER 16 GB, 64 GB RAM, Windows 11.
This page separates available files from measurements on this machine.

## Quantization choices

The existing installer supports these OpenBMB GGUFs:

| Weight quant | Download, decimal GB | Installer support |
|---|---:|---|
| mix_q3gud_im | 15.5 | Yes |
| Q4_K_M | 21.2 | Yes; initial host test choice |
| Q6_K | 28.5 | Yes |

The [official file repository](https://huggingface.co/openbmb/MiniCPM-V-4.7-35B-A3B-gguf/tree/main)
also lists IQ3_XS, IQ3_M, IQ4_XS, IQ4_NL, Q4_0, Q4_1, Q4_K_S,
Q5_0, Q5_1, Q5_K_S, Q5_K_M and Q8_0. Q5 files range from about
24 to 26.1 GB; Q8_0 is about 36.9 GB. Availability there does not mean
these variants have been added to setup or tested with this backend here.
F16 is about 69.4 GB, before runtime allocations.

Vision uses the model-specific `mmproj-model-f16.gguf`, another 1.12 GB.
Do not reuse Qwen's projector. Download sizes are not total runtime RAM or VRAM.

## Measured host results

Q4_K_M completed the recorded host test sequence with PolyStrata, GPU vision,
262,144-token capacity, Q8_0 KV and the whole cache allocated. No context
extension was used: the GGUF declares `qwen35moe.context_length = 262144`.
Image input is capped at 1,024 tokens in this profile. One request slot,
prompt batch 512, VRAM reserve 768 MiB, tail skipping 0 and an 8 GiB
conversation-cache limit were retained.

**Use low reasoning for coding fixtures like these.** Low reasoning passed 18/18 sessions,
versus 16/18 with reasoning off. This is a bounded fixture result,
not a general coding-quality ranking or evidence that weight quantization
caused any remaining failures. No Q6/Q8 comparison was run.

The initial validator incorrectly rejected normal `set.add()` and
`dict.values()` operations. Coding tests were rerun after correcting it;
the table below uses `corrected/` records. Original records and the original
validator remain archived. Image, recall, calibration and DSH results were
unaffected. Historical Qwen results used the earlier stricter validator,
so these counts should not be used as a direct cross-model quality ranking.

| Check | Result |
|---|---|
| Coding, reasoning off | 16/18 |
| Coding, low reasoning | 18/18 |
| Synthetic image checks | 12/12 |
| Long-input recall | 6/6 |
| Long coding + image, reasoning off | 3/3; image IDs 3/3 |
| Long coding + image, low reasoning | 3/3; image IDs 3/3 |
| Development DSH streaming/tool replay | 3/3 |

The retained CPU setting is **15 threads**. Confirmation medians were
137.3 tokens/s for the baseline and 138.3 for the candidate;
both confirmation configurations used 15 threads. This small difference is
repeat variation, not a measured gain from changing a setting.
Short-prompt speed is not the decode rate after a near-full input.

Median complete coding sessions took **3.61 s off** and **5.82 s low**.
Peak total system RAM use was 55.54 GiB, with at least 8.28 GiB available;
peak sampled GPU allocation was 15988 MiB. Samples were five seconds apart; paging was not measured.

### Long-input recall

| Actual input tokens, median | Prefill tok/s | First token, s | Decode tok/s | Recall |
|---:|---:|---:|---:|---|
| 131,031 | 1,379.6 | 95.1 | 54.2 | 3/3 |
| 254,191 | 960.1 | 265.0 | 34.6 | 3/3 |

Vision remained loaded during text recall. Combined coding/image trials use
approximately 229K tokens of repeated source excerpts before the task and
leave room for subsequent tool turns. Cold prefix processing and later
prefix reuse are different workloads; see the per-call records.

### Combined coding and image sessions

Each mode starts cold; later fixtures may reuse the source prefix. These
are three different tasks, not three repetitions of one task.

| Reasoning | Fixture | Session, s | First-call input tokens | Cached input tokens | Code/tool checks | Image ID |
|---|---|---:|---:|---:|---|---|
| none | trim_history | 359.07 | 230717 | 0 | pass | yes |
| none | merge_tool_results | 67.68 | 230731 | 208896 | pass | yes |
| none | summarize_usage | 77.57 | 230714 | 208896 | pass | yes |
| low | trim_history | 369.55 | 230715 | 0 | pass | yes |
| low | merge_tool_results | 80.34 | 230729 | 208896 | pass | yes |
| low | summarize_usage | 92.07 | 230712 | 208896 | pass | yes |

### Use in AryaAI development

- Model ID: `minicpm-v-4.7-35b-a3b-q4_k_m`.
- API: `http://127.0.0.1:8080/v1`; text and image input.
- Context: 262,144 total tokens; advertised output limit: 8,192 tokens within that total.
- Installed profile: `strata-minicpmv-q4_k_m.json`.
- Reload the development app model list after its metadata is updated.

The isolated DSH adapter checks cover streaming and tool-result replay,
not every desktop workflow. Existing default model and thinking preferences
are preserved; select low reasoning when using MiniCPM for this kind of coding.

[Raw records](../bench/results/2026-10-18-model-roster/minicpmv/) and
[the model roster report](MODEL_ROSTER_HOST_RESULTS.md) contain exact
profiles, file fingerprints, tuning runs, responses and resource samples.

These are bounded Python fixtures, synthetic images and three-fact recall
in repeated source excerpts. They are not a real-repository coding score
or a general vision benchmark. No draft block is present in these MiniCPM
files; this backend generates one token at a time. The separate DSpark
heads offered upstream were not installed or tested by this path.
