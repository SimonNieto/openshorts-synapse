"""Is the on-screen hook understood cold? (playbook.hook_problems, and the one
retry of main.retry_unclear_hooks with selection.hook_check / HOOK_CHECK=1.)

The hooks are the 11 of JRE #2515 (Chase Hughes-001). The viewer reads them
before hearing a word and without the title."""
import json

import pytest

import playbook
import plus

CLEAR = [
    "Five and a half hours straight.",
    "A galaxy might share its shape with DNA.",
    "Every single fight ended the exact same way.",
    "The whole world is lonelier than ever before.",
    "Most doctors won't tell you this.",
    "97% of people miss this.",
]
UNCLEAR = {
    "The quit room has no one in it.": "an image ('room')",
    "Your brain wakes up with one labeled folder.": "an image ('folder')",
    "He asked one question thirty-nine times straight.": "opens on 'he'",
    "She prayed to fix his heart and brain.": "opens on 'she'",
    "It might go on forever, fractal inside fractal.": "opens on 'it'",
    "Nobody gave him a real chance to win.": "'him' is someone the viewer has not met",
    "His opponent was left completely unrecognizable.": "opens on 'his'",
    "This changes everything you know.": "no concrete noun or number",
    "Nobody ever tells you the real truth about the thing.": "10 words (max 8)",
}


class TestHookProblems:
    def test_clear_hooks_pass(self):
        for hook in CLEAR:
            assert playbook.hook_problems(hook) == [], hook

    def test_unclear_hooks_say_why(self):
        for hook, why in UNCLEAR.items():
            problems = playbook.hook_problems(hook)
            assert any(why in p for p in problems), (hook, problems)

    def test_a_number_or_a_concrete_word_is_enough(self):
        assert playbook.hook_problems("Only three percent survive.") == []
        assert playbook.hook_problems("Kratom hits the same receptors.") == []
        assert "no concrete noun or number" in playbook.hook_problems("Nobody saw that coming.")[-1]

    def test_no_hook_nothing_to_say(self):
        assert playbook.hook_problems("") == [] and playbook.hook_problems(None) == []

    def test_check_hook_keeps_its_verdict_and_adds_clarity(self):
        c = {"video_title_for_youtube_short": "Can psychedelics really reboot your entire identity?",
             "viral_hook_text": "Your brain wakes up with one labeled folder."}
        assert playbook.check_hook(c) is False, "still returns 'repeats the title'"
        assert c["hook_clear"] is False and "folder" in c["hook_problems"][0]
        assert playbook.hook_issues(c) == c["hook_problems"]
        c = {"video_title_for_youtube_short": "Can stress rewire your brain?",
             "viral_hook_text": "Stress can rewire your brain."}
        assert playbook.check_hook(c) is True and c["hook_clear"] is True
        assert playbook.hook_issues(c) == ["says the title again"]


class TestHookSpoils:
    # Hooks, punchlines and titles from JRE #2515 and its hook-check trial.
    def test_a_rewrite_that_tells_the_ending_is_caught(self):
        assert playbook.hook_spoils("A 6-to-1 underdog won the greatest fight ever", "and then Justin rallied")             == "tells the ending ('won')"
        assert playbook.hook_spoils("He survived five days without water.") == "tells the ending ('survived')"
        assert playbook.hook_spoils("It turned out to be a tumor.", "") == "tells the ending ('turned out')"

    def test_the_punchline_quoted_as_the_hook_is_caught(self):
        assert playbook.hook_spoils("The quit room has no one in it.",
                                    "the quit room has no one in it there's nothing in there") == "says the punchline"
        assert playbook.hook_spoils("The whole world is lonelier than ever before.",
                                    "We have more rampant loneliness around the world than we've ever had before")             == "says the punchline"

    def test_a_tease_passes(self):
        for hook, punch in (("Nobody gave him a real chance to win.", "and then Justin rallied"),
                            ("Every single fight ended the exact same way.", "to see it that way at the White House"),
                            ("His opponent was left completely unrecognizable.", "he's unrecognizable"),
                            ("It might go on forever, fractal inside fractal.", "black holes inside their brain cells"),
                            ("Five and a half hours straight.", "and it seems like we're protected"),
                            ("Betting odds gave the champion almost no chance.", "and then Justin rallied"),
                            ("", "anything"), (None, None)):
            assert playbook.hook_spoils(hook, punch) == "", hook

    def test_check_hook_and_issues_carry_it(self):
        c = {"video_title_for_youtube_short": "Can a 6-to-1 underdog really beat the sport's best?",
             "viral_hook_text": "The underdog won the greatest fight ever.", "punchline": "and then Justin rallied"}
        assert playbook.check_hook(c) is False
        assert c["hook_spoils"] == "tells the ending ('won')" and c["hook_clear"] is True
        assert playbook.hook_issues(c) == ["tells the ending ('won')"]
        c["viral_hook_text"] = "Nobody gave the underdog a chance."
        assert playbook.hook_issues(c) == [] and c["hook_spoils"] == ""


