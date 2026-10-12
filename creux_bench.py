"""Banc « le creux 5-13 s » (12-oct-2026).

YouTube Studio of the first two « références » shorts (JRE #1109, 10-oct): 65 % stayed past the first seconds,
then of those still there at 4 s, 41-46 % were left at 15 s (the record: 63 %): banter or a vague list between
the opening sentence and the fact the title promises, heard at 17-20 s. The clip choice now names that fact
(``fact_words``) and may cut the stall (cut_out why "stall"); main.fact_said_at times it once the cuts are out.

Runs inside the backend container, from this checkout (its code):

    python creux_bench.py prompt [--job 0e9eb341-97a7-4069-964c-3634e359fae9] [--out output/_stepup/creux]
    python creux_bench.py render --clips 5,8 [--job ...] [--out ...]

prompt: every clip of the job read again with the clip choice's own `fact_words` and `cut_out` rules
        (gemini_worker.PLAYBOOK_DETAIL_ADDENDUM, cut out of it verbatim), ONE Claude Sonnet call per clip through
        the app's client (answers kept in the AI cache); then main.check_cut_out and main.fact_said_at, before and
        after the cut. Writes creux.json + creux.md in --out.
render: the clips listed, re-made by the whole pipeline of this checkout (the job's profile, plus.job_env) with the
        cut_out passages of creux.json — no clip choice, no title or hook call: main.py runs with its
        get_viral_clips replaced by these clips (a patched copy, removed after). Output in --out/render.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("YOLO_MODEL_PATH", "/app/yolov8n.pt")

JOB = "0e9eb341-97a7-4069-964c-3634e359fae9"
OUT = "/app/output/_stepup/creux"
MIN_SECS = 15   # plus.CLIP_FORMATS: the shortest a clip may get

PROMPT = """You re-read ONE clip already cut from a podcast episode, for a YouTube Shorts channel.

Its title: "{title}"
It opens on: "{hook}"
It ends on its payoff: "{punchline}"

The clip, word for word (what the viewer hears, in order, with the second each sentence starts at):
\"\"\"{text}\"\"\"

Apply exactly these two rules of the clip choice:
{rules}

