"""B-roll images for Clip Generator++.

One full-screen hero and two or three wide cards per clip, exactly when the
speaker names something concrete (the kratom plant, a brain scan, soldiers...),
while the voice goes on. They make the clip clearer, hold attention
(something changes on screen) and make it a real edit rather than a
re-upload. The house recipe is fixed (plus.BROLL): the profile only says
whether a channel wants images at all.

* Moments: the AI brain (Claude, Gemini as the fallback) reads the clip inside
  its episode, SEES the clip (frame sheets) and places images that carry the
  idea being said; the anchor is found in the word timestamps, so the cut
  lands on the word. Then it reads each image back (a weak one is redone once).
* Images: generated on this machine's GPU by a ComfyUI server (Z-Image Turbo,
  the Pinokio one): free and unlimited. A picture that fails is retried once
  then skipped; ComfyUI down stops the job. When the last clip still making
  images is done, the models are unloaded from VRAM so Whisper / NVENC in the
  container never fight it for the card. (Gemini images, free photos from
  Openverse and the FLUX graph were removed on 1-oct-2026: never chosen.)
* The source's own picture (screen_inset): when the programme put an image
  in a corner of the wide frame, that picture is one of the cards.
* Render: the hero dissolves over the whole frame; the cards sit above the
  speaker's head in the premium drawing (broll.CARD_*). It runs AFTER the
  edit style and the images stay next to the clip, so a restyle re-cuts them.
"""
import io
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from typing import List, Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageStat

import visual_mood
from ffmpeg_utils import LOUDNORM_FILTER, layer_encode_args

STYLES = {
    "photo": "Realistic documentary photograph, natural light, shallow depth of field, rich but true colours.",
    "neon": ("Clean scientific illustration on a deep navy background, glowing cyan and violet neon lines "
             "and soft light, minimal and elegant, like a science documentary graphic."),
    "drawing": "Simple flat 2D illustration, bold clean outlines, limited warm palette, friendly and clear.",
    "cinematic": ("Cinematic film still, dark moody lighting, strong contrast, fine film grain, shallow depth "
                  "of field, dramatic and tense."),
    "vintage": ("Vintage archive photograph, black and white or faded sepia, film grain, soft vignette, "
                "as found in a historical archive."),
    "3d": ("Clean 3D render, soft studio lighting, smooth materials, neutral light-grey gradient background, "
           "like a product visualisation."),
    "comic": ("Comic-book illustration, bold ink outlines, vivid flat colours, halftone shading, "
              "expressive and punchy."),
    "diagram": ("Minimal explanatory diagram: simple shapes, icons and arrows on a plain light background, "
                "flat colours, NO text, NO labels, NO numbers."),
}
COMMON_RULES = ("One clear subject, centred, filling the frame. No text, no letters, no numbers, "
                "no logos, no watermark. Never depict a real, identifiable person.")
# An art-directed prompt (direct_art) already says the look and the frame: only the hard rules follow it, said in
# the positive (at cfg 1.0 "no text" pulls the model towards text; the director is told the same).
ART_RULES = "Every sign, screen, page and label is a plain surface. Every person is anonymous and fictional."
PROMPT_MAX = 900   # characters of an image prompt kept anywhere (the art director writes 80-120 words)
TEXT_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
SEG_DUR = 1.6
HEAD_FREE = 4.3   # the hook's seconds stay on the speaker
TAIL_FREE = 2.0
MIN_GAP = 3.0     # s between two images
# Profile broll.density ("how many"): fewer / normal / more images than the profile's max.
# share: fraction of max asked from the planner; gap: seconds between two images; pace / names: how the
# planner is told to pace the clip. Normal is the behaviour before this option existed.
DENSITY_CAP = 12
DENSITY = {
    "less": {"gap": 4.5,
             "pace": "Be SELECTIVE: keep only the strongest, most useful moments, about one image every 8-10 s of the clip.",
             "names": "When the speaker names something that can be drawn or photographed AND it matters to the point, "
                      "show it (skip mere passing mentions):"},
    "normal": {"gap": 3.0,
               "pace": "The viewer must ALWAYS have something to look at: illustrate GENEROUSLY, about one image every "
                       "4-6 s of the clip.",
               "names": "Every time the speaker names something that can be drawn or photographed, show it, even if it "
                        "is a passing mention:"},
    "more": {"gap": 2.4,
             "pace": "The viewer must ALWAYS have something to look at: illustrate VERY GENEROUSLY, about one image "
                     "every 3-4 s of the clip.",
             "names": "Every time the speaker names something that can be drawn or photographed, show it, even in "
                      "passing, and use every concrete mention you find:"},
}

# The "mixed" layout (premium): an image only when it adds meaning, two to four per 30 s plus the hero. The texts
# above stay for the historical layouts, whose pace is the ticker's.
DENSITY_MIXED = {
    "less": {"pace": "Be SELECTIVE: one or two images per 30 s of clip, plus the hero when the clip has a real scene for it "
                     "— only where the speaker names or tells something worth seeing.",
             "names": "Show what the speaker names when it is:"},
    "normal": {"pace": "An image only where the speaker names or tells something that can be shown: up to three per 30 s "
                       "of clip, plus the hero when the clip has a real scene for it. The face alone is fine; a picture "
                       "of an idea is not.",
               "names": "Show what the speaker names when it is:"},
    "more": {"pace": "An image wherever the speaker names or tells something that can be shown: three or four per 30 s of "
                     "clip, plus the hero when the clip has a real scene for it. The face alone is fine; a picture of an "
                     "idea is not.",
             "names": "Show what the speaker names, and the strongest passing mentions, when it is:"},
}
# How the pictures sit on screen, for the editor: the historical small card under the captions, or the mixed
# layout's wide card above the head and its one full-screen hero.
FRAME_TEXT = {
    "small": "Each one shows small (about a third of the screen width, under the captions) while the voice goes on,\n"
             "from the anchor word to the end of its sentence or clause (1.5-3 s): put the anchor where the thing is named, and\n"
             "prefer a sentence the image can accompany to its end.",
    "mixed": "Each one shows as a wide card above the speaker's head (about 60 % of the screen width, 2.2-3.5 s) while the\n"
             "voice goes on, from the anchor word to the end of its sentence or clause —\n"
             "except the one HERO, full screen for about 3 s: put the anchor where the thing is named, and prefer a\n"
             "sentence the image can accompany to its end.",
}


def image_count(base, density):
    """Images asked per clip: the profile's max, scaled by the density."""
    base = max(1, int(base))
    if density == "less":
        return max(1, int(base * 0.6 + 0.5))
    if density == "more":
        return min(DENSITY_CAP, max(base + 1, int(base * 1.5 + 0.5)))
    return base


FULL_DUR_MIN = 1.2  # a big (full-frame) picture hides the speaker: it stays short to keep attention
FULL_DUR_MAX = 1.5
DUR_MIN = 1.5     # an image stays from its word to the end of the sentence / clause:
DUR_MAX = 3.0     # at least this long, at most that long
DUR_TAIL = 0.2    # s kept after the last word of the clause
DUR_NEXT_GAP = 0.3  # s left free before the next image
KEY_LEAD = 0.12   # s the image comes up before its key word is said (the pop-in takes ~0.4 s)

# "mixed" layout (premium look): ONE full-screen "hero" picture on the most visual
# moment of the clip, the other images as small cards. The hero is generated in
# 9:16 at the biggest size the GPU gives in ~20 s (measured on an RTX 3060 with
# Z-Image Turbo: 896x1600 in 16 s, 1024x1792 in 23 s; profile broll.hero_res).
HERO_GEN = {"std": (896, 1600), "high": (1024, 1792)}
# s on screen (5-oct-2026, decision 5 « dessins en pleine largeur »: every drawing is a full-screen shot, so it stays
# 2.0-2.5 s and the face comes back; was 2.5-3.5 for the one hero of a clip)
HERO_DUR_MIN, HERO_DUR_MAX = 2.0, 2.5
# The « dessin » chain in full width (plus.BROLL "full_width"): a drawing never covers the punchline — it leaves
# PUNCH_CLEAR s before it is said, and a moment that cannot stay HERO_DUR_MIN s that way gets no picture.
PUNCH_CLEAR = 0.2
# The opening drawing (5-oct-2026, decision 8, plus.BROLL "opening", OFF until the A/B test says otherwise): the
# clip's clearest drawing full screen from 0 to OPENING_SECONDS, then a hard cut to the face — under the hook and the
# captions (the B-roll layer is under both). The one exception to HEAD_FREE.
OPENING_SECONDS = 1.2


def _knob(name, default):
    """A matter-of-taste value, settable from the env (BROLL_<NAME>) without a code change."""
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


# Camera fixed (5-oct-2026, decision 5, her rule « caméra fixe »): the full-screen drawing comes in and leaves on a hard
# cut, like a cut between two cameras, and does not move. Was a 0.35 s crossfade and a 6 % push-in.
HERO_FADE = _knob("BROLL_HERO_FADE", 0.0)           # s: crossfade in and out; 0 = a hard cut
HERO_PUSH = _knob("BROLL_HERO_PUSH", 1.0)           # push-in over the time on screen; 1.0 = none
HERO_VIGNETTE = _knob("BROLL_HERO_VIGNETTE", 0.30)  # darkening at the corners (0-1): keeps the eye in the middle
HERO_GRADIENT = _knob("BROLL_HERO_GRADIENT", 0.45)  # darkening at the very bottom (0-1): the captions stay readable on a bright picture
HERO_GRAIN = _knob("BROLL_HERO_GRAIN", 5.0)         # film grain, sigma in 8-bit levels: hides the upscale and the AI smoothness
# Sampler steps of the hero alone (BROLL_HERO_STEPS; 0 = the usual COMFYUI_ZIMAGE_STEPS, 8). Z-Image Turbo is
# distilled for 8: more is a matter of taste to measure on the brain bench (+50 % of its 16 s at 12).
HERO_STEPS = int(_knob("BROLL_HERO_STEPS", 0))
# Takes of the hero (BROLL_HERO_TAKES): the full-screen picture is made this many times (new seeds), the judge
# sees them together and the best one stays. 16 s of GPU each on the 3060.
HERO_TAKES = max(1, int(_knob("BROLL_HERO_TAKES", 2)))
# The small cards of the "mixed" layout: landscape 16:10 pictures made in that
# ratio (1152x720: 8.6 s on the 3060), wide (profile broll.card_size, 60 % of the
# frame), in the free band ABOVE the speaker's head by default (broll.card_position
# "top": with the natural captions on the chin there is no room between the face
# and the captions, and under them a wide card runs into the app's buttons).
CARD_GEN = (1152, 720)
# Fixed by design, not profile settings (the maintainer's env knobs BROLL_CARD_SIZE / BROLL_CARD_POSITION only):
# a width and a place that work on a tracked podcast frame, measured, with nothing to get wrong in the editor.
CARD_SIZE = int(_knob("BROLL_CARD_SIZE", 60))
CARD_POSITION = os.environ.get("BROLL_CARD_POSITION") if os.environ.get("BROLL_CARD_POSITION") in ("top", "above", "below") else "top"
CARD_DUR_MIN, CARD_DUR_MAX = 2.2, 3.5       # to the end of the clause, never a flash, never a poster
CARD_IN = _knob("BROLL_CARD_IN", 0.35)      # s: fades in while rising CARD_RISE_PX (not from the edge of the screen)
CARD_RISE_PX = 12
CARD_OUT = _knob("BROLL_CARD_OUT", 0.25)    # s: fades out, shrinking CARD_OUT_SHRINK
CARD_OUT_SHRINK = 0.02
CARD_PUSH = _knob("BROLL_CARD_PUSH", 1.03)  # push-in inside the card over its time on screen
TOP_BAND = (0.05, 0.34)                     # of the height: above the head of a tracked speaker (crown at ~0.34 H)
# The « littéral » chain's OBJECT card (9-oct-2026, after OptimalHealth's melatonin bottle): the thing alone on a plain
# colour, made 4:3 (OBJECT_GEN: ~9 s on the 3060), shown as a big card OBJECT_SIZE % of the width wide, rounded
# corners and a light shadow, in the lower half of the frame over the bottom of the face: its top just under the
# captions when they sit in the middle, held within OBJECT_TOP (fractions of the height). A hard cut in and out, no
# move, the speaker stays sharp around it. (The references measure ~85 % of the width: a matter of taste, the knob.)
OBJECT_GEN = (1024, 768)
OBJECT_SIZE = int(_knob("BROLL_OBJECT_SIZE", 60))
OBJECT_TOP = (0.55, 0.62)
OBJECT_RISE = 0.4          # s: the card rises from OBJECT_RISE_FROM lower and settles (the chain starts it 0.5 s early)
OBJECT_RISE_FROM = 0.10    # of the height
# The « littéral » chain's SPLIT screen (9-oct-2026, OptimalHealth's ibuprofen): the speaker's frame moved up into the
# top half (from SPLIT_FACE_FROM of the height: the face of a tracked podcast frame lands in the middle of it), the
# thing filling the bottom half (SPLIT_GEN, made 9:8 like the half), the captions on the line between them.
SPLIT_GEN = (1152, 1024)
SPLIT_FACE_FROM = 0.14
# Pace of the "mixed" layout: few images, far apart (one hero + two or three cards on 30 s), whatever the
# profile's max / density say; nothing in the hook's seconds nor in the last MIXED_TAIL s.
MIXED_MAX = int(_knob("BROLL_MIXED_MAX", 4))     # density "normal" / "more": one hero + three cards
MIXED_FEW = int(_knob("BROLL_MIXED_FEW", 3))     # density "less": one hero + two cards
MIXED_GAP = _knob("BROLL_MIXED_GAP", 4.0)
MIXED_TAIL = 2.0

# A picture the SOURCE put on screen (screen_inset: the producer's inset in a corner of the wide frame), cut
# out at full resolution and shown as a wide card for as long as the source showed it. Not generated, not
# reviewed, not graded, and never shorter than the moment it was up for.
SCREEN_DUR_MIN, SCREEN_DUR_MAX = 1.5, 12.0
SCREEN_ASPECT_MIN = 0.5    # a side-by-side picture is wider than the generated cards (CARD_GEN is 0.625)
SCREEN_CARD_SIZE = 86      # % of the width: the viewer must READ this one (labels, two halves); it still fits the band
# A sound when the FIRST full-screen drawing of the clip arrives (plus.BROLL "sfx"): a soft whoosh made by
# assets/sfx/make_sfx.py (ours, no licence), mixed under the voice; the other pictures come in silent.
# 5-oct-2026 (decision 3 « whoosh audible »): it was mixed at -18 dB and measured 21-26 dB under the voice, inaudible on a
# phone; it is now set SFX_UNDER_VOICE_DB under the voice measured around it (its gain kept in SFX_GAIN_RANGE;
# SFX_GAIN_DB when the voice cannot be read), and the mix is normalised again (ffmpeg_utils.LOUDNORM_FILTER, true peak
# -2 dBTP) as background_music.py does.
SFX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sfx", "whoosh_soft.wav")
SFX_GAIN_DB = _knob("BROLL_SFX_DB", -6.5)
SFX_UNDER_VOICE_DB = _knob("BROLL_SFX_UNDER", 12.0)
SFX_GAIN_RANGE = (-14.0, -2.0)
SFX_LEAD = 0.12       # s before the picture: the sound announces it
HERO_RULE = """HERO IMAGE: one image of the set MAY be shown FULL SCREEN for about 3 s: the clip's poster, the frame a cold
viewer stops on. A hero is a real scene the speaker names or a story of the brief tells — a thing at its real scale,
a place, an action, a creature — shot wide or medium. First list "hero_options": THREE different candidate concepts
(each: "anchor", the verbatim words where it would land; "picture", the scene in one sentence; "why", what the viewer
sees) — take them from the episode's HERO IDEAS when one fits, or find better — then pick the strongest (clear at a
glance, specific to this clip, the thing itself) and mark that moment "hero": true (one at most) with "hero_why" (one
sentence). When the clip has no such scene, mark no hero: the cards alone beat a poster of an idea. Make the hero's
image_prompt a complete scene with depth (foreground, subject, background): it fills a phone screen."""
HERO_RULE_ADAPTIVE = HERO_RULE.replace(
    "A hero is a real scene the speaker names or a story of the brief tells — a thing at its real scale,\na place, an action, a creature — shot wide or medium.",
    "A hero is the clip's strongest moment: a real scene the speaker names or a story of the brief tells,\nthe experience as it is lived, or what the sentence means shown as a real event — never a symbol.").replace(
    "When the clip has no such scene, mark no hero", "When the clip has no such moment, mark no hero")
STOPWORDS = set("""a an the of to in on at by for with from and or but so as is are was were be been it its this that
these those he she they we you i me him her them us my your his their our there here then than very just not no
some any all one two three""".split())

# What the chain filtered out of one clip, by reason, printed by add_broll at the end of the clip (the audit of
# 1-oct-2026 found moments dropped by the parser without a line of log: a filter that does not count its hits
# cannot be judged).
FILTERS = __import__("collections").Counter()


def filter_hit(name, detail=""):
    """One hit of the filter ``name``; ``detail`` is printed when given."""
    FILTERS[name] += 1
    if detail:
        print(f"   ✂️ {detail}")


def filters_line():
    """The clip's filter hits as one line ("none" when nothing was filtered)."""
    return ", ".join(f"{k} {v}" for k, v in sorted(FILTERS.items())) or "none"


def _worth(v):
    """The planner's 1-5 worth of a moment (1.0 when not given): _space keeps the higher one of two that touch."""
    try:
        w = float(v)
    except (TypeError, ValueError):
        return 1.0
    return w if 1.0 <= w <= 5.0 else 1.0

PLAN_PROMPT = """You are the editor of a short-form podcast clip. Pick up to {n} moments (about one every 4-6 s, so the viewer
always has something to look at) where a B-roll image (1.6 s, full screen, while the voice continues) adds
content: every time the speaker names something CONCRETE and visual, even in passing — an object, a plant, a substance, an organ, a place, an animal, a tool,
a group of people (soldiers, surgeons), an event. Never an abstract idea, never "he/she/they", never a
named real person, never a brand. Only moments between {lo:.1f}s and {hi:.1f}s{avoid}.

For each moment give:
- "anchor": the exact 1-3 words as spoken in the transcript (verbatim, same spelling); the image appears when the
  most meaningful of them (the noun that names the thing) is spoken;
- "time": the second the anchor is spoken (from the markers);
- "said": the sentence (about 8-15 words, verbatim) the image illustrates;
- "image_prompt": one English sentence describing the image to generate: the subject WITH the specifics the speaker
  gives (number, place, era, action, mood), setting, light. It shows what the sentence says about the thing, not only the
  thing.{style_rule}
- "subject": the main thing seen, 1-3 words. The images are watched in a row: never the same subject twice, vary the
  scale (wide scene, close-up, schematic), and when the clip follows a person or a case, show that case.
{title}
TRANSCRIPT (seconds from the clip start):
{text}

Return JSON: {{"moments": [{{"anchor": "...", "time": 12.3, "subject": "...", "image_prompt": "..."{style_field}}}]}}"""

# "auto" style: the planner picks one per image, from what the thing IS.
STYLE_RULE = """
- "style": how to show it, one of:
  "photo"   - anything that can really be photographed: plants, food, drugs/pills, animals, places, tools,
              objects, organs as a surgeon would see them, groups of people (soldiers, athletes), events;
  "neon"    - the invisible or microscopic, explained like a science documentary: neurons, receptors,
              molecules, hormones, DNA, cells, brain activity, the immune system, radiation, a chemical reaction;
  "drawing" - what no honest photo can show: a mechanism or process, a thought experiment;
  "cinematic" - drama, danger, tension, a dark or intense story moment, a night scene, a dangerous substance —
              NEVER for a patient, an illness, a disability or a death (use "photo" there);
  "vintage" - the past: a historical scene, an old era, archive footage of an event or of a period;
  "3d"      - one clean object or a body part / organ / machine shown as a product, when a photo would be cluttered;
  "comic"   - humour, an anecdote, an exaggerated situation, a caricature-like moment (never a real person);
  "diagram" - a process, a flow, a comparison or a cause and effect that reads better as shapes and arrows.
  Keep the clip coherent: one style should dominate, use the others only when the moment clearly calls for it."""
# "auto" style in the "mixed" layout: no style to pick (B-roll « ambiance », 2-oct-2026): every picture's look comes
# from its "mood" (visual_mood: what kind of thing, how it feels), turned into words and a grade by code.
STYLE_RULE_PREMIUM = """
- "style": "photo" — the look of every picture comes from its "mood" (what kind of thing it is, how the moment
  feels), never from a style name."""
PREMIUM_STYLES = ("photo",)
# The episode's registers (ai_brain.EPISODE_BIBLE["registers"], 1-oct-2026 evening): how THIS episode shows a kind of
# thing a camera cannot shoot as it is (what only an instrument sees, an abstraction, an inner experience). The
# editor names one in "style", the director paints it, and no grade, no signature, no photo look-grid of the review
# applies to such a picture.
STYLE_RULE_REGISTERS = """
- "style": how to show it, one of:
  "photo"     - the default: the look comes from the picture's "mood";
{lines}
  A register is not an allegory: an experience, a distant or invisible object, a notion the speaker names IS the
  thing named, and its register is how this episode shows it (see REGISTERS in the bible). Never a photo of a
  stand-in object when a register fits. An INSTRUMENT register only for a sentence that speaks of what that
  instrument shows (its image or its readout) — never as the look of a place, a treatment or a conversation."""


def registers():
    """The episode's registers, [] without a bible or without any."""
    import ai_brain
    return [r for r in ((ai_brain.EPISODE_BIBLE or {}).get("registers") or [])
            if isinstance(r, dict) and r.get("name") and r.get("look")]


def register_names():
    return [r["name"] for r in registers()]


def register_of(style):
    """The register dict a style name points to, or None (a photo style, an unknown one)."""
    style = str(style or "").lower()
    return next((r for r in registers() if r["name"] == style), None) if style else None


def register_look(m):
    """The register block a moment's picture is painted in, or None for a photograph."""
    r = register_of((m or {}).get("style"))
    return r["look"] if r else None


def style_rule_premium():
    """The editor's style rule in the mixed layout: the two photo styles, plus the episode's registers when the
    bible wrote some."""
    regs = registers()
    if not regs:
        return STYLE_RULE_PREMIUM
    lines = "\n".join(f'  "{r["name"]}"{" " * max(1, 11 - len(r["name"]))}- {r.get("when") or "the moments that call for it"}' for r in regs)
    return STYLE_RULE_REGISTERS.format(lines=lines)


def premium_style(style):
    """What a planner's style becomes in the mixed layout: "photo" or a register of the episode; anything else (the
    historical cinematic / neon / comic / diagram...) is a photo, its look set by its mood."""
    return style if style in PREMIUM_STYLES or register_of(style) else "photo"


# THE EXPERIENCE, NOT THE SETTING (B-roll « ambiance », 2-oct-2026): something taken or practised for its effect on
# the mind, or a state lived from inside, is shown as it is lived — not the room it is taken in — even named in
# passing; real suffering comes first (sober), and a clip never turns into a string of such pictures.
EXPERIENCE_RULE = """THE EXPERIENCE, NOT THE SETTING: when the speaker names something taken or practised for its effect on the
mind, or a state lived from inside, its picture is the experience as it is lived — what the person perceives, painted
as WHAT FILLS THE FRAME (shapes, light, colours, surfaces, what is seen), never the person seen from outside nor a
pensive face, never the viewer: no "first-person", "point of view" or "through his eyes" in a prompt (the image model
then draws a person) ("visibility": inner, in its REGISTER when the bible gives one) — not the room, the clinic or the
object it comes from — even when he names it
in passing or for its results (this wins over the substances line above). ONE such picture in a clip that names it in passing; more only when he describes
the experience itself. AN INNER PICTURE IS FOR WHAT IS SEEN: a vision, a hallucinated sight, the world seen changed.
A feeling, a rush, a craving, an energy or a chemistry (euphoria, rage, a "high", a dump of dopamine) has nothing to
see: no picture for it — unless the speaker tells a scene, which is then shown. A DEATH FIRST: when the moment is about a death, a victim or someone dying ("gravity"
grave), no experience picture — a sober, dignified photograph instead. An illness or an addiction ("gravity" real)
lived as negative is shown from inside with RESTRAINT: muted colours, few effects, never spectacular or glorifying,
never horror, never a caricature of the illness; an experience lived as positive, or one that heals, keeps all its
colours."""
# A clip about a death (the editor's clip_gravity "grave", v14): its pictures are absences.
ABSENCE_LINE = ("  ABSENCE (the clip is about a death; this overrules the editor's draft): the places and things the person "
                "left, as they are, EMPTY — nobody in the frame (people \"none\"): no colleague, pupil, passer-by, nor "
                "anyone who could be taken for him or his close ones.")
# Safety (v14, the user's rule): nothing that evokes an overdose, a means of suicide or a symbol of death. v16: judged
# WITH the words (a vial is harmless alone, not on "took his own life").
SAFETY_RULE = """NOTHING THAT EVOKES AN OVERDOSE, A MEANS OF SUICIDE OR A SYMBOL OF DEATH, not even as a visual cliché: no
pills spilled or heaped, no empty or tipped-over bottle by a bed, no rope, no blade near skin, no weapon aimed at
anyone, no skull, no coffin, no grave, no wilted flowers or burnt-out candle standing for a death, no heart monitor
with a flat or failing line, no empty hospital bed for a death. A picture is read
WITH ITS WORDS: on a sentence that tells of a death, nothing that could be taken for its cause or its means — no
substance, medicine or container of one, however harmless it would be on its own. No drug being taken nor its gear in
use (a pipe being lit, a needle in a vein, a line on a table)."""
# The editor's flags (v14): a picture with one of them is not made (in the bench's fixed moments: skipped, with why).
FLAGS = ("set_phrase", "negated", "precise_structure")
FLAGS_RULE = """FLAGS, for every picture: "set_phrase" true when the thing the words name, taken literally, does not exist in
the story the clip tells — it is only called up to qualify something else (an idea, a judgment, an intensity, a
feeling): a figure of speech, however vivid, whose literal picture would make a viewer think of another subject
(read the sentence before: a comparison often starts there); "negated" true when the speaker says it is NOT that thing, or that it had
nothing to do with what is told — also on any other moment of the clip that would show a link he denies; never when
he only says it does not matter or "even if" (the thing stays real and is what is told: "it doesn't matter if you
have a tumor" still speaks of a tumor); "precise_structure" true when the picture would need a precise chemical
structure, a formula, an equation, a chart or a labelled diagram. A picture with a flag true is not made."""
# v17 (the user, 3-oct-2026: "les images de cerveau… les photos d'opération… pas dégueu, limite en dessin animé"): the
# inside of a body is drawn, never photographed — declared ("inside_body"), never guessed from the words.
# v19 (the user: "un seul style de dessin pour tout l'épisode, cohérent avec les photos autour — le nerf en style animé
# détonne"): ONE drawing per episode (the bible's "drawing", else the house's), the picture's own light and palette.
BODY_RULE = """THE INSIDE OF A BODY IS DRAWN, NEVER PHOTOGRAPHED: a brain, an organ, tissue, a nerve or a muscle seen inside, a
wound, an operation (surgeons at work on someone, even seen from afar) — "inside_body": true. It is drawn in the
episode's ONE drawing (the same for every such picture of the episode, added by code), dry and clean — nothing wet,
no blood — so nothing is hard to look at; its scene, composition, light and colours are the picture's own, like the
photographs around it, and its prompt has no camera word. A scan, an X-ray or a micrograph keeps its own instrument look
("inside_body": false)."""
BODY_LINE = ("  INSIDE THE BODY (drawn, never photographed; this overrules the medium, the lens and the texture): write "
             "what is drawn — its forms, their scale and arrangement — with the composition, the light and the palette of "
             "its look line, like the photographs of the set; no camera word (lens, millimetres, depth of field, "
             "photograph). The episode's drawing follows your prompt word for word: \"{drawing}\"")
DRAWING_HOUSE = ("A hand-painted documentary illustration in gouache and coloured pencil: forms true to life and "
                 "simplified to clear volumes, softly modelled with fine pencil edges, clean dry matte surfaces with the "
                 "grain of the paper, the true colours of each thing gently muted, painted edge to edge across the whole "
                 "frame, plainly a drawing made by one hand.")


def episode_drawing():
    """The one drawing of the episode's inside-of-a-body pictures: the bible's "drawing", else the house's (no bible,
    an older one, a refused drawing, or BROLL_DRAWING=house)."""
    import ai_brain
    if os.environ.get("BROLL_DRAWING", "episode") == "house":
        return DRAWING_HOUSE
    return str((ai_brain.EPISODE_BIBLE or {}).get("drawing") or "").strip() or DRAWING_HOUSE
# Who is in the frame (v16): declared by the editor (its draft) and by the art director (its prompt), never guessed from
# the words — "man-made", "the north face", "portrait-format", "the patient's chart" made the old word guard add a person.
PEOPLE = ("none", "hands", "one", "group")
PEOPLE_RULE = """"people", for every picture: who is in its frame — "none" (nobody: a place, a thing, a vision, an instrument's
image), "hands" (hands only), "one" (one or a few people), "group" (a crowd). An inner picture is "none": what is
perceived, never the one who perceives."""
# v16 — the parallel and the known picture (the user's correction): the pair side by side is fine when its two halves
# share the structure the speaker compares; what failed was a spiral galaxy next to a lone drawn neuron.
PARALLEL_KINDS = ("none", "one", "pair")
PARALLEL_RULE = """A PARALLEL: when the speaker compares two things for a structure they share ("parallel" for every picture: "none"
otherwise). While he announces, describes or wonders about the comparison: "one" — ONE image of the shared structure
that reads as both. At the moment he SHOWS it ("this is X and that is Y"): "pair" — the two side by side, each half
the real reference image of its own field, the one the researchers of that field publish (its real subject, its
imaging technique, its colours), never the famous emblem of the field in its place, both halves at the same scale,
density and framing so the eye goes back and forth. Either way the shared structure is shown WHOLE, at the scale
where each field shows it — a network of many elements, never one element of it (one cell, one galaxy). When the
video itself puts that image on screen, it is shown as it is (no picture is planned there)."""
KNOWN_PICTURE_RULE = """A KNOWN PICTURE: when the speaker refers to a known image (a published image, a scan, a chart, a comparison),
the picture is that image as it really is — its real subject, the imaging technique that made it, its real colours and
textures — never a generic stand-in nor the emblem of the field. Its own medium and colours overrule a register's
(a register restyles what has no known picture; a known picture is shown as it is)."""
# A place with nobody in it says someone is missing: kept for that (B-roll « ambiance » v12, 2-oct-2026: the boards
# were full of empty clinics and objects set on trays).
EMPTY_RULE = """AN EMPTY PLACE IS AN ABSENCE: a place with nobody in it is for a death or a loss only; elsewhere places have
their people, and things are shown in their life (in use, in someone's hands, where they belong), never set down on a
surface for the camera."""
# What the image model draws wrong: details nobody can check on a phone but that are false (a generated molecule).
PRECISION_RULE = """NOTHING THE IMAGE MODEL WILL GET WRONG: no precise chemical structure, formula, equation, chart or labelled
diagram — it invents their details; show the substance as matter, or what it does."""
RESTRAINT_LINE = ("  RESTRAINT (an illness or an addiction): muted colours, few effects, never spectacular or glorifying, "
                  "never horror, never a caricature of the illness.")
INNER_MAX = int(_knob("BROLL_INNER_MAX", 2))   # experience pictures a clip keeps at most (the editor is told one in passing)
INNER_PRIORITY = 1.0     # worth added to a named experience (not grave): the code keeps it among the candidates
KEEP_WORTH = 3.0         # a candidate below this worth is a nice extra the clip does without
CANDIDATES_MORE = 3      # the editor lists this many candidates more than the clip keeps
LAST_SKIPS = []          # the fixed moments (bench) the editor chose to leave without a picture, with why
LAST_PICTURED = []       # the moments add_broll made pictures for, in order: broll_<k> is the k-th (the bench reads it)
LAST_GEN = []            # every picture made by the last add_broll: file, model, layout, size, seconds (the bench reads it)


