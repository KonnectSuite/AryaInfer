"""serve/configschema.py - the web page's full model-config view (GET / POST /api/models/config).

The old Settings view (serve/runconfig.py) listed 19 hand-picked keys.  This module replaces that list with a complete,
ordered catalog of every documented run-config key, grouped into sections, plus a catalog of the engine flags a
"args" list may hold.  The front-end renders the catalog generically, so a new key is one entry here - not a page edit.

A value is checked before anything is written: a request with one bad value changes nothing (as runconfig.apply does).
Unknown keys are refused with a clear message; the raw JSON view is the escape hatch for anything not modelled here.
The earlier file is kept as <name>.bak; the server reads the config at start and at every switch to the model (#37),
so a change is used from the next start of, or switch to, the model.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from serve import runconfig  # its _number/save/load and value helpers stay the single source for the shared pieces

# ------------------------------------------------------------------ catalog

EFFORTS = ["none", "low", "medium", "high"]
BUDGET_LEVELS = ["off", "low", "medium", "high"]

# (key, kind, help, choices, advanced).  kind:
#   bool | enum | int>=0 | num>=0 | 0<x<=1 | 0<=x<=1 | 1..64 | int>0 | names | string | object | list | readonly
#   engine  - the engine choice (front-end merges /api/engines)
#   args    - the engine "args" list (front-end merges the flag catalog below)
#   vision  - the "vision" block (its own sub-keys are dotted keys below)
GROUPS: list[tuple[str, str, list[tuple]]] = [
    ("identity", "Identity", [
        ("display_name", "string", "The name shown in the model picker (empty: the model name)", (), False),
        ("model_name", "string", "The model's id, as the server and /v1/models list it", (), False),
        ("aliases", "names", "Other names the server lists and answers to (comma-separated)", (), False),
    ]),
    ("engine", "Engine", [
        ("exe", "engine", "Which engine binary runs this model (from the Engines view)", (), False),
        ("args", "args", "The engine's command-line flags", (), False),
        ("env", "object", "Extra environment variables for the engine process", (), True),
        ("gpu", "int>=0", "The GPU this model runs on (0 = the first card)", (), False),
        ("gpus_asked", "bool", "Record that a GPU was asked for at setup (do not change)", (), True),
        ("lib_dirs", "list", "Directories the engine searches for its DLLs (CUDA, cuBLAS)", (), True),
        ("cwd", "string", "The working directory the engine starts in", (), True),
    ]),
    ("vision", "Vision", [
        ("vision.exe", "string", "The vision encoder binary", (), False),
        ("vision.mmproj", "string", "The mmproj (vision projection) model file", (), False),
        ("vision.model", "string", "The vision model file", (), False),
        ("vision.gpu", "bool", "Run the vision encoder on the GPU", (), False),
        ("vision.max_tokens", "int>=0", "Vision tokens cap (0 or empty: default)", (), True),
        ("vision.min_tokens", "int>=0", "Vision tokens minimum (0 or empty: default)", (), True),
        ("vision.elastic", "bool", "Start the encoder with the first picture instead of the model", (), True),
    ]),
    ("sampling", "Sampling defaults", [
        ("sampling.temperature", "num>=0", "Default temperature (0 = greedy; without it the model card's: 1.0 thinking, 0.7 not)", (), False),
        ("sampling.top_p", "0<x<=1", "Default top_p for requests that send none", (), False),
        ("sampling.top_k", "1..64", "Default top_k (1-64)", (), False),
        ("sampling.min_p", "0<=x<=1", "Default min_p", (), False),
        ("sampling.presence_penalty", "num>=0", "Default presence penalty", (), False),
        ("sampling.frequency_penalty", "num>=0", "Default frequency penalty", (), False),
        ("sampling.repetition_penalty", "num>0", "Default repetition penalty (1 = off)", (), False),
        ("sampling.penalty_last_n", "int>=0", "Default repetition-penalty window (0 = whole context)", (), True),
        ("sampling.seed", "int>0", "Default seed (empty: unseeded)", (), True),
        ("sampling.experimental_speed_projection", "bool", "Default for the experimental speed-projection vector", (), True),
    ]),
    ("reasoning", "Reasoning", [
        ("reasoning_effort", "enum", "The thinking level for requests that name none", EFFORTS, False),
        ("reasoning_budget_tokens", "int>=0", "Cap every request's thinking at this many tokens (0 or empty: no cap)", (), False),
        ("reasoning_budget_by_effort", "object", "A thinking ceiling per level (off/low/medium/high)", BUDGET_LEVELS, False),
        ("reasoning_loop_recovery", "enum", "On a thinking loop: keep the answer (recover), end it (stop), or leave it (false)", ["false", "stop", "recover"], True),
        ("reasoning_close_retry", "bool", "Retry a request whose thinking tag was closed too early", (), True),
        ("anthropic_thinking", "enum", "Anthropic requests that do not ask for thinking: model (as the model does) or on_request", ["model", "on_request"], False),
        ("effort_position", "enum", "Where a non-default effort goes: start (default) or end (keeps the cache)", ["start", "end"], False),
        ("preserve_thinking", "bool", "Keep earlier turns' thinking in the prompt (templates that support it)", (), False),
    ]),
    ("behavior", "Request behavior", [
        ("fit_max_tokens", "bool", "Shorten a max_tokens that does not fit the context instead of answering 400", (), False),
        ("drop_oldest", "bool", "Drop a conversation's oldest turns when it no longer fits, instead of 400", (), False),
        ("truncate_middle", "bool", "Trim the middle of an oversized text prompt, keeping its start and end", (), False),
        ("repeat_stop_tokens", "int>=0", "End an answer that repeats one token this many times (0 = off)", (), True),
        ("tool_call_recovery", "bool", "Read a tool call written in another form (opt-in)", (), True),
        ("warm_start", "bool", "Keep the first turn of the last tool request for the next one", (), True),
        ("codex_thread_titles", "bool", "Codex thread-title handling (opt-in)", (), True),
        ("codex_compaction_cache", "bool", "Codex compaction cache (opt-in)", (), True),
    ]),
    ("lifecycle", "Lifecycle", [
        ("idle_unload_s", "num>=0", "Unload the model after this many seconds without requests (0 or empty: never)", (), False),
        ("lazy_load", "bool", "Start without loading the model; the first request loads it (text only)", (), False),
        ("engine_silence_s", "num>=0", "End a request when the engine says nothing for this long (default 300 s, 0 = wait)", (), True),
        ("api_monitor", "bool", "Keep the last 100 requests' prompts and answers for /api-monitor", (), False),
        ("switch_on_request", "bool", "List every installed model in /v1/models and load the one a request names", (), False),
        ("open_browser", "bool", "Open the chat page in the browser when the model is ready", (), False),
        ("min_free_vram_mib", "int>=0", "Load an unloaded model only when this much VRAM is free (0 or empty: no limit)", (), True),
        ("before_load", "string", "A command run before the model is loaded again", (), True),
        ("before_load_timeout_s", "num>=0", "How long the before-load command may run (default 120 s)", (), True),
        ("before_load_ignore_failure", "bool", "Always load even when the before-load command fails", (), True),
        ("before_load_strict", "bool", "Always refuse when the before-load command fails", (), True),
        ("memory_debug", "bool", "Log VRAM free before/after each load", (), True),
    ]),
    ("info", "Read-only", [
        ("context", "readonly", "The engine's full context (max tokens it can hold)", (), False),
        ("backend", "readonly", "The model's backend (which engine family runs it)", (), False),
        ("arch", "readonly", "The model architecture, where the engine reports one", (), False),
        ("port", "readonly", "The server port this model was configured for", (), False),
        ("host", "readonly", "The host this model's server binds to", (), False),
        ("tokenizer", "readonly", "The tokenizer directory", (), False),
        ("log", "readonly", "The engine log file", (), False),
    ]),
]

# kind -> (whole, lo, hi, lo_open) for the numeric kinds the front-end renders as a number input
NUMERIC = {
    "int>=0": (True, 0, None, False),
    "num>=0": (False, 0, None, False),
    "0<x<=1": (False, 0, 1, True),
    "0<=x<=1": (False, 0, 1, False),
    "1..64": (True, 1, 64, False),
    "num>0": (False, 0, None, True),
    "int>0": (True, 0, None, True),
}

# kind -> [min, max, step] the front-end renders as a slider (the bounds the kind already enforces)
KIND_RANGE = {
    "0<x<=1": [0, 1, 0.01],
    "0<=x<=1": [0, 1, 0.01],
    "1..64": [1, 64, 1],
}

# key -> [min, max, step] for the settings a useful slider can cover; a value outside the slider still
# saves through the paired number box (check() keeps the kind's own bounds - the range is only sugar).
RANGES: dict[str, list] = {
    "sampling.temperature": [0, 2, 0.05],
    "sampling.presence_penalty": [0, 2, 0.05],
    "sampling.frequency_penalty": [0, 2, 0.05],
    "sampling.repetition_penalty": [0.5, 2, 0.01],
    "reasoning_budget_tokens": [0, 65536, 256],
    "reasoning_budget_by_effort": [0, 65536, 256],   # the per-level caps share this scale
    "repeat_stop_tokens": [0, 256, 8],
    "idle_unload_s": [0, 3600, 60],
    "engine_silence_s": [0, 1800, 30],
    "min_free_vram_mib": [0, 24576, 256],
    "before_load_timeout_s": [0, 600, 10],
    "vision.max_tokens": [0, 16384, 256],
    "vision.min_tokens": [0, 4096, 64],
}

KEYS: dict[str, dict] = {}
for _g, _label, _keys in GROUPS:
    for _key, _kind, _help, _choices, _advanced in _keys:
        KEYS[_key] = {"key": _key, "kind": _kind, "help": _help, "choices": list(_choices), "advanced": _advanced}


# ------------------------------------------------------------------ engine flag catalog ("args")

# flag -> (kind, help).  kind: "bool" | "int" | "num" | "text" | "path" | ("enum", choices).
ENGINE_FLAGS: dict[str, tuple] = {
    "--vision": ("bool", "Include the image encoder"),
    "--report-drafts": ("bool", "Report draft acceptance in the status line"),
    "--lm-head-draft": ("bool", "Use the LM-head draft layer"),
    "--no-cuda-graph": ("bool", "Turn off CUDA graphs"),
    "--no-graphs": ("bool", "Turn off CUDA graphs (alias)"),
    "--split-skip-if-fits": ("bool", "Run an auto layer-split on one card when it fits"),
    "--vram-elastic": ("bool", "The expert cache in segments so VRAM can be returned"),
    "--max-context": ("int", "Tokens the attention caches hold"),
    "--kv": ("text", "KV cache dtype (e.g. q4_0, int8, f16)"),
    "--kv-dtype": ("text", "KV cache dtype (NInfer names)"),
    "--spec": ("text", "Speculative drafting width / mode"),
    "--mtp": ("path", "The MTP draft layer model"),
    "--prefill": ("text", "Prefill path (auto or an explicit mode)"),
    "--pool-workers": ("int", "Expert pool workers"),
    "--vram-reserve-mib": ("int", "VRAM in MiB left free for other programs"),
    "--spec-min-p": ("num", "Minimum draft-layer probability to keep a guess"),
    "--pcie-frac": ("num", "Fraction of experts paged over PCIe"),
    "--adapt-every": ("int", "Adapt the expert cache every N steps"),
    "--adapt-swaps": ("int", "Expert swaps per adaptation"),
    "--adapt-decay": ("num", "Adaptation decay factor"),
    "--draft": ("text", "Draft mode (e.g. dflash2)"),
    "--draft-model": ("path", "The draft model file"),
    "--draft-tokens": ("int", "Draft tokens per round"),
    "--host-kv-mib": ("int", "Host KV cache in MiB"),
    "--prefill-chunk": ("int", "Prefill chunk size"),
    "--max-concurrency": ("int", "Max concurrent requests"),
    "--pack": ("path", "The model pack directory"),
    "--native": ("path", "A native model shard"),
    "--ple-gguf": ("path", "A PLE expert shard"),
    "--expert-profile": ("path", "The expert profile file"),
    "--expert-cache": ("text", "Expert cache mode (auto or a size)"),
    "--batch": ("int", "Batch slots (parallel requests)"),
    "--layer-split": ("text", "Layer split across GPUs (auto or a layer list)"),
}

# The flag subgroups the Settings page renders the "args" flags in (order matters; a flag in no group
# lands in the trailing "Other flags" group).
FLAG_GROUPS: list[tuple[str, str, list[str]]] = [
    ("context", "Context & memory",
     ["--max-context", "--kv", "--kv-dtype", "--vram-reserve-mib", "--host-kv-mib"]),
    ("drafting", "Drafting",
     ["--spec", "--mtp", "--draft", "--draft-model", "--draft-tokens", "--spec-min-p",
      "--lm-head-draft", "--report-drafts"]),
    ("experts", "Experts & cache",
     ["--pack", "--native", "--ple-gguf", "--expert-profile", "--expert-cache", "--vram-elastic",
      "--adapt-every", "--adapt-swaps", "--adapt-decay", "--pool-workers", "--pcie-frac"]),
    ("prefill", "Prefill & batching",
     ["--prefill", "--prefill-chunk", "--batch", "--max-concurrency"]),
    ("misc", "Graphs & misc",
     ["--vision", "--no-cuda-graph", "--no-graphs", "--split-skip-if-fits", "--layer-split"]),
]

# flag -> [min, max, step] for the flags a slider covers (values outside still save via the number box).
FLAG_RANGES: dict[str, list] = {
    "--max-context": [1024, 262144, 1024],
    "--vram-reserve-mib": [0, 8192, 256],
    "--host-kv-mib": [0, 131072, 4096],
    "--prefill-chunk": [64, 8192, 64],
    "--draft-tokens": [0, 8, 1],
    "--batch": [1, 64, 1],
    "--max-concurrency": [1, 32, 1],
    "--spec-min-p": [0, 1, 0.01],
    "--pcie-frac": [0, 1, 0.01],
    "--adapt-every": [1, 64, 1],
    "--adapt-swaps": [1, 256, 4],
    "--adapt-decay": [0, 1, 0.05],
    "--pool-workers": [0, 32, 1],
}


def _flag_get(args: list, flag: str):
    """The value after `flag` in a flat ["--a","v","--b"] list, or None."""
    if not isinstance(args, list):
        return None
    for i, a in enumerate(args[:-1]):
        if a == flag:
            return str(args[i + 1])
    return None


def _flag_set(args: list, flag: str, value) -> list:
    """The list with `flag` (and its value) removed, then flag+value appended when value is not None."""
    out = []
    i = 0
    while i < len(args):
        if args[i] == flag:
            i += 2                       # skip flag and its value
            continue
        out.append(args[i])
        i += 1
    if value is not None:
        out += [flag, str(value)]
    return out


def _flag_on(args: list, flag: str, on: bool) -> list:
    out = [a for a in args if a != flag] if not on else list(args)
    if on and flag not in out:
        out.append(flag)
    return out


# ------------------------------------------------------------------ read / get / check

def load(path: str | Path) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(cfg, dict):
        raise ValueError(f"{Path(path).name} is not a JSON object")
    return cfg


def save(path: str | Path, cfg: dict) -> Path:
    """The config written whole (a temporary file moved over the old one), the earlier kept as <name>.bak."""
    path = Path(path)
    bak = path.with_name(path.name + ".bak")
    shutil.copyfile(path, bak)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, path)
    return bak


def _number(key, v, whole=False, lo=0.0, hi=None, lo_open=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (whole and v != int(v)) or \
            (v <= lo if lo_open else v < lo) or (hi is not None and v > hi):
        rng = f"{'more than' if lo_open else 'at least'} {lo:g}" + (f" and at most {hi:g}" if hi is not None else "")
        raise ValueError(f"{key}: expected a {'whole ' if whole else ''}number, {rng}, not {v!r}")
    return int(v) if whole else v


def _value_of(cfg: dict, key: str):
    """The key's current value (dotted keys walk dicts; args flags read the "args" list; absent -> None)."""
    if key.startswith("arg:"):
        return _flag_get(cfg.get("args"), key[4:])
    node: object = cfg
    for part in key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _set_value(cfg: dict, key: str, value):
    """Set (or, when value is None, remove) `key` in a deep copy of the shape already done by the caller."""
    if key.startswith("arg:"):
        cfg["args"] = _flag_set(cfg.get("args") or [], key[4:], value)
        return
    parts = key.split(".")
    node = cfg
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    leaf = parts[-1]
    if value is None:
        node.pop(leaf, None)
    else:
        node[leaf] = value
    if parts[0] == "sampling" and not node:
        cfg.pop("sampling", None)


