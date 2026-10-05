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
    # The show the channel clips (4-oct-2026, one field for the old niche and
    # playbook_show): picks the hashtag pool, and names the show in the credit
    # line when the episode's title does not (playbook.split_show).
    "show": "",
    # The clip length, one of CLIP_FORMATS (4-oct-2026, instead of six numbers).
    "format": "standard",
    # The channel's name under the captions (blank = none).
    "watermark": "",
    # Images when something concrete is named (broll.py, the recipe in BROLL).
    # Off by default: it needs ComfyUI running on this PC, and a job without
    # it stops when the images cannot be made.
    "broll": {"enabled": False},
    "auto_publish": {"enabled": False, "platforms": ["tiktok", "instagram", "youtube"]},
    # What the channel is about.
    "selection": {
        # The playbook.TOPIC_BUCKETS the channel covers, said in the scoring
        # and clip-choice prompts; a clip outside them loses niche_weight
        # points of score, or is dropped with niche_only. niche_context: one
        # sentence on the channel, optional (JSON only). [] = off.
        "niche_topics": [], "niche_weight": 15, "niche_only": False, "niche_context": "",
    },
    # The next run ignores the AI memory (new picks), then switches itself off.
    "fresh": False,
}

# --- the house recipe: what every Clip Generator++ job does -----------------------------
# Captions: the natural look set in Montserrat ExtraBold (viral_fx.PRESETS["premium"]).
EDIT_STYLE = "premium"
# Hook at the top: the documentary line (hooks.HOOK_STYLES["docline"], H3 of
# the hook study of 2-oct-2026): the topic as a small yellow eyebrow, a short
# rule, the hook in sentence case with its payoff word in yellow (the brain's
# hook_accent); the title leaves at 3.3 s, the eyebrow and the rule stay.
HOOK_STYLE, HOOK_SECONDS = "docline", 3.3
# The picture: zooms aimed at the measured face; the premium framing of the
# reframe (framing.py, SMOOTH_CAMERA); reaction shots of the listener after a
# strong line (reactions.py); every layer before the captions encoded
# near-lossless (ffmpeg_utils.layer_encode_args).
FX = {"smart_framing": True, "smooth_camera": True, "reactions": True, "hq_chain": True}
# B-roll when the profile wants images: made on this PC (ComfyUI, Z-Image
# Turbo), "mixed" ideas (the thing named first), one hero + three wide cards,
# each picture's look read from what is said (visual_mood: its mood's words for
# the image model, its grade when it is cut in), a soft whoosh on the hero.
# Since 5-oct-2026 the « dessin » chain draws them all full screen ("full_width"
# below) and the whoosh marks the first one only.
BROLL = {"source": "local", "engine": "zimage", "style": "auto", "mode": "mixed", "density": "normal",
         "review": "auto", "layout": "mixed", "hero_res": "std", "label": False, "max": 6, "sfx": True,
         # The channel's teal/amber stamp in every picture's grade (visual_mood.SIGNATURE): 0 = none, 1 = a full
         # duotone; never on a picture whose colours or light the speaker describes (B-roll « ambiance », 2-oct-2026).
         "signature": 0.2,
         # A clear, natural face on every picture (broll.FACE_MODES: never / hero / always): the "turned away" rule
         # dated from FLUX's faces; Z-Image draws them right, the review marks a waxy one down, and a card of
         # anonymous backs reads cold (audit « sens », 1-oct-2026 evening).
         "faces": "always",
         # B-roll v2 (1-oct-2026): a second call writes the prompt of every picture of a set, each in its look
         # sheet (broll.direct_art), validated on the brain bench (JRE #2515 clips 1, 3, 5) the same day.
         "art_director": True,
         # B-roll v20 « la fiche » (3-oct-2026): the editor's shot specs, the prompt written by the code, a blind
         # check (broll_v20) — the art director above is the old chain's, kept for the bench only.
         # v21 « idées » (4-oct-2026): the round of ideas in text before the rendering (broll_ideas: art director,
         # verifier, viewer on the channel's own text), the hero chosen among the ideas kept.
         # v26 « dessin » (4-oct-2026, validated by the user as the final version): every picture drawn in the
         # episode's style charter by the art director, a safety verifier, one render per moment (broll_draw).
         "chain": "dessin", "ideas": True,
         # Step up (5-oct-2026, validated by the user): every drawing made 9:16 and shown alone, full screen,
         # 2.0-2.5 s, hard cut in and out, no push-in — never a card on the head (decision 5; the source's own
         # picture stays a card); the whoosh on the first drawing only, ~12 dB under the voice (decision 3,
         # "sfx" above).
         "full_width": True,
         # The opening drawing, 0-1.2 s under the hook (decision 8): coded, OFF until the A/B test (6 clips with /
         # 6 without, published 5-8 oct) is good at 48 h.
         "opening": False}
