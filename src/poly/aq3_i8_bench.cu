// src/poly/aq3_i8_bench.cu - the AQ3 int8 tensor-core product alone, in TFLOPS, on matrices the model has.
//
// The whole prefill (matmul + attention + GDN) of the Q8_0 expansion path measures about 77 TFLOPS at 8K on this card;
// the int8 product has to beat that to be worth integrating.  This prints the kernel's own rate for the shapes a
// layer has, with the int8 codes made once by the library's own kernels (not timed).
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

static double bench(int n_out, int n_in, int rows, int reps, int mode) {
    const std::vector<uint8_t> w = make_aq3(n_out, n_in, 11);
    std::vector<float> x((size_t) rows * n_in);
    std::mt19937 rng(13);
    std::uniform_real_distribution<float> u(-1.f, 1.f);
    for (float& v : x) v = u(rng);

    void *dw = nullptr, *dwi = nullptr, *dxi = nullptr;
    float *dx = nullptr, *dy = nullptr;
    const size_t wi_bytes = (size_t) n_out * n_in + (size_t) n_out * (n_in / 128) * 2;
    const size_t xi_bytes = (size_t) rows * n_in + (size_t) rows * (n_in / 32) * 2;
    ck(cudaMalloc(&dw, w.size()), "w");
    ck(cudaMalloc(&dwi, wi_bytes), "wi");
    ck(cudaMalloc(&dx, x.size() * sizeof(float)), "x");
    ck(cudaMalloc(&dxi, xi_bytes), "xi");
    ck(cudaMalloc(&dy, (size_t) rows * n_out * sizeof(float)), "y");
    ck(cudaMemcpy(dw, w.data(), w.size(), cudaMemcpyHostToDevice), "w copy");
    ck(cudaMemcpy(dx, x.data(), x.size() * sizeof(float), cudaMemcpyHostToDevice), "x copy");
    aq3_to_i8(dw, dwi, n_in, n_out, nullptr);
    aq3_i8_quantize(dx, dxi, n_in, rows, nullptr);
    if (!fused_gemm_i8(dwi, (size_t) n_in, dxi, dy, n_in, n_out, rows, nullptr, mode)) {
        std::printf("declined %d x %d x %d\n", n_out, n_in, rows);
        std::exit(1);
    }
    ck(cudaDeviceSynchronize(), "warm");
    cudaEvent_t a, b;
    ck(cudaEventCreate(&a), "ev a");
    ck(cudaEventCreate(&b), "ev b");
    ck(cudaEventRecord(a), "rec a");
    for (int i = 0; i < reps; ++i) fused_gemm_i8(dwi, (size_t) n_in, dxi, dy, n_in, n_out, rows, nullptr, mode);
    ck(cudaEventRecord(b), "rec b");
    ck(cudaEventSynchronize(b), "sync b");
    float ms = 0.f;
    ck(cudaEventElapsedTime(&ms, a, b), "elapsed");
    const double tflops = 2.0 * (double) n_out * n_in * rows * reps / ((double) ms * 1e9);
    std::printf("%5d x %5d, %4d tokens, mode %d: %.3f ms a call, %.1f TFLOPS\n", n_out, n_in, rows, mode, ms / reps,
                tflops);
    cudaFree(dw);
    cudaFree(dwi);
    cudaFree(dx);
    cudaFree(dxi);
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
    bench(5120, 5120, 1024, 5, 0);
    bench(10240, 5120, 1024, 5, 0);
    bench(5120, 17408, 1024, 5, 0);
    return 0;
}
