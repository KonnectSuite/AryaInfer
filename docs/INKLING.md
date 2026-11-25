# Inkling 2 Mini

Inkling 2 Mini is the one model here whose engine is a program of its own: it does
not run on `strata.exe`, and it does not run on `strata-poly`. It needs
`strata-inkling.exe`, the Strata *Inkling shape* engine, built from the
`src/inkling2` tree. The model files are:

| File | Size | What it is |
| --- | ---: | --- |
| `C:\AI\Strata-data\models\inkling-2-mini\Inkling-2-Mini-SQ-15.strata` | 13.36 GB | the text model, 24 layers, 128 experts |
| `C:\AI\Strata-data\models\inkling-2-mini\Inkling-2-Mini-Vision.strata` | 0.59 GB | the vision encoder (`--vision`) |
| `C:\AI\Strata-data\packs\inkling-2-mini-sq-15\tokenizer` | | the tokenizer the server owns |

`Inkling-2-Mini-SQ-10.strata.part` in the same folder is an incomplete download
and is not a second model.

## Where the binary comes from

AryaInfer builds it, from the Strata `0.1.68` source vendored in
`engine-inkling/src` (gitignored). `engines.json` marks the engine `manual`: the
installer never downloads it, and `docs/INKLING.md` (this page) is what setup
points at instead.

```powershell
# from the repository root; ~4 minutes, 9.3 MB executable
powershell -NoProfile -File engine-inkling\build.ps1
```

`build.ps1` runs `cmake -S engine-inkling\src\engine -B engine-inkling\build
-DSTRATA_ENABLE_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89` with the CUDA 13.1.2
`nvcc`, builds the `strata-inkling` target and copies the result to
`engine-inkling\strata-inkling.exe` next to the five DLLs it needs
(`cublas64_13`, `cublasLt64_13`, `cudart64_13`, and the MSVC runtime). It writes
`engine-inkling\BUILD.json`, which is what the server and `setup.py` read.

Two facts about this binary that look wrong and are not:

- `strata-inkling.exe --version` prints **0.1.67**. The version is a `#define
  INKLING_VERSION` in `src/inkling2/ink_main.cpp`, and upstream did not bump it
  when the tree moved to 0.1.68. `BUILD.json` records `"version": "0.1.68"`, the
  release the sources came from.
- `--info` output is identical to the 0.1.67 release binary: the artifact format
  did not change, only the engine around it.

## Running it

`strata-inkling-2-mini-sq15-0168.json` is the working config. Its engine flags
carry one decision that is not obvious, explained in *What makes it slow* below:

```
--native Inkling-2-Mini-SQ-15.strata --vision Inkling-2-Mini-Vision.strata
--max-context 65536 --kv k8v4 --kv-offload auto --draft off
--vram-experts-gb 9.5 --ram-experts-gb 1.62 --parallel 1
```

The previous config (`...-0167.json`) named the 0.1.67 release binary and asked
for `--max-context 262144` with the expert pool at its 10.66 GB default. Both of
those are why Inkling 2 Mini felt broken: at 262144 the engine keeps only ~8,000
K/V tokens on the card and streams the rest from RAM, so every decoded token
waits on the PCIe link. See the table below.

## Measured on this host

`RTX 4070 Ti SUPER 16 GB`, i9-14900KF, 64 GB, Windows 11. `--bench` with
`--prompt-len N --gen 64`, which is the engine's own loop: prefill from empty, then
64 greedy tokens. Medians of two runs, engine-inkling/scratch/matrix-*.json.

| Prompt | Config | Prefill tok/s | Decode tok/s |
| --- | --- | ---: | ---: |
| 2,048 | 0.1.67 release binary (the old pin) | 2,458 | 60.7 |
| 2,048 | 0.1.68 built here | 2,470 | 60.0 |
| 8,192 | 0.1.68, default expert budget (10.66 GB) | 2,275 | 32-60* |
| 8,192 | 0.1.68, `--vram-experts-gb 9.5` | 2,118 | 52.6 |
| 8,192 | **shipped config** (`--max-context 65536`, 9.5 GB, `k8v4`) | 2,122 | 52.9 |
| 32,768 | 0.1.68, default expert budget (10.66 GB) | 1,857 | 14.6 |
| 32,768 | 0.1.68, `--vram-experts-gb 9.0` | 1,732 | 41.6 |
| 32,768 | 0.1.68, `--vram-experts-gb 9.5` | 1,838 | 48.1 |
| 32,768 | **shipped config** | 1,843 | 48.9 |
| 65,536 | 0.1.68, `--kv fp8`, host KV | 1,497 | 8.0 |

