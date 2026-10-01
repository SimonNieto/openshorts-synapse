"""main.retry_unclear_hooks, the second round. JRE #2515, 1-oct-2026: "This image will break your brain." was
rewritten, as clearer, into "The universe and a brain cell look identical" — under the title "Does the universe
actually look like a human brain cell?". Taken (clear beats unclear), then never looked at again. One more
round for that case, with the title's words to stay away from."""
import pytest

import playbook

main = pytest.importorskip("main")

TITLE = "Does the universe actually look like a human brain cell?"


def _shorts():
    return [{"start": 733.0, "end": 772.0, "video_title_for_youtube_short": TITLE,
             "viral_hook_text": "This image will break your brain.", "punchline": "That's the universe."}]


def test_title_words():
    words = playbook.title_words(TITLE)
    assert {"universe", "brain", "cell"} <= set(words) and "the" not in words and len(words) == len(set(words))
    assert playbook.title_words("") == []


def test_one_more_round_with_the_title_words_to_avoid(capsys):
    shorts, prompts = _shorts(), []

    def ask(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return {"hooks": [{"id": 0, "viral_hook_text": "The universe and a brain cell look identical"}]}
        return {"hooks": [{"id": 0, "viral_hook_text": "Neurons and galaxies share one shape"}]}

    assert main.retry_unclear_hooks(shorts, None, ask=ask) == 1
    assert len(prompts) == 2
    assert '"title_words_not_to_reuse": [' not in prompts[0], "the first problem was clarity, not the title"
    assert '"title_words_not_to_reuse": [' in prompts[1] and '"universe"' in prompts[1] and "look identical" in prompts[1]
    assert "says the title again" in prompts[1]
    assert shorts[0]["viral_hook_text"] == "Neurons and galaxies share one shape"
    assert shorts[0]["hook_repeats_title"] is False
    assert shorts[0]["hook_check"]["checked"] == "Neurons and galaxies share one shape"
    out = capsys.readouterr().out
    assert "Hook rewritten again" in out and "Hook check: 1/1 unclear hook(s) rewritten" in out


def test_a_second_rewrite_that_still_says_the_title_is_refused(capsys):
    shorts, prompts = _shorts(), []

    def ask(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return {"hooks": [{"id": 0, "viral_hook_text": "The universe and a brain cell look identical"}]}
        return {"hooks": [{"id": 0, "viral_hook_text": "A brain cell looks like the universe"}]}

    assert main.retry_unclear_hooks(shorts, None, ask=ask) == 1
    assert len(prompts) == 2
    assert shorts[0]["viral_hook_text"] == "The universe and a brain cell look identical", "the clearer one stays"
    assert "Hook kept again" in capsys.readouterr().out


def test_no_second_round_when_the_rewrite_does_not_say_the_title():
    shorts, prompts = _shorts(), []

    def ask(prompt):
        prompts.append(prompt)
        return {"hooks": [{"id": 0, "viral_hook_text": "Neurons and galaxies share one shape"}]}

    assert main.retry_unclear_hooks(shorts, None, ask=ask) == 1
    assert len(prompts) == 1


def test_a_hook_flagged_for_the_title_from_the_start_gets_the_words_in_its_first_prompt():
    shorts = _shorts()
    shorts[0]["viral_hook_text"] = "The universe looks like a human brain cell"
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return {"hooks": [{"id": 0, "viral_hook_text": "Neurons and galaxies share one shape"}]}

    assert main.retry_unclear_hooks(shorts, None, ask=ask) == 1
    assert len(prompts) == 1 and '"title_words_not_to_reuse": [' in prompts[0]
    assert "title_words_not_to_reuse" in playbook.HOOK_RETRY_PROMPT


def test_a_failed_second_call_keeps_the_first_rewrite(capsys):
    shorts, prompts = _shorts(), []

    def ask(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return {"hooks": [{"id": 0, "viral_hook_text": "The universe and a brain cell look identical"}]}
        raise RuntimeError("model down")

    assert main.retry_unclear_hooks(shorts, None, ask=ask) == 1
    assert shorts[0]["viral_hook_text"] == "The universe and a brain cell look identical"
    assert "the rewrite failed" in capsys.readouterr().out
