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
# This is the UNION of every flag the engines in this repo answer to, not one engine's list: a flag an
# engine does not know is moved to a collapsed group by ENGINE_FLAGS_OF rather than removed, so a value
# already in a file can always be seen and edited.  FLAG_META carries the labels, units and defaults.
ENGINE_FLAGS: dict[str, tuple] = {
    # context & memory
    "--max-context": ("int", "Tokens the attention caches hold"),
    "--kv": ("text", "KV cache dtype"),
    "--kv-dtype": ("text", "KV cache dtype (NInfer names)"),
    "--kv-grow": ("bool", "Grow the KV cache as the context fills instead of reserving it all"),
    "--vram-reserve-mib": ("int", "VRAM in MiB left free for other programs"),
    "--host-kv-mib": ("int", "Host KV cache in MiB"),
    "--vram-elastic": ("bool", "The expert cache in segments so VRAM can be returned"),
    "--vram-segment-mib": ("int", "Segment size for --vram-elastic"),
    "--short-read": ("int", "Prompts this short or shorter go through the decode path"),
    # drafting
    "--spec": ("text", "Speculative drafting width / mode"),
    "--spec-min-p": ("num", "Minimum draft-layer probability to keep a guess"),
    "--mtp": ("path", "The MTP draft layer model"),
    "--mtp-max-t": ("int", "Widest draft window for --mtp"),
    "--draft": ("text", "Draft mode"),
    "--draft-model": ("path", "The draft model file"),
    "--draft-tokens": ("int", "Draft tokens per round"),
    "--draft-cap": ("int", "Widest verify window for the draft mode"),
    "--draft-fallback": ("text", "Drafter to use when the chosen one is unavailable"),
    "--draft-conf": ("num", "Confidence below which a draft is dropped"),
    "--suffix-draft": ("int", "Suffix-lookup drafts per round"),
    "--lookup-max-t": ("int", "Widest suffix-lookup window"),
    "--lookup-sizes": ("text", "Extra suffix-lookup window sizes (comma-separated)"),
    "--lookup-chain": ("int", "Tokens the suffix lookup may chain"),
    "--lm-head-draft": ("bool", "Use the LM-head draft layer"),
    "--report-drafts": ("bool", "Report draft acceptance in the status line"),
    "--spec-follow": ("bool", "Let the drafter follow the accepted tokens"),
    "--dspark": ("bool", "Use the DSpark drafter (Inkling)"),
    # speed against the words the model produces - they change the answer, so they are marked as such
    "--tail-skip": ("int", "Leave out a tail expert outside VRAM"),
    "--skip-weight": ("num", "Leave out experts below this router weight"),
    "--cache-bias": ("num", "Favour an expert already in the VRAM cache"),
    # experts & cache
    "--pack": ("path", "The model pack directory"),
    "--native": ("path", "A native model shard"),
    "--ple-gguf": ("path", "A PLE expert shard"),
    "--expert-profile": ("path", "The expert profile file"),
    "--expert-profile-save": ("path", "Save what the adaptive tier learned to this file"),
    "--expert-cache": ("text", "Expert cache mode"),
    "--vram-experts-gb": ("num", "GiB of experts kept on the card (Inkling)"),
    "--ram-experts-gb": ("num", "GiB of experts kept in system RAM (Inkling)"),
    "--ssd-experts": ("bool", "Let the experts stream from the SSD (Inkling)"),
    "--kv-offload": ("text", "Where the KV cache lives (Inkling)"),
    "--expert-cache-cpu-order": ("bool", "Order the CPU expert pass by cache position"),
    "--mmap-experts": ("bool", "Map the experts from the file instead of reading them in"),
    "--resident-experts": ("bool", "Map the experts and keep the CPU copy resident"),
    "--adapt-every": ("int", "Adapt the expert cache every N steps"),
    "--adapt-swaps": ("int", "Expert swaps per adaptation"),
    "--adapt-decay": ("num", "Adaptation decay factor"),
    "--adapt-async": ("text", "Adapt the cache on another thread (0 or 1)"),
    "--pool-workers": ("int", "Expert pool workers"),
    "--pool-affinity": ("text", "Which cores the expert pool uses"),
    "--cpu-threads": ("int", "CPU threads the engine may use"),
    "--threads": ("int", "CPU threads for the loader and helpers"),
    "--pcie-frac": ("num", "Fraction of experts paged over PCIe"),
    "--ram-keep-gib": ("num", "RAM the engine keeps for its own tiers"),
    "--dump-routing": ("path", "Write every window's expert routing to this file"),
    "--native-router": ("bool", "Run the router on the GPU"),
    # prefill & batching
    "--prefill": ("text", "Prefill path (auto or a chunk size)"),
    "--prefill-chunk": ("int", "Prefill chunk size"),
    "--chunk": ("int", "Prompt chunk the prompt path reads at once"),
    "--prefill-head-alias": ("bool", "Read the output head beside the prompt"),
    "--batch": ("int", "Batch slots (parallel requests)"),
    "--slots": ("int", "Batch slots (alias of --batch)"),
    "--parallel": ("int", "Concurrent requests the engine serves"),
    "--max-concurrency": ("int", "Max concurrent requests"),
    "--pipeline-windows": ("int", "Decode windows the pipeline may overlap"),
    # engine runtime & model
    "--vision": ("bool", "Include the image encoder"),
    "--no-cuda-graph": ("bool", "Turn off CUDA graphs"),
    "--no-graphs": ("bool", "Turn off CUDA graphs (alias)"),
    "--no-token-graph": ("bool", "Turn off the token graph"),
    "--window-hashes": ("bool", "Check every window against a recorded hash (testing)"),
    "--split-skip-if-fits": ("bool", "Run an auto layer-split on one card when it fits"),
    "--layer-split": ("text", "Layer split across GPUs (auto or a layer list)"),
    "--gpu": ("int", "The GPU this model runs on"),
    "--gpus": ("text", "The GPUs to use (comma-separated)"),
    "--ep-split": ("text", "Expert-parallel split across GPUs"),
    "--shared-late": ("bool", "Read the shared expert late"),
    "--gpu-stages": ("bool", "Print per-stage GPU timings"),
}

