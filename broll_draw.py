"""B-roll v26 « dessin » (4-oct-2026) — the chain the user validated, as the production's (plus.BROLL "chain": "dessin").

  1. the editor (broll_spec, as in v20/v21) places the clip's moments and marks the hero;
  2. the art director (Opus, ONE call per clip) writes ONE idea per moment, drawn: the episode's style charter
     (.claude/skills/synapse-cut/charte.md) and its principles (directeur-banc.md) in the call, the charter's style
     sentence added word for word by the code, at the head of the picture's text (4-oct-2026);
  3. the verifier (Sonnet, ONE pass, before any picture) checks safety only: it refuses or lets pass, it gives no score;
  4. one render per moment (the hero full screen, the others as cards). No viewer, no judge, no render loop.
     5-oct-2026 (decision 5, plus.BROLL "full_width"): EVERY picture is made 9:16 and shown alone, full screen, never
     as a card on the speaker's head — the ideas and the prompts do not change, only the shape (run(..., full=True)).
  5. 5-oct-2026, dressed bodies: a person in the picture -> the code adds DRESSED to its text; every picture rendered
     is looked at (dress_check, one yes/no question on a small image): a bare body is drawn once more, then dropped.

The pictures are drawn and keep their own palette: no mood grade, no signature. Every picture made, and every idea the
verifier refused (rendered anyway, never used), goes to the clip's trace (broll_v20.trace). broll_dessin.py (the bench)
uses the same prompts."""
import os
import re

import broll_ideas

SKILL = broll_ideas.SKILL_DIR
CHARTER_FILE, PRINCIPLES_FILE = "charte.md", "directeur-banc.md"


def read(name):
    with open(os.path.join(SKILL, name), encoding="utf-8") as f:
        return f.read().strip()


def charter():
    """(the charter's text, its style sentence word for word — its first quoted line —, the director's principles);
    raises OSError when the skill's files or the style sentence are missing (the clip then gets no picture)."""
    text = read(CHARTER_FILE)
    suffix = next((line[1:].strip() for line in text.splitlines() if line.startswith("> ")), "")
    if not suffix:
        raise OSError(f"no style sentence (a line starting with '> ') in {CHARTER_FILE}")
    return text, suffix, read(PRINCIPLES_FILE)


DA_PROMPT = """You are the art director of the channel described below (its texts are in French; answer in ENGLISH).

THE CHANNEL'S PRINCIPLES (everything you propose obeys them, first of all "ce qui passe avant l'impact"):
{principes}

THE EPISODE'S STYLE CHARTER (every picture is drawn in it; the code adds the style words itself):
{charte}

YOUR PRINCIPLES (they decide how a sentence becomes a picture):
{banc}

For each sentence below you get the clip it belongs to, what was heard just before, and the sentence itself. For each
one, ONE picture, drawn in the charter: the IDEA of the sentence, never its word, the simplest symbol of it, big.
People are always drawn and anonymous; never a speaker, never a real person of the story.
The whole picture is ONE drawing, nothing in it photographic: the person and the place around them (the room, the floor,
the walls, the light) are drawn alike. So never write "drawn" about one thing alone (it makes the rest a photograph),
and describe the setting as parts of the drawing, never as a photographer would ("seen from the doorway", "daylight
through high windows", a blurred background).
For each sentence: "idea" (what it means, one line) and "picture": the drawing in plain words, 60 at most, what fills
the frame first, what it does, two or three particular details, the light. Say "a single" or "only one" for every thing
that appears once. No style word and no camera word (the code adds the charter's style), nothing to read in the
picture except a question mark when your principles ask for one, no negation in the words (say what is there).
{moments}
Return JSON: {{"moments": [{{"k": 0, "idea": "...", "picture": "..."}}]}}"""
DA_SCHEMA = {"type": "object", "properties": {"moments": {"type": "array", "items": {
    "type": "object", "properties": {"k": {"type": "integer"}, "idea": {"type": "string"},
                                     "picture": {"type": "string"}},
    "required": ["k", "idea", "picture"]}}}, "required": ["moments"]}

