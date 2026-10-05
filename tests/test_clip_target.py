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

    def test_cut_right_after_the_payoff(self):
        # 5-oct-2026 (« finir sur la chute »): right after the payoff, the
        # format's minimum (15 s) as the only floor — before, the first
        # sentence end that reached the target's low end (25 s).
        c = {"start": 0.0, "end": 58.0, "punchline": PAYOFF}
        assert main.trim_to_target(c, self.W, 15, (25, 40)) is True
        assert c["end_fit_for_target"] and c["end_on_payoff"] and c["clean_end"] == "payoff", c
        assert 21.4 < c["end"] <= 21.5, "the cut sits right after the payoff's last word"
        assert "over_target" not in c

    def test_the_format_minimum_holds(self):
        w = mk(FILL + PAYOFF + " " + FILL * 10)          # payoff from 4.5 to 7.9 s
        c = {"start": 0.0, "end": 58.0, "punchline": PAYOFF}
        assert main.trim_to_target(c, w, 15, (25, 40)) is True
        assert 15 <= dur(c) < 17, "on to the first sentence end that keeps 15 s"
        last = max(i for i, x in enumerate(w) if x["e"] <= c["end"])
        assert w[last]["w"].endswith("."), "the new end is a sentence end"

    def test_a_late_payoff_is_kept_whole_even_over_the_target(self):
        w = mk(FILL * 9 + PAYOFF + " " + FILL * 4)        # payoff from 40.5 to 43.9 s
        c = {"start": 0.0, "end": 58.0, "punchline": PAYOFF}
        assert main.trim_to_target(c, w, 15, (25, 40)) is True
        assert 43.9 < c["end"] < 44.5, c
        assert c["over_target"] == "payoff needs the length", "still over: shorten_to_target opens it later"

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

    def test_a_clip_inside_the_target_ends_on_its_payoff_too(self):
        # 5-oct-2026: every clip, not only the ones over the target.
        c = {"start": 0.0, "end": 38.0, "punchline": PAYOFF}
        assert main.trim_to_target(c, self.W, 15, (25, 40)) is True
        assert 21.4 < c["end"] <= 21.5 and "end_fit_for_target" not in c and c["end_on_payoff"], c

    def test_a_clip_already_ending_on_its_payoff_is_untouched(self):
        c = {"start": 0.0, "end": 21.45, "punchline": PAYOFF}
        assert main.trim_to_target(c, self.W, 15, (25, 40)) is False
        assert c["end"] == 21.45 and c["end_on_payoff"] and "over_target" not in c

    def test_without_a_target_nothing_is_over_it(self):
        c = {"start": 0.0, "end": 58.0, "punchline": PAYOFF}
        assert main.trim_to_target(c, self.W, 15) is True
        assert 21.4 < c["end"] <= 21.5 and "over_target" not in c and "end_fit_for_target" not in c

    def test_pauses_end_a_sentence_on_an_unpunctuated_transcript(self):
        text = (FILL * 4 + PAYOFF + " " + FILL * 10).replace(".", "")
        w = mk(text)
        for x in w[45:]:                                   # a 1 s pause 22.5 s in, 1 s after the payoff
            x["s"] += 1.0
            x["e"] += 1.0
        c = {"start": 0.0, "end": 58.0, "punchline": PAYOFF.replace(".", "")}
        assert main.trim_to_target(dict(c), w, 15, (25, 40)) is False, "no full stop: nothing to cut on"
        assert main.trim_to_target(c, w, 15, (25, 40), pauses=True) is True
        assert w[44]["e"] < c["end"] < w[45]["s"], "the pause that closes the payoff's sentence"

    def test_unpunctuated_without_a_pause_the_payoff_word_ends_it(self):
        # JRE #2553 c05: "...it should scare the shit out of them it says the
        # clinical trials..." — no full stop, no pause: the payoff ends it.
        w = mk((FILL * 4 + PAYOFF + " " + FILL * 10).replace(".", ""))
        c = {"start": 0.0, "end": 58.0, "punchline": PAYOFF.replace(".", "")}
        assert main.trim_to_target(c, w, 15, (25, 40), pauses=True) is True
        assert 21.4 < c["end"] <= 21.5, c


# --- the payoff always in the clip, the clip ends on it (5-oct-2026) -----------------------
# JRE #2553-004 (job b8e46c24), the real numbers: the model's cut (cached answer) and
# Whisper's words around it, copied from the job's metadata.

def _w(spec):
    """'word:start:end ...' (absolute seconds) -> words."""
    out = []
    for tok in spec.split():
        w, s, e = tok.rsplit(":", 2)
        out.append({"w": w, "s": float(s), "e": float(e)})
    return out


