"""The look of a B-roll picture, read from what is said (B-roll « ambiance », 2-oct-2026).

No table of subjects and their looks. Every segment answers the same eight questions (AXES), each with three to
five anchored levels, every level defined: what kind of thing it is for a camera (visibility), its size (scale),
its time (era), how it is lived (valence, intensity), from where it is told (distance), whether real suffering is
at stake (gravity) and what the moment does in the clip (function). The editor picks one level per question for
every picture (an enum in its schema, never a free score) and quotes the words that decided it.

Then code, not a model, turns the levels into the picture's look sheet:
- WORDS for the art director (medium, composition, lens and point of view, light and exposure, palette, texture,
  mood): the image model reads words, never numbers, so exposure, light, lens and framing travel as sentences;
- a GRADE (colour and contrast only: saturation, contrast, black level, temperature) applied when the picture is
  cut in: one per clip from the clip's base mood, plus a correction per picture (CORRECTION) wide enough for a
  real change of feeling to show (tests/test_visual_mood.py measures it in ΔE);
- the channel's teal/amber SIGNATURE at a set strength in that grade (plus.BROLL["signature"]), never on a
  picture whose colours or light the speaker describes himself (fidelity first);
- a PIXEL CHECK of every picture against its sheet (brightness, contrast, colourfulness) that may only move the
  grade, and that records the gaps it cannot close (a later decision: make the picture again, once at most).
"""
import math
import os
import re
import statistics

VERSION = "mood1"     # names the look of the notion library's pictures (broll.look_key): the house-look ones are not reused

# --- the questions -------------------------------------------------------------------------------------------
AXES = {
    "visibility": (
        ("eye", "a camera can shoot it as it is: a person, an object, a place, an event"),
        ("instrument", "it is real but only an instrument sees it: a microscope, a telescope, a scanner, an x-ray, "
                       "slow motion, a cutaway"),
        ("model", "an abstraction no camera sees: a mechanism, a quantity, a law, a mathematical or physical notion"),
        ("inner", "it exists only inside someone: a sensation, a dream, a vision, an altered state, a memory as lived"),
    ),
    "scale": (
        ("micro", "smaller than the eye can see"),
        ("hand", "something held in a hand, or a detail of a body"),
        ("body", "a person, a few people, a room"),
        ("place", "a building, a street, a landscape, a crowd"),
        ("vast", "beyond a landscape: a planet, the sky, the cosmos, a whole population"),
    ),
    "era": (
        ("now", "the present day, about the last twenty years"),
        ("recent", "within living memory, before about 2005: the age of colour film"),
        ("early", "before about 1950: the age of black-and-white photography"),
        ("before", "before photography existed"),
    ),
    "valence": (
        ("grim", "loss, suffering, threat, fear, disgust"),
        ("uneasy", "worry, doubt, strangeness, conflict"),
        ("neutral", "a fact or an explanation, no feeling either way"),
        ("warm", "comfort, tenderness, relief, humour"),
        ("elated", "wonder, joy, triumph, awe"),
    ),
    "intensity": (
        ("still", "calm, slow, contemplative"),
        ("steady", "an ordinary pace: telling, explaining"),
        ("charged", "tension rising, excitement, urgency"),
        ("extreme", "a peak: danger, violence, ecstasy, panic"),
    ),
    "distance": (
        ("lived", "the speaker, or the person of the story, lives it: told from inside"),
        ("witnessed", "someone else's story, told from outside"),
        ("explained", "a fact, a mechanism, general knowledge"),
    ),
    "gravity": (
        ("none", "no real person's suffering is at stake"),
        ("real", "real people's illness, injury, addiction or loss"),
        ("grave", "a death, a victim, abuse, someone dying"),
    ),
    "function": (
        ("setup", "it sets up the situation"),
        ("build", "it escalates: tension, stakes"),
        ("reveal", "the key fact, the payoff, the climax"),
        ("aside", "a joke, a digression, a light moment"),
        ("close", "the resolution, the conclusion"),
    ),
}
LEVELS = {axis: tuple(name for name, _d in levels) for axis, levels in AXES.items()}
# A missing or unknown answer: the plainest level (a documentary photograph of today, no feeling either way).
DEFAULT = {"visibility": "eye", "scale": "body", "era": "now", "valence": "neutral", "intensity": "steady",
           "distance": "explained", "gravity": "none", "function": None}
