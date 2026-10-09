"""The montage (montage.py, 5-oct-2026): silences tightened, cut_out passages taken out, joins that would
show hidden or refused. Pure planning only — the sound, the frames and ffmpeg are faked."""
import json

import montage
import recut
from montage import Grid, Levels

GRID = Grid(30.0, 0.0)
SPEECH, QUIET = -15.0, -60.0


def levels(t0, t1, silences):
    """A sound level per 10 ms over [t0, t1]: speech, except the (a, b) silences."""
    n = int(round((t1 - t0) / montage.HOP))
    db = []
    for i in range(n):
        t = t0 + i * montage.HOP
        db.append(QUIET if any(a <= t < b for a, b in silences) else SPEECH)
    return Levels(t0, db)


def words_of(text_times):
    """[("word", s, e), ...] -> recut.transcript_words' shape."""
    return [{"w": w, "s": s, "e": e} for w, s, e in text_times]


def transcript_of(words):
    return {"segments": [{"start": words[0]["s"], "end": words[-1]["e"],
                          "words": [{"word": " " + w["w"], "start": w["s"], "end": w["e"]} for w in words]}]}


# A clip of [100, 112]: a hush before the first word, a long pause under the hook, the punchline after
# a pause, and silence at the end. Whisper-like timestamps (contiguous, the pauses absorbed).
WORDS = words_of([
    ("They", 100.05, 100.6), ("have", 100.6, 100.9), ("side", 100.9, 101.3), ("effects.", 101.3, 102.3),
    ("People", 103.0, 103.4), ("are", 103.4, 103.6), ("microdosing", 103.6, 104.4), ("them.", 104.4, 105.2),
    ("It", 105.9, 106.1), ("used", 106.1, 106.4), ("to", 106.4, 106.5), ("be", 106.5, 106.7), ("that", 106.7, 107.0),
    ("you", 107.0, 107.2), ("trust", 107.2, 107.6), ("the", 107.6, 107.7), ("coat.", 107.7, 108.4),
    ("So", 108.4, 108.6), ("listen.", 108.6, 109.5),
])
SILENCES = [(100.0, 100.40), (102.0, 103.0), (105.0, 105.9), (109.5, 112.5)]
LEVELS = levels(99.0, 113.0, SILENCES)


def fake_judge(jump=2.0, camera=False, calls=None):
    """The closest-to-the-breath pair, with a given jump (a number, or f(a, b))."""
    def judge(left, right, keep, ok):
        if calls is not None:
            calls.append((left, right, keep))
        pairs = montage.candidate_pairs(GRID, left, right, keep, ok)
        if not pairs:
            return None
        a, b = min(pairs, key=lambda p: (p[0] - left[0]) + (right[1] - p[1]))
        j = jump(a, b) if callable(jump) else jump
        return {"a": a, "b": b, "jump": j, "camera": camera, "kept": round((a - left[0]) + (right[1] - b), 3)}
    return judge


def plan(**kw):
    args = dict(hook_line="They have side effects.", punchline="It used to be that you trust the coat.",
                judge=fake_judge())
    args.update(kw)
    return montage.plan(100.0, 112.0, WORDS, LEVELS, GRID, **args)


class TestText:
    def test_negations_are_seen_in_every_spelling(self):
        for t in ("not", "never", "don't", "doesnt", "can't", "no", "nobody", "isn't"):
            assert montage.is_negation(montage._tok(t)), t
        for t in ("note", "know", "nothingness", "now"):
            assert not montage.is_negation(montage._tok(t)), t

    def test_find_span_is_verbatim_but_for_punctuation(self):
        assert montage.find_span(WORDS, "people are MICRODOSING them", 100, 112) == (4, 7)
        assert montage.find_span(WORDS, "people are not here", 100, 112) is None

    def test_find_span_falls_back_on_the_first_four_words(self):
        # Whisper and the model disagree on the last word: the first four still find it, as long as the text.
        assert montage.find_span(WORDS, "It used to be thet you trust", 100, 112) == (8, 14)

    def test_find_passage_needs_both_ends_in_order(self):
        assert montage.find_passage(WORDS, {"from": "People are", "to": "them."}, 100, 112) == (4, 7)
        assert montage.find_passage(WORDS, {"from": "them.", "to": "People are"}, 100, 112) is None
        assert montage.find_passage(WORDS, {"from": "Nobody said", "to": "this"}, 100, 112) is None

    def test_a_short_reply_is_recognised(self):
        ws = words_of([("Whoa.", 0, 0.4), ("That's", 1, 1.2), ("crazy.", 1.2, 1.6), ("So", 2, 2.2),
                       ("the", 2.2, 2.3), ("data", 2.3, 2.6), ("say", 2.6, 2.8), ("this.", 2.8, 3.0)])
        assert montage.is_reply(ws, 0)
        assert montage.is_reply(ws, 1)
        assert not montage.is_reply(ws, 3)


