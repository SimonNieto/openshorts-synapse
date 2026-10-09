"""The smart zooms (zooms.py, plus.FX["zoom_style"] = "references", 9-oct-2026)."""
import json

import numpy as np

import plus
import zooms


def _words(text, start=0.0, step=0.3, pause_after=()):
    out, t = [], start
    for k, tok in enumerate(text.split()):
        out.append({"text": tok, "start": round(t, 3), "end": round(t + step - 0.02, 3)})
        t += step + (0.5 if k in pause_after else 0.0)
    return out


def _flat(words, db=-20.0, hz=120.0):
    return [(db, hz) for _ in words]


LINE = ("so the thing is that when you go to the hospital at night the doctor has been awake for "
        "thirty hours and they might as well be drunk. And nobody tells you that when you walk in there "
        "so you should ask them how long they have been on call because it changes everything")


class TestPlan:
    def test_no_strong_moment_no_punch_but_the_relaunch(self):
        w = _words("so the thing is that when you go there and they say that it is what it is "
                   "and then you go back home and you sit there and you think about it for a while")
        assert zooms.plan(6.0, w[:18], _flat(w[:18])) == []
        sw = zooms.plan(w[-1]["end"] + 1, w, _flat(w))
        assert [s["why"] for s in sw if s["to"] == "tight"] == ["relance"]

    def test_a_number_and_a_shock_word_get_a_punch_on_their_first_letter(self):
        w = _words(LINE, pause_after=(19,))
        sw = zooms.plan(w[-1]["end"] + 1, w, _flat(w))
        ins = [s for s in sw if s["to"] == "tight"]
        assert ins and ins[0]["word"] == "thirty" and "chiffre" in ins[0]["why"]
        starts = {w_["start"] for w_ in w}
        assert all(s["t"] in starts for s in sw if not s.get("hidden"))       # never inside a word

    def test_never_two_dry_cuts_within_the_gap(self):
        w = _words(LINE, pause_after=(19,))
        sw = [s for s in zooms.plan(w[-1]["end"] + 1, w, _flat(w)) if not s.get("hidden")]
        assert all(b["t"] - a["t"] >= zooms.MIN_GAP - 1e-6 for a, b in zip(sw, sw[1:]))
        # alternating: in, out, in, out
        assert all(s["to"] == ("tight" if k % 2 == 0 else "wide") for k, s in enumerate(sw))

    def test_back_wide_on_a_new_sentence_after_a_pause(self):
        w = _words(LINE, step=0.25)              # "thirty" at 4.75 s, "drunk. And" at 7.25 s
        sw = zooms.plan(w[-1]["end"] + 1, w, _flat(w))
        outs = [s for s in sw if s["to"] == "wide"]
        assert outs and outs[0]["why"] == "nouvelle phrase" and outs[0]["word"] == "And"

    def test_a_word_said_louder_is_a_moment(self):
        w = _words("we looked at the data and the effect was enormous across every single group we studied")
        pros = _flat(w)
        k = [x["text"] for x in w].index("effect")
        pros[k] = (-10.0, 120.0)
        ms = zooms.moments(w, pros)
        assert any(m["word"] == "effect" and "appuyé" in m["why"] for m in ms)
        pros[k] = (-20.0, 160.0)
        assert any(m["word"] == "effect" and "voix" in m["why"] for m in zooms.moments(w, pros))

    def test_the_punchline_wins(self):
        w = _words(LINE, pause_after=(19,))
        k = [x["text"] for x in w].index("ask")
        sw = zooms.plan(w[-1]["end"] + 1, w, _flat(w), punch=(w[k]["start"], w[-1]["end"]))
        assert any(s["to"] == "tight" and s["why"].startswith("chute") and s["word"] == "ask" for s in sw)

    def test_a_join_to_hide_gets_its_switch_on_its_very_time(self):
        w = _words("so the thing is that when you go there and they say that it is what it is", step=0.4)
        sw = zooms.plan(8.0, w, _flat(w), joins=[w[6]["start"]])
        assert [s["t"] for s in sw if s["why"] == "raccord caché"] == [w[6]["start"]]

    def test_no_punch_under_a_picture_and_wide_before_it(self):
        w = _words(LINE, pause_after=(19,))
        k = [x["text"] for x in w].index("thirty")
        pic = (w[k]["start"] - 0.5, w[k]["start"] + 2.0)
        sw = zooms.plan(w[-1]["end"] + 1, w, _flat(w), pictures=[pic])
        assert not any(s["to"] == "tight" and pic[0] - zooms.TIGHT_MIN <= s["t"] < pic[1] for s in sw)

    def test_a_camera_cut_brings_the_frame_back_wide_without_a_cut_of_ours(self):
        w = _words(LINE, pause_after=(19,))
        k = [x["text"] for x in w].index("thirty")
        cut = w[k]["start"] + 1.0
        sw = zooms.plan(w[-1]["end"] + 1, w, _flat(w), cuts=[cut])
        assert {"t": round(cut, 3), "to": "wide", "why": "coupe caméra", "word": "", "hidden": True} in sw
        assert not any(abs(s["t"] - cut) < zooms.CUT_GAP and not s.get("hidden") for s in sw)


    def test_never_long_without_a_change(self):
        w = _words("we sat there and we waited for them. then we talked about the weather and the trip home. "
                   "and after that we went back inside to sit down and we talked a bit more about the trip", step=0.3)
        end = w[-1]["end"] + 1
        sw = zooms.plan(end, w, _flat(w))
        times = [0.0] + [s["t"] for s in sw]
        assert sw and max(b - a for a, b in zip(times, times[1:])) <= zooms.RELAUNCH + 1.5
        assert all(not w[[x["start"] for x in w].index(s["t"])]["text"].endswith(".") for s in sw if s["to"] == "tight")

    def test_the_last_sentence_is_said_wide(self):
        w = _words(LINE, step=0.25)
        k = [x["text"] for x in w].index("because")
        w[k - 1]["text"] += "."
        sw = zooms.plan(w[-1]["end"] + 0.5, w, _flat(w))
        assert not any(s["to"] == "tight" and s["t"] >= w[k]["start"] - zooms.TIGHT_MIN for s in sw)

    def test_the_slow_push_starts_over_after_a_picture(self):
        _, start = zooms.frame_states(150, 30.0, [], restarts=[3.0])
        assert start[89] == 0 and start[90] == 90
        # a switch and a restart on the same frame (a silence cut as a picture ends)
        tight, start = zooms.frame_states(150, 30.0, [{"t": 3.0, "to": "tight"}], restarts=[3.0])
        assert tight[90] and start[90] == 90


    def test_the_frame_switches_on_the_silence_cuts_in_turn(self):
        w = _words(LINE, step=0.25)
        sil = [w[6]["start"], w[13]["start"], w[24]["start"], w[25]["start"]]     # the last one too close
        every = [s for s in zooms.plan(w[-1]["end"] + 1, w, _flat(w), silences=sil) if not s.get("hidden")]
        assert [s["t"] for s in every if s["why"] == "coupe de silence"] == sil[:3]
        assert all(s["to"] == ("tight" if k % 2 == 0 else "wide") for k, s in enumerate(every))   # in turn

    def test_a_join_to_hide_needs_only_the_gap(self):
        assert zooms.hide_spacing([0.5, 2.0, 2.6, 4.0, 6.0, 9.7], 10.0, cuts=[6.2]) == [0, 2, 4, 5]


