"""Clip Generator++ BETA "Synapse Cut playbook" (SYNAPSE_PLAYBOOK=1).

What the prompts cannot guarantee, done here in plain code: the credit line
that opens every description (show + episode + guest, the only place names
go), the check that no name slipped into a title, and one JSON per clip for
the channel's own stats (which title shape / topic got which views).

The prompt side lives in gemini_worker (QUESTION_TITLE_ADDENDUM,
PLAYBOOK_DETAIL_ADDENDUM); main.py, hook_grounding.py and the
regenerate-copy route switch them on with ``enabled()``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

# topic_bucket values the detail pass may use (stats group by them; phase 2
# will weight the scoring with them). Anything else is stored as "other".
TOPIC_BUCKETS = ("brain_danger", "substances", "psychosis_mental_illness", "crime_dark",
                 "medical_mystery", "mind_psychology", "self_improvement", "science_other", "other")

# Words of a show / episode title that are not part of a person's name.
_NOT_NAMES = set("""the a an and of with on in at for to from by ep episode experience podcast show radio
hour live part full interview talk talks clip clips official hd new""".split())

_UUID_PREFIX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_", re.I)
_CHUNK_SUFFIX = re.compile(r"-\d{3}$")          # "-001": the 500 MB pieces of a long source
_SHOW_SPLIT = re.compile(r"\s*(?:#\d+|\s-\s|\s–\s|\s\|\s|:\s)")
CREDIT_TAIL = "All rights to the original creators."


def enabled() -> bool:
    return os.environ.get("SYNAPSE_PLAYBOOK") == "1"


def episode_title(source_video: str) -> str:
    """'<job uuid>_Joe Rogan Experience #2553 - Andrew Huberman-002.mkv'
    -> 'Joe Rogan Experience #2553 - Andrew Huberman'."""
    name = os.path.splitext(os.path.basename(source_video or ""))[0]
    name = _CHUNK_SUFFIX.sub("", _UUID_PREFIX.sub("", name))
    return re.sub(r"[_\s]+", " ", name).strip()


def _no_hash(text: str) -> str:
    # "#2553" would be read as a hashtag by the publisher (app._HASHTAG_TOKEN_RE).
    return re.sub(r"#\s*(\d+)", r"Ep. \1", text)


def split_show(title: str, show: str = "") -> tuple:
    """(show, rest of the episode title). ``show`` (the profile's) wins over
    the guess: the part of the title before '#123', ' - ', ' | ' or ': '."""
    title = (title or "").strip()
    if show:
        bare = re.sub(r"^the\s+", "", show.strip(), flags=re.I)
        m = re.match(r"^(?:the\s+)?" + re.escape(bare) + r"\s*[,:|–-]?\s*", title, re.I)
        return show.strip(), (title[m.end():] if m else title).strip()
    m = _SHOW_SPLIT.search(title)
    if not m or m.start() == 0:
        return "", title
    return title[:m.start()].strip(), title[m.start():].strip(" -–|:")


def speaker_names(brief) -> list:
    out = []
    for s in (brief or {}).get("speakers") or []:
        n = str((s or {}).get("name") or "").strip()
        if n and n.lower() not in ("unknown", "none", "n/a", "unnamed"):
            out.append(n)
    return out


def credit_line(source_video: str, brief=None, show: str = "") -> str:
    """'Clip from Joe Rogan Experience, Ep. 2553 - Andrew Huberman. All rights
    to the original creators.' Guests the title does not name are added."""
    title = episode_title(source_video)
    show, rest = split_show(title, show)
    head = f"{show}, {rest}" if show and rest else (show or rest)
    missing = [n for n in speaker_names(brief) if n.lower() not in head.lower()]
    if missing:
        head += (", " if head else "") + "with " + " & ".join(missing)
    head = _no_hash(head).strip().rstrip(".")
    return f"Clip from {head}. {CREDIT_TAIL}" if head else CREDIT_TAIL


def with_credit(text: str, credit: str) -> str:
    """The credit line on its own first line; an older one is replaced."""
    body = (text or "").strip()
    if body.startswith("Clip from ") or body.startswith(CREDIT_TAIL):
        body = body.split("\n", 1)[1].strip() if "\n" in body else ""
    return f"{credit}\n{body}".strip() if credit else body


def name_tokens(source_video: str = "", brief=None, show: str = "", extra=()) -> list:
    """Every word of a person / show name that must not be in a title."""
    title = episode_title(source_video)
    parts = [title, show, *speaker_names(brief), *[x for x in extra if x]]
    toks = set()
    for p in parts:
        for w in re.findall(r"[A-Za-zÀ-ÿ'’]+", p or ""):
            w = re.sub(r"['’]s$", "", w)
            # Names are capitalised in a title; "brain" or "sleep" are not names.
            if len(w) >= 3 and w[0].isupper() and w.lower() not in _NOT_NAMES:
                toks.add(w.lower())
    return sorted(toks)


def names_in(title: str, tokens) -> list:
    low = (title or "").lower()
    return [t for t in tokens if re.search(r"(?<![a-zà-ÿ])" + re.escape(t) + r"(?![a-zà-ÿ])", low)]


def check_title(clip: dict, tokens) -> bool:
    """Sets clip['title_has_name'] (+ which names); True when one slipped in."""
    found = names_in(clip.get("video_title_for_youtube_short") or "", tokens)
    clip["title_has_name"] = bool(found)
    if found:
        clip["title_names"] = found
    else:
        clip.pop("title_names", None)
    return bool(found)


# The title shape the channel's numbers favour: a closed yes/no question
# ("Can a brain tumor make you a killer?" 7,100 views vs 1,300 for the
# statement). The prompt asks for it; this checks it, without AI.
TITLE_OPENERS = ("can", "is", "does", "are", "do", "will", "should")
TITLE_MAX = 60
_VAGUE_SUBJECT = re.compile(
    r"\b(?:this|that|these|those|one)\s+(?:show|guy|guys|man|woman|dude|person|people|thing|things|story|"
    r"clip|moment|video|podcast|one|trick|habit|stuff)\b"
    r"|^\w+\s+(?:he|she|they|him|her|them)\b", re.I)


def _first_word(title: str) -> str:
    return re.sub(r"[^a-z']", "", ((title or "").split() or [""])[0].lower())


def why_budget(n: int) -> int:
    """'Why' titles allowed in a batch of n clips: 1 in 3 (so none under 3)."""
    return n // 3


def assign_why_slots(shorts) -> None:
    """The first why_budget(n) 'Why' titles of the batch are allowed."""
    budget = why_budget(len(shorts))
    for c in shorts:
        c["why_slot"] = _first_word(c.get("video_title_for_youtube_short")) == "why" and budget > 0
        budget -= c["why_slot"]


def title_problems(title: str, why_slot: bool = False) -> list:
    t = (title or "").strip()
    core = re.sub(r"[^\w?!.)\"'’]+$", "", t)   # trailing emojis do not count
    first = _first_word(t)
    out = []
    if first == "why":
        if not why_slot:
            out.append("too many 'Why' titles (max 1 in 3)")
    elif first not in TITLE_OPENERS:
        out.append(f"starts with '{first or '?'}' (must be Can/Is/Does/Are/Do/Will/Should)")
    if not core.endswith("?"):
        out.append("not a question")
    m = _VAGUE_SUBJECT.search(core)
    if m:
        out.append(f"subject not named ('{m.group(0).strip()}')")
    if len(core) > TITLE_MAX:
        out.append(f"{len(core)} characters (max {TITLE_MAX})")
    return out


def check_format(clip: dict) -> bool:
    """Sets clip['title_format_ok'] (+ what is wrong); True when the title is fine."""
    problems = title_problems(clip.get("video_title_for_youtube_short"), bool(clip.get("why_slot")))
    clip["title_format_ok"] = not problems
    if problems:
        clip["title_format_issues"] = problems
    else:
        clip.pop("title_format_issues", None)
    return not problems


def moment_id(source_video: str, start, end) -> str:
    key = f"{episode_title(source_video)}|{float(start):.1f}|{float(end):.1f}"
    return "m_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def prepare(shorts, source_video, brief=None, show="", series_name=""):
    """After selection, before rendering: credit line in both descriptions,
    moment id, bucket clean-up and a first name check. Returns the name
    tokens (the render re-checks the title once hook grounding had its say)."""
    credit = credit_line(source_video, brief, show)
    tokens = name_tokens(source_video, brief, show, (series_name,))
    for c in shorts:
        for k in ("video_description_for_tiktok", "video_description_for_instagram"):
            c[k] = with_credit(c.get(k), credit)
        c["moment_id"] = moment_id(source_video, c.get("start", 0), c.get("end", 0))
        if c.get("topic_bucket") not in TOPIC_BUCKETS:
            c["topic_bucket"] = "other"
        if check_title(c, tokens):
            print(f"   ⚠️ Playbook: a name is in the title of the clip at {float(c.get('start', 0)):.0f}s "
                  f"({', '.join(c['title_names'])}): {c.get('video_title_for_youtube_short')}")
    assign_why_slots(shorts)
    for c in shorts:
        if not check_format(c):
            print(f"   ⚠️ Playbook: title format of the clip at {float(c.get('start', 0)):.0f}s "
                  f"({'; '.join(c['title_format_issues'])}): {c.get('video_title_for_youtube_short')}")
    return tokens


def hook_sentence(clip: dict, transcript=None) -> str:
    """The sentence the clip really opens on: the model's hook_line when the
    cut was aligned on it, else the first words heard."""
    if clip.get("hook_aligned") and clip.get("hook_line"):
        return str(clip["hook_line"]).strip()
    start = float(clip.get("start", 0))
    words = []
    for seg in (transcript or {}).get("segments", []):
        for w in seg.get("words", []) or []:
            if w.get("start", 0) >= start - 0.05:
                words.append(str(w.get("word", "")).strip())
                if re.search(r"[.!?…]$", words[-1]) or len(words) >= 30:
                    return " ".join(words)
    return " ".join(words)


def export_clip(clip: dict, output_dir: str, clip_filename: str, tokens, transcript=None) -> str:
    """<clip>_playbook.json next to the clip: what the stats need later."""
    check_title(clip, tokens)
    check_format(clip)
    start, end = float(clip.get("start", 0)), float(clip.get("end", 0))
    data = {
        "moment_id": clip.get("moment_id"),
        "clip_file": clip_filename,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 2),
        "topic_bucket": clip.get("topic_bucket") or "other",
        "hook_sentence": hook_sentence(clip, transcript),
        "hook_aligned": bool(clip.get("hook_aligned")),
        # No hook nor sentence start fitted the length band (main._playbook_start).
        "start_mid_sentence": bool(clip.get("start_mid_sentence")),
        # The end was moved earlier (onto a sentence end) to open on the hook.
        "end_moved_for_hook": bool(clip.get("end_fit_for_hook")),
        "title": clip.get("video_title_for_youtube_short") or "",
        "title_has_name": bool(clip.get("title_has_name")),
        "title_names": clip.get("title_names") or [],
        "title_format_ok": bool(clip.get("title_format_ok")),
        "title_format_issues": clip.get("title_format_issues") or [],
        "on_screen_hook": clip.get("viral_hook_text") or "",
        "score": clip.get("predicted_score"),
    }
    path = os.path.join(output_dir, os.path.splitext(clip_filename)[0] + "_playbook.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def update_export(output_dir: str, clip_filename: str, clip: dict, tokens) -> None:
    """After a regenerate-copy: new title in the clip's JSON (if it exists)."""
    path = os.path.join(output_dir, os.path.splitext(clip_filename)[0] + "_playbook.json")
    if not os.path.exists(path):
        return
    check_title(clip, tokens)
    check_format(clip)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.update({"title": clip.get("video_title_for_youtube_short") or "",
                 "title_has_name": bool(clip.get("title_has_name")),
                 "title_names": clip.get("title_names") or [],
                 "title_format_ok": bool(clip.get("title_format_ok")),
                 "title_format_issues": clip.get("title_format_issues") or [],
                 "on_screen_hook": clip.get("viral_hook_text") or ""})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
