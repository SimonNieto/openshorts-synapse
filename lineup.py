"""Line-up: every clip still on disk on one board, and the variety of the week to come (5-oct-2026).

The week of 5-oct-2026 went out as 12 clips of one episode in 4 days: same man, same curtain, 7 of 12 "Medicine",
12 of 12 question titles (output/_stepup/donnees/rapport.md). Nothing in the app showed it before it was scheduled.
This module reads the clips, the publish plan, the Studio export and the hook jury; it never publishes anything:

- ``build``: the catalogue (published clips included, unlike the pickers that hide them) with each clip's topic,
  episode, state on the publishing line, real numbers and jury note; the categories; the week's timeline on
  YouTube's line, its mix and the variety alerts. The dashboard's Line-up tab draws it (``GET /api/lineup``).
- ``plan``: a deterministic order for chosen clips over chosen slots: at each slot, the best hook that keeps the
  mix. A proposal only: the tab posts it through the existing ``/api/social/post``, one clip at a time.
- ``set_category``: the topic corrected by hand (``category_manual`` in metadata.json, its mtime kept).
- ``start_jury``: the hook jury (hook_jury.py, its own module) over the clips that have no note yet, in one
  background thread (JURY_ENABLED switches it).
- ``thumbnail``: a still of the rendered clip at ~1.5 s, made once per rendered file and cached on disk in
  ``output/_lineup/thumbs/``.

No AI call from the board, the plan nor the category (the user's rule: a clip's tokens are spent once): they read
what the generator already wrote in metadata.json (topic_bucket, predicted_score, titles, hook, moment_nature…), the
jury's kept notes, the publish plan and the Studio export. A clip without a topic is "Other", corrected by hand —
never guessed. Only ``start_jury`` (the tab's "test" button) asks a model, once per rendered mp4.
The variety rules are landmarks, not locks: an alert says what and where, nothing is ever blocked.
"""
from __future__ import annotations

import glob
import hashlib
import importlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta

import playbook
import stats_ingest

# --- the variety rules (5-oct-2026) -----------------------------------------------------------------------------
# Read on YouTube's line (the channel's reference: a clip's other platforms go out with it), over today and the
# six days after it. Landmarks, not locks: they raise an alert, they never block a post.
WINDOW_DAYS = 7
# Two clips of one topic back to back read as one short posted twice to someone who scrolls the channel
# (5-oct-2026: 7 of the week's 12 were "Medicine", runs of three and four of them).
MAX_SAME_CATEGORY_IN_A_ROW = 1
# One episode is one face, one set, one light: past two a day the feed looks like a re-upload of the episode.
MAX_EPISODE_PER_DAY = 2
# The same guest is the same face and the same set on screen, whatever the topic or the episode: two posts in a
# row with one guest look alike before a word is heard (5-oct-2026, the user: vary the content AND the picture).
MAX_SAME_GUEST_IN_A_ROW = 1
# One topic may lead the week, not be it: ~35 % is 7 posts of 21 at three a day.
MAX_CATEGORY_SHARE = 0.35
# One episode at most half the week (5-oct-2026: 12 of 12 from JRE #2553).
MAX_EPISODE_SHARE = 0.50
# Question titles are the playbook's (they win: 7,100 views against 1,300 for the statement), but 12 of 12 made
# the week read like a quiz: ~60 % at most. Why / How titles count too: the same promise shape to the eye.
MAX_QUESTION_SHARE = 0.60
QUESTION_FORMS = ("question", "why", "how")
# A share means nothing over a handful of posts (1 of 2 is already 50 %): the share rules start at 6 posts.
MIN_CLIPS_FOR_SHARES = 6
# "Other" is no topic (the clips made before the playbook have no topic_bucket): two of them in a row, or many in
# a week, say nothing about variety. They count in the totals, never as a topic of their own.
UNSORTED_CATEGORY = "other"

RULES = {
    "window_days": WINDOW_DAYS,
    "advisory": True,
    "same_category_in_a_row": {
        "max": MAX_SAME_CATEGORY_IN_A_ROW,
        "why": "Two clips of one topic back to back read as one short posted twice."},
    "same_guest_in_a_row": {
        "max": MAX_SAME_GUEST_IN_A_ROW,
        "why": "The same guest is the same face and the same set: two in a row look alike before a word is heard."},
    "episode_per_day": {
        "max": MAX_EPISODE_PER_DAY,
        "why": "One episode is one face and one set: more than two a day looks like a re-upload."},
    "category_share": {
        "max": MAX_CATEGORY_SHARE, "min_clips": MIN_CLIPS_FOR_SHARES,
        "why": "One topic may lead the week, not be it."},
    "episode_share": {
        "max": MAX_EPISODE_SHARE, "min_clips": MIN_CLIPS_FOR_SHARES,
        "why": "One episode at most half the week."},
    "title_form_share": {
        "max": MAX_QUESTION_SHARE, "min_clips": MIN_CLIPS_FOR_SHARES, "forms": list(QUESTION_FORMS),
        "why": "Question titles win, but a week of only questions reads like a quiz."},
    "ignored_categories": [UNSORTED_CATEGORY],
}

# --- the hook jury (hook_jury.py, its own module) ---------------------------------------------------------------
# (5-oct-2026) switched on at the user's request: the viewer notes each clip once, at the end of its job, and the
# notes of the clips made before arrive in output/_jury/results/. The board only READS them; POST /api/lineup/jury
# (the tab's "test" button) judges the clips without a note — never one whose rendered mp4 is unchanged (the user's
# rule: a clip's tokens are spent once). Off (False): nothing imports hook_jury, every clip's ``jury`` and the
# calibration are null, POST /api/lineup/jury answers "disabled" without running anything.
JURY_ENABLED = True
# How the clips are ranked (the board's order, the plan's choice): three groups, best evidence first, and a score
# is only ever compared with a score of its own group (5-oct-2026: the jury's notes run 22-72, the generator's
# selection scores 65-90 — an untested clip outranked every tested one). 1. the published clips with their real
# "Stayed to watch" (apart: the number that decides a short's fate, never mixed with an estimate); 2. the clips the
# jury noted, by ``jury.score``; 3. after them, the clips not tested yet (``untested``), by ``ai_score``.
RANK_SOURCES = ("stayed", "jury", "ai")

# --- the plan ---------------------------------------------------------------------------------------------------
# The Publish plan's daily times (dashboard/src/lib/postSlots.js SLOT_OPTIONS): what /plan fills when the tab
# sends no slots of its own.
SLOT_TIMES = ("08:00", "12:00", "20:00")
# The channel's time zone when the dashboard sends none (``tz``): the publish plan stores local dates and times
# (Upload-Post gets them with the browser's zone) while the container's clock is UTC. Europe/Paris: the plan's
# "posted now" entries read 14:34 for 12:34 UTC (24-sep-2026). LINEUP_TZ overrides it.
DEFAULT_TZ = "Europe/Paris"

