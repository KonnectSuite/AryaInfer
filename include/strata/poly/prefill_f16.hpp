// include/strata/poly/prefill_f16.hpp - a prompt batch's 3-bit matrices on the fp16 tensor cores: the weight tile
// dequantized into shared memory inside the product, so the weights are read once, as 3-bit blocks, and never as
// halves in memory (--prefill-f16, off by default).
#pragma once

#include <cstddef>
#include <cstdint>

namespace strata::poly {

/// Whether this build has a fused tensor-core product for a matrix of `ggml_type` (IQ3_XXS today).
bool f16_type(int ggml_type);
/// x (floats) to halves, for the fused product's token tile.
void cast_f16(const float* x, uint16_t* out, size_t n, void* stream);
/// y = W^T x: W is `n_out` rows of `n_in` values of ggml_type, `row_bytes` apart; x has `rows` rows of `n_in` halves;
/// y is `rows` rows of `n_out` floats.  False when the type has no kernel, and then nothing was written.
bool fused_gemm_f16(const void* w, size_t row_bytes, int ggml_type, const uint16_t* x, float* y, int n_in, int n_out,
                    int rows, void* stream);

}  // namespace strata::poly
