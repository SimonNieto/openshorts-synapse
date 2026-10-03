"""B-roll v20: the image prompt, built by CODE from the editor's shot spec (see output/_test_broll/v20_contract.md §2).

Z-Image Turbo's text encoder reads causally: the START of the prompt weighs most, and it wants concrete scenes (nouns,
counts, light and colour words), never metaphors, feelings or negations. So the order is fixed and the subject comes
first (the episode's drawing leads a drawn picture, and is the only text outside the word cap):

  medium -> "{count} {subject}, {state}, {setting}." -> details -> who is in the frame -> shot and layout ->
  light and colours (<= 25 words, no emotional adjective).

Nothing is appended by regex: a "3 metres" or "85 mm" in the details never becomes a count. Every free-text field is
cleaned (clauses that negate, name a camera or are filler are dropped; measures are dropped), so the prompt holds no
negation word whatever the editor wrote. The same spec also gives the judge's line and the yes/no questions the
checker asks of the picture (`questions`). Deterministic: the same spec gives the same string. No model is called.
"""
import re

import visual_mood

SIZES = {"hero": (864, 1536), "card": (1280, 720)}       # Z-Image's own sizes (9:16 and 16:9)
MIN_WORDS, MAX_WORDS = 50, 110                            # a prompt's words, the drawing text excluded
LIGHT_CAP = 25                                            # words of the light + colours block
KINDS = ("thing", "scene", "vision", "instrument", "body_inside", "pair")
# The house drawing when the episode gave none (positive words only; the episode's own is broll.episode_drawing()).
DRAWING_FALLBACK = ("A hand-painted documentary illustration in gouache and coloured pencil: forms true to life and "
                    "simplified to clear volumes, clean dry matte surfaces with the grain of the paper, the true colours "
                    "of each thing gently muted, painted edge to edge across the whole frame.")

_COUNT_WORDS = {"1": "a single", "2": "two", "3": "three", "4": "four", "many": "many"}
_COUNT_ALIAS = {"one": "1", "single": "1", "two": "2", "three": "3", "four": "4", "several": "many", "crowd": "many"}
# A past era in words (photo kinds only). "before" has no photograph: a photographed reconstruction keeps the medium.
ERA_WORDS = {"now": "",
             "recent": "on colour film from the late twentieth century",
             "early": "in black and white from the early twentieth century",
             "before": "of a faithful period reconstruction"}
_SHOT = {"wide": "wide shot, the whole setting in view",
         "medium": "medium shot from a few steps away",
         "close": "close-up of the subject, filling most of the frame",
         "macro": "macro close-up of the finest detail, a thin sliver of sharp focus"}
_LAYOUT = {("hero", False): "vertical full-screen scene with a close foreground, a middle ground and depth behind",
           ("hero", True): "vertical full-screen composition, forms clear from edge to edge",
           ("card", False): "horizontal frame, the subject large and centred",
           ("card", True): "horizontal frame, the subject large and centred"}
_LAYOUT_PAIR = {"hero": "vertical full-screen composition, two equal halves, each subject large and clear",
                "card": "horizontal frame, two equal halves, each subject large and centred"}
_PEOPLE_LINE = {"hands": "Only a pair of hands enters the frame.",
                "one": "One anonymous person, a stranger, seen from the side.",
                "group": "A small group of anonymous strangers, seen together from a distance."}
# Nobody in the frame, said in the positive (right after the subject sentence; see _empty_line).
_EMPTY_SCENE = "The place is empty and still, deserted."
_EMPTY_SETTING = "The setting is deserted."
_KEY = {"low": "low-key light, deep shadows, one pool of light on the subject",
        "mid": "balanced light, a clear key light with soft shadows",
        "high": "bright high-key light with open shadows"}
_KEY_INSTRUMENT = {"low": "dark field, the subject glowing against a deep dark background",
                   "mid": "even illumination, clear detail",
                   "high": "bright field, a pale background, fine detail"}
_PAD = ("True colours and fine detail on every surface.", "The main subject is sharp and clearly set apart.")
# What the code drops when the editor's words are tightened to fit (cheapest first): see build_prompt.
_SHRINK = ({"details": 14}, {"details": 8}, {"light": 18}, {"state": 8, "setting": 8}, {"details": 4}, {"light": 12})

# --- cleaning the editor's words -------------------------------------------------------------------------------------
NEGATION = re.compile(r"\b(?:no|not|never|without|avoid\w*|nothing|none|nobody|nowhere|neither|nor|cannot|lacking)\b"
                      r"|n['’]t\b", re.I)
