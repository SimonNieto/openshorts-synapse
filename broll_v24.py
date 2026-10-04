"""B-roll v24 « on juge des images » (4-oct-2026) — the bench only; production stays on v21 + v22 until the user
validates a version by its name.

The v23 bench measured that the text round's ranking does not predict the picture (correlation -0.14): v24 judges
pictures, not sentences.

  1. TEXT: the art director (Opus) gives up to three ideas of different natures for each moment, each in its own words
     ("picture", its prose); the verifier (Sonnet) checks them — safety, a negation, a set phrase taken literally. No
     ranking, no moment dropped for "nothing above the face alone".
  2. RENDER: every idea that passed is made (a card each; a pair's two halves one by one) through the store
     (broll_store: the seed comes from the prompt, a picture already made is read back with no GPU), the first idea of
     every moment first, so a GPU cap cuts the third ideas before the first ones.
  3. MECHANICAL CHECK (broll_check.check): the subject is there, nothing unsafe, no body photographed, no writing, the
     count, who is in the frame, the medium, the look. A picture that fails is out, never rendered again.
  4. THE VIEWER CHOOSES (Sonnet, sees the pictures): four questions on every PICTURE (does it show the word instead of
     the idea, is it the first stock photo, a setting instead of the idea, does it contradict the idea?), then the
     pictures with four "no" ranked with the face alone; the first one before the face wins the moment. It also says
     whether that picture could fill the whole screen.
  5. THE HERO, among the winners (the director's hero_ok, the viewer's "full screen", the timing rules), is made again
     full screen from the same idea.
  6. THE VERIFIER SEES THE WINNERS (Sonnet): its checklist on the picture itself; a refused picture gives its place to
     the next one the viewer ranked before the face, else the face alone.

Caps per clip (CAP_GPU_S, CAP_TOKENS) are shown in the result; no render loop anywhere."""
import os
import re
import shutil
import tempfile
import time

import broll
import broll_check
import broll_ideas
import broll_v20

FACE = "face"
FLAWS4 = ("repeats", "stock", "setting", "contradicts")
YES_NO = ("yes", "no")
CAP_GPU_S = float(os.environ.get("BROLL_V24_GPU_CAP") or 300)       # seconds of GPU a clip may spend
CAP_TOKENS = int(os.environ.get("BROLL_V24_TOKEN_CAP") or 120000)    # tokens (read + written) a clip may spend
VERIFY_ROUNDS = 2                                                    # winners seen by the verifier, then their next
LOOK_BAD = broll_check.LOOK_BAD
JUDGE_PX = broll.COLD_PX                                             # the judges' pictures, one size for all


def _model(stage, default):
    return (os.environ.get(f"BRAIN_{stage.upper()}") or default).lower()


# --- the prompts -------------------------------------------------------------------------------------------------------
_ENGINE_V24 = """WHAT THE ENGINE (Z-Image) DRAWS BADLY: it falls back to the icon of the strongest word (a brain comes out whole, a
galaxy as a spiral); it does not follow a scale ("macro", "thousands of tiny"), a precise position ("in the opening",
"coiled on a hook", "folded into the pocket") nor "the same shape / structure" between two things. Every idea is made
and judged on its picture: write each one so that it holds whatever the engine does.
"""
_RULES_V24 = """TWO RULES FOR EVERY IDEA:
- When the thing named IS the point, the picture shows it WHOLE, doing what the sentence says, with whoever does it; a
  detail may sharpen it, never replace it (a close-up of one part, or the thing left alone once the act is over, loses
  what the sentence tells).
- Name what must be SEEN, in "picture" as in the render fields, never the instrument that shows it nor the category it
  belongs to: the engine draws the words it gets, an instrument named comes out as that instrument, a category as its
  usual icon.
Every idea is made and shown to the viewer next to the others: its "picture" stands on its own, whole.
"""
_INSTRUMENT_OLD = ('"instrument" is for a KNOWN kind of image (a scan, a telescope frame, a fluorescence micrograph of\n'
                   '     whole cells);')
_INSTRUMENT_NEW = ('"instrument" is for a KNOWN kind of image (a scan, a micrograph): its "subject" and "picture" name\n'
                   '     what that image SHOWS, never the instrument;')
DA_PROMPT_V24 = (broll_ideas._DA_TEXT.replace("<<PICTURE_B>>", broll_ideas.PICTURE_B_ASK)
                 .replace("<<ENGINE>>", _ENGINE_V24 + _RULES_V24).replace(_INSTRUMENT_OLD, _INSTRUMENT_NEW))

