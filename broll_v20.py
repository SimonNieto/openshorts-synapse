"""B-roll v20 « la fiche » (3-oct-2026): the editor fills one shot spec per picture (broll_spec), the code writes the
image prompt from it (shot_prompt, the subject first, no negation), one blind check per batch answers questions the
code builds from the spec (broll_check), and decide() keeps / renders again / takes the alternative / drops. No art
director, no register, no reviewer's prompt. broll.add_broll calls run() when cfg["chain"] == "spec"; the candidates
it returns have the old chain's shape, so the rendering is the same.
PROSE mode (v24, the bench: run(..., prose=True)): the image prompt starts from the art director's own picture of the
idea (the moment's "picture", a pair's right half "picture_b"; shot_prompt.build_prompt(prose=...)); off in production."""
import os
import re

import visual_mood

MAX_ROUNDS = 4        # check rounds per clip (each round: one check call for every picture still undecided)
LAST_CHECKS = []      # every check of the last clip (the bench's board): file, moment, verdict, what was seen
LESSON_CTX = {}       # what the lessons journal notes with every picture of the clip being made (its title)
PROSE = False         # v24: the prompt starts from the art director's picture (set by run(..., prose=); the bench only)


def _lesson(c, verdict, why):
    """One event of the lessons journal (broll_lessons) for a picture decided after the render."""
    import broll_lessons
    m, spec, r = c.get("m") or {}, (c.get("m") or {}).get("spec") or {}, c.get("check") or {}
    broll_lessons.record({"source": "check", "verdict": verdict, "why": why or "", "kind": spec.get("kind"),
                          "role": m.get("role") or spec.get("role"), "flaw": m.get("idea_flaw") or "",
                          "score": r.get("score"), "look": r.get("look"), "fits": r.get("fits"),
                          "subject": str(spec.get("subject") or "")[:80], "title": str(m.get("picture") or "")[:120],
                          "said": str(m.get("said") or "")[:120], "layout": c.get("layout"),
                          "clip_title": LESSON_CTX.get("clip_title") or ""})


def _layout(m, full=False):
    """The picture's family: the clip's one hero full screen, the others cards — or every one full screen (``full``,
    the « dessin » chain in full width, 5-oct-2026: never a card on the head)."""
    return "hero" if full or m.get("hero") else "card"


def _text(spec, layout, prose=None):
    """The image prompt of a spec; ``prose``: the art director's picture of it (PROSE mode), None: its fields."""
    import broll
    import shot_prompt
    drawing = broll.episode_drawing() if spec.get("kind") == "body_inside" else ""
    return shot_prompt.build_prompt(spec, layout, drawing, prose=prose)


def _prose(m, spec):
    """(prose, prose_b): the art director's picture of ``spec`` (a spec of the moment ``m``) and of a pair's right
    half — (None, None) unless PROSE: production makes the prompt from the fields. The chosen idea's picture is the
    moment's "picture" (unless the spec carries its own); the right half's is the pair's "picture_b". An alternative
    carries its own (_alt), "" when it has none: never the first idea's picture. Around a death, each one goes through
    the nets its fields went through (_grave_safe)."""
    if not PROSE:
        return None, None
    m, spec = m or {}, spec or {}
    if spec.get("picture") is not None:
        a, b = spec.get("picture") or None, spec.get("picture_b") or None
    else:
        a, b = m.get("picture") or None, spec.get("picture_b") or m.get("picture_b") or None
    mood = spec.get("mood") if isinstance(spec.get("mood"), dict) else {}
    if m.get("clip_gravity") == "grave" or spec.get("death_near") or mood.get("gravity") == "grave":
        a, b = _grave_safe(a), _grave_safe(b)
    return a, b


def _grave_safe(prose):
    """A picture's prose in a clip about a death, or on a sentence that mentions one, under the house's nets its fields
    went through (broll_ideas._spec_of): what hangs goes (_HANG_RE); a strap-like thing (_STRAP_RE) and the prose is not
    used — its fields, which the code checked, make the prompt."""
    import broll_ideas
    if not prose:
        return None
    if broll_ideas._STRAP_RE.search(prose):
        return None
    return re.sub(r"\s{2,}", " ", broll_ideas._HANG_RE.sub("", prose)).strip(" ,") or None


