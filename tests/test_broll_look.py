"""The look of every picture ("mixed" layout, B-roll « ambiance », 2-oct-2026): no house sentence, no named grade —
each picture's mood becomes its look sentence (when the art director did not write its prompt) and its own grade,
applied at render time; the older clips' named grades still render the same."""
import os
import tempfile

import pytest
from PIL import Image, ImageStat

import broll
import plus
import visual_mood

from test_broll import TEXT, _transcript


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.delenv("EDIT_STYLE", raising=False)
    monkeypatch.setattr(broll, "NOTION_DIR", tempfile.mkdtemp(prefix="notions_"))
    monkeypatch.setattr(broll, "HERO_TAKES", 1)   # the hero's takes have their own tests
    monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)


class TestProfile:
    def test_the_recipe_has_a_signature_and_no_house_look(self):
        assert plus.BROLL["signature"] == 0.2 and "house_look" not in plus.BROLL and "grade" not in plus.BROLL
        assert plus.sanitize({"broll": {"enabled": True, "house_look": "neon", "grade": "sepia", "signature": 1}})["broll"] == {"enabled": True}


class TestPrompt:
    def test_the_mood_sentence_sits_between_the_scene_and_the_rules(self):
        mood = visual_mood.sentence({"valence": "grim", "intensity": "charged"})
        text = broll._image_text("A brain model on a desk.", "photo", mood=mood)
        assert text.index("A brain model") < text.index("A low-key frame") < text.index(broll.COMMON_RULES)
        assert broll.STYLES["photo"] not in text and "teal" not in text

    def test_an_art_prompt_gets_no_look_sentence(self):
        text = broll._image_text("A long director's prompt.", "photo", art=True, mood="A documentary photograph.")
        assert text == f"A long director's prompt. {broll.ART_RULES}"

    def test_no_mood_leaves_the_historical_prompt_as_before(self):
        # the historical text, spaces included (the image cache keys on it)
        assert broll._image_text("A brain.", "photo") == f"A brain. {broll.STYLES['photo']} {broll.COMMON_RULES}"

    def test_auto_style_in_the_mixed_layout_is_photographic(self, monkeypatch):
        import ai_brain
        from test_broll import _words
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt, schema=schema) or {"moments": []})
        words = _words(TEXT)
        broll.plan_with_claude({}, words, 4, [], auto_style=True)
        assert '"comic"' in seen["prompt"] and "comic" in seen["schema"]["properties"]["moments"]["items"]["properties"]["style"]["enum"]
        broll.plan_with_claude({}, words, 4, [], auto_style=True, hero=True)
        # the mixed layout: the schema is the rule (photo and the episode's registers), the look is the mood's
        assert '"comic"' not in seen["prompt"] and '"neon"' not in seen["prompt"] and "Nothing else" not in seen["prompt"]
        assert seen["schema"]["properties"]["moments"]["items"]["properties"]["style"]["enum"] == ["photo"]
        assert '"cinematic" -' not in seen["prompt"] and 'the look of every picture comes from its "mood"' in seen["prompt"]
        broll.plan_with_claude({}, words, 4, [], auto_style=False, hero=True)
        assert '"style"' not in seen["prompt"]


def _chroma(img):
    r, g, b = (ImageStat.Stat(c).mean[0] for c in img.split())
    return max(r, g, b) - min(r, g, b)


class TestGrade:
    def _img(self):
        im = Image.new("RGB", (120, 80))
        px = im.load()
        for x in range(120):
            for y in range(80):
                px[x, y] = (x * 2, 40 + y, 200 - x)
        return im

    def test_off_is_a_no_op(self):
        im = self._img()
        assert broll._grade_colour(im, "off") is im
        assert broll._grade_colour(im, "nope") is im
        assert broll._grade_params("off") is None and broll._grade_params(None) is None

    def test_an_older_clips_cinematic_grade_renders_the_same(self):
        im = self._img()
        out = broll._grade_colour(im, "cinematic")
        assert out.size == im.size and _chroma(out) < _chroma(im)
        black = broll._grade_colour(Image.new("RGB", (8, 8), (0, 0, 0)), "cinematic")
        assert min(black.getextrema()[c][0] for c in range(3)) >= broll.GRADES["cinematic"]["lift"] - 1
        bright = broll._grade_colour(Image.new("RGB", (8, 8), (210, 210, 210)), "cinematic").getpixel((2, 2))
        dark = broll._grade_colour(Image.new("RGB", (8, 8), (40, 40, 40)), "cinematic").getpixel((2, 2))
        assert bright[0] > bright[2]            # warm highlights
        assert dark[2] > dark[0]                # cool shadows

    def test_a_mood_grade_is_applied_by_visual_mood(self):
        im = self._img()
        g = visual_mood.grade({"valence": "grim"}, signature=0)
        out = broll._grade_colour(im, g)
        assert out.tobytes() == visual_mood.apply_grade(im, g).tobytes()
        assert broll._grade_params(g) is g

    def test_grain_moves(self):
        import numpy as np
        rng = np.random.default_rng(1)
        im = Image.new("RGB", (40, 30), (100, 100, 100))
        a, b = broll._grain(im, 4.0, rng), broll._grain(im, 4.0, rng)
        assert a.tobytes() != im.tobytes() and a.tobytes() != b.tobytes()
        assert broll._grain(im, 0.0, rng) is im


