"""screen_inset: the picture a podcast puts in a corner of the wide frame (JRE #2515, 1-oct-2026: "Brain Cell /
The Universe" bottom-right for the last 7 s of the clip at 733 s), found on the source, hidden on the cut,
shown whole as a card."""
import os
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

import screen_inset as si

FFMPEG = shutil.which("ffmpeg") is not None


def _frame(W=640, H=360, blob_x=200, inset=None, pattern_seed=1):
    """A grey wall, a dark "person" blob that moves with blob_x, and optionally a white-framed picture
    ``inset`` = (x, y, w, h) in fractions holding a fixed random pattern."""
    img = np.full((H, W), 120, dtype=np.uint8)
    img[:, :] += (np.arange(W, dtype=np.uint8) // 8)[None, :] % 20       # a textured wall
    img[H // 3:, blob_x:blob_x + 90] = 40                                 # the person
    if inset:
        x, y, w, h = inset
        x0, y0, x1, y1 = int(x * W), int(y * H), int((x + w) * W), int((y + h) * H)
        img[y0:y1, x0:x1] = 250
        rng = np.random.default_rng(pattern_seed)
        img[y0 + 6:y1 - 6, x0 + 6:x1 - 6] = rng.integers(0, 200, (y1 - y0 - 12, x1 - x0 - 12), dtype=np.uint8)
    return img


BOX = (0.55, 0.58, 0.42, 0.38)


class TestGeometry:
    def test_a_white_framed_picture_in_a_corner_is_a_rectangle(self):
        found = si.rectangles(_frame(inset=BOX))
        assert found, "nothing found"
        best = max(found, key=lambda b: b[2] * b[3])
        assert all(abs(a - b) < 0.02 for a, b in zip(best, BOX)), best
        assert si.corner_name(best) == "bottom-right"

    def test_the_wall_and_the_person_are_not(self):
        assert si.rectangles(_frame()) == []

    def test_a_rectangle_in_the_middle_is_not_an_inset(self):
        assert not si.in_corner((0.3, 0.3, 0.3, 0.3))
        assert si.in_corner((0.02, 0.6, 0.3, 0.35))
        assert si.corner_name((0.02, 0.02, 0.3, 0.3)) == "top-left"


class TestTime:
    def test_a_box_that_comes_up_mid_clip_is_picked_with_its_onset(self):
        n, fps = 40, 4
        g = {"box": BOX, "frames": set(range(24, 40))}
        picked = si.pick([g], n, fps)
        assert picked and picked[1:] == (24, 39, "onset")

    def test_a_box_there_the_whole_time_is_the_set_not_an_inset(self):
        assert si.pick([{"box": BOX, "frames": set(range(40))}], 40, 4) is None

    def test_a_box_that_goes_away_is_picked_too(self):
        picked = si.pick([{"box": BOX, "frames": set(range(0, 20))}], 40, 4)
        assert picked and picked[1:] == (0, 19, "offset")

    def test_a_flash_is_ignored(self):
        assert si.pick([{"box": BOX, "frames": {10, 11, 12}}], 40, 4) is None

    def test_one_missed_sample_does_not_split_it(self):
        picked = si.pick([{"box": BOX, "frames": set(range(20, 40)) - {30}}], 40, 4)
        assert picked and picked[1:3] == (20, 39)

    def test_the_inner_panels_of_a_picture_are_dropped(self):
        inner = (0.57, 0.62, 0.18, 0.3)
        groups = si.cluster([[BOX, inner] if i >= 20 else [] for i in range(40)])
        assert len(groups) == 2 and groups[0]["box"] == pytest.approx(BOX, abs=1e-6), "largest first"
        picked = si.pick(groups, 40, 4)
        assert picked and picked[0]["box"] == pytest.approx(BOX, abs=1e-6)

    def test_still_versus_moving(self):
        still = np.stack([_frame(inset=BOX, blob_x=100 + 5 * i) for i in range(8)])
        assert si.is_still(still, BOX, 0, 7)
        moving = np.stack([_frame(inset=BOX, pattern_seed=i) for i in range(8)])
        assert not si.is_still(moving, BOX, 0, 7)


class TestPlate:
    def test_feather_fades_the_edges_that_meet_the_frame_and_keeps_the_open_ones(self):
        plate = si.feather(Image.new("RGB", (120, 80), (90, 90, 90)), 10, open_edges=("right", "bottom"))
        a = np.array(plate.getchannel("A"))
        assert a[40, 60] == 255
        assert a[40, 0] < 40 and a[0, 60] < 40            # left and top fade out
        assert a[40, 119] == 255 and a[79, 60] == 255    # right and bottom stay opaque: the frame's border

    def test_box_in_pixels_shrinks_and_grows(self):
        assert si._px((0.5, 0.5, 0.4, 0.4), 1000, 500) == (500, 250, 400, 200)
        x, y, w, h = si._px((0.5, 0.5, 0.4, 0.4), 1000, 500, grow=0.01)
        assert (x, y, w, h) == (490, 240, 420, 220)
        x, y, w, h = si._px((0.6, 0.6, 0.4, 0.4), 1000, 500, grow=0.05)   # clamped to the frame
        assert x + w <= 1000 and y + h <= 500


def _write_video(path, frames, fps=10):
    """Grey frames -> an mp4 through ffmpeg (what the detector reads)."""
    H, W = frames[0].shape
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}",
                          "-r", str(fps), "-i", "-", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "16", path],
                         stdin=subprocess.PIPE)
    p.communicate(b"".join(f.tobytes() for f in frames))
    assert p.returncode == 0


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg needed")
class TestOnAVideo:
    def test_finds_the_picture_hides_it_and_keeps_it(self, tmp_path):
        # 16 s at 10 fps: the person drifts, the picture comes up at 10 s and stays to the end.
        frames = [_frame(blob_x=150 + (i % 40), inset=BOX if i >= 100 else None) for i in range(160)]
        src = str(tmp_path / "src.mp4")
        _write_video(src, frames)
        found = si.detect(src, 4.0, 16.0, pre=4.0)
        assert found, "the picture was not found"
        assert found["corner"] == "bottom-right" and found["witness"] == "onset"
        assert all(abs(a - b) < 0.03 for a, b in zip(found["box"], BOX)), found["box"]
        assert abs(found["t0"] - 6.0) <= 0.5 and abs(found["t1"] - 12.0) <= 0.3
        assert found["plate_at"] < 10.0 <= found["still_at"]
        # The cut: the same seconds as the clip; prepare covers the box and keeps the picture.
        cut = str(tmp_path / "cut.mp4")
        _write_video(cut, frames[40:160])
        name = si.prepare(src, cut, found, str(tmp_path), "clip_1_")
        assert name == "clip_1_inset.jpg" and os.path.exists(tmp_path / name)
        still = Image.open(tmp_path / name)
        assert still.width > still.height
        out = subprocess.run(["ffmpeg", "-v", "error", "-ss", "9.0", "-i", cut, "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "gray", "-"], capture_output=True).stdout
        after = np.frombuffer(out, np.uint8).reshape(360, 640)
        x, y, w, h = BOX
        patch = after[int((y + 0.05) * 360):int((y + h - 0.05) * 360), int((x + 0.05) * 640):int((x + w - 0.05) * 640)]
        assert patch.max() < 200, "the white picture is still visible on the cut"
        assert abs(float(patch.mean()) - 125) < 15, "the wall is not back where the picture was"

    def test_a_video_in_the_corner_is_left_alone(self, tmp_path, capsys):
        frames = [_frame(blob_x=150, inset=BOX if i >= 60 else None, pattern_seed=i) for i in range(120)]
        src = str(tmp_path / "src.mp4")
        _write_video(src, frames)
        assert si.detect(src, 2.0, 12.0, pre=2.0) is None
        assert "A video plays in the bottom-right corner" in capsys.readouterr().out

    def test_the_set_s_own_frame_is_not_an_inset(self, tmp_path):
        frames = [_frame(blob_x=150 + (i % 30), inset=BOX) for i in range(120)]
        src = str(tmp_path / "src.mp4")
        _write_video(src, frames)
        assert si.detect(src, 2.0, 12.0, pre=2.0) is None


def test_switch(monkeypatch):
    monkeypatch.delenv("SCREEN_INSET", raising=False)
    assert si.enabled()
    monkeypatch.setenv("SCREEN_INSET", "0")
    assert not si.enabled()