class TestStates:
    def test_switch_frames_and_slow_push_origins(self):
        sw = [{"t": 1.0, "to": "tight"}, {"t": 2.5, "to": "wide"}]
        tight, start = zooms.frame_states(120, 30.0, sw, cuts=[3.0])
        assert not tight[29] and tight[30] and tight[74] and not tight[75]
        assert start[10] == 0 and start[40] == 30 and start[80] == 75 and start[100] == 90


class TestSlow:
    def test_only_the_longest_quarter_of_the_stretches_pushes_in(self):
        sw = [{"t": t, "to": to} for t, to in ((2.0, "tight"), (3.5, "wide"), (5.0, "tight"), (6.5, "wide"))]
        tight, start = zooms.frame_states(300, 30.0, sw)                # stretches 2, 1.5, 1.5, 1.5, 3.5 s
        assert zooms.slow_starts(tight, start, 30.0) == {195, 0}


class TestBoxes:
    def _shot(self, n=90, cx=960.0, cy=430.0, fw=220.0, fh=260.0, travel=0.0):
        base = [(608, 1080, 656, 0)] * n
        heads = [(cx + travel * np.sin(k / 9.0), cy, fw, fh, 0.0) for k in range(n)]
        return base, heads

    def test_wide_creeps_in_tight_punches_and_the_eyes_hold_their_line(self):
        base, heads = self._shot()
        tight = np.array([False] * 45 + [True] * 45)
        start = np.array([0] * 45 + [45] * 45)
        rep = []
        boxes = zooms.shot_boxes(base, heads, tight, start, 30.0, 1080, 1080, rep)
        zs = [1080 / b[3] for b in boxes]
        assert abs(zs[0] - 1.0) < 1e-6 and 1.02 < zs[44] < 1.04                      # slow push
        assert abs(zs[45] - zooms.PUNCH) < 0.01 and zs[89] > zs[45]                  # the dry punch, then the push
        eye = 430.0 - zooms.EYE * 260.0

        def eye_out(b):
            return (eye - b[1]) / b[3]
        assert abs(eye_out(boxes[0]) - eye_out(boxes[45])) < 0.01 and abs(eye_out(boxes[89]) - eye_out(boxes[0])) < 0.01
        for x, y, w, h in boxes:                                                     # inside the base box
            assert x >= 656 - 1e-6 and x + w <= 656 + 608 + 1e-6 and y >= -1e-6 and y + h <= 1080 + 1e-6

    def test_the_face_never_leaves_the_frame(self):
        base, heads = self._shot(n=60, cx=1090.0, fw=230.0)  # near the right edge of the base box
        tight = np.array([True] * 60)
        start = np.zeros(60, dtype=int)
        for x, y, w, h in zooms.shot_boxes(base, heads, tight, start, 30.0, 1080, 1080):
            hw = zooms.HEAD_W * 230.0
            assert (1090.0 + hw / 2 - x) / w <= 1.0 - zooms.MARGIN + 1e-6
            assert (1090.0 - hw / 2 - x) / w >= zooms.MARGIN - 1e-6

    def test_a_head_on_the_move_gets_a_smaller_punch(self):
        tight = np.array([True] * 90)
        start = np.zeros(90, dtype=int)
        still, moving = [], []
        zooms.shot_boxes(*self._shot(), tight, start, 30.0, 1080, 1080, still)
        zooms.shot_boxes(*self._shot(travel=90.0), tight, start, 30.0, 1080, 1080, moving)
        assert moving[0]["punch"] < still[0]["punch"]

    def test_the_upscale_is_capped_on_an_already_tight_framing(self):
        base = [(512, 910, 700, 60)] * 60                    # framing's eye-line punch-in (x1.19)
        heads = [(960.0, 430.0, 200.0, 240.0, 0.0)] * 60
        rep = []
        boxes = zooms.shot_boxes(base, heads, np.array([True] * 60), np.zeros(60, dtype=int), 30.0, 1080, 1080, rep)
        assert min(1080 / b[3] for b in boxes) >= 1080 / 910 * zooms.PUNCH_MIN - 1e-6
        assert max(1080 / b[3] for b in boxes) <= zooms.TOTAL_MAX + 1e-6