# The axes a clip's base is made of (the grade); the others belong to one picture only (its words).
BASE_AXES = ("era", "valence", "intensity", "gravity", "distance")
TEXT_FIELDS = {"cue": 160, "colours_said": 160, "true_colours": 120}

# --- how much a picture may differ from its clip, the signature -----------------------------------------------
# The share of a picture's own grade it keeps against its clip's: 0.8, so a picture two levels darker in feeling
# than its clip shows it (ΔE >= 6 on a plain picture, tests/test_visual_mood.py) while one in the clip's mood wears
# exactly the clip's grade.
CORRECTION = 0.8
SIGNATURE = 0.2       # plus.BROLL["signature"]: the teal/amber stamp's strength (0 = none, 1 = a full duotone)
SIG_SHADOW = (0.10, 0.48, 0.52)    # teal, where the picture is dark
SIG_LIGHT = (1.00, 0.66, 0.32)     # amber, where it is bright

_VAL = {"grim": -2, "uneasy": -1, "neutral": 0, "warm": 1, "elated": 2}
_INT = {"still": 0, "steady": 1, "charged": 2, "extreme": 3}
_GRAV = {"none": 0, "real": 1, "grave": 2}
# How much style a picture may carry when real suffering is at stake: a real patient is shown as he is.
_BUDGET = {"none": 1.0, "real": 0.6, "grave": 0.35}


# --- the editor's side: the rule, the schema, cleaning --------------------------------------------------------
def levels_text(axes=None, indent="  "):
    """The questions and their anchored levels, one line per question, for a prompt."""
    lines = []
    for axis in axes or AXES:
        lines.append(f'{indent}"{axis}": ' + "; ".join(f"{name} = {d}" for name, d in AXES[axis]))
    return "\n".join(lines)


MOOD_RULE = ('- "mood": what kind of thing the picture shows and how this moment feels, answered from the words said '
             'around it (never from the topic in general). For each question pick the ONE level whose definition fits; '
             'when two fit, the one the speaker\'s own words support:\n' + levels_text(indent="    ") + '\n'
             '  and "cue": the 3-12 words of "said" that decided valence and intensity, verbatim; "colours_said": the '
             'colours, light or textures the speaker himself gives this thing, verbatim (empty when he gives none); '
             '"true_colours": the 2-3 real colours of the thing and its setting as a camera would record them.')
SCHEMA = {
    "type": "object",
    "properties": {**{axis: {"type": "string", "enum": list(LEVELS[axis])} for axis in AXES},
                   **{k: {"type": "string"} for k in TEXT_FIELDS}},
    "required": [a for a in AXES if a != "function"] + ["cue"],
}


def clean(raw):
    """The editor's answer -> {axis: level, cue, colours_said, true_colours, defaulted: [axes]}: an unknown or
    missing level becomes DEFAULT's, and says so."""
    raw = raw if isinstance(raw, dict) else {}
    out, defaulted = {}, []
    for axis in AXES:
        v = str(raw.get(axis) or "").strip().lower()
        if v in LEVELS[axis]:
            out[axis] = v
        else:
            out[axis] = DEFAULT[axis]
            if axis != "function":
                defaulted.append(axis)
    for k, n in TEXT_FIELDS.items():
        out[k] = re.sub(r"\s+", " ", str(raw.get(k) or "")).strip()[:n]
    out["defaulted"] = defaulted
    return out


