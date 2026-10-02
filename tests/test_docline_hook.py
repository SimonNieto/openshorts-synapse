"""The documentary line (hooks "docline", H3 of the hook study of 2-oct-2026):
a topic eyebrow, a short rule that draws itself, the hook in sentence case
with its payoff word in yellow, a soft veil; the title leaves, the eyebrow
and the rule stay. These tests pin the accent choice, the wrap, the frames
(what moves when, what stays) and the ffmpeg graph — never ffmpeg itself.
"""
import os

from PIL import Image

import hooks
import playbook
import plus
from hooks import (DOCLINE, DOCLINE_ACCENT, create_docline_frames, docline_accent,
                   docline_graph, docline_layout)

W, H = 540, 960   # half a 1080x1920 frame: the same proportions, faster
HOOK = "He asked “am I dead?” 39 times."


class TestAccent:
    def test_the_brain_s_words_win_when_they_are_in_the_hook(self):
        words = HOOK.split()
        assert docline_accent(HOOK, "39 times") == {words.index("39"), words.index("times.")}

    def test_the_brain_s_words_are_matched_without_case_or_punctuation(self):
        assert docline_accent("Most doctors won't tell you this.", "THIS") == {5}

    def test_a_number_when_the_brain_s_words_are_not_in_the_hook(self):
        assert docline_accent(HOOK, "universe") == {HOOK.split().index("39")}

    def test_else_the_last_long_non_filler_word(self):
        assert docline_accent("Most doctors won't tell you this.") == {3}
        assert docline_accent("Your brain fakes eyeballs just to see.") == {3}

    def test_nothing_to_colour_in_a_hook_of_fillers(self):
        assert docline_accent("You and me.") == set()


class TestLayout:
    def test_a_short_hook_is_one_line_at_full_size(self):
        lines, font, _ = docline_layout("Nobody tells you this.", 1080)
        assert lines == [["Nobody", "tells", "you", "this."]]
        assert font.size == DOCLINE["title_px"]

    def test_two_lines_break_after_the_punctuation_not_greedily(self):
        lines, _, _ = docline_layout(HOOK, 1080)
        assert lines == [["He", "asked", "“am", "I", "dead?”"], ["39", "times."]]

    def test_the_lines_stay_between_the_margins(self):
        lines, font, tracking = docline_layout(HOOK + " And then he stopped asking.", 1080)
        max_w = 1080 * (1 - DOCLINE["left"] - DOCLINE["right"])
        assert 2 <= len(lines) <= DOCLINE["title_lines"]
        for line in lines:
            assert hooks._tracked_width(font, " ".join(line), tracking) <= max_w

    def test_a_hook_too_long_for_two_lines_shrinks_instead_of_losing_words(self):
        text = "This is the longest hook anyone has ever written for a clip of this channel so far"
        lines, font, _ = docline_layout(text, 1080)
        assert [w for l in lines for w in l] == text.split()
        assert len(lines) <= DOCLINE["title_lines"]
        assert int(DOCLINE["title_px"] * DOCLINE["title_min_scale"]) <= font.size < DOCLINE["title_px"]

    def test_emoji_are_dropped(self):
        lines, _, _ = docline_layout("Stop 🛑 doing this! 💯", 1080)
        assert lines == [["Stop", "doing", "this!"]]

    def test_no_line_ends_on_an_article_or_a_conjunction(self):
        # The JRE #2515 hook first broke as "The universe and a" / "brain cell look identical".
        text = "The universe and a brain cell look identical"
        lines, font, tracking = docline_layout(text, 1080)
        assert [w for l in lines for w in l] == text.split()
        assert len(lines) == 2 and lines[0][-1].lower() not in hooks._NO_END
        assert font.size >= int(DOCLINE["title_px"] * DOCLINE["title_nice_scale"])


def _chars(ws):
    return len(" ".join(ws))


class TestBreak:
    """docline_break with a width of one per character."""
    WORDS = "The universe and a brain cell look identical".split()

    def test_a_clause_break_comes_first(self):
        assert hooks.docline_break(HOOK.split(), _chars, 25) == (1, 5)

    def test_then_a_break_before_a_phrase(self):
        # "The universe" / "and a brain cell look identical" (12 / 31).
        assert hooks.docline_break(self.WORDS, _chars, 31) == (2, 2)

    def test_then_any_break_that_does_not_leave_an_orphan(self):
        # At 30 the phrase break no longer fits: "...and a brain" / "cell look identical".
        assert hooks.docline_break(self.WORDS, _chars, 30) == (3, 5)

    def test_a_lopsided_clause_break_is_not_a_clause_break(self):
        words = "Wait, this changes everything about sleep.".split()
        tier, k = hooks.docline_break(words, _chars, 40)
        assert (tier, k) != (1, 1)

    def test_nothing_fits(self):
        assert hooks.docline_break(self.WORDS, _chars, 10) is None


def _alpha_max(img, box):
    return max(img.crop(box).getchannel("A").getdata())


