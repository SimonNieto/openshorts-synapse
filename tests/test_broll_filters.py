"""The prohibitions, rebuilt (audit of 1-oct-2026 evening, commit A — the mechanics): every filter counts and says
what it drops; the planner's worth decides between two moments that touch, not their order; the "latest subjects"
memory is gone; a notion tag holds when the subject names what the glossary draws; every guard that fires goes out,
hands in the positive; the weakest judge never has the last word on a card. No model is called."""
import os

import pytest

import ai_brain
import broll


def _words(text, step=0.42, dur=0.4):
    out, t = [], 0.0
    for w in text.split():
        out.append({"text": w, "start": round(t, 2), "end": round(t + dur, 2)})
        t += step
    return out


TEXT = ("Well you know this is the setup for the story. In 1998 the soldiers were given two gallons of water, "
        "and then they marched all night long. It was brutal. Nobody spoke for hours but the drill went on and on "
        "until sunrise came and the camp woke up again and the sergeant finally smiled at them all. They never "
        "forgot that long night in the desert and the lesson it taught them about discipline.")


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(broll, "NOTION_DIR", str(tmp_path / "notions"))
    monkeypatch.setattr(broll, "HERO_TAKES", 1)
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    broll.FILTERS.clear()


class TestTheParserSaysWhatItDrops:
    def _data(self, words, *anchors):
        idx = {w["text"]: i for i, w in enumerate(words)}
        return {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": a, "subject": a, **extra}
                            for a, extra in anchors]}

    def test_the_worth_decides_between_two_moments_that_touch(self, capsys):
        words = _words(TEXT)
        # "gallons" (t≈8.0) and "water" (t≈9.2) are 1.3 s apart: with a 3 s gap only one stays
        data = self._data(words, ("gallons", {"worth": 2}), ("water,", {"worth": 5}))
        res = broll._parse_moments(data, words, 4, [], gap=3.0)
        assert [m["anchor"] for m in res] == ["water,"] and res[0]["score"] == 5.0
        out = capsys.readouterr().out
        assert 'Moment "gallons"' in out and "dropped: 0.8 s from \"water,\" (worth 2 against 5)" in out
        assert broll.FILTERS["parser: too close"] == 1
        # without a worth, the earlier one stays (the historical behaviour)
        broll.FILTERS.clear()
        res = broll._parse_moments(self._data(words, ("gallons", {}), ("water,", {})), words, 4, [], gap=3.0)
        assert [m["anchor"] for m in res] == ["gallons"] and res[0]["score"] == 1.0

    def test_beyond_n_the_least_worth_goes_and_it_is_said(self, capsys):
        words = _words(TEXT)
        data = self._data(words, ("soldiers", {"worth": 4}), ("marched", {"worth": 1}), ("sergeant", {"worth": 5}))
        res = broll._parse_moments(data, words, 2, [], gap=3.0)
        assert [m["anchor"] for m in res] == ["soldiers", "sergeant"]
        assert 'Moment "marched"' in capsys.readouterr().out and broll.FILTERS["parser: beyond n"] == 1

    def test_every_other_drop_is_named(self, capsys):
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"moments": [{"anchor": "unicorn", "time": 20.0, "image_prompt": "x"},
                            {"anchor": "setup", "time": words[idx["setup"]]["start"], "image_prompt": "x"},
                            {"anchor": "drill", "time": words[idx["drill"]]["start"], "image_prompt": "x", "subject": "drill"},
                            {"anchor": "drill went", "time": words[idx["drill"]]["start"], "image_prompt": "y", "subject": "drill"}]}
        res = broll._parse_moments(data, words, 4, [], gap=3.0)
        assert [m["anchor"] for m in res] == ["drill"]
        out = capsys.readouterr().out
        assert "its words are not in the transcript there" in out and "in the hook, the tail" in out
        assert 'the same thing as "drill"' in out
        assert broll.FILTERS["parser: anchor not found"] == 1 and broll.FILTERS["parser: outside the window"] == 1
        assert broll.FILTERS["parser: same subject"] == 1
        assert broll.filters_line() == "parser: anchor not found 1, parser: outside the window 1, parser: same subject 1"

    def test_a_bad_worth_is_one(self):
        assert broll._worth(None) == 1.0 and broll._worth("x") == 1.0 and broll._worth(9) == 1.0 and broll._worth(3) == 3.0

    def test_the_editor_is_asked_for_the_worth(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt, schema=schema) or {"moments": []})
        broll.plan_with_claude({}, _words(TEXT), 4, [], hero=True)
        assert '"worth": 1-5, how much this picture adds to the clip' in seen["prompt"]
        assert seen["schema"]["properties"]["moments"]["items"]["properties"]["worth"] == {"type": "integer"}
        assert "ALREADY SHOWN" not in seen["prompt"]


class TestTheFactsAreNotAcronymsOrAges:
    def test_or_and_his_40s_are_not_facts(self):
        facts = broll.facts_of("A man in his 40s in a UCSF OR, an IV line, 4,000 seats, the 1980s look.")
        assert "ucsf" in facts and "4000" in facts and "1980" in facts
        assert "or" not in facts and "iv" not in facts and "40" not in facts


