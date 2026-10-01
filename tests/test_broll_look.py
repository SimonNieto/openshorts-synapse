"""One look for the whole chain (profile broll.house_look / broll.grade, "mixed" layout): the house sentence in
every image prompt, a photographic style set in auto mode, and one colour grade on every picture at render time."""
import os
import tempfile

import pytest
from PIL import Image, ImageStat

import broll
import plus

from test_broll import TEXT, _transcript, _words


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.delenv("EDIT_STYLE", raising=False)
    monkeypatch.setattr(broll, "NOTION_DIR", tempfile.mkdtemp(prefix="notions_"))
    monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)


class TestProfile:
    def test_defaults_off(self):
        d = plus.sanitize({})["broll"]
        assert (d["house_look"], d["grade"]) == ("", "off")

    def test_values(self):
        b = plus.sanitize({"broll": {"house_look": "  teal and  amber,\n35 mm ", "grade": "cinematic"}})["broll"]
        assert (b["house_look"], b["grade"]) == ("teal and amber, 35 mm", "cinematic")
        assert plus.sanitize({"broll": {"grade": "sepia"}})["broll"]["grade"] == "off"
        assert len(plus.sanitize({"broll": {"house_look": "x" * 500}})["broll"]["house_look"]) == 200


class TestPrompt:
    def test_the_house_look_sits_between_the_scene_and_the_style_sheet(self):
        text = broll._image_text("A brain model on a desk.", "photo", look="Same visual look as the other images of the set — palette: teal.",
                                 house="cinematic documentary photograph, 35 mm")
        i_scene, i_house, i_look, i_style = (text.index(s) for s in ("A brain model", "cinematic documentary photograph, 35 mm.",
                                                                     "Same visual look", broll.STYLES["photo"]))
        assert i_scene < i_house < i_look < i_style
        assert text.endswith(broll.COMMON_RULES)

    def test_no_house_look_leaves_the_prompt_as_before(self):
        plain = broll._image_text("A brain.", "photo")
        assert plain == broll._image_text("A brain.", "photo", house="   ")
        # the historical text, spaces included (the image cache keys on it)
        assert plain == f"A brain.   {broll.STYLES['photo']} {broll.COMMON_RULES}".replace("  ", " ")

    def test_auto_style_in_the_mixed_layout_is_photographic(self, monkeypatch):
        import ai_brain
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt) or {"moments": []})
        words = _words(TEXT)
        broll.plan_with_claude({}, words, 4, [], auto_style=True)
        assert '"comic"' in seen["prompt"] and "one series" not in seen["prompt"]
        broll.plan_with_claude({}, words, 4, [], auto_style=True, hero=True)
        assert '"comic"' not in seen["prompt"] and "one series" in seen["prompt"] and '"neon"' in seen["prompt"]
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

    def test_cinematic_desaturates_lifts_the_blacks_and_splits_the_tones(self):
        im = self._img()
        out = broll._grade_colour(im, "cinematic")
        assert out.size == im.size and _chroma(out) < _chroma(im)
        black = broll._grade_colour(Image.new("RGB", (8, 8), (0, 0, 0)), "cinematic")
        assert min(black.getextrema()[c][0] for c in range(3)) >= broll.GRADES["cinematic"]["lift"] - 1
        bright = broll._grade_colour(Image.new("RGB", (8, 8), (210, 210, 210)), "cinematic").getpixel((2, 2))
        dark = broll._grade_colour(Image.new("RGB", (8, 8), (40, 40, 40)), "cinematic").getpixel((2, 2))
        assert bright[0] > bright[2]            # warm highlights
        assert dark[2] > dark[0]                # cool shadows
        clean = broll._grade_colour(im, "clean")
        assert _chroma(im) > _chroma(clean) > _chroma(out)

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
        for g in ("off", "cinematic"):
            f = os.path.join(tmp, "h_" + g)
            os.makedirs(f)
            broll._hero_frames(src, f, 10, 1.0, 108, 192, grade=g)
            outs["hero_" + g] = Image.open(os.path.join(f, "c005.png")).convert("RGB")
            f = os.path.join(tmp, "c_" + g)
            os.makedirs(f)
            broll._rise_frames(src, f, 10, 1.0, 540, 960, 60, "top", look="premium", border="premium", grade=g)
            outs["card_" + g] = Image.open(os.path.join(f, "c005.png")).convert("RGB")
        assert outs["hero_off"].tobytes() != outs["hero_cinematic"].tobytes()
        assert _chroma(outs["hero_cinematic"]) < _chroma(outs["hero_off"])
        assert outs["card_off"].tobytes() != outs["card_cinematic"].tobytes()


class TestAddBroll:
    def test_items_carry_the_grade_and_the_styles_are_photographic(self, monkeypatch):
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house=""):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            made.append((style, house))
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
        data = {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": a, "role": "example", "shot": "wide", "style": s}
                            for a, s in (("soldiers", "comic"), ("marched", "neon"), ("sergeant", "diagram"))]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "max": 4, "grade": "cinematic",
               "house_look": "teal and amber documentary photograph"}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert [it["style"] for it in rep["items"]] == ["photo", "neon", "photo"]
        assert all(it["grade"] == "cinematic" for it in rep["items"])
        assert all(h == "teal and amber documentary photograph" for _, h in made)
        # the historical layouts: no house look, no grade on the items, whatever the profile says
        made.clear()
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, {**cfg, "layout": "rise"})
        assert all(h == "" for _, h in made) and all("grade" not in it for it in rep["items"])
        assert [it["style"] for it in rep["items"]] == ["comic", "neon", "diagram"]
