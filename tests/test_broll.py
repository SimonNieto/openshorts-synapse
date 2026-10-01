"""broll.py: the timing and the geometry of the B-roll pictures, and the premium
"mixed" layout (one full-screen hero + small cards). No GPU, no model: the
image maker, the planner and ffmpeg are stubbed."""
import json
import os
import tempfile

import pytest
from PIL import Image

import broll
import plus


def _words(text, step=0.42, dur=0.4, start=0.0):
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start": round(t, 2), "end": round(t + dur, 2)})
        t += step
    return out


TEXT = ("Well you know this is the setup for the story. In 1998 the soldiers were given two gallons of water, "
        "and then they marched all night long. It was brutal. Nobody spoke for hours but the drill went on and on "
        "until sunrise came and the camp woke up again and the sergeant finally smiled at them all. They never "
        "forgot that long night in the desert and the lesson it taught them about discipline.")


@pytest.fixture(autouse=True)
def _quiet_env(monkeypatch):
    monkeypatch.delenv("EDIT_STYLE", raising=False)
    monkeypatch.delenv("PLUS_FX_JSON", raising=False)
    monkeypatch.delenv("BROLL_EXIT", raising=False)
    # Never touch the channel's real notion memory, never talk to ComfyUI.
    monkeypatch.setattr(broll, "NOTION_DIR", tempfile.mkdtemp(prefix="notions_"))
    monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)


class TestCounts:
    def test_density_scales_the_profile_max(self):
        assert [broll.image_count(6, d) for d in ("less", "normal", "more")] == [4, 6, 9]
        assert [broll.image_count(3, d) for d in ("less", "normal", "more")] == [2, 3, 5]
        assert [broll.image_count(1, d) for d in ("less", "normal", "more")] == [1, 1, 2]
        assert broll.image_count(10, "more") == broll.DENSITY_CAP


class TestMoments:
    def test_an_image_lasts_to_the_end_of_its_sentence_and_never_runs_into_the_next(self):
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}

        def mk(a):
            return {"anchor": a, "time": words[idx[a]]["start"], "image_prompt": a}

        out = broll._parse_moments({"moments": [mk("soldiers"), mk("gallons"), mk("brutal."), mk("drill")]}, words, 6, [])
        assert out and all(broll.DUR_MIN <= m["dur"] <= broll.DUR_MAX for m in out)
        for a, b in zip(out, out[1:]):
            assert a["t"] + a["dur"] <= b["t"] - broll.DUR_NEXT_GAP + 0.01
        assert out[0]["dur"] > 1.5

    def test_the_image_lands_on_the_key_word_of_its_anchor(self):
        words = _words("so we were talking about it all night and they drank two gallons of water every single day for months on end yes", step=0.5)
        i = [w["text"] for w in words].index("two")
        res = broll._parse_moments({"moments": [{"anchor": "two gallons of water", "time": words[i]["start"],
                                                 "image_prompt": "jugs"}]}, words, 3, [])
        assert res and res[0]["key"] == "gallons"
        assert res[0]["t"] > words[i]["start"] + 0.3

    def test_the_planner_hero_flag_is_carried(self):
        words = _words(TEXT)
        i = [w["text"] for w in words].index("soldiers")
        res = broll._parse_moments({"moments": [{"anchor": "soldiers", "time": words[i]["start"], "image_prompt": "x",
                                                 "hero": True}]}, words, 3, [])
        assert res[0]["hero"] is True
        res = broll._parse_moments({"moments": [{"anchor": "soldiers", "time": words[i]["start"], "image_prompt": "x"}]},
                                   words, 3, [])
        assert res[0]["hero"] is False


def _moment(t, dur=2.0, **k):
    return {"t": t, "dur": dur, "anchor": "a", "query": "q", "prompt": "p", "role": None, "shot": None, "style": None,
            "notion": "", "real_photo": False, "hero": False, **k}