VERIFY_PROMPT = """You are the verifier of the channel described below (its texts are in French; answer in ENGLISH).
You check SAFETY only, in one pass, before any picture is made. You do not judge whether a picture is good, relevant or
well chosen, and you give no score: you refuse or you let it pass.

THE CHANNEL'S PRINCIPLES:
{principes}

Every picture is DRAWN in the episode's illustration style (the code adds the style words to the description): an
organ drawn whole and clean (a brain, a spine, a nerve), even with an instrument touching it, is fine, never a reason
to refuse.
Refuse a picture when:
- it is gore: a head or a body opened, a wound, blood, a cut into flesh, tissue taken out of a body;
- something in it evokes a death or its means, even as a visual cliché (a clip about a death, a sentence about deaths);
- in a clip about a death, or on a sentence that mentions a death, something in it hangs, dangles or is looped: a
  cord, a strap, a lanyard, a belt, a scarf, a cable, a tube, a rope, a lace (a badge's lanyard coiled on a desk, in a
  clip about a suicide, is one; so is anything "hanging", "swinging" or "dangling" from a line, whatever it is) —
  anywhere else, a washing line or a strap is an ordinary thing and passes;
- in a clip whose subject is a death, the dead person is shown, alive or not: such a clip shows an absence;
- it gives real victims a number or their belongings (chairs, bowls, toys, shoes, clothes of the victims);
- it shows a drug, its gear or its intake.
Otherwise let it pass. "verdict": "pass" or "refuse"; "reason": 12 words at most when you refuse.
{items}
Return JSON: {{"moments": [{{"k": 0, "verdict": "pass", "reason": ""}}]}}"""
VERIFY_SCHEMA = {"type": "object", "properties": {"moments": {"type": "array", "items": {
    "type": "object", "properties": {"k": {"type": "integer"}, "verdict": {"type": "string", "enum": ["pass", "refuse"]},
                                     "reason": {"type": "string"}},
    "required": ["k", "verdict", "reason"]}}}, "required": ["moments"]}


# Dressed bodies (5-oct-2026, the user: « et pour ce qui est des corps presque nus ? faut faire quelque chose »).
# Z-Image undresses a person as soon as something must be shown "inside" the body — on job b8e46c24: a woman in
# underwear in a scanner, a man under a sheet, a bare shoulder for a needle — though no prompt asked for it. Safety,
# not the invention of the ideas: whenever the picture has a person in it, the code adds a dressing sentence after the
# director's picture (the charter's style sentence stays first, word for word) — DRESSED_PATIENT when someone lies
# down or the inside of a body is shown (on the demo, "everyday clothes" turned such a patient into a crop top or
# underwear, the closed gown dressed them), DRESSED otherwise (a gown there moved a needle scene to a clinic and added
# people). Every picture rendered is then looked at (dress_check: one yes/no question on a small image) and drawn
# once more with DRESSED_MORE added and another seed when a body is bare — then dropped if it still is.
DRESSED = ("Anyone in this scene is fully dressed in everyday clothes that cover them from the neck to the knees; for an "
           "injection only one sleeve is rolled up to the elbow; anything inside a body is drawn through the clothes.")
DRESSED_PATIENT = ("Anyone in this scene is fully dressed: a patient wears a closed long-sleeved hospital gown from the "
                   "neck to the knees, anyone else their usual clothes; anything inside a body is drawn through the "
                   "gown.")
DRESSED_MORE = "The clothes stay closed from the neck to the knees; a glow inside a body shows as light on the fabric."
LYING_RE = re.compile(r"\b(lies|lying|lay|laid|patients?|scanner|scan|mri|x-ray|stretcher|gurney|hospital beds?|"
                      r"operating table|exam(?:ination)? table|abdomen|bell(?:y|ies)|stomach|organs?|"
                      r"inside (?:the|her|his|a|their) bod(?:y|ies))\b", re.I)
PERSON_RE = re.compile(
    r"\b(persons?|people|man|men|woman|women|child|children|kids?|boys?|girls?|bab(?:y|ies)|toddlers?|teen\w*|"
    r"adults?|patients?|doctors?|nurses?|surgeons?|athletes?|figures?|someone|somebody|anyone|crowd|audience|"
    r"players?|swimmers?|runners?|fighters?|soldiers?|workers?|students?|mothers?|fathers?|parents?|"
    r"bod(?:y|ies)|torsos?|chests?|bell(?:y|ies)|abdomen|stomach|shoulders?|arms?|he|she|him|his|her|hers)\b", re.I)


