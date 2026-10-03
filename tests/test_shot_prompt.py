"""B-roll v20: the image prompt built from a shot spec (shot_prompt.py): subject first, no negation, word caps,
deterministic, no count sentence from a measure, and the checker's questions. No model is called."""
import itertools
import re

import pytest

import shot_prompt as sp

NEG = re.compile(r"\b(?:no|not|never|without|avoid\w*|nothing|none|nobody|nowhere|neither|nor|cannot)\b|n['’]t", re.I)
CAMERA = re.compile(r"\b(?:canon|nikon|sony|leica|hasselblad|fujifilm|gopro|arri|8k|4k|masterpiece|mm|f/\d|bokeh|dslr)\b",
                    re.I)

BASE = {"visibility": "eye", "scale": "hand", "era": "now", "valence": "neutral", "intensity": "steady",
        "distance": "explained", "gravity": "none", "cue": "x"}


def mood(**kw):
    return {**BASE, **kw}


DRAW = ("Painted in opaque water-based colour with a fine dry brush: thin warm outlines where two forms meet, volumes "
        "modelled in three soft values, a faint tooth of paper in the flat areas, forms simplified to their readable "
        "masses.")

THING = {"kind": "thing", "subject": "red apple", "count": "1", "state": "resting on a wooden table", "setting": "plain",
         "details": "a glossy skin, a short green stem, small drops of water", "people": "none", "shot": "close",
         "mood": mood(true_colours="deep red skin, green stem, brown wood")}
SCENE = {"kind": "scene", "subject": "commuters on a subway platform", "count": "many", "state": "waiting for a train",
         "setting": "a crowded city station at rush hour",
         "details": "yellow edge line, tiled walls, a long line of coats and bags", "people": "group", "shot": "wide",
         "hero": True, "mood": mood(era="recent", valence="uneasy", intensity="charged", scale="place",
                                    true_colours="grey tiles, yellow line")}
VISION = {"kind": "vision", "subject": "a tunnel of white light", "count": "1", "state": "narrowing ahead",
          "setting": "in a dark room", "details": "soft blurred edges, a bright centre", "people": "none",
          "shot": "wide", "hero": True, "mood": mood(valence="elated", intensity="charged", visibility="inner",
                                                     colours_said="white light, deep black")}
INSTRUMENT = {"kind": "instrument", "instrument": "fluorescence microscope", "subject": "neuron", "count": "1",
              "state": "glowing along its branches", "setting": "plain",
              "details": "a round cell body, thin branching fibres", "people": "none", "shot": "macro",
              "mood": mood(visibility="instrument", scale="micro", true_colours="green glow on black")}
BODY = {"kind": "body_inside", "subject": "human brain seen from above", "count": "1", "state": "resting level",
        "setting": "plain", "details": "two halves, a deep central groove, folded surface", "people": "none",
        "shot": "close", "mood": mood(valence="grim", gravity="real", true_colours="pink grey tissue")}
PAIR = {"kind": "pair", "subject": "chimpanzee skull", "subject_b": "human skull", "count": "1", "state": "",
        "setting": "plain", "details": "the brow ridge, the jaw, the round cranium", "people": "none", "shot": "medium",
        "mood": mood()}
# name -> (spec, layout, drawing)
SIX = {"thing": (THING, "card", ""), "scene": (SCENE, "hero", ""), "vision": (VISION, "hero", ""),
       "instrument": (INSTRUMENT, "card", ""), "body_inside": (BODY, "card", DRAW), "pair": (PAIR, "card", "")}


def body_words(prompt, drawing=""):
    return len(prompt.replace(drawing, "", 1).split()) if drawing else len(prompt.split())


GOLDEN = {
    "thing": "A documentary photograph showing a single red apple, resting on a wooden table, on a plain dark "
             "background. Visible details: a glossy skin, a short green stem, small drops of water. Close-up of the "
             "subject, filling most of the frame, horizontal frame, the subject large and centred. Balanced light, a "
             "clear key light with soft shadows; soft directional light. Colours: deep red skin, green stem, brown "
             "wood.",
    "scene": "A documentary photograph on colour film from the late twentieth century, showing many commuters on a "
             "subway platform, waiting for a train, in a crowded city station at rush hour. Visible details: yellow "
             "edge line, tiled walls, a long line of coats and bags. A small group of anonymous strangers, seen "
             "together from a distance. Wide shot, the whole setting in view, vertical full-screen scene with a close "
             "foreground, a middle ground and depth behind. Low-key light, deep shadows, one pool of light on the "
             "subject; hard directional light, crisp shadows. Colours: grey tiles, yellow line.",
    "vision": "What is perceived from inside the experience, the whole frame filled edge to edge by a single tunnel "
              "of white light, narrowing ahead, in a dark room. Visible details: soft blurred edges, a bright centre. "
              "Wide shot, the whole setting in view, vertical full-screen scene with a close foreground, a middle "
              "ground and depth behind. Bright high-key light with open shadows; hard directional light, crisp "
              "shadows. Colours: white light, deep black.",
    "instrument": "A fluorescence microscope image showing a single neuron, glowing along its branches, on a plain "
                  "dark background. Visible details: a round cell body, thin branching fibres. Macro close-up of the "
                  "finest detail, a thin sliver of sharp focus, horizontal frame, the subject large and centred. Even "
                  "illumination, clear detail. Colours: green glow on black.",
    "body_inside": DRAW + " It shows a single human brain seen from above, resting level, on a plain dark background. "
                   "Visible details: two halves, a deep central groove, folded surface. Close-up of the subject, "
                   "filling most of the frame, horizontal frame, the subject large and centred. Low-key light, deep "
                   "shadows, one pool of light on the subject; soft directional light. Colours: pink grey tissue, "
                   "muted colours.",
    "pair": "Two images side by side, the same scale. On the left, a chimpanzee skull; on the right, a human skull. "
            "Visible details: the brow ridge, the jaw, the round cranium. Medium shot from a few steps away, "
            "horizontal frame, two equal halves, each subject large and centred. Balanced light, a clear key light "
            "with soft shadows; soft directional light.",
}


