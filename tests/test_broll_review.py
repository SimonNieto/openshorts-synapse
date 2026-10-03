"""The two-axis review (B-roll v2, chantier E): the reviewer scores the meaning (score) and the look (look); a
card is kept at score >= 4 and look >= 3, a hero at score >= 4 and look >= 4, judged at 768 px by the B-roll's
judge; a card is made again once, a hero twice, from a better prompt in the art director's grammar; both
scores land in the items and in the playbook export. No model is called."""
import json
import os

import pytest
from PIL import Image

import ai_brain
import broll
import playbook


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
LONG = ("A lone soldier walks across the cracked desert floor at dawn, canteen in hand, boots dusted red. The camp "
        "sits far behind him, three canvas tents and a cold fire pit. The frame is 9:16, the man in the upper-middle "
        "third, a blurred creosote bush close in the foreground, the lower third an empty dark plain. 35 mm lens at "
        "chest height, ten metres away. First sun from the right, low and warm, long soft shadows. Teal shadow in the "
        "sand, amber rim on his shoulders, fine grain. Sweat-stained cotton, scuffed leather, a bent tent peg. Mood: "
        "spent, resolute, quiet.")


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(broll, "NOTION_DIR", str(tmp_path / "notions"))
    monkeypatch.setattr(broll, "HERO_TAKES", 1)   # the hero's takes have their own tests
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")
    monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)


class TestThePrompt:
    def test_the_reviewer_is_asked_for_the_look(self):
        text = broll.REVIEW_PROMPT.format(frame=broll._review_frame([{"layout": "card"}]), items="- x")
        assert "STEP 3 - THE LOOK" in text and '"look" 1-5' in text and "artefacts (hands, faces, lettering" in text
        assert "ART-DIRECTED, write it in that same grammar" in text and "80 to 120 words" in text
        assert broll.REVIEW_SCHEMA["properties"]["reviews"]["items"]["properties"]["look"] == {"type": "integer"}
        assert "look" in broll.REVIEW_SCHEMA["properties"]["reviews"]["items"]["required"]

    def test_an_art_directed_picture_shows_its_prompt_to_the_reviewer(self):
        words = _words(TEXT)
        art = {"file": "/x/broll_0.jpg", "m": {"t": 5.0, "idea": "i", "said": "s", "prompt": LONG, "art": True}}
        plain = {"file": "/x/broll_1.jpg", "m": {"t": 9.0, "idea": "i", "said": "s", "prompt": "A drill."}}
        lines = broll._review_lines([art, plain], words)
        assert "ART-DIRECTED" in lines[0] and LONG[:40] in lines[0]
        assert "ART-DIRECTED" not in lines[1]


class TestTheKeepRule:
    def _c(self, score, look, layout="card"):
        return {"score": score, "look_score": look, "layout": layout}

    def test_cards_need_look_three_heroes_four(self):
        cands = [self._c(5, 2), self._c(4, 3), self._c(4, 3, "hero"), self._c(4, 4, "hero"), self._c(5, None)]
        kept = broll._keep_meaningful(cands)
        assert kept == [cands[1], cands[3], cands[4]]
        assert broll.LOOK_CARD == 3 and broll.LOOK_HERO == 4

    def test_the_floor_only_fills_with_passing_looks(self):
        cands = [self._c(3, 2), self._c(3, 3), self._c(2, 5)]
        assert broll._keep_meaningful(cands) == [cands[1]]

    def test_take_review_and_better(self):
        c = broll._take_review({"layout": "card"}, {"score": "4", "look": 3.0, "problem": "p", "better_prompt": "  a  b "})
        assert (c["score"], c["look_score"], c["problem"], c["better_prompt"]) == (4, 3, "p", "a b")
        assert broll._take_review({}, {"score": 4, "look": 9})["look_score"] is None
        assert broll._take_review({}, {"score": 4, "look": True})["look_score"] is None
        assert broll._take_review({}, {"score": 4})["look_score"] is None
        assert broll._better({"score": 4, "look_score": 3}, {"score": 3, "look_score": 5})
        assert broll._better({"score": 4, "look_score": 4}, {"score": 4, "look_score": 3})
        assert not broll._better({"score": 4, "look_score": 3}, {"score": 4, "look_score": 3})
        assert broll._needs_redo({"score": 4, "look_score": 2, "layout": "card"})
        assert broll._needs_redo({"score": 4, "look_score": 3, "layout": "hero"})
        assert not broll._needs_redo({"score": 4, "look_score": 3, "layout": "card"})


