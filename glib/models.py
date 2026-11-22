"""Downloads the voice engines once. After that Glib works with no internet connection."""
import shutil
import tarfile
import threading
import urllib.request
from pathlib import Path

from . import config

GH = "https://github.com"
HF = "https://huggingface.co"
PARAKEET_DIR = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
# Chatterbox voice conversion (Resemble AI, MIT), ONNX export (Apache-2.0)
CB_Q8 = f"{HF}/TigreGotico/voiceclonnx-chatterbox/resolve/main/onnx"
CB_FP32 = f"{HF}/onnx-community/chatterbox-ONNX/resolve/main/onnx"

# name -> (url, file or folder under data/models, size in MB, what it is for)
FILES = {
    "listener": (f"{GH}/k2-fsa/sherpa-onnx/releases/download/asr-models/{PARAKEET_DIR}.tar.bz2",
                 PARAKEET_DIR, 630, "Listens to your recording and compares it with the script"),
    "denoiser": (f"{GH}/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/dpdfnet2_48khz_hr.onnx",
                 "dpdfnet2_48khz_hr.onnx", 11, "Removes background noise at full studio quality"),
    "reader": (f"{GH}/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
               "kokoro-v1.0.onnx", 310, "British reader used by Rebuild"),
    "reader_voices": (f"{GH}/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
                      "voices-v1.0.bin", 27, "Reader voices"),
    "converter_enc": (f"{CB_Q8}/speech_encoder_q8.onnx", "chatterbox/speech_encoder_q8.onnx", 216,
                      "Learns your voice"),
    "converter_dec": (f"{CB_Q8}/conditional_decoder_q8.onnx", "chatterbox/conditional_decoder_q8.onnx", 252,
                      "Speaks in your voice"),
    # higher-precision converter (Settings > Voice quality > Highest)
    "converter_enc_hq": (f"{CB_FP32}/speech_encoder.onnx", "chatterbox/speech_encoder.onnx", 2, ""),
    "converter_enc_hq_data": (f"{CB_FP32}/speech_encoder.onnx_data", "chatterbox/speech_encoder.onnx_data", 565, ""),
    "converter_dec_hq": (f"{CB_FP32}/conditional_decoder.onnx", "chatterbox/conditional_decoder.onnx", 2, ""),
    "converter_dec_hq_data": (f"{CB_FP32}/conditional_decoder.onnx_data", "chatterbox/conditional_decoder.onnx_data", 516, ""),
}

POLISH = ["listener", "denoiser"]


def rebuild_set(settings=None):
    s = settings or config.load()
    conv = (["converter_enc_hq", "converter_enc_hq_data", "converter_dec_hq", "converter_dec_hq_data"]
            if s.get("voice_quality") == "highest" else ["converter_enc", "converter_dec"])
    return ["reader", "reader_voices"] + conv


progress = {"running": False, "current": None, "done_mb": 0, "total_mb": 0, "error": None}
_lock = threading.Lock()


def path(name: str) -> Path:
    return config.MODELS / FILES[name][1]


def have(name: str) -> bool:
    p = path(name)
    return p.exists() and (any(p.iterdir()) if p.is_dir() else p.stat().st_size > 1000)


def needed(settings=None):
    return POLISH + rebuild_set(settings)


def status(settings=None):
    need = needed(settings)
    return {
        "items": [{"name": n, "about": FILES[n][3], "mb": FILES[n][2], "ready": have(n)} for n in need],
        "polish_ready": all(have(n) for n in POLISH if n != "denoiser"),
        "rebuild_ready": all(have(n) for n in rebuild_set(settings)) and have("listener"),
        "missing_mb": sum(FILES[n][2] for n in need if not have(n)),
        "progress": dict(progress),
    }


def _fetch(name: str):
    url, target, mb, _ = FILES[name]
    dest = config.MODELS / target
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / (Path(url).name + ".part")
    got = tmp.stat().st_size if tmp.exists() else 0          # resume an interrupted download
    req = urllib.request.Request(url, headers={"User-Agent": "Glib", **({"Range": f"bytes={got}-"} if got else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        if got and r.status != 206:                           # server ignored the range: start over
            got = 0
        total = got + int(r.headers.get("Content-Length") or mb * 1e6)
        progress.update(current=FILES[name][3] or name, done_mb=round(got / 1e6), total_mb=round(total / 1e6))
        with open(tmp, "ab" if got else "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                progress["done_mb"] = round(got / 1e6)
    if got < total:
        raise IOError("the download stopped early")
    if url.endswith(".tar.bz2"):
        progress["current"] = "Unpacking"
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
        for name in (only or needed()):
            if not have(name):
                _fetch(name)
    except Exception as e:  # shown to the user in plain words
        progress["error"] = f"Download stopped ({e}). Check the internet connection and press Download again; it continues where it stopped."
    finally:
        progress.update(running=False, current=None)


def download_in_background(only=None):
    threading.Thread(target=download_all, args=(only,), daemon=True).start()


if __name__ == "__main__":
    import sys
    import time
    download_in_background()
    time.sleep(1)
    while progress["running"]:
        print(f"\r  {progress['current'] or ''}: {progress['done_mb']} / {progress['total_mb']} MB      ", end="", flush=True)
        time.sleep(1)
    print()
    if progress["error"]:
        print(progress["error"])
        sys.exit(1)
    print("Voice engines are ready.")
