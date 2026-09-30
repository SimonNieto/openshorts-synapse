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
    "fx": {"smart_framing": True, "look": False, "spotlight": False, "streaks": False, "reactions": False,
           "smooth_camera": False},
    "music": {"enabled": False, "mood": "", "volume": 0.22},
    # BETA: 2-4 image cutaways when something concrete is named (broll.py).
    "broll": {"enabled": False, "source": "local", "engine": "zimage", "planner": "gemini", "style": "photo",
              "max": 6, "mode": "mixed", "density": "normal", "real_photos": False, "review": "auto", "layout": "full", "position": "below", "y": None, "size": 28,
              "hold": None, "enter": "rise", "zoom": "soft", "border": "soft"},
    "auto_publish": {"enabled": False, "platforms": ["tiktok", "instagram", "youtube"]},
    "beta": {"selection_v2": False, "series_titles": False, "series_name": "",
             # Synapse Cut playbook: question titles without names, starts on the
             # hook sentence, credit line + question in the descriptions, one
             # stats JSON per clip (playbook.py). "playbook_show": the show's name
             # for the credit line (empty = read from the source's file name).
             "playbook": False, "playbook_show": ""},
    # How the clips are chosen and cut, past the length band. Every default
    # here is "off": a profile saved without the block behaves as before.
    "selection": {
        # Two clips of one job sharing more than this share of the shorter
        # one (0.2 = 20 %), or more than dedupe_seconds, or opening on the
        # same sentence: only the best-scoring one is kept. 0 = off.
        "dedupe_overlap": 0, "dedupe_seconds": 8,
        # [low, high] seconds to AIM for inside clip_min..clip_max (the hard
        # limits): asked for in the prompt, and a clip over it is cut back to
        # the sentence of its payoff. None = off.
        "clip_target": None,
    },
    # Which AI runs each step (ai_brain.STAGES): "gemini" or a Claude model.
    # "thinking" = Claude's effort on the two decision steps (clips, B-roll);
    # "fresh" = the next run ignores the AI memory (then switches itself off).
    "brain": {"preset": "balanced", "stages": None, "thinking": "deep", "thinking_broll": "normal", "fresh": False},
}

BRAIN_STAGES = ("brief_score", "detail", "layout", "broll", "image_review", "hook", "text")
BRAIN_CHOICES = ("gemini", "haiku", "sonnet", "opus")
BRAIN_PRESETS = {
    # No Claude at all: every step on Gemini (billed per token, cheap).
    "gemini": {k: "gemini" for k in BRAIN_STAGES},
    # "Gemini reads, Claude decides" — the default.
    "balanced": {"brief_score": "gemini", "detail": "sonnet", "layout": "gemini", "broll": "sonnet",
                 "image_review": "gemini", "hook": "sonnet", "text": "gemini"},
    # Claude everywhere, the light steps on Haiku (a fraction of the plan's usage).
    "claude": {"brief_score": "haiku", "detail": "sonnet", "layout": "haiku", "broll": "sonnet",
               "image_review": "haiku", "hook": "sonnet", "text": "haiku"},
    # Claude everywhere, Opus on the two decisions.
    "claude_max": {"brief_score": "sonnet", "detail": "opus", "layout": "haiku", "broll": "opus",
                   "image_review": "sonnet", "hook": "sonnet", "text": "haiku"},
}
THINKING = {"light": "low", "normal": "medium", "deep": "high"}


def _brain(raw, broll):
    """Sanitized brain block. Profiles saved before it existed: the balanced
    preset, with the B-roll step on whatever brain the B-roll section had."""
    legacy = not isinstance(raw, dict) or not raw
    raw = {} if legacy else raw
    preset = raw.get("preset") if raw.get("preset") in (*BRAIN_PRESETS, "custom") else "balanced"
    if preset == "custom":
        stages = dict(BRAIN_PRESETS["balanced"])
        for k, v in (raw.get("stages") or {}).items():
            if k in stages and v in BRAIN_CHOICES:
                stages[k] = v
    else:
        stages = dict(BRAIN_PRESETS[preset])
    if legacy:
        stages["broll"] = "sonnet" if (broll or {}).get("planner") == "claude" else "gemini"
        preset = "balanced" if stages == BRAIN_PRESETS["balanced"] else "custom"
    return {"preset": preset, "stages": stages,
            "thinking": raw.get("thinking") if raw.get("thinking") in THINKING else "deep",
            # B-roll's own level; profiles saved before it followed "thinking".
            "thinking_broll": (raw.get("thinking_broll") if raw.get("thinking_broll") in THINKING
                               else raw.get("thinking") if raw.get("thinking") in THINKING else "normal"),
            "fresh": _bool(raw.get("fresh"))}


