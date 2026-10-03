"""B-roll v20 « la fiche » (3-oct-2026): the editor's side. One Claude call lists the clip's candidate pictures, each
as a SHOT SPEC (output/_test_broll/v20_contract.md §1); the code checks every spec (validate) and places it on the
clip's words with broll's own timing rules (plan_specs). The image prompt is written later, by code, from the
fields (shot_prompt) — the editor never writes one."""
import os
import re

import broll
import visual_mood

KINDS = ("thing", "scene", "vision", "instrument", "body_inside", "pair")
LITERAL = ("literal", "figure", "denied")
COUNTS = ("1", "2", "3", "4", "many")
PEOPLE = ("none", "hands", "one", "group")
PERSON = ("none", "anonymous", "real")
SHOTS = ("wide", "medium", "close", "macro")
GRAVITY = ("none", "real", "grave")
FLAGS = ("death_near", "substance", "intake")
# word caps of the free-text fields (the contract's table)
CAPS = {"said": 25, "subject": 8, "subject_b": 8, "instrument": 5, "state": 10, "setting": 10, "details": 20}
# the fields an alternative spec has: everything but where it lands and what it is worth
ALT_FIELDS = ("literal", "kind", "subject", "subject_words", "subject_b", "instrument", "count", "state", "setting",
              "details", "people", "person", "shot", "death_near", "substance", "intake", "mood")
_TAG = "spec#"     # carried through broll._parse_moments in its "idea" field, to find each spec again
# The bench of 3-oct (v20b) asked n + CANDIDATES_MORE and got 2-6 specs a clip, 1-3 placed: too few to keep two
# pictures once the check drops some. The editor now lists every concrete thing named, up to this many more.
CANDIDATES_EXTRA = 3
UNNAMED_COST = 2       # worth taken from a spec whose subject holds none of the words that name it (an invented stand-in)
RELOCATE_MAX = 8.0     # s an anchor may move to another mention of its words, to land in the allowed window
# A sight made only of these is no vision (a colour field, a glare, a blur): no viewer links it to what is said.
_ABSTRACT_SIGHT = {"colour", "color", "hue", "tone", "light", "glare", "glow", "flash", "blur", "haze", "texture",
                   "surface", "field", "pattern", "shape", "geometry", "void", "darkness", "brightness", "swirl",
                   "shadow", "frame", "focus", "fractal"}
# a spec dropped for one of these reasons may hand its place to its alternative (they are the picture's, not the words')
_PICTURE_FAULTS = ("no subject", "subject words not said in the clip", "a speaker of the video", "a real person",
                   "a vision of no concrete thing said")


def candidates_cap(n):
    """How many candidate specs the editor may list for a clip that keeps ``n`` pictures."""
    return n + broll.CANDIDATES_MORE + CANDIDATES_EXTRA

