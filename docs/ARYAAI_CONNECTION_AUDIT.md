# AryaAI development connections and thinking controls

Checked October 18, 2026 on the AryaInfer host. AryaInfer is a fork of
[PolyStrata](https://github.com/VecSzn/PolyStrata), itself a fork of
[Niko1221's original Strata](https://github.com/Niko1221/Strata).

## Connection cleanup

| Removed provider entry | Former destination |
|---|---|
| `openai` | Ollama at `127.0.0.1:11434/v1`; this was not a cloud OpenAI connection |
| `llamacpp` | llama.cpp at `127.0.0.1:8081/v1` |
| `freetoken` | FreeToken at `127.0.0.1:8082/v1` |

The old combined `llamacpp` launcher has a disabled override, preventing its
base configuration from re-enabling it. Obsolete llama.cpp and FreeToken
launcher settings were removed. Its NInfer settings and the separate NInfer
provider were preserved. No credential files were read or changed.

The active profile is `%USERPROFILE%/profiles/desktop/cordis.patch.yml`.
A private backup is retained in ignored `local-data/`. A semantic comparison
confirmed that only the three provider removals, launcher cleanup and intended
thinking maps changed. The existing MiniCPM default, default reasoning
preferences, model context/input capabilities, timeouts and output limits were
preserved. Current model output caps are 65,536 tokens each; the connection
probes request 4,096. Output still consumes the model's total context allowance.

Reload or restart AryaAI development if its already-open model picker retains
old entries. These are saved-profile and actual-adapter checks, not verification
of every native desktop screen or an authenticated desktop-session test.

## Thinking controls by model

These findings describe the installed templates and server path, rather than
assuming every model implements the same effort scale.

| Installed model | Actual controls | AryaAI mapping |
|---|---|---|
| Qwen3.8 Flash Next IQ3_XXS | Off, Low, Medium, High | `off: none`, `low: low`, `medium: medium`, `high: high` |
| Qwen3.6 UD-Q4_K_XL | Off / On | Off sends `none`; Low/Medium/High alias native On (`high`) |
| Qwen3.6 Q8_0 | Off / On | Same binary-control mapping |
| MiniCPM-V 4.7 Q4_K_M | Off / On | Same binary-control mapping |
| Ornith APEX-I-QUALITY | Off / On | Same binary-control mapping |
| Gemma 4 UD-Q4_K_M | Off / On | Same binary-control mapping |
| Tiel Coder UD-Q4_K_XL | Off, Low, Medium, High | Same distinct-effort mapping as Qwen3.8 |
| LFM2.5 UD-Q4_K_XL | Native thinking; no Off choice | Low/Medium/High all send `high`; these are aliases |

The development selector groups equivalent enabled efforts into **On** for
binary models and **Native thinking** for LFM. Qwen3.8 and Tiel retain their
distinct Low/Medium/High levels and their supported Off choice. Compatibility
aliases remain accepted for existing agents and saved preferences, but are not
displayed as different strengths. A saved Medium selection on a binary model
therefore displays On without rewriting the chat. Historical benchmark requests
labeled `low` mean thinking On for binary models.

The adapter derives the grouping from identical explicit wire mappings; the
picker contains no model-name list. Choosing On uses the supported `high` alias.
LFM has no Off choice. These labels describe controls, not new quality or speed
measurements.

For Qwen3.8 and Tiel, the server translates High to the template's `xhigh`.
Low, Medium and High render different prompts. For the five binary-control
profiles, those three effort values render identical prompts, while Off differs.
LFM opens its native thinking block and is not offered an Off option in AryaAI.

Thinking On permits reasoning; it does not guarantee a visible reasoning block
for every short response. Output allowance and task correctness are separate
from whether the requested mode reached the model.

## Verification

| Check | Result |
|---|---|
| Installed model profiles | 8/8 present in the normal service catalog |
| Rebuilt development selector metadata | 8/8 profiles grouped correctly; all original accepted effort IDs retained |
| Renderer audit, with and without tools | 16/16 contexts passed across eight profiles |
| Advertised mode / adapter checks | 31/31 passed |
| Outgoing effort fields and tool-result replay | 62 requests matched their intended model and wire effort |
| Off-mode reasoning blocks | None in all seven Off-mode trials |
| Service after audit | MiniCPM Q4 restored, healthy, 262,144 context, GPU vision enabled |

[Raw records and tool fingerprints](../bench/results/2026-10-18-development-connection-audit/summary.json)
include the safe provider-capability export used by the adapter, cleanup record,
template fingerprints and every mode result. User preferences were preserved;
the saved MiniCPM default and the previously active server model agree.

[Selector metadata](../bench/results/2026-10-18-development-connection-audit/selector-runtime.json)
was checked separately through the rebuilt development adapter. It verifies
control grouping and compatibility IDs, rather than repeating inference or
full-context benchmarks. Restart AryaAI development to load its rebuilt Host
and browser packages together.

The [AryaAI selector change](https://github.com/KonnectSuite/AryaAI/commit/6a2d0d2800)
also passed 142 focused adapter/API/picker tests and ten browser acceptance
checks across Chromium and WebKit, including read-only snapshot replay. The wider GUI suite had
10,218 passes, 14 failures and one skip; its failures concerned other controls,
stylesheet rules and Windows file-link permissions. This is not a claim that
the complete application test suite is green.

`tools/arya_thinking_audit.py` uses each installed tokenizer and the production
`Service.render_prompt` path. It checks all eight profiles both with and without
tools and records template and rendered-prompt SHA-256 fingerprints.

`tools/arya_dsh_connection_audit.mjs` loads the development runtime's actual
adapter and saved model capability maps. For each advertised mode it requests
a structured file-read call, replays a controlled tool result and checks the
returned label. A loopback-only relay records the outgoing model, effort and
token allowance, excluding headers and credentials. Reasoning text is not
saved; only its length may be recorded. A placeholder key is used against the
unauthenticated loopback server.

The API remains `http://127.0.0.1:8080/v1`. Only one model is loaded at a time.
The previously active server model is restored after the adapter audit.
This check does not rerun full-context benchmarks or erase the measured model
limitations in the [complete host report](MODEL_ROSTER_HOST_RESULTS.md).

Reproduce with the desired service running and a non-secret export of its
provider fields (`api`, `baseURL`, `models`, timeout and budget settings):

```powershell
.\.venv\Scripts\python.exe tools/arya_thinking_audit.py --out <template-results.json>
node tools/arya_dsh_connection_audit.mjs --config <safe-provider-export.json> --runtime-root <development-runtime-project> --out <adapter-results.json>
node tools/arya_dsh_selector_audit.mjs --config <safe-provider-export.json> --runtime-root <development-runtime-project> --out <selector-results.json>
```
