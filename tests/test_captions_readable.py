"""The premium captions read with the sound off, on a phone (5-oct-2026,
decision 1 of the "step up", the image study's C1 / idea 2): size 100, at most
14 characters, a thick almost solid black edge and a 3 px shadow, the words
not said yet at 70 %. Same place, same face, same yellow, same lit word; the
natural preset does not change. The last class has libass (the ass filter the
pipeline burns with) draw real captions and measures them."""
import os
import shutil
import subprocess
import tempfile

import numpy as np
import pytest

import viral_fx

WORDS = [{"text": w, "start": i * 0.35, "end": i * 0.35 + 0.3} for i, w in enumerate(
    "so the dopamine system in your brain is basically a prediction machine. it learns from every mistake".split())]


def _style(ass, name="Main"):
    return next(line for line in ass.splitlines() if line.startswith(f"Style: {name},")).split(",")


def _main_lines(ass):
    return [l for l in ass.splitlines() if l.startswith("Dialogue:") and ",Main,," in l]


class TestTheRecipe:
    def test_premium_is_bigger_and_shorter_in_the_same_place_face_and_yellow(self):
        p = viral_fx.PRESETS["premium"]
        assert (p["size"], p["max_chars"], p["max_words"]) == (100, 14, 3)
        assert (p["caption_y"], p["font"], p["accent"], p["lit"]) == (1275, "Montserrat ExtraBold", "#FFD84D", True)
        assert p["safe_x"] == (0.06, 0.84)

    def test_a_thick_almost_solid_black_edge_and_a_shadow(self):
        ass, _ = viral_fx.build_ass(WORDS, "premium")
        f = _style(ass)
        # OutlineColour, BackColour (the shadow), Outline, Shadow
        assert (f[5], f[6], f[16], f[17]) == ("&H20000000", "&H60000000", "5", "3")

    def test_the_lit_alphas_are_the_premium_style_s(self):
        p = viral_fx.PRESETS["premium"]
        f = _style(viral_fx.build_ass(WORDS, "premium")[0])
        assert viral_fx.LIT_DIM == 0.70
        assert viral_fx.LIT_ALPHAS == (int(f[3][2:4], 16), int(f[5][2:4], 16), int(f[6][2:4], 16))
        assert viral_fx.LIT_ALPHAS == (0x00, p["edge_alpha"], p["shadow_alpha"])

    def test_natural_does_not_change(self):
        n = viral_fx.PRESETS["natural"]
        assert (n["size"], n["max_chars"], n["caption_y"]) == (64, 16, 1180)
        assert not set(n) & {"outline", "shadow", "edge_alpha", "shadow_alpha", "safe_x", "lit"}
        ass, _ = viral_fx.build_ass(WORDS, "natural", watermark="@thesynapsecut")
        f = _style(ass)
        assert (f[5], f[6], f[16], f[17]) == ("&H70000000", "&H99000000", "2", "2")
        assert "\\fscx" not in ass and "\\1a" not in ass


