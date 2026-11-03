"""serve/comfyui.py - image generation through a local or remote ComfyUI.

AryaInfer starts ComfyUI programs and models nothing about them: a workflow is an API-format JSON graph with
placeholders (the contract `arya-comfyui-workflows` documents), and this module fills them in, submits the graph,
waits for the history entry and downloads the image.  The page never talks to ComfyUI itself - its CORS header names one
other origin at most - so every call is proxied here, which is also what makes a remote ComfyUI, with a token in
`headers`, work from the same page.

Settings live in `comfyui.json` beside the run config (serve/webconf.py's neighbour), written whole and atomically:
the endpoint, headers, timeout, the two default workflows (text and edit), the local server launcher, the VRAM policy
and the gallery limits.  The workflows themselves are files: the six shipped in `serve/comfy-workflows/`, plus any the
page imported into `local-data/comfy-workflows/`.

Placeholders:
  {{prompt}}               required, in a text input (replaced anywhere in the string)
  {{seed}}                 whole field -> a number, inside a string -> digits
  {{width}} {{height}}     whole field, 64-8192; a graph that bakes a size refuses a request for one
  {{steps}} {{cfg}}        whole field, 1-150 / 0-30
  {{resolution}}           derived: the canvas' long side, snapped to 32 (Qwen-Image conditioning wants that)
  {{image}}                exactly one LoadImage input; the graph is then an edit graph
  {{images}}               a link ["{{images}}", 0] on a numbered input such as images.image_1: one LoadImage per
                           reference, in the order they were supplied, up to 16

The compatibility rules this follows (HTTP endpoints, the workflow contract, the launcher's "never kill what you did
not start") are adapted from dsh-arya-image-gen (Apache-2.0); the graphs themselves come from arya-comfyui-workflows.
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import secrets
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from serve.gallery import Gallery

ROOT = Path(__file__).resolve().parent.parent
FILE = "comfyui.json"
VERSION = 1
SHIPPED_DIR = ROOT / "serve" / "comfy-workflows"
IMPORTED_DIRNAME = "comfy-workflows"        # beside the run config, under local-data when that is where the config is

DEFAULT_BASE_URL = "http://127.0.0.1:8188"
POLICIES = ("auto", "keep", "unload")
LAUNCH_MODES = ("auto", "scheduled-task", "process")
DEFAULT_EXTRA_ARGS = "--listen 127.0.0.1"
MAX_WORKFLOW_BYTES = 5 << 20
MAX_JSON_BYTES = 16 << 20
MAX_IMAGE_BYTES = 64 << 20
MAX_REFERENCES = 16
MAX_COUNT = 4

PROMPT = "{{prompt}}"
SEED = "{{seed}}"
IMAGE = "{{image}}"
IMAGES = "{{images}}"
RESOLUTION = "{{resolution}}"
NUMERIC = {                                  # whole-field numeric placeholders: (low, high, integer)
    "width": (64, 8192, True),
    "height": (64, 8192, True),
    "steps": (1, 150, True),
    "cfg": (0, 30, False),
}
LEGACY_PROMPT, LEGACY_SEED, LEGACY_IMAGE = "%prompt%", "%seed%", "%image%"
DEFAULT_CANVAS = 1024
NAME_PATTERN = re.compile(r"^[A-Za-z0-9._ -]{1,64}$")
MASK = "********"

DEFAULTS = {
    "base_url": DEFAULT_BASE_URL,
    "headers": {},
    "timeout_s": 600.0,
    "active_text": "",
    "active_edit": "",
    "launch": {"mode": "auto", "server_dir": "", "python_exe": "", "extra_args": DEFAULT_EXTRA_ARGS,
               "task_name": "ComfyUI", "auto_start": False},
    "free_vram": {"policy": "auto", "need_mib": 10240},
    "gallery": {"max_files": 500, "max_mib": 8192},
    "imported": [],
    "max_rounds": 8,
}


class ComfyError(RuntimeError):
    """A ComfyUI call failed; the message is the sentence the page shows."""


class ComfyCancelled(ComfyError):
    """The job was cancelled (the page's Stop, or the chat request that asked for it went away)."""


class WorkflowError(ValueError):
    """A workflow or a request for it cannot be run (400 to the page)."""


# ------------------------------------------------------------------------------------------------ settings
def path_for(config_path: str | Path | None) -> Path:
    """`comfyui.json` beside the run config (else beside the code): the run config is per model, this file is not."""
    base = Path(config_path).parent if config_path else ROOT
    return base / FILE


def imported_dir(path: str | Path) -> Path:
    """Where the page's imported workflows live: a `comfy-workflows` folder beside the settings file."""
    return Path(path).parent / IMPORTED_DIRNAME


def _number(value, name: str, low: float, high: float, what: str) -> float:
    number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not number or not (low <= float(value) <= high):
        raise ValueError(f"{name} must be a number of {what} between {low:g} and {high:g}")
    return float(value)


def _flag(value, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1, "true", "false", "on", "off"):
        return str(value).lower() in ("1", "true", "on")
    raise ValueError(f"{name} must be true or false, not {value!r}")


def normalize(raw: dict) -> dict:
    """The settings with every value checked and filled in from DEFAULTS.  ValueError: the sentence the page shows."""
    if not isinstance(raw, dict):
        raise ValueError("the ComfyUI settings must be an object")
    out = json.loads(json.dumps(DEFAULTS))
    for key, value in raw.items():
        if key in out:
            out[key] = value
    base = str(out.get("base_url") or "").strip().rstrip("/")
    if base:
        parts = urllib.parse.urlsplit(base)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"the ComfyUI address must start with http:// or https://, not {base!r}")
        if parts.query or parts.fragment:
            raise ValueError("the ComfyUI address is a base address: leave out ?query and #hash")
    out["base_url"] = base or DEFAULT_BASE_URL
    out["timeout_s"] = _number(out.get("timeout_s"), "timeout_s", 10, 3600, "seconds")
    headers = out.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError('"headers" must be an object of names and values')
    out["headers"] = {str(k).strip(): str(v) for k, v in headers.items() if str(k).strip()}
    for key in ("active_text", "active_edit"):
        value = out.get(key) or ""
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a workflow name")
        out[key] = value.strip()
    launch = out.get("launch") or {}
    if not isinstance(launch, dict):
        raise ValueError('"launch" must be an object')
    mode = str(launch.get("mode") or "auto").strip().lower()
    if mode not in LAUNCH_MODES:
        raise ValueError(f"launch mode is {', '.join(LAUNCH_MODES)}")
    out["launch"] = {
        "mode": mode,
        "server_dir": str(launch.get("server_dir") or "").strip(),
        "python_exe": str(launch.get("python_exe") or "").strip(),
        "extra_args": str(launch.get("extra_args") if launch.get("extra_args") is not None else DEFAULT_EXTRA_ARGS),
        "task_name": str(launch.get("task_name") or "ComfyUI").strip() or "ComfyUI",
        "auto_start": _flag(launch.get("auto_start", False), "launch.auto_start"),
    }
    free = out.get("free_vram") or {}
    if not isinstance(free, dict):
        raise ValueError('"free_vram" must be an object')
    policy = str(free.get("policy") or "auto").strip().lower()
    if policy not in POLICIES:
        raise ValueError(f"the VRAM policy is {', '.join(POLICIES)}")
    out["free_vram"] = {"policy": policy,
                        "need_mib": int(_number(free.get("need_mib", 10240), "free_vram.need_mib", 512, 98304, "MiB"))}
    gal = out.get("gallery") or {}
    if not isinstance(gal, dict):
        raise ValueError('"gallery" must be an object')
    out["gallery"] = {"max_files": int(_number(gal.get("max_files", 500), "gallery.max_files", 10, 100000, "files")),
                      "max_mib": _number(gal.get("max_mib", 8192), "gallery.max_mib", 0, 1_000_000, "MiB")}
    imported = out.get("imported") or []
    if not isinstance(imported, list):
        raise ValueError('"imported" must be a list of workflow names')
    out["imported"] = [str(n) for n in imported if isinstance(n, str) and NAME_PATTERN.match(n)]
    out["max_rounds"] = int(_number(out.get("max_rounds", 8), "max_rounds", 1, 32, "rounds"))
    return out


