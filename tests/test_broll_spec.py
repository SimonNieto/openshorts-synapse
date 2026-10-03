"""B-roll v20 « la fiche »: the editor's shot specs (broll_spec) — the schema, the code's checks of a spec, the
placing of the specs on the clip and the editor's prompt. No model is called (broll.claude_json is stubbed)."""
import re

import pytest

import ai_brain
import broll
import broll_spec
import visual_mood


def _words(text, step=0.42, dur=0.4):
    out, t = [], 0.0
    for w in text.split():
        out.append({"text": w, "start": round(t, 2), "end": round(t + dur, 2)})
        t += step
    return out


TEXT = ("Well you know this is how it all started for me back then. In 1998 the soldiers carried two gallons of water "
        "across the desert at night. Years later under the microscope the neurons looked like a forest of tiny "
        "branches. Then the surgeon opened the skull and we saw the brain itself, pale and folded. My brother said "
        "it was like a storm in my head, but it was not a storm at all. He kept a red bicycle in the garage and an "
        "old camera on his desk for years and years. The lesson stayed with all of us until the very end of it.")
WORDS = _words(TEXT)
MOOD = {"visibility": "eye", "scale": "body", "era": "now", "valence": "neutral", "intensity": "steady",
        "distance": "witnessed", "gravity": "none", "function": "setup", "cue": "the soldiers carried"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    broll.FILTERS.clear()
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    yield
    broll.FILTERS.clear()


def _at(word):
    return next(w for w in WORDS if re.sub(r"\W", "", w["text"]).lower() == word)


def _spec(anchor, subject, words=None, **kw):
    s = {"anchor": anchor, "time": _at(anchor.split()[-1])["start"], "said": f"something about the {anchor}",
         "worth": 4, "literal": "literal", "kind": "thing", "subject": subject, "subject_words": words or anchor,
         "count": "1", "state": "resting in place", "setting": "plain", "details": "worn metal, scratched paint",
         "people": "none", "person": "none", "shot": "medium", "hero": False, "death_near": False,
         "substance": False, "intake": False, "mood": dict(MOOD)}
    s.update(kw)
    return s


def _valid(spec, gravity="none"):
    return broll_spec.validate(spec, TEXT, gravity)


class TestSchema:
    def test_enums_are_the_contract(self):
        item = broll_spec.SPEC_SCHEMA["properties"]["moments"]["items"]["properties"]
        assert broll_spec.SPEC_SCHEMA["properties"]["clip_gravity"]["enum"] == ["none", "real", "grave"]
        assert item["literal"]["enum"] == ["literal", "figure", "denied"]
        assert item["kind"]["enum"] == ["thing", "scene", "vision", "instrument", "body_inside", "pair"]
        assert item["count"]["enum"] == ["1", "2", "3", "4", "many"]
        assert item["people"]["enum"] == ["none", "hands", "one", "group"]
        assert item["person"]["enum"] == ["none", "anonymous", "real"]
        assert item["shot"]["enum"] == ["wide", "medium", "close", "macro"]
        assert item["mood"] is visual_mood.SCHEMA
        for flag in ("hero", "death_near", "substance", "intake"):
            assert item[flag]["type"] == "boolean"
        assert item["worth"]["type"] == "integer" and item["time"]["type"] == "number"
        assert set(broll_spec.SPEC_SCHEMA["required"]) == {"clip_gravity", "moments"}

    def test_every_spec_has_an_idea_and_a_role(self):
        # v21: the idea of the sentence first, and whether the thing named is the point or only the vehicle of the idea
        item = broll_spec.SPEC_SCHEMA["properties"]["moments"]["items"]["properties"]
        assert broll_spec.ROLES == ("point", "vehicle")
        assert item["role"]["enum"] == ["point", "vehicle"] and item["idea"]["type"] == "string"
        assert {"idea", "role"} <= set(broll_spec.SPEC_ITEM["required"])

    def test_the_alt_is_the_same_fields_without_where_and_worth(self):
        alt = broll_spec.SPEC_SCHEMA["properties"]["moments"]["items"]["properties"]["alt"]["properties"]
        assert not {"anchor", "time", "said", "worth", "hero"} & set(alt)
        assert not {"idea", "role"} & set(alt)               # an alt keeps the idea and the role of its spec
        assert {"literal", "kind", "subject", "subject_words", "people", "person", "shot", "mood"} <= set(alt)
        assert alt["kind"]["enum"] == list(broll_spec.KINDS)


class TestValidate:
    def test_a_good_spec_passes_cleaned(self):
        s, why = _valid(_spec("soldiers", "  soldiers   marching ", worth=9, shot="zoom", count="7"))
        assert why == "ok" and s["subject"] == "soldiers marching"
        assert s["worth"] == 5 and s["shot"] == "medium" and s["count"] == "1" and s["kind"] == "thing"
        assert not broll.FILTERS

    @pytest.mark.parametrize("extra, name", [
        ({"literal": "figure"}, "spec: a figure of speech"),
        ({"literal": "denied"}, "spec: denied by the speaker"),
        ({"person": "real", "people": "one"}, "spec: a real person"),
        ({"death_near": True, "substance": True}, "spec: a death with a substance or an intake"),
        ({"death_near": True, "intake": True}, "spec: a death with a substance or an intake"),
        ({"subject": "   "}, "spec: no subject"),
    ])
    def test_drops(self, extra, name):
        s, why = _valid({**_spec("storm", "a storm over the sea"), **extra})
        assert s is None and why == name[len("spec: "):]
        assert broll.FILTERS[name] == 1

    def test_a_death_alone_in_a_grave_clip_or_a_substance_alone_in_another_is_kept(self):
        assert _valid(_spec("bicycle", "a red bicycle", death_near=True), "grave")[0]
        assert _valid(_spec("bicycle", "a red bicycle", substance=True, intake=True))[0]
        assert _valid(_spec("bicycle", "a red bicycle", substance=True), "real")[0]
        assert not broll.FILTERS

    def test_a_death_mentioned_in_passing_keeps_its_picture_in_every_clip(self):
        # v21: "grave" only when a death is the clip's subject; a death mentioned in passing is "real" and its sentence
        # is flagged death_near. The code no longer drops it: its picture only has to evoke nothing of it.
        for gravity in ("none", "real", "grave"):
            s, why = _valid(_spec("bicycle", "a red bicycle", death_near=True), gravity)
            assert s and why == "ok" and s["death_near"] is True, gravity
        assert not broll.FILTERS
        # its alternative goes through the same check: kept as well
        alt = {k: v for k, v in _spec("bicycle", "x").items() if k in broll_spec.ALT_FIELDS}
        s, _ = _valid(_spec("bicycle", "a red bicycle", alt={**alt, "subject": "a red bicycle bell", "death_near": True}))
        assert s["alt"]["subject"] == "a red bicycle bell" and s["alt"]["death_near"] is True
        assert not broll.FILTERS
        # what is still dropped: a death with a substance or an intake (the spec's, and its alternative's)
        s, why = _valid(_spec("bicycle", "a red bicycle", death_near=True, intake=True))
        assert s is None and why == "a death with a substance or an intake"
        s, _ = _valid(_spec("bicycle", "a red bicycle",
                            alt={**alt, "subject": "a red bicycle bell", "death_near": True, "substance": True}))
        assert s and "alt" not in s
        assert broll.FILTERS["spec: a death with a substance or an intake"] == 1
        assert broll.FILTERS["spec: alt a death with a substance or an intake"] == 1
        assert not any("does not tell one" in name for name in broll.FILTERS)

    def test_a_substance_in_a_grave_clip_is_dropped(self):
        for extra in ({"substance": True}, {"intake": True}):
            s, why = _valid({**_spec("bicycle", "a red bicycle"), **extra}, "grave")
            assert s is None and why == "a substance in a clip about a death", extra
        assert broll.FILTERS["spec: a substance in a clip about a death"] == 2
        # a death with a substance keeps its own, earlier reason
        s, why = _valid(_spec("bicycle", "a red bicycle", death_near=True, substance=True), "grave")
        assert s is None and why == "a death with a substance or an intake"

    def test_a_vision_has_nobody_in_it(self):
        s, _ = _valid(_spec("branches", "a forest of tiny branches", kind="vision", people="one", person="anonymous"))
        assert s["people"] == "none" and s["person"] == "none"
        assert broll.FILTERS["spec: vision with people (fixed)"] == 1

    def test_a_grave_clip_has_nobody_in_its_pictures(self):
        s, _ = _valid(_spec("garage", "a garage with a red bicycle", people="group", person="anonymous"), "grave")
        assert s["people"] == "none" and s["person"] == "none" and s["mood"]["gravity"] == "grave"
        s, _ = _valid(_spec("garage", "a garage", people="hands", person="anonymous"), "real")
        assert s["people"] == "hands" and s["person"] == "anonymous"

    def test_the_subject_words_must_be_said(self):
        assert _valid(_spec("gallons", "two gallons of water", words="gallons of water"))[0]
        assert _valid(_spec("gallons", "a gallon jug", words="Gallon!"))[0]                 # plural, punctuation
        assert _valid(_spec("microscope", "a microscope", words="microscopic"))[0]          # a 5-letter stem
        assert _valid(_spec("bicycle", "red bicycles", words="the bicycles"))[0]            # stopwords ignored
        s, why = _valid(_spec("bicycle", "a motorbike", words="motorbike"))
        assert s is None and why == "subject words not said in the clip"
        assert _valid(_spec("bicycle", "a bicycle", words="the"))[0] is None               # nothing named
        assert broll.FILTERS["spec: subject words not said in the clip"] == 2

    def test_a_speaker_is_never_pictured(self, monkeypatch):
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", {"speakers": [{"name": "Robert Lanza", "role": "host"}]})
        assert _valid(_spec("desk", "Lanza at his desk", words="desk"))[0] is None
        assert _valid(_spec("desk", "an old camera on a desk", words="camera"))[0]

    def test_the_kind_is_consistent(self):
        s, _ = _valid(_spec("brain", "a pale folded brain", kind="body_inside", instrument="MRI scanner"))
        assert s["kind"] == "instrument" and s["instrument"] == "MRI scanner"
        s, _ = _valid(_spec("brain", "a pale folded brain", kind="body_inside", people="one", person="anonymous"))
        assert s["kind"] == "body_inside" and s["people"] == "none" and s["person"] == "none"
        s, _ = _valid(_spec("bicycle", "a red bicycle", kind="pair"))
        assert s["kind"] == "thing" and s["subject_b"] == ""
        s, _ = _valid(_spec("bicycle", "a red bicycle", instrument="telescope"))
        assert s["instrument"] == ""
        s, _ = _valid(_spec("bicycle", "a red bicycle", people="one", person="none"))
        assert s["person"] == "anonymous"

    def test_word_caps(self):
        s, _ = _valid(_spec("bicycle", "a very old red bicycle with a bent wheel and a bell", said=" ".join(["w"] * 40),
                            details=" ".join(["rust"] * 30), state=" ".join(["leaning"] * 15)))
        assert len(s["subject"].split()) == 8 and len(s["said"].split()) == 25
        assert len(s["details"].split()) == 20 and len(s["state"].split()) == 10

    def test_a_vision_is_a_concrete_thing_said(self):
        # the thing seen, in his words: kept
        assert _valid(_spec("branches", "a forest of tiny branches", kind="vision"))[0]
        # a colour field standing for a sentence: dropped (the bench's visions no viewer linked)
        s, why = _valid(_spec("storm", "a saturated field of overlapping colour", words="storm", kind="vision"))
        assert s is None and why == "a vision of no concrete thing said"
        # a sight made only of light and colours, even when said: dropped
        s, why = broll_spec.validate(_spec("storm", "swirling colours of light", words="colours and light",
                                           kind="vision"), "and then it was all colours and light", "none")
        assert s is None and why == "a vision of no concrete thing said"
        assert broll.FILTERS["spec: a vision of no concrete thing said"] == 2
        # the same picture as a thing is no vision: only its worth goes down if it is not the thing named
        assert _valid(_spec("storm", "a saturated field of overlapping colour", words="storm"))[0]

    def test_a_spec_dropped_for_its_picture_hands_its_place_to_its_alt(self):
        alt = {"kind": "scene", "subject": "a storm over the sea", "subject_words": "storm", "shot": "wide"}
        s, why = _valid(_spec("storm", "a field of colour", words="storm", kind="vision", hero=True, worth=4, alt=alt))
        assert why == "ok" and s["subject"] == "a storm over the sea" and s["kind"] == "scene"
        assert s["worth"] == 3 and s["hero"] is False and "alt" not in s and s["anchor"] == "storm"
        assert broll.FILTERS["spec: its alternative instead"] == 1
        # a fault of the words (a figure of speech) is the alt's too: both go
        s, why = _valid(_spec("storm", "a storm over the sea", literal="figure", alt=alt))
        assert s is None and why == "a figure of speech"
        # an invalid alt cannot take the place
        s, why = _valid(_spec("storm", "a field of colour", words="storm", kind="vision",
                              alt={**alt, "subject_words": "hurricane"}))
        assert s is None and broll.FILTERS["spec: alt subject words not said in the clip"] == 1

    def test_a_subject_that_is_not_the_thing_named_ranks_last(self):
        s, _ = _valid(_spec("bicycle", "a garage workbench with tools", worth=5))
        assert s["worth"] == 3 and broll.FILTERS["spec: subject not the thing named (worth lowered)"] == 1
        assert _valid(_spec("bicycle", "a garage workbench", worth=1))[0]["worth"] == 1
        # the thing named, a plural, a stem or the start of a word: untouched
        for subject, words in (("an old film camera", "camera"), ("red bicycles", "bicycle"),
                               ("a microscope slide", "microscopic"), ("a desert at night", "deserts")):
            assert _valid(_spec("camera", subject, words=words, worth=4))[0]["worth"] == 4, subject
        assert broll.FILTERS["spec: subject not the thing named (worth lowered)"] == 2

    def test_an_invalid_alt_goes_the_spec_stays(self):
        alt = {k: v for k, v in _spec("bicycle", "x").items() if k in broll_spec.ALT_FIELDS}
        s, _ = _valid(_spec("bicycle", "a red bicycle", alt={**alt, "subject": "a red bicycle bell", "literal": "figure"}))
        assert s and "alt" not in s and broll.FILTERS["spec: alt a figure of speech"] == 1
        s, _ = _valid(_spec("bicycle", "a red bicycle", alt={**alt, "subject": "a motorbike", "subject_words": "motorbike"}))
        assert s and "alt" not in s
        s, _ = _valid(_spec("bicycle", "a red bicycle", alt={"subject": "a red bicycle in a garage", "shot": "wide",
                                                             "kind": "vision", "people": "group"}))
        assert set(s["alt"]) == set(broll_spec.ALT_FIELDS + ("role", "idea", "light"))
        assert s["alt"]["subject"] == "a red bicycle in a garage" and s["alt"]["shot"] == "wide"
        assert s["alt"]["people"] == "none"          # a vision, fixed like the spec
        assert s["alt"]["mood"]["valence"] == "neutral"   # the spec's mood when the alt gives none
        assert s["alt"]["role"] == "point"                # the spec's role, "point" when it gave none

    def test_the_idea_the_role_and_the_light_are_cleaned(self):
        s, why = _valid(_spec("soldiers", "soldiers marching", idea=" ".join(["meaning"] * 40),
                              light=" ".join(["lamplight"] * 20), role=" Vehicle "))
        assert why == "ok" and s["role"] == "vehicle"
        assert len(s["idea"].split()) == 25 and len(s["light"].split()) == 12
        s, _ = _valid(_spec("soldiers", "soldiers marching"))                      # none given: the old chain's defaults
        assert s["role"] == "point" and s["idea"] == "" and s["light"] == ""
        for odd in ("metaphor", "", None, 3):                                      # an unknown role is the point
            s, _ = _valid(_spec("soldiers", "soldiers marching", role=odd))
            assert s["role"] == "point", odd

    def test_a_vehicle_needs_no_spoken_name_and_is_not_ranked_last(self):
        # role "vehicle": the thing named is only the vehicle of an idea, the picture shows what the sentence means
        s, why = _valid(_spec("bicycle", "a man laughing in a diner booth", words="motorbike", role="vehicle", worth=5))
        assert why == "ok" and s["role"] == "vehicle" and s["worth"] == 5
        assert _valid(_spec("bicycle", "a garage workbench with tools", role="vehicle", worth=5))[0]["worth"] == 5
        assert not broll.FILTERS
        # a "point" is the thing named: the same fields are dropped, or ranked last (and "point" is the default role)
        s, why = _valid(_spec("bicycle", "a man laughing in a diner booth", words="motorbike", role="point"))
        assert s is None and why == "subject words not said in the clip"
        assert _valid(_spec("bicycle", "a man laughing in a diner booth", words="motorbike"))[0] is None
        assert _valid(_spec("bicycle", "a garage workbench with tools", role="point", worth=5))[0]["worth"] == 3
        assert _valid(_spec("bicycle", "a garage workbench with tools", worth=5))[0]["worth"] == 3
        assert broll.FILTERS["spec: subject words not said in the clip"] == 2
        assert broll.FILTERS["spec: subject not the thing named (worth lowered)"] == 2

    def test_a_vision_of_a_colour_field_is_dropped_whatever_the_role(self):
        # the "vision of no concrete thing said" drop is the old chain's: only the idea round (ideas=True) lifts it
        for role in ("point", "vehicle"):
            s, why = _valid(_spec("storm", "a field of colour", words="storm", kind="vision", role=role))
            assert s is None and why == "a vision of no concrete thing said", role
        assert broll.FILTERS["spec: a vision of no concrete thing said"] == 2
        # its alternative takes its place, with the spec's role
        alt = {"kind": "scene", "subject": "a storm over the sea", "subject_words": "storm", "shot": "wide"}
        s, why = _valid(_spec("storm", "a field of colour", words="storm", kind="vision", role="vehicle", alt=alt))
        assert why == "ok" and s["subject"] == "a storm over the sea" and s["role"] == "vehicle"

    def test_the_alt_keeps_the_role_of_its_spec(self):
        alt = {k: v for k, v in _spec("bicycle", "x").items() if k in broll_spec.ALT_FIELDS}
        alt.update(subject="a motorbike", subject_words="motorbike")
        s, _ = _valid(_spec("bicycle", "a red bicycle", role="vehicle", alt=alt))
        assert s["alt"]["role"] == "vehicle" and s["alt"]["subject"] == "a motorbike"   # no spoken name needed either
        s, _ = _valid(_spec("bicycle", "a red bicycle", role="point", alt=alt))
        assert "alt" not in s and broll.FILTERS["spec: alt subject words not said in the clip"] == 1

    def test_the_idea_round_leaves_the_subject_checks_to_its_judges(self, monkeypatch):
        # ideas=True (v21): the picture is chosen after the judges' calls, so neither the spoken name of the subject nor
        # the colour-field check applies, whatever the role, and no worth is taken off; every other drop still holds
        for role in ("point", "vehicle"):
            s, why = broll_spec.validate(_spec("bicycle", "a motorbike", words="motorbike", role=role, worth=5),
                                         TEXT, "none", ideas=True)
            assert why == "ok" and s["worth"] == 5, role
        field = _spec("storm", "a saturated field of overlapping colour", words="storm", kind="vision")
        assert broll_spec.validate(field, TEXT, "none", ideas=True)[0]
        alt = {k: v for k, v in _spec("bicycle", "x").items() if k in broll_spec.ALT_FIELDS}
        s, _ = broll_spec.validate(_spec("bicycle", "a red bicycle", alt={**alt, "subject": "a motorbike",
                                                                          "subject_words": "motorbike"}),
                                   TEXT, "none", ideas=True)
        assert s["alt"]["subject"] == "a motorbike"
        assert not broll.FILTERS
        for extra, reason in (({"literal": "figure"}, "a figure of speech"),
                              ({"literal": "denied"}, "denied by the speaker"),
                              ({"person": "real", "people": "one"}, "a real person"),
                              ({"death_near": True, "intake": True}, "a death with a substance or an intake"),
                              ({"subject": "   "}, "no subject")):
            s, why = broll_spec.validate({**_spec("storm", "a storm over the sea"), **extra}, TEXT, "none", ideas=True)
            assert s is None and why == reason, extra
        s, why = broll_spec.validate(_spec("storm", "a storm", words="storm"), TEXT, "grave", ideas=True)
        assert why == "ok"
        s, why = broll_spec.validate(_spec("storm", "a storm", substance=True), TEXT, "grave", ideas=True)
        assert s is None and why == "a substance in a clip about a death"
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", {"speakers": [{"name": "Robert Lanza", "role": "host"}]})
        assert broll_spec.validate(_spec("desk", "Lanza at his desk", words="desk"), TEXT, "none", ideas=True)[0] is None


class TestPlanSpecs:
    def _plan(self, monkeypatch, moments, gravity="none", n=2, **kw):
        seen = {}

        def fake(prompt, schema, **k):
            seen.update(prompt=prompt, schema=schema, **k)
            return {"clip_gravity": gravity, "moments": moments}

        monkeypatch.setattr(broll, "claude_json", fake)
        clip = {"video_title_for_youtube_short": "The night march", "viral_hook_text": "Two gallons, one night"}
        got = broll_spec.plan_specs(clip, WORDS, n, [], sheets=["/tmp/frames_1.jpg"], **kw)
        return seen, got

    def _six(self):
        return [
            _spec("soldiers", "soldiers carrying water cans", kind="scene", worth=5, hero=True, shot="wide",
                  people="group", person="anonymous",
                  alt={"subject": "two gallons of water", "subject_words": "gallons of water", "kind": "thing"}),
            _spec("microscope", "neurons like tiny branches", words="neurons", kind="instrument",
                  instrument="light microscope", worth=4, shot="macro"),
            _spec("brain", "a pale folded brain", kind="body_inside", worth=3, people="one", person="anonymous"),
            _spec("storm", "a storm", literal="figure", worth=5),
            _spec("bicycle", "a red bicycle", worth=2),
            _spec("camera", "a motorbike", words="motorbike", worth=5),
        ]

    def test_moments_and_reserves(self, monkeypatch):
        seen, (moments, reserves) = self._plan(monkeypatch, self._six())
        assert [m["spec"]["subject"] for m in moments] == ["soldiers carrying water cans", "neurons like tiny branches"]
        assert [m["spec"]["subject"] for m in reserves] == ["a pale folded brain", "a red bicycle"]
        assert moments[0]["t"] < moments[1]["t"]
        for m in moments + reserves:
            for k in ("t", "anchor", "dur", "hero", "said", "mood", "spec", "query", "style", "people", "inside_body",
                      "clip_gravity"):
                assert k in m, k
            assert m["query"] == m["spec"]["subject"] and m["style"] == "photo" and m["clip_gravity"] == "none"
            assert m["mood"]["valence"] == "neutral" and not m["idea"].startswith("spec#")
            assert broll.CARD_DUR_MIN <= m["dur"] <= broll.CARD_DUR_MAX
        assert moments[0]["hero"] is True and moments[1]["hero"] is False and not any(m["hero"] for m in reserves)
        assert moments[0]["spec"]["alt"]["subject"] == "two gallons of water"
        assert moments[1]["spec"]["instrument"] == "light microscope"
        brain = reserves[0]
        assert brain["inside_body"] is True and brain["people"] == "none" and brain["spec"]["kind"] == "body_inside"
        assert broll.FILTERS["spec: a figure of speech"] == 1
        assert broll.FILTERS["spec: subject words not said in the clip"] == 1
        # the call: one, the editor's stage, the sheets attached, the schema, the clip in the prompt
        assert seen["stage"] == "broll_plan" and seen["attach"] == ["/tmp/frames_1.jpg"]
        assert seen["schema"] is broll_spec.SPEC_SCHEMA
        p = seen["prompt"]
        assert "The night march" in p and "Two gallons, one night" in p and "frames_1.jpg" in p
        flat = " ".join(p.split())
        cap = 2 + broll.CANDIDATES_MORE + broll_spec.CANDIDATES_EXTRA
        assert broll_spec.candidates_cap(2) == cap and cap > 2 + broll.CANDIDATES_MORE
        assert f"at least 4 when the clip names that many, up to {cap};" in flat and "the best 2 by worth" in flat
        assert broll._numbered_text(WORDS)[:200] in p and "(no brief for this video)" in p
        assert "{" not in p.split("EPISODE BRIEF")[0]

    def test_a_moment_carries_the_idea_and_the_role_of_its_spec(self, monkeypatch):
        specs = [_spec("soldiers", "soldiers carrying water cans", worth=5, idea="a night march told as a feat",
                       role="vehicle"),
                 _spec("camera", "an old camera on a desk", worth=4)]
        _seen, (moments, _r) = self._plan(monkeypatch, specs)
        by = {m["spec"]["subject"]: m for m in moments}
        march, camera = by["soldiers carrying water cans"], by["an old camera on a desk"]
        assert march["role"] == "vehicle" and march["idea_text"] == "a night march told as a feat"
        assert camera["role"] == "point" and camera["idea_text"] == "" and camera["spec"]["light"] == ""
        assert march["idea"] == "" and camera["idea"] == ""          # "idea" stays the parser's tag field, emptied

    def test_the_idea_round_keeps_the_specs_the_old_chain_drops_for_their_words(self, monkeypatch):
        # plan_specs(ideas=True) passes ideas to validate: the motorbike nobody says is no longer dropped (nor ranked
        # last); the figure of speech still is
        _seen, (moments, reserves) = self._plan(monkeypatch, self._six(), ideas=True)
        assert "a motorbike" in [m["spec"]["subject"] for m in moments + reserves]
        assert "spec: subject words not said in the clip" not in broll.FILTERS
        assert "spec: subject not the thing named (worth lowered)" not in broll.FILTERS
        assert broll.FILTERS["spec: a figure of speech"] == 1
        broll.FILTERS.clear()
        _seen, (moments, reserves) = self._plan(monkeypatch, self._six())             # the default: the old chain
        assert "a motorbike" not in [m["spec"]["subject"] for m in moments + reserves]
        assert broll.FILTERS["spec: subject words not said in the clip"] == 1

    def test_no_marked_hero_no_hero(self, monkeypatch):
        specs = self._six()
        specs[0]["hero"] = False
        _seen, (moments, _r) = self._plan(monkeypatch, specs)
        assert not any(m["hero"] for m in moments)

    def test_a_grave_clip(self, monkeypatch):
        _seen, (moments, reserves) = self._plan(monkeypatch, self._six(), gravity="grave")
        assert moments and all(m["people"] == "none" and m["spec"]["person"] == "none" for m in moments + reserves)
        assert all(m["clip_gravity"] == "grave" for m in moments + reserves)

    def test_nothing_listed(self, monkeypatch):
        _seen, got = self._plan(monkeypatch, [])
        assert got == ([], [])

    def test_every_placed_spec_not_kept_is_a_reserve(self, monkeypatch):
        specs = [_spec("soldiers", "soldiers carrying water cans", worth=5),
                 _spec("desert", "a desert at night", worth=2),               # 3.4 s from the soldiers: too close
                 _spec("bicycle", "a red bicycle", worth=3),
                 _spec("camera", "an old camera on a desk", worth=4),
                 _spec("brain", "a pale folded brain", kind="body_inside", worth=4)]
        _seen, (moments, reserves) = self._plan(monkeypatch, specs, n=2)
        assert [m["spec"]["subject"] for m in moments] == ["soldiers carrying water cans", "an old camera on a desk"]
        assert [m["spec"]["subject"] for m in reserves] == ["a pale folded brain", "a red bicycle", "a desert at night"]
        assert not any(m["hero"] for m in reserves)
        for r in reserves:                       # a reserve never runs into the next planned moment
            nxt = [m["t"] for m in moments if m["t"] > r["t"]]
            assert not nxt or r["t"] + r["dur"] <= min(nxt) - broll.DUR_NEXT_GAP + 1e-6 or r["dur"] == broll.CARD_DUR_MIN

    def test_an_anchor_that_skips_a_word_is_put_on_the_spoken_one(self, monkeypatch):
        # "kept a red bicycle" said; the editor wrote "kept red bicycle" and the marker's time, 3 s early
        spec = _spec("bicycle", "a red bicycle", worth=5)
        spec.update(anchor="kept red bicycle", time=_at("bicycle")["start"] - 3.0)
        _seen, (moments, _r) = self._plan(monkeypatch, [spec, _spec("soldiers", "soldiers carrying water cans")])
        bike = next(m for m in moments if m["spec"]["subject"] == "a red bicycle")
        assert bike["anchor"] == "bicycle" and bike["spec"]["time"] == _at("bicycle")["start"]
        assert broll.FILTERS["spec: anchor respelled (fixed)"] == 1 and "parser: anchor not found" not in broll.FILTERS

    def test_an_anchor_said_far_from_its_time_is_found(self, monkeypatch):
        spec = _spec("camera", "an old camera on a desk", worth=5)
        spec["time"] = 0.0                                   # 30 s off: the parser's 4 s would miss it
        _seen, (moments, _r) = self._plan(monkeypatch, [spec], n=1)
        assert [m["anchor"] for m in moments] == ["camera"] and not broll.FILTERS.get("parser: anchor not found")

    def test_an_anchor_on_the_punchline_moves_to_its_next_mention(self, monkeypatch):
        first, second = [w for w in WORDS if "storm" in w["text"]]
        monkeypatch.setattr(broll, "claude_json", lambda *a, **k: {
            "clip_gravity": "none", "moments": [_spec("storm", "a storm over the sea", time=first["start"])]})
        moments, _r = broll_spec.plan_specs({}, WORDS, 2, [first["start"]])
        assert len(moments) == 1 and moments[0]["spec"]["time"] == second["start"]
        assert broll.FILTERS["spec: anchor moved into the window (fixed)"] == 1
        # an anchor never spoken: its subject words are, near its time
        monkeypatch.setattr(broll, "claude_json", lambda *a, **k: {
            "clip_gravity": "none", "moments": [{**_spec("bicycle", "a red bicycle"), "anchor": "the motorbike"}]})
        assert [m["anchor"] for m in broll_spec.plan_specs({}, WORDS, 2, [])[0]] == ["bicycle"]
        # no word of it spoken within RELOCATE_MAX s of its time: left to the parser, which drops it
        monkeypatch.setattr(broll, "claude_json", lambda *a, **k: {
            "clip_gravity": "none", "moments": [{**_spec("bicycle", "a red bicycle", time=0.0), "anchor": "the motorbike"}]})
        assert broll_spec.plan_specs({}, WORDS, 2, [])[0] == []
        assert broll.FILTERS["parser: anchor not found"] == 1


class TestRunUnderTheMinimum:
    """broll_v20.run: under the minimum after the reserves, the alternatives never rendered are made."""

    @staticmethod
    def _ok(text="no"):
        return {"sees": "a thing", "fits": "with", "links": True, "look": 4,
                "answers": {"q_subject": "yes", "q_count": "1", "q_people": "0", "q_text": text,
                            "q_medium": "photograph", "q_unsafe": "no", "q_body_photo": "no"}}

    def test_the_alternative_of_a_dropped_picture_is_made(self, monkeypatch, tmp_path):
        import os
        import broll_check
        import broll_v20
        alt = {k: v for k, v in _spec("bicycle", "a red bicycle").items() if k in broll_spec.ALT_FIELDS}
        alt.update(subject="an old camera on a desk", subject_words="camera")

        def moment(t, subject, **kw):
            spec = {**_spec("bicycle", subject), "alt": dict(alt), **kw}
            return {"t": t, "anchor": "bicycle", "said": "x", "dur": 3.0, "hero": False, "mood": {}, "score": 4,
                    "spec": spec}
        monkeypatch.setattr(broll, "_frame_sheets", lambda clip_path, tmp: [])
        monkeypatch.setattr(broll_spec, "plan_specs", lambda *a, **k: (
            [moment(6.0, "a red bicycle with text"), moment(12.0, "soldiers carrying water cans")], []))
        # the first picture always has writing in it: rendered again, then dropped (decide never reaches its alt)
        monkeypatch.setattr(broll_check, "check", lambda cands, words, **k: {
            os.path.basename(c["file"]): self._ok("yes" if os.path.basename(c["file"]).startswith("broll_0") else "no")
            for c in cands})
        made = []

        def render(text, out, layout):
            made.append(os.path.basename(out))
            return out, len(made)
        kept, pictured = broll_v20.run("clip.mp4", {}, [], None, 0, 30, 4, [], 1.0, 2.0, 2.0, (), None,
                                       str(tmp_path), render)
        assert "broll_2a.jpg" in made and len(kept) == 2 and len(pictured) == 3
        assert [c["m"]["spec"]["subject"] for c in kept] == ["an old camera on a desk", "soldiers carrying water cans"]
        assert "alt" not in kept[0]["m"]["spec"]


class TestEditorPrompt:
    PRINCIPLES = ("THE IDEA OF THE SENTENCE FIRST", "THE LITERAL SENSE OF THE THING NAMED", "ONE VISIBLE INSTANT",
                  "AN EXPERIENCE IS WHAT IS SEEN", "THE INSIDE OF A BODY IS ALWAYS DRAWN", "WHAT AN INSTRUMENT SEES",
                  "NEVER A REAL PERSON", "A DEATH", "KEEP THE FACTS SAID", "VARY", '"worth" 1-5', '"hero" true',
                  "AN ALT FOR EVERY CANDIDATE")

    def test_the_house_principles_in_order(self):
        p = " ".join(broll_spec.EDITOR_PROMPT.split())
        at = [p.index(k) for k in self.PRINCIPLES]
        assert at == sorted(at)
        for phrase in ("does not exist in the story the clip tells", "Read the sentence before",
                       "the speaker says it is not so", "no duration, no sound, no name or writing, no feeling",
                       'kind "vision"', 'people "none", never the person who sees', 'kind "body_inside"',
                       'kind "instrument"', 'person "real" and the code drops the spec', "A speaker is never pictured",
                       "never the means of the death",
                       "an overdose, a means of suicide or a symbol of death, not even as a visual cliché",
                       "add none of your own", "a real scene with depth", "a different picture of the same words",
                       "the code writes the image prompt from the fields", "no style word", "no metaphor"):
            assert phrase in p, phrase

    def test_the_idea_of_the_sentence_comes_first(self):
        # v21, principle 1: a picture is for what a sentence MEANS; "idea" and "role" (point | vehicle)
        p = " ".join(broll_spec.EDITOR_PROMPT.split())
        one, two = p.index("1. THE IDEA OF THE SENTENCE FIRST"), p.index("2. THE LITERAL SENSE OF THE THING NAMED")
        first = p[one:two]
        for phrase in ("a picture is for what a sentence MEANS, not for the word it contains",
                       "Read the sentence before the anchor", 'write "idea" (what it means, one line) and "role"',
                       '"point" when the thing named IS the point', "take it away and the idea falls",
                       "literal, exact, at its real scale, in its real setting",
                       '"subject" is that thing and "subject_words" its spoken name',
                       '"vehicle" when the thing is only the vehicle of an idea',
                       "the picture will show what the sentence means", "a concrete scene a camera could film",
                       "the art director proposes others", "A sentence that means nothing showable gets no entry",
                       "the face is the picture"):
            assert phrase in first, phrase
        assert "A figure or a denial gets no picture" in p[two:]          # principle 2 keeps the figure and the denial

    def test_the_old_principles_are_gone(self):
        p = " ".join(broll_spec.EDITOR_PROMPT.split())
        for gone in ("A PICTURE ONLY FOR WHAT IS NAMED OR TOLD", "THE LITERAL SENSE ONLY",
                     "The subject IS the thing named and holds its spoken name", "never a stand-in for an idea",
                     "a death in a clip that does not tell one", '"grave" ONLY when the clip TELLS a death'):
            assert gone not in p, gone

    def test_a_death_in_passing_is_real_and_flagged_not_grave(self):
        # v21, principle 8: "grave" only when a death is the clip's subject; in passing = "real" + death_near, whose
        # picture may evoke nothing of it (the old rule "no picture for a death in a clip that does not tell one" is gone)
        p = " ".join(broll_spec.EDITOR_PROMPT.split())
        eight = p[p.index("8. A DEATH"):p.index("9. KEEP THE FACTS SAID")]
        for phrase in ('"grave" ONLY when a death is the clip\'s SUBJECT',
                       "its title, its hook or its thesis is about that death",
                       '"real" when a death, an illness, an injury, an addiction or a loss is mentioned in passing',
                       'else "none"', "Grave: every picture is an absence", "nobody in the frame",
                       'a sentence that mentions a death is flagged "death_near", and its picture may evoke nothing of it',
                       "In a grave clip, no drug, poison or medicine", "A DRUG is never shown itself"):
            assert phrase in eight, phrase

    def test_every_field_is_explained(self):
        p = broll_spec._RULES
        for field in ("anchor", "time", "said", "idea", "role", "kind", "subject", "subject_words", "subject_b", "count",
                      "state", "setting", "details", "people", "person", "shot", "death_near", "substance", "intake",
                      "notion", "alt", "worth", "hero", "literal", "clip_gravity"):
            assert f'"{field}"' in p, field
        assert '"point" or "vehicle"' in " ".join(p.split())
        assert visual_mood.MOOD_RULE in broll_spec.EDITOR_PROMPT

    def test_no_bench_example(self):
        p = broll_spec.EDITOR_PROMPT
        assert not re.search(r"\b(tumou?rs?|cages?|meth|galax\w*|refrigerators?|fridges?)\b", p, re.I)
        # v21: 938 words (principle 1 took the idea and the role); the cap stays tight so the prompt does not swell
        assert 500 <= len(re.findall(r"[A-Za-z][A-Za-z'_-]*", broll_spec._RULES)) <= 950

    def test_what_the_bench_lost(self):
        p = " ".join(broll_spec._RULES.split())
        for phrase in ("one for EVERY concrete thing named", "others are reserves for a picture that fails",
                       '"subject" is that thing and "subject_words" its spoken name',
                       'kind "vision" only for a concrete thing he says was seen', "A colour, a light or a blur is no vision",
                       "an operation (the organ, never the team)", "1-3 CONSECUTIVE words copied exactly"):
            assert phrase in p, phrase
