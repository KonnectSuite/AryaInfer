# AryaInfer fork instructions

AryaInfer is a fork of PolyStrata (VecSzn), which is a fork of the original
Strata (Niko1221). Preserve both credits and the original MIT notice. See CREDITS.md.

This fork targets the i9-14900KF, RTX 4070 Ti SUPER 16 GB, 64 GB RAM, Windows 11
host in docs/ARYAINFER.md. Only call results host findings when measured here.
Replace inherited performance wording with reproducible host findings as benchmarks
are completed; keep original attribution for historical and comparison data.
Do not change engine identifiers, release URLs or saved-data paths solely for branding.

# AGENTS.md

AryaInfer runs the Qwen3.8-Flash-Next mixture-of-experts model (and its Coder, Swift 1.5 and Unsloth variants) on a
normal PC: one NVIDIA or AMD graphics card plus system RAM, on Windows or Linux. It has a C++/CUDA/HIP engine
(`src/`, `include/`), a Python server with an OpenAI- and Anthropic-compatible API and a web app (`serve/`), and a
one-click installer (`setup.py`, started by `START-HERE.bat` / `setup.sh`).

A second engine, `strata-poly` (`src/poly/`), runs GLM 5.3 Flash, DeepSeek V4 Flash and six smaller model families
from their GGUF files. The six smaller families have Windows and Linux paths; larger models and other backends
have separate limits: [docs/GLM.md](docs/GLM.md), [docs/BACKENDS.md](docs/BACKENDS.md).
Qwen3.6 also has a native Strata path with vision and MTP (`--family qwen36-strata`): [docs/QWEN36.md](docs/QWEN36.md).
The Qwen engine, the installer, the server and the web app come from
[Strata](https://github.com/Niko1221/Strata).

The chat page reaches tools two ways: MCP servers the user configures ([serve/mcp.py](serve/mcp.py), managed from the
Monitor tab) and a SearXNG web search ([serve/websearch.py](serve/websearch.py)): [docs/SEARCH.md](docs/SEARCH.md).

## Installing AryaInfer for a user

Follow **[docs/AI_SETUP.md](docs/AI_SETUP.md)**: check the PC, pick the model by RAM, run setup non-interactively,
start and verify the server, and connect the user's apps. Never expose the server beyond `127.0.0.1` without
`--api-key`. As an alternative to shell commands, AryaInfer's MCP server ([docs/MCP_SERVER.md](docs/MCP_SERVER.md))
offers the same steps as tools.

## Working on the code

- How the engine works, every measured number, the API and all settings: [docs/DETAILS.md](docs/DETAILS.md) and
  the [paper](docs/paper/Strata-Paper.pdf).
- AMD (HIP) build and validation: [docs/AMD_HIP.md](docs/AMD_HIP.md); multi-GPU: [docs/MULTI_GPU.md](docs/MULTI_GPU.md).
- Text taken from the Strata project names that project. After merging from it,
  `python tools/polystrata_names.py` checks current AryaInfer branding in code files, and
  `python tools/aryainfer_names.py --check` the docs; each one's first lines say what it leaves alone.
- Setup's own tests run without a GPU or downloads: `python tools/test_setup_<name>.py` (for example
  `tools/test_setup_amd.py`, `tools/test_setup_choices.py`).
- Keep the docs' style: plain words, measured numbers with what they were measured on, no claims without a
  measurement.

## Interface work

Every new or edited view, dialog, drawer, card or row is judged as design, not only as function:

- Use the kit: the tokens in `serve/web/tokens.css` (never a new colour) and the components in
  `serve/web/components.css`. A card has a title, a description and fields; a field's hint belongs under the field, not
  floating to the right of its label; actions live in a footer or a row of their own and stay in reach.
- One control for one job: a message box is the chat's composer, a dialog is `st-dialog`, a menu is `st-menu`. Do not
  build a second, slightly different copy of something the page already has.
- Look at it before calling it done: 1440 px and 390 px, light and dark. On a phone a dialog is full screen and the
  layout is one column; nothing may be cut off or need a sideways scroll.

## Contributing a change or report

- Search the open issues and pull requests first, and add to a thread that already covers your point.
- Open an issue with the form that fits (bug report, feature request or question).
- One change per pull request. Say what it changes and what it leaves alone.
- A new feature is opt-in, and the default path stays byte-identical to the last release. Say how you checked.
- Build every backend a file touches (CUDA, HIP, SYCL) before asking for review.
- Change a default only where you measured it faster, and show the numbers with what they were measured on.
- A report from hardware the maintainers do not have is welcome. Follow
  [docs/COMMUNITY_BENCHMARKS.md](docs/COMMUNITY_BENCHMARKS.md), compare against a same-day run of the build you are
  testing, and say what you did not test.
- Open test requests and the hardware that is wanted are listed in [docs/TEST_REQUESTS.md](docs/TEST_REQUESTS.md).
