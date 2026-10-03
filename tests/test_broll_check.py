"""B-roll v20 — the check (broll_check): one blind call per batch, answers graded against the spec's questions,
decide() and pick_best(). No model is called: broll.claude_json and shot_prompt.questions are faked.
v21: the viewer hears the words and reads them as subtitles, so "links" became "fits" ("with" / "against" / "away");
a picture that does not fit goes to its alternative, whatever its kind."""
import os
import sys
import types

import pytest
from PIL import Image

import broll
import broll_check as bc
import shot_prompt as real_shot_prompt          # the autouse fixture below swaps sys.modules["shot_prompt"] for a fake


def fake_questions(spec):
    """The same shape as shot_prompt.questions: [{"id", "q", "expect"}]."""
    kind = spec.get("kind", "thing")
    qs = [{"id": "q_subject", "q": f"Is the main subject {spec['subject']}?", "expect": "yes"}]
    if str(spec.get("count", "1")) in ("1", "2", "3", "4") and kind != "pair":          # no count for a pair
        qs.append({"id": "q_count", "q": f"How many {spec['subject']} are visible?", "expect": int(spec.get("count", 1))})
    if kind in ("body_inside", "instrument"):                                            # the body is the subject
        pass
    elif spec.get("people", "none") == "hands":
        qs.append({"id": "q_people", "q": "Apart from hands and arms, is any part of a person visible?", "expect": "no"})
    else:
        qs.append({"id": "q_people", "q": "How many people or body parts are visible?",
                   "expect": {"none": 0, "one": 1, "group": 2}[spec.get("people", "none")]})
    qs.append({"id": "q_text", "q": "Is there any writing, letters or numbers?", "expect": "no"})
    if kind != "pair":                                                                   # each half has its own medium
        qs.append({"id": "q_medium", "q": "Is it a photograph, a drawing or painting, or a scientific image?",
                   "expect": {"body_inside": "drawing", "instrument": "scientific image"}.get(kind, "photograph")})
    qs.append({"id": "q_unsafe", "q": "Does it show blood, a wound, a weapon?", "expect": "no"})
    qs.append({"id": "q_body_photo", "q": "Is it a PHOTOGRAPH of the inside of a body?", "expect": "no"})
    if kind == "pair":
        qs.append({"id": "q_pair", "q": f"Are there two images, {spec['subject']} and {spec['subject_b']}?",
                   "expect": "yes"})
    return qs


@pytest.fixture(autouse=True)
def _fake_shot_prompt(monkeypatch):
    monkeypatch.setitem(sys.modules, "shot_prompt", types.SimpleNamespace(questions=fake_questions))
    broll.FILTERS.clear()
    yield
    broll.FILTERS.clear()


SPEC = {"kind": "thing", "subject": "a red apple", "count": "2", "people": "hands", "details": "SECRET DETAILS",
        "state": "SECRET STATE"}
GOOD = {"q_subject": "yes", "q_count": "2", "q_people": "no", "q_text": "no", "q_medium": "photograph",
        "q_unsafe": "no", "q_body_photo": "no"}


def result(fits="with", look=4, **answers):
    """A check result as bc.check() gives it: "fits", and "links" (= fits is "with")."""
    return {"sees": "two apples on a table", "fits": fits, "links": fits == "with", "look": look,
            "answers": {**GOOD, **answers}}


def legacy(links, look=4, **answers):
    """A result in the shape of before v21: the boolean "links" only, no "fits"."""
    return {"sees": "two apples on a table", "links": links, "look": look, "answers": {**GOOD, **answers}}


def cand(tmp_path, k=0, said="she ate two apples", spec=None, name=None):
    path = str(tmp_path / (name or f"broll_{k}.jpg"))
    Image.new("RGB", (900, 1600), (120, 40, 40)).save(path)
    return {"k": k, "m": {"said": said, "spec": spec or dict(SPEC), "prompt": "SECRET PROMPT", "idea": "SECRET IDEA",
                          "anchor": "apples", "t": 3.0}, "file": path, "layout": "card", "take": None}


# ---------------------------------------------------------------------------------------------- the call

