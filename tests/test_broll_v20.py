"""B-roll v20 « la fiche » (3-oct-2026): the whole chain on fakes — the editor's specs, the code's prompt, the blind
check and decide(), the hero's takes, the alternative, the reserve under the minimum. No model, no ComfyUI.
v21 (« idées »): ``run(..., ideas=True)`` puts the round of ideas (broll_ideas) between the editor and the rendering;
a picture that does not fit the words ("against" / "away") takes its alternative, whatever its kind; a pair is made as
two halves that share nothing (``_halves``)."""
import copy
import os
import re

import pytest
from PIL import Image

import broll
import broll_check
import broll_ideas
import broll_lessons
import broll_spec
import broll_v20
import shot_prompt

SPEC = {"kind": "thing", "subject": "a glass of water", "subject_words": "water", "count": "1",
        "state": "standing still", "setting": "a kitchen table", "details": "clear glass, drops on the side",
        "people": "none", "person": "none", "shot": "medium", "literal": "literal",
        "mood": {}, "alt": {"kind": "thing", "subject": "a tap running", "subject_words": "water", "count": "1",
                            "state": "running", "setting": "a sink", "details": "steel tap", "people": "none",
                            "person": "none", "shot": "close", "literal": "literal", "mood": {}}}


def _m(t, hero=False, gravity="none", **spec):
    return {"t": t, "anchor": "water", "said": "a glass of water", "dur": 2.0, "hero": hero, "mood": {},
            "clip_gravity": gravity, "spec": {**SPEC, **spec}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    broll.FILTERS.clear()
    monkeypatch.setattr(broll, "_frame_sheets", lambda clip_path, tmp: [])
    monkeypatch.setattr(broll, "episode_drawing", lambda: "A gouache drawing.")
    yield
    broll.FILTERS.clear()


def _render(tmp_path, made):
    def render(text, out, layout):
        Image.new("RGB", (64, 64)).save(out)
        made.append((os.path.basename(out), layout, text))
        return out, len(made)
    return render


def _ok(subject="yes", fits="with", look=4):
    """A check result as broll_check.check gives it: "fits" ("with" / "against" / "away") and its "links"."""
    return {"sees": "a glass", "fits": fits, "links": fits == "with", "look": look,
            "answers": {"q_subject": subject, "q_count": "1", "q_people": "0", "q_text": "no",
                        "q_medium": "photograph", "q_unsafe": "no", "q_body_photo": "no"}}


def _run(monkeypatch, tmp_path, moments, reserves, verdicts, plan_kw=None, clip=None, words=None, avoid=None, head=1.0,
         block=(), **run_kw):
    """``verdicts``: file basename -> check result (missing: a clean one). ``plan_kw`` is filled with the keywords
    plan_specs was called with; ``avoid`` (default none), ``head`` and ``block``: the clip's timing rules;
    ``run_kw``: more keywords of broll_v20.run (``ideas``)."""
    def plan(*a, **k):
        if plan_kw is not None:
            plan_kw.update(k, args=a)                    # the keywords, and under "args" the positional arguments
        return moments, reserves
    monkeypatch.setattr(broll_spec, "plan_specs", plan)
    monkeypatch.setattr(broll_check, "check", lambda cands, words, **k: {
        os.path.basename(c["file"]): verdicts.get(os.path.basename(c["file"]), _ok()) for c in cands})
    made = []
    kept, pictured = broll_v20.run("clip.mp4", clip if clip is not None else {}, words if words is not None else [],
                                   None, 0, 30, 4, avoid if avoid is not None else [], head, 2.0, 2.0, block, None,
                                   str(tmp_path), _render(tmp_path, made), **run_kw)
    return kept, pictured, made


def test_the_prompt_is_the_codes_and_a_clean_picture_is_kept(monkeypatch, tmp_path):
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {})
    assert len(kept) == 2 and all(c["verdict"] == "keep" for c in kept)
    assert made[0][2].index("glass of water") < 120                  # the subject opens the prompt
    assert kept[0]["m"]["prompt"] == made[0][2] and kept[0]["m"]["art"] is True


def test_the_hero_takes_then_the_best_stays(monkeypatch, tmp_path):
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0, hero=True), _m(12.0)], [],
                          {"broll_0.jpg": _ok(look=2)})
    assert [m[0] for m in made][:2] == ["broll_0.jpg", "broll_0_t2.jpg"] and made[0][1] == "hero"
    assert kept[0]["file"].endswith("broll_0_t2.jpg")


def test_a_wrong_subject_is_rendered_again_and_a_picture_against_the_words_takes_the_alternative(monkeypatch, tmp_path):
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0, kind="vision")], [],
                          {"broll_0.jpg": _ok(subject="no"), "broll_1.jpg": _ok(fits="against")})
    names = [m[0] for m in made]
    assert "broll_0_v2.jpg" in names and "broll_1_alt.jpg" in names
    alt = next(c for c in kept if c["k"] == 1)
    assert alt["m"]["spec"]["subject"] == "a tap running" and "tap running" in alt["m"]["prompt"]
    assert broll.FILTERS["check: contradicts the words"] == 1 and broll.FILTERS["check: wrong subject"] == 1


