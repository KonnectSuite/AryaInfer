# Community tuning record on NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU

Measured on 2026-11-13 on the Coder model, looking for a configuration that decodes
well on 8 GiB of VRAM. Speed only.

## Hardware and software

- GPU and VRAM: NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU, 8 GiB VRAM
- CPU: Intel(R) Core(TM) Ultra 7 265H (16 cores, 16 threads); installed RAM: 63.4 GiB
- OS: Windows 11 (10.0.26300); GPU driver: 597.01; CUDA: 13.2
- Engines compared: the fork's `engine\strata.exe` 0.1.45 and Strata 0.1.59.1 kept in
  `engine-backup-0.1.59.1\strata.exe`
- Background workloads and power limits: not recorded

## Model and configuration

- Model and quantization: Qwen3.8-Flash-Next GSQ-RCO Coder (IQ1_M)
- Base configuration: the install's `strata-coder-iq1_m.json`; each arm adds the flags
  listed under its own name, on port 8123
- Two prompt sizes: `2k` and `24k`, one request each per pass; prompt token counts are
  not identical between arms (1,660 / 1,784 / 1,908 at `2k`, 26,171 / 26,422 at `24k`)
  because the harness regenerated them, so read the medians as a shape, not as a
  controlled A/B at fixed length

## Method

`harness.py` (kept here) started one server per arm, waited for it to be ready, sent
the two prompt sizes, and read the engine's own timings and its cache-hit line back
from the engine log. GPU telemetry (SM clock, wait time, VRAM) came from `nvidia-smi`
sampled during each request; it is in the rows.

## Results

| Arm | Engine | Extra flags | Slots / VRAM free per the engine's own line | `2k` prefill tok/s | `2k` decode tok/s | `24k` prefill tok/s | `24k` decode tok/s | Cache hit |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `base` | 0.1.45 | none | 528 slots, 1.01 GiB / 0 MiB free | 352.7 | 26.6 | 340.3 | 5.3 | 25.6% |
| `res812` | 0.1.45 | reserve 812 as the engine suggested | 528 slots, 1.01 GiB / 0 MiB free | 324.4 | 33.7 | 318.7 | 4.5 | 21.5% |
| `mtpq4` | 0.1.45 | `--mtp-q4 all` | 480 slots, 0.91 GiB / 13 MiB free | 228.1 | 7.1 | 255.1 | 5.8 | 13.4% |
| `upstream` | 0.1.59.1 | none | 816 slots, 1.56 GiB / 233 MiB free | 621.9 (567.5-698.0, n=4) | 22.7 (15.4-32.9, n=4) | 501.1 (404.2-597.3, n=6) | 6.8 (5.2-27.3, n=6) | 44.0% (35.1-69.4) |
| `up_spec2` | 0.1.59.1 | two-token draft | 816 slots / 233 MiB free | - | - | 403.1 | 5.0 | 59.0% |
| `up_pcores` | 0.1.59.1 | `--pool-affinity p-cores` | 816 slots / 233 MiB free | 460.8 | 8.0 | 559.6 | 9.8 | 53.7% |
| `up_mtpq4` | 0.1.59.1 | `--mtp-q4 all` | 816 slots / 233 MiB free | 405.0 | 10.6 | 582.5 (509.1-618.8, n=3) | 10.7 (10.4-11.3, n=3) | 57.6% (54.2-64.2) |

What these rows support:

- Prefill is where the newer engine is clearly better: 567.5-698.0 tok/s against
  324-353 tok/s for the same model on 0.1.45.
- Decode at 24K is bad in every arm (4.5-11.3 tok/s). The engine says why in its own
  line: `WARNING: only 0 MiB of VRAM free at the start of this request (below 1024
  MiB): when the card is this full the driver can page GPU memory to system RAM,
  decode falls to a few tok/s and a window may never finish (#2065)`.
- The `res812` arm decoded faster at 2K (33.7 against 26.6) but its own log still
  reports 0 MiB free and 528 slots, so the reserve cannot be credited from these
  rows; it is one run, and the difference is within the spread the `upstream` arm
  shows across four runs.
- `--mtp-q4 all` did not help on this card in either engine: hit rate fell to 13.4%
  on 0.1.45 and decode at 2K fell to 7.1 tok/s.

## The crash this run was chasing

`tune_kv_ab.jsonl` is not a speed record. Its 30 rows are all failures — 8
`"error": "engine exited 2"`, 1 `"server exited 1"`, and 21 rows that recorded a
process id and no timings — from the arms that grew the KV window (`A_base`,
`B_kv20480`, `C_kvgrow`, `D_kv20480_r812`, `E_kv20480_pf2048`, `F_mtpq4`,
`G_headalias`, `H_reserve812`, `I_ple`, `J_spec6`, `K_pcache`, `L_k8v4`, `M_adapt`,
`N_pcie`, `O_pool`). It is kept because it is the evidence behind the paging warning
above: on this card, a bigger window on the 0.1.59.1 engine did not slow down, it
exited.

## Correctness and limitations

One pass per arm for most arms, so single-run numbers carry the card's state; the
`upstream`, `up_mtpq4` arms have 3-6 passes and show how wide that state is. Prompt
lengths differ slightly between arms. No correctness or quality check was run. Not
tested here: thinking enabled, parallel slots above 1, and any model other than the
Coder.
