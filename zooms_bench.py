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
    import montage
    import plus
    import punch_in
    import recut
    report = {}
    for n, a0 in CLIPS.items():
        c0 = meta["shorts"][n - 1]
        start, end = float(c0["start"]), float(c0["end"])
        raw_words = viral_fx.clip_words(transcript, start, end)
        for style in ("fixed", "references"):
            c = json.loads(json.dumps(c0))
            os.environ["PLUS_FX_JSON"] = json.dumps({"zoom_style": style})
            os.environ["PLUS_ZOOMS_JSON"] = json.dumps(plus.ZOOMS)
            refs = style == "references"
            os.environ["BROLL_HERO_PUSH"] = "1.0"
            os.environ["BROLL_HERO_PUSH_RATE"] = f"{plus.STILL_RATE:g}" if refs else "0"
            os.environ["BROLL_HERO_STILL_EVERY"] = str(plus.STILL_EVERY) if refs else "0"
            os.environ["BROLL_HERO_PUSH_CURVE"] = "linear"
            import broll
            importlib.reload(broll)
            zooms.configure()
            # The montage first, as a job does it (the silences cut, the joins to hide).
            cut = os.path.join(OUT, f"_cut_{n}_{style}.mp4")
            mont = montage.apply(src, c, transcript, start, end, cut, dict(plus.MONTAGE))
            if mont:
                segs = mont["segments"]
                words = viral_fx.clip_words(mont["transcript"], 0.0, mont["duration"])

                def to_clip(t):
                    v = recut.source_to_clip(segs, start + t)
                    return v if v is not None else t
            else:
                run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", src, "-t", f"{end - start:.3f}",
                     "-c:v", "libx264", "-crf", "10", "-preset", "fast", "-c:a", "aac", "-b:a", "192k", cut])
                words = raw_words

                def to_clip(t):
                    return t
            joins = (mont or {}).get("joins") or []
            hide = [j["t"] for j in joins if j.get("verdict") == "hide"]
            clean = [j["t"] for j in joins if j.get("verdict") == "clean"]
            punch = (mont or {}).get("punch") or punch_span(words, c0.get("punchline"))
            items = [{"t": round(to_clip(float(b["t"])), 3), "dur": float(b["dur"]),
                      "path": os.path.join(JOB, b["image"])} for b in c0.get("broll") or []]
            pics = [(it["t"], it["t"] + it["dur"]) for it in items]
            if refs:
                zooms.write_cues(cut, words, joins=hide, punch=punch, pictures=pics, silences=clean)
            framed = os.path.join(OUT, f"_framed_{n}_{style}.mp4")
            assert m.render_clip(cut, framed, "vertical")
            plan = (zooms.read_cues(cut) or {}).get("applied") if refs else []
            if os.path.exists(zooms.cues_path(cut)):
                os.remove(zooms.cues_path(cut))
            full = os.path.join(OUT, f"_full_{n}_{style}.mp4")
            overlay_drawings(framed, full, items, fps)
            if not refs and mont:
                # The fixed recipe's tight frames (punch_in.finish), after the pictures, as a job cuts them.
                tight_out = os.path.join(OUT, f"_tight_{n}_{style}.mp4")
                wins = punch_in.finish(full, tight_out, {"broll": [{"t": it["t"], "dur": it["dur"]} for it in items]},
                                       words=words, montage_report=mont, hook_end=None, source_height=1080)
                if wins:
                    full = tight_out
                    for w in wins:
                        plan += [{"t": w["a"], "to": "tight", "why": f"plan serré ({w['why']})", "word": ""},
                                 {"t": w["b"], "to": "wide", "why": "fin du plan serré", "word": ""}]
            a = round(to_clip(a0), 2)
            tag = "zooms" if refs else "fixe"
            mp4 = os.path.join(OUT, f"clip{n:02d}_{tag}.mp4")
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-i", full, "-t", "15", "-c:v", "libx264",
                 "-crf", "16", "-preset", "medium", "-c:a", "aac", "-movflags", "+faststart", mp4])
            shown = [(it["t"], it["t"] + it["dur"], it.get("still") or not refs) for it in items]
            contact_sheet(mp4, os.path.join(OUT, f"clip{n:02d}_{tag}_planche.jpg"), labels_for(a, plan, shown),
                          f"Clip {n} — {tag} — {a:.1f}-{a + 15:.1f} s du clip monté (1 image/s)")
            # The rhythm: speech rate before / after the montage, changes on screen a minute, the longest stretch.
            dur = (mont or {}).get("duration") or (end - start)
            changes = sorted({round(x["t"], 2) for x in plan if not x.get("hidden")}
                             | {round(x, 2) for p_ in pics for x in p_}
                             | {round(x, 2) for x in (mont or {}).get("camera_cuts") or []})
            gaps = [b_ - a_ for a_, b_ in zip([0.0] + changes, changes + [dur])]
            span = lambda ws: (ws[-1]["end"] - ws[0]["start"]) if ws else 1.0
            report[f"clip{n:02d}_{tag}"] = {
                "window": [a, a + 15], "punch": punch, "pictures": pics, "plan": plan,
                "montage_saved_s": (mont or {}).get("saved", 0.0), "duration": round(dur, 2),
                "joins": {"hide": len(hide), "clean": len(clean), "refused": len((mont or {}).get("refused") or [])},
                "words_per_s_raw": round(len(raw_words) / span(raw_words), 2),
                "words_per_s_cut": round(len(words) / span(words), 2),
                "changes_per_min": round(len(changes) / dur * 60, 1), "longest_without_change_s": round(max(gaps), 1)}
            print(f"   📊 clip {n} {tag}: " + json.dumps({k: v for k, v in report[f"clip{n:02d}_{tag}"].items()
                                                      if k not in ("plan", "pictures", "punch")}, ensure_ascii=False))
        for f in set(glob.glob(os.path.join(OUT, f"_*_{n}*.mp4*")) + glob.glob(os.path.join(OUT, f"_*_{n}_*"))):
            if os.path.exists(f):
                os.remove(f)
    with open(os.path.join(OUT, "plans.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
