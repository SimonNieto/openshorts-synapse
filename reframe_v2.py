"""Reframe engine v2: analyze in Python, render natively in ffmpeg.

v1 decodes every frame at full resolution in OpenCV, crops/resizes in numpy
and pipes raw frames back into ffmpeg. v2 splits that into:

  1. ANALYSIS — one ffmpeg-decoded pass at <=640px feeding the same detectors
     and the same SmoothedCameraman/SpeakerTracker state machines as v1, so
     the resulting camera trajectory (crop x per frame) is equivalent.
  2. RENDER — one ffmpeg process per scene doing decode -> dynamic crop
     (sendcmd) -> scale -> encode natively (TRACK scenes), or the blurred
     background filtergraph (GENERAL scenes); segments are then concatenated
     with stream copy and the audio mapped straight from the source clip.

No raw-frame piping, no second full-res decode, one less intermediate encode.
Callers must treat any exception as "fall back to the v1 loop".

Pure helpers (sendcmd/concat generation, scene slicing) have no heavy imports
so they stay unit-testable in CI.
"""
import os
import subprocess
import tempfile

import active_speaker
import camera_inset
import punch_in
import screencast_layout
import layout_ranges
import split_layout
from ffmpeg_utils import (video_encode_args, escape_filter_value, QUALITY_FAST,
                          METADATA_SCRUB)

ANALYSIS_MAX_WIDTH = 640


# Short-form platforms (TikTok / Reels / Shorts) expect a 1080-wide vertical
# upload; anything smaller is treated as low quality and re-encoded from the
# already-soft source. The crop region is whatever the source height allows, so
# a 720p input yields a 406x720 crop — we scale that up to the delivery floor
# rather than shipping sub-HD. Sources that already exceed it are left alone
# (never downscale quality the user supplied).
DELIVERY_MIN_WIDTH = 1080


# --- pure helpers (CI-testable) --------------------------------------------

def delivery_size(orig_w, orig_h, aspect_ratio):
    """Output (width, height) for a reframe of this source.

    Picks the largest crop the source allows, then upscales to
    ``DELIVERY_MIN_WIDTH`` if that crop is narrower. Both dimensions come back
    even (x264/NVENC reject odd ones).
    """
    out_h = orig_h
    out_w = int(out_h * aspect_ratio)
    if out_w > orig_w:
        out_w = orig_w
        out_h = int(out_w / aspect_ratio)

    if out_w < DELIVERY_MIN_WIDTH:
        out_w = DELIVERY_MIN_WIDTH
        out_h = int(round(out_w / aspect_ratio))

    return out_w + (out_w % 2), out_h + (out_h % 2)


def source_already_fits(orig_w, orig_h, aspect_ratio, tol=0.01):
    """True when the source is already at (or past) the target aspect.

    Such a source has no width to throw away, so every layout that rearranges
    the frame is a downgrade: GENERAL puts it in a blurred bed, SPLIT stacks
    two crops of an already-narrow frame, SCREENCAST/INSET carve panels out of
    it. TRACK is the only one that leaves it alone — its crop is the whole
    frame — so a vertical upload should pass straight through.
    """
    return orig_w / float(orig_h) <= aspect_ratio * (1 + tol)


def dedupe_sendcmd_lines(xs, fps, target="crop@c"):
    """sendcmd lines setting crop x per frame, deduped to change-points.

    Timestamps are relative to the segment (the render seeks per scene).
    """
    lines = []
    prev = None
    for i, x in enumerate(xs):
        if x != prev:
            lines.append(f"{i / fps:.4f} {target} x {x};")
            prev = x
    return lines


def scene_frame_ranges(scene_boundaries, strategies, total_frames):
    """Clamp scene (start, end) frame ranges to the decoded frame count,
    dropping empty ranges. Each range keeps its strategy so later indices
    can't misalign when a range is dropped."""
    ranges = []
    for i, (start_f, end_f) in enumerate(scene_boundaries):
        strategy = strategies[i] if i < len(strategies) else 'TRACK'
        start_f = max(0, min(start_f, total_frames))
        end_f = max(start_f, min(end_f, total_frames))
        if end_f > start_f:
            ranges.append((start_f, end_f, strategy))
    return ranges


