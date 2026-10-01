"""Target clip length (selection.clip_target -> CLIP_TARGET_MIN/MAX_SECONDS).

JRE #2515 came back as 11 clips of 37-59 s in a 15-60 s band: the prompt said
"length is a ceiling" and nothing held it to that. The target is asked for in
the prompt, then an over-long clip is cut back to the sentence of its payoff."""
import pytest

from clip_selection import clip_target_bounds, duration_summary

main = pytest.importorskip("main")
from test_selection_pipeline import clip, run  # noqa: E402,F401  (run is a fixture)

FILL = "it happens to people every day without them knowing. "          # 9 words = 4.5 s
PAYOFF = "that is the scary part of it."                                 # 7 words = 3.5 s


def mk(text):
    return [{"w": w, "s": i * 0.5, "e": i * 0.5 + 0.4} for i, w in enumerate(text.split())]


def dur(c):
    return c["end"] - c["start"]


class TestBounds:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("CLIP_TARGET_MAX_SECONDS", raising=False)
        monkeypatch.delenv("CLIP_TARGET_MIN_SECONDS", raising=False)
        assert clip_target_bounds() is None

    def test_reads_the_env_inside_the_band(self, monkeypatch):
        monkeypatch.setenv("CLIP_MIN_SECONDS", "15")
        monkeypatch.setenv("CLIP_MAX_SECONDS", "60")
        monkeypatch.setenv("CLIP_TARGET_MIN_SECONDS", "25")
        monkeypatch.setenv("CLIP_TARGET_MAX_SECONDS", "40")
        assert clip_target_bounds() == (25.0, 40.0)
        monkeypatch.setenv("CLIP_TARGET_MIN_SECONDS", "5")      # below the band: clamped
        assert clip_target_bounds() == (15.0, 40.0)
        monkeypatch.delenv("CLIP_TARGET_MIN_SECONDS")
        assert clip_target_bounds() == (15.0, 40.0)

    def test_a_target_at_the_maximum_is_no_target(self, monkeypatch):
        monkeypatch.setenv("CLIP_MAX_SECONDS", "60")
        monkeypatch.setenv("CLIP_TARGET_MAX_SECONDS", "60")
        assert clip_target_bounds() is None
        monkeypatch.setenv("CLIP_TARGET_MAX_SECONDS", "garbage")
        assert clip_target_bounds() is None

    def test_summary_line(self):
        shorts = [{"start": 0, "end": 30}, {"start": 0, "end": 50}, {"start": 0, "end": 20}]
        line = duration_summary(shorts, (25, 40))
        assert "3 clip(s), 20-50s, median 30s, mean 33s" in line
        assert "target 25-40s: 1 inside, 1 over, 1 under" in line
        assert "target" not in duration_summary(shorts)
        assert duration_summary([]) == "no clips"


