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
    monkeypatch.setattr(broll, "HERO_TAKES", 1)   # the hero's takes have their own tests
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
        assert broll.pick_hero([_moment(20.0, role="concept", shot="close", style="photo")], self.DUR, []) is None
        assert broll.pick_hero([_moment(10.0, role="concept", shot="medium", style="photo")], self.DUR, []) is None
        assert broll.pick_hero([_moment(20.0, role="concept", shot="medium", style="photo")], self.DUR, []) == 0
        assert broll.pick_hero([_moment(10.0, role="example", shot="close", style="photo")], self.DUR, []) == 0

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
    def test_the_drawing_is_the_house_recipe_not_a_profile_choice(self):
        # Since 1-oct-2026 the profile only says whether a channel wants images; the layout,
        # the hero size and the rest come from plus.BROLL and reach the job through PLUS_BROLL_JSON.
        assert (plus.BROLL["layout"], plus.BROLL["hero_res"], plus.BROLL["engine"]) == ("mixed", "std", "zimage")
        assert plus.sanitize({"broll": {"enabled": True, "layout": "fortune", "hero_res": "4k"}})["broll"] == {"enabled": True}
        cfg = json.loads(plus.job_env({"name": "t", "broll": {"enabled": True}})["PLUS_BROLL_JSON"])
        assert cfg["layout"] == "mixed" and cfg["hero_res"] == "std" and cfg["enabled"] is True
        assert "PLUS_BROLL_JSON" not in plus.job_env({"name": "t"})


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

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
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
        assert cards and all(it["layout"] == "card" and it["gen"] == list(broll.CARD_GEN) for it in cards)
        assert sorted(made) == sorted([(896, 1600)] + [broll.CARD_GEN] * len(cards))
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
        assert "HERO IMAGE" not in plain and "HERO IMAGE" in seen["prompt"]
        assert seen["schema"]["properties"]["moments"]["items"]["properties"]["hero"] == {"type": "boolean"}
        assert "hero" not in broll.PLAN_SCHEMA["properties"]["moments"]["items"]["properties"]


# --- chantier C: the wide cards of the "mixed" layout -------------------------------------

class TestCardGeometry:
    def test_a_wide_card_above_the_head_stays_in_its_band(self):
        g = broll.rise_geometry("natural", True, "top", 60, aspect=0.625)
        b = g["box"]
        assert g["effective_pct"] == 60 and not g["limited"] and not g["into_app_zone"]
        assert b["y"] >= int(1920 * broll.TOP_BAND[0]) and b["y"] + b["h"] <= int(1920 * broll.TOP_BAND[1])
        assert abs(b["h"] / b["w"] - 0.625) < 0.01

    def test_the_band_above_the_head_limits_a_card_taller_than_it(self):
        g = broll.rise_geometry("natural", True, "top", 60, aspect=1.0)      # a 60 % square does not fit above the head
        assert g["limited"] and g["box"]["y"] + g["box"]["h"] <= int(1920 * broll.TOP_BAND[1])

    def test_the_historical_positions_are_unchanged(self):
        assert broll.rise_geometry("natural", True, "below", 28)["box"] == {"x": 389, "y": 1274, "w": 302, "h": 302}
        assert broll.rise_geometry("natural", True, "above", 27)["box"] == {"x": 394, "y": 818, "w": 291, "h": 291}
        above = broll.rise_geometry("natural", True, "above", 27)["box"]
        assert above["y"] + above["h"] <= broll._caption_band(1920, "natural", True)[0]

    def test_the_premium_edge(self):
        w, rim, shade, blur = broll._border("premium", 3, 0)
        assert (w, rim, shade, blur) == (1, 30, 60, 2.0)
        assert broll._border("soft", 3, 0) == (2, 110, 85, 1.0)


