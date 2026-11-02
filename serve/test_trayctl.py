"""serve/trayctl.py: the tray icon's model, its hidden start, its states, its graceful stop, its log and the
sign-in entry.  No GPU, no window station and no real server: the seams (popen, contain, probe, post, sleep, clock,
APPDATA) are handed the fakes, exactly as serve/test_keepawake.py hands the Windows call.

    python -m unittest serve.test_trayctl -v
"""
import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from serve.trayctl import (CRASHED, EXTERNAL, NO_CONFIG, READY, STARTING, STOPPED, STOPPING, UNLOADED,
                           ServerController, autostart_enabled, autostart_path, autostart_text, config_name,
                           config_port, dashboard_url, disable_autostart, enable_autostart, find_configs,
                           new_control_token, pythonw_for, read_config, server_command, startup_folder)


class FakeProc:
    """A subprocess.Popen stand-in: poll() answers from a list (the last value repeats)."""

    def __init__(self, codes=(None,), argv=None, kwargs=None):
        self.codes = list(codes)
        self.argv, self.kwargs = argv, kwargs
        self.killed = False

    def poll(self):
        return self.codes[0] if len(self.codes) == 1 else self.codes.pop(0)

    @property
    def returncode(self):
        return self.poll()

    def kill(self):
        self.killed = True


CREATED = []                                   # every controller a test made: their log handles are closed in tearDown


def controller(root, proc=None, codes=(None,), probe=lambda host, port, timeout=2.0: None, post=None,
               contain=lambda p: True, popen=None, log_cap=None):
    """A controller whose process, health answer and stop request are all fakes, logging into a temp folder, on a
    virtual clock: a sleep() moves the clock forward, so a stop's wait finishes at once in the tests."""
    made = []
    vtime = [0.0]

    def spawn(argv, **kwargs):
        p = proc if proc is not None else FakeProc(codes, argv, kwargs)
        made.append(p)
        return p

    c = ServerController(root=root, python_exe=Path(root) / ".venv" / "Scripts" / "python.exe",
                         log_path=Path(root) / "logs" / "tray.log",
                         popen=popen or spawn, contain=contain, probe=probe, post=post,
                         sleep=lambda s: vtime.__setitem__(0, vtime[0] + s), clock=lambda: vtime[0],
                         log_cap=2 * 1024 * 1024 if log_cap is None else log_cap)
    c.made = made
    CREATED.append(c)
    return c


def write_cfg(root, tag, **keys):
    p = Path(root) / f"strata-{tag}.json"
    p.write_text(json.dumps({"exe": "engine/strata.exe", "args": [], **keys}), encoding="utf-8")
    return p


class TrayctlTest(unittest.TestCase):
    """The log handles the controllers keep open are closed before the temp folders are removed (Windows refuses
    a file that is still open)."""

    def tearDown(self):
        for c in CREATED:
            c.close_log()
        CREATED.clear()

    def temp_root(self):
        """A folder of its own, cleaned up with the test (no implicit TemporaryDirectory cleanup warning)."""
        t = TemporaryDirectory()
        self.addCleanup(t.cleanup)
        return Path(t.name)


class CommandTests(TrayctlTest):
    def test_the_server_command_is_the_run_scripts_one_plus_the_tray_token(self):
        cmd = server_command("py.exe", "C:/AryaStrata", "C:/AryaStrata/strata-iq3_xxs.json", 8080,
                             control_token="a" * 32)
        self.assertEqual(cmd[0], "py.exe")
        self.assertEqual(Path(cmd[1]), Path("C:/AryaStrata/serve/server.py"))
        self.assertEqual(cmd[2:4], ["--engine", "strata"])
        self.assertEqual(Path(cmd[5]), Path("C:/AryaStrata/strata-iq3_xxs.json"))
        self.assertEqual(cmd[4], "--config")
        self.assertEqual(cmd[6:8], ["--port", "8080"])
        self.assertNotIn("--open", cmd)                                # the tray says "ready"; the menu opens the page
        self.assertEqual(cmd[8:], ["--control-token", "a" * 32])

    def test_open_browser_stays_the_run_scripts_option(self):
        cmd = server_command("py.exe", "R", "R/strata-x.json", 8080, open_browser=True)
        self.assertIn("--open", cmd)
        self.assertNotIn("--control-token", cmd)                       # asked for nothing: the plain start

    def test_the_token_is_random_per_run_and_long_enough_to_be_a_secret(self):
        a, b = new_control_token(), new_control_token()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 32)

    def test_the_dashboard_always_goes_through_loopback(self):
        self.assertEqual(dashboard_url("0.0.0.0", 8080), "http://127.0.0.1:8080/")
        self.assertEqual(dashboard_url("127.0.0.1", 8095), "http://127.0.0.1:8095/")
        self.assertEqual(dashboard_url("localhost", 8080), "http://127.0.0.1:8080/")

    def test_the_port_comes_from_the_config_and_falls_back_to_the_servers(self):
        self.assertEqual(config_port({"port": 8080}), 8080)
        self.assertEqual(config_port({}), 8095)
        self.assertEqual(config_port({"port": "not a number"}, 8095), 8095)
        self.assertEqual(config_port({"port": 0}), 8095)

    def test_the_model_name_is_the_configs_one_else_the_config_tag(self):
        self.assertEqual(config_name("strata-iq3_xxs.json", {"model_name": "Flash Next"}), "Flash Next")
        self.assertEqual(config_name("C:/x/strata-swift-iq3_xxs.json", {}), "swift-iq3_xxs")

    def test_pythonw_is_the_windowless_twin_when_it_is_there(self):
        with TemporaryDirectory() as d:
            s = Path(d) / "Scripts"
            s.mkdir()
            (s / "python.exe").write_text("")
            self.assertEqual(pythonw_for(s / "python.exe"), s / "python.exe")     # no pythonw: python.exe
            (s / "pythonw.exe").write_text("")
            self.assertEqual(pythonw_for(s / "python.exe"), s / "pythonw.exe")


