"""Style families (B-roll v2, chantier B): in the mixed layout one photographic recipe per clip (lens, film,
light, grade) replaces the eight STYLES; the art director picks it or the recipe fixes it; neon is gone from
that layout. Nothing here calls a model."""
import pytest
from PIL import Image

import ai_brain
import broll
import plus


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
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")


def _moments():
    return [{"t": 5.0, "anchor": "soldiers", "prompt": "Soldiers at a camp.", "subject": "soldiers", "shot": "wide",
             "style": "cinematic", "hero": True},
            {"t": 12.0, "anchor": "drill", "prompt": "A drill.", "subject": "drill", "shot": "close", "style": "neon"}]


class TestTheFamilies:
    def test_four_recipes_each_with_a_lens_and_a_light(self):
        assert set(broll.FAMILIES) == {"cinematic_photo", "editorial_photo", "scientific_dark", "archive"}
        assert broll.FAMILY_DEFAULT in broll.FAMILIES and plus.BROLL["style_family"] == "auto"
        for name, block in broll.FAMILIES.items():
            assert ("mm" in block or "lens" in block) and ("light" in block or "lamp" in block or "film" in block), name
            assert 120 <= len(block) <= 400, name
        assert "neon" not in " ".join(broll.FAMILIES.values()).lower()

    def test_the_premium_rule_has_no_neon_any_more(self):
        assert broll.PREMIUM_STYLES == ("photo", "cinematic") and '"neon"' not in broll.STYLE_RULE_PREMIUM
        assert "real micrograph or lab photograph" in broll.STYLE_RULE_PREMIUM
        # the eight styles stay for the historical layouts
        assert "neon" in broll.STYLES and len(broll.STYLES) == 8


class TestTheImageText:
    def test_the_family_takes_the_place_of_the_style(self):
        text = broll._image_text("A brain.", "neon", look="L.", house="H", family="scientific_dark")
        assert text == f"A brain. H. L. {broll.FAMILIES['scientific_dark']} {broll.COMMON_RULES}"
        assert broll.STYLES["neon"] not in text

    def test_no_family_is_the_style_as_before(self):
        assert broll._image_text("A brain.", "neon") == f"A brain. {broll.STYLES['neon']} {broll.COMMON_RULES}"
        assert broll._image_text("A brain.", "neon", family="nope") == broll._image_text("A brain.", "neon")

    def test_an_art_prompt_keeps_the_family_block_and_the_hard_rules_only(self):
        text = broll._image_text(LONG, "photo", look="L.", house="H", art=True, family="archive")
        assert text.startswith("A lone soldier") and text.endswith(f"{broll.FAMILIES['archive']} {broll.ART_RULES}")
        assert "H." not in text and "L." not in text
        plain = broll._image_text(LONG, "photo", art=True)
        assert plain.endswith(broll.ART_RULES) and broll.FAMILIES["archive"] not in plain


class TestTheArtDirector:
    def test_auto_asks_for_a_choice_with_the_four_recipes(self):
        text = broll._art_prompt(_moments(), {}, "house", family="auto")
        assert "choose ONE for the whole clip" in text and 'return its name in "family"' in text
        for name, block in broll.FAMILIES.items():
            assert f'"{name}"' in text and block in text
        assert "ONLY when most pictures of the set are microscopic" in text and "ONLY when the story happens in the past" in text
        # tones, not the eight styles, describe each picture
        assert "tone: a dramatic, dark or tense moment" in text and "tone: a microscopic or invisible subject" in text
        assert "style note:" not in text and broll.STYLES["neon"] not in text

    def test_a_fixed_family_is_stated_not_chosen(self):
        text = broll._art_prompt(_moments(), {}, "house", family="editorial_photo")
        assert "THE STYLE FAMILY of this clip" in text and broll.FAMILIES["editorial_photo"] in text
        assert "choose ONE" not in text and broll.FAMILIES["archive"] not in text

    def test_the_historical_layouts_keep_the_style_notes(self):
        text = broll._art_prompt(_moments(), {}, "house", mixed=False, rise=True)
        assert "STYLE FAMILY" not in text and "style note:" in text and broll.STYLES["neon"] in text

    def test_the_chosen_family_lands_on_every_moment(self):
        ms = _moments()
        n = broll._apply_art(ms, {"family": "archive", "prompts": [{"k": 0, "prompt": LONG}]})
        assert n == 1 and all(m["family"] == "archive" for m in ms)
        ms = _moments()
        broll._apply_art(ms, {"family": "neon", "prompts": []})
        assert not any(m.get("family") for m in ms)
        assert "family" in broll.ART_SCHEMA["properties"] and broll.ART_SCHEMA["properties"]["family"]["enum"] == list(broll.FAMILIES)

    def test_direct_art_passes_the_family_through(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **kw: seen.update(prompt=prompt) or {"prompts": []})
        monkeypatch.setattr(ai_brain, "route", lambda k, *a, **kw: "claude")
        monkeypatch.setattr(ai_brain, "stage_model", lambda k, *a, **kw: "sonnet")
        broll.direct_art(_moments(), {}, "house", family="scientific_dark")
        assert "THE STYLE FAMILY of this clip" in seen["prompt"] and broll.FAMILIES["scientific_dark"] in seen["prompt"]


