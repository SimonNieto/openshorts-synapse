"""B-roll v20 — the check. ONE Claude call looks at every picture of a batch as a viewer who knows NOTHING of the video:
what it sees, whether the spoken words alone would link it, then literal questions the code built from the spec (the
expected answers are never shown). ``decide`` turns the verdict into keep / rerender / alt / drop. No model is called
here except through ``broll.claude_json``."""
import os
import re
import shutil
import tempfile

import broll

MIN_PER_CLIP = 2        # fewer pictures kept than this: the reserves are rendered
BUDGET = 3              # renders of one moment, the first included
LINK_TRIES = 2          # a picture that does not link / shows another subject is rendered again only below this
LOOK_BAD = 2            # a look at or under this is rendered again once

CHECK_PROMPT = """You are a viewer scrolling short videos. You know NOTHING about this video: not its subject, not its \
story, not who speaks. Under each picture you get ONLY the spoken words heard while it is on screen, and some questions.
For each picture:
1. "sees": what you see, 15 words at most, plain, no guessing at a story.
2. "fits": you hear those words and read them as subtitles while the picture is on screen. The picture may show the \
thing named, or what the sentence MEANS (a scene, an angle, a resemblance), or — when the words name an experience \
(a trip, a vision, a sensation) — what that person perceives, even abstract: all of these go "with" the words. \
"against" only when the picture contradicts them (another thing, another time, the opposite of what is said); "away" \
only when it pulls your attention elsewhere (a scene of something else entirely, a stock photo with nothing of the \
words in it).
3. "answers": one entry per listed question, {{"id": the question's id, "a": your answer}}. Answer literally, from the \
picture alone: yes or no, a number, or a short word. Look again at the picture for each question.
4. "look": 1 to 5, a clean, well-made picture (5 = clean; 1 = deformed hands or faces, garbled text, smeared, broken).
The pictures, in the order they appear:
{items}
Return JSON: {{"checks": [{{"file": "...", "sees": "...", "fits": "with", "answers": [{{"id": "...", "a": "..."}}], \
"look": 4}}]}}"""

FITS = ("with", "against", "away")

CHECK_SCHEMA = {"type": "object", "properties": {"checks": {"type": "array", "items": {
    "type": "object", "properties": {
        "file": {"type": "string"}, "sees": {"type": "string"}, "fits": {"type": "string", "enum": list(FITS)},
        "answers": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "a": {"type": "string"}}, "required": ["id", "a"]}},
        "look": {"type": "integer"}},
    "required": ["file", "sees", "fits", "answers", "look"]}}}, "required": ["checks"]}


# ---------------------------------------------------------------------------------------------- the questions

def _questions(spec):
    """The code-built questions of a spec: [{"id", "q", "expect"}] (shot_prompt, imported late)."""
    if not spec:
        return []
    import shot_prompt
    return list(shot_prompt.questions(spec) or [])


def _said(c, words):
    """The spoken words shown with a picture: the moment's ``said`` only (the words around its time when missing)."""
    m = c.get("m") or {}
    said = m.get("said") or (m.get("spec") or {}).get("said") or ""
    t = m.get("t", (m.get("spec") or {}).get("time"))
    if not said and t is not None:
        said = " ".join(w["text"] for w in words or [] if t - 3 <= w["start"] <= t + 4)
    return re.sub(r"\s+", " ", str(said).replace('"', "'")).strip()[:200]


def _as_dict(answers):
    """The answers as {id: value} (the model returns a list of {"id", "a"}; a dict is kept as it is)."""
    if isinstance(answers, dict):
        return dict(answers)
    out = {}
    for a in answers or []:
        if isinstance(a, dict) and a.get("id") is not None:
            out[str(a["id"])] = a.get("a", a.get("answer"))
    return out