class TestCheck:
    def _run(self, monkeypatch, tmp_path, cands, reply, words=(), **kw):
        seen = {"calls": 0}

        def fake_json(prompt, schema, **k):
            seen["calls"] += 1
            seen.update(prompt=prompt, schema=schema, **k)
            seen["exists"] = [os.path.exists(p) for p in k.get("attach") or []]
            if isinstance(reply, Exception):
                raise reply
            return reply

        monkeypatch.setattr(broll, "claude_json", fake_json)
        return bc.check(cands, list(words), **kw), seen

    def test_one_call_for_the_batch_with_one_attachment_per_picture(self, monkeypatch, tmp_path):
        cands = [cand(tmp_path, 0), cand(tmp_path, 1, said="the other words"), cand(tmp_path, 2, said="third words")]
        reply = {"checks": [{"file": f"broll_{k}.jpg", "sees": "apples", "fits": "with", "look": 4,
                             "answers": [{"id": "q_subject", "a": "yes"}]} for k in range(3)]}
        out, seen = self._run(monkeypatch, tmp_path, cands, reply)
        assert seen["calls"] == 1 and len(seen["attach"]) == len(cands) == 3
        assert all(seen["exists"]) and not any(os.path.exists(p) for p in seen["attach"])     # cleaned afterwards
        assert seen["stage"] == "broll_check" and seen["model"] == "sonnet"
        assert [os.path.basename(p) for p in seen["attach"]] == ["broll_0.jpg", "broll_1.jpg", "broll_2.jpg"]
        assert set(out) == {"broll_0.jpg", "broll_1.jpg", "broll_2.jpg"}
        with Image.open(cands[0]["file"]) as im:
            assert im.size == (900, 1600)                       # the original is left alone

    def test_the_model_is_the_callers(self, monkeypatch, tmp_path):
        _out, seen = self._run(monkeypatch, tmp_path, [cand(tmp_path)], {"checks": []}, model="haiku")
        assert seen["model"] == "haiku"

    def test_the_prompt_shows_the_words_and_the_questions_only(self, monkeypatch, tmp_path):
        c = cand(tmp_path)
        _out, seen = self._run(monkeypatch, tmp_path, [c], {"checks": []})
        p = seen["prompt"]
        assert 'heard "she ate two apples"' in p and "You know NOTHING about this video" in p
        assert "[q_subject] Is the main subject a red apple?" in p and "[q_pair]" not in p
        for hidden in ("SECRET DETAILS", "SECRET STATE", "SECRET PROMPT", "SECRET IDEA", "photograph, drawing"):
            assert hidden not in p.replace("a photograph, a drawing or painting", "")
        assert '"expect"' not in p and "expect" not in p.lower()        # the expected answers are never shown
        assert "'expect'" not in p

    def test_the_expected_answers_are_never_in_the_prompt(self, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "shot_prompt", types.SimpleNamespace(questions=lambda spec: [
            {"id": "q_subject", "q": "Is the main subject a lamp?", "expect": "XPCT_77"},
            {"id": "q_count", "q": "How many lamps?", "expect": 9876}]))
        _out, seen = self._run(monkeypatch, tmp_path, [cand(tmp_path)], {"checks": []})
        assert "XPCT_77" not in seen["prompt"] and "9876" not in seen["prompt"]
        assert "[q_count] How many lamps?" in seen["prompt"]

    def test_the_prompt_template_is_short(self):
        assert len(bc.CHECK_PROMPT.split()) <= 250
        low = bc.CHECK_PROMPT.lower()
        assert "15 words" in low and "1 to 5" in low
        # item 2 is "fits": the viewer hears the words and reads them as subtitles; with / against / away
        assert '"fits"' in low and "link" not in low and "subtitles" in low
        for word in ('"with"', '"against"', '"away"'):
            assert word in low, word
        assert '"fits": "with"' in bc.CHECK_PROMPT                    # the JSON example

    def test_the_schema_asks_for_fits_not_links(self):
        item = bc.CHECK_SCHEMA["properties"]["checks"]["items"]
        assert bc.FITS == ("with", "against", "away")
        assert item["properties"]["fits"] == {"type": "string", "enum": ["with", "against", "away"]}
        assert "links" not in item["properties"] and set(item["required"]) == {"file", "sees", "fits", "answers", "look"}

    def test_words_around_the_moment_when_it_has_no_said(self, monkeypatch, tmp_path):
        c = cand(tmp_path, said="")
        words = [{"text": "far", "start": 40.0}, {"text": "apples", "start": 3.5}, {"text": "red", "start": 2.5}]
        _out, seen = self._run(monkeypatch, tmp_path, [c], {"checks": []}, words=words)
        assert 'heard "apples red"' in seen["prompt"] and "far" not in seen["prompt"]

    def test_a_pair_spec_asks_its_pair_question(self, monkeypatch, tmp_path):
        spec = {"kind": "pair", "subject": "a wolf", "subject_b": "a dog", "count": "1", "people": "none"}
        _out, seen = self._run(monkeypatch, tmp_path, [cand(tmp_path, spec=spec)], {"checks": []})
        assert "[q_pair] Are there two images, a wolf and a dog?" in seen["prompt"]

    def test_the_result_is_keyed_by_file_with_answers_as_a_dict(self, monkeypatch, tmp_path):
        cands = [cand(tmp_path, 0), cand(tmp_path, 1)]
        reply = {"checks": [{"file": "broll_0.jpg", "sees": "two apples", "fits": "against", "look": 9,
                             "answers": [{"id": "q_subject", "a": "no"}, {"id": "q_count", "a": "3"}]},
                            {"file": "/somewhere/broll_1.jpg", "sees": "x" * 400, "fits": "with", "look": "high",
                             "answers": {"q_text": "yes"}}]}
        out, _seen = self._run(monkeypatch, tmp_path, cands, reply)
        assert out["broll_0.jpg"] == {"sees": "two apples", "fits": "against", "links": False, "look": 5,
                                      "answers": {"q_subject": "no", "q_count": "3"}}       # look clamped to 1-5
        assert out["broll_1.jpg"]["look"] is None and len(out["broll_1.jpg"]["sees"]) == 200
        assert out["broll_1.jpg"]["answers"] == {"q_text": "yes"}
        assert set(out["broll_1.jpg"]) == {"sees", "fits", "links", "answers", "look"}
        assert out["broll_1.jpg"]["fits"] == "with" and out["broll_1.jpg"]["links"] is True

    def test_links_is_fits_with_and_an_old_links_answer_is_mapped(self, monkeypatch, tmp_path):
        cands = [cand(tmp_path, k) for k in range(7)]

        def one(k, **fields):
            return {"file": f"broll_{k}.jpg", "sees": "x", "look": 4, "answers": [], **fields}
        reply = {"checks": [one(0, fits="away"), one(1, fits="with"),
                            one(2, links=True),                                  # the old answer: True is "with"
                            one(3, links=False),                                 # False is "away"
                            one(4, fits="sideways", links=False),                # not a fits: the old answer
                            one(5, fits="against", links=True),                  # a fits wins over a links
                            one(6)]}                                             # nothing said: not held against it
        out, _seen = self._run(monkeypatch, tmp_path, cands, reply)
        assert {f: (r["fits"], r["links"]) for f, r in out.items()} == {
            "broll_0.jpg": ("away", False), "broll_1.jpg": ("with", True), "broll_2.jpg": ("with", True),
            "broll_3.jpg": ("away", False), "broll_4.jpg": ("away", False), "broll_5.jpg": ("against", False),
            "broll_6.jpg": ("with", True)}

    def test_a_failed_call_gives_nothing(self, monkeypatch, tmp_path):
        out, seen = self._run(monkeypatch, tmp_path, [cand(tmp_path)], RuntimeError("quota"))
        assert out == {} and not any(os.path.exists(p) for p in seen["attach"])

    def test_no_candidate_no_call(self, monkeypatch, tmp_path):
        out, seen = self._run(monkeypatch, tmp_path, [], {"checks": []})
        assert out == {} and seen["calls"] == 0

    def test_a_candidate_without_a_spec_has_no_questions(self, monkeypatch, tmp_path):
        c = cand(tmp_path)
        c["m"]["spec"] = None
        _out, seen = self._run(monkeypatch, tmp_path, [c], {"checks": []})
        assert "questions:" not in seen["prompt"] and 'heard "she ate two apples"' in seen["prompt"]


