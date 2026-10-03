"""B-roll v20 — the check (broll_check): one blind call per batch, answers graded against the spec's questions,
decide() and pick_best(). No model is called: broll.claude_json and shot_prompt.questions are faked."""
import os
import sys
import types

import pytest
from PIL import Image

import broll
import broll_check as bc


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


def result(links=True, look=4, **answers):
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
        reply = {"checks": [{"file": f"broll_{k}.jpg", "sees": "apples", "links": True, "look": 4,
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
        assert "15 words" in low and "1 to 5" in low and "link" in low

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
        reply = {"checks": [{"file": "broll_0.jpg", "sees": "two apples", "links": False, "look": 9,
                             "answers": [{"id": "q_subject", "a": "no"}, {"id": "q_count", "a": "3"}]},
                            {"file": "/somewhere/broll_1.jpg", "sees": "x" * 400, "links": True, "look": "high",
                             "answers": {"q_text": "yes"}}]}
        out, _seen = self._run(monkeypatch, tmp_path, cands, reply)
        assert out["broll_0.jpg"] == {"sees": "two apples", "links": False, "look": 5,
                                      "answers": {"q_subject": "no", "q_count": "3"}}       # look clamped to 1-5
        assert out["broll_1.jpg"]["look"] is None and len(out["broll_1.jpg"]["sees"]) == 200
        assert out["broll_1.jpg"]["answers"] == {"q_text": "yes"}

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
        assert grade({**GOOD, "q_subject": "an apple"})["subject_ok"] is False        # neither yes nor no
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
VISION = {**SPEC, "kind": "vision"}                  # the only kind for which "does not link" is a hard fail
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

    def test_a_vision_that_does_not_link_is_another_idea_at_once(self):
        r = result(links=False)
        assert decide(r, tries=1, spec=VISION_ALT) == "alt"          # the same prompt again would not read either
        assert decide(r, tries=1, alt_used=True, spec=VISION_ALT) == "drop"
        assert decide(r, tries=1, spec={**VISION}) == "drop"
        assert decide(r, tries=3, spec=VISION_ALT) == "alt"          # not a matter of budget
        assert broll.FILTERS["check: no link"] == 4 and "check: no cold link (kept: its subject is said)" not in broll.FILTERS

    @pytest.mark.parametrize("kind,medium", [("thing", "photograph"), ("scene", "photograph"),
                                             ("instrument", "scientific image"), ("body_inside", "drawing")])
    def test_any_other_kind_that_does_not_link_is_kept_its_subject_is_said(self, kind, medium, monkeypatch):
        # the subject is right and the speaker names it: not linking cold is advisory, only a vision needs the link
        spec = {**SPEC, "kind": kind, "alt": ALT}
        r = result(links=False, q_medium=medium)
        assert decide(r, tries=1, spec=spec) == "keep"
        assert decide(r, tries=1, alt_used=True, spec=spec) == "keep"
        assert decide(r, tries=3, spec={**spec, "alt": None}) == "keep"
        assert broll.FILTERS["check: no cold link (kept: its subject is said)"] == 3
        assert "check: no link" not in broll.FILTERS
        hits = []
        monkeypatch.setattr(broll, "filter_hit", lambda name, detail="": hits.append((name, detail)))
        decide(r, tries=1, spec=spec)
        assert [h[0] for h in hits] == ["check: no cold link (kept: its subject is said)"]
        assert "a red apple" in hits[0][1]

    def test_a_non_vision_that_does_not_link_goes_on_to_the_other_checks(self):
        # the advisory note does not stop the decision: what is wrong besides still counts
        assert decide(result(links=False, q_subject="no"), tries=1) == "rerender"
        assert decide(result(links=False, q_subject="no"), tries=2) == "alt"
        assert decide(result(links=False, q_count="9"), tries=2) == "rerender"
        assert decide(result(links=False, q_count="9"), tries=3) == "drop"
        assert decide(result(links=False, look=1), tries=1) == "rerender"
        assert decide(result(links=False, look=1), tries=2) == "keep"
        assert decide(result(links=False, q_unsafe="yes")) == "alt"
        assert decide(result(links=False, q_body_photo="yes"), alt_used=True) == "drop"

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
        r = {"sees": "a wolf", "links": True, "look": 4, "answers": {**GOOD, "q_count": "1", "q_people": "0",
                                                                      "q_pair": "no"}}
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

    def test_a_bad_look_renders_once_else_keeps(self):
        for look in (1, 2):
            broll.FILTERS.clear()
            assert decide(result(look=look), tries=1) == "rerender"
            assert broll.FILTERS["check: look"] == 1
            assert decide(result(look=look), tries=2) == "keep" and broll.FILTERS["check: look"] == 1
        assert decide(result(look=3)) == "keep" and decide(result(look=5)) == "keep"
        assert decide(result(look=None)) == "keep"

    def test_the_order_of_the_causes(self):
        # unsafe beats everything; (a vision) no link beats a wrong count; a wrong count beats a bad look
        r = result(links=False, look=1, q_unsafe="yes", q_count="9")
        assert decide(r) == "alt" and decide(r, spec=VISION_ALT) == "alt"
        r = result(links=False, look=1, q_count="9")
        assert decide(r, tries=2, spec=VISION_ALT) == "alt"
        assert decide(r, tries=2) == "rerender"       # any other kind: no link is only a note, the wrong count counts
        r = result(look=1, q_count="9")
        assert decide(r, tries=2) == "rerender" and decide(r, tries=3) == "drop"

    def test_every_non_keep_calls_filter_hit_with_a_detail(self, monkeypatch):
        hits = []
        monkeypatch.setattr(broll, "filter_hit", lambda name, detail="": hits.append((name, detail)))
        decide(result(q_unsafe="yes"))
        decide(result(links=False), tries=1, spec=VISION_ALT)
        decide(result(q_count="4", q_text="yes"), tries=1)
        decide(result())
        assert [h[0] for h in hits] == ["check: unsafe", "check: no link", "check: wrong count"]
        assert all(h[0] in h[1] and "a red apple" in h[1] for h in hits)
        assert "text in it" in hits[2][1]                             # every wrong answer is in the detail

    def test_the_alt_spec_itself_has_no_further_alt(self):
        spec = {**VISION}                                             # what broll_v20 renders after "alt"
        assert decide(result(q_unsafe="yes"), tries=2, alt_used=True, spec=spec) == "drop"
        assert decide(result(links=False), tries=2, alt_used=True, spec=spec) == "drop"
        assert decide(result(links=False), tries=2, alt_used=True, spec={**SPEC}) == "keep"    # not a vision: a note


# ---------------------------------------------------------------------------------------------- hero takes, minimum

def take(name, look=4, links=True, spec=None, **answers):
    return {"file": name, "m": {"spec": spec or dict(SPEC)}, "check": result(links=links, look=look, **answers)}


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

    def test_unsafe_and_no_link_lose(self):
        ok, unsafe, nolink = take("ok", look=2), take("u", look=5, q_unsafe="yes"), take("n", look=5, links=False)
        assert bc.pick_best([unsafe, nolink, ok]) is ok
        assert bc.pick_best([unsafe, nolink]) is nolink               # fewer failures... and the unsafe one is worse
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
