"""Starts Glib: a small local server plus an app window.

Built to start reliably on ordinary Windows PCs:
- everything is logged to the data folder from the very first line, and any startup failure is
  shown in a message box instead of failing silently;
- the window opens straight away on a 'starting' page and switches to Glib once it is ready
  (the first start can be slow while antivirus software checks the new files);
- if the usual port is reserved or taken (Docker, WSL and Hyper-V often reserve port ranges),
  Glib picks a free one and remembers it so a second launch finds the running copy.
"""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser

from . import config

PREFERRED_PORT = int(os.environ.get("GLIB_PORT", "8756"))
PORT_FILE = config.DATA / "glib.port"
LOG_FILE = config.DATA / "glib.log"


def _log_to_file():
    config.ensure_dirs()
    if sys.stdout is None or sys.stderr is None or not sys.stdout.isatty():
        try:
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 2_000_000:
                LOG_FILE.replace(LOG_FILE.with_suffix(".old.log"))
            log = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
            if sys.stdout is None or not sys.stdout.isatty():
                sys.stdout = log
            if sys.stderr is None or not sys.stderr.isatty():
                sys.stderr = log
        except Exception:
            pass
    print(f"\n=== Glib starting {time.strftime('%Y-%m-%d %H:%M:%S')} (Python {sys.version.split()[0]})", flush=True)


def message(text, title="Glib"):
    """A plain Windows message box (falls back to the log elsewhere)."""
    print(f"[message] {text}", flush=True)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)   # information icon
        except Exception:
            pass


def _is_glib(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/hello", timeout=1.5) as r:
            return b'"glib"' in r.read()
    except Exception:
        return False


def _saved_port():
    try:
        return int(PORT_FILE.read_text().strip())
    except Exception:
        return None


def _can_bind(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _choose_port():
    if _can_bind(PREFERRED_PORT):
        return PREFERRED_PORT
    for port in range(PREFERRED_PORT + 1, PREFERRED_PORT + 40):
        if _can_bind(port):
            return port
    s = socket.socket()
    s.bind(("127.0.0.1", 0))                       # let Windows pick any free port
    port = s.getsockname()[1]
    s.close()
    return port


def _starting_page(url):
    """A local page shown while Glib starts; it switches to Glib as soon as Glib answers."""
    page = config.DATA / "starting.html"
    page.write_text(f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Glib</title>
<style>body{{margin:0;height:100vh;display:grid;place-items:center;font:16px "Segoe UI",sans-serif;color:#193b77;background:#f6f7fb}}
.s{{width:28px;height:28px;border:3px solid #2ea8e6;border-right-color:transparent;border-radius:50%;animation:r 1s linear infinite;margin:0 auto 16px}}
@keyframes r{{to{{transform:rotate(360deg)}}}}p{{color:#66708a;text-align:center;max-width:420px}}</style></head>
<body><div><div class="s"></div><h2 style="text-align:center;margin:0 0 6px">Glib is starting…</h2>
<p id="m">The first start can take a minute while Windows and your antivirus check the new files.</p></div>
<script>
const url = {url!r}; let n = 0;
async function poll() {{
  try {{ await fetch(url + "api/hello", {{mode: "no-cors", cache: "no-store"}}); location.replace(url); return; }} catch (e) {{}}
  if (++n === 120) document.getElementById("m").textContent = "This is taking longer than usual. If nothing happens, close this window and open Glib again.";
  setTimeout(poll, 1000);
}}
poll();
</script></body></html>""", encoding="utf-8")
    return page.as_uri()


def open_window(target):
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
                subprocess.Popen([exe, f"--app={target}", "--window-size=1280,860"])
                print(f"window: {exe}", flush=True)
                return
            except Exception as e:
                print(f"window: {exe} failed: {e}", flush=True)
    print("window: default browser", flush=True)
    webbrowser.open(target)


def main():
    _log_to_file()
    try:
        # A copy of Glib is already running: just show its window.
        for port in {p for p in (_saved_port(), PREFERRED_PORT) if p}:
            if _is_glib(port):
                print(f"already running on port {port}", flush=True)
                open_window(f"http://127.0.0.1:{port}/")
                return

        port = _choose_port()
        url = f"http://127.0.0.1:{port}/"
        PORT_FILE.write_text(str(port))
        print(f"port {port}", flush=True)
        open_window(_starting_page(url))           # immediate feedback, before the slow imports

        import uvicorn
        from . import recorder, server

        def watch():
            """Close quietly once the window has been closed and no work is running.
            A closing window says goodbye; if it never does (crash, power cut), give up after a long
            silence. Minimised windows are slowed down by Windows, so silence alone must be long."""
            while True:
                time.sleep(5)
                busy = recorder.status()["on"] or any(j["state"] in ("queued", "running") for j in server.jobs.values())
                seen = server.last_seen
                if busy or not seen["ever"]:
                    continue
                quiet = time.time() - seen["t"]
                if (seen["bye"] and time.time() - seen["bye"] > 20 and quiet > 20) or quiet > 20 * 60:
                    print("window closed: stopping", flush=True)
                    os._exit(0)

        threading.Thread(target=watch, daemon=True).start()
        srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port,
                                            log_level="warning", log_config=None))
        srv.run()
        if not srv.started:
            raise RuntimeError(f"the local connection on port {port} could not be opened")
    except BaseException as e:   # noqa: BLE001  (show every startup failure, never fail silently)
        if isinstance(e, KeyboardInterrupt):
            return
        traceback.print_exc()
        message("Glib could not start.\n\n"
                f"What happened: {str(e) or e.__class__.__name__}\n\n"
                f"The details are saved in:\n{LOG_FILE}\n\n"
                "Please send that file so the problem can be fixed.", "Glib could not start")


if __name__ == "__main__":
    main()