class TestGolden:
    @pytest.mark.parametrize("name", list(SIX))
    def test_golden_prompt(self, name):
        spec, layout, drawing = SIX[name]
        assert sp.build_prompt(spec, layout, drawing) == GOLDEN[name]

    @pytest.mark.parametrize("name", list(SIX))
    def test_word_counts_and_no_negation(self, name):
        spec, layout, drawing = SIX[name]
        p = sp.build_prompt(spec, layout, drawing)
        assert sp.MIN_WORDS <= body_words(p, drawing) <= sp.MAX_WORDS
        assert not NEG.search(p.replace(drawing, "", 1) if drawing else p)
        assert not CAMERA.search(p.replace(drawing, "", 1) if drawing else p)

    @pytest.mark.parametrize("name", [n for n in SIX if n != "body_inside"])
    def test_subject_in_the_first_25_words(self, name):
        spec, layout, drawing = SIX[name]
        first = " ".join(sp.build_prompt(spec, layout, drawing).split()[:25]).lower()
        for key in ("subject", "subject_b"):
            if spec.get(key):
                assert all(w in first for w in sp._bare(spec[key]).lower().split()), (key, first)

    def test_the_drawing_leads_a_drawn_picture_and_is_left_as_given(self):
        p = sp.build_prompt(BODY, "card", DRAW)
        assert p.startswith(DRAW + " It shows a single human brain")
        assert "documentary photograph" not in p

    def test_a_drawing_that_negates_loses_that_piece_and_none_falls_back_to_the_house_one(self):
        p = sp.build_prompt(BODY, "card", DRAW + " Never a cartoon.")
        assert p.startswith(DRAW + " It shows") and not NEG.search(p.replace(DRAW, "", 1))
        assert sp.build_prompt(BODY, "card", "").startswith(sp.DRAWING_FALLBACK)
        assert sp.build_prompt(BODY, "card", "No colour, never painted.").startswith(sp.DRAWING_FALLBACK)

    def test_deterministic(self):
        for spec, layout, drawing in SIX.values():
            assert sp.build_prompt(spec, layout, drawing) == sp.build_prompt(dict(spec), layout, drawing)

    def test_the_spec_is_not_changed(self):
        before = repr(SCENE)
        sp.build_prompt(SCENE, "hero")
        sp.questions(SCENE)
        assert repr(SCENE) == before


