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
| decode, 8K context | 16-20 tok/s |
| decode, 13-26K context | 4-10 tok/s |
| VRAM free with everything loaded | 233 MiB (the engine reports this as LOW and asks for `--vram-reserve-mib 579`) |

The decode spread is not a settings effect: the same binary and the same
arguments produced 26.65, 31.3, 33.7 and 4.4 tok/s at a 2K prompt in one
afternoon. What tracks it is the card's state. Under load this GPU sits between
720 and 2,332 MHz of its 3,090 MHz, draws 9-52 W and reaches 96 °C, with
`clocks_event_reasons.active` bit `0x20` (software thermal slowdown) set, and at
idle after an hour of work it still reads 79 °C at 180 MHz. There is no fan or
performance switch reachable here: the Lenovo WMI surface has no thermal-mode
class, `powercfg /overlayactivate` answers "Invalid Parameters", and the machine
has only the balanced power scheme.

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
| `--vram-reserve-mib 1344` | 0.1.45 | leaves 0 expert-cache slots: 1.5 tok/s at 24K |
| `--vram-reserve-mib 1344` | 0.1.59.1 | 965 MiB free as asked, but warm-up ran 1.6-1.8 tok/s and the arm ended on HTTP 503 |
| `--mtp-q4 all` | 0.1.45 | 480 slots instead of 528 (the draft experts are not what costs the VRAM), 7.1 tok/s at 2K |
| `--kv-resident 20480`, `--kv-grow`, `--prefill 2048` | 0.1.45 | 6-7 tok/s at 20K against 20.0 for the shipped configuration |
| `--spec 2` instead of 4, at 24-26K | 0.1.59.1 | no gain: 6.4 tok/s with 66 of 66 drafts accepted, against 5.2-8.8 for `--spec 4`. `--spec 0` is refused: a native (IQ) pack requires `--spec T` with `T >= 2` |
| moving more experts into VRAM / more KV into RAM | 0.1.45 | frees about 90 MiB of VRAM and costs 3-19x at long context |

An `--vram-reserve-mib 812` on 0.1.59.1 was not measured; the engine asks for 579
and gets 233 MiB free at 300, and 100K recall works at that setting.

Defender exclusions for `AryaInfer\`, `PolyStrata-data\`, `strata.exe` and
`strata-vision.exe` were added while measuring. They cut model load time; they do
not change decode rate.

## What was not measured here

- The image path on 0.1.59.1: `strata-vision.exe` in `engine\` is still the fork's
  0.1.45 build, and no image request was sent after the engine swap.
- `strata-poly` beyond one smoke test: it loaded Qwen3.6-35B-A3B-UD-Q4_K_M in
  12.4 s, put 2,088 of 10,496 routed experts in 3.7 GiB of VRAM, and generated
  four tokens. No family and no pack was benchmarked on this machine.
- Anything about 0.1.59.1 on the hardware in `docs/ARYAINFER.md`, where the
  inherited numbers were measured.

The harness used for the tables above is `tune_ab2.py` next to this checkout's
parent folder (`C:\Users\kphung\AryaCode\KonnectSuite\tune_ab2.py`): one server per
arm, a warm-up, prefill and two decodes per context size, `nvidia-smi` sampled
four times a second, and the engine's own cache-hit and VRAM lines parsed out of
its log. Its rows are in `tune_ab2.jsonl`.