# ---------------------------------------------------------------------------------------------- grading

def grade(answers, spec=None):
    return bc.grade_answers(fake_questions(spec or SPEC), answers)


class TestGradeAnswers:
    def test_a_clean_picture_passes_everything(self):
        g = grade(GOOD)
        assert g == {"subject_ok": True, "count_ok": True, "people_ok": True, "text_ok": True, "medium_ok": True,
                     "unsafe": False, "body_photo": False, "pair_ok": True}

    def test_yes_and_no_in_any_case_and_form(self):
        for yes in ("yes", "Yes", "YES.", " yes, clearly", True, "True", "Yeah"):
            assert grade({**GOOD, "q_subject": yes})["subject_ok"] is True, yes
        for no in ("no", "No.", "NO", False, "None", "Nope", "not really"):
            assert grade({**GOOD, "q_subject": no})["subject_ok"] is False, no
        # neither yes nor no: a description that names the thing asked counts as yes, another thing as no
        assert grade({**GOOD, "q_subject": "an apple"})["subject_ok"] is True
        assert grade({**GOOD, "q_subject": "a banana on a plate"})["subject_ok"] is False
        for yes in ("yes", "Yes, a few words", True, "yes."):
            assert grade({**GOOD, "q_text": yes})["text_ok"] is False, yes
        for no in ("no", "No", False, "None visible"):
            assert grade({**GOOD, "q_text": no})["text_ok"] is True, no

    def test_numbers_as_strings_ints_floats_or_words(self):
        for ok in ("2", 2, "2.0", 2.0, "two", "Two apples", "2 apples", "about 2", "exactly 2."):
            assert grade({**GOOD, "q_count": ok})["count_ok"] is True, ok
        for bad in ("1", 3, "one", "three", "many", "0", "none"):
            assert grade({**GOOD, "q_count": bad})["count_ok"] is False, bad

    def test_many_is_four_or_more(self):
        spec = {**SPEC, "count": "many"}
        assert [q["id"] for q in fake_questions(spec)].count("q_count") == 0         # not asked: not held against it
        qs = [{"id": "q_count", "q": "How many?", "expect": "many"}]
        for ok in ("many", "several", 7, "a crowd", "12"):
            assert bc.grade_answers(qs, {"q_count": ok})["count_ok"] is True, ok
        for bad in (1, "two", "none"):
            assert bc.grade_answers(qs, {"q_count": bad})["count_ok"] is False, bad

    def test_people_hands_asks_if_anything_but_hands_is_seen_and_expects_no(self):
        # people "hands": "Apart from hands and arms, is any part of a person visible?", expected "no"
        for ok in ("no", "No.", "NO", False, "None", "nothing else", "No, only the hands", "nobody"):
            assert grade({**GOOD, "q_people": ok})["people_ok"] is True, ok
        for bad in ("yes", "Yes.", True, "Yes, a face", "a face", "1", "1 person", "2", "a person standing",
                    "three people", "a face and hands"):
            assert grade({**GOOD, "q_people": bad})["people_ok"] is False, bad

    def test_people_ok_compares_yes_and_no_when_the_expectation_is_yes_or_no(self):
        assert bc._people_ok("no", "no") and bc._people_ok("No, none", "No") and bc._people_ok(False, "no")
        assert not bc._people_ok("yes", "no") and not bc._people_ok("a hand", "no") and not bc._people_ok("2", "no")
        assert bc._people_ok("Yes, a face", "yes") and bc._people_ok(True, "yes")
        assert not bc._people_ok("no", "yes") and not bc._people_ok("0", "yes")
        assert bc._people_ok("hands", "hands") and not bc._people_ok("2 people", "hands")    # a count/kind: as before

    def test_people_none_one_and_group(self):
        none = {**SPEC, "people": "none"}
        one = {**SPEC, "people": "one"}
        group = {**SPEC, "people": "group"}
        for a in ("0", 0, "none", "No one", "nobody", "zero", "0 people", "no hands"):
            assert grade({**GOOD, "q_people": a}, none)["people_ok"] is True, a
        for a in ("1", 1, "one", "a person", "1 person", "a woman", "one man"):
            assert grade({**GOOD, "q_people": a}, one)["people_ok"] is True, a
        for a in ("2", "three", "5 people", "a crowd", "a group of people", "several", "people"):
            assert grade({**GOOD, "q_people": a}, group)["people_ok"] is True, a
        assert grade({**GOOD, "q_people": "2"}, one)["people_ok"] is False
        assert grade({**GOOD, "q_people": "1"}, group)["people_ok"] is False
        assert grade({**GOOD, "q_people": "hands"}, none)["people_ok"] is False
        assert grade({**GOOD, "q_people": "0"}, one)["people_ok"] is False

    def test_medium_painting_counts_as_drawing_micrograph_as_scientific(self):
        draw = {**SPEC, "kind": "body_inside"}
        for a in ("drawing", "painting", "a watercolor painting", "illustration", "drawing/painting", "Drawn"):
            assert grade({**GOOD, "q_medium": a}, draw)["medium_ok"] is True, a
        for a in ("photograph", "photo", "scientific image"):
            assert grade({**GOOD, "q_medium": a}, draw)["medium_ok"] is False, a
        sci = {**SPEC, "kind": "instrument"}
        for a in ("scientific image", "micrograph", "microscope image", "Microscopy image", "X-ray", "a scientific image (micrograph)"):
            assert grade({**GOOD, "q_medium": a}, sci)["medium_ok"] is True, a
        for a in ("photograph", "a documentary photo", "Photograph."):          # a telescope's image is a photograph too
            assert grade({**GOOD, "q_medium": a}, sci)["medium_ok"] is True, a
        for a in ("drawing", "painting"):
            assert grade({**GOOD, "q_medium": a}, sci)["medium_ok"] is False, a
        assert bc._medium_ok("photograph", "scientific image") and not bc._medium_ok("scientific image", "photograph")
        for a in ("photograph", "a documentary photo", "Photograph.", "realistic photograph"):
            assert grade({**GOOD, "q_medium": a})["medium_ok"] is True, a
        assert grade({**GOOD, "q_medium": "drawing"})["medium_ok"] is False

    def test_unsafe_and_body_photo_are_flagged_on_a_yes(self):
        assert grade({**GOOD, "q_unsafe": "yes"})["unsafe"] is True
        assert grade({**GOOD, "q_unsafe": "Yes, a syringe"})["unsafe"] is True
        assert grade({**GOOD, "q_unsafe": "a syringe"})["unsafe"] is True            # an answer that is no "no"
        assert grade({**GOOD, "q_unsafe": "no"})["unsafe"] is False
        assert grade({**GOOD, "q_unsafe": "None"})["unsafe"] is False
        assert grade({**GOOD, "q_unsafe": "I don't see any"})["unsafe"] is False
        assert grade({**GOOD, "q_body_photo": "YES"})["body_photo"] is True
        assert grade({**GOOD, "q_body_photo": "no"})["body_photo"] is False
        assert grade({**GOOD, "q_body_photo": False})["body_photo"] is False
        assert grade({**GOOD, "q_body_photo": True})["body_photo"] is True

    def test_pair(self):
        spec = {"kind": "pair", "subject": "a wolf", "subject_b": "a dog", "count": "1", "people": "none"}
        assert grade({**GOOD, "q_pair": "yes"}, spec)["pair_ok"] is True
        assert grade({**GOOD, "q_pair": "No"}, spec)["pair_ok"] is False

    def test_what_was_not_asked_or_answered_is_not_held_against_the_picture(self):
        assert grade({})["subject_ok"] is True and grade({})["unsafe"] is False
        assert grade(None)["count_ok"] is True
        assert grade({**GOOD, "q_count": ""})["count_ok"] is True
        assert bc.grade_answers([], GOOD)["pair_ok"] is True
        assert bc.grade_answers(None, GOOD)["people_ok"] is True
        assert bc.grade_answers([{"id": "q_odd", "q": "?", "expect": "yes"}], {"q_odd": "no"})["subject_ok"] is True

    def test_ids_with_or_without_prefix_and_a_list_of_answers(self):
        qs = [{"id": "subject", "q": "?", "expect": "yes"}, {"id": "body-photo", "q": "?", "expect": "no"}]
        g = bc.grade_answers(qs, [{"id": "subject", "a": "no"}, {"id": "body-photo", "a": "yes"}])
        assert g["subject_ok"] is False and g["body_photo"] is True
        g = bc.grade_answers([{"id": "q_subject", "q": "?", "expect": "yes"}], {"Q_Subject": "no"})
        assert g["subject_ok"] is False


