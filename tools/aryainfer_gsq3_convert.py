"""Qwen3.8 27B: ISTA-DASLab's 3-bit GSQ checkpoint -> an aryainfer AQ3 GGUF.

The GGUF is the existing Qwen3.8-27B GSQ-RCO GGUF (metadata, tokenizer, norms, GDN parameters, MTP block, embeddings,
output head: all copied byte for byte) with every 3-bit linear of the text body replaced by the GSQ checkpoint's own
codes in AQ3 blocks.  ggml has no AQ3 type, so an AQ3 matrix is stored as GGML_TYPE_I8 of shape
[n_in / 256 * 100, n_out]; aryainfer (ARYAINFER_ENGINE) recognises that width and uploads it as AQ3.  strata-poly
does not read these files.

AQ3 block, 256 values (two GSQ groups of 128), 100 bytes, 3.125 bits a weight:
    half d[2]      the two groups' scales (GSQ's BF16 scale as FP16)
    u8   qs[64]    low two bits of value j at byte j % 64, bits 2 * (j / 64)
    u8   hm[32]    high bit of value j at byte j % 32, bit j / 32
    w[j] = d[j / 128] * ((lo | hi << 2) - 4)
Source: compressed-tensors pack-quantized, a little-endian 3-bit stream per row, codes stored as q + 4.

    python tools/aryainfer_gsq3_convert.py --src DIR --gguf IN.gguf --check      # correlation of layer 0 and 3
    python tools/aryainfer_gsq3_convert.py --src DIR --gguf IN.gguf --out OUT.gguf
"""
from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "third_party" / "llama.cpp" / "gguf-py"))

MAP = {
    "linear_attn.in_proj_qkv": "attn_qkv", "linear_attn.in_proj_z": "attn_gate", "linear_attn.out_proj": "ssm_out",
    "self_attn.q_proj": "attn_q", "self_attn.k_proj": "attn_k", "self_attn.v_proj": "attn_v",
    "self_attn.o_proj": "attn_output",
    "mlp.gate_proj": "ffn_gate", "mlp.up_proj": "ffn_up", "mlp.down_proj": "ffn_down",
}
I8 = 24
BLOCK_BYTES = 100


