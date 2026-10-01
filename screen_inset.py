"""A picture the source itself puts on screen, found and shown whole.

Podcast sets (JRE and the like) show what is being talked about as an inset in
a corner of the wide frame: the producer pulls up an image, it sits bottom-right
for a few seconds, and the conversation goes on. The vertical crop follows the
speaker's face and cuts that inset in half: a white rectangle hangs in the
corner for as long as it is up, and the one picture the clip is about is never
seen (JRE #2515, clip at 733 s, 1-oct-2026: "Brain Cell / The Universe" side by
side, six seconds of half a frame in the corner).

What this finds: an axis-aligned rectangle, anchored to a corner, that COMES UP
(or goes away) during the clip and holds a still picture while it is up. The
set's own frames (posters, a sign, a monitor) are rectangles too, but they are
there the whole time: a box that never comes or goes is not an inset. The
speaker is never one either: a person moves, a picture does not. A video
played in the corner is seen and left alone: a still card would lie about it.

Two things are done with it (main._process_one_clip, before the reframe):

* the box is covered on the horizontal cut with the wall behind it, taken from a
  frame just before it came up (feathered edges), so the crop and the face
  tracker never see it (``prepare``);
* the picture itself is cropped at full resolution and handed to the B-roll as
  a wide card above the speaker's head for as long as the source showed it
  (broll.add_broll / broll.screen_item, item source "screen").

camera_inset is the other case (a webcam with the PERSON in it, on a screen
recording) and screencast_layout wants content across the whole width; neither
sees a picture in a corner.
"""
import json
import os
import shutil
import subprocess
import tempfile

import numpy as np

PRE = 10.0          # s looked at before the clip: a picture already up when the clip starts still shows its wall
FPS = 4             # samples per second
SAMPLE_W = 640      # analysis width
MIN_W, MAX_W = 0.15, 0.60     # of the frame width
MIN_H, MAX_H = 0.15, 0.75     # of the frame height
CORNER = 0.12       # the box's nearest vertical AND horizontal edges are within this of the frame's
FILL = 0.80         # contour area over its bounding box: a rectangle, not an L or a blob
IOU_SAME = 0.85     # two detections of the same box
MIN_DUR = 1.5       # s on screen, at least
MIN_AWAY = 1.0      # s without the box, contiguous, before it came up or after it went away
STATIC_DIFF = 4.0   # mean |diff| (8-bit) between successive samples of the box: a still picture
PLATE_DIFF = 8.0    # the box must differ from the wall it covers by at least this much
PLATE_LEAD = 0.5    # s before the box came up (or after it went) that the wall is taken from
PLATE_MARGIN = 0.012  # of the frame width around the box: the picture's own frame is covered too
STILL_SHRINK = 0.015  # of the box, cut off each side of the still: the inset's border stays in the source


def enabled():
    """SCREEN_INSET=0 turns the whole thing off (on by default: it only acts on a box it has seen come and go)."""
    return os.environ.get("SCREEN_INSET", "1") != "0"


# --- geometry -------------------------------------------------------------------------