class TestSoundAndGrid:
    def test_runs_find_the_silences(self):
        runs = LEVELS.runs(100.2, 111.8)
        want = [(102.0, 103.0), (105.0, 105.9), (109.5, 111.8)]
        assert len(runs) == 3
        assert all(abs(a - c) < 0.011 and abs(b - d) < 0.011 for (a, b), (c, d) in zip(runs, want))

    def test_voice_onset_and_offset(self):
        assert abs(LEVELS.voice_from(100.0, 101.0) - 100.40) < 0.011
        assert abs(LEVELS.voice_until(112.0, 108.0) - 109.5) < 0.011

    def test_grid_points_sit_between_two_frames(self):
        assert abs(GRID.snap(1.0) - (1.0 + 1 / 60)) < 1e-5 or abs(GRID.snap(1.0) - (1.0 - 1 / 60)) < 1e-5
        for p in GRID.points(10.0, 10.2):
            assert abs((p * 30) % 1 - 0.5) < 1e-4
        assert len(GRID.points(10.0, 10.2)) == 6

    def test_standard_rates(self):
        assert montage.standard_rate(4046 / 135) == 30000 / 1001
        assert montage.standard_rate(25.0) == 25.0
        assert montage.standard_rate(12.5) == 12.5


class TestPlan:
    def test_silences_become_a_breath_and_the_clip_opens_on_the_voice(self):
        p = plan()
        assert abs(p["start"] - (100.40 - montage.LEAD_IN)) < 1 / 30 + 1e-6
        cut = [r for r in p["removals"] if r["kind"] == "silence"]
        assert len(cut) == 2
        first = min(cut, key=lambda r: r["a"])
        assert 102.0 < first["a"] < first["b"] < 103.0
        kept = (first["a"] - 102.0) + (103.0 - first["b"])
        assert montage.BREATH - 1e-6 <= kept <= montage.BREATH + montage.BREATH_SLACK + 1e-6
        # Every boundary is half a frame between two frames.
        for r in p["removals"]:
            for t in (r["a"], r["b"]):
                assert abs((t * 30) % 1 - 0.5) < 1e-4

    def test_the_pause_before_the_punchline_stays_a_beat(self):
        p = plan()
        beat = next(r for r in p["removals"] if 105.0 <= r["a"] < 105.9)
        assert beat["why"] == "beat"
        assert (beat["a"] - 105.0) + (105.9 - beat["b"]) >= montage.BEAT - 1e-6

    def test_the_tail_is_trimmed_to_a_short_hold(self):
        p = plan()
        assert abs(p["end"] - (109.5 + montage.TAIL_KEEP)) < 1 / 30 + 1e-6

    def test_a_visible_jump_is_refused_and_the_pause_kept(self):
        p = plan(judge=fake_judge(jump=montage.JUMP_HIDE + 5))
        assert not p["removals"]
        assert {r["reason"] for r in p["refused"]} == {"jump"}
        segs, joins = montage.timeline(p["start"], p["end"], p["removals"])
        assert len(segs) == 1 and joins == []

    def test_a_small_jump_is_to_hide_a_camera_cut_is_not(self):
        p = plan(judge=fake_judge(jump=(montage.JUMP_CLEAN + montage.JUMP_HIDE) / 2))
        assert {r["verdict"] for r in p["removals"]} == {"hide"}
        p = plan(judge=fake_judge(jump=80.0, camera=True))
        assert {r["verdict"] for r in p["removals"]} == {"camera"}

    def test_a_wider_breath_is_tried_before_giving_up(self):
        calls = []

        def jump(a, b):
            return 2.0 if (a - 102.0) + (103.0 - b) > montage.BREATH + montage.BREATH_SLACK + 0.01 else 30.0
        p = plan(judge=fake_judge(jump=jump, calls=calls))
        first = min(p["removals"], key=lambda r: r["a"])
        assert first["verdict"] == "clean" and first["kept"] > montage.BREATH + montage.BREATH_SLACK
        assert any(k[1] > montage.BREATH + montage.BREATH_SLACK for _, _, k in calls)

    def test_words_stay_in_sync_after_the_cuts(self):
        p = plan()
        segs, joins = montage.timeline(p["start"], p["end"], p["removals"])
        vt = recut.virtual_transcript(transcript_of(WORDS), segs)
        vw = {w["word"].strip(): w for sg in vt["segments"] for w in sg["words"]}
        # A word keeps its place relative to the piece it is in: source time - piece start + piece offset.
        for name in ("People", "It", "listen."):
            src = next(w for w in WORDS if w["w"] == name)
            t = recut.source_to_clip(segs, src["s"])
            assert abs(vw[name]["start"] - t) < 2e-3, name
        said = [w["word"].strip() for sg in vt["segments"] for w in sg["words"]]
        assert said == [w["w"] for w in WORDS]      # every word once: none vanished, none doubled at a join
        assert abs(recut.total_duration(segs) - (p["end"] - p["start"] - sum(r["b"] - r["a"] for r in p["removals"]))) < 1e-3

    def test_a_word_whisper_put_in_the_silence_is_never_swallowed(self):
        ws = WORDS[:4] + [{"w": "uh", "s": 102.4, "e": 102.45}] + WORDS[4:]
        p = montage.plan(100.0, 112.0, ws, LEVELS, GRID, judge=fake_judge())
        for r in p["removals"]:
            assert not (r["a"] <= 102.4 and 102.45 <= r["b"])
        segs, _ = montage.timeline(p["start"], p["end"], p["removals"])
        vt = recut.virtual_transcript(transcript_of(ws), segs)
        assert "uh" in [w["word"].strip() for sg in vt["segments"] for w in sg["words"]]

    def test_no_piece_shorter_than_half_a_second(self):
        p = plan()
        segs, _ = montage.timeline(p["start"], p["end"], p["removals"])
        assert all(s["end"] - s["start"] >= montage.MIN_PIECE - 1e-6 for s in segs)

    def test_switched_off_silences_leave_only_the_edges(self):
        p = plan(silences=False)
        assert p["removals"] == []
        assert p["start"] > 100.3