def concat_list_content(segment_paths):
    # Single quotes per concat-demuxer spec; our paths are tempfile-generated
    # (no quotes in them).
    return "".join(f"file '{p}'\n" for p in segment_paths)


# How much of the frame height the real content should fill in GENERAL layout.
#
# Fitting a 16:9 source to the full output width leaves it 608px tall in a
# 1920px frame — the content is 32% of the screen and 68% is blurred filler.
# That reads as a thumbnail floating in soup, and it is what a GENERAL scene
# looked like in real delivered clips (audited 26-jul-2026).
#
# Scaling the content up and letting the sides overflow trades width for
# presence, and the trade has to stay conservative: GENERAL is chosen for group
# shots and landscapes, exactly the material where cropping the sides cuts
# someone out of frame. At 0.42 a 16:9 source keeps ~76% of its width while
# going from 32% to 42% of the frame height. 0.55 was tried and rejected — it
# reaches 55% height but throws away 42% of the width.
#
# GENERAL_CONTENT_HEIGHT_RATIO=0.32 restores the old full-width behaviour.
GENERAL_CONTENT_HEIGHT_RATIO = float(
    os.environ.get("GENERAL_CONTENT_HEIGHT_RATIO", "0.42"))


def full_width_content_height(orig_w, orig_h, out_w):
    """Height the source fills when its FULL width is kept (even)."""
    fg_h = int(round(out_w * orig_h / float(orig_w)))
    return fg_h + (fg_h % 2)


def general_filtergraph(out_w, out_h, content_h=None, orig_w=None, orig_h=None):
    """Blurred-background 'general shot' layout: bg fills the frame (centre-
    cropped, blurred), fg is scaled to a readable share of the height and
    centred, overflowing the sides rather than floating small in the middle.

    ``content_h`` overrides the height ratio. Passing the full-width height
    turns the side-cropping off entirely, which is what a scene full of charts
    or spreadsheets needs: the default 0.42 ratio buys presence by throwing away
    ~24% of the width, and on that material the discarded columns are the point.

    ``orig_w``/``orig_h`` floor the foreground at the height where the source
    fills the output width. The 0.42 ratio buys presence on a LANDSCAPE source
    by overflowing the sides; on a portrait one the same number is a shrink —
    an already-9:16 upload came back as a 453px sliver floating over a blurred
    copy of itself. Filling the width is the floor, never the target.
    """
    fg_h = content_h if content_h else int(out_h * GENERAL_CONTENT_HEIGHT_RATIO)
    if orig_w and orig_h:
        fg_h = max(fg_h, full_width_content_height(orig_w, orig_h, out_w))
    fg_h += fg_h % 2
    return (
        f"[0:v]split=2[bga][fga];"
        f"[bga]scale=-2:{out_h},crop=w=min(iw\\,{out_w}):h={out_h},"
        f"scale={out_w}:{out_h},gblur=sigma=12[bg];"
        # Scale by HEIGHT, then trim any overflow to the output width. crop
        # centres by default, and min() makes it a no-op when the scaled source
        # is already narrower than the frame (portrait/square sources).
        f"[fga]scale=-2:{fg_h},crop=w=min(iw\\,{out_w}):h=ih[fg];"
        f"[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2,setsar=1[v]"
    )


# --- analysis ---------------------------------------------------------------