_CAMERA = re.compile(r"\b(?:aperture|bokeh|dslr|mirrorless|canon|nikon|sony|leica|hasselblad|fujifilm|gopro|arri|"
                     r"[48]k|masterpiece|hyper-?realistic|photo-?realistic|ultra[- ]detailed|highly detailed|"
                     r"trending on \w+)\b|\bf/\d|\b\d+\s*mm\s+(?:lens|prime)\b|"
                     r"\b(?:shot|taken|photographed|filmed|captured)\s+(?:at|on|with|using)\b", re.I)
_UNIT = (r"(?:mm|cm|km|m|metres?|meters?|centimetres?|centimeters?|kilometres?|kilometers?|miles?|feet|foot|ft|"
         r"inch(?:es)?|yards?|kg|kilos?|tonnes?|tons?|grams?|litres?|liters?|degrees?|percent|%)")
_MEASURE = re.compile(r"\b\d+(?:[.,]\d+)?[\s-]*" + _UNIT + r"(?![a-z])(?:\s+(?:high|tall|long|wide|deep|thick|away|"
                      r"across|apart))?", re.I)
_DANGLING = re.compile(r"(?:^|\s+)(?:at|of|about|around|over|under|near|by|to|from|with|for|roughly|approximately)$", re.I)
_EMOTION = re.compile(r"\b(?:" + "|".join(sorted(
    (set(visual_mood.VAL_WORD.values()) | set(visual_mood.INT_WORD.values())) - {"warm", "luminous"}
    | {"somber", "ominous", "eerie", "haunting", "menacing", "sinister", "gloomy", "melancholy", "moody", "dramatic",
       "cinematic", "bleak", "anxious", "fearful", "joyful", "happy", "sad", "serene", "majestic", "beautiful",
       "unsettling", "spooky", "grim"})) + r")\b,?\s*", re.I)
_PREPS = frozenset("of with in on at from for under over by beside near inside outside above below behind against along "
                   "across among between through around into onto".split())
_IRREGULAR = {"man": "men", "woman": "women", "child": "children", "person": "people", "foot": "feet", "tooth": "teeth",
              "mouse": "mice", "leaf": "leaves", "knife": "knives", "wolf": "wolves", "shelf": "shelves",
              "tomato": "tomatoes", "potato": "potatoes"}


def _wc(text):
    return len(str(text or "").split())


def _trim(text, limit):
    words = str(text or "").split()
    return " ".join(words[:limit]) if limit and len(words) > limit else " ".join(words)


def _cap(text):
    return text[:1].upper() + text[1:] if text else text


def _clean(text, limit=None):
    """One free-text field of the spec, made safe: clauses (split on , ; :) that negate or name a camera are dropped,
    measures ("3 metres", "85 mm") are dropped, then at most ``limit`` words are kept."""
    text = re.sub(r"\s+", " ", str(text or "")).strip().strip(".;,:")
    keep = []
    for clause in re.split(r"\s*[;,:]\s*|\s+[—–]\s+", text):
        if not clause or NEGATION.search(clause) or _CAMERA.search(clause):
            continue
        clause = re.sub(r"\s+", " ", _MEASURE.sub("", clause)).strip(" -")
        clause = _DANGLING.sub("", clause).strip()
        if clause:
            keep.append(clause)
    return _trim(", ".join(keep), limit)


def _drawing_text(drawing):
    """The episode's drawing as given, minus any piece that negates (the bible already refuses those)."""
    text = re.sub(r"\s+", " ", str(drawing or "")).strip()
    pieces = [p for p in re.split(r"(?<=[,;.!?])\s+", text) if p and not NEGATION.search(p)]
    text = " ".join(pieces).rstrip(",;")
    if not text:
        return DRAWING_FALLBACK
    return text if text[-1] in ".!?:" else text + "."


# --- the spec's fields -------------------------------------------------------------------------------------------------
def _kind(spec):
    return spec.get("kind") if spec.get("kind") in KINDS else "thing"


def _count(spec):
    c = str(spec.get("count") or "1").strip().lower()
    c = _COUNT_ALIAS.get(c, c)
    return c if c in _COUNT_WORDS else "1"


def _bare(subject):
    return re.sub(r"^(?:a|an|the|one|some|many|two|three|four)\s+", "", subject, flags=re.I)


