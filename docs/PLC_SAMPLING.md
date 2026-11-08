# PLC and HMI sampling on this host

What each installed model does on industrial code, measured 5 November 2026 on the
i9-14900KF / RTX 4070 Ti SUPER host, and the sampling each entry now ships with. The work
exists because AryaCode writes PLC and HMI code: IEC 61131-3 Structured Text, Studio 5000
ladder in NeutralText and L5X, and FactoryTalk View ME expressions. The NInfer profile was
added on 7 November and is reported separately below.

Everything below is one run per model per set unless a line says otherwise. The probe is
`tools/plc_sampling_probe.py`; the thinking check is `tools/thinking_mode_probe.py`. Both
drive a running server and write their results as JSON, so any number here can be re-taken.

## What the probe asks for, and how it is checked

Eight fixtures, each checked by what it produced rather than by how it reads:

| fixture | asks for | the check |
| --- | --- | --- |
| `st_seal_in` | Structured Text motor seal-in with a 5 s `TON` start timeout | `TON`, `T#5`, the three tags, and no ladder mnemonic |
| `st_scale` | Structured Text 4-20 mA / 27,648-count scale to percent, clamped | 27,648, 100.0, `REAL`, and a clamp (`MIN`/`MAX`/`LIMIT`/`IF`) |
| `st_bits` | bit 5 of a DINT into a BOOL, bit 7 set | 32 / `16#20` / `.5`, and 128 / `16#80`, and a boolean operation |
| `ld_rung` | one Studio 5000 ladder rung in NeutralText | `XIC(Start)`, `XIO(Stop)`, `OTE(Run)`, one rung, ends with `;`, balanced |
| `l5x_xml` | an L5X `<Rung Number="0" Type="N">` with `<Text>` and `<Comment>` | parses as XML, attributes correct, `<Text>` holds the logic |
| `hmi_vis` | FactoryTalk View visibility expression, Auto off and Running on | `{Auto}`, `{Running}`, a negated Auto test, `AND` |
| `hmi_alarm` | FactoryTalk alarm message showing live level and setpoint | one line, `Tank`, a `{/Tag}` placeholder |
| `st_case` | Structured Text `CASE` state machine, 30 s watchdog | `CASE`, `0:`, `10:`, `20:`, a 30 s timer |

Thinking is switched off in every probe request: this measures sampling, not reasoning.

## The four candidate sets

| name | temperature | top_p | top_k | presence |
| --- | ---: | ---: | ---: | ---: |
| `coding` | 0.6 | 0.95 | 20 | 0.0 |
| `coding-0.5` | 0.6 | 0.95 | 20 | 0.5 |
| `family` | 1.0 | 0.95 | 20 | 0.5 |
| `precise` | 0.3 | 0.9 | 20 | 0.0 |

`coding` and `coding-0.5` are the sets the Qwen3.8 and Qwen3.6 calibration used;
`family` is what the Qwen3.6 entries shipped before this pass; `precise` is the
low-temperature set that the three Flash-Next MoE files preferred.

## Results, passes of 8 fixtures

| model | coding | coding-0.5 | family | precise |
| --- | ---: | ---: | ---: | ---: |
| Ornith 1.5 35B-A3B APEX | 5 | 5 | 2 | 4 |
| Qwen3.6 35B Abliterated Q4_K_M | 4 | 4 | 4 | 5 |
| Qwen3.6 35B UD-Q4_K_XL | 5 | 5 | 4 | 4 |
| Qwen3.8 27B GSQ3 AQ3 | 3 | 5 | 4 | 5 |
| Qwen3.8 27B Turbo Brilliance | 4 | 4 | 3 | 5 |
| Qwen3.8 Flash Next IQ3_XXS | 5 | 4 | 5 | 6 |
| Swift 1.5 Abliterated IQ3_XXS | 5 | 5 | 6 | 7 |
| Swift 1.5 IQ3_XXS | 5 | 6 | 5 | 6 |
| **total** | **36** | **38** | **33** | **42** |

The Qwen3.6 35B Opus Reasoning APEX row was measured with the others and removed from the
table when its entry was uninstalled on November 5, 2026 (it did not think or perform like
Opus on this host, and Ornith and UD-Q4_K_XL were preferred). The totals above are the eight
installed models.