class TestNamedPerson:
    # JRE #2515 (1-oct-2026): the rewrites refused for a pronoun the hook had just explained.
    def test_a_pronoun_after_the_person_it_points_at_is_fine(self):
        for hook in ("A DMT user asked if he was dead.", "A woman prayed for his heart and brain.",
                     "Two fighters broke faces, then they hugged.", "A patient saw her own surgery.",
                     "The champion lost his sight mid-fight."):
            assert playbook.hook_problems(hook) == [], hook

    def test_a_pronoun_before_or_without_the_person_is_not(self):
        assert playbook.hook_problems("He asked one question 39 times.") == \
            ["opens on 'he', which points at nothing the viewer has seen"]
        assert "'his' is someone the viewer has not met" in playbook.hook_problems("Entities performed surgery inside his body.")
        assert "'he' is someone the viewer has not met" in playbook.hook_problems("The room went silent when he spoke.")

    def test_the_retry_prompt_says_so(self):
        prompt = playbook.hook_retry_prompt([{"id": 0, "title": "T?", "opening": "O.", "punchline": "P.",
                                              "hook": "H", "problems": ["p"]}], "en")
        assert "unless the hook itself says who" in prompt


class TestRetryPieces:
    TRANSCRIPT = {"language": "en", "segments": [{"words": [
        {"word": w, "start": 100 + i * 0.4, "end": 100 + i * 0.4 + 0.3} for i, w in enumerate(
            "Before that. Psilocybin quiets the default mode network. Your sense of self goes offline. "
            "Then it comes back.".split())]}]}

    def test_opening_is_the_first_two_sentences_of_the_clip(self):
        clip = {"start": 100.8, "end": 140.0}
        assert playbook.opening_sentences(clip, self.TRANSCRIPT) == \
            "Psilocybin quiets the default mode network. Your sense of self goes offline."
        assert playbook.opening_sentences(clip, None) == ""
        assert playbook.opening_sentences({"start": 100.8, "end": 102.0}, self.TRANSCRIPT) == "Psilocybin quiets the"

    def test_prompt_is_filled(self):
        prompt = playbook.hook_retry_prompt([{"id": 0, "title": "T?", "opening": "O.", "punchline": "P.",
                                              "hook": "H", "problems": ["p"]}], "en")
        assert "max 7 words, in en" in prompt and '"opening": "O."' in prompt and '"punchline": "P."' in prompt
        assert playbook.HOOK_RETRY_WORDS == playbook.HOOK_MAX_WORDS - 1, "one word under the limit the check applies"
        assert "it NEVER tells it" in prompt
        assert '{"hooks": [{"id": <clip id>, "viral_hook_text": "<max 7 words>"}]}' in prompt

    def test_a_better_hook_is_taken(self):
        c = {"video_title_for_youtube_short": "Can psychedelics really reboot your entire identity?",
             "viral_hook_text": "Your brain wakes up with one labeled folder."}
        assert playbook.apply_hook_retry(c, " Psilocybin switches off   your sense of self. ") is True
        assert c["viral_hook_text"] == "Psilocybin switches off your sense of self."
        assert c["hook_clear"] is True and c["hook_problems"] == []
        assert c["hook_check"]["before"] == "Your brain wakes up with one labeled folder."
        assert c["hook_check"]["retried"] is True

    def test_a_hook_that_is_no_better_is_refused(self):
        title = "Can psychedelics really reboot your entire identity?"
        old = "Your brain wakes up with one labeled folder."
        for new in ("It opens a door in your mind.", "Can psychedelics really reboot your identity?", "", None, old):
            c = {"video_title_for_youtube_short": title, "viral_hook_text": old}
            assert playbook.apply_hook_retry(c, new) is False, new
            assert c["viral_hook_text"] == old and c["hook_check"]["kept"], new
            assert c["hook_clear"] is False

    def test_a_rewrite_that_tells_the_ending_is_refused(self):
        # Real rewrite on JRE #2515: clear, concrete, and it gives the fight away.
        c = {"video_title_for_youtube_short": "Can a 6-to-1 underdog really beat the sport's best?",
             "viral_hook_text": "Nobody gave him a real chance to win.", "punchline": "and then Justin rallied"}
        assert playbook.apply_hook_retry(c, "A 6-to-1 underdog won the greatest fight ever") is False
        assert c["viral_hook_text"] == "Nobody gave him a real chance to win."
        assert c["hook_check"]["issues_rejected"] == ["tells the ending ('won')"]
        assert playbook.apply_hook_retry(c, "Nobody gave the 6-to-1 underdog a chance") is True
        assert c["hook_spoils"] == ""
        # ...and a hook that quotes the punchline is sent back even when it is clear
        c = {"video_title_for_youtube_short": "Does this fighter actually have zero quit in him?",
             "viral_hook_text": "The quit room has no one in it.",
             "punchline": "the quit room has no one in it there's nothing in there"}
        assert "says the punchline" in playbook.hook_issues(c)

    def test_clear_beats_unclear_even_when_it_says_the_title_again(self):
        # Real answer on JRE #2515: the viewer reads the hook without the title.
        c = {"video_title_for_youtube_short": "Does a prayer really shape a DMT experience?",
             "viral_hook_text": "She prayed to fix his heart and brain."}
        assert playbook.apply_hook_retry(c, "A prayer changed a brutal DMT surgery experience") is True
        assert c["hook_clear"] is True and c["hook_repeats_title"] is True
        # ...but a clear hook is never traded for a clear one that repeats the title
        c = {"video_title_for_youtube_short": "Does a prayer really shape a DMT experience?",
             "viral_hook_text": "One prayer before 5 grams."}
        assert playbook.apply_hook_retry(c, "A prayer changed a brutal DMT surgery experience") is False

    def test_export_and_update_carry_the_verdict(self, tmp_path):
        c = {"start": 0.0, "end": 30.0, "video_title_for_youtube_short": "Can psychedelics reboot your identity?",
             "viral_hook_text": "Your brain wakes up with one labeled folder."}
        out = json.load(open(playbook.export_clip(c, str(tmp_path), "x_clip_1.mp4", []), encoding="utf-8"))
        assert out["hook_clear"] is False and out["hook_problems"] and out["hook_before_retry"] == ""
        assert out["hook_tells_ending"] == ""
        playbook.apply_hook_retry(c, "Psilocybin switches off your sense of self.")
        out = json.load(open(playbook.export_clip(c, str(tmp_path), "x_clip_1.mp4", []), encoding="utf-8"))
        assert out["hook_clear"] is True and out["hook_before_retry"].startswith("Your brain wakes up")
        playbook.update_export(str(tmp_path), "x_clip_1.mp4", {**c, "viral_hook_text": "It is a trap."}, [])
        out = json.load(open(tmp_path / "x_clip_1_playbook.json", encoding="utf-8"))
        assert out["hook_clear"] is False and out["on_screen_hook"] == "It is a trap."