class TestPassages:
    def test_a_passage_is_taken_out_whole(self):
        p = plan(cut_out=[{"from": "People are", "to": "microdosing them.", "why": "aside"}],
                 hook_line="Nothing like it", punchline="So listen.")
        cut = [r for r in p["removals"] if r["kind"] == "passage"]
        assert len(cut) == 1
        r = cut[0]
        assert 102.0 <= r["a"] <= 103.0 and 105.0 <= r["b"] <= 105.9
        segs, _ = montage.timeline(p["start"], p["end"], p["removals"])
        vt = recut.virtual_transcript(transcript_of(WORDS), segs)
        said = [w["word"].strip() for sg in vt["segments"] for w in sg["words"]]
        assert "microdosing" not in said and "People" not in said
        assert said[:4] == ["They", "have", "side", "effects."] and "It" in said

    def test_the_hook_the_punchline_and_negations_are_untouchable(self):
        p = plan(cut_out=[{"from": "They have", "to": "effects.", "why": "aside"}])
        assert p["refused"][0]["reason"] in ("hook", "edge")
        p = plan(cut_out=[{"from": "It used to", "to": "the coat.", "why": "aside"}], hook_line="x y z")
        assert p["refused"][0]["reason"] == "punchline"
        ws = [dict(w) for w in WORDS]
        ws[6]["w"] = "never"
        p = montage.plan(100.0, 112.0, ws, LEVELS, GRID, cut_out=[{"from": "People are", "to": "never them."}],
                         judge=fake_judge())
        assert p["refused"][0]["reason"] == "negation"

    def test_a_passage_not_found_is_not_cut(self):
        p = plan(cut_out=[{"from": "Doctors hate", "to": "this trick.", "why": "aside"}])
        assert p["refused"][0]["reason"] == "not_found"
        assert all(r["kind"] == "silence" for r in p["removals"])

    def test_a_passage_with_a_visible_jump_is_refused(self):
        p = plan(cut_out=[{"from": "People are", "to": "microdosing them.", "why": "aside"}],
                 hook_line="x y z", punchline="So listen.", judge=fake_judge(jump=montage.JUMP_HIDE + 1))
        assert any(r["kind"] == "passage" and r["reason"] == "jump" for r in p["refused"])
        assert not any(r["kind"] == "passage" for r in p["removals"])


