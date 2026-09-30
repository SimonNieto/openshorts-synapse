"""Tests for the pure clip-selection helpers (windows, snapping, pricing)."""
import re

import pytest

from clip_selection import (
    build_transcript_windows,
    clip_count_targets,
    clip_dedupe_settings,
    clips_overlap,
    dedupe_overlapping,
    snap_clip_to_words,
    compact_words,
    lookup_model_prices,
    trim_to_best,
)


def _seg(start, end, text):
    return {"start": start, "end": end, "text": text}


def _word(w, s, e):
    return {"w": w, "s": s, "e": e}


class TestBuildTranscriptWindows:
    def test_windows_align_to_segment_boundaries(self):
        transcript = {"segments": [
            _seg(0, 40, "a"), _seg(40, 80, "b"), _seg(80, 100, "c"), _seg(100, 150, "d"),
        ]}
        windows = build_transcript_windows(transcript, 150, window_seconds=90, overlap_seconds=30)
        segment_edges = {0, 40, 80, 100, 150}
        for w in windows:
            assert w["start"] in segment_edges
            assert w["end"] in segment_edges

    def test_windows_overlap(self):
        transcript = {"segments": [_seg(i * 10, (i + 1) * 10, f"s{i}") for i in range(30)]}
        windows = build_transcript_windows(transcript, 300, window_seconds=90, overlap_seconds=30)
        assert len(windows) >= 3
        for prev, nxt in zip(windows, windows[1:]):
            # next window starts before the previous one ends (overlap)
            assert nxt["start"] < prev["end"]
        # full coverage to the end
        assert windows[-1]["end"] == 300

    def test_empty_transcript_falls_back_to_full_video(self):
        windows = build_transcript_windows({"segments": []}, 120)
        assert len(windows) == 1
        assert windows[0]["start"] == 0.0
        assert windows[0]["end"] == 120

    def test_always_progresses(self):
        # One giant segment must not loop forever
        transcript = {"segments": [_seg(0, 500, "long monolog")]}
        windows = build_transcript_windows(transcript, 500, window_seconds=90, overlap_seconds=30)
        assert len(windows) == 1


class TestSnapClipToWords:
    def _words(self):
        # words every ~2s with 0.4s gaps: [0,1.6], [2,3.6], [4,5.6], ...
        return [_word(f"w{i}", i * 2.0, i * 2.0 + 1.6) for i in range(40)]

    def test_start_snaps_into_silence_before_word(self):
        words = self._words()
        # Gemini proposes 10.3 — nearest word start is 10.0, gap before is 9.6->10.0
        start, end = snap_clip_to_words(10.3, 30.1, words, 80.0)
        assert 9.8 <= start <= 10.0  # word start minus half-gap lead
        # end 30.1 -> nearest word end 29.6 plus tail
        assert 29.6 <= end <= 30.05

    def test_no_words_nearby_keeps_original(self):
        words = [_word("far", 200.0, 201.0)]
        assert snap_clip_to_words(10.0, 40.0, words, 300.0) == (10.0, 40.0)

    def test_empty_words_keeps_original(self):
        assert snap_clip_to_words(5.0, 25.0, [], 100.0) == (5.0, 25.0)

    def test_duration_repaired_to_minimum(self):
        words = self._words()
        # snapping would yield ~14.4s; must be extended to >= 15s on a word end
        start, end = snap_clip_to_words(10.0, 24.5, words, 80.0)
        assert end - start >= 15.0

    def test_duration_capped_at_maximum(self):
        words = self._words()
        start, end = snap_clip_to_words(0.0, 59.9, words, 80.0)
        assert end - start <= 60.0


class TestPricing:
    def test_known_models(self):
        assert lookup_model_prices("gemini-2.5-flash") == (0.30, 2.50)
        assert lookup_model_prices("gemini-3-flash-preview") == (0.50, 3.00)

    def test_prefix_match_with_suffix(self):
        assert lookup_model_prices("gemini-2.5-flash-002") == (0.30, 2.50)

    def test_unknown_model_returns_none(self):
        assert lookup_model_prices("gpt-9-mega") is None
        assert lookup_model_prices(None) is None


class TestCompactWords:
    def test_rounds_timestamps(self):
        words = [{"w": " hi", "s": 17.240000000000002, "e": 17.899999999999999}]
        assert compact_words(words) == [{"w": " hi", "s": 17.24, "e": 17.9}]