# ---------------------------------------------------------------------------------------------- decide

ALT = {"subject": "a green pear", "count": "1", "people": "none"}
VISION = {**SPEC, "kind": "vision"}                  # v21: a vision is no different from any other kind here
VISION_ALT = {**VISION, "alt": ALT}


def decide(result_, tries=1, alt_used=False, spec=None):
    return bc.decide(spec if spec is not None else {**SPEC, "alt": ALT}, result_, tries, alt_used)


class TestDecide:
    def test_a_clean_picture_is_kept_and_counts_no_filter(self):
        assert decide(result()) == "keep" and not broll.FILTERS

    def test_a_picture_nobody_checked_is_dropped(self):
        assert decide({}) == "drop" and decide(None) == "drop" and broll.FILTERS["check: not checked"] == 2

    @pytest.mark.parametrize("field,value,name", [("q_unsafe", "yes", "check: unsafe"),
                                                  ("q_body_photo", "yes", "check: body photo")])
    def test_unsafe_or_a_body_photo_goes_to_the_alt_else_drops(self, field, value, name):
        r = result(**{field: value})
        assert decide(r) == "alt" and broll.FILTERS[name] == 1
        assert decide(r, tries=3) == "alt"                         # not a matter of budget
        assert decide(r, alt_used=True) == "drop"
        assert decide(r, spec={**SPEC}) == "drop"                 # no alt in the spec
        assert decide(r, spec={**SPEC, "alt": None}) == "drop"
        assert decide(r, tries=1, alt_used=True, spec={**SPEC}) == "drop"
        assert broll.FILTERS[name] == 6

    def test_a_wrong_subject_renders_once_then_alt_then_drop(self):
        r = result(q_subject="no")
        assert decide(r, tries=1) == "rerender"
        assert decide(r, tries=2) == "alt"
        assert decide(r, tries=3) == "alt"
        assert decide(r, tries=2, alt_used=True) == "drop"
        assert decide(r, tries=2, spec={**SPEC}) == "drop"
        assert decide(r, tries=1, alt_used=True) == "rerender"      # the alt itself gets its second render
        assert broll.FILTERS["check: wrong subject"] == 6

    @pytest.mark.parametrize("fits,name", [("away", "check: pulls attention away"),
                                           ("against", "check: contradicts the words")])
    def test_a_picture_that_does_not_fit_is_another_idea_at_once(self, fits, name):
        # the viewer hears the words and reads them as subtitles: a picture that contradicts them ("against") or pulls
        # his attention elsewhere ("away") leaves; the same prompt again would do the same, so its alt, or nothing
        r = result(fits)
        assert decide(r, tries=1) == "alt" and broll.FILTERS[name] == 1
        assert decide(r, tries=3) == "alt"                           # not a matter of budget
        assert decide(r, tries=1, alt_used=True) == "drop"           # the alt itself gets no further alt
        assert decide(r, tries=1, spec={**SPEC}) == "drop"           # no alt in the spec
        assert decide(r, tries=1, spec={**SPEC, "alt": None}) == "drop"
        assert broll.FILTERS[name] == 5
        assert not [n for n in broll.FILTERS if n != name]

    @pytest.mark.parametrize("fits,name", [("away", "check: pulls attention away"),
                                           ("against", "check: contradicts the words")])
    @pytest.mark.parametrize("kind,medium", [("thing", "photograph"), ("scene", "photograph"),
                                             ("vision", "photograph"), ("instrument", "scientific image"),
                                             ("body_inside", "drawing")])
    def test_every_kind_that_does_not_fit_goes_to_its_alt(self, kind, medium, fits, name, monkeypatch):
        # v21: not only a vision. The old advisory "no cold link (kept: its subject is said)" no longer exists.
        # One exception: a VISION read as "away" is kept on the idea round's verdict (the blind check called the DMT
        # trip "nothing to do with the words"); "against" still drops it.
        spec = {**SPEC, "kind": kind, "alt": ALT}
        r = result(fits, q_medium=medium)
        if kind == "vision" and fits == "away":
            assert decide(r, tries=1, spec=spec) == "keep"
            assert broll.FILTERS["check: a vision read as away (kept)"] == 1 and name not in broll.FILTERS
            return
        assert decide(r, tries=1, spec=spec) == "alt"
        assert decide(r, tries=1, alt_used=True, spec=spec) == "drop"
        assert decide(r, tries=3, spec={**spec, "alt": None}) == "drop"
        assert broll.FILTERS[name] == 3
        assert "check: no cold link (kept: its subject is said)" not in broll.FILTERS
        assert "check: no link" not in broll.FILTERS
        hits = []
        monkeypatch.setattr(broll, "filter_hit", lambda n, detail="": hits.append((n, detail)))
        decide(r, tries=1, spec=spec)
        assert [h[0] for h in hits] == [name] and "a red apple" in hits[0][1]

    def test_an_old_links_answer_is_read_as_fits(self):
        # a result in the old shape ("links" only, no "fits"): True fits, False pulls attention away
        assert decide(legacy(True)) == "keep" and not broll.FILTERS
        assert decide(legacy(False), tries=1) == "alt" and broll.FILTERS["check: pulls attention away"] == 1
        assert decide(legacy(False), tries=1, alt_used=True) == "drop"
        assert decide(legacy(False), tries=1, spec={**SPEC}) == "drop"
        assert "check: no link" not in broll.FILTERS
        # neither a "fits" nor a "links": nothing is held against the picture
        assert decide({"sees": "x", "look": 4, "answers": dict(GOOD)}) == "keep"
        # a "fits" wins over a "links"
        assert decide({**result("against"), "links": True}) == "alt"
        assert decide({**result("with"), "links": False}) == "keep"

    def test_a_picture_that_does_not_fit_still_answers_to_the_checks_before_it(self):
        # unsafe / body photo, then the wrong subject (a rendering miss: the same prompt, a new seed), then "fits"
        assert decide(result("away", q_subject="no"), tries=1) == "rerender"
        assert decide(result("away", q_subject="no"), tries=2) == "alt"
        assert decide(result("against", q_subject="no"), tries=2, alt_used=True) == "drop"
        assert decide(result("away", q_unsafe="yes")) == "alt"
        assert decide(result("against", q_body_photo="yes"), alt_used=True) == "drop"
        assert broll.FILTERS["check: wrong subject"] == 3
        assert broll.FILTERS["check: unsafe"] == 1 and broll.FILTERS["check: body photo"] == 1
        assert "check: pulls attention away" not in broll.FILTERS and "check: contradicts the words" not in broll.FILTERS
        # and before the shape and the look: no second render for a wrong count or a bad look, the alt at once
        assert decide(result("away", q_count="9"), tries=1) == "alt"
        assert decide(result("against", q_count="9"), tries=3) == "alt"
        assert decide(result("away", look=1), tries=1) == "alt"
        assert decide(result("away", q_text="yes", q_medium="drawing"), tries=1, alt_used=True) == "drop"

    @pytest.mark.parametrize("field,value,name", [("q_count", "5", "check: wrong count"),
                                                  ("q_people", "2", "check: wrong people"),
                                                  ("q_text", "yes", "check: text in it"),
                                                  ("q_medium", "drawing", "check: wrong medium")])
    def test_a_wrong_shape_renders_within_the_budget_of_three_then_drops(self, field, value, name):
        r = result(**{field: value})
        assert decide(r, tries=1) == "rerender"
        assert decide(r, tries=2) == "rerender"
        assert decide(r, tries=3) == "drop"                          # never the alt: the same idea, wrong again
        assert decide(r, tries=3, alt_used=False) == "drop"
        assert decide(r, tries=2, alt_used=True) == "rerender"
        assert broll.FILTERS[name] == 5

    def test_a_pair_that_is_not_a_pair(self):
        spec = {"kind": "pair", "subject": "a wolf", "subject_b": "a dog", "count": "1", "people": "none"}
        r = result(q_count="1", q_people="0", q_pair="no")
        assert decide(r, tries=1, spec=spec) == "rerender" and decide(r, tries=3, spec=spec) == "drop"
        assert broll.FILTERS["check: not a pair"] == 2

    @pytest.mark.parametrize("kind,medium", [("body_inside", "drawing"), ("instrument", "scientific image")])
    def test_a_body_that_is_the_subject_is_not_dropped_for_its_people(self, kind, medium):
        # an anatomical arm / a drawn brain was answered "1 body part" and dropped as "wrong people"
        spec = {"kind": kind, "subject": "a human brain", "count": "1", "people": "none"}
        assert "q_people" not in [q["id"] for q in fake_questions(spec)]
        r = result(q_people="1 body part", q_count="1", q_medium=medium)
        assert decide(r, tries=1, spec=spec) == "keep" and decide(r, tries=3, spec=spec) == "keep"
        assert "check: wrong people" not in broll.FILTERS
        # the same answer on a thing that must hold nobody is still wrong
        assert decide(result(q_people="1 body part", q_count="2"), tries=1, spec={**SPEC, "people": "none"}) == "rerender"

    def test_a_pair_is_not_dropped_for_its_count(self):
        # the split galaxy / neuron image was asked how many images there are and dropped three times
        spec = {"kind": "pair", "subject": "a galaxy", "subject_b": "a neuron", "count": "1", "people": "none"}
        assert "q_count" not in [q["id"] for q in fake_questions(spec)]
        r = result(q_count="2", q_people="0", q_pair="yes")
        assert decide(r, tries=1, spec=spec) == "keep" and "check: wrong count" not in broll.FILTERS

    def test_a_pair_is_not_dropped_for_its_medium(self, monkeypatch):
        # each half has its own medium (a drawn neuron beside a telescope's frame): the pair is not asked one, with the
        # real questions as with the fake ones, and a mixed answer that came anyway is not held against it
        spec = {"kind": "pair", "subject": "a galaxy", "subject_b": "a neuron", "count": "1", "people": "none"}
        assert "q_medium" not in [q["id"] for q in fake_questions(spec)]
        monkeypatch.setitem(sys.modules, "shot_prompt", real_shot_prompt)
        assert "q_medium" not in [q["id"] for q in bc._questions(spec)]
        r = result(q_people="0", q_pair="yes", q_medium="drawing")
        assert decide(r, tries=1, spec=spec) == "keep" and "check: wrong medium" not in broll.FILTERS
        # a thing is still asked its medium
        assert decide(result(q_medium="drawing"), tries=1) == "rerender"

    def test_a_list_subject_is_asked_whether_it_is_shown_and_not_dropped_for_its_count(self, monkeypatch, tmp_path):
        # real questions: "eye mask, earbuds, blood pressure cuff" asked "How many ... cuffs are visible?" (the count
        # was the list's length) failed the count again and again
        monkeypatch.setitem(sys.modules, "shot_prompt", real_shot_prompt)
        spec = {"kind": "thing", "subject": "eye mask, earbuds, blood pressure cuff", "count": "3", "people": "none",
                "state": "resting", "details": "SECRET DETAILS"}
        qs = bc._questions(spec)
        assert qs[0] == {"id": "q_subject", "q": "Does the picture show eye mask, earbuds, blood pressure cuff?",
                         "expect": "yes"}
        assert "q_count" not in [q["id"] for q in qs]
        # what the viewer is asked, word for word
        seen = {}

        def fake_json(prompt, schema, **k):
            seen["prompt"] = prompt
            return {"checks": []}
        monkeypatch.setattr(broll, "claude_json", fake_json)
        bc.check([cand(tmp_path, spec=spec)], [])
        assert "[q_subject] Does the picture show eye mask, earbuds, blood pressure cuff?" in seen["prompt"]
        assert "[q_count]" not in seen["prompt"]
        # however many the viewer counts, it is not held against the picture
        r = result(q_subject="yes", q_people="0", q_count="1")
        assert decide(r, tries=1, spec=spec) == "keep" and "check: wrong count" not in broll.FILTERS
        assert decide(result(q_subject="no", q_people="0"), tries=1, spec=spec) == "rerender"

    def test_a_bad_look_renders_once_else_keeps(self):
        for look in (1, 2):
            broll.FILTERS.clear()
            assert decide(result(look=look), tries=1) == "rerender"
            assert broll.FILTERS["check: look"] == 1
            assert decide(result(look=look), tries=2) == "keep" and broll.FILTERS["check: look"] == 1
        assert decide(result(look=3)) == "keep" and decide(result(look=5)) == "keep"
        assert decide(result(look=None)) == "keep"

    def test_the_order_of_the_causes(self):
        # unsafe beats everything; a wrong subject beats no fit; no fit beats a wrong count; a wrong count beats a bad look
        def why(r, **kw):
            broll.FILTERS.clear()
            verdict = decide(r, **kw)
            return verdict, sorted(broll.FILTERS)
        assert why(result("away", look=1, q_unsafe="yes", q_count="9")) == ("alt", ["check: unsafe"])
        assert why(result("away", look=1, q_count="9", q_subject="no"), tries=1) == ("rerender", ["check: wrong subject"])
        assert why(result("away", look=1, q_count="9")) == ("alt", ["check: pulls attention away"])
        assert why(result("against", look=1, q_count="9"), spec=VISION_ALT) == ("alt", ["check: contradicts the words"])
        assert why(result(look=1, q_count="9"), tries=2) == ("rerender", ["check: wrong count"])
        assert why(result(look=1, q_count="9"), tries=3) == ("drop", ["check: wrong count"])
        assert why(result(look=1), tries=1) == ("rerender", ["check: look"])

    def test_every_non_keep_calls_filter_hit_with_a_detail(self, monkeypatch):
        hits = []
        monkeypatch.setattr(broll, "filter_hit", lambda name, detail="": hits.append((name, detail)))
        decide(result(q_unsafe="yes"))
        decide(result("away"), tries=1)
        decide(result("against"), tries=1)
        decide(result(q_count="4", q_text="yes"), tries=1)
        decide(result())
        assert [h[0] for h in hits] == ["check: unsafe", "check: pulls attention away", "check: contradicts the words",
                                        "check: wrong count"]
        assert all(h[0] in h[1] and "a red apple" in h[1] for h in hits)
        assert "text in it" in hits[3][1]                             # every wrong answer is in the detail

    def test_the_alt_spec_itself_has_no_further_alt(self):
        spec = {**VISION}                                             # what broll_v20 renders after "alt"
        assert decide(result(q_unsafe="yes"), tries=2, alt_used=True, spec=spec) == "drop"
        assert decide(result("against"), tries=2, alt_used=True, spec=spec) == "drop"
        assert decide(result("away"), tries=2, alt_used=True, spec={**SPEC}) == "drop"       # any kind: it leaves
        assert decide(result("against"), tries=2, alt_used=True, spec={**SPEC}) == "drop"