def describe(m):
    """« grim · charged · lived · real » — the levels that carry the feeling, for a log line."""
    m = m or {}
    parts = [m.get("valence"), m.get("intensity"), m.get("distance")]
    if m.get("gravity") not in (None, "none"):
        parts.append(m["gravity"])
    if m.get("era") not in (None, "now"):
        parts.append(m["era"])
    if m.get("visibility") not in (None, "eye"):
        parts.append(m["visibility"])
    return " · ".join(p for p in parts if p)


def compact(m):
    """A picture's mood as kept in its item: the levels and the texts, nothing empty."""
    return {k: v for k, v in (m or {}).items() if k != "defaulted" and v}


def base(moods, episode=None):
    """The clip's base mood (BASE_AXES): per question, the median level of its pictures with the episode's as one
    more vote (a clip of one picture meets its episode half-way, a clip of four hardly moves)."""
    moods = [m for m in moods or [] if m]
    out = {}
    for axis in BASE_AXES:
        order = LEVELS[axis]
        idx = [order.index(m[axis]) for m in moods if m.get(axis) in order]
        if episode and episode.get(axis) in order:
            idx.append(order.index(episode[axis]))
        out[axis] = order[int(math.floor(statistics.median(idx) + 0.5))] if idx else DEFAULT[axis]
    return out


def episode_levels(bible):
    """The episode's mood (the bible's "mood": BASE_AXES levels), or None."""
    m = (bible or {}).get("mood")
    if not isinstance(m, dict):
        return None
    out = {a: m[a] for a in BASE_AXES if m.get(a) in LEVELS[a]}
    return out or None


# --- levels -> words (what the image model reads) --------------------------------------------------------------
MEDIUM = {
    ("eye", "now"): "a documentary photograph of today",
    ("eye", "recent"): "a colour photograph of its time, with that period's film, lenses and colours",
    ("eye", "early"): "a black-and-white photograph of its time, a silver-gelatin print",
    ("eye", "before"): "a painting or an engraving of its time, as that period pictured it",
    "instrument": ("the image the instrument that sees it makes (a micrograph, a telescope or probe image, a scan, a "
                   "high-speed frame), in that instrument's real light and colours"),
    "model": ("a physical model of the notion in real materials (shapes, wire, glass, paper, water, light) on a table "
              "or in a room, photographed"),
    "inner": ("what the person perceives from inside, through their own eyes and senses — what they see, hear or feel, "
              "turned into what is seen — never the person seen from outside, never a face that looks pensive; painted "
              "from the speaker's own words, its colours, shapes and scale as strange as it is told"),
}
FRAME_BY_FUNCTION = {
    "setup": "a wide establishing frame that shows where we are",
    "build": "a tighter frame, the subject pressing toward the camera",
    "reveal": "the clearest frame of the set: the one thing, large, nothing competing with it",
    "aside": "a light, open frame with air around the subject",
    "close": "a calm frame, the subject at rest with room around it",
    None: "one clear subject with air around it",
}
FRAME_BY_INTENSITY = {
    "still": "a level horizon, the subject centred and stable",
    "steady": "a balanced composition on the thirds",
    "charged": "a slight diagonal, the subject off-centre and leaning into the frame",
    "extreme": "a strong diagonal, a tilted horizon, the subject cut by the edge of the frame",
}
LENS_BY_SCALE = {
    "micro": "microscope or 100 mm macro magnification, a sliver of focus",
    "hand": "a close-up at 85-100 mm, shallow depth of field",
    "place": "a wide 24-35 mm view from a few metres back or from above",
    "vast": "the widest view (14-24 mm, or a telescope's field), a small figure or object for scale only if the scene has one",
}
LENS_BY_DISTANCE = {
    "lived": "close, at the person's own eye level, 50-85 mm, shallow depth of field: we are with them",
    "witnessed": "from across the room at standing height, 35-50 mm, as a quiet observer",
    "explained": "a clear, neutral view at 35 mm, medium depth of field, everything readable",
}
POV_BY_DISTANCE = {"lived": "seen from where the person is", "witnessed": "seen as an observer", "explained": ""}
KEY_WORDS = {
    "low": "a low-key frame: most of it in deep shadow, one pool of light on the subject",
    "mid": "a balanced exposure: a clear key light, soft shadows, detail everywhere",
    "high": "a bright, high-key frame: open shadows, light everywhere",
}
LIGHT_BY_INTENSITY = {
    "still": "soft, diffused light",
    "steady": "soft directional light",
    "charged": "hard directional light, crisp shadows",
    "extreme": "hard light raking from one side, deep shadows",
}
LIGHT_GRAVE = "gentle natural light that shows the person with dignity"
TEXTURE = {
    "now": "crisp, true detail",
    "recent": "the grain and softness of its film",
    "early": "silver grain and a soft period lens",
    "before": "brush strokes or engraved lines",
    "instrument": "the instrument's own texture (stain, noise, the glow of its detector)",
    "model": "real materials, their surfaces and edges",
    "inner": "the texture the speaker describes, else a painted one",
}
# An experience picture made sober because real suffering is at stake (broll.experience_guard): the person or the
# place as a camera sees them, never the inside of the experience.
SOBER = ("the person or the place as a camera sees them, with dignity — never what is seen, heard or felt inside, "
         "nothing imagined around them")
