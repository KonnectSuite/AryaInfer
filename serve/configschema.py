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
    "--expert-profile-save-every": ("int", "Minutes between profile saves"),
    "--remote-expert-opt": ("bool", "Try the remote expert before the local one"),
    "--ple-delay-us": ("int", "Delay between table reads"),
    "--ple-sync-submit": ("bool", "Submit table reads synchronously"),
    "--no-host-worker": ("bool", "No host worker thread"),
    "--draft-rule": ("text", "How the drafter picks its chain"),
    "--no-fused-gr": ("bool", "No fused gated residual"),
    "--gr-fp32-activations": ("bool", "Keep gated-residual activations in FP32"),
    "--gr-native-mmvf": ("bool", "Native gated-residual multiply"),
    "--stage-timing": ("bool", "Print per-stage timings"),
    "--stats": ("bool", "Print statistics when a request finishes"),
    "--mtp-draft-vocab": ("path", "The draft vocabulary file"),
    "--shared-expert-arena": ("path", "A shared expert arena file (Linux /dev/shm)"),
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
    # memory, KV placement and the CPU pool: the knobs that move decode speed on a 16 GiB card
    "--kv-resident": ("int", "Context tokens whose KV stays on the card"),
    "--memory-limit-mib": ("int", "Memory the engine may use"),
    "--ram-experts-mib": ("int", "Experts kept in system RAM (Inkling/PolyStrata)"),
    "--vram-pool": ("int", "VRAM the expert pool may fill"),
    "--pool-cores": ("text", "Cores the expert pool may use"),
    "--pool-tasks": ("int", "Pool tasks per phase"),
    "--host-core": ("int", "The core the host thread runs on"),
    "--aux-cpus": ("text", "Cores for auxiliary work"),
    "--session-min-free-mib": ("int", "Free memory a saved session leaves"),
    "--session-save-reclaim": ("bool", "Reclaim memory when a session is saved"),
    "--conversation-cache-mib": ("int", "Memory for saved conversations"),
    "--conversation-cache-slots": ("int", "Saved conversations kept"),
    "--conversation-cache-min-tokens": ("int", "Shortest conversation kept"),
    "--conversation-cache-min-free-mib": ("int", "Free memory the conversation cache leaves"),
    "--batch-groups": ("int", "Groups a batched prompt is split into"),
    "--sync-every-layer": ("bool", "Synchronise after every layer (slower, for timing)"),
    # the PLE table read (the n-gram side branch)
    "--ple-io": ("text", "How the PLE table is read (direct or mmap)"),
    "--ple-inflight": ("int", "PLE reads in flight"),
    "--ple-row-cache": ("int", "Bytes of PLE rows kept"),
    "--no-ple": ("bool", "Turn the PLE side branch off"),
    "--no-ple-prefetch": ("bool", "Turn the PLE read-ahead off"),
    # drafting detail
    "--mtp-q4": ("text", "Quantise the MTP path (all, proj or head)"),
    "--mtp-hnorm": ("bool", "Normalise the MTP hidden state"),
    "--draft-mtp-spec": ("int", "Verify width the MTP drafter aims at"),
    "--draft-mtp-min-p": ("num", "Confidence an MTP draft needs"),
    "--expert-swaps": ("int", "Expert swaps an adaptation round may make"),
    "--adapt-min-gain": ("num", "Smallest gain an adaptation round accepts"),
    "--coupled-draft": ("bool", "Couple the draft cost to the CPU share"),
    "--no-coupled-draft": ("bool", "Do not couple the draft cost"),
    "--cpu-share": ("num", "Share of a prompt's experts the CPU computes"),
    "--lock-experts": ("bool", "Pin the expert placement"),
    "--no-gpu-experts": ("bool", "Run every expert on the CPU"),
    "--spec-width": ("int", "Verify width the drafter aims at"),
    "--draft-window": ("int", "Draft window size"),
    "--batch-mtp": ("bool", "Batch the MTP step"),
    "--no-draft": ("bool", "Turn drafting off"),
    "--any-node": ("bool", "Run on any node (cluster)"),
    "--lookup": ("int", "Suffix-lookup window size"),
    "--kv-whole": ("bool", "Keep the whole KV cache"),
    "--prefill-f16": ("bool", "Read the prompt on the FP16 path"),
    "--image-pad": ("int", "Image placeholder tokens"),
    # RoPE and YaRN
    "--rope-scale": ("num", "RoPE scaling factor"),
    "--rope-freq-base": ("num", "RoPE base frequency"),
    "--rope-freq-scale": ("num", "RoPE frequency scale"),
    "--rope-scaling": ("text", "RoPE scaling mode"),
    "--yarn-attn-factor": ("num", "YaRN attention factor"),
    "--yarn-orig-ctx": ("int", "Context the model was trained at"),
    "--yarn-ext-factor": ("num", "YaRN extension factor"),
    "--yarn-beta-fast": ("num", "YaRN fast beta"),
    "--yarn-beta-slow": ("num", "YaRN slow beta"),
    # native kernel switches (off = the reference path, for an A/B)
    "--native-rope": ("bool", "Native RoPE kernel"),
    "--native-gdn": ("bool", "Native GDN kernel"),
    "--native-qsa": ("bool", "Native QSA kernel"),
    "--native-qsa-indexer": ("bool", "Native QSA indexer"),
    "--native-moe-combine": ("bool", "Native MoE combine"),
    "--native-ple-key": ("bool", "Native PLE key path"),
    "--native-bf16": ("bool", "Native BF16 path"),
    "--native-flash-attn-short": ("bool", "Native flash attention for short prompts"),
    "--native-dense-gguf": ("path", "A dense GGUF the engine reads natively"),
    "--native-head-gguf": ("path", "An output head GGUF the engine reads natively"),
    "--embd-gguf": ("path", "An embedding GGUF the engine reads natively"),
    "--cvec-dir": ("path", "A control-vector directory"),
    "--cvec-mode": ("text", "How control vectors are applied"),
    "--no-capture": ("bool", "Turn off graph capture"),
    "--no-pool": ("bool", "Turn off the CPU expert pool"),
    "--no-hit-poke": ("bool", "Turn off the cache hit hint"),
    "--keep-canonical": ("bool", "Keep the canonical weights in memory"),
    "--trim-stage-weights": ("bool", "Release staged weights after use"),
    # sampling and request shape when they are passed as flags instead of the config's sampling section
    "--temperature": ("num", "Sampling temperature"),
    "--top-k": ("int", "Top-k sampling"),
    "--top-p": ("num", "Top-p (nucleus) sampling"),
    "--min-p": ("num", "Min-p sampling"),
    "--seed": ("int", "Random seed"),
    "--max-new": ("int", "Tokens to generate"),
    "--tokens": ("int", "Prompt token count"),
    "--tokens-file": ("path", "A file of prompt token ids"),
    "--images": ("text", "Images to send with the prompt"),
    "--eos-ids": ("text", "Extra end-of-turn token ids"),
    "--stream-token": ("text", "Token that marks a streamed piece"),
    "--turn-token": ("text", "Token that ends a turn"),
    "--tail-role-token": ("text", "Token that starts the assistant's turn"),
    "--greedy": ("bool", "Greedy sampling (deterministic)"),
    "--draft-vocab": ("path", "Vocabulary the drafter may propose from"),
    # prompt cache and staging
    "--prompt-cache": ("int", "Prompt-cache entries kept"),
    "--prompt-cache-every": ("int", "Steps between prompt-cache writes"),
    "--prompt-cache-tail": ("int", "Tokens the prompt cache keeps from the tail"),
    "--prompt-cache-spread": ("bool", "Spread the prompt cache over the context"),
    "--prompt-batch": ("int", "Prompt rows per batch"),
    "--prefill-pipe": ("int", "Prompt pipeline depth"),
    "--stage-ahead": ("int", "Layers staged ahead of the compute"),
    "--stage-mib": ("int", "Bytes staged per layer"),
    "--stage-read-mib": ("int", "Bytes read per stage"),
    "--window": ("int", "Decode window size"),
    "--tree": ("bool", "Tree attention for the verify window"),
    "--follow": ("bool", "Follow an accepted draft chain"),
    "--lookup-chain-min": ("int", "Shortest chain the lookup keeps"),
    # several cards
    "--peer-device": ("int", "The peer GPU running streamed experts"),
    "--peer-slots": ("int", "Expert slots on the peer GPU"),
    "--peer-reserve-mib": ("int", "VRAM kept free on the peer GPU"),
    "--peer-prefill-rows": ("int", "Prompt rows the peer computes"),
    "--peer-adapt-swaps": ("int", "Expert swaps the peer may make"),
    "--expert-cache-device1": ("int", "Expert cache on GPU 1"),
    "--expert-cache-device2": ("int", "Expert cache on GPU 2"),
    "--expert-cache-device3": ("int", "Expert cache on GPU 3"),
    "--expert-cache-per-layer": ("bool", "Size the expert cache per layer"),
    "--expert-cache-remote-placement": ("text", "Where remote experts are placed"),
    "--control-vector": ("text", "A control vector to apply"),
    "--control-vector-layer-range": ("text", "Layers a control vector covers"),
    "--control-vector-scaled": ("bool", "Scale the control vector"),
    "--conversation-cache-park-gain": ("num", "Gain when parking a conversation"),
    "--conversation-cache-rewind-keep": ("int", "Tokens kept when a conversation rewinds"),
    "--conversation-cache-swap-block-mib": ("int", "Block size when swapping a conversation out"),
    "--resident-cpu-experts": ("bool", "Keep the CPU expert copy resident (alias of --resident-experts)"),
    "--native-bf16-extra": ("bool", "Native BF16 side paths"),
    "--native-ple-postops": ("bool", "Native post-ops in the table branch"),
    "--no-trim-stage-weights": ("bool", "Keep staged weights after use"),
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