class TestFrames:
    def _make(self, tmp_path, **kw):
        return create_docline_frames(HOOK, "Psychology", W, H, str(tmp_path), accent="39", seconds=1.0, **kw)

    def test_the_sequence_covers_the_entrance_the_hold_and_the_exit(self, tmp_path):
        made = self._make(tmp_path)
        fps = DOCLINE["fps"]
        assert made["count"] == int(round((1.0 + DOCLINE["out"]) * fps)) + 1
        for k in range(made["count"]):
            assert os.path.exists(made["pattern"] % k)
        assert os.path.exists(made["rest"])
        assert made["lines"] == ["He asked “am I dead?”", "39 times."]
        assert made["accent"] == ["39"]

    def test_every_frame_is_the_top_band_of_the_picture(self, tmp_path):
        made = self._make(tmp_path)
        size = Image.open(made["pattern"] % 0).size
        assert size[0] == W and int(H * 0.25) <= size[1] <= int(H * 0.45)
        assert Image.open(made["rest"]).size == size
        # The veil fades out inside the band: its last row is clear.
        assert _alpha_max(Image.open(made["pattern"] % int(0.8 * DOCLINE["fps"])),
                          (0, size[1] - 1, W, size[1])) == 0

    def test_the_first_frame_is_empty_and_the_held_frame_is_full(self, tmp_path):
        made = self._make(tmp_path)
        fps = DOCLINE["fps"]
        first = Image.open(made["pattern"] % 0)
        held = Image.open(made["pattern"] % int(0.8 * fps))
        title_zone = (0, int(H * 0.17), W, held.size[1])
        assert _alpha_max(first, title_zone) == 0
        assert _alpha_max(held, title_zone) > 200
        # The veil is on at the top edge of the held frame, and still full
        # behind the first line of the title (the neon sign sits there).
        assert held.getpixel((W // 2, 0))[3] == round(255 * DOCLINE["veil_alpha"])
        first_line = int(H * 0.17)
        assert held.getpixel((W - 5, first_line))[3] == round(255 * DOCLINE["veil_alpha"])

    def test_the_rule_draws_itself_from_the_left(self, tmp_path):
        made = self._make(tmp_path)
        fps = DOCLINE["fps"]
        start, length = DOCLINE["rule"]
        mid = Image.open(made["pattern"] % int(round((start + length / 2) * fps)))
        done = Image.open(made["pattern"] % int(round((start + length) * fps) + 2))
        left = int(W * DOCLINE["left"])
        full = int(W * DOCLINE["rule_width"])

        def rule_width(img):
            a = img.getchannel("A")
            # The rule is the one row of fully opaque white pixels under the eyebrow.
            best = 0
            for y in range(int(H * DOCLINE["top"]), int(H * 0.17)):
                row = [x for x in range(left, left + full + 2) if a.getpixel((x, y)) == 255
                       and img.getpixel((x, y))[:3] == (255, 255, 255)]
                best = max(best, len(row))
            return best

        assert 0 < rule_width(mid) < rule_width(done)
        assert abs(rule_width(done) - full) <= 2

    def test_the_payoff_word_is_yellow_and_the_rest_white(self, tmp_path):
        made = self._make(tmp_path)
        held = Image.open(made["pattern"] % int(0.8 * DOCLINE["fps"]))
        colours = {px[:3] for px in held.getdata() if px[3] == 255}
        assert DOCLINE_ACCENT in colours and (255, 255, 255) in colours

    def test_after_the_title_leaves_the_eyebrow_and_the_rule_stay(self, tmp_path):
        made = self._make(tmp_path)
        rest = Image.open(made["rest"])
        last = Image.open(made["pattern"] % (made["count"] - 1))
        assert list(rest.getdata()) == list(last.getdata())
        title_zone = (0, int(H * 0.19), W, rest.size[1])
        eyebrow_zone = (0, int(H * DOCLINE["top"]), W, int(H * 0.17))
        # Under the title zone only the veil remains (black, faint).
        assert _alpha_max(rest, title_zone) < 255 * DOCLINE["rest_alpha"] + 2
        assert _alpha_max(rest, eyebrow_zone) == 255
        assert rest.getpixel((W // 2, 0))[3] == round(255 * DOCLINE["rest_alpha"])

    def test_without_a_topic_the_rule_alone_opens_the_line(self, tmp_path):
        made = create_docline_frames(HOOK, "", W, H, str(tmp_path), seconds=1.0)
        rest = Image.open(made["rest"])
        y = int(H * DOCLINE["top"])
        left = int(W * DOCLINE["left"])
        assert rest.getpixel((left + 2, y + 1))[:3] == (255, 255, 255)

    def test_identical_states_are_written_once(self, tmp_path, monkeypatch):
        saved = []
        real = Image.Image.save

        def spy(self, fp, *a, **kw):
            saved.append(fp)
            return real(self, fp, *a, **kw)

        monkeypatch.setattr(Image.Image, "save", spy)
        made = create_docline_frames(HOOK, "Psychology", W, H, str(tmp_path), seconds=3.3)
        # About 28 moving states (eyebrow 5, rule 11, title 12, exit 6) out of 106 frames.
        assert len(saved) < made["count"] // 3


class TestGraph:
    def test_the_sequence_then_the_resting_png(self):
        graph = docline_graph(3.5)
        assert "eof_action=pass" in graph
        assert "enable='gte(t,3.500)'" in graph and graph.endswith("[v]")


class TestWiring:
    def test_the_style_exists_and_the_recipe_uses_it(self):
        assert "docline" in hooks.HOOK_STYLES
        assert plus.HOOK_STYLE == "docline" and plus.HOOK_SECONDS == 3.3

    def test_the_eyebrow_comes_from_the_topic_bucket(self):
        assert playbook.hook_category({"topic_bucket": "mind_psychology"}) == "Psychology"
        assert playbook.hook_category({"topic_bucket": "other"}) == ""
        assert playbook.hook_category({}) == ""
        for bucket in playbook.TOPIC_BUCKETS:
            if bucket != "other":
                assert playbook.hook_category({"topic_bucket": bucket}), bucket

    def test_the_rewritten_hook_keeps_the_accent_the_model_named(self):
        clip = {"video_title_for_youtube_short": "Is everything you see made of consciousness?",
                "viral_hook_text": "He explains it", "punchline": ""}
        assert playbook.apply_hook_retry(clip, "Your brain fakes eyeballs just to see.", "fakes eyeballs")
        assert clip["hook_accent"] == "fakes eyeballs"
