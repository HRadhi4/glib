"""Microphone recording."""
import threading

import numpy as np

from .config import SR

_state = {"stream": None, "chunks": [], "level": 0.0, "peak": 0.0, "target": None}
_lock = threading.Lock()


def devices():
    try:
        import sounddevice as sd
        default = sd.default.device[0]
        return [{"id": i, "name": d["name"], "default": i == default}
                for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    except Exception:
        return []


def _callback(indata, frames, time_info, status):
    x = indata[:, 0].copy()
    _state["chunks"].append(x)
    lv = float(np.sqrt((x ** 2).mean()))
    _state["level"] = lv
    _state["peak"] = max(_state["peak"], float(np.abs(x).max()))


def start(target, device=None):
    """target is a label saying what is being recorded (a line or a voice sample)."""
    import sounddevice as sd
    with _lock:
        if _state["stream"] is not None:
            raise RuntimeError("Already recording.")
        _state.update(chunks=[], level=0.0, peak=0.0, target=target)
        try:
            st = sd.InputStream(samplerate=SR, channels=1, dtype="float32", device=device, callback=_callback)
        except Exception:
            st = sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=_callback)
        st.start()
        _state["stream"] = st


def stop():
    """Returns (samples, target)."""
    with _lock:
        st = _state["stream"]
        if st is None:
            raise RuntimeError("Not recording.")
        st.stop()
        st.close()
        _state["stream"] = None
        x = np.concatenate(_state["chunks"]) if _state["chunks"] else np.zeros(0, np.float32)
        return x, _state["target"]


def status():
    on = _state["stream"] is not None
    return {"on": on, "target": _state["target"] if on else None,
            "level": round(min(1.0, _state["level"] * 6), 3) if on else 0,
            "seconds": round(sum(len(c) for c in _state["chunks"]) / SR, 1) if on else 0,
            "too_loud": _state["peak"] > 0.98}
