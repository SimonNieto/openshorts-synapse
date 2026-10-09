"""The one-word captions (9-oct-2026, the « références » recipe, OptimalHealth as the model;
RECETTE_REFERENCES.md sections 2-3): one word at a time in capitals, white with a thick black
edge, mid-screen, a golden strong word now and then, from the first word; no hook title on
screen; « CREDIT: <show> » tiny at the top left and the channel's name in a grey box at the top
right, the whole clip long. The last class has libass draw them and measures the ink."""
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np
import pytest

import viral_fx

TEXT = ("if you go to the emergency room at three in the morning, your first question for the "
        "on-call physician should be... how long have you been on call? malpractice kills 251,000 people")
WORDS = [{"text": w, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, w in enumerate(TEXT.split())]


def _style(ass, name):
    return next(line for line in ass.splitlines() if line.startswith(f"Style: {name},")).split(",")


def _lines(ass, style):
    return [l for l in ass.splitlines() if l.startswith("Dialogue:") and f",{style},," in l]


def _text(line):
    return re.sub(r"\{[^}]*\}", "", line.split(",,", 1)[1].split(",", 4)[-1])


class TestOneWord:
    def test_one_word_a_caption_in_capitals_without_its_punctuation(self):
        ass, groups = viral_fx.build_ass(WORDS, "oneword")
        texts = [_text(l) for l in _lines(ass, "Main")]
        assert all(len(g) == 1 for g in groups)
        # "..." alone is not a word; "morning," / "be..." / "call?" lose their punctuation
        assert len(texts) == len(WORDS) - 0 and "MORNING" in texts and "BE" in texts and "CALL" in texts
        assert "ON-CALL" in texts and "251,000" in texts and "OF" not in texts and "THE" in texts
        assert all(t == t.upper() and " " not in t for t in texts)
        words = [{"text": "...", "start": 0, "end": 0.2}, {"text": "so", "start": 0.3, "end": 0.5}]
        assert [_text(l) for l in _lines(viral_fx.build_ass(words, "oneword")[0], "Main")] == ["SO"]

    def test_a_word_shows_from_its_start_to_the_next_one_from_the_first_word(self):
        ass, _ = viral_fx.build_ass(WORDS, "oneword", after=0.0)
        times = [l.split(",")[1:3] for l in _lines(ass, "Main")]
        assert times[0] == ["0:00:00.00", "0:00:00.30"] and times[1][0] == "0:00:00.30"

    def test_mid_screen_white_thick_black_edge_no_fade_no_lighting(self):
        p = viral_fx.PRESETS["oneword"]
        assert (p["font"], p["size"], p["caption_y"], p["lit"]) == ("Montserrat ExtraBold", 133, 1114, False)
        assert 0.56 <= p["caption_y"] / 1920 <= 0.60                 # theirs 58 % (mesures, 9 hits)
        f = _style(viral_fx.build_ass(WORDS, "oneword")[0], "Main")
        # PrimaryColour white, OutlineColour solid black, Outline 6, Shadow 3
        assert (f[3], f[5], f[16], f[17]) == ("&H00FFFFFF", "&H00000000", "6", "3")
        ass, _ = viral_fx.build_ass(WORDS, "oneword")
        assert "\\fad" not in ass and "\\1a" not in ass and "\\t(" not in ass
        assert {m for m in re.findall(r"\\pos\((\d+),(\d+)\)", "\n".join(_lines(ass, "Main")))} == {("540", "1114")}

    def test_at_most_one_golden_word_and_only_an_emotion_word(self):
        # Decoded on 12 OptimalHealth shorts: one coloured word (« CRAZY ») in 724 s.
        gold = viral_fx._ass_color("#F2B544")
        ass, groups = viral_fx.build_ass(WORDS, "oneword")
        assert gold not in ass  # no emotion word in this text: all white
        ws = [{"text": w, "start": i * 0.3, "end": i * 0.3 + 0.25}
              for i, w in enumerate("that is crazy and really insane, crazy right".split())]
        lines = _lines(viral_fx.build_ass(ws, "oneword")[0], "Main")
        keyed = [_text(l) for l in lines if gold in l]
        assert keyed == ["CRAZY"]
        for w in ("emergency", "understand", "necessarily", "sometimes"):
            assert gold not in viral_fx.build_ass([{"text": w, "start": 0, "end": 0.2}], "oneword")[0]

    def test_a_very_long_word_is_set_smaller_to_stay_inside_84_percent(self):
        p = viral_fx.PRESETS["oneword"]
        assert p["safe_x"] == (0.08, 0.92)
        assert viral_fx._fit_scale("EMERGENCY", p) == 100
        assert viral_fx._fit_scale("ELECTROENCEPHALOGRAPHY", p) < 100
        ws = [{"text": "electroencephalography", "start": 0, "end": 0.5}]
        assert "\\fscx" in _lines(viral_fx.build_ass(ws, "oneword")[0], "Main")[0]

    def test_premium_is_unchanged(self):
        p = viral_fx.PRESETS["premium"]
        assert (p["size"], p["caption_y"], p["max_words"], p["lit"]) == (100, 1275, 3, True)
        ass, _ = viral_fx.build_ass(WORDS, "premium", watermark="@TheSynapseCut", credit="Joe Rogan Experience")
        assert _lines(ass, "Mark") and not _lines(ass, "Corner") and not _lines(ass, "Badge")


class TestCorner:
    def test_the_channel_goes_top_right_in_its_box_never_under_the_word(self):
        ass, _ = viral_fx.build_ass(WORDS, "oneword", watermark="@TheSynapseCut", credit="Joe Rogan Experience",
                                    duration=29.5)
        assert not _lines(ass, "Mark")
        (badge,) = _lines(ass, "Badge")
        assert _text(badge) == "THE SYNAPSE CUT" and "\\an9" in badge
        assert badge.split(",")[1:3] == ["0:00:00.00", "0:00:29.50"]
        f = _style(ass, "Badge")
        assert f[15] == "3" and f[5] == "&H733C3C3C"            # BorderStyle 3: a grey see-through box

    def test_the_credit_line_top_left(self):
        ass, _ = viral_fx.build_ass(WORDS, "oneword", watermark="@TheSynapseCut", credit="Joe Rogan Experience",
                                    duration=29.5)
        (credit,) = _lines(ass, "Corner")
        assert _text(credit) == "CREDIT: JOE ROGAN EXPERIENCE" and "\\an7" in credit
        x, y = map(int, re.search(r"\\pos\((\d+),(\d+)\)", credit).groups())
        assert x < 0.06 * 1080 and y < 0.05 * 1920
        f = _style(ass, "Corner")
        assert int(f[2]) <= 0.02 * 1920 and f[3] == "&H33FFFFFF"   # ~2 % of the height, white at 80 %

    def test_without_a_show_or_a_watermark_nothing_at_the_top(self):
        ass, _ = viral_fx.build_ass(WORDS, "oneword")
        assert not _lines(ass, "Corner") and not _lines(ass, "Badge")

    def test_the_channel_label(self):
        assert viral_fx.channel_label("@TheSynapseCut") == "THE SYNAPSE CUT"
        assert viral_fx.channel_label("Optimal Health") == "OPTIMAL HEALTH"
        assert viral_fx.channel_label("") == "" and viral_fx.channel_label(None) == ""

    def test_the_show_comes_from_the_episode_title_then_the_profile(self):
        import playbook
        src = "/app/downloads/b8e46c24-7f5e-48cf-8adc-c2d2677a241e_Joe Rogan Experience #2553 - Andrew Huberman-004.mkv"
        assert playbook.show_name(src, "Joe Rogan podcast") == "Joe Rogan Experience"
        assert playbook.show_name("x_Some untitled long talk.mkv", "Huberman Lab") == "Huberman Lab"
        assert len(playbook.show_name("A" * 10 + " " + "B" * 50 + ".mkv")) <= 40


class TestTheRecipe:
    def test_one_word_and_no_hook_title_by_default(self):
        import plus
        assert plus.CAPTION_STYLE == plus.EDIT_STYLE == "oneword" and plus.HOOK_ON_SCREEN is False
        env = plus.job_env({})
        assert env["EDIT_STYLE"] == "oneword" and env["AUTO_HOOK"] == "0"

    def test_both_switches_bring_the_old_recipe_back(self, monkeypatch):
        import plus
        monkeypatch.setattr(plus, "EDIT_STYLE", "premium")
        monkeypatch.setattr(plus, "HOOK_ON_SCREEN", True)
        env = plus.job_env({})
        assert (env["EDIT_STYLE"], env["AUTO_HOOK"], env["AUTO_HOOK_STYLE"]) == ("premium", "1", "docline")

    def test_the_broll_band_has_no_watermark_under_the_word(self):
        import broll
        top, bottom = broll._caption_band(1920, "oneword", True)
        assert (top, bottom) == broll._caption_band(1920, "oneword", False)
        assert top < 1114 < bottom

    def test_the_job_names_the_show_only_without_a_hook_title(self, monkeypatch, tmp_path):
        import main
        seen = []
        monkeypatch.setattr(viral_fx, "apply_captions", lambda *a, **k: seen.append(k.get("credit")))
        tr = {"segments": [{"words": [{"word": "hello", "start": 1.0, "end": 1.4}]}]}
        for name in ("clip_1.mp4", "hooked_1_clip_1.mp4"):
            main.viral_caption_clip(str(tmp_path / name), tr, 0.0, 5.0, "oneword", watermark="@TheSynapseCut",
                                    clip={}, show="Joe Rogan Experience")
        assert seen == ["Joe Rogan Experience", None]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg with libass")
class TestDrawnByLibass:
    """The real ass filter on a grey 1080x1920 frame: one word, then a very long one."""

    @pytest.fixture(scope="class")
    def frames(self):
        words = [{"text": "person", "start": 0.0, "end": 0.5}, {"text": "electroencephalography,", "start": 1.0, "end": 1.5}]
        ass, _ = viral_fx.build_ass(words, "oneword", watermark="@TheSynapseCut", credit="Joe Rogan Experience",
                                    duration=2.0)
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "c.ass")
            with open(path, "w", encoding="utf-8") as f:
                f.write(ass)
            cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x808080:s=1080x1920:r=10:d=2",
                   "-vf", f"ass='{path}':fontsdir='{viral_fx.FONT_DIR}',format=gray",
                   "-f", "rawvideo", "-pix_fmt", "gray", "-"]
            raw = subprocess.run(cmd, capture_output=True, check=True, timeout=120).stdout
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        fr = np.frombuffer(raw, np.uint8).reshape(-1, 1920, 1080).astype(int)
        return fr[3], fr[13]

    @staticmethod
    def _ink(a, y0, y1):
        band = np.abs(a[y0:y1] - 128) > 10
        rows, cols = np.where(band.any(axis=1))[0], np.where(band.any(axis=0))[0]
        return cols.min(), cols.max(), y0 + rows.min(), y0 + rows.max()

    def test_the_word_mid_screen_at_the_references_size(self, frames):
        person, _ = frames
        white = np.where((person[800:1200] > 235).any(axis=1))[0] + 800
        assert 54 <= white.max() - white.min() + 1 <= 66                  # capitals ~58 px (theirs 58, measured on the videos)
        assert abs((white.min() + white.max()) / 2 - 1114) <= 12
        left, right, _, _ = self._ink(person, 800, 1200)
        assert 0.26 <= (right - left) / 1080 <= 0.34                       # "PERSON" ~30 % of the width in theirs

    def test_a_very_long_word_stays_inside_84_percent(self, frames):
        _, long_word = frames
        left, right, _, _ = self._ink(long_word, 800, 1200)
        assert left >= 0.08 * 1080 and right <= 0.92 * 1080

    def test_the_top_corners_are_drawn(self, frames):
        person, _ = frames
        l, r, t, b = self._ink(person[:, :540], 0, 160)
        assert l < 0.06 * 1080 and b < 0.06 * 1920                         # the credit, top left
        l2, r2, t2, b2 = self._ink(person[:, 540:], 160, 320)
        assert 540 + r2 > 0.93 * 1080 and t2 >= 0.11 * 1920 - 12           # the channel's box, top right
