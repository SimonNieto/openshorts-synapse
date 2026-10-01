"""The art director (B-roll v2, chantier A): a second call writes the prompt of every picture of a set in the
channel's look. Nothing here calls Claude, Gemini or ComfyUI."""
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
    monkeypatch.setenv("BROLL_NOTION_DIR", str(tmp_path / "notions"))
    monkeypatch.setattr(broll, "NOTION_DIR", str(tmp_path / "notions"))
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.delenv("CLAUDE_EFFORT_BROLL", raising=False)


def _moments():
    return [{"t": 5.0, "anchor": "soldiers", "prompt": "Soldiers at a camp.", "subject": "soldiers", "shot": "wide",
             "role": "example", "said": "the soldiers were given two gallons of water", "idea": "The ordeal starts.",
             "style": "photo", "hero": True, "sheet": {"palette": "sand, teal", "light": "low sun"}, "thesis": "Discipline is built."},
            {"t": 12.0, "anchor": "drill", "prompt": "A drill.", "subject": "drill", "shot": "close", "role": "concept",
             "style": "neon", "notion": "Drill", "hero": False}]


class TestTheRequest:
    def test_the_request_carries_the_set_the_look_and_the_grammar(self, monkeypatch):
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", {"glossary": [{"term": "Drill", "meaning": "m", "visual": "a sergeant's whistle"},
                                                                       {"term": "Dopamine", "meaning": "m", "visual": "x"}]})
        text = broll._art_prompt(_moments(), {"video_title_for_youtube_short": "T"}, "teal and amber documentary", clip_text="the drill went on")
        assert "teal and amber documentary" in text and 'title "T"' in text and "thesis: Discipline is built." in text
        assert "palette: sand, teal; light: low sun" in text
        assert "#0 HERO (full screen, 9:16" in text and "#1 CARD (small wide frame" in text
        assert "said: \"the soldiers were given two gallons of water\"" in text and "the editor's draft: Soldiers at a camp." in text
        assert "notion: Drill" in text and "- Drill: a sergeant's whistle" in text and "Dopamine" not in text
        assert broll.STYLES["neon"] in text and broll.STYLES["photo"] in text
        for part in ("SUBJECT AND ACTION", "SETTING", "COMPOSITION", "LENS", "LIGHT", "PALETTE", "MATERIAL", "MOOD"):
            assert part in text
        assert "80 to 120 English words" in text and "ignores negations" in text

    def test_the_historical_layouts_get_their_own_frames(self):
        ms = _moments()
        assert "CARD (small square frame" in broll._art_prompt(ms, {}, "h", mixed=False, rise=True)
        assert "FULL FRAME (9:16" in broll._art_prompt(ms, {}, "h", mixed=False, rise=False)

    def test_a_fixed_style_is_the_note_of_every_picture(self):
        text = broll._art_prompt(_moments(), {}, "h", auto_style=False, style="vintage")
        assert text.count(broll.STYLES["vintage"]) == 2 and broll.STYLES["neon"] not in text


class TestApplying:
    def test_prompts_land_by_index_and_the_drafts_are_kept(self):
        ms = _moments()
        n = broll._apply_art(ms, {"prompts": [{"k": 1, "prompt": LONG}, {"k": 0, "prompt": LONG + " More."}]})
        assert n == 2
        assert ms[0]["art"] and ms[0]["prompt"].startswith("A lone soldier") and ms[0]["prompt_editor"] == "Soldiers at a camp."
        assert ms[1]["art"] and ms[1]["prompt_editor"] == "A drill."

    def test_what_is_not_a_prompt_is_ignored(self):
        ms = _moments()
        n = broll._apply_art(ms, {"prompts": [{"k": 0, "prompt": "too short"}, {"k": 7, "prompt": LONG},
                                              {"k": "x", "prompt": LONG}, {"k": 1, "prompt": "w " * 300}, "junk"]})
        assert n == 0 and not any(m.get("art") for m in ms) and ms[0]["prompt"] == "Soldiers at a camp."
        assert broll._apply_art(ms, None) == 0

    def test_a_prompt_is_capped_at_the_prompt_maximum(self):
        ms = _moments()
        broll._apply_art(ms, {"prompts": [{"k": 0, "prompt": ("word " * 200).strip()}]})
        assert len(ms[0]["prompt"]) == broll.PROMPT_MAX

    def test_a_long_prompt_is_cut_after_its_last_full_sentence(self):
        sentences = " ".join(f"Sentence number {i} says a few true things about the scene." for i in range(18))
        ms = _moments()
        broll._apply_art(ms, {"prompts": [{"k": 0, "prompt": sentences}]})
        got = ms[0]["prompt"]
        assert len(got) <= broll.PROMPT_MAX and got.endswith("about the scene.") and len(got) > broll.PROMPT_MAX - 80
        assert broll._cut_at_sentence("short.", 900) == "short."
        # a sentence ending before the half is not worth the loss: the limit cuts
        assert len(broll._cut_at_sentence("a" * 100 + ". " + "b" * 900, 900)) == 900

    def test_the_editor_and_the_notion_caps_follow(self):
        assert broll.PROMPT_MAX == 900
        words = _words(TEXT)
        data = {"moments": [{"anchor": "soldiers", "time": words[11]["start"], "image_prompt": "x " * 600}]}
        ms = broll._parse_moments(data, words, 4, [], 3.0)
        assert len(ms[0]["prompt"]) == broll.PROMPT_MAX