class TestSafeWidth:
    """Inside 6-84 % of the width (the apps' buttons are on the right)."""

    def _words(self, *texts, gap=1.0):
        out, t = [], 0.0
        for text in texts:
            for w in text.split():
                out.append({"text": w, "start": t, "end": t + 0.1})
                t += 0.1
            t += gap
        return out

    def test_a_caption_of_14_or_so_characters_is_left_as_is(self):
        p = viral_fx.PRESETS["premium"]
        for text in ("A WHISTLEBLOWER.", "TO THE EMERGENCY", "UNDERSTAND HOW", "LIFE-THREATENING"):
            assert viral_fx._fit_scale(text, p) == 100, text
        ass, _ = viral_fx.build_ass(self._words("a whistleblower.", "understand how"), "premium")
        assert "\\fscx" not in ass

    def test_a_wider_run_of_short_words_is_set_a_little_smaller(self):
        # group_words lets short words carry a long one up to max_chars + 4
        ass, groups = viral_fx.build_ass(self._words("and the workhouse", "so"), "premium")
        assert [len(g) for g in groups] == [3, 1]
        first, second = _main_lines(ass)
        assert "\\fscx90\\fscy90" in first and "\\fscx" not in second
        assert 85 <= viral_fx._fit_scale("AND THE WORKHOUSE", viral_fx.PRESETS["premium"]) < 100

    def test_natural_or_a_face_that_cannot_be_measured_is_never_narrowed(self, monkeypatch):
        assert viral_fx._fit_scale("AND THE WORKHOUSE WWWW", viral_fx.PRESETS["natural"]) == 100
        monkeypatch.setattr(viral_fx, "CAPTION_FACES", {})
        assert viral_fx._fit_scale("AND THE WORKHOUSE WWWW", viral_fx.PRESETS["premium"]) == 100

    def test_never_below_half(self):
        assert viral_fx._fit_scale("W" * 60, viral_fx.PRESETS["premium"]) == 50


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg with libass")
class TestDrawnByLibass:
    """The real ass filter on a grey 1080x1920 frame, each caption fully lit."""
    Y0, Y1 = 1100, 1460
    GROUPS = ["a whistleblower.", "and the workhouse", "hhhh", "jumpy, quiz"]

    @pytest.fixture(scope="class")
    def frames(self):
        words, starts, t = [], [], 0.0
        for text in self.GROUPS:
            starts.append(t)
            for w in text.split():
                words.append({"text": w, "start": t, "end": t + 0.1})
                t += 0.1
            t += 1.5
        ass, groups = viral_fx.build_ass(words, "premium", watermark="@TheSynapseCut")
        assert len(groups) == len(self.GROUPS)
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "c.ass")
            with open(path, "w", encoding="utf-8") as f:
                f.write(ass)
            # 10 fps: frame round((start + 0.4) * 10) shows the group, every word lit
            cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x808080:s=1080x1920:r=10:d={t:.1f}",
                   "-vf", f"ass='{path}':fontsdir='{viral_fx.FONT_DIR}',"
                   f"crop=1080:{self.Y1 - self.Y0}:0:{self.Y0},format=gray",
                   "-f", "rawvideo", "-pix_fmt", "gray", "-"]
            raw = subprocess.run(cmd, capture_output=True, check=True, timeout=120).stdout
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        fr = np.frombuffer(raw, np.uint8).reshape(-1, self.Y1 - self.Y0, 1080).astype(int)
        return {text: fr[int(round((s + 0.4) * 10))] for text, s in zip(self.GROUPS, starts)}

    def _ink(self, a):
        ink = np.abs(a - 128) > 10
        rows, cols = np.where(ink.any(axis=1))[0], np.where(ink.any(axis=0))[0]
        return cols.min(), cols.max(), self.Y0 + rows.min(), self.Y0 + rows.max()

    def test_capitals_are_44_px(self, frames):
        white = np.where((frames["hhhh"] > 235).any(axis=1))[0]
        assert 42 <= white.max() - white.min() + 1 <= 46            # 32 at size 72

    def test_every_caption_stays_inside_the_safe_width(self, frames):
        for text, a in frames.items():
            left, right, _, _ = self._ink(a)
            assert left >= 0.06 * 1080 and right <= 0.84 * 1080, text

    def test_same_place_and_broll_s_band_holds_the_caption_and_the_watermark(self, frames):
        import broll
        top, bottom = broll._caption_band(1920, "premium", True)
        for text, a in frames.items():
            _, _, ink_top, ink_bottom = self._ink(a)
            assert top <= ink_top and ink_bottom <= bottom, text
        white = np.where((frames["hhhh"] > 235).any(axis=1))[0] + self.Y0
        assert abs((white.min() + white.max()) / 2 - 1275) <= 12   # the capitals' middle near caption_y
