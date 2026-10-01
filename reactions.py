"""Reaction cutaways (Clip Generator++): cut to the LISTENER for ~0.9 s right
after a line lands, while the speaker's audio keeps playing (a J-cut).

Why: the big podcast channels do not animate a talking head with effects,
they cut between cameras — the host, then the guest reacting. A reaction
tells the viewer "this landed" and resets attention without looking edited.

How a reaction is found, in the SOURCE video around the clip (±60 s):
1. shots: split where consecutive thumbnails differ a lot (camera switches);
2. listening shots: one dominant, close face whose MOUTH barely moves
   (lip-gap variation from MediaPipe FaceMesh) while the transcript says
   someone is speaking — i.e. that person is hearing, not talking;
3. not the speaker: the person's look (face + clothes colour histogram)
   must differ from the speaker's, measured on the shots where the mouth
   moves during the clip itself — so we never cut to the speaker pausing;
4. the most expressive 0.9 s of the shot (head motion + mouth/smile range).

Where it goes in the clip: right after the end of a sentence — the AI's
punchline first when selection v2 found it, then the sentences carrying the
strongest words — never in the first 2 s or the last 1.5 s, >= 6 s apart,
about one per 12 s (max 3). The clip's timing and audio never change.

Nothing is inserted when the source has no second camera / no listener.
"""
import math
import os
import re
import subprocess
import tempfile

FPS = 5
WIDTH = 480
MIN_SHOT = 1.2          # s: shorter shots are flashes / B-roll, not usable
# Smooth camera (profile option, SMOOTH_CAMERA=1): fewer, a bit longer
# cutaways that dissolve in and out (~4 frames) instead of flashing.
SMOOTH = os.environ.get("SMOOTH_CAMERA", "0") == "1"
REACT_LEN = 1.2 if SMOOTH else 0.9   # s: length of one cutaway
REACT_FADE = 0.13       # s: dissolve in and out, smooth camera only
FACE_MIN_H = 0.18       # dominant face height (fraction of frame) — a close shot


def _encode_args():
    """x264 veryfast crf 18 historically; near-lossless when the profile's HQ
    render chain is on (the motion, the B-roll, the hook and the captions all
    re-encode this layer): ffmpeg_utils.layer_encode_args."""
    from ffmpeg_utils import layer_encode_args
    return layer_encode_args(["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"])


