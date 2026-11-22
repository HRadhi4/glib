"""The local web server behind the Glib window. Nothing here talks to the internet except engine downloads."""
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, audio, config, master, models, pipeline, recorder, store, vc

app = FastAPI(title="Glib")


@app.middleware("http")
async def _seen(request, call_next):
    """Any request from the window counts as 'the window is open'."""
    if request.url.path.startswith("/api/") and request.url.path != "/api/bye":
        last_seen.update(t=time.time(), ever=True, bye=0.0)
    return await call_next(request)
app.mount("/assets", StaticFiles(directory=str(config.WEB / "assets")), name="assets")

last_seen = {"t": time.time(), "ever": False, "bye": 0.0}
jobs = {}                 # key -> {"label", "state", "note"}
_queue = queue.Queue()
_exports = {}


def _worker():
    while True:
        key, fn = _queue.get()
        job = jobs[key]
        job["state"] = "running"
        try:
            fn(lambda msg: job.__setitem__("note", msg))
            jobs.pop(key, None)
        except Exception as e:
            traceback.print_exc()
            job.update(state="error", note=_plain(e))


def _plain(e):
    text = str(e) or e.__class__.__name__
    if isinstance(e, (ImportError, ModuleNotFoundError)):
        return "A part of Glib is missing. Run the Glib installer again to repair it."
    if isinstance(e, MemoryError) or "not enough memory" in text.lower():
        return "The computer ran out of memory. Close other programs and try again."
    return text[:300]


threading.Thread(target=_worker, daemon=True).start()


def submit(key, label, fn):
    if key in jobs and jobs[key]["state"] in ("queued", "running"):
        return
    jobs[key] = {"label": label, "state": "queued", "note": ""}
    _queue.put((key, fn))


def _need(pid, idx=None):
    try:
        p = store.load(pid)
    except Exception:
        raise HTTPException(404, "That script could not be found.")
    if idx is not None and not (0 <= idx < len(p["lines"])):
        raise HTTPException(404, "That line does not exist.")
    return p


# ---------------- pages ----------------
@app.get("/")
def index():
    return FileResponse(config.WEB / "index.html", headers={"Cache-Control": "no-store"})


@app.post("/api/bye")
def bye():
    """Sent by the window as it closes."""
    last_seen["bye"] = time.time()
    return {"ok": True}


@app.get("/api/state")
def state(pid: str = ""):
    s = config.load()
    out = {
        "version": __version__, "settings": s, "voices": config.BRITISH_VOICES,
        "choices": {"loudness": master.LOUDNESS_TARGETS, "denoise": master.DENOISE_LEVELS},
        "engines": models.status(s),
        "voice": {"minutes": round(vc.voice_minutes(), 2), "reader": _reader_note(),
                  "samples": [{"name": p.name, "seconds": round(_dur(p)), "check": _quality().get(p.name)}
                              for p in vc.voice_files()]},
        "recorder": recorder.status(), "projects": store.listing(),
        "jobs": [dict(j, key=k) for k, j in jobs.items()],
        "exports": _exports,
    }
    if pid:
        try:
            p = store.load(pid)
            for l in p["lines"]:
                l["pick"] = pipeline.pick(l)
            out["project"] = p
        except Exception:
            out["project"] = None
    return out


def _reader_note():
    import json
    f = config.VOICE / "reader_match.json"
    try:
        d = json.loads(f.read_text())
        return {"voice": config.BRITISH_VOICES.get(d["voice"], d["voice"]), "pitch": d.get("your_pitch_hz")}
    except Exception:
        return None


def _dur(p):
    import soundfile as sf
    return sf.info(str(p)).duration


@app.post("/api/settings")
def settings(changes: dict = Body(...)):
    return config.save(changes)


@app.get("/api/devices")
def devices():
    return recorder.devices()


@app.post("/api/engines/download")
def engines_download():
    models.download_in_background()
    return {"ok": True}


