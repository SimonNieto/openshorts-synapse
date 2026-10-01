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

Everything lands in output/_test_broll/premium/.
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
    style = prof["edit_style"]
    fx = dict(prof["fx"])
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
          f"{len(items)} B-roll image(s), style {prof['edit_style']}, hook {prof['hook_style']})")
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

def cmd_visual(args):
    """Filled in by the premium chantiers: BEFORE = the profile as saved, AFTER = the premium overrides."""
    sys.exit("visual mode: not available yet (chantier B)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("chain", cmd_chain), ("visual", cmd_visual)):
        p = sub.add_parser(name)
        p.add_argument("--job", required=True)
        p.add_argument("--clip", type=int, default=1)
        p.add_argument("--profile", default=None)
        p.add_argument("--before-cache", action="store_true")
        p.set_defaults(fn=fn)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
