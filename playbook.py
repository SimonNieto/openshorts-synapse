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
        who = next((w for w in words if w in _HOOK_PRONOUNS), None)
        if who:
            out.append(f"'{who}' is someone the viewer has not met")
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
  viewer has not met;
- a statement, not a question. It adds a stake, a tension or a promise: it may
  share the subject with the title but never says the title again;
- no name of a person or a show; never an explicit word for suicide or
  self-harm; a drug is shown from its risk, never as fun;
- it teases the payoff, it NEVER tells it: nothing from the punchline, no
  result, no verdict, no "won", "lost", "died", "survived", "turned out". The
  viewer must need the clip to learn how it ends ("A 6-to-1 underdog won the
  greatest fight ever" is wrong; "Nobody gave the underdog a chance" is right);
- true to the clip: nothing the opening does not support.

CLIPS_JSON:
{clips}

Return only: {{"hooks": [{{"id": <clip id>, "viral_hook_text": "<max {max_words} words>"}}]}}
"""

HOOK_RETRY_SCHEMA = {
    "type": "object",
    "properties": {"hooks": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "viral_hook_text": {"type": "string"}},
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


def apply_hook_retry(clip: dict, new_hook: str) -> bool:
    """Take the rewritten hook when it is better than the current one
    (_hook_rank of their hook_issues); what happened is kept in
    clip['hook_check']. True when the hook changed."""
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
    check_hook(clip)
    clip["hook_check"] = record
    return True


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
        "over_target": clip.get("over_target") or "",
        # No full stop nor pause near the end (main.end_on_sentence).
        "end_mid_sentence": bool(clip.get("end_mid_sentence")),
        "title": clip.get("video_title_for_youtube_short") or "",
        "title_has_name": bool(clip.get("title_has_name")),
        "title_names": clip.get("title_names") or [],
        "title_format_ok": bool(clip.get("title_format_ok")),
        "title_format_issues": clip.get("title_format_issues") or [],
        "on_screen_hook": clip.get("viral_hook_text") or "",
        "hook_repeats_title": bool(clip.get("hook_repeats_title")),
        "hook_title_overlap": clip.get("hook_title_overlap", 0.0),
        # Understood without the title nor the sound (hook_problems); the hook
        # it replaced when the model was asked again (apply_hook_retry).
        "hook_clear": bool(clip.get("hook_clear")),
        "hook_problems": clip.get("hook_problems") or [],
        "hook_before_retry": (clip.get("hook_check") or {}).get("before") or "",
        # The hook tells the ending (hook_spoils): "" when it teases.
        "hook_tells_ending": clip.get("hook_spoils") or "",
        "score": clip.get("predicted_score"),
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