# ---------------- scripts ----------------
@app.post("/api/projects")
def new_project(body: dict = Body(...)):
    if not (body.get("script") or "").strip():
        raise HTTPException(400, "Paste the script first.")
    return store.create(body.get("title") or "Untitled", body["script"])


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    import shutil
    _need(pid)
    shutil.rmtree(store.folder(pid), ignore_errors=True)
    return {"ok": True}


@app.put("/api/projects/{pid}/lines/{idx}")
def edit_line(pid: str, idx: int, body: dict = Body(...)):
    _need(pid, idx)
    changes = {}
    if "text" in body and body["text"].strip():
        changes.update(text=body["text"].strip(), review=None, check=None)
        for kind in ("polished", "rebuilt"):
            store.wav(pid, idx, kind).unlink(missing_ok=True)
    if "choice" in body:
        changes["choice"] = body["choice"] if body["choice"] in ("raw", "polished", "rebuilt") else None
    p = store.update_line(pid, idx, **changes)
    if "text" in changes and store.wav(pid, idx, "raw").exists():
        submit(f"polish:{pid}:{idx}", f"Checking line {idx + 1}", lambda note: pipeline.polish(pid, idx, note))
    return p


def _take_in(pid, idx, x):
    if len(x) < config.SR * 0.3:
        raise HTTPException(400, "That recording was too short. Hold on a little longer before stopping.")
    audio.write(store.wav(pid, idx, "raw"), x)
    store.wav(pid, idx, "polished").unlink(missing_ok=True)
    store.update_line(pid, idx, review=None, choice=None)
    submit(f"polish:{pid}:{idx}", f"Checking line {idx + 1}", lambda note: pipeline.polish(pid, idx, note))


@app.post("/api/record/start")
def record_start(body: dict = Body(...)):
    try:
        recorder.start(body.get("target"), config.load().get("input_device"))
    except Exception as e:
        raise HTTPException(500, f"The microphone could not be started. Check that one is plugged in and allowed "
                                 f"in Windows sound settings. ({_plain(e)})")
    return {"ok": True}


@app.post("/api/record/stop")
def record_stop(body: dict = Body(default={})):
    try:
        x, target = recorder.stop()
    except Exception as e:
        raise HTTPException(400, _plain(e))
    if body.get("discard") or not target:
        return {"ok": True}
    if target.get("voice"):
        return _add_voice(x)
    _need(target["pid"], target["idx"])
    _take_in(target["pid"], target["idx"], x)
    return {"ok": True}


async def _decode(file: UploadFile):
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
    try:
        return audio.read(tmp.name)
    except Exception:
        raise HTTPException(400, "That file could not be read. Use a WAV, MP3, FLAC or OGG sound file.")
    finally:
        os.unlink(tmp.name)


@app.post("/api/projects/{pid}/lines/{idx}/upload")
async def upload_line(pid: str, idx: int, file: UploadFile):
    _need(pid, idx)
    _take_in(pid, idx, await _decode(file))
    return {"ok": True}


@app.post("/api/projects/{pid}/lines/{idx}/rebuild")
def rebuild_line(pid: str, idx: int):
    _need(pid, idx)
    _check_rebuild_ready()
    submit(f"rebuild:{pid}:{idx}", f"Rebuilding line {idx + 1}", lambda note: pipeline.rebuild(pid, idx, note))
    return {"ok": True}


@app.post("/api/projects/{pid}/rebuild")
def rebuild_many(pid: str, body: dict = Body(default={})):
    p = _need(pid)
    _check_rebuild_ready()
    n = 0
    for i, l in enumerate(p["lines"]):
        needs = not l["has"]["rebuilt"] if body.get("only_missing", True) else True
        if body.get("only_flagged"):
            needs = needs and not (l.get("review") and l["review"]["state"] == "good")
        if needs:
            submit(f"rebuild:{pid}:{i}", f"Rebuilding line {i + 1}",
                   lambda note, i=i: pipeline.rebuild(pid, i, note))
            n += 1
    return {"queued": n}


