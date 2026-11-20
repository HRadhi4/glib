"""Compares what was said with the script, word by word, and decides what to cut and what to flag."""
import re
from difflib import SequenceMatcher

FILLERS = {"um", "uh", "uhm", "umm", "er", "erm", "ah", "eh", "hmm", "mm", "mhm", "uhh", "hm"}

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen " \
       "sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
NUMBER_WORDS = set(ONES) | set(TENS[2:]) | {"hundred", "thousand", "point", "and", "oh"}


# spoken unit names -> the short written form, so "2 mL/kg" matches "two mils per kilo"
UNITS = {}
for short, longs in {
    "ml": "milliliter milliliters millilitre millilitres mil mils", "kg": "kilogram kilograms kilo kilos",
    "mg": "milligram milligrams", "mcg": "microgram micrograms", "g": "gram grams",
    "mmol": "millimole millimoles", "meq": "milliequivalent milliequivalents",
    "min": "minute minutes mins", "h": "hour hours hr hrs", "l": "liter liters litre litres",
    "cm": "centimeter centimeters centimetre centimetres", "wk": "week weeks",
}.items():
    for long in longs.split():
        UNITS[long] = short


def number_words(n: int):
    if n < 20:
        return [ONES[n]]
    if n < 100:
        return [TENS[n // 10]] + ([ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        return [ONES[n // 100], "hundred"] + (number_words(n % 100) if n % 100 else [])
    if n < 1_000_000:
        return number_words(n // 1000) + ["thousand"] + (number_words(n % 1000) if n % 1000 else [])
    return [ONES[int(d)] for d in str(n)]


def spoken_number(tok: str):
    whole, _, frac = tok.partition(".")
    out = number_words(int(whole)) if whole else []
    if frac:
        out += ["point"] + [ONES[int(d)] for d in frac]
    return out


def apply_say_as(text: str, say_as: dict) -> str:
    """Replace written forms with how they are spoken (PEEP -> peep)."""
    for written, spoken in sorted((say_as or {}).items(), key=lambda kv: -len(kv[0])):
        if written.strip():
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(written.strip())}(?![A-Za-z0-9])", spoken, text,
                          flags=re.IGNORECASE)
    return text


def words(text: str):
    """Text -> list of (comparison form, original form). Numbers become words; 'and' in numbers is dropped."""
    text = text.replace("%", " percent ").replace("&", " and ").replace("’", "'")
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    text = re.sub(r"(?<=[A-Za-z])/(?=[A-Za-z])", " per ", text)
    out = []
    for sid, raw in enumerate(re.findall(r"\d+(?:\.\d+)?|[A-Za-z]+(?:'[A-Za-z]+)?", text)):
        if raw[0].isdigit():
            out += [(w, raw, sid) for w in spoken_number(raw)]
        else:
            w = raw.lower().replace("'", "")
            out.append((UNITS.get(w, w), raw, sid))
    cleaned = []
    for i, (w, raw, sid) in enumerate(out):
        if w == "and" and 0 < i < len(out) - 1 and out[i - 1][0] in NUMBER_WORDS and out[i + 1][0] in NUMBER_WORDS:
            continue
        cleaned.append((w, raw, sid))
    return cleaned


def likeness(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if a.rstrip("s") == b.rstrip("s"):
        return 0.95
    return SequenceMatcher(None, a, b).ratio()


def same(a: str, b: str) -> bool:
    r = likeness(a, b)
    return r >= 0.95 or (min(len(a), len(b)) >= 5 and r >= 0.80)


def starts(a: str, b: str) -> bool:
    """a is a cut-off beginning of b (a false start such as 'tachy-' before 'tachypnoea')."""
    return len(a) >= 1 and len(b) > len(a) and b.startswith(a)


def _joined(word, pieces):
    """Cost of reading several heard pieces as one script word ('t f i' = TFI, 'ret check' = recheck); 0 = no."""
    whole = "".join(pieces)
    if whole == word:
        return 0.05
    if any(p in FILLERS for p in pieces) or any(same(a, b) or starts(a, b) for a, b in zip(pieces, pieces[1:])):
        return 0
    if len(word) >= 6 and whole[0] == word[0] and whole[-2:] == word[-2:] and likeness(whole, word) >= 0.88:
        return 0.35
    return 0


def align(script, heard):
    """Best word-by-word pairing. Returns steps: (kind, script indexes, heard indexes).
    kind: ok | near | wrong | extra | missing"""
    n, m = len(script), len(heard)
    INF = 1e9
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0

    def relax(i, j, c, step):
        if c < cost[i][j]:
            cost[i][j] = c
            back[i][j] = step

    for i in range(n + 1):
        for j in range(m + 1):
            c = cost[i][j]
            if c >= INF:
                continue
            if i < n and j < m:
                r = likeness(script[i], heard[j])
                if same(script[i], heard[j]):
                    relax(i + 1, j + 1, c, ("ok", 1, 1))
                elif r >= 0.6 and min(len(script[i]), len(heard[j])) >= 3:
                    relax(i + 1, j + 1, c + 0.6, ("near", 1, 1))
                else:
                    relax(i + 1, j + 1, c + 1.3, ("wrong", 1, 1))
            if j < m:
                relax(i, j + 1, c + (0.4 if heard[j] in FILLERS else 1.0), ("extra", 0, 1))
            if i < n:
                relax(i + 1, j, c + 1.0, ("missing", 1, 0))
            # one written word heard as several ("TFI" -> "t f i") and the other way round
            for k in (2, 3, 4):
                if i < n and j + k <= m:
                    r = _joined(script[i], heard[j:j + k])
                    if r:
                        relax(i + 1, j + k, c + r, ("ok", 1, k))
                if j < m and i + k <= n and "".join(script[i:i + k]) == heard[j]:
                    relax(i + k, j + 1, c + 0.05, ("ok", k, 1))
    steps, i, j = [], n, m
    while i or j:
        kind, di, dj = back[i][j]
        steps.append((kind, list(range(i - di, i)), list(range(j - dj, j))))
        i, j = i - di, j - dj
    return steps[::-1]


def score(rv) -> float:
    """How far a take is from the script: lower is better."""
    hard = sum(1 for f in rv["flags"] if f["hard"])
    return 3 * hard + (len(rv["flags"]) - hard) + 2 * (rv["fillers_cut"] + rv["repeats_cut"])


def review(script_text: str, heard_words: list, say_as: dict = None):
    """heard_words: [{'word', 'start', 'end'}]. Returns what to cut, what to flag and a word-by-word view.
    A 'say as' entry is accepted either as written or as spoken."""
    best = _review(script_text, heard_words)
    spoken = apply_say_as(script_text, say_as)
    if spoken != script_text and score(best) > 0:
        other = _review(spoken, heard_words)
        if score(other) < score(best):
            best = other
    return best


def _review(script_text: str, heard_words: list):
    script = words(script_text)
    heard = []
    for hw in heard_words:
        stutter = bool(re.search(r"\b(\w{1,3})-\1", hw["word"].lower()))
        toks = words(hw["word"])
        for w, raw, _ in (toks[-1:] if stutter else toks):
            heard.append({"w": w, "raw": raw, "start": hw["start"], "end": hw["end"], "stutter": stutter})
    heard = [h for i, h in enumerate(heard) if not (
        h["w"] == "and" and 0 < i < len(heard) - 1
        and heard[i - 1]["w"] in NUMBER_WORDS and heard[i + 1]["w"] in NUMBER_WORDS)]
    S = [w for w, _, _ in script]
    H = [h["w"] for h in heard]
    steps = align(S, H)

    role = {}  # heard index -> ok | near | wrong | extra
    for kind, si, hi in steps:
        for j in hi:
            role[j] = kind
    cut = {j for j in range(len(H)) if role.get(j) == "extra" and H[j] in FILLERS}
    seq = [j for j in range(len(H)) if j not in cut]      # the take with the fillers taken out
    extra_pos = [i for i, j in enumerate(seq) if role.get(j) == "extra"]
    runs = []
    for i in extra_pos:
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])

    def echo(a, b):  # run a is a (possibly cut-off) copy of run b
        return len(a) == len(b) and all(same(H[seq[x]], H[seq[y]]) or starts(H[seq[x]], H[seq[y]])
                                        for x, y in zip(a, b))

    for run in runs:
        L = len(run)
        after = list(range(run[-1] + 1, run[-1] + 1 + L))
        before = list(range(run[0] - L, run[0]))
        if after and after[-1] < len(seq) and echo(run, after):
            cut.update(seq[i] for i in run)          # said twice: drop the first go
        elif before and before[0] >= 0 and echo(before, run):
            cut.update(seq[i] for i in before)       # keep the later, cleaner go
            for i in before:
                role[seq[i]] = "extra"
            for i in run:
                role[seq[i]] = "ok"
        else:
            for i in run:
                w = H[seq[i]]
                nxt = H[seq[i + 1]] if i + 1 < len(seq) else ""
                prv = H[seq[i - 1]] if i > 0 else ""
                if same(w, nxt) or starts(w, nxt) or (prv and same(w, prv)):
                    cut.add(seq[i])

    spans = []
    for j in sorted(cut):
        nxt = j + 1
        end = heard[nxt]["start"] if nxt < len(heard) else heard[j]["end"]
        spans.append((heard[j]["start"], max(end, heard[j]["start"] + 0.05)))

    flags, view = [], []
    last_sid = [None]

    def show(si):  # original spelling of the script words, each written number shown once
        out = []
        for i in si:
            if script[i][2] != last_sid[0]:
                out.append(script[i][1])
                last_sid[0] = script[i][2]
        return " ".join(out)

    def is_num(si):
        return any(script[i][1][0].isdigit() for i in si)

    for kind, si, hi in steps:
        s_txt = " ".join(dict.fromkeys(script[i][1] for i in si))
        h_txt = " ".join(heard[j]["raw"] for j in hi)
        if kind == "extra":
            j = hi[0]
            if j in cut:
                why = "filler" if H[j] in FILLERS else "repeat"
                view.append({"t": heard[j]["raw"], "k": "cut", "why": why})
            elif role.get(j) == "ok":
                view.append({"t": heard[j]["raw"], "k": "ok"})
            else:
                view.append({"t": heard[j]["raw"], "k": "extra"})
                flags.append({"kind": "extra", "text": f"Extra word not in the script: “{h_txt}”", "hard": True})
        elif kind == "missing":
            view.append({"t": s_txt, "k": "missing"})
            last_sid[0] = script[si[-1]][2]
            flags.append({"kind": "missing", "hard": True, "text":
                          f"Check the number “{s_txt}”" if is_num(si) else f"Missing word: “{s_txt}”"})
        elif kind == "wrong":
            view.append({"t": h_txt, "k": "wrong", "want": s_txt})
            last_sid[0] = script[si[-1]][2]
            flags.append({"kind": "wrong", "text": f"Wrong word: said “{h_txt}”, script says “{s_txt}”", "hard": True})
        elif kind == "near":
            view.append({"t": h_txt, "k": "near", "want": s_txt})
            last_sid[0] = script[si[-1]][2]
            flags.append({"kind": "near", "text": f"Check this word: heard “{h_txt}” for “{s_txt}”", "hard": False})
        else:
            if any(j in cut for j in hi):   # the earlier copy of a repeated phrase
                view.append({"t": h_txt, "k": "cut", "why": "repeat"})
            else:
                t = show(si)
                if t:
                    view.append({"t": t, "k": "ok"})
            if any(heard[j]["stutter"] for j in hi):
                flags.append({"kind": "stutter", "text": f"Stutter inside the word “{s_txt}”", "hard": True})

    n_fill = sum(1 for j in cut if H[j] in FILLERS)
    return {
        "heard": " ".join(h["raw"] for h in heard),
        "cuts": spans,
        "fillers_cut": n_fill,
        "repeats_cut": len(cut) - n_fill,
        "flags": flags,
        "view": view,
        "matched": sum(1 for k, si, _ in steps if k == "ok" for _ in si),
        "script_words": len(S),
    }
