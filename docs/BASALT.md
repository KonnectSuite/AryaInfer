# The Basalt lane

Basalt is a separate inference engine built from [jesdga95/basalt](https://github.com/jesdga95/basalt): a Strata fork
targeting Blackwell (`sm_120`) with its own model container, `.basalt`. On the RTX PRO 2000 Laptop host it runs
Qwen3.8-Flash-Next UD-IQ1_S faster than the GGUF lanes do, so AryaInfer can manage it like any other lane: one server,
one web app, one API, the model picked from the roster.

The engine is not shipped, vendored or pinned by this repository. AryaInfer reads its model files, writes a run config
for it, and classifies its process; the binary and the models stay where the user built them.

## What AryaInfer does with it

| Part | File | What it does |
| --- | --- | --- |
| Container reader | `tools/basalt_model.py` | reads the `.basalt` header, the section table and the JSON metadata; exports the five tokenizer files |
| Importer | `tools/basalt_import.py` | writes a `strata-*.json` run config from a `.basalt` file, optionally taking the engine settings from Basalt's own `official_config.json` |
| Roster | `serve/models.py` (`_basalt`) | the backend, display name, size label, quantisation, context, draft-head and layered/vision flags, RAM and VRAM estimates |
| Engine class | `serve/server.py` (`basalt_engine`) | marks the process as a Basalt lane: same line protocol, no `SAVE`/`RESTORE`, no `BUILD.json` - the version comes from the engine's own `INFO engine=` |
| Settings page | `serve/configschema.py` | the `basalt` engine family and the 107 long options its own `--help` lists |
| Engines page | `serve/engines.py` (`_custom`) | a card of its own, marked *your build*, because `engines.json` does not pin it and nothing installs it |
| Tests | `tools/test_basalt_model.py`, `serve/test_models_basalt.py` | 22 tests over a synthetic container, the importer, the roster and the family |

Nothing else changes: chat, thinking, tools, the Anthropic and OpenAI APIs, the picker, the web app and the run-config
editor all go through the same code as the other lanes.

The Engines page is a census of `engines.json`, so an engine it does not pin had no card at all: the page described a
checkout that was not the one running. It now reads the run configs as well and adds a card for any binary the manifest
does not own — the binary's real path, `not pinned · your build` where a pinned version would go, and the models that
use it. Repair leaves those alone, and a binary that has gone missing is marked missing rather than dropped. A run
config pointing at a manifest engine still gets one card, not two.

## Installing a model

```text
python tools/basalt_import.py --model C:\basalt\models\Qwen3.8-FN-UD-IQ1_S.basalt ^
       --exe C:\basalt\bin\basalt.exe ^
       --from-config C:\basalt\official_config.json
```

That writes `strata-basalt-qwen38-ud-iq1_s.json` next to the server, exports the tokenizer into
`PolyStrata-data\packs\basalt-qwen38-ud-iq1_s\tokenizer`, and prints the id the picker will show. `--print-only`
shows the config without writing anything; `--force` replaces an existing one.

Facts the importer takes from the file rather than guessing:

- the context, unless `--max-context` or the source config says otherwise (this host: 131,072 for 262,144 trained);
- `--kv q4_0`, the value Basalt accepts for a card this size (its other choices are `fp16`, `int8`, `k8v4`);
- `--suffix-draft` only when the file carries a draft head (`mtp/`). Basalt drafts from that head even without the
  flag, so the flag is a hint, not a requirement;
- `cwd` = the folder above `bin\`, because the engine resolves `--expert-profile` against the working directory;
- `lib_dirs` = the CUDA 13 `bin` folders the binary needs on this host.

Images are off in this lane. The containers carry a vision encoder (`vision/mmproj`, 0.91 GB in both files) and the
engine can use it in-process, but the server has no path that hands an image to an engine's own encoder, so switching
it on would reserve memory for a feature the page cannot reach. `vision` stays out of the config.

## Measured on this host

RTX PRO 2000 Blackwell Generation Laptop GPU (8 GiB), Intel Core Ultra 7 265H, 63.4 GiB RAM, Windows 11, CUDA 13.5
toolkit, engine `basalt.exe` 0.5.7, model `Qwen3.8-FN-UD-IQ1_S.basalt` (70,405,386,113 B), `--max-context 131072`,
`--kv q4_0`, `--resident-experts`, `--vram-reserve-mib 320`.

Through `serve/server.py` with `tools/strata_bench.py` (3 runs, medians):

| Test | Result |
| --- | --- |
| Short chat decode | 55.9 tok/s (52.3-69.2, n=9), first token 0.51 s |
| 4K prompt, fresh | 1,218.2 tok/s prompt, first token 3.37 s |
| 16K prompt, fresh | 1,211.3 tok/s prompt, first token 13.36 s |
| Agent session, follow-up turns | 45.5 tok/s decode, first token 3.80 s, cache hit 69.3 % |
| Load | 24.8 s to `READY`, 365 MiB VRAM free afterwards |

The same three prompt shapes sent to Basalt's own server and to AryaInfer's (fresh prompt every run, so nothing is
cached): 4K prompt 1,071 and 1,059 tok/s on Basalt's server against 1,059 and 1,059 here; 16K prompt 1,066 and 1,059
against 1,076 and 1,063; decode 47-67 tok/s on both. The engine is the same binary in both cases, so what that
measures is the server in between: no difference beyond run-to-run noise.

Records: `bench/results/2026-11-26-community-rtx-pro-2000-blackwell-generat-basalt-qwen38-ud-iq1-s/`.

## The Coder container does not run here

`Qwen3.8-FN-Coder-IQ1_M.basalt` (61,519,659,898 B, no draft head) kills the engine on its first prompt on this card.
The engine logs a verification window that never completes:

```text
basalt verify: window up to 2 tokens, 52.2 MiB of device buffers
basalt serve: 385 MiB of VRAM free with everything loaded
basalt serve: error: verify: timed out at layer 33; device plan: ring 33 published (entries: VRAM 1, peer 0, CPU 9),
                      host flag 33; its GPU waits were released but the GPU did not finish within 5 s
basalt serve: error: the GPU did not finish a released window: ending without the CUDA teardown
```

Measured seven ways, driven by AryaInfer's own `StrataEngine` with no HTTP server involved, so the port cannot be the
cause: `--kv q4_0` (layers 2 and 33), `--vram-reserve-mib 700` (36), no `--resident-experts` (9), `--kv k8v4` (21),
`--max-context 8192` (6), `--pool-workers 4` (1). The layer wanders, the prompt is the trigger, and the UD container
with the identical flags answers in 1.25 s. `--kv q8_0` is refused by the engine itself
(`--kv must be fp16, int8, q4_0 or k8v4`).

The run config for the Coder is kept at `configs-unused\strata-basalt-qwen38-coder-iq1_m.json` so the picker does not
offer a model that always fails. Move it back beside the server when a later Basalt fixes this.

## What was not measured here

- Images through the Basalt lane (off by design, see above).
- A second Basalt model that works: only the UD container was run to completion.
- Basalt's own server features that AryaInfer does not use (batch slots `BGEN`/`BDONE`, `SLEEP`/`WAKE`, `CONV`).
- Any host other than this one.

## Credits

Basalt is [jesdga95/basalt](https://github.com/jesdga95/basalt), MIT, built on
[Strata](https://github.com/Niko1221/Strata) by Niko1221, with kernels from Infernix and ggml/llama.cpp. AryaInfer
neither ships nor modifies it; this lane is a reader for its model format and a run config that points at it.