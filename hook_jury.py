"""The hook jury: would a scrolling viewer still be watching at 3 seconds? (5-oct-2026)

(5-oct-2026) Wired at the end of every Clip Generator++ job, before any calibration (the user: « Brancher tout de
suite »). What runs, and what does not yet:

1. ONE note per rendered clip, kept (the user's rule: "on n'utilise pas deux fois les tokens"). plus.SPECTATOR ->
   job_env PLUS_SPECTATOR=1 -> main.spectate_clips, right after the job's final metadata write ->
   ``spectate_job``: every rendered clip through run_one, SPECTATOR_WORKERS at a time, 1 vote (APP_VOTES), one
   "👁️ Spectator cNN: <score> (<stop>) — <verdict>" line each in the job log. The result is kept in
   output/_jury/results/<job_id>_c<NN>.json (C1) and never asked again while it is up to date — whatever the
   number of votes or the jury version; only a new rendered mp4 (another name or mtime, ``load_result``) or
   ``force=True`` re-judges. A lock file per clip keeps two runs from paying for the same clip. An AI error never
   fails the job, and the job waits at most SPECTATOR_BUDGET seconds (then: no score for the clips left). The
   dashboard only READS (``load_result``, ``load_calibration``); it never judges on opening.
2. NOT done yet (the user declined it for now): the calibration — the score is not yet checked against the real
   "Stayed to watch". To run it (backend container, app folder; the 11 published shorts are already transcribed
   in output/_jury/transcripts/):
       python hook_jury.py --output /app/output published    # the 11 published shorts of output/_jury/published/
       python hook_jury.py --output /app/output run e9e44926:10 88a7e7c1:2 88a7e7c1:3 82509f9b:1 e9e44926:8
           e9e44926:7 88a7e7c1:4 e9e44926:6 e9e44926:1 e9e44926:9 e9e44926:4 e9e44926:5      (one line; the
           clips already judged cost nothing: the calibration measures the very notes the app keeps)
                                                            # the 12 local clips of shorts_23.json (local_tag)
       python hook_jury.py --output /app/output rank         # optional: the ranking check (groups of 4)
       python hook_jury.py --output /app/output calibrate    # -> output/_jury/calibration.json
   The 23 reference shorts = those 11 published files + the 12 local clips (each checked to be the very file sent
   for publication). e9e44926_c04 and _c05 had their figure read < 48 h after publication: the age rule leaves
   them out (n = 21) and the sensitivity block puts them back. Then write the reading in
   output/_lineup/jury/calibration.md and set APP_VOTES / SCORE_MODE from the numbers (``score_mode_suggested``).
3. The out-of-sample test: b8e46c24's scores frozen on 5-oct in output/_jury/preregistered_b8e46c24.json (its
   figures come after 10-oct); compare after 48 h with a Studio export dropped in stats/.
Measured (Claude Sonnet through the subscription): one viewer vote = ~4.2k tokens read + ~0.2k written, 3-4 s;
the editor check ~1.2k tokens; a clip with 1 vote ~5.5k tokens, ~7 s; with 3 votes ~14k tokens, ~15 s.

Why: on this channel ONE number separates the shorts YouTube pushes from the ones it drops after the test pool:
"Stayed to watch" / « Ont continué de regarder » (output/_stepup/donnees/rapport.md, C1: rank correlation 0.72
with the views over 23 shorts; the same moment re-published with another opening went 47.7 % -> 77.8 %). It is
decided by what is seen, read and heard in the first seconds. This module asks a model to be that viewer.

What the juror gets is what a viewer of the Shorts feed gets, nothing more:
- frames of the FINAL rendered clip (hook and captions burned in) at 0 / 0.5 / 1 / 1.5 / 2.2 / 3 s, shrunk to
  a phone's width;
- the words said from 0 to 3 s and from 3 to 6 s AS EDITED (a re-cut clip: ``recipe.segments`` through
  ``recut.virtual_transcript``; otherwise the source transcript from ``start``);
- the hook text.
It knows nothing of the episode, the guest, the title, nor the real numbers (blind: the calibration below would
mean nothing otherwise). Its rules are the PRINCIPLES of the step-up reports (rapport C2-C4, accroche C2-C3 and
ideas 1/5, recit C3), never examples taken from the shorts it is calibrated on.

Three passes, all through ai_brain (the Claude subscription; Gemini when Claude cannot and a key is at hand):
1. the viewer, alone with one clip, N votes (``APP_VOTES``): a 0-100 chance to stay past 3 s, the C1 criteria,
   "stop" (yes / maybe / no), "feeling", a verdict and a fix. The votes differ by one line in the prompt so the AI
   cache keeps each one (asking three times the same question would read back the same answer);
2. the editor, text only, with the whole clip as edited: is the hook true to the clip (``hook_true``), does it
   give the ending away (``no_spoiler``), and where a cleaner opening sentence starts;
3. the ranking check (``rank``): the viewer sees the openings of 4 clips together and orders them; pairwise wins
   become ``rank_check`` {"wins", "games", "rank_score"}.

``calibrate`` measures the scores against the real "Stayed to watch" of the published shorts and writes
output/_jury/calibration.json (the C1 format); ``preregister`` freezes the scores of a job not yet measured
(the only out-of-sample test).

    python hook_jury.py run [--all | JOB:N ...] [--force] [--votes N] [--workers K]
    python hook_jury.py published [--force]        # the published shorts kept in output/_jury/published/
    python hook_jury.py rank [--force]             # the ranking check over every clip judged
    python hook_jury.py calibrate
    python hook_jury.py preregister [JOB] [--force]

The dashboard (lineup.py) only calls: load_result, load_calibration, run_one, run_many, clip_video_path.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

# --- what the jury is -----------------------------------------------------------------------------------------
VERSION = "jury-v1"
MODEL = "sonnet"                      # the Claude model; ai_brain falls back to Gemini when Claude cannot run
STAGE = "spectator"                   # the dashboard's "🧠 [Claude · sonnet] spectator" line during a job
CALL_TIMEOUT = 120                    # one call never holds a job's end longer (the measured call: 3-8 s)
# At the end of a Clip Generator++ job (main.spectate_clips, plus.SPECTATOR): clips judged SPECTATOR_WORKERS at a
# time, and the job waits at most SPECTATOR_BUDGET seconds for them — a clip still being judged then is left
# without a score (the dashboard can judge it later), never a failed or late job.
SPECTATOR_WORKERS = 4
SPECTATOR_BUDGET = 150
# A clip being judged holds a lock file next to its result: another run (the dashboard's background pass, a
# second process) skips it instead of paying for the same clip twice. Older than this, a lock is a crashed run's.
LOCK_STALE = 15 * 60
# The viewer is not an editor: ai_brain's default system prompt ("a senior short-form video editor") would
# frame every answer as a professional's (5-oct-2026).
SYSTEM_VIEWER = ("You play the viewer described in the request, honestly, without politeness. The images are "
                 "attached to the request, in order, each right after its file name. Answer only with the "
                 "requested JSON.")
# What the viewer sees: the frames of the first 3 s, at a phone's width (390 px = an iPhone's CSS width; the
# accroche report measured the hook at that size: 14 px capitals).
FRAME_TIMES = (0.0, 0.5, 1.0, 1.5, 2.2, 3.0)
PHONE_WIDTH = 390
WORD_WINDOWS = ((0.0, 3.0), (3.0, 6.0))
# Votes per clip in the app. Provisional (5-oct-2026), from the 14 clips judged 3 times before the pass was
# stopped: one vote ranks the clips like another vote does (test-retest Spearman 0.94), a vote is 2.5 points from
# the median on average (median spread 4, worst 23): 1 vote, 2.6 times cheaper (``--votes 3`` re-measures it).
APP_VOTES = 1
# The calibration measures what the app shows: the same number of votes.
CALIBRATION_VOTES = APP_VOTES
# The ranking check: groups of RANK_GROUP openings (RANK_FRAMES each, fewer than alone so a group costs about one
# solo call), every clip in RANK_ROUNDS groups with other opponents -> (RANK_GROUP - 1) * RANK_ROUNDS games.
RANK_GROUP = 4
RANK_FRAMES = (0.0, 1.0, 2.2)
RANK_ROUNDS = 3
RANK_SEED = 20261005
# Which number is ``score``: "solo" (median of the votes), "ranked" (the ranking check's win rate) or "blend"
# (their mean). Set from the calibration (5-oct-2026, calibration.md): the simplest one unless another is clearly
# better on the real numbers (SCORE_MODE_MIN_GAIN of Spearman).
SCORE_MODE = "solo"
SCORE_MODES = ("solo", "ranked", "blend")
SCORE_MODE_MIN_GAIN = 0.10

# --- calibration ----------------------------------------------------------------------------------------------
# "Stayed to watch" settles once the test pool is done; a figure read younger says little ("un chiffre à 3 h
# ne vaut rien"): only shorts at least this old when their figure was read.
MIN_AGE_HOURS = 48
MIN_CALIBRATION = 8                    # below: "too_few"
# reading of the Spearman correlation: (name, minimum rho, maximum two-sided permutation p). With n ~ 20, rho 0.6
# is where chance gives p < 0.01 and 0.4 where it gives p ~ 0.08: "strong" asks for both a large effect and p <=
# 0.05, "moderate" a useful one (a better short ranked above a worse one ~ 2 times in 3) with p <= 0.15; anything
# else, negative included, is "weak".
READINGS = (("strong", 0.6, 0.05), ("moderate", 0.4, 0.15))
CALIBRATION_EXCLUDE = {
    "b8e46c24_c05": "0 views: YouTube never showed it, its stayed-to-watch says nothing about the opening",
}
# The hand-read Studio figures of the 23 first shorts (04/10/2026 ~21 h, read only) and where they are.
SHORTS_FILE = os.path.join("_stepup", "donnees", "shorts_23.json")
STUDIO_RAW_FILE = os.path.join("_stepup", "donnees", "studio_raw.json")
STUDIO_READ_AT = "2026-10-04T21:00:00+02:00"   # studio_raw.json "_note": « le 04/10/2026 vers 21 h »
# The same moment published twice (tableau.md C): (version 1, version 2) YouTube ids, to see if the jury prefers
# the version the viewers preferred. Used only to report, never shown to the jury.
SAME_MOMENT_PAIRS = (("oE5v5OBVxAU", "CeWu-DMt838"), ("HdPGfq-MdZw", "YQ36UAqW66M"),
                     ("gDPFFxA5yPw", "AfYZc_rxCgU"), ("iiTNieJon3I", "gQ8cV2WJ-D0"))
PREREGISTER_JOB = "b8e46c24"

JURY_DIR = "_jury"
CRITERIA = ("stands_alone", "topic_named", "tension", "hook_matches_voice", "first_frame_clear", "no_spoiler")
VIEWER_CRITERIA = CRITERIA[:5]        # no_spoiler needs the whole clip: the editor pass answers it
STOPS = ("no", "maybe", "yes")

# --- the prompts (principles only: no example from a calibration short, 5-oct-2026) -------------------------------
VIEWER = """You are scrolling YouTube Shorts on your phone, sound on. You hear the voice, you read the captions,
you see the picture. You are curious about science, health, the mind and psychedelics, not a specialist. You know
NOTHING about this podcast, this episode, the people talking, the context, or what the editors wanted to do. Any
intention you might guess does not count: only what you see, read and hear. You decide in one to three seconds
whether you keep watching or swipe to the next video."""

PRINCIPLES = """How a viewer like you decides (judge by these, honestly; do not be polite):
1. The first sentence you hear must make sense on its own. A start in the middle of a sentence, on a connector
   ("also", "so", "and", "like", "well", "I mean"), on a pronoun whose person or thing you never heard ("they",
   "that", "it", "he", "these"), on a preamble, or on someone talking to the studio crew, feels like walking into
   the middle of a conversation.