class TestHero:
    DUR = 40.0

    def test_a_concrete_wide_example_beats_a_close_concept(self):
        ms = [_moment(8.0, role="concept", shot="close", style="photo"),
              _moment(18.0, role="example", shot="wide", style="photo"),
              _moment(28.0, role="concept", shot="medium", style="photo")]
        assert broll.pick_hero(ms, self.DUR, []) == 1

    def test_the_planner_pick_counts_unless_it_breaks_the_timing(self):
        ms = [_moment(8.0, role="example", shot="wide", style="photo"),
              _moment(18.0, role="concept", shot="close", style="photo", hero=True)]
        assert broll.pick_hero(ms, self.DUR, []) == 1
        # ... on the punchline, it is overruled
        assert broll.pick_hero(ms, self.DUR, [19.0]) == 0

    def test_never_in_the_hook_the_tail_or_on_the_punchline(self):
        assert broll.pick_hero([_moment(3.0, role="example", shot="wide")], self.DUR, []) is None
        assert broll.pick_hero([_moment(37.5, role="example", shot="wide")], self.DUR, []) is None
        assert broll.pick_hero([_moment(20.0, role="example", shot="wide")], self.DUR, [21.0]) is None
        assert broll.pick_hero([_moment(20.0, role="example", shot="wide")], self.DUR, [25.0]) == 0

    def test_a_diagram_or_a_schematic_never_fills_the_screen(self):
        assert broll.pick_hero([_moment(20.0, role="example", shot="schematic", style="diagram")], self.DUR, []) is None
        assert broll.pick_hero([_moment(20.0, role="concept", shot="close", style="photo")], self.DUR, []) == 0

    def test_a_kept_notion_picture_is_not_a_hero(self):
        assert broll.pick_hero([_moment(20.0, role="example", shot="wide", notion="Dopamine")], self.DUR, []) is None

    def test_hero_duration_is_its_sentence_plus_the_fade_within_bounds(self):
        assert broll.hero_dur(_moment(10.0, dur=1.5)) == broll.HERO_DUR_MIN
        assert broll.hero_dur(_moment(10.0, dur=3.0)) == round(min(broll.HERO_DUR_MAX, 3.0 + broll.HERO_FADE), 2)
        assert broll.hero_dur(_moment(10.0, dur=9.0)) == broll.HERO_DUR_MAX
        assert broll.HERO_DUR_MIN >= 2.5 and broll.HERO_DUR_MAX <= 3.5


class TestNotionShapes:
    def test_one_kept_picture_per_layout_family(self):
        paths = {lay: broll._notion_path("Dopamine", "neon", "zimage", lay) for lay in ("rise", "full", "hero", "card")}
        assert len(set(paths.values())) == 4
        assert paths["rise"].endswith("__sq.jpg") and paths["full"].endswith("__tall.jpg")
        assert paths["hero"].endswith("__hero.jpg") and paths["card"].endswith("__wide.jpg")
        # the historical callers passed a bool
        assert broll._notion_path("Dopamine", "neon", "zimage", True) == paths["rise"]
        assert broll._notion_path("Dopamine", "neon", "zimage", False) == paths["full"]

    def test_the_library_reads_the_layout_back_from_the_file_name(self):
        assert [broll._layout_of(s) for s in ("sq", "tall", "hero", "wide", "???")] == ["rise", "full", "hero", "card", "full"]

    def test_generation_sizes(self):
        assert broll._gen_size("rise") == broll.RISE_GEN
        assert broll._gen_size("full") == (768, 1344)
        assert broll._gen_size("hero") == broll.HERO_GEN["std"] == (896, 1600)
        assert broll._gen_size("hero", "high") == (1024, 1792)


class TestProfile:
    def test_layouts_and_hero_size(self):
        assert plus.sanitize({})["broll"]["layout"] == "full"
        assert plus.sanitize({"broll": {"layout": "mixed"}})["broll"]["layout"] == "mixed"
        assert plus.sanitize({"broll": {"layout": "fortune"}})["broll"]["layout"] == "full"
        assert plus.sanitize({})["broll"]["hero_res"] == "std"
        assert plus.sanitize({"broll": {"hero_res": "high"}})["broll"]["hero_res"] == "high"
        assert plus.sanitize({"broll": {"hero_res": "4k"}})["broll"]["hero_res"] == "std"


