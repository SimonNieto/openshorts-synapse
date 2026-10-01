"""The episode's visual bible (B-roll v2, chantier J): one read per episode gives the world, the look, the
motifs, the pictures to avoid and a hero idea per story; every clip's editor and art director read it, and the
clip's style sheet wears the episode's look. No model is called."""
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
BRIEF = {"speakers": [{"name": "Joe", "role": "host"}], "topic": "Night marches and discipline", "themes": ["discipline"],
         "tone": "calm", "glossary": [{"term": "Drill", "meaning": "m", "visual": "a whistle"}],
         "stories": [{"summary": "The 1998 march", "details": "two gallons of water", "quote": "two gallons of water", "t": 5.0}]}
BIBLE_RAW = {"world": ["a desert camp at dawn, three canvas tents", "a dented steel canteen", "  "],
             "look": {"palette": "sand ochre on the ground, teal in the pre-dawn sky", "light": "first sun from the right, low",
                      "lens": "24 and 50 mm, waist height", "texture": "dust, worn cotton", "mood": "spent, resolute"},
             "motifs": ["the canteen (whenever water is said)", "the horizon line"], "avoid": ["a glowing brain", "a parade"],
             "heroes": [{"story": "The 1998 march", "picture": "A lone soldier on the cracked desert floor at dawn.", "why": "the ordeal at scale"},
                        {"story": "junk", "picture": ""}]}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(broll, "NOTION_DIR", str(tmp_path / "notions"))
    monkeypatch.setattr(broll, "HERO_TAKES", 1)   # the hero's takes have their own tests
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")


class TestTheBible:
    def test_one_read_of_the_brief_and_the_transcript(self, monkeypatch):
        seen = {}

        def fake_think(stage, prompt, schema, **kw):
            seen.update(kw, prompt=prompt, schema=schema)
            return BIBLE_RAW, "claude"

        monkeypatch.setattr(ai_brain, "think", fake_think)
        tr = {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in _words(TEXT)]}]}
        bible = ai_brain.episode_bible(BRIEF, tr)
        assert seen["route_key"] == "broll_art" and seen["effort"] == "high" and seen["schema"] is ai_brain.BIBLE_SCHEMA
        assert "TOPIC: Night marches and discipline" in seen["prompt"] and "- Drill: m -> a whistle" in seen["prompt"]
        assert "TRANSCRIPT ([mm:ss] markers)" in seen["prompt"] and "[00:00]" in seen["prompt"] and "soldiers" in seen["prompt"]
        assert bible["world"] == ["a desert camp at dawn, three canvas tents", "a dented steel canteen"]
        assert bible["look"]["palette"].startswith("sand ochre") and bible["motifs"][0].startswith("the canteen")
        assert bible["heroes"] == [{"story": "The 1998 march", "picture": "A lone soldier on the cracked desert floor at dawn.", "why": "the ordeal at scale"}]
        assert bible["by"] == "claude" and ai_brain.EPISODE_BIBLE is bible

    def test_nothing_without_a_brief_or_on_a_failure(self, monkeypatch):
        assert ai_brain.episode_bible(None) is None

        def boom(*a, **kw):
            raise RuntimeError("quota")

        monkeypatch.setattr(ai_brain, "think", boom)
        assert ai_brain.episode_bible(BRIEF) is None and ai_brain.EPISODE_BIBLE is None
        monkeypatch.setattr(ai_brain, "think", lambda *a, **kw: ({"world": []}, "claude"))
        assert ai_brain.episode_bible(BRIEF) is None

    def test_the_text_for_the_clips(self):
        assert ai_brain.bible_text(None) == "" and ai_brain.bible_text() == ""
        text = ai_brain.bible_text(ai_brain._clean_bible(BIBLE_RAW, "claude"))
        assert text.startswith("EPISODE VISUAL BIBLE")
        assert "WORLD: a desert camp at dawn, three canvas tents; a dented steel canteen" in text
        assert "LOOK: palette: sand ochre" in text and "MOTIFS: the canteen" in text and "AVOID: a glowing brain; a parade" in text
        assert "- The 1998 march: A lone soldier on the cracked desert floor at dawn. (the ordeal at scale)" in text
        assert "junk" not in text