2. Within about 5 seconds you must know what this is about: the subject is named, by the voice or the on-screen
   text.
3. Within about 5 seconds there must be a stake: an open question, a danger to you or to a person you can picture,
   a surprise, a conflict. Information without a stake does not hold you.
4. Your eye and your ear should get ONE message: the on-screen hook says the same thing as the voice, or names
   who or what the voice's "they / it / that" is. Reading one thing while hearing another makes you choose, and
   you swipe.
5. The first frame must read in a split second at phone size: a sharp face or a clear picture, text big enough to
   read. Someone who is only listening, a dark or busy frame, or text too small to read wastes that first second.
6. A hook that already tells how it ends closes the question: nothing is left to stay for."""

SOLO_TASK = """Answer as this viewer, about THIS clip only:
- topic_guess: what you think this video is about after these seconds, in a few words ("no idea" if you cannot
  tell).
- hook_read: the text written on screen as the hook (the headline over the picture, not the captions), word for
  word as you read it on the frames, or null if there is none or you cannot read it.
- stands_alone, topic_named, tension, hook_matches_voice, first_frame_clear: true or false for principles 1 to 5
  (null only if you truly cannot tell, e.g. no hook at all for hook_matches_voice).
- stop: "yes", "maybe" or "no": do you stop scrolling?
- feeling: one short line, first person: what it does to you (curiosity, a chill, unease, a laugh, confusion,
  nothing...).
- score: your honest estimate, 0 to 100, of the chance that a viewer like you is still watching at 3 seconds. On
  the Shorts feed roughly 40 to 80 viewers out of 100 stay past the first seconds and 60 is an ordinary opening;
  use the whole range.
- verdict: ONE simple sentence in plain English for the editor: why you stay or why you swipe.
- fix: ONE concrete change to the opening that would make you stay (a later start, a hook that names the subject,
  a clearer first frame...), or null if nothing needs fixing."""

TRUTH_TASK = """You are an editor checking a short vertical video before it is published. Below: the hook line written
on screen over its first seconds, and everything the video says, as edited, with the second each line starts.

Answer:
- hook_true: does the video deliver what the hook says? false if the hook states a fact the video never says
  (a number, a cause, a method, a comparison, an outcome) or promises something the video does not deliver;
  true otherwise; null if there is no hook.
- hook_problem: when hook_true is false, one plain English sentence saying what is wrong; else null.
- true_hook: when hook_true is false, a hook of at most 7 words that is true to the video and keeps the question
  open; else null.
- no_spoiler: false if the hook already tells how the story ends or gives the answer the video builds up to;
  true otherwise; null if there is no hook.
- better_start: if the video's FIRST sentence does not make sense on its own (it starts mid-sentence, on a
  connector, on a pronoun whose person or thing was not named, on a preamble or an aside to the crew) or does not
  name the subject, quote word for word the first 4 to 8 words of the earliest LATER sentence that would stand
  alone, name the subject and open a question; else null."""

RANK_TASK = """These {n} Shorts come up one after the other in your feed: {labels}. For each one you get the frames at
{times} s (files "<letter>_t<seconds>s.jpg"), the words heard in its first 3 seconds and its on-screen hook.

Order them from the one you would most likely keep watching to the one you would swipe away first. Judge only the
openings, as this viewer, by the principles above.
- order: the letters, best first (every letter exactly once).
- why: one short line on what separates the first from the last."""

SOLO_SCHEMA = {
    "type": "object",
    "properties": {
        "topic_guess": {"type": "string"},
        "hook_read": {"type": ["string", "null"]},
        **{k: {"type": ["boolean", "null"]} for k in VIEWER_CRITERIA},
        "stop": {"type": "string", "enum": list(STOPS)},
        "feeling": {"type": "string"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "verdict": {"type": "string"},
        "fix": {"type": ["string", "null"]},
    },
    "required": ["topic_guess", "hook_read", *VIEWER_CRITERIA, "stop", "feeling", "score", "verdict", "fix"],
}
TRUTH_SCHEMA = {
    "type": "object",
    "properties": {
        "hook_true": {"type": ["boolean", "null"]},
        "hook_problem": {"type": ["string", "null"]},
        "true_hook": {"type": ["string", "null"]},
        "no_spoiler": {"type": ["boolean", "null"]},
        "better_start": {"type": ["string", "null"]},
    },
    "required": ["hook_true", "hook_problem", "true_hook", "no_spoiler", "better_start"],
}
RANK_SCHEMA = {
    "type": "object",
    "properties": {"order": {"type": "array", "items": {"type": "string"}}, "why": {"type": "string"}},
    "required": ["order", "why"],
}


# --- paths ------------------------------------------------------------------------------------------------------

def jury_dir(output_dir):
    return os.path.join(output_dir, JURY_DIR)


def ref_of(job_id, clip_index):
    return f"{str(job_id)[:8]}_c{int(clip_index) + 1:02d}"


def result_path(output_dir, job_id, clip_index):
    return os.path.join(jury_dir(output_dir), "results", f"{job_id}_c{int(clip_index) + 1:02d}.json")


def _published_result_path(output_dir, video_id):
    return os.path.join(jury_dir(output_dir), "calibration_clips", f"{video_id}.json")


def _write_json(path, data):
    """Atomic: the dashboard may read while a background run writes."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _job_dir(output_dir, job_id):
    """The job's folder: exact id, else the only folder starting with it (the CLI takes 'b8e46c24')."""
    job_id = str(job_id or "")
    if not job_id or job_id.startswith(("_", ".")) or "/" in job_id or "\\" in job_id:
        return None
    exact = os.path.join(output_dir, job_id)
    if os.path.isdir(exact):
        return exact
    found = [p for p in glob.glob(os.path.join(glob.escape(output_dir), glob.escape(job_id) + "*"))
             if os.path.isdir(p) and not os.path.basename(p).startswith("_")]
    return found[0] if len(found) == 1 else None