def public_settings(settings: dict) -> dict:
    """What GET /comfy may tell the page: the headers masked."""
    out = json.loads(json.dumps(settings))
    if out.get("headers"):
        out["headers"] = {k: MASK for k in out["headers"]}
    return out


def merge_secrets(new: dict, old: dict) -> dict:
    """`new` with every masked header value replaced by the stored one."""
    out = {k: v for k, v in new.items() if k != "headers"}
    block = new.get("headers")
    if isinstance(block, dict):
        kept = old.get("headers") if isinstance(old.get("headers"), dict) else {}
        value = {}
        for k, v in block.items():
            if v == MASK:
                if k in kept:
                    value[k] = kept[k]
            else:
                value[k] = v
        out["headers"] = value
    return out


def read_settings(path: str | Path) -> dict:
    """The saved settings, {} when the file is missing, and a moved-aside file when it cannot be read."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        target = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        with contextlib.suppress(OSError):
            os.replace(path, target)
        print(f"[strata] {path.name}: {e}; the ComfyUI settings start empty", flush=True)
        return {}
    block = data.get("settings") if isinstance(data, dict) else None
    return block if isinstance(block, dict) else {}


def write_settings(path: str | Path, settings: dict) -> Path:
    """The whole file: a temporary file written first, then moved over the old one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"version": VERSION, "settings": settings}, indent=1) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    os.replace(tmp, path)
    return path


