"""B-roll « littéral » (9-oct-2026, broll_litteral): the concrete nouns said, each shown literally on its word — a scene
full screen, an object as a big card in the lower half, a 3D sequence with marks drawn by the code — from 0.8 s, one
every 3-5 s, 1-3 s each, 35-60 % of the clip off the face. No model, no GPU and no ffmpeg are called."""
import os

import pytest
from PIL import Image

import broll
import broll_draw
import broll_ideas
import broll_litteral as bl
import plus


def _words(text, step=0.4):
    return [{"text": w, "start": round(i * step, 2), "end": round(i * step + 0.35, 2)} for i, w in enumerate(text.split())]


TEXT = ("If you go to the emergency room at three in the morning, your first question for the on-call physician "
        "should be, how long have you been on call? You would not let that person drive your car home. "
        "They take melatonin pills every night and the pills sit in a bottle by the bed. The hospital is quiet "
        "and the nurse walks the corridor with a coffee in her hand while the clock ticks on the wall above.")
WORDS = _words(TEXT)
IDX = {w["text"].strip(".,?").lower(): i for i, w in reversed(list(enumerate(WORDS)))}


def _noun(word, key=None, fmt="scene", prio=2, picture=None, bg=""):
    return {"i": IDX[word], "word": word, "key": key or word, "format": fmt, "priority": prio,
            "picture": picture or f"a single {word}", "background": bg}


def test_the_recipe_runs_the_literal_chain_and_keeps_the_drawn_one():
    assert plus.BROLL["chain"] == "litteral"
    # the « dessin » chain keeps its own texts of 4-oct-2026
    text, suffix, banc = broll_draw.charter()
    assert broll_draw.CHARTER_FILE == "charte-dessin.md" and suffix.startswith("Editorial ink illustration")
    assert "Principes du directeur artistique" in banc
    assert "l'idée de la phrase" in broll_draw.principles()


def test_the_charter_gives_one_style_for_pictures_and_one_for_sequences():
    text, styles, method = bl.charter()
    assert styles["picture"].startswith("Photorealistic cinematic photograph") and "no writing" in styles["picture"]
    assert styles["sequence"].startswith("High-end 3D medical visualization")
    assert "noms concrets" in method and "Séquence" in text
    skill = broll_ideas.skill_text("principes")
    assert "montre la chose dite" in skill and "pas d'image" in skill


