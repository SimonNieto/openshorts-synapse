"""Banc « littéral » (9-oct-2026) : la chaîne broll_litteral sur de vrais clips, sans job.

Pour chaque clip : le directeur (un appel, réponse gardée par ai_cache : relancer ne coûte rien), le vérificateur, les
rendus Z-Image (broll_store : une image déjà faite revient sans GPU), les images posées sur le *.pre_fx.mp4 du clip par
broll.overlay_items (le même code que le job), puis une planche 1 image/s à 390 px. Sorties dans --out :
c<N>.mp4, c<N>_planche.jpg, c<N>_<k>_<clé>.jpg (chaque image), c<N>_plan.json (noms relevés, séquence, verdicts,
calage, prompts, coût).

    python broll_litteral_banc.py --clips 1,3,7,10
    python broll_litteral_banc.py --clips 3 --fix fixes.json   # des images refaites : {"3": {"clé": {"picture": "..."}}}

Le transcript mot à mot vient de output/_stepup/clips.json (champ words : [[début, mot], ...])."""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import broll            # noqa: E402
import broll_litteral as bl   # noqa: E402
import broll_store      # noqa: E402

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join("/app", "output", "_stepup", "etude2", "v3", "images")
CLIPS_JSON = os.path.join("/app", "output", "_stepup", "clips.json")
JOB = "b8e46c24-7f5e-48cf-8adc-c2d2677a241e"
STEPS = int(os.environ.get("COMFYUI_ZIMAGE_STEPS") or 8)
TILE_W = 390


def clip_entry(job, n):
    data = json.load(open(CLIPS_JSON, encoding="utf-8"))
    for c in data["clips"]:
        if c["job"] == job[:len(c["job"])] or job.startswith(c["job"]) or c["job"].startswith(job[:8]):
            if int(c["n"]) == int(n):
                return c
    raise SystemExit(f"clip {n} of {job} not in {CLIPS_JSON}")


def words_of(entry):
    raw = [(float(t), str(w)) for t, w in entry["words"]]
    out = []
    for k, (t, w) in enumerate(raw):
        end = raw[k + 1][0] if k + 1 < len(raw) else min(float(entry["duration"]), t + 0.5)
        out.append({"text": w, "start": max(0.0, t), "end": max(end, t + 0.05)})
    return out


def punch_time(entry, words):
    """The punchline's first word in the clip (its first three words matched in order), or None."""
    target = [re.sub(r"[^\w']", "", w.lower()) for w in str(entry.get("punchline") or "").split()][:3]
    bare = [re.sub(r"[^\w']", "", w["text"].lower()) for w in words]
    for i in range(len(bare) - len(target) + 1):
        if target and bare[i:i + len(target)] == target:
            return words[i]["start"]
    return None


def pre_fx(job, n):
    got = glob.glob(os.path.join("/app", "output", job, f"*_clip_{n}.pre_fx.mp4"))
    if not got:
        raise SystemExit(f"no pre_fx for clip {n}")
    return got[0]


def items_of(cands):
    """The cut-in items as add_broll makes them (layout, times, marks; the same overlap rule)."""
    items = []
    for c in cands:
        m = c["m"]
        it = {"t": round(m["t"], 2), "dur": round(float(m["dur"]), 2), "layout": c["layout"], "_img": c["file"],
              "anchor": m["anchor"], "key": m["query"], "format": m["format"]}
        if c["layout"] == "object":
            it["size"] = broll.OBJECT_SIZE
        if m.get("seq"):
            it.update(seq=m["seq"], step=m.get("step", 0), marks=list(m.get("marks") or []))
        items.append(it)
    for a, b in zip(items, items[1:]):
        a["dur"] = round(min(a["dur"], b["t"] - a["t"]), 2)       # add_broll's rule for this chain
    return items