class TestCardDurations:
    def test_mixed_cards_last_from_two_point_two_to_three_and_a_half_seconds(self):
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}

        def mk(a):
            return {"anchor": a, "time": words[idx[a]]["start"], "image_prompt": a}

        data = {"moments": [mk("soldiers"), mk("marched"), mk("drill"), mk("sergeant")]}
        legacy = broll._parse_moments(data, words, 6, [], 4.0)
        prem = broll._parse_moments(data, words, 6, [], 4.0, (broll.CARD_DUR_MIN, broll.CARD_DUR_MAX))
        assert all(broll.DUR_MIN <= m["dur"] <= broll.DUR_MAX for m in legacy)
        assert all(broll.CARD_DUR_MIN <= m["dur"] <= broll.CARD_DUR_MAX for m in prem)
        assert any(p["dur"] > l["dur"] for p, l in zip(prem, legacy))      # a short clause: the higher floor lifts it


class TestPremiumCardFrames:
    def _render(self, **kw):
        tmp = tempfile.mkdtemp(prefix="card_")
        src = os.path.join(tmp, "s.jpg")
        Image.new("RGB", (576, 360), (120, 90, 60)).save(src, quality=95)
        folder = os.path.join(tmp, "f")
        os.makedirs(folder)
        return broll._rise_frames(src, folder, 20, 2.4, 540, 960, 60, "top", **kw), folder

    def test_fades_in_while_rising_a_few_pixels_and_fades_out(self):
        (pattern, x, motion), folder = self._render(look="premium", border="premium")
        ys, ye, drift, cvh, rise_s = motion
        assert ys - ye == broll.CARD_RISE_PX and rise_s == broll.CARD_IN     # no travel from the edge of the screen
        frames = sorted(f for f in os.listdir(folder) if f.endswith(".png"))
        a0 = Image.open(os.path.join(folder, frames[0])).getchannel("A").getextrema()[1]
        a_mid = Image.open(os.path.join(folder, frames[len(frames) // 2])).getchannel("A").getextrema()[1]
        a_last = Image.open(os.path.join(folder, frames[-1])).getchannel("A").getextrema()[1]
        assert a0 < 40 and a_mid == 255 and a_last < 120

    def test_the_historical_card_still_comes_from_the_edge(self):
        (pattern, x, motion), folder = self._render()
        assert len(motion) == 4 and motion[0] < 0            # from the top edge: the card lands in the upper half

    def test_a_label_in_the_corner_when_asked(self):
        (_, _, _), plain = self._render(look="premium", border="premium")
        (_, _, _), labelled = self._render(look="premium", border="premium", label="dopamine")
        a = Image.open(os.path.join(plain, "c024.png")).convert("L")
        b = Image.open(os.path.join(labelled, "c024.png")).convert("L")
        assert a.size == b.size and a.tobytes() != b.tobytes()
        W, H = a.size
        assert a.crop((0, 0, W, H // 2)).tobytes() == b.crop((0, 0, W, H // 2)).tobytes()   # only the lower part changed


class TestMixedCards:
    def test_the_cards_are_drawn_one_way(self):
        # No keyword on the cards, 60 % wide above the head: the house recipe, nothing in the profile.
        assert plus.BROLL["label"] is False
        assert "card_position" not in plus.BROLL and "card_size" not in plus.BROLL and "position" not in plus.BROLL
        assert (broll.CARD_SIZE, broll.CARD_POSITION) == (60, "top")

    def test_mixed_cards_are_wide_premium_and_above_the_head(self, monkeypatch):
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            made.append(tuple(size))
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
        data = {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": a, "subject": s, "role": r, "shot": sh}
                            for a, s, r, sh in (("soldiers", "soldiers", "example", "wide"),
                                                ("marched", "night march", "example", "close"),
                                                ("sergeant", "sergeant", "consequence", "medium"))]}
        seen = {}

        def fake_plan(clip, words_, n, avoid, *a, **k):
            seen.update(k)
            return broll._parse_moments(data, words_, n, avoid, broll.DENSITY["normal"]["gap"], k.get("dur_range"))

        monkeypatch.setattr(broll, "plan_with_claude", fake_plan)
        # The rise layout's settings the user's saved profile carries (fixed hold, "my height", a strong edge, an
        # exit zoom, a card size) do not touch the premium drawing.
        cfg = {"planner": "claude", "layout": "mixed", "style": "photo", "max": 4, "label": True, "y": 73.1,
               "hold": 3.0, "border": "strong", "zoom": "strong", "enter": "rise", "size": 27, "position": "below"}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert seen["dur_range"] == (broll.CARD_DUR_MIN, broll.CARD_DUR_MAX)
        cards = [it for it in rep["items"] if it["layout"] == "card"]
        assert len(cards) == 2 and (1152, 720) in made
        for it in cards:
            assert it["look"] == "premium" and it["border"] == "premium" and it["position"] == "top" and it["size"] == 60
            assert it["gen"] == [1152, 720] and broll.CARD_DUR_MIN <= it["dur"] <= broll.CARD_DUR_MAX + 0.01
            assert "y" not in it and "zoom" not in it and "enter" not in it
        assert {it["dur"] for it in cards} != {3.0}                    # to the end of the sentence, not the fixed hold
        assert [it["label"] for it in cards] == ["soldiers", "night march"]
        hero = [it for it in rep["items"] if it["layout"] == "hero"][0]
        assert "label" not in hero and "look" not in hero and hero["border"] == "premium"

    def test_the_rise_layout_keeps_its_historical_rise_time(self, monkeypatch):
        import viral_fx
        monkeypatch.setattr(viral_fx, "_probe", lambda p: {"w": 108, "h": 192, "fps": 10, "duration": 8.0})
        cap = _Captured()
        monkeypatch.setattr(broll.subprocess, "run", cap)
        tmp = tempfile.mkdtemp(prefix="ov_")
        src = os.path.join(tmp, "s.jpg")
        Image.new("RGB", (256, 256), (90, 60, 30)).save(src)
        broll.overlay_items("clip.mp4", "out.mp4", [{"t": 2.0, "dur": 1.9, "layout": "rise", "size": 28, "_img": src}])
        graph = cap.cmds[-1][cap.cmds[-1].index("-filter_complex") + 1]
        assert f"/{broll.RISE_IN}" in graph


# --- chantier E: the pace of the "mixed" layout -------------------------------------------

class TestPace:
    def test_nothing_runs_into_the_last_seconds(self):
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        duration = words[-1]["end"]
        late = next(w["text"] for w in words if w["start"] > duration - 3.4)      # a word just before the tail
        data = {"moments": [{"anchor": "soldiers", "time": words[idx["soldiers"]]["start"], "image_prompt": "a"},
                            {"anchor": late, "time": words[idx[late]]["start"], "image_prompt": "b"}]}
        # the historical window lets the image start until duration - 3.6 s, 1 s before the end at most
        plain = broll._parse_moments(data, words, 6, [])
        assert len(plain) in (1, 2)
        paced = broll._parse_moments(data, words, 6, [], 4.0, (broll.CARD_DUR_MIN, broll.CARD_DUR_MAX), tail=broll.MIXED_TAIL)
        assert all(m["t"] + m["dur"] <= duration - broll.MIXED_TAIL + 1e-6 for m in paced)
        assert all(m["dur"] >= broll.CARD_DUR_MIN for m in paced)

    def test_a_longer_hook_pushes_the_first_image_back(self):
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"moments": [{"anchor": "soldiers", "time": words[idx["soldiers"]]["start"], "image_prompt": "a"}]}
        assert broll._parse_moments(data, words, 3, [])                            # 5.5 s: past the 4.3 s head room
        assert not broll._parse_moments(data, words, 3, [], head=6.3)             # a 6 s hook: left to the face

    def test_mixed_asks_for_few_images_far_apart(self, monkeypatch):
        seen = {}

        def fake_plan(clip, words_, n, avoid, *a, **k):
            seen.update(k, n=n)
            return []

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "plan_with_claude", fake_plan)
        tr = _transcript(TEXT)
        end = tr["segments"][0]["words"][-1]["end"] + 1
        base = {"planner": "claude", "style": "photo", "max": 10, "density": "more"}
        monkeypatch.setenv("AUTO_HOOK", "1")
        monkeypatch.setenv("AUTO_HOOK_SECONDS", "6")
        broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, end, {**base, "layout": "mixed"})
        assert (seen["n"], seen["gap_min"], seen["tail"], seen["head"]) == (broll.MIXED_MAX, broll.MIXED_GAP, broll.MIXED_TAIL, 6.3)
        broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, end, {**base, "layout": "mixed", "density": "less"})
        assert seen["n"] == broll.MIXED_FEW == 3
        broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, end, {**base, "layout": "mixed", "max": 1, "density": "normal"})
        assert seen["n"] == broll.MIXED_MAX                              # the profile's max is a rise / full setting
        broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, end, {**base, "layout": "rise"})
        assert (seen["n"], seen["gap_min"], seen["tail"], seen["head"]) == (broll.image_count(10, "more"), 0.0, None, broll.HEAD_FREE)

    def test_the_clip_log_line(self, monkeypatch, capsys):
        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
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
        data = {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": a, "role": "example", "shot": "wide"}
                            for a in ("soldiers", "drill", "sergeant")]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 4.0, k.get("dur_range"),
                                                                                           k.get("tail"), k.get("head")))
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1,
                              {"planner": "claude", "layout": "mixed", "style": "photo", "max": 4})
        out = capsys.readouterr().out
        line = next(l for l in out.splitlines() if "🖼️ B-roll mixed:" in l)
        assert f"{len(rep['items'])} image(s) (1 hero)" in line and "covered" in line and "ComfyUI" in line
        for a, b in zip(rep["items"], rep["items"][1:]):
            assert b["t"] - a["t"] >= broll.MIXED_GAP - 1e-6