def is_inner(m):
    """The moment shows an experience lived from inside: its mood says so, or its register is of that kind."""
    reg = register_of((m or {}).get("style"))
    return ((m or {}).get("mood") or {}).get("visibility") == "inner" or bool(reg and reg.get("kind") == "inner")


def experience_guard(moments):
    """The code's last word on experience pictures (mixed layout): one about a death ("gravity" grave) is made a
    sober photograph (an illness or an addiction, "real", stays an experience, shown with restraint), and a clip keeps
    INNER_MAX of them at most (the highest worth stay). Returns the moments kept; every change is counted (FILTERS)."""
    for m in moments:
        mood = m.get("mood") or {}
        if is_inner(m) and mood.get("gravity") == "grave":
            filter_hit("experience: a death, made sober",
                       f'Moment "{m.get("anchor")}" ({mood.get("gravity")}): an experience picture becomes a sober photograph.')
            m["style"] = "photo"
            # Its look sheet says it to the director and to the image model: the person, not what he lives inside.
            m["mood"] = {**mood, "visibility": "eye", "sober": True}
    inner = sorted((m for m in moments if is_inner(m)), key=lambda m: -m.get("score", 1.0))
    drop = inner[INNER_MAX:]
    for m in drop:
        filter_hit("experience: beyond the cap",
                   f'Moment "{m.get("anchor")}" dropped: {INNER_MAX} experience picture(s) already in this clip.')
    return [m for m in moments if not any(m is d for d in drop)]


def expected_show(m):
    """v13: what the axes say a moment's picture shows — "meaning" (an abstraction, or a claim explained), "thing" (a
    fact or an episode lived or seen), None when either fits or for an experience (its own rule)."""
    mood = (m or {}).get("mood") or {}
    if mood.get("visibility") == "inner":
        return None
    if mood.get("visibility") == "model":
        return "meaning"
    if m.get("role") in ("concept", "consequence") and mood.get("distance") == "explained":
        return "meaning"
    if m.get("role") == "example" and mood.get("distance") in ("lived", "witnessed"):
        return "thing"
    return None


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "thesis": {"type": "string"},
        "arc": {"type": "string"},
        "style_sheet": {"type": "object", "properties": {k: {"type": "string"} for k in
                        ("palette", "light", "era", "camera", "mood", "cast")}},
        "moments": {"type": "array", "items": {
            "type": "object",
            "properties": {"anchor": {"type": "string"}, "time": {"type": "number"}, "idea": {"type": "string"}, "said": {"type": "string"},
                           "subject": {"type": "string"},
                           "shot": {"type": "string", "enum": ["wide", "medium", "close", "macro", "schematic"]},
                           "worth": {"type": "integer"},
                           "role": {"type": "string", "enum": ["concept", "example", "consequence", "other"]},
                           "notion": {"type": "string"},
                           "real_photo": {"type": "boolean"}, "search_query": {"type": "string"},
                           "image_prompt": {"type": "string"},
                           "style": {"type": "string", "enum": ["photo", "neon", "drawing", "cinematic", "vintage", "3d", "comic", "diagram"]}},
            "required": ["anchor", "time", "image_prompt"]}}},
    "required": ["moments"],
}
# What makes an image belong to THIS sentence rather than to its noun: the
# specifics the speaker gives (number, place, era, action, who, mood) and the
# sense of the sentence, resolved with the brief and the words before.
GROUNDING_RULE = """STICK TO THE CONTEXT, not to the noun: read the whole sentence around the anchor and the words
before it (resolve "he", "it", "that thing" from them and from the brief); keep EVERY specific the speaker gives (the
number, the place, the era, the kind of person, the action, the tone) and show what the sentence SAYS about the thing,
not just the thing — a picture that would do for any other clip about the same noun is not the picture. TONE: a
patient, an illness, a disability, a death is shown with warmth and dignity, never as a menace. BE CORRECT: the right organ, tool, animal or place, named precisely. SOUND-OFF
TEST, eliminatory: someone who sees ONLY the picture, then hears "said", links them within a second - else a more
telling scene, or no image."""

# The images of a clip are ONE sequence the viewer watches in a row: they must
# tell the clip's story, not repeat one picture.
SET_RULE = """THE SET TELLS THE STORY: seen one after the other, the pictures follow the arc (setup -> claim -> payoff)
and vary subject and shot. HUMAN CASE FIRST: when the clip follows a person, a patient or a real case (see the
STORIES), that case is the thread. CAST: describe a recurring person or place ONCE in "style_sheet"."cast" and copy
it word for word into every image_prompt where it appears; leave "cast" empty when nobody recurs. THE SPEAKERS
themselves and their studio are never a picture: the video already shows them, and nobody real is ever drawn."""

# What makes a B-roll read as cheap AI stock on a science channel: the pictures
# every generator draws first. The editor and the art director are told never
# to ask for them (Claude reads a ban fine; the image model only ever gets
# positive prompts), the reviewer marks them down, and the brief's glossary is
# asked for real things instead.
CLICHES = ("a glowing brain, a brain floating in space or in blue light", "neurons or synapses drawn as neon lines",
           "a light bulb for an idea", "a handshake", "pills or capsules on a plain white background",
           "a dark silhouette with glowing eyes", "a holographic screen, a floating interface or a HUD",
           "a head with gears, puzzle pieces, a maze or a chess board for the mind",
           "people grinning at the camera like a stock photo", "a DNA helix glowing on black",
           # the allegories a clever editor reaches for: as empty as the neon brain, only better dressed
           "a lone small figure facing a vast landscape, a starry sky or the sea", "open empty palms held out",
           "a hand reaching toward a light", "a doorway or threshold glowing with light",
           "water or sand running through fingers", "a person seen from behind at a window",
           "an empty corridor or a long empty road", "a clock, an hourglass or a crossroads for time or a choice",
           # v17: the v16 bench drew fire for "rage" and a light tunnel for "high on meth"
           "flames, an explosion, lightning or a tunnel of light standing for a feeling or a drug's effect")
CLICHE_RULE = ("NEVER THE AI CLICHÉ (for a PHOTO picture; a register picture follows its register) - the pictures every "
               "generator draws first, and the allegories a clever editor reaches for when nothing concrete was said: "
               + "; ".join(CLICHES) + """. THE STORY ALIVE instead: the speaker's case, its people and its things in
their life, at their true scale. THE CASE BEFORE THE NOTION: the case in its real setting; the notion itself only when
nothing concrete was said. WHAT ONLY AN INSTRUMENT SEES, as that instrument's own image in real light - unless the
episode's REGISTERS say how.""")
# The editor's one line on clichés (the director, who writes the picture, reads the whole CLICHE_RULE).
CLICHE_LINE = ("NO SYMBOL FOR AN IDEA (photo pictures): never the glowing brain, the light bulb, the handshake, the open "
               "palms, the lone figure before the vastness, the glowing doorway - the story alive instead (its people and "
               "things in their life); what only an instrument sees as that instrument's image unless a REGISTER says how.")

CLAUDE_SYSTEM ="You are a meticulous short-form video editor. You answer only with the requested JSON."
CLAUDE_SYSTEM_VISION = ("You are a meticulous short-form video editor. The images are attached to the request, in "
                        "order, each right after its file name. Answer only with the requested JSON.")

# Claude's brief: images that carry the IDEA being said, chosen with the
# conversation around the clip and with what is already on screen in view.
# How literal the images are (profile broll.mode).
MODE_RULES = {
    "literal": "Be LITERAL: show exactly the thing named, as a plain picture of it. Two nearby moments may use two "
               "different images.",
    # The recipe (plus.BROLL["mode"]): the thing named, first — the audit of 1-oct-2026 found 8 allegories out of 11
    # pictures (open palms, a doorway, water through fingers), and the 3 that worked showed the thing named.
    "mixed": ("THE THING NAMED, FIRST. Every image shows something the speaker NAMES or TELLS — the thing itself or "
              "the scene of the story, at its real scale, in its real setting, alive. A picture of an idea (a "
              "ready-made allegory: see the clichés below) is allowed ONLY when the speaker says that image himself — "
              "and then it shows exactly what he says, nothing cleverer. A SET PHRASE IS NOT AN IMAGE: when his words name a thing but he "
              "only means \"very\", \"obvious\", \"huge\", \"everywhere\" or \"at once\" — a figure of speech used for "
              "emphasis, that he does not build on — those words get no picture; only an image he builds on (he "
              "compares, describes it, comes back to it) is shown. When a sentence names nothing, it gets no image: the "
              "face is the picture. Zero images beats one allegory. What a camera cannot shoot as it is (an inner "
              "experience, what only an instrument sees, an abstraction) IS a thing named: when the episode's REGISTERS "
              "(in the bible below) give it one, show it in that register, as it is known to look and as he tells it, "
              "never as a photo of a stand-in object."),
    # v13 (bench "adaptive"): the thing named or what the sentence means, decided moment by moment from the axes.
    "adaptive": ("THING OR MEANING, MOMENT BY MOMENT. For every picture write \"point\" (what the sentence asserts, a few "
                 "words) and decide \"show\": \"thing\" when the thing the speaker names carries his point — a fact about "
                 "it, an episode he lived or saw (role example, distance lived or witnessed): the thing itself or the "
                 "scene, at its real scale, in its real setting, alive; \"meaning\" when the thing named only carries a "
                 "claim — how something works, what it leads to, how two things compare, what something is worth (role "
                 "concept or consequence, distance explained) — and always for an abstraction (visibility model): what "
                 "the sentence says happens, shown as a real event or process in the world (the mechanism at work, the "
                 "consequence on someone, the change from before to after). A \"meaning\" picture is never a symbol nor a "
                 "ready-made allegory (see the clichés below); an allegory only when the speaker says that image "
                 "himself, shown exactly as he says it. A SET PHRASE IS NOT AN IMAGE: when his words name a thing but he "
                 "only means \"very\", \"obvious\", \"huge\", \"everywhere\" or \"at once\", those words get no picture. "
                 "When a sentence names nothing and claims nothing that can be shown, it gets no image: the face is the "
                 "picture. What a camera cannot shoot as it is IS a thing named: when the episode's REGISTERS give it one, "
                 "show it in that register. " + "PARALLEL_PLACEHOLDER"),
    "concept": ("Favour the IDEA over the noun: show what the sentence MEANS in one clear scene (the mechanism, "
                "the consequence, the analogy), and use a plain literal picture only when the word itself is the "
                "point."),
}
CLAUDE_PLAN_PROMPT = """You are the editor of a short-form clip cut from a longer conversation. {count_rule} {frame}

FIRST understand the clip inside its episode (the EPISODE BRIEF below: who talks, what the episode is about, the
visual glossary, the real stories told). Then write:
- "thesis": in one sentence, what the viewer must take away from THIS clip;
- "arc": setup -> claim -> payoff of the clip, in a few words each.
{mode_rule}
{sheet_rule}
Each image has a "role": "example" (a case, a place, an object, a creature, a scene the speaker tells — the usual
picture), "concept" (the notion itself, only when it is introduced, drawn as the glossary says: a real object,
instrument or place), "consequence" (what it leads to, when the speaker says it in concrete terms).
When a notion of the visual glossary is shown, draw it exactly as the glossary says (the channel always shows it the
same way).

{pace}
{names}
- a substance, a plant, food or drink; an object, a tool, a vehicle, a garment;
- a place, a building, a landscape, an era, an event; an animal; a body part; a kind of person;
- a scene of a story: who, where, doing what, with the real details the brief gives;
- an image the speaker builds himself, shown as he says it;
- a number or a scale, shown as the things counted; an action the viewer cannot see in the video.
{grounding}
{set_rule}
{cliche_line}
{experience_rule}Never: something already visible in the video (look at the frame sheets), a named real person, a brand (use a
generic equivalent). At most {cap} images.

Frame sheets: {sheets} — thumbnails of the clip every 2.5 s, each stamped with its time. Look at them first.

For each image give:
- "anchor": the exact 1-3 words as spoken where the image should land (verbatim from the transcript). The image
  pops up just before the most meaningful of these words (the noun that names the thing: "gallons" in "two gallons of
  water", not "two") is spoken, so choose words whose key word is the one that shows the thing;
- "time": the second the anchor is spoken (from the markers);
- "said": the sentence (about 8-15 words, verbatim) this image illustrates;
- "idea": the link the viewer makes between the picture and the words, in one sentence;
- "subject": the main thing seen, 1-3 words, one per image;
- "shot": wide | medium | close | macro | schematic;
- "worth": 1-5, how much this picture adds to the clip (5 = the one picture the clip needs, 1 = a nice extra): when
  two moments are too close, the higher worth stays;
- "notion": only when the image is simply THE usual picture of a notion of the brief's glossary (VISUAL GLOSSARY or
  OTHER NOTIONS, even if the speaker says it in other words), with no detail of this particular case (number, person,
  scene, era): its name exactly as listed. If the image must show a specific case, leave it empty;
- "image_prompt": one or two English sentences describing ONE clear scene: the thing named or told, with the
  specifics of "said" (number, place, era, who, action, mood): subject, action, setting, light. It must read on a phone at a third of the screen width: one main subject, simple background, no text.{style_rule}{mood_rule}
Only moments between {lo:.1f}s and {hi:.1f}s{avoid}, at least {gap:g} s apart.

EPISODE BRIEF:
{brief}
{bible}
CLIP TITLE: {title}
HOOK: {hook}
SAID JUST BEFORE THE CLIP (context only): {before}

TRANSCRIPT OF THE CLIP (seconds from the clip start):
{text}

SAID JUST AFTER THE CLIP (context only): {after}"""
# The clip's visual direction. Historical layouts: one style sheet for the set. The mixed layout (B-roll
# « ambiance », 2-oct-2026): no sheet to write — every picture's "mood" is answered and code makes its look.
SHEET_RULE = """Also write "style_sheet": ONE visual direction for the whole set of images of this clip, so they look shot by the
same person on the same day, in plain words a few words long each: "palette" (the 2-4 dominant colours), "light"
(kind and direction of the light), "era" (the period the story is in, or "present day"), "camera" (lens, angle,
grain), "mood". Take them from the topic, the era and the tone of the stories, not from the words of one sentence.
When an EPISODE VISUAL BIBLE is given below, take the pictures from its WORLD (the things this episode really
contains), return to its MOTIFS, and never show its WRONG FACTS."""
SHEET_RULE_MOOD = """THE LOOK of every picture comes from its "mood" (below): what kind of thing it is for a camera and how THIS moment
is lived, read from the words said, not from the topic. Write "style_sheet" only for "cast" (see CAST below).
Also write "clip_gravity": what the clip AS A WHOLE is about — "grave" only when the clip TELLS someone's death (the
story of a death, a suicide, a killing, a victim is what it is about); a risk of death, a number of deaths or deaths
named on the way are not: the clip is about what it argues. "real" when an illness or an addiction is its subject,
"none" otherwise.
When an EPISODE VISUAL BIBLE is given below, take the pictures from its WORLD (the things this episode really
contains), return to its MOTIFS, and never show its WRONG FACTS."""

REVIEW_FRAME = {
    "small": "Each image below will appear for about {dur:.1f} s, small (about a third of a phone screen's width),",
    "mixed": "Each image below will appear as a wide card above the speaker's head (about 60 % of a phone screen's width)\n"
             "for 2-3.5 s, or full screen for about 3 s when marked HERO,",
}
REVIEW_PROMPT = """{frame}
while the speaker says the quoted words.

STEP 1 - LOOK FIRST. For every image, before you read what it was meant to show, write "seen": one plain sentence
of what is really in it - the main subject, HOW MANY of it (count them), the setting, the era or look, any lettering,
symbol or logo (say if letters are garbled), anything odd (extra fingers, a distorted face). Describe only the pixels.

STEP 2 - THE SENSE AND THE FACTS, from what you wrote in "seen". The images, in the order they appear on screen:
{items}
"score" (THE SENSE, 1-5): does the picture show what the quoted words say - the thing named, with the specifics the
speaker gives (the number, the place, the era, the action, the mood)? SOUND-OFF TEST: a viewer who sees ONLY the
picture, then hears the words, links them within a second. 5 = instantly and exactly that; 4 = yes; 3 = the noun but
not what was said about it, or a link that needs explaining; 2 or 1 = another thing, or nothing to do with the words,
or A SET PHRASE TAKEN LITERALLY: the speaker uses a figure of speech for emphasis (his words name a thing, he means
"very", "obvious", "huge") and the picture shows that thing, however well it matches the words.
When a picture carries a "judge it on" line, that line says what must be seen: rate the sense against it first (only
what a still picture can show of it).
JUDGE WHAT A STILL PICTURE CAN SHOW: a name (a medicine, a brand, a label), a motion, a sequence or a change over time,
a sound or a voice cannot be seen — never lower the sense for them, nor because a precise prop is missing. A false
fact is still false (a person asleep when he was awake, the wrong place, era or number). A picture marked "fx" is
judged as the viewer will see it: "double" is shown to you WITH its effect (a faint copy drifting beside it);
"tremble" shakes finely on screen (judge the picture as trembling).
AN INNER PICTURE (marked INNER) shows what the person perceives: when the person is seen from outside in it — a face,
a silhouette, a figure, or people standing in for what is perceived (a crowd for voices) — its sense is 2, and its
"person_seen" is true (answer "person_seen" for every INNER picture).
A PAIR (marked PAIR) is two images side by side that must share the structure the speaker compares: each half the
real reference image of its field (its real subject, imaging technique and colours), both at the same scale, density
and framing. Halves that do not share that structure (an emblem of the field next to something else) — sense 2.
"facts_ok" (true / false): false when the picture states a false fact - the wrong organ, tool, animal or place, a
number or an era that contradicts the words or the EPISODE FACTS given below, or a precise chemical structure,
formula or labelled diagram (the image model invents their details). Judge facts against the quoted words and
the EPISODE FACTS, never against your own idea of what is plausible: a surprising scene the speaker tells (a cage on
a famous lawn) is a true scene, and the picture that shows it is right.
THE SET: the pictures are seen in a row. When two DIFFERENT moments show the same subject in the same framing, the
later one's sense drops a point and its better_prompt shows another side of the idea. Takes of ONE moment (marked
"take") are not a set: compare them with each other, score each apart, and say in "problem" which take is the better.

STEP 3 - THE LOOK (THE RENDERING, 1-5): is the picture well made for its frame and its kind? For a photograph: a
real light with a direction and a quality, one subject with air around it, readable at the size it is shown, the
artefacts (hands, faces, lettering, melted objects), no stock-photo feel, a mood that fits its subject (a patient,
an illness, a death is shown with dignity, never as a menace). A picture marked REGISTER below is not a photograph:
rate its look on its "judge it on" line, on its fidelity to the register it names and on its force, and
never on a real light source; its cheap line is its only stock test. 5 = a still a magazine would print, 4 = good,
3 = correct but flat, 2 or 1 = artefacts, stock or unreadable. A face, when one shows, must be natural and in focus with normal eyes,
teeth and hands; a deformed, waxy or doubled face scores look 2 at most.

"safe" (true / false): false when the picture evokes an overdose, a means of suicide or a symbol of death, even as a
cliché (pills spilled or heaped, an empty or tipped-over bottle by a bed, a rope, a blade near skin, a weapon aimed
at someone, a skull, a coffin, a grave, wilted flowers or a burnt-out candle for a death, a heart monitor with a
flat or failing line) — such a picture is never
shown, however well it matches the words. Read it WITH ITS WORDS: on a sentence that tells of a death, anything that
could be taken for its cause or its means — a substance, a medicine, a container of one — is not safe, however
harmless it would be on its own. Not safe either: a drug being taken or its gear in use (a pipe being lit, a needle in
a vein), and a PHOTOGRAPH of the inside of a body (an organ, a brain, tissue, blood, an open operation) — those are
drawn in the episode's drawing, and a drawing of them is safe.

For each image, by "file": "seen", "score" 1-5, "facts_ok" true / false, "safe" true / false, "look" 1-5, "problem" (a few words, empty
if none), "better_prompt" — empty when the score and the look are both 4 or 5 and facts_ok and safe are true; a
picture that fails ALWAYS gets one, written in full: the same idea, made to work — the scene rewritten IN THE
POSITIVE: describe only what IS in the frame, never "no", "not", "without" or "instead of" (the image model ignores
negations), and take out the words that caused the problem (if a window caused it, there is no window in the new
prompt). (Another idea, when this one has failed twice, is the art director's to write.)
When the image's own prompt is given below as ART-DIRECTED, write it in that same grammar, 80 to 120 words, in this
order: subject and action, setting, composition for its frame, lens and viewpoint, light (source, direction,
quality), palette and grade, material and detail, mood - keep what worked, change what failed."""
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"reviews": {"type": "array", "items": {
        "type": "object",
        "properties": {"file": {"type": "string"}, "seen": {"type": "string"}, "score": {"type": "integer"},
                       "facts_ok": {"type": "boolean"}, "safe": {"type": "boolean"},
                       "look": {"type": "integer"}, "problem": {"type": "string"}, "better_prompt": {"type": "string"},
                       "person_seen": {"type": "boolean"}},
        # v15b: the better prompt asked every time (empty for a picture that passes). The other idea (v15 "new_prompt")
        # is the art director's since v16 (another_idea): the review's were the same scene, or the cliché.
        "required": ["file", "seen", "score", "look", "better_prompt"]}}},
    "required": ["reviews"],
}

def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9']+", (text or "").lower()) if t]


def _numbered_text(words):
    """The clip's words with a [seconds] marker at every sentence / 4 s."""
    out, last = [], -99.0
    for i, w in enumerate(words):
        prev = words[i - 1]["text"] if i else "."
        if w["start"] - last >= 4.0 or re.search(r"[.!?]$", prev):
            out.append(f"\n[{w['start']:.1f}]")
            last = w["start"]
        out.append(w["text"])
    return " ".join(out).strip()


def _allowed(t, duration, avoid, head=HEAD_FREE, block=()):
    """``block``: (from, to) stretches of the clip no image may start in (the seconds the source itself shows a
    picture, already cut in as a card)."""
    return (head <= t <= duration - TAIL_FREE - SEG_DUR and all(abs(t - a) > 1.2 for a in avoid)
            and all(not (a <= t <= b) for a, b in block))


def _stem(text):
    return " ".join(t.rstrip("s") for t in _tokens(text))


def _space(moments, n, gap=MIN_GAP):
    """At most ``n``, ``gap`` s apart, never the same thing twice."""
    kept = []

    def same(a, b):
        # the same word, or the same thing seen (three "brain" images read as one image shown three times)
        return _stem(a["query"]) == _stem(b["query"]) or (
            bool(a.get("subject")) and _stem(a["subject"]) == _stem(b.get("subject") or ""))

    for m in sorted(moments, key=lambda m: -m.get("score", 1.0)):
        if len(kept) == n:
            filter_hit("parser: beyond n", f'Moment "{m["anchor"]}" at {m["t"]:.1f} s dropped: {n} pictures already kept, '
                                           f'this one worth {m.get("score", 1.0):g}.')
            continue
        clash = next((k for k in kept if abs(m["t"] - k["t"]) < gap or same(m, k)), None)
        if clash is None:
            kept.append(m)
        elif same(m, clash):
            filter_hit("parser: same subject", f'Moment "{m["anchor"]}" at {m["t"]:.1f} s dropped: the same thing as "{clash["anchor"]}".')
        else:
            filter_hit("parser: too close", f'Moment "{m["anchor"]}" at {m["t"]:.1f} s dropped: {abs(m["t"] - clash["t"]):.1f} s from '
                                            f'"{clash["anchor"]}" (worth {m.get("score", 1.0):g} against {clash.get("score", 1.0):g}).')
    return sorted(kept, key=lambda m: m["t"])


# The "hero" of a "mixed" clip: the one image shown full screen (~3 s). Chosen
# here and not only by the planner, so a Gemini plan gets one too and a planner's
# pick that breaks the timing rules is overruled.
HERO_ROLE = {"example": 2.0, "consequence": 2.0, "concept": 0.0}
HERO_SHOT = {"wide": 1.5, "medium": 1.0, "close": 0.5, "macro": 0.0, "schematic": -1.0}
HERO_STYLE = {"diagram": -2.0, "drawing": -1.0, "neon": -1.0, "comic": -1.0, "3d": -0.5}
HERO_MIN_SCORE = 2.5   # a plain photo of a concept fills the screen only as a medium shot in the payoff half; a close-up,
                       # a schematic or a diagram never does (an example or a consequence passes from a close-up on)


def hero_dur(m):
    """Time on screen of the hero: its sentence (``dur``) plus the crossfade, within HERO_DUR_MIN..MAX."""
    return round(min(HERO_DUR_MAX, max(HERO_DUR_MIN, float(m.get("dur") or 0) + HERO_FADE)), 2)


def full_dur(m, avoid=()):
    """Time on screen of a full-width drawing (the « dessin » chain, 5-oct-2026): hero_dur, ended PUNCH_CLEAR s before
    a punchline (``avoid``) said while it would be up — the face says the punchline. Under HERO_DUR_MIN: no room, the
    moment gets no picture (full_room)."""
    t, d = float(m["t"]), hero_dur(m)
    for a in avoid or ():
        if t < float(a) < t + d + PUNCH_CLEAR:
            d = min(d, float(a) - PUNCH_CLEAR - t)
    return round(d, 2)


def full_room(m, avoid=()):
    """A full-width drawing fits this moment: HERO_DUR_MIN s at least before the punchline."""
    return full_dur(m, avoid) >= HERO_DUR_MIN - 1e-6


def hero_fits(m, duration, avoid, head=HEAD_FREE, block=()):
    """A hero never runs into the hook's seconds, the last TAIL_FREE s, within
    1.2 s of the punchline, or a ``block`` stretch (the source's own picture) —
    on its whole time on screen, not only its first frame."""
    t, d = m["t"], hero_dur(m)
    if t < head or t + d > duration - TAIL_FREE:
        return False
    return (all(t + d <= a - 1.2 or t >= a + 1.2 for a in avoid)
            and all(t + d <= a or t >= b for a, b in block))


def pick_hero(moments, duration, avoid, head=HEAD_FREE, block=(), adaptive=False):
    """Index of the moment shown full screen, or None: a concrete scene (an example
    or a consequence, a wide or medium shot, a photographic style) that fits the
    timing rules. The planner's own "hero" counts for a lot, a moment in the second
    part of the clip (the payoff) a little; a tie goes to the later one. None when
    no moment reads well on a whole phone screen (a diagram, a schematic). ``adaptive`` (v13): the strongest moment
    wins — an experience or a "meaning" picture weighs like an example, a reveal +1.5, every point of worth above 3
    +0.5."""
    best, best_score = None, 0.0
    for i, m in enumerate(moments):
        if not hero_fits(m, duration, avoid, head, block) or m.get("notion"):
            continue
        role = HERO_ROLE.get(m.get("role") or "", 0.0)
        if adaptive and (m.get("show") == "meaning" or is_inner(m)):
            role = max(role, HERO_ROLE["example"])
        score = 1.0 + role + HERO_SHOT.get(m.get("shot") or "", 0.5)
        if adaptive:
            score += 1.5 if (m.get("mood") or {}).get("function") == "reveal" else 0.0
            score += 0.5 * max(0.0, float(m.get("score") or 1.0) - 3.0)
        score += HERO_STYLE.get(m.get("style") or "photo", 0.0)
        score += 3.0 if m.get("hero") else 0.0
        score += 0.5 if m["t"] > duration * 0.35 else 0.0
        if best is None or score > best_score + 1e-9 or (abs(score - best_score) < 1e-9 and m["t"] > moments[best]["t"]):
            best, best_score = i, score
    return best if best is not None and best_score >= HERO_MIN_SCORE else None


def _find_anchor(words, anchor, near):
    toks = _tokens(anchor)
    if not toks:
        return None
    best = None
    for i in range(len(words)):
        if abs(words[i]["start"] - near) > 4.0:
            continue
        seq = _tokens(" ".join(w["text"] for w in words[i:i + len(toks)]))
        if seq[:len(toks)] == toks or (len(toks) == 1 and toks[0] in _tokens(words[i]["text"])):
            if best is None or abs(words[i]["start"] - near) < abs(words[best]["start"] - near):
                best = i
    return best


def _plan_prompt(clip, words, n, avoid, auto_style, head=HEAD_FREE):
    duration = words[-1]["end"]
    avoid_txt = (", and not within 1.2 s of " + ", ".join(f"{a:.1f}s" for a in avoid)) if avoid else ""
    title = clip.get("video_title_for_youtube_short") or ""
    return PLAN_PROMPT.format(n=n + 2, lo=head, hi=duration - TAIL_FREE - SEG_DUR, avoid=avoid_txt,
                              style_rule=STYLE_RULE if auto_style else "",
                              style_field=', "style": "photo"' if auto_style else "",
                              title=f"\nCLIP TITLE: {title}\n" if title else "",
                              text=_numbered_text(words)[:6000])


# Which parts of a clip's style sheet each image style takes: a photo shares the
# light and the era, a neon / diagram / 3d picture only the colours.
SHEET_FIELDS = {"neon": ("palette",), "diagram": ("palette",), "3d": ("palette",),
                "drawing": ("palette", "mood"), "comic": ("palette", "mood")}
SHEET_ALL = ("palette", "light", "era", "camera", "mood")
SHOTS = ("wide", "medium", "close", "macro", "schematic")


def _clean_sheet(raw):
    """The planner's style_sheet -> {field: short text}, or None."""
    if not isinstance(raw, dict):
        return None
    sheet = {}
    for k in SHEET_ALL:
        v = _short_field(re.sub(r"\s+", " ", str(raw.get(k) or "")).strip(" ."), 70)
        if v:
            sheet[k] = v
    return sheet or None


def look_text(sheet, style):
    """One short sentence for the image prompt: the clip's look, restricted to
    what suits ``style``. Empty without a sheet."""
    if not sheet:
        return ""
    parts = [f"{k}: {sheet[k]}" for k in SHEET_FIELDS.get(style, SHEET_ALL) if sheet.get(k)]
    return ("Same visual look as the other images of the set — " + "; ".join(parts) + ".") if parts else ""


def _bible_block():
    """The episode's visual bible as prompt text, with a blank line after it ("" without one)."""
    import ai_brain
    text = ai_brain.bible_text()
    return text + "\n" if text else ""


def _short_field(text, limit=160):
    """``text`` within ``limit`` characters, cut after its last clause (comma or semicolon) when one ends past the
    half, never mid-word."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    end = max(head.rfind(", "), head.rfind("; "))
    if end < limit // 2:
        end = head.rfind(" ")
    return head[:end].rstrip(" ,;") if end > 0 else head


def _key_index(words, i, n):
    """Of the ``n`` words of an anchor starting at ``i``, the one that carries the
    meaning (the noun that names the thing, not "the" / "of" / a number word):
    the longest word that is not a stopword, the last one on a tie. The image
    lands there, so "two gallons of water" waits for "gallons", not for "two"."""
    best, best_len = i, -1
    for k in range(i, min(i + max(1, n), len(words))):
        toks = _tokens(words[k]["text"])
        w = toks[0] if toks else ""
        score = 0 if (not w or w in STOPWORDS) else len(w)
        if score >= best_len and score > 0:
            best, best_len = k, score
    return best


def _moment_dur(words, i, t, duration, lo=DUR_MIN, hi=DUR_MAX):
    """How long the image stays: from its word to the end of the sentence (or of
    the clause, once it has lasted ``lo``), so it goes away when the voice moves
    on to something else. Clamped to lo..hi and to the clip's end."""
    end = words[i]["end"]
    for j in range(i, len(words)):
        end = words[j]["end"]
        text = words[j]["text"]
        if end - t >= hi:
            break
        if re.search(r"[.!?;:…]$", text) or (re.search(r",$", text) and end - t >= lo):
            break
    dur = max(lo, min(hi, end - t + DUR_TAIL))
    return round(min(dur, max(lo, duration - 1.0 - t)), 2)


