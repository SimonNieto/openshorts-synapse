"""broll_bench.py ``plan``: the brain bench's pure parts (version specs, job lookup, the watch on broll,
the board). Nothing here calls Claude, ComfyUI or ffmpeg."""
import json
import os

import pytest
from PIL import Image

import broll
import broll_bench as bench


class TestVersions:
    def test_a_named_version_and_its_overrides(self):
        assert bench._version("current") == ("current", {})
        name, over = bench._version("v2:art_director=1;family=cinematic_photo;steps=12;ratio=0.5;faces=off")
        assert name == "v2"
        assert over == {"art_director": True, "family": "cinematic_photo", "steps": 12, "ratio": 0.5, "faces": False}

    def test_overrides_lay_over_the_named_version(self, monkeypatch):
        monkeypatch.setitem(bench.VERSIONS, "da", {"art_director": True, "family": "editorial_photo"})
        assert bench._version("da:family=archive") == ("da", {"art_director": True, "family": "archive"})

    def test_an_unknown_name_without_overrides_is_refused(self):
        with pytest.raises(ValueError):
            bench._version("nope")
        with pytest.raises(ValueError):
            bench._version("v2:art_director")


class TestJobLookup:
    def _job(self, root, name, shorts=1):
        d = os.path.join(root, "output", name)
        os.makedirs(d)
        with open(os.path.join(d, "x_metadata.json"), "w", encoding="utf-8") as f:
            json.dump({"shorts": [{"start": 0, "end": 10}] * shorts}, f)
        return d

    def test_a_prefix_finds_the_one_job(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bench, "HERE", str(tmp_path))
        d = self._job(str(tmp_path), "2bb7b6b6-0e8a-47af-92e3-80243afb200e")
        self._job(str(tmp_path), "2bc00000-0000")
        job_dir, meta = bench._find_job("2bb7")
        assert job_dir == d and len(meta["shorts"]) == 1

    def test_an_ambiguous_prefix_or_no_job_stops(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bench, "HERE", str(tmp_path))
        self._job(str(tmp_path), "aaaa1")
        self._job(str(tmp_path), "aaaa2")
        with pytest.raises(SystemExit):
            bench._find_job("aaaa")
        with pytest.raises(SystemExit):
            bench._find_job("zzzz")

    def test_a_clip_needs_its_pre_fx_render(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bench, "HERE", str(tmp_path))
        d = self._job(str(tmp_path), "bbbb", shorts=2)
        meta = {"shorts": [{"start": 0, "end": 10}, {"start": 20, "end": 30}]}
        with pytest.raises(SystemExit):
            bench._clip_of(d, meta, 2)
        open(os.path.join(d, "job [JRE #2515]_clip_2.pre_fx.mp4"), "wb").close()
        clip, pre = bench._clip_of(d, meta, 2)
        assert clip["start"] == 20 and pre.endswith("_clip_2.pre_fx.mp4")
        with pytest.raises(SystemExit):
            bench._clip_of(d, meta, 3)


class TestWatch:
    def test_the_watch_records_and_puts_broll_back(self, monkeypatch):
        graph = broll._graph
        plan = lambda *a, **k: [{"anchor": "brain", "subject": "brain", "thesis": "T"}]  # noqa: E731
        review = lambda cands, words: [{"file": "broll_0.jpg", "score": 4, "seen": "a brain"}]  # noqa: E731
        image = lambda prompt, style, out_path, **k: broll._graph("zimage", f"{prompt} FULL", 7, 1152, 720) and out_path  # noqa: E731
        monkeypatch.setattr(broll, "plan_with_claude", plan)
        monkeypatch.setattr(broll, "review_images", review)
        monkeypatch.setattr(broll, "local_image", image)
        with bench._Watch(broll) as w:
            moments = broll.plan_with_claude()
            broll.local_image("A brain.", "photo", "/tmp/x/broll_0.jpg", look="", house="")
            broll.review_images([{"file": "/tmp/x/broll_0.jpg", "k": 0, "layout": "card"}], [])
        assert moments[0]["thesis"] == "T" and w.moments[0]["subject"] == "brain"
        assert w.images == 1 and w.sent["broll_0.jpg"]["text"] == "A brain. FULL"
        assert w.sent["broll_0.jpg"]["seed"] == 7 and w.sent["broll_0.jpg"]["size"] == [1152, 720]
        assert w.sent["broll_0.jpg"]["steps"] == 8
        assert w.reviews == [{"file": "broll_0.jpg", "k": 0, "layout": "card", "score": 4, "seen": "a brain"}]
        assert set(w.seconds) == {"plan", "gpu", "review"}
        # the bench's patches are gone, the test's own ones are back in place
        assert broll.plan_with_claude is plan and broll.review_images is review and broll.local_image is image
        assert broll._graph is graph

    def test_k_of(self):
        assert bench._k_of("broll_3.jpg") == 3 and bench._k_of("broll_12_v2.jpg") == 12 and bench._k_of("x.jpg") is None


