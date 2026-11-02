"""Gate 1 for Qwen3.8 27B (architecture "qwen35"): header facts the plan's gate needs.

Run on a header-only fetch (the first ~128 MiB of a GGUF): the reader parses metadata and
tensor infos only, never tensor data, so a truncated header file is enough for every row
this script prints.

    python tools/qwen38_gate1_dump.py C:\\AI\\Strata-data\\models\\qwen38-27b\\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf.header

Prints: the metadata keys a strata-poly dense load reads, the per-tensor type map, the
tensor names a dense Qwen35 load_layer looks for, the draft block (nextn.*) and its FFN,
the rope sections, and the KV/MLP geometry against the plan's expected numbers.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gguf_reader import GGUFFile  # noqa: E402

EXPECTED_GEOM = {
    "qwen35.block_count": 64,
    "qwen35.nextn_predict_layers": 1,
    "qwen35.embedding_length": 5120,
    "qwen35.feed_forward_length": 17408,
    "qwen35.vocab_size": 248320,
    "qwen35.attention.head_count": 24,
    "qwen35.attention.head_count_kv": 4,
    "qwen35.attention.key_length": 256,
    "qwen35.attention.value_length": 256,
    "qwen35.ssm.state_size": 128,
    "qwen35.ssm.group_count": 16,
    "qwen35.ssm.time_step_rank": 48,
    "qwen35.ssm.inner_size": 6144,
    "qwen35.ssm.conv_kernel": 4,
}

# the keys Qwen35::load_layer and Engine::load_shape read (src/poly/qwen35.cpp:110,
# src/poly/engine.cpp:950); a dense file has no ffn_gate_inp / *_exps / shexp keys
LAYER_KEYS = [
    "attn_norm.weight", "post_attention_norm.weight",
    "attn_qkv.weight", "attn_gate.weight", "ssm_conv1d.weight", "ssm_dt.bias", "ssm_a",
    "ssm_alpha.weight", "ssm_beta.weight", "ssm_norm.weight", "ssm_out.weight",
    "attn_q.weight", "attn_k.weight", "attn_v.weight", "attn_q_norm.weight", "attn_k_norm.weight",
    "attn_output.weight",
    "ffn_gate.weight", "ffn_up.weight", "ffn_down.weight",
]
MOE_KEYS = ["ffn_gate_inp.weight", "ffn_gate_exps.weight", "ffn_up_exps.weight", "ffn_down_exps.weight",
            "ffn_gate_inp_shexp.weight", "ffn_exp_bdy2eid.weight"]
DRAFT_KEYS = ["nextn.eh_proj.weight", "nextn.enorm.weight", "nextn.hnorm.weight",
              "nextn.shared_head_norm.weight", "nextn.embed_tokens.weight", "nextn.shared_head_head.weight"]


def main(argv: list[str]) -> int:
    for arg in argv:
        g = GGUFFile(pathlib.Path(arg))
        md = g.metadata
        arch = str(md.get("general.architecture", ""))
        pre = arch + "."
        print("=" * 78)
        print(arg)
        print(f"architecture = {arch!r}   tensors = {len(g.tensors)}   alignment = {g.alignment}"
              f"   data_start = {g.data_start}")
        print("-- geometry keys (expected = the plan's numbers) --")
        for key, want in EXPECTED_GEOM.items():
            got = md.get(key)
            print(f"  {key:42s} = {got}  {'OK' if got == want else f'EXPECTED {want}'}")
        for key in ("qwen35.rope.dimension_count", "qwen35.rope.dimension_sections", "qwen35.rope.freq_base",
                    "qwen35.attention.layer_norm_rms_epsilon", "qwen35.rope.scaling.type",
                    "qwen35.rope.scaling.factor", "qwen35.expert_count", "qwen35.expert_used_count",
                    "qwen35.expert_feed_forward_length"):
            print(f"  {key:42s} = {md.get(key)}")
        print("  tokenizer keys:", {k.split('.')[-1]: md.get(k) for k in md
                                    if k.startswith("tokenizer.ggml.") and k.split('.')[-1]
                                    in ("model", "eos_token", "bos_token", "mask_token", "padding_token")})
        print("-- per-tensor type map --")
        for t, n in g.by_type().items():
            print(f"  {t:10s} {n}")
        print("-- layer keys present (layer 3 = a GDN layer, layer 7 = attention, per the doc) --")
        for il in (0, 3, 7, 63):
            have = [k for k in LAYER_KEYS if any(t.name == f"{arch}.blk.{il}.{k}" for t in g.tensors)]
            print(f"  blk.{il}: " + ", ".join(have))
        print("-- MoE keys (a dense file has none) --")
        moe_hits = {k: sum(1 for t in g.tensors if f".{k}" in t.name) for k in MOE_KEYS}
        print("  " + ", ".join(f"{k}={v}" for k, v in moe_hits.items()))
        print("-- draft block (nextn.*) --")
        for k in DRAFT_KEYS:
            t = next((t for t in g.tensors if t.name.endswith("." + k)), None)
            if t:
                print(f"  {k:34s} {t.type_name:8s} {t.shape}")
        nff = next((t for t in g.tensors if t.name.endswith("nextn.ffn_gate.weight")), None)
        print(f"  draft FFN: {[t.name.split('.')[-1] for t in g.tensors if 'nextn.ffn' in t.name]}")
        print("-- tensor shapes the dense load checks (blk.7 attention + FFN of a GDN layer) --")
        for want in ("blk.7.attn_q.weight", "blk.7.attn_k.weight", "blk.7.attn_v.weight",
                     "blk.7.attn_output.weight", "blk.7.ffn_gate.weight", "blk.7.ffn_up.weight",
                     "blk.7.ffn_down.weight", "blk.3.attn_qkv.weight", "blk.3.attn_gate.weight",
                     "blk.3.ssm_out.weight", "blk.3.ssm_alpha.weight", "token_embd.weight",
                     "output.weight", "token_embd_norm.weight"):
            t = next((t for t in g.tensors if t.name.endswith(want)), None)
            print(f"  {want:32s} " + (f"{t.type_name:8s} {t.shape}" if t else "ABSENT"))
        vision = [t.name for t in g.tensors if t.name.startswith("vision")]
        print(f"-- vision tensors in this file: {len(vision)} --")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
