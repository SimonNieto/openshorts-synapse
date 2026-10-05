"""What did the published shorts actually get, and what made them?

Two inputs, standard library only, no AI call:

- **A YouTube Studio export** (Analytics > Advanced mode > Content, Shorts, with "Stayed to watch" and "Engaged
  views" added, Export > CSV — the CSV itself or the ZIP Studio downloads; French or English), or the hand-made
  ``studio.json`` relevé. Each row is joined to the clip the app made (``output/<job>/*_metadata.json``) and to the
  publish plan (``publish_schedule.json``): by the YouTube id when the app knows it, else the title (also the
  titles the clip had before: ``copy_before_stepup``, ``title_before_retitle``, the one sent at publication), else
  the ``moment_id``, else the publication day + the length. The tables put **"Stayed to watch" / « Ont continué de
  regarder »** first (5-oct-2026, output/_stepup/donnees/rapport.md: rank correlation ~0.74 with the views over
  22 shorts, when length, % viewed or likes say almost nothing) and group it by what the app knows of each clip:
  length, title shape, topic, ``moment_nature``, opening image.
- **Legacy**: a CSV of views with a ``moment_id`` / file / title column, joined to the ``*_playbook.json``
  exports (``build_report``), as before.

    python stats_ingest.py "Table data.csv"                  # Studio export: tables, stayed first
    python stats_ingest.py export.zip --json stats.json      # the ZIP Studio downloads works too
    python stats_ingest.py ab "Table data.csv"               # the opening-image A/B test (decision 8)
    python stats_ingest.py mark-opening b8e46c24 1,3,8       # record an opening image posed by hand
    python stats_ingest.py views.csv                         # legacy views CSV + playbook exports

app.py's /api/plus/stats serves the same tables to the dashboard (the export is imported there, or dropped in
``stats/``) next to Upload-Post's live views.
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import itertools
import json
import math
import os
import random
import re
import sys
import unicodedata
import zipfile
from datetime import date, datetime, timedelta

# The title shapes the playbook asks for (playbook.TITLE_OPENERS) and the ones
# it forbids; anything else is "other".
TITLE_FORMS = ("can", "is", "does", "are", "do", "will", "should", "why", "how", "what")
DURATION_BUCKETS = ((20, "< 20 s"), (30, "20-30 s"), (40, "30-40 s"), (50, "40-50 s"), (60, "50-60 s"))

# Where the dashboard saves the Studio exports it is given (relative to the app's folder, like
# publish_schedule.json); /api/plus/stats reads the newest one. Git-ignored: it is the channel's own data.
STUDIO_DIR = "stats"
STUDIO_EXTENSIONS = (".csv", ".tsv", ".zip", ".json")
# A group with fewer shorts than this is shown but flagged "too few": one short decides its median.
MIN_GROUP = 3
# The publication-day + length fallback (a title changed in Studio after publication, e.g. Meth/Adderall,
# 29-sep): Studio's length minus the clip's (end - start) was between 0 and +1.1 s on the 12 shorts linked by
# title (5-oct-2026), so a candidate must fall inside this window — and be the only one that day.
DURATION_SLACK = (-0.75, 1.75)
# The opening image (decision 8): a full-screen drawn picture over the first 1.2 s. The recipe records it on the
# clip as ``clip["opening_image"]`` (truthy: a dict {"dur", "how", ...} or True); ``mark-opening`` writes the same
# field for an opening posed by hand. The A/B test of 5-8 oct 2026 was posed by hand on 4-oct (poser.sh, before
# the field existed): its six clips are recorded here so the stats know them without rewriting the job.
OPENING_SECONDS = 1.2
AB_OPENING_TEST = {"job": "b8e46c24", "clips": (1, 3, 8, 10, 11, 12),
                   "published": ("2026-10-05", "2026-10-08"), "control": "the 6 other clips of the same job"}
# The A/B verdict: a gap is only called a signal when both groups have this many shorts and the permutation
# test gives less than AB_SIGNAL_P (never "proven" on a dozen shorts).
AB_MIN_EACH = 3
AB_SIGNAL_P = 0.10
# Stayed-to-watch settles in the first two days (the test pool, rapport C1): younger shorts are flagged.
YOUNG_DAYS = 2

_ID_COLUMNS = {
    "moment_id": ("moment_id", "moment id", "moment"),
    "file": ("file", "fichier", "filename", "file name", "file_name", "clip_file", "clip file", "clip",
             "video_file", "video file"),
    "title": ("title", "titre", "video title", "titre de la video", "post_title", "post title", "caption"),
}
_VIEWS_COLUMNS = ("views", "vues", "view_count", "view count", "views_count", "nombre de vues", "plays")
_RETENTION_COLUMNS = ("retention", "average percentage viewed (%)", "average percentage viewed",
                      "pourcentage moyen de visionnage (%)", "pourcentage moyen de visionnage",
                      "pourcentage moyen regarde (%)", "pourcentage moyen regarde", "% moyen regarde",
                      "avg_view_percentage", "average view percentage", "retention (%)", "avp")
# Studio's columns, English and French (compared without accents, case, nor a trailing "(%)"), in the order
# they claim a column: an earlier key keeps a column a later one would also match.
_STUDIO_COLUMNS = (
    ("video_id", ("content", "contenu", "video id", "video_id", "id de la video", "id video",
                  "identifiant de la video", "youtube id", "youtube_id", "id"), ()),
    ("moment_id", _ID_COLUMNS["moment_id"], ()),
    ("file", _ID_COLUMNS["file"], ()),
    ("title", ("video title", "titre de la video") + _ID_COLUMNS["title"], ()),
    ("published", ("video publish time", "heure de publication de la video", "date de publication de la video",
                   "publish time", "publish date", "published", "published at", "date de publication",
                   "publication", "pub", "date"), ("publish time", "publication")),
    ("duration", ("duration", "duree", "duree de la video", "video duration", "length", "dur"), ()),
    ("views", _VIEWS_COLUMNS, ()),
    ("engaged_views", ("engaged views", "vues engagees"), ("engaged view", "vues engagee")),
    ("avg_view_duration", ("average view duration", "duree moyenne de visionnage", "duree moyenne de vue",
                           "duree moyenne regardee", "avd"), ("average view duration", "duree moyenne")),
    ("avg_pct_viewed", _RETENTION_COLUMNS, ("average percentage viewed", "pourcentage moyen")),
    ("stayed", ("stayed to watch", "ont continue de regarder", "viewed (vs. swiped away)",
                "viewed vs. swiped away", "viewed (vs swiped away)", "viewed vs swiped away",
                "regardees (vs balayees)", "vues (vs balayages)", "stayed", "restent"),
     ("stayed to watch", "continue de regarder", "continue a regarder", "viewed (vs", "viewed vs")),
)
_TOTAL_WORDS = {"total", "totaux", "total general", "totals"}


def _norm(text) -> str:
    """Lower case, no accents, single spaces: how column names are compared."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.replace("﻿", "")).strip().lower()