The NInfer profile arrived later and was measured on November 7, 2026, so it is
reported separately instead of changing the eight-model totals:

| model | coding | coding-0.5 | family | precise |
| --- | ---: | ---: | ---: | ---: |
| Qwen3.8 27B NInfer GSQ3 | 5 | 5 | not run | 5 |

It misses the same three fixtures as every other Qwen entry (`ld_rung`, `hmi_vis`,
`hmi_alarm`), and `coding-0.5` measures identical to `coding` because its sampler
ignores the presence penalty; the config ships `precise`.

Per fixture, across the eight models:

| fixture | coding | coding-0.5 | family | precise |
| --- | ---: | ---: | ---: | ---: |
| `st_seal_in` | 6 | 8 | 6 | 8 |
| `st_scale` | 7 | 8 | 7 | 7 |
| `st_bits` | 6 | 7 | 6 | 7 |
| `ld_rung` | 0 | 1 | 0 | 2 |
| `l5x_xml` | 8 | 6 | 7 | 8 |
| `hmi_vis` | 1 | 0 | 1 | 2 |
| `hmi_alarm` | 0 | 0 | 0 | 0 |
| `st_case` | 8 | 8 | 6 | 8 |

**Reading it.** Temperature 1.0 is the worst set, or tied for the worst, on all eight models
and lowers the Structured Text fixtures. Below 1.0 the sets are close: `precise` leads by four
passes over `coding-0.5`, and the lead comes from the three Flash-Next MoE files (6, 7 and 6
against 5, 5 and 6). A difference of one pass on eight fixtures is treated as a tie here,
and a tie keeps the family's documented set.

## The finding that matters more than sampling

No model produced Studio 5000 NeutralText or FactoryTalk placeholder syntax, at any
temperature, in any of the four sets:

- `ld_rung` 3 of 32, and none was one clean NeutralText rung. The answers
  were Siemens STL (`LD Start, LDN Stop, … ST Run`), a table row (`| Start | Stop | Run |`),
  a contact table, or boolean algebra with `->`.
- `hmi_vis` 4 of 32. The answers were `!Auto && Running`, `NOT([Auto]) AND [Running]`,
  `NOT Auto AND Running`, or the same with `[Tag]` brackets — none used FactoryTalk's `{Tag}`.
- `hmi_alarm` 0 of 32. The answers used `%Tag%`, `[TAG]`, `{Tag}` or `{Tag:Name}`, never the
  application's `{/Tag}`.

Structured Text fares far better: the seal-in circuit passed 28 of 32, the 4-20 mA scale
29 of 32, the `CASE` machine 30 of 32. The models know PLC structure and write valid ST;
they default to generic or Siemens surface syntax when a dialect is named.

That is not a sampling setting. It is the place to fix at the contract: give AryaCode's PLC
work a short dialect preamble (Studio 5000 NeutralText for ladder, FactoryTalk `{Tag}` and
`{/Tag}` for HMI) or a tool that composes the rung, as `l5x_compose_logic` does, rather than
expecting the surface syntax to come out right by chance.

## Thinking modes, and the defaults now shipped

Every model serves four levels and every level arrived as a different request. Off produced
no reasoning; low, medium and high all thought; the default level produced reasoning. The
table is reasoning characters on one PLC question (budget 512) and whether the small answer
was right.

| model | off | low | medium | high | default (level) |
| --- | ---: | ---: | ---: | ---: | --- |
| Ornith 1.5 35B APEX | 0 ok | 1,406 ok | 1,454 ok | 1,598 ok | 1,670 ok (medium) |
| Qwen3.6 35B Abliterated | 0 ok | 1,502 ok | 1,474 ok | 1,535 ok | 1,667 ok (none) |
| Qwen3.6 35B UD-Q4_K_XL | 0 ok | 1,568 ok | 1,676 no | 1,545 ok | 1,446 ok (medium) |
| Qwen3.8 27B AQ3 | 0 ok | 1,432 ok | 1,481 ok | 1,650 no | 1,467 ok (medium) |
| Qwen3.8 27B Turbo | 0 no | 1,527 ok | 1,478 no | 1,759 ok | 1,462 ok (medium) |
| Qwen3.8 Flash Next IQ3_XXS | 0 ok | 692 ok | 1,451 ok | 1,672 ok | 1,595 ok (medium) |
| Swift 1.5 Abliterated | 0 ok | 1,512 ok | 1,084 ok | 1,747 ok | 1,376 ok (medium) |
| Swift 1.5 IQ3_XXS | 0 no | 1,110 ok | 1,335 ok | 1,610 no | 1,549 ok (medium) |
| Qwen3.8 27B NInfer GSQ3 | 0 | 1,384 | 1,483 | 1,651 | not measured |