def _metadata(job_dir):
    """(path, data) of the job's *_metadata.json, (None, None) when there is none."""
    if not job_dir:
        return None, None
    for path in sorted(glob.glob(os.path.join(glob.escape(job_dir), "*_metadata.json"))):
        data = _read_json(path)
        if isinstance(data, dict):
            return path, data
    return None, None


def clip_video_path(output_dir, job_id, clip_index):
    """The final rendered mp4 of a clip (hook and captions burned in): the file the clip's metadata points to
    (``video_url``, what the dashboard plays and publishes), else the newest derived file
    (subtitled_ / recut_ / hooked_ / hook_, like app._canonical_clip_file), else the bare clip. None when the
    clip was never rendered (a .pre_fx file is not a final clip)."""
    job_dir = _job_dir(output_dir, job_id)
    meta_path, meta = _metadata(job_dir)
    if not meta:
        return None
    shorts = meta.get("shorts") or []
    try:
        clip_index = int(clip_index)
        short = shorts[clip_index] if clip_index >= 0 else None
    except (TypeError, ValueError, IndexError):
        return None
    if not isinstance(short, dict):
        return None
    name = os.path.basename(str(short.get("video_url") or ""))
    if name and os.path.isfile(os.path.join(job_dir, name)):
        return os.path.join(job_dir, name)
    base = os.path.basename(meta_path)[:-len("_metadata.json")]
    clean = f"{base}_clip_{clip_index + 1}.mp4"
    derived = []
    for pattern in (f"subtitled_*_{clean}", f"recut_*_{clean}", f"hooked_*_{clean}", f"hook_{clean}"):
        derived += glob.glob(os.path.join(glob.escape(job_dir), glob.escape(pattern).replace(r"[*]", "*")))
    if derived:
        return max(derived, key=os.path.getmtime)
    path = os.path.join(job_dir, clean)
    return path if os.path.isfile(path) else None


def _mtime(path):
    try:
        return round(os.path.getmtime(path), 3)
    except OSError:
        return None


def load_result(output_dir, job_id, clip_index):
    """The jury's result for a clip (C1), or None when there is none or it is stale: the rendered mp4 it judged
    is not the clip's current one any more (another name, or the same name re-written)."""
    data = _read_json(result_path(output_dir, job_id, clip_index))
    if not isinstance(data, dict):
        return None
    path = clip_video_path(output_dir, job_id, clip_index)
    if not path or os.path.basename(path) != data.get("clip_file"):
        return None
    mtime = _mtime(path)
    try:
        if mtime is None or abs(float(data.get("clip_mtime")) - mtime) > 0.01:
            return None
    except (TypeError, ValueError):
        return None
    return data


def load_calibration(output_dir):
    """output/_jury/calibration.json: {"version", "at", "n", "spearman", "p", "reading", "rows", "note", ...},
    or None."""
    data = _read_json(os.path.join(jury_dir(output_dir), "calibration.json"))
    return data if isinstance(data, dict) else None


# --- what the viewer hears --------------------------------------------------------------------------------------

def _words_of(transcript):
    import recut
    return recut.transcript_words(transcript)


def clip_words(transcript, short):
    """The words of the clip AS EDITED, on the clip's timeline ([{"w", "s", "e"}], t=0 = first frame): through the
    EDL when the clip was re-cut (montage / editor: ``recipe.segments``), else the source words from ``start``."""
    segments = ((short.get("recipe") or {}).get("segments")) or []
    if segments:
        import recut
        return _words_of(recut.virtual_transcript(transcript, segments))
    try:
        start, end = float(short["start"]), float(short["end"])
    except (KeyError, TypeError, ValueError):
        return []
    out = []
    for w in _words_of(transcript):
        if w["e"] <= start + 0.05 or w["s"] >= end - 0.05:
            continue
        out.append({"w": w["w"], "s": round(w["s"] - start, 3), "e": round(w["e"] - start, 3)})
    return out


def window_text(words, a, b):
    """The words starting in [a, b) — a word already under way at 0 belongs to the first window."""
    picked = [w["w"] for w in words if (w["s"] >= a or (a <= 0 and w["e"] > 0.05)) and w["s"] < b]
    return " ".join(x for x in picked if x).strip()