def _iou(a, b):
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix = max(0.0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0.0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _inside(small, big, share=0.9):
    """``share`` of ``small`` lies inside ``big``."""
    sx0, sy0, sw, sh = small
    bx0, by0, bw, bh = big
    ix = max(0.0, min(sx0 + sw, bx0 + bw) - max(sx0, bx0))
    iy = max(0.0, min(sy0 + sh, by0 + bh) - max(sy0, by0))
    return ix * iy >= share * sw * sh if sw * sh > 0 else False


def in_corner(box, margin=CORNER):
    """The box hugs one corner: its nearest horizontal edge and its nearest vertical edge are both close to the frame's."""
    x, y, w, h = box
    return min(x, 1.0 - (x + w)) <= margin and min(y, 1.0 - (y + h)) <= margin


def corner_name(box):
    x, y, w, h = box
    return ("top" if y < 1.0 - (y + h) else "bottom") + "-" + ("left" if x < 1.0 - (x + w) else "right")


def rectangles(gray):
    """Corner-anchored rectangles in one grey frame, as (x, y, w, h) fractions of the frame."""
    import cv2
    H, W = gray.shape[:2]
    edges = cv2.Canny(gray, 60, 160)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < W * MIN_W or h < H * MIN_H or w > W * MAX_W or h > H * MAX_H:
            continue
        if cv2.contourArea(c) < FILL * w * h:
            continue
        box = (x / W, y / H, w / W, h / H)
        if in_corner(box):
            out.append(box)
    return out


# --- time -----------------------------------------------------------------------------

def _runs(mask):
    """[(first, last)] of the True stretches of ``mask``."""
    runs, start = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    return runs


def _presence(present, n, gap=1):
    """Boolean mask over ``n`` samples from the set of indices ``present``, holes of ``gap`` samples or fewer filled."""
    mask = np.zeros(n, dtype=bool)
    mask[sorted(present)] = True
    for a, b in zip(_runs(mask), _runs(mask)[1:]):
        if b[0] - a[1] - 1 <= gap:
            mask[a[1]:b[0] + 1] = True
    return mask


def cluster(per_frame):
    """Group the frames' rectangles into boxes seen again and again. ``per_frame``: [[box, ...], ...].
    Returns [{"box": median box, "frames": set of indices}] (largest first)."""
    groups = []
    for i, boxes in enumerate(per_frame):
        for b in boxes:
            for g in groups:
                if _iou(g["box"], b) >= IOU_SAME:
                    g["frames"].add(i)
                    g["all"].append(b)
                    break
            else:
                groups.append({"box": b, "frames": {i}, "all": [b]})
    for g in groups:
        g["box"] = tuple(float(v) for v in np.median(np.array(g["all"]), axis=0))
        del g["all"]
    return sorted(groups, key=lambda g: -g["box"][2] * g["box"][3])


def pick(groups, n, fps=FPS):
    """The one inset among the clusters, or None: on screen at least MIN_DUR s in one stretch, and away
    (no detection) for at least MIN_AWAY s right before it came up or right after it went. Inner panels of a
    kept box (a picture with two halves) are dropped. Returns (group, first, last, witness) with sample
    indices and witness in ("onset", "offset")."""
    kept = []
    for g in groups:
        mask = _presence(g["frames"], n)
        runs = [(a, b) for a, b in _runs(mask) if (b - a + 1) >= MIN_DUR * fps]
        if not runs:
            continue
        a, b = max(runs, key=lambda r: r[1] - r[0])
        away = int(round(MIN_AWAY * fps))
        before = a >= away and not mask[a - away:a].any()
        after = b + away < n and not mask[b + 1:b + 1 + away].any()
        if not (before or after):
            continue
        if any(_inside(g["box"], k[0]["box"]) for k in kept):
            continue
        kept.append((g, a, b, "onset" if before else "offset"))
    return kept[0] if kept else None


# --- frames ---------------------------------------------------------------------------

def probe_size(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height", "-of", "csv=p=0", path], stderr=subprocess.STDOUT,
                                  timeout=60).decode().strip().split(",")
    return int(out[0]), int(out[1])


def sample(path, t_from, t_to, fps=FPS, width=SAMPLE_W):
    """Grey frames of ``path`` between the two times, ``fps`` a second, ``width`` px wide: (frames, height)."""
    sw, sh = probe_size(path)
    height = max(2, int(round(sh * width / sw / 2)) * 2)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t_from):.3f}", "-t", f"{max(0.1, t_to - t_from):.3f}",
           "-i", path, "-vf", f"fps={fps},scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=600).stdout
    n = len(raw) // (width * height)
    if n == 0:
        return np.zeros((0, height, width), dtype=np.uint8), height
    return np.frombuffer(raw[:n * width * height], dtype=np.uint8).reshape(n, height, width), height


def _crop(frame, box):
    H, W = frame.shape[:2]
    x, y, w, h = box
    x0, y0 = int(round(x * W)), int(round(y * H))
    x1, y1 = max(x0 + 1, int(round((x + w) * W))), max(y0 + 1, int(round((y + h) * H)))
    return frame[y0:y1, x0:x1]