def _hnorm(text) -> str:
    """A column name as compared: _norm, without a unit at the end ('(%)', '%', '(s)')."""
    s = _norm(text)
    s = re.sub(r"\s*\((?:%|s|sec|secondes|seconds)\)$", "", s)
    return re.sub(r"\s*%$", "", s).strip()


def norm_title(title) -> str:
    """A title as a join key: letters and digits only, hashtags dropped (emojis, case, punctuation and the
    ``#joerogan #jre`` tail differ between what was sent and what the platform shows)."""
    text = re.sub(r"#\w+", " ", str(title or ""))
    return re.sub(r"[^a-z0-9]+", " ", _norm(text)).strip()


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
    """'7,100' / '7 100' / '7 646' / '7.1K' / '45,3 %' -> a float, None when it is not a number."""
    s = str(value if value is not None else "")
    for space in ("\xa0", " ", " "):                 # French thousands: (narrow) no-break spaces
        s = s.replace(space, " ")
    s = s.strip().rstrip("%").strip()
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


def parse_duration(value):
    """'0:52' / '1:01:02' / '52' / '52 s' / '45,5' -> seconds (float), None when it is not a length."""
    s = _norm(value).replace(" ", "")
    if not s:
        return None
    if re.fullmatch(r"\d+(:\d{1,2}){1,2}(\.\d+)?", s):
        total = 0.0
        for part in s.split(":"):
            total = total * 60 + float(part)
        return total
    s = re.sub(r"(s|sec|secondes|seconds)$", "", s)
    return parse_number(s)


_MONTHS = {
    "jan": 1, "janv": 1, "janvier": 1, "january": 1, "feb": 2, "fev": 2, "fevr": 2, "fevrier": 2, "february": 2,
    "mar": 3, "mars": 3, "march": 3, "apr": 4, "avr": 4, "avril": 4, "april": 4, "may": 5, "mai": 5,
    "jun": 6, "juin": 6, "june": 6, "jul": 7, "juil": 7, "juillet": 7, "july": 7, "aug": 8, "aout": 8,
    "august": 8, "sep": 9, "sept": 9, "septembre": 9, "september": 9, "oct": 10, "octobre": 10, "october": 10,
    "nov": 11, "novembre": 11, "november": 11, "dec": 12, "decembre": 12, "december": 12,
}


def parse_date(value):
    """'Sep 28, 2026' / '28 sept. 2026' / '2026-09-28' / '28/09/2026' -> '2026-09-28', None otherwise."""
    s = _norm(value)
    if not s:
        return None

    def iso(y, m, d):
        try:
            return date(int(y), int(m), int(d)).isoformat()
        except ValueError:
            return None

    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return iso(*m.groups())
    m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
        return iso(y, a, b) if b > 12 else iso(y, b, a)        # 9/28/2026 (US) or 28/09/2026 (FR)
    words = re.findall(r"[a-z]+|\d+", s)
    month = next((_MONTHS[w] for w in words if w in _MONTHS), None)
    year = next((w for w in words if re.fullmatch(r"\d{4}", w)), None)
    day = next((w for w in words if re.fullmatch(r"\d{1,2}", w) and 1 <= int(w) <= 31), None)
    return iso(year, month, day) if month and year and day else None


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


def _mean(values):
    return sum(values) / len(values) if values else None


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


def permutation_p(a, b, limit=20000, seed=7):
    """Two-sided permutation test on the difference of means: the share of the ways to split the pooled values
    into groups of these sizes whose gap is at least the observed one. Exact (every split) up to ``limit``
    splits (6 vs 6 = 924), else ``limit`` random splits with a fixed seed. None when a group is empty."""
    if not a or not b:
        return None
    pooled = list(a) + list(b)
    n, total = len(a), sum(pooled)
    observed = abs(_mean(a) - _mean(b))
    if math.comb(len(pooled), n) <= limit:
        splits = itertools.combinations(range(len(pooled)), n)
    else:
        rng = random.Random(seed)
        splits = (rng.sample(range(len(pooled)), n) for _ in range(limit))
    hits = count = 0
    for idx in splits:
        sa = sum(pooled[i] for i in idx)
        gap = abs(sa / n - (total - sa) / (len(pooled) - n))
        hits += gap >= observed - 1e-9
        count += 1
    return hits / count


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


def _resolve_columns(header):
    """{key: the CSV's column name or None} for every _STUDIO_COLUMNS key; one column per key."""
    normed = {}
    for h in header:
        normed.setdefault(_hnorm(h), h)
    cols, used = {}, set()
    for key, names, contains in _STUDIO_COLUMNS:
        found = next((normed[_hnorm(n)] for n in names if _hnorm(n) in normed and normed[_hnorm(n)] not in used),
                     None)
        if found is None:
            found = next((h for part in contains for k, h in normed.items() if part in k and h not in used), None)
        cols[key] = found
        if found is not None:
            used.add(found)
    return cols


