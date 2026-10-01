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

``plan`` (the brain): planner + art direction + pictures + review on the chosen
clips, exactly as a job runs them, but NO video is cut (add_broll in its
manual-review mode). One board per clip and version
(``brain/<job>_clip<N>_<version>.jpg``: each kept picture as graded, its prompt,
the exact text / seed / size sent to ComfyUI, the review's scores, the moments
dropped, the seconds and the tokens) with its JSON; two versions are also put
side by side (``_compare.jpg``). A version is a name of ``VERSIONS`` (cfg keys
laid over the house recipe) or ``name:key=value;key=value``. A job made without
B-roll has no glossary in its brief: the episode is read again (ai_cache keeps
the answer). The notion memory is never read nor written.

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
AFTER_BROLL = {"layout": "mixed", "hold": None, "density": "normal", "max": 4, "hero_res": "std",
               "grade": "cinematic", "sfx": True,
               "house_look": "cinematic documentary photograph, 35 mm lens, natural light, teal and amber grade, "
                             "fine film grain, shallow depth of field"}
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
}
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
        self.images, self._current = 0, None

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
            return self._timed("art", orig["direct_art"], *a, **kw)

        def plan_gemini(*a, **kw):
            out = self._timed("plan", orig["plan_with_gemini"], *a, **kw)
            self.moments = [dict(m) for m in out]
            return out

        def review(cands, words):
            out = self._timed("review", orig["review_images"], cands, words)
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
        if k is not None and k < len(w.moments):
            m = w.moments[k]
            it.update(said=m.get("said"), shot=m.get("shot"), planner_hero=bool(m.get("hero")), key=m.get("key"))
        # The exact text ComfyUI got for the picture that was kept: the one whose text opens with the item's
        # prompt (the redo's when the redo was kept); else the first picture made for this moment.
        cands = [(name, s) for name, s in w.sent.items() if _k_of(name) == k]
        exact = next((s for _n, s in cands if it.get("prompt") and s["text"].startswith(it["prompt"][:60])), None)
        it["sent"] = exact or (cands[0][1] if cands else None)
    thesis = next((m.get("thesis") for m in w.moments if m.get("thesis")), "")
    sheet = next((m.get("sheet") for m in w.moments if m.get("sheet")), None)
    kept = {it["k"] for it in items if it.get("k") is not None}
    dropped = []
    for k, m in enumerate(w.moments):
        if k in kept:
            continue
        rs = [r for r in w.reviews if r.get("k") == k]
        dropped.append({"k": k, "anchor": m.get("anchor"), "subject": m.get("subject"), "layout": "hero" if m.get("hero") else "card",
                        "scores": [r.get("score") for r in rs], "problem": (rs[-1].get("problem") if rs else "") or ""})
    return {"job": os.path.basename(job_dir), "clip": n, "version": version, "overrides": over,
            "duration": round(end - start, 2), "title": clip.get("video_title_for_youtube_short") or "",
            "hook": clip.get("viral_hook_text") or "", "thesis": thesis, "sheet": sheet,
            "sequence": [m.get("subject") for m in w.moments if m.get("subject")],
            "planner": (rep or {}).get("planner"), "moments": w.moments, "items": items, "reviews": w.reviews,
            "sent": w.sent, "dropped": dropped, "seconds": seconds, "usage": usage, "images_made": w.images,
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
        if it.get("notion"):
            line1 += f"   notion « {it['notion']} »" + (" (reused)" if it.get("reused") else "")
        if it.get("planner_hero"):
            line1 += "   planner's hero"
        lines += block(f_b, line1, _C_LABEL)
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
            for name, over in versions:
                tag = f"{job8}_clip{n}_{name}"
                print(f"\n▶ clip {n} · {name}: {clip.get('video_title_for_youtube_short')}", flush=True)
                res = _plan_clip(job_dir, meta, n, clip, pre_fx, prof, name, over, tag)
                with open(os.path.join(BRAIN_DIR, tag + ".json"), "w", encoding="utf-8") as f:
                    json.dump(res, f, indent=1, ensure_ascii=False)
                boards.append(_board(res, os.path.join(BRAIN_DIR, tag + ".jpg")))
                scores = [it.get("score") for it in res["items"] if it.get("score") is not None]
                row = {"clip": n, "version": name, "images": len(res["items"]), "made": res["images_made"],
                       "hero": any(it.get("layout") == "hero" for it in res["items"]),
                       "scores": scores, "dropped": len(res["dropped"]), "seconds": res["seconds"], "usage": res["usage"]}
                summary.append(row)
                print(f"   {name}: {row['images']} kept of {row['made']} made, scores {scores}, hero {row['hero']}, "
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
    p.set_defaults(fn=cmd_plan)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
