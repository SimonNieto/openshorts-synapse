"""Burned-in caption / hook removal that tries to leave no trace.

The old eraser inpainted the WHOLE user rectangle every frame, at 35 % of
the resolution: a smeared, blurry band that "boiled" from frame to frame,
especially over a face. This one:

1. masks only the TEXT inside the rectangle (``caption_mask``): letters,
   their outline / shadow and glow, or a solid banner — the face, shirt or
   wall around the letters is never touched;
2. fills every masked pixel with the REAL picture from the nearest frame,
   before or after (up to ~0.5 s), where that pixel was visible and away
   from any text — word-by-word captions keep changing, so what sits behind
   a word is usually on screen a few frames earlier or later;
3. reconstructs (Navier-Stokes inpainting, full resolution) only what was
   never visible in that window, adding the clip's own grain so the patch is
   not smoother than the picture around it;
4. smooths the patch over time and feathers it into the frame.

Honest limit: text that sits on the SAME spot for a long time over a moving
face (a hook held for 5 s on someone's mouth) has no real background to
borrow and falls back to reconstruction. Truly invisible removal there needs
an AI video-inpainting model (LaMa / ProPainter class) on a GPU.
"""
import os
import subprocess
from typing import Callable, Optional

import cv2
import numpy as np


def _odd(n: int) -> int:
    return n if n % 2 else n + 1


def _halo_radius(region: np.ndarray, mask: np.ndarray, text_h: float) -> int:
    """How far the letters' glow or drop shadow reaches, in px, MEASURED:
    mean COLOUR (Lab — a green glow over red skin barely changes luminance)
    in 3-px rings around the text, going outwards; the halo ends where it
    stops changing from one ring to the next. A plain outlined caption gives
    ~3 px, a neon word 15-40."""
    lim = int(max(4, min(70, text_h * 0.9)))
    dist = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 3)
    lab = cv2.cvtColor(region, cv2.COLOR_BGR2LAB).astype(np.float32)
    rings = []
    for d in range(0, lim + 3, 3):
        ring = (dist > d) & (dist <= d + 3)
        if ring.sum() < 20:
            break
        rings.append((d, lab[ring].mean(axis=0)))
    if len(rings) < 3:
        return max(3, int(text_h * 0.4))
    far = rings[-1][1]
    # A glow fades slowly (a coloured haze over the skin changes little from
    # one ring to the next): the halo ends where the rings have stopped
    # changing AND look like the background further out.
    flat = 0
    for (d, cur), (_, nxt) in zip(rings, rings[1:]):
        if float(np.linalg.norm(nxt - cur)) < 2.0 and float(np.linalg.norm(cur - far)) < 6.0:
            flat += 1
            if flat == 2:
                return int(min(lim, max(3, d - 3)))
        else:
            flat = 0
    return lim


