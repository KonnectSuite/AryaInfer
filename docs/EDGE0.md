# Edge0-145B

Edge0-145B is a 145B-parameter latent-MoE model from
[Edge0-AI](https://github.com/Edge0-AI/Edge0), and it is the fifth engine in the
roster. It is **not** a new architecture port: the model runs on
`edge0-strata`, Edge0's fork of [Strata](https://github.com/Niko1221/Strata)
(the engine this repository also builds on), and the server talks to it over the
same `--serve` line protocol as the others. So adding it means adding a binary
and a config, exactly the way `engine-ninfer/` does - not touching `src/poly`
or the GGUF reader.

## Install

```bat
START-HERE.bat --setup --family edge0
```

or, with the Python of the checkout:

```bat
.venv\Scripts\python.exe setup.py --family edge0
```

Setup does three things:

1. **The engine**: Edge0 publishes its CUDA engine inside the Windows desktop
   bundle (`edge0-chat-0.3.0-windows-x64.zip`, 280 MB, SHA-256 pinned in
   `setup.py`). Setup downloads it and unpacks the two files it needs into
   `engine-edge0/` - `strata.exe` and `strata_kq.dll`. That folder is the
   engine's own: an update of the Strata engine in `engine/` cannot touch it.
   The engine it replaces is kept in `engine-edge0/.previous`;
   `setup.py --rollback-engine` puts it back.
2. **The pack**: `Edge0/Edge0-145B-q3k` from Hugging Face, 74 files, 106.3 GB,
   into `<data folder>\models\Edge0-145B-q3k\`. It is a **Strata pack folder**,
   not GGUF shards, so setup downloads it file by file from the pinned list
   `EDGE0_FILES` in `setup.py` (sizes, and the Hub's SHA-256 for the large LFS
   files). Every file resumes; nothing is re-downloaded after a stopped run.
3. **The config**: `strata-edge0-145b.json`, with the args and the
   `STRATA_LATENT_*` environment the model's own `model.json` lists.

## What runs where

| | |
| --- | --- |
| Total / active parameters | 145B / 10.12B (their README counts a different active set than the pack's `model.json`) |
| Experts | 512 per layer, 10 routed + 1 shared, latent width 1792, expert record 1,630,720 B |
| Pack on disk | 106.3 GB (Q3_K: Q3_K gate/up + IQ4_NL down, Q8 dense projections) |
| VRAM before experts | about 4.6 GB (skeleton 2.9 + MTP head 0.8 + buffers) |
| Context | 131,072 by default (the pack supports 262,144; `--context 262144` writes it) |
| RAM | about 38 GB on a 16 GB card by setup's estimate: the experts the card does not hold are read through the file cache |

An RTX 4070 Ti SUPER 16 GB holds about 12 GB of the 40 GB expert pool, so most
answers are partly CPU work. That is the same shape as the other MoE models in
this repository on this card, and the reason to have it is breadth: a second
model family for agent work without loading a second program.

## Switching

The config sits beside the other `strata-*.json` files, so `edge0-145b` appears
in the model list and in `/api/models` like any other model. With
`switch_on_request` (the default) the server stops the engine that is running
and starts Edge0's, and switching away stops Edge0's again - one engine at a
time, as always. Nothing about the API, the web app or the tools changes.

## Not included yet

- **No vision.** The pack ships `mmproj-BF16.gguf`, but Edge0's own config never
  wires images, so the roster lists this model as text-only until the fork's
  image path is tried (its `strata-vision.exe` equivalent is not part of the
  bundle).
- **No Linux engine.** Edge0 publishes a Windows x64 CUDA build only (compute
  capability 7.5+, CUDA 13). Setup refuses `--family edge0` off Windows; on
  Linux, build <https://github.com/Edge0-AI/Edge0> and point the config's `exe`
  at it.
- **No measurement on this host yet.** The roster's numbers for this model are
  absent on purpose: they go in `bench/results/` once the first run here is
  recorded (4K/16K/32K prefill, decode, 96K read), the same way the Strata
  0.1.62 numbers were. Edge0's own published rows are for an RTX 5090 D, a
  16 GB card constrained to 20 GB of RAM, and a 24 GB card - none is a 16 GB
  Ada card.

## Known issue on this host (2026-11-19)

The 0.3.0 engine **loads the pack and starts its session** here (47 s, expert
arena 37.32 GiB, 1785 resident slots, `session is up (engine 0.1.55)`), but the
**first generation deadlocks** in the fork's graph-verify window:

```text
K0-STAGE-RESET t=... h_seq=0
K0-LAUNCH-QUERY NOTREADY(busy)
K0PROBE u_gpu=1 LUGPU=1 nent=41 n_tok=6 k=10
strata serve: verify: timed out at layer 1; its GPU waits were released and the GPU finished (#267)
```

Tested without effect: vendor-exact args (no `--pcie-frac`/`--kv-resident`/
`--vram-reserve-mib`/`--pcie-mode`), `--spec 0`, no `--mtp`, `--no-warmup`,
`STRATA_VERIFY_ASYNC_LAUNCH=0`, and the fused latent kernels off
(`STRATA_LATENT_FUSED=0`, `STRATA_LATENT_FUSED_DU=0`, `STRATA_LAT_FUSED_Q3K=0`).
The engine answers `READY`, so the server lists and switches to the model
normally; it only fails at the first token.

This is an upstream engine bug on this card/driver (RTX 4070 Ti SUPER, sm_89,
driver 621.24), the same class as <https://github.com/Edge0-AI/Edge0/issues/244>
("deadlocks on ... sm_89"). There is no newer Windows engine than 0.3.0
(released 2026-11-17), so the options are (a) report it upstream with this log,
(b) build `edge0-strata` from `main` with the CUDA 13 toolkit and test a newer
commit, or (c) wait for a 0.3.x engine release. The roster entry and the
`edge0` family stay in place - they are what an updated engine will need.

## Licence

The framework is Apache-2.0 and `edge0-strata` is MIT, but the **model** is
under the Edge0 Community Model License 1.0: personal, research and internal
use, and commercial use of outputs, are allowed; selling the model, paid
distribution, commercial inference services, or an independent commercial
coding/office assistant built on it need Edge0's written permission. The Qwen
Community License terms for the base model are retained. Setup prints the
licence before installing.

## Where the pieces came from

- Engine: `edge0-strata` at Edge0's `v0.3.0` bundle, engine build 0.3.0
  (`engine-edge0/strata.exe`); its merge base with upstream Strata is commit
  `c62d5e3a15b40ea51c96aae9e8d36928965f53ab` (2026-10-31), so it is newer than
  this tree's vendored `v0.1.45` pin and older than the 0.1.62 engine in
  `engine/`.
- Pack: `Edge0/Edge0-145B-q3k` at revision
  `4bebcc0f9390c6eb13384b8463ac75722f5ff703`, pinned in `HF_REVISIONS`
  (`setup.py`).

[Back to the README](../README.md) - [Engines](ENGINES.md) - [Backends](BACKENDS.md)