def test_a_vision_read_as_away_is_kept_on_the_idea_rounds_verdict(monkeypatch, tmp_path):
    # the blind check called the DMT trip "nothing to do with the words": a vision the idea round chose stays
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0, kind="vision")], [], {"broll_0.jpg": _ok(fits="away")})
    assert [m[0] for m in made] == ["broll_0.jpg"] and len(kept) == 1 and kept[0]["verdict"] == "keep"
    assert broll.FILTERS["check: a vision read as away (kept)"] == 1


def test_a_picture_that_does_not_fit_takes_its_alternative_whatever_its_kind(monkeypatch, tmp_path):
    # v21: against the words or away from them, a thing (any kind) goes to its alternative like a vision; the old
    # "a non-vision that does not link is kept" is gone
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [],
                          {"broll_0.jpg": _ok(fits="against"), "broll_1.jpg": _ok(fits="away")})
    assert [m[0] for m in made] == ["broll_0.jpg", "broll_1.jpg", "broll_0_alt.jpg", "broll_1_alt.jpg"]
    assert len(kept) == 2 and all(c["alt_used"] and c["m"]["spec"]["subject"] == "a tap running" for c in kept)
    assert broll.FILTERS["check: contradicts the words"] == 1 and broll.FILTERS["check: pulls attention away"] == 1
    assert "check: no cold link (kept: its subject is said)" not in broll.FILTERS and "check: no link" not in broll.FILTERS


def test_an_alternative_that_does_not_fit_either_is_dropped(monkeypatch, tmp_path):
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [],
                          {"broll_1.jpg": _ok(fits="away"), "broll_1_alt.jpg": _ok(fits="against")})
    assert [m[0] for m in made] == ["broll_0.jpg", "broll_1.jpg", "broll_1_alt.jpg"]
    assert [c["k"] for c in kept] == [0]
    assert broll.FILTERS["check: pulls attention away"] == 1 and broll.FILTERS["check: contradicts the words"] == 1


def test_a_picture_that_fits_is_kept_as_it_is(monkeypatch, tmp_path):
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {"broll_1.jpg": _ok(fits="with")})
    assert [m[0] for m in made] == ["broll_0.jpg", "broll_1.jpg"] and len(kept) == 2
    assert not [n for n in broll.FILTERS if n.startswith("check:")]


def test_under_the_minimum_a_reserve_is_made(monkeypatch, tmp_path):
    unsafe = {**_ok(), "answers": {**_ok()["answers"], "q_unsafe": "yes"}}
    kept, pictured, made = _run(monkeypatch, tmp_path, [_m(5.0, alt=None), _m(12.0, alt=None)], [_m(20.0)],
                                {"broll_0.jpg": unsafe, "broll_1.jpg": unsafe})
    assert len(kept) == 1 and kept[0]["file"].endswith("broll_2r.jpg") and len(pictured) == 3
    assert broll.LAST_PICTURED[2]["t"] == 20.0 and broll.FILTERS["check: unsafe"] == 2


def test_a_picture_nobody_checked_is_not_kept(monkeypatch, tmp_path):
    monkeypatch.setattr(broll_spec, "plan_specs", lambda *a, **k: ([_m(5.0)], []))
    monkeypatch.setattr(broll_check, "check", lambda cands, words, **k: {})
    kept, _p = broll_v20.run("clip.mp4", {}, [], None, 0, 30, 4, [], 1.0, 2.0, 2.0, (), None, str(tmp_path),
                             _render(tmp_path, []))
    assert kept == [] and broll.FILTERS["check: not checked"] == 1


def test_add_broll_branches_on_the_chain():
    src = open(os.path.join(os.path.dirname(broll.__file__), "broll.py"), encoding="utf-8").read()
    assert 'cfg.get("chain") == "spec"' in src and "broll_v20.run(" in src and "raw=True" in src
    assert 'ideas=bool(cfg.get("ideas"))' in src               # v21: the profile's switch reaches the chain


# ---------------------------------------------------------------------------------------------- v21: the round of ideas

WORDS = [{"text": t, "start": round(i * 0.4, 2), "end": round(i * 0.4 + 0.35, 2)}
         for i, t in enumerate("a glass of water".split())]


def _round_returning(monkeypatch, moments, reserves, seen):
    """broll_ideas.idea_round, faked: its arguments go to ``seen``, ``(moments, reserves)`` is its answer."""
    def fake(*args, **kwargs):
        seen.update(args=args, kwargs=kwargs)
        return moments, reserves
    monkeypatch.setattr(broll_ideas, "idea_round", fake)


def test_without_ideas_the_round_is_never_called(monkeypatch, tmp_path):
    seen, plan_kw = {}, {}
    _round_returning(monkeypatch, [], [], seen)
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {}, plan_kw=plan_kw)
    assert not seen and plan_kw["ideas"] is False and len(kept) == 2 and len(made) == 2
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {}, plan_kw=plan_kw, ideas=False)
    assert not seen and plan_kw["ideas"] is False and len(kept) == 2


