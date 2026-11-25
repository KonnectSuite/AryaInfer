# Settings

The Settings page is the editor for one model's run config: the `strata-*.json`
file `/api/models` lists. It shows every knob the server knows how to check —
engine flags, config keys and the environment variables that have no flag — with
a plain-language name, the raw key, the value the engine uses when you leave it
alone, a one-line explanation and, where it makes sense, a control instead of a
text box.

Nothing here is written until you press **Save**. The Changes card lists exactly
what Save would write, and the server checks every value before it touches the
file (the previous file is kept as `.bak`).

## What a setting looks like

Each row is the same shape, whether it is a flag, a config key or a variable:

| Part | Meaning |
| --- | --- |
| name | What the setting does, in plain words |
| `code` | The exact key (`--draft-cap`, `sampling.temperature`, `STRATA_HOST_CORE`) |
| control | A slider, a dropdown, a switch, a path field with **Browse…**, or a text box |
| unit | `tokens`, `MiB`, `requests` — only when the value has one |
| hint | The sentence under the control: what it changes and what it costs |
| **?** | Hover or focus for the default the engine applies when the row is empty |
| *changed* | The row no longer holds the file's value |
| **Reset** | Put this row back to the file's value |
| **Reset card** | The same for every row in that card |
| **Reset every setting** | The same for the page (asks first; still nothing written until Save) |

An empty field means "not set", which is how a config says "use the engine's
default" — that is also what the **?** tooltip quotes, so an empty box is never
ambiguous. A row marked *Speed vs. quality* changes the words the model produces
(the three lossy routing knobs); it says so in its hint and on its tooltip.

## Controls, per kind

- **Dropdown** for a closed set: `--kv` (`auto|fp16|int8|q4_0|k8v4|k8v8|fp8`,
  filtered per engine), `--draft`, `--kv-offload`, `--pool-affinity`, the
  environment variables that are 0/1.
- **Slider + number** where a range is documented: `--draft-cap` 0-32,
  `--spec` 0-16, `STRATA_ROUTE_TAIL_SKIP` 0-9, `--chunk` 64-16384.
- **Browse…** on every path: the model pack, the native shard, the draft model,
  the expert profile, the routing dump, `cwd`, `lib_dirs`.
- **Suggestions** where the value is open but has common choices: `--prefill`
  offers `auto, 2048, 4096, 8192, 16384, 32768` and still accepts anything.
- **Switch** for on/off flags; **text** for everything else.

## Presets

The first card offers measured starting points for the engine you are editing.
A chip fills the fields as an *unsaved change* — the Changes card then shows each
value it would write, and Save decides. `Recommended for a 16 GB card` on
Strata Inkling, for example, sets `--max-context 65536`, `--vram-experts-gb 9.5`,
`--ram-experts-gb 1.62`, `--kv k8v4`, `--kv-offload auto`, `--draft off` and
`--parallel 1`, which is the configuration measured at 48.9 tok/s decode at 32K
on this host. Under the chips a sentence says what the chip leaves alone, so it
is clear the rest of the file stays as it is.

The Sampling card has its own chips. `Precise`, `Balanced` and `Creative` each
set the whole sampler — temperature, top-p, top-k, min-p and the repetition
penalty — not just the temperature, and the card says so. A chip is not applied
until you Save, exactly like a hand edit.

## The "?" tooltip

The `?` beside a Reset button explains that one setting: what kind of value it
takes, the documented default and its unit, the allowed range, whether this
engine lists the setting at all, what the file holds now, and — for the three
lossy routing flags — that it changes the words the model produces. The hint
under the field says how the setting behaves; the tooltip says what the value
may be.

## Environment variables

Some knobs have no flag at all: the engine reads them from the process
environment. They are the second half of the Engine card:

- `STRATA_ROUTE_TAIL_SKIP` — leave out an expert outside VRAM when every token of
  the verify window routes it among its last N of ten. Off (0) by default; the
  measured range is 5-7 for 13-16% more decode at KL 0.004-0.032.
- `STRATA_SM89_PERF` — the 16 Ada switches Strata 0.1.68 turns on for this card.
  Off is the control arm for an A/B.
- `STRATA_HOST_CORE` — the core the host thread runs on. Leaving the first P-core
  to GPU interrupts measured +6% decode.
- `STRATA_POOL_CORES`, `STRATA_AUX_CPUS`, `STRATA_MMVQ_IL_89`, `STRATA_PF_FUSED_TQ`,
  and the prefill/adaptation/measurement switches; each row carries its own hint.

A variable the catalog does not know is still shown, with an editable name and
value, so a variable you added by hand never disappears from the page. **Empty
value** means the variable is not set.

## What this page does not do

- It does not start or stop a model. A saved config takes effect when the model
  is next started or switched.
- It does not edit `sampling` behavior of a single request; those are per-request
  settings in the chat drawer and the API (`docs/DETAILS.md`).
- It does not invent a default. When the engine's own default is not documented,
  the tooltip says "the engine decides" and the field stays empty.

## Where the knobs come from

`serve/configschema.py` is the one catalog:

- `ENGINE_FLAGS` — every flag this server can check, with its kind and help;
- `ENGINE_FLAGS_OF` — the flags each engine family actually takes, read from its
  own `--help`; `EXTRA_ACCEPTED` adds the ones a help screen omits;
- `FLAG_CHOICES`, `FLAG_META`, `FLAG_RANGES` — dropdown sets, labels, units,
  defaults, risk and ranges;
- `ENGINE_ENV` — the variables without a flag;
- `PRESETS` — the measured starting points, with the record they came from.

A flag that a family does not take is not removed from the payload: it moves to
the collapsed *Not listed by this engine* group, and comes back to its normal
card when the file already sets it.

`serve/test_engine_flags.py` is the drift check: with `STRATA_FLAG_DRIFT=1` it
runs each installed engine's `--help` and reports flags the catalog does not know
and catalogued flags the engine does not list. It is opt-in because it needs the
engines on disk; the normal suite does not start one.

Run it on this host with:

```
set STRATA_FLAG_DRIFT=1
python -m unittest serve.test_engine_flags
```