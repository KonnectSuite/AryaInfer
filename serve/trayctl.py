"""serve/trayctl.py - the headless half of the Windows tray icon (serve/tray.py): the model to start, the command to
start it with, its start and stop without a console window, what state it is in, its log, and the sign-in entry.

Importable and testable on any system; it only runs Windows things when they are needed (the startup-folder entry).

The tray icon owns the server as a hidden child, so no console window appears and nothing is left behind: the server
goes into serve/winjob.py's kill-on-close job, so closing the icon - cleanly or from Task Manager - ends the server,
and the engine ends with its server.  A hidden child has no console, so Ctrl+C cannot reach it: the tray starts the
server with a per-run control token and stops it with POST /api/shutdown (serve/server.py), which is Ctrl+C's own
path - the engine gets its QUIT, the vision encoder and the MCP servers end, sessions are saved.

    python -m serve.trayctl [--config strata-<model>.json]      what the tray would start, and its state
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8095                       # serve/server.py's own default (setup writes 8080 into the config)
TRAY_APP_NAME = "AryaStrata"
AUTOSTART_NAME = "AryaStrata (tray).vbs"  # the entry in the user's Startup folder
LOG_CAP_BYTES = 2 * 1024 * 1024           # logs/tray.log rolls to logs/tray.log.1 past this

# What the icon shows.  The server serves only once the model is loaded, so "no answer yet" with a live child means
# the model is still loading (30-90 s on a warm start, minutes for a first one).
NO_CONFIG = "no model is installed"
STOPPED = "stopped"
STARTING = "loading the model"
READY = "ready"
UNLOADED = "serving, model out of the card"
STOPPING = "stopping"
EXTERNAL = "running outside the tray"
CRASHED = "stopped by itself"


def read_config(path) -> dict:
    """A run config as a dict; {} when it cannot be read (the tray says so instead of failing)."""
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def find_configs(root=ROOT) -> list[Path]:
    """Installed models' run configs, newest used first - the same rule as setup's start and the MCP server's
    (tools/strata_mcp.py): strata-<model>.json beside the code, its settings/bak files left out."""
    root = Path(root)
    out = [p for p in root.glob("strata-*.json")
           if ".bak" not in p.name and ".shared-settings." not in p.name and p.is_file()]
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def config_port(cfg: dict, default: int = DEFAULT_PORT) -> int:
    v = cfg.get("port")
    return int(v) if str(v or "").isdigit() and int(v) > 0 else default


def config_name(cfg_path, cfg: dict | None = None) -> str:
    """The name the tray shows for a model: its config's model_name, else the config's own tag."""
    name = (cfg or {}).get("model_name") or ""
    return str(name).strip() or Path(cfg_path).stem[len("strata-"):]


def new_control_token() -> str:
    """The per-run token the tray stops its own server with (POST /api/shutdown).  Kept in memory only: a random
    value per start, never written to a file and never the API key."""
    return secrets.token_hex(16)


def server_command(python_exe, root, cfg_path, port: int, open_browser: bool = False,
                   control_token: str | None = None) -> list[str]:
    """The server's command line for a model, as run-<model>.bat has it (setup.py: write_run_script), plus the tray's
    --control-token.  --open is left out: the tray says "AryaStrata is ready" and opens the page when asked to."""
    cmd = [str(python_exe), str(Path(root) / "serve" / "server.py"), "--engine", "strata",
           "--config", str(Path(cfg_path)), "--port", str(int(port))]
    if open_browser:
        cmd.append("--open")
    if control_token:
        cmd += ["--control-token", str(control_token)]
    return cmd


def dashboard_url(host: str, port: int) -> str:
    """The page to open: always through loopback, also when the server listens on 0.0.0.0 (the LAN addresses are
    for other devices, and are printed in the log)."""
    h = "127.0.0.1" if str(host).strip() in ("0.0.0.0", "", "::", "::1", "localhost") else str(host).strip()
    return f"http://{h}:{int(port)}/"


def health(host: str, port: int, timeout: float = 2.0) -> dict | None:
    """GET /health (no API key needed) as a dict, or None when nothing answers there.  /health answers as soon as
    the server serves, which is after the model is loaded."""
    url = f"http://{dashboard_url(host, port)[len('http://'):]}health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def pythonw_for(python_exe) -> Path:
    """The windowless twin of a venv's python.exe (the same Scripts folder), else python.exe itself."""
    p = Path(python_exe)
    w = p.with_name("pythonw.exe")
    return w if w.exists() else p


