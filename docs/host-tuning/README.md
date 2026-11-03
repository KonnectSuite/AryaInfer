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
| `strata-qwen36s-q8_0.json` | `strata-poly.exe` | 262,144 | q8_0 | - | 512 MiB | - |
| `strata-qwen36s-ud-q4_k_xl.json` | `strata-poly.exe` | 262,144 | q8_0 | - | 512 MiB | - |
| `strata-qwen3.8-27b-iq2_s.json` | `strata-poly.exe`, the qwen38 build | 204,800 | q4_0 | - | 512 MiB | - |
| `strata-qwen3.8-27b-iq3_xxs.json` | `strata-poly.exe`, the qwen38 build | 131,072 | q4_0 | - | 512 MiB | - |

All eight run on GPU 0 with vision on, thinking level medium with an 8,000-token budget, and `fit_max_tokens` for the
native Flash-Next models. The first three leave the expert cache and prefill at the engine's own `auto`.

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
