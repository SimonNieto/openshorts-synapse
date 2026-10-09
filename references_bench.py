"""Banc « titres + départs » de la recette références (9-oct-2026, RECETTE_REFERENCES.md §3-4).

Runs inside the backend container, from this checkout (its code):

    python references_bench.py [--job b8e46c24-7f5e-48cf-8adc-c2d2677a241e] [--out output/_stepup/etude2/v3/titres]

(a) Titles: every clip of the job retitled with the title block of the house recipe
    (gemini_worker.title_rules(), style "references"), ONE Claude Sonnet call per clip through the app's own
    client (ai_brain.claude_json, answers kept in the AI cache). In: the clip's words, its topic and its payoff.
    Out: the title and ``subject_words`` (the words naming the clip's thing, as the clip-choice pass returns them).
(b) Departures: when ``subject_words`` is heard with the job's cut (before) and after main.open_on_subject
    (after), simulated on the source transcript — no other call.
Writes titres_departs.json + titres_departs.md in --out; old titles, views and "stayed" from the step-up study
files (output/_stepup).
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["TITLE_STYLE"] = "references"
os.environ.setdefault("YOLO_MODEL_PATH", "/app/yolov8n.pt")

import ai_brain  # noqa: E402
import gemini_worker  # noqa: E402
import main  # noqa: E402
import playbook  # noqa: E402

STEPUP = "/app/output/_stepup"
MIN_SECS = 15   # plus.CLIP_FORMATS["standard"]["clip_min"]

PROMPT = """You write the YouTube Shorts title of ONE clip cut from a podcast episode.

The clip, word for word (what the viewer hears, in order):
\"\"\"{text}\"\"\"

Its topic family: {topic}
The payoff it ends on: "{punchline}"
{rules}
Also return `subject_words`: the 1 to 3 words, copied VERBATIM from the clip
above, that name the thing or the event the clip is about — what the title
names.