# --- the editor's prompt -------------------------------------------------------------------------------------------
_RULES = """You are the editor of a short-form clip cut from a longer conversation. You choose its B-roll pictures, but
you never write an image prompt: for each picture you fill a SHOT SPEC, field by field, and the code writes the image
prompt from the fields. So every field holds concrete nouns and plain adjectives a camera could record: no style word,
no camera word, no metaphor, no feeling, no negation.

List the CANDIDATE pictures: one for EVERY concrete thing named and every scene told, at least {least} when the clip
names that many, up to {cap}; none when it names nothing. The code keeps the best {n} by worth, {gap:g} s apart; the
others are reserves for a picture that fails. Only moments between {lo:.1f}s and {hi:.1f}s{avoid}. Never what the
video already shows (frame sheets: {sheets}, a thumbnail every 2.5 s).

THE HOUSE PRINCIPLES, in this order:
1. A PICTURE ONLY FOR WHAT IS NAMED OR TOLD: a thing the speaker names or a scene he tells, at its real scale, in its
real setting. The subject IS the thing named and holds its spoken name (a product or a substance: its usual look);
never a stand-in for an idea, a treatment or a length of time (the code ranks it last). A sentence that names nothing
gets no picture: the face is the picture.
2. THE LITERAL SENSE ONLY. Read the sentence before the anchor, then its own. "literal" is "figure" when the thing
named, taken literally, does not exist in the story the clip tells (a figure of speech or a comparison that only
qualifies something else); "denied" when the speaker says it is not so. Only "literal" gets a picture.
3. ONE VISIBLE INSTANT, what one photograph shows: no duration, no sound, no name or writing, no feeling.
4. AN EXPERIENCE IS WHAT IS SEEN: kind "vision" only for a concrete thing he says was seen; the subject is that
thing, people "none", never the person who sees. A colour, a light or a blur is no vision (the code drops it).
5. THE INSIDE OF A BODY IS ALWAYS DRAWN: organs, tissue, a brain, nerves, an operation (the organ, never the team)
are kind "body_inside"; the code adds the episode's drawing.
6. WHAT AN INSTRUMENT SEES: what only a microscope, a telescope or a scanner shows is kind "instrument"; the
subject is what its image shows.
7. NEVER A REAL PERSON: a real, named or identifiable person of the story is person "real" and the code drops the
spec. A speaker is never pictured. A stranger is "anonymous".
8. A DEATH: "clip_gravity" is "grave" ONLY when the clip TELLS a death ("real": real illness, injury, addiction or
loss; else "none"). Grave: every picture is an absence, the places and things of the person's life, nobody in the
frame, never the means of the death. In every clip, nothing that evokes an overdose, a means of suicide or a symbol
of death, not even as a visual cliché. A sentence about a death in a clip that does not tell one gets no picture;
in a grave clip, no drug, poison or medicine. A DRUG is never shown itself (the substance, its crystals or
powder, its gear): show what is said around it that a camera sees, its plant or place of origin, the place where
it is given, the people it is given to as anonymous strangers.
9. KEEP THE FACTS SAID: every precise fact he gives (a number, a colour, a place, an era) goes into the fields; add
none of your own.
10. VARY the subjects and the shots: never the same subject twice.
11. "worth" 1-5: 5 = the picture the clip needs, 1 = a nice extra.
12. "hero" true only for a real scene with depth (foreground, subject, background) that could fill a whole phone
screen.
13. AN ALT FOR EVERY CANDIDATE: "alt" is a different picture of the same words, used when the first one fails.

THE FIELDS of a spec:
- "anchor": 1-3 CONSECUTIVE words copied exactly from the transcript where the picture lands (the code finds them
  near "time"); "time": their second (from the markers); "said": the spoken words of that sentence, 25 at most.
- "kind": "thing", "scene" (a place or a moment of the story), "vision", "instrument", "body_inside", or "pair" (he
  compares two named things now; "subject_b" is the second).
- "subject": what fills the frame, 8 words at most; "subject_words": the spoken words naming it, copied from the
  transcript (the code checks them).
- "count": how many of the subject. "state": what it does or its condition at that instant, 10 words at most.
- "setting": where, 10 words at most, or "plain". "details": 2-3 visible details that make it THIS thing, 20 words.
- "people": who is in the frame; "person": who that is. "shot": the framing.
- "death_near": the sentence is about a death; "substance": a drug or a poison is involved; "intake": something is
  being taken. The code drops a death with a substance or an intake.
- "notion": only for the usual picture of a notion of the brief's glossary: its name as listed.
- "alt": the same fields from "literal" to "mood", without anchor, time, said, worth or hero.
"""
_CONTEXT = """
EPISODE BRIEF:
{brief}
{bible}
CLIP TITLE: {title}
HOOK: {hook}
SAID JUST BEFORE THE CLIP (context only): {before}

TRANSCRIPT OF THE CLIP (seconds from the clip start):
{text}

SAID JUST AFTER THE CLIP (context only): {after}"""
EDITOR_PROMPT = _RULES + visual_mood.MOOD_RULE.replace("{", "{{").replace("}", "}}") + "\n" + _CONTEXT

# --- the schema ----------------------------------------------------------------------------------------------------
_STR = {"type": "string"}
_BOOL = {"type": "boolean"}