def is_still(frames, box, first, last):
    """The box holds a still picture: successive samples barely differ (median mean |diff| <= STATIC_DIFF)."""
    diffs = []
    for i in range(first, last):
        a, b = _crop(frames[i], box).astype(np.int16), _crop(frames[i + 1], box).astype(np.int16)
        if a.shape == b.shape and a.size:
            diffs.append(float(np.abs(a - b).mean()))
    return bool(diffs) and float(np.median(diffs)) <= STATIC_DIFF


def differs_from_wall(frames, box, shown, wall):
    a, b = _crop(frames[shown], box).astype(np.int16), _crop(frames[wall], box).astype(np.int16)
    return a.shape == b.shape and a.size and float(np.abs(a - b).mean()) >= PLATE_DIFF


def detect(source, start, end, pre=PRE, fps=FPS):
    """The picture the source shows in a corner during [start, end] (source seconds), or None.

    {"box": [x, y, w, h] (fractions of the frame), "t0" / "t1": clip seconds it is up (clamped to the clip),
    "corner", "witness": "onset" | "offset", "plate_at": source second the wall behind it is taken from,
    "still_at": source second the picture is cropped at}. Prints one line and returns None for a corner video
    (a moving picture)."""
    t_from = max(0.0, float(start) - pre)
    frames, _h = sample(source, t_from, float(end), fps=fps)
    n = len(frames)
    if n < int(MIN_DUR * fps) + 1:
        return None
    per_frame = [rectangles(f) for f in frames]
    if not any(per_frame):
        return None
    found = pick(cluster(per_frame), n, fps)
    if not found:
        return None
    g, a, b, witness = found
    box = g["box"]
    if not is_still(frames, box, a, b):
        print(f"   ℹ️ A video plays in the {corner_name(box)} corner of the source from "
              f"{t_from + a / fps - start:.1f}s: left as it is (a still card would not be it).")
        return None
    wall = a - int(round(PLATE_LEAD * fps)) if witness == "onset" else b + int(round(PLATE_LEAD * fps))
    wall = min(n - 1, max(0, wall))
    if not differs_from_wall(frames, box, (a + b) // 2, wall):
        return None
    on, off = t_from + a / fps, t_from + (b + 1) / fps
    return {"box": [round(v, 4) for v in box],
            "t0": round(max(0.0, on - float(start)), 2),
            "t1": round(min(float(end) - float(start), off - float(start)), 2),
            "corner": corner_name(box), "witness": witness,
            "plate_at": round(t_from + wall / fps, 2),
            "still_at": round(t_from + (a + b) / 2 / fps, 2)}


# --- what is done with it ---------------------------------------------------------------

def _grab(source, at, out_png, crop=None):
    """One frame of ``source`` at ``at`` s as PNG, optionally cropped (x, y, w, h in px)."""
    vf = [f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}"] if crop else []
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, at):.3f}", "-i", source, "-frames:v", "1",
                    *(["-vf", ",".join(vf)] if vf else []), out_png], check=True, timeout=120)


def _px(box, W, H, shrink=0.0, grow=0.0):
    """The box in pixels, shrunk by ``shrink`` of its own size or grown by ``grow`` of the frame width, inside the frame."""
    x, y, w, h = box
    gx, gy = grow * W, grow * W
    x0, y0 = x * W + shrink * w * W - gx, y * H + shrink * h * H - gy
    x1, y1 = (x + w) * W - shrink * w * W + gx, (y + h) * H - shrink * h * H + gy
    x0, y0 = int(max(0, round(x0))), int(max(0, round(y0)))
    x1, y1 = int(min(W, round(x1))), int(min(H, round(y1)))
    return x0, y0, max(2, x1 - x0), max(2, y1 - y0)


