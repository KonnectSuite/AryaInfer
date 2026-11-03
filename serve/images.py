"""serve/images.py - image generation (Qwen-Image-2.1-Turbo) through stable-diffusion.cpp's sd-cli.

POST /v1/images/generations takes OpenAI's request shape (prompt, size, n, response_format b64_json|url) plus AryaStrata's
own fields seed and steps.  Each request runs one `sd-cli` process with the arguments the model's card gives for
stable-diffusion.cpp (8 steps, CFG 1, euler, Turbo's sigmas, --diffusion-fa) and returns the PNG files that process
wrote, unchanged: an image from the API is byte for byte the image plain sd-cli writes with the same arguments.

The GPU is shared with the text engine one job at a time: an image job takes the service's turn (the FIFO every chat
request takes), so no chat turn runs on the GPU meanwhile, and the config's "gpu_policy" says what happens to the
text engine during the job (gpu_turn):
  keep    - it stays loaded and idle (an APU's shared memory, a card with room for both)
  shrink  - an engine started with --vram-elastic gives the image job VRAM from its expert cache and takes it back
            afterwards (POST /v1/vram's mechanism; the conversation stays in the engine)
  unload  - its conversation is saved to a session file, the engine is stopped, and the next start restores it
  auto    - (default) keep when there is room for the image job next to it, else shrink when the engine can,
            else unload
The process per request keeps nothing on the GPU between images: when the job ends, all of its memory is free again.

The config's "images" section (written by setup --images, tools/image/install.py):
  {"exe": "engine-image/sd-cli", "backend": "vulkan", "diffusion_model": "...Q8_0.gguf", "vae": "...",
   "llm": "...Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf", "quant": "Q8_0", "args": ["--diffusion-fa"],
   "gpu_policy": "auto", "reload": "lazy"|"eager", "max_n": 4, "max_side": 2048, "timeout_s": 3600,
   "lib_dirs": [...], "uma": false, "need_mib": null, "out_dir": null, "keep_files": 64,
   "native": false}   (native: AryaStrata's own DiT runner, tools/image/sdcpp_native; CUDA / HIP builds)
"""
from __future__ import annotations

import base64
import contextlib
import os
import random
import re
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# Qwen-Image-2.1-Turbo's own schedule (model_index.json "sample_sigmas") plus the terminal 0, as Unsloth's card passes
# it to sd-cli; it is an 8-step schedule, so another step count leaves the schedule to sd.cpp
TURBO_SIGMAS = "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0"
TURBO_STEPS = 8
MODEL_NAME = "qwen-image-2.1-turbo"
POLICIES = ("auto", "keep", "shrink", "unload")
SIZE_STEP = 32                     # sd.cpp's Qwen-Image-2.1 docs: dimensions divisible by 32
MIN_SIDE = 256
FILE_NAME = re.compile(r"^[0-9a-f]{32}\.png$")
STEP_LINE = re.compile(r"\|\s*(\d+)/(\d+)\s*-")      # sd.cpp's progress bar: "|====    | 3/8 - 14.1s/it"


class ImageRequestError(ValueError):
    """A request the image endpoint refuses (400)."""


class ImageJobFailed(RuntimeError):
    """sd-cli ended without the images (500); the message carries the end of its log."""


def parse_size(value, max_side: int) -> tuple[int, int]:
    """OpenAI's size, "1024x1024" (or "auto": 1024x1024) -> (width, height); each side a multiple of 32 from 256 to
    max_side."""
    if value is None or value == "auto":
        return 1024, 1024
    if not isinstance(value, str):
        raise ImageRequestError("size: a string WIDTHxHEIGHT, e.g. \"1024x1024\"")
    m = re.fullmatch(r"\s*(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*", value)
    if not m:
        raise ImageRequestError(f"size: WIDTHxHEIGHT, e.g. \"1024x1024\", not {value!r}")
    w, h = int(m.group(1)), int(m.group(2))
    for side in (w, h):
        if side < MIN_SIDE or side > max_side or side % SIZE_STEP:
            raise ImageRequestError(f"size {w}x{h}: each side a multiple of {SIZE_STEP} from {MIN_SIDE} to {max_side}")
    return w, h


