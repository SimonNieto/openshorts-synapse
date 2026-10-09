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
                 "medical_mystery", "mind_psychology", "self_improvement", "science_other",
                 # Moments outside a brain / mind channel. Offered to the model only
                 # with a niche filter (NICHE_DETAIL_ADDENDUM): without a place to put
                 # a fight recap it filed it under science_other or self_improvement.
                 "sports_combat", "entertainment", "business_money", "other")
# What a moment is (5-oct-2026, gemini_worker.PLAYBOOK_DETAIL_ADDENDUM): the channel's peaks threaten someone
# the viewer can picture — the viewer ("could this happen to me?") or a person whose fate plays out in the clip
# (récit report, JRE #2553). An order of preference for the model's ranking, never a filter; exported in
# <clip>_playbook.json to read the views by nature. Anything else is stored as "other".
MOMENT_NATURES = ("threat_to_you", "person_at_stake", "your_mind", "debate", "other")
# What the first ~5 s heard must do (5-oct-2026, lot Sélection; the jury's criteria of the same names,
# hook_jury.py): the clip-choice call lists the ones its opening fails in ``opening_misses``.
OPENING_CRITERIA = ("stands_alone", "topic_named", "tension")
# The Synapse Cut's own niche, the brain and the mind (the profile's topics of 1-oct-2026): the profile screen
# shows the other buckets as off niche (4-oct-2026).
NICHE_CORE = ("brain_danger", "substances", "psychosis_mental_illness", "crime_dark", "medical_mystery",
              "mind_psychology", "self_improvement")

# The eyebrow of the documentary line (hooks "docline"): the bucket's name as
# a topic label, in the channel's caption language (English clips). "other"
# and an unknown bucket show no eyebrow, the rule alone.
HOOK_CATEGORY = {
    "brain_danger": "Brain", "substances": "Substances", "psychosis_mental_illness": "Mental health",
    "crime_dark": "True crime", "medical_mystery": "Medicine", "mind_psychology": "Psychology",
    "self_improvement": "Self-improvement", "science_other": "Science", "sports_combat": "Combat sports",
    "entertainment": "Entertainment", "business_money": "Money",
}


def hook_category(clip) -> str:
    """The topic label shown above the hook (HOOK_CATEGORY), "" when none."""
    return HOOK_CATEGORY.get(str((clip or {}).get("topic_bucket") or ""), "")


# What each bucket means, in the words the niche sentence of the prompts uses.
BUCKET_LABELS = {
    "brain_danger": "what damages or threatens the brain (injury, tumors, disease, the toll of addiction)",
    "substances": "drugs, alcohol, psychedelics and medication: what they do to the brain and the body",
    "psychosis_mental_illness": "psychosis and mental illness",
    "crime_dark": "the psychology behind crime and dark behaviour",
    "medical_mystery": "strange medical and neurological cases",
    "mind_psychology": "how the mind works: psychology, perception, memory, consciousness",
    "self_improvement": "discipline, habits, focus and tools for mental health",
    "science_other": "other science",
    "sports_combat": "sport and combat sports",
    "entertainment": "show business, comedy and celebrities",
    "business_money": "business and money",
}
# Points an off-niche clip loses by default. The detail pass scores the clips
# of a job within ~10 points of each other (72-83 on JRE #2515): 15 puts an
# off-niche clip under every on-niche one without erasing the score.
NICHE_WEIGHT = 15

# Words of a show / episode title that are not part of a person's name.
_NOT_NAMES = set("""the a an and of with on in at for to from by ep episode experience podcast show radio
hour live part full interview talk talks clip clips official hd new""".split())

_UUID_PREFIX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_", re.I)
_CHUNK_SUFFIX = re.compile(r"-\d{3}$")          # "-001": the 500 MB pieces of a long source
_SHOW_SPLIT = re.compile(r"\s*(?:#\d+|\s-\s|\s–\s|\s\|\s|:\s)")
CREDIT_TAIL = "All rights to the original creators."


def enabled() -> bool:
    return os.environ.get("SYNAPSE_PLAYBOOK") == "1"


def niche_settings():
    """The channel's positive topic list, or None when there is none (the
    default). ``NICHE_TOPICS``: comma-separated TOPIC_BUCKETS the channel is
    about; ``NICHE_WEIGHT``: points a clip outside them loses;
    ``NICHE_ONLY=1``: such a clip is dropped instead; ``NICHE_CONTEXT``: one
    sentence on the channel, put before the topics in the prompts."""
    topics = [t for t in (x.strip() for x in (os.environ.get("NICHE_TOPICS") or "").split(","))
              if t in TOPIC_BUCKETS and t != "other"]
    if not topics:
        return None
    try:
        weight = max(0.0, float(os.environ.get("NICHE_WEIGHT", "")))
    except ValueError:
        weight = float(NICHE_WEIGHT)
    return {"topics": topics, "weight": weight, "only": os.environ.get("NICHE_ONLY") == "1",
            "context": (os.environ.get("NICHE_CONTEXT") or "").strip()}


def niche_sentence(settings) -> str:
    """'<the channel in one sentence> — a; b; c' for the prompts."""
    topics = "; ".join(BUCKET_LABELS.get(t, t.replace("_", " ")) for t in settings["topics"])
    return f"{settings['context'].rstrip('.')} — {topics}" if settings.get("context") else topics


