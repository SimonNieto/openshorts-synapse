"""The pace of the mixed layout (B-roll v2, chantier G): the editor is asked for an image only when it adds
meaning, up to three per 30 s plus the hero, and told how the pictures really sit on screen (wide cards above
the head, one full-screen hero); the reviewer too. The historical layouts keep their texts. No model is called."""
import pytest

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
    monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")


def _plan_prompt(monkeypatch, **kw):
    seen = {}
    monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt) or {"moments": []})
    broll.plan_with_claude({}, _words(TEXT), 4, [], **kw)
    return seen["prompt"]


class TestTheEditor:
    def test_mixed_asks_for_meaning_not_a_ticker(self, monkeypatch):
        text = _plan_prompt(monkeypatch, hero=True, density="normal")
        assert "up to three per 30 s of clip, plus the hero" in text and "ALWAYS have something to look at" not in text
        assert "Show what the speaker names when it is:" in text and "even if it is a passing mention" not in text
        assert "wide card above the speaker's head (about 60 % of the screen width, 2.2-3.5 s)" in text
        assert "except the one HERO, full screen for about 3 s" in text
        assert "about a third of the screen width" not in text

    def test_each_density_has_its_mixed_text(self, monkeypatch):
        less = _plan_prompt(monkeypatch, hero=True, density="less")
        more = _plan_prompt(monkeypatch, hero=True, density="more")
        assert "Be SELECTIVE: one or two images per 30 s" in less and "three or four per 30 s" in more
        assert set(broll.DENSITY_MIXED) == set(broll.DENSITY)
        for v in broll.DENSITY_MIXED.values():
            assert "plus the hero" in v["pace"] and "ALWAYS" not in v["pace"]

    def test_the_historical_layouts_keep_their_texts(self, monkeypatch):
        text = _plan_prompt(monkeypatch, hero=False, density="normal")
        assert "ALWAYS have something to look at" in text and "even if it is a passing mention" in text
        assert "about a third of the screen width, under the captions" in text and "HERO" not in text
        assert "up to three per 30 s" not in text
        less = _plan_prompt(monkeypatch, hero=False, density="less")
        assert broll.DENSITY["less"]["pace"] in less

    def test_the_gap_still_comes_from_the_density_table(self):
        assert broll.DENSITY["normal"]["gap"] == 3.0 and "gap" not in broll.DENSITY_MIXED["normal"]


class TestTheReviewer:
    def test_mixed_cards_are_judged_at_their_real_size(self):
        frame = broll._review_frame([{"layout": "card"}, {"layout": "hero"}])
        assert "wide card above the speaker's head (about 60 %" in frame and "full screen for about 3 s when marked HERO" in frame
        text = broll.REVIEW_PROMPT.format(frame=frame, items="- x")
        assert text.startswith("Each image below will appear as a wide card") and "about a third" not in text

    def test_the_historical_card_is_still_small(self):
        frame = broll._review_frame([{"layout": "rise"}, {"layout": "full"}])
        assert "small (about a third of a phone screen's width)" in frame and f"{broll.RISE_DUR:.1f} s" in frame

    def test_the_claude_review_uses_the_frame(self, monkeypatch, tmp_path):
        from PIL import Image
        p = tmp_path / "broll_0.jpg"
        Image.new("RGB", (1152, 720), (1, 2, 3)).save(p)
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt) or {"reviews": []})
        cands = [{"file": str(p), "k": 0, "layout": "card", "m": {"t": 5.0, "idea": "i", "said": "s", "prompt": "p"}}]
        broll.review_with_claude(cands, _words(TEXT))
        assert seen["prompt"].startswith("Each image below will appear as a wide card above the speaker's head")
