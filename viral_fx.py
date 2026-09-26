"""Viral edit presets: the "podcast shorts" look, rendered locally with ffmpeg.

Two presets, modelled on the reference shorts the user picked:

* ``punchy`` — one or two words at a time in the centre, big and bold, with
  a soft glow; key words cycle through vivid colours; hard "jump zooms"
  between tight and wide shots with a slow push inside each shot; a short
  camera shake on the strongest words; warm contrasty grade + vignette.
  (A glitch/flash layer was tried on the first test and dropped: too much.)
* ``clean`` — 2-4 words per caption with a dark soft shadow and one key word
  coloured; the same zooms, milder; a brief dip to black to punctuate.

Options (Clip Generator++ profiles), all off by default:
* ``smart_framing`` — the zoom is centred on the measured face and sized from
  it; tight on the hook and on the shots with the strongest words and the
  loudest delivery, wide elsewhere (never three tight shots in a row).
* ``look`` — sharper detail + a faint highlight bloom.
* ``spotlight`` — on the 2-3 strongest lines the vignette closes in around the
  face for ~0.55 s (the soft cousin of a flash cut).
* ``streaks`` — on zoom-in cuts: 3-frame motion blur + a light line sweeping at
  eye level.
* ``watermark`` — channel name, small, under the captions.

Layers, so it slots into the clip pipeline like everything else:
* ``apply_motion`` — zooms + options, on the canonical clip BEFORE the hook is
  burned, so the hook text is never zoomed or cropped;
* ``apply_captions`` — the preset's captions, as the last layer;
* ``mix_music`` — a ducked music bed brought to ~-11 LUFS.
``apply`` does motion + captions in one encode. No AI call, no download, no
GPU: key words, framing and moments are measured locally.

CLI (for tests): python viral_fx.py <clip.mp4> <metadata.json> <clip_index> <punchy|clean> <out.mp4> [opts-json]
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
FONT = "Liberation Sans"

PALETTE = ["#FFE14D", "#C77DFF", "#4DE8FF", "#FFB23F", "#5DFF9E"]

STOPWORDS = set("""a an the and or but if so to of in on at by for with from up down out over under again then
once here there when where why how all any both each few more most other some such no nor not only own same than
too very can will just don should now i me my we our you your he him his she her it its they them their what which
who whom this that these those am is are was were be been being have has had having do does did doing would could
ought i'm you're he's she's it's we're they're i've you've we've they've i'd you'd he'd she'd we'd they'd i'll
you'll he'll she'll we'll they'll isn't aren't wasn't weren't hasn't haven't hadn't doesn't don't didn't won't
wouldn't shan't shouldn't can't cannot couldn't mustn't let's that's who's what's here's there's when's where's
why's how's like just really yeah um uh okay ok gonna wanna got get gets thing things know mean kind sort
allows allow people person something anything everything nothing someone anyone everyone because before after
think thought going actually basically literally probably maybe little pretty whatever always never also still
about around another other others would could should might must said says saying doing being having make makes
made take takes took come comes came give gives gave want wants wanted need needs needed look looks looked""".split())

PRESETS = {
    "punchy": {"max_words": 2, "max_chars": 11, "size": 100, "zoom_wide": 1.04, "zoom_tight": 1.20,
               "shot": (2.0, 3.0), "push": 0.035, "shake": 7.0, "dip": False,
               "grade": "eq=contrast=1.12:saturation=1.20:gamma=0.97,colorbalance=rs=0.05:gs=0.01:bs=-0.05",
               "vignette": "PI/5", "caption_y": 1010, "key_every": 2},
    "clean": {"max_words": 4, "max_chars": 18, "size": 54, "zoom_wide": 1.03, "zoom_tight": 1.13,
              "shot": (2.8, 4.0), "push": 0.02, "shake": 0.0, "dip": True,
              "grade": "eq=contrast=1.05:saturation=1.08",
              "vignette": "PI/6", "caption_y": 1060, "key_every": 1},
    # Calibrated on 15 top podcast shorts (Diary of a CEO, Shawn Ryan, Theo
    # Von, Huberman, Lex, Modern Wisdom, Peterson, Motiversity; 150 k-4.2 M
    # views): 2-3 plain white words with a soft shadow, an accent colour on
    # a real key word only now and then, no glow, no shake. Without a
    # second camera they HOLD a shot 5-10 s, so the reframe happens only at a
    # sentence end, gently (1.00 <-> 1.08) with a slow push inside the shot.
    # Key words: one in every other caption (a real 6+ letter word), plus
    # always the clip's topic words (from its title / hook) and numbers.
    "natural": {"max_words": 3, "max_chars": 16, "size": 64, "zoom_wide": 1.0, "zoom_tight": 1.08,
                "shot": (6.0, 9.0), "push": 0.015, "shake": 0.0, "dip": False,
                "grade": "eq=contrast=1.04:saturation=1.05",
                "vignette": "PI/7", "caption_y": 1250, "key_every": 2, "key_min": 0.6,
                "accent": "#FFD84D", "sentence_cuts": True,
                "tight_face": 0.28, "wide_face": 0.22, "zoom_max": 1.18, "tight_min": 1.06, "reframe_step": 0.04},
}


# --- words ---------------------------------------------------------------------

def clip_words(transcript, start, end):
    """Words of [start, end] in clip time, cleaned for display."""
    out = []
    for seg in (transcript or {}).get("segments", []) or []:
        for w in seg.get("words") or []:
            ws, we = float(w.get("start", 0)), float(w.get("end", 0))
            if we <= start or ws >= end:
                continue
            text = (w.get("word") or "").strip()
            if not text:
                continue
            out.append({"text": text, "start": max(0.0, ws - start), "end": min(end, we) - start})
    return out


def _bare(word):
    return re.sub(r"[^\w'$%]", "", word.lower())


def keyword_score(word, topic=None):
    """How much a word deserves colour/emphasis: numbers, money, the clip's
    topic words (``topic``: bare words of its title / hook), long rare words."""
    b = _bare(word)
    if not b or b in STOPWORDS:
        return 0.0
    in_topic = bool(topic) and (b in topic or b.rstrip("s") in topic)
    # A contraction ("there'll") or a stutter ("t-t-t-tick") is never the key
    # word, however long it is — unless it is the topic itself.
    if not in_topic and ("'" in b or re.search(r"\b(\w{1,2})-\1", word.lower())):
        return 0.0
    score = min(len(b), 10) / 10.0
    if re.search(r"\d|\$|%", word):
        score += 1.0
    if in_topic:
        score += 0.8 + (0.3 if len(b) <= 4 else 0.0)
    return score


def topic_words(*texts):
    """Bare 4+ letter content words of a clip's title / hook."""
    out = set()
    for t in texts:
        for w in re.findall(r"[\w'$%]+", t or ""):
            b = _bare(w)
            # 4+ letter content words, and acronyms written in capitals (AI, MDMA)
            if (len(b) >= 4 or (len(w) >= 2 and w.isupper())) and b not in STOPWORDS:
                out.add(b)
                out.add(b.rstrip("s"))
    return out