def test_with_ideas_the_round_chooses_what_is_rendered(monkeypatch, tmp_path):
    first, second, spare = _m(5.0, gravity="grave"), _m(12.0), _m(20.0)
    chosen = _m(12.0, subject="a tap running", light="low sodium lamp from the right", alt=None)
    again = _m(20.0, subject="a kettle on the hob", alt=None)
    seen, plan_kw, clip = {}, {}, {"video_title_for_youtube_short": "Water"}
    _round_returning(monkeypatch, [chosen], [again], seen)
    kept, pictured, made = _run(monkeypatch, tmp_path, [first, second], [spare], {}, plan_kw=plan_kw, clip=clip,
                                words=WORDS, ideas=True)
    # the editor is told it works for the round, and the round gets the clip: moments, reserves, clip, words, the
    # clip's gravity (the first moment's) and its text
    assert plan_kw["ideas"] is True
    moments, reserves, got_clip, words, gravity, clip_text = seen["args"]
    assert moments == [first, second] and reserves == [spare] and got_clip is clip and words is WORDS
    assert gravity == "grave" and clip_text == "a glass of water"
    # the clip's timing rules go with it, as keywords (the round picks the hero with them): run's own, here none
    assert seen["kwargs"] == {"avoid": [], "head": 1.0, "block": ()} and len(seen["args"]) == 6
    # what it returns is what is rendered: its moment first, then its reserve (under the minimum), nothing of the rest
    assert [m[0] for m in made] == ["broll_0.jpg", "broll_1r.jpg"]
    assert "Low sodium lamp from the right." in made[0][2]            # the art director's light is in the prompt
    assert [c["m"]["spec"]["subject"] for c in kept] == ["a tap running", "a kettle on the hob"]
    assert len(pictured) == 2 and pictured[0] is chosen


def test_the_round_gets_the_timing_rules_the_editor_was_given_as_keywords(monkeypatch, tmp_path):
    seen, plan_kw = {}, {}
    _round_returning(monkeypatch, [_m(12.0)], [], seen)
    avoid, block = [7.5, 19.0], ((20.0, 24.0),)
    _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {}, plan_kw=plan_kw, words=WORDS, ideas=True,
         avoid=avoid, head=2.5, block=block)
    # avoid, head and block are keywords of the round (the other six arguments stay positional) ...
    assert set(seen["kwargs"]) == {"avoid", "head", "block"} and len(seen["args"]) == 6
    assert seen["kwargs"]["avoid"] is avoid and seen["kwargs"]["head"] == 2.5 and seen["kwargs"]["block"] is block
    # ... the very rules the editor placed the moments with
    assert plan_kw["args"][3] is avoid and plan_kw["head"] == 2.5 and plan_kw["block"] is block


def test_the_hero_is_picked_among_the_ideas_with_the_clips_rules_and_made_full_screen(monkeypatch, tmp_path):
    """v21: the hero is not the editor's mark any more: broll_ideas picks it among the ideas kept (hero_ok, the viewer's
    score) with broll.hero_fits and the avoid / head / block run() was given; that moment is then made full screen."""
    asked = []

    def fits(m, duration, avoid, head, block):
        asked.append((m["anchor"], duration, avoid, head, block))
        return True
    monkeypatch.setattr(broll, "hero_fits", fits)
    scene = {"title": "A noon kitchen", "picture": "A busy restaurant kitchen at noon.", "adds": "", "reads": "",
             "kind": "scene", "subject": "a busy restaurant kitchen", "count": "1", "state": "steam rising from pans",
             "setting": "a restaurant at noon", "details": "steel pans, a wide window", "people": "none",
             "person": "none", "shot": "wide", "light": "hard noon daylight through a window", "hero_ok": True}
    monkeypatch.setattr(broll_ideas, "_direct", lambda moments, words, clip, gravity: {
        k: {"idea": "a kitchen", "role": "point", "ideas": [dict(scene)], "why": ""} for k in range(len(moments))})
    monkeypatch.setattr(broll_ideas, "_verify", lambda moments, words, clip, gravity, ideas: {
        (k, 0): {"verdict": "pass", "reason": "", "details": "", "flaw": "none"} for k in range(len(moments))})
    monkeypatch.setattr(broll_ideas, "_view", lambda moments, words, clip, gravity, ideas: {
        k: {"views": {0: {"stops": "yes", "feels": "", "link": "yes", "adds": "", "score": 4 + k, "flaw": "none",
                          "unease": ""}}, "order": ["0", "face"]} for k in range(len(moments))})
    avoid, block = [9.0], ((14.0, 15.0),)
    kept, pictured, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {}, words=WORDS, ideas=True,
                                avoid=avoid, head=2.5, block=block)
    # hero_fits was asked about both ideas (4 and 5 from the viewer), with the clip's length and the rules as given
    assert asked == [("water", 1.55, avoid, 2.5, block)] * 2 and asked[0][2] is avoid and asked[0][4] is block
    # the second one has the better score: it is the hero, the first one a card (and the editor marked neither)
    assert [m["hero"] for m in pictured] == [False, True]
    assert [(name, layout) for name, layout, _t in made] == [("broll_0.jpg", "card"), ("broll_1.jpg", "hero"),
                                                                 ("broll_1_t2.jpg", "hero")]
    assert "vertical full-screen scene" in made[1][2] and "horizontal frame" in made[0][2]
    assert [(c["k"], c["layout"]) for c in kept] == [(0, "card"), (1, "hero")]


