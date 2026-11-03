// src/poly/prefill_f16.cu - see the header.  The 3-bit blocks are llama.cpp's (third_party/llama.cpp, MIT): the layout
// and the two tables come with ggml-common.h, so this file keeps no second copy of them.
//
// The product: a block of 32 weight rows by 128 tokens, in a k loop of 128 values.  The weight tile is dequantized
// straight into shared memory (the only place halves live), the token tile is cast from floats as it is loaded, and
// eight warps multiply them with fp16 wmma and fp32 accumulators.  Reading the weights as 3-bit blocks once per tile,
// never as halves in memory, is what makes the tensor cores pay: the fp16 round trip through global memory lost.
#include "strata/poly/prefill_f16.hpp"

#if !defined(STRATA_USE_HIP) && !defined(GGML_USE_HIP)

#include "ggml.h"
#include "common.cuh"

#include <cuda_fp16.h>
#include <mma.h>

namespace strata::poly {
namespace {

constexpr int BM = 32, BN = 128, BK = 128;   // weight rows, tokens, k values a step
constexpr size_t kAq3Block = 100;            // AQ3: bytes per 256 values
constexpr int THREADS = 256;                 // eight warps: 2 x 4, each 16 rows by 32 tokens
constexpr size_t kSmem = (size_t) (BM * BK + BN * BK) * sizeof(__half) + (size_t) BM * BN * sizeof(float);

// Eight consecutive values of an IQ3_XXS block: (ib, il) is one thread's 8-value chunk, the first four from grid1,
// the last four from grid2, the sign bits from the block's key.  One thread writes eight halves.
__device__ __forceinline__ void iq3_xxs_8(const block_iq3_xxs& x, int ib, int il, __half* out) {
    const uint8_t* q3 = x.qs + 8 * ib;
    const uint16_t* gas = (const uint16_t*) (x.qs + QK_K / 4) + 2 * ib;
    const uint32_t aux = (uint32_t) gas[0] | ((uint32_t) gas[1] << 16);
    const float d = (float) x.d * (0.5f + (float) (aux >> 28)) * 0.5f;
    const uint8_t* g1 = (const uint8_t*) &iq3xxs_grid[q3[2 * il]];
    const uint8_t* g2 = (const uint8_t*) &iq3xxs_grid[q3[2 * il + 1]];
    const uint8_t signs = ksigns_iq2xs[(aux >> (7 * il)) & 127];
    float v[8];
#pragma unroll
    for (int j = 0; j < 4; ++j) {
        const float s1 = (signs & kmask_iq2xs[j]) ? -1.f : 1.f;
        const float s2 = (signs & kmask_iq2xs[j + 4]) ? -1.f : 1.f;
        v[j] = d * (float) g1[j] * s1;
        v[j + 4] = d * (float) g2[j] * s2;
    }
#pragma unroll
    for (int j = 0; j < 8; ++j) out[j] = __float2half(v[j]);
}

// Eight consecutive values of an AQ3 block (tools/aryainfer_gsq3_convert.py): 256 values in 100 bytes, two fp16 group
// scales, the low two bits at byte j % 64 (bits 2 * (j / 64)), the high bit at byte j % 32 (bit j / 32), value - 4.
__device__ __forceinline__ void aq3_8(const uint8_t* blk, int off, __half* out) {
    const float d = __half2float(((const __half*) blk)[off >> 7]);
    const uint8_t* qs = blk + 4 + (off & 63);
    const uint8_t* hm = blk + 68 + (off & 31);
    const int sl = 2 * (off >> 6), sh = off >> 5;
#pragma unroll
    for (int j = 0; j < 8; ++j)
        out[j] = __float2half(d * (float) ((int) (((qs[j] >> sl) & 3) | (((hm[j] >> sh) & 1) << 2)) - 4));
}

template <bool AQ3>
__global__ void fused_iq3_gemm(const uint8_t* __restrict__ w, size_t row_bytes, const __half* __restrict__ x,
                               float* __restrict__ y, int n_in, int n_out, int rows) {
    extern __shared__ char smem[];
    __half* a_s = (__half*) smem;              // BM x BK
    __half* b_s = a_s + BM * BK;               // BN x BK
    float* c_s = (float*) (b_s + BN * BK);     // BM x BN
    const int m0 = blockIdx.y * BM, n0 = blockIdx.x * BN;
    const int tid = threadIdx.x, warp = tid >> 5;
    const int wm = warp >> 2, wn = warp & 3;   // 2 x 4 warps, each 16 rows by 32 tokens
    nvcuda::wmma::fragment<nvcuda::wmma::matrix_a, 16, 16, 16, half, nvcuda::wmma::row_major> fa;
    nvcuda::wmma::fragment<nvcuda::wmma::matrix_b, 16, 16, 16, half, nvcuda::wmma::col_major> fb;
    nvcuda::wmma::fragment<nvcuda::wmma::accumulator, 16, 16, 16, float> fc0, fc1;
    nvcuda::wmma::fill_fragment(fc0, 0.0f);
    nvcuda::wmma::fill_fragment(fc1, 0.0f);
    for (int k0 = 0; k0 < n_in; k0 += BK) {
        // a weight tile: a thread one 8-value chunk of a row, straight from the block's layout.  The chunk's place in
        // its 256-value block is the k offset within the block plus the chunk's 8 values, never the k index twice.
        for (int c = tid; c < BM * (BK / 8); c += THREADS) {
            const int m = c / (BK / 8), t = c % (BK / 8);
            const int col = m0 + m, k = k0 + 8 * t;
            if (col >= n_out || k + 7 >= n_in) {
                __half* out = a_s + m * BK + 8 * t;
#pragma unroll
                for (int j = 0; j < 8; ++j) out[j] = __float2half(0.0f);
                continue;
            }
            const uint8_t* row = w + (size_t) col * row_bytes;
            const int off = (int) (k0 & 255) + 8 * t;   // first 128 values of the block, then its second
            if constexpr (AQ3) {
                aq3_8(row + (size_t) (k >> 8) * kAq3Block, off, a_s + m * BK + 8 * t);
            } else {
                const uint8_t* blk = row + (size_t) (k >> 8) * sizeof(block_iq3_xxs);
                iq3_xxs_8(*(const block_iq3_xxs*) blk, off >> 5, (off & 31) >> 3, a_s + m * BK + 8 * t);
            }
        }
        // the token tile: halves already, sixteen bytes a thread
        for (int i = tid * 8; i < BN * BK; i += THREADS * 8) {
            const int t = i / BK, kk = i - t * BK;
            const int tok = n0 + t, k = k0 + kk;
            __half* out = b_s + t * BK + kk;
            if (tok >= rows || k + 7 >= n_in) {
                for (int j = 0; j < 8; ++j) out[j] = __float2half(0.0f);
                continue;
            }
            *reinterpret_cast<float4*>(out) = *reinterpret_cast<const float4*>(x + (size_t) tok * n_in + k);
        }
        __syncthreads();
        for (int kk = 0; kk < BK; kk += 16) {
            nvcuda::wmma::load_matrix_sync(fa, a_s + (wm * 16) * BK + kk, BK);
            nvcuda::wmma::load_matrix_sync(fb, b_s + (wn * 32) * BK + kk, BK);
            nvcuda::wmma::mma_sync(fc0, fa, fb, fc0);
            nvcuda::wmma::load_matrix_sync(fb, b_s + (wn * 32 + 16) * BK + kk, BK);
            nvcuda::wmma::mma_sync(fc1, fa, fb, fc1);
        }
        __syncthreads();
    }
    nvcuda::wmma::store_matrix_sync(c_s + (wm * 16) * BN + wn * 32, fc0, BN, nvcuda::wmma::mem_row_major);
    nvcuda::wmma::store_matrix_sync(c_s + (wm * 16) * BN + wn * 32 + 16, fc1, BN, nvcuda::wmma::mem_row_major);
    __syncthreads();
    for (int i = tid; i < BM * BN; i += THREADS) {
        const int m = i / BN, t = i - m * BN;
        const int col = m0 + m, tok = n0 + t;
        if (col < n_out && tok < rows) y[(size_t) tok * n_out + col] = c_s[m * BN + t];
    }
}

struct Q81 {
    half2 ds;   // the block's scale and its scale times the sum of its values
    int8_t qs[32];
};

// y = w x for NC tokens of q8_1 activations: a warp a row, a lane a 32-value piece of it at a time, each piece's
// weights unpacked once to int8 and multiplied with every token's piece by dp4a.
template <int NC>
__global__ void aq3_gemv_kernel(const uint8_t* __restrict__ w, const Q81* __restrict__ x, float* __restrict__ y,
                                int n_in, int n_out) {
    const int row = blockIdx.x * 4 + threadIdx.y;
    if (row >= n_out) return;
    const int nb = n_in >> 8, pieces = nb * 8, per_tok = n_in >> 5;
    const uint8_t* wr = w + (size_t) row * nb * kAq3Block;
    float acc[NC];
#pragma unroll
    for (int c = 0; c < NC; ++c) acc[c] = 0.f;
    for (int s = threadIdx.x; s < pieces; s += 32) {
        const int c = s & 7;
        const uint8_t* blk = wr + (size_t) (s >> 3) * kAq3Block;
        const float d = __half2float(((const __half*) blk)[c >> 2]);
        const uint32_t* qs = (const uint32_t*) (blk + 4 + 32 * (c & 1));
        const uint32_t* hm = (const uint32_t*) (blk + 68);
        const int sl = 2 * (c >> 1);
        int v[8];
#pragma unroll
        for (int i = 0; i < 8; ++i)
            v[i] = (int) (((qs[i] >> sl) & 0x03030303u) | (((hm[i] >> c) & 0x01010101u) << 2));
#pragma unroll
        for (int t = 0; t < NC; ++t) {
            const Q81& q = x[(size_t) t * per_tok + s];
            const int* xq = (const int*) q.qs;
            int sumi = 0;
#pragma unroll
            for (int i = 0; i < 8; ++i) sumi = __dp4a(v[i], xq[i], sumi);
            const float2 ds = __half22float2(q.ds);
            acc[t] += d * (ds.x * (float) sumi - 4.f * ds.y);
        }
    }
#pragma unroll
    for (int t = 0; t < NC; ++t) {
        float a = acc[t];
#pragma unroll
        for (int o = 16; o > 0; o >>= 1) a += __shfl_xor_sync(0xffffffffu, a, o);
        if (threadIdx.x == 0) y[(size_t) t * n_out + row] = a;
    }
}

// A 32-value piece of AQ3 to a Q8_0 block (half d; int8 qs[32]): the group's scale and the values as they are.
//
// One block expands 256 pieces (8,704 bytes of Q8_0, a multiple of 16), computes them into shared memory, then copies
// that range out as whole 32-bit words.  The direct version stored each thread's 34-byte block at a 34-byte stride, so
// every 4-byte store instruction across a warp touched 32 different 32-byte sectors; the copy here is contiguous, and
// the expansion drops from about 60 GB/s to the card's write bandwidth.  The output range starts at blockIdx * 8,704,
// so it is 16-byte aligned, and the last block copies its rem.
constexpr int kAq3Expand = 256;
__global__ void aq3_q8_0_kernel(const uint8_t* __restrict__ w, uint8_t* __restrict__ q8, int n_in, size_t pieces) {
    __shared__ __align__(16) uint8_t sm[kAq3Expand * 34];
    const size_t base = (size_t) blockIdx.x * kAq3Expand;
    const size_t p = base + threadIdx.x;
    if (p < pieces) {
        const size_t per_row = (size_t) (n_in / 32);
        const size_t row = p / per_row, s = p - row * per_row;
        const int c = (int) (s & 7);
        const uint8_t* blk = w + row * (size_t) (n_in / 256) * kAq3Block + (s >> 3) * kAq3Block;
        const uint32_t* qs = (const uint32_t*) (blk + 4 + 32 * (c & 1));
        const uint32_t* hm = (const uint32_t*) (blk + 68);
        const int sl = 2 * (c >> 1);
        uint8_t* out = sm + (size_t) threadIdx.x * 34;
        ((__half*) out)[0] = ((const __half*) blk)[c >> 2];
        uint16_t* o16 = (uint16_t*) (out + 2);   // 34-byte blocks: two-byte aligned
#pragma unroll
        for (int i = 0; i < 8; ++i) {
            const uint32_t v = __vsub4(((qs[i] >> sl) & 0x03030303u) | (((hm[i] >> c) & 0x01010101u) << 2), 0x04040404u);
            o16[2 * i] = (uint16_t) v;
            o16[2 * i + 1] = (uint16_t) (v >> 16);
        }
    }
    __syncthreads();
    const size_t n = pieces - base < (size_t) kAq3Expand ? pieces - base : (size_t) kAq3Expand;
    const size_t bytes = n * 34, words = bytes / 4;
    uint8_t* dst = q8 + base * 34;
    const uint32_t* src32 = (const uint32_t*) sm;
    uint32_t* dst32 = (uint32_t*) dst;
    for (size_t i = threadIdx.x; i < words; i += (size_t) blockDim.x) dst32[i] = src32[i];
    if (threadIdx.x < bytes - words * 4) dst[words * 4 + threadIdx.x] = sm[words * 4 + threadIdx.x];
}

__global__ void cast_f16_kernel(const float* __restrict__ x, __half* __restrict__ y, size_t n) {
    const size_t i = (size_t) blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) y[i] = __float2half(x[i]);
}

}  // namespace

