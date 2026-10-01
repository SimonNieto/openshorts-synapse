"""The house recipe (plus.py, 1-oct-2026): how a clip is made is no longer a profile choice.

A profile keeps a channel's own facts (account, niche, lengths, brain, B-roll on/off, watermark,
publishing). Everything else the profile editor used to offer is fixed in plus.EDIT_STYLE / HOOK_* /
FX / BROLL / SELECTION, reaches every job through job_env, and an old saved profile loses those keys
without breaking."""
import json

import plus
import viral_fx
import broll


OLD_PROFILE = {
    "name": "Joe Rogan · natural", "upload_profile": "default", "niche": "Joe Rogan podcast",
    "clip_min": 15, "clip_max": 60, "target_clips": 2, "edit_style": "punchy", "hook_style": "classic",
    "hook_seconds": 5, "hook_box": True, "watermark": "@TheSynapseCut",
    "fx": {"smart_framing": True, "look": True, "spotlight": True, "streaks": True, "reactions": False,
           "smooth_camera": False, "hq_chain": False},
    "music": {"enabled": True, "mood": "calm", "volume": 0.1},
    "broll": {"enabled": True, "engine": "flux", "style": "comic", "layout": "rise", "real_photos": True,
              "review": "manual", "grade": "off", "sfx": False, "house_look": "neon"},
    "auto_publish": {"enabled": False, "platforms": ["tiktok"]},
    "beta": {"playbook": False, "playbook_show": "The Show"},
    "selection": {"dedupe_overlap": 0, "clip_target": [25, 40], "niche_topics": ["substances"], "niche_only": True,
                  "min_clips": 2, "hook_check": False, "audio_signals": False, "title_variety": False},
    "brain": {"preset": "claude"},
}


class TestSanitize:
    def test_keeps_the_channel_s_facts_and_drops_the_rest(self):
        p = plus.sanitize(OLD_PROFILE)
        assert set(p) == {"name", "upload_profile", "niche", "clip_min", "clip_max", "target_clips", "watermark",
                          "broll", "auto_publish", "playbook_show", "selection", "brain"}
        assert p["broll"] == {"enabled": True}
        assert p["watermark"] == "@TheSynapseCut" and p["clip_max"] == 60 and p["target_clips"] == 2
        assert p["playbook_show"] == "The Show", "read from the old beta block"
        assert set(p["selection"]) == {"clip_target", "niche_topics", "niche_weight", "niche_only", "niche_context",
                                       "min_clips"}

    def test_the_defaults_are_the_same_shape(self):
        assert set(plus.sanitize({})) == set(plus.sanitize(OLD_PROFILE))
        assert plus.sanitize({})["broll"] == {"enabled": False}

    def test_the_new_show_field_wins_over_the_old_block(self):
        assert plus.sanitize({"playbook_show": "New", "beta": {"playbook_show": "Old"}})["playbook_show"] == "New"
        assert plus.sanitize({"playbook_show": "", "beta": {"playbook_show": "Old"}})["playbook_show"] == ""


class TestJobEnv:
    def test_every_job_gets_the_recipe_whatever_the_profile_said(self):
        for profile in ({}, OLD_PROFILE):
            env = plus.job_env(profile)
            assert env["EDIT_STYLE"] == "premium"
            assert (env["AUTO_HOOK"], env["AUTO_HOOK_STYLE"], env["AUTO_HOOK_SECONDS"]) == ("1", "bold", "3")
            assert env["SMOOTH_CAMERA"] == env["PLUS_REACTIONS"] == env["PLUS_HQ_CHAIN"] == "1"
            assert env["SYNAPSE_PLAYBOOK"] == env["HOOK_CHECK"] == env["AUDIO_SIGNALS"] == env["TITLE_VARIETY"] == "1"
            assert (env["CLIP_DEDUPE_OVERLAP"], env["CLIP_DEDUPE_SECONDS"]) == ("0.2", "8")
            assert "PLUS_MUSIC_ON" not in env
            fx = json.loads(env["PLUS_FX_JSON"])
            assert fx["smooth_camera"] and fx["reactions"] and fx["hq_chain"] and fx["smart_framing"]
            assert "look" not in fx and "spotlight" not in fx and "streaks" not in fx

    def test_the_watermark_travels_with_the_fx(self):
        assert json.loads(plus.job_env(OLD_PROFILE)["PLUS_FX_JSON"])["watermark"] == "@TheSynapseCut"
        assert json.loads(plus.job_env({})["PLUS_FX_JSON"])["watermark"] is None

    def test_broll_is_the_recipe_plus_the_switch(self):
        cfg = json.loads(plus.job_env(OLD_PROFILE)["PLUS_BROLL_JSON"])
        for k, v in plus.BROLL.items():
            assert cfg[k] == v, k
        assert cfg["enabled"] is True and cfg["planner"] == "claude"
        assert cfg["engine"] == "zimage" and cfg["layout"] == "mixed" and cfg["review"] == "auto"
        assert "real_photos" not in cfg
        assert "PLUS_BROLL_JSON" not in plus.job_env({**OLD_PROFILE, "broll": {"enabled": False}})

    def test_the_channel_s_own_choices_still_reach_the_job(self):
        env = plus.job_env(OLD_PROFILE)
        assert (env["CLIP_MIN_SECONDS"], env["CLIP_MAX_SECONDS"]) == ("15", "60")
        assert env["CLIP_TARGET_MIN"] == env["CLIP_TARGET_MAX"] == "2"
        assert (env["CLIP_TARGET_MIN_SECONDS"], env["CLIP_TARGET_MAX_SECONDS"]) == ("25", "40")
        assert env["NICHE_TOPICS"] == "substances" and env["NICHE_ONLY"] == "1"
        assert env["PLAYBOOK_SHOW"] == "The Show"
        assert env["BRAIN_DETAIL"] in plus.BRAIN_CHOICES


class TestTheRecipeMatchesTheCode:
    def test_edit_style_and_hook_exist(self):
        import hooks
        assert plus.EDIT_STYLE in viral_fx.PRESETS
        assert plus.HOOK_STYLE in hooks.HOOK_STYLES and 2 <= plus.HOOK_SECONDS <= 10

    def test_broll_recipe_values_are_known_to_broll(self):
        assert plus.BROLL["engine"] in broll.ENGINES and broll.ENGINES == ("zimage",)
        assert plus.BROLL["style"] == "auto" and plus.BROLL["mode"] in broll.MODE_RULES
        assert plus.BROLL["density"] in broll.DENSITY and plus.BROLL["grade"] in broll.GRADES
        assert plus.BROLL["hero_res"] in broll.HERO_GEN and plus.BROLL["layout"] == "mixed"

    def test_what_was_removed_is_gone(self):
        for name in ("plan_shots", "face_track", "spotlight_moments", "_streak_frames", "mix_music"):
            assert not hasattr(viral_fx, name), name
        for name in ("free_photo", "openverse_image", "gemini_image", "REAL_PHOTO_RULE"):
            assert not hasattr(broll, name), name
        for name in ("music_library", "pick_track"):
            assert not hasattr(plus, name), name
