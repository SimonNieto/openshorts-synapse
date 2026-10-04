"""The v24 short bench (4-oct-2026): ten fixed moments, one per kind of difficulty (output/_test_broll/short/
moments.json: the literal, a positive and a negative experience, an abstract explanation, an absence, a grave moment,
a comparison, a figure of speech, a negation, a moral question). Every change is tried here first; the bench of the
eight clips (broll_bench.py plan) runs only before a version goes to production. Runs inside the backend container.

    python broll_bench24.py freeze                      the editor's fiche of each moment, frozen (fiches.json)
    python broll_bench24.py run --tag v24 [--only 1,5] [--dry] [--shadow haiku]
    python broll_bench24.py board --tag v24             the boards again from the run's JSON
    python broll_bench24.py stability --tag v24 --runs 3      the viewer asked again on the same pictures
    python broll_bench24.py stability --v23 --runs 3          ... on the pictures of the v23 bench (made again)
    python broll_bench24.py agree --tags v24 [--v23 10]       the sheets the user chooses on (no answer shown)
    python broll_bench24.py score --answers "1B 2A 3-0 ..."   her choices against the viewer's

Nothing is made twice: the fiches are frozen, the director's and the judges' answers come back from ai_cache when
their question is the same, and every picture from the store (broll_store) when its prompt is the same. ``--dry``
stops after the prompts and says which ones are new. Caps per clip: broll_v24.CAP_GPU_S, CAP_TOKENS."""
import argparse
import copy
import glob
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import broll_bench as bb   # noqa: E402
import plus                # noqa: E402

SHORT_DIR = os.path.join(HERE, "output", "_test_broll", "short")
MOMENTS = os.path.join(SHORT_DIR, "moments.json")
FICHES = os.path.join(SHORT_DIR, "fiches.json")
V24_DIR = os.path.join(HERE, "output", "_test_broll", "v24")
V23_SET = os.path.join(V24_DIR, "v23_set.json")
AGREE = os.path.join(SHORT_DIR, "agree_key.json")
LETTERS = "ABCDEFGH"
_MOMENT_KEYS = ("t", "anchor", "said", "spec", "mood", "dur", "hero", "clip_gravity", "subject", "notion", "score",
                "role", "idea_text")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)


def _env():
    prof = bb._profile(None)
    bb._job_env(prof)
    os.environ["BROLL_NOTION_MEMORY"] = "0"
    return prof


def _episode(job):
    """(job_dir, meta) with the episode's brief and visual bible set in ai_brain, as broll_bench's plan does."""
    import ai_brain
    job_dir, meta = bb._find_job(job)
    brief, _how = bb._full_brief(meta)
    ai_brain.EPISODE_BRIEF = brief
    bible = meta.get("episode_bible") or None
    if bible and not bible.get("mood"):
        bible = None
    if bible:
        ai_brain.EPISODE_BIBLE = bible
    elif brief:
        ai_brain.episode_bible(brief, meta.get("transcript"))
    else:
        ai_brain.EPISODE_BIBLE = None
    return job_dir, meta


# --- freeze: the editor's fiche of each moment -------------------------------------------------------------------------
def _capture_editor(job_dir, meta, n, clip, pre_fx, prof):
    """The editor of the v23 bench on one clip (its question is the same: ai_cache answers), stopped right after it:
    {"words", "avoid", "head", "tail", "block", "dur_range", "moments", "reserves", "raw"}. No picture is made."""
    import broll
    import broll_spec
    import broll_v20
    planner = "gemini" if prof["brain"]["stages"]["broll"] == "gemini" else "claude"
    cfg = {**plus.BROLL, "enabled": True, "planner": planner, "review": "manual", "chain": "", "ideas": False,
           "reserves": "quota", **{k: v for k, v in bb.VERSIONS["v23"].items() if k != "env"}}
    c = dict(clip)
    inset = c.get("screen_inset")
    if inset and inset.get("image"):
        c["screen_inset"] = {**inset, "path": os.path.join(job_dir, inset["image"])}
    got = {}
    orig_run, orig_cj = broll_v20.run, broll.claude_json

    def cj(prompt, schema, *a, **kw):
        out = orig_cj(prompt, schema, *a, **kw)
        if kw.get("stage") == "broll_plan":
            got["raw"] = out
        return out

    def fake_run(clip_path, clip_, words, transcript, start, end, n_, avoid, head, tail, gap_min, block, dur_range, tmp,
                 render, ideas=False, **_kw):
        sheets = broll._frame_sheets(clip_path, tmp)
        moments, reserves = broll_spec.plan_specs(clip_, words, n_, avoid, transcript=transcript, start=start, end=end,
                                                  sheets=sheets, head=head, tail=tail, gap_min=gap_min, block=block,
                                                  dur_range=dur_range, ideas=ideas)
        got.update(words=words, avoid=list(avoid or []), head=head, tail=tail,
                   block=[list(b) for b in block or []], dur_range=list(dur_range) if dur_range else None,
                   moments=moments, reserves=reserves)
        return [], []

    keep = tempfile.mkdtemp(prefix="freeze_")
    broll_v20.run, broll.claude_json = fake_run, cj
    try:
        broll.add_broll(pre_fx, os.path.join(keep, "not_written.mp4"), c, meta.get("transcript"), float(clip["start"]),
                        float(clip["end"]), cfg, keep_dir=keep, keep_prefix="", ground_hook=False)
    finally:
        broll_v20.run, broll.claude_json = orig_run, orig_cj
        shutil.rmtree(keep, ignore_errors=True)
    return got