class TestTheCall:
    def test_claude_writes_the_set_with_its_own_voice(self, monkeypatch):
        seen = {}

        def fake(prompt, schema, **kw):
            seen.update(kw, prompt=prompt, schema=schema)
            return {"prompts": [{"k": 0, "prompt": LONG}, {"k": 1, "prompt": LONG}]}

        monkeypatch.setattr(broll, "claude_json", fake)
        monkeypatch.setattr(ai_brain, "route", lambda k, *a, **kw: "claude")
        monkeypatch.setattr(ai_brain, "stage_model", lambda k, *a, **kw: {"broll_art": "sonnet"}[k])
        ms = _moments()
        assert broll.direct_art(ms, {}, "house") == 2
        assert seen["model"] == "sonnet" and seen["system"] == broll.ART_SYSTEM and seen["schema"] is broll.ART_SCHEMA
        assert seen["effort"] == "high" and "house" in seen["prompt"]
        assert all(m["art"] for m in ms)

    def test_the_effort_follows_the_profile(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **kw: seen.update(kw) or {"prompts": []})
        monkeypatch.setattr(ai_brain, "route", lambda k, *a, **kw: "claude")
        monkeypatch.setattr(ai_brain, "stage_model", lambda k, *a, **kw: "sonnet")
        monkeypatch.setenv("CLAUDE_EFFORT_BROLL", "medium")
        broll.direct_art(_moments(), {}, "house")
        assert seen["effort"] == "medium"

    def test_gemini_takes_the_step_when_the_brain_says_so(self, monkeypatch):
        monkeypatch.setattr(ai_brain, "route", lambda k, *a, **kw: "gemini" if k == "broll_art" else "claude")
        monkeypatch.setattr(ai_brain, "gemini_json", lambda contents, model=None: ({"prompts": [{"k": 0, "prompt": LONG}]}, None))
        monkeypatch.setattr(broll, "claude_json", lambda *a, **kw: pytest.fail("Claude must not be called"))
        ms = _moments()
        assert broll.direct_art(ms, {}, "house") == 1 and ms[0]["art"] and not ms[1].get("art")

    def test_a_failure_keeps_the_editors_prompts(self, monkeypatch, capsys):
        monkeypatch.setattr(ai_brain, "route", lambda k, *a, **kw: "claude")
        monkeypatch.setattr(ai_brain, "stage_model", lambda k, *a, **kw: "sonnet")

        def boom(*a, **kw):
            raise RuntimeError("quota")

        monkeypatch.setattr(broll, "claude_json", boom)
        ms = _moments()
        assert broll.direct_art(ms, {}, "house") == 0
        assert ms[0]["prompt"] == "Soldiers at a camp." and not ms[0].get("art")
        assert "art direction failed" in capsys.readouterr().out
        assert broll.direct_art([], {}, "house") == 0


class TestTheImageText:
    def test_an_art_prompt_goes_out_with_only_the_hard_rules(self):
        text = broll._image_text(LONG, "neon", look="Same visual look as the set.", house="teal documentary", art=True)
        assert text.startswith("A lone soldier") and text.endswith(broll.ART_RULES)
        assert "teal documentary" not in text and "Same visual look" not in text and broll.STYLES["neon"] not in text
        assert broll.COMMON_RULES not in text
        # the guardrails still watch the scene (a person: anonymous)
        assert "anonymous person" in text.lower() or "face turned away" in text.lower()

    def test_the_editors_prompt_is_assembled_as_before(self):
        assert broll._image_text("A brain.", "photo", "L", "H") == broll._image_text("A brain.", "photo", "L", "H", art=False)
        assert "H." in broll._image_text("A brain.", "photo", "L", "H")