class TestWordsOfTheMedium:
    def test_count_words(self):
        for c, words in (("1", "a single"), ("2", "two"), ("3", "three"), ("4", "four"), ("many", "many")):
            p = sp.build_prompt({**THING, "count": c}, "card")
            assert f"showing {words} red apple" in p, (c, p)

    def test_a_count_makes_the_head_noun_plural(self):
        assert sp._plural("red apple") == "red apples"
        assert sp._plural("glass of water") == "glasses of water"
        assert sp._plural("hand holding a pen") == "hands holding a pen"
        assert sp._plural("red blood cells") == "red blood cells"
        assert sp._plural("baby") == "babies" and sp._plural("woman at a desk") == "women at a desk"
        assert "three red apples" in sp.build_prompt({**THING, "count": "3"}, "card")
        assert "a single red apple" in sp.build_prompt({**THING, "subject": "a red apple"}, "card")

    def test_era_words_come_from_the_mood(self):
        now = sp.build_prompt(THING, "card")
        assert now.startswith("A documentary photograph showing")
        recent = sp.build_prompt({**THING, "mood": mood(era="recent")}, "card")
        assert recent.startswith("A documentary photograph on colour film from the late twentieth century, showing")
        early = sp.build_prompt({**THING, "mood": mood(era="early", true_colours="red skin")}, "card")
        assert early.startswith("A documentary photograph in black and white from the early twentieth century")
        assert "Colours:" not in early                       # a black-and-white picture names no colour
        before = sp.build_prompt({**THING, "mood": mood(era="before")}, "card")
        assert before.startswith("A documentary photograph of a faithful period reconstruction, showing")
        for p in (recent, early, before):
            assert len(p.split("showing")[0].split()) + 1 <= 14      # the medium: 14 words at most
        assert sp.build_prompt(THING, "card", era_words="in sepia from the 1990s").startswith(
            "A documentary photograph in sepia from the 1990s, showing")

    def test_other_kinds_ignore_the_era(self):
        for spec in (INSTRUMENT, VISION, BODY):
            p = sp.build_prompt({**spec, "mood": {**spec["mood"], "era": "early"}}, "card", DRAW)
            assert "twentieth century" not in p.replace(DRAW, "")

    VISION_LEAD = "What is perceived from inside the experience, the whole frame filled edge to edge by"

    def test_the_medium_by_kind(self):
        assert sp.build_prompt(VISION, "hero").startswith(self.VISION_LEAD + " a single tunnel of white light")
        assert sp.build_prompt(INSTRUMENT, "card").startswith("A fluorescence microscope image showing")
        assert sp.build_prompt({**INSTRUMENT, "instrument": "electron microscope"}, "card").startswith(
            "An electron microscope image showing")
        assert sp.build_prompt({**INSTRUMENT, "instrument": "x-ray"}, "card").startswith("An x-ray image showing")
        assert sp.build_prompt(PAIR, "card").startswith("Two images side by side, the same scale. On the left, ")

    def test_a_vision_is_what_is_perceived_never_someone_who_perceives(self):
        # "A photograph seen through the eyes of someone looking at ..." made the engine draw the person who sees (a man
        # in a kitchen for the voices in his head): the lead names the experience and the frame, never a viewer
        assert sp._medium(VISION, "") == self.VISION_LEAD
        assert sp._medium(VISION, "in sepia from the 1990s") == self.VISION_LEAD       # an era is for photographs only
        assert sp._medium({**VISION, "subject": "a swarm of tiny lights"}, "") == self.VISION_LEAD
        for layout, people, count, era in itertools.product(("hero", "card", "half"), ("none", "hands", "one", "group"),
                                                            ("1", "many"), ("now", "recent", "early", "before")):
            spec = {**VISION, "people": people, "count": count, "mood": {**VISION["mood"], "era": era}}
            p = sp.build_prompt(spec, layout)
            assert p.startswith(self.VISION_LEAD + " "), (layout, people, count, era)
            assert "someone" not in p.lower(), (layout, people, count, era, p)
            assert sp.MIN_WORDS <= len(p.split()) <= sp.MAX_WORDS and not NEG.search(p), p
        assert "someone" not in sp.build_prompt({**VISION, "light": "pale light from the left"}, "hero").lower()
        # the other kinds keep their own lead: only a vision is "what is perceived"
        for spec in (THING, SCENE, INSTRUMENT, PAIR):
            assert "perceived" not in sp.build_prompt(spec, "card")

    def test_setting(self):
        assert "on a plain dark background" in sp.build_prompt({**THING, "setting": "plain"}, "card")
        assert "on a plain dark background" in sp.build_prompt({**THING, "setting": ""}, "card")
        assert ", in a kitchen." in sp.build_prompt({**THING, "setting": "a kitchen"}, "card")
        assert ", on a pier." in sp.build_prompt({**THING, "setting": "on a pier"}, "card")


class TestLayoutAndFrame:
    def test_hero_is_a_vertical_scene_with_depth_card_is_wide_and_centred(self):
        hero = sp.build_prompt(THING, "hero")
        card = sp.build_prompt(THING, "card")
        assert "vertical full-screen scene with a close foreground" in hero and "depth" in hero
        assert "horizontal frame, the subject large and centred" in card and "vertical" not in card

    @pytest.mark.parametrize("shot,words", [("wide", "Wide shot, the whole setting in view"),
                                            ("medium", "Medium shot from a few steps away"),
                                            ("close", "Close-up of the subject"),
                                            ("macro", "Macro close-up of the finest detail")])
    def test_shot_words(self, shot, words):
        assert words in sp.build_prompt({**THING, "shot": shot}, "card")

    def test_people_line_is_positive(self):
        assert "Only a pair of hands enters the frame." in sp.build_prompt({**THING, "people": "hands"}, "card")
        assert "One anonymous person" in sp.build_prompt({**THING, "people": "one"}, "card")
        assert "A small group of anonymous strangers" in sp.build_prompt({**THING, "people": "group"}, "card")
        none = sp.build_prompt({**THING, "people": "none"}, "card")
        assert "person" not in none and "hands" not in none and "people" not in none

    def test_nobody_in_a_scene_is_said_in_the_positive_right_after_the_subject_sentence(self):
        # Z-Image adds a person to "a clinical room with a reclined chair" otherwise
        spec = {**SCENE, "subject": "reclined chair", "count": "1", "state": "facing a window",
                "setting": "a clinical room", "details": "a white wall, a low lamp", "people": "none"}
        p = sp.build_prompt(spec, "hero")
        assert ("in a clinical room. The place is empty and still, deserted. Visible details: a white wall, a low lamp."
                in p), p
        assert p.index("The place is empty and still, deserted.") < p.index("Visible details")
        assert not NEG.search(p) and sp.MIN_WORDS <= len(p.split()) <= sp.MAX_WORDS
        # a scene that holds people says it differently, and a scene on a plain setting is just as empty
        assert "deserted" not in sp.build_prompt({**spec, "people": "group"}, "hero")
        assert "The place is empty and still, deserted." in sp.build_prompt({**spec, "setting": "plain"}, "hero")

    def test_a_thing_in_a_named_setting_has_a_deserted_setting_a_plain_one_does_not(self):
        named = sp.build_prompt({**THING, "setting": "a kitchen"}, "card")
        assert ", in a kitchen. The setting is deserted. Visible details:" in named, named
        assert not NEG.search(named) and sp.MIN_WORDS <= len(named.split()) <= sp.MAX_WORDS
        for setting in ("plain", "", "Plain"):
            assert "deserted" not in sp.build_prompt({**THING, "setting": setting}, "card"), setting
        assert "deserted" not in sp.build_prompt({**THING, "setting": "a kitchen", "people": "hands"}, "card")
        assert "deserted" not in sp.build_prompt({**THING, "setting": "a kitchen", "people": "one"}, "card")

    def test_the_empty_line_is_for_a_scene_or_a_thing_only_and_stays_in_the_caps(self):
        for spec in (VISION, INSTRUMENT, PAIR):
            assert "deserted" not in sp.build_prompt({**spec, "setting": "a kitchen", "people": "none"}, "card")
        assert "deserted" not in sp.build_prompt({**BODY, "setting": "a kitchen"}, "card", DRAW)
        long = {**TestEverySpec.LONG, "kind": "scene", "people": "none", "count": "1", "mood": mood()}
        for layout in ("hero", "card"):
            p = sp.build_prompt(long, layout)
            assert "deserted" in p and sp.MIN_WORDS <= len(p.split()) <= sp.MAX_WORDS, p
        empty = {**SCENE, "people": "none"}
        assert sp.build_prompt(empty, "hero") == sp.build_prompt(dict(empty), "hero")      # deterministic

    def test_only_a_thing_or_a_scene_holds_people(self):
        for spec in (VISION, INSTRUMENT, BODY, PAIR):
            p = sp.build_prompt({**spec, "people": "one"}, "card", DRAW).replace(DRAW, "")
            assert "person" not in p and "hands" not in p

    def test_size_for(self):
        assert sp.size_for("hero") == (864, 1536)
        assert sp.size_for("card") == (1280, 720)
        assert sp.size_for("anything else") == (864, 1536)


