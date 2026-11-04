// src/poly/aq3_i8_bench.cu - the AQ3 int8 tensor-core product alone, in TFLOPS, on matrices the model has.
//
// The whole prefill (matmul + attention + GDN) of the Q8_0 expansion path measures about 77 TFLOPS at 8K on this card;
// the int8 product has to beat that to be worth integrating.  This prints the kernel's own rate, with the activations
// built on the CPU, for the shapes a layer has.
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <vector>

#include <cuda_fp16.h>
#include <cuda_runtime.h>

#include "strata/poly/prefill_f16.hpp"

using namespace strata::poly;

static void ck(cudaError_t e, const char* what) {
    if (e != cudaSuccess) {
        std::printf("CUDA %s: %s\n", what, cudaGetErrorString(e));
        std::exit(1);
    }
}

static void put_half(std::vector<uint8_t>& b, size_t at, float v) {
    const __half h = __float2half(v);
    std::memcpy(b.data() + at, &h, 2);
}

static std::vector<uint8_t> make_aq3(int n_out, int n_in, unsigned seed) {
    const size_t rb = aq3_row_bytes(n_in);
    std::vector<uint8_t> w((size_t) n_out * rb, 0);
    std::mt19937 rng(seed);
    for (int r = 0; r < n_out; ++r) {
        uint8_t* row = w.data() + (size_t) r * rb;
        for (int k = 0; k < n_in; ++k) {
            const int b = k / 256, off = k % 256;
            uint8_t* blk = row + (size_t) b * 100;
            const int code = (int) (rng() & 7u);
            blk[4 + (off & 63)] |= (uint8_t) ((code & 3) << (2 * (off >> 6)));
            blk[68 + (off & 31)] |= (uint8_t) (((code >> 2) & 1) << (off >> 5));
        }
        for (int b = 0; b < n_in / 256; ++b) {
            put_half(w, (size_t) r * rb + (size_t) b * 100, 0.02f + 0.01f * (float) (b % 3));
            put_half(w, (size_t) r * rb + (size_t) b * 100 + 2, 0.03f + 0.01f * (float) (b % 2));
        }
    }
    return w;
}

static std::vector<uint8_t> make_q8(int rows, int n_in, unsigned seed) {
    const int blocks = n_in / 32;
    std::vector<uint8_t> q8((size_t) rows * blocks * 36, 0);
    std::mt19937 rng(seed);
    std::uniform_real_distribution<float> u(-1.f, 1.f);
    for (int t = 0; t < rows; ++t) {
        for (int b = 0; b < blocks; ++b) {
            uint8_t* blk = q8.data() + ((size_t) t * blocks + b) * 36;
            float m = 0.f;
            float vals[32];
            for (float& v : vals) {
                v = u(rng);
                m = std::max(m, std::fabs(v));
            }
            const float d = m > 0.f ? m / 127.f : 0.f;
            float sum = 0.f;
            for (int i = 0; i < 32; ++i) {
                const int q = d > 0.f ? (int) std::lround(vals[i] / d) : 0;
                const int qc = std::max(-127, std::min(127, q));
                blk[4 + i] = (uint8_t) (int8_t) qc;
                sum += (float) qc * d;
            }
            put_half(q8, (size_t) blk - (size_t) q8.data(), d);
            put_half(q8, (size_t) blk - (size_t) q8.data() + 2, sum);
        }
    }
    return q8;
}

static double bench(int n_out, int n_in, int rows, int reps, int mode) {
    const std::vector<uint8_t> w = make_aq3(n_out, n_in, 11);
    const std::vector<uint8_t> q8 = make_q8(rows, n_in, 13);
    void *dw = nullptr, *dq8 = nullptr;
    float* dy = nullptr;
    ck(cudaMalloc(&dw, w.size()), "w");
    ck(cudaMalloc(&dq8, q8.size()), "q8");
    ck(cudaMalloc(&dy, (size_t) rows * n_out * sizeof(float)), "y");
    ck(cudaMemcpy(dw, w.data(), w.size(), cudaMemcpyHostToDevice), "w copy");
    ck(cudaMemcpy(dq8, q8.data(), q8.size(), cudaMemcpyHostToDevice), "q8 copy");
    if (!fused_gemm_i8(dw, aq3_row_bytes(n_in), dq8, dy, n_in, n_out, rows, nullptr, mode)) {
        std::printf("declined %d x %d x %d\n", n_out, n_in, rows);
        std::exit(1);
    }
    ck(cudaDeviceSynchronize(), "warm");
    cudaEvent_t a, b;
    ck(cudaEventCreate(&a), "ev a");
    ck(cudaEventCreate(&b), "ev b");
    ck(cudaEventRecord(a), "rec a");
    for (int i = 0; i < reps; ++i) fused_gemm_i8(dw, aq3_row_bytes(n_in), dq8, dy, n_in, n_out, rows, nullptr, mode);
    ck(cudaEventRecord(b), "rec b");
    ck(cudaEventSynchronize(b), "sync b");
    float ms = 0.f;
    ck(cudaEventElapsedTime(&ms, a, b), "elapsed");
    const double tflops = 2.0 * (double) n_out * n_in * rows * reps / ((double) ms * 1e9);
    std::printf("%5d x %5d, %4d tokens, mode %d: %.3f ms a call, %.1f TFLOPS\n", n_out, n_in, rows, mode, ms / reps,
                tflops);
    cudaFree(dw);
    cudaFree(dq8);
    cudaFree(dy);
    return tflops;
}

int main() {
    std::printf("AQ3 int8 product, kernel alone\n");
    bench(17408, 5120, 1024, 5, 0);
    bench(17408, 5120, 1024, 5, 1);   // no weight staging
    bench(17408, 5120, 1024, 5, 2);   // no activation staging
    bench(17408, 5120, 1024, 5, 4);   // no mma or epilogue
    bench(17408, 5120, 1024, 5, 7);   // no staging and no mma
    return 0;
}