class TestClipCountTargets:
    """The floor is the whole point: prod was delivering a single clip on the
    mode, and users who got 1-3 came back 0.4% of the time against 16% for 4-9.
    """

    def test_floor_clears_the_dead_zone_once_there_is_material(self):
        # 4+ shortlisted windows must not be allowed to return the 1-3 band.
        for n in (4, 5, 6, 8, 10):
            low, high = clip_count_targets(n)
            assert low >= 4, f"{n} windows asked for only {low}"
            assert high >= low

    def test_tiny_shortlists_stay_modest(self):
        assert clip_count_targets(1)[0] <= 2
        assert clip_count_targets(2)[0] <= 3

    def test_ceiling_is_capped_so_long_videos_do_not_explode(self):
        assert clip_count_targets(40) == clip_count_targets(12)
        assert clip_count_targets(40)[1] <= 12

    def test_low_never_exceeds_high(self):
        for n in range(1, 40):
            low, high = clip_count_targets(n)
            assert low <= high

    def test_degenerate_input_does_not_crash(self):
        assert clip_count_targets(0)[0] >= 1
        assert clip_count_targets(None)[0] >= 1

    def test_env_overrides_for_ab_runs(self, monkeypatch):
        monkeypatch.setenv("CLIP_TARGET_MIN", "1")
        monkeypatch.setenv("CLIP_TARGET_MAX", "2")
        assert clip_count_targets(5) == (1, 2)

    def test_garbage_env_falls_back_to_computed(self, monkeypatch):
        baseline = clip_count_targets(5)
        monkeypatch.setenv("CLIP_TARGET_MIN", "not-a-number")
        assert clip_count_targets(5) == baseline

    def test_override_min_above_max_still_orders(self, monkeypatch):
        monkeypatch.setenv("CLIP_TARGET_MIN", "9")
        monkeypatch.setenv("CLIP_TARGET_MAX", "3")
        low, high = clip_count_targets(5)
        assert low <= high


class TestDetailPromptCarriesTheCount:
    def test_template_formats_with_the_targets(self):
        gw = pytest.importorskip("gemini_worker")
        low, high = clip_count_targets(5)
        prompt = gw.DETAIL_PROMPT_TEMPLATE.format(
            video_duration=300, language="es", min_clips=low, max_clips=high,
            min_secs=15.0, max_secs=60.0, windows_json="[]")
        assert f"return {low} to {high} clips" in prompt
        assert "15 to 60 seconds" in prompt
        # The JSON schema example legitimately keeps braces (they are {{ }} in
        # the template), so assert on unsubstituted placeholders specifically.
        assert re.findall(r"\{[a-z_]+\}", prompt) == []


class TestTrimToBest:
    """The detail pass returns clips in transcript order. Slicing that list
    kept the earliest ones and dropped the back of the video — measured on a
    9m19s walkthrough whose clips all landed inside the first 2m40s."""

    @staticmethod
    def _clip(start, score):
        return {"start": start, "end": start + 20, "predicted_score": score}

    def test_keeps_the_best_scoring_not_the_earliest(self):
        shorts = [self._clip(0, 60), self._clip(30, 55),
                  self._clip(300, 90), self._clip(400, 85)]
        kept = trim_to_best(shorts, 2)
        assert [c["start"] for c in kept] == [300, 400]

    def test_survivors_come_back_in_transcript_order(self):
        shorts = [self._clip(0, 99), self._clip(100, 10),
                  self._clip(200, 80), self._clip(300, 90)]
        kept = trim_to_best(shorts, 3)
        assert [c["start"] for c in kept] == [0, 200, 300]

    def test_a_short_list_is_untouched(self):
        shorts = [self._clip(0, 10), self._clip(50, 20)]
        assert trim_to_best(shorts, 5) == shorts
        assert trim_to_best(shorts, 2) == shorts

    def test_the_whole_video_stays_reachable(self):
        # The regression in one line: 16 clips spread over 9 minutes, trimmed
        # to 8. A positional slice ends at 3:30; by score the tail survives.
        shorts = [self._clip(i * 35, 50 + (i % 4) * 10) for i in range(16)]
        kept = trim_to_best(shorts, 8)
        assert max(c["start"] for c in kept) > 8 * 35

    def test_ties_keep_transcript_order(self):
        shorts = [self._clip(0, 70), self._clip(100, 70), self._clip(200, 70)]
        assert [c["start"] for c in trim_to_best(shorts, 2)] == [0, 100]

    def test_a_missing_or_bad_score_does_not_raise(self):
        shorts = [{"start": 0, "end": 20},
                  {"start": 100, "end": 120, "predicted_score": None},
                  {"start": 200, "end": 220, "predicted_score": "x"},
                  self._clip(300, 40)]
        kept = trim_to_best(shorts, 2)
        assert len(kept) == 2
        assert kept[-1]["start"] == 300      # the only real score survives

    def test_max_clips_is_never_below_one(self):
        shorts = [self._clip(0, 10), self._clip(50, 20)]
        assert len(trim_to_best(shorts, 0)) == 1


