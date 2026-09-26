"""Clip Generator++ — channel profiles, music library, per-job env.

A profile is the whole recipe of one channel, picked in one click before a
run: account + niche, clip length, edit style and its options, hook box,
watermark, music bed, auto-publish, and the BETA switches (AI selection v2,
series titles). The classic Clip Generator never reads any of this: a job
only changes when it is started from Clip Generator++ with a profile.

Stored server-side (clip_profiles.json, self-host), so the same profiles are
there from any browser and on any machine the project moves to.
"""
import json
import os
import random
import re
import time
import uuid

PROFILE_FILE = "clip_profiles.json"
MUSIC_DIR = os.environ.get("PLUS_MUSIC_DIR") or "music"
AUDIO_EXT = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac")

DEFAULT_PROFILE = {
    "name": "Podcast · natural",
    "upload_profile": "",
    "niche": "",
    "clip_min": 15,
    "clip_max": 35,
    "target_clips": None,
    "edit_style": "natural",
    # Hook at the top: "none", "bold" (big headline, fades in, ~4 s) or
    # "classic" (the white serif card of the classic Clip Generator).
    "hook_style": "bold",
    "hook_seconds": 4,
    "hook_box": True,
    # End every clip on a full stop (never on a dangling "cause...").
    "clean_ending": True,
    "watermark": "",
    "fx": {"smart_framing": True, "look": False, "spotlight": False, "streaks": False, "reactions": False},
    "music": {"enabled": False, "mood": "", "volume": 0.22},
    # BETA: 2-4 image cutaways when something concrete is named (broll.py).
    "broll": {"enabled": False, "source": "auto", "style": "photo", "max": 3},
    "auto_publish": {"enabled": False, "platforms": ["tiktok", "instagram", "youtube"]},
    "beta": {"selection_v2": False, "series_titles": False, "series_name": ""},
}


def _bool(v):
    return bool(v) and str(v).lower() not in ("0", "false", "no")


def _int(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError):
        return default


def sanitize(raw):
    """Whitelist + clamp every field: the profile becomes env vars of a job."""
    raw = raw or {}
    d = DEFAULT_PROFILE
    fx = raw.get("fx") or {}
    music = raw.get("music") or {}
    beta = raw.get("beta") or {}
    ap = raw.get("auto_publish") or {}
    br = raw.get("broll") or {}
    clip_min = _int(raw.get("clip_min"), 5, 170, d["clip_min"])
    clip_max = _int(raw.get("clip_max"), 10, 180, d["clip_max"])
    if clip_max < clip_min + 5:
        clip_max = clip_min + 5
    target = raw.get("target_clips")
    try:
        vol = float(music.get("volume", d["music"]["volume"]))
    except (TypeError, ValueError):
        vol = d["music"]["volume"]
    # Profiles saved before hook_style existed only had the hook_box switch.
    hook_style = raw.get("hook_style")
    if hook_style not in ("none", "bold", "classic"):
        if "hook_box" in raw:
            hook_style = "classic" if _bool(raw.get("hook_box")) else "none"
        else:
            hook_style = d["hook_style"]
    return {
        "name": (str(raw.get("name") or "").strip() or "Profile")[:60],
        "upload_profile": str(raw.get("upload_profile") or "").strip()[:80],
        "niche": str(raw.get("niche") or "").strip()[:80],
        "clip_min": clip_min,
        "clip_max": clip_max,
        "target_clips": _int(target, 1, 15, None) if target not in (None, "", 0, "0") else None,
        "edit_style": raw.get("edit_style") if raw.get("edit_style") in ("natural", "punchy", "clean") else "natural",
        "hook_style": hook_style,
        "hook_seconds": _int(raw.get("hook_seconds"), 2, 10, d["hook_seconds"]),
        "hook_box": hook_style != "none",
        "clean_ending": _bool(raw.get("clean_ending", True)),
        "watermark": re.sub(r"[^\w .@&'-]", "", str(raw.get("watermark") or ""))[:30],
        "fx": {k: _bool(fx.get(k, v)) for k, v in d["fx"].items()},
        "music": {"enabled": _bool(music.get("enabled")),
                  "mood": str(music.get("mood") or "").strip().strip("/\\")[:60],
                  "volume": max(0.05, min(0.6, vol))},
        "broll": {"enabled": _bool(br.get("enabled")),
                  "source": br.get("source") if br.get("source") in ("auto", "gemini", "free") else "auto",
                  "style": br.get("style") if br.get("style") in ("photo", "neon", "drawing") else "photo",
                  "max": _int(br.get("max"), 1, 4, 3)},
        "auto_publish": {"enabled": _bool(ap.get("enabled")),
                         "platforms": [p for p in (ap.get("platforms") or []) if p in ("tiktok", "instagram", "youtube")]
                         or ["tiktok", "instagram", "youtube"]},
        "beta": {"selection_v2": _bool(beta.get("selection_v2")),
                 "series_titles": _bool(beta.get("series_titles")),
                 "series_name": str(beta.get("series_name") or "").strip()[:40]},
    }


