# Handoff: public documentation refresh

Date: 2026-11-08. Owner of this handoff: the next documentation agent.

This is a docs-only job. No engine, server or web-app behaviour needs to change.
The goal the user set: "go through all of the public docs and update it... how
we serve strata engine, poly engine, aryaengine, and ninfer engine all in one
inference space. AryaInfer. credit everyone please. update all the benchmarks."

The engine/credit/benchmark core of that pass is done and pushed. The remaining
work is per-family pages, translations, encoding cleanup and a final consistency
audit.

## Where things stand

- Repo: `C:\Users\KNPhu\AryaCode\KonnectSuite\AryaInfer`, branch `main`,
  HEAD `dadb269e`, pushed to `origin` (KonnectSuite/AryaInfer).
- Recent commits:
  - `dadb269e` docs: mark translations as describing the 0.1.45 two-engine world
  - `634b1354` docs: name the installed profiles that carry no speed row
  - `4975f7ee` docs: refresh per-family pages against the current roster
  - `733cde36` docs: record the showcase pass in the handoff
  - `44f02a28` docs: repair double-encoded text in benchmark and family pages
- **The remaining-work list below is done** (2026-11-08): per-family pages
  refreshed (Q8 banner, QWEN38-27B current summary, PLC_SAMPLING NInfer
  thinking row + Qwen3.5-4B row, MODELS.md installed-ten table); ENGINES.md
  names the four installed profiles with no speed row; translations carry a
  staleness banner pointing at the English README; link/claim audit clean
  (all root+docs links resolve, ENGINES anchors live, counts consistent);
  `aryainfer_names.py --check` exits 0.
- Progress on the remaining-work list below (2026-11-08, this session):
  - **Headline showcase added**: `README.md` now leads with the Gojo Voxel
    comparison (local Swift 1.5 IQ3_XXS vs the DeepSeek v4 Flash API, same
    prompt hash, same harness) with side-by-side renders, in-browser
    recordings (`.webp`), and a UI-screenshots section. Full write-up:
    `docs/BENCHMARK_GOJO_SWIFT_VS_DEEPSEEK.md`, artifacts under
    `docs/benchmarks/gojo-voxel/`.
  - **PolyStrata links**: the canonical org is now
    `https://github.com/simplexai-labs/PolyStrata` (VecSzn's account was
    flagged and the repo transferred; VecSzn remains the author). Applied
    repo-wide.
  - **Decode speeds corrected**: harness `usage.outputTokens` counts visible
    output only; reasoning streams on top. The Gojo numbers are ~99 tok/s
    (local) and ~233 tok/s (API) all-streamed, not the 49.3/116.5 visible-only
    rates.
  - **Section 3 (encoding damage) is done**: targeted cp1252 round-trip
    repairs across 11 files; remaining `Â`/`â€`/`U+FFFD` hits are only the
    intentional scan-pattern literals in this file (lines 97 and 101).
- Working tree: `models.json` is modified and `docs/QWEN35-4B.md` is untracked.
  Both are the user's files. Leave them alone; do not commit them.
- Installed engines:
  - Strata `0.1.58` at `C:\AI\Strata-data\engines\strata-0.1.58`
    (build commit `8a42a9457db6`, v0.2.12 release).
  - PolyStrata `0.1.45` at `engine-poly\strata-poly.exe`
    (`BUILD.json`: src `7bc1d82fc296b2ed`).
  - `aryainfer` at `C:\AI\Strata-data\engines\arya-infer\aryainfer.exe`
    (repo build `build-poly\aryainfer.exe`, 2026-11-03).
  - NInfer at `engine-ninfer\ninfer-engine.exe` (roofkid/ninfer-4080,
    `rtx4080-port` commit `2469b5752672ad597055af61fe28e8e7ced20056`, plus shim).
- The ten `strata-*.json` run configs at the repo root are the installed roster.
  Do not edit their engine paths without being asked.

## What was already changed

- **New `docs/ENGINES.md`** - the authoritative page: the four backends, their
  binaries, what each runs, context sizes, the shared line protocol
  (`READY`/`INFO`/`GEN`/`GENI`/`T`/`PP`/`RESUME`/`DONE`), which model uses which
  engine, measured tables, the full credit list, and how to add a backend.