def test_an_empty_round_is_no_picture_for_the_clip(monkeypatch, tmp_path, capsys):
    seen = {}
    _round_returning(monkeypatch, [], [], seen)
    kept, pictured, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [_m(20.0)], {}, words=WORDS, ideas=True)
    assert seen and (kept, pictured, made) == ([], [], [])
    assert "no idea above the face alone" in capsys.readouterr().out


def test_no_moment_from_the_editor_no_round(monkeypatch, tmp_path):
    seen = {}
    _round_returning(monkeypatch, [_m(5.0)], [], seen)
    assert _run(monkeypatch, tmp_path, [], [_m(20.0)], {}, ideas=True) == ([], [], [])
    assert not seen


# --------------------------------------------------------------------------------------- v21: the halves of a pair
# A pair is made as two pictures, one per half (the code composes them). Nothing of one half leaks into the other (the
# second bench: a photographed prosthetic hand got the drawn half's "red muscle tissue" and came out skinned).

COLOURS = ("colours_said", "true_colours")
PAIR_MOOD = {"era": "now", "valence": "neutral", "intensity": "steady", "visibility": "eye", "scale": "hand",
             "distance": "explained", "gravity": "none", "cue": "x", "colours_said": "red and white",
             "true_colours": "pink and grey"}
# the director declares two things; the second one names the inside of a body, so the code draws it
PAIR = {"kind": "pair", "subject": "a prosthetic hand", "subject_b": "a forearm with its muscles laid bare",
        "subject_words": "hand", "kind_a": "thing", "kind_b": "thing", "count": "2", "state": "resting side by side",
        "setting": "a laboratory bench", "details": "a carbon-fibre palm, steel finger joints",
        "details_b": "long red tendons, folded muscle fibres", "instrument": "microscope", "people": "group",
        "person": "anonymous", "shot": "medium", "light": "soft window daylight", "literal": "literal",
        "mood": PAIR_MOOD}
# the same pair with nothing of anatomy in it: a word of anatomy is put in one place at a time
PLAIN_PAIR = {**PAIR, "subject_b": "a wooden ladder", "details_b": "two rails, round rungs"}
SIDES = {"left": ("kind_a", "subject", "details"), "right": ("kind_b", "subject_b", "details_b")}


def halves_of(spec):
    """broll_v20._halves as {"left": ..., "right": ...}."""
    left, right = broll_v20._halves(spec)
    return {"left": left, "right": right}


def pair_with(side, kind, **words):
    """PLAIN_PAIR with the half ``side`` given its ``kind`` and the ``words`` of its "subject" and / or "details"."""
    kind_key, subject_key, details_key = SIDES[side]
    keys = {"subject": subject_key, "details": details_key}
    return {**PLAIN_PAIR, kind_key: kind, **{keys[field]: text for field, text in words.items()}}


def test_a_half_holds_nothing_of_the_pair_and_the_pair_is_left_as_it_was():
    before = copy.deepcopy(PAIR)
    halves = halves_of(PAIR)
    assert PAIR == before                         # the judge and the report read the pair as the director wrote it
    for half in halves.values():
        assert not {"alt", "subject_b", "kind_a", "kind_b", "details_b", "state"} & set(half)
        assert half["count"] == "1"
    assert (halves["left"]["kind"], halves["left"]["subject"]) == ("thing", "a prosthetic hand")
    assert halves["right"]["subject"] == "a forearm with its muscles laid bare"
    # a half with no kind of its own is a thing
    both = halves_of({k: v for k, v in PLAIN_PAIR.items() if k not in ("kind_a", "kind_b")})
    assert both["left"]["kind"] == both["right"]["kind"] == "thing"


def test_the_pairs_state_is_shared_by_neither_half():
    halves = halves_of(PAIR)
    for half in halves.values():
        assert "state" not in half
        assert "resting side by side" not in shot_prompt.build_prompt(half, "half", "A gouache drawing.")


def test_the_moods_colours_are_blanked_in_both_halves_and_nothing_else_of_it():
    others = {k: v for k, v in PAIR_MOOD.items() if k not in COLOURS}
    for half in halves_of(PAIR).values():
        assert [half["mood"][k] for k in COLOURS] == ["", ""]
        assert {k: v for k, v in half["mood"].items() if k not in COLOURS} == others
        prompt = shot_prompt.build_prompt(half, "half", "A gouache drawing.")
        assert "Colours:" not in prompt and "red and white" not in prompt and "pink and grey" not in prompt
    assert PAIR["mood"] is PAIR_MOOD and PAIR_MOOD["colours_said"] == "red and white"   # not blanked on the pair itself
    grave = halves_of({**PAIR, "mood": {**PAIR_MOOD, "gravity": "grave"}})
    assert all(half["mood"]["gravity"] == "grave" for half in grave.values())
    # a pair with no mood at all has two empty colours and no more
    for spec in ({**PAIR, "mood": None}, {**PAIR, "mood": {}}, {k: v for k, v in PAIR.items() if k != "mood"}):
        assert all(half["mood"] == {"colours_said": "", "true_colours": ""} for half in halves_of(spec).values())