def _alt(spec):
    """The alternative's spec: the chosen one under the alternative's own fields. PROSE mode: it carries its own
    picture ("" when it has none, so its fields make its prompt), never the first idea's."""
    own = spec.get("alt") or {}
    alt = {**spec, **own}
    alt.pop("alt", None)
    if PROSE:
        alt["picture"], alt["picture_b"] = own.get("picture") or "", own.get("picture_b") or ""
    return alt


def _moment_for(m, spec, text):
    """The moment as the rendering and the report read it, from its spec."""
    import shot_prompt
    m = {**m, "spec": spec}
    m.update(prompt=text, query=spec.get("subject") or m.get("anchor"), subject=spec.get("subject"),
             judge=shot_prompt.judge_line(spec), people=spec.get("people") or "none",
             inside_body=spec.get("kind") == "body_inside", mood=visual_mood.clean(spec.get("mood") or m.get("mood")),
             style="photo", art=True)
    return m


def _new_cand(k, m, layout, path, seed, take=None):
    c = {"k": k, "m": m, "style": "photo", "file": path, "source": "local", "credit": None, "layout": layout,
         "seed": seed, "model": "turbo", "tries": 1, "alt_used": False, "score": 0, "look_score": 0}
    if take:
        c["take"] = take
    return c


PAIR_GUTTER = 8       # px between the two halves of a pair
# "Left: A. Right: B." — a pair's picture written for both halves at once (the director of the third bench)
_SIDES = re.compile(r"^\s*(?:on\s+the\s+)?left(?:\s+(?:half|side|image))?\s*:\s*(?P<a>.+?)\s*[.;,]\s*"
                    r"(?:on\s+the\s+)?right(?:\s+(?:half|side|image))?\s*:\s*(?P<b>.+)$", re.I | re.S)
_SIDE_LABEL = re.compile(r"^\s*(?:on\s+the\s+)?(?:left|right)(?:\s+(?:half|side|image))?\s*(?::|\s[—–-]\s)\s*", re.I)


def _pair_proses(prose, prose_b):
    """(left, right): the art director's picture of each half of a pair, its "Left:" / "Right:" label dropped. A
    "Left: A. Right: B." picture is split between the halves (the right one's own "picture_b" wins); a picture of the
    whole pair with no "picture_b" is neither half's (both keep their fields, as before)."""
    a, b = str(prose or "").strip() or None, str(prose_b or "").strip() or None
    sides = _SIDES.match(a) if a else None
    if sides:
        a, b = sides.group("a"), b or sides.group("b")
    elif not b:
        a = None
    return tuple(_SIDE_LABEL.sub("", x, count=1).strip() or None if x else None for x in (a, b))


def _halves(spec, prose=None, prose_b=None):
    """The two specs of a pair (v21): the left thing with its own kind and details, the right one with its own. Nothing
    of one half leaks into the other (the second bench: a photographed prosthetic hand got the drawn half's "red muscle
    tissue" and came out skinned, a galaxy got the neuron's "branching threads"): no shared state, no colours from the
    mood, and the inside of a body named in a half is drawn whatever kind the director gave that half.
    PROSE mode: ``prose`` / ``prose_b`` (the moment's "picture", the pair's "picture_b": _prose) — each half carries its
    own picture under "picture" (_pair_proses; none: its fields make its prompt) and the net reads it too."""
    import broll_ideas
    base = {k: v for k, v in spec.items() if k not in ("alt", "subject_b", "kind_a", "kind_b", "details_b", "state",
                                                        "picture", "picture_b")}
    mood = dict(base.get("mood") or {})
    mood.update(colours_said="", true_colours="")
    base["mood"] = mood
    left = {**base, "kind": spec.get("kind_a") or "thing", "subject": spec.get("subject"), "count": "1"}
    right = {**base, "kind": spec.get("kind_b") or "thing", "subject": spec.get("subject_b") or spec.get("subject"),
             "details": spec.get("details_b") or "", "count": "1"}
    for half, own in zip((left, right), _pair_proses(prose, prose_b)):
        if own:
            half["picture"] = own
        if half["kind"] in ("thing", "scene", "vision", "instrument") and broll_ideas._BODY_RE.search(
                f'{half.get("subject") or ""} {half.get("details") or ""} {own or ""}'):
            half["kind"], half["instrument"] = "body_inside", ""
        if half["kind"] in ("instrument", "body_inside"):
            half["setting"] = "plain"
        half["people"], half["person"] = ("none", "none") if half["kind"] != "scene" else (half.get("people"), half.get("person"))
    return left, right


