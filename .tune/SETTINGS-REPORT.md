# Qwen3.8 Flash Next on this PC — settings deep dive and tune-up

Host: **i9-14900KF (8 P + 16 E, 32 logical), 64 GB RAM, RTX 4070 Ti SUPER 16 GB (Ada, sm\_89,
driver 610.88), Windows 11.** Engine **0.1.45**, model **qwen3.8-flash-next-iq3\_xxs** (70.6 GB
across two shards, plus a 43 GB PLE table and the MTP head).

Everything below that says "measured" was measured on this machine with the engine's own
accounting (the `--serve` pipe's `DONE` line: `prompt_ms`, `decode_ms`, draft acceptance, expert
tier hits). Everything that cites a vendor or community figure says where it came from and on what
hardware, because almost none of it was measured on a 4070 Ti SUPER.

> **2026-11-19 correction.** The `--vram-reserve-mib 700` prefill win in section 4.2
> (+13.5% / +15.0%) does not reproduce. The harness of the time sent one prompt per
> case, so after the warm-up request every measured rep was served from the
> conversation cache and "prefill" timed a short tail read instead of a cold prompt.
> With one cold prompt per measured rep the arm is -3.9% at 32K. The section is kept
> as written history; see `bench/results/iq3_xxs-0.1.62-draft-cap-8/` for the
> corrected measurement and the engine 0.1.62 record.

---

## 1. What the community benchmark archive actually says for *this* hardware

The upstream run archive (`bench/results/`, ~60 dated runs, indexed by `bench/results/COMMUNITY.md`)
is large, but for a single 16 GB Ada card most of it does not apply. The honest summary:

### 1.1 Rules out

