"""Starts Glib: a small local server plus an app window."""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from . import config

PORT = int(os.environ.get("GLIB_PORT", "8756"))
URL = f"http://127.0.0.1:{PORT}/"


def _already_running():
    try:
        with urllib.request.urlopen(URL + "api/devices", timeout=1.5):
            return True
    except Exception:
        return False


def open_window():
    """Open Glib in its own window (Edge or Chrome app mode); fall back to the normal browser."""
    if os.environ.get("GLIB_NO_WINDOW"):
        return
    candidates = [shutil.which("msedge"), shutil.which("chrome")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                           os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    for exe in candidates:
        if exe and os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={URL}", "--window-size=1280,860"])
                return
            except Exception:
                pass
    webbrowser.open(URL)


def main():
    config.ensure_dirs()
    if sys.stdout is None or sys.stderr is None:      # started without a console window
        log = open(config.DATA / "glib.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = log
    if _already_running():
        open_window()
        return
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            print(f"Port {PORT} is busy. Close the other program or set GLIB_PORT.")
            return
    import uvicorn
    from . import server

    def watch():   # close quietly a little while after the window is closed and no work is running
        while True:
            time.sleep(5)
            busy = any(j["state"] in ("queued", "running") for j in server.jobs.values())
            if server.last_seen["ever"] and not busy and time.time() - server.last_seen["t"] > 45:
                os._exit(0)

    threading.Thread(target=watch, daemon=True).start()
    threading.Timer(1.2, open_window).start()
    uvicorn.run(server.app, host="127.0.0.1", port=PORT, log_level="warning", log_config=None)


if __name__ == "__main__":
    main()
