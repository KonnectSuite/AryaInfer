# Credits and project lineage

AryaInfer, maintained in [KonnectSuite/AryaInfer](https://github.com/KonnectSuite/AryaInfer),
is a fork of [PolyStrata](https://github.com/simplexai-labs/PolyStrata) by VecSzn.
PolyStrata is a fork of [the original Strata](https://github.com/Niko1221/Strata)
by Niko1221 and the Strata contributors.

We credit Niko1221 and the original Strata contributors for the original Qwen
engine, server, installer, web app and research. We credit VecSzn and the
PolyStrata contributors for the additional model engine, model integrations,
measurements and extensions inherited by this fork. Individual source notices,
third-party licenses and benchmark author attributions are preserved.
The original MIT copyright and permission notice remains in [LICENSE](LICENSE).

AryaInfer now serves five engine backends from one server: the upstream
[Strata](https://github.com/Niko1221/Strata) engine, its `strata-inkling`
sibling, [PolyStrata](https://github.com/simplexai-labs/PolyStrata)'s
`strata-poly`, our `aryainfer` build of the same `src/poly` tree with the AQ3
kernels, and AryaNInfer, a ported NInfer core with our shim
(`engine-ninfer`). [docs/ENGINES.md](docs/ENGINES.md) describes the split.

The Strata, Strata Inkling and PolyStrata engines are built, released and
supported upstream: [Strata releases](https://github.com/Niko1221/Strata/releases)
and [PolyStrata releases](https://github.com/simplexai-labs/PolyStrata/releases).
AryaInfer installs those binaries from `engines.json`; it does not claim their
release cadence. `aryainfer` and AryaNInfer are this fork's builds.

We credit [roofkid](https://github.com/roofkid/ninfer-4080) for the NInfer
engine, its GSQ3 `.ninfer` artifact format and its MTP3/DFlash2 work on a
16 GB card. The shim and Windows patches under `engine-ninfer/` are this fork's;
the core is pinned at commit `2469b57` and keeps its Apache-2.0 license. NInfer
builds in turn on ideas from [Neroued's ninfer](https://github.com/Neroued/ninfer).
The renamed build is **AryaNInfer** (`arya-ninfer.exe`, 0.1.0); the core keeps its
own name and commit so its provenance stays readable.

We credit [ISTA-DASLab](https://huggingface.co/ISTA-DASLab) for the 3-bit GSQ
checkpoints this fork runs on the dense 27B path (the
[GSQ-RCO GGUF](https://huggingface.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF) and the
[3-bit GSQ](https://huggingface.co/ISTA-DASLab/Qwen3.8-27B-3Bit-GSQ) source that
`tools/aryainfer_gsq3_convert.py` turns into AQ3), [roofkid's GSQ3 NInfer
repack](https://huggingface.co/roofkid/Qwen3.8-27B-GSQ3-NInfer),
[Unsloth](https://huggingface.co/unsloth) for the UD quants, the
[Qwen team](https://huggingface.co/Qwen/Qwen3.8-27B) for the base models, NVIDIA
for the NVTX headers vendored into the Windows build (Apache-2.0), and the
llama.cpp/ggml authors (MIT) whose kernels and file formats the engines build on.

AryaInfer is configured for our i9-14900KF, RTX 4070 Ti SUPER 16 GB, 64 GB RAM,
Windows 11 host. We build and benchmark changes against that setup, and replace
documentation wording with our measured findings as results become available.
Installed engines here: Strata 0.1.67 (native), Strata Inkling 0.1.67, PolyStrata
0.1.66 (`engine-poly`), the `aryainfer` build of 2026-11-03 (source pin
0.1.45 / 0.1.45-poly.9), and AryaNInfer 0.1.0 on the pinned NInfer core
`rtx4080-port` `2469b57`.

Only measurements explicitly recorded as AryaInfer host results describe this
machine. Inherited tables and demos describe their original machines. Keep their
provenance when comparing, superseding or archiving them. Record the exact model,
build, configuration, workload and raw results for every new performance claim.

Technical identifiers such as `strata-poly`, the `polystrata.py` compatibility CLI,
upstream release/download URLs, original benchmark files and repository names
remain where changing them would break compatibility or erase attribution.

## The web app's interface

The chat page's MCP catalog and its add-server flow are adapted from
[llama.cpp](https://github.com/ggml-org/llama.cpp)'s server WebUI (MIT): the shape of
a catalog entry, the category grouping and the order of the add flow. No source file
from that project is copied, and its web UI is Svelte, which this page does not use.

The brand marks in `serve/web/mcp-icons.svg` come from
[Simple Icons](https://simpleicons.org), whose icon data is CC0 1.0. Each mark is a
trademark of its owner and identifies its product only; see
`serve/web/mcp-icons.LICENSE.txt`.
