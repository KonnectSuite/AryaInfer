# AryaInfer model shootout — AryaAI promo site

**One task, six completed outputs (two models produced nothing).** Measured on this host; every number below comes from the saved session logs in each benchmark folder or from rendering the delivered site at 1440×900.

The task was fixed: build the same static AryaAI promotional site from `# BUILD PROMPT — ARYAAI STATIC PROM.txt` (15 required sections, a hero containing a CSS-built fake app window, and an explicit "no overclaiming" rule).

---

## Verdict in one line

The quality claim holds — **Qwen3.8 Flash Next is the best output here by a clear margin.** The *speed* claim does not survive measurement. And **Gemma 4 is not a waste of space** — dropping it while keeping Qwen3.6 is the one keep/drop call I'd reverse.

---

## Measured results

| Model | Quant | Gen speed (tok/s) | Output tok | Engaged build time | Assistant msgs | Sections built | Craft | Claims |
|---|---|---|---|---|---|---|---|---|
| **Qwen3.8 Flash Next** | IQ3_XXS | 74.3 | 58,069 | 20.1 min | 57 | 14/15 | **8.0** | 8.5 |
| **Ornith1.5 35B-A3B** | Q8_0 | 65.0 | 40,517 | 15.7 min | 56 | **15/15** | 7.0 | 8.0 |
| **Qwen3.6 35B-A3B** | Q8_0 | 74.9 | 43,607 | 8.1 min | 50 | **15/15** | 5.5 | **9.0** |
| **Gemma 4 26B-A4B** | Q4_K_M | **79.4** | 19,756 | **5.2 min** | 12 | **15/15** | 7.0 | **9.0** |
| **MiniCPM 4.7 35B-A3B** | Q8_0 | 59.4 | 16,908 | 3.7 min | 9 | 10/15 | 6.0 | 9.0 |
| **LFM2.5 24B-A2B** | Q8_0 | 55.1 | 19,623 | 7.5 min | 11 | **4/15** | 3.0 | **4.0** |
| **Tiel Coder 35B-A3B** | Q8_0 | 41.4 | 5,091 | 8.8 min | 17 | — no output — | — | — |
| **DeepSeek v4.1 Flash API** | (API) | — | — | — | — | — no output — | — | — |

"Gen speed" is output tokens ÷ streamed generation wall-time, aggregated across every assistant message in the session. "Engaged build time" is session wall-clock with idle gaps >120 s removed (raw spans are useless — Gemma's and Ornith's sessions sat open for ~23 hours each).

**Caveat that matters:** each model ran at a different quantisation. Gemma at Q4_K_M should be expected to out-run the Q8_0 models, and Qwen3.8 at IQ3_XXS is running the *lightest* weights in the set yet still places third. These speed numbers are not apples-to-apples.

---

## Where Qwen3.8 actually wins

1. **Its hero renders.** The single most important required element — the fake app window — works at 1440 px with all three columns legible: PROJECT sidebar, the exact user request, four status chips, and a believable ladder/ST code block (`XIC Motor_Start` / `XIO Motor_Fault` / `XIC E_Stop_Circuit` / `OTE Motor_Run` / `GEQ-LEQ Line_Speed 5..120`). **Qwen3.6's hero is physically broken at the same width** — its middle chat column collapses to a ~20 px sliver, so the request, the ticks and the code are invisible. That one screenshot decides the Qwen3.8 vs Qwen3.6 question.
2. **It covers the two hardest detail requirements** the others dropped: the 5-tab interface mock (Chat/Agent/Plan/Rockwell/Files) with the 6-step pipeline, and the 13-row capability matrix with all 12 language tags. Qwen3.6 has neither.
3. **Coherent art direction:** one bespoke mascot set in 5 states (greeting, thinking, explaining, success-celebrating, reduced-motion) exported as png/webp/apng/512, self-hosted Sora + JetBrains Mono (no external font CDN), custom SVG mark. 18 images total, 0 broken, 0 console errors.
4. **Claim discipline:** "Studio 5000-style Logix projects", "designed for Logix-style project layouts", plus a footer-level disclaimer that it does not replace validation by a qualified engineer.