# ---------------------------------------------------------------------------------------------- hero takes, minimum

def take(name, look=4, fits="with", spec=None, **answers):
    return {"file": name, "m": {"spec": spec or dict(SPEC)}, "check": result(fits, look=look, **answers)}


class TestPickBest:
    def test_a_take_with_every_check_ok_beats_a_prettier_one_that_fails(self):
        a, b = take("a", look=5, q_count="5"), take("b", look=3)
        assert bc.pick_best([a, b]) is b and bc.pick_best([b, a]) is b

    def test_then_the_look(self):
        a, b = take("a", look=3), take("b", look=5)
        assert bc.pick_best([a, b]) is b
        assert bc.pick_best([b, a]) is b

    def test_a_tie_gives_the_first(self):
        a, b = take("a", look=4), take("b", look=4)
        assert bc.pick_best([a, b]) is a

    @pytest.mark.parametrize("fits", ["away", "against"])
    def test_unsafe_and_a_picture_that_does_not_fit_lose(self, fits):
        ok, unsafe, nofit = take("ok", look=2), take("u", look=5, q_unsafe="yes"), take("n", look=5, fits=fits)
        assert bc.pick_best([unsafe, nofit, ok]) is ok
        assert bc.pick_best([unsafe, nofit]) is nofit                 # fewer failures... and the unsafe one is worse
        assert bc.pick_best([take("x", look=5, q_count="3", q_text="yes"), take("y", look=1, q_count="3")])["file"] == "y"

    def test_unsafe_weighs_more_than_a_wrong_count(self):
        assert bc.pick_best([take("u", look=5, q_unsafe="yes"), take("c", look=1, q_count="9")])["file"] == "c"

    def test_a_take_without_a_check_ranks_last_but_one_take_is_returned(self):
        bare = {"file": "z", "m": {"spec": dict(SPEC)}}
        assert bc.pick_best([bare, take("a", look=1)])["file"] == "a"
        assert bc.pick_best([bare]) is bare
        assert bc.pick_best([]) is None

    def test_spec_and_result_keys_are_read_too(self):
        a = {"spec": SPEC, "result": result(look=2)}
        b = {"spec": SPEC, "result": result(look=4)}
        assert bc.pick_best([a, b]) is b


class TestMinimum:
    def test_the_constant_and_needs_reserve(self):
        assert bc.MIN_PER_CLIP == 2
        assert bc.needs_reserve([]) and bc.needs_reserve(["a"]) and bc.needs_reserve(1) and bc.needs_reserve(0)
        assert not bc.needs_reserve(["a", "b"]) and not bc.needs_reserve(["a", "b", "c"]) and not bc.needs_reserve(2)
        assert bc.needs_reserve(None)
