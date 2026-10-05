"""Punch-in: a short push toward the subject on the beats that carry the clip.

Not a layout. Every other mode here decides WHERE the frame sits; this one
decides when it moves in, which is the difference between a clip that reads as
footage and one that reads as edited. A static crop for 45 seconds is the single
most "unedited" thing a vertical clip can do.

The push is deliberately small. Anything past ~15% starts cropping the speaker's
head on a face-framed shot, and on an upscaled source it also starts showing.
The curve is asymmetric on purpose: fast in, hold, slow out, which is how a
human operator does it and how it reads as intent rather than drift.

It rides the TRACK path, widening the existing per-frame crop command from
x-only to w/h/x/y, so it composes with the camera trajectory instead of fighting
it. Off by default (``PUNCH_IN=1``).

Beat times come from the audio envelope. The transcript would be a better
source (punch on the hook word, not on the loudest syllable), and render() has
no transcript today — ``emphasis_times`` is a plain list of seconds, so wiring
main.py's word timings in later needs no change here.

Since 5-oct-2026 the module also holds the TIGHT FRAME (bottom of the file),
which is what Clip Generator++ uses; the animated push above stays off. The
user's decision 4: past 6 s without a change on screen, a dry cut to a frame
about 1.2x tighter for 2-3 s on the strong phrase, then back. No zoom, no
movement: a change of shot, as between two cameras. The same switch, on the
very frame of a join, hides the montage's joins that would show as a jumping
head (montage.py, the user's reservation 9).
"""
import math
import os
import re

import numpy as np

ENABLED = os.environ.get("PUNCH_IN", "0") == "1"

# Peak zoom. 1.12 crops 11% off each dimension: visible as intent, still short
# of cutting into a head framed by the TRACK crop.
MAX_ZOOM = float(os.environ.get("PUNCH_IN_ZOOM", "1.12"))

# Envelope, in seconds: snap in, sit there, drift out.
RISE_SECONDS = 0.25
HOLD_SECONDS = 1.30
FALL_SECONDS = 0.55

# Never punch twice inside this window. Two pushes in quick succession read as a
# glitch, and the second one lands before the first has released.
#
# Audio-envelope resolution used to find beats.
BEAT_WINDOW = 0.2

# A beat must exceed the clip's median loudness by this much of the gap to its
# peak. Low values punch on every syllable; this keeps it to real emphasis.
#
# These two were shipped at 4.0/0.45 and that produced 8.4 punches per minute of
# clip, one every seven seconds. That is not a push on the beat, it is a twitch.
# Swept over 20 corpus clips (31-jul-2026), punches per minute, median and max:
#
#   gap  prom    median  max          gap  prom    median  max
#   4.0  0.45       8.4  11.8        12.0  0.60       2.9   4.6
#   4.0  0.75       2.4   5.8        18.0  0.45       2.9   3.9
#   8.0  0.60       3.4   5.9        18.0  0.60       2.8   3.0
#
# 18.0/0.60 is picked for having the tightest spread, not just the right median:
# a setting whose worst case is 3.0/min never surprises anyone, while 12.0/0.60
# has the same median but can still reach 4.6 on a loud clip. No setting left a
# clip with zero punches.
MIN_GAP_SECONDS = 18.0
BEAT_PROMINENCE = 0.60


def _ease(t):
    """Smoothstep on [0, 1]. Linear ramps look mechanical at this duration."""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def zoom_curve(n_frames, fps, emphasis_times, max_zoom=None,
               start_offset=0.0):
    """Per-frame zoom factor (1.0 = untouched) for one scene.

    ``emphasis_times`` are absolute seconds; ``start_offset`` is where this
    scene begins, so callers can pass clip-level beats unchanged.
    """
    max_zoom = MAX_ZOOM if max_zoom is None else max_zoom
    zooms = [1.0] * max(0, n_frames)
    if not zooms or max_zoom <= 1.0:
        return zooms

    span = RISE_SECONDS + HOLD_SECONDS + FALL_SECONDS
    for t in emphasis_times:
        local = t - start_offset
        if local <= -span or local >= n_frames / fps:
            continue
        for f in range(max(0, int(local * fps)),
                       min(n_frames, int((local + span) * fps) + 1)):
            dt = f / fps - local
            if dt < 0:
                continue
            if dt < RISE_SECONDS:
                amount = _ease(dt / RISE_SECONDS)
            elif dt < RISE_SECONDS + HOLD_SECONDS:
                amount = 1.0
            elif dt < span:
                amount = 1.0 - _ease(
                    (dt - RISE_SECONDS - HOLD_SECONDS) / FALL_SECONDS)
            else:
                continue
            # Overlapping pushes take the strongest rather than compounding.
            zooms[f] = max(zooms[f], 1.0 + (max_zoom - 1.0) * amount)
    return zooms