class ConfigTests(TrayctlTest):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_the_configs_are_the_run_configs_newest_used_first(self):
        old = write_cfg(self.root, "old")
        new = write_cfg(self.root, "new")
        (self.root / "strata-old.json.bak-tune-1").write_text("{}", encoding="utf-8")
        (self.root / "strata-new.json.shared-settings.json").write_text("{}", encoding="utf-8")
        os.utime(old, (time.time() - 100, time.time() - 100))
        names = [p.name for p in find_configs(self.root)]
        self.assertEqual(names, ["strata-new.json", "strata-old.json"])

    def test_a_config_that_cannot_be_read_is_kept_and_reads_as_empty(self):
        write_cfg(self.root, "good")
        (self.root / "strata-broken.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(sorted(p.name for p in find_configs(self.root)),
                         ["strata-broken.json", "strata-good.json"])   # listed like setup lists it: the tray checks
        self.assertEqual(read_config(self.root / "strata-broken.json"), {})   # and says so, it does not fail


class StartTests(TrayctlTest):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        write_cfg(self.root, "iq3_xxs", port=8123)

    def test_start_runs_the_server_hidden_and_ties_it_to_the_tray(self):
        made = []

        def popen(argv, **kw):
            p = FakeProc((None,), argv, kw)
            made.append((p, kw))
            return p

        tied = []
        c = controller(self.root, popen=popen, contain=lambda p: tied.append(p) or True)
        ok, detail = c.start()
        self.assertTrue(ok)
        self.assertEqual(detail["port"], 8123)
        self.assertEqual(detail["model"], "iq3_xxs")
        proc, kw = made[0]
        argv = proc.argv
        self.assertEqual(argv[1], str(self.root / "serve" / "server.py"))
        self.assertIn("--control-token", argv)                         # the tray can stop what it started
        self.assertEqual(kw["cwd"], str(self.root))
        self.assertEqual(kw["stdout"], kw["stderr"])                  # the whole console output goes to the log
        self.assertEqual(kw["stdout"], c.log_handle())
        self.assertTrue(kw["creationflags"] & 0x00000008)              # DETACHED_PROCESS: no console window
        self.assertTrue(kw["creationflags"] & 0x00000200)              # CREATE_NEW_PROCESS_GROUP
        self.assertEqual(tied, [proc])                                 # serve/winjob.contain: it dies with the tray

    def test_start_refuses_to_run_two_servers_and_to_start_without_a_model(self):
        c = controller(self.root)
        self.assertTrue(c.start()[0])
        ok, detail = c.start()
        self.assertFalse(ok)
        self.assertIn("already", detail["message"])
        empty = self.temp_root()
        c2 = controller(empty)
        ok, detail = c2.start()
        self.assertFalse(ok)
        self.assertIn("no model is installed", detail["message"])

    def test_start_refuses_a_config_without_an_engine_and_a_name_that_is_not_installed(self):
        (self.root / "strata-nogpu.json").write_text(json.dumps({"args": []}), encoding="utf-8")
        c = controller(self.root)
        ok, detail = c.start(config_path=self.root / "strata-nogpu.json")
        self.assertFalse(ok)
        self.assertIn("no engine", detail["message"])
        ok, detail = c.start(config_path=self.root / "strata-swift.json")
        self.assertFalse(ok)
        self.assertIn("not an installed model", detail["message"])

    def test_a_start_that_cannot_launch_says_so_and_leaves_no_half_started_model(self):
        def popen(argv, **kw):
            raise OSError("the engine's file is missing")
        c = controller(self.root, popen=popen)
        ok, detail = c.start()
        self.assertFalse(ok)
        self.assertIn("could not start", detail["message"])
        self.assertIsNone(c.proc)
        self.assertEqual(c.status()[0], STOPPED)