def _frames(src, t0, t1):
    """RGB frames at FPS, WIDTH wide, from t0..t1 (s). Returns (list, h)."""
    import numpy as np
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", src], capture_output=True, text=True).stdout
    w, h = [int(x) for x in probe.strip().split("\n")[0].split(",")[:2]]
    oh = int(round(h * WIDTH / w / 2) * 2)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", src,
                          "-vf", f"fps={FPS},scale={WIDTH}:{oh}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    size = WIDTH * oh * 3
    frames = [np.frombuffer(raw[i * size:(i + 1) * size], dtype=np.uint8).reshape(oh, WIDTH, 3)
              for i in range(len(raw) // size)]
    return frames, oh, (w, h)


def _speech_fraction(words_abs, a, b):
    """Share of [a, b] covered by transcript words (someone is talking)."""
    covered = sum(max(0.0, min(b, w["end"]) - max(a, w["start"])) for w in words_abs)
    return covered / max(0.01, b - a)


def _appearance(img, box):
    """HSV histogram of face + the torso under it (clothes are the strongest
    cue for "is this the same person" on a podcast set)."""
    import cv2
    x0, y0, x1, y1 = box
    fh = y1 - y0
    H, W = img.shape[:2]
    rx0, rx1 = max(0, int(x0 - 0.3 * fh)), min(W, int(x1 + 0.3 * fh))
    ry0, ry1 = max(0, int(y0)), min(H, int(y1 + 1.6 * fh))
    if rx1 - rx0 < 8 or ry1 - ry0 < 8:
        return None
    hsv = cv2.cvtColor(img[ry0:ry1, rx0:rx1], cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [12, 8, 8], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def analyze(src, t0, t1, words_abs):
    """Shots of [t0, t1] with their dominant face, mouth activity and look."""
    import numpy as np
    import cv2
    import mediapipe as mp
    frames, fh_px, (sw, sh) = _frames(src, t0, t1)
    if not frames:
        return [], (sw, sh)
    thumbs = [cv2.resize(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), (32, 18)).astype("float32") for f in frames]
    cuts = [0] + [i for i in range(1, len(thumbs)) if float(np.mean(np.abs(thumbs[i] - thumbs[i - 1]))) > 28] + [len(frames)]
    per = []
    with mp.solutions.face_mesh.FaceMesh(static_image_mode=False, max_num_faces=2, refine_landmarks=False,
                                         min_detection_confidence=0.5, min_tracking_confidence=0.5) as mesh:
        for f in frames:
            res = mesh.process(f)
            faces = []
            for lm in (res.multi_face_landmarks or []):
                xs = [p.x for p in lm.landmark]
                ys = [p.y for p in lm.landmark]
                x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
                h = max(1e-3, y1 - y0)
                lip = abs(lm.landmark[14].y - lm.landmark[13].y) / h      # inner lip gap
                corner = abs(lm.landmark[291].x - lm.landmark[61].x) / max(1e-3, x1 - x0)  # smile width
                faces.append({"box": (x0, y0, x1, y1), "h": h, "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
                              "lip": lip, "corner": corner})
            faces.sort(key=lambda d: -d["h"])
            per.append(faces)
    shots = []
    for a, b in zip(cuts, cuts[1:]):
        start, end = t0 + a / FPS, t0 + b / FPS
        if end - start < MIN_SHOT:
            continue
        idx = [i for i in range(a, b) if per[i]]
        if len(idx) < 0.7 * (b - a):
            continue
        dom = [per[i][0] for i in idx]
        mean_h = sum(d["h"] for d in dom) / len(dom)
        if mean_h < FACE_MIN_H:
            continue
        # A two-shot (both people in frame) is not a reaction shot.
        second = [per[i][1]["h"] for i in idx if len(per[i]) > 1]
        if second and sum(second) / len(second) > 0.6 * mean_h:
            continue
        lips = [d["lip"] for d in dom]
        talk = sum(abs(x - y) for x, y in zip(lips, lips[1:])) / max(1, len(lips) - 1)
        mid = idx[len(idx) // 2]
        box = dom[len(dom) // 2]["box"]
        W_, H_ = frames[mid].shape[1], frames[mid].shape[0]
        look = _appearance(frames[mid], (box[0] * W_, box[1] * H_, box[2] * W_, box[3] * H_))
        shots.append({"start": start, "end": end, "frames": idx, "dom": dom, "talk": talk,
                      "speech": _speech_fraction(words_abs, start, end), "face_h": mean_h,
                      "cx": sorted(d["cx"] for d in dom)[len(dom) // 2],
                      "cy": sorted(d["cy"] for d in dom)[len(dom) // 2], "look": look})
    return shots, (sw, sh)


def find_reactions(src, clip_start, clip_end, words_abs, pad=60.0, log=print):
    """Listener shots near the clip, best first: [{start, dur, cx, cy, score}],
    plus the analysed shots and the talking reference (for placement)."""
    import cv2
    t0, t1 = max(0.0, clip_start - pad), clip_end + pad
    shots, size = analyze(src, t0, t1, words_abs)
    if not shots:
        return [], size, [], None
    talks = sorted(s["talk"] for s in shots if s["speech"] > 0.5)
    if not talks:
        return [], size, shots, None
    # Talking shots sit well above listening ones; the split is relative to
    # this video (lighting, resolution, how much this person moves).
    ref = talks[int(len(talks) * 0.75)] if len(talks) > 3 else max(talks)
    speaker_shots = [s for s in shots if s["start"] < clip_end and s["end"] > clip_start
                     and s["talk"] >= 0.6 * ref and s["look"] is not None]
    speaker_looks = [s["look"] for s in speaker_shots]
    out = []
    for s in shots:
        if s["speech"] < 0.5 or s["talk"] > 0.45 * ref or s["look"] is None:
            continue
        if speaker_looks:
            dist = min(cv2.compareHist(s["look"], lk, cv2.HISTCMP_BHATTACHARYYA) for lk in speaker_looks)
            if dist < 0.35:
                continue            # that is the speaker, pausing — not a reaction
        else:
            dist = None
        # The most expressive REACT_LEN windows of the shot (a long listening
        # shot can give two different moments, >= 4 s apart).
        # A listener still says "yeah", "mm", "right" now and then: in the
        # audio those are the SPEAKER's words we keep, so showing a moving
        # mouth there looks like a dubbing error. Every frame of the window,
        # plus 0.4 s before and after, must have a still, closed mouth
        # (measured: listening windows sit at <= 0.003 lip change per frame
        # and a lip gap <= 0.008 of the face height; interjections at 0.007+
        # and 0.02+). Expressiveness then comes from the head and the smile
        # only, never from the lips.
        dom, n = s["dom"], max(1, int(REACT_LEN * FPS))
        still_talk = min(0.0035, 0.4 * ref)
        wins = []
        for i in range(0, max(1, len(dom) - n + 1)):
            guard = dom[max(0, i - 2):i + n + 2]
            lips = [d["lip"] for d in guard]
            talk_w = sum(abs(a - b) for a, b in zip(lips, lips[1:])) / max(1, len(lips) - 1)
            if talk_w > still_talk or max(lips) > 0.010:
                continue
            win = dom[i:i + n]
            motion = (max(d["cx"] for d in win) - min(d["cx"] for d in win)
                      + max(d["cy"] for d in win) - min(d["cy"] for d in win))
            smile = max(d["corner"] for d in win) - min(d["corner"] for d in win)
            wins.append((motion * 4 + smile * 3, i))
        taken = []
        for e, i in sorted(wins, reverse=True):
            start = s["start"] + i / FPS
            if start + REACT_LEN > s["end"]:
                start = max(s["start"], s["end"] - REACT_LEN)
            if any(abs(start - q) < 4 for q in taken):
                continue
            taken.append(start)
            out.append({"start": round(start, 2), "dur": REACT_LEN, "cx": s["cx"], "cy": s["cy"],
                        "score": round(e + (0.2 if dist and dist > 0.5 else 0), 4), "look": s["look"],
                        "shot": (round(s["start"], 1), round(s["end"], 1)), "talk": round(s["talk"], 4),
                        "look_dist": round(dist, 3) if dist is not None else None})
            if len(taken) >= 2:
                break
    out.sort(key=lambda r: -r["score"])
    log(f"   👀 Reactions: {len(shots)} shots read, {len(out)} listening moment(s) of another person")
    return out, size, shots, ref


def insertion_points(words_rel, duration, punchline_time=None, max_n=None):
    """Clip-relative times just after a line lands."""
    from viral_fx import keyword_score
    if SMOOTH:
        max_n = max_n or max(1, min(2, int(duration // 18)))
    else:
        max_n = max_n or max(1, min(3, int(duration // 12)))
    gap = 12 if SMOOTH else 6
    ends = []
    sent = []
    for w in words_rel:
        sent.append(w)
        if re.search(r"[.?!]$", w["text"].strip()):
            strength = max(keyword_score(x["text"]) for x in sent)
            ends.append((w["end"], strength))
            sent = []
    picks = []
    if punchline_time is not None:
        after = [t for t, _ in ends if t >= punchline_time]
        if after:
            picks.append(after[0])
    for t, _ in sorted(ends, key=lambda e: -e[1]):
        if len(picks) >= max_n:
            break
        if 2.0 <= t <= duration - 1.5 - REACT_LEN and all(abs(t - q) >= gap for q in picks):
            picks.append(t)
    return sorted(p + 0.08 for p in picks if 2.0 <= p <= duration - 1.5 - REACT_LEN)[:max_n]


def add_reactions(src, clip_path, clip_start, clip_end, transcript, out_path,
                  punchline_time=None, log=print):
    """Insert reaction cutaways into ``clip_path`` (vertical render of
    [clip_start, clip_end] of ``src``). Returns the report, or None when the
    source offers no usable reaction (nothing written then)."""
    words_abs = [{"text": (w.get("word") or "").strip(), "start": float(w["start"]), "end": float(w["end"])}
                 for sg in (transcript or {}).get("segments", []) for w in sg.get("words") or []]
    words_rel = [{"text": w["text"], "start": w["start"] - clip_start, "end": w["end"] - clip_start}
                 for w in words_abs if clip_start <= w["start"] < clip_end]
    duration = clip_end - clip_start
    points = insertion_points(words_rel, duration, punchline_time)
    if not points:
        log("   👀 Reactions: no sentence end to hang a reaction on — skipped.")
        return None
    import cv2
    cands, (sw, sh), shots, ref = find_reactions(src, clip_start, clip_end, words_abs, log=log)
    if len(cands) < len(points):
        wider = find_reactions(src, clip_start, clip_end, words_abs, pad=150.0, log=log)
        if len(wider[0]) > len(cands):
            cands, (sw, sh), shots, ref = wider

    def covering(t_abs):
        return next((s for s in shots if s["start"] <= t_abs < s["end"]), None)

    # Only cut away while the clip SHOWS the speaker: over a shot that is
    # already the listener (or anyone who looks like the reaction), a
    # "reaction" would change nothing on screen.
    pairs, used = [], []
    for t in points:
        on_screen = covering(clip_start + t)
        for c in cands:
            if c in used:
                continue
            if on_screen is not None:
                if ref and on_screen["talk"] <= 0.45 * ref:
                    break           # the clip already shows a listener here
                if (on_screen["look"] is not None and c["look"] is not None and
                        cv2.compareHist(on_screen["look"], c["look"], cv2.HISTCMP_BHATTACHARYYA) < 0.35):
                    continue        # same person as on screen: pick another
            used.append(c)
            pairs.append((t, c))
            break
    if not pairs:
        log("   👀 Reactions: no usable listener shot for this clip (single camera, or the clip "
            "already shows the listener) — skipped.")
        return None
    points, chosen = [p for p, _ in pairs], [c for _, c in pairs]

    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,r_frame_rate", "-of", "csv=p=0", clip_path],
                           capture_output=True, text=True).stdout.strip().split("\n")[0].split(",")
    cw, ch = int(probe[0]), int(probe[1])
    num, den = (probe[2] if len(probe) > 2 else "30/1").split("/")
    fps = round(float(num) / float(den or 1)) or 30
    tmp = tempfile.mkdtemp(prefix="react_")
    try:
        inputs, graph, cur = [], [], "[0:v]"
        for k, (t, c) in enumerate(zip(points, chosen)):
            # Full-height 9:16 crop centred on the listener (same framing
            # logic as the TRACK reframe), then scaled to the clip size.
            crop_h = sh
            crop_w = int(round(sh * cw / ch / 2) * 2)
            x = int(min(max(c["cx"] * sw - crop_w / 2, 0), sw - crop_w))
            seg = os.path.join(tmp, f"r{k}.mp4")
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{c['start']:.3f}", "-t", f"{c['dur']:.3f}",
                                "-i", src, "-vf", f"crop={crop_w}:{crop_h}:{x}:0,scale={cw}:{ch},setsar=1,fps={fps}",
                                "-an", *_encode_args(), seg],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(r.stderr[-400:])
            inputs += ["-itsoffset", f"{t:.3f}", "-i", seg]
            src_label = f"[{k + 1}:v]"
            if SMOOTH:
                # Both pictures exist during the fade (the speaker's shot runs
                # underneath), so this is a true dissolve, in and out.
                graph.append(f"{src_label}format=rgba,fade=t=in:st={t:.3f}:d={REACT_FADE}:alpha=1,"
                             f"fade=t=out:st={t + c['dur'] - REACT_FADE:.3f}:d={REACT_FADE}:alpha=1[rf{k}]")
                src_label = f"[rf{k}]"
            graph.append(f"{cur}{src_label}overlay=0:0:eof_action=pass:enable='between(t,{t:.3f},{t + c['dur']:.3f})'[o{k}]")
            cur = f"[o{k}]"
        graph.append(f"{cur}format=yuv420p[v]")
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip_path, *inputs,
                            "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "0:a?",
                            *_encode_args(), "-c:a", "copy",
                            "-movflags", "+faststart", out_path], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-600:])
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    report = [{"at": round(t, 2), "from": c["start"], "shot": c["shot"]} for t, c in zip(points, chosen)]
    at = ", ".join(f"{r['at']}s" for r in report)
    log(f"   👀 Reactions inserted: {at}")
    return report
