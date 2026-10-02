"""Registers (1-oct-2026 evening): the bible writes, per episode, how what a camera cannot shoot is shown (a trip,
the cosmos, a notion); the editor names a register in "style"; the director paints the picture in it and writes a
judge line for every picture; the photo recipe (house look, family, grade, cliché list, photo look-grid) skips a
register picture; a manual redo keeps the register. No model is called."""
import pytest

import ai_brain
import broll


def _words(text, step=0.42, dur=0.4):
    out, t = [], 0.0
    for w in text.split():
        out.append({"text": w, "start": round(t, 2), "end": round(t + dur, 2)})
        t += step
    return out


TEXT = ("Well you know this is the setup for the story. When the DMT hit, these alien beings pinned me down and the "
        "room became a dome of jewelled tiles that breathed. And then I woke up and had a cup of coffee in the "
        "kitchen. Nobody spoke for hours but the drill went on and on until sunrise came and the camp woke up again "
        "and the sergeant finally smiled at them all that morning.")

VISION = ("Impossible interior space seen from inside a DMT trip: a breathing dome of jewelled tiles in saturated magenta, "
          "gold and electric green, tall translucent beings with no faces leaning in, geometry folding into itself, light "
          "coming from inside every surface, no horizon, no shadow, hyper-detailed, the scale of a cathedral felt from a bed.")
BIBLE_RAW = {"world": ["an IV pump with a digital readout", "a vial of DMT"], "mood": {"valence": "elated"},
             "motifs": ["the vial"], "avoid": ["a smoked DMT pipe"], "heroes": [{"story": "trip", "picture": "p"}],
             "registers": [
                 {"name": "Vision", "when": "what Chase saw and felt on DMT", "look": VISION,
                  "judge": "a cold viewer feels an overwhelming, specific other place, not a screensaver",
                  "cheap": "a kaleidoscope wallpaper or a cartoon alien"},
                 {"name": "photo", "when": "x", "look": "a " * 30},
                 {"name": "cosmos", "when": "the universe", "look": "Deep-field telescope image, " + "stars " * 20},
                 {"name": "short", "when": "x", "look": "too short"}]}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(broll, "NOTION_DIR", str(tmp_path / "notions"))
    monkeypatch.setattr(broll, "HERO_TAKES", 1)
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")


@pytest.fixture
def bible(monkeypatch):
    b = ai_brain._clean_bible(BIBLE_RAW, "claude")
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", b)
    return b


class TestTheBible:
    def test_the_rules_ask_for_registers_and_only_false_facts_to_avoid(self):
        assert "\"registers\": the episode's own way of showing each KIND of thing it talks about that a camera cannot shoot" in ai_brain.BIBLE_RULES
        assert "as strange, vast, exact or saturated as\n  the thing is and as it is told" in ai_brain.BIBLE_RULES
        assert "never a matter of taste or style" in ai_brain.BIBLE_RULES
        assert "registers" in ai_brain.BIBLE_SCHEMA["properties"] and "registers" not in ai_brain.BIBLE_SCHEMA["required"]

    def test_registers_are_cleaned(self, bible):
        names = [r["name"] for r in bible["registers"]]
        assert names == ["vision", "cosmos"]          # "photo" is reserved, "short" has no look
        v = bible["registers"][0]
        assert v["look"].startswith("Impossible interior") and v["judge"].startswith("a cold viewer") and v["cheap"].startswith("a kaleidoscope")
        assert broll.register_names() == ["vision", "cosmos"] and broll.register_of("Vision")["name"] == "vision"
        assert broll.register_of("photo") is None and broll.register_of(None) is None

    def test_the_bible_text_tells_the_registers_and_the_wrong_facts(self, bible):
        text = ai_brain.bible_text()
        assert "REGISTERS (how this episode shows what a camera cannot shoot" in text
        assert '- "vision" — when: what Chase saw and felt on DMT | look: Impossible interior' in text
        assert "| judge: a cold viewer" in text and "| cheap: a kaleidoscope" in text
        assert "WRONG FACTS (never show): a smoked DMT pipe" in text and "AVOID:" not in text

    def test_an_old_bible_without_registers_still_works(self, monkeypatch):
        old = ai_brain._clean_bible({k: v for k, v in BIBLE_RAW.items() if k != "registers"}, "claude")
        monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", old)
        assert old["registers"] == [] and broll.registers() == [] and "REGISTERS" not in ai_brain.bible_text()
        assert broll.style_rule_premium() == broll.STYLE_RULE_PREMIUM