class TestTrimToTarget:
    W = mk(FILL * 4 + PAYOFF + " " + FILL * 10)          # payoff said from 18.0 to 21.4 s

    def test_cut_on_the_first_sentence_end_past_the_payoff_that_reaches_the_target(self):
        c = {"start": 0.0, "end": 58.0, "punchline": PAYOFF}
        assert main.trim_to_target(c, self.W, 15, (25, 40)) is True
        assert c["end_fit_for_target"] and 25 <= dur(c) <= 40, c
        last = max(i for i, w in enumerate(self.W) if w["e"] <= c["end"])
        assert self.W[last]["w"].endswith("."), "the new end is a sentence end"
        assert dur(c) < 27, "the first one that reaches 25 s, not the last one under 40 s"

    def test_a_late_payoff_is_kept_whole_even_over_the_target(self):
        w = mk(FILL * 9 + PAYOFF + " " + FILL * 4)        # payoff from 40.5 to 43.9 s
        c = {"start": 0.0, "end": 58.0, "punchline": PAYOFF}
        assert main.trim_to_target(c, w, 15, (25, 40)) is True
        assert 43.9 < c["end"] < 44.5 and "over_target" not in c, c

    def test_a_clip_that_ends_on_its_payoff_keeps_its_length(self):
        w = mk(FILL * 11 + PAYOFF + " " + FILL * 3)       # payoff from 49.5 to 52.9 s
        c = {"start": 0.0, "end": 53.0, "punchline": PAYOFF}
        assert main.trim_to_target(c, w, 15, (25, 40)) is False
        assert c["end"] == 53.0 and c["over_target"] == "payoff needs the length"

    def test_never_cuts_without_a_located_payoff(self):
        for punchline in ("", None, "words nobody said in this transcript"):
            c = {"start": 0.0, "end": 58.0, "punchline": punchline}
            assert main.trim_to_target(c, self.W, 15, (25, 40)) is False
            assert c["end"] == 58.0 and c["over_target"] == "payoff not located"

    def test_a_clip_inside_the_target_is_untouched(self):
        c = {"start": 0.0, "end": 38.0, "punchline": PAYOFF}
        assert main.trim_to_target(c, self.W, 15, (25, 40)) is False
        assert c == {"start": 0.0, "end": 38.0, "punchline": PAYOFF}

    def test_pauses_end_a_sentence_on_an_unpunctuated_transcript(self):
        text = (FILL * 4 + PAYOFF + " " + FILL * 10).replace(".", "")
        w = mk(text)
        for x in w[52:]:                                   # a 1 s pause 26 s in
            x["s"] += 1.0
            x["e"] += 1.0
        c = {"start": 0.0, "end": 58.0, "punchline": PAYOFF.replace(".", "")}
        assert main.trim_to_target(dict(c), w, 15, (25, 40)) is False, "no full stop: nothing to cut on"
        assert main.trim_to_target(c, w, 15, (25, 40), pauses=True) is True
        assert w[51]["e"] < c["end"] < w[52]["s"]


class TestPrompt:
    def test_rules_text(self):
        assert main.target_length_rules(None, 15, 60) == ""
        rules = main.target_length_rules((25, 40), 15, 60)
        assert "aim for 25-40" in rules and "15-60s stays the hard limit" in rules
        assert "punchline" not in rules
        assert "`punchline`" in main.target_length_rules((25, 40), 15, 60, payoff=True)

    def test_off_means_the_same_prompt_byte_for_byte(self, run, monkeypatch):
        run([clip(100.0, 140.0)])
        off = run.prompts["detail"][-1]
        assert "TARGET LENGTH" not in off
        monkeypatch.setenv("CLIP_TARGET_MIN_SECONDS", "25")
        monkeypatch.setenv("CLIP_TARGET_MAX_SECONDS", "40")
        run([clip(100.0, 140.0)])
        on = run.prompts["detail"][-1]
        rules = main.target_length_rules((25.0, 40.0), 15.0, 60.0)
        assert rules in on and on.replace(rules, "") == off


class TestPipeline:
    def test_playbook_clip_is_cut_back_after_its_payoff(self, run, monkeypatch, capsys):
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        monkeypatch.setenv("CLEAN_END", "1")
        monkeypatch.setenv("CLIP_TARGET_MIN_SECONDS", "25")
        monkeypatch.setenv("CLIP_TARGET_MAX_SECONDS", "40")
        # The pipeline transcript is one sentence repeated: its first
        # occurrence in the clip is the "payoff".
        shorts = run([clip(99.0, 157.5, hook_line="", punchline="it happens to people every day without them knowing.")])
        assert len(shorts) == 1 and shorts[0]["end_fit_for_target"]
        assert 25 <= dur(shorts[0]) <= 40
        out = capsys.readouterr().out
        assert "Target length: 1/1" in out and "Clip lengths: 1 clip(s)" in out
        assert "`punchline`" in run.prompts["detail"][-1]

    def test_without_a_target_the_clip_keeps_its_length(self, run, monkeypatch):
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        monkeypatch.setenv("CLEAN_END", "1")
        shorts = run([clip(99.0, 157.5, hook_line="", punchline="it happens to people every day without them knowing.")])
        assert dur(shorts[0]) > 50 and "end_fit_for_target" not in shorts[0]