class TestWhoJudges:
    def test_the_hero_goes_to_the_broll_judge_at_768(self, monkeypatch):
        calls = []
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(ai_brain, "route", lambda k, *a, **kw: "claude")
        monkeypatch.setattr(ai_brain, "stage_model", lambda k, *a, **kw: {"broll": "sonnet", "image_review": "haiku"}[k])

        def fake_claude(cands, words, model=None, size=512):
            calls.append((model, size, [os.path.basename(c["file"]) for c in cands]))
            return [{"score": 5, "look": 5, "file": os.path.basename(c["file"])} for c in cands]

        monkeypatch.setattr(broll, "review_with_claude", fake_claude)
        cands = [{"file": "/x/broll_0.jpg", "layout": "card"}, {"file": "/x/broll_1.jpg", "layout": "hero"},
                 {"file": "/x/broll_2.jpg", "layout": "card"}]
        out = broll._review_images(cands, [])          # the dispatch (v17: review_images adds the cold read)
        assert [r["file"] for r in out] == ["broll_0.jpg", "broll_1.jpg", "broll_2.jpg"]
        assert ("sonnet", broll.HERO_REVIEW_PX, ["broll_1.jpg"]) in calls
        assert ("haiku", 512, ["broll_0.jpg", "broll_2.jpg"]) in calls
        assert broll.HERO_REVIEW_PX == 768

    def test_a_hero_alone_is_judged_by_the_judge_too(self, monkeypatch):
        calls = []
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(ai_brain, "route", lambda k, *a, **kw: "gemini")
        monkeypatch.setattr(ai_brain, "stage_model", lambda k, *a, **kw: "sonnet")
        monkeypatch.setattr(broll, "review_with_claude", lambda cands, words, model=None, size=512: calls.append((model, size)) or [{"score": 5, "look": 5}])
        monkeypatch.setattr(broll, "review_with_gemini", lambda cands, words: pytest.fail("the hero is never Gemini's"))
        broll._review_images([{"file": "/x/broll_1.jpg", "layout": "hero"}], [])
        assert calls == [("sonnet", 768)]

    def test_the_review_is_resized_to_the_size_asked(self, monkeypatch, tmp_path):
        p = tmp_path / "broll_1.jpg"
        Image.new("RGB", (896, 1600), (1, 2, 3)).save(p)
        seen = {}

        def fake_json(prompt, schema, attach=None, **kw):
            seen["sizes"] = [Image.open(a).size for a in attach]
            return {"reviews": []}

        monkeypatch.setattr(broll, "claude_json", fake_json)
        cands = [{"file": str(p), "layout": "hero", "m": {"t": 5.0, "idea": "i", "said": "s", "prompt": "p", "hero": True}}]
        broll.review_with_claude(cands, _words(TEXT), size=768)
        assert seen["sizes"] == [(430, 768)]
        broll.review_with_claude(cands, _words(TEXT))
        assert seen["sizes"] == [(287, 512)]