def apply_niche(shorts, settings):
    """(kept, dropped). A clip whose ``topic_bucket`` is outside the niche is
    marked ``off_niche`` and either dropped (``only``) or loses ``weight``
    points of ``predicted_score`` — the score every later ranking reads
    (trim_to_best, auto-publish, the dashboard); the model's own score stays
    in ``predicted_score_raw``."""
    kept, dropped = [], []
    for c in shorts:
        bucket = c.get("topic_bucket") if c.get("topic_bucket") in TOPIC_BUCKETS else "other"
        if bucket in settings["topics"]:
            kept.append(c)
            continue
        c["off_niche"] = True
        if settings["only"]:
            dropped.append(c)
            continue
        raw = c.get("predicted_score")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and "predicted_score_raw" not in c:
            c["predicted_score_raw"] = raw
            c["predicted_score"] = max(0, int(round(raw - settings["weight"])))
        kept.append(c)
    return kept, dropped


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
    """(show, rest of the episode title). ``show`` (the profile's) when the
    title starts with it; else the title's own show, the part before '#123',
    ' - ', ' | ' or ': '; else ``show``. Since 4-oct-2026 the profile's one
    show field also picks the hashtags ("Joe Rogan podcast"): the episode's
    own wording of its show wins over it."""
    title = (title or "").strip()
    show = (show or "").strip()
    if show:
        bare = re.sub(r"^the\s+", "", show, flags=re.I)
        m = re.match(r"^(?:the\s+)?" + re.escape(bare) + r"\s*[,:|–-]?\s*", title, re.I)
        if m:
            return show, title[m.end():].strip()
    m = _SHOW_SPLIT.search(title)
    if not m or m.start() == 0:
        return show, title
    return title[:m.start()].strip(), title[m.start():].strip(" -–|:")


def show_name(source_video: str, show: str = "", limit: int = 40) -> str:
    """The show a clip comes from, as the « CREDIT: » line at the top of the
    one-word captions names it (viral_fx.CORNER, 9-oct-2026): the episode
    title's own show ("Joe Rogan Experience"), else the profile's ``show``,
    else the title itself, cut at a word under ``limit`` characters."""
    title = episode_title(source_video)
    name, rest = split_show(title, show)
    name = (name or rest or "").strip()
    if len(name) > limit:
        name = name[:limit].rsplit(" ", 1)[0].strip(" -–|:,")
    return name


def speaker_names(brief) -> list:
    out = []
    for s in (brief or {}).get("speakers") or []:
        n = str((s or {}).get("name") or "").strip()
        if n and n.lower() not in ("unknown", "none", "n/a", "unnamed"):
            out.append(n)
    return out


def _spoken(name: str, spoken: str) -> bool:
    last = name.split()[-1]
    return bool(re.search(r"(?<![A-Za-z])" + re.escape(last) + r"(?![A-Za-z])", spoken, re.I))


def credit_line(source_video: str, brief=None, show: str = "", spoken=None) -> str:
    """'Clip from Joe Rogan Experience, Ep. 2553 - Andrew Huberman. All rights
    to the original creators.' Guests the title does not name are added —
    when ``spoken`` (the transcript text) is given, only if their name is
    actually said: a published credit must never name someone the brief
    guessed wrong."""
    title = episode_title(source_video)
    show, rest = split_show(title, show)
    head = f"{show}, {rest}" if show and rest else (show or rest)
    missing = [n for n in speaker_names(brief) if n.lower() not in head.lower()
               and (spoken is None or _spoken(n, spoken))]
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
    """'Why' titles allowed in a batch of n clips: 1 in 6 (so none under 6).
    Was 1 in 3 until 1-oct-2026: "Why" is an open question, the closed ones
    are what the channel's numbers favour."""
    return n // 6


def assign_why_slots(shorts) -> None:
    """The first why_budget(n) 'Why' titles of the batch are allowed."""
    budget = why_budget(len(shorts))
    for c in shorts:
        c["why_slot"] = _first_word(c.get("video_title_for_youtube_short")) == "why" and budget > 0
        budget -= c["why_slot"]


TITLE_STYLES = ("question", "references")


def title_style() -> str:
    """How titles are written: "references" (9-oct-2026, the OptimalHealth formulas: one everyday thing,
    4-8 words, question or statement, gemini_worker.REFERENCES_TITLE_ADDENDUM) or "question" (the closed
    yes/no question of 1-oct-2026, QUESTION_TITLE_ADDENDUM). TITLE_STYLE in a job's env (plus.job_env),
    else the house recipe's (plus.SELECTION) — the editor's regenerate-copy has no job env."""
    v = (os.environ.get("TITLE_STYLE") or "").strip().lower()
    if v not in TITLE_STYLES:
        try:
            import plus
            v = str(plus.SELECTION.get("title_style") or "question").lower()
        except Exception:
            v = "question"
    return v if v in TITLE_STYLES else "question"


# The "references" title (RECETTE_REFERENCES.md §4): OptimalHealth's median is 6 words, none has an emoji.
REF_TITLE_WORDS = (4, 8)
# Words that got a short held back (c05 "Is Big Pharma scared of microdosers?", 9 views, 5-oct-2026): the
# phrase itself, a prescription drug shared / split / sold / microdosed, and a drug not yet on the market
# (the 9-oct bench titled c05 "The Hidden Problem With Retitrutide Doses": the same held-back topic).
_HELD_BACK = re.compile(
    r"\bbig\s+pharma\b"
    r"|\bret\w{0,3}trutide\b|\borforglipron\b|\bcagrisema\b|\bsurvodutide\b"
    r"|\b(?:shar\w*|split\w*|sell\w*|sold|microdos\w*|trad\w*)\b.{0,40}\b(?:prescriptions?|meds|medications?|pills?)\b"
    r"|\b(?:prescriptions?|meds|medications?|pills?)\b.{0,40}\b(?:shar\w*|split\w*|sell\w*|sold|microdos\w*)\b",
    re.I)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def held_back_words(text: str) -> str:
    """The words of ``text`` that got a short held back ("" when none)."""
    m = _HELD_BACK.search(text or "")
    return m.group(0) if m else ""


