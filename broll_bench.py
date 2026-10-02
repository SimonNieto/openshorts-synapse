"""Witness renders for the premium B-roll work (Clip Generator++), on a REAL clip.

Runs inside the backend container (PIL, ffmpeg, the job's modules):

    python broll_bench.py chain  --job <job id> --clip 1
    python broll_bench.py visual --job <job id> --clip 1 [--profile <id>] [--before-cache]

``chain``: the clip's render chain after the reframe (motion -> B-roll -> hook
-> captions), rendered three times from the pristine ``.pre_fx.mp4``: with the
historical encoders, with the HQ chain (fx.hq_chain) and a near-lossless
reference. Reports SSIM of each against the reference, sizes and times, and
writes a 400x400 crop of the darkest zone at t=10 s side by side
(``chain_dark_crop.jpg``) plus two full frames (``chain_frame_*.jpg``).

``visual``: the same clip rendered BEFORE (the profile as saved) and AFTER
(the premium settings) with its B-roll planned and generated for real, side by
side (ffmpeg hstack, ``visual_side_by_side.mp4``) and six frames at the key
instants (``visual_f*.jpg``). The BEFORE render is kept and reused
(``--before-cache``) so the premium chantiers can be compared one after the
other on the same images.

    python broll_bench.py plan --job <job id or prefix> [--clips 1,3,5] [--versions current,v2] [--fresh]
                               [--signatures 0,0.2]
    python broll_bench.py board --job <job id or prefix> [--clips 1,3,5] [--versions v3] [--signatures 0,0.2]
    python broll_bench.py moods --job <job id or prefix> [--clips 1,3,5] [--from v9] [--runs 5]
    python broll_bench.py plan ... --moments aligned:v8,v9,v10,v11      (the SAME moments as those versions)
    python broll_bench.py select --job <job> --clips 5 --runs 4 [--versions v12] [--focus 33.6]
    python broll_bench.py content --jobs 88a7e7c1:5,e9e44926:9 --versions v8,v12

``plan`` (the brain): planner + art direction + pictures + review on the chosen
clips, exactly as a job runs them, but NO video is cut (add_broll in its
manual-review mode). One board per clip and version
(``brain/<job>_clip<N>_<version>.jpg``: each kept picture as graded, its prompt,
the exact text / seed / size sent to ComfyUI, the review's scores, the moments
dropped, the seconds and the tokens) with its JSON; two versions are also put
side by side (``_compare.jpg``). A version is a name of ``VERSIONS`` (cfg keys
laid over the house recipe) or ``name:key=value;key=value``. A job made without
B-roll has no glossary in its brief: the episode is read again (ai_cache keeps
the answer). The notion memory is never read nor written. ``--signatures``: one
more sheet per clip and version (``_signatures.jpg``) with every kept picture raw
and graded at each signature strength — the same pictures, only the stamp moves.

``moods`` (B-roll « ambiance », 2-oct-2026): the pictures of an earlier ``plan``
run (``--from`` its version) are rated again ``--runs`` times, fresh each time
(visual_mood.rate, the editor's own mood rule), to measure how much the anchored
levels move on the SAME segments: per question the share of answers on the most
frequent level and the mean largest gap in levels, then what it does to the
pictures (the largest ΔE between two runs' grades on the kept picture).
``brain/<job>_clip<N>_moods.json``.

``--moments aligned:<versions>`` (B-roll « ambiance » v12, 2-oct-2026): the editor gets the moments of earlier runs
— one per moment any of those versions illustrated (aligned_moments: the same moment within GROUP_S s or the same
sentence) — and answers for each, a picture or a reason to skip it: versions compared ON THE SAME MOMENTS.
``select``: the editor alone, fresh, --runs times on a clip, free choice as in a job: how often each moment is chosen
(--focus: the moment to watch). ``content``: what fills every kept picture (the review's "seen", one Haiku call):
people, a place with people, an empty place, an object set down, an object in use, an inner or abstract picture —
counted per version, for all pictures and for the heroes.

Everything lands in output/_test_broll/premium/ (``plan``: output/_test_broll/brain/).
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

import plus

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT_DIR = os.path.join(HERE, "output", "_test_broll", "premium")


def _find_clip(job, n):
    job_dir = os.path.join(HERE, "output", job)
    metas = glob.glob(os.path.join(job_dir, "*_metadata.json"))
    if not metas:
        sys.exit(f"no metadata in {job_dir}")
    with open(metas[0], encoding="utf-8") as f:
        meta = json.load(f)
    clip = meta["shorts"][n - 1]
    pre = glob.glob(os.path.join(job_dir, f"*_clip_{n}.pre_fx.mp4"))
    if not pre:
        sys.exit(f"no .pre_fx.mp4 for clip {n} in {job_dir} (the bench needs a Clip Generator++ render)")
    return job_dir, meta, clip, pre[0]


def _profile(profile_id=None):
    import plus
    profiles = plus.load_profiles()
    prof = next((p for p in profiles if p.get("id") == profile_id), None) if profile_id else (profiles[0] if profiles else None)
    return plus.sanitize(prof or {})


def _job_env(prof):
    """The env a Clip Generator++ job gets from this profile, applied to this process."""
    import plus
    env = plus.job_env(prof)
    for k, v in env.items():
        os.environ[k] = v
    return env


def _ffprobe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def _frame(path, t, out, vf=None):
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1"]
    if vf:
        cmd += ["-vf", vf]
    subprocess.run(cmd + [out], check=True)
    return out


def _ssim(a, ref):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", a, "-i", ref, "-lavfi", "[0:v][1:v]ssim", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"All:([\d.]+)", r.stderr)
    return float(m[-1]) if m else None


def _label(img_path, text):
    from PIL import Image, ImageDraw
    im = Image.open(img_path).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 8 + 7 * len(text), 18), fill=(0, 0, 0))
    d.text((4, 3), text, fill=(255, 216, 77))
    im.save(img_path, quality=95)


def _hstack(paths, out, height=None):
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in paths]
    if height:
        ims = [im.resize((int(im.width * height / im.height), height), Image.LANCZOS) for im in ims]
    h = max(im.height for im in ims)
    sheet = Image.new("RGB", (sum(im.width for im in ims) + 6 * (len(ims) - 1), h), (24, 24, 24))
    x = 0
    for im in ims:
        sheet.paste(im, (x, 0))
        x += im.width + 6
    sheet.save(out, quality=92)
    return out


# --- the chain ------------------------------------------------------------------------

def render_chain(pre_fx, words, clip, prof, items, img_dir, out_path, tag, log):
    """motion -> B-roll (items) -> hook -> captions, as main.py / app.py chain them. Returns per-layer seconds."""
    import broll
    import hooks
    import viral_fx
    style = plus.EDIT_STYLE
    fx = dict(plus.FX)
    fx.pop("watermark", None)
    if clip.get("punchline_time") is not None:
        fx["hints"] = {"punchline_time": clip["punchline_time"]}
    topic = viral_fx.topic_words(clip.get("video_title_for_youtube_short"), clip.get("viral_hook_text"))
    tmp = os.path.join(OUT_DIR, f"_tmp_{tag}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    times = {}
    t0 = time.time()
    motion = os.path.join(tmp, "1_motion.mp4")
    viral_fx.apply_motion(pre_fx, words, style, motion, opts=fx)
    times["motion"] = round(time.time() - t0, 1)
    cur = motion
    if items:
        t0 = time.time()
        br = os.path.join(tmp, "2_broll.mp4")
        broll.overlay_items(cur, br, items, img_dir=img_dir)
        times["broll"] = round(time.time() - t0, 1)
        cur = br
    hook = clip.get("auto_hook") or {}
    text = hook.get("text") or clip.get("viral_hook_text")
    if text and prof["hook_style"] != "none":
        t0 = time.time()
        hk = os.path.join(tmp, "3_hooked.mp4")
        hooks.add_hook_to_video(cur, text, hk, position="top", duration=float(hook.get("duration_seconds") or prof["hook_seconds"]),
                                style=hook.get("style") or prof["hook_style"])
        times["hook"] = round(time.time() - t0, 1)
        cur = hk
    t0 = time.time()
    viral_fx.apply_captions(cur, words, style, out_path, watermark=prof["watermark"] or None, topic=topic)
    times["captions"] = round(time.time() - t0, 1)
    sizes = {os.path.basename(p)[2:-4]: round(os.path.getsize(p) / 1e6, 1) for p in sorted(glob.glob(os.path.join(tmp, "*.mp4")))}
    sizes["final"] = round(os.path.getsize(out_path) / 1e6, 1)
    log(f"   {tag}: layers {times} s, files {sizes} MB")
    shutil.rmtree(tmp, ignore_errors=True)
    return {"seconds": times, "mb": sizes}


def cmd_chain(args):
    import ffmpeg_utils as ffu
    import viral_fx
    os.makedirs(OUT_DIR, exist_ok=True)
    job_dir, meta, clip, pre_fx = _find_clip(args.job, args.clip)
    prof = _profile(args.profile)
    _job_env(prof)
    words = viral_fx.clip_words(meta.get("transcript"), float(clip["start"]), float(clip["end"]))
    items = [it for it in (clip.get("broll") or []) if it.get("image") and os.path.exists(os.path.join(job_dir, it["image"]))]
    print(f"🎬 chain bench: {os.path.basename(pre_fx)[:70]} ({_ffprobe_duration(pre_fx):.1f} s, {len(words)} words, "
          f"{len(items)} B-roll image(s), style {plus.EDIT_STYLE}, hook {plus.HOOK_STYLE})")
    report = {"job": args.job, "clip": args.clip, "variants": {}}
    outs = {}
    # Near-lossless reference: every layer at qp 4 (a visually lossless x264), through the same code path.
    ref_args = ["-c:v", "libx264", "-preset", "fast", "-qp", "4"]
    import broll
    import hooks
    patched = [(m, m.layer_encode_args) for m in (ffu, viral_fx, broll, hooks)]
    for tag, on in (("legacy", False), ("hq", True), ("reference", None)):
        out = os.path.join(OUT_DIR, f"chain_{tag}.mp4")
        if tag == "reference":
            for m, _ in patched:
                m.layer_encode_args = lambda legacy, final=False: list(ref_args)
        try:
            with ffu.hq_chain(on):
                report["variants"][tag] = render_chain(pre_fx, words, clip, prof, items, job_dir, out, tag, print)
        finally:
            for m, orig in patched:
                m.layer_encode_args = orig
        outs[tag] = out
    for tag in ("legacy", "hq"):
        report["variants"][tag]["ssim_vs_reference"] = _ssim(outs[tag], outs["reference"])
        print(f"   SSIM {tag} vs reference: {report['variants'][tag]['ssim_vs_reference']}")
    # Dark crop at t = 10 s (or the middle of a shorter clip): the darkest 400x400 zone of the reference frame.
    from PIL import Image
    dur = _ffprobe_duration(pre_fx)
    t = 10.0 if dur > 14 else dur / 2
    frames = {tag: _frame(outs[tag], t, os.path.join(OUT_DIR, f"_f_{tag}.png")) for tag in outs}
    ref_l = Image.open(frames["reference"]).convert("L")
    W, H = ref_l.size
    best, box = None, None
    for y in range(0, H - 400, 40):
        for x in range(0, W - 400, 40):
            m = sum(ref_l.crop((x, y, x + 400, y + 400)).resize((20, 20)).getdata()) / 400
            if 6 <= m and (best is None or m < best):
                best, box = m, (x, y, x + 400, y + 400)
    box = box or (0, H - 400, 400, H)
    crops = []
    for tag in ("legacy", "hq", "reference"):
        p = os.path.join(OUT_DIR, f"_crop_{tag}.png")
        Image.open(frames[tag]).crop(box).save(p)
        _label(p, f"{tag} t={t:.0f}s")
        crops.append(p)
    _hstack(crops, os.path.join(OUT_DIR, "chain_dark_crop.jpg"))
    for k, tt in enumerate((t, min(dur - 1, t + 9))):
        fs = []
        for tag in ("legacy", "hq", "reference"):
            p = _frame(outs[tag], tt, os.path.join(OUT_DIR, f"_ff_{tag}.png"))
            _label(p, tag)
            fs.append(p)
        _hstack(fs, os.path.join(OUT_DIR, f"chain_frame_{k + 1}.jpg"), height=720)
    for p in glob.glob(os.path.join(OUT_DIR, "_f*_*.png")) + glob.glob(os.path.join(OUT_DIR, "_crop_*.png")):
        os.remove(p)
    report["dark_box"] = box
    with open(os.path.join(OUT_DIR, "chain_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(f"✅ chain bench written to {OUT_DIR} (chain_dark_crop.jpg, chain_frame_1.jpg, chain_frame_2.jpg, chain_report.json)")


# --- the look (before / after) ----------------------------------------------------------

# What the premium chantiers change, applied on top of the saved profile for the AFTER render.
AFTER_BROLL = {"layout": "mixed", "hold": None, "density": "normal", "max": 4, "hero_res": "std", "sfx": True}
AFTER_FX = {"hq_chain": True}


def _render_with_broll(pre_fx, meta, clip, prof, cfg, tag, keep_dir):
    """motion -> add_broll (planned and generated for real) -> hook -> captions, as main.py chains them.
    Returns (final path, items, seconds per layer)."""
    import broll
    import hooks
    import viral_fx
    start, end = float(clip["start"]), float(clip["end"])
    style = plus.EDIT_STYLE
    fx = dict(plus.FX)
    fx.pop("watermark", None)
    if clip.get("punchline_time") is not None:
        fx["hints"] = {"punchline_time": clip["punchline_time"]}
    words = viral_fx.clip_words(meta.get("transcript"), start, end)
    topic = viral_fx.topic_words(clip.get("video_title_for_youtube_short"), clip.get("viral_hook_text"))
    tmp = os.path.join(OUT_DIR, f"_tmp_{tag}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    os.makedirs(keep_dir, exist_ok=True)
    times = {}
    t0 = time.time()
    motion = os.path.join(tmp, "1_motion.mp4")
    viral_fx.apply_motion(pre_fx, words, style, motion, opts=fx)
    times["motion"] = round(time.time() - t0, 1)
    t0 = time.time()
    br = os.path.join(tmp, "2_broll.mp4")
    rep = broll.add_broll(motion, br, dict(clip), meta.get("transcript"), start, end, cfg, keep_dir=keep_dir,
                          keep_prefix=f"{tag}_")
    times["broll"] = round(time.time() - t0, 1)
    cur = br if rep and not rep.get("pending") and os.path.exists(br) else motion
    hook = clip.get("auto_hook") or {}
    text = hook.get("text") or clip.get("viral_hook_text")
    if text and prof["hook_style"] != "none":
        t0 = time.time()
        hk = os.path.join(tmp, "3_hooked.mp4")
        hooks.add_hook_to_video(cur, text, hk, position="top", duration=float(hook.get("duration_seconds") or prof["hook_seconds"]),
                                style=hook.get("style") or prof["hook_style"])
        times["hook"] = round(time.time() - t0, 1)
        cur = hk
    t0 = time.time()
    final = os.path.join(OUT_DIR, f"visual_{tag}.mp4")
    viral_fx.apply_captions(cur, words, style, final, watermark=prof["watermark"] or None, topic=topic)
    times["captions"] = round(time.time() - t0, 1)
    shutil.rmtree(tmp, ignore_errors=True)
    items = (rep or {}).get("items") or []
    with open(os.path.join(OUT_DIR, f"visual_{tag}_items.json"), "w", encoding="utf-8") as f:
        json.dump({"items": items, "seconds": times, "planner": (rep or {}).get("planner"), "cfg": cfg}, f, indent=1,
                  ensure_ascii=False)
    return final, items, times


def _describe(tag, items, dur, times):
    covered = sum(float(it.get("dur") or 0) for it in items)
    hero = next((it for it in items if it.get("layout") == "hero"), None)
    where = ", ".join("%ss/%ss %s" % (it["t"], it["dur"], it.get("style")) for it in items)
    hero_txt = ", hero at %s s for %s s" % (hero["t"], hero["dur"]) if hero else ""
    layouts = sorted(set(str(it.get("layout")) for it in items))
    print("   %s: %d image(s), %.1f s of %.0f s covered (%d %%), layouts %s, at %s%s; seconds %s"
          % (tag, len(items), covered, dur, round(100 * covered / max(dur, 1)), layouts, where, hero_txt, times))


def cmd_visual(args):
    # Everything imported up front: the bench runs for minutes and the code may be edited meanwhile.
    import ffmpeg_utils as ffu
    import ai_brain  # noqa: F401
    import broll  # noqa: F401
    import hooks  # noqa: F401
    import viral_fx  # noqa: F401
    from PIL import Image
    os.makedirs(OUT_DIR, exist_ok=True)
    job_dir, meta, clip, pre_fx = _find_clip(args.job, args.clip)
    prof = _profile(args.profile)
    _job_env(prof)
    os.environ.pop("PLUS_HQ_CHAIN", None)
    # A bench never writes into (nor reads from) the channel's notion memory: every picture is made afresh.
    os.environ["BROLL_NOTION_MEMORY"] = "0"
    dur = _ffprobe_duration(pre_fx)
    print(f"🎬 visual bench: {os.path.basename(pre_fx)[:70]} ({dur:.1f} s), profile '{prof['name']}', "
          f"style {plus.EDIT_STYLE}, hook {plus.HOOK_STYLE} {plus.HOOK_SECONDS} s")
    before = os.path.join(OUT_DIR, "visual_before.mp4")
    before_items = os.path.join(OUT_DIR, "visual_before_items.json")
    if args.before_cache and os.path.exists(before) and os.path.exists(before_items):
        with open(before_items, encoding="utf-8") as f:
            saved = json.load(f)
        b_items, b_times = saved["items"], saved.get("seconds") or {}
        print("   before: reused from the previous run")
    else:
        cfg = {**plus.BROLL, "enabled": True}
        with ffu.hq_chain(False):
            before, b_items, b_times = _render_with_broll(pre_fx, meta, clip, prof, cfg, "before",
                                                          os.path.join(OUT_DIR, "visual_before_images"))
    _describe("before", b_items, dur, b_times)
    cfg = {**plus.BROLL, "enabled": True, **AFTER_BROLL}
    prof_after = dict(prof)   # the look is the house recipe (plus.FX); AFTER_FX kept for the report
    with ffu.hq_chain(True):
        after, a_items, a_times = _render_with_broll(pre_fx, meta, clip, prof_after, cfg, "after",
                                                     os.path.join(OUT_DIR, "visual_after_images"))
    _describe("after", a_items, dur, a_times)

    # Six instants: the hero coming in, holding and leaving, two cards, and a moment with the face alone.
    instants = []
    hero = next((it for it in a_items if it.get("layout") == "hero"), None)
    if hero:
        instants += [("hero_in", hero["t"] + 0.25), ("hero_mid", hero["t"] + hero["dur"] / 2),
                     ("hero_out", hero["t"] + hero["dur"] - 0.2)]
    for k, it in enumerate([it for it in a_items if it.get("layout") != "hero"][:3]):
        instants.append((f"card{k + 1}", it["t"] + min(1.0, it["dur"] / 2)))
    instants.append(("plain", hero["t"] - 1.2 if hero and hero["t"] > 6 else 5.0))
    for k, it in enumerate(b_items):
        if len(instants) >= 6:
            break
        instants.append((f"before_img{k + 1}", it["t"] + 1.0))
    instants = instants[:6]
    sheets = []
    for k, (label, t) in enumerate(instants):
        t = max(0.2, min(dur - 0.2, t))
        fb = _frame(before, t, os.path.join(OUT_DIR, "_fb.png"))
        fa = _frame(after, t, os.path.join(OUT_DIR, "_fa.png"))
        _label(fb, f"before  {label}  {t:.1f}s")
        _label(fa, f"after  {label}  {t:.1f}s")
        sheets.append(_hstack([fb, fa], os.path.join(OUT_DIR, f"visual_f{k + 1}_{label}.jpg"), height=720))
    for p in ("_fb.png", "_fa.png"):
        if os.path.exists(os.path.join(OUT_DIR, p)):
            os.remove(os.path.join(OUT_DIR, p))
    # One contact sheet of the six pairs, three per row.
    tiles = [Image.open(p).convert("RGB") for p in sheets]
    tw = 600
    tiles = [im.resize((tw, int(im.height * tw / im.width)), Image.LANCZOS) for im in tiles]
    th = max(im.height for im in tiles)
    cols = 3
    rows = -(-len(tiles) // cols)
    sheet = Image.new("RGB", (cols * tw + (cols - 1) * 8, rows * th + (rows - 1) * 8), (24, 24, 24))
    for k, im in enumerate(tiles):
        sheet.paste(im, ((k % cols) * (tw + 8), (k // cols) * (th + 8)))
    sheet.save(os.path.join(OUT_DIR, "visual_sheet.jpg"), quality=90)
    # The two clips side by side, to watch.
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", before, "-i", after, "-filter_complex",
                    "[0:v]scale=540:-2[a];[1:v]scale=540:-2[b];[a][b]hstack=2[v]", "-map", "[v]", "-map", "1:a?",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", os.path.join(OUT_DIR, "visual_side_by_side.mp4")], check=True)
    print(f"✅ visual bench written to {OUT_DIR}: visual_sheet.jpg, visual_f1..6_*.jpg, visual_side_by_side.mp4, "
          f"visual_before.mp4, visual_after.mp4")


# --- the brain (B-roll v2): planner + art direction + pictures + review, no video cut -----------------

BRAIN_DIR = os.path.join(HERE, "output", "_test_broll", "brain")
# Named versions of the brain: cfg keys laid over plus.BROLL (the house recipe). On the command line a
# version is "name" or "name:key=value;key=value" (its keys laid over the named one, or over "current").
VERSIONS = {
    "current": {},
    "art": {"art_director": True},            # chantier A: the art director writes the prompts
    "v2": {"art_director": True},             # the same, run again after each later chantier (its own boards)
    "v3": {},                                 # the recipe as it stands (E review, H faces, F notions), its own boards
    "v4": {},                                 # with the episode's visual bible (J), the visual argument (K), the hero takes (L)
    "v5": {},                                 # the thing named first (audit « sens », 1-oct evening), faces everywhere
    "v6": {},                                 # the episode's registers (vision, cosmos, math...) written by the bible
    "v7": {},                                 # the prohibitions rebuilt (three verdicts, worth, counted filters, lighter editor)
    "v8": {},                                 # the editor cut to its nine rules, the schema enum as the style rule
    "v9": {},                                 # the look read from what is said: moods, look sheets, computed grades
    "v10": {},                                # the experience, not the setting (registers of kind inner), suffering first
    "v11": {},                                # v10 + a set phrase is not an image (editor and review)
    "v12": {},                                # gravity: only a death is sober; no positive example; empty place; candidates
    "v13": {"mode": "adaptive"},              # v12 + thing or meaning moment by moment, the strongest hero, the parallel
}
GROUP_S = 2.5   # two pictures closer than this (or on the same sentence) show the same moment
BOARD_W = 1500
THUMB_W, THUMB_H = 420, 300


def _value(s):
    """A command-line value -> bool / int / float / str."""
    s = s.strip()
    if s.lower() in ("1", "true", "on", "yes"):
        return True
    if s.lower() in ("0", "false", "off", "no"):
        return False
    for cast in (int, float):
        try:
            return cast(s)
        except ValueError:
            pass
    return s


def _version(spec):
    """"name" or "name:key=value;key=value" -> (name, cfg overrides)."""
    name, _, rest = spec.partition(":")
    name = name.strip() or "current"
    if name not in VERSIONS and not rest.strip():
        raise ValueError(f"unknown version '{name}' (known: {', '.join(VERSIONS)})")
    over = dict(VERSIONS.get(name, {}))
    for kv in filter(None, (p.strip() for p in rest.split(";"))):
        k, eq, v = kv.partition("=")
        if not k.strip() or not eq:
            raise ValueError(f"bad override '{kv}' (want key=value)")
        over[k.strip()] = _value(v)
    return name, over


def aligned_moments(job8, n, versions):
    """The moments the given versions illustrated on clip ``n``, one per moment: [{"t", "time", "anchor", "said"}] by
    time. Two pictures on the same sentence (half its words in common) or within a second are one moment; the earliest
    version listed gives its anchor and sentence."""
    items = []
    for v in versions:
        path = os.path.join(BRAIN_DIR, f"{job8}_clip{n}_{v}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            res = json.load(f)
        for it in res.get("items") or []:
            if it.get("source") == "screen" or not it.get("anchor"):
                continue
            items.append({"t": float(it["t"]), "anchor": it["anchor"], "said": it.get("said") or "", "v": v})
    rank = {v: i for i, v in enumerate(versions)}

    def words_of(it):
        return set(re.findall(r"[a-z0-9']+", it["said"].lower()))

    def same_moment(a, b):
        # the same sentence (half its words in common, the excerpts start at different words), or the same second
        wa, wb = words_of(a), words_of(b)
        if wa and wb and len(wa & wb) / len(wa | wb) >= 0.5:
            return True
        return abs(a["t"] - b["t"]) <= 1.0

    groups = []
    for it in sorted(items, key=lambda i: i["t"]):
        g = next((g for g in groups if any(same_moment(it, m) for m in g)), None)
        if g is None:
            groups.append([it])
        else:
            g.append(it)
    groups = [{"t": min(m["t"] for m in g), "best": min(g, key=lambda m: (rank[m["v"]], m["t"])), "members": g}
              for g in groups]
    out = []
    for g in sorted(groups, key=lambda g: g["t"]):
        b = g["best"]
        # the anchor's spoken time: an item lands KEY_LEAD before its key word
        out.append({"t": round(b["t"], 2), "time": round(b["t"] + 0.12, 2), "anchor": b["anchor"], "said": b["said"]})
    return out


def _find_job(job):
    """output/<job> by its full id or a prefix -> (job_dir, meta)."""
    out = os.path.join(HERE, "output")
    dirs = [d for d in os.listdir(out) if d.startswith(job) and os.path.isdir(os.path.join(out, d))] if os.path.isdir(out) else []
    dirs = [d for d in dirs if d == job] or dirs
    if len(dirs) != 1:
        raise SystemExit(f"job '{job}': " + ("no such job" if not dirs else "several jobs match: " + ", ".join(d[:8] for d in dirs)))
    job_dir = os.path.join(out, dirs[0])
    metas = glob.glob(os.path.join(glob.escape(job_dir), "*_metadata.json"))
    if not metas:
        raise SystemExit(f"no metadata in {job_dir}")
    with open(metas[0], encoding="utf-8") as f:
        return job_dir, json.load(f)


def _clip_of(job_dir, meta, n):
    if not 1 <= n <= len(meta.get("shorts") or []):
        raise SystemExit(f"clip {n}: the job has {len(meta.get('shorts') or [])} clip(s)")
    pre = glob.glob(os.path.join(glob.escape(job_dir), f"*_clip_{n}.pre_fx.mp4"))
    if not pre:
        raise SystemExit(f"no .pre_fx.mp4 for clip {n} in {job_dir} (the bench needs a Clip Generator++ render)")
    return meta["shorts"][n - 1], pre[0]


def _full_brief(meta):
    """The episode brief with its glossary and stories (what the B-roll planner reads). A job made without
    B-roll kept only the short brief: the episode is read again here (ai_cache remembers the answer)."""
    import ai_brain
    brief = meta.get("episode_brief") or None
    if brief and (brief.get("glossary") or brief.get("stories")):
        return brief, "from the job"
    print("   📖 The job's brief has no glossary: reading the whole episode again (the B-roll brief)...", flush=True)
    return ai_brain.episode_brief(meta.get("transcript")), "read again"


class _Watch:
    """Watches the brain at work on one clip: the planner's moments, every review, the exact text, seed and
    size of every picture asked from ComfyUI, and the seconds per step. Patches broll's module globals
    (add_broll looks them up at call time) and puts them back."""

    NAMES = ("plan_with_claude", "plan_with_gemini", "direct_art", "review_images", "local_image", "_graph")

    def __init__(self, broll):
        self.broll = broll
        self.moments, self.reviews, self.sent, self.seconds = [], [], {}, {}
        self.final = None   # the moments the art director got: the pictures' own list (after the experience guard)
        self.images, self._current, self._depth = 0, None, 0

    def _timed(self, key, fn, *a, **kw):
        t0 = time.time()
        try:
            return fn(*a, **kw)
        finally:
            self.seconds[key] = round(self.seconds.get(key, 0.0) + time.time() - t0, 1)

    def __enter__(self):
        b = self.broll
        self._orig = {k: getattr(b, k) for k in self.NAMES}
        orig = self._orig

        def plan(*a, **kw):
            out = self._timed("plan", orig["plan_with_claude"], *a, **kw)
            self.moments = [dict(m) for m in out]
            return out

        def art(*a, **kw):
            self.final = [dict(m) for m in (a[0] if a else kw.get("moments") or [])]
            return self._timed("art", orig["direct_art"], *a, **kw)

        def plan_gemini(*a, **kw):
            out = self._timed("plan", orig["plan_with_gemini"], *a, **kw)
            self.moments = [dict(m) for m in out]
            return out

        def review(cands, words):
            # review_images calls itself (the hero to the judge, the cards their own way): the outermost call
            # alone is timed and recorded, once per picture.
            self._depth += 1
            try:
                out = (self._timed("review", orig["review_images"], cands, words) if self._depth == 1
                       else orig["review_images"](cands, words))
            finally:
                self._depth -= 1
            if self._depth == 0:
                for c, r in zip(cands, out):
                    self.reviews.append({"file": os.path.basename(c["file"]), "k": c.get("k"), "layout": c.get("layout"),
                                         **{kk: vv for kk, vv in (r or {}).items() if kk != "file"}})
            return out

        def image(prompt, style, out_path, *a, **kw):
            self._current = os.path.basename(out_path)
            self.images += 1
            return self._timed("gpu", orig["local_image"], prompt, style, out_path, *a, **kw)

        def graph(engine, text, seed, width=768, height=1344, *a, **kw):
            g = orig["_graph"](engine, text, seed, width, height, *a, **kw)
            steps = next((n["inputs"].get("steps") for n in g.values() if n.get("class_type") == "KSampler"), None)
            self.sent[self._current or f"image_{len(self.sent)}"] = {"text": text, "seed": seed, "size": [width, height],
                                                                   "steps": steps}
            return g

        for k, fn in (("plan_with_claude", plan), ("plan_with_gemini", plan_gemini), ("direct_art", art), ("review_images", review),
                      ("local_image", image), ("_graph", graph)):
            setattr(b, k, fn)
        return self

    def __exit__(self, *exc):
        for k, v in self._orig.items():
            setattr(self.broll, k, v)
        return False


def _final(broll, w):
    """The moments the pictures were made for, in order (broll.LAST_PICTURED, after the experience guard and the
    sober pictures not rewritten), else what the art director got, else the planner's."""
    pictured = [dict(m) for m in getattr(broll, "LAST_PICTURED", None) or []]
    return pictured or (w.final if w.final is not None else w.moments)