class TestDedupeOverlapping:
    """Two neighbouring scoring windows each returned a clip over the same
    seconds (JRE #2515, Chase Hughes-001): 1926.9-1985.1 and 1968.3-2026.5."""

    A = {"start": 1926.9, "end": 1985.1, "predicted_score": 75, "hook_line": "I described it as control alt delete."}
    B = {"start": 1968.3, "end": 2026.5, "predicted_score": 73, "hook_line": "I think separation is the lie."}

    def test_the_real_pair_keeps_the_best_score(self):
        kept, dropped = dedupe_overlapping([self.A, self.B])
        assert kept == [self.A]
        assert dropped[0][0] is self.B and dropped[0][1] is self.A
        assert "16.8s in common" in dropped[0][2]

    def test_the_real_pair_shares_less_than_30_percent(self):
        # 16.8 s of 58.2 s = 29 %: a 30 % share alone would let it through,
        # which is why the default is 20 % of the shorter clip OR 8 s.
        assert clips_overlap(self.A, self.B, max_share=0.3, max_seconds=0) == ""
        assert clips_overlap(self.A, self.B, max_share=0.3, max_seconds=8)
        assert clips_overlap(self.A, self.B, max_share=0.2, max_seconds=0)

    def test_best_score_wins_whatever_the_order(self):
        better_b = {**self.B, "predicted_score": 90}
        kept, dropped = dedupe_overlapping([self.A, better_b])
        assert kept == [better_b] and dropped[0][0] is self.A

    def test_a_tie_keeps_the_earlier_clip(self):
        tie_b = {**self.B, "predicted_score": 75}
        assert dedupe_overlapping([self.A, tie_b])[0] == [self.A]

    def test_a_few_shared_seconds_are_not_a_duplicate(self):
        a = {"start": 100.0, "end": 140.0, "predicted_score": 70}
        b = {"start": 137.0, "end": 180.0, "predicted_score": 80}   # 3 s = 7.5 %
        kept, dropped = dedupe_overlapping([a, b])
        assert kept == [a, b] and dropped == []

    def test_share_is_of_the_shorter_clip(self):
        long_ = {"start": 0.0, "end": 60.0, "predicted_score": 80}
        short = {"start": 54.0, "end": 74.0, "predicted_score": 70}  # 6 s = 30 % of 20 s, 10 % of 60 s
        assert dedupe_overlapping([long_, short])[0] == [long_]

    def test_same_hook_line_is_a_duplicate_even_far_apart(self):
        a = {"start": 10.0, "end": 40.0, "predicted_score": 60, "hook_line": "Your brain can lie to you."}
        b = {"start": 900.0, "end": 930.0, "predicted_score": 80, "hook_line": "your brain can lie to you"}
        kept, dropped = dedupe_overlapping([a, b])
        assert kept == [b] and dropped[0][2] == "same hook line"

    def test_empty_or_tiny_hook_lines_never_match(self):
        a = {"start": 10.0, "end": 40.0, "hook_line": ""}
        b = {"start": 100.0, "end": 140.0, "hook_line": ""}
        c = {"start": 200.0, "end": 240.0, "hook_line": "Oh yeah."}
        d = {"start": 300.0, "end": 340.0, "hook_line": "Oh yeah."}
        assert dedupe_overlapping([a, b, c, d])[0] == [a, b, c, d]

    def test_survivors_keep_their_order_and_three_way_chains_resolve(self):
        a = {"start": 0.0, "end": 40.0, "predicted_score": 70}
        b = {"start": 20.0, "end": 60.0, "predicted_score": 90}
        c = {"start": 50.0, "end": 90.0, "predicted_score": 80}     # overlaps b (10 s), not a
        far = {"start": 500.0, "end": 530.0, "predicted_score": 10}
        kept, dropped = dedupe_overlapping([a, b, c, far])
        assert kept == [b, far] and len(dropped) == 2

    def test_a_clip_without_times_is_left_alone(self):
        odd = {"predicted_score": 50}
        assert dedupe_overlapping([self.A, odd])[0] == [self.A, odd]

    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("CLIP_DEDUPE_OVERLAP", raising=False)
        assert clip_dedupe_settings() is None
        monkeypatch.setenv("CLIP_DEDUPE_OVERLAP", "0")
        assert clip_dedupe_settings() is None
        monkeypatch.setenv("CLIP_DEDUPE_OVERLAP", "garbage")
        assert clip_dedupe_settings() is None

    def test_settings_from_env(self, monkeypatch):
        monkeypatch.setenv("CLIP_DEDUPE_OVERLAP", "0.2")
        monkeypatch.delenv("CLIP_DEDUPE_SECONDS", raising=False)
        assert clip_dedupe_settings() == (0.2, 8.0)
        monkeypatch.setenv("CLIP_DEDUPE_OVERLAP", "30")           # a percentage
        monkeypatch.setenv("CLIP_DEDUPE_SECONDS", "0")
        assert clip_dedupe_settings() == (0.3, 0.0)