def has_person(picture):
    """The director's picture puts a person (or a body) in the scene."""
    return bool(PERSON_RE.search(picture or ""))


def picture_text(suffix, picture, more=False):
    """The text the image model gets: the charter's style first (4-oct-2026, the user: a drawn man in a photographed
    room, sometimes all photographed — the model reads the medium before the scene), then the director's picture,
    then — a person in it — the dressing sentence (5-oct-2026: DRESSED_PATIENT for someone lying or a body seen inside,
    else DRESSED; ``more``: DRESSED_MORE added, the redraw of a bare body)."""
    text = f"{suffix} {picture}"
    if more or has_person(picture):
        text += " " + (DRESSED_PATIENT if LYING_RE.search(picture or "") else DRESSED)
        if more:
            text += " " + DRESSED_MORE
    return text


DRESS_PROMPT = """Look at this drawing. Answer true ONLY if a person in it is undressed: naked, in underwear, a bra, a
swimsuit or a crop top that leaves the belly bare, lying with nothing on under a sheet, or with bare skin on the chest,
the belly, the back or the top of the shoulders. Anyone wearing a top (a T-shirt, scrubs, a sweater, a shirt with an
open collar, a hospital gown) is dressed, even with a sleeve rolled up, and even when a glow, a light or an organ is
drawn over or through the clothes: that is not skin. Hands, arms, the neck, the face and the legs do not count.
Nobody in it: false.
Return JSON: {"bare": true or false, "what": "<8 words at most: who is bare and where, else empty>"}"""
DRESS_SCHEMA = {"type": "object", "properties": {"bare": {"type": "boolean"}, "what": {"type": "string"}},
                "required": ["bare", "what"]}
DRESS_PX = 512        # the drawing's longer side as the check sees it: a body reads at that size, and it costs little


def dress_check(path, tmp):
    """(bare, what) for a rendered picture: True / False, or None when no answer came. One small image, one yes/no
    question, Sonnet at low effort (Haiku if Sonnet fails). Measured (5-oct-2026, output/_stepup/chantier/L2) on 62
    labelled drawings — job b8e46c24's 34, its 3 bare originals, 25 redraws of the hard cases: every bare body found
    (8/8), 3 dressed patients out of 47 called bare (a glow drawn on a gown read as skin: one redraw for nothing),
    ~980 tokens an image. Haiku, before the question said what a top is, flagged 6 dressed people out of 31; at 768 px
    instead of 512 Sonnet did no better."""
    import broll
    from PIL import Image
    thumb = os.path.join(tmp, "dress_" + os.path.basename(path))
    try:
        im = Image.open(path).convert("RGB")
        im.thumbnail((DRESS_PX, DRESS_PX), Image.LANCZOS)
        im.save(thumb, quality=88)
    except Exception as e:
        return None, f"unreadable ({str(e)[:60]})"
    model = broll_ideas._model("broll_dress", "sonnet")
    for m in dict.fromkeys((model, "haiku")):
        try:
            data = broll.claude_json(DRESS_PROMPT, DRESS_SCHEMA, timeout=120, attach=[thumb], stage="broll_dress",
                                     model=m, effort="low") or {}
        except Exception as e:
            print(f"   ⚠️ Dress check on {m} failed ({str(e)[:100]}).")
            continue
        if isinstance(data.get("bare"), bool):
            return data["bare"], re.sub(r"\s+", " ", str(data.get("what") or "")).strip()[:80]
    return None, "no answer"