def _word_at(words, t):
    return min(words, key=lambda w: abs(float(w["start"]) - t)) if words else {"text": "", "start": t}


def _fiche_for(target, got, gravity):
    """The moment of ``target`` (its second ``t``): the editor's placed moment on that sentence (kept or reserve), else
    the spec it listed there (a figure or a denial is listed, then dropped), else one made by the code from the
    sentence. -> (moment, source)."""
    import broll
    import broll_ideas
    import broll_spec
    import visual_mood
    words, t = got["words"], float(target["t"])
    said, _b, _a = broll_ideas._around(words, t)
    placed = [m for m in (got.get("moments") or []) + (got.get("reserves") or [])
              if abs(float(m["t"]) - t) <= 2.5 and broll_ideas._around(words, float(m["t"]))[0] == said]
    if placed:
        m = min(placed, key=lambda m: abs(float(m["t"]) - t))
        m = {k: copy.deepcopy(m.get(k)) for k in _MOMENT_KEYS if k in m}
        (m.get("spec") or {}).pop("alt", None)
        return m, "placed by the editor"
    listed = [s for s in ((got.get("raw") or {}).get("moments") or []) if isinstance(s, dict)
              and abs(float(s.get("time") or -99) - t) <= 3.5]
    if listed:
        raw = min(listed, key=lambda s: abs(float(s.get("time") or 0) - t))
        spec = broll_spec._clean_fields(raw, gravity)
        source = f"listed by the editor ({spec['literal'] or 'literal'}), dropped by its rules"
    else:
        flags = target.get("flags") or {}
        spec = broll_spec._clean_fields({"kind": "scene", "subject": "", "literal": "literal", **flags}, gravity)
        raw = {}
        source = "made from the sentence (the editor listed nothing there)"
    spec.update(said=said, time=t, anchor=str(raw.get("anchor") or _word_at(words, t)["text"]).strip(" ,.?!"),
                worth=3, hero=False, notion="", subject_words=spec.get("subject_words") or "")
    m = {"t": t, "anchor": spec["anchor"], "said": said, "spec": spec, "mood": visual_mood.clean(spec.get("mood")),
         "dur": broll.CARD_DUR_MAX, "hero": False, "clip_gravity": gravity, "subject": spec.get("subject"),
         "notion": ""}
    return m, source


