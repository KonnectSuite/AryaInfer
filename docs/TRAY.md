# The tray icon (Windows)

AryaStrata in the Windows notification area: the model runs with no console window to close by accident, and the
icon is where it is started, stopped, restarted and switched. Windows only; Linux runs it from a terminal as before.

## Starting it

- Double-click **`AryaStrata-Tray.vbs`** in the install folder (setup writes it at the end of an install), or
- run `pythonw serve\tray.py` (no window: `pythonw`, not `python`).

Setup also offers to start the tray icon **at sign-in**: a `.vbs` in the user's Startup folder. The offer is off by
default, so `START-HERE.bat` and `run-<model>.bat` stay the way AryaStrata has always started; the icon's own
**Start at sign-in** item turns the entry on and off later with no setup run. (A Startup-folder entry was chosen
over Task Scheduler because Task Scheduler's default start was measured at 0.05 GiB/s on this PC against 1.42-1.52
GiB/s for a double-click: [DETAILS.md](DETAILS.md#running-it-at-startup-task-scheduler).)

## The menu

| Item | What it does |
| --- | --- |
| Open AryaStrata | Opens the web app, `http://127.0.0.1:<port>/` from the config |
| Start AryaStrata | Starts the model hidden, in a job that ends with the icon |
| Stop AryaStrata | Stops it the way Ctrl+C would, then waits for the card to be free |
| Restart AryaStrata | Stop, then start again on the same model |
| Model | Only when more than one model is installed: switch by restarting on it |
| Start at sign-in | Writes or removes the Startup-folder entry |
| Open the log | `logs\tray.log`, the server's whole console output and the tray's own lines |
| Quit AryaStrata | Removes the icon and stops the model |

Items that do not apply to the current state are greyed out. Double-click opens the web app; right-click opens the
menu. The tooltip says the state and, when there is one, the address; a balloon announces ready, crashed (with the
exit code) and a server that is running outside the tray.

## The states

| Icon | State | Meaning |
| --- | --- | --- |
| grey | stopped | nothing is running |
| amber | starting | the child is alive, the model is loading (30-90 s) |
| teal | ready | `/health` answers with `loaded: true` |
| blue | unloaded | it answers, but the model is not loaded |
| dim blue | stopping | asked to stop; releasing the card |
| red | crashed | the child ended with a non-zero code |
| violet | running outside the tray | the port answers, and this icon did not start it: it is left alone |

## Stopping without a console

A hidden child has no window to send Ctrl+C to. The tray therefore starts the server with a random
`--control-token` and calls `POST /api/shutdown` on loopback, JSON, with the token in `X-AryaStrata-Control` (the
server exits with that flag missing: the endpoint does not exist). The request runs Ctrl+C's own `shutdown()`: the
engine's QUIT, the vision encoder, the MCP servers and the saved sessions. Quitting the icon also ends the child
through `serve/winjob.py`'s kill-on-close job, so killing the icon from Task Manager takes the engine with it
instead of leaving it holding the graphics card.

The tray's own lines go to `logs\tray.log` (rolled over once at 2 MiB to `tray.log.1`).

## What was measured here

Measured on this PC (Windows 11, i9-14900KF / RTX 4070 Ti SUPER) while building this:

- the seven icon files are written to `%LOCALAPPDATA%\AryaStrata` and read back with `ExtractIconExW`;
  `LoadImageW` returns NULL on these files (no error code), so it is not used;
- the icon starts under `pythonw`, adds itself to the notification area, and logs `tray: the icon is up`; the shell
  shows it in the overflow as an `AryaStrata` notification-area button with the state's own frame colour, read back
  through UI automation (the overflow window, `TopLevelWindowForOverflowXamlIsland`);
- a right-click on that icon opens the real menu: with a server running outside the tray, **Open AryaStrata** and
  **Quit** are enabled and **Start** / **Stop** / **Restart** are greyed out;
- a server running outside the tray on port 8080 shows as **running outside the tray** and is left alone;
- the sign-in entry is written and removed in the user's Startup folder (`AryaStrata (tray).vbs`), and the entry
  starts the icon when run;
- the whole cycle from the tray's own menu, on `swift-1.5-abliterated-iq3_xxs`, 262144-token context:
  - **Start**: `[strata] experts loaded: 39.97 GiB at 3.51 GiB/s`, **ready 30.1 s** after the pick, 14709 MiB of
    the card in use;
  - **Stop**: `POST /api/shutdown` answered, `[strata] stopped`, the child ended with exit 0 in **6.1 s**, no
    `strata.exe` or server process left, port 8080 free, the card back to 748 MiB;
  - **Restart**: ready again **27 s** after the pick, 14677 MiB;
  - **Quit**: model stopped (exit 0), icon and `pythonw` gone, card back to 784 MiB.

Two shell rules that a first version got wrong, both measured on this PC: `NIF_SHOWTIP` must not be part of
`NIM_ADD` (the add fails with `E_FAIL` and no icon appears), and the shell version is `NOTIFYICON_VERSION_4`
(asking for 5 fails).