def check(cands, words, model="sonnet"):
    """The viewer's verdict on each picture: {file basename: {"sees", "links", "answers": {qid: value}, "look"}}.
    ONE ``broll.claude_json`` call for the whole batch; {} when it fails (the caller keeps what it has)."""
    if not cands:
        return {}
    items = []
    for c in cands:
        spec = (c.get("m") or {}).get("spec") or {}
        qs = _questions(spec)
        line = f'- file "{os.path.basename(c["file"])}": heard "{_said(c, words)}"'
        if spec.get("kind") == "vision":
            # the channel's viewer knows the house rule: an experience named is shown as the person perceives it
            line += " (the words name an experience: this picture shows what the person perceives during it)"
        if qs:
            line += "\n  questions:\n" + "\n".join(f'    [{q["id"]}] {q["q"]}' for q in qs)
        items.append(line)
    small_dir = tempfile.mkdtemp(prefix="check_")
    try:
        small = []
        for c in cands:
            p = os.path.join(small_dir, os.path.basename(c["file"]))
            broll._review_still(c, broll.COLD_PX).save(p, quality=88)
            small.append(p)
        data = broll.claude_json(CHECK_PROMPT.format(items="\n".join(items)), CHECK_SCHEMA, timeout=240,
                                 attach=small, stage="broll_check", model=model)
    except Exception as e:
        print(f"   ⚠️ Check failed ({str(e)[:120]}) — the pictures are kept as they are.")
        return {}
    finally:
        shutil.rmtree(small_dir, ignore_errors=True)
    out = {}
    for r in (data or {}).get("checks") or []:
        if not isinstance(r, dict) or not r.get("file"):
            continue
        fits = r.get("fits") if r.get("fits") in FITS else ("with" if r.get("links") is not False else "away")
        out[os.path.basename(str(r["file"]))] = {
            "sees": str(r.get("sees") or "")[:200], "fits": fits, "links": fits == "with",
            "answers": _as_dict(r.get("answers")), "look": _look_of(r)}
    return out


def _look_of(r):
    look = (r or {}).get("look")
    if isinstance(look, bool) or not isinstance(look, (int, float)):
        return None
    return min(5, max(1, int(look)))


# ---------------------------------------------------------------------------------------------- grading

_YES = re.compile(r"^(yes|true|yep|yeah|yup|correct|affirmative)\b")
_NO = re.compile(r"^(no|none|false|nope|nothing|negative|nobody|not)\b")
_NO_ANY = re.compile(r"\b(no|none|nothing|nobody|neither|not|isn't|aren't|doesn't|don't|without)\b")
_NUM_WORDS = {"zero": 0, "one": 1, "single": 1, "two": 2, "couple": 2, "pair": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_MANY_WORDS = re.compile(r"\b(many|several|few|crowd|group|dozens?|numerous|lots|multiple|plenty)\b")
_PLURAL_PEOPLE = re.compile(r"\b(people|persons|men|women|children|kids|figures|silhouettes)\b")
_HANDS = re.compile(r"\b(hands?|fingers?|arms?)\b")
_WHOLE = re.compile(r"\b(face|faces|head|heads|body|bodies|torso|standing|sitting|walking|whole|full)\b")
MANY = 99


def _norm(v):
    """A lower-case, trimmed, quote-free string of an answer ("2.0" becomes "2")."""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float) and v == int(v):
        v = int(v)
    t = re.sub(r"\s+", " ", str(v if v is not None else "")).strip().lower().strip("\"'`")
    t = re.sub(r"(?<=\d)\.0+\b", "", t)
    return t.rstrip(".!, ")


_QUESTION_WORDS = frozenset("is the main subject does picture show one of two subjects are there images and a an".split())


def _names_the_thing(answer, question):
    """A descriptive answer names the thing the question asks about: two content words in common with the question's
    subject, or one when the subject has two or fewer ("law books" for "stack of four closed law volumes": stack, law)."""
    import broll
    asked = [t for t in broll._tokens(question) if t not in broll.STOPWORDS and t not in _QUESTION_WORDS]
    said = set(t for t in broll._tokens(answer) if t not in broll.STOPWORDS)
    shared = [t for t in asked if t in said or t.rstrip("s") in {s.rstrip("s") for s in said}]
    return len(shared) >= 2 or (len(asked) <= 2 and len(shared) >= 1)


def _yn(v):
    """"yes" / "no" / None (neither) of an answer."""
    t = _norm(v)
    if _YES.match(t):
        return "yes"
    if _NO.match(t):
        return "no"
    return None


def _flagged(v):
    """A "does it show ..." answer that says yes (an answer that is neither a yes nor a no counts as yes, unless it
    denies in other words)."""
    t = _norm(v)
    yn = _yn(t)
    if yn:
        return yn == "yes"
    return bool(t) and not _NO_ANY.search(t)