_NEGATION_OLD = "no figure of speech taken literally;"
_NEGATION_NEW = ("no figure of speech or set phrase taken literally; nothing the sentence denies (when it says a thing "
                 "did not happen or had nothing to do with it, that thing is not in the picture);")
VERIFIER_PROMPT_V24 = broll_ideas.VERIFIER_PROMPT.replace(_NEGATION_OLD, _NEGATION_NEW)

CHOOSE_PROMPT = """You are the viewer of the channel described below (its text is in French; answer in ENGLISH).
You scroll Shorts with the sound on: you HEAR the voice and READ the subtitles. You know NOTHING of the episode, the
context or the team's intentions: only the words and the picture count. The calibration tells you what fails; a
picture that copies one of its landmarks earns nothing for it.

THE CHANNEL'S PRINCIPLES:
{principes}

THE CALIBRATION:
{calibrage}
{lessons}
For each sentence below you get the subtitle you read while a picture is on screen, what you heard just before, and
the pictures made for it (attached above, each under its file name). The IDEA of a sentence is what it means to you,
not the words it uses. You give no score. Look at each picture as it IS, never as it was meant to be.
FIRST, for every picture: "sees" (what you see, 12 words at most), then "yes" or "no" to each question, without mercy:
"repeats": does it show the WORD of the sentence instead of its idea?
"stock": is it the first picture a stock-photo bank would give for these words?
"setting": is it a setting (a room, a place, a background) instead of the idea?
"contradicts": does it contradict the idea (it shows the opposite, or what the sentence denies)?
THEN, for each sentence, rank together the pictures with four "no" and the FACE ALONE ("{face}": the speaker's face,
no picture): "order" lists their file names, best first, with "{face}" placed where the face alone stands — every
picture after "{face}" is worse than no picture. A picture with one "yes" is never ranked. And "full_screen": "yes"
when the picture you rank first could fill the whole phone screen for three seconds and hold you, else "no".
{moments}
Return JSON: {{"moments": [{{"k": 0, "views": [{{"file": "c0_0.jpg", "sees": "...", "repeats": "no", "stock": "no", \
"setting": "no", "contradicts": "no"}}], "order": ["c0_0.jpg", "{face}"], "full_screen": "no"}}]}}"""

POST_VERIFY_PROMPT = """You are the verifier of the channel described below (its text is in French; answer in ENGLISH).
You are strict and literal: a doubt is flagged, never forgiven. The channel's principles decide; the calibration tells
you what fails and why.

THE CHANNEL'S PRINCIPLES:
{principes}

THE CALIBRATION:
{calibrage}
{lessons}
THE CLIP: title "{title}", hook "{hook}". Clip gravity: {gravity} ("grave" = a death is the clip's subject: every
picture is an absence, nobody in the frame, never the means; "real" = a death, an illness or a loss is mentioned).
Speakers, never pictured: {speakers}.
Each picture below (attached above, under its file name) will be on screen while its subtitle is read. Check the
PICTURE itself — what is in it, not what it was meant to be — against the checklist: no real or recognisable person (an
anonymous stranger passes); nothing that evokes a death or its means, even as a visual cliché; in a grave clip nobody
in the frame and nothing hanging, draped or looped (a belt, a strap, a tie, a scarf, a cord, a cable, a tube, a lace);
no drug taken, prepared or shown itself (pills, powder, crystals, a syringe, a pipe); the inside of a body drawn,
never photographed; nothing to read; no gore; no figure of speech or set phrase taken literally; nothing the sentence
denies; nothing that goes against a fact said.
For every picture: "sees" (10 words at most), "verdict" ("pass" or "refuse"), "reason" (12 words at most).
{items}
Return JSON: {{"checks": [{{"file": "c0_0.jpg", "sees": "...", "verdict": "pass", "reason": ""}}]}}"""

_STR = {"type": "string"}
CHOOSE_SCHEMA = {"type": "object", "properties": {"moments": {"type": "array", "items": {
    "type": "object", "properties": {
        "k": {"type": "integer"},
        "views": {"type": "array", "items": {"type": "object", "properties": {
            "file": _STR, "sees": _STR, **{f: {"type": "string", "enum": list(YES_NO)} for f in FLAWS4}},
            "required": ["file", "sees", *FLAWS4]}},
        "order": {"type": "array", "items": _STR},
        "full_screen": {"type": "string", "enum": list(YES_NO)}},
    "required": ["k", "views", "order", "full_screen"]}}}, "required": ["moments"]}