class TestTheEditor:
    def _plan(self, monkeypatch, data=None):
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt, schema=schema) or (data or {"moments": []}))
        return seen, broll.plan_with_claude({}, _words(TEXT), 4, [], auto_style=True, hero=True)

    def test_the_style_rule_lists_the_registers(self, monkeypatch, bible):
        seen, _m = self._plan(monkeypatch)
        p = seen["prompt"]
        assert '"vision"     - what Chase saw and felt on DMT' in p and '"cosmos"     - the universe' in p
        assert "A register is not an allegory" in p and "Never a photo of a\n  stand-in object when a register fits" in p
        enum = seen["schema"]["properties"]["moments"]["items"]["properties"]["style"]["enum"]
        assert "vision" in enum and "cosmos" in enum and "photo" in enum
        assert "when the episode's REGISTERS (in the bible below) give it one" in p
        assert "NO SYMBOL FOR AN IDEA (photo pictures)" in p and "NEVER THE AI CLICHÉ" not in p
        assert enum == ["photo", "vision", "cosmos"]

    def test_without_registers_the_old_rule_and_schema(self, monkeypatch):
        seen, _m = self._plan(monkeypatch)
        assert 'the look of every picture comes from its "mood"' in seen["prompt"]
        assert seen["schema"]["properties"]["moments"]["items"]["properties"]["style"]["enum"] == ["photo"]

    def test_a_register_style_survives_the_parse_and_the_mixed_layout(self, monkeypatch, bible):
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"moments": [{"anchor": "alien beings", "time": words[idx["alien"]]["start"], "image_prompt": "x", "style": "vision"},
                            {"anchor": "coffee", "time": words[idx["coffee"]]["start"], "image_prompt": "y", "style": "neon"}]}
        _s, moments = self._plan(monkeypatch, data)
        assert [m["style"] for m in moments] == ["vision", "neon"]
        assert broll.premium_style("vision") == "vision" and broll.premium_style("neon") == "photo"
        assert broll.premium_style("cinematic") == "photo" and broll.register_look(moments[0]) == VISION
        assert broll.register_look(moments[1]) is None

    def test_without_a_bible_a_register_name_is_dropped(self, monkeypatch):
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        res = broll._parse_moments({"moments": [{"anchor": "coffee", "time": words[idx["coffee"]]["start"], "image_prompt": "x", "style": "vision"}]}, words, 3, [])
        assert res and res[0]["style"] is None and broll.premium_style("vision") == "photo"


class TestTheDirector:
    def test_a_register_picture_gets_its_block_and_every_picture_a_judge_line(self, bible):
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "style": "vision", "hero": True, "thesis": "T"},
              {"t": 9.0, "anchor": "b", "prompt": "q", "subject": "cup", "style": "photo"}]
        text = broll._art_prompt(ms, {"video_title_for_youtube_short": "Title"})
        assert 'REGISTER "vision" (not a photograph): Impossible interior' in text and "Cheap version to stay away from: a kaleidoscope" in text
        assert "- REGISTER PICTURES: a picture marked REGISTER below is not a photograph" in text
        assert "EACH PICTURE'S LOOK comes with it below" in text
        assert 'For EVERY picture also write "judge"' in text and '"judge": "..."' in text
        assert "- PHOTO pictures: NEVER THE AI CLICHÉ" in text
        assert text.count("  look (") == 1          # the photo has its look sheet, the vision its register instead
        assert "judge" in broll.ART_SCHEMA["properties"]["prompts"]["items"]["properties"]

    def test_no_register_paragraph_for_an_all_photo_set(self):
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "style": "photo"}]
        text = broll._art_prompt(ms, {})
        assert "REGISTER PICTURES" not in text and 'write "judge"' in text

    def test_the_judge_line_lands_on_the_moment(self):
        long = ("word " * 90).strip()
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s"}]
        assert broll._apply_art(ms, {"prompts": [{"k": 0, "prompt": long, "judge": "  the dome must  breathe "}]}) == 1
        assert ms[0]["judge"] == "the dome must breathe"


class TestTheImageText:
    def test_a_register_picture_has_no_look_sentence_and_no_style_sentence(self):
        text = broll._image_text("A dome of tiles.", "vision", look="L", art=True, register=VISION, mood="M sentence.")
        assert text == f"A dome of tiles. {VISION} {broll.ART_RULES}"
        plain = broll._image_text("A dome of tiles.", "vision", look="L", art=False, register=VISION, mood="M sentence.")
        assert plain == text and "M sentence." not in plain

    def test_a_photo_is_untouched(self):
        assert broll._image_text("A cup.", "photo", art=True) == f"A cup. {broll.ART_RULES}"

    def test_the_manual_redo_keeps_the_register(self, monkeypatch):
        seen = []
        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)
        monkeypatch.setattr(broll, "local_image", lambda prompt, style, out, **kw: seen.append((style, kw.get("register"))) or out)
        broll.regenerate_image("A dome.", "vision", "o.jpg", cfg={"layout": "hero"}, gen=[896, 1600], register=VISION)
        broll.regenerate_image("A dome.", "vision", "o.jpg", cfg={"layout": "hero"}, gen=[896, 1600])
        assert seen == [("vision", VISION), ("photo", None)]


class TestTheReviewer:
    def test_the_judge_line_and_the_register_reach_the_review(self, bible):
        words = _words(TEXT)
        lines = broll._review_lines([{"file": "/x/broll_0.jpg", "m": {"t": 5.0, "idea": "i", "said": "s", "prompt": "p",
                                                                     "judge": "the dome breathes", "style": "vision"}},
                                     {"file": "/x/broll_1.jpg", "m": {"t": 9.0, "idea": "i", "said": "s", "prompt": "q", "style": "photo"}}], words)
        assert 'judge it on: "the dome breathes"' in lines[0] and 'REGISTER "vision" (not a photograph; its cheap version: a kaleidoscope' in lines[0]
        assert "judge it on" not in lines[1] and "REGISTER" not in lines[1]

    def test_the_review_prompt_judges_a_register_on_its_own_terms(self):
        text = broll.REVIEW_PROMPT.format(frame=broll._review_frame([{"layout": "hero"}]), items="- x")
        assert "A picture marked REGISTER below is not a photograph" in text and "never on a real light source" in text
        assert "its cheap line is its only stock test" in text
        assert "rate the sense against it first" in text
