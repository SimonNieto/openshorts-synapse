"""What did the published clips actually get? Joins the per-clip playbook
exports (``output/<job>/<clip>_playbook.json``, playbook.export_clip) to a CSV
of real views and prints what to tune the selection with: median views by
topic, by length, by title shape, by whether the clip opens on its hook
sentence, and how well the AI's ``predicted_score`` tracks the views.

    python stats_ingest.py views.csv                 # exports read from ./output
    python stats_ingest.py views.csv --output /app/output --json stats.json

The CSV is an export of YouTube Studio or Upload-Post, or a hand-made file.
One column says which clip the row is about — ``moment_id``, a file name
(``file`` / ``clip_file``), or the title — and one gives the views; a
retention column is used when there is one. Column names are matched loosely
(English or French, any case); ``,`` ``;`` and tab separators all work. A clip
posted on several platforms can have one row per platform: views add up.

Standard library only, no AI call. app.py's /api/plus/stats uses the same
grouping helpers on Upload-Post's live numbers.
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import json
import math
import os
import re
import sys
import unicodedata

# The title shapes the playbook asks for (playbook.TITLE_OPENERS) and the ones
# it forbids; anything else is "other".
TITLE_FORMS = ("can", "is", "does", "are", "do", "will", "should", "why", "how", "what")
DURATION_BUCKETS = ((20, "< 20 s"), (30, "20-30 s"), (40, "30-40 s"), (50, "40-50 s"), (60, "50-60 s"))

_ID_COLUMNS = {
    "moment_id": ("moment_id", "moment id", "moment"),
    "file": ("file", "fichier", "filename", "file name", "file_name", "clip_file", "clip file", "clip",
             "video_file", "video file"),
    "title": ("title", "titre", "video title", "titre de la video", "post_title", "post title", "caption"),
}
_VIEWS_COLUMNS = ("views", "vues", "view_count", "view count", "views_count", "nombre de vues", "plays")
_RETENTION_COLUMNS = ("retention", "average percentage viewed (%)", "average percentage viewed",
                      "pourcentage moyen de visionnage (%)", "pourcentage moyen de visionnage",
                      "avg_view_percentage", "average view percentage", "retention (%)")


def _norm(text) -> str:
    """Lower case, no accents, single spaces: how column names are compared."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.replace("﻿", "")).strip().lower()


def norm_title(title) -> str:
    """A title as a join key: letters and digits only (emojis, case and
    punctuation differ between the export and what the platform shows)."""
    return re.sub(r"[^a-z0-9]+", " ", _norm(title)).strip()


def file_key(name) -> str:
    """'subtitled_17_hooked_16_<job>_Ep_clip_3.mp4' -> '<job>_ep_clip_3': the
    canonical clip name, whatever layer of it was published."""
    base = os.path.splitext(os.path.basename(str(name or "").replace("\\", "/")))[0]
    while True:
        stripped = re.sub(r"^(?:subtitled|hooked)_\d+_", "", base)
        if stripped == base:
            break
        base = stripped
    return base.strip().lower()


def parse_number(value):
    """'7,100' / '7 100' / '7.1K' / '45,3 %' -> a float, None when it is not a number."""
    s = str(value if value is not None else "").replace(" ", " ").replace("\xa0", " ").strip().rstrip("%").strip()
    if not s:
        return None
    mult = 1.0
    m = re.fullmatch(r"(.*?)\s*([kKmM])", s)
    if m:
        s, mult = m.group(1), (1e3 if m.group(2).lower() == "k" else 1e6)
    s = s.replace(" ", "")
    if re.fullmatch(r"-?[1-9]\d{0,2}([,.]\d{3})+", s):     # 7,100 / 7.100: thousands (0.453 is not)
        s = re.sub(r"[,.]", "", s)
    else:
        s = s.replace(",", ".")                            # 45,3: a decimal comma
    try:
        return float(s) * mult
    except ValueError:
        return None


def title_form(title) -> str:
    """The title's first word when it is one of TITLE_FORMS ('Can', 'Why'...), else 'other'."""
    first = re.sub(r"[^a-z']", "", (str(title or "").split() or [""])[0].lower())
    return first.capitalize() if first in TITLE_FORMS else "other"


def duration_bucket(seconds):
    try:
        d = float(seconds)
    except (TypeError, ValueError):
        return None
    if d <= 0:
        return None
    return next((label for limit, label in DURATION_BUCKETS if d < limit), "60 s +")