- `CREDITS.md` - engine versions updated; roofkid/NInfer (Apache-2.0, pinned),
  Neroued's ninfer, ISTA-DASLab GSQ, Unsloth, Qwen, NVTX, llama.cpp/ggml,
  Splash/HyperQwen, curl/FFmpeg, Simple Icons.
- `README.md` - nav link to Engines; "ten profiles / four backends"; a new
  0.1.58 measured section; the October 0.1.45 table kept as history; roster
  paragraph corrected.
- `docs/ARYAINFER.md` - "Four engines, one server" table and pointer.
- `docs/HOW_IT_WORKS.md` - "Four engines, one program" section; credits fixed.
- `docs/BACKENDS.md` - pointer at the top; `docs/NINFER.md` - status no longer
  says text-only; `docs/MODELS.md`, `docs/DETAILS.md`,
  `docs/COMMUNITY_BENCHMARKS.md` - dated-pointer notes above the inherited
  0.1.45 sections; `docs/MODEL_ROSTER_HOST_RESULTS.md` - roster-moved banner;
  `docs/PLC_SAMPLING.md` - NInfer row (separate from the eight-model totals).
- `AGENTS.md` - now names the third and fourth engine paths.

Commits: `35b9bd38` (the main pass) and `06540c89` (PolyStrata version fix).

## Remaining work, in priority order

### 1. Per-family benchmark pages still describe the old roster

The pages below are honest for their dates but read as current. Mark them
clearly as historical or refresh the stale claims. Do not invent numbers.

- `docs/QWEN36_HOST_RESULTS.md` - Q4/Q8 at 131K, engine 0.1.45. Confirm whether
  the Q8 profile is still installed (it was removed from the roster); if it is
  not, say so and keep the numbers as the record.
- `docs/Q8_HOST_RESULTS.md`, `docs/MODEL_ROSTER_HOST_RESULTS.md` - October
  batches; keep, but ensure the banner and `ENGINES.md` link are enough.
- `docs/QWEN38-27B.md` - long record with AQ3 numbers. Add a short "current
  summary" table at the top (AQ3 8K/32K/130.7K) and a link to `ENGINES.md`.
  Its engine labels `aryainfer-0.1.45` vs `0.1.45` must stay distinguishable.
- `docs/NINFER.md` - check that the vision section and the `--host-kv-mib`
  245,760 note are still accurate; link to `ENGINES.md` already present.
- `docs/PLC_SAMPLING.md` - the thinking-mode table and the "what each entry
  ships with" table do not cover NInfer, Swift 1.5 or Qwen3.5-4B. Add rows only
  where measured; otherwise say "not measured".
- `docs/MODELS.md` - its model-size advice still targets the old roster; check
  the installed ten and update the recommendation section.

### 2. Missing benchmark rows

`docs/ENGINES.md` has Strata 0.1.58, AQ3, NInfer and 35B Q4/Q8. Missing:

- Qwen3.8-27B **Turbo IQ3_XXS** (AryaInfer): no table in the current docs.
  Either measure it again on this host (short + 32K prompt) and add a row, or
  cite the record in `docs/QWEN38-27B.md` if one exists there.
- **Qwen3.5-4B** (AryaInfer): no speed table.
- **Swift 1.5 / Swift 1.5 abliterated on 0.1.58**: configs point at the new
  engine, but they were not re-measured. Say so explicitly in both config docs.

### 3. Encoding damage

Several inherited files contain mojibake, for example `README.md` line 5
(`·`), line 9-16 (`â€™`), and the `MODEL_ROSTER_HOST_RESULTS.md` title
(`—`). `docs/DETAILS.md`, `docs/MODELS.md` and
`docs/COMMUNITY_BENCHMARKS.md` have the same banner. Fix only when you can do it
without changing meaning: read UTF-8, write UTF-8 without BOM, then grep for
`U+FFFD` (`\uFFFD`) and for the literal `Â`/`â€` sequences.

### 4. Translations

