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
/// The AQ3 matrix for the int8 product: n_out rows of n_in signed int8 codes, then a half scale a 128-value group.
void aq3_to_i8(const void* w, void* out, int n_in, int n_out, void* stream);
/// The activations for the int8 product: rows of n_in signed int8 codes, then a half scale a 32-value block.
void aq3_i8_quantize(const float* x, void* out, int n_in, int rows, void* stream);
/// The int8 tensor-core product (STRATA_AQ3_I8): the buffers aq3_to_i8 and aq3_i8_quantize write.
bool fused_gemm_i8(const void* w, size_t row_bytes, const void* xq, float* y, int n_in, int n_out, int rows,
                   void* stream, int mode = 0);

/// AQ3 (aryainfer, tools/aryainfer_gsq3_convert.py): uniform 3-bit, two fp16 scales a 256-value block of 100 bytes.
/// Not a ggml type; the GGUF stores it as I8 rows of aq3_row_bytes(n_in) and the engine tags the upload with this id.
constexpr uint32_t kTypeAQ3 = 200;
size_t aq3_row_bytes(int n_in);
/// The matrix as ggml Q8_0 (exact: a 32-value block shares its 128-value group's scale), q8 rows of n_in / 32 * 34 bytes.
void aq3_to_q8_0(const void* w, void* q8, int n_in, int n_out, void* stream);
/// y = w x for ncols (1..8) tokens of q8_1 activations laid out token after token, as native_mmvq takes them.
void aq3_gemv(const void* w, const void* xq, float* y, int n_in, int n_out, int ncols, void* stream);

}  // namespace strata::poly