# Each engine answers to its own subset of the union above.  The family comes from the executable's
# name; "other" (an engine this page does not know) keeps the whole union, because a wrong guess must
# never hide a knob that is in the file.
_EXE_FAMILY: tuple[tuple[str, str], ...] = (
    ("strata-inkling", "inkling"),
    ("inkling", "inkling"),
    ("strata-poly", "poly"),
    ("aryainfer", "poly"),
    ("arya-ninfer", "ninfer"),
    ("ninfer", "ninfer"),
    ("arya-ada", "strata"),
    ("strata", "strata"),
    ("arya", "strata"),
)


def engine_family(exe) -> str:
    """The engine family a run config's executable belongs to ("other" when nothing matches)."""
    name = str(exe or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    for stem, family in _EXE_FAMILY:
        if name.startswith(stem):
            return family
    return "other"


# Flags an engine is known NOT to take.  They still render - a value already in a file must never
# vanish - but in a collapsed "not used by this engine" group, so the list a user reads is the list
# their engine answers to.  A flag set explicitly is shown in its own group regardless.
# The flags each engine family accepts.  Read from the engines themselves: strata and inkling from
# their own --help (strata prints it on stderr), poly from the flag strings in src/poly (the shipped
# strata-poly.exe prints no help at all) and ninfer from engine-ninfer/shim/main.cpp.  A help screen
# omits flags that still work, so EXTRA_ACCEPTED adds back the ones a recorded run on this host used;
# a flag outside both sets is only ever moved to one collapsed group, never dropped.
ENGINE_FLAGS_OF: dict[str, frozenset] = {
    "strata": frozenset({
        "--adapt-async", "--adapt-every", "--adapt-min-gain", "--adapt-swaps", "--aux-cpus", "--batch",
        "--batch-groups", "--batch-mtp", "--calibrate", "--check-logits", "--control-vector",
        "--control-vector-layer-range", "--control-vector-scaled", "--conversation-cache-mib",
        "--conversation-cache-min-free-mib", "--conversation-cache-min-tokens",
        "--conversation-cache-park-gain", "--conversation-cache-rewind-keep", "--conversation-cache-slots",
        "--conversation-cache-swap-block-mib", "--coupled-draft", "--cpu-oracle-q8-0", "--cvec-dir",
        "--cvec-mode", "--draft", "--draft-cap", "--draft-conf", "--draft-fallback", "--draft-model",
        "--draft-mtp-min-p", "--draft-mtp-spec", "--draft-rule", "--dump-halves", "--dump-layers",
        "--dump-logits", "--dump-mixed", "--dump-residual", "--dump-routing", "--embd-gguf",
        "--expert-cache", "--expert-cache-cpu-order", "--expert-cache-device1", "--expert-cache-device2",
        "--expert-cache-device3", "--expert-cache-per-layer", "--expert-cache-remote-placement",
        "--expert-profile", "--expert-profile-save", "--expert-profile-save-every", "--gpu",
        "--gpu-only-full", "--gpu-stages", "--gr-fp32-activations", "--gr-native-mmvf", "--graph-only",
        "--greedy", "--host-core", "--keep-canonical", "--kv", "--kv-grow", "--kv-resident",
        "--layer-split", "--logits-stride", "--lookup-chain", "--lookup-chain-min", "--lookup-max-t",
        "--lookup-sizes", "--max-context", "--max-new", "--memory-limit-mib", "--mmap-experts", "--mtp",
        "--mtp-draft-vocab", "--mtp-hnorm", "--mtp-max-t", "--mtp-q4", "--native", "--native-",
        "--native-bf16", "--native-bf16-extra", "--native-dense-gguf", "--native-flash-attn-short",
        "--native-gdn", "--native-head-gguf", "--native-moe-combine", "--native-ple-key",
        "--native-ple-postops", "--native-qsa", "--native-qsa-indexer", "--native-rope", "--native-router",
        "--no-capture", "--no-coupled-draft", "--no-fused-gr", "--no-hit-poke", "--no-host-worker",
        "--no-ple", "--no-ple-prefetch", "--no-pool", "--no-token-graph", "--no-trim-stage-weights",
        "--pack", "--peer-adapt-swaps", "--peer-device", "--peer-prefill-rows", "--peer-reserve-mib",
        "--peer-slots", "--pipeline-windows", "--ple-delay-us", "--ple-gguf", "--ple-inflight", "--ple-io",
        "--ple-row-cache", "--ple-sync-submit", "--pool-affinity", "--pool-cores", "--pool-tasks",
        "--pool-workers", "--prefill", "--prefill-head-alias", "--prefill-pipe", "--prompt-cache",
        "--prompt-cache-every", "--prompt-cache-spread", "--prompt-cache-tail", "--ram-keep-gib",
        "--remote-expert-opt", "--resident-cpu-experts", "--resident-experts", "--rope-freq-base",
        "--rope-freq-scale", "--rope-scale", "--rope-scaling", "--seed", "--serve",
        "--session-min-free-mib", "--session-save-reclaim", "--shared-expert-arena", "--shared-late",
        "--short-read", "--slots", "--spec", "--spec-follow", "--spec-min-p", "--stage-timing", "--stats",
        "--stream-token", "--suffix-draft", "--sync-every-layer", "--tail-role-token", "--temperature",
        "--tokens", "--tokens-file", "--top-k", "--top-p", "--trim-stage-weights", "--turn-token",
        "--vision", "--vram-elastic", "--vram-segment-mib", "--window-hashes", "--yarn-attn-factor",
        "--yarn-beta-fast", "--yarn-beta-slow", "--yarn-ext-factor", "--yarn-orig-ctx",
    }),
    "inkling": frozenset({
        "--bench", "--cpu", "--cpu-threads", "--draft", "--dspark", "--ep-split", "--export-tokenizer",
        "--gen", "--gpu", "--gpus", "--info", "--kld-eval", "--kv", "--kv-offload", "--layer-split",
        "--max-context", "--native", "--parallel", "--prompt-len", "--ram-experts-gb", "--selfcheck",
        "--serve", "--ssd-experts", "--verify-hash", "--version", "--vision", "--vram-experts-gb",
        "--vram-reserve-mib",
    }),
    "poly": frozenset({
        "--any-node", "--batch", "--batch-mtp", "--cache-bias", "--check-batch", "--check-topk",
        "--check-tree", "--conversation-cache-mib", "--conversation-cache-min-free-mib",
        "--conversation-cache-min-tokens", "--conversation-cache-slots", "--cpu-share", "--draft-model",
        "--draft-vocab", "--draft-window", "--dump-layers", "--eos-ids", "--expert-profile",
        "--expert-swaps", "--follow", "--help", "--image-pad", "--images", "--kv", "--kv-whole",
        "--layer-split", "--lock-experts", "--lookup", "--lookup-chain", "--lookup-chain-min",
        "--max-context", "--max-new", "--metal-memory", "--metal-optimize", "--min-p", "--model",
        "--no-draft", "--no-gpu-experts", "--no-graphs", "--no-metal-optimize", "--prefill-f16",
        "--prompt-batch", "--prompt-cache", "--prompt-cache-every", "--ram-experts-mib", "--report-drafts",
        "--seed", "--serve", "--skip-weight", "--slots", "--spec-width", "--stage-ahead", "--stage-mib",
        "--stage-read-mib", "--tail-skip", "--temperature", "--threads", "--tokens", "--top-k", "--top-p",
        "--top-probs", "--tree", "--vram-pool", "--vram-reserve-mib", "--window",
    }),
    "ninfer": frozenset({
        "--artifact", "--ctx", "--device", "--draft-tokens", "--host-kv-mib", "--kv", "--kv-dtype",
        "--lm-head-draft", "--log-level", "--max-concurrency", "--max-context", "--model", "--ngram",
        "--ngram-max", "--ngram-min", "--ngram-n", "--ngram-pool-mib", "--no-cuda-graph",
        "--prefill-chunk", "--prompt-batch", "--safety-margin-mib", "--serve", "--spec", "--version",
        "--vision", "--vram-reserve-mib", "--weights",
    }),
}
EXTRA_ACCEPTED: dict[str, frozenset] = {
    "strata": frozenset({"--adapt-decay", "--conversation-cache-mib", "--expert-profile-save-every", "--no-capture", "--pcie-frac", "--vram-reserve-mib"}),
    "inkling": frozenset({"--chunk"}),
    "poly": frozenset({}),
    "ninfer": frozenset({}),
}

# Per-flag, per-engine options.  Only where the engine's own --help states the set; everything else
# stays free text with the suggestions in FLAG_META, so a value the page does not know still saves.
FLAG_CHOICES: dict[str, dict[str, list]] = {
    "--kv": {"inkling": ["auto", "fp16", "fp8", "k8v8", "k8v4"],
             "strata": ["fp16", "int8", "q4_0", "k8v4"]},
    "--kv-offload": {"inkling": ["auto", "on", "off"]},
    "--draft": {"inkling": ["off", "auto", "dspark"], "strata": ["mtp", "dflash2", "auto"]},
    "--draft-fallback": {"strata": ["mtp", "none"]},
    "--pool-affinity": {"strata": ["auto", "all", "p-cores", "measure"]},
    "--adapt-async": {"strata": ["0", "1"]},
}

# flag -> the words and numbers a novice needs beside it.  label: a plain-language name (the help is
# the tooltip); unit: shown after the box; default: what the engine does when the flag is absent
# (None = the engine decides, shown as "engine default"); suggest: datalist entries for a free-text
# flag; risk: "quality" when the setting changes the words the model produces.
FLAG_META: dict[str, dict] = {
    "--max-context": {"label": "Context window", "unit": "tokens"},
    "--kv": {"label": "KV cache precision", "default": "fp16"},
    "--kv-grow": {"label": "Grow the KV cache", "default": False},
    "--vram-reserve-mib": {"label": "VRAM kept free", "unit": "MiB"},
    "--host-kv-mib": {"label": "Host KV cache", "unit": "MiB"},
    "--vram-elastic": {"label": "Returnable expert cache"},
    "--vram-segment-mib": {"label": "Segment size", "unit": "MiB", "advanced": True},
    "--short-read": {"label": "Short prompt threshold", "unit": "tokens", "advanced": True},
    "--spec": {"label": "Draft width", "advanced": True},
    "--spec-min-p": {"label": "Lowest kept draft probability", "advanced": True},
    "--mtp": {"label": "MTP draft layer", "default": None},
    "--mtp-max-t": {"label": "MTP draft window", "unit": "tokens", "advanced": True},
    "--draft": {"label": "Drafter", "default": None},
    "--draft-model": {"label": "Draft model file"},
    "--draft-tokens": {"label": "Drafts per round", "unit": "tokens", "advanced": True},
    "--draft-cap": {"label": "Widest verify window", "unit": "tokens"},
    "--draft-fallback": {"label": "Fallback drafter", "advanced": True},
    "--draft-conf": {"label": "Draft confidence floor", "advanced": True},
    "--suffix-draft": {"label": "Suffix drafts per round", "advanced": True},
    "--lookup-max-t": {"label": "Suffix-lookup window", "advanced": True},
    "--lookup-sizes": {"label": "Extra lookup windows", "advanced": True},
    "--lookup-chain": {"label": "Lookup chain", "advanced": True},
    "--pack": {"label": "Model pack directory"},
    "--native": {"label": "Native model shard"},
    "--ple-gguf": {"label": "PLE expert shard"},
    "--expert-profile": {"label": "Expert profile file"},
    "--expert-profile-save": {"label": "Save the learned profile to", "advanced": True},
    "--expert-cache": {"label": "VRAM expert cache", "default": "auto", "suggest": ["auto"]},
    "--mmap-experts": {"label": "Map the experts from disk", "advanced": True},
    "--resident-experts": {"label": "Keep the CPU expert copy resident", "advanced": True},
    "--adapt-every": {"label": "Adapt the cache every", "unit": "steps", "advanced": True},
    "--adapt-swaps": {"label": "Swaps per adaptation", "advanced": True},
    "--adapt-decay": {"label": "Adaptation decay", "advanced": True},
    "--adapt-async": {"label": "Adapt on another thread", "advanced": True},
    "--pool-workers": {"label": "CPU expert workers", "unit": "threads"},
    "--pool-affinity": {"label": "Worker cores", "default": "auto"},
    "--cpu-threads": {"label": "CPU threads", "unit": "threads"},
    "--pcie-frac": {"label": "Experts over PCIe", "advanced": True},
    "--dump-routing": {"label": "Write routing to", "advanced": True},
    "--prefill": {"label": "Prompt reading", "default": "auto", "suggest": ["auto"]},
    "--prefill-chunk": {"label": "Prompt chunk", "unit": "tokens"},
    "--chunk": {"label": "Prompt chunk", "unit": "tokens"},
    "--prefill-head-alias": {"label": "Read the output head beside the prompt", "advanced": True},
    "--batch": {"label": "Batch slots", "unit": "requests"},
    "--parallel": {"label": "Concurrent requests", "unit": "requests", "default": 1},
    "--max-concurrency": {"label": "Max concurrent requests", "unit": "requests"},
    "--pipeline-windows": {"label": "Overlapped decode windows", "advanced": True},
    "--vision": {"label": "Image encoder", "default": False},
    "--layer-split": {"label": "Layer split", "advanced": True},
    "--gpu": {"label": "GPU", "unit": "index"},
    "--gpus": {"label": "GPUs", "advanced": True},
    "--ep-split": {"label": "Expert-parallel split", "advanced": True},
    "--tail-skip": {"label": "Skip a tail expert", "risk": "quality", "default": 0,
                    "help": "Leave out an expert outside VRAM when every token of the verify window routes "
                            "it among its last N of ten.  Changes the words the model produces."},
    "--skip-weight": {"label": "Skip experts below", "risk": "quality", "advanced": True},
    "--cache-bias": {"label": "Cache bias", "risk": "quality", "advanced": True},
}

# The engine's environment variables: the knobs with no flag at all.  Without this catalog they can
# only be hand-typed JSON, which is why settings like the tail-skip rank were invisible.  kind is the
# same vocabulary as the flags; choices/range/default/risk mean the same.
ENGINE_ENV: dict[str, dict] = {
    "STRATA_ROUTE_TAIL_SKIP": {
        "kind": "int", "label": "Tail-expert skip", "default": 0, "risk": "quality", "range": [0, 9, 1],
        "help": "Leave out an expert outside VRAM when every token of the window routes it among its last N "
                "of ten.  Off on every backend by default; 7 was the CUDA default until 0.1.62.  Changes the "
                "words the model produces (measured KL 0.004-0.032, 13-16% faster)."},
    "STRATA_SM89_PERF": {
        "kind": "bool", "label": "Ada speed switches", "default": True,
        "help": "The engine's own sm_89 switch table (16 settings).  Off = the plain path, for an A/B."},
    "STRATA_POOL_CORES": {
        "kind": "text", "label": "Worker cores", "default": None,
        "help": "Which cores the expert pool may use, e.g. 0-7,16-23 (P-cores first, E-cores after)."},
    "STRATA_HOST_CORE": {
        "kind": "int", "label": "Host thread core", "default": None,
        "help": "The core the host thread runs on.  Leaving the first P-core to the GPU's interrupts "
                "measured +6% decode on this host."},
    "STRATA_AUX_CPUS": {
        "kind": "int", "label": "Helper CPUs", "default": None,
        "help": "Extra CPUs the engine may use for loading and copying."},
    "STRATA_NV_CHUNK": {
        "kind": "int", "label": "Prompt chunk override", "default": 8, "range": [2, 64, 1],
        "help": "Chunk the automatic prompt sizing picked in KiB (8 = 8192 tokens; 16 raises it)."},
    "STRATA_PREFILL_CPU_SHARE": {
        "kind": "num", "label": "Prompt CPU share", "default": None, "range": [0, 1, 0.05],
        "help": "Fraction of the streamed prompt experts the CPU computes (0 = none)."},
    "STRATA_PREFILL_CPU_SHARE_MAX": {
        "kind": "int", "label": "Prompt CPU share cap", "unit": "experts", "default": None, "advanced": True,
        "help": "Never hand the CPU more than this many streamed prompt experts in one chunk."},
    "STRATA_PREFILL_CPU_SHARE_NT": {
        "kind": "int", "label": "Prompt CPU share threshold", "default": None, "advanced": True,
        "help": "Only share prompt experts with the CPU when the drawn batch is at least this wide."},
    "STRATA_PREFILL_AUTO_MAX": {
        "kind": "int", "label": "Auto prompt chunk cap", "unit": "tokens", "default": None, "advanced": True,
        "help": "Ceiling the automatic prompt sizing may pick (--prefill auto)."},
    "STRATA_PREFILL_EQUAL": {
        "kind": "bool", "label": "Equal prompt chunks", "default": None, "advanced": True,
        "help": "Split the prompt into equal chunks instead of the sized ones."},
    "STRATA_PREFILL_PIPE": {
        "kind": "bool", "label": "Pipeline the prompt read", "default": None, "advanced": True,
        "help": "Read the next prompt chunk while the current one computes."},
    "STRATA_PF_FUSED_TQ": {
        "kind": "bool", "label": "Fused trellis prompt kernels", "default": None,
        "help": "Run the fused trellis prompt path below 80 SMs (off by default on every CUDA card)."},
    "STRATA_L3_PF": {
        "kind": "bool", "label": "L2 prefetch", "default": None,
        "help": "Prefetch experts into L2.  Measured slower on this host (-8-12% on a PCIe-streaming "
                "decode), so it stays opt-in."},
    "STRATA_ADAPT_FETCH": {
        "kind": "int", "label": "Adaptive prefetch", "default": None, "range": [0, 2, 1], "advanced": True,
        "help": "How the adaptive tier prefetches on a swap: 0 none, 1 the next layer, 2 the vote."},
    "STRATA_ADAPT_ASYNC": {
        "kind": "bool", "label": "Adapt on another thread", "default": None, "advanced": True,
        "help": "Rank and promote experts on a thread of their own instead of in the decode window."},
    "STRATA_KV_GROW": {
        "kind": "bool", "label": "Grow the KV cache", "default": None,
        "help": "Grow the KV cache on demand instead of reserving the whole context up front."},
    "STRATA_MEMORY_LIMIT_MIB": {
        "kind": "int", "label": "Memory ceiling", "unit": "MiB", "default": None,
        "help": "How much system RAM the engine may hold for experts and KV."},
    "STRATA_RAM_KEEP_GIB": {
        "kind": "num", "label": "RAM to keep for tiers", "unit": "GiB", "default": None,
        "help": "RAM the expert tiers may use.  Lower it when other programs need the memory."},
    "STRATA_RESIDENT_HEADROOM_GIB": {
        "kind": "num", "label": "Resident headroom", "unit": "GiB", "default": None, "advanced": True,
        "help": "Free system RAM kept back from the resident expert tier."},
    "STRATA_BATCH_MTP": {
        "kind": "bool", "label": "Batch the MTP round", "default": None, "advanced": True,
        "help": "Run the MTP draft rows as one batch instead of row by row."},
    "STRATA_PIPELINE_AUTO": {
        "kind": "bool", "label": "Automatic pipelining", "default": None, "advanced": True,
        "help": "Let the engine decide its decode pipeline depth."},
    "STRATA_SPEC_COUPLED": {
        "kind": "bool", "label": "Coupled drafting", "default": None, "advanced": True,
        "help": "Couple the draft window to the verify cost instead of a fixed --spec."},
    "STRATA_MMVQ_IL_89": {
        "kind": "bool", "label": "sm_89 MMVQ table", "default": None, "advanced": True,
        "help": "Use the sm_89 MMVQ interleave table on this card."},
    "STRATA_INK_EXACT": {
        "kind": "int", "label": "Inkling expert lane", "default": None, "range": [0, 1, 1],
        "help": "0 = always the CPU lane, 1 = always copy into the card, unset = the engine decides."},
    "STRATA_DECODE_TIMING": {
        "kind": "bool", "label": "Print decode timings", "default": False, "advanced": True,
        "help": "Print a per-round decode timing line to the engine log (diagnostics)."},
    "STRATA_LOOKAHEAD_STATS": {
        "kind": "bool", "label": "Print lookahead stats", "default": False, "advanced": True,
        "help": "Print how well the expert lookahead predicts every 100 rounds (diagnostics)."},
    "STRATA_TRACE": {
        "kind": "int", "label": "Trace level", "default": 0, "range": [0, 2, 1], "advanced": True,
        "help": "1 = VRAM and step lines, 2 = also device waits, in the engine log (diagnostics)."},
}

# Presets: a named set of changes a user can apply with one click.  They are pending edits only - the
# Changes rail still saves them - and each one names the record it was measured in.
PRESETS: dict[str, list[dict]] = {
    "inkling": [
        {"key": "recommended", "label": "Recommended for a 16 GB card",
         "note": "64K context, 9.5 GB of experts on the card, 4-bit V, no drafting: 48.9 tok/s decode at a "
                 "32K prompt, 2122 tok/s prefill at 8K.",
         "source": "bench/results/2026-11-25-host-rtx-4070-ti-super-inkling-2-mini-sq-15/README.md",
         "flags": {"--max-context": "65536", "--vram-experts-gb": "9.5", "--kv": "k8v4", "--draft": "off"}},
        {"key": "long-context", "label": "Longest context",
         "note": "262144 tokens declared; the KV over ~16K tokens reads from host RAM, so decode drops to "
                 "~8 tok/s at a 65K prompt.  4-bit V is the lever that keeps it usable.",
         "source": "bench/results/2026-11-25-host-rtx-4070-ti-super-inkling-2-mini-sq-15/README.md",
         "flags": {"--max-context": "262144", "--vram-experts-gb": "9.5", "--kv": "k8v4", "--draft": "off"}},
    ],
    "strata": [
        {"key": "recommended", "label": "Recommended for this host",
         "note": "DFlash2 with the widest window, a 700 MiB VRAM reserve so the expert cache grows about 765 "
                 "slots (+10-11% decode measured), and the adaptive cache on.",
         "source": "docs/host-tuning/README.md",
         "flags": {"--draft": "dflash2", "--draft-cap": "8", "--expert-cache": "auto",
                   "--vram-reserve-mib": "700", "--adapt-every": "1"}},
        {"key": "stock", "label": "Stock (no tuning)", "note": "Remove every tuning flag and let the engine decide.",
         "source": "", "flags": {}},
    ],
    "poly": [
        {"key": "stock", "label": "Stock (no tuning)", "note": "Remove every tuning flag.",
         "source": "", "flags": {}},
    ],
}

# Keys whose value when unset is known and worth showing beside the box.  None (or an absent entry)
# means "the engine or the model card decides", which the page prints as that.
KEY_DEFAULTS: dict[str, object] = {
    "engine_silence_s": 300,
    "before_load_timeout_s": 120,
    "idle_unload_s": 0,
    "min_free_vram_mib": 0,
    "reasoning_budget_tokens": 0,
    "repeat_stop_tokens": 0,
    "sampling.repetition_penalty": 1,
    "sampling.penalty_last_n": 0,
    "vision.max_tokens": 0,
    "vision.min_tokens": 0,
}

# The flag subgroups the Settings page renders the "args" flags in (order matters; a flag in no group
# lands in the trailing "Other flags" group).
FLAG_GROUPS: list[tuple[str, str, list[str]]] = [
    ("context", "Context & memory",
     ["--max-context", "--kv", "--kv-dtype", "--kv-grow", "--vram-reserve-mib", "--host-kv-mib",
      "--vram-elastic", "--vram-segment-mib", "--short-read"]),
    ("drafting", "Drafting",
     ["--spec", "--mtp", "--mtp-max-t", "--draft", "--draft-model", "--draft-tokens", "--draft-cap",
      "--draft-fallback", "--draft-conf", "--spec-min-p", "--spec-follow", "--suffix-draft",
      "--lookup-max-t", "--lookup-sizes", "--lookup-chain", "--dspark", "--lm-head-draft",
      "--report-drafts"]),
    ("experts", "Experts & cache",
     ["--pack", "--native", "--ple-gguf", "--expert-profile", "--expert-profile-save", "--expert-cache",
      "--vram-experts-gb", "--ram-experts-gb", "--ssd-experts", "--vram-elastic", "--mmap-experts",
      "--resident-experts", "--adapt-every", "--adapt-swaps", "--adapt-decay", "--adapt-async",
      "--pool-workers", "--pool-affinity", "--cpu-threads", "--threads", "--pcie-frac", "--ram-keep-gib",
      "--dump-routing", "--native-router"]),
    ("prefill", "Prefill & batching",
     ["--prefill", "--prefill-chunk", "--chunk", "--prefill-head-alias", "--batch", "--slots",
      "--parallel", "--max-concurrency", "--pipeline-windows"]),
    ("quality", "Speed vs. quality",
     ["--tail-skip", "--skip-weight", "--cache-bias"]),
    ("misc", "Graphs, vision & devices",
     ["--vision", "--no-cuda-graph", "--no-graphs", "--no-token-graph", "--window-hashes",
      "--split-skip-if-fits", "--layer-split", "--gpu", "--gpus", "--ep-split", "--shared-late",
      "--gpu-stages", "--kv-offload"]),
]

# flag -> [min, max, step] for the flags a slider covers (values outside still save via the number box).
FLAG_RANGES: dict[str, list] = {
    "--max-context": [1024, 262144, 1024],
    "--vram-reserve-mib": [0, 8192, 256],
    "--host-kv-mib": [0, 131072, 4096],
    "--vram-segment-mib": [64, 4096, 64],
    "--short-read": [0, 4096, 64],
    "--prefill-chunk": [64, 16384, 64],
    "--chunk": [64, 16384, 64],
    "--draft-tokens": [0, 8, 1],
    "--draft-cap": [0, 32, 1],
    "--draft-conf": [0, 1, 0.05],
    "--mtp-max-t": [1, 16, 1],
    "--spec-min-p": [0, 1, 0.01],
    "--suffix-draft": [0, 8, 1],
    "--lookup-max-t": [0, 32, 1],
    "--lookup-chain": [0, 8, 1],
    "--vram-experts-gb": [0.5, 15.5, 0.5],
    "--ram-experts-gb": [0, 32, 0.5],
    "--ram-keep-gib": [0, 64, 1],
    "--cpu-threads": [1, 32, 1],
    "--threads": [1, 32, 1],
    "--batch": [1, 64, 1],
    "--slots": [1, 64, 1],
    "--parallel": [1, 64, 1],
    "--max-concurrency": [1, 32, 1],
    "--pipeline-windows": [0, 8, 1],
    "--pcie-frac": [0, 1, 0.01],
    "--adapt-every": [1, 64, 1],
    "--adapt-swaps": [1, 256, 4],
    "--adapt-decay": [0, 1, 0.05],
    "--pool-workers": [0, 32, 1],
    "--tail-skip": [0, 9, 1],
    "--skip-weight": [0, 0.2, 0.005],
    "--cache-bias": [0, 2, 0.1],
    "--gpu": [0, 8, 1],
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


def flag_spec(cfg: dict, flag: str) -> tuple | None:
    """(kind, help) for `flag` on this config's engine, with the engine's own option set where it is known.

    The union in ENGINE_FLAGS says a flag exists; FLAG_CHOICES narrows one to an enum for the engine that
    documents the set, and FLAG_META supplies the help shown beside the box.  None: not editable here.
    """
    spec = ENGINE_FLAGS.get(flag)
    if spec is None:
        return None
    family = engine_family(cfg.get("exe"))
    choices = FLAG_CHOICES.get(flag, {}).get(family)
    kind = ("enum", choices) if choices else spec[0]
    meta = FLAG_META.get(flag) or {}
    return (kind, meta.get("help") or spec[1])


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
    rng = f"{'more than' if lo_open else 'at least'} {lo:g}" + (f" and at most {hi:g}" if hi is not None else "")
    if isinstance(v, str):           # a form field, a preset or a JSON body carries text
        try:
            v = float(v.strip())
        except ValueError:
            raise ValueError(f"{key}: expected a {'whole ' if whole else ''}number, {rng}, not {v.strip()!r}") from None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or \
            (whole and v != int(v)) or (v <= lo if lo_open else v < lo) or (hi is not None and v > hi):
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
        spec = flag_spec(cfg, flag)
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
            kind = (flag_spec(new, flag) or ("text",))[0]
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
    """GET /api/models/config: every key and engine setting, grouped, with its value and its default.

    The engine's family decides which flags apply (`ENGINE_FLAGS_OF`): a flag the engine does not list is
    listed in one collapsed group instead of the working ones, and a flag that is set in the file is
    always shown, whatever the family says.  `engine.env` is the environment catalog - the knobs with no
    flag at all - so a setting like the tail-skip rank is editable instead of hand-typed JSON.
    """
    groups = []
    args = cfg.get("args")
    if not isinstance(args, list):
        args = []
    family = engine_family(cfg.get("exe"))
    accepted = ENGINE_FLAGS_OF.get(family) or frozenset()
    accepted = accepted | EXTRA_ACCEPTED.get(family, frozenset())
    absent = frozenset(ENGINE_FLAGS) - accepted if accepted else frozenset()
    known_flags = sorted(ENGINE_FLAGS)
    other = []
    i = 0
    while i < len(args):
        a = args[i]
        if isinstance(a, str) and a.startswith("--") and a in ENGINE_FLAGS:
            i += 1 if ENGINE_FLAGS[a][0] == "bool" else 2
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
            item = {"key": key, "value": value, "kind": kind, "help": help_, "advanced": advanced,
                    "default": KEY_DEFAULTS.get(key)}
            if choices:
                item["choices"] = choices
            rng = RANGES.get(key) or KIND_RANGE.get(kind)
            if rng:
                item["range"] = rng
            if kind == "args":
                flags = []
                for flag in known_flags:
                    fkind, fhelp = flag_spec(cfg, flag)
                    base_bool = ENGINE_FLAGS[flag][0] == "bool"
                    present = _bool_flag(cfg, flag) if base_bool else _flag_get(args, flag) is not None
                    fval = _bool_flag(cfg, flag) if base_bool else _flag_get(args, flag)
                    meta = FLAG_META.get(flag) or {}
                    entry = {"flag": flag,
                             "kind": fkind[0] if isinstance(fkind, tuple) else fkind,
                             "help": fhelp, "present": bool(present), "value": fval,
                             "label": meta.get("label") or fhelp,
                             "default": meta.get("default"),
                             "advanced": bool(meta.get("advanced")),
                             "applicable": flag not in absent or bool(present)}
                    if isinstance(fkind, tuple):
                        entry["choices"] = list(fkind[1])
                    for opt in ("unit", "risk", "suggest"):
                        if meta.get(opt):
                            entry[opt] = list(meta[opt]) if opt == "suggest" else meta[opt]
                    if flag in FLAG_RANGES:
                        entry["range"] = FLAG_RANGES[flag]
                    flags.append(entry)
                shown = [f for f in flags if f["applicable"]]
                by_flag = {f["flag"]: f for f in shown}
                # A flag belongs to one group on the page even when the catalog lists it in two
                # (--vram-elastic is both a context and an expert setting); the first group keeps it.
                seen: set[str] = set()
                fgroups = []
                for gk, glabel, gflags in FLAG_GROUPS:
                    members = [by_flag[f] for f in gflags if f in by_flag and f not in seen]
                    seen.update(f for f in gflags if f in by_flag)
                    if members:
                        fgroups.append({"key": gk, "label": glabel, "flags": members})
                grouped = {f for _, _, gflags in FLAG_GROUPS for f in gflags}
                rest = [f for f in shown if f["flag"] not in grouped]
                if rest:
                    fgroups.append({"key": "other", "label": "Other flags", "flags": rest})
                left = [f for f in flags if not f["applicable"] and not f["present"]]
                if left:
                    fgroups.append({"key": "absent", "label": f"Not listed by this engine ({family})",
                                    "flags": left})
                item["flags"] = flags
                item["flag_groups"] = fgroups
                item["other"] = other
            items.append(item)
        groups.append({"key": g, "label": label, "keys": items})
    env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
    env_items = []
    for name in sorted(ENGINE_ENV):
        spec = ENGINE_ENV[name]
        entry = {"name": name, "kind": spec.get("kind", "text"), "label": spec.get("label") or name,
                 "help": spec.get("help", ""), "default": spec.get("default"),
                 "advanced": bool(spec.get("advanced")), "value": env.get(name)}
        for opt in ("unit", "risk", "range", "choices"):
            if spec.get(opt) is not None:
                entry[opt] = spec[opt]
        env_items.append(entry)
    return {"file": Path(path).name, "groups": groups,
            "engine": {"family": family, "exe": str(cfg.get("exe") or ""), "env": env_items,
                       "unknown_env": sorted(set(env) - set(ENGINE_ENV)),
                       "presets": PRESETS.get(family, [])},
            "note": "Saved to the run config; used from the next start of, or switch to, the model."}