def caption_mask(region: np.ndarray, sensitivity: float = 1.0) -> np.ndarray:
    """Pixels of burned-in TEXT (fill + outline + glow, or a solid banner)
    inside a user-drawn region — not the whole rectangle.

    * Letters: a bright fill (white, yellow, any vivid colour) that is thin
      compared to the box — morphological top-hat on luminance and on value.
    * Outline / shadow: dark pixels count ONLY where they touch a letter —
      on its own a dark thin shape is a mouth, a nostril or a mic, not text.
    * Glow: covered by growing the letters by ~1/3 of their measured height.
    * Banner (hook box): a large near-uniform light or dark rectangle is taken
      whole, letters included."""
    h, w = region.shape[:2]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    k = _odd(max(7, min(61, int(h * 0.35))))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    thr = 45 / max(0.4, sensitivity)
    thin = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel) > thr
    thin |= cv2.morphologyEx(hsv[..., 2], cv2.MORPH_TOPHAT, kernel) > thr * 1.1
    val, sat = hsv[..., 2], hsv[..., 1]
    thin |= (cv2.morphologyEx(sat, cv2.MORPH_TOPHAT, kernel) > thr * 1.3) & (val >= 120)
    # Caption fills are near-pure white, or a vivid colour at high brightness.
    colour = ((val >= 225) & (sat <= 60)) | ((val >= 190) & (sat >= 90)) | ((val >= 120) & (sat >= 150))
    bright = (thin & colour).astype(np.uint8) * 255
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(bright, connectivity=8)
    min_area = max(8, int(h * w * 0.0002))
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edges = cv2.magnitude(gx, gy)
    cand = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        # A glowing word is ONE wide blob, so no width limit; what is not
        # text is a blob taller than the line or a sparse sliver.
        if not (area >= min_area and bh <= 0.8 * h and area >= 0.08 * bw * bh):
            continue
        blob = (labels[y:y + bh, x:x + bw] == i).astype(np.uint8)
        rim = blob - cv2.erode(blob, np.ones((3, 3), np.uint8))
        e = edges[y:y + bh, x:x + bw][rim > 0]
        sharp = float(np.percentile(e, 75)) if e.size else 0.0
        touch = x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1
        # Letters are strokes: the widest inscribed circle is ~1/10 of the
        # letter height (bold: 1/8). A solid chunk of set is ~1/3 or more —
        # unless it is a whole word its glow merged into one wide blob, well
        # inside the box (a light panel's edge runs out of it).
        if bh >= 12 and area >= 0.45 * bw * bh and (bw < 2.2 * bh or touch):
            inscribed = float(cv2.distanceTransform(np.pad(blob, 1), cv2.DIST_L2, 3).max())
            if inscribed > 0.28 * min(bh, bw):
                continue
        cand.append((i, x, y, bw, bh, area, touch, sharp))
    # Rendered letters have crisp rims; a lit cheek, teeth or a light panel
    # behind the speaker are soft or run out of the box.
    # The line height comes from the letters inside the box, crisp ones first
    # (a word animating in is motion-blurred, so softness alone rejects
    # nothing).
    core = ([c for c in cand if not c[6] and c[7] >= 110] or [c for c in cand if not c[6]] or cand)
    keep = np.zeros(n, dtype=bool)
    heights = []
    if core:
        text_h = float(np.percentile([c[4] for c in cand if not c[6]] or [c[4] for c in core], 75))
        core_area = float(np.median([c[5] for c in core]))
        centres = np.array([(c[1] + c[3] / 2, c[2] + c[4] / 2) for c in core])
        for c in cand:
            i, x, y, bw, bh, area, touch, sharp = c
            if touch and (sharp < 110 or not (0.4 * text_h <= bh <= 1.5 * text_h)):
                continue   # a piece of the set crossing the box edge
            if area < 0.1 * core_area:
                d = np.min(np.hypot(centres[:, 0] - (x + bw / 2), centres[:, 1] - (y + bh / 2)))
                if d > 1.5 * text_h:
                    continue   # a speck far from every letter
            keep[i] = True
            heights.append(bh)
    letters = (keep[labels] * 255).astype(np.uint8)
    mask = letters.copy()
    if heights:
        text_h = float(np.percentile(heights, 60))
        near = cv2.dilate(letters, cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (_odd(int(text_h * 0.4) + 3), _odd(int(text_h * 0.4) + 3))))
        dark = (cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel) > thr) & (near > 0)
        mask |= dark.astype(np.uint8) * 255
        mask = cv2.dilate(mask, cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * 3 + 1, 2 * 3 + 1)))
        halo = _halo_radius(region, mask, text_h)
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * halo + 1, 2 * halo + 1)))
    # A hook banner: a big near-uniform light / dark rectangle INSIDE the box
    # (touching at most one of its sides — a dark wall or shirt runs out of
    # it) with text on it.
    for lo, hi in ((225, 256), (0, 28)):
        uni = cv2.inRange(val, lo, hi - 1)
        if lo:
            uni &= cv2.inRange(sat, 0, 50)
        n2, _, st2, _ = cv2.connectedComponentsWithStats(uni, connectivity=8)
        for i in range(1, n2):
            x, y, bw, bh, area = st2[i]
            if not (bw * bh >= 0.12 * h * w and area >= 0.75 * bw * bh and bh >= 0.1 * h):
                continue
            touches = int(x <= 1) + int(y <= 1) + int(x + bw >= w - 1) + int(y + bh >= h - 1)
            has_text = letters[y:y + bh, x:x + bw].mean() > 255 * 0.02 or \
                (cv2.morphologyEx(gray[y:y + bh, x:x + bw], cv2.MORPH_BLACKHAT, kernel) > thr).mean() > 0.02
            if touches <= 1 and has_text:
                pad = max(3, int(bh * 0.08))
                cv2.rectangle(mask, (max(0, x - pad), max(0, y - pad)),
                              (min(w - 1, x + bw + pad), min(h - 1, y + bh + pad)), 255, -1)
    return mask