def test_the_right_half_has_only_its_own_details_and_none_when_it_has_none():
    halves = halves_of(PAIR)
    assert halves["left"]["details"] == "a carbon-fibre palm, steel finger joints"
    assert halves["right"]["details"] == "long red tendons, folded muscle fibres"
    without = {k: v for k, v in PLAIN_PAIR.items() if k != "details_b"}
    for spec in (without, {**PLAIN_PAIR, "details_b": ""}, {**PLAIN_PAIR, "details_b": None}):
        halves = halves_of(spec)
        assert halves["left"]["details"] == PLAIN_PAIR["details"] and halves["right"]["details"] == ""
        prompt = shot_prompt.build_prompt(halves["right"], "half")
        assert "carbon-fibre" not in prompt and "finger joints" not in prompt and "Visible details" not in prompt


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("field", ["subject", "details"])
@pytest.mark.parametrize("kind", ["thing", "scene", "vision", "instrument"])
def test_a_half_that_names_core_anatomy_is_a_drawn_inside_whatever_kind_it_was_given(kind, field, side):
    halves = halves_of(pair_with(side, kind, **{field: "a glowing synapse"}))
    half, other = halves[side], halves["right" if side == "left" else "left"]
    assert (half["kind"], half["instrument"], half["setting"]) == ("body_inside", "", "plain")
    assert (half["people"], half["person"]) == ("none", "none")
    assert half[field] == "a glowing synapse" and other["kind"] == "thing"          # the other half is left alone


@pytest.mark.parametrize("word", ["muscle", "tendons", "nerve fibres", "brain", "neurons", "skull", "spinal cord",
                                  "blood vessels", "dopamine", "molecules"])
def test_each_word_of_core_anatomy_draws_the_half_that_holds_it(word):
    halves = halves_of(pair_with("left", "thing", subject=f"a model of the {word}"))
    assert halves["left"]["kind"] == "body_inside" and halves["right"]["kind"] == "thing"
    halves = halves_of(pair_with("right", "scene", details=f"fine {word.upper()}, a pale wall"))
    assert halves["right"]["kind"] == "body_inside" and halves["left"]["kind"] == "thing"


@pytest.mark.parametrize("subject", ["a prison cell", "the heart of a busy city", "a broken bone in a cast",
                                     "a brainstorm", "an organic garden"])
def test_words_that_only_look_like_anatomy_leave_the_half_as_it_was(subject):
    halves = halves_of({**PLAIN_PAIR, "subject": subject, "subject_b": subject, "kind_b": "scene"})
    assert (halves["left"]["kind"], halves["right"]["kind"]) == ("thing", "scene")


def test_the_photographed_prosthetic_hand_never_gets_the_drawn_halfs_muscle_words():
    halves = halves_of({**PAIR, "details_b": "red muscle tissue, long tendons"})
    assert (halves["left"]["kind"], halves["right"]["kind"]) == ("thing", "body_inside")
    photo = shot_prompt.build_prompt(halves["left"], "half")
    assert photo.startswith("A documentary photograph showing a single prosthetic hand")
    assert not re.search(r"muscle|tissue|tendon", photo, re.I)
    drawn = shot_prompt.build_prompt(halves["right"], "half", "A gouache drawing.")
    assert drawn.startswith("A gouache drawing. It shows a single forearm with its muscles laid bare")
    assert "Visible details: red muscle tissue, long tendons." in drawn
    # a left half that says anatomy itself is drawn too: never a photograph with those words
    skinned = halves_of({**PAIR, "subject": "a prosthetic hand over its muscles and tendons"})["left"]
    assert skinned["kind"] == "body_inside"
    assert "documentary photograph" not in shot_prompt.build_prompt(skinned, "half", "A gouache drawing.")


@pytest.mark.parametrize("kind", ["thing", "vision", "instrument", "body_inside"])
def test_a_half_that_is_not_a_scene_holds_nobody(kind):
    spec = {**PLAIN_PAIR, "kind_a": kind, "kind_b": kind, "people": "group", "person": "anonymous"}
    for half in halves_of(spec).values():
        assert (half["people"], half["person"]) == ("none", "none")
        assert half["kind"] == kind
    assert "anonymous" not in " ".join(shot_prompt.build_prompt(h, "half", "A gouache drawing.")
                                       for h in halves_of(spec).values())


def test_a_scene_half_keeps_its_people_and_a_scene_that_names_anatomy_is_drawn_with_nobody():
    spec = {**PLAIN_PAIR, "kind_a": "scene", "kind_b": "thing", "people": "group", "person": "anonymous"}
    left, right = broll_v20._halves(spec)
    assert (left["kind"], left["people"], left["person"]) == ("scene", "group", "anonymous")
    assert (right["kind"], right["people"], right["person"]) == ("thing", "none", "none")
    drawn = halves_of({**spec, "subject": "a lecture hall about the brain"})["left"]
    assert (drawn["kind"], drawn["people"], drawn["person"]) == ("body_inside", "none", "none")


def test_an_instrument_half_keeps_its_instrument_and_a_plain_setting():
    halves = halves_of({**PLAIN_PAIR, "kind_a": "instrument", "instrument": "fluorescence microscope",
                        "subject": "a round green cell"})
    assert (halves["left"]["kind"], halves["left"]["instrument"], halves["left"]["setting"]) == (
        "instrument", "fluorescence microscope", "plain")
    assert (halves["right"]["kind"], halves["right"]["setting"]) == ("thing", "a laboratory bench")