def _read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    return _decode(raw)


def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _zip_table(path):
    """(text, problem): the table CSV inside the ZIP YouTube Studio downloads ("Table data.csv" /
    "Données du tableau.csv"; "Chart data" and "Totals" are left aside)."""
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith((".csv", ".tsv")) and not n.startswith("__MACOSX")]
            if not names:
                return "", "no CSV inside this ZIP"
            ranked = sorted(names, key=lambda n: (not re.search(r"table", _norm(os.path.basename(n))),
                                                  bool(re.search(r"chart|graph|total", _norm(os.path.basename(n)))),
                                                  -z.getinfo(n).file_size))
            return _decode(z.read(ranked[0])), ""
    except zipfile.BadZipFile:
        return "", "not a readable ZIP file"


def parse_table(text):
    """(rows, problem) from a CSV text: see read_views."""
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(",;\t", key=first.count) if first else ","
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    header = reader.fieldnames or []
    cols = _resolve_columns(header)
    if not cols["views"] and not cols["stayed"]:
        return [], (f"no views column (looked for: {', '.join(_VIEWS_COLUMNS[:4])}..., or Stayed to watch) "
                    f"in: {', '.join(header)}")
    if not any(cols[k] for k in ("video_id", "moment_id", "file", "title")):
        return [], f"no video id (Content), moment_id, file or title column in: {', '.join(header)}"
    rows = []
    for raw in reader:
        def get(key):
            col = cols[key]
            value = (raw.get(col) or "").strip() if col else ""
            return value or None
        label = get("video_id") or get("title") or get("moment_id") or get("file") or ""
        if _norm(label) in _TOTAL_WORDS:
            continue                                        # Studio's "Total" line
        views = parse_number(get("views"))
        stayed = parse_number(get("stayed"))
        if views is None and stayed is None:
            continue                                        # an empty line
        avg_pct = parse_number(get("avg_pct_viewed"))
        rows.append({"video_id": get("video_id"), "moment_id": get("moment_id"), "file": get("file"),
                     "title": get("title"), "published": parse_date(get("published")),
                     "duration": parse_duration(get("duration")), "views": views,
                     "engaged_views": parse_number(get("engaged_views")),
                     "avg_view_duration": parse_duration(get("avg_view_duration")),
                     "avg_pct_viewed": avg_pct, "stayed": stayed,
                     "retention": avg_pct})                 # the legacy name of avg_pct_viewed
    return rows, ""


def read_studio_json(path):
    """(rows, problem) from the hand-made relevé (output/_stepup/studio/studio.json: {"shorts": [{"id", "title",
    "pub", "dur", "views", "stayed", "avd", "avp"}]}) or a plain list of such objects."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return [], f"not a readable JSON file ({e})"
    items = data.get("shorts") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return [], "no 'shorts' list in this JSON"
    rows = []
    for s in items:
        if not isinstance(s, dict):
            continue
        avg_pct = parse_number(s.get("avp", s.get("avg_pct_viewed")))
        rows.append({"video_id": s.get("id") or s.get("video_id"), "moment_id": s.get("moment_id"),
                     "file": s.get("file"), "title": s.get("title"),
                     "published": parse_date(s.get("pub") or s.get("published")),
                     "duration": parse_duration(s.get("dur", s.get("duration"))),
                     "views": parse_number(s.get("views")), "engaged_views": parse_number(s.get("engaged_views")),
                     "avg_view_duration": parse_duration(s.get("avd", s.get("avg_view_duration"))),
                     "avg_pct_viewed": avg_pct, "stayed": parse_number(s.get("stayed")), "retention": avg_pct})
    return rows, ""


def read_views(path):
    """(rows, problem). One row per video: {"video_id", "moment_id", "file", "title", "published" (ISO day),
    "duration" (s), "views", "engaged_views", "avg_view_duration" (s), "avg_pct_viewed", "stayed",
    "retention" (= avg_pct_viewed)} — None for what the file does not have; problem: why the file cannot be
    used, or "". Reads a CSV (YouTube Studio's in French or English, Upload-Post's, or hand-made; ``,`` ``;`` or
    tab), the ZIP Studio downloads, or a studio.json relevé. Studio's "Total" line is left out."""
    ext = os.path.splitext(str(path))[1].lower()
    if ext == ".json":
        return read_studio_json(path)
    if ext == ".zip":
        text, problem = _zip_table(path)
        if problem:
            return [], problem
    else:
        text = _read_text(path)
    return parse_table(text)


def _exports(folder):
    try:
        names = [n for n in os.listdir(folder)
                 if n.lower().endswith(STUDIO_EXTENSIONS) and not n.startswith((".", "~"))]
    except OSError:
        return []
    paths = [os.path.join(folder, n) for n in names if os.path.isfile(os.path.join(folder, n))]
    return sorted(paths, key=os.path.getmtime, reverse=True)


def latest_export(folder=STUDIO_DIR):
    """The newest Studio export in ``folder`` (CSV, ZIP or JSON), None when there is none."""
    paths = _exports(folder)
    return paths[0] if paths else None


def read_latest_export(folder=STUDIO_DIR):
    """(path, rows, problem) for the newest export in ``folder`` that reads — the "Chart data" or "Totals" CSV
    dropped next to the table one is passed over. (None, [], "") when there is no export; the newest file and
    its problem when none reads."""
    paths = _exports(folder)
    first = None
    for path in paths:
        rows, problem = read_views(path)
        if not problem and rows:
            return path, rows, ""
        first = first or (path, [], problem or "no video in it")
    return first or (None, [], "")


