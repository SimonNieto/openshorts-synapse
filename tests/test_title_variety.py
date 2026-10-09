"""The titles of one job read as a set (selection.title_variety -> TITLE_VARIETY=1,
with the playbook): JRE #2515 on 1-oct-2026 came back with "DMT" in 4 titles of
6 and "really / truly / just / ever" in 4 of 6. Each title passed title_problems;
together they read like one short posted four times. The repeats get one grouped
rewrite (main.retitle_repeats)."""
import pytest

import playbook
import plus


@pytest.fixture(autouse=True)
def _question_titles(monkeypatch):
    """These checks are the closed-question titles (playbook.title_style "question"); the "references" style
    has its own (tests/test_references_recipe.py)."""
    monkeypatch.setenv("TITLE_STYLE", "question")


# The six titles of the job, with the scores the model gave.
JRE = [("Is certainty just a security blanket for your brain?", 74),
       ("Can words ever truly describe a DMT experience?", 71),
       ("Is separation the brain's greatest illusion?", 80),
       ("Why did coming back from DMT feel so devastating?", 86),
       ("Why does DMT memory outlast every dream you've had?", 72),
       ("Can a DMT trip really target a specific illness?", 84)]


def _shorts(rows=JRE):
    return [{"start": 10.0 * i, "end": 10.0 * i + 30, "video_title_for_youtube_short": t, "predicted_score": s,
             "viral_hook_text": "h", "punchline": "p"} for i, (t, s) in enumerate(rows)]


class TestTitleSetProblems:
    def test_a_key_word_carries_two_titles_at_most(self):
        assert [playbook.title_keyword_max(n) for n in (1, 3, 6, 9, 11, 12)] == [2, 2, 2, 3, 3, 4]

    def test_the_real_job(self):
        out = playbook.title_set_problems(_shorts())
        # "DMT" is in 4 titles: the two best-scoring (86, 84) keep it, 71 and 72 lose it.
        assert "'dmt' is already in 2 other titles" in out[1]["issues"] and "dmt" in out[1]["avoid"]
        assert "'dmt' is already in 2 other titles" in out[4]["issues"]
        assert 3 not in out and 5 not in out
        # "just", "ever", "really": the best-scoring (84) keeps its word, the other two lose theirs.
        assert "'just' pads the question (one such title per job)" in out[0]["issues"] and out[0]["avoid"] == ["just"]
        assert "'ever' pads the question (one such title per job)" in out[1]["issues"]
        assert sorted(out[1]["avoid"]) == ["dmt", "ever"]
        # "brain" is in two titles: fine.
        assert 2 not in out
        assert sorted(out) == [0, 1, 4]

    def test_a_varied_set_has_no_problem(self):
        rows = [("Can a brain tumor make you a killer?", 80), ("Is kratom as harmless as people think?", 75),
                ("Does cannabis cause psychosis?", 70), ("Can a brain scan predict a crime?", 85)]
        assert playbook.title_set_problems(_shorts(rows)) == {}

    def test_plurals_and_possessives_count_as_the_same_word(self):
        rows = [("Can a brain tumor make you a killer?", 80), ("Is the brain's memory a lie?", 75),
                ("Do brains really sleep?", 70)]
        out = playbook.title_set_problems(_shorts(rows))
        assert list(out) == [2] and out[2]["avoid"] == ["brain"]

    def test_empty_and_missing_titles_are_ignored(self):
        assert playbook.title_set_problems([{"video_title_for_youtube_short": ""}, {}]) == {}
        assert playbook.title_set_problems([]) == {}


class TestApplyRetitle:
    TOKENS = ("chase", "hughes", "joe", "rogan")

    def _clip(self):
        return {"video_title_for_youtube_short": "Can words ever truly describe a DMT experience?",
                "predicted_score": 71}

    def test_a_good_title_is_taken_and_recorded(self):
        c = self._clip()
        ok = playbook.apply_retitle(c, "  Can language  survive a trip beyond words? ", self.TOKENS, ["dmt", "ever"],
                                    ["'dmt' is already in 2 other titles"])
        assert ok and c["video_title_for_youtube_short"] == "Can language survive a trip beyond words?"
        assert c["title_check"]["before"] == "Can words ever truly describe a DMT experience?"
        assert c["title_check"]["issues_before"] == ["'dmt' is already in 2 other titles"]
        assert c["title_format_ok"] is True and c["title_has_name"] is False

    def test_refused_titles(self):
        for new, why in (("Is DMT beyond words?", "still carries 'dmt'"),
                         ("Can DMTs be described?", "still carries 'dmts'"),
                         ("Can anyone ever describe the trip?", "still carries 'ever'"),
                         ("What words describe the trip?", "fails the format"),
                         ("Why can't words describe the trip?", "fails the format"),
                         ("Can Joe Rogan describe the trip?", "a name in the new title"),
                         ("", "no new title"), (None, "no new title"),
                         ("Can words ever truly describe a DMT experience?", "no new title")):
            c = self._clip()
            assert playbook.apply_retitle(c, new, self.TOKENS, ["dmt", "ever"]) is False, new
            assert c["video_title_for_youtube_short"] == "Can words ever truly describe a DMT experience?"
            assert why in c["title_check"]["kept"], (new, c["title_check"])

    def test_a_why_title_needs_the_clip_s_why_slot(self):
        c = {**self._clip(), "why_slot": True}
        assert playbook.apply_retitle(c, "Why do words fail after the trip?", self.TOKENS, ["dmt"]) is True

    def test_export_carries_the_verdict(self, tmp_path):
        import json
        c = {"start": 0.0, "end": 30.0, **self._clip()}
        playbook.apply_retitle(c, "Can language survive a trip beyond words?", self.TOKENS, ["dmt"],
                               ["'dmt' is already in 2 other titles"])
        out = json.load(open(playbook.export_clip(c, str(tmp_path), "x_clip_1.mp4", []), encoding="utf-8"))
        assert out["title_before_retitle"] == "Can words ever truly describe a DMT experience?"
        assert out["title_repeats"] == ["'dmt' is already in 2 other titles"]
        assert out["title"] == "Can language survive a trip beyond words?"