# An illness or an addiction lived from inside (gravity "real", B-roll « ambiance » v12): shown, with restraint —
# when it is lived as negative only (v14): an experience lived as positive, or one that heals, keeps all its colours.
RESTRAINT = ("with restraint: muted colours, few effects, never spectacular or glorifying, never horror, never a "
             "caricature of the illness")
# A clip about a death (the editor's clip_gravity "grave", v14): every picture is an absence.
ABSENCE = ("an absence: the places and things the person left, as they are, with nobody in them who could be taken "
           "for him or for his close ones")


def _restrained(m):
    """Restraint: an illness or an addiction ("real") lived as negative (grim, uneasy)."""
    return (m or {}).get("gravity") == "real" and (m or {}).get("valence") in ("grim", "uneasy")
VAL_WORD = {"grim": "sombre", "uneasy": "uneasy", "neutral": "matter-of-fact", "warm": "warm", "elated": "luminous"}
INT_WORD = {"still": "quiet", "steady": "measured", "charged": "tense", "extreme": "overwhelming"}


def key_of(m):
    """The exposure the moment calls for: "low", "mid" or "high". Darker when it is lived as bad or intense,
    brighter when it is lived as good; never low around a death (gravity "grave": dignity, not menace)."""
    m = {**DEFAULT, **(m or {})}
    v, a = _VAL[m["valence"]], _INT[m["intensity"]]
    k = _budget(m) * (0.06 * v - 0.04 * max(0, a - 1))
    level = "low" if k <= -0.07 else "high" if k >= 0.07 else "mid"
    return "mid" if level == "low" and m["gravity"] == "grave" else level


def words(m):
    """The picture's look sheet in words, slot by slot (the art director's grammar)."""
    m = {**DEFAULT, **{k: v for k, v in (m or {}).items() if v}}
    vis, era = m["visibility"], m["era"]
    medium = MEDIUM[(vis, era)] if vis == "eye" else MEDIUM[vis]
    if m.get("sober"):
        medium += f"; {SOBER}"
    elif vis == "inner" and _restrained(m):
        medium += f"; {RESTRAINT}"
    if m.get("absence"):
        medium += f"; {ABSENCE}"
    frame = f"{FRAME_BY_FUNCTION.get(m.get('function'), FRAME_BY_FUNCTION[None])}; {FRAME_BY_INTENSITY[m['intensity']]}"
    if m["scale"] == "body":
        lens = LENS_BY_DISTANCE[m["distance"]]
    else:
        lens = LENS_BY_SCALE[m["scale"]] + (f", {POV_BY_DISTANCE[m['distance']]}" if POV_BY_DISTANCE[m["distance"]] else "")
    # Around a death, gentle light; an illness or an addiction never under the hardest light; else the intensity's.
    intensity = "charged" if m["gravity"] == "real" and m["intensity"] == "extreme" else m["intensity"]
    light = KEY_WORDS[key_of(m)] + "; " + (LIGHT_GRAVE if m["gravity"] == "grave" else LIGHT_BY_INTENSITY[intensity])
    if m.get("colours_said"):
        palette = f"the speaker's own colours and light: {m['colours_said']}"
    elif m.get("true_colours"):
        palette = f"the true colours of the scene: {m['true_colours']}"
    else:
        palette = "the true colours of the scene's things and light sources"
    texture = TEXTURE[era] if vis == "eye" else TEXTURE[vis]
    mood = (f"{VAL_WORD[m['valence']]}, {INT_WORD[m['intensity']]}"
            + (", dignified" if m["gravity"] == "grave" else ", restrained" if _restrained(m) else ""))
    return {"medium": medium, "composition": frame, "lens": lens, "light": light, "palette": palette,
            "texture": texture, "mood": mood}