def cmd_freeze(args):
    prof = _env()
    targets = _load(MOMENTS)
    out = {"made": time.strftime("%Y-%m-%d %H:%M"), "clips": {}, "moments": []}
    by_clip = {}
    for tg in targets:
        by_clip.setdefault((tg["job"], int(tg["clip"])), []).append(tg)
    for (job, n), tgs in by_clip.items():
        job_dir, meta = _episode(job)
        clip, pre_fx = bb._clip_of(job_dir, meta, n)
        print(f"\n▶ {job} clip {n}: {clip.get('video_title_for_youtube_short')}", flush=True)
        got = _capture_editor(job_dir, meta, n, clip, pre_fx, prof)
        if not got.get("words"):
            raise SystemExit(f"{job} clip {n}: the editor did not run")
        gravity = next((m.get("clip_gravity") for m in got["moments"] + got["reserves"] if m.get("clip_gravity")),
                       None) or ((got.get("raw") or {}).get("clip_gravity") or "none")
        key = f"{os.path.basename(job_dir)[:8]}_clip{n}"
        out["clips"][key] = {"job": job, "clip": n, "title": clip.get("video_title_for_youtube_short") or "",
                             "hook": clip.get("viral_hook_text") or "", "punchline_time": clip.get("punchline_time"),
                             "words": got["words"], "avoid": got["avoid"], "head": got["head"], "tail": got["tail"],
                             "block": got["block"], "dur_range": got["dur_range"], "gravity": gravity}
        for tg in tgs:
            m, source = _fiche_for(tg, got, gravity)
            out["moments"].append({**tg, "clip_key": key, "moment": m, "source": source})
            print(f"   #{tg['id']} {tg['type']}: {source} — t {m['t']:.1f} s, \"{m['said'][:90]}\" "
                  f"(kind {m['spec'].get('kind')}, subject \"{m['spec'].get('subject')}\", flags "
                  f"{[f for f in ('death_near', 'substance', 'intake') if m['spec'].get(f)]})", flush=True)
    out["moments"].sort(key=lambda x: x["id"])
    _save(out, FICHES)
    print(f"\n✅ {len(out['moments'])} fiches frozen -> {FICHES}")


# --- run: the v24 chain on the frozen fiches --------------------------------------------------------------------------
def _renderer(version, log, dry, gpu_cap):
    import broll
    import broll_store
    base_steps = int(os.environ.get("COMFYUI_ZIMAGE_STEPS") or 8)

    def make(text, out, size, seed, steps):
        try:
            return broll.local_image(text, "photo", out, size=size, seed=seed, steps=steps, raw=True)
        except Exception as e:
            if not broll.comfy_available():
                raise
            print(f"   ⚠️ ComfyUI refused a picture ({str(e)[:120]}).", flush=True)
            return None

    return broll_store.renderer(make, lambda layout: broll._gen_size(layout, "std"),
                                lambda layout: (broll.HERO_STEPS if layout == "hero" and broll.HERO_STEPS > 0
                                                else base_steps),
                                version=version, dry=dry, log=log, gpu_cap=gpu_cap)


def cmd_run(args):
    import ai_brain
    import broll
    import broll_v24
    _env()
    fiches = _load(FICHES)
    only = {int(x) for x in str(args.only or "").split(",") if x.strip()}
    chosen = [f for f in fiches["moments"] if not only or f["id"] in only]
    if not args.dry and not broll.comfy_available():
        raise SystemExit(f"ComfyUI not reachable at {broll._comfy_url()} (start it in Pinokio)")
    run_dir = os.path.join(SHORT_DIR, args.tag)
    out = {"tag": args.tag, "version": "v24", "dry": bool(args.dry), "made": time.strftime("%Y-%m-%d %H:%M"),
           "mech_model": args.mech or broll_v24._model("broll_mech", "sonnet"), "clips": {}, "moments": []}
    by_clip = {}
    for f in chosen:
        by_clip.setdefault(f["clip_key"], []).append(f)
    broll._comfy_enter()
    try:
        for key, fs in by_clip.items():
            ctx = fiches["clips"][key]
            _episode(ctx["job"])
            clip = {"video_title_for_youtube_short": ctx["title"], "viral_hook_text": ctx["hook"],
                    "punchline_time": ctx.get("punchline_time")}
            moments = [copy.deepcopy(f["moment"]) for f in fs]
            img_dir = os.path.join(run_dir, "images", key)
            shutil.rmtree(img_dir, ignore_errors=True)
            os.makedirs(img_dir)
            log = []
            render = _renderer(args.tag, log, args.dry, broll_v24.CAP_GPU_S)
            print(f"\n▶ {key} ({ctx['gravity']}): " + " | ".join(f"#{f['id']} {f['type']}" for f in fs), flush=True)
            res = broll_v24.run_moments(moments, clip, ctx["words"], ctx["gravity"], render, img_dir,
                                        avoid=ctx["avoid"], head=ctx["head"], block=[tuple(b) for b in ctx["block"]],
                                        dry=args.dry, mech_model=args.mech or None)
            res["render_log"] = log
            res["made_now"] = sum(1 for x in log if x["made"])
            res["from_store"] = sum(1 for x in log if x["cached"])
            res["new_prompts"] = sum(1 for x in log if not x["made"] and not x["cached"])
            if args.shadow and not args.dry:
                res["shadow"] = _shadow(res, moments, ctx["words"], args.shadow)
            print("   " + broll_v24.summary_line(res) + f" — {res['made_now']} made now, {res['from_store']} from the "
                  f"store" + (f", {res['new_prompts']} new prompt(s) not made" if res["new_prompts"] else ""),
                  flush=True)
            out["clips"][key] = {k: v for k, v in res.items() if k != "moments"}
            for f, rec in zip(fs, res["moments"]):
                out["moments"].append({"id": f["id"], "type": f["type"], "label": f["label"], "clip_key": key,
                                       "source": f["source"], "record": rec})
    finally:
        broll._comfy_leave()
    out["moments"].sort(key=lambda x: x["id"])
    out["totals"] = {"gpu_s": round(sum(c["gpu_s"] for c in out["clips"].values()), 1),
                     "tokens": sum(c["tokens"] for c in out["clips"].values()),
                     "calls": sum(c["calls"] for c in out["clips"].values()),
                     "made_now": sum(c["made_now"] for c in out["clips"].values()),
                     "from_store": sum(c["from_store"] for c in out["clips"].values()),
                     "with_picture": sum(1 for m in out["moments"] if m["record"].get("final") not in (None, "face")),
                     "usage": dict(ai_brain.USAGE)}
    _save(out, os.path.join(run_dir, "run.json"))
    if not args.dry:
        _boards(out, run_dir)
    t = out["totals"]
    print(f"\n✅ {args.tag}: {t['with_picture']}/{len(out['moments'])} moments with a picture; GPU {t['gpu_s']:.0f} s "
          f"({t['made_now']} made now, {t['from_store']} from the store); {t['tokens']:,} tokens in {t['calls']} calls "
          f"-> {run_dir}")