def direct_and_verify(sentences, title=None):
    """The art director's call then the verifier's pass for ``sentences`` = [(clip title, heard before, sentence)] ->
    ([{"idea", "picture"} or {}], [{"verdict", "reason"}], style suffix)."""
    text, suffix, banc = charter()
    q = broll_ideas._q
    lines = [f'k={k} — clip "{q(t, 20)}"\n  heard just before: "{q(b)}"\n  SENTENCE: "{q(s)}"'
             for k, (t, b, s) in enumerate(sentences)]
    principes = broll_ideas.skill_text("principes")
    data = broll_ideas._call(DA_PROMPT.format(principes=principes, charte=text, banc=banc, moments="\n".join(lines)),
                             DA_SCHEMA, "broll_ideas", broll_ideas._model("broll_ideas", "opus"),
                             effort=os.environ.get("CLAUDE_EFFORT_BROLL_IDEAS") or "high")
    got = {m["k"]: m for m in (data or {}).get("moments") or [] if isinstance(m, dict) and isinstance(m.get("k"), int)}
    ideas = []
    for k in range(len(sentences)):
        m = got.get(k) or {}
        ideas.append({"idea": str(m.get("idea") or ""), "picture": re.sub(r"\s+", " ", str(m.get("picture") or "")).strip()})
    items = [f'k={k} — clip "{q(t, 20)}"; sentence: "{q(s)}"\n  picture: "{q(ideas[k]["picture"], 70)}"'
             for k, (t, _b, s) in enumerate(sentences) if ideas[k]["picture"]]
    verdicts = [{"verdict": "refuse", "reason": "no picture"} for _ in sentences]
    if items:
        checked = broll_ideas._call(VERIFY_PROMPT.format(principes=principes, items="\n".join(items)), VERIFY_SCHEMA,
                                    "broll_verify", broll_ideas._model("broll_verify", "sonnet"), effort="medium")
        for m in (checked or {}).get("moments") or []:
            if isinstance(m, dict) and isinstance(m.get("k"), int) and 0 <= m["k"] < len(sentences):
                verdicts[m["k"]] = {"verdict": "pass" if m.get("verdict") == "pass" else "refuse",
                                    "reason": broll_ideas._q(m.get("reason"), 14)}
        for k in range(len(sentences)):
            if ideas[k]["picture"] and verdicts[k]["reason"] == "no picture":
                verdicts[k] = {"verdict": "refuse", "reason": "not answered by the verifier"}
    return ideas, verdicts, suffix


def _dressed(k, got, seed, text, suffix, picture, layout, entry, tmp, render):
    """The dress check of a picture about to be kept (5-oct-2026) -> (path, seed, text, how). Nobody bare: kept as is.
    A bare body: drawn once more with DRESSED_MORE and another seed, kept if that one is dressed, else (None, ...): no
    picture. No answer from the check: kept only when the picture names nobody. Every picture set aside goes to the
    clip's trace, refused, with why."""
    import broll
    import broll_v20

    def refuse(path, s, why, prompt=None):
        broll_v20.LAST_CHECKS.append({**entry, "prompt": prompt or entry.get("prompt"), "file": os.path.basename(path),
                                      "verdict": "refused", "why": why, "seed": s})

    bare, what = dress_check(got, tmp)
    if bare is False:
        return got, seed, text, "ok"
    if bare is None:
        if not has_person(picture):
            return got, seed, text, f"not checked ({what}), nobody named"
        broll.filter_hit("v26: dress not checked, a person in it — dropped")
        refuse(got, seed, f"dress not checked ({what})")
        return None, None, text, "not checked"
    broll.filter_hit("v26: bare body, drawn again dressed", f"Picture {k}: {what}.")
    refuse(got, seed, f"bare body: {what} (drawn again)")
    text2 = picture_text(suffix, picture, more=True)
    got2, seed2 = render(text2, os.path.join(tmp, f"broll_{k}_dressed.jpg"), layout)
    if got2:
        bare2, what2 = dress_check(got2, tmp)
        if bare2 is False:
            print(f"   👕 B-roll: picture {k} drawn again, dressed (the first one: {what}).")
            return got2, seed2, text2, f"ok on the second drawing (the first: {what})"
        refuse(got2, seed2, f"bare body again: {what2}" if bare2 else f"dress not checked ({what2})", text2)
    broll.filter_hit("v26: bare body, dropped")
    print(f"   🚫 B-roll: picture {k} dropped — a bare body ({what}), drawn twice.")
    return None, None, text, "bare"