def _reference_problems(t: str) -> list:
    out = []
    if _EMOJI.search(t):
        out.append("an emoji (none in this niche's titles)")
    core = _EMOJI.sub("", t).strip()
    n = len(re.findall(r"[\w’'-]+", core))
    lo, hi = REF_TITLE_WORDS
    if n < lo or n > hi:
        out.append(f"{n} words (must be {lo}-{hi})")
    if "#" in core:
        out.append("a hashtag")
    m = _VAGUE_SUBJECT.search(core)
    if m:
        out.append(f"subject not named ('{m.group(0).strip()}')")
    held = held_back_words(core)
    if held:
        out.append(f"words that got a short held back ('{held}')")
    if len(core) > TITLE_MAX:
        out.append(f"{len(core)} characters (max {TITLE_MAX})")
    return out


def title_problems(title: str, why_slot: bool = False, style: str = None) -> list:
    t = (title or "").strip()
    if (style or title_style()) == "references":
        return _reference_problems(t)
    core = re.sub(r"[^\w?!.)\"'’]+$", "", t)   # trailing emojis do not count
    first = _first_word(t)
    out = []
    if first == "why":
        if not why_slot:
            out.append("too many 'Why' titles (max 1 in 6)")
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


# --- the titles of one job, read as a set ----------------------------------------
# JRE #2515 (1-oct-2026): "DMT" in 4 titles of 6, "really / truly / just /
# ever" in 4 of 6. Each title passed title_problems; together they read like
# one short posted four times. Plain word counts, no AI: a miss costs one
# grouped retitle (main.retitle_repeats), never the clip.
TITLE_INTENSIFIERS = frozenset("really actually truly just ever even literally seriously".split())
TITLE_INTENSIFIER_MAX = 1
# "references" titles (title_style): the words that carry OptimalHealth's formulas, each in this many titles of a
# job at most; "really" / "actually" leave the padding words there.
TITLE_SIGNALS = frozenset("hidden really actually trick fastest truth myth".split())
TITLE_SIGNAL_MAX = 2


def title_variety_enabled() -> bool:
    """TITLE_VARIETY=1 (profile: selection.title_variety): the titles of a job
    are checked as a set and the repeats get one rewrite by the model."""
    return os.environ.get("TITLE_VARIETY") == "1"


def title_keyword_max(n: int) -> int:
    """How many titles of a batch of n one key word may carry: 2, or a third."""
    return max(2, n // 3)


def _title_keywords(title: str) -> set:
    return {w for w in _sig_words(title) if w not in TITLE_OPENERS and w not in TITLE_INTENSIFIERS
            and w not in TITLE_SIGNALS}


def _title_intensifier(title: str):
    return next((w for w in _hook_words(title) if w in TITLE_INTENSIFIERS), None)


def title_set_problems(shorts) -> dict:
    """{index: {"issues": [...], "avoid": [words]}} over the titles of one
    job: a key word in more than title_keyword_max(n) titles (the extra,
    lowest-scoring ones are the problem), an intensifier in more than
    TITLE_INTENSIFIER_MAX titles. {} when the set reads fine."""
    n = len(shorts)
    titles = [(i, c.get("video_title_for_youtube_short") or "") for i, c in enumerate(shorts)]

    def score(i):
        try:
            return float(shorts[i].get("predicted_score") or 0)
        except (TypeError, ValueError):
            return 0.0

    out = {}

    def flag(i, issue, word):
        rec = out.setdefault(i, {"issues": [], "avoid": []})
        rec["issues"].append(issue)
        if word not in rec["avoid"]:
            rec["avoid"].append(word)

    by_word = {}
    for i, t in titles:
        for w in _title_keywords(t):
            by_word.setdefault(w, []).append(i)
    cap = title_keyword_max(n)
    for w, idx in sorted(by_word.items()):
        if len(idx) <= cap:
            continue
        keep = sorted(idx, key=score, reverse=True)[:cap]
        for i in idx:
            if i not in keep:
                flag(i, f"'{w}' is already in {cap} other titles", w)
    if title_style() == "references":
        # The signal words ARE the formula (REFERENCES_VARIETY_ADDENDUM): each in TITLE_SIGNAL_MAX titles, the
        # padding words in TITLE_INTENSIFIER_MAX title.
        for w in sorted(TITLE_SIGNALS):
            idx = [i for i, t in titles if w in _hook_words(t)]
            if len(idx) > TITLE_SIGNAL_MAX:
                keep = sorted(idx, key=score, reverse=True)[:TITLE_SIGNAL_MAX]
                for i in idx:
                    if i not in keep:
                        flag(i, f"'{w}' is already in {TITLE_SIGNAL_MAX} other titles", w)
        ints = [(i, next((w for w in _hook_words(t) if w in TITLE_INTENSIFIERS - TITLE_SIGNALS), None))
                for i, t in titles]
    else:
        ints = [(i, _title_intensifier(t)) for i, t in titles]
    ints = [(i, x) for i, x in ints if x]
    if len(ints) > TITLE_INTENSIFIER_MAX:
        keep = sorted((i for i, _ in ints), key=score, reverse=True)[:TITLE_INTENSIFIER_MAX]
        for i, x in ints:
            if i not in keep:
                flag(i, f"'{x}' pads the question (one such title per job)", x)
    return out


RETITLE_PROMPT = """
You fix the titles of short video clips cut from one episode. A title is ONE
closed question in {language}, max 60 characters, ending with "?", starting
with Can, Is, Does, Are, Do, Will or Should, that names the concrete thing of
the clip and never contains its own answer. The clips of one episode are
posted one after the other: read as a set, their titles must not look like
the same short posted four times.

For each clip below you get its current title, what is wrong with it, the
words to leave out (`avoid`), its on-screen hook, the first sentences heard
and the payoff it ends on. `other_titles` are the episode's titles that stay.
Write ONE new title per clip:
- it uses none of the `avoid` words (nor their plural or another form): take
  another angle on the same moment — the consequence, the person, the
  mechanism, the number, the risk — rather than naming the thing again;
- no "really", "actually", "truly", "just", "ever": a plain question is stronger;
- it is not one of `other_titles` and shares no angle with them;
- it does not say the on-screen hook again;
- no name of a person or a show; never an explicit word for suicide or
  self-harm; a drug is shown from its risk or what it does, never as fun;
- true to the clip: a question this clip answers or explores.

CLIPS_JSON:
{clips}

Return only: {{"titles": [{{"id": <clip id>, "video_title_for_youtube_short": "<the question>"}}]}}
"""

RETITLE_SCHEMA = {
    "type": "object",
    "properties": {"titles": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "video_title_for_youtube_short": {"type": "string"}},
        "required": ["id", "video_title_for_youtube_short"]}}},
    "required": ["titles"],
}


