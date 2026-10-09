"""B-roll « littéral » (9-oct-2026) — the pictures of the channels that work (OptimalHealth, Clip Storm; the study in
output/_stepup/etude2/references, the user's RECETTE_REFERENCES.md § 1), as plus.BROLL "chain": "litteral".

  1. the director (ONE call per clip) does not look for an idea: it lists the CONCRETE NOUNS said in the clip (an
     object, a substance, an organ, a place, a gesture, a type of person) with the number of the word in the
     transcript, and gives each thing its LITERAL picture, a format ("object" or "scene") and a key (the same thing
     said again keeps its key: its picture comes back, never made twice). Nothing concrete: no picture. When the guest
     explains HOW (a gesture, a technique, a mechanism), at most one SEQUENCE: one 3D figure (a glowing blue anatomical
     hologram, or an organ in a realistic 3D render), the points of it where something happens, and 3-6 steps, each on
     its word, each with its marks (an arrow, a turning circle, a glow) — drawn by the code over the same picture
     (broll._draw_marks), never asked from the image model. It reads the channel's principles (SKILL.md), the
     pictures' charter (charte.md) and its method (directeur-banc.md);
  2. the verifier (Sonnet, ONE pass, before any render) checks safety only, as in the « dessin » chain;
  3. the code places the pictures (schedule): each comes up ON its word (the word's start, ± 0.1 s), never in the first
     HEAD s, one every GAP_MIN-5 s, DUR_MIN-DUR_MAX s each, a hard cut, at least FACE_MIN s of face between two, never
     over the punchline; a sequence holds its figure from its first step to its last; it aims at COVER_LO-COVER_HI of
     the clip off the face;
  4. one render per key kept: the charter's style sentence first, word for word; a scene 9:16 full screen (layout
     "hero"), an object alone on its plain colour (layout "object", broll.OBJECT_GEN) shown as a big card in the
     lower half (broll._object_frames), a sequence's figure 9:16 full screen with its points found on the render by
     one small look (locate: Sonnet, low effort). A person in it: dressed (the dressing sentence, then the dress check
     of the « dessin » chain: one more render, then dropped).

  5. (9-oct-2026 evening, the integration of the « références » recipe) what a still cannot be:
     - an ACTION, a PLACE or a STATE LIVED (rules 3 and 5 of the decoding: 31 of 55 nouns and 16 of 17 states are real
       footage full screen) comes as 1-3 s of Pexels footage (broll_video.videos_for_clip, plus.BROLL["video"]): the
       director gives such a scene a "footage" query; nothing found -> the generated picture, as before;
     - a 3D render of the INSIDE of the body moves lightly (broll_animate, plus.BROLL["animate"], engine "ltxv" by
       default): a light that pulses or a slow flow along it, never an organ that must change shape (the director says
       "pulse", "flow" or "none");
     - an object fills its card (fill_object: about OBJECT_FILL of it, the bench's lidocaine vial filled 15 %), its label
       blank;
     - 41 % of the pictures come in with a 0.2 s transition (a flash of light on a full-screen one, a blur on a card), the
       rest on a dry cut (transitions(): the measures of 9 hits, etude2/mesures/rapport.md).

The old chain stays: plus.BROLL "chain": "dessin" (broll_draw, its own texts in charte-dessin.md, directeur-dessin.md,
principes-dessin.md). broll_litteral_banc.py runs this chain on real clips without a job."""
import os
import re

import broll_ideas

SKILL = broll_ideas.SKILL_DIR
CHARTER_FILE, METHOD_FILE = "charte.md", "directeur-banc.md"
# The formats (9-oct-2026, the decoding of 12 OptimalHealth shorts, output/_stepup/etude2/decodage/rapport.md § 4):
# "object" a thing you hold -> a card in the lower half that rises from the bottom; "split" a substance or many small
# things (pills, beans) -> the screen cut in two, the guest above, the thing filling the lower half; "scene" a place,
# an action, a person living a state -> full screen; "inside" an invisible mechanism (a nerve, a cell, an organ, an
# inflammation) -> full screen 3D medical render; a gesture or mechanism step by step -> a sequence (one 3D figure).
FORMATS = ("object", "split", "scene", "inside")
LAYOUT = {"object": "object", "split": "split", "scene": "hero", "inside": "hero", "sequence": "hero"}
FULL = ("scene", "inside", "sequence")        # the formats that hide the face
MARK_KINDS = ("arrow", "circle", "glow")
MARK_DIRS = ("left", "right", "up", "down", "in", "out", "cw", "ccw")

HEAD = 0.8          # s: no picture before (the clip opens on the voice and the face) — a card at most before FULL_HEAD
FULL_HEAD = 3.0     # s: no full-screen picture before (12/12 shorts decoded: the face alone for 0-3 s)
HEAD_GRACE = 0.3    # s: a word said this long before HEAD still gets its picture, at HEAD
LEAD = 0.17         # s a picture comes up before its word starts (measured on 9 hits: median 0.17 s, middle half -0.43/+0.13)
CARD_LEAD = 0.5     # s an object card starts rising before its word (it is settled on the word)
DUR_MIN, DUR_MAX = 1.0, 3.0   # decoded: median 2 s, 112 of 130 pictures at most 3 s
DUR_AIM = 2.0       # s on screen when the clause gives no end
STEP = 1.0          # s at least between two pictures' starts (an enumeration changes picture about every second)
JOIN = 0.4          # s: a gap of face shorter than this between two pictures is closed (picture to picture)
TAIL = 1.5          # the last s stay on the face (10/12 decoded shorts end on a face)
PUNCH_CLEAR = 0.2   # a picture leaves this long before the punchline (the face says it)
COVER_LO, COVER_HI = 0.35, 0.45   # decoded: ~40 % of the time off the face, cards included
PER_MIN = 12        # pictures a minute at most (decoded: ~11)
SEQ_STEPS = (3, 6)  # steps of a sequence
SEQ_MAX = 10.0      # s a sequence may hold its figure (decoded: 5-10 s)
STEP_MIN = 0.5      # s between two steps (closer: the later one is dropped)

# A person in the picture: dressed (5-oct-2026, the « dessin » chain's lesson: Z-Image undresses anyone shown lying down
# or "inside"), said in photo words.
DRESSED = "Anyone in this picture is fully dressed in everyday clothes that cover them from the neck to the knees."
DRESSED_PATIENT = ("Anyone in this picture is fully dressed: a patient wears a closed long-sleeved hospital gown from the "
                   "neck to the knees, anyone else their usual clothes.")