def art_line(m):
    """The look sheet as one line of the art director's list of pictures."""
    w = words(m)
    return "; ".join(f"{k}: {v}" for k, v in w.items())


def sentence(m):
    """The look sheet as plain sentences after a prompt that is not the art director's (the editor's draft kept):
    the image model still gets the medium, the frame, the lens and the light."""
    w = words(m)
    return " ".join(s[0].upper() + s[1:] + "." for s in (w["medium"], w["composition"], w["lens"], w["light"], w["texture"]))


# --- levels -> grade (colour and contrast only) -----------------------------------------------------------------
NEUTRAL_GRADE = {"sat": 1.0, "contrast": 1.0, "lift": 6.0, "temp": 0.0, "gamma": 1.0, "grain": 4.0, "sig": 0.0}
_ERA = {"now": {"sat": 1.0, "temp": 0.0, "lift": 0.0, "grain": 0.0},
        "recent": {"sat": 0.9, "temp": 5.0, "lift": 4.0, "grain": 2.0},
        "early": {"sat": 0.04, "temp": 3.0, "lift": 6.0, "grain": 4.0},
        "before": {"sat": 0.95, "temp": 6.0, "lift": 4.0, "grain": 0.0}}


def _budget(m):
    """How much style a picture may carry: tempered by gravity, except a "real" moment lived as positive (a healing,
    a relief): it keeps all its colours."""
    m = {**DEFAULT, **(m or {})}
    if m["gravity"] == "real" and m["valence"] in ("warm", "elated"):
        return 1.0
    return _BUDGET[m["gravity"]]


def _feeling(m):
    """The grade of a feeling (valence, intensity, gravity): saturation, contrast, black level, temperature."""
    m = {**DEFAULT, **(m or {})}
    v, a, b = _VAL[m["valence"]], _INT[m["intensity"]], _budget(m)
    return {"sat": 1.0 + b * (0.08 * v + 0.05 * (a - 1)),
            "contrast": 1.0 + b * (0.05 * (a - 1) - 0.02 * v),
            "lift": 6.0 - 2.0 * (a - 1),
            "temp": b * 7.0 * v}


def grade(m, clip_base=None, signature=SIGNATURE, correction=CORRECTION):
    """The picture's grade: its clip's feeling, moved CORRECTION of the way toward its own, then its own era's
    medium (a black-and-white picture stays black and white whatever its clip) and the signature (none when the
    speaker gives the colours)."""
    m = {**DEFAULT, **{k: v for k, v in (m or {}).items() if v}}
    own = _feeling(m)
    clip = _feeling({**m, **(clip_base or {})}) if clip_base else own
    g = {k: clip[k] + correction * (own[k] - clip[k]) for k in own}
    era = _ERA.get(m["era"], _ERA["now"])
    sig = 0.0 if m.get("colours_said") else max(0.0, min(1.0, float(signature or 0.0)))
    return {"sat": round(g["sat"] * era["sat"], 3), "contrast": round(g["contrast"], 3),
            "lift": round(max(0.0, g["lift"]) + era["lift"], 2), "temp": round(g["temp"] + era["temp"], 2),
            "gamma": 1.0, "grain": NEUTRAL_GRADE["grain"] + era["grain"], "sig": round(sig, 3)}