def check(key: str, v, cfg: dict):
    """The value to store for `key`, or ValueError.  None removes the key (its default)."""
    if key.startswith("arg:"):
        flag = key[4:]
        spec = ENGINE_FLAGS.get(flag)
        if spec is None:
            raise ValueError(f"{flag} is not an editable flag here (use the raw JSON view)")
        kind = spec[0]
        if v is None:
            return None
        if kind == "bool":
            if not isinstance(v, bool):
                raise ValueError(f"{flag}: expected true or false, not {v!r}")
            return v
        if isinstance(kind, tuple) and kind[0] == "enum":
            if v not in kind[1]:
                raise ValueError(f"{flag}: expected one of {', '.join(kind[1])}, not {v!r}")
            return str(v)
        if kind == "int":
            return str(_number(flag, v, whole=True))
        if kind == "num":
            return str(_number(flag, v))
        return str(v)                                   # text / path
    spec = KEYS[key]
    kind = spec["kind"]
    if v is None:
        return None
    if kind == "readonly":
        raise ValueError(f"{key!r} is read-only")
    if kind == "bool":
        if not isinstance(v, bool):
            raise ValueError(f"{key}: expected true or false, not {v!r}")
        if key == "lazy_load" and v and cfg.get("vision"):
            raise ValueError("lazy_load: lazy loading is text-only, and this model reads images (\"vision\")")
        return v
    if kind == "enum":
        if v not in spec["choices"]:
            raise ValueError(f"{key}: expected one of {', '.join(spec['choices'])}, not {v!r}")
        return v
    if kind == "names":
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",") if x.strip()]
        if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() and len(x) <= 128 for x in v):
            raise ValueError(f"{key}: expected a list of model names, not {v!r}")
        return v or None
    if kind == "string":
        return str(v)
    if kind == "list":
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",") if x.strip()]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ValueError(f"{key}: expected a list of strings, not {v!r}")
        return v or None
    if kind == "object":
        # budget-by-effort / env: {name: value}; null removes the whole block, a null value removes that entry
        if key == "reasoning_budget_by_effort":
            if not isinstance(v, dict):
                raise ValueError(f"{key}: expected an object of level: tokens, not {v!r}")
            clean = {}
            for level, value in v.items():
                if level not in BUDGET_LEVELS:
                    raise ValueError(f"{key}: {level!r} is not a level (off, low, medium or high)")
                clean[level] = _number(f"{key}.{level}", 0 if value is None else value, whole=True)
            return clean or None
        if key == "env":
            if not isinstance(v, dict):
                raise ValueError(f"{key}: expected an object of NAME: value, not {v!r}")
            return {str(k): str(x) for k, x in v.items() if x is not None and str(x) != ""} or None
        raise ValueError(f"{key}: cannot be changed here (use the raw JSON view)")
    if kind == "engine":
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"{key}: expected an engine path, not {v!r}")
        return v
    if kind == "args":
        raise ValueError("args is edited through its flags (arg:--flag), not as a whole; use the raw JSON view")
    # numeric kinds
    if kind in NUMERIC:
        whole, lo, hi, lo_open = NUMERIC[kind]
        return _number(key, v, whole=whole, lo=lo, hi=hi, lo_open=lo_open)
    raise ValueError(f"{key!r} cannot be changed here (kind {kind!r}); use the raw JSON view")


