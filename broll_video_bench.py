"""Bench of broll_video (9-oct-2026) on a job's clips, in the container:

    python broll_video_bench.py plan   OUT clips.json TAG [TAG...]   moments + Pexels choices + a board of the previews
                                                                      (no video downloaded)
    python broll_video_bench.py render OUT JOB_DIR                    downloads the chosen files (cache), cuts the
                                                                      excerpts, lays them on the clips' *.pre_fx.mp4,
                                                                      a board 1 frame/s

OUT/choix.json holds the plan; OUT/fix.json may correct it by hand: {"TAG": {"<t>": {"query": "...", "pick": <index or
video id>, "frame": "a|b|c"} | null}} (null = no footage on that moment). The cache is OUT/cache (BROLL_VIDEO_CACHE)."""
import glob
import json
import os
import subprocess
import sys

OUT = sys.argv[2]
os.environ.setdefault("BROLL_VIDEO_CACHE", os.path.join(OUT, "cache"))
import broll_video as bv  # noqa: E402

TILE = 390


def font(n):
    from PIL import ImageFont
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", n)
    except OSError:
        return ImageFont.load_default()


def mb(c):
    return c["file"]["size"] / 1e6


def plan(clips_file, tags):
    with open(clips_file, encoding="utf-8") as f:
        clips = {c["tag"]: c for c in json.load(f)["clips"]}
    out = {}
    for tag in tags:
        c = clips[tag]
        words = [(float(s), w) for s, w in c["words"]]
        moments = bv.spot(words, c.get("title", ""))
        rows = bv.plan_clip(moments, os.path.join(OUT, "tmp", tag))
        out[tag] = {"title": c.get("title"), "duration": c.get("duration"), "moments": moments,
                    "plan": [{"moment": r["moment"], "choice": r["choice"], "candidates": r["candidates"]} for r in rows]}
        print(tag, len(moments), "moments,", len(rows), "actions")
    with open(os.path.join(OUT, "choix.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    board(out)


def apply_fix(data):
    path = os.environ.get("BENCH_FIX") or os.path.join(OUT, "fix.json")
    if not os.path.exists(path):
        return data
    with open(path, encoding="utf-8") as f:
        fix = json.load(f)
    with open(os.path.join(OUT, "fix.json"), "w", encoding="utf-8") as f:     # kept with the bench
        json.dump(fix, f, ensure_ascii=False, indent=1)
    for tag, moves in fix.items():
        have = {f"{r['moment']['t']:g}" for r in data[tag]["plan"]}
        for key, m in moves.items():          # a moment the spotter missed, added by hand
            if key not in have and m:
                data[tag]["plan"].append({"moment": {"t": float(key), "word": m["word"], "sentence": "",
                                                     "kind": "action", "query": m["query"]},
                                          "choice": None, "candidates": []})
        data[tag]["plan"].sort(key=lambda r: r["moment"]["t"])
        for r in data[tag]["plan"]:
            key = f"{r['moment']['t']:g}"
            if key not in moves:
                continue
            m = moves[key]
            if m is None:
                r["choice"] = None
                continue
            if m.get("query"):
                r["moment"]["query"] = m["query"]
                r["candidates"] = bv.search(m["query"])[:bv.CANDIDATES]
            cs = r["candidates"]
            pick = m.get("pick", 0)
            c = next((x for x in cs if x["id"] == pick), None) or (cs[pick] if isinstance(pick, int) and pick < len(cs)
                                                                   else None)
            if c:
                frames = bv.preview_frames(c)
                fi = {"a": 0, "b": 1, "c": 2}.get(m.get("frame", "b"), 1)
                r["choice"] = {**c, "frame_index": frames[min(fi, len(frames) - 1)][0] if frames else 0,
                               "frame_of": max(1, len(c.get("pictures") or [])), "why": "corrige a la main"}
    return data


def board(data, name="planche_choix.jpg"):
    """One row per action moment: the word, the query, the chosen video's three preview frames, its facts."""
    from PIL import Image, ImageDraw
    rows = [(tag, r) for tag, d in data.items() for r in d["plan"]]
    tw, th, info = 170, 302, 520
    bw, per = 3 * (tw + 6) + info, 2          # two moments side by side
    W, H = per * bw, max(1, (len(rows) + per - 1) // per) * (th + 8) + 8
    img = Image.new("RGB", (W, H), (20, 20, 20))
    d = ImageDraw.Draw(img)
    f1, f2 = font(20), font(15)
    for i, (tag, r) in enumerate(rows):
        y, bx = 8 + (i // per) * (th + 8), (i % per) * bw
        m, c = r["moment"], r["choice"]
        x0 = bx + 3 * (tw + 6) + 8
        d.text((x0, y), f"{tag[-3:]} · {m['t']:.2f} s · « {m['word']} »", fill=(255, 220, 0), font=f1)
        d.text((x0, y + 28), f"query : {m.get('query')}", fill=(220, 220, 220), font=f2)
        if not c:
            d.text((x0, y + 56), "AUCUNE video retenue", fill=(255, 90, 90), font=f1)
            continue
        lines = [c["title"][:48], f"{c['duration']:.0f} s · {c['file']['width']}x{c['file']['height']} · {mb(c):.1f} Mo",
                 f"auteur : {c['credit']['author']}", (c.get("why") or "")[:56], c["page"][-60:]]
        for k, line in enumerate(lines):
            d.text((x0, y + 56 + 22 * k), line, fill=(255, 255, 255), font=f2)
        for k, (pi, _url) in enumerate(bv.preview_frames(c)):
            p = os.path.join(bv.cache_dir(), "previews", f"{c['id']}_{pi}.jpg")
            try:
                bv._fetch(_url, p, bv.PREVIEW_HOST)
                fr = Image.open(p).convert("RGB")
            except Exception:
                continue
            cw, ch = bv.crop_size(*fr.size)
            left, top = (fr.size[0] - cw) // 2, (fr.size[1] - ch) // 2
            img.paste(fr.crop((left, top, left + cw, top + ch)).resize((tw, th)), (bx + k * (tw + 6), y))
    img.save(os.path.join(OUT, name), quality=86)
    total = {}
    for _tag, r in rows:
        if r["choice"]:
            total[r["choice"]["id"]] = mb(r["choice"])
    print(f"{len(total)} vidéos, {sum(total.values()):.1f} Mo à télécharger")


def render(job_dir):
    with open(os.path.join(OUT, "choix.json"), encoding="utf-8") as f:
        data = apply_fix(json.load(f))
    with open(os.path.join(OUT, "choix_final.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    board(data, "planche_choix_final.jpg")
    with open(os.environ.get("BENCH_CLIPS", "/app/output/_stepup/clips.json"), encoding="utf-8") as f:
        words_of = {c["tag"]: [(float(s), w) for s, w in c["words"]] for c in json.load(f)["clips"]}
    credits = []
    for tag, d in data.items():
        n = int(tag.split("_c")[-1])
        clip = glob.glob(os.path.join(job_dir, f"*_clip_{n}.pre_fx.mp4"))[0]
        words, end = words_of[tag], float(d["duration"])
        placed = []
        for r in d["plan"]:
            m, c = r["moment"], r["choice"]
            if not c:
                continue
            t = float(m["t"])
            dur = bv.span(words, t, end)
            if dur < bv.SHOW_MIN or any(t < q["t"] + q["dur"] and q["t"] < t + dur for q in placed):
                continue
            src = bv.download(c)
            path = bv.cut(src, bv.excerpt_start(c, dur), dur, os.path.join(OUT, "tmp", f"{tag}_{t:06.2f}.mp4"))
            placed.append({"t": t, "dur": dur, "path": path})
            credits.append({"clip": tag, "t": t, "dur": dur, "word": m["word"], **c["credit"], "title": c["title"]})
        out = os.path.join(OUT, f"{tag}_video.mp4")
        bv.apply(clip, placed, out)
        frames(out, os.path.join(OUT, f"planche_{tag}.jpg"), end)
        print(tag, [(p["t"], p["dur"]) for p in placed])
    with open(os.path.join(OUT, "credits.json"), "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=1)


def frames(video, path, dur, cols=6):
    """1 frame a second, 390 px wide, its second written on it."""
    from PIL import Image, ImageDraw
    tmp = path + "_f"
    os.makedirs(tmp, exist_ok=True)
    for old in glob.glob(os.path.join(tmp, "*.jpg")):
        os.remove(old)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vf", f"fps=1,scale={TILE}:-2",
                    os.path.join(tmp, "f_%03d.jpg")], check=True)
    files = sorted(glob.glob(os.path.join(tmp, "*.jpg")))
    ims = [Image.open(p) for p in files]
    w, h = ims[0].size
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(ims):
        x, y = (i % cols) * w, (i // cols) * h
        sheet.paste(im, (x, y))
        d.text((x + 8, y + 6), f"{i} s", fill=(255, 220, 0), font=font(26))
    sheet.save(path, quality=84)
    for p in files:
        os.remove(p)
    os.rmdir(tmp)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    if sys.argv[1] == "plan":
        plan(sys.argv[3], sys.argv[4:])
    elif sys.argv[1] == "look":           # candidate sheets of a few queries, to correct a choice by hand
        for i, q in enumerate(sys.argv[3:]):
            cs = bv.search(q)[:bv.CANDIDATES]
            bv.sheet(cs, os.path.join(OUT, "tmp", f"look_{i}.jpg"), q)
            print(i, q, [(k, c["id"], c["title"][:40], round(mb(c), 1)) for k, c in enumerate(cs)])
    elif sys.argv[1] == "board":
        with open(os.path.join(OUT, "choix.json"), encoding="utf-8") as f:
            board(apply_fix(json.load(f)), "planche_choix_corrigee.jpg")
    else:
        render(sys.argv[3])