def test_a_pair_is_made_as_two_halves_each_with_its_own_prompt_and_composed(monkeypatch, tmp_path):
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0, alt=None, **PAIR), _m(12.0)], [], {})
    halves = [m for m in made if m[0].startswith("broll_0_h")]
    assert [(name, layout) for name, layout, _t in halves] == [("broll_0_h0.jpg", "half"), ("broll_0_h1.jpg", "half")]
    (_n0, _l0, left), (_n1, _l1, right) = halves
    # the left one stays a photograph of the hand, with none of the other half's words; the right one is the drawing
    assert left.startswith("A documentary photograph showing a single prosthetic hand")
    assert "Visible details: a carbon-fibre palm, steel finger joints." in left
    assert not re.search(r"muscle|tissue|tendon", left, re.I)
    assert right.startswith("A gouache drawing. It shows a single forearm with its muscles laid bare")
    assert "Visible details: long red tendons, folded muscle fibres." in right and "carbon-fibre" not in right
    assert "resting side by side" not in left + right and "Colours:" not in left + right    # no state, no colours
    pair = next(c for c in kept if c["k"] == 0)
    assert pair["verdict"] == "keep" and pair["m"]["spec"]["kind"] == "pair"
    assert pair["m"]["prompt"] == f"PAIR — left: {left} — right: {right}"
    assert Image.open(pair["file"]).size == broll._gen_size("card")                      # the two halves, composed


# ------------------------------------------------------------------------------------------- v22: the lessons journal
# Every picture decided after the render — kept with the viewer's score, or dropped with its reason — is one line of the
# lessons journal (broll_lessons, via broll_v20._lesson); a picture to be rendered again is a lesson once it is decided.
# The journal is off for the whole suite (tests/conftest.py): the ``lessons`` fixture turns it on, in a temporary folder.

LESSON_KEYS = {"source", "verdict", "why", "kind", "role", "flaw", "score", "look", "fits", "subject", "title", "said",
               "layout", "clip_title", "at"}


@pytest.fixture
def lessons(monkeypatch, tmp_path):
    """The journal on, in a temporary folder; the value reads it (the events, oldest first)."""
    monkeypatch.setenv("BROLL_LESSONS", "1")
    monkeypatch.setattr(broll_lessons, "LESSONS_DIR", str(tmp_path / "journal"))
    monkeypatch.setattr(broll_v20, "LESSON_CTX", {})
    return broll_lessons.recent


def _scored(score, **kw):
    """A clean check result that carries the viewer's score (``kw``: the keywords of _ok)."""
    return {**_ok(**kw), "score": score}


def test_a_kept_picture_is_a_lesson_with_its_score_its_look_and_where_it_came_from(monkeypatch, tmp_path, lessons):
    idea = {**_m(5.0, role="point"), "role": "vehicle", "idea_flaw": "object", "picture": "A glass of water on a table"}
    kept, _p, _made = _run(monkeypatch, tmp_path, [idea, _m(12.0)], [], {"broll_0.jpg": _scored(4, look=3)},
                           clip={"video_title_for_youtube_short": "Water is life"})
    assert [c["verdict"] for c in kept] == ["keep", "keep"]
    first, second = lessons()
    assert set(first) == LESSON_KEYS
    assert {k: v for k, v in first.items() if k != "at"} == {
        "source": "check", "verdict": "keep", "why": "", "kind": "thing", "role": "vehicle", "flaw": "object", "score": 4,
        "look": 3, "fits": "with", "subject": "a glass of water", "title": "A glass of water on a table",
        "said": "a glass of water", "layout": "card", "clip_title": "Water is life"}
    # nothing of its own to say: a flaw, a title and a role left empty, the check gave no score; never a missing key
    assert set(second) == LESSON_KEYS
    assert (second["flaw"], second["title"], second["role"], second["score"]) == ("", "", None, None)
    assert (second["verdict"], second["look"], second["fits"]) == ("keep", 4, "with")


def test_the_role_of_the_spec_stands_in_when_the_moment_has_none(monkeypatch, tmp_path, lessons):
    _run(monkeypatch, tmp_path, [_m(5.0, role="point"), _m(12.0, role="point")], [], {})
    assert [e["role"] for e in lessons()] == ["point", "point"]


def test_a_dropped_picture_is_a_lesson_with_its_reason_its_flaw_and_what_the_viewer_gave_it(monkeypatch, tmp_path, lessons):
    first = {**_m(5.0, alt=None), "idea_flaw": "setting"}                 # no alternative: it is dropped
    kept, _p, _made = _run(monkeypatch, tmp_path, [first, _m(12.0), _m(20.0)], [], {"broll_0.jpg": _scored(4, fits="away")})
    assert [c["k"] for c in kept] == [1, 2]
    drop, *rest = lessons()
    assert (drop["verdict"], drop["why"], drop["flaw"], drop["fits"], drop["score"], drop["subject"]) == (
        "drop", "pulls attention away", "setting", "away", 4, "a glass of water")
    assert [(e["verdict"], e["why"]) for e in rest] == [("keep", ""), ("keep", "")]