### What Qwen3.8 still needs before anyone sees it
- Its footer ships **internal build artefacts**: "Brand identity from the AryaAI Production Branding Kit." and a live `MOTION: ON` dev chip. Those must not appear on a public page.
- Footer block is misaligned — centred in the left column instead of the page.
- Nav has no active state; every link renders underlined at once.
- The **Supported Work** section (4 category tiles: Software Development / Industrial Automation / Engineering Tools / Technical Analysis) is missing outright — the only one of the 15 it dropped.

---

## Where the user's read needs correcting

**"Speed" — not supported.** Qwen3.8 was the *slowest* of the successful builds by engaged time (20.1 min, 58k output tokens) and only third on token rate (74.3 tok/s behind Gemma's 79.4 and Qwen3.6's 74.9). What it actually delivered is *one-pass correctness*: 1 human turn, no rework loop. That is the real advantage and it is worth stating that way — "fastest to a finished deliverable", not "fastest".

**"Gemma 4 is a waste of space" — disagree.** It built all 15 sections with 0 console errors, 9/10 claim discipline, and did it in **5.2 minutes, 12 messages, 19.7k output tokens** — the most token-efficient complete build in the entire set. Its problems are polish (the brand kit's 12-pose companion sprite pasted in unsliced as decoration, ~200 px of dead indent inside the repo card, a missing mobile menu, no `prefers-reduced-motion`). Those are fixable. Compare with the model it is being dropped in favour of: Qwen3.6 follows the prompt more literally but ships a visibly broken hero.

**"MiniCPM / LFM / Tiel" — agree, and the case is stronger than disk space.** LFM produced 4 of 15 sections plus two **fabricated features** ("Real-Time Collaboration — team-based coding with live sync, comments, and shared workspaces") and the exact claim the prompt forbids ("Seamless integration with Studio 5000 and Rockwell Automation"). MiniCPM omitted a third of the rubric (workflow, supported work, feature showcase, architecture, principles, personas) and ships a dead `#features` nav link. Tiel Coder produced nothing at all — 5,091 output tokens and no `index.html`. The argument for dropping them is that they produce unshippable work, not that they occupy bytes.

**DeepSeek v4.1 Flash API** also produced no site, but it is an API model with no local weights — there is no disk to reclaim.

---

## Recommended keep list

| | Model | Role |
|---|---|---|
| Keep | **Qwen3.8 Flash Next** | Default. Best output, one pass, needs a 4-fix polish pass. |
| Keep | **Ornith1.5 35B-A3B** | Second. 15/15 sections, strongest Rockwell section. Fix: desktop hamburger visible at 1440 px, native scrollbars inside the mock panels, 3D cartoon mascot clashes with the art direction, broken workflow wrap on stage 6. |
| Keep one | **Gemma 4 26B-A4B** *or* **Qwen3.6 35B-A3B** | Gemma on evidence (cheapest complete build); Qwen3.6 only if you value literal spec adherence over a working hero. |
| Drop | **MiniCPM**, **LFM2.5**, **Tiel Coder** | 10/15, 4/15, and 0/15. Unshippable. |

---

## Honest limits of this test

- **One task, one sample per model.** It supports "these three produce unshippable work" strongly. It does not establish a general speed ranking, or a general "smaller models are useless" conclusion — Qwen3.8 is itself a ~35B-A3B MoE, and Gemma 4 26B-A4B (the smallest active-parameter model here at 4B active) was the fastest token emitter and the most token-efficient complete build.
- **Low discriminative power at the top.** Qwen3.8, Qwen3.6, Ornith and MiniCPM converged on nearly the same site — same eyebrow, same buttons, same copy — because they all read the same brand kit. The differences between them are execution and polish, not approach.
- A real keep/drop decision should also weigh tasks this one does not exercise: agentic tool loops, long-context code editing, PLC/Studio-domain reasoning.

---

*Evidence: 24 viewport screenshots in `.bench-review/shots/`, contact sheet at `.bench-review/heroes-side-by-side.png`, metrics and timings derived from each folder's `dsh-session-*.zip`.*