def _k_of(name):
    """broll_3.jpg / broll_3_v2.jpg -> 3."""
    m = re.search(r"broll_(\d+)", str(name or ""))
    return int(m.group(1)) if m else None


def _plan_clip(job_dir, meta, n, clip, pre_fx, prof, version, over, tag):
    """The whole brain on one clip, pictures kept in BRAIN_DIR/<tag>_images, nothing cut into the video
    (add_broll in its manual-review mode). Returns everything the board and the JSON need."""
    import ai_brain
    import broll
    keep = os.path.join(BRAIN_DIR, f"{tag}_images")
    shutil.rmtree(keep, ignore_errors=True)
    os.makedirs(keep)
    planner = "gemini" if prof["brain"]["stages"]["broll"] == "gemini" else "claude"
    cfg = {**plus.BROLL, "enabled": True, "planner": planner, "review": "manual", **over}
    start, end = float(clip["start"]), float(clip["end"])
    c = dict(clip)
    inset = c.get("screen_inset")
    if inset and inset.get("image"):
        c["screen_inset"] = {**inset, "path": os.path.join(job_dir, inset["image"])}
    u0 = dict(ai_brain.USAGE)
    t0 = time.time()
    with _Watch(broll) as w:
        rep = broll.add_broll(pre_fx, os.path.join(keep, "not_written.mp4"), c, meta.get("transcript"), start, end,
                              cfg, keep_dir=keep, keep_prefix="", ground_hook=False)
    seconds = {**w.seconds, "total": round(time.time() - t0, 1)}
    usage = {k: ai_brain.USAGE[k] - u0[k] for k in u0}
    items = [dict(it) for it in (rep or {}).get("items") or []]
    for it in items:
        k = _k_of(it.get("image"))
        it["k"] = k
        final = _final(broll, w)                                    # broll_<k> is the k-th picture of THIS list
        if k is not None and k < len(final):
            m = final[k]
            it.update(said=m.get("said"), shot=m.get("shot"), planner_hero=bool(m.get("hero")), key=m.get("key"),
                      hero_why=m.get("hero_why"))
        # The exact text ComfyUI got for the picture that was kept: the one whose text opens with the item's
        # prompt (the redo's when the redo was kept); else the first picture made for this moment.
        cands = [(name, s) for name, s in w.sent.items() if _k_of(name) == k]
        exact = next((s for _n, s in cands if it.get("prompt") and s["text"].startswith(it["prompt"][:60])), None)
        it["sent"] = exact or (cands[0][1] if cands else None)
    thesis = next((m.get("thesis") for m in w.moments if m.get("thesis")), "")
    sheet = next((m.get("sheet") for m in w.moments if m.get("sheet")), None)
    kept = {it["k"] for it in items if it.get("k") is not None}
    final = _final(broll, w)
    dropped = []
    for k, m in enumerate(final):
        if k in kept:
            continue
        rs = [r for r in w.reviews if r.get("k") == k]
        dropped.append({"k": k, "t": m.get("t"), "anchor": m.get("anchor"), "subject": m.get("subject"),
                        "layout": "hero" if m.get("hero") else "card", "why": "review" if rs else "no picture",
                        "scores": [r.get("score") for r in rs], "problem": (rs[-1].get("problem") if rs else "") or ""})
    final_t = {round(float(m.get("t") or 0), 2) for m in final}
    for m in w.moments:
        if round(float(m.get("t") or 0), 2) not in final_t:
            # planned, then left out before any picture: the experience guard (cap, a sober picture not rewritten)
            dropped.append({"k": None, "t": m.get("t"), "anchor": m.get("anchor"), "subject": m.get("subject"),
                            "layout": "card", "why": "guard", "scores": [], "problem": "left out before the picture"})
    return {"job": os.path.basename(job_dir), "clip": n, "version": version, "overrides": over,
            "duration": round(end - start, 2), "title": clip.get("video_title_for_youtube_short") or "",
            "hook": clip.get("viral_hook_text") or "", "thesis": thesis, "sheet": sheet,
            "hero_options": next((m.get("hero_options") for m in w.moments if m.get("hero_options")), []),
            "final": _final(broll, w),
            "sequence": [m.get("subject") for m in w.moments if m.get("subject")],
            "planner": (rep or {}).get("planner"), "moments": w.moments, "items": items, "reviews": w.reviews,
            "sent": w.sent, "dropped": dropped, "skipped": list(getattr(broll, "LAST_SKIPS", []) or []),
            "seconds": seconds, "usage": usage, "images_made": w.images,
            "images_dir": keep, "cfg": cfg}