POST_VERIFY_SCHEMA = {"type": "object", "properties": {"checks": {"type": "array", "items": {
    "type": "object", "properties": {"file": _STR, "sees": _STR, "verdict": {"type": "string", "enum": ["pass", "refuse"]},
                                     "reason": _STR},
    "required": ["file", "sees", "verdict", "reason"]}}}, "required": ["checks"]}


# --- helpers -----------------------------------------------------------------------------------------------------------
def _yes_no(v):
    s = str(v).strip().lower().rstrip(".!") if v is not None else ""
    return "yes" if s in ("yes", "y", "true") else "no" if s in ("no", "n", "false") else None


def _name(x):
    """A file name as the judges write it: its base name, lower case, no quotes."""
    return os.path.basename(str(x or "").strip().strip("\"'`")).lower()


def _small(paths, folder):
    """The judges' copies of ``paths`` (JUDGE_PX at most), same base names, in ``folder``."""
    from PIL import Image
    out = []
    for p in paths:
        im = Image.open(p).convert("RGB")
        im.thumbnail((JUDGE_PX, JUDGE_PX))
        q = os.path.join(folder, os.path.basename(p))
        im.save(q, quality=88)
        out.append(q)
    return out


def _tokens_now():
    import ai_brain
    return int(ai_brain.USAGE["input_tokens"]) + int(ai_brain.USAGE["output_tokens"])


def ranked_before_face(order, clean):
    """The files of ``clean`` the viewer ranked before the face alone, in its order (each once); a file it did not
    rank, or ranked after the face, is not there."""
    out = []
    for x in order or []:
        x = _name(x)
        if x == FACE:
            break
        if x in clean and x not in out:
            out.append(x)
    return out


# --- 1. the text: the director and the verifier --------------------------------------------------------------------------
def text_round(moments, clip, words, gravity, clip_text):
    """-> one record per moment: {"k", "anchor", "t", "said", "idea", "role", "why", "cands": [{"i", "title",
    "picture", "picture_b", "adds", "hero_ok", "verdict", "reason", "flaw", "refused", "spec"}]}. A candidate keeps a
    spec (its own prose under "picture") only when the code and the verifier let it through."""
    directed = broll_ideas._direct(moments, words, clip, gravity, (), prompt=DA_PROMPT_V24)
    ideas = {k: list((directed.get(k) or {}).get("ideas") or []) for k in range(len(moments))}
    specs, refused = {}, {}
    for k, m in enumerate(moments):
        for i, idea in enumerate(ideas[k]):
            spec, why = broll_ideas._spec_of(m, idea, clip_text, gravity)
            if spec:
                specs[(k, i)] = spec
            else:
                refused[(k, i)] = f"code: {why}"
                broll.filter_hit(f"v24: {why} (code)")
    live = {k: [idea if (k, i) in specs else None for i, idea in enumerate(ideas[k])] for k in ideas}
    verdicts = {}
    if any(any(v) for v in live.values()):
        verdicts = broll_ideas._verify(moments, words, clip, gravity, live, prompt=VERIFIER_PROMPT_V24)
    for (k, i), v in verdicts.items():
        if (k, i) not in specs:
            continue
        if v["verdict"] == "refuse":
            refused[(k, i)] = f"verifier: {v['reason']}"
            broll.filter_hit("v24: refused by the verifier (text)")
        elif v["verdict"] == "fix" and v["details"]:
            specs[(k, i)]["details"] = v["details"]
    records = []
    for k, m in enumerate(moments):
        d = directed.get(k) or {}
        said, before, _after = broll_ideas._around(words, float(m["t"]))
        cands = []
        for i, idea in enumerate(ideas[k]):
            v = verdicts.get((k, i)) or {}
            spec = specs.get((k, i)) if (k, i) not in refused else None
            if spec is not None:
                spec["picture"] = str(idea.get("picture") or "").strip()      # its own prose, never another's
            cands.append({"i": i, "title": idea.get("title"), "picture": idea.get("picture"),
                          "picture_b": broll_ideas._pair_b(idea), "adds": idea.get("adds"),
                          "hero_ok": idea.get("hero_ok") is True, "kind": (spec or {}).get("kind") or idea.get("kind"),
                          "verdict": v.get("verdict") or ("refused by the code" if (k, i) in refused else "pass"),
                          "reason": v.get("reason") or "", "flaw": v.get("flaw") or "", "refused": refused.get((k, i)),
                          "spec": spec})
        records.append({"k": k, "anchor": m.get("anchor"), "t": float(m["t"]), "said": said or m.get("said"),
                        "before": before, "idea": d.get("idea"), "role": d.get("role"),
                        "why": d.get("why") if not ideas[k] else "", "cands": cands})
    return records