def _compound(subject):
    """A subject that lists several things ("eye mask, earbuds, blood pressure cuff"): no count word, no plural, no
    counting question — the count the editor gave was the length of the list."""
    return bool(re.search(r",|\band\b", str(subject or ""), re.I))


def _plural(phrase):
    """The head noun of a noun phrase made plural ("glass of water" -> "glasses of water"); a plural stays."""
    words = phrase.split()
    if not words:
        return phrase
    end = next((i for i, w in enumerate(words) if i > 0 and (w.lower() in _PREPS or w.lower().endswith("ing"))),
               len(words))
    head = words[end - 1]
    low = head.lower()
    if low in _IRREGULAR:
        new = _IRREGULAR[low]
    elif low.endswith(("ss", "us", "is", "sh", "ch", "x", "z")):
        new = head + "es"
    elif low.endswith("s"):
        new = head
    elif low.endswith("y") and len(low) > 1 and low[-2] not in "aeiou":
        new = head[:-1] + "ies"
    else:
        new = head + "s"
    if low in _IRREGULAR and head[:1].isupper():
        new = _cap(new)
    words[end - 1] = new
    return " ".join(words)


def _subject(spec, key="subject", words_key="subject_words"):
    return _clean(spec.get(key), 10) or _clean(spec.get(words_key), 6) or ("the subject" if key == "subject" else "")


def _article(word):
    return "An" if re.match(r"(?:[aeiou]|x-ray)", word, re.I) else "A"


def _with_article(phrase):
    """"skull" -> "a skull"; a phrase that has an article, or is plural, is left as it is."""
    if re.match(r"(?:a|an|the|one|some|two|three|four|many)\s", phrase, re.I) or re.search(r"[^s]s$", phrase):
        return phrase
    return f"{_article(phrase).lower()} {phrase}"


def _pair_b(spec):
    return _subject(spec, "subject_b", "") or "a second thing"


def _people(spec):
    """Who is in the frame: only a thing or a scene may hold people (a vision, an instrument's image, a drawn inside
    and a pair never do); an unknown value is nobody."""
    p = spec.get("people")
    return p if _kind(spec) in ("thing", "scene") and p in ("hands", "one", "group") else "none"


def _empty_line(spec):
    """Nobody in the frame, said in the POSITIVE (a negation is banned, and a place named alone invites a person):
    a scene is "empty and still, deserted", a thing set in a named place says the setting is deserted. Else ''."""
    if _people(spec) != "none":
        return ""
    kind = _kind(spec)
    if kind == "scene":
        return _EMPTY_SCENE
    if kind == "thing":
        setting = _clean(spec.get("setting"), 12)
        if setting and setting.lower() != "plain":
            return _EMPTY_SETTING
    return ""


def _mood(spec):
    return visual_mood.clean(spec.get("mood"))


def _phrase(spec, caps):
    """« a single red apple, resting on a table, on a plain dark background » (a pair: both sides)."""
    kind = _kind(spec)
    if kind == "pair":
        return f"on the left, {_with_article(_subject(spec))}; on the right, {_with_article(_pair_b(spec))}"
    subject = _bare(_subject(spec))
    count = _count(spec)
    listed = _compound(subject)
    if count != "1" and not listed:
        subject = _plural(subject)
    setting = _clean(spec.get("setting"), caps["setting"])
    if not setting or setting.lower() == "plain":
        setting = "on a plain dark background"
    elif setting.split()[0].lower() not in _PREPS:
        setting = "in " + setting
    parts = (subject if listed else f"{_COUNT_WORDS[count]} {subject}", _clean(spec.get("state"), caps["state"]), setting)
    return ", ".join(p for p in parts if p)


def _medium(spec, era_words):
    """The lead of the prompt, up to the subject (<= 14 words)."""
    kind = _kind(spec)
    if kind == "pair":
        return "Two images side by side, the same scale."
    if kind == "vision":
        # never "someone": the engine draws the person who sees (a man in a kitchen for the voices in his head)
        return "What is perceived from inside the experience, the whole frame filled edge to edge by"
    if kind == "instrument":
        name = re.sub(r"^(?:a|an|the)\s+", "", _clean(spec.get("instrument"), 5), flags=re.I) or "scientific instrument"
        if not re.search(r"(?:image|micrograph|scan|view)$", name, re.I):
            name += " image"
        return f"{_article(name)} {name} showing"
    era = era_words.strip() if era_words else ERA_WORDS.get(_mood(spec)["era"], "")
    return f"A documentary photograph {era}, showing" if era else "A documentary photograph showing"