def feather(rgb, feather_px, open_edges=()):
    """RGBA plate: opaque inside, fading to transparent over ``feather_px`` at each edge except the ones in
    ``open_edges`` ("left", "right", "top", "bottom": the frame's own border, nothing to blend into)."""
    from PIL import Image
    w, h = rgb.size
    f = max(1, min(int(feather_px), w // 3, h // 3))
    ramp = np.linspace(0.0, 1.0, f + 2)[1:-1]
    ax = np.ones(w, dtype=np.float32)
    ay = np.ones(h, dtype=np.float32)
    if "left" not in open_edges:
        ax[:f] = np.minimum(ax[:f], ramp[:w])
    if "right" not in open_edges:
        ax[w - f:] = np.minimum(ax[w - f:], ramp[::-1][-w:])
    if "top" not in open_edges:
        ay[:f] = np.minimum(ay[:f], ramp[:h])
    if "bottom" not in open_edges:
        ay[h - f:] = np.minimum(ay[h - f:], ramp[::-1][-h:])
    alpha = (np.outer(ay, ax) * 255).astype(np.uint8)
    out = rgb.convert("RGBA")
    out.putalpha(Image.fromarray(alpha, "L"))
    return out


def prepare(source, cut_path, inset, keep_dir, keep_prefix):
    """Cover the box on the horizontal cut ``cut_path`` (in place) with the wall behind it, and save the picture
    at full resolution as ``<keep_prefix>inset.jpg`` in ``keep_dir``. Returns that file name."""
    from PIL import Image
    from ffmpeg_utils import video_encode_args, QUALITY_FAST
    W, H = probe_size(source)
    cw, ch = probe_size(cut_path)
    tmp = tempfile.mkdtemp(prefix="inset_")
    try:
        # The picture, without the inset's own border.
        still_png = os.path.join(tmp, "still.png")
        _grab(source, inset["still_at"], still_png, _px(inset["box"], W, H, shrink=STILL_SHRINK))
        name = f"{keep_prefix}inset.jpg"
        Image.open(still_png).convert("RGB").save(os.path.join(keep_dir, name), quality=92)
        # The wall, a little larger than the box, feathered where it meets the rest of the frame.
        px, py, pw, ph = _px(inset["box"], W, H, grow=PLATE_MARGIN)
        plate_png = os.path.join(tmp, "plate.png")
        _grab(source, inset["plate_at"], plate_png, (px, py, pw, ph))
        open_edges = tuple(e for e, hit in (("left", px <= 1), ("top", py <= 1), ("right", px + pw >= W - 1),
                                            ("bottom", py + ph >= H - 1)) if hit)
        plate = feather(Image.open(plate_png).convert("RGB"), PLATE_MARGIN * W, open_edges)
        if (cw, ch) != (W, H):
            plate = plate.resize((max(2, int(round(pw * cw / W))), max(2, int(round(ph * ch / H)))), Image.LANCZOS)
            px, py = int(round(px * cw / W)), int(round(py * ch / H))
        plate.save(plate_png)
        lead = 1.0 / FPS
        a, b = max(0.0, float(inset["t0"]) - lead), float(inset["t1"]) + lead
        out = cut_path + ".inset.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", cut_path, "-i", plate_png, "-filter_complex",
               f"[1:v]format=rgba[p];[0:v][p]overlay={px}:{py}:enable='between(t,{a:.3f},{b:.3f})'[v]",
               "-map", "[v]", "-map", "0:a?", *video_encode_args(QUALITY_FAST), "-c:a", "copy",
               "-movflags", "+faststart", out]
        subprocess.run(cmd, check=True, timeout=1800)
        os.replace(out, cut_path)
        return name
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def describe(inset):
    x, y, w, h = inset["box"]
    return (f"a picture {w:.0%} x {h:.0%} of the frame in the {inset['corner']} corner from {inset['t0']:.1f}s "
            f"to {inset['t1']:.1f}s")


if __name__ == "__main__":  # python screen_inset.py <source> <start> <end>
    import sys
    print(json.dumps(detect(sys.argv[1], float(sys.argv[2]), float(sys.argv[3])), indent=1))
