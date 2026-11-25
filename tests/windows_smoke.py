"""End-to-end test of an installed Glib, driven through its own local web interface.

Run with Glib's bundled Python while Glib is running:
    "%LOCALAPPDATA%\\Programs\\Glib\\runtime\\python.exe" tests\\windows_smoke.py OUTDIR

A synthetic speaker (a different text-to-speech voice with an American accent) stands in for
the user: it records voice samples, reads takes with slips, and Glib must Polish and Rebuild them.
Everything measured is written to OUTDIR/results.json together with the audio for listening.
"""
import json
import os
import shutil
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "smoke_out")
OUT.mkdir(parents=True, exist_ok=True)
DATA = Path(os.environ.get("LOCALAPPDATA", "")) / "Glib"
for _ in range(120):                       # Glib writes the port it chose (the usual one may be taken)
    if (DATA / "glib.port").exists():
        break
    time.sleep(1)
PORT = int((DATA / "glib.port").read_text().strip())
URL = f"http://127.0.0.1:{PORT}"
R = {"steps": [], "started": time.time()}


def log(step, **kw):
    kw["step"] = step
    kw["t"] = round(time.time() - R["started"], 1)
    R["steps"].append(kw)
    print(json.dumps(kw), flush=True)
    (OUT / "results.json").write_text(json.dumps(R, indent=1))