def _palette(m, kind):
    """The colours (said, then true), without any emotional adjective; muted when an illness is lived as negative.
    A black-and-white picture of an early era names none."""
    if m["era"] == "early" and kind in ("thing", "scene"):
        return ""
    items = [_EMOTION.sub("", _clean(m.get(k), 12)).strip(" ,") for k in ("colours_said", "true_colours")]
    items = [i for i in items if i]
    if len(items) == 2 and items[1].lower() in items[0].lower():
        items = items[:1]
    muted = visual_mood._restrained(m)
    text = _trim(", ".join(items), 12 - (2 if muted else 0))
    return ", ".join(p for p in (text, "muted colours" if muted else "") if p)


def _look(spec, cap):
    """Light, then colours, in at most ``cap`` words: concrete light words from the mood's exposure (key_of) and its
    intensity's light; no valence or intensity adjective."""
    kind, m = _kind(spec), _mood(spec)
    key = visual_mood.key_of(m)
    pal = _palette(m, kind)
    pal = f"Colours: {pal}." if pal else ""
    given = _EMOTION.sub("", _clean(spec.get("light"), 12)).strip(" ,")
    if given:
        light = given                                     # v21: the art director's concrete light words
    else:
        if kind == "instrument":
            lead, direction = _KEY_INSTRUMENT[key], ""
        else:
            intensity = "charged" if m["gravity"] == "real" and m["intensity"] == "extreme" else m["intensity"]
            lead = _KEY[key]
            direction = ("soft natural daylight" if m["gravity"] == "grave"
                         else visual_mood.LIGHT_BY_INTENSITY[intensity])
        light = f"{lead}; {direction}" if direction and _wc(lead) + _wc(direction) <= cap - _wc(pal) else lead
    return " ".join(p for p in (_cap(light) + ".", pal) if p)


def _frame(spec, layout):
    kind = _kind(spec)
    shot = _SHOT.get(spec.get("shot"), _SHOT["medium"])
    side = "card" if layout == "card" else "hero"
    lay = _LAYOUT_PAIR[side] if kind == "pair" else _LAYOUT[(side, kind in ("instrument", "body_inside"))]
    return f"{_cap(shot)}, {lay}."


def _blocks(spec, layout, era_words, caps):
    """(first block, the others) of the prompt's body."""
    kind = _kind(spec)
    phrase = _phrase(spec, caps)
    medium = _medium(spec, era_words)
    if kind == "pair":
        first = f"{medium} {_cap(phrase)}."
    elif kind == "body_inside":
        first = f"It shows {phrase}."
    else:
        first = f"{medium} {phrase}."
    out = [first]
    empty = _empty_line(spec)
    if empty:
        out.append(empty)
    details = _clean(spec.get("details"), caps["details"])
    if details:
        out.append(f"Visible details: {details}.")
    people = _PEOPLE_LINE.get(_people(spec))
    if people:
        out.append(people)
    out.append(_frame(spec, layout))
    out.append(_look(spec, caps["light"]))
    return out


def build_prompt(spec, layout="hero", drawing="", era_words=""):
    """The image prompt of one shot spec for ``layout`` ("hero": a full vertical scene, "card": a wide frame).
    ``drawing``: the episode's drawing text, which leads a "body_inside" picture and is the only text beyond the word
    cap; ``era_words``: an override of the mood's era wording (photo kinds). Deterministic, no negation."""
    spec = spec if isinstance(spec, dict) else {}
    caps = {"details": 24, "state": 12, "setting": 12, "light": LIGHT_CAP}
    blocks = _blocks(spec, layout, era_words, caps)
    for step in _SHRINK:                                       # too long: tighten the optional words, cheapest first
        if _wc(" ".join(blocks)) <= MAX_WORDS:
            break
        caps.update(step)
        blocks = _blocks(spec, layout, era_words, caps)
    for pad in _PAD:                                           # too short: plain, positive filler
        if _wc(" ".join(blocks)) >= MIN_WORDS:
            break
        blocks.append(pad)
    if _kind(spec) == "body_inside":
        blocks.insert(0, _drawing_text(drawing))
    return " ".join(blocks)


def size_for(layout):
    """(width, height) asked from Z-Image for a layout (its official sizes); anything but "card" is a hero."""
    return SIZES["card"] if layout == "card" else SIZES["hero"]


