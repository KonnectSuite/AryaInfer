> **AryaInfer documentation:** forked from [PolyStrata](https://github.com/simplexai-labs/PolyStrata), a fork of [Niko1221’s original Strata](https://github.com/Niko1221/Strata). Measurements and hardware claims on this page are inherited upstream results unless explicitly marked as measured on the AryaInfer host. See [host findings](ARYAINFER.md).

# How does AryaInfer work?

Models like Qwen3.8-Flash-Next normally run on servers with hundreds of gigabytes of graphics memory. Your graphics
card has 12-24 GB. AryaInfer makes it fit by **sharing the work across your whole PC** - the same idea as a kitchen, where
the things you use all the time stay on the counter and the rest waits in the pantry. Back to the
[README](../README.md#how-does-it-work).

## Who does what

<p align="center"><img src="media/how-it-works.svg" width="860" alt="The model's 24,576 experts: the busiest on the graphics card, all of them in RAM, a lookup table on the SSD"></p>

- **The model is a team of 24,576 small specialists ("experts"),** and each word it writes needs only 10 of them.
  So it doesn't have to have all of them on the graphics card at once.
- **Your graphics card** does the part of the work needed for every word, and keeps the few thousand experts that
  are asked most often. It keeps learning which ones those are while you use it.
- **Your RAM** holds every expert. When a word needs one the card doesn't have, **your processor** works on it -
  at the same time as the graphics card, so neither waits for the other.
- **Your SSD** holds a big lookup table; the model only reads a few small rows of it per word.

The same in technical terms:

- **GPU (VRAM):** attention and DeltaNet mixers, the gated-residual weights, routers, shared experts, output head, the
  MTP draft layer, the KV cache (from 64K: only its most-read part, the rest streams from RAM), and an **expert
  cache** that fills the rest of VRAM with the most-used experts (it adapts to the conversation while you chat).
  More VRAM matters more than a faster GPU: every extra GB holds ~700 more experts, and every expert on the GPU is one
  the CPU does not have to compute.
- **RAM:** all 24,576 experts, pinned. The CPU computes the experts that are not on the GPU **in place**, at the same
  time as the GPU works on the cached ones (AVX-512 / AVX2 kernels, ggml's for the i-quants). On a PC with little RAM
  and a big card, the [low-RAM mode](MODELS.md#a-big-graphics-card-and-little-ram) keeps in RAM only what the GPU does
  not hold.
- **SSD:** the 28.8 GB n-gram table, read a few rows per token through the OS cache.

This works the same on NVIDIA (CUDA) and AMD (HIP) cards: the same engine, compiled for each.

## Guess, then check

<p align="center"><img src="media/guess-and-check.svg" width="860" alt="A small helper guesses the next words; the big model checks them all at once and keeps the right ones"></p>

- **Guess, then check.** A small, fast helper built into the model guesses the next few words, and the big model
  checks all the guesses in one go. It keeps the ones it agrees with and writes the next word itself - so one step
  often produces several words. The helper only guesses - the big model decides every word - so you get the same
  quality answer, 1.6-1.8x sooner.
- In technical terms: the model's own MTP layer drafts up to 3 tokens; one pass over all 48 layers checks them, 2.4-3.2
  tokens per pass on average. When the reply repeats the context (code edits, quoted text), **prompt lookup** drafts
  up to 5 tokens from the earlier copy, but only where its measured acceptance and cost say it pays: code edits 6-11%
  faster, other text unchanged. The drafts are checked like the MTP's, so the output is the same.

## Reading long texts

**Long texts are read in big pieces** (up to 8,192 tokens - pieces of words - at a time), which is why a long
document or code base is read at over 1,000 tokens per second. The experts of the next layer stream to the GPU over
PCIe while the current layer's attention runs. After the first message, AryaInfer keeps the conversation and reads only
what is new, so follow-ups start in seconds.

## Four engines, one program

AryaInfer is not tied to one inference engine. The same server, chat page, API,
tools and settings serve four backends, and the model you pick decides which one
runs:

- **Strata** (`strata.exe`, upstream 0.1.58): the native Qwen engine for
  Flash-Next, Swift 1.5 and the 262K MoE profiles.
- **PolyStrata** (`strata-poly`): the GGUF engine for Qwen3.6-35B-A3B, Ornith,
  GLM 5.3 Flash, DeepSeek V4 Flash and the other families in
  [BACKENDS.md](BACKENDS.md).
- **AryaInfer** (`aryainfer`): our build of the same tree with the AQ3 kernels,
  for the dense 27B AQ3 and Turbo quants and Qwen3.5-4B.
- **NInfer** (`engine-ninfer`): a ported NInfer core behind a small shim, for the
  Qwen3.8-27B GSQ3 `.ninfer` artifact, with its own 128K path and prefix reuse.

The engine never sees the chat template or the thinking rules: the server owns
those and sends token ids. That is what lets a model roster mix engines without
changing how you use it. The measured tables for all four are in
[ENGINES.md](ENGINES.md).

## More

The [details](DETAILS.md#how-it-works) explain every part and its numbers, and the
[paper](paper/Strata-Paper.pdf) tells the whole story, with the measurements behind it.

## Credits

- AryaInfer is a fork of [PolyStrata](https://github.com/simplexai-labs/PolyStrata), which is a fork of [original Strata](https://github.com/Niko1221/Strata) by Niko1221 and its contributors. The Qwen
  engine, the installer, the server and the web app are that project's work. AryaInfer inherits the engine from PolyStrata for GLM 5.3
  Flash ([GLM.md](GLM.md)), whose file is from
  [neuralll](https://huggingface.co/neuralll/GLM-5.3-Flash-GSQ-RCO-3.0bit-Q4Kattn-GGUF).
- Model: [Qwen3.8-Flash-Next](https://huggingface.co/Qwen/Qwen3.8-Flash-Next) by the Qwen team; compressed versions by
  [ISTA-DASLab](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF);
  [Swift 1.5](https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF) by UkisAI; the experimental
  [UD-Q4_K_XL](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF) by Unsloth (its support follows
  [eddoursul/Strata](https://github.com/eddoursul/Strata)). Their licenses apply to the model files.
- Built with parts of [llama.cpp / ggml](https://github.com/ggml-org/llama.cpp) (MIT). The NInfer backend is
  [roofkid's ninfer-4080](https://github.com/roofkid/ninfer-4080) core (Apache-2.0, pinned at commit `2469b57`)
  behind our shim, with its own debt to [Neroued's ninfer](https://github.com/Neroued/ninfer). The 3-bit GSQ
  checkpoints come from [ISTA-DASLab](https://huggingface.co/ISTA-DASLab). Ideas also came from
  [Splash](https://github.com/incoai/splash) and [HyperQwen](https://github.com/syv-ai/HyperQwen). More in the
  [details](DETAILS.md#credits-and-licenses) and [ENGINES.md](ENGINES.md#credits).
- The AMD (HIP) backend: [AMD_HIP.md](AMD_HIP.md) names the contributors and the machines it was validated on.

## License

AryaInfer is open source under the [MIT License](../LICENSE). A few parts carry their own licenses: `third_party/ggml`
(MIT, llama.cpp / ggml), the web app's font (SIL Open Font License 1.1) and the experimental speed projection's
vector in `data/experimental-speed-projection` (Qwen Community License 1.0, from the model's activations). The
models are not part of this repository; each model's own license applies to its files.
