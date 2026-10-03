"""B-roll v21 « idées » (4-oct-2026): a round of IDEAS in text, before any picture is made. For every moment the editor
placed (broll_spec), three Claude calls for the whole clip, each built on the channel's own text
(.claude/skills/synapse-cut/: the principles, and for the judges the calibration):

  1. the ART DIRECTOR (principles only): what the sentence means, whether the thing named is the point or the vehicle
     of the idea, then three ideas of different natures — or "no picture", which is a valid answer;
  2. the VERIFIER (principles + calibration): the checklist — pass / fix (the details rewritten) / refuse;
  3. the VIEWER (principles + calibration): hears the sentence, reads the subtitles, scores every idea, and ranks the
     face alone among them: an idea ranked under the face alone is dropped.

The code keeps the best idea of each moment (its fields become the moment's shot spec, so shot_prompt still writes the
image prompt, the subject first) and the second one as the alternative. The Claude Code agents of the same names serve
the bench only; here the skill's text goes into our own calls."""
import os
import re

import broll
import broll_spec

SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".claude", "skills", "synapse-cut")
IDEAS_PER_MOMENT = 3
ROLES = ("point", "vehicle")
STOPS = ("yes", "maybe", "no")
LINKS = ("yes", "blurry", "no")
VERDICTS = ("pass", "fix", "refuse")
FLAWS = ("none", "setting", "object", "figure", "symbol", "stock")
FACE = "face"                 # the viewer's level zero: the speaker's face alone, no picture
TIMEOUT = int(os.environ.get("BROLL_IDEAS_TIMEOUT") or 240)
LAST_IDEAS = []               # the last clip's round, for the bench's board and JSON


# --- the channel's text ---------------------------------------------------------------------------------------------
_FALLBACK = {
    "principes": ("The Synapse Cut: the wildest ideas from the world's biggest podcasts, in 60 seconds. The viewer scrolls "
                  "with the sound on, hears the voice, reads the subtitles, knows nothing of the episode. A picture stops "
                  "the thumb and amplifies the idea: it shows what the sentence MEANS, literal when the thing named is "
                  "the point, illustrative when it is only the vehicle of an idea; it adds an angle, an emotion or a "
                  "resemblance; it reads in two seconds; it stays true and respectful. Before impact: gravity (a death "
                  "told with dignity: an absence, never the means), safety (no drug taken or shown, the inside of a body "
                  "drawn), the facts (nothing invented, nothing to read), no real person. An experience is shown from "
                  "inside; a figure of speech has no literal picture; a scene holds by one or two true particular "
                  "details, never by a generic place."),
    "calibrage": ("What fails: the setting instead of the idea (an empty room nothing in the sentence asks for), the "
                  "object placed to tick the box, the figure of speech taken literally, the symbol, the stock photo."),
}
_CACHE = {}


def skill_text(part="principes"):
    """The channel's text as written in the skill: "principes" (SKILL.md without its front matter) or "calibrage"
    (calibrage.md). A missing file gives a short English fallback (and a warning once)."""
    if part in _CACHE:
        return _CACHE[part]
    path = os.path.join(SKILL_DIR, "SKILL.md" if part == "principes" else "calibrage.md")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if text.startswith("---"):
            text = text.split("---", 2)[2] if text.count("---") >= 2 else text
        text = text.strip()
    except OSError:
        print(f"   ⚠️ Ideas: {path} not found — a short fallback of the channel's {part} is used.")
        text = _FALLBACK[part]
    _CACHE[part] = text
    return text


