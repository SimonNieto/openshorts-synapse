import punch_in
from punch_in import MAX_ZOOM, crop_boxes, sendcmd_lines, zoom_curve


class TestZoomCurve:
    def test_no_beats_means_no_movement(self):
        assert set(zoom_curve(90, 30.0, [])) == {1.0}

    def test_a_beat_reaches_full_zoom_and_comes_back(self):
        zooms = zoom_curve(150, 30.0, [1.0])
        assert max(zooms) == MAX_ZOOM
        assert zooms[0] == 1.0
        assert zooms[-1] == 1.0

    def test_the_push_is_faster_in_than_out(self):
        zooms = zoom_curve(300, 30.0, [1.0])
        peak = zooms.index(max(zooms))
        release = next(i for i in range(peak, len(zooms)) if zooms[i] == 1.0)
        rise = peak - int(1.0 * 30)
        assert rise < (release - peak)

    def test_overlapping_beats_do_not_compound(self):
        zooms = zoom_curve(300, 30.0, [1.0, 1.2, 1.4])
        assert max(zooms) == MAX_ZOOM

    def test_beats_outside_the_scene_are_ignored(self):
        assert set(zoom_curve(60, 30.0, [45.0])) == {1.0}

    def test_start_offset_shifts_a_clip_level_beat_into_the_scene(self):
        # Same beat, scene starting at 10s: only the offset version moves.
        assert set(zoom_curve(60, 30.0, [10.5])) == {1.0}
        assert max(zoom_curve(60, 30.0, [10.5], start_offset=10.0)) > 1.0

    def test_zero_length_scene_is_safe(self):
        assert zoom_curve(0, 30.0, [1.0]) == []


class TestCropBoxes:
    def test_unzoomed_frames_keep_the_tracked_crop(self):
        boxes = crop_boxes([100, 100], [1.0, 1.0], 600, 1080, 1920, 1080)
        assert boxes[0][0] == 600 and boxes[0][1] == 1080

    def test_zoom_shrinks_the_crop(self):
        boxes = crop_boxes([100], [1.12], 600, 1080, 1920, 1080)
        assert boxes[0][0] < 600 and boxes[0][1] < 1080

    def test_the_centre_holds_while_zooming(self):
        # A push must not read as a pan: same x in, same centre out.
        wide = crop_boxes([600], [1.0], 600, 1080, 1920, 1080)[0]
        tight = crop_boxes([600], [1.12], 600, 1080, 1920, 1080)[0]
        assert abs((wide[2] + wide[0] / 2) - (tight[2] + tight[0] / 2)) <= 2

    def test_boxes_stay_inside_the_frame(self):
        for x in (0, 1320):
            box = crop_boxes([x], [1.12], 600, 1080, 1920, 1080)[0]
            assert 0 <= box[2] <= 1920 - box[0]
            assert 0 <= box[3] <= 1080 - box[1]

    def test_all_dimensions_are_even(self):
        for z in (1.0, 1.03, 1.07, 1.12):
            w, h, x, y = crop_boxes([333], [z], 601, 1079, 1920, 1080)[0]
            assert w % 2 == 0 and h % 2 == 0 and x % 2 == 0 and y % 2 == 0


class TestSendcmdLines:
    def test_first_frame_sets_every_parameter(self):
        lines = sendcmd_lines([(600, 1080, 100, 0)], fps=30.0)
        assert len(lines) == 4
        assert {ln.split()[2] for ln in lines} == {"w", "h", "x", "y"}

    def test_repeated_boxes_emit_nothing(self):
        box = (600, 1080, 100, 0)
        assert len(sendcmd_lines([box, box, box], fps=30.0)) == 4

    def test_only_changed_parameters_are_re_emitted(self):
        lines = sendcmd_lines([(600, 1080, 100, 0), (600, 1080, 104, 0)],
                              fps=30.0)
        assert len(lines) == 5
        assert lines[-1].endswith("x 104;")

    def test_timestamps_are_scene_relative(self):
        lines = sendcmd_lines([(600, 1080, 100, 0), (598, 1078, 101, 1)],
                              fps=30.0)
        assert lines[0].startswith("0.0000")
        assert lines[-1].startswith("0.0333")