def sheet(video, words, items, out_path, title, cols=10):
    """One frame a second (at s + 0.5) at TILE_W px, the second and the word said under it, a coloured edge when a
    picture is up (blue: full screen, yellow: object card, green: split screen, magenta: sequence)."""
    from PIL import Image, ImageDraw
    tmp = tempfile.mkdtemp(prefix="sheet_")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", video, "-vf", f"fps=1,scale={TILE_W}:-2",
                        os.path.join(tmp, "f%03d.jpg")], check=True)
        frames = sorted(glob.glob(os.path.join(tmp, "f*.jpg")))
        if not frames:
            return
        tw, th = Image.open(frames[0]).size
        rows = (len(frames) + cols - 1) // cols
        lab = 46
        im = Image.new("RGB", (cols * (tw + 6) + 6, 70 + rows * (th + lab + 6)), (16, 16, 18))
        d = ImageDraw.Draw(im)
        font, small = broll._font(30), broll._font(22)
        d.text((10, 18), title[:120], fill=(255, 216, 77), font=font)
        for k, f in enumerate(frames):
            t = k + 0.5
            x, y = 6 + (k % cols) * (tw + 6), 70 + (k // cols) * (th + lab + 6)
            im.paste(Image.open(f), (x, y))
            up = next((it for it in items if it["t"] <= t < it["t"] + it["dur"]), None)
            if up:
                colour = {"hero": (80, 160, 255), "object": (255, 210, 60), "split": (60, 220, 120)}[up["layout"]] if not up.get("seq") else (230, 80, 230)
                d.rectangle((x - 3, y - 3, x + tw + 2, y + th + 2), outline=colour, width=4)
            said = " ".join(w["text"] for w in words if k <= w["start"] < k + 1)[:28]
            d.text((x + 4, y + th + 4), f"{k}s", fill=(255, 255, 255), font=small)
            d.text((x + 50, y + th + 4), said, fill=(190, 190, 190), font=small)
        im.save(out_path, quality=88)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default=JOB)
    ap.add_argument("--clips", default="1,3,7")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--fix", default="", help="JSON {clip: {key: {picture|format|background|figure: ...}}}")
    ap.add_argument("--plan-only", action="store_true", help="the director and the verifier only, no render")
    args = ap.parse_args()
    os.environ.setdefault("EDIT_STYLE", "premium")        # the object card sits under the premium captions' band
    os.environ.setdefault("BROLL_TRACE", "0")             # the bench keeps its own trace (c<N>_plan.json)
    os.environ["PLUS_HQ_CHAIN"] = "0"                     # a viewing copy (crf 19), not a near-lossless layer
    os.makedirs(args.out, exist_ok=True)
    fixes = json.load(open(args.fix, encoding="utf-8")) if args.fix else {}
    import ai_brain
    summary = []
    for n in [int(x) for x in args.clips.split(",") if x.strip()]:
        entry = clip_entry(args.job, n)
        words = words_of(entry)
        duration = float(entry["duration"])
        clip = {"video_title_for_youtube_short": entry.get("title") or "", "punchline_time": punch_time(entry, words)}
        avoid = [clip["punchline_time"]] if clip["punchline_time"] is not None else []
        u0 = dict(ai_brain.USAGE)
        t0 = time.time()
        nouns, seqs, styles = bl.direct(words, clip)
        for key, fix in (fixes.get(str(n)) or {}).items():
            for nn in nouns:
                if nn["key"] == key:
                    nn.update({k: v for k, v in fix.items() if k in ("picture", "format", "background")})
            for s in seqs:
                if s["key"] == key and fix.get("figure"):
                    s["figure"] = fix["figure"]
        log = []

        def make(text, out, size, seed, steps):
            return broll.local_image(text, "photo", out, size=size, seed=seed, steps=steps, raw=True)

        render = broll_store.renderer(make, lambda layout: broll._gen_size(layout, "std"), lambda layout: STEPS,
                                      version="litteral", log=log, dry=args.plan_only)
        tmp = tempfile.mkdtemp(prefix="lit_")
        broll._comfy_enter()
        try:
            cands, picks = bl.run(pre_fx(args.job, n), clip, words, avoid, [], tmp, render, duration=duration,
                                  plan=(nouns, seqs, styles))
        finally:
            broll._comfy_leave()
        u1 = ai_brain.USAGE
        tokens = {"calls": u1["calls"] - u0["calls"], "input": u1["input_tokens"] - u0["input_tokens"],
                  "output": u1["output_tokens"] - u0["output_tokens"]}
        import broll_v20
        checks = list(broll_v20.LAST_CHECKS)
        items = items_of(cands)
        kept_files = {}
        for old in glob.glob(os.path.join(args.out, f"c{n:02d}_*.jpg")):
            if not old.endswith("_planche.jpg"):
                os.remove(old)                            # this bench's own pictures of an earlier run
        for c in cands:
            key = c["m"]["query"]
            if key not in kept_files:
                name = f"c{n:02d}_{len(kept_files)}_{key}.jpg"
                shutil.copy2(c["file"], os.path.join(args.out, name))
                kept_files[key] = name
        video = os.path.join(args.out, f"c{n:02d}.mp4")
        if items and not args.plan_only:
            broll.overlay_items(pre_fx(args.job, n), video, items)
            sheet(video, words, items, os.path.join(args.out, f"c{n:02d}_planche.jpg"),
                  f"c{n:02d} — {entry.get('title')}")
        gpu = round(sum(line["s"] for line in log), 1)
        cover = bl.coverage(items, duration)
        plan = {"clip": n, "title": entry.get("title"), "duration": duration, "punchline_time": clip["punchline_time"],
                "nouns": nouns, "sequences": seqs, "styles": styles,
                "shown": [{k: v for k, v in it.items() if k != "_img"} | {"file": kept_files.get(it["key"])}
                          for it in items],
                "checks": checks, "renders": log, "gpu_s": gpu, "tokens": tokens, "cover": round(cover, 3),
                "wall_s": round(time.time() - t0, 1)}
        json.dump(plan, open(os.path.join(args.out, f"c{n:02d}_plan.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        summary.append({"clip": n, "images": len(kept_files), "shown": len(items), "cover": round(cover, 3),
                        "gpu_s": gpu, "tokens": tokens})
        print(f"c{n:02d}: {len(nouns)} nouns, {len(seqs)} sequence(s), {len(kept_files)} images, {len(items)} shown, "
              f"{100 * cover:.0f} % off the face, GPU {gpu} s, tokens {tokens}", flush=True)
        for it in items:
            print(f"   {it['t']:5.2f}s +{it['dur']:.2f}  {it['layout']:6s} {it['key']:28s} « {it['anchor']} »"
                  + (f"  marks {it['marks']}" if it.get("marks") else ""), flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
    json.dump(summary, open(os.path.join(args.out, "resume.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
