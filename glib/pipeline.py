"""The two ways Glib improves a line: Polish (your real recording, tidied) and Rebuild (read again in your voice)."""
import re

import numpy as np

from . import align, asr, audio, config, master, store, tts, vc
from .config import SR

FLAT_BELOW = 2.0   # semitones of pitch spread; under this the delivery sounds flat


def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 0.03:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _safe_cut(x, a, b, text, s, now):
    """Remove one slip (roughly a..b seconds), but only keep the cut if a second listen confirms the
    line is closer to the script afterwards. Tries a few nearby cut points; returns (audio, review) or None."""
    dur, want = len(x) / SR, b - a
    spots = [t for t in audio.quiet_spots(x, a - 0.22, b + 0.22)]
    starts_ = [a] + [t for t in spots if abs(t - a) <= 0.22][:4]
    ends_ = [b] + [t for t in spots if abs(t - b) <= 0.22][:4]
    if a < 0.15:
        starts_ = [0.0]
    if b > dur - 0.10:
        ends_ = [dur]
    cands = sorted({(round(p, 3), round(q, 3)) for p in starts_ for q in ends_
                    if 0.5 * want <= q - p <= 1.6 * want + 0.12},
                   key=lambda c: abs(c[0] - a) + abs(c[1] - b))[:7]
    best = None
    for p, q in cands:
        y = audio.remove(x, max(0.0, p), min(dur, q))
        rv = align.review(text, asr.listen(y, SR, s), s.get("say_as"))
        sc = align.score(rv)
        if sc < now and (best is None or sc < best[0]):
            best = (sc, y, rv)
            if sc <= now - 2:
                break
    return best


def polish(pid: str, idx: int, note=None):
    s = config.load()
    p = store.load(pid)
    line = p["lines"][idx]
    x = master.rumble_filter(audio.read(store.wav(pid, idx, "raw")), SR)
    if note:
        note("Removing background noise")
    x = master.denoise(x, SR, s.get("denoise", "normal"), s["threads"])
    if note:
        note("Listening to the recording")
    heard = asr.listen(x, SR, s)
    if not heard:
        review = {"heard": "", "view": [], "fillers_cut": 0, "repeats_cut": 0, "pause_removed": 0,
                  "flags": [{"kind": "silent", "text": "No speech was heard. Check the microphone and record again.",
                             "hard": True}], "state": "check", "flat": False, "melody": None,
                  "seconds": round(len(x) / SR, 1)}
        return store.update_line(pid, idx, review=review)
    first = align.review(line["text"], heard, s.get("say_as"))
    removed = {"f": 0, "r": 0}

    def clean_up(y, current, rounds):
        """Cut the slips the listener found, then listen again: a quick repeat often hides behind
        another and only shows once the audio around it has changed."""
        for rnd in range(rounds):
            spans = _merge(current["cuts"])
            if not spans:
                break
            for a, b in reversed(spans):          # last slip first, so earlier times stay valid
                got = _safe_cut(y, a, b, line["text"], s, align.score(current))
                if got:
                    removed["f"] += max(0, current["fillers_cut"] - got[2]["fillers_cut"])
                    removed["r"] += max(0, current["repeats_cut"] - got[2]["repeats_cut"])
                    _, y, current = got
            again = align.review(line["text"], asr.listen(y, SR, s), s.get("say_as"))
            if align.score(again) >= align.score(current) and not again["cuts"]:
                current = again
                break
            current = again
        return y, current

    if first["cuts"] and note:
        note("Removing slips")
    y, final = clean_up(x, first, 3)
    if note:
        note("Tidying pauses and finishing the sound")
    y, pause_removed = audio.tighten(y, SR, s["max_pause"], s["keep_pause"])
    y = master.finish(y, SR, s, denoise_too=False)
    if note:
        note("Final listen")
    check = align.review(line["text"], asr.listen(y, SR, s), s.get("say_as"))
    if check["cuts"]:
        y, check = clean_up(y, check, 2)
    final = check if align.score(check) <= align.score(final) or check["cuts"] else final
    y = audio.fade_edges(y)
    audio.write(store.wav(pid, idx, "polished"), y)

    flags = list(final["flags"])
    if final["cuts"]:
        words_left = ", ".join(f"“{v['t']}”" for v in final["view"] if v["k"] == "cut")
        flags.append({"kind": "left", "hard": True,
                      "text": f"A repeated or filler word could not be removed cleanly: {words_left}"})
    mel = audio.melody(y)
    review = {
        "heard": first["heard"], "view": first["view"] if not removed["f"] + removed["r"] or not final["cuts"] else final["view"],
        "flags": flags,
        "fillers_cut": removed["f"], "repeats_cut": removed["r"], "slips_removed": removed["f"] + removed["r"],
        "pause_removed": round(pause_removed, 1),
        "melody": round(mel["spread"], 1) if mel else None,
        "flat": bool(mel and mel["spread"] < FLAT_BELOW),
        "state": "check" if any(f["hard"] for f in flags) else "good",
        "seconds": round(len(y) / SR, 1),
        **master.report(y, SR),
    }
    return store.update_line(pid, idx, review=review)