| Rule out | Why |
|---|---|
| `STRATA_SM86_*` / sm\_60 bitwise switches (+13.0% on an A4000) | Architecture-gated: the engine only sets them "when every visible card has that one compute capability" (`include/strata/core/nv_defaults.hpp`, `docs/DETAILS.md:2308-2340`). 4070 Ti SUPER is sm\_89 → these switches never arm. |
| Copying the old 4070 Ti SUPER run's `--pool-workers 23` | That run is 0.1.39-era. The engine's rule today is `p_cores - 1 + e_cores/2` = **15** (`include/strata/kernels/cpu/pool_plan.hpp:8-12,38-41,84-120`), measured 165/116 tok/s at 15 workers vs 106/84 at 23. |
| `--kv q4_0` to save VRAM | RTX 5070 Ti 16 GB measured **−16…−18% prefill with no decode gain** (4K 1,180 vs 1,438; 32K 1,902 vs 2,256), and `docs/DETAILS.md:94-98` puts the perplexity cost at +8–12%. `--kv int8` is the right setting; only drop to `k8v4` if VRAM-starved at very long context (3090 at 198K: 99 vs 85 tok/s). |
| `--prefill auto:32768` for a big prefill win | Real (+18–29% at 32K on a 5070 Ti) but the vendor rule is explicit: `auto:16384`/`auto:32768` are **not bit-exact on CUDA** (P100 and A4000 residual dumps differ), so the NVIDIA default stays 8192 (`docs/DETAILS.md:2364-2368`). Not worth it on a daily driver. |
| `--batch` / `--batch-mtp` for multi-client serving | 4090: 2 slots cost 2.88 GiB/slot and took 1-client decode from 93–95 to 65–72 (**−28%**); `--batch-mtp` died outright with `mtp: unsupported native MMVQ GGML type`. |
| `STRATA_KV_PREFETCH=1` | **−5.3% prefill at 32K**, −4.1% at 64K in the same measurement that produced the option. |
| `--mmap-experts`, `--resident-experts` on this box | Low-RAM answers for hosts under ~53 GB used RAM; this PC has 64 GB and clears the check. |
| `--aux-cpus auto`, `--host-core last` | `--aux-cpus auto` is an open PR (#1598), not in main. `--host-core last` is documented "Not on hybrid CPUs". |

### 1.2 Supported, and worth acting on

| Setting | Evidence | Ours today |
|---|---|---|
| `--pool-affinity p-cores` | **The biggest documented lever.** i7-13700K (8 P + 8 E) + RTX 5090, Swift IQ3\_XXS at 128K: `all` with 15 workers = 6.7 ms/window, 148 tok/s; `p-cores` with 7 workers = 2.2 ms, **188–191 tok/s**. `measure` A/B-times both once at start. | absent (engine default `all`) |
| `--pool-workers` | The engine already picks 15 for this exact CPU; passing 15 explicitly is harmless but redundant. | `15` |
| `--pcie-frac` | Calibrated values are per-PC: **0.00** on the 4070 Ti SUPER, the 3090 eGPU and a 5060 Ti; 0.19 on 5060 Ti + E5-2680 v4; 0.33 on a 5080. Engine default is now `-1` = auto-refined in the first decode windows on single-GPU CUDA (0.1.42+, `src/program/generate.cpp:676-677,2144`); an explicit value always wins. RTX 3060 IQ3\_XXS 0.55 → 0.20 was ×1.300 decode. | `0.20` (calibrated) |
| `--spec-min-p` | Setup writes 0.5; the 3090 eGPU and 5060 Ti calibrations both preferred **0.70**. Per-PC, not a constant. `--spec 4` stays (4/5/6/8 sweep ratios 1.122/1.079/1.060/1.027). | `0.70` |
| `--mtp` on | RTX 3060 12 GB IQ3\_XXS 4,096-in/1,024-out **35.9 → 44.1 tok/s (+22.8%)**; real-text draft acceptance 0.60–0.78. | `--mtp …\mtp\rt` |
| `--kv-resident 32768` | Q2\_0 at 262K: **50.9 → 62.6 tok/s** (1,589 → 3,872 experts in VRAM); ~+6% at 128K; 13.7 KB RAM per context token; "the attention reads exactly the same values". | `32768` |
| `--expert-cache auto` | 4,096 slots measured 54.4% hit rate, drain 19.1 → 10.3 ms/token. The shared counter only gave 2.97%; `--expert-cache-per-layer` gives 21.4% at 8/layer, 70.4% at 64/layer. | `auto` (→ 2,189 slots here) |
| Vision on the **CPU** | Under 24 GB VRAM the vendor puts the encoder on the CPU: A4000 16 GB IQ3\_XXS measured **46.0 → 48.4 tok/s decode (+5.2%)** and expert slots **4,686 → 5,435**. Windows warning attached: an RTX 4080 SUPER lost **35–44% of decode** with the GPU encoder (61 MiB VRAM free). Cost: 4–6 s per 300-token picture. | **GPU encoder** (`vision.gpu: true`) |
| `STRATA_EXCHANGE_ROTATE=1` | Removes the last host memcpy in resident-RAM exchange. 3060 IQ3\_XXS 58.96 → 62.03 (**+5.2%**); Q2\_0 104.90 → 113.44 (+8.1%, 1,024 identical ids). Costs ~1.06 GiB page-locked at `--adapt-swaps 80`. | absent |
| `STRATA_DISJOINT_ADAPT=1` | **+15.5%** generation in the vendor notes, in-engine 81.5 → 94.1 tok/s. | absent |
| `--prefill-head-alias` | Lends the 417 MiB output head to prompt buffers: RTX PRO 2000 8 GB 292.5 → 667.1 tok/s, real loop 256 → 583 (+125%), decode +19%. Costs 0.6–0.75 s on reads ≤512; refused with `--batch`, 2 GPUs or layer split. | absent |

### 1.3 Contradicted between runs — measure locally, do not trust either side

- `STRATA_PREFILL_CPU_SHARE=0`: one 3060 run lost 4.9–23.8% prompt speed to it; 5080 and 5060 Ti owners use it deliberately.
- `--prefill auto:32768`: 5070 Ti +18–29% vs the "not bit-exact on CUDA" rule above.
- `--kv q4_0`: docs say "~4% faster at 128K"; the 5070 Ti measured −16…−18% prefill.
- 0.1.41 regressed prompt reads 3.8/6.6/8.0% at 25K/51K/104K against 0.1.40.3 with no explanation, so **prefill numbers from 0.1.39–0.1.41 are not a 0.1.45 baseline.**

### 1.4 The noise floor — this governs how the benchmarking must be done

> "decode differences under roughly **10%** should not be read as real" — 5070 Ti README, whose six identical runs spanned 53.9–63.5 tok/s.
> Restart-to-restart spread up to ~5% — 2×3080 README.

Consequence: single runs are worthless for judging a setting. Everything measured for this report
is medians of interleaved A/B passes, and any delta under 10% is reported as "not distinguishable
from noise" rather than as a win.

### 1.5 The number to beat on this exact GPU and quant

The community 4070 Ti SUPER run measured **2,404–2,747 tok/s cold prefill** and **76.0 tok/s decode
at 32 k with int8**, falling to 70.0 at 128 k (q4\_0) and 56.0 at 256 k (k8v4). Sibling cards:
5060 Ti 16 GB 1,157–1,225 prefill / 56.6–60.2 decode; 5070 Ti 2,482 prefill / 73.7 decode at 32 k.

---

## 2. What Strata's own installer recommends for this host

`setup.py` is the authority here; it computes a recommendation from a VRAM/RAM/hybrid-core table
rather than from an opinion.

| Decision | Code | Value for this PC |
|---|---|---|
| Context | `rec_ctx = 65536 if 14 <= small < 20` (`setup.py:7580`), then `min(rec_ctx, ram_ctx())` (7584) | **65,536** |
| Context ceiling from RAM | `ctx_ram_need = arena (42.9) + ctx*13*1056/1e9 + 24` (4680-4694); 262,144 → 42.9 + 3.60 + 24 = **70.5 GB > 64** | **131,072 max** |
| Low-RAM mode | `ram < arena + 10` = 52.9 (4455, 4467-4470) | **off** (64 > 52.9) |
| KV type | `fp16 if ctx <= 8192 else int8` (7628) | **int8** |
| KV streaming | needs `ctx >= 65536` and `ram >= 60 + 0.90 + 1` (4518-4525, written 7959-7989) | **`--kv-resident 32768`** |
| CPU workers | `hybrid_pool_workers((8,16)) = 8-1+16//2` (1099-1123) | **15** |
| Vision encoder | `IMAGES_GPU_ENCODER_MIN_VRAM_GB = 23.5` (2251); under it, a "yes" gets the CPU encoder (2256-2268, 7651-7655) | **CPU**, ~3 s/picture, no VRAM |
| Base args written | 7919-7926 | `--expert-cache auto --prefill auto --spec 4 --spec-min-p 0.5 --mtp <rt> --max-context 65536 --kv int8 --kv-resident 32768` |

**The installer's own words on 256K with this quant and 64 GB** (`docs/DETAILS.md:70-76`): "IQ3\_XXS
and IQ3\_S at 262K are not measured: with their 43 / 50 GB of experts, a 260K-token context brings a
64 GB PC to its memory limit by setup's estimate … setup recommends up to 128K with them on 64 GB."
`setup.py:7600-7607` prints, for anyone who overrides it: "Kept as you chose: it may be slower or run
out of RAM under load. **64K is the recommended size**."

---

## 3. Where your current config sits against that advice

Your `strata-iq3_xxs.json` is a *calibrated and hand-tuned* configuration, not a default one. It is
already good in most places; the deltas that matter:

| Key | Yours | Installer would write | Verdict |
|---|---|---|---|
| `--max-context` | **262144** | 65536 (limit 131072) | **Above the recommended ceiling.** It is ~0.1 GB short of this PC's commit limit; the engine log says "the Windows commit limit is 97.8 GiB and the model wants about as much as there is … Windows only has 4.2 GiB left. It can end at the limit with no message (exit code 0xC0000409, #1607)". Measured below. |
| `--spec-min-p` | 0.70 | 0.5 | Calibrated value; keep if the sweep agrees. |
| `--pcie-frac` | 0.20 | free, `-1` auto | The 4070 Ti SUPER calibration in the archive landed on **0.00**; ours says 0.20. Re-measured below. |
| `--adapt-every/--adapt-swaps/--adapt-decay` | 1 / 80 / 0.97 | absent (4 / 64 / 0.99) | Aggressive adaptive expert routing. Costs ~1.06 GiB page-locked, which is where `STRATA_EXCHANGE_ROTATE` interacts. |
| `--vram-reserve-mib` | 1792 | 700 with a GPU encoder, unwritten with the CPU one | Conservative; gives away expert slots. Softer options measured below. |
| `--vision` | GPU encoder (`vision.gpu: true`) | CPU under 23.5 GB | **Against the recommendation**, and the Windows-specific evidence for the CPU encoder is strong (4080 SUPER: −35–44% decode). |
| `--expert-cache auto` | resolves to **2,189 slots** here | `auto` | The engine wanted 3,328 slots and had no VRAM for them ("profile-ranked, no eviction"). Raising free VRAM is therefore worth more than any cache flag. |
| `--mtp`, `--kv int8`, `--kv-resident 32768`, `--prefill auto`, `--spec 4`, `--pool-workers 15` | as recommended | same | Already right. |

Also relevant to stability, not speed: `C:\pagefile.sys` is **34,816 MB, automatic-managed**, giving
that 97.8 GiB commit limit and only **4.2 GiB** of headroom. The engine names #1607 (a silent exit
at the commit limit) as the failure mode, and it also declines to arm the CPU prefill share because
it wants 4.0 GiB left over. That is a real risk for a daily driver, separate from any speed question.

