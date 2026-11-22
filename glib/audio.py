"""Sound handling: loading, cutting, noise clean-up, pause tightening, levelling, pitch."""
import numpy as np
import soundfile as sf
from scipy import signal

from .config import SR


def resample(x: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to or len(x) == 0:
        return x.astype(np.float32)
    g = np.gcd(int(sr_from), int(sr_to))
    return signal.resample_poly(x, sr_to // g, sr_from // g).astype(np.float32)


def read(path, sr=SR) -> np.ndarray:
    x, s = sf.read(str(path), dtype="float32", always_2d=True)
    return resample(x.mean(axis=1), s, sr)


def write(path, x: np.ndarray, sr=SR, subtype="PCM_16"):
    sf.write(str(path), np.clip(x, -1, 1), sr, subtype=subtype)


def frame_db(x: np.ndarray, sr=SR, hop=0.010, win=0.025) -> np.ndarray:
    """Loudness of each 10 ms step, in dB."""
    h, w = int(sr * hop), int(sr * win)
    if len(x) < w:
        x = np.pad(x, (0, w - len(x)))
    n = 1 + (len(x) - w) // h
    idx = np.arange(w)[None, :] + h * np.arange(n)[:, None]
    rms = np.sqrt((x[idx] ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(rms)


def speech_mask(x: np.ndarray, sr=SR):
    """True for each 10 ms step that contains voice rather than room noise."""
    db = frame_db(x, sr)
    floor = np.percentile(db, 10)
    top = np.percentile(db, 95)
    thr = max(floor + 8, top - 35)
    thr = min(thr, top - 6)
    m = db > thr
    # bridge tiny gaps, drop tiny blips
    m = signal.medfilt(m.astype(np.float32), 5) > 0.5
    return m, db


def highpass(x, sr=SR, hz=70):
    sos = signal.butter(2, hz, "highpass", fs=sr, output="sos")
    return signal.sosfiltfilt(sos, x).astype(np.float32)


def clean_noise(x: np.ndarray, sr=SR, strength=0.85) -> np.ndarray:
    """Gentle spectral gate: learns the steady room noise from the quietest moments and lowers it."""
    if len(x) < sr // 2:
        return x
    f, t, Z = signal.stft(x, fs=sr, nperseg=1024, noverlap=768)
    mag = np.abs(Z)
    energy = mag.mean(axis=0)
    quiet = mag[:, energy <= np.percentile(energy, 12)]
    if quiet.shape[1] < 3:
        return x
    noise = quiet.mean(axis=1, keepdims=True) + 1.5 * quiet.std(axis=1, keepdims=True)
    gain = np.clip((mag - noise) / (mag + 1e-9), 0, 1)
    gain = signal.medfilt2d(gain, kernel_size=(3, 5))
    gain = 1 - strength * (1 - gain)
    _, y = signal.istft(Z * gain, fs=sr, nperseg=1024, noverlap=768)
    y = y[: len(x)]
    if len(y) < len(x):
        y = np.pad(y, (0, len(x) - len(y)))
    return y.astype(np.float32)


def _quietest(db, centre_s, lo_s, hi_s, hop=0.010):
    """Nearest quiet spot to centre_s within [lo_s, hi_s] (seconds)."""
    lo = max(0, int(lo_s / hop))
    hi = min(len(db) - 1, int(hi_s / hop))
    if hi <= lo:
        return float(np.clip(centre_s, lo_s, hi_s))
    seg = db[lo:hi + 1]
    return (lo + int(np.argmin(seg))) * hop + 0.012


def cut(x: np.ndarray, spans, sr=SR, fade=0.012):
    """Remove the given (start, end) spans in seconds, joining the pieces with short crossfades.
    Each edge is nudged to the quietest nearby moment so the join is not heard."""
    if not spans:
        return x, []
    db = frame_db(x, sr)
    dur = len(x) / sr
    spans = sorted((max(0.0, a), min(dur, b)) for a, b in spans if b > a)
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 0.03:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    refined = []
    for a, b in merged:
        reach = min(0.12, (b - a) / 3)
        a2 = _quietest(db, a, a - 0.10, a + reach) if a > 0.02 else 0.0
        b2 = _quietest(db, b, b - reach, b + 0.04) if b < dur - 0.02 else dur
        if b2 - a2 > 0.03:
            refined.append((a2, b2))
    keep, pos = [], 0.0
    for a, b in refined:
        keep.append((pos, a))
        pos = b
    keep.append((pos, dur))
    return join([x[int(a * sr):int(b * sr)] for a, b in keep if b - a > 0.005], sr, fade), refined


def quiet_spots(x: np.ndarray, lo_s: float, hi_s: float, sr=SR):
    """Moments between lo_s and hi_s where the voice dips (good places to cut), quietest first."""
    db = frame_db(x, sr, hop=0.005, win=0.020)
    k = np.ones(5) / 5
    sm = np.convolve(db, k, mode="same")
    lo, hi = max(1, int(lo_s / 0.005)), min(len(sm) - 2, int(hi_s / 0.005))
    spots = [(sm[i], i * 0.005 + 0.010) for i in range(lo, hi + 1) if sm[i] <= sm[i - 1] and sm[i] < sm[i + 1]]
    return [t for _, t in sorted(spots)]


def remove(x: np.ndarray, a: float, b: float, sr=SR, fade=0.012):
    """Take out exactly a..b seconds and crossfade the join."""
    return join([x[: int(a * sr)], x[int(b * sr):]], sr, fade)


def join(pieces, sr=SR, fade=0.012):
    pieces = [p for p in pieces if len(p)]
    if not pieces:
        return np.zeros(0, np.float32)
    n = int(sr * fade)
    out = pieces[0].astype(np.float32).copy()
    for p in pieces[1:]:
        k = min(n, len(out), len(p))
        if k > 1:
            ramp = np.linspace(0, 1, k, dtype=np.float32)
            out[-k:] = out[-k:] * (1 - ramp) + p[:k] * ramp
            out = np.concatenate([out, p[k:]])
        else:
            out = np.concatenate([out, p])
    return out


def tighten(x: np.ndarray, sr=SR, max_pause=0.6, keep_pause=0.32, edge=0.12):
    """Shorten long silences and trim the silence at both ends. Returns audio and seconds removed."""
    if len(x) < sr // 5:
        return x, 0.0
    m, _ = speech_mask(x, sr)
    if not m.any():
        return x, 0.0
    hop = 0.010
    first, last = int(np.argmax(m)), len(m) - int(np.argmax(m[::-1]))
    spans = []
    start = first * hop - edge
    if start > 0.02:
        spans.append((0.0, start))
    i = first
    while i < last:
        if not m[i]:
            j = i
            while j < last and not m[j]:
                j += 1
            gap = (j - i) * hop
            if gap > max_pause:
                extra = gap - keep_pause
                mid = (i + j) / 2 * hop
                spans.append((mid - extra / 2, mid + extra / 2))
            i = j
        else:
            i += 1
    end = last * hop + edge + 0.02
    if end < len(x) / sr - 0.02:
        spans.append((end, len(x) / sr))
    pieces, pos = [], 0
    for a, b in spans:
        pieces.append(x[pos:int(a * sr)])
        pos = int(b * sr)
    pieces.append(x[pos:])
    y = join(pieces, sr, 0.015)
    return y, (len(x) - len(y)) / sr


def level(x: np.ndarray, sr=SR, target_db=-20.0, peak_db=-1.0) -> np.ndarray:
    """Bring the voice to the same loudness on every line, with a soft ceiling so nothing clips."""
    if len(x) < sr // 10:
        return x
    m, db = speech_mask(x, sr)
    if not m.any():
        return x
    voice = 10 * np.log10(np.mean(10 ** (db[m] / 10)))
    gain = 10 ** ((target_db - voice) / 20)
    y = x * min(gain, 20.0)
    ceiling = 10 ** (peak_db / 20)
    knee = ceiling * 0.7
    over = np.abs(y) > knee
    y[over] = np.sign(y[over]) * (knee + (ceiling - knee) * np.tanh((np.abs(y[over]) - knee) / (ceiling - knee)))
    return y.astype(np.float32)


def fade_edges(x, sr=SR, ms=8):
    n = min(int(sr * ms / 1000), len(x) // 2)
    if n > 1:
        x = x.copy()
        r = np.linspace(0, 1, n, dtype=np.float32)
        x[:n] *= r
        x[-n:] *= r[::-1]
    return x


def melody(x: np.ndarray, sr=SR):
    """How much the voice moves up and down, in semitones (spread of pitch). Low = flat delivery."""
    y = resample(x, sr, 16000)
    m, _ = speech_mask(y, 16000)
    w, h = 640, 160
    lo, hi = 16000 // 400, 16000 // 70
    f0 = []
    for i in range(0, len(y) - w, h * 2):
        if not m[min(len(m) - 1, i // h)]:
            continue
        s = y[i:i + w] - y[i:i + w].mean()
        ac = signal.correlate(s, s, mode="full")[w - 1:]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.45:
            f0.append(16000 / k)
    if len(f0) < 12:
        return None
    st = 12 * np.log2(np.array(f0))
    st = st[np.abs(st - np.median(st)) < 12]   # ignore octave slips
    return {"spread": float(np.std(st)), "pitch_hz": float(2 ** (np.median(st) / 12))}
