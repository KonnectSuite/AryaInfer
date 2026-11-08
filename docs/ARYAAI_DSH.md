# AryaAI development DSH with AryaInfer

## Current connection and thinking audit

The [October 18 connection audit](ARYAAI_CONNECTION_AUDIT.md) removes the old
Ollama, llama.cpp and FreeToken connections and documents the actual thinking
controls for all eight installed profiles. Qwen3.8 and Tiel support distinct
effort levels; Qwen3.6, MiniCPM, Ornith and Gemma use Off/On aliases; LFM uses
native thinking without Off. Current output caps and the MiniCPM default were
preserved. The earlier 8,192-token declarations below describe benchmark-time
configuration; the current saved caps are 65,536 within total context.

## Original setup and benchmark history

This host's Qwen3.8-Flash-Next IQ3_XXS profile was measured on October 17, 2026.
See the [host benchmark](../bench/results/2026-10-17-aryastrata-qwen38-iq3xxs/README.md)
for exact measurements, source/build identities and raw records.

Qwen3.6 Q4 and Q8 are now also configured for the development app: each uses
262,144-token context, up to 8,192 output tokens, and text/image input. Their
PolyStrata profiles are `qwen3.6-35b-a3b-ud-q4_k_xl` and
`qwen3.6-35b-a3b-q8_0`. Each passed three isolated streaming/tool-result replay
checks through the development app's actual `dsh-llm-pi-ai` 0.2.0-rc.2 adapter.
See the [full Q4/Q8 host results](QWEN36_HOST_RESULTS.md). These adapter checks
do not establish acceptance of every native desktop workflow. Updated model
metadata is saved in the development profile; reload the development app to
refresh a model list that was already open.

## Additional development models

All five additional models have installed profiles and development-app metadata. Each passed three isolated streaming/tool-result replay checks. The output limit advertised to the app is 8,192 tokens within total context; it is not extra context.

| Model | ID | Total context | Input |
|---|---|---:|---|
| MiniCPM-V 4.7 35B-A3B Q4_K_M | `minicpm-v-4.7-35b-a3b-q4_k_m` | 262,144 | text, image |
| Gemma 4 26B-A4B UD-Q4_K_M | `gemma-4-26b-a4b-ud-q4_k_m` | 262,144 | text, image |
| LFM2.5-24B-A2B UD-Q4_K_XL | `lfm2.5-24b-a2b-ud-q4_k_xl` | 131,072 | text |
| Ornith 1.5 35B-A3B APEX-I-QUALITY | `ornith-1.5-35b-a3b-apex-i-quality` | 262,144 | text, image |
| Tiel Coder 35B-A3B UD-Q4_K_XL | `tiel-coder-35b-a3b-ud-q4_k_xl` | 262,144 | text, image |

Use low reasoning for MiniCPM, Ornith and Tiel for this style of coding. Gemma output-budget results and recommendations are in the [host report](MODEL_ROSTER_HOST_RESULTS.md); its standard low-mode runs hit the output allowance on some fixtures. LFM is text-only and always reasons: low/medium/high explicitly alias its native mode (`high` on the wire), with no off choice. Use at least 4,096 output tokens for work like the measured deployment probe. Its initial forced-off and incorrect non-reasoning metadata failures remain archived. Tiel has measured build-ID transcription misses. Reload the development app to refresh a model list that was already open. Existing default-model and sampling preferences remain unchanged.

These checks do not qualify the native desktop approval, compaction, recovery or large-repository workflows.

Gemma passed 2/3 long coding/image fixtures even with the larger allowance.
LFM passed 0/3 long coding fixtures and 2/6 recall trials with native thinking.
Keep those entries available for their measured shorter workloads; prefer
MiniCPM or Ornith for the full-context coding/image workload validated in this batch.

## Flint 40B-A2.5B, October 23, 2026

Flint came in with the PolyStrata 0.1.45-poly.3 merge and is added to the development profile as
`flint-40b-a2.5b-ud-q4_k_xl` on the `strata` provider: 262,144-total context, text input only.

