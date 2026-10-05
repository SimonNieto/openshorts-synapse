"""Step up of 5-oct-2026 (lot L2 « dessins »), validated by the user:
  - decision 5: in the « dessin » chain every drawing is made 9:16 and shown alone, full screen, 2.0-2.5 s, a hard cut in
    and out, never as a card on the speaker's head (the source's own picture stays a card); a vertical render that fails
    gives the old card; a drawing never covers the punchline;
  - decision 3: the whoosh on the first drawing of the clip only;
  - decision 8: the opening drawing (0-1.2 s, under the hook), behind plus.BROLL["opening"], OFF.
No model and no GPU are called: the director, the verifier, the image model and ffmpeg are faked."""
import os
import shutil
import subprocess
import tempfile

import pytest
from PIL import Image

import broll
import broll_draw
import broll_ideas
import broll_spec
import broll_v20
import plus

TEXT = ("Well you know this is the setup for the story. In 1998 the soldiers were given two gallons of water, "
        "and then they marched all night long. It was brutal. Nobody spoke for hours but the drill went on and on "
        "until sunrise came and the camp woke up again and the sergeant finally smiled at them all. They never "
        "forgot that long night in the desert and the lesson it taught them about discipline.")


def _transcript(text, step=0.42):
    words, t = [], 0.0
    for w in text.split():
        words.append({"word": " " + w, "start": round(t, 2), "end": round(t + 0.4, 2)})
        t += step
    return {"segments": [{"words": words}]}


def _moment(t, anchor="soldiers", hero=False, gravity="none", death_near=False, dur=2.4):
    spec = {"kind": "scene", "subject": f"the {anchor}", "people": "one", "mood": {"gravity": "none"}, "hero": hero,
            "death_near": death_near}
    return {"t": t, "anchor": anchor, "said": f"they talked about {anchor}", "dur": dur, "hero": hero, "spec": spec,
            "mood": {"x": 1}, "clip_gravity": gravity}


class Calls:
    """The art director and the verifier, faked (one picture per moment, all pass unless said)."""

    def __init__(self, pictures, verdicts=None):
        self.pictures, self.verdicts = pictures, verdicts or ["pass"] * len(pictures)

    def __call__(self, prompt, schema, stage, model, effort=None, timeout=None):
        if schema is broll_draw.DA_SCHEMA:
            return {"moments": [{"k": k, "idea": f"idea {p}", "picture": p} for k, p in enumerate(self.pictures)]}
        return {"moments": [{"k": k, "verdict": v, "reason": ""} for k, v in enumerate(self.verdicts)]}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.delenv("AUTO_HOOK", raising=False)
    monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)
    monkeypatch.setenv("BROLL_TRACE", "0")


@pytest.fixture
def run(monkeypatch, tmp_path):
    """add_broll on the « dessin » chain with everything around it faked. Returns (report, sizes asked, items cut in,
    keep_dir)."""
    def go(moments, pictures, cfg=None, clip=None, fail_hero=False, verdicts=None, screen=None):
        made, cut = [], []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), **kw):
            made.append(tuple(size))
            if fail_hero and tuple(size) == broll.HERO_GEN["std"]:
                raise RuntimeError("out of memory")
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            return out_path

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "local_image", fake_image)
        monkeypatch.setattr(broll, "overlay_items", lambda clip_, out, items, img_dir=None: cut.append(list(items)))
        monkeypatch.setattr(broll_spec, "plan_specs", lambda *a, **kw: ([dict(m) for m in moments], []))
        monkeypatch.setattr(broll_ideas, "_call", Calls(pictures, verdicts))
        monkeypatch.setattr(broll_v20, "trace", lambda *a, **kw: None)
        keep = tmp_path / "job"
        keep.mkdir(exist_ok=True)
        c = {"punchline_time": None, "viral_hook_text": "Soldiers marched all night",
             "video_title_for_youtube_short": "Can you march all night?", **(clip or {})}
        if screen:
            Image.new("RGB", (640, 360), (200, 200, 200)).save(keep / "screen.jpg")
            c["screen_inset"] = {**screen, "image": "screen.jpg"}
        tr = _transcript(TEXT)
        conf = {**plus.BROLL, "enabled": True, "planner": "claude", **(cfg or {})}
        rep = broll.add_broll(str(keep / "c_clip_1.mp4"), str(tmp_path / "out.mp4"), c, tr, 0.0, 40.0, conf,
                              keep_dir=str(keep), keep_prefix="c_clip_1_")
        return rep, made, cut, keep
    return go


def test_the_recipe_draws_full_width_with_the_opening_off():
    assert plus.BROLL["chain"] == "dessin" and plus.BROLL["full_width"] is True
    assert plus.BROLL["sfx"] is True