class StatusTests(TrayctlTest):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        write_cfg(self.root, "iq3_xxs", port=8123)

    def test_a_live_child_that_does_not_answer_yet_is_the_model_loading(self):
        c = controller(self.root, proc=FakeProc((None,)))
        c.start()
        state, detail = c.status()
        self.assertEqual(state, STARTING)
        self.assertEqual(detail["model"], "iq3_xxs")
        self.assertTrue(detail["url"].endswith(":8123/"))

    def test_the_states_are_what_health_says_plus_the_exit_code(self):
        c = controller(self.root, proc=FakeProc((None,)), probe=lambda h, p, timeout=2.0: {"loaded": True})
        c.start()
        self.assertEqual(c.status()[0], READY)
        self.assertTrue(c.ready())
        c2 = controller(self.root, proc=FakeProc((None,)), probe=lambda h, p, timeout=2.0: {"loaded": False})
        c2.start()
        self.assertEqual(c2.status()[0], UNLOADED)

    def test_a_child_that_ends_is_stopped_crashed_or_still_stopping(self):
        c = controller(self.root, proc=FakeProc((None, 0)))
        c.start()
        c.stop_asked = True
        self.assertEqual(c.status()[0], STOPPING)                      # asked, and the child has not ended yet
        c.proc = FakeProc((0,))
        self.assertEqual(c.status()[0], STOPPED)
        c.proc = FakeProc((3,))
        self.assertEqual(c.status()[0], CRASHED)
        self.assertEqual(c.status()[1]["code"], 3)

    def test_a_port_that_answers_without_being_ours_is_running_outside_the_tray(self):
        c = controller(self.root, probe=lambda h, p, timeout=2.0: {"loaded": True})
        self.assertEqual(c.status()[0], EXTERNAL)
        self.assertEqual(c.status()[1]["health"], {"loaded": True})

    def test_a_folder_with_no_installed_model_says_so(self):
        c = controller(self.temp_root())
        self.assertEqual(c.status()[0], NO_CONFIG)

    def test_the_log_rolls_over_at_the_cap_and_keeps_the_last_run(self):
        c = controller(self.root, log_cap=40)
        c.log("a" * 60)
        c.close_log()
        c.log("b" * 60)                                                 # past the cap: the next handle rolls it
        self.assertTrue(c.log_path.with_name("tray.log.1").exists())
        new = c.log_path.read_text(encoding="utf-8")
        old = c.log_path.with_name("tray.log.1").read_text(encoding="utf-8")
        self.assertIn("b" * 60, new)
        self.assertNotIn("a" * 60, new)
        self.assertIn("a" * 60, old)

    def test_a_log_that_cannot_be_written_never_stops_the_model(self):
        c = controller(self.root)
        with mock.patch.object(c, "log_handle", side_effect=OSError("the disk is full")):
            c.log("this must not raise")
        c.close_log()