The `strata` provider was empty before this change (`providers: {}`): the profile had been pointed at
`deepseek-account` / `deepseek-flash`, and no local server entry existed. The provider block was restored with
Flint as its only model. The default model, the account provider and the `llamacpp`/ninfer entry were left as
they were. The previous profile is `local-data/dsh-desktop-profile-before-flint.yml.bak`.

```yaml
        models:
          - id: flint-40b-a2.5b-ud-q4_k_xl
            name: AryaStrata Flint 40B A2.5B UD-Q4_K_XL - 256K
            contextWindow: 262144
            maxTokens: 32768
            input: [text]
            reasoningEfforts:
              low: low
              medium: medium
              high: high
```

The provider needs `STRATA_API_KEY` to resolve; it is set for this user to a placeholder, because the loopback
server does not require a key.

**Output budget.** 32,768 advertised tokens, not the 8,192 the other entries use. Flint's model card asks for at
least 32,768 including reasoning for hard problems, and its thinking counts toward `max_tokens`. At the 262,144
ceiling that leaves 229,376 for input. Lower it if compaction starts too early for the workload.

**Sampling.** The run config pins the card's defaults — `temperature 1.0`, `top_p 0.95`, `top_k 20` — in its
`sampling` block. They apply only to requests that send none; a client's own values win, and an explicit
`temperature: 0` is still greedy. The block lives in `strata-flint-ud-q4_k_xl.json`, which git does not track, so
re-running `setup.py` for this family writes a config without it. The pre-change file is
`local-data/flint-config-before-aryaai-calibration.json.bak`.

**Thinking levels.** Flint opens its own `<think>` block, so there is no off. Measured here, `none` and `low`
returned the same answer at 58 tokens with 165 characters of reasoning, while `high` reasoned longer (80 tokens).
The profile therefore offers low, medium and high, as the LFM entry does.

**Checked here.** The profile parses with its other 13 entries unchanged; the server accepts the sampling block
(it refuses to start on a bad value) and reports 262,144 tokens; streaming, `reasoning_content`, tool calls and
each effort level answered over the OpenAI-compatible surface the adapter uses.

**Not checked.** The `dsh-llm-pi-ai` 0.2.0-rc.2 adapter probe could not run here: its packages are packed inside
`resources/app.asar`, and the development checkout the probe expects (`C:\DeepseekAI\AryaAIDSH\deepseek-harness`)
does not exist. The 3/3 streaming and tool-replay checks recorded for the other models have not been repeated for
Flint. Reload the development app to see the entry.

## Applied development profile

Ornith APEX-I-QUALITY is configured as `ornith-1.5-35b-a3b-apex-i-quality`,
with 262,144 total context tokens, 8,192 advertised output tokens within that
budget, and text/image input. Low reasoning passed all 18 bounded coding
sessions and all three long coding/image sessions. Three isolated development
adapter checks passed. See the [model roster report](MODEL_ROSTER_HOST_RESULTS.md)
for the measured timings and limits.

MiniCPM-V 4.7 Q4_K_M is configured as
`minicpm-v-4.7-35b-a3b-q4_k_m`, with 262,144 total context tokens,
8,192 advertised output tokens within that budget, and text/image input.
The GPU vision profile passed three isolated development-adapter streaming and
tool-result replay checks. Low reasoning passed 18/18 corrected bounded coding
sessions and is recommended for these fixtures. See the
[MiniCPM host results](MINICPMV_HOST_RESULTS.md) for long-context checks,
timings, memory observations and the validator correction. Reload the development
app model list if the new entry is not visible. Existing default-model and
thinking preferences were preserved.

The local `strata` provider now uses `timeoutMs: 1200000` and
`streamIdleTimeoutMs: 1200000` (20 minutes). Near-full cold prompts measured
roughly four minutes before the first token, so the previous five-minute idle
limit left little headroom for loading and image processing. The actual
development adapter accepted these settings; this configuration check did not
simulate a 20-minute stall. Other providers were unchanged. A separate private
backup is kept at `local-data/aryaai-profile-before-long-context-timeouts.yml.bak`.