DRESSED_MORE = "The clothes stay closed from the neck to the knees."
# The object large in its frame and its label blank (bench of 9-oct-2026: the lidocaine vial of c10 filled 15 % of its
# card, with « Liidocaine » printed on it). fill_object() then crops the render so the object fills OBJECT_FILL of it.
OBJECT_LINE = ("Alone in the centre of the frame on a plain seamless {bg} background, studio product shot, close-up, soft "
               "even light, a soft shadow beneath it, the object very large, filling about three quarters of the frame's "
               "height, its edges inside the frame. Any label or sticker on it is blank and plain, with no writing, no "
               "letters and no numbers.")
OBJECT_FILL = 0.70       # of the card's height (or width, a wide object) the object fills (theirs: the melatonin bottle)
OBJECT_ZOOM_MAX = 2.6    # never cropped tighter than this (the card is ~650 px wide, the render 1024)
# The transitions (measured on 9 hits, frame by frame: 41 % of the picture changes come in with a 0.2 s flash of light or
# a blurred arrival of the card, the rest on a dry cut).
TRANSITION_SHARE, TRANSITION_S = 0.41, 0.2
# The light motions of an animated 3D render of the inside of the body (broll_animate): the shape never moves.
MOTIONS = {"pulse": "A soft light pulses slowly inside it, glowing brighter then dimmer, the shape itself does not move",
           "flow": "Tiny points of light flow slowly along it, the shape itself does not move"}
ANIMATE_MAX_S = 3.2      # s of an animated shot at most (the picture's time on screen + a margin)
DEFAULT_BG = "light blue"
SPLIT_LINE = "Close-up filling the whole frame edge to edge, seen from slightly above, nothing else in view."


def read(name):
    with open(os.path.join(SKILL, name), encoding="utf-8") as f:
        return f.read().strip()


def charter():
    """(the charter's text, its style sentences word for word — its quoted lines: the pictures', then the sequences' —,
    the director's method); raises OSError when a file or the first style sentence is missing (no picture then). A
    charter with one quoted line uses it for the sequences too."""
    text = read(CHARTER_FILE)
    quoted = [line[1:].strip() for line in text.splitlines() if line.startswith("> ") and line[1:].strip()]
    if not quoted:
        raise OSError(f"no style sentence (a line starting with '> ') in {CHARTER_FILE}")
    return text, {"picture": quoted[0], "sequence": quoted[1] if len(quoted) > 1 else quoted[0]}, read(METHOD_FILE)


DA_PROMPT = """You are the picture editor of the channel described below (its texts are in French; answer in ENGLISH).

THE CHANNEL'S PRINCIPLES (everything you do obeys them, first of all "ce qui passe avant l'impact"):
{principes}

THE CHARTER OF THE PICTURES (the code adds the style words itself):
{charte}

YOUR METHOD:
{methode}

THE CLIP: "{title}"
Its words, each with its number in brackets:
{words}

You do NOT look for an idea. List the CONCRETE NOUNS said in this clip, each time one is said and worth showing: an
object, a substance, an organ, a place, a gesture, a type of person — a thing a camera can film. For each one its
LITERAL picture: the thing itself, as anyone recognises it. No symbol, no allegory, no metaphor, no figure of speech,
nothing to decode. A real person's name never gets a picture, nor does a common noun said of that person ("he's a
physician" about a named man). An expression is not a noun ("my finger on the pulse", "a puddle of tears", "the bright
lights"). Nothing concrete in the clip: an empty list.
Offer MANY: every concrete noun worth seeing, each time it is said (a 30 s clip usually has 10 to 20); the code keeps
about one picture every 5 s and 40 % of the clip off the face. A list (A, B, C) gets one entry per element.
People are ordinary Americans (the podcasts are American): give each one an age, a plain casting note and a look ("a
white man in his forties in navy scrubs", "a Black woman in her thirties"), varied across the clip — without it the
image model makes everyone East Asian — and always DOING something visible (rubbing his eyes, driving, writing),
never posing for the camera.
Never a thing made to be read (a newspaper, a book, a sign, a label, what a screen shows): the image model writes
gibberish on it. Show the hands or the person holding it from the side, or leave it out.
"nouns", one entry each:
- "i": the number of the noun itself (not its article nor its adjective): the picture comes up on that word;
- "word": that word;
- "key": a short name of the thing; the same thing said again gets the same key (its picture comes back);
- "format": "object" (ONE thing you hold in a hand: a bottle, a pen, keys — shown alone on a plain colour, as a card
  under the face), "split" (a substance or many small things: pills, coffee beans, water — filling the lower half of
  the screen under the face), "scene" (a place, an action, a person living a state — tired, asleep, ill — full
  screen) or "inside" (something invisible inside the body: a nerve, a cell, an organ, an inflammation — a 3D
  medical render, full screen);
- "picture": on the FIRST entry of a key only (later ones: ""), the thing in plain words, 30 at most, present tense,
  positive: what fills the frame and one or two true details from what is said. "A single" for a thing alone. For
  "inside": the organ or the cells, whole and clean. No style word, no camera word, nothing to read (no text, no
  number, no label);
- "background": for an object, ONE plain colour that contrasts with it (e.g. "sky blue", "warm yellow"); else "";
- "footage": for a "scene" that is an ACTION (someone doing it: driving, sleeping, running), a PLACE (a hospital, a
  factory) or a STATE someone lives (tired, stressed, ill, in pain), on its FIRST entry: 2-5 plain English words to find
  real stock footage of it ("exhausted doctor night shift hospital", "person scrolling phone in bed"), anonymous people
  only, nothing that evokes a death or its means; else "" (the code then makes the picture);
- "motion": for "inside" only, on its FIRST entry: "pulse" (a light pulses in it) or "flow" (light flows along it) when
  the organ can stay perfectly still while that light moves; "none" when showing it would need the organ itself to
  move or change shape (a heart that beats, a lung that breathes, a muscle that contracts, a needle going in); else "";
- "priority": 3 = the thing the clip is about, 2 = clearly worth showing, 1 = minor.
"sequences": [] unless the guest explains HOW to do something or HOW something works, step by step (a gesture of the
eyes, a breath, a signal along a nerve, a cord that pulses). Then ONE sequence for that passage:
- "key": a short name; "figure": the 3D figure in plain words, 25 at most — "a glowing translucent blue holographic
  human head, front view" (a body, a face) or "a realistic 3D anatomical render of" the organ — nothing about
  arrows, circles or light spots (the code draws them);
- "points": the 1-4 places of the figure where something happens, named as seen on the screen ("the eye on the left
  of the screen", "the middle of the cord");
- "steps": 3 to 6, in order, each on the word that says it: "i", "word", and "marks": what shows at that step, 0-2 of
  {{"kind": "arrow" | "circle" | "glow", "at": one of the points, "dir": "left" | "right" | "up" | "down" | "in"
  (toward the figure's middle) | "out" | "cw" | "ccw" (for a circle, as seen on the screen) | "" (a glow)}}.
Return JSON: {{"nouns": [{{"i": 12, "word": "...", "key": "...", "format": "object", "picture": "...",
"background": "...", "footage": "", "motion": "", "priority": 2}}], "sequences": [{{"key": "...", "figure": "...", "points": ["..."],
"steps": [{{"i": 40, "word": "...", "marks": [{{"kind": "arrow", "at": "...", "dir": "in"}}]}}]}}]}}"""
_MARK = {"type": "object", "properties": {"kind": {"type": "string", "enum": list(MARK_KINDS)}, "at": {"type": "string"},
                                          "dir": {"type": "string"}}, "required": ["kind", "at"]}