class TestLight:
    def test_light_and_colours_stay_within_25_words_and_hold_no_emotional_adjective(self):
        loud = mood(valence="grim", intensity="extreme", colours_said="dark ominous red, sombre grey, uneasy tense "
                    "black, eerie green, cold steel blue, dull brown, bright orange", true_colours="red, grey")
        for spec in (THING, SCENE, VISION, INSTRUMENT, BODY):
            look = sp._look({**spec, "mood": loud}, sp.LIGHT_CAP)
            assert sp._wc(look) <= sp.LIGHT_CAP, look
            assert not re.search(r"ominous|sombre|uneasy|tense|eerie|grim|overwhelming", look, re.I), look
            p = sp.build_prompt({**spec, "mood": loud}, "card", DRAW)
            assert look in p

    def test_said_colours_lead_the_palette(self):
        m = mood(colours_said="bright orange and black", true_colours="orange and black stripes")
        p = sp.build_prompt({**THING, "mood": m}, "card")
        assert "Colours: bright orange and black, orange and black stripes." in p
        m = mood(colours_said="bright orange and black", true_colours="orange")
        assert "Colours: bright orange and black." in sp.build_prompt({**THING, "mood": m}, "card")   # said covers true

    def test_light_follows_key_of(self):
        low = sp.build_prompt({**THING, "mood": mood(valence="grim", intensity="charged")}, "card")
        high = sp.build_prompt({**THING, "mood": mood(valence="elated", intensity="still")}, "card")
        assert "Low-key light" in low and "hard directional light" in low
        assert "Bright high-key light" in high and "soft, diffused light" in high

    def test_grave_light_is_gentle_and_never_low_key(self):
        p = sp.build_prompt({**THING, "mood": mood(gravity="grave", valence="grim", intensity="extreme")}, "card")
        assert "soft natural daylight" in p and "Low-key" not in p and "dignity" not in p

    def test_restrained_illness_has_muted_colours(self):
        p = sp.build_prompt({**THING, "mood": mood(gravity="real", valence="grim", true_colours="grey skin")}, "card")
        assert "Colours: grey skin, muted colours." in p

    def test_an_instrument_has_no_directional_light(self):
        p = sp.build_prompt(INSTRUMENT, "card")
        assert "directional" not in p and "Even illumination" in p

    GIVEN = "soft window daylight from the left, late afternoon"

    @pytest.mark.parametrize("name", list(SIX))
    def test_the_art_directors_light_takes_the_place_of_the_moods(self, name):
        # v21: spec["light"] holds the art director's concrete light words (time of day, direction, source); the
        # mood's key light and direction are not used, the mood's colours still follow
        spec, layout, drawing = SIX[name]
        by_mood = sp.build_prompt(spec, layout, drawing)
        p = sp.build_prompt({**spec, "light": self.GIVEN}, layout, drawing)
        assert "Soft window daylight from the left, late afternoon." in p
        for lead in (*sp._KEY.values(), *sp._KEY_INSTRUMENT.values()):
            assert lead.lower() not in p.lower(), lead
        assert "directional" not in p and "natural daylight" not in p
        # nothing else changes: the same prompt, its light block replaced
        mood_look = sp._look(spec, sp.LIGHT_CAP)
        assert mood_look in by_mood
        assert p == by_mood.replace(mood_look, sp._look({**spec, "light": self.GIVEN}, sp.LIGHT_CAP))
        body = p.replace(drawing, "", 1) if drawing else p
        assert sp.MIN_WORDS <= len(body.split()) <= sp.MAX_WORDS and not NEG.search(body)
        if spec["mood"].get("true_colours"):
            assert "Colours: " + spec["mood"]["true_colours"].split(",")[0] in p

    def test_the_art_directors_light_is_capitalised_and_loses_its_emotion_words(self):
        p = sp.build_prompt({**THING, "light": "ominous low sun from the right, eerie haze over the table"}, "card")
        assert "Low sun from the right, haze over the table." in p
        assert not re.search(r"ominous|eerie", p, re.I)
        # a grave mood keeps its dignity by the words the art director gives, never by the mood's gentle daylight
        grave = sp.build_prompt({**THING, "mood": mood(gravity="grave", valence="grim", intensity="extreme"),
                                 "light": "flat grey overcast morning light"}, "card")
        assert "Flat grey overcast morning light." in grave and "natural daylight" not in grave and "Low-key" not in grave

    def test_the_art_directors_light_is_cleaned_like_every_free_text_field(self):
        look = sp._look({**THING, "light": "a low lamp on the left, no shadows, 85 mm lens glow, a warm wall"},
                         sp.LIGHT_CAP)
        assert look.startswith("A low lamp on the left, a warm wall.") and not NEG.search(look) and "85" not in look
        long = " ".join(["lamp"] * 20)
        assert len(sp._look({**THING, "light": long}, sp.LIGHT_CAP).split(" Colours:")[0].split()) == 12

    @pytest.mark.parametrize("light", ["", "   ", None, "no shadows", "ominous, eerie", 0])
    def test_no_usable_art_directors_light_leaves_the_moods(self, light):
        # nothing, or only negation and emotion words: the mood's key light and direction as before
        assert sp.build_prompt({**THING, "light": light}, "card") == sp.build_prompt(THING, "card")
        assert "Balanced light, a clear key light with soft shadows; soft directional light." in sp.build_prompt(
            {**THING, "light": light}, "card")

    def test_the_light_does_not_touch_the_judges_side(self):
        spec = {**THING, "light": self.GIVEN}
        assert sp.questions(spec) == sp.questions(THING) and sp.judge_line(spec) == sp.judge_line(THING)
        before = repr(spec)
        sp.build_prompt(spec, "card")
        assert repr(spec) == before