def apply(cfg: dict, changes: dict) -> tuple[dict, list[str]]:
    """The config with `changes` ({key: value-or-None}) made, and the keys that changed.  All values are checked first,
    so a request with one bad value changes nothing (ValueError)."""
    if not isinstance(changes, dict) or not changes:
        raise ValueError('send {"set": {"<key>": <value or null>, ...}}')
    checked = {k: check(k, v, cfg) for k, v in changes.items()}
    new = json.loads(json.dumps(cfg))
    changed = []
    for key, v in checked.items():
        if key.startswith("arg:"):
            before = _flag_get(new.get("args"), key[4:])
            after = v
            if before == after:
                continue
            # bool flags: store in args via presence; value flags via flag+value
            flag = key[4:]
            kind = ENGINE_FLAGS.get(flag, ("text",))[0]
            if kind == "bool":
                new["args"] = _flag_on(new.get("args") or [], flag, v is True)
            else:
                new["args"] = _flag_set(new.get("args") or [], flag, v)
            changed.append(key)
            continue
        if _value_of(new, key) == v:
            continue
        _set_value(new, key, v)
        changed.append(key)
    # drop an empty args / sampling / vision block so the file stays tidy
    for block in ("args", "sampling", "vision", "env"):
        if block in new and new[block] in (None, [], {}):
            new.pop(block, None)
    return new, changed