class TestInTheEditor:
    def _plan(self, monkeypatch, data=None):
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt) or (data or {"moments": []}))
        moments = broll.plan_with_claude({}, _words(TEXT), 4, [], hero=True)
        return seen["prompt"], moments

    def test_the_editor_reads_the_bible_and_wears_its_look(self, monkeypatch):
        monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", ai_brain._clean_bible(BIBLE_RAW, "claude"))
        words = _words(TEXT)
        data = {"style_sheet": {"palette": "neon pink", "light": "flat", "era": "1998", "camera": "fisheye", "mood": "tense", "cast": "a tall sergeant"},
                "moments": [{"anchor": "soldiers", "time": words[11]["start"], "image_prompt": "x", "shot": "wide", "role": "example"}]}
        prompt, moments = self._plan(monkeypatch, data)
        head = "EPISODE VISUAL BIBLE (one read of the whole episode"
        assert head in prompt and "WORLD: a desert camp" in prompt and "HERO IDEAS" in prompt
        assert prompt.index("EPISODE BRIEF:") < prompt.index(head) < prompt.index("CLIP TITLE:")
        assert "its LOOK is the style_sheet of every clip" in prompt
        sheet = moments[0]["sheet"]
        assert sheet["palette"].startswith("sand ochre") and sheet["light"].startswith("first sun") and sheet["camera"] == "24 and 50 mm, waist height"
        assert sheet["era"] == "1998" and sheet["mood"] == "tense"

    def test_without_a_bible_nothing_changes(self, monkeypatch):
        words = _words(TEXT)
        data = {"style_sheet": {"palette": "neon pink", "light": "flat", "camera": "fisheye"},
                "moments": [{"anchor": "soldiers", "time": words[11]["start"], "image_prompt": "x"}]}
        prompt, moments = self._plan(monkeypatch, data)
        assert "EPISODE VISUAL BIBLE (one read" not in prompt and "WORLD:" not in prompt
        assert moments[0]["sheet"] == {"palette": "neon pink", "light": "flat", "camera": "fisheye"}
        assert broll._sheet_with_bible(None) is None

    def test_a_long_look_field_is_cut_after_a_clause_never_mid_word(self):
        text = "deep indigo in the windows, hot amber on the skin, surgical white on the bench, cool blue off the monitor, more"
        got = broll._short_field(text, 90)
        assert got == "deep indigo in the windows, hot amber on the skin, surgical white on the bench" and len(got) <= 90
        assert broll._short_field("short", 90) == "short"
        assert broll._short_field("a" * 50 + " word " + "b" * 60, 100).endswith("word")

    def test_the_mood_of_the_episode_fills_an_empty_one(self, monkeypatch):
        monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", ai_brain._clean_bible(BIBLE_RAW, "claude"))
        sheet = broll._sheet_with_bible({"era": "present day"})
        assert sheet["mood"] == "spent, resolute" and sheet["era"] == "present day" and "palette" in sheet


class TestInTheArtDirector:
    def test_the_director_reads_the_world_the_look_and_the_avoid_list(self, monkeypatch):
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "hero": True}]
        assert "EPISODE VISUAL BIBLE (one read" not in broll._art_prompt(ms, {}, "h")
        monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", ai_brain._clean_bible(BIBLE_RAW, "claude"))
        text = broll._art_prompt(ms, {}, "h", family="cinematic_photo")
        head = "EPISODE VISUAL BIBLE (one read"
        assert head in text and "AVOID: a glowing brain" in text and "MOTIFS:" in text
        assert text.index("THE STYLE FAMILY") < text.index(head) < text.index("THIS CLIP'S STYLE SHEET")