# --- open later: the clips that end on their payoff and still run long ---------------
# JRE #2515 (1-oct-2026): 5 clips of 6 came back at 50-55 s with the target
# asked for; trim_to_target could cut none ("payoff needs the length"). The
# only cut left is a later opening, chosen by the model among the sentence
# starts the code measured to land inside the target.

def _twelve_sentences():
    """12 sentences of 10 words (5 s each): a 60 s clip ending on sentence 12."""
    text = " ".join(f"s{j} one two three four five six seven eight end." for j in range(1, 13))
    return mk(text)


class TestOpenLaterCandidates:
    def test_sentence_starts_that_leave_the_target_to_the_end(self):
        w = _twelve_sentences()
        c = {"start": 0.0, "end": 60.0, "punchline": "s12 one two three four five six seven eight end."}
        cands = main.open_later_candidates(c, w, 15, (25, 40))
        assert [(k, left) for k, left, _ in cands] == [(50, 35.1), (60, 30.1), (70, 25.1)]
        assert cands[0][2] == "s6 one two three four five six seven eight end."
        for k, left, _ in cands:
            assert 25 <= 60.0 - (w[k]["s"] - 0.08) <= 40

    def test_filler_is_stepped_over_and_mid_sentence_starts_are_not_offered(self):
        w = _twelve_sentences()
        w[60]["w"] = "so"                                    # sentence 7 opens on a filler
        cands = main.open_later_candidates({"start": 0.0, "end": 60.0}, w, 15, (25, 40))
        assert [k for k, _, _ in cands] == [50, 61, 70]
        assert cands[1][2].startswith("one two")

    def test_an_unpunctuated_clip_without_pauses_has_no_candidate(self):
        w = mk(" ".join("word" for _ in range(120)))
        assert main.open_later_candidates({"start": 0.0, "end": 60.0}, w, 15, (25, 40)) == []

    def test_rules_say_to_open_later(self):
        rules = main.target_length_rules((25.0, 40.0), 15.0, 60.0)
        assert "open LATER" in rules and "never earlier" in rules
        assert "25s is a floor as much as 40s is a" in rules and "ceiling" in rules


