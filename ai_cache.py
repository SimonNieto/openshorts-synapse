"""Clip Generator++: never pay Claude twice for the same question.

Two disk caches under ``output/_ai_cache`` (kept across jobs and restarts):

- TRANSCRIPTS, keyed on the source video's bytes + the transcription
  settings: re-running a video gets the exact same words, so every prompt
  built from them is byte-identical and hits the answer cache below;
- ANSWERS, keyed on everything a Claude call depends on (model, effort,
  system prompt, JSON schema, prompt, and the bytes of every attached
  image): the brief, the scoring and detail passes, the B-roll plan, the
  image reviews... asked again with the same inputs are read back for
  0 tokens. Any change of input (settings, profile, beta switch, clip
  length) changes the prompt and asks Claude afresh.

``AI_CACHE=0`` switches both off (e.g. to get a new draw of clips on the
same video). Entries older than ``AI_CACHE_DAYS`` (30) are ignored and
pruned.
"""
import hashlib
import json
import os
import time

ROOT = os.environ.get("AI_CACHE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                       "output", "_ai_cache")
HITS = {"answers": 0, "transcripts": 0}
_pruned = False


def enabled():
    return os.environ.get("AI_CACHE", "1") != "0"


def refreshing():
    """AI_CACHE_REFRESH=1 (the profile's "fresh picks"): ask again, ignore
    what is remembered, but remember the new answers for the next re-run."""
    return os.environ.get("AI_CACHE_REFRESH") == "1"


def _max_age():
    try:
        return float(os.environ.get("AI_CACHE_DAYS") or 30) * 86400
    except ValueError:
        return 30 * 86400


def _path(kind, key):
    return os.path.join(ROOT, kind, key[:2], key + ".json")


def _prune():
    """Drop expired entries, once per process."""
    global _pruned
    if _pruned:
        return
    _pruned = True
    limit = time.time() - _max_age()
    for base, _dirs, files in os.walk(ROOT):
        for f in files:
            p = os.path.join(base, f)
            try:
                if os.path.getmtime(p) < limit:
                    os.remove(p)
            except OSError:
                pass


def _read(kind, key):
    if not enabled() or (kind == "answers" and refreshing()):
        return None
    p = _path(kind, key)
    try:
        if time.time() - os.path.getmtime(p) > _max_age():
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(kind, key, data):
    """Best effort, atomic (clip workers run in parallel threads)."""
    if not enabled():
        return
    try:
        _prune()
        p = _path(kind, key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception as e:
        print(f"   ⚠️ AI cache write failed ({e}) — carrying on.", flush=True)


def _file_digest(path, h):
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)


# --- answers ------------------------------------------------------------------------

def answer_key(model, effort, system, schema, prompt, attach=None):
    h = hashlib.sha256()
    h.update(json.dumps([model, effort, system, schema, prompt], sort_keys=True, ensure_ascii=False)
             .encode("utf-8"))
    for p in attach or []:
        h.update(os.path.basename(p).encode("utf-8"))
        _file_digest(p, h)
    return h.hexdigest()


def gemini_key(model, contents):
    """The same for a Gemini call: text parts and the bytes of image parts."""
    h = hashlib.sha256()
    h.update(f"gemini|{model}".encode("utf-8"))
    for part in contents if isinstance(contents, (list, tuple)) else [contents]:
        if isinstance(part, str):
            h.update(b"T" + part.encode("utf-8"))
            continue
        blob = getattr(part, "inline_data", None)
        data = getattr(blob, "data", None) if blob is not None else None
        if data:
            h.update(b"I" + (getattr(blob, "mime_type", "") or "").encode() + bytes(data))
        else:
            h.update(b"?" + repr(part).encode("utf-8", "replace"))
    return h.hexdigest()


def remember(key, fn, who="Gemini"):
    """``fn()``'s answer, read back from the cache when this exact question
    was answered before."""
    hit = get_answer(key)
    if hit is not None:
        print(f"   ♻️ {who}: same question as before — answer reused, $0", flush=True)
        return hit
    data = fn()
    put_answer(key, data)
    return data


def get_answer(key):
    data = _read("answers", key)
    if data is not None:
        HITS["answers"] += 1
    return data


def put_answer(key, data):
    _write("answers", key, data)


# --- transcripts --------------------------------------------------------------------

def video_key(path):
    """The source's identity: size + its first and last 8 MB (hashing a 5 GB
    podcast whole would take longer than it saves), plus the transcription
    settings — another model gives other words."""
    h = hashlib.sha256()
    size = os.path.getsize(path)
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(8 << 20))
        if size > 16 << 20:
            f.seek(-(8 << 20), os.SEEK_END)
            h.update(f.read())
    settings = sorted((k, v) for k, v in os.environ.items() if "WHISPER" in k or "TRANSCRIBE" in k)
    h.update(json.dumps(settings).encode())
    return h.hexdigest()


def get_transcript(video_path):
    try:
        data = _read("transcripts", video_key(video_path))
    except OSError:
        return None
    if data and data.get("segments"):
        HITS["transcripts"] += 1
        return data
    return None


def put_transcript(video_path, transcript):
    try:
        _write("transcripts", video_key(video_path), transcript)
    except OSError:
        pass