class TestHeroFrames:
    def test_crossfade_push_in_and_bottom_gradient(self):
        tmp = tempfile.mkdtemp(prefix="hero_")
        src = os.path.join(tmp, "s.jpg")
        Image.new("RGB", (224, 400), (140, 140, 140)).save(src, quality=95)
        folder = os.path.join(tmp, "f")
        os.makedirs(folder)
        fps, dur, W, H = 10, 1.0, 108, 192
        pattern = broll._hero_frames(src, folder, fps, dur, W, H)
        frames = sorted(f for f in os.listdir(folder) if f.endswith(".png"))
        assert len(frames) == 10 and pattern.endswith("c%03d.png")
        first = Image.open(os.path.join(folder, frames[0]))
        mid = Image.open(os.path.join(folder, frames[5]))
        last = Image.open(os.path.join(folder, frames[-1]))
        assert first.size == (W, H) and first.mode == "RGBA"
        assert first.getchannel("A").getextrema() == (0, 0)             # starts transparent: a crossfade, not a pop
        assert mid.getchannel("A").getextrema() == (255, 255)
        assert 0 < last.getchannel("A").getextrema()[0] < 255               # fading out at the end
        rgb = mid.convert("RGB")
        top = sum(rgb.crop((W // 4, H // 2 - 10, 3 * W // 4, H // 2)).convert("L").getdata()) / (W // 2 * 10)
        bottom = sum(rgb.crop((W // 4, H - 10, 3 * W // 4, H)).convert("L").getdata()) / (W // 2 * 10)
        assert bottom < top - 25                                             # the dark gradient for the captions

    def test_the_grain_moves_from_frame_to_frame(self):
        tmp = tempfile.mkdtemp(prefix="hero_")
        src = os.path.join(tmp, "s.jpg")
        Image.new("RGB", (224, 400), (140, 140, 140)).save(src, quality=95)
        folder = os.path.join(tmp, "f")
        os.makedirs(folder)
        broll._hero_frames(src, folder, 10, 1.0, 108, 192)
        a = Image.open(os.path.join(folder, "c004.png")).convert("L").crop((40, 90, 60, 100)).tobytes()
        b = Image.open(os.path.join(folder, "c005.png")).convert("L").crop((40, 90, 60, 100)).tobytes()
        assert a != b


class _Captured:
    def __init__(self):
        self.cmds = []

    def __call__(self, cmd, *a, **k):
        self.cmds.append(list(cmd))

        class R:
            returncode = 0
        return R()


class TestOverlay:
    def _run(self, monkeypatch, items):
        import viral_fx
        monkeypatch.setattr(viral_fx, "_probe", lambda p: {"w": 108, "h": 192, "fps": 10, "duration": 8.0})
        cap = _Captured()
        monkeypatch.setattr(broll.subprocess, "run", cap)
        broll.overlay_items("clip.mp4", "out.mp4", items)
        cmd = cap.cmds[-1]
        return cmd[cmd.index("-filter_complex") + 1]

    def test_a_hero_covers_the_frame_and_leaves_the_podcast_sharp(self, monkeypatch):
        tmp = tempfile.mkdtemp(prefix="ov_")
        src = os.path.join(tmp, "h.jpg")
        Image.new("RGB", (224, 400), (90, 60, 30)).save(src)
        graph = self._run(monkeypatch, [{"t": 2.0, "dur": 3.0, "layout": "hero", "_img": src}])
        assert "boxblur" not in graph
        assert "overlay=0:0" in graph and "between(t,2.000,5.000)" in graph

    def test_the_historical_full_card_still_blurs_the_podcast(self, monkeypatch):
        tmp = tempfile.mkdtemp(prefix="ov_")
        src = os.path.join(tmp, "t.jpg")
        Image.new("RGB", (192, 336), (90, 60, 30)).save(src)
        graph = self._run(monkeypatch, [{"t": 2.0, "dur": 1.4, "layout": "full", "_img": src}])
        assert "boxblur" in graph


def _transcript(text, step=0.42):
    return {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in _words(text, step)]}]}


class TestAddBroll:
    """add_broll with everything around it stubbed: which pictures are asked, at what size, and the items it returns."""

    @pytest.fixture
    def stubs(self, monkeypatch):
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look=""):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            made.append(tuple(size))
            return out_path

        cut = []
        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "local_image", fake_image)
        monkeypatch.setattr(broll, "review_images", lambda cands, words: [{"score": 5} for _ in cands])
        monkeypatch.setattr(broll, "overlay_items", lambda clip, out, items, img_dir=None: cut.append(items))
        return made, cut

    def _plan(self, monkeypatch, words, hero_flag=None):
        idx = {w["text"]: i for i, w in enumerate(words)}

        def mk(a, **k):
            return {"anchor": a, "time": words[idx[a]]["start"], "image_prompt": "a scene of " + a, **k}

        # "story." falls in the hook's seconds and is dropped by _parse_moments; the four others are kept.
        data = {"moments": [mk("story.", role="concept", shot="close", style="neon"),
                            mk("soldiers", role="example", shot="wide", style="photo"),
                            mk("marched", role="example", shot="close", style="photo"),
                            mk("drill", role="concept", shot="close", style="neon"),
                            mk("sergeant", role="consequence", shot="medium", style="photo")]}
        if hero_flag is not None:
            data["moments"][hero_flag]["hero"] = True
        seen = {}

        def fake_plan(clip, words_, n, avoid, *a, **k):
            seen.update(k)
            return broll._parse_moments(data, words_, n, avoid, broll.DENSITY["normal"]["gap"])

        monkeypatch.setattr(broll, "plan_with_claude", fake_plan)
        return seen

    def test_mixed_makes_one_hero_at_its_own_size_and_small_cards(self, monkeypatch, stubs):
        made, cut = stubs
        tr = _transcript(TEXT)
        words = [{"text": w["word"].strip(), "start": w["start"], "end": w["end"]} for w in tr["segments"][0]["words"]]
        seen = self._plan(monkeypatch, words)
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "max": 4, "density": "normal", "engine": "zimage"}
        rep = broll.add_broll("clip.mp4", "out.mp4", {"punchline_time": None}, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert seen.get("hero") is True
        items = rep["items"]
        assert len(items) == 4
        heroes = [it for it in items if it["layout"] == "hero"]
        # two concrete scenes tie (the wide soldiers, the medium sergeant): the later one, the payoff, wins
        assert len(heroes) == 1 and heroes[0]["anchor"] == "sergeant"
        assert broll.HERO_DUR_MIN <= heroes[0]["dur"] <= broll.HERO_DUR_MAX
        assert heroes[0]["gen"] == [896, 1600] and "enter" not in heroes[0]
        cards = [it for it in items if it["layout"] != "hero"]
        assert cards and all(it["layout"] == "rise" and it["gen"] == list(broll.RISE_GEN) for it in cards)
        assert sorted(made) == sorted([(896, 1600)] + [broll.RISE_GEN] * len(cards))
        for a, b in zip(items, items[1:]):
            assert a["t"] + a["dur"] <= b["t"] - 0.24
        assert cut and cut[0] == items

    def test_high_hero_size_from_the_profile(self, monkeypatch, stubs):
        made, _ = stubs
        tr = _transcript(TEXT)
        words = [{"text": w["word"].strip(), "start": w["start"], "end": w["end"]} for w in tr["segments"][0]["words"]]
        self._plan(monkeypatch, words)
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "max": 4, "hero_res": "high"}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert (1024, 1792) in made and [it for it in rep["items"] if it["layout"] == "hero"][0]["gen"] == [1024, 1792]

    def test_the_historical_layouts_are_untouched(self, monkeypatch, stubs):
        made, _ = stubs
        tr = _transcript(TEXT)
        words = [{"text": w["word"].strip(), "start": w["start"], "end": w["end"]} for w in tr["segments"][0]["words"]]
        seen = self._plan(monkeypatch, words)
        for layout, size in (("rise", broll.RISE_GEN), ("full", (768, 1344))):
            made.clear()
            rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1,
                                  {"planner": "claude", "layout": layout, "style": "auto", "max": 4})
            assert seen.get("hero") is False
            assert set(made) == {size}
            assert all(it["layout"] == layout and "gen" not in it for it in rep["items"])


class TestPlannerPrompt:
    def test_the_hero_rule_and_field_only_in_the_mixed_layout(self, monkeypatch):
        import ai_brain
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
        seen = {}

        def fake_json(prompt, schema, **k):
            seen["prompt"], seen["schema"] = prompt, schema
            return {"moments": []}

        monkeypatch.setattr(broll, "claude_json", fake_json)
        words = _words(TEXT)
        broll.plan_with_claude({}, words, 4, [])
        assert "HERO IMAGE" not in seen["prompt"]
        assert "hero" not in seen["schema"]["properties"]["moments"]["items"]["properties"]
        plain = seen["prompt"]
        broll.plan_with_claude({}, words, 4, [], hero=True)
        assert seen["prompt"].startswith(plain) and "HERO IMAGE" in seen["prompt"]
        assert seen["schema"]["properties"]["moments"]["items"]["properties"]["hero"] == {"type": "boolean"}
        assert "hero" not in broll.PLAN_SCHEMA["properties"]["moments"]["items"]["properties"]