class TestSchedule:
    """The rules of the 12 OptimalHealth shorts decoded (output/_stepup/etude2/decodage/rapport.md § 4)."""

    def test_on_the_word_the_face_alone_for_3_s_but_one_card(self):
        nouns = [_noun("if"), _noun("emergency"), _noun("morning"), _noun("physician"),
                 _noun("go", fmt="object", bg="yellow"), _noun("room", fmt="object", bg="yellow")]
        picks = bl.schedule(nouns, WORDS, 60.0)
        full = [p for p in picks if p["format"] in bl.FULL]
        assert full and all(p["t"] >= bl.FULL_HEAD for p in full), "nothing full screen in the first 3 s"
        assert full[0]["key"] == "morning" and full[0]["t"] == round(WORDS[IDX["morning"]]["start"] - bl.LEAD, 2)
        early = [p for p in picks if p["t"] < bl.FULL_HEAD]
        assert len(early) == 1 and early[0]["format"] == "object"
        # an object card rises CARD_LEAD s before its word (it is settled on it), never before HEAD
        assert early[0]["t"] >= bl.HEAD and early[0]["t"] == round(WORDS[early[0]["i"]]["start"] - bl.CARD_LEAD, 2)

    def test_the_pace_of_the_references(self):
        nouns = [_noun(w) for w in ("morning", "physician", "car", "melatonin", "bottle", "bed",
                                     "hospital", "nurse", "corridor", "coffee", "clock", "wall")]
        total = WORDS[-1]["end"] + 1.5
        picks = bl.schedule(nouns, WORDS, total)
        assert len(picks) >= 4 and len(picks) <= bl.PER_MIN * total / 60 + 1
        for a, b in zip(picks, picks[1:]):
            assert b["t"] - a["t"] >= bl.STEP - 1e-6
            gap = b["t"] - (a["t"] + a["dur"])
            assert gap >= -1e-6 and (gap < 1e-6 or gap >= bl.JOIN - 1e-6), "picture to picture, or a real face"
        assert all(p["dur"] <= bl.DUR_MAX + bl.CARD_LEAD + 1e-6 for p in picks)
        assert bl.COVER_LO - 0.02 <= bl.coverage(picks, total) <= bl.COVER_HI + 1e-6
        assert picks[-1]["t"] + picks[-1]["dur"] <= total - bl.TAIL + 1e-6, "the clip ends on a face"

    def test_priority_wins_a_clash(self):
        picks = bl.schedule([_noun("morning", prio=1), _noun("your", prio=3)], WORDS, 60.0)
        assert [p["key"] for p in picks] == ["your"]

    def test_the_punchline_stays_on_the_face_and_the_tail_too(self):
        t_car = WORDS[IDX["car"]]["start"]
        picks = bl.schedule([_noun("car")], WORDS, 60.0, avoid=[t_car + 0.6])
        assert picks == []                                   # 0.4 s of room: no picture
        picks = bl.schedule([_noun("car")], WORDS, 60.0, avoid=[t_car + 1.5])
        assert picks and picks[0]["t"] + picks[0]["dur"] <= t_car + 1.5 - bl.PUNCH_CLEAR + 1e-6
        assert bl.schedule([_noun("clock")], WORDS, WORDS[IDX["clock"]]["start"] + 1.5) == []

    def test_a_key_said_again_comes_back(self):
        picks = bl.schedule([_noun("melatonin", key="pills"), _noun("bed", key="pills")], WORDS, 60.0)
        assert [p["key"] for p in picks] == ["pills", "pills"]

    def test_a_sequence_holds_its_figure_end_to_end(self):
        seq = {"key": "eyes", "figure": "a glowing blue holographic human head", "points": ["eye"],
               "steps": [{"i": IDX["hospital"], "word": "hospital", "marks": []},
                         {"i": IDX["nurse"], "word": "nurse", "marks": [{"kind": "glow", "at": "eye", "dir": ""}]},
                         {"i": IDX["corridor"], "word": "corridor", "marks": []}]}
        picks = bl.schedule([_noun("quiet"), _noun("coffee")], WORDS, 80.0, sequences=[seq])
        steps = [p for p in picks if p["format"] == "sequence"]
        assert [p["step"] for p in steps] == [0, 1, 2]
        for a, b in zip(steps, steps[1:]):
            assert abs(a["t"] + a["dur"] - b["t"]) < 1e-6        # no face between two steps
        assert not any(p["key"] == "quiet" for p in picks), "nothing else while the figure is up"


class TestDirector:
    def test_nouns_cleaned_one_picture_per_key(self):
        data = {"nouns": [{"i": IDX["melatonin"], "word": "melatonin", "key": "Melatonin bottle", "format": "object",
                           "picture": "a bottle of melatonin pills", "background": "sky blue", "priority": 3},
                          {"i": IDX["bottle"], "word": "bottle", "key": "melatonin bottle", "format": "scene",
                           "picture": "", "priority": 2},
                          {"i": 999, "word": "x", "key": "x", "format": "scene", "picture": "x", "priority": 1},
                          {"i": IDX["car"], "word": "car", "key": "car", "format": "scene", "picture": "", "priority": 1}]}
        got = bl.nouns_of(data, WORDS)
        assert [(n["key"], n["format"], n["background"]) for n in got] == [
            ("melatonin_bottle", "object", "sky blue"), ("melatonin_bottle", "object", "sky blue")]

    def test_a_sequence_needs_three_steps_on_its_points(self):
        steps = [{"i": IDX[w], "word": w, "marks": [{"kind": "arrow", "at": "eye", "dir": "in"},
                                                     {"kind": "arrow", "at": "nose", "dir": "up"}]}
                 for w in ("hospital", "nurse", "corridor")]
        got = bl.sequences_of({"sequences": [{"key": "eyes", "figure": "a head", "points": ["eye"], "steps": steps}]},
                              WORDS)
        assert len(got) == 1 and all(s["marks"] == [{"kind": "arrow", "at": "eye", "dir": "in"}] for s in got[0]["steps"])
        assert bl.sequences_of({"sequences": [{"key": "e", "figure": "a head", "points": ["eye"],
                                               "steps": steps[:2]}]}, WORDS) == []

    def test_the_style_sentence_heads_every_prompt(self):
        _t, styles, _m = bl.charter()
        obj = bl.picture_text(styles, {"picture": "a bottle of melatonin pills", "format": "object",
                                       "background": "sky blue"})
        assert obj.startswith(styles["picture"]) and "plain seamless sky blue background" in obj
        scene = bl.picture_text(styles, {"picture": "a tired doctor in scrubs in a corridor", "format": "scene"})
        assert scene.startswith(styles["picture"]) and scene.endswith(bl.DRESSED)
        seq = bl.picture_text(styles, {"picture": "a glowing blue holographic human head", "format": "sequence"})
        assert seq == f"{styles['sequence']} a glowing blue holographic human head."


