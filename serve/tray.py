"""serve/tray.py - the AryaStrata tray icon for Windows: the model's live status in the notification area, with
start, stop, restart, model switch, the sign-in entry and the log, and no console window anywhere.

    TRAY.vbs / pythonw serve\\tray.py        the icon (what setup's launcher and the Startup entry run)
    python serve\\tray.py --check            the icon files and the menu, then exit (no tray: for checks)
    python serve\\tray.py --status           what the tray would show, then exit

The state, the command line, the start/stop and the sign-in entry are in serve/trayctl.py (importable and tested
without Windows); this file is the notification-area half: the icon, its tooltip and balloons, the menu, and the
message loop they live on.  ctypes only, like serve/winjob.py and serve/keepawake.py - no extra packages.

Closing the icon stops AryaStrata the way Ctrl+C would (POST /api/shutdown, serve/server.py), and the server also
goes into serve/winjob.py's kill-on-close job, so killing the icon from Task Manager takes the server - and with it
the engine - down instead of leaving them holding the graphics card.  docs/TRAY.md.
"""
from __future__ import annotations

import ctypes                    # ctypes.wintypes is Windows-only and is imported inside windows_api()
import os
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from serve.trayctl import (CRASHED, EXTERNAL, NO_CONFIG, READY, STARTING, STOPPED, STOPPING, UNLOADED,  # noqa: E402
                           ServerController, config_name, read_config)

WINDOWS_ONLY = ("AryaStrata's tray icon is for Windows. On this system start the model with ./setup.sh, or "
                "python serve/server.py --engine strata --config strata-<model>.json (docs/INSTALL.md).")

# the icon files, and the tray's own window class: one icon per state, drawn once at start
ICON_KINDS = ("idle", "starting", "ready", "unloaded", "stopping", "crashed", "external")
STATE_ICON = {STOPPED: "idle", NO_CONFIG: "idle", STARTING: "starting", READY: "ready", UNLOADED: "unloaded",
              STOPPING: "stopping", CRASHED: "crashed", EXTERNAL: "external"}
ACCENT = {"idle": (110, 122, 138), "starting": (255, 178, 32), "ready": (0, 224, 210), "unloaded": (43, 108, 255),
          "stopping": (86, 132, 178), "crashed": (226, 74, 74), "external": (150, 120, 220)}
INK = (15, 20, 27)            # the web app's dark ground (serve/web/favicon.svg)
LETTER = (230, 232, 235)      # the mark's letter colour
# the "A" of AryaStrata's mark, from serve/web/favicon.svg's 512x512 grid (the letter and its counter)
_A_OUTER = [(256, 120), (358, 348), (304, 348), (282, 296), (230, 296), (208, 348), (154, 348)]
_A_HOLE = [(256, 204), (233, 260), (279, 260)]

TIP_LIMIT = 120               # szTip holds 127 characters; keep the tooltip short enough for every shell


# -------------------------------------------------------------------------------------------- the view (testable)
def icon_kind(state: str) -> str:
    return STATE_ICON.get(state, "idle")


def tip_text(state: str, detail: dict | None = None, model: str | None = None) -> str:
    """The tooltip for a state, within the shell's 127-character tooltip."""
    detail = detail or {}
    url = detail.get("url") or ""
    name = model or detail.get("model") or ""
    text = {
        READY: f"AryaStrata: {name} is ready at {url}",
        STARTING: f"AryaStrata: {name} is loading the model - the page answers as soon as it is ready",
        UNLOADED: f"AryaStrata: the page is up, {name} is out of the graphics card; the next request loads it",
        STOPPING: "AryaStrata: stopping (the model is being released)",
        CRASHED: f"AryaStrata stopped by itself (exit {detail.get('code')}) - open the log from the menu",
        EXTERNAL: f"AryaStrata is running outside the tray at {url}: stop it from its own window",
        NO_CONFIG: "AryaStrata: no model is installed - run START-HERE.bat (docs/INSTALL.md)",
        STOPPED: "AryaStrata is stopped",
    }.get(state, "AryaStrata")
    return text[:TIP_LIMIT]