def _shadow(res, moments, words, model):
    """The mechanical check again by ``model`` on the same pictures: where it agrees with the run's (point 11)."""
    import broll_v24
    items, theirs = [], {}
    for r in res["moments"]:
        for c in r["cands"]:
            if c.get("file") and c.get("mech"):
                items.append({"file": c["file"], "m": moments[r["k"]], "spec": c["spec"]})
                theirs[broll_v24._name(c["file"])] = c["mech"]["why"]
    got = broll_v24.mechanical(items, words, model)
    rows = [{"file": f, "run": theirs[f], model: (got.get(f) or {}).get("why", "not checked")} for f in theirs]
    same = sum(1 for r in rows if bool(r["run"]) == bool(r[model]))
    return {"model": model, "rows": rows, "same_verdict": same, "of": len(rows)}


# --- the boards --------------------------------------------------------------------------------------------------------
def _thumb(path, w, h):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((w, h))
    return im


def _boards(out, run_dir, per=4):
    """One board per ``per`` moments: the sentence, every idea made (its title, the mechanical check, the viewer's four
    answers and rank, the verifier on the picture), the winner framed, the face alone when nothing passed."""
    from PIL import Image, ImageDraw
    W, TW, TH = 1700, 400, 250
    f_h, f_b, f_s = bb._font(26, True), bb._font(19), bb._font(16)
    paths = []
    for b0 in range(0, len(out["moments"]), per):
        rows = out["moments"][b0:b0 + per]
        heights = []
        for mm in rows:
            r = mm["record"]
            n = max(1, len(r["cands"]) + (1 if r.get("hero_render") else 0))
            heights.append(150 + ((n + 3) // 4) * (TH + 150))
        board = Image.new("RGB", (W, sum(heights) + 20), bb._C_BG)
        d = ImageDraw.Draw(board)
        y = 10
        for mm, hgt in zip(rows, heights):
            r = mm["record"]
            final = r.get("final")
            d.text((20, y), f"#{mm['id']} {mm['type']} — {mm['label']}   →  "
                   + ("VISAGE SEUL" if final in (None, "face") else os.path.basename(final)), fill=bb._C_LABEL, font=f_h)
            yy = y + 36
            for line in bb._wrap(f"« {r.get('said')} »", f_b, W - 40)[:2]:
                d.text((20, yy), line, fill=bb._C_HEAD, font=f_b)
                yy += 24
            idea = f"idée : {r.get('idea') or '-'} ({r.get('role') or '-'})" + (f" — pas d'image : {r['why']}" if r.get("why") else "")
            for line in bb._wrap(idea, f_s, W - 40)[:2]:
                d.text((20, yy), line, fill=bb._C_SENT, font=f_s)
                yy += 20
            x, ty = 20, y + 150
            cells = [(c, c.get("file")) for c in r["cands"]]
            if r.get("hero_render"):
                cells.append(({"title": "héros plein écran", "hero": True, **r["hero_render"]}, r["hero_render"]["file"]))
            for j, (c, f) in enumerate(cells):
                if j and j % 4 == 0:
                    x, ty = 20, ty + TH + 150
                if f and os.path.exists(f):
                    im = _thumb(f, TW, TH)
                    board.paste(im, (x + (TW - im.width) // 2, ty))
                    won = final not in (None, "face") and os.path.basename(final) == os.path.basename(f)
                    if won:
                        d.rectangle([x - 4, ty - 4, x + TW + 4, ty + TH + 4], outline=(120, 220, 120), width=5)
                else:
                    d.rectangle([x, ty, x + TW, ty + TH], outline=bb._C_DIM, width=2)
                    d.text((x + 10, ty + 10), "non rendue", fill=bb._C_DIM, font=f_b)
                lines = [f"[{c.get('i', 'H')}] {c.get('title') or ''}"]
                if c.get("refused"):
                    lines.append(f"x texte : {c['refused']}")
                elif c.get("hero"):
                    lines.append("+ contrôle" if not c.get("mech") else f"x contrôle : {c['mech']}")
                else:
                    mech = (c.get("mech") or {}).get("why")
                    lines.append("+ contrôle" if c.get("mech") and not mech else f"x contrôle : {mech or '-'}")
                    flags = ((c.get("view") or {}).get("flags") or {})
                    yes = [k for k, v in flags.items() if v == "yes"]
                    if flags:
                        lines.append(("x spectateur : " + ", ".join(yes)) if yes else
                                     f"+ spectateur, rang {(c.get('view') or {}).get('rank') or 'après le visage'}")
                post = (r.get("post") or {}).get(os.path.basename(f or "").lower())
                if post:
                    lines.append(("+ vérif. image" if post["verdict"] == "pass" else f"x vérif. image : {post['reason']}"))
                ly = ty + TH + 6
                for line in lines:
                    for part in bb._wrap(line, f_s, TW)[:2]:
                        d.text((x, ly), part, fill=bb._C_BODY, font=f_s)
                        ly += 19
                x += TW + 20
            y += hgt
        p = os.path.join(run_dir, f"board_{b0 // per + 1}.jpg")
        board.save(p, quality=88)
        paths.append(p)
        print(f"   🖼️ {p}", flush=True)
    return paths


def cmd_board(args):
    run_dir = os.path.join(SHORT_DIR, args.tag)
    _boards(_load(os.path.join(run_dir, "run.json")), run_dir)


# --- stability: the viewer asked again on the same pictures -------------------------------------------------------------
def _short_groups(tag):
    """[(clip_key, job, [groups])] of a run: per moment the pictures the viewer got (made, mechanical check passed)."""
    out = _load(os.path.join(SHORT_DIR, tag, "run.json"))
    fiches = _load(FICHES)
    by = {}
    for mm in out["moments"]:
        r = mm["record"]
        files = [c["file"] for c in r["cands"] if c.get("file") and c.get("mech") and not c["mech"].get("why")]
        by.setdefault(mm["clip_key"], []).append({"k": r["k"], "id": mm["id"], "said": r["said"],
                                                  "before": r.get("before"), "files": files,
                                                  "first": {"order": r.get("view_order") or []}})
    return [(key, fiches["clips"][key]["job"], gs) for key, gs in by.items()]


def _v23_groups():
    """[(tag, job, [groups])] of the v23 pictures (made again from their prompt and seed, regen23.py): per moment every
    picture made for it, copied under its own name; the sentence and what was heard before from the clip's words."""
    import broll_ideas
    import viral_fx
    items = _load(V23_SET)
    out = []
    for tag in sorted({it["tag"] for it in items}):
        its = [it for it in items if it["tag"] == tag]
        job_dir, meta = bb._find_job(its[0]["job"][:8])
        clip = meta["shorts"][int(its[0]["clip"]) - 1]
        words = viral_fx.clip_words(meta.get("transcript"), float(clip["start"]), float(clip["end"]))
        res = _load(os.path.join(bb.BRAIN_DIR, f"{tag}.json"))
        final = res.get("final") or res.get("moments") or []
        folder = os.path.join(V24_DIR, "v23", tag)
        os.makedirs(folder, exist_ok=True)
        groups = []
        for k in sorted({it["k"] for it in its}):
            files = []
            for it in its:
                if it["k"] == k and it["verdict"] != "other take":
                    dst = os.path.join(folder, it["file"])
                    if not os.path.exists(dst):
                        shutil.copyfile(it["path"], dst)
                    files.append(dst)
            t = float(final[k]["t"]) if k < len(final) and final[k].get("t") is not None else None
            if t is None:
                continue
            said, before, _a = broll_ideas._around(words, t)
            groups.append({"k": k, "id": f"{tag}#{k}", "said": said, "before": before, "files": files})
        out.append((tag, its[0]["job"][:8], groups))
    return out


def cmd_stability(args):
    import broll_v24
    _env()
    sets = _v23_groups() if args.v23 else _short_groups(args.tag)
    name = "v23" if args.v23 else args.tag
    rows = []
    for key, job, groups in sets:
        _episode(job)
        runs = []
        for i in range(args.runs):
            print(f"▶ {key}: the viewer, run {i + 1}/{args.runs}", flush=True)
            runs.append(broll_v24.choose([{**g, "k": j} for j, g in enumerate(groups)], reuse=False))
        for j, g in enumerate(groups):
            winners = [broll_v24.verdict_of(r.get(j) or {}, None)[0] for r in runs]
            flags = {}
            for r in runs:
                for f, v in ((r.get(j) or {}).get("views") or {}).items():
                    flags.setdefault(f, []).append(tuple((v.get("flags") or {}).get(x) for x in broll_v24.FLAWS4))
            rows.append({"id": g["id"], "said": g["said"], "files": [os.path.basename(f) for f in g["files"]],
                         "winners": winners, "stable": len(set(winners)) == 1,
                         "flags_stable": {f: len(set(v)) == 1 for f, v in flags.items()},
                         "runs": [{"order": (r.get(j) or {}).get("order"),
                                   "views": (r.get(j) or {}).get("views")} for r in runs]})
    n = len(rows)
    stable = sum(r["stable"] for r in rows)
    fl = [s for r in rows for s in r["flags_stable"].values()]
    multi = [r for r in rows if len(r["files"]) >= 2]
    rep = {"set": name, "runs": args.runs, "moments": n, "same_choice": stable,
           "same_choice_with_2_or_more": sum(r["stable"] for r in multi), "with_2_or_more": len(multi),
           "pictures": len(fl), "same_four_answers": sum(fl), "rows": rows}
    _save(rep, os.path.join(SHORT_DIR, f"stability_{name}.json"))
    print(f"\n✅ {name}: the same choice in all {args.runs} runs on {stable}/{n} moments "
          f"({rep['same_choice_with_2_or_more']}/{len(multi)} with two pictures or more); the same four answers on "
          f"{sum(fl)}/{len(fl)} pictures -> stability_{name}.json")


# --- agreement: the user chooses on the same pictures ------------------------------------------------------------------
def cmd_agree(args):
    """Sheets of moments, each with its pictures lettered A, B, C... and 0 for the face alone; the viewer's choice is
    NOT shown. The key (letters -> files, the viewer's choice) goes to agree_key.json."""
    from PIL import Image, ImageDraw
    entries = []
    for tag in [t for t in str(args.tags or "").split(",") if t.strip()]:
        for key, _job, groups in _short_groups(tag):
            out = _load(os.path.join(SHORT_DIR, tag, "run.json"))
            recs = {m["id"]: m["record"] for m in out["moments"]}
            for g in groups:
                if g["files"]:
                    entries.append({"source": tag, "id": g["id"], "said": g["said"], "before": g.get("before"),
                                    "files": g["files"], "viewer": os.path.basename(recs[g["id"]].get("winner") or "face")})
    if args.v23:
        stab = os.path.join(SHORT_DIR, "stability_v23.json")
        first = {r["id"]: r for r in _load(stab)["rows"]} if os.path.exists(stab) else {}
        v23 = [(key, g) for key, _job, gs in _v23_groups() for g in gs if g["files"]]
        v23.sort(key=lambda kg: -len(kg[1]["files"]))
        for key, g in v23[:args.v23]:
            w = (first.get(g["id"]) or {}).get("winners") or []
            entries.append({"source": "v23", "id": g["id"], "said": g["said"], "before": g.get("before"),
                            "files": g["files"], "viewer": w[0] if w else None})
    W, TW, TH, per = 1500, 460, 300, 5
    f_h, f_b = bb._font(30, True), bb._font(22)
    key_out, sheets = [], []
    for s0 in range(0, len(entries), per):
        rows = entries[s0:s0 + per]
        H = 30 + len(rows) * (TH + 150)
        sheet = Image.new("RGB", (W, H), bb._C_BG)
        d = ImageDraw.Draw(sheet)
        y = 20
        for j, e in enumerate(rows):
            num = s0 + j + 1
            letters = {}
            d.text((20, y), f"{num}.", fill=bb._C_LABEL, font=f_h)
            yy = y
            for line in bb._wrap(f"« {e['said']} »", f_b, W - 100)[:2]:
                d.text((80, yy + 4), line, fill=bb._C_HEAD, font=f_b)
                yy += 28
            x = 80
            for i, f in enumerate(e["files"][:3]):
                im = _thumb(f, TW, TH)
                sheet.paste(im, (x, y + 70))
                d.text((x, y + 74 + TH), LETTERS[i], fill=bb._C_LABEL, font=f_h)
                letters[LETTERS[i]] = os.path.basename(f)
                x += TW + 20
            d.text((80, y + 110 + TH), "0 = visage seul", fill=bb._C_DIM, font=f_b)
            key_out.append({"num": num, **{k: e[k] for k in ("source", "id", "said", "viewer")}, "letters": letters})
            y += TH + 150
        p = os.path.join(SHORT_DIR, f"agree_{s0 // per + 1}.jpg")
        sheet.save(p, quality=88)
        sheets.append(p)
    _save({"made": time.strftime("%Y-%m-%d %H:%M"), "moments": key_out}, AGREE)
    print("✅ " + ", ".join(sheets) + f" ({len(key_out)} moments); key -> {AGREE}")


def cmd_score(args):
    """Her answers ("1B 2A 3-0" or "1:B, 2:0"...) against the viewer's choices of the key."""
    import re
    key = {m["num"]: m for m in _load(AGREE)["moments"]}
    got = dict((int(n), a.upper()) for n, a in re.findall(r"(\d+)\s*[-:=. ]?\s*([A-Ha-h0])\b", args.answers))
    rows, same = [], 0
    for num, m in sorted(key.items()):
        if num not in got:
            continue
        hers = "face" if got[num] == "0" else m["letters"].get(got[num])
        viewer = m.get("viewer") or None
        ok = (hers or "").lower() == (viewer or "").lower()
        same += ok
        rows.append({"num": num, "said": m["said"][:80], "hers": hers, "viewer": viewer, "same": ok})
    rep = {"answered": len(rows), "same": same, "rows": rows}
    _save(rep, os.path.join(SHORT_DIR, "agree_score.json"))
    print(f"✅ the viewer agrees with you on {same}/{len(rows)} moments")
    for r in rows:
        print(f"   {r['num']:>2} {'✓' if r['same'] else '✗'} vous {r['hers']} / spectateur {r['viewer']} — {r['said']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("freeze").set_defaults(fn=cmd_freeze)
    p = sub.add_parser("run")
    p.add_argument("--tag", default="v24")
    p.add_argument("--only", default="")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--mech", default="", help="the mechanical check's model (default BRAIN_BROLL_MECH or sonnet)")
    p.add_argument("--shadow", default="", help="the mechanical check again with this model, to compare (haiku)")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("board")
    p.add_argument("--tag", default="v24")
    p.set_defaults(fn=cmd_board)
    p = sub.add_parser("stability")
    p.add_argument("--tag", default="v24")
    p.add_argument("--v23", action="store_true")
    p.add_argument("--runs", type=int, default=3)
    p.set_defaults(fn=cmd_stability)
    p = sub.add_parser("agree")
    p.add_argument("--tags", default="v24")
    p.add_argument("--v23", type=int, default=0, help="also that many moments of the v23 pictures")
    p.set_defaults(fn=cmd_agree)
    p = sub.add_parser("score")
    p.add_argument("--answers", required=True)
    p.set_defaults(fn=cmd_score)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