class TestCleaning:
    def test_a_measure_in_the_details_makes_no_count_sentence(self):
        for details in ("a stone tower 3 metres tall, a wide stair", "shot at 85 mm, a long shadow",
                        "a 85 mm brass tube, a dial", "a ledge about 3 metres away, two windows"):
            p = sp.build_prompt({**SCENE, "details": details}, "hero")
            assert not re.search(r"\b(?:3|85|mm|metres?)\b", p), p
            assert not re.search(r"exactly|show (?:two|three|four)|panels?|large group|easy to count", p, re.I), p
        p = sp.build_prompt({**THING, "subject": "tower", "details": "3 metres tall, 85 mm"}, "card")
        assert "three" not in p.lower() and "Visible details" not in p      # nothing is left of those details

    def test_the_guard_words_that_made_counts_are_never_added(self):
        for words in ("a phone on a table", "three screens", "a crowd of 85 people", "4 posters, a sign"):
            p = sp.build_prompt({**SCENE, "details": words}, "hero")
            assert not re.search(r"easy to count|exactly|plain colour, soft light|abstract shapes|one large group", p)

    def test_negation_in_the_editors_words_is_dropped_by_clause(self):
        spec = {**THING, "state": "resting, not moving", "setting": "a kitchen without people",
                "details": "a glossy skin, no stem, nothing else, a green leaf, isn't bruised"}
        p = sp.build_prompt(spec, "card")
        assert not NEG.search(p), p
        assert "a glossy skin, a green leaf" in p and "resting," in p and "on a plain dark background" in p

    def test_camera_and_filler_words_are_dropped(self):
        spec = {**THING, "details": "shot on a Canon, 8k masterpiece, bokeh, a glossy skin, f/1.8, a green stem"}
        p = sp.build_prompt(spec, "card")
        assert not CAMERA.search(p) and "a glossy skin, a green stem" in p

    def test_an_empty_subject_falls_back_to_the_spoken_words(self):
        p = sp.build_prompt({**THING, "subject": "no apple", "subject_words": "apple"}, "card")
        assert "showing a single apple" in p and not NEG.search(p)
        assert "the subject" in sp.build_prompt({"kind": "thing"}, "card")

    def test_a_bare_or_odd_spec_still_gives_a_prompt(self):
        for odd in ({}, None, {"kind": "nonsense", "count": "7", "shot": "huge", "people": "crowd", "mood": "x"}):
            p = sp.build_prompt(odd, "card")
            assert sp.MIN_WORDS <= len(p.split()) <= sp.MAX_WORDS and not NEG.search(p)
            assert sp.questions(odd) and sp.judge_line(odd)