# --- the prompts -------------------------------------------------------------------------------------------------------
DA_PROMPT = """You are the art director of the channel described below (its text is in French; answer in ENGLISH).

THE CHANNEL'S PRINCIPLES (read them first; everything you propose obeys them, and first of all "ce qui passe avant \
l'impact"):
{principes}

THE CLIP: title "{title}", hook "{hook}". Clip gravity: {gravity}{grave_line}
Never pictured: the speakers ({speakers}) and any real person of the story.
{brief}
THE MOMENTS. For each one, in order:
1. "idea": what the sentence MEANS, one line (not what it names).
2. "role": "point" when the thing named IS the point (take it away and the idea falls: the picture is literal, exact,
   at its true scale, in its true setting) or "vehicle" when the thing is only the vehicle of an idea (the picture
   shows what the sentence means: a concrete scene a camera could film, an angle, an emotion, a resemblance).
3. "ideas": up to {per} ideas of DIFFERENT natures (one literal, one that shows the idea by a concrete scene, one that
   plays an angle or a resemblance) — three variants of one scene do not count. An EMPTY list means "no picture": a
   valid answer when no concrete picture carries the idea; say why in "no_picture_why". Each idea:
   - "title" (6 words at most);
   - "picture": the picture in plain words, 45 at most: ONE instant, concrete, what a camera could film — or, for the
     inside of a body, what the episode's drawing shows; for an experience, what the person perceives;
   - "adds": what it adds that the subtitles do not say (an angle, an emotion, a resemblance);
   - "reads": what a viewer who knows nothing understands in two seconds, subtitles on screen;
   - the RENDER FIELDS the code turns into the image prompt (plain nouns and adjectives a camera records; no style
     word, no metaphor, no negation): "kind" (thing / scene / vision = what a person perceives, people none /
     instrument = what a microscope, telescope or scanner shows / body_inside = organs, tissue, a brain, an operation,
     always drawn / pair = two named things side by side, "subject_b"), "subject" (what fills the frame, 8 words),
     "count" ("1".."4" or "many"), "state" (what it does at that instant, 10 words), "setting" (where, 10 words, or
     "plain"), "details" (2-3 visible particular details that make it THIS thing, 20 words), "people" (none / hands /
     one / group), "person" (none / anonymous — never a real one), "shot" (wide / medium / close / macro),
     "light" (the light in concrete words: time of day, direction, source, 12 words at most — calm and everyday for
     an inner or an empty picture, never the dark of a horror film), "instrument" (instrument only, 5 words);
     for a PAIR the two halves are made separately and put side by side by the code: "kind_a" (the left thing's
     own kind: thing / scene / instrument / body_inside) and "kind_b" (the right one's), "details_b" (the right
     thing's 2-3 visible details, 20 words), "subject_b" (the right thing, 8 words);
     "hero_ok": true when this picture could fill the whole phone screen for three seconds (a real scene with
     depth, a drawing or a vision that fills the frame edge to edge), false for a small thing, a pair or a flat
     detail. "instrument" is for a KNOWN kind of image (a scan, a telescope frame, a fluorescence micrograph of
     whole cells); the chemistry at a synapse (receptors, vesicles, dopamine, molecules) is never an instrument's
     image: it is drawn (body_inside) or the idea is shown another way.
   - "anchor": optional, 1-3 consecutive spoken words of the sentence (or the next one) where the picture should land
     instead, when the idea belongs to those words.
Keep every precise fact said (a number, a colour, a place, an era); invent none. Vary the subjects across the clip:
already planned elsewhere in the clip: {planned}.
THE RENDER FIELDS ARE DRAWN LITERALLY by the engine: never a comparison in them ("almond-shaped" gives a real almond,
"ribbon of cortex" a real ribbon, "eyeshades" sunglasses) — name the thing itself; never a screen, a display, a
label, a page, a sign or a chart (they come out with writing); a scene shows its things, never a number of them
above four.
{moments}
Return JSON: {{"moments": [{{"k": 0, "idea": "...", "role": "point", "ideas": [...], "no_picture_why": ""}}]}}"""

VERIFIER_PROMPT = """You are the verifier of the channel described below (its text is in French; answer in ENGLISH).
You are strict and literal: a doubt is flagged, never forgiven. The channel's principles decide; the calibration tells
you what fails and why.

THE CHANNEL'S PRINCIPLES:
{principes}

THE CALIBRATION:
{calibrage}

THE CLIP: title "{title}", hook "{hook}". Clip gravity: {gravity} ("grave" = a death is the clip's subject: every
picture is an absence, nobody in the frame, never the means; "real" = a death, an illness or a loss is mentioned).
Speakers, never pictured: {speakers}. {brief}
THE CHECKLIST, for every idea: no real person (an anonymous stranger passes); nothing that evokes a death or its means,
even as a visual cliché; an absence when the clip is grave; an experience shown from inside (what is perceived, never
the person who perceives it); no figure of speech taken literally; the facts said kept and none invented; no drug
taken, prepared or shown itself; the inside of a body drawn, never photographed; nothing to read in the picture; no
gore. A sentence flagged "mentions a death" may have a picture, but nothing in it may evoke that death. In a grave clip
refuse any belt, strap, tie, scarf, cord, cable, tube, lace or stethoscope shown hanging, draped or looped (the
silhouette of a hanged body), and any garment with something hanging from it.
For every idea answer: "verdict": "pass" / "fix" (a precise correction makes it pass: give "details" rewritten in the
positive, 20 words at most, the only field you change) / "refuse"; "reason" (12 words at most); "flaw": the
calibration's flaw you recognise, "none" / "setting" (the setting instead of the idea) / "object" (the object placed
to tick the box) / "figure" / "symbol" / "stock" — a flaw is information for the viewer, not a refusal.
{moments}
Return JSON: {{"moments": [{{"k": 0, "ideas": [{{"i": 0, "verdict": "pass", "reason": "", "details": "", "flaw": "none"}}]}}]}}"""