def apply_crop_overrides(xs, strategies, scene_boundaries, overrides,
                         crop_w, orig_w, orig_h=None, splits=None):
    """Frame the scenes the user positioned by hand.

    ``overrides`` maps a scene index to either

      * a number — the crop CENTRE as a fraction of the source width, giving a
        single locked 9:16 window for that scene; or
      * ``{"top": v, "bottom": v}`` — two centres, stacking those two regions
        one above the other (the SPLIT layout). Each half is either a bare
        fraction (horizontal only) or ``{"x": f, "y": f}``; SPLIT crops are
        SHORTER than the source, so they carry a vertical centre too.

    Fractions travel instead of pixels because the editor knows where it
    dropped the rectangle, not the source's dimensions, and the same number
    survives a source re-encode at another resolution.

    A hand-framed scene overrides its automatic verdict outright: the single
    form forces TRACK so a scene the detector had sent to GENERAL (blurred
    background) comes back to a vertical crop, and the split form writes
    straight into ``splits``, so the user can stack a scene the detector never
    proposed — no dependency on SPLIT_LAYOUT being switched on.

    Runs after every automatic pass, including the ALTERNATE writes, so a
    manual choice always wins. Unknown scene indices and malformed values are
    skipped rather than rejected: a stale editor tab must not fail the render.
    """
    max_x = max(0, orig_w - crop_w)

    def to_x(fraction):
        return max(0, min(int(round(float(fraction) * orig_w - crop_w / 2)), max_x))

    for raw_idx, value in (overrides or {}).items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if not 0 <= idx < len(scene_boundaries):
            continue
        start_f, end_f = scene_boundaries[idx]
        end_f = min(end_f, len(xs))
        if end_f <= start_f:
            continue

        if isinstance(value, dict):
            # Split: the halves are centres in SOURCE PIXELS, which is what
            # split_filtergraph expects — unlike the single-crop path, there is
            # no crop window to offset by.
            # split_geometry reads centre[0]/centre[1]: each half is a POINT,
            # not a horizontal position, because its crop is shorter than the
            # source and has to be placed vertically as well.
            def point(half):
                if isinstance(half, dict):
                    fx, fy = float(half['x']), float(half.get('y', 0.5))
                else:
                    fx, fy = float(half), 0.5
                return (fx * orig_w, fy * orig_h)

            try:
                centres = (point(value['top']), point(value['bottom']))
            except (KeyError, TypeError, ValueError):
                continue
            if splits is None or not orig_h:
                continue
            splits[start_f] = centres
            strategies[idx] = 'SPLIT'
            continue

        try:
            x = to_x(value)
        except (TypeError, ValueError):
            continue
        xs[start_f:end_f] = [x] * (end_f - start_f)
        strategies[idx] = 'TRACK'
        # A scene taken over by a single locked crop must not also carry a
        # stale split recipe from the detector.
        if splits is not None:
            splits.pop(start_f, None)

    return xs, strategies


def _analyze_trajectory(input_video, scenes_boundaries, scene_strategies,
                        fps, orig_w, orig_h, cameraman, tracker):
    """Replays v1's per-frame decision loop on a downscaled ffmpeg-decoded
    stream. Returns xs: crop x per frame (None on GENERAL frames)."""
    import numpy as np
    import main as m

    small_w = min(ANALYSIS_MAX_WIDTH, orig_w)
    if small_w % 2:
        small_w -= 1
    small_h = max(int(orig_h * small_w / orig_w), 2)
    if small_h % 2:
        small_h += 1
    scale = orig_w / small_w
    frame_bytes = small_w * small_h * 3

    proc = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-i", input_video,
         "-vf", f"scale={small_w}:{small_h}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=frame_bytes * 4)

    xs = []
    targets = []   # where the camera WANTS to be (crop x), before its own smoothing
    frame_number = 0
    current_scene_index = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape((small_h, small_w, 3))

            if current_scene_index < len(scenes_boundaries):
                start_f, end_f = scenes_boundaries[current_scene_index]
                if frame_number >= end_f and current_scene_index < len(scenes_boundaries) - 1:
                    current_scene_index += 1

            strategy = (scene_strategies[current_scene_index]
                        if current_scene_index < len(scene_strategies) else 'TRACK')

            # SPLIT, SCREENCAST and WIDE crops are static (fixed boxes for the
            # whole scene), so like GENERAL they need no camera trajectory.
            # ALTERNATE gets one written in after this pass.
            if strategy in ('GENERAL', 'SPLIT', 'SCREENCAST', 'WIDE',
                            'INSET', 'ALTERNATE'):
                cameraman.current_center_x = orig_w / 2
                cameraman.target_center_x = orig_w / 2
                xs.append(None)
                targets.append(None)
            else:
                is_scene_start = (
                    current_scene_index < len(scenes_boundaries)
                    and frame_number == scenes_boundaries[current_scene_index][0])
                cut = is_scene_start and m.SCENE_CUT_RESET
                if cut:
                    # New shot: forget the old subject and cut to the new one
                    # (see SmoothedCameraman.begin_scene).
                    tracker.reset()
                    cameraman.begin_scene()

                if frame_number % m.DETECT_STRIDE == 0 or cut:
                    candidates = m.detect_face_candidates(frame)
                    for cand in candidates:
                        cand['box'] = [int(v * scale) for v in cand['box']]
                        cand['score'] = cand['box'][2] * cand['box'][3]
                    target_box = tracker.get_target(candidates, frame_number, orig_w)
                    if target_box:
                        cameraman.update_target(target_box)
                    elif frame_number % m.YOLO_FALLBACK_STRIDE == 0 or cut:
                        person_box = m.detect_person_yolo(frame)
                        if person_box:
                            cameraman.update_target([int(v * scale) for v in person_box])

                x1, _y1, _x2, _y2 = cameraman.get_crop_box(force_snap=is_scene_start)
                xs.append(x1)
                targets.append(cameraman.target_center_x - cameraman.crop_width / 2)

            frame_number += 1
    finally:
        proc.stdout.close()
        proc.wait()

    return xs, targets