# --- the thumbnail ----------------------------------------------------------------------------------------------
# Past the first frame (often a cut or a black frame), on the hook's first words.
THUMB_AT = 1.5
THUMB_WIDTH = 360
THUMB_DIR = os.path.join("_lineup", "thumbs")          # under the output dir
FFMPEG_TIMEOUT = 30

# --- the disk ---------------------------------------------------------------------------------------------------
# (5-oct-2026) The self-hosted app deletes nothing on its own any more (app.AUTO_PURGE): the user removes old
# projects herself, so the board shows what each one weighs and the disk left. Walking output/ is slow (thousands
# of files): the sizes are measured at most once every DISK_CACHE_SECONDS, never on every request.
DISK_CACHE_SECONDS = 300
GB = 1024 ** 3

# A job folder: a uuid4 or a test id (u2515ins-0000-…). Never a dot, a slash nor a leading "_" (output/_lineup,
# output/_jury… are not jobs).
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})")
_EPISODE_NO = re.compile(r"#\s*(\d{1,5})\b|\b(?:episode|ep\.?|e)\s*(\d{1,5})\b", re.I)
_SMALL_WORDS = {"the", "a", "an", "of", "and", "with", "on", "in", "at", "for", "to", "by"}
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class LineupError(ValueError):
    """A request the line-up cannot serve (bad id, unknown clip, unknown category); ``status``: the HTTP code."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# --- small helpers ----------------------------------------------------------------------------------------------

def safe_job_id(job_id) -> bool:
    return isinstance(job_id, str) and bool(_JOB_ID.match(job_id))


def clip_ref(job_id, clip_index) -> str:
    """'b8e46c24_c01': the clip's short name, the same as stats_ingest's and the jury's."""
    return f"{str(job_id)[:8]}_c{int(clip_index) + 1:02d}"


def category_label(category) -> str:
    return playbook.HOOK_CATEGORY.get(str(category or ""), "Other")


def _zone(tz=None):
    from zoneinfo import ZoneInfo
    for name in (tz, os.environ.get("LINEUP_TZ"), DEFAULT_TZ, "UTC"):
        if not name:
            continue
        try:
            return ZoneInfo(str(name))
        except Exception:
            continue
    return ZoneInfo("UTC")


