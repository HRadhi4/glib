"""Paths and user settings. Everything Glib stores lives in the data folder next to the app."""
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("GLIB_DATA", ROOT / "data"))
MODELS = DATA / "models"
VOICE = DATA / "voice"
PROJECTS = DATA / "projects"
WEB = Path(__file__).resolve().parent / "web"
SETTINGS_FILE = DATA / "settings.json"

SR = 48000  # working sample rate for recordings and exports

DEFAULTS = {
    "listener": "parakeet",        # speech recogniser: parakeet | whisper
    "whisper_size": "small.en",
    "converter": "knnvc",          # voice converter: knnvc | chatterbox
    "base_voice": "bm_george",     # British reader that Rebuild starts from
    "speed": 1.0,
    "clean_noise": True,
    "max_pause": 0.60,             # pauses longer than this are shortened ...
    "keep_pause": 0.32,            # ... to this length (seconds)
    "line_gap": 0.45,              # silence between lines in the export
    "title_gap": 0.90,             # silence after a title line
    "input_device": None,
    "threads": max(2, (os.cpu_count() or 4) - 1),
    # Written exactly as the reader should say them. Used by Rebuild and by the script check.
    "say_as": {},
}

BRITISH_VOICES = {
    "bm_george": "George (male)", "bm_daniel": "Daniel (male)",
    "bm_lewis": "Lewis (male)", "bm_fable": "Fable (male)",
    "bf_emma": "Emma (female)", "bf_alice": "Alice (female)",
    "bf_isabella": "Isabella (female)", "bf_lily": "Lily (female)",
}

_lock = threading.Lock()


def ensure_dirs():
    for p in (DATA, MODELS, VOICE, PROJECTS):
        p.mkdir(parents=True, exist_ok=True)


def load():
    ensure_dirs()
    s = json.loads(json.dumps(DEFAULTS))
    if SETTINGS_FILE.exists():
        try:
            s.update(json.loads(SETTINGS_FILE.read_text("utf-8")))
        except Exception:
            pass
    return s


def save(changes: dict):
    with _lock:
        s = load()
        for k, v in changes.items():
            if k in DEFAULTS:
                s[k] = v
        SETTINGS_FILE.write_text(json.dumps(s, indent=2), "utf-8")
        return s