`README.de.md`, `README.es.md`, `README.fr.md`, `README.ja.md`,
`README.pt-BR.md`, `README.zh-CN.md`, and
`docs/HOW_IT_WORKS_MODELS.{de,es,fr,ja,pt-BR,zh-CN}.md` still describe the
two-engine, 0.1.45 world. Either translate the new four-engine section or keep
them and make the English page authoritative (the README already says
translations retain inherited guidance; make that sentence clearer if needed).

### 5. Link and claim audit

- Walk every link in `README.md`, `docs/ENGINES.md`, `docs/ARYAINFER.md`,
  `docs/HOW_IT_WORKS.md`, `docs/BACKENDS.md`, `docs/NINFER.md`; fix anchors such
  as `docs/ENGINES.md#choosing-a-model-not-an-engine` and `#credits`.
- Verify the counts: ten installed profiles, four backends, Strata 0.1.58,
  PolyStrata 0.1.45 (`src 7bc1d82f`), NInfer `2469b57`, 131,072 for NInfer.
- Check that the README's "Supported models" table and the new Engines roster
  do not contradict each other (the README table is the inherited support
  matrix; the Engines table is what is installed here).

## Rules for this repo

- `AGENTS.md`: one change per commit; keep upstream attribution; a measured
  number must say what it was measured on; no claim without a measurement.
- Docs-only changes do not need engine builds or the web tests. Run
  `.\.venv\Scripts\python.exe tools\aryainfer_names.py --check` after edits
  (exit 0) and `tools/polystrata_names.py` only if you touch code files.
- Commit style: `docs: lowercase sentence`. Push with
  `$env:GIT_TERMINAL_PROMPT="0"; git -c credential.interactive=false push origin main`.
- Do not touch `C:\AryaStrata` (the user's installed clone), the user's
  `models.json`, or `docs/QWEN35-4B.md`.
- The 8080 server is the user's, started through the DSH host. Do not stop or
  restart it for docs work. Never kill `tailscaled`.
- PowerShell notes: `.NET` file APIs resolve relative paths against the process
  directory, so use absolute paths; read files with the editor/read tool before
  editing; write UTF-8 without BOM.

## Numbers to reuse (measured here)

Strata 0.1.58, Flash-Next IQ3_XXS, 262,144 ctx, DFlash2, temp 0.3, vision on
(one run per row):

| prompt | prefill | decode |
| ---: | ---: | ---: |
| 19 | 52.6 | 86.4 |
| 4,621 | 1,886.0 | 78.4 |
| 16,121 | 1,336.9 | 74.4 |

0.1.56 comparison: 52.8 tok/s decode around 15K (Monitor), prompt reads
491-523 tok/s in the engine log.

AQ3 (q4_0, `STRATA_GDN_MMA=1`): 1,229.3 prefill / 85.1 decode at 8K batch 2048;
1,062.5 / 80.5 at 32K; 582.6 / 68.4 at 130,672 tokens batch 1024.

NInfer (rk4v4-e8, MTP draft 3, repeated-id corpus at 96-100% acceptance):
2,039 / 1,855 / 1,672 / 1,535 / 1,358 prefill and 115.3 / 109.8 / 103.3 /
100.2 / 89.0 decode at 8K / 32K / 64K / 98K / 130.8K. Real prose: 74.7 tok/s.
Prefix reuse: 1,220-token turn 1,845 ms -> 33 ms; 57,018-token turn 30.1 s ->
41 ms with `--host-kv-mib 245760`.

Qwen3.6-35B-A3B: Q4 151.2 short decode, 1,404.3 prefill / 73.8 decode at
131,031 tokens; Q8 97.2, 1,404.5 / 52.2.

NInfer PLC probe, 8 fixtures, thinking off: coding 5, coding-0.5 5, precise 5;
same three failures as the other Qwen entries (`ld_rung`, `hmi_vis`,
`hmi_alarm`). Thinking probe: off 0, low 1,384, medium 1,483, high 1,651
reasoning characters.

## Definition of done

- Every public page that mentions engines names the four backends consistently
  and links `docs/ENGINES.md`.
- Every benchmark table carries a date, engine build, model file and workload,
  or is explicitly marked historical.
- No new mojibake or `U+FFFD` in touched files; `aryainfer_names.py --check`
  exits 0; the links you touched resolve.
- A short "docs: ..." commit (or a few, one per topic), pushed to `origin/main`.