Return only: {{"fact_words": "<verbatim or empty>", "cut_out": [{{"first_words": "...", "last_words": "...", "why": "..."}}]}}
"""
SCHEMA = {"type": "object",
          "properties": {"fact_words": {"type": "string"},
                         "cut_out": {"type": "array", "items": {
                             "type": "object",
                             "properties": {"first_words": {"type": "string"}, "last_words": {"type": "string"},
                                            "why": {"type": "string"}},
                             "required": ["first_words", "last_words", "why"]}}},
          "required": ["fact_words", "cut_out"]}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _meta_path(job):
    return glob.glob(f"/app/output/{job}/*_metadata.json")[0]


def _words(meta):
    return [{"w": w["word"], "s": w["start"], "e": w["end"]}
            for seg in meta["transcript"]["segments"] for w in seg.get("words", [])]


def rules():
    """The `fact_words` and `cut_out` bullets of the clip choice, verbatim."""
    import gemini_worker
    text = gemini_worker.PLAYBOOK_DETAIL_ADDENDUM
    a = text.index("- `fact_words`")
    b = text.index("- DESCRIPTIONS")
    return text[a:b].rstrip()


def _marked(words, start, end):
    import main
    return main.marked_text(words, start, end) or " ".join(w["w"].strip() for w in words
                                                          if start - 0.05 <= w["s"] < end)


def prompt_bench(job, out):
    import ai_brain
    import main
    meta = _load(_meta_path(job))
    words = _words(meta)
    block = rules()
    rows = []
    for n, s in enumerate(meta["shorts"], 1):
        start, end = float(s["start"]), float(s["end"])
        prompt = PROMPT.format(title=s.get("video_title_for_youtube_short") or "", hook=s.get("hook_line") or "",
                               punchline=s.get("punchline") or "", text=_marked(words, start, end), rules=block)
        ans = ai_brain.claude_json(prompt, SCHEMA, model="sonnet", effort="medium")
        clip = {"start": start, "end": end, "hook_line": s.get("hook_line") or "",
                "hook_aligned": s.get("hook_aligned"), "punchline": s.get("punchline") or "",
                "fact_words": str(ans.get("fact_words") or "").strip(), "cut_out": []}
        before = main.fact_said_at(clip, words)
        clip["cut_out"] = ans.get("cut_out") or []
        kept, dropped = main.check_cut_out(clip, words, MIN_SECS)
        after = main.fact_said_at(clip, words)
        spans = main.cut_out_spans(clip, words)
        rows.append({"clip": n, "title": s.get("video_title_for_youtube_short"), "start": start, "end": end,
                     "fact_words": clip["fact_words"], "fact_before": before, "fact_after": after,
                     "cut_out": clip["cut_out"], "dropped": clip.get("cut_out_dropped") or [],
                     "cut_seconds": round(sum(e - s for s, e in spans), 2),
                     "cut_text": [" ".join(w["w"].strip() for w in words if a - 0.01 <= w["s"] and w["e"] <= b + 0.01)
                                  for a, b in spans]})
        r = rows[-1]
        print(f"c{n}: {r['title']!r} fact {before} -> {after} s | {kept} cut ({r['cut_seconds']} s), "
              f"{dropped} dropped", flush=True)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "creux.json"), "w", encoding="utf-8") as f:
        json.dump({"job": job, "rows": rows, "usage": ai_brain.USAGE}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, "creux.md"), "w", encoding="utf-8") as f:
        f.write(report(job, rows))
    return rows


def report(job, rows):
    import main
    lines = [f"# Banc « le creux 5-13 s » — job {job}", "",
             f"Fait promis par le titre, seconde où il est entendu (avant / après les coupes) ; en retard au-delà de "
             f"{main.FACT_LATE_SECONDS:g} s.", "",
             "| Clip | Titre | Fait (mots) | Avant | Après | Coupé | Passages |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        cuts = " ; ".join(f"{c['why']}: « {c['from']} … {c['to']} »" for c in r["cut_out"]) or "—"
        sec = lambda v: "—" if v is None else f"{v:.1f}"  # noqa: E731
        lines.append(f"| c{r['clip']} | {r['title']} | {r['fact_words'] or '—'} | {sec(r['fact_before'])} | "
                     f"{sec(r['fact_after'])} | {r['cut_seconds']:.1f} s | {cuts} |")
    lines += ["", "## Ce qui est coupé, mot pour mot", ""]
    for r in rows:
        for t in r["cut_text"]:
            lines.append(f"- c{r['clip']} : « {t} »")
        for d in r["dropped"]:
            lines.append(f"- c{r['clip']} refusé ({d['reason']}) : « {d['from']} … {d['to']} »")
    return "\n".join(lines) + "\n"


# --- render -----------------------------------------------------------------------------------------------

def bench_clips(transcript, input_video):
    """What the patched main.py takes in place of get_viral_clips: the listed clips of the job, as the job
    left them, with the cut_out passages and fact_words of creux.json (checked again), the episode brief and
    bible of the job (no call)."""
    import ai_brain
    import main
    job, out, picks = os.environ["CREUX_JOB"], os.environ["CREUX_OUT"], json.loads(os.environ["CREUX_CLIPS"])
    meta = _load(_meta_path(job))
    words = _words(meta)
    bench = {r["clip"]: r for r in _load(os.path.join(out, "creux.json"))["rows"]}
    keep = ("start", "end", "source_window_id", "predicted_score", "video_description_for_tiktok",
            "video_description_for_instagram", "video_title_for_youtube_short", "viral_hook_text", "why_chosen",
            "hook_line", "punchline", "topic_bucket", "hook_accent", "moment_nature", "subject_words",
            "everyday_thing", "audience_reach", "practical", "two_voices", "opening_score", "opening_misses",
            "moment_id", "hook_aligned", "end_on_payoff", "clean_end")
    shorts = []
    for n in picks:
        s = {k: v for k, v in meta["shorts"][n - 1].items() if k in keep}
        r = bench.get(n) or {}
        s["fact_words"] = r.get("fact_words") or ""
        s["cut_out"] = [{"from": c["from"], "to": c["to"], "why": c["why"]} for c in r.get("cut_out") or []]
        main.check_cut_out(s, words, MIN_SECS)
        main.check_opening(s, words)
        print(f"   🧪 Banc creux: c{n} {s.get('video_title_for_youtube_short')!r}, cut_out {s['cut_out']}, "
              f"fact at {s.get('fact_said_at')} s", flush=True)
        shorts.append(s)
    ai_brain.EPISODE_BRIEF = meta.get("episode_brief")
    ai_brain.EPISODE_BIBLE = meta.get("episode_bible")
    return {"shorts": shorts}


def render(job, out, clips):
    import plus
    here = os.path.dirname(os.path.abspath(__file__))
    meta = _load(_meta_path(job))
    profiles = _load("/app/clip_profiles.json")
    profiles = profiles if isinstance(profiles, list) else profiles.get("profiles", profiles)
    pid = (meta.get("plus_profile") or {}).get("id")
    profile = next(p for p in (profiles if isinstance(profiles, list) else profiles.values()) if p.get("id") == pid)
    env = {**os.environ, **plus.job_env(profile)}
    env.update({"CREUX_JOB": job, "CREUX_OUT": out, "CREUX_CLIPS": json.dumps(clips),
                "PLUS_PROFILE_JSON": json.dumps(meta.get("plus_profile") or {}),
                "TITLE_VARIETY": "0", "HOOK_CHECK": "0", "PYTHONIOENCODING": "utf-8"})
    src = open(os.path.join(here, "main.py"), encoding="utf-8").read()
    call = "clips_data = get_viral_clips(transcript, duration, video_path=input_video)"
    assert src.count(call) == 1, "main.py changed: the clip choice call is not found once"
    patched = os.path.join(here, "_main_creux_bench.py")
    with open(patched, "w", encoding="utf-8") as f:
        f.write(src.replace(call, "clips_data = __import__('creux_bench').bench_clips(transcript, input_video)"))
    rdir = os.path.join(out, "render")
    os.makedirs(rdir, exist_ok=True)
    tpath = os.path.join(rdir, "transcript.json")
    with open(tpath, "w", encoding="utf-8") as f:
        json.dump(meta["transcript"], f)
    source = os.path.join("/app/uploads", meta["source_video"])
    try:
        with open(os.path.join(rdir, "_job.log"), "w", encoding="utf-8") as log:
            log.write("ENV " + json.dumps({k: v for k, v in plus.job_env(profile).items()}) + "\n")
            log.flush()
            code = subprocess.call([sys.executable, "-u", patched, "-i", source, "-o", rdir, "--transcript", tpath],
                                   cwd=here, env=env, stdout=log, stderr=subprocess.STDOUT)
    finally:
        os.remove(patched)
    print(f"render exit {code}: {rdir}", flush=True)
    return code


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["prompt", "render"])
    ap.add_argument("--job", default=JOB)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--clips", default="5,8")
    a = ap.parse_args()
    if a.mode == "prompt":
        prompt_bench(a.job, a.out)
    else:
        sys.exit(render(a.job, a.out, [int(x) for x in a.clips.split(",") if x.strip()]))
