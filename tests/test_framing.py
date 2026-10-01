"""framing.py: how a tracked head is framed per shot (fixed framing with look-room, hold-and-glide,
eye line by a bounded punch-in). Source 1920x1080, crop 607x1080 (9:16), 30 fps."""
import math

import pytest

import framing

W, H, CW, CH, FPS = 1920, 1080, 607, 1080, 30.0


def _track(n, cx=920.0, cy=480.0, w=250.0, h=250.0, yaw=0.0, wobble=6.0, every=4):
    """A head seen every ``every`` frames (None between, like DETECT_STRIDE), jittering by ``wobble`` px."""
    out = []
    for i in range(n):
        if i % every:
            out.append(None)
            continue
        j = wobble * math.sin(i / 3.0)
        c = cx(i) if callable(cx) else cx
        out.append((c + j, cy, w, h, yaw))
    return out


def _inside(boxes):
    for w, h, x, y in boxes:
        assert w % 2 == 0 and h % 2 == 0 and x % 2 == 0 and y % 2 == 0
        assert 0 <= x and x + w <= W and 0 <= y and y + h <= H
        assert abs(w / h - CW / CH) < 0.01


class TestFixedFraming:
    def test_a_still_head_gets_one_framing_centred_on_it(self):
        boxes, rep = framing.shot_boxes(_track(300), FPS, CW, CH, W, H)
        _inside(boxes)
        assert rep["fixed"] and rep["moves"] == 0 and rep["zoom"] == 1.0 and rep["look"] == 0.0
        assert len(set(boxes)) == 1
        w, h, x, y = boxes[0]
        assert (w, h, y) == (CW - CW % 2, CH, 0)
        assert abs((x + w / 2) - 920) <= 3, "the head is in the middle"

    def test_a_turned_face_gets_room_in_front_of_it(self):
        right, _ = framing.shot_boxes(_track(300, yaw=0.18), FPS, CW, CH, W, H)      # looks to the image's right
        left, _ = framing.shot_boxes(_track(300, yaw=-0.18), FPS, CW, CH, W, H)
        front, _ = framing.shot_boxes(_track(300, yaw=0.03), FPS, CW, CH, W, H)
        xr, xl, xf = right[0][2], left[0][2], front[0][2]
        shift = framing.LOOK_ROOM * right[0][0]
        assert xr - xf == pytest.approx(shift, abs=3), "the frame moves right: the face sits left, room in front"
        assert xf - xl == pytest.approx(shift, abs=3)

    def test_a_lean_that_fits_the_frame_does_not_move_the_camera(self):
        # 150 px of travel with a 250 px face: 325 px of head + 150 < 607 - 2 * 36
        cx = lambda i: 920.0 + (150.0 if 120 <= i < 220 else 0.0)
        boxes, rep = framing.shot_boxes(_track(300, cx=cx), FPS, CW, CH, W, H)
        assert rep["fixed"] and len(set(boxes)) == 1
        w, h, x, y = boxes[0]
        head_w = framing.HEAD_W * 250
        assert x + framing.MARGIN_X * w <= 920 - head_w / 2, "the head at rest stays inside the margin"
        assert 1070 + head_w / 2 <= x + w - framing.MARGIN_X * w, "and so does the head leaning"

    def test_the_head_never_reaches_the_edge_even_when_turned(self):
        # A wide head (400 px face -> 520 px head) turned right: the look-room must give way to the margin.
        boxes, rep = framing.shot_boxes(_track(300, w=400, h=400, yaw=0.2), FPS, CW, CH, W, H)
        w, h, x, y = boxes[0]
        head_w = framing.HEAD_W * 400
        assert x + framing.MARGIN_X * w <= 920 - head_w / 2 + 1
        assert 920 + head_w / 2 <= x + w - framing.MARGIN_X * w + 1


