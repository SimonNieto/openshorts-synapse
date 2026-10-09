"""Bench of the smart zooms (zooms.py): clips of a finished job framed again from the SOURCE, fixed vs zooms,
the drawings full screen as the recipe cuts them (with their slow push under "references").

Run in the container from the checkout to try (9-oct-2026: clips 1, 7, 11 of job b8e46c24):
  docker exec -w /app/<checkout> -e YOLO_MODEL_PATH=/app/yolov8n.pt openshorts-backend python zooms_bench.py
Writes, per clip, a 15 s mp4 and a contact sheet one frame a second at 390 px wide, each cell saying where a
dry cut fell and why (word, reason), into OUT; plans.json holds every plan.
"""
import glob
import importlib
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.getcwd())
OUT = os.environ.get("ZOOMS_BENCH_OUT", "/app/output/_stepup/etude2/v3/zooms")
JOB = os.environ.get("ZOOMS_BENCH_JOB", "/app/output/b8e46c24-7f5e-48cf-8adc-c2d2677a241e")
CLIPS = {1: 5.0, 7: 14.0, 11: 12.0}       # clip number -> where its 15 s start (drawings inside)
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])


def punch_span(words, text):
    """The punchline's (start, clip end) from its first four words."""
    toks = [re.sub(r"[^a-z0-9']", "", t.lower()) for t in (text or "").split()][:4]
    wt = [re.sub(r"[^a-z0-9']", "", w["text"].lower()) for w in words]
    for i in range(len(wt) - len(toks) + 1):
        if toks and wt[i:i + len(toks)] == toks:
            return (words[i]["start"], words[-1]["end"])
    return None


def overlay_drawings(video, out, items, fps):
    """The drawings full screen, hard cut in and out (broll._hero_frames with the current HERO_PUSH)."""
    import broll
    tmp = os.path.join(OUT, "_tmp_draw")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    ins, graph, last = [], [], "[0:v]"
    for k, it in enumerate(items):
        folder = os.path.join(tmp, f"d{k}")
        os.makedirs(folder)
        every = broll.HERO_STILL_EVERY        # one in that many holds still, as broll.add_broll cuts them
        still = every > 0 and k % every == every - 1
        it["still"] = still
        pat = broll._hero_frames(it["path"], folder, fps, it["dur"], 1080, 1920, push=1.0 if still else None)
        ins += ["-framerate", f"{fps:.6f}", "-i", pat]
        graph.append(f"[{k + 1}:v]setpts=PTS+{it['t']:.3f}/TB[d{k}];{last}[d{k}]overlay=0:0:eof_action=pass[v{k}]")
        last = f"[v{k}]"
    if not items:
        shutil.copy2(video, out)
    else:
        run(["ffmpeg", "-y", "-v", "error", "-i", video, *ins, "-filter_complex", ";".join(graph), "-map", last,
             "-map", "0:a?", "-c:v", "libx264", "-crf", "14", "-preset", "fast", "-c:a", "copy", out])
    shutil.rmtree(tmp, ignore_errors=True)