# --- chantier G: a sound when the hero arrives --------------------------------------------

class TestSfx:
    def _run(self, monkeypatch, items, fail_first=False):
        import subprocess
        import viral_fx
        monkeypatch.setattr(viral_fx, "_probe", lambda p: {"w": 108, "h": 192, "fps": 10, "duration": 8.0})
        cmds = []

        def run(cmd, *a, **k):
            cmds.append(list(cmd))
            if fail_first and len(cmds) == 1:
                raise subprocess.CalledProcessError(1, cmd)

            class R:
                returncode = 0
            return R()

        monkeypatch.setattr(broll.subprocess, "run", run)
        broll.overlay_items("clip.mp4", "out.mp4", items)
        return cmds

    def _hero(self, sfx=True):
        tmp = tempfile.mkdtemp(prefix="sfx_")
        src = os.path.join(tmp, "h.jpg")
        Image.new("RGB", (224, 400), (90, 60, 30)).save(src)
        it = {"t": 2.0, "dur": 3.0, "layout": "hero", "_img": src}
        if sfx:
            it["sfx"] = True
        return it

    def test_the_whoosh_is_mixed_under_the_voice_when_asked(self, monkeypatch):
        assert os.path.exists(broll.SFX_PATH)
        cmd = self._run(monkeypatch, [self._hero()])[-1]
        graph = cmd[cmd.index("-filter_complex") + 1]
        assert broll.SFX_PATH in cmd and "adelay=1880|1880" in graph and f"volume={broll.SFX_GAIN_DB:g}dB" in graph
        assert "amix=inputs=2:duration=first:normalize=0[a]" in graph
        assert cmd[cmd.index("-c:a") + 1] == "aac" and "[a]" in cmd

    def test_no_flag_or_no_file_means_the_audio_is_copied(self, monkeypatch):
        cmd = self._run(monkeypatch, [self._hero(sfx=False)])[-1]
        assert cmd[cmd.index("-c:a") + 1] == "copy" and "adelay" not in cmd[cmd.index("-filter_complex") + 1]
        monkeypatch.setattr(broll, "SFX_PATH", os.path.join(tempfile.gettempdir(), "no_such_whoosh.wav"))
        cmd = self._run(monkeypatch, [self._hero()])[-1]
        assert cmd[cmd.index("-c:a") + 1] == "copy"

    def test_a_failed_mix_falls_back_to_the_plain_cut(self, monkeypatch):
        cmds = self._run(monkeypatch, [self._hero()], fail_first=True)
        assert len(cmds) == 2 and "adelay" in cmds[0][cmds[0].index("-filter_complex") + 1]
        assert cmds[1][cmds[1].index("-c:a") + 1] == "copy" and broll.SFX_PATH not in cmds[1]

    def test_only_the_hero_of_a_mixed_clip_gets_the_flag(self, monkeypatch):
        assert plus.BROLL["sfx"] is True, "the whoosh is part of the house recipe"

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
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
        data = {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": a, "role": "example", "shot": "wide"}
                            for a in ("soldiers", "drill", "sergeant")]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 4.0, k.get("dur_range"),
                                                                                           k.get("tail"), k.get("head")))
        for layout, want in (("mixed", True), ("rise", False)):
            rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1,
                                  {"planner": "claude", "layout": layout, "style": "photo", "max": 4, "sfx": True})
            assert [bool(it.get("sfx")) for it in rep["items"]] == [it["layout"] == "hero" and want for it in rep["items"]]
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1,
                              {"planner": "claude", "layout": "mixed", "style": "photo", "max": 4})
        assert not any(it.get("sfx") for it in rep["items"])