# The same rewrite for "references" titles (title_style): OptimalHealth's shapes, one everyday thing.
REF_RETITLE_PROMPT = """
You fix the titles of short video clips cut from one episode. A title is 4 to
8 words in {language}, max 60 characters, Title Case, no emoji, a question or
a statement, about ONE thing the viewer knows (an object, a substance, a food,
a body part, an everyday gesture), in one of the shapes that work in this
niche: "The Hidden Problem With Melatonin", "The Eye Trick That Helps You Fall
Asleep", "What's Really In Your Shower Water?", "What Ibuprofen Really Does To
Your Body", "The Fastest Way To Calm Down", "Can Alzheimer's Actually Be
Reversed?". Hidden / Really / Actually / Trick / Fastest / Truth / Myth only
when it is TRUE of the clip. The clips of one episode are posted one after the
other: read as a set, their titles must not look like the same short posted
four times.

For each clip below you get its current title, what is wrong with it, the
words to leave out (`avoid`), its on-screen hook, the first sentences heard
and the payoff it ends on. `other_titles` are the episode's titles that stay.
Write ONE new title per clip:
- it uses none of the `avoid` words (nor their plural or another form): take
  another angle on the same moment or another of the formulas above;
- it is not one of `other_titles` and does not reuse their shape;
- it does not say the on-screen hook again;
- no name of a person or a show; never "Big Pharma" nor a prescription drug
  shared, split, sold or microdosed, nor a drug not yet approved (retatrutide…); never an explicit word for suicide or
  self-harm; a drug is shown from its risk or what it does, never as fun;
- true to the clip: it promises only what this clip says.

CLIPS_JSON:
{clips}

Return only: {{"titles": [{{"id": <clip id>, "video_title_for_youtube_short": "<the title>"}}]}}
"""


def retitle_prompt(items, other_titles, language: str = "en") -> str:
    """``items``: [{"id", "title", "problems", "avoid", "hook", "opening", "payoff"}]."""
    template = REF_RETITLE_PROMPT if title_style() == "references" else RETITLE_PROMPT
    return template.format(language=language or "en",
                                 clips=json.dumps({"other_titles": list(other_titles), "clips": items},
                                                  ensure_ascii=False, indent=1))


def apply_retitle(clip: dict, new_title: str, tokens, avoid, issues=None) -> bool:
    """Take the rewritten title when it passes title_problems (its 'Why'
    slot unchanged), carries no name and none of the ``avoid`` words; what
    happened is kept in clip['title_check']. True when the title changed."""
    old = (clip.get("video_title_for_youtube_short") or "").strip()
    new = re.sub(r"\s+", " ", str(new_title or "")).strip()
    record = {"retried": True, "before": old, "issues_before": list(issues or [])}
    if not new or new == old:
        clip["title_check"] = {**record, "kept": "no new title"}
        return False
    problems = title_problems(new, bool(clip.get("why_slot")))
    if problems:
        clip["title_check"] = {**record, "kept": f"the new title fails the format ({'; '.join(problems)})",
                               "rejected": new}
        return False
    if names_in(new, tokens or ()):
        clip["title_check"] = {**record, "kept": "a name in the new title", "rejected": new}
        return False
    bad = sorted(set(_hook_words(new)) | _sig_words(new)) if avoid else []
    stems = {a.rstrip("s") for a in avoid or ()}
    hit = next((w for w in bad if w in avoid or w.rstrip("s") in stems), None)
    if hit:
        clip["title_check"] = {**record, "kept": f"the new title still carries '{hit}'", "rejected": new}
        return False
    clip["video_title_for_youtube_short"] = new
    check_title(clip, tokens or ())
    check_format(clip)
    clip["title_check"] = record
    return True


def check_format(clip: dict) -> bool:
    """Sets clip['title_format_ok'] (+ what is wrong); True when the title is fine."""
    problems = title_problems(clip.get("video_title_for_youtube_short"), bool(clip.get("why_slot")))
    clip["title_format_ok"] = not problems
    if problems:
        clip["title_format_issues"] = problems
    else:
        clip.pop("title_format_issues", None)
    return not problems


# The on-screen hook must ADD to the title (a stake, a tension, a promise),
# not say it again: "Should you be afraid of testosterone therapy?" under the
# title "Should men be afraid of testosterone therapy as they age?" wastes the
# first seconds. Words that carry no subject are left out of the comparison.
_HOOK_STOPWORDS = set("""a an the and or but of to in on at for from by with about as into than then
is are was were be been being am do does did done can could will would should shall may might must
have has had not no yes so if it its it's this that these those there here what why how when who which
you your you're yours we our us i me my he him his she her they them their one ones just really
actually even ever more most very much many some any all every only also still too like get got
gets make makes made""".split())
HOOK_OVERLAP_MAX = 0.5