def _float(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _selection(raw):
    """Sanitized selection block (DEFAULT_PROFILE["selection"])."""
    raw = raw if isinstance(raw, dict) else {}
    d = DEFAULT_PROFILE["selection"]
    share = _float(raw.get("dedupe_overlap"), 0.0, 100.0, d["dedupe_overlap"])
    target = raw.get("clip_target")
    try:
        lo, hi = sorted(max(5, min(180, int(float(v)))) for v in target)
        target = [lo, hi]
    except (TypeError, ValueError):
        target = None
    return {
        # 20 and 0.2 both mean 20 %.
        "dedupe_overlap": round(share / 100.0 if share > 1 else share, 3),
        "dedupe_seconds": round(_float(raw.get("dedupe_seconds"), 0.0, 60.0, d["dedupe_seconds"]), 1),
        "clip_target": target,
    }


def _hold(v):
    try:
        h = float(v)
    except (TypeError, ValueError):
        return None
    return round(min(4.0, max(1.0, h)), 1) if h > 0 else None


def _free_y(v):
    try:
        y = float(v)
    except (TypeError, ValueError):
        return None
    return round(y, 1) if 3.0 <= y <= 97.0 else None


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
                  "source": "local",
                  "engine": br.get("engine") if br.get("engine") in ("zimage", "flux") else "zimage",
                  "planner": br.get("planner") if br.get("planner") in ("gemini", "claude") else "gemini",
                  "style": br.get("style") if br.get("style") in ("auto", "photo", "neon", "drawing", "cinematic", "vintage", "3d", "comic", "diagram") else "photo",
                  "max": _int(br.get("max"), 1, 10, 6),
                  "mode": br.get("mode") if br.get("mode") in ("literal", "mixed", "concept") else "mixed",
                  # Claude may mark identifiable places / objects: a real photo (Openverse, CC0 / CC BY) instead of a generated image.
                  "real_photos": _bool(br.get("real_photos")),
                  # How many images per clip, relative to "max": fewer / normal / more (broll.DENSITY).
                  "density": br.get("density") if br.get("density") in ("less", "normal", "more") else "normal",
                  # "manual": the images are prepared but only cut in once you approve them.
                  "review": br.get("review") if br.get("review") in ("auto", "manual") else "auto",
                  "layout": br.get("layout") if br.get("layout") in ("rise", "full") else "full",
                  "position": br.get("position") if br.get("position") in ("below", "above") else "below",
                  # A height chosen by the user (the small card's centre, % from the top of the frame): wins over "position".
                  "y": _free_y(br.get("y")),
                  # How long each image stays (None = until the end of its sentence, else 1-4 s), how the small card
                  # comes in ("rise" from the edge / "fade") and the zoom just before it leaves (off / soft / strong).
                  "hold": _hold(br.get("hold")),
                  "enter": br.get("enter") if br.get("enter") in ("rise", "fade") else "rise",
                  "zoom": br.get("zoom") if br.get("zoom") in ("off", "soft", "strong") else "soft",
                  # The edge and shadow around the pictures: soft (thin, see-through edge), strong (the old white edge), none.
                  "border": br.get("border") if br.get("border") in ("soft", "strong", "none") else "soft",
                  "size": _int(br.get("size"), 18, 60, 28)},
        "auto_publish": {"enabled": _bool(ap.get("enabled")),
                         "platforms": [p for p in (ap.get("platforms") or []) if p in ("tiktok", "instagram", "youtube")]
                         or ["tiktok", "instagram", "youtube"]},
        "beta": {"selection_v2": _bool(beta.get("selection_v2")),
                 "series_titles": _bool(beta.get("series_titles")),
                 "series_name": str(beta.get("series_name") or "").strip()[:40],
                 "playbook": _bool(beta.get("playbook")),
                 "playbook_show": re.sub(r"[\r\n#]", "", str(beta.get("playbook_show") or "")).strip()[:60]},
        "selection": _selection(raw.get("selection")),
        "brain": _brain(raw.get("brain"), br),
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


