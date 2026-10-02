"""The hero at its best (B-roll v2, chantier L): the editor lists three hero concepts and picks one with its
reason, the art director writes it as the clip's poster, the hero is made in several takes the judge sees
together (the best stays), and the reviewer applies the hero test. No model, no ComfyUI."""
import pytest
from PIL import Image

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
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")
    monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)


class TestTheEditor:
    def test_three_concepts_then_one_pick(self, monkeypatch, capsys):
        seen = {}
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"thesis": "T", "hero_options": [{"anchor": "soldiers", "picture": "A line of soldiers at dawn.", "why": "scale"},
                                                {"anchor": "drill", "picture": "A whistle.", "why": "sound"},
                                                {"picture": "no anchor", "why": "x"}, {"picture": "a fourth one"}, "junk"],
                "moments": [{"anchor": "soldiers", "time": words[idx["soldiers"]]["start"], "image_prompt": "x", "hero": True,
                             "hero_why": "  The widest, the  most felt. "},
                            {"anchor": "drill", "time": words[idx["drill"]]["start"], "image_prompt": "y"}]}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt, schema=schema) or data)
        moments = broll.plan_with_claude({}, words, 4, [], hero=True)
        p = seen["prompt"]
        assert 'First list "hero_options": THREE different candidate concepts' in p and '"hero_why"' in p and "HERO IDEAS" in p
        props = seen["schema"]["properties"]
        assert props["hero_options"]["items"]["required"] == ["picture"] and props["moments"]["items"]["properties"]["hero_why"] == {"type": "string"}
        assert moments[0]["hero_why"] == "The widest, the most felt." and moments[1]["hero_why"] == ""
        assert [o["picture"] for o in moments[0]["hero_options"]] == ["A line of soldiers at dawn.", "A whistle.", "no anchor"]
        assert moments[1]["hero_options"] == moments[0]["hero_options"]
        out = capsys.readouterr().out
        assert "Hero options: A line of soldiers at dawn. | A whistle. | no anchor -> chosen \"soldiers\"" in out

    def test_the_historical_layouts_ask_nothing_of_it(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt, schema=schema) or {"moments": []})
        broll.plan_with_claude({}, _words(TEXT), 4, [], hero=False)
        assert "hero_options" not in seen["prompt"] and "hero_options" not in seen["schema"]["properties"]


class TestTheArtDirector:
    def test_the_hero_is_the_poster(self):
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "hero": True, "hero_why": "the widest frame"},
              {"t": 9.0, "anchor": "b", "prompt": "q", "subject": "t", "hero": False}]
        text = broll._art_prompt(ms, {})
        assert "THE HERO, the clip's poster — why this one: the widest frame" in text and text.count("THE HERO, the clip's poster") == 1
        assert "THE HERO is the clip's poster: one unforgettable frame" in text
        assert "THE HERO, the clip's poster" not in broll._art_prompt(ms, {}, mixed=False, rise=True)


class TestTheReviewer:
    def test_the_hero_test_only_with_a_hero(self):
        assert broll._hero_test([{"layout": "card", "m": {}}]) == ""
        assert "THE HERO TEST" in broll._hero_test([{"layout": "hero", "m": {}}])
        assert "which take is the better" in broll.HERO_TEST
        words = _words(TEXT)
        lines = broll._review_lines([{"file": "/x/broll_0.jpg", "take": 2, "m": {"t": 5.0, "idea": "i", "said": "s", "prompt": "p", "hero": True}}], words)
        assert "take 2 of the same moment: compare the takes, score each apart" in lines[0]

    def test_the_claude_review_carries_the_hero_test(self, monkeypatch, tmp_path):
        p = tmp_path / "broll_1.jpg"
        Image.new("RGB", (896, 1600), (1, 2, 3)).save(p)
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **kw: seen.update(prompt=prompt) or {"reviews": []})
        broll.review_with_claude([{"file": str(p), "layout": "hero", "m": {"t": 5.0, "idea": "i", "said": "s", "prompt": "p", "hero": True, "thesis": "T"}}], _words(TEXT))
        assert "THE CLIP'S POINT: T" in seen["prompt"] and seen["prompt"].index("THE CLIP'S POINT") < seen["prompt"].index("THE HERO TEST")


class TestInTheJob:
    @pytest.fixture
    def stubs(self, monkeypatch):
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            made.append({"out": out_path.rsplit("/", 1)[-1], "size": size, **kw})
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

    def test_two_takes_judged_together_the_better_one_stays(self, monkeypatch, stubs):
        made, tr, words = stubs
        monkeypatch.setattr(broll, "HERO_TAKES", 2)
        calls = []

        def review(cands, words_):
            calls.append([(c["file"].rsplit("/", 1)[-1], c.get("take")) for c in cands])
            return [{"score": 5, "look": 5} if c.get("take") == 2 else {"score": 4, "look": 4} if c.get("take") == 1
                    else {"score": 5, "look": 5} for c in cands]

        monkeypatch.setattr(broll, "review_images", review)
        rep = self._run(tr, words)
        heroes = [m for m in made if m["size"] == (896, 1600)]
        assert len(heroes) == 2 and heroes[1]["out"].endswith("_t2.jpg") and heroes[0]["seed"] != heroes[1]["seed"]
        # both takes went to the judge in the same call
        takes_seen = [t for call in calls for _f, t in call if t]
        assert sorted(takes_seen) == [1, 2] and len(calls) == 1
        hero = next(it for it in rep["items"] if it["layout"] == "hero")
        assert hero["take"] == 2 and hero["score"] == 5 and hero["seed"] == heroes[1]["seed"]
        assert sum(it["layout"] == "hero" for it in rep["items"]) == 1 and len(rep["items"]) == 3
        assert all("take" not in it for it in rep["items"] if it["layout"] != "hero")

    def test_a_tie_keeps_the_first_take(self, monkeypatch, stubs):
        made, tr, words = stubs
        monkeypatch.setattr(broll, "HERO_TAKES", 3)
        monkeypatch.setattr(broll, "review_images", lambda cands, words_: [{"score": 5, "look": 4} for _ in cands])
        rep = self._run(tr, words)
        assert len([m for m in made if m["size"] == (896, 1600)]) == 3
        assert next(it for it in rep["items"] if it["layout"] == "hero")["take"] == 1

    def test_one_take_is_the_old_way(self, monkeypatch, stubs):
        made, tr, words = stubs
        monkeypatch.setattr(broll, "HERO_TAKES", 1)
        monkeypatch.setattr(broll, "review_images", lambda cands, words_: [{"score": 5, "look": 5} for _ in cands])
        rep = self._run(tr, words)
        assert len([m for m in made if m["size"] == (896, 1600)]) == 1
        assert "take" not in next(it for it in rep["items"] if it["layout"] == "hero")

    def test_the_recipe_asks_two_takes(self):
        assert broll.HERO_TAKES == 2