def _compose_pair(paths, layout, out):
    """Two square halves side by side (a card) or one above the other (a hero), each centre-cropped, a thin gutter."""
    import broll
    from PIL import Image
    W, H = broll._gen_size(layout)
    if layout == "hero":
        hw, hh = W, (H - PAIR_GUTTER) // 2
    else:
        hw, hh = (W - PAIR_GUTTER) // 2, H
    canvas = Image.new("RGB", (W, H), (8, 8, 8))
    for i, p in enumerate(paths):
        im = Image.open(p).convert("RGB")
        scale = max(hw / im.width, hh / im.height)
        im = im.resize((max(hw, round(im.width * scale)), max(hh, round(im.height * scale))), Image.LANCZOS)
        x0, y0 = (im.width - hw) // 2, (im.height - hh) // 2
        im = im.crop((x0, y0, x0 + hw, y0 + hh))
        canvas.paste(im, (0, i * (hh + PAIR_GUTTER)) if layout == "hero" else (i * (hw + PAIR_GUTTER), 0))
    canvas.save(out, quality=92)
    return out


def _make(spec, layout, raw, render, prose=None, prose_b=None):
    """One picture of a spec -> (path or None, seed): a pair is two halves made one by one (layout "half", a square
    each) and composed by the code — Z-Image paints the same thing twice when asked for two in one frame.
    ``prose`` / ``prose_b``: the art director's pictures (PROSE mode, _prose); None: the fields."""
    if spec.get("kind") != "pair":
        return render(_text(spec, layout, prose), raw, layout)
    paths, seed = [], None
    for i, half in enumerate(_halves(spec, prose, prose_b)):
        got, s = render(_text(half, "half", half.get("picture")), raw.replace(".jpg", f"_h{i}.jpg"), "half")
        if not got:
            return None, None
        paths.append(got)
        seed = seed if seed is not None else s
    return _compose_pair(paths, layout, raw), seed


def _render_moment(k, m, render, tmp, tag=""):
    """The first render(s) of a moment: the hero gets broll.HERO_TAKES takes of its prompt."""
    import broll
    layout = _layout(m)
    spec = m["spec"]
    prose, prose_b = _prose(m, spec)
    if spec.get("kind") == "pair":
        a, b = _halves(spec, prose, prose_b)
        text = f"PAIR — left: {_text(a, 'half', a.get('picture'))} — right: {_text(b, 'half', b.get('picture'))}"
    else:
        text = _text(spec, layout, prose)
    m = _moment_for(m, spec, text)
    takes = broll.HERO_TAKES if layout == "hero" else 1
    out = []
    for j in range(1, takes + 1):
        raw = os.path.join(tmp, f"broll_{k}{tag}" + (f"_t{j}" if j > 1 else "") + ".jpg")
        got, seed = _make(spec, layout, raw, render, prose, prose_b)
        if got:
            out.append(_new_cand(k, m, layout, got, seed, take=j if takes > 1 else None))
    return out


