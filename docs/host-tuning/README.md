# Host tuning: the run configs this host runs

A model's settings live in `strata-<model>.json` beside the server: context, KV format, drafting, adaptive draft,
VRAM reserve, thinking budget. Setup writes one, this host then tuned it. Those files are git-ignored because they
carry one machine's absolute paths (the clone's folder, the data folder, a log path), so this folder keeps a copy of
each with the paths replaced:

- `$INSTALL` - the folder the repository is cloned into
- `$DATA` - setup's data folder (the models, packs and MTP layer), the one `--data-dir` names

Nothing else changed: same engines, same flags, same thinking settings. No API key is in them (none of these servers
runs with one), and no model file or log is copied.

| Config | Engine | Context | KV | Drafting | VRAM reserve | PCIe fraction |
| --- | --- | --- | --- | --- | --- | --- |
| `strata-iq3_xxs.json` | `strata.exe` 0.1.56 | 262,144 | int8 | `--spec 4 --draft dflash2`, adaptive draft every 1, 160 swaps, decay 0.97 | 1000 MiB | 0.20 |
| `strata-swift-iq3_xxs.json` | `strata.exe` 0.1.56 | 262,144 | int8 | as above | 1000 MiB | 0.20 |
| `strata-swift-abliterated-iq3_xxs.json` | `strata.exe` 0.1.56 | 262,144 | int8 | as above | 1000 MiB | 0.00 |
| `strata-ornith-apex-i-quality.json` | `strata-poly.exe` | 262,144 | q8_0 | - | the engine's default | - |
| `strata-qwen36s-ud-q4_k_xl.json` | `strata-poly.exe` | 262,144 | q8_0 | - | 512 MiB | - |
| `strata-qwen36s-mtp-ud-q4_k_xl.json` | `strata-poly.exe` | 262,144 | q8_0 | - | 512 MiB | - |
| `strata-qwen36s-abliterated.json` | `strata-poly.exe` | 262,144 | q8_0 | - | 512 MiB | - |
| `strata-qwen36s-q8_0.json` | `strata-poly.exe` | 262,144 | q8_0 | - | 512 MiB | - |
| `strata-qwen3.8-27b-aq3.json` | `aryainfer.exe` | 131,072 | q4_0 | engine default | 1024 MiB | - |
| `strata-qwen3.8-27b-turbo-iq3xxs.json` | `aryainfer.exe` | 131,072 | q4_0 | engine default | 1024 MiB | - |

`strata-qwen36s-q8_0.json` is kept as the record of a measured profile: its 35.2 GB file was uninstalled on
November 3, 2026 after the four-file comparison in [the Qwen3.6 results](../QWEN36_HOST_RESULTS.md). The
`strata-qwen36s-opus-reasoning.json` example went with its model on November 5, 2026. The two Qwen3.8
27B profiles run on the Arya engine (`aryainfer.exe`) with a prompt batch of 1,024; the Poly profiles use 2,048.

The two 27B profiles keep **1024 MiB** free rather than 512. After an hour of use the engine's footprint had reached
the old reserve and its throughput fell 5-6x - from 59.9 to 10.8 tok/s, and 9.5 tok/s on a 13-token prompt - until the
engine was restarted. On a 49,519-token request the 1 GiB reserve measured 1,009 tok/s prefill and 53.6 tok/s decode
against 1,018 and 55.6 with 512 MiB, so the extra headroom costs nothing measurable.

All of them run on GPU 0 with vision on where the model has a vision encoder, thinking level medium with an 8,000-token
budget, and `fit_max_tokens` for the native Flash-Next models. The `strata.exe` profiles leave the expert cache and
prefill at the engine's own `auto`.

Every vision profile sets `"min_tokens": 1024` in its `vision` section, which the server passes to the encoder as
`--min-tokens`. Without it a small picture is encoded into about 320 tokens and the answers drift; the measurements
and the card that found it are in [the Qwen3.6 results](../QWEN36_HOST_RESULTS.md). The abliterated Qwen3.6 has no
encoder of its own, so its profile borrows the base Qwen3.6 projector.

## Put them back into an install

```powershell
python tools/apply_host_tuning.py --install C:\AryaInfer --data C:\AI\Strata-data --dry-run   # what it would write
python tools/apply_host_tuning.py --install C:\AryaInfer --data C:\AI\Strata-data
```

The tool reads each file, replaces the two placeholders, and writes `strata-<model>.json` into the install. A config
already there is kept beside it as `<name>.bak-host-tuning`, so nothing is lost. Files are written through `json`, so a
Windows path's backslashes are escaped as the format needs; substitute them by hand only if you replace the whole
quoted value including its backslashes.

These are tuning choices, not measurements. What each one was measured to do is on
[the host findings page](../ARYAINFER.md) and the per-model host-result pages it links. The display names inside the
copies are the host's own and still carry the old product name.