def _text_lines(frame: np.ndarray) -> list:
    """Caption-like text LINES in a frame: [(x0, y0, x1, y1)] px.

    A line is several letter-sized blobs of similar height sitting side by
    side (or one wide blob, when a glow merges the letters), in near-pure
    white or a vivid colour, and roughly centred — which is how captions and
    hooks are laid out. Isolated bright shapes of the set (a neon letter, a
    reflection) do not form such lines."""
    H, W = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    k = _odd(max(9, int(H * 0.035)))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    thin = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel) > 45
    thin |= cv2.morphologyEx(hsv[..., 2], cv2.MORPH_TOPHAT, kernel) > 50
    val, sat = hsv[..., 2], hsv[..., 1]
    colour = (val >= 200) | ((val >= 120) & (sat >= 150))
    m = (thin & colour).astype(np.uint8) * 255
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edges = cv2.magnitude(gx, gy)
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    blobs = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if (0.008 * H <= bh <= 0.08 * H and area >= 12 and area >= 0.08 * bw * bh
                and x > 2 and y > 2 and x + bw < W - 2 and y + bh < H - 2):
            blobs.append((x, y, x + bw, y + bh))
    blobs.sort(key=lambda r: (r[1] + r[3]) / 2)
    lines, used = [], [False] * len(blobs)
    for i, (x0, y0, x1, y1) in enumerate(blobs):
        if used[i]:
            continue
        h = y1 - y0
        members = [i]
        for j in range(i + 1, len(blobs)):
            if used[j]:
                continue
            a0, b0, a1, b1 = blobs[j]
            hj = b1 - b0
            overlap = min(y1, b1) - max(y0, b0)
            if overlap > 0.5 * min(h, hj) and 0.5 < hj / h < 2.0:
                members.append(j)
        members.sort(key=lambda j: blobs[j][0])
        # Split where the horizontal gap is too big to be one line.
        group = [members[0]]
        for j in members[1:]:
            if blobs[j][0] - blobs[group[-1]][2] <= 1.6 * h:
                group.append(j)
            else:
                break
        for j in group:
            used[j] = True
        gx0 = min(blobs[j][0] for j in group)
        gy0 = min(blobs[j][1] for j in group)
        gx1 = max(blobs[j][2] for j in group)
        gy1 = max(blobs[j][3] for j in group)
        width, gh = gx1 - gx0, gy1 - gy0
        centred = abs((gx0 + gx1) / 2 - W / 2) <= 0.18 * W
        if not (centred and (len(group) >= 3 or width >= 2.5 * gh) and width >= 0.08 * W):
            continue
        # Rendered text has razor edges (measured: 259-999 at the 95th
        # percentile, glowing words included); a lit forehead, wrinkles or a
        # reflection are soft (<= 200) even when they are as bright.
        if float(np.percentile(edges[gy0:gy1, gx0:gx1], 95)) >= 230:
            lines.append((gx0, gy0, gx1, gy1))
    return lines


