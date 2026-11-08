# Images through ComfyUI

AryaInfer can generate and edit pictures with a [ComfyUI](https://github.com/comfyanonymous/ComfyUI) on this machine
or on another one. The chat page never talks to ComfyUI directly: every call goes through AryaInfer's own server,
which is what makes a remote ComfyUI (with a token in its headers) work from the same page, and what keeps the page's
rule that the browser talks only to AryaInfer.

The graphs are API-format workflow JSONs with placeholders, the contract the
[arya-comfyui-workflows](https://github.com/KonnectSuite/arya-comfyui-workflows) pack documents. This is the same
contract the `dsh-arya-image-gen` plugin uses; the compatibility rules (endpoints, placeholders, "never kill a server
you did not start") are adapted from that plugin (Apache-2.0), and the six graphs below are that pack's.

## Get a ComfyUI

| route | best for | notes |
| --- | --- | --- |
| **Desktop app** | most people on Windows | https://comfy.org/download — starts on `127.0.0.1:8188` |
| **Windows portable** | a self-contained folder | unzip and run its launcher; point AryaInfer at that folder if it should start it |
| **comfy-cli** | scripted installs | `pip install "comfy-cli>=1.14.0"`, then `comfy install` |
| **Manual** | custom PyTorch builds | clone ComfyUI, install `requirements.txt`, `python main.py` |

The six shipped graphs expect these files, in ComfyUI's `models/` folder:

| file | folder |
| --- | --- |
| `qwen_image_2.1_turbo_int8_convrot.safetensors` | `diffusion_models/` |
| `qwen3vl_8b_w4a8.safetensors` | `text_encoders/` |
| `qwen_image_2.1_vae_bf16.safetensors` | `vae/` |

If those files are already somewhere else, point ComfyUI at them with `extra_model_paths.yaml` instead of copying
hundreds of gigabytes.

## The shipped graphs

| name | output | what it does |
| --- | --- | --- |
| `Qwen_Image_2_1_Turbo_Square_1024` | 1024x1024 | text to image |
| `Qwen_Image_2_1_Turbo_Wide_1344x768` | 1344x768 | text to image |
| `Qwen_Image_2_1_Turbo_Portrait_768x1344S` | 768x1344 | text to image |
| `Qwen_Image_2_1_Turbo_Edit` | the source's size | take a reference image and change it |
| `Qwen_Image_2_1_Remove_Background` | the source's size | take a reference image and cut its background away |
| `Qwen_Image_2_1_Cutout_RGBA_1024` | 1024x1024 | text to image, prompted for a cut-out subject |

They live in `serve/comfy-workflows/`. The page can import more (an API-format graph saved with ComfyUI's
**Save (API Format)**); imports are kept in `local-data/comfy-workflows/` beside the settings file and never overwrite
a shipped name.

## The page

**Settings > Tools > Images** (and the **Setup** button in the room) is the server card: the address, headers, timeout,
the launch method with Start/Stop/Restart, the workflow list with the default for text and for edits, Import JSON,
and **Check against ComfyUI**, which names a missing node class or model file per graph before a run fails. The VRAM
policy and the gallery limits are there too.

**Images** in the sidebar is the room. It is a conversation, not a form: you say what you want, the model writes the
image prompt and picks the workflow itself (the tool description lists every graph with its role and size), and asks
ComfyUI for it. A follow-up ("warmer light", "put a croissant on the saucer") is an edit: the model passes the id of the
last picture as `reference_id` with an image-to-image graph, so the composition carries over. The thread lives in the
browser, so when a phone has thrown it away the room reads the newest pictures from the gallery instead, and an
image-to-image call with no `reference_id` edits the newest picture - "change the last one" survives a reload.

The room is laid out like the chat: the message box under it **is** the chat's composer, same component and width
(860 px, centred), with the attach-picture button, dictation and the send button where the chat has them; it is shown
on **Create** and hidden on the gallery tabs. The conversation is the chat's column too, while **My images** and
**Templates** use the full width: square tiles in a grid that fits as many columns as the window has room for (two a
row on a phone), the prompt over the picture on hover, and the favourite star where it always was.

A picture attached with the paperclip goes with the **request**, not just the instructions: the page sends
`strata_images: {"references": ["<id>"]}`, the server gives that request its own tool, and the picture is edited even
when the model leaves `reference_id` out - and a text-to-image graph it names by mistake is replaced by the default
image-to-image graph, because attaching a picture is the instruction to edit it. A bad list (or an id that is gone)
answers with a sentence, not a crash.

The tool is **raster only**, and the server enforces it: when the last message names a format to be written - SVG,
HTML, CSS, Markdown, Mermaid, Graphviz, PlantUML, LaTeX - and does not name a picture, the request is not offered
`generate_image` at all, so the model writes the code in a fenced block. Asked for "an animated HTML of turtles in a
pond", one model offered the tool reached for a "reference palette" picture first: a failed ComfyUI call and a wait
nobody asked for. A request that also says picture, photo, image, illustration, wallpaper or poster keeps the tool;
"an image for my HTML page" is a picture request. The answer renders code in a sandboxed frame in the chat itself (no
network, opaque origin, inline style and script only), with a **Download** button that saves the block as a file. The
code stays readable under the preview, and a block that is still streaming, or one larger than 200 KB, stays code.
When the chat has web search on, the model may search for a factual reference and turn what it finds into the prompt;
web pictures cannot be downloaded into ComfyUI, and the room never pretends otherwise.

- **My images** is the server-side gallery: search, favourites, a pager, and a viewer with edit / ask-for-a-change /
  download / favourite / delete.
- **Templates** are twelve prompts to start from (a studio portrait, a product shot, a poster, a restyle).
- **Local model** is the older sd-cli image form, shown only when an sd-cli image model is configured.
- The thread is kept in this browser (like the chats); the pictures are on the server, so they show in every browser.

## Placeholders

A graph is a plain ComfyUI API graph plus these tokens:

| token | where | meaning |
| --- | --- | --- |
| `{{prompt}}` | any text input, required | the prompt; replaced wherever it appears in the string |
| `{{seed}}` | a numeric input | a fresh seed per image; inside a string it becomes digits |
| `{{width}}`, `{{height}}` | the whole value of a numeric input | the canvas, 64-8192 |
| `{{steps}}`, `{{cfg}}` | the whole value of a numeric input | sampler steps (1-150) and guidance (0-30) |
| `{{resolution}}` | the whole value of a numeric input | derived: the canvas' long side, rounded to 32 |
| `{{image}}` | exactly one `LoadImage` input | makes the graph an edit graph |
| `{{images}}` | a link `["{{images}}", 0]` on a numbered input such as `images.image_1` | one `LoadImage` per reference, in order, up to 16 |

A graph that bakes a size (the three create graphs do) refuses a request for a size: add `{{width}}`/`{{height}}` to
its `EmptyLatentImage` to make it adjustable, or pick the graph whose size you want. `Check against ComfyUI` reports a
graph whose node classes or model files the server does not have, before a run fails.

## Settings

`comfyui.json` beside the run config (written by the page, whole and atomically; the page never edits the run config):

```json
{"version": 1,
 "settings": {"base_url": "http://127.0.0.1:8188", "headers": {}, "timeout_s": 600,
              "active_text": "Qwen_Image_2_1_Turbo_Square_1024", "active_edit": "Qwen_Image_2_1_Turbo_Edit",
              "launch": {"mode": "auto", "server_dir": "", "python_exe": "", "extra_args": "--listen 127.0.0.1",
                         "task_name": "ComfyUI", "auto_start": false},
              "free_vram": {"policy": "auto", "need_mib": 10240},
              "gallery": {"max_files": 500, "max_mib": 8192},
              "imported": [], "max_rounds": 8}}
```

`headers` carry a reverse-proxy token for a remote ComfyUI; the page sees them masked and sends them back unchanged.

## Starting and stopping a local ComfyUI

`launch.mode` says how Start reaches this machine's ComfyUI:

- `auto` — the named scheduled task if Task Scheduler has one, else `python main.py --port <port>` in the configured
  folder, else "external": AryaInfer says so and starts nothing;
- `scheduled-task` — `schtasks /run` and `/end` on `launch.task_name` (the way ComfyUI Desktop is often run);
- `process` — `python main.py` from `launch.server_dir` with `launch.python_exe`.

Stop only ever ends a python process whose command line runs ComfyUI's `main.py` on the configured port, or the
scheduled task it started. **It never kills whatever else holds that port** — on this machine Tailscale listens there
for the tailnet, and killing that would break remote access rather than stop ComfyUI. Start is refused for a remote
endpoint; start it there.

## The VRAM policy

ComfyUI and the text engine compete for one card. `free_vram.policy` decides what the model does during an image job,
through the same code the sd-cli images use (`serve/gputurn.py`):

| policy | what happens |
| --- | --- |
| `auto` (default) | keep the model when `need_mib` fits next to it, else shrink its expert cache (`--vram-elastic`), else unload it |
| `keep` | the model stays loaded; the job gets what is free |
| `unload` | save the conversation, stop the engine, run the job, and restore the conversation after the next start |

`need_mib` is what the job is planned with (default 10 GiB; the shipped graphs fit in about that on a 16 GB card).

The same card runs both engines, so AryaInfer hands it back and forth: starting the text engine asks ComfyUI to unload
its weights (`POST /free`) first, and ComfyUI reloads them from disk on the next picture. Without that, the text engine
loads into whatever ComfyUI left free and runs partly on the CPU - measured on this host as 30 tok/s decode and 57 tok/s
prefill for Qwen3.8 27B, against 57 tok/s and 882 tok/s with the card to itself.

## Where the images go

`local-data/image-gallery/`: one PNG per image named by 32 hex digits, and `index.json` with the prompt, workflow,
seed, timings, source image and favourite flag. The gallery is pruned to `gallery.max_files` / `max_mib`, favourites
last. Images are served at `/comfy/files/<id>.png`; the name cannot leave the folder.

## Security

ComfyUI has no authentication of its own. Do not expose it with `--listen 0.0.0.0`: use a reverse proxy with TLS and a
token (put the token in `headers`), or a private network such as Tailscale. AryaInfer's own page gate applies as it
does to MCP and web search: the image endpoints answer JSON from this page only, and a foreign `Origin` is refused.

## Troubleshooting

| symptom | cause | fix |
| --- | --- | --- |
| "Could not reach ComfyUI" | it is not running, or the address is wrong | start it (or press Start), then check the address |
| Check names a missing node class | the install or a custom node pack is older than the graph | update ComfyUI, or import a graph that matches it |
| Check names a missing model | the safetensors file is absent or in the wrong folder | move it to the folder in the table above |
| a job ends with a workflow error | ComfyUI's own message is shown as-is | read it: a missing model and a bad node link look different there |
| generation is slow or fails on a big prompt | the card ran out of room | lower `need_mib` won't help; unload other GPU users, or use a smaller graph |
| a create graph refuses a size | its size is baked | use the graph for that size, or add `{{width}}`/`{{height}}` and re-import |