VIEWER_PROMPT = """You are the viewer of the channel described below (its text is in French; answer in ENGLISH).
You scroll Shorts with the sound on: you HEAR the voice and READ the subtitles. You know NOTHING of the episode, the
context or the team's intentions: only the words and the picture count. The calibration tells you the level a picture
must reach; you look for its force, never for a copy of it.

THE CHANNEL'S PRINCIPLES:
{principes}

THE CALIBRATION:
{calibrage}

For each sentence you get the subtitle you read while the picture is on screen, what you heard just before, and the
pictures proposed (described). The level zero is the FACE ALONE: the speaker's face, no picture. For every picture:
"stops" (yes / maybe / no: does your thumb stop), "feels" (what it does to you, 8 words), "link" (yes / blurry / no:
do you get the link with these words in your ear, in two seconds), "adds" (what it tells you that the words did not,
8 words, or "nothing"), "score" 1-5 (5 = you smile, you understand more than you were told; 1 = no link, or a stock
photo), "flaw" (the calibration's flaw you recognise, or "none"), "unease" (what feels false, disrespectful or
ridiculous, or ""). Then "order": the ids of the pictures best first, with "{face}" placed where the face alone
stands — every picture after "{face}" is worse than no picture.
{moments}
Return JSON: {{"moments": [{{"k": 0, "views": [{{"i": 0, "stops": "yes", "feels": "", "link": "yes", "adds": "", \
"score": 3, "flaw": "none", "unease": ""}}], "order": ["0", "{face}", "1"]}}]}}"""

_IDEA_FIELDS = ("kind", "subject", "subject_b", "instrument", "count", "state", "setting", "details", "people",
                "person", "shot", "light")
PAIR_KINDS = ("thing", "scene", "instrument", "body_inside")     # a half of a pair has its own kind
_STR = {"type": "string"}
_IDEA_SCHEMA = {"type": "object", "properties": {
    "title": _STR, "picture": _STR, "adds": _STR, "reads": _STR, "anchor": _STR,
    "kind": {"type": "string", "enum": list(broll_spec.KINDS)}, "subject": _STR, "subject_b": _STR, "instrument": _STR,
    "kind_a": {"type": "string", "enum": list(PAIR_KINDS)}, "kind_b": {"type": "string", "enum": list(PAIR_KINDS)},
    "details_b": _STR, "hero_ok": {"type": "boolean"},
    "count": {"type": "string", "enum": list(broll_spec.COUNTS)}, "state": _STR, "setting": _STR, "details": _STR,
    "people": {"type": "string", "enum": list(broll_spec.PEOPLE)},
    "person": {"type": "string", "enum": ["none", "anonymous"]},
    "shot": {"type": "string", "enum": list(broll_spec.SHOTS)}, "light": _STR},
    "required": ["title", "picture", "adds", "reads", "kind", "subject", "count", "state", "setting", "details",
                 "people", "person", "shot", "light"]}
DA_SCHEMA = {"type": "object", "properties": {"moments": {"type": "array", "items": {
    "type": "object", "properties": {
        "k": {"type": "integer"}, "idea": _STR, "role": {"type": "string", "enum": list(ROLES)},
        "ideas": {"type": "array", "items": _IDEA_SCHEMA}, "no_picture_why": _STR},
    "required": ["k", "idea", "role", "ideas"]}}}, "required": ["moments"]}
VERIFIER_SCHEMA = {"type": "object", "properties": {"moments": {"type": "array", "items": {
    "type": "object", "properties": {"k": {"type": "integer"}, "ideas": {"type": "array", "items": {
        "type": "object", "properties": {
            "i": {"type": "integer"}, "verdict": {"type": "string", "enum": list(VERDICTS)}, "reason": _STR,
            "details": _STR, "flaw": {"type": "string", "enum": list(FLAWS)}},
        "required": ["i", "verdict", "reason", "flaw"]}}},
    "required": ["k", "ideas"]}}}, "required": ["moments"]}