def _sig_words(text: str) -> set:
    out = set()
    for w in re.findall(r"[a-zà-ÿ0-9']+", (text or "").lower()):
        w = re.sub(r"'s$", "", w).strip("'")
        if len(w) < 3 or w in _HOOK_STOPWORDS:
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") else w)   # therapies ~ therapie, doctors ~ doctor
    return out


def hook_overlap(title: str, hook: str) -> float:
    """Share of the hook's significant words that are also in the title."""
    h = _sig_words(hook)
    return len(h & _sig_words(title)) / len(h) if h else 0.0


# --- is the on-screen hook understood cold? ------------------------------------
# The hook is read in the first seconds, before a word is heard and without
# the title. "The quit room has no one in it." and "Your brain wakes up with
# one labeled folder." (JRE #2515) quote the speaker's image and mean nothing
# to someone who has not watched the clip. Plain word lists, no AI: a miss
# costs one retry (main.retry_unclear_hooks), never the clip.
HOOK_MAX_WORDS = 8
_NUMBER_WORDS = set("""two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen
sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred hundreds
thousand thousands million millions billion billions half double twice triple percent""".split())
# Someone / something the viewer has not met.
_HOOK_PRONOUNS = set("he she him her his hers they them their theirs".split())
# ...unless the hook itself says who, before the pronoun: "A DMT user asked
# if he was dead" is read cold; "He asked one question 39 times" is not.
# (JRE #2515, 1-oct-2026: two rewrites refused for a "he" / "his" whose
# person the hook had just named.)
_HOOK_PERSONS = set("""man men woman women guy guys girl girls boy boys kid kids child children baby teen
teenager person patient patients user users fighter boxer wrestler champion doctor surgeon nurse scientist
neuroscientist psychologist psychiatrist therapist comedian soldier veteran marine monk mother father mom dad
parent parents wife husband son daughter brother sister twin friend guest host stranger killer murderer victim
inmate prisoner cop officer detective pilot athlete runner climber student teacher professor worker ceo founder
billionaire millionaire addict alcoholic smoker survivor driver hunter farmer chef actor singer rapper
astronaut scientist writer author monk nun priest someone somebody""".split())
_HOOK_OPEN_PRONOUNS = _HOOK_PRONOUNS | set("it this that these those".split())
# Words that carry no picture: not what "a concrete noun" means.
_HOOK_WEAK = set("""thing things stuff way ways time times life world reality everything nothing something
anything truth lie lies secret secrets reason reasons moment moments part parts kind kinds people person nobody
everyone everybody someone somebody anyone chance fact facts idea ideas point real whole exact same single
ever never always forever before after again straight completely entire entirely literally simply exactly
gave give gives tell tells told talk talks said says want wants need needs take takes took come comes coming
came goes going gone went happen happens happened change changes changed know knows knew think thinks thought
look looks seem seems mean means keep keeps stop stops start starts watch wait believe expect expected realize
understand first last next only most more less best worst good great little long hard true""".split())
# The mind (or a life) as an object: images that need the clip to be understood.
_HOOK_FIGURATIVE = set("""room folder file door gate switch button wall cage prison trap monster demon ghost
storm ocean journey mask mirror puppet machine engine fuel battery software hardware reboot reset fractal
matrix simulation autopilot thermostat iceberg maze labyrinth rollercoaster volcano script rabbit""".split())


def _hook_words(hook: str) -> list:
    return [w.strip("'’-") for w in re.findall(r"[A-Za-zÀ-ÿ0-9$%'’-]+", (hook or "").lower()) if w.strip("'’-")]


def _singular(word: str) -> str:
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


def hook_problems(hook: str) -> list:
    """What keeps an on-screen hook from being understood cold ([] when
    nothing does, or when there is no hook)."""
    words = _hook_words(hook)
    if not words:
        return []
    out = []
    if len(words) > HOOK_MAX_WORDS:
        out.append(f"{len(words)} words (max {HOOK_MAX_WORDS})")
    if words[0] in _HOOK_OPEN_PRONOUNS:
        out.append(f"opens on '{words[0]}', which points at nothing the viewer has seen")
    else:
        k = next((i for i, w in enumerate(words) if w in _HOOK_PRONOUNS), None)
        if k is not None and not any(_singular(w) in _HOOK_PERSONS or w in _HOOK_PERSONS for w in words[:k]):
            out.append(f"'{words[k]}' is someone the viewer has not met")
    image = next((w for w in words if _singular(w) in _HOOK_FIGURATIVE), None)
    if image:
        out.append(f"an image ('{image}') instead of the thing itself")
    number = any(re.search(r"\d", w) or w in _NUMBER_WORDS for w in words)
    concrete = any(len(w) >= 4 and w not in _HOOK_STOPWORDS and w not in _HOOK_WEAK
                   and w not in _HOOK_OPEN_PRONOUNS and _singular(w) not in _HOOK_FIGURATIVE
                   for w in words)
    if not number and not concrete:
        out.append("no concrete noun or number")
    return out


# --- does the hook tell the ending? --------------------------------------------
# A hook teases the payoff, it never tells it: "A 6-to-1 underdog won the
# greatest fight ever" (a rewrite on JRE #2515) leaves nothing to watch for,
# and "The quit room has no one in it." is the clip's punchline word for word.
# Two plain tests: a verb that settles the story (past tense), or most of
# the hook's words already in the punchline (HOOK_SPOIL_MAX). Nouns such as
# "champion" or "winner" stay out: they name who is in the story, not how it
# ends ("Betting odds gave the champion no chance" teases).
_HOOK_OUTCOME = set("""won lost died survived defeated recovered cured healed escaped failed succeeded
retired""".split())
_HOOK_OUTCOME_PHRASES = ("ended up", "turned out", "turns out", "in the end", "wound up")
HOOK_SPOIL_MAX = 0.5