# ------------------------------------------------------------------------------------------------ workflows
def _read_workflow(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError as e:
        raise WorkflowError(f"{path.name}: cannot be read ({e})") from None
    if size > MAX_WORKFLOW_BYTES:
        raise WorkflowError(f"{path.name}: a workflow file is at most 5 MB")
    return path.read_text(encoding="utf-8-sig")


def describe(workflow_json: str | dict) -> dict:
    """What a graph can do: its role, which placeholders it declares, the size it bakes."""
    text = workflow_json if isinstance(workflow_json, str) else json.dumps(workflow_json)
    role = "image-to-image" if (IMAGE in text or IMAGES in text or LEGACY_IMAGE in text) else "text-to-image"
    placeholders = {key: (("{{" + key + "}}") in text) for key in ("width", "height", "steps", "cfg")}
    placeholders["resolution"] = RESOLUTION in text
    baked = {}
    try:
        data = json.loads(text)
    except ValueError:
        return {"role": role, "placeholders": placeholders, "baked_size": None}
    if isinstance(data, dict):
        for node in data.values():
            inputs = node.get("inputs") if isinstance(node, dict) else None
            if not isinstance(inputs, dict):
                continue
            for key in ("width", "height"):
                if key not in baked and isinstance(inputs.get(key), int) and not isinstance(inputs.get(key), bool):
                    baked[key] = inputs[key]
    return {"role": role, "placeholders": placeholders,
            "baked_size": ({"width": baked["width"], "height": baked["height"]}
                           if "width" in baked and "height" in baked else None)}


def load_workflows(shipped: str | Path = SHIPPED_DIR, imported: str | Path | None = None) -> list[dict]:
    """Every workflow the page may offer: the shipped ones first, then the page's imports (same name: shipped wins)."""
    out, seen = [], set()
    for source, folder in (("shipped", Path(shipped)), ("imported", Path(imported) if imported else None)):
        if folder is None or not folder.is_dir():
            continue
        for file in sorted(folder.glob("*.json")):
            name = file.stem
            if name in seen or not NAME_PATTERN.match(name):
                continue
            try:
                text = _read_workflow(file)
                info = describe(text)
            except (WorkflowError, OSError):
                continue
            seen.add(name)
            out.append({"name": name, "source": source, **info, "path": str(file)})
    return out


def find_workflow(workflows: list[dict], name: str | None, role: str | None = None) -> dict:
    """One workflow by name (or the first of `role`): the sentence the page shows when it is not there."""
    if name:
        bare = re.sub(r"\.json$", "", name.strip(), flags=re.I).lower()
        match = next((w for w in workflows if w["name"] == name), None) or \
            next((w for w in workflows if w["name"].lower() == bare), None)
        if match is None:
            raise WorkflowError(f"No ComfyUI workflow named {name!r}. Available: "
                                + (", ".join(w["name"] for w in workflows) or "none"))
        if role and match["role"] != role:
            alternative = next((w for w in workflows if w["role"] == role), None)
            raise WorkflowError(f"{match['name']!r} is {'an' if match['role'].startswith('image') else 'a'} "
                                f"{match['role']} workflow; this call needs {role}."
                                + (f" Use {alternative['name']!r} instead." if alternative else
                                   " Import one in Settings > Tools > Images."))
        return match
    if role:
        match = next((w for w in workflows if w["role"] == role), None)
        if match is None:
            raise WorkflowError(f"No {role} workflow is configured. Import one in Settings > Tools > Images"
                                + (" (a graph with an {{image}} or {{images}} input)." if role == "image-to-image" else "."))
        return match
    raise WorkflowError("Pick a workflow first, or set a default in Settings > Tools > Images")


def _parse_workflow(workflow_json: str | dict) -> dict:
    if isinstance(workflow_json, dict):
        data = workflow_json
    else:
        if not str(workflow_json or "").strip():
            raise WorkflowError("Import a ComfyUI API-format workflow JSON first")
        if len(workflow_json.encode("utf-8")) > MAX_WORKFLOW_BYTES:
            raise WorkflowError("a workflow file is at most 5 MB")
        try:
            data = json.loads(workflow_json)
        except ValueError:
            raise WorkflowError("that workflow file is not valid JSON") from None
    if not isinstance(data, dict) or not data:
        raise WorkflowError("a workflow must be a non-empty API-format JSON object")
    if not any(_has_prompt(node.get("inputs")) for node in data.values() if isinstance(node, dict)):
        raise WorkflowError(f"a workflow must contain {PROMPT} in a text input")
    return data


def _has_prompt(value) -> bool:
    if isinstance(value, str):
        return PROMPT in value or LEGACY_PROMPT in value
    if isinstance(value, list):
        return any(_has_prompt(v) for v in value)
    if isinstance(value, dict):
        return any(_has_prompt(v) for v in value.values())
    return False


def _image_inputs(data: dict) -> int:
    count = 0
    for node in data.values():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if isinstance(inputs, dict) and inputs.get("image") in (IMAGE, LEGACY_IMAGE):
            count += 1
    return count


def _reference_inputs(data: dict) -> list[tuple[str, str, str]]:
    """Inputs that link {{images}} -> [(node id, key, prefix)]."""
    out = []
    for node_id, node in data.items():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            if isinstance(value, list) and value and value[0] == IMAGES:
                match = re.match(r"^(.*?)(\d+)$", str(key))
                if match is None:
                    raise WorkflowError(f'{IMAGES} must sit on a numbered input such as "images.image_1" '
                                        f'(node {node_id}, input "{key}")')
                out.append((node_id, key, match.group(1)))
    return out


def _numeric_values(data: dict, supplied: dict) -> dict:
    """Validate the numeric placeholders against what the request supplied -> {token: number}."""
    declared, baked = set(), {}
    wants_resolution = False
    for node in data.values():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            continue
        for key in NUMERIC:
            if inputs.get(key) == "{{" + key + "}}":
                declared.add(key)
        if inputs.get("resolution") == RESOLUTION:
            wants_resolution = True
        for key in ("width", "height"):
            if key not in baked and isinstance(inputs.get(key), int) and not isinstance(inputs.get(key), bool):
                baked[key] = inputs[key]
    values = {}
    for key, (low, high, integer) in NUMERIC.items():
        token = "{{" + key + "}}"
        want = supplied.get(key)
        if key not in declared:
            if want is not None:
                raise WorkflowError(f"This workflow bakes {key}; add {token} to a numeric input to make it adjustable, "
                                    f"or pick a workflow that supports it.")
            continue
        if want is None:
            if key in ("width", "height"):
                values[token] = DEFAULT_CANVAS
                continue
            raise WorkflowError(f"This workflow declares {token}; pass {key} so it can be filled in.")
        if not isinstance(want, (int, float)) or isinstance(want, bool):
            raise WorkflowError(f"{key} must be a number")
        value = int(round(want)) if integer else float(want)
        if not (low <= value <= high):
            raise WorkflowError(f"{key} must be between {low:g} and {high:g} (got {want})")
        values[token] = value
    if wants_resolution:
        width = values.get("{{width}}", baked.get("width", DEFAULT_CANVAS))
        height = values.get("{{height}}", baked.get("height", DEFAULT_CANVAS))
        long_side = max(int(width), int(height))
        values[RESOLUTION] = max(64, min(4096, round(long_side / 32) * 32))
    # a numeric placeholder inside a longer string would reach ComfyUI as text: refuse it now
    for node_id, node in data.items():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if isinstance(inputs, dict):
            _check_whole_fields(inputs, node_id)
    return values


def _check_whole_fields(value, node_id) -> None:
    if isinstance(value, str):
        for token in [("{{" + k + "}}") for k in NUMERIC] + [RESOLUTION]:
            if token in value and value != token:
                raise WorkflowError(f"{token} must be the whole value of a numeric input (node {node_id}), "
                                    "not part of a longer string")
        return
    if isinstance(value, list):
        for child in value:
            _check_whole_fields(child, node_id)
        return
    if isinstance(value, dict):
        for child in value.values():
            _check_whole_fields(child, node_id)


def prepare(workflow_json: str | dict, *, prompt: str, seed: int | None = None, width=None, height=None,
            steps=None, cfg=None, image: str | None = None, images: list[str] | None = None) -> dict:
    """The graph with the prompt, seed, size and reference names filled in, ready for POST /prompt."""
    data = _parse_workflow(workflow_json)
    prompt = "" if prompt is None else str(prompt)
    seed = int(seed if seed is not None else secrets.randbelow(1 << 32))
    references = list(images or [])
    values = _numeric_values(data, {"width": width, "height": height, "steps": steps, "cfg": cfg})
    dynamic = _reference_inputs(data)

    def walk(value):
        if isinstance(value, str):
            if value in values:
                return values[value]
            replaced = value.replace(PROMPT, prompt).replace(LEGACY_PROMPT, prompt)
            if replaced in (SEED, LEGACY_SEED):
                return seed
            return replaced.replace(SEED, str(seed)).replace(LEGACY_SEED, str(seed))
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        return value

    prepared = {}
    for node_id, node in data.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            prepared[node_id] = node
            continue
        prepared[node_id] = {**node, "inputs": walk(node["inputs"])}

    image_inputs = _image_inputs(prepared)
    if dynamic:
        names = references or ([image] if image else [])
        if not names:
            raise WorkflowError(f"This workflow takes reference images through {IMAGES}; supply at least one image")
        if len(names) > MAX_REFERENCES:
            raise WorkflowError(f"This workflow accepts at most {MAX_REFERENCES} reference images; got {len(names)}")
        return _expand_references(prepared, dynamic, names)
    if image_inputs > 1:
        raise WorkflowError(f"A workflow has at most one {IMAGE} image input; found {image_inputs}")
    if image_inputs and not image:
        raise WorkflowError(f"This workflow contains an {IMAGE} image input, which needs a source image")
    if not image_inputs and image:
        raise WorkflowError(f"This workflow takes no {IMAGE} image input; pick an edit workflow")
    if image_inputs:
        for node in prepared.values():
            inputs = node.get("inputs") if isinstance(node, dict) else None
            if isinstance(inputs, dict) and inputs.get("image") in (IMAGE, LEGACY_IMAGE):
                inputs["image"] = image
    return prepared


def _expand_references(data: dict, slices: list[tuple[str, str, str]], names: list[str]) -> dict:
    """One LoadImage node per reference, in the caller's order, replacing the {{images}} link."""
    out = dict(data)
    highest = 0
    for key in out:
        if str(key).isdigit():
            highest = max(highest, int(key))
    for node_id, key, prefix in slices:
        node = out.get(node_id) if isinstance(out.get(node_id), dict) else {}
        inputs = dict(node.get("inputs") or {})
        inputs.pop(key, None)
        for index, name in enumerate(names):
            highest += 1
            out[str(highest)] = {"class_type": "LoadImage", "inputs": {"image": name}}
            inputs[f"{prefix}{index + 1}"] = [str(highest), 0]
        out[node_id] = {**node, "inputs": inputs}
    return out


# ------------------------------------------------------------------------------------------------ client
def _ssl_context():
    """A trust store that works: certifi's bundle when the install has it, else the platform's own."""
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def _png_size(data: bytes) -> tuple[int | None, int | None]:
    """A PNG's width and height from its IHDR, so a record carries the real size a graph baked."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return None, None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _sniff_image(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def is_local(base_url: str) -> bool:
    try:
        host = urllib.parse.urlsplit(base_url).hostname or ""
    except ValueError:
        return False
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


class ComfyClient:
    """One ComfyUI's HTTP surface, as this project uses it."""

    def __init__(self, base_url: str, headers: dict | None = None, timeout_s: float = 600.0):
        self.base = str(base_url).rstrip("/")
        self.headers = dict(headers or {})
        self.timeout = float(timeout_s)

    def _open(self, path: str, data: bytes | None = None, timeout: float | None = None, accept="application/json"):
        url = f"{self.base}/{path.lstrip('/')}"
        req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
        req.add_header("Accept", accept)
        if data is not None and "Content-Type" not in self.headers and not any(
                k.lower() == "content-type" for k in self.headers):
            req.add_header("Content-Type", "application/json")
        for key, value in self.headers.items():
            req.add_header(key, value)
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout, context=_ssl_context())
        except urllib.error.HTTPError as e:
            with e:
                text = e.read(4096).decode("utf-8", "replace").strip()
            hint = ""
            if e.code in (401, 403):
                hint = " (ComfyUI refused the request: it has no sign-in of its own, so check any proxy token in the headers)"
            raise ComfyError(f"ComfyUI answered HTTP {e.code}{hint}" + (f": {text[:800]}" if text else "")) from None
        except urllib.error.URLError as e:
            raise ComfyError(f"Could not reach ComfyUI at {self.base} ({e.reason}). Start it, or check the address "
                             "in Settings > Tools > Images.") from None
        except (TimeoutError, OSError) as e:
            raise ComfyError(f"ComfyUI at {self.base} did not answer ({e})") from None

    def _json(self, path: str, data: dict | None = None, timeout: float | None = None) -> dict | list:
        body = json.dumps(data).encode() if data is not None else None
        with self._open(path, body, timeout) as r:
            raw = r.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ComfyError(f"ComfyUI's answer on /{path} was larger than {MAX_JSON_BYTES >> 20} MB")
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            raise ComfyError(f"ComfyUI's answer on /{path} was not JSON") from None

    def system_stats(self, timeout: float | None = None) -> dict:
        return self._json("system_stats", timeout=timeout or 5.0)

    def object_info(self) -> dict:
        return self._json("object_info")

    def submit(self, workflow: dict, client_id: str) -> str:
        answer = self._json("prompt", {"prompt": workflow, "client_id": client_id})
        prompt_id = answer.get("prompt_id") if isinstance(answer, dict) else None
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ComfyError(f"ComfyUI returned no prompt_id: {json.dumps(answer)[:400]}")
        return prompt_id

    def queue(self) -> dict:
        answer = self._json("queue")
        ids = lambda value: [e[1] for e in value if isinstance(e, list) and len(e) > 1 and isinstance(e[1], str)]
        return {"running": ids(answer.get("queue_running") or []), "pending": ids(answer.get("queue_pending") or [])}

    def history(self, prompt_id: str) -> dict | None:
        answer = self._json(f"history/{urllib.parse.quote(prompt_id)}")
        entry = answer.get(prompt_id) if isinstance(answer, dict) else None
        return entry if isinstance(entry, dict) else None

    def view(self, output: dict) -> bytes:
        query = urllib.parse.urlencode({"filename": output["filename"], "subfolder": output.get("subfolder", ""),
                                        "type": output.get("type", "output")})
        with self._open(f"view?{query}", accept="*/*") as r:
            raw = r.read(MAX_IMAGE_BYTES + 1)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ComfyError(f"ComfyUI's image was larger than {MAX_IMAGE_BYTES >> 20} MB")
        if _sniff_image(raw) is None:
            raise ComfyError("ComfyUI returned something that is not a PNG, JPEG, WebP or GIF")
        return raw

    def upload(self, png: bytes, name: str) -> str:
        boundary = "----arya" + secrets.token_hex(12)
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
                f"Content-Type: {_sniff_image(png) or 'image/png'}\r\n\r\n").encode() + png + \
               f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n" \
               f"--{boundary}--\r\n".encode()
        url = f"{self.base}/upload/image"
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        req.add_header("Accept", "application/json")
        for key, value in self.headers.items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_context()) as r:
                raw = r.read(MAX_JSON_BYTES)
        except urllib.error.HTTPError as e:
            with e:
                text = e.read(2048).decode("utf-8", "replace").strip()
            raise ComfyError(f"ComfyUI refused the image upload (HTTP {e.code})" + (f": {text[:400]}" if text else "")) from None
        except urllib.error.URLError as e:
            raise ComfyError(f"Could not reach ComfyUI to upload the image ({e.reason})") from None
        try:
            answer = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            raise ComfyError("ComfyUI's upload answer was not JSON") from None
        stored = answer.get("name") if isinstance(answer, dict) else None
        if not isinstance(stored, str) or not stored:
            raise ComfyError("ComfyUI's upload returned no file name")
        subfolder = answer.get("subfolder") if isinstance(answer.get("subfolder"), str) else ""
        return f"{subfolder}/{stored}" if subfolder else stored

    def free_memory(self) -> None:
        """Ask ComfyUI to unload its weights (POST /free).  Its models reload from disk on the next picture, which is
        the price of giving the card back to the text engine."""
        try:
            with self._open("free", b'{"unload_models": true, "free_memory": true}', timeout=30) as r:
                r.read(1024)
        except ComfyError:
            pass

    def interrupt(self) -> None:
        with contextlib.suppress(ComfyError):
            self._json("interrupt", {})

    def queue_delete(self, prompt_ids: list[str]) -> None:
        with contextlib.suppress(ComfyError):
            self._json("queue", {"delete": list(prompt_ids)})

    def wait(self, prompt_id: str, cancel: threading.Event | None = None, poll: float = 0.5) -> dict:
        """Poll /history until the job has an output image; -> {output, queue_ms, exec_ms}.  ComfyCancelled on Stop."""
        submitted = time.monotonic()
        exec_started = None
        last_queue = 0.0
        while True:
            if cancel is not None and cancel.is_set():
                self.queue_delete([prompt_id])
                raise ComfyCancelled("cancelled")
            if exec_started is None and time.monotonic() - last_queue >= 1.0:
                last_queue = time.monotonic()
                with contextlib.suppress(ComfyError):
                    if prompt_id in self.queue()["running"]:
                        exec_started = time.monotonic()
            entry = self.history(prompt_id)
            if entry:
                status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
                if status.get("status_str") == "error":
                    detail = json.dumps(status.get("messages") or status)[:1200]
                    raise ComfyError(f"ComfyUI's workflow failed: {detail}")
                output = self._first_output(entry.get("outputs"))
                if output:
                    finished = time.monotonic()
                    start = exec_started or submitted
                    return {"output": output, "queue_ms": int((start - submitted) * 1000),
                            "exec_ms": int((finished - start) * 1000)}
                if status.get("completed") is True:
                    raise ComfyError("ComfyUI's workflow finished without an output image")
            if cancel is not None and cancel.is_set():
                with contextlib.suppress(ComfyError):
                    if prompt_id in self.queue()["pending"]:
                        self.queue_delete([prompt_id])
                    else:
                        self.interrupt()
                raise ComfyCancelled("cancelled")
            time.sleep(poll)

    @staticmethod
    def _first_output(outputs) -> dict | None:
        if not isinstance(outputs, dict):
            return None
        for node in outputs.values():
            images = node.get("images") if isinstance(node, dict) else None
            if not isinstance(images, list):
                continue
            for item in images:
                if isinstance(item, dict) and isinstance(item.get("filename"), str) and item["filename"]:
                    output = {"filename": item["filename"],
                              "subfolder": item.get("subfolder") if isinstance(item.get("subfolder"), str) else "",
                              "type": item.get("type") if isinstance(item.get("type"), str) else "output"}
                    if output["type"] == "output":
                        return output
        return None