VIEWER_SCHEMA = {"type": "object", "properties": {"moments": {"type": "array", "items": {
    "type": "object", "properties": {"k": {"type": "integer"}, "views": {"type": "array", "items": {
        "type": "object", "properties": {
            "i": {"type": "integer"}, "stops": {"type": "string", "enum": list(STOPS)}, "feels": _STR,
            "link": {"type": "string", "enum": list(LINKS)}, "adds": _STR,
            "score": {"type": "integer", "minimum": 1, "maximum": 5},
            "flaw": {"type": "string", "enum": list(FLAWS)}, "unease": _STR},
        "required": ["i", "stops", "feels", "link", "adds", "score", "flaw"]}},
        "order": {"type": "array", "items": _STR}},
    "required": ["k", "views", "order"]}}}, "required": ["moments"]}


# --- the clip's words around a moment --------------------------------------------------------------------------------
def _sentences(words):
    """[(start, end, text)] of the clip's sentences (split on . ? ! or a 7 s stretch)."""
    out, cur, t0 = [], [], None
    for w in words:
        if t0 is None:
            t0 = float(w["start"])
        cur.append(w["text"])
        if w["text"].rstrip().endswith((".", "?", "!")) or float(w["end"]) - t0 > 7:
            out.append((t0, float(w["end"]), " ".join(cur)))
            cur, t0 = [], None
    if cur:
        out.append((t0, float(words[-1]["end"]), " ".join(cur)))
    return out


def _around(words, t):
    """(the sentence spoken at ``t``, the one before, the one after)."""
    sents = _sentences(words)
    for i, (a, b, text) in enumerate(sents):
        if a <= t <= b or (i + 1 < len(sents) and t < sents[i + 1][0]):
            return text, (sents[i - 1][2] if i > 0 else ""), (sents[i + 1][2] if i + 1 < len(sents) else "")
    return (sents[-1][2] if sents else ""), "", ""


def _q(text, n=40):
    return re.sub(r"\s+", " ", str(text or "")).replace('"', "'").strip()[: n * 7]


# --- the three calls ---------------------------------------------------------------------------------------------------
def _model(stage, default):
    return (os.environ.get(f"BRAIN_{stage.upper()}") or default).lower()


def _call(prompt, schema, stage, model, effort=None, timeout=TIMEOUT):
    """One claude_json call; a model other than sonnet that fails or times out is tried once more on sonnet."""
    try:
        return broll.claude_json(prompt, schema, timeout=timeout, stage=stage, model=model, effort=effort) or {}
    except Exception as e:
        if model == "sonnet":
            raise
        print(f"   ⚠️ {stage} on {model} failed ({str(e)[:100]}) — sonnet instead.")
        return broll.claude_json(prompt, schema, timeout=timeout, stage=stage, model="sonnet") or {}


def _moment_lines(moments, words):
    lines = []
    for k, m in enumerate(moments):
        spec = m.get("spec") or {}
        said, before, after = _around(words, float(m["t"]))
        flags = [f for f in broll_spec.FLAGS if spec.get(f)]
        extra = ""
        if spec.get("death_near"):
            extra += " [mentions a death: nothing may evoke it]"
        if spec.get("substance") or spec.get("intake"):
            extra += " [a drug or an intake is involved: never shown]"
        if spec.get("kind") == "vision":
            extra += " [an experience: what is perceived]"
        if spec.get("kind") == "body_inside":
            extra += " [the inside of a body: drawn]"
        lines.append(f'MOMENT k={k} at {float(m["t"]):.1f} s' + (" (full-screen hero)" if m.get("hero") else "")
                     + f', the thing named: "{_q(spec.get("subject"), 8)}"{extra}\n'
                     f'  before: "{_q(before)}"\n  SAID: "{_q(said or m.get("said"))}"\n  after: "{_q(after)}"')
    return "\n".join(lines)


def _idea_lines(moments, words, ideas, viewer=False):
    lines = []
    for k, m in enumerate(moments):
        said, before, _after = _around(words, float(m["t"]))
        head = (f'SENTENCE k={k}: subtitle "{_q(said or m.get("said"))}"; heard just before: "{_q(before)}"' if viewer
                else f'MOMENT k={k}: before "{_q(before)}" / SAID "{_q(said or m.get("said"))}"')
        body = [f'  [{i}] {_q(idea.get("picture"), 50)}' + ("" if viewer else
                f' (kind {idea.get("kind")}, people {idea.get("people")}, light: {_q(idea.get("light"), 12)})')
                for i, idea in enumerate(ideas.get(k) or []) if idea]
        if not body:
            continue
        lines.append(head + "\n" + "\n".join(body))
    return "\n".join(lines)


