"""The "podcast shorts" look: captions and grade, rendered locally with ffmpeg.

Three presets, the same words in three faces:

* ``natural`` — 2-3 plain white words with a soft shadow, an accent colour on
  a real key word now and then (the clip's topic words and numbers always),
  no glow, no shake; a light grade and a soft vignette on the picture.
* ``premium`` — natural set in Montserrat ExtraBold, the geometric extra-bold
  the big podcast channels caption in, a little lower (under the mouth of
  the premium framing), lit word by word as it is said, and since 5-oct-2026
  big with a solid black edge (read with the sound off, on a phone, over a
  bright drawing). The house style until 9-oct-2026.
* ``oneword`` — the « références » recipe (OptimalHealth): one word at a time
  in capitals, mid-screen, a golden word now and then, the credit and the
  channel's name small at the top (see PRESETS). The house style since
  9-oct-2026 (plus.CAPTION_STYLE; "premium" stays one switch away).

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
# Since 2-oct-2026 (the subtitle study, chosen by the channel):
# * caption_y 1275 (66.4 % of the height) instead of 1180: the premium framing
#   (framing.py, same day) sets faces lower and bigger, and at 1180 the
#   captions sat on the speaker's mouth in 68 % of the frames (MediaPipe, one
#   frame every 0.5 s; 5 % with the old framing). At 1275: 0 %, still inside
#   the band every app leaves free (26-68 % of the height);
# * "lit": the spoken word lights up (_lit_word) instead of the plain fade.
# Since 5-oct-2026 (decision 1 of the "step up", the image study's C1/idea 2):
# captions read with the sound off, on a phone, even over a bright full-screen
# drawing. At 72 the capitals measured 32 px (11.6 px on a 390 px phone), 20 %
# less than the published shorts (39-40 px), and over a bright picture 12 of
# 23 captions fell under a 3:1 contrast. Now:
# * size 100 (capitals ~44 px, 16 px on a phone) and at most 14 characters a
#   caption (~2.2 words), so a caption stays inside the safe width (6-84 % of
#   the frame, the Shorts buttons on the right: ``safe_x``) — _fit_scale sets
#   the rare wider one a little smaller instead of under the buttons;
# * a thick, almost solid black edge (5 px, alpha 0x20) and a 3 px shadow:
#   the word holds on a white coat or a white MRI sheet;
# * the words not said yet at 70 % (LIT_DIM) instead of 42 %.
# Same place (caption_y 1275), same face, same yellow, same lit word.
# ``outline`` / ``shadow`` / ``edge_alpha`` / ``shadow_alpha``: the calm
# style's edge, read by build_ass (natural keeps 2 / 2 / 0x70 / 0x99).
PRESETS["premium"] = {**PRESETS["natural"], "font": "Montserrat ExtraBold", "bold": 0, "spacing": 0, "size": 100,
                      "max_chars": 14, "caption_y": 1275, "lit": True, "safe_x": (0.06, 0.84),
                      "outline": 5, "shadow": 3, "edge_alpha": 0x20, "shadow_alpha": 0x60}
# "oneword" (9-oct-2026, the « références » recipe, OptimalHealth (387 k) as THE
# model; RECETTE_REFERENCES.md section 2): ONE word at a time, in capitals,
# white with a thick solid black edge, around the middle of the screen, from
# the first word, over the full-screen pictures too (the captions are the last
# layer). No lighting up, no fade: the word is there when it is said, gone at
# the next. Measured on their storyboards (vLVGpzxWpfw, gwzeJicUXAE,
# OrOdCRiDWQQ): the word's centre at 53-70 % of the height, capitals 2.2-2.6 %
# of the height (~45-50 px on 1920), "PERSON" 30 % of the width, "OFF" 14 %.
# Measured on the videos themselves (9-oct-2026, etude2/mesures, 9 hits, frame by frame): the word centred at
# 58 % of the height, capitals 58 px. Size 133 here: capitals ~58 px; centre at 1114 px (58 % of 1920).
# A long word is set smaller to
# stay inside 84 % of the width (safe_x 8-92 %, _fit_scale). A short word
# never rides with its neighbour ("one_word"); the punctuation is dropped.
# Colour (decoded on 12 of their shorts, 724 s: ONE coloured word, "CRAZY"): at
# most ``key_max`` word per clip, and only an emotion word (EMOTION_WORDS) —
# the first one said; a clip without one stays all white.
# ``corner``: the channel's name small at the top right in a grey see-through
# box (their « OPTIMAL HEALTH »), instead of under the word, and the clip's
# credit (« CREDIT: <the show> ») tiny at the top left, the whole clip long
# (CORNER below) — their top band, with no hook title on screen
# (plus.HOOK_ON_SCREEN).
PRESETS["oneword"] = {**PRESETS["premium"], "max_words": 1, "max_chars": 40, "one_word": True, "size": 133,
                      "caption_y": 1114, "lit": False, "fade": 0, "safe_x": (0.08, 0.92),
                      "accent": "#F2B544", "key_every": 0, "key_gap": 4, "key_min": 0.8, "key_max": 1,
                      "key_only": "emotion",
                      "outline": 6, "shadow": 3, "edge_alpha": 0x00, "shadow_alpha": 0x50, "corner": True}
# The only words a "key_only": "emotion" preset may colour (their « CRAZY »).
EMOTION_WORDS = frozenset("""crazy insane wild unbelievable incredible insanely shocking terrifying scary
terrified amazing horrible awful disgusting brutal nuts mindblowing""".split())

# The small texts at the top of a "corner" preset, in px of a 1080x1920 frame.
# The credit: white at 80 % (alpha 0x33), size 34 (~1.8 % of the height), a thin
# dark edge so it reads on a bright picture. The channel: white in a grey box
# at 55 % (box_alpha 0x73, BorderStyle 3: the "outline" is the box's padding),
# its top at 11.5 % of the height, as their logo (11-17 %).
CORNER = {"size": 34, "alpha": 0x33, "outline": 2, "edge_alpha": 0x60, "spacing": 1,
          "x_margin": 0.04, "credit_y": 0.03,
          "channel_size": 32, "channel_y": 0.115, "box": "#3C3C3C", "box_alpha": 0x73, "box_pad": 9}


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


def group_words(words, max_words, max_chars, one_word=False):
    """Caption groups. Short function words ride with their neighbour, so a
    1-word preset still shows "A GOAL" instead of a lone "A" — unless
    ``one_word``: every word alone, as the references caption ("OF")."""
    if one_word:
        return [[w] for w in words]
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


# "Spoken word lit" (the premium captions, 2-oct-2026): the group shows dimmed,
# each word rises to full in LIT_RISE ms the moment it is said, and the key
# word turns from white to the accent at that same moment. Nothing moves: the
# eye reads ahead and follows the voice. The fill, the edge and the shadow are
# dimmed together through their own alphas (\1a \3a \4a), never \alpha, which
# would leave the edge and the shadow solid once the word is lit.
# 5-oct-2026: LIT_DIM 0.42 -> 0.70 (at 42 % a word not said yet vanished on a
# bright picture: the A of "IDENTIFIED A" over the MRI sheet), and the alphas
# follow the premium style's new solid edge (0x70 / 0x99 -> 0x20 / 0x60).
LIT_DIM = 0.70                                   # opacity of a word not said yet
LIT_RISE = 60                                    # ms from dim to full
LIT_ALPHAS = (0x00, 0x20, 0x60)                  # the premium style's fill / edge / shadow alphas


def _dimmed(alpha, k):
    """The ASS alpha of a component whose own alpha is ``alpha``, shown at opacity ``k``."""
    return int(round(255 - (255 - alpha) * k))


# The safe width (5-oct-2026). A preset's ``safe_x`` = (left, right) of the
# frame's width its captions' ink (edge and shadow included) stays inside.
# At size 100 / 14 characters the 611 captions of job b8e46c24 measured 722 px
# at most against 734 (centred in 6-84 %), but group_words lets a run of short
# words reach max_chars + 4 ("AND THE WORKHOUSE": 806 px) and never splits a
# long word: _fit_scale sets those few smaller, both axes alike.
# The faces it can measure: (file in fonts/, the em libass draws per unit of
# font size — 0.645 for Montserrat ExtraBold, measured with the ass filter on
# 13 strings, about 1 % wide of the real ink, never narrow).
CAPTION_FACES = {"Montserrat ExtraBold": ("Montserrat-ExtraBold.ttf", 0.645)}
_face_cache = {}


def _fit_scale(text, p, width=1080):
    """Percent (``\\fscx``/``\\fscy``) a caption is set at so its ink stays
    inside the preset's ``safe_x``: 100 when it fits, for a preset without
    one, or when the face cannot be measured (no PIL, no file)."""
    face = CAPTION_FACES.get(p.get("font"))
    if not p.get("safe_x") or not face:
        return 100
    try:
        if face[0] not in _face_cache:
            from PIL import ImageFont
            _face_cache[face[0]] = ImageFont.truetype(os.path.join(FONT_DIR, face[0]), 1000)
        glyphs = _face_cache[face[0]].getlength(text) / 1000 * face[1] * p["size"]
    except (ImportError, OSError):
        return 100
    lo, hi = p["safe_x"]
    room = 2 * min(0.5 - lo, hi - 0.5) * width
    edge = 2 * p.get("outline", 2) + p.get("shadow", 2) + 3       # both edges, the shadow, the blur
    if glyphs + edge <= room or glyphs <= 0:
        return 100
    return max(50, int((room - edge) / glyphs * 100))


_EDGE_PUNCT = re.compile(r"^[^\w$#]+|[^\w%$']+$")


def _one_word_text(text):
    """A word as the one-word captions show it, without the punctuation around
    it ("morning," -> "morning", "..." -> "")."""
    return _EDGE_PUNCT.sub("", text)


# Long words that are never the strong word of a one-word caption (the colour
# goes to a thing or an act: "MALPRACTICE", "DRUNK", "12"), with the adverbs in -ly.
_PLAIN_LONG = set("""understand different interesting sometimes through necessarily another anybody somebody
everybody something important especially probably obviously usually certainly definitely absolutely
basically actually generally normally totally whatever whenever wherever however together already
yourself himself herself themselves ourselves myself because""".split())


def _plain_long(word):
    b = _bare(word)
    return b in _PLAIN_LONG or b.endswith("ly")


def channel_label(watermark):
    """The profile's watermark as the corner shows it: "@TheSynapseCut" ->
    "THE SYNAPSE CUT" (the @ dropped, the words of a CamelCase handle split)."""
    w = re.sub(r"^@+", "", str(watermark or "").strip())
    if " " not in w:
        w = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", w)
    return re.sub(r"\s+", " ", w).strip().upper()


def _corner_lines(width, height, end, watermark=None, credit=None):
    """The small texts at the top of a "corner" preset (PRESETS["oneword"]),
    from 0 to ``end``: « CREDIT: <show> » top left, the channel's name top
    right in its grey box (style Badge)."""
    lines = []
    margin = int(width * CORNER["x_margin"])
    s, e = _ass_time(0.0), _ass_time(end)
    if credit and str(credit).strip():
        y = int(height * CORNER["credit_y"])
        lines.append(f"Dialogue: 3,{s},{e},Corner,,0,0,0,,{{\\an7\\pos({margin},{y})}}"
                     f"{_esc('CREDIT: ' + str(credit).strip().upper())}")
    label = channel_label(watermark)
    if label:
        pad = CORNER["box_pad"]
        y = int(height * CORNER["channel_y"]) + pad
        lines.append(f"Dialogue: 3,{s},{e},Badge,,0,0,0,,{{\\an9\\pos({width - margin - pad},{y})}}{_esc(label)}")
    return lines


def _lit_word(text, at, accent=None):
    """One word of a lit caption: ``at`` = seconds from the caption's start to
    the word; ``accent``: the key word's colour (hex), reached when it is said."""
    t0 = max(0, int(round(at * 1000)))
    fill, edge, shadow = LIT_ALPHAS
    dim = "".join(f"\\{n}a&H{_dimmed(a, LIT_DIM):02X}&" for n, a in zip((1, 3, 4), LIT_ALPHAS))
    lit = f"\\1a&H{fill:02X}&\\3a&H{edge:02X}&\\4a&H{shadow:02X}&" + (f"\\c{_ass_color(accent)}" if accent else "")
    return f"{{\\c&HFFFFFF&{dim}\\t({t0},{t0 + LIT_RISE},{lit})}}{text}"


