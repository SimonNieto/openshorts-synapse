"""visual_mood: anchored levels, the clip's base, the grade and its visible correction, the words, the pixel check
and the bench's spread (B-roll « ambiance », 2-oct-2026)."""
import numpy as np
import pytest
from PIL import Image

import visual_mood as vm


def _picture(dark=0.0, size=96):
    """A plain photo-like picture: a brightness ramp under three soft colour fields."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) / size
    lum = (0.04 + 0.92 * (0.6 * y + 0.4 * x)) * (1.0 - dark)
    r = lum * (0.9 + 0.2 * np.sin(6 * x))
    g = lum * (0.85 + 0.15 * np.cos(5 * y))
    b = lum * (0.8 + 0.25 * np.sin(4 * (x + y)))
    arr = np.clip(np.stack([r, g, b], -1) * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


NEUTRAL = {"valence": "neutral", "intensity": "steady"}


def test_every_axis_has_three_to_five_defined_levels():
    for axis, levels in vm.AXES.items():
        assert 3 <= len(levels) <= 5, axis
        assert all(name and len(d.split()) >= 3 for name, d in levels), axis
    assert set(vm.DEFAULT) == set(vm.AXES)


def test_the_schema_is_the_levels():
    for axis in vm.AXES:
        assert vm.SCHEMA["properties"][axis]["enum"] == list(vm.LEVELS[axis])
    assert "cue" in vm.SCHEMA["required"]
    for axis in vm.AXES:
        assert f'"{axis}"' in vm.MOOD_RULE


def test_clean_keeps_levels_defaults_the_rest_and_says_so():
    m = vm.clean({"valence": "Grim", "intensity": "loud", "era": "recent", "cue": "  he  was\ngone ",
                  "colours_said": "x" * 400})
    assert m["valence"] == "grim" and m["era"] == "recent"
    assert m["intensity"] == "steady" and "intensity" in m["defaulted"]
    assert m["function"] is None and "function" not in m["defaulted"]
    assert m["cue"] == "he was gone" and len(m["colours_said"]) == vm.TEXT_FIELDS["colours_said"]
    assert vm.clean(None)["valence"] == "neutral"


def test_base_is_the_median_pulled_toward_the_episode():
    moods = [vm.clean({"valence": v}) for v in ("grim", "uneasy", "uneasy", "neutral")]
    assert vm.base(moods)["valence"] == "uneasy"
    # one vote for the episode against four pictures: hardly moves
    assert vm.base(moods, {"valence": "elated"})["valence"] == "uneasy"
    # a clip of one picture leans on its episode
    assert vm.base([vm.clean({"valence": "elated"})], {"valence": "neutral"})["valence"] == "warm"
    assert vm.base([], {"valence": "grim"})["valence"] == "grim"
    assert vm.base([])["valence"] == "neutral"


def test_episode_levels_reads_the_bible():
    assert vm.episode_levels({"mood": {"valence": "warm", "era": "nope"}}) == {"valence": "warm"}
    assert vm.episode_levels({"look": {"palette": "teal"}}) is None
    assert vm.episode_levels(None) is None


def test_a_picture_in_its_clips_mood_wears_the_clips_grade():
    clip = {"valence": "uneasy", "intensity": "charged", "era": "now", "gravity": "none", "distance": "lived"}
    assert vm.grade(clip, clip) == vm.grade(clip, None)


def test_the_correction_moves_most_of_the_way():
    own = vm.grade({"valence": "grim"}, None, signature=0)
    clip = vm.grade(NEUTRAL, None, signature=0)
    mixed = vm.grade({"valence": "grim"}, NEUTRAL, signature=0)
    share = (mixed["temp"] - clip["temp"]) / (own["temp"] - clip["temp"])
    assert share == pytest.approx(vm.CORRECTION, abs=0.01)
    assert vm.CORRECTION >= 0.7


def test_a_real_change_of_feeling_shows():
    """Two levels of valence away from the clip: seen at once (ΔE >= 6); one level: seen side by side (>= 3)."""
    img = _picture()
    clip = vm.apply_grade(img, vm.grade(NEUTRAL, NEUTRAL, signature=0))
    for far in ("grim", "elated"):
        g = vm.grade({**NEUTRAL, "valence": far}, NEUTRAL, signature=0)
        assert vm.delta_e(clip, vm.apply_grade(img, g)) >= 6.0, far
    for near in ("uneasy", "warm"):
        g = vm.grade({**NEUTRAL, "valence": near}, NEUTRAL, signature=0)
        assert vm.delta_e(clip, vm.apply_grade(img, g)) >= 3.0, near
    same = vm.grade(NEUTRAL, NEUTRAL, signature=0)
    assert vm.delta_e(clip, vm.apply_grade(img, same)) == pytest.approx(0.0, abs=1e-6)


def test_gravity_tempers_the_style():
    free = vm.grade({"valence": "grim"}, None, signature=0)
    real = vm.grade({"valence": "grim", "gravity": "real"}, None, signature=0)
    grave = vm.grade({"valence": "grim", "gravity": "grave"}, None, signature=0)
    assert abs(free["temp"]) > abs(real["temp"]) > abs(grave["temp"])
    assert vm.key_of({"valence": "grim", "intensity": "extreme"}) == "low"
    assert vm.key_of({"valence": "grim", "intensity": "extreme", "gravity": "grave"}) == "mid"


def test_the_era_is_the_pictures_own():
    g = vm.grade({"era": "early", "valence": "elated"}, {"era": "now", "valence": "grim"})
    assert g["sat"] < 0.1                       # a black-and-white picture stays black and white
    assert vm.grade({"era": "recent"})["grain"] > vm.grade({"era": "now"})["grain"]


def test_the_signature_is_a_setting_and_never_covers_the_speakers_colours():
    assert vm.grade(NEUTRAL, signature=0.2)["sig"] == 0.2
    assert vm.grade(NEUTRAL, signature=0)["sig"] == 0.0
    assert vm.grade(NEUTRAL, signature=3)["sig"] == 1.0
    assert vm.grade({**NEUTRAL, "colours_said": "a violet glow"}, signature=0.2)["sig"] == 0.0
    img = _picture()
    plain = vm.apply_grade(img, vm.grade(NEUTRAL, signature=0))
    stamped = vm.apply_grade(img, vm.grade(NEUTRAL, signature=0.2))
    assert 2.0 <= vm.delta_e(plain, stamped) <= 8.0          # a light stamp, not a look
    # the duotone keeps the brightness
    assert vm.measure(stamped)["key"] == pytest.approx(vm.measure(plain)["key"], abs=2.5)


def test_words_follow_the_levels_not_a_subject():
    w = vm.words({"visibility": "eye", "era": "early"})
    assert "black-and-white" in w["medium"]
    assert "instrument" in vm.words({"visibility": "instrument"})["medium"]
    assert "speaker's own words" in vm.words({"visibility": "inner"})["medium"]
    assert vm.words({"valence": "grim", "intensity": "charged"})["light"].startswith("a low-key frame")
    assert "dignity" in vm.words({"valence": "grim", "gravity": "grave"})["light"]
    assert "dignity" not in vm.words({"valence": "grim", "gravity": "real"})["light"]
    assert vm.key_of({"valence": "grim", "intensity": "charged", "gravity": "real"}) == "low"
    assert vm.words({"intensity": "extreme", "gravity": "real"})["light"].endswith("hard directional light, crisp shadows")
    assert "with restraint" in vm.words({"visibility": "inner", "gravity": "real", "valence": "uneasy"})["medium"]
    # an experience lived as positive, or one that heals, keeps all its colours (v14)
    assert "with restraint" not in vm.words({"visibility": "inner", "gravity": "real", "valence": "elated"})["medium"]
    assert "never the person seen from outside" in vm.words({"visibility": "inner"})["medium"]
    assert "a violet glow" in vm.words({"colours_said": "a violet glow", "true_colours": "grey"})["palette"]
    assert "grey, white" in vm.words({"true_colours": "grey, white"})["palette"]
    assert "50-85 mm" in vm.words({"scale": "body", "distance": "lived"})["lens"]
    assert "14-24 mm" in vm.words({"scale": "vast", "distance": "lived"})["lens"]
    s = vm.sentence({"valence": "warm"})
    assert s.count(".") >= 5 and "teal" not in s.lower() and "amber" not in s.lower()


def test_the_pixel_check_moves_only_the_grade():
    dark = _picture(dark=0.7)
    g0 = vm.grade({"valence": "elated"}, signature=0.2)
    g, rep = vm.check(dark, g0, {"valence": "elated"})
    assert rep["raw"]["key"] < vm.KEY_RANGE["high"][0]
    assert g["gamma"] < 1.0 and any(m.startswith("gamma") for m in rep["moved"])
    assert g["sig"] == g0["sig"] and g["temp"] == g0["temp"]       # colour of the feeling and stamp untouched
    assert rep["after"]["key"] > rep["graded"]["key"]


def test_a_gap_the_grade_cannot_close_is_recorded():
    black = Image.new("RGB", (64, 64), (6, 6, 8))
    _g, rep = vm.check(black, vm.grade({"valence": "elated"}), {"valence": "elated"})
    assert any(x.startswith("key") for x in rep["gap"])


def test_a_picture_inside_its_targets_is_left_alone():
    img = _picture()
    g0 = vm.grade(NEUTRAL)
    g, rep = vm.check(img, g0, NEUTRAL)
    assert g == g0 and rep["moved"] == [] and rep["gap"] == []


def test_spread_counts_how_much_the_levels_move():
    a = vm.clean({"valence": "grim", "intensity": "charged"})
    b = vm.clean({"valence": "uneasy", "intensity": "charged"})
    c = vm.clean({"valence": "neutral", "intensity": "charged"})
    runs = [[a, a], [a, b], [a, c]]
    s = vm.spread(runs)
    assert s["intensity"] == {"agree": 1.0, "steps": 0.0, "changed": 0, "pictures": 2}
    assert s["valence"]["agree"] == pytest.approx((1.0 + 1 / 3) / 2, abs=1e-3)
    assert s["valence"]["steps"] == 1.0 and s["valence"]["changed"] == 1


def test_rate_asks_fresh_and_reads_the_levels(monkeypatch):
    import ai_brain
    seen = {}

    def fake(prompt, schema, **kw):
        seen.update(kw, prompt=prompt)
        return {"moods": [{"k": 1, "mood": {"valence": "warm", "cue": "so happy"}}, {"k": 9, "mood": {}}]}

    monkeypatch.setattr(ai_brain, "claude_json", fake)
    out = vm.rate([{"anchor": "a", "said": "x"}, {"anchor": "b", "said": "y"}], "x y", fresh=True)
    assert seen["reuse"] is False and "THE PICTURES" in seen["prompt"]
    assert out[0] is None and out[1]["valence"] == "warm"