def _count(t):
    """The number in an answer (MANY for several / a group), None when there is none."""
    t = _norm(t)
    if re.match(r"^(no|none|nobody|nothing|zero|nil)\b", t):
        return 0
    m = re.search(r"\d+", t)
    if m:
        return int(m.group())
    for w in re.findall(r"[a-z]+", t):
        if w in _NUM_WORDS:
            return _NUM_WORDS[w]
    if _MANY_WORDS.search(t):
        return MANY
    return 1 if re.match(r"^(an?|the)\b", t) else None


def _count_ok(answer, expect):
    exp, got = _count(expect), _count(answer)
    if exp is None or got is None:
        return _norm(answer) == _norm(expect)
    return got >= 4 if exp == MANY else got == exp


def _people_kind(v):
    """("none" | "hands" | "people", n) of an answer or of an expectation."""
    t = _norm(v)
    n = _count(t)
    if n == 0:
        return "none", 0
    if _HANDS.search(t) and not _WHOLE.search(t):
        return "hands", n or 2
    if n is None:
        n = MANY if _PLURAL_PEOPLE.search(t) else 1
    return "people", n


def _people_ok(answer, expect):
    if str(expect).strip().lower() in ("yes", "no"):          # people "hands": is any other part of a person seen?
        return _norm(answer).startswith(str(expect).strip().lower())
    ek, en = _people_kind(expect)
    ak, an = _people_kind(answer)
    if ek != ak:
        return False
    return an == 1 if (ek == "people" and en == 1) else (an >= 2 if ek == "people" else True)


_MEDIA = (("scientific", ("scientific", "micrograph", "microscop", "telescop", "x-ray", "xray", "scan", "diagram")),
          ("drawing", ("drawing", "drawn", "painting", "painted", "paint", "illustrat", "sketch", "watercolo", "artwork",
                       "engraving", "ink")),
          ("photograph", ("photo", "picture", "camera", "realistic")))


def _medium(v):
    """"photograph" / "drawing" / "scientific" of an answer (a scientific image wins over a photograph of the
    instrument's screen; otherwise the first one named), "" when it is none of them."""
    t = _norm(v)
    if any(k in t for k in _MEDIA[0][1]):
        return "scientific"
    hits = [(t.find(k), fam) for fam, keys in _MEDIA[1:] for k in keys if k in t]
    return min(hits)[1] if hits else ""


def _medium_ok(answer, expect):
    e, a = _medium(expect), _medium(answer)
    if e == "scientific" and a == "photograph":
        return True                                           # a telescope's or a scanner's image is a photograph too
    return a == e if e else _norm(answer) == _norm(expect)


_IDS = ("bodyphoto", "subject", "count", "people", "text", "medium", "unsafe", "pair")


def _qkey(qid):
    """The kind of a question from its id ("q_subject", "subject", "body-photo"...), None when unknown."""
    k = re.sub(r"[^a-z]", "", re.sub(r"^q[_ -]?", "", str(qid or "").strip().lower()))
    return next((i for i in _IDS if k == i or k.startswith(i)), None)


def _aid(qid):
    return re.sub(r"[^a-z0-9]", "", str(qid or "").lower())


def grade_answers(questions, answers):
    """The viewer's answers against what the questions expect (tolerant: yes/no in any case, numbers as strings or
    words, "hands" for "2 hands", a painting for a drawing, a micrograph for a scientific image). A question that
    was not asked or not answered is not held against the picture."""
    out = {"subject_ok": True, "count_ok": True, "people_ok": True, "text_ok": True, "medium_ok": True,
           "unsafe": False, "body_photo": False, "pair_ok": True}
    got = {_aid(k): v for k, v in _as_dict(answers).items()}
    for q in questions or []:
        kind = _qkey(q.get("id"))
        a = got.get(_aid(q.get("id")))
        if kind is None or a is None or not str(a).strip():
            continue
        expect = q.get("expect")
        if kind == "unsafe":
            out["unsafe"] = _flagged(a)
        elif kind == "bodyphoto":
            out["body_photo"] = _flagged(a)
        elif kind in ("subject", "pair", "text"):
            want = _yn(expect) or ("no" if kind == "text" else "yes")
            answer = _yn(a)
            if answer is None and kind != "text":
                # a description instead of yes / no ("a stack of five law books"): yes when it names the thing asked
                answer = "yes" if _names_the_thing(a, q.get("q")) else "no"
            out["text_ok" if kind == "text" else f"{kind}_ok"] = answer == want
        elif kind == "count":
            out["count_ok"] = _count_ok(a, expect)
        elif kind == "people":
            out["people_ok"] = _people_ok(a, expect)
        elif kind == "medium":
            out["medium_ok"] = _medium_ok(a, expect)
    return out