def crop_boxes(xs, zooms, crop_w, crop_h, orig_w, orig_h):
    """Per-frame (w, h, x, y), zooming about the tracked crop's own centre.

    Keeping the centre fixed is what makes this a push rather than a pan: the
    subject stays put and the frame closes in around them.
    """
    boxes = []
    for i, x in enumerate(xs):
        z = zooms[i] if i < len(zooms) else 1.0
        w = int(crop_w / z)
        h = int(crop_h / z)
        w -= w % 2
        h -= h % 2
        w = max(2, min(w, orig_w))
        h = max(2, min(h, orig_h))

        cx = x + crop_w / 2.0
        cy = crop_h / 2.0
        nx = int(round(cx - w / 2.0))
        ny = int(round(cy - h / 2.0))
        nx = max(0, min(nx, orig_w - w))
        ny = max(0, min(ny, orig_h - h))
        boxes.append((w, h, nx - (nx % 2), ny - (ny % 2)))
    return boxes


def sendcmd_lines(boxes, fps, target="crop@c"):
    """sendcmd lines for per-frame w/h/x/y, deduped to change-points.

    Same contract as reframe_v2.dedupe_sendcmd_lines, but four parameters: at
    30fps a 45s clip is 1350 frames and writing every parameter every frame
    makes a command file large enough to slow the filter down.
    """
    lines = []
    prev = None
    for i, box in enumerate(boxes):
        if box == prev:
            continue
        t = i / fps
        w, h, x, y = box
        pw, ph, px, py = prev if prev else (None, None, None, None)
        if w != pw:
            lines.append(f"{t:.4f} {target} w {w};")
        if h != ph:
            lines.append(f"{t:.4f} {target} h {h};")
        if x != px:
            lines.append(f"{t:.4f} {target} x {x};")
        if y != py:
            lines.append(f"{t:.4f} {target} y {y};")
        prev = box
    return lines


def emphasis_times(video_path, duration, window=BEAT_WINDOW,
                   min_gap=MIN_GAP_SECONDS, prominence=BEAT_PROMINENCE):
    """Seconds where the audio leaps above its own baseline.

    A stand-in for the hook words until the transcript is wired through. Returns
    [] for silent or unreadable audio, which simply means no punches.
    """
    import active_speaker

    envelope = active_speaker.audio_envelope(video_path, 0.0, duration,
                                             window_s=window)
    if not envelope:
        return []

    values = np.asarray(envelope, dtype=float)
    baseline = float(np.median(values))
    peak = float(values.max())
    if peak - baseline <= 1e-6:
        return []

    threshold = baseline + (peak - baseline) * prominence
    times = []
    last = -1e9
    for i, v in enumerate(values):
        t = i * window
        if v >= threshold and t - last >= min_gap:
            times.append(round(t, 3))
            last = t
    return times


# --- the tight frame (Clip Generator++, 5-oct-2026) ------------------------------------------------
# A change of shot, not a push: the frame cuts to TIGHT_ZOOM x tighter about the face and cuts back,
# nothing moves in between (the user's rule: fixed camera, no animated zoom). Applied on the finished
# picture (after the B-roll, before the hook and the captions), where every other change of the clip is
# known: the source's camera cuts, the reactions, the pictures, the joins of the montage.
TIGHT_ZOOM = 1.20       # on a 1080p source (1.3 shows the upscale; the image study's mock-up, 4-oct-2026)
TIGHT_ZOOM_HI = 1.30    # from 1440p up
TIGHT_DUR = 2.5         # s a tight frame lasts (2-3 s, the strong phrase)...
TIGHT_MIN, TIGHT_MAX = 2.0, 3.0   # ...ending on a word
STATIC_MAX = 6.0        # s on screen without a change before a tight frame comes in (decision 4)
MIN_CHANGE_GAP = 4.0    # s between the starts of two changes: never a flicker
MIN_REST = 2.0          # s between the end of a change and the start of the next
HIDE_PAIR = (1.5, 4.5)  # two joins to hide this far apart share one tight frame (in on one, out on the other)
CHANGE_DIFF = 8.0       # mean |diff| of 32x18 grey thumbnails, frame to frame: the picture changed (montage.SHOT_DIFF)
CHANGE_FPS = 30


