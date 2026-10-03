"""B-roll v20 « la fiche » (3-oct-2026): the editor fills one shot spec per picture (broll_spec), the code writes the
image prompt from it (shot_prompt, the subject first, no negation), one blind check per batch answers questions the
code builds from the spec (broll_check), and decide() keeps / renders again / takes the alternative / drops. No art
director, no register, no reviewer's prompt. broll.add_broll calls run() when cfg["chain"] == "spec"; the candidates
it returns have the old chain's shape, so the rendering is the same."""
import os

import visual_mood

MAX_ROUNDS = 4        # check rounds per clip (each round: one check call for every picture still undecided)
LAST_CHECKS = []      # every check of the last clip (the bench's board): file, moment, verdict, what was seen


def _layout(m):
    return "hero" if m.get("hero") else "card"


def _text(spec, layout):
    import broll
    import shot_prompt
    drawing = broll.episode_drawing() if spec.get("kind") == "body_inside" else ""
    return shot_prompt.build_prompt(spec, layout, drawing)


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


def _halves(spec):
    """The two specs of a pair (v21): the left thing with its own kind and details, the right one with its own. Nothing
    of one half leaks into the other (the second bench: a photographed prosthetic hand got the drawn half's "red muscle
    tissue" and came out skinned, a galaxy got the neuron's "branching threads"): no shared state, no colours from the
    mood, and the inside of a body named in a half is drawn whatever kind the director gave that half."""
    import broll_ideas
    base = {k: v for k, v in spec.items() if k not in ("alt", "subject_b", "kind_a", "kind_b", "details_b", "state")}
    mood = dict(base.get("mood") or {})
    mood.update(colours_said="", true_colours="")
    base["mood"] = mood
    left = {**base, "kind": spec.get("kind_a") or "thing", "subject": spec.get("subject"), "count": "1"}
    right = {**base, "kind": spec.get("kind_b") or "thing", "subject": spec.get("subject_b") or spec.get("subject"),
             "details": spec.get("details_b") or "", "count": "1"}
    for half in (left, right):
        if half["kind"] in ("thing", "scene", "vision", "instrument") and broll_ideas._BODY_RE.search(
                f'{half.get("subject") or ""} {half.get("details") or ""}'):
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


def _make(spec, layout, raw, render):
    """One picture of a spec -> (path or None, seed): a pair is two halves made one by one (layout "half", a square
    each) and composed by the code — Z-Image paints the same thing twice when asked for two in one frame."""
    if spec.get("kind") != "pair":
        return render(_text(spec, layout), raw, layout)
    paths, seed = [], None
    for i, half in enumerate(_halves(spec)):
        got, s = render(_text(half, "half"), raw.replace(".jpg", f"_h{i}.jpg"), "half")
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
    text = _text(spec, layout)
    if spec.get("kind") == "pair":
        a, b = _halves(spec)
        text = f"PAIR — left: {_text(a, 'half')} — right: {_text(b, 'half')}"
    m = _moment_for(m, spec, text)
    takes = broll.HERO_TAKES if layout == "hero" else 1
    out = []
    for j in range(1, takes + 1):
        raw = os.path.join(tmp, f"broll_{k}{tag}" + (f"_t{j}" if j > 1 else "") + ".jpg")
        got, seed = _make(spec, layout, raw, render)
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
            for g in group:
                LAST_CHECKS.append({"file": os.path.basename(g["file"]), "k": k, "layout": g["layout"],
                                    "checked": bool(g["check"]),
                                    "anchor": g["m"].get("anchor"), "subject": spec.get("subject"),
                                    "verdict": verdict if g is c else "other take", "score": 5 if verdict == "keep" and g is c else 2,
                                    "look": g["look_score"], "seen": (g["check"] or {}).get("sees"),
                                    "links": (g["check"] or {}).get("links"), "answers": (g["check"] or {}).get("answers"),
                                    "prompt": g["m"].get("prompt")})
            if verdict == "keep":
                c["score"] = 5
                kept.append(c)
            elif verdict == "rerender":
                raw = os.path.join(tmp, f"broll_{k}_v{c['tries'] + 1}.jpg")
                got, seed = _make(spec, c["layout"], raw, render)
                if got:
                    pending.append({**c, "file": got, "seed": seed, "tries": c["tries"] + 1, "take": None})
            elif verdict == "alt":
                alt = {**spec, **(spec.get("alt") or {})}
                alt.pop("alt", None)
                text = _text(alt, c["layout"])
                m2 = _moment_for(c["m"], alt, text)
                raw = os.path.join(tmp, f"broll_{k}_alt.jpg")
                got, seed = _make(alt, c["layout"], raw, render)
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
        ideas=False):
    """The whole v20 chain for one clip. ``render(text, out_path, layout) -> (path or None, seed)`` makes one picture
    (add_broll's ComfyUI call). ``ideas`` (v21): the round of ideas in text between the editor and the rendering
    (broll_ideas: art director, verifier, viewer; the face alone as the level zero). Under broll_check.MIN_PER_CLIP
    kept: the reserves, then the alternatives not yet rendered. Returns (cands, moments) — cands in the old chain's
    shape, the kept ones only."""
    import ai_brain
    import broll
    import broll_check
    import broll_spec
    del LAST_CHECKS[:]
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
                                                   block=block)
        if not moments:
            print("   ℹ️ B-roll v21: no idea above the face alone — no picture for this clip.")
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
    # the minimum: reserves, one at a time, until the clip has broll_check.MIN_PER_CLIP pictures
    k = len(moments)
    for m in reserves:
        if not broll_check.needs_reserve(kept):
            break
        if _too_close(m, kept):
            continue
        m = {**m, "hero": False}
        print(f'   🪫 Under the minimum ({len(kept)}): the reserve "{m["spec"].get("subject")}" is made.')
        kept += _settle(_render_moment(k, m, render, tmp, tag="r"), words, render, tmp)
        moments.append(m)
        k += 1
    # still under it: the alternatives never rendered (a picture dropped for its shape, its count or its writing never
    # reaches its alt in decide), the best worth first — the reserves' and the planned moments'. Not after a check
    # that gave no answer: its alternative would go unchecked too.
    if broll_check.needs_reserve(kept):
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
            alt = {**m["spec"], **m["spec"]["alt"]}
            alt.pop("alt", None)
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
    return kept, moments