def test_profile_switch():
    assert "HOOK_CHECK" not in plus.job_env({"name": "t"})
    assert plus.job_env({"name": "t", "selection": {"hook_check": True}})["HOOK_CHECK"] == "1"
    assert playbook.hook_check_enabled() is False


# --- the retry itself (needs main) -------------------------------------------------------

main = pytest.importorskip("main")


def _shorts():
    return [
        {"start": 100.8, "end": 140.0, "video_title_for_youtube_short": "Can psychedelics really reboot your identity?",
         "viral_hook_text": "Your brain wakes up with one labeled folder.", "punchline": "Then it comes back."},
        {"start": 300.0, "end": 330.0, "video_title_for_youtube_short": "Is kratom really harmless?",
         "viral_hook_text": "Kratom hits the same receptors as opioids."},
        {"start": 500.0, "end": 530.0, "video_title_for_youtube_short": "Can a fighter come back from that?",
         "viral_hook_text": "His opponent was left completely unrecognizable."},
        {"start": 700.0, "end": 730.0, "video_title_for_youtube_short": "Is there a hook?", "viral_hook_text": ""},
    ]


class TestRetryUnclearHooks:
    def test_one_call_for_every_unclear_hook_and_only_those(self, capsys):
        shorts, prompts = _shorts(), []

        def ask(prompt):
            prompts.append(prompt)
            return {"hooks": [{"id": 0, "viral_hook_text": "Psilocybin switches off your sense of self."},
                              {"id": 2, "viral_hook_text": "It was a bloodbath."}]}

        assert main.retry_unclear_hooks(shorts, TestRetryPieces.TRANSCRIPT, ask=ask) == 1
        assert len(prompts) == 1
        assert "labeled folder" in prompts[0] and "unrecognizable" in prompts[0]
        assert "Kratom" not in prompts[0], "a clear hook is not sent"
        assert "Psilocybin quiets the default mode network." in prompts[0], "the clip's opening goes with it"
        assert '"punchline": "Then it comes back."' in prompts[0], "and its punchline"
        assert shorts[0]["viral_hook_text"] == "Psilocybin switches off your sense of self."
        assert shorts[2]["viral_hook_text"] == "His opponent was left completely unrecognizable.", "no better: kept"
        assert "hook_check" not in shorts[1] and "hook_check" not in shorts[3]
        out = capsys.readouterr().out
        assert "Hook check: 1/2 unclear hook(s) rewritten" in out and "Hook rewritten" in out

    def test_never_asks_twice_about_the_same_hook(self):
        shorts, calls = _shorts(), []

        def ask(prompt):
            calls.append(prompt)
            return {"hooks": []}

        main.retry_unclear_hooks(shorts, None, ask=ask)
        main.retry_unclear_hooks(shorts, None, ask=ask)
        assert len(calls) == 1
        # hook grounding wrote a new hook: that one is checked
        shorts[0]["viral_hook_text"] = "It opens a door."
        main.retry_unclear_hooks(shorts, None, ask=ask)
        assert len(calls) == 2 and "It opens a door." in calls[1] and "unrecognizable" not in calls[1]

    def test_nothing_unclear_no_call(self):
        def ask(prompt):
            raise AssertionError("no call expected")
        assert main.retry_unclear_hooks([_shorts()[1]], None, ask=ask) == 0

    def test_a_failed_call_keeps_the_hooks(self, capsys):
        shorts = _shorts()

        def ask(prompt):
            raise RuntimeError("model down")

        assert main.retry_unclear_hooks(shorts, None, ask=ask) == 0
        assert shorts[0]["viral_hook_text"].endswith("labeled folder.")
        assert "the rewrite failed" in capsys.readouterr().out

    def test_a_malformed_answer_keeps_the_hooks(self):
        for answer in (None, {}, {"hooks": None}, {"hooks": ["x", {"id": "zero"}, {"viral_hook_text": "y"}]}):
            shorts = _shorts()
            assert main.retry_unclear_hooks(shorts, None, ask=lambda p, a=answer: a) == 0
            assert shorts[0]["viral_hook_text"].endswith("labeled folder.")
