"""The listener: turns a recording into words with the time each word was spoken."""
import threading

import numpy as np

from . import config, models
from .audio import resample

_engines = {}
_lock = threading.Lock()


def _parakeet(threads):
    import sherpa_onnx
    d = models.path("listener")
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
        joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
        model_type="nemo_transducer", num_threads=threads)


def _listen_parakeet(x16, threads):
    with _lock:
        if "parakeet" not in _engines:
            _engines["parakeet"] = _parakeet(threads)
        rec = _engines["parakeet"]
        out, CH = [], 28 * 16000          # long takes are heard in 28 s pieces
        for off in range(0, len(x16), CH):
            piece = x16[off:off + CH]
            if len(piece) < 1600:
                continue
            st = rec.create_stream()
            st.accept_waveform(16000, piece)
            rec.decode_stream(st)
            r = st.result
            durs = list(getattr(r, "durations", []) or [])
            cur = None
            for i, (tok, ts) in enumerate(zip(r.tokens, r.timestamps)):
                t = off / 16000 + float(ts)
                end = t + (float(durs[i]) if i < len(durs) and durs[i] > 0 else 0.08)
                if tok.startswith(" ") or tok.startswith("▁") or cur is None:
                    if cur and cur["word"].strip():
                        out.append(cur)
                    cur = {"word": tok.strip(" ▁"), "start": t, "end": end}
                else:
                    cur["word"] += tok
                    cur["end"] = end
            if cur and cur["word"].strip():
                out.append(cur)
    return _tidy(out, len(x16) / 16000)


def _listen_whisper(x16, threads, size):
    """Optional second listener (needs the extra engines to be installed)."""
    from faster_whisper import WhisperModel
    with _lock:
        key = "whisper:" + size
        if key not in _engines:
            _engines[key] = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=threads,
                                         download_root=str(config.MODELS / "whisper"))
        segs, _ = _engines[key].transcribe(
            x16, language="en", word_timestamps=True, condition_on_previous_text=False,
            initial_prompt="Umm, let me, let me think, uh, like this. So, so the b- the baby is, um, fine.")
        out = [{"word": w.word.strip(), "start": float(w.start), "end": float(w.end)}
               for s in segs for w in (s.words or [])]
    return _tidy(out, len(x16) / 16000)


def _tidy(words, dur):
    words = [w for w in words if any(c.isalnum() for c in w["word"])]
    for i, w in enumerate(words):
        nxt = words[i + 1]["start"] if i + 1 < len(words) else dur
        w["end"] = float(min(max(w["end"], w["start"] + 0.04), max(nxt, w["start"] + 0.04)))
    return words


def listen(x: np.ndarray, sr: int, settings=None):
    """Returns [{'word', 'start', 'end'}] with times in seconds."""
    s = settings or config.load()
    x16 = resample(x, sr, 16000)
    peak = float(np.abs(x16).max()) if len(x16) else 0
    if peak < 1e-4:
        return []
    x16 = (x16 / peak * 0.7).astype(np.float32)
    if s.get("listener") == "whisper":
        try:
            return _listen_whisper(x16, s["threads"], s.get("whisper_size", "small.en"))
        except ImportError:
            pass
    return _listen_parakeet(x16, s["threads"])