# --- the clips the app made -------------------------------------------------------------

_YT_URL = re.compile(r"(?:youtube\.com/(?:shorts/|watch\?(?:[^#\s]*&)?v=|embed/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")
_YT_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def youtube_id(value, platform=None, _depth=0) -> str:
    """The 11-character YouTube video id in an Upload-Post answer (a post-analytics row, an upload or status
    result): a YouTube URL anywhere in it, or a ``platform_post_id`` / ``video_id`` field on a YouTube entry.
    "" when there is none — never a guess."""
    if isinstance(value, str):
        m = _YT_URL.search(value)
        return m.group(1) if m else ""
    if _depth > 4:
        return ""
    if isinstance(value, list):
        return next((y for y in (youtube_id(v, platform, _depth + 1) for v in value) if y), "")
    if not isinstance(value, dict):
        return ""
    plat = str(value.get("platform") or platform or "").lower()
    for key in ("post_url", "url", "share_url", "permalink", "link", "video_url"):
        found = youtube_id(value.get(key)) if isinstance(value.get(key), str) else ""
        if found:
            return found
    if plat == "youtube":
        for key in ("platform_post_id", "youtube_id", "video_id", "post_id"):
            v = value.get(key)
            if isinstance(v, str) and _YT_ID.fullmatch(v.strip()):
                return v.strip()
    for key, v in value.items():
        if isinstance(v, (dict, list)):
            found = youtube_id(v, "youtube" if str(key).lower() == "youtube" else plat, _depth + 1)
            if found:
                return found
    return ""


def opening_image(clip, openings=None, job_id="", index=None) -> bool:
    """Does the clip open on a drawn picture (decision 8)? ``clip["opening_image"]`` (what the recipe and
    ``mark-opening`` write), a B-roll picture already on screen at the first frame (t <= 0.1 s, or one marked
    as the opening), or — for the clips posed by hand before the field existed — ``openings``
    ({job id prefix: clip numbers}, AB_OPENING_TEST by default)."""
    if (clip or {}).get("opening_image"):
        return True
    for item in (clip or {}).get("broll") or []:
        if not isinstance(item, dict):
            continue
        if item.get("opening") or "opening" in (item.get("role"), item.get("kind"), item.get("layout")):
            return True
        try:
            if float(item.get("t")) <= 0.1:
                return True
        except (TypeError, ValueError):
            pass
    if index is not None and job_id:
        table = openings if openings is not None else {AB_OPENING_TEST["job"]: AB_OPENING_TEST["clips"]}
        return any(job_id.startswith(prefix) and index + 1 in tuple(numbers) for prefix, numbers in table.items())
    return False


def _clip_duration(short, export):
    segments = ((short.get("recipe") or {}).get("segments")) or []
    try:
        if segments:
            return round(sum(float(s["end"]) - float(s["start"]) for s in segments), 2)
        if short.get("end") is not None and short.get("start") is not None:
            return round(float(short["end"]) - float(short["start"]), 2) or None
    except (KeyError, TypeError, ValueError):
        pass
    return export.get("duration")


def _clip_record(job_id, index, short, export, entries, local, openings):
    titles = []

    def add(title):
        title = (title or "").strip()
        if title and title not in titles:
            titles.append(title)

    add(short.get("video_title_for_youtube_short") or export.get("title"))
    for e in entries:
        add(e.get("title"))                                  # what was sent at publication
    add((short.get("copy_before_stepup") or {}).get("title"))
    add((short.get("title_check") or {}).get("before"))
    add(export.get("title_before_retitle"))
    published = short.get("published") if isinstance(short.get("published"), dict) else {}
    days, yt_ids = set(), set()
    for e in entries:
        if e.get("platform") in (None, "", "youtube"):
            if e.get("date"):
                days.add(str(e["date"])[:10])
            if e.get("youtube_id"):
                yt_ids.add(str(e["youtube_id"]))
    if published.get("scheduled_for"):
        days.add(str(published["scheduled_for"])[:10])
    elif published.get("at") and not days:
        try:
            days.add(datetime.fromtimestamp(float(published["at"])).date().isoformat())
        except (TypeError, ValueError, OSError):
            pass
    if published.get("youtube_id"):
        yt_ids.add(str(published["youtube_id"]))
    clip_file = export.get("clip_file") or os.path.basename(str(short.get("video_url") or ""))
    hook_aligned = short.get("hook_aligned", export.get("hook_aligned"))
    return {
        "job_id": job_id, "clip_index": index, "ref": f"{job_id[:8]}_c{index + 1:02d}", "local": local,
        "moment_id": short.get("moment_id") or export.get("moment_id"), "clip_file": clip_file,
        "title": titles[0] if titles else "", "titles": titles,
        "duration": _clip_duration(short, export) if local else None,
        "days": sorted(days), "youtube_ids": sorted(yt_ids),
        "topic_bucket": short.get("topic_bucket") or export.get("topic_bucket"),
        "moment_nature": short.get("moment_nature") or export.get("moment_nature"),
        "hook_aligned": None if hook_aligned is None else bool(hook_aligned),
        "opening_image": opening_image(short, openings, job_id, index) if local else None,
        "score": short.get("predicted_score", export.get("score")),
    }


