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


FPS = DOCLINE["fps"]


def _at(made, t):
    return Image.open(hooks.docline_frame_at(made, t))


def _frame(made, k):
    """Frame k of the timeline, sampled in the middle of the frame."""
    return _at(made, (k + 0.5) / FPS)


class TestFrames:
    def _make(self, tmp_path, **kw):
        kw.setdefault("total", 6.0)
        return create_docline_frames(HOOK, "Psychology", W, H, str(tmp_path), accent="39", seconds=1.0, **kw)

    def test_the_timeline_covers_the_clip_and_a_second_more(self, tmp_path):
        made = self._make(tmp_path)
        assert abs(sum(d for _, d in made["segments"]) - 7.0) < 1e-6
        assert abs(made["title_end"] - (int(round((1.0 + DOCLINE["out"]) * FPS)) + 1) / FPS) < 1e-9
        for png, _ in made["segments"]:
            assert os.path.exists(png)
        assert made["lines"] == ["He asked “am I dead?”", "39 times."]
        assert made["accent"] == ["39"]

    def test_every_frame_is_the_top_band_of_the_picture(self, tmp_path):
        made = self._make(tmp_path)
        sizes = {Image.open(p).size for p, _ in made["segments"]}
        assert len(sizes) == 1
        size = sizes.pop()
        assert size[0] == W and int(H * 0.25) <= size[1] <= int(H * 0.45)
        # The veil fades out inside the band: its last row is clear.
        assert _alpha_max(_frame(made, int(0.8 * FPS)), (0, size[1] - 1, W, size[1])) == 0

    def test_the_first_frame_is_empty_and_the_held_frame_is_full(self, tmp_path):
        made = self._make(tmp_path)
        first = _frame(made, 0)
        held = _frame(made, int(0.8 * FPS))
        title_zone = (0, int(H * 0.17), W, held.size[1])
        assert _alpha_max(first, title_zone) == 0
        assert _alpha_max(held, title_zone) > 200
        # The veil is on at the top edge of the held frame, and still full
        # behind the first line of the title (the neon sign sits there).
        assert held.getpixel((W // 2, 0))[3] == round(255 * DOCLINE["veil_alpha"])
        assert held.getpixel((W - 5, int(H * 0.17)))[3] == round(255 * DOCLINE["veil_alpha"])

    def test_the_rule_draws_itself_from_the_left(self, tmp_path):
        made = self._make(tmp_path)
        start, length = DOCLINE["rule"]
        mid = _frame(made, int(round((start + length / 2) * FPS)))
        done = _frame(made, int(round((start + length) * FPS)) + 2)
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
        held = _frame(made, int(0.8 * FPS))
        colours = {px[:3] for px in held.getdata() if px[3] == 255}
        assert DOCLINE_ACCENT in colours and (255, 255, 255) in colours

    def test_by_default_everything_leaves_with_the_title(self, tmp_path):
        # The channel's choice (2-oct-2026): the topic goes too, nothing stays on the clip.
        made = self._make(tmp_path)
        assert hooks.docline_frame_at(made, 5.9) == made["rest"]
        rest = Image.open(made["rest"])
        assert _alpha_max(rest, (0, 0, W, rest.size[1])) == 0
        # ...while the eyebrow and the rule are there with the title.
        held = _frame(made, int(0.8 * FPS))
        assert _alpha_max(held, (0, int(H * DOCLINE["top"]), W, int(H * 0.15))) == 255

    def test_kept_the_eyebrow_and_the_rule_stay(self, tmp_path):
        made = self._make(tmp_path, cfg={"keep_eyebrow": True})
        assert hooks.docline_frame_at(made, made["title_end"] + 0.01) == made["rest"]
        assert hooks.docline_frame_at(made, 5.9) == made["rest"]
        rest = Image.open(made["rest"])
        title_zone = (0, int(H * 0.19), W, rest.size[1])
        eyebrow_zone = (0, int(H * DOCLINE["top"]), W, int(H * 0.17))
        # Under the title zone only the veil remains (black, faint).
        assert _alpha_max(rest, title_zone) < 255 * DOCLINE["rest_alpha"] + 2
        assert _alpha_max(rest, eyebrow_zone) == 255
        assert rest.getpixel((W // 2, 0))[3] == round(255 * DOCLINE["rest_alpha"])

    def test_without_a_topic_the_rule_alone_opens_the_line(self, tmp_path):
        made = create_docline_frames(HOOK, "", W, H, str(tmp_path), seconds=1.0, total=3.0,
                                     cfg={"keep_eyebrow": True})
        rest = Image.open(made["rest"])
        y = int(H * DOCLINE["top"])
        left = int(W * DOCLINE["left"])
        assert rest.getpixel((left + 2, y + 1))[:3] == (255, 255, 255)

    def test_each_state_is_written_once_however_long_it_lasts(self, tmp_path):
        made = create_docline_frames(HOOK, "Psychology", W, H, str(tmp_path), seconds=3.3, total=30.0)
        pngs = {p for p, _ in made["segments"]}
        # About 30 moving states (veil 5, rule 11, title 12, exit 6) for a 30 s clip.
        assert len(os.listdir(tmp_path)) == len(pngs) < 45


class TestQuiet:
    """A kept eyebrow steps aside for the B-roll cards drawn above the head."""

    def _make(self, tmp_path, quiet):
        return create_docline_frames(HOOK, "Psychology", W, H, str(tmp_path), seconds=1.0,
                                     quiet=quiet, total=20.0, cfg={"keep_eyebrow": True})

    def _clear(self, made, t):
        img = _at(made, t)
        return _alpha_max(img, (0, 0, W, img.size[1])) == 0

    def test_gone_during_a_card_and_back_after(self, tmp_path):
        made = self._make(tmp_path, [(5.0, 8.0)])
        assert hooks.docline_frame_at(made, 4.5) == made["rest"]
        assert self._clear(made, 5.2) and self._clear(made, 7.9)
        fading = _at(made, 5.0 - DOCLINE["quiet_lead"] + DOCLINE["quiet_out"] / 2)
        assert 0 < _alpha_max(fading, (0, 0, W, fading.size[1])) < 255
        assert hooks.docline_frame_at(made, 8.0 + DOCLINE["quiet_in"] + 0.05) == made["rest"]

    def test_two_close_cards_keep_it_hidden_between(self, tmp_path):
        made = self._make(tmp_path, [(5.0, 7.0), (7.2, 9.0)])
        assert self._clear(made, 7.1)

    def test_far_apart_cards_let_it_come_back_between(self, tmp_path):
        made = self._make(tmp_path, [(5.0, 7.0), (12.0, 14.0)])
        assert hooks.docline_frame_at(made, 9.5) == made["rest"]
        assert self._clear(made, 13.0)

    def test_no_card_no_gap(self, tmp_path):
        made = self._make(tmp_path, [])
        assert hooks.docline_frame_at(made, 15.0) == made["rest"]
        assert [p for p, _ in made["segments"]].count(made["rest"]) == 1

    def test_only_the_cards_above_the_head_count(self):
        items = [{"t": 5, "dur": 3, "layout": "card"}, {"t": 10, "dur": 3, "layout": "hero"},
                 {"t": 15, "dur": 2, "layout": "rise"}, "junk", {"layout": "card"}]
        assert hooks.docline_quiet(items) == [(5.0, 8.0)]
        assert hooks.docline_quiet(None) == []


class TestConcat:
    def test_the_script_lists_every_state_and_repeats_the_last(self, tmp_path):
        made = create_docline_frames(HOOK, "Psychology", W, H, str(tmp_path), seconds=1.0, total=4.0)
        path = hooks.write_docline_concat(made, str(tmp_path / "t.ffconcat"))
        rows = open(path, encoding="utf-8").read().splitlines()
        assert rows[0] == "ffconcat version 1.0"
        files = [r for r in rows if r.startswith("file ")]
        durs = [float(r.split()[1]) for r in rows if r.startswith("duration ")]
        assert len(files) == len(made["segments"]) + 1 and files[-1] == files[-2]
        assert abs(sum(durs) - 5.0) < 1e-3
        # Names relative to the script, which sits next to the PNGs.
        assert all("/" not in f and "\\" not in f for f in files)

    def test_the_graph_stops_with_the_picture(self):
        assert docline_graph() == "[1:v]format=rgba[h];[0:v][h]overlay=0:0:shortest=1[v]"


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
