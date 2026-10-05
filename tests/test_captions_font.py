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
    def test_natural_is_unchanged_and_the_old_presets_are_gone(self):
        ass, _ = viral_fx.build_ass(WORDS, "natural", watermark="@thesynapsecut")
        main = _style(ass, "Main")
        assert main.startswith("Style: Main,Liberation Sans,64,")
        assert main.endswith(",&H70000000,&H99000000,1,0,0,0,100,100,0.5,0,1,2,2,5,0,0,0,1")
        assert _style(ass, "Mark").startswith("Style: Mark,Liberation Sans,18,") and _style(ass, "Mark").split(",")[7] == "1"
        # punchy / clean (glow, jump zooms, shake) were removed on 1-oct-2026
        assert set(viral_fx.PRESETS) == {"natural", "premium"}

    def test_premium_sets_the_same_groups_in_the_bundled_face_lower_and_lit(self):
        ass, groups = viral_fx.build_ass(WORDS, "premium", watermark="@thesynapsecut")
        main = _style(ass, "Main")
        # 100 since 5-oct-2026 (72 before): read with the sound off, on a phone
        assert main.startswith("Style: Main,Montserrat ExtraBold,100,")
        # the face is already extra bold (no synthetic bold) and wide (no extra
        # spacing); a 5 px almost solid black edge and a 3 px shadow (5-oct-2026)
        assert main.endswith(",&H20000000,&H60000000,0,0,0,0,100,100,0,0,1,5,3,5,0,0,0,1")
        assert _style(ass, "Mark").startswith("Style: Mark,Montserrat ExtraBold,")
        nat, nat_groups = viral_fx.build_ass(WORDS, "natural", watermark="@thesynapsecut")
        assert len(groups) == len(nat_groups)
        main_pos = lambda text: set(re.findall(r"\\pos\((\d+),(\d+)\)",
                                               "\n".join(l for l in text.splitlines() if ",Main,," in l)))
        # Under the mouth of the premium framing (2-oct-2026); natural keeps its place.
        assert main_pos(ass) == {("540", "1275")} and main_pos(nat) == {("540", "1180")}
        assert ass.count("\\fad(80,0)") == nat.count("\\fad(80,0)")                          # same calm fade-in
        # The same key words get the accent (premium reaches it when the word is said).
        accent = viral_fx._ass_color("#FFD84D")
        assert ass.count(accent) == nat.count(accent) > 0

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
        # premium is the house style: every Clip Generator++ job, whatever an old profile said
        assert plus.EDIT_STYLE == "premium"
        assert plus.job_env({"name": "t", "edit_style": "punchy"})["EDIT_STYLE"] == "premium"
        assert "edit_style" not in plus.sanitize({"edit_style": "punchy"})
        top, bottom = broll._caption_band(1920, "premium", True)
        nt, nb = broll._caption_band(1920, "natural", True)
        # premium sits lower (1275 instead of 1180) and, since 5-oct-2026, is
        # bigger (100 instead of 72): its band starts lower and ends lower than
        # natural's, the watermark included, and stays inside the band the
        # apps leave free (above 75 % of the height; their bar from ~83 %).
        assert (top, bottom) == (1200, 1385)
        assert top > nt and bottom > nb
        assert bottom < 1920 * 0.75
        # That it holds the ink libass really draws: tests/test_captions_readable.py.