def group_words(words, max_words, max_chars):
    """Caption groups. Short function words ride with their neighbour, so a
    1-word preset still shows "A GOAL" instead of a lone "A"."""
    groups, cur = [], []
    for w in words:
        cand = cur + [w]
        text = " ".join(x["text"] for x in cand)
        gap = (w["start"] - cur[-1]["end"]) if cur else 0
        fits = len(cand) <= max_words and len(text) <= max_chars
        only_small = all(len(_bare(x["text"])) <= 3 for x in cur)
        if cur and gap < 0.6 and (fits or (only_small and len(cand) <= 3 and len(text) <= max_chars + 4)):
            cur = cand
        else:
            if cur:
                groups.append(cur)
            cur = [w]
    if cur:
        groups.append(cur)
    return groups


# --- captions (ASS) ------------------------------------------------------------

def _ass_time(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_color(hex_color, alpha=0):
    h = hex_color.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}&"


def _esc(text):
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def build_ass(words, preset, width=1080, height=1920, watermark=None, topic=None):
    p = PRESETS[preset]
    groups = group_words(words, p["max_words"], p["max_chars"])
    # Colour one word in every ``key_every`` groups — the strongest of the group.
    lines = []
    colour_i = 0
    for gi, g in enumerate(groups):
        start = g[0]["start"]
        end = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else g[-1]["end"] + 0.3
        end = min(end, g[-1]["end"] + 0.6)
        best = max(range(len(g)), key=lambda k: keyword_score(g[k]["text"], topic))
        score = keyword_score(g[best]["text"], topic)
        # The rhythm (every ``key_every`` captions) never skips a topic word
        # or a number (score >= 1.2).
        colored = score >= p.get("key_min", 0.5) and (gi % p["key_every"] == 0 or score >= 1.2)
        color = (p.get("accent") or PALETTE[colour_i % len(PALETTE)]) if colored else None
        if colored:
            colour_i += 1
        parts_text, parts_glow = [], []
        for k, w in enumerate(g):
            t = _esc(w["text"].upper())
            if color and k == best:
                parts_text.append(f"{{\\c{_ass_color(color)}}}{t}{{\\c&HFFFFFF&}}")
                parts_glow.append(f"{{\\3c{_ass_color(color)}}}{t}{{\\3c&HFFFFFF&}}")
            else:
                parts_text.append(t)
                parts_glow.append(t)
        x, y = width // 2, p["caption_y"]
        s, e = _ass_time(start), _ass_time(end)
        if preset == "punchy":
            pop = "\\fscx118\\fscy118\\t(0,90,\\fscx100\\fscy100)"
            # Layer 0: a blurred halo (white, or the key word's colour); layer 1: crisp text.
            lines.append(f"Dialogue: 0,{s},{e},Glow,,0,0,0,,{{\\an5\\pos({x},{y}){pop}}}{' '.join(parts_glow)}")
            lines.append(f"Dialogue: 1,{s},{e},Main,,0,0,0,,{{\\an5\\pos({x},{y}){pop}}}{' '.join(parts_text)}")
        elif preset == "natural":
            # No pop: an 80 ms fade-in reads as calm, not as an effect.
            lines.append(f"Dialogue: 1,{s},{e},Main,,0,0,0,,{{\\an5\\pos({x},{y})\\fad(80,0)}}{' '.join(parts_text)}")
        else:
            pop = "\\fscx106\\fscy106\\t(0,80,\\fscx100\\fscy100)"
            lines.append(f"Dialogue: 1,{s},{e},Main,,0,0,0,,{{\\an5\\pos({x},{y}){pop}}}{' '.join(parts_text)}")
        if watermark:
            lines.append(f"Dialogue: 2,{s},{e},Mark,,0,0,0,,{{\\an5\\pos({x},{y + int(p['size'] * 0.95)})}}{_esc(watermark.upper())}")

    size = p["size"]
    if preset == "punchy":
        styles = [
            f"Style: Main,{FONT},{size},&H00FFFFFF,&H00FFFFFF,&H60000000,&H90000000,1,0,0,0,100,100,1,0,1,2,2,5,0,0,0,1",
            f"Style: Glow,{FONT},{size},&H30FFFFFF,&H00FFFFFF,&H00FFFFFF,&HFF000000,1,0,0,0,100,100,1,0,1,11,0,5,0,0,0,1",
        ]
        # Blur the halo layer.
        lines = [ln.replace(",Glow,,0,0,0,,{", ",Glow,,0,0,0,,{\\blur18") for ln in lines]
    elif preset == "natural":
        # Plain white, thin dark edge + soft drop shadow: readable on any
        # background without looking "designed".
        styles = [f"Style: Main,{FONT},{size},&H00FFFFFF,&H00FFFFFF,&H70000000,&H99000000,1,0,0,0,100,100,0.5,0,1,2,2,5,0,0,0,1"]
        lines = [ln.replace(",Main,,0,0,0,,{", ",Main,,0,0,0,,{\\blur0.8") for ln in lines]
    else:
        styles = [f"Style: Main,{FONT},{size},&H00FFFFFF,&H00FFFFFF,&H80000000,&H90000000,1,0,0,0,100,100,0.5,0,1,3,2,5,0,0,0,1"]
        lines = [ln.replace(",Main,,0,0,0,,{", ",Main,,0,0,0,,{\\blur2") for ln in lines]
    styles.append(f"Style: Mark,{FONT},{max(18, size // 4)},&H90FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,2,0,1,0,0,5,0,0,0,1")

    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        *styles, "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *lines, "",
    ]), groups