class Src:
    def __init__(self, d: pathlib.Path):
        self.d = d
        self.map = json.loads((d / "model.safetensors.index.json").read_text())["weight_map"]
        self.heads = {}

    def get(self, name: str) -> np.ndarray:
        fn = self.map[name]
        if fn not in self.heads:
            with open(self.d / fn, "rb") as f:
                n = struct.unpack("<Q", f.read(8))[0]
                self.heads[fn] = (8 + n, json.loads(f.read(n)))
        base, h = self.heads[fn]
        e = h[name]
        a, b = e["data_offsets"]
        dt = {"I32": np.int32, "BF16": np.uint16, "I64": np.int64}[e["dtype"]]
        return np.fromfile(self.d / fn, dtype=dt, count=(b - a) // np.dtype(dt).itemsize, offset=base + a).reshape(
            e["shape"])

    def codes(self, prefix: str):
        """(u [out, in] uint8 0..7, scales [out, in/128] float32)."""
        out, inn = (int(v) for v in self.get(prefix + ".weight_shape"))
        pk = self.get(prefix + ".weight_packed").view(np.uint8).reshape(out, -1)
        bits = np.unpackbits(pk, axis=1, bitorder="little")[:, : inn * 3].reshape(out, inn, 3)
        u = (bits[..., 0] | bits[..., 1] << 1 | bits[..., 2] << 2).astype(np.uint8)
        s = (self.get(prefix + ".weight_scale").astype(np.uint32) << 16).view(np.float32).reshape(out, inn // 128)
        # llama.cpp's GGUF holds the GDN value heads tiled ([v_per_k, k, dim]), HF grouped ([k, v_per_k, dim])
        # (conversion/qwen.py _reorder_v_heads); a head is 128 wide, one scale group
        heads = np.arange(48).reshape(16, 3).T.reshape(-1)
        rows = (heads[:, None] * 128 + np.arange(128)).reshape(-1)
        if prefix.endswith("in_proj_qkv"):
            u[4096:], s[4096:] = u[4096:][rows], s[4096:][rows]
        elif prefix.endswith("in_proj_z"):
            u, s = u[rows], s[rows]
        elif prefix.endswith("out_proj"):
            u = u.reshape(out, 48, 128)[:, heads].reshape(out, inn)
            s = s[:, heads]
        return u, s


def pack_aq3(u: np.ndarray, s: np.ndarray) -> np.ndarray:
    out, inn = u.shape
    assert inn % 256 == 0, inn
    nb = inn // 256
    b = u.reshape(out, nb, 256)
    lo, hi = b & 3, b >> 2
    qs = np.zeros((out, nb, 64), np.uint8)
    for k in range(4):
        qs |= lo[:, :, 64 * k: 64 * k + 64] << (2 * k)
    hm = np.zeros((out, nb, 32), np.uint8)
    for m in range(8):
        hm |= hi[:, :, 32 * m: 32 * m + 32] << m
    d = np.ascontiguousarray(s.astype(np.float16)).reshape(out, nb, 2).view(np.uint8)
    return np.concatenate([d, qs, hm], axis=2).reshape(out, nb * BLOCK_BYTES)


def unpack_aq3(raw: np.ndarray, inn: int) -> np.ndarray:
    out = raw.shape[0]
    nb = inn // 256
    b = raw.reshape(out, nb, BLOCK_BYTES)
    d = b[:, :, :4].copy().view(np.float16).astype(np.float32)
    qs, hm = b[:, :, 4:68], b[:, :, 68:100]
    j = np.arange(256)
    lo = (qs[:, :, j % 64] >> (2 * (j // 64))) & 3
    hi = (hm[:, :, j % 32] >> (j // 32)) & 1
    v = (lo | hi << 2).astype(np.float32) - 4
    return (v * np.repeat(d, 128, axis=2)).reshape(out, inn)


def targets(reader):
    for t in reader.tensors:
        parts = t.name.split(".")
        if parts[0] == "blk" and int(parts[1]) < 64 and parts[-1] == "weight":
            for hf, gg in MAP.items():
                if parts[2] == gg:
                    yield t, f"model.language_model.layers.{parts[1]}.{hf}"


def check(src: Src, reader) -> bool:
    from gguf.quants import dequantize
    ok = True
    for t, hf in targets(reader):
        if t.name.split(".")[1] not in ("0", "3"):
            continue
        u, s = src.codes(hf)
        w = unpack_aq3(pack_aq3(u, s), u.shape[1])
        ref = (u.astype(np.float32) - 4) * np.repeat(s, 128, axis=1)
        exact = float(np.abs(w - ref).max() / np.abs(ref).max())
        g = dequantize(t.data, t.tensor_type).reshape(u.shape)
        rows = np.linspace(0, u.shape[0] - 1, 6).astype(int)
        c = float(np.mean([np.corrcoef(w[i], g[i])[0, 1] for i in rows]))
        print(f"{t.name:28s} {t.tensor_type.name:8s} {str(u.shape):16s} corr {c:.3f}  roundtrip {exact:.1e}")
        ok = ok and c > 0.6 and exact < 1e-2
    return ok


def skip_kv(f) -> None:
    def val(tp):
        if tp in (0, 1, 7): f.read(1)
        elif tp in (2, 3): f.read(2)
        elif tp in (4, 5, 6): f.read(4)
        elif tp in (10, 11, 12): f.read(8)
        elif tp == 8: f.read(struct.unpack("<Q", f.read(8))[0])
        elif tp == 9:
            et, n = struct.unpack("<IQ", f.read(12))
            for _ in range(n): val(et)
        else: raise ValueError(tp)
    f.read(struct.unpack("<Q", f.read(8))[0])
    val(struct.unpack("<I", f.read(4))[0])


def convert(src: Src, reader, gguf_in: pathlib.Path, out: pathlib.Path) -> None:
    with open(gguf_in, "rb") as f:
        magic, ver, n_t, n_kv = struct.unpack("<IIQQ", f.read(24))
        for _ in range(n_kv): skip_kv(f)
        kv_end = f.tell()
        f.seek(24)
        kv = f.read(kv_end - 24)
    repl = dict((t.name, hf) for t, hf in targets(reader))
    align = 32
    pad = lambda n: (-n) % align
    infos, sizes = [], []
    for t in reader.tensors:
        if t.name in repl:
            out_n, inn = int(t.shape[1]), int(t.shape[0])
            shape, tp, size = [inn // 256 * BLOCK_BYTES, out_n], I8, inn // 256 * BLOCK_BYTES * out_n
        else:
            shape, tp, size = [int(v) for v in t.shape], int(t.tensor_type), int(t.n_bytes)
        infos.append((t.name, shape, tp))
        sizes.append(size)
    head = bytearray(struct.pack("<IIQQ", magic, ver, len(infos), n_kv) + kv)
    at = 0
    for (name, shape, tp), size in zip(infos, sizes):
        nb = name.encode()
        head += struct.pack("<Q", len(nb)) + nb + struct.pack("<I", len(shape))
        head += struct.pack(f"<{len(shape)}Q", *shape) + struct.pack("<IQ", tp, at)
        at += size + pad(size)
    head += b"\0" * pad(len(head))
    tmp = out.with_suffix(".part")
    with open(tmp, "wb") as o:
        o.write(head)
        for i, (t, size) in enumerate(zip(reader.tensors, sizes)):
            if t.name in repl:
                data = pack_aq3(*src.codes(repl[t.name])).tobytes()
            else:
                data = t.data.tobytes()
            assert len(data) == size, (t.name, len(data), size)
            o.write(data)
            o.write(b"\0" * pad(size))
            if i % 50 == 0:
                print(f"{i}/{len(sizes)} {t.name}", flush=True)
    tmp.replace(out)
    print("wrote", out, out.stat().st_size)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, type=pathlib.Path)
    ap.add_argument("--gguf", required=True, type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    from gguf import GGUFReader
    reader = GGUFReader(a.gguf)
    src = Src(a.src)
    if a.check:
        return 0 if check(src, reader) else 1
    if not a.out:
        ap.error("--out or --check")
    convert(src, reader, a.gguf, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
