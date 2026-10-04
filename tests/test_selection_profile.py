"""Clip Generator++ profile -> job env for the selection block (plus.py).

Every setting is off by default: a profile saved before the block existed
must start the same job as before."""
import plus


def _env(selection=None, **profile):
    raw = {"name": "t", **profile}
    if selection is not None:
        raw["selection"] = selection
    return plus.job_env(raw)


# The channel's topics: nothing of these without the block.
CHANNEL_VARS = ("NICHE_TOPICS", "NICHE_WEIGHT", "NICHE_ONLY", "NICHE_CONTEXT")
# The house recipe (plus.SELECTION, 1-oct-2026): on for every job, whatever the profile says.
RECIPE_VARS = {"CLIP_DEDUPE_OVERLAP": "0.2", "CLIP_DEDUPE_SECONDS": "8", "HOOK_CHECK": "1",
               "AUDIO_SIGNALS": "1", "TITLE_VARIETY": "1", "SYNAPSE_PLAYBOOK": "1"}


def test_a_profile_without_the_block_sets_nothing_of_its_own():
    env = _env()
    assert not [k for k in CHANNEL_VARS if k in env]
    assert {k: env[k] for k in RECIPE_VARS} == RECIPE_VARS
    assert (env["CLIP_TARGET_MIN_SECONDS"], env["CLIP_TARGET_MAX_SECONDS"]) == ("25", "40"), "the standard format"
    assert plus.sanitize({})["selection"] == plus.DEFAULT_PROFILE["selection"]


def test_garbage_falls_back_to_the_defaults():
    assert plus.sanitize({"selection": "x"})["selection"] == plus.DEFAULT_PROFILE["selection"]
    assert plus.sanitize({"selection": {"clip_target": "x", "min_clips": None}})["selection"] \
        == plus.DEFAULT_PROFILE["selection"]
    assert plus.sanitize({"format": "huge"})["format"] == "standard"


def test_the_recipe_cannot_be_switched_off_by_a_profile():
    env = _env({"dedupe_overlap": 0, "hook_check": False, "audio_signals": False, "title_variety": False},
               beta={"playbook": False})
    assert {k: env[k] for k in RECIPE_VARS} == RECIPE_VARS
    assert "dedupe_overlap" not in plus.sanitize({"selection": {"dedupe_overlap": 0}})["selection"]


def test_the_format_reaches_the_job():
    # 4-oct-2026: three formats instead of the six numbers
    for name, f in plus.CLIP_FORMATS.items():
        env = _env(format=name)
        assert (env["CLIP_MIN_SECONDS"], env["CLIP_MAX_SECONDS"]) == (str(f["clip_min"]), str(f["clip_max"]))
        assert [int(env["CLIP_TARGET_MIN_SECONDS"]), int(env["CLIP_TARGET_MAX_SECONDS"])] == f["clip_target"]
        assert f["clip_min"] <= f["clip_target"][0] < f["clip_target"][1] <= f["clip_max"], name
    std = plus.CLIP_FORMATS["standard"]
    assert (std["clip_min"], std["clip_max"], std["clip_target"], std["min_clips"]) == (15, 60, [25, 40], 2), \
        "the Joe Rogan profile's own numbers"


def test_an_old_profile_s_numbers_become_the_nearest_format():
    assert plus.sanitize({"clip_min": 15, "clip_max": 60, "selection": {"clip_target": [25, 40]}})["format"] == "standard"
    assert plus.sanitize({"selection": {"clip_target": [45, 60]}})["format"] == "long"
    assert plus.sanitize({"clip_min": 15, "clip_max": 35})["format"] == "short"
    assert plus.sanitize({"format": "long", "clip_min": 10, "clip_max": 20})["format"] == "long", "the format wins"
    assert plus.sanitize({"selection": {"clip_target": "x"}, "clip_min": "y"})["format"] == "standard"


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


def test_the_format_s_floor_is_the_prompt_floor_only():
    env = _env()
    assert env["CLIP_COUNT_FLOOR"] == "2" and "CLIP_TARGET_MIN" not in env and "CLIP_TARGET_MAX" not in env
    # target_clips fixes the count and wins
    env = _env(target_clips=5)
    assert "CLIP_COUNT_FLOOR" not in env and env["CLIP_TARGET_MIN"] == env["CLIP_TARGET_MAX"] == "5"


def test_audio_signals_and_title_variety_are_always_on():
    assert _env()["AUDIO_SIGNALS"] == "1" and _env({"audio_signals": False})["AUDIO_SIGNALS"] == "1"
    assert _env()["TITLE_VARIETY"] == "1" and _env({"title_variety": False})["TITLE_VARIETY"] == "1"