def _hhmm(value):
    """'8:00' / '08:00:00' -> '08:00', None when it is not a time."""
    m = _TIME.match(str(value or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _iso_day(value):
    s = str(value or "")[:10]
    if not _DATE.match(s):
        return None
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def _at(day, hhmm):
    """The naive local datetime of a slot (a slot without a time counts from the start of its day)."""
    h, m = (int(x) for x in (hhmm or "00:00").split(":"))
    return datetime.combine(date.fromisoformat(day), datetime.min.time()).replace(hour=h, minute=m)


def _day_label(day) -> str:
    d = date.fromisoformat(day)
    return f"{_DAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]}"


def _when_label(item) -> str:
    return f"{_day_label(item['date'])} {item['time']}" if item.get("time") else _day_label(item["date"])


def _pct(count, total) -> int:
    return int(round(100.0 * count / total)) if total else 0


def _slug(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if float(value).is_integer() else round(float(value), 1)


def title_form(title):
    """'question' (Can / Is / Does… or any '?'), 'why', 'how' or 'statement'; None without a title."""
    core = re.sub(r"#\w+", " ", str(title or "")).strip()
    if not core:
        return None
    first = stats_ingest.title_form(core).lower()
    if first in ("why", "how"):
        return first
    if first != "other" or "?" in core:
        return "question"
    return "statement"


def episode_info(source, job_id="") -> dict:
    """{"show", "episode", "guest", "episode_key"} from the source's name: 'Joe Rogan Experience #2553 - Andrew
    Huberman-004' -> 'Joe Rogan Experience', '#2553', 'Andrew Huberman', 'jre-2553'. The 500 MB piece suffix
    ('-004') is not part of it: two pieces are one episode. None for what the name does not say."""
    name = os.path.basename(str(source or "").replace("\\", "/"))
    if job_id and name.startswith(f"{job_id}_"):
        name = name[len(job_id) + 1:]
    title = playbook.episode_title(name)
    if not title:
        return {"show": None, "episode": None, "guest": None,
                "episode_key": f"job-{str(job_id)[:8]}" if job_id else None}
    show, rest = playbook.split_show(title)
    if not show:
        show, rest = title, ""
    m = _EPISODE_NO.search(rest) or _EPISODE_NO.search(title)
    number = (m.group(1) or m.group(2)) if m else None
    guest = _EPISODE_NO.sub(" ", rest, count=1) if number else rest
    guest = re.sub(r"\s+", " ", guest).strip(" -–|:,.") or None
    if number and show and _EPISODE_NO.search(show):
        show = _EPISODE_NO.sub(" ", show, count=1).strip(" -–|:,.") or show
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", show) if w.lower() not in _SMALL_WORDS).lower()
    key = f"{initials or 'ep'}-{number}" if number else (_slug(title)[:48] or f"job-{str(job_id)[:8]}")
    return {"show": show or None, "episode": f"#{number}" if number else None, "guest": guest, "episode_key": key}


def _episode_label(clip) -> str:
    return " ".join(x for x in (clip.get("show"), clip.get("episode")) if x) or clip.get("episode_key") or "?"


# --- the clips on disk ------------------------------------------------------------------------------------------

def _projects(output_dir):
    """(job_id, job_dir, metadata path, data) of every job folder with a readable metadata.json, ``_*`` folders
    left out."""
    try:
        names = sorted(os.listdir(output_dir))
    except OSError:
        return
    for job_id in names:
        job_dir = os.path.join(output_dir, job_id)
        if not safe_job_id(job_id) or not os.path.isdir(job_dir):
            continue
        metas = sorted(glob.glob(os.path.join(glob.escape(job_dir), "*_metadata.json")))
        if not metas:
            continue
        try:
            with open(metas[0], encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            yield job_id, job_dir, metas[0], data


def rendered_file(job_dir, base_name, index, short) -> str | None:
    """The clip's rendered mp4 (a name inside ``job_dir``), None when it is gone. The one the app serves
    (``video_url``), else app._canonical_clip_file's choice: the newest subtitled / recut / hooked layer, else
    the clean reframe."""
    url = str((short or {}).get("video_url") or "")
    if url:
        name = os.path.basename(url.split("?", 1)[0])
        if name and os.path.isfile(os.path.join(job_dir, name)):
            return name
    clean = f"{base_name}_clip_{index + 1}.mp4"
    folder, pat = glob.escape(job_dir), glob.escape(clean)
    derived = []
    for pattern in (f"subtitled_*_{pat}", f"recut_*_{pat}", f"hooked_*_{pat}", f"hook_{pat}"):
        derived += glob.glob(os.path.join(folder, pattern))
    if derived:
        return os.path.basename(max(derived, key=os.path.getmtime))
    return clean if os.path.isfile(os.path.join(job_dir, clean)) else None


def _playbook_exports(job_dir) -> dict:
    out = {}
    for path in glob.glob(os.path.join(glob.escape(job_dir), "*_playbook.json")):
        m = re.search(r"_clip_(\d+)_playbook\.json$", path)
        if not m:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                out[int(m.group(1))] = json.load(f)
        except (OSError, ValueError):
            pass
    return out


def _duration(short, export):
    segments = ((short.get("recipe") or {}).get("segments")) or []
    try:
        if segments:
            return round(sum(float(s["end"]) - float(s["start"]) for s in segments), 1)
        if short.get("end") is not None and short.get("start") is not None:
            return round(float(short["end"]) - float(short["start"]), 1) or None
    except (KeyError, TypeError, ValueError):
        pass
    return _number(export.get("duration"))


def _entries_by_clip(schedule) -> dict:
    by_clip = {}
    for e in schedule or []:
        if not isinstance(e, dict) or e.get("job_id") is None:
            continue
        try:
            key = (str(e["job_id"]), int(e.get("clip_index")))
        except (TypeError, ValueError):
            continue
        by_clip.setdefault(key, []).append(e)
    return by_clip


def _entry_slots(entries, now) -> list:
    """The publish-plan entries of one clip grouped by date + time: [{"date", "time", "platforms", "status"}],
    oldest first. A slot is published when an entry was posted, or when Upload-Post had it and its time has
    passed (it publishes on its own: the plan keeps ``posted`` False for a scheduled send); scheduled otherwise."""
    groups = {}
    for e in entries:
        day = _iso_day(e.get("date"))
        if not day:
            continue
        hhmm = _hhmm(e.get("time"))
        g = groups.setdefault((day, hhmm or ""), {"date": day, "time": hhmm, "platforms": [], "entries": []})
        platform = str(e.get("platform") or "").lower()
        if platform and platform not in g["platforms"]:
            g["platforms"].append(platform)
        g["entries"].append(e)
    slots = []
    for _key, g in sorted(groups.items()):
        es = g.pop("entries")
        if any(e.get("posted") for e in es) or (any(e.get("auto") for e in es) and _at(g["date"], g["time"]) <= now):
            g["status"] = "published"
        else:
            g["status"] = "scheduled"
        g["platforms"].sort()
        slots.append(g)
    return slots


def _stamp_slot(stamp, now, zone):
    """A slot from a clip's own ``published`` stamp (metadata.json) when the plan has no entry for it."""
    when = None
    if stamp.get("scheduled_for"):
        try:
            when = datetime.fromisoformat(str(stamp["scheduled_for"])[:19])
        except ValueError:
            when = None
    if when is None and stamp.get("at") is not None:
        try:
            when = datetime.fromtimestamp(float(stamp["at"]), zone).replace(tzinfo=None)
        except (TypeError, ValueError, OSError):
            when = None
    if when is None:
        return None
    return {"date": when.date().isoformat(), "time": when.strftime("%H:%M"), "platforms": [],
            "status": "published" if when <= now else "scheduled"}


def _state(entries, stamp, now, zone):
    """(status, slots, line slots, published_at). The line is the YouTube slots (the reference timeline; the
    clip's other platforms are grouped with them), else every slot."""
    slots = _entry_slots(entries, now)
    if slots and not stamp and all(e.get("auto") for e in entries):
        # Put back in its project by hand (/api/clip/{job}/{i}/restore: the platform refused it): free again,
        # its old slots kept for the record, off the timeline.
        return "available", slots, [], None
    if not slots and stamp:
        slot = _stamp_slot(stamp, now, zone) if isinstance(stamp, dict) else None
        if slot is None:
            return "published", [], [], None                # an old bare ``published: true``
        slots = [slot]
    line = [s for s in slots if "youtube" in s["platforms"]] or slots
    if any(s["status"] == "scheduled" for s in line):
        status = "scheduled"
    elif line:
        status = "published"
    else:
        status = "available"
    published = [s for s in line if s["status"] == "published"]
    published_at = None
    if published:
        last = published[-1]
        published_at = f"{last['date']}T{last['time'] or '00:00'}:00"
    return status, slots, line, published_at


def _expires_in_days(job_dir, clock, retention_seconds):
    """Days left before app.cleanup_jobs purges the job: it ages the job FOLDER's mtime (not metadata.json's)."""
    if not retention_seconds:
        return None
    try:
        age = clock - os.path.getmtime(job_dir)
    except OSError:
        return None
    return round(max(0.0, (float(retention_seconds) - age) / 86400.0), 1)


def _studio_stats(stats_dir, output_dir, schedule):
    """({(job_id, clip_index): {"stayed", "views", "as_of"}}, export info or None) from the newest Studio export,
    joined to the clips as /api/plus/stats does (stats_ingest.link_studio)."""
    if not stats_dir:
        return {}, None
    try:
        path, rows, problem = stats_ingest.read_latest_export(stats_dir)
    except Exception as e:                                   # a broken export never breaks the board
        return {}, {"file": None, "exported": None, "problem": str(e)[:200], "linked": 0}
    if not path:
        return {}, None
    exported = datetime.fromtimestamp(os.path.getmtime(path)).date().isoformat()
    info = {"file": os.path.basename(path), "exported": exported, "problem": problem or None, "linked": 0}
    if problem:
        return {}, info
    out = {}
    for row, clip, _how in stats_ingest.link_studio(rows, stats_ingest.load_clips(output_dir, schedule)):
        if not clip:
            continue
        key = (clip["job_id"], clip["clip_index"])
        current = out.get(key)
        # The same short uploaded twice: the row with the most views speaks for it.
        if current is None or (row.get("views") or 0) > (current["views"] or 0):
            out[key] = {"stayed": _number(row.get("stayed")), "views": _number(row.get("views")), "as_of": exported}
    info["linked"] = len(out)
    return out, info


# --- the hook jury (hook_jury.py, contract C1) -------------------------------------------------------------------

def jury_module():
    """hook_jury, imported on first use (its own module, built apart); None when it is not there or the jury is
    off (JURY_ENABLED)."""
    if not JURY_ENABLED:
        return None
    try:
        return importlib.import_module("hook_jury")
    except ImportError:
        return None


def _jury_result(mod, output_dir, job_id, clip_index):
    if mod is None:
        return None
    try:
        result = mod.load_result(output_dir, job_id, clip_index)
    except Exception as e:
        print(f"⚠️ Line-up: jury result of {clip_ref(job_id, clip_index)} unreadable: {e}")
        return None
    return result if isinstance(result, dict) else None


def _jury_calibration(mod, output_dir):
    if mod is None:
        return None
    try:
        result = mod.load_calibration(output_dir)
    except Exception as e:
        print(f"⚠️ Line-up: jury calibration unreadable: {e}")
        return None
    return result if isinstance(result, dict) else None


# --- the board --------------------------------------------------------------------------------------------------

def _project_age_days(meta_path, clock):
    """Days since the project's date (its metadata.json mtime: what History and the Publish plan show, kept by
    every edit)."""
    try:
        return round(max(0.0, (clock - os.path.getmtime(meta_path)) / 86400.0), 1)
    except OSError:
        return None


def _catalog(projects, output_dir, by_clip, now, zone, clock, retention_seconds, stats, mod):
    projects = sorted(projects, key=lambda p: (-_mtime(p[2]), p[0]))
    for job_id, job_dir, meta_path, data in projects:
        base_name = os.path.basename(meta_path)[:-len("_metadata.json")]
        episode = episode_info(data.get("source_video") or f"{base_name}.mp4", job_id)
        kept = os.path.exists(os.path.join(job_dir, ".keep"))
        expires = None if kept else _expires_in_days(job_dir, clock, retention_seconds)
        age = _project_age_days(meta_path, clock)
        exports = _playbook_exports(job_dir)
        for i, short in enumerate(data.get("shorts") or []):
            if not isinstance(short, dict):
                continue
            name = rendered_file(job_dir, base_name, i, short)
            if not name:
                continue
            export = exports.get(i + 1) or {}
            ai_bucket = short.get("topic_bucket") or export.get("topic_bucket")
            ai_bucket = ai_bucket if ai_bucket in playbook.TOPIC_BUCKETS else None
            manual = short.get("category_manual")
            manual = manual if manual in playbook.TOPIC_BUCKETS else None
            category = manual or ai_bucket or UNSORTED_CATEGORY
            nature = short.get("moment_nature") or export.get("moment_nature")
            hook = (short.get("auto_hook") or {}).get("text") if isinstance(short.get("auto_hook"), dict) else None
            status, slots, line, published_at = _state(by_clip.get((job_id, i), []), short.get("published"),
                                                       now, zone)
            title = short.get("video_title_for_youtube_short") or export.get("title") or None
            clip = {
                "job_id": job_id, "clip_index": i, "ref": clip_ref(job_id, i),
                "title": title,
                "hook": hook or short.get("viral_hook_text") or None,
                "hook_line": short.get("hook_line") or None,
                "video_url": f"/videos/{job_id}/{name}",
                "thumb_url": f"/api/lineup/thumb/{job_id}/{i}",
                "duration": _duration(short, export),
                "category": category, "category_label": category_label(category),
                "category_source": "manual" if manual else "ai",
                "ai_category": ai_bucket,
                **episode,
                "title_form": title_form(title),
                "moment_nature": nature if nature in playbook.MOMENT_NATURES else None,
                "ai_score": _number(short.get("predicted_score")),
                "status": status, "slots": slots, "published_at": published_at,
                "stats": stats.get((job_id, i)),
                "jury": _jury_result(mod, output_dir, job_id, i),
                "expires_in_days": expires, "kept": kept, "project_age_days": age,
                "niche": data.get("niche"), "niche_guess": data.get("niche_guess"),
                "upload_profile": data.get("upload_profile"),
                "_line": line,
            }
            clip["rank_score"], clip["rank_score_source"] = rank_score(clip)
            clip["untested"] = clip["rank_score_source"] == "ai"
            yield clip


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _item(clip, slot, status):
    """One post on the timeline, what the rules read."""
    return {"date": slot["date"], "time": slot.get("time"), "ref": clip["ref"], "status": status,
            "category": clip.get("category"), "category_label": clip.get("category_label"),
            "episode_key": clip.get("episode_key"), "episode_label": _episode_label(clip) if clip.get("episode_key")
            else None, "guest": clip.get("guest"), "guest_key": _slug(clip.get("guest")) or None,
            "title_form": clip.get("title_form"), "on_disk": clip.get("on_disk", True)}


def _timeline(clips, by_clip, now):
    """Every post on YouTube's line, any date: the clips on disk, and the plan's entries whose clip is gone from
    the disk (their title is known, not their topic nor their episode)."""
    items, seen = [], set()
    for c in clips:
        seen.add((c["job_id"], c["clip_index"]))
        for slot in c["_line"]:
            items.append(_item(c, slot, slot["status"]))
    for (job_id, i), entries in sorted(by_clip.items()):
        if (job_id, i) in seen:
            continue
        slots = _entry_slots(entries, now)
        line = [s for s in slots if "youtube" in s["platforms"]] or slots
        title = next((e.get("title") for e in entries if e.get("title")), None)
        gone = {"ref": clip_ref(job_id, i), "category": None, "category_label": None, "episode_key": None,
                "title_form": title_form(title), "on_disk": False}
        for slot in line:
            item = _item(gone, slot, slot["status"])
            item["title"] = title
            items.append(item)
    items.sort(key=_order)
    return items


def _order(item):
    return item["date"], item.get("time") or "", item["ref"]


def _board(output_dir, schedule, *, stats_dir=None, retention_seconds=None, tz=None, clock=None):
    clock = time.time() if clock is None else float(clock)
    zone = _zone(tz)
    now = datetime.fromtimestamp(clock, zone).replace(tzinfo=None, microsecond=0)
    by_clip = _entries_by_clip(schedule)
    stats, stats_info = _studio_stats(stats_dir, output_dir, schedule)
    mod = jury_module()
    projects = list(_projects(output_dir))
    clips = list(_catalog(projects, output_dir, by_clip, now, zone, clock, retention_seconds, stats, mod))
    return {"clips": clips, "timeline": _timeline(clips, by_clip, now), "now": now, "zone": zone,
            "stats_export": stats_info, "mod": mod, "projects": projects, "clock": clock}


def evaluate(items, prev=None, total=None, span="this week"):
    """(alerts, penalty) for the posts ``items`` (one window, any order): each alert says what and where in
    plain English, ``penalty`` how far past the rules (posts over a limit) for the plan to compare choices.
    ``prev``: the last post before the window (a run may start there). ``total``: the share rules' denominator
    when it is not len(items) (the plan's final count while it is still filling)."""
    items = sorted(items, key=_order)
    alerts, penalty = [], 0

    def cat(it):
        c = (it or {}).get("category")
        return c if c and c != UNSORTED_CATEGORY else None

    def runs(key, limit, kind, say):
        """Back-to-back posts sharing ``key`` (None never matches), longer than ``limit``: one alert per run."""
        nonlocal penalty
        run = []
        for it in ([prev] if prev else []) + items + [None]:
            if run and it is not None and key(it) is not None and key(it) == key(run[-1]):
                run.append(it)
                continue
            if len(run) > limit:
                alerts.append({"kind": kind,
                               "message": f"{say(run)} ({_when_label(run[0])} to {_when_label(run[-1])}).",
                               "refs": [r["ref"] for r in run], "date": run[limit]["date"]})
                penalty += len(run) - limit
            run = [it] if it is not None and key(it) is not None else []

    runs(cat, MAX_SAME_CATEGORY_IN_A_ROW, "same_category_in_a_row",
         lambda run: f"{len(run)} {run[0].get('category_label') or category_label(cat(run[0]))} clips in a row")
    runs(lambda it: (it or {}).get("guest_key"), MAX_SAME_GUEST_IN_A_ROW, "same_guest_in_a_row",
         lambda run: f"{len(run)} clips in a row with {run[0].get('guest') or 'the same guest'}: same face, same set")

    per_day = {}
    for it in items:
        if it.get("episode_key"):
            per_day.setdefault((it["date"], it["episode_key"]), []).append(it)
    for (day, _key), group in sorted(per_day.items()):
        if len(group) > MAX_EPISODE_PER_DAY:
            alerts.append({"kind": "episode_per_day",
                           "message": f"{len(group)} clips from {group[0]['episode_label']} on {_day_label(day)}: "
                                      f"{MAX_EPISODE_PER_DAY} a day at most.",
                           "refs": [g["ref"] for g in group], "date": day})
            penalty += len(group) - MAX_EPISODE_PER_DAY

    n = len(items) if total is None else max(int(total), len(items))
    if n >= MIN_CLIPS_FOR_SHARES:
        def over(groups, limit, kind, say):
            nonlocal penalty
            cap = math.floor(limit * n + 1e-9)
            for _key, group in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
                if len(group) > cap:
                    alerts.append({"kind": kind, "message": say(group, len(group)),
                                   "refs": [g["ref"] for g in group], "date": None})
                    penalty += len(group) - cap

        cats, eps = {}, {}
        for it in items:
            if cat(it):
                cats.setdefault(cat(it), []).append(it)
            if it.get("episode_key"):
                eps.setdefault(it["episode_key"], []).append(it)
        over(cats, MAX_CATEGORY_SHARE, "category_share",
             lambda g, k: f"{g[0].get('category_label') or category_label(cat(g[0]))} is {k} of {n} clips {span} "
                          f"({_pct(k, n)}%): keep one topic under {_pct(MAX_CATEGORY_SHARE, 1)}%.")
        over(eps, MAX_EPISODE_SHARE, "episode_share",
             lambda g, k: f"{k} of {n} clips {span} come from {g[0]['episode_label']} ({_pct(k, n)}%): "
                          f"keep one episode under {_pct(MAX_EPISODE_SHARE, 1)}%.")
        asks = [it for it in items if it.get("title_form") in QUESTION_FORMS]
        over({"question": asks} if asks else {}, MAX_QUESTION_SHARE, "title_form_share",
             lambda g, k: f"{k} of {n} titles {span} are questions ({_pct(k, n)}%): "
                          f"keep questions under {_pct(MAX_QUESTION_SHARE, 1)}%.")
    return alerts, penalty


def _week(timeline, today):
    end = today + timedelta(days=WINDOW_DAYS - 1)
    lo, hi = today.isoformat(), end.isoformat()
    inside = [it for it in timeline if lo <= it["date"] <= hi]
    before = [it for it in timeline if it["date"] < lo]
    return lo, hi, inside, (before[-1] if before else None)


def _mix(items) -> dict:
    mix = {"category": {}, "episode": {}, "title_form": {}}
    for it in items:
        for field, key in (("category", it.get("category")), ("episode", it.get("episode_key")),
                           ("title_form", it.get("title_form"))):
            if key:
                mix[field][key] = mix[field].get(key, 0) + 1
    return mix


def _public(clip) -> dict:
    return {k: v for k, v in clip.items() if not k.startswith("_")}


def build(output_dir, schedule, *, stats_dir="stats", retention_seconds=None, tz=None, clock=None,
          uploads_dir=None) -> dict:
    """GET /api/lineup (contract C2): the catalogue, the categories, the week (today -> +6 days on YouTube's
    line: timeline, mix, alerts), the rules, the jury's calibration and its background run; the projects and the
    disk, for deleting old projects by hand. ``retention_seconds``: the automatic purge's clock, None when the app
    purges nothing on its own (then every ``expires_in_days`` is null). ``null`` wherever a value is missing —
    never a guess."""
    board = _board(output_dir, schedule, stats_dir=stats_dir, retention_seconds=retention_seconds, tz=tz,
                   clock=clock)
    disk = disk_usage(output_dir, uploads_dir)
    now, clips = board["now"], board["clips"]
    lo, hi, inside, prev = _week(board["timeline"], now.date())
    alerts, _penalty = evaluate(inside, prev)
    counts = {}
    for c in clips:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    categories = [{"id": b, "label": category_label(b), "count": counts.get(b, 0)} for b in playbook.TOPIC_BUCKETS]
    episodes = {it["episode_key"]: it["episode_label"] for it in inside if it.get("episode_key")}
    return {
        "now": now.isoformat(timespec="seconds"),
        "timezone": getattr(board["zone"], "key", None),
        "clips": [_public(c) for c in clips],
        "categories": categories,
        "week": {
            "from": lo, "to": hi,
            "timeline": [{k: it[k] for k in ("date", "time", "ref", "status", "on_disk")}
                         | ({"title": it.get("title")} if not it["on_disk"] else {}) for it in inside],
            "mix": _mix(inside),
            "episodes": episodes,
            "alerts": alerts,
        },
        "rules": rules(),
        "stats_export": board["stats_export"],
        "jury_enabled": JURY_ENABLED,
        "jury_calibration": _jury_calibration(board["mod"], output_dir),
        "jury_run": jury_state(),
        "auto_purge": retention_seconds is not None,
        "disk": {"output_gb": _gb(disk["output"], 2), "uploads_gb": _gb(disk["uploads"], 2),
                 "free_gb": _gb(disk["free"], 1), "measured_at": disk["measured_at"]},
        "projects": _project_list(board, disk, retention_seconds),
    }


def _gb(size, digits):
    return None if size is None else round(size / GB, digits)


_NO_CLIPS = {"clips": 0, "published": 0, "scheduled": 0, "available": 0}


def _project_list(board, disk, retention_seconds):
    """One line per project on disk (even one whose clips are all gone), oldest first: what the tab offers to
    delete by hand (the existing DELETE /api/local-projects/{job_id}). ``clips``: its clips with a rendered file
    (the board's), ``shorts``: every clip it made."""
    counts = {}
    for c in board["clips"]:
        n = counts.setdefault(c["job_id"], dict(_NO_CLIPS))
        n["clips"] += 1
        n[c["status"]] += 1
    out = []
    for job_id, job_dir, meta_path, data in board["projects"]:
        base_name = os.path.basename(meta_path)[:-len("_metadata.json")]
        title = base_name[len(job_id) + 1:] if base_name.startswith(f"{job_id}_") else base_name
        kept = os.path.exists(os.path.join(job_dir, ".keep"))
        out.append({"job_id": job_id, "title": title or job_id,
                    "age_days": _project_age_days(meta_path, board["clock"]),
                    "size_gb": _gb(disk["folders"].get(job_id), 3),
                    "shorts": len(data.get("shorts") or []), **counts.get(job_id, _NO_CLIPS),
                    "kept": kept,
                    "expires_in_days": None if kept else _expires_in_days(job_dir, board["clock"],
                                                                          retention_seconds),
                    "episode_key": episode_info(data.get("source_video") or f"{base_name}.mp4",
                                                job_id)["episode_key"]})
    out.sort(key=lambda p: (-(p["age_days"] or 0), p["job_id"]))
    return out


_disk_lock = threading.Lock()
_disk_cache = {}


def _tree_size(path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def disk_usage(output_dir, uploads_dir=None) -> dict:
    """{"output", "uploads", "free" (bytes, None when unknown), "folders": {name: bytes} of output/'s top
    folders, "measured_at"}, measured at most once every DISK_CACHE_SECONDS per (output_dir, uploads_dir)."""
    key = (os.path.abspath(output_dir), os.path.abspath(uploads_dir) if uploads_dir else None)
    with _disk_lock:
        hit = _disk_cache.get(key)
        if hit and time.monotonic() - hit[0] < DISK_CACHE_SECONDS:
            return hit[1]
    folders, total = {}, 0
    try:
        names = os.listdir(output_dir)
    except OSError:
        names = None
    for name in names or []:
        path = os.path.join(output_dir, name)
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                folders[name] = _tree_size(path)
                total += folders[name]
            elif os.path.isfile(path):
                total += os.path.getsize(path)
        except OSError:
            pass
    uploads = _tree_size(uploads_dir) if uploads_dir and os.path.isdir(uploads_dir) else None
    try:
        free = shutil.disk_usage(output_dir).free
    except OSError:
        free = None
    data = {"output": None if names is None else total, "uploads": uploads, "free": free, "folders": folders,
            "measured_at": datetime.now().isoformat(timespec="seconds")}
    with _disk_lock:
        _disk_cache[key] = (time.monotonic(), data)
    return data


def forget_disk() -> None:
    """Drop the measured sizes (a project was deleted: the next board measures again)."""
    with _disk_lock:
        _disk_cache.clear()


def rules() -> dict:
    """RULES + how the clips are ranked (the plan's order), which depends on the jury switch."""
    sources = [s for s in RANK_SOURCES if JURY_ENABLED or s != "jury"]
    if JURY_ENABLED:
        why = ("Three groups, never compared with each other: published clips by their real 'Stayed to watch'; "
               "then the clips the spectator tested, by their jury score; then the clips not tested yet, by the "
               "generator's selection score (ai_score).")
        plan = ("Tested clips first: an untested clip only takes a slot when no tested clip left fits it "
                "without an alert.")
    else:
        why = ("Published clips by their real 'Stayed to watch'; the others by the generator's selection score "
               "(ai_score): the hook jury is off.")
        plan = "The best ai_score that fits the slot without an alert, else the one that clashes least."
    return {**RULES, "ranking": {"by": sources, "field": "rank_score", "source_field": "rank_score_source",
                                 "untested_field": "untested", "untested_last": True, "why": why, "plan": plan},
            "jury_enabled": JURY_ENABLED}


def find_clip(board_or_view, job_id, clip_index):
    for c in board_or_view["clips"]:
        if c["job_id"] == job_id and c["clip_index"] == clip_index:
            return c
    return None


# --- the plan ---------------------------------------------------------------------------------------------------

_RANK_BASIS = {"stayed": "real stayed", "jury": "jury score", "ai": "AI score"}


def rank_score(clip):
    """(value, source) in RANK_SOURCES: the real "Stayed to watch" (%), else the jury's score (jury on), else the
    AI's selection score — "ai" (value None when the generator gave none) means not tested by the spectator."""
    stayed = _number((clip.get("stats") or {}).get("stayed"))
    if stayed is not None:
        return stayed, "stayed"
    jury = clip.get("jury")
    if JURY_ENABLED and isinstance(jury, dict) and _number(jury.get("score")) is not None:
        return _number(jury["score"]), "jury"
    return clip.get("ai_score"), "ai"


def _rank(clip):
    """(value, basis in words) for the plan's ``why``."""
    value, source = rank_score(clip)
    return value, _RANK_BASIS.get(source)


def rank_key(clip):
    """The sort key of RANK_SOURCES: the group first (a jury score is never compared with an AI score), then the
    score within the group (best first, none last), then the ref (deterministic)."""
    value, source = rank_score(clip)
    group = RANK_SOURCES.index(source) if source in RANK_SOURCES else len(RANK_SOURCES)
    return (group, -(value if value is not None else -1), clip["ref"])


_rank_key = rank_key


def _clash_phrase(alerts, item) -> str:
    """What placing ``item`` would do, in a few words, from the first alert it is part of."""
    alert = next((a for a in alerts if item["ref"] in a["refs"]), None)
    if alert is None:
        return "clash"
    kind, n = alert["kind"], len(alert["refs"])
    if kind == "same_category_in_a_row":
        return f"put {n} {item.get('category_label') or 'same-topic'} clips in a row"
    if kind == "same_guest_in_a_row":
        return f"put {n} clips with {item.get('guest') or 'the same guest'} in a row"
    if kind == "episode_per_day":
        return f"put {n} clips of {item.get('episode_label') or 'one episode'} on {_day_label(alert['date'])}"
    if kind == "category_share":
        return f"push {item.get('category_label') or 'its topic'} over {_pct(MAX_CATEGORY_SHARE, 1)}% of the week"
    if kind == "episode_share":
        return f"push {item.get('episode_label') or 'its episode'} over half the week"
    return f"push question titles over {_pct(MAX_QUESTION_SHARE, 1)}% of the week"


def _norm_slots(slots, now, occupied):
    """(slots to fill, skipped): valid, unique, in time order; a passed or already taken slot is skipped."""
    keep, skipped, seen = [], [], set()
    for s in slots or []:
        s = s if isinstance(s, dict) else {}
        day, hhmm = _iso_day(s.get("date")), _hhmm(s.get("time"))
        if not day or not hhmm:
            skipped.append({"date": s.get("date"), "time": s.get("time"), "why": "not a date and time"})
            continue
        if (day, hhmm) in seen:
            continue
        seen.add((day, hhmm))
        if _at(day, hhmm) <= now:
            skipped.append({"date": day, "time": hhmm, "why": "already passed"})
        elif (day, hhmm) in occupied:
            skipped.append({"date": day, "time": hhmm, "why": "already taken"})
        else:
            keep.append({"date": day, "time": hhmm})
    keep.sort(key=lambda s: (s["date"], s["time"]))
    return keep, skipped


def _default_slots(now, occupied):
    """The free Publish-plan times (SLOT_TIMES) from now to the end of the week."""
    out = []
    for d in range(WINDOW_DAYS):
        day = (now.date() + timedelta(days=d)).isoformat()
        for hhmm in SLOT_TIMES:
            if _at(day, hhmm) > now and (day, hhmm) not in occupied:
                out.append({"date": day, "time": hhmm})
    return out


def plan(output_dir, schedule, clips, slots=None, *, stats_dir=None, retention_seconds=None, tz=None,
         clock=None) -> dict:
    """POST /api/lineup/plan: an order for ``clips`` ([[job_id, clip_index], …]; None = every available clip, the
    tab's "Mix my week") over ``slots`` ([{date, time}],
    the week's free Publish-plan times when none), around what is already scheduled or published. Deterministic:
    slots in time order; at each one the best clip (``rank_score``: real stayed, else jury score, else AI score;
    then ref) that raises no alert, else the one that raises the least. PUBLISHES NOTHING."""
    board = _board(output_dir, schedule, stats_dir=stats_dir, retention_seconds=retention_seconds, tz=tz,
                   clock=clock)
    now, timeline = board["now"], board["timeline"]
    left_out, why_out, candidates, seen = [], {}, [], set()
    if clips is None:                                # "Mix my week": every clip still available
        clips = [(c["job_id"], c["clip_index"]) for c in board["clips"] if c["status"] == "available"]
    for pair in clips:
        try:
            job_id, index = str(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if (job_id, index) in seen:
            continue
        seen.add((job_id, index))
        clip = find_clip(board, job_id, index)
        ref = clip_ref(job_id, index)
        if clip is None:
            left_out.append(ref)
            why_out[ref] = "not on disk"
        elif clip["status"] != "available":
            left_out.append(ref)
            why_out[ref] = f"already {clip['status']}"
        else:
            candidates.append(clip)

    occupied = {(it["date"], it.get("time")) for it in timeline}
    if slots:
        todo, skipped = _norm_slots(slots, now, occupied)
    else:
        todo, skipped = _default_slots(now, occupied), []

    today = now.date()
    lo = today.isoformat()
    hi = max([(today + timedelta(days=WINDOW_DAYS - 1)).isoformat()] + [s["date"] for s in todo])
    span = ("this week" if hi == (today + timedelta(days=WINDOW_DAYS - 1)).isoformat()
            else f"from {_day_label(lo)} to {_day_label(hi)}")
    existing = [it for it in timeline if lo <= it["date"] <= hi]
    before = [it for it in timeline if it["date"] < lo]
    prev = before[-1] if before else None
    total = len(existing) + min(len(todo), len(candidates))

    remaining = sorted(candidates, key=_rank_key)
    placed, out = [], []

    def least(slot, base):
        """The smallest penalty increase any clip left would cause at ``slot``."""
        return min(evaluate(existing + placed + [_item(c, slot, "planned")], prev, total, span)[1] - base
                   for c in remaining)

    for k, slot in enumerate(todo):
        if not remaining:
            break
        _alerts, base = evaluate(existing + placed, prev, total, span)
        scored = []
        for c in remaining:
            item = _item(c, slot, "planned")
            alerts, pen = evaluate(existing + placed + [item], prev, total, span)
            scored.append((pen - base, _rank_key(c), c, item, alerts))
        scored.sort(key=lambda s: (s[0], s[1]))
        delta, _key, best, item, alerts = scored[0]
        # More slots than clips: a slot where every clip clashes (a 3rd clip of the episode that day…) is left
        # free when a later one clashes less — never when the clash is the same everywhere (a week-long share).
        later = todo[k + 1:]
        if delta > 0 and len(later) >= len(remaining) and any(least(s, base) < delta for s in later):
            skipped.append({"date": slot["date"], "time": slot["time"],
                            "why": "left free: every clip left would clash here"})
            continue
        top = min(scored, key=lambda s: s[1])
        value, basis = _rank(best)
        known = value is not None
        shown = f"{basis} {value}" if known else "no score yet"
        lead = f"Best {basis} left ({value})" if top[2] is best and known else (
            "No score yet" if top[2] is best else f"Best that keeps the mix ({shown})" if delta == 0
            else f"Least clash ({shown})")
        if delta == 0:
            why = lead if top[2] is best else f"{lead}; {top[2]['ref']} would {_clash_phrase(top[4], top[3])}"
        else:
            why = f"{lead}, though it would {_clash_phrase(alerts, item)}"
            if top[2] is not best:
                why += f"; {top[2]['ref']} clashes more"
        if JURY_ENABLED and best.get("untested"):
            # Placed only because no tested clip left fits this slot better (or none is left): say so first.
            why = f"Not tested by the spectator yet; {why[0].lower()}{why[1:]}"
        placed.append(item)
        remaining.remove(best)
        out.append({"date": slot["date"], "time": slot["time"], "job_id": best["job_id"],
                     "clip_index": best["clip_index"], "ref": best["ref"], "why": why})
    for c in remaining:
        left_out.append(c["ref"])
        why_out[c["ref"]] = "no slot left"
    final, _penalty = evaluate(existing + placed, prev, span=span)
    return {"plan": out, "alerts": final, "left_out": left_out, "left_out_why": why_out, "skipped_slots": skipped}


# --- the category, corrected by hand ----------------------------------------------------------------------------

def set_category(output_dir, job_id, clip_index, category) -> str | None:
    """Write ``category_manual`` on clip ``clip_index`` of ``job_id`` (None removes it: back to the AI's
    ``topic_bucket``). metadata.json keeps its mtime — the project's date in History and the Publish plan — and
    is written in place, so the job folder's mtime (what cleanup_jobs ages it by) does not move either. -> the
    category saved. LineupError: bad id (400), unknown category (400), unknown job or clip (404)."""
    if not safe_job_id(job_id):
        raise LineupError("Not a project id.")
    if category is not None and category not in playbook.TOPIC_BUCKETS:
        raise LineupError(f"Unknown category: {category}.")
    metas = sorted(glob.glob(os.path.join(glob.escape(os.path.join(output_dir, job_id)), "*_metadata.json")))
    if not metas:
        raise LineupError("Project not found.", 404)
    path = metas[0]
    st = os.stat(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    shorts = data.get("shorts") or []
    if not isinstance(clip_index, int) or not 0 <= clip_index < len(shorts):
        raise LineupError("Clip not found.", 404)
    if category:
        shorts[clip_index]["category_manual"] = category
    else:
        shorts[clip_index].pop("category_manual", None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    try:
        os.utime(path, (st.st_atime, st.st_mtime))
    except OSError:
        pass                     # a bind mount can refuse it (EPERM): the category is saved all the same
    return category


# --- the jury, in the background --------------------------------------------------------------------------------

_jury_lock = threading.Lock()
_jury_thread = None
_jury_run = {"running": False, "done": 0, "total": 0, "current": None, "errors": [], "already_judged": 0,
             "started_at": None, "finished_at": None}


def jury_state() -> dict:
    """jury_run (contract C2) + ``disabled`` while the jury is off (JURY_ENABLED)."""
    with _jury_lock:
        return {**_jury_run, "errors": list(_jury_run["errors"]), "disabled": not JURY_ENABLED}


def clips_to_judge(output_dir) -> list:
    """[(job_id, clip_index)] of every rendered clip on disk without an up-to-date jury note, published ones
    included (the calibration needs them)."""
    mod = jury_module()
    out = []
    for job_id, job_dir, meta_path, data in sorted(_projects(output_dir)):
        base_name = os.path.basename(meta_path)[:-len("_metadata.json")]
        for i, short in enumerate(data.get("shorts") or []):
            if isinstance(short, dict) and rendered_file(job_dir, base_name, i, short):
                if _jury_result(mod, output_dir, job_id, i) is None:
                    out.append((job_id, i))
    return out


def start_jury(output_dir, clips, force=False) -> dict:
    """Judge ``clips`` ([(job_id, clip_index)]) with hook_jury.run_many in one background thread; one run at a
    time (a second call while one runs gets its state, ``already_running``). A clip whose note is up to date (same
    rendered mp4) is never judged again, ``force`` or not (5-oct-2026, the user's rule: a clip's tokens are spent
    once): it is counted in ``already_judged``. While the jury is off (JURY_ENABLED): nothing runs, the state comes
    back with ``disabled``. LineupError 503 without hook_jury."""
    global _jury_thread
    if not JURY_ENABLED:
        return jury_state()
    mod = jury_module()
    if mod is None or not hasattr(mod, "run_many"):
        raise LineupError("The hook jury is not installed.", 503)
    asked = list(dict.fromkeys((str(j), int(i)) for j, i in clips))
    with _jury_lock:
        if _jury_run["running"]:
            return {**_jury_run, "errors": list(_jury_run["errors"]), "disabled": False, "already_running": True}
    clips = [c for c in asked if _jury_result(mod, output_dir, *c) is None]
    with _jury_lock:
        if _jury_run["running"]:
            return {**_jury_run, "errors": list(_jury_run["errors"]), "disabled": False, "already_running": True}
        _jury_run.update(running=bool(clips), done=0, total=len(clips), current=None, errors=[],
                         already_judged=len(asked) - len(clips),
                         started_at=datetime.now().isoformat(timespec="seconds"),
                         finished_at=None if clips else datetime.now().isoformat(timespec="seconds"))
    if not clips:
        return jury_state()
    _jury_thread = threading.Thread(target=_run_jury, args=(mod, output_dir, clips, False), daemon=True,
                                    name="lineup-jury")
    _jury_thread.start()
    return jury_state()


def _run_jury(mod, output_dir, clips, force):
    def progress(done, total, ref):
        with _jury_lock:
            _jury_run.update(done=int(done), total=int(total), current=ref)

    errors = []
    try:
        results = mod.run_many(output_dir, clips, progress=progress, force=force)
        for r in results or []:
            if isinstance(r, dict) and r.get("error"):
                errors.append(f"{r.get('ref') or '?'}: {str(r['error'])[:300]}")
    except Exception as e:
        errors.append(f"{type(e).__name__}: {str(e)[:300]}")
    finally:
        with _jury_lock:
            _jury_run.update(running=False, current=None, finished_at=datetime.now().isoformat(timespec="seconds"),
                             errors=_jury_run["errors"] + errors)


def wait_jury(timeout=None) -> bool:
    """Wait for the background run to end (tests, scripts). True when it has."""
    t = _jury_thread
    if t is not None:
        t.join(timeout)
        return not t.is_alive()
    return True


# --- the thumbnail ----------------------------------------------------------------------------------------------

def _clip_video(output_dir, job_id, clip_index):
    """The rendered mp4 of a clip: hook_jury.clip_video_path (the file the jury judged) when it is there, else
    the same choice made here. None when the clip or its file is gone."""
    mod = jury_module()
    if mod is not None and hasattr(mod, "clip_video_path"):
        try:
            path = mod.clip_video_path(output_dir, job_id, clip_index)
            if path and os.path.isfile(path):
                return path
        except Exception:
            pass
    job_dir = os.path.join(output_dir, job_id)
    metas = sorted(glob.glob(os.path.join(glob.escape(job_dir), "*_metadata.json")))
    if not metas:
        return None
    try:
        with open(metas[0], encoding="utf-8") as f:
            shorts = json.load(f).get("shorts") or []
    except (OSError, ValueError, AttributeError):
        return None
    if not 0 <= clip_index < len(shorts) or not isinstance(shorts[clip_index], dict):
        return None
    base_name = os.path.basename(metas[0])[:-len("_metadata.json")]
    name = rendered_file(job_dir, base_name, clip_index, shorts[clip_index])
    return os.path.join(job_dir, name) if name else None


def _inside(path, folder) -> bool:
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return os.path.commonpath([path, folder]) == folder and path != folder


def thumbnail(output_dir, job_id, clip_index) -> str | None:
    """A JPEG of the rendered clip at THUMB_AT s (the first frame when the clip is shorter), cached in
    output/_lineup/thumbs/ under the mp4's name + mtime (a re-render makes a new one, the old one is dropped).
    None when the clip has no rendered file. LineupError 400 on an id that is not a job's."""
    if not safe_job_id(job_id) or not isinstance(clip_index, int) or not 0 <= clip_index < 1000:
        raise LineupError("Not a clip.")
    job_dir = os.path.join(output_dir, job_id)
    if not os.path.isdir(job_dir) or not _inside(job_dir, output_dir):
        return None
    video = _clip_video(output_dir, job_id, clip_index)
    if not video or not os.path.isfile(video) or not _inside(video, job_dir):
        return None
    st = os.stat(video)
    key = hashlib.sha1(f"{os.path.basename(video)}|{st.st_mtime}|{st.st_size}".encode()).hexdigest()[:12]
    folder = os.path.join(output_dir, THUMB_DIR)
    stem = f"{job_id}_c{clip_index + 1:02d}"
    path = os.path.join(folder, f"{stem}_{key}.jpg")
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, f".{stem}_{key}.{os.getpid()}.{threading.get_ident()}.jpg")
    try:
        for at in (THUMB_AT, 0):
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(at), "-i", video, "-frames:v", "1",
                   "-vf", f"scale={THUMB_WIDTH}:-2", "-q:v", "4", tmp]
            try:
                subprocess.run(cmd, check=True, timeout=FFMPEG_TIMEOUT, capture_output=True)
            except (subprocess.SubprocessError, OSError):
                continue
            if os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
                break
        else:
            return None
        for old in glob.glob(os.path.join(glob.escape(folder), f"{glob.escape(stem)}_*.jpg")):
            try:
                os.remove(old)
            except OSError:
                pass
        os.replace(tmp, path)
        return path
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
