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

    def test_a_nested_review_call_is_recorded_once(self, monkeypatch):
        def outer(cands, words):
            # like review_images: the hero to one judge, the rest to itself
            rest = [c for c in cands if c["layout"] != "hero"]
            inner = broll.review_images(rest, words) if rest and len(rest) < len(cands) else [{"score": 3} for _ in cands]
            return [{"score": 5} if c["layout"] == "hero" else inner.pop(0) for c in cands]

        monkeypatch.setattr(broll, "review_images", outer)
        cands = [{"file": "/x/broll_0.jpg", "k": 0, "layout": "card"}, {"file": "/x/broll_1.jpg", "k": 1, "layout": "hero"}]
        with bench._Watch(broll) as w:
            out = broll.review_images(cands, [])
        assert [r["score"] for r in out] == [3, 5]
        assert [(r["file"], r["score"]) for r in w.reviews] == [("broll_0.jpg", 3), ("broll_1.jpg", 5)]
        assert bench._dedupe_reviews([{"file": "a", "score": 2}, {"file": "b", "score": 4}, {"file": "a", "score": 5}]) == \
            [{"file": "a", "score": 5}, {"file": "b", "score": 4}]

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


class TestTheMoods:
    """B-roll « ambiance » (2-oct-2026): the board shows each picture's mood, grade and pixel check; the signature
    sheet shows the same pictures at each stamp strength; ``moods`` rates the same pictures again and again."""

    def _item(self, img_dir, said=""):
        import visual_mood
        Image.new("RGB", (1152, 720), (90, 120, 150)).save(img_dir / "broll_0.jpg")
        mood = {"valence": "grim", "intensity": "charged", "distance": "lived", "gravity": "real", "cue": "it hurt",
                **({"colours_said": said} if said else {})}
        g, px = visual_mood.check(str(img_dir / "broll_0.jpg"), visual_mood.grade(mood, {"valence": "neutral"}), mood)
        return {"k": 0, "image": "broll_0.jpg", "layout": "card", "t": 8.1, "dur": 2.4, "style": "photo", "score": 4,
                "anchor": "the scan", "subject": "scan", "prompt": "A scan.", "mood": mood, "mood_base": {"valence": "neutral"},
                "grade": g, "pixels": px}

    def test_the_board_line_says_mood_grade_and_pixels(self, tmp_path):
        it = self._item(tmp_path)
        line = bench._mood_line(it)
        assert line.startswith("MOOD grim · charged · lived · real («it hurt»)") and "clip base neutral" in line
        assert "GRADE sat " in line and "sig 0.2" in line and "PIXELS key " in line
        assert bench._mood_line({"style": "photo"}) == ""

    def test_the_signature_sheet_is_the_same_picture_at_each_strength(self, tmp_path):
        res = {"items": [self._item(tmp_path), {"k": 1, "image": "none.jpg", "grade": {"sig": 0.2}}],
               "images_dir": str(tmp_path)}
        out = bench._signature_sheet(res, [0.0, 0.2], str(tmp_path / "sig.jpg"))
        im = Image.open(out)
        assert im.height > 300 and im.width > 3 * 400
        assert bench._signature_sheet({"items": [], "images_dir": str(tmp_path)}, [0.2], str(tmp_path / "n.jpg")) is None
        assert bench._sigs("0, 0.2") == [0.0, 0.2] and bench._sigs("") == []

    def test_spread_grades_counts_the_grades_and_their_distance(self, tmp_path):
        import visual_mood
        Image.new("RGB", (64, 64), (120, 110, 100)).save(tmp_path / "broll_0.jpg")
        a, b = visual_mood.clean({"valence": "grim"}), visual_mood.clean({"valence": "neutral"})
        same = bench._spread_grades([{"subject": "x"}], [[a], [a], [a]], str(tmp_path), None)
        assert same == [{"k": 0, "subject": "x", "grades": 1, "max_delta_e": 0.0, "on_picture": True}]
        moved = bench._spread_grades([{"subject": "x"}, {"subject": "y"}], [[a, b], [b, b]], str(tmp_path), None)
        assert moved[0]["grades"] == 2 and moved[0]["max_delta_e"] > 3 and not moved[1]["on_picture"]

    def test_the_moods_command_rates_the_same_pictures_fresh(self, tmp_path, monkeypatch):
        import ai_brain
        import visual_mood
        monkeypatch.setattr(bench, "HERE", str(tmp_path))
        monkeypatch.setattr(bench, "BRAIN_DIR", str(tmp_path / "brain"))
        (tmp_path / "brain").mkdir()
        d = tmp_path / "output" / "abcd1234-x"
        d.mkdir(parents=True)
        words = [{"word": f" w{i}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(40)]
        with open(d / "x_metadata.json", "w", encoding="utf-8") as f:
            json.dump({"shorts": [{"start": 0, "end": 20, "video_title_for_youtube_short": "T"}],
                       "transcript": {"segments": [{"words": words}]}, "episode_brief": {"glossary": [{"term": "a"}]}}, f)
        with open(tmp_path / "brain" / "abcd1234_clip1_v9.json", "w", encoding="utf-8") as f:
            json.dump({"moments": [{"t": 4.0, "anchor": "w8", "said": "w8 w9", "subject": "thing",
                                    "mood": {"valence": "grim", "intensity": "steady"}}], "images_dir": str(tmp_path)}, f)
        answers = iter(["grim", "grim", "uneasy"])
        seen = []

        def fake_rate(moments, text, brief="", title="", fresh=True, **kw):
            seen.append(fresh)
            return [visual_mood.clean({"valence": next(answers), "intensity": "steady", "cue": "c"})]

        monkeypatch.setattr(visual_mood, "rate", fake_rate)
        monkeypatch.setattr(bench, "_profile", lambda pid=None: {"name": "p"})
        monkeypatch.setattr(bench, "_job_env", lambda prof: None)
        monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
        import argparse
        bench.cmd_moods(argparse.Namespace(job="abcd", clips="1", source="v9", runs=3, profile=None))
        assert seen == [True, True, True]
        with open(tmp_path / "brain" / "abcd1234_clip1_moods.json", encoding="utf-8") as f:
            row = json.load(f)
        assert row["spread"]["valence"]["agree"] == pytest.approx(2 / 3, abs=1e-3) and row["spread"]["valence"]["steps"] == 1
        assert row["spread"]["intensity"]["agree"] == 1.0 and row["per_picture"][0]["levels"]["valence"] == {"grim": 2, "uneasy": 1}
        assert row["per_picture"][0]["editor"]["valence"] == "grim" and row["grades"][0]["grades"] == 2


class TestTheSameMoments:
    """v12 (2-oct-2026): versions compared on the same moments; what fills the pictures, counted."""

    def _run(self, brain, job8, n, v, items, reviews=()):
        with open(brain / f"{job8}_clip{n}_{v}.json", "w", encoding="utf-8") as f:
            json.dump({"items": items, "reviews": list(reviews)}, f)

    def test_one_moment_per_sentence_or_second(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bench, "BRAIN_DIR", str(tmp_path))
        said_a = "He took his own life, he's a colleague physician friend of mine at Stanford"
        said_b = "He's a colleague physician friend of mine at Stanford and I know his wife"
        self._run(tmp_path, "j", 1, "v8", [{"t": 13.6, "anchor": "Ibogaine", "said": "nothing to do with Ibogaine whatsoever"},
                                           {"t": 18.5, "anchor": "Stanford", "said": said_b}])
        self._run(tmp_path, "j", 1, "v9", [{"t": 15.6, "anchor": "took his own life", "said": said_a},
                                           {"t": 29.1, "anchor": "Taekwondo.", "said": "a martial arts guy, Taekwondo"},
                                           {"t": 29.6, "anchor": "guy", "said": ""}])
        ms = bench.aligned_moments("j", 1, ["v8", "v9"])
        assert [(m["t"], m["anchor"]) for m in ms] == [(13.6, "Ibogaine"), (18.5, "Stanford"), (29.1, "Taekwondo.")]
        assert ms[1]["time"] == round(18.5 + 0.12, 2) and ms[1]["said"] == said_b      # the earliest version speaks
        assert bench.aligned_moments("j", 1, ["v99"]) == []

    def test_content_classifies_what_the_review_saw(self, tmp_path, monkeypatch):
        import argparse
        import ai_brain
        monkeypatch.setattr(bench, "BRAIN_DIR", str(tmp_path))
        self._run(tmp_path, "j", 1, "v8", [{"k": 0, "layout": "hero"}, {"k": 1, "layout": "card", "take": 2}],
                  [{"k": 0, "file": "broll_0.jpg", "seen": "an empty room"},
                   {"k": 1, "file": "broll_1.jpg", "seen": "take one"}, {"k": 1, "file": "broll_1_t2.jpg", "seen": "a vial on a tray"}])
        seen = {}

        def fake(prompt, schema, **kw):
            seen.update(prompt=prompt, **kw)
            return {"kinds": [{"id": "v8|j:1|0", "kind": "empty_place"}, {"id": "v8|j:1|1", "kind": "object_set_down"}]}

        monkeypatch.setattr(ai_brain, "claude_json", fake)
        bench.cmd_content(argparse.Namespace(jobs="j:1", versions="v8", name="t"))
        assert seen["model"] == "haiku" and "v8|j:1|1: a vial on a tray" in seen["prompt"]
        with open(tmp_path / "content_t.json", encoding="utf-8") as f:
            table = json.load(f)["table"]["v8"]
        assert table["all"] == {"empty_place": 1, "object_set_down": 1} and table["hero"] == {"empty_place": 1}
