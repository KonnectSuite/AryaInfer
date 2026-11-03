// src/poly/aq3_i8_test.cu - the AQ3 int8 tensor-core product against a CPU reference on a synthetic matrix.
//
// The CPU builds one AQ3 matrix (random 3-bit codes, two group scales a 256-value block), quantizes the activations
// to the Q8_1 layout the kernel reads (a half scale and 32 int8 a 32-value block), and computes the product in
// double.  The GPU kernel should reproduce it within fp32 rounding.  No model file, no MMQ layout: this isolates the
// kernel's fragment mapping and its scale application.
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

static float half_at(const std::vector<uint8_t>& b, size_t at) {
    const uint16_t bits = (uint16_t) b[at] | ((uint16_t) b[at + 1] << 8);
    __half h;
    std::memcpy(&h, &bits, 2);
    return __half2float(h);
}

static void put_half(std::vector<uint8_t>& b, size_t at, float v) {
    const __half h = __float2half(v);
    std::memcpy(b.data() + at, &h, 2);
}

int main() {
    const int n_out = 256, n_in = 512, rows = 64;
    const int blocks = n_in / 32;
    const size_t rb = aq3_row_bytes(n_in);

    std::vector<uint8_t> w((size_t) n_out * rb, 0);
    std::mt19937 rng(7);
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

    std::vector<float> x((size_t) rows * n_in);
    std::uniform_real_distribution<float> u(-1.f, 1.f);
    for (float& v : x) v = u(rng);
    std::vector<uint8_t> q8((size_t) rows * blocks * 36, 0);
    for (int t = 0; t < rows; ++t) {
        for (int b = 0; b < blocks; ++b) {
            uint8_t* blk = q8.data() + ((size_t) t * blocks + b) * 36;
            const float* src = x.data() + (size_t) t * n_in + (size_t) b * 32;
            float m = 0.f;
            for (int i = 0; i < 32; ++i) m = std::max(m, std::fabs(src[i]));
            const float d = m > 0.f ? m / 127.f : 0.f;
            float sum = 0.f;
            for (int i = 0; i < 32; ++i) {
                const int q = d > 0.f ? (int) std::lround(src[i] / d) : 0;
                const int qc = std::max(-127, std::min(127, q));
                blk[4 + i] = (uint8_t) (int8_t) qc;
                sum += (float) qc * d;
            }
            put_half(q8, (size_t) blk - (size_t) q8.data(), d);
            put_half(q8, (size_t) blk - (size_t) q8.data() + 2, sum);
        }
    }

    std::vector<float> ref((size_t) rows * n_out);
    for (int t = 0; t < rows; ++t) {
        for (int r = 0; r < n_out; ++r) {
            double acc = 0.0;
            const uint8_t* wrow = w.data() + (size_t) r * rb;
            for (int k = 0; k < n_in; ++k) {
                const int b = k / 256, off = k % 256;
                const uint8_t* wblk = wrow + (size_t) b * 100;
                const int code = (int) ((wblk[4 + (off & 63)] >> (2 * (off >> 6))) & 3) |
                                 (int) (((wblk[68 + (off & 31)] >> (off >> 5)) & 1) << 2);
                const float wd = half_at(w, (size_t) r * rb + (size_t) b * 100 + (off >= 128 ? 2 : 0));
                const uint8_t* qblk = q8.data() + ((size_t) t * blocks + k / 32) * 36;
                const double xd = half_at(q8, (size_t) (qblk - q8.data()));
                acc += ((double) code - 4.0) * (double) wd * (double) (int8_t) qblk[4 + (k % 32)] * xd;
            }
            ref[(size_t) t * n_out + r] = (float) acc;
        }
    }

    void *dw = nullptr, *dq8 = nullptr;
    float* dy = nullptr;
    ck(cudaMalloc(&dw, w.size()), "w");
    ck(cudaMalloc(&dq8, q8.size()), "q8");
    ck(cudaMalloc(&dy, ref.size() * sizeof(float)), "y");
    ck(cudaMemcpy(dw, w.data(), w.size(), cudaMemcpyHostToDevice), "w copy");
    ck(cudaMemcpy(dq8, q8.data(), q8.size(), cudaMemcpyHostToDevice), "q8 copy");

    if (!fused_gemm_i8(dw, rb, dq8, dy, n_in, n_out, rows, nullptr)) {
        std::printf("fused_gemm_i8 declined the shape\n");
        return 1;
    }
    ck(cudaDeviceSynchronize(), "i8");

    std::vector<float> got(ref.size());
    ck(cudaMemcpy(got.data(), dy, got.size() * sizeof(float), cudaMemcpyDeviceToHost), "read y");

    double scale = 0.0, worst = 0.0;
    int nan = 0;
    for (size_t i = 0; i < got.size(); ++i) {
        scale = std::max(scale, (double) std::fabs(ref[i]));
        if (!std::isfinite(got[i])) {
            ++nan;
        } else {
            worst = std::max(worst, (double) std::fabs(got[i] - ref[i]));
        }
    }
    std::printf("got %.6g %.6g %.6g %.6g\n", got[0], got[1], got[2], got[3]);
    std::printf("ref %.6g %.6g %.6g %.6g\n", ref[0], ref[1], ref[2], ref[3]);
    std::printf("worst |diff| %.6g (scale %.6g), non-finite %d\n", worst, scale, nan);
    const bool ok = nan == 0 && worst <= 1e-4 * std::max(1.0, scale);
    std::printf(ok ? "AQ3 int8 product matches\n" : "AQ3 int8 product does not match\n");
    return ok ? 0 : 1;
}
