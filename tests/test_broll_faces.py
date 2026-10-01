"""Faces (B-roll v2, chantier H): a clear, natural face is allowed everywhere (plus.BROLL["faces"] = "always";
"never" / "always" the other ways), the other guardrails stay, nobody real and recognisable ever. No model called."""
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


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(broll, "NOTION_DIR", str(tmp_path / "notions"))
    monkeypatch.setattr(broll, "HERO_TAKES", 1)   # the hero's takes have their own tests
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")
    monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)


class TestGuardrails:
    def test_a_person_keeps_a_natural_face_when_faces_are_allowed(self):
        _p, off = broll.guardrails("A patient looks out of the window with hope.")
        _p, on = broll.guardrails("A patient looks out of the window with hope.", faces=True)
        assert "face turned away" in off and "face turned away" not in on
        assert "nobody real or recognisable" in on and "natural, in focus" in on

    def test_a_crowd_keeps_its_nearest_faces_when_allowed(self):
        _p, off = broll.guardrails("A crowd of people in a plaza at dusk.")
        _p, on = broll.guardrails("A crowd of people in a plaza at dusk.", faces=True)
        assert "silhouettes" in off and "silhouettes" not in on and "nearest faces natural and anonymous" in on

    def test_the_other_guardrails_stay(self):
        _p, on = broll.guardrails("Two surgeons read a chart on an iPhone.", faces=True)
        assert "exactly 2 surgeons" in on and "plain colour" in on and "unbranded" in on and "iphone" not in _p.lower()

    def test_the_image_text_passes_faces_through(self):
        off = broll._image_text("A woman smiles at a child.", "photo")
        on = broll._image_text("A woman smiles at a child.", "photo", faces=True)
        assert "face turned away" in off and "face turned away" not in on
        art = broll._image_text("A woman smiles at a child. " * 10, "photo", art=True, faces=True)
        assert "face turned away" not in art and art.endswith(broll.ART_RULES)


class TestTheArtDirector:
    def test_the_director_is_told_where_a_face_may_show(self):
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "hero": True}]
        hero = broll._art_prompt(ms, {}, "h", faces="hero")
        assert "welcome on the HERO" in hero and "On the cards keep people anonymous" in hero
        always = broll._art_prompt(ms, {}, "h", faces="always")
        assert "welcome on every picture" in always
        never = broll._art_prompt(ms, {}, "h", faces="never")
        assert "People stay anonymous on every picture" in never
        for text in (hero, always, never):
            assert "Nobody real and recognisable" in text

    def test_the_reviewer_watches_the_faces(self):
        text = broll.REVIEW_PROMPT.format(frame=broll._review_frame([{"layout": "hero"}]), items="- x")
        assert "deformed, waxy or doubled face" in text


class TestInTheJob:
    @pytest.fixture
    def stubs(self, monkeypatch):
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            made.append({"size": size, **kw})
            return out_path

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "local_image", fake_image)
        monkeypatch.setattr(broll, "review_images", lambda cands, words: [{"score": 5, "look": 5} for _ in cands])
        monkeypatch.setattr(broll, "overlay_items", lambda *a, **k: None)
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": "a person " + a, "role": "example",
                             "shot": s, "style": "photo"} for a, s in (("soldiers", "wide"), ("drill", "close"), ("sergeant", "medium"))]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
        tr = {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in words]}]}
        return made, tr, words

    def _run(self, tr, words, **cfg):
        base = {"planner": "claude", "layout": "mixed", "style": "auto", "house_look": "h", "art_director": False}
        return broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, {**base, **cfg})

    def test_hero_mode_frees_the_hero_only(self, stubs):
        made, tr, words = stubs
        self._run(tr, words, faces="hero")
        by_size = {m["size"]: m["faces"] for m in made}
        assert by_size[(896, 1600)] is True and by_size[(1152, 720)] is False

    def test_always_and_never(self, stubs):
        made, tr, words = stubs
        self._run(tr, words, faces="always")
        assert all(m["faces"] for m in made)
        made.clear()
        self._run(tr, words, faces="never")
        assert not any(m["faces"] for m in made)
        made.clear()
        self._run(tr, words)       # no key: as before
        assert not any(m["faces"] for m in made)

    def test_the_director_gets_the_mode(self, monkeypatch, stubs):
        made, tr, words = stubs
        seen = {}
        monkeypatch.setattr(broll, "direct_art", lambda moments, clip, house, **kw: seen.update(kw) or 0)
        self._run(tr, words, faces="always", art_director=True)
        assert seen["faces"] == "always"

    def test_the_recipe_allows_a_face_everywhere(self):
        assert plus.BROLL["faces"] == "always" and broll.FACE_MODES == ("never", "hero", "always")


class TestRegenerate:
    def test_a_manual_redo_follows_the_mode_and_the_layout(self, monkeypatch):
        seen = []
        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "local_image", lambda prompt, style, out, **kw: seen.append(kw["faces"]) or out)
        broll.regenerate_image("A person.", "photo", "o.jpg", cfg={"layout": "hero", "faces": "hero"}, gen=[896, 1600])
        broll.regenerate_image("A person.", "photo", "o.jpg", cfg={"layout": "card", "faces": "hero"}, gen=[1152, 720])
        broll.regenerate_image("A person.", "photo", "o.jpg", cfg={"layout": "card", "faces": "always"}, gen=[1152, 720])
        broll.regenerate_image("A person.", "photo", "o.jpg", cfg={"layout": "hero"}, gen=[896, 1600])
        assert seen == [True, False, True, False]
