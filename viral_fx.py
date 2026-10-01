"""The "podcast shorts" look: captions and grade, rendered locally with ffmpeg.

Two presets, the same words in two faces:

* ``natural`` — 2-3 plain white words with a soft shadow, an accent colour on
  a real key word now and then (the clip's topic words and numbers always),
  no glow, no shake; a light grade and a soft vignette on the picture.
* ``premium`` — natural set in Montserrat ExtraBold, the geometric extra-bold
  the big podcast channels caption in. The house style.

The frame itself never moves here: the reframe (framing.py) holds the
speaker's head where an editor would. The jump zooms, shake, dips, glow,
"sharp look", spotlight, light streaks and music bed of the first versions
were removed on 1-oct-2026: measured on real clips, none of them read as
premium and nobody switched them on.

Layers, so it slots into the clip pipeline like everything else:
* ``apply_motion`` — the look (grade + vignette), on the canonical clip BEFORE
  the hook is burned;
* ``apply_captions`` — the preset's captions, as the last layer, with the
  channel name small under the words (``watermark``).
``apply`` does both in one encode. No AI call, no download, no GPU.

CLI (for tests): python viral_fx.py <clip.mp4> <metadata.json> <clip_index> <natural|premium> <out.mp4> [opts-json]
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from ffmpeg_utils import layer_encode_args

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
    # Calibrated on 15 top podcast shorts (Diary of a CEO, Shawn Ryan, Theo
    # Von, Huberman, Lex, Modern Wisdom, Peterson, Motiversity; 150 k-4.2 M
    # views): 2-3 plain white words with a soft shadow, an accent colour on
    # a real key word only now and then, no glow, no shake. The frame itself
    # is held by the reframe (framing.py); here there is no zoom at all.
    # Key words: one in every other caption (a real 6+ letter word), plus
    # always the clip's topic words (from its title / hook) and numbers.
    # The "punchy" / "clean" presets (glowing words, jump zooms, shake, dips)
    # were removed on 1-oct-2026 with the rest of the effects nobody used.
    "natural": {"max_words": 3, "max_chars": 16, "size": 64,
                "grade": "eq=contrast=1.04:saturation=1.05",
                "vignette": "PI/7", "caption_y": 1180, "key_every": 2, "key_min": 0.6,
                "accent": "#FFD84D", "calm": True},
}
# "premium": the natural preset set in a premium face. Liberation Sans is a
# system stand-in for Arial; the big podcast channels caption in a geometric
# extra-bold (Montserrat, Inter...). Same words, same colours, same place; the
# face is already extra bold so libass must not embolden it again (bold 0),
# its letters are wide so no extra spacing, and 72 px instead of 64: its
# capitals are lower for the same em size, and 72 is where it fills the same
# space as Liberation 64 (compared at 64 / 68 / 72 on three clips with
# broll_bench.py fonts). Montserrat is OFL (fonts/OFL-Montserrat.txt) and
# ships in fonts/, which the ass filter reads.
PRESETS["premium"] = {**PRESETS["natural"], "font": "Montserrat ExtraBold", "bold": 0, "spacing": 0, "size": 72}


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
        parts_text = []
        for k, w in enumerate(g):
            t = _esc(w["text"].upper())
            parts_text.append(f"{{\\c{_ass_color(color)}}}{t}{{\\c&HFFFFFF&}}" if color and k == best else t)
        x, y = width // 2, p["caption_y"]
        s, e = _ass_time(start), _ass_time(end)
        if p.get("calm"):
            # No pop: an 80 ms fade-in reads as calm, not as an effect.
            lines.append(f"Dialogue: 1,{s},{e},Main,,0,0,0,,{{\\an5\\pos({x},{y})\\fad(80,0)}}{' '.join(parts_text)}")
        else:
            pop = "\\fscx106\\fscy106\\t(0,80,\\fscx100\\fscy100)"
            lines.append(f"Dialogue: 1,{s},{e},Main,,0,0,0,,{{\\an5\\pos({x},{y}){pop}}}{' '.join(parts_text)}")
        if watermark:
            lines.append(f"Dialogue: 2,{s},{e},Mark,,0,0,0,,{{\\an5\\pos({x},{y + int(p['size'] * 0.95)})}}{_esc(watermark.upper())}")

    size = p["size"]
    font = p.get("font", FONT)          # the preset's face; Liberation Sans for the presets that name none
    if p.get("calm"):
        # Plain white, thin dark edge + soft drop shadow: readable on any
        # background without looking "designed".
        styles = [f"Style: Main,{font},{size},&H00FFFFFF,&H00FFFFFF,&H70000000,&H99000000,{p.get('bold', 1)},0,0,0,100,100,"
                  f"{p.get('spacing', 0.5)},0,1,2,2,5,0,0,0,1"]
        lines = [ln.replace(",Main,,0,0,0,,{", ",Main,,0,0,0,,{\\blur0.8") for ln in lines]
    else:
        styles = [f"Style: Main,{FONT},{size},&H00FFFFFF,&H00FFFFFF,&H80000000,&H90000000,1,0,0,0,100,100,0.5,0,1,3,2,5,0,0,0,1"]
        lines = [ln.replace(",Main,,0,0,0,,{", ",Main,,0,0,0,,{\\blur2") for ln in lines]
    styles.append(f"Style: Mark,{font},{max(18, size // 4)},&H90FFFFFF,&H00FFFFFF,&H00000000,&H00000000,{p.get('bold', 1)},0,0,0,100,100,2,0,1,0,0,5,0,0,0,1")

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


# --- the filter graph --------------------------------------------------------------

def build_graph(words, info, preset, opts, tmp, ass_path=None, motion=True):
    """Returns (filter_complex, extra_inputs, report)."""
    p = PRESETS[preset]
    W, H, fps, duration = info["w"], info["h"], info["fps"], info["duration"]
    opts = opts or {}
    extra, report, graph = [], {}, []
    cur = "[0:v]"
    if motion:
        # No zoom motion: the reframe (framing.py) already holds the speaker's
        # head where an editor would, and on a real clip (28-sep-2026) even
        # eased zoom glides read as jerky — zoompan rounds its window to whole
        # pixels, which shimmers on any slow zoom. The motion layer is the
        # look only: the preset's grade and a soft vignette.
        graph.append(f"{cur}{p['grade']},vignette=angle={p['vignette']}[g0]")
        cur = "[g0]"

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
        graph, extra, report = build_graph(words, info, preset, opts, tmp, ass_path=ass_path, motion=motion)
        # The captions are the delivered layer; the motion alone is re-encoded
        # again by the B-roll, the hook and the captions (ffmpeg_utils.layer_encode_args).
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", clip_path, *extra,
               "-filter_complex", graph, "-map", "[vout]", "-map", "0:a?",
               *layer_encode_args(["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"], final=captions),
               "-c:a", "copy", "-movflags", "+faststart", out_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {r.stderr[-900:]}")
        report.update(captions=n_caps)
        return report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def apply_motion(clip_path, words, preset, out_path, opts=None):
    """The look (grade + vignette), no captions: goes UNDER the hook."""
    return _render(clip_path, words, preset, out_path, motion=True, captions=False, opts=opts)


def apply_captions(clip_path, words, preset, out_path, watermark=None, topic=None):
    """The preset's captions only: the last layer, like every caption burn."""
    return _render(clip_path, words, preset, out_path, motion=False, captions=True, watermark=watermark,
                   topic=topic)


def apply(clip_path, words, preset, out_path, watermark=None, opts=None, topic=None):
    """Motion + captions in one encode (a clip without a hook, tests)."""
    return _render(clip_path, words, preset, out_path, motion=True, captions=True,
                   watermark=watermark, opts=opts, topic=topic)


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
