# Handoff — Qwen3.8 27B performance (goal rounds 1-8, 2026-11-03)

Status line: the user's original complaint is fixed (the long-context spill), the tuned path reads a
61,787-token prompt at **911.9 tok/s** and writes at **59-66 tok/s** on this host, and the remaining decode
headroom is a **draft-window policy** question, not a kernel one first. Server is currently stopped; the GPU is
free (852 MiB used).

## The problem, as it stood

`HANDOFF-2026-11-03-arya-local-and-qwen38.md`, part B: 56K/65K prompts read at 330/325 tok/s and wrote at 19.7/16.4,
then even a 14-token prompt decoded at 0.2 tok/s until the server was restarted. The cause was VRAM pressure
(WDDM spill), not the engine's arithmetic.

## What was measured, in order

All on this host (i9-14900KF, RTX 4070 Ti SUPER 16 GB, 96 GB RAM, Windows 11), q4_0 KV, `strata-poly`/
`aryainfer` 0.1.45, the ISTA-DASLab `Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf`. One engine at a time, `nvidia-smi`
checked empty before each arm.

1. **The spill is the prompt batch's scratch.** At 131K context with `--prompt-batch 2048` the batch scratch
   (2.9 GB) + KV (2.4 GB) + weights (9.7 GB) + vision (0.87-1.2 GB) is ~16.6 GB on a 16.4 GB card.
   Batch 512: decode at 64K went **32.0 -> 70.3 tok/s** with 14.9 GB used. This is the fix for the complaint.
2. **128K vs 64K context, q4_0 vs q8_0, at a 62K prompt: within noise** (912.6 / 903.8 / 905.4 tok/s). No smaller
   context twin is needed; the 128K/q4_0 entry stays.
3. **Vision on the CPU** (config `vision.gpu: false`) frees ~1.2 GB; the dense engine sizes its arena to free
   VRAM and reading went 722.2 -> 826.0 at 62K (+14%), decode unchanged. An image turn still works on CPU (9.9 s
   end to end for a 768px PNG, 1,024 image tokens). `"gpu": true` trades that back for faster image encoding.
4. **The chunked GDN MMA kernel** (`STRATA_GDN_MMA=1`, compiled into this repo's build, absent from the installed
   0.1.45): reading **+8.2% at 8K, +9.1% at 32K, +7.4% at 62K** (1,190.0 -> 1,287.8, 1,021.4 -> 1,114.5,
   854.9 -> 917.8). The engine says "decode and snapshots unchanged"; upstream notes some long-response runs
   regressed, so it is a per-model `env` entry, not a binary default.
5. **End to end**, server, arya model (128K, q4_0, batch 512, CPU vision, GDN MMA): 61,787 tokens read at
   **911.9 tok/s**, 33 written at 58.8, follow-up at 65.9, 14,655 MiB, 68.8 s for the prompt.
6. **Decode pass structure** (8K, `--report-drafts`): one-token pass 22.7 ms (44.1 tok/s, 427 GB/s = 64% of peak);
   extra verify rows cost **3.4-5.6 ms**, not 13; so seven rows would be ~47 ms, ~150 tok/s at perfect acceptance,
   ~90 at 0.8 a position. The policy offers only **2.6-3.3 guesses a round**, which is what caps decode at ~75.
7. **What did not work**: `--prefill-f16` (704.7 vs 1,190 tok/s, dequant-dominated), `--lookup-chain 4` on filler
   text (+6.6% at 8K, nothing at 32K), `--tree 2,2` (23.5 tok/s at 8K, 78/300 accepted), `--tree 2,1` (28.3),
   `--draft-window 2048/4096` (noise), a four-row MMQ gate (70.2/74.3), `STRATA_BF16_TC` / `STRATA_XN_F16` /
   `STRATA_PA_V2T` / `STRATA_SELECT_SIMT` (all within noise), capy-flash's NVFP4 artifacts (sm_120 only).

## What exists in the tree now

- `CMakeLists.txt`: an **`aryainfer`** target built from `src/poly` sources with `-DARYAINFER_ENGINE=1` (and
  `STRATA_PREFILL_F16=1`); `strata-poly` itself is untouched so an upstream PolyStrata engine can still be
  dropped in. Built binary installed at `C:\AI\Strata-data\engines\arya-infer\aryainfer.exe` (69 MB);
  `build-poly/aryainfer.exe` is the build output.
- `src/poly/main.cpp`: under `ARYAINFER_ENGINE` the READY line's `engine=` reads `aryainfer-0.1.45` (otherwise
  `0.1.45`).
- `serve/server.py`: `poly_engine()` also recognises `aryainfer`, so the server sends it `.sve` pictures and does
  not append the native `--vision` flag (it refused that with "unknown option --vision" before).
- `serve/test_server.py`: the engine-args test covers `aryainfer.exe`. `serve.test_server` 367 tests OK; page and
  image suites 171 OK; `tools/aryainfer_names.py --check` clean.