# --- analysis: faces + loudness -------------------------------------------------

def _probe(clip_path):
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate:format=duration", "-of", "json", clip_path],
        capture_output=True, text=True, check=True).stdout)
    st = probe["streams"][0]
    num, den = (st.get("r_frame_rate") or "30/1").split("/")
    return {"w": int(st["width"]), "h": int(st["height"]),
            "fps": round(float(num) / float(den or 1)) or 30,
            "duration": float(probe["format"]["duration"])}


def face_track(clip_path, width, height, every=0.5):
    """[(t, cx, cy_eyes, face_h)] in 0..1 frame units, the largest face per
    sample (MediaPipe on 2 fps / 360 px frames piped from ffmpeg: fast)."""
    try:
        import numpy as np
        import mediapipe as mp
    except ImportError:
        return []
    sw = 360
    sh = int(round(height * sw / width / 2) * 2)
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", clip_path, "-vf", f"fps={1 / every:g},scale={sw}:{sh}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    raw = proc.stdout
    frame_bytes = sw * sh * 3
    out = []
    with mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5) as det:
        for k in range(len(raw) // frame_bytes):
            img = np.frombuffer(raw[k * frame_bytes:(k + 1) * frame_bytes], dtype=np.uint8).reshape(sh, sw, 3)
            res = det.process(img)
            if not res.detections:
                continue
            best = max(res.detections, key=lambda d: d.location_data.relative_bounding_box.height)
            b = best.location_data.relative_bounding_box
            out.append((k * every, b.xmin + b.width / 2, b.ymin + b.height * 0.42, b.height))
    return out


def loudness_track(clip_path):
    """[(t, momentary LUFS)] every 100 ms."""
    r = subprocess.run(["ffmpeg", "-v", "verbose", "-hide_banner", "-i", clip_path, "-vn",
                        "-af", "ebur128=framelog=verbose", "-f", "null", "-"], capture_output=True, text=True)
    return [(float(t), float(m)) for t, m in re.findall(r"t:\s*([\d.]+)\s+TARGET:.*?M:\s*(-?[\d.]+)", r.stderr)
            if float(m) > -70]


def _median(vals, default):
    vals = sorted(vals)
    return vals[len(vals) // 2] if vals else default


# --- shots -------------------------------------------------------------------------

def shot_cuts(words, duration, lo, hi, sentences=False):
    """Cut points for the zooms, snapped to gaps between words (never mid-word).
    ``sentences``: prefer the gap right after a sentence end (. ? !), falling
    back to any gap when a sentence runs past the window."""
    gaps = [w["start"] for w in words[1:]]
    ends = ([b["start"] for a, b in zip(words, words[1:]) if re.search(r"[.?!]$", a["text"].strip())]
            if sentences else [])
    cuts, t = [], 0.0
    while True:
        target = t + (lo + hi) / 2
        if target >= duration - lo * 0.6:
            break
        near = [g for g in ends if t + lo <= g <= t + hi] or [g for g in gaps if t + lo <= g <= t + hi]
        c = min(near, key=lambda g: abs(g - target)) if near else target
        cuts.append(round(c, 3))
        t = c
    return cuts


# Face height (fraction of the frame) each framing aims for, and the zoom
# ceiling: past ~1.4x the upscale from a 1080p landscape source turns soft.
TIGHT_FACE, WIDE_FACE, ZOOM_MAX = 0.34, 0.22, 1.40


def plan_shots(words, duration, preset, faces, loud, smart):
    """Shots with a zoom and a centre. Smart framing: tight on the hook and on
    the shots that carry the strongest words and the loudest delivery, wide
    elsewhere; the zoom is sized from the measured face and centred on it (eyes
    at ~42 % of the frame). Otherwise: plain alternation around the centre."""
    p = PRESETS[preset]
    cuts = shot_cuts(words, duration, *p["shot"], sentences=bool(p.get("sentence_cuts")))
    bounds = [0.0] + cuts + [duration + 1]
    shots = [{"a": bounds[i], "b": bounds[i + 1]} for i in range(len(bounds) - 1)]
    if not smart:
        for i, sh in enumerate(shots):
            sh.update(z=p["zoom_tight"] if i % 2 else p["zoom_wide"], cx=0.5, cy=0.5, tight=bool(i % 2))
        return shots

    ref_m = _median([m for _, m in loud], -20.0)
    for sh in shots:
        ws = [w for w in words if sh["a"] <= w["start"] < sh["b"]]
        kw = max([keyword_score(w["text"]) for w in ws] or [0.0])
        ms = [m for t, m in loud if sh["a"] <= t < sh["b"]]
        energy = (max(ms) - ref_m) / 6.0 if ms else 0.0
        sh["emphasis"] = kw + max(-0.5, min(1.0, energy))
        fs = [f for f in faces if sh["a"] - 0.25 <= f[0] <= sh["b"] + 0.25]
        sh["cx"] = _median([f[1] for f in fs], None)
        sh["cy"] = _median([f[2] for f in fs], None)
        sh["fh"] = _median([f[3] for f in fs], None)
    # No face in a shot: keep the last known framing (a cutaway, a hand...).
    last = (0.5, 0.45, None)
    for sh in shots:
        if sh["cx"] is None:
            sh["cx"], sh["cy"], sh["fh"] = last
        last = (sh["cx"], sh["cy"], sh["fh"])

    ranked = sorted(sh["emphasis"] for sh in shots)
    cutoff = ranked[len(ranked) // 2] if ranked else 0
    run = 0
    for i, sh in enumerate(shots):
        tight = i == 0 or sh["emphasis"] > cutoff
        if tight and run >= 2:          # never three tight shots in a row
            tight = False
        run = run + 1 if tight else 0
        sh["tight"] = tight
        fh = sh["fh"]
        if fh:
            z = (p.get("tight_face", TIGHT_FACE) if tight else p.get("wide_face", WIDE_FACE)) / fh
            z = max(1.0, min(p.get("zoom_max", ZOOM_MAX) if tight else 1.18, z))
        else:
            z = p["zoom_tight"] if tight else p["zoom_wide"]
        if tight:
            z = max(z, p.get("tight_min", 1.15))   # a cut must read as a cut
        # Two shots of the same kind in a row still get a visible reframe (a
        # few % closer, the other way next time): the reference shorts change
        # the picture every 2-3 s, a 10 s static wide shot is where people swipe.
        if i and shots[i - 1]["tight"] == tight and abs(shots[i - 1]["z"] - z) < 0.05:
            step = p.get("reframe_step", 0.07)
            z = z + step if shots[i - 1]["z"] <= z else max(1.0, z - step)
            if abs(shots[i - 1]["z"] - z) < 0.05:
                z = shots[i - 1]["z"] + step
        sh["z"] = round(min(z, p.get("zoom_max", ZOOM_MAX)), 3)
    return shots


def _nest(shots, key, var="it"):
    expr = f"{shots[-1][key]}"
    for sh in reversed(shots[:-1]):
        expr = f"if(lt({var},{sh['b']:.3f}),{sh[key]},{expr})"
    return expr


def _between_sum(windows, var="it"):
    return "+".join(f"between({var},{a:.3f},{b:.3f})" for a, b in windows) or "0"


def _crop_origin(sh, W, H):
    """Top-left of the zoomed window (input px) for a shot, as zoompan does it."""
    z = sh["z"]
    x = min(max(sh["cx"] * W - W / z / 2, 0), W - W / z)
    y = min(max(sh["cy"] * H - H / z * 0.42, 0), H - H / z)
    return x, y


def _out_point(sh, W, H):
    """Where the shot's face centre lands in the output frame (px)."""
    x0, y0 = _crop_origin(sh, W, H)
    return (sh["cx"] * W - x0) * sh["z"], (sh["cy"] * H - y0) * sh["z"]


def spotlight_moments(words, duration, hints=None, loud=None, max_n=None):
    """The strongest lines, ~one per 10 s: the AI's punchline when known, then
    the words that are both strong (long / numbers) AND said louder than the
    speaker's usual level. Never in the first 1.5 s, >= 7 s apart."""
    max_n = max_n or max(1, min(4, int(duration // 10)))
    ref = _median([m for _, m in loud or []], None)

    def energy(t):
        if ref is None:
            return 0.0
        ms = [m for tt, m in loud if t - 0.2 <= tt <= t + 0.6]
        return (max(ms) - ref) / 6.0 if ms else 0.0

    picks = []
    if hints and hints.get("punchline_time") is not None:
        picks.append(float(hints["punchline_time"]))
    scored = sorted(((keyword_score(w["text"]) + max(-0.3, min(0.8, energy(w["start"]))), w["start"])
                     for w in words if keyword_score(w["text"]) >= 0.5), reverse=True)
    for score, t in scored:
        if len(picks) >= max_n or score < 0.7:
            break
        if 1.5 < t < duration - 1 and all(abs(t - q) >= 7 for q in picks):
            picks.append(t)
    return sorted(picks)[:max_n]


# --- streak overlay (light line), generated per render ------------------------------

def _streak_frames(folder, width, fps=30, seconds=0.5):
    """A soft horizontal light line sweeping across, alpha in-out. PNG frames."""
    from PIL import Image
    import numpy as np
    os.makedirs(folder, exist_ok=True)
    n = max(8, int(fps * seconds))
    hgt = 120
    ys = np.arange(hgt) - hgt / 2
    core = np.exp(-(ys / 2.2) ** 2)          # thin bright core
    glow = np.exp(-(ys / 14.0) ** 2) * 0.35  # soft halo
    vert = np.clip(core + glow, 0, 1)
    xs = np.linspace(0, 1, width)
    for k in range(n):
        ph = k / (n - 1)
        centre = 0.25 + 0.5 * ph
        horiz = np.exp(-((xs - centre) / 0.28) ** 2)
        alpha = (np.outer(vert, horiz) * math.sin(math.pi * ph) * 0.55 * 255).astype(np.uint8)
        rgba = np.zeros((hgt, width, 4), dtype=np.uint8)
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = 225, 238, 255
        rgba[..., 3] = alpha
        Image.fromarray(rgba, "RGBA").save(os.path.join(folder, f"s_{k:02d}.png"))
    return os.path.join(folder, "s_%02d.png"), hgt


# --- the filter graph --------------------------------------------------------------

def build_graph(words, info, preset, opts, faces, loud, tmp, ass_path=None, motion=True):
    """Returns (filter_complex, extra_inputs, report)."""
    p = PRESETS[preset]
    W, H, fps, duration = info["w"], info["h"], info["fps"], info["duration"]
    opts = opts or {}
    extra, report, graph = [], {}, []
    cur = "[0:v]"
    if motion:
        shots = plan_shots(words, duration, preset, faces, loud, bool(opts.get("smart_framing")))
        report["shots"] = [{"a": round(sh["a"], 2), "z": sh["z"], "tight": sh["tight"]} for sh in shots]
        z_base = _nest(shots, "z")
        seg_a = _nest([dict(sh, a_=round(sh["a"], 3)) for sh in shots], "a_")
        seg_len = _nest([dict(sh, l_=round(max(0.5, sh["b"] - sh["a"]), 3)) for sh in shots], "l_")
        z_expr = f"({z_base})+{p['push']}*(it-({seg_a}))/({seg_len})"
        cx, cy = _nest(shots, "cx"), _nest(shots, "cy")
        shake_x = shake_y = "0"
        if p["shake"]:
            picked = []
            for wd in sorted(words, key=lambda w: keyword_score(w["text"]), reverse=True):
                if keyword_score(wd["text"]) < 0.8:
                    break
                if all(abs(wd["start"] - q) > 2.5 for q in picked):
                    picked.append(wd["start"])
            wins = _between_sum([(t, t + 0.35) for t in picked])
            amp = p["shake"]
            shake_x = f"({amp}*sin(it*53)*({wins}))"
            shake_y = f"({amp * 0.7}*cos(it*41)*({wins}))"
        x_expr = f"clip(({cx})*iw-iw/zoom/2,0,iw-iw/zoom)+{shake_x}"
        y_expr = f"clip(({cy})*ih-ih/zoom*0.42,0,ih-ih/zoom)+{shake_y}"
        graph.append(f"{cur}zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d=1:s={W}x{H}:fps={fps},"
                     f"{p['grade']}[g0]")
        cur = "[g0]"

        if opts.get("look"):
            # Crisper detail + a faint highlight bloom: reads as "HD" on a phone
            # and moves the image away from the raw re-upload.
            # The bloom is blended in RGB: in YUV a screen blend shifts the
            # chroma planes (pink, then grey-washed on the first tests).
            # Blurred at a quarter of the size — same look, a fraction of the CPU.
            graph.append(f"{cur}unsharp=5:5:0.75:5:5:0,format=gbrp,split[l0][l1]")
            graph.append(f"[l1]scale={W // 4}:{H // 4},curves=all='0/0 0.62/0 1/1',gblur=sigma=6,"
                         f"scale={W}:{H}[lb]")
            graph.append("[l0][lb]blend=all_mode=screen:all_opacity=0.18,format=yuv420p[g1]")
            cur = "[g1]"

        # Vignette, plus the spotlight: on the strongest lines the edges close
        # in around the face for ~0.55 s and the face lifts a touch. Gentle by
        # design (no flash): it reads as the light tightening, not an effect.
        base_angle = p["vignette"]
        if opts.get("spotlight"):
            moments = spotlight_moments(words, duration, opts.get("hints"), loud)
            report["spotlight"] = moments
            d = 0.55
            env = "+".join(f"between(t,{a:.3f},{a + d:.3f})*sin(PI*(t-{a:.3f})/{d})" for a in moments) or "0"
            x0, y0 = f"{W // 2}", f"{H // 2}"
            for a in reversed(moments):
                sh = next((s for s in shots if s["a"] <= a < s["b"]), shots[-1])
                ox, oy = _out_point(sh, W, H)
                x0 = f"if(between(t,{a:.3f},{a + d:.3f}),{round(ox)},{x0})"
                y0 = f"if(between(t,{a:.3f},{a + d:.3f}),{round(oy)},{y0})"
            lift = _between_sum([(a, a + d) for a in moments], "t")
            graph.append(f"{cur}vignette=angle='{base_angle}+0.42*({env})':x0='{x0}':y0='{y0}':eval=frame,"
                         f"eq=brightness=0.035:enable='{lift}'[g2]")
        else:
            graph.append(f"{cur}vignette=angle={base_angle}[g2]")
        cur = "[g2]"

        if p["dip"]:
            cuts = [sh["a"] for sh in shots[1:]]
            if len(cuts) > 1:
                dips = [(c - 0.06, c + 0.10) for c in cuts[1::3][:3]]
                graph.append(f"{cur}eq=brightness=-0.55:enable='{_between_sum(dips, 't')}'[g3]")
                cur = "[g3]"

        if opts.get("streaks"):
            # On zoom-IN cuts only (max one every 6 s): 3-frame motion blur so
            # the jump reads as a camera move, and a light line sweeping at
            # eye level.
            ins = []
            for prev, sh in zip(shots, shots[1:]):
                if sh["z"] > prev["z"] + 0.05 and all(sh["a"] - q >= 6 for q in ins):
                    ins.append(sh["a"])
            report["streaks"] = ins
            if ins:
                blur_en = _between_sum([(c - 0.04, c + 0.08) for c in ins], "t")
                graph.append(f"{cur}tmix=frames=3:weights='1 2 1':enable='{blur_en}'[g4]")
                cur = "[g4]"
                pattern, sh_h = _streak_frames(os.path.join(tmp, "streak"), W, fps)
                for k, c in enumerate(ins):
                    idx = k + 1
                    extra += ["-itsoffset", f"{max(0.0, c - 0.05):.3f}", "-framerate", str(fps), "-i", pattern]
                    sh = next(s for s in shots if s["a"] == c)
                    _, oy = _out_point(sh, W, H)
                    y = int(min(max(oy - sh_h / 2, 0), H - sh_h))
                    graph.append(f"{cur}[{idx}:v]overlay=x=0:y={y}:eof_action=pass[s{k}]")
                    cur = f"[s{k}]"

    wm = opts.get("watermark")
    if wm and not ass_path and motion:
        # Without the preset's captions the watermark still sits low-centre.
        safe = re.sub(r"[^\w .@&-]", "", wm).upper()
        graph.append(f"{cur}drawtext=fontfile='{os.path.join(FONT_DIR, 'Anton-Regular.ttf')}':text='{safe}':"
                     f"fontsize={int(H * 0.012)}:fontcolor=white@0.55:x=(w-tw)/2:y=h*0.62[wm]")
        cur = "[wm]"
    if ass_path:
        graph.append(f"{cur}ass='{ass_path}':fontsdir='{FONT_DIR}'[cap]")
        cur = "[cap]"
    graph.append(f"{cur}format=yuv420p[vout]")
    return ";".join(graph), extra, report


def _render(clip_path, words, preset, out_path, motion, captions, watermark=None, opts=None, topic=None):
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset}")
    opts = dict(opts or {})
    if watermark:
        opts["watermark"] = watermark
    info = _probe(clip_path)
    tmp = tempfile.mkdtemp(prefix="vfx_")
    try:
        ass_path, n_caps = None, 0
        if captions:
            ass_text, groups = build_ass(words, preset, info["w"], info["h"], opts.get("watermark"), topic=topic)
            n_caps = len(groups)
            ass_path = os.path.join(tmp, "captions.ass")
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(ass_text)
        need_faces = motion and (opts.get("smart_framing") or opts.get("spotlight") or opts.get("streaks"))
        faces = face_track(clip_path, info["w"], info["h"]) if need_faces else []
        loud = loudness_track(clip_path) if motion and (opts.get("smart_framing") or opts.get("spotlight")) else []
        graph, extra, report = build_graph(words, info, preset, opts, faces, loud, tmp,
                                           ass_path=ass_path, motion=motion)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", clip_path, *extra,
               "-filter_complex", graph, "-map", "[vout]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
               "-c:a", "copy", "-movflags", "+faststart", out_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {r.stderr[-900:]}")
        report.update(captions=n_caps, faces=len(faces))
        return report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def apply_motion(clip_path, words, preset, out_path, opts=None):
    """Zooms (+ smart framing, look, spotlight, streaks), no captions: goes
    UNDER the hook."""
    return _render(clip_path, words, preset, out_path, motion=True, captions=False, opts=opts)


def apply_captions(clip_path, words, preset, out_path, watermark=None, topic=None):
    """The preset's captions only: the last layer, like every caption burn."""
    return _render(clip_path, words, preset, out_path, motion=False, captions=True, watermark=watermark,
                   topic=topic)


def apply(clip_path, words, preset, out_path, watermark=None, opts=None, topic=None):
    """Motion + captions in one encode (a clip without a hook, tests)."""
    return _render(clip_path, words, preset, out_path, motion=True, captions=True,
                   watermark=watermark, opts=opts, topic=topic)


# --- music bed ------------------------------------------------------------------------

def mix_music(clip_path, music_path, out_path, volume=0.22, target_lufs=-11.0):
    """A steady music bed under the voice, then the mix brought to ~-11 LUFS.

    Steady is the point: the first version ducked fast (350 ms release) and
    ran a dynamic loudnorm, so the music swelled in every pause between
    sentences and the whole mix breathed — "trop de haut et de bas". Now:
    * the track itself is levelled first (its own drops and builds flattened);
    * the duck is slow and shallow (2.2:1, 1.8 s release): it settles under
      the speech and stays there instead of pumping between words (music
      level jumps > 3 dB in 30 s: 171 before, 12 now — fewer than the raw
      track's own 13);
    * loudness is set ONCE with a fixed gain measured on the mix (two
      passes) plus a peak limiter — no gain riding at all."""
    dur = _probe(clip_path)["duration"]
    fade = max(0.0, dur - 1.5)
    tmp = tempfile.mkdtemp(prefix="mus_")
    try:
        mix_wav = os.path.join(tmp, "mix.wav")
        graph = (f"[1:a]aformat=channel_layouts=stereo:sample_rates=48000,"
                 f"acompressor=threshold=0.08:ratio=4:attack=80:release=1200:makeup=2,"
                 f"volume={volume},afade=t=out:st={fade:.2f}:d=1.5[m];"
                 # A light voice leveller (2.5:1): quiet and loud phrases sit
                 # closer together, like the reference shorts (mix spread
                 # 6.9 -> 5.3 dB between the median and the quietest 10 %).
                 f"[0:a]aformat=channel_layouts=stereo:sample_rates=48000,"
                 f"acompressor=threshold=0.1:ratio=2.5:attack=15:release=200:makeup=1.6,asplit=2[v][sc];"
                 f"[m][sc]sidechaincompress=threshold=0.03:ratio=2.2:attack=250:release=1800:knee=6[md];"
                 f"[v][md]amix=inputs=2:duration=first:normalize=0[a]")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip_path, "-stream_loop", "-1",
                            "-i", music_path, "-filter_complex", graph, "-map", "[a]", "-t", f"{dur:.3f}",
                            "-c:a", "pcm_s16le", mix_wav], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"music mix failed: {r.stderr[-600:]}")
        m = subprocess.run(["ffmpeg", "-hide_banner", "-i", mix_wav, "-af", "ebur128", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
        found = re.findall(r"I:\s+(-?[\d.]+) LUFS", m)
        gain = (target_lufs - float(found[-1])) if found else 0.0
        gain = max(-12.0, min(12.0, gain))
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip_path, "-i", mix_wav,
                            "-filter_complex", f"[1:a]volume={gain:.2f}dB,alimiter=limit=0.89:level=false[a]",
                            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                            "-ar", "48000", "-movflags", "+faststart", out_path], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"music mix failed: {r.stderr[-600:]}")
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print(__doc__)
        sys.exit(2)
    clip, meta, idx, preset, out = sys.argv[1:6]
    options = json.loads(sys.argv[6]) if len(sys.argv) > 6 else {}
    with open(meta, encoding="utf-8") as f:
        data = json.load(f)
    c = data["shorts"][int(idx)]
    ws = clip_words(data.get("transcript"), float(c["start"]), float(c["end"]))
    print(apply(clip, ws, preset, out, options.pop("watermark", None), options))
