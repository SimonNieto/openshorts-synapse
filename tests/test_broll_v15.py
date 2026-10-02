"""B-roll « ambiance » v15 (2-oct-2026): the review and the redos — a redo is in the positive (its negations taken
out), another idea after two failures or for an unsafe picture, the judge asks only what a still picture can show,
and what the image model cannot draw (a doubled presence, a tremble) is added at the edit (fx). No model."""
import os
import tempfile

import numpy as np
import pytest
from PIL import Image

import broll


@pytest.fixture(autouse=True)
def _clear():
    broll.FILTERS.clear()
    yield
    broll.FILTERS.clear()


class TestPositiveRedos:
    def test_a_negation_is_taken_out_with_its_sentence(self):
        text = ("A man sits on the edge of his bed. The window is not visible. Warm lamp light from the left. "
                "Nothing behind him. He looks down at his hands.")
        assert broll.positive(text) == "A man sits on the edge of his bed. Warm lamp light from the left. He looks down at his hands."
        assert broll.FILTERS["redo: negation taken out"] == 1
        assert broll.positive("Notebook on a desk, a knotted rope of wool.") == "Notebook on a desk, a knotted rope of wool."
        assert broll.positive("") == "" and broll.positive("No window.") == ""

    def test_the_review_writes_both_prompts_in_the_positive(self):
        text = broll.REVIEW_PROMPT
        assert '"better_prompt": the same idea, made to work — the scene rewritten IN THE POSITIVE' in text
        assert '"new_prompt": a DIFFERENT picture for the same words' in text
        assert "new_prompt" in broll.REVIEW_SCHEMA["properties"]["reviews"]["items"]["properties"]
        # v15b: both are always asked for (the review left the other idea out 9 times in 11 when it was optional)
        assert {"better_prompt", "new_prompt"} <= set(broll.REVIEW_SCHEMA["properties"]["reviews"]["items"]["required"])
        c = broll._take_review({"layout": "card"}, {"score": 2, "look": 3, "better_prompt": "A room. Not behind a window.",
                                                    "new_prompt": "A crowded street at noon."})
        assert c["better_prompt"] == "A room." and c["new_prompt"] == "A crowded street at noon."

    def test_after_two_failures_another_idea(self):
        c = {"score": 2, "look_score": 3, "layout": "card", "better_prompt": "Same, closer.", "new_prompt": "Another.", "failed": 1}
        assert broll._next_prompt(c) == "Same, closer."
        c["failed"] = 2
        assert broll._next_prompt(c) == "Another."
        c["new_prompt"] = ""
        assert broll._next_prompt(c) is None

    def test_nothing_left_of_the_idea_another_one_never_twice_the_same(self):
        """v15b: a better prompt emptied by its negations gives way to the other idea; a prompt tried is not again."""
        c = {"score": 2, "look_score": 3, "layout": "card", "better_prompt": "", "new_prompt": "Another.", "failed": 1}
        assert broll._next_prompt(c) == "Another."
        c["tried"] = ["Another."]
        assert broll._next_prompt(c) is None
        c.update(better_prompt="Same, closer.", tried=["Same, closer."], failed=2)
        assert broll._next_prompt(c) == "Another."


class TestStillOnly:
    def test_the_review_and_the_judge_lines_ask_what_a_still_shows(self):
        assert "JUDGE WHAT A STILL PICTURE CAN SHOW" in broll.REVIEW_PROMPT
        assert "nor because a precise prop is missing" in broll.REVIEW_PROMPT
        assert "a person asleep when he was awake" in broll.REVIEW_PROMPT          # a false fact stays false
        art = broll._art_prompt([{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s"}], {})
        assert "only what a STILL picture can show: never a name\nor a label, a motion" in art


class TestFx:
    def test_the_director_asks_for_it_and_the_item_keeps_it(self):
        assert broll.ART_SCHEMA["properties"]["prompts"]["items"]["properties"]["fx"]["enum"] == ["none", "double", "tremble"]
        art = broll._art_prompt([{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s"}], {})
        assert '"fx": "none", or what the edit adds' in art and "paints ONE sharp, single image" in art
        long = ("word " * 60).strip()
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s"}, {"t": 9.0, "anchor": "b", "prompt": "q", "subject": "t"}]
        broll._apply_art(ms, {"prompts": [{"k": 0, "prompt": long, "fx": "double"}, {"k": 1, "prompt": long, "fx": "spin"}]})
        assert ms[0]["fx"] == "double" and ms[1]["fx"] is None
        lines = broll._review_lines([{"file": "/x/broll_0.jpg", "layout": "card", "m": {**ms[0], "said": "x"}}], [])
        assert "fx: double (added at the edit, not in this still)" in lines[0]

    def _src(self):
        tmp = tempfile.mkdtemp(prefix="fx_")
        src = os.path.join(tmp, "s.jpg")
        y, x = np.mgrid[0:800, 0:448]
        arr = np.stack([(x * 7) % 256, (y * 3) % 256, ((x + y) * 5) % 256], -1).astype(np.uint8)
        Image.fromarray(arr, "RGB").save(src, quality=95)
        return tmp, src

    def test_double_and_tremble_change_the_hero_frames(self):
        tmp, src = self._src()
        outs = {}
        for fx in (None, "double", "tremble"):
            f = os.path.join(tmp, f"h_{fx}")
            os.makedirs(f)
            broll._hero_frames(src, f, 10, 1.0, 108, 192, fx=fx)
            outs[fx] = [np.asarray(Image.open(os.path.join(f, f"c{i:03d}.png")).convert("RGB"), dtype=float) for i in (3, 4)]
        assert np.abs(outs["double"][0] - outs[None][0]).mean() > 3          # the copy shows
        assert np.abs(outs["tremble"][0] - outs[None][0]).mean() > 3
        # the tremble moves from a frame to the next more than the plain push-in does
        assert np.abs(outs["tremble"][1] - outs["tremble"][0]).mean() > np.abs(outs[None][1] - outs[None][0]).mean()

    def test_the_card_gets_it_too(self):
        tmp, src = self._src()
        frames = {}
        for fx in (None, "double"):
            f = os.path.join(tmp, f"c_{fx}")
            os.makedirs(f)
            broll._rise_frames(src, f, 10, 1.0, 540, 960, 60, "top", look="premium", border="premium", fx=fx)
            frames[fx] = np.asarray(Image.open(os.path.join(f, "c005.png")).convert("RGB"), dtype=float)
        assert np.abs(frames["double"] - frames[None]).mean() > 1

    def test_the_bench_previews_an_fx(self, tmp_path, monkeypatch):
        import broll_bench as bench
        monkeypatch.setattr(bench, "BRAIN_DIR", str(tmp_path))
        _tmp, src = self._src()
        res = {"images_dir": os.path.dirname(src), "items": [{"k": 0, "image": "s.jpg", "fx": "tremble"}, {"k": 1, "image": "s.jpg"}]}
        out = bench._fx_previews(res, "j_clip1_v15")
        assert [os.path.basename(p) for p in out] == ["j_clip1_v15_fx0.gif"]
        assert Image.open(out[0]).n_frames > 10