def startup_folder(environ: dict | None = None) -> Path | None:
    """The user's Startup folder (Windows); None where there is none."""
    env = os.environ if environ is None else environ
    if os.name != "nt":
        return None
    appdata = env.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def autostart_text(pythonw, script) -> str:
    """The .vbs that starts the tray icon at sign-in: window 0, so nothing shows up."""
    return ('rem AryaStrata: the tray icon at sign-in. Written by setup.py / the tray icon\'s menu; the menu\'s\n'
            'rem "Start at sign-in" writes and removes this file. Run = 0 (no window), and AryaStrata then runs\n'
            'rem while you are signed in: closing the icon stops it (see docs/TRAY.md).\n'
            f'CreateObject("WScript.Shell").Run """{Path(pythonw)}"" ""{Path(script)}""", 0, False\n')


def autostart_path(name: str = AUTOSTART_NAME, environ: dict | None = None) -> Path | None:
    folder = startup_folder(environ)
    return None if folder is None else folder / name


def autostart_enabled(name: str = AUTOSTART_NAME, environ: dict | None = None) -> bool:
    p = autostart_path(name, environ)
    return bool(p) and p.exists()


def enable_autostart(pythonw, script, name: str = AUTOSTART_NAME, environ: dict | None = None) -> Path | None:
    """Write the sign-in entry; None where a Startup folder is not available (no Windows, no APPDATA)."""
    p = autostart_path(name, environ)
    if p is None:
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(autostart_text(pythonw, script), encoding="utf-8")
    return p


def disable_autostart(name: str = AUTOSTART_NAME, environ: dict | None = None) -> bool:
    p = autostart_path(name, environ)
    if p is None or not p.exists():
        return False
    p.unlink()
    return True


