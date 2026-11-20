"""The reader: a natural British voice that reads the script. Rebuild then gives it your voice tone."""
import re
import threading

import numpy as np

from . import config, models
from .align import apply_say_as

_kokoro = None
_lock = threading.Lock()

# how written units are read aloud: (after a number, after "per")
UNITS = {
    "mL": ("millilitres", "millilitre"), "ml": ("millilitres", "millilitre"), "L": ("litres", "litre"),
    "kg": ("kilograms", "kilogram"), "g": ("grams", "gram"), "mg": ("milligrams", "milligram"),
    "mcg": ("micrograms", "microgram"), "mmol": ("millimoles", "millimole"),
    "mEq": ("milliequivalents", "milliequivalent"), "min": ("minutes", "minute"),
    "h": ("hours", "hour"), "hr": ("hours", "hour"), "day": ("days", "day"), "dose": ("doses", "dose"),
    "U": ("units", "unit"), "dL": ("decilitres", "decilitre"), "cm": ("centimetres", "centimetre"),
    "wk": ("weeks", "week"),
}
_U = "|".join(sorted(map(re.escape, UNITS), key=len, reverse=True))


def spoken_text(text: str, say_as: dict = None) -> str:
    """Prepare a script line for reading aloud."""
    t = apply_say_as(text, say_as)
    t = re.sub(rf"/\s*({_U})\b", lambda m: " per " + UNITS[m.group(1)][1], t)
    t = re.sub(rf"(?<=\d)\s*({_U})\b", lambda m: " " + UNITS[m.group(1)][0], t)
    t = re.sub(r"(?<=\d)\s*[-–]\s*(?=\d)", " to ", t)          # 1.5–2  ->  1.5 to 2
    t = t.replace("×", " times ").replace("≥", " at least ").replace("≤", " at most ")
    t = t.replace("→", ", then ").replace("·", ", ").replace("&", " and ")
    t = re.sub(r"(?<=[A-Za-z])/(?=[A-Za-z])", " or ", t)
    t = re.sub(r"^\s*#+\s*", "", t)
    return re.sub(r"\s+", " ", t).strip()


def read_aloud(text: str, settings=None):
    """Returns (samples, sample_rate) of the British reader saying the text."""
    global _kokoro
    s = settings or config.load()
    with _lock:
        if _kokoro is None:
            from kokoro_onnx import Kokoro
            _kokoro = Kokoro(str(models.path("reader")), str(models.path("reader_voices")))
        voice = s.get("base_voice", "bm_george")
        if voice not in config.BRITISH_VOICES:
            voice = "bm_george"
        x, sr = _kokoro.create(spoken_text(text, s.get("say_as")), voice=voice,
                               speed=float(s.get("speed", 1.0)), lang="en-gb")
    return np.asarray(x, dtype=np.float32), int(sr)