def consume_fresh(profile_id):
    """The "fresh picks" switch is for ONE run: switch it off once a job has
    taken it."""
    profiles = load_profiles()
    for p in profiles:
        if p.get("id") == profile_id and (p.get("brain") or {}).get("fresh"):
            p["brain"]["fresh"] = False
            save_profiles(profiles)
            return True
    return False


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
        # The niche and upload profile travel with the project: publishing
        # picks the niche's hashtag pool from it (otherwise it fell back to
        # Gemini's guessed niche, which has no researched pool).
        "PLUS_PROFILE_JSON": json.dumps({"id": profile.get("id"), "name": p["name"],
                                         "niche": p.get("niche") or None,
                                         "upload_profile": p.get("upload_profile") or None,
                                         # The editor's later text calls (translate,
                                         # regenerate) follow the profile too.
                                         "brain": {"text": p["brain"]["stages"]["text"]}}),
    }
    # Who thinks at each step (ai_brain.choice reads BRAIN_<STAGE>).
    for k, v in p["brain"]["stages"].items():
        env[f"BRAIN_{k.upper()}"] = v
    env["CLAUDE_EFFORT_DETAIL"] = THINKING[p["brain"]["thinking"]]
    env["CLAUDE_EFFORT_BROLL"] = THINKING[p["brain"]["thinking_broll"]]
    if p["brain"]["fresh"]:
        env["AI_CACHE_REFRESH"] = "1"
    if p["hook_style"] != "none":
        env["AUTO_HOOK_STYLE"] = p["hook_style"]
        env["AUTO_HOOK_SECONDS"] = str(p["hook_seconds"])
    if p["target_clips"]:
        env["CLIP_TARGET_MIN"] = env["CLIP_TARGET_MAX"] = str(p["target_clips"])
    if p["fx"].get("reactions"):
        env["PLUS_REACTIONS"] = "1"
    if p["fx"].get("smooth_camera"):
        # Read by reframe_v2 (calm tracking + soft cuts); the zoom glides come
        # through PLUS_FX_JSON like every other fx option.
        env["SMOOTH_CAMERA"] = "1"
    if p["music"]["enabled"]:
        env["PLUS_MUSIC_MOOD"] = p["music"]["mood"]
        env["PLUS_MUSIC_VOLUME"] = str(p["music"]["volume"])
        env["PLUS_MUSIC_ON"] = "1"
    if p["broll"]["enabled"]:
        # The B-roll planner is the brain's "broll" step.
        env["PLUS_BROLL_JSON"] = json.dumps({**p["broll"],
                                             "planner": "gemini" if p["brain"]["stages"]["broll"] == "gemini"
                                             else "claude"})
    if p["beta"]["selection_v2"]:
        env["SELECTION_V2"] = "1"
    if p["beta"]["series_titles"] and p["beta"]["series_name"]:
        env["TITLE_SERIES"] = p["beta"]["series_name"]
    if p["beta"]["playbook"]:
        env["SYNAPSE_PLAYBOOK"] = "1"
        if p["beta"]["playbook_show"]:
            env["PLAYBOOK_SHOW"] = p["beta"]["playbook_show"]
    sel = p["selection"]
    if sel["dedupe_overlap"] > 0:
        env["CLIP_DEDUPE_OVERLAP"] = f"{sel['dedupe_overlap']:g}"
        env["CLIP_DEDUPE_SECONDS"] = f"{sel['dedupe_seconds']:g}"
    if sel["clip_target"]:
        env["CLIP_TARGET_MIN_SECONDS"], env["CLIP_TARGET_MAX_SECONDS"] = (str(v) for v in sel["clip_target"])
    return env