# Whisper's words of the source, 386-410 s (the clip opens at 368.62 s).
C09_WORDS = _w(
    "It's:386.06:386.30 going:386.30:386.40 to:386.40:386.46 be:386.46:386.54 a:386.54:386.62 "
    "very:386.62:386.80 interesting:386.80:387.16 "
    "tool.:387.16:387.48 And:388.32:388.80 the:388.80:389.28 neurosurgery:389.28:390.10 and:390.10:390.24 "
    "other:390.24:390.38 communities:390.38:390.88 like:390.88:391.46 dogpiled:391.46:392.32 me,:392.32:392.52 "
    "like:392.68:393.08 we,:393.08:393.20 this:393.32:393.60 is:393.60:393.72 terrible,:393.72:394.12 "
    "this:394.26:394.36 is:394.36:394.46 terrible.:394.46:394.68 You:394.76:394.88 know:394.88:394.96 "
    "who:394.96:395.08 didn't:395.08:395.38 dogpile:395.38:395.84 me?:395.84:396.00 Were:396.14:396.60 "
    "the:396.60:396.80 dozens:396.80:397.74 of:397.74:397.98 dermatologists:397.98:398.82 and:398.82:399.00 "
    "ophthalmologists:399.00:399.74 saying,:399.74:400.06 we:400.24:400.74 think:400.74:401.08 "
    "scans:401.08:401.96 and:401.96:402.50 more:402.50:402.72 data:402.72:402.96 are:402.96:403.20 "
    "great.:403.20:403.62 The:403.80:404.10 ophthalmology:404.10:404.78 community:404.78:405.28 "
    "and:405.28:405.68 the:405.68:405.90 dermatology:405.90:406.54 community:406.54:406.90 have:406.90:407.16 "
    "embraced:407.16:407.78 public:407.78:408.86 education:408.86:409.36 on:409.36:409.62 these:409.62:409.84 "
    "topics:409.84:410.48")
C09_PUNCHLINE = ("Were the dozens of dermatologists and ophthalmologists saying, we think scans and more data "
                 "are great.")