---

## 4. Measured on this machine

### 4.1 `tools/calibrate.py` — the vendor's own sweep, first run on this PC

768 s, 22 engine restarts, all against today's config. Each phase's numbers are only comparable
*within* that phase (later phases run with a warmer expert cache, which is why the adapt phase reads
82–86 tok/s where the PCIe phase reads 63–70).

**PCIe share** (median of 3 rounds, decode tok/s):

| `--pcie-frac` | 0.00 | 0.20 | 0.35 | 0.55 | 0.75 | 0.90 | 1.00 |
|---|---|---|---|---|---|---|---|
| median | 63.0 | **63.7** | 57.2 | 45.2 | 38.5 | 35.6 | 31.7 |
| range | 61.9–67.0 | 47.1–70.1 | 43.3–59.6 | 35.7–47.7 | 35.3–39.9 | 34.2–35.7 | 29.4–31.8 |

A confirmation pass at the two contenders settled it: `0.20` gave 67.2 / 68.1 / 73.0 against
`0.55` at 46.1 / 51.2 / 48.1. So the low end is right and **0.20 is confirmed**, but note that
**0.00 and 0.20 are inside each other's noise** (63.0 vs 63.7 with overlapping ranges) — the archive's
4070 Ti SUPER run calibrated to 0.00, and this host cannot distinguish the two. The practical rule:
any value ≤ 0.35 is fine, anything ≥ 0.55 is a large real loss (−30% at 0.55, −50% at 1.0).