class TestInTheJob:
    @pytest.fixture
    def stubs(self, monkeypatch):
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            made.append({"prompt": prompt, "out": os.path.basename(out_path), "size": size, **kw})
            return out_path

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "local_image", fake_image)
        monkeypatch.setattr(broll, "overlay_items", lambda *a, **k: None)
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": "a scene of " + a, "role": "example",
                             "shot": s, "style": "photo"} for a, s in (("soldiers", "wide"), ("drill", "close"), ("sergeant", "medium"))]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
        tr = {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in words]}]}
        return made, tr, words

    def _run(self, tr, words, **cfg):
        base = {"planner": "claude", "layout": "mixed", "style": "auto", "house_look": "h", "art_director": False}
        return broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, {**base, **cfg})

    def test_both_scores_land_in_the_items(self, monkeypatch, stubs):
        made, tr, words = stubs
        monkeypatch.setattr(broll, "review_images", lambda cands, words_: [{"score": 5, "look": 4} for _ in cands])
        rep = self._run(tr, words)
        assert all(it["score"] == 5 and it["look_score"] == 4 for it in rep["items"])

    @staticmethod
    def _ideas(monkeypatch, text="Another scene."):
        """v16: another idea is the art director's (another_idea), not the review's."""
        calls = []

        def fake(cands, clip, clip_text="", **kw):
            calls.append([c["k"] for c in cands])
            for c in cands:
                c["new"] = {"prompt": text, "judge": "", "fx": None, "people": "none"}
                c["new_prompt"] = text
            return len(cands)

        monkeypatch.setattr(broll, "another_idea", fake)
        monkeypatch.setattr(broll, "direct_art", lambda *a, **k: 0)
        return calls

    def test_a_hero_is_made_again_twice_then_dropped(self, monkeypatch, stubs):
        """v15: the first redo is the same idea made to work; once it has failed twice, the next one is another idea
        (v16: the art director's), never the same scene reworded."""
        made, tr, words = stubs
        calls = self._ideas(monkeypatch)
        monkeypatch.setattr(broll, "review_images",
                            lambda cands, words_: [{"score": 4, "look": 2, "better_prompt": "Brighter."}
                                                   if c["layout"] == "hero" else {"score": 4, "look": 4} for c in cands])
        rep = self._run(tr, words, art_director=True)
        assert len(calls) == 1              # asked once the hero had failed twice (its budget ends with that attempt)
        hero_tries = [m for m in made if m["size"] == (896, 1600)]
        k = hero_tries[0]["out"][len("broll_"):-len(".jpg")]
        assert len(hero_tries) == 3 and [m["out"] for m in hero_tries][1:] == [f"broll_{k}_v2.jpg", f"broll_{k}_v3.jpg"]
        assert [m["prompt"] for m in hero_tries][1:] == ["Brighter.", "Another scene."]
        assert broll.FILTERS["redo: a new idea"] == 1
        assert not any(it["layout"] == "hero" for it in rep["items"]) and len(rep["items"]) == 2

    def test_a_card_failed_twice_gets_another_idea(self, monkeypatch, stubs):
        """v15b: a card's take and its redo both failed — one more attempt, with another idea, then the best one."""
        made, tr, words = stubs
        calls = self._ideas(monkeypatch)
        monkeypatch.setattr(broll, "review_images",
                            lambda cands, words_: [{"score": 5, "look": 5} if c["layout"] == "hero" or c["file"].endswith("_v3.jpg")
                                                   else {"score": 3, "look": 2, "better_prompt": "Closer."}
                                                   for c in cands])
        rep = self._run(tr, words, art_director=True)
        assert len(calls) == 1 and len(calls[0]) == 2       # ONE call of the director for both cards
        cards = [m for m in made if m["size"] == (1152, 720)]
        assert [m["prompt"] for m in cards if m["out"].endswith("_v2.jpg")] == ["Closer.", "Closer."]
        assert [m["prompt"] for m in cards if m["out"].endswith("_v3.jpg")] == ["Another scene.", "Another scene."]
        assert broll.FILTERS["redo: a new idea"] == 2
        kept = [it for it in rep["items"] if it["layout"] == "card"]
        assert len(kept) == 2 and all(it["prompt"] == "Another scene." and it["score"] == 5 for it in kept)

    def test_an_unsafe_card_gets_another_idea_at_once(self, monkeypatch, stubs):
        made, tr, words = stubs
        self._ideas(monkeypatch)
        monkeypatch.setattr(broll, "review_images",
                            lambda cands, words_: [{"score": 5, "look": 5} if c["layout"] == "hero" or c["file"].endswith("_v2.jpg")
                                                   else {"score": 4, "look": 4, "safe": False, "better_prompt": "Closer."}
                                                   for c in cands])
        rep = self._run(tr, words, art_director=True)
        cards = [m for m in made if m["size"] == (1152, 720)]
        assert [m["prompt"] for m in cards if m["out"].endswith("_v2.jpg")] == ["Another scene.", "Another scene."]
        assert not any(m["out"].endswith("_v3.jpg") for m in cards)
        assert len([it for it in rep["items"] if it["layout"] == "card"]) == 2

    def test_without_another_idea_a_twice_failed_hero_stops(self, monkeypatch, stubs):
        made, tr, words = stubs
        monkeypatch.setattr(broll, "review_images",
                            lambda cands, words_: [{"score": 4, "look": 2, "better_prompt": "Brighter."} if c["layout"] == "hero"
                                                   else {"score": 4, "look": 4} for c in cands])
        self._run(tr, words)
        assert len([m for m in made if m["size"] == (896, 1600)]) == 2

    def test_a_card_is_made_again_once_and_the_better_one_wins(self, monkeypatch, stubs):
        made, tr, words = stubs
        monkeypatch.setattr(broll, "review_images",
                            lambda cands, words_: [{"score": 4, "look": 4} if c["file"].endswith("_v2.jpg")
                                                   else {"score": 3, "look": 2, "better_prompt": "Closer."} if c["layout"] == "card"
                                                   else {"score": 5, "look": 5} for c in cands])
        rep = self._run(tr, words)
        cards = [m for m in made if m["size"] == (1152, 720)]
        assert len(cards) == 4 and sum(m["prompt"] == "Closer." for m in cards) == 2
        kept_cards = [it for it in rep["items"] if it["layout"] == "card"]
        assert len(kept_cards) == 2 and all(it["prompt"] == "Closer." and it["score"] == 4 and it["look_score"] == 4 for it in kept_cards)

    def test_a_long_better_prompt_of_an_art_picture_stays_art(self, monkeypatch, stubs):
        made, tr, words = stubs

        def fake_direct(moments, clip, **kw):
            for m in moments:
                m["prompt_editor"], m["prompt"], m["art"] = m["prompt"], LONG, True
            return len(moments)

        monkeypatch.setattr(broll, "direct_art", fake_direct)
        monkeypatch.setattr(broll, "review_images",
                            lambda cands, words_: [{"score": 4, "look": 5} if c["file"].endswith("_v2.jpg")
                                                   else {"score": 2, "look": 2, "better_prompt": LONG + " Brighter."} if c["layout"] == "hero"
                                                   else {"score": 2, "look": 2, "better_prompt": "Closer."} if c["file"].endswith("broll_1.jpg")
                                                   else {"score": 5, "look": 5} for c in cands])
        rep = self._run(tr, words, art_director=True)
        redo = {m["out"]: m for m in made if m["out"].endswith("_v2.jpg")}
        hero_k = next(m["out"] for m in made if m["size"] == (896, 1600))[len("broll_"):-len(".jpg")]
        assert redo[f"broll_{hero_k}_v2.jpg"]["art"] is True and redo["broll_1_v2.jpg"]["art"] is False
        hero = next(it for it in rep["items"] if it["layout"] == "hero")
        assert hero["art"] is True and hero["prompt"].endswith("Brighter.")
        drill = next(it for it in rep["items"] if it["anchor"] == "drill")
        assert "art" not in drill and drill["prompt"] == "Closer."


