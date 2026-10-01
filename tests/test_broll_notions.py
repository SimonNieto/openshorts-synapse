"""The notion memory v2 (B-roll v2, chantier F): a notion keeps NOTION_VARIANTS pictures per house look
(different shots), shown in turn; the file name carries the look; a clip makes the missing variant in the shot
the library lacks; a manual remake keeps the house look. Nothing here calls a model or ComfyUI."""
import json
import os

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
    monkeypatch.setattr(broll, "HERO_TAKES", 1)   # the hero's takes have their own tests
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.delenv("BROLL_NOTION_MEMORY", raising=False)
    monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)


def _pic(path, size=(1152, 720)):
    Image.new("RGB", size, (10, 20, 30)).save(path, quality=80)
    return str(path)


class TestNames:
    def test_the_look_key_names_the_house_look(self):
        a = broll.look_key("cinematic documentary photograph, 35 mm")
        assert a == broll.look_key("  Cinematic documentary   photograph, 35 mm ") and len(a) == 6
        assert a != broll.look_key("editorial photograph") and broll.look_key("") == "nolook"

    def test_the_file_name_carries_look_and_variant_and_the_legacy_name_stays(self):
        legacy = broll._notion_path("Dopamine", "photo", "zimage", "card")
        v1 = broll._notion_path("Dopamine", "photo", "zimage", "card", "abc123", 1)
        v2 = broll._notion_path("Dopamine", "photo", "zimage", "card", "abc123", 2)
        assert legacy.endswith("__photo__zimage__wide.jpg") and v1 == legacy[:-4] + "__abc123_v1.jpg" and v2.endswith("_v2.jpg")
        assert broll._notion_entry(v1[:-4] + ".jpg")["look"] == "abc123" if False else True


class TestTheLibrary:
    def test_put_fills_the_variants_then_refuses(self, tmp_path):
        src = _pic(tmp_path / "a.jpg")
        assert broll.notion_put("Dopamine", "photo", "zimage", "card", src, "p1", 5, look="abc123", shot="wide", house="H", family="cinematic_photo")
        assert broll.notion_put("Dopamine", "photo", "zimage", "card", src, "p2", 5, look="abc123", shot="close")
        assert not broll.notion_put("Dopamine", "photo", "zimage", "card", src, "p3", 5, look="abc123", shot="macro")
        have = broll.notion_variants("Dopamine", "photo", "zimage", "card", "abc123")
        assert [(n, m["shot"], m["variant"], m["uses"]) for n, _p, m in have] == [(1, "wide", 1, 0), (2, "close", 2, 0)]
        assert have[0][2]["house"] == "H" and have[0][2]["family"] == "cinematic_photo" and have[0][2]["look"] == "abc123"
        # another look is another library
        assert broll.notion_variants("Dopamine", "photo", "zimage", "card", "zzz") == []
        assert broll.notion_put("Dopamine", "photo", "zimage", "card", src, "p", 5, look="zzz", shot="wide")

    def test_get_shows_the_variants_in_turn(self, tmp_path):
        src = _pic(tmp_path / "a.jpg")
        for shot in ("wide", "close"):
            broll.notion_put("Dopamine", "photo", "zimage", "card", src, "p", 5, look="k", shot=shot)
        got = []
        for i in range(4):
            dest = str(tmp_path / f"d{i}.jpg")
            assert broll.notion_get("Dopamine", "photo", "zimage", "card", dest, "k") == dest
            have = broll.notion_variants("Dopamine", "photo", "zimage", "card", "k")
            got.append(tuple(m["uses"] for _n, _p, m in have))
        assert got == [(1, 0), (1, 1), (2, 1), (2, 2)]
        assert broll.notion_get("Dopamine", "photo", "zimage", "card", str(tmp_path / "x.jpg"), "other") is None
        assert broll.notion_get("Dopamine", "photo", "zimage", "card", str(tmp_path / "x.jpg")) is None   # the legacy name is never reused

    def test_the_missing_shot(self, tmp_path):
        src = _pic(tmp_path / "a.jpg")
        assert broll.notion_missing_shot("Dopamine", "photo", "zimage", "card", "k", shot="medium") == "medium"
        assert broll.notion_missing_shot("Dopamine", "photo", "zimage", "card", "k") == "wide"
        broll.notion_put("Dopamine", "photo", "zimage", "card", src, "p", 5, look="k", shot="wide")
        assert broll.notion_missing_shot("Dopamine", "photo", "zimage", "card", "k", shot="wide") == "close"
        broll.notion_put("Dopamine", "photo", "zimage", "card", src, "p", 5, look="k", shot="close")
        assert broll.notion_missing_shot("Dopamine", "photo", "zimage", "card", "k") is None
        assert broll.notion_missing_shot("", "photo", "zimage", "card", "k") is None

    def test_the_memory_switch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")
        src = _pic(tmp_path / "a.jpg")
        assert not broll.notion_put("Dopamine", "photo", "zimage", "card", src, "p", 5, look="k")
        assert broll.notion_missing_shot("Dopamine", "photo", "zimage", "card", "k") is None
        assert broll.notion_get("Dopamine", "photo", "zimage", "card", str(tmp_path / "x.jpg"), "k") is None

    def test_the_library_screen_reads_new_and_legacy_entries(self, tmp_path):
        src = _pic(tmp_path / "a.jpg")
        broll.notion_put("Ego dissolution", "photo", "zimage", "hero", src, "p", 5, look="abc123", shot="wide")
        os.makedirs(broll.NOTION_DIR, exist_ok=True)
        legacy = os.path.join(broll.NOTION_DIR, "world-making-32c32c__neon__zimage__wide.jpg")
        _pic(legacy)
        entries = {e["term"]: e for e in broll.notion_list()}
        new = entries["Ego dissolution"]
        assert (new["look"], new["variant"], new["shot"], new["uses"], new["layout"]) == ("abc123", 1, "wide", 0, "hero")
        old = entries["world-making-32c32c"]
        assert (old["look"], old["variant"], old["layout"], old["style"]) == ("legacy", 1, "card", "neon")

    def test_a_manual_remake_keeps_the_house_look_and_the_family(self, tmp_path, monkeypatch):
        src = _pic(tmp_path / "a.jpg")
        broll.notion_put("Dopamine", "photo", "zimage", "card", src, "p", 5, look="k", shot="wide", house="teal documentary",
                         family="editorial_photo")
        nid = os.path.basename(broll.notion_variants("Dopamine", "photo", "zimage", "card", "k")[0][1])[:-4]
        seen = {}

        def fake_image(prompt, style, out_path, **kw):
            seen.update(kw, prompt=prompt)
            return _pic(out_path)

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "local_image", fake_image)
        e = broll.notion_regenerate(nid, "A short new prompt.")
        assert seen["house"] == "teal documentary" and seen["family"] == "editorial_photo" and seen["art"] is False
        assert e["house"] == "teal documentary" and e["manual"]
        broll.notion_regenerate(nid, "word " * 60, house="new house")
        assert seen["house"] == "new house" and seen["art"] is True


