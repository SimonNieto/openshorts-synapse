"""THE EXPERIENCE, NOT THE SETTING (B-roll « ambiance », 2-oct-2026): something taken or practised for its effect
on the mind is shown as it is lived, even named in passing; real suffering comes first (a sober photograph); a
clip keeps INNER_MAX such pictures at most. No model, no ComfyUI."""
import pytest

import ai_brain
import broll
import visual_mood

from test_broll import TEXT, _words

VISION = ("Impossible interior of a vast dome built from shifting tessellated tiles, saturated violet, red and gold, "
          "a deep tunnel of light at the centre, geometry folding into itself, painted as the speaker tells it.")
BIBLE = {"world": ["a clinic"], "mood": {"valence": "uneasy"}, "motifs": [], "avoid": [], "heroes": [],
         "registers": [{"name": "vision", "kind": "inner", "when": "a trip", "look": VISION},
                       {"name": "histology", "kind": "instrument", "when": "cells", "look": "A stained slide " * 6},
                       {"name": "nokind", "when": "x", "look": "A plain look written long enough " * 3}]}


@pytest.fixture
def bible(monkeypatch):
    b = ai_brain._clean_bible(BIBLE, "claude")
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", b)
    return b


@pytest.fixture(autouse=True)
def _clear():
    broll.FILTERS.clear()
    yield
    broll.FILTERS.clear()


class TestTheBible:
    def test_every_inner_experience_gets_a_register_with_a_kind(self, bible):
        rules = ai_brain.bible_rules()
        assert "EVERY inner\n  experience the episode names" in rules and "even when it is named in passing" in rules
        assert "never the room it happens in nor its medical version" in " ".join(rules.split()) and "0 to 6 in all" in rules
        assert "A REGISTER IS A STYLE, NEVER A SCENE" in rules
        for topic in ("psychedelic", "DMT", "dream", "trip", "cosmos", "math"):
            assert topic not in rules, topic
        reg = ai_brain._bible_schema()["properties"]["registers"]["items"]
        assert reg["properties"]["kind"]["enum"] == ["instrument", "model", "inner"] and "kind" in reg["required"]
        assert [r.get("kind") for r in bible["registers"]] == ["inner", "instrument", None]
        assert '- "vision" (inner) — when: a trip' in ai_brain.bible_text(bible)
        assert ai_brain.REGISTER_MAX == 6


class TestTheEditor:
    def test_the_rule_is_in_the_mixed_prompt_only(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt) or {"moments": []})
        broll.plan_with_claude({}, _words(TEXT), 4, [], hero=True)
        p = seen["prompt"]
        assert broll.EXPERIENCE_RULE in p and "A DEATH FIRST" in p and "RESTRAINT" in p
        assert broll.EMPTY_RULE in p and broll.PRECISION_RULE in p
        assert p.index("NO SYMBOL FOR AN IDEA") < p.index("THE EXPERIENCE, NOT THE SETTING") < p.index("Never: something already visible")
        broll.plan_with_claude({}, _words(TEXT), 4, [], hero=False)
        assert "THE EXPERIENCE, NOT THE SETTING" not in seen["prompt"]


def _m(anchor, score=3.0, style="photo", **mood):
    return {"anchor": anchor, "t": 5.0, "score": score, "style": style, "mood": visual_mood.clean(mood)}


class TestTheGuard:
    def test_inner_by_mood_or_by_register_kind(self, bible):
        assert broll.is_inner(_m("a", visibility="inner"))
        assert broll.is_inner(_m("b", style="vision"))
        assert not broll.is_inner(_m("c", style="histology")) and not broll.is_inner(_m("d", style="nokind"))
        assert not broll.is_inner(_m("e")) and not broll.is_inner({})

    def test_only_a_death_makes_it_a_sober_photograph(self, bible):
        """v12 (2-oct-2026): "real" (an illness, an addiction) is shown from inside with restraint; only "grave" (a
        death, a victim) turns an experience picture into a sober photograph."""
        grave = _m("deaths", style="vision", visibility="inner", gravity="grave")
        real = _m("voices", visibility="inner", gravity="real", valence="uneasy")
        free = _m("trip", style="vision", visibility="inner")
        out = broll.experience_guard([grave, real, free])
        assert out == [grave, real, free]
        assert grave["style"] == "photo" and grave["mood"]["visibility"] == "eye"
        assert real["mood"]["visibility"] == "inner" and broll.is_inner(real) and not real["mood"].get("sober")
        assert free["style"] == "vision" and broll.is_inner(free)
        assert broll.FILTERS["experience: a death, made sober"] == 1
        w_real = visual_mood.words(real["mood"])
        assert "with restraint: muted colours" in w_real["medium"] and "never a caricature of the illness" in w_real["medium"]
        # the words of a sober picture are a documentary photograph with gentle light
        w = visual_mood.words(grave["mood"])
        assert "with restraint" not in w["medium"]
        assert w["medium"].startswith("a documentary photograph") and "dignity" in w["light"]
        assert "never what is seen, heard or felt inside" in w["medium"] and grave["mood"]["sober"] is True
        assert "never what is seen, heard or felt inside" in visual_mood.sentence(grave["mood"])
        assert "never what is seen" not in visual_mood.words(free["mood"])["medium"]
        assert "with restraint" not in visual_mood.words(free["mood"])["medium"]

    def test_a_clip_never_turns_into_a_string_of_experience_pictures(self, bible, monkeypatch):
        monkeypatch.setattr(broll, "INNER_MAX", 2)
        ms = [_m("one", 2.0, visibility="inner"), _m("two", 5.0, style="vision"), _m("street", 1.0),
              _m("three", 4.0, visibility="inner"), _m("four", 1.0, visibility="inner")]
        out = broll.experience_guard(ms)
        assert [m["anchor"] for m in out] == ["two", "street", "three"]
        assert broll.FILTERS["experience: beyond the cap"] == 2
        assert broll.INNER_MAX >= 1