def _parse_moments(data, words, n, avoid, gap=MIN_GAP, dur_range=None, tail=None, head=HEAD_FREE, block=(),
                    keep_worth=None, fixed=False):
    """The planner's answer -> moments that land on a real spoken word, in
    the allowed window, spaced out. Anything that does not check out is
    dropped, whoever the planner was. ``dur_range``: (min, max) s on screen
    (the "mixed" layout's cards stay longer than the historical ones);
    ``tail``: seconds at the end of the clip no image may run into; ``head``:
    the first seconds left to the face (the hook's); ``block``: (from, to)
    stretches no image may start in or run into (the source's own picture). ``keep_worth``: a candidate below
    this worth is dropped (the mixed layout's candidates); a named experience (not grave) gets INNER_PRIORITY more.
    ``fixed``: the bench's fixed moments — every one kept (no spacing, no count), the ones the editor skipped
    recorded in LAST_SKIPS."""
    duration = words[-1]["end"]
    lo, hi = dur_range or (DUR_MIN, DUR_MAX)
    moments = []
    sheet = _clean_sheet((data or {}).get("style_sheet"))
    for m in (data or {}).get("moments") or []:
        try:
            near = float(m.get("time", 0))
        except (TypeError, ValueError):
            continue
        flagged = [f for f in FLAGS if m.get(f) is True]
        if flagged:
            why = "flagged " + ", ".join(f.replace("_", " ") for f in flagged)
            if fixed:
                LAST_SKIPS.append({"t": near, "anchor": str(m.get("anchor") or "")[:80], "why": why})
            filter_hit(f"editor: {why}", f'Moment "{m.get("anchor")}" at {near:.1f} s not made: {why}.')
            continue
        if fixed and m.get("skip"):
            why = re.sub(r"\s+", " ", str(m.get("skip_why") or "")).strip()[:200]
            LAST_SKIPS.append({"t": near, "anchor": str(m.get("anchor") or "")[:80], "why": why})
            filter_hit("editor: fixed moment skipped", f'Moment "{m.get("anchor")}" at {near:.1f} s left without a picture: {why}')
            continue
        i = _find_anchor(words, m.get("anchor"), near)
        if i is None:
            filter_hit("parser: anchor not found",
                       f'Moment "{m.get("anchor")}" at {near:.1f} s dropped: its words are not in the transcript there.')
            continue
        n_tok = len(_tokens(m.get("anchor")))
        k = _key_index(words, i, n_tok)
        t = max(0.0, words[k]["start"] - KEY_LEAD)
        if not _allowed(t, duration, avoid, head, block):
            filter_hit("parser: outside the window",
                       f'Moment "{m.get("anchor")}" at {t:.1f} s dropped: in the hook, the tail, on the punchline or on the source\'s picture.')
            continue
        dur = _moment_dur(words, k, t, duration, lo, hi)
        if tail:
            dur = round(min(dur, duration - tail - t), 2)
            if dur < lo:
                filter_hit("parser: runs into the tail",
                           f'Moment "{m.get("anchor")}" at {t:.1f} s dropped: it would run into the last {tail:g} s (the face keeps them).')
                continue
        for a, _b in block:
            if t < a:
                dur = round(min(dur, a - DUR_NEXT_GAP - t), 2)   # it leaves before the source's picture comes up
        if dur < lo:
            filter_hit("parser: too short before the source's picture",
                       f'Moment "{m.get("anchor")}" at {t:.1f} s dropped: no room before the source\'s own picture.')
            continue
        moments.append({"t": t, "anchor": " ".join(w["text"] for w in words[i:i + n_tok]),
                        "key": words[k]["text"],
                        "query": str(m.get("search_query") or m.get("anchor"))[:60],
                        "prompt": str(m.get("image_prompt") or m.get("anchor"))[:PROMPT_MAX],
                        "idea": str(m.get("idea") or "")[:200],
                        "said": str(m.get("said") or "")[:200],
                        "subject": str(m.get("subject") or "")[:40],
                        "shot": m.get("shot") if m.get("shot") in SHOTS else None,
                        "style": m.get("style") if (m.get("style") in STYLES or register_of(m.get("style"))) else None,
                        "role": m.get("role") if m.get("role") in ("concept", "example", "consequence") else None,
                        "notion": str(m.get("notion") or "")[:80],
                        "real_photo": bool(m.get("real_photo")) and bool(str(m.get("search_query") or "").strip()),
                        "hero": bool(m.get("hero")),
                        "hero_why": re.sub(r"\s+", " ", str(m.get("hero_why") or "")).strip()[:200],
                        "mood": visual_mood.clean(m["mood"]) if isinstance(m.get("mood"), dict) else None,
                        "show": m.get("show") if m.get("show") in ("thing", "meaning") else None,
                        "people": m.get("people") if m.get("people") in PEOPLE else None,
                        "parallel": m.get("parallel") if m.get("parallel") in ("one", "pair") else None,
                        "inside_body": m.get("inside_body") is True,
                        "point": re.sub(r"\s+", " ", str(m.get("point") or "")).strip()[:160],
                        "dur": dur,
                        "sheet": sheet,
                        "score": _worth(m.get("worth")), "worth_given": m.get("worth") is not None})
    for mo in moments:
        mood = mo.get("mood") or {}
        if mood.get("visibility") == "inner" and mood.get("gravity") != "grave":
            mo["score"] = mo["score"] + INNER_PRIORITY     # a named experience is kept among the candidates
    if fixed:
        kept = sorted(moments, key=lambda m: m["t"])
    else:
        if keep_worth:
            for mo in moments:
                if not mo.get("worth_given"):
                    mo["score"] = max(mo["score"], keep_worth)      # no worth said: kept like a plain candidate
            for mo in [mo for mo in moments if mo["score"] < keep_worth]:
                filter_hit("parser: low worth", f'Candidate "{mo["anchor"]}" at {mo["t"]:.1f} s left out: worth {mo["score"]:g}.')
            moments = [mo for mo in moments if mo["score"] >= keep_worth]
        kept = _space(moments, n, gap)
    for a, b in zip(kept, kept[1:]):
        # never run into the next image
        a["dur"] = round(max(lo, min(a["dur"], b["t"] - a["t"] - DUR_NEXT_GAP)), 2)
    return kept