# --- smooth camera (Clip Generator++ option, SMOOTH_CAMERA=1) ---------------------
#
# The v1 cameraman pans at a fixed speed as soon as the face leaves a wide safe
# zone, and a head that bobs around that edge makes it start and stop; far
# moves go at 15 px/frame, a whip. An editor instead holds the frame, and when
# the subject has REALLY moved, glides there once, easing in and out, then
# holds again. calm_path() replays that on the camera's wanted positions.
# Measured on a real JRE clip (28-sep-2026): the guest leaning forward and
# back moved the wanted crop x over 200 px (a third of the crop) and the first
# version answered with five 0.4 s glides back and forth — worse than the old
# camera. A talking head is framed ONCE per shot by an editor: a shot whose
# head stays inside STATIC_BAND of the crop gets one fixed framing, centred on
# where the head goes; only a head that really travels gets (slow) glides.
STATIC_BAND = 0.45         # of the crop width: head travel that still fits a fixed frame
CALM_DEADZONE = 0.20       # of the crop width: closer than this, the frame holds
CALM_CONFIRM_S = 0.8       # the offset must last this long (a lean is not a move)
CALM_GAP_S = 4.0           # at least this long between two moves...
CALM_URGENT = 0.38         # ...unless the face is about to leave the frame
CALM_URGENT_GAP_S = 1.0
SOFT_CUT_S = 0.13          # ~4 frames: the last frame of a shot dissolves into the next


def _smootherstep(u):
    return u * u * u * (u * (u * 6 - 15) + 10)