# ---------------------------------------------------------------------------------------------- the decision

_SHAPE_WRONG = (("count_ok", "wrong count"), ("people_ok", "wrong people"), ("text_ok", "text in it"),
                ("medium_ok", "wrong medium"), ("pair_ok", "not a pair"))


def _verdict(spec, result, verdict, why, extra=""):
    """Count the filter hit (``check: <why>``) and give the verdict."""
    subject = str((spec or {}).get("subject") or "")[:60]
    sees = str((result or {}).get("sees") or "")[:80]
    broll.filter_hit(f"check: {why}", f'check: {why}{extra} → {verdict} — "{subject}", seen: "{sees}"')
    return verdict


def decide(spec, result, tries, alt_used):
    """"keep" | "rerender" | "alt" | "drop" for one picture. ``tries``: renders of this moment so far (the first
    included, budget BUDGET); ``alt_used``: the spec's alternative was already rendered. A picture nobody checked
    is dropped: an unchecked picture may be wrong or unsafe."""
    spec = spec or {}
    if not result:
        return _verdict(spec, {}, "drop", "not checked")
    g = grade_answers(_questions(spec), result.get("answers"))
    other = "alt" if spec.get("alt") and not alt_used else "drop"
    if g["unsafe"] or g["body_photo"]:
        return _verdict(spec, result, other, "unsafe" if g["unsafe"] else "body photo")
    if not g["subject_ok"]:
        # the picture missed its subject: a rendering miss, the same prompt with a new seed may hit it
        return _verdict(spec, result, "rerender" if tries < LINK_TRIES else other, "wrong subject")
    fits = result.get("fits") or ("with" if result.get("links", True) else "away")
    if fits == "away" and spec.get("kind") == "vision":
        # a vision the idea round already judged (the channel's viewer, with the principles): the picture of what a
        # person perceives may look like "nothing to do with the words" to a blind check — advisory only
        broll.filter_hit("check: a vision read as away (kept)", f'Picture "{spec.get("subject")}": the check reads it '
                                                                 f'as pulling away, a vision is kept on the idea round\'s verdict.')
    elif fits != "with":
        # the channel's viewer, the words in his ear: a picture that contradicts them or pulls him elsewhere leaves —
        # the same prompt again would do the same, so the alternative (another idea) or nothing
        return _verdict(spec, result, other, "contradicts the words" if fits == "against" else "pulls attention away")
    wrong = [why for key, why in _SHAPE_WRONG if not g[key]]
    if wrong:
        return _verdict(spec, result, "rerender" if tries < BUDGET else "drop", wrong[0],
                        f" ({', '.join(wrong)})" if len(wrong) > 1 else "")
    look = _look_of(result)
    if look is not None and look <= LOOK_BAD and tries < LINK_TRIES:
        return _verdict(spec, result, "rerender", "look", f" ({look}/5)")
    return "keep"


def _parts(take):
    """(spec, check result) of a take: {"spec", "result"} or a candidate ({"m": {"spec"}, "check"})."""
    spec = take.get("spec") or (take.get("m") or {}).get("spec") or {}
    return spec, take.get("result") or take.get("check") or {}


def pick_best(takes):
    """The best of the hero's takes: every check ok first (safe, links, the right subject, count, people, text,
    medium), then the fewest failed checks, then the look; the first one on a tie. None when there are no takes."""
    def rank(take):
        spec, r = _parts(take)
        g = grade_answers(_questions(spec), r.get("answers"))
        bad = [g["unsafe"], g["body_photo"], r.get("links") is False] + [not g[k] for k in
                                                                      ("subject_ok", "count_ok", "people_ok",
                                                                       "text_ok", "medium_ok", "pair_ok")]
        return (not any(bad), not (g["unsafe"] or g["body_photo"]), -sum(bad), _look_of(r) or 0)
    best, best_rank = None, None
    for t in takes or []:
        k = rank(t)
        if best_rank is None or k > best_rank:
            best, best_rank = t, k
    return best


def needs_reserve(kept):
    """True when fewer than MIN_PER_CLIP pictures are kept (``kept``: the list, or its length)."""
    n = kept if isinstance(kept, int) else len(kept or [])
    return n < MIN_PER_CLIP
