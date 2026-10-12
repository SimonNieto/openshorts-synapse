"""The stall (12-oct-2026): what stands between the opening sentence and the fact the title promises.

YouTube Studio of the first two « références » shorts (JRE #1109, 10-oct): 65 % stayed past the first seconds,
then 41-46 % of those still there at 4 s were left at 15 s (the record: 63 %) — banter or a vague list before the
fact, heard at 17-20 s. The clip choice names the fact (``fact_words``) and may mark the stall as a cut_out passage
(why "stall"); the code times the fact once the passages are out (main.fact_said_at) and flags fact_late past
main.FACT_LATE_SECONDS. No AI call, no token."""
import json

import pytest

main = pytest.importorskip("main")
import ai_brain  # noqa: E402
import gemini_worker as gw  # noqa: E402

# JRE #1109 c05, as said (4 words a second, about the real pace).
HOOK5 = ("Many people take pride in that too, I don't need eight hours sleep, I got three, I'm good, "
         "ready to go kick ass and dominate the world.")
STALL5 = ("Yeah yeah. It's the sort of like sleep machismo attitude. There is a lot of that, right? "
          "Yeah baby, I like sleep well. I mean you'd be glad to know that then.")
FACT5 = ("You know men who sleep five to six hours a night will have a level of testosterone which is that "
         "of someone 10 years their senior. So a lack of sleep will age you by a decade.")
# JRE #1109 c08: the stall holds a whole "not just X but Y".
HOOK8 = "Sleep is the greatest legal performance enhancing drug that most people are probably neglecting in sport."
STALL8 = ("Wow. And not just for your physical performance but actually skill learning, memory, and all of "
          "the recuperative benefits.")
FACT8 = ("And you can flip the coin by the way, if you're getting six hours of sleep or less your time to "
         "physical exhaustion drops by up to 30%. You're now gonna be physically exhausted by round seven.")


def mk(text, step=0.25, length=0.2):
    return [{"w": w, "s": round(i * step, 3), "e": round(i * step + length, 3)} for i, w in enumerate(text.split())]


def clip_of(hook, stall, fact, **extra):
    w = mk(f"{hook} {stall} {fact}")
    c = {"start": 0.0, "end": w[-1]["e"] + 0.05, "hook_aligned": True, "hook_line": hook,
         "punchline": fact.split(". ")[-1], "video_title_for_youtube_short": "Why Less Rest Lowers Your Testosterone"}
    c.update(extra)
    return w, c


class TestStallCut:
    def test_the_stall_is_cut_and_the_fact_comes_early(self):
        w, c = clip_of(HOOK5, STALL5, FACT5, fact_words="men who sleep five to six")
        assert main.fact_said_at(c, w) > main.FACT_LATE_SECONDS
        assert "fact_late" in main.check_opening(c, w)
        c["cut_out"] = [{"first_words": "Yeah yeah. It's the", "last_words": "know that then.", "why": "stall"}]
        assert main.check_cut_out(c, w, 10) == (1, 0)
        assert c["cut_out"] == [{"from": "Yeah yeah. It's the", "to": "know that then.", "why": "stall"}]
        assert main.fact_said_at(c, w) <= main.FACT_LATE_SECONDS
        assert "fact_late" not in main.check_opening(c, w)

    def test_an_unpunctuated_transcript_still_has_its_opening_sentence(self):
        # JRE #1109 c05 as Whisper wrote it: no full stop, no long pause — the model's stall was refused
        # ("first words not found in the clip after its opening sentence") until the quoted hook marked its end.
        bare = lambda t: " ".join(w.strip(",.?!").lower() for w in t.split())  # noqa: E731
        w, c = clip_of(bare(HOOK5), bare(STALL5), bare(FACT5), fact_words="men who sleep five to six")
        c["hook_line"] = HOOK5
        c["cut_out"] = [{"first_words": "yeah yeah it's the", "last_words": "know that then", "why": "stall"}]
        assert main.check_cut_out(c, w, 10) == (1, 0)
        assert main.fact_said_at(c, w) <= main.FACT_LATE_SECONDS
        # The opening sentence itself still never goes.
        w, c = clip_of(bare(HOOK5), bare(STALL5), bare(FACT5))
        c["hook_line"] = HOOK5
        c["cut_out"] = [{"first_words": "ready to go kick", "last_words": "yeah yeah", "why": "stall"}]
        assert main.check_cut_out(c, w, 10) == (0, 1)

    def test_a_whole_not_just_but_may_go_a_half_one_never(self):
        w, c = clip_of(HOOK8, STALL8, FACT8, fact_words="your time to physical exhaustion")
        c["cut_out"] = [{"first_words": "Wow. And not just", "last_words": "the recuperative benefits.",
                         "why": "stall"}]
        assert main.check_cut_out(c, w, 10) == (1, 0)
        # The "but" left outside: "not just for your physical performance" alone would deny.
        w, c = clip_of(HOOK8, STALL8, FACT8)
        c["cut_out"] = [{"first_words": "Wow. And not just", "last_words": "your physical performance",
                         "why": "stall"}]
        assert main.check_cut_out(c, w, 10) == (0, 1)
        assert c["cut_out_dropped"][0]["reason"] == "holds a negation or a nuance"

    def test_nuance_words(self):
        toks = main._ptoks
        assert not main._has_nuance(toks("and not just for your body but actually your memory"))
        assert not main._has_nuance(toks("not only the doctors but also the nurses"))
        assert main._has_nuance(toks("it's not going to cure anything"))
        assert main._has_nuance(toks("not just for your body"))
        assert main._has_nuance(toks("but only for a while"))
        assert main._has_nuance(toks("not just this but not that"))

    def test_the_fact_is_never_moved_nor_guessed(self):
        w, c = clip_of(HOOK5, STALL5, FACT5)
        assert main.fact_said_at(c, w) is None and "fact_said_at" not in c
        c["fact_words"] = "words nobody said here"
        assert main.fact_said_at(c, w) is None and "fact_late" not in main.check_opening(c, w)
        # Matched on its first 4 words: a quote a word longer than what Whisper heard still lands.
        c["fact_words"] = "men who sleep five to six hours nightly"
        start = c["start"]
        assert main.fact_said_at(c, w) is not None and c["start"] == start
        # A passage cut AFTER the fact does not bring it earlier.
        c["cut_out"] = [{"from": "So a lack", "to": "by a decade.", "why": "stall"}]
        before = main.fact_said_at({**c, "cut_out": []}, w)
        assert main.fact_said_at(c, w) == before

    def test_fact_late_costs_points_never_the_clip(self):
        assert main.OPENING_PENALTY["fact_late"] == 15
        c = {"predicted_score": 80, "opening_score": 80, "opening_flags": ["fact_late"]}
        assert main.rank_by_opening(c) < 80 and c["moment_score"] == 80


class TestPromptAndSchema:
    def test_rules(self):
        flat = " ".join(gw.PLAYBOOK_DETAIL_ADDENDUM.split())
        assert "`fact_words`: the first 3 to 6 words" in flat and "THE STALL" in flat
        assert "aside, screen_reading, hesitation, digression or stall" in flat
        assert "except a whole \"not just X but Y\"" in flat
        assert set(main.CUT_OUT_WHY) == {"aside", "screen_reading", "hesitation", "digression", "stall"}

    def test_schema(self):
        item = gw.DetailResponsePlaybook.model_json_schema()["$defs"]["DetailClipModelPlaybook"]["properties"]
        assert "fact_words" in item
        assert "fact_words" in json.dumps(ai_brain.json_schema(gw.DetailResponsePlaybook))