class TestRender:
    def test_chroma_follows_the_luma_box(self):
        luma, chroma = zooms.affine((100.0, 50.0, 540.0, 960.0), 1080, 1920)
        # the centre of the output maps to the centre of the box, in both planes
        assert np.allclose(luma @ [539.5, 959.5, 1], [100 + 270 - 0.5, 50 + 480 - 0.5], atol=1e-6)
        cx, cy = chroma @ [269.5, 479.5, 1]
        assert abs(cx * 2 - (100 + 270 - 0.5)) < 0.3 and abs(cy * 2 + 0.5 - (50 + 480 - 0.5)) < 0.3


class TestRecipe:
    def test_the_references_zooms_are_the_branchs_recipe(self, monkeypatch):
        assert plus.FX["zoom_style"] == "references"
        env = plus.job_env({})
        monkeypatch.setenv("PLUS_FX_JSON", env["PLUS_FX_JSON"])
        assert zooms.style() == "references"
        assert env["BROLL_HERO_PUSH_RATE"] == "0.014" and env["BROLL_HERO_PUSH_CURVE"] == "linear"
        assert json.loads(env["PLUS_ZOOMS_JSON"])["punch"] == 1.12
        monkeypatch.setenv("PLUS_FX_JSON", json.dumps({**plus.FX, "zoom_style": "fixed"}))
        assert zooms.style() == "fixed"
        monkeypatch.delenv("PLUS_FX_JSON")
        assert zooms.style() == "fixed"

    def test_cues_round_trip(self, tmp_path):
        v = str(tmp_path / "c.mp4")
        zooms.write_cues(v, [{"text": "hi", "start": 0.1, "end": 0.3}], joins=[1.5], punch=(2.0, 3.0))
        zooms.mark_applied(v, [{"t": 1.5, "to": "tight", "why": "raccord caché", "word": ""}])
        c = zooms.read_cues(v)
        assert c["words"][0]["text"] == "hi" and c["joins"] == [1.5] and c["applied"][0]["to"] == "tight"


