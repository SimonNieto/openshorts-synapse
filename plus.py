"""Clip Generator++ — channel profiles, the house recipe, per-job env.

A profile is a channel's own facts, picked in one click before a run: account
+ niche, clip lengths and the band to aim for, which AI thinks at each step,
B-roll images or not, the name under the captions, auto-publish. How a clip
is made (captions, hook, camera, B-roll drawing, selection checks) is the
house recipe, fixed below. The classic Clip Generator never reads any of
this: a job only changes when it is started from Clip Generator++ with a
profile.

Stored server-side (clip_profiles.json, self-host), so the same profiles are
there from any browser and on any machine the project moves to.
"""
import json
import os
import re
import time
import uuid

PROFILE_FILE = "clip_profiles.json"

# A profile is a CHANNEL's own facts: its account, its niche, how long its
# clips run, which AI thinks, whether it wants B-roll images, its name under the
# captions, publishing. How a clip is MADE is not a profile choice any more:
# the house recipe below (edit style, hook, camera, B-roll drawing, selection
# checks) is what every job does. Until 1-oct-2026 each of these was a switch
# in the profile editor; the ones that proved themselves on real clips were
# switched on everywhere and the rest were removed with their code (jump
# zooms, shake, "sharp look", spotlight, light streaks, music bed, FLUX, free
# photos, the classic hook box). Old saved profiles still load: sanitize()
# drops the keys it no longer knows.
DEFAULT_PROFILE = {
    "name": "Podcast · premium",
    "upload_profile": "",
    "niche": "",
    "clip_min": 15,
    "clip_max": 35,
    "target_clips": None,
    # The channel's name under the captions (blank = none).
    "watermark": "",
    # Images when something concrete is named (broll.py, the recipe in BROLL).
    # Off by default: it needs ComfyUI running on this PC, and a job without
    # it stops when the images cannot be made.
    "broll": {"enabled": False},
    "auto_publish": {"enabled": False, "platforms": ["tiktok", "instagram", "youtube"]},
    # The show's name for the playbook's credit line (empty = read from the
    # source's file name). JSON only, no screen.
    "playbook_show": "",
    # What the channel is about and how long its clips should AIM to be.
    "selection": {
        # [low, high] seconds to AIM for inside clip_min..clip_max (the hard
        # limits): asked for in the prompt, and a clip over it is cut back to
        # the sentence of its payoff. None = off.
        "clip_target": None,
        # The playbook.TOPIC_BUCKETS the channel covers, said in the scoring
        # and clip-choice prompts; a clip outside them loses niche_weight
        # points of score, or is dropped with niche_only. niche_context: one
        # sentence on the channel, optional. [] = off.
        "niche_topics": [], "niche_weight": 15, "niche_only": False, "niche_context": "",
        # The fewest clips the clip-choice prompt asks for (None = the usual
        # floor, 6 for a long source). With a niche, a source that is mostly
        # off niche should be allowed to give 2 clips, not be padded to 6.
        "min_clips": None,
    },
    # Which AI runs each step (ai_brain.STAGES): "gemini" or a Claude model.
    # "thinking" = Claude's effort on the two decision steps (clips, B-roll);
    # "fresh" = the next run ignores the AI memory (then switches itself off).
    "brain": {"preset": "balanced", "stages": None, "thinking": "deep", "thinking_broll": "normal", "fresh": False},
}