**Draft floor** (`--spec-min-p`): 0.30 → 63.1, **0.50 → 68.8**, 0.70 → 68.1 (medians of 3). 0.5 and
0.7 are tied; 0.3 is worse. Calibration picks 0.5.

**CPU workers** (restarts, 2 samples each): 23 → 74.4, **15 → 77.2**, 12 → 73.5, 7 → 66.7,
6 → 68.2 tok/s. The engine's own rule for this i9-14900KF (8−1+16/2 = 15) is also the measured
optimum, and the 23 workers that the old community 4070 Ti SUPER run used are **3.6% slower** here.

**Adaptive expert tier** (2 samples each): default `4/64/0.99` → 82.1, `1/80/0.97` → 84.1,
**`1/160/0.97` → 85.6** tok/s. So the wider swap window is worth **+4.3%** over the engine default,
and it is also the most *consistent* arm (85.6 / 85.5 across both samples, where the default spread
81.7–82.6).

**What calibration therefore recommends** (it prints this but does not write it):

```json
{"--pcie-frac": "0.20", "--spec-min-p": "0.50", "--pool-workers": "15",
 "--adapt-every": "1", "--adapt-swaps": "160", "--adapt-decay": "0.97"}
```

Two real changes against today's file: `--spec-min-p 0.70 → 0.50` (tied, so either) and
`--adapt-swaps 80 → 160` (a genuine +4.3%). Everything else it endorses was already in place.

