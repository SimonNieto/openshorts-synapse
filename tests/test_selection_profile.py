"""Clip Generator++ profile -> job env for the selection block (plus.py).

Every setting is off by default: a profile saved before the block existed
must start the same job as before."""
import plus


def _env(selection=None, **profile):
    raw = {"name": "t", **profile}
    if selection is not None:
        raw["selection"] = selection
    return plus.job_env(raw)


# The channel's own choices: nothing of these without the block.
CHANNEL_VARS = ("CLIP_TARGET_MIN_SECONDS", "CLIP_TARGET_MAX_SECONDS", "NICHE_TOPICS", "NICHE_WEIGHT",
                "NICHE_ONLY", "NICHE_CONTEXT", "CLIP_COUNT_FLOOR")
# The house recipe (plus.SELECTION, 1-oct-2026): on for every job, whatever the profile says.
RECIPE_VARS = {"CLIP_DEDUPE_OVERLAP": "0.2", "CLIP_DEDUPE_SECONDS": "8", "HOOK_CHECK": "1",
               "AUDIO_SIGNALS": "1", "TITLE_VARIETY": "1", "SYNAPSE_PLAYBOOK": "1"}


def test_a_profile_without_the_block_sets_nothing_of_its_own():
    env = _env()
    assert not [k for k in CHANNEL_VARS if k in env]
    assert {k: env[k] for k in RECIPE_VARS} == RECIPE_VARS
    assert plus.sanitize({})["selection"] == plus.DEFAULT_PROFILE["selection"]


def test_garbage_falls_back_to_the_defaults():
    assert plus.sanitize({"selection": "x"})["selection"] == plus.DEFAULT_PROFILE["selection"]
    assert plus.sanitize({"selection": {"clip_target": "x", "min_clips": None}})["selection"] \
        == plus.DEFAULT_PROFILE["selection"]


def test_the_recipe_cannot_be_switched_off_by_a_profile():
    env = _env({"dedupe_overlap": 0, "hook_check": False, "audio_signals": False, "title_variety": False},
               beta={"playbook": False})
    assert {k: env[k] for k in RECIPE_VARS} == RECIPE_VARS
    assert "dedupe_overlap" not in plus.sanitize({"selection": {"dedupe_overlap": 0}})["selection"]


def test_clip_target_reaches_the_job():
    env = _env({"clip_target": [25, 40]}, clip_min=15, clip_max=60)
    assert env["CLIP_TARGET_MIN_SECONDS"] == "25" and env["CLIP_TARGET_MAX_SECONDS"] == "40"
    assert env["CLIP_MIN_SECONDS"] == "15" and env["CLIP_MAX_SECONDS"] == "60", "the band stays the hard limit"
    assert _env({"clip_target": [40, 25]})["CLIP_TARGET_MIN_SECONDS"] == "25", "given backwards: reordered"
    for bad in (None, "x", [25], [25, 40, 60], {"a": 1}):
        env = _env({"clip_target": bad})
        assert "CLIP_TARGET_MAX_SECONDS" not in env and "CLIP_TARGET_MIN_SECONDS" not in env, bad


SYNAPSE_TOPICS = ["brain_danger", "substances", "psychosis_mental_illness", "mind_psychology",
                  "self_improvement", "medical_mystery", "crime_dark"]


def test_niche_reaches_the_job():
    env = _env({"niche_topics": SYNAPSE_TOPICS + ["cooking", "other", "substances"], "niche_only": True,
                "niche_context": "The brain\nand the mind."})
    assert env["NICHE_TOPICS"] == ",".join(SYNAPSE_TOPICS), "unknown buckets, 'other' and repeats are left out"
    assert env["NICHE_WEIGHT"] == "15" and env["NICHE_ONLY"] == "1"
    assert env["NICHE_CONTEXT"] == "The brain and the mind."
    env = _env({"niche_topics": ["substances"], "niche_weight": 25})
    assert env["NICHE_WEIGHT"] == "25" and "NICHE_ONLY" not in env and "NICHE_CONTEXT" not in env
    for off in ([], None, "substances", ["cooking"]):
        assert "NICHE_TOPICS" not in _env({"niche_topics": off, "niche_only": True}), off


def test_min_clips_is_the_prompt_floor_only():
    env = _env({"min_clips": 2})
    assert env["CLIP_COUNT_FLOOR"] == "2" and "CLIP_TARGET_MIN" not in env and "CLIP_TARGET_MAX" not in env
    # target_clips fixes the count and wins
    env = _env({"min_clips": 2}, target_clips=5)
    assert "CLIP_COUNT_FLOOR" not in env and env["CLIP_TARGET_MIN"] == env["CLIP_TARGET_MAX"] == "5"
    for off in (None, 0, "", "x"):
        assert "CLIP_COUNT_FLOOR" not in _env({"min_clips": off}), off


def test_audio_signals_and_title_variety_are_always_on():
    assert _env()["AUDIO_SIGNALS"] == "1" and _env({"audio_signals": False})["AUDIO_SIGNALS"] == "1"
    assert _env()["TITLE_VARIETY"] == "1" and _env({"title_variety": False})["TITLE_VARIETY"] == "1"
