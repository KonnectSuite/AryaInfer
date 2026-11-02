"""serve/tray.py: the tray icon's view (icon per state, tooltip, balloons, menu) and the notification-area shell
driven by a fake Win32 layer, so the icon, the menu, the balloons and every menu pick are checked without a desktop.

    python -m unittest serve.test_tray -v
"""
import ctypes
import os
import unittest
from ctypes import wintypes
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from serve.tray import (ACCENT, CRASHED, EXTERNAL, ID_AUTOSTART, ID_LOG, ID_MODEL, ID_MODEL_BASE, ID_OPEN,
                        ID_QUIT, ID_RESTART, ID_START, ID_STOP, INK, LETTER, NO_CONFIG, READY, STARTING, STOPPED,
                        STOPPING, TIP_LIMIT, UNLOADED, WINDOWS_ONLY, TrayApp, balloon_for, draw_icon, icon_dir,
                        icon_kind, main, menu_items, tip_text, write_icons)
from serve.trayctl import ServerController


class Recorder:
    def __init__(self, ret=None):
        self.calls, self.ret = [], ret

    def __call__(self, *a):
        self.calls.append(a)
        return self.ret


class FakeU:
    """user32: the calls the tray's menu and icons need, all recorded, none real."""

    def __init__(self, track_ret=0):
        self.menus, self.items = [], []
        self.track_ret = track_ret
        self.GetCursorPos = Recorder()
        self.SetForegroundWindow = Recorder()
        self.TrackPopupMenu = Recorder(ret=track_ret)
        self.CreatePopupMenu = lambda: "MENU"
        self.AppendMenuW = lambda hmenu, flags, mid, label: self.items.append((flags, mid, label))
        self.DestroyMenu = Recorder(ret=True)
        self.GetSystemMetrics = lambda n: 16
        self.LoadImageW = Recorder(ret=1)
        self.DestroyIcon = Recorder(ret=True)
        self.PostMessageW = Recorder(ret=True)


class FakeShell:
    """shell32: every notify call is recorded as a snapshot of the struct's fields taken at the call itself -
    the tray passes byref(nid) and nid belongs to the caller, so reading it later would see recycled memory.
    ExtractIconExW fills the out-icons the way the shell does, so load_icons has handles to keep."""

    def __init__(self, api):
        import ctypes
        from ctypes import POINTER, cast
        from ctypes.wintypes import HICON
        self.calls, self.extract_calls = [], []

        def notify(op, nid_ref):
            nid = cast(nid_ref, POINTER(api.NOTIFYICONDATAW)).contents
            snap = SimpleNamespace(op=op, uFlags=nid.uFlags, uID=nid.uID, uVersion=nid.uVersion,
                                   hIcon=nid.hIcon, szTip=nid.szTip, szInfo=nid.szInfo,
                                   szInfoTitle=nid.szInfoTitle, dwInfoFlags=nid.dwInfoFlags)
            self.calls.append((op, snap))
            return True

        def extract(path, index, big, small, n):
            if index >= 0:
                for p in (big, small):
                    if p is not None:
                        cast(p, POINTER(HICON))[0] = 0x5A72A7E        # the fake "the shell made a handle"
            self.extract_calls.append((str(path), index))
            return 1

        notify.calls = self.calls                                      # so a test can read the recorded calls
        self.Shell_NotifyIconW = notify
        self.ExtractIconExW = extract


class FakeK:
    def __init__(self):
        self.GetLastError = lambda: 0
        self.CreateMutexW = lambda *a: 1
        self.CloseHandle = Recorder()
        self.GetModuleHandleW = lambda n=None: 1


class FakeApi:
    """The tray's Win32 seam: the real constants and types, the calls as recorders."""

    def __init__(self, track_ret=0):
        from serve.tray import windows_api
        real = windows_api()
        for name in dir(real):
            if name.isupper():
                setattr(self, name, getattr(real, name))
        self.wintypes = wintypes
        self.ctypes = ctypes
        self.u, self.k = FakeU(track_ret), FakeK()
        self.shell = FakeShell(self)