def _clip_lines(clip, gravity):
    import ai_brain
    speakers = ", ".join(sorted(broll._speaker_words())) or "the hosts"
    brief = ai_brain.EPISODE_BRIEF or {}
    notions = brief.get("glossary") if isinstance(brief, dict) else None
    brief_line = ""
    if isinstance(notions, list) and notions:
        names = [str(n.get("name") or n.get("term") or "") for n in notions if isinstance(n, dict)][:12]
        brief_line = "The episode's notions: " + ", ".join(x for x in names if x) + "."
    grave_line = (" — a death is the clip's SUBJECT: every picture is an absence (what remains of the person's life, "
                  "nobody in the frame), never the means; nothing hangs from a rope, a cord or a thread, and NO belt, "
                  "strap, tie, scarf, cord, cable, tube, lace or stethoscope anywhere in the picture (the engine lets "
                  "them hang, and a hanging strap is a hanged body); a garment on a wall hook or a hanger, with nothing "
                  "hanging from it, is fine." if gravity == "grave" else "")
    return dict(title=_q(clip.get("video_title_for_youtube_short"), 20), hook=_q(clip.get("viral_hook_text"), 20),
                gravity=gravity, grave_line=grave_line, speakers=speakers, brief=brief_line)


def _direct(moments, words, clip, gravity):
    """The art director's call -> {k: {"idea", "role", "ideas": [...], "why": ""}}."""
    planned = ", ".join(_q((m.get("spec") or {}).get("subject"), 6) for m in moments) or "-"
    prompt = DA_PROMPT.format(principes=skill_text("principes"), per=IDEAS_PER_MOMENT, planned=planned,
                              moments=_moment_lines(moments, words), **_clip_lines(clip, gravity))
    data = _call(prompt, DA_SCHEMA, "broll_ideas", _model("broll_ideas", "opus"),
                 effort=os.environ.get("CLAUDE_EFFORT_BROLL_IDEAS") or "high")
    out = {}
    for mm in data.get("moments") or []:
        if isinstance(mm, dict) and isinstance(mm.get("k"), int):
            ideas = [i for i in (mm.get("ideas") or []) if isinstance(i, dict)][:IDEAS_PER_MOMENT]
            out[mm["k"]] = {"idea": _q(mm.get("idea"), 30), "role": mm.get("role") if mm.get("role") in ROLES else "point",
                            "ideas": ideas, "why": _q(mm.get("no_picture_why"), 20)}
    return out


def _verify(moments, words, clip, gravity, ideas):
    """The verifier's call -> {(k, i): {"verdict", "reason", "details", "flaw"}}."""
    prompt = VERIFIER_PROMPT.format(principes=skill_text("principes"), calibrage=skill_text("calibrage"),
                                    moments=_idea_lines(moments, words, ideas), **_clip_lines(clip, gravity))
    data = _call(prompt, VERIFIER_SCHEMA, "broll_verify", _model("broll_verify", "sonnet"), effort="medium")
    out = {}
    for mm in data.get("moments") or []:
        if not (isinstance(mm, dict) and isinstance(mm.get("k"), int)):
            continue
        for v in mm.get("ideas") or []:
            if isinstance(v, dict) and isinstance(v.get("i"), int):
                out[(mm["k"], v["i"])] = {"verdict": v.get("verdict") if v.get("verdict") in VERDICTS else "pass",
                                          "reason": _q(v.get("reason"), 14), "details": _q(v.get("details"), 20),
                                          "flaw": v.get("flaw") if v.get("flaw") in FLAWS else "none"}
    return out