def calm_path(targets, fps, crop_w, max_x):
    """Crop x per frame for one TRACK scene: one fixed framing when the head's
    travel fits it (the usual talking head); otherwise hold, and one slow eased
    glide (1.2-1.8 s) when the face has settled elsewhere, never twice within
    CALM_GAP_S unless it is leaving the frame."""
    import numpy as np
    n = len(targets)
    if not n:
        return []
    t = [min(max(v, 0), max_x) for v in targets]
    # Where the head spends the shot: the densest STATIC_BAND-wide stretch of
    # its positions. If it holds at least 80 % of the frames, that is the
    # shot — one fixed framing, no camera move; the rest are stray or brief
    # detections (a wide shot of the host opened on a wrong YOLO box for
    # 1 s, 28-sep-2026, and the camera used to start there).
    ts = np.sort(np.asarray(t, dtype=float))
    band, j, best = STATIC_BAND * crop_w, 0, (0, ts[0], ts[0])
    for i in range(n):
        while ts[i] - ts[j] > band:
            j += 1
        if i - j + 1 > best[0]:
            best = (i - j + 1, ts[j], ts[i])
    if best[0] >= 0.8 * n:
        return [int(round((best[1] + best[2]) / 2))] * n

    def settle(i, span):
        window = sorted(t[i:i + max(1, int(span * fps))])
        return window[len(window) // 2]

    dz, confirm = CALM_DEADZONE * crop_w, max(1, int(CALM_CONFIRM_S * fps))
    anchor, out, last_move = settle(0, 0.5), [], -1e9
    i = 0
    while i < n:
        off = abs(t[i] - anchor)
        if off > dz:
            j = i
            while j < n and abs(t[j] - anchor) > dz and j - i < confirm:
                j += 1
            since = (i - last_move) / fps
            urgent = off > CALM_URGENT * crop_w
            if j - i >= confirm and (since >= CALM_GAP_S or (urgent and since >= CALM_URGENT_GAP_S)):
                new = settle(i, 0.8)
                dur = min(1.8, max(1.2, abs(new - anchor) / crop_w * 2.5))
                m = max(2, int(dur * fps))
                for k in range(min(m, n - i)):
                    out.append(anchor + (new - anchor) * _smootherstep((k + 1) / m))
                i += m
                anchor, last_move = new, i
                continue
        out.append(anchor)
        i += 1
    return [int(round(min(max(v, 0), max_x))) for v in out[:n]]


def _people_in_general_scenes(input_video, scene_boundaries, strategies, fps, samples=3):
    """Indexes of GENERAL scenes where the YOLO person detector finds someone
    in most sampled frames (faces too small or turned away still have a body)."""
    import cv2
    import numpy as np
    import main as m
    out = []
    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        return out
    try:
        for idx, (s_f, e_f) in enumerate(scene_boundaries):
            if idx >= len(strategies) or strategies[idx] != 'GENERAL' or e_f - s_f < 2:
                continue
            hits = seen = 0
            for f_idx in np.linspace(s_f, e_f - 1, samples):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(f_idx)))
                ok, frame = cap.read()
                if not ok or frame.mean() < 16:
                    continue
                seen += 1
                if m.detect_person_yolo(frame):
                    hits += 1
            if seen and hits * 2 > seen:
                out.append(idx)
    finally:
        cap.release()
    return out


# --- render -----------------------------------------------------------------

def _run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=1800)


