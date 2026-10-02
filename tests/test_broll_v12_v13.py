"""B-roll « ambiance » v12 (2-oct-2026): candidates kept by worth (a named experience first), the bench's fixed
moments, no positive example in the prompts, the empty place and the precise structure, the restraint of an illness
lived from inside. No model."""
import pytest

import ai_brain
import broll
import visual_mood

from test_broll import TEXT, _words


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    broll.FILTERS.clear()
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    yield
    broll.FILTERS.clear()


def _plan(monkeypatch, data=None, **kw):
    seen = {}
    monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt, schema=schema) or (data or {"moments": []}))
    return seen, broll.plan_with_claude({}, _words(TEXT), 4, [], hero=True, **kw)


def _at(word):
    words = _words(TEXT)
    return next(w for w in words if w["text"] == word)


def _mo(word, worth=None, **mood):
    w = _at(word)
    out = {"anchor": word, "time": w["start"], "image_prompt": word, "subject": word}
    if worth is not None:
        out["worth"] = worth
    if mood:
        out["mood"] = mood
    return out


class TestNoPositiveExample:
    def test_the_prompts_keep_principles_not_scenes_to_copy(self, monkeypatch):
        seen, _m = _plan(monkeypatch)
        p = seen["prompt"]
        for copied in ("pill bottle", "bed rail", "pills", "syringe", "a blade against a bone", "hike at dawn",
                       "security blanket", "decorator crabs", "a bare plaster wall"):
            assert copied not in p, copied
        assert "a glowing brain" in broll.CLICHE_RULE           # the ban list stays
        art = broll._art_prompt([{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "hero": True}], {})
        for copied in ("one bulb over the bed", "window light from the left", "rust-red door", "telling\n  object"):
            assert copied not in art, copied
        rules = ai_brain.bible_rules()
        for copied in ("a vial held to the light", "petri dish", "smoked pipe"):
            assert copied not in rules, copied

    def test_the_empty_place_and_the_precise_structure(self, monkeypatch):
        seen, _m = _plan(monkeypatch)
        assert broll.EMPTY_RULE in seen["prompt"] and broll.PRECISION_RULE in seen["prompt"]
        art = broll._art_prompt([{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s"}], {})
        assert "AN EMPTY PLACE IS AN ABSENCE" in art and "NOTHING THE IMAGE MODEL WILL GET WRONG" in art
        assert "A PARALLEL" not in art                          # v13 only
        assert "precise chemical\nstructure" in broll.REVIEW_PROMPT or "precise chemical structure" in broll.REVIEW_PROMPT


class TestCandidates:
    def test_the_editor_lists_candidates_and_the_code_keeps_the_best(self, monkeypatch):
        data = {"moments": [_mo("soldiers", 5), _mo("marched", 2), _mo("sergeant", 4), _mo("desert", 3)]}
        seen, moments = _plan(monkeypatch, data)
        assert "List the CANDIDATE B-roll images" in seen["prompt"] and "At most 7 images." in seen["prompt"]
        assert "worth" in seen["schema"]["properties"]["moments"]["items"]["required"]
        assert [m["anchor"] for m in moments] == ["soldiers", "sergeant", "desert"]
        assert broll.FILTERS["parser: low worth"] == 1

    def test_a_named_experience_is_kept_first(self, monkeypatch):
        data = {"moments": [_mo("soldiers", 4, visibility="eye"), _mo("drill", 3, visibility="inner"),
                            _mo("marched", 3, visibility="inner", gravity="grave")]}
        _seen, moments = _plan(monkeypatch, data)
        by = {m["anchor"]: m for m in moments}
        assert by["drill"]["score"] == 3 + broll.INNER_PRIORITY and by["marched"]["score"] == 3

    def test_a_candidate_without_worth_is_kept_like_a_plain_one(self, monkeypatch):
        _seen, moments = _plan(monkeypatch, {"moments": [_mo("soldiers")]})
        assert moments and moments[0]["score"] == broll.KEEP_WORTH


class TestFixedMoments:
    def test_one_answer_per_fixed_moment_a_skip_has_its_reason(self, monkeypatch):
        fixed = [{"anchor": w, "time": _at(w)["start"], "said": w} for w in ("soldiers", "marched", "sergeant")]
        data = {"moments": [_mo("soldiers", 1), {**_mo("marched"), "skip": True, "skip_why": "a set phrase"},
                            _mo("sergeant", 2)]}
        seen, moments = _plan(monkeypatch, data, fixed=fixed)
        p = seen["prompt"]
        assert "THE MOMENTS ARE FIXED" in p and '- time ' in p and "At most 3 images." in p
        assert seen["schema"]["properties"]["moments"]["items"]["properties"]["skip"] == {"type": "boolean"}
        assert [m["anchor"] for m in moments] == ["soldiers", "sergeant"]       # no worth floor, no spacing
        assert broll.LAST_SKIPS == [{"t": fixed[1]["time"], "anchor": "marched", "why": "a set phrase"}]


class TestRestraint:
    def test_a_register_picture_of_an_illness_gets_the_restraint_line(self, monkeypatch):
        b = ai_brain._clean_bible({"world": ["x"], "registers": [
            {"name": "voices", "kind": "inner", "when": "x", "look": "A room where the walls murmur " * 3}]}, "claude")
        monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", b)
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "style": "voices",
               "mood": visual_mood.clean({"visibility": "inner", "gravity": "real"})}]
        assert broll.RESTRAINT_LINE in broll._art_prompt(ms, {})
        ms[0]["mood"] = visual_mood.clean({"visibility": "inner"})
        assert broll.RESTRAINT_LINE not in broll._art_prompt(ms, {})