def plan_with_gemini(clip, words, n, avoid, api_key, auto_style=False, dur_range=None, gap=MIN_GAP, tail=None,
                     head=HEAD_FREE, block=()):
    from google import genai
    from google.genai import types
    prompt = _plan_prompt(clip, words, n, avoid, auto_style, head) + _block_text(block)
    client = genai.Client(api_key=api_key)
    last = None
    for attempt in range(3):
        try:
            r = client.models.generate_content(
                model=TEXT_MODEL, contents=[prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json"))
            data = json.loads(r.text or "{}")
            break
        except Exception as e:
            last = e
            time.sleep(4 * (attempt + 1))
    else:
        raise RuntimeError(f"moment planning failed: {last}")
    return _parse_moments(data, words, n, avoid, gap, dur_range, tail, head, block)


def _block_text(block):
    """One line of the planner's prompt per stretch the source's own picture takes."""
    return "".join(f"\nNo image between {a:.1f}s and {b:.1f}s: the video itself shows a picture there, already "
                   f"cut in big, and the viewer must see it alone." for a, b in block)


# --- Claude (the user's subscription, through Claude Code) -----------------------

def claude_ready():
    """Claude can think for this job (set up, not switched off by a quota)."""
    import ai_brain
    return ai_brain.claude_usable()


def claude_json(prompt, schema, timeout=240, attach=None, stage=None, effort=None, model=None, system=None, reuse=True):
    """One Claude call through ai_brain (the job-wide Claude-first switch): a
    quota / session limit switches Claude off for the rest of the job.
    ``model``: the profile's model for the B-roll by default; ``system``: the
    editor's voice by default (the art director has its own). ``reuse=False``:
    never the remembered answer (the bench asks a judge the same question again)."""
    import ai_brain
    model = model or ai_brain.stage_model("broll")
    if stage:
        ai_brain.say(f"Claude · {model}", stage)
    try:
        return ai_brain.claude_json(prompt, schema, timeout=timeout, attach=attach, effort=effort, model=model,
                                    system=system or (CLAUDE_SYSTEM_VISION if attach else CLAUDE_SYSTEM), reuse=reuse)
    except Exception as e:
        ai_brain._switch_off_if_limit(e)
        raise


def _context(transcript, start, end, before=45.0, after=20.0):
    """What was said just before and after the clip in the full conversation:
    the clip often starts mid-argument, and the image must serve the point."""
    pre, post = [], []
    for seg in (transcript or {}).get("segments", []) or []:
        for w in seg.get("words") or []:
            ws = float(w.get("start", 0))
            text = (w.get("word") or "").strip()
            if start - before <= ws < start:
                pre.append(text)
            elif end < ws <= end + after:
                post.append(text)
    return " ".join(pre)[-1500:], " ".join(post)[:700]


def _frame_sheets(clip_path, folder, every=2.5, cols=5, tile_w=216):
    """Thumbnails of the clip every ``every`` s, each stamped with its time:
    Claude sees what is already on screen. Packed ``cols`` wide and as many
    rows as fit Claude's image budget (~1.2 MP: 15 vertical tiles), the last
    sheet cropped to its rows — a 35 s clip is ONE sheet (~1.5k tokens) where
    it was two 4x3 sheets, the second one mostly black but billed in full."""
    from PIL import ImageFont
    subprocess.run(["ffmpeg", "-v", "error", "-i", clip_path, "-vf",
                    f"fps=1/{every:g}:round=down,scale={tile_w}:-2",
                    os.path.join(folder, "f_%03d.jpg")], check=True)
    frames = sorted(f for f in os.listdir(folder) if f.startswith("f_"))
    if not frames:
        return []
    with Image.open(os.path.join(folder, frames[0])) as first:
        tw, th = first.size
    per = cols * max(1, int(1_250_000 // (cols * tw * th)))
    fs = max(14, int(tw * 0.1))
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", fs)
    except OSError:
        font = ImageFont.load_default()
    sheets = []
    for s in range(0, len(frames), per):
        chunk = frames[s:s + per]
        rows = -(-len(chunk) // cols)
        sheet = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
        for k, f in enumerate(chunk):
            tile = Image.open(os.path.join(folder, f)).convert("RGB")
            d = ImageDraw.Draw(tile)
            label = f"{(s + k) * every:.1f}s"
            d.rectangle((0, 0, int(fs * 0.55 * len(label)) + 8, fs + 6), fill=(0, 0, 0))
            d.text((4, 2), label, fill=(255, 216, 77), font=font)
            sheet.paste(tile, ((k % cols) * tw, (k // cols) * th))
        path = os.path.join(folder, f"frames_{s // per + 1}.jpg")
        sheet.save(path, quality=85)
        sheets.append(path)
    return sheets


def apply_notions(moments, brief, clip_text):
    """A moment whose image is the plain picture of a glossary notion (the planner
    named it) is tagged with the notion's exact name; the channel's usual picture
    is then reused from the notion memory when one exists. A notion the clip did
    not say in words (the planner had only its meaning) also gets its glossary
    picture added to the image prompt. A name that is not in the glossary is
    dropped."""
    import ai_brain
    if not brief:
        return moments
    matched, rest = ai_brain.glossary_split(brief, clip_text)

    def norm(t):
        return re.sub(r"\W+", " ", str(t or "").lower()).strip()

    said_names = {norm(g.get("term")) for g in matched}
    by_name = {norm(g.get("term")): g for g in [*matched, *rest]}
    for m in moments:
        g = by_name.get(norm(m.get("notion")))
        if not g:
            m["notion"] = ""
            continue
        own = ai_brain._content(" ".join(str(m.get(k) or "") for k in ("subject", "anchor", "query")))
        drawn = ai_brain._content(str(g.get("visual") or ""))
        # The picture IS the notion when its subject names the term, or names what the glossary draws for it
        # ("brain scan" for "Mesial temporal sclerosis" -> "a medical brain scan showing the temporal lobe").
        if not (ai_brain._term_matches(g["term"], own) or (own and len(own & drawn) >= min(2, len(own)))):
            filter_hit("notion: tag dropped")
            # The tag names a notion the picture does not show (a cardboard box tagged "Ego dissolution"): the
            # glossary's drawing would be glued onto a stranger, or the library's picture shown in its place.
            print(f"   ℹ️ Notion \"{g['term']}\" tagged on \"{m.get('subject') or m['anchor']}\", which is not it — tag dropped.")
            m["notion"] = ""
            continue
        m["notion"] = g["term"]
        if norm(g["term"]) not in said_names:
            m["prompt"] = f"{m['prompt']} Draw {g['term']} the channel's usual way: {g['visual']}."[:PROMPT_MAX]
            print(f"   📚 Notion \"{g['term']}\" recognised by meaning — glossary picture added.")
    return moments


def plan_with_claude(clip, words, n, avoid, auto_style=False, transcript=None, start=0.0, end=None,
                     sheets=None, ground=None, mode="mixed", density="normal", hero=False,
                     dur_range=None, gap_min=0.0, tail=None, head=HEAD_FREE, block=(), fixed=None, parallel=False):
    """Claude reads the clip, the conversation around it and (``sheets``) what
    is on screen, and places images that carry the IDEA being said.
    ``ground``: hook_grounding.request()'s (frames, prompt) — the hook is
    rewritten from the screen in this same call instead of a second one.
    ``hero``: the "mixed" layout — it may name the one image worth the whole
    screen. ``gap_min`` / ``tail`` / ``head``: that layout's pace (MIXED_*).
    ``block``: the seconds the source's own picture takes (no image there)."""
    import ai_brain
    duration = words[-1]["end"]
    gap = max(DENSITY[density]["gap"], gap_min)
    before, after = _context(transcript, start, end if end is not None else start + duration)
    avoid_txt = (", and not within 1.2 s of " + ", ".join(f"{a:.1f}s" for a in avoid)) if avoid else ""
    avoid_txt += _block_text(block)
    title = clip.get("video_title_for_youtube_short") or ""
    clip_text = " ".join(w["text"] for w in words)
    brief = ai_brain.brief_for_clip(ai_brain.EPISODE_BRIEF, f"{before} {clip_text} {after}", start,
                                    end if end is not None else start + duration)
    pace_of = DENSITY_MIXED if hero else DENSITY      # the mixed layout has its own, selective pace
    del LAST_SKIPS[:]
    pace, cap = pace_of[density]["pace"], n
    if fixed:
        # The bench's fixed moments: one answer per moment, a picture or a reason to leave it without one.
        count_rule = ("THE MOMENTS ARE FIXED (a comparison bench): give exactly one entry per moment listed below, with "
                      "its anchor and time as given; when the rules say a moment gets no picture, keep its entry with "
                      "\"skip\": true and \"skip_why\" (one line).\n" + "\n".join(
                          f'- time {float(f["time"]):.1f}, anchor "{f["anchor"]}" — said: "{f.get("said") or ""}"' for f in fixed))
        pace, cap = "", len(fixed)
    elif hero:
        # The mixed layout's candidates: the editor lists, the code keeps the best (a stable choice).
        cap = n + CANDIDATES_MORE
        count_rule = (f"List the CANDIDATE B-roll images of this clip — every moment where the speaker names or tells "
                      f"something worth showing, up to {cap}, none when it names nothing — each with its \"worth\": the "
                      f"code keeps the best {n} (worth 3 or more), never in the hook or the last seconds.")
        pace = (pace + f" CANDIDATES: list every moment that qualifies (up to {cap}); the code keeps up to {n}, spaced "
                       f"at least {max(DENSITY[density]['gap'], gap_min):g} s apart, by worth.")
    else:
        count_rule = f"Add up to {n} B-roll images — fewer when the clip names little, none when it names nothing."
    mode_rule = MODE_RULES.get(mode, MODE_RULES["mixed"]).replace(" PARALLEL_PLACEHOLDER", " " + PARALLEL_RULE.replace("\n", " "))
    if parallel and not hero and "A PARALLEL" not in mode_rule:
        mode_rule += " " + PARALLEL_RULE.replace("\n", " ")     # the mixed layout has it in every request (v16)
    common = dict(n=n, cap=cap, count_rule=count_rule, avoid=avoid_txt,
                  sheets=", ".join(os.path.basename(p) for p in sheets or []) or "none",
                  frame=FRAME_TEXT["mixed" if hero else "small"],
                  style_rule=((style_rule_premium() if hero else STYLE_RULE) if auto_style else ""),
                  mood_rule=("\n" + visual_mood.MOOD_RULE) if hero else "",
                  sheet_rule=SHEET_RULE_MOOD if hero else SHEET_RULE,
                  mode_rule=mode_rule,
                  title=title or "-",
                  hook=clip.get("viral_hook_text") or "-", before=before or "-", after=after or "-",
                  brief=brief or "(no brief for this video)", bible=_bible_block(), text=_numbered_text(words)[:6000],
                  grounding=GROUNDING_RULE, set_rule=SET_RULE, cliche_line=CLICHE_LINE,
                  experience_rule=("\n".join((EXPERIENCE_RULE, EMPTY_RULE, PRECISION_RULE, SAFETY_RULE, BODY_RULE,
                                              PARALLEL_RULE, KNOWN_PICTURE_RULE, PEOPLE_RULE, FLAGS_RULE)) + "\n")
                  if hero else "",
                  pace=pace, names=pace_of[density]["names"],
                  gap=gap)
    prompt = CLAUDE_PLAN_PROMPT.format(lo=head, hi=duration - TAIL_FREE - SEG_DUR, **common)
    schema, attach, shots_dir = PLAN_SCHEMA, list(sheets or []), None
    if hero:
        # The mixed layout: the schema is the style rule — "photo" and the episode's registers, nothing else can even
        # be returned; every picture answers the mood questions (anchored levels: an enum each), and the clip's
        # sheet is only its recurring cast.
        schema = json.loads(json.dumps(schema))
        item = schema["properties"]["moments"]["items"]
        item["properties"]["style"]["enum"] = list(PREMIUM_STYLES) + register_names()
        item["properties"]["mood"] = visual_mood.SCHEMA
        item["required"] = list(item["required"]) + ["mood", "worth", "people", "parallel", "inside_body"] + list(FLAGS)
        item["properties"]["inside_body"] = {"type": "boolean"}
        for flag in FLAGS:
            item["properties"][flag] = {"type": "boolean"}
        item["properties"]["people"] = {"type": "string", "enum": list(PEOPLE)}
        item["properties"]["parallel"] = {"type": "string", "enum": list(PARALLEL_KINDS)}
        schema["properties"]["clip_gravity"] = {"type": "string", "enum": ["none", "real", "grave"]}
        schema["required"] = list(schema.get("required") or []) + ["clip_gravity"]
        if mode == "adaptive":
            item["properties"]["show"] = {"type": "string", "enum": ["thing", "meaning"]}
            item["properties"]["point"] = {"type": "string"}
            item["required"] = list(item["required"]) + ["show"]
        if fixed:
            item["properties"]["skip"] = {"type": "boolean"}
            item["properties"]["skip_why"] = {"type": "string"}
        schema["properties"]["style_sheet"] = {"type": "object", "properties": {"cast": {"type": "string"}}}
    if hero:
        prompt += "\n" + (HERO_RULE_ADAPTIVE if mode == "adaptive" else HERO_RULE)
        schema = json.loads(json.dumps(schema))
        schema["properties"]["moments"]["items"]["properties"]["hero"] = {"type": "boolean"}
        schema["properties"]["moments"]["items"]["properties"]["hero_why"] = {"type": "string"}
        schema["properties"]["hero_options"] = {"type": "array", "items": {
            "type": "object", "properties": {"anchor": {"type": "string"}, "picture": {"type": "string"}, "why": {"type": "string"}},
            "required": ["picture"]}}
    if ground:
        frames, hook_prompt = ground
        shots_dir = tempfile.mkdtemp(prefix="hookshots_")
        for k, b in enumerate(frames):
            p = os.path.join(shots_dir, f"screen_{k + 1}.jpg")
            with open(p, "wb") as f:
                f.write(b)
            attach.append(p)
        names = ", ".join(f"screen_{k + 1}.jpg" for k in range(len(frames)))
        prompt += (f"\n\nSECOND TASK, same clip — field \"hook\". The files {names} are {len(frames)} frames of "
                   f"this clip at full resolution (read the on-screen text on them).\n{hook_prompt}")
        schema = json.loads(json.dumps(schema))
        schema["properties"]["hook"] = {"type": "object", "properties": {
            "on_screen": {"type": "string"}, "viral_hook_text": {"type": "string"},
            "video_title_for_youtube_short": {"type": "string"}},
            "required": ["on_screen", "viral_hook_text", "video_title_for_youtube_short"]}
        schema["required"] = list(schema.get("required") or []) + ["hook"]
    try:
        # The judgment call of the B-roll (which idea, which image): high
        # effort, paid for by the checks Gemini now does.
        data = claude_json(prompt, schema, timeout=600, attach=attach or None,
                           effort=os.environ.get("CLAUDE_EFFORT_BROLL") or "high",
                           stage="B-roll: understanding the clip and choosing its images"
                                 + (" + hook from the screen" if ground else ""))
    finally:
        if shots_dir:
            shutil.rmtree(shots_dir, ignore_errors=True)
    if ground:
        import hook_grounding
        hook_grounding.apply(clip, (data or {}).get("hook"), len(ground[0]))
    moments = _parse_moments(data, words, len(fixed) if fixed else n, avoid, gap, dur_range, tail, head, block,
                             keep_worth=KEEP_WORTH if (hero and not fixed) else None, fixed=bool(fixed))
    if mode == "adaptive":
        for m in moments:
            want = expected_show(m)
            if want and m.get("show") and m["show"] != want:
                filter_hit("show: against the axes", f'Moment "{m["anchor"]}": shows the {m["show"]}, its axes say {want}.')
        print("   🧭 Show: " + " | ".join(f"{m.get('subject') or m['anchor']}: {m.get('show') or '-'}"
                                         + (f" ({m['point']})" if m.get("point") else "") for m in moments))
    for m in moments:
        if m.get("hero") and m.get("notion"):
            # The hero is THIS clip's picture, never the channel's usual picture of a notion: the editor's pick
            # stays the hero (pick_hero refuses a notion), made for this clip and not kept for the others.
            print(f"   🎯 Hero \"{m['anchor']}\" is also notion \"{m['notion']}\": made for this clip, not from the library.")
            m["notion"] = ""
    apply_notions(moments, ai_brain.EPISODE_BRIEF, f"{before} {clip_text} {after}")
    thesis = str((data or {}).get("thesis") or "")[:300]
    if thesis:
        print(f"   💡 Clip thesis: {thesis}")
    options = [{k: re.sub(r"\s+", " ", str(o.get(k) or "")).strip()[:200] for k in ("anchor", "picture", "why")}
               for o in ((data or {}).get("hero_options") or []) if isinstance(o, dict) and str(o.get("picture") or "").strip()][:3]
    chosen = next((m for m in moments if m.get("hero")), None)
    if options:
        print(f"   🎯 Hero options: " + " | ".join(o["picture"][:80] for o in options)
              + (f" -> chosen \"{chosen['anchor']}\"" + (f": {chosen['hero_why']}" if chosen.get("hero_why") else "") if chosen else ""))
    cast = str(((data or {}).get("style_sheet") or {}).get("cast") or "")[:200]
    if cast:
        print(f"   🎭 Recurring subject: {cast}")
    subjects = [m.get("subject") for m in moments if m.get("subject")]
    if subjects:
        print(f"   🎞️ Sequence: {' -> '.join(subjects)}")
    moods = [f"{m.get('subject') or m['anchor']}: {visual_mood.describe(m['mood'])}"
             + (f" («{m['mood']['cue']}»)" if m["mood"].get("cue") else "") for m in moments if m.get("mood")]
    if moods:
        print("   🎚️ Moods: " + " | ".join(moods))
    missing = sorted({a for m in moments if m.get("mood") for a in m["mood"]["defaulted"]})
    if missing:
        filter_hit("mood: level missing", f"Mood levels missing, the plain level used: {', '.join(missing)}.")
    clip_gravity = (data or {}).get("clip_gravity") if (data or {}).get("clip_gravity") in ("none", "real", "grave") else None
    if clip_gravity == "grave":
        print("   🕯️ The clip is about a death: every picture sober, an absence.")
    for m in moments:
        m["thesis"] = thesis
        m["hero_options"] = options
        m["clip_gravity"] = clip_gravity
    pairs = [f'{m.get("subject") or m["anchor"]}: {m["parallel"]}' for m in moments if m.get("parallel")]
    if pairs:
        print("   🪞 Parallel: " + " | ".join(pairs))
    return moments


# --- the art director (B-roll v2, profile-less: plus.BROLL["art_director"]) ---------------------------
# The editor (plan_with_claude) decides WHAT each picture shows and WHEN; a second
# call, the director of photography, writes the prompt the image model paints
# from — for the whole set at once, so every picture shares one light and one
# palette, in a fixed grammar the model reads best: subject and action, setting,
# composition for its frame, lens, light, palette, material, mood. 80-120 words,
# stated in the positive (at cfg 1.0 a negation does nothing).
ART_MIN_WORDS, ART_MAX_WORDS = 40, 220   # an answer outside this is not a prompt: the editor's draft stays
# s: one art director's call at most. Opus at max effort (the user's choice on 2-oct-2026) answers in 25-160 s; one
# call once hung 658 s for 4k tokens written (an overloaded API, retried in silence): past this, Sonnet does it.
ART_TIMEOUT = int(_knob("BROLL_ART_TIMEOUT", 240))


def art_effort():
    """The art director's thinking level: its own (profile brain.thinking_art -> CLAUDE_EFFORT_BROLL_ART), else the
    B-roll's, else high."""
    return os.environ.get("CLAUDE_EFFORT_BROLL_ART") or os.environ.get("CLAUDE_EFFORT_BROLL") or "high"


def _art_call(prompt, stage):
    """One art director's call on its model and effort; when it does not answer within ART_TIMEOUT, the same request
    goes to Sonnet (high effort) once — counted."""
    import subprocess
    import ai_brain
    model = ai_brain.stage_model("broll_art")
    try:
        return claude_json(prompt, ART_SCHEMA, timeout=ART_TIMEOUT, effort=art_effort(), stage=stage, model=model,
                           system=ART_SYSTEM)
    except Exception as e:
        slow = isinstance(e, subprocess.TimeoutExpired) or "timed out" in str(e).lower()
        if model == "sonnet" or not slow:
            raise
        filter_hit("art: too slow, sonnet instead", f"{stage}: {model} gave no answer in {ART_TIMEOUT} s — Sonnet instead.")
        return claude_json(prompt, ART_SCHEMA, timeout=ART_TIMEOUT, effort="high", stage=stage, model="sonnet",
                           system=ART_SYSTEM)
# Where a clear, natural face may show (plus.BROLL["faces"]): never (every person anonymous, face turned away),
# hero (the full-screen picture only: a look, a gesture, a posture is often THE picture), always. Nobody real
# and recognisable in any mode; the other guardrails (counts, lettering, brands, crowds) stay.
FACE_MODES = ("never", "hero", "always")
FACE_TEXT = {
    "never": "FACES: People stay anonymous on every picture (turned away, in shadow, small in the frame).",
    "hero": "FACES: a clear, natural face with a real expression is welcome on the HERO and only there: a look, a\n"
            "  gesture, a posture is often the picture. On the cards keep people anonymous (turned away, in shadow, small).",
    "always": "FACES: a clear, natural face with a real expression is welcome on every picture: a look, a gesture, a\n"
              "  posture is often the picture.",
}
ART_SYSTEM = "You are a director of photography for a documentary channel. You answer only with the requested JSON."
ART_PROMPT = """You are the director of photography of a short-form documentary channel. The editor has chosen the
moments of this clip that get a picture and what each one must show; you write the prompt the image model will
paint from, for EVERY picture of the set at once, so they look made by one hand.

{look_rule}
{bible}THIS CLIP'S STYLE SHEET (the editor's): {sheet}
THE CLIP: title "{title}"; thesis: {thesis}
{glossary}
THE PICTURES, in the order they are seen:
{moments}

Write ONE prompt per picture, 80 to 120 English words (never more: a longer prompt is cut at its last full sentence),
in this fixed order, each part one or two plain sentences:
1. SUBJECT AND ACTION: who or what, doing what, with every specific the editor gives (number, place, era, state).
2. SETTING: the exact place and time of day, what surrounds the subject.
3. COMPOSITION FOR ITS FRAME. A HERO fills a phone screen (9:16): the subject sits in the upper-middle third,
   something close and soft gives depth in the foreground, and the lower third stays calm and dark (captions go
   there). A CARD is a small wide frame (16:10) seen above the speaker's head: one clear subject with air around
   it, readable at a glance when small.
4. LENS AND POINT OF VIEW: the focal length (24, 35, 50, 85 mm, macro), the camera's height and distance.
5. LIGHT: its source, its direction and its quality.
6. PALETTE: the true colours of the scene's things and light sources, said in those things.
7. MATERIAL AND DETAIL: textures and surfaces, and the one small true detail that proves the place is real.
8. MOOD: two or three words.

RULES
- One hand: the pictures of the set share what their looks share; where one picture's look differs from the
  others (a darker moment, an older era, an inner experience), that picture differs as much. Vary the shots (wide,
  medium, close, macro) so no two pictures look alike; the HERO is the widest and most cinematic frame of the set.
- THE HERO is the clip's poster: one unforgettable frame of the thing or the scene the editor chose, as it really
  is — never an allegory. Spend your best sentences on it: a real scale, a human presence, depth, the light of its
  look.
- Describe what IS in the frame, never what is not: the image model ignores negations ("no text", "without
  people" do nothing): say what fills the space instead.
- A VIEWER READS IT IN ONE SECOND: say what is seen in plain, concrete words a viewer would use — the thing, where
  it is, its light and colours. No ornament, jewel, carving, architecture, paper, ink or material the sentence does
  not call for, no literary metaphor: an experience is painted with the colours, light and motion it is told with,
  never decorated.
- {extra_rules}
- {medium_rule}
- Keep every fact the editor gives, the glossary's way of drawing a notion, and the subject of each picture.
- PHOTO pictures: {cliche}
  When the editor's draft or a glossary line is one of these clichés, keep its subject and shoot it as a real
  thing at its true scale in a real place.
{registers}
- Nothing written anywhere in the scene (signs, screens, pages and labels show plain surfaces).
- {faces} Nobody real and recognisable, ever.

For EVERY picture also write "judge": one sentence, what a good picture of THIS one is (what must be seen, what
would make it wrong) — the reviewer rates the picture against it — only what a STILL picture can show: never a name
or a label, a motion, a sequence or a change over time, a sound or a voice; a false fact stays wrong.
And "fx": "none", or what the edit adds to the sharp picture because the image model cannot draw it — "double" (a
faint copy of the picture that drifts beside it: a presence doubled, a voice that is another person, a split) or
"tremble" (a fine shake: a perception that shivers, a panic). With an fx, the prompt paints ONE sharp, single image
(never a doubled, ghosted, blurred or shaking subject).
And "people": who is in the frame of YOUR prompt — "none" (nobody), "hands" (hands only), "one" (one or a few
people), "group" (a crowd); an inner picture is "none". The image model's guard adds a face or a crowd only from this.
And, for THE HERO only, "alt_prompt": the same moment shot another way — another viewpoint, distance or framing of
the same scene, same rules, same length (the image model paints nearly the same picture from one prompt whatever the
seed: its second take needs other words); "" for a card.

Return JSON: {{"prompts": [{{"k": 0, "prompt": "...", "judge": "...", "fx": "none", "people": "none", "alt_prompt": ""}}, ...]}}
with the "k" of every picture above."""
REGISTER_TEXT = """- REGISTER PICTURES: a picture marked REGISTER below is not a photograph and has no look sheet: its register
  is its STYLE (the look of one picture), never its scene — the scene comes from THIS picture's sentence (what the
  speaker says happens or is perceived here), so two pictures of one register never share a scene. An inner register
  paints what the person perceives as WHAT FILLS THE FRAME (shapes, light, colours, surfaces) — never the person seen
  from outside, never the viewer: no "first-person", "point of view" or "through his eyes" (the image model then
  draws a person), never a sound or a feeling named as such (say what is SEEN). Write it in this
  order: 1. what is seen (this sentence's content), 2. geometry and scale, 3. colours and light (the register's),
  4. composition for its frame, 5. medium and texture, 6. mood. Make it as strange, saturated or vast as its register
  says; its "cheap" line is what to stay away from. Still 80 to 120 words, still nothing written anywhere, still
  nobody real."""
ART_SCHEMA = {
    "type": "object",
    "properties": {"prompts": {"type": "array", "items": {
        "type": "object",
        "properties": {"k": {"type": "integer"}, "prompt": {"type": "string"}, "judge": {"type": "string"},
                       "fx": {"type": "string", "enum": ["none", "double", "tremble"]},
                       "people": {"type": "string", "enum": list(PEOPLE)}, "alt_prompt": {"type": "string"},
                       "inside_body": {"type": "boolean"}},
        "required": ["k", "prompt", "people"]}}},
    "required": ["prompts"],
}
# The pair and the one image of a parallel (v16), told to the director for the pictures the editor marked.
PAIR_LINE = ("  PAIR (he shows the comparison now; this overrules the editor's draft and the register's medium and "
             "palette): the two side by side in one frame, each half the real reference image of its own field — its real "
             "subject, the imaging technique of that field, its real colours, never the field's emblem — both halves at "
             "the same scale, density and framing, each showing the shared structure WHOLE (a dense network of many "
             "elements, never one element of it); name both halves and both imaging techniques in the prompt.")
ONE_LINE = ("  ONE IMAGE OF THE SHARED STRUCTURE (this overrules the editor's draft and the register's medium and palette): "
            "the shared structure WHOLE — a dense network of many elements, never one element of it — reading as both "
            "things compared, in the imaging technique and the real colours of their reference images (name them); "
            "never two pictures.")

# --- the look of each picture (B-roll « ambiance », 2-oct-2026, "mixed" layout) ------------------------------
# No house look, no style family: every picture comes with its look sheet, made by code from its mood
# (visual_mood.words: medium, composition, lens, light and exposure, palette, texture, mood). The director says it in
# the scene's own things; the colour of the feeling is the grade's, added when the picture is cut in.
LOOK_RULE_MOOD = """EACH PICTURE'S LOOK comes with it below ("look": read from what is said — its medium, composition, lens, light
and exposure, palette, texture and mood). Write every part of it in the scene's own things — its light sources,
surfaces and shadows — never in technical terms. Colours: the scene's true colours only, no overall tint
and no grade words (teal, orange, warm or cinematic grade): the colour of the mood is set afterwards."""
LOOK_RULE_HISTORICAL = ("THE CHANNEL'S LOOK (every picture): cinematic documentary photograph; each picture's style "
                        "note below says the rest.")
MEDIUM_RULE_MOOD = ("The medium is the look's: a photograph for what a camera sees, the instrument's own image for "
                    "what only an instrument sees, a physical model for an abstraction, the experience as it is told "
                    "for an inner one — never a glowing illustration or a symbol. A picture with a REGISTER is painted "
                    "in its register.")
MEDIUM_RULE_HISTORICAL = ("Photographic, real-world vocabulary: a documentary still, unless a picture's style note says "
                          "otherwise or it has a REGISTER (then the register wins).")


def _art_frame(m, mixed, rise):
    """How the picture is framed on screen, for the art director."""
    if mixed:
        return "HERO (full screen, 9:16, about 3 s)" if m.get("hero") else "CARD (small wide frame 16:10 above the head)"
    return "CARD (small square frame under the captions)" if rise else "FULL FRAME (9:16, full screen, about 1.5 s)"


def _art_glossary(moments, clip_text):
    """The glossary lines the set needs: the notions the clip says, and the ones the editor named."""
    import ai_brain
    brief = ai_brain.EPISODE_BRIEF
    if not brief:
        return ""
    matched, rest = ai_brain.glossary_split(brief, clip_text)
    named = {str(m.get("notion") or "").lower() for m in moments if m.get("notion")}
    picked = list(matched[:12]) + [g for g in rest if str(g.get("term") or "").lower() in named]
    if not picked:
        return ""
    return ("VISUAL GLOSSARY (the channel always draws these notions this way):\n"
            + "\n".join(f"- {g['term']}: {g.get('visual') or g.get('meaning') or ''}" for g in picked) + "\n")


def _art_prompt(moments, clip, mixed=True, rise=False, auto_style=True, style="photo", clip_text="", faces="never"):
    """The art director's request for the whole set of one clip. Mixed layout: every photo picture brings its look
    sheet (visual_mood.art_line, from its mood); historical layouts: the STYLES are the notes."""
    sheet = next((m.get("sheet") for m in moments if m.get("sheet")), None)
    sheet_txt = "; ".join(f"{k}: {v}" for k, v in (sheet or {}).items()) or "none"
    thesis = next((m.get("thesis") for m in moments if m.get("thesis")), "") or "-"
    lines = []
    for k, m in enumerate(moments):
        m_style = (m.get("style") or "photo") if auto_style else style
        shot = m.get("notion_shot") or m.get("shot") or "-"
        if m.get("notion_shot") and m.get("notion_shot") != m.get("shot"):
            shot += " (the channel keeps another shot of this notion already: take this one)"
        parts = [f"#{k} {_art_frame(m, mixed, rise)}", f"shot: {shot}", f"role: {m.get('role') or '-'}",
                 f"subject: {m.get('subject') or m.get('query') or '-'}"]
        if m.get("notion"):
            parts.append(f"notion: {m['notion']}")
        lines.append("- " + " · ".join(parts))
        if mixed and m.get("hero"):
            lines.append("  THE HERO, the clip's poster" + (f" — why this one: {m['hero_why']}" if m.get("hero_why") else ""))
        if m.get("said"):
            lines.append(f"  said: \"{m['said']}\"")
        if m.get("idea"):
            lines.append(f"  idea: {m['idea']}")
        lines.append(f"  the editor's draft: {m.get('prompt') or '-'}"
                     + (f" (people: {m['people']})" if m.get("people") else ""))
        if m.get("tried_line"):
            lines.append(m["tried_line"])
        if m.get("parallel") == "pair":
            lines.append(PAIR_LINE)
        elif m.get("parallel") == "one":
            lines.append(ONE_LINE)
        drawn = bool(m.get("inside_body"))
        reg = register_of(m_style) if not drawn else None      # a drawing overrules a register
        if reg:
            lines.append(f"  REGISTER \"{reg['name']}\" (not a photograph) — its style; the scene is this sentence's: {reg['look']}"
                         + (f" Cheap version to stay away from: {reg['cheap']}" if reg.get("cheap") else ""))
            if visual_mood._restrained(m.get("mood")):
                lines.append(RESTRAINT_LINE)
        elif mixed:
            mood = m.get("mood") or visual_mood.clean(None)
            lines.append(f"  look ({visual_mood.describe(mood)}): {visual_mood.art_line(mood, drawn=drawn)}")
            if m.get("show"):
                lines.append(f"  show: {m['show']}" + (f" — point: {m['point']}" if m.get("point") else "")
                             + (" (what the sentence means, as a real event or process)" if m["show"] == "meaning" else ""))
            if mood.get("absence"):
                lines.append(ABSENCE_LINE)
            if mood.get("sober"):
                lines.append("  SOBER, REAL SUFFERING (this overrules the editor's draft): show only the person or the place "
                             "as a camera sees them; nothing he sees, hears or feels inside appears in the frame — no "
                             "figures, faces, mouths, shapes or light around him.")
        else:
            lines.append(f"  style note: {STYLES.get(m_style, STYLES['photo'])}")
        if drawn:
            lines.append(BODY_LINE.format(drawing=episode_drawing()))
    any_register = any(register_of((m.get("style") or "photo") if auto_style else style) for m in moments)
    extra = [EMPTY_RULE, PRECISION_RULE, SAFETY_RULE, BODY_RULE, PARALLEL_RULE, KNOWN_PICTURE_RULE]
    return ART_PROMPT.format(extra_rules="\n- ".join(r.replace("\n", "\n  ") for r in extra) if mixed else
                             "Everything in the frame is something the image model can draw right.",
                             look_rule=LOOK_RULE_MOOD if mixed else LOOK_RULE_HISTORICAL,
                             medium_rule=MEDIUM_RULE_MOOD if mixed else MEDIUM_RULE_HISTORICAL,
                             sheet=sheet_txt, cliche=CLICHE_RULE,
                             registers=(REGISTER_TEXT + "\n") if any_register else "", bible=_bible_block(),
                             title=clip.get("video_title_for_youtube_short") or "-", thesis=thesis,
                             glossary=_art_glossary(moments, clip_text), moments="\n".join(lines),
                             faces=FACE_TEXT.get(faces, FACE_TEXT["never"]))


def _cut_at_sentence(text, limit):
    """``text`` within ``limit`` characters: cut after its last full sentence when one ends past the half,
    else at the limit."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    end = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    return head[:end + 1].rstrip() if end >= limit // 2 else head


_NUM_RE = re.compile(r"\d[\d,.]*\d|\d")
_FACT_STOP = {"the", "and", "setting", "composition", "light", "lens", "palette", "material", "mood", "shot",
              "subject", "draw", "show", "close", "wide", "medium", "macro", "hero", "card", "step", "steps"}


def facts_of(text):
    """The facts of an image draft that must survive any rewrite: its numbers (separators dropped) and its
    proper nouns (a capitalised word that does not open a sentence, or an acronym), lower-cased."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    # An age or a decade of life ("in his 40s") is not a fact the picture must keep; a year or an era ("1980s") is.
    text = re.sub(r"\b(?:his|her|their|my|your|our)\s+\d{2}s\b", "", text)
    facts = {re.sub(r"[,.]", "", n) for n in _NUM_RE.findall(text)}
    for sentence in re.split(r"(?<=[.!?:;])\s+", text):
        for w in sentence.split(" ")[1:]:
            w = w.strip("()\"',.;:!?")
            if len(w) < 3 or w.lower() in _FACT_STOP:
                continue
            # A proper noun, or an acronym of three letters or more ("OR" the operating room and "IV" are words)
            if (w[0].isupper() and w[1:].islower()) or (w.isupper() and w.isalpha()):
                facts.add(w.lower())
    return {f for f in facts if f}


_NOTION_SENTENCE_RE = re.compile(r"\s*Draw .{1,80}? the channel's usual way: .*$", re.S)


def _speaker_words():
    """The words of the episode's speakers' names (the brief's "speakers"): never a fact a picture keeps — the video
    shows them, and nobody real is drawn."""
    import ai_brain
    out = set()
    for s in (ai_brain.EPISODE_BRIEF or {}).get("speakers") or []:
        out |= {w.lower() for w in re.findall(r"[A-Za-z']+", str((s or {}).get("name") or "")) if len(w) > 2}
    return out


def lost_facts(draft, prompt, spoken=None):
    """The facts of ``draft`` (facts_of) missing from ``prompt``: [] when every one is there (a crude plural
    is forgiven both ways). The glossary sentence apply_notions glues to a draft ("Draw X the channel's usual
    way: ...") names the notion, not a fact of the picture: it is not read. v16b: the speakers' names are never
    facts, and with ``spoken`` (the clip's words) a word counts only when the speaker said it (a number always) —
    the director may drop the editor's "MMA" or "LCD", never what was said."""
    draft = _NOTION_SENTENCE_RE.sub("", str(draft or ""))
    have = {t.rstrip("s") for t in re.findall(r"[a-z0-9']+", re.sub(r"(?<=\d)[,.](?=\d)", "", str(prompt or "").lower()))}
    facts = facts_of(draft) - _speaker_words()
    if spoken is not None:
        said = {t.rstrip("s") for t in re.findall(r"[a-z0-9']+", re.sub(r"(?<=\d)[,.](?=\d)", "", str(spoken).lower()))}
        facts = {f for f in facts if f.isdigit() or f.rstrip("s") in said}
    return sorted(f for f in facts if f.rstrip("s") not in have)


def _apply_art(moments, data, clip_text=None):
    """The art director's prompts onto the moments, by index: ``prompt`` becomes the director's (the editor's
    draft kept in ``prompt_editor``, ``art`` set), when it reads like a prompt AND keeps the editor's facts
    (lost_facts: a number, a place, a name the draft had — the one specific thing of the picture is not the
    director's to drop). Returns how many were taken."""
    taken = 0
    for p in (data or {}).get("prompts") or []:
        try:
            k = int(p.get("k"))
        except (TypeError, ValueError, AttributeError):
            continue
        text = re.sub(r"\s+", " ", str(p.get("prompt") or "")).strip()
        if not 0 <= k < len(moments) or not ART_MIN_WORDS <= len(text.split()) <= ART_MAX_WORDS:
            continue
        m = moments[k]
        lost = lost_facts(m.get("prompt_editor") or m.get("prompt"), text, clip_text)
        if lost:
            filter_hit("art: facts lost")
            print(f"   ⚠️ Art direction #{k}: the director dropped {', '.join(lost)} — the editor's draft is kept "
                  f"for this picture.")
            continue
        if not m.get("art"):
            m["prompt_editor"] = m.get("prompt") or ""
        m["prompt"] = _cut_at_sentence(text, PROMPT_MAX)
        m["art"] = True
        judge = re.sub(r"\s+", " ", str(p.get("judge") or "")).strip()[:300]
        if judge:
            m["judge"] = judge
        m["fx"] = p.get("fx") if p.get("fx") in FX_KINDS else None
        if p.get("people") in PEOPLE:
            m["people"] = p["people"]                  # who is in the director's frame (v16): the guard reads it
        if isinstance(p.get("inside_body"), bool):
            m["inside_body"] = m.get("inside_body") or p["inside_body"]   # drawn, never photographed (v17)
        # The hero's second take (v16): the same moment in other words — Turbo paints one prompt alike whatever the seed.
        alt = re.sub(r"\s+", " ", str(p.get("alt_prompt") or "")).strip()
        if m.get("hero") and ART_MIN_WORDS <= len(alt.split()) <= ART_MAX_WORDS \
                and not lost_facts(m.get("prompt_editor") or "", alt, clip_text):
            m["prompt_alt"] = _cut_at_sentence(alt, PROMPT_MAX)
        taken += 1
    return taken


def direct_art(moments, clip, mixed=True, rise=False, auto_style=True, style="photo", clip_text="", faces="never"):
    """The second call of the brain: one prompt per picture of the set, each in its own look sheet (mixed layout).
    Runs on the brain's ``broll_art`` step (a Claude model, or Gemini). Any failure leaves the editor's prompts in
    place."""
    import ai_brain
    if not moments:
        return 0
    prompt = _art_prompt(moments, clip, mixed, rise, auto_style, style, clip_text, faces)
    try:
        if ai_brain.route("broll_art") == "gemini":
            ai_brain.say(f"Gemini · {TEXT_MODEL}", "B-roll: art direction of the set")
            data, _r = ai_brain.gemini_json([prompt], model=TEXT_MODEL)
        else:
            data = _art_call(prompt, "B-roll: art direction of the set")
    except Exception as e:
        print(f"   ⚠️ B-roll art direction failed ({str(e)[:160]}) — the editor's prompts are used.")
        return 0
    taken = _apply_art(moments, data, clip_text or None)
    words = [len(m["prompt"].split()) for m in moments if m.get("art")]
    print(f"   🎨 Art direction: {taken}/{len(moments)} prompt(s) written"
          + (f", {sum(words) // len(words)} words on average" if words else "")
          + (" — the others keep the editor's draft" if taken < len(moments) else ""))
    return taken


ANOTHER_IDEA_TEXT = """ANOTHER IDEA. The pictures below were made and judged, and they failed — twice, or as not safe (each one's
attempts, what the reviewer saw in them and why they failed are given). The image model paints nearly the same
picture again from the same scene whatever the seed: for each one write ANOTHER picture for the SAME words — another
subject, setting, viewpoint or scale that carries what is said — never the same scene reworded, never what failed.

"""


def another_idea(cands, clip, clip_text="", mixed=True, auto_style=True, style="photo", faces="never"):
    """v16: the art director (not the review) writes another idea for the pictures that failed twice or are not safe —
    one call for all of them, with every attempt and what the review saw. Sets c["new"] ({prompt, judge, fx, people})
    and c["new_prompt"] on each one answered; returns how many."""
    import ai_brain
    if not cands:
        return 0
    moments = []
    for c in cands:
        m = {k: v for k, v in c["m"].items() if k not in ("prompt_alt",)}
        tries = "; ".join(f'«{h["prompt"][:220]}» — seen: {h["seen"][:160]} — failed: {h["problem"][:160] or "-"}'
                          for h in (c.get("history") or [])[-3:])
        m["prompt"] = (c.get("history") or [{}])[0].get("prompt") or m.get("prompt") or ""
        m["tried_line"] = f"  TRIED AND FAILED: {tries}" if tries else ""
        moments.append(m)
    prompt = ANOTHER_IDEA_TEXT + _art_prompt(moments, clip, mixed, False, auto_style, style, clip_text, faces)
    try:
        data = _art_call(prompt, "B-roll: another idea for the pictures that failed")
    except Exception as e:
        print(f"   ⚠️ Another idea failed ({str(e)[:160]}) — those pictures stop here.")
        return 0
    got = 0
    for p in (data or {}).get("prompts") or []:
        try:
            k = int(p.get("k"))
        except (TypeError, ValueError, AttributeError):
            continue
        text = positive(re.sub(r"\s+", " ", str(p.get("prompt") or "")).strip())
        if not 0 <= k < len(cands) or not ART_MIN_WORDS <= len(text.split()) <= ART_MAX_WORDS:
            continue
        c = cands[k]
        c["new"] = {"prompt": _cut_at_sentence(text, PROMPT_MAX),
                    "judge": re.sub(r"\s+", " ", str(p.get("judge") or "")).strip()[:300],
                    "fx": p.get("fx") if p.get("fx") in FX_KINDS else None,
                    "people": p.get("people") if p.get("people") in PEOPLE else None,
                    "inside_body": p.get("inside_body") is True}
        c["new_prompt"] = c["new"]["prompt"]
        got += 1
    print(f"   💡 Another idea: {got}/{len(cands)} written by the art director.")
    return got


HERO_REVIEW_PX = 768   # a full-screen picture is judged bigger than a card (512): lettering, hands, faces show


def _review_facts(cands):
    """What the episode established, for the judge: the bible's world and its AVOID list, and the glossary line of
    every notion among the pictures ("" without any). The review has no transcript: without this it judged a real
    event of the episode (a cage on the White House lawn) with its general knowledge and marked the right picture
    wrong."""
    import ai_brain
    bible = ai_brain.EPISODE_BIBLE or {}
    lines = []
    if bible.get("world"):
        lines.append("- WORLD of the episode (real things said in it): " + "; ".join(bible["world"]))
    if bible.get("avoid"):
        lines.append("- WRONG FACTS the episode rules out: " + "; ".join(bible["avoid"]))
    named = {str(c.get("m", {}).get("notion") or "").lower() for c in cands}
    for g in (ai_brain.EPISODE_BRIEF or {}).get("glossary") or []:
        if str(g.get("term") or "").lower() in named:
            lines.append(f"- {g['term']}: {g.get('meaning') or ''} -> drawn as: {g.get('visual') or ''}")
    if not lines:
        return ""
    return ("\nEPISODE FACTS (from a read of the whole episode). They are TRUE for this review, whatever your general "
            "knowledge says: an event the episode tells happened; a place, a number, an era it gives are right.\n"
            + "\n".join(lines))


def review_with_claude(cands, words, model=None, size=512):
    """Claude looks at each made image and scores it against the idea it must
    carry (1-5) and for its look (1-5), with a better prompt when it falls
    short. ``size``: the pixels the pictures are judged at."""
    thesis = next((c["m"].get("thesis") for c in cands if c["m"].get("thesis")), "")
    files = [c["file"] for c in cands]
    lines = _review_lines(cands, words)
    prompt = REVIEW_PROMPT.format(frame=_review_frame(cands), items="\n".join(lines))
    if thesis:
        prompt += f"\nTHE CLIP'S POINT: {thesis} (context: say in \"problem\" when a picture works against it)."
    prompt += _review_facts(cands)
    prompt += _hero_test(cands)
    # Judged at 512 px (same names): the card is ~300 px wide on screen, and a
    # 1024 px image costs Claude ~4x the tokens for nothing it could not see.
    small_dir = tempfile.mkdtemp(prefix="review_")
    try:
        small = []
        for c in cands:
            p = os.path.join(small_dir, os.path.basename(c["file"]))
            _review_still(c, size).save(p, quality=88)
            small.append(p)
        data = claude_json(prompt, REVIEW_SCHEMA, timeout=240, attach=small, stage="B-roll: checking each image",
                           model=model)
    finally:
        shutil.rmtree(small_dir, ignore_errors=True)
    by_file = {r.get("file"): r for r in (data or {}).get("reviews") or []}
    return [by_file.get(os.path.basename(f), {"score": 3}) for f in files]


HERO_TEST = """
THE HERO TEST (the image marked FULL SCREEN): a cold viewer sees it full screen for one second while hearing
the words — do they get the point of the clip? Is it a frame a documentary would open with (a real place, a real
scale, depth, the light of the scene)? Judge it harder than the cards: look 5 only for a frame you would print. When
several takes of the same moment are given, score each apart and say in "problem" which take is the better and why."""


def _hero_test(cands):
    """The hero's own test, when a hero is among the pictures judged."""
    return HERO_TEST if any(c.get("layout") == "hero" or c.get("m", {}).get("hero") for c in cands) else ""


def _review_frame(cands):
    """The opening of the review: the mixed layout's cards and hero, or the historical small card."""
    mixed = any(c.get("layout") in ("hero", "card") for c in cands)
    return REVIEW_FRAME["mixed" if mixed else "small"].format(dur=RISE_DUR)


def _review_lines(cands, words):
    lines = []
    for c in cands:
        near = " ".join(w["text"] for w in words if c["m"]["t"] - 4 <= w["start"] <= c["m"]["t"] + 4)
        tags = ([f"role: {c['m']['role']}"] if c["m"].get("role") else []) + \
               (["shown FULL SCREEN for ~3 s: judge it at that size"] if c["m"].get("hero") else []) + \
               ([f"take {c['take']} of the same moment: compare the takes, score each apart"] if c.get("take") else [])
        reg = register_of(c["m"].get("style"))
        fx = c["m"].get("fx")
        lines.append(f'- file "{os.path.basename(c["file"])}": idea "{c["m"].get("idea") or c["m"]["prompt"]}"'
                     f'{" (" + "; ".join(tags) + ")" if tags else ""}; '
                     f'said: "{c["m"].get("said") or "..." + near + "..."}"'
                     + (f'; judge it on: "{c["m"]["judge"]}"' if c["m"].get("judge") else "")
                     + (f'; REGISTER "{reg["name"]}" (not a photograph; its cheap version: {reg.get("cheap") or "-"})' if reg else "")
                     + ("; INNER (what the person perceives)" if is_inner(c["m"]) else "")
                     + ("; PAIR (the two compared, side by side)" if c["m"].get("parallel") == "pair" else "")
                     + ("; fx double: shown here WITH its effect, as the viewer sees it" if fx == "double" else
                        "; fx tremble: this picture shakes finely on screen" if fx == "tremble" else "")
                     + (f'; prompt (ART-DIRECTED): "{c["m"]["prompt"]}"' if c["m"].get("art") else ""))
    return lines


FX_REVIEW_T = 0.55     # s: the "double" copy at its widest (sin peak of _fx_double), for the review's still


def _review_still(c, size):
    """The picture as the review sees it (v16): ``size`` px at most, with its "double" when it has one — the review
    judged the sharp still, the viewer saw the doubled one."""
    im = Image.open(c["file"]).convert("RGB")
    if c.get("m", {}).get("fx") == "double":
        import numpy as np
        arr = _fx_double(np.asarray(im, dtype=np.float32), FX_REVIEW_T)
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    im.thumbnail((size, size))
    return im


def review_with_gemini(cands, words):
    """The same check as review_with_claude, by Gemini (cheap vision): each
    image goes in labelled with its file name, at 512 px."""
    import ai_brain
    from google.genai import types
    thesis = next((c["m"].get("thesis") for c in cands if c["m"].get("thesis")), "")
    prompt = REVIEW_PROMPT.format(frame=_review_frame(cands), items="\n".join(_review_lines(cands, words)))
    if thesis:
        prompt += f"\nTHE CLIP'S POINT: {thesis} (context: say in \"problem\" when a picture works against it)."
    prompt += _review_facts(cands)
    prompt += _hero_test(cands)
    prompt += ('\nReturn only: {"reviews": [{"file": "...", "seen": "...", "score": 1-5, "facts_ok": true, "safe": true, '
               '"look": 1-5, "problem": "...", "better_prompt": "..."}]}')
    parts = []
    for c in cands:
        im = _review_still(c, 512)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        parts += [f'file "{os.path.basename(c["file"])}":',
                  types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")]
    ai_brain.say(f"Gemini · {TEXT_MODEL}", "B-roll: checking each image")
    data, _r = ai_brain.gemini_json(parts + [prompt], model=TEXT_MODEL)
    by_file = {r.get("file"): r for r in (data or {}).get("reviews") or []}
    if not by_file:
        raise RuntimeError("no review in Gemini's answer")
    return [by_file.get(os.path.basename(c["file"]), {"score": 3}) for c in cands]


# v17 — THE COLD VIEWER: the review knows what each picture was meant to show (its idea, its prompt, its judge line,
# the episode's facts) and passed pictures that read only with that knowledge (the UT Austin tower for "if I had a
# tumor", a courtroom for "high on meth", a golden smear for "the psychedelic stuff"). A second judge gets ONLY the
# picture and the words said, like a viewer scrolling past; a picture it does not link is not kept.
COLD_PROMPT = """You are a viewer scrolling short videos. You know NOTHING about this video: not its subject, not its story,
not who speaks. For each image below you hear the quoted words while it is on screen.
For each one: "sees" — one plain sentence of what is in the picture; "links" — true only if, hearing those words,
you link the picture to them at once, without any explanation, label or knowledge of a story behind it (the picture
shows what the words talk about: the thing, the scene, the experience, or what they say happens); false when the link
needs the story, a caption or a clever reading, or when the picture shows something else. An abstract pattern, a
texture, streaks, a material or an object standing for a feeling or a chemistry does NOT link — only a vision links,
when the words speak of what is seen. "why" — a few words. "repeats" — the file of an EARLIER picture in this list
that shows the same thing in the same way (the viewer would see the same picture twice), else "". "body_photo" —
true when the picture is a PHOTOGRAPH (not a drawing) of the inside of a body (an organ, a brain, tissue, blood) or
of an operation on someone, even seen from afar.
The images, in the order they appear:
{items}
Return JSON: {{"reads": [{{"file": "...", "sees": "...", "links": true, "why": "...", "repeats": "", "body_photo": false}}]}}"""
COLD_SCHEMA = {"type": "object", "properties": {"reads": {"type": "array", "items": {
    "type": "object", "properties": {"file": {"type": "string"}, "sees": {"type": "string"}, "links": {"type": "boolean"},
                                     "why": {"type": "string"}, "repeats": {"type": "string"},
                                     "body_photo": {"type": "boolean"}},
    "required": ["file", "sees", "links", "body_photo"]}}}, "required": ["reads"]}
COLD_ABSENCE = (" (the video tells of someone who died: an empty place or the things he left link when they are what "
                "the words name)")


def cold_read(cands, words, model=None, size=512):
    """The cold viewer's verdict on each picture: {"sees", "links", "why"} by file name ({} when the call fails)."""
    items = []
    for c in cands:
        m = c.get("m") or {}
        said = m.get("said") or (" ".join(w["text"] for w in words if m["t"] - 3 <= w["start"] <= m["t"] + 4)
                                 if m.get("t") is not None else "")
        items.append(f'- file "{os.path.basename(c["file"])}"'
                     + (" (shown FULL SCREEN)" if c.get("layout") == "hero" else "") + f': heard "{said}"'
                     + (COLD_ABSENCE if (m.get("mood") or {}).get("absence") else ""))
    small_dir = tempfile.mkdtemp(prefix="cold_")
    try:
        small = []
        for c in cands:
            p = os.path.join(small_dir, os.path.basename(c["file"]))
            _review_still(c, size).save(p, quality=88)
            small.append(p)
        data = claude_json(COLD_PROMPT.format(items="\n".join(items)), COLD_SCHEMA, timeout=240, attach=small,
                           stage="B-roll: a cold viewer looks at each image", model=model)
    except Exception as e:
        print(f"   ⚠️ Cold read failed ({str(e)[:120]}) — the review's verdicts stand.")
        return {}
    finally:
        shutil.rmtree(small_dir, ignore_errors=True)
    return {r.get("file"): r for r in (data or {}).get("reads") or [] if isinstance(r, dict)}


def _with_cold_read(cands, words, reviews):
    """The review's verdicts with the cold viewer's: a picture it does not link gets sense 2 at most (counted), its
    reason in "problem" (the art director reads it to write another idea)."""
    import ai_brain
    if os.environ.get("BROLL_COLD_READ", "1") == "0" or not claude_ready():
        return reviews
    # One look at every picture in the order they are seen (a repeat shows), by the B-roll's judge: Haiku let pictures
    # pass that meant nothing (streaks for "high on meth", pellets for a "dump of dopamine"), v17 bench.
    model = ai_brain.stage_model("broll")
    reads = cold_read(cands, words, model=None if model == "gemini" else model, size=COLD_PX)
    names = [os.path.basename(c["file"]) for c in cands]
    for k, c in enumerate(cands):
        r = dict(reviews[k] or {})
        read = reads.get(names[k])
        if read is None:
            continue
        rep = str(read.get("repeats") or "").strip()
        j = names.index(rep) if rep in names[:k] else None
        if j is not None and cands[j].get("k") == c.get("k"):
            j = None                                   # two takes of one moment are meant to look alike
        r["cold"] = {"sees": str(read.get("sees") or "")[:300], "links": read.get("links") is not False,
                     "why": str(read.get("why") or "")[:200], **({"repeats": rep} if j is not None else {}),
                     **({"body_photo": True} if read.get("body_photo") is True else {})}
        if read.get("body_photo") is True and not (c.get("m") or {}).get("inside_body"):
            # v17: the inside of a body, or an operation, is drawn — a photograph of it is not shown (another idea,
            # drawn: _take_review marks the moment)
            r["safe"] = False
            r["problem"] = ("a photograph of the inside of a body or of an operation — draw it in the episode's "
                            "drawing; " + str(r.get("problem") or ""))[:300]
            filter_hit("cold read: a photo of a body's inside")
        if read.get("links") is False:
            r["score"] = min(int(r.get("score") or 3), 2)
            r["problem"] = (f'a cold viewer does not link it ({r["cold"]["why"] or r["cold"]["sees"]}); '
                            + str(r.get("problem") or ""))[:300]
            filter_hit("cold read: no link")
        elif j is not None:
            r["score"] = min(int(r.get("score") or 3), 2)
            r["problem"] = (f"the same picture as {rep} for the viewer; " + str(r.get("problem") or ""))[:300]
            filter_hit("cold read: a repeat")
        reviews[k] = r
    return reviews


COLD_PX = 640    # the cold viewer's pictures: one size for the hero and the cards, seen in one row


def review_images(cands, words):
    """The review (``_review_images``), then the cold viewer (v17, ``_with_cold_read``)."""
    if not cands:
        return []
    return _with_cold_read(cands, words, _review_images(cands, words))


def _review_images(cands, words):
    """The image check, on the profile's choice (ai_brain "image_review").
    Gemini: it checks every image and only the doubtful ones (score 3 —
    neither clearly good nor clearly wrong) go to Claude, the B-roll's judge,
    for the final say. A Claude model: it checks them all itself. A hero
    (full screen) is always judged by the B-roll's judge, at HERO_REVIEW_PX."""
    import ai_brain
    if not cands:
        return []
    heroes = [k for k, c in enumerate(cands) if c.get("layout") == "hero"]
    if heroes and len(heroes) < len(cands) and claude_ready():
        out = [None] * len(cands)
        for k, r in zip(heroes, review_with_claude([cands[k] for k in heroes], words,
                                                   model=ai_brain.stage_model("broll"), size=HERO_REVIEW_PX)):
            out[k] = r
        rest = [k for k in range(len(cands)) if k not in heroes]
        for k, r in zip(rest, _review_images([cands[k] for k in rest], words)):
            out[k] = r
        return out
    if heroes and claude_ready():
        return review_with_claude(cands, words, model=ai_brain.stage_model("broll"), size=HERO_REVIEW_PX)
    if ai_brain.route("image_review") == "gemini":
        try:
            reviews = review_with_gemini(cands, words)
            doubtful = [k for k, r in enumerate(reviews) if int(r.get("score") or 3) == 3]
            by_claude = 0
            if doubtful and claude_ready():
                try:
                    for k, r in zip(doubtful, review_with_claude([cands[k] for k in doubtful], words,
                                                                 model=ai_brain.stage_model("broll"))):
                        reviews[k] = r
                    by_claude = len(doubtful)
                except Exception as e:
                    print(f"   ⚠️ Claude second look failed ({str(e)[:120]}) — Gemini's scores kept.")
            print(f"   🔎 Image check: {len(cands)} by Gemini, {by_claude} doubtful one(s) re-checked by Claude.")
            return reviews
        except Exception as e:
            print(f"   ⚠️ B-roll review via Gemini failed ({str(e)[:160]}) — Claude checks them.")
    first, judge = ai_brain.stage_model("image_review"), ai_brain.stage_model("broll")
    reviews = review_with_claude(cands, words, model=first)
    if first != judge:
        # The weakest model never has the last word: a card it finds doubtful or weak goes to the B-roll's judge.
        doubtful = [k for k, r in enumerate(reviews)
                    if int(r.get("score") or 3) <= 3 or (isinstance(r.get("look"), int) and r.get("look") <= 3)]
        if doubtful:
            try:
                for k, r in zip(doubtful, review_with_claude([cands[k] for k in doubtful], words, model=judge)):
                    reviews[k] = r
                print(f"   🔎 Image check: {len(cands)} by {first}, {len(doubtful)} doubtful one(s) re-checked by {judge}.")
            except Exception as e:
                print(f"   ⚠️ {judge}'s second look failed ({str(e)[:120]}) — {first}'s scores kept.")
    return reviews


def plan_locally(clip, words, n, avoid):
    """No key / no answer: the clip's topic words and strongest nouns."""
    import viral_fx
    topic = viral_fx.topic_words(clip.get("video_title_for_youtube_short"), clip.get("viral_hook_text"))
    duration = words[-1]["end"]
    moments = []
    for w in words:
        score = viral_fx.keyword_score(w["text"], topic)
        t = max(0.0, w["start"] - 0.08)
        if score >= 1.0 and _allowed(t, duration, avoid):
            word = re.sub(r"[^\w' -]", "", w["text"]).strip()
            moments.append({"t": t, "anchor": word, "query": word.lower(),
                            "prompt": f"{word.lower()}, shown clearly as the main subject", "score": score})
    return _space(moments, n)


# --- images -----------------------------------------------------------------------


# --- local GPU (ComfyUI) --------------------------------------------------------

def _comfy_url():
    return (os.environ.get("COMFYUI_URL") or "http://host.docker.internal:8188").rstrip("/")


def comfy_available(timeout=3):
    import httpx
    try:
        return httpx.get(f"{_comfy_url()}/system_stats", timeout=timeout).status_code == 200
    except Exception:
        return False


ENGINES = ("zimage",)     # the one image engine; the name is kept in the notion library's file names


# --- guardrails ---------------------------------------------------------------------
# What the fast image models (Z-Image Turbo, FLUX schnell) get wrong: exact counts,
# lettering on screens / signs / pages, hands, faces in a crowd, logos. They run at
# cfg 1.0, where a negative prompt does nothing, so every guardrail is a POSITIVE
# sentence describing what to draw instead, added by the code from what the prompt
# contains. Nothing here costs Claude a token.
_NUM_WORDS = {"two": 2, "three": 3, "four": 4, "2": 2, "3": 3, "4": 4}
_COUNT_RE = re.compile(r"\b(two|three|four|2|3|4)\s+((?:[a-z-]+\s+){0,2}[a-z-]{3,}s)\b", re.I)
_BIG_RE = re.compile(r"\b(\d{2,}|dozens|hundreds|thousands|millions?|hundred|thousand)\b", re.I)
_TEXT_RE = re.compile(r"\b(screens?|monitors?|phones?|smartphones?|laptops?|computers?|tablets?|tv|television|books?|"
                      r"newspapers?|papers?|letters?|signs?|signage|posters?|banners?|labels?|charts?|graphs?|"
                      r"documents?|pages?|tweets?|headlines?|whiteboards?|blackboards?|menus?|tickets?|passports?|"
                      r"license|dashboards?|spreadsheets?|prescriptions?|notes?|notebooks?|chalkboards?|equations?|"
                      r"formulas?)\b", re.I)
# Who is in the frame is never read from the words any more (v16): "first-person", "man-made", "the north face",
# "portrait-format", "the patient's chart" made a word list add a person to a picture with nobody in it. The editor
# and the art director declare it ("people", PEOPLE); an inner picture is "none" whatever they say.
_BRANDS = ("iphone", "ipad", "nike", "adidas", "coca-cola", "coke", "pepsi", "starbucks", "mcdonald", "tesla", "google",
           "facebook", "instagram", "tiktok", "youtube", "twitter", "amazon", "netflix", "walmart", "samsung",
           "microsoft", "android", "apple", "logo", "branded")
_BRAND_RE = re.compile(r"\b(" + "|".join(re.escape(b) for b in _BRANDS) + r")\b", re.I)
_GENERIC = {"iphone": "smartphone", "ipad": "tablet", "coca-cola": "cola bottle", "coke": "cola bottle",
            "pepsi": "cola bottle", "nike": "plain", "adidas": "plain"}
def guardrails(prompt, faces=False, people=None):
    """(prompt, extra): the prompt with brand names swapped for generic ones, and
    the positive sentences to add at its end for the pitfalls this prompt holds.
    ``faces``: a clear face is allowed on this picture (people stay anonymous:
    nobody real or recognisable). ``people``: who is in the frame, as the editor or
    the art director declared it (PEOPLE) — the only source of the hands, crowd and
    person sentences; undeclared (None) or "none": none of them."""
    def generic(m):
        return _GENERIC.get(m.group(1).lower(), m.group(0))
    had_brand = bool(_BRAND_RE.search(prompt))
    prompt = _BRAND_RE.sub(generic, prompt)
    prompt = re.sub(r"\b([Aa])n (smartphone|plain|tablet|cola)\b", r"\1 \2", prompt)   # "An iPhone" -> "A smartphone"
    extra = []
    c = _COUNT_RE.search(prompt)
    if c:
        filter_hit("guard: count")
        extra.append(f"Show exactly {_NUM_WORDS[c.group(1).lower()]} {c.group(2)}, clearly separate from each other "
                     "and easy to count.")
    elif _BIG_RE.search(prompt):
        filter_hit("guard: big number")
        extra.append("Show it as one large group seen as a whole, without trying to depict an exact number.")
    if _TEXT_RE.search(prompt):
        filter_hit("guard: text")
        extra.append("Any screen, sign, page or label shows only plain colour, soft light or abstract shapes.")
    if had_brand:
        filter_hit("guard: brand")
        extra.append("A generic unbranded version with plain surfaces.")
    if people in ("hands", "one"):
        filter_hit("guard: hands")
        extra.append("Hands natural and well formed, each with five fingers, in a simple pose.")
    if people == "group":
        filter_hit("guard: crowd")
        extra.append("The group is seen as a whole, the nearest faces natural and anonymous, nobody recognisable."
                     if faces else "The figures are seen from behind or at a distance, as simple silhouettes.")
    elif people == "one":
        filter_hit("guard: person")
        extra.append("An anonymous person, nobody real or recognisable, the face natural, in focus and lit by the "
                     "scene's light." if faces else
                     "An anonymous person, face turned away, in shadow or small in the frame.")
    # Every guard that fired goes out (a cap of three used to drop the faces guard behind count + text + brand).
    return prompt, " ".join(extra)


# --- the channel's notion pictures ---------------------------------------------------
# The first good picture of a glossary notion ("Dopamine", "Basal ganglia"...) is
# kept and shown again, unchanged, every time a clip's image is simply that notion:
# the channel always draws it the same way, and it costs no GPU time and no review.
# Kept across jobs and episodes in output/_glossary_images (delete a file to have
# that picture made again). BROLL_NOTION_MEMORY=0 switches it off.
NOTION_DIR = os.environ.get("BROLL_NOTION_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "output", "_glossary_images")
# An image is kept when the judge finds it clear AND on point (4-5). A merely acceptable one (3) only
# fills in when fewer than KEEP_FLOOR images would be left: a clip is better with fewer images that mean something.
KEEP_SCORE = int(os.environ.get("BROLL_KEEP_SCORE") or 4)
KEEP_FLOOR = 2
# The second axis (the look, 1-5): a card needs LOOK_CARD, a full-screen hero LOOK_HERO. A review without a look
# (an old answer, Gemini off its schema) judges on the meaning alone.
LOOK_CARD = int(os.environ.get("BROLL_LOOK_CARD") or 3)
LOOK_HERO = int(os.environ.get("BROLL_LOOK_HERO") or 4)
REDO_CARD, REDO_HERO = 1, 2   # pictures made again from the reviewer's better prompt, at most
REDO_NEW_IDEA = 1             # v15b: a card's one more attempt when it is another idea (two failed, or unsafe)


def _look_ok(c):
    look = c.get("look_score")
    return look is None or look >= (LOOK_HERO if c.get("layout") == "hero" else LOOK_CARD)


def _take_review(c, r):
    """The reviewer's answer onto a candidate: score (the sense), facts_ok (True unless the judge said false),
    look_score (None when not given), problem, better_prompt; every attempt and what the review saw in it go to
    ``history`` (shared by a candidate and its redos), which the art director reads to write another idea (v16)."""
    c["score"] = int(r.get("score") or 3)
    c["facts_ok"] = r.get("facts_ok") is not False
    c["safe"] = r.get("safe") is not False
    look = r.get("look")
    c["look_score"] = int(look) if isinstance(look, (int, float)) and not isinstance(look, bool) and 1 <= int(look) <= 5 else None
    c["problem"] = str(r.get("problem") or "")[:300]
    c["better_prompt"] = positive(re.sub(r"\s+", " ", str(r.get("better_prompt") or "")).strip())[:PROMPT_MAX]
    if (r.get("cold") or {}).get("body_photo") and c.get("m") is not None:
        c["m"] = {**c["m"], "inside_body": True}       # its next picture is drawn (v17)
    if r.get("person_seen") is True and is_inner(c.get("m") or {}):
        # v16b: the code applies it — as a sense rule the judges followed one time in two (rejudge, 4 runs)
        c["score"] = min(c["score"], 2)
        filter_hit("review: inner picture shows the person")
    if "history" not in c:
        c["history"] = []
    c["history"].append({"prompt": str((c.get("m") or {}).get("prompt") or "")[:500],
                         "seen": str(r.get("seen") or "")[:300], "problem": c["problem"]})
    return c


# A redo never carries a negation (v15): the image model ignores them, and the word they name comes back in the
# picture ("not behind a window" brought the window back four times on one hero).
_NEGATION_RE = re.compile(r"\b(no|not|never|without|instead of|rather than|nor|none|nothing|nobody|avoid\w*|free of|"
                          r"don't|doesn't|isn't|aren't|won't|can't)\b", re.I)


def positive(text):
    """``text`` without its sentences that carry a negation (counted). "" when nothing positive is left."""
    text = str(text or "").strip()
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?;])\s+", text)
    kept = [s for s in sentences if not _NEGATION_RE.search(s)]
    if len(kept) < len(sentences):
        filter_hit("redo: negation taken out")
    return " ".join(kept).strip()


def _wants_new_idea(c):
    """The picture's next attempt must be another idea: it is not safe, it failed twice, or nothing of the same idea
    is left (no better prompt once its negations are out, or it was tried already)."""
    if not _safe(c) or c.get("failed", 0) >= 2:
        return True
    return not c.get("better_prompt") or c["better_prompt"] in (c.get("tried") or ())


def _next_prompt(c):
    """The prompt of a picture's next attempt: the same idea made to work (the review's better_prompt), or another
    idea (new_prompt — the art director's since v16, another_idea) once this one has failed twice, when the picture
    is not safe, or when nothing of the same idea is left once its negations are out (v15b); never a prompt already
    tried; None when there is nothing to try."""
    tried = c.get("tried") or ()
    if not _safe(c) or c.get("failed", 0) >= 2:
        order = (c.get("new_prompt"),)
    else:
        order = (c.get("better_prompt"), c.get("new_prompt"))
    return next((p for p in order if p and p not in tried), None)


def _redo_budget(c):
    """How many times a picture may be made again: the hero twice (its takes count as attempts); a card once, and once
    more when the next attempt is another idea — without it, a card that failed twice would never get one."""
    if c["layout"] == "hero":
        return REDO_HERO
    return REDO_CARD + (REDO_NEW_IDEA if not _safe(c) or c.get("failed", 0) >= 2 else 0)


def _facts_ok(c):
    return c.get("facts_ok", True) is not False


def _safe(c):
    return c.get("safe", True) is not False


def _needs_redo(c):
    # An unsafe picture is never made again with the same idea: only another idea (v15, _next_prompt).
    return not _safe(c) or c["score"] <= 3 or not _look_ok(c) or not _facts_ok(c)


def _better(c2, c):
    """The redo beats the first picture: true facts first, then a higher sense, then a higher look."""
    return ((_safe(c2), _facts_ok(c2), c2["score"], c2.get("look_score") or 0)
            > (_safe(c), _facts_ok(c), c["score"], c.get("look_score") or 0))


def _keep_meaningful(cands):
    """The candidates worth showing, in their order: every one with true facts, a sense of KEEP_SCORE+ and a look
    that passes (_look_ok), topped up with the best 3s (never below 3, facts true, look passing) up to KEEP_FLOOR."""
    good = [c for c in cands if _safe(c) and _facts_ok(c) and c["score"] >= KEEP_SCORE and _look_ok(c)]
    if len(good) < KEEP_FLOOR:
        spare = sorted((c for c in cands if _safe(c) and _facts_ok(c) and 3 <= c["score"] < KEEP_SCORE and _look_ok(c)),
                       key=lambda c: -c["score"])
        good += spare[:KEEP_FLOOR - len(good)]
    return [c for c in cands if c in good]


NOTION_MIN_SCORE = 5   # kept and shown in EVERY later clip: only a picture the judge rates perfect

# One kept picture per shape: the small square card, the tall full-frame image,
# the full-screen hero (bigger) and (premium cards) the wide 16:10 card.
_SHAPES = {"rise": "sq", "full": "tall", "hero": "hero", "card": "wide"}
_SHAPE_LAYOUT = {v: k for k, v in _SHAPES.items()}


def _shape(layout):
    """Shape key of a layout (True / False mean the historical rise / full)."""
    if layout is True:
        return "sq"
    if layout is False or layout is None:
        return "tall"
    return _SHAPES.get(layout, "tall")


def _layout_of(shape):
    return _SHAPE_LAYOUT.get(shape, "full")


def _gen_size(layout, hero_res="std"):
    """Pixels asked from the image model for a layout family."""
    if layout in ("rise", True):
        return RISE_GEN
    if layout == "hero":
        return HERO_GEN.get(hero_res) or HERO_GEN["std"]
    if layout == "card":
        return CARD_GEN
    if layout == "object":
        return OBJECT_GEN
    if layout == "split":
        return SPLIT_GEN
    if layout == "half":
        return (1024, 1024)       # one half of a pair (v21, broll_v20._make): a square, cropped and composed by code
    return (768, 1344)


# v2 (1-oct-2026): a notion keeps NOTION_VARIANTS pictures per look (different shots), shown in turn; the file
# name carries the look, so a new look makes the library again as the clips need it. The pictures made before carry
# no look ("legacy" in the library screen) and are not reused. Since B-roll « ambiance » (2-oct-2026) the look is
# the mood system's version (visual_mood.VERSION, current_look): the pictures of the teal/amber house look stay in
# the library but are not reused.
NOTION_VARIANTS = int(os.environ.get("BROLL_NOTION_VARIANTS") or 2)
NOTION_SHOTS = ("wide", "close", "macro")   # the shots the variants take, the editor's own first
_USES_LOCK = __import__("threading").Lock()


def look_key(house=""):
    """Six characters naming the look a notion picture was made with ("nolook" for none)."""
    h = re.sub(r"\s+", " ", str(house or "")).strip().lower()
    if not h:
        return "nolook"
    import hashlib
    return hashlib.sha1(h.encode()).hexdigest()[:6]


def current_look():
    """The look key of the pictures the mixed layout makes now."""
    return look_key(visual_mood.VERSION)


def _notion_base(term, style, engine, layout):
    import hashlib
    norm = re.sub(r"\W+", " ", str(term or "").lower()).strip()
    import unicodedata
    ascii_norm = unicodedata.normalize("NFKD", norm).encode("ascii", "ignore").decode()   # plain file / URL names
    slug = re.sub(r"\s+", "-", ascii_norm.strip())[:40] or "notion"
    h = hashlib.sha1(norm.encode()).hexdigest()[:6]
    return os.path.join(NOTION_DIR, f"{slug}-{h}__{style}__{engine}__{_shape(layout)}")


def _notion_path(term, style, engine, layout, look=None, variant=None):
    """The picture's path: ``<base>__<look>_v<variant>.jpg``, or the legacy name (no look) when ``look`` is None."""
    base = _notion_base(term, style, engine, layout)
    return base + ".jpg" if look is None else f"{base}__{look}_v{int(variant or 1)}.jpg"


def notion_variants(term, style, engine, layout, look):
    """The kept pictures of ``term`` for this look: [(variant, path, meta)], by variant."""
    base = os.path.basename(_notion_base(term, style, engine, layout)) + f"__{look}_v"
    out = []
    try:
        names = os.listdir(NOTION_DIR)
    except OSError:
        return out
    for f in names:
        mv = re.match(re.escape(base) + r"(\d+)\.jpg$", f)
        if mv:
            p = os.path.join(NOTION_DIR, f)
            out.append((int(mv.group(1)), p, _notion_meta(p)))
    return sorted(out)


def notion_missing_shot(term, style, engine, layout, look, shot=None):
    """The shot the next kept picture of ``term`` should take (the editor's own first, then the shots not kept
    yet), or None when the library holds NOTION_VARIANTS of them already (or the memory is off)."""
    if os.environ.get("BROLL_NOTION_MEMORY", "1") == "0" or not term:
        return None
    have = notion_variants(term, style, engine, layout, look)
    if len(have) >= NOTION_VARIANTS:
        return None
    if not have:
        return shot if shot in SHOTS else NOTION_SHOTS[0]
    taken = {str(meta.get("shot") or "") for _n, _p, meta in have}
    return next((s for s in NOTION_SHOTS if s not in taken), None) or next((s for s in SHOTS if s not in taken), NOTION_SHOTS[0])


def notion_get(term, style, engine, layout, dest, look="nolook"):
    """Copy the kept picture of ``term`` the channel showed the least (its variants take turns) to ``dest`` and
    return ``dest``; None if none."""
    if os.environ.get("BROLL_NOTION_MEMORY", "1") == "0" or not term:
        return None
    have = notion_variants(term, style, engine, layout, look)
    if not have:
        return None
    _n, src, meta = min(have, key=lambda v: (int(v[2].get("uses") or 0), v[0]))
    shutil.copy2(src, dest)
    with _USES_LOCK:
        try:
            meta["uses"] = int(meta.get("uses") or 0) + 1
            with open(src[:-4] + ".json", "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
    return dest


def notion_put(term, style, engine, layout, src, prompt="", score=None, look="nolook", shot=None, mood=None):
    """Keep ``src`` as the next picture of ``term`` for this look (NOTION_VARIANTS at most: the first good ones
    stay the channel's pictures), with the ``mood`` it was made in (a redo from the library keeps its look).
    Never raises."""
    if os.environ.get("BROLL_NOTION_MEMORY", "1") == "0" or not term:
        return False
    try:
        have = notion_variants(term, style, engine, layout, look)
        if len(have) >= NOTION_VARIANTS:
            return False
        n = (max(v[0] for v in have) + 1) if have else 1
        dest = _notion_path(term, style, engine, layout, look, n)
        os.makedirs(NOTION_DIR, exist_ok=True)
        shutil.copy2(src, dest)
        with open(dest[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump({"term": term, "style": style, "engine": engine, "layout": _layout_of(_shape(layout)),
                       "prompt": prompt, "score": score, "saved": time.strftime("%Y-%m-%d %H:%M"),
                       "look": look, "variant": n, "shot": shot or "", "uses": 0,
                       "mood": visual_mood.compact(mood) if mood else {}}, f, ensure_ascii=False, indent=1)
        return True
    except OSError:
        return False


# The library screen (dashboard "Notion pictures") reads and edits the same memory.
# An entry is identified by its file name without ".jpg"; the picture stays under
# the same key (notion / style / layout) whatever model made it, so the jobs that
# look it up keep finding it; ``made_with`` only says how it was made.
_NOTION_LOCK = __import__("threading").Lock()


def _notion_file(nid):
    """Path of the entry's picture; ValueError for a name that is not one."""
    nid = str(nid or "")
    if not nid or os.path.basename(nid) != nid or nid.startswith(".") or nid.endswith(".prev"):
        raise ValueError("unknown picture")
    path = os.path.join(NOTION_DIR, nid + ".jpg")
    if not os.path.exists(path):
        raise ValueError("unknown picture")
    return path


def _notion_meta(path):
    try:
        with open(path[:-4] + ".json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _notion_entry(path):
    meta = _notion_meta(path)
    stem = os.path.basename(path)[:-4]
    parts = stem.split("__")
    look, variant = "legacy", 1
    if len(parts) >= 5:
        mv = re.match(r"^([0-9a-z]+)_v(\d+)$", parts[4])
        if mv:
            look, variant = mv.group(1), int(mv.group(2))
    shape = parts[3] if len(parts) > 3 else stem.rsplit("__", 1)[-1]
    return {"id": stem, "term": meta.get("term") or parts[0],
            "style": meta.get("style") or (parts[1] if len(parts) > 1 else "photo"),
            "engine": meta.get("engine") or (parts[2] if len(parts) > 2 else "zimage"),
            "layout": meta.get("layout") or _layout_of(shape),
            "look": meta.get("look") or look, "variant": int(meta.get("variant") or variant),
            "shot": meta.get("shot") or "", "uses": int(meta.get("uses") or 0),
            "mood": meta.get("mood") if isinstance(meta.get("mood"), dict) else {},
            "prompt": meta.get("prompt") or "", "score": meta.get("score"), "saved": meta.get("saved") or "",
            "made_with": meta.get("made_with") or meta.get("engine") or "zimage",
            "manual": bool(meta.get("manual")), "has_prev": os.path.exists(path[:-4] + ".prev.jpg"),
            "v": int(os.path.getmtime(path))}


def notion_list():
    """Every kept picture, by notion name."""
    if not os.path.isdir(NOTION_DIR):
        return []
    out = [_notion_entry(os.path.join(NOTION_DIR, f)) for f in os.listdir(NOTION_DIR)
           if f.endswith(".jpg") and not f.endswith(".prev.jpg")]
    return sorted(out, key=lambda e: (e["term"].lower(), e["style"], e["layout"], e["look"], e["variant"]))


def notion_regenerate(nid, prompt, engine=None):
    """Make the notion's picture again from ``prompt`` (edited by the user) on the
    chosen model and keep it as THE picture: the previous one is set aside so it
    can be restored. A long prompt goes out as the art director's; a short one gets
    the look sentence of the mood the picture was made in. No review.
    Raises ValueError / RuntimeError."""
    path = _notion_file(nid)
    entry = _notion_entry(path)
    prompt = re.sub(r"\s+", " ", str(prompt or "")).strip()[:PROMPT_MAX]
    if not prompt:
        raise ValueError("the prompt is empty")
    engine = engine if engine in ENGINES else entry["made_with"] if entry["made_with"] in ENGINES else "zimage"
    if not _NOTION_LOCK.acquire(blocking=False):
        raise RuntimeError("another picture is being made, wait for it")
    tmp = tempfile.mkdtemp(prefix="notion_")
    try:
        if not comfy_available():
            raise RuntimeError(f"ComfyUI not reachable at {_comfy_url()} (start it in Pinokio)")
        new = os.path.join(tmp, "new.jpg")
        art = len(prompt.split()) >= ART_MIN_WORDS
        local_image(prompt, entry["style"], new, engine=engine, size=_gen_size(entry["layout"]), art=art,
                    mood=visual_mood.sentence(entry["mood"]) if entry["mood"] and not art else "")
        base = path[:-4]
        shutil.copy2(path, base + ".prev.jpg")
        if os.path.exists(base + ".json"):
            shutil.copy2(base + ".json", base + ".prev.json")
        shutil.move(new, path)
        meta = _notion_meta(path)
        meta.update(term=entry["term"], style=entry["style"], engine=entry["engine"], layout=entry["layout"],
                    prompt=prompt, score=None, made_with=engine, manual=True, saved=time.strftime("%Y-%m-%d %H:%M"))
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        return _notion_entry(path)
    finally:
        _NOTION_LOCK.release()
        shutil.rmtree(tmp, ignore_errors=True)
        comfy_release()


def notion_restore(nid):
    """Put back the picture that the last regeneration replaced."""
    path = _notion_file(nid)
    base = path[:-4]
    if not os.path.exists(base + ".prev.jpg"):
        raise ValueError("no previous picture")
    shutil.move(base + ".prev.jpg", path)
    if os.path.exists(base + ".prev.json"):
        shutil.move(base + ".prev.json", base + ".json")
    return _notion_entry(path)


def notion_delete(nid):
    """Forget the picture: the next clip that needs the notion makes a new one."""
    path = _notion_file(nid)
    base = path[:-4]
    for ext in (".jpg", ".json", ".prev.jpg", ".prev.json"):
        try:
            os.remove(base + ext)
        except OSError:
            pass


# Z-Image, the base model (released 27-jan-2026): undistilled, real guidance and negative prompt, more varied
# compositions than Turbo (rated "low" in diversity by its makers), 28-50 steps on the model card, 25 in ComfyUI's
# official template. v16: for the pictures that need range (cfg "base_for": the hero, the register pictures); Turbo
# stays for the photo cards.
ZIMAGE_BASE_MODEL = os.environ.get("COMFYUI_ZIMAGE_BASE_MODEL") or "z_image_int8_convrot.safetensors"
ZIMAGE_BASE_STEPS = int(_knob("COMFYUI_ZIMAGE_BASE_STEPS", 25))
ZIMAGE_BASE_CFG = _knob("COMFYUI_ZIMAGE_BASE_CFG", 4.0)
BASE_NEGATIVE = ("blurry, low quality, jpeg artifacts, deformed hands, extra fingers, distorted face, waxy skin, "
                 "watermark, text, letters, logo, signature, frame border, collage")
BASE_FOR = ("hero", "register")


def base_negative(register=None, inner=False, pair=False):
    """The base model's negative prompt: the usual faults, the register's cheap version, a person for an inner picture
    (what is perceived, never the one who perceives), the collage word dropped for a pair."""
    neg = BASE_NEGATIVE.replace(", collage", "") if pair else BASE_NEGATIVE
    parts = [neg]
    if inner:
        parts.append("a person, a face, a figure seen from outside, a selfie")
    if register and register.get("cheap"):
        parts.append(str(register["cheap"]).rstrip("."))
    return ", ".join(parts)


def _graph(engine, text, seed, width=768, height=1344, steps=None, model="turbo", negative=""):
    """ComfyUI API graph for one image (768x1344 = 9:16 by default; the cards
    ask 1152x720, the hero 896x1600); node "7" is the PreviewImage (ComfyUI's
    temp folder, wiped on restart — not its gallery). ``steps``: sampler steps
    (the hero may ask more), else COMFYUI_ZIMAGE_STEPS (8).

    One engine: Z-Image Turbo (int8 model + fp8 Qwen3-4B encoder, 8 steps),
    ~12 s an image on an RTX 3060. The FLUX.1 schnell graph (25 s an image,
    never chosen) was removed on 1-oct-2026; ``engine`` stays in the signature
    because the notion library's file names carry it. Settings checked against
    the official ComfyUI templates (2-oct-2026): Turbo 8 steps, cfg 1 (no
    guidance: its negative is zeroed), res_multistep / simple, shift 3. ComfyUI
    never truncates the text (diffusers cuts at 512 tokens; ours are 157-286).
    ``model`` "base" (v16): Z-Image, the undistilled model — guidance, a real
    negative prompt, more varied compositions, ZIMAGE_BASE_STEPS steps."""
    base = model == "base"
    latent = {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}}
    out = {"6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["v", 0]}},
           "7": {"class_type": "PreviewImage", "inputs": {"images": ["6", 0]}},
           "4": latent}
    out.update({
        "u": {"class_type": "UNETLoader", "inputs": {
            "unet_name": ZIMAGE_BASE_MODEL if base else
            (os.environ.get("COMFYUI_ZIMAGE_MODEL") or "z_image_turbo_int8_convrot.safetensors"),
            "weight_dtype": "default"}},
        "c": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": os.environ.get("COMFYUI_ZIMAGE_TEXT_ENCODER") or "qwen_3_4b_fp8_mixed.safetensors",
            "type": "lumina2", "device": "default"}},
        "v": {"class_type": "VAELoader", "inputs": {"vae_name": os.environ.get("COMFYUI_ZIMAGE_VAE") or "ae.safetensors"}},
        "m": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["u", 0], "shift": 3.0}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["c", 0]}},
        "3": ({"class_type": "CLIPTextEncode", "inputs": {"text": negative or "", "clip": ["c", 0]}} if base else
              {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["2", 0]}}),
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["m", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
            "seed": seed,
            "steps": int(steps or (ZIMAGE_BASE_STEPS if base else (os.environ.get("COMFYUI_ZIMAGE_STEPS") or 8))),
            "cfg": ZIMAGE_BASE_CFG if base else 1.0,
            "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0}},
    })
    return out


def _image_text(prompt, style, look="", art=False, faces=False, register=None, mood="", people=None, body=False,
                drawing=""):
    """The full prompt sent to the image model: the scene (with its guardrails), then what says its look, then the
    rules. ``art``: the scene is the art director's prompt, which already states the look, the frame and the light:
    only the guardrails and the hard rules follow it. ``mood``: the mixed layout's look sentence of the picture
    (visual_mood.sentence) after a prompt that is not the director's; else (historical layouts) the clip's style
    sheet (``look``) and the style's own description. ``people``: who is in the frame (declared, PEOPLE)."""
    prompt, guard = (guardrails(prompt, faces, people) if os.environ.get("BROLL_GUARDRAILS", "1") != "0"
                     else (prompt, ""))
    if body:
        register = None                                            # the drawing overrules a register's medium
        guard = " ".join(p for p in (drawing or episode_drawing(), guard) if p)   # v19: the episode's drawing
    if register:
        # Not a photograph: the register's block carries the look; no look sentence, no style sentence.
        return " ".join(p for p in (prompt, guard, register, ART_RULES) if p)
    if art:
        return " ".join(p for p in (prompt, guard, ART_RULES) if p)
    if mood:
        return " ".join(p for p in (prompt, guard, mood, COMMON_RULES) if p)
    return " ".join(p for p in (prompt, guard, look, STYLES.get(style, STYLES["photo"]), COMMON_RULES) if p)


def local_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", art=False,
                seed=None, steps=None, faces=False, register=None, mood="", people=None, model="turbo", negative="",
                body=False, drawing="", raw=False):
    """One 9:16 image from ComfyUI. Measured on an RTX 3060 (ComfyUI on
    PyTorch cu130 — the int8 kernels need it): Z-Image Turbo ~12 s per
    image, FLUX.1 schnell ~25 s; the first call of a job also loads the
    models from disk (~45 s in all). ``seed``: the one to use (kept in the
    item, so a picture can be made again at another size or step count),
    else a new one; ``steps``: the sampler steps, else the usual. ``model``
    "base" with its ``negative`` prompt: Z-Image (v16, _graph). ``raw``: the prompt goes out as is (v20: the code
    wrote it from the shot spec — no guardrail, no look sentence, no rule appended)."""
    import random
    import uuid
    import httpx
    text = prompt if raw else _image_text(prompt, style, look, art, faces, register, mood, people, body, drawing)
    seed = random.randint(0, 2 ** 48) if seed is None else int(seed)
    graph = _graph(engine if engine in ENGINES else "zimage", text, seed, *size, steps=steps, model=model,
                   negative=negative)
    if model == "base":
        timeout = max(timeout, 900)        # 25 guided steps: several times Turbo's time
    base = _comfy_url()
    with httpx.Client(timeout=30) as http:
        r = http.post(f"{base}/prompt", json={"prompt": graph, "client_id": uuid.uuid4().hex})
        if r.status_code != 200:
            raise RuntimeError(f"ComfyUI refused the job ({r.status_code}): {r.text[:300]}")
        pid = r.json()["prompt_id"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            h = http.get(f"{base}/history/{pid}").json().get(pid)
            if h:
                status = h.get("status") or {}
                if status.get("status_str") == "error":
                    msgs = [m for m in status.get("messages") or [] if m and m[0] == "execution_error"]
                    raise RuntimeError(f"ComfyUI error: {str(msgs[-1][1].get('exception_message') if msgs else status)[:300]}")
                imgs = (h.get("outputs") or {}).get("7", {}).get("images") or []
                if imgs:
                    im = imgs[0]
                    got = http.get(f"{base}/view", params={"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                                          "type": im.get("type", "temp")})
                    got.raise_for_status()
                    Image.open(io.BytesIO(got.content)).convert("RGB").save(out_path, quality=92)
                    return out_path
                if status.get("completed"):
                    raise RuntimeError("ComfyUI finished without an image")
            time.sleep(0.5)
    raise RuntimeError(f"ComfyUI timed out after {timeout}s")


def comfy_release(full=False):
    """Give the GPU back: unload the models from VRAM (``full``: also drop
    them from RAM). Never raises."""
    import httpx
    try:
        httpx.post(f"{_comfy_url()}/free", json={"unload_models": True, "free_memory": bool(full)}, timeout=5)
    except Exception:
        pass


# Clips render in parallel (main.py CLIP_WORKERS, 3 by default) and each one
# used to unload the models when it was done, so the next image of the clips
# still running paid the model load again (~15 s on the 3060, measured). The
# VRAM is now given back by the LAST clip of this process still making images.
_COMFY_USERS = {"n": 0}
_COMFY_USERS_LOCK = __import__("threading").Lock()


def _comfy_enter():
    with _COMFY_USERS_LOCK:
        _COMFY_USERS["n"] += 1


def _comfy_leave():
    """One clip is done with ComfyUI: unload the models only if no other clip is still using them."""
    with _COMFY_USERS_LOCK:
        was = _COMFY_USERS["n"]
        _COMFY_USERS["n"] = max(0, was - 1)
    if was == 1:
        comfy_release()


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


# Exit of a picture: it swells a little, smoothly (no overshoot), in the stretch before it fades — a soft
# push that reads as "this is about to leave" — and keeps growing slightly as it fades. BROLL_EXIT=shrink
# brings back the previous exit (small card shrinking away).
EXIT_SWELL = 0.45   # s of slow swelling before the fade starts


# Profile options: how long a picture stays ("hold": None = until the end of its sentence, else 1-4 s), how
# the small card comes in ("enter": rise from the edge / fade in) and the zoom before it leaves ("zoom").
ZOOM_LEVELS = {"off": 0.0, "soft": 1.0, "strong": 2.0}
# The edge and the shadow around a card / photo (profile broll.border). Each pair is (small card, big card).
# "strong" is the previous look: an almost opaque white edge and a heavy shadow.
BORDERS = {
    "strong": {"edge": 1.0, "rim": (235, 225), "shade": (185, 175), "blur": (0.7, 0.6)},
    "soft": {"edge": 0.6, "rim": (110, 100), "shade": (85, 80), "blur": (1.0, 0.9)},
    "none": {"edge": 0.0, "rim": (0, 0), "shade": (0, 0), "blur": (0.7, 0.6)},
    # The "mixed" layout's cards: a 1 px edge at 12 % (a hint of a rim, not a sticker's white border) and a wider,
    # softer shadow (twice the blur, alpha 60), with more room around the card for it.
    "premium": {"edge": 0.0, "px": 1, "rim": (30, 30), "shade": (60, 60), "blur": (2.0, 2.0), "pad": 4},
}


def _border(name, edge_px, idx):
    """(edge width px, edge alpha, shadow alpha, shadow blur factor) for a border style; idx 0 = small card, 1 = big."""
    b = BORDERS.get(name) or BORDERS["soft"]
    w = b.get("px") or (0 if not b["edge"] else max(2, int(round(edge_px * b["edge"]))))
    return w, b["rim"][idx], b["shade"][idx], b["blur"][idx]
ENTER_MODES = ("rise", "fade")


def _hold(v):
    """A fixed time on screen in seconds (1-4), or None for "until the end of the sentence"."""
    try:
        h = float(v)
    except (TypeError, ValueError):
        return None
    return round(min(4.0, max(1.0, h)), 1) if h > 0 else None


def _zoom_k(zoom):
    return ZOOM_LEVELS.get(zoom, 1.0)


def _exit_mode():
    return "shrink" if os.environ.get("BROLL_EXIT") == "shrink" else "swell"


def _smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _entry_ease(x):
    """How the small card comes in: a bounce (old) or one smooth pop with no overshoot."""
    return _ease_back(x) if _exit_mode() == "shrink" else _ease(x)


def _push_in(f, n, zmax):
    """Zoom of the photo INSIDE its card at frame f of n: a slow continuous push-in (old exit), or none — the
    card then stays still and its only zoom is the swell just before it leaves."""
    return 1.0 + (zmax - 1.0) * f / (n - 1) if _exit_mode() == "shrink" else 1.0


def _rise_out():
    """Seconds the small card takes to leave."""
    return 0.26 if _exit_mode() == "shrink" else 0.32


def _card_out():
    """Seconds the big card takes to fade."""
    return 0.12 if _exit_mode() == "shrink" else 0.20


def _exit_scale(t, dur, fade, gain, grow, shrink=0.0):
    """Scale factor at time ``t`` of a picture shown ``dur`` s whose fade lasts ``fade`` s: 1 for most of its
    life, then a smooth swell of ``gain`` over EXIT_SWELL s and ``grow`` more while it fades (swell mode), or
    the old shrink of ``shrink`` while it fades (shrink mode)."""
    q = _ease(max(0.0, (t - (dur - fade)) / fade))
    if _exit_mode() == "shrink":
        return 1.0 - shrink * q
    return 1.0 + gain * _smooth((t - (dur - fade - EXIT_SWELL)) / EXIT_SWELL) + grow * q


def _card_frames(src, folder, fps, dur, W, H, zoom="soft", border="soft"):
    """The image as an animated PNG sequence (RGBA), the way an editor
    would place it:

    * wide / square photos -> a CARD: ~86 % of the width, rounded corners, a
      thin white edge and a soft drop shadow, centred a bit above the middle
      (the captions at ~65 % stay readable under it);
    * tall images (Gemini's 9:16) -> the full frame.

    Both pop in (scale 0.9 -> 1 with a fade, 0.15 s), push in slowly (8 %)
    while on screen, and fade out over the last 0.12 s. Returns
    (pattern, x, y, full)."""
    img = Image.open(src).convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.07)
    img = ImageEnhance.Color(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.15)
    iw, ih = img.size
    full = ih / iw >= 1.45
    if full:
        cw, ch, radius, edge, shadow = W, H, 0, 0, 0
    else:
        cw = int(W * 0.86)
        ch = int(cw * min(max(ih / iw, 0.72), 1.12))
        radius, edge, shadow = int(cw * 0.045), max(3, W // 300), int(W * 0.03)
    pad = shadow * 2
    cvw, cvh = cw + 2 * pad, ch + 2 * pad
    # Source pre-scaled once to the largest zoom; every frame crops from it.
    zmax = 1.08
    base = max(cw / iw, ch / ih) * zmax
    big = img.resize((int(iw * base) + 2, int(ih * base) + 2), Image.LANCZOS)
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius, fill=255)
    edge, rim_a, shade_a, blur_k = _border(border, edge, 1) if edge else (0, 0, 0, 0)
    rim = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    if edge and rim_a:
        ImageDraw.Draw(rim).rounded_rectangle((0, 0, cw - 1, ch - 1), radius, outline=(255, 255, 255, rim_a),
                                              width=edge)
    shade = Image.new("RGBA", (cvw, cvh), (0, 0, 0, 0))
    if shadow and shade_a:
        ImageDraw.Draw(shade).rounded_rectangle((pad, pad + shadow // 2, pad + cw, pad + ch + shadow // 2),
                                                radius, fill=(0, 0, 0, shade_a))
        shade = shade.filter(ImageFilter.GaussianBlur(shadow * blur_k))
    n = max(2, int(round(dur * fps)))
    for f in range(n):
        t = f / fps
        zoom = _push_in(f, n, zmax)
        vw, vh = cw * zmax / zoom, ch * zmax / zoom      # view into ``big``
        x0, y0 = (big.width - vw) / 2, (big.height - vh) / 2
        photo = big.crop((int(x0), int(y0), int(x0 + vw), int(y0 + vh))).resize((cw, ch), Image.BILINEAR)
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        card.paste(photo, (0, 0), mask)
        card.alpha_composite(rim)
        frame = shade.copy()
        frame.alpha_composite(card, (pad, pad))
        fade = _card_out()
        pin, pout = _ease(t / 0.15), min(1.0, (dur - t) / fade)
        k = _zoom_k(zoom)
        scale = (0.9 + 0.1 * pin) * _exit_scale(t, dur, fade, 0.05 * k, 0.04 * k)
        if scale < 0.999:
            small = frame.resize((max(1, int(cvw * scale)), max(1, int(cvh * scale))), Image.BILINEAR)
            frame = Image.new("RGBA", (cvw, cvh), (0, 0, 0, 0))
            frame.alpha_composite(small, ((cvw - small.width) // 2, (cvh - small.height) // 2))
        elif scale > 1.001:
            grown = frame.resize((int(cvw * scale), int(cvh * scale)), Image.BILINEAR)
            x0, y0 = (grown.width - cvw) // 2, (grown.height - cvh) // 2
            frame = grown.crop((x0, y0, x0 + cvw, y0 + cvh))
        alpha = min(pin, pout)
        if alpha < 0.999:
            frame.putalpha(frame.getchannel("A").point(lambda v, a=alpha: int(v * a)))
        frame.save(os.path.join(folder, f"c{f:03d}.png"), compress_level=1)
    x = (W - cvw) // 2
    y = (H - cvh) // 2 if full else max(int(H * 0.1), int(H * 0.40 - cvh / 2))
    return os.path.join(folder, "c%03d.png"), x, y, full


# "rise" layout: a small card comes up from the bottom edge, growing as it
# rises (slight overshoot), and settles in the free band BELOW the captions
# (or just ABOVE them) — never on them — at ``size`` % of the frame width,
# just big enough to tell what it is; then it shrinks and fades. The podcast
# stays sharp all around it.
RISE_DUR = 1.9
RISE_IN = 0.42      # s to come up and grow
RISE_OUT = 0.26     # s to shrink + fade
RISE_SIZE = 28      # default card width, % of the frame
RISE_GEN = (1024, 1024)  # square generated images for this layout
PLATFORM_UI = 0.82  # below this line TikTok / Reels / Shorts draw their caption and buttons (approximate: it varies by app)


def _ease_back(x, s=1.5):
    """0 -> 1 with a small overshoot (~6 %) before settling."""
    x = max(0.0, min(1.0, x)) - 1.0
    return 1.0 + (s + 1.0) * x ** 3 + s * x ** 2


def _caption_band(H, style=None, watermark=None):
    """(top, bottom) of the burned captions in px of this clip — the edit
    style's caption line (Clip Generator++ captions are centred on
    ``caption_y`` of a 1920 px frame) plus the channel watermark under it.
    Without an edit style: the default captions near the bottom. ``style`` /
    ``watermark``: given (the profile editor), else read from the job's env."""
    import viral_fx
    p = viral_fx.PRESETS.get((style if style is not None else os.environ.get("EDIT_STYLE")) or "")
    if not p:
        return int(H * 0.70), int(H * 0.80)
    size = p["size"]
    bottom = p["caption_y"] + 0.6 * size
    try:
        wm = watermark if watermark is not None else json.loads(os.environ.get("PLUS_FX_JSON") or "{}").get("watermark")
        if wm:
            bottom = p["caption_y"] + 0.95 * size + max(18, size // 4) * 0.6
    except ValueError:
        pass
    k = H / 1920
    return int((p["caption_y"] - 0.75 * size) * k), int(bottom * k)


def _free_y(v):
    """A user-chosen height (card centre, % from the top) or None."""
    try:
        y = float(v)
    except (TypeError, ValueError):
        return None
    return round(y, 1) if 3.0 <= y <= 97.0 else None


RISE_HARD_BOTTOM = 0.97   # a small card never goes below this line of the frame ...
RISE_HARD_TOP = 0.05      # ... nor above this one: the only limits on the size the user asks for


def _rise_box(cap_top, cap_bottom, position, size_pct, aspect, W=1080, H=1920, y_pct=None):
    """Where the settled small card sits and how big it is. The size asked for is HONOURED (18-60 % of the
    width): under the captions the card is centred in the free band while it fits, and past that it keeps its
    top just under the captions and grows downward (over the app's own buttons — the user's choice), so it never
    covers the captions. Only the frame's edges cut it. Shared by the renderer and the editor's preview.
    ``y_pct``: a height chosen by the user (the card's CENTRE, % of the frame height from the top) — it wins
    over ``position``; the card goes exactly there, kept inside the frame."""
    gap = int(H * 0.012)
    if position == "above":
        band_top, band_bottom = int(H * 0.12), cap_top - gap
        ch_max = band_bottom - int(H * RISE_HARD_TOP)
    elif position == "top":
        # Above the speaker's head (the crown of a tracked face sits at ~0.34 H): the one wide free zone of a
        # podcast frame once the hook is gone. The band is the limit here: lower would be on the hair.
        band_top, band_bottom = int(H * TOP_BAND[0]), int(H * TOP_BAND[1])
        ch_max = band_bottom - band_top
    else:
        band_top, band_bottom = cap_bottom + gap, int(H * PLATFORM_UI)
        ch_max = int(H * RISE_HARD_BOTTOM) - band_top
    pad = max(8, int(W * 0.016)) * 2
    wanted = int(W * max(18, min(90, int(size_pct))) / 100)   # the profile offers 18-60; SCREEN_CARD_SIZE goes past
    cw = wanted
    if y_pct is not None:
        ch_max = int(H * RISE_HARD_BOTTOM) - int(H * RISE_HARD_TOP)
    if cw * aspect > ch_max:
        cw = int(max(ch_max, H * 0.08) / aspect)
    ch = int(cw * aspect)
    if y_pct is not None:
        y_end = min(max(H * float(y_pct) / 100, H * RISE_HARD_TOP + ch / 2), H * RISE_HARD_BOTTOM - ch / 2)
    elif position == "above":
        y_end = band_bottom - ch / 2                   # card bottom just above the captions
    elif position == "top":
        y_end = (band_top + band_bottom) / 2           # centred in the band above the head
    else:
        y_end = max((band_top + band_bottom) / 2, band_top + ch / 2)
    return {"cw": cw, "ch": ch, "wanted": wanted, "y_end": y_end, "band_top": band_top, "band_bottom": band_bottom,
            "pad": pad, "room": band_bottom - band_top - 2 * pad}


def rise_geometry(edit_style, watermark, position, size_pct, W=1080, H=1920, aspect=1.0, y_pct=None):
    """What a small "rise" card measures for this edit style, for the profile editor: its settled box in px of a
    1080x1920 frame, the caption band and the app limit (``aspect`` = height / width of the picture, 1 for the
    generated squares)."""
    cap_top, cap_bottom = _caption_band(H, edit_style, bool(watermark))
    bx = _rise_box(cap_top, cap_bottom, position, size_pct, aspect, W, H, y_pct)
    left, top = (W - bx["cw"]) // 2, int(bx["y_end"] - bx["ch"] / 2)
    platform_y = int(H * PLATFORM_UI)
    return {"requested_pct": round(100 * bx["wanted"] / W), "effective_pct": round(100 * bx["cw"] / W),
            "limited": bx["cw"] < bx["wanted"], "room_px": bx["room"],
            "box": {"x": left, "y": top, "w": bx["cw"], "h": bx["ch"]},
            "cap_top": cap_top, "cap_bottom": cap_bottom, "band_top": bx["band_top"], "band_bottom": bx["band_bottom"],
            "platform_y": platform_y, "into_app_zone": (y_pct is not None or position != "above") and top + bx["ch"] > platform_y,
            "hard_top": int(H * RISE_HARD_TOP), "hard_bottom": int(H * RISE_HARD_BOTTOM), "W": W, "H": H}


def _font(size):
    """A bold sans for the little texts drawn on a card: the channel's premium font when it is in fonts/, else
    the system's Liberation Sans Bold, else PIL's default."""
    from PIL import ImageFont
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, "fonts", "Montserrat-ExtraBold.ttf"),
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _label_card(card, text, cw, ch):
    """A one-word label in small capitals, bottom-left of a card, on a dark pill (profile broll.label)."""
    text = re.sub(r"\s+", " ", str(text or "")).strip().upper()[:26]
    if not text:
        return
    size = max(13, int(cw * 0.04))
    font = _font(size)
    d = ImageDraw.Draw(card)
    spacing = size * 0.12
    widths = [d.textlength(ch_, font=font) for ch_ in text]
    tw = sum(widths) + spacing * (len(text) - 1)
    m = int(cw * 0.035)
    px, py = int(size * 0.7), int(size * 0.45)
    x0, y1 = m, ch - m
    y0 = y1 - size - 2 * py
    d.rounded_rectangle((x0, y0, x0 + tw + 2 * px, y1), radius=int(size * 0.5), fill=(0, 0, 0, 150))
    x = x0 + px
    for ch_, w in zip(text, widths):
        d.text((x, y0 + py), ch_, fill=(255, 255, 255, 235), font=font)
        x += w + spacing


def _rise_frames(src, folder, fps, dur, W, H, size_pct, position="below", y_pct=None, enter="rise", zoom="soft",
                 border="soft", look=None, label=None, grade="off", min_aspect=None, fx=None):
    """PNG sequence of the rising card, drawn in a fixed canvas; the canvas
    itself moves up through the overlay's ``y`` expression. Returns
    (pattern, x, motion) where motion = (y_start, y_end, drift, canvas_h[,
    rise_s]) for the canvas centre.

    ``look="premium"`` (the "mixed" layout's cards): a landscape card with a
    3 % radius that fades in while rising CARD_RISE_PX over CARD_IN s (no
    travel from the edge of the screen), pushes in CARD_PUSH while it stays,
    and fades out over CARD_OUT s shrinking CARD_OUT_SHRINK. ``label``: a
    small-caps word drawn in its corner. ``grade``: the picture's grade (a
    visual_mood grade, or an older clip's GRADES name) in place of the historical
    touch-up, with its grain per frame."""
    prem = look == "premium"
    img = Image.open(src).convert("RGB")
    params = _grade_params(grade)
    if params:
        img = _grade_colour(img, grade)
    else:
        img = ImageEnhance.Contrast(img).enhance(1.07)
        img = ImageEnhance.Color(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.15)
    grain = float(params.get("grain") or 0.0) if params else 0.0
    fx_rng = __import__("numpy").random.default_rng(13)
    rng = __import__("numpy").random.default_rng(11) if grain else None
    iw, ih = img.size
    cap_top, cap_bottom = _caption_band(H)
    shadow = max(8, int(W * 0.016))
    pad = shadow * int((BORDERS.get(border) or BORDERS["soft"]).get("pad", 2))
    aspect = min(max(ih / iw, min_aspect or (0.6 if prem else 0.75)), 1.25)   # ``min_aspect``: a wider picture (screen_inset)
    box = _rise_box(cap_top, cap_bottom, position, size_pct, aspect, W, H, y_pct)
    cw, ch, y_end = box["cw"], box["ch"], box["y_end"]
    radius = int(cw * (0.03 if prem else 0.07))
    edge, rim_a, shade_a, blur_k = _border(border, max(3, W // 360), 0)
    uw, uh = cw + 2 * pad, ch + 2 * pad              # card + its shadow margin
    zk = _zoom_k(zoom)
    smax = max(1.10, 1.02 + 0.13 * zk)   # room in the canvas for the exit swell
    cvw, cvh = int(uw * smax) + 2, int(uh * smax) + 2
    zmax = 1.05
    base = max(cw / iw, ch / ih) * zmax
    big = img.resize((int(iw * base) + 2, int(ih * base) + 2), Image.LANCZOS)
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius, fill=255)
    rim = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    if edge and rim_a:
        ImageDraw.Draw(rim).rounded_rectangle((0, 0, cw - 1, ch - 1), radius, outline=(255, 255, 255, rim_a), width=edge)
    shade = Image.new("RGBA", (uw, uh), (0, 0, 0, 0))
    if shade_a:
        ImageDraw.Draw(shade).rounded_rectangle((pad, pad + shadow // 2, pad + cw, pad + ch + shadow // 2),
                                                radius, fill=(0, 0, 0, shade_a))
        shade = shade.filter(ImageFilter.GaussianBlur(shadow * blur_k))
    n = max(2, int(round(dur * fps)))
    for f in range(n):
        t = f / fps
        zoom = (1.0 + (CARD_PUSH - 1.0) * f / max(1, n - 1)) if prem else _push_in(f, n, zmax)
        vw, vh = cw * zmax / zoom, ch * zmax / zoom
        x0, y0 = (big.width - vw) / 2, (big.height - vh) / 2
        if fx == "tremble":
            dx, dy = _fx_shift(fx_rng, x0, y0, vw)
            x0, y0 = x0 + dx, y0 + dy
        photo = big.crop((int(x0), int(y0), int(x0 + vw), int(y0 + vh))).resize((cw, ch), Image.BILINEAR)
        if fx == "double":
            import numpy as np
            photo = Image.fromarray(np.clip(_fx_double(np.asarray(photo, dtype=np.float32), f / fps), 0, 255).astype(np.uint8), "RGB")
        if rng is not None:
            photo = _grain(photo, grain, rng)
        unit = shade.copy()
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        card.paste(photo, (0, 0), mask)
        card.alpha_composite(rim)
        if label:
            _label_card(card, label, cw, ch)
        unit.alpha_composite(card, (pad, pad))
        if prem:
            q = _ease(max(0.0, (t - (dur - CARD_OUT)) / CARD_OUT))    # 0 -> 1 on the way out
            s = 1.0 - CARD_OUT_SHRINK * q
            alpha = _ease(t / CARD_IN) * (1.0 - q)
        else:
            fade = _rise_out()
            q = _ease(max(0.0, (t - (dur - fade)) / fade))               # 0 -> 1 on the way out
            if enter == "fade":
                s_in, a_in = 0.94 + 0.06 * _ease(t / 0.3), _ease(t / 0.3)      # no travel: it just appears, settling a little
            else:
                s_in, a_in = 0.3 + 0.7 * _entry_ease(t / RISE_IN), min(1.0, t / 0.06)
            s = s_in * _exit_scale(t, dur, fade, 0.07 * zk, 0.06 * zk, shrink=0.18)
            alpha = a_in * (1.0 - q)
        sw, sh = max(1, int(uw * s)), max(1, int(uh * s))
        frame = Image.new("RGBA", (cvw, cvh), (0, 0, 0, 0))
        frame.alpha_composite(unit.resize((sw, sh), Image.BILINEAR), ((cvw - sw) // 2, (cvh - sh) // 2))
        if alpha < 0.999:
            frame.putalpha(frame.getchannel("A").point(lambda v, a=alpha: int(v * a)))
        frame.save(os.path.join(folder, f"c{f:03d}.png"), compress_level=1)
    if prem:
        # No travel from the edge: it settles CARD_RISE_PX up while it fades in.
        return os.path.join(folder, "c%03d.png"), (W - cvw) // 2, (y_end + CARD_RISE_PX, y_end, 0, cvh, CARD_IN)
    # small, just outside the edge nearest to where it lands: the bottom one, or the top one for a card placed
    # in the upper half
    y_start = -ch * 0.3 / 2 if (y_pct is not None or position == "top") and y_end < H / 2 else H + ch * 0.3 / 2
    if enter == "fade":
        y_start = y_end                                # it does not travel
    # No drift once it has landed: overlay positions snap to even pixels, so a
    # slow slide shows as little jumps (the slow push-in inside the photo,
    # drawn in the frames, is what keeps it alive).
    return os.path.join(folder, "c%03d.png"), (W - cvw) // 2, (y_start, y_end, 0, cvh)


# The grade of a picture, applied when it is cut in (so a restyle keeps it and the image review judges the raw
# picture). Since B-roll « ambiance » (2-oct-2026) it is the picture's own (item["grade"], a visual_mood grade:
# its clip's feeling, its own correction, the signature, the pixel check's moves). GRADES are the named grades of
# the clips made before (item["grade"] = "cinematic"), kept so a restyle of those clips looks the same.
GRADES = {
    "cinematic": {"sat": 0.88, "contrast": 1.04, "lift": 10, "warm": 10, "cool": 10, "grain": 4.0},
    "clean": {"sat": 0.94, "contrast": 1.02, "lift": 4, "warm": 4, "cool": 4, "grain": 0.0},
}


def _grade_params(grade):
    """An item's grade -> its parameters (a dict), or None for no grade."""
    if isinstance(grade, dict):
        return grade
    return GRADES.get(grade) if isinstance(grade, str) else None


def grade_item(item, path, signature=None):
    """Set ``item["grade"]`` from its mood and its clip's base mood (visual_mood.grade, with the signature at
    ``signature``, plus.BROLL's when None), checked on the picture at ``path`` (visual_mood.check: only the grade
    moves), and ``item["pixels"]`` the check's report. Returns the gaps the grade could not close ([] also for an
    item without a mood, a register picture). Never raises."""
    if not item.get("mood") or item.get("register"):
        return []
    try:
        sig = visual_mood.SIGNATURE if signature is None else float(signature)
    except (TypeError, ValueError):
        sig = visual_mood.SIGNATURE
    g = visual_mood.grade(item["mood"], item.get("mood_base") or None, signature=sig)
    try:
        g, px = visual_mood.check(path, g, item["mood"])
    except Exception as e:
        px = {"error": str(e)[:160], "moved": [], "gap": []}
    item["grade"], item["pixels"] = g, px
    return list(px.get("gap") or [])


def _grade_colour(img, grade):
    """The colour part of a grade on a PIL RGB image (vignette and grain are drawn per frame by the renderers):
    a visual_mood grade (dict), or a named one of GRADES."""
    if isinstance(grade, dict):
        return visual_mood.apply_grade(img, grade)
    g = GRADES.get(grade) if isinstance(grade, str) else None
    if not g:
        return img
    import numpy as np
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    lum = arr @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    arr = lum[..., None] + (arr - lum[..., None]) * g["sat"]
    arr = np.clip((arr - 128.0) * g["contrast"] + 128.0, 0, 255)
    arr = g["lift"] + arr * (255.0 - g["lift"]) / 255.0
    t = (np.clip(lum, 0, 255) / 255.0)[..., None]
    arr[..., 0:1] += g["warm"] * t * t
    arr[..., 1:2] += g["warm"] * 0.45 * t * t
    arr[..., 2:3] += g["cool"] * (1 - t) * (1 - t)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def _grain(img, sigma, rng):
    """Fine film grain on a PIL RGB image (a new field every call)."""
    if not sigma:
        return img
    import numpy as np
    arr = np.asarray(img, dtype=np.float32) + rng.normal(0.0, sigma, (img.height, img.width, 1)).astype(np.float32)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


# What the image model cannot draw (v15), added at the edit on a sharp picture: "double" a faint copy that drifts
# beside it, "tremble" a fine shake. The director asks for it (fx), the item keeps it, every frame gets it.
FX_KINDS = ("double", "tremble")
FX_DOUBLE_ALPHA = 0.3      # the copy's weight
FX_DOUBLE_DRIFT = 0.024    # of the width: how far the copy drifts (it comes and goes)
FX_TREMBLE = 0.004         # of the width: the shake (a standard deviation)


def _fx_double(arr, t):
    """The picture with a faint copy of itself drifting beside it (``arr``: H x W x 3 float)."""
    import numpy as np
    h, w = arr.shape[:2]
    dx = int(round(w * FX_DOUBLE_DRIFT * (0.5 + 0.5 * np.sin(2 * np.pi * t / 2.2))))
    dy = int(round(h * 0.004 * np.sin(2 * np.pi * t / 3.1)))
    return arr * (1.0 - FX_DOUBLE_ALPHA) + np.roll(arr, (dy, dx), axis=(0, 1)) * FX_DOUBLE_ALPHA


def _fx_shift(rng, room_x, room_y, w):
    """The tremble's offset for one frame, within the room the crop leaves."""
    dx = max(-room_x, min(room_x, float(rng.normal(0.0, FX_TREMBLE * w))))
    dy = max(-room_y, min(room_y, float(rng.normal(0.0, FX_TREMBLE * w))))
    return dx, dy


def object_box(W=1080, H=1920, size_pct=None, aspect=None):
    """(x, y, w, h) of the « littéral » chain's object card in a W x H frame: OBJECT_SIZE % of the width, the
    generated picture's shape (OBJECT_GEN), centred, its top just under the captions (_caption_band) held within
    OBJECT_TOP of the height — under captions in the middle of the frame, else over the bottom of the face."""
    cw = int(W * max(30, min(95, int(size_pct or OBJECT_SIZE))) / 100)
    ch = int(cw * (aspect or OBJECT_GEN[1] / OBJECT_GEN[0]))
    _cap_top, cap_bottom = _caption_band(H)
    top = int(min(max(cap_bottom + H * 0.012, H * OBJECT_TOP[0]), H * OBJECT_TOP[1]))
    top = min(top, int(H * RISE_HARD_BOTTOM) - ch)
    return (W - cw) // 2, top, cw, ch


def _object_frames(src, folder, fps, dur, W, H, size_pct=None):
    """PNG sequence (RGBA) of an object card (the « littéral » chain): the picture as a big card with rounded corners
    and a light shadow, a hard cut in and out, no move (the frames are one image repeated). Returns (pattern, x, y) of
    the canvas (card + shadow margin)."""
    img = Image.open(src).convert("RGB")
    img = ImageEnhance.Sharpness(img).enhance(1.1)
    x, y, cw, ch = object_box(W, H, size_pct, img.height / img.width)
    img = img.resize((cw, ch), Image.LANCZOS)
    radius = int(cw * 0.06)
    shadow = max(8, int(W * 0.014))
    pad = shadow * 2
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius, fill=255)
    canvas = Image.new("RGBA", (cw + 2 * pad, ch + 2 * pad), (0, 0, 0, 0))
    shade = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shade).rounded_rectangle((pad, pad + shadow // 2, pad + cw, pad + ch + shadow // 2), radius,
                                            fill=(0, 0, 0, 110))
    canvas.alpha_composite(shade.filter(ImageFilter.GaussianBlur(shadow * 0.8)))
    card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    card.paste(img, (0, 0), mask)
    canvas.alpha_composite(card, (pad, pad))
    first = os.path.join(folder, "c000.png")
    canvas.save(first, compress_level=1)
    for f in range(1, max(2, int(round(dur * fps)))):
        shutil.copyfile(first, os.path.join(folder, f"c{f:03d}.png"))
    return os.path.join(folder, "c%03d.png"), x - pad, y - pad, canvas.height


def _split_frames(src, folder, fps, dur, W, H):
    """PNG sequence of a split screen's bottom half: the picture covering W x H/2 (centre crop), a hard cut, no move."""
    img = Image.open(src).convert("RGB")
    img = ImageEnhance.Sharpness(img).enhance(1.1)
    hw, hh = W, H - H // 2
    k = max(hw / img.width, hh / img.height)
    big = img.resize((max(hw, int(img.width * k + 0.5)), max(hh, int(img.height * k + 0.5))), Image.LANCZOS)
    x0, y0 = (big.width - hw) // 2, (big.height - hh) // 2
    first = os.path.join(folder, "c000.png")
    big.crop((x0, y0, x0 + hw, y0 + hh)).save(first, compress_level=1)
    for f in range(1, max(2, int(round(dur * fps)))):
        shutil.copyfile(first, os.path.join(folder, f"c{f:03d}.png"))
    return os.path.join(folder, "c%03d.png")


MARK_COLOUR = (255, 255, 255)
MARK_GLOW = (150, 220, 255)


def _mark_vec(mk, cx):
    """The unit direction of an arrow mark in frame space ("in": toward the frame's middle line ``cx``)."""
    d = mk.get("dir")
    if d in ("in", "out"):
        sx = 1.0 if mk["px"] < cx else -1.0
        return (sx, 0.0) if d == "in" else (-sx, 0.0)
    return {"left": (-1.0, 0.0), "right": (1.0, 0.0), "up": (0.0, -1.0), "down": (0.0, 1.0)}.get(d, (1.0, 0.0))


def _draw_marks(W, H, marks, t):
    """RGBA layer of a « littéral » sequence step's marks at ``t`` s into the step, drawn by the code (exact, never asked
    from the image model), glowing white: an arrow that slides along its direction, a circle arrow that turns
    (cw / ccw as seen), a glow that pulses. ``marks``: [{"kind", "dir", "px", "py"}] in frame pixels."""
    import math
    sharp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(sharp)
    lw = max(4, int(W * 0.009))
    for mk in marks:
        x, y = mk["px"], mk["py"]
        if mk["kind"] == "arrow":
            vx, vy = _mark_vec(mk, W / 2)
            L = W * 0.10
            s = L * 0.35 * ((t / 0.9) % 1.0)                     # it slides along its way, again and again
            x0, y0 = x - vx * L * 0.5 + vx * s, y - vy * L * 0.5 + vy * s
            x1, y1 = x0 + vx * L, y0 + vy * L
            d.line((x0, y0, x1, y1), fill=MARK_COLOUR + (255,), width=lw)
            hx, hy, a = -vx * lw * 3.2, -vy * lw * 3.2, lw * 2.4
            d.polygon([(x1 + vx * lw, y1 + vy * lw), (x1 + hx - vy * a, y1 + hy + vx * a),
                       (x1 + hx + vy * a, y1 + hy - vx * a)], fill=MARK_COLOUR + (255,))
        elif mk["kind"] == "circle":
            r = W * 0.055
            sign = 1.0 if mk.get("dir") != "ccw" else -1.0       # PIL's angles turn clockwise on the screen
            a0 = (sign * 360.0 * t / 1.6) % 360.0
            if sign > 0:
                start, end = a0, a0 + 290.0
            else:
                start, end = a0 - 290.0, a0
            d.arc((x - r, y - r, x + r, y + r), start, end, fill=MARK_COLOUR + (255,), width=lw)
            tip = math.radians(end if sign > 0 else start)
            tx, ty = x + r * math.cos(tip), y + r * math.sin(tip)
            # the head points along the way it turns
            vx, vy = -math.sin(tip) * sign, math.cos(tip) * sign
            a = lw * 2.2
            d.polygon([(tx + vx * a * 1.4, ty + vy * a * 1.4), (tx - vy * a, ty + vx * a), (tx + vy * a, ty - vx * a)],
                      fill=MARK_COLOUR + (255,))
        elif mk["kind"] == "glow":
            r = W * (0.05 + 0.02 * (0.5 + 0.5 * math.sin(2 * math.pi * t / 1.2)))
            d.ellipse((x - r, y - r, x + r, y + r), fill=MARK_GLOW + (200,))
    glow = sharp.filter(ImageFilter.GaussianBlur(max(6, int(W * 0.012))))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(glow)
    out.alpha_composite(glow)
    if any(mk["kind"] != "glow" for mk in marks):
        out.alpha_composite(sharp)
    else:
        out.alpha_composite(sharp.filter(ImageFilter.GaussianBlur(max(3, int(W * 0.006)))))
    return out


def _hero_frames(src, folder, fps, dur, W, H, grade="off", fx=None, marks=None):
    """PNG sequence (RGBA) of a full-screen "hero" picture, the way a cutaway is
    cut in a documentary: the image covers the frame (centre crop), pushes in
    slowly (1.00 -> HERO_PUSH, eased over its whole time on screen) and
    crossfades in and out over HERO_FADE s — the podcast stays sharp underneath,
    no blur. Every frame is resampled with LANCZOS straight from the source with
    a sub-pixel box, so the move is smooth (zoompan rounds its window to whole
    pixels and shimmers on a slow zoom). A soft vignette, a dark gradient at the
    bottom (the captions stay readable on a bright picture) and a fine film
    grain that changes every frame finish it. ``grade``: the picture's grade
    (a visual_mood grade, or an older clip's GRADES name) in place of the
    historical contrast / colour touch-up.
    Since 5-oct-2026 (« caméra fixe ») HERO_PUSH is 1.0 and HERO_FADE 0: a hard
    cut in and out and no move — the picture is then resampled once, only the
    grain changes from frame to frame.
    Returns the frame pattern."""
    import numpy as np
    img = Image.open(src).convert("RGB")
    if _grade_params(grade):
        img = _grade_colour(img, grade)
    else:
        img = ImageEnhance.Contrast(img).enhance(1.07)
        img = ImageEnhance.Color(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.2)      # the source is smaller than the frame (896 px -> 1080 px)
    iw, ih = img.size
    if iw / ih > W / H:
        sh, sw = ih, ih * W / H
    else:
        sw, sh = iw, iw * H / W
    # Static shading (one array for the whole sequence): vignette + bottom gradient.
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    rx, ry = (xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2)
    r2 = np.clip((rx * rx + ry * ry) / 2.0, 0, 1)            # 0 at the centre, 1 at the corners
    shade = 1.0 - HERO_VIGNETTE * r2 * r2
    g = np.clip((yy / H - 0.55) / 0.45, 0, 1)                # 0 down to 55 % of the height, 1 at the bottom
    shade = (shade * (1.0 - HERO_GRADIENT * g * g))[..., None].astype(np.float32)
    rng = np.random.default_rng(7)
    noise = rng.normal(0.0, HERO_GRAIN, (H, W, 1)).astype(np.float32) if HERO_GRAIN > 0 else None
    n = max(2, int(round(dur * fps)))
    fx_rng = np.random.default_rng(13)
    still = None      # the picture never moves (no push, no effect): resampled once
    # A « littéral » sequence step's marks (fractions of the source picture) in frame pixels, through the crop.
    px_marks = []
    for mk in marks or ():
        try:
            u, v = float(mk["x"]), float(mk["y"])
        except (KeyError, TypeError, ValueError):
            continue
        cx0, cy0 = (iw - sw) / 2, (ih - sh) / 2
        px_marks.append({**mk, "px": (u * iw - cx0) / sw * W, "py": (v * ih - cy0) / sh * H})
    for f in range(n):
        t = f / fps
        z = 1.0 + (HERO_PUSH - 1.0) * _smooth(t / dur)
        if fx == "tremble":
            z *= 1.025                                        # room for the shake inside the picture
        bw, bh = sw / z, sh / z
        x0, y0 = (iw - bw) / 2, (ih - bh) / 2
        if fx == "tremble":
            dx, dy = _fx_shift(fx_rng, x0, y0, bw)
            x0, y0 = x0 + dx, y0 + dy
        if still is not None:
            arr = still.copy()
        else:
            frame = img.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + bw, y0 + bh))
            arr = np.asarray(frame, dtype=np.float32)
            if fx == "double":
                arr = _fx_double(arr, t)
            arr = arr * shade
            if abs(HERO_PUSH - 1.0) < 1e-9 and fx is None:
                still = arr.copy()
        if noise is not None:
            # The same grain field moved around: new grain every frame for the price of a copy.
            arr += np.roll(noise, (int(rng.integers(0, H)), int(rng.integers(0, W))), axis=(0, 1))
        out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
        if px_marks:
            out = out.convert("RGBA")
            out.alpha_composite(_draw_marks(W, H, px_marks, t))
            out = out.convert("RGB")
        # A hard cut when HERO_FADE is 0 (5-oct-2026), else a crossfade in and out.
        alpha = min(_smooth(t / HERO_FADE), _smooth((dur - t) / HERO_FADE)) if HERO_FADE > 0 else 1.0
        out.putalpha(int(round(255 * max(0.0, min(1.0, alpha)))))
        out.save(os.path.join(folder, f"c{f:03d}.png"), compress_level=1)
    return os.path.join(folder, "c%03d.png")


def screen_item(inset, img_dir=None):
    """The B-roll item for the picture the source put on screen (screen_inset.detect + prepare: clip
    ``screen_inset`` with ``image``, the still next to the clip). A wide card above the head, at the premium
    drawing, from the second the source showed it for as long as it showed it. None without the still."""
    if not inset:
        return None
    path = inset.get("path") or (os.path.join(img_dir, inset["image"]) if img_dir and inset.get("image") else None)
    if not path or not os.path.exists(path):
        return None
    t0, t1 = float(inset.get("t0") or 0.0), float(inset.get("t1") or 0.0)
    dur = round(min(SCREEN_DUR_MAX, max(SCREEN_DUR_MIN, t1 - t0)), 2)
    return {"t": round(t0, 2), "dur": dur, "anchor": "on screen", "idea": "the picture the video itself showed",
            "role": None, "query": "the picture shown on screen", "prompt": "", "source": "screen", "style": "photo",
            "layout": "card", "look": "premium", "size": SCREEN_CARD_SIZE, "position": CARD_POSITION,
            "border": "premium", "image": inset.get("image"), "_img": path}


def _block_of(item):
    """The stretch of the clip a screen item takes, for the planner: a second of lead so a card leaves first."""
    return [(round(float(item["t"]) - 1.0, 2), round(float(item["t"]) + float(item["dur"]), 2))] if item else []


def add_screen_only(clip_path, out_path, inset, img_dir=None, manual=False):
    """Only the source's own picture, as a card (no B-roll in the profile, or none planned). Same report as
    add_broll, or None."""
    item = screen_item(inset, img_dir)
    if not item:
        return None
    if not manual:
        overlay_items(clip_path, out_path, [item])
    item.pop("_img", None)
    print(f"   🖼️ B-roll: the picture the source showed on screen, as a card from {item['t']:.1f}s for "
          f"{item['dur']:.1f} s" + (" (manual review: not cut in yet)" if manual else ""))
    return {"items": [item], "credits": [], "planner": "screen", "sources": ["screen"], "pending": manual}


# --- the opening drawing (5-oct-2026, decision 8; plus.BROLL "opening", OFF until the A/B test) ---------------------
# Never on the opening: a drawing whose words evoke a death or a serious illness (the code's net, before any call;
# the chooser is told the same and also refuses a real, recognisable person). A clip about a death opens on the face.
OPENING_NO_RE = re.compile(
    r"\b(dead|deaths?|die[sd]?|dying|kill\w*|suicid\w*|overdos\w*|funeral\w*|coffins?|graves?|graveyards?|"
    r"gravestones?|corpses?|morgue|autops\w*|cemeter\w*|tombs?\w*|skulls?|skeletons?|cancer\w*|tumou?rs?|chemo\w*|"
    r"terminal(?:ly)? ill\w*|hospital beds?|icu|intensive care|life support|ventilators?|coma|heart attacks?|"
    r"seizures?|drips?|iv bags?|blood\w*|wounds?|bleed\w*)\b", re.I)
OPENING_PX = (270, 480)      # the chooser sees each drawing at about a phone's size: what reads there reads in the feed
OPENING_PROMPT = """A short vertical video opens on ONE of the drawings attached, full screen, for its first {secs:g}
seconds, under its hook (the line written on top of it): "{hook}". The video's title: "{title}".
That first second decides whether someone scrolling stops. Pick the ONE drawing that reads in one glance on a phone —
one big clear subject, few small details — and shows what the hook is about.
Never pick a drawing that evokes a death or its means, a serious illness (a sick or dying person, a hospital bed, a
drip, a tumour), or a real, recognisable person. When no drawing qualifies, answer -1: the video then opens on the
speaker's face, which is fine.
{lines}
Return JSON: {{"pick": <the drawing's number, or -1>, "why": "<12 words at most>"}}"""
OPENING_SCHEMA = {"type": "object", "properties": {"pick": {"type": "integer"}, "why": {"type": "string"}},
                  "required": ["pick", "why"]}


def opening_candidates(drawn):
    """The (item, cand) pairs that may open the clip: full-screen drawings only (not a card, not the source's own
    picture), not in a clip about a death, not on a sentence that mentions one, nothing in their words that evokes a
    death or a serious illness (OPENING_NO_RE)."""
    if any((c.get("m") or {}).get("clip_gravity") == "grave" for _it, c in drawn):
        return []
    out = []
    for it, c in drawn:
        m = c.get("m") or {}
        spec = m.get("spec") or {}
        if it.get("layout") != "hero" or it.get("source") == "screen" or spec.get("death_near"):
            continue
        # the director's own picture (the charter's style sentence left out), else the prompt
        text = " ".join(str(x or "") for x in (m.get("picture") or it.get("prompt"), m.get("idea_text"), it.get("idea"),
                                                it.get("subject"), m.get("said"), it.get("anchor")))
        if OPENING_NO_RE.search(text):
            filter_hit("opening: death or illness in its words", f'Picture "{it.get("anchor")}" never opens the clip.')
            continue
        out.append((it, c))
    return out


def choose_opening(cands, clip, tmp):
    """(index in ``cands``, why) of the drawing that opens the clip, or (None, why). One Claude call that SEES the
    drawings at a phone's size with the hook and the title (no Claude, a failed call or -1: no opening — a weak or
    wrong opening is worse than the face)."""
    if not cands:
        return None, "no full-screen drawing may open this clip"
    if not claude_ready():
        return None, "Claude is not available"
    thumbs, lines = [], []
    for k, (it, c) in enumerate(cands):
        path = os.path.join(tmp, f"opening_{k}.jpg")
        try:
            im = Image.open(it["_img"]).convert("RGB")
            im.thumbnail(OPENING_PX, Image.LANCZOS)
            im.save(path, quality=88)
        except Exception as e:
            return None, f"drawing unreadable ({str(e)[:60]})"
        thumbs.append(path)
        what = (c.get("m") or {}).get("idea_text") or it.get("idea") or it.get("subject") or it.get("anchor")
        lines.append(f'drawing {k} (image "opening_{k}.jpg", shown at {float(it["t"]):.1f}s on "{it.get("anchor")}"): '
                     f'{str(what)[:160]}')
    prompt = OPENING_PROMPT.format(secs=OPENING_SECONDS, hook=str(clip.get("viral_hook_text") or "")[:120],
                                   title=str(clip.get("video_title_for_youtube_short") or "")[:120],
                                   lines="\n".join(lines))
    try:
        import broll_ideas
        data = claude_json(prompt, OPENING_SCHEMA, timeout=180, attach=thumbs, stage="broll_opening",
                           model=broll_ideas._model("broll_verify", "sonnet"), effort="low") or {}
    except Exception as e:
        return None, f"the choice failed ({str(e)[:80]})"
    try:
        k = int(data.get("pick"))
    except (TypeError, ValueError):
        return None, "no answer"
    why = re.sub(r"\s+", " ", str(data.get("why") or "")).strip()[:120]
    return (k, why) if 0 <= k < len(cands) else (None, why or "none qualifies")


def opening_item(items, drawn, clip, tmp, keep_dir=None, keep_prefix=""):
    """The opening's B-roll item — the chosen drawing full screen from 0 to OPENING_SECONDS, a hard cut, no sound —
    or None. Its own copy of the picture (``<keep_prefix>broll_open.jpg``): the manual review and a restyle find each
    item by its file. Never over the source's own picture or a picture already up in the first seconds."""
    first = min((float(it["t"]) for it in items), default=None)
    if first is not None and first < OPENING_SECONDS + 0.25:
        print("   ℹ️ Opening drawing: a picture is already up in the first seconds — none.")
        return None
    cands = opening_candidates(drawn)
    k, why = choose_opening(cands, clip, tmp)
    if k is None:
        print(f"   ℹ️ Opening drawing: none ({why}) — the clip opens on the face.")
        return None
    it = cands[k][0]
    op = {key: v for key, v in it.items() if key not in ("sfx", "image", "_img")}
    op.update(t=0.0, dur=OPENING_SECONDS, layout="hero", opening=True, opening_why=why, _img=it["_img"])
    if keep_dir:
        name = f"{keep_prefix}broll_open.jpg"
        shutil.copy2(it["_img"], os.path.join(keep_dir, name))
        op["image"] = name
    print(f'   🎬 Opening drawing (0-{OPENING_SECONDS:g} s, under the hook): "{it.get("anchor")}" — {why}')
    return op


class ComfyDown(RuntimeError):
    """The local GPU (ComfyUI) is off or stopped answering: B-roll images are
    made only there, so the whole job stops instead of shipping clips without
    them. A single picture that fails while ComfyUI is up is not this: it is
    retried once, then skipped (add_broll.make_image)."""


def add_broll(clip_path, out_path, clip, transcript, start, end, cfg, api_key=None, keep_dir=None, keep_prefix="",
              ground_hook=False, block=()):
    """Cut up to cfg["max"] (1-10) images into ``clip_path``. Returns a report dict
    ({items, credits, planner, sources}) or None when nothing was added.
    ``keep_dir``: keep each image there (``<keep_prefix>broll_<k>.jpg``, named
    in its item as ``image``) so a restyle can re-apply them. ``block``: more
    (from, to) clip stretches no image may start in (the montage, 5-oct-2026:
    the reactions and the tight frames hiding its joins, montage.broll_block)."""
    import viral_fx
    # "manual" review: the images are kept next to the clip and listed, but
    # nothing is cut in until the user approves them (app.py .../broll/apply).
    manual = cfg.get("review") == "manual" and bool(keep_dir)
    FILTERS.clear()
    LAST_PICTURED[:] = []
    LAST_GEN[:] = []
    # The picture the source itself showed (screen_inset): one of the cards, placed by the source, not planned.
    screen = screen_item(clip.get("screen_inset"), keep_dir)
    block = _block_of(screen) + [(float(a), float(b)) for a, b in (block or ())]

    def screen_only():
        return add_screen_only(clip_path, out_path, clip.get("screen_inset"), keep_dir, manual)

    words = viral_fx.clip_words(transcript, start, end)
    if len(words) < 10:
        return screen_only()
    if not comfy_available():
        raise ComfyDown(f"ComfyUI not reachable at {_comfy_url()} (start it in Pinokio)")
    density = cfg.get("density") if cfg.get("density") in DENSITY else "normal"
    n = image_count(max(1, min(10, int(cfg.get("max") or 6))), density)
    if cfg.get("layout") == "mixed":
        n = MIXED_FEW if density == "less" else MIXED_MAX      # the premium pace, whatever the profile's max
    fixed = [f for f in (cfg.get("fixed_moments") or []) if isinstance(f, dict) and f.get("anchor")] or None
    if fixed:
        n = len(fixed)                                         # the bench's fixed moments: one answer each
    if screen:
        n = max(1, n - 1)                                      # the source's picture is one of them
    auto_style = cfg.get("style") == "auto"
    style = cfg.get("style") if cfg.get("style") in STYLES else "photo"
    engine = "zimage"
    rise = cfg.get("layout") == "rise"
    mixed = cfg.get("layout") == "mixed"     # premium: one full-screen hero + small cards
    hero_res = cfg.get("hero_res") if cfg.get("hero_res") in HERO_GEN else "std"
    size_pct = int(cfg.get("size") or RISE_SIZE)
    avoid = [float(clip["punchline_time"])] if clip.get("punchline_time") is not None else []
    planner = "local"
    moments = []
    tmp = tempfile.mkdtemp(prefix="broll_")
    # Images are made on this PC only (ComfyUI in Pinokio): no Gemini image, no free photo.
    used_local = True

    def item_layout(m):
        """Which family of picture this moment gets: hero / wide card, or the profile's single layout."""
        if mixed:
            return "hero" if m.get("hero") else "card"
        return "rise" if rise else "full"

    # The « dessin » chain in full width (5-oct-2026, decision 5): every drawing made 9:16 and shown alone, full screen,
    # HERO_DUR_MIN..MAX s, hard cut in and out — never a card on the head (the source's own picture stays a card).
    full = mixed and cfg.get("chain") == "dessin" and bool(cfg.get("full_width"))
    # The « littéral » chain (9-oct-2026, broll_litteral): the concrete nouns said, each shown on its word, a scene full
    # screen or an object card; it places its pictures and their times itself.
    literal = mixed and cfg.get("chain") == "litteral"
    dur_range = (HERO_DUR_MIN, HERO_DUR_MAX) if full else (CARD_DUR_MIN, CARD_DUR_MAX) if mixed else None
    # The pace of the mixed layout: MIXED_GAP between images, the last MIXED_TAIL s to the face, and a card above
    # the head never overlaps a hook longer than the usual head room.
    gap_min, tail, head = (MIXED_GAP, MIXED_TAIL, HEAD_FREE) if mixed else (0.0, None, HEAD_FREE)
    if mixed and os.environ.get("AUTO_HOOK") == "1":
        try:
            head = max(HEAD_FREE, float(os.environ.get("AUTO_HOOK_SECONDS") or 0) + 0.3)
        except ValueError:
            pass
    face_mode = cfg.get("faces") if cfg.get("faces") in FACE_MODES else "never"
    gpu = [0.0]      # seconds spent waiting for ComfyUI, for the clip's log line
    seeds = {}       # picture path -> the seed it was made with (kept in its item)

    base_for = {s.strip() for s in str(cfg.get("base_for") or "").split(",") if s.strip() in BASE_FOR}

    def image_model(m, m_layout, m_style):
        """("base", negative) for a picture that needs range (cfg "base_for": the hero, the register pictures), else
        ("turbo", "")."""
        if mixed and (("hero" in base_for and m_layout == "hero")
                      or ("register" in base_for and register_of(m_style))):
            return "base", base_negative(register_of(m_style), is_inner(m), m.get("parallel") == "pair")
        return "turbo", ""

    def make_image(prompt, m_style, raw, query, used_urls, sheet=None, layout=None, art=False, register=None, mood=None,
                   people=None, model="turbo", negative="", body=False):
        """(path, "local", None) from ComfyUI, or (None, None, None) when this
        one picture could not be made: a second try with a new seed, then the
        picture is skipped and the clip goes on with the others (one refused
        prompt used to stop the whole job). Only a ComfyUI that stopped
        answering raises ComfyDown: images are made nowhere else. ``mood``: the
        picture's mood (mixed layout): a prompt that is not the art director's
        gets its look sentence. ``people``: who is in its frame (declared);
        ``model`` / ``negative``: image_model's."""
        size = _gen_size(layout if layout is not None else ("rise" if rise else "full"), hero_res)
        steps = HERO_STEPS if layout == "hero" and HERO_STEPS > 0 and model != "base" else None
        faces = face_mode == "always" or (face_mode == "hero" and layout == "hero")
        mood_text = visual_mood.sentence(mood, drawn=bool(body)) if mixed and mood and not art else ""
        last = None
        for attempt in range(2):
            t0 = time.time()
            seed = random.randint(0, 2 ** 48)
            try:
                got = local_image(prompt, m_style, raw, engine=engine, size=size,
                                  look="" if mixed else look_text(sheet, m_style), art=art, seed=seed, steps=steps,
                                  faces=faces, register=register, mood=mood_text, people=people, model=model,
                                  negative=negative, body=body, drawing=episode_drawing() if body else "")
                seeds[got] = seed
                LAST_GEN.append({"file": os.path.basename(got), "model": model, "layout": layout,
                                 "size": list(size), "s": round(time.time() - t0, 1)})
                return got, "local", None
            except Exception as e:
                last = e
                if not comfy_available():
                    raise ComfyDown(f"ComfyUI stopped answering ({str(e)[:160]})") from e
            finally:
                gpu[0] += time.time() - t0
        print(f"   ⚠️ B-roll: no image for \"{str(query)[:40]}\" after two tries ({str(last)[:120]}) — skipped, "
              f"the clip keeps the others.")
        return None, None, None

    _comfy_enter()
    try:
        if mixed and cfg.get("chain") in ("spec", "dessin", "litteral"):
            # v20 « la fiche »: the editor's shot specs, the prompt written by the code, a blind check per batch
            # (broll_v20). No Gemini fallback: without Claude, no B-roll — a wrong picture is worse than none.
            if not claude_ready():
                print("   ⚠️ B-roll v20 needs Claude (claude CLI / CLAUDE_CODE_OAUTH_TOKEN) — no B-roll for this clip.")
                return screen_only()
            import broll_v20

            def render(text, out, layout):
                """One picture of the v20 chain: the code's prompt as is (no guardrail, no look sentence)."""
                size = _gen_size(layout, hero_res)
                steps = HERO_STEPS if layout == "hero" and HERO_STEPS > 0 else None
                for _attempt in range(2):
                    t0 = time.time()
                    seed = random.randint(0, 2 ** 48)
                    try:
                        got = local_image(text, "photo", out, engine=engine, size=size, seed=seed, steps=steps, raw=True)
                        LAST_GEN.append({"file": os.path.basename(got), "model": "turbo", "layout": layout,
                                         "size": list(size), "s": round(time.time() - t0, 1)})
                        return got, seed
                    except Exception as e:
                        if not comfy_available():
                            raise ComfyDown(f"ComfyUI stopped answering ({str(e)[:160]})") from e
                    finally:
                        gpu[0] += time.time() - t0
                return None, None

            if literal:
                import broll_litteral
                cands, moments = broll_litteral.run(clip_path, clip, words, avoid, block, tmp, render)
            elif cfg.get("chain") == "dessin":
                # v26 « dessin » (4-oct-2026): the art director in the episode's style charter, a safety verifier, one
                # render per moment — no judge, no render loop (broll_draw); in full width (5-oct-2026) every one 9:16
                import broll_draw
                cands, moments = broll_draw.run(clip_path, clip, words, transcript, start, end, n, avoid, head, tail,
                                                gap_min, block, dur_range, tmp, render, full=full)
            else:
                cands, moments = broll_v20.run(clip_path, clip, words, transcript, start, end, n, avoid, head, tail,
                                               gap_min, block, dur_range, tmp, render, ideas=bool(cfg.get("ideas")),
                                               reserve_mode=str(cfg.get("reserves") or "none"),
                                               prose=bool(cfg.get("prose")), judge=cfg.get("judge") or None,
                                               shown=(os.path.join(os.path.dirname(os.path.abspath(clip_path)), "_broll_shown.json")
                                                      if cfg.get("shown") else None))
            planner = "claude"
            if not cands:
                print("   ℹ️ B-roll v20: no picture kept for this clip.")
                return screen_only()
        else:
            # Planner: Claude (the user's subscription) when chosen and set up —
            # it reads the conversation around the clip and SEES the clip (frame
            # sheets), so it illustrates the idea and never what is already on
            # screen. Gemini is the fallback: a quota hit on one never costs the
            # clip its B-roll.
            if cfg.get("planner") == "claude":
                if claude_ready():
                    try:
                        try:
                            sheets = _frame_sheets(clip_path, tmp)
                        except Exception as e:
                            print(f"   ⚠️ B-roll frame sheets failed ({e}) — Claude plans from the words only.")
                            sheets = []
                        # A screen clip's hook is rewritten from its frames in this
                        # same call (main.py then skips its own hook_grounding call).
                        ground = None
                        if ground_hook:
                            try:
                                import hook_grounding
                                ground = hook_grounding.request(clip_path, clip, transcript, start, end)
                            except Exception as e:
                                print(f"   ⚠️ Hook frames failed ({e}) — the hook is grounded on its own later.")
                        moments = plan_with_claude(clip, words, n, avoid, auto_style, transcript, start, end, sheets,
                                                   ground=ground,
                                                   mode=cfg.get("mode") or "mixed",
                                                   density=density,
                                                   hero=mixed, dur_range=dur_range, gap_min=gap_min, tail=tail, head=head,
                                                   block=block, fixed=fixed, parallel=bool(cfg.get("parallel")))
                        planner = "claude"
                        if not moments:
                            print("   ℹ️ B-roll: Claude found no moment where an image would add meaning — none added.")
                            return screen_only()
                    except Exception as e:
                        print(f"   ⚠️ B-roll planning via Claude failed ({str(e)[:200]}) — Gemini instead.")
                else:
                    print("   ⚠️ B-roll planner is Claude but it is not set up "
                          "(claude CLI / CLAUDE_CODE_OAUTH_TOKEN) — Gemini instead.")
            if not moments and api_key:
                try:
                    import ai_brain
                    ai_brain.say("Gemini — Claude unavailable", "B-roll: choosing the images")
                    moments = plan_with_gemini(clip, words, n, avoid, api_key, auto_style, dur_range=dur_range,
                                               gap=max(MIN_GAP, gap_min), tail=tail, head=head, block=block)
                    planner = "gemini"
                except Exception as e:
                    print(f"   ⚠️ B-roll planning via Gemini failed ({e}) — local pick instead.")
            if not moments:
                # The local pick only knows words, not what they mean ("needle" ->
                # the Space Needle): no B-roll beats a wrong one.
                print("   ℹ️ B-roll skipped: moments need the Claude or Gemini planner (not set up or call failed).")
                return screen_only()
            if mixed:
                if auto_style:
                    # A photo or a register of the episode: whatever else the planner picked is a photo.
                    for m in moments:
                        m["style"] = premium_style(m.get("style"))
                # Every picture has a mood (a planner that gave none: the plainest levels), and the clip a base mood: the
                # median of its pictures with the episode's as one more vote (visual_mood.base).
                import ai_brain
                for m in moments:
                    m["mood"] = m.get("mood") or visual_mood.clean(None)
                if any(m.get("clip_gravity") == "grave" for m in moments):
                    # The whole clip is about a death: every picture is grave and an absence (the editor's clip_gravity).
                    for m in moments:
                        m["mood"] = {**m["mood"], "gravity": "grave", "absence": not register_of(m.get("style"))}
                # Experience pictures: real suffering first (sober), and a cap per clip.
                moments = experience_guard(moments)
                clip_base = visual_mood.base([m["mood"] for m in moments], visual_mood.episode_levels(ai_brain.EPISODE_BIBLE))
                for m in moments:
                    m["mood_base"] = clip_base
                print(f"   🎚️ Clip mood: {visual_mood.describe(clip_base)}")
                # The code has the last word on the hero: the planner's pick counts, the timing rules win.
                k_hero = pick_hero(moments, words[-1]["end"], avoid, head, block, adaptive=cfg.get("mode") == "adaptive")
                for i, m in enumerate(moments):
                    m["hero"] = i == k_hero
                if k_hero is None:
                    print("   ℹ️ B-roll: no moment of this clip reads well on a whole screen — small cards only.")
            # The notion memory: a notion whose library is not complete gets a new picture this time, in the shot the
            # library lacks (the art director is told); a complete one is reused, its variants in turn.
            look = current_look() if mixed else look_key("")
            for m in moments:
                if m.get("notion"):
                    want = notion_missing_shot(m["notion"], (m.get("style") or "photo") if auto_style else style, engine,
                                               item_layout(m), look, m.get("shot"))
                    if want:
                        m["notion_shot"] = want
            if planner == "claude" and cfg.get("art_director"):
                # The second call: the prompts of the whole set, each in its look sheet (the editor's drafts stay
                # when it fails).
                direct_art(moments, clip, mixed=mixed, rise=rise, auto_style=auto_style, style=style,
                           clip_text=" ".join(w["text"] for w in words), faces=face_mode)
            if mixed:
                # A picture made sober (real suffering) needs the director's rewrite: the editor's draft still paints
                # what the person lives inside. Without it, no picture.
                for m in [m for m in moments if ((m.get("mood") or {}).get("sober") or (m.get("mood") or {}).get("absence"))
                          and not m.get("art")]:
                    filter_hit("experience: sober picture not rewritten",
                               f'Moment "{m.get("anchor")}" dropped: made sober (or an absence), but its prompt is still the editor\'s draft.')
                    moments.remove(m)
                if not moments:
                    return screen_only()
            LAST_PICTURED[:] = moments

            used_urls, cands = set(), []
            for k, m in enumerate(moments):
                m_style = (m.get("style") or "photo") if auto_style else style
                m_layout = item_layout(m)
                raw = os.path.join(tmp, f"broll_{k}.jpg")
                kept = (notion_get(m.get("notion"), m_style, engine, m_layout, raw, look)
                        if m.get("notion") and not m.get("notion_shot") and not m.get("inside_body") else None)
                if kept:
                    print(f"   ♻️ Notion \"{m['notion']}\": the channel's picture is reused (no image made, no review).")
                    cands.append({"k": k, "m": m, "style": m_style, "file": kept, "source": "local", "credit": None,
                                  "score": 5, "reused": True, "layout": m_layout})
                    continue
                # A notion's picture is the channel's usual one, kept for other clips:
                # made without this clip's look.
                model, negative = image_model(m, m_layout, m_style)
                people = "none" if is_inner(m) else m.get("people")     # an inner picture never gets a person
                got, used, credit = make_image(m["prompt"], m_style, raw, m["query"], used_urls,
                                               None if m.get("notion") else m.get("sheet"), layout=m_layout,
                                               art=bool(m.get("art")), register=register_look(m), mood=m.get("mood"),
                                               people=people, model=model, negative=negative,
                                               body=bool(m.get("inside_body")))
                takes = HERO_TAKES if m_layout == "hero" else 1
                if got:
                    cands.append({"k": k, "m": m, "style": m_style, "file": got, "source": used, "credit": credit,
                                  "layout": m_layout, "seed": seeds.get(got), "model": model,
                                  **({"take": 1} if takes > 1 else {})})
                    # The hero's other takes: the director's other composition of the same moment (v16 — Turbo paints
                    # one prompt alike whatever the seed), else the same prompt with a new seed. The judge sees the takes
                    # together, the best one stays.
                    for j in range(2, takes + 1):
                        raw_j = os.path.join(tmp, f"broll_{k}_t{j}.jpg")
                        alt = m.get("prompt_alt") if j == 2 else None
                        m_j = {**m, "prompt": alt} if alt else m
                        got_j, used_j, credit_j = make_image(m_j["prompt"], m_style, raw_j, m["query"], used_urls,
                                                             None if m.get("notion") else m.get("sheet"), layout=m_layout,
                                                             art=bool(m.get("art")), register=register_look(m),
                                                             mood=m.get("mood"), people=people, model=model,
                                                             negative=negative, body=bool(m.get("inside_body")))
                        if got_j:
                            cands.append({"k": k, "m": m_j, "style": m_style, "file": got_j, "source": used_j,
                                          "credit": credit_j, "layout": m_layout, "seed": seeds.get(got_j), "take": j,
                                          "model": model, **({"alt": True} if alt else {})})

            # Claude checks every image against the idea it must carry; a weak
            # generated one is redone once from its better prompt, then dropped
            # if it is still not clear.
            if planner == "claude" and any(not c.get("reused") for c in cands):
                try:
                    checked = [c for c in cands if not c.get("reused")]
                    for c, r in zip(checked, review_images(checked, words)):
                        _take_review(c, r)
                    # Several takes of one moment: the best one stays (meaning, then look; the first on a tie), the
                    # others leave before the redo rounds.
                    best = {}
                    for c in checked:
                        if c.get("take") and (c["k"] not in best or _better(c, best[c["k"]])):
                            best[c["k"]] = c
                    if best:
                        drop = [c for c in checked if c.get("take") and best[c["k"]] is not c]
                        cands = [c for c in cands if c not in drop]
                        checked = [c for c in checked if c not in drop]
                        for c in best.values():
                            print(f"   🎬 Hero: take {c['take']} kept (score {c['score']}, look {c.get('look_score')}) of "
                                  f"{1 + len([d for d in drop if d['k'] == c['k']])}.")
                    for c in checked:
                        # the best take still failing means every take failed: as many failures as takes
                        c["failed"] = (1 + len([d for d in (drop if best else []) if d["k"] == c["k"]])) if _needs_redo(c) else 0
                    redone = 0
                    for _round in range(max(REDO_CARD + REDO_NEW_IDEA, REDO_HERO)):
                        # A weak picture is made again from the reviewer's better prompt: once for a card (and once
                        # more with another idea when that one failed too), twice for the hero. The better prompt of an
                        # art-directed picture is in the director's grammar and goes out as such; a short one is the
                        # editor's kind again. Another idea (v16) is the art director's: one call for every picture of
                        # the round that needs one, with what was tried and what the review saw.
                        wants = [c for c in checked if _needs_redo(c) and c.get("tries", 0) < _redo_budget(c)
                                 and _wants_new_idea(c)
                                 and (not c.get("new_prompt") or c["new_prompt"] in (c.get("tried") or ()))]
                        if wants and cfg.get("art_director"):
                            another_idea(wants, clip, " ".join(w["text"] for w in words), mixed=mixed,
                                         auto_style=auto_style, style=style, faces=face_mode)
                        todo = [c for c in checked if _needs_redo(c) and _next_prompt(c)
                                and c.get("tries", 0) < _redo_budget(c)]
                        pairs = []
                        for c in todo:
                            c["tries"] = c.get("tries", 0) + 1
                            nxt = _next_prompt(c)
                            c.setdefault("tried", []).append(nxt)
                            new = c.get("new") if nxt == c.get("new_prompt") else None
                            if new:
                                filter_hit("redo: a new idea", f'Picture "{c["m"]["anchor"]}": '
                                           + ("not safe" if not _safe(c) else f'{c.get("failed")} failed attempts')
                                           + " — another idea, not the same scene reworded.")
                            raw = os.path.join(tmp, f"broll_{c['k']}_v{c['tries'] + 1}.jpg")
                            art = (bool(c["m"].get("art")) or bool(new)) and len(nxt.split()) >= ART_MIN_WORDS
                            m_next = {**c["m"], "prompt": nxt, "art": art}
                            if new:
                                # The director's new picture comes with its own judge line, fx and people.
                                m_next.update(judge=new.get("judge") or c["m"].get("judge"), fx=new.get("fx"),
                                              people=new.get("people") or c["m"].get("people"),
                                              inside_body=bool(new.get("inside_body") or c["m"].get("inside_body")))
                            model, negative = image_model(m_next, c["layout"], c["style"])
                            got, used, credit = make_image(nxt, c["style"], raw, c["m"]["query"],
                                                           used_urls, None if c["m"].get("notion") else c["m"].get("sheet"),
                                                           layout=c["layout"], art=art, register=register_look(c["m"]),
                                                           mood=c["m"].get("mood"),
                                                           people="none" if is_inner(m_next) else m_next.get("people"),
                                                           model=model, negative=negative,
                                                           body=bool(m_next.get("inside_body")))
                            if got:
                                pairs.append((c, {**c, "file": got, "source": used, "credit": credit, "seed": seeds.get(got),
                                                 "m": m_next, "model": model}))
                        if not pairs:
                            break
                        redone += len(pairs)
                        for (c, c2), r2 in zip(pairs, review_images([c2 for _, c2 in pairs], words)):
                            _take_review(c2, r2)
                            failed = c.get("failed", 0) + (1 if _needs_redo(c2) else 0)
                            if _better(c2, c):
                                c.update(c2)
                            c["failed"] = failed
                    kept = _keep_meaningful(cands)
                    print(f"   🔎 B-roll review: scores {[c['score'] for c in cands]}, looks "
                          f"{[c.get('look_score') for c in cands]}"
                          f"{f', {redone} redone' if redone else ''}, {len(kept)}/{len(cands)} kept")
                    for c in cands:
                        if c not in kept:
                            why = ("unsafe" if not _safe(c) else "false fact" if not _facts_ok(c)
                                   else "sense" if c["score"] < KEEP_SCORE else "look")
                            filter_hit(f"review: dropped ({why})", f'Picture "{c["m"]["anchor"]}" dropped by the review ({why}: sense '
                                                                   f'{c["score"]}, look {c.get("look_score")}): {c.get("problem") or "-"}')
                    for c in kept:
                        if c["m"].get("notion") and not c["m"].get("inside_body") and not c.get("reused") and c["score"] >= NOTION_MIN_SCORE and c["style"] in STYLES:
                            if notion_put(c["m"]["notion"], c["style"], engine, c["layout"], c["file"], c["m"]["prompt"],
                                          c["score"], look=look, shot=c["m"].get("notion_shot") or c["m"].get("shot"),
                                          mood=c["m"].get("mood")):
                                print(f"   📚 Notion \"{c['m']['notion']}\": picture kept for the next clips "
                                      f"({c['m'].get('notion_shot') or c['m'].get('shot') or '-'} shot).")
                    cands = kept
                except ComfyDown:
                    raise
                except Exception as e:
                    print(f"   ⚠️ B-roll review via Claude failed ({str(e)[:160]}) — images kept unchecked.")

        items, credits, sources = [], [], []
        drawn = []       # (item, cand) of every picture made for this clip, for the opening drawing
        for c in cands:
            m = c["m"]
            # A real photo (a place, a flag) is shown BIG: a small card shows a tower or a flag badly. Big
            # pictures cover the speaker, so they stay short.
            hero = mixed and c["layout"] == "hero"
            obj = mixed and c["layout"] == "object"
            big = (not rise and not mixed) or (c["source"] == "free" and not mixed)
            dur = m.get("dur") or (SEG_DUR if big else RISE_DUR)
            if literal:
                dur = round(float(m["dur"]), 2)            # broll_litteral.schedule's: its clause, the pace, the cover
            elif hero:
                # its sentence, HERO_DUR_MIN..MAX s; in full width it also leaves before the punchline
                dur = full_dur(m, avoid) if full else hero_dur(m)
            elif _hold(cfg.get("hold")) and not mixed:
                dur = _hold(cfg.get("hold"))               # the user's own time on screen (a mixed card follows its sentence)
            elif big:
                dur = round(max(FULL_DUR_MIN, min(FULL_DUR_MAX, dur)), 2)
            item = {"t": round(m["t"], 2), "dur": dur, "anchor": m["anchor"],
                    "idea": m.get("idea") or "", "role": m.get("role"), "subject": m.get("subject") or "",
                    "query": m["query"], "prompt": m["prompt"],
                    "source": c["source"],
                    "style": c["style"] if c["source"] in ("local", "gemini") else "photo",
                    "layout": c["layout"] if literal else "hero" if hero else ("full" if big else ("card" if mixed else "rise")),
                    "_img": c["file"]}
            reg = register_of(c["style"])
            if reg:
                item["register"] = reg["look"]       # not a photograph: a manual redo paints it in its register again
            if m.get("judge"):
                item["judge"] = m["judge"]
            if m.get("people") in PEOPLE:
                item["people"] = "none" if is_inner(m) else m["people"]   # a manual redo's guard reads it (v16)
            if m.get("inside_body"):
                item["inside_body"] = True           # drawn, never photographed: a manual redo keeps it (v17)
                item["drawing"] = episode_drawing()  # v19: the episode's one drawing, the same in a manual redo
                if item["drawing"] == DRAWING_HOUSE:
                    filter_hit("drawing: the house's (no episode drawing)")
            if c.get("alt"):
                item["alt"] = True                   # the hero's other composition won (v16)
            if c.get("model") == "base":
                item["model"] = "base"               # made by Z-Image, the base model (v16, cfg base_for)
            if mixed:
                # The size the picture was made at: a manual redo asks for the same one.
                item["gen"] = list(_gen_size(c["layout"], hero_res))
                if m.get("fx") in FX_KINDS:
                    item["fx"] = m["fx"]                               # added at render, on the sharp picture
                if m.get("mood") and not reg:
                    item["mood"] = visual_mood.compact(m["mood"])      # its look: a manual redo keeps it
                    item["mood_base"] = dict(m.get("mood_base") or {})  # the clip's, for its grade
                    # Its grade (applied when it is cut in, restyle included), checked on its pixels.
                    gaps = grade_item(item, c["file"], cfg.get("signature"))
                    if gaps:
                        filter_hit("pixels: gap the grade cannot close",
                                   f'Picture "{m["anchor"]}": {"; ".join(gaps)} — the grade cannot close it.')
            if m.get("sheet") and not m.get("notion"):
                item["sheet"] = m["sheet"]      # kept: a manual redo keeps the clip's look
            if m.get("art"):
                # The art director's prompt (a redo from the review's better_prompt is the editor's kind again).
                item["art"] = True
                item["prompt_editor"] = m.get("prompt_editor") or ""
            if m.get("notion"):
                item["notion"] = m["notion"]
                if c.get("reused"):
                    item["reused"] = True
            if c.get("score"):
                item["score"] = c["score"]
            if c.get("look_score") is not None:
                item["look_score"] = c["look_score"]
            if c.get("seed") is not None:
                item["seed"] = c["seed"]        # the picture can be made again: same seed, another size or steps
            if c.get("take"):
                item["take"] = c["take"]        # which of the hero's takes the judge kept
            if mixed:
                # The premium drawing is fixed: premium edge, fade in, no exit zoom, cards CARD_SIZE % wide at
                # CARD_POSITION. The rise layout's hold / enter / zoom / border / size / position / y do not apply.
                item["border"] = "premium"
                if m.get("seq"):
                    # a step of a « littéral » sequence: the same figure, its marks drawn over it (_draw_marks)
                    item.update(seq=m["seq"], step=m.get("step", 0), marks=list(m.get("marks") or []))
                if literal:
                    item["format"] = m.get("format") or ""
                    if obj:
                        item.update(size=OBJECT_SIZE, background=m.get("background") or "")
                elif not hero:
                    item.update(look="premium", size=CARD_SIZE, position=CARD_POSITION)
                    if cfg.get("label"):
                        item["label"] = m.get("subject") or m.get("key") or m["anchor"]
            else:
                item["zoom"] = cfg.get("zoom") if cfg.get("zoom") in ZOOM_LEVELS else "soft"
                item["border"] = cfg.get("border") if cfg.get("border") in BORDERS else "soft"
                if not big:
                    item["enter"] = cfg.get("enter") if cfg.get("enter") in ENTER_MODES else "rise"
                    item.update(size=size_pct, position="above" if cfg.get("position") == "above" else "below")
                    if _free_y(cfg.get("y")) is not None:
                        item["y"] = _free_y(cfg.get("y"))
            if keep_dir:
                # Kept next to the clip: a later restyle re-cuts the same images.
                name = f"{keep_prefix}broll_{c['k']}.jpg"
                shutil.copy2(c["file"], os.path.join(keep_dir, name))
                item["image"] = name
            items.append(item)
            drawn.append((item, c))
            sources.append(c["source"])
            if c["credit"]:
                credits.append(c["credit"])
        if mixed and cfg.get("sfx"):
            # The whoosh (5-oct-2026, decision 3): on the first full-screen picture of the clip only, the others
            # come in silent.
            first = min((it for it in items if it["layout"] == "hero"), key=lambda it: float(it["t"]), default=None)
            if first is not None:
                first["sfx"] = True
        if not items:
            print("   ℹ️ B-roll: no image good enough for this clip's moments — clip left without.")
            return screen_only()
        graded = [it for it in items if isinstance(it.get("grade"), dict)]
        if graded:
            print("   🎨 Grades: " + " | ".join(
                f"{it.get('subject') or it['anchor']} ({visual_mood.describe(it['mood'])}): sat {it['grade']['sat']:g} "
                f"contrast {it['grade']['contrast']:g} temp {it['grade']['temp']:+g} sig {it['grade']['sig']:g}"
                + (f", pixels moved {', '.join(it['pixels']['moved'])}" if (it.get("pixels") or {}).get("moved") else "")
                + (f", GAP {'; '.join(it['pixels']['gap'])}" if (it.get("pixels") or {}).get("gap") else "")
                for it in graded))
        if screen:
            # The source's own picture takes its place among the cards, at the second the source showed it.
            items.append(screen)
            sources.append("screen")
            items.sort(key=lambda it: float(it["t"]))
        if _hold(cfg.get("hold")) or mixed or screen:
            # A fixed time on screen (or a hero longer than its sentence): two pictures never overlap, the
            # first one leaves a little early
            for a, b in zip(items, items[1:]):
                if literal or (a.get("seq") and a.get("seq") == b.get("seq")):
                    # broll_litteral.schedule placed them: picture to picture is a cut, never a flash of face
                    a["dur"] = round(min(a["dur"], b["t"] - a["t"]), 2)
                    continue
                a["dur"] = round(max(1.0, min(a["dur"], b["t"] - a["t"] - 0.25)), 2)
        clip.pop("opening_image", None)
        if full and cfg.get("opening"):
            # The opening drawing (5-oct-2026, decision 8; OFF in the recipe until the A/B test): the one exception to
            # HEAD_FREE, set after the planning — the other pictures keep the hook's seconds free.
            op = opening_item(items, drawn, clip, tmp, keep_dir, keep_prefix)
            if op:
                items.insert(0, op)
                sources.insert(0, op["source"])
                # the clip opens on a drawing (lot L5, the A/B test's statistics): the picture's file, else its anchor
                clip["opening_image"] = op.get("image") or op.get("anchor") or True
        if not manual:
            overlay_items(clip_path, out_path, items)
        for it in items:
            it.pop("_img", None)
        duration = words[-1]["end"]
        covered = sum(float(it["dur"]) for it in items)
        print(f"   🖼️ B-roll {cfg.get('layout') or 'full'}: {len(items)} image(s)"
              + (f" ({sum(it['layout'] == 'hero' for it in items)} hero)" if mixed else "")
              + f", {covered:.1f} s of {duration:.0f} s covered ({100 * covered / max(duration, 1.0):.0f} %), "
              f"ComfyUI {gpu[0]:.0f} s" + (" (manual review: not cut in yet)" if manual else ""))
        print(f"   🧮 Filters this clip: {filters_line()}")
        return {"items": items, "credits": credits, "planner": planner, "sources": sources, "pending": manual}
    finally:
        if used_local:
            _comfy_leave()
        shutil.rmtree(tmp, ignore_errors=True)


def regenerate_image(prompt, style, out_path, query="", cfg=None, api_key=None, sheet=None, gen=None, art=False,
                     seed=None, steps=None, register=None, mood=None, people=None, body=False, drawing=""):
    """One image again, from a new prompt / style (the manual review), on the
    local GPU. ``gen``: the (width, height) the first picture was made at (the
    item's "gen"), else the layout's usual size. ``art``: the item's prompt is
    the art director's (sent as is, when it still reads like one). ``mood``: the
    item's mood (mixed layout): a prompt that is not the director's gets its look
    sentence. Returns (path, source, credit); raises when nothing came."""
    cfg = cfg or {}
    style = style if (style in STYLES or register) else "photo"   # a register picture keeps its register's name
    engine = "zimage"
    rise = cfg.get("layout") == "rise"
    try:
        size = (int(gen[0]), int(gen[1])) if gen else (RISE_GEN if rise else (768, 1344))
    except (TypeError, ValueError, IndexError):
        size = RISE_GEN if rise else (768, 1344)
    if not comfy_available():
        raise RuntimeError("ComfyUI is not reachable (start it in Pinokio)")
    # A hero or a wide card belongs to a "mixed" clip: its look is its mood's, like the first picture's.
    mixed = cfg.get("layout") in ("hero", "card", "mixed")
    try:
        art = bool(art) and len(str(prompt).split()) >= ART_MIN_WORDS
        mode = cfg.get("faces") if cfg.get("faces") in FACE_MODES else "never"
        faces = mode == "always" or (mode == "hero" and cfg.get("layout") == "hero")
        mood_text = visual_mood.sentence(mood or visual_mood.clean(None), drawn=bool(body)) if mixed and not art else ""
        return local_image(prompt, style, out_path, engine=engine, size=size,
                           look="" if mixed else look_text(sheet, style), art=art, seed=seed, steps=steps,
                           faces=faces, register=register or None, mood=mood_text,
                           people=people if people in PEOPLE else None, body=bool(body),
                           drawing=drawing or ""), "local", None
    finally:
        comfy_release()


def _rms_db(path, t0=None, dur=None):
    """RMS level (dBFS) of ``path``'s sound, mixed to mono — from ``t0`` for ``dur`` s, else the whole file. None
    when it cannot be read or is silent."""
    import math
    import numpy as np
    cmd = ["ffmpeg", "-v", "error"]
    if t0 is not None:
        cmd += ["-ss", f"{max(0.0, float(t0)):.3f}"]
    cmd += ["-i", path]
    if dur:
        cmd += ["-t", f"{float(dur):.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        a = np.frombuffer(r.stdout, dtype=np.float32).astype(np.float64)
    except Exception:
        return None
    if a.size < 800:          # under 50 ms: nothing to measure
        return None
    ms = float(np.mean(a * a))
    return 10.0 * math.log10(ms) if ms > 1e-10 else None


_SFX_RMS = {}


def sfx_gain(clip_path, t):
    """The whoosh's gain (dB) for a picture at ``t`` s of ``clip_path`` (5-oct-2026, decision 3): the whoosh plays
    SFX_UNDER_VOICE_DB under the voice heard as it passes — the quieter of its own window (the measure of the sound
    study of 4-oct-2026) and that window 0.25 s wider on each side, so it is never louder than that (on the demo of
    clip 1 the wider window alone left it 8 dB under) — within SFX_GAIN_RANGE; SFX_GAIN_DB when nothing can be read."""
    own = _SFX_RMS.get(SFX_PATH)
    if own is None:
        own = _rms_db(SFX_PATH)
        if own is not None:
            _SFX_RMS[SFX_PATH] = own
    w0 = float(t) - SFX_LEAD
    levels = [v for v in (_rms_db(clip_path, max(0.0, w0), 0.55 + min(0.0, w0)),
                          _rms_db(clip_path, max(0.0, w0 - 0.25), 1.05 + min(0.0, w0 - 0.25))) if v is not None]
    voice = min(levels) if levels else None
    if own is None or voice is None:
        return SFX_GAIN_DB
    lo, hi = SFX_GAIN_RANGE
    return round(max(lo, min(hi, voice - SFX_UNDER_VOICE_DB - own)), 1)


def overlay_items(clip_path, out_path, items, img_dir=None):
    """Cut already-made B-roll images into ``clip_path``. Each item: t, layout
    ("rise" | "full"), size / position for "rise", and the image
    as ``_img`` (a path) or ``image`` (a file name in ``img_dir``). Used by
    ``add_broll`` and by a restyle, which re-applies the same media on the
    new edit."""
    import viral_fx
    info = viral_fx._probe(clip_path)
    w, h, fps = info["w"], info["h"], int(round(info.get("fps") or 30))
    tmp = tempfile.mkdtemp(prefix="broll_ov_")
    try:
        layers = []
        for k, it in enumerate(items):
            folder = os.path.join(tmp, f"card_{k}")
            os.makedirs(folder)
            src = it.get("_img") or (os.path.join(img_dir, it["image"]) if img_dir and it.get("image") else None)
            if not src or not os.path.exists(src):
                continue
            rise = it.get("layout") in ("rise", "card")
            hero = it.get("layout") == "hero"
            screen = it.get("source") == "screen"      # the source's own picture: up for as long as the source had it
            try:
                dur = float(it.get("dur") or (RISE_DUR if rise else SEG_DUR))
            except (TypeError, ValueError):
                dur = RISE_DUR if rise else SEG_DUR
            dur = max(0.4 if it.get("seq") else 1.0, min(SCREEN_DUR_MAX if screen else 4.0, dur))
            grade = it.get("grade") if _grade_params(it.get("grade")) else "off"
            if it.get("layout") == "object":
                pattern, x, y, cvh = _object_frames(src, folder, fps, dur, w, h, int(it.get("size") or OBJECT_SIZE))
                # it rises from below and settles (the overlay's y expression of the rising cards, canvas centres)
                ye = y + cvh / 2
                layers.append({"t": it["t"], "dur": dur, "rise": True, "object": True, "pattern": pattern, "x": x,
                               "y": (ye + h * OBJECT_RISE_FROM, ye, 0, cvh, OBJECT_RISE)})
            elif it.get("layout") == "split":
                pattern = _split_frames(src, folder, fps, dur, w, h)
                layers.append({"t": it["t"], "dur": dur, "rise": False, "split": True, "pattern": pattern, "x": 0,
                               "y": h // 2})
            elif hero:
                fx = it.get("fx") if it.get("fx") in FX_KINDS else None
                pattern = _hero_frames(src, folder, fps, dur, w, h, grade=grade, fx=fx, marks=it.get("marks"))
                layers.append({"t": it["t"], "dur": dur, "rise": False, "hero": True, "pattern": pattern, "x": 0, "y": 0})
            elif rise:
                pattern, x, motion = _rise_frames(src, folder, fps, dur, w, h, int(it.get("size") or RISE_SIZE),
                                                  it.get("position") or "below", _free_y(it.get("y")),
                                                  it.get("enter") if it.get("enter") in ENTER_MODES else "rise",
                                                  it.get("zoom") if it.get("zoom") in ZOOM_LEVELS else "soft",
                                                  it.get("border") if it.get("border") in BORDERS else "soft",
                                                  look=it.get("look"), label=it.get("label"), grade=grade,
                                                  fx=it.get("fx") if it.get("fx") in FX_KINDS else None,
                                                  min_aspect=SCREEN_ASPECT_MIN if screen else None)
                layers.append({"t": it["t"], "dur": dur, "rise": True, "pattern": pattern, "x": x, "y": motion})
            else:
                pattern, x, y, _full = _card_frames(src, folder, fps, dur, w, h,
                                                    it.get("zoom") if it.get("zoom") in ZOOM_LEVELS else "soft",
                                                    it.get("border") if it.get("border") in BORDERS else "soft")
                layers.append({"t": it["t"], "dur": dur, "rise": False, "pattern": pattern, "x": x, "y": y})
        if not layers:
            raise RuntimeError("no B-roll image to cut in")
        big = [ly for ly in layers if not ly["rise"] and not ly.get("hero") and not ly.get("split")]
        if big:
            # Behind a big card, the podcast keeps playing — blurred and dimmed,
            # so the photo reads as "in front of" the conversation. A small
            # "rise" card leaves the podcast untouched, and so does a hero: it
            # covers the frame and dissolves to the sharp face.
            windows = "+".join(f"between(t,{ly['t']:.3f},{ly['t'] + ly['dur']:.3f})" for ly in big)
            graph = [f"[0:v]boxblur=22:2:enable='{windows}',"
                     f"eq=brightness=-0.10:saturation=0.8:enable='{windows}'[bg]"]
        else:
            graph = ["[0:v]null[bg]"]
        cur, inputs = "[bg]", []
        splits = [ly for ly in layers if ly.get("split")]
        if splits:
            # A split screen: the speaker's frame moved up into the top half while the thing fills the bottom one.
            windows = "+".join(f"between(t,{ly['t']:.3f},{ly['t'] + ly['dur']:.3f})" for ly in splits)
            graph += [f"{cur}split=2[sa][sb]", f"[sb]crop=iw:ih/2:0:{int(h * SPLIT_FACE_FROM)}[stop]",
                      f"[sa][stop]overlay=0:0:enable='{windows}'[bgs]"]
            cur = "[bgs]"
        for k, ly in enumerate(layers):
            inputs += ["-itsoffset", f"{ly['t']:.3f}", "-framerate", str(fps), "-i", ly["pattern"]]
            win = f"between(t,{ly['t']:.3f},{ly['t'] + ly['dur']:.3f})"
            if ly["rise"]:
                ys, ye, drift, cvh = ly["y"][:4]
                rise_s = ly["y"][4] if len(ly["y"]) > 4 else RISE_IN
                # Canvas centre: eases up from under the frame (cubic; a premium card only rises a few px while
                # it fades in), then drifts up ``drift`` px while on screen (0: it stays put).
                y = (f"'{ys:.1f}+({ye:.1f}-{ys:.1f})*(1-pow(1-clip((t-{ly['t']:.3f})/{rise_s},0,1),3))"
                     f"-{drift}*clip((t-{ly['t']:.3f}-{rise_s})/{ly['dur'] - rise_s:.3f},0,1)-{cvh / 2:.1f}'")
                graph.append(f"{cur}[{k + 1}:v]overlay=x={ly['x']}:y={y}:eval=frame:eof_action=pass:"
                             f"enable='{win}'[b{k}]")
            else:
                graph.append(f"{cur}[{k + 1}:v]overlay={ly['x']}:{ly['y']}:eof_action=pass:enable='{win}'[b{k}]")
            cur = f"[b{k}]"
        graph[-1] = graph[-1][:graph[-1].rfind("[")] + "[v]"
        # An intermediate layer: the hook and the captions re-encode it (ffmpeg_utils.layer_encode_args).
        enc = layer_encode_args(["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"])
        # The whoosh of the first full-screen drawing (item "sfx"): mixed into the clip's own track
        # SFX_UNDER_VOICE_DB under the voice around it (sfx_gain), then the mix is normalised again
        # (LOUDNORM_FILTER: -14 LUFS, true peak -2 dBTP, as background_music.py; 5-oct-2026) — the audio is
        # re-encoded (AAC, 48 kHz) in this pass only; without a whoosh it is copied as always.
        sfx_at = [float(it["t"]) for it in items if it.get("sfx") and it.get("layout") == "hero"
                  and any(ly.get("hero") and abs(ly["t"] - float(it["t"])) < 1e-6 for ly in layers)]
        audio_in, audio_graph = [], []
        if sfx_at and os.path.exists(SFX_PATH):
            for j, t in enumerate(sfx_at):
                audio_in += ["-i", SFX_PATH]
                ms = max(0, int(round((t - SFX_LEAD) * 1000)))
                audio_graph.append(f"[{1 + len(layers) + j}:a]adelay={ms}|{ms},"
                                   f"volume={sfx_gain(clip_path, t):g}dB[sx{j}]")
            norm = (f",{LOUDNORM_FILTER},aresample=48000"
                    if os.environ.get("AUDIO_NORMALIZE", "1").strip() != "0" else "")
            audio_graph.append(f"[0:a]{''.join(f'[sx{j}]' for j in range(len(sfx_at)))}"
                               f"amix=inputs={len(sfx_at) + 1}:duration=first:normalize=0{norm}[a]")

        def cut(with_sfx):
            if with_sfx:
                cmd = ["ffmpeg", "-y", "-v", "error", "-i", clip_path, *inputs, *audio_in,
                       "-filter_complex", ";".join(graph + audio_graph), "-map", "[v]", "-map", "[a]", *enc,
                       "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out_path]
            else:
                cmd = ["ffmpeg", "-y", "-v", "error", "-i", clip_path, *inputs, "-filter_complex", ";".join(graph),
                       "-map", "[v]", "-map", "0:a?", *enc, "-c:a", "copy", "-movflags", "+faststart", out_path]
            subprocess.run(cmd, check=True)

        if audio_graph:
            try:
                cut(True)
            except subprocess.CalledProcessError:
                print("   ⚠️ B-roll sound: the mix failed (no audio track?) — cut in without the whoosh.")
                cut(False)
        else:
            cut(False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sources(api_key=None, style="photo", engine="zimage"):
    """For the profile editor's "test" button: does Claude (subscription)
    answer, and does the local GPU (ComfyUI) make an image? Never raises.
    ``api_key`` / ``engine`` are accepted for the endpoint's sake and ignored:
    images are made on this PC only."""
    out = {"claude": None, "local": None}
    tmp = tempfile.mkdtemp(prefix="broll_test_")
    try:
        if claude_ready():
            try:
                t0 = time.time()
                r = claude_json('In the sentence "we gave the mice psilocybin", which word names a concrete '
                                'substance? Answer as JSON.',
                                {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]},
                                timeout=120)
                out["claude"] = f"ok ({time.time() - t0:.0f} s, '{r.get('word')}')"
            except Exception as e:
                out["claude"] = "error: " + str(e)[:220]
        else:
            out["claude"] = "not set up"
        if comfy_available():
            try:
                t0 = time.time()
                local_image("A close-up of fresh green kratom leaves on a wooden table.", style,
                            os.path.join(tmp, "l.jpg"))
                out["local"] = f"ok ({time.time() - t0:.0f} s)"
            except Exception as e:
                out["local"] = "error: " + str(e)[:220]
            finally:
                comfy_release()
        else:
            out["local"] = "offline"
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