# --- the house recipe: what every Clip Generator++ job does -----------------------------
# Captions: the natural look set in Montserrat ExtraBold (viral_fx.PRESETS["premium"]).
EDIT_STYLE = "premium"
# Hook at the top: the bold headline (hooks.HOOK_STYLES["bold"]), 3 s on screen.
HOOK_STYLE, HOOK_SECONDS = "bold", 3
# The picture: zooms aimed at the measured face; the premium framing of the
# reframe (framing.py, SMOOTH_CAMERA); reaction shots of the listener after a
# strong line (reactions.py); every layer before the captions encoded
# near-lossless (ffmpeg_utils.layer_encode_args).
FX = {"smart_framing": True, "smooth_camera": True, "reactions": True, "hq_chain": True}
# B-roll when the profile wants images: made on this PC (ComfyUI, Z-Image
# Turbo), the style picked per image by the planner, "mixed" ideas (half
# literal, half the idea behind the words), one hero + three wide cards, the
# documentary house look and the cinematic grade, a soft whoosh on the hero.
BROLL = {"source": "local", "engine": "zimage", "style": "auto", "mode": "mixed", "density": "normal",
         "review": "auto", "layout": "mixed", "hero_res": "std", "label": False, "max": 6,
         "house_look": ("cinematic documentary photograph, 35 mm lens, natural light, teal and amber grade, "
                        "fine film grain, shallow depth of field"),
         "grade": "cinematic", "sfx": True,
         # One photographic family per clip (broll.FAMILIES): "auto" = the art director picks it (the default
         # family without one), else its name.
         "style_family": "auto",
         # A clear, natural face on every picture (broll.FACE_MODES: never / hero / always): the "turned away" rule
         # dated from FLUX's faces; Z-Image draws them right, the review marks a waxy one down, and a card of
         # anonymous backs reads cold (audit « sens », 1-oct-2026 evening).
         "faces": "always",
         # B-roll v2 (1-oct-2026): a second call writes the prompt of every picture of a set in the channel's
         # look (broll.direct_art), validated on the brain bench (JRE #2515 clips 1, 3, 5) the same day.
         "art_director": True}
# Selection: two clips sharing more than 20 % (or 8 s) of each other keep the
# best one; an unclear hook gets one rewrite; the scoring pass hears the
# audio (audio_signals.py); the titles of a job are read as a set
# (playbook.title_set_problems). All with the Synapse Cut playbook on.
SELECTION = {"dedupe_overlap": 0.2, "dedupe_seconds": 8.0, "hook_check": True, "audio_signals": True,
             "title_variety": True, "playbook": True}