def _view(moments, words, clip, gravity, ideas):
    """The viewer's call -> {k: {"views": {i: {...}}, "order": [ids, FACE among them]}}."""
    prompt = VIEWER_PROMPT.format(principes=skill_text("principes"), calibrage=skill_text("calibrage"), face=FACE,
                                  moments=_idea_lines(moments, words, ideas, viewer=True), **_clip_lines(clip, gravity))
    data = _call(prompt, VIEWER_SCHEMA, "broll_viewer", _model("broll_viewer", "sonnet"), effort="medium")
    out = {}
    for mm in data.get("moments") or []:
        if not (isinstance(mm, dict) and isinstance(mm.get("k"), int)):
            continue
        views = {v["i"]: {"stops": v.get("stops"), "feels": _q(v.get("feels"), 10), "link": v.get("link"),
                          "adds": _q(v.get("adds"), 10), "score": int(v.get("score") or 0),
                          "flaw": v.get("flaw") if v.get("flaw") in FLAWS else "none", "unease": _q(v.get("unease"), 14)}
                 for v in mm.get("views") or [] if isinstance(v, dict) and isinstance(v.get("i"), int)}
        out[mm["k"]] = {"views": views, "order": [str(x) for x in (mm.get("order") or [])]}
    return out


# --- applying the round --------------------------------------------------------------------------------------------
# The inside of a body named in a picture's words: it is drawn whatever kind the director declared (a skinned arm with
# its muscles came out as a photograph, the house never shows that). Core anatomy only: "cell", "heart" or "bone"
# alone are too often something else (a prison cell, the heart of a city).
_BODY_RE = re.compile(r"\b(muscles?|tendons?|nerves?|nerve fib\w+|organs?|tissues?|brains?|neurons?|synapses?|"
                      r"synaptic|arter(?:y|ies)|veins?|intestines?|lungs?|skull|cortex|spinal cord|blood vessels?|"
                      r"receptors?|vesicles?|neurotransmitters?|dopamine|serotonin|molecules?)\b", re.I)
_HANG_RE = re.compile(r"\b(hanging|hangs|hung|suspended|dangling|dangles|loose|loosened|cord|cords|rope|ropes|"
                      r"string|strings|thread|threads|strap|straps|loop|loops|looped|noose)\b", re.I)
# A strap-like thing in a clip about a death is refused outright (third bench: a taekwondo belt "coiled on a wall
# hook" came out hanging from the hook like a strap, in the clip "He took his own life"; a stethoscope tube around a
# collar reads the same way). The engine cannot be trusted to keep it flat.
_STRAP_RE = re.compile(r"\b(belts?|straps?|ties?|neckties?|scar(?:f|ves)|cords?|ropes?|cables?|tubes?|hoses?|"
                       r"leash(?:es)?|chains?|lanyards?|necklaces?|stethoscopes?|laces)\b", re.I)


def _spec_of(m, idea, clip_text, gravity):
    """The moment's spec with the idea's render fields -> (spec, "") or (None, why): the code's own check of the idea
    (a real person, a drug near a death...), the kind's consistency, the caps. Two nets of the house: the inside of a
    body named in the words is drawn (kind body_inside) whatever the director declared; in a clip about a death, or on
    a sentence that mentions one, nothing "hangs" (the engine hung a whole dobok from a thread)."""
    base = {k: v for k, v in (m.get("spec") or {}).items() if k != "alt"}
    raw = {**base, **{k: idea.get(k) for k in _IDEA_FIELDS if idea.get(k) not in (None, "")}, "literal": "literal"}
    s = broll_spec._clean_fields(raw, gravity)
    why = broll_spec._check(s, raw, clip_text, gravity, alt=True, ideas=True)
    if why:
        return None, why
    s["light"] = broll_spec._cap(idea.get("light"), 12)
    s["subject_words"] = base.get("subject_words") or ""
    s["hero_ok"] = idea.get("hero_ok") is True
    if s["kind"] in ("thing", "scene", "vision", "instrument") and _BODY_RE.search(
            " ".join((s.get("subject") or "", s.get("details") or "", s.get("state") or ""))):
        s["kind"], s["people"], s["person"], s["instrument"] = "body_inside", "none", "none", ""
    if gravity == "grave" or s.get("death_near"):
        strap_text = " ".join([s.get("subject") or "", s.get("state") or "", s.get("details") or "",
                               str(idea.get("subject_b") or ""), str(idea.get("details_b") or "")])
        if _STRAP_RE.search(strap_text):
            return None, "a strap-like thing in a clip about a death"
        for k in ("subject", "state", "details", "setting"):
            s[k] = re.sub(r"\s{2,}", " ", _HANG_RE.sub("", s.get(k) or "")).strip(" ,")
    if s["kind"] == "pair":
        # the two halves are made one by one (broll_v20._make): each with its own kind and details
        for k in ("kind_a", "kind_b"):
            s[k] = idea.get(k) if idea.get(k) in PAIR_KINDS else "thing"
        s["details_b"] = broll_spec._cap(idea.get("details_b"), 20)
    return {**base, **s}, ""