def test_a_picture_that_takes_its_alternative_is_a_drop_and_the_alternative_has_its_own_lesson(monkeypatch, tmp_path, lessons):
    _kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {"broll_0.jpg": _ok(fits="against")})
    assert [m[0] for m in made] == ["broll_0.jpg", "broll_1.jpg", "broll_0_alt.jpg"]
    assert [(e["verdict"], e["why"], e["subject"]) for e in lessons()] == [
        ("drop", "contradicts the words", "a glass of water"), ("keep", "", "a glass of water"), ("keep", "", "a tap running")]


def test_a_picture_that_does_not_beat_the_face_alone_is_a_lesson_and_takes_its_alternative(monkeypatch, tmp_path, lessons):
    # v22: scored 2 (or 1) by the viewer, a clean picture that fits the words still leaves
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {"broll_0.jpg": _scored(2)})
    assert [m[0] for m in made] == ["broll_0.jpg", "broll_1.jpg", "broll_0_alt.jpg"]
    assert [c["m"]["spec"]["subject"] for c in kept] == ["a tap running", "a glass of water"]
    assert [(e["verdict"], e["why"], e["score"], e["subject"]) for e in lessons()] == [
        ("drop", "under the face alone", 2, "a glass of water"), ("keep", "", None, "a glass of water"),
        ("keep", "", None, "a tap running")]
    assert broll.FILTERS["check: under the face alone"] == 1


def test_an_alternative_that_does_not_beat_the_face_alone_either_is_dropped_and_recorded(monkeypatch, tmp_path, lessons):
    kept, _p, _made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [],
                           {"broll_0.jpg": _scored(2), "broll_0_alt.jpg": _scored(1)})
    assert [c["k"] for c in kept] == [1]
    assert [(e["verdict"], e["why"], e["score"], e["subject"]) for e in lessons()] == [
        ("drop", "under the face alone", 2, "a glass of water"), ("keep", "", None, "a glass of water"),
        ("drop", "under the face alone", 1, "a tap running")]


def test_a_picture_scored_three_is_kept(monkeypatch, tmp_path, lessons):
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {"broll_0.jpg": _scored(3), "broll_1.jpg": _scored(5)})
    assert len(kept) == 2 and len(made) == 2
    assert [(e["verdict"], e["score"]) for e in lessons()] == [("keep", 3), ("keep", 5)]


def test_a_picture_to_render_again_is_a_lesson_once_decided_not_before(monkeypatch, tmp_path, lessons):
    wrong = _ok(subject="no")                                            # the first render and its second one miss the subject
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0, alt=None), _m(12.0)], [],
                          {"broll_0.jpg": wrong, "broll_0_v2.jpg": wrong})
    assert [m[0] for m in made] == ["broll_0.jpg", "broll_1.jpg", "broll_0_v2.jpg"] and [c["k"] for c in kept] == [1]
    # the first render of the moment is no lesson: "rerender" is not a decision
    assert [(e["verdict"], e["why"]) for e in lessons()] == [("keep", ""), ("drop", "wrong subject")]


def test_a_picture_that_was_rendered_again_and_kept_is_one_keep(monkeypatch, tmp_path, lessons):
    kept, _p, _made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {"broll_0.jpg": _ok(subject="no")})
    assert len(kept) == 2
    assert [(e["verdict"], e["why"]) for e in lessons()] == [("keep", ""), ("keep", "")]


def test_a_picture_nobody_checked_is_a_lesson_too(monkeypatch, tmp_path, lessons):
    monkeypatch.setattr(broll_spec, "plan_specs", lambda *a, **k: ([_m(5.0)], []))
    monkeypatch.setattr(broll_check, "check", lambda cands, words, **k: {})
    kept, _p = broll_v20.run("clip.mp4", {}, [], None, 0, 30, 4, [], 1.0, 2.0, 2.0, (), None, str(tmp_path),
                             _render(tmp_path, []))
    (event,) = lessons()
    assert kept == [] and (event["verdict"], event["why"]) == ("drop", "not checked")
    assert (event["score"], event["look"], event["fits"]) == (None, None, None)


def test_the_heros_takes_make_one_lesson_the_best_ones(monkeypatch, tmp_path, lessons):
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0, hero=True), _m(12.0)], [],
                          {"broll_0.jpg": _scored(2, look=2), "broll_0_t2.jpg": _scored(5, look=5)})
    assert [m[0] for m in made][:2] == ["broll_0.jpg", "broll_0_t2.jpg"] and len(kept) == 2
    # the other take leaves before any decision and is no lesson: one line for the moment, the take that stayed
    assert [(e["layout"], e["verdict"], e["score"], e["look"]) for e in lessons()] == [
        ("hero", "keep", 5, 5), ("card", "keep", None, 4)]


def test_the_clip_title_goes_with_every_lesson_cut_to_120_and_the_next_clip_starts_clean(monkeypatch, tmp_path, lessons):
    _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {}, clip={"video_title_for_youtube_short": "T" * 200})
    assert [e["clip_title"] for e in lessons()] == ["T" * 120] * 2
    assert broll_v20.LESSON_CTX == {"clip_title": "T" * 120}
    _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {}, clip={})        # a clip with no title
    assert [e["clip_title"] for e in lessons()][2:] == ["", ""] and broll_v20.LESSON_CTX == {"clip_title": ""}