class FakeCtl:
    """The tray's controller seam: a model that answers exactly what a test wants it to say."""

    def __init__(self, state=READY, detail=None, model="iq3_xxs", autostart=False):
        self.state, self.detail, self.model = state, detail or {"url": "http://127.0.0.1:8123/"}, model
        self.autostart = autostart
        self.log_lines, self.calls = [], []
        self.log_path = Path("logs") / "tray.log"          # never opened by these checks
        self.stop_result = (True, {"code": 0})

    def status(self):
        return self.state, self.detail

    def model_name(self):
        return self.model

    def configs(self):
        return []

    def url(self):
        return self.detail.get("url", "")

    def log(self, line):
        self.log_lines.append(line)

    def close_log(self):
        pass

    def autostart_on(self):
        return self.autostart

    def set_autostart(self, on):
        self.autostart = on
        self.calls.append(("autostart", on))
        return True, "the sign-in entry is in the Startup folder" if on else "the sign-in entry was removed"

    def start(self, model=None, config_path=None, open_browser=False):
        self.calls.append(("start", model))
        return True, {"port": 8123}

    def stop(self, wait_s=20.0):
        self.calls.append(("stop",))
        return self.stop_result

    def restart(self, model=None):
        self.calls.append(("restart", model))
        return True, {"port": 8123}


def tray(state=READY, detail=None, autostart=False, track_ret=0):
    tmp = TemporaryDirectory()
    CLEANUP.append(tmp)
    ctl = FakeCtl(state=state, detail=detail, autostart=autostart)
    app = TrayApp(ctl, api=FakeApi(track_ret), open_page=lambda u: opened.append(u), icon_dir=Path(tmp.name))
    app.load_icons()                                       # the fake LoadImageW hands back a handle per state
    return app


opened = []
CLEANUP = []          # the icon folders the tray helper made, removed with the test (no implicit cleanup warning)