class StopTests(TrayctlTest):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        write_cfg(self.root, "iq3_xxs", port=8123)

    def test_stop_asks_once_waits_for_the_exit_and_reports_it(self):
        proc = FakeProc((None, 0))
        asked = []
        c = controller(self.root, proc=proc, post=lambda: asked.append(1) or True)
        c.start()
        ok, detail = c.stop()
        self.assertTrue(ok)
        self.assertEqual(detail["code"], 0)
        self.assertTrue(detail["graceful"])
        self.assertEqual(len(asked), 1)                                # one request, not a kill

    def test_stop_says_what_it_cannot_do(self):
        c = controller(self.root, probe=lambda h, p, timeout=2.0: {"loaded": True})
        ok, detail = c.stop()
        self.assertFalse(ok)
        self.assertIn("outside the tray", detail["message"])           # it has no token for that server
        c2 = controller(self.root)
        ok, detail = c2.stop()
        self.assertFalse(ok)
        self.assertIn("not running", detail["message"])

    def test_a_stop_that_the_server_ignores_leaves_it_running_and_says_so(self):
        c = controller(self.root, proc=FakeProc((None,)), post=lambda: True)
        c.start()
        ok, detail = c.stop(wait_s=0.5)
        self.assertFalse(ok)
        self.assertIn("taking its time", detail["message"])

    def test_a_failed_stop_request_does_not_leave_the_tray_thinking_it_stopped(self):
        c = controller(self.root, proc=FakeProc((None,)), post=lambda: False)
        c.start()
        ok, detail = c.stop(wait_s=0.2)
        self.assertFalse(ok)
        self.assertIn("keeps running", detail["message"])
        self.assertFalse(c.stop_asked)

    def test_restart_stops_first_and_never_starts_a_second_server_on_top_of_it(self):
        c = controller(self.root, codes=(None, 0), post=lambda: True)
        c.start()
        ok, detail = c.restart()
        self.assertTrue(ok, detail)
        self.assertEqual(len(c.made), 2)                                # the start's server, then the restart's
        c2 = controller(self.root, codes=(None,), post=lambda: True)    # a server that will not come down
        c2.start()
        ok, detail = c2.restart()
        self.assertFalse(ok)
        self.assertIn("taking its time", detail["message"])
        self.assertEqual(len(c2.made), 1)                               # and nothing was started on top of it

    def test_the_stop_request_is_json_from_loopback_with_the_tray_token(self):
        seen = []

        def urlopen(req, timeout=None):
            seen.append(req)

            class R:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self):
                    return b'{"status":"stopping"}'
            return R()

        with TemporaryDirectory() as d:
            root = Path(d)
            write_cfg(root, "iq3_xxs", port=8123)
            c = controller(root)
            c.start()
            token = c.token
            try:
                with mock.patch("urllib.request.urlopen", side_effect=urlopen):
                    self.assertTrue(c.post_shutdown())
            finally:
                c.close_log()                                          # Windows: the temp folder goes after the log
        req = seen[0]
        self.assertEqual(req.full_url, "http://127.0.0.1:8123/api/shutdown")   # loopback only
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.get_header("Content-type"), "application/json")   # no plain form shuts the model down
        # urllib stores header names capitalized; HTTP and the server read them case-insensitively
        self.assertEqual(req.get_header("X-aryastrata-control"), token)


class AutoStartTests(TrayctlTest):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.appdata = Path(self.tmp.name)
        self.env = {"APPDATA": str(self.appdata)}
        self.addCleanup(self.tmp.cleanup)

    def test_the_sign_in_entry_is_the_tray_with_no_window(self):
        text = autostart_text("C:/AryaStrata/.venv/Scripts/pythonw.exe", "C:/AryaStrata/serve/tray.py")
        self.assertIn('CreateObject("WScript.Shell").Run', text)
        self.assertIn("pythonw.exe", text)                             # windowless: pythonw, not python
        self.assertIn("tray.py", text)                                 # the tray icon itself, no arguments
        self.assertTrue(text.rstrip().endswith(", 0, False"))          # window 0: nothing shows up at sign-in
        run = [ln for ln in text.splitlines() if ln.startswith("CreateObject")][0]
        # VBScript's "" is one quote, so the two quoted paths are written """path"" ""path""" - a Run line with the
        # wrong quote count is a syntax error and starts nothing (measured on the real launcher)
        self.assertEqual(run, 'CreateObject("WScript.Shell").Run '
                              '"""C:\\AryaStrata\\.venv\\Scripts\\pythonw.exe"" '
                              '""C:\\AryaStrata\\serve\\tray.py""", 0, False')

    def test_the_entry_is_written_to_the_startup_folder_and_removed_again(self):
        with mock.patch.dict(os.environ, self.env):
            self.assertFalse(autostart_enabled())
            p = enable_autostart("C:/py/pythonw.exe", "C:/AryaStrata/serve/tray.py")
            self.assertEqual(p, autostart_path())
            self.assertEqual(p.parent, startup_folder(self.env))       # written in the Startup folder, nowhere else
            self.assertTrue(p.parent.is_dir())                         # the folder is made when it is missing
            self.assertTrue(autostart_enabled())
            self.assertIn("pythonw.exe", p.read_text(encoding="utf-8"))
            self.assertTrue(disable_autostart())
            self.assertFalse(autostart_enabled())
            self.assertFalse(disable_autostart())                        # already gone: says so harmlessly

    def test_the_controllers_own_toggle_is_the_same_entry(self):
        root = Path(self.tmp.name)
        write_cfg(root, "iq3_xxs")
        c = controller(root)
        with mock.patch.dict(os.environ, self.env):
            ok, msg = c.set_autostart(True)
            self.assertTrue(ok, msg)
            self.assertTrue(c.autostart_on())
            ok, msg = c.set_autostart(False)
            self.assertTrue(ok, msg)
            self.assertFalse(c.autostart_on())

    def test_no_AppData_means_no_sign_in_entry(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(enable_autostart("pythonw.exe", "tray.py"))
            self.assertFalse(autostart_enabled())


if __name__ == "__main__":
    unittest.main()
