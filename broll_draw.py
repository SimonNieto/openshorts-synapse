"""B-roll v26 « dessin » (4-oct-2026) — the chain the user validated, as the production's (plus.BROLL "chain": "dessin").

  1. the editor (broll_spec, as in v20/v21) places the clip's moments and marks the hero;
  2. the art director (Opus, ONE call per clip) writes ONE idea per moment, drawn: the episode's style charter
     (.claude/skills/synapse-cut/charte.md) and its principles (directeur-banc.md) in the call, the charter's style
     sentence added word for word by the code, at the head of the picture's text (4-oct-2026);
  3. the verifier (Sonnet, ONE pass, before any picture) checks safety only: it refuses or lets pass, it gives no score;
  4. one render per moment (the hero full screen, the others as cards). No viewer, no judge, no render loop.

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
    """(the charter's text, its style suffix word for word, the director's principles); raises OSError when the skill's
    files are missing."""
    text = read(CHARTER_FILE)
    suffix = next(line[1:].strip() for line in text.splitlines() if line.startswith("> Premium"))
    return text, suffix, read(PRINCIPLES_FILE)


DA_PROMPT = """You are the art director of the channel described below (its texts are in French; answer in ENGLISH).

THE CHANNEL'S PRINCIPLES (everything you propose obeys them, first of all "ce qui passe avant l'impact"):
{principes}

THE EPISODE'S STYLE CHARTER (every picture is drawn in it; the code adds the style words itself):
{charte}

YOUR PRINCIPLES (they decide how a sentence becomes a picture):
{banc}

{lessons}For each sentence below you get the clip it belongs to, what was heard just before, and the sentence itself. For each
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


def direct_and_verify(sentences, title=None, lessons=False):
    """The art director's call then the verifier's pass for ``sentences`` = [(clip title, heard before, sentence)] ->
    ([{"idea", "picture"} or {}], [{"verdict", "reason"}], style suffix). ``lessons``: the owner's kept lessons
    (broll_teach) go into the director's call; off, the call is word for word the one before them."""
    text, suffix, banc = charter()
    q = broll_ideas._q
    lines = [f'k={k} — clip "{q(t, 20)}"\n  heard just before: "{q(b)}"\n  SENTENCE: "{q(s)}"'
             for k, (t, b, s) in enumerate(sentences)]
    principes = broll_ideas.skill_text("principes")
    taught = ""
    if lessons:
        import broll_teach
        taught = broll_teach.director_block(os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
        if taught:
            print(f"   🎓 B-roll v26: the art director reads {taught.count(chr(10) + '- ')} lesson(s) of the owner.")
    data = broll_ideas._call(DA_PROMPT.format(principes=principes, charte=text, banc=banc, lessons=taught,
                                              moments="\n".join(lines)),
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


def run(clip_path, clip, words, transcript, start, end, n, avoid, head, tail, gap_min, block, dur_range, tmp, render,
        lessons=False):
    """The v26 chain for one clip; ``render(text, out_path, layout) -> (path or None, seed)`` is add_broll's. Returns
    (cands, moments) in broll_v20.run's shape — the kept pictures only."""
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
        ideas, verdicts, suffix = direct_and_verify(sentences, lessons=lessons)
    except OSError as e:
        print(f"   ⚠️ B-roll v26: the style charter is missing ({e}) — no picture for this clip.")
        return [], []
    kept = []
    for k, m in enumerate(moments):
        idea, v = ideas[k], verdicts[k]
        layout = broll_v20._layout(m)
        if not idea["picture"]:
            broll.filter_hit("v26: no idea from the art director")
            continue
        # The style first (4-oct-2026, the user: a drawn man in a photographed room, sometimes all photographed): the
        # image model reads the medium before the scene, so the room is drawn with the person.
        text = f'{suffix} {idea["picture"]}'
        entry = {"k": k, "anchor": m.get("anchor"), "said": sentences[k][2], "idea": idea["idea"], "prompt": text,
                 "layout": layout}
        if v["verdict"] == "pass":
            got, seed = render(text, os.path.join(tmp, f"broll_{k}.jpg"), layout)
            if not got:
                broll.filter_hit("v26: not made (ComfyUI)")
                continue
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