def _int_field(req: dict, key: str, lo: int, hi: int, default):
    v = req.get(key)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ImageRequestError(f"{key}: a whole number from {lo} to {hi}")
    return v


def parse_request(req: dict, cfg: dict) -> dict:
    """The fields of one /v1/images/generations request, checked.  Unknown OpenAI fields (quality, style, user,
    background, moderation) are accepted and ignored; an output format other than PNG is refused."""
    prompt = req.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ImageRequestError("prompt: a non-empty string")
    if len(prompt) > 16000:
        raise ImageRequestError("prompt: at most 16000 characters")
    if "\0" in prompt:
        raise ImageRequestError("prompt: no NUL characters")
    fmt = req.get("response_format") or "b64_json"
    if fmt not in ("b64_json", "url"):
        raise ImageRequestError("response_format: b64_json or url")
    out_fmt = req.get("output_format")
    if out_fmt not in (None, "png"):
        raise ImageRequestError("output_format: only png")
    w, h = parse_size(req.get("size"), int(cfg.get("max_side") or 2048))
    n = _int_field(req, "n", 1, int(cfg.get("max_n") or 4), 1)
    steps = _int_field(req, "steps", 1, 100, int(cfg.get("steps") or TURBO_STEPS))
    seed = _int_field(req, "seed", 0, 2**62, None)
    if seed is None:
        seed = random.SystemRandom().randrange(0, 2**31)
    return {"prompt": prompt, "width": w, "height": h, "n": n, "steps": steps, "seed": seed, "response_format": fmt}


def sd_cli_args(cfg: dict, job: dict, out_pattern: str) -> list[str]:
    """The sd-cli command for one job: the model card's stable-diffusion.cpp command (8 steps, CFG 1, euler, Turbo's
    sigmas, --diffusion-fa from the config's args), the size, seed and batch count, and the config's other args."""
    cmd = [str(cfg["exe"]),
           "--diffusion-model", str(cfg["diffusion_model"]), "--vae", str(cfg["vae"]), "--llm", str(cfg["llm"]),
           "-p", job["prompt"],
           "--steps", str(job["steps"]), "--cfg-scale", "1.0", "--sampling-method", "euler",
           "-W", str(job["width"]), "-H", str(job["height"])]
    if job["steps"] == TURBO_STEPS:
        cmd += ["--sigmas", str(cfg.get("sigmas") or TURBO_SIGMAS)]
    cmd += ["-s", str(job["seed"])]
    if job["n"] > 1:
        cmd += ["-b", str(job["n"])]
    cmd += ["-o", out_pattern]
    cmd += [str(a) for a in (cfg.get("args") or [])]
    if cfg.get("native") is True:                   # AryaStrata's DiT runner inside sd-cli (CUDA / HIP builds)
        cmd += ["--model-args", "qwen_image_2_1_native=1"]
    return cmd


def image_env(cfg: dict, base: dict | None = None) -> dict:
    """sd-cli's environment: the libraries its backend needs (ROCm's, setup's lib_dirs) first on the search path, the
    GPU to use when the config names one, and the config's own "env"."""
    env = dict(os.environ if base is None else base)
    dirs = [str(d) for d in cfg.get("lib_dirs") or [] if Path(d).is_dir()]
    if dirs:
        var = "PATH" if os.name == "nt" else "LD_LIBRARY_PATH"
        env[var] = os.pathsep.join(dirs + ([env[var]] if env.get(var) else []))
    gpu = cfg.get("gpu")
    if gpu is not None:
        var = {"cuda": "CUDA_VISIBLE_DEVICES", "hip": "HIP_VISIBLE_DEVICES",
               "vulkan": "GGML_VK_VISIBLE_DEVICES"}.get(cfg.get("backend"))
        if var:
            env[var] = str(gpu)
            if var == "CUDA_VISIBLE_DEVICES":
                env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    for k, v in (cfg.get("env") or {}).items():
        env[str(k)] = str(v)
    return env


