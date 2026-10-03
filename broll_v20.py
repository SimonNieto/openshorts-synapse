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


def _render_moment(k, m, render, tmp, tag=""):
    """The first render(s) of a moment: the hero gets broll.HERO_TAKES takes of its prompt."""
    import broll
    layout = _layout(m)
    spec = m["spec"]
    text = _text(spec, layout)
    m = _moment_for(m, spec, text)
    takes = broll.HERO_TAKES if layout == "hero" else 1
    out = []
    for j in range(1, takes + 1):
        raw = os.path.join(tmp, f"broll_{k}{tag}" + (f"_t{j}" if j > 1 else "") + ".jpg")
        got, seed = render(text, raw, layout)
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
                got, seed = render(c["m"]["prompt"], raw, c["layout"])
                if got:
                    pending.append({**c, "file": got, "seed": seed, "tries": c["tries"] + 1, "take": None})
            elif verdict == "alt":
                alt = {**spec, **(spec.get("alt") or {})}
                alt.pop("alt", None)
                text = _text(alt, c["layout"])
                m2 = _moment_for(c["m"], alt, text)
                raw = os.path.join(tmp, f"broll_{k}_alt.jpg")
                got, seed = render(text, raw, c["layout"])
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


def run(clip_path, clip, words, transcript, start, end, n, avoid, head, tail, gap_min, block, dur_range, tmp, render):
    """The whole v20 chain for one clip. ``render(text, out_path, layout) -> (path or None, seed)`` makes one picture
    (add_broll's ComfyUI call). Under broll_check.MIN_PER_CLIP kept: the reserves, then the alternatives not yet
    rendered. Returns (cands, moments) — cands in the old chain's shape, the kept ones only."""
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
                                              dur_range=dur_range)
    if not moments:
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
