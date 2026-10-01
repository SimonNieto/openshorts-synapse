"""broll.py, the picture the SOURCE put in a corner (screen_inset): one of the cards, placed by the source,
never planned over, up for as long as the source showed it. Image maker, planner and ffmpeg stubbed."""
import tempfile

import pytest
from PIL import Image

import broll
import viral_fx


def _words(text, step=0.42, dur=0.4, start=0.0):
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start": round(t, 2), "end": round(t + dur, 2)})
        t += step
    return out


def _transcript(text, step=0.42):
    return {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]}
                                    for w in _words(text, step)]}]}


TEXT = ("Well you know this is the setup for the story. In 1998 the soldiers were given two gallons of water, "
        "and then they marched all night long. It was brutal. Nobody spoke for hours but the drill went on and on "
        "until sunrise came and the camp woke up again and the sergeant finally smiled at them all. They never "
        "forgot that long night in the desert and the lesson it taught them about discipline.")


@pytest.fixture(autouse=True)
def _quiet_env(monkeypatch):
    monkeypatch.delenv("EDIT_STYLE", raising=False)
    monkeypatch.delenv("PLUS_FX_JSON", raising=False)
    monkeypatch.setattr(broll, "NOTION_DIR", tempfile.mkdtemp(prefix="notions_"))
    monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)


@pytest.fixture
def still(tmp_path):
    p = str(tmp_path / "clip_1_inset.jpg")
    Image.new("RGB", (832, 420), (200, 40, 40)).save(p, quality=80)
    return p


@pytest.fixture
def stubs(monkeypatch):
    """Everything around add_broll stubbed; the planner records what it was asked (``_n``, ``block``...)."""
    made, cut, seen = [], [], {}

    def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
        Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
        made.append(tuple(size))
        return out_path

    monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
    monkeypatch.setattr(broll, "claude_ready", lambda: True)
    monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
    monkeypatch.setattr(broll, "local_image", fake_image)
    monkeypatch.setattr(broll, "review_images", lambda cands, words: [{"score": 5} for _ in cands])
    monkeypatch.setattr(broll, "overlay_items", lambda clip, out, items, img_dir=None: cut.append(items))
    words = _words(TEXT)
    idx = {w["text"]: i for i, w in enumerate(words)}

    def mk(a, **k):
        return {"anchor": a, "time": words[idx[a]]["start"], "image_prompt": "a scene of " + a, **k}

    data = {"moments": [mk("soldiers", role="example", shot="wide", style="photo"),
                        mk("marched", role="example", shot="close", style="photo"),
                        mk("drill", role="concept", shot="close", style="neon"),
                        mk("sergeant", role="consequence", shot="medium", style="photo")]}

    def fake_plan(clip, words_, n, avoid, *a, **k):
        seen.update(k)
        seen["_n"] = n
        return broll._parse_moments(data, words_, n, avoid, broll.DENSITY["normal"]["gap"], k.get("dur_range"),
                                    k.get("tail"), k.get("head", broll.HEAD_FREE), k.get("block", ()))

    monkeypatch.setattr(broll, "plan_with_claude", fake_plan)
    return made, cut, seen


