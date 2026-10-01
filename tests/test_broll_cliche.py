"""Anti-cliché and specificity rules (B-roll v2, chantier C): the editor, the art director, the reviewer and the
brief's glossary are told what cheap AI B-roll looks like; the channel's latest subjects are remembered so a batch
does not open on the same picture three times. Nothing here calls a model."""
import json
import os

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
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.delenv("BROLL_NOTION_MEMORY", raising=False)


class TestTheRules:
    def _plan_prompt(self, monkeypatch, **kw):
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt) or {"moments": []})
        broll.plan_with_claude({}, _words(TEXT), 4, [], **kw)
        return seen["prompt"]

    def test_the_editor_is_told_the_clichés_and_the_positive_rules(self, monkeypatch):
        text = self._plan_prompt(monkeypatch, hero=True)
        assert "NEVER THE AI CLICHÉ" in text and "A DETAIL THAT TELLS" in text and "THE CASE BEFORE THE NOTION" in text
        assert "THE INVISIBLE, PHOTOGRAPHED" in text
        for c in broll.CLICHES:
            assert c in text
        assert "glowing brain" in text and "light bulb" in text and "handshake" in text and "glowing eyes" in text
        # the rule sits after the set rule and before the "Never:" line, once
        assert text.count("NEVER THE AI CLICHÉ") == 1 and text.index("THE SET TELLS THE STORY") < text.index("NEVER THE AI CLICHÉ")
        assert "ALREADY SHOWN" not in text

    def test_the_premium_neon_is_a_micrograph_not_neon_lines(self, monkeypatch):
        text = self._plan_prompt(monkeypatch, hero=True, auto_style=True)
        assert "real micrograph or lab photograph" in text and "never glowing neon lines" in text

    def test_the_art_director_gets_the_same_ban(self):
        ms = [{"t": 5.0, "anchor": "drill", "prompt": "A glowing brain.", "subject": "brain", "shot": "close", "hero": True}]
        text = broll._art_prompt(ms, {}, "house")
        assert "NEVER THE AI CLICHÉ" in text and "keep its subject and shoot it as a real" in text
        for c in broll.CLICHES:
            assert c in text

    def test_the_reviewer_marks_a_cliché_down(self):
        text = broll.REVIEW_PROMPT.format(frame=broll._review_frame([{"layout": "card"}]), items="- x")
        assert "STOCK OR CLICHÉ" in text and "scores 3 at" in text
        for c in broll.CLICHES:
            assert c in text

    def test_the_brief_asks_for_real_things(self):
        assert "never a symbol" in ai_brain.BRIEF_RULES and "no glowing brain" in ai_brain.BRIEF_RULES
        assert "never a symbol" in ai_brain.BRIEF_PROMPT
        assert "glowing brain" not in ai_brain.BRIEF_RULES_LITE

    def test_a_chalkboard_or_an_equation_is_lettering(self):
        for text in ("A chalkboard full of equations.", "a formula on a board", "Chalkboards everywhere."):
            _p, guard = broll.guardrails(text)
            assert "plain colour" in guard, text
        _p, guard = broll.guardrails("A kitchen counter at dawn.")
        assert "plain colour" not in guard


class TestRecentSubjects:
    def test_round_trip_and_cap(self):
        assert broll.recent_subjects() == []
        n = broll.remember_subjects([{"subject": "brain", "source": "local"}, {"subject": "patient in bed", "source": "local"},
                                     {"subject": "", "source": "local"}, {"subject": "on screen", "source": "screen"}])
        assert n == 2 and broll.recent_subjects() == ["brain", "patient in bed"]
        broll.remember_subjects([{"subject": f"s{i}", "source": "local"} for i in range(broll.RECENT_MAX + 5)])
        kept = json.load(open(broll._recent_path(), encoding="utf-8"))
        assert len(kept) == broll.RECENT_MAX and kept[-1]["subject"] == f"s{broll.RECENT_MAX + 4}" and "brain" not in [e["subject"] for e in kept]
        assert len(broll.recent_subjects()) == broll.RECENT_SHOWN and broll.recent_subjects(3) == ["s42", "s43", "s44"]

    def test_the_memory_switch_turns_it_off(self, monkeypatch):
        monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")
        assert broll.remember_subjects([{"subject": "brain", "source": "local"}]) == 0
        assert not os.path.exists(broll._recent_path()) and broll.recent_subjects() == []

    def test_a_broken_file_is_an_empty_memory(self):
        os.makedirs(broll.NOTION_DIR)
        with open(broll._recent_path(), "w") as f:
            f.write("{not json")
        assert broll.recent_subjects() == []
        assert broll.remember_subjects([{"subject": "x", "source": "local"}]) == 1 and broll.recent_subjects() == ["x"]

    def test_the_editor_is_told_what_was_just_shown(self, monkeypatch):
        broll.remember_subjects([{"subject": "hands clutching symbols", "source": "local"}, {"subject": "night sky", "source": "local"}])
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt) or {"moments": []})
        broll.plan_with_claude({}, _words(TEXT), 4, [], hero=True)
        assert "ALREADY SHOWN by the channel in its latest clips" in seen["prompt"]
        assert "hands clutching symbols; night sky" in seen["prompt"]
        assert seen["prompt"].index("NEVER THE AI CLICHÉ") < seen["prompt"].index("ALREADY SHOWN") < seen["prompt"].index("Never: something already visible")


class TestInTheJob:
    def test_items_carry_their_subject_and_the_clip_is_remembered(self, monkeypatch):
        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
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
        data = {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": "a scene of " + a, "subject": s,
                             "role": "example", "shot": "wide", "style": "photo"}
                            for a, s in (("soldiers", "soldiers at dawn"), ("sergeant", "sergeant's smile"))]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
        tr = {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in words]}]}
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "house_look": "h"}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert [it["subject"] for it in rep["items"]] == ["soldiers at dawn", "sergeant's smile"]
        assert broll.recent_subjects() == ["soldiers at dawn", "sergeant's smile"]
        # a bench or a test with the memory off leaves no trace
        monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")
        os.remove(broll._recent_path())
        broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert not os.path.exists(broll._recent_path())

    def test_the_recipe_is_unchanged_by_the_rules(self):
        assert plus.BROLL["style"] == "auto" and plus.BROLL["art_director"] is False