def apply_grade(img, g, signature=True):
    """``g`` (a grade of this module) on a PIL RGB picture -> PIL RGB. Order: saturation, contrast, mid-tones
    (gamma, the pixel check's only lever on brightness), black level, temperature (weighted to the mid-tones, the
    blacks stay black), then the signature duotone at ``g["sig"]``. Grain is the renderer's, per frame."""
    import numpy as np
    from PIL import Image
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    w = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    lum = arr @ w
    arr = lum[..., None] + (arr - lum[..., None]) * float(g.get("sat", 1.0))
    pivot = float(lum.mean())          # contrast around the picture's own mean: it never brightens nor darkens it
    arr = np.clip((arr - pivot) * float(g.get("contrast", 1.0)) + pivot, 0, 255)
    gamma = float(g.get("gamma", 1.0))
    if abs(gamma - 1.0) > 1e-6:
        arr = 255.0 * (arr / 255.0) ** gamma
    lift = float(g.get("lift", 0.0))
    arr = lift + arr * (255.0 - lift) / 255.0
    temp = float(g.get("temp", 0.0))
    if temp:
        t = np.clip(arr @ w, 0, 255)[..., None] / 255.0
        k = temp * (0.35 + 0.65 * 4.0 * t * (1.0 - t))
        arr[..., 0:1] += k
        arr[..., 1:2] += 0.15 * k
        arr[..., 2:3] -= k
    s = float(g.get("sig", 0.0)) if signature else 0.0
    if s > 0:
        arr = np.clip(arr, 0, 255)
        lum = arr @ w
        t = np.clip((lum / 255.0 - 0.15) / 0.7, 0, 1)
        t = (t * t * (3 - 2 * t))[..., None]
        lo, hi = np.array(SIG_SHADOW, dtype=np.float32), np.array(SIG_LIGHT, dtype=np.float32)
        tone = lo + (hi - lo) * t
        tone = tone / np.maximum(tone @ w, 1e-3)[..., None]       # the duotone keeps every pixel's brightness
        arr = arr * (1.0 - s) + lum[..., None] * tone * s
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


# --- the pixel check -------------------------------------------------------------------------------------------
def _lab(arr):
    """sRGB 0-255 (H, W, 3) -> CIE L*, a*, b* (D65)."""
    import numpy as np
    c = arr / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    x = lin @ np.array([0.4124, 0.3576, 0.1805]) / 0.95047
    y = lin @ np.array([0.2126, 0.7152, 0.0722])
    z = lin @ np.array([0.0193, 0.1192, 0.9505]) / 1.08883

    def f(t):
        return np.where(t > 0.008856, np.cbrt(t), 7.787 * t + 16.0 / 116.0)

    fx, fy, fz = f(x), f(y), f(z)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


def _small(img, side=256):
    from PIL import Image
    img = img.convert("RGB")
    k = side / max(img.size)
    return img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.BILINEAR) if k < 1 else img


def measure(img):
    """{key: mean L*, contrast: std of L*, chroma: mean C*} of a PIL picture."""
    import numpy as np
    L, a, b = _lab(np.asarray(_small(img), dtype=np.float64))
    return {"key": round(float(L.mean()), 1), "contrast": round(float(L.std()), 1),
            "chroma": round(float(np.sqrt(a * a + b * b).mean()), 1)}


def delta_e(img_a, img_b):
    """Mean CIE76 ΔE between two pictures of the same size (2-3: just seen side by side; 5 and up: seen at once)."""
    import numpy as np
    la = _lab(np.asarray(_small(img_a), dtype=np.float64))
    lb = _lab(np.asarray(_small(img_b).resize(_small(img_a).size), dtype=np.float64))
    return float(np.sqrt(sum((p - q) ** 2 for p, q in zip(la, lb))).mean())