class ViewTests(unittest.TestCase):
    def tearDown(self):
        for t in CLEANUP:
            t.cleanup()
        CLEANUP.clear()

    def test_every_state_gets_its_own_icon_and_the_unknown_ones_the_idle_one(self):
        self.assertEqual(icon_kind(READY), "ready")
        self.assertEqual(icon_kind(STARTING), "starting")
        self.assertEqual(icon_kind(CRASHED), "crashed")
        self.assertEqual(icon_kind(EXTERNAL), "external")
        self.assertEqual(icon_kind(STOPPED), "idle")
        self.assertEqual(icon_kind(NO_CONFIG), "idle")
        self.assertEqual(icon_kind("something new"), "idle")

    def test_the_tooltip_fits_the_shells_own_limit_and_names_the_url_when_it_matters(self):
        detail = {"url": "http://127.0.0.1:8080/", "port": 8080}
        for state in (READY, STARTING, UNLOADED, STOPPING, CRASHED, EXTERNAL, NO_CONFIG, STOPPED):
            t = tip_text(state, detail, "Flash Next")
            self.assertLessEqual(len(t), TIP_LIMIT, f"{state}: {t}")
            self.assertTrue(t.startswith("AryaStrata"), state)
        self.assertIn("http://127.0.0.1:8080/", tip_text(READY, detail, "Flash Next"))
        self.assertIn("exit 3", tip_text(CRASHED, {"code": 3}))
        self.assertIn("outside the tray", tip_text(EXTERNAL, detail))

    def test_the_balloons_say_what_changed_and_stay_quiet_when_nothing_did(self):
        detail = {"url": "http://127.0.0.1:8080/"}
        self.assertIsNone(balloon_for(READY, READY, detail))
        self.assertIsNone(balloon_for(None, READY, detail))              # the icon's first read: no balloon
        t, b, kind = balloon_for(STARTING, READY, detail, "Flash Next")
        self.assertEqual((kind, "Flash Next" in b), ("info", True))
        self.assertEqual(balloon_for(STARTING, CRASHED, {"code": 3})[2], "error")
        self.assertEqual(balloon_for(READY, STOPPED, detail, asked_to_stop=True)[2], "info")
        self.assertEqual(balloon_for(READY, STOPPED, detail, asked_to_stop=False)[2], "warning")
        self.assertEqual(balloon_for(READY, NO_CONFIG, detail)[2], "warning")
        self.assertEqual(balloon_for(READY, EXTERNAL, detail)[2], "info")
        title, body, kind = balloon_for(STARTING, CRASHED, {"code": 3})
        self.assertIn("logs/tray.log", body)                 # the balloon points at the log, as the tooltip does

    def test_the_menu_enables_only_what_the_state_allows(self):
        def ids(state, models=("iq3_xxs",)):
            return {i["id"]: i for i in menu_items(state, models=list(models))}
        m = ids(READY)
        self.assertTrue(m[ID_OPEN]["enabled"] and m[ID_STOP]["enabled"] and m[ID_RESTART]["enabled"])
        self.assertFalse(m[ID_START]["enabled"])                          # it is up: nothing to start
        m = ids(STARTING)
        self.assertTrue(m[ID_STOP]["enabled"])                            # loading, and it can be asked to stop
        self.assertFalse(m[ID_START]["enabled"])
        m = ids(STOPPED)
        self.assertTrue(m[ID_START]["enabled"] and m[ID_STOP]["enabled"] is False)
        self.assertFalse(m[ID_OPEN]["enabled"])                           # nothing to open
        m = ids(EXTERNAL)
        self.assertTrue(m[ID_OPEN]["enabled"])
        self.assertFalse(m[ID_STOP]["enabled"] or m[ID_RESTART]["enabled"])  # not the tray's server to stop
        m = ids(NO_CONFIG, models=())
        self.assertFalse(m[ID_START]["enabled"])                          # nothing installed to start

    def test_the_model_submenu_appears_only_when_there_is_a_choice(self):
        one = menu_items(READY, models=["iq3_xxs"])
        self.assertNotIn(ID_MODEL, [i["id"] for i in one])
        two = [i for i in menu_items(READY, models=["iq3_xxs", "swift-iq3_xxs"], running="swift-iq3_xxs")
               if i["id"] == ID_MODEL]
        self.assertEqual(len(two), 1)
        labels = [m["label"] for m in two[0]["submenu"]]
        checked = [m["checked"] for m in two[0]["submenu"]]
        self.assertEqual(labels, ["iq3_xxs", "swift-iq3_xxs"])
        self.assertEqual(checked, [False, True])
        self.assertTrue(two[0]["enabled"])
        self.assertFalse([i for i in menu_items(EXTERNAL, models=["a", "b"]) if i["id"] == ID_MODEL][0]["enabled"])

    def test_the_quit_item_always_says_what_it_does(self):
        for state in (READY, STOPPED, CRASHED, STARTING, EXTERNAL):
            quit_item = [i for i in menu_items(state) if i["id"] == ID_QUIT][0]
            self.assertIn("stop", quit_item["label"].lower())
            self.assertTrue(quit_item["enabled"])

    def test_the_icon_is_the_mark_on_the_dark_ground_framed_in_the_state_colour(self):
        kinds = list(ACCENT)
        borders = []
        for kind in kinds:
            img = draw_icon(kind, 48)
            self.assertEqual(img.size, (48, 48))
            self.assertEqual(img.getpixel((24, 0)), ACCENT[kind] + (255,), f"{kind} frame")   # the top edge
            self.assertEqual(img.getpixel((0, 0))[3], 0)                                        # the corners are round
            self.assertIn(INK, [img.getpixel((24, 24))[0:3], img.getpixel((6, 6))[0:3]])
            borders.append(ACCENT[kind])
        self.assertEqual(len(set(borders)), len(kinds))                   # every state reads as its own colour
        letter = draw_icon("ready", 48)
        self.assertIn(LETTER, [letter.getpixel((x, y))[0:3] for x in range(12, 36) for y in range(12, 36)])

    def test_the_icons_are_written_once_as_a_shell_can_load_them(self):
        with TemporaryDirectory() as d:
            made = write_icons(Path(d))
            self.assertEqual(sorted(made), sorted(("idle", "starting", "ready", "unloaded", "stopping",
                                                   "crashed", "external")))
            for kind, p in made.items():
                self.assertTrue(p.exists() and p.name == f"aryastrata-{kind}.ico")
                head = p.read_bytes()[:6]
                self.assertEqual(head[:4], b"\x00\x00\x01\x00")           # a real .ico (the shell loads it by name)
            from PIL import Image
            with Image.open(made["ready"]) as im:
                self.assertEqual(len(im.info["sizes"]), 4)
            # the tray reads its icons with ExtractIconExW (LoadImageW returns NULL on these files: measured on
            # the real shell), so the load calls are pinned here: a count, then index 0, for every state
            app = tray(state=READY)
            per = app.api.shell.extract_calls
            self.assertEqual(len(per), 2 * len(made))
            self.assertTrue(all(str(p).endswith(".ico") for p, _ in per))
            self.assertEqual([i for _, i in per], [-1, 0] * len(made))    # count, then take, per state
            self.assertEqual(len(app.hicons), len(made))
            self.assertTrue(all(app.hicons.values()))                     # every state got a handle