class TestEverySpec:
    """A grid over the spec's values: whatever the editor picks, the caps and the no-negation rule hold."""
    LONG = {"subject": "old brass compass with a cracked glass lid", "state": "lying open on a rough oak table top",
            "setting": "a cluttered ship cabin lit by a single low lantern",
            "details": "a green patina on the case, a bent needle, worn engraved letters along the rim, "
                       "a frayed leather strap",
            "instrument": "scanning electron microscope", "subject_b": "modern digital compass with a metal frame"}

    @pytest.mark.parametrize("long", [False, True])
    def test_caps_hold(self, long):
        moods = [mood(), mood(era="early", valence="grim", intensity="extreme", gravity="grave"),
                 mood(era="recent", valence="elated", intensity="charged", colours_said="warm amber and deep teal "
                      "water under pale sky", true_colours="brass, oak brown, glass green, black iron, white paper")]
        for kind, layout, shot, count, people, m in itertools.product(
                sp.KINDS, ("hero", "card"), ("wide", "medium", "close", "macro"), ("1", "2", "3", "4", "many"),
                ("none", "hands", "one", "group"), moods):
            spec = {"kind": kind, "subject": "glass of water", "state": "standing", "setting": "plain",
                    "details": "clear water", "count": count, "shot": shot, "people": people, "mood": m,
                    "instrument": "microscope", "subject_b": "a stone"}
            if long:
                spec.update(self.LONG)
            p = sp.build_prompt(spec, layout, DRAW)
            body = p.replace(DRAW, "", 1) if kind == "body_inside" else p
            assert sp.MIN_WORDS <= len(body.split()) <= sp.MAX_WORDS, (spec, len(body.split()), body)
            assert not NEG.search(body), body
            if kind != "body_inside":
                assert "glass" in " ".join(body.split()[:25]) or long, body