\* The default budget lands on a cliff, not a slope: two loads of the same
command gave 59.8 and 32.0 tok/s, because the K/V that fits in VRAM came out as
8,960 tokens in one load and 4,096 in the other. A number at this setting is only
reproducible to that cliff.

### Batching

`--parallel 4` measured **122.1 tok/s aggregate at 30.5 tok/s per slot** on a
2,048-token prompt (60.5 for one slot). `--parallel 8` was no better: 118.6
aggregate, 14.8 per slot. Four slots share the card well; eight contend for the
same K/V budget. Batching multiplies the K/V a config needs, so it wants a
shorter `--max-context` than a single long conversation does.

## What makes it slow

Inkling 2 Mini's K/V costs ~110 KB per token (24 layers of `k8v4`); 262,144
tokens would be ~28 GB, which no 16 GB card holds, so the engine keeps as much
K/V in VRAM as it can and *maps the rest from host RAM*. Every decoded token
reads the whole used context back over PCIe at ~24 GB/s. That is the cost, and it
grows with the context you have **used**, not with the `--max-context` you
declare. Declaring 262144 is not by itself the problem: at an 8,192-token prompt
it measured as fast as 32768 did.

What fixes it is budgeting the card so the K/V for the context you actually use
*fits on it*. On a 32,768-token prompt the four budgets measured:

| `--vram-experts-gb` | K/V tokens kept in VRAM | Experts in VRAM / RAM | Decode tok/s |
| ---: | ---: | ---: | ---: |
| 10.66 (default) | 7,936 | 2,832 / 240 | 14.6 |
| 10.0 | 27,648 | 2,708 / 364 | 33-47* |
| 9.5 | 44,032 | 2,483 / 589 | 48.1 |
| 9.0 | 68,096 | 2,342 / 730 | 41.6 |
| 8.5 | 134,400 | 2,075 / 997 | 33.1 |

\* Also a cliff: 46.6 and 32.9 on two loads.

Two things move in opposite directions here. Every GB taken from the expert pool
gives the K/V cache roughly ten times the tokens it needs, but it also pushes
experts out to the RAM tier, where each cold expert costs ~13-20 ms per token to
fetch. 9.5 GB is the knee: the K/V for 32K of context fits on the card and 589
experts still do not have to be fetched. 8.5 GB buys K/V room nobody uses and
pays for it in cold experts (`--bench` prefill fell to 363 tok/s at 8.0 GB).

## What 0.1.68 adds, and what it does not

- `--chunk N` is new. It does **not** help here: 2,048 and 4,096 measured within
  noise of the 512 the engine picks by itself, at every prompt length tried.
- `--draft auto` (DSpark) is a loss on this model and card: 43.0-49.8 tok/s
  against 60.7 with `--draft off`, which is what the config ships. `--draft-beam`,
  `--draft-cost`, `--draft-adapt` and `--draft-plain` are new knobs on the same
  machinery and were not pursued for that reason.
- `include/strata/inkling2/profile_rules.hpp` reads like a gift: it names
  `Sm89Ada`, an `RTX 4070 (sm_89, 12 GB CoreResidentHybrid @ 65K/131K & TightHybrid
  @ 262K)` measured profile, and chunk rules for exactly this class of card. It is
  **not wired up**: `resolve_inkling2_profile()` and `format_profile_line()` have
  no caller anywhere in the tree, and no `profile=` line appears in any log. The
  numbers on this page were measured, not inherited from that header.

## Determinism

Greedy output is stable across loads: the same six-token prompt with `--temp 0` gave
`15,13,15,11,198,149861,149862,196991,11,198,149861,149862` on two separate
engine starts of the shipped config. One caveat the engine prints itself: an expert
that is not on the card is computed by the CPU kernel, "which can differ from an
all-resident run in rounding"; `STRATA_INK_EXACT=1` forces one lane for a bit-exact
comparison.

## Vision

`--vision Inkling-2-Mini-Vision.strata` adds a native encoder: the engine takes
image embeddings on the wire and the server sends them as `GENI`. The 0.1.67
control and the 0.1.68 build both report `images=1` in `--info`; the vision path
was not benchmarked separately here.

## Reproducing a line in the table

```powershell
engine-inkling\strata-inkling.exe --bench `
  --native C:\AI\Strata-data\models\inkling-2-mini\Inkling-2-Mini-SQ-15.strata `
  --vram-experts-gb 9.5 --ram-experts-gb 1.62 --prompt-len 32768 --gen 64 `
  --kv k8v4 --kv-offload auto --draft off --max-context 65536
```

`engine-inkling/scratch/bench-matrix.ps1` runs a list of arms over a list of
prompt lengths and writes one log per run plus `matrix-<tag>.json`; every number
above came from it.