class ServerController:
    """The tray's server: start it hidden, ask what it is doing, stop it the way Ctrl+C would.

    Everything the tray needs is here and nothing here touches the tray: the seams (popen, contain, probe,
    sleep, clock) are arguments, so serve/test_trayctl.py runs every path without a GPU, a window station,
    or real processes.
    """

    def __init__(self, root=ROOT, python_exe=None, log_path=None, *, popen=subprocess.Popen,
                 contain=None, probe=health, post=None, sleep=time.sleep, clock=time.monotonic, log_cap=LOG_CAP_BYTES):
        from serve.winjob import contain as _contain          # the kill-on-close job (Windows; a no-op elsewhere)
        self.root = Path(root)
        self.python_exe = str(python_exe or self._venv_python())
        self.log_path = Path(log_path) if log_path else self.root / "logs" / "tray.log"
        self.log_cap = int(log_cap)
        self.popen, self.contain, self.probe = popen, (contain or _contain), probe
        self.post, self.sleep, self.clock = post, sleep, clock
        self.proc = None
        self.token = ""
        self.cfg_path: Path | None = None
        self.stop_asked = False
        self.log_file = None

    @property
    def port(self) -> int:
        """The port to talk to: the one the installed config says - this tray's own config once it has started a
        server, else the newest installed one (setup writes 8080 there; DEFAULT_PORT is only for no config at all)."""
        cfg = self.cfg_path if self.cfg_path is not None else (self.configs()[0] if self.configs() else None)
        return config_port(read_config(cfg)) if cfg is not None else DEFAULT_PORT

    # ---- the log: the server's whole console output, and the tray's own lines, in logs/tray.log
    def log(self, line: str) -> None:
        try:
            f = self.log_handle()
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
            f.flush()
        except OSError:
            pass                                          # a log that cannot be written never stops the model

    def log_handle(self):
        """The append handle for the log, rolled over once when it passed the cap (tray.log -> tray.log.1)."""
        if self.log_file is not None and not self.log_file.closed:
            return self.log_file
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.log_path.exists() and self.log_path.stat().st_size > self.log_cap:
            os.replace(self.log_path, self.log_path.with_name(self.log_path.name + ".1"))
        self.log_file = open(self.log_path, "a", encoding="utf-8", errors="replace")
        return self.log_file

    def close_log(self) -> None:
        if self.log_file is not None and not self.log_file.closed:
            self.log_file.close()

    def _venv_python(self) -> Path:
        v = self.root / ".venv" / "Scripts" / ("python.exe" if os.name == "nt" else "python")
        return v if v.exists() else Path(sys.executable)

    # ---- what is installed
    def configs(self) -> list[Path]:
        return find_configs(self.root)

    def config_path(self, model: str | None = None) -> Path | None:
        """The run config to start: the one named, else the newest used (setup's rule). None when nothing is set up."""
        have = self.configs()
        if not have:
            return None
        if not model:
            return self.cfg_path if self.cfg_path in have else have[0]
        m = str(model).strip().lower()
        for p in have:
            if p.stem[len("strata-"):] == m or str(read_config(p).get("model_name", "")).lower() == m:
                return p
        return None

    def model_name(self) -> str | None:
        return None if self.cfg_path is None else config_name(self.cfg_path, read_config(self.cfg_path))

    def url(self) -> str:
        return dashboard_url(read_config(self.cfg_path).get("host") if self.cfg_path else "127.0.0.1", self.port)

    # ---- start
    def start(self, model: str | None = None, config_path=None, open_browser: bool = False) -> tuple[bool, dict]:
        """Start the server as a hidden child, in the job that dies with this tray. (ok, detail)."""
        if self.proc is not None and self.proc.poll() is None:
            return False, {"message": "AryaStrata is already starting"}
        cfg = Path(config_path) if config_path else self.config_path(model)
        if cfg is None:
            return False, {"message": "no model is installed: run START-HERE.bat first (docs/INSTALL.md)"}
        cfg = Path(cfg)
        cfgs = self.configs()
        if cfgs and cfg not in cfgs:
            return False, {"message": f"{cfg.name} is not an installed model"}
        self.cfg_path = cfg
        cfg_json = read_config(cfg)
        if not cfg_json.get("exe"):
            return False, {"message": f"{cfg.name} has no engine in it: run SETUP.bat (--setup) first"}
        self.token = new_control_token()                                    # self.port follows cfg_path (property)
        self.stop_asked = False
        argv = server_command(self.python_exe, self.root, cfg, self.port,
                              open_browser=open_browser, control_token=self.token)
        self.log(f"start: {cfg.name} port {self.port}")
        flags = 0
        if os.name == "nt":
            DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP = 0x00000008, 0x00000200
            flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP      # no console: closing a window cannot stop it
        try:
            self.proc = self.popen(argv, cwd=str(self.root), stdin=subprocess.DEVNULL,
                                   stdout=self.log_handle(), stderr=self.log_handle(), creationflags=flags)
        except OSError as e:
            self.proc = None
            self.log(f"start failed: {e}")
            return False, {"message": f"could not start AryaStrata: {e}"}
        if not self.contain(self.proc):                            # Windows: end the server when this tray ends
            self.log("the server is not tied to the tray's lifetime (the job object could not be made)")
        return True, {"port": self.port, "model": self.model_name()}

    # ---- what is happening
    def status(self) -> tuple[str, dict]:
        """(state, detail) for the tooltip, the icon and the menu. detail: code / health / url / message."""
        detail = {"url": self.url(), "port": self.port}
        if self.cfg_path is None and not self.configs():
            return NO_CONFIG, detail
        proc, port = self.proc, self.port
        if proc is not None:
            code = proc.poll()
            if code is not None:                                   # it ended: by request, cleanly, or by itself
                detail["code"] = code
                return (STOPPED if code == 0 else CRASHED), detail
            if self.stop_asked:
                return STOPPING, detail                            # asked, and it is still releasing the card
            h = self.probe("127.0.0.1", port)
            if h is None:
                detail["model"] = self.model_name()
                return STARTING, detail                            # serving starts after the model is loaded
            detail["health"] = h
            return (READY if h.get("loaded") else UNLOADED), detail
        h = self.probe("127.0.0.1", port)                          # the port answers, not for this tray
        if h:
            detail["health"] = h
            return EXTERNAL, detail
        return STOPPED, detail

    def ready(self) -> bool:
        return self.status()[0] == READY

    # ---- stop
    def stop(self, wait_s: float = 20.0) -> tuple[bool, dict]:
        """POST /api/shutdown (Ctrl+C's path: the engine's QUIT, the encoder, the MCP servers, the sessions) and
        wait for the process to go. False with a reason when the tray cannot stop it."""
        if self.proc is None:
            if self.probe("127.0.0.1", self.port):
                return False, {"message": "AryaStrata was started outside the tray: stop it from its own window"}
            return False, {"message": "AryaStrata is not running"}
        if self.proc.poll() is not None:
            return True, {"message": "AryaStrata has already stopped"}
        self.stop_asked = True
        self.log("stop: asking the server to stop")
        ok = self.post() if self.post is not None else self.post_shutdown()
        end = self.clock() + wait_s
        while self.clock() < end:
            if self.proc.poll() is not None:
                detail = {"code": self.proc.returncode, "graceful": ok}
                self.log(f"stop: the server ended (exit {self.proc.returncode})")
                return True, detail
            self.sleep(0.25)
        if not ok:
            self.stop_asked = False
            return False, {"message": "the server did not answer the stop request; it keeps running"}
        return False, {"message": "the server is taking its time (a request may be running); try again in a minute"}

    def post_shutdown(self) -> bool:
        """The stop request itself: JSON from loopback with the tray's token. True on 200."""
        req = urllib.request.Request(dashboard_url("127.0.0.1", self.port)[:-1] + "/api/shutdown",
                                     data=b'{"by":"tray"}', method="POST",
                                     headers={"Content-Type": "application/json",
                                              "X-AryaStrata-Control": self.token})
        try:
            with urllib.request.urlopen(req, timeout=5.0) as r:
                return 200 <= r.status < 300
        except (OSError, urllib.error.URLError, ValueError) as e:
            self.log(f"stop: the stop request failed: {e}")
            return False

    def restart(self, model: str | None = None) -> tuple[bool, dict]:
        """Stop it, then start it again on the same model. The stop is asked for and waited for; if the server
        refuses to end, nothing is started on top of it."""
        ok, detail = self.stop()
        if not ok:
            return False, detail
        if self.proc is not None and self.proc.poll() is None:
            return False, {"message": "the server is still running; AryaStrata was not restarted"}
        return self.start(model=model)

    # ---- sign-in
    def autostart_on(self) -> bool:
        return autostart_enabled()

    def set_autostart(self, on: bool) -> tuple[bool, str]:
        script = self.root / "serve" / "tray.py"
        if on:
            p = enable_autostart(pythonw_for(self.python_exe), script)
            return (p is not None, "the sign-in entry is in the Startup folder" if p is not None
                    else "no Startup folder was found: AryaStrata will start when you run the tray icon yourself")
        return (True, "the sign-in entry was removed") if disable_autostart() or not autostart_enabled() \
            else (False, "the sign-in entry could not be removed")


def main(argv=None) -> int:
    """What the tray would start, and what state it is in - the support view of the tray's own state."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="a run config beside this folder (default: the newest used)")
    a = ap.parse_args(argv)
    c = ServerController()
    cfg = c.config_path()
    if cfg is None:
        print("no model is installed in this AryaStrata folder: run START-HERE.bat (docs/INSTALL.md)")
        return 1
    state, detail = c.status()
    print(f"model:   {config_name(cfg, read_config(cfg))}  ({cfg.name})")
    print(f"url:     {dashboard_url(read_config(cfg).get('host', '127.0.0.1'), config_port(read_config(cfg)))}")
    print(f"state:   {state}" + (f" (exit {detail['code']})" if "code" in detail else ""))
    print(f"log:     {c.log_path}")
    print(f"sign-in: {'on' if c.autostart_on() else 'off'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