class TestJudgeAndQuestions:
    def ids(self, spec):
        return [q["id"] for q in sp.questions(spec)]

    def test_judge_line(self):
        assert sp.judge_line(THING) == "A single red apple, resting on a wooden table, on a plain dark background."
        assert sp.judge_line(PAIR) == "Two images side by side: a chimpanzee skull and a human skull."
        assert sp.judge_line(VISION).startswith("What a person sees: a single tunnel of white light")
        assert sp.judge_line(INSTRUMENT).startswith("Fluorescence microscope image showing a single neuron")
        assert sp.judge_line(BODY).startswith("A drawing of a single human brain seen from above")
        assert sp.judge_line({**SCENE, "details": "not here"}).count(".") == 1

    def test_questions_of_a_thing(self):
        qs = sp.questions(THING)
        assert [q["id"] for q in qs] == ["q_subject", "q_count", "q_people", "q_text", "q_medium", "q_unsafe",
                                         "q_body_photo"]
        by = {q["id"]: q for q in qs}
        assert by["q_subject"] == {"id": "q_subject", "q": "Is the main subject red apple?", "expect": "yes"}
        assert by["q_count"]["q"] == "How many red apples are visible?" and by["q_count"]["expect"] == 1
        assert by["q_people"]["expect"] == 0 and by["q_text"]["expect"] == "no"
        assert by["q_medium"]["expect"] == "photograph"
        assert by["q_unsafe"]["expect"] == "no" and "syringe" in by["q_unsafe"]["q"] and "noose" in by["q_unsafe"]["q"]
        assert by["q_body_photo"] == {"id": "q_body_photo", "expect": "no", "q": (
            "Is it a PHOTOGRAPH of a surgical operation or of the inside of a body (an organ, a brain, tissue)?")}
        assert all(set(q) == {"id", "q", "expect"} for q in qs)

    def test_q_count_only_for_one_to_four(self):
        for c in ("1", "2", "3", "4"):
            q = {x["id"]: x for x in sp.questions({**THING, "count": c})}
            assert q["q_count"]["expect"] == int(c)
        assert "q_count" not in self.ids({**THING, "count": "many"})
        assert "q_count" in self.ids({**THING, "count": "weird"})            # an unknown count is one

    @pytest.mark.parametrize("people,expect", [("none", 0), ("hands", "no"), ("one", 1), ("group", 2)])
    def test_q_people(self, people, expect):
        q = {x["id"]: x for x in sp.questions({**THING, "people": people})}
        assert q["q_people"]["expect"] == expect

    def test_q_people_of_hands_asks_what_is_visible_apart_from_hands_and_arms(self):
        q = {x["id"]: x for x in sp.questions({**THING, "people": "hands"})}
        assert q["q_people"] == {"id": "q_people", "expect": "no",
                                 "q": "Apart from hands and arms, is any part of a person visible?"}
        other = {x["id"]: x for x in sp.questions({**THING, "people": "one"})}
        assert "Apart from" not in other["q_people"]["q"]

    def test_q_people_is_zero_when_the_kind_never_holds_people(self):
        q = {x["id"]: x for x in sp.questions({**VISION, "people": "group"})}
        assert q["q_people"]["expect"] == 0

    def test_no_q_people_where_the_body_is_the_subject_nor_for_a_pair(self):
        # an anatomical arm or a drawn brain was answered "1 body part" and dropped as "wrong people"; a pair's halves
        # each have their own (a drawn synapse beside a clenched fist was dropped as "wrong people")
        for spec in (BODY, INSTRUMENT, PAIR):
            for people in ("none", "hands", "one", "group"):
                assert "q_people" not in self.ids({**spec, "people": people}), (spec["kind"], people)
        for spec in (THING, SCENE, VISION):
            assert "q_people" in self.ids(spec), spec["kind"]
        assert self.ids(BODY) == ["q_subject", "q_count", "q_text", "q_medium", "q_unsafe", "q_body_photo"]

    def test_no_q_count_for_a_pair(self):
        # the galaxy / neuron split image was asked how many "galaxy image beside neural cell images" and dropped 3 times
        for count in ("1", "2", "3", "4", "many"):
            assert "q_count" not in self.ids({**PAIR, "count": count}), count
        assert self.ids(PAIR) == ["q_subject", "q_text", "q_unsafe", "q_body_photo", "q_pair"]
        for spec in (THING, SCENE, VISION, INSTRUMENT, BODY):
            assert "q_count" in self.ids({**spec, "count": "2"}), spec["kind"]

    def test_no_q_medium_for_a_pair(self):
        # each half has its own medium (a drawn neuron beside a telescope's frame): asked one medium for the whole
        # image, the checker dropped the pair
        for count in ("1", "2", "many"):
            assert "q_medium" not in self.ids({**PAIR, "count": count}), count
        assert "q_medium" not in self.ids({**PAIR, "subject": "eye mask, earbuds"})
        for spec in (THING, SCENE, INSTRUMENT, BODY):
            assert "q_medium" in self.ids(spec), spec["kind"]
        assert self.ids(PAIR) == ["q_subject", "q_text", "q_unsafe", "q_body_photo", "q_pair"]
        # nor for a vision: what a person perceives reads as "digital art" (the DMT trip was dropped as the wrong medium)
        assert "q_medium" not in self.ids(VISION)

    def test_q_medium_by_kind(self):
        for spec, expect in ((THING, "photograph"), (SCENE, "photograph"),
                             (INSTRUMENT, "scientific image"), (BODY, "drawing")):
            q = {x["id"]: x for x in sp.questions(spec)}
            assert q["q_medium"]["expect"] == expect, spec["kind"]

    def test_q_pair_only_for_a_pair(self):
        for spec in (THING, SCENE, VISION, INSTRUMENT, BODY):
            assert "q_pair" not in self.ids(spec)
        q = {x["id"]: x for x in sp.questions(PAIR)}
        assert q["q_pair"] == {"id": "q_pair", "q": "Are there two images, a chimpanzee skull and a human skull?",
                               "expect": "yes"}
        assert q["q_subject"]["q"] == "Is one of the two main subjects chimpanzee skull?"

    def test_questions_use_the_cleaned_subject(self):
        q = {x["id"]: x for x in sp.questions({**THING, "subject": "tower 3 metres tall"})}
        assert q["q_subject"]["q"] == "Is the main subject tower?"

    # a coat on a wall hook was answered "hanging" and dropped as unsafe: the question says what is NOT meant
    HANGING = ("a garment or an object hanging from a rope, a cord or a thread (a garment on a wall hook, a hanger or "
               "a peg is NOT that), a belt, a strap, a tie, a scarf, a cord or a tube hanging, draped or looped")
    PILLS = "pills or a medicine bottle"

    def unsafe(self, spec):
        return {x["id"]: x for x in sp.questions(spec)}["q_unsafe"]["q"]

    def test_q_unsafe_of_an_ordinary_picture_names_neither_pills_nor_what_hangs(self):
        q = self.unsafe(THING)
        assert q.startswith("Does it show blood, a wound, a weapon, a drug being taken or prepared (a syringe, powder, "
                            "a pipe), a grave, a coffin") and q.endswith("a noose or a lifeless body?")
        assert self.PILLS not in q and self.HANGING not in q and "hang" not in q and q.count("?") == 1

    @pytest.mark.parametrize("name", list(SIX))
    def test_q_unsafe_names_what_hangs_near_a_death(self, name):
        # the engine drew a whole dobok hung from a thread for a sentence about a death: the checker is asked about it
        spec = SIX[name][0]
        plain, near = self.unsafe(spec), self.unsafe({**spec, "death_near": True})
        assert self.HANGING not in plain and self.PILLS not in plain
        assert self.HANGING in near and self.PILLS in near
        # nothing else of the question changes: the two phrases join its list, before the grave
        assert near.replace(f"{self.PILLS}, {self.HANGING}, ", "") == plain
        assert near.index(self.PILLS) < near.index(self.HANGING) < near.index("a grave")

    @pytest.mark.parametrize("name", list(SIX))
    def test_q_unsafe_names_what_hangs_in_a_grave_clip(self, name):
        spec = SIX[name][0]
        grave = {**spec, "mood": {**spec["mood"], "gravity": "grave"}}
        assert self.HANGING in self.unsafe(grave)
        assert self.unsafe(grave) == self.unsafe({**spec, "death_near": True})        # the same question as near a death
        assert self.HANGING in self.unsafe({**spec, "mood": {"gravity": "grave"}})    # a mood of that one axis is enough
        both = self.unsafe({**grave, "death_near": True})
        assert both == self.unsafe(grave) and both.count(self.HANGING) == 1

    @pytest.mark.parametrize("spec", [
        {**THING, "death_near": False}, {**THING, "death_near": None}, {**THING, "mood": mood(gravity="none")},
        {**THING, "mood": mood(gravity="real")},               # an illness or a loss in passing: not a death
        {**THING, "mood": {"gravity": "real"}}, {**THING, "mood": {}}, {**THING, "mood": None}, {**THING, "mood": "grave"}])
    def test_q_unsafe_does_not_name_what_hangs_otherwise(self, spec):
        q = self.unsafe(spec)
        assert self.HANGING not in q and "hanging" not in q
        assert q == self.unsafe(THING)

    def test_the_rest_of_the_questions_do_not_depend_on_the_death(self):
        for spec in (THING, SCENE, BODY, PAIR):
            plain = [q for q in sp.questions(spec) if q["id"] != "q_unsafe"]
            near = [q for q in sp.questions({**spec, "death_near": True}) if q["id"] != "q_unsafe"]
            grave = [q for q in sp.questions({**spec, "mood": {**spec["mood"], "gravity": "grave"}})
                     if q["id"] != "q_unsafe"]
            assert plain == near == grave, spec["kind"]
        assert next(q for q in sp.questions({**THING, "death_near": True}) if q["id"] == "q_unsafe")["expect"] == "no"