class TestTheExport:
    def test_the_playbook_export_carries_the_broll_scores(self, tmp_path):
        clip = {"moment_id": "m1", "start": 10.0, "end": 40.0, "video_title_for_youtube_short": "Is this real?",
                "broll": [{"t": 5.0, "dur": 2.2, "layout": "card", "subject": "a cup", "style": "photo", "family": "cinematic_photo",
                           "score": 4, "look_score": 3, "art": True, "prompt": "never exported", "image": "x.jpg"},
                          {"t": 20.0, "dur": 3.0, "layout": "hero", "subject": "sky", "score": 5, "look_score": 5, "notion": "Sky"}]}
        p = playbook.export_clip(clip, str(tmp_path), "x_clip_1.mp4", [])
        data = json.load(open(p, encoding="utf-8"))
        assert data["broll"] == [{"t": 5.0, "dur": 2.2, "layout": "card", "subject": "a cup", "style": "photo", "family": "cinematic_photo",
                                  "score": 4, "look_score": 3, "art": True},
                                 {"t": 20.0, "dur": 3.0, "layout": "hero", "subject": "sky", "score": 5, "look_score": 5, "notion": "Sky"}]
        assert playbook.broll_summary({}) == [] and playbook.broll_summary({"broll": ["junk"]}) == []
