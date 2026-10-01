"""The thing named, first (1-oct-2026 evening, audit-broll-sens; it replaces the visual argument of chantier K):
every image shows something the speaker names or tells, an allegory only when he says it himself, no image where
nothing is named, no hero when the clip has no real scene. The specificity test stays. No model is called."""
import pytest

import ai_brain
import broll


def _words(text, step=0.42, dur=0.4):
    out, t = [], 0.0
    for w in text.split():
        out.append({"text": w, "start": round(t, 2), "end": round(t + dur, 2)})
        t += step
    return out


TEXT = ("Well you know this is the setup for the story. In 1998 the soldiers were given two gallons of water, "
        "and then they marched all night long. It was brutal. Nobody spoke for hours but the drill went on and on "
        "until sunrise came and the camp woke up again and the sergeant finally smiled at them all. They never "
        "forgot that long night in the desert and the lesson it taught them about discipline.")


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(broll, "NOTION_DIR", str(tmp_path / "notions"))
    monkeypatch.setattr(broll, "HERO_TAKES", 1)
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")


class TestTheEditor:
    def _plan(self, monkeypatch, data=None, **kw):
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt, schema=schema) or (data or {"moments": []}))
        moments = broll.plan_with_claude({}, _words(TEXT), 4, [], hero=True, **kw)
        return seen, moments

    def test_the_thing_named_comes_before_everything_else(self, monkeypatch):
        seen, _m = self._plan(monkeypatch)
        p = seen["prompt"]
        assert "THE THING NAMED, FIRST. Every image shows something the speaker NAMES or TELLS" in p
        assert "allowed ONLY when the speaker says that image himself" in p and "Zero images beats one allegory" in p
        assert p.index("THE THING NAMED, FIRST") < p.index('Also write "style_sheet"') < p.index("NEVER THE AI CLICHÉ")
        assert "At most 4 images; one or two when the clip\nnames little, none when it names nothing" in p
        assert "Aim for" not in p and "visual_argument" not in p and "PROVES" not in p
        assert '"idea": the link the viewer makes between the picture and the words' in p
        assert "SPECIFICITY TEST: if the same picture would do for any other clip about the same noun" in p
        assert p.index("NEVER THE AI CLICHÉ") < p.index("SPECIFICITY TEST") < p.index("Never: something already visible")
        assert "visual_argument" not in seen["schema"]["properties"]

    def test_the_hero_is_a_real_scene_or_nothing(self, monkeypatch):
        seen, _m = self._plan(monkeypatch)
        p = seen["prompt"]
        assert "one image of the set MAY be shown FULL SCREEN" in p and "never an allegory" in p
        assert "When the clip has no such scene,\nmark no hero" in p
        assert broll.HERO_MIN_SCORE == 2.5

    def test_the_pace_wants_things_not_ideas(self):
        assert "a picture of an idea is not" in broll.DENSITY_MIXED["normal"]["pace"]
        for v in broll.DENSITY_MIXED.values():
            assert "names or tells" in v["pace"] and "merely repeats the noun" not in v["pace"]

    def test_no_argument_lands_on_the_moments(self, monkeypatch):
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"thesis": "T", "visual_argument": "ignored now",
                "moments": [{"anchor": "soldiers", "time": words[idx["soldiers"]]["start"], "image_prompt": "x"}]}
        _s, moments = self._plan(monkeypatch, data)
        assert len(moments) == 1 and "argument" not in moments[0] and moments[0]["thesis"] == "T"


class TestTheCliches:
    def test_the_prestige_allegories_are_cliches_too(self):
        joined = "; ".join(broll.CLICHES)
        for c in ("lone small figure facing a vast landscape", "open empty palms", "hand reaching toward a light",
                  "doorway or threshold glowing", "running through fingers", "seen from behind at a window",
                  "empty corridor", "hourglass"):
            assert c in joined
        assert "what a clever editor reaches for when nothing concrete was said" in broll.CLICHE_RULE

    def test_the_bible_asks_for_things_not_allegories(self):
        assert ai_brain.BIBLE_RULES.count("never an allegory") == 2
        assert "doorway for a threshold" in ai_brain.BIBLE_RULES


class TestTheArtDirector:
    def test_the_director_hears_the_thesis_and_shoots_the_thing(self):
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "hero": True, "thesis": "T"}]
        text = broll._art_prompt(ms, {"video_title_for_youtube_short": "Title"}, "h")
        assert 'THE CLIP: title "Title"; thesis: T\n' in text and "visual argument" not in text
        assert "one unforgettable frame of the thing or the scene the editor chose, as it really" in text


class TestTheReviewer:
    def test_the_reviewer_rates_the_sense_with_the_sound_off_test(self):
        text = broll.REVIEW_PROMPT.format(frame=broll._review_frame([{"layout": "card"}]), items="- x")
        assert '"score" (THE SENSE, 1-5)' in text and "SOUND-OFF TEST" in text
        assert "SPECIFICITY TEST" not in text          # the editor's test, not a veto of the review any more