class TestTheGlossarySentenceIsNotAFact:
    def test_the_notion_label_glued_by_apply_notions_is_not_read(self):
        draft = ("A brain MRI scan glows on a lightbox in a dim room. Draw Mesial temporal sclerosis the channel's usual "
                 "way: A medical brain scan (MRI or CT) showing the temporal lobe region.")
        assert broll.lost_facts(draft, "a brain mri scan glows on a lightbox, the temporal lobe marked") == []
        assert broll.lost_facts("The White House behind a cage. Draw UFC the channel's usual way: a cage.", "a cage at night") == ["house", "white"]


class TestTheLatestSubjectsMemoryIsGone:
    def test_nothing_left(self):
        for name in ("recent_subjects", "remember_subjects", "RECENT_RULE", "RECENT_MAX", "_recent_path"):
            assert not hasattr(broll, name), name
        assert "{recent}" not in broll.CLAUDE_PLAN_PROMPT


class TestANotionTagHoldsWhenTheSubjectIsWhatTheGlossaryDraws:
    BRIEF = {"glossary": [{"term": "Mesial temporal sclerosis", "meaning": "scarring of the temporal lobe",
                           "visual": "A medical brain scan (MRI or CT) showing the temporal lobe region"},
                          {"term": "Ego dissolution", "meaning": "the self drops",
                           "visual": "A person sitting in meditation, boundaries dissolving"}], "stories": []}

    def test_brain_scan_is_the_scan_of_the_notion(self):
        ms = [{"t": 5.0, "anchor": "temporal lobe", "query": "temporal lobe", "subject": "brain scan", "notion": "Mesial temporal sclerosis", "prompt": "p"},
              {"t": 9.0, "anchor": "old bullshit", "query": "old bullshit", "subject": "box of old belongings", "notion": "Ego dissolution", "prompt": "q"}]
        broll.apply_notions(ms, self.BRIEF, "he talks about the scan of the temporal lobe and old bullshit")
        assert ms[0]["notion"] == "Mesial temporal sclerosis" and ms[1]["notion"] == ""
        assert broll.FILTERS["notion: tag dropped"] == 1


class TestTheGuards:
    def test_every_guard_that_fires_goes_out(self):
        _p, extra = broll.guardrails("Two surgeons read a chart on an iPhone, hands on the page, a patient beside them.",
                                     faces=True, people="group")
        _p, one = broll.guardrails("A surgeon reads a chart.", faces=True, people="one")
        assert "Hands natural and well formed" in one          # one person declared: the hands sentence too
        for part in ("Show exactly 2 surgeons", "plain colour", "generic unbranded", "The group is seen as a whole"):
            assert part in extra, part
        assert "from the side or partly out of frame" not in extra
        assert broll.FILTERS["guard: count"] == 1 and broll.FILTERS["guard: text"] == 2 and broll.FILTERS["guard: brand"] == 1
        assert broll.FILTERS["guard: hands"] == 1 and broll.FILTERS["guard: crowd"] == 1 and broll.FILTERS["guard: person"] == 1
        assert not hasattr(broll, "GUARD_MAX")


class TestTheSecondLook:
    def test_a_doubtful_card_goes_to_the_judge(self, monkeypatch):
        calls = []
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(ai_brain, "route", lambda k, *a, **kw: "claude")
        monkeypatch.setattr(ai_brain, "stage_model", lambda k, *a, **kw: {"broll": "sonnet", "image_review": "haiku"}[k])

        def fake(cands, words, model=None, size=512):
            calls.append((model, [os.path.basename(c["file"]) for c in cands]))
            if model == "haiku":
                return [{"score": 3, "look": 4, "file": "broll_0.jpg"}, {"score": 5, "look": 2, "file": "broll_1.jpg"},
                        {"score": 5, "look": 5, "file": "broll_2.jpg"}]
            return [{"score": 4, "look": 4, "file": os.path.basename(c["file"]), "by": "judge"} for c in cands]

        monkeypatch.setattr(broll, "review_with_claude", fake)
        cands = [{"file": f"/x/broll_{k}.jpg", "layout": "card"} for k in range(3)]
        out = broll._review_images(cands, [])          # the dispatch (v17: review_images adds the cold read)
        assert calls == [("haiku", ["broll_0.jpg", "broll_1.jpg", "broll_2.jpg"]), ("sonnet", ["broll_0.jpg", "broll_1.jpg"])]
        assert [r.get("by") for r in out] == ["judge", "judge", None] and out[2]["score"] == 5

    def test_one_model_for_both_means_one_pass(self, monkeypatch):
        calls = []
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(ai_brain, "route", lambda k, *a, **kw: "claude")
        monkeypatch.setattr(ai_brain, "stage_model", lambda k, *a, **kw: "sonnet")
        monkeypatch.setattr(broll, "review_with_claude", lambda cands, words, model=None, size=512: calls.append(model) or [{"score": 3, "look": 3} for _ in cands])
        broll._review_images([{"file": "/x/broll_0.jpg", "layout": "card"}], [])
        assert calls == ["sonnet"]