def transcript_lines(words, max_words=28):
    """The clip's words as lines "[12.3s] sentence", cut on sentence ends (the editor reads timings)."""
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.?!]['\"”)]*$", w["w"]) or len(cur) >= max_words:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return [f"[{max(0.0, ln[0]['s']):.1f}s] " + " ".join(w["w"] for w in ln) for ln in lines]


def _norm_words(text):
    return re.findall(r"[a-z0-9']+", str(text or "").lower().replace("’", "'"))


def find_phrase(words, phrase):
    """The clip second where ``phrase`` (a quote of the clip) starts, None when it is not said."""
    target = _norm_words(phrase)
    if not target:
        return None
    flat = []
    for w in words:
        for tok in _norm_words(w["w"]):
            flat.append((tok, w["s"]))
    toks = [t for t, _ in flat]
    n = min(len(target), 5)               # the first 5 words decide: a quote may stop mid-sentence
    for i in range(len(toks) - n + 1):
        if toks[i:i + n] == target[:n]:
            return flat[i][1]
    return None


# --- clips --------------------------------------------------------------------------------------------------

def clip_subject(output_dir, job_id, clip_index):
    """Everything the jury needs about one app clip."""
    job_dir = _job_dir(output_dir, job_id)
    _meta_path, meta = _metadata(job_dir)
    if not meta:
        raise FileNotFoundError(f"no metadata for job {job_id}")
    job_id = os.path.basename(job_dir)
    shorts = meta.get("shorts") or []
    if not 0 <= int(clip_index) < len(shorts):
        raise IndexError(f"{ref_of(job_id, clip_index)}: the job has {len(shorts)} clips")
    short = shorts[int(clip_index)]
    video = clip_video_path(output_dir, job_id, clip_index)
    if not video:
        raise FileNotFoundError(f"{ref_of(job_id, clip_index)}: no rendered clip on disk")
    hook = ((short.get("auto_hook") or {}).get("text") or short.get("viral_hook_text") or "").strip() or None
    return {"kind": "clip", "job_id": job_id, "clip_index": int(clip_index), "ref": ref_of(job_id, clip_index),
            "video": video, "hook": hook, "words": clip_words(meta.get("transcript") or {}, short)}


def published_subject(output_dir, video_id, transcribe=None):
    """A short kept only as its published file (output/_jury/published/<youtube id>.mp4): no metadata, so its
    words come from a transcription of the file (kept in _jury/transcripts/) and its hook is read on the frames."""
    video = os.path.join(jury_dir(output_dir), "published", f"{video_id}.mp4")
    if not os.path.isfile(video):
        raise FileNotFoundError(f"{video_id}: no published file")
    cache = os.path.join(jury_dir(output_dir), "transcripts", f"{video_id}.json")
    transcript = _read_json(cache)
    if not (isinstance(transcript, dict) and transcript.get("segments")):
        transcript = (transcribe or transcribe_file)(video)
        _write_json(cache, transcript)
    return {"kind": "published", "video_id": video_id, "ref": video_id, "video": video, "hook": None,
            "words": _words_of(transcript)}


def transcribe_file(path):
    """The app's own Whisper (transcribe_backends, the model already in the container's cache; offline so a
    missing model fails instead of downloading)."""
    import ai_brain  # noqa: F401  (loads .env: WHISPER_MODEL / DEVICE / COMPUTE)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import transcribe_backends
    return transcribe_backends.transcribe_media(path)


# --- frames -------------------------------------------------------------------------------------------------

def extract_frames(video, times, out_dir, width=PHONE_WIDTH, prefix=""):
    """JPEGs of ``video`` at ``times`` (s), ``width`` px wide; a time past the end is skipped. Same input, same
    bytes: the AI cache recognises a question already asked."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for t in times:
        out = os.path.join(out_dir, f"{prefix}t{t:.1f}s.jpg")
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
               "-vf", f"scale={int(width)}:-2", "-q:v", "3", out]
        subprocess.run(cmd, capture_output=True, timeout=60)
        if os.path.isfile(out) and os.path.getsize(out) > 0:
            paths.append(out)
    return paths


# --- the model calls ----------------------------------------------------------------------------------------

def _gemini_fallback(prompt, schema, attach):
    """Gemini with the same images, when a key is at hand (ai_brain caches its answers too)."""
    def call():
        import ai_brain
        from google.genai import types
        parts = []
        for p in attach or []:
            parts.append(f'Image "{os.path.basename(p)}":')
            with open(p, "rb") as f:
                parts.append(types.Part.from_bytes(data=f.read(), mime_type="image/jpeg"))
        parts.append(prompt + "\n\nAnswer with ONE JSON object and nothing else, following this JSON schema:\n"
                     + json.dumps(schema, separators=(",", ":")))
        data, _ = ai_brain.gemini_json(parts)
        return data
    return call


def _ask(prompt, schema, attach=None, system=None):
    """One jury call -> (answer, who, cost {"seconds", "input_tokens", "output_tokens", "calls"}). The tokens are
    ai_brain's count of this call (LAST_USAGE): exact one clip at a time, approximate when clips are judged in
    parallel threads (spectate_job) — the job's own total (ai_brain.USAGE) stays exact."""
    import ai_brain
    t0 = time.time()
    ai_brain.LAST_USAGE = None
    fallback = _gemini_fallback(prompt, schema, attach) if os.environ.get("GEMINI_API_KEY") else None
    data, who = ai_brain.think(STAGE, prompt, schema, fallback=fallback, attach=attach, route_key="hook",
                               brain=MODEL, system=system, timeout=CALL_TIMEOUT)
    used = ai_brain.LAST_USAGE or {}
    cost = {"seconds": round(time.time() - t0, 1), "input_tokens": int(used.get("input_tokens") or 0),
            "output_tokens": int(used.get("output_tokens") or 0), "calls": 1}
    return data, (MODEL if who == "claude" else "gemini"), cost


def _add_cost(total, cost):
    for k, v in (cost or {}).items():
        total[k] = round(total.get(k, 0) + v, 1) if k == "seconds" else total.get(k, 0) + v
    return total


def _frame_times(frame_names):
    out = []
    for n in frame_names:
        m = re.search(r"t([\d.]+)s\.jpg$", n)
        if m:
            out.append(m.group(1))
    return out


def solo_prompt(subject, frame_names, vote):
    words = subject.get("words") or []
    first = next((w["s"] for w in words), None)
    lines = [VIEWER, "",
             f"The {len(frame_names)} images are your phone screen at " + ", ".join(_frame_times(frame_names))
             + " s (the on-screen hook and the captions are part of the picture): " + ", ".join(frame_names) + ".",
             f'Words you hear from 0 to 3 s: "{window_text(words, *WORD_WINDOWS[0]) or "(nothing)"}"',
             f'Words you hear from 3 to 6 s: "{window_text(words, *WORD_WINDOWS[1]) or "(nothing)"}"']
    if first is not None and first > 0.3:
        lines.append(f"(The voice starts at {first:.1f} s.)")
    hook = subject.get("hook")
    lines.append(f'On-screen hook: "{hook}"' if hook else
                 "On-screen hook: not given as text; read it on the frames if there is one.")
    lines += ["", PRINCIPLES, "", SOLO_TASK]
    if vote > 1:
        # A second opinion must be a NEW question for the AI cache (5-oct-2026): same clip, same rules.
        lines.append(f"\n(Independent vote {vote} of the panel: judge afresh, as if this clip came up for the first "
                     "time.)")
    return "\n".join(lines)


def truth_prompt(hook, words):
    return "\n".join([TRUTH_TASK, "", f'Hook on screen: "{hook}"' if hook else "Hook on screen: (none)", "",
                      "What the video says:", *transcript_lines(words)])


def _bool(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "yes"):
        return True
    if isinstance(v, str) and v.strip().lower() in ("false", "no"):
        return False
    return None


def _text(v, limit=400):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return None if s.lower() in ("", "null", "none", "n/a") else s[:limit]


def clean_vote(data):
    """One viewer answer, typed and bounded."""
    data = data if isinstance(data, dict) else {}
    try:
        score = int(round(float(data.get("score"))))
    except (TypeError, ValueError):
        score = None
    stop = str(data.get("stop") or "").strip().lower()
    return {"score": None if score is None else max(0, min(100, score)),
            **{k: _bool(data.get(k)) for k in VIEWER_CRITERIA},
            "stop": stop if stop in STOPS else None,
            "feeling": _text(data.get("feeling"), 200), "verdict": _text(data.get("verdict"), 300),
            "fix": _text(data.get("fix"), 300), "topic_guess": _text(data.get("topic_guess"), 120),
            "hook_read": _text(data.get("hook_read"), 160)}


def majority(values):
    """True / False when more than half of the votes say so, else None (one vote: itself)."""
    vals = [v for v in values]
    yes, no = sum(v is True for v in vals), sum(v is False for v in vals)
    if yes * 2 > len(vals):
        return True
    if no * 2 > len(vals):
        return False
    return None


def median_int(values):
    vals = [v for v in values if v is not None]
    return int(round(statistics.median(vals))) if vals else None


def combine_votes(votes):
    """The panel's answer: median score, majority criteria, and the words of the median juror."""
    votes = [v for v in votes if v.get("score") is not None]
    if not votes:
        raise ValueError("no usable vote")
    scores = [v["score"] for v in votes]
    med = median_int(scores)
    mid = min(range(len(votes)), key=lambda i: (abs(votes[i]["score"] - med), i))
    stops = [STOPS.index(v["stop"]) for v in votes if v.get("stop") in STOPS]
    counts = {s: stops.count(s) for s in set(stops)}
    best = max(counts.values()) if counts else 0
    tied = sorted(s for s, c in counts.items() if c == best)
    stop = STOPS[tied[len(tied) // 2]] if tied else None
    return {"score": med, "votes": scores, "spread": max(scores) - min(scores),
            "criteria": {k: majority([v.get(k) for v in votes]) for k in VIEWER_CRITERIA},
            "stop": stop, "feeling": votes[mid].get("feeling"), "verdict": votes[mid].get("verdict"),
            "fix": votes[mid].get("fix"), "topic_guess": votes[mid].get("topic_guess"),
            "hook_read": next((v["hook_read"] for v in votes if v.get("hook_read")), None)}


def clean_truth(data, words):
    data = data if isinstance(data, dict) else {}
    out = {"hook_true": _bool(data.get("hook_true")), "hook_problem": _text(data.get("hook_problem"), 300),
           "true_hook": _text(data.get("true_hook"), 80), "no_spoiler": _bool(data.get("no_spoiler")),
           "better_start": _text(data.get("better_start"), 120), "better_start_at": None}
    if out["better_start"]:
        at = find_phrase(words, out["better_start"])
        if at is None or at < 1.0:             # not said in the clip (or it IS the opening): dropped, never invented
            out["better_start"] = None
        else:
            out["better_start_at"] = round(at, 1)
    return out


def compose_fix(panel, truth):
    """The one proposal the dashboard shows: a false hook first, then an opening that does not stand alone or
    name its subject (with the clip's own later sentence), else the viewer's own fix."""
    truth = truth or {}
    if truth.get("hook_true") is False and truth.get("true_hook"):
        why = f" ({truth['hook_problem']})" if truth.get("hook_problem") else ""
        return f"Hook not true to the clip: try “{truth['true_hook']}”{why}"
    crit = panel.get("criteria") or {}
    if truth.get("better_start") and (crit.get("stands_alone") is False or crit.get("topic_named") is False):
        return f"Start at “{truth['better_start']}…” ({truth['better_start_at']:.0f} s in)"
    return panel.get("fix")


def judge(subject, votes=APP_VOTES, frames_dir=None):
    """Run the viewer (``votes`` times) and the editor on one subject -> the jury's fields (no file written)."""
    tmp = frames_dir or tempfile.mkdtemp(prefix="jury_")
    try:
        frames = extract_frames(subject["video"], FRAME_TIMES, tmp)
        if not frames:
            raise RuntimeError(f"{subject['ref']}: no frame could be read from {os.path.basename(subject['video'])}")
        names = [os.path.basename(p) for p in frames]
        cost, raw, models = {}, [], set()
        for k in range(1, max(1, int(votes)) + 1):
            data, who, c = _ask(solo_prompt(subject, names, k), SOLO_SCHEMA, attach=frames, system=SYSTEM_VIEWER)
            raw.append(clean_vote(data))
            models.add(who)
            _add_cost(cost, c)
        panel = combine_votes(raw)
        hook = subject.get("hook") or panel.get("hook_read")
        truth = None
        if subject.get("words"):
            data, who, c = _ask(truth_prompt(hook, subject["words"]), TRUTH_SCHEMA)
            truth = clean_truth(data, subject["words"])
            models.add(who)
            _add_cost(cost, c)
    finally:
        if frames_dir is None:
            shutil.rmtree(tmp, ignore_errors=True)
    criteria = dict(panel["criteria"])
    criteria["no_spoiler"] = truth.get("no_spoiler") if truth else None
    return {"score_solo": panel["score"], "votes": panel["votes"], "spread": panel["spread"],
            "criteria": criteria, "hook_true": truth.get("hook_true") if truth else None,
            "stop": panel["stop"], "feeling": panel["feeling"], "verdict": panel["verdict"],
            "fix": compose_fix(panel, truth), "fix_viewer": panel["fix"], "topic_guess": panel["topic_guess"],
            "hook": hook, "hook_read": panel["hook_read"], "hook_problem": truth.get("hook_problem") if truth else None,
            "true_hook": truth.get("true_hook") if truth else None,
            "better_start": truth.get("better_start") if truth else None,
            "better_start_at": truth.get("better_start_at") if truth else None,
            "votes_detail": raw, "model": "+".join(sorted(models)), "cost": cost}


def final_score(score_solo, rank_check, mode=None):
    """``score`` from the solo note and the ranking check, by SCORE_MODE (solo when there is no ranking)."""
    mode = mode or SCORE_MODE
    rank = (rank_check or {}).get("rank_score")
    if mode == "ranked" and rank is not None:
        return int(rank)
    if mode == "blend" and rank is not None and score_solo is not None:
        return int(round((score_solo + rank) / 2))
    return score_solo


def _now():
    return datetime.now().replace(microsecond=0).isoformat()


def run_one(output_dir, job_id, clip_index, force=False, votes=None):
    """Judge one clip and write output/_jury/results/<job_id>_c<NN>.json (C1). A clip is judged ONCE: while its
    result is up to date (same rendered mp4: name + mtime, ``load_result``) it is returned with no model call,
    whatever ``votes`` or the jury version — only ``force`` asks again (5-oct-2026, the user's rule)."""
    votes = int(votes or APP_VOTES)
    subject = clip_subject(output_dir, job_id, clip_index)
    old = load_result(output_dir, subject["job_id"], clip_index)
    if old and not force:
        return old
    path = result_path(output_dir, subject["job_id"], clip_index)
    with _clip_lock(path, subject["ref"]):
        fresh = None if force else load_result(output_dir, subject["job_id"], clip_index)
        if fresh:
            return fresh                              # another run judged it in the meantime
        fields = judge(subject, votes=votes)
        rank_check = (old or {}).get("rank_check") if old else None   # same mp4: the ranking still holds
        result = {"job_id": subject["job_id"], "clip_index": int(clip_index), "ref": subject["ref"],
                  "clip_file": os.path.basename(subject["video"]), "clip_mtime": _mtime(subject["video"]),
                  "version": VERSION, "model": fields.pop("model"), "at": _now(),
                  "score": final_score(fields["score_solo"], rank_check), **fields, "rank_check": rank_check}
        _write_json(path, result)
    return result


class JuryBusy(RuntimeError):
    """Another run is judging this clip right now."""


class _clip_lock:
    """``<result>.lock``, created exclusively: a second run on the same clip raises JuryBusy (a lock older than
    LOCK_STALE is a crashed run's and is taken over)."""

    def __init__(self, result_file, ref):
        self.path, self.ref = result_file + ".lock", ref

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {_now()}".encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > LOCK_STALE:
                        os.remove(self.path)
                        continue
                except OSError:
                    continue
                raise JuryBusy(f"{self.ref} is being judged by another run")
        raise JuryBusy(f"{self.ref}: could not take the lock")

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass
        return False


def run_many(output_dir, clips, progress=None, force=False, votes=None):
    """Judge ``clips`` [(job_id, clip_index)], one after the other. ``progress(done, total, ref)`` after each.
    A clip already judged (up-to-date result) costs nothing: its kept result is returned. A clip that fails does
    not stop the others: its entry is {"job_id", "clip_index", "ref", "error"}."""
    clips = list(clips or [])
    out = []
    for n, (job_id, clip_index) in enumerate(clips, 1):
        ref = ref_of(job_id, clip_index)
        try:
            out.append(run_one(output_dir, job_id, clip_index, force=force, votes=votes))
        except Exception as e:                                     # noqa: BLE001 — reported, never fatal
            out.append({"job_id": job_id, "clip_index": clip_index, "ref": ref, "error": str(e)[:300]})
        if progress:
            try:
                progress(n, len(clips), ref)
            except Exception:                                      # noqa: BLE001
                pass
    return out


def spectate_line(result):
    """The job log's line for one clip: "👁️ Spectator c03: 52 (maybe) — <verdict>"."""
    num = f"c{int(result.get('clip_index', 0)) + 1:02d}"
    if result.get("error"):
        return f"   👁️ Spectator {num}: no score ({result['error'][:160]})"
    verdict = result.get("verdict") or ""
    flag = " ⚠️ hook not true to the clip" if result.get("hook_true") is False else ""
    return f"   👁️ Spectator {num}: {result.get('score')} ({result.get('stop') or '?'}) — {verdict}{flag}"


def spectate_job(job_dir, workers=SPECTATOR_WORKERS, budget=SPECTATOR_BUDGET, log=print):
    """The spectator at the end of a generator job (main.spectate_clips): every rendered clip of ``job_dir``
    judged once (run_one: a clip with an up-to-date result costs nothing), ``workers`` at a time, one log line
    each. The job waits at most ``budget`` seconds: the threads are daemons, so a clip still being judged then is
    simply left without a score. Never raises. Returns [result or {"ref", "error"}]."""
    t0 = time.time()
    try:
        output_dir, job_id = os.path.dirname(os.path.abspath(job_dir)), os.path.basename(os.path.abspath(job_dir))
        _p, meta = _metadata(job_dir)
        todo = [(job_id, i) for i in range(len((meta or {}).get("shorts") or []))
                if clip_video_path(output_dir, job_id, i)]
    except Exception as e:                                         # noqa: BLE001
        log(f"   👁️ Spectator: skipped ({str(e)[:160]})")
        return []
    if not todo:
        return []
    import queue
    import threading
    pending, done = queue.Queue(), []
    for item in todo:
        pending.put(item)
    lock = threading.Lock()

    def worker():
        while True:
            try:
                jid, i = pending.get_nowait()
            except queue.Empty:
                return
            res = run_many(output_dir, [(jid, i)])[0]
            with lock:
                done.append(res)
                log(spectate_line(res))

    threads = [threading.Thread(target=worker, daemon=True, name=f"spectator-{k}")
               for k in range(max(1, min(int(workers), len(todo))))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.0, budget - (time.time() - t0)))
    with lock:
        results = list(done)
    scored = [r for r in results if not r.get("error")]
    left = len(todo) - len(results)
    msg = f"   👁️ Spectator: {len(scored)}/{len(todo)} clips scored in {time.time() - t0:.0f}s"
    if left:
        msg += f" — stopped waiting after {budget}s, {left} left without a score (the dashboard can judge them)"
    log(msg)
    return results


def run_published(output_dir, video_id, force=False, votes=CALIBRATION_VOTES, transcribe=None):
    """Judge a short kept only as its published file (calibration material); result in _jury/calibration_clips/."""
    path = _published_result_path(output_dir, video_id)
    subject = published_subject(output_dir, video_id, transcribe=transcribe)
    old = _read_json(path)
    if isinstance(old, dict) and not force and old.get("clip_mtime") == _mtime(subject["video"]):
        return old                                                 # judged once, kept (same rule as run_one)
    fields = judge(subject, votes=votes)
    rank_check = (old or {}).get("rank_check") if isinstance(old, dict) else None
    result = {"video_id": video_id, "ref": video_id, "clip_file": os.path.basename(subject["video"]),
              "clip_mtime": _mtime(subject["video"]), "version": VERSION, "model": fields.pop("model"),
              "at": _now(), "score": final_score(fields["score_solo"], rank_check), **fields,
              "rank_check": rank_check}
    _write_json(path, result)
    return result


# --- the ranking check ----------------------------------------------------------------------------------------

def make_groups(ids, rounds=RANK_ROUNDS, size=RANK_GROUP, seed=RANK_SEED):
    """``rounds`` shuffles of ``ids`` cut in groups of ``size`` (a short last group is topped up with clips from
    other groups, so every group compares at least 3): every id plays in at least ``rounds`` groups."""
    ids = list(ids)
    if len(ids) < 2:
        return []
    size = max(2, min(size, len(ids)))
    rng = random.Random(seed)
    groups = []
    for _ in range(rounds):
        order = ids[:]
        rng.shuffle(order)
        chunk = [order[i:i + size] for i in range(0, len(order), size)]
        if len(chunk) > 1 and len(chunk[-1]) < min(3, size):
            last = chunk[-1]
            pool = [x for x in order if x not in last]
            rng.shuffle(pool)
            last += pool[:min(3, size) - len(last)]
        groups += chunk
    return groups


def pairwise_table(groups_orders):
    """{id: {"wins", "games", "rank_score"}} from the groups' orders (best first): each order gives every pair
    in it one game."""
    table = {}
    for order in groups_orders:
        for i, a in enumerate(order):
            for b in order[i + 1:]:
                table.setdefault(a, {"wins": 0, "games": 0})
                table.setdefault(b, {"wins": 0, "games": 0})
                table[a]["wins"] += 1
                table[a]["games"] += 1
                table[b]["games"] += 1
    for v in table.values():
        v["rank_score"] = int(round(100 * v["wins"] / v["games"])) if v["games"] else None
    return table


def rank_prompt(labels, subjects):
    lines = [VIEWER, "", PRINCIPLES, "",
             RANK_TASK.format(n=len(labels), labels=", ".join(labels),
                              times=", ".join(f"{t:g}" for t in RANK_FRAMES)), ""]
    for lab, s in zip(labels, subjects):
        hook = s.get("hook") or s.get("hook_read")
        lines.append(f'{lab}: words in the first 3 s: "{window_text(s.get("words") or [], 0.0, 3.0) or "(nothing)"}"; '
                     + (f'on-screen hook: "{hook}"' if hook else "on-screen hook: read it on the frames"))
    return "\n".join(lines)


def clean_order(order, labels):
    """The model's order made a permutation of ``labels`` (unknown letters dropped, missing ones last)."""
    seen = []
    for x in order or []:
        x = str(x).strip().upper()[:1]
        if x in labels and x not in seen:
            seen.append(x)
    return seen + [x for x in labels if x not in seen]


def rank_pass(output_dir, subjects, rounds=RANK_ROUNDS, size=RANK_GROUP, seed=RANK_SEED):
    """The ranking check over ``subjects`` ({ref: subject}) -> {"groups": [...], "table": {...}, "cost": {...}}.
    Group calls are cached by ai_brain like any other (same group, same frames: 0 tokens)."""
    refs = sorted(subjects)
    groups = make_groups(refs, rounds, size, seed)
    tmp = tempfile.mkdtemp(prefix="jury_rank_")
    done, cost = [], {}
    try:
        frames = {}
        for ref in refs:
            frames[ref] = extract_frames(subjects[ref]["video"], RANK_FRAMES,
                                         os.path.join(tmp, re.sub(r"\W", "_", ref)))
        for g, group in enumerate(groups, 1):
            labels = [chr(ord("A") + i) for i in range(len(group))]
            attach = []
            gdir = os.path.join(tmp, f"g{g}")
            os.makedirs(gdir, exist_ok=True)
            for lab, ref in zip(labels, group):
                for p in frames[ref]:
                    dst = os.path.join(gdir, f"{lab}_{os.path.basename(p)}")
                    shutil.copyfile(p, dst)
                    attach.append(dst)
            try:
                data, who, c = _ask(rank_prompt(labels, [subjects[r] for r in group]), RANK_SCHEMA, attach=attach,
                                    system=SYSTEM_VIEWER)
            except Exception as e:                                 # noqa: BLE001 — one group lost, not the pass
                print(f"   ⚠️ rank group {g} failed: {str(e)[:160]}", flush=True)
                continue
            _add_cost(cost, c)
            order = clean_order((data or {}).get("order"), labels)
            by_label = dict(zip(labels, group))
            done.append({"refs": group, "order": [by_label[x] for x in order],
                         "why": _text((data or {}).get("why"), 200), "model": who})
            print(f"   🏁 group {g}/{len(groups)}: {' > '.join(by_label[x] for x in order)}", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"groups": done, "table": pairwise_table([d["order"] for d in done]), "cost": cost}


# --- statistics ---------------------------------------------------------------------------------------------

def spearman(xs, ys):
    import stats_ingest
    return stats_ingest.spearman(list(xs), list(ys))


def spearman_p(xs, ys, limit=20000, seed=7):
    """Two-sided permutation p of Spearman's rho: the share of shufflings of ``ys`` whose |rho| is at least the
    observed one (every permutation when there are at most ``limit``, else ``limit`` random ones, fixed seed)."""
    xs, ys = list(xs), list(ys)
    rho = spearman(xs, ys)
    if rho is None:
        return None
    observed = abs(rho) - 1e-9
    n = len(ys)
    if math.factorial(n) <= limit:
        import itertools
        perms = itertools.permutations(ys)
    else:
        rng = random.Random(seed)

        def shuffled():
            for _ in range(limit):
                y = ys[:]
                rng.shuffle(y)
                yield y
        perms = shuffled()
    hits = total = 0
    for y in perms:
        r = spearman(xs, list(y))
        hits += r is not None and abs(r) >= observed
        total += 1
    return hits / total if total else None


def reading(n, rho, p):
    if n < MIN_CALIBRATION or rho is None:
        return "too_few"
    for name, min_rho, max_p in READINGS:
        if rho >= min_rho and p is not None and p <= max_p:
            return name
    return "weak"


def _parse_ts(value):
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _schedule(app_root):
    data = _read_json(os.path.join(app_root, "publish_schedule.json"))
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    return data if isinstance(data, list) else []


def _published_version_ok(output_dir, app_root, job_id, clip_index, video):
    """(ok, why): the mp4 on disk is the one that was published — the YouTube entry of the publish plan sent
    this very file, and the file was not written after it was sent."""
    name, mtime = os.path.basename(video), _mtime(video)
    sent = []
    for e in _schedule(app_root):
        if (isinstance(e, dict) and str(e.get("job_id")) == job_id and e.get("clip_index") == clip_index
                and e.get("platform") in (None, "", "youtube")):
            sent.append(e)
    if sent:
        e = sent[-1]
        if os.path.basename(str(e.get("video_url") or "")) != name:
            return False, f"published file {os.path.basename(str(e.get('video_url')))} is not the one on disk"
        at = e.get("created_at") or e.get("posted_at")
        if at and mtime and mtime > float(at) + 120:
            return False, "re-rendered after it was sent for publication"
        return True, "same file as the publish plan, written before it was sent"
    _p, meta = _metadata(_job_dir(output_dir, job_id))
    pub = ((meta or {}).get("shorts") or [{}] * (clip_index + 1))[clip_index].get("published") or {}
    if pub.get("at") and mtime and mtime <= float(pub["at"]) + 120:
        return True, "written before it was sent (metadata)"
    return False, "cannot check that the file on disk is the published one"


def calibration_set(output_dir, app_root=None):
    """(rows, excluded). rows: {"ref", "stayed", "source", "published", "age_h", "kind", "job_id", "clip_index",
    "video_id", "title", "views"} for every published short with a real stayed-to-watch, at least MIN_AGE_HOURS old
    when read, whose video is the published version; excluded: {"ref", "why"}."""
    app_root = app_root or os.path.dirname(os.path.abspath(output_dir))
    rows, excluded, seen = [], [], set()
    shorts = _read_json(os.path.join(output_dir, SHORTS_FILE)) or []
    raw = _read_json(os.path.join(output_dir, STUDIO_RAW_FILE)) or {}
    pub_ts = {v.get("id"): _parse_ts(v.get("pub")) for v in (raw.get("videos") or []) if isinstance(v, dict)}
    read_at = _parse_ts(STUDIO_READ_AT)
    for s in shorts if isinstance(shorts, list) else []:
        vid, tag = s.get("id"), s.get("local_tag")
        ref = tag or vid
        stayed = s.get("restent_pct")
        if stayed is None:
            excluded.append({"ref": ref, "why": "no stayed-to-watch figure"})
            continue
        pub = pub_ts.get(vid)
        age = round((read_at - pub).total_seconds() / 3600, 1) if pub and read_at else None
        row = {"ref": ref, "video_id": vid, "stayed": float(stayed), "source": "studio 04/10 (shorts_23.json)",
               "published": s.get("pub"), "age_h": age, "title": s.get("titre"), "views": s.get("vues")}
        if age is None or age < MIN_AGE_HOURS:
            excluded.append({"ref": ref, "why": f"figure read {age} h after publication (< {MIN_AGE_HOURS} h)",
                             "stayed": float(stayed), "video_id": vid, "age_h": age})
            continue
        if tag:
            job_prefix, n = tag.rsplit("_c", 1)
            job_dir = _job_dir(output_dir, job_prefix)
            video = clip_video_path(output_dir, job_prefix, int(n) - 1) if job_dir else None
            if not video:
                excluded.append({"ref": ref, "why": "clip no longer on disk"})
                continue
            ok, why = _published_version_ok(output_dir, app_root, os.path.basename(job_dir), int(n) - 1, video)
            if not ok:
                excluded.append({"ref": ref, "why": why})
                continue
            row.update(kind="clip", job_id=os.path.basename(job_dir), clip_index=int(n) - 1, check=why)
        else:
            if not os.path.isfile(os.path.join(jury_dir(output_dir), "published", f"{vid}.mp4")):
                excluded.append({"ref": ref, "why": "no video of it"})
                continue
            row.update(kind="published", check="the published file itself")
        rows.append(row)
        seen.add(ref)
        seen.add(vid)
    rows += _studio_export_rows(output_dir, app_root, seen, excluded)
    return rows, excluded


def _studio_export_rows(output_dir, app_root, seen, excluded):
    """Clips with a real stayed-to-watch in the newest Studio export (stats/), old enough when exported."""
    import stats_ingest
    path, rows, _problem = stats_ingest.read_latest_export(os.path.join(app_root, "stats"))
    if not path or not rows:
        return []
    as_of = datetime.fromtimestamp(os.path.getmtime(path))
    clips = stats_ingest.load_clips(output_dir, _schedule(app_root))
    out = []
    for r, c, how in stats_ingest.link_studio(rows, clips):
        if not c or not c.get("local") or r.get("stayed") is None or c["ref"] in seen:
            continue
        ref = c["ref"]
        if ref in CALIBRATION_EXCLUDE:
            excluded.append({"ref": ref, "why": CALIBRATION_EXCLUDE[ref]})
            continue
        try:
            # the export gives a day: count from its END, so a short is never thought older than it is
            day_end = datetime.fromisoformat(r["published"]) + timedelta(days=1)
            age = round((as_of - day_end).total_seconds() / 3600, 1)
        except (KeyError, TypeError, ValueError):
            age = None
        if age is None or age < MIN_AGE_HOURS:
            excluded.append({"ref": ref, "why": f"less than {MIN_AGE_HOURS} h old in the export ({age} h)"})
            continue
        out.append({"ref": ref, "stayed": float(r["stayed"]),
                    "source": f"studio export {os.path.basename(path)} ({how})",
                    "published": r.get("published"), "age_h": age, "kind": "clip", "job_id": c["job_id"],
                    "clip_index": c["clip_index"], "video_id": r.get("video_id"), "title": r.get("title"),
                    "views": r.get("views")})
        seen.add(ref)
    return out


def _row_result(output_dir, row):
    if row["kind"] == "clip":
        return load_result(output_dir, row["job_id"], row["clip_index"])
    return _read_json(_published_result_path(output_dir, row["video_id"]))


def _corr(rows, key):
    pts = [(r[key], r["stayed"]) for r in rows if r.get(key) is not None]
    if len(pts) < 3:
        return {"n": len(pts), "rho": None, "p": None}
    xs, ys = zip(*pts)
    rho = spearman(xs, ys)
    return {"n": len(pts), "rho": None if rho is None else round(rho, 3),
            "p": None if rho is None else round(spearman_p(xs, ys), 4)}


def stability(results):
    """How much one vote moves: spread of the 3 votes, and test-retest rank correlation between vote 1 and vote 2
    (and 3) across clips — if one vote ranks the clips like another vote does, one vote is enough."""
    multi = [r for r in results if len(r.get("votes") or []) >= 3]
    if not multi:
        return None
    spreads = [r["spread"] for r in multi]
    dev = [abs(v - r["score_solo"]) for r in multi for v in r["votes"]]
    retest = []
    for a, b in ((0, 1), (0, 2), (1, 2)):
        rho = spearman([r["votes"][a] for r in multi], [r["votes"][b] for r in multi])
        if rho is not None:
            retest.append(rho)
    crit_agree = []
    for r in multi:
        det = r.get("votes_detail") or []
        for k in VIEWER_CRITERIA:
            vals = [d.get(k) for d in det]
            if len(vals) >= 3:
                crit_agree.append(len(set(vals)) == 1)
    return {"clips": len(multi), "spread_mean": round(statistics.mean(spreads), 1),
            "spread_median": statistics.median(spreads), "spread_max": max(spreads),
            "abs_dev_from_median_mean": round(statistics.mean(dev), 1),
            "retest_spearman_mean": round(statistics.mean(retest), 3) if retest else None,
            "criteria_unanimous_share": round(sum(crit_agree) / len(crit_agree), 3) if crit_agree else None}


def calibrate(output_dir, app_root=None, write=True):
    """Scores vs real stayed-to-watch -> output/_jury/calibration.json (C1 format + the comparison solo / ranked
    / blend, the stability of the votes, a sensitivity check without the age rule, the same-moment pairs)."""
    rows, excluded = calibration_set(output_dir, app_root)
    table = []
    for row in rows:
        res = _row_result(output_dir, row)
        if not res:
            excluded.append({"ref": row["ref"], "why": "not judged yet (run the jury first)"})
            continue
        rank = (res.get("rank_check") or {}).get("rank_score")
        solo = res.get("score_solo", res.get("score"))
        table.append({**{k: row.get(k) for k in ("ref", "stayed", "title", "published", "age_h", "views", "source",
                                                    "video_id", "kind")},
                      "score_solo": solo, "rank_score": rank,
                      "score_blend": None if rank is None or solo is None else int(round((solo + rank) / 2)),
                      "vote1": (res.get("votes") or [None])[0], "votes": res.get("votes"),
                      "verdict": res.get("verdict"), "stop": res.get("stop"), "criteria": res.get("criteria"),
                      "hook_true": res.get("hook_true")})
    corr = {m: _corr(table, k) for m, k in (("solo", "score_solo"), ("ranked", "rank_score"),
                                            ("blend", "score_blend"), ("vote1", "vote1"))}
    # The score the app keeps is SCORE_MODE; the numbers' own choice is reported next to it: the simplest (solo)
    # unless another one is clearly better (SCORE_MODE_MIN_GAIN) on the same shorts.
    suggested = "solo"
    for m in ("ranked", "blend"):
        rho, base = corr[m]["rho"], corr["solo"]["rho"]
        if (rho is not None and base is not None and corr[m]["n"] == corr["solo"]["n"]
                and rho >= base + SCORE_MODE_MIN_GAIN
                and (suggested == "solo" or rho > corr[suggested]["rho"])):
            suggested = m
    mode = SCORE_MODE
    key = {"solo": "score_solo", "ranked": "rank_score", "blend": "score_blend"}[mode]
    for t in table:
        t["score"] = t[key] if t[key] is not None else t["score_solo"]
    main = corr[mode]
    # sensitivity: the young figures the age rule left out, put back
    young = [e for e in excluded if e.get("age_h") is not None and e.get("stayed") is not None]
    sens = None
    if young:
        extra = []
        for e in young:
            row = {"kind": "published", "video_id": e["video_id"]}
            ref = e["ref"]
            if "_c" in ref and len(ref) == 12:
                row = {"kind": "clip", "job_id": os.path.basename(_job_dir(output_dir, ref[:8]) or ""),
                       "clip_index": int(ref[-2:]) - 1}
            res = _row_result(output_dir, row) if (row.get("job_id") or row.get("video_id")) else None
            if res:
                solo = res.get("score_solo", res.get("score"))
                rank = (res.get("rank_check") or {}).get("rank_score")
                extra.append({"ref": ref, "stayed": e["stayed"], "score_solo": solo, "rank_score": rank,
                              "score_blend": None if rank is None or solo is None else int(round((solo + rank) / 2))})
        all_rows = table + extra
        sens = {"added": [e["ref"] for e in extra],
                **{m: _corr(all_rows, k) for m, k in (("solo", "score_solo"), ("ranked", "rank_score"),
                                                      ("blend", "score_blend"))}}
    by_ref = {t.get("video_id") or t["ref"]: t for t in table}
    pairs = []
    for v1, v2 in SAME_MOMENT_PAIRS:
        a, b = by_ref.get(v1), by_ref.get(v2)
        if a and b:
            better = a if a["stayed"] > b["stayed"] else b
            pick = {m: (None if a[k] is None or b[k] is None or a[k] == b[k]
                        else (a if a[k] > b[k] else b)["ref"] == better["ref"])
                    for m, k in (("solo", "score_solo"), ("ranked", "rank_score"))}
            pairs.append({"v1": a["ref"], "v2": b["ref"], "stayed": [a["stayed"], b["stayed"]],
                          "solo": [a["score_solo"], b["score_solo"]], "ranked": [a["rank_score"], b["rank_score"]],
                          "jury_right": pick})
    out = {"version": VERSION, "at": _now(), "n": main["n"], "spearman": main["rho"], "p": main["p"],
           "reading": reading(main["n"], main["rho"], main["p"]), "score_mode": mode,
           "score_mode_suggested": suggested,
           "spearman_solo": corr["solo"]["rho"], "p_solo": corr["solo"]["p"],
           "spearman_ranked": corr["ranked"]["rho"], "p_ranked": corr["ranked"]["p"],
           "spearman_blend": corr["blend"]["rho"], "p_blend": corr["blend"]["p"],
           "spearman_one_vote": corr["vote1"]["rho"], "p_one_vote": corr["vote1"]["p"],
           "rows": [{"ref": t["ref"], "score": t["score"], "stayed": t["stayed"], "score_solo": t["score_solo"],
                     "rank_score": t["rank_score"], "title": t["title"], "published": t["published"],
                     "age_h": t["age_h"], "verdict": t["verdict"], "stop": t["stop"], "source": t["source"]}
                    for t in sorted(table, key=lambda t: -t["stayed"])],
           "excluded": excluded, "stability": stability([_row_result(output_dir, r) or {} for r in rows]),
           "sensitivity_without_age_rule": sens, "same_moment_pairs": pairs,
           "note": ("Spearman rank correlation between the jury's score and the real 'Stayed to watch' (YouTube "
                    f"Studio) of the published shorts at least {MIN_AGE_HOURS} h old; p = two-sided permutation test. "
                    "Small sample, and the jury's principles were drawn from the analysis of these same shorts: "
                    "an optimistic reading. The out-of-sample test is the pre-registered job.")}
    if write:
        _write_json(os.path.join(jury_dir(output_dir), "calibration.json"), out)
    return out


def preregister(output_dir, job=PREREGISTER_JOB, force=False):
    """Freeze, with the time, the jury's scores of a job whose real figures are not known yet."""
    job_dir = _job_dir(output_dir, job)
    if not job_dir:
        raise FileNotFoundError(f"no job folder for {job}")
    job_id = os.path.basename(job_dir)
    path = os.path.join(jury_dir(output_dir), f"preregistered_{job_id[:8]}.json")
    if os.path.exists(path) and not force:
        raise FileExistsError(f"{path} exists: a pre-registration is never rewritten (--force to do it anyway)")
    _p, meta = _metadata(job_dir)
    clips = []
    for i in range(len((meta or {}).get("shorts") or [])):
        r = load_result(output_dir, job_id, i)
        ref = ref_of(job_id, i)
        if not r:
            clips.append({"ref": ref, "missing": "no up-to-date jury result"})
            continue
        rank = (r.get("rank_check") or {}).get("rank_score")
        clips.append({"ref": ref, "clip_file": r["clip_file"], "clip_mtime": r["clip_mtime"], "score": r["score"],
                      "score_solo": r.get("score_solo"), "rank_score": rank,
                      "score_blend": None if rank is None else int(round((r.get("score_solo") + rank) / 2)),
                      "votes": r.get("votes"), "criteria": r.get("criteria"), "hook_true": r.get("hook_true"),
                      "stop": r.get("stop"), "verdict": r.get("verdict"),
                      "excluded_from_test": CALIBRATION_EXCLUDE.get(ref)})
    body = json.dumps(clips, sort_keys=True, ensure_ascii=False)
    out = {"job_id": job_id, "frozen_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
           "version": VERSION, "score_mode": SCORE_MODE, "clips": clips,
           "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
           "how_to_test": ("After the figures are in (each short >= 48 h old in a Studio export): Spearman between "
                           "these frozen scores and the real 'Stayed to watch', excluding excluded_from_test. "
                           "sha256 = hash of json.dumps(clips, sort_keys=True, ensure_ascii=False).")}
    _write_json(path, out)
    return out


# --- every clip on disk -------------------------------------------------------------------------------------

def all_clips(output_dir):
    """[(job_id, clip_index)] of every clip in output/<job>/*_metadata.json (folders starting with "_" skipped)."""
    out = []
    for meta_path in sorted(glob.glob(os.path.join(glob.escape(output_dir), "*", "*_metadata.json"))):
        job_dir = os.path.dirname(meta_path)
        if os.path.basename(job_dir).startswith(("_", ".")):
            continue
        data = _read_json(meta_path) or {}
        for i, s in enumerate(data.get("shorts") or []):
            if isinstance(s, dict):
                out.append((os.path.basename(job_dir), i))
    return out


def published_ids(output_dir):
    return sorted(os.path.basename(p)[:-4] for p in
                  glob.glob(os.path.join(glob.escape(jury_dir(output_dir)), "published", "*.mp4")))


def rank_all(output_dir, force=False):
    """The ranking check over every judged subject (app clips with a fresh result + the published calibration
    shorts) -> output/_jury/rank_check.json, and ``rank_check`` / ``score`` written into each result."""
    subjects, results = {}, {}
    for job_id, i in all_clips(output_dir):
        r = load_result(output_dir, job_id, i)
        if r:
            s = clip_subject(output_dir, job_id, i)
            s["hook_read"] = r.get("hook_read")
            subjects[s["ref"]] = s
            results[s["ref"]] = ("clip", job_id, i, r)
    for vid in published_ids(output_dir):
        r = _read_json(_published_result_path(output_dir, vid))
        if isinstance(r, dict):
            s = published_subject(output_dir, vid)
            s["hook_read"] = r.get("hook_read")
            subjects[vid] = s
            results[vid] = ("published", vid, None, r)
    out = rank_pass(output_dir, subjects)
    out.update(version=VERSION, at=_now(), pool=sorted(subjects), rounds=RANK_ROUNDS, group=RANK_GROUP)
    _write_json(os.path.join(jury_dir(output_dir), "rank_check.json"), out)
    for ref, (kind, a, b, r) in results.items():
        t = out["table"].get(ref)
        r["rank_check"] = None if not t else {"wins": t["wins"], "games": t["games"], "rank_score": t["rank_score"]}
        r["score"] = final_score(r.get("score_solo", r.get("score")), r["rank_check"])
        _write_json(result_path(output_dir, a, b) if kind == "clip" else _published_result_path(output_dir, a), r)
    return out


# --- command line -------------------------------------------------------------------------------------------

def _default_output():
    return os.environ.get("JURY_OUTPUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _parse_targets(output_dir, targets):
    """'JOB:N' / 'JOB_cNN' (N = the clip's number, from 1) -> [(job_id, clip_index)]."""
    out = []
    for t in targets:
        m = re.match(r"^([0-9A-Za-z-]+)(?::|_c)(\d+)$", t.strip())
        if not m:
            raise SystemExit(f"not a clip: {t!r} (JOB:N or JOB_cNN)")
        job_dir = _job_dir(output_dir, m.group(1))
        if not job_dir:
            raise SystemExit(f"no single job folder for {m.group(1)!r}")
        out.append((os.path.basename(job_dir), int(m.group(2)) - 1))
    return out


def _work(args):
    kind, output_dir, key, force, votes = args
    t0 = time.time()
    try:
        if kind == "clip":
            r = run_one(output_dir, key[0], key[1], force=force, votes=votes)
        else:
            r = run_published(output_dir, key, force=force, votes=votes)
        return {"ref": r["ref"], "score": r["score_solo"], "votes": r["votes"], "verdict": r["verdict"],
                "cost": r.get("cost"), "seconds": round(time.time() - t0, 1)}
    except Exception as e:                                         # noqa: BLE001
        return {"ref": key if isinstance(key, str) else ref_of(*key), "error": str(e)[:300]}


def _run_batch(kind, output_dir, keys, force, votes, workers):
    jobs = [(kind, output_dir, k, force, votes) for k in keys]
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for n, res in enumerate(pool.map(_work, jobs), 1):
                print(f"[{n}/{len(jobs)}] {json.dumps(res, ensure_ascii=False)}", flush=True)
    else:
        for n, job in enumerate(jobs, 1):
            print(f"[{n}/{len(jobs)}] {json.dumps(_work(job), ensure_ascii=False)}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="The hook jury (first seconds of each rendered clip).")
    ap.add_argument("--output", default=_default_output(), help="the output folder (default: ./output)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("targets", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--votes", type=int, default=APP_VOTES)
    p.add_argument("--workers", type=int, default=1)
    p = sub.add_parser("published")
    p.add_argument("ids", nargs="*")
    p.add_argument("--force", action="store_true")
    p.add_argument("--votes", type=int, default=CALIBRATION_VOTES)
    p.add_argument("--workers", type=int, default=1)
    sub.add_parser("rank")
    sub.add_parser("calibrate")
    p = sub.add_parser("preregister")
    p.add_argument("job", nargs="?", default=PREREGISTER_JOB)
    p.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    out = a.output
    if a.cmd == "run":
        keys = all_clips(out) if a.all else _parse_targets(out, a.targets)
        if not keys:
            raise SystemExit("nothing to judge: JOB:N ... or --all")
        _run_batch("clip", out, keys, a.force, a.votes, a.workers)
    elif a.cmd == "published":
        ids = a.ids or published_ids(out)
        for vid in ids:                    # transcribe first, in this process (one Whisper model, the GPU gate)
            published_subject(out, vid)
        _run_batch("published", out, ids, a.force, a.votes, a.workers)
    elif a.cmd == "rank":
        res = rank_all(out)
        top = sorted(res["table"].items(), key=lambda kv: -(kv[1]["rank_score"] or 0))
        for ref, t in top:
            print(f"{ref:14} {t['rank_score']:>3}  ({t['wins']}/{t['games']})")
        print(json.dumps(res["cost"]))
    elif a.cmd == "calibrate":
        res = calibrate(out)
        print(json.dumps({k: v for k, v in res.items() if k not in ("rows", "excluded")}, indent=1,
                         ensure_ascii=False))
        print("\n| short | jury | ranked | stayed | verdict |\n|---|---|---|---|---|")
        for r in res["rows"]:
            print(f"| {r['ref']} {(r['title'] or '')[:40]} | {r['score_solo']} | {r['rank_score']} | "
                  f"{r['stayed']} | {r['verdict']} |")
        for e in res["excluded"]:
            print(f"excluded {e['ref']}: {e['why']}")
    elif a.cmd == "preregister":
        res = preregister(out, a.job, force=a.force)
        print(json.dumps({k: res[k] for k in ("job_id", "frozen_at", "sha256")}))
        for c in res["clips"]:
            print(c.get("ref"), c.get("score"), c.get("score_solo"), c.get("rank_score"), c.get("verdict"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