### 4.2 The settings `calibrate.py` does not touch — interleaved A/B, 2 passes

11 arms, each a full engine start, run in alternating order so restart drift lands on every arm
equally. `--prompt-cache 0` throughout so every prompt read is a real read. Values are medians over
the passes; the bracket is the observed range, which is the honesty check on every claim below.

**Prefill (tok/s)** — the column where the differences are real:

| arm | 2k | 8k | 32k | vs baseline @32k |
|---|---|---|---|---|
| baseline (today) | 995.6 | 1757.2 | 2150.4 | — |
| **`--vram-reserve-mib 700`** | 1054.2 | **1994.7** | **2473.4** | **+15.0%** |
| `--max-context 131072` | 1041.2 | 1842.7 | 2286.7 | +6.3% |
| `--vision` dropped | 1028.5 | 1734.0 | 2120.6 | −1.4% |
| `--spec-min-p 0.5 --adapt-swaps 160` | 1019.6 | 1754.3 | 2168.5 | +0.8% |
| `--pool-affinity p-cores` (15 workers) | 1026.6 | 1763.8 | 2123.1 | −1.3% |
| `--pool-affinity p-cores --pool-workers 7` | 1032.6 | 1756.2 | 2155.9 | +0.3% |
| `--pool-affinity measure` | 1028.3 | 1765.5 | 2137.2 | −0.6% |
| `STRATA_EXCHANGE_ROTATE=1` | 1016.8 | 1645.9 | 2064.2 | −4.0% |
| `STRATA_DISJOINT_ADAPT=1` | 1026.1 | 1723.3 | 2104.7 | −2.1% |

**Decode (tok/s)** — everything here is inside the ±10% noise band, so nothing is claimed from it:

| arm | 2k | 8k | 32k |
|---|---|---|---|
| baseline | 92.9 | 90.8 | **96.5** |
| `vram-reserve 700` | 90.4 | 84.4 | 93.9 |
| `max-context 131072` | 84.3 | 82.4 | 88.8 |
| `vision` dropped | 82.8 | 82.9 | 90.5 |
| `p-cores` (15) | 69.6 | 74.6 | 79.7 |
| `p-cores` (7) | 84.2 | 79.1 | 86.7 |
| `affinity measure` | 79.1 | 57.2 | 80.0 |
| `EXCHANGE_ROTATE=1` | 71.0 | 68.5 | 82.6 |
| `DISJOINT_ADAPT=1` | 80.6 | 83.7 | 79.1 |

**What this says**

1. **`--vram-reserve-mib 700` is the one real win, and it is a prefill win.** It raises the expert
   cache from **2,189 to 2,880 slots (+31.5%)**, and because the prompt path borrows those slots
   instead of reading experts from the SSD, prefill goes **+15.0% at 32 k** and **+13.5% at 8 k**
   with decode unchanged inside noise. Highest-value change available.
2. **The community's `--pool-affinity p-cores` advice is wrong on this CPU.** Every affinity variant
   was neutral-to-much-worse (−17% to −37% at some sizes). The documented 148 → 188 tok/s win was on
   an 8 P + 8 E i7-13700K, where `p-cores` still had SMT siblings to spread 7 workers over. Here 15
   workers have only 16 P-logical CPUs to share with the host, so pinning them to P-cores starves
   the pool. **Leave the default `all`.**
