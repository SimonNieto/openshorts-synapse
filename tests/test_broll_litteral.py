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
    assert styles["picture"].startswith("Photorealistic cinematic image") and "blank" in styles["picture"]
    assert styles["sequence"].startswith("High-end 3D medical visualization")
    assert "noms concrets" in method and "Séquence" in text
    skill = broll_ideas.skill_text("principes")
    assert "montre la chose dite" in skill and "pas d'image" in skill


class TestSchedule:
    def test_on_the_word_never_before_0_8_s(self):
        nouns = [_noun("if"), _noun("emergency"), _noun("physician")]
        picks = bl.schedule(nouns, WORDS, 60.0)
        assert picks[0]["key"] == "emergency" and picks[0]["t"] == WORDS[IDX["emergency"]]["start"]
        assert all(p["t"] >= bl.HEAD for p in picks)

    def test_three_seconds_between_starts_and_face_between(self):
        nouns = [_noun(w) for w in ("emergency", "room", "morning", "physician", "car", "melatonin", "bottle", "bed",
                                     "hospital", "nurse", "corridor", "coffee", "clock", "wall")]
        picks = bl.schedule(nouns, WORDS, WORDS[-1]["end"] + 1.5)
        assert len(picks) >= 5
        for a, b in zip(picks, picks[1:]):
            assert b["t"] - a["t"] >= bl.GAP_MIN - 1e-6
            assert b["t"] - (a["t"] + a["dur"]) >= bl.FACE_MIN - 1e-6
        assert all(bl.DUR_MIN <= p["dur"] <= bl.DUR_MAX for p in picks)
        cover = bl.coverage(picks, WORDS[-1]["end"] + 1.5)
        assert bl.COVER_LO - 0.02 <= cover <= bl.COVER_HI + 0.02, cover

    def test_priority_wins_a_clash(self):
        picks = bl.schedule([_noun("room", prio=1), _noun("morning", prio=3)], WORDS, 60.0)
        assert [p["key"] for p in picks] == ["morning"]

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
        rep, made, cut = add([_row("emergency", "er", picture="an emergency room at night"),
                              _row("melatonin", "pills", "object", "a bottle of melatonin pills", "sky blue"),
                              _row("bed", "pills"),
                              _row("corridor", "hall", picture="a quiet hospital corridor")])
        sizes = [s for s, _p in made]
        assert sorted(sizes) == sorted([broll.HERO_GEN["std"], broll.OBJECT_GEN, broll.HERO_GEN["std"]])
        items = rep["items"]
        assert [it["layout"] for it in items] == ["hero", "object", "object", "hero"]
        assert items[1]["image"] != items[2]["image"] and items[1]["size"] == broll.OBJECT_SIZE
        assert items[0]["t"] == WORDS[IDX["emergency"]]["start"]
        assert cut and cut[0] == items

    def test_a_refused_key_is_never_made(self, add):
        rep, made, _cut = add([_row("emergency", "er", picture="an emergency room"),
                               _row("car", "car", "object", "a car key", "yellow")], refuse=["car"])
        assert len(made) == 1 and [it["anchor"] for it in rep["items"]] == ["emergency"]

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
    pattern, x, y = broll._object_frames(str(src), str(folder), 30, 1.0, 1080, 1920)
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
