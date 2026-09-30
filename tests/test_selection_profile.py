"""Clip Generator++ profile -> job env for the selection block (plus.py).

Every setting is off by default: a profile saved before the block existed
must start the same job as before."""
import plus


def _env(selection=None, **profile):
    raw = {"name": "t", **profile}
    if selection is not None:
        raw["selection"] = selection
    return plus.job_env(raw)


NEW_VARS = ("CLIP_DEDUPE_OVERLAP", "CLIP_DEDUPE_SECONDS", "CLIP_TARGET_MIN_SECONDS",
            "CLIP_TARGET_MAX_SECONDS")


def test_a_profile_without_the_block_sets_nothing_new():
    env = _env()
    assert not [k for k in NEW_VARS if k in env]
    assert plus.sanitize({})["selection"] == plus.DEFAULT_PROFILE["selection"]


def test_garbage_falls_back_to_the_defaults():
    assert plus.sanitize({"selection": "x"})["selection"] == plus.DEFAULT_PROFILE["selection"]
    assert plus.sanitize({"selection": {"dedupe_overlap": "x", "dedupe_seconds": None}})["selection"] \
        == plus.DEFAULT_PROFILE["selection"]


def test_dedupe_reaches_the_job():
    env = _env({"dedupe_overlap": 0.2, "dedupe_seconds": 8})
    assert env["CLIP_DEDUPE_OVERLAP"] == "0.2" and env["CLIP_DEDUPE_SECONDS"] == "8"
    # 20 is read as 20 %
    assert _env({"dedupe_overlap": 20})["CLIP_DEDUPE_OVERLAP"] == "0.2"
    assert "CLIP_DEDUPE_OVERLAP" not in _env({"dedupe_overlap": 0})


def test_clip_target_reaches_the_job():
    env = _env({"clip_target": [25, 40]}, clip_min=15, clip_max=60)
    assert env["CLIP_TARGET_MIN_SECONDS"] == "25" and env["CLIP_TARGET_MAX_SECONDS"] == "40"
    assert env["CLIP_MIN_SECONDS"] == "15" and env["CLIP_MAX_SECONDS"] == "60", "the band stays the hard limit"
    assert _env({"clip_target": [40, 25]})["CLIP_TARGET_MIN_SECONDS"] == "25", "given backwards: reordered"
    for bad in (None, "x", [25], [25, 40, 60], {"a": 1}):
        env = _env({"clip_target": bad})
        assert "CLIP_TARGET_MAX_SECONDS" not in env and "CLIP_TARGET_MIN_SECONDS" not in env, bad