def load_profiles():
    try:
        with open(PROFILE_FILE, encoding="utf-8") as f:
            return json.load(f).get("profiles", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_profiles(profiles):
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump({"profiles": profiles}, f, indent=2, ensure_ascii=False)


def get_profile(profile_id):
    return next((p for p in load_profiles() if p.get("id") == profile_id), None)


def upsert(raw, profile_id=None):
    profiles = load_profiles()
    clean = sanitize(raw)
    now = time.time()
    if profile_id:
        for i, p in enumerate(profiles):
            if p.get("id") == profile_id:
                profiles[i] = {**clean, "id": profile_id, "created_at": p.get("created_at", now), "updated_at": now}
                save_profiles(profiles)
                return profiles[i]
        return None
    created = {**clean, "id": uuid.uuid4().hex[:12], "created_at": now, "updated_at": now}
    profiles.append(created)
    save_profiles(profiles)
    return created


def delete(profile_id):
    profiles = load_profiles()
    kept = [p for p in profiles if p.get("id") != profile_id]
    if len(kept) == len(profiles):
        return False
    save_profiles(kept)
    return True


# --- music library ------------------------------------------------------------------

def music_library():
    """Moods = sub-folders of music/ (plus the loose tracks at its root)."""
    out = []
    try:
        entries = sorted(os.listdir(MUSIC_DIR))
    except OSError:
        return out
    root_tracks = [e for e in entries if e.lower().endswith(AUDIO_EXT)]
    if root_tracks:
        out.append({"mood": "", "label": "music/ (root)", "tracks": root_tracks})
    for e in entries:
        path = os.path.join(MUSIC_DIR, e)
        if os.path.isdir(path):
            tracks = sorted(t for t in os.listdir(path) if t.lower().endswith(AUDIO_EXT))
            out.append({"mood": e, "label": e, "tracks": tracks})
    return out


def pick_track(mood, seed=None):
    folder = os.path.join(MUSIC_DIR, mood) if mood else MUSIC_DIR
    try:
        tracks = sorted(t for t in os.listdir(folder) if t.lower().endswith(AUDIO_EXT))
    except OSError:
        return None
    if not tracks:
        return None
    return os.path.join(folder, random.Random(seed).choice(tracks))


# --- job env ----------------------------------------------------------------------------

def job_env(profile):
    """Env vars main.py reads for a Clip Generator++ job."""
    p = sanitize(profile)
    env = {
        "EDIT_STYLE": p["edit_style"],
        "PLUS_FX_JSON": json.dumps({**p["fx"], "watermark": p["watermark"] or None}),
        "AUTO_HOOK": "1" if p["hook_style"] != "none" else "0",
        "CLEAN_END": "1" if p["clean_ending"] else "0",
        "CLIP_MIN_SECONDS": str(p["clip_min"]),
        "CLIP_MAX_SECONDS": str(p["clip_max"]),
        "PLUS_PROFILE_JSON": json.dumps({"id": profile.get("id"), "name": p["name"]}),
    }
    if p["hook_style"] != "none":
        env["AUTO_HOOK_STYLE"] = p["hook_style"]
        env["AUTO_HOOK_SECONDS"] = str(p["hook_seconds"])
    if p["target_clips"]:
        env["CLIP_TARGET_MIN"] = env["CLIP_TARGET_MAX"] = str(p["target_clips"])
    if p["fx"].get("reactions"):
        env["PLUS_REACTIONS"] = "1"
    if p["music"]["enabled"]:
        env["PLUS_MUSIC_MOOD"] = p["music"]["mood"]
        env["PLUS_MUSIC_VOLUME"] = str(p["music"]["volume"])
        env["PLUS_MUSIC_ON"] = "1"
    if p["broll"]["enabled"]:
        env["PLUS_BROLL_JSON"] = json.dumps(p["broll"])
    if p["beta"]["selection_v2"]:
        env["SELECTION_V2"] = "1"
    if p["beta"]["series_titles"] and p["beta"]["series_name"]:
        env["TITLE_SERIES"] = p["beta"]["series_name"]
    return env
