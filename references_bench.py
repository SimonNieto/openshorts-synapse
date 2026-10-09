"""Banc « titres + départs » de la recette références (9-oct-2026, RECETTE_REFERENCES.md §3-4).

Runs inside the backend container, from this checkout (its code):

    python references_bench.py [titles|selection] [--job b8e46c24-7f5e-48cf-8adc-c2d2677a241e]
                               [--out output/_stepup/etude2/v3/titres]

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


# --- (c) the selection weights on a whole episode (9-oct-2026, decoding of OptimalHealth) -------------------------
# ONE Claude Sonnet call reads the episode in the pipeline's own windows (the sentence starts marked as the
# clip-choice pass sees them) and, per window, gives its best moment with the labels the clip-choice pass now
# returns (audience_reach, practical, two_voices, everyday_thing) and a moment score; it also labels last week's
# clips. The code adds the weights (main._weights_for, plus.SELECTION["weights"]) and measures the face in the
# source (main.face_share, local). Compared: the top 10 without the weights, with them, and last week's 12.
LABEL_PROMPT = """You pick moments for a YouTube Shorts channel that cuts podcast clips
(neuroscience, health, the mind). The episode is given in windows; "[<seconds>]"
marks a sentence a clip may open on.

For EACH window, give the single best moment it holds as a short (20-60 s):
- `start`: the number of the mark it opens on; `end`: the second it ends (on
  its payoff, inside the window or up to 20 s after it);
- `moment_score`: 0-100, how strong the moment itself is for a cold viewer
  (the story, the payoff, the stake) — exactly as you would score it without
  the labels below;
- `label`: what it is about, 3-8 words;
{rules}
Then do the same labels (no start / end) for each of `published`, last week's
clips from this episode.

WINDOWS_JSON:
{windows}

PUBLISHED_JSON:
{published}

Return only: {{"moments": [{{"window": "<id>", "start": 0, "end": 0, "moment_score": 0, "label": "",
"audience_reach": "", "practical": false, "two_voices": false, "everyday_thing": ""}}],
"published": [{{"clip": "<id>", "moment_score": 0, "label": "", "audience_reach": "", "practical": false,
"two_voices": false, "everyday_thing": ""}}]}}
"""
def _addendum_block(first, stop):
    """The clip-choice prompt's own words for the labels (gemini_worker.PLAYBOOK_DETAIL_ADDENDUM)."""
    t = gemini_worker.PLAYBOOK_DETAIL_ADDENDUM
    a = t.index(first)
    return t[a:t.index(stop, a)]


# The same definitions as the clip-choice pass: everyday thing, who is concerned, two voices.
LABEL_RULES = _addendum_block("- ONE EVERYDAY THING", "- THE END:")
_ITEM = {"type": "object", "properties": {
    "moment_score": {"type": "integer"}, "label": {"type": "string"}, "audience_reach": {"type": "string"},
    "practical": {"type": "boolean"}, "two_voices": {"type": "boolean"}, "everyday_thing": {"type": "string"}}}
LABEL_SCHEMA = {"type": "object", "properties": {
    "moments": {"type": "array", "items": {**_ITEM, "properties": {
        **_ITEM["properties"], "window": {"type": "string"}, "start": {"type": "number"}, "end": {"type": "number"}}}},
    "published": {"type": "array", "items": {**_ITEM, "properties": {
        **_ITEM["properties"], "clip": {"type": "string"}}}}},
    "required": ["moments", "published"]}


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0)) / max(1e-6, min(a1 - a0, b1 - b0))