# --- 2. the render -----------------------------------------------------------------------------------------------------
def _prompt_text(m, spec, layout):
    prose, prose_b = broll_v20._prose(m, spec)
    if spec.get("kind") == "pair":
        a, b = broll_v20._halves(spec, prose, prose_b)
        return (f"PAIR — left: {broll_v20._text(a, 'half', a.get('picture'))} — right: "
                f"{broll_v20._text(b, 'half', b.get('picture'))}"), prose, prose_b
    return broll_v20._text(spec, layout, prose), prose, prose_b


def render_all(records, moments, render, tmp, dry=False):
    """Every candidate with a spec made as a card (c<k>_<i>.jpg), the first ideas of all the moments first. Sets the
    candidate's "prompt", "file" (None when not made: dry, the GPU cap, ComfyUI) and "seed"."""
    order = sorted(((c["i"], r["k"], c) for r in records for c in r["cands"] if c["spec"]), key=lambda x: (x[0], x[1]))
    for _i, k, c in order:
        m = moments[k]
        text, prose, prose_b = _prompt_text(m, c["spec"], "card")
        c["prompt"] = text
        raw = os.path.join(tmp, f"c{k}_{c['i']}.jpg")
        got, seed = broll_v20._make(c["spec"], "card", raw, render, prose, prose_b)
        c.update(file=got, seed=seed, layout="card")
        if not got and not dry:
            broll.filter_hit("v24: not made (GPU cap or ComfyUI)")


# --- 3. the mechanical check -------------------------------------------------------------------------------------------
def _mech_why(spec, r):
    """Why a checked picture is out ("" when it passes): what the code guarantees, never a taste."""
    if not r:
        return "not checked"
    g = broll_check.grade_answers(broll_check._questions(spec), r.get("answers"))
    if g["unsafe"]:
        return "unsafe"
    if g["body_photo"]:
        return "body photo"
    if not g["subject_ok"]:
        return "wrong subject"
    for key, why in broll_check._SHAPE_WRONG:
        if not g[key]:
            return why
    look = r.get("look")
    if isinstance(look, int) and not isinstance(look, bool) and look <= LOOK_BAD:
        return f"look {look}/5"
    return ""


def mechanical(items, words, model=None):
    """``items``: [{"file", "m" (the moment), "spec"}] -> {file name: {"why", "check"}} (one broll_check call, one
    retry when it gives nothing; an unchecked picture is out)."""
    if not items:
        return {}
    model = model or _model("broll_mech", "sonnet")
    cands = [{"file": it["file"], "m": {**it["m"], "spec": it["spec"]}} for it in items]
    results = broll_check.check(cands, words, model=model) or broll_check.check(cands, words, model=model)
    out = {}
    for it in items:
        r = results.get(os.path.basename(it["file"])) or {}
        out[_name(it["file"])] = {"why": _mech_why(it["spec"], r), "check": r}
    return out


# --- 4. the viewer chooses ---------------------------------------------------------------------------------------------
def _choose_lines(groups):
    lines = []
    for g in groups:
        names = ", ".join(f'"{_name(f)}"' for f in g["files"])
        lines.append(f'SENTENCE k={g["k"]}: subtitle "{broll_ideas._q(g["said"])}"; heard just before: '
                     f'"{broll_ideas._q(g.get("before"))}"\n  pictures: {names}')
    return "\n".join(lines)