DA_SCHEMA = {"type": "object", "properties": {
    "nouns": {"type": "array", "items": {
        "type": "object", "properties": {"i": {"type": "integer"}, "word": {"type": "string"}, "key": {"type": "string"},
                                         "format": {"type": "string", "enum": list(FORMATS)},
                                         "picture": {"type": "string"}, "background": {"type": "string"},
                                         "footage": {"type": "string"},
                                         "motion": {"type": "string", "enum": ["pulse", "flow", "none", ""]},
                                         "priority": {"type": "integer"}},
        "required": ["i", "word", "key", "format", "picture", "priority"]}},
    "sequences": {"type": "array", "items": {
        "type": "object", "properties": {"key": {"type": "string"}, "figure": {"type": "string"},
                                         "points": {"type": "array", "items": {"type": "string"}},
                                         "steps": {"type": "array", "items": {
                                             "type": "object", "properties": {"i": {"type": "integer"},
                                                                              "word": {"type": "string"},
                                                                              "marks": {"type": "array", "items": _MARK}},
                                             "required": ["i", "word", "marks"]}}},
        "required": ["key", "figure", "points", "steps"]}}},
    "required": ["nouns"]}

VERIFY_PROMPT = """You are the verifier of the channel described below (its texts are in French; answer in ENGLISH).
You check SAFETY only, in one pass, before any picture is made. You do not judge whether a picture is good, relevant or
well chosen, and you give no score: you refuse or you let it pass.

THE CHANNEL'S PRINCIPLES:
{principes}

Every picture is a photograph or a clean 3D medical render (the code adds the style words). An organ shown whole and
clean (a brain, a heart, a tumour inside an organ), even with an instrument touching it, is fine; so is a glowing
anatomical hologram of a head or a body. White arrows, turning circles and glowing spots drawn over a 3D figure are the
channel's way of explaining: never a reason to refuse. A medicine on its own (a pill bottle, tablets, a blister pack)
is an everyday object and passes.
Each picture comes with what is said around it: read it to know who a person in the picture stands for.
Refuse a picture when:
- it is gore: a head or a body opened, a wound, blood, a cut into flesh, tissue taken out of a body;
- something in it evokes a death or its means, even as a visual cliché (a clip about a death, a sentence about deaths);
- in a clip about a death, or on a sentence that mentions a death, something in it hangs, dangles or is looped (a
  cord, a strap, a belt, a cable, a tube, a rope); anywhere else such things are ordinary and pass;
- in a clip whose subject is a death, the dead person is shown, alive or not;
- it gives real victims a number or their belongings;
- it shows an illicit or recreational drug, its gear, or anyone taking a drug or a medicine;
- it shows a real person: the speakers, or anyone named in the clip — a stranger standing for a named person too (a
  "physician" said of a named man is that man: refuse);
- something in it is to be read (text, numbers, a label).
Otherwise let it pass. "verdict": "pass" or "refuse"; "reason": 12 words at most when you refuse.
THE CLIP: "{title}"
{items}
Return JSON: {{"pictures": [{{"key": "...", "verdict": "pass", "reason": ""}}]}}"""
VERIFY_SCHEMA = {"type": "object", "properties": {"pictures": {"type": "array", "items": {
    "type": "object", "properties": {"key": {"type": "string"},
                                     "verdict": {"type": "string", "enum": ["pass", "refuse"]},
                                     "reason": {"type": "string"}},
    "required": ["key", "verdict", "reason"]}}}, "required": ["pictures"]}

LOCATE_PROMPT = """Look at this picture. For each named point below, give where it is, as fractions of the picture: "x"
from 0 (left edge) to 1 (right edge), "y" from 0 (top edge) to 1 (bottom edge). Left and right are as seen in the
picture. A point you cannot see: x and y -1.
{points}
Return JSON: {{"points": [{{"name": "...", "x": 0.5, "y": 0.5}}]}}"""
LOCATE_SCHEMA = {"type": "object", "properties": {"points": {"type": "array", "items": {
    "type": "object", "properties": {"name": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"}},
    "required": ["name", "x", "y"]}}}, "required": ["points"]}
LOCATE_PX = 512


# What the last run() spent beyond the image renders (add_broll times those): Pexels footage used, animated shots and
# their GPU seconds — for the bench's cost line.
LAST_COST = {}


def _still_of(video, out):
    """The middle frame of ``video`` as a jpg (the picture kept next to the clip, the trace's), or None."""
    import subprocess
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "default=nw=1:nk=1", video], capture_output=True, text=True, check=True).stdout)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{dur / 2:.3f}", "-i", video, "-frames:v", "1", "-q:v",
                        "3", out], check=True, capture_output=True)
        return out if os.path.exists(out) else None
    except Exception:
        return None


def _clean(text, n=400):
    return re.sub(r"\s+", " ", str(text or "")).strip()[:n]