def selection(job, out, weights=None):
    import clip_selection
    import plus
    os.environ["SELECTION_WEIGHTS"] = json.dumps(weights or plus.SELECTION["weights"])
    meta = _load(glob.glob(f"/app/output/{job}/*metadata.json")[0])
    tr = meta["transcript"]
    words = [{"w": w["word"], "s": w["start"], "e": w["end"]} for seg in tr["segments"] for w in seg.get("words", [])]
    duration = words[-1]["e"]
    windows = clip_selection.build_transcript_windows(tr, duration, window_seconds=90)
    payload = [{"id": w["id"], "start": round(w["start"], 1), "end": round(w["end"], 1),
                "text": main.marked_text(words, w["start"], w["end"])} for w in windows]
    short = job.split("-")[0]
    pub = {row[3]: row for row in _load(f"{STEPUP}/etude2/donnees/vues_publiques_2026-10-09.json")["shorts"]}
    studio = _load(f"{STEPUP}/etude2/donnees/studio_2026-10-09.json")
    week = []
    for n, s in enumerate(meta["shorts"], 1):
        tag = f"{short}_c{n:02d}"
        p = pub.get(tag) or ["", s.get("video_title_for_youtube_short"), None]
        week.append({"clip": f"c{n:02d}", "start": float(s["start"]), "end": float(s["end"]), "title": p[1],
                     "views": p[2], "stayed": (studio.get(p[0]) or {}).get("stayed"),
                     "predicted_score": s.get("predicted_score"),
                     "text": " ".join(w["w"].strip() for w in words if s["start"] - 0.05 <= w["s"] < s["end"])})
    prompt = LABEL_PROMPT.format(rules=LABEL_RULES, windows=json.dumps(payload, ensure_ascii=False),
                                 published=json.dumps([{"clip": c["clip"], "text": c["text"]} for c in week],
                                                      ensure_ascii=False))
    ans = ai_brain.claude_json(prompt, LABEL_SCHEMA, model="sonnet", effort="low", timeout=900)
    video = (glob.glob(f"/app/uploads/{job}_*") + glob.glob(f"/app/output/{job}/{job}_*.mkv"))[:1]
    moments = []
    for m in ans.get("moments") or []:
        try:
            start, end = float(m["start"]), float(m["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end - start < 10:
            continue
        c = {**m, "start": start, "end": end, "predicted_score": m.get("moment_score"),
             "opening_score": m.get("moment_score")}
        if video:
            c["face_share"] = main.face_share(video[0], start, end)
            c["face_small"] = c["face_share"] is not None and c["face_share"] < main.FACE_SMALL_SHARE
        c["weights"] = main._weights_for(c)
        c["base"] = int(m.get("moment_score") or 0)
        c["weighted"] = int(round(c["base"] + sum(c["weights"].values())))
        c["week"] = next((w["clip"] for w in week if _overlap(start, end, w["start"], w["end"]) >= 0.5), "")
        moments.append(c)
    # Two windows overlap by 30 s: the same moment twice keeps its best copy.
    moments.sort(key=lambda c: c["weighted"], reverse=True)
    kept = []
    for c in moments:
        if all(_overlap(c["start"], c["end"], k["start"], k["end"]) < 0.5 for k in kept):
            kept.append(c)
    labels = {p.get("clip"): p for p in ans.get("published") or []}
    for w in week:
        lab = labels.get(w["clip"]) or {}
        w.update({k: lab.get(k) for k in ("moment_score", "label", "audience_reach", "practical", "two_voices",
                                          "everyday_thing")})
        if video:
            w["face_share"] = main.face_share(video[0], w["start"], w["end"])
            w["face_small"] = w["face_share"] is not None and w["face_share"] < main.FACE_SMALL_SHARE
        w["weights"] = main._weights_for(w)
        w.pop("text", None)
    with_w = kept[:10]
    without = sorted(kept, key=lambda c: c["base"], reverse=True)[:10]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "selection.json"), "w", encoding="utf-8") as f:
        json.dump({"job": job, "weights": json.loads(os.environ["SELECTION_WEIGHTS"]), "moments": kept,
                   "week": week, "usage": ai_brain.USAGE}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, "selection.md"), "w", encoding="utf-8") as f:
        f.write(selection_report(job, kept, with_w, without, week))
    return kept, week


def _mmss(t):
    t = int(t)
    return f"{t // 60}:{t % 60:02d}"


def _w(ws):
    return " ".join(f"{k} {v:+g}" for k, v in ws.items()) or "—"