class TestInTheJob:
    @pytest.fixture
    def stubs(self, monkeypatch):
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            made.append({"prompt": prompt, "style": style, **kw})
            return out_path

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "local_image", fake_image)
        monkeypatch.setattr(broll, "review_images", lambda cands, words: [{"score": 5} for _ in cands])
        monkeypatch.setattr(broll, "overlay_items", lambda *a, **k: None)
        monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": "a scene of " + a, "role": "example",
                             "shot": "wide", "style": s} for a, s in (("soldiers", "neon"), ("drill", "cinematic"), ("sergeant", "comic"))]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
        tr = {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in words]}]}
        return made, tr, words

    def _run(self, tr, words, **cfg):
        base = {"planner": "claude", "layout": "mixed", "style": "auto", "house_look": "h", "grade": "cinematic"}
        return broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, {**base, **cfg})

    def test_without_the_director_auto_is_the_default_family_and_neon_is_photo(self, stubs, capsys):
        made, tr, words = stubs
        rep = self._run(tr, words, style_family="auto")
        assert all(m["family"] == "cinematic_photo" for m in made)
        assert [it["style"] for it in rep["items"]] == ["photo", "cinematic", "photo"]
        assert all(it["family"] == "cinematic_photo" for it in rep["items"])
        assert "Style family: cinematic_photo" in capsys.readouterr().out

    def test_the_director_picks_the_family_when_auto(self, monkeypatch, stubs):
        made, tr, words = stubs
        seen = {}

        def fake_direct(moments, clip, house, **kw):
            seen.update(kw)
            for m in moments:
                m["family"] = "archive"
            return 0

        monkeypatch.setattr(broll, "direct_art", fake_direct)
        rep = self._run(tr, words, art_director=True)
        assert seen["family"] == "auto" and all(m["family"] == "archive" for m in made)
        assert all(it["family"] == "archive" for it in rep["items"])

    def test_a_fixed_family_wins_over_the_director(self, monkeypatch, stubs):
        made, tr, words = stubs
        seen = {}

        def fake_direct(moments, clip, house, **kw):
            seen.update(kw)
            for m in moments:
                m["family"] = "archive"
            return 0

        monkeypatch.setattr(broll, "direct_art", fake_direct)
        self._run(tr, words, art_director=True, style_family="editorial_photo")
        assert seen["family"] == "editorial_photo" and all(m["family"] == "editorial_photo" for m in made)

    def test_the_historical_layouts_have_no_family(self, stubs):
        made, tr, words = stubs
        rep = self._run(tr, words, layout="rise")
        assert all(m["family"] is None for m in made) and all("family" not in it for it in rep["items"])
        assert [it["style"] for it in rep["items"]] == ["neon", "cinematic", "comic"]

    def test_a_redo_keeps_the_family(self, monkeypatch, stubs):
        made, tr, words = stubs
        monkeypatch.setattr(broll, "review_images",
                            lambda cands, words_: [{"score": 2, "better_prompt": "Closer."} if c["file"].endswith("broll_0.jpg")
                                                   else {"score": 5} for c in cands])
        self._run(tr, words)
        redo = [m for m in made if m["prompt"] == "Closer."]
        assert redo and redo[0]["family"] == "cinematic_photo"


class TestRegenerate:
    def test_the_items_family_is_used_again(self, monkeypatch):
        seen = []
        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)
        monkeypatch.setattr(broll, "local_image", lambda prompt, style, out, **kw: seen.append(kw) or out)
        cfg = {"layout": "card", "house_look": "h"}
        broll.regenerate_image("A brain.", "photo", "o.jpg", cfg=cfg, gen=[1152, 720], family="scientific_dark")
        broll.regenerate_image("A brain.", "photo", "o.jpg", cfg=cfg, gen=[1152, 720], family="nope")
        broll.regenerate_image("A brain.", "photo", "o.jpg", cfg=cfg, gen=[1152, 720])
        assert [s["family"] for s in seen] == ["scientific_dark", None, None]
