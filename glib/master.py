"""Voice-over finishing chain, the way a studio engineer would set it up for narration.

Order: rumble filter -> neural noise removal -> tone shaping -> de-esser -> compressor
-> loudness to a LUFS target -> true-peak limiter.

Loudness follows ITU-R BS.1770-4 / EBU R128 (K-weighting, 400 ms blocks, absolute and relative
gates). The limiter keeps true peaks (4x oversampled) under the ceiling.
"""
import threading

import numpy as np
from scipy import signal
from scipy.ndimage import maximum_filter1d, minimum_filter1d

from . import models

LOUDNESS_TARGETS = {"-14": "-14 LUFS (YouTube)", "-16": "-16 LUFS (voice-over, room for music)",
                    "-19": "-19 LUFS (quiet, broadcast-style)"}
DENOISE_LEVELS = {"off": "Off", "gentle": "Gentle", "normal": "Normal", "strong": "Strong"}
_ATTENUATION = {"gentle": 12.0, "normal": 20.0, "strong": 0.0}   # dB cap on noise reduction (0 = no cap)

_denoisers = {}
_dlock = threading.Lock()


# ---------------------------------------------------------------- filters
def _biquad(kind, f0, sr, q=0.7071, gain_db=0.0):
    """RBJ cookbook biquad as second-order sections."""
    a = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * q)
    if kind == "peak":
        b = [1 + alpha * a, -2 * cw, 1 - alpha * a]
        den = [1 + alpha / a, -2 * cw, 1 - alpha / a]
    elif kind == "highshelf":
        sq = 2 * np.sqrt(a) * alpha
        b = [a * ((a + 1) + (a - 1) * cw + sq), -2 * a * ((a - 1) + (a + 1) * cw), a * ((a + 1) + (a - 1) * cw - sq)]
        den = [(a + 1) - (a - 1) * cw + sq, 2 * ((a - 1) - (a + 1) * cw), (a + 1) - (a - 1) * cw - sq]
    elif kind == "lowshelf":
        sq = 2 * np.sqrt(a) * alpha
        b = [a * ((a + 1) - (a - 1) * cw + sq), 2 * a * ((a - 1) - (a + 1) * cw), a * ((a + 1) - (a - 1) * cw - sq)]
        den = [(a + 1) + (a - 1) * cw + sq, -2 * ((a - 1) + (a + 1) * cw), (a + 1) + (a - 1) * cw - sq]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        den = [1 + alpha, -2 * cw, 1 - alpha]
    else:
        raise ValueError(kind)
    b, den = np.array(b) / den[0], np.array(den) / den[0]
    return np.concatenate([b, den])[None, :]


def _k_weight(x, sr):
    """BS.1770 K-weighting: high shelf (+4 dB above ~1.7 kHz) then RLB high-pass."""
    sos = np.vstack([_biquad("highshelf", 1681.974450955533, sr, 0.7071752369554196, 3.999843853973347),
                     _biquad("highpass", 38.13547087602444, sr, 0.5003270373238773)])
    return signal.sosfilt(sos, x)


def lufs(x: np.ndarray, sr: int) -> float:
    """Integrated loudness (LUFS) of a mono signal."""
    if len(x) < int(0.4 * sr):
        x = np.pad(x, (0, int(0.4 * sr) - len(x)))
    y = _k_weight(x.astype(np.float64), sr)
    block, hop = int(0.4 * sr), int(0.1 * sr)
    n = 1 + (len(y) - block) // hop
    idx = np.arange(block)[None, :] + hop * np.arange(n)[:, None]
    z = (y[idx] ** 2).mean(axis=1)
    l = -0.691 + 10 * np.log10(z + 1e-12)
    z = z[l > -70]
    if not len(z):
        return -70.0
    rel = -0.691 + 10 * np.log10(z.mean()) - 10
    z2 = z[-0.691 + 10 * np.log10(z) > rel]
    return float(-0.691 + 10 * np.log10((z2 if len(z2) else z).mean()))


def true_peak_db(x: np.ndarray) -> float:
    up = signal.resample_poly(x, 4, 1)
    return float(20 * np.log10(np.abs(up).max() + 1e-12))