def build_ass(words, preset, width=1080, height=1920, watermark=None, topic=None, after=0.0, credit=None,
              duration=None):
    """``after``: the seconds the hook is on screen (hooks.hook_gone_at): the
    captions start with the first word said once it is gone, never under it.
    A "corner" preset (oneword) puts ``watermark`` top right and ``credit``
    (the show's name, see playbook.show_name; None = no credit line) top
    left, for ``duration`` seconds (the clip's length; else to the last word)."""
    p = PRESETS[preset]
    words = [w for w in words if w["start"] >= after - 1e-6]
    if p.get("one_word"):
        words = [{**w, "text": _one_word_text(w["text"])} for w in words]
        words = [w for w in words if w["text"]]
    groups = group_words(words, p["max_words"], p["max_chars"], one_word=bool(p.get("one_word")))
    # Colour one word in every ``key_every`` groups — the strongest of the group.
    lines = []
    colour_i = 0
    last_key = -10 ** 6
    for gi, g in enumerate(groups):
        start = g[0]["start"]
        end = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else g[-1]["end"] + 0.3
        end = min(end, g[-1]["end"] + 0.6)
        best = max(range(len(g)), key=lambda k: keyword_score(g[k]["text"], topic))
        score = keyword_score(g[best]["text"], topic)
        # The rhythm (every ``key_every`` captions) never skips a topic word
        # or a number (score >= 1.2). A preset with a ``key_gap`` instead
        # (oneword) colours a strong word only ``key_gap`` words after the last.
        if p.get("key_only") == "emotion":
            best = next((k for k, w in enumerate(g)
                         if re.sub(r"[^a-z]", "", w["text"].lower()) in EMOTION_WORDS), best)
            colored = (re.sub(r"[^a-z]", "", g[best]["text"].lower()) in EMOTION_WORDS
                       and colour_i < p.get("key_max", 1))
        elif p.get("key_gap"):
            colored = (score >= p.get("key_min", 0.5) and gi - last_key >= p["key_gap"]
                       and (score >= 1.2 or not _plain_long(g[best]["text"])))
        else:
            colored = (bool(p["key_every"]) and score >= p.get("key_min", 0.5)
                       and (gi % p["key_every"] == 0 or score >= 1.2))
        if colored:
            last_key = gi
        color = (p.get("accent") or PALETTE[colour_i % len(PALETTE)]) if colored else None
        if colored:
            colour_i += 1
        parts_text = []
        for k, w in enumerate(g):
            t = _esc(w["text"].upper())
            if p.get("lit"):
                parts_text.append(_lit_word(t, w["start"] - start, color if color and k == best else None))
            else:
                parts_text.append(f"{{\\c{_ass_color(color)}}}{t}{{\\c&HFFFFFF&}}" if color and k == best else t)
        x, y = width // 2, p["caption_y"]
        s, e = _ass_time(start), _ass_time(end)
        if p.get("calm"):
            # No pop: an 80 ms fade-in reads as calm, not as an effect.
            k = _fit_scale(" ".join(_esc(w["text"].upper()) for w in g), p, width)
            fit = f"\\fscx{k}\\fscy{k}" if k < 100 else ""
            # oneword: no fade at all, the word is there the moment it is said.
            fade = p.get("fade", 80)
            fad = f"\\fad({fade},0)" if fade else ""
            lines.append(f"Dialogue: 1,{s},{e},Main,,0,0,0,,{{\\an5\\pos({x},{y}){fad}{fit}}}{' '.join(parts_text)}")
        else:
            pop = "\\fscx106\\fscy106\\t(0,80,\\fscx100\\fscy100)"
            lines.append(f"Dialogue: 1,{s},{e},Main,,0,0,0,,{{\\an5\\pos({x},{y}){pop}}}{' '.join(parts_text)}")
        if watermark and not p.get("corner"):
            lines.append(f"Dialogue: 2,{s},{e},Mark,,0,0,0,,{{\\an5\\pos({x},{y + int(p['size'] * 0.95)})}}{_esc(watermark.upper())}")

    size = p["size"]
    font = p.get("font", FONT)          # the preset's face; Liberation Sans for the presets that name none
    if p.get("calm"):
        # Plain white, a dark edge + soft drop shadow: readable on any
        # background without looking "designed" (thin for natural, thick and
        # almost solid for premium since 5-oct-2026, see PRESETS).
        edge, shade = p.get("edge_alpha", 0x70), p.get("shadow_alpha", 0x99)
        styles = [f"Style: Main,{font},{size},&H00FFFFFF,&H00FFFFFF,&H{edge:02X}000000,&H{shade:02X}000000,"
                  f"{p.get('bold', 1)},0,0,0,100,100,{p.get('spacing', 0.5)},0,1,{p.get('outline', 2)},"
                  f"{p.get('shadow', 2)},5,0,0,0,1"]
        lines = [ln.replace(",Main,,0,0,0,,{", ",Main,,0,0,0,,{\\blur0.8") for ln in lines]
    else:
        styles = [f"Style: Main,{FONT},{size},&H00FFFFFF,&H00FFFFFF,&H80000000,&H90000000,1,0,0,0,100,100,0.5,0,1,3,2,5,0,0,0,1"]
        lines = [ln.replace(",Main,,0,0,0,,{", ",Main,,0,0,0,,{\\blur2") for ln in lines]
    styles.append(f"Style: Mark,{font},{max(18, size // 4)},&H90FFFFFF,&H00FFFFFF,&H00000000,&H00000000,{p.get('bold', 1)},0,0,0,100,100,2,0,1,0,0,5,0,0,0,1")
    if p.get("corner"):
        c = CORNER
        styles.append(f"Style: Corner,{font},{c['size']},&H{c['alpha']:02X}FFFFFF,&H00FFFFFF,"
                      f"&H{c['edge_alpha']:02X}000000,&HFF000000,{p.get('bold', 1)},0,0,0,100,100,{c['spacing']},0,1,"
                      f"{c['outline']},0,7,0,0,0,1")
        # BorderStyle 3: libass draws a box in the OutlineColour, the Outline as its padding.
        styles.append(f"Style: Badge,{font},{c['channel_size']},&H00FFFFFF,&H00FFFFFF,"
                      f"{_ass_color(c['box'], c['box_alpha'])[:-1]},&HFF000000,{p.get('bold', 1)},0,0,0,100,100,"
                      f"{c['spacing']},0,3,{c['box_pad']},0,9,0,0,0,1")
        end = duration or ((groups[-1][-1]["end"] + 0.6) if groups else 0.0)
        if end > 0:
            lines.extend(_corner_lines(width, height, end, watermark=watermark, credit=credit))

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


def _render(clip_path, words, preset, out_path, motion, captions, watermark=None, opts=None, topic=None,
            after=0.0, credit=None):
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
            ass_text, groups = build_ass(words, preset, info["w"], info["h"], opts.get("watermark"), topic=topic,
                                         after=after, credit=credit, duration=info["duration"])
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


def apply_captions(clip_path, words, preset, out_path, watermark=None, topic=None, after=0.0, credit=None):
    """The preset's captions only: the last layer, like every caption burn.
    ``after``: when the hook under them has left; ``credit``: the show named
    at the top left by a "corner" preset (see build_ass)."""
    return _render(clip_path, words, preset, out_path, motion=False, captions=True, watermark=watermark,
                   topic=topic, after=after, credit=credit)


def apply(clip_path, words, preset, out_path, watermark=None, opts=None, topic=None, credit=None):
    """Motion + captions in one encode (a clip without a hook, tests)."""
    return _render(clip_path, words, preset, out_path, motion=True, captions=True,
                   watermark=watermark, opts=opts, topic=topic, credit=credit)


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