class TestContinuous:
    """10-oct-2026: their face shots creep slowly and steadily, no dry reframe (etude2/mesures/zoom_continu.py)."""

    @staticmethod
    def _mode(monkeypatch):
        for k in ("MODE", "RATE_RANGE", "BACK_EVERY", "PUNCH", "PUNCH_HI", "SLOW_RATE", "SLOW_MAX", "MIN_GAP", "RELAUNCH"):
            monkeypatch.setattr(zooms, k, getattr(zooms, k))
        monkeypatch.setenv("PLUS_ZOOMS_JSON", plus.job_env({})["PLUS_ZOOMS_JSON"])
        zooms.configure()

    def test_the_branch_s_recipe_is_continuous(self, monkeypatch):
        self._mode(monkeypatch)
        assert zooms.MODE == "continuous" and zooms.RATE_RANGE == (0.003, 0.007) and zooms.BACK_EVERY == 3
        # no join is hidden by a dry cut any more: each keeps its pause (montage.settle)
        assert zooms.hide_spacing([2.0, 5.0, 9.0], 30.0) == [0, 1, 2]

    def test_rates_drawn_per_stretch_out_one_in_three(self, monkeypatch):
        self._mode(monkeypatch)
        rates = zooms.continuous_rates(np.repeat(np.arange(9) * 100, 100))
        vals = [rates[s] for s in sorted(rates)]
        assert all(0.003 - 1e-9 <= abs(r) <= 0.007 + 1e-9 for r in vals)
        assert [r < 0 for r in vals] == [False, False, True] * 3
        assert zooms.continuous_rates(np.repeat(np.arange(9) * 100, 100)) == rates, "the same clip, the same draw"

    def test_linear_no_jump_eyes_on_their_line(self, monkeypatch):
        self._mode(monkeypatch)
        n = 300
        base = [(608, 1080, 656, 0)] * n
        heads = [(960.0, 430.0, 220.0, 260.0, 0.0)] * n
        tight = np.zeros(n, dtype=bool)
        start = np.array([0] * 150 + [150] * 150)            # a picture ended at frame 150: a new stretch
        rates = {0: 0.005, 150: -0.006}
        rep = []
        boxes = zooms.shot_boxes(base, heads, tight, start, 30.0, 1080, 1080, rep, rates=rates)
        zs = np.array([1080 / b[3] for b in boxes])
        a, b = zs[:150], zs[150:]
        assert abs(a[0] - 1.0) < 1e-9 and abs(a[-1] - (1 + 0.005 * 5.0)) < 1e-3          # in, +0.5 %/s
        assert abs(b[0] - (1 + 0.006 * 5.0)) < 1e-3 and abs(b[-1] - 1.0) < 1e-9          # out, -0.6 %/s
        for run in (a, b):
            d = np.diff(run)
            assert np.all(np.sign(d) == np.sign(d[0])) and np.ptp(d) < 1e-9, "linear: no acceleration"
            assert np.max(np.abs(d)) < 0.0003, "no dry cut inside a stretch"
        eye = 430.0 - zooms.EYE * 260.0
        line = [(eye - x[1]) / x[3] for x in boxes]
        assert max(line) - min(line) < 0.005
        assert [r["out"] for r in rep] == [False, True]
