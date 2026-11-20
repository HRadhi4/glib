"""Projects on disk: one folder per script, holding the lines and their recordings."""
import json
import re
import threading
import time

from . import config

_lock = threading.RLock()


def split_script(script: str):
    """One recording line per sentence. Lines starting with # are titles (longer pause after)."""
    lines = []
    for para in script.replace("\r", "").split("\n"):
        para = para.strip()
        if not para:
            continue
        if para.startswith("#"):
            lines.append({"text": para.lstrip("# ").strip(), "title": True})
            continue
        safe = re.sub(r"\b(Dr|Mr|Mrs|Ms|Prof|St|vs|No|approx|e\.g|i\.e)\.", lambda m: m.group(1) + "\u2024", para)
        for sent in re.split(r"(?<=[.!?])[\"')\]]?\s+(?=[A-Z0-9“\"(])", safe):
            if sent.strip():
                lines.append({"text": sent.strip().replace("\u2024", "."), "title": False})
    return lines


def _file(pid):
    return config.PROJECTS / pid / "project.json"


def folder(pid):
    return config.PROJECTS / pid


def wav(pid, idx, kind):
    return config.PROJECTS / pid / f"line_{idx + 1:03d}_{kind}.wav"


def create(title: str, script: str):
    config.ensure_dirs()
    title = title.strip() or "Untitled"
    pid = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "script"
    pid = f"{pid}-{time.strftime('%Y%m%d-%H%M%S')}"
    (config.PROJECTS / pid).mkdir(parents=True)
    p = {"id": pid, "title": title, "created": time.time(),
         "lines": [dict(l, review=None, check=None, choice=None, stamp=0) for l in split_script(script)]}
    save(p)
    return p


def load(pid):
    with _lock:
        p = json.loads(_file(pid).read_text("utf-8"))
    for i, l in enumerate(p["lines"]):
        l["has"] = {k: wav(pid, i, k).exists() for k in ("raw", "polished", "rebuilt")}
    return p


def save(p):
    with _lock:
        clean = dict(p, lines=[{k: v for k, v in l.items() if k != "has"} for l in p["lines"]])
        _file(p["id"]).write_text(json.dumps(clean, indent=1), "utf-8")


def update_line(pid, idx, **changes):
    with _lock:
        p = load(pid)
        p["lines"][idx].update(changes)
        p["lines"][idx]["stamp"] = int(time.time() * 1000)
        save(p)
        return p


def listing():
    config.ensure_dirs()
    out = []
    for d in config.PROJECTS.iterdir():
        if (d / "project.json").exists():
            try:
                p = json.loads((d / "project.json").read_text("utf-8"))
                out.append({"id": p["id"], "title": p["title"], "created": p["created"], "lines": len(p["lines"])})
            except Exception:
                pass
    return sorted(out, key=lambda x: -x["created"])
