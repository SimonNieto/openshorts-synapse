"""The hero composed (B-roll v2, chantier D'): every picture keeps the seed it was made with, the hero may ask its
own step count, a manual remake can reuse a seed. The 9:16 composition rule itself lives in the art director's
request (test_broll_art). Nothing here talks to ComfyUI."""
import pytest
from PIL import Image

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
    monkeypatch.delenv("COMFYUI_ZIMAGE_STEPS", raising=False)


def _sampler(graph):
    return next(n["inputs"] for n in graph.values() if n.get("class_type") == "KSampler")


class TestTheGraph:
    def test_steps_default_env_and_parameter(self, monkeypatch):
        assert _sampler(broll._graph("zimage", "x", 1, 896, 1600))["steps"] == 8
        monkeypatch.setenv("COMFYUI_ZIMAGE_STEPS", "10")
        assert _sampler(broll._graph("zimage", "x", 1, 896, 1600))["steps"] == 10
        assert _sampler(broll._graph("zimage", "x", 1, 896, 1600, steps=12))["steps"] == 12
        assert _sampler(broll._graph("zimage", "x", 7, 896, 1600))["seed"] == 7

    def test_the_hero_steps_knob_is_off_by_default(self):
        assert broll.HERO_STEPS == 0


class TestLocalImage:
    def _run(self, monkeypatch, **kw):
        seen = {}

        def fake_graph(engine, text, seed, width=768, height=1344, steps=None):
            seen.update(seed=seed, steps=steps, size=(width, height))
            raise RuntimeError("stop here")

        monkeypatch.setattr(broll, "_graph", fake_graph)
        with pytest.raises(RuntimeError, match="stop here"):
            broll.local_image("A brain.", "photo", "o.jpg", size=(896, 1600), **kw)
        return seen

    def test_a_given_seed_and_steps_reach_the_graph(self, monkeypatch):
        seen = self._run(monkeypatch, seed=42, steps=12)
        assert seen == {"seed": 42, "steps": 12, "size": (896, 1600)}

    def test_no_seed_means_a_new_one(self, monkeypatch):
        a = self._run(monkeypatch)["seed"]
        b = self._run(monkeypatch)["seed"]
        assert 0 <= a < 2 ** 48 and a != b


class TestInTheJob:
    @pytest.fixture
    def stubs(self, monkeypatch):
        made = []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", **kw):
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            made.append({"prompt": prompt, "size": size, "out": out_path, **kw})
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
                             "shot": s, "style": "photo"} for a, s in (("soldiers", "wide"), ("drill", "close"), ("sergeant", "medium"))]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
        tr = {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in words]}]}
        return made, tr, words

    def test_every_item_keeps_its_seed(self, stubs):
        made, tr, words = stubs
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "house_look": "h"}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        seeds = {m["out"]: m["seed"] for m in made}
        assert all(isinstance(it["seed"], int) for it in rep["items"])
        assert sorted(it["seed"] for it in rep["items"]) == sorted(seeds.values())
        assert len(set(seeds.values())) == len(seeds)
        # the hero asked no particular step count (the knob is off), nor did the cards
        assert all(m["steps"] is None for m in made)

    def test_the_hero_alone_takes_the_hero_steps(self, monkeypatch, stubs):
        made, tr, words = stubs
        monkeypatch.setattr(broll, "HERO_STEPS", 12)
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "house_look": "h"}
        broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        by_size = {m["size"]: m["steps"] for m in made}
        assert by_size[(896, 1600)] == 12 and by_size[(1152, 720)] is None

    def test_a_redo_has_its_own_seed(self, monkeypatch, stubs):
        made, tr, words = stubs
        monkeypatch.setattr(broll, "review_images",
                            lambda cands, words_: [{"score": 2, "better_prompt": "Closer."} if c["file"].endswith("broll_1.jpg")
                                                   else {"score": 5} for c in cands])
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "house_look": "h"}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        redo = next(m for m in made if m["prompt"] == "Closer.")
        drill = next(it for it in rep["items"] if it["anchor"] == "drill")
        assert drill["seed"] == redo["seed"] and drill["prompt"] == "Closer."


class TestRegenerate:
    def test_seed_and_steps_pass_through(self, monkeypatch):
        seen = []
        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)
        monkeypatch.setattr(broll, "local_image", lambda prompt, style, out, **kw: seen.append(kw) or out)
        broll.regenerate_image("A brain.", "photo", "o.jpg", cfg={"layout": "hero"}, gen=[896, 1600], seed=99, steps=12)
        broll.regenerate_image("A brain.", "photo", "o.jpg", cfg={"layout": "hero"}, gen=[896, 1600])
        assert (seen[0]["seed"], seen[0]["steps"]) == (99, 12) and (seen[1]["seed"], seen[1]["steps"]) == (None, None)