class ShellTests(unittest.TestCase):
    def setUp(self):
        opened.clear()

    def tearDown(self):
        for t in CLEANUP:
            t.cleanup()
        CLEANUP.clear()

    def test_the_icon_starts_idle_and_the_state_change_writes_icon_tooltip_and_balloon(self):
        app = tray(state=READY)
        app.add_icon()
        shell = app.api.shell
        add = shell.Shell_NotifyIconW.calls[0]
        self.assertEqual(add[0], app.api.NIM_ADD)
        self.assertTrue(add[1].uFlags & app.api.NIF_MESSAGE and add[1].uFlags & app.api.NIF_ICON)
        # NIF_SHOWTIP in NIM_ADD makes the shell refuse the icon with E_FAIL (measured on this PC, Windows 11)
        self.assertFalse(add[1].uFlags & app.api.NIF_SHOWTIP)
        self.assertEqual(add[1].uVersion, app.api.SHELL_VERSION)          # NOTIFYICON_VERSION_4: balloons + tooltip
        self.assertEqual(app.api.SHELL_VERSION, 4)                         # there is no version 5: it is refused
        self.assertEqual(shell.Shell_NotifyIconW.calls[1][0], app.api.NIM_SETVERSION)
        app.state = STARTING                                                # the icon came up reading "starting"
        app.apply_state()                                                   # now READY: icon, tooltip, "ready" balloon
        kinds = [c[1].uFlags for c in shell.Shell_NotifyIconW.calls[2:]]
        self.assertIn(app.api.NIF_ICON | app.api.NIF_TIP | app.api.NIF_SHOWTIP, kinds)
        self.assertIn(app.api.NIF_INFO | app.api.NIF_SHOWTIP, kinds)
        info = [c[1] for c in shell.Shell_NotifyIconW.calls[2:] if c[1].uFlags & app.api.NIF_INFO][0]
        self.assertIn("ready", info.szInfoTitle)
        tip = [c[1] for c in shell.Shell_NotifyIconW.calls[2:] if c[1].uFlags & app.api.NIF_TIP][0]
        self.assertIn("8123", tip.szTip)
        app.close()

    def test_the_menu_is_the_menu_the_state_describes_and_the_pick_is_dispatched(self):
        app = tray(state=READY, autostart=True, track_ret=ID_OPEN)
        app.hwnd = 1
        app.show_menu()
        labels = [i[2] for i in app.api.u.items if i[2]]
        self.assertIn("Stop AryaStrata", labels)
        self.assertIn("Quit AryaStrata (and stop the model)", labels)
        self.assertIn("Start at sign-in", labels)
        flags = {i[2]: i[0] for i in app.api.u.items if i[2]}
        self.assertTrue(flags["Start AryaStrata"] & app.api.MF_GRAYED)     # it is up: starting is greyed out
        self.assertTrue(flags["Start at sign-in"] & app.api.MF_CHECKED)
        self.assertEqual(opened, ["http://127.0.0.1:8123/"])                # the pick above opened the page
        self.assertTrue(app.api.u.SetForegroundWindow.calls)              # so an outside click closes the menu
        app.close()

    def test_opening_the_page_and_toggling_the_sign_in_entry_come_straight_back(self):
        app = tray(state=READY)
        app.dispatch(ID_OPEN)
        self.assertEqual(opened, ["http://127.0.0.1:8123/"])
        app.dispatch(ID_AUTOSTART)
        self.assertEqual(app.ctl.autostart, True)
        self.assertTrue(any("sign-in on" in l for l in app.ctl.log_lines))
        app.close()

    def test_stop_restart_and_quit_run_off_the_trays_thread(self):
        app = tray(state=READY)
        app.dispatch(ID_STOP)
        app.join_actions()
        self.assertIn(("stop",), app.ctl.calls)
        app.dispatch(ID_RESTART)
        app.join_actions()
        self.assertIn(("restart", None), app.ctl.calls)
        app.dispatch(ID_QUIT)
        app.join_actions()
        self.assertTrue(app.quitting)
        self.assertIn(("stop",), app.ctl.calls)
        self.assertTrue(app.hicons)

    def test_a_model_pick_restarts_on_that_model(self):
        app = tray(state=READY)
        app.ctl.configs = lambda: [Path("C:/AryaStrata/strata-swift-iq3_xxs.json")]
        app.dispatch(ID_MODEL_BASE)
        app.join_actions()
        self.assertEqual(app.ctl.calls[-1], ("restart", "swift-iq3_xxs"))
        app.close()

    def test_the_double_click_opens_the_page_and_the_right_click_shows_the_menu(self):
        app = tray(state=READY, track_ret=0)
        app.hwnd = 1
        api = app.api
        app._wnd_proc(1, api.WM_TRAY, 0, api.WM_LBUTTONDBLCLK)
        self.assertEqual(len(opened), 1)
        app._wnd_proc(1, api.WM_TRAY, 0, api.WM_RBUTTONUP)
        self.assertTrue(app.api.u.TrackPopupMenu.calls)
        app._wnd_proc(1, api.WM_COMMAND, ID_STOP, 0)
        app.join_actions()
        self.assertIn(("stop",), app.ctl.calls)
        app.close()

    def test_the_windows_only_message_is_said_once_on_a_non_Windows_system(self):
        with mock.patch.object(os, "name", "posix"):
            out = __import__("io").StringIO()
            with mock.patch("sys.stdout", out):
                self.assertEqual(main([]), 1)
            self.assertIn("Windows", out.getvalue())
            self.assertIn("setup.sh", out.getvalue())

    def test_the_status_and_check_modes_report_the_state_and_the_icons_without_a_tray(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "strata-x.json").write_text('{"exe": "e", "port": 8123}', encoding="utf-8")
            ctl = ServerController(root=root, python_exe=Path(d) / "python.exe",
                                   log_path=root / "logs" / "tray.log")
            out = __import__("io").StringIO()
            with mock.patch("sys.stdout", out), mock.patch("serve.tray.ServerController", lambda: ctl):
                self.assertEqual(main(["--status"]), 0)
            self.assertIn("stopped", out.getvalue())
            with mock.patch("sys.stdout", out), mock.patch("serve.tray.icon_dir", lambda env=None: Path(d)):
                self.assertEqual(main(["--check"]), 0)
            self.assertIn("aryastrata-ready.ico", out.getvalue())
            ctl.close_log()


if __name__ == "__main__":
    unittest.main()