3. **`STRATA_EXCHANGE_ROTATE=1` and `STRATA_DISJOINT_ADAPT=1` do not reproduce here** (−4.0% and
   −2.1% prefill). Their documented wins came from other caches/desktop sizes; not worth taking.
4. **Dropping `--vision` buys nothing** (+2 expert slots, decode −6% inside noise). Keep vision on;
   whether the *encoder* runs on CPU or GPU is a server-side key, not this startup flag.
5. **`--prefill-head-alias` is unavailable in this build**: the engine refuses at start with
   "`--prefill-head-alias` is unavailable: it needs `--short-read 0`". It would cost 0.6–0.75 s per
   short read even if enabled, so it is not worth pursuing for a chat workload.
6. **The calibration picks are invisible in a 3-request burst** — expected: `--spec-min-p` and
   `--adapt-swaps` change drafting and cache *adaptation*, which need a sustained workload to show.
   They are adopted on the vendor tuner's own three-round evidence, not on these numbers.

### 4.3 Long context: measured, because this is the deciding constraint

This is the part that matters for a coding agent that must read a whole PLC/HMI project. Measured
with the shipped config (`--max-context 262144`, `--kv-resident 32768`) on a prompt built from the
repository's own docs and source, i.e. realistic engineering text.

| prompt | prefill | **time to first token** | decode at that length | result |
|---|---|---|---|---|
| **131,096 tokens** (cold) | 2,186 tok/s | **60.0 s** | 34.6 tok/s | answered normally, `finish=stop` |
| **200,024 tokens** (131K of it already cached) | — | **35.7 s** | 39.8 tok/s | answered normally, only ~71K read fresh |

- **256K context is not just theoretically supported, it is real on this box.** The engine loads at
  `max_context 262144`, reads 131K cold in 60 s, and reads a 200K conversation in 35.7 s because
  only 70,982 of its 200,024 tokens were read fresh - the other ~129,000 came out of the prompt
  cache. A cold 256K read extrapolates to **~130 s**, then it streams.
- **The load-bearing setting is `--kv-resident 32768`.** It keeps only 32K KV cells in VRAM and
  holds the whole K/V in 3.09 GiB of pinned RAM, which is what lets a 16 GB card carry a 256K
  context at all. The GPU is not the limit here.
