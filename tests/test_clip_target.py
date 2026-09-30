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