def test_profile_switch():
    # Part of the house recipe since 1-oct-2026: on for every job, no profile switch.
    assert plus.job_env({"name": "t"})["TITLE_VARIETY"] == "1"
    assert plus.SELECTION["title_variety"] is True
    assert "title_variety" not in plus.sanitize({"selection": {"title_variety": False}})["selection"]
    assert playbook.title_variety_enabled() is False


def test_prompt_is_filled():
    prompt = playbook.retitle_prompt([{"id": 1, "title": "T?", "problems": ["p"], "avoid": ["dmt"], "hook": "H",
                                       "opening": "O.", "payoff": "P."}], ["Other?"], "en")
    assert "closed question in en" in prompt and '"avoid": [\n    "dmt"\n   ]' in prompt
    assert '"other_titles": [\n  "Other?"\n ]' in prompt
    assert '{"titles": [{"id": <clip id>, "video_title_for_youtube_short": "<the question>"}]}' in prompt


# --- the rewrite itself (needs main) -------------------------------------------------------
main = pytest.importorskip("main")

TRANSCRIPT = {"language": "en", "segments": [{"words": [
    {"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, w in enumerate(
        "Words fail here. Nothing describes it. Then it comes back.".split())]}]}


class TestRetitleRepeats:
    def test_one_call_for_the_repeats_and_only_those(self, capsys):
        shorts, prompts = _shorts(), []

        def ask(prompt):
            prompts.append(prompt)
            return {"titles": [{"id": 0, "video_title_for_youtube_short": "Is certainty a security blanket?"},
                               {"id": 1, "video_title_for_youtube_short": "Can language survive the trip?"},
                               {"id": 4, "video_title_for_youtube_short": "Does DMT memory beat every dream?"}]}

        assert main.retitle_repeats(shorts, TRANSCRIPT, ("chase", "hughes"), ask=ask) == 2
        assert len(prompts) == 1
        assert "Can words ever truly describe a DMT experience?" in prompts[0]
        assert '"Can a DMT trip really target a specific illness?"' in prompts[0], "the kept titles travel as other_titles"
        assert "Words fail here. Nothing describes it." in prompts[0], "the clip's opening goes with it"
        assert shorts[0]["video_title_for_youtube_short"] == "Is certainty a security blanket?"
        assert shorts[1]["video_title_for_youtube_short"] == "Can language survive the trip?"
        assert shorts[4]["video_title_for_youtube_short"].startswith("Why does DMT memory outlast"), "still 'dmt': kept"
        assert shorts[4]["title_check"]["kept"] == "the new title still carries 'dmt'"
        assert "title_check" not in shorts[3] and "title_check" not in shorts[5]
        out = capsys.readouterr().out
        assert "repeats the others" in out and "Title rewritten" in out and "Titles: 2/3 repeated title(s) rewritten" in out

    def test_nothing_repeated_no_call(self, capsys):
        def ask(prompt):
            raise AssertionError("no call expected")
        rows = [("Can a brain tumor make you a killer?", 80), ("Is kratom as harmless as people think?", 75)]
        assert main.retitle_repeats(_shorts(rows), TRANSCRIPT, (), ask=ask) == 0
        assert "no repeat across the 2 title(s)" in capsys.readouterr().out

    def test_a_failed_or_malformed_call_keeps_the_titles(self, capsys):
        for answer in (None, {}, {"titles": None}, {"titles": ["x", {"id": "zero"}]}):
            shorts = _shorts()
            assert main.retitle_repeats(shorts, TRANSCRIPT, (), ask=lambda p, a=answer: a) == 0
            assert [c["video_title_for_youtube_short"] for c in shorts] == [t for t, _ in JRE]
        shorts = _shorts()

        def ask(prompt):
            raise RuntimeError("model down")

        assert main.retitle_repeats(shorts, TRANSCRIPT, (), ask=ask) == 0
        assert [c["video_title_for_youtube_short"] for c in shorts] == [t for t, _ in JRE]
        assert "the rewrite failed" in capsys.readouterr().out


def test_detail_prompt_carries_the_set_rule_only_with_the_switch(monkeypatch):
    monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
    monkeypatch.delenv("TITLE_VARIETY", raising=False)
    off = main.playbook_detail_rules(60.0)
    assert "TITLES AS A SET" not in off
    monkeypatch.setenv("TITLE_VARIETY", "1")
    on = main.playbook_detail_rules(60.0)
    assert "TITLES AS A SET" in on and on.replace(__import__("gemini_worker").TITLE_VARIETY_ADDENDUM, "") == off
