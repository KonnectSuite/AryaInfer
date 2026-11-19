# Strata engine 0.1.62 with `--draft-cap 8` on NVIDIA GeForce RTX 4070 Ti SUPER

Measured on 2026-11-19 on this host with the repository's own harness, `.tune/bench.py`, interleaved A/B against the engine in production here (0.1.59). Speeds are the engine's own timings from its `--serve` line protocol. Speed only: no correctness check was run.

## Result

Engine **0.1.62** (upstream release v0.2.16) plus **`--draft-cap 8`** replaces engine 0.1.59. Everything else in the install configuration is unchanged.

| Workload (fresh prompt) | 0.1.59 prefill | 0.1.62 + cap 8 | Δ | 0.1.59 decode | 0.1.62 + cap 8 | Δ | Draft accept |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 4K prompt | 2,079 tok/s | 2,021 tok/s | **−2.8 %** | 107.2 tok/s | 127.9 tok/s | **+19.3 %** | 0.913 → 0.907 |
| 16K prompt | 2,756 tok/s | 3,319 tok/s | **+20.4 %** | 114.6 tok/s | 109.4 tok/s | −4.5 % (noise) | 0.933 → 0.917 |
| 32K prompt | 3,246 tok/s | 3,417 tok/s | **+5.3 %** | 95.8 tok/s | 95.7 tok/s | ±0 | 0.831 → 0.879 |
| 96K prompt | 3,243 tok/s | 3,412 tok/s | **+5.2 %** | 72.3 tok/s | 94.9 tok/s | **+31.3 %** | 0.725 → 0.793 |

First-token latency follows from the prefill column: 16K 5.90 s → 4.94 s, 32K 10.09 s → 9.59 s, 96K 30.2 s → 28.7 s, 4K 1.97 s → 2.03 s.

The prefill gain is the engine's, not the flag's: a run without `--draft-cap` (`.tune/results/phase3.json`) shows the same +20.4 % / +5.1 % / −2.1 %. The flag only recovers the decode the new engine loses with the dflash2 defaults on sm_89, where `--draft-cap` otherwise falls back to `--spec` (4).

## Hardware and software

- GPU: NVIDIA GeForce RTX 4070 Ti SUPER, 16 GiB VRAM, compute capability 8.9, driver 610.88
- CPU: Intel Core i9-14900KF (8 performance + 16 efficiency cores, 32 threads); AVX-2 expert kernels, no AVX-512
- RAM: 63.8 GiB; storage: SSD, model files on C:
- OS: Windows 11 (10.0.26200)
- Engine: 0.1.59 (old) vs 0.1.62, `BUILD.json` commit `1d295787b365`, CUDA 13.0, archs 75/86/89/120
- AryaInfer branch `perf/qwen38-strata-engine`

## Model and configuration

- Model and quantization: qwen3.8-flash-next-iq3_xxs (70.6 GiB in two shards, 43 GB PLE table)
- Context: 262,144 tokens; `--kv int8`, `--kv-resident 32768`, `--expert-cache auto`, `--prefill auto`, `--spec 4`, `--mtp`, `--draft dflash2`, single GPU
- The two arms differ only in the engine binary and the added `--draft-cap 8`.

```text
strata.exe --pack <packs>\iq3_xxs --native <shard 1 of 2> --ple-gguf <shard 2 of 2>
  --expert-profile <repo>\data\expert-profile.bin --expert-cache auto --prefill auto
  --spec 4 --mtp <mtp>\rt --kv int8 --max-context 262144 --kv-resident 32768
  --conversation-cache-mib 4096 --vram-reserve-mib 2048 --vision --pcie-frac 0.20
  --spec-min-p 0.70 --pool-workers 15 --adapt-every 1 --adapt-swaps 160 --adapt-decay 0.97
  --draft dflash2 --draft-model <models>\dflash2-flash-next\Qwen3.8-Flash-Next.dflash2.pack
  --draft-cap 8
```

## Method

`.tune/bench.py` starts `strata.exe --serve` directly and drives it over the engine's own line protocol, so the HTTP layer is not in the numbers and engine loading is not timed. For every arm: load, one discarded warm-up request per case, then 5 measured requests (2 at 96K). **Each measured request uses a different prompt of the same token count** — paragraphs drawn by a tag-seeded shuffle from repository prose (`docs/**/*.md`, `src/**/*.cpp`, `README.md`, `AGENTS.md`) and tokenised with the pack's tokenizer — so the conversation cache cannot serve a measured rep. `prefill_tok_s = prompt_read · 1000 / prompt_ms` with `prompt_read` equal to the full prompt, and decode comes from the engine's `DONE` line. Arms are interleaved A/B with the old engine repeated at the end as a noise control; the table is the median of the arms at each size. Reproduce with:

```text
.venv\Scripts\python.exe .tune\bench.py --sweep .tune\sweeps\phase5.json --sizes 4096,16384,32768 --reps 5 --max-new 384 --out .tune\results\phase5.json
.venv\Scripts\python.exe .tune\bench.py --sweep .tune\sweeps\phase6.json --sizes 98304 --reps 2 --max-new 64 --out .tune\results\phase6.json
.venv\Scripts\python.exe .tune\analyze.py .tune\results\phase5.json p5-old,p5-old2
```

## What did not help

Every configuration arm tried against 0.1.59 on cold prompts (`.tune/results/phase1b.json`) was inside the ±3 % noise floor or worse: `--vram-reserve-mib 700` +1.5 / +1.7 / **−3.9 %** (4K/16K/32K), `--vram-reserve-mib 1000` −0.3 / −4.7 %, `--mtp-q4 proj|all`, `--spec-min-p 0.50`, `--adapt-async 1`, `--no-hit-poke`, `--expert-cache-per-layer`, `--pool-tasks 192`, and the `--prefill auto:16384|32768` chunk arms. On 0.1.62 the PLE knobs (`--ple-inflight 512`, `--ple-row-cache 8388608`) and `STRATA_ADAPT_FETCH=1|2` were also no-ops.

**Retraction:** the earlier `.tune/SETTINGS-REPORT.md` claim that `--vram-reserve-mib 700` buys “prefill +13.5 % / +15.0 %” does not reproduce. The old harness reused one prompt per case, so after the warm-up request every measured rep was served from the conversation cache and “prefill” timed a short tail read (a 32K case reported `prompt_read 3072` of 32768). With one prompt per rep the effect disappears. `.tune/bench.py` was fixed and the report should not be trusted for that arm.

## Correctness and limitations

No correctness check was run; speculative decoding is verified by the engine, so flag changes cannot alter the sampled output, but that was not re-measured here. Decode rates move ±5-15 % between arms because each arm reads different prompt text; only the 4K (+19 %) and 96K (+31 %) decode gains clear that floor — 16K and 32K decode are a wash. The 96K row has 2 reps. Background load and power limits were not recorded. Vision was not exercised (the configuration's vision binary was updated together with the engine).

Per-request data for every arm: `results.json`. Engine start-up lines of a 0.1.62 run: `engine-log-excerpt.txt`.

## Rollback

Point `strata-iq3_xxs.json` back at `C:\AI\Strata-data\engines\strata-0.1.59\strata.exe` (and its `strata-vision.exe`), drop `--draft-cap 8`, and restore that folder's entry in `lib_dirs`. The 0.1.59 folder was kept intact; 0.1.62 lives beside it in `C:\AI\Strata-data\engines\strata-0.1.62`.