def load_clips(output_dir, schedule=None, openings=None):
    """Every clip the app made that is still on disk (``output/<job>/*_metadata.json``, its ``shorts``, plus
    the ``*_playbook.json`` export when there is one), and the publish-plan entries whose project is gone
    (``local`` False: their titles and days are known, not what made them). One dict per clip:
    job_id, clip_index, ref ('b8e46c24_c03'), local, moment_id, clip_file, title, titles (every title it had),
    duration, days (YouTube publication days), youtube_ids, topic_bucket, moment_nature, hook_aligned,
    opening_image, score."""
    by_clip = {}
    for e in schedule or []:
        if isinstance(e, dict) and e.get("job_id") is not None and e.get("clip_index") is not None:
            by_clip.setdefault((str(e["job_id"]), int(e["clip_index"])), []).append(e)
    clips, seen = [], set()
    for meta_path in sorted(glob.glob(os.path.join(output_dir, "*", "*_metadata.json"))):
        job_dir = os.path.dirname(meta_path)
        job_id = os.path.basename(job_dir)
        try:
            with open(meta_path, encoding="utf-8") as f:
                shorts = json.load(f).get("shorts") or []
        except (OSError, ValueError, AttributeError):
            continue
        exports = {}
        for path in glob.glob(os.path.join(glob.escape(job_dir), "*_playbook.json")):
            m = re.search(r"_clip_(\d+)_playbook\.json$", path)
            if not m:
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    exports[int(m.group(1))] = json.load(f)
            except (OSError, ValueError):
                pass
        for i, short in enumerate(shorts):
            if isinstance(short, dict) and (job_id, i) not in seen:
                clips.append(_clip_record(job_id, i, short, exports.get(i + 1) or {}, by_clip.get((job_id, i), []),
                                          True, openings))
                seen.add((job_id, i))
    for (job_id, i), entries in sorted(by_clip.items()):
        if (job_id, i) not in seen:
            clips.append(_clip_record(job_id, i, {}, {}, entries, False, openings))
    return clips