MIN_SCORE = 3                 # a viewer's score under this ("no link, or a stock photo") counts as under the face alone
FLAW_SCORE = 5                # an idea the verifier flags as the setting / an object placed / stock passes only at this
_WEAK_FLAWS = ("setting", "object", "stock")
HERO_MIN = 4                  # the viewer's score an idea needs to fill the whole screen


def _above_face(order, ids, views=None, flaws=None):
    """The idea ids ranked before the face alone, in order (ids not listed come after it); an idea scored under
    MIN_SCORE by the viewer counts as under the face whatever its rank, and so does an idea the verifier flagged as the
    setting instead of the idea, an object placed or a stock photo, unless the viewer gave it FLAW_SCORE (the judges
    of the text were kinder to a therapy room than the viewer of the picture)."""
    seen, out = set(), []
    for x in order:
        if x == FACE:
            break
        if x not in ids or x in seen:
            continue
        score = int(((views or {}).get(int(x)) or {}).get("score") or MIN_SCORE)
        if score < MIN_SCORE or ((flaws or {}).get(int(x)) in _WEAK_FLAWS and score < FLAW_SCORE):
            continue
        out.append(x)
        seen.add(x)
    return out


def _pick_hero(moments, specs_of, words, avoid, head, block):
    """The one moment shown full screen, chosen among the IDEAS kept (v21): the director says the idea can fill the
    screen (hero_ok), the viewer gave it HERO_MIN or more, the timing rules pass (broll.hero_fits); the viewer's score
    decides, the editor's own hero mark and the second half of the clip as bonuses. None: cards only."""
    duration = float(words[-1]["end"]) if words else 0.0
    best, best_score = None, 0.0
    for i, m in enumerate(moments):
        spec, score = specs_of(i)
        if not spec or not spec.get("hero_ok") or score < HERO_MIN or m.get("notion"):
            continue
        if not broll.hero_fits(m, duration, avoid, head, block):
            continue
        total = score + (1.0 if m.get("hero") else 0.0) + (0.5 if float(m["t"]) > duration * 0.35 else 0.0)
        if best is None or total > best_score:
            best, best_score = i, total
    return best