# Flags an engine's help lists that belong to no settings page, with the reason.  A run config never carries
# them: they pick a mode the server starts (`--serve`), a one-off tool (`--selfcheck`, `--calibrate`), a
# diagnostic dump (`--dump-*`, `--check-*`), or a fragment the help printer left behind.  Recording them
# here instead of in ENGINE_FLAGS is what lets `serve/test_engine_flags.py` stay a real ratchet: a flag the
# engine gains tomorrow is neither catalogued nor excused, so the test fails until someone decides which it is.
NOT_EDITABLE: dict[str, dict[str, str]] = {
    "strata": {
        "--serve": "mode: starts the line-protocol server",
        "--native-": "fragment the help printer left behind",
        "--calibrate": "one-off tool",
        "--check-logits": "diagnostic dump",
        "--cpu-oracle-q8-0": "one-off oracle for kernel work",
        "--dump-halves": "diagnostic dump",
        "--dump-layers": "diagnostic dump",
        "--dump-logits": "diagnostic dump",
        "--dump-mixed": "diagnostic dump",
        "--dump-residual": "diagnostic dump",
        "--logits-stride": "diagnostic dump",
        "--graph-only": "diagnostic mode: builds the graph, runs nothing",
        "--gpu-only-full": "diagnostic: forces a full-VRAM placement that cannot fit here",
    },
    "poly": {
        "--serve": "mode: starts the line-protocol server",
        "--model": "alias of --native (the model file)",
        "--check-batch": "diagnostic dump",
        "--check-topk": "diagnostic dump",
        "--check-tree": "diagnostic dump",
        "--dump-layers": "diagnostic dump",
        "--top-probs": "diagnostic dump",
    },
    "inkling": {
        "--serve": "mode: starts the line-protocol server",
        "--version": "prints the build and exits",
        "--info": "prints the model header and exits",
        "--selfcheck": "one-off tool",
        "--bench": "one-off tool",
        "--kld-eval": "one-off tool",
        "--export-tokenizer": "one-off tool",
        "--verify-hash": "one-off tool",
        "--gen": "the bench's own option",
        "--prompt-len": "the bench's own option",
        "--cpu": "picks a CPU backend, not a setting",
    },
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
    # the prompt path takes "auto" or a chunk size, so the field suggests the sizes the engines document
    "--prefill": {"label": "Prompt reading", "default": "auto",
                  "suggest": ["auto", "2048", "4096", "8192", "16384", "32768"]},
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
    # memory and KV placement: the knobs that decide how much of the model is on the card
    "--kv-resident": {"label": "Context kept on the card", "unit": "tokens",
                      "help": "Tokens whose KV stays in VRAM; the rest is read from host RAM."},
    "--kv-whole": {"label": "Keep the whole KV cache", "advanced": True},
    "--memory-limit-mib": {"label": "Memory ceiling", "unit": "MiB", "advanced": True},
    "--ram-experts-mib": {"label": "Experts in system RAM", "unit": "MiB"},
    "--vram-pool": {"label": "VRAM for the expert pool", "unit": "MiB"},
    "--pool-cores": {"label": "Worker cores"},
    "--pool-tasks": {"label": "Pool tasks per phase", "advanced": True},
    "--host-core": {"label": "Host thread core", "unit": "core index"},
    "--aux-cpus": {"label": "Helper CPUs", "advanced": True},
    "--session-min-free-mib": {"label": "Free memory a saved session leaves", "unit": "MiB",
                               "advanced": True},
    "--session-save-reclaim": {"label": "Reclaim memory when saving a session", "advanced": True},
    "--conversation-cache-mib": {"label": "Saved conversations", "unit": "MiB", "advanced": True},
    "--conversation-cache-slots": {"label": "Conversations kept", "advanced": True},
    "--conversation-cache-min-tokens": {"label": "Shortest conversation kept", "unit": "tokens",
                                        "advanced": True},
    "--conversation-cache-min-free-mib": {"label": "Free memory the cache leaves", "unit": "MiB",
                                          "advanced": True},
    "--batch-groups": {"label": "Prompt batch groups", "advanced": True},
    "--sync-every-layer": {"label": "Synchronise every layer", "advanced": True},
    # the PLE side branch (the n-gram table)
    "--ple-io": {"label": "How the table is read", "advanced": True,
                 "help": "direct reads the table from disk as the layers need it; mmap maps it instead."},
    "--ple-inflight": {"label": "Table reads in flight", "advanced": True},
    "--ple-row-cache": {"label": "Table rows kept", "unit": "bytes", "advanced": True},
    "--no-ple": {"label": "Turn the table branch off", "advanced": True},
    "--no-ple-prefetch": {"label": "Turn the table read-ahead off", "advanced": True},
    # drafting detail
    "--mtp-q4": {"label": "Quantise the draft path", "advanced": True},
    "--mtp-hnorm": {"label": "Normalise the draft hidden state", "advanced": True},
    "--draft-mtp-spec": {"label": "Draft verify width", "unit": "tokens", "advanced": True},
    "--draft-mtp-min-p": {"label": "Draft confidence floor", "advanced": True},
    "--expert-swaps": {"label": "Swaps per round", "advanced": True},
    "--adapt-min-gain": {"label": "Smallest accepted gain", "advanced": True},
    "--coupled-draft": {"label": "Couple drafting to the CPU share", "advanced": True},
    "--no-coupled-draft": {"label": "Do not couple drafting", "advanced": True},
    "--cpu-share": {"label": "Prompt experts on the CPU", "advanced": True},
    "--lock-experts": {"label": "Pin the expert placement", "advanced": True},
    "--no-gpu-experts": {"label": "Run every expert on the CPU", "advanced": True},
    "--spec-width": {"label": "Verify width", "unit": "tokens", "advanced": True},
    "--draft-window": {"label": "Draft window", "unit": "tokens", "advanced": True},
    "--batch-mtp": {"label": "Batch the draft round", "advanced": True},
    "--no-draft": {"label": "No drafting", "advanced": True},
    "--lookup": {"label": "Suffix-lookup window", "advanced": True},
    "--any-node": {"label": "Run on any node", "advanced": True},
    "--prefill-f16": {"label": "Read the prompt on the FP16 path", "advanced": True},
    "--image-pad": {"label": "Image placeholder tokens", "unit": "tokens", "advanced": True},
    # RoPE and YaRN
    "--rope-scale": {"label": "RoPE scale", "advanced": True},
    "--rope-freq-base": {"label": "RoPE base frequency", "advanced": True},
    "--rope-freq-scale": {"label": "RoPE frequency scale", "advanced": True},
    "--rope-scaling": {"label": "RoPE mode", "advanced": True},
    "--yarn-attn-factor": {"label": "YaRN attention factor", "advanced": True},
    "--yarn-orig-ctx": {"label": "Trained context", "unit": "tokens", "advanced": True},
    "--yarn-ext-factor": {"label": "YaRN extension factor", "advanced": True},
    "--yarn-beta-fast": {"label": "YaRN fast beta", "advanced": True},
    "--yarn-beta-slow": {"label": "YaRN slow beta", "advanced": True},
    # native kernel switches: off = the reference path, which is what an A/B needs
    "--native-rope": {"label": "Native RoPE kernel", "advanced": True},
    "--native-gdn": {"label": "Native GDN kernel", "advanced": True},
    "--native-qsa": {"label": "Native QSA kernel", "advanced": True},
    "--native-qsa-indexer": {"label": "Native QSA indexer", "advanced": True},
    "--native-moe-combine": {"label": "Native expert combine", "advanced": True},
    "--native-ple-key": {"label": "Native table key path", "advanced": True},
    "--native-bf16": {"label": "Native BF16 path", "advanced": True},
    "--native-flash-attn-short": {"label": "Native short-prompt attention", "advanced": True},
    "--native-dense-gguf": {"label": "Dense GGUF read natively", "advanced": True},
    "--native-head-gguf": {"label": "Output head read natively", "advanced": True},
    "--embd-gguf": {"label": "Embedding GGUF", "advanced": True},
    "--cvec-dir": {"label": "Control-vector folder", "advanced": True},
    "--cvec-mode": {"label": "Control-vector mode", "advanced": True},
    "--no-capture": {"label": "No graph capture", "advanced": True},
    "--no-pool": {"label": "No CPU expert pool", "advanced": True},
    "--no-hit-poke": {"label": "No cache hint", "advanced": True},
    "--keep-canonical": {"label": "Keep canonical weights", "advanced": True},
    "--trim-stage-weights": {"label": "Release staged weights", "advanced": True},
}