def _check_rebuild_ready():
    if not models.status(config.load())["rebuild_ready"]:
        raise HTTPException(400, "The voice engines are not downloaded yet. Press Download on the top bar.")
    if not vc.voice_files():
        raise HTTPException(400, "Rebuild needs to know your voice. Record a sample in the My Voice tab first.")


@app.get("/api/projects/{pid}/lines/{idx}/{kind}.wav")
def line_audio(pid: str, idx: int, kind: str):
    if kind not in ("raw", "polished", "rebuilt"):
        raise HTTPException(404)
    f = store.wav(pid, idx, kind)
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{pid}/export")
def export(pid: str):
    _need(pid)

    def run(note):
        note("Joining the lines")
        _exports[pid] = pipeline.export(pid)
    submit(f"export:{pid}", "Exporting the audio", run)
    return {"ok": True}


@app.get("/api/projects/{pid}/export.wav")
def export_file(pid: str):
    e = _exports.get(pid)
    if not e or not Path(e["file"]).exists():
        raise HTTPException(404)
    return FileResponse(e["file"], media_type="audio/wav", filename=e["name"])


@app.post("/api/open")
def open_folder(body: dict = Body(default={})):
    target = store.folder(body["pid"]) if body.get("pid") else config.DATA
    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except Exception:
        pass
    return {"folder": str(target)}


# ---------------- your voice ----------------
def _add_voice(x):
    if len(x) < config.SR * 5:
        raise HTTPException(400, "That sample was too short. Read for at least 20 seconds.")
    config.ensure_dirs()
    n = 1 + max([int(p.stem.split("_")[1]) for p in vc.voice_files()] or [0])
    s = config.load()
    raw_check = master.check_sample(x, config.SR)
    # keep the voice natural for the converter: no compression or EQ, only rumble and (gentle) noise removal
    x = master.rumble_filter(x, config.SR)
    x = master.denoise(x, config.SR, "gentle" if s.get("denoise") != "off" else "off", s["threads"])
    peak = float(abs(x).max()) or 1.0
    x = x * (0.89 / peak)
    name = f"sample_{n:02d}.wav"
    audio.write(config.VOICE / name, x)
    _quality()[name] = raw_check
    _save_quality()
    return {"ok": True, "minutes": round(vc.voice_minutes(), 2), "check": raw_check}


def _quality():
    global _q
    if "_q" not in globals():
        import json
        f = config.VOICE / "quality.json"
        _q = json.loads(f.read_text()) if f.exists() else {}
    return _q


def _save_quality():
    import json
    (config.VOICE / "quality.json").write_text(json.dumps(_quality(), indent=1))


@app.post("/api/voice/upload")
async def voice_upload(file: UploadFile):
    return _add_voice(await _decode(file))


@app.delete("/api/voice/{name}")
def voice_delete(name: str):
    f = config.VOICE / Path(name).name
    if f.exists() and f.name.startswith("sample_"):
        f.unlink()
        _quality().pop(f.name, None)
        _save_quality()
    return {"ok": True}


@app.get("/api/voice/{name}")
def voice_audio(name: str):
    f = config.VOICE / Path(name).name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/api/voice/learn")
def voice_learn():
    _check_rebuild_ready()
    submit("voice", "Studying your voice", lambda note: vc.learn_voice(note))
    return {"ok": True}


@app.post("/api/jobs/clear")
def jobs_clear():
    for k in [k for k, j in jobs.items() if j["state"] == "error"]:
        jobs.pop(k, None)
    return {"ok": True}


@app.exception_handler(Exception)
async def oops(request, exc):
    traceback.print_exc()
    return JSONResponse({"detail": _plain(exc)}, status_code=500)