class TestPayoffInTheClip:
    def test_c09_the_end_never_steps_back_before_the_answer(self):
        # Prod: CLEAN_END stepped back to "You know who didn't dogpile me?"
        # (396.07 s) and cut the answer off.
        c = {"start": 368.62, "end": 398.0, "punchline": C09_PUNCHLINE}
        main.end_on_sentence(c, C09_WORDS, 15, 60, pauses=True)
        assert 403.62 < c["end"] < 404.1 and c["clean_end"] == "payoff" and c["end_to_payoff"], c

    def test_c09_through_the_payoff_ending(self):
        c = {"start": 368.62, "end": 398.0, "punchline": C09_PUNCHLINE}
        main.trim_to_target(c, C09_WORDS, 15, (25, 40), pauses=True, max_secs=60)
        assert 403.62 < c["end"] < 404.1 and c["end_on_payoff"] and "payoff_outside" not in c, c
        assert c["end"] - 403.62 <= 2.0, "tail after the payoff"

    def test_c09_classic_clean_ending_also_keeps_the_payoff(self):
        c = {"start": 368.62, "end": 398.0, "punchline": C09_PUNCHLINE}
        main.end_on_sentence(c, C09_WORDS, 15, 60)
        assert c["end"] > 403.62, c

    def test_the_payoff_is_a_floor_for_the_clean_ending(self):
        # The payoff is in, the cut stops mid-run after it with no full stop
        # ahead: the last resort (back up to 8 s) used to land on the full
        # stop BEFORE the payoff and cut it off.
        w = mk(FILL * 4 + "the answer was simple " + "word " * 20)    # payoff 18.0-19.9 s
        c = {"start": 0.0, "end": 22.92, "punchline": "the answer was simple"}
        main.end_on_sentence(c, w, 15, 60)
        assert c["end"] == 22.92, c
        c = {"start": 0.0, "end": 22.92}
        main.end_on_sentence(c, w, 15, 60)
        assert c["end"] < 18.0, "without a payoff the old behaviour stays"

    def test_c11_payoff_outside(self):
        # Hook at 1521 s, payoff "So they tried cheating..." at 1589.6 s: 72 s,
        # over 60 + 3 s. Kept, flagged, never auto-published.
        words = _w(" ".join(f"w{i}.:{1521.0 + i * 0.5:.2f}:{1521.4 + i * 0.5:.2f}" for i in range(137))
                   + " So:1589.57:1589.95 they:1589.95:1590.37 tried:1590.37:1590.65 cheating.:1590.65:1591.23 "
                   "They:1591.61:1591.67 tried:1591.67:1591.93 hacking:1591.93:1592.31 into:1592.31:1592.57 "
                   "the:1592.57:1592.67 system.:1592.67:1593.03 They:1593.23:1593.51 hacked:1593.51:1593.83")
        c = {"start": 1520.99, "end": 1554.43,
             "punchline": "So they tried cheating. They tried hacking into the system."}
        main.trim_to_target(c, words, 15, (25, 40), pauses=True, max_secs=60)
        assert c["payoff_outside"] and "72s" in c["payoff_outside"], c
        assert c["end"] == 1554.43 and "end_on_payoff" not in c
        assert c["over_target"] if c["end"] - c["start"] > 40 else "over_target" not in c
        c2 = {"start": 1520.99, "end": 1554.43,
              "punchline": "So they tried cheating. They tried hacking into the system."}
        main.end_on_sentence(c2, words, 15, 60, pauses=True)
        assert c2["payoff_outside"], "end_on_sentence flags it too"

    def test_a_payoff_just_past_the_end_within_the_leeway(self):
        w = mk(FILL * 12 + PAYOFF + " " + FILL)             # payoff from 54.0 to 57.4 s
        c = {"start": 0.0, "end": 50.0, "punchline": PAYOFF}
        main.trim_to_target(c, w, 15, (25, 40), max_secs=55)
        assert 57.4 < c["end"] <= 58.0 and c["clean_end"] == "payoff", "55 + 3 s leeway holds it"
        c = {"start": 0.0, "end": 50.0, "punchline": PAYOFF}
        main.trim_to_target(c, w, 15, (25, 40), max_secs=50)
        assert c["payoff_outside"] and c["end"] == 50.0, "50 + 3 s does not"

    def test_short_reaction_kept_new_thought_cut(self):
        # c08: "...that scared people. The plunger. It's the plunger. So I'm
        # excited, and I have to say..." / c12: "...brain resource. Makes good sense."
        w = mk(FILL * 4 + PAYOFF + " The plunger. It's the plunger. " + FILL * 6)
        c = {"start": 0.0, "end": 50.0, "punchline": PAYOFF}
        main.trim_to_target(c, w, 15, (25, 40), max_secs=60)
        last = max(i for i, x in enumerate(w) if x["e"] <= c["end"])
        assert last == 44 and w[last]["w"] == "plunger.", "the first echo; the second ends 2.5 s after the payoff"
        assert c["payoff_reaction"] and c["end"] - 21.4 <= 2.0
        fast = [dict(x) for x in w]                       # said at c08's real pace: both echoes fit
        for x, (s, e) in zip(fast[43:48], ((21.62, 21.85), (21.85, 22.12), (22.34, 22.5), (22.5, 22.6),
                                           (22.6, 22.82))):
            x["s"], x["e"] = s, e
        c = {"start": 0.0, "end": 50.0, "punchline": PAYOFF}
        main.trim_to_target(c, fast, 15, (25, 40), max_secs=60)
        last = max(i for i, x in enumerate(fast) if x["e"] <= c["end"])
        assert last == 47 and c["end"] - 21.4 <= 2.0, c
        # a long sentence after the payoff is a new thought: cut
        w = mk(FILL * 4 + PAYOFF + " So I am excited and I have to say it. " + FILL * 6)
        c = {"start": 0.0, "end": 50.0, "punchline": PAYOFF}
        main.trim_to_target(c, w, 15, (25, 40), max_secs=60)
        assert 21.4 < c["end"] <= 21.5 and "payoff_reaction" not in c
        # a reaction past 2 s after the payoff: cut (c02's "Whoa." 1.5 s later)
        w = mk(FILL * 4 + PAYOFF + " " + FILL * 6)
        w.insert(43, {"w": "Whoa.", "s": 23.6, "e": 24.0})
        for x in w[44:]:
            x["s"] += 3.0
            x["e"] += 3.0
        c = {"start": 0.0, "end": 50.0, "punchline": PAYOFF}
        main.trim_to_target(c, w, 15, (25, 40), max_secs=60)
        assert 21.4 < c["end"] <= 21.9, c

    def test_a_pause_fragment_is_no_reaction(self):
        # c01: "...they might as well be drunk. And [pause] it's also how they
        # train them" — "And" alone, closed by a pause, is no sentence.
        w = mk(FILL * 4 + PAYOFF + " And it's also how they train them. " + FILL * 6)
        for x in w[44:]:                                   # a 0.9 s pause after "And"
            x["s"] += 0.8
            x["e"] += 0.8
        assert main._is_boundary(w, 43) and not main._ends_sentence(w, 43)
        c = {"start": 0.0, "end": 50.0, "punchline": PAYOFF}
        main.trim_to_target(c, w, 15, (25, 40), pauses=True, max_secs=60)
        assert 21.4 < c["end"] <= 21.5 and "payoff_reaction" not in c, c


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
        assert len(shorts) == 1 and shorts[0]["end_fit_for_target"] and shorts[0]["end_on_payoff"]
        # 5-oct-2026: right after the payoff, the format's 15 s as the floor.
        assert 15 <= dur(shorts[0]) < 20
        out = capsys.readouterr().out
        assert "Payoff ending: 1/1 clip(s) end on their payoff (1 cut right after it" in out
        assert "Clip lengths: 1 clip(s)" in out
        assert "`punchline`" in run.prompts["detail"][-1]

    def test_without_a_target_the_playbook_still_ends_on_the_payoff(self, run, monkeypatch):
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        monkeypatch.setenv("CLEAN_END", "1")
        shorts = run([clip(99.0, 157.5, hook_line="", punchline="it happens to people every day without them knowing.")])
        assert 15 <= dur(shorts[0]) < 20 and shorts[0]["end_on_payoff"]
        assert "end_fit_for_target" not in shorts[0] and "over_target" not in shorts[0]

    def test_without_the_playbook_nor_a_target_the_end_is_untouched(self, run, monkeypatch):
        monkeypatch.setenv("CLEAN_END", "1")
        shorts = run([clip(99.0, 157.5, punchline="it happens to people every day without them knowing.")])
        assert dur(shorts[0]) > 50 and "end_on_payoff" not in shorts[0]

    def test_a_payoff_outside_is_flagged_in_the_log(self, run, monkeypatch, capsys):
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        monkeypatch.setenv("CLEAN_END", "1")
        monkeypatch.setenv("CLIP_TARGET_MIN_SECONDS", "25")
        monkeypatch.setenv("CLIP_TARGET_MAX_SECONDS", "40")
        # The pipeline transcript is one sentence said over and over: a
        # punchline nobody said in the clip but said later cannot be built
        # from it, so the payoff check is stubbed to place it 80 s after.
        real = main._payoff_span

        def far(words, punchline, lo, hi, wt=None):
            k = next(i for i, w in enumerate(words) if w["s"] >= 99.0 + 80)
            return (k, k + 8) if lo <= words[k]["s"] <= hi else None
        monkeypatch.setattr(main, "_payoff_span", far)
        shorts = run([clip(99.0, 129.0, hook_line="", punchline="the payoff said much later")])
        monkeypatch.setattr(main, "_payoff_span", real)
        assert shorts[0]["payoff_outside"] and "end_on_payoff" not in shorts[0]
        out = capsys.readouterr().out
        assert "PAYOFF IS OUTSIDE the clip" in out and "left out of the auto-publish" in out
        assert "1 with the payoff outside" in out


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

    def test_a_sentence_that_points_at_what_came_before_is_not_offered(self):
        w = _twelve_sentences()
        w[50]["w"], w[51]["w"] = "the", "second"          # "the second thing was..."
        w[60]["w"] = "then"
        cands = main.open_later_candidates({"start": 0.0, "end": 60.0}, w, 15, (25, 40))
        assert [k for k, _, _ in cands] == [70]
        w = _twelve_sentences()
        w[50]["w"], w[51]["w"] = "the", "first"           # "the first thing" opens fine
        w[60]["w"], w[61]["w"] = "and", "then"
        cands = main.open_later_candidates({"start": 0.0, "end": 60.0}, w, 15, (25, 40))
        assert [k for k, _, _ in cands] == [50, 70]

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
        assert "Payoff ending: 0/1" in out and "1 where it is not found in the words" in out
        assert "Open later: 1/1" in out

    def test_without_the_playbook_no_later_opening(self, run, monkeypatch):
        monkeypatch.setenv("CLIP_TARGET_MIN_SECONDS", "25")
        monkeypatch.setenv("CLIP_TARGET_MAX_SECONDS", "40")

        def ask(prompt):
            raise AssertionError("no call expected")

        monkeypatch.setattr(main, "_ask_open_later", ask)
        shorts = run([clip(99.0, 157.5, hook_line="", punchline="words nobody said in this transcript")])
        assert len(shorts) == 1 and "start_fit_for_target" not in shorts[0]