class TestCompoundSubject:
    """A subject that lists several things ("eye mask, earbuds, blood pressure cuff": a comma or the word "and") gets no
    count word and no plural (the subject is used as it is), is asked "Does the picture show ...?" and is never counted:
    the count the editor gave was the length of the list."""
    LISTED = "eye mask, earbuds, blood pressure cuff"
    COUNT_WORD = r"(?:a single|two|three|four|many) "

    def ids(self, spec):
        return [q["id"] for q in sp.questions(spec)]

    @pytest.mark.parametrize("subject", ["eye mask, earbuds, blood pressure cuff", "eye mask, earbuds", "pen and notebook",
                                         "salt and pepper"])
    @pytest.mark.parametrize("count", ["1", "2", "3", "4", "many"])
    def test_no_count_word_and_no_plural_the_subject_as_it_is(self, subject, count):
        p = sp.build_prompt({**THING, "subject": subject, "count": count}, "card")
        assert f"showing {subject}, resting on a wooden table, on a plain dark background." in p
        assert not re.search(r"showing " + self.COUNT_WORD, p) and f"{subject}s" not in p
        assert sp.judge_line({**THING, "subject": subject, "count": count}) == (
            f"{subject[0].upper()}{subject[1:]}, resting on a wooden table, on a plain dark background.")

    @pytest.mark.parametrize("name", [n for n in SIX if n != "pair"])
    def test_every_kind_uses_the_subject_as_it_is(self, name):
        spec, layout, drawing = SIX[name]
        p = sp.build_prompt({**spec, "subject": self.LISTED, "count": "3"}, layout, drawing)
        assert f"{self.LISTED}, " in p
        assert not re.search(self.COUNT_WORD + re.escape(self.LISTED), p) and "cuffs" not in p
        body = p.replace(drawing, "", 1) if drawing else p
        assert sp.MIN_WORDS <= len(body.split()) <= sp.MAX_WORDS and not NEG.search(body)

    def test_a_pair_keeps_its_own_phrase(self):
        p = sp.build_prompt({**PAIR, "subject": self.LISTED, "subject_b": "human skull"}, "card")
        assert "On the left, an eye mask, earbuds, blood pressure cuff; on the right, a human skull." in p

    def test_the_question_is_whether_the_picture_shows_it_and_it_is_never_counted(self):
        for count in ("1", "2", "3", "4", "many"):
            qs = sp.questions({**THING, "subject": self.LISTED, "count": count})
            assert [q["id"] for q in qs] == ["q_subject", "q_people", "q_text", "q_medium", "q_unsafe", "q_body_photo"]
            assert qs[0] == {"id": "q_subject", "q": f"Does the picture show {self.LISTED}?", "expect": "yes"}
        for spec in (SCENE, VISION, INSTRUMENT, BODY):
            qs = {q["id"]: q for q in sp.questions({**spec, "subject": self.LISTED, "count": "2"})}
            assert qs["q_subject"] == {"id": "q_subject", "q": f"Does the picture show {self.LISTED}?", "expect": "yes"}
            assert "q_count" not in qs, spec["kind"]
        qs = {q["id"]: q for q in sp.questions({**THING, "subject": "pen and notebook", "count": "2"})}
        assert qs["q_subject"]["q"] == "Does the picture show pen and notebook?" and "q_count" not in qs

    def test_a_pair_is_asked_in_its_own_words_whatever_its_subject(self):
        qs = {q["id"]: q for q in sp.questions({**PAIR, "subject": "eye mask, earbuds"})}
        assert qs["q_subject"]["q"] == "Is one of the two main subjects eye mask, earbuds?"

    def test_a_word_that_only_holds_and_is_not_a_list(self):
        for plain in ("red apple", "sand dune", "brand new bicycle", "android phone", "", None):
            assert not sp._compound(plain), plain
        for listed in ("eye mask, earbuds", "pen and notebook", "Pen AND notebook", "salt and pepper"):
            assert sp._compound(listed), listed
        spec = {**THING, "subject": "sand dune", "count": "2"}
        assert "showing two sand dunes," in sp.build_prompt(spec, "card")           # counted and made plural as before
        qs = sp.questions(spec)
        assert [q["id"] for q in qs][:2] == ["q_subject", "q_count"]
        assert qs[0]["q"] == "Is the main subject sand dune?" and qs[1]["q"] == "How many sand dunes are visible?"