def need_mib(cfg: dict, width: int, height: int) -> int:
    """The GPU memory an image job is planned with: the three model files plus the working buffers (about 2 GiB plus
    4 GiB per megapixel at Turbo's settings; the 780M baseline peaked 7.4 GB over the weights at 1024x1024 on HIP);
    the config's "need_mib" overrides it."""
    if cfg.get("need_mib"):
        return int(cfg["need_mib"])
    files = 0
    for k in ("diffusion_model", "vae", "llm"):
        try:
            files += Path(cfg[k]).stat().st_size
        except (OSError, KeyError, TypeError):
            pass
    work = (2 << 30) + int(4 * (1 << 30) * width * height / (1024 * 1024))
    return (files + work) >> 20


class ImageGen:
    """One sd-cli process per request, one request at a time (the service's turn, gpu_turn)."""

    def __init__(self, cfg: dict, log=None):
        self.cfg = dict(cfg)
        policy = self.cfg.get("gpu_policy") or "auto"
        if policy not in POLICIES:
            raise ValueError(f'images "gpu_policy" must be one of {", ".join(POLICIES)}, not {policy!r}')
        reload = self.cfg.get("reload") or "lazy"
        if reload not in ("lazy", "eager"):
            raise ValueError(f'images "reload" must be lazy or eager, not {reload!r}')
        for k in ("exe", "diffusion_model", "vae", "llm"):
            if not isinstance(self.cfg.get(k), str) or not self.cfg[k]:
                raise ValueError(f'the config\'s "images" section needs "{k}" (run setup with --images again)')
        self.policy, self.reload = policy, reload
        self.model = self.cfg.get("model_name") or MODEL_NAME
        self.log = log
        out = self.cfg.get("out_dir")
        self.dir = Path(out) if out else Path(tempfile.mkdtemp(prefix="strata-images-"))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.keep_files = int(self.cfg.get("keep_files") or 64)
        self.lock = threading.Lock()              # one sd-cli at a time even when the service's turn is not taken
        self.totals = {"images": 0, "jobs": 0, "seconds": 0.0, "failed": 0}
        self.last = None                           # the last job's figures (/v1/status)
        self.progress = None                       # (step, steps) of the running job

    def missing(self) -> list[str]:
        return [self.cfg[k] for k in ("exe", "diffusion_model", "vae", "llm") if not Path(self.cfg[k]).exists()]

    def need_mib(self, job: dict) -> int:
        """What the GPU turn should reserve for this job: the model files plus the working buffers."""
        return need_mib(self.cfg, job["width"], job["height"])

    def _say(self, text: str) -> None:
        print(f"[strata] {text}", flush=True)
        if self.log is not None:
            try:
                self.log.write(f"[images] {text}\n")
                self.log.flush()
            except (OSError, ValueError):
                pass

    def _prune(self) -> None:
        """Keep the newest keep_files PNGs of response_format url (the oldest go)."""
        files = sorted((p for p in self.dir.glob("*.png") if FILE_NAME.match(p.name)), key=lambda p: p.stat().st_mtime)
        for p in files[:max(0, len(files) - self.keep_files)]:
            with contextlib.suppress(OSError):
                p.unlink()

    def file(self, name: str) -> Path | None:
        """A stored image (response_format url) by its name, or None."""
        if not FILE_NAME.match(name or ""):
            return None
        p = self.dir / name
        return p if p.is_file() else None

    def run(self, job: dict, cancel: threading.Event | None = None) -> tuple[list[bytes], dict]:
        """Run sd-cli for `job` (parse_request's dict) -> (the PNG files' bytes in order, figures).  The caller holds
        the GPU turn.  ImageJobFailed when sd-cli fails, times out or is cancelled."""
        work = Path(tempfile.mkdtemp(prefix="job-", dir=self.dir))
        pattern = str(work / "img_%d.png")
        cmd = sd_cli_args(self.cfg, job, pattern)
        timeout = float(self.cfg.get("timeout_s") or 3600)
        logf = work / "sd-cli.log"
        t0 = time.monotonic()
        self.progress = (0, job["steps"])
        with self.lock:
            with open(logf, "w", encoding="utf-8", errors="replace") as lf:
                try:
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, env=image_env(self.cfg),
                                            cwd=str(work), text=True, errors="replace", bufsize=1)
                except OSError as e:
                    raise ImageJobFailed(f"sd-cli did not start ({cmd[0]}): {e}") from e
                try:
                    from serve.winjob import contain
                    contain(proc)                 # ends with the server (Windows)
                except Exception:
                    pass
                why = None

                def pump():
                    for line in proc.stdout:
                        lf.write(line)
                        m = STEP_LINE.search(line)
                        if m:
                            self.progress = (int(m.group(1)), int(m.group(2)))
                reader = threading.Thread(target=pump, daemon=True)
                reader.start()
                while proc.poll() is None:
                    if cancel is not None and cancel.is_set():
                        why = "cancelled (the client left)"
                    elif time.monotonic() - t0 > timeout:
                        why = f"it ran past timeout_s ({timeout:g} s)"
                    if why:
                        proc.kill()
                        break
                    time.sleep(0.2)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=30)
                reader.join(timeout=10)
        secs = time.monotonic() - t0
        self.progress = None
        log = logf.read_text(encoding="utf-8", errors="replace")
        outs = [work / f"img_{i}.png" for i in range(job["n"])]
        try:
            if why or proc.returncode != 0 or not all(p.is_file() for p in outs):
                self.totals["failed"] += 1
                tail = "\n".join(log.strip().splitlines()[-12:])
                what = why or (f"sd-cli exited with code {proc.returncode}" if proc.returncode
                               else "sd-cli wrote no image")
                self._say(f"image job failed: {what}\n{tail}")
                raise ImageJobFailed(f"{what}; the end of its log:\n{tail}")
            images = [p.read_bytes() for p in outs]
        finally:
            for p in work.iterdir():
                with contextlib.suppress(OSError):
                    p.unlink()
            with contextlib.suppress(OSError):
                work.rmdir()
        figures = {"seconds": round(secs, 2), "steps": job["steps"], "n": job["n"],
                   "size": f"{job['width']}x{job['height']}", "seed": job["seed"],
                   "backend": self.cfg.get("backend"), "quant": self.cfg.get("quant")}
        for key, pat in (("text_encode_ms", r"get_learned_condition completed, taking ([0-9.]+) ?ms"),
                         ("sampling_s", r"sampling completed, taking ([0-9.]+) ?s"),
                         ("vae_decode_s", r"decode_first_stage completed, taking ([0-9.]+) ?s")):
            m = re.findall(pat, log)
            if m:
                figures[key] = float(m[-1])
        self.totals["jobs"] += 1
        self.totals["images"] += job["n"]
        self.totals["seconds"] += secs
        self.last = figures
        return images, figures

    def store(self, data: bytes) -> str:
        """Keep one PNG for response_format url -> its file name (32 random hex digits: the name is the access)."""
        name = secrets.token_hex(16) + ".png"
        (self.dir / name).write_bytes(data)
        self._prune()
        return name

    def response(self, images: list[bytes], job: dict, figures: dict, base_url: str) -> dict:
        data = []
        for i, png in enumerate(images):
            item = {"revised_prompt": job["prompt"], "seed": job["seed"] + i}
            if job["response_format"] == "url":
                item["url"] = f"{base_url}/v1/images/files/{self.store(png)}"
            else:
                item["b64_json"] = base64.b64encode(png).decode("ascii")
            data.append(item)
        return {"created": int(time.time()), "data": data, "model": self.model,
                "output_format": "png", "size": f"{job['width']}x{job['height']}", "strata": figures}

    def status(self) -> dict:
        out = {"enabled": True, "model": self.model, "backend": self.cfg.get("backend"),
               "quant": self.cfg.get("quant"), "gpu_policy": self.policy, **self.totals}
        if self.progress:
            out["step"], out["steps"] = self.progress
        if self.last:
            out["last"] = self.last
        return out


# ------------------------------------------------------------------------------------------- the GPU turn
# The policy and the turn itself live in serve/gputurn.py, so a ComfyUI job (serve/comfyui.py) goes through the same
# one.  They stay importable from here: the server and the tests call them by this module's name.
from serve.gputurn import engine_elastic, gpu_turn, resolve_policy, restore_session  # noqa: E402,F401