def idea_round(moments, reserves, clip, words, gravity, clip_text, avoid=(), head=0.0, block=()):
    """The round for a clip's moments and reserves -> (moments, reserves) with their specs replaced by the chosen idea's
    fields (the second idea above the face alone as "alt"); a moment with no idea left is dropped (filter hits). The
    hero is then chosen among the ideas kept (_pick_hero; ``avoid``, ``head``, ``block``: the timing rules).
    LAST_IDEAS keeps the whole round for the bench."""
    del LAST_IDEAS[:]
    everything = list(moments) + list(reserves)
    if not everything:
        return moments, reserves
    directed = _direct(everything, words, clip, gravity)
    ideas = {k: directed.get(k, {}).get("ideas") or [] for k in range(len(everything))}
    # the code's own check first: a refused idea never reaches the judges
    specs = {}
    for k, m in enumerate(everything):
        kept = []
        for i, idea in enumerate(ideas[k]):
            spec, why = _spec_of(m, idea, clip_text, gravity)
            if spec:
                specs[(k, i)] = spec
                kept.append(idea)
            else:
                broll.filter_hit(f"ideas: {why}", f'Idea "{_q(idea.get("title"), 6)}" of "{m.get("anchor")}" refused by '
                                                  f'the code: {why}.')
                kept.append(None)
        ideas[k] = kept
    verdicts = _verify(everything, words, clip, gravity, ideas) if any(any(ideas[k]) for k in ideas) else {}
    for (k, i), v in verdicts.items():
        if i >= len(ideas.get(k) or []) or ideas[k][i] is None:
            continue
        if v["verdict"] == "refuse":
            broll.filter_hit("ideas: refused by the verifier", f'Idea "{_q(ideas[k][i].get("title"), 6)}" of '
                                                              f'"{everything[k].get("anchor")}": {v["reason"]}.')
            ideas[k][i] = None
        elif v["verdict"] == "fix" and v["details"]:
            specs[(k, i)]["details"] = v["details"]
            broll.filter_hit("ideas: fixed by the verifier (fixed)", f'Idea "{_q(ideas[k][i].get("title"), 6)}": '
                                                                    f'{v["reason"]} — details rewritten.')
    views = _view(everything, words, clip, gravity, ideas) if any(any(ideas[k]) for k in ideas) else {}
    out_moments, out_reserves = [], []
    for k, m in enumerate(everything):
        d = directed.get(k) or {}
        live = [str(i) for i, idea in enumerate(ideas[k]) if idea]
        v = views.get(k) or {}
        flaws = {i: (verdicts.get((k, i)) or {}).get("flaw") for i in range(len(ideas[k]))}
        order = _above_face(v.get("order") or live, live, v.get("views"), flaws) if v else live
        record = {"k": k, "anchor": m.get("anchor"), "t": m.get("t"), "said": m.get("said"), "idea": d.get("idea"),
                  "role": d.get("role"), "why": d.get("why"), "hero": bool(m.get("hero")),
                  "reserve": k >= len(moments), "ideas": [], "chosen": None}
        for i, idea in enumerate(directed.get(k, {}).get("ideas") or []):
            vv = (v.get("views") or {}).get(i) or {}
            vd = verdicts.get((k, i)) or {}
            record["ideas"].append({"i": i, "title": idea.get("title"), "picture": idea.get("picture"),
                                    "adds": idea.get("adds"), "verdict": vd.get("verdict") or ("refused by the code"
                                                                                               if ideas[k][i] is None and not vd else "pass"),
                                    "reason": vd.get("reason"), "flaw": vd.get("flaw"), "score": vv.get("score"),
                                    "stops": vv.get("stops"), "link": vv.get("link"), "feels": vv.get("feels"),
                                    "viewer_adds": vv.get("adds"), "unease": vv.get("unease"),
                                    "above_face": str(i) in order})
        if not d.get("ideas") and not (directed.get(k) is None):
            broll.filter_hit("ideas: no picture (the director)", f'Moment "{m.get("anchor")}": no picture — {d.get("why") or "-"}.')
        elif not order:
            broll.filter_hit("ideas: no idea above the face alone", f'Moment "{m.get("anchor")}": '
                             + ("every idea refused" if not live else "the viewer ranks the face alone above every idea") + ".")
        if order:
            i0 = int(order[0])
            spec = specs[(k, i0)]
            if len(order) > 1:
                alt = specs[(k, int(order[1]))]
                spec["alt"] = {kk: alt.get(kk) for kk in broll_spec.ALT_FIELDS + ("light",)}
            else:
                spec.pop("alt", None)
            idea = ideas[k][i0]
            m2 = {**m, "spec": spec, "idea_text": d.get("idea"), "role": d.get("role"), "picture": idea.get("picture")}
            # the idea may land on other words of the sentence (or the next): the anchor moves there
            if idea.get("anchor"):
                probe = {"anchor": _q(idea["anchor"], 3), "time": float(m["t"]), "subject_words": ""}
                if broll_spec._on_words(probe, words, [], 0.0, ()) != "lost" and abs(probe["time"] - float(m["t"])) <= 8.0:
                    m2["t"], m2["anchor"] = probe["time"], probe["anchor"]
            m2.update(query=spec.get("subject"), subject=spec.get("subject"), people=spec.get("people"),
                      inside_body=spec.get("kind") == "body_inside", viewer_score=(v.get("views") or {}).get(i0, {}).get("score"))
            record["chosen"] = i0
            (out_reserves if k >= len(moments) else out_moments).append(m2)
        LAST_IDEAS.append(record)
    # The hero, among the ideas kept: the editor's mark is a bonus, no longer the condition.
    k_hero = _pick_hero(out_moments, lambda i: (out_moments[i]["spec"], int(out_moments[i].get("viewer_score") or 0)),
                        words, avoid, head, block)
    for i, m in enumerate(out_moments):
        m["hero"] = i == k_hero
    for m in out_reserves:
        m["hero"] = False
    if k_hero is None and out_moments:
        broll.filter_hit("ideas: no hero", "No idea kept can fill the whole screen (hero_ok, viewer 4 or more, the timing) — cards only.")
    print("   💡 Ideas: " + " | ".join(
        f'{r["anchor"]}: ' + (f'#{r["chosen"]} "{_q((r["ideas"][r["chosen"]] or {}).get("title"), 6)}"'
                              f' ({(r["ideas"][r["chosen"]] or {}).get("score") or "-"}/5)' if r["chosen"] is not None
                              else "no picture") for r in LAST_IDEAS if not r["reserve"]))
    return out_moments, out_reserves
