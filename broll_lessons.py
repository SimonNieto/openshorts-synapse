"""B-roll v22 « leçons » (4-oct-2026): the chain learns from its own generations. Every picture decided after the
render — kept with the viewer's score, or dropped with its reason (broll_v20) — and every verdict of the channel's
owner (the dashboard's thumbs, app.py) is appended to a journal. The recent journal is summed up into a few
PRINCIPLE-like lines (never a scene to copy) that the art director, the verifier and the viewer read in their calls
(broll_ideas): what failed lately and why, what worked. The owner's verdicts weigh from one occurrence; a pattern of
the chain's own checks needs MIN_COUNT. The journal lives in output/_lessons (a .keep protects it from the job
sweep). Never raises into a job."""
import json
import os
import re
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LESSONS_DIR = os.environ.get("BROLL_LESSONS_DIR") or os.path.join(HERE, "output", "_lessons")
RECENT = 300          # events the summary reads, at most
DAYS = 14             # and none older than this
MIN_COUNT = 3         # a pattern of the checks below this count is noise
MAX_LINES = 8         # lines of a summary
_LOCK = threading.Lock()
# the check's reasons, grouped into the lessons' buckets
_AWAY = ("pulls attention away", "contradicts the words", "under the face alone")
_SAFETY = ("unsafe", "body photo")


def path():
    return os.path.join(LESSONS_DIR, "broll_lessons.jsonl")