- Model configs: `strata-qwen3.8-27b-arya.json` (root, mirrors the user's runtime folder) with
  `env: {"STRATA_GDN_MMA": "1"}`, `--max-context 131072 --kv q4_0 --prompt-batch 512`, vision on the CPU; the
  tracked copy `docs/host-tuning/strata-qwen3.8-27b-arya.json`; `models.json` entries for
  `qwen3.8-27b-arya` (arya engine) and the existing `qwen3.8-27b-iq3_xxs` (upstream engine, now batch 512 +
  CPU vision) with notes carrying these numbers.
- `tools/qwen38_spec_bench.py`: `--report-drafts` is opt-in (`--drafts-by-pos`) because the installed engine
  build does not know the flag.
- `docs/QWEN38-27B.md`: the living record — every table above, with sources and caveats, including a correction
  of an earlier mispriced row cost. Read this first for detail.

Commits (AryaInfer, `main`): `f5431b5b` (the spill/batch fix and host-RAM analysis), `3ca359ac` (arm table and
the other engines), `8d25614a` (repository build; prefill-f16 and lookup-chain measured), `c09c4fa1` (`aryainfer`
target, server recognition, tests, configs), `7532a922` (capy-flash catalogue), `b654dd6c` (draft flags, batch,
CPU vision), `a3f3cb7c` (pass-cost table; the row figure it prints was corrected later), `a6619655` (negative
results: four-row MMQ, env switches), `92c958b6` (GDN MMA win and the arya env), `7afd5397` (128K vs 64K vs q8_0,
end-to-end 911.9), and the correction commit for the row cost.

## Running it

Server (the same way the controller starts it):

    cd C:\Users\KNPhu\AryaCode\KonnectSuite\AryaInfer
    $env:PATH = "C:\AI\Strata-data\cuda\13.1.2\bin\x64;C:\AI\Strata-data\cuda\13.1.2\bin;C:\AI\Strata-data\engines\strata-0.1.54;" + $env:PATH
    $env:SSL_CERT_FILE = (.venv\Scripts\python.exe -c "import certifi;print(certifi.where())")
    .venv\Scripts\python.exe serve\server.py --engine strata --config strata-qwen36s-ud-q4_k_xl.json --port 8080

Then `POST /api/models/load {"model": "qwen3.8-27b-arya"}` (or pick it in the WebUI) to get the fork engine with
the GDN MMA; `qwen3.8-27b-iq3_xxs` runs the same file on upstream's installed `strata-poly`.

Build the fork engine (MSVC 14.44 + CUDA 13.1.2, sm_89):

    build-env\build-poly.cmd     # configures build-poly and builds strata-poly
    build-env\build-arya.cmd     # builds the aryainfer target

Copy `build-poly\aryainfer.exe` to `C:\AI\Strata-data\engines\arya-infer\aryainfer.exe` after a rebuild.

Benchmarking rule learned the hard way: **stop the server and every engine first**; the user caught two
`server.py` processes and a resident engine polluting arms. The raw harness used in rounds 4-7 lives at
`build-env/rawtree2.py` (starts one engine, feeds GEN, parses `strata serve: prompt`, kills it); it wants
`STRATA_*` env passed through `os.environ` and `--prompt-batch 512` on a free card.

## Next steps, in order

1. **Force a deeper draft window and measure acceptance at positions 4-7.** `--window N` only sets the ceiling;
   `Guesses::wants()`/`takes()` decide. Patch a fork-only env (e.g. `STRATA_FORCE_GUESSES=N` under
   `ARYAINFER_ENGINE` in `src/poly/main.cpp`/`guesses.hpp`) that makes `wants()` return true up to N, then measure
   decode and `--report-drafts` acceptance at 8K/32K. If positions 4-7 hold at >=60%, a depth-aware policy in
   aryainfer is the decode win (the arithmetic: ~90 tok/s at 0.8 a position vs 75 now). Keep the change in
   aryainfer, not strata-poly.
2. If acceptance collapses past position 4, the limit is the MTP block's quality (this file has
   `nextn_predict_layers = 1`); then the lever is a better draft (two heads are not in the weights) or accepting
   the ceiling.
3. Only after 1-2: the GDN per-row state kernel, if the rows themselves are still the cost.
4. Housekeeping: `git push` (the session's commits are local; origin was last at `ec3a111d`), and re-run the full
   `python -m unittest serve.test_webui serve.test_comfyui serve.test_images serve.test_search serve.test_server`
   if any server file changes again.

## Caveats

- The GDN MMA kernel is opt-in upstream for a reason (chunked arithmetic rounds differently; some long-response
  runs regressed in upstream measurements). It is an `env` entry on the arya model, easy to drop.
- Vision on the CPU costs image encoding time; text-only sessions get +14% reading for it.
- The installed `strata-poly-qwen38\strata-poly.exe` (0.1.45, 2026-11-02) lacks `--tree`, `--lookup-chain`,
  `--report-drafts` and the GDN MMA compile flag; the repository build has them. Do not confuse the two.
- `C:\AryaStrata` is the user's installed clone; this work is in `C:\Users\KNPhu\AryaCode\KonnectSuite\AryaInfer`.