Return only: {{"video_title_for_youtube_short": "<the title>", "subject_words": "<verbatim words>"}}
"""
SCHEMA = {"type": "object",
          "properties": {"video_title_for_youtube_short": {"type": "string"}, "subject_words": {"type": "string"}},
          "required": ["video_title_for_youtube_short", "subject_words"]}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def bench(job, out):
    meta = _load(glob.glob(f"/app/output/{job}/*metadata.json")[0])
    words = [{"w": w["word"], "s": w["start"], "e": w["end"]}
             for seg in meta["transcript"]["segments"] for w in seg.get("words", [])]
    short = job.split("-")[0]
    by_tag = {c["tag"]: c for c in _load(f"{STEPUP}/clips.json")["clips"]}
    pub = {row[3]: row for row in _load(f"{STEPUP}/etude2/donnees/vues_publiques_2026-10-09.json")["shorts"]}
    studio = _load(f"{STEPUP}/etude2/donnees/studio_2026-10-09.json")
    rows = []
    for n, s in enumerate(meta["shorts"], 1):
        tag = f"{short}_c{n:02d}"
        c = by_tag.get(tag) or {}
        start, end = float(s["start"]), float(s["end"])
        text = " ".join(w["w"].strip() for w in words if start - 0.05 <= w["s"] < end)
        prompt = PROMPT.format(text=text, topic=c.get("topic") or s.get("topic_bucket") or "",
                               punchline=s.get("punchline") or c.get("punchline") or "",
                               rules=gemini_worker.title_rules())
        ans = ai_brain.claude_json(prompt, SCHEMA, model="sonnet", effort="medium")
        title = str(ans.get("video_title_for_youtube_short") or "").strip()
        subject = str(ans.get("subject_words") or "").strip()
        p = pub.get(tag) or ["", "", None, tag, "", ""]
        st = studio.get(p[0]) or {}
        clip = {"start": start, "end": end, "subject_words": subject, "punchline": s.get("punchline") or "",
                "hook_line": s.get("hook_line") or ""}
        before = main.subject_said_at(clip, words)
        moved = main.open_on_subject(clip, words, MIN_SECS)
        rows.append({
            "clip": f"c{n:02d}", "video_id": p[0], "old_title": p[1] or s.get("video_title_for_youtube_short"),
            "views": p[2], "stayed": st.get("stayed"), "opening": p[4],
            "new_title": title, "title_problems": playbook.title_problems(title, style="references"),
            "subject_words": subject, "said_at_before": before, "said_at_after": clip.get("subject_said_at"),
            "start_before": round(start, 2), "start_after": round(float(clip["start"]), 2),
            "moved_by": round(float(clip["start"]) - start, 2) if moved is not None else 0.0,
            "length_before": round(end - start, 1), "length_after": round(end - float(clip["start"]), 1),
            "first_sentence_before": main._sentence_text(words, main._first_heard(words, start), 30),
            "first_sentence_after": main._sentence_text(words, main._first_heard(words, float(clip["start"])), 30),
        })
        r = rows[-1]
        print(f"{tag}: {r['old_title']!r} -> {title!r} | {subject!r} {before} -> {r['said_at_after']}", flush=True)
    sets = playbook.title_set_problems([{"video_title_for_youtube_short": r["new_title"], "predicted_score": 0}
                                        for r in rows])
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "titres_departs.json"), "w", encoding="utf-8") as f:
        json.dump({"job": job, "rows": rows, "set_problems": {rows[i]["clip"]: v for i, v in sets.items()},
                   "usage": ai_brain.USAGE}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, "titres_departs.md"), "w", encoding="utf-8") as f:
        f.write(report(job, rows, sets))
    return rows


def _sec(v):
    return "jamais" if v is None else f"{v:.1f} s".replace(".", ",")


def report(job, rows, sets):
    """The two tables, in French (the user's language)."""
    target = main.OPENING_SUBJECT_SECONDS
    early_b = sum(r["said_at_before"] is not None and r["said_at_before"] <= target for r in rows)
    early_a = sum(r["said_at_after"] is not None and r["said_at_after"] <= target for r in rows)
    out = [f"# Banc recette « références » — job {job[:8]} (JRE #2553-004)", "",
           "Généré par `references_bench.py` (branche de la recette). Un appel Claude Sonnet par clip, par le "
           "client de l'app (`ai_brain.claude_json`), avec le nouveau bloc titre "
           "(`gemini_worker.REFERENCES_TITLE_ADDENDUM`). Entrée : les mots du clip publié, son sujet, sa chute.", "",
           "## (a) Titres", "",
           "| Clip | Ancien titre (publié) | Vues | Ont continué | Nouveau titre |",
           "|---|---|---|---|---|"]
    for r in rows:
        stayed = f"{r['stayed']} %" if r.get("stayed") else "—"
        views = f"{r['views']:,}".replace(",", " ") if isinstance(r.get("views"), int) else "—"
        flag = f" ⚠️ {'; '.join(r['title_problems'])}" if r["title_problems"] else ""
        out.append(f"| {r['clip']} | {r['old_title']} | {views} | {stayed} | **{r['new_title']}**{flag} |")
    out += ["", f"Contrôles du code : {sum(not r['title_problems'] for r in rows)}/{len(rows)} titres passent "
            f"(4-8 mots, sans émoji, sans nom, sans mot qui a fait bloquer un short) ; série : "
            f"{'aucune répétition' if not sets else sets}.", "",
            "## (b) Départs : à quelle seconde le mot-sujet est dit", "",
            f"Mot-sujet = `subject_words` rendu par Claude avec le titre. Avant = la coupe publiée ; après = "
            f"`main.open_on_subject` rejoué sur le transcript de la source (fin et chute inchangées, clip ≥ "
            f"{MIN_SECS} s). Cible : avant {target:g} s.", "",
            "| Clip | Mot-sujet | Dit à (avant) | Dit à (après) | Départ décalé | 1re phrase après |",
            "|---|---|---|---|---|---|"]
    for r in rows:
        moved = f"+{r['moved_by']:.1f} s".replace(".", ",") if r["moved_by"] else "—"
        out.append(f"| {r['clip']} | {r['subject_words']} | {_sec(r['said_at_before'])} | "
                   f"{_sec(r['said_at_after'])} | {moved} | {r['first_sentence_after'][:80]} |")
    out += ["", f"Mot-sujet dit avant {target:g} s : **{early_b}/{len(rows)} avant, {early_a}/{len(rows)} après**.",
            ""]
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="b8e46c24-7f5e-48cf-8adc-c2d2677a241e")
    ap.add_argument("--out", default="/app/output/_stepup/etude2/v3/titres")
    a = ap.parse_args()
    bench(a.job, a.out)
