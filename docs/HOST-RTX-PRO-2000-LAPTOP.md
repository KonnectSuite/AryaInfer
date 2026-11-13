# This laptop: what it runs, and what it measured

The numbers in the rest of `docs/` come from the machine in `docs/ARYAINFER.md`
(i9-14900KF, 16 GB RTX 4070 Ti SUPER). This page is the other host: a 16-core
laptop with an 8 GB workstation card, which is the machine the Coder
configuration in `strata-coder-iq1_m.json` was tuned on. Only numbers measured on
this machine appear here.

| | |
|---|---|
| CPU | Intel Core Ultra 7 265H, 16 threads (6 P + 8 E + 2 LPE), AVX-2 only (the engine logs "this CPU has no AVX-512") |
| GPU | NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU, 8,151 MiB, driver 597.01, sm_120, boost 3,090 MHz |
| RAM | 63.4 GiB |
| Disk | 1 NVMe volume, 2 TB |
| OS | Windows 11, balanced power plan (the only scheme installed) |
| Model | Qwen3.8-Flash-Next Coder IQ1_M, 54.4 GB over two shards (27.58 GB native + 26.82 GB PLE) |

## The engines on this machine

| Engine | Version | Built from | Size |
|---|---|---|---|
| `engine\strata.exe` | 0.1.59.1 | upstream [Niko1221/Strata](https://github.com/Niko1221/Strata) tag `v0.2.13.1`, commit `628f74955` | 115,088,384 B |
| `engine-poly\strata-poly.exe` | 0.1.45 | upstream [simplexai-labs/PolyStrata](https://github.com/simplexai-labs/PolyStrata) `main`, commit `67dde645d` (the 149 commits after `v0.1.45-poly.9`) | 84,346,368 B |

Both were compiled here on 2026-11-13 with CUDA 13.5 for `sm_120` only:
`build-upstream-strata.cmd` (171 of 171 units) and `build-upstream-polystrata.cmd`
(130 of 130), from the worktrees `strata-upstream\` and `polystrata-upstream\`.
The previous binaries, the fork's own 0.1.45 builds, are kept in
`engine-backup-0.1.45\` and `engine-backup-0.1.45\poly\`; copying those four files
back restores them.

The PolyStrata line is where upstream keeps its version number: the newest tag is
`v0.1.45-poly.9`, `main` is 149 commits past it and still says 0.1.45, so the
binary here is newer than the newest release while reporting the same version.
The 149 commits are mostly the Metal backend and benchmarks; on Windows CUDA what
it changes is small.

Neither engine was merged into this fork's source. Strata 0.1.59 restructured the
tree (`cmake/backends/*`, a vendored `third_party/strata-ggml`) over 3,881 commits
against 684 local ones, and a merge would have cost more than building the release
in its own worktree and installing the binary. The fork's own source, including
its `kQ4_0` KV and the AQ3 path, is untouched.

`engine\BUILD.json` and `engine-poly\BUILD.json` say `"source": "upstream"` with
the commit they were built from. `setup.py` treats any engine whose `source` is
not `local` as one it does not have to compile, so the normal `START-HERE.bat`
path starts these binaries; `setup.py --build` still compiles the fork's source
over them, and after that the release line and this page disagree again.

Nothing here repacks a model: the 0.1.45 packs under
`PolyStrata-data\packs\` load unchanged in 0.1.59.1.

## What the Coder does on this machine

Shipped configuration (`strata-coder-iq1_m.json`, `--vram-reserve-mib 300`,
`--kv q4_0 --kv-resident 32768`, `--spec 4`, `--max-context 131072`):

| | measured |
|---|---|
| recall at 32K (depth 50%) | found, 32,444 prompt tokens, 98 s |
| recall at 100K (depth 50%) | found, 110,822 prompt tokens, 262 s |
| prompt read | 291-605 tok/s (110,822 tokens in 262 s = 423 tok/s) |
| decode, 2-4K context | 26-33 tok/s (cool machine), 4.4-11.6 tok/s (after an hour of load, median 8.5) |
| decode, 8K context | 16-30 tok/s |
| decode, 13-26K context | 5-11 tok/s, and 27.3 once (see below) |
| VRAM free with everything loaded | 233 MiB (the engine reports this as LOW and asks for `--vram-reserve-mib 579`) |

This is the configuration the machine should run, and it is what is in
`strata-coder-iq1_m.json` today. It is not a compromise: every change tried
against it either lost (see the table below) or made the engine unstable, and it
holds 110,822 tokens of recall. What it cannot do is beat the card it runs on.

The decode spread is not a settings effect: the same binary and the same
arguments produced 26.65, 31.3, 33.7 and 4.4 tok/s at a 2K prompt in one
afternoon. What tracks it is the card's state. Under load this GPU sits between
720 and 2,332 MHz of its 3,090 MHz, draws 9-52 W and reaches 96 °C, with
`clocks_event_reasons.active` bit `0x20` (software thermal slowdown) set, and at
idle after an hour of work it still reads 79 °C at 180 MHz. There is no fan or
performance switch reachable here: the Lenovo WMI surface has no thermal-mode
class, `powercfg /overlayactivate` answers "Invalid Parameters", and the machine
has only the balanced power scheme.

### How much one number here is worth

One interleaved run at a 24K prompt, the shipped configuration and one variant,
alternating to cancel drift, is the best illustration. Each cell is the median of
two decodes, with the range the engine reported:

| Arm | 24K, run 1 | 24K, run 2 |
|---|---|---|
| shipped configuration | 27.30 tok/s (19.2-35.4) at 1440 MHz, 32 W | 11.00 tok/s (5.9-16.1) at 1252 MHz, 17 W |
| `--mtp-q4 all` | 10.45 (5.6-15.3) at 738 MHz, 16.5 W | 10.65 (5.6-15.7) at 1106 MHz, 17.3 W |

Same arguments, 2.5x apart, and the fast row is the one where the card happened
to be holding boost clocks and drawing 32 W. Across the day the shipped
configuration measured 5.25, 6.5, 11.0 and 27.3 tok/s at 24K. Any single reading
on this laptop, mine included, is worth no more than that: quote the range.

At 13K and beyond the card is not the bottleneck: it idles at 15-16 W while
decode runs at 5-10 tok/s, with 55-82% expert cache hits. The per-token cost that
grows is work over the context itself, on a card this small.

## Settings that were measured and rejected here

Each of these was run on this machine, on the Coder, and lost. The engine column is
the one the row was measured on: the two builds account for VRAM differently, so a
row from 0.1.45 does not automatically carry over to 0.1.59.1.

| Change | Engine | Result |
|---|---|---|
| `--vram-reserve-mib 812` | 0.1.45 | free VRAM rises but the expert cache loses slots: 4.5 tok/s at 24K against 5.3 for the shipped reserve |
| `--vram-reserve-mib 812` | 0.1.59.1 | the engine died on an 8,579-token prompt: `prefill: the expert source could not copy experts 256.. of layer 0`, exit code `0xC0000409` (fail-fast in `ucrtbase.dll`), server answered HTTP 503 |
| `--vram-reserve-mib 1344` | 0.1.45 | leaves 0 expert-cache slots: 1.5 tok/s at 24K |
| `--vram-reserve-mib 1344` | 0.1.59.1 | 965 MiB free as asked, but warm-up ran 1.6-1.8 tok/s and the arm ended on HTTP 503 |
| `--mtp-q4 all` | 0.1.45 | 480 slots instead of 528 (the draft experts are not what costs the VRAM), 7.1 tok/s at 2K |
| `--mtp-q4 all` | 0.1.59.1 | no gain at 24K and a loss at 2K: 10.45 and 10.65 tok/s at 24K, 10.60 at 2K against 15.40 for the shipped configuration under the same conditions |
| `--pool-workers 6` with `--pool-affinity p-cores` | 0.1.59.1 | inconclusive and not adopted: 7.95 / 17.75 / 9.80 tok/s at 2K / 8K / 24K against 15.40 / 11.00 / 5.25, which is the same order-dependent noise the table above describes |
| `--kv-resident 20480`, `--kv-grow`, `--prefill 2048` | 0.1.45 | 6-7 tok/s at 20K against 20.0 for the shipped configuration |
| `--spec 2` instead of 4, at 24-26K | 0.1.59.1 | no gain: 6.4 tok/s with 66 of 66 drafts accepted, against 5.2-8.8 for `--spec 4`. `--spec 0` is refused: a native (IQ) pack requires `--spec T` with `T >= 2` |
| moving more experts into VRAM / more KV into RAM | 0.1.45 | frees about 90 MiB of VRAM and costs 3-19x at long context |

`--vram-reserve-mib 812` is therefore not a slower setting on 0.1.59.1, it is an
unstable one: the engine's own advice (579, or 1152 for the #2065 warning) trades
expert-cache slots for headroom, and at 812 the prompt path runs out of somewhere
to put the experts it lends and aborts. The shipped 300 leaves 233 MiB free and
has not crashed in any run here, including a 110,822-token prompt.

Two upstream 0.1.59 knobs turned out not to apply to this machine:
`--ram-keep-gib W` is RAM to leave free for other work (a low-RAM lever, and this
box has 23.42 GiB of arena resident plus 28 GB of PLE table), and `--kv k8v4`
costs 816 B per cell against `--kv q4_0`'s 528, so it would give slots back, not
take them.

Defender exclusions for `AryaInfer\`, `PolyStrata-data\`, `strata.exe` and
`strata-vision.exe` were added while measuring. They cut model load time; they do
not change decode rate.

## What was not measured here

- The image path on 0.1.59.1: `strata-vision.exe` in `engine\` is still the fork's
  0.1.45 build (upstream builds it separately from `tools/vision`, against a
  llama.cpp checkout), and no image request was sent after the engine swap.
- `strata-poly` on any other family. It was verified on the one GGUF that is on
  this machine: Qwen3.6-35B-A3B-UD-Q4_K_M loaded in 10.7 s, put 2,064 of 10,496
  routed experts in 3.7 GiB of VRAM, and generated 64 tokens at 23.35 tok/s with
  69.8% of the experts served from VRAM and 58.9 ms per token of CPU expert work.
- Anything about 0.1.59.1 on the hardware in `docs/ARYAINFER.md`, where the
  inherited numbers were measured.

The harness used for the tables above is `tune_ab2.py` next to this checkout's
parent folder (`C:\Users\kphung\AryaCode\KonnectSuite\tune_ab2.py`): one server per
arm, a warm-up, prefill and two decodes per context size, `nvidia-smi` sampled
four times a second, and the engine's own cache-hit and VRAM lines parsed out of
its log. Its rows are in `tune_ab2.jsonl`.
