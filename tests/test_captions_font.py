"""The caption face is a property of the preset (viral_fx.PRESETS[...]["font"]):
the historical presets keep Liberation Sans, the "premium" preset sets the same
calm captions in the bundled Montserrat ExtraBold."""
import os
import re

import viral_fx

WORDS = [{"text": w, "start": i * 0.35, "end": i * 0.35 + 0.3} for i, w in enumerate(
    "so the dopamine system in your brain is basically a prediction machine. it learns from every mistake".split())]


def _style(ass, name):
    return next(line for line in ass.splitlines() if line.startswith(f"Style: {name},"))


class TestPresetFont:
    def test_natural_punchy_and_clean_are_unchanged(self):
        ass, _ = viral_fx.build_ass(WORDS, "natural", watermark="@thesynapsecut")
        main = _style(ass, "Main")
        assert main.startswith("Style: Main,Liberation Sans,64,")
        assert main.endswith(",&H70000000,&H99000000,1,0,0,0,100,100,0.5,0,1,2,2,5,0,0,0,1")
        assert _style(ass, "Mark").startswith("Style: Mark,Liberation Sans,18,") and _style(ass, "Mark").split(",")[7] == "1"
        for preset in ("punchy", "clean"):
            ass, _ = viral_fx.build_ass(WORDS, preset)
            assert _style(ass, "Main").startswith(f"Style: Main,Liberation Sans,{viral_fx.PRESETS[preset]['size']},")

    def test_premium_sets_the_same_captions_in_the_bundled_face(self):
        ass, groups = viral_fx.build_ass(WORDS, "premium", watermark="@thesynapsecut")
        main = _style(ass, "Main")
        assert main.startswith("Style: Main,Montserrat ExtraBold,72,")
        # the face is already extra bold (no synthetic bold) and wide (no extra spacing)
        assert main.endswith(",&H70000000,&H99000000,0,0,0,0,100,100,0,0,1,2,2,5,0,0,0,1")
        assert _style(ass, "Mark").startswith("Style: Mark,Montserrat ExtraBold,")
        nat, nat_groups = viral_fx.build_ass(WORDS, "natural", watermark="@thesynapsecut")
        assert len(groups) == len(nat_groups)
        main_pos = lambda text: re.findall(r"\\pos\(\d+,\d+\)", "\n".join(l for l in text.splitlines() if ",Main,," in l))
        assert main_pos(ass) == main_pos(nat)                                                 # same place on screen
        assert ass.count("\\fad(80,0)") == nat.count("\\fad(80,0)")                          # same calm fade-in
        assert ass.count("\\c&H4DD8FF&") == nat.count("\\c&H4DD8FF&")                        # same accent words

    def test_the_face_ships_in_fonts_under_the_ofl(self):
        from PIL import ImageFont
        path = os.path.join(viral_fx.FONT_DIR, "Montserrat-ExtraBold.ttf")
        assert os.path.exists(path)
        assert ImageFont.truetype(path, 20).getname() == ("Montserrat", "ExtraBold")
        with open(os.path.join(viral_fx.FONT_DIR, "OFL-Montserrat.txt"), encoding="utf-8") as f:
            assert "SIL Open Font License" in f.read()

    def test_premium_is_a_profile_style_and_keeps_the_caption_band(self):
        import broll
        import plus
        assert plus.sanitize({"edit_style": "premium"})["edit_style"] == "premium"
        assert plus.sanitize({"edit_style": "fancy"})["edit_style"] == "natural"
        top, bottom = broll._caption_band(1920, "premium", True)
        nt, nb = broll._caption_band(1920, "natural", True)
        assert abs(top - nt) <= 8 and abs(bottom - nb) <= 10     # 72 px instead of 64: a few px, same band
