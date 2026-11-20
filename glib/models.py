"""Downloads the voice engines once. After that Glib works with no internet connection."""
import shutil
import tarfile
import threading
import urllib.request
from pathlib import Path

from . import config

GH = "https://github.com"
PARAKEET_DIR = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"

# name -> (url, file or folder under data/models, size in MB, what it is for)
FILES = {
    "listener": (f"{GH}/k2-fsa/sherpa-onnx/releases/download/asr-models/{PARAKEET_DIR}.tar.bz2",
                 PARAKEET_DIR, 630, "Listens to your recording and compares it with the script"),
    "reader": (f"{GH}/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
               "kokoro-v1.0.onnx", 310, "British reader used by Rebuild"),
    "reader_voices": (f"{GH}/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
                      "voices-v1.0.bin", 27, "Reader voices"),
    "converter": (f"{GH}/bshall/knn-vc/releases/download/v0.1/WavLM-Large.pt",
                  "WavLM-Large.pt", 1200, "Turns the reader into your voice tone"),
    "converter_out": (f"{GH}/bshall/knn-vc/releases/download/v0.1/prematch_g_02500000.pt",
                      "prematch_g_02500000.pt", 65, "Voice converter output stage"),
}

progress = {"running": False, "current": None, "done_mb": 0, "total_mb": 0, "error": None}
_lock = threading.Lock()


def path(name: str) -> Path:
    return config.MODELS / FILES[name][1]


def have(name: str) -> bool:
    p = path(name)
    return p.exists() and (any(p.iterdir()) if p.is_dir() else p.stat().st_size > 1000)


def status():
    return {
        "items": [{"name": n, "about": f[3], "mb": f[2], "ready": have(n)} for n, f in FILES.items()],
        "polish_ready": have("listener"),
        "rebuild_ready": all(have(n) for n in FILES),
        "missing_mb": sum(f[2] for n, f in FILES.items() if not have(n)),
        "progress": dict(progress),
    }


def _fetch(name: str):
    url, target, mb, _ = FILES[name]
    dest = config.MODELS / target
    tmp = config.MODELS / (Path(url).name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Glib"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or mb * 1e6)
        progress.update(current=name, done_mb=0, total_mb=round(total / 1e6))
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            progress["done_mb"] = round(got / 1e6)
        if got < total:
            raise IOError(f"download of {name} stopped early")
    if url.endswith(".tar.bz2"):
        progress["current"] = name + " (unpacking)"
        with tarfile.open(tmp) as t:
            t.extractall(config.MODELS, filter="data")
        tmp.unlink()
    else:
        shutil.move(tmp, dest)


def download_all(only=None):
    """Fetch whatever is missing. Safe to call again after an interruption."""
    with _lock:
        if progress["running"]:
            return
        progress.update(running=True, error=None)
    try:
        config.ensure_dirs()
        for name in FILES:
            if only and name not in only:
                continue
            if not have(name):
                _fetch(name)
    except Exception as e:  # shown to the user in plain words
        progress["error"] = f"Download stopped: {e}. Check the internet connection and press Download again."
    finally:
        progress.update(running=False, current=None)


def download_in_background(only=None):
    threading.Thread(target=download_all, args=(only,), daemon=True).start()


if __name__ == "__main__":
    import sys, time
    download_in_background()
    time.sleep(1)
    while progress["running"]:
        print(f"\r  {progress['current'] or ''}: {progress['done_mb']} / {progress['total_mb']} MB      ", end="", flush=True)
        time.sleep(1)
    print()
    if progress["error"]:
        print(progress["error"]); sys.exit(1)
    print("Voice engines are ready.")