def _enum(values):
    return {"type": "string", "enum": list(values)}


_FIELD_PROPS = {
    "literal": _enum(LITERAL), "kind": _enum(KINDS),
    "subject": _STR, "subject_words": _STR, "subject_b": _STR, "instrument": _STR,
    "count": _enum(COUNTS), "state": _STR, "setting": _STR, "details": _STR,
    "people": _enum(PEOPLE), "person": _enum(PERSON), "shot": _enum(SHOTS),
    "death_near": _BOOL, "substance": _BOOL, "intake": _BOOL,
    "mood": visual_mood.SCHEMA,
}
_FIELD_REQUIRED = ["literal", "kind", "subject", "subject_words", "count", "state", "setting", "details", "people",
                   "person", "shot", "death_near", "substance", "intake"]
ALT_SCHEMA = {"type": "object", "properties": {k: _FIELD_PROPS[k] for k in ALT_FIELDS}, "required": list(_FIELD_REQUIRED)}
SPEC_ITEM = {
    "type": "object",
    "properties": {"anchor": _STR, "time": {"type": "number"}, "said": _STR, **_FIELD_PROPS,
                   "worth": {"type": "integer", "minimum": 1, "maximum": 5}, "hero": _BOOL, "notion": _STR,
                   "alt": ALT_SCHEMA},
    "required": ["anchor", "time", "said"] + _FIELD_REQUIRED + ["mood", "worth", "hero", "alt"],
}
SPEC_SCHEMA = {
    "type": "object",
    "properties": {"clip_gravity": _enum(GRAVITY), "moments": {"type": "array", "items": SPEC_ITEM}},
    "required": ["clip_gravity", "moments"],
}