class Calls:
    def __init__(self, nouns, sequences=(), refuse=()):
        self.nouns, self.sequences, self.refuse = nouns, list(sequences), set(refuse)

    def __call__(self, prompt, schema, stage, model, effort=None, timeout=None):
        if schema is bl.DA_SCHEMA:
            return {"nouns": self.nouns, "sequences": self.sequences}
        keys = [ln.split('"')[1] for ln in prompt.splitlines() if ln.startswith('key "')]
        return {"pictures": [{"key": k, "verdict": "refuse" if k in self.refuse else "pass", "reason": ""} for k in keys]}


@pytest.fixture
def add(monkeypatch, tmp_path):
    def go(nouns, sequences=(), refuse=(), points=None):
        made, cut = [], []

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), **kw):
            made.append((tuple(size), prompt))
            Image.new("RGB", size, (50, 80, 120)).save(out_path, quality=80)
            return out_path

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "local_image", fake_image)
        monkeypatch.setattr(broll, "overlay_items", lambda clip_, out, items, img_dir=None: cut.append(list(items)))
        monkeypatch.setattr(broll_ideas, "_call", Calls(nouns, sequences, refuse))
        monkeypatch.setattr(broll_draw, "dress_check", lambda path, tmp: (False, ""))
        monkeypatch.setattr(bl, "locate", lambda path, pts, tmp: points or {})
        monkeypatch.setenv("BROLL_TRACE", "0")
        monkeypatch.delenv("AUTO_HOOK", raising=False)
        keep = tmp_path / "job"
        keep.mkdir(exist_ok=True)
        tr = {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in WORDS]}]}
        clip = {"punchline_time": None, "video_title_for_youtube_short": "Ask your ER doctor this"}
        rep = broll.add_broll(str(keep / "c_clip_1.mp4"), str(tmp_path / "out.mp4"), clip, tr, 0.0, 80.0,
                              {**plus.BROLL, "enabled": True, "planner": "claude"}, keep_dir=str(keep),
                              keep_prefix="c_clip_1_")
        return rep, made, cut
    return go


def _row(word, key, fmt="scene", picture="", bg="", prio=2):
    return {"i": IDX[word], "word": word, "key": key, "format": fmt, "picture": picture, "background": bg,
            "priority": prio}