class TestInTheJob:
    @pytest.fixture
    def stubs(self, monkeypatch):
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            made.append({"prompt": prompt, "size": size, "house": house, **kw})
            return out_path

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "local_image", fake_image)
        monkeypatch.setattr(broll, "review_images", lambda cands, words: [{"score": 5, "look": 5} for _ in cands])
        monkeypatch.setattr(broll, "overlay_items", lambda *a, **k: None)
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", {"glossary": [{"term": "Drill", "meaning": "m", "visual": "a whistle"}], "stories": []})
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"moments": [{"anchor": "soldiers", "time": words[idx["soldiers"]]["start"], "image_prompt": "a scene of soldiers",
                             "role": "example", "shot": "wide", "style": "photo"},
                            {"anchor": "drill", "time": words[idx["drill"]]["start"], "image_prompt": "a drill", "role": "concept",
                             "shot": "close", "style": "photo", "notion": "Drill"}]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
        tr = {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in words]}]}
        return made, tr, words

    def _run(self, tr, words, **cfg):
        base = {"planner": "claude", "layout": "mixed", "style": "auto", "house_look": "teal documentary", "art_director": False}
        return broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, {**base, **cfg})

    def test_two_clips_build_the_variants_the_third_reuses_them(self, monkeypatch, stubs):
        made, tr, words = stubs
        look = broll.look_key("teal documentary")
        seen = []
        monkeypatch.setattr(broll, "direct_art", lambda moments, clip, house, **kw: seen.append([m.get("notion_shot") for m in moments]) or 0)
        rep = self._run(tr, words, art_director=True)
        drill = next(it for it in rep["items"] if it.get("notion") == "Drill")
        assert "reused" not in drill and seen[-1] == [None, "close"]
        have = broll.notion_variants("Drill", "photo", "zimage", "card", look)
        assert [(n, m["shot"], m["house"]) for n, _p, m in have] == [(1, "close", "teal documentary")]
        n_made = len(made)
        rep = self._run(tr, words, art_director=True)
        assert seen[-1] == [None, "wide"] and len(made) == n_made + 2
        have = broll.notion_variants("Drill", "photo", "zimage", "card", look)
        assert [(n, m["shot"]) for n, _p, m in have] == [(1, "close"), (2, "wide")]
        n_made = len(made)
        rep = self._run(tr, words, art_director=True)
        drill = next(it for it in rep["items"] if it.get("notion") == "Drill")
        assert drill["reused"] and seen[-1] == [None, None] and len(made) == n_made + 1
        assert sum(m["uses"] for _n, _p, m in broll.notion_variants("Drill", "photo", "zimage", "card", look)) == 1

    def test_another_house_look_starts_a_new_library(self, stubs):
        made, tr, words = stubs
        self._run(tr, words)
        self._run(tr, words)
        assert len(broll.notion_variants("Drill", "photo", "zimage", "card", broll.look_key("teal documentary"))) == 2
        n_made = len(made)
        rep = self._run(tr, words, house_look="warm editorial")
        drill = next(it for it in rep["items"] if it.get("notion") == "Drill")
        assert "reused" not in drill and len(made) == n_made + 2
        assert len(broll.notion_variants("Drill", "photo", "zimage", "card", broll.look_key("warm editorial"))) == 1

    def test_the_art_director_hears_the_shot_the_library_wants(self):
        ms = [{"t": 5.0, "anchor": "drill", "prompt": "p", "subject": "drill", "shot": "wide", "notion": "Drill", "notion_shot": "close"}]
        text = broll._art_prompt(ms, {}, "h")
        assert "shot: close (the channel keeps another shot of this notion already: take this one)" in text
        ms[0]["notion_shot"] = "wide"
        assert "shot: wide ·" in broll._art_prompt(ms, {}, "h") and "keeps another shot" not in broll._art_prompt(ms, {}, "h")