# Selection: two clips sharing more than 20 % (or 8 s) of each other keep the
# best one; an unclear hook gets one rewrite; the scoring pass hears the
# audio (audio_signals.py); the titles of a job are read as a set
# (playbook.title_set_problems). All with the Synapse Cut playbook on.
SELECTION = {"dedupe_overlap": 0.2, "dedupe_seconds": 8.0, "hook_check": True, "audio_signals": True,
             "title_variety": True, "playbook": True}

# A channel's clip length (4-oct-2026: three formats instead of six numbers). clip_min / clip_max = the hard limits;
# clip_target = the length to AIM for, asked for in the prompt (a clip over it is cut back to the sentence of its
# payoff). "standard" = the Joe Rogan profile's own numbers (the clip-selection audit of 30-sep); "short" and "long"
# are not yet tried on a job.
CLIP_FORMATS = {
    "short": {"clip_min": 10, "clip_max": 40, "clip_target": [15, 30]},
    "standard": {"clip_min": 15, "clip_max": 60, "clip_target": [25, 40]},
    "long": {"clip_min": 30, "clip_max": 90, "clip_target": [40, 60]},
}
# How many clips (4-oct-2026, validated by the user: « s'il y en a plus que deux de bons, on est bloqué à deux »): no
# number in the profile, the AI keeps every clip good enough to publish. The fewest the clip-choice prompt asks for
# (CLIP_COUNT_FLOOR) is 1, never padding; the ceiling stays clip_count_targets' (grows with the video, at most 12).
# Before: the profile's target_clips fixed the count (min = max) and the floor was 2.
CLIP_FLOOR = 1

# The AI brain, part of the house recipe since 4-oct-2026 (the user: « ça fonctionne très très bien », the
# Joe Rogan profile's own setting, no longer a profile choice): Claude at every step (ai_brain.STAGES), the light
# ones on Haiku. The « dessin » B-roll chain sets its art director and verifier itself (broll_draw: Opus, Sonnet).
BRAIN = {"brief_score": "haiku", "detail": "sonnet", "layout": "haiku", "broll": "sonnet", "broll_art": "sonnet",
         "image_review": "haiku", "hook": "sonnet", "text": "haiku"}
# Claude's effort: choosing the clips, the B-roll plan, the old chain's art direction.
BRAIN_EFFORT = {"detail": "medium", "broll": "medium", "broll_art": "high"}