def median(values):
    vals = sorted(values)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1              # ties share the mean rank
        i = j + 1
    return ranks


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def spearman(xs, ys):
    """Rank correlation: does a higher score go with more views, whatever the
    size of the gap (one viral clip does not decide it)."""
    return pearson(_ranks(xs), _ranks(ys)) if len(xs) >= 3 else None


# --- reading ----------------------------------------------------------------------------

def load_exports(output_dir):
    """Every <clip>_playbook.json under ``output_dir`` (any depth)."""
    out = []
    for path in sorted(glob.glob(os.path.join(output_dir, "**", "*_playbook.json"), recursive=True)):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data["_path"] = path
            out.append(data)
    return out


def _column(header, names):
    normed = {_norm(h): h for h in header}
    return next((normed[n] for n in names if n in normed), None)


def read_views(path):
    """(rows, problem). rows: [{"moment_id", "file", "title", "views", "retention"}]
    (None for what the CSV does not have); problem: why the file cannot be used, or ""."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    first = text.splitlines()[0] if text.strip() else ""
    delimiter = max(",;\t", key=first.count) if first else ","
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    header = reader.fieldnames or []
    cols = {key: _column(header, names) for key, names in _ID_COLUMNS.items()}
    views_col = _column(header, _VIEWS_COLUMNS)
    retention_col = _column(header, _RETENTION_COLUMNS)
    if not views_col:
        return [], f"no views column (looked for: {', '.join(_VIEWS_COLUMNS[:4])}...) in: {', '.join(header)}"
    if not any(cols.values()):
        return [], f"no moment_id, file or title column in: {', '.join(header)}"
    rows = []
    for raw in reader:
        views = parse_number(raw.get(views_col))
        if views is None:
            continue                                        # a "Total" line, an empty line
        rows.append({"moment_id": (raw.get(cols["moment_id"]) or "").strip() if cols["moment_id"] else None,
                     "file": (raw.get(cols["file"]) or "").strip() if cols["file"] else None,
                     "title": (raw.get(cols["title"]) or "").strip() if cols["title"] else None,
                     "views": views,
                     "retention": parse_number(raw.get(retention_col)) if retention_col else None})
    return rows, ""


def join(exports, rows):
    """(clips, unmatched rows). One entry per published clip: its export plus
    ``views`` (summed over its rows) and ``retention`` (their mean). A row is
    matched by moment_id, else file name, else title."""
    by_id = {e.get("moment_id"): e for e in exports if e.get("moment_id")}
    by_file = {file_key(e.get("clip_file")): e for e in exports if e.get("clip_file")}
    by_title = {}
    for e in exports:
        by_title.setdefault(norm_title(e.get("title")), e)
    by_title.pop("", None)

    def _by_title(title):
        # Exact, else one starts with the other: a platform cuts a long title,
        # a publisher appends hashtags.
        t = norm_title(title)
        if not t:
            return None
        if t in by_title:
            return by_title[t]
        return next((e for k, e in by_title.items()
                     if min(len(k), len(t)) >= 12 and (k.startswith(t) or t.startswith(k))), None)

    found, unmatched = {}, []
    for r in rows:
        e = (by_id.get(r["moment_id"]) if r.get("moment_id") else None) \
            or (by_file.get(file_key(r["file"])) if r.get("file") else None) \
            or (_by_title(r["title"]) if r.get("title") else None)
        if e is None:
            unmatched.append(r)
            continue
        slot = found.setdefault(e["_path"], {**e, "views": 0.0, "_retention": []})
        slot["views"] += r["views"]
        if r.get("retention") is not None:
            slot["_retention"].append(r["retention"])
    clips = []
    for slot in found.values():
        ret = slot.pop("_retention")
        slot["retention"] = sum(ret) / len(ret) if ret else None
        clips.append(slot)
    return clips, unmatched


# --- tables -----------------------------------------------------------------------------

def group_stats(clips, key):
    """[{"key", "posts", "median_views", "avg_views", "median_retention"}],
    best median first. ``key(clip)`` -> the group's name, None to leave the
    clip out."""
    groups = {}
    for c in clips:
        k = key(c)
        if k is None:
            continue
        groups.setdefault(str(k), []).append(c)
    out = []
    for k, members in groups.items():
        views = [m["views"] for m in members]
        ret = [m["retention"] for m in members if m.get("retention") is not None]
        out.append({"key": k, "posts": len(members), "median_views": round(median(views)),
                    "avg_views": round(sum(views) / len(views)),
                    "median_retention": round(median(ret), 1) if ret else None})
    return sorted(out, key=lambda g: (-g["median_views"], g["key"]))


def score_correlation(clips, field="score"):
    """How the AI's score tracks the views: Spearman (ranks) and Pearson on
    log(views), over the clips that have a score."""
    pairs = [(float(c[field]), float(c["views"])) for c in clips
             if isinstance(c.get(field), (int, float)) and not isinstance(c.get(field), bool)]
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    rho = spearman(xs, ys)
    r = pearson(xs, [math.log1p(max(0.0, y)) for y in ys])
    return {"n": len(pairs), "spearman": None if rho is None else round(rho, 2),
            "pearson_log_views": None if r is None else round(r, 2)}


GROUPS = (
    ("topic_bucket", "by topic", lambda c: c.get("topic_bucket") or "other"),
    ("duration", "by length", lambda c: duration_bucket(c.get("duration"))),
    ("title_form", "by title shape", lambda c: title_form(c.get("title"))),
    ("hook_aligned", "opens on its hook sentence", lambda c: "yes" if c.get("hook_aligned") else "no"),
    ("hook_clear", "on-screen hook clear on its own",
     lambda c: None if "hook_clear" not in c else ("yes" if c["hook_clear"] else "no")),
    ("off_niche", "outside the niche", lambda c: None if "off_niche" not in c else ("yes" if c["off_niche"] else "no")),
)


def build_report(exports, rows):
    clips, unmatched = join(exports, rows)
    return {
        "clips": len(clips), "exports": len(exports), "rows": len(rows), "unmatched": len(unmatched),
        "unmatched_sample": [r.get("title") or r.get("file") or r.get("moment_id") for r in unmatched[:5]],
        "groups": {name: group_stats(clips, key) for name, _label, key in GROUPS},
        "score_vs_views": score_correlation(clips),
        "posts": sorted(({k: c.get(k) for k in ("moment_id", "clip_file", "title", "topic_bucket", "duration",
                                                  "hook_aligned", "score", "views", "retention")}
                         for c in clips), key=lambda p: -p["views"]),
    }


def _reading(corr) -> str:
    rho, n = corr["spearman"], corr["n"]
    if rho is None:
        return "not enough scored clips to say (3 needed)"
    if n < 15:
        verdict = "too few clips to trust it yet"
    elif rho >= 0.4:
        verdict = "the score tells something: ranking by it is worth it"
    elif rho <= -0.2:
        verdict = "higher scores got FEWER views: do not rank by it"
    else:
        verdict = "the score says little about the views"
    return f"Spearman {rho:+.2f}, Pearson on log(views) {corr['pearson_log_views']:+.2f}, {n} clips — {verdict}"


def format_report(report) -> str:
    lines = [f"{report['clips']} published clip(s) matched ({report['rows']} CSV row(s), "
             f"{report['unmatched']} not matched, {report['exports']} export(s) on disk)."]
    if report["unmatched_sample"]:
        lines.append("  not matched, e.g.: " + " | ".join(str(x)[:50] for x in report["unmatched_sample"]))
    labels = {name: label for name, label, _key in GROUPS}
    for name, rows in report["groups"].items():
        if not rows:
            continue
        lines += ["", f"{labels[name]} (median views · mean · clips{' · median retention' if any(r['median_retention'] is not None for r in rows) else ''})"]
        for r in rows:
            ret = f" · {r['median_retention']:g} %" if r["median_retention"] is not None else ""
            lines.append(f"  {r['key']:<28} {r['median_views']:>9,} · {r['avg_views']:>9,} · {r['posts']:>3}{ret}")
    lines += ["", "predicted_score vs views: " + _reading(report["score_vs_views"])]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Join the playbook exports to a CSV of real views.")
    parser.add_argument("csv", help="views export (YouTube Studio, Upload-Post, or hand-made)")
    parser.add_argument("--output", default="output", help="folder holding the jobs (default: output)")
    parser.add_argument("--json", dest="json_path", help="also write the full report as JSON here")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    exports = load_exports(args.output)
    if not exports:
        print(f"No *_playbook.json under {args.output}: run a job with the Synapse Cut playbook first.")
        return 1
    rows, problem = read_views(args.csv)
    if problem:
        print(f"Cannot use {args.csv}: {problem}")
        return 1
    report = build_report(exports, rows)
    print(format_report(report))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nFull report: {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
