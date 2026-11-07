# NInfer engine (experimental)

A second backend next to `aryainfer` and `strata-poly`: the pinned
[roofkid/ninfer-4080](https://github.com/roofkid/ninfer-4080) engine
(branch `rtx4080-port`, commit `2469b5752672ad597055af61fe28e8e7ced20056`)
with a small shim that speaks AryaInfer's engine line protocol. The Python
server still renders the chat template, applies the thinking budget, parses
tool calls and serves the web app; the engine only turns prompt ids into
generated ids.

Status: opt-in, text only. The stock `aryainfer` and `strata-poly` paths are
unchanged; nothing in `serve/` changed for this backend.

## What it needs

- The GSQ3 artifact `qwen3_8_27b_gsq3.ninfer` (13,330,776,576 bytes,
  SHA-256 `c6f27073393e5bcc629489420470d71f52a27553bfc5c360fef07a25b3b550d7`)
  from `roofkid/Qwen3.8-27B-GSQ3-NInfer`, put in
  `C:\AI\Strata-data\models\qwen3_8_27b_gsq3.ninfer`.
- The Qwen3.8 tokenizer folder, `C:\AI\Strata-data\models\qwen38-27b\tokenizer`.
- `engine-ninfer/ninfer-engine.exe`, built by `engine-ninfer/build.ps1`
  (Visual Studio 2022, CUDA 13.1, vcpkg with ffmpeg and curl, and the
  vendored NVTX v3.1.0 headers).
- The run config `strata-qwen3.8-27b-ninfer.json` (port 8088, 131072 context,
  `rk4v4-e8` KV, MTP with three drafts).

Start it like any other model:

```
python serve\server.py --engine strata --config strata-qwen3.8-27b-ninfer.json --port 8088
```

`/health` reports the model as `qwen3.8-27b-ninfer`, `max_context` 131072.
The model also appears in `/v1/models` for a server started with
`switch_on_request`.

## Measured on this host

RTX 4070 Ti SUPER 16 GB, i9-14900KF, 64 GB RAM. Artifact above, 131072
context, `rk4v4-e8` KV, MTP draft 3, `--prefill-chunk 2688`, no CUDA graphs
(see the patch note), benchmark prompts from `bench/fixtures/bench_corpus.ids`
(65,536 ids) repeated three times where a longer prompt was needed, `-r 2
--warmup 1`, `--ngram off`.

| prompt tokens | prefill tok/s | decode tok/s |
| ---: | ---: | ---: |
| 8,192 | 2,039 | 115.3 |
| 32,768 | 1,855 | 109.8 |
| 65,536 | 1,672 | 103.3 |
| 98,304 | 1,535 | 100.2 |
| 130,816 | 1,358 | 89.0 |

The benchmark corpus repeats token ids, so its MTP acceptance is 96-100% and
its decode figure is optimistic. Real prose measured through the CLI was
74.7 tok/s (47.2% acceptance, 2.41 tokens per round). Through the HTTP server
short answers decode around 110-130 tok/s.

For comparison, the same host measured the Qwen3.8 27B AQ3 model on
`aryainfer` at 1,229 / 1,063 / 583 prefill tok/s at 8K / 32K / 128K and
88.3 / 80.5 / 68.4 decode tok/s. NInfer's prefill is about 1.7x / 1.8x / 2.3x
faster there; its long-context decode is ahead of AQ3, its short real-prose
decode is roughly parity.

Memory at 131,072: weights 10.91 GiB, sequence state 2.44 GiB, workspace peak
about 400 MiB, 761 MiB free after startup. The engine starts with 131,072
context in this config.

Prefix reuse works for repeated conversations: a 776-token prompt reused 775
tokens on the second identical request, prompt time 653.6 ms -> 36.4 ms
(18x), decode about 126 tok/s. The shim asks for two device state slots and
four private continuations in `engine-ninfer/shim/main.cpp`; with the derived
defaults (one slot) a finished session is not device-resident, the reuse
candidate is only expandable and the planner never selects it.

## What is not supported

- **Vision**: no `vision` key in the config, images are off. The shim only
  implements the `GEN` command.
- **Embeddings**: `GENI` returns an error.
- **Repetition penalties**: the shim passes temperature, top_p, top_k, min_p
  and seed, but not `penalty_repeat`, `penalty_present` or `penalty_freq`.
  The default config has presence 0.0, so the default path is unaffected; a
  request that sets a repetition penalty does not get it.
- **n-gram speculation**: the draft mode is forced off; only MTP is used.
- **Context beyond 131,072**: the benchmark needs prompt + generation + 6
  tokens of headroom, so the largest benchmark prompt was 130,816.

## Patches

`engine-ninfer/patches/0001-ninfer-windows.patch` carries the changes needed
on this host:

1. A portable 128-bit multiply (`src/core/u128_math.h` and four call sites)
   because MSVC x64 has no `unsigned __int128`.
2. Windows logging (`_getpid`, `localtime_s`, console width) instead of
   `unistd.h` and `sys/ioctl.h`.
3. A no-op `cuda_profiler_api.h` (CUDA 13 keeps the functions in the driver
   API, not `cudart`).
4. Explicit move-assignment bodies for the admission candidates (MSVC 14.44
   dropped the `= default` specializations).
5. Token streaming: `OutputDelta` carries text only, so the shim needs the
   accepted token ids. `TokenBatch` is added to `OutputSink` and filled from
   the request's own `generated` list.
6. A private long-anchor cache opportunity in `Frontend::prepare_tokens`, so
   a prompt whose prefix is still cached can reuse it.
7. CUDA Graph re-instantiation when `cudaGraphExecUpdate` fails on a
   speculative round whose topology changed.
8. `NINFER_ARYAINFER_SHIM` in `apps/CMakeLists.txt`, which builds
   `ninfer-engine` from `engine-ninfer/shim/main.cpp`.

The debug prints in the patch are gated by `NINFER_DEBUG_CACHE`; a normal run
is silent. `NINFER_DEBUG_CACHE=1` prints selection and planner lines to the
engine log.

The build script fetches NVIDIA NVTX v3.1.0 because CUDA 13.1.2 no longer
ships `nvtx3/nvToolsExt.h`. NVTX is profiling only; the headers compile to
no-ops unless the API is exported.

## Credits

NInfer is Apache-2.0, from `roofkid/ninfer-4080` (commit above); the GSQ3
artifact is published at `roofkid/Qwen3.8-27B-GSQ3-NInfer` and derives from
`ISTA-DASLab/Qwen3.8-27B-3Bit-GSQ`. NVTX is Apache-2.0, from NVIDIA. The
shim, patch and this note are part of AryaInfer and keep its MIT notice.
