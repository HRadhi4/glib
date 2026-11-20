"""The converter: gives the reader's speech your voice tone, learned from your voice samples."""
import sys
import threading
from pathlib import Path

import numpy as np

from . import config, models
from .audio import read, resample, speech_mask

_lock = threading.Lock()
_knn = None
_pool = None          # (signature, tensor) of your voice
_chatterbox = None


def voice_files():
    return sorted(config.VOICE.glob("sample_*.wav"))


def voice_minutes():
    import soundfile as sf
    return sum(sf.info(str(p)).duration for p in voice_files()) / 60


def _signature():
    return "|".join(f"{p.name}:{p.stat().st_size}" for p in voice_files())


def chatterbox_installed():
    try:
        import importlib.util
        return importlib.util.find_spec("chatterbox") is not None
    except Exception:
        return False


# ---------- built-in converter (kNN-VC) ----------
def _load_knn():
    global _knn
    if _knn is None:
        import json
        import torch
        vendor = str(Path(__file__).parent / "vendor" / "knnvc")
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        from hifigan.models import Generator
        from hifigan.utils import AttrDict
        from matcher import KNeighborsVC
        from wavlm.WavLM import WavLM, WavLMConfig
        torch.set_num_threads(config.load()["threads"])
        h = AttrDict(json.loads((Path(vendor) / "hifigan" / "config_v1_wavlm.json").read_text()))
        gen = Generator(h)
        gen.load_state_dict(torch.load(models.path("converter_out"), map_location="cpu", weights_only=True)["generator"])
        gen.eval()
        gen.remove_weight_norm()
        ck = torch.load(models.path("converter"), map_location="cpu", weights_only=False)
        wavlm = WavLM(WavLMConfig(ck["cfg"]))
        wavlm.load_state_dict(ck["model"])
        wavlm.eval()
        _knn = KNeighborsVC(wavlm, gen, h, "cpu")
    return _knn


def _features(knn, x16: np.ndarray):
    """Voice features of 16 kHz audio, worked out in 20 s pieces to keep memory low."""
    import torch
    feats, CH = [], 20 * 16000
    for off in range(0, len(x16), CH):
        piece = x16[off:off + CH]
        if len(piece) < 4000:
            continue
        feats.append(knn.get_features(torch.from_numpy(piece.copy()), vad_trigger_level=0))
    return torch.cat(feats, dim=0)


def learn_voice(progress=None):
    """Study your voice samples. Cached, so it only runs again when the samples change."""
    global _pool
    import torch
    sig = _signature()
    if not sig:
        raise RuntimeError("Record a voice sample first (My Voice tab).")
    cache = config.VOICE / "voice.pt"
    with _lock:
        if _pool and _pool[0] == sig:
            return _pool[1]
        if cache.exists():
            saved = torch.load(cache, map_location="cpu", weights_only=True)
            if saved.get("sig") == sig:
                _pool = (sig, saved["pool"])
                return _pool[1]
        knn = _load_knn()
        parts = []
        files = voice_files()
        for n, p in enumerate(files):
            if progress:
                progress(f"Studying your voice ({n + 1} of {len(files)})")
            x = read(p, 16000)
            m, _ = speech_mask(x, 16000)          # keep the speech, drop the silences
            keep = np.repeat(m, 160)[: len(x)]
            x = x[: len(keep)][keep]
            if len(x) > 8000:
                parts.append(_features(knn, x / (np.abs(x).max() + 1e-9) * 0.7))
        pool = torch.cat(parts, dim=0)
        torch.save({"sig": sig, "pool": pool}, cache)
        _pool = (sig, pool)
        return pool


def _convert_knn(x: np.ndarray, sr: int, progress=None):
    pool = learn_voice(progress)
    with _lock:
        knn = _load_knn()
        x16 = resample(x, sr, 16000)
        x16 = x16 / (np.abs(x16).max() + 1e-9) * 0.7
        out = knn.match(_features(knn, x16.astype(np.float32)), pool, topk=4, tgt_loudness_db=None)
    return out.numpy().astype(np.float32), 16000


# ---------- optional converter (Chatterbox, needs the extra engines) ----------
def _reference_clip():
    """About 12 s of your clearest speech, as Chatterbox wants one short example."""
    ref = config.VOICE / "reference.wav"
    files = voice_files()
    if not files:
        raise RuntimeError("Record a voice sample first (My Voice tab).")
    if not ref.exists() or ref.stat().st_mtime < max(p.stat().st_mtime for p in files):
        import soundfile as sf
        x = read(files[0], 24000)
        m, _ = speech_mask(x, 24000)
        start = int(np.argmax(m)) * 240
        sf.write(str(ref), x[start:start + 12 * 24000], 24000, subtype="PCM_16")
    return ref


def _convert_chatterbox(x: np.ndarray, sr: int, progress=None):
    global _chatterbox
    import soundfile as sf
    with _lock:
        if _chatterbox is None:
            if progress:
                progress("Loading the Chatterbox converter (first time downloads it)")
            from chatterbox.vc import ChatterboxVC
            _chatterbox = ChatterboxVC.from_pretrained(device="cpu")
        src = config.DATA / "_reader_tmp.wav"
        sf.write(str(src), x, sr, subtype="PCM_16")
        wav = _chatterbox.generate(str(src), target_voice_path=str(_reference_clip()))
        src.unlink(missing_ok=True)
    return wav.squeeze().detach().cpu().numpy().astype(np.float32), int(_chatterbox.sr)


def convert(x: np.ndarray, sr: int, settings=None, progress=None):
    """Reader speech in, the same speech in your voice tone out. Returns (samples, sample_rate)."""
    s = settings or config.load()
    if s.get("converter") == "chatterbox" and chatterbox_installed():
        return _convert_chatterbox(x, sr, progress)
    return _convert_knn(x, sr, progress)