class TestScreenCard:
    def test_the_source_picture_is_one_of_the_cards(self, stubs, still):
        made, cut, seen = stubs
        tr = _transcript(TEXT)
        words = [{"text": w["word"].strip(), "start": w["start"], "end": w["end"]} for w in tr["segments"][0]["words"]]
        clip = {"punchline_time": None, "screen_inset": {"t0": 22.0, "t1": 27.0, "path": still}}
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "max": 4, "density": "normal", "engine": "zimage"}
        rep = broll.add_broll("clip.mp4", "out.mp4", clip, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert seen["block"] == [(21.0, 27.0)], "the planner is told the seconds the source's picture takes"
        assert seen["_n"] == broll.MIXED_MAX - 1, "the source's picture counts as one of the cards"
        items = rep["items"]
        screen = [it for it in items if it.get("source") == "screen"]
        assert len(screen) == 1 and screen[0]["layout"] == "card" and screen[0]["look"] == "premium"
        assert screen[0]["t"] == 22.0 and screen[0]["dur"] == 5.0 and "_img" not in screen[0]
        assert [it["t"] for it in items] == sorted(it["t"] for it in items)
        before = [it for it in items if it["t"] < 22.0]
        assert before and all(it["t"] + it["dur"] <= 22.0 - 0.24 for it in before), "a card leaves before it"
        assert all(it["layout"] != "hero" or it["t"] + it["dur"] <= 21.0 for it in items), \
            "the hero never runs into the source's picture"
        assert len(made) == len(items) - 1, "no image is made for the source's own picture"
        assert cut and cut[0] == items and "screen" in rep["sources"]

    def test_only_the_source_picture_when_nothing_is_planned(self, monkeypatch, stubs, still, capsys):
        made, cut, _ = stubs
        monkeypatch.setattr(broll, "plan_with_claude", lambda *a, **k: [])
        tr = _transcript(TEXT)
        clip = {"screen_inset": {"t0": 10.0, "t1": 13.0, "path": still}}
        rep = broll.add_broll("clip.mp4", "out.mp4", clip, tr, 0.0, 30.0, {"planner": "claude", "layout": "mixed"})
        assert rep["planner"] == "screen" and [it["source"] for it in rep["items"]] == ["screen"]
        assert rep["items"][0]["t"] == 10.0 and rep["items"][0]["dur"] == 3.0
        assert made == [] and cut and cut[0][0]["source"] == "screen"
        assert "the picture the source showed on screen" in capsys.readouterr().out

    def test_without_a_picture_nothing_changes(self, stubs):
        made, cut, seen = stubs
        tr = _transcript(TEXT)
        rep = broll.add_broll("clip.mp4", "out.mp4", {"punchline_time": None}, tr, 0.0, 30.0,
                              {"planner": "claude", "layout": "mixed", "max": 4})
        assert seen["block"] == [] and seen["_n"] == broll.MIXED_MAX
        assert all(it.get("source") != "screen" for it in rep["items"])

    def test_without_the_still_there_is_no_card(self, tmp_path):
        assert broll.screen_item({"t0": 1.0, "t1": 4.0, "image": "missing.jpg"}, str(tmp_path)) is None
        assert broll.screen_item(None) is None
        assert broll.add_screen_only("clip.mp4", "out.mp4", {"t0": 1.0, "t1": 4.0}) is None

    def test_the_time_on_screen_is_the_source_s_within_bounds(self, still):
        assert broll.screen_item({"t0": 1.0, "t1": 1.5, "path": still})["dur"] == broll.SCREEN_DUR_MIN
        assert broll.screen_item({"t0": 1.0, "t1": 30.0, "path": still})["dur"] == broll.SCREEN_DUR_MAX
        it = broll.screen_item({"t0": 1.0, "t1": 7.0, "path": still, "image": "clip_1_inset.jpg"})
        assert it["dur"] == 6.0 and it["image"] == "clip_1_inset.jpg" and it["position"] == broll.CARD_POSITION
        assert it["size"] == broll.SCREEN_CARD_SIZE and it["border"] == "premium" and "grade" not in it

    def test_add_screen_only_cuts_it_in_unless_the_review_is_manual(self, monkeypatch, still, tmp_path):
        cut = []
        monkeypatch.setattr(broll, "overlay_items", lambda clip, out, items, img_dir=None: cut.append(items))
        inset = {"t0": 2.0, "t1": 6.0, "image": "clip_1_inset.jpg"}
        rep = broll.add_screen_only("clip.mp4", "out.mp4", inset, str(tmp_path))
        assert rep and not rep["pending"] and len(cut) == 1 and cut[0][0]["image"] == "clip_1_inset.jpg"
        rep = broll.add_screen_only("clip.mp4", "out.mp4", inset, str(tmp_path), manual=True)
        assert rep["pending"] and len(cut) == 1

    def test_a_screen_card_stays_longer_than_the_four_seconds_of_a_generated_one(self, monkeypatch, still):
        monkeypatch.setattr(viral_fx, "_probe", lambda p: {"w": 108, "h": 192, "fps": 10, "duration": 12.0})
        cmds = []
        monkeypatch.setattr(broll.subprocess, "run", lambda cmd, **k: cmds.append(cmd))
        base = {"t": 1.0, "dur": 7.0, "layout": "card", "look": "premium", "size": 60, "position": "top",
                "border": "premium", "_img": still}
        broll.overlay_items("clip.mp4", "out.mp4", [dict(base, source="screen")])
        graph = cmds[-1][cmds[-1].index("-filter_complex") + 1]
        assert "between(t,1.000,8.000)" in graph
        broll.overlay_items("clip.mp4", "out.mp4", [dict(base, source="local")])
        graph = cmds[-1][cmds[-1].index("-filter_complex") + 1]
        assert "between(t,1.000,5.000)" in graph

    def test_no_image_starts_in_or_runs_into_the_blocked_seconds(self):
        assert broll._allowed(10.0, 30.0, [], block=[(9.0, 12.0)]) is False
        assert broll._allowed(8.0, 30.0, [], block=[(9.0, 12.0)]) is True
        words = _words(TEXT)
        i = next(k for k, w in enumerate(words) if w["text"] == "soldiers")
        data = {"moments": [{"anchor": "soldiers", "time": words[i]["start"], "image_prompt": "soldiers"}]}
        t = words[i]["start"] - broll.KEY_LEAD
        kept = broll._parse_moments(data, words, 3, [], 0.0, (2.2, 3.5), block=[(t + 2.0, t + 6.0)])
        assert kept == [], "it would run into the picture and cannot stay 2.2 s: dropped"
        kept = broll._parse_moments(data, words, 3, [], 0.0, (2.2, 3.5), block=[(t + 3.0, t + 6.0)])
        assert len(kept) == 1 and kept[0]["dur"] == pytest.approx(3.0 - broll.DUR_NEXT_GAP, abs=0.02)
        assert broll.hero_fits({"t": 10.0, "dur": 3.0}, 40.0, [], block=[(12.0, 15.0)]) is False
        assert broll.hero_fits({"t": 10.0, "dur": 3.0}, 40.0, [], block=[(14.0, 15.0)]) is True

    def test_the_planner_is_told_in_words(self):
        txt = broll._block_text([(21.0, 27.0)])
        assert "between 21.0s and 27.0s" in txt and "the video itself shows a picture" in txt
        assert broll._block_text([]) == ""