# ---------------------------------------------------------------- dynamics helpers
def _env_db(x, sr, ms=1.0):
    """RMS level per short block, in dB, plus the block size in samples."""
    h = max(1, int(sr * ms / 1000))
    n = len(x) // h
    if n == 0:
        return np.array([-120.0]), h
    r = np.sqrt((x[: n * h].reshape(n, h) ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(r), h


def _smooth(level_db, attack_blocks, release_blocks, start=-120.0):
    """Attack/release ballistics on a block-rate level (classic analog-style detector)."""
    ka = np.exp(-1.0 / max(attack_blocks, 1e-3))
    kr = np.exp(-1.0 / max(release_blocks, 1e-3))
    out = np.empty_like(level_db)
    s = start
    for i, v in enumerate(level_db):
        k = ka if v > s else kr
        s = k * s + (1 - k) * v
        out[i] = s
    return out


def _to_samples(gain_blocks, h, n):
    """Block-rate gain -> per-sample gain (linear interpolation)."""
    centres = (np.arange(len(gain_blocks)) + 0.5) * h
    return np.interp(np.arange(n), centres, gain_blocks).astype(np.float32)


def speech_level_db(x, sr):
    """Typical level of the voice itself (ignores pauses)."""
    lv, _ = _env_db(x, sr, 20)
    voiced = lv[lv > np.percentile(lv, 95) - 30]
    return float(np.median(voiced)) if len(voiced) else -60.0


# ---------------------------------------------------------------- stages
def rumble_filter(x, sr, hz=80):
    sos = signal.butter(4, hz, "highpass", fs=sr, output="sos")
    return signal.sosfiltfilt(sos, x).astype(np.float32)


def denoise(x, sr, level="normal", threads=2):
    """Neural noise removal (DPDFNet, full band 48 kHz). Level caps how far noise is pushed down,
    which keeps the voice natural instead of 'underwater'."""
    if level == "off" or len(x) < sr // 4 or not models.have("denoiser"):
        return x
    import sherpa_onnx
    att = _ATTENUATION.get(level, 20.0)
    with _dlock:
        key = (att, threads)
        if key not in _denoisers:
            cfg = sherpa_onnx.OfflineSpeechDenoiserConfig(
                model=sherpa_onnx.OfflineSpeechDenoiserModelConfig(
                    dpdfnet=sherpa_onnx.OfflineSpeechDenoiserDpdfNetModelConfig(
                        model=str(models.path("denoiser")), attenuation_limit_db=att),
                    num_threads=threads))
            _denoisers[key] = sherpa_onnx.OfflineSpeechDenoiser(cfg)
        d = _denoisers[key]
        from .audio import resample
        y48 = resample(x, sr, d.sample_rate)
        pad = int(0.25 * d.sample_rate)                # warm-up so the first syllable is not eaten
        r = d(np.concatenate([np.zeros(pad, np.float32), y48, np.zeros(pad, np.float32)]), d.sample_rate)
        y = np.asarray(r.samples, np.float32)[pad: pad + len(y48)]
    y = resample(y, d.sample_rate, sr)
    if len(y) < len(x):
        y = np.pad(y, (0, len(x) - len(y)))
    return y[: len(x)].astype(np.float32)


def tone(x, sr):
    """Gentle narration EQ: clear the boxy low-mids, a touch of presence and air."""
    sos = np.vstack([
        _biquad("lowshelf", 120, sr, 0.7, -1.5),      # less boom from close-mic proximity effect
        _biquad("peak", 300, sr, 1.0, -2.0),          # 'boxy' / 'muddy' region
        _biquad("peak", 3500, sr, 0.9, 1.5),          # presence / intelligibility
        _biquad("highshelf", 10000, sr, 0.7, 1.0) if sr > 24000 else _biquad("peak", 1000, sr, 1, 0),
    ])
    return signal.sosfilt(sos, x).astype(np.float32)


def deess(x, sr, max_cut_db=8.0):
    """Split-band de-esser: only the 5-9 kHz band is turned down, and only on loud 's' and 'sh'."""
    hi = min(9000, sr / 2 - 500)
    if hi <= 5500:
        return x
    sos = signal.butter(4, [5000, hi], "bandpass", fs=sr, output="sos")
    band = signal.sosfiltfilt(sos, x)
    rest = x - band
    b_db, h = _env_db(band, sr, 2)
    f_db, _ = _env_db(x, sr, 2)
    over = np.clip((b_db - f_db) + 6.0, 0, None)       # sibilant when the band nears the full level
    cut = np.minimum(over * 1.5, max_cut_db)
    cut = _smooth(cut, 0.5, 15, start=0.0)               # 1 ms attack, 30 ms release
    g = _to_samples(10 ** (-cut / 20), h, len(x))
    return (rest + band * g).astype(np.float32)


def compress(x, sr, ratio=3.0, below_speech_db=8.0, knee_db=6.0, attack_ms=8, release_ms=140):
    """Smooth voice compressor. Threshold sits a little under the speaking level so loud words
    are tamed and quiet ones come forward, without pumping."""
    lv, h = _env_db(x, sr, 1)
    thr = speech_level_db(x, sr) - below_speech_db
    det = _smooth(lv, attack_ms / (h / sr * 1000), release_ms / (h / sr * 1000))
    over = det - thr
    gr = np.where(over <= -knee_db / 2, 0.0,
                  np.where(over >= knee_db / 2, over * (1 - 1 / ratio),
                           (1 - 1 / ratio) * (over + knee_db / 2) ** 2 / (2 * knee_db)))
    g = _to_samples(10 ** (-gr / 20), h, len(x))
    return (x * g).astype(np.float32)


def limit(x, sr, ceiling_db=-1.0, lookahead_ms=5.0, release_ms=60.0):
    """Look-ahead brick-wall limiter on true (4x oversampled) peaks."""
    if not len(x):
        return x
    ceiling = 10 ** (ceiling_db / 20)
    h = max(1, int(sr * 0.0005))                          # 0.5 ms blocks
    n = int(np.ceil(len(x) / h))
    up = np.abs(signal.resample_poly(np.pad(x, (0, n * h - len(x))), 4, 1)).reshape(n, 4 * h).max(axis=1)
    need = np.minimum(1.0, ceiling / (up + 1e-12))
    la = max(1, int(lookahead_ms / 0.5))
    need = minimum_filter1d(need, size=2 * la + 1)        # start reducing before the peak arrives
    g_db = 20 * np.log10(need)
    g_db = -_smooth(-g_db, 0.01, release_ms / 0.5, start=0.0)
    g = _to_samples(10 ** (g_db / 20), h, len(x))
    y = x * g
    return np.clip(y, -ceiling, ceiling).astype(np.float32)


def normalise(x, sr, target_lufs=-16.0):
    cur = lufs(x, sr)
    if cur <= -69:
        return x
    return (x * 10 ** ((target_lufs - cur) / 20)).astype(np.float32)


def finish(x, sr, settings, denoise_too=True):
    """The full chain for one clip. Returns the finished clip."""
    if len(x) < sr // 10:
        return x
    y = rumble_filter(x, sr)
    if denoise_too:
        y = denoise(y, sr, settings.get("denoise", "normal"), settings.get("threads", 2))
    y = tone(y, sr)
    y = deess(y, sr)
    y = compress(y, sr)
    y = normalise(y, sr, float(settings.get("loudness", "-16")))
    return limit(y, sr, -1.0)


def report(x, sr):
    return {"lufs": round(lufs(x, sr), 1), "true_peak": round(true_peak_db(x), 1)}


def check_sample(x, sr):
    """Plain-words quality check of a voice recording."""
    lv, _ = _env_db(x, sr, 20)
    if not len(lv) or lv.max() < -60:
        return {"verdict": "bad", "text": "Almost silent. Check that the right microphone is selected."}
    floor = float(np.percentile(lv, 8))
    speech = speech_level_db(x, sr)
    snr = speech - floor
    clipped = float(np.mean(np.abs(x) > 0.985))
    out = {"snr": round(snr, 1), "level": round(speech, 1)}
    if clipped > 0.0005:
        out.update(verdict="bad", text="Too loud: the recording distorts. Move back a little or lower the microphone level.")
    elif speech < -42:
        out.update(verdict="warn", text="Quite quiet. Move closer to the microphone.")
    elif snr < 22:
        out.update(verdict="warn", text="Noisy room. A quieter room gives a much better voice match.")
    elif (echo := echo_seconds(x, sr)) and echo > 0.42:
        out.update(verdict="warn", echo=round(echo, 2),
                   text="Room echo. Record in a smaller room with soft things around you (curtains, a sofa, "
                        "clothes in a wardrobe); echo in your samples is copied into the rebuilt voice.")
    elif snr < 32:
        out.update(verdict="ok", text="Good. A little background noise.")
    else:
        out.update(verdict="good", text="Clean recording.")
    return out


def echo_seconds(x, sr):
    """Rough reverberation time of the room (seconds for sound to die away by 60 dB),
    measured on how fast the voice fades at the ends of words. Close-mic speech in a
    furnished room is usually under 0.3 s; bare rooms are 0.5 s and more."""
    lv, _ = _env_db(x, sr, 5)                         # 5 ms frames
    if len(lv) < 200:
        return None
    lv = np.convolve(lv, np.ones(3) / 3, mode="same")
    floor = np.percentile(lv, 10)
    times = []
    i = 1
    while i < len(lv) - 100:
        if lv[i] > floor + 25 and lv[i] >= lv[i - 1] and lv[i] >= lv[i + 1]:
            peak, low = lv[i], lv[i]
            for j in range(i + 1, min(i + 100, len(lv))):   # up to 500 ms
                if lv[j] > low + 3:                           # the next sound starts: not a clean ending
                    break
                low = min(low, lv[j])
                if lv[j] <= peak - 15:
                    times.append((j - i) * 0.005)
                    break
            i += 8
        else:
            i += 1
    if len(times) < 8:
        return None
    return float(4 * np.percentile(times, 30))      # 15 dB fall x4 = 60 dB; the quicker endings show the room
