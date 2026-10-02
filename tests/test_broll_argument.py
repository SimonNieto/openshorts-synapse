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
        assert p.index("THE THING NAMED, FIRST") < p.index('THE LOOK of every picture comes from its "mood"') < p.index("NO SYMBOL FOR AN IDEA")
        assert "At most 4 images." in p and "none when it names nothing" in p
        assert "Aim for" not in p and "visual_argument" not in p and "PROVES" not in p
        assert '"idea": the link the viewer makes between the picture and the words' in p
        # the specificity test lives inside the context rule now, not as a rule of its own
        assert "a picture that would do for any\nother clip about the same noun is not the picture" in p
        assert "SPECIFICITY TEST" not in p and "Nothing else (no neon" not in p
        assert "visual_argument" not in seen["schema"]["properties"]
        assert seen["schema"]["properties"]["moments"]["items"]["properties"]["style"]["enum"] == ["photo"]

    def test_every_picture_answers_the_mood_questions(self, monkeypatch):
        """B-roll « ambiance » (2-oct-2026): anchored levels, an enum each, required on every moment; the clip's
        sheet is only its cast; the historical layouts keep their style sheet and no mood."""
        seen, _m = self._plan(monkeypatch)
        p, item = seen["prompt"], seen["schema"]["properties"]["moments"]["items"]
        assert item["properties"]["mood"] == broll.visual_mood.SCHEMA and "mood" in item["required"]
        assert item["properties"]["mood"]["properties"]["valence"]["enum"] == ["grim", "uneasy", "neutral", "warm", "elated"]
        assert broll.visual_mood.MOOD_RULE in p and 'Write "style_sheet" only for "cast"' in p
        assert seen["schema"]["properties"]["style_sheet"]["properties"] == {"cast": {"type": "string"}}
        assert '"palette" (the 2-4 dominant colours)' not in p
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt, schema=schema) or {"moments": []})
        broll.plan_with_claude({}, _words(TEXT), 4, [], hero=False)
        assert "mood" not in seen["schema"]["properties"]["moments"]["items"]["properties"]
        assert 'Also write "style_sheet": ONE visual direction' in seen["prompt"] and '"valence"' not in seen["prompt"]

    def test_the_moods_are_parsed_and_logged(self, monkeypatch, capsys):
        words = _words(TEXT)
        anchor = next(w for w in words if len(w["text"]) > 4 and words.index(w) > 12)
        data = {"moments": [{"anchor": anchor["text"], "time": anchor["start"], "image_prompt": "x", "subject": "thing",
                             "mood": {"valence": "grim", "intensity": "charged", "visibility": "eye", "scale": "body",
                                      "era": "now", "distance": "lived", "gravity": "real", "cue": "it hurt"}}]}
        _seen, moments = self._plan(monkeypatch, data)
        assert moments and moments[0]["mood"]["valence"] == "grim" and moments[0]["mood"]["defaulted"] == []
        out = capsys.readouterr().out
        assert "🎚️ Moods: thing: grim · charged · lived · real («it hurt»)" in out

    def test_the_hero_is_a_real_scene_or_nothing(self, monkeypatch):
        seen, _m = self._plan(monkeypatch)
        p = seen["prompt"]
        assert "one image of the set MAY be shown FULL SCREEN" in p and "A hero is a real scene the speaker names" in p
        assert "When the clip has no such scene, mark no hero" in p and "never on the punchline" not in p
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
        assert "the allegories a clever editor reaches for when nothing concrete was said" in broll.CLICHE_RULE

    def test_the_bible_asks_for_things_not_allegories(self):
        assert ai_brain.BIBLE_RULES.count("never an allegory") == 2
        assert "doorway for a threshold" in ai_brain.BIBLE_RULES


class TestTheArtDirector:
    def test_the_director_hears_the_thesis_and_shoots_the_thing(self):
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "hero": True, "thesis": "T"}]
        text = broll._art_prompt(ms, {"video_title_for_youtube_short": "Title"})
        assert 'THE CLIP: title "Title"; thesis: T\n' in text and "visual argument" not in text
        assert "one unforgettable frame of the thing or the scene the editor chose, as it really" in text


class TestTheReviewer:
    def test_the_reviewer_rates_the_sense_with_the_sound_off_test(self):
        text = broll.REVIEW_PROMPT.format(frame=broll._review_frame([{"layout": "card"}]), items="- x")
        assert '"score" (THE SENSE, 1-5)' in text and "SOUND-OFF TEST" in text
        assert "SPECIFICITY TEST" not in text          # the editor's test, not a veto of the review any more