def call(path, method="GET", body=None, raw=False, timeout=120):
    data, headers = None, {}
    if body is not None:
        data, headers = json.dumps(body).encode(), {"Content-Type": "application/json"}
    req = urllib.request.Request(URL + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
    return b if raw else json.loads(b or b"{}")


def upload(path, wav_bytes, name="take.wav"):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + wav_bytes + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(URL + path, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read() or b"{}")


def state(pid=""):
    return call("/api/state?pid=" + pid)


def wait_jobs(pid, limit=3600):
    t0 = time.time()
    while time.time() - t0 < limit:
        s = state(pid)
        live = [j for j in s["jobs"] if j["state"] in ("queued", "running")]
        errs = [j for j in s["jobs"] if j["state"] == "error"]
        if errs:
            log("job_error", jobs=errs)
            call("/api/jobs/clear", "POST")
        if not live:
            return s
        time.sleep(1)
    raise TimeoutError("jobs did not finish")


# ------------------------------------------------------------------ 1. app is up
for _ in range(90):
    try:
        call("/api/devices")
        break
    except Exception:
        time.sleep(1)
s = state()
log("app_up", version=s["version"], port=PORT, data_folder=str(DATA), engines=s["engines"])
log("second_launch_check", hello=call("/api/hello"))

# ------------------------------------------------------------------ 2. engines
t0 = time.time()
call("/api/engines/download", "POST")
while True:
    s = state()
    p = s["engines"]["progress"]
    if not p["running"] and (s["engines"]["rebuild_ready"] or p["error"]):
        break
    time.sleep(3)
log("engines", seconds=round(time.time() - t0), ready=s["engines"]["rebuild_ready"], error=p["error"],
    polish_ready=s["engines"]["polish_ready"])
if not s["engines"]["rebuild_ready"]:
    sys.exit(1)

# ------------------------------------------------------------------ 3. a stand-in speaker
from kokoro_onnx import Kokoro  # noqa: E402  (bundled with Glib)

K = Kokoro(str(DATA / "models" / "kokoro-v1.0.onnx"), str(DATA / "models" / "voices-v1.0.bin"))
SPEAKER = "am_michael"
rng = np.random.default_rng(7)


def say(text, speed=1.0):
    x, sr = K.create(text, voice=SPEAKER, speed=speed, lang="en-us")
    return np.asarray(x, np.float32), sr


def room(x):
    return (x + 0.003 * rng.standard_normal(len(x))).astype(np.float32)


def wav_bytes(x, sr):
    import io
    b = io.BytesIO()
    sf.write(b, x, sr, format="WAV", subtype="PCM_16")
    return b.getvalue()


PASSAGES = [
    "Every morning the town wakes slowly. The baker opens his shop at six, the first bus leaves the station at half past, and by eight o'clock the streets are busy with people on their way to work and school.",
    "Numbers should be easy to follow. Three point five kilometres, sixty pages an hour, ninety two percent, one hundred and twenty steps to the top of the tower. I say each number slowly so that nobody has to guess.",
    "Some questions have easy answers, and others take more thought. Why is the sky darker in winter? Which road should we choose first? What will we do if the weather changes? Asking out loud helps everybody think.",
    "When I explain an idea, I start with the reason, then I show the long way, and finally the quick way. Judgement, measure, pleasure, vision; thin, thick, these, those; yellow, jungle, cheerful, shallow.",
    "The weather outside may be warm or cool, bright or cloudy, but a good routine stays the same. Check the list, read the label twice, keep your desk tidy, and speak up early if something does not look right.",
    "Thank you for joining me today. In this short reading I will speak in my normal voice, at a steady and comfortable pace, exactly as I would when explaining something to a small group of friends.",
]
sample_dir = OUT / "speaker_samples"
sample_dir.mkdir(exist_ok=True)
for i, text in enumerate(PASSAGES * 2):
    x, sr = say(text, 0.95 if i % 2 else 1.0)
    x = room(np.concatenate([np.zeros(sr // 3, np.float32), x, np.zeros(sr // 2, np.float32)]))
    if i < 2:
        sf.write(sample_dir / f"speaker_{i + 1}.wav", x, sr)
    r = upload("/api/voice/upload", wav_bytes(x, sr), f"sample{i}.wav")
    log("voice_sample", n=i + 1, minutes=r.get("minutes"), check=r.get("check"))

# ------------------------------------------------------------------ 4. a script with slips
SCRIPT = """# A Short Walk Through the City
The city wakes up early, and the first trains leave at six.
We start at the old bridge and walk for about 20 minutes.
Turn left at the bakery, then follow the river to the market.
The market has more than 40 stalls, and most of them open by eight.
If it rains, we take the covered path along the station, which adds about five minutes to the walk but keeps everyone dry and comfortable.
Thank you for walking with me today."""
pid = call("/api/projects", "POST", {"title": "Smoke test", "script": SCRIPT})["id"]
TAKES = [
    "A short walk through the city.",
    "The city wakes up, um, early, and the first trains leave at six.",
    "We start at the old, the old bridge and walk for about 20 minutes.",
    "Turn left at the bakery, then follow the river to the market.",
    "The market has more than 50 stalls, and most of them open by eight.",
    "If it rains, we take the covered path along the station, which adds about five minutes to the walk but keeps everyone dry and comfortable.",
    "Thank you for walking with with me today.",
]
t0 = time.time()
for i, take in enumerate(TAKES):
    x, sr = say(take)
    x = room(np.concatenate([np.zeros(sr // 2, np.float32), x, np.zeros(sr // 2, np.float32)]))
    upload(f"/api/projects/{pid}/lines/{i}/upload", wav_bytes(x, sr))
s = wait_jobs(pid)
for i, line in enumerate(s["project"]["lines"]):
    r = line.get("review") or {}
    log("polish", line=i + 1, state=r.get("state"), slips_removed=r.get("slips_removed"),
        pause_removed=r.get("pause_removed"), flags=[f["text"] for f in r.get("flags", [])],
        lufs=r.get("lufs"), true_peak=r.get("true_peak"))
log("polish_total", seconds=round(time.time() - t0))

# ------------------------------------------------------------------ 5. rebuild every line
t0 = time.time()
call(f"/api/projects/{pid}/rebuild", "POST", {"only_missing": False})
s = wait_jobs(pid)
rb_seconds = round(time.time() - t0, 1)
audio_s = sum((l.get("check") or {}).get("seconds", 0) for l in s["project"]["lines"])
for i, line in enumerate(s["project"]["lines"]):
    log("rebuild", line=i + 1, check=line.get("check"))
log("rebuild_total", seconds=rb_seconds, audio_seconds=round(audio_s, 1),
    seconds_per_audio_second=round(rb_seconds / max(audio_s, 0.1), 2), reader=state()["voice"]["reader"])

# ------------------------------------------------------------------ 6. export
call(f"/api/projects/{pid}/export", "POST")
s = wait_jobs(pid)
log("export", result=s["exports"].get(pid))
(OUT / "export.wav").write_bytes(call(f"/api/projects/{pid}/export.wav", raw=True))
for i in range(len(TAKES)):
    for kind in ("raw", "polished", "rebuilt"):
        try:
            (OUT / f"line{i + 1}_{kind}.wav").write_bytes(call(f"/api/projects/{pid}/lines/{i}/{kind}.wav", raw=True))
        except Exception:
            pass

# ------------------------------------------------------------------ 6b. 'closest to my voice' engine, same lines
call("/api/settings", "POST", {"voice_engine": "match"})
t0 = time.time()
for i in (1, 2, 5):
    call(f"/api/projects/{pid}/lines/{i}/rebuild", "POST")
s = wait_jobs(pid)
log("rebuild_match", seconds=round(time.time() - t0, 1), checks=[s["project"]["lines"][i].get("check") for i in (1, 2, 5)])
for i in (1, 2, 5):
    (OUT / f"line{i + 1}_rebuilt_match.wav").write_bytes(call(f"/api/projects/{pid}/lines/{i}/rebuilt.wav", raw=True))
call("/api/settings", "POST", {"voice_engine": "natural"})

# ------------------------------------------------------------------ 6c. American accent
call("/api/settings", "POST", {"accent": "american"})
t0 = time.time()
for i in (1, 5):
    call(f"/api/projects/{pid}/lines/{i}/rebuild", "POST")
s = wait_jobs(pid)
log("rebuild_american", seconds=round(time.time() - t0, 1), reader=state()["voice"]["reader"],
    settings_reader=state()["settings"]["base_voice"], checks=[s["project"]["lines"][i].get("check") for i in (1, 5)])
for i in (1, 5):
    (OUT / f"line{i + 1}_rebuilt_american.wav").write_bytes(call(f"/api/projects/{pid}/lines/{i}/rebuilt.wav", raw=True))
call("/api/settings", "POST", {"accent": "british"})

# ------------------------------------------------------------------ 6d. whole audio from the script, no recording
pid2 = call("/api/projects", "POST", {"title": "No recording", "script": SCRIPT})["id"]
t0 = time.time()
call(f"/api/projects/{pid2}/autoread", "POST", {"accent": "american"})
s = wait_jobs(pid2)
log("autoread", seconds=round(time.time() - t0, 1), export=s["exports"].get(pid2),
    checks=[l.get("check", {}).get("state") if l.get("check") else None for l in s["project"]["lines"]])
(OUT / "autoread_american.wav").write_bytes(call(f"/api/projects/{pid2}/export.wav", raw=True))
call("/api/settings", "POST", {"accent": "british"})

# ------------------------------------------------------------------ 7. highest quality converter, same lines
call("/api/settings", "POST", {"voice_quality": "highest"})
t0 = time.time()
call("/api/engines/download", "POST")
while True:
    s = state()
    if not s["engines"]["progress"]["running"] and (s["engines"]["rebuild_ready"] or s["engines"]["progress"]["error"]):
        break
    time.sleep(3)
log("engines_highest", seconds=round(time.time() - t0), ready=s["engines"]["rebuild_ready"])
if s["engines"]["rebuild_ready"]:
    t0 = time.time()
    for i in (2, 5):
        call(f"/api/projects/{pid}/lines/{i}/rebuild", "POST")
    wait_jobs(pid)
    log("rebuild_highest", seconds=round(time.time() - t0, 1))
    for i in (2, 5):
        (OUT / f"line{i + 1}_rebuilt_highest.wav").write_bytes(
            call(f"/api/projects/{pid}/lines/{i}/rebuilt.wav", raw=True))
call("/api/settings", "POST", {"voice_quality": "standard"})

# ------------------------------------------------------------------ 8. converter internals
sys.path.insert(0, os.environ.get("GLIB_APP", ""))
try:
    from glib import vc, tts, config  # noqa: E402
    x, sr = tts.read_aloud(" ".join(PASSAGES[0].split()[:60]), config.load())
    log("long_source", seconds=round(len(x) / sr, 1))
    for piece in (9.0, 30.0):
        vc.PIECE_S = piece
        t0 = time.time()
        y, ysr = vc.convert(x, sr)
        sf.write(OUT / f"long_piece{int(piece)}.wav", y, ysr)
        log("long_convert", piece_seconds=piece, out_seconds=round(len(y) / ysr, 1), work=round(time.time() - t0, 1))
except Exception as e:
    log("long_convert_error", error=repr(e))

shutil.copy(DATA / "glib.log", OUT / "glib.log") if (DATA / "glib.log").exists() else None
log("done")
