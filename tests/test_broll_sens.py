"""B-roll « sens » (1-oct-2026 evening, audit-broll-sens): the bugs that destroyed the one specific picture of a
clip. The editor's hero stays the hero even when it is also a notion; the art director keeps the editor's facts;
the reviewer reads the episode's facts; a notion tag only when the picture is the notion; the style sheet is cut at
a word; the hard rules are said in the positive. No model is called."""
import pytest

import ai_brain
import broll


def _words(text, step=0.42, dur=0.4):
    out, t = [], 0.0
    for w in text.split():
        out.append({"text": w, "start": round(t, 2), "end": round(t + dur, 2)})
        t += step
    return out


TEXT = ("Well you know this is the setup for the story. Just think of the UFC fight this weekend, the cage on the "
        "White House lawn, I remember everything about it. And then the folder is just labeled my old bullshit "
        "and you have a decision to make about it. Nobody spoke for hours but the drill went on and on until "
        "sunrise came and the camp woke up again and the sergeant finally smiled at them all that morning.")

BRIEF = {"speakers": [], "topic": "t", "themes": [], "tone": "",
         "glossary": [{"term": "UFC 250 at the White House", "meaning": "a fight card on the lawn",
                       "visual": "An octagon cage on the White House lawn with the building behind"},
                      {"term": "Ego dissolution", "meaning": "the self drops",
                       "visual": "A person in meditation, boundaries dissolving"}],
         "stories": []}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(broll, "NOTION_DIR", str(tmp_path / "notions"))
    monkeypatch.setattr(broll, "HERO_TAKES", 1)
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")


def _plan(monkeypatch, data, **kw):
    monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: data)
    return broll.plan_with_claude({}, _words(TEXT), 4, [], hero=True, **kw)


class TestTheHeroStaysTheHero:
    def test_a_hero_that_is_also_a_notion_is_made_for_this_clip(self, monkeypatch, capsys):
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", BRIEF)
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"moments": [
            {"anchor": "UFC fight", "time": words[idx["UFC"]]["start"], "subject": "White House octagon",
             "image_prompt": "The White House behind a cage.", "hero": True, "role": "example", "shot": "wide",
             "notion": "UFC 250 at the White House"},
            {"anchor": "sergeant", "time": words[idx["sergeant"]]["start"], "subject": "sergeant",
             "image_prompt": "A sergeant.", "role": "example", "shot": "medium"}]}
        moments = _plan(monkeypatch, data)
        assert moments[0]["hero"] is True and moments[0]["notion"] == ""
        assert "made for this clip, not from the library" in capsys.readouterr().out
        # ... so the code's own pick agrees with the editor's
        assert broll.pick_hero(moments, words[-1]["end"], []) == 0


class TestTheDirectorKeepsTheFacts:
    def test_numbers_and_proper_nouns_are_the_facts(self):
        facts = broll.facts_of("Wide dusk shot of the White House behind a cage, 4,000 seated guests and 85,000 on "
                               "the Ellipse. The DMT pump reads 12 ml. In Toronto in the 1980s.")
        assert {"white", "house", "ellipse", "dmt", "4000", "85000", "12", "1980", "toronto"} <= facts
        assert "wide" not in facts and "the" not in facts and "in" not in facts

    def test_lost_facts_forgives_plurals_and_separators(self):
        assert broll.lost_facts("Two jugs in Toronto, 85,000 people.", "a crowd of 85000 in toronto with jugs") == []
        assert broll.lost_facts("The White House behind the cage.", "A packed arena at night.") == ["house", "white"]

    def test_a_prompt_that_drops_a_fact_is_not_taken(self, capsys):
        long = ("A packed arena at night, tens of thousands in silhouette under stadium lights, the octagon bright "
                "in the middle, floodlights from high angles, amber cage and indigo crowd, metal fencing and plastic "
                "seats, dust in the beams, electric and intense, the frame held wide from the upper seats so the "
                "whole bowl reads at a glance on a phone screen with air above for the dark sky.")
        ms = [{"t": 5.0, "anchor": "a", "prompt": "The White House facade behind an octagon cage on the lawn.", "subject": "s"},
              {"t": 9.0, "anchor": "b", "prompt": "A sergeant smiling at dawn.", "subject": "s2"}]
        n = broll._apply_art(ms, {"prompts": [{"k": 0, "prompt": long}, {"k": 1, "prompt": long}]})
        assert n == 1 and not ms[0].get("art") and ms[0]["prompt"].startswith("The White House")
        assert ms[1].get("art") and ms[1]["prompt"].startswith("A packed arena")
        assert "the director dropped house, white" in capsys.readouterr().out
        # the same prompt with the facts in it is taken
        ms2 = [{"t": 5.0, "anchor": "a", "prompt": "The White House facade behind an octagon cage on the lawn.", "subject": "s"}]
        assert broll._apply_art(ms2, {"prompts": [{"k": 0, "prompt": long + " The White House facade rises behind it."}]}) == 1