# --- the board: one picture per line, its prompt and its scores, to judge by eye ----------------------

def _font(size, bold=False):
    from PIL import ImageFont
    for p in (f"/usr/share/fonts/truetype/liberation/LiberationSans-{'Bold' if bold else 'Regular'}.ttf",
              os.path.join(HERE, "fonts", "Montserrat-ExtraBold.ttf")):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(text, font, width):
    lines, cur = [], ""
    for w in str(text or "").split():
        t = f"{cur} {w}".strip()
        if font.getlength(t) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


_C_BG, _C_HEAD, _C_LABEL, _C_BODY, _C_DIM, _C_SENT = (20, 20, 22), (242, 242, 242), (255, 216, 77), (214, 214, 214), (140, 140, 140), (160, 172, 184)


def _score_colour(s):
    try:
        s = int(s)
    except (TypeError, ValueError):
        return _C_DIM
    return (120, 220, 120) if s >= 4 else (240, 200, 90) if s == 3 else (240, 110, 110)


def _board(res, out_path):
    """The clip's brain on one picture: header (title, hook, thesis, look), one row per kept picture
    (thumbnail as graded, prompt, the exact text sent, the review), the moments dropped, the cost."""
    from PIL import Image, ImageDraw
    import broll
    f_h, f_b, f_t, f_s = _font(26, True), _font(19, True), _font(18), _font(15)
    M, GAP = 24, 16
    x_txt = M + THUMB_W + 30
    w_txt = BOARD_W - x_txt - M

    def block(font, text, colour, width=None, indent=0):
        return [(font, line, colour, indent) for line in _wrap(text, font, (width or w_txt) - indent)]

    def height(lines):
        return sum(int(f.size * 1.35) for f, _l, _c, _i in lines)

    head = block(f_h, f"{res['job'][:8]} · clip {res['clip']} · version {res['version']} · {res['duration']:.1f} s", _C_HEAD, BOARD_W - 2 * M)
    head += block(f_b, f"TITLE  {res.get('title') or '-'}", _C_HEAD, BOARD_W - 2 * M)
    head += block(f_t, f"HOOK  {res.get('hook') or '-'}", _C_BODY, BOARD_W - 2 * M)
    head += block(f_t, f"THESIS  {res.get('thesis') or '-'}", _C_BODY, BOARD_W - 2 * M)
    if res.get("hero_options"):
        head += block(f_s, "HERO OPTIONS  " + " | ".join(f"{o.get('picture')} ({o.get('why')})" for o in res["hero_options"]), _C_DIM, BOARD_W - 2 * M)
    if res.get("sheet"):
        head += block(f_t, "LOOK  " + "; ".join(f"{k}: {v}" for k, v in res["sheet"].items()), _C_BODY, BOARD_W - 2 * M)
    if res.get("sequence"):
        head += block(f_t, "SEQUENCE  " + " -> ".join(res["sequence"]), _C_BODY, BOARD_W - 2 * M)
    if res.get("overrides"):
        head += block(f_s, "overrides  " + json.dumps(res["overrides"], ensure_ascii=False), _C_DIM, BOARD_W - 2 * M)

    rows = []
    for it in res.get("items") or []:
        lines = []
        tag = {"hero": "HERO", "card": "CARD"}.get(it.get("layout"), str(it.get("layout") or "").upper())
        if it.get("source") == "screen":
            tag = "SOURCE PICTURE"
        line1 = (f"#{it.get('k') if it.get('k') is not None else '-'}  {tag}  {float(it['t']):.1f} s +{float(it['dur']):.1f} s   "
                 f"{it.get('style') or '-'}" + (f" / {it['family']}" if it.get("family") else "")
                 + f"   shot {it.get('shot') or '-'} · role {it.get('role') or '-'}")
        mood_line = _mood_line(it)
        if it.get("notion"):
            line1 += f"   notion « {it['notion']} »" + (" (reused)" if it.get("reused") else "")
        if it.get("planner_hero"):
            line1 += "   planner's hero"
        if it.get("take"):
            line1 += f"   take {it['take']}"
        lines += block(f_b, line1, _C_LABEL)
        if mood_line:
            lines += block(f_s, mood_line, _C_SENT)
        if it.get("hero_why"):
            lines += block(f_s, f"why this hero: {it['hero_why']}", _C_DIM)
        # "look" on an item is the card's drawing ("premium"); the review's look score (chantier E) is "look_score".
        lines += block(f_b, f"score {it.get('score', '-')}" + (f"   look {it['look_score']}" if it.get("look_score") is not None else ""),
                       _score_colour(it.get("score")))
        lines += block(f_t, f"“{it.get('anchor') or ''}”" + (f"  —  said: {it['said']}" if it.get("said") else ""), _C_BODY)
        if it.get("idea"):
            lines += block(f_t, f"idea: {it['idea']}", _C_BODY)
        if it.get("source") != "screen":
            if it.get("art"):
                lines += block(f_s, f"EDITOR'S DRAFT: {it.get('prompt_editor') or '-'}", _C_DIM)
            lines += block(f_t, f"{'ART DIRECTOR' if it.get('art') else 'PROMPT'} ({len(it.get('prompt') or '')} chars): "
                                f"{it.get('prompt') or ''}", _C_HEAD)
            sent = it.get("sent") or {}
            if sent:
                lines += block(f_s, f"SENT TO Z-IMAGE ({len(sent['text'])} chars, {len(sent['text'].split())} words, "
                                    f"{sent['size'][0]}x{sent['size'][1]}, {sent.get('steps')} steps, seed {sent.get('seed')}): {sent['text']}",
                               _C_SENT)
        for r in (r for r in res.get("reviews") or [] if r.get("k") == it.get("k")):
            which = "redo" if str(r.get("file", "")).endswith("_v2.jpg") else "review"
            txt = f"{which} {r.get('file')}: score {r.get('score')}"
            if r.get("seen"):
                txt += f" — seen: {r['seen']}"
            if r.get("problem"):
                txt += f" — problem: {r['problem']}"
            lines += block(f_s, txt, _score_colour(r.get("score")), indent=12)
            if r.get("better_prompt"):
                lines += block(f_s, f"better prompt: {r['better_prompt']}", _C_DIM, indent=12)
        img = None
        for folder in (res.get("images_dir") or "", os.path.join(HERE, "output", res["job"])):
            p = os.path.join(folder, str(it.get("image") or ""))
            if it.get("image") and os.path.exists(p):
                img = p
                break
        rows.append((it, img, lines))

    tail = []
    if res.get("dropped"):
        tail += block(f_b, "NOT KEPT", _C_LABEL, BOARD_W - 2 * M)
        for d in res["dropped"]:
            why = f"scores {d['scores']}" if d.get("scores") else "no picture"
            tail += block(f_t, f"#{d['k']} {d['layout']} “{d.get('anchor') or ''}” ({d.get('subject') or '-'}) — {why}"
                               + (f": {d['problem']}" if d.get("problem") else ""), _C_DIM, BOARD_W - 2 * M, indent=12)
    if not rows:
        tail += block(f_b, "No picture planned for this clip.", _C_LABEL, BOARD_W - 2 * M)
    s, u = res.get("seconds") or {}, res.get("usage") or {}
    tail += block(f_t, f"plan {s.get('plan', 0):.0f} s · art {s.get('art', 0):.0f} s · {res.get('images_made', 0)} picture(s) on ComfyUI {s.get('gpu', 0):.0f} s · "
                       f"review {s.get('review', 0):.0f} s · total {s.get('total', 0):.0f} s   —   Claude {u.get('calls', 0)} call(s): "
                       f"{u.get('input_tokens', 0):,} read / {u.get('output_tokens', 0):,} written   —   planner {res.get('planner')}",
                  _C_DIM, BOARD_W - 2 * M)

    row_h = [max(THUMB_H if img else 0, height(lines)) + GAP for _it, img, lines in rows]
    H = M + height(head) + GAP + sum(row_h) + GAP + height(tail) + M
    board = Image.new("RGB", (BOARD_W, H), _C_BG)
    d = ImageDraw.Draw(board)

    def draw(lines, x, y):
        for f, line, colour, indent in lines:
            d.text((x + indent, y), line, fill=colour, font=f)
            y += int(f.size * 1.35)
        return y

    y = draw(head, M, M) + GAP
    for (it, img, lines), rh in zip(rows, row_h):
        d.line((M, y - GAP // 2, BOARD_W - M, y - GAP // 2), fill=(50, 50, 54), width=1)
        if img:
            im = Image.open(img).convert("RGB")
            if it.get("grade"):
                im = broll._grade_colour(im, it["grade"])
            scale = min(THUMB_W / im.width, THUMB_H / im.height)
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
            board.paste(im, (M + (THUMB_W - im.width) // 2, y))
        draw(lines, x_txt, y)
        y += rh
    d.line((M, y - GAP // 2, BOARD_W - M, y - GAP // 2), fill=(50, 50, 54), width=1)
    draw(tail, M, y + GAP // 2)
    board.save(out_path, quality=90)
    return out_path


def _mood_line(it):
    """The picture's mood, grade and pixel check, in one line for its board row ("" without a mood)."""
    import visual_mood
    m, g, px = it.get("mood") or {}, it.get("grade"), it.get("pixels") or {}
    if not m:
        return ""
    out = f"MOOD {visual_mood.describe(m)}" + (f" («{m['cue']}»)" if m.get("cue") else "")
    if m.get("colours_said"):
        out += f" — speaker's colours: {m['colours_said']}"
    if it.get("mood_base"):
        out += f" — clip base {visual_mood.describe(it['mood_base'])}"
    if isinstance(g, dict):
        out += (f"   GRADE sat {g.get('sat')} contrast {g.get('contrast')} temp {g.get('temp'):+g} lift {g.get('lift')} "
                f"gamma {g.get('gamma')} sig {g.get('sig')}")
    if px.get("raw"):
        t = px.get("target") or {}
        out += "   PIXELS " + ", ".join(f"{k} {px['raw'][k]}->{(px.get('after') or {}).get(k)}"
                                       + (f" [{t[k][0]:g}-{t[k][1]:g}]" if k in t else "") for k in ("key", "contrast", "chroma"))
        if px.get("moved"):
            out += f" (moved {', '.join(px['moved'])})"
        if px.get("gap"):
            out += f" GAP {'; '.join(px['gap'])}"
    return out


def _signature_sheet(res, sigs, out_path):
    """Every kept picture of a run, raw then graded at each signature strength in ``sigs`` (the same picture, the
    same grade, only the stamp moves; a picture whose colours the speaker gives keeps none). None without one."""
    from PIL import Image, ImageDraw
    import broll
    rows = []
    for it in res.get("items") or []:
        if not isinstance(it.get("grade"), dict) or not it.get("image"):
            continue
        path = os.path.join(res.get("images_dir") or "", it["image"])
        if not os.path.exists(path):
            continue
        im = Image.open(path).convert("RGB")
        k = 300 / im.height
        im = im.resize((max(1, int(im.width * k)), 300), Image.LANCZOS)
        said = bool((it.get("mood") or {}).get("colours_said"))
        cells = [("raw", im)] + [(f"signature {int(round(s * 100))} %" + (" (speaker's colours: none)" if said else ""),
                                  broll._grade_colour(im, {**it["grade"], "sig": 0.0 if said else s})) for s in sigs]
        rows.append((f"#{it.get('k')} {it.get('subject') or it.get('anchor') or ''} — {_mood_line(it)[:150]}", cells))
    if not rows:
        return None
    f_l = _font(16)
    pad, head = 12, 26
    w = max(sum(c.width for _l, c in cells) + pad * (len(cells) + 1) for _t, cells in rows)
    h = sum(head + 300 + 22 + pad for _r in rows) + pad
    sheet = Image.new("RGB", (w, h), _C_BG)
    d = ImageDraw.Draw(sheet)
    y = pad
    for title, cells in rows:
        d.text((pad, y), title, fill=_C_LABEL, font=f_l)
        y += head
        x = pad
        for label, im in cells:
            sheet.paste(im, (x, y))
            d.text((x, y + 304), label, fill=_C_BODY, font=f_l)
            x += im.width + pad
        y += 300 + 22 + pad
    sheet.save(out_path, quality=90)
    return out_path


def _sigs(spec):
    return [float(x) for x in str(spec or "").split(",") if x.strip()]


def _dedupe_reviews(reviews):
    """One review per picture file, the last one recorded (runs made before the spy counted its depth)."""
    by_file = {}
    for r in reviews or []:
        by_file[r.get("file")] = r
    return list(by_file.values())


def cmd_board(args):
    """The boards again from the JSON of an earlier run (no model, no GPU): after a change of the board, or of a
    run recorded with a flaw."""
    job_dir, _meta = _find_job(args.job)
    job8 = os.path.basename(job_dir)[:8]
    clips = [int(x) for x in str(args.clips).split(",") if x.strip()]
    names = [v.strip().split(":")[0] for v in str(args.versions).split(",") if v.strip()]
    for n in clips:
        for name in names:
            tag = f"{job8}_clip{n}_{name}"
            path = os.path.join(BRAIN_DIR, tag + ".json")
            if not os.path.exists(path):
                print(f"   no run recorded for {tag}")
                continue
            with open(path, encoding="utf-8") as f:
                res = json.load(f)
            res["reviews"] = _dedupe_reviews(res.get("reviews"))
            with open(path, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False)
            _board(res, os.path.join(BRAIN_DIR, tag + ".jpg"))
            print(f"   {tag}.jpg")
            if _sigs(getattr(args, "signatures", None)) and _signature_sheet(res, _sigs(args.signatures),
                                                                            os.path.join(BRAIN_DIR, tag + "_signatures.jpg")):
                print(f"   {tag}_signatures.jpg")
        on_disk = [p for p in glob.glob(os.path.join(glob.escape(BRAIN_DIR), f"{job8}_clip{n}_*.jpg"))
                   if not p.endswith("_compare.jpg")]
        on_disk.sort(key=lambda p: (not p.endswith("_current.jpg"), os.path.getmtime(p)))
        if len(on_disk) > 1:
            _hstack(on_disk, os.path.join(BRAIN_DIR, f"{job8}_clip{n}_compare.jpg"))


def cmd_plan(args):
    """Planner + art direction + pictures + review on the chosen clips, one board and one JSON per clip and
    version, the versions side by side when there are two. No video is cut."""
    import ai_brain
    import broll
    os.makedirs(BRAIN_DIR, exist_ok=True)
    job_dir, meta = _find_job(args.job)
    clips = [int(x) for x in str(args.clips).split(",") if x.strip()]
    try:
        versions = [_version(v) for v in str(args.versions).split(",") if v.strip()] or [("current", {})]
    except ValueError as e:
        raise SystemExit(str(e))
    prof = _profile(args.profile)
    _job_env(prof)
    # A bench never reads nor writes the channel's notion memory: every picture is made afresh.
    os.environ["BROLL_NOTION_MEMORY"] = "0"
    if args.fresh:
        os.environ["AI_CACHE_REFRESH"] = "1"
    if not broll.comfy_available():
        raise SystemExit(f"ComfyUI not reachable at {broll._comfy_url()} (start it in Pinokio)")
    brief, how = _full_brief(meta)
    ai_brain.EPISODE_BRIEF = brief
    # The episode's visual bible: the job's when it has the episode's mood (B-roll « ambiance »), else made now (one
    # call, remembered by ai_cache).
    bible = meta.get("episode_bible") or None
    if bible and not bible.get("mood"):
        bible = None
    if bible:
        ai_brain.EPISODE_BIBLE = bible
    elif brief and not args.no_bible:
        print("   🎨 No visual bible in the job: reading the episode for it...", flush=True)
        bible = ai_brain.episode_bible(brief, meta.get("transcript"))
    else:
        ai_brain.EPISODE_BIBLE = None
    job8 = os.path.basename(job_dir)[:8]
    print(f"🧠 brain bench: job {job8}, clips {clips}, versions {[v for v, _ in versions]}; brief {how} "
          f"({len((brief or {}).get('glossary') or [])} notions, {len((brief or {}).get('stories') or [])} stories); "
          f"profile '{prof['name']}', planner {os.environ.get('BRAIN_BROLL')} effort {os.environ.get('CLAUDE_EFFORT_BROLL')}, "
          f"review {os.environ.get('BRAIN_IMAGE_REVIEW')}", flush=True)
    summary = []
    broll._comfy_enter()     # the models stay in VRAM from one clip to the next
    try:
        for n in clips:
            clip, pre_fx = _clip_of(job_dir, meta, n)
            boards = []
            fixed = aligned_moments(job8, n, args.moments.split(":", 1)[1].split(",")) \
                if str(getattr(args, "moments", "") or "").startswith("aligned:") else None
            if fixed:
                print(f"   📌 {len(fixed)} fixed moment(s): " + " | ".join(f"{f['time']:.1f} s {f['anchor']}" for f in fixed), flush=True)
            for name, over in versions:
                if fixed:
                    over = {**over, "fixed_moments": fixed}
                tag = f"{job8}_clip{n}_{name}"
                print(f"\n▶ clip {n} · {name}: {clip.get('video_title_for_youtube_short')}", flush=True)
                res = _plan_clip(job_dir, meta, n, clip, pre_fx, prof, name, over, tag)
                with open(os.path.join(BRAIN_DIR, tag + ".json"), "w", encoding="utf-8") as f:
                    json.dump(res, f, indent=1, ensure_ascii=False)
                boards.append(_board(res, os.path.join(BRAIN_DIR, tag + ".jpg")))
                if _sigs(args.signatures):
                    _signature_sheet(res, _sigs(args.signatures), os.path.join(BRAIN_DIR, tag + "_signatures.jpg"))
                scores = [it.get("score") for it in res["items"] if it.get("score") is not None]
                row = {"clip": n, "version": name, "images": len(res["items"]), "made": res["images_made"],
                       "hero": any(it.get("layout") == "hero" for it in res["items"]),
                       "pixel_gaps": sum(bool((it.get("pixels") or {}).get("gap")) for it in res["items"]),
                       "experience": sum(broll.is_inner({"style": it.get("style"), "mood": it.get("mood")}) for it in res["items"]),
                       "scores": scores, "dropped": len(res["dropped"]), "seconds": res["seconds"], "usage": res["usage"]}
                summary.append(row)
                print(f"   {name}: {row['images']} kept of {row['made']} made ({row['experience']} experience), scores {scores}, hero {row['hero']}, "
                      f"{res['seconds']} s, Claude {res['usage']['calls']} call(s) "
                      f"{res['usage']['input_tokens']:,}/{res['usage']['output_tokens']:,} -> {tag}.jpg", flush=True)
            # Side by side with every version of this clip already on disk ("current" first, then by age), so a
            # version can be run alone and still be compared with the ones made before.
            on_disk = [p for p in glob.glob(os.path.join(glob.escape(BRAIN_DIR), f"{job8}_clip{n}_*.jpg"))
                       if not p.endswith("_compare.jpg")]
            on_disk.sort(key=lambda p: (not p.endswith("_current.jpg"), os.path.getmtime(p)))
            if len(on_disk) > 1:
                _hstack(on_disk, os.path.join(BRAIN_DIR, f"{job8}_clip{n}_compare.jpg"))
    finally:
        broll._comfy_leave()
    with open(os.path.join(BRAIN_DIR, f"{job8}_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"job": os.path.basename(job_dir), "clips": clips, "versions": [v for v, _ in versions],
                   "rows": summary}, f, indent=1, ensure_ascii=False)
    for name, _o in versions:
        rows = [r for r in summary if r["version"] == name]
        scores = [s for r in rows for s in r["scores"]]
        print(f"\n{name}: {sum(r['images'] for r in rows)} picture(s) kept of {sum(r['made'] for r in rows)} made on "
              f"{len(rows)} clip(s), mean score {sum(scores) / len(scores):.2f}" if scores else f"\n{name}: no picture kept",
              end="")
        print(f", {sum(r['seconds'].get('total', 0) for r in rows):.0f} s in all "
              f"(plan {sum(r['seconds'].get('plan', 0) for r in rows):.0f}, ComfyUI {sum(r['seconds'].get('gpu', 0) for r in rows):.0f}, "
              f"review {sum(r['seconds'].get('review', 0) for r in rows):.0f}), Claude "
              f"{sum(r['usage']['input_tokens'] for r in rows):,} read / {sum(r['usage']['output_tokens'] for r in rows):,} written")
    print(f"✅ boards in {BRAIN_DIR}: {job8}_clip<N>_<version>.jpg (+ _compare.jpg with two versions), {job8}_summary.json")


# --- the moods' spread (B-roll « ambiance »): the same segments rated again and again ------------------

def _spread_grades(moments, runs, images_dir, episode):
    """Per picture: how many distinct grades the runs give it, and the largest ΔE between two of them on its kept
    picture (a 64-step grey-to-colour ramp when the picture is not on disk)."""
    from PIL import Image
    import visual_mood
    out = []
    for k, m in enumerate(moments):
        grades = {}
        for run in runs:
            if k >= len(run) or not run[k]:
                continue
            base = visual_mood.base([r for r in run if r], episode)
            g = visual_mood.grade(run[k], base, signature=0.0)
            grades[json.dumps(g, sort_keys=True)] = g
        path = os.path.join(images_dir or "", f"broll_{k}.jpg")
        if os.path.exists(path):
            im = visual_mood._small(Image.open(path), 256)
        else:
            im = Image.linear_gradient("L").resize((128, 128)).convert("RGB")
        graded = [visual_mood.apply_grade(im, g) for g in grades.values()]
        worst = max((visual_mood.delta_e(a, b) for i, a in enumerate(graded) for b in graded[i + 1:]), default=0.0)
        out.append({"k": k, "subject": m.get("subject") or m.get("anchor"), "grades": len(grades),
                    "max_delta_e": round(worst, 2), "on_picture": os.path.exists(path)})
    return out


def cmd_moods(args):
    """The same pictures rated --runs times, fresh: how much the anchored levels (and the grades) move."""
    import ai_brain
    import broll
    import viral_fx
    import visual_mood
    job_dir, meta = _find_job(args.job)
    job8 = os.path.basename(job_dir)[:8]
    prof = _profile(args.profile)
    _job_env(prof)
    brief, _how = _full_brief(meta)
    ai_brain.EPISODE_BRIEF = brief
    bible = meta.get("episode_bible") if (meta.get("episode_bible") or {}).get("mood") else None
    rows = []
    for n in [int(x) for x in str(args.clips).split(",") if x.strip()]:
        src = os.path.join(BRAIN_DIR, f"{job8}_clip{n}_{args.source}.json")
        if not os.path.exists(src):
            raise SystemExit(f"no plan run {os.path.basename(src)}: run `plan --versions {args.source}` on clip {n} first")
        with open(src, encoding="utf-8") as f:
            res = json.load(f)
        moments = res.get("moments") or []
        if not moments:
            print(f"   clip {n}: no picture planned in {args.source}, nothing to rate")
            continue
        clip = meta["shorts"][n - 1]
        start, end = float(clip["start"]), float(clip["end"])
        words = viral_fx.clip_words(meta.get("transcript"), start, end)
        text = " ".join(w["text"] for w in words)
        brief_txt = ai_brain.brief_for_clip(brief, text, start, end) if brief else ""
        episode = visual_mood.episode_levels(bible or ai_brain.EPISODE_BIBLE)
        editor = [visual_mood.clean(m["mood"]) if m.get("mood") else None for m in moments]
        runs, t0 = [], time.time()
        for r in range(int(args.runs)):
            print(f"▶ clip {n}: rating {len(moments)} picture(s), run {r + 1}/{args.runs}", flush=True)
            runs.append(visual_mood.rate(moments, broll._numbered_text(words), brief_txt,
                                         clip.get("video_title_for_youtube_short") or "", fresh=True))
        spread = visual_mood.spread(runs)
        with_editor = visual_mood.spread(runs + [editor]) if any(editor) else None
        grades = _spread_grades(moments, runs, res.get("images_dir"), episode)
        per_pic = []
        for k, m in enumerate(moments):
            levels = {a: [run[k][a] for run in runs if k < len(run) and run[k]] for a in visual_mood.AXES}
            per_pic.append({"k": k, "subject": m.get("subject"), "said": m.get("said"),
                            "editor": visual_mood.compact(editor[k]) if editor[k] else None,
                            "levels": {a: {v: vals.count(v) for v in dict.fromkeys(vals)} for a, vals in levels.items()},
                            "cues": [run[k].get("cue") for run in runs if k < len(run) and run[k]]})
        row = {"job": os.path.basename(job_dir), "clip": n, "source": args.source, "runs": int(args.runs),
               "pictures": len(moments), "seconds": round(time.time() - t0, 1), "spread": spread,
               "spread_with_editor": with_editor, "grades": grades, "per_picture": per_pic}
        with open(os.path.join(BRAIN_DIR, f"{job8}_clip{n}_moods.json"), "w", encoding="utf-8") as f:
            json.dump(row, f, indent=1, ensure_ascii=False)
        rows.append(row)
        print(f"\n   clip {n}: {len(moments)} picture(s) x {args.runs} runs ({row['seconds']:.0f} s)")
        for axis, s in spread.items():
            ed = (with_editor or {}).get(axis) or {}
            print(f"     {axis:<10} agree {s['agree'] if s['agree'] is not None else '-'}  steps {s['steps']}  "
                  f"moved on {s['changed']}/{s['pictures']}" + (f"   (with the editor's answer: agree {ed.get('agree')})" if ed else ""))
        for p, g in zip(per_pic, grades):
            moved = {a: c for a, c in p["levels"].items() if len(c) > 1}
            print(f"     #{p['k']} {p['subject']}: {g['grades']} grade(s), max ΔE {g['max_delta_e']}"
                  + (f" — moved: {moved}" if moved else " — same levels every run"))
    if rows:
        axes = list(visual_mood.AXES)
        print("\n   all clips: " + ", ".join(
            f"{a} {sum(r['spread'][a]['agree'] * r['spread'][a]['pictures'] for r in rows if r['spread'][a]['agree'] is not None) / max(1, sum(r['spread'][a]['pictures'] for r in rows)):.2f}"
            for a in axes))
        des = [g["max_delta_e"] for r in rows for g in r["grades"]]
        print(f"   grades: {sum(g['grades'] == 1 for r in rows for g in r['grades'])}/{len(des)} picture(s) got one grade "
              f"in every run; largest ΔE between two runs: median {sorted(des)[len(des) // 2]:.1f}, max {max(des):.1f}")
    print(f"✅ {BRAIN_DIR}/{job8}_clip<N>_moods.json")


# --- the editor's choice, again and again (v12: is the choice of moments stable?) ---------------------

def cmd_select(args):
    """The editor alone, fresh, --runs times per clip, chosen as in a job (candidates, guard): which moments come back."""
    import tempfile
    import ai_brain
    import broll
    import viral_fx
    job_dir, meta = _find_job(args.job)
    job8 = os.path.basename(job_dir)[:8]
    prof = _profile(args.profile)
    _job_env(prof)
    brief, _how = _full_brief(meta)
    ai_brain.EPISODE_BRIEF = brief
    bible = meta.get("episode_bible") if (meta.get("episode_bible") or {}).get("mood") else None
    ai_brain.EPISODE_BIBLE = bible or ai_brain.episode_bible(brief, meta.get("transcript"))
    name, over = _version(args.versions)
    cfg = {**plus.BROLL, **over}
    rows = []
    for n in [int(x) for x in str(args.clips).split(",") if x.strip()]:
        clip, pre_fx = _clip_of(job_dir, meta, n)
        start, end = float(clip["start"]), float(clip["end"])
        words = viral_fx.clip_words(meta.get("transcript"), start, end)
        avoid = [float(clip["punchline_time"])] if clip.get("punchline_time") is not None else []
        tmp = tempfile.mkdtemp(prefix="select_")
        sheets = broll._frame_sheets(pre_fx, tmp)
        runs = []
        for r in range(int(args.runs)):
            os.environ["AI_CACHE_REFRESH"] = "1"
            try:
                moments = broll.plan_with_claude(clip, words, broll.MIXED_MAX, avoid, True, meta.get("transcript"), start,
                                                 end, sheets, mode=cfg.get("mode") or "mixed", density=cfg.get("density") or "normal",
                                                 hero=True, dur_range=(broll.CARD_DUR_MIN, broll.CARD_DUR_MAX),
                                                 gap_min=broll.MIXED_GAP, tail=broll.MIXED_TAIL, head=broll.HEAD_FREE)
            finally:
                os.environ.pop("AI_CACHE_REFRESH", None)
            if hasattr(broll, "experience_guard"):
                for m in moments:
                    m["mood"] = m.get("mood") or broll.visual_mood.clean(None)
                moments = broll.experience_guard(moments)
            runs.append([{"t": round(m["t"], 2), "anchor": m["anchor"], "subject": m.get("subject"), "worth": m.get("score"),
                          "inner": bool(hasattr(broll, "is_inner") and broll.is_inner(m))} for m in moments])
            print(f"▶ {name} clip {n} run {r + 1}: " + " | ".join(f"{x['t']:.1f} s {x['subject']}" + (" (inner)" if x["inner"] else "")
                                                         for x in runs[-1]), flush=True)
        focus = float(args.focus) if args.focus else None
        hits = sum(any(abs(x["t"] - focus) <= GROUP_S for x in run) for run in runs) if focus is not None else None
        row = {"job": os.path.basename(job_dir), "clip": n, "version": name, "runs": runs, "focus": focus, "focus_hits": hits}
        rows.append(row)
        with open(os.path.join(BRAIN_DIR, f"{job8}_clip{n}_{name}_select.json"), "w", encoding="utf-8") as f:
            json.dump(row, f, indent=1, ensure_ascii=False)
        if focus is not None:
            print(f"   {name} clip {n}: the moment at {focus:g} s chosen in {hits}/{len(runs)} run(s)")
    print(f"✅ {BRAIN_DIR}/<job>_clip<N>_{name}_select.json")


# --- what fills the pictures (v12: empty places and objects set down) ------------------------------

CONTENT_KINDS = ("people", "place_with_people", "empty_place", "object_set_down", "object_in_use", "inner_or_abstract")


def _seen_of(res, it):
    """The review's description of the picture that was kept for ``it`` ("" when none was recorded)."""
    k = it.get("k")
    revs = [r for r in res.get("reviews") or [] if r.get("k") == k and r.get("seen")]
    if it.get("take") and int(it["take"]) > 1:
        revs = [r for r in revs if str(r.get("file", "")).endswith(f"_t{it['take']}.jpg")] or revs
    return (revs[-1]["seen"] if revs else "")[:400]


def cmd_content(args):
    """Every kept picture of the given clips and versions, classified from what the review saw (one Haiku call)."""
    import ai_brain
    entries = []
    for spec in str(args.jobs).split(","):
        job, n = spec.split(":")
        n = int(n)
        for v in str(args.versions).split(","):
            path = os.path.join(BRAIN_DIR, f"{job[:8]}_clip{n}_{v}.json")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                res = json.load(f)
            for it in res.get("items") or []:
                seen = _seen_of(res, it)
                if seen:
                    entries.append({"id": f"{v}|{job[:8]}:{n}|{it.get('k')}", "v": v, "hero": it.get("layout") == "hero",
                                    "seen": seen})
    if not entries:
        raise SystemExit("no picture with a review to classify")
    prompt = ("Each line below describes one picture (what is really in it). Classify each into ONE kind:\n"
              "- people: one or more people, the main subject;\n- place_with_people: a place where people are present;\n"
              "- empty_place: a place, a room, a bed, a corridor, a landscape with nobody in it;\n"
              "- object_set_down: a thing lying or standing on a surface, nobody using it;\n"
              "- object_in_use: a thing in someone's hands or in use;\n"
              "- inner_or_abstract: an inner experience, a vision, a model, a diagram, a microscope or instrument image.\n"
              "Return JSON {\"kinds\": [{\"id\": \"...\", \"kind\": \"...\"}]} for every line.\n\n"
              + "\n".join(f"{e['id']}: {e['seen']}" for e in entries))
    schema = {"type": "object", "properties": {"kinds": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "kind": {"type": "string", "enum": list(CONTENT_KINDS)}}, "required": ["id", "kind"]}}},
        "required": ["kinds"]}
    data = ai_brain.claude_json(prompt, schema, timeout=300, model="haiku")
    kinds = {k.get("id"): k.get("kind") for k in (data or {}).get("kinds") or []}
    table = {}
    for e in entries:
        e["kind"] = kinds.get(e["id"]) or "?"
        t = table.setdefault(e["v"], {"all": {}, "hero": {}})
        t["all"][e["kind"]] = t["all"].get(e["kind"], 0) + 1
        if e["hero"]:
            t["hero"][e["kind"]] = t["hero"].get(e["kind"], 0) + 1
    out = os.path.join(BRAIN_DIR, f"content_{args.name}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"entries": entries, "table": table}, f, indent=1, ensure_ascii=False)
    for v in str(args.versions).split(","):
        t = table.get(v) or {"all": {}, "hero": {}}
        total, heroes = sum(t["all"].values()), sum(t["hero"].values())
        flat = t["all"].get("empty_place", 0) + t["all"].get("object_set_down", 0)
        flat_h = t["hero"].get("empty_place", 0) + t["hero"].get("object_set_down", 0)
        print(f"   {v}: {total} picture(s), empty place or object set down {flat} — heroes {heroes}, of them {flat_h} empty "
              f"place or object set down — {t['all']}")
    print(f"✅ {out}")


# --- the caption face (chantier F) --------------------------------------------------------

def cmd_fonts(args):
    """Captions only, on the pristine clip, natural (Liberation Sans 64) next to premium (Montserrat ExtraBold) at
    64 / 68 / 72, on up to three clips: one frame per clip at a caption with an accent word, the caption band
    cropped and stacked (``fonts_sheet.jpg``), plus the full frames of the first clip."""
    import viral_fx
    from PIL import Image
    os.makedirs(OUT_DIR, exist_ok=True)
    prof = _profile(args.profile)
    _job_env(prof)
    rows = []
    full = []
    for k, spec in enumerate([s for s in (args.clips or f"{args.job}:{args.clip}").split(",") if s]):
        job, _, n = spec.partition(":")
        job_dir, meta, clip, pre_fx = _find_clip(job, int(n or 1))
        words = viral_fx.clip_words(meta.get("transcript"), float(clip["start"]), float(clip["end"]))
        topic = viral_fx.topic_words(clip.get("video_title_for_youtube_short"), clip.get("viral_hook_text"))
        # An instant with an accent word, past the first third of the clip.
        _, groups = viral_fx.build_ass(words, "natural", topic=topic)
        dur = _ffprobe_duration(pre_fx)
        t = None
        for g in groups:
            if g[0]["start"] > dur / 3 and any(viral_fx.keyword_score(w["text"], topic) >= 0.6 for w in g):
                t = g[0]["start"] + 0.25
                break
        t = t if t is not None else dur / 2
        tiles = []
        variants = [("natural", 64), ("premium", 64), ("premium", 68), ("premium", 72)]
        for preset, size in variants:
            keep = viral_fx.PRESETS[preset]["size"]
            viral_fx.PRESETS[preset]["size"] = size
            try:
                out = os.path.join(OUT_DIR, f"_font_{k}_{preset}_{size}.mp4")
                viral_fx.apply_captions(pre_fx, words, preset, out, watermark=prof["watermark"] or None, topic=topic)
            finally:
                viral_fx.PRESETS[preset]["size"] = keep
            png = _frame(out, t, os.path.join(OUT_DIR, f"_font_{k}_{preset}_{size}.png"))
            os.remove(out)
            _label(png, f"{preset} {size}")
            if k == 0:
                full.append(png)
            im = Image.open(png).convert("RGB")
            W, H = im.size
            tiles.append(im.crop((0, int(H * 0.52), W, int(H * 0.70))))
        row = Image.new("RGB", (sum(t_.width for t_ in tiles) + 6 * (len(tiles) - 1), tiles[0].height), (24, 24, 24))
        x = 0
        for im in tiles:
            row.paste(im, (x, 0))
            x += im.width + 6
        rows.append(row)
        print(f"   clip {spec}: frame at {t:.1f} s")
    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height for r in rows) + 6 * (len(rows) - 1)), (24, 24, 24))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 6
    sheet.save(os.path.join(OUT_DIR, "fonts_sheet.jpg"), quality=92)
    if full:
        _hstack(full, os.path.join(OUT_DIR, "fonts_full.jpg"), height=960)
    for p in glob.glob(os.path.join(OUT_DIR, "_font_*.png")):
        os.remove(p)
    print(f"✅ fonts bench written to {OUT_DIR}: fonts_sheet.jpg (caption bands), fonts_full.jpg (first clip)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("chain", cmd_chain), ("visual", cmd_visual), ("fonts", cmd_fonts)):
        p = sub.add_parser(name)
        p.add_argument("--job", required=name != "fonts")
        p.add_argument("--clip", type=int, default=1)
        p.add_argument("--clips", default=None, help="fonts: several clips, as job:clip,job:clip")
        p.add_argument("--profile", default=None)
        p.add_argument("--before-cache", action="store_true")
        p.set_defaults(fn=fn)
    p = sub.add_parser("plan", help="the brain on some clips, boards only, no video cut")
    p.add_argument("--job", required=True, help="job id or its first characters")
    p.add_argument("--clips", default="1", help="clip numbers, e.g. 1,3,5")
    p.add_argument("--versions", default="current", help="brain versions to run, e.g. current,v2 or v2:art_director=1")
    p.add_argument("--profile", default=None)
    p.add_argument("--fresh", action="store_true", help="ask Claude again instead of reading the remembered answers")
    p.add_argument("--no-bible", action="store_true", help="plan without the episode's visual bible")
    p.add_argument("--signatures", default="", help="also a sheet of every picture at these signature strengths, e.g. 0,0.2")
    p.add_argument("--moments", default="", help="aligned:v8,v9 — the editor answers on the moments those versions illustrated")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("board", help="the boards again from the JSON of an earlier plan run")
    p.add_argument("--job", required=True)
    p.add_argument("--clips", default="1")
    p.add_argument("--versions", default="current")
    p.add_argument("--signatures", default="", help="also a sheet of every picture at these signature strengths, e.g. 0,0.2")
    p.set_defaults(fn=cmd_board)
    p = sub.add_parser("moods", help="the same pictures rated again and again: how much the mood levels move")
    p.add_argument("--job", required=True)
    p.add_argument("--clips", default="1")
    p.add_argument("--from", dest="source", default="v9", help="the version of the plan run whose pictures are rated")
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--profile", default=None)
    p.set_defaults(fn=cmd_moods)
    p = sub.add_parser("select", help="the editor alone, fresh, several times: how stable the choice of moments is")
    p.add_argument("--job", required=True)
    p.add_argument("--clips", default="1")
    p.add_argument("--runs", type=int, default=4)
    p.add_argument("--versions", default="current", help="one version (its cfg keys), e.g. v13")
    p.add_argument("--focus", default="", help="a moment (s) to count across the runs")
    p.add_argument("--profile", default=None)
    p.set_defaults(fn=cmd_select)
    p = sub.add_parser("content", help="what fills the kept pictures (empty places, objects set down...), per version")
    p.add_argument("--jobs", required=True, help="job:clip,job:clip")
    p.add_argument("--versions", required=True)
    p.add_argument("--name", default="run")
    p.set_defaults(fn=cmd_content)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