def choose(groups, reuse=True, model=None):
    """The viewer on the PICTURES. ``groups``: [{"k", "said", "before", "files": [paths]}] (every file name unique) ->
    {k: {"views": {file name: {"sees", "flags": {flaw: yes/no/None}}}, "order": [names, FACE among them],
    "full_screen": "yes"/"no"/None}}. ``reuse=False``: never the remembered answer (the bench's stability)."""
    groups = [g for g in groups if g.get("files")]
    if not groups:
        return {}
    model = model or _model("broll_choose", "sonnet")
    prompt = CHOOSE_PROMPT.format(principes=broll_ideas.skill_text("principes"),
                                  calibrage=broll_ideas.skill_text("calibrage"), face=FACE,
                                  lessons=broll_ideas._lessons("judges"), moments=_choose_lines(groups))
    folder = tempfile.mkdtemp(prefix="v24_choose_")
    try:
        small = _small([f for g in groups for f in g["files"]], folder)
        data = broll.claude_json(prompt, CHOOSE_SCHEMA, timeout=300, attach=small, stage="broll_choose", model=model,
                                 effort="medium", reuse=reuse) or {}
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    out = {}
    for mm in data.get("moments") or []:
        if not (isinstance(mm, dict) and isinstance(mm.get("k"), int)):
            continue
        views = {_name(v.get("file")): {"sees": broll_ideas._q(v.get("sees"), 14),
                                        "flags": {f: _yes_no(v.get(f)) for f in FLAWS4}}
                 for v in mm.get("views") or [] if isinstance(v, dict) and v.get("file")}
        out[mm["k"]] = {"views": views, "order": [_name(x) for x in mm.get("order") or []],
                        "full_screen": _yes_no(mm.get("full_screen"))}
    return out


def verdict_of(view, order):
    """(winner file name or FACE, [names ranked before the face with four "no"]) of one sentence's answer."""
    views = (view or {}).get("views") or {}
    clean = [f for f, v in views.items() if not [x for x in FLAWS4 if (v.get("flags") or {}).get(x) == "yes"]]
    ranked = ranked_before_face(order if order is not None else (view or {}).get("order"), clean)
    return (ranked[0] if ranked else FACE), ranked


# --- 6. the verifier on the pictures -----------------------------------------------------------------------------------
def post_verify(entries, clip, gravity, reuse=True, model=None):
    """``entries``: [{"file", "said", "before", "flags": [..]}] -> {file name: {"verdict", "reason", "sees"}}; a picture
    the verifier did not answer for is refused (an unchecked picture may be unsafe)."""
    if not entries:
        return {}
    model = model or _model("broll_postverify", "sonnet")
    lines = []
    for e in entries:
        extra = "".join(f" [{f}]" for f in e.get("flags") or [])
        lines.append(f'- "{_name(e["file"])}": subtitle "{broll_ideas._q(e["said"])}"; heard just before '
                     f'"{broll_ideas._q(e.get("before"))}"{extra}')
    cl = broll_ideas._clip_lines(clip, gravity)
    prompt = POST_VERIFY_PROMPT.format(principes=broll_ideas.skill_text("principes"),
                                       calibrage=broll_ideas.skill_text("calibrage"),
                                       lessons=broll_ideas._lessons("judges"), items="\n".join(lines),
                                       title=cl["title"], hook=cl["hook"], gravity=gravity, speakers=cl["speakers"])
    folder = tempfile.mkdtemp(prefix="v24_verify_")
    try:
        small = _small([e["file"] for e in entries], folder)
        data = broll.claude_json(prompt, POST_VERIFY_SCHEMA, timeout=300, attach=small, stage="broll_postverify",
                                 model=model, effort="medium", reuse=reuse) or {}
    except Exception as e:
        print(f"   ⚠️ v24: the verifier on the pictures failed ({str(e)[:120]}) — every picture refused.")
        data = {}
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    got = {_name(c.get("file")): c for c in data.get("checks") or [] if isinstance(c, dict)}
    out = {}
    for e in entries:
        c = got.get(_name(e["file"])) or {}
        verdict = c.get("verdict") if c.get("verdict") in ("pass", "refuse") else "refuse"
        out[_name(e["file"])] = {"verdict": verdict, "reason": broll_ideas._q(c.get("reason") or
                                                                              ("" if c else "not answered"), 14),
                                 "sees": broll_ideas._q(c.get("sees"), 12)}
    return out


def _flags_of(m, spec, gravity):
    out = []
    if gravity == "grave":
        out.append("a clip about a death")
    if (spec or {}).get("death_near"):
        out.append("the sentence mentions a death")
    if (spec or {}).get("substance") or (spec or {}).get("intake"):
        out.append("a drug is named: never shown")
    return out