def run(clip_path, clip, words, transcript, start, end, n, avoid, head, tail, gap_min, block, dur_range, tmp, render,
        full=False):
    """The v26 chain for one clip; ``render(text, out_path, layout) -> (path or None, seed)`` is add_broll's. Returns
    (cands, moments) in broll_v20.run's shape — the kept pictures only.
    ``full`` (5-oct-2026, decision 5 « dessins en pleine largeur », plus.BROLL "full_width"): every picture is made in
    the hero's 9:16 and shown alone, full screen — the same ideas and prompts, only the shape changes. A moment with no
    room before the punchline (broll.full_room) is not rendered; a vertical render that fails is made again as the
    old card (a card rather than nothing)."""
    import broll
    import broll_spec
    import broll_v20
    del broll_v20.LAST_CHECKS[:]
    broll_v20.LESSON_CTX.update(clip_title=str(clip.get("video_title_for_youtube_short") or "")[:120])
    try:
        sheets = broll._frame_sheets(clip_path, tmp)
    except Exception as e:
        print(f"   ⚠️ B-roll frame sheets failed ({e}) — the editor plans from the words only.")
        sheets = []
    moments, _reserves = broll_spec.plan_specs(clip, words, n, avoid, transcript=transcript, start=start, end=end,
                                               sheets=sheets, head=head, tail=tail, gap_min=gap_min, block=block,
                                               dur_range=dur_range, ideas=True)
    if not moments:
        return [], []
    title = str(clip.get("video_title_for_youtube_short") or "")
    sentences = []
    for m in moments:
        said, before, _after = broll_ideas._around(words, float(m["t"]))
        sentences.append((title, before, said or m.get("said") or ""))
    try:
        ideas, verdicts, suffix = direct_and_verify(sentences)
    except OSError as e:
        print(f"   ⚠️ B-roll v26: the style charter is missing ({e}) — no picture for this clip.")
        return [], []
    kept = []
    for k, m in enumerate(moments):
        idea, v = ideas[k], verdicts[k]
        layout = broll_v20._layout(m, full)
        if not idea["picture"]:
            broll.filter_hit("v26: no idea from the art director")
            continue
        text = picture_text(suffix, idea["picture"])
        entry = {"k": k, "anchor": m.get("anchor"), "said": sentences[k][2], "idea": idea["idea"], "prompt": text,
                 "layout": layout}
        if v["verdict"] == "pass" and full and not broll.full_room(m, avoid):
            # full screen hides the face: the punchline is said on the face, so no room means no picture
            broll.filter_hit("v26: no room before the punchline (full width)",
                             f'Moment "{m.get("anchor")}" at {float(m["t"]):.1f} s: under {broll.HERO_DUR_MIN:g} s '
                             f'before the punchline — no picture.')
            continue
        if v["verdict"] == "pass":
            got, seed = render(text, os.path.join(tmp, f"broll_{k}.jpg"), layout)
            if not got and layout == "hero" and full:
                # the vertical render failed: the old card rather than nothing
                broll.filter_hit("v26: vertical not made, card instead")
                layout = entry["layout"] = "card"
                got, seed = render(text, os.path.join(tmp, f"broll_{k}_card.jpg"), layout)
            if not got:
                broll.filter_hit("v26: not made (ComfyUI)")
                continue
            got, seed, text, dressed = _dressed(k, got, seed, text, suffix, idea["picture"], layout, entry, tmp, render)
            if not got:
                continue
            entry.update(prompt=text, dress=dressed)
            m2 = broll_v20._moment_for(m, m["spec"], text)
            # drawn in the charter: its own palette (no mood grade, no signature), never the episode's drawing
            m2.update(mood=None, inside_body=False, idea_text=idea["idea"], picture=idea["picture"])
            c = broll_v20._new_cand(k, m2, layout, got, seed)
            c.update(verdict="keep", score=5)
            kept.append(c)
            broll_v20.LAST_CHECKS.append({**entry, "file": os.path.basename(got), "verdict": "keep", "why": "",
                                          "seed": seed})
        else:
            # refused: rendered anyway for the trace (the user: « toujours les traces des images refusées »), never used
            broll.filter_hit("v26: refused by the verifier")
            path = None
            if os.environ.get("BROLL_TRACE", "1") != "0":
                path, seed = render(text, os.path.join(tmp, f"refused_{k}.jpg"), "card")
            broll_v20.LAST_CHECKS.append({**entry, "file": os.path.basename(path) if path else "", "verdict": "refused",
                                          "why": v["reason"], "seed": seed if path else None})
    broll.LAST_PICTURED[:] = moments
    kept.sort(key=lambda c: float(c["m"]["t"]))
    print(f"   🖍️ B-roll v26 « dessin »: {len(kept)} drawn of {len(moments)} moments"
          + (f", {sum(1 for v in verdicts if v['verdict'] != 'pass')} refused by the verifier" if verdicts else ""))
    broll_v20.trace(clip_path, clip, tmp, kept)
    return kept, moments