def contact_sheet(video, out, labels, title):
    from PIL import Image, ImageDraw, ImageFont
    tmp = os.path.join(OUT, "_tmp_frames")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for s in range(15):       # the frame AT each second (the fps filter shows the one half a second later)
        run(["ffmpeg", "-v", "error", "-ss", f"{s + 0.02:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale=390:-2",
             os.path.join(tmp, f"f{s:02d}.png")])
    frames = sorted(glob.glob(os.path.join(tmp, "f*.png")))[:15]
    w, h = Image.open(frames[0]).size
    cols, top = 5, 54
    sheet = Image.new("RGB", (cols * w, top + 3 * h), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    big, small = ImageFont.truetype(FONT, 26), ImageFont.truetype(FONT, 19)
    d.text((10, 12), title, fill=(240, 240, 240), font=big)
    for k, f in enumerate(frames):
        x, y = (k % cols) * w, top + (k // cols) * h
        sheet.paste(Image.open(f), (x, y))
        lines = labels[k] if k < len(labels) else []
        box_h = 8 + 24 * len(lines)
        d.rectangle((x, y + h - box_h, x + w, y + h), fill=(0, 0, 0))
        for n, (txt, col) in enumerate(lines):
            d.text((x + 8, y + h - box_h + 4 + 24 * n), txt, fill=col, font=small)
        d.rectangle((x, y, x + w - 1, y + h - 1), outline=(60, 60, 60))
    sheet.save(out, quality=90)
    shutil.rmtree(tmp, ignore_errors=True)


def labels_for(a, plan, pics):
    """Per second shown: the second, the dry cuts of the second before it (time, way, word, why)."""
    out = []
    for s in range(15):
        t0, t1 = a + s - 1.0 + 1e-3, a + s + 1e-3
        lines = [(f"{a + s:.0f} s", (200, 200, 200))]
        for ev in plan or []:
            if t0 < ev["t"] <= t1 and not ev.get("hidden"):
                way = "SERRE" if ev["to"] == "tight" else "LARGE"
                col = (255, 210, 60) if ev["to"] == "tight" else (120, 200, 255)
                word = f" « {ev['word']} »" if ev["word"] else ""
                lines.append((f"{ev['t']:.1f} {way}{word}"[:32], col))
                lines.append((f"   {ev['why']}"[:32], col))
        for p in pics:
            if p[0] <= a + s < p[1]:
                lines.append((f"image plein écran ({'fixe' if len(p) > 2 and p[2] else 'zoom lent'})",
                              (170, 255, 170)))
        out.append(lines)
    return out


def main():
    import main as m
    import viral_fx
    import zooms
    os.makedirs(OUT, exist_ok=True)
    os.environ["SMOOTH_CAMERA"] = "1"
    meta = json.load(open(glob.glob(f"{JOB}/*_metadata.json")[0]))
    src = os.path.join("/app/uploads", meta["source_video"])
    if not os.path.exists(src):
        src = os.path.join(JOB, meta["source_video"])
    transcript = meta["transcript"]
    fps = float(eval(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                     "stream=r_frame_rate", "-of", "csv=p=0", src],
                                    capture_output=True, text=True).stdout.strip()))
    report = {}
    for n, a in CLIPS.items():
        c = meta["shorts"][n - 1]
        start, end = float(c["start"]), float(c["end"])
        cut = os.path.join(OUT, f"_cut_{n}.mp4")
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", src, "-t", f"{end - start:.3f}",
             "-c:v", "libx264", "-crf", "10", "-preset", "fast", "-c:a", "aac", "-b:a", "192k", cut])
        words = viral_fx.clip_words(transcript, start, end)
        punch = punch_span(words, c.get("punchline"))
        pics = [(float(b["t"]), float(b["t"]) + float(b["dur"])) for b in c.get("broll") or []]
        items = [{"t": float(b["t"]), "dur": float(b["dur"]), "path": os.path.join(JOB, b["image"])}
                 for b in c.get("broll") or []]
        for style in ("fixed", "references"):
            import plus
            os.environ["PLUS_FX_JSON"] = json.dumps({"zoom_style": style})
            os.environ["PLUS_ZOOMS_JSON"] = json.dumps(plus.ZOOMS)
            os.environ["BROLL_HERO_PUSH"] = f"{plus.STILL_PUSH:g}" if style == "references" else "1.0"
            os.environ["BROLL_HERO_STILL_EVERY"] = str(plus.STILL_EVERY) if style == "references" else "0"
            os.environ["BROLL_HERO_PUSH_CURVE"] = "linear"
            import broll
            importlib.reload(broll)
            if style == "references":
                zooms.write_cues(cut, words, punch=punch, pictures=pics)
            framed = os.path.join(OUT, f"_framed_{n}_{style}.mp4")
            assert m.render_clip(cut, framed, "vertical")
            plan = (zooms.read_cues(cut) or {}).get("applied") if style == "references" else []
            if os.path.exists(zooms.cues_path(cut)):
                os.remove(zooms.cues_path(cut))
            full = os.path.join(OUT, f"_full_{n}_{style}.mp4")
            overlay_drawings(framed, full, items, fps)
            tag = "zooms" if style == "references" else "fixe"
            mp4 = os.path.join(OUT, f"clip{n:02d}_{tag}.mp4")
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-i", full, "-t", "15", "-c:v", "libx264",
                 "-crf", "16", "-preset", "medium", "-c:a", "aac", "-movflags", "+faststart", mp4])
            shown = [(it["t"], it["t"] + it["dur"], it.get("still") or style != "references") for it in items]
            contact_sheet(mp4, os.path.join(OUT, f"clip{n:02d}_{tag}_planche.jpg"), labels_for(a, plan, shown),
                          f"Clip {n} — {tag} — {a:.0f}-{a + 15:.0f} s du clip (1 image/s)")
            report[f"clip{n:02d}_{tag}"] = {"window": [a, a + 15], "punch": punch, "pictures": pics, "plan": plan}
        for f in set(glob.glob(os.path.join(OUT, f"_*_{n}*.mp4*")) + glob.glob(os.path.join(OUT, f"_*_{n}_*"))):
            if os.path.exists(f):
                os.remove(f)
    with open(os.path.join(OUT, "plans.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: v["plan"] for k, v in report.items()}, ensure_ascii=False)[:5000])


if __name__ == "__main__":
    main()
