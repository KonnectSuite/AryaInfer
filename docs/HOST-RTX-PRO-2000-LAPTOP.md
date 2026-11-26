# This laptop: what it runs, and what it measured

> **The Coder was removed from this machine on 2026-11-13**: the model shards, its
> pack, the MTP runtime, the vision encoder and `strata-coder-iq1_m.json` were
> deleted (63.08 GB freed), because at 8 GB of VRAM it ran at 5-33 tok/s with a
> 3-4 minute first token at 100K context. This page stays as the measured record of
> what it did on this hardware. It was installed again on 2026-11-24 at IQ1_M and
> now measures 22.4 tok/s; see "Models installed 2026-11-24". `qwen36-UD-Q4_K_M`
> recorded 73.7 tok/s on 2026-11-13; the same config re-measured on 2026-11-24 gave
> 20.0 tok/s over 96 new tokens (expert cache 45.4% hit), which is the number to
> compare a Q4 MoE against on this 8 GB card. `strata-qwen36-200k.json` and
> `models\qwen36-UD-Q4_K_M\` are what remain: 21.1 GB, and 73.7 tok/s measured on
> the same day through the same server. The poly engine was rebuilt from the
> 2026-11-24 upstream release (`v0.2.20-poly.4-hotfix`, which runs Inkling 2) and
> `strata.exe` from the newer Strata snapshot on 2026-11-24; see "The 2026-11-20
> engine update" and "The 2026-11-24 Strata update" below.

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
| `engine\strata.exe` | 0.1.67 | release `strata-engine-0.1.67-windows-x86_64-cuda-cuda13.tar.gz` from [Niko1221/Strata](https://github.com/Niko1221/Strata/releases/tag/v0.2.21), installed by `setup.py --repair-engines` with its SHA-256 checked | 181,013,504 B |
| `engine-poly\strata-poly.exe` | 0.2.20 | upstream [simplexai-labs/PolyStrata](https://github.com/simplexai-labs/PolyStrata) tag `v0.2.20-poly.4-hotfix`, commit `36e654b1b`, rebuilt here 2026-11-24 | 54,883,840 B |
| `engine-arya\aryainfer.exe` | 0.1.45 | this fork's release `engines-2026.11` (`aryainfer-windows-x64-cuda13.zip`), archs 75/80/86/89/120 | 367,995,392 B |
| `engine-inkling\strata-inkling.exe` | 0.1.68 | built here 2026-11-25 by `engine-inkling\build.ps1` from Strata main at `2af30cc`, CUDA 13.5, `sm_120` | 11,522,048 B |

`engine\strata.exe` is the pinned release binary as of 2026-11-25:
`python setup.py --repair-engines` downloaded it from Strata's `v0.2.21` release
and verified `b0bdbed3…a19880` before unpacking. It carries cubins for sm_75,
sm_86, sm_89 and sm_120 plus PTX, so this card is covered without a local build.
The 0.1.66 binary compiled here on 2026-11-24 (64,620,032 B, `sm_120` only,
`build-strata-0.1.66\build.cmd`, 144 of 144 units) is kept in `engine\.previous\`
and `setup.py --rollback-engine` puts it back; `strata-0.1.63.exe` is still in
`engine\` as well. The poly engine was rebuilt the same way on 2026-11-24:
`polystrata-upstream\build-poly.4.cmd` (120 of 120 units,
`polystrata-upstream\build-poly.4`), from the poly worktree. The binaries they
replaced (0.1.63 and the 0.1.45 poly build) are in `engine-backup-0.1.63\`
and `engine-backup-poly.4\`; copying those files back restores them. The older
fork 0.1.45 and 0.1.59.1 builds are still in `engine-backup-0.1.45\` and
`engine-backup-0.1.59.1\`.

`engine-arya\aryainfer.exe` is installed because `engines.json` pins it, and
nothing here runs it: the AQ3 and Turbo quants it exists for are not on this
machine. AryaNInfer is a manual engine with no download, and there is no
`.ninfer` artifact here, so it was not installed.

The PolyStrata line is where upstream keeps its version number: the newest tag is
`v0.2.20-poly.4-hotfix` (2026-11-23), which is `main` at commit `36e654b1b`, and
the engine itself still says 0.1.66. It moved the tree into `engine/` and vendored
ggml, and it added Inkling 2 to `strata-poly` (`src/poly/inkling2.cpp`), so poly
now runs `inkling2_loop` models; the Qwen3.8 `qwen4exp` family is still not in
`src/poly`.

Neither engine was merged into this fork's source. Strata restructured the tree
again in 0.2.16 (the engine moved into `engine/`, so the build is
`cmake -S engine`) over thousands of commits against the fork's few hundred, and a
merge would have cost more than building the release in its own worktree. 0.2.16
also dropped the llama.cpp MMQ prompt kernels: every CUDA build now compiles
Strata's own, so 0.1.66 has no `strata_kq.dll` and the one 0.1.59.1 needed was
removed from `engine\` (the backup keeps it). The fork's own source, including its
`kQ4_0` KV and the AQ3 path, is untouched.

`engine\BUILD.json` and `engine-poly\BUILD.json` say `"source": "upstream"`: the
poly one names the tag and commit it was built from, the Strata one the snapshot
downloaded on 2026-11-23 (app 0.2.20, engine 0.1.66), because a downloaded zip
carries no git metadata. For `engine\`, `setup.py` sees a version
at or above its minimum and leaves the binary alone. For `engine-poly\` that was
not enough: its BUILD.json has no `src` hash of this checkout's source, so
`update_poly_engine` would have recompiled the fork's `src/poly` over the engine
on the first `START-HERE.bat`. Since 2026-11-20 that function keeps an engine
whose `source` is `upstream` (warning only when the card is another architecture
generation), and `tools/test_poly_prebuilt.py` covers it. `setup.py --build` still
compiles the fork's source over either, and after that the release line and this
page disagree again.

Nothing here repacks a model: the 0.1.45 packs under
`PolyStrata-data\packs\` are still what these engines read, and the 0.1.66 build
this page records changed no pack format.

## The 2026-11-20 engine update

What was measured, with the shipped `strata-qwen36-200k.json`, one server on port
8080 at 23:38 on 2026-11-20: the poly engine was ready in 15.2 s, put 1,788 of
10,496 routed experts in 3.2 GiB of VRAM, and decoded 77.8 tok/s on an 83-token
prompt and 95.9 tok/s on a 394-token prompt (64 new tokens each). An image request
through `engine-poly\strata-vision.exe` answered "Red" for a red 96x96 PNG in
0.52 s, 32 prompt tokens, so the image path works on this engine and this encoder.

A rested-card comparison, each arm started after 120 s idle and alternating the two
binaries: the new engine gave 78.5 and 74.5 tok/s on the short case and 88.4 and
95.2 on the mid case; the 11-13 engine gave 80.8 and 78.5, and 97.8 and 86.5. The
spread within one binary is as large as the gap between them, so this host measures
no decode difference between the two builds, which is what those 44 commits
predict. The new engine did keep more experts in VRAM: 1,788 (3.2 GiB) against
1,684 (3.0 GiB).

`strata.exe` 0.1.63 was not run: there is no Strata-native pack on this machine
since the Coder was removed, and `strata.exe --version` printing `strata 0.1.63`
is all that was measured. The release notes' new defaults (route tail skip off, a
16-token short read, `ADAPT_FETCH=2`, the 12.0 decode switches) are therefore
unmeasured here.

## The 2026-11-24 Strata update

`engine\strata.exe` went from 0.1.63 to 0.1.66, built here from the Strata main
snapshot downloaded on 2026-11-23 (`Strata-main.zip`, app version 0.2.20, engine
`CMakeLists.txt` version 0.1.66). No fetch was made: the zip is the newest Strata
source on this machine, and it carries no git metadata, so `engine\BUILD.json`
records the snapshot instead of a tag and commit. The build is
`build-strata-0.1.66\build.cmd` — the same CUDA 13.5, `sm_120`, Release, tests-off
recipe as 0.1.63 — and it compiled 144 of 144 units into `strata_core` and
`strata_kernels` where 0.1.63 compiled 132. The binary is
64,620,032 B against 66,830,848 B before, and `strata.exe --version` prints
`strata 0.1.66`. As with 0.1.63, decode, its prompt kernels and its image path are
unmeasured on this machine: there is still no Strata-native pack here, so the
version line is the whole of what was checked. The engine that was replaced is in
`engine-backup-0.1.63\`.

The poly engine moved too: `update` fetched simplexai-labs/PolyStrata (the tags
`v0.2.19-poly.1` through `v0.2.20-poly.4-hotfix`) and the newest, `main` at
commit `36e654b1b`, was built here on 2026-11-24 with
`polystrata-upstream\build-poly.4.cmd` (120 of 120 units). That release moved the
tree into `engine/`, vendored ggml and added Inkling 2 to `strata-poly`. The
engine it replaced (0.1.45, tag `v0.1.45-poly.10`) is in `engine-backup-poly.4\`.

## The 2026-11-25 update: the control center, the pinned engines, Inkling for sm_120

The fork merged `origin/main` (157 commits, 271 files) on 2026-11-25: the web app
grew a Models view, an Engines view and a Settings editor for every run config,
`engines.json` pins each engine to a release with a size and a SHA-256, and the
Inkling lane arrived (`engine-inkling\build.ps1`, `serve/inkling_kind.py`,
`serve/inkling_dialect.py`). The merge kept this page's host rows and the trellis
quant names; the fork's hand-rolled Inkling reply splitter was dropped because
upstream's dialect module does the same job.

`python setup.py --repair-engines` installed the three pinned binaries
(SHA-256 checked) and `python setup.py --check-engines` then exits 0. The Engines
view says the same thing: Strata 0.1.67 current, PolyStrata current, AryaInfer
0.1.45 current, Strata Inkling 0.1.68 manual, AryaNInfer missing.

The Strata engine moved 0.1.63 → 0.1.67 on the Coder, measured the same day with
`tools/strata_bench.py`, same config, thinking off, median of 3 runs each:

| | strata 0.1.63 | strata 0.1.67 | change |
|---|---|---|---|
| chat decode | 28.3 tok/s | 22.0 tok/s | −22% |
| chat first token | 0.76 s | 0.85 s | +0.09 s |
| 4K prompt | 451.8 tok/s | 774.4 tok/s | +71% |
| 16K prompt | 437.4 tok/s | 803.4 tok/s | +84% |
| 16K first token | 36.80 s | 20.07 s | −45% |
| agent turn first token | 11.70 s | 6.30 s | −46% |
| agent decode | 29.6 tok/s | 19.3 tok/s | −35% |
| agent cache hit | 69.39% | 69.39% | same |

So on this 8 GB card the release buys prompt speed and costs generation speed.
The two runs differ in more than the version — the release is a fat binary with
four architectures and PTX — and no knob tried recovered the decode: with
`--kv-resident` 20480 chat decode is 18.4 tok/s and agent decode 15.9, with 65536
17.1 and 16.4, so the 32768 already in `strata-coder-iq1_m.json` is the best of
the three and prefill does not move with it (774.5 and 785.6 tok/s at 4K), which
rules out KV residency as the cause. The 0.1.63 binary is still in `engine\`, so
pointing `strata-coder-iq1_m.json` back at it restores 28.3 tok/s of decode with
451 tok/s of prompt. The config now points at `engine\strata.exe`, which follows
whatever `setup.py` installs.

Gyro-S loads and answers on 0.1.67: the trellis `TQ1_0` GGUF is accepted at
172,032 context, MTP window warm-up 1,118 ms, and a 48-token request came back in
3.59 s. Its decode rate against 0.1.63 was not measured.

`engine-inkling\build.ps1` hardcoded sm_89 and the CUDA 13.1.2 folder under
`C:\AI\Strata-data`, neither of which exists here, so it now takes `-Arch` and
reads the card's compute capability from `nvidia-smi` when it is not given, falls
back to the newest toolkit with an `nvcc` under
`C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA`, and records what actually
compiled it. Built from Strata main at `2af30cc` (the commit that puts
`project(strata VERSION 0.1.68)` in `engine\CMakeLists.txt`; the `v0.2.21` tag is
still 0.1.67), it produced `strata-inkling.exe` 11,522,048 B with
`BUILD.json` archs [120] and cuda_toolkit 13.5. `--version` prints `strata-inkling
0.1.67`, which is the upstream `INKLING_VERSION` string that was never bumped, not
a stale build.

`--info` on `Inkling-2-Mini-UD-IQ1_S.gguf` reads
`arch=inkling2_loop format=gguf layers=24 experts=128 images=1 parallel=64`, so
the native engine runs the GGUF this host already has — no `.strata` download.
Engine-level bench here (`--bench --prompt-len 2048 --gen 64 --max-context 8192
--kv k8v4 --draft off --vram-experts-gb 5.5`): prefill 487.2 tok/s, decode
25.6 tok/s. The card holds 476 of 3,072 experts (1.99 GiB) and a 13.76 GB pinned
host arena for the rest; the launch probe measured the cold experts at 48.0 ms per
token computed on the CPU against 97.7 ms per token copied into the card, so they
are computed where they sit. Through the server,
`strata-inkling2-mini-native.json` (16,384 context, `k8v4`, `--kv-offload auto`,
`--draft off`) reaches READY in about 40 s and a chat request returns clean text
with `finish_reason: stop`.

What was not measured here: Inkling's native vision path (the config has no vision
section), Inkling in a long conversation, the 35B models on the new Strata engine
(they run on the poly binary, which did not change), and multi-client behaviour.

## Models installed 2026-11-20

Four more families were installed for `engine-poly\strata-poly.exe`, every one at
the trained context of 262,144 tokens, each with its own config and start script in
the checkout root. They were installed through a wrapper that keeps the upstream
poly engine: `setup.py`'s install steps would otherwise have downloaded the fork's
ready-made engine and compiled this checkout's `src/poly` over it.

| Config | Model file | Size | Smoke test |
|---|---|---|---|
| `strata-ornith-apex-i-quality.json` | Ornith-1.5-35B-A3B-APEX-MTP-I-Quality | 23.72 GB | loaded 13.6 s, 2,103 of 10,496 experts in 4.1 GiB, answered "OK" |
| `strata-qwen36-ornith-1.5-35b-a3b-apex-mtp-i-balanced.json` | Ornith-1.5-35B-A3B-APEX-MTP-I-Balanced | 26.17 GB | loaded 12.2 s, 1,913 experts, answered "OK" |
| `strata-qwen36-nail-qwen3.6-35b-a3b-ud-q4_k_xl.json` | Nail-Qwen3.6-35B-A3B-UD-Q4_K_XL | 22.36 GB | loaded 9.8 s, 2,092 of 10,240 experts in 3.7 GiB, answered "OK" |
| `strata-minicpmv-q4_k_m.json` | MiniCPM-V-4.7-35B-A3B-Q4_K_M | 21.2 GB | loaded 10.6 s, 2,512 of 10,240 experts in 4.5 GiB, answered "OK" |

This is a smoke test, not a benchmark: one chat completion each ("Reply with
exactly: OK", temperature 0), on its own port, with the 8 GB card at 6,880 MiB used.
No speed number here is worth comparing, and none was compared.

Three things a first conversation on these models shows. Nail's chat template adds
a system preamble of about 180 tokens, so the one-line prompt was 197 prompt
tokens and the model thinks before it answers: "OK" took 153 new tokens. MiniCPM-V
answers short replies inside the reasoning channel — the engine's server reports
`content: null` and puts "OK" or "4" in `reasoning_content` — which is the model's
template, not a load failure. Both Ornith sizes and MiniCPM-V start the image
encoder named in their config (`strata-vision: model files loaded in 1.7–3.2 s`).

All four configs now carry `--kv q8_0`, the setting that makes a 262,144-token
context affordable on an 8 GB card: at load Ornith quality's expert cache went from
2,103 to 2,238 of 10,496 experts (4.1 GiB, the engine's own line) and Nail's stayed
at 2,093 of 10,240 (3.7 GiB), while the attention caches cost about half the VRAM
they would in fp16. Two changes that a 16 GB template carries were not applied:
`--vram-reserve-mib 512` with `--prompt-batch 2048` took Nail's cache down to 1,790
experts (3.2 GiB), 305 fewer, so the default batch and reserve stay. Threads stay at
10, where the earlier tuning here left them. No speed is claimed for these settings
here: the power-mode section below measures what one of them writes, and the same
config measures 16 tok/s in one Windows power mode and 52–57 in another.

Both Ornith sizes are here because the request said quality or balanced or both.
Quality came through the setup family, which pins the MTP file; Balanced and Nail
have no such family entry, so they were downloaded and installed with
`--custom-gguf`, and that resolution matched them to the `qwen36` family. The
Balanced config therefore carries `--tail-skip 6` from that family; nothing has
measured whether Ornith wants it.

## Models installed 2026-11-24

Three families were added on 2026-11-24, from Hugging Face: the ISTA-DASLab Coder
at IQ1_M and Agention's Gyro-S on `strata-0.1.63.exe`, and Inkling-2-Mini on the
rebuilt poly engine (the slower `strata-inkling` route was removed the same day).

| Model | Engine | Files | Pack | Loaded | Measured |
|---|---|---|---:|---|---|
| Coder IQ1_M (`qwen3.8-flash-next-coder-iq1_m`) | `strata-0.1.63.exe` | 29,608,446,496 + 28,800,138,432 + 907,543,008 B | 1.48 GB | 23.42 GiB of experts at 5.70 GiB/s, 172,032 context, KV k8v4 | 22.4 tok/s end to end at 131K; 9.8 tok/s at 262K fp16 KV; at 172,032 with k8v4 a 200-token reply takes 1.6 s |
| Gyro-S (`qwen3.8-flash-next-gyro-s`) | `strata-0.1.63.exe` | 58,487,015,808 + 904,004,128 B | 1.54 GB | 24.02 GiB of experts, 2,068 in 2.02 GiB of VRAM, 172,032 context, KV k8v4 | 26.3 tok/s at 262K in the app (62.7% expert cache hit); at 172,032 with k8v4 a three-word reply takes 4.7 s |
| Inkling 2 Mini IQ1_S (poly) (`inkling-2-mini-poly`) | `strata-poly.exe` | 7,764,293,056 + 639,348,160 B | none (GGUF in place) | 2,225 of 3,072 routed experts in 4.4 GiB of VRAM, 172,032 context, KV q8_0, vision on | 54.7 tok/s decode in the app at 262K with a warm cache (97.8% hit); 14.75 tok/s steady from cold; vision read `HELLO 42` |
| Inkling 2 Mini Q4_K_XL (poly) (`inkling-2-mini-poly-q4`) | `strata-poly.exe` | 17,629,760,736 B | none (GGUF in place) | 851 of 3,072 routed experts in 4.1 GiB of VRAM, 172,032 context, KV q8_0, vision on | 22.5 tok/s decode direct over 64 tokens (71.9% from VRAM), 20.0 in the app over 160 tokens |

Two things had to change after the first measurements, both because the pack
streams experts over PCIe on an 8 GB card. Engine 0.1.66 runs the CPU side of that
stream about 1.6-1.7x slower than 0.1.63 on this machine: the same Coder arguments
measured 6.96 against 12.28 tok/s at 65K context, and 11.95 against 20.04 at 8K;
Gyro-S measured 7.81 against 13.91 at 4K. Its 0.1.66 configs now run
`engine\strata-0.1.63.exe` (a copy of the previous build), which still reads the
v5 Hadamard pack and needs no Q8 workaround. Second, at 131K context the draft
layer does not fit in VRAM, so the engine silently drops it and every speculative
round is wasted work — the log says `runs without the draft layer` and its own
speculation line reads `drafts accepted 0 of 93`. `STRATA_MTP_KEEP=1` (in each
config's `env`) keeps the draft at the cost of a smaller expert cache; measured on
0.1.63 it moved the Coder from 12.13 to 16.55 tok/s at 131K and Gyro-S to 15.00.
The app then measured 22.4 and 23.6 tok/s, because a chat answer amortizes the
prefill and the card was cool at the start.

The Coder's config is the one `setup.py --family coder` writes, now at 262,144
tokens (the context the host's models use) with `--kv q4_0`, `--spec 4` and the
MTP draft in `PolyStrata-data\mtp\rt`; the IQ1_M pack held 256 of its 512 experts,
as the Coder family intends. The long context is what costs speed there: at 131K
it measured 22.4 tok/s in the app, at 262K it measured 9.8, because the KV cache
leaves only 343 experts in VRAM (0.66 GiB) and the rest stream over PCIe.
Gyro-S keeps `--spec 4` and the default `data\expert-profile.bin`, because no Gyro
profile exists upstream; at 262K it measured 26.3 tok/s. Inkling's config is `strata-inkling2-mini-poly.json`; its tokenizer was
exported from the GGUF with `tools\strata_tokenizer.py`, because the `.strata` pack
carries only the chat template.

The 262,144-token context left the card too tight for Gyro-S: its log reported
`111 MiB of the card's memory are free` and Windows then pages GPU memory to system
RAM, so a long question stalled and the stuck request held the model's turn — the
next switch answered `409 busy` until it finished. Its `--vram-reserve-mib` is now
1216 (785 MiB free, 21-26 tok/s). The Coder cannot take the same reserve: at 262K,
1216 MiB leaves `0 slots` for the expert cache and the model does not start, so it
keeps 300 and loads 343 experts. All four configs also cap thinking with
`reasoning_effort: low` and `reasoning_budget_by_effort` (256 / 512 / 1024
tokens), lowered after the app's own `High` request spent 8,192 thinking tokens
(5-7 minutes at 20-25 tok/s) before any answer appeared; a request with a very
small `max_tokens` can still spend every token thinking, which the app sees as
empty content with `finish_reason: length`.

