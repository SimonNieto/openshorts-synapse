"""Premium framing of a tracked person: how an editor frames a talking head.

reframe v2 follows the biggest face with a "heavy tripod" camera, then
calm_path turned that into one fixed framing per shot. Measured on JRE #2515
(1-oct-2026, clip at 733 s), that framing had three faults an editor never
makes:

* the face sat at 55-60 % of the width with its nose a few pixels from the
  edge whenever the host leaned to the mic — the fixed-framing rule counted
  head TRAVEL (45 % of the crop) but not head WIDTH (the head was 55 % of the
  crop wide), so "fits in one framing" was true of the head's centre and false
  of the head;
* the centre was the low edge of the densest band, not its middle: a bias of
  up to a quarter of the band, always to the same side;
* a face turned three-quarters to the right was framed with the empty space
  BEHIND it. Editors leave the room in front of a face (look-room), and put
  the eyes on the upper third, not the chin on the captions.

So, per TRACK shot, from the tracked head (centre, size, yaw) frame by frame:

1. ONE FIXED FRAMING when the head's travel plus its width plus two margins
   fits the crop: centred on the travel, shifted by LOOK_ROOM away from where
   the face looks, and never letting the head within MARGIN_X of an edge.
2. Otherwise HOLD and GLIDE: the frame holds while the head stays in its
   comfortable zone; when the head has settled elsewhere (CONFIRM_S), or is
   about to leave the frame (URGENT_S), one eased glide of 1.2-1.8 s, then
   hold again, never two glides within GAP_S unless urgent.
3. EYE LINE by a bounded punch-in: a face sitting low in the source (its
   centre under EYE_LINE[1] of the height) or too small (under FACE_MIN of the
   height) gets the crop tightened up to ZOOM_MAX and placed so the face
   centre lands at EYE_TARGET with HEADROOM above the crown. Fixed for the
   shot: a vertical move reads as a tilt, and nobody tilts on a talking head.

The output is one crop box per frame (w, h, x, y), the format punch_in's
sendcmd already renders, so a beat punch-in composes on top (with_zoom).
"""
import math

import numpy as np

MARGIN_X = 0.06          # of the crop width kept free on each side of the head
HEAD_W = 1.20            # head width over the face box width: MediaPipe's full-range box spans the head itself
                         # (measured 333 px on a 334 px head, JRE 1-oct-2026); the rest is hair and headphones
SLACK = 0.03             # of the crop width: a travel this far past "fits" still gets one framing, not glides
EDGE = 0.02              # of the crop width: closer than this to an edge, the head is leaving the frame
HEAD_ABOVE = 0.45        # of the face box height above the box: brow to crown
HEAD_BELOW = 0.15        # under the box: the chin
LOOK_ROOM = 0.06         # of the crop width: the face sits this far off centre, away from where it looks
LOOK_YAW = 0.08          # |yaw| (nose offset over face width) from which a face reads as turned
EYE_LINE = (0.36, 0.48)  # face-centre band (of the crop height) that needs no punch-in
EYE_TARGET = 0.44        # where the face centre goes when the crop is re-placed
HEADROOM = 0.05          # of the crop height above the crown, at least
FACE_MIN = 0.17          # a face box shorter than this (of the crop height) earns a punch-in
ZOOM_MAX = 1.15          # on a 1080p source: the HQ chain still hides a 2x upscale, not more
ZOOM_MAX_HI = 1.35       # from 1440p up
SMOOTH_S = 0.5           # median window on the observations: detector jitter is not a move
CONFIRM_S = 0.8          # a new position must last this long (a lean is not a move)
GAP_S = 4.0              # between two glides...
URGENT_S = 0.3           # ...unless the head is leaving the frame: then this long
GLIDE_S = (1.2, 1.8)     # one eased glide, longer for a longer way
HOLD_ZONE = 0.20         # of the crop width: the frame holds while the head stays this close to where it was framed


def max_zoom(orig_h):
    return ZOOM_MAX_HI if orig_h >= 1440 else ZOOM_MAX


def _smootherstep(u):
    return u * u * u * (u * (u * 6 - 15) + 10)


def _even(v, lo=2):
    v = int(round(v))
    return max(lo, v - (v % 2))