class TestAddBroll:
    def test_scene_full_screen_object_card_one_render_per_key(self, add):
        rep, made, cut = add([_row("physician", "er", picture="an emergency room at night"),
                              _row("melatonin", "pills", "object", "a bottle of melatonin pills", "sky blue"),
                              _row("bed", "pills"),
                              _row("corridor", "hall", picture="a quiet hospital corridor")])
        sizes = [s for s, _p in made]
        assert sorted(sizes) == sorted([broll.HERO_GEN["std"], broll.OBJECT_GEN, broll.HERO_GEN["std"]])
        items = rep["items"]
        assert [it["layout"] for it in items] == ["hero", "object", "object", "hero"]
        assert items[1]["image"] != items[2]["image"] and items[1]["size"] == broll.OBJECT_SIZE
        assert items[0]["t"] == round(WORDS[IDX["physician"]]["start"] - bl.LEAD, 2)
        assert cut and cut[0] == items
        assert not any(it.get("sfx") for it in items), "no whoosh (none measurable on the references)"

    def test_a_refused_key_is_never_made(self, add):
        rep, made, _cut = add([_row("physician", "er", picture="an emergency room"),
                               _row("car", "car", "object", "a car key", "yellow")], refuse=["m1"])
        assert len(made) == 1 and [it["anchor"] for it in rep["items"]] == ["physician"]

    def test_a_sequence_s_steps_carry_their_marks_end_to_end(self, add):
        steps = [{"i": IDX[w], "word": w, "marks": [{"kind": "circle", "at": "eye", "dir": "cw"}]}
                 for w in ("hospital", "nurse", "corridor")]
        rep, made, _cut = add([], [{"key": "eyes", "figure": "a glowing blue holographic human head",
                                    "points": ["eye"], "steps": steps}], points={"eye": (0.4, 0.45)})
        assert len(made) == 1 and made[0][1].startswith("High-end 3D medical visualization")
        seq = [it for it in rep["items"] if it.get("seq") == "eyes"]
        assert len(seq) == 3 and all(it["layout"] == "hero" for it in seq)
        assert seq[0]["marks"] == [{"kind": "circle", "dir": "cw", "x": 0.4, "y": 0.45}]
        for a, b in zip(seq, seq[1:]):
            assert abs(a["t"] + a["dur"] - b["t"]) < 1e-6