Inkling 2 on the poly engine answered with the model's own template markers
(`<|message_model|><|content_thinking|>...<|end_message|><|content_text|>...`) inside
the reply text, because nothing in `serve/` knew them. `serve/server.py` now reads
the tokenizer's `inkling2` pre as `call_format == "inkling"`, adds its turn openers,
and `inkling_events()` splits the stream at `<|content_thinking|>` and
`<|content_text|>`, drops the markers and ends the message at `<|end_message|>`.
Measured after the change: `What is 12 times 12?` → `content: "144"` with the
thinking in `reasoning_content`, and a streamed `Name the capital of France` →
`Paris` over 21 SSE chunks. At the 1024-token budget the model sometimes writes
its answer inside the thinking, after `I have thought about this long enough;
time to give my answer.`, with no `<|content_text|>` marker; `inkling_events()`
therefore holds back a suffix that could still become that sentence and treats
what follows it as the answer, so `Say hi in three words.` on `High` returned
`content: "Hi there friend"` on IQ1_S (9.3 s) and Q4_K_XL (1.9 s).

The four configs were then moved to 172,032 tokens (168K) with a smaller KV format,
because the 262K settings spent too much VRAM on the cache: Gyro and the Coder use
`--kv k8v4` (INT8 keys, rotated Q4_0 values, 816 B/cell against int8's 1,056), and the
poly Inkling configs keep `--kv q8_0`, the smallest KV format `strata-poly` offers
(fp16, q8_0, q4_0). Measured after the change on this host: Gyro-S a three-word reply
in 4.7 s at 172,032, the Coder a one-line Python answer in 1.6 s, Inkling IQ1_S
`12 times 12` -> `144` in 2.8 s, Inkling Q4_K_XL `Hello there friend` in 3.0 s. The
engine logs no low-VRAM warning at the new settings.

One tool had to be extended: Gyro's experts are stored in a Hadamard-rotated basis
(`prism.hadamard.*` in the GGUF metadata). A pack built without the rotation table
loads and answers, but the answer is plausible garbage — 120 repetitions of one
token. `tools/iq_pack.py` now writes `hadamard.txt` and marks `native_experts.txt`
v5 for such files, a port of the Strata 0.2.20 packer; the table it wrote is
byte-identical to that packer's (sha256 `0AC6508D…`), and the engine then logs
`APR pack: Hadamard-folded experts (block 128)` and answers correctly.

PolyStrata 0.2.20 (`v0.2.20-poly.4-hotfix`) runs Inkling 2: the rebuilt
`strata-poly.exe` loads the IQ1_S GGUF and measured 58.7 tok/s decode in the app at
32K (92.7% expert cache hit), 54.7 tok/s at 262K once the cache warms. The Qwen3.8
`qwen4exp` family (Coder, Gyro-S) is still refused with `is a 'qwen4exp' model,
which this engine does not run`, because `src/poly` in this release has no
`qwen4exp` loader.
Inkling's config is `strata-inkling2-mini-poly.json`; the `strata-inkling.exe`
route (native SQ-10 pack, 13.7 tok/s) and its 11.1 GB of `.strata` files were
removed on 2026-11-24, because poly runs the same model about four times faster.

Quant choice is an expert-tier question on this card, not a model-size one: at
Q4_K_XL (16.4 GB) only 851 of Inkling's 3,072 routed experts fit in 4.1 GiB of
VRAM and it decodes at 22.5 tok/s direct (20.0 in the app); at IQ1_S (7.2 GB)
2,225 fit and it decodes at 54.6 direct (58.7 in the app). The "60+ tok/s" rows
elsewhere in `docs/` were measured on the 16 GB desktop host. For comparison, the
Q4 35B MoEs on this laptop measured 20.0 tok/s (`qwen3.6-35b-a3b-ud-q4_k_m`,
expert cache 45.4% hit), 17 tok/s (Nail Q4_K_XL) and 7.8 tok/s (Ornith APEX)
through the same server on 2026-11-24, so Inkling at Q4 is not slower than they are.

Both Inkling configs now run 262,144 tokens with `--kv q8_0` and vision on, the
same context the rest of this host uses. Poly's Inkling has no KV offload, so the
context costs expert-tier VRAM and decode: 32K measured 54.6 tok/s, 262K measured
14.75 tok/s steady from cold, and a chat at 262K with the cache warm measured
54.7 tok/s (97.8% hit). Vision runs through `engine\strata-vision-inkling2v.exe`,
built from PolyStrata's `terminal\tools\vision` because that projector is the
`inkling2v` one. Sending the first image needed a server change: Inkling's template
writes `<|content_image|><|unused_200054|>`, not `<|image_pad|>`, so
`serve/server.py` now reads the marker after `<|content_image|>` when the usual
literal is absent; the 448×320 test image (`HELLO 42`) came back as `42`.

The Coder and Gyro-S vision blocks use `engine\strata-vision-0.1.66.exe`, built
from the Strata 0.1.66 snapshot's `terminal\tools\vision`; the older
`engine\strata-vision.exe` (the `qwen4exp` build that shipped with poly 0.1.45)
could not open Gyro's TQ1_0 file (`ERR cannot open the text model`), the 0.1.66
build reads it. Both models were raised to 262,144 tokens as well: the Coder
measured 22.4 tok/s at 131K and 9.8 at 262K, Gyro-S 26.3 at 262K; both read the
`HELLO 42` image correctly (the Coder answered `42` in `content`).

## Why it looked slow: the Windows power mode

Serving the Ornith quality config in Windows' Balanced power mode measured a 16.0
tok/s write (64 new tokens) and 120.8 tok/s read (480 prompt tokens) with the card
at 85–89 °C, clocks averaging 180–364 MHz and 16.1 W: the 60 W power limit (default
60, maximum 75) was not being used, because the GPU stayed under its 87 °C target by
clocking down. Setting Windows' "Best performance" mode, which drives Lenovo
Intelligent Cooling on this machine, with

    powercfg /overlaysetactive ded574b5-45a0-4f42-8737-46345c09c238

dropped the idle temperature from 83 to 78 °C in 90 seconds. The same arm then wrote
90.2 tok/s and read 295.3 tok/s at 2,150 MHz average and 29 W.

Sustained is lower, because the card heats to 85–88 °C: four back-to-back writes of
128 tokens on one server measured 52.4, 56.7, 51.8 and 54.5 tok/s at 1,477–2,400 MHz
and 36–51 W, and a repeat of the same four gave 53.7, 56.8, 50.6 and 52.2. The 8 GB
laptop row in [BACKENDS.md](BACKENDS.md) — an RTX 4070 Laptop at 32,768 tokens of
context — writes Ornith quality at 48–50 tok/s, so this host sustains at that level
and starts above it while the card is still cool.

Six flag arms under the new mode, 128 written tokens each, cooled to 70 °C or for up
to five minutes between arms (`speed_tune.py`, rows in
`model-installs-2026-11-20\speed.jsonl`): base 90.2 tok/s, `--tail-skip 6` 133.3
(read fell to 255.0), `--threads 6` 82.7, `--threads 14` 87.7, `--prompt-batch 512`
104.6, base again 53.6. The two arms that started at 86 °C are the slow ones, and the
rest sit inside that temperature spread, so no flag was adopted beyond the `--kv
q8_0` already applied. `--tail-skip 6` buys about 40% more write speed at a read-speed
cost; it is the setting upstream Strata turned off by default for quality in 0.1.63,
and nothing here measures what it costs Ornith's answers.

The overlay is an AC-power setting: on battery Windows falls back to what the mode
carries. Read it back with

    (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes').ActiveOverlayAcPowerScheme

and set "Better performance" instead with the id
`3af9b8d9-7c97-431d-ad78-34a8bfea439f`.

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
row from 0.1.45 does not automatically carry over to 0.1.59.1. Nothing in this
table was re-run on 0.1.63 or 0.1.66: with no Strata-native pack left on the
machine, both were built and version-checked but not served.

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

## Inkling 2 Mini on the native engine, with the SQ-10 pack

The native `strata-inkling.exe` built here for sm_120 ran three Inkling files
this machine had, all Unsloth GGUFs, and each one reported `drafter=none`: the
DSpark drafter is a separate file for the GGUF path, and the picture reader was a
second engine process. The `.strata` pack from
`strata-engine/Inkling-2-Mini-Strata` carries both inside it, so it was fetched
with the sizes and SHA-256 digests from the upstream release grid
(`tools/release_grid/models.lock.json`) and put beside the GGUFs:
`Inkling-2-Mini-SQ-10.strata` 10,471,526,400 B `ac4d452a…5934`,
`Inkling-2-Mini-Vision.strata` 636,526,592 B `6589eff4…c677`. SQ-10, not SQ-15:
SQ-15 is 14.35 GB and SQ-20 is 19.35 GB, and this card has 8,151 MiB.

`--info` on the pack: `format=strata build=SQ-10 layers=24 visits=48 hidden=2304
vocab=200058 experts=128 eos=200006 drafter=dspark images=1 image_pad=200054
parallel=64`. What that changes on this card, measured 2026-11-25 with
`--vram-experts-gb 5.5 --kv k8v4`:

| run | prefill | decode |
| --- | --- | --- |
| 2,048-token prompt, 64 generated, `--draft off` | 980.8 tok/s (2.09 s) | 29.1 tok/s |
| 2,048-token prompt, 64 generated, `--draft auto` | 1030.8 tok/s (1.99 s) | 20.3 tok/s |
| 8,192-token prompt, 128 generated, `--draft off` | 922.1 tok/s (8.88 s) | 28.5 tok/s |
| 8,192-token prompt, 128 generated, `--draft auto` | 907.5 tok/s (9.03 s) | 36.3 tok/s |
| 32,768-token prompt, 128 generated, `--draft off` | 736.8 tok/s (44.47 s) | 19.2 tok/s |
| 32,768-token prompt, 128 generated, `--draft auto` | 737.3 tok/s (44.44 s) | 13.8 tok/s |
| 2,048-token prompt, 64 generated, `--parallel 4 --draft auto` | 967.2 tok/s (8.47 s) | 54.9 tok/s aggregate, 13.7 per slot |

Drafting pays here only in the middle: it wins at 8,192 (+7.8 tok/s) and loses at
2,048 (−8.8) and at 32,768 (−5.4), which is the length this app actually sends.
The run config therefore ships `--draft off`. The pack also loads far faster than
the GGUF did: trunk 1.87 GB in 0.44 s and 1,169 experts on the card with 1,903 in
an 8.60 GB pinned host arena in 3.63 s, against 476 card experts and 2,596 host
experts taking 36–45 s for the IQ1_S GGUF — the GGUF path widens its experts to
canonical SF4 on the way in. A model switch through `POST /api/models/load` now
takes 9–10 s each way; the same switch on the IQ1_S GGUF at 262,144 context took
53 s warm and 155 s cold, which is why it looked like nothing happened.

K/V is not the problem people expect: at `--max-context 262144` with
`--kv k8v4` the engine keeps 12,288 tokens on the card and maps 249,856 host
tokens into 3,050 MiB of RAM, about 12 KB per token, not the ~110 KB a fp16 K/V
would cost.

Through the server (`strata-inkling-2-mini-sq-10.json`, images on, 262,144
context): a 25-token prompt answered in 2.66 s; a 448×320 PNG with "HELLO 42" was
read correctly in 10.07 s by the pack's own encoder (no second vision process);
a `tool_choice: required` call returned `finish_reason=tool_calls` with
`{"a":2,"b":2}`. `GET /api/models` answers in 1.4 s with all ten models
available, and the harness reports the lane as `engineVersion=strata-inkling-0.1.67`.
The older run config that pointed `strata-inkling` at the IQ1_S GGUF is retired to
`configs-unused\`: the pack replaces it, and two Inkling native entries in one
picker is not a choice, it is a coin toss.

## Why the Inkling lane looked dead in AryaCode

With SQ-10 loaded and `/api/models` answering, an AryaCode session still never
reached the model, and the engine log showed the load with no prompt line after
it. The cause is in the harness, not here.

AryaCode's local-model plugin (`@aryacode/dsh-local-llm` 0.24.2, at
`C:\Users\kphung\.aryacode\profiles\desktop\node_modules\@aryacode\dsh-local-llm`)
decides whether an engine is running by scanning `tasklist` for image names in
its `ENGINE_IMAGES` set (`lib/index.js:2285`), which shipped as `strata.exe`,
`strata-poly.exe`, `aryainfer.exe` and `ninfer-engine.exe` — no
`strata-inkling.exe`. So the scan found nothing while the port answered,
`phaseOf()` (`lib/index.js:2678-2686`) fell through to `foreign` ("A process is
serving this port that this Host did not start"), and `ensure()`
(`lib/index.js:11643-11684`) waited for a `running` phase that could never
arrive: it polls `/api/aryastrata/status` for 120 s and then throws "The
selected Strata model is still loading" without sending the request. The same
path is why every other model worked — those image names are in the set.

Measured on this host: `tasklist` carries
`"strata-inkling.exe","22224","Console","1","13,475,256 K"`; the shipped set
matched no process, and `local-data\check-engine-images.mjs` — the same scan and
the same phase decision, run against the live server — reports
`found=true loaded=true -> running` once the name is in the set.

Fixed here by adding `"strata-inkling.exe"` to that set (backup
`lib\index.js.bak-2026-11-25`); it takes effect on the next AryaCode start.
Two things this host did not change and did not test: the plugin still reads an
Inkling run config as engine kind `other` (`lib/index.js:337-343`), so the
tuning panel offers only the flags already in the file; and the name belongs in
the upstream package, since a plugin update overwrites this edit.

## What was not measured here

- The Strata-native engine beyond `--version`: with the Coder removed there is no
  Strata-native pack on this machine, so 0.1.63's and 0.1.66's decode, their own
  prompt kernels and their image path are unmeasured here. The image path itself was
  measured on the poly engine on 2026-11-20 and works.
- `strata-poly` on any other family. It was verified on the one GGUF that is on
  this machine: Qwen3.6-35B-A3B-UD-Q4_K_M loaded in 10.7 s, put 2,064 of 10,496
  routed experts in 3.7 GiB of VRAM, and generated 64 tokens at 23.35 tok/s with
  69.8% of the experts served from VRAM and 58.9 ms per token of CPU expert work.
- Anything about 0.1.59.1 on the hardware in `docs/ARYAINFER.md`, where the
  inherited numbers were measured.

## Bench records this host keeps in the repo

Five folders under `bench/results/` carry this machine's measurements, each with its
raw rows and its harness so the run can be repeated:

| Folder | What it holds |
| --- | --- |
| `2026-11-13-community-rtx-pro-2000-blackwell-generat-qwen3-6-35b-a3b-ud-q4-k-m` | the `tools/strata_bench.py` suite on engine 0.1.45: 63.6 tok/s short chat, 575.6 tok/s prefill at 4K, 1,295.7 at 16K, 16.9 tok/s decode on agent follow-ups with a 68.8% cache hit, at 204,800 context |
| `2026-11-13-community-rtx-pro-2000-blackwell-generat-qwen3-8-flash-next-coder-iq1-m-cache-reserve` | the Coder tuning arms (0.1.45 against 0.1.59.1, reserve and `--mtp-q4` variants) with the engine's own VRAM-free and cache-hit lines, plus `tune_kv_ab.jsonl`, the 30 rows that record the bigger-window arms exiting rather than slowing |
| `2026-11-20-community-rtx-pro-2000-blackwell-generat-qwen3-6-35b-a3b-ud-q4-k-m-poly-engine` | the two `strata-poly` builds, warm and after 120 s idle, with every arm's engine log: no decode difference, 1,788 experts resident against 1,684 |
| `2026-11-25-community-rtx-pro-2000-blackwell-generat-qwen3-8-flash-next-coder-iq1-m` and `-2` | the same-day Coder comparison of `strata.exe` 0.1.63 against 0.1.67 |
| `2026-11-25-community-rtx-pro-2000-blackwell-generat-inkling-2-mini-sq-10` | the native Inkling lane: prefill and decode at 2,048 / 8,192 / 32,768 with drafting on and off, the load telemetry, and the chat, picture and tool-call checks |

The harnesses are inside those folders as `harness.py`. `tune_kv_ab.jsonl` and the
2026-11-20 logs came from `C:\Users\kphung\AryaCode\KonnectSuite\tune_ab2.py`,
`tune_kv_ab.py` and `ab_poly_2026_11_20.py` (modes `serve`, `ab` and `cool`, the last
one resting the card 120 s before each arm).

Rows from 2026-11-13 that no longer have a script that names them — `rr_power.jsonl`,
`rr_spec.jsonl`, `rr_threads.jsonl`, `sustain_a.jsonl`, `sustain_smoke.jsonl`,
`ab_poly_batch1.jsonl` — are deliberately not in the repo: their arms cannot be
described honestly without the harness that produced them.

