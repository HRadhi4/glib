"""The converter: gives the British reader's speech your voice, learned from your voice samples.

Engine: Chatterbox voice conversion (Resemble AI, MIT licence), run through ONNX Runtime.
  speech encoder:      24 kHz audio -> speech tokens, speaker identity (x-vector), voice features
  conditional decoder: tokens + your identity + your voice features -> 24 kHz speech

What Glib adds on top, as a sound engineer would:
- The voice prompt is the cleanest 10-second stretch of all your samples (most speech, least
  noise, no distortion), not simply the first seconds of a file.
- Your speaker identity is averaged over the best stretch of every sample, which keeps the
  voice steady from line to line.
- Long lines are converted in pieces split at natural pauses and joined with short crossfades.
"""
import json
import threading

import numpy as np

from . import config, models
from .audio import read, resample, speech_mask

SR = 24000
PROMPT_S = 10.0          # length of the voice prompt
PIECE_S = 9.0            # longest piece converted in one go
_lock = threading.Lock()
_sessions = {}
_voice = None            # (signature, dict of arrays)


def voice_files():
    return sorted(config.VOICE.glob("sample_*.wav"))


def voice_minutes():
    import soundfile as sf
    return sum(sf.info(str(p)).duration for p in voice_files()) / 60


def _signature():
    return "|".join(f"{p.name}:{p.stat().st_size}:{int(p.stat().st_mtime)}" for p in voice_files())


def _session_files():
    hq = config.load().get("voice_quality") == "highest"
    return (models.path("converter_enc_hq"), models.path("converter_dec_hq")) if hq else \
           (models.path("converter_enc"), models.path("converter_dec"))


def _load():
    import onnxruntime as ort
    enc_p, dec_p = _session_files()
    key = (str(enc_p), str(dec_p))
    if key not in _sessions:
        _sessions.clear()
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(config.load()["threads"])
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        prov = ["CPUExecutionProvider"]
        _sessions[key] = (ort.InferenceSession(str(enc_p), so, providers=prov),
                          ort.InferenceSession(str(dec_p), so, providers=prov))
    return _sessions[key]


def _encode(x24):
    enc, _ = _load()
    _cond, tokens, xvec, feat = enc.run(None, {"audio_values": x24[None, :].astype(np.float32)})
    return tokens, xvec, feat


def _peak_norm(x, peak=0.85):
    m = float(np.abs(x).max()) if len(x) else 0
    return (x * (peak / m)).astype(np.float32) if m > 1e-4 else x


def _best_window(x, sr, seconds):
    """Start (in samples) of the stretch with the most clean speech."""
    n = int(seconds * sr)
    if len(x) <= n:
        return 0, 0.0
    m, db = speech_mask(x, sr)
    hop = sr // 100
    floor = np.percentile(db, 10)
    clip = np.abs(x) > 0.985
    best, best_score = 0, -1e9
    for s in range(0, len(x) - n, sr // 2):
        a, b = s // hop, (s + n) // hop
        voiced = m[a:b].mean() if b > a else 0
        loud = np.median(db[a:b][m[a:b]]) - floor if m[a:b].any() else 0
        clipped = clip[s:s + n].mean()
        # want: lots of speech (but natural pauses are fine), high signal-to-noise, no distortion
        score = min(voiced, 0.85) * 40 + min(loud, 45) - clipped * 5000
        if score > best_score:
            best, best_score = s, score
    return best, best_score


def learn_voice(progress=None):
    """Study your voice samples once; cached until the samples change."""
    global _voice
    sig = _signature()
    if not sig:
        raise RuntimeError("Rebuild needs to know your voice. Record a sample in the My Voice tab first.")
    cache = config.VOICE / "voice_ref.npz"
    with _lock:
        if _voice and _voice[0] == sig:
            return _voice[1]
        if cache.exists():
            d = np.load(cache, allow_pickle=False)
            if str(d["sig"]) == sig and str(d.get("enc", "")) == str(_session_files()[0].name):
                _voice = (sig, {k: d[k] for k in ("tokens", "xvec", "feat")})
                return _voice[1]
        files = voice_files()
        clips = []
        for i, p in enumerate(files):
            if progress:
                progress(f"Studying your voice ({i + 1} of {len(files)})")
            x = read(p, SR)
            s, score = _best_window(x, SR, PROMPT_S)
            clips.append((score, _peak_norm(x[s:s + int(PROMPT_S * SR)])))
        clips.sort(key=lambda c: -c[0])
        tokens, xvec, feat = _encode(clips[0][1])
        xs = [xvec] + [_encode(c[1])[1] for c in clips[1:6]]
        xavg = np.mean(np.concatenate(xs, axis=0), axis=0, keepdims=True).astype(np.float32)
        ref = {"tokens": tokens, "xvec": xavg, "feat": feat}
        np.savez(cache, sig=sig, enc=_session_files()[0].name, **ref)
        _voice = (sig, ref)
        return ref


def _pieces(x, sr, longest):
    """Split at the quietest moment between 45% and 100% of the longest allowed piece."""
    out, start = [], 0
    n = int(longest * sr)
    while len(x) - start > n:
        lo, hi = start + int(0.45 * n), start + n
        seg = x[lo:hi]
        h = sr // 100
        e = np.convolve(seg ** 2, np.ones(h) / h, mode="same")
        cut = lo + int(np.argmin(e[h:-h])) + h if len(e) > 2 * h else hi
        out.append((start, cut))
        start = cut
    out.append((start, len(x)))
    return out


def convert(x: np.ndarray, sr: int, settings=None, progress=None):
    """Reader speech in, the same words in your voice out. Returns (samples, 24000)."""
    ref = learn_voice(progress)
    x24 = _peak_norm(resample(x, sr, SR))
    with _lock:
        _, dec = _load()
        parts = []
        for a, b in _pieces(x24, SR, PIECE_S):
            if b - a < SR // 10:
                continue
            tokens, _, _ = _encode(x24[a:b])
            speech = np.concatenate([ref["tokens"], tokens], axis=1).astype(np.int64)
            wav = dec.run(None, {"speech_tokens": speech, "speaker_embeddings": ref["xvec"],
                                 "speaker_features": ref["feat"]})[0]
            parts.append(np.squeeze(wav).astype(np.float32))
    from .audio import join
    return join(parts, SR, 0.02), SR


def pick_reader(settings):
    """British reader whose natural pitch is closest to yours (Settings > Reader: Automatic)."""
    chosen = settings.get("base_voice", "auto")
    if chosen != "auto" and chosen in config.BRITISH_VOICES:
        return chosen
    cache = config.VOICE / "reader_match.json"
    sig = _signature()
    if cache.exists():
        d = json.loads(cache.read_text())
        if d.get("sig") == sig:
            return d["voice"]
    from .audio import melody
    from . import tts
    mine = [m["pitch_hz"] for m in (melody(read(p)) for p in voice_files()[:3]) if m]
    if not mine:
        return "bm_george"
    target = float(np.median(mine))
    best, gap = "bm_george", 1e9
    for v in config.BRITISH_VOICES:
        y, r = tts.read_aloud("Good morning. Today we will look at a few simple ideas, one step at a time.",
                              dict(settings, base_voice=v))
        m = melody(resample(y, r, 48000))
        if m and abs(12 * np.log2(m["pitch_hz"] / target)) < gap:
            best, gap = v, abs(12 * np.log2(m["pitch_hz"] / target))
    cache.write_text(json.dumps({"sig": sig, "voice": best, "your_pitch_hz": round(target)}))
    return best