class TestRenderers:
    def test_the_grade_changes_the_hero_and_the_card_frames(self):
        tmp = tempfile.mkdtemp(prefix="grade_")
        src = os.path.join(tmp, "s.jpg")
        im = Image.new("RGB", (448, 800))
        px = im.load()
        for x in range(448):
            for y in range(800):
                px[x, y] = (x % 256, (y // 3) % 256, 120)
        im.save(src, quality=95)
        outs = {}
        grades = {"off": "off", "cinematic": "cinematic",
                  "grim": visual_mood.grade({"valence": "grim", "intensity": "charged"}, signature=0.2)}
        for name, g in grades.items():
            f = os.path.join(tmp, "h_" + name)
            os.makedirs(f)
            broll._hero_frames(src, f, 10, 1.0, 108, 192, grade=g)
            outs["hero_" + name] = Image.open(os.path.join(f, "c005.png")).convert("RGB")
            f = os.path.join(tmp, "c_" + name)
            os.makedirs(f)
            broll._rise_frames(src, f, 10, 1.0, 540, 960, 60, "top", look="premium", border="premium", grade=g)
            outs["card_" + name] = Image.open(os.path.join(f, "c005.png")).convert("RGB")
        assert outs["hero_off"].tobytes() != outs["hero_cinematic"].tobytes()
        assert _chroma(outs["hero_cinematic"]) < _chroma(outs["hero_off"])
        assert outs["card_off"].tobytes() != outs["card_cinematic"].tobytes()
        assert outs["hero_grim"].tobytes() not in (outs["hero_off"].tobytes(), outs["hero_cinematic"].tobytes())
        assert outs["card_grim"].tobytes() != outs["card_off"].tobytes()


class TestAddBroll:
    def _run(self, monkeypatch, moods, styles=None, **cfg_over):
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", **kw):
            Image.new("RGB", size, (120, 110, 100)).save(out_path, quality=80)
            made.append({"style": style, "look": look, **kw})
            return out_path

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "local_image", fake_image)
        monkeypatch.setattr(broll, "review_images", lambda cands, words: [{"score": 5} for _ in cands])
        monkeypatch.setattr(broll, "overlay_items", lambda *a, **k: None)
        tr = _transcript(TEXT)
        words = [{"text": w["word"].strip(), "start": w["start"], "end": w["end"]} for w in tr["segments"][0]["words"]]
        idx = {w["text"]: i for i, w in enumerate(words)}
        anchors = ("soldiers", "marched", "sergeant")
        styles = styles or ("comic", "neon", "diagram")
        data = {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": a, "role": "example", "shot": "wide",
                             "style": s, **({"mood": md} if md is not None else {})}
                            for a, s, md in zip(anchors, styles, moods)]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "max": 4, **cfg_over}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        return rep, made, tr, words, cfg

    def test_every_item_carries_its_mood_and_its_own_grade(self, monkeypatch, capsys):
        moods = [{"valence": "neutral", "intensity": "steady"}, {"valence": "grim", "intensity": "charged"},
                 {"valence": "neutral", "intensity": "steady", "colours_said": "a red glow"}]
        rep, made, tr, words, cfg = self._run(monkeypatch, moods, signature=0.2)
        items = rep["items"]
        assert [it["style"] for it in items] == ["photo", "photo", "photo"]
        assert all(isinstance(it["grade"], dict) and it["mood_base"] for it in items)
        assert items[0]["mood_base"]["valence"] == "neutral"            # the median of the clip
        assert items[1]["grade"]["temp"] < items[0]["grade"]["temp"]    # the grim one is colder
        assert items[0]["grade"]["sig"] == 0.2 and items[2]["grade"]["sig"] == 0.0   # the speaker's colours
        assert all("raw" in it["pixels"] and "gap" in it["pixels"] for it in items)
        # no art director here: the editor's draft goes out with the picture's look sentence
        assert all(m["mood"].startswith("A documentary photograph of today") and m["look"] == "" for m in made)
        out = capsys.readouterr().out
        assert "🎚️ Clip mood: neutral · steady · explained" in out and "🎨 Grades: " in out

    def test_a_planner_without_moods_gets_the_plain_look(self, monkeypatch):
        rep, made, *_ = self._run(monkeypatch, [None, None, None], signature=0)
        assert all(it["mood"]["valence"] == "neutral" and it["grade"]["sig"] == 0.0 for it in rep["items"])

    def test_the_historical_layouts_have_no_mood_and_no_grade(self, monkeypatch):
        rep, made, tr, words, cfg = self._run(monkeypatch, [None, None, None], layout="rise")
        assert all("grade" not in it and "mood" not in it for it in rep["items"])
        assert [it["style"] for it in rep["items"]] == ["comic", "neon", "diagram"]
        assert all(m["mood"] == "" for m in made)

    def test_grade_item_on_a_redo(self, tmp_path):
        p = tmp_path / "x.jpg"
        Image.new("RGB", (64, 64), (5, 5, 6)).save(p)
        item = {"mood": {"valence": "elated"}, "mood_base": {"valence": "neutral"}}
        gaps = broll.grade_item(item, str(p), 0.2)
        assert item["grade"]["sig"] == 0.2 and gaps and gaps == item["pixels"]["gap"]
        assert broll.grade_item({"register": "x", "mood": {"valence": "grim"}}, str(p)) == []
        assert broll.grade_item({}, str(p)) == []