bool f16_type(int ggml_type) { return ggml_type == (int) GGML_TYPE_IQ3_XXS || ggml_type == (int) kTypeAQ3; }

void cast_f16(const float* x, uint16_t* out, size_t n, void* stream) {
    if (n == 0) return;
    cast_f16_kernel<<<(unsigned) ((n + 255) / 256), 256, 0, (cudaStream_t) stream>>>(x, (__half*) out, n);
}

bool fused_gemm_f16(const void* w, size_t row_bytes, int ggml_type, const uint16_t* x, float* y, int n_in, int n_out,
                    int rows, void* stream) {
    if (!f16_type(ggml_type) || n_in <= 0 || n_out <= 0 || rows <= 0) return false;
    static bool attrs = false;
    if (!attrs) {
        cudaFuncSetAttribute(fused_iq3_gemm<false>, cudaFuncAttributeMaxDynamicSharedMemorySize, (int) kSmem);
        cudaFuncSetAttribute(fused_iq3_gemm<true>, cudaFuncAttributeMaxDynamicSharedMemorySize, (int) kSmem);
        attrs = true;
    }
    const dim3 grid((rows + BN - 1) / BN, (n_out + BM - 1) / BM);
    if (ggml_type == (int) kTypeAQ3)
        fused_iq3_gemm<true><<<grid, THREADS, kSmem, (cudaStream_t) stream>>>((const uint8_t*) w, row_bytes,
                                                                             (const __half*) x, y, n_in, n_out, rows);
    else
        fused_iq3_gemm<false><<<grid, THREADS, kSmem, (cudaStream_t) stream>>>((const uint8_t*) w, row_bytes,
                                                                              (const __half*) x, y, n_in, n_out, rows);
    return true;
}