def detect_text_regions(video_path: str, samples: int = 28, max_regions: int = 4) -> list:
    """Suggest erase boxes: where burned-in captions / hooks show up, and when.

    ~28 frames spread over the clip, text lines found in each (``_text_lines``)
    and grouped by height on screen. A group seen in most samples is the
    caption band (the whole clip); one seen only for a while is a hook (from
    its first to its last sighting). A line that never changes and is not
    small is scene text (a sign) and is left alone."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    duration = n_frames / fps
    found, times, H, W = [], [], None, None
    head = [0.25 + 0.5 * k for k in range(12) if 0.25 + 0.5 * k < duration * 0.5]
    spread = [duration * (k + 0.5) / samples for k in range(samples)]
    for t in sorted(set(round(x, 2) for x in head + spread)):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok:
            continue
        H, W = fr.shape[:2]
        times.append(t)
        found.append(_text_lines(fr))
    cap.release()
    if not times:
        return []
    clusters = []   # {yc, boxes: [(sample_idx, box)]}
    for si, lines in enumerate(found):
        for box in lines:
            yc = (box[1] + box[3]) / 2
            c = next((c for c in clusters if abs(c["yc"] - yc) <= 0.05 * H), None)
            if c is None:
                c = {"yc": yc, "boxes": []}
                clusters.append(c)
            c["boxes"].append((si, box))
            c["yc"] = float(np.mean([(b[1] + b[3]) / 2 for _, b in c["boxes"]]))
    regions = []
    for c in clusters:
        seen = sorted({si for si, _ in c["boxes"]})
        # Share of the RUNTIME covered (the head is sampled more densely).
        share = sum(_sample_span(times, si, duration) for si in seen) / duration
        if len(seen) < 2:
            continue
        xs0 = [b[0] for _, b in c["boxes"]]
        xs1 = [b[2] for _, b in c["boxes"]]
        ys0 = [b[1] for _, b in c["boxes"]]
        ys1 = [b[3] for _, b in c["boxes"]]
        line_h = float(np.median([b[3] - b[1] for _, b in c["boxes"]]))
        # A line whose extent never changes and that is not small is part of
        # the set (a sign); captions change width with every word.
        widths = [b[2] - b[0] for _, b in c["boxes"]]
        if share > 0.9 and np.std(widths) < 0.02 * W and line_h > 0.03 * H:
            continue
        pad_y, pad_x = int(line_h * 0.6) + 6, int(W * 0.03)
        x0, x1 = max(0, min(xs0) - pad_x), min(W, max(xs1) + pad_x)
        y0, y1 = max(0, min(ys0) - pad_y), min(H, max(ys1) + pad_y)
        if share >= 0.5 or (len(seen) >= 4 and times[seen[-1]] - times[seen[0]] >= 0.5 * duration):
            # Captions: text keeps coming back here all along the clip.
            start, end = 0.0, duration
        else:
            # A hook stays up long enough to be read: it must show on
            # consecutive samples at least 0.4 s apart. A lone sighting, or a
            # few scattered ones, is the set catching the light.
            runs, run = [], [seen[0]]
            for si in seen[1:]:
                if si == run[-1] + 1:
                    run.append(si)
                else:
                    runs.append(run)
                    run = [si]
            runs.append(run)
            runs = [r for r in runs if len(r) >= 2 and times[r[-1]] - times[r[0]] >= 0.4]
            if not runs:
                continue
            first, last = runs[0][0], runs[-1][-1]
            start = max(0.0, times[first] - _sample_span(times, first, duration))
            end = min(duration, times[last] + _sample_span(times, last, duration))
        regions.append([x0, y0, x1, y1, start, end, share])
    # One box per place on screen: a caption band and a hook above it that
    # overlap become one box covering both, for the union of their times.
    merged = True
    while merged:
        merged = False
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                a, b = regions[i], regions[j]
                oy = min(a[3], b[3]) - max(a[1], b[1])
                ox = min(a[2], b[2]) - max(a[0], b[0])
                if ox > 0 and oy > 0.3 * min(a[3] - a[1], b[3] - b[1]):
                    regions[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]),
                                  min(a[4], b[4]), max(a[5], b[5]), max(a[6], b[6])]
                    del regions[j]
                    merged = True
                    break
            if merged:
                break
    out = []
    for x0, y0, x1, y1, start, end, share in regions:
        whole = end - start >= 0.9 * duration
        out.append({"x": round(float(x0) / W, 4), "y": round(float(y0) / H, 4),
                    "w": round(float(x1 - x0) / W, 4), "h": round(float(y1 - y0) / H, 4),
                    "start": 0.0 if whole else round(float(start), 2),
                    "end": round(float(duration if whole else end), 2),
                    "kind": "captions" if whole else "hook", "seen": round(float(share), 2)})
    out.sort(key=lambda r: -r["seen"])
    return out[:max_regions]


def _sample_span(times: list, i: int, duration: float) -> float:
    """Seconds of runtime one sample stands for (half-way to its neighbours)."""
    lo = (times[i - 1] + times[i]) / 2 if i > 0 else 0.0
    hi = (times[i] + times[i + 1]) / 2 if i + 1 < len(times) else duration
    return hi - lo


def _blur_pair(vk: np.ndarray, k: np.ndarray, sigma: float):
    """Gaussian blur of (values * weights, weights) for normalised
    convolution. A wide blur is done on a grid shrunk by sigma/2 and scaled
    back: same smooth result, a fraction of the cost."""
    if sigma <= 3:
        return cv2.GaussianBlur(vk, (0, 0), sigma), cv2.GaussianBlur(k, (0, 0), sigma)
    h, w = k.shape[:2]
    f = sigma / 2.0
    sw, sh = max(2, int(round(w / f))), max(2, int(round(h / f)))
    vs = cv2.GaussianBlur(cv2.resize(vk, (sw, sh), interpolation=cv2.INTER_AREA), (0, 0), 1.6)
    ks = cv2.GaussianBlur(cv2.resize(k, (sw, sh), interpolation=cv2.INTER_AREA), (0, 0), 1.6)
    vs = cv2.resize(vs, (w, h), interpolation=cv2.INTER_LINEAR)
    ks = cv2.resize(ks, (w, h), interpolation=cv2.INTER_LINEAR)
    if vk.ndim == 3 and vs.ndim == 2:
        vs = vs[..., None]
    return vs, ks


def _complete_flow(flow: np.ndarray, invalid: np.ndarray) -> np.ndarray:
    """Flow is meaningless where text sits (the letters move, not the scene):
    replace it there with the motion of the picture around, by normalised
    convolution at growing scales (small gaps filled finely, big ones
    coarsely). Faces move smoothly enough for this to hold."""
    if not invalid.any():
        return flow
    valid = (~invalid).astype(np.float32)
    out = flow.copy()
    missing = invalid.copy()
    for sigma in (3, 9, 27):
        num, den = _blur_pair(flow * valid[..., None], valid, sigma)
        fill = missing & (den > 1e-3)
        out[fill] = num[fill] / den[fill][..., None]
        missing &= ~fill
        if not missing.any():
            break
    if missing.any():
        out[missing] = np.median(flow[~invalid], axis=0) if (~invalid).any() else 0
    return out


def _flow(dis, a: np.ndarray, b: np.ndarray, invalid: np.ndarray) -> np.ndarray:
    """a -> b motion, completed across the text and smoothed (DIS estimates
    it in 8-px patches; a blocky field makes blocky warps)."""
    f = _complete_flow(dis.calc(a, b, None), invalid)
    return cv2.GaussianBlur(f, (0, 0), 2.0).astype(np.float16)


def _letter_pixels(img: np.ndarray, k: int) -> np.ndarray:
    """Thin bright / vivid strokes — what a letter looks like — anywhere in
    ``img``, a little grown. Used on CARRIED background: a word the detector
    missed on some frame (half faded in, motion-blurred) must not ride along
    into the frames where it was erased."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    thin = (cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel) > 40) |         (cv2.morphologyEx(hsv[..., 2], cv2.MORPH_TOPHAT, kernel) > 45)
    colour = (hsv[..., 2] >= 185) | ((hsv[..., 2] >= 120) & (hsv[..., 1] >= 150))
    return cv2.dilate((thin & colour).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0


def _spread(values: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Extend ``values`` (H x W x C float) from the ``known`` pixels over the
    whole array, smoothly: normalised convolution at growing scales."""
    k = known.astype(np.float32)
    out = np.zeros_like(values)
    missing = np.ones(known.shape, dtype=bool)
    for sigma in (2, 6, 18, 54):
        num, den = _blur_pair(values * k[..., None], k, sigma)
        if num.ndim == 2:
            num = num[..., None]
        put = missing & (den > 1e-4)
        out[put] = num[put] / den[put][..., None]
        missing &= ~put
        if not missing.any():
            break
    return out


def _match_seams(fill: np.ndarray, crop: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """Poisson-style seam removal, cheap: the colour step between the patch
    and the picture just outside it is measured all along the hole's edge
    and spread smoothly over the patch, so the patch keeps its own detail
    but meets its surroundings without a visible border."""
    h8 = hole.astype(np.uint8)
    inner = hole & ~(cv2.erode(h8, np.ones((3, 3), np.uint8)) > 0)
    outer = (cv2.dilate(h8, np.ones((5, 5), np.uint8)) > 0) & ~hole
    if not inner.any() or not outer.any():
        return fill
    f = fill.astype(np.float32)
    o = outer.astype(np.float32)
    den = np.maximum(cv2.GaussianBlur(o, (0, 0), 2.5), 1e-4)[..., None]
    target = cv2.GaussianBlur(crop.astype(np.float32) * o[..., None], (0, 0), 2.5) / den
    d = np.zeros_like(f)
    d[inner] = target[inner] - f[inner]
    corr = cv2.GaussianBlur(_spread(d, inner), (0, 0), 2.0)
    f[hole] += corr[hole]
    return np.clip(f, 0, 255).astype(np.uint8)


def erase(input_path: str, output_path: str, px_boxes: list, width: int, height: int, fps: float,
          duration: float, encode_args: list, on_progress: Optional[Callable[[float], None]] = None,
          sensitivity: Optional[float] = None) -> None:
    """``px_boxes``: [{"rect": (x, y, w, h) px, "start": s|None, "end": s|None}].

    Background behind the text is PROPAGATED along the motion of the picture
    (dense optical flow between consecutive frames, completed across the
    text), forwards from the past and backwards from the future, up to ~1 s
    each way; each hidden pixel takes whichever estimate travelled the fewest
    frames. What was never visible within that second is reconstructed.

    Two decoders read the file in step: one looks ahead (masks, flow, the
    backward pass, in blocks of ~1 s), the other supplies full frames at
    output time, so only crops are held in memory."""
    pad = 24
    x0 = max(0, min(b["rect"][0] for b in px_boxes) - pad)
    y0 = max(0, min(b["rect"][1] for b in px_boxes) - pad)
    x1 = min(width, max(b["rect"][0] + b["rect"][2] for b in px_boxes) + pad)
    y1 = min(height, max(b["rect"][1] + b["rect"][3] for b in px_boxes) + pad)
    cw, ch = x1 - x0, y1 - y0
    sensitivity = sensitivity or float(os.environ.get("HOOK_REMOVAL_SENSITIVITY", "1.0"))
    safe_kernel = np.ones((15, 15), np.uint8)
    max_age = max(4, int(round(fps * 1.0)))
    block = max(8, int(round(fps * 1.0)))
    lone_age = max(2, int(round(fps * 0.25)))
    # Text in a frame taints the neighbouring ~0.1 s: a word fading or
    # sliding in is invisible to the detector for a few frames.
    taint = max(2, int(round(fps * 0.1)))
    letter_k = _odd(max(9, min(61, int(min(b["rect"][3] for b in px_boxes) * 0.35))))
    # Flow at half resolution: plenty for a face's motion, 4x cheaper.
    fw, fh = max(16, cw // 2), max(16, ch // 2)
    sx, sy = cw / fw, ch / fh
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
    grid_x, grid_y = np.meshgrid(np.arange(cw, dtype=np.float32), np.arange(ch, dtype=np.float32))
    INVALID = 255

    stem = os.path.splitext(output_path)[0]
    silent_path = f"{stem}.silent.mp4"
    audio_path = f"{stem}.audio.m4a"
    encoder = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-video_size", f"{width}x{height}", "-framerate", str(fps), "-i", "pipe:0",
         *encode_args, "-an", silent_path],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    total_frames = max(1, int(duration * fps))
    rng = np.random.default_rng(7)
    state = {"prev_out": None, "prev_mask": None, "sigma": None, "written": 0,
             "fwd": None, "shot": 0, "prev_thumb": None, "read": 0, "eof": False}
    entries = {}   # idx -> dict(crop, mask, unsafe, shot, small, fb, ff)
    unsafe5 = {}
    bwd = {}       # idx -> (background, age) from the backward pass

    def masks_for(idx, crop):
        t = idx / fps
        m = np.zeros((ch, cw), dtype=np.uint8)
        for b in px_boxes:
            if (b["start"] is not None and t < b["start"]) or (b["end"] is not None and t > b["end"]):
                continue
            bx, by, bw, bh = b["rect"]
            lx, ly = bx - x0, by - y0
            m[ly:ly + bh, lx:lx + bw] |= caption_mask(crop[ly:ly + bh, lx:lx + bw], sensitivity)
        return m, cv2.dilate(m, safe_kernel) > 0

    def seed_of(j):
        """Pixels of frame j that are real picture: away from text on j and
        on its 2 neighbours each side (a word popping in is invisible to the
        detector for a frame or two)."""
        u = unsafe5.get(j)
        if u is None:
            e = entries[j]
            u = e["unsafe"].copy()
            for d in range(-taint, taint + 1):
                n = entries.get(j + d) if d else None
                if n is not None and n["shot"] == e["shot"]:
                    u |= n["unsafe"]
            if (j + taint) in entries or state["eof"]:
                unsafe5[j] = u
        return ~u

    def read_one(analysis):
        ok, frame = analysis.read()
        if not ok:
            state["eof"] = True
            return
        idx = state["read"]
        thumb = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (32, 56)).astype(np.float32)
        if state["prev_thumb"] is not None and float(np.mean(np.abs(thumb - state["prev_thumb"]))) > 25:
            state["shot"] += 1
        state["prev_thumb"] = thumb
        crop = frame[y0:y1, x0:x1].copy()
        m, unsafe = masks_for(idx, crop)
        small = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (fw, fh), interpolation=cv2.INTER_AREA)
        e = {"crop": crop, "mask": m, "unsafe": unsafe, "shot": state["shot"], "small": small,
             "fb": None, "ff": None, "has_text": bool(m.any())}
        p = entries.get(idx - 1)
        if p is not None and p["shot"] == e["shot"] and (e["has_text"] or p["has_text"]):
            bad = cv2.resize((unsafe | p["unsafe"]).astype(np.uint8), (fw, fh),
                             interpolation=cv2.INTER_NEAREST) > 0
            bad = cv2.dilate(bad.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            e["fb"] = _flow(dis, small, p["small"], bad)
            p["ff"] = _flow(dis, p["small"], small, bad)
        entries[idx] = e
        state["read"] += 1

    def warp(bg, age, flow_half):
        f = cv2.resize(flow_half.astype(np.float32), (cw, ch), interpolation=cv2.INTER_LINEAR)
        mx = grid_x + f[..., 0] * sx
        my = grid_y + f[..., 1] * sy
        wb = cv2.remap(bg, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        wa = cv2.remap(age, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=INVALID)
        return wb, wa

    def step(prev, j, flow_key):
        """Carry the background of a neighbouring frame into frame j."""
        e = entries[j]
        seed = seed_of(j)
        if prev is None or prev[2] != e["shot"] or e[flow_key] is None or seed.all():
            age = np.where(seed, 0, INVALID).astype(np.uint8)
            return (e["crop"], age, e["shot"])
        wb, wa = warp(prev[0], prev[1], e[flow_key])
        # Same scene? The carried picture must match the real one right
        # around the hole; if not (a dissolve, a whip pan) start over here.
        ring = seed & ~cv2.erode(seed.astype(np.uint8), safe_kernel).astype(bool)
        if ring.any():
            ys, xs = np.nonzero(ring)
            if len(ys) > 2000:
                sel = np.linspace(0, len(ys) - 1, 2000).astype(int)
                ys, xs = ys[sel], xs[sel]
            diff = float(np.mean(np.abs(wb[ys, xs].astype(np.int16) - e["crop"][ys, xs].astype(np.int16))))
            if diff > 16:
                return (e["crop"], np.where(seed, 0, INVALID).astype(np.uint8), e["shot"])
        age = np.where(wa >= max_age, INVALID, wa + 1).astype(np.uint8)
        bg = np.where(seed[..., None], e["crop"], wb)
        age[seed] = 0
        return (bg, age, e["shot"])

    def backward_block(s, e_end):
        top = min(e_end - 1 + max_age, state["read"] - 1)
        cur = None
        for j in range(top, s - 1, -1):
            cur = step(cur, j, "ff")
            if j < e_end:
                bwd[j] = (cur[0], cur[1])

    def emit(i, output):
        ok, frame = output.read()
        if not ok:
            return
        e = entries[i]
        crop, mask = e["crop"], e["mask"]
        state["fwd"] = step(state["fwd"], i, "fb")
        for d in (-1, 1):
            n = entries.get(i + d)
            if n is not None and n["shot"] == e["shot"] and n["has_text"] and e["has_text"]:
                mask = mask | n["mask"]
        need = mask > 0
        if need.any():
            fb_bg, fb_age = state["fwd"][0], state["fwd"][1]
            bb_bg, bb_age = bwd.get(i, (crop, np.full((ch, cw), INVALID, np.uint8)))
            ys, xs = np.nonzero(need)
            m = safe_kernel.shape[0]
            ry0, ry1 = max(0, ys.min() - m), min(ch, ys.max() + m + 1)
            rx0, rx1 = max(0, xs.min() - m), min(cw, xs.max() + m + 1)
            R = (slice(ry0, ry1), slice(rx0, rx1))
            need_r, mask_r, crop_r = need[R], mask[R], crop[R]
            fa, ba = fb_age[R], bb_age[R]
            has_f, has_b = fa != INVALID, ba != INVALID
            use_f = has_f & (~has_b | (fa <= ba))
            pick = np.where(use_f[..., None], fb_bg[R], bb_bg[R])
            # Where past and future both carry a pixel, blend them by
            # freshness instead of switching: no seam where one takes over.
            wf = np.where(has_f, 1.0 / (1.0 + fa.astype(np.float32)), 0.0)
            wb = np.where(has_b, 1.0 / (1.0 + ba.astype(np.float32)), 0.0)
            two = has_f & has_b
            if two.any():
                mix = (fb_bg[R].astype(np.float32) * wf[..., None] + bb_bg[R].astype(np.float32) * wb[..., None])                     / np.maximum(wf + wb, 1e-6)[..., None]
                pick[two] = mix[two].astype(np.uint8)
            # Carried background is trusted when the past and the future agree
            # on it, or when only one exists and it is recent. Two estimates
            # that disagree mean the motion under the text was guessed wrong.
            both_ok = has_f & has_b
            agree = np.abs(fb_bg[R].astype(np.int16) - bb_bg[R].astype(np.int16)).mean(axis=2) <= 18
            young = np.minimum(np.where(has_f, fa, INVALID), np.where(has_b, ba, INVALID)) <= lone_age
            trusted = (both_ok & (agree | young)) | ((has_f ^ has_b) & young)
            fill = crop_r.copy()
            todo = need_r.copy()
            # A carried pixel may not be brighter / more saturated than the
            # picture around the hole: then it is text the detector missed.
            ring = (cv2.dilate(mask_r, safe_kernel) > 0) & ~need_r
            hsv_r = cv2.cvtColor(crop_r, cv2.COLOR_BGR2HSV)
            if ring.any():
                v_max = float(np.percentile(hsv_r[..., 2][ring], 97)) + 18
                s_max = float(np.percentile(hsv_r[..., 1][ring], 97)) + 35
            else:
                v_max, s_max = 255.0, 255.0
            hsv_p = cv2.cvtColor(pick, cv2.COLOR_BGR2HSV)
            ghost = _letter_pixels(pick, letter_k) & ~_letter_pixels(crop_r, letter_k)
            ok = todo & trusted & ~ghost & (hsv_p[..., 2] <= v_max) & (hsv_p[..., 1] <= s_max)
            fill[ok] = pick[ok]
            todo &= ~ok
            if todo.any():
                hole = todo.astype(np.uint8) * 255
                if int(todo.sum()) > 2000:
                    # A big hole never seen in any frame: a smooth membrane
                    # between its edges (grain goes back on below). Line-
                    # extending inpainting draws streaks across a wide hole.
                    hh, ww = hole.shape
                    small = cv2.resize(fill, (max(1, ww // 2), max(1, hh // 2)),
                                       interpolation=cv2.INTER_AREA).astype(np.float32)
                    small_known = cv2.resize(hole, (small.shape[1], small.shape[0]),
                                             interpolation=cv2.INTER_NEAREST) == 0
                    rec = _spread(small, small_known)
                    rec = cv2.GaussianBlur(rec, (0, 0), 1.5)
                    rec = cv2.resize(np.clip(rec, 0, 255).astype(np.uint8), (ww, hh), interpolation=cv2.INTER_LINEAR)
                else:
                    rec = cv2.inpaint(fill, hole, 4, cv2.INPAINT_NS)
                if state["sigma"] is None or state["written"] % 30 == 0:
                    if ring.any():
                        hp = crop_r.astype(np.int16) - cv2.GaussianBlur(crop_r, (0, 0), 1.2).astype(np.int16)
                        state["sigma"] = float(np.std(hp[ring]))
                if state["sigma"] and state["sigma"] > 0.5:
                    noise = rng.normal(0, state["sigma"] * 0.8, rec.shape).astype(np.int16)
                    rec = np.clip(rec.astype(np.int16) + noise * todo[..., None], 0, 255).astype(np.uint8)
                fill[todo] = rec[todo]
            fill = _match_seams(fill, crop_r, need_r)
            full = crop.copy()
            full[R] = fill
            # Reconstructed pixels only: a light temporal blend so the guess
            # does not boil. Propagated ones are already coherent over time.
            if state["prev_out"] is not None:
                both = np.zeros_like(need)
                both[R] = todo
                both &= state["prev_mask"] > 0
                full[both] = (0.7 * full[both] + 0.3 * state["prev_out"][both]).astype(np.uint8)
            alpha = cv2.GaussianBlur(mask_r.astype(np.float32) / 255.0, (0, 0), 1.6)[..., None]
            out = crop.copy()
            out[R] = (full[R] * alpha + crop_r * (1 - alpha)).astype(np.uint8)
            state["prev_out"], state["prev_mask"] = full, mask
        else:
            out = crop
            state["prev_out"], state["prev_mask"] = None, None
        frame[y0:y1, x0:x1] = out
        encoder.stdin.write(frame.tobytes())
        state["written"] += 1
        if on_progress and state["written"] % 10 == 0:
            on_progress(min(1.0, state["written"] / total_frames))

    analysis = cv2.VideoCapture(input_path)
    output = cv2.VideoCapture(input_path)
    try:
        next_emit = 0
        while True:
            if next_emit % block == 0 and next_emit not in bwd:
                want = next_emit + block + max_age + taint
                while not state["eof"] and state["read"] < want:
                    read_one(analysis)
                if next_emit >= state["read"]:
                    break
                backward_block(next_emit, min(next_emit + block, state["read"]))
            if next_emit >= state["read"]:
                break
            emit(next_emit, output)
            bwd.pop(next_emit, None)
            for old in [k for k in entries if k < next_emit - taint - 1]:
                entries.pop(old)
                unsafe5.pop(old, None)
            next_emit += 1
        if on_progress:
            on_progress(1.0)
    finally:
        analysis.release()
        output.release()
        encoder.stdin.close()
        encode_err = encoder.stderr.read()
        encoder.wait()
    if encoder.returncode != 0:
        for leftover in (silent_path, audio_path):
            if os.path.exists(leftover):
                os.remove(leftover)
        raise RuntimeError(f"caption removal encode failed: {(encode_err or b'').decode(errors='replace')[-800:]}")
    has_audio = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", input_path, "-vn", "-c:a", "aac", "-b:a", "192k", audio_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE).returncode == 0
    mux = ["ffmpeg", "-y", "-loglevel", "error", "-i", silent_path]
    if has_audio and os.path.exists(audio_path):
        mux += ["-i", audio_path]
    mux += ["-c", "copy", "-movflags", "+faststart", output_path]
    try:
        subprocess.run(mux, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    finally:
        for leftover in (silent_path, audio_path):
            if os.path.exists(leftover):
                os.remove(leftover)