class TestInTheJob:
    def test_add_broll_applies_the_guard_before_the_hero(self, bible, monkeypatch):
        from PIL import Image
        from test_broll import _transcript
        monkeypatch.setattr(broll, "HERO_TAKES", 1)
        monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)
        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "review_images", lambda cands, words: [{"score": 5} for _ in cands])
        monkeypatch.setattr(broll, "overlay_items", lambda *a, **k: None)
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", **kw):
            Image.new("RGB", size, (90, 90, 90)).save(out_path, quality=80)
            made.append({"prompt": prompt, "register": kw.get("register")})
            return out_path

        monkeypatch.setattr(broll, "local_image", fake_image)
        tr = _transcript(TEXT)
        words = [{"text": w["word"].strip(), "start": w["start"], "end": w["end"]} for w in tr["segments"][0]["words"]]
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"moments": [
            {"anchor": "soldiers", "time": words[idx["soldiers"]]["start"], "image_prompt": "a vision", "style": "vision",
             "mood": {"visibility": "inner", "gravity": "grave"}},
            {"anchor": "marched", "time": words[idx["marched"]]["start"], "image_prompt": "a vision", "style": "vision",
             "mood": {"visibility": "inner"}},
            {"anchor": "sergeant", "time": words[idx["sergeant"]]["start"], "image_prompt": "a man", "style": "photo"}]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "max": 4}
        # Without the director's rewrite, the sober picture would still paint the inside: it is dropped.
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert [it["anchor"] for it in rep["items"]] == ["marched", "sergeant"]
        assert broll.FILTERS["experience: sober picture not rewritten"] == 1
        # With it: the director is told, the picture is a sober photograph in the clip's grade.
        seen = {}

        def fake_direct(moments, clip, **kw):
            seen["prompt"] = broll._art_prompt(moments, clip, **{k: v for k, v in kw.items() if k in ("mixed", "faces")})
            for m in moments:
                m["prompt_editor"], m["prompt"], m["art"] = m["prompt"], ("word " * 60).strip(), True
            return len(moments)

        monkeypatch.setattr(broll, "direct_art", fake_direct)
        made.clear()
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, {**cfg, "art_director": True})
        by = {it["anchor"]: it for it in rep["items"]}
        assert seen["prompt"].count("SOBER, REAL SUFFERING (this overrules the editor's draft)") == 1
        assert by["soldiers"]["style"] == "photo" and "register" not in by["soldiers"] and "grade" in by["soldiers"]
        assert by["soldiers"]["mood"]["sober"] is True
        assert by["marched"]["style"] == "vision" and by["marched"]["register"] == VISION and "grade" not in by["marched"]
        assert [m["register"] for m in made] == [None, VISION, None]


class TestSetPhrases:
    """A figure of speech used for emphasis is not an image (the user, 2-oct-2026: a literal picture of the words of
    a set phrase showed what the speaker did not mean, and the review rated it 5)."""

    def test_the_editor_illustrates_no_set_phrase(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt) or {"moments": []})
        broll.plan_with_claude({}, _words(TEXT), 4, [], hero=True)
        p = seen["prompt"]
        assert "A SET PHRASE IS NOT AN IMAGE" in p and "only an image he builds on" in p
        assert p.index("allowed ONLY when the speaker says that image himself") < p.index("A SET PHRASE IS NOT AN IMAGE")

    def test_the_review_marks_a_literal_set_phrase_down(self):
        assert "2 or 1 = another thing, or nothing to do with the words,\nor A SET PHRASE TAKEN LITERALLY" in broll.REVIEW_PROMPT
        assert broll.KEEP_SCORE > 2      # so such a picture is dropped