def balloon_for(prev: str | None, state: str, detail: dict, model: str | None = None,
               asked_to_stop: bool = False) -> tuple[str, str, str] | None:
    """(title, body, kind) for the balloon to show on the prev -> state change, or None.  kind: info, warning, error."""
    if prev == state or prev is None:
        return None
    name = model or detail.get("model") or "the model"
    if state == READY:
        return ("AryaStrata is ready", f"{name} is loaded. Open it from the tray icon's menu"
                                       f" ({detail.get('url')}).", "info")
    if state == CRASHED:
        return ("AryaStrata stopped by itself", f"The server ended with exit code {detail.get('code')}. "
                                                "Open the log from the tray icon's menu (logs/tray.log).", "error")
    if state == STOPPED and prev in (STARTING, READY, UNLOADED):
        return (("AryaStrata is stopped", "The model and the graphics card are released.",
                 "info") if asked_to_stop else
                ("AryaStrata stopped by itself", "The server ended. Open the log from the tray icon's menu.",
                 "warning"))
    if state == NO_CONFIG:
        return ("AryaStrata: no model is installed", "Run START-HERE.bat to set one up (docs/INSTALL.md).",
                "warning")
    if state == EXTERNAL:
        return ("AryaStrata is running outside the tray",
                "AryaStrata answers on this port but was not started by the tray icon: stop it from its own window.",
                "info")
    return None


ID_OPEN, ID_START, ID_STOP, ID_RESTART = 1, 2, 3, 4
ID_MODEL, ID_AUTOSTART, ID_LOG, ID_QUIT = 9, 10, 11, 12
ID_MODEL_BASE = 100           # model submenu items: ID_MODEL_BASE + index into the config list

_SWITCH = (READY, UNLOADED, STOPPED, CRASHED)          # the tray owns the server: it can restart it on a model
_RUNNABLE = (STOPPED, CRASHED)


def menu_items(state: str, *, autostart: bool = False, models: list[str] | None = None,
               running: str | None = None) -> list[dict]:
    """The menu for a state: [{kind: "item"/"submenu"/"sep", id, label, enabled, checked, submenu}] - the pure half
    of the tray, so the menu is checked in tests.  A menu item that does not apply is greyed, with the reason in
    the tooltip, which is clearer in the shell than a dialog."""
    models = list(models or [])
    can_stop = state in (STARTING, READY, UNLOADED)
    items = [
        {"kind": "item", "id": ID_OPEN, "label": "Open AryaStrata",
         "enabled": state in (READY, UNLOADED, EXTERNAL)},
        {"kind": "item", "id": ID_START, "label": "Start AryaStrata",
         "enabled": state in _RUNNABLE and bool(models)},
        {"kind": "item", "id": ID_STOP, "label": "Stop AryaStrata", "enabled": can_stop},
        {"kind": "item", "id": ID_RESTART, "label": "Restart AryaStrata",
         "enabled": state in (READY, UNLOADED, CRASHED, STOPPED) and bool(models)},
        {"kind": "sep", "id": 0},
    ]
    if len(models) > 1:
        items.append({"kind": "submenu", "id": ID_MODEL, "label": "Model",
                      "enabled": state in _SWITCH,
                      "submenu": [{"kind": "item", "id": ID_MODEL_BASE + i, "label": m,
                                   "enabled": True, "checked": m == running} for i, m in enumerate(models)]})
        items.append({"kind": "sep", "id": 0})
    items += [
        {"kind": "item", "id": ID_AUTOSTART, "label": "Start at sign-in", "enabled": True, "checked": autostart},
        {"kind": "item", "id": ID_LOG, "label": "Open the log", "enabled": True},
        {"kind": "sep", "id": 0},
        {"kind": "item", "id": ID_QUIT, "label": "Quit AryaStrata (and stop the model)", "enabled": True},
    ]
    return items