# Where a picture's measures must fall, from its sheet: wide on purpose (a dark street at night and a white
# kitchen can both be "mid"); a picture is only moved when it misses its sheet clearly.
KEY_RANGE = {"low": (12.0, 42.0), "mid": (28.0, 64.0), "high": (45.0, 82.0)}
CONTRAST_RANGE = {"still": (8.0, 24.0), "steady": (11.0, 28.0), "charged": (15.0, 32.0), "extreme": (19.0, 38.0)}
GAMMA_CLAMP, CONTRAST_CLAMP, SAT_CLAMP = (0.7, 1.45), (0.85, 1.3), (0.0, 1.4)
GAP_TOL = {"key": 3.0, "contrast": 2.0, "chroma": 3.0}


def targets(m):
    """{measure: (lo, hi)} a picture of mood ``m`` must fall in (chroma: only its bounds that the mood sets)."""
    m = {**DEFAULT, **{k: v for k, v in (m or {}).items() if v}}
    t = {"key": KEY_RANGE[key_of(m)], "contrast": CONTRAST_RANGE[m["intensity"]]}
    lo, hi = 0.0, 200.0
    if m["era"] == "early":
        hi = 4.0                                     # a black-and-white picture
    elif m["gravity"] == "grave" or m["valence"] == "grim" or _restrained(m):
        hi = 32.0                                    # never garish where it hurts
    if m["valence"] == "elated" and m["era"] != "early":
        lo = 10.0                                    # wonder is not grey
    if (lo, hi) != (0.0, 200.0):
        t["chroma"] = (lo, hi)
    return t


def _solve(small, g, key, measure_key, lo, hi, clamp):
    """The value of ``g[key]`` within ``clamp`` that brings ``measure_key`` of the graded picture inside (lo, hi),
    or the closest the clamp allows (bisection; the measures grow or fall monotonically with each lever)."""
    def at(v):
        return measure(apply_grade(small, {**g, key: v}, signature=False))[measure_key]

    cur = at(g[key])
    if lo <= cur <= hi:
        return g[key], cur
    want = lo + 2.0 if cur < lo else hi - 2.0
    a, b = clamp
    fa, fb = at(a), at(b)
    rising = fb > fa
    best_v, best_m = (a, fa) if abs(fa - want) < abs(fb - want) else (b, fb)
    for _ in range(14):
        mid = (a + b) / 2.0
        fm = at(mid)
        if abs(fm - want) < abs(best_m - want):
            best_v, best_m = mid, fm
        if (fm < want) == rising:
            a = mid
        else:
            b = mid
    return round(best_v, 3), best_m


def check(path_or_img, g, m):
    """The pixel check of one picture: measured with its grade (no signature), moved — gamma for the brightness,
    contrast, saturation for the colourfulness, each within its clamp — when it misses the targets of its sheet.
    Returns (grade, report): report = {"raw", "graded", "after", "target", "moved": [...], "gap": [...]}; "gap"
    lists the measures still out of range by more than GAP_TOL once the clamps are reached (the grade cannot close
    them: the picture would have to be made again)."""
    from PIL import Image
    img = Image.open(path_or_img) if isinstance(path_or_img, (str, bytes, os.PathLike)) else path_or_img
    small = _small(img)
    g = dict(g)
    tg = targets(m)
    report = {"raw": measure(small), "graded": measure(apply_grade(small, g, signature=False)),
              "target": {k: list(v) for k, v in tg.items()}, "moved": [], "gap": []}
    start = dict(g)
    # Two passes: contrast pivots on mid-grey, so a contrast fix moves the brightness of a dark picture and the
    # brightness is solved again.
    for _pass in range(2):
        for meas, lever, clamp in (("key", "gamma", GAMMA_CLAMP), ("contrast", "contrast", CONTRAST_CLAMP),
                                   ("chroma", "sat", SAT_CLAMP)):
            if meas in tg:
                g[lever], _got = _solve(small, g, lever, meas, *tg[meas], clamp)
    report["moved"] = [f"{lever} {start[lever]:g}->{g[lever]:g}" for lever in ("gamma", "contrast", "sat")
                       if abs(g[lever] - start[lever]) > 1e-3]
    after = measure(apply_grade(small, g, signature=False))
    report["after"] = after
    for meas, (lo, hi) in tg.items():
        miss = lo - after[meas] if after[meas] < lo else after[meas] - hi if after[meas] > hi else 0.0
        if miss > GAP_TOL[meas]:
            report["gap"].append(f"{meas} {after[meas]:g} outside {lo:g}-{hi:g}")
    return g, report