class TestInTheJob:
    @pytest.fixture
    def stubs(self, monkeypatch):
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", art=False, **kw):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            made.append({"prompt": prompt, "style": style, "house": house, "art": art, "look": look})
            return out_path

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "local_image", fake_image)
        monkeypatch.setattr(broll, "review_images", lambda cands, words: [{"score": 5} for _ in cands])
        monkeypatch.setattr(broll, "overlay_items", lambda *a, **k: None)
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": "a scene of " + a, "role": r, "shot": s,
                             "style": "photo"} for a, r, s in (("soldiers", "example", "wide"), ("drill", "concept", "close"),
                                                               ("sergeant", "consequence", "medium"))]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
        tr = {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in words]}]}
        return made, tr, words

    def _art(self, monkeypatch, calls):
        def fake_direct(moments, clip, house, **kw):
            calls.append({"n": len(moments), "house": house, **kw})
            for m in moments:
                m["prompt_editor"], m["prompt"], m["art"] = m["prompt"], LONG + " " + m["anchor"], True
            return len(moments)

        monkeypatch.setattr(broll, "direct_art", fake_direct)

    def test_on_the_pictures_are_made_from_the_art_prompts(self, monkeypatch, stubs):
        made, tr, words = stubs
        calls = []
        self._art(monkeypatch, calls)
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "house_look": "teal documentary", "grade": "cinematic",
               "art_director": True}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert calls and calls[0]["n"] == len(rep["items"]) and calls[0]["house"] == "teal documentary" and calls[0]["mixed"]
        assert all(m["art"] and m["prompt"].startswith("A lone soldier") for m in made)
        assert all(it["art"] and it["prompt"].startswith("A lone soldier") and it["prompt_editor"].startswith("a scene of ")
                   for it in rep["items"])

    def test_off_nothing_changes(self, monkeypatch, stubs):
        made, tr, words = stubs
        calls = []
        self._art(monkeypatch, calls)
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "house_look": "teal documentary", "grade": "cinematic"}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert not calls and all(not m["art"] for m in made)
        assert all("art" not in it and "prompt_editor" not in it and it["prompt"].startswith("a scene of ") for it in rep["items"])
        assert plus.BROLL["art_director"] is False

    def test_a_redo_from_the_review_is_the_editors_kind_again(self, monkeypatch, stubs):
        made, tr, words = stubs
        self._art(monkeypatch, [])
        monkeypatch.setattr(broll, "review_images",
                            lambda cands, words_: [{"score": 2 if c["m"]["anchor"] == "drill" else 5, "better_prompt": "A closer drill."}
                                                   if c["file"].endswith("broll_1.jpg") else {"score": 5} for c in cands])
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "house_look": "teal documentary", "art_director": True}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        redo = [m for m in made if m["prompt"] == "A closer drill."]
        assert redo and not redo[0]["art"] and redo[0]["house"] == "teal documentary"
        drill = next(it for it in rep["items"] if it["anchor"] == "drill")
        assert drill["prompt"] == "A closer drill." and "art" not in drill


class TestRegenerate:
    def test_an_art_item_is_remade_as_is_a_short_rewrite_as_the_editors(self, monkeypatch):
        seen = []
        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)
        monkeypatch.setattr(broll, "local_image", lambda prompt, style, out, **kw: seen.append(kw) or out)
        cfg = {"layout": "hero", "house_look": "teal documentary"}
        broll.regenerate_image(LONG, "photo", "o.jpg", cfg=cfg, gen=[896, 1600], art=True)
        broll.regenerate_image("A brain on a desk.", "photo", "o.jpg", cfg=cfg, gen=[896, 1600], art=True)
        broll.regenerate_image(LONG, "photo", "o.jpg", cfg=cfg, gen=[896, 1600])
        assert [s["art"] for s in seen] == [True, False, False] and all(s["house"] == "teal documentary" for s in seen)


class TestTheStage:
    def test_the_step_exists_everywhere(self):
        assert "broll_art" in ai_brain.STAGES and ai_brain.STAGE_DEFAULTS["broll_art"] == "sonnet"
        assert "broll_art" in plus.BRAIN_STAGES
        for name, preset in plus.BRAIN_PRESETS.items():
            assert preset["broll_art"] in plus.BRAIN_CHOICES, name
        assert plus.BRAIN_PRESETS["gemini"]["broll_art"] == "gemini" and plus.BRAIN_PRESETS["balanced"]["broll_art"] == "sonnet"
        env = plus.job_env({"name": "x", "broll": {"enabled": True}, "brain": {"preset": "claude"}})
        assert env["BRAIN_BROLL_ART"] == "sonnet"
        import json
        assert json.loads(env["PLUS_BROLL_JSON"])["art_director"] is False

    def test_an_old_custom_profile_gets_the_preset_value_for_the_new_step(self):
        p = plus.sanitize({"brain": {"preset": "custom", "stages": {"broll": "opus"}}})
        assert p["brain"]["stages"]["broll_art"] == "sonnet" and p["brain"]["stages"]["broll"] == "opus"