# Labels only: these flags already carry a help sentence that says what they do, so all that is missing is a
# short name to put in the field head.  Nothing here changes a default, a range or a hint.
FLAG_META.update({
    "--control-vector": {"label": "Control vector"},
    "--control-vector-layer-range": {"label": "Vector layers"},
    "--control-vector-scaled": {"label": "Scale the vector"},
    "--conversation-cache-min-tokens": {"label": "Shortest conversation kept"},
    "--conversation-cache-park-gain": {"label": "Parking gain"},
    "--conversation-cache-rewind-keep": {"label": "Kept on rewind"},
    "--conversation-cache-swap-block-mib": {"label": "Swap block", "unit": "MiB"},
    "--draft-rule": {"label": "Draft chain rule"},
    "--draft-vocab": {"label": "Draft vocabulary"},
    "--dspark": {"label": "DSpark drafter"},
    "--eos-ids": {"label": "End-of-turn ids"},
    "--expert-cache-cpu-order": {"label": "CPU order by cache position"},
    "--expert-cache-device1": {"label": "Expert cache on GPU 1"},
    "--expert-cache-device2": {"label": "Expert cache on GPU 2"},
    "--expert-cache-device3": {"label": "Expert cache on GPU 3"},
    "--expert-cache-per-layer": {"label": "Expert cache per layer"},
    "--expert-cache-remote-placement": {"label": "Remote expert placement"},
    "--expert-profile-save-every": {"label": "Save the profile every", "unit": "min"},
    "--follow": {"label": "Follow an accepted chain"},
    "--gpu-stages": {"label": "Print GPU stage timings"},
    "--gr-fp32-activations": {"label": "Gated residual in FP32"},
    "--gr-native-mmvf": {"label": "Native gated-residual multiply"},
    "--greedy": {"label": "Greedy sampling"},
    "--image-pad": {"label": "Image placeholder tokens", "unit": "tokens"},
    "--images": {"label": "Images"},
    "--kv-dtype": {"label": "KV data type"},
    "--kv-offload": {"label": "KV offload"},
    "--kv-whole": {"label": "Whole KV cache"},
    "--lm-head-draft": {"label": "Draft from the output head"},
    "--lock-experts": {"label": "Pin the expert placement"},
    "--lookup-chain-min": {"label": "Shortest lookup chain"},
    "--max-concurrency": {"label": "Max concurrent requests", "unit": "requests"},
    "--max-new": {"label": "Tokens to generate"},
    "--min-p": {"label": "Min-p"},
    "--mtp-draft-vocab": {"label": "Draft vocabulary file"},
    "--native-bf16": {"label": "Native BF16 path"},
    "--native-bf16-extra": {"label": "Native BF16 side paths"},
    "--native-gdn": {"label": "Native GDN kernel"},
    "--native-ple-postops": {"label": "Native table post-ops"},
    "--native-qsa": {"label": "Native QSA kernel"},
    "--native-qsa-indexer": {"label": "Native QSA indexer"},
    "--native-rope": {"label": "Native RoPE kernel"},
    "--native-router": {"label": "Router on the GPU"},
    "--no-cuda-graph": {"label": "No CUDA graphs"},
    "--no-fused-gr": {"label": "No fused gated residual"},
    "--no-gpu-experts": {"label": "Experts on the CPU only"},
    "--no-graphs": {"label": "No CUDA graphs"},
    "--no-host-worker": {"label": "No host worker"},
    "--no-token-graph": {"label": "No token graph"},
    "--no-trim-stage-weights": {"label": "Keep staged weights"},
    "--peer-adapt-swaps": {"label": "Peer swaps per round"},
    "--peer-device": {"label": "Peer GPU", "unit": "index"},
    "--peer-prefill-rows": {"label": "Peer prompt rows"},
    "--peer-reserve-mib": {"label": "VRAM kept free on the peer", "unit": "MiB"},
    "--peer-slots": {"label": "Peer expert slots"},
    "--ple-delay-us": {"label": "Table read delay", "unit": "µs"},
    "--ple-sync-submit": {"label": "Synchronous table reads"},
    "--pool-tasks": {"label": "Pool tasks per phase"},
    "--prefill-f16": {"label": "Prompt on the FP16 path"},
    "--prefill-head-alias": {"label": "Read the head beside the prompt"},
    "--prefill-pipe": {"label": "Prompt pipeline depth"},
    "--prompt-batch": {"label": "Prompt rows per batch"},
    "--prompt-cache": {"label": "Prompt cache entries"},
    "--prompt-cache-every": {"label": "Steps between cache writes"},
    "--prompt-cache-spread": {"label": "Spread the prompt cache"},
    "--prompt-cache-tail": {"label": "Tail tokens kept"},
    "--ram-experts-gb": {"label": "Experts in system RAM", "unit": "GiB"},
    "--ram-keep-gib": {"label": "RAM kept for tiers", "unit": "GiB"},
    "--remote-expert-opt": {"label": "Try the remote expert first"},
    "--report-drafts": {"label": "Report the drafts"},
    "--resident-cpu-experts": {"label": "Keep the CPU expert copy"},
    "--rope-freq-base": {"label": "RoPE base frequency"},
    "--rope-freq-scale": {"label": "RoPE frequency scale"},
    "--seed": {"label": "Seed"},
    "--session-min-free-mib": {"label": "Free memory a saved session leaves", "unit": "MiB"},
    "--shared-expert-arena": {"label": "Shared expert arena file"},
    "--shared-late": {"label": "Read the shared expert late"},
    "--slots": {"label": "Batch slots", "unit": "requests"},
    "--spec-follow": {"label": "Follow the draft chain"},
    "--split-skip-if-fits": {"label": "Skip the split when it fits"},
    "--ssd-experts": {"label": "Stream experts from the SSD"},
    "--stage-ahead": {"label": "Layers staged ahead"},
    "--stage-mib": {"label": "Bytes staged per layer", "unit": "MiB"},
    "--stage-read-mib": {"label": "Bytes read per stage", "unit": "MiB"},
    "--stage-timing": {"label": "Print stage timings"},
    "--stats": {"label": "Print statistics"},
    "--stream-token": {"label": "Stream marker token"},
    "--tail-role-token": {"label": "Assistant turn token"},
    "--temperature": {"label": "Temperature"},
    "--threads": {"label": "Helper threads", "unit": "threads"},
    "--tokens": {"label": "Prompt tokens"},
    "--tokens-file": {"label": "Prompt ids file"},
    "--top-k": {"label": "Top-k"},
    "--top-p": {"label": "Top-p"},
    "--tree": {"label": "Tree attention"},
    "--turn-token": {"label": "Turn end token"},
    "--vram-experts-gb": {"label": "Experts on the card", "unit": "GiB"},
    "--window": {"label": "Decode window", "unit": "tokens"},
    "--window-hashes": {"label": "Check window hashes"},
    "--yarn-attn-factor": {"label": "YaRN attention factor"},
    "--yarn-beta-fast": {"label": "YaRN fast beta"},
    "--yarn-beta-slow": {"label": "YaRN slow beta"},
    "--yarn-ext-factor": {"label": "YaRN extension factor"},
})

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