size_t aq3_row_bytes(int n_in) { return (size_t) (n_in / 256) * kAq3Block; }

void aq3_to_q8_0(const void* w, void* q8, int n_in, int n_out, void* stream) {
    const size_t pieces = (size_t) n_out * (size_t) (n_in / 32);
    aq3_q8_0_kernel<<<(unsigned) ((pieces + 255) / 256), 256, 0, (cudaStream_t) stream>>>((const uint8_t*) w,
                                                                                          (uint8_t*) q8, n_in, pieces);
}

void aq3_gemv(const void* w, const void* xq, float* y, int n_in, int n_out, int ncols, void* stream) {
    const dim3 block(32, 4), grid((unsigned) ((n_out + 3) / 4));
    const auto* wp = (const uint8_t*) w;
    const auto* xp = (const Q81*) xq;
    cudaStream_t st = (cudaStream_t) stream;
    switch (ncols) {
    case 1: aq3_gemv_kernel<1><<<grid, block, 0, st>>>(wp, xp, y, n_in, n_out); break;
    case 2: aq3_gemv_kernel<2><<<grid, block, 0, st>>>(wp, xp, y, n_in, n_out); break;
    case 3: aq3_gemv_kernel<3><<<grid, block, 0, st>>>(wp, xp, y, n_in, n_out); break;
    case 4: aq3_gemv_kernel<4><<<grid, block, 0, st>>>(wp, xp, y, n_in, n_out); break;
    case 5: aq3_gemv_kernel<5><<<grid, block, 0, st>>>(wp, xp, y, n_in, n_out); break;
    case 6: aq3_gemv_kernel<6><<<grid, block, 0, st>>>(wp, xp, y, n_in, n_out); break;
    case 7: aq3_gemv_kernel<7><<<grid, block, 0, st>>>(wp, xp, y, n_in, n_out); break;
    default: aq3_gemv_kernel<8><<<grid, block, 0, st>>>(wp, xp, y, n_in, n_out); break;
    }
}

}  // namespace strata::poly

#else   // HIP: the fused product is CUDA's (wmma); the engine keeps the MMQ path

namespace strata::poly {
bool f16_type(int) { return false; }
void cast_f16(const float*, uint16_t*, size_t, void*) {}
bool fused_gemm_f16(const void*, size_t, int, const uint16_t*, float*, int, int, int, void*) { return false; }
size_t aq3_row_bytes(int n_in) { return (size_t) (n_in / 256) * 100; }
void aq3_to_q8_0(const void*, void*, int, int, void*) {}
void aq3_gemv(const void*, const void*, float*, int, int, int, void*) {}
}  // namespace strata::poly

#endif