The running development app uses `%USERPROFILE%/profiles/desktop/cordis.patch.yml`.
The initial Qwen3.8 model's label, context, output capability and input modalities
were updated, followed by the two Qwen3.6 model entries. The provider key,
credentials reference, default-model selection, other
providers and existing low-thinking preference were preserved. The original file
is backed up locally under `local-data/dsh-desktop-profile-before-aryastrata.yml.bak`
in the AryaStrata checkout; it is excluded from Git. No AryaAI source code was changed.

The relevant configuration is:

```yaml
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config:
    provider: strata
    model: qwen3.8-flash-next-iq3_xxs

- id: llm-pi-ai
  name: '@deepseek-ai/dsh-llm-pi-ai'
  config:
    providers:
      strata:
        apiKeyEnv: STRATA_API_KEY
        api: openai-completions
        baseURL: http://127.0.0.1:8080/v1
        timeoutMs: 1200000
        streamIdleTimeoutMs: 1200000
        outputBudgetMode: gateway
        models:
          - id: qwen3.8-flash-next-iq3_xxs
            name: AryaStrata Qwen3.8 Flash Next IQ3_XXS - 256K
            contextWindow: 262144
            maxTokens: 8192
            input: [text, image]
            reasoningEfforts:
              'off': 'none'
              low: low
              medium: medium
              high: high
```

This is an excerpt, not a replacement for the whole profile. The existing
credential reference was retained; no key is published here. The server is
loopback-only and currently does not require a key. A fresh chat ensures the
new model metadata is used.

## Context and output budget

The model label’s 256K means 256 × 1,024 = 262,144 tokens.
262,144 is the total context ceiling, not a guaranteed amount of user text plus
unlimited output. An 8,192-token output allowance leaves at most 253,952 input
tokens before any additional system/tool budgeting, and compaction can start
earlier. The near-ceiling retrieval benchmark used 258,300 input tokens and only
128 output tokens. It does not show that the same input fits with an 8K answer.

The profile previously advertised almost the whole context as output capability
and advertised image input. The new capability metadata reserves a practical
answer budget. Image input was subsequently enabled in both the server and this development profile; the published coding and speed benchmarks remain text-only measurements. The selected output cap
is a configuration choice, not a measured optimum for every coding task.

## What was tested

- Actual development `dsh-llm-pi-ai` **0.2.0-rc.2**, its streaming adapter and
  `BlockAssembler`: **3/3** structured tool calls and replayed tool results passed.
  The probe uses the development runtime's installed packages, an isolated
  Cordis context, and a public placeholder against the local model server.
- A separate OpenAI-compatible bounded coding-agent loop: **9/9** small Python
  read/edit/test sessions passed with thinking off and **9/9** with low thinking.
  Median session times were **4.74 s** and **6.49 s** respectively.
- Three six-turn agent-style speed sessions per configuration, with four tool
  schemas, measured prompt-cache reuse and follow-up latency. These summarize
  files and do not apply code patches.

The desktop profile is configured, but a native desktop session, approval flow,
compaction, reconnect/recovery and a large-repository coding workflow were not
qualified. The authenticated desktop API was not used. The adapter probe does
not execute a real filesystem tool; its controlled tool result tests streaming
and replay fidelity. Use the recorded results within those boundaries.

## Using the profile

Keep the existing low-thinking setting for normal work unless the task calls for
another level. Thinking off was faster on the three small fixtures; those tests
are too limited to establish that it is better for complex coding.

The measured host profile serves one model request at a time. Two simultaneous
clients queued: this was not a true batch-parallel test. Prefer sequential local
model calls when evaluating latency, and include the actual tool/system prompt
size when interpreting first-token times. Fresh 32K prompts took about 11 s;
the 258K retrieval prompts took about 102 s before the answer began.