def selection_report(job, kept, with_w, without, week):
    out = [f"# Banc sélection « public concerné » — job {job[:8]} (JRE #2553-004)", "",
           "Un seul appel Claude Sonnet lit l'épisode entier dans les fenêtres du pipeline (débuts de phrase marqués) "
           "et donne, par fenêtre, son meilleur moment avec une note du moment seul et les étiquettes que la "
           "sélection rend maintenant (public concerné, conseil pratique / mythe cassé, deux voix, chose du "
           "quotidien). Il étiquette aussi les 12 clips de la semaine. Le code ajoute les poids "
           "(`plus.SELECTION[\"weights\"]`) et mesure le visage dans la source (local, sans IA). "
           f"Poids : {json.dumps(json.loads(os.environ['SELECTION_WEIGHTS']))}.", "",
           "Lecture : « pts » = la note du moment ; « + poids » = ce que la pondération ajoute ; « sem. » = le clip "
           "de la semaine qui recouvre ce moment.", "",
           "## Les 10 moments en tête avec la pondération", "",
           "| # | Moment | Sujet | Public | Pratique | 2 voix | Visage | pts | + poids | Total | sem. |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, c in enumerate(with_w, 1):
        out.append(f"| {i} | {_mmss(c['start'])}-{_mmss(c['end'])} | {c.get('label')} | {c.get('audience_reach')} | "
                   f"{'oui' if c.get('practical') else '—'} | {'oui' if c.get('two_voices') else '—'} | "
                   f"{c.get('face_share') if c.get('face_share') is not None else '?'} | {c['base']} | "
                   f"{_w(c['weights'])} | **{c['weighted']}** | {c['week'] or '—'} |")
    ins = [c for c in with_w if c not in without]
    outs = [c for c in without if c not in with_w]
    out += ["", f"Sans la pondération (même appel, note du moment seule), le top 10 diffère de "
            f"{len(ins)} moment(s) : entrent {', '.join(c.get('label') or '?' for c in ins) or '—'} ; sortent "
            f"{', '.join(c.get('label') or '?' for c in outs) or '—'}.", "",
            "## Les 12 clips de la semaine, étiquetés de la même façon", "",
            "| Clip | Titre publié | Vues | Ont continué | Sujet | Public | Pratique | 2 voix | Visage | pts | + poids "
            "| Dans le top 10 ? |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    top = {c["week"] for c in with_w if c["week"]}
    for w in week:
        views = f"{w['views']:,}".replace(",", " ") if isinstance(w.get("views"), int) else "—"
        out.append(f"| {w['clip']} | {w['title']} | {views} | {w['stayed'] + ' %' if w.get('stayed') else '—'} | "
                   f"{w.get('label')} | {w.get('audience_reach')} | {'oui' if w.get('practical') else '—'} | "
                   f"{'oui' if w.get('two_voices') else '—'} | {w.get('face_share') if w.get('face_share') is not None else '?'}"
                   f" | {w.get('moment_score')} | {_w(w['weights'])} | {'oui' if w['clip'] in top else 'non'} |")
    reach = {r: sum((w.get('audience_reach') or '') == r for w in week) for r in ("everyone", "many", "few")}
    reach_top = {r: sum((c.get('audience_reach') or '') == r for c in with_w) for r in ("everyone", "many", "few")}
    out += ["", f"Public concerné — semaine : {reach['everyone']} « everyone », {reach['many']} « many », "
            f"{reach['few']} « few » ; top 10 pondéré : {reach_top['everyone']} / {reach_top['many']} / "
            f"{reach_top['few']}. Clips de la semaine repris dans le top 10 : {len(top)}/12.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", nargs="?", default="titles", choices=("titles", "selection"))
    ap.add_argument("--job", default="b8e46c24-7f5e-48cf-8adc-c2d2677a241e")
    ap.add_argument("--out", default="/app/output/_stepup/etude2/v3/titres")
    a = ap.parse_args()
    if a.what == "selection":
        selection(a.job, a.out)
    else:
        bench(a.job, a.out)
