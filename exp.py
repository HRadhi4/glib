"""Voice-conversion strategy experiment (Chatterbox ONNX). Writes outputs/<condition>_<variant>_<line>.wav"""
import glob, os, time, json, urllib.request
import numpy as np, soundfile as sf
from scipy import signal
import onnxruntime as ort

SR = 24000
HF = "https://huggingface.co/TigreGotico/voiceclonnx-chatterbox/resolve/main/onnx"
os.makedirs("models", exist_ok=True); os.makedirs("outputs", exist_ok=True)
for f in ("speech_encoder_q8.onnx", "conditional_decoder_q8.onnx"):
    if not os.path.exists(f"models/{f}"):
        urllib.request.urlretrieve(f"{HF}/{f}", f"models/{f}")
so = ort.SessionOptions(); so.intra_op_num_threads = os.cpu_count()
enc = ort.InferenceSession("models/speech_encoder_q8.onnx", so, providers=["CPUExecutionProvider"])
dec = ort.InferenceSession("models/conditional_decoder_q8.onnx", so, providers=["CPUExecutionProvider"])
LOG = {"io": {"enc_in": [(i.name, i.shape) for i in enc.get_inputs()], "enc_out": [(o.name, o.shape) for o in enc.get_outputs()],
              "dec_in": [(i.name, i.shape) for i in dec.get_inputs()]}}


def load(p):
    x, sr = sf.read(p, dtype="float32", always_2d=True); x = x.mean(1)
    if sr != SR:
        g = np.gcd(sr, SR); x = signal.resample_poly(x, SR // g, sr // g).astype(np.float32)
    return x


def pk(x): return (x / (np.abs(x).max() + 1e-9) * 0.85).astype(np.float32)


def encode(x):
    _c, tok, xv, feat = enc.run(None, {"audio_values": pk(x)[None, :]})
    return tok, xv, feat


def frames_db(x, hop=240):
    n = len(x) // hop
    return 20 * np.log10(np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)


def windows(x, seconds, step=0.5):
    n = int(seconds * SR); db = frames_db(x); floor = np.percentile(db, 10); out = []
    for s in range(0, max(1, len(x) - n), int(step * SR)):
        d = db[s // 240:(s + n) // 240]; v = d > floor + 12
        out.append((min(v.mean(), 0.85) * 40 + (np.median(d[v]) - floor if v.any() else 0), s))
    return sorted(out, reverse=True), n


def build_refs(files):
    clips = []
    for f in files:
        x = load(f); w, n = windows(x, 10.0); clips.append((w[0][0], x[w[0][1]:w[0][1] + n]))
    clips.sort(key=lambda c: -c[0])
    tok, xv, feat = encode(clips[0][1])
    xs = [encode(c[1])[1] for c in clips]
    refs = {"V1_avg6": (tok, np.mean(np.concatenate([xv] + xs[1:6]), 0, keepdims=True), feat),
            "V2_single": (tok, xv, feat),
            "V3_avgall": (tok, np.mean(np.concatenate(xs), 0, keepdims=True), feat)}
    # V4: prompt built from the best 2.5 s phrases of four different recordings
    phrases = []
    for f in files[:4]:
        x = load(f); w, n = windows(x, 2.5); phrases.append(x[w[0][1]:w[0][1] + n])
    gap = np.zeros(int(0.15 * SR), np.float32)
    mix = np.concatenate(sum([[p, gap] for p in phrases], []))[: int(10 * SR)]
    t4, x4, f4 = encode(mix)
    refs["V4_phrases"] = (t4, refs["V1_avg6"][1], f4)
    return refs


def convert(src, ref):
    tok, xv, feat = ref
    stok, _, _ = encode(src)
    w = dec.run(None, {"speech_tokens": np.concatenate([tok, stok], 1).astype(np.int64),
                       "speaker_embeddings": xv.astype(np.float32), "speaker_features": feat})[0]
    return np.squeeze(w).astype(np.float32)


sources = {os.path.basename(f)[7:-4]: load(f) for f in sorted(glob.glob("inputs/source_*.wav"))}
for cond in ("clean", "room"):
    files = sorted(glob.glob(f"inputs/{cond}_speaker_*.wav"))
    t0 = time.time(); refs = build_refs(files); LOG[f"{cond}_ref_seconds"] = round(time.time() - t0, 1)
    for name, ref in refs.items():
        for line, src in sources.items():
            t0 = time.time(); y = convert(src, ref)
            sf.write(f"outputs/{cond}_{name}_{line}.wav", y, SR)
            LOG[f"{cond}_{name}_{line}"] = {"in_s": round(len(src) / SR, 2), "out_s": round(len(y) / SR, 2), "work": round(time.time() - t0, 1)}
            if name == "V1_avg6":   # V5: a second pass through the converter
                y2 = convert(y, ref); sf.write(f"outputs/{cond}_V5_twice_{line}.wav", y2, SR)
json.dump(LOG, open("outputs/log.json", "w"), indent=1)
print(json.dumps(LOG, indent=1))