# --- 5. the hero -------------------------------------------------------------------------------------------------------
def pick_hero(records, moments, words, avoid, head, block):
    """The moment whose winner is made full screen: the director's hero_ok, the viewer's "full screen", the timing
    rules (broll.hero_fits); the editor's hero mark and the second part of the clip as bonuses. None: cards only."""
    duration = float(words[-1]["end"]) if words else 0.0
    best, best_score = None, 0.0
    for r in records:
        c = r.get("winner_cand")
        if not c or not c.get("hero_ok") or r.get("full_screen") != "yes" or c.get("kind") == "pair":
            continue
        m = moments[r["k"]]
        if m.get("notion") or not broll.hero_fits(m, duration, avoid, head, block):
            continue
        score = 1.0 + (1.0 if m.get("hero") else 0.0) + (0.5 if float(m["t"]) > duration * 0.35 else 0.0)
        if best is None or score > best_score:
            best, best_score = r["k"], score
    return best


# --- the whole chain ---------------------------------------------------------------------------------------------------
def run_moments(moments, clip, words, gravity, render, tmp, avoid=(), head=0.0, block=(), dry=False, mech_model=None,
                gpu_spent=None):
    """The v24 chain on ready moments (each with "t", "anchor", "said", "spec", "mood", "dur", "hero"). ``render``:
    broll_store.renderer(...) (its ``spent`` holds the GPU seconds). ``dry``: stops after the prompts. -> the record
    {"moments": [...], "hero", "gpu_s", "tokens", "calls", "seconds", "capped"}."""
    import ai_brain
    t0, tok0, calls0 = time.time(), _tokens_now(), int(ai_brain.USAGE["calls"])
    seconds = {}
    clip_text = " ".join(w["text"] for w in words)
    saved_prose = broll_v20.PROSE
    broll_v20.PROSE = True
    capped = []
    try:
        t = time.time()
        records = text_round(moments, clip, words, gravity, clip_text)
        seconds["text"] = round(time.time() - t, 1)
        t = time.time()
        render_all(records, moments, render, tmp, dry=dry)
        seconds["render"] = round(time.time() - t, 1)
        if dry:
            return _result(records, None, t0, tok0, calls0, seconds, render, capped, dry=True)
        # 3. the mechanical check
        t = time.time()
        made = [(r, c) for r in records for c in r["cands"] if c.get("file")]
        mech = mechanical([{"file": c["file"], "m": moments[r["k"]], "spec": c["spec"]} for r, c in made], words,
                          mech_model)
        for _r, c in made:
            got = mech.get(_name(c["file"])) or {"why": "not checked", "check": {}}
            c["mech"] = {"why": got["why"], "sees": (got["check"] or {}).get("sees"),
                         "look": (got["check"] or {}).get("look"), "answers": (got["check"] or {}).get("answers"),
                         "fits": (got["check"] or {}).get("fits"), "score": (got["check"] or {}).get("score")}
            if got["why"]:
                broll.filter_hit(f"v24 mechanical: {got['why']}")
        seconds["mechanical"] = round(time.time() - t, 1)
        # 4. the viewer chooses among the pictures that passed
        t = time.time()
        groups = []
        for r in records:
            files = [c["file"] for c in r["cands"] if c.get("file") and not (c.get("mech") or {}).get("why")]
            groups.append({"k": r["k"], "said": r["said"], "before": r.get("before"), "files": files})
        views = choose(groups)
        seconds["choose"] = round(time.time() - t, 1)
        by_name = {_name(c["file"]): (r, c) for r in records for c in r["cands"] if c.get("file")}
        for r in records:
            v = views.get(r["k"]) or {}
            r["view_order"] = v.get("order") or []
            r["full_screen"] = v.get("full_screen")
            winner, ranked = verdict_of(v, None)
            r["ranked"], r["winner"] = ranked, winner
            for c in r["cands"]:
                if c.get("file"):
                    vv = (v.get("views") or {}).get(_name(c["file"])) or {}
                    c["view"] = {"sees": vv.get("sees"), "flags": vv.get("flags"),
                                 "rank": ranked.index(_name(c["file"])) + 1 if _name(c["file"]) in ranked else None}
            r["winner_cand"] = by_name[winner][1] if winner in by_name else None
            if not any(g["files"] for g in groups if g["k"] == r["k"]):
                r["winner"] = FACE
        # 5. the hero, made full screen from the winning idea
        hero_k = pick_hero(records, moments, words, avoid, head, block)
        hero_file = None
        if hero_k is not None and _tokens_now() - tok0 < CAP_TOKENS:
            t = time.time()
            r = records[hero_k]
            c = r["winner_cand"]
            text, prose, prose_b = _prompt_text({**moments[hero_k], "hero": True}, c["spec"], "hero")
            raw = os.path.join(tmp, f"h{hero_k}_{c['i']}.jpg")
            got, seed = broll_v20._make(c["spec"], "hero", raw, render, prose, prose_b)
            if got:
                hm = mechanical([{"file": got, "m": moments[hero_k], "spec": c["spec"]}], words, mech_model)
                why = (hm.get(_name(got)) or {}).get("why", "not checked")
                r["hero_render"] = {"file": got, "prompt": text, "seed": seed, "mech": why}
                if not why:
                    hero_file = got
            seconds["hero"] = round(time.time() - t, 1)
        elif hero_k is not None:
            capped.append("hero (tokens)")
        # 6. the verifier on the winners (the hero's full-screen picture first), then on the next ones
        t = time.time()
        chains = {}
        for r in records:
            chain = ([hero_file] if hero_file and r["k"] == hero_k else []) + [by_name[n][1]["file"] for n in r["ranked"]]
            chains[r["k"]] = chain
            r["post"] = {}
        pos = {k: 0 for k in chains}
        for rnd in range(VERIFY_ROUNDS):
            entries = []
            for r in records:
                ch, p = chains[r["k"]], pos[r["k"]]
                if p < len(ch) and r.get("final") is None:
                    spec = (r["winner_cand"] or {}).get("spec") if p == 0 else None
                    entries.append({"file": ch[p], "said": r["said"], "before": r.get("before"), "k": r["k"],
                                    "flags": _flags_of(moments[r["k"]], spec or moments[r["k"]].get("spec"), gravity)})
            if not entries:
                break
            if rnd > 0 and _tokens_now() - tok0 >= CAP_TOKENS:
                capped.append("verifier's second round (tokens)")
                break
            got = post_verify(entries, clip, gravity)
            for e in entries:
                r = records[e["k"]]
                v = got.get(_name(e["file"])) or {"verdict": "refuse", "reason": "not answered"}
                r["post"][_name(e["file"])] = v
                if v["verdict"] == "pass":
                    r["final"] = e["file"]
                else:
                    broll.filter_hit("v24: refused by the verifier (picture)")
                    pos[e["k"]] += 1
        for r in records:
            if r.get("final") is None:
                r["final"] = FACE
            r["final_layout"] = ("hero" if hero_file and r["final"] == hero_file else
                                 "card" if r["final"] != FACE else None)
        seconds["verify"] = round(time.time() - t, 1)
        return _result(records, hero_k if hero_file else None, t0, tok0, calls0, seconds, render, capped)
    finally:
        broll_v20.PROSE = saved_prose