def mark_opening(output_dir, job, numbers, seconds=OPENING_SECONDS, how="manual"):
    """Write ``opening_image`` on clips 'cNN' of one job (``job``: its id or a prefix): the record of an opening
    picture posed by hand. The metadata file keeps its mtime (it is the project's date). -> the refs marked."""
    paths = sorted(glob.glob(os.path.join(output_dir, f"{job}*", "*_metadata.json")))
    jobs = {os.path.dirname(p) for p in paths}
    if len(jobs) != 1:
        raise ValueError(f"{len(jobs)} job folders match '{job}' under {output_dir}")
    path = paths[0]
    st = os.stat(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    shorts = data.get("shorts") or []
    marked = []
    for n in numbers:
        if not 1 <= int(n) <= len(shorts):
            raise ValueError(f"clip c{int(n):02d} does not exist (the job has {len(shorts)} clips)")
        shorts[int(n) - 1]["opening_image"] = {"dur": seconds, "how": how, "marked": date.today().isoformat()}
        marked.append(f"{os.path.basename(os.path.dirname(path))[:8]}_c{int(n):02d}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    try:
        os.utime(path, (st.st_atime, st.st_mtime))
    except OSError:
        pass
    return marked


# --- the Studio join --------------------------------------------------------------------

def _day_shift(day, n):
    try:
        return (date.fromisoformat(day) + timedelta(days=n)).isoformat()
    except (TypeError, ValueError):
        return None


def _title_matches(row_title, clip):
    """2 for an exact title (any of the clip's titles), 1 when one starts with the other (a platform cuts a
    long title, a publisher appends hashtags), 0 otherwise."""
    t = norm_title(row_title)
    if not t:
        return 0
    best = 0
    for title in clip["titles"]:
        k = norm_title(title)
        if not k:
            continue
        if k == t:
            return 2
        if min(len(k), len(t)) >= 12 and (k.startswith(t) or t.startswith(k)):
            best = 1
    return best


def link_studio(rows, clips):
    """[(row, clip or None, how)] in the rows' order. how: "youtube_id", "moment_id", "file", "title" or
    "date+duration" (weakest: the publication day ±1 and the length, only when a single clip fits). The strong
    keys go first over every row, so a weaker one never takes a clip a stronger one points to."""
    slots = [[r, None, ""] for r in rows]
    by_yt, by_moment, by_file = {}, {}, {}
    for c in clips:
        for y in c["youtube_ids"]:
            by_yt.setdefault(y, c)
        if c.get("moment_id"):
            by_moment.setdefault(c["moment_id"], c)
        if c.get("clip_file"):
            by_file.setdefault(file_key(c["clip_file"]), c)
    taken = set()

    def key(c):
        return c["job_id"], c["clip_index"]

    for slot in slots:
        r = slot[0]
        for how, table, value in (("youtube_id", by_yt, r.get("video_id")),
                                  ("moment_id", by_moment, r.get("moment_id")),
                                  ("file", by_file, file_key(r["file"]) if r.get("file") else None)):
            if value and value in table:
                slot[1], slot[2] = table[value], how
                taken.add(key(table[value]))
                break
    for slot in slots:
        r = slot[0]
        if slot[1] is not None or not r.get("title"):
            continue
        # A clip already linked is taken again only on its exact title (the same short uploaded twice).
        scored = [(s, c) for c in clips for s in (_title_matches(r["title"], c),)
                  if s == 2 or (s and key(c) not in taken)]
        if not scored:
            continue
        day = r.get("published")
        near = {day, _day_shift(day, -1), _day_shift(day, 1)} if day else set()
        scored.sort(key=lambda sc: (key(sc[1]) in taken, -sc[0], not (near & set(sc[1]["days"])),
                                    not sc[1]["local"]))
        slot[1], slot[2] = scored[0][1], "title"
        taken.add(key(scored[0][1]))
    for slot in slots:
        r = slot[0]
        if slot[1] is not None or not r.get("published") or r.get("duration") is None:
            continue
        for days in ({r["published"]}, {_day_shift(r["published"], -1), _day_shift(r["published"], 1)}):
            fits = [c for c in clips if key(c) not in taken and c.get("duration") and days & set(c["days"])
                    and DURATION_SLACK[0] <= r["duration"] - c["duration"] <= DURATION_SLACK[1]]
            if len(fits) == 1:
                slot[1], slot[2] = fits[0], "date+duration"
                taken.add(key(fits[0]))
            if fits:
                break                                       # several fit: say nothing rather than guess
    return [tuple(s) for s in slots]


def studio_posts(rows, clips, as_of=None):
    """One dict per Studio row: its numbers + what the app knows of its clip (None when not linked)."""
    as_of = as_of or date.today()
    posts = []
    for r, c, how in link_studio(rows, clips):
        c = c or {}
        title = r.get("title") or c.get("title") or ""
        try:
            age = (as_of - date.fromisoformat(r["published"])).days if r.get("published") else None
        except ValueError:
            age = None
        posts.append({
            "video_id": r.get("video_id"), "title": title, "published": r.get("published"), "age_days": age,
            "duration": r["duration"] if r.get("duration") is not None else c.get("duration"),
            "views": r.get("views"), "engaged_views": r.get("engaged_views"),
            "avg_view_duration": r.get("avg_view_duration"), "avg_pct_viewed": r.get("avg_pct_viewed"),
            "stayed": r.get("stayed"),
            "linked": ("clip" if c.get("local") else "plan") if c else "", "how": how,
            "ref": c.get("ref"), "job_id": c.get("job_id"), "clip_index": c.get("clip_index"),
            "topic_bucket": c.get("topic_bucket"), "moment_nature": c.get("moment_nature"),
            "opening_image": c.get("opening_image"), "hook_aligned": c.get("hook_aligned"),
            "score": c.get("score"), "title_form": title_form(title) if title else None,
        })
    posts.sort(key=lambda p: (p["stayed"] is None, -(p["stayed"] or 0), -(p["views"] or 0)))
    return posts


def _yes_no(value):
    return None if value is None else ("yes" if value else "no")


# (name, French label for the CLI, English label, key(post) -> group or None to leave the post out).
STUDIO_GROUPS = (
    ("opening_image", "image dessinée d'ouverture", "opening image", lambda p: _yes_no(p.get("opening_image"))),
    ("duration", "durée", "length", lambda p: duration_bucket(p.get("duration"))),
    ("title_form", "forme du titre", "title shape", lambda p: p.get("title_form")),
    ("topic_bucket", "sujet", "topic", lambda p: p.get("topic_bucket")),
    ("moment_nature", "nature du moment", "moment nature", lambda p: p.get("moment_nature")),
    ("hook_aligned", "ouvre sur sa phrase-hook", "opens on its hook sentence",
     lambda p: _yes_no(p.get("hook_aligned"))),
)


def studio_group_stats(posts, key):
    """[{"key", "n", "n_stayed", "stayed_median", "stayed_mean", "views_median", "engaged_median",
    "avg_pct_median", "few"}], the best median "stayed" first (groups without it last)."""
    groups = {}
    for p in posts:
        k = key(p)
        if k is not None:
            groups.setdefault(str(k), []).append(p)
    out = []
    for k, members in groups.items():
        def values(field):
            return [m[field] for m in members if m.get(field) is not None]
        stayed, views, engaged, avp = values("stayed"), values("views"), values("engaged_views"), values("avg_pct_viewed")
        out.append({"key": k, "n": len(members), "n_stayed": len(stayed),
                    "stayed_median": round(median(stayed), 1) if stayed else None,
                    "stayed_mean": round(_mean(stayed), 1) if stayed else None,
                    "views_median": round(median(views)) if views else None,
                    "engaged_median": round(median(engaged)) if engaged else None,
                    "avg_pct_median": round(median(avp), 1) if avp else None,
                    "few": len(stayed) < MIN_GROUP})
    return sorted(out, key=lambda g: (g["stayed_median"] is None, -(g["stayed_median"] or 0), -g["n"], g["key"]))


def _correlation(posts, x_field, y_field="views"):
    pairs = [(float(p[x_field]), float(p[y_field])) for p in posts
             if isinstance(p.get(x_field), (int, float)) and not isinstance(p.get(x_field), bool)
             and isinstance(p.get(y_field), (int, float))]
    rho = spearman([a for a, _ in pairs], [b for _, b in pairs])
    return {"n": len(pairs), "spearman": None if rho is None else round(rho, 2)}


def ab_opening(posts, clips=(), same_jobs=True):
    """The opening-image A/B test: "Stayed to watch" of the shorts that open on a drawn picture against those
    that do not — by default only the latter from the same job(s) (the test's control: same episode, same
    week; older shorts differ in too many ways). Honest about its size: a permutation p-value, a verdict code
    ("no_data", "too_few", "chance", "signal") and the test clips that have no number yet."""
    with_ = [p for p in posts if p.get("opening_image") is True and p.get("stayed") is not None]
    jobs = {p["job_id"] for p in with_} | {c["job_id"] for c in clips if c.get("opening_image")}
    without = [p for p in posts if p.get("opening_image") is False and p.get("stayed") is not None
               and (not same_jobs or not jobs or p["job_id"] in jobs)]
    seen = {p.get("ref") for p in posts if p.get("stayed") is not None}
    pending = sorted(c["ref"] for c in clips if c.get("opening_image") and c["ref"] not in seen)

    def side(group):
        stayed = [p["stayed"] for p in group]
        views = [p["views"] for p in group if p.get("views") is not None]
        return {"n": len(group), "refs": [p.get("ref") for p in group],
                "stayed_median": round(median(stayed), 1) if stayed else None,
                "stayed_mean": round(_mean(stayed), 1) if stayed else None,
                "views_median": round(median(views)) if views else None,
                "young": sum(1 for p in group if p.get("age_days") is not None and p["age_days"] < YOUNG_DAYS)}

    a, b = side(with_), side(without)
    gap = round(a["stayed_mean"] - b["stayed_mean"], 1) if a["n"] and b["n"] else None
    p_value = permutation_p([p["stayed"] for p in with_], [p["stayed"] for p in without])
    if not a["n"] or not b["n"]:
        verdict = "no_data"
    elif min(a["n"], b["n"]) < AB_MIN_EACH:
        verdict = "too_few"
    elif p_value is not None and p_value < AB_SIGNAL_P:
        verdict = "signal"
    else:
        verdict = "chance"
    return {"with": a, "without": b, "gap": gap, "p_value": None if p_value is None else round(p_value, 3),
            "verdict": verdict, "pending": pending, "same_jobs": same_jobs,
            "control": "same job" if same_jobs and jobs else "all"}


def build_studio_report(rows, clips, as_of=None):
    posts = studio_posts(rows, clips, as_of)
    hows = {}
    for p in posts:
        if p["how"]:
            hows[p["how"]] = hows.get(p["how"], 0) + 1
    return {
        "rows": len(posts),
        "linked_clip": sum(1 for p in posts if p["linked"] == "clip"),
        "linked_plan": sum(1 for p in posts if p["linked"] == "plan"),
        "unlinked": sum(1 for p in posts if not p["linked"]),
        "how": hows,
        "with_stayed": sum(1 for p in posts if p["stayed"] is not None),
        "as_of": (as_of or date.today()).isoformat(),
        "stayed_vs_views": _correlation(posts, "stayed"),
        "avg_pct_vs_views": _correlation(posts, "avg_pct_viewed"),
        "score_vs_stayed": _correlation(posts, "score", "stayed"),
        "groups": {name: studio_group_stats(posts, key) for name, _fr, _en, key in STUDIO_GROUPS},
        "ab_opening": ab_opening(posts, clips),
        "posts": posts,
    }


# --- the legacy views CSV + playbook exports --------------------------------------------

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
        slot["views"] += r.get("views") or 0.0
        if r.get("retention") is not None:
            slot["_retention"].append(r["retention"])
    clips = []
    for slot in found.values():
        ret = slot.pop("_retention")
        slot["retention"] = sum(ret) / len(ret) if ret else None
        clips.append(slot)
    return clips, unmatched


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


# --- the Studio report, in French (the CLI is read by the channel's owner) --------------

def _fr(value, digits=1, unit=""):
    if value is None:
        return "—"
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text + unit


_HOW_FR = {"youtube_id": "par l'identifiant YouTube", "moment_id": "par le moment_id", "file": "par le fichier",
           "title": "par le titre", "date+duration": "par la date + la durée"}


def format_studio_report(report, top=None) -> str:
    hows = ", ".join(f"{n} {_HOW_FR.get(h, h)}" for h, n in sorted(report["how"].items(), key=lambda x: -x[1]))
    lines = [f"YouTube Studio : {report['rows']} shorts dans l'export ({report['with_stayed']} avec « Ont continué "
             f"de regarder »), relevé du {report['as_of']}.",
             f"  {report['linked_clip']:>3} reliés à un clip de l'appli encore sur le disque",
             f"  {report['linked_plan']:>3} reconnus dans le plan de publication (projet effacé du disque)",
             f"  {report['unlinked']:>3} non reliés (publiés avant le plan de publication, ou à la main)"]
    if hows:
        lines.append(f"  liens : {hows}")
    corr = report["stayed_vs_views"]
    if corr["spearman"] is not None:
        avp = report["avg_pct_vs_views"]
        lines += ["", f"« Ont continué de regarder » suit les vues : corrélation de rang {_fr(corr['spearman'], 2)} "
                      f"sur {corr['n']} shorts (% moyen regardé : {_fr(avp['spearman'], 2)})."]
    lines += ["", "Shorts triés par « Ont continué de regarder »",
              f"  {'restent':>8} {'vues':>7} {'engagées':>8} {'% regardé':>9} {'durée':>6}  {'clip':<20} titre"]
    for p in report["posts"][:top] if top else report["posts"]:
        ref = (p["ref"] or "") + (" (plan)" if p["linked"] == "plan" else "")
        if p["how"] == "date+duration":
            ref += " ?"
        lines.append(f"  {_fr(p['stayed'], 1, ' %'):>8} {_fr(p['views'], 0):>7} {_fr(p['engaged_views'], 0):>8} "
                     f"{_fr(p['avg_pct_viewed'], 1, ' %'):>9} {_fr(p['duration'], 0, ' s'):>6}  {ref:<20} "
                     f"{(p['title'] or '')[:56]}")
    if any(p["how"] == "date+duration" for p in report["posts"]):
        lines.append("  ? = relié par la date de publication et la durée (titre changé dans Studio) : à vérifier.")
    lines.append("  (plan) = reconnu dans le plan de publication, projet effacé : ses caractéristiques sont perdues.")
    empty = [fr for name, fr, _en, _key in STUDIO_GROUPS if not report["groups"].get(name)]
    for name, fr, _en, _key in STUDIO_GROUPS:
        rows = report["groups"].get(name) or []
        if not rows:
            continue
        lines += ["", f"Par {fr} (médiane « restent » · shorts · médiane vues · médiane % regardé)"]
        for g in rows:
            few = "   trop peu pour conclure" if g["few"] else ""
            lines.append(f"  {g['key']:<20} {_fr(g['stayed_median'], 1, ' %'):>8} · {g['n']:>3} · "
                         f"{_fr(g['views_median'], 0):>7} · {_fr(g['avg_pct_median'], 1, ' %'):>7}{few}")
    if empty:
        lines += ["", f"Pas encore de chiffres par {', '.join(empty)} : aucun short publié et relié n'a ce "
                      "renseignement (les champs n'existent que sur les clips récents)."]
    lines += ["", format_ab(report["ab_opening"])]
    return "\n".join(lines)


def format_ab(ab) -> str:
    a, b = ab["with"], ab["without"]
    control = "les autres clips du même job" if ab["control"] == "same job" else "tous les shorts sans ouverture"
    lines = ["Test A/B de l'image dessinée d'ouverture (« Ont continué de regarder »)",
             f"  avec ouverture : {a['n']} short(s) reliés, médiane {_fr(a['stayed_median'], 1, ' %')}, "
             f"moyenne {_fr(a['stayed_mean'], 1, ' %')}, médiane vues {_fr(a['views_median'], 0)}",
             f"  sans ({control}) : {b['n']} short(s), médiane {_fr(b['stayed_median'], 1, ' %')}, "
             f"moyenne {_fr(b['stayed_mean'], 1, ' %')}, médiane vues {_fr(b['views_median'], 0)}"]
    if ab["verdict"] == "no_data":
        lines.append("  Verdict : pas encore de chiffres à comparer.")
    elif ab["verdict"] == "too_few":
        lines.append(f"  Verdict : trop peu de shorts ({a['n']} contre {b['n']}, il en faut au moins {AB_MIN_EACH} "
                     "de chaque côté) : rien à conclure.")
    else:
        chance = f"un écart au moins aussi grand sort par hasard {_fr(ab['p_value'] * 100, 0)} fois sur 100"
        if ab["verdict"] == "signal":
            lines.append(f"  Verdict : écart de {_fr(ab['gap'], 1)} points ; {chance}. Signal encourageant sur "
                         f"{a['n']} contre {b['n']} shorts, pas une preuve : à confirmer sur le prochain lot.")
        else:
            lines.append(f"  Verdict : écart de {_fr(ab['gap'], 1)} points ; {chance}. Compatible avec le hasard "
                         f"à {a['n']} contre {b['n']} shorts : on ne peut pas dire que l'ouverture change quelque chose.")
    young = a["young"] + b["young"]
    if young and ab["verdict"] != "no_data":
        lines.append(f"  Attention : {young} short(s) ont moins de {YOUNG_DAYS} jours au relevé (chiffres pas encore "
                     "stables ; relever 48 h après la publication du dernier).")
    if ab["pending"]:
        lines.append(f"  Pas encore dans l'export : {', '.join(ab['pending'])}.")
    return "\n".join(lines)


# --- command line -----------------------------------------------------------------------

def _parse_openings(values):
    """['b8e46c24:1,3,8'] -> {'b8e46c24': (1, 3, 8)}."""
    out = {}
    for v in values or []:
        job, _, nums = v.partition(":")
        out[job.strip()] = tuple(int(n) for n in re.findall(r"\d+", nums))
    return out


def _load_schedule(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("entries", []) if isinstance(data, dict) else data
    except (OSError, ValueError):
        return []


def _studio_cli(args, ab_only=False) -> int:
    rows, problem = read_views(args.file)
    if problem:
        print(f"Impossible d'utiliser {args.file} : {problem}")
        return 1
    openings = _parse_openings(args.opening) if args.opening else None
    clips = load_clips(args.output, _load_schedule(args.schedule), openings)
    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.fromtimestamp(os.path.getmtime(args.file)).date()
    report = build_studio_report(rows, clips, as_of)
    if ab_only:
        ab = report["ab_opening"] = ab_opening(report["posts"], clips, same_jobs=not args.all)
        print(format_ab(ab))
        stayed = {p["ref"]: p["stayed"] for p in report["posts"] if p["ref"]}
        for side, label in (("with", "avec"), ("without", "sans")):
            if ab[side]["refs"]:
                print(f"  {label} : " + " · ".join(f"{ref} {_fr(stayed.get(ref), 1, ' %')}"
                                                     for ref in ab[side]["refs"]))
    else:
        print(format_studio_report(report))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nRapport complet : {args.json_path}")
    return 0


def _is_studio(path) -> bool:
    if os.path.splitext(path)[1].lower() in (".json", ".zip"):
        return True
    rows, problem = read_views(path)
    return not problem and any(r.get("video_id") or r.get("stayed") is not None for r in rows)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "mark-opening":
        parser = argparse.ArgumentParser(prog="stats_ingest.py mark-opening",
                                         description="Record an opening image posed by hand on clips of a job.")
        parser.add_argument("job", help="job id or its first characters (b8e46c24)")
        parser.add_argument("clips", help="clip numbers, e.g. 1,3,8")
        parser.add_argument("--output", default="output")
        args = parser.parse_args(argv[1:])
        try:
            marked = mark_opening(args.output, args.job, [int(n) for n in re.findall(r"\d+", args.clips)])
        except (ValueError, OSError) as e:
            print(f"Rien d'écrit : {e}")
            return 1
        print("Ouverture notée sur : " + ", ".join(marked))
        return 0
    ab_only = bool(argv) and argv[0] == "ab"
    parser = argparse.ArgumentParser(description="Join a YouTube Studio export (or a views CSV) to the clips.")
    parser.add_argument("file", help="YouTube Studio export (CSV / ZIP), studio.json, or a views CSV")
    parser.add_argument("--output", default="output", help="folder holding the jobs (default: output)")
    parser.add_argument("--schedule", default="publish_schedule.json", help="the publish plan")
    parser.add_argument("--json", dest="json_path", help="also write the full report as JSON here")
    parser.add_argument("--as-of", help="day of the export (YYYY-MM-DD; default: the file's date)")
    parser.add_argument("--opening", action="append",
                        help="clips that open on a drawn picture, 'job:1,3,8' (default: the field on the clips "
                             "+ the A/B test of 5-oct)")
    parser.add_argument("--all", action="store_true", help="A/B: compare with every short without an opening")
    args = parser.parse_args(argv[1:] if ab_only else argv)
    if ab_only or _is_studio(args.file):
        return _studio_cli(args, ab_only)
    exports = load_exports(args.output)
    if not exports:
        print(f"No *_playbook.json under {args.output}: run a job with the Synapse Cut playbook first.")
        return 1
    rows, problem = read_views(args.file)
    if problem:
        print(f"Cannot use {args.file}: {problem}")
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
