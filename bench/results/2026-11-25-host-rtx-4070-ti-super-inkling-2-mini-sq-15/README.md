# Inkling 2 Mini SQ-15 on a locally built Strata Inkling 0.1.68

Host: i9-14900KF (8P + 16E), RTX 4070 Ti SUPER 16 GB (sm_89, 66 SMs, ~672 GB/s,
PCIe host->device probe 24.1 GB/s), 64 GB RAM, Windows 11 26200, CUDA 13.1.2,
driver 621.24.

Engine: `engine-inkling/strata-inkling.exe`, built here from the vendored Strata
0.1.68 sources (`engine-inkling/build.ps1`, MSVC 19.44, `-DCMAKE_CUDA_ARCHITECTURES=89`,
9.3 MB). Model: `Inkling-2-Mini-SQ-15.strata` (13.36 GB) + `Inkling-2-Mini-Vision.strata`.

Why this record exists: Inkling 2 Mini was unusable at its shipped configuration
(~2.3 tok/s on a 48K-token conversation; `docs/ENGINES.md` claimed 88.8 tok/s).
The cause was not the engine version: it was how much K/V the run config kept on
the card. Measured here, 2026-11-25.

## Decode and prefill, `--bench --prompt-len N --gen 64`

| Prompt | Config | Prefill tok/s | Decode tok/s |
| --- | --- | ---: | ---: |
| 2,048 | 0.1.67 release binary (old pin), `--kv fp8` | 2,457.5 | 60.7 |
| 2,048 | 0.1.68 built here, same flags | 2,476.4 | 61.0 |
| 8,192 | 0.1.68, default expert budget 10.66 GB | 2,275 | 32.0-59.8 (cliff) |
| 8,192 | shipped config (9.5 GB, `k8v4`, max-ctx 65536) | 2,122.0 | 52.9 |
| 32,768 | 0.1.68, default expert budget 10.66 GB | 1,857 | 14.6 |
| 32,768 | 9.0 GB | 1,732 | 41.6 |
| 32,768 | 9.5 GB | 1,838 | 48.1 |
| 32,768 | shipped config | 1,843.5 | 48.9 |
| 65,536 | 0.1.68, `--kv fp8`, 10.66 GB | 1,497 | 8.0 |

## Where the time went

Decode falls with the context **used**, not with `--max-context`. Inkling K/V is
~110 KB per token (24 layers, `k8v4`), so 262,144 tokens would be ~28 GB: on a
16 GB card the engine maps most of the K/V from host RAM and every decoded token
reads it back over PCIe. The `--vram-experts-gb` value decides the split, and the
engine's automatic answer at the default budget keeps only ~7,900 K/V tokens on
the card at a 32K context — hence 14.6 tok/s.

| `--vram-experts-gb` | K/V tokens in VRAM at 32K | Experts VRAM/RAM | Decode tok/s |
| ---: | ---: | ---: | ---: |
| 10.66 | 7,936 | 2,832 / 240 | 14.6 |
| 10.0 | 27,648 | 2,708 / 364 | 32.9-46.6 (cliff) |
| 9.5 | 44,032 | 2,483 / 589 | 48.1 |
| 9.0 | 68,096 | 2,342 / 730 | 41.6 |
| 8.5 | 134,400 | 2,075 / 997 | 33.1 |

9.5 GB is the knee: the K/V for a 32K context fits on the card, and 589 experts
still do not have to be fetched from RAM (each costs ~13-20 ms/token).

## Batching

2,048-token prompt, `--parallel 4`: **122.1 tok/s aggregate, 30.5 per slot**
(one slot: 60.5). `--parallel 8`: 118.6 aggregate, 14.8 per slot.

## Not fixed by the port

- `--chunk` (new in 0.1.68): 512 / 2048 / 4096 measured within noise.
- `--draft auto` (DSpark): 43.0-49.8 tok/s against 60.7 with `--draft off`.
- `include/strata/inkling2/profile_rules.hpp` names an `Sm89Ada` profile and a
  chunk-2048 rule for this card class but is dead code: nothing calls
  `resolve_inkling2_profile()`, and no `profile=` line ever prints.

## Commands

```powershell
engine-inkling\build.ps1
engine-inkling\strata-inkling.exe --selfcheck
engine-inkling\strata-inkling.exe --bench `
  --native C:\AI\Strata-data\models\inkling-2-mini\Inkling-2-Mini-SQ-15.strata `
  --vision C:\AI\Strata-data\models\inkling-2-mini\Inkling-2-Mini-Vision.strata `
  --max-context 65536 --vram-experts-gb 9.5 --ram-experts-gb 1.62 --draft off `
  --kv k8v4 --kv-offload auto --prompt-len 32768 --gen 64
```

Full arm matrix and per-run logs: `engine-inkling/scratch/matrix-*.json` and
`engine-inkling/scratch/m-*.log` (gitignored; regenerate with
`engine-inkling/scratch/bench-matrix.ps1`).

Not tested here: the vision path end to end (the engine reports `images=1` and the
config passes `--vision`, but no image was sent through the server), and a
multi-slot server conversation with real chat traffic.