class TestTheReviewerReadsTheEpisode:
    def test_the_facts_block_carries_the_world_the_avoid_list_and_the_notions(self, monkeypatch):
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", BRIEF)
        monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", {"world": ["an octagon cage on the White House South Lawn"],
                                                        "avoid": ["a UFC octagon shot that hides the White House"]})
        cands = [{"m": {"notion": "UFC 250 at the White House"}}, {"m": {}}]
        text = broll._review_facts(cands)
        assert text.startswith("\nEPISODE FACTS") and "TRUE for this review, whatever your general knowledge" in text
        assert "WORLD of the episode" in text and "South Lawn" in text
        assert "AVOID (pictures the episode's director refused)" in text and "hides the White House" in text
        assert "- UFC 250 at the White House: a fight card on the lawn -> drawn as: An octagon cage" in text
        assert "Ego dissolution" not in text

    def test_nothing_without_a_bible_or_a_notion(self):
        assert broll._review_facts([{"m": {}}]) == ""

    def test_the_review_prompt_says_whose_facts_win(self):
        text = broll.REVIEW_PROMPT.format(frame=broll._review_frame([{"layout": "card"}]), items="- x")
        assert "never against your own idea of what is plausible" in text

    def test_the_claude_review_appends_the_facts(self, monkeypatch, tmp_path):
        from PIL import Image
        monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", {"world": ["a glass vial of DMT"], "avoid": []})
        p = tmp_path / "broll_0.jpg"
        Image.new("RGB", (64, 64)).save(p)
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt) or {"reviews": []})
        broll.review_with_claude([{"file": str(p), "layout": "card", "m": {"t": 5.0, "idea": "i", "said": "s", "prompt": "p"}}],
                                 _words(TEXT))
        assert "EPISODE FACTS" in seen["prompt"] and "a glass vial of DMT" in seen["prompt"]
        assert seen["prompt"].index("STEP 3 - THE LOOK") < seen["prompt"].index("\nEPISODE FACTS (")


class TestANotionTagOnlyWhenThePictureIsTheNotion:
    def _moment(self, **k):
        return {"t": 5.0, "anchor": "a", "query": "a", "prompt": "p", "subject": "", "notion": "", **k}

    def test_a_box_tagged_ego_dissolution_loses_the_tag(self, capsys):
        ms = [self._moment(anchor="labeled my old bullshit", subject="box of old belongings", notion="Ego dissolution",
                           prompt="A cardboard box of old photographs."),
              self._moment(anchor="UFC fight", query="UFC fight", subject="White House octagon",
                           notion="UFC 250 at the White House", prompt="The White House behind a cage.")]
        broll.apply_notions(ms, BRIEF, TEXT)
        assert ms[0]["notion"] == "" and "Draw Ego dissolution" not in ms[0]["prompt"]
        assert ms[1]["notion"] == "UFC 250 at the White House"
        assert 'tagged on "box of old belongings", which is not it' in capsys.readouterr().out

    def test_a_notion_said_in_other_words_still_gets_its_glossary_picture(self):
        ms = [self._moment(anchor="the self drops", subject="ego dissolution", notion="Ego dissolution", prompt="A person.")]
        broll.apply_notions(ms, BRIEF, "the self drops away and nothing else is said here at all")
        assert ms[0]["notion"] == "Ego dissolution" and "Draw Ego dissolution the channel's usual way" in ms[0]["prompt"]


class TestSmallThings:
    def test_the_style_sheet_is_cut_at_a_word(self):
        sheet = broll._clean_sheet({"palette": "deep indigo-black in the DMT room and night sky, hot amber-gold on the "
                                               "White House facade and stage lights, surgical white on the pump"})
        assert len(sheet["palette"]) <= 70 and not sheet["palette"].endswith("whi")
        assert sheet["palette"].endswith(("sky", "sky,")) or sheet["palette"].split()[-1].isalpha()

    def test_the_hard_rules_are_said_in_the_positive(self):
        low = f" {broll.ART_RULES.lower()} "
        assert " no " not in low and "never" not in low and "without" not in low
        assert "plain surface" in low and "anonymous" in low
