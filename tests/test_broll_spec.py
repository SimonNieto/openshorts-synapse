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

    def test_the_alt_is_the_same_fields_without_where_and_worth(self):
        alt = broll_spec.SPEC_SCHEMA["properties"]["moments"]["items"]["properties"]["alt"]["properties"]
        assert not {"anchor", "time", "said", "worth", "hero"} & set(alt)
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

    def test_a_death_in_a_clip_that_does_not_tell_one_is_dropped(self):
        for gravity in ("none", "real"):
            s, why = _valid(_spec("bicycle", "a red bicycle", death_near=True), gravity)
            assert s is None and why == "a death in a clip that does not tell one", gravity
        assert broll.FILTERS["spec: a death in a clip that does not tell one"] == 2
        # its alternative goes through the same check: dropped, the spec kept
        alt = {k: v for k, v in _spec("bicycle", "x").items() if k in broll_spec.ALT_FIELDS}
        s, _ = _valid(_spec("bicycle", "a red bicycle", alt={**alt, "subject": "a red bicycle bell", "death_near": True}))
        assert s and "alt" not in s
        assert broll.FILTERS["spec: alt a death in a clip that does not tell one"] == 1

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
        assert set(s["alt"]) == set(broll_spec.ALT_FIELDS)
        assert s["alt"]["subject"] == "a red bicycle in a garage" and s["alt"]["shot"] == "wide"
        assert s["alt"]["people"] == "none"          # a vision, fixed like the spec
        assert s["alt"]["mood"]["valence"] == "neutral"   # the spec's mood when the alt gives none


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
        return {"sees": "a thing", "links": True, "look": 4,
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
    PRINCIPLES = ("A PICTURE ONLY FOR WHAT IS NAMED OR TOLD", "THE LITERAL SENSE ONLY", "ONE VISIBLE INSTANT",
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
                       '"grave" ONLY when the clip TELLS a death', "never the means of the death",
                       "an overdose, a means of suicide or a symbol of death, not even as a visual cliché",
                       "add none of your own", "a real scene with depth", "a different picture of the same words",
                       "the code writes the image prompt from the fields", "no style word", "no metaphor"):
            assert phrase in p, phrase

    def test_every_field_is_explained(self):
        p = broll_spec._RULES
        for field in ("anchor", "time", "said", "kind", "subject", "subject_words", "subject_b", "count", "state",
                      "setting", "details", "people", "person", "shot", "death_near", "substance", "intake",
                      "notion", "alt", "worth", "hero", "literal", "clip_gravity"):
            assert f'"{field}"' in p, field
        assert visual_mood.MOOD_RULE in broll_spec.EDITOR_PROMPT

    def test_no_bench_example(self):
        p = broll_spec.EDITOR_PROMPT
        assert not re.search(r"\b(tumou?rs?|cages?|meth|galax\w*|refrigerators?|fridges?)\b", p, re.I)
        assert 500 <= len(re.findall(r"[A-Za-z][A-Za-z'_-]*", broll_spec._RULES)) <= 860

    def test_what_the_bench_lost(self):
        p = " ".join(broll_spec._RULES.split())
        for phrase in ("one for EVERY concrete thing named", "others are reserves for a picture that fails",
                       "The subject IS the thing named and holds its spoken name", "never a stand-in for an idea",
                       'kind "vision" only for a concrete thing he says was seen', "A colour, a light or a blur is no vision",
                       "an operation (the organ, never the team)", "1-3 CONSECUTIVE words copied exactly"):
            assert phrase in p, phrase