# ------------------------------------------------------------------ view

def _flag_value(cfg: dict, flag: str):
    return _flag_get(cfg.get("args"), flag)


def _bool_flag(cfg: dict, flag: str):
    return isinstance(cfg.get("args"), list) and flag in cfg["args"]


def view(cfg: dict, path: str | Path) -> dict:
    """GET /api/models/config: every key, grouped, with its value (None: not set, the default applies)."""
    groups = []
    args = cfg.get("args")
    if not isinstance(args, list):
        args = []
    known_flags = sorted(ENGINE_FLAGS)
    other = []
    i = 0
    while i < len(args):
        a = args[i]
        if isinstance(a, str) and a.startswith("--") and a in ENGINE_FLAGS:
            kind = ENGINE_FLAGS[a][0]
            if kind == "bool":
                i += 1
            else:
                i += 2
            continue
        other.append(a)
        i += 1
    for g, label, keys in GROUPS:
        items = []
        for key, kind, help_, choices, advanced in keys:
            if key == "args":
                value = args
            elif key == "exe":
                value = cfg.get("exe")
            else:
                value = _value_of(cfg, key)
            item = {"key": key, "value": value, "kind": kind, "help": help_, "advanced": advanced}
            if choices:
                item["choices"] = choices
            rng = RANGES.get(key) or KIND_RANGE.get(kind)
            if rng:
                item["range"] = rng
            if kind == "args":
                flags = []
                for flag in known_flags:
                    fkind, fhelp = ENGINE_FLAGS[flag]
                    present = _bool_flag(cfg, flag) if fkind == "bool" else _flag_get(args, flag) is not None
                    fval = _bool_flag(cfg, flag) if fkind == "bool" else _flag_get(args, flag)
                    entry = {"flag": flag, "kind": fkind[0] if isinstance(fkind, tuple) else fkind,
                             "help": fhelp, "present": bool(present), "value": fval,
                             **({"choices": fkind[1]} if isinstance(fkind, tuple) else {})}
                    if flag in FLAG_RANGES:
                        entry["range"] = FLAG_RANGES[flag]
                    flags.append(entry)
                by_flag = {f["flag"]: f for f in flags}
                fgroups = [{"key": gk, "label": glabel, "flags": [by_flag[f] for f in gflags if f in by_flag]}
                           for gk, glabel, gflags in FLAG_GROUPS]
                grouped = {f for _, _, gflags in FLAG_GROUPS for f in gflags}
                rest = [f for f in flags if f["flag"] not in grouped]
                if rest:
                    fgroups.append({"key": "other", "label": "Other flags", "flags": rest})
                item["flags"] = flags
                item["flag_groups"] = fgroups
                item["other"] = other
            items.append(item)
        groups.append({"key": g, "label": label, "keys": items})
    return {"file": Path(path).name, "groups": groups,
            "note": "Saved to the run config; used from the next start of, or switch to, the model."}