def tight_zoom(source_height):
    return TIGHT_ZOOM_HI if source_height >= 1440 else TIGHT_ZOOM


def spaced(a, b, others):
    """A change over [a, b] keeps its distance to every other change (c, d): MIN_REST from its end to the
    next one's start, MIN_CHANGE_GAP between two starts, no overlap."""
    for c, d in others:
        if d <= a + 1e-6 and c <= a + 1e-6:
            if a - d < MIN_REST - 1e-6 or a - c < MIN_CHANGE_GAP - 1e-6:
                return False
        elif c >= b - 1e-6:
            if c - b < MIN_REST - 1e-6 or c - a < MIN_CHANGE_GAP - 1e-6:
                return False
        else:
            return False
    return True


def schedule_hides(joins, duration, events=()):
    """A tight frame for every join to hide (``joins``: clip seconds, sorted), its switch on the join's
    very frame: [join, join + TIGHT_DUR], else [join - TIGHT_DUR, join], or one frame from a join to the
    next when they are HIDE_PAIR apart. ``events``: the other changes already known ((in, out); a camera
    cut is (t, t)). Returns (windows [(a, b)], indices of the joins no window could hide)."""
    windows, refused, covered = [], [], set()
    joins = [float(t) for t in joins]
    for n, t in enumerate(joins):
        if n in covered:
            continue
        cands = []
        if n + 1 < len(joins) and HIDE_PAIR[0] <= joins[n + 1] - t <= HIDE_PAIR[1]:
            cands.append(((t, joins[n + 1]), {n, n + 1}))
        cands += [((t, t + TIGHT_DUR), {n}), ((t - TIGHT_DUR, t), {n})]
        for (a, b), who in cands:
            if a < -1e-6 or b > duration + 1e-6:
                continue
            if any(a + 1e-6 < u < b - 1e-6 for m, u in enumerate(joins) if m not in who and m not in covered):
                continue            # another join to hide would sit inside the tight frame, not on its edge
            if not spaced(a, b, list(events) + windows):
                continue
            windows.append((round(max(0.0, a), 4), round(min(duration, b), 4)))
            covered |= who
            break
        else:
            refused.append(n)
    return sorted(windows), refused


def _sentence_starts(words):
    out = set()
    for k, w in enumerate(words):
        if k == 0 or re.search(r"[.!?]$", words[k - 1]["text"].strip()) or w["start"] - words[k - 1]["end"] >= 0.3:
            out.add(k)
    return out


def plan_tight(duration, changes, words=(), punch=None, hook_end=None):
    """Tight frames for the stretches that run past STATIC_MAX s without a change on screen.

    ``changes``: (in, out) of every change in clip seconds (camera cuts, reactions, pictures, the joins'
    tight frames); ``words``: the clip's words ({"text", "start", "end"}, clip seconds) — a tight frame
    starts on a sentence that carries strong words (viral_fx.keyword_score) and ends on a word;
    ``punch``: (start, end) of the punchline: in its stretch the tight frame goes on it; ``hook_end``: the
    hook's title leaving the screen, a change too. Returns [(a, b)], never within MIN_REST / MIN_CHANGE_GAP
    of another change, never past the clip's end (the clip may end on one)."""
    from viral_fx import keyword_score
    evs = sorted([(float(a), float(b)) for a, b in changes] + ([(hook_end, hook_end)] if hook_end else []))
    words = list(words or [])
    starts = _sentence_starts(words)
    out = []
    prev_out = 0.0
    for nxt in evs + [None]:
        g0, g1 = prev_out, (nxt[0] if nxt else duration)
        if nxt:
            prev_out = max(prev_out, nxt[1])
        length = g1 - g0
        if length <= STATIC_MAX:
            continue
        n = int(math.ceil((length - STATIC_MAX) / (STATIC_MAX + TIGHT_DUR)))
        for k in range(n):
            ideal = g0 + (k + 1) * length / (n + 1) - TIGHT_DUR / 2
            last_ok = (g1 if nxt is None else g1 - MIN_REST) - TIGHT_MIN
            lo = g0 + (MIN_REST if g0 > 0 else 0.5)
            # On a word that opens a phrase first; anywhere in the stretch (every quarter second) else.
            cands = [(words[i]["start"] - 0.05, i) for i, w in enumerate(words) if lo <= w["start"] - 0.05 <= last_ok]
            steps = int(max(0.0, last_ok - lo) / 0.25)
            cands += [(lo + 0.25 * s, None) for s in range(steps + 1)]
            best = None
            for a, i in cands:
                ends = [w["end"] for w in words if a + TIGHT_MIN <= w["end"] <= a + TIGHT_MAX]
                b = min(ends, key=lambda e: abs(e - (a + TIGHT_DUR))) if ends else a + TIGHT_DUR
                if nxt is None:
                    b = min(b, duration)
                if b - a < TIGHT_MIN - 1e-6 or not spaced(a, b, evs + out):
                    continue
                score = -0.4 * abs(a - ideal)
                if i is not None:
                    score += max([keyword_score(w["text"]) for w in words if a <= w["start"] < b] or [0.0])
                    score += 0.8 if i in starts else 0.0
                if punch and abs(a - (punch[0] - 0.05)) < 0.3:
                    score += 3.0
                if best is None or score > best[0]:
                    best = (score, a, b)
            if best:
                out.append((round(best[1], 3), round(best[2], 3)))
    return sorted(out)