class TestShortenToTarget:
    PAYOFF = "s12 one two three four five six seven eight end."

    def _shorts(self):
        return [{"start": 0.0, "end": 60.0, "punchline": self.PAYOFF, "over_target": "payoff needs the length",
                 "video_title_for_youtube_short": "Can a long clip open later?", "viral_hook_text": "Old hook here.",
                 "hook_line": "s1 one two three four five six seven eight end.", "hook_aligned": True},
                {"start": 100.0, "end": 130.0, "punchline": "x", "video_title_for_youtube_short": "Is this fine?"}]

    def test_the_pick_moves_the_start_the_hook_line_and_the_hook(self, capsys):
        w = _twelve_sentences()
        shorts, prompts = self._shorts(), []

        def ask(prompt):
            prompts.append(prompt)
            return {"clips": [{"id": 0, "open_on": 2, "viral_hook_text": "Psilocybin  melts the self."}]}

        assert main.shorten_to_target(shorts, w, 15, (25, 40), "en", ask=ask) == 1
        c = shorts[0]
        assert c["start"] == 29.92 and c["end"] == 60.0 and 25 <= dur(c) <= 40
        assert c["hook_line"].startswith("s7 one") and c["hook_aligned"] and c["start_fit_for_target"]
        assert "over_target" not in c
        assert c["viral_hook_text"] == "Psilocybin melts the self." and c["hook_before_open_later"] == "Old hook here."
        assert len(prompts) == 1
        assert '"seconds_left": 30.1' in prompts[0] and "Can a long clip open later?" in prompts[0]
        assert "Is this fine?" not in prompts[0], "a clip inside the target is not sent"
        assert "8 words, in en" in prompts[0]
        assert shorts[1] == self._shorts()[1]
        out = capsys.readouterr().out
        assert "60s -> 30s (opens later" in out and "+ new hook" in out and "Open later: 1/1" in out

    def test_an_empty_hook_keeps_the_old_one(self):
        w = _twelve_sentences()
        shorts = self._shorts()
        main.shorten_to_target(shorts, w, 15, (25, 40), ask=lambda p: {"clips": [{"id": 0, "open_on": 1}]})
        assert shorts[0]["start"] == 24.92 and shorts[0]["viral_hook_text"] == "Old hook here."
        assert "hook_before_open_later" not in shorts[0]

    def test_a_bad_pick_a_malformed_answer_or_a_failure_keeps_the_clip(self, capsys):
        w = _twelve_sentences()
        for answer in ({"clips": [{"id": 0, "open_on": 9}]}, {"clips": [{"id": 0, "open_on": 0}]}, {}, None,
                       {"clips": [{"id": "zero", "open_on": 1}, "x"]}):
            shorts = self._shorts()
            assert main.shorten_to_target(shorts, w, 15, (25, 40), ask=lambda p, a=answer: a) == 0
            assert shorts[0]["start"] == 0.0 and shorts[0]["hook_line"].startswith("s1 ")
            assert shorts[0]["over_target"].endswith("no usable later opening picked")
        shorts = self._shorts()

        def ask(prompt):
            raise RuntimeError("model down")

        assert main.shorten_to_target(shorts, w, 15, (25, 40), ask=ask) == 0
        assert shorts[0]["start"] == 0.0 and shorts[0]["over_target"] == "payoff needs the length"
        assert "Open later: the call failed" in capsys.readouterr().out

    def test_no_candidate_means_no_call(self):
        w = mk(" ".join("word" for _ in range(120)))
        shorts = self._shorts()

        def ask(prompt):
            raise AssertionError("no call expected")

        assert main.shorten_to_target(shorts, w, 15, (25, 40), ask=ask) == 0
        assert shorts[0]["over_target"].endswith("no sentence start leaves it inside the target")

    def test_nothing_over_the_target_means_no_call(self):
        def ask(prompt):
            raise AssertionError("no call expected")
        assert main.shorten_to_target([self._shorts()[1]], _twelve_sentences(), 15, (25, 40), ask=ask) == 0

    def test_a_located_punchline_time_follows_the_start(self):
        w = _twelve_sentences()
        shorts = self._shorts()
        shorts[0]["punchline_time"] = 55.0
        main.shorten_to_target(shorts, w, 15, (25, 40), ask=lambda p: {"clips": [{"id": 0, "open_on": 1}]})
        assert shorts[0]["punchline_time"] == 30.08


class TestOpenLaterPipeline:
    def test_a_clip_whose_payoff_is_not_located_opens_later(self, run, monkeypatch, capsys):
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        monkeypatch.setenv("CLEAN_END", "1")
        monkeypatch.setenv("CLIP_TARGET_MIN_SECONDS", "25")
        monkeypatch.setenv("CLIP_TARGET_MAX_SECONDS", "40")
        asked = []

        def ask(prompt):
            asked.append(prompt)
            return {"clips": [{"id": 0, "open_on": 1, "viral_hook_text": ""}]}

        monkeypatch.setattr(main, "_ask_open_later", ask)
        shorts = run([clip(99.0, 157.5, hook_line="", punchline="words nobody said in this transcript")])
        assert len(asked) == 1 and len(shorts) == 1
        assert shorts[0]["start_fit_for_target"] and 25 <= dur(shorts[0]) <= 41
        out = capsys.readouterr().out
        assert "Target length: 0/1" in out and "Open later: 1/1" in out

    def test_without_the_playbook_no_later_opening(self, run, monkeypatch):
        monkeypatch.setenv("CLIP_TARGET_MIN_SECONDS", "25")
        monkeypatch.setenv("CLIP_TARGET_MAX_SECONDS", "40")

        def ask(prompt):
            raise AssertionError("no call expected")

        monkeypatch.setattr(main, "_ask_open_later", ask)
        shorts = run([clip(99.0, 157.5, hook_line="", punchline="words nobody said in this transcript")])
        assert len(shorts) == 1 and "start_fit_for_target" not in shorts[0]