class TestEmphasisTimes:
    def test_silent_or_unreadable_audio_yields_no_beats(self, monkeypatch):
        import active_speaker
        monkeypatch.setattr(active_speaker, "audio_envelope",
                            lambda *a, **k: [])
        assert punch_in.emphasis_times("x.mp4", 30.0) == []

    def test_flat_audio_yields_no_beats(self, monkeypatch):
        import active_speaker
        monkeypatch.setattr(active_speaker, "audio_envelope",
                            lambda *a, **k: [0.5] * 50)
        assert punch_in.emphasis_times("x.mp4", 10.0) == []

    def test_beats_respect_the_minimum_gap(self, monkeypatch):
        import active_speaker
        envelope = [1.0 if i % 2 == 0 else 0.0 for i in range(100)]
        monkeypatch.setattr(active_speaker, "audio_envelope",
                            lambda *a, **k: envelope)
        times = punch_in.emphasis_times("x.mp4", 20.0, window=0.2, min_gap=4.0)
        assert all(b - a >= 4.0 for a, b in zip(times, times[1:]))


# --- the tight frame (5-oct-2026, decision 4 and the montage's hidden joins) ---------------------------

def _words(spec):
    """"Text@start-end ..." -> clip words."""
    out = []
    for tok in spec.split():
        text, times = tok.rsplit("@", 1)
        s, e = times.split("-")
        out.append({"text": text, "start": float(s), "end": float(e)})
    return out


class TestSpacing:
    def test_two_changes_never_flicker(self):
        assert punch_in.spaced(10.0, 12.5, [(5.0, 5.0)])
        assert not punch_in.spaced(10.0, 12.5, [(7.0, 7.0)])        # 3 s after a cut: too close
        assert not punch_in.spaced(10.0, 12.5, [(6.5, 8.5)])        # 1.5 s after a picture left
        assert not punch_in.spaced(10.0, 12.5, [(13.5, 13.5)])      # 1 s before the next cut
        assert not punch_in.spaced(10.0, 12.5, [(11.0, 12.0)])      # overlap
        assert punch_in.spaced(10.0, 12.5, [(14.5, 16.0)])


class TestScheduleHides:
    def test_a_join_gets_a_tight_frame_starting_on_it(self):
        windows, refused = punch_in.schedule_hides([10.0], 30.0)
        assert windows == [(10.0, 10.0 + punch_in.TIGHT_DUR)] and refused == []

    def test_two_close_joins_share_one_tight_frame(self):
        windows, refused = punch_in.schedule_hides([10.0, 12.0], 30.0)
        assert windows == [(10.0, 12.0)] and refused == []

    def test_backwards_when_a_cut_follows(self):
        windows, refused = punch_in.schedule_hides([10.0], 30.0, events=[(13.0, 13.0)])
        assert windows == [(10.0 - punch_in.TIGHT_DUR, 10.0)]

    def test_no_room_means_the_join_is_given_up(self):
        windows, refused = punch_in.schedule_hides([10.0, 10.8], 30.0)
        assert len(windows) == 1 and refused == [1]
        windows, refused = punch_in.schedule_hides([10.0], 30.0, events=[(8.5, 8.5), (11.5, 11.5)])
        assert windows == [] and refused == [0]

    def test_never_past_the_clip(self):
        windows, refused = punch_in.schedule_hides([1.0, 29.5], 30.0)
        assert all(0.0 <= a < b <= 30.0 for a, b in windows)