def _float(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _selection(raw):
    """Sanitized selection block (DEFAULT_PROFILE["selection"])."""
    raw = raw if isinstance(raw, dict) else {}
    d = DEFAULT_PROFILE["selection"]
    import playbook
    topics = raw.get("niche_topics")
    topics = [t for t in (topics if isinstance(topics, (list, tuple)) else [])
              if t in playbook.TOPIC_BUCKETS and t != "other"]
    return {
        "niche_topics": list(dict.fromkeys(topics)),
        "niche_weight": round(_float(raw.get("niche_weight"), 0.0, 100.0, d["niche_weight"]), 1),
        "niche_only": _bool(raw.get("niche_only")),
        "niche_context": re.sub(r"\s+", " ", str(raw.get("niche_context") or "")).strip()[:200],
    }


def _format(raw):
    """The profile's CLIP_FORMATS key. A profile saved before 4-oct-2026 had
    numbers: the format whose aim is nearest to its own (its min/max else)."""
    if raw.get("format") in CLIP_FORMATS:
        return raw["format"]
    sel = raw.get("selection") if isinstance(raw.get("selection"), dict) else {}
    try:
        mid = sum(float(v) for v in sel.get("clip_target")) / 2
    except (TypeError, ValueError):
        try:
            mid = (float(raw["clip_min"]) + float(raw["clip_max"])) / 2
        except (KeyError, TypeError, ValueError):
            return DEFAULT_PROFILE["format"]
    return min(CLIP_FORMATS, key=lambda k: abs(sum(CLIP_FORMATS[k]["clip_target"]) / 2 - mid))


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
    ap = raw.get("auto_publish") or {}
    br = raw.get("broll") or {}
    # Before 4-oct-2026: the show's name (playbook_show, once in the "beta"
    # block) and the hashtag niche were two fields; the show's name wins.
    show = raw.get("show")
    if show is None:
        show = raw.get("playbook_show") or (raw.get("beta") or {}).get("playbook_show") or raw.get("niche")
    return {
        "name": (str(raw.get("name") or "").strip() or "Profile")[:60],
        "upload_profile": str(raw.get("upload_profile") or "").strip()[:80],
        "show": re.sub(r"[\r\n#]", "", str(show or "")).strip()[:60],
        "format": _format(raw),
        "watermark": re.sub(r"[^\w .@&'-]", "", str(raw.get("watermark") or ""))[:30],
        "broll": {"enabled": _bool(br.get("enabled"))},
        "auto_publish": {"enabled": _bool(ap.get("enabled")),
                         "platforms": [p for p in (ap.get("platforms") or []) if p in ("tiktok", "instagram", "youtube")]
                         or ["tiktok", "instagram", "youtube"]},
        "selection": _selection(raw.get("selection")),
        # Profiles saved before 4-oct-2026 kept it in their brain block.
        "fresh": _bool(raw["fresh"] if "fresh" in raw else (raw.get("brain") or {}).get("fresh")),
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
        if p.get("id") == profile_id and (p.get("fresh") or (p.get("brain") or {}).get("fresh")):
            p["fresh"] = False
            p.pop("brain", None)
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
    fmt = CLIP_FORMATS[p["format"]]
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
        "CLIP_MIN_SECONDS": str(fmt["clip_min"]),
        "CLIP_MAX_SECONDS": str(fmt["clip_max"]),
        "CLIP_TARGET_MIN_SECONDS": str(fmt["clip_target"][0]),
        "CLIP_TARGET_MAX_SECONDS": str(fmt["clip_target"][1]),
        # The show (as the niche) and upload profile travel with the project:
        # publishing picks the niche's hashtag pool from it (otherwise it fell
        # back to Gemini's guessed niche, which has no researched pool).
        "PLUS_PROFILE_JSON": json.dumps({"id": profile.get("id"), "name": p["name"],
                                         "niche": p["show"] or None,
                                         "upload_profile": p.get("upload_profile") or None,
                                         # The editor's later text calls (translate,
                                         # regenerate) follow the profile too.
                                         "brain": {"text": BRAIN["text"]}}),
    }
    # Who thinks at each step (ai_brain.choice reads BRAIN_<STAGE>).
    for k, v in BRAIN.items():
        env[f"BRAIN_{k.upper()}"] = v
    env["CLAUDE_EFFORT_DETAIL"] = BRAIN_EFFORT["detail"]
    env["CLAUDE_EFFORT_BROLL"] = BRAIN_EFFORT["broll"]
    env["CLAUDE_EFFORT_BROLL_ART"] = BRAIN_EFFORT["broll_art"]
    if p["fresh"]:
        env["AI_CACHE_REFRESH"] = "1"
    if p["broll"]["enabled"]:
        # The B-roll planner is the brain's "broll" step.
        env["PLUS_BROLL_JSON"] = json.dumps({**BROLL, "enabled": True,
                                             "planner": "gemini" if BRAIN["broll"] == "gemini" else "claude"})
    if p["show"]:
        env["PLAYBOOK_SHOW"] = p["show"]
    sel = p["selection"]
    if sel["niche_topics"]:
        env["NICHE_TOPICS"] = ",".join(sel["niche_topics"])
        env["NICHE_WEIGHT"] = f"{sel['niche_weight']:g}"
        if sel["niche_only"]:
            env["NICHE_ONLY"] = "1"
        if sel["niche_context"]:
            env["NICHE_CONTEXT"] = sel["niche_context"]
    # The floor of the clip-choice prompt only (CLIP_FLOOR): no count, no ceiling of the profile's own.
    env["CLIP_COUNT_FLOOR"] = str(CLIP_FLOOR)
    return env