# --- robustness: one failed picture, several clips at once ----------------------------------

class TestRobustness:
    def _setup(self, monkeypatch, fail):
        """``fail``: {prompt substring: how many times local_image raises for it}."""
        calls = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
            calls.append(prompt)
            for key, n in fail.items():
                if key in prompt and sum(key in c for c in calls) <= n:
                    raise RuntimeError("ComfyUI error: CUDA out of memory")
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
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
        data = {"moments": [{"anchor": a, "time": words[idx[a]]["start"], "image_prompt": "scene of " + a}
                            for a in ("soldiers", "drill", "sergeant")]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 4.0))
        return tr, words, calls

    def test_a_picture_that_fails_twice_is_skipped_and_the_clip_keeps_the_others(self, monkeypatch, capsys):
        tr, words, calls = self._setup(monkeypatch, {"drill": 5})
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1,
                              {"planner": "claude", "layout": "rise", "style": "photo", "max": 4})
        assert [it["anchor"] for it in rep["items"]] == ["soldiers", "sergeant"]
        assert sum("drill" in c for c in calls) == 2            # one retry, not more
        assert "no image for" in capsys.readouterr().out

    def test_a_transient_failure_is_retried_and_the_picture_kept(self, monkeypatch):
        tr, words, calls = self._setup(monkeypatch, {"drill": 1})
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1,
                              {"planner": "claude", "layout": "rise", "style": "photo", "max": 4})
        assert [it["anchor"] for it in rep["items"]] == ["soldiers", "drill", "sergeant"]

    def test_comfyui_that_stopped_answering_still_stops_the_job(self, monkeypatch):
        tr, words, calls = self._setup(monkeypatch, {"drill": 5})
        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: len(calls) < 2)   # up for the check, down after
        with pytest.raises(broll.ComfyDown):
            broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1,
                            {"planner": "claude", "layout": "rise", "style": "photo", "max": 4})

    def test_the_vram_is_given_back_by_the_last_clip_only(self, monkeypatch):
        released = []
        monkeypatch.setattr(broll, "comfy_release", lambda full=False: released.append(full))
        monkeypatch.setattr(broll, "_COMFY_USERS", {"n": 0})
        broll._comfy_enter()
        broll._comfy_enter()
        broll._comfy_leave()
        assert released == []
        broll._comfy_leave()
        assert released == [False]
        broll._comfy_leave()                                     # never below zero, never a second release
        assert released == [False] and broll._COMFY_USERS["n"] == 0

    def test_add_broll_counts_itself_in_and_out(self, monkeypatch):
        tr, words, calls = self._setup(monkeypatch, {})
        released = []
        monkeypatch.setattr(broll, "comfy_release", lambda full=False: released.append(full))
        monkeypatch.setattr(broll, "_COMFY_USERS", {"n": 1})    # another clip of this job is still making images
        seen = []
        real = broll.local_image
        monkeypatch.setattr(broll, "local_image", lambda *a, **k: seen.append(broll._COMFY_USERS["n"]) or real(*a, **k))
        broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1,
                        {"planner": "claude", "layout": "rise", "style": "photo", "max": 4})
        assert seen and all(n == 2 for n in seen) and released == [] and broll._COMFY_USERS["n"] == 1
        broll._comfy_leave()                                     # the other clip finishes: now the GPU is freed
        assert released == [False]