# A config key's plain-language name.  Before this, the page used the key's help sentence as its label, which
# is a paragraph in a name slot; the hint now lives under the field where AGENTS.md asks for it.
KEY_LABELS: dict[str, str] = {
    "display_name": "Shown as",
    "model_name": "Model name",
    "aliases": "Other names",
    "exe": "Engine executable",
    "args": "Engine settings",
    "env": "Environment",
    "gpu": "GPU",
    "gpus_asked": "GPUs asked for",
    "lib_dirs": "DLL folders",
    "cwd": "Working folder",
    "vision.exe": "Vision engine",
    "vision.mmproj": "Image encoder file",
    "vision.model": "Vision model",
    "vision.gpu": "Vision GPU",
    "vision.max_tokens": "Most image tokens",
    "vision.min_tokens": "Fewest image tokens",
    "vision.elastic": "Elastic image tokens",
    "sampling.temperature": "Temperature",
    "sampling.top_p": "Top-p",
    "sampling.top_k": "Top-k",
    "sampling.min_p": "Min-p",
    "sampling.presence_penalty": "Presence penalty",
    "sampling.frequency_penalty": "Frequency penalty",
    "sampling.repetition_penalty": "Repetition penalty",
    "sampling.penalty_last_n": "Penalty window",
    "sampling.seed": "Seed",
    "sampling.experimental_speed_projection": "Speed-projection vector",
    "reasoning_effort": "Thinking effort",
    "reasoning_budget_tokens": "Thinking budget",
    "reasoning_budget_by_effort": "Budget per effort level",
    "reasoning_loop_recovery": "Thinking loop",
    "reasoning_close_retry": "Retry a closed thought",
    "anthropic_thinking": "Thinking blocks (Anthropic API)",
    "effort_position": "Effort placement",
    "preserve_thinking": "Keep thinking in history",
    "fit_max_tokens": "Fit the budget to the window",
    "drop_oldest": "Drop the oldest turns",
    "truncate_middle": "Cut from the middle",
    "repeat_stop_tokens": "Repeat the stop tokens",
    "tool_call_recovery": "Recover a broken tool call",
    "warm_start": "Warm start",
    "codex_thread_titles": "Codex thread titles",
    "codex_compaction_cache": "Codex compaction cache",
    "idle_unload_s": "Unload when idle",
    "lazy_load": "Load on first use",
    "engine_silence_s": "Silence before a restart",
    "api_monitor": "Watch the API",
    "switch_on_request": "Switch on request",
    "open_browser": "Open the browser",
    "min_free_vram_mib": "VRAM kept free",
    "before_load": "Run before loading",
    "before_load_timeout_s": "Setup timeout",
    "before_load_ignore_failure": "Ignore a failed setup",
    "before_load_strict": "Fail when setup fails",
    "memory_debug": "Memory debugging",
    "context": "Context",
    "backend": "Backend",
    "arch": "Architecture",
    "port": "Port",
    "host": "Host",
    "tokenizer": "Tokenizer",
    "log": "Log file",
}