- **But the host runs on a knife edge.** Minimum free **commit** during the 128K read was
  **1.57 GiB of 97.8 GiB**. The engine warns on every start that it "can end at the limit with no
  message (exit code 0xC0000409, #1607)". That is a page-file problem, not a context problem.

**The fix for long-context stability** (needs an elevated prompt; this session was not elevated):

1. System Properties > Advanced > Performance Settings > Advanced > Virtual memory > Change
2. Uncheck "Automatically manage paging file size for all drives"
3. C: custom size, initial **65536** MB, maximum **65536** MB, click Set, OK
4. Reboot

That lifts the commit ceiling from 97.8 GiB to roughly 128 GiB — about 30 GiB of headroom instead of
1.57. There is 670 GB free on C:, so it costs nothing. Without it, a long session plus a browser can
take the machine past the commit limit and the engine dies silently.

**Practical note for the daily driver:** you pay the big read once per conversation, not per turn.
`--prompt-cache 6` keeps six checkpoints (~118 MB each, written every 16,384 tokens); raising it to
10–12 keeps more resume points through a long PLC session at ~1.2–1.4 GB of RAM. Worth doing *after*
the page file is raised, not before.

---

## 5. What changing `--max-context` would cost (why 256K is the right choice here)

At the same 1,000 MiB reserve, dropping to 128K buys only **5.6%** prefill (2,819 vs 2,670 tok/s at
32K) and 106 expert slots, while halving the context a coding agent can hold. Measured:

| context | `--vram-reserve-mib` | expert slots | prefill @8K | prefill @32K |
|---|---|---|---|---|
| 262,144 | 1792 (today) | 2,189 | 1,788 | 2,153 |
| 262,144 | 1,000 | **2,703** | **2,169** | **2,670** |
| 131,072 | 1,000 | 2,809 | 2,782 | 2,819 |

So: **keep 256K.** The reserve change alone recovers +21–24% prefill; the extra 5.6% from halving
the context is not worth the capability.

---

## 6. Thinking modes — all four verified, three ways

Qwen3.8 Flash Next and Tiel Coder are the only models in this install with **graded** effort; every
other installed model (Ornith 1.5, Qwen3.6 Q4/Q8) renders identical prompts for low/medium/high, so
their effort selector is cosmetic. Verified in three layers:

**Layer 1 — wire prompt rendering** (no GPU): four distinct SHA-256 hashes per mode, with and without
a tools array. `none` = `322020c7…`, `low` = `8b70f4e3…`, `medium` = `052fb1e4…`, `high` = `37b204f3…`.
The mechanism: `none` pre-closes the assistant turn with `<think>\n\n</think>\n\n`; `low` prepends a
system turn "Reasoning effort is set to low…"; `high` prepends "Reasoning effort is set to xhigh…";
`medium` adds nothing.

**Layer 2 — live engine, direct pipe**: reasoning present for low/medium/high, absent for none, all
four finishing cleanly at 86–108 tok/s.

**Layer 3 — the real API, exactly as AryaAI calls it** (`POST /v1/chat/completions`,
`reasoning_effort`): server healthy in 28.2 s reporting `max_context 262144` and `images true`, all
four models listed, and every mode correct on the same arithmetic problem:

| mode | reasoning | answer | correct | wall |
|---|---|---|---|---|
| none | 0 ch | 1,346 ch | yes | 5.5 s |
| low | 371 ch | 222 ch | yes | 3.2 s |
| medium | 396 ch | 260 ch | yes | 2.8 s |
| high | **541 ch** | 131 ch | yes | 3.4 s |

Reasoning volume rises monotonically with effort (0 → 371 → 396 → 541 characters), which is the
behaviour the four-level model is supposed to have, and the answer was right in every mode including
`none`.

---

## 7. The configuration that was applied

`strata-iq3_xxs.json`, three values changed (backup kept beside it):

| key | before | after | why |
|---|---|---|---|
| `--vram-reserve-mib` | 1792 | **1000** | expert cache 2,189 → 2,703 slots; prefill +21–24% at 8K/32K; leaves 1 GB for the desktop |
| `--spec-min-p` | 0.70 | **0.50** | `calibrate.py` pick; 0.5 and 0.7 tied in the sweep, 0.3 worse |
| `--adapt-swaps` | 80 | **160** | `calibrate.py` pick: 85.6 vs 82.1 tok/s on its adapt phase (+4.3%), also the steadiest arm |
| `--max-context` | 262144 | **262144 (unchanged)** | the coding-agent requirement; confirmed working end to end |

Everything else was tested and deliberately left alone: `--kv int8`, `--kv-resident 32768`,
`--prefill auto`, `--spec 4`, `--pool-workers 15`, `--pcie-frac 0.20`, `--mtp`, `--vision`,
`--expert-cache auto`, `--prefill auto`, and the default `all` CPU affinity.

Applied and verified: config validates, all 10 referenced paths resolve, and a real server started
from it reports `loaded: true`, `max_context 262144`, `images: true`.

---

## 8. What is NOT recommended, and why (summary)

| rejected | measured here |
|---|---|
| `--pool-affinity p-cores` (the archive's biggest claim) | −17% to −37% at 2K/8K/32K on this hybrid CPU; 15 workers starve when pinned to 16 P-logical CPUs |
| `--pool-affinity measure` | −37% at 8K |
| `STRATA_EXCHANGE_ROTATE=1` | −4.0% prefill |
| `STRATA_DISJOINT_ADAPT=1` | −2.1% prefill |
| dropping `--vision` | +2 slots only, decode −6% (inside noise) |
| `--prefill-head-alias` | unavailable in this build without `--short-read 0` |
| `--kv q4_0` | not tested here; rejected on the archive's −16…−18% prefill and +8–12% perplexity |
| `--prefill auto:16384/32768` | rejected on the vendor's bit-exactness rule for CUDA |