def _result(records, hero_k, t0, tok0, calls0, seconds, render, capped, dry=False):
    import ai_brain
    for r in records:
        r.pop("winner_cand", None)
        for c in r["cands"]:
            c["spec"] = {k: v for k, v in (c.get("spec") or {}).items() if k != "alt"} if c.get("spec") else None
    spent = float((getattr(render, "spent", None) or [0.0])[0])
    tokens = _tokens_now() - tok0
    if spent >= CAP_GPU_S:
        capped.append("GPU")
    return {"moments": records, "hero": hero_k, "dry": dry, "gpu_s": round(spent, 1), "gpu_cap": CAP_GPU_S,
            "tokens": tokens, "token_cap": CAP_TOKENS, "calls": int(ai_brain.USAGE["calls"]) - calls0,
            "seconds": {**seconds, "total": round(time.time() - t0, 1)}, "capped": capped}


def summary_line(res):
    """One line a person reads: pictures kept, the hero, GPU and tokens against their caps."""
    kept = [r for r in res["moments"] if r.get("final") not in (None, FACE)]
    made = sum(1 for r in res["moments"] for c in r["cands"] if c.get("file"))
    return (f"{len(kept)}/{len(res['moments'])} moment(s) with a picture, {made} made, hero "
            f"{'k=' + str(res['hero']) if res.get('hero') is not None else 'none'}; GPU {res['gpu_s']:.0f}/"
            f"{res['gpu_cap']:.0f} s, tokens {res['tokens']:,}/{res['token_cap']:,}, {res['calls']} call(s), "
            f"{res['seconds'].get('total', 0):.0f} s" + (f" — capped: {', '.join(res['capped'])}" if res["capped"] else ""))