def hook_spoils(hook: str, punchline: str = "") -> str:
    """Why the hook tells the ending instead of teasing it ("" when it does
    not, or when there is no hook)."""
    text = (hook or "").lower()
    if not text.strip():
        return ""
    words = _hook_words(hook)
    verdict = next((w for w in words if w in _HOOK_OUTCOME), None)
    if verdict:
        return f"tells the ending ('{verdict}')"
    phrase = next((ph for ph in _HOOK_OUTCOME_PHRASES if ph in text), None)
    if phrase:
        return f"tells the ending ('{phrase}')"
    h, p = _sig_words(hook), _sig_words(punchline)
    shared = h & p
    if len(shared) >= 2 and len(shared) / len(h) >= HOOK_SPOIL_MAX:
        return "says the punchline"
    return ""


def hook_check_enabled() -> bool:
    """HOOK_CHECK=1 (profile: selection.hook_check): an unclear hook gets one
    rewrite by the model. The check itself always runs with the playbook."""
    return os.environ.get("HOOK_CHECK") == "1"


def check_hook(clip: dict) -> bool:
    """Sets clip['hook_repeats_title'] (the hook says the title again:
    HOOK_OVERLAP_MAX or more of its significant words),
    clip['hook_clear'] / clip['hook_problems'] (hook_problems) and
    clip['hook_spoils'] (hook_spoils, against clip['punchline']). Returns
    True when the hook repeats the title."""
    share = hook_overlap(clip.get("video_title_for_youtube_short"), clip.get("viral_hook_text"))
    clip["hook_repeats_title"] = share >= HOOK_OVERLAP_MAX
    clip["hook_title_overlap"] = round(share, 2)
    clip["hook_problems"] = hook_problems(clip.get("viral_hook_text"))
    clip["hook_clear"] = not clip["hook_problems"]
    clip["hook_spoils"] = hook_spoils(clip.get("viral_hook_text"), clip.get("punchline"))
    return clip["hook_repeats_title"]


_HOOK_REPEAT = "says the title again"
HOOK_REPEAT = _HOOK_REPEAT


def title_words(title: str) -> list:
    """The title's own words a rewritten hook must stay away from (main.retry_unclear_hooks, when the hook
    says the title again): its words of three letters or more that are not stopwords, in order."""
    out = []
    for w in _hook_words(title):
        if len(w) >= 3 and w not in _HOOK_STOPWORDS and w not in out:
            out.append(w)
    return out


def hook_issues(clip: dict) -> list:
    """Everything wrong with the clip's hook: check_hook's three verdicts
    (unclear, tells the ending, says the title again)."""
    repeats = check_hook(clip)
    return (clip["hook_problems"] + ([clip["hook_spoils"]] if clip["hook_spoils"] else [])
            + ([_HOOK_REPEAT] if repeats else []))


def _hook_rank(issues) -> tuple:
    """Lower is better. A hook that tells the ending comes last whatever
    else it does right: the clip has nothing left to show. Then clarity: a
    hook read without the title that says it again still tells the viewer
    what the clip is about; one that cannot be understood tells nothing."""
    spoils = any(i.startswith("tells the ending") or i == "says the punchline" for i in issues)
    return spoils, len([i for i in issues if i != _HOOK_REPEAT and not (i.startswith("tells the ending")
                                                                        or i == "says the punchline")]),         _HOOK_REPEAT in issues


def opening_sentences(clip: dict, transcript=None, n: int = 2, max_words: int = 60) -> str:
    """The first ``n`` sentences heard in the clip (what a rewritten hook
    must stay true to)."""
    start, end = float(clip.get("start", 0)), float(clip.get("end", 0))
    words, sentences = [], 0
    for seg in (transcript or {}).get("segments", []):
        for w in seg.get("words", []) or []:
            if w.get("start", 0) < start - 0.05:
                continue
            if w.get("start", 0) >= end or len(words) >= max_words:
                return " ".join(words)
            words.append(str(w.get("word", "")).strip())
            if re.search(r"[.!?…]$", words[-1]):
                sentences += 1
                if sentences >= n:
                    return " ".join(words)
    return " ".join(words)


HOOK_RETRY_PROMPT = """
You fix the on-screen hooks of short video clips. The hook is the big text a
viewer reads in the first 3 seconds, BEFORE hearing a word and WITHOUT reading
the title: it has to be understood cold, on its own.

For each clip below you get its title, the first sentences heard, the
punchline it closes on, its current hook and what is wrong with it. Write ONE
better hook per clip:
- max {max_words} words, in {language} (count them: one word over and the hook
  is thrown away);
- it names the concrete thing the clip is about (the substance, the organ, the
  illness, the number, the act) in plain words: someone who reads only these
  words knows the subject;
- no metaphor and no image that needs the clip to be understood ("The quit
  room has no one in it." and "One labeled folder." are wrong);
- no "he", "she", "they", "it" or "this" pointing at someone or something the
  viewer has not met — unless the hook itself says who, before it ("A DMT
  user asked if he was dead" is fine; "He asked if he was dead" is not);
- a statement, not a question. It adds a stake, a tension or a promise: it may
  share the subject with the title but never says the title again. When a clip
  lists "title_words_not_to_reuse", the hook is built from OTHER words (at most
  one of those): the hook and the title must say two different things;
- no name of a person or a show; never an explicit word for suicide or
  self-harm; a drug is shown from its risk, never as fun;
- it teases the payoff, it NEVER tells it: nothing from the punchline, no
  result, no verdict, no "won", "lost", "died", "survived", "turned out". The
  viewer must need the clip to learn how it ends ("A 6-to-1 underdog won the
  greatest fight ever" is wrong; "Nobody gave the underdog a chance" is right);
- true to the clip: nothing the opening does not support.

CLIPS_JSON:
{clips}

Return only: {{"hooks": [{{"id": <clip id>, "viral_hook_text": "<max {max_words} words>", "hook_accent": "<the one or two words of that hook carrying its payoff, copied verbatim>"}}]}}
"""