def changes_on_screen(clip_path, fps=CHANGE_FPS):
    """Where the finished picture changes (a camera cut, a reaction or a picture coming or going), as
    (t, t), from grey thumbnails at ``fps``."""
    import subprocess
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", clip_path, "-an", "-vf",
                          f"fps={fps},scale=32:18:flags=area,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, timeout=600).stdout
    n = len(raw) // 576
    th = [np.frombuffer(raw[i * 576:(i + 1) * 576], dtype=np.uint8).astype("float32") for i in range(n)]
    return [(round(i / fps, 2), round(i / fps, 2)) for i in range(1, n)
            if float(np.mean(np.abs(th[i] - th[i - 1]))) > CHANGE_DIFF]


def _probe(clip_path):
    import subprocess
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate", "-of", "csv=p=0", clip_path],
                         capture_output=True, text=True, timeout=60).stdout.strip().split("\n")[0].split(",")
    num, den = (out[2] if len(out) > 2 else "30/1").split("/")
    return int(out[0]), int(out[1]), (float(num) / float(den or 1)) or 30.0


def face_in(clip_path, a, b):
    """The face (x, y, w, h in the clip's pixels) over [a, b] of a finished clip: the median of three
    looks, or None when no face is seen (a back, a profile)."""
    import subprocess
    import montage
    W, H, _ = _probe(clip_path)
    boxes = []
    for t in (a + 0.2, (a + b) / 2, b - 0.2):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", clip_path, "-frames:v", "1",
                              "-vf", "scale=540:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, timeout=120).stdout
        h = len(raw) // (540 * 3)
        if h <= 0:
            continue
        box = montage._face_box(np.frombuffer(raw[:540 * h * 3], dtype=np.uint8).reshape(h, 540, 3))
        if box:
            k = W / 540.0
            boxes.append(tuple(v * k for v in box))
    if not boxes:
        return None
    return tuple(float(np.median([bx[i] for bx in boxes])) for i in range(4))


def tight_box(W, H, face, zoom):
    """(w, h, x, y) of the tight frame in a W x H picture: ``zoom`` x closer about the face, which keeps
    its place in the frame (the framing's composition holds); about the upper middle without a face."""
    w, h = int(W / zoom) // 2 * 2, int(H / zoom) // 2 * 2
    cx, cy = ((face[0] + face[2] / 2.0, face[1] + face[3] / 2.0) if face else (W / 2.0, H * 0.42))
    x = int(min(max(cx * (1.0 - 1.0 / zoom), 0), W - w)) // 2 * 2
    y = int(min(max(cy * (1.0 - 1.0 / zoom), 0), H - h)) // 2 * 2
    return w, h, x, y


