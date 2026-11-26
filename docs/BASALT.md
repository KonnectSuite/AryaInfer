# The Basalt lane

Basalt is a separate inference engine built from [jesdga95/basalt](https://github.com/jesdga95/basalt): a Strata fork
targeting Blackwell (`sm_120`) with its own model container, `.basalt`. On the RTX PRO 2000 Laptop host it runs
Qwen3.8-Flash-Next UD-IQ1_S faster than the GGUF lanes do, so AryaInfer manages it like any other lane: one server,
one web app, one API, the model picked from the roster.

The engine is pinned in `engines.json` and installed by `setup.py` on request, so a fresh clone gets it the same way it
gets Strata. The *models* are not: a `.basalt` container is 26-70 GB, so it stays a per-machine file that
`tools/basalt_import.py` registers.

## Installing the engine

```text
python setup.py --repair-engines --with-basalt
```

That downloads the pinned release (`basalt-v0.5.7-windows-x64.zip`, 70,553,484 B, sha256 `dfb71d0a…122881`, or the
Linux tarball), checks the digest, and installs it into `engine-basalt\`. Basalt's releases ship no `BUILD.json`, so
`engines.json` carries a `record` for it: the version to install and check against, and `"flat": "bin"` — the archive
nests its four binaries one folder down, and they are moved up beside the `LICENSE` and `THIRD_PARTY_LICENSES` the
install keeps. `setup.py` writes the `BUILD.json` the rest of the program reads, with `archs: []` because the archive
does not name the architectures it was built for, so no card is refused on architecture alone. Without `--with-basalt`
nothing is downloaded and the default install is unchanged; the Engines page shows Basalt as *opt-in* either way.

The engine itself is the same 0.5.7 either way, so a checkout that already has a `basalt.exe` can skip the download:
copy it into `engine-basalt\` with a `BUILD.json` saying `{"version": "0.5.7"}` and `manifest_installed()` accepts it.

**The expert profile.** Basalt places experts from a profile it keeps in `data/profiles` *above its own binary*, and it
refuses to start when the one for the model's shape is absent:

```text
basalt: error: expert profile ...\AryaInfer/data/profiles/qwen4exp-48x512.prof is missing: data/ must sit
next to bin/ (the engine reads data/profiles from the directory above its own executable), so run the binary
from its install folder, or pass --expert-profile
```

A release archive carries no `data/`, so an install gets one of three ways: copy `data/profiles` from an install that
has it, let `basalt-bench` build one for the model (its own tool, minutes per shape), or pass the file explicitly.
`tools/basalt_import.py` does the last: it looks for `data/profiles` above the binary and writes
`--expert-profile <arch>-<layers>x<experts>.prof` for the container it imported, so the lane starts whether the install
kept `bin\` or was flattened.

## What AryaInfer does with it

| Part | File | What it does |
| --- | --- | --- |
| Manifest pin | `engines.json` (`basalt`) | version, release asset, size and digest, and the `record` that stands in for the missing `BUILD.json` |
| Installer | `setup.py` (`_stage_unrecorded`, `--with-basalt`) | unpacks the release, flattens `bin\`, keeps the licence files, writes the `BUILD.json` |
| Container reader | `tools/basalt_model.py` | reads the `.basalt` header, the section table and the JSON metadata; exports the five tokenizer files |
| Importer | `tools/basalt_import.py` | writes a `strata-*.json` run config from a `.basalt` file, optionally taking the engine settings from Basalt's own `official_config.json` |
| Roster | `serve/models.py` (`_basalt`) | the backend, display name, size label, quantisation, context, draft-head and layered/vision flags, RAM and VRAM estimates |
| Engine class | `serve/server.py` (`basalt_engine`) | marks the process as a Basalt lane: same line protocol, no `SAVE`/`RESTORE` - the version comes from the engine's own `INFO engine=` |
| Settings page | `serve/configschema.py` | the `basalt` engine family and the 107 long options its own `--help` lists |
| Engines page | `serve/engines.py` | a pinned card like the others, plus *your build* cards for any binary `engines.json` does not own |
| Tests | `tools/test_basalt_model.py`, `serve/test_models_basalt.py`, `tools/test_setup_engines.py` | 24 tests over a synthetic container, the importer, the roster, the family, and installing a release that carries no `BUILD.json` |

Nothing else changes: chat, thinking, tools, the Anthropic and OpenAI APIs, the picker, the web app and the run-config
editor all go through the same code as the other lanes.

The Engines page is a census of `engines.json`, so an engine it does not pin had no card at all: the page described a
checkout that was not the one running. It now reads the run configs as well and adds a card for any binary the manifest
does not own — the binary's real path, `not pinned · your build` where a pinned version would go, and the models that
use it. Repair leaves those alone, and a binary that has gone missing is marked missing rather than dropped. A run
config pointing at a manifest engine still gets one card, not two. With the pin above, Basalt is the first kind of
card; the second kind covers a build the owner compiled themselves, which takes precedence.

## Getting a model onto another PC

The engine travels with the checkout; the model does not. Two ways to get one:

- **Copy the container.** `models\Qwen3.8-FN-UD-IQ1_S.basalt` is a single file (70,405,386,113 B here). Put it
  anywhere on the other PC — an external drive, or `PolyStrata-data\models\` if that tree exists there — and run the
  importer against it with `--exe engine-basalt\basalt.exe`.
- **Build it from a GGUF.** Basalt's own checkout has the converter (`tools/`, `python -m tools.convert …`) and the
  same 70 GB `.basalt` comes out of a Qwen3.8-Flash-Next quant plus its tokenizer; the container is dense+experts+gguf
  sections, so it needs the GGUF and about twice its size in free disk. Its `README.md` is the current word on that;
  nothing here re-derives it.

Either way the last step is `tools/basalt_import.py`, which writes the run config and exports the tokenizer; the picker
then shows the model and the server starts `engine-basalt\basalt.exe` for it. On a card under 8 GiB the flags that
matter are `--kv q4_0` and `--vram-reserve-mib`, both of which the importer sets from what it finds.

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
- `--expert-profile` naming the profile for the file's shape (`<arch>-<layers>x<experts>.prof`, found under
  `data/profiles` above the binary). The engine would otherwise look for `data/profiles` above *its own* binary and
  refuse to start; naming the file also survives a flattened install, which is what `--with-basalt` produces;
- `cwd` = the folder that owns `data\`, so a profile that is not named is still found the default way;
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