def render(input_video, final_output_video, aspect_ratio, content_ranges=None,
           force_strategy=None, crop_overrides=None):
    """Full v2 reframe of one clip. Raises on failure (caller falls back).

    ``content_ranges`` comes from screencast_layout.detect_content_ranges() on
    the SOURCE video, already translated into this clip's timeline. None or []
    means the layout never triggers, which is the default.

    ``force_strategy`` ('WIDE' / 'TRACK' / any layout the render loop knows)
    applies that layout to EVERY scene, skipping the classifier and the layout
    upgrades — the clip editor's whole-clip framing override.

    ``crop_overrides`` maps scene index -> crop centre as a fraction of the
    source width, for scenes the user framed by hand in the editor. Scenes not
    listed keep the automatic camera, so correcting one bad shot never disturbs
    the ones the tracker got right. Applied AFTER force_strategy: a per-scene
    hand position always beats the whole-clip choice for the scenes it names.
    """
    import main as m
    content_ranges = content_ranges or []

    print("   🚀 Reframe engine v2 (ffmpeg-native render)")
    scenes, fps = m.detect_scenes(input_video)
    fps = float(fps)  # PySceneDetect can hand back a Fraction
    orig_w, orig_h = m.get_video_resolution(input_video)

    out_w, out_h = delivery_size(orig_w, orig_h, aspect_ratio)

    if not scenes:
        import cv2
        cap = cv2.VideoCapture(input_video)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        from scenedetect import FrameTimecode
        scenes = [(FrameTimecode(0, fps), FrameTimecode(total, fps))]

    scene_boundaries = [(s.get_frames(), e.get_frames()) for s, e in scenes]
    # A source shot vertical is already the output: nothing to reframe. The
    # scene classifier still sends its face-less shots (a slide, a chart, a
    # screen recording) to GENERAL, and GENERAL on such a source shrank the
    # whole frame into the middle of a blurred copy of itself. Skip the
    # classifier and every layout upgrade instead of trying to survive them.
    passthrough = source_already_fits(orig_w, orig_h, aspect_ratio)
    if force_strategy:
        strategies = [force_strategy] * len(scenes)
        content_ranges = []  # no screencast/inset upgrades over an explicit choice
        print(f"   🎯 Framing override: every scene -> {force_strategy}")
    elif passthrough:
        strategies = ['TRACK'] * len(scenes)
        content_ranges = []
        print(f"   ↕️  Source is already {orig_w}x{orig_h} vertical — "
              f"passing it through, no reframe")
    else:
        strategies = m.analyze_scenes_strategy(input_video, scenes)

    # SPLIT is an upgrade applied on top of the TRACK/GENERAL verdict, keyed by
    # the scene's START FRAME rather than its index: scene_frame_ranges() drops
    # empty ranges, so indices there don't line up with `scenes`. A surviving
    # range always keeps its original start_f (the clamp only bites on scenes
    # that begin past the last decoded frame, and those get dropped).
    splits = {}
    split_scene_of = {}
    detected_splits = {} if passthrough else split_layout.detect_split_scenes(
        input_video, scenes, strategies)
    for scene_idx, centres in detected_splits.items():
        strategies[scene_idx] = 'SPLIT'
        start_f = scene_boundaries[scene_idx][0]
        splits[start_f] = centres
        split_scene_of[start_f] = scene_idx

    # Geometry alone will stack a scene where one person never speaks. Ask who
    # is actually talking before spending half the frame on the other one.
    alternates = {}
    if splits and active_speaker.ENABLED:
        for start_f in list(splits):
            scene_idx = split_scene_of[start_f]
            end_f = scene_boundaries[scene_idx][1]
            verdicts = active_speaker.verdicts_for_scene(
                input_video, start_f, end_f, fps, splits[start_f])
            if not active_speaker.is_conversation(verdicts):
                a, b = active_speaker.shares(verdicts)
                print(f"   🔇 Scene {scene_idx}: one speaker holds the floor "
                      f"({max(a, b):.0%}) — not stacking")
                del splits[start_f]
                strategies[scene_idx] = 'GENERAL'
            elif active_speaker.CUT_MODE:
                strategies[scene_idx] = 'ALTERNATE'
                alternates[start_f] = (
                    active_speaker.hold(verdicts), splits.pop(start_f))
    if splits:
        print(f"   🪞 SPLIT layout on {len(splits)} scene(s)")
    if alternates:
        print(f"   🎬 Speaker-cut layout on {len(alternates)} scene(s)")

    # SCREENCAST wins over SPLIT on the rare scene that qualifies for both: two
    # faces beside a chart still means the chart is what the shot is about, and
    # stacking the two speakers would crop it away entirely.
    # A screen with a webcam composited into a corner gets its own layout, and
    # the question "is there an inset" is settled geometrically rather than by
    # asking Gemini: offered as a fourth choice it answered "screencast" on all
    # five clips that had one, while camera_inset.detect finds all five with no
    # false positives. The box is fixed for the whole video, so it is found once.
    inset = None
    if content_ranges and screencast_layout.ENABLED:
        try:
            inset = camera_inset.detect(input_video)
        except Exception as e:
            print(f"   ⚠️ Inset check failed ({e}) — using the screen layouts.")
        if inset:
            print(f"   📹 Webcam inset at {inset}")

    screencasts = {}
    wide_count = 0
    inset_count = 0
    if content_ranges:
        for scene_idx, (plan, centre) in screencast_layout.detect_screencast_scenes(
                input_video, scenes, strategies, content_ranges).items():
            # An inset beats both screen plans: it is the only one that can show
            # the screen whole AND the person at a readable size.
            if inset:
                plan, centre = 'INSET', None
            strategies[scene_idx] = plan
            start_f = scene_boundaries[scene_idx][0]
            splits.pop(start_f, None)
            if plan == 'SCREENCAST':
                screencasts[start_f] = centre
            elif plan == 'INSET':
                inset_count += 1
            else:
                wide_count += 1
    if screencasts:
        print(f"   🖥️ SCREENCAST layout on {len(screencasts)} scene(s)")
    if wide_count:
        print(f"   📐 Full-width layout on {wide_count} scene(s)")
    if inset_count:
        print(f"   📹 Camera-inset layout on {inset_count} scene(s)")

    # Smooth camera (Clip Generator++): a GENERAL scene (the whole frame
    # shrunk into a band over a blurred copy of itself) is kept only when
    # nobody is in it. A wide shot of the host whose face the detector misses
    # (small, in profile) came out as a tiny Joe floating in blur (JRE,
    # 28-sep-2026); with a PERSON in the shot it is tracked like any other —
    # the tracker already falls back to the YOLO person box without a face.
    if os.environ.get("SMOOTH_CAMERA", "0") == "1" and not force_strategy and not passthrough:
        tightened = _people_in_general_scenes(input_video, scene_boundaries, strategies, fps)
        for idx in tightened:
            strategies[idx] = 'TRACK'
        if tightened:
            print(f"   🎯 Tight framing on {len(tightened)} wide scene(s) with a person (no blurred band)")

    # The crop geometry comes from the SOURCE dims only — SmoothedCameraman
    # derives crop_width/crop_height from video_width/video_height and never
    # reads the output pair. So out_w/out_h being the (possibly upscaled)
    # delivery size doesn't move the camera; only the final scale= uses it.
    cameraman = m.SmoothedCameraman(out_w, out_h, orig_w, orig_h, aspect_ratio=aspect_ratio)
    tracker = m.SpeakerTracker(cooldown_frames=30)

    xs, targets = _analyze_trajectory(input_video, scene_boundaries, strategies, fps,
                                      orig_w, orig_h, cameraman, tracker)
    if not xs:
        raise RuntimeError("analysis produced no frames")
    smooth = os.environ.get("SMOOTH_CAMERA", "0") == "1"
    if smooth:
        max_x = max(0, orig_w - cameraman.crop_width)
        calmed = 0
        for idx, (s_f, e_f) in enumerate(scene_boundaries):
            e_f = min(e_f, len(xs))
            if idx < len(strategies) and strategies[idx] == 'TRACK' and e_f > s_f:
                seg = targets[s_f:e_f]
                if all(v is not None for v in seg):
                    xs[s_f:e_f] = calm_path(seg, fps, cameraman.crop_width, max_x)
                    calmed += 1
        print(f"   🎥 Smooth camera on {calmed} scene(s), soft cuts between shots")

    # Beats are found once per clip; each scene takes the ones inside it.
    beats = []
    if punch_in.ENABLED:
        beats = punch_in.emphasis_times(input_video, len(xs) / fps)
        if beats:
            print(f"   🔍 Punch-in on {len(beats)} beat(s)")

    crop_w, crop_h = cameraman.crop_width, cameraman.crop_height

    # ALTERNATE renders through the TRACK path: hard cuts between two speakers
    # are still just a list of crop x values, so no new filtergraph is needed.
    # The trajectory is written here because the analysis pass deliberately
    # skips these scenes rather than tracking a face through them.
    for start_f, (held, centres) in alternates.items():
        end_f = scene_boundaries[split_scene_of[start_f]][1]
        end_f = min(end_f, len(xs))
        if end_f <= start_f:
            continue
        xs[start_f:end_f] = active_speaker.speaker_xs(
            held, centres, crop_w, orig_w, end_f - start_f, fps)

    # Last word on the trajectory: a scene the user framed by hand beats every
    # automatic verdict above, including the ALTERNATE writes.
    if crop_overrides:
        xs, strategies = apply_crop_overrides(
            xs, strategies, scene_boundaries, crop_overrides, crop_w,
            orig_w, orig_h=orig_h, splits=splits)
        print(f"   ✋ Manual framing on {len(crop_overrides)} scene(s)")

    ranges = scene_frame_ranges(scene_boundaries, strategies, len(xs))
    if not ranges:
        raise RuntimeError("no usable scene ranges")
    workdir = tempfile.mkdtemp(prefix="reframe_v2_")
    segments = []
    try:
        for idx, (start_f, end_f, strategy) in enumerate(ranges):
            seg_path = os.path.join(workdir, f"seg_{idx:03d}.mp4")
            ss = start_f / fps
            dur = (end_f - start_f) / fps

            if strategy == 'INSET':
                graph = camera_inset.inset_filtergraph(
                    orig_w, orig_h, out_w, out_h, inset)
            elif strategy == 'SCREENCAST':
                graph = screencast_layout.screencast_filtergraph(
                    orig_w, orig_h, out_w, out_h, screencasts[start_f])
            elif strategy == 'WIDE':
                graph = general_filtergraph(
                    out_w, out_h,
                    full_width_content_height(orig_w, orig_h, out_w))
            elif strategy == 'SPLIT':
                left, right = splits[start_f]
                graph = split_layout.split_filtergraph(
                    orig_w, orig_h, out_w, out_h, left, right)
            elif strategy == 'GENERAL':
                graph = general_filtergraph(out_w, out_h,
                                            orig_w=orig_w, orig_h=orig_h)
            else:
                seg_xs = [x if x is not None else 0 for x in xs[start_f:end_f]]
                cmd_path = os.path.join(workdir, f"cmd_{idx:03d}.txt")
                if beats:
                    zooms = punch_in.zoom_curve(len(seg_xs), fps, beats,
                                                start_offset=ss)
                    boxes = punch_in.crop_boxes(seg_xs, zooms, crop_w, crop_h,
                                                orig_w, orig_h)
                    lines = punch_in.sendcmd_lines(boxes, fps)
                    first = boxes[0]
                    init = f"w={first[0]}:h={first[1]}:x={first[2]}:y={first[3]}"
                else:
                    lines = dedupe_sendcmd_lines(seg_xs, fps)
                    # sendcmd only ever moves x, so y is whatever it starts as.
                    # crop_h equals the source height on any landscape input,
                    # making this 0; it only bites on a source TALLER than the
                    # target, where y=0 threw away the bottom of the frame
                    # instead of trimming both ends.
                    crop_y = max(0, (orig_h - crop_h) // 2)
                    init = f"w={crop_w}:h={crop_h}:x={seg_xs[0]}:y={crop_y}"
                with open(cmd_path, "w") as f:
                    f.write("\n".join(lines) + "\n")
                graph = (
                    f"[0:v]sendcmd=f='{escape_filter_value(cmd_path)}',"
                    f"crop@c={init},"
                    f"scale={out_w}:{out_h},setsar=1[v]"
                )

            extra_in = []
            if smooth and segments and dur > SOFT_CUT_S * 2:
                # Soft cut: the previous shot's last frame dissolves into this
                # one over ~4 frames. The source cuts hard, so there is no
                # "after" for the old shot; holding its last frame for 0.13 s
                # reads as a dissolve and keeps the timeline — and the sound —
                # exactly where they were.
                last_png = os.path.join(workdir, f"last_{idx:03d}.png")
                try:
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.3", "-i", segments[-1],
                                    "-update", "1", last_png], check=True, timeout=120)
                    k = graph.rfind("[v]")
                    graph = (graph[:k] + "[vm]" + graph[k + 3:]
                             + f";[1:v]scale={out_w}:{out_h},format=rgba,"
                               f"fade=t=out:st=0:d={SOFT_CUT_S}:alpha=1[fo];"
                               f"[vm][fo]overlay=0:0:eof_action=pass,format=yuv420p[v]")
                    extra_in = ["-loop", "1", "-framerate", f"{fps:.3f}", "-t", f"{SOFT_CUT_S + 0.05:.2f}",
                                "-i", last_png]
                except Exception as e:
                    print(f"   ⚠️ Soft cut skipped at scene {idx} ({e})")

            _run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{ss:.4f}", "-t", f"{dur:.4f}", "-i", input_video, *extra_in,
                "-filter_complex", graph, "-map", "[v]",
                *video_encode_args(QUALITY_FAST), "-an", seg_path,
            ])
            segments.append(seg_path)

        list_path = os.path.join(workdir, "concat.txt")
        with open(list_path, "w") as f:
            f.write(concat_list_content(segments))

        # Concat video segments (stream copy) + audio straight from the clip.
        _run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-i", input_video,
            "-map", "0:v:0", "-map", "1:a:0?",
            "-c:v", "copy", "-c:a", "copy", *METADATA_SCRUB,
            # +faststart moves the moov atom to the front so the browser <video>
            # can start playing before the whole file downloads. Without it the
            # in-app preview spins forever (download still works) — the moov
            # lands at the end of a plain concat.
            "-movflags", "+faststart",
            final_output_video,
        ])
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)

    # Tell the caption pass which stretches are stacked (see layout_ranges).
    layout_ranges.write(final_output_video,
                        [(s / fps, e / fps, strategy) for s, e, strategy in ranges])
    print(f"   ✅ Clip saved to {final_output_video}")
    return True