class TestFullWidth:
    def test_every_drawing_is_made_9_16_and_shown_alone_2_to_2_5_s(self, run):
        rep, made, cut, _keep = run([_moment(6.0, "soldiers"), _moment(12.0, "drill", hero=True), _moment(20.0, "sergeant")],
                                    ["A.", "B.", "C."])
        assert made == [broll.HERO_GEN["std"]] * 3
        items = rep["items"]
        assert [it["layout"] for it in items] == ["hero"] * 3
        assert all(broll.HERO_DUR_MIN <= it["dur"] <= broll.HERO_DUR_MAX for it in items)
        assert all(it["gen"] == list(broll.HERO_GEN["std"]) for it in items)
        assert not any("size" in it or "position" in it for it in items), "no card geometry: nothing on the head"
        assert all(it["t"] >= broll.HEAD_FREE for it in items), "the hook's seconds stay on the face"
        assert cut and cut[0] == items

    def test_the_whoosh_marks_the_first_drawing_only(self, run):
        rep, _made, _cut, _keep = run([_moment(6.0, "soldiers"), _moment(12.0, "drill"), _moment(20.0, "sergeant")],
                                      ["A.", "B.", "C."])
        assert [bool(it.get("sfx")) for it in rep["items"]] == [True, False, False]
        rep, *_ = run([_moment(6.0, "soldiers"), _moment(12.0, "drill")], ["A.", "B."], cfg={"sfx": False})
        assert not any(it.get("sfx") for it in rep["items"])

    def test_a_failed_vertical_render_gives_the_old_card(self, run):
        rep, made, _cut, _keep = run([_moment(6.0, "soldiers")], ["A."], fail_hero=True)
        assert made == [broll.HERO_GEN["std"]] * 2 + [broll.CARD_GEN]      # two tries in 9:16, then the card
        (it,) = rep["items"]
        assert it["layout"] == "card" and it["gen"] == list(broll.CARD_GEN) and it["size"] == broll.CARD_SIZE
        assert not it.get("sfx"), "the whoosh marks a full-screen drawing"

    def test_a_drawing_never_covers_the_punchline(self, run):
        # 13.5 s: the drawing at 12.0 would be up until 14.4 — it leaves at 13.3 (1.3 s: no room, not even made)
        rep, made, _cut, _keep = run([_moment(6.0, "soldiers"), _moment(12.0, "drill")], ["A.", "B."],
                                     clip={"punchline_time": 13.5})
        assert len(made) == 1 and [it["anchor"] for it in rep["items"]] == ["soldiers"]
        # 8.3 s: the one at 6.0 (2.4 s) leaves 0.2 s before it, after 2.1 s — still room
        rep, *_ = run([_moment(6.0, "soldiers")], ["A."], clip={"punchline_time": 8.3})
        assert rep["items"][0]["dur"] == 2.1
        assert broll.full_dur({"t": 6.0, "dur": 2.4}, [8.3]) == 2.1 and broll.full_room({"t": 6.0, "dur": 2.4}, [8.3])
        assert not broll.full_room({"t": 12.0, "dur": 2.4}, [13.5])

    def test_the_source_s_own_picture_stays_a_card(self, run):
        rep, *_ = run([_moment(14.0, "drill")], ["A."], screen={"t0": 6.0, "t1": 9.0})
        by = {it["anchor"]: it for it in rep["items"]}
        assert by["on screen"]["layout"] == "card" and by["drill"]["layout"] == "hero"

    def test_without_full_width_the_chain_keeps_its_hero_and_cards(self, run):
        rep, made, *_ = run([_moment(6.0, "soldiers"), _moment(12.0, "drill", hero=True)], ["A.", "B."],
                            cfg={"full_width": False})
        assert sorted(made) == sorted([broll.CARD_GEN, broll.HERO_GEN["std"]])
        assert [it["layout"] for it in rep["items"]] == ["card", "hero"]


class TestDrawRun:
    """broll_draw.run itself in full width: the same prompts, every render in the hero's shape."""

    def test_every_render_is_full_screen_with_the_same_prompt(self, monkeypatch, tmp_path):
        monkeypatch.setattr(broll_ideas, "_call", Calls(["A fridge.", "A dish."]))
        monkeypatch.setattr(broll, "_frame_sheets", lambda path, tmp: [])
        monkeypatch.setattr(broll_spec, "plan_specs", lambda *a, **kw: ([_moment(6.0, hero=True), _moment(12.0)], []))
        monkeypatch.setattr(broll_v20, "trace", lambda *a, **kw: None)
        made = []

        def render(text, out, layout):
            made.append((text, layout))
            open(out, "wb").write(b"jpg")
            return out, 1
        words = [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(TEXT.split())]
        cands, _m = broll_draw.run(str(tmp_path / "c.mp4"), {}, words, None, 0, 50, 4, [], 4.3, 2.0, 4.0, (), None,
                                   str(tmp_path), render, full=True)
        _text, suffix, _banc = broll_draw.charter()
        assert made == [(f"{suffix} A fridge.", "hero"), (f"{suffix} A dish.", "hero")]
        assert [c["layout"] for c in cands] == ["hero", "hero"]
        assert broll_v20._layout({"hero": False}, True) == "hero" and broll_v20._layout({"hero": False}) == "card"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_the_real_mix_is_normalised_48k_and_under_minus_1_dbtp(tmp_path):
    """The whoosh mixed by ffmpeg for real: the graph runs, the sound comes out at 48 kHz, true peak <= -1 dBTP."""
    clip = str(tmp_path / "c.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=108x192:r=10:d=4",
                    "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:d=4", "-af", "volume=-12dB",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", clip], check=True)
    img = str(tmp_path / "h.jpg")
    Image.new("RGB", (224, 400), (90, 60, 30)).save(img)
    out = str(tmp_path / "o.mp4")
    broll.overlay_items(clip, out, [{"t": 1.5, "dur": 2.0, "layout": "hero", "_img": img, "sfx": True}])
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=sample_rate",
                            "-of", "csv=p=0", out], capture_output=True, text=True, check=True).stdout.strip()
    assert probe == "48000"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", out, "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    peak = float(r.stderr.rsplit("Peak:", 1)[1].split("dBFS")[0])
    assert peak <= -1.0
    lo, hi = broll.SFX_GAIN_RANGE
    assert lo <= broll.sfx_gain(clip, 1.5) <= hi and broll._rms_db(clip, 1.0, 1.0) is not None   # read on the real sound