One question per level is not a quality measurement, and the wrong answers move around with
no level pattern: UD-Q4_K_XL answered `medium` wrong and its default (the same medium prompt)
right, and Turbo did the same. What the table establishes is the wire: the level changes the
request (110 / 138 / 134-108 / 150 prompt tokens on these templates), off is silent where the
model offers it, and the shipped default is the level the server says it is. The NInfer row
records the reasoning characters the shim streamed at each level; its answer correctness on
this fixture was not recorded.

The shipped default effort follows the earlier per-model calibration in
[AGENTIC_TUNING.md](AGENTIC_TUNING.md) and `models.json`: off (`none` in the config) for the
Abliterated Q4_K_M (5 of 6 with thinking off against 4 of 6 with it), and `medium` elsewhere.

## What each entry ships with now

The runtime configs (`strata-*.json` at the top of the checkout, which is what the
controller starts) and the tracked copies in `docs/host-tuning` carry:

| model | temperature | top_p | top_k | presence | default effort |
| --- | ---: | ---: | ---: | ---: | --- |
| Qwen3.8 27B AQ3 | 0.3 | 0.9 | 20 | 0.0 | medium |
| Qwen3.8 27B Turbo Brilliance | 0.3 | 0.9 | 20 | 0.0 | medium |
| Qwen3.6 35B UD-Q4_K_XL | 0.6 | 0.95 | 20 | 0.5 | medium |
| Qwen3.6 35B Abliterated Q4_K_M | 0.3 | 0.9 | 20 | 0.0 | none (off) |
| Ornith 1.5 35B APEX | 0.6 | 0.95 | 20 | 0.5 | medium |
| Qwen3.8 Flash Next IQ3_XXS | 0.3 | 0.9 | 20 | 0.0 | medium |
| Swift 1.5 IQ3_XXS | 0.3 | 0.9 | 20 | 0.0 | medium |
| Swift 1.5 Abliterated IQ3_XXS | 0.3 | 0.9 | 20 | 0.0 | medium |
| Qwen3.8 27B NInfer GSQ3 | 0.3 | 0.9 | 20 | 0.0 | medium |
| Qwen3.5 4B Q4_K_M | 0.7 | 0.8 | 20 | 1.5 | none (off) |

The three Flash Next / Swift entries had no `sampling` block before this pass and ran the
engine's own defaults; they now state theirs, so the setting the app shows is the setting the
engine runs.

Reasoning budgets are 20 percent higher on every entry, in both the per-level map and the
flat fallback:

| level | before | now |
| --- | ---: | ---: |
| off | 0 | 0 |
| low | 4,000 | 4,800 |
| medium | 8,000 | 9,600 |
| high | 10,000 | 12,000 |
| high (Turbo) | 12,000 | 14,400 |
| `reasoning_budget_tokens` | 8,000 | 9,600 |

Two repairs came out of the same pass. The Abliterated entry gained the vision block the
other 35B files already had (the base Qwen3.6 projector from UD-Q4_K_XL), so it can read
images again; its display name said "text". The Turbo entry's display name said 100K while
its context had already been raised to 131,072.

## What was not tested

- One sample per model per set, eight fixtures. Differences of one pass are called ties.
- The checks are structural, not compiled: no Studio 5000, MotionWorks or FactoryTalk build
  accepted the Structured Text, the rung or the L5X in this pass.
- The thinking table is one question per level. It shows the levels are wired and reach the
  model; it does not rank their quality.
- Only the PLC/HMI task style was measured. Agentic tool-call reliability at these settings
  was not re-measured; the earlier `presence_penalty` table in
  [AGENTIC_TUNING.md](AGENTIC_TUNING.md) still stands for that workload.
- The 70 GB MoE files were measured through the running server on this host with the GPU
  shared, not on a clean card.
- Qwen3.5-4B was not measured on these fixtures. Its row in the ships-with table is the
  shipped configuration, not a result.
