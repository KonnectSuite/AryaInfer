"""serve/gputurn.py - an image job's turn on the GPU, shared by every image provider.

An image job needs the whole card for a while, and the text engine may be holding it.  This is the one place that
decides what happens to the model during the job - keep it, shrink its expert cache, or unload it and save the
conversation - and gives the memory back afterwards.  serve/images.py's sd-cli jobs use it; so do the ComfyUI jobs in
serve/comfyui.py, which is why it lives here rather than inside one provider.

Policies (the provider's `policy`, set by its settings):
  keep    - the engine stays loaded and idle
  shrink  - an engine started with --vram-elastic lends the job VRAM from its expert cache and takes it back after
  unload  - its conversation is saved, the engine is stopped, and the next start restores it
  auto    - keep when there is room for the job next to it, else shrink when the engine can, else unload
"""
from __future__ import annotations

import contextlib
import os
import secrets
import sys
import threading
import time


def resolve_policy(svc, owner, need: int) -> str:
    """auto -> keep / shrink / unload for this job; a fixed policy is kept, except that an engine that is not
    running has nothing to give back (keep)."""
    eng = svc.engine
    running = not hasattr(eng, "alive") or eng.alive()
    if not running or not hasattr(eng, "unload"):
        return "keep"
    if owner.policy != "auto":
        return owner.policy
    if (getattr(owner, "cfg", None) or {}).get("uma"):
        return "keep"                         # an APU: the image job and the engine share the RAM either way
    free = svc.free_vram_mib()
    if free is None or free >= need:
        return "keep"
    if engine_elastic(eng):
        return "shrink"
    return "unload"


def engine_elastic(eng) -> bool:
    """An engine that resizes its expert cache on request (--vram-elastic, #533)."""
    if not hasattr(eng, "vram"):
        return False
    if (getattr(eng, "info", None) or {}).get("vram_elastic"):
        return True
    spawn = getattr(eng, "spawn", None)
    args = spawn[1] if isinstance(spawn, (list, tuple)) and len(spawn) > 1 else []
    return "--vram-elastic" in (args or [])


def _client_gone(svc) -> Exception:
    """The server module's ClientGone (it may run as __main__, so not imported by name)."""
    return getattr(sys.modules.get(type(svc).__module__), "ClientGone", RuntimeError)()


@contextlib.contextmanager
def gpu_turn(svc, owner, job: dict, cancel: threading.Event | None = None, take_turn: bool = True):
    """The image job's turn on the GPU: the service's FIFO (and, with parallel requests, the engine's control lines
    once no slot is generating), and the text engine made room for it per the policy.  Yields the policy used.

    owner is the provider running the job: it carries policy, cfg (for uma), dir (where a saved conversation
    goes), _say, and 
eload, and its 
eed_mib(job) says how much GPU memory the job asks for.  	ake_turn=False
    when the caller already holds the service's turn - a chat tool call runs inside the request that is answering, and
    asking for the FIFO again would wait on itself."""
    state = {"queued": True}
    with svc.status_lock:
        svc.status["queued"] += 1

    def unqueue() -> None:
        if state["queued"]:
            state["queued"] = False
            with svc.status_lock:
                svc.status["queued"] -= 1

    try:
        if take_turn:
            with svc._turn(cancel):
                unqueue()
                with _room_and_job(svc, owner, job, cancel, control=True) as policy:
                    yield policy
        else:
            unqueue()
            with _room_and_job(svc, owner, job, cancel, control=False) as policy:
                yield policy
    finally:
        unqueue()


@contextlib.contextmanager
def _room_and_job(svc, owner, job: dict, cancel, control: bool):
    """Inside the turn: wait for parallel slots, decide the policy, make room, run, give it back."""
    ctl = getattr(svc.engine, "ctl", None) if control and getattr(svc.engine, "batch", 0) else None
    if ctl is not None:
        while not ctl.acquire(timeout=0.25):
            if cancel is not None and cancel.is_set():
                raise _client_gone(svc)
    try:
        if ctl is not None:                           # running parallel requests finish first
            while getattr(svc, "live_reqs", None):
                if cancel is not None and cancel.is_set():
                    raise _client_gone(svc)
                time.sleep(0.25)
        need = int(owner.need_mib(job))
        policy = resolve_policy(svc, owner, need)
        with svc.status_lock:
            svc.status.update(busy=True, phase="generating an image", started=time.time(),
                              first_token=None, prompt_tokens=None, generated=None, max_tokens=None)
        restore = _make_room(svc, owner, policy, need)
        try:
            yield policy
        finally:
            _give_back(svc, owner, policy, restore)
            with svc.status_lock:
                svc.status["busy"] = False
            svc.last_request_at = time.time()
    finally:
        if ctl is not None:
            ctl.release()


def _make_room(svc, owner, policy: str, need: int):
    """Do what `policy` says before the job; -> what _give_back needs."""
    eng = svc.engine
    if policy == "shrink":
        try:
            out = eng.vram(need)
            owner._say(f"image job: the engine's expert cache gave VRAM back ({out.get('vram_free_mib')} MiB free)")
            return "shrunk"
        except Exception as e:                       # noqa: BLE001 - the job still runs, with what is free
            owner._say(f"image job: the engine could not give VRAM back ({e}); the job runs with what is free")
            return None
    if policy == "unload":
        saved = None
        if hasattr(eng, "session_file") and not getattr(eng, "batch", 0):
            path = str(owner.dir / f"llm-session-{secrets.token_hex(6)}.bin")
            try:
                r = eng.session_file("save", path)
                saved = path
                owner._say(f"image job: the conversation ({r.get('tokens')} tokens) saved; unloading the model")
            except Exception as e:                   # noqa: BLE001 - unloading still frees the GPU
                owner._say(f"image job: the conversation could not be saved ({e}); unloading the model")
                with contextlib.suppress(OSError):
                    os.unlink(path)
        eng.unload()
        if svc.vision is not None and hasattr(svc.vision, "unload"):
            svc.vision.unload()
        return saved or "unloaded"
    return None


def _give_back(svc, owner, policy: str, restore) -> None:
    eng = svc.engine
    if restore == "shrunk":
        try:
            eng.vram(svc.vram_reserve)               # the reserve asked for last (None: the start's)
        except Exception as e:                       # noqa: BLE001
            owner._say(f"image job: the expert cache did not grow back ({e}); POST /v1/vram can retry")
    elif policy == "unload" and restore:
        if restore != "unloaded":
            svc.restore_after_load = restore         # Service.ensure_loaded restores it after the next start
        if owner.reload == "eager":
            try:
                svc.ensure_loaded()                  # the caller still holds the FIFO
            except Exception as e:                   # noqa: BLE001 - the next request tries again
                owner._say(f"image job: the model did not load again yet ({e}); the next request loads it")


def restore_session(svc) -> None:
    """After an engine start: restore the conversation an image job saved before it unloaded the engine."""
    path = getattr(svc, "restore_after_load", None)
    if not path:
        return
    svc.restore_after_load = None
    try:
        r = svc.engine.session_file("restore", path)
        print(f"[strata] the conversation from before the image job is back ({r.get('tokens')} tokens)", flush=True)
    except Exception as e:                           # noqa: BLE001 - the engine runs, without the old cache
        print(f"[strata] the conversation from before the image job was not restored ({e}); the next request "
              "reads its prompt again", flush=True)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)