class TestHoldAndGlide:
    def test_a_head_that_really_moves_gets_one_glide_then_holds(self):
        cx = lambda i: 700.0 if i < 200 else 1200.0       # 500 px: no single framing holds a 325 px head over it
        boxes, rep = framing.shot_boxes(_track(600, cx=cx), FPS, CW, CH, W, H)
        _inside(boxes)
        assert not rep["fixed"] and rep["moves"] == 1
        xs = [b[2] + b[0] / 2 for b in boxes]
        assert abs(xs[0] - 700) < 10 and abs(xs[-1] - 1200) < 10
        assert len(set(xs[:150])) == 1 and len(set(xs[-150:])) == 1, "holds before and after"
        moving = [i for i in range(1, len(xs)) if xs[i] != xs[i - 1]]
        assert moving and 0.8 * FPS - 2 <= moving[-1] - moving[0] + 1 <= framing.GLIDE_S[1] * FPS + 2   # an instant 500 px jump counts as "leaving": a quicker glide
        steps = [abs(xs[i] - xs[i - 1]) for i in moving]
        assert max(steps) < 500 / (0.8 * FPS) * 2.0, "eased: no whip"

    def test_a_brief_excursion_is_ignored(self):
        cx = lambda i: 700.0 if not (100 <= i < 115) else 1200.0   # half a second away
        boxes, rep = framing.shot_boxes(_track(600, cx=cx), FPS, CW, CH, W, H)
        assert rep["moves"] == 0
        assert len(set(boxes)) == 1

    def test_the_glide_hurries_when_the_head_is_leaving_the_frame(self):
        cx = lambda i: 700.0 if i < 100 else 700.0 + min(600.0, (i - 100) * 6.0)   # 180 px/s to the right
        boxes, rep = framing.shot_boxes(_track(500, cx=cx, every=1, wobble=0), FPS, CW, CH, W, H)
        assert rep["moves"] >= 1
        head_w = framing.HEAD_W * 250
        for i, (w, h, x, y) in enumerate(boxes):
            c = cx(i)
            assert c + head_w / 2 <= x + w + 60, f"frame {i}: the head is cut on the right"

    def test_two_glides_are_at_least_gap_apart_unless_urgent(self):
        cx = lambda i: 500.0 if i < 150 else (1000.0 if i < 300 else 1400.0)   # two settled moves 5 s apart
        boxes, rep = framing.shot_boxes(_track(600, cx=cx), FPS, CW, CH, W, H)
        assert rep["moves"] == 2


class TestEyeLine:
    def test_a_face_sitting_low_is_raised_by_a_bounded_punch_in(self):
        boxes, rep = framing.shot_boxes(_track(300, cy=560.0, h=250.0, w=250.0), FPS, CW, CH, W, H)   # centre at 0.52 H
        _inside(boxes)
        w, h, x, y = boxes[0]
        assert 1.0 < rep["zoom"] <= framing.ZOOM_MAX
        assert h == framing._even(CH / rep["zoom"]) and y > 0
        assert rep["eye"] <= framing.EYE_LINE[1] + 0.01, "the face centre came up to the eye line"
        crown = 560 - 125 - framing.HEAD_ABOVE * 250
        assert y + framing.HEADROOM * h <= crown + 1

    def test_a_face_already_on_the_eye_line_keeps_the_full_frame(self):
        boxes, rep = framing.shot_boxes(_track(300, cy=440.0), FPS, CW, CH, W, H)   # 0.41 H
        assert rep["zoom"] == 1.0 and boxes[0][1] == CH and boxes[0][3] == 0

    def test_a_small_face_is_brought_closer_within_the_cap(self):
        boxes, rep = framing.shot_boxes(_track(300, cy=440.0, w=120.0, h=120.0), FPS, CW, CH, W, H)   # 11 % of H
        assert rep["zoom"] == pytest.approx(framing.ZOOM_MAX, abs=0.01)
        _inside(boxes)

    def test_the_punch_in_never_squeezes_the_head_s_travel(self):
        # 260 px of travel and a 325 px head need 585 px + margins: a zoom would push the head out.
        cx = lambda i: 920.0 + (260.0 if (i // 150) % 2 else 0.0)
        boxes, rep = framing.shot_boxes(_track(600, cx=cx, cy=560.0), FPS, CW, CH, W, H)
        assert rep["zoom"] < 1.05

    def test_high_resolution_sources_may_zoom_more(self):
        assert framing.max_zoom(1080) == framing.ZOOM_MAX
        assert framing.max_zoom(1440) == framing.ZOOM_MAX_HI
        assert framing.max_zoom(2160) == framing.ZOOM_MAX_HI


class TestPlumbing:
    def test_nothing_seen_nothing_framed(self):
        assert framing.shot_boxes([None] * 50, FPS, CW, CH, W, H) is None

    def test_gaps_are_held_from_the_last_sighting(self):
        heads = [None, None, (900.0, 480.0, 250.0, 250.0, 0.1), None, None, (910.0, 480.0, 250.0, 250.0, None)]
        obs = framing.fill(heads)
        assert obs[0][0] == 900.0 and obs[3][0] == 900.0 and obs[5][0] == 910.0
        assert obs[2][4] == 0.1 and obs[5][4] == 0.0

    def test_a_beat_punch_in_closes_about_the_box_centre(self):
        boxes = [(606, 1078, 600, 0)] * 10
        zooms = [1.0] * 5 + [1.12] * 5
        out = framing.with_zoom(boxes, zooms, W, H)
        assert out[:5] == boxes[:5]
        w, h, x, y = out[-1]
        assert w == framing._even(606 / 1.12) and h == framing._even(1078 / 1.12)
        assert abs((x + w / 2) - (600 + 303)) <= 2 and abs((y + h / 2) - 539) <= 2
        _inside(out)

    def test_describe_reads_as_a_log_line(self):
        line = framing.describe([{"fixed": True, "moves": 0, "zoom": 1.0, "look": 0.07},
                                 {"fixed": False, "moves": 2, "zoom": 1.12, "look": 0.0}])
        assert "1 fixed" in line and "1 with glides (2 move(s))" in line and "x1.12" in line and "look-room on 1" in line