def _settle(cands, words, render, tmp):
    """Check, decide, render again, until every candidate is kept or dropped. Returns the kept ones."""
    import broll
    import broll_check
    pending, kept = list(cands), []
    for _round in range(MAX_ROUNDS):
        if not pending:
            break
        results = broll_check.check(pending, words) or broll_check.check(pending, words)   # one retry: no result = dropped
        # the hero's takes: the best one stays, the others leave before any decision
        by_k = {}
        for c in pending:
            r = results.get(os.path.basename(c["file"])) or {}
            c["check"] = r
            c["look_score"] = int(r.get("look") or 0)
            by_k.setdefault(c["k"], []).append(c)
        pending = []
        for k, group in by_k.items():
            c = group[0] if len(group) == 1 else broll_check.pick_best(group)
            if len(group) > 1:
                print(f"   🎬 Hero: take {c.get('take')} kept of {len(group)}.")
            spec = c["m"]["spec"]
            verdict = broll_check.decide(spec, c["check"], c["tries"], c["alt_used"])
            c["verdict"] = verdict
            if verdict != "rerender":
                # the lesson of this picture (v22): kept with its score, or dropped with its reason; an "alt" is the
                # first idea's failure
                _lesson(c, "drop" if verdict in ("alt", "drop") else "keep", broll_check.LAST_WHY if verdict != "keep" else "")
            for g in group:
                LAST_CHECKS.append({"file": os.path.basename(g["file"]), "k": k, "layout": g["layout"],
                                    "checked": bool(g["check"]),
                                    "anchor": g["m"].get("anchor"), "subject": spec.get("subject"),
                                    "verdict": verdict if g is c else "other take", "score": 5 if verdict == "keep" and g is c else 2,
                                    "look": g["look_score"], "viewer": (g["check"] or {}).get("score"),
                                    "seen": (g["check"] or {}).get("sees"),
                                    "links": (g["check"] or {}).get("links"), "answers": (g["check"] or {}).get("answers"),
                                    "prompt": g["m"].get("prompt"), "seed": g.get("seed"),
                                    "why": (broll_check.LAST_WHY if verdict != "keep" else "") if g is c else ""})
            if verdict == "keep":
                c["score"] = 5
                kept.append(c)
            elif verdict == "rerender":
                raw = os.path.join(tmp, f"broll_{k}_v{c['tries'] + 1}.jpg")
                got, seed = _make(spec, c["layout"], raw, render, *_prose(c["m"], spec))
                if got:
                    pending.append({**c, "file": got, "seed": seed, "tries": c["tries"] + 1, "take": None})
            elif verdict == "alt":
                alt = _alt(spec)
                prose, prose_b = _prose(c["m"], alt)
                text = _text(alt, c["layout"], prose)
                m2 = _moment_for(c["m"], alt, text)
                raw = os.path.join(tmp, f"broll_{k}_alt.jpg")
                got, seed = _make(alt, c["layout"], raw, render, prose, prose_b)
                if got:
                    pending.append({**c, "m": m2, "file": got, "seed": seed, "tries": c["tries"] + 1,
                                    "alt_used": True, "take": None})
            # "drop": nothing more (decide already counted it)
    for c in pending:
        broll.filter_hit("check: out of rounds", f'Picture "{c["m"].get("anchor")}" still undecided after '
                                                  f'{MAX_ROUNDS} checks — dropped.')
    return kept


def _too_close(m, kept):
    import broll
    return any(abs(float(m["t"]) - float(c["m"]["t"])) < broll.MIN_GAP for c in kept)