# --- the judge's side --------------------------------------------------------------------------------------------------
def judge_line(spec):
    """One sentence of what must be seen in the picture."""
    spec = spec if isinstance(spec, dict) else {}
    kind = _kind(spec)
    caps = {"details": 24, "state": 12, "setting": 12}
    phrase = _phrase(spec, caps)
    if kind == "pair":
        return f"Two images side by side: {_with_article(_subject(spec))} and {_with_article(_pair_b(spec))}."
    if kind == "vision":
        return f"What a person sees: {phrase}."
    if kind == "instrument":
        name = _clean(spec.get("instrument"), 5) or "scientific instrument"
        return f"{_cap(name)} image showing {phrase}."
    if kind == "body_inside":
        return f"A drawing of {phrase}."
    return _cap(phrase) + "."


def questions(spec):
    """The yes/no questions the checker asks of a picture, with the answer the spec expects: [{"id", "q", "expect"}].
    expect: "yes" / "no" / an int / "hands" / "photograph" / "drawing" / "scientific image". For q_people an int is
    the number of people (0, 1), and 2 means two or more. No q_people for a "body_inside" or an "instrument" (the body
    is the subject), no q_count for a "pair" (two images)."""
    spec = spec if isinstance(spec, dict) else {}
    kind = _kind(spec)
    subject = _subject(spec)
    count = _count(spec)
    listed = _compound(subject)
    qs = [{"id": "q_subject",
           "q": (f"Is one of the two main subjects {subject}?" if kind == "pair"
                 else f"Does the picture show {subject}?" if listed else f"Is the main subject {subject}?"),
           "expect": "yes"}]
    # No count for a pair (two images: the model counts the halves and the subjects, and the split picture was dropped),
    # nor for a subject that lists several things (the count was the list's length).
    if count in ("1", "2", "3", "4") and kind != "pair" and not listed:
        qs.append({"id": "q_count", "q": f"How many {_plural(_bare(subject))} are visible?", "expect": int(count)})
    # No people question where the body IS the subject (an anatomical arm or a drawn brain is "1 body part"), nor for
    # a pair (each half has its own: a drawn synapse beside a clenched fist).
    people = _people(spec)
    if kind in ("body_inside", "instrument", "pair"):
        pass
    elif people == "hands":
        qs.append({"id": "q_people", "q": "Apart from hands and arms, is any part of a person visible?", "expect": "no"})
    else:
        qs.append({"id": "q_people", "q": "How many people or body parts are visible?",
                   "expect": {"none": 0, "one": 1, "group": 2}[people]})
    qs.append({"id": "q_text", "q": "Is there any writing, letters or numbers?", "expect": "no"})
    # No medium question for a pair (each half has its own: a drawn neuron beside a telescope's frame) nor for a
    # vision (what a person perceives reads as "digital art" to a checker, and was dropped as the wrong medium).
    if kind not in ("pair", "vision"):
        qs.append({"id": "q_medium", "q": "Is it a photograph, a drawing or painting, or a scientific image?",
                   "expect": {"body_inside": "drawing", "instrument": "scientific image"}.get(kind, "photograph")})
    # A medicine shown is fine; a drug being taken, and near a death any pill, is not (the house rule: nothing that
    # evokes an overdose, a means of suicide or a symbol of death).
    grave = spec.get("death_near") or _mood(spec).get("gravity") == "grave"
    near = ("pills or a medicine bottle, a garment or an object hanging from a rope, a cord or a thread (a garment on a "
            "wall hook, a hanger or a peg is NOT that), a belt, a strap, a tie, a scarf, a cord or a tube hanging, "
            "draped or looped, " if grave else "")
    qs.append({"id": "q_unsafe", "expect": "no",
               "q": f"Does it show blood, a wound, a weapon, a drug being taken or prepared (a syringe, powder, a pipe), "
                    f"{near}a grave, a coffin, a hospital bed, a flat heart line, a noose or a lifeless body?"})
    qs.append({"id": "q_body_photo", "expect": "no",
               "q": "Is it a PHOTOGRAPH of a surgical operation or of the inside of a body (an organ, a brain, tissue)?"})
    if kind == "pair":
        qs.append({"id": "q_pair", "q": f"Are there two images, {_with_article(subject)} and "
                                        f"{_with_article(_pair_b(spec))}?", "expect": "yes"})
    return qs