# --- the bench: the same segments rated again and again --------------------------------------------------------
RATE_PROMPT = """You are the editor of a short-form clip cut from a longer conversation. Its B-roll pictures are chosen
(below, with the sentence each one illustrates). For EVERY picture, answer "mood":
{rule}

EPISODE BRIEF:
{brief}

CLIP TITLE: {title}

TRANSCRIPT OF THE CLIP (seconds from the clip start):
{text}

THE PICTURES:
{pictures}

Return JSON: {{"moods": [{{"k": 0, "mood": {{...}}}}, ...]}} with the "k" of every picture above."""
RATE_SCHEMA = {"type": "object", "properties": {"moods": {"type": "array", "items": {
    "type": "object", "properties": {"k": {"type": "integer"}, "mood": SCHEMA}, "required": ["k", "mood"]}}},
    "required": ["moods"]}


def rate(moments, clip_text, brief="", title="", fresh=True, model=None, effort=None):
    """The moods of fixed pictures, asked alone (the bench's repeated question: the same segments every time).
    Returns [mood or None per moment]."""
    import ai_brain
    pictures = "\n".join(f'#{k} at {float(m.get("t") or 0):.1f} s, subject "{m.get("subject") or "-"}", anchor '
                         f'"{m.get("anchor") or ""}" — said: "{m.get("said") or ""}"' for k, m in enumerate(moments))
    prompt = RATE_PROMPT.format(rule=MOOD_RULE, brief=brief or "-", title=title or "-", text=clip_text[:6000],
                                pictures=pictures)
    data = ai_brain.claude_json(prompt, RATE_SCHEMA, timeout=300, model=model or ai_brain.stage_model("broll"),
                                effort=effort or os.environ.get("CLAUDE_EFFORT_BROLL") or "high", reuse=not fresh)
    out = [None] * len(moments)
    for r in (data or {}).get("moods") or []:
        try:
            k = int(r.get("k"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= k < len(out):
            out[k] = clean(r.get("mood"))
    return out


def spread(runs):
    """How much the same pictures' levels move from one run to the next. ``runs``: [[mood per picture] per run].
    Returns {axis: {"agree": share of answers on each picture's most frequent level (1.0 = always the same),
    "steps": mean largest gap in levels on one picture (ordinal axes; 0 = never moves), "changed": pictures whose
    level moved at least once}}."""
    out = {}
    n_pics = max((len(r) for r in runs), default=0)
    for axis in AXES:
        order = LEVELS[axis]
        agree, steps, changed, seen = [], [], 0, 0
        for k in range(n_pics):
            vals = [r[k][axis] for r in runs if k < len(r) and r[k] and r[k].get(axis)]
            if not vals:
                continue
            seen += 1
            top = max(vals.count(v) for v in set(vals))
            agree.append(top / len(vals))
            idx = [order.index(v) for v in vals if v in order]
            steps.append(max(idx) - min(idx) if idx else 0)
            changed += len(set(vals)) > 1
        out[axis] = {"agree": round(sum(agree) / len(agree), 3) if agree else None,
                     "steps": round(sum(steps) / len(steps), 2) if steps else None, "changed": changed, "pictures": seen}
    return out