def run(clip_path, clip, words, transcript, start, end, n, avoid, head, tail, gap_min, block, dur_range, tmp, render,
        ideas=False, reserve_mode="none", prose=False, judge=None, shown=None):
    """The whole v20 chain for one clip. ``render(text, out_path, layout) -> (path or None, seed)`` makes one picture
    (add_broll's ComfyUI call). ``ideas`` (v21): the round of ideas in text between the editor and the rendering
    (broll_ideas: art director, verifier, viewer; the face alone as the level zero). ``reserve_mode``: "none" (production:
    a weak picture harms more than no picture, the face alone wins, no picture is made to reach a count), "quota"
    (the bench's older versions: under broll_check.MIN_PER_CLIP kept, the reserves, then the alternatives not yet
    rendered) or "above_face" (the bench's v23: every reserve whose idea passed the face alone is made, never for a
    count). ``prose`` (v24, the bench; sets PROSE for the clip): the image prompt starts from the art director's own
    picture of the idea, not from its fields. Returns (cands, moments) — cands in the old chain's shape, the kept ones
    only."""
    import ai_brain
    import broll
    import broll_check
    import broll_spec
    global PROSE
    PROSE = bool(prose)
    del LAST_CHECKS[:]
    LESSON_CTX.update(clip_title=str(clip.get("video_title_for_youtube_short") or "")[:120])
    try:
        sheets = broll._frame_sheets(clip_path, tmp)
    except Exception as e:
        print(f"   ⚠️ B-roll frame sheets failed ({e}) — the editor plans from the words only.")
        sheets = []
    moments, reserves = broll_spec.plan_specs(clip, words, n, avoid, transcript=transcript, start=start, end=end,
                                              sheets=sheets, head=head, tail=tail, gap_min=gap_min, block=block,
                                              dur_range=dur_range, ideas=ideas)
    if not moments:
        return [], []
    if ideas:
        import broll_ideas
        gravity = moments[0].get("clip_gravity") or "none"
        moments, reserves = broll_ideas.idea_round(moments, reserves, clip, words, gravity,
                                                   " ".join(w["text"] for w in words), avoid=avoid, head=head,
                                                   block=block, judge=judge, shown=shown)
        if not moments:
            print("   ℹ️ B-roll v21: no idea above the face alone — no picture for this clip.")
            trace(clip_path, clip, tmp, [], ideas)     # the ideas refused, all of them
            return [], []
    base = visual_mood.base([visual_mood.clean(m.get("mood")) for m in moments],
                            visual_mood.episode_levels(ai_brain.EPISODE_BIBLE))
    for m in moments + reserves:
        m["mood_base"] = base
    print(f"   🗂️ Specs: " + " | ".join(f'{m["spec"].get("kind")}: {m["spec"].get("subject")}'
                                        + (" (hero)" if m.get("hero") else "") for m in moments)
          + (f" — {len(reserves)} in reserve" if reserves else ""))
    broll.LAST_PICTURED[:] = moments
    cands = []
    for k, m in enumerate(moments):
        cands += _render_moment(k, m, render, tmp)
    kept = _settle(cands, words, render, tmp) if cands else []
    mode = reserve_mode if reserve_mode in ("none", "quota", "above_face") else "none"
    k = len(moments)
    if mode == "above_face":
        # the bench's v23: a reserve whose idea passed the face alone is a picture like the others, never a filler
        for m in reserves:
            if _too_close(m, kept):
                continue
            m = {**m, "hero": False}
            print(f'   ➕ Reserve above the face alone: "{m["spec"].get("subject")}" is made.')
            kept += _settle(_render_moment(k, m, render, tmp, tag="r"), words, render, tmp)
            moments.append(m)
            k += 1
    for m in (reserves if mode == "quota" else []):
        # the bench's older versions: the minimum, reserves one at a time until broll_check.MIN_PER_CLIP pictures
        if not broll_check.needs_reserve(kept):
            break
        if _too_close(m, kept):
            continue
        m = {**m, "hero": False}
        print(f'   🪫 Under the minimum ({len(kept)}): the reserve "{m["spec"].get("subject")}" is made.')
        kept += _settle(_render_moment(k, m, render, tmp, tag="r"), words, render, tmp)
        moments.append(m)
        k += 1
    # still under it (quota only): the alternatives never rendered (a picture dropped for its shape, its count or its
    # writing never reaches its alt in decide), the best worth first — the reserves' and the planned moments'. Not
    # after a check that gave no answer: its alternative would go unchecked too.
    if mode == "quota" and broll_check.needs_reserve(kept):
        last = {e["k"]: e for e in LAST_CHECKS}
        done = ({e["k"] for e in LAST_CHECKS if e.get("verdict") == "alt"} | {c["k"] for c in kept}
                | {j for j, e in last.items() if not e.get("checked")})
        pool = [(j, m) for j, m in enumerate(moments) if j not in done and (m.get("spec") or {}).get("alt")]
        pool.sort(key=lambda jm: (-float(jm[1].get("score") or jm[1]["spec"].get("worth") or 1), float(jm[1]["t"])))
        for _j, m in pool:
            if not broll_check.needs_reserve(kept):
                break
            if _too_close(m, kept):
                continue
            alt = _alt(m["spec"])
            m = {**m, "spec": alt, "hero": False}
            print(f'   🪫 Under the minimum ({len(kept)}): the alternative "{alt.get("subject")}" is made.')
            kept += _settle(_render_moment(k, m, render, tmp, tag="a"), words, render, tmp)
            moments.append(m)
            k += 1
    broll.LAST_PICTURED[:] = moments
    kept.sort(key=lambda c: float(c["m"]["t"]))
    # a reserve may come up 3 s after a kept picture: the earlier one leaves before it
    lo = (dur_range or (broll.CARD_DUR_MIN, broll.CARD_DUR_MAX))[0]
    for a, b in zip(kept, kept[1:]):
        room = float(b["m"]["t"]) - float(a["m"]["t"]) - broll.DUR_NEXT_GAP
        if float(a["m"].get("dur") or 0) > room:
            a["m"]["dur"] = round(max(lo, room), 2)
    print(f"   🔎 B-roll v20: {len(kept)} kept of {len(moments)} moments — "
          + ", ".join(f'{c["m"].get("anchor")}: {c["verdict"]} (look {c["look_score"]})' for c in kept))
    trace(clip_path, clip, tmp, kept, ideas)
    return kept, moments