def _key(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")[:40]


def word_lines(words, per_line=14):
    """The clip's words numbered for the director, a line per sentence (cut at most every ``per_line`` words), each line
    with the second it starts at."""
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(f"[{i}]{_clean(w.get('text'), 40)}")
        if re.search(r"[.?!]$", str(w.get("text") or "").strip()) or len(cur) >= per_line:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    out, i = [], 0
    for line in lines:
        out.append(f"({float(words[i]['start']):.1f} s) " + " ".join(line))
        i += len(line)
    return "\n".join(out)


def nouns_of(data, words):
    """The director's nouns, cleaned: [{"i", "word", "key", "format", "picture", "background", "footage", "motion",
    "priority"}] in the clip's order, one per word; a key's picture/format/background/footage/motion are its first
    entry's. Entries outside the words,
    without a key, or of a key with no picture, are dropped."""
    seen, out, used = {}, [], set()
    rows = [r for r in (data or {}).get("nouns") or [] if isinstance(r, dict)]
    rows = sorted(rows, key=lambda r: r.get("i") if isinstance(r.get("i"), int) else 10 ** 9)
    for r in rows:
        i = r.get("i")
        if not isinstance(i, int) or not 0 <= i < len(words) or i in used:
            continue
        key = _key(r.get("key") or r.get("word"))
        if not key:
            continue
        picture = _clean(r.get("picture"), 300)
        if key not in seen:
            if not picture:
                continue
            fmt = r.get("format") if r.get("format") in FORMATS else "scene"
            seen[key] = {"picture": picture, "format": fmt,
                         "background": _clean(r.get("background"), 40) if fmt == "object" else "",
                         # real footage for an action, a place, a state lived (a scene only); a light motion for a 3D
                         # render of the inside of the body
                         "footage": _clean(r.get("footage"), 60) if fmt == "scene" else "",
                         "motion": r.get("motion") if fmt == "inside" and r.get("motion") in MOTIONS else ""}
        try:
            prio = int(r.get("priority") or 1)
        except (TypeError, ValueError):
            prio = 1
        used.add(i)
        out.append({"i": i, "word": _clean(r.get("word") or words[i].get("text"), 40), "key": key,
                    "priority": min(max(prio, 1), 3), **seen[key]})
    return out


def _mark(m, points):
    if not isinstance(m, dict) or m.get("kind") not in MARK_KINDS:
        return None
    at = _clean(m.get("at"), 60)
    if at not in points:
        return None
    d = str(m.get("dir") or "").strip().lower()
    if m["kind"] == "circle":
        d = d if d in ("cw", "ccw") else "cw"
    elif m["kind"] == "arrow":
        if d not in MARK_DIRS or d in ("cw", "ccw"):
            return None
    else:
        d = ""
    return {"kind": m["kind"], "at": at, "dir": d}


def sequences_of(data, words, taken=()):
    """The director's sequence (the first valid one, a clip shows one at most), cleaned: {"key", "figure", "points",
    "steps": [{"i", "word", "marks"}]} — steps in order on distinct words at least STEP_MIN s apart, SEQ_STEPS of them,
    within SEQ_MAX s; marks on the declared points only. [] when none holds."""
    for r in (data or {}).get("sequences") or []:
        if not isinstance(r, dict):
            continue
        figure = _clean(r.get("figure"), 300)
        points = [_clean(p, 60) for p in (r.get("points") or []) if _clean(p, 60)][:4]
        key = _key(r.get("key") or "sequence")
        if not figure or key in taken:
            continue
        steps, last = [], None
        for s in sorted([s for s in r.get("steps") or [] if isinstance(s, dict) and isinstance(s.get("i"), int)],
                        key=lambda s: s["i"]):
            i = s["i"]
            if not 0 <= i < len(words):
                continue
            t = float(words[i]["start"])
            if last is not None and t - last < STEP_MIN:
                continue
            marks = [mk for mk in (_mark(m, points) for m in s.get("marks") or []) if mk][:2]
            steps.append({"i": i, "word": _clean(s.get("word") or words[i].get("text"), 40), "marks": marks})
            last = t
        while len(steps) > SEQ_STEPS[1] or (len(steps) > 1 and float(words[steps[-1]["i"]]["start"])
                                             - float(words[steps[0]["i"]]["start"]) > SEQ_MAX):
            steps.pop()
        if len(steps) >= SEQ_STEPS[0]:
            return [{"key": key, "figure": figure, "points": points, "steps": steps}]
    return []


def has_person(picture):
    import broll_draw
    return broll_draw.has_person(picture)


def picture_text(styles, n, more=False):
    """The text the image model gets: the charter's style sentence first, word for word (a sequence: its own), then the
    director's picture (an object: alone on its plain colour, OBJECT_LINE), then — a person in it — the dressing
    sentence."""
    import broll_draw
    if isinstance(styles, str):
        styles = {"picture": styles, "sequence": styles}
    picture = n["picture"].rstrip(". ") + "."
    if n["format"] == "object":
        text = f"{styles['picture']} {picture} {OBJECT_LINE.format(bg=n.get('background') or DEFAULT_BG)}"
    elif n["format"] == "split":
        text = f"{styles['picture']} {picture} {SPLIT_LINE}"
    elif n["format"] in ("sequence", "inside"):
        points = [p for p in n.get("points") or [] if p]
        if points:
            # the figure shows what the marks will point at (bench of 9-oct-2026: a figure written without its
            # tumour came out as a body, the marks pointing at nothing)
            return f"{styles['sequence']} {picture} Clearly visible: " + "; ".join(points) + "."
        return f"{styles['sequence']} {picture}"
    else:
        text = f"{styles['picture']} {picture}"
    if more or has_person(n["picture"]):
        text += " " + (DRESSED_PATIENT if broll_draw.LYING_RE.search(n["picture"]) else DRESSED)
        if more:
            text += " " + DRESSED_MORE
    return text


def _end_of(words, i):
    """Where the word ``i`` ends: its end, else the next word's start (the transcript may give starts only)."""
    w = words[i]
    end = w.get("end")
    nxt = float(words[i + 1]["start"]) if i + 1 < len(words) else None
    if end is None or float(end) <= float(w["start"]):
        end = nxt if nxt is not None else float(w["start"]) + 0.4
    return float(end)


def natural_dur(words, i, t):
    """How long the thing is the subject: to the end of the clause its word is in (the first word ending in . , ; : ? !
    after it), DUR_MIN + 0.5 - DUR_MAX; DUR_AIM when the clause runs on."""
    for j in range(i, len(words)):
        end = _end_of(words, j)
        if end - t > DUR_MAX:
            break
        if re.search(r"[.,;:?!]$", str(words[j].get("text") or "").strip()):
            return round(min(DUR_MAX, max(DUR_MIN + 0.5, end - t + 0.15)), 2)
    return DUR_AIM


def _room(t, duration, avoid, block, tail):
    """Seconds a picture starting at ``t`` may stay: to the clip's tail, the next block stretch, PUNCH_CLEAR before a
    punchline; None when it may not start there (in a block)."""
    if any(float(a) <= t < float(b) for a, b in block or ()):
        return None
    room = duration - tail - t
    for a, _b in block or ():
        if float(a) > t:
            room = min(room, float(a) - t)
    for p in avoid or ():
        if t - 0.05 <= float(p):
            room = min(room, float(p) - PUNCH_CLEAR - t)
    return room


def schedule(nouns, words, duration, avoid=(), block=(), head=HEAD, tail=TAIL, sequences=(), full_head=FULL_HEAD):
    """The pictures shown, in order: [{**noun, "t", "dur"}] — a sequence's steps as one entry each ("format"
    "sequence", "key", "step", "marks", end to end). The rules of the 12 OptimalHealth shorts decoded (9-oct-2026):
    - each comes up on its word (its start - LEAD; an object card CARD_LEAD s before, it rises to be settled on it);
    - nothing before ``head`` s, nothing full screen before ``full_head`` s, and at most one card before it; nothing in
      the last ``tail`` s (the clip ends on a face), nothing starting in a ``block`` stretch nor running over a
      punchline (``avoid``);
    - DUR_MIN-DUR_MAX s each: to the end of its clause (a new sentence, or the word no longer said), cut short by the
      next picture (picture to picture, an enumeration) — a face shorter than JOIN s between two is closed;
    - chosen by priority (a sequence first, then the nouns, the strongest and earliest first), STEP s at least between
      two starts, PER_MIN a minute at most, at most COVER_HI of the clip off the face; then stretched (to DUR_MAX, room
      allowed) while under COVER_LO."""
    total = max(float(duration), 1.0)
    cands = []
    for n in nouns:
        word_t = float(words[n["i"]]["start"])
        t = round(max(0.0, word_t - (CARD_LEAD if n["format"] == "object" else LEAD)), 2)
        first = full_head if n["format"] in FULL else head
        if first - HEAD_GRACE - 1e-6 <= t < first:
            t = first       # said just before: it comes up then (« emergency room » at 0.64 s -> 0.8 s)
        room = _room(t, duration, avoid, block, tail) if t >= first - 1e-6 else None
        if room is None or room < DUR_MIN - 1e-6:
            continue
        lead = max(0.0, word_t - t)
        cands.append({**n, "t": t, "dur": round(min(natural_dur(words, n["i"], word_t) + lead, DUR_MAX + lead, room), 2),
                      "room": room, "max": DUR_MAX + lead})
    seqs = []
    for s in sequences or ():
        ts = [round(max(0.0, float(words[st["i"]]["start"]) - LEAD), 2) for st in s["steps"]]
        if ts[0] < full_head - 1e-6:
            continue
        room = _room(ts[0], duration, avoid, block, tail)
        last = min(natural_dur(words, s["steps"][-1]["i"], ts[-1]), DUR_MAX)
        if room is None or ts[-1] - ts[0] + DUR_MIN > room + 1e-6:
            continue
        span = round(min(ts[-1] - ts[0] + last, room, SEQ_MAX), 2)
        steps = []
        for k, (st, t) in enumerate(zip(s["steps"], ts)):
            end = ts[k + 1] if k + 1 < len(ts) else ts[0] + span
            steps.append({"i": st["i"], "word": st["word"], "key": s["key"], "format": "sequence", "picture": s["figure"],
                          "points": s["points"], "marks": st["marks"], "step": k, "t": t, "dur": round(end - t, 2),
                          "priority": 3, "background": ""})
        seqs.append({"seq": steps, "t": ts[0], "dur": span, "room": span, "max": span, "priority": 4})

    def trimmed(picks):
        """The picks in time order with their times on screen cut by the next one, a short face closed."""
        picks = sorted(picks, key=lambda c: c["t"])
        durs = []
        for k, c in enumerate(picks):
            d = c["dur"]
            if "seq" not in c and k + 1 < len(picks):
                gap = picks[k + 1]["t"] - c["t"]
                d = min(d, gap)
                if 0 < gap - d < JOIN and gap <= min(c["max"], c["room"]) + JOIN:
                    d = gap
            durs.append(round(max(min(d, c["room"]), 0.0), 2))
        return picks, durs

    def fits(c, picks):
        for a in picks:
            if abs(a["t"] - c["t"]) < STEP - 1e-6:
                return False
            for s, o in ((a, c), (c, a)):
                if "seq" in s and s["t"] - 1e-6 <= o["t"] < s["t"] + s["dur"] + JOIN:
                    return False
        early = [a for a in picks + [c] if a["t"] < full_head - 1e-6]
        if len(early) > 1:
            return False
        if len(picks) + 1 > max(1, int(PER_MIN * total / 60.0 + 0.5)):
            return False
        _p, durs = trimmed(picks + [c])
        return sum(durs) <= COVER_HI * total + 1e-6

    picks = []
    for c in seqs + sorted([c for c in cands if c["priority"] >= 3], key=lambda c: c["t"]):
        if fits(c, picks):
            picks.append(c)
    # then the others, spread: the one furthest from the pictures already kept first (a long stretch on the face is
    # what loses the viewer — the decoded shorts never stay 7 s without a change), its priority counting too
    rest = [c for c in cands if c["priority"] < 3]
    while rest:
        def score(c):
            near = min((abs(c["t"] - a["t"]) for a in picks), default=6.0)
            return c["priority"] + min(near, 6.0) / 2.0
        ok = [c for c in rest if fits(c, picks)]
        if not ok:
            break
        best = max(ok, key=lambda c: (score(c), -c["t"]))
        picks.append(best)
        rest.remove(best)
    picks, durs = trimmed(picks)
    for c, d in zip(picks, durs):
        c["dur"] = d
    if picks and sum(durs) < COVER_LO * total:
        for k in sorted(range(len(picks)), key=lambda k: -picks[k]["priority"]):
            c = picks[k]
            short = COVER_LO * total - sum(p["dur"] for p in picks)
            if short <= 0:
                break
            if "seq" in c:
                continue
            nxt = picks[k + 1]["t"] - c["t"] if k + 1 < len(picks) else 10 ** 9
            c["dur"] = round(min(c["max"], c["room"], nxt, c["dur"] + short), 2)
    out = []
    for c in picks:
        if "seq" in c:
            out.extend(c["seq"])
        else:
            out.append({k: v for k, v in c.items() if k not in ("room", "max")})
    return out


def coverage(picks, duration):
    return sum(float(c["dur"]) for c in picks) / max(float(duration), 1.0)


def direct(words, clip):
    """The director's call -> (nouns, sequences, style sentences). Raises OSError when the charter is missing."""
    text, styles, method = charter()
    title = _clean(clip.get("video_title_for_youtube_short") or clip.get("title"), 140)
    prompt = DA_PROMPT.format(principes=broll_ideas.skill_text("principes"), charte=text, methode=method,
                              title=title, words=word_lines(words))
    data = broll_ideas._call(prompt, DA_SCHEMA, "broll_ideas", broll_ideas._model("broll_ideas", "opus"),
                             effort=os.environ.get("CLAUDE_EFFORT_BROLL_LITERAL") or "medium")
    nouns = nouns_of(data, words)
    return nouns, sequences_of(data, words, taken={n["key"] for n in nouns}), styles


def _around_word(words, i, n=8, before=24):
    """What is said around the word ``i``: ``before`` words before it (a « physician » is said of a man named ten words
    earlier — on job b8e46c24 c07 the verifier missed him with 8), ``n`` after."""
    return " ".join(str(w.get("text") or "") for w in words[max(0, i - max(n, before)):i + n + 1])


def mention_id(j):
    return f"m{j}"


def verify(nouns, sequences, clip, words=None):
    """{id: (verdict, reason)} — id mention_id(j) for every noun mention (its picture where it is said: a « physician »
    said of a named man is refused there only), a sequence's key for a sequence: one Sonnet pass, each with what is
    said around it (``words``); an id it does not answer is refused."""
    keys = {}
    for j, n in enumerate(nouns):
        keys[mention_id(j)] = f'({n["format"]}) picture: "{broll_ideas._q(n["picture"], 60)}"'
        if words:
            keys[mention_id(j)] += f'; said around it: "…{_around_word(words, n["i"])}…"'
    for s in sequences:
        keys[s["key"]] = f'(a 3D figure held while the guest explains) figure: "{broll_ideas._q(s["figure"], 60)}"'
        if words:
            keys[s["key"]] += (f'; said around it: "…{_around_word(words, s["steps"][0]["i"], 4)} … '
                               f'{_around_word(words, s["steps"][-1]["i"], 4)}…"')
    if not keys:
        return {}
    q = broll_ideas._q
    items = "\n".join(f'key "{k}" {line}' for k, line in keys.items())
    title = _clean(clip.get("video_title_for_youtube_short") or clip.get("title"), 140)
    data = broll_ideas._call(VERIFY_PROMPT.format(principes=broll_ideas.skill_text("principes"), title=title,
                                                  items=items),
                             VERIFY_SCHEMA, "broll_verify", broll_ideas._model("broll_verify", "sonnet"), effort="medium")
    out = {k: ("refuse", "not answered by the verifier") for k in keys}
    for r in (data or {}).get("pictures") or []:
        if isinstance(r, dict) and _key(r.get("key")) in out:
            out[_key(r.get("key"))] = ("pass" if r.get("verdict") == "pass" else "refuse", q(r.get("reason"), 14))
    return out


def locate(path, points, tmp):
    """{point name: (x, y)} as fractions of the picture, from one small look (Sonnet, low effort; Haiku if it fails);
    a point not found is left out."""
    import broll
    from PIL import Image
    if not points:
        return {}
    thumb = os.path.join(tmp, "locate_" + os.path.basename(path))
    try:
        im = Image.open(path).convert("RGB")
        im.thumbnail((LOCATE_PX, LOCATE_PX), Image.LANCZOS)
        im.save(thumb, quality=88)
    except Exception:
        return {}
    lines = "\n".join(f'- "{p}"' for p in points)
    for m in dict.fromkeys((broll_ideas._model("broll_points", "sonnet"), "haiku")):
        try:
            data = broll.claude_json(LOCATE_PROMPT.format(points=lines), LOCATE_SCHEMA, timeout=120, attach=[thumb],
                                     stage="broll_points", model=m, effort="low") or {}
        except Exception as e:
            print(f"   ⚠️ Locating the points on {m} failed ({str(e)[:100]}).")
            continue
        out = {}
        for r in data.get("points") or []:
            try:
                x, y = float(r.get("x")), float(r.get("y"))
            except (TypeError, ValueError):
                continue
            name = _clean(r.get("name"), 60)
            if name in points and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
                out[name] = (round(x, 4), round(y, 4))
        return out
    return {}


def marks_at(marks, where):
    """A step's marks with their points' places: [{"kind", "dir", "x", "y"}] (the code draws them, broll._draw_marks);
    a mark whose point was not found is left out."""
    out = []
    for mk in marks or ():
        if mk["at"] in where:
            x, y = where[mk["at"]]
            out.append({"kind": mk["kind"], "dir": mk["dir"], "x": x, "y": y})
    return out


def _render_key(n, styles, tmp, render, k, checks):
    """One picture for a key -> (path, seed, text) or (None, None, text): its render, then — a person in it — the dress
    check: a bare body is made once more with DRESSED_MORE, then dropped; no answer from the check: dropped."""
    import broll
    import broll_draw
    layout = LAYOUT[n["format"]]
    text = picture_text(styles, n)
    got, seed = render(text, os.path.join(tmp, f"lit_{k}.jpg"), layout)
    if not got:
        broll.filter_hit("litteral: not made (ComfyUI)")
        return None, None, text
    if n["format"] == "sequence" or not has_person(n["picture"]):
        return got, seed, text
    bare, what = broll_draw.dress_check(got, tmp)
    if bare is False:
        return got, seed, text
    checks.append({"key": n["key"], "file": os.path.basename(got), "prompt": text, "verdict": "refused",
                   "why": f"bare body: {what}" if bare else f"dress not checked ({what})", "seed": seed})
    if bare is None:
        broll.filter_hit("litteral: dress not checked, a person in it — dropped")
        return None, None, text
    text2 = picture_text(styles, n, more=True)
    got2, seed2 = render(text2, os.path.join(tmp, f"lit_{k}_dressed.jpg"), layout)
    if got2:
        bare2, what2 = broll_draw.dress_check(got2, tmp)
        if bare2 is False:
            return got2, seed2, text2
        checks.append({"key": n["key"], "file": os.path.basename(got2), "prompt": text2, "verdict": "refused",
                       "why": f"bare body again: {what2}" if bare2 else f"dress not checked ({what2})", "seed": seed2})
    broll.filter_hit("litteral: bare body, dropped")
    return None, None, text


def object_bbox(path):
    """(x0, y0, x1, y1) of the object on its plain background in the picture at ``path``, or None (no plain background,
    nothing found): the pixels away from the border's colour in hue (a shadow is the same hue, darker) or much brighter /
    darker, cleaned, the parts at least 15 % the size of the biggest."""
    import cv2
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    h, w = a.shape[:2]
    b = max(4, int(min(h, w) * 0.04))
    border = np.concatenate([a[:b].reshape(-1, 3), a[-b:].reshape(-1, 3), a[:, :b].reshape(-1, 3),
                             a[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    if float(np.median(np.abs(border - bg).sum(-1))) > 45:
        return None                       # the border is not one plain colour: not a product shot
    lum = a.mean(-1) + 1.0
    dc = np.sqrt(((a / lum[..., None] - bg / (bg.mean() + 1.0)) ** 2).sum(-1))
    dl = a.mean(-1) - bg.mean()
    m = ((dc > 0.18) | (dl > 70) | (dl < -110)).astype(np.uint8) * 255
    m = cv2.morphologyEx(cv2.medianBlur(m, 7), cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return None
    areas = st[1:, cv2.CC_STAT_AREA]
    keep = [k + 1 for k in range(n - 1) if areas[k] >= 0.15 * areas.max()]
    x0, y0 = min(st[k, 0] for k in keep), min(st[k, 1] for k in keep)
    x1, y1 = max(st[k, 0] + st[k, 2] for k in keep), max(st[k, 1] + st[k, 3] for k in keep)
    if (x1 - x0) * (y1 - y0) < 0.002 * w * h:
        return None
    return int(x0), int(y0), int(x1), int(y1)


def fill_object(path, fill=OBJECT_FILL, zoom_max=OBJECT_ZOOM_MAX):
    """Crops an object's render in place (same shape) so the object fills ``fill`` of its height — or of its width, a
    wide object — centred on it, never more than ``zoom_max`` tighter. Returns the zoom applied (1.0: left as is: the
    object fills it already, or no plain background found)."""
    from PIL import Image
    try:
        box = object_bbox(path)
    except Exception:
        return 1.0
    if not box:
        return 1.0
    im = Image.open(path).convert("RGB")
    w, h = im.size
    bw, bh = box[2] - box[0], box[3] - box[1]
    zoom = min(fill * h / max(bh, 1), fill * w / max(bw, 1), zoom_max)
    if zoom <= 1.05:
        return 1.0
    cw, ch = w / zoom, h / zoom
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    x0 = min(max(cx - cw / 2, 0.0), w - cw)
    y0 = min(max(cy - ch / 2, 0.0), h - ch)
    im.resize((w, h), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + ch)).save(path, quality=94)
    return round(zoom, 2)


def transitions(picks, share=TRANSITION_SHARE):
    """For each pick (time order), how it comes in: "flash" (a full-screen picture, 0.2 s of light), "blur" (a card
    arriving blurred) or "" (a dry cut) — ``share`` of the picture changes get one, spread evenly; a sequence's later
    steps (the same figure) never do."""
    out, k = [], 0
    for p in picks:
        if p.get("format") == "sequence" and p.get("step", 0) > 0:
            out.append("")
            continue
        on = int((k + 1) * share) > int(k * share)
        k += 1
        out.append(("blur" if p.get("format") in ("object", "split") else "flash") if on else "")
    return out


def _sentence_around(words, i, n=10):
    return " ".join(str(w.get("text") or "") for w in words[max(0, i - n):i + n + 1])


def footage_for(picks, words, duration, tmp, cfg=None):
    """Real footage for the scenes the director gave a "footage" query (an action, a place, a state lived): one moment
    per key (its first time on screen, as long as its longest), through broll_video.videos_for_clip (Pexels: one judge
    call on the previews for the clip). {key: placement} — a key without footage keeps its generated picture."""
    import broll_video
    first = {}
    for p in picks:
        if p.get("format") == "scene" and p.get("footage"):
            if p["key"] not in first:
                first[p["key"]] = {"t": float(p["t"]), "word": p["word"], "key": p["key"], "kind": "action",
                                   "sentence": _sentence_around(words, p["i"]), "query": p["footage"],
                                   "dur": float(p["dur"])}
            else:
                first[p["key"]]["dur"] = max(first[p["key"]]["dur"], float(p["dur"]))
    if not first:
        return {}
    try:
        got = broll_video.videos_for_clip(list(first.values()), words, duration, tmp, cfg=cfg, gap=0.0)
    except Exception as e:
        print(f"   ⚠️ B-roll vidéo : {type(e).__name__} — les images générées restent.")
        return {}
    return {g["key"]: g for g in got if g.get("key")}


def animate_inside(path, n, seconds, tmp, cfg=None):
    """A 3D render of the inside of the body made a short silent shot with its light motion (broll_animate: "pulse",
    "flow"), or None (off, no motion, ComfyUI said no). {"path", "gpu_s", "engine"}."""
    import broll_animate
    if n.get("motion") not in MOTIONS or not broll_animate.enabled(cfg):
        return None
    import inspect
    out = os.path.join(tmp, f"anim_{_key(n['key'])}.mp4")
    eng = broll_animate.engine(cfg)
    # the engine is passed when this broll_animate knows several (the « wan22 » one, branch references-animate)
    extra = {"engine": eng} if "engine" in inspect.signature(broll_animate.animate).parameters else {}
    try:
        r = broll_animate.animate(path, MOTIONS[n["motion"]], out, scene=n["picture"],
                                  seconds=min(ANIMATE_MAX_S, max(1.0, float(seconds) + 0.1)), **extra)
    except Exception as e:
        print(f"   ⚠️ B-roll animé : « {n['key']} » reste une image ({str(e)[:120]}).")
        return None
    print(f"   🎞️ B-roll animé : « {n['key']} » ({n['motion']}), {r.get('seconds')} s, GPU {r.get('gpu_s')} s.")
    return {"path": r["path"], "gpu_s": r.get("gpu_s"), "engine": r.get("engine") or ("ltxv" if not extra else eng)}


def run(clip_path, clip, words, avoid, block, tmp, render, duration=None, head=HEAD, plan=None, cfg=None):
    """The « littéral » chain for one clip; ``render(text, out_path, layout) -> (path or None, seed)`` is add_broll's.
    Returns (cands, picks) — cands in broll_v20's shape (one per picture shown, a key shown twice is two cands on the
    same file, a sequence one cand per step on its figure, with its "marks"), layout "hero" (a scene, a sequence) or
    "object"; picks: the schedule. ``plan``: (nouns, sequences, styles) already decided (the bench), no Claude call.
    A cand may carry "video" (an mp4 shown in place of its picture: Pexels footage or an animated render), "credit"
    and "transition" ("flash", "blur" or ""); ``cfg``: the job's plus.BROLL (its "video" and "animate" switches)."""
    import broll
    import broll_v20
    del broll_v20.LAST_CHECKS[:]
    LAST_COST.clear()
    if len(words) < 3:
        return [], []
    duration = float(duration or _end_of(words, len(words) - 1))
    try:
        nouns, sequences, styles = plan or direct(words, clip)
    except OSError as e:
        print(f"   ⚠️ B-roll « littéral »: the charter is missing ({e}) — no picture for this clip.")
        return [], []
    if not nouns and not sequences:
        print("   ℹ️ B-roll « littéral »: nothing concrete said in this clip — no picture.")
        return [], []
    verdicts = verify(nouns, sequences, clip, words)
    names = {mention_id(j): f'{n["key"]} « {n["word"]} » at {float(words[n["i"]]["start"]):.1f} s'
             for j, n in enumerate(nouns)}
    for key, (v, why) in verdicts.items():
        if v != "pass":
            broll.filter_hit("litteral: refused by the verifier", f'"{names.get(key, key)}": {why}')
            broll_v20.LAST_CHECKS.append({"key": names.get(key, key), "file": "", "verdict": "refused", "why": why})
    ok = [n for j, n in enumerate(nouns) if verdicts.get(mention_id(j), ("refuse",))[0] == "pass"]
    seqs = [s for s in sequences if verdicts.get(s["key"], ("refuse",))[0] == "pass"]
    made, failed, where, videos = {}, set(), {}, {}
    # the actions, places and states lived first: real footage where Pexels has it (no picture to make for those)
    first_picks = schedule(ok, words, duration, avoid, block, head=head, sequences=seqs)
    for key, g in footage_for(first_picks, words, duration, tmp, cfg).items():
        still = _still_of(g["path"], os.path.join(tmp, f"lit_video_{_key(key)}.jpg"))
        if still:
            made[key] = (still, None, f"Pexels footage: {g.get('query')}")
            videos[key] = {**g, "kind": "pexels"}
    LAST_COST["videos"] = len(videos)
    while True:
        picks = schedule([n for n in ok if n["key"] not in failed], words, duration, avoid, block, head=head,
                         sequences=[s for s in seqs if s["key"] not in failed])
        todo = [p for p in dict((p["key"], p) for p in picks).values() if p["key"] not in made]
        if not todo:
            break
        for p in todo:
            got, seed, text = _render_key(p, styles, tmp, render, len(made) + len(failed), broll_v20.LAST_CHECKS)
            if got:
                made[p["key"]] = (got, seed, text)
                if p["format"] == "sequence":
                    where[p["key"]] = locate(got, p.get("points") or [], tmp)
            else:
                failed.add(p["key"])
    # an object fills its card; a 3D render of the inside of the body moves lightly (its light, never its shape)
    longest = {}
    for p in picks:
        longest[p["key"]] = max(longest.get(p["key"], 0.0), float(p["dur"]))
    for key, p in dict((p["key"], p) for p in picks).items():
        if key in videos:
            continue
        if p["format"] == "object":
            z = fill_object(made[key][0])
            if z > 1.0:
                print(f"   🔍 B-roll « littéral » : « {key} » recadré ×{z:g} pour remplir sa carte.")
        elif p["format"] == "inside" and p.get("motion"):
            anim = animate_inside(made[key][0], p, longest[key], tmp, cfg)
            if anim:
                videos[key] = {**anim, "kind": "animate"}
                LAST_COST["animate_gpu_s"] = round(LAST_COST.get("animate_gpu_s", 0.0) + float(anim.get("gpu_s") or 0), 1)
                LAST_COST["animated"] = LAST_COST.get("animated", 0) + 1
    enters = transitions(picks)
    cands = []
    for k, p in enumerate(picks):
        got, seed, text = made[p["key"]]
        layout = LAYOUT[p["format"]]
        m = {"t": p["t"], "dur": p["dur"], "anchor": p["word"], "said": p["word"], "query": p["key"], "prompt": text,
             "subject": p["picture"], "idea": p["key"], "picture": p["picture"],
             "people": "one" if p["format"] != "sequence" and has_person(p["picture"]) else "none",
             "format": p["format"], "background": p.get("background") or "", "mood": None, "style": "photo",
             "art": True, "literal": True}
        if p["format"] == "sequence":
            m.update(seq=p["key"], step=p["step"], marks=marks_at(p["marks"], where.get(p["key"]) or {}))
        m["transition"] = enters[k]
        vid = videos.get(p["key"])
        cand = {"k": k, "m": m, "style": "photo", "file": got, "source": "local", "credit": None,
                "layout": layout, "seed": seed, "model": "turbo", "score": 5, "verdict": "keep"}
        if vid:
            cand.update(video=vid["path"], video_kind=vid["kind"])
            if vid["kind"] == "pexels":
                cand.update(source="pexels", credit=vid.get("credit"), seed=None, model="pexels")
                m["footage"] = vid.get("query")
            else:
                cand["model"] = f"turbo+{vid.get('engine') or 'ltxv'}"
        cands.append(cand)
        broll_v20.LAST_CHECKS.append({"key": p["key"], "t": p["t"], "dur": p["dur"], "word": p["word"],
                                      "file": os.path.basename(got), "verdict": "keep", "why": "", "prompt": text,
                                      "seed": seed, "layout": layout, "transition": enters[k],
                                      **({"video": vid["kind"]} if vid else {}),
                                      **({"marks": m["marks"]} if "marks" in m else {})})
    broll.LAST_PICTURED[:] = picks
    LAST_COST["pictures"] = len([k for k in made if videos.get(k, {}).get("kind") != "pexels"])
    print(f"   📸 B-roll « littéral »: {len(nouns)} concrete nouns, {len(sequences)} sequence(s), {len(made)} pictures "
          f"made ({sum(1 for v in videos.values() if v['kind'] == 'pexels')} Pexels footage, "
          f"{sum(1 for v in videos.values() if v['kind'] == 'animate')} animated), "
          f"{len(cands)} shown, {sum(1 for e in enters if e)} with a transition, "
          f"{100 * coverage(picks, duration):.0f} % of the clip off the face"
          + (f", {sum(1 for v, _w in verdicts.values() if v != 'pass')} refused by the verifier" if verdicts else ""))
    try:
        broll_v20.trace(clip_path, clip, tmp, cands)
    except Exception:
        pass
    return cands, picks