def test_the_object_card_and_the_marks_are_drawn(tmp_path):
    src = tmp_path / "o.jpg"
    Image.new("RGB", broll.OBJECT_GEN, (40, 120, 220)).save(src)
    folder = tmp_path / "f"
    folder.mkdir()
    pattern, x, y, _cvh = broll._object_frames(str(src), str(folder), 30, 1.0, 1080, 1920)
    frames = sorted(os.listdir(folder))
    assert len(frames) == 30
    im = Image.open(folder / frames[0])
    bx, by, bw, bh = broll.object_box(1080, 1920)
    assert abs(bw - 0.6 * 1080) < 2 and 0.5 * 1920 <= by and by + bh <= 0.97 * 1920
    assert all(abs(a - b) <= 3 for a, b in zip(im.getpixel((im.width // 2, im.height // 2))[:3], (40, 120, 220)))
    assert im.getpixel((2, 2))[3] == 0                                         # rounded corner: see-through
    layer = broll._draw_marks(1080, 1920, [{"kind": "arrow", "dir": "in", "px": 400, "py": 900},
                                           {"kind": "circle", "dir": "ccw", "px": 700, "py": 900},
                                           {"kind": "glow", "dir": "", "px": 540, "py": 1200}], 0.3)
    assert layer.getpixel((400, 900))[3] > 200 and layer.getpixel((540, 1200))[3] > 100
    assert layer.getpixel((50, 50))[3] == 0


def test_the_split_screen_fills_the_lower_half(tmp_path):
    src = tmp_path / "s.jpg"
    Image.new("RGB", broll.SPLIT_GEN, (200, 60, 60)).save(src)
    folder = tmp_path / "f"
    folder.mkdir()
    broll._split_frames(str(src), str(folder), 30, 0.5, 1080, 1920)
    frames = sorted(os.listdir(folder))
    assert len(frames) == 15 and Image.open(folder / frames[0]).size == (1080, 960)
    assert broll._gen_size("split") == broll.SPLIT_GEN and broll._gen_size("object") == broll.OBJECT_GEN


def test_a_split_picture_is_cut_in_as_such(add):
    rep, made, _cut = add([_row("melatonin", "pills", "split", "a heap of small white melatonin tablets")])
    (it,) = rep["items"]
    assert it["layout"] == "split" and made[0][0] == broll.SPLIT_GEN
    assert made[0][1].endswith(bl.SPLIT_LINE)


# --- the integration of the « références » recipe (9-oct-2026 evening): footage, animation, transitions, full cards ----

def _ffmpeg_colour(path, colour, seconds, size="216x384", audio=False):
    import subprocess
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={colour}:s={size}:r=30:d={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", "-c:a", "aac", "-shortest"]
    subprocess.run(cmd + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def test_the_director_s_footage_and_motion_are_kept_per_key():
    data = {"nouns": [
        {"i": 3, "word": "drive", "key": "driving", "format": "scene", "picture": "a tired man driving at night",
         "footage": "tired man driving at night", "motion": "pulse", "priority": 2},
        {"i": 5, "word": "nerve", "key": "nerve", "format": "inside", "picture": "a glowing nerve", "motion": "flow",
         "footage": "nerve", "priority": 2},
        {"i": 7, "word": "heart", "key": "heart", "format": "inside", "picture": "a heart", "motion": "none",
         "priority": 1},
        {"i": 9, "word": "bottle", "key": "bottle", "format": "object", "picture": "a bottle", "footage": "bottle",
         "priority": 1},
        {"i": 11, "word": "driving", "key": "driving", "format": "scene", "picture": "", "footage": "", "priority": 1}]}
    by = {}
    for n in bl.nouns_of(data, WORDS):
        by.setdefault(n["key"], []).append(n)
    assert by["driving"][0]["footage"] == "tired man driving at night" and by["driving"][0]["motion"] == ""
    assert by["driving"][1]["footage"] == "tired man driving at night", "a key said again keeps its footage"
    assert by["nerve"][0]["motion"] == "flow" and by["nerve"][0]["footage"] == ""
    assert by["heart"][0]["motion"] == "", "an organ that must move stays a still"
    assert by["bottle"][0]["footage"] == ""
    assert '"footage"' in bl.DA_PROMPT and '"motion"' in bl.DA_PROMPT
    assert set(bl.DA_SCHEMA["properties"]["nouns"]["items"]["properties"]) >= {"footage", "motion"}


def test_41_percent_of_the_pictures_come_in_with_a_transition():
    picks = [{"format": "scene" if k % 3 else "object", "t": k * 2.0} for k in range(100)]
    enters = bl.transitions(picks)
    assert 40 <= sum(1 for e in enters if e) <= 42
    assert all(e in ("", "flash") for p, e in zip(picks, enters) if p["format"] == "scene")
    assert all(e in ("", "blur") for p, e in zip(picks, enters) if p["format"] == "object")
    seq = [{"format": "sequence", "step": s, "t": 10 + s} for s in range(4)]
    assert all(e == "" for e in bl.transitions([{"format": "scene"}] * 7 + seq)[8:]), "the same figure: no transition"


def test_an_object_fills_its_card_and_its_label_is_blank(tmp_path):
    import numpy as np
    from PIL import ImageDraw
    p = tmp_path / "vial.jpg"
    im = Image.new("RGB", broll.OBJECT_GEN, (70, 175, 220))
    ImageDraw.Draw(im).rectangle((470, 260, 560, 480), fill=(235, 235, 240))      # a small vial: 29 % of the height
    im.save(p, quality=95)
    z = bl.fill_object(str(p))
    assert z > 2.0
    out = Image.open(p)
    assert out.size == broll.OBJECT_GEN
    x0, y0, x1, y1 = bl.object_bbox(str(p))
    assert 0.62 <= (y1 - y0) / out.height <= 0.78
    # a picture without a plain background is left alone
    noisy = tmp_path / "scene.jpg"
    Image.fromarray(np.random.default_rng(1).integers(0, 255, (768, 1024, 3), dtype=np.uint8)).save(noisy)
    assert bl.fill_object(str(noisy)) == 1.0
    _t, styles, _m = bl.charter()
    obj = bl.picture_text(styles, {"picture": "a single vial of lidocaine", "format": "object", "background": "blue"})
    assert "no writing" in obj.split(styles["picture"])[1] and "three quarters of the frame" in obj


def test_footage_and_an_animated_render_are_cut_in_with_their_credit(add, monkeypatch, tmp_path):
    import broll_animate
    import broll_video
    asked = {}

    def fake_videos(moments, words, clip_end, tmp, cfg=None, session=None, fps=30, gap=None):
        asked["moments"], asked["gap"], asked["cfg"] = moments, gap, cfg
        out = []
        for m in moments:
            path = _ffmpeg_colour(tmp_path / f"v_{m['key']}.mp4", "green", m["dur"])
            out.append({"t": m["t"], "dur": m["dur"], "path": path, "word": m["word"], "query": m["query"],
                        "credit": {"author": "Jane Doe", "license": broll_video.LICENSE}, "kind": "video",
                        "key": m["key"]})
        return out

    def fake_animate(image_path, motion, out_path, *, scene="", seconds=2.5, **kw):
        asked["animate"] = (motion, seconds)
        _ffmpeg_colour(out_path, "blue", seconds)
        return {"path": str(out_path), "seconds": seconds, "gpu_s": 31.0}

    monkeypatch.setattr(broll_video, "videos_for_clip", fake_videos)
    monkeypatch.setattr(broll_animate, "animate", fake_animate)
    rep, made, _cut = add([
        {**_row("physician", "driving", picture="a tired doctor driving home at night"),
         "footage": "tired doctor driving at night"},
        {**_row("melatonin", "nerve", "inside", "a glowing nerve fibre, whole and clean"), "motion": "pulse"},
        _row("corridor", "hall", picture="a quiet hospital corridor")])
    assert asked["gap"] == 0.0 and asked["cfg"]["video"] is True
    assert [m["key"] for m in asked["moments"]] == ["driving"] and asked["moments"][0]["query"].startswith("tired")
    assert asked["animate"][0] == bl.MOTIONS["pulse"] and asked["animate"][1] <= bl.ANIMATE_MAX_S
    # the footage is not made by ComfyUI: two renders (the nerve, the corridor)
    assert len(made) == 2
    items = {it["anchor"]: it for it in rep["items"]}
    assert items["physician"]["video_kind"] == "pexels" and items["physician"]["video"].endswith(".mp4")
    assert items["melatonin"]["video_kind"] == "animate" and items["melatonin"]["video"].endswith(".mp4")
    assert "video" not in items["corridor"]
    assert rep["credits"] and rep["credits"][0]["author"] == "Jane Doe"
    assert all(it.get("transition", "") in ("", "flash", "blur") for it in rep["items"])
    assert bl.LAST_COST["videos"] == 1 and bl.LAST_COST["animated"] == 1 and bl.LAST_COST["animate_gpu_s"] == 31.0


def test_a_video_comes_out_of_a_flash_and_a_still_too(tmp_path):
    import subprocess
    clip = _ffmpeg_colour(tmp_path / "clip.mp4", "red", 2.0, audio=True)
    vid = _ffmpeg_colour(tmp_path / "v.mp4", "0x0000C0", 1.0)
    still = tmp_path / "s.jpg"
    Image.new("RGB", (216, 384), (0, 160, 0)).save(still)
    out = tmp_path / "out.mp4"
    broll.overlay_items(clip, str(out), [
        {"t": 0.5, "dur": 0.8, "layout": "hero", "_video": vid, "transition": "flash"},
        {"t": 1.4, "dur": 0.5, "layout": "hero", "_img": str(still), "transition": "flash"}])

    def at(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(out), "-frames:v", "1", "-vf",
                              "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True,
                             check=True).stdout
        return tuple(raw[:3])
    assert at(0.2)[0] > 180 and at(0.2)[2] < 80                     # the face (red)
    assert min(at(0.52)) > 150                                       # the flash: near white
    assert at(1.0)[2] > 150 and at(1.0)[0] < 60                      # the footage (blue)
    assert at(1.75)[1] > 100 and at(1.75)[0] < 90                    # the still (green), after its flash
    assert broll._media_seconds(str(out)) >= 1.9
