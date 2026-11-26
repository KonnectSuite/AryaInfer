# Community benchmark on NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU

Inkling 2 Mini on the native `strata-inkling` engine, with the SQ-10 pack, on an
8 GiB card. Measured 2026-11-25. Speed plus the three checks a server needs to be
usable (chat, picture, tool call).

## Hardware and software

- GPU and VRAM: NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU, 8,151 MiB
  (sm_120, compute_cap 12.0)
- CPU: Intel(R) Core(TM) Ultra 7 265H (16 cores, 16 threads); installed RAM: 63.43 GiB
- OS: Windows 11 (10.0.26300); GPU driver: 597.01; CUDA: 13.5
- Engine: `engine-inkling\strata-inkling.exe`, built on this host for arch 120
  (`engine-inkling\build.ps1`). `--version` prints `strata-inkling 0.1.67`;
  `BUILD.json` records version 0.1.68, archs [120], CUDA toolkit 13.5
- Model: `Inkling-2-Mini-SQ-10.strata` 10,471,526,400 B
  sha256 `ac4d452ad03e4930abd9d46f9c5eec22b2f75a1da45a1e49bd24ccd58b065934` and
  `Inkling-2-Mini-Vision.strata` 636,526,592 B
  sha256 `6589eff47f9c20bc3a032faa3d449f10bf4f04a84cc6b2ee8a44d51d2b6fc677`, both from
  `https://huggingface.co/strata-engine/Inkling-2-Mini-Strata/resolve/main/` and both
  verified against `tools/release_grid/models.lock.json` after download
- Background workloads and power limits: not recorded

## Model and configuration

`--info` on the pack:

```text
arch=inkling2_loop format=strata build=SQ-10 layers=24 visits=48 hidden=2304 vocab=200058 experts=128 eos=200006 drafter=dspark images=1 image_pad=200054 parallel=64 spec_opts=1
```

The run config the server uses:

```text
strata-inkling.exe --serve --native Inkling-2-Mini-SQ-10.strata --vision Inkling-2-Mini-Vision.strata --max-context 262144 --kv k8v4 --kv-offload auto --draft off --vram-experts-gb 5.5 --parallel 1
```

## What the card does with it

From the engine log (`engine-log-excerpt.txt`):

- trunk 1.87 GB in 0.44-0.74 s; experts 1,169 in VRAM and 1,903 in host RAM in
  3.15-3.99 s; `sm120_tc=1`
- host expert arena 8.60 GB pinned, inside `min(16 GiB, 35% of the available RAM)`
  with 49.1-51.4 GB available
- `InkTier` adaptive tier on: 4 expert classes, pool 3.13 GiB, a round every 4
  tokens and 16 swaps; during a real 262K session it ran 2,024 rounds and 25,949 swaps
- 1,881 MiB free after the experts; runner + K/V took 1,272 MiB; DSpark 76 MiB,
  leaving 533 MiB free, or 609 MiB with `--draft off`
- cold-expert launch probe chose the CPU lane: 23.2-23.5 ms/token against
  30.3-34.6 ms/token to copy them into the card
- at `--max-context 262144` the engine maps `global KV = 10496 VRAM + 251648 mapped
  host tokens (3071.9 MiB host RAM)`, which is about 12 KB a token. The maintainers'
  SQ-15 record on the 16 GB card describes Inkling K/V as ~110 KB a token; on this
  host the engine's own line says something nine times smaller, and that difference
  is not explained here.

## Decode and prefill, `--bench --prompt-len N --gen 64`

Medians. `--kv k8v4 --vram-experts-gb 5.5`.

| Prompt | Draft | Prefill tok/s | Decode tok/s |
| --- | --- | ---: | ---: |
| 2,048 | off | 980.8 (2.09 s) | 29.1 |
| 2,048 | auto | 1,030.8 (1.99 s) | 20.3 (19.4-20.3) |
| 8,192 | off | 922.1 (8.88 s) | 28.5 |
| 8,192 | auto | 907.5 (9.03 s) | 36.3 |
| 32,768 | off | 736.8 (44.47 s) | 19.2 |
| 32,768 | auto | 737.3 (44.44 s) | 13.8 |

`--parallel 4 --draft auto` at 2,048: 54.9 tok/s aggregate, 13.7 per slot.

Drafting pays only in the middle on this card: +7.8 tok/s at 8,192, −8.8 at 2,048 and
−5.4 at 32,768. The shipped config therefore runs `--draft off`, because 32K is the
length the agent traffic on this host actually sends.

For comparison, the maintainers' SQ-15 record on the 16 GB RTX 4070 Ti SUPER reports
2,122 prefill / 52.9 decode at 8,192 and 1,843.5 / 48.9 at 32,768 with the shipped
config. Different card and different pack, so the two records are a shape, not a
ranking: this card keeps 1,169 experts on the card where that one keeps 2,483.

## Through the server

`serve\server.py --engine strata --config strata-inkling-2-mini-sq-10.json --port 8080`:

- `GET /api/models` in 1.36 s with all 10 configs listed
- `GET /health` → `{"status":"ok","max_context":262144,"model":"inkling-2-mini-sq-10","images":true,"loaded":true}`
- a chat request: 25 prompt tokens, 57 completion tokens, 2.66 s
- a 448×320 PNG rendered locally with the text `HELLO 42`, sent as a base64
  `image_url`, read back correctly in 10.07 s
- `tool_choice=required` returned `finish_reason=tool_calls` with `{"a": 2, "b": 2}`
- switching to it and back through `POST /api/models/load` took 9 s and 10 s

## Correctness and limitations

Bench medians are of 2-3 runs; the per-run engine lines were not kept, so
`results.json` carries the medians and the ranges where more than one run was
recorded. Prompt sizes are the engine's own `--prompt-len`, not real conversations.
The vision check proves the encoder reads a picture through the server; it does not
score accuracy. What this host did not test: `--vram-experts-gb` other than 5.5 (the
value that leaves the card 533-609 MiB free), `--parallel` above 4, thinking effort
levels, and the SQ-15 and SQ-20 packs.