def test_the_long_fields_of_a_lesson_are_cut(monkeypatch, tmp_path, lessons):
    long = {**_m(5.0, subject="s" * 100), "picture": "p" * 200, "said": "w" * 200}
    _run(monkeypatch, tmp_path, [long, _m(12.0)], [], {})
    first = lessons()[0]
    assert (first["subject"], first["title"], first["said"]) == ("s" * 80, "p" * 120, "w" * 120)


def test_each_field_of_a_lesson_comes_from_its_own_place(lessons):
    # the kind and the subject are the spec's, the role the moment's (the spec's when it has none), the flaw, the title (its
    # "picture") and the words the moment's, the score / look / fits the check's, the layout the candidate's
    broll_v20.LESSON_CTX["clip_title"] = "The clip"
    c = {"m": {"role": "vehicle", "idea_flaw": "stock", "picture": "the picture", "said": "the words",
               "subject": "NOT THIS", "kind": "NOT THIS", "spec": {"kind": "scene", "subject": "the subject", "role": "NOT THIS"}},
         "check": {"score": 4, "look": 3, "fits": "against", "sees": "x"}, "layout": "hero"}
    broll_v20._lesson(c, "drop", "contradicts the words")
    (event,) = lessons()
    assert {k: v for k, v in event.items() if k != "at"} == {
        "source": "check", "verdict": "drop", "why": "contradicts the words", "kind": "scene", "role": "vehicle",
        "flaw": "stock", "score": 4, "look": 3, "fits": "against", "subject": "the subject", "title": "the picture",
        "said": "the words", "layout": "hero", "clip_title": "The clip"}


def test_a_lesson_of_a_bare_candidate_is_empty_never_an_error(lessons):
    broll_v20._lesson({}, "keep", None)
    broll_v20._lesson({"m": None, "check": None, "layout": None}, "drop", "wrong count")
    bare, other = lessons()
    assert set(bare) == set(other) == LESSON_KEYS
    assert (bare["source"], bare["verdict"], bare["why"], bare["flaw"], bare["subject"], bare["said"], bare["title"]) == (
        "check", "keep", "", "", "", "", "")
    assert (bare["kind"], bare["role"], bare["score"], bare["look"], bare["fits"], bare["layout"]) == (None,) * 6
    assert (other["verdict"], other["why"]) == ("drop", "wrong count")


def test_nothing_is_recorded_while_the_journal_is_off(monkeypatch, tmp_path):
    monkeypatch.setenv("BROLL_LESSONS", "0")
    monkeypatch.setattr(broll_lessons, "LESSONS_DIR", str(tmp_path / "journal"))
    kept, _p, _made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {"broll_0.jpg": _scored(1)})
    assert len(kept) == 2 and not os.path.exists(tmp_path / "journal")      # the chain ran, the journal was never made


def test_a_journal_that_cannot_be_written_never_breaks_the_chain(monkeypatch, tmp_path, capsys):
    (tmp_path / "blocker").write_text("a file, not a folder")
    monkeypatch.setenv("BROLL_LESSONS", "1")
    monkeypatch.setattr(broll_lessons, "LESSONS_DIR", str(tmp_path / "blocker" / "journal"))
    kept, _p, _made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {})
    assert len(kept) == 2 and "Lessons: not recorded" in capsys.readouterr().out


def test_the_flaw_the_idea_round_found_reaches_the_lesson_of_the_picture(monkeypatch, tmp_path, lessons):
    """broll_ideas puts the verifier's flaw of the chosen idea in the moment (``idea_flaw``); _settle notes it."""
    idea = {"title": "A noon kitchen", "picture": "A busy restaurant kitchen at noon.", "adds": "", "reads": "",
            "kind": "scene", "subject": "a busy restaurant kitchen", "count": "1", "state": "steam rising from pans",
            "setting": "a restaurant at noon", "details": "steel pans, a wide window", "people": "none", "person": "none",
            "shot": "wide", "light": "hard noon daylight through a window"}
    flaws = ["object", "none"]
    monkeypatch.setattr(broll_ideas, "_direct", lambda moments, words, clip, gravity: {
        k: {"idea": "a kitchen", "role": "point", "ideas": [dict(idea)], "why": ""} for k in range(len(moments))})
    monkeypatch.setattr(broll_ideas, "_verify", lambda moments, words, clip, gravity, ideas: {
        (k, 0): {"verdict": "pass", "reason": "", "details": "", "flaw": flaws[k]} for k in range(len(moments))})
    monkeypatch.setattr(broll_ideas, "_view", lambda moments, words, clip, gravity, ideas: {
        k: {"views": {0: {"stops": "yes", "feels": "", "link": "yes", "adds": "", "score": 5, "flaw": "none",
                          "unease": ""}}, "order": ["0", "face"]} for k in range(len(moments))})
    kept, pictured, _made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {"broll_0.jpg": _ok(fits="away")},
                                 words=WORDS, ideas=True)
    assert [m["idea_flaw"] for m in pictured] == ["object", "none"] and [c["k"] for c in kept] == [1]
    drop, keep = lessons()
    assert (drop["verdict"], drop["why"], drop["flaw"], drop["kind"]) == ("drop", "pulls attention away", "object", "scene")
    assert (keep["verdict"], keep["flaw"]) == ("keep", "none")
