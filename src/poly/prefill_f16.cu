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
            const uint8_t* blk = row + (size_t) (k >> 8) * sizeof(block_iq3_xxs);
            const int off = (int) (k0 & 255) + 8 * t;   // first 128 values of the block, then its second
            iq3_xxs_8(*(const block_iq3_xxs*) blk, off >> 5, (off & 31) >> 3, a_s + m * BK + 8 * t);
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

__global__ void cast_f16_kernel(const float* __restrict__ x, __half* __restrict__ y, size_t n) {
    const size_t i = (size_t) blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) y[i] = __float2half(x[i]);
}

}  // namespace

bool f16_type(int ggml_type) { return ggml_type == (int) GGML_TYPE_IQ3_XXS; }

void cast_f16(const float* x, uint16_t* out, size_t n, void* stream) {
    if (n == 0) return;
    cast_f16_kernel<<<(unsigned) ((n + 255) / 256), 256, 0, (cudaStream_t) stream>>>(x, (__half*) out, n);
}

bool fused_gemm_f16(const void* w, size_t row_bytes, int ggml_type, const uint16_t* x, float* y, int n_in, int n_out,
                    int rows, void* stream) {
    if (ggml_type != (int) GGML_TYPE_IQ3_XXS || n_in <= 0 || n_out <= 0 || rows <= 0) return false;
    static bool attrs = false;
    if (!attrs) {
        cudaFuncSetAttribute(fused_iq3_gemm, cudaFuncAttributeMaxDynamicSharedMemorySize, (int) kSmem);
        attrs = true;
    }
    const dim3 grid((rows + BN - 1) / BN, (n_out + BM - 1) / BM);
    fused_iq3_gemm<<<grid, THREADS, kSmem, (cudaStream_t) stream>>>((const uint8_t*) w, row_bytes, (const __half*) x, y,
                                                                   n_in, n_out, rows);
    return true;
}

}  // namespace strata::poly

#else   // HIP: the fused product is CUDA's (wmma); the engine keeps the MMQ path

namespace strata::poly {
bool f16_type(int) { return false; }
void cast_f16(const float*, uint16_t*, size_t, void*) {}
bool fused_gemm_f16(const void*, size_t, int, const uint16_t*, float*, int, int, int, void*) { return false; }
}  // namespace strata::poly

#endif