HOOK_RETRY_SCHEMA = {
    "type": "object",
    "properties": {"hooks": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "viral_hook_text": {"type": "string"},
                       "hook_accent": {"type": "string"}},
        "required": ["id", "viral_hook_text"]}}},
    "required": ["hooks"],
}


# The rewrite asks for one word fewer than the limit: on JRE #2515 sonnet
# answered "max 8" with 9-word hooks three times out of eight, each thrown
# away for that alone. Asked for 7 it lands on 7 or 8; the check stays at 8.
HOOK_RETRY_WORDS = HOOK_MAX_WORDS - 1


def hook_retry_prompt(items, language: str = "en") -> str:
    """``items``: [{"id", "title", "opening", "punchline", "hook", "problems"}]."""
    return HOOK_RETRY_PROMPT.format(max_words=HOOK_RETRY_WORDS, language=language or "en",
                                    clips=json.dumps(items, ensure_ascii=False, indent=1))


def apply_hook_retry(clip: dict, new_hook: str, accent=None) -> bool:
    """Take the rewritten hook when it is better than the current one
    (_hook_rank of their hook_issues); what happened is kept in
    clip['hook_check']. ``accent``: the payoff word(s) the model named for
    the new hook (hook_accent), kept with it. True when the hook changed."""
    old = (clip.get("viral_hook_text") or "").strip()
    before = hook_issues(clip)
    new_hook = re.sub(r"\s+", " ", str(new_hook or "")).strip()
    record = {"retried": True, "before": old, "issues_before": before}
    if not new_hook or new_hook == old:
        clip["hook_check"] = {**record, "kept": "no new hook"}
        return False
    trial = {"video_title_for_youtube_short": clip.get("video_title_for_youtube_short"),
             "viral_hook_text": new_hook, "punchline": clip.get("punchline")}
    after = hook_issues(trial)
    if _hook_rank(after) >= _hook_rank(before):
        clip["hook_check"] = {**record, "kept": "the new hook was no better", "rejected": new_hook,
                              "issues_rejected": after}
        return False
    clip["viral_hook_text"] = new_hook
    clip["hook_accent"] = re.sub(r"\s+", " ", str(accent or "")).strip()
    check_hook(clip)
    clip["hook_check"] = record
    return True


def moment_id(source_video: str, start, end) -> str:
    key = f"{episode_title(source_video)}|{float(start):.1f}|{float(end):.1f}"
    return "m_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def prepare(shorts, source_video, brief=None, show="", series_name="", spoken=None):
    """After selection, before rendering: credit line in both descriptions,
    moment id, bucket clean-up and a first name check. Returns the name
    tokens (the render re-checks the title once hook grounding had its say)."""
    credit = credit_line(source_video, brief, show, spoken)
    tokens = name_tokens(source_video, brief, show, (series_name,))
    for c in shorts:
        for k in ("video_description_for_tiktok", "video_description_for_instagram"):
            c[k] = with_credit(c.get(k), credit)
        c["moment_id"] = moment_id(source_video, c.get("start", 0), c.get("end", 0))
        if c.get("topic_bucket") not in TOPIC_BUCKETS:
            c["topic_bucket"] = "other"
        if c.get("moment_nature") not in MOMENT_NATURES:
            c["moment_nature"] = "other"
        if "opening_misses" in c:
            c["opening_misses"] = [m for m in c.get("opening_misses") or [] if m in OPENING_CRITERIA]
        if check_title(c, tokens):
            print(f"   ⚠️ Playbook: a name is in the title of the clip at {float(c.get('start', 0)):.0f}s "
                  f"({', '.join(c['title_names'])}): {c.get('video_title_for_youtube_short')}")
    assign_why_slots(shorts)
    for c in shorts:
        if not check_format(c):
            print(f"   ⚠️ Playbook: title format of the clip at {float(c.get('start', 0)):.0f}s "
                  f"({'; '.join(c['title_format_issues'])}): {c.get('video_title_for_youtube_short')}")
        if check_hook(c):
            print(f"   ⚠️ Playbook: the on-screen hook of the clip at {float(c.get('start', 0)):.0f}s repeats "
                  f"the title ({c['hook_title_overlap']:.0%} of its words): {c.get('viral_hook_text')}")
        if c.get("hook_problems"):
            print(f"   ⚠️ Playbook: the on-screen hook of the clip at {float(c.get('start', 0)):.0f}s is not "
                  f"clear on its own ({'; '.join(c['hook_problems'])}): {c.get('viral_hook_text')}")
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


def pause_before(clip: dict, transcript=None):
    """Seconds of silence between the last word before the clip and its
    first word (None without word timestamps): a line said after a pause is
    a line the speaker set up."""
    start = float(clip.get("start", 0))
    prev_end = None
    for seg in (transcript or {}).get("segments", []):
        for w in seg.get("words", []) or []:
            if w.get("start", 0) >= start - 0.05:
                return None if prev_end is None else round(max(0.0, w["start"] - prev_end), 2)
            prev_end = w.get("end", prev_end)
    return None


def broll_summary(clip: dict) -> list:
    """The clip's B-roll items, the fields the stats need (never the prompts)."""
    out = []
    for it in clip.get("broll") or []:
        if not isinstance(it, dict):
            continue
        out.append({k: it.get(k) for k in ("t", "dur", "layout", "subject", "style", "family", "score", "look_score",
                                           "art", "notion", "reused", "source") if it.get(k) is not None})
    return out