# -------------------------------------------------------------------------------------------- the icon art
def icon_dir(env: dict | None = None) -> Path:
    """Where the tray's icon files are kept: %LOCALAPPDATA%\\AryaStrata, else a temp folder."""
    env = os.environ if env is None else env
    base = env.get("LOCALAPPDATA")
    d = Path(base) / "AryaStrata" if base else Path(tempfile.gettempdir()) / "AryaStrata-tray"
    d.mkdir(parents=True, exist_ok=True)
    return d


def draw_icon(kind: str, size: int = 48):
    """The tray icon for one state: AryaStrata's mark (serve/web/favicon.svg's "A") on the dark ground, framed in
    the state's colour.  Pillow, which setup already installs (requirements.txt)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    accent = ACCENT.get(kind, ACCENT["idle"])
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=max(2, size // 6), fill=INK,
                        outline=accent, width=max(1, size // 16))
    s = size / 512.0
    # the mark's letter, edged in the state's colour: at 16 px (the tray's own size) the letter alone is a hairline,
    # so the state colour is what carries the icon there, and the letter stays readable at 32 px and up
    edge = max(1, size // 24)
    d.polygon([(round(x * s), round(y * s)) for x, y in _A_OUTER], fill=LETTER, outline=accent, width=edge)
    d.polygon([(round(x * s), round(y * s)) for x, y in _A_HOLE], fill=INK)
    return img


def write_icons(where: Path | None = None, kinds: tuple[str, ...] = ICON_KINDS) -> dict[str, Path]:
    """Every state's icon as an .ico (16/24/32/48 px), returning {kind: path}.  The shell wants a file it can load
    by name (LoadImageW), so each state is drawn once at start, not on every tooltip change."""
    where = Path(where) if where else icon_dir()
    out = {}
    for kind in kinds:
        p = where / f"aryastrata-{kind}.ico"
        img = draw_icon(kind)
        img.save(p, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48)])
        out[kind] = p
    return out


# -------------------------------------------------------------------------------------------- Win32
def windows_api():
    """The Win32 types, constants and calls the tray needs, with their prototypes set.  ctypes.wintypes is
    Windows-only, so this is a function: the testable half of the module imports nothing Windows."""
    import ctypes
    from ctypes import wintypes

    class Api:
        pass

    api = Api()
    api.ctypes, api.wintypes = ctypes, wintypes
    u = api.u = ctypes.windll.user32
    k = api.k = ctypes.windll.kernel32
    shell = api.shell = ctypes.windll.shell32

    api.LRESULT = ctypes.c_ssize_t
    api.WNDPROC = ctypes.WINFUNCTYPE(api.LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", api.WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON), ("hCursor", wintypes.HGDIOBJ), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                    ("hIconSm", wintypes.HICON)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                    ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateFlags", wintypes.DWORD),
                    ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                    ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                    ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]

    api.WNDCLASSEXW, api.NOTIFYICONDATAW = WNDCLASSEXW, NOTIFYICONDATAW

    # tray-icon messages and flags (shell 5: balloons and the tooltip that does not cover the clock)
    api.NIM_ADD, api.NIM_MODIFY, api.NIM_DELETE, api.NIM_SETVERSION = 0, 1, 2, 4
    api.NIF_MESSAGE, api.NIF_ICON, api.NIF_TIP, api.NIF_INFO, api.NIF_SHOWTIP = 0x1, 0x2, 0x4, 0x10, 0x20
    api.SHELL_VERSION = 4                             # NOTIFYICON_VERSION_4: balloons, and the tooltip that does not
    #                                                   cover the clock (there is no version 5: NIM_SETVERSION with it
    #                                                   is refused, measured here)
    api.NI_INFO, api.NI_WARNING, api.NI_ERROR = 0x1, 0x2, 0x3
    api.WM_USER = 0x0400
    api.WM_TRAY = api.WM_USER + 1                     # the shell clicked/activated the icon
    api.WM_POLL = 0x8000 + 1                          # the status thread's "the state changed"
    api.WM_LBUTTONUP, api.WM_LBUTTONDBLCLK, api.WM_RBUTTONUP, api.WM_MBUTTONUP = 0x0202, 0x0203, 0x0204, 0x0208
    api.NIN_BALLOONUSERCLICK = api.WM_USER + 5
    api.WM_COMMAND, api.WM_CLOSE, api.WM_DESTROY = 0x0111, 0x0010, 0x0002
    api.WM_QUIT, api.WM_APP = 0x0012, 0x8000
    api.MF_STRING, api.MF_GRAYED, api.MF_CHECKED, api.MF_POPUP = 0x0, 0x1, 0x8, 0x10
    api.MF_SEPARATOR = 0x800
    api.TPM_RETURNCMD, api.TPM_NONOTIFY, api.TPM_BOTTOMALIGN = 0x100, 0x80, 0x20
    api.LR_LOADFROMFILE, api.SM_CXSMICON = 0x10, 13
    api.HWND_MESSAGE = wintypes.HWND(-3)              # a window that only receives messages
    api.CS_HREDRAW, api.CS_VREDRAW = 0x1, 0x2
    api.WS_OVERLAPPED = 0
    api.ERROR_ALREADY_EXISTS = 183

    k.GetModuleHandleW.restype = wintypes.HINSTANCE
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    u.RegisterClassExW.restype = wintypes.USHORT
    u.RegisterClassExW.argtypes = (ctypes.POINTER(WNDCLASSEXW),)
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = (wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                  wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
    u.DefWindowProcW.restype = api.LRESULT
    u.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    u.DestroyWindow.argtypes = (wintypes.HWND,)
    u.PostMessageW.restype = wintypes.BOOL
    u.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    u.GetMessageW.restype = ctypes.c_int
    u.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
    u.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
    u.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
    u.PostQuitMessage.argtypes = (ctypes.c_int,)
    u.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    u.GetSystemMetrics.restype = ctypes.c_int
    u.GetSystemMetrics.argtypes = (ctypes.c_int,)
    u.SetForegroundWindow.argtypes = (wintypes.HWND,)
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.AppendMenuW.restype = wintypes.BOOL
    u.AppendMenuW.argtypes = (wintypes.HMENU, wintypes.UINT, wintypes.UINT, wintypes.LPCWSTR)
    u.TrackPopupMenu.restype = ctypes.c_uint
    u.TrackPopupMenu.argtypes = (wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 wintypes.HWND, wintypes.LPVOID)
    u.DestroyMenu.restype = wintypes.BOOL
    u.DestroyMenu.argtypes = (wintypes.HMENU,)
    u.LoadImageW.restype = wintypes.HANDLE
    u.LoadImageW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                             wintypes.UINT)
    u.DestroyIcon.restype = wintypes.BOOL
    u.DestroyIcon.argtypes = (wintypes.HANDLE,)
    shell.Shell_NotifyIconW.restype = wintypes.BOOL
    shell.Shell_NotifyIconW.argtypes = (wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW))
    # the .ico files we write are read with ExtractIconExW: LoadImageW returns NULL on them (measured here, 0 with
    # no error code), while ExtractIconExW hands back the 16 px and 32 px icons the tray and its window want
    shell.ExtractIconExW.restype = wintypes.UINT
    shell.ExtractIconExW.argtypes = (wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.HICON),
                                     ctypes.POINTER(wintypes.HICON), wintypes.UINT)
    return api


class TrayApp:
    """The tray icon itself: the shell's notification-area entry, its tooltip, balloons and menu, on a
    message-only window, with the model's state polled in a thread and applied on the tray's own thread."""

    def __init__(self, ctl: ServerController | None = None, api=None, open_page=None, icon_dir=None):
        self.api = api or windows_api()
        self.ctl = ctl or ServerController()
        self.open_page = open_page or webbrowser.open
        self.class_name = "AryaStrataTray"
        self.icon_id = 0x5A72                               # uID of this tray icon
        self.state, self.detail = None, {}
        self.stop_asked = False
        self.quitting = False
        self.mutex = None
        self.hwnd = None
        self.hwnd_created = False
        self.action_threads = []
        self.icons = {}
        self.hicons = {}
        self.icon_paths = write_icons(icon_dir)
        self._wndproc = self.api.WNDPROC(self._wnd_proc)     # kept alive: the shell calls it for our window
        self._atom = None

    # ---- the icon: add, update (icon + tooltip), balloon, remove
    def _nid(self, flags: int):
        """The shell's notify struct for this icon, sized as shell 5 expects it."""
        api = self.api
        nid = api.NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(api.NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = self.icon_id
        nid.uFlags = flags
        nid.uCallbackMessage = api.WM_TRAY
        nid.uVersion = api.SHELL_VERSION
        return nid

    def add_icon(self) -> None:
        api = self.api
        # NIF_SHOWTIP is not part of NIM_ADD: the shell refuses an add that carries it with E_FAIL (measured here),
        # so the icon is added plainly and the version is set afterwards - updates and balloons then use it
        nid = self._nid(api.NIF_MESSAGE | api.NIF_ICON | api.NIF_TIP)
        nid.hIcon = self.hicons["idle"]
        nid.szTip = "AryaStrata"[:127]
        if not api.shell.Shell_NotifyIconW(api.NIM_ADD, ctypes.byref(nid)):
            raise OSError(f"the shell refused the tray icon (error {api.k.GetLastError()})")
        if not api.shell.Shell_NotifyIconW(api.NIM_SETVERSION, ctypes.byref(nid)):
            self.ctl.log(f"shell version {api.SHELL_VERSION} was refused: no balloon, and the tooltip may cover "
                         f"the clock (error {api.k.GetLastError()})")

    def update_icon(self, kind: str, tip: str) -> None:
        api = self.api
        nid = self._nid(api.NIF_ICON | api.NIF_TIP | api.NIF_SHOWTIP)
        nid.hIcon = self.hicons.get(kind) or self.hicons["idle"]
        nid.szTip = tip[:127]
        api.shell.Shell_NotifyIconW(api.NIM_MODIFY, ctypes.byref(nid))

    def balloon(self, title: str, body: str, kind: str) -> None:
        api = self.api
        nid = self._nid(api.NIF_INFO | api.NIF_SHOWTIP)
        nid.szInfo = body[:255]
        nid.szInfoTitle = title[:63]
        nid.uVersion = api.SHELL_VERSION
        nid.dwInfoFlags = {"info": api.NI_INFO, "warning": api.NI_WARNING, "error": api.NI_ERROR}.get(kind,
                                                                                                       api.NI_INFO)
        api.shell.Shell_NotifyIconW(api.NIM_MODIFY, ctypes.byref(nid))

    def remove_icon(self) -> None:
        api = self.api
        nid = self._nid(0)
        api.shell.Shell_NotifyIconW(api.NIM_DELETE, ctypes.byref(nid))

    # ---- the window
    def create_window(self) -> None:
        api, wintypes = self.api, self.api.wintypes
        wc = api.WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(api.WNDCLASSEXW)
        wc.style = api.CS_HREDRAW | api.CS_VREDRAW
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = k = api.k.GetModuleHandleW(None)
        wc.hIcon = self.hicons["idle"]
        wc.hIconSm = self.hicons["idle"]
        wc.lpszClassName = self.class_name
        self._atom = api.u.RegisterClassExW(ctypes.byref(wc))
        if not self._atom:
            raise OSError(f"RegisterClassExW failed ({api.k.GetLastError()})")
        self.hwnd = api.u.CreateWindowExW(0, self.class_name, "AryaStrata", api.WS_OVERLAPPED,
                                          0, 0, 0, 0, api.HWND_MESSAGE, None, k, None)
        if not self.hwnd:
            raise OSError(f"CreateWindowExW failed ({api.k.GetLastError()})")
        self.hwnd_created = True

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """The tray's window procedure: every tray action runs here, on the tray's own thread, which is the only
        thread that touches the notification area (the status thread posts WM_POLL).  ctypes hands a 0 WPARAM/LPARAM
        to Python as None, hence _lo()."""
        api = self.api

        def _lo(v) -> int:
            return (int(v) if v else 0) & 0xFFFF

        if msg == api.WM_TRAY:
            click = _lo(lparam)
            if click == api.WM_LBUTTONDBLCLK:
                self.dispatch(ID_OPEN)
            elif click in (api.WM_RBUTTONUP, api.WM_MBUTTONUP):
                self.show_menu()
            elif click == api.NIN_BALLOONUSERCLICK:
                self.dispatch(ID_OPEN)
            return 0
        if msg == api.WM_POLL:
            self.apply_state()
            return 0
        if msg == api.WM_COMMAND:
            self.dispatch(_lo(wparam))
            return 0
        if msg in (api.WM_CLOSE, api.WM_DESTROY):
            api.u.PostQuitMessage(0)
            return 0
        return api.u.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---- the menu
    def show_menu(self) -> None:
        api = self.api
        wintypes = api.wintypes
        items = menu_items(self.state or STOPPED, autostart=self.ctl.autostart_on(),
                           models=[config_name(p, read_config(p)) for p in self.ctl.configs()],
                           running=self.ctl.model_name())
        hmenu = api.u.CreatePopupMenu()
        submenu = None
        for it in items:
            if it["kind"] == "sep":
                api.u.AppendMenuW(hmenu, api.MF_SEPARATOR, 0, None)
            elif it["kind"] == "submenu":
                submenu = api.u.CreatePopupMenu()
                for m in it["submenu"]:
                    api.u.AppendMenuW(submenu, api.MF_STRING | (api.MF_CHECKED if m.get("checked") else 0),
                                      m["id"], m["label"])
                flags = api.MF_POPUP | (0 if it.get("enabled", True) else api.MF_GRAYED)
                api.u.AppendMenuW(hmenu, flags, submenu, it["label"])
            else:
                flags = api.MF_STRING | (api.MF_GRAYED if not it.get("enabled", True) else 0) \
                    | (api.MF_CHECKED if it.get("checked") else 0)
                api.u.AppendMenuW(hmenu, flags, it["id"], it["label"])
        pt = wintypes.POINT()
        api.u.GetCursorPos(ctypes.byref(pt))
        api.u.SetForegroundWindow(self.hwnd)             # so the menu closes when the user clicks elsewhere
        cmd = api.u.TrackPopupMenu(hmenu, api.TPM_RETURNCMD | api.TPM_NONOTIFY | api.TPM_BOTTOMALIGN,
                                   pt.x, pt.y, 0, self.hwnd, None)
        api.u.DestroyMenu(hmenu)                         # the submenu goes with it (it is owned by the menu)
        if cmd:
            self.dispatch(int(cmd))

    def dispatch(self, cmd: int) -> None:
        """A menu pick. Start/stop/restart/model run on a worker thread so the tray keeps answering the shell
        while the model loads (30-90 s) or releases the card."""
        api = self.api
        if cmd == ID_OPEN:
            self.ctl.log(f"menu: opening {self.ctl.url()}")
            self.open_page(self.ctl.url())
        elif cmd in (ID_START, ID_STOP, ID_RESTART) or ID_MODEL_BASE <= cmd:
            t = threading.Thread(target=self._run_server_action, args=(cmd,), daemon=True, name="tray-server")
            self.action_threads.append(t)
            t.start()
        elif cmd == ID_AUTOSTART:
            on = not self.ctl.autostart_on()
            ok, msg = self.set_autostart(on)
            self.ctl.log(f"menu: start at sign-in {'on' if on else 'off'}: {msg}")
            self.balloon(("AryaStrata starts at sign-in" if on else "AryaStrata starts when you start it"), msg[:255],
                         "info")
            self.apply_state()
        elif cmd == ID_LOG:
            self.open_log()
        elif cmd == ID_QUIT:
            self.quit_tray()

    def _run_server_action(self, cmd: int) -> None:
        api = self.api
        model = None
        if cmd >= ID_MODEL_BASE:
            models = self.ctl.configs()
            i = cmd - ID_MODEL_BASE
            model = None
            if 0 <= i < len(models):
                model = models[i].stem[len("strata-"):]
        if cmd == ID_START:
            ok, detail = self.ctl.start(model=model)
        elif cmd == ID_RESTART or cmd >= ID_MODEL_BASE:
            ok, detail = self.ctl.restart(model=model)
        else:
            ok, detail = self.ctl.stop()
            self.stop_asked = True
        self.ctl.log(f"menu: {'ok' if ok else detail.get('message', '')}")
        self.apply_state()

    # ---- the log and the sign-in entry
    def open_log(self) -> None:
        p = self.ctl.log_path
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8")
        os.startfile(str(p))                             # the shell's own "open this file" (Notepad, by default)

    def set_autostart(self, on: bool):
        return self.ctl.set_autostart(on)

    # ---- state
    def apply_state(self) -> None:
        """The icon, tooltip and any balloon for the state the status thread found."""
        prev, (state, detail) = self.state, self.ctl.status()
        if state == prev and detail.get("code") == self.detail.get("code"):
            return
        asked = self.stop_asked
        self.state, self.detail = state, detail
        self.update_icon(icon_kind(state), tip_text(state, detail, self.ctl.model_name()))
        note = balloon_for(prev, state, detail, self.ctl.model_name(), asked_to_stop=asked)
        if note:
            self.balloon(*note)
            self.ctl.log(f"state: {state}")

    def poll_loop(self) -> None:
        while not self.quitting:
            try:
                self.api.u.PostMessageW(self.hwnd, self.api.WM_POLL, 0, 0)
            except OSError:
                return
            time.sleep(2.5)

    # ---- running
    def load_icons(self) -> None:
        """One icon handle per state, taken from the .ico files (ExtractIconExW: LoadImageW will not read them -
        measured here).  The 16 px extract is the tray's own size; the larger one is its fallback."""
        api, wintypes = self.api, self.api.wintypes
        for kind, path in self.icon_paths.items():
            if not api.shell.ExtractIconExW(str(path), -1, None, None, 0):
                raise OSError(f"the tray icon {path.name} has no icon in it")
            big, small = wintypes.HICON(), wintypes.HICON()
            if not api.shell.ExtractIconExW(str(path), 0, ctypes.byref(big), ctypes.byref(small), 1):
                raise OSError(f"the tray icon {path.name} could not be loaded")
            self.hicons[kind] = small or big

    def run(self) -> int:
        api, wintypes = self.api, self.api.wintypes
        self.load_icons()
        self.mutex = api.k.CreateMutexW(None, False, "Local\\AryaStrataTray")
        if api.k.GetLastError() == api.ERROR_ALREADY_EXISTS:
            self.ctl.log("another AryaStrata tray icon is already running: nothing to do")
            return 0
        self.create_window()
        self.add_icon()
        self.apply_state()
        self.ctl.log(f"tray: the icon is up ({self.state})")
        self.poll_thread = threading.Thread(target=self.poll_loop, daemon=True, name="tray-poll")
        self.poll_thread.start()
        msg = wintypes.MSG()
        while True:
            got = api.u.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got <= 0:                                  # 0 = WM_QUIT (our quit path), -1 = a window-station error
                break
            api.u.TranslateMessage(ctypes.byref(msg))
            api.u.DispatchMessageW(ctypes.byref(msg))
        self.close()
        return 0

    def quit_tray(self) -> None:
        """Stop the model first (Ctrl+C's path, so sessions are saved), then close the icon.  If the server will
        not come down, closing this tray closes its job handle, and Windows ends the server and the engine:
        nothing is left holding the card (docs/TRAY.md)."""
        if self.quitting:
            return
        self.quitting = True
        self.stop_asked = True
        self.ctl.log("menu: Quit AryaStrata")
        self.update_icon("stopping", tip_text(STOPPING, self.detail, self.ctl.model_name()))
        self.remove_icon()
        t = threading.Thread(target=self._finish_quit, daemon=True, name="tray-quit")
        self.action_threads.append(t)
        t.start()

    def join_actions(self, timeout: float = 5.0) -> None:
        """Wait for the menu's start/stop/restart/quit work to finish: the tray answers the shell while that runs,
        and this is the seam the checks use to see the outcome."""
        for t in list(self.action_threads):
            t.join(timeout)

    def _finish_quit(self) -> None:
        ok, detail = self.ctl.stop(wait_s=25.0)
        self.ctl.log(f"quit: {'the model stopped' if ok else detail.get('message', '')}")
        self.api.u.PostMessageW(self.hwnd, self.api.WM_QUIT, 0, 0)

    def close(self) -> None:
        api = self.api
        self.quitting = True                             # the status thread stops on this flag
        t = getattr(self, "poll_thread", None)
        if t is not None and t is not threading.current_thread():
            t.join(timeout=4.0)                          # it posts to our window: let it finish before DestroyWindow
        self.join_actions(timeout=2.0)                   # a menu action still running touches the icon too
        self.remove_icon()
        for h in self.hicons.values():
            api.u.DestroyIcon(h)
        if self.hwnd_created:
            api.u.DestroyWindow(self.hwnd)
        if self.mutex:
            api.k.CloseHandle(self.mutex)
        self.ctl.log("tray: closed")
        self.ctl.close_log()


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="draw every state's icon and print the menu, then exit")
    ap.add_argument("--status", action="store_true", help="print the state the tray would show, then exit")
    a = ap.parse_args(argv)
    if sys.stdout is None:                              # pythonw.exe has no console: nothing to print to
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if a.status:
        ctl = ServerController()
        state, detail = ctl.status()
        print(f"{state}\n{tip_text(state, detail, ctl.model_name())}")
        return 0
    if a.check:
        where = icon_dir()
        made = write_icons(where)
        print(f"icons: {', '.join(sorted(p.name for p in made.values()))} in {where}")
        for state in (STOPPED, STARTING, READY, UNLOADED, CRASHED, EXTERNAL, NO_CONFIG):
            print(f"menu for {state}: " + " | ".join(
                ("[" + i["label"] + "]" if i["kind"] == "submenu" else i.get("label", "-"))
                for i in menu_items(state, autostart=True, models=["iq3_xxs", "swift-iq3_xxs"], running="iq3_xxs")))
        return 0
    if os.name != "nt":
        print(WINDOWS_ONLY)
        return 1
    ctl = ServerController()
    app = TrayApp(ctl)
    try:
        return app.run()
    except OSError as e:                                # no window station (a service, a session 0 logon)
        print(f"AryaStrata's tray icon cannot be shown here: {e}")
        ctl.log(f"tray: the icon cannot be shown here: {e}")
        ctl.close_log()
        return 1


if __name__ == "__main__":
    sys.exit(main())