class TestBoard:
    def test_a_board_draws_every_kept_picture_with_its_texts(self, tmp_path):
        img_dir = tmp_path / "imgs"
        img_dir.mkdir()
        Image.new("RGB", (1152, 720), (90, 120, 150)).save(img_dir / "broll_0.jpg")
        Image.new("RGB", (896, 1600), (150, 90, 90)).save(img_dir / "broll_1.jpg")
        res = {"job": "2bb7b6b6-x", "clip": 3, "version": "current", "overrides": {}, "duration": 52.2,
               "title": "Is separation the brain's greatest illusion?", "hook": "Separation is a lie", "thesis": "We are one.",
               "sheet": {"palette": "teal, amber", "light": "window light"}, "sequence": ["brain", "crowd"],
               "planner": "claude", "images_dir": str(img_dir), "images_made": 3,
               "items": [{"k": 0, "image": "broll_0.jpg", "layout": "card", "t": 8.1, "dur": 2.4, "style": "photo", "score": 4,
                          "anchor": "the brain", "said": "the brain makes it up", "idea": "The brain builds the self.",
                          "prompt": "A brain model on a desk. " * 20, "grade": "cinematic", "shot": "close", "role": "concept",
                          "sent": {"text": "A brain model on a desk. " * 30, "seed": 5, "size": [1152, 720], "steps": 8}},
                         {"k": 1, "image": "broll_1.jpg", "layout": "hero", "t": 30.0, "dur": 3.2, "style": "photo", "score": 5,
                          "anchor": "the crowd", "prompt": "A crowd at dusk.", "planner_hero": True, "notion": "Crowd",
                          "sent": {"text": "A crowd at dusk. More.", "seed": 9, "size": [896, 1600], "steps": 8}}],
               "reviews": [{"file": "broll_0.jpg", "k": 0, "score": 3, "seen": "a brain", "problem": "generic", "better_prompt": "Closer."},
                           {"file": "broll_0_v2.jpg", "k": 0, "score": 4, "seen": "a closer brain"},
                           {"file": "broll_1.jpg", "k": 1, "score": 5, "seen": "a crowd"}],
               "dropped": [{"k": 2, "anchor": "water", "subject": "water", "layout": "card", "scores": [2], "problem": "off topic"}],
               "seconds": {"plan": 12.3, "gpu": 40.0, "review": 9.5, "total": 70.1},
               "usage": {"calls": 2, "input_tokens": 12345, "output_tokens": 678}}
        out = bench._board(res, str(tmp_path / "board.jpg"))
        im = Image.open(out)
        assert im.width == bench.BOARD_W and im.height > 2 * bench.THUMB_H + 200
        # the hero thumbnail (tall, reddish) and the card (wide, bluish) are both on the board, in the left column
        px = [im.getpixel((bench.THUMB_W // 2 + 24, y)) for y in range(0, im.height, 8)]
        assert any(p[2] > p[0] + 30 for p in px) and any(p[0] > p[2] + 30 for p in px)

    def test_a_board_without_pictures_still_renders(self, tmp_path):
        res = {"job": "j", "clip": 1, "version": "current", "overrides": {"art_director": True}, "duration": 30.0,
               "title": "", "hook": "", "thesis": "", "sheet": None, "sequence": [], "planner": None, "images_dir": str(tmp_path),
               "images_made": 0, "items": [], "reviews": [], "dropped": [], "seconds": {}, "usage": {}}
        out = bench._board(res, str(tmp_path / "empty.jpg"))
        assert Image.open(out).width == bench.BOARD_W

    def test_wrap_keeps_every_word(self):
        f = bench._font(18)
        text = "one two three four five six seven eight nine ten " * 5
        lines = bench._wrap(text, f, 300)
        assert " ".join(lines) == text.strip() and len(lines) > 3
        assert bench._wrap("", f, 300) == [""]