def export_clip(clip: dict, output_dir: str, clip_filename: str, tokens, transcript=None) -> str:
    """<clip>_playbook.json next to the clip: what the stats need later."""
    check_title(clip, tokens)
    check_format(clip)
    check_hook(clip)
    start, end = float(clip.get("start", 0)), float(clip.get("end", 0))
    data = {
        "moment_id": clip.get("moment_id"),
        "clip_file": clip_filename,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 2),
        "topic_bucket": clip.get("topic_bucket") or "other",
        # Threat to you / person at stake / your mind / debate (MOMENT_NATURES).
        "moment_nature": clip.get("moment_nature") if clip.get("moment_nature") in MOMENT_NATURES else "other",
        "hook_sentence": hook_sentence(clip, transcript),
        "hook_aligned": bool(clip.get("hook_aligned")),
        "pause_before": pause_before(clip, transcript),
        # No hook nor sentence start fitted the length band (main._playbook_start).
        "start_mid_sentence": bool(clip.get("start_mid_sentence")),
        # The end was moved earlier (onto a sentence end) to open on the hook.
        "end_moved_for_hook": bool(clip.get("end_fit_for_hook")),
        # Target length (main.trim_to_target): cut back after the payoff, or
        # why the clip stayed over the target ("" when it was not over).
        "end_moved_for_target": bool(clip.get("end_fit_for_target")),
        # The start was moved to a later sentence to land inside the target
        # (main.shorten_to_target); the hook it replaced, if it wrote one.
        "start_moved_for_target": bool(clip.get("start_fit_for_target")),
        "hook_before_open_later": clip.get("hook_before_open_later") or "",
        "over_target": clip.get("over_target") or "",
        # No full stop nor pause near the end (main.end_on_sentence).
        "end_mid_sentence": bool(clip.get("end_mid_sentence")),
        # The clip ends on its payoff (main.trim_to_target, 5-oct-2026), or why
        # the payoff is outside it ("" when it is in: main.land_payoff).
        "end_on_payoff": bool(clip.get("end_on_payoff")),
        "payoff_outside": clip.get("payoff_outside") or "",
        "title": clip.get("video_title_for_youtube_short") or "",
        "title_has_name": bool(clip.get("title_has_name")),
        "title_names": clip.get("title_names") or [],
        "title_format_ok": bool(clip.get("title_format_ok")),
        "title_format_issues": clip.get("title_format_issues") or [],
        "on_screen_hook": clip.get("viral_hook_text") or "",
        # The hook's payoff word(s) drawn in yellow, as the brain named them
        # (hooks.docline_accent falls back to a number or the last long word).
        "hook_accent": clip.get("hook_accent") or "",
        # The set check (title_set_problems): the title it replaced when the
        # model was asked again, or why the repeat stayed (apply_retitle).
        "title_before_retitle": (clip.get("title_check") or {}).get("before") or "",
        "title_repeats": (clip.get("title_check") or {}).get("issues_before") or [],
        "hook_repeats_title": bool(clip.get("hook_repeats_title")),
        "hook_title_overlap": clip.get("hook_title_overlap", 0.0),
        # Understood without the title nor the sound (hook_problems); the hook
        # it replaced when the model was asked again (apply_hook_retry).
        "hook_clear": bool(clip.get("hook_clear")),
        "hook_problems": clip.get("hook_problems") or [],
        "hook_before_retry": (clip.get("hook_check") or {}).get("before") or "",
        # The hook tells the ending (hook_spoils): "" when it teases.
        "hook_tells_ending": clip.get("hook_spoils") or "",
        # The B-roll pictures cut in (broll.add_broll): when, what, how the judge scored their meaning and
        # their look — for the views <-> B-roll stats.
        "broll": broll_summary(clip),
        "score": clip.get("predicted_score"),
        # The opening (5-oct-2026, main.rank_by_opening): the score above weighs the moment (moment_score, the
        # model's own) and its opening (opening_score, judged in the clip-choice call; opening_misses: which of
        # stands_alone / topic_named / tension it fails; opening_flags: what the code found in the final cut).
        "moment_score": clip.get("moment_score", clip.get("predicted_score")),
        "opening_score": clip.get("opening_score"),
        "opening_misses": [m for m in clip.get("opening_misses") or [] if m in OPENING_CRITERIA],
        "opening_flags": clip.get("opening_flags") or [],
        # 9-oct-2026 (recette « références »): the title style, the words naming the clip's thing and when they are
        # heard, the start moved for them (main.open_on_subject), the everyday thing and its weight.
        "title_style": title_style(),
        "subject_words": clip.get("subject_words") or "",
        "subject_said_at": clip.get("subject_said_at"),
        "opening_moved_for_subject": clip.get("opening_moved_for_subject") or None,
        "everyday_thing": clip.get("everyday_thing") or "",
        "everyday_bonus": clip.get("everyday_bonus") or 0,
        # A bigger channel posted this moment in the last 30 days (already_clipped.py; off by default).
        "already_clipped": clip.get("already_clipped") or None,
        # Outside the profile's niche_topics: the score above lost the niche
        # weight, score_raw is what the model gave (apply_niche).
        "off_niche": bool(clip.get("off_niche")),
        "score_raw": clip.get("predicted_score_raw", clip.get("predicted_score")),
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
    check_hook(clip)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.update({"title": clip.get("video_title_for_youtube_short") or "",
                 "title_has_name": bool(clip.get("title_has_name")),
                 "title_names": clip.get("title_names") or [],
                 "title_format_ok": bool(clip.get("title_format_ok")),
                 "title_format_issues": clip.get("title_format_issues") or [],
                 "on_screen_hook": clip.get("viral_hook_text") or "",
                 "hook_repeats_title": bool(clip.get("hook_repeats_title")),
                 "hook_title_overlap": clip.get("hook_title_overlap", 0.0),
                 "hook_clear": bool(clip.get("hook_clear")),
                 "hook_problems": clip.get("hook_problems") or []})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