def _medfilt(a, k):
    """Running median, window ``k`` (odd), edges held."""
    if k < 3 or len(a) < 3:
        return np.asarray(a, dtype=float)
    k = min(k if k % 2 else k + 1, len(a) if len(a) % 2 else len(a) - 1)
    pad = k // 2
    padded = np.concatenate([np.full(pad, a[0]), a, np.full(pad, a[-1])])
    win = np.lib.stride_tricks.sliding_window_view(padded, k)
    return np.median(win, axis=1)


def fill(heads):
    """(cx, cy, w, h, yaw) arrays over every frame from per-frame observations that may be None
    (held from the last one seen, the first one seen before that); None when nothing was seen.
    Observations are (cx, cy, w, h, yaw) with yaw None when unknown."""
    n = len(heads)
    seen = [(i, o) for i, o in enumerate(heads) if o]
    if not seen:
        return None
    out = np.zeros((n, 5), dtype=float)
    k = 0
    cur = seen[0][1]
    for i in range(n):
        if k < len(seen) and seen[k][0] == i:
            cur = seen[k][1]
            k += 1
        cx, cy, w, h, yaw = cur
        out[i] = (cx, cy, w, h, 0.0 if yaw is None else yaw)
    return out


def glide_path(desired, cx, fps, cw, allowed, edge_room, look_px, orig_w):
    """Crop centre x per frame: hold, then one eased glide when the head has settled elsewhere or is
    about to leave the frame. ``desired``: where the centre would ideally be (head + look-room);
    ``cx``: the head itself; ``allowed``: how far the head may travel inside one framing (margins kept);
    ``edge_room``: how far the head may sit from where it was framed before it touches an edge."""
    n = len(desired)
    lo, hi = cw / 2.0, orig_w - cw / 2.0

    def clamp(v):
        return min(max(v, lo), hi)

    def settle(i, span):
        window = sorted(desired[i:i + max(1, int(span * fps))])
        return clamp(window[len(window) // 2])

    # The frame holds while the head stays this close to where it was framed: never under a tenth of
    # the width (detector jitter on a tight shot is 30 px), never over HOLD_ZONE.
    hold = min(HOLD_ZONE * cw, max(0.10 * cw, allowed / 2.0))
    confirm, urgent_n = max(1, int(CONFIRM_S * fps)), max(1, int(URGENT_S * fps))
    anchor, out, last_move, moves = settle(0, 0.5), [], -1e9, 0
    i = 0
    while i < n:
        off = desired[i] - anchor
        leaving = abs(cx[i] - (anchor - look_px)) > edge_room
        if abs(off) > hold or leaving:
            need = urgent_n if leaving else confirm
            j = i
            while j < n and j - i < need and (abs(desired[j] - anchor) > hold
                                              or abs(cx[j] - (anchor - look_px)) > edge_room):
                j += 1
            since = (i - last_move) / fps
            if j - i >= need and (since >= GAP_S or leaving):
                new = settle(i, 0.8)
                if abs(new - anchor) >= 1.0:
                    dur = min(GLIDE_S[1], max(GLIDE_S[0], abs(new - anchor) / cw * 2.5))
                    if leaving:
                        dur = min(dur, 1.0)      # the head is on its way out: quicker, still eased
                    m = max(2, int(dur * fps))
                    for k in range(min(m, n - i)):
                        out.append(anchor + (new - anchor) * _smootherstep((k + 1) / m))
                    i += m
                    anchor, last_move, moves = new, i, moves + 1
                    continue
        out.append(anchor)
        i += 1
    return [clamp(v) for v in out[:n]], moves


def shot_boxes(heads, fps, crop_w, crop_h, orig_w, orig_h, zmax=None):
    """Crop boxes (w, h, x, y) per frame for one TRACK shot, and a report, from the tracked head per
    frame (``heads``: (cx, cy, w, h, yaw) or None, in source pixels). None when no head was seen."""
    obs = fill(heads)
    if obs is None:
        return None
    n = len(obs)
    k = max(3, int(SMOOTH_S * fps) | 1)
    cx, cy, w, h = (_medfilt(obs[:, j], k) for j in range(4))
    yaw_seen = [o[4] for o in heads if o and o[4] is not None]
    yaw = float(np.median(yaw_seen)) if yaw_seen else 0.0
    face_w, face_h = float(np.median(w)), float(np.median(h))
    head_w = HEAD_W * face_w
    cy_med = float(np.median(cy))
    crown = cy_med - face_h / 2.0 - HEAD_ABOVE * face_h
    chin = cy_med + face_h / 2.0 + HEAD_BELOW * face_h
    p_lo, p_hi = float(np.percentile(cx, 3)), float(np.percentile(cx, 97))
    span = p_hi - p_lo

    # --- zoom and vertical placement: fixed for the shot ---
    zmax = zmax or max_zoom(orig_h)
    wanted = 1.0
    if cy_med / crop_h > EYE_LINE[1]:
        wanted = crop_h * (1.0 - EYE_TARGET) / max(1.0, crop_h - cy_med)      # the face up to the eye line
    if face_h / crop_h < FACE_MIN:
        wanted = max(wanted, FACE_MIN * crop_h / max(1.0, face_h))             # a small face, bigger
    room = crop_w * (1.0 - 2 * MARGIN_X) / max(1.0, span + head_w + SLACK * crop_w)   # the travel must still fit, with slack
    z = max(1.0, min(wanted, zmax, room))
    ch = _even(crop_h / z)
    cw = _even(ch * crop_w / crop_h)
    if z > 1.0 + 1e-6 or not (EYE_LINE[0] <= cy_med / ch <= EYE_LINE[1]):
        y = cy_med - EYE_TARGET * ch
        y = min(y, crown - HEADROOM * ch)                                      # never tight on the crown
        y = max(y, chin + 0.02 * ch - ch)                                      # nor cutting the chin
    else:
        y = (crop_h - ch) / 2.0
    y = _even(min(max(y, 0.0), orig_h - ch), lo=0)

    # --- horizontal: one framing, or hold and glide ---
    look_px = (LOOK_ROOM * cw * (1 if yaw > 0 else -1)) if abs(yaw) >= LOOK_YAW else 0.0
    allowed = max(0.0, cw - head_w - 2 * MARGIN_X * cw)
    edge_room = max(0.05 * cw, (cw - head_w) / 2.0 - EDGE * cw)
    fixed = span <= allowed + SLACK * cw
    moves = 0
    if fixed:
        centre = (p_lo + p_hi) / 2.0 + look_px
        lo_c = p_hi + head_w / 2.0 + MARGIN_X * cw - cw / 2.0     # the head's right edge inside the margin
        hi_c = p_lo - head_w / 2.0 - MARGIN_X * cw + cw / 2.0     # and its left edge
        if lo_c <= hi_c:
            centre = min(max(centre, lo_c), hi_c)
        centre = min(max(centre, cw / 2.0), orig_w - cw / 2.0)
        xs = [centre] * n
    else:
        desired = [float(v) + look_px for v in cx]
        xs, moves = glide_path(desired, [float(v) for v in cx], fps, cw, allowed, edge_room, look_px, orig_w)
    boxes = []
    for v in xs:
        x = _even(min(max(v - cw / 2.0, 0.0), orig_w - cw), lo=0)
        boxes.append((cw, ch, x, y))
    report = {"fixed": fixed, "moves": moves, "zoom": round(z, 3), "look": round(look_px / cw, 3) if cw else 0.0,
              "y": y, "face_h": round(face_h / ch, 3), "eye": round((cy_med - y) / ch, 3), "span": round(span),
              "head_w": round(head_w)}
    return boxes, report


def with_zoom(boxes, zooms, orig_w, orig_h):
    """A beat punch-in (punch_in.zoom_curve) on top of the shot's boxes: each box closes in about its own
    centre by its frame's zoom."""
    out = []
    for i, (w, h, x, y) in enumerate(boxes):
        z = zooms[i] if i < len(zooms) else 1.0
        if z <= 1.0 + 1e-9:
            out.append((w, h, x, y))
            continue
        nw, nh = _even(w / z), _even(h / z)
        nx = _even(min(max(x + (w - nw) / 2.0, 0), orig_w - nw), lo=0)
        ny = _even(min(max(y + (h - nh) / 2.0, 0), orig_h - nh), lo=0)
        out.append((nw, nh, nx, ny))
    return out


def describe(reports):
    """One log line for a clip's TRACK shots."""
    fixed = sum(1 for r in reports if r["fixed"])
    glides = sum(r["moves"] for r in reports)
    zoomed = [r["zoom"] for r in reports if r["zoom"] > 1.0]
    looked = sum(1 for r in reports if r["look"])
    bits = [f"{fixed} fixed", f"{len(reports) - fixed} with glides ({glides} move(s))"]
    if zoomed:
        bits.append(f"punch-in for the eye line on {len(zoomed)} (x{max(zoomed):.2f} max)")
    if looked:
        bits.append(f"look-room on {looked}")
    return ", ".join(bits)