def record(event):
    """Append one event (a dict; "at" is added). Keys the summary reads: source ("check" / "owner"), verdict
    ("keep" / "drop" / "up" / "down"), why, kind, role, flaw, score, subject, title, note, clip_title."""
    if os.environ.get("BROLL_LESSONS", "1") == "0":
        return False
    try:
        os.makedirs(LESSONS_DIR, exist_ok=True)
        keep = os.path.join(LESSONS_DIR, ".keep")
        if not os.path.exists(keep):
            open(keep, "w").close()
        line = json.dumps({**event, "at": time.time()}, ensure_ascii=False)
        with _LOCK:
            with open(path(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return True
    except Exception as e:
        print(f"   ⚠️ Lessons: not recorded ({str(e)[:80]}).")
        return False


def recent(n=RECENT, days=DAYS):
    """The last ``n`` events not older than ``days``, oldest first."""
    try:
        with open(path(), encoding="utf-8") as f:
            lines = f.readlines()[-n:]
    except OSError:
        return []
    out, floor = [], time.time() - days * 86400
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and float(e.get("at") or 0) >= floor:
            out.append(e)
    return out


def clear():
    try:
        os.remove(path())
    except OSError:
        pass


def _kind(e):
    k = str(e.get("kind") or "").strip().lower()
    return k if k in ("thing", "scene", "vision", "instrument", "body_inside", "pair") else "picture"


_KIND_WORDS = {"thing": "a thing", "scene": "a scene", "vision": "what a person perceives", "instrument": "an instrument's image",
               "body_inside": "a drawing of the inside of a body", "pair": "two things side by side",
               "picture": "a picture"}


def _lines(events, for_who):
    """[(count, line)] of the lessons in ``events``: the owner's first, then the checks' patterns."""
    out = []
    owner_down = [e for e in events if e.get("source") == "owner" and e.get("verdict") == "down"]
    owner_up = [e for e in events if e.get("source") == "owner" and e.get("verdict") == "up"]
    # the owner's lines always come first (a pattern's rank is its count, never above these)
    for e in owner_down[-4:]:
        what = _clean(e.get("note")) or f'{_clean(e.get("subject"))} for "{_clean(e.get("said"))[:60]}"'
        out.append((10 ** 6, f"The channel's owner rejected a picture: {what}."))
    if for_who == "judges":
        for e in owner_up[-3:]:
            liked = _clean(e.get("subject")) or _clean(e.get("title"))
            out.append((10 ** 6 - 1, "The channel's owner liked: " + liked + ' for "' + _clean(e.get("said"))[:60]
                                     + '" — that level is the bar.'))
    checks = [e for e in events if e.get("source") == "check"]
    # dropped for not beating the face / away from the words, by kind
    by_kind = {}
    for e in checks:
        if e.get("verdict") in ("drop", "alt") and str(e.get("why") or "") in _AWAY:
            by_kind[_kind(e)] = by_kind.get(_kind(e), 0) + 1
        elif e.get("verdict") == "keep" and isinstance(e.get("score"), int) and e["score"] <= 2:
            by_kind[_kind(e)] = by_kind.get(_kind(e), 0) + 1
    for kind, n in by_kind.items():
        if n >= MIN_COUNT:
            out.append((n, f"{n} pictures of {_KIND_WORDS[kind]} did not beat the face alone lately (the viewer saw a "
                           f"setting, a stock photo or nothing of the words): show the idea itself, with one or two "
                           f"true particular details, or propose no picture."))
    flaws = {}
    for e in checks:
        if e.get("verdict") in ("drop", "alt") and e.get("flaw") in ("setting", "object", "stock", "symbol"):
            flaws[e["flaw"]] = flaws.get(e["flaw"], 0) + 1
    for flaw, n in flaws.items():
        if n >= MIN_COUNT:
            word = {"setting": "the setting instead of the idea", "object": "an object placed to tick the box",
                    "stock": "a stock-photo look", "symbol": "a symbol to decode"}[flaw]
            out.append((n, f"{n} ideas flagged as {word} were dropped after the render: that flaw does not survive "
                           f"the picture, leave such ideas out."))
    text = sum(1 for e in checks if e.get("verdict") in ("drop", "alt") and e.get("why") == "text in it")
    if text >= MIN_COUNT:
        out.append((text, f"{text} pictures carried writing (screens, labels, calendars, diplomas, signs): never a thing "
                          f"that bears text."))
    missed = {}
    for e in checks:
        if e.get("verdict") in ("drop", "alt") and e.get("why") == "wrong subject":
            missed[_kind(e)] = missed.get(_kind(e), 0) + 1
    for kind, n in missed.items():
        if n >= MIN_COUNT:
            out.append((n, f"The engine missed the subject of {n} pictures of {_KIND_WORDS[kind]}: name the thing "
                           f"plainly, one subject, its particular details, nothing to compare it to."))
    safety = [str(e.get("why")) for e in checks if e.get("verdict") in ("drop", "alt") and e.get("why") in _SAFETY]
    if len(safety) >= MIN_COUNT:
        out.append((len(safety), f"{len(safety)} pictures were refused for safety after the render: nothing of the "
                                 f"inside of a body photographed, nothing of a death's means, no drug, no gore."))
    strong = {}
    for e in checks:
        if e.get("verdict") == "keep" and isinstance(e.get("score"), int) and e["score"] >= 4:
            strong[_kind(e)] = strong.get(_kind(e), 0) + 1
    for kind, n in sorted(strong.items(), key=lambda kv: -kv[1])[:2]:
        if n >= MIN_COUNT:
            out.append((n, f"What worked: {n} pictures of {_KIND_WORDS[kind]} scored 4 or 5 (the viewer understood "
                           f"more than he was told)."))
    return out


def _clean(v):
    return re.sub(r"\s+", " ", str(v or "")).replace('"', "'").strip()


def summary(for_who="director"):
    """The lessons block for a prompt ("" when there is nothing to say): the owner's verdicts, then the strongest
    patterns of the last RECENT events, MAX_LINES at most. ``for_who``: "director" (what to avoid, principles) or
    "judges" (the same, plus what the owner liked)."""
    events = recent()
    if not events:
        return ""
    lines = sorted(_lines(events, for_who), key=lambda cl: -cl[0])[:MAX_LINES]
    if not lines:
        return ""
    return ("LESSONS OF THE LAST DAYS (measured on this channel's own pictures; principles, never scenes to copy):\n"
            + "\n".join(f"- {line}" for _c, line in lines))
