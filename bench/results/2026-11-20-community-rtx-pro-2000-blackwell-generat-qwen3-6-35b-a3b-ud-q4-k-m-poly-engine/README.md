# Community benchmark on NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU

Measured on 2026-11-20 comparing two `strata-poly` builds on the same model and the
same run configuration. Speed only: no correctness check beyond one image request.

## Hardware and software

- GPU and VRAM: NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU, 8 GiB VRAM
- CPU: Intel(R) Core(TM) Ultra 7 265H (16 cores, 16 threads); installed RAM: 63.4 GiB
- OS: Windows 11 (10.0.26300); GPU driver: 597.01; CUDA: 13.5
- AryaInfer: fork of PolyStrata, branch `main`
- Build under test: `engine-poly\strata-poly.exe`, 84,397,056 B, the build this host
  installed on 2026-11-20
- Build it replaced: `engine-backup-0.1.59.1\poly\strata-poly.exe`, 84,346,368 B,
  built on this host on 2026-11-13 from PolyStrata `main` at `67dde645d`
  (tag `v0.1.45-poly.9 plus the 149 commits after it`)
- `strata-poly` prints no version (`strata-poly: unknown option --version`), so the
  two arms are identified by file, byte size and `BUILD.json`, not by a version line
- Background workloads and power limits: not recorded

## Model and configuration

- Model and quantization: Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
- Context: 204800 tokens; parallel slots: 1
- Settings: the install's own configuration `strata-qwen36-200k.json`, unchanged
  between the two arms; the only difference between arms is the binary

```text
strata-poly.exe --serve --model Qwen3.6-35B-A3B-UD-Q4_K_M.gguf --max-context 204800 --expert-profile expert-profile.txt --conversation-cache-mib auto --tail-skip 0 --threads 10 --kv q8_0 --prompt-batch 2048 --vram-reserve-mib 512
```

The four configs the arms ran are in `configs\`, one per arm name.

## Method

`harness.py` (kept here; it started a server per arm on its own port, waited for
`/health`, then sent two prompt sizes with 64 new tokens each and read the engine's
own timings back from the log).

- `short`: an 83-token prompt, 64 new tokens
- `mid`: a 394-token prompt, 64 new tokens
- `serve-8080`: the arm that was already running when the run started, measured once
- `new-*` / `old-*`: alternating arms, one server each
- `*-cool-*`: the same two arms after the card had been idle for 120 s, so a warm
  card does not decide the comparison

Per-request rows: `rows.jsonl`. The first lines of one warm arm of each build are in
`engine-log-excerpt.txt`; the full per-arm logs (nine engine logs and nine server
logs) stayed beside the checkout in `poly-update-2026-11-20\`, since `*.log` is
gitignored here.

## Results

| Arm | Case | Prompt tokens | Prompt tok/s | Decode tok/s |
| --- | --- | ---: | ---: | ---: |
| serve-8080 (new build, already running) | short | 83 | 163.1 | 77.8 |
| serve-8080 | mid | 394 | 470.3 | 95.9 |
| new build, warm | short | 83 | 114.2 / 100.2 | 82.0 / 39.05 |
| new build, warm | mid | 394 | 505.3 / 315.5 | 97.9 / 18.5 |
| 2026-11-13 build, warm | short | 83 | 158.0 / 111.3 | 79.25 / 65.45 |
| 2026-11-13 build, warm | mid | 394 | 430.7 / 428.2 | 82.8 / 70.95 |
| new build, rested 120 s | short | 83 | 122.0 / 126.1 | 78.5 / 74.45 |
| new build, rested 120 s | mid | 394 | 492.7 / 493.0 | 88.4 / 95.2 |
| 2026-11-13 build, rested 120 s | short | 83 | 116.8 / 129.3 | 80.8 / 78.55 |
| 2026-11-13 build, rested 120 s | mid | 394 | 512.7 / 483.9 | 97.85 / 86.5 |

Rested arms are the ones to read: the spread inside one build (74.45 to 78.5 on the
short case, 88.4 to 95.2 on the mid case) is as large as the gap between the builds,
so this host measured no decode difference between them.

The one difference that did show up is resident experts. The new build kept 1,788 of
10,496 routed experts in 3.2 GiB of VRAM; the 2026-11-13 build kept 1,684 in 3.0 GiB.
Both lines are in `engine-log-excerpt.txt`.

The image path was checked on the new build: a red 96x96 PNG through
`engine-poly\strata-vision.exe` answered "Red" in 0.52 s, 32 prompt tokens.

## Correctness and limitations

Speed only; the two short warm runs of each build differ by more than the builds do,
which is why the rested runs carry the conclusion. One run of the new build produced
39.05 tok/s decode on the short case with the same config, which is a card-state
outlier, not a build difference: the rested runs of the same binary returned 78.5 and
74.45. Context length was not varied, thinking was off, and the model's output was not
checked for quality. What this host did not test: the Strata-native path (no Strata
pack installed here) and any other model on these two builds.