# ------------------------------------------------------------------------------------------------ launcher
class ServerManager:
    """Start, stop and probe a ComfyUI on this machine.

    It only ever ends a python process whose command line runs ComfyUI's main.py on the configured port: whatever else
    holds that port (Tailscale does, on this host) is not ComfyUI, and killing it would break remote access.
    """

    START_TIMEOUT_S = 180.0
    STOP_TIMEOUT_S = 30.0
    POLL_S = 2.0

    def __init__(self, settings_provider, log=None):
        self._settings = settings_provider
        self.log = log
        self.busy = False
        self.child: subprocess.Popen | None = None

    def _say(self, text: str) -> None:
        print(f"[strata] {text}", flush=True)
        if self.log is not None:
            with contextlib.suppress(OSError, ValueError):
                self.log.write(f"[comfy] {text}\n")
                self.log.flush()

    def settings(self) -> dict:
        return self._settings()

    def probe(self) -> dict:
        """GET /system_stats: the ground truth for 'is ComfyUI answering'."""
        settings = self.settings()
        client = ComfyClient(settings["base_url"], settings["headers"], 10)
        try:
            stats = client.system_stats(timeout=5.0)
        except ComfyError:
            return {"up": False}
        system = stats.get("system") if isinstance(stats, dict) else {}
        devices = stats.get("devices") if isinstance(stats, dict) else None
        device = None
        if isinstance(devices, list) and devices and isinstance(devices[0], dict):
            device = {"name": devices[0].get("name"), "vram_free_mib": (devices[0].get("vram_free") or 0) >> 20,
                      "vram_total_mib": (devices[0].get("vram_total") or 0) >> 20}
        return {"up": True,
                "version": system.get("comfyui_version") if isinstance(system, dict) else None,
                "python": (system.get("python_version") or "").split(" ")[0] if isinstance(system, dict) else None,
                "device": device}

    def _port(self) -> str:
        try:
            parts = urllib.parse.urlsplit(self.settings()["base_url"])
        except ValueError:
            return "8188"
        return str(parts.port or (443 if parts.scheme == "https" else 80))

    def _log_dir(self) -> Path:
        d = ROOT / "local-data" / "comfyui"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _task_state(self, name: str) -> str | None:
        if os.name != "nt" or not name:
            return None
        run = subprocess.run(["schtasks", "/query", "/tn", name, "/fo", "LIST"], capture_output=True, text=True,
                             timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if run.returncode != 0:
            return None
        match = re.search(r"^Status:\s*(.+)$", run.stdout or "", re.I | re.M)
        return match.group(1).strip() if match else None

    def _task_run(self, verb: str, name: str) -> str | None:
        run = subprocess.run(["schtasks", f"/{verb}", "/tn", name], capture_output=True, text=True, timeout=20,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if run.returncode == 0:
            return None
        return ((run.stderr or run.stdout or "").strip() or f"schtasks /{verb} exited {run.returncode}")[:400]

    def _wait_task_idle(self, name: str, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self._task_state(name)
            if not state or "running" not in state.lower():
                return
            time.sleep(1.0)

    def _plan(self) -> dict:
        settings = self.settings()
        launch = settings["launch"]
        task = self._task_state(launch["task_name"])
        process_ready = bool(launch["python_exe"]) and bool(launch["server_dir"]) and \
            (Path(launch["server_dir"]) / "main.py").is_file()
        task_hint = f'scheduled task "{launch["task_name"]}"' + (f" ({task})" if task else " (not found)")
        process_hint = (f'main.py under {launch["server_dir"]}' if process_ready
                        else "no ComfyUI folder with main.py configured")
        if launch["mode"] == "scheduled-task":
            return {"launch": "scheduled-task", "hint": f"Using {task_hint}.", "task_state": task}
        if launch["mode"] == "process":
            return {"launch": "process", "hint": f"Using {process_hint}.", "task_state": task}
        if task:
            return {"launch": "scheduled-task", "hint": f"Auto: using {task_hint}.", "task_state": task}
        if process_ready:
            return {"launch": "process", "hint": f"Auto: using {process_hint}.", "task_state": task}
        return {"launch": "external", "hint": f"Auto: {task_hint} and {process_hint}; start ComfyUI yourself.",
                "task_state": task}

    def _pids(self) -> list[int]:
        """Python processes whose command line runs ComfyUI main.py on this port (never the Tailscale daemon)."""
        port = self._port()
        if os.name == "nt":
            script = ("$ErrorActionPreference='SilentlyContinue'\n"
                      "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" |\n"
                      "Where-Object { $_.CommandLine -and $_.CommandLine -match 'main\\.py' -and "
                      f"$_.CommandLine -match '{port}' }} |\n"
                      "ForEach-Object { $_.ProcessId }")
            run = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                                 timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if run.returncode != 0:
                return []
            return [int(x) for x in (run.stdout or "").split() if x.strip().isdigit()]
        run = subprocess.run(["pgrep", "-af", f"main.py.*{port}"], capture_output=True, text=True)
        if run.returncode != 0:
            return []
        out = []
        for line in (run.stdout or "").splitlines():
            first = line.split(None, 1)[0]
            if first.isdigit():
                out.append(int(first))
        return out

    def status(self) -> dict:
        probe = self.probe()
        local = is_local(self.settings()["base_url"])
        pids = self._pids() if local else []
        plan = self._plan()
        return {"up": probe["up"], "local": local,
                "managed": bool(self.child and self.child.pid in pids) if local else False,
                "pids": pids, "busy": self.busy, "launch": plan["launch"], "hint": plan["hint"],
                "task_state": plan.get("task_state"),
                "version": probe.get("version"), "python": probe.get("python"), "device": probe.get("device")}

    def start(self) -> dict:
        if self.busy:
            raise ComfyError("a ComfyUI server action is already running")
        settings = self.settings()
        if not is_local(settings["base_url"]):
            raise ComfyError("Start is available only for a ComfyUI on this machine; start the remote one there.")
        self.busy = True
        try:
            if self.probe()["up"]:
                return self.status()
            for pid in self._pids():                       # a leftover that holds the port but never answers
                self._say(f"ComfyUI is not answering but process {pid} still holds port {self._port()}; clearing it")
                self._kill(pid)
            plan = self._plan()
            if plan["launch"] == "scheduled-task":
                name = settings["launch"]["task_name"]
                failure = self._task_run("run", name)
                if failure and "already running" in failure.lower():
                    self._task_run("end", name)
                    self._wait_task_idle(name)
                    failure = self._task_run("run", name)
                if failure:
                    raise ComfyError(f'Could not start scheduled task "{name}": {failure}. Create it in Task Scheduler, '
                                     "or set the launch method to 'process' with a ComfyUI folder and python.")
                return self._wait_until_up()
            if plan["launch"] == "external":
                raise ComfyError(plan["hint"] + " Nothing to start automatically.")
            launch = settings["launch"]
            python = launch["python_exe"]
            folder = Path(launch["server_dir"])
            if not python or not Path(python).is_file():
                raise ComfyError(f"Python interpreter not found: {python or '(not set)'} - set it in Settings > Tools > Images")
            if not (folder / "main.py").is_file():
                raise ComfyError(f"ComfyUI main.py not found under {folder} - set the folder in Settings > Tools > Images")
            args = [python, "main.py", "--port", self._port(), *_extra_args(launch["extra_args"])]
            log = self._log_dir() / "comfyui.log"
            with open(log, "ab") as out:
                self.child = subprocess.Popen(args, cwd=str(folder), stdin=subprocess.DEVNULL, stdout=out,
                                              stderr=subprocess.STDOUT,
                                              creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) |
                                                            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            self._say(f"ComfyUI started from {folder} (pid {self.child.pid}); log {log}")
            return self._wait_until_up()
        finally:
            self.busy = False

    def stop(self) -> dict:
        if self.busy:
            raise ComfyError("a ComfyUI server action is already running")
        settings = self.settings()
        if not is_local(settings["base_url"]):
            raise ComfyError("Stop is available only for a ComfyUI on this machine; stop the remote one there.")
        self.busy = True
        try:
            if self._plan()["launch"] == "scheduled-task":
                name = settings["launch"]["task_name"]
                failure = self._task_run("end", name)
                if failure:
                    self._say(f'could not end scheduled task "{name}": {failure}')
                self._wait_task_idle(name)
            pids = self._pids()
            if self.child and self.child.pid and self.child.pid not in pids:
                pids.append(self.child.pid)
            for pid in pids:
                self._kill(pid)
            deadline = time.monotonic() + self.STOP_TIMEOUT_S
            while time.monotonic() < deadline:
                if not self._pids() and not self.probe()["up"]:
                    break
                time.sleep(1.0)
            self.child = None
            return self.status()
        finally:
            self.busy = False

    def restart(self) -> dict:
        self.stop()
        return self.start()

    @staticmethod
    def _kill(pid: int) -> None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            with contextlib.suppress(OSError):
                os.kill(pid, 15)

    def _wait_until_up(self) -> dict:
        deadline = time.monotonic() + self.START_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(self.POLL_S)
            if self.probe()["up"]:
                return self.status()
        tail = ""
        with contextlib.suppress(OSError):
            lines = (self._log_dir() / "comfyui.log").read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(lines[-12:]).strip()[:2000]
        raise ComfyError(f"ComfyUI did not answer within {int(self.START_TIMEOUT_S)} s."
                         + (f"\nLast output:\n{tail}" if tail else ""))


def _extra_args(text: str) -> list[str]:
    """Space-separated extra main.py arguments; quotes keep a grouped value together."""
    import shlex
    return shlex.split(text or "")


# ------------------------------------------------------------------------------------------------ the hub
IMAGE_TOOL_DESCRIPTION = (
    "Create or edit a picture with ComfyUI, the image engine on this PC. You write the image prompt yourself from what "
    "the user asks - subject, style, light, composition - in the language that fits the picture, and you pick the "
    "workflow by the shape and the job it is for. For an edit or a restyle of an existing picture in this room, pass "
    "its id as reference_id and an image-to-image workflow; naming an image-to-image workflow without reference_id "
    "edits the newest picture in the gallery. A reference_id with a text-to-image workflow fails, so pass both or "
    "neither.")
IMAGE_TOOL = {
    "name": "generate_image",
    "description": IMAGE_TOOL_DESCRIPTION,
    "parameters": {"type": "object", "properties": {
        "prompt": {"type": "string", "description": "The final image prompt you wrote: subject, style, light, "
                                                    "composition, and what to leave out."},
        "workflow": {"type": "string", "description": "The workflow to run; pick the one whose size and role fit."},
        "count": {"type": "integer", "description": f"How many variants, 1 to {MAX_COUNT} (default 1)."},
        "reference_id": {"type": "string", "description": "The id of an image in this room's gallery to edit or "
                                                          "restyle; needs an image-to-image workflow."},
    }, "required": ["prompt"]},
}


class ComfyHub:
    """The ComfyUI side of the page: settings, workflows, jobs, the gallery, and the chat's generate_image tool."""

    def __init__(self, settings: dict, svc=None, log=None, shipped: str | Path = SHIPPED_DIR,
                 settings_path: str | Path | None = None):
        self.settings = normalize(settings)
        self.svc = svc
        self.log = log
        self.name, self.source = "images", "comfyui"
        self.policy = self.settings["free_vram"]["policy"]
        self.reload = "lazy"
        self.cfg = {"uma": False}
        self.shipped = Path(shipped)
        self.settings_path = Path(settings_path) if settings_path else None
        # under local-data wherever the settings file is: the app's own data folder, never beside the source
        gallery_root = (self.settings_path.parent if self.settings_path else ROOT) / "local-data"
        gallery_dir = gallery_root / "image-gallery"
        self.gallery = Gallery(gallery_dir, self.settings["gallery"], log=log)
        self.dir = self.gallery.dir
        self.manager = ServerManager(lambda: self.settings, log=log)
        self.jobs: dict[str, dict] = {}
        self.lock = threading.RLock()
        self._reach: dict | None = None

    def reach(self, max_age: float = 5.0) -> dict:
        """Is ComfyUI answering?  Cached for a few seconds: /health and the dialog both ask."""
        now = time.monotonic()
        with self.lock:
            if self._reach and now - self._reach["at"] < max_age:
                return self._reach
        probe = self.manager.probe()
        with self.lock:
            self._reach = {"at": now, "up": bool(probe.get("up")), "version": probe.get("version")}
            return self._reach

    # ------------------------------------------------------------------ small pieces
    def _say(self, text: str) -> None:
        print(f"[strata] {text}", flush=True)
        if self.log is not None:
            with contextlib.suppress(OSError, ValueError):
                self.log.write(f"[comfy] {text}\n")
                self.log.flush()

    def need_mib(self, job: dict) -> int:
        return int(self.settings["free_vram"]["need_mib"])

    def free_memory(self) -> None:
        """Give the GPU back to the text engine: ComfyUI's weights come out of VRAM when this machine is the one
        running both, and come back from disk on the next picture.  Another machine's ComfyUI is left alone."""
        if self.configured() and is_local(self.settings["base_url"]):
            self.client(30).free_memory()

    def configured(self) -> bool:
        return bool(self.settings.get("base_url"))

    def client(self, timeout_s: float | None = None) -> ComfyClient:
        return ComfyClient(self.settings["base_url"], self.settings["headers"],
                           timeout_s or self.settings["timeout_s"])

    def workflows(self) -> list[dict]:
        imported = imported_dir(self.settings_path) if self.settings_path else ROOT / "local-data" / IMPORTED_DIRNAME
        return load_workflows(self.shipped, imported)

    def save(self, raw: dict) -> dict:
        """Check and store the settings; the live hub adopts them at once."""
        current = self.settings
        merged = normalize(merge_secrets(raw, current))
        if self.settings_path is not None:
            write_settings(self.settings_path, merged)
        self.settings = merged
        self.policy = merged["free_vram"]["policy"]
        self.gallery.settings = merged["gallery"]
        return merged

    # ------------------------------------------------------------------ status and check
    def status(self) -> dict:
        workflows = self.workflows()
        server = self.manager.status()
        with self.lock:
            self._reach = {"at": time.monotonic(), "up": bool(server.get("up")), "version": server.get("version")}
        return {"configured": self.configured(), "reachable": server["up"], "version": server.get("version"),
                "device": server.get("device"), "server": server,
                "settings": public_settings(self.settings), "workflows": workflows,
                "gallery": self.gallery.status(), "jobs": [self.job_view(j) for j in self._recent_jobs()]}

    def check(self) -> dict:
        """Name what is missing before a run fails: node classes from /object_info, model files from its enums."""
        try:
            client = self.client(30)
            info = client.object_info()
            stats = client.system_stats(timeout=10)
        except ComfyError as e:
            raise ComfyError(str(e)) from None
        classes = set(info.keys()) if isinstance(info, dict) else set()
        workflows = self.workflows()
        results = []
        for wf in workflows:
            try:
                data = _parse_workflow(_read_workflow(Path(wf["path"])))
            except (WorkflowError, OSError) as e:
                results.append({"name": wf["name"], "role": wf["role"], "ok": False,
                                "missing_nodes": [], "missing_models": [], "error": str(e)})
                continue
            missing_nodes, missing_models = [], []
            for node_id, node in data.items():
                if not isinstance(node, dict):
                    continue
                kind = node.get("class_type")
                inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
                if isinstance(kind, str) and kind not in classes:
                    missing_nodes.append(f"{kind} (node {node_id})")
                    continue
                for field, value in inputs.items():
                    if not isinstance(value, str) or not value or (value.startswith("{{") and value.endswith("}}")):
                        continue                        # a placeholder is not a file name
                    choices = _enum_choices(info, kind, field)
                    if choices is not None and value not in choices:
                        missing_models.append(f"{value} ({kind}.{field})")
            results.append({"name": wf["name"], "role": wf["role"], "ok": not missing_nodes and not missing_models,
                            "missing_nodes": missing_nodes, "missing_models": missing_models, "error": ""})
        system = stats.get("system") if isinstance(stats, dict) else {}
        return {"ok": True, "version": system.get("comfyui_version") if isinstance(system, dict) else None,
                "workflows": results}

    def import_workflow(self, name: str, text: str) -> dict:
        """Validate one API-format graph and keep it beside the settings file under `name`."""
        name = str(name or "").strip()
        if not NAME_PATTERN.match(name):
            raise WorkflowError("a workflow name is 1-64 letters, digits, spaces, '.', '_' or '-'")
        if any(w["name"] == name for w in self.workflows() if w["source"] == "shipped"):
            raise WorkflowError(f"{name!r} is the name of a shipped workflow; give this one another name")
        data = _parse_workflow(text)
        folder = imported_dir(self.settings_path) if self.settings_path else ROOT / "local-data" / IMPORTED_DIRNAME
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{name}.json"
        target.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
        self.settings["imported"] = sorted({*self.settings.get("imported", []), name})
        if self.settings_path is not None:
            write_settings(self.settings_path, self.settings)
        return {"name": name, **describe(data)}

    def remove_workflow(self, name: str) -> dict:
        if any(w["name"] == name and w["source"] == "shipped" for w in self.workflows()):
            raise WorkflowError(f"{name!r} is shipped with AryaInfer and cannot be removed")
        folder = imported_dir(self.settings_path) if self.settings_path else ROOT / "local-data" / IMPORTED_DIRNAME
        target = folder / f"{name}.json"
        if not target.is_file():
            raise WorkflowError(f"there is no imported workflow named {name!r}")
        target.unlink()
        self.settings["imported"] = [n for n in self.settings.get("imported", []) if n != name]
        for key in ("active_text", "active_edit"):
            if self.settings.get(key) == name:
                self.settings[key] = ""
        if self.settings_path is not None:
            write_settings(self.settings_path, self.settings)
        return {"name": name}

    # ------------------------------------------------------------------ jobs
    def _recent_jobs(self, limit: int = 8) -> list[dict]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.get("started", 0), reverse=True)
        return jobs[:limit]

    @staticmethod
    def job_view(job: dict) -> dict:
        view = {k: job.get(k) for k in ("id", "state", "prompt", "workflow", "count", "seed", "error",
                                        "started", "finished", "queue_ahead")}
        view["images"] = job.get("images") or []
        return view

    def job(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return self.job_view(job) if job else None

    def start_job(self, spec: dict) -> dict:
        """Begin one generation; the page polls GET /comfy?job=<id>."""
        job = {"id": secrets.token_hex(8), "state": "queued", "started": time.time(), "finished": None,
               "prompt": str(spec.get("prompt") or ""), "workflow": str(spec.get("workflow") or ""),
               "count": int(spec.get("count") or 1), "seed": None, "images": [], "error": None,
               "cancel": threading.Event()}
        with self.lock:
            self.jobs[job["id"]] = job
            for old in sorted(self.jobs.values(), key=lambda j: j.get("started", 0))[:-20]:
                self.jobs.pop(old["id"], None)
        thread = threading.Thread(target=self._run_job, args=(job, spec), daemon=True, name=f"comfy-{job['id']}")
        view = self.job_view(job)
        thread.start()
        return view

    def _run_job(self, job: dict, spec: dict) -> None:
        job["state"] = "running"
        try:
            result = self.generate(spec, cancel=job["cancel"], take_turn=True)
            job.update(state="done", images=result["images"], seed=result["seed"],
                       workflow=result["workflow"], finished=time.time())
        except ComfyCancelled:
            job.update(state="cancelled", error="cancelled", finished=time.time())
        except (ComfyError, WorkflowError) as e:
            job.update(state="error", error=str(e), finished=time.time())
        except Exception as e:                                   # noqa: BLE001 - never lose the sentence
            job.update(state="error", error=f"{type(e).__name__}: {e}", finished=time.time())
        if job["state"] != "done":
            self._say(f"ComfyUI job failed: {job['error']}")

    def cancel_job(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            job["cancel"].set()
        return self.job_view(job)

    # ------------------------------------------------------------------ generation
    def _references(self, spec: dict) -> list[tuple[bytes, str]]:
        """The source images of an edit, as (png bytes, upload name)."""
        out = []
        for ref in spec.get("references") or []:
            if not isinstance(ref, dict):
                raise WorkflowError("a reference is a gallery image id or a data URL")
            if ref.get("id"):
                record = self.gallery.get(str(ref["id"]))
                if record is None:
                    raise WorkflowError(f"there is no image {ref['id']!r} in the gallery")
                path = self.gallery.file(record["file"])
                if path is None:
                    raise WorkflowError(f"the image file for {ref['id']!r} is gone")
                out.append((path.read_bytes(), "arya-ref.png"))
                continue
            url = str(ref.get("data_url") or "")
            match = re.match(r"^data:image/(png|jpeg|webp);base64,(.+)$", url, re.S)
            if not match:
                raise WorkflowError("a reference is a gallery image id or a data: URL of a PNG, JPEG or WebP")
            try:
                png = base64.b64decode(match.group(2), validate=True)
            except (ValueError, TypeError):
                raise WorkflowError("that reference is not valid base64") from None
            if len(png) > MAX_IMAGE_BYTES:
                raise WorkflowError(f"a reference image is at most {MAX_IMAGE_BYTES >> 20} MB")
            if _sniff_image(png) is None:
                raise WorkflowError("a reference must be a PNG, JPEG, WebP or GIF")
            out.append((png, f"arya-ref.{match.group(1).replace('jpeg', 'jpg')}"))
        if len(out) > MAX_REFERENCES:
            raise WorkflowError(f"at most {MAX_REFERENCES} reference images")
        return out

    def _pick_workflow(self, spec: dict, editing: bool) -> dict:
        workflows = self.workflows()
        role = "image-to-image" if editing else "text-to-image"
        name = str(spec.get("workflow") or "").strip()
        if not name:
            name = self.settings.get("active_edit" if editing else "active_text") or ""
        if name:
            return find_workflow(workflows, name, role)
        mine = [w for w in workflows if w["role"] == role]
        if not mine:
            raise WorkflowError(f"No {role} workflow is configured. Import one in Settings > Tools > Images"
                                + (" (a graph with an {{image}} or {{images}} input)." if editing else "."))
        # the shipped pack's own order by usefulness: Square for text, Turbo Edit for edits, not a cut-out graph
        def score(w: dict) -> tuple:
            n = w["name"].lower()
            if editing:
                return (0 if "turbo_edit" in n else 1 if "background" in n else 2, n)
            return (0 if "square" in n else 1 if "wide" in n else 2 if "portrait" in n else 3, n)
        return sorted(mine, key=score)[0]

    def generate(self, spec: dict, cancel: threading.Event | None = None, take_turn: bool | None = None) -> dict:
        """Run one generation to completion -> {images, seed, workflow, elapsed_ms}.  ComfyError when it fails."""
        prompt = str(spec.get("prompt") or "").strip()
        if not prompt:
            raise WorkflowError("the prompt is empty")
        count = int(spec.get("count") or 1)
        if not 1 <= count <= MAX_COUNT:
            raise WorkflowError(f"count must be 1 to {MAX_COUNT}")
        references = self._references(spec)
        named = str(spec.get("workflow") or "").strip()
        if named and not references:
            # the model asked for an edit without saying which picture: say both halves of the rule, it retries at once
            try:
                bare = find_workflow(self.workflows(), named)
            except WorkflowError:
                bare = None
            if bare and bare["role"] == "image-to-image":
                raise WorkflowError(f"{bare['name']!r} edits a picture: pass reference_id as well (the id of the "
                                    "picture to change), or pick a text-to-image workflow to make a new one")
        workflow = self._pick_workflow(spec, bool(references))
        if references and workflow["role"] != "image-to-image":
            raise WorkflowError(f"{workflow['name']!r} does not edit; with reference_id pass an image-to-image "
                                "workflow")
        graph_text = _read_workflow(Path(workflow["path"]))
        seed = spec.get("seed")
        seed = int(seed) if isinstance(seed, (int, float)) and not isinstance(seed, bool) else secrets.randbelow(1 << 32)
        client = self.client()
        if take_turn is None:
            take_turn = bool(spec.get("take_turn", True))
        started = time.monotonic()
        uploaded = [client.upload(png, name) for png, name in references]
        images = []
        used = []
        try:
            with (gpu_turn_or_null(self.svc, self, {"width": spec.get("width") or DEFAULT_CANVAS,
                                                    "height": spec.get("height") or DEFAULT_CANVAS,
                                                    "need_mib": self.need_mib({})},
                                   cancel, take_turn) as _policy):
                for index in range(count):
                    if cancel is not None and cancel.is_set():
                        raise ComfyCancelled("cancelled")
                    item_seed = seed + index
                    prepared = prepare(graph_text, prompt=prompt, seed=item_seed,
                                       width=spec.get("width"), height=spec.get("height"),
                                       image=uploaded[0] if uploaded else None,
                                       images=uploaded or None)
                    prompt_id = client.submit(prepared, secrets.token_hex(16))
                    used.append(prompt_id)
                    waited = client.wait(prompt_id, cancel)
                    png = client.view(waited["output"])
                    actual_w, actual_h = _png_size(png)
                    record = self.gallery.add(png, {
                        "prompt": prompt, "workflow": workflow["name"], "provider": "comfyui", "seed": item_seed,
                        "width": actual_w or spec.get("width"), "height": actual_h or spec.get("height"),
                        "source": spec.get("source") or ("edit" if uploaded else "generate"),
                        "parent": spec.get("parent") or None,
                        "queue_ms": waited["queue_ms"], "exec_ms": waited["exec_ms"],
                        "comfy_version": (self.manager.probe() or {}).get("version")})
                    images.append(self.image_view(record))
        finally:
            if cancel is not None and cancel.is_set():
                client.queue_delete(used)
        elapsed = int((time.monotonic() - started) * 1000)
        return {"images": images, "seed": seed, "workflow": workflow["name"], "elapsed_ms": elapsed}

    @staticmethod
    def image_view(record: dict) -> dict:
        return {"id": record["id"], "url": f"/comfy/files/{record['file']}",
                "prompt": record.get("prompt"), "workflow": record.get("workflow"), "seed": record.get("seed"),
                "width": record.get("width"), "height": record.get("height"),
                "created": record.get("created"), "favorite": bool(record.get("favorite"))}

    def upload_image(self, data_url: str, prompt: str = "") -> dict:
        """Keep a pasted or dropped picture as a gallery item (a reference for an edit)."""
        png, _ = self._references({"references": [{"data_url": data_url}]})[0]
        record = self.gallery.add(png, {"prompt": prompt, "source": "upload", "provider": "comfyui"})
        return self.image_view(record)

    # ------------------------------------------------------------------ the chat tool
    def tools(self) -> list[dict]:
        """The chat's image tool, with this server's workflows and their sizes written into the description: the model
        picks the graph, so it has to know what there is to pick."""
        workflows = self.workflows() if self.configured() else []
        if not workflows:
            return []
        parts = []
        for w in workflows:
            if w.get("baked_size"):
                shape = f"{w['baked_size']['width']}x{w['baked_size']['height']}"
            else:
                shape = "the source's size"
            parts.append(f"{w['name']} ({w['role'].replace('-', ' ')}, {shape})")
        tool = json.loads(json.dumps(IMAGE_TOOL))
        tool["description"] = (IMAGE_TOOL_DESCRIPTION + " Workflows here: " + "; ".join(parts) + "."
                                + f" Pass the workflow name exactly. Leave it out only when the square default is right.")
        tool["parameters"]["properties"]["workflow"]["description"] = (
            "One of: " + ", ".join(w["name"] for w in workflows) + ".")
        return [tool]

    def routes(self) -> dict:
        return {t["name"]: (self, t["name"]) for t in self.tools()}

    def template_tools(self, exclude=()) -> list[dict]:
        return [{"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
                for t in self.tools() if t["name"] not in exclude]

    def openai_tools(self) -> list[dict]:
        return [{"type": "function", "function": t} for t in self.template_tools()]

    def wait(self, timeout: float | None = None) -> None:
        return None

    def close(self) -> None:
        return None

    def call(self, name: str, arguments: dict, cancel=None) -> dict:
        """One tool call from the chat loop: generate the image(s) and answer with their addresses."""
        started = time.monotonic()
        arguments = arguments if isinstance(arguments, dict) else {}
        try:
            if name != IMAGE_TOOL["name"]:
                raise WorkflowError(f"there is no tool named {name!r}")
            reference = str(arguments.get("reference_id") or "").strip()
            named = str(arguments.get("workflow") or "").strip()
            borrowed = None
            if not reference and named:
                # "change the last picture" is well defined for this room even when the page has lost its thread (a
                # phone that evicted its storage, a reload): the gallery is on the server and is the record.  Only an
                # image-to-image call borrows it - a text-to-image graph must never edit something by surprise.
                try:
                    asked = find_workflow(self.workflows(), named)
                except WorkflowError:
                    asked = None
                if asked is not None and asked["role"] == "image-to-image":
                    newest = self.gallery.list(limit=1)["items"]
                    if newest:
                        reference, borrowed = newest[0]["id"], newest[0]
            result = self.generate({"prompt": arguments.get("prompt"), "count": arguments.get("count") or 1,
                                    "workflow": arguments.get("workflow"), "source": "chat",
                                    "references": [{"id": reference}] if reference else []},
                                   cancel=cancel, take_turn=False)
            lines = [f"Generated {len(result['images'])} image(s) with {result['workflow']} (seed {result['seed']})."]
            if borrowed is not None:
                made = borrowed.get("prompt") or "the previous picture"
                lines.append(f"Edited the newest picture in the gallery, id {borrowed['id']} ({made[:80]}).")
            for image in result["images"]:
                lines.append(f"{image['url']}")
            text = "\n".join(lines)
            return {"server": self.name, "tool": name, "ok": True, "text": text, "chars": len(text),
                    "truncated": False, "ms": int((time.monotonic() - started) * 1000), "images": result["images"]}
        except ComfyCancelled:
            raise
        except (ComfyError, WorkflowError) as e:
            text = f"error: {e}"
            return {"server": self.name, "tool": name, "ok": False, "text": text, "chars": len(text),
                    "truncated": False, "ms": int((time.monotonic() - started) * 1000), "images": []}
        except Exception as e:                                   # noqa: BLE001 - the model reads the sentence
            text = f"error: {type(e).__name__}: {e}"
            return {"server": self.name, "tool": name, "ok": False, "text": text, "chars": len(text),
                    "truncated": False, "ms": int((time.monotonic() - started) * 1000), "images": []}


def gpu_turn_or_null(svc, owner, job: dict, cancel, take_turn: bool):
    """The GPU turn when a service is attached (the server), else a no-op context (unit tests, tools without one)."""
    if svc is None:
        return _null_turn()
    from serve.gputurn import gpu_turn
    return gpu_turn(svc, owner, job, cancel, take_turn=take_turn)


@contextlib.contextmanager
def _null_turn():
    yield "keep"


def _enum_choices(info: dict, node: str, field: str) -> list | None:
    """ComfyUI's allowed values for one input, when it is an enum."""
    node_info = info.get(node) if isinstance(info, dict) else None
    inputs = node_info.get("input") if isinstance(node_info, dict) else None
    required = inputs.get("required") if isinstance(inputs, dict) else None
    spec = required.get(field) if isinstance(required, dict) else None
    if isinstance(spec, list) and spec and isinstance(spec[0], list):
        return [str(x) for x in spec[0]]
    return None