class TestSettle:
    def test_a_join_without_room_for_its_tight_frame_is_given_up(self):
        # Two joins to hide 0.9 s apart (too close to share a frame, too close for two): one goes.
        p = plan(judge=fake_judge(jump=(montage.JUMP_CLEAN + montage.JUMP_HIDE) / 2))
        n = len(p["removals"])
        segs, joins, windows, events = montage.settle(p, shots=())
        assert len(windows) >= 1
        hide_t = [t for r, t in joins if r["verdict"] == "hide"]
        for t in hide_t:
            assert any(abs(t - a) < 1e-3 or abs(t - b) < 1e-3 for a, b in windows)
        assert len(p["removals"]) + sum(1 for r in p["refused"] if r["reason"] == "spacing") == n

    def test_with_the_smart_zooms_a_join_to_hide_needs_only_their_gap(self, monkeypatch):
        # 9-oct-2026 (zooms.py): the dry cut lands on the join itself, no tight-frame window to fit.
        import zooms
        monkeypatch.setenv("PLUS_FX_JSON", json.dumps({"zoom_style": "references"}))
        p = plan(judge=fake_judge(jump=(montage.JUMP_CLEAN + montage.JUMP_HIDE) / 2))
        segs, joins, windows, events = montage.settle(p, shots=())
        hide_t = [t for r, t in joins if r["verdict"] == "hide"]
        assert windows == [] and hide_t
        assert all(b - a >= zooms.MIN_GAP - 1e-6 for a, b in zip(hide_t, hide_t[1:]))
        # short_piece: a 0.25-0.35 s pause now counted (SILENCE_MIN 0.25) leaves a piece too short to keep
        assert all(r["reason"] in ("spacing", "short_piece") for r in p["refused"] if r["kind"] == "silence")

    def test_hide_off_drops_every_join_to_hide(self):
        p = plan(judge=fake_judge(jump=(montage.JUMP_CLEAN + montage.JUMP_HIDE) / 2))
        segs, joins, windows, events = montage.settle(p, shots=(), hide=False)
        assert windows == [] and joins == []
        assert {r["reason"] for r in p["refused"]} <= {"hide_off", "short_piece"} and "hide_off" in {r["reason"] for r in p["refused"]}

    def test_source_camera_cuts_land_on_the_new_timeline(self):
        p = plan()
        segs, joins, windows, events = montage.settle(p, shots=(106.0,))
        assert len(events) == 1
        assert abs(events[0][0] - recut.source_to_clip(segs, 106.0)) < 1e-3


class TestCutCommand:
    SEGS = [{"start": 100.35, "end": 102.1}, {"start": 102.9, "end": 105.1}]

    def test_one_pass_with_a_fade_on_both_sides_of_every_join(self):
        cmd = montage.cut_command("src.mkv", self.SEGS, "out.mp4", fps=30000 / 1001,
                                  video_args=["-c:v", "libx264"])
        graph = cmd[cmd.index("-filter_complex") + 1]
        assert cmd[cmd.index("-ss") + 1] == f"{99.35:.6f}"
        assert "trim=start=1.000000:end=2.750000" in graph and "trim=start=3.550000:end=5.750000" in graph
        assert graph.count("afade=t=in:st=0:d=0.0150") == 2
        assert "afade=t=out:st=1.735000:d=0.0150" in graph
        assert "concat=n=2:v=1:a=1" in graph and "loudnorm" in graph
        assert cmd[cmd.index("-r") + 1] == "30000/1001"
        assert 0.010 <= montage.FADE <= 0.020

    def test_no_loudness_pass_when_switched_off(self):
        cmd = montage.cut_command("src.mkv", self.SEGS, "out.mp4", normalize=False, video_args=["-c:v", "x"])
        assert "loudnorm" not in cmd[cmd.index("-filter_complex") + 1]


class TestClipRecord:
    REPORT = {"start": 100.0, "end": 110.0, "segments": [{"start": 100.0, "end": 102.0}, {"start": 103.0, "end": 110.0}],
              "hide_windows": [[2.0, 4.5]], "joins": [{"t": 2.0, "verdict": "hide"}]}

    def test_the_inset_moves_onto_the_new_timeline(self):
        found = {"t0": 4.0, "t1": 6.0, "box": [0.6, 0.6, 0.3, 0.3]}
        moved = montage.inset_on_clip(found, self.REPORT)
        assert (moved["t0"], moved["t1"]) == (3.0, 5.0)
        assert (moved["src_t0"], moved["src_t1"]) == (104.0, 106.0)
        assert montage.inset_on_clip({"t0": 2.2, "t1": 2.8}, self.REPORT) is None

    def test_no_picture_over_a_reaction_but_pictures_may_cover_joins(self):
        block = montage.broll_block({"reactions": [{"at": 8.0, "dur": 1.2}]}, self.REPORT)
        assert block == [(7.7, 9.5)], "a drawing over a join hides it: the join's tight frame is then dropped"

    def test_the_switch_reaches_the_job_from_the_recipe(self, monkeypatch):
        monkeypatch.setenv("PLUS_MONTAGE_JSON", json.dumps({"enabled": True, "silences": True}))
        assert montage.config()["silences"] is True
        monkeypatch.setenv("PLUS_MONTAGE_JSON", json.dumps({"enabled": False}))
        assert montage.config() == {}
        monkeypatch.delenv("PLUS_MONTAGE_JSON")
        assert montage.config() == {}

    def test_describe(self):
        line = montage.describe({"saved": 2.5, "joins": [{"verdict": "clean"}, {"verdict": "hide"}],
                                 "refused": [{"reason": "jump"}]})
        assert "2.5 s saved" in line and "1 clean" in line and "1 jump" in line