class TestPlanTight:
    WORDS = _words(" ".join(f"w{k}.@{k * 0.5:.2f}-{k * 0.5 + 0.45:.2f}" for k in range(80)))

    def test_a_long_static_stretch_gets_tight_frames(self):
        out = punch_in.plan_tight(40.0, [(5.0, 5.0), (25.0, 25.0)], self.WORDS)
        assert out
        assert all(punch_in.TIGHT_MIN - 1e-6 <= b - a <= punch_in.TIGHT_MAX + 1e-6 for a, b in out)
        # Nothing in [5, 25] runs past STATIC_MAX any more.
        marks = sorted([5.0, 25.0] + [x for w in out for x in w if 5.0 <= x <= 25.0])
        assert max(b - a for a, b in zip(marks, marks[1:])) <= punch_in.STATIC_MAX + 1.0

    def test_found_even_where_no_word_opens_in_time(self):
        # A reaction 15.7-16.9 then a tight frame at 25.5: the only room is 20.9-21.5, where no word starts.
        words = [w for w in self.WORDS if not (20.5 <= w["start"] <= 21.8)]
        out = punch_in.plan_tight(35.0, [(15.7, 16.9), (25.5, 28.0)], words)
        assert any(16.9 < a and b < 25.5 for a, b in out)

    def test_a_short_stretch_is_left_alone(self):
        assert punch_in.plan_tight(12.0, [(5.0, 5.0), (10.0, 10.0)], self.WORDS) == []

    def test_spacing_with_every_other_change(self):
        changes = [(3.3, 3.3), (12.0, 13.2), (20.0, 22.5)]
        out = punch_in.plan_tight(40.0, changes, self.WORDS)
        for a, b in out:
            assert punch_in.spaced(a, b, changes)

    def test_the_punchline_takes_the_last_stretch(self):
        out = punch_in.plan_tight(40.0, [(5.0, 5.0), (30.0, 30.0)], self.WORDS, punch=(36.0, 39.0))
        assert any(abs(a - 35.95) < 0.01 for a, b in out)
        assert all(b <= 40.0 for _, b in out)

    def test_ends_on_a_word(self):
        out = punch_in.plan_tight(40.0, [(5.0, 5.0), (25.0, 25.0)], self.WORDS)
        ends = {round(w["end"], 2) for w in self.WORDS}
        assert all(round(b, 2) in ends for _, b in out)


class TestTightBox:
    def test_closer_about_the_face_which_keeps_its_place(self):
        w, h, x, y = punch_in.tight_box(1080, 1920, (440, 600, 200, 260), 1.2)
        assert (w, h) == (900, 1600)
        cx, cy = 540, 730
        assert abs((cx - x) / w - cx / 1080) < 0.01 and abs((cy - y) / h - cy / 1920) < 0.01

    def test_inside_the_picture_and_even(self):
        for face in ((0, 0, 100, 100), (1000, 1800, 80, 120), None):
            w, h, x, y = punch_in.tight_box(1080, 1920, face, 1.3)
            assert 0 <= x <= 1080 - w and 0 <= y <= 1920 - h
            assert w % 2 == h % 2 == x % 2 == y % 2 == 0

    def test_zoom_by_source(self):
        assert punch_in.tight_zoom(1080) == punch_in.TIGHT_ZOOM == 1.2
        assert punch_in.tight_zoom(2160) == punch_in.TIGHT_ZOOM_HI == 1.3


class TestTightGraph:
    WINS = [{"a": 10.0, "b": 12.5, "box": (900, 1600, 90, 120)}, {"a": 20.0, "b": 22.0, "box": (900, 1600, 60, 100)}]

    def test_a_dry_cut_in_and_out_on_the_very_frames(self):
        g = punch_in.tight_graph(self.WINS, 30.0, 1080, 1920)
        a, b = 10.0 - 1 / 60, 12.5 - 1 / 60
        assert f"between(t,{a:.4f},{b:.4f})" in g          # from the window's first frame to its last
        assert "crop=w=900:h=1600" in g and "scale=1080:1920" in g
        # One fixed place per window: nothing moves inside a tight frame (no zoom, no pan).
        assert f"if(between(t,{a:.4f},{b:.4f}),90," in g and f"if(between(t,{a:.4f},{b:.4f}),120," in g
        assert "zoompan" not in g and "sendcmd" not in g