# --- checking one spec ---------------------------------------------------------------------------------------------
def _text(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _cap(v, n):
    return " ".join(_text(v).split()[:n]).rstrip(" ,;:")


def _tokens(text):
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _said(token, spoken):
    """``token`` is one of the ``spoken`` tokens: the same word, a plural, or the same 5-letter stem."""
    t = token.rstrip("s")
    return any(token == s or t == s.rstrip("s") or (len(token) >= 5 and len(s) >= 5 and token[:5] == s[:5])
               for s in spoken)


def words_said(subject_words, clip_text):
    """Every content word of ``subject_words`` occurs in ``clip_text`` (case and punctuation ignored, stem ok)."""
    toks = [t for t in _tokens(subject_words) if t not in broll.STOPWORDS]
    spoken = set(_tokens(clip_text))
    return bool(toks) and all(_said(t, spoken) for t in toks)


def _named(subject, subject_words):
    """The words of ``subject`` that are spoken words naming it (``subject_words``): the same word, a plural, a 5-letter
    stem, or one the start of the other (4 letters at least). None: the subject is a stand-in, not the thing named."""
    said = [t for t in _tokens(subject_words) if t not in broll.STOPWORDS]
    return [w for w in _tokens(subject) if w not in broll.STOPWORDS and any(
        _said(w, [t]) or (min(len(w), len(t)) >= 4 and (w.startswith(t) or t.startswith(w))) for t in said)]


def _abstract(word):
    return word in _ABSTRACT_SIGHT or (word.endswith("s") and word[:-1] in _ABSTRACT_SIGHT)


def _names_speaker(*texts):
    """A capitalised word of ``texts`` is a word of a speaker's name (the brief's speakers)."""
    names = broll._speaker_words()
    return bool(names) and any(w[0].isupper() and w.lower() in names
                               for t in texts for w in re.findall(r"[A-Za-z']+", str(t or "")))


def _drop(reason, spec, alt=False):
    name = f"spec: {'alt ' if alt else ''}{reason}"
    where = f'"{_text(spec.get("anchor"))[:40]}"' if spec.get("anchor") else "a spec"
    broll.filter_hit(name, f'{"Alternative of " if alt else "Spec "}{where} ({_text(spec.get("subject"))[:40] or "-"}, '
                           f'words "{_text(spec.get("subject_words"))[:40]}") dropped: {reason}.')
    return None, reason


def _fix(reason, spec):
    broll.filter_hit(f"spec: {reason} (fixed)", f'Spec "{_text(spec.get("anchor"))[:40]}": {reason} — fixed.')


def _clean_fields(raw, gravity):
    """The fields of ``raw`` in their types and caps; enums outside their list take a safe value."""
    s = {}
    s["literal"] = _text(raw.get("literal")).lower()
    s["kind"] = _text(raw.get("kind")).lower()
    if s["kind"] not in KINDS:
        s["kind"] = "thing"
    for k in ("subject", "subject_b", "instrument", "state", "setting", "details"):
        s[k] = _cap(raw.get(k), CAPS[k])
    s["subject_words"] = _cap(raw.get("subject_words"), 12)
    s["setting"] = s["setting"] or "plain"
    c = _text(raw.get("count")).lower()
    s["count"] = c if c in COUNTS else "1"
    s["shot"] = _text(raw.get("shot")).lower() if _text(raw.get("shot")).lower() in SHOTS else "medium"
    s["people"] = _text(raw.get("people")).lower() if _text(raw.get("people")).lower() in PEOPLE else "none"
    p = _text(raw.get("person")).lower()
    s["person"] = p if p in PERSON else ("none" if s["people"] == "none" else "anonymous")
    for k in FLAGS:
        s[k] = raw.get(k) is True
    s["mood"] = dict(raw["mood"]) if isinstance(raw.get("mood"), dict) else {}
    if gravity == "grave" and s["mood"]:
        s["mood"]["gravity"] = "grave"
    return s


def _check(s, raw, clip_text, gravity, alt=False):
    """Drops (returns a reason) or fixes ``s`` in place (returns "")."""
    if s["literal"] != "literal":
        return {"figure": "a figure of speech", "denied": "denied by the speaker"}.get(s["literal"], "not literal")
    if s["person"] == "real":
        return "a real person"
    if s["death_near"] and (s["substance"] or s["intake"]):
        return "a death with a substance or an intake"
    if s["death_near"] and gravity != "grave":
        return "a death in a clip that does not tell one"     # any picture there evokes the death
    if gravity == "grave" and (s["substance"] or s["intake"]):
        return "a substance in a clip about a death"
    if not s["subject"]:
        return "no subject"
    if not words_said(s["subject_words"], clip_text):
        return "subject words not said in the clip"
    if _names_speaker(s["subject"], s["subject_b"], s["subject_words"]):
        return "a speaker of the video"
    if s["kind"] == "vision" and all(_abstract(w) for w in _named(s["subject"], s["subject_words"])):
        return "a vision of no concrete thing said"    # a colour field, a glare: nobody links it to the words
    # consistency of the kind
    if s["kind"] == "body_inside" and s["instrument"]:
        s["kind"] = "instrument"           # a scan or a micrograph keeps its instrument's look
    if s["kind"] != "instrument":
        s["instrument"] = ""
    if s["kind"] == "pair" and not s["subject_b"]:
        s["kind"] = "thing"
    if s["kind"] != "pair":
        s["subject_b"] = ""
    if s["kind"] in ("vision", "body_inside") and s["people"] != "none":
        if not alt:
            _fix(f"{s['kind']} with people", raw)
        s["people"] = "none"
    if gravity == "grave" and s["people"] != "none":
        if not alt:
            _fix("grave clip, nobody in the frame", raw)
        s["people"] = "none"
    if s["people"] == "none":
        s["person"] = "none"
    elif s["person"] == "none":
        s["person"] = "anonymous"
    return ""


def _alt_of(spec, clip_text, gravity):
    """The spec's "alt" merged onto it and checked -> its fields, or None (an invalid one is a filter hit)."""
    raw_alt = spec.get("alt")
    if not (isinstance(raw_alt, dict) and raw_alt):
        return None
    merged = {**{k: spec.get(k) for k in ALT_FIELDS}, **raw_alt}
    a = _clean_fields(merged, gravity)
    why = _check(a, merged, clip_text, gravity, alt=True)
    if why:
        _drop(why, {**merged, "anchor": _text(spec.get("anchor"))}, alt=True)
        return None
    return {k: a[k] for k in ALT_FIELDS}


def validate(spec, clip_text, gravity):
    """One editor's spec -> (the cleaned spec, "ok") or (None, why). Drops: not literal, a real person, a death with a
    substance or an intake, no subject, subject words not said in the clip, a speaker, a vision of no concrete thing
    said. Fixes: who is in the frame of a vision, of the inside of a body, of a grave clip; the kind's own fields; the
    word caps. Its "alt" goes through the same check (merged onto the spec): an invalid alt is removed, the spec kept;
    a spec dropped for its picture (_PICTURE_FAULTS) hands its place to a valid alt (worth - 1). A subject that holds
    none of its spoken words is a stand-in: worth - UNNAMED_COST. Every drop is a broll.filter_hit."""
    if not isinstance(spec, dict):
        return _drop("not an object", {})
    s = _clean_fields(spec, gravity)
    why = _check(s, spec, clip_text, gravity)
    if why and why not in _PICTURE_FAULTS:
        return _drop(why, spec)
    try:
        worth = max(1, min(5, int(round(float(spec.get("worth"))))))
    except (TypeError, ValueError):
        worth = 1
    hero = spec.get("hero") is True
    alt = _alt_of(spec, clip_text, gravity)
    if why:
        _drop(why, spec)
        if not alt:
            return None, why
        broll.filter_hit("spec: its alternative instead", f'Spec "{_text(spec.get("anchor"))[:40]}": its alternative '
                                                          f'"{alt["subject"][:40]}" takes its place.')
        s, alt, worth, hero = dict(alt), None, worth - 1, False
    if not _named(s["subject"], s["subject_words"]):
        worth -= UNNAMED_COST
        broll.filter_hit("spec: subject not the thing named (worth lowered)",
                         f'Spec "{_text(spec.get("anchor"))[:40]}": "{s["subject"][:40]}" holds none of the words '
                         f'"{s["subject_words"][:40]}" — worth lowered.')
    try:
        t = float(spec.get("time"))
    except (TypeError, ValueError):
        t = 0.0
    out = {"anchor": _text(spec.get("anchor"))[:80], "time": t, "said": _cap(spec.get("said"), CAPS["said"]),
           "worth": max(1, worth), **s, "hero": hero, "notion": _text(spec.get("notion"))[:80]}
    if alt:
        out["alt"] = alt
    return out, "ok"


# --- the call and the placing ---------------------------------------------------------------------------------------
def _prompt(clip, words, n, cap, avoid, transcript, start, end, sheets, head, gap, block):
    import ai_brain
    duration = words[-1]["end"]
    end = end if end is not None else start + duration
    before, after = broll._context(transcript, start, end)
    clip_text = " ".join(w["text"] for w in words)
    avoid_txt = (", and not within 1.2 s of " + ", ".join(f"{a:.1f}s" for a in avoid)) if avoid else ""
    brief = ai_brain.brief_for_clip(ai_brain.EPISODE_BRIEF, f"{before} {clip_text} {after}", start, end)
    prompt = EDITOR_PROMPT.format(
        n=n, cap=cap, least=min(cap, n + 2), gap=gap, lo=head, hi=duration - broll.TAIL_FREE - broll.SEG_DUR,
        avoid=avoid_txt + broll._block_text(block),
        sheets=", ".join(os.path.basename(p) for p in sheets or []) or "none",
        brief=brief or "(no brief for this video)", bible=broll._bible_block(),
        title=clip.get("video_title_for_youtube_short") or "-", hook=clip.get("viral_hook_text") or "-",
        before=before or "-", after=after or "-", text=broll._numbered_text(words)[:6000])
    return prompt, f"{before} {clip_text} {after}"


def _mentions(words, toks):
    """Where the tokens ``toks`` are spoken in a row, anywhere in the clip (broll._find_anchor's own matching)."""
    n = len(toks)
    return [i for i in range(len(words))
            if broll._tokens(" ".join(w["text"] for w in words[i:i + n]))[:n] == toks
            or (n == 1 and toks[0] in broll._tokens(words[i]["text"]))]


def _on_words(spec, words, avoid, head, block):
    """Puts ``spec``'s anchor on words broll._parse_moments finds (it looks for the anchor's exact words within 4 s of
    "time"; the bench lost specs whose anchor skipped or changed a word, or whose time was a sentence marker too far
    off). The anchor's own words where they are spoken nearest its time; else the spoken word of its anchor (then of its
    subject words) nearest its time, within RELOCATE_MAX s. A mention that lands in the allowed window within
    RELOCATE_MAX s wins over a nearer one outside it. Fixes "anchor" and "time" in place; returns "" (as given),
    "respelled", "moved" or "lost" (none of its words is spoken: the parser drops it)."""
    duration = words[-1]["end"]
    near = spec["time"]
    toks = broll._tokens(spec["anchor"])
    hits = [(i, len(toks), spec["anchor"]) for i in _mentions(words, toks)] if toks else []
    respelled = not hits
    # respelled: the longest word first (the one that names, as broll._key_index reads it), the anchor's then the
    # subject words'
    keys = []
    for source in ((spec["anchor"], spec["subject_words"]) if respelled else ()):
        keys += sorted((t for t in broll._tokens(source) if t not in broll.STOPWORDS and len(t) >= 3 and t not in keys),
                       key=len, reverse=True)
    for key in keys:
        hits = [(i, 1, x) for i, w in enumerate(words) if abs(w["start"] - near) <= RELOCATE_MAX
                for x in broll._tokens(w["text"]) if _said(x, [key])]
        if hits:
            break
    if not hits:
        return "lost"

    def dist(h):
        return abs(words[h[0]]["start"] - near)

    def lands(h):
        k = broll._key_index(words, h[0], h[1])
        return broll._allowed(max(0.0, words[k]["start"] - broll.KEY_LEAD), duration, avoid, head, block)

    best = min(hits, key=dist)
    inside = [h for h in hits if lands(h) and dist(h) <= RELOCATE_MAX]
    moved = not lands(best) and bool(inside)
    if moved:
        best = min(inside, key=dist)
    old = f'"{spec["anchor"]}" at {near:.1f} s'
    spec["anchor"], spec["time"] = best[2], words[best[0]]["start"]
    if respelled:
        broll.filter_hit("spec: anchor respelled (fixed)", f'Spec {old}: its words are not spoken in a row — '
                                                           f'anchored on "{best[2]}" at {spec["time"]:.1f} s.')
        return "respelled"
    if moved:
        broll.filter_hit("spec: anchor moved into the window (fixed)",
                         f'Spec {old}: outside the window — moved to its mention at {spec["time"]:.1f} s.')
        return "moved"
    return ""


def _item(k, spec):
    """A spec in the shape broll._parse_moments reads (its subject stands in for the image prompt)."""
    return {"anchor": spec["anchor"], "time": spec["time"], "said": spec["said"], "worth": spec["worth"],
            "subject": spec["subject"], "search_query": spec["subject"], "image_prompt": spec["subject"],
            "shot": spec["shot"], "style": "photo", "people": spec["people"],
            "inside_body": spec["kind"] == "body_inside", "mood": spec["mood"] or None, "hero": spec["hero"],
            "notion": spec["notion"], "idea": f"{_TAG}{k}"}


def _finish(m, spec, gravity):
    m.update(spec=spec, mood=visual_mood.clean(spec["mood"]), query=spec["subject"], subject=spec["subject"],
             prompt=spec["subject"], said=spec["said"] or m.get("said") or "", style="photo", people=spec["people"],
             inside_body=spec["kind"] == "body_inside", clip_gravity=gravity, idea="")
    return m


def plan_specs(clip, words, n, avoid, transcript=None, start=0.0, end=None, sheets=None, head=broll.HEAD_FREE,
               tail=broll.MIXED_TAIL, gap_min=broll.MIXED_GAP, block=(), dur_range=None):
    """The editor's call for one clip -> (moments, reserves). Every concrete thing named is asked, up to
    candidates_cap(n) specs; every one is validated, its anchor put on spoken words (_on_words), then placed by
    broll._parse_moments (anchor, window, duration). The best ``n`` by worth, spaced by broll._space, are the moments
    (time order, the hero set by broll.pick_hero among the specs marked hero); every other placed spec is a reserve
    (worth order, never the hero, never a kept subject again, its time on screen ending before the next moment). Every
    moment keeps "spec" (the validated dict, its "alt" included), "mood", "query", "style", "people", "inside_body",
    "clip_gravity"."""
    import ai_brain
    duration = words[-1]["end"]
    gap = max(broll.DENSITY["normal"]["gap"], gap_min)
    dur_range = dur_range or (broll.CARD_DUR_MIN, broll.CARD_DUR_MAX)
    lo = dur_range[0]
    cap = candidates_cap(n)
    prompt, context_text = _prompt(clip, words, n, cap, avoid, transcript, start, end, sheets, head, gap, block)
    data = broll.claude_json(prompt, SPEC_SCHEMA, timeout=600, attach=list(sheets or []) or None,
                             effort=os.environ.get("CLAUDE_EFFORT_BROLL") or "high", stage="broll_plan") or {}
    gravity = data.get("clip_gravity") if data.get("clip_gravity") in GRAVITY else "none"
    if gravity == "grave":
        print("   🕯️ The clip tells a death: every picture an absence, nobody in the frame.")
    clip_text = " ".join(w["text"] for w in words)
    specs = []
    for raw in data.get("moments") or []:
        spec, _why = validate(raw, clip_text, gravity)
        if spec:
            specs.append(spec)
    # Placed one by one (each filter counted once), then chosen together.
    placed = []
    for k, spec in enumerate(specs):
        _on_words(spec, words, avoid, head, block)
        for m in broll._parse_moments({"moments": [_item(k, spec)]}, words, 1, avoid, gap, dur_range, tail, head,
                                      block):
            placed.append(_finish(m, spec, gravity))
    kept = broll._space(placed, n, gap)
    for a, b in zip(kept, kept[1:]):
        a["dur"] = round(max(lo, min(a["dur"], b["t"] - a["t"] - broll.DUR_NEXT_GAP)), 2)
    reserves, seen = [], [broll._stem(m["subject"]) for m in kept]
    for m in sorted((m for m in placed if not any(m is x for x in kept)), key=lambda m: (-m["score"], m["t"])):
        if broll._stem(m["subject"]) in seen:
            broll.filter_hit("spec: reserve, same subject", f'Reserve "{m["anchor"]}" left out: "{m["subject"]}" already planned.')
            continue
        seen.append(broll._stem(m["subject"]))
        nxt = [x["t"] for x in kept if x["t"] > m["t"]]
        if nxt:
            m["dur"] = round(max(lo, min(m["dur"], min(nxt) - m["t"] - broll.DUR_NEXT_GAP)), 2)
        m["hero"] = False
        reserves.append(m)
    # The hero: the code's pick among the specs the editor marked as a full-screen scene (its notion set aside, as
    # plan_with_claude does: the hero is made for this clip).
    for m in kept:
        if m["hero"]:
            m["notion"] = ""
    marked = [m for m in kept if m["spec"]["hero"]]
    k_hero = broll.pick_hero(marked, duration, avoid, head, block) if marked else None
    for m in kept:
        m["hero"] = k_hero is not None and m is marked[k_hero]
    broll.apply_notions(kept + reserves, ai_brain.EPISODE_BRIEF, context_text)
    for m in kept + reserves:
        m["spec"]["notion"] = m.get("notion") or ""
    print(f"   🗂️ Editor's specs: {len(data.get('moments') or [])} listed (up to {cap}), {len(specs)} valid, "
          f"{len(placed)} placed, {len(kept)} kept, {len(reserves)} in reserve (clip gravity {gravity}).")
    return kept, reserves