def tight_graph(windows, fps, W, H):
    """The filtergraph of the tight frames: the picture and its tight version side by side, the tight one
    shown over each window, from the window's first frame to its last (half a frame early on the clock, so
    each cut lands on its very frame). The crop's size is the same for every window (one zoom a clip) and
    only its place changes between windows: a crop whose size changes mid-stream (sendcmd) crashes ffmpeg
    7.1 (measured, 5-oct-2026). Both branches see every frame, so nothing waits in a queue."""
    wins = sorted(windows, key=lambda w: w["a"])
    half = 0.5 / fps
    cw, ch = wins[0]["box"][0], wins[0]["box"][1]
    spans = [(max(0.0, w["a"] - half), max(0.0, w["b"] - half)) for w in wins]
    x_expr, y_expr = "0", "0"
    for (a, b), w in reversed(list(zip(spans, wins))):
        x_expr = f"if(between(t,{a:.4f},{b:.4f}),{w['box'][2]},{x_expr})"
        y_expr = f"if(between(t,{a:.4f},{b:.4f}),{w['box'][3]},{y_expr})"
    enable = "+".join(f"between(t,{a:.4f},{b:.4f})" for a, b in spans)
    return (f"[0:v]split[base][z];[z]crop=w={cw}:h={ch}:x='{x_expr}':y='{y_expr}',"
            f"scale={W}:{H}:flags=lanczos,setsar=1[t];"
            f"[base][t]overlay=0:0:enable='{enable}',format=yuv420p[v]")


def _clip_duration(clip_path):
    import subprocess
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", clip_path],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def finish(clip_path, out_path, clip, words=(), montage_report=None, hook_end=None, source_height=1080, log=print):
    """Cut the tight frames into a finished clip (after the B-roll, before the hook and the captions):
    the ones hiding the montage's joins (``montage_report["hide_windows"]``, unless a picture or a
    reaction already covers the join) and one in every stretch past STATIC_MAX without a change.
    Returns the windows cut in [{"a", "b", "box", "why"}]; nothing is written when there is none."""
    rep = montage_report or {}
    W, H, _fps = _probe(clip_path)
    duration = _clip_duration(clip_path)
    pictures = [(float(it["t"]), float(it["t"]) + float(it.get("dur") or 0)) for it in (clip.get("broll") or [])
                if isinstance(it, dict) and it.get("t") is not None and not clip.get("broll_pending")]
    reacts = [(float(r["at"]), float(r["at"]) + float(r.get("dur") or 1.2)) for r in (clip.get("reactions") or [])]
    covers = pictures + reacts
    hide_joins = [j["t"] for j in rep.get("joins") or [] if j.get("verdict") == "hide"]

    def covered(t):
        return any(a - 0.05 <= t <= b + 0.05 for a, b in covers)

    windows = []
    for a, b in rep.get("hide_windows") or []:
        edges = [t for t in hide_joins if abs(t - a) < 1e-3 or abs(t - b) < 1e-3]
        if edges and all(covered(t) for t in edges):
            continue                    # a picture or a reaction already hides the join
        at_a = any(abs(t - a) < 1e-3 for t in edges)
        at_b = any(abs(t - b) < 1e-3 for t in edges)
        for c, d in covers:             # a picture over the tight frame (not over its join) cuts it short
            if c < b and a < d:
                if at_a and not at_b and c > a:
                    b = min(b, c)
                elif at_b and not at_a and d < b:
                    a = max(a, d)
        if b - a > 0.3:
            windows.append({"a": round(a, 4), "b": round(b, 4), "why": "join"})
    known = covers + [(w["a"], w["b"]) for w in windows]
    # What the picture shows changing that is not one of those (the source's camera cuts): the edges of a
    # reaction or a picture are seen too, and must not count as changes of their own.
    seen = [s for s in changes_on_screen(clip_path) if not any(a - 0.3 <= s[0] <= b + 0.3 for a, b in known)]
    changes = known + seen
    for a, b in plan_tight(duration, changes, words, punch=rep.get("punch"), hook_end=hook_end):
        windows.append({"a": a, "b": b, "why": "static"})
    if not windows:
        return []
    zoom = tight_zoom(source_height)
    for w in windows:
        w["box"] = tight_box(W, H, face_in(clip_path, w["a"], w["b"]), zoom)
    apply_tight(clip_path, out_path, windows)
    log(f"   🎥 Tight frames (x{zoom:.2f}): " + ", ".join(f"{w['a']:.1f}-{w['b']:.1f}s ({w['why']})" for w in windows))
    return windows


def apply_tight(clip_path, out_path, windows):
    """Write ``clip_path`` with the tight frames cut in: ``windows`` [{"a", "b", "box": (w, h, x, y)}] in
    clip seconds. One pass, the sound copied."""
    import subprocess
    from ffmpeg_utils import layer_encode_args
    W, H, fps = _probe(clip_path)
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip_path, "-filter_complex",
                        tight_graph(windows, fps, W, H), "-map", "[v]", "-map", "0:a?",
                        *layer_encode_args(["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]),
                        "-c:a", "copy", "-movflags", "+faststart", out_path],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg exit {r.returncode}: {r.stderr[-600:]}")
    return out_path