BRAIN_STAGES = ("brief_score", "detail", "layout", "broll", "broll_art", "image_review", "hook", "text")
BRAIN_CHOICES = ("gemini", "haiku", "sonnet", "opus")
BRAIN_PRESETS = {
    # No Claude at all: every step on Gemini (billed per token, cheap).
    "gemini": {k: "gemini" for k in BRAIN_STAGES},
    # "Gemini reads, Claude decides" — the default.
    "balanced": {"brief_score": "gemini", "detail": "sonnet", "layout": "gemini", "broll": "sonnet",
                 "broll_art": "sonnet", "image_review": "gemini", "hook": "sonnet", "text": "gemini"},
    # Claude everywhere, the light steps on Haiku (a fraction of the plan's usage).
    "claude": {"brief_score": "haiku", "detail": "sonnet", "layout": "haiku", "broll": "sonnet",
               "broll_art": "sonnet", "image_review": "haiku", "hook": "sonnet", "text": "haiku"},
    # Claude everywhere, Opus on the two decisions.
    "claude_max": {"brief_score": "sonnet", "detail": "opus", "layout": "haiku", "broll": "opus",
                   "broll_art": "sonnet", "image_review": "sonnet", "hook": "sonnet", "text": "haiku"},
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
    target = raw.get("clip_target")
    try:
        lo, hi = sorted(max(5, min(180, int(float(v)))) for v in target)
        target = [lo, hi]
    except (TypeError, ValueError):
        target = None
    import playbook
    topics = raw.get("niche_topics")
    topics = [t for t in (topics if isinstance(topics, (list, tuple)) else [])
              if t in playbook.TOPIC_BUCKETS and t != "other"]
    min_clips = raw.get("min_clips")
    return {
        "clip_target": target,
        "niche_topics": list(dict.fromkeys(topics)),
        "niche_weight": round(_float(raw.get("niche_weight"), 0.0, 100.0, d["niche_weight"]), 1),
        "niche_only": _bool(raw.get("niche_only")),
        "niche_context": re.sub(r"\s+", " ", str(raw.get("niche_context") or "")).strip()[:200],
        "min_clips": _int(min_clips, 1, 15, None) if min_clips not in (None, "", 0, "0") else None,
    }


def _bool(v):
    return bool(v) and str(v).lower() not in ("0", "false", "no")


def _int(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError):
        return default


def sanitize(raw):
    """Whitelist + clamp every field: the profile becomes env vars of a job.
    Keys of older profiles (fx, music, edit_style, hook_style, beta, the
    B-roll drawing...) are dropped: the house recipe replaced them."""
    raw = raw or {}
    d = DEFAULT_PROFILE
    ap = raw.get("auto_publish") or {}
    br = raw.get("broll") or {}
    clip_min = _int(raw.get("clip_min"), 5, 170, d["clip_min"])
    clip_max = _int(raw.get("clip_max"), 10, 180, d["clip_max"])
    if clip_max < clip_min + 5:
        clip_max = clip_min + 5
    target = raw.get("target_clips")
    # The show's name moved out of the old "beta" block.
    show = raw.get("playbook_show")
    if show is None:
        show = (raw.get("beta") or {}).get("playbook_show")
    return {
        "name": (str(raw.get("name") or "").strip() or "Profile")[:60],
        "upload_profile": str(raw.get("upload_profile") or "").strip()[:80],
        "niche": str(raw.get("niche") or "").strip()[:80],
        "clip_min": clip_min,
        "clip_max": clip_max,
        "target_clips": _int(target, 1, 15, None) if target not in (None, "", 0, "0") else None,
        "watermark": re.sub(r"[^\w .@&'-]", "", str(raw.get("watermark") or ""))[:30],
        "broll": {"enabled": _bool(br.get("enabled"))},
        "auto_publish": {"enabled": _bool(ap.get("enabled")),
                         "platforms": [p for p in (ap.get("platforms") or []) if p in ("tiktok", "instagram", "youtube")]
                         or ["tiktok", "instagram", "youtube"]},
        "playbook_show": re.sub(r"[\r\n#]", "", str(show or "")).strip()[:60],
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


# --- job env ----------------------------------------------------------------------------

def job_env(profile):
    """Env vars main.py reads for a Clip Generator++ job."""
    p = sanitize(profile)
    env = {
        # --- the house recipe (EDIT_STYLE, HOOK_*, FX, SELECTION above) ---
        "EDIT_STYLE": EDIT_STYLE,
        "PLUS_FX_JSON": json.dumps({**FX, "watermark": p["watermark"] or None}),
        "AUTO_HOOK": "1",
        "AUTO_HOOK_STYLE": HOOK_STYLE,
        "AUTO_HOOK_SECONDS": str(HOOK_SECONDS),
        "PLUS_REACTIONS": "1",
        # Read by reframe_v2: the premium framing (framing.py) and soft cuts.
        "SMOOTH_CAMERA": "1",
        # Read by ffmpeg_utils.layer_encode_args at every layer of the clip's render chain.
        "PLUS_HQ_CHAIN": "1",
        # Every clip ends on a full stop (main.end_on_sentence): a clip
        # stopping on a dangling "cause..." is never wanted.
        "CLEAN_END": "1",
        "SYNAPSE_PLAYBOOK": "1",
        "CLIP_DEDUPE_OVERLAP": f"{SELECTION['dedupe_overlap']:g}",
        "CLIP_DEDUPE_SECONDS": f"{SELECTION['dedupe_seconds']:g}",
        "HOOK_CHECK": "1",
        "AUDIO_SIGNALS": "1",
        "TITLE_VARIETY": "1",
        # --- the channel's own facts ---
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
    if p["target_clips"]:
        env["CLIP_TARGET_MIN"] = env["CLIP_TARGET_MAX"] = str(p["target_clips"])
    if p["broll"]["enabled"]:
        # The B-roll planner is the brain's "broll" step.
        env["PLUS_BROLL_JSON"] = json.dumps({**BROLL, "enabled": True,
                                             "planner": "gemini" if p["brain"]["stages"]["broll"] == "gemini"
                                             else "claude"})
    if p["playbook_show"]:
        env["PLAYBOOK_SHOW"] = p["playbook_show"]
    sel = p["selection"]
    if sel["clip_target"]:
        env["CLIP_TARGET_MIN_SECONDS"], env["CLIP_TARGET_MAX_SECONDS"] = (str(v) for v in sel["clip_target"])
    if sel["niche_topics"]:
        env["NICHE_TOPICS"] = ",".join(sel["niche_topics"])
        env["NICHE_WEIGHT"] = f"{sel['niche_weight']:g}"
        if sel["niche_only"]:
            env["NICHE_ONLY"] = "1"
        if sel["niche_context"]:
            env["NICHE_CONTEXT"] = sel["niche_context"]
    if sel["min_clips"] and not p["target_clips"]:
        # The floor of the clip-choice prompt only; target_clips (above)
        # fixes the count and wins.
        env["CLIP_COUNT_FLOOR"] = str(sel["min_clips"])
    return env