# The flag subgroups the Settings page renders the "args" flags in (order matters; a flag in no group
# lands in the trailing "Other flags" group).
FLAG_GROUPS: list[tuple[str, str, list[str]]] = [
    ("context", "Context & memory",
     ["--max-context", "--kv", "--kv-dtype", "--kv-grow", "--vram-reserve-mib", "--host-kv-mib",
      "--vram-elastic", "--vram-segment-mib", "--short-read", "--kv-resident", "--kv-whole",
      "--memory-limit-mib", "--session-min-free-mib", "--session-save-reclaim",
      "--conversation-cache-mib", "--conversation-cache-slots", "--conversation-cache-min-tokens",
      "--conversation-cache-min-free-mib"]),
    ("drafting", "Drafting",
     ["--spec", "--mtp", "--mtp-max-t", "--draft", "--draft-model", "--draft-tokens", "--draft-cap",
      "--draft-fallback", "--draft-conf", "--spec-min-p", "--spec-follow", "--suffix-draft",
      "--lookup-max-t", "--lookup-sizes", "--lookup-chain", "--dspark", "--lm-head-draft",
      "--report-drafts", "--mtp-q4", "--mtp-hnorm", "--draft-mtp-spec", "--draft-mtp-min-p",
      "--coupled-draft", "--no-coupled-draft", "--spec-width", "--draft-window", "--batch-mtp",
      "--no-draft", "--lookup"]),
    ("experts", "Experts & cache",
     ["--pack", "--native", "--ple-gguf", "--expert-profile", "--expert-profile-save", "--expert-cache",
      "--vram-experts-gb", "--ram-experts-gb", "--ssd-experts", "--vram-elastic", "--mmap-experts",
      "--resident-experts", "--adapt-every", "--adapt-swaps", "--adapt-decay", "--adapt-async",
      "--pool-workers", "--pool-affinity", "--cpu-threads", "--threads", "--pcie-frac", "--ram-keep-gib",
      "--dump-routing", "--native-router", "--ram-experts-mib", "--vram-pool", "--pool-cores",
      "--pool-tasks", "--host-core", "--aux-cpus", "--expert-swaps", "--adapt-min-gain",
      "--cpu-share", "--lock-experts", "--no-gpu-experts", "--no-pool", "--no-hit-poke",
      "--keep-canonical", "--trim-stage-weights", "--ple-io", "--ple-inflight", "--ple-row-cache",
      "--no-ple", "--no-ple-prefetch", "--expert-profile-save-every", "--remote-expert-opt",
      "--ple-delay-us", "--ple-sync-submit", "--no-host-worker", "--no-fused-gr",
      "--gr-fp32-activations", "--gr-native-mmvf", "--draft-rule", "--expert-cache-cpu-order",
      "--mtp-draft-vocab", "--shared-expert-arena"]),
    ("prefill", "Prefill & batching",
     ["--prefill", "--prefill-chunk", "--chunk", "--prefill-head-alias", "--batch", "--slots",
      "--parallel", "--max-concurrency", "--pipeline-windows", "--batch-groups", "--prefill-f16",
      "--prompt-batch", "--prefill-pipe", "--stage-ahead", "--stage-mib", "--stage-read-mib",
      "--prompt-cache", "--prompt-cache-every", "--prompt-cache-tail", "--prompt-cache-spread"]),
    ("quality", "Speed vs. quality",
     ["--tail-skip", "--skip-weight", "--cache-bias"]),
    ("sampling", "Sampling",
     ["--temperature", "--top-k", "--top-p", "--min-p", "--seed", "--max-new", "--tokens",
      "--greedy", "--draft-vocab"]),
    ("misc", "Graphs, vision & devices",
     ["--vision", "--no-cuda-graph", "--no-graphs", "--no-token-graph", "--window-hashes",
      "--split-skip-if-fits", "--layer-split", "--gpu", "--gpus", "--ep-split", "--shared-late",
      "--gpu-stages", "--kv-offload", "--no-capture", "--sync-every-layer", "--any-node",
      "--image-pad", "--rope-scale", "--rope-freq-base", "--rope-freq-scale", "--rope-scaling",
      "--yarn-attn-factor", "--yarn-orig-ctx", "--yarn-ext-factor", "--yarn-beta-fast",
      "--yarn-beta-slow", "--native-rope", "--native-gdn", "--native-qsa", "--native-qsa-indexer",
      "--native-moe-combine", "--native-ple-key", "--native-bf16", "--native-flash-attn-short",
      "--native-dense-gguf", "--native-head-gguf", "--embd-gguf", "--cvec-dir", "--cvec-mode",
      "--peer-device", "--peer-slots", "--peer-reserve-mib", "--peer-prefill-rows",
      "--peer-adapt-swaps", "--expert-cache-device1", "--expert-cache-device2",
      "--expert-cache-device3", "--expert-cache-per-layer", "--expert-cache-remote-placement",
      "--control-vector", "--control-vector-layer-range", "--control-vector-scaled",
      "--conversation-cache-park-gain", "--conversation-cache-rewind-keep",
      "--conversation-cache-swap-block-mib", "--resident-cpu-experts", "--native-bf16-extra",
      "--native-ple-postops", "--no-trim-stage-weights", "--window", "--tree", "--follow",
      "--lookup-chain-min", "--images", "--eos-ids", "--stream-token", "--turn-token",
      "--tail-role-token", "--tokens-file", "--stats", "--stage-timing"]),
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
    "--kv-resident": [0, 262144, 1024],
    "--memory-limit-mib": [1024, 131072, 1024],
    "--ram-experts-mib": [0, 65536, 512],
    "--vram-pool": [0, 16384, 256],
    "--pool-tasks": [1, 512, 1],
    "--host-core": [0, 31, 1],
    "--session-min-free-mib": [0, 16384, 256],
    "--conversation-cache-mib": [0, 16384, 256],
    "--conversation-cache-slots": [0, 64, 1],
    "--conversation-cache-min-tokens": [0, 65536, 256],
    "--conversation-cache-min-free-mib": [0, 16384, 256],
    "--batch-groups": [1, 16, 1],
    "--ple-inflight": [1, 4096, 1],
    "--ple-row-cache": [0, 67108864, 1048576],
    "--draft-mtp-spec": [1, 16, 1],
    "--draft-mtp-min-p": [0, 1, 0.01],
    "--expert-swaps": [1, 512, 4],
    "--adapt-min-gain": [0, 1, 0.01],
    "--cpu-share": [0, 1, 0.01],
    "--spec-width": [1, 32, 1],
    "--draft-window": [0, 32, 1],
    "--lookup": [0, 32, 1],
    "--image-pad": [0, 4096, 32],
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
                    "default": KEY_DEFAULTS.get(key), "label": KEY_LABELS.get(key)}
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
                       # the names an editor row has no catalog entry for, with what the file holds: a row
                       # for each one, so a variable this build does not know is still visible and editable.
                       "unknown_env": sorted(set(env) - set(ENGINE_ENV)),
                       "unknown_env_values": {n: str(env[n]) for n in sorted(set(env) - set(ENGINE_ENV))},
                       "presets": PRESETS.get(family, [])},
            "note": "Saved to the run config; used from the next start of, or switch to, the model."}