TRACE_DIR = "_broll_trace"     # output/_broll_trace/<date>_<job8>/<clip>/: every picture a job made, kept or refused


def trace(clip_path, clip, tmp, kept, ideas=False):
    """The clip's trace (4-oct-2026, the user: « qu'on ait toujours les traces des images refusées »): every picture
    the clip made — kept, refused, the hero's other take — copied with its prompt, its seed, the check's answers and
    the verdict with its reason (trace.json), plus the round of ideas (the ideas refused before any picture). Under
    output/_broll_trace (a ``.keep`` keeps it out of the job clean-up). Changes nothing the job shows; never raises;
    BROLL_TRACE=0 switches it off."""
    if os.environ.get("BROLL_TRACE", "1") == "0":
        return None
    if not LAST_CHECKS:
        try:
            import broll_ideas
            if not (ideas and broll_ideas.LAST_IDEAS):
                return None
        except Exception:
            return None
    import json
    import shutil
    import time
    try:
        job_dir = os.path.dirname(os.path.abspath(clip_path))
        root = os.path.join(os.path.dirname(job_dir), TRACE_DIR)
        folder = os.path.join(root, f"{time.strftime('%Y-%m-%d')}_{os.path.basename(job_dir)[:8]}",
                              os.path.splitext(os.path.basename(clip_path))[0])
        os.makedirs(folder, exist_ok=True)
        open(os.path.join(root, ".keep"), "a").close()
        kept_files = {os.path.basename(c["file"]) for c in kept}
        pictures = []
        for e in LAST_CHECKS:
            src = os.path.join(tmp, e["file"])
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(folder, e["file"]))
            pictures.append({**e, "kept": e["file"] in kept_files})
        rounds = []
        if ideas:
            import broll_ideas
            rounds = [dict(r) for r in broll_ideas.LAST_IDEAS]
        with open(os.path.join(folder, "trace.json"), "w", encoding="utf-8") as f:
            json.dump({"clip": str(clip.get("video_title_for_youtube_short") or ""), "made": time.strftime("%Y-%m-%d %H:%M"),
                       "pictures": pictures, "ideas": rounds}, f, ensure_ascii=False, indent=1, default=str)
        refused = sum(1 for p in pictures if not p["kept"])
        print(f"   🗃️ B-roll trace: {len(pictures)} picture(s), {refused} not kept -> {folder}")
        return folder
    except Exception as e:
        print(f"   ⚠️ B-roll trace not written ({str(e)[:120]}).")
        return None