def rebuild(pid: str, idx: int, note=None):
    s = config.load()
    line = store.load(pid)["lines"][idx]
    if note:
        note("Reading the line")
    reader = vc.pick_reader(s)
    x, sr = tts.read_aloud(line["text"], dict(s, base_voice=reader))
    engine = vc.engine_for(s)
    if note:
        note("Speaking it in your voice")
    y, sr2 = vc.convert(x, sr, s, note, engine)
    y = audio.resample(y, sr2, SR)
    y, _ = audio.tighten(y, SR, max_pause=1.2, keep_pause=0.6)
    if note:
        note("Finishing the sound")
    y = audio.fade_edges(master.finish(y, SR, s, denoise_too=False))
    audio.write(store.wav(pid, idx, "rebuilt"), y)
    if note:
        note("Checking the result against the script")
    rv = align.review(tts.spoken_text(line["text"]), asr.listen(y, SR, s), s.get("say_as"))
    odd = [f for f in rv["flags"] if f["kind"] in ("wrong", "missing", "near")]
    # the second listen can mishear a perfectly good word, so these are "have a listen" notes, never blockers
    check = {"flags": [{"kind": f["kind"], "hard": False,
                        "text": "Have a listen: " + f["text"].replace("Wrong word: said", "the listener heard")
                        .replace("Check this word: heard", "the listener heard").replace("script says", "for")}
                       for f in odd],
             "state": "listen" if odd else "good", "seconds": round(len(y) / SR, 1), "engine": engine}
    return store.update_line(pid, idx, check=check)


def pick(line):
    """Which version of a line goes into the final audio."""
    has, choice = line["has"], line.get("choice")
    if choice and has.get(choice):
        return choice
    polished_ok = has["polished"] and line.get("review") and line["review"]["state"] == "good"
    if polished_ok:
        return "polished"
    if has["rebuilt"]:
        return "rebuilt"
    if has["polished"]:
        return "polished"
    return "raw" if has["raw"] else None


def export(pid: str, note=None):
    s = config.load()
    p = store.load(pid)
    parts, used, skipped = [], {"polished": 0, "rebuilt": 0, "raw": 0}, []
    for i, line in enumerate(p["lines"]):
        kind = pick(line)
        if not kind:
            skipped.append(i + 1)
            continue
        used[kind] += 1
        clip = audio.read(store.wav(pid, i, kind))
        if kind == "raw":                       # an untouched take still gets the same loudness as the rest
            clip = master.finish(master.rumble_filter(clip, SR), SR, s, denoise_too=False)
        parts.append(clip)
        gap = s["title_gap"] if line.get("title") else s["line_gap"]
        parts.append(np.zeros(int(SR * gap), np.float32))
    if not parts:
        raise RuntimeError("There is nothing to export yet. Record or rebuild at least one line.")
    out = np.concatenate([np.zeros(int(SR * 0.25), np.float32)] + parts)
    if note:
        note("Matching the loudness of the whole programme")
    out = master.limit(master.normalise(out, SR, float(s.get("loudness", "-16"))), SR, -1.0)
    name = re.sub(r"[^A-Za-z0-9 _-]+", "", p["title"]).strip() or "glib"
    path = store.folder(pid) / f"{name}.wav"
    audio.write(path, out, SR, "PCM_24")
    return {"file": str(path), "name": path.name, "minutes": round(len(out) / SR / 60, 2),
            "used": used, "skipped": skipped, **master.report(out, SR)}
