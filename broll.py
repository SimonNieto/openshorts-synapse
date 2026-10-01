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

from ffmpeg_utils import layer_encode_args

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
    "less": {"pace": "Be SELECTIVE: one or two images per 30 s of clip, plus the hero — only the moments where a picture "
                     "says what the voice alone cannot.",
             "names": "Show something the speaker names only when it is a case, a place or an object at real scale that "
                      "carries the point (skip passing mentions):"},
    "normal": {"pace": "An image only when it adds meaning the voice alone does not give: two to four per 30 s of clip, "
                       "plus the hero. The face alone is fine; a picture that merely repeats the noun is not.",
               "names": "Show something the speaker names only when it is a case, a place or an object at real scale that "
                        "carries the point (skip passing mentions):"},
    "more": {"pace": "An image only when it adds meaning the voice alone does not give: three or four per 30 s of clip, "
                     "plus the hero. A picture that merely repeats the noun is not worth the cut.",
             "names": "Show something the speaker names when it is a case, a place or an object at real scale that "
                      "carries the point, and the strongest passing mentions:"},
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
HERO_DUR_MIN, HERO_DUR_MAX = 2.5, 3.5   # s on screen: long enough to read as a shot, short enough to come back to the face


def _knob(name, default):
    """A matter-of-taste value, settable from the env (BROLL_<NAME>) without a code change."""
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


HERO_FADE = _knob("BROLL_HERO_FADE", 0.35)          # s: crossfade in and out (a pop reads as a sticker, a dissolve as a cut)
HERO_PUSH = _knob("BROLL_HERO_PUSH", 1.06)          # push-in over the time on screen: 6 % is felt, not seen
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
# A sound when the hero arrives (profile broll.sfx): a soft whoosh made by assets/sfx/make_sfx.py (ours, no
# licence), mixed under the voice. -18 dB on a -6 dBFS peak: heard as air moving, never as an effect.
SFX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sfx", "whoosh_soft.wav")
SFX_GAIN_DB = _knob("BROLL_SFX_DB", -18.0)
SFX_LEAD = 0.12       # s before the picture: the sound announces it
HERO_RULE = """HERO IMAGE: one image of the set is shown FULL SCREEN for about 3 s: the clip's poster, the frame a cold
viewer stops on. First list "hero_options": THREE different candidate concepts (each: "anchor", the verbatim words
where it would land; "picture", the scene in one sentence; "why", what it proves) — take them from the episode's
HERO IDEAS when one fits, or find better — then pick the strongest (clear at a glance, specific to this clip, felt,
never a cliché) and mark that moment "hero": true (one at most) with "hero_why" (one sentence). A hero is a concrete
scene (an example, a consequence, a place, an action), shot wide or medium, never a diagram, never in the hook's
first seconds, never on the punchline; make its image_prompt a complete scene with depth (foreground, subject,
background): it fills a phone screen."""
STOPWORDS = set("""a an the of to in on at by for with from and or but so as is are was were be been it its this that
these those he she they we you i me him her them us my your his their our there here then than very just not no
some any all one two three""".split())

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
# "auto" style in the "mixed" layout: one photographic look for the whole clip (the reference shorts never mix a
# comic, a 3D render and a photo); neon stays for what no camera can see.
STYLE_RULE_PREMIUM = """
- "style": how to show it, one of:
  "photo"     - the default, for everything that exists in the physical world: anonymous people, places, objects,
                plants, food, animals, tools, events, a scene with action;
  "cinematic" - the same when the moment is dramatic, dark or tense (a night scene, a danger, a fight) - never for
                a patient, an illness, a disability or a death (use "photo" there).
  The microscopic or the invisible (neurons, receptors, molecules, hormones, DNA, cells, brain activity) is "photo"
  too: a real micrograph or lab photograph in real light, never glowing neon lines.
  Nothing else (no neon, no drawing, no comic, no diagram, no 3D render, no vintage): the images of a clip are
  one series shot with one camera."""
PREMIUM_STYLES = ("photo", "cinematic")
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "thesis": {"type": "string"},
        "arc": {"type": "string"},
        "visual_argument": {"type": "string"},
        "style_sheet": {"type": "object", "properties": {k: {"type": "string"} for k in
                        ("palette", "light", "era", "camera", "mood", "cast")}},
        "moments": {"type": "array", "items": {
            "type": "object",
            "properties": {"anchor": {"type": "string"}, "time": {"type": "number"}, "idea": {"type": "string"}, "said": {"type": "string"},
                           "subject": {"type": "string"},
                           "shot": {"type": "string", "enum": ["wide", "medium", "close", "macro", "schematic"]},
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
GROUNDING_RULE = """STICK TO THE CONTEXT, not to the noun. Before writing an image, read the whole sentence around the
anchor and the words just before it (resolve "he", "it", "that thing" from them and from the brief), then:
- keep EVERY specific the speaker gives and put it in the image_prompt: the number or quantity
  ("two gallons of water" -> two big water jugs, not "water"), the place ("in Toronto" -> the CN Tower skyline), the era
  ("in the 80s" -> 1980s look), the kind of person, the action, the tone (a danger, a relief, a fight);
- show what the sentence SAYS about the thing (its state, its effect, its size), not just the thing: "the knife went
  through the bone" -> a blade against a bone, not a kitchen knife on a table;
- if the sentence is a claim, a comparison or a story beat, show that beat in one clear scene;
- "said": the sentence (about 8-15 words, verbatim) the image illustrates. If you cannot tie the image to that sentence,
  drop the moment.
- TONE: keep the mood of the story. For a patient, an illness, a disability or a death show warmth and dignity - a
  person with expressive eyes in soft light, hands, a calmly lit hospital room - never a menacing, horror-like or
  dehumanised picture (no black silhouette with glowing eyes, no faceless figure in the dark, no harsh shadows on a
  face). A picture must not frighten unless the story itself is about fear.
- SOUND-OFF TEST: someone who sees ONLY the picture, then hears "said", must link them within a second. If the link
  needs an explanation, pick a more telling scene (the concrete case, the action, the effect) or drop the moment.
- BE CORRECT: an organ, a tool, an animal, a place must be the right one and look right (the throat is not the lungs,
  a larynx is in the neck); name it precisely in the image_prompt with where it is and what it looks like."""

# The images of a clip are ONE sequence the viewer watches in a row: they must
# tell the clip's story, not repeat one picture.
SET_RULE = """THE SET TELLS THE STORY. The images are seen one after the other: together they must follow the arc
(setup -> claim -> payoff), not repeat one idea.
- VARIETY: no two images with the same main subject AND look ("subject" of each moment: 1-3 words). Three brains in a
  row read as one image shown three times: show the brain once, then the patient, the device, the moment it works.
  Vary the scale too ("shot"): wide scene, medium, close-up, macro, schematic — never the same shot twice in a row.
- HUMAN CASE FIRST: when the clip follows a person, a patient, a group or a real case (see the STORIES), that case
  is the thread of the images: prefer showing it (who, where, doing what) over an abstract picture of the notion.
- CAST: describe that recurring person / place ONCE in "style_sheet"."cast" (age, look, clothes, setting — never a real
  identifiable person) and copy that description word for word into every image_prompt where it appears, so the viewer
  recognises the same person from one image to the next. Leave "cast" empty when nobody recurs."""


# What makes a B-roll read as cheap AI stock on a science channel: the pictures
# every generator draws first. The editor and the art director are told never
# to ask for them (Claude reads a ban fine; the image model only ever gets
# positive prompts), the reviewer marks them down, and the brief's glossary is
# asked for real things instead.
CLICHES = ("a glowing brain, a brain floating in space or in blue light", "neurons or synapses drawn as neon lines",
           "a light bulb for an idea", "a handshake", "pills or capsules on a plain white background",
           "a dark silhouette with glowing eyes", "a holographic screen, a floating interface or a HUD",
           "a head with gears, puzzle pieces, a maze or a chess board for the mind",
           "people grinning at the camera like a stock photo", "a DNA helix glowing on black")
CLICHE_RULE = ("NEVER THE AI CLICHÉ. These pictures are what every generator draws first and what marks a cheap channel; "
               "none of them, whatever the words: " + "; ".join(CLICHES) + """.
- A DETAIL THAT TELLS instead: every picture holds one specific, real-world thing at its true scale, as a documentary
  photographer would find it — the pill bottle on a kitchen counter at 7 am, the patient's hand on the bed rail, the
  stained slice of tissue on a microscope slide, the worn stairs of the named building, a gesture, a texture in macro.
- THE CASE BEFORE THE NOTION: when the speaker tells a case, an example, a place or a person, show THAT in its real
  setting. Show the notion itself only when nothing concrete was said, and then as a real object, instrument or place
  that embodies it (a lab bench, a scan on a lightbox, an archive print), never as a symbol.
- THE INVISIBLE, PHOTOGRAPHED: a neuron, a cell, a molecule, a hormone is shown as a real micrograph or a lab
  photograph in real light (stained tissue under the microscope, a petri dish on the bench, a printed model on a
  desk), never as glowing lines on a dark void.""")
# A picture that would do for any clip about the same noun is not the picture: the editor and the reviewer apply
# the same test, the episode's world (its bible) and the sentence's specifics are where the right one comes from.
SPECIFIC_RULE = ("SPECIFICITY TEST: if the same picture would do for any other clip about the same noun (a generic brain, "
                 "a generic pill, a generic crowd), it is not the picture: take it from the world of THIS episode (its "
                 "places, objects, people, era — the bible's WORLD when given) and the specifics of THIS sentence.")
# The channel's latest pictures (recent_subjects): the editor is told what was just shown so a batch of clips does
# not open on the same picture three times.
RECENT_RULE = ("ALREADY SHOWN by the channel in its latest clips — find another picture of the idea, never one of these "
               "again: {}.")

CLAUDE_SYSTEM ="You are a meticulous short-form video editor. You answer only with the requested JSON."
CLAUDE_SYSTEM_VISION = ("You are a meticulous short-form video editor. The images are attached to the request, in "
                        "order, each right after its file name. Answer only with the requested JSON.")

# Claude's brief: images that carry the IDEA being said, chosen with the
# conversation around the clip and with what is already on screen in view.
# How literal the images are (profile broll.mode).
MODE_RULES = {
    "literal": "Be LITERAL: show exactly the thing named, as a plain picture of it. Two nearby moments may use two "
               "different images.",
    "mixed": ("MIX literal and conceptual images, roughly half and half. Literal: the thing named, plain "
              "(\"salvia\" -> the plant, \"knife\" -> a knife). Conceptual: when the words carry a bigger idea "
              "(a claim, a mechanism, an analogy, a consequence), show that idea in one clear scene. "
              "Alternate them so the edit never feels repetitive."),
    "concept": ("Favour the IDEA over the noun: show what the sentence MEANS in one clear scene (the mechanism, "
                "the consequence, the analogy), and use a plain literal picture only when the word itself is the "
                "point."),
}
CLAUDE_PLAN_PROMPT = """You are the editor of a short-form clip cut from a longer conversation. Add up to {n} B-roll
images. {frame}

FIRST understand the clip inside its episode (the EPISODE BRIEF below: who talks, what the episode is about, the
visual glossary, the real stories told). Then write:
- "thesis": in one sentence, what the viewer must take away from THIS clip;
- "arc": setup -> claim -> payoff of the clip, in a few words each;
- "visual_argument": the ONE thing a viewer must SEE to believe the thesis, in one sentence: a scene, an object at
  its real scale, a gesture — the hero usually shows it. Then plan the set as a documentary sequence that builds
  that argument (where we are, the case, the mechanism, the consequence): no two images make the same point.
Also write "style_sheet": ONE visual direction for the whole set of images of this clip, so they look shot by the
same person on the same day, in plain words a few words long each: "palette" (the 2-4 dominant colours), "light"
(kind and direction of the light), "era" (the period the story is in, or "present day"), "camera" (lens, angle,
grain), "mood". Take them from the topic, the era and the tone of the stories, not from the words of one sentence.
When an EPISODE VISUAL BIBLE is given below, its LOOK is the style_sheet of every clip of the episode: copy its
palette, light and lens, add only this clip's era and mood; take the pictures from its WORLD (the things this
episode really contains), return to its MOTIFS, and never show what its AVOID list names.
The images serve that thesis and that arc — never an isolated word. Typical roles ("role" of each moment):
"concept" (the notion the point rests on, when it is introduced), "example" (the concrete case, with the REAL
details from the stories: place, year, kind of people, study), "consequence" (what it leads to — often the payoff).
When a notion of the visual glossary is shown, draw it exactly as the glossary says (the channel always shows it the
same way).

{pace}
{names}
- substances, plants, drugs, food and drinks ("salvia" -> the plant, "cigar" -> a lit cigar, "coffee", "pills");
- objects, tools, weapons, vehicles, clothes ("knife", "gun", "car", "phone", "syringe");
- places, buildings, landscapes, eras, events; animals; body parts and organs; kinds of people (soldiers, surgeons);
- a mechanism, a number or a scale, an analogy ("like a hike at dawn" -> a mountain trail at sunrise);
- an action or a situation the viewer cannot see in the video.
{mode_rule}
{grounding}
{set_rule}
{cliche_rule}
{specific_rule}
{recent}Never: something already visible in the video (look at the frame sheets), a named real person,
a brand (use a generic equivalent), an abstraction nobody can draw. Aim for {n} images; return fewer only when the clip
truly has nothing concrete to show.

Frame sheets: {sheets} — thumbnails of the clip every 2.5 s, each stamped with its time. Look at them first.

For each image give:
- "anchor": the exact 1-3 words as spoken where the image should land (verbatim from the transcript). The image
  pops up just before the most meaningful of these words (the noun that names the thing: "gallons" in "two gallons of
  water", not "two") is spoken, so choose words whose key word is the one that shows the thing;
- "time": the second the anchor is spoken (from the markers);
- "said": the sentence (about 8-15 words, verbatim) this image illustrates;
- "idea": what this image PROVES or makes felt for the thesis, in one sentence a picture editor would write
  ("the ordeal was real: a dented canteen was all they had"), never what it depicts;
- "subject": the main thing seen, 1-3 words ("brain", "patient in bed", "implant") — two images never share it;
- "shot": wide | medium | close | macro | schematic;
- "notion": only when the image is simply THE usual picture of a notion of the brief's glossary (VISUAL GLOSSARY or
  OTHER NOTIONS, even if the speaker says it in other words), with no detail of this particular case (number, person,
  scene, era): its name exactly as listed. If the image must show a specific case, leave it empty;
- "image_prompt": one or two English sentences describing ONE clear scene that shows that idea, keeping the
  specifics of "said" (number, place, era, who, action, mood): subject, action, setting, light. It must read on a phone at a third of the screen width: one main subject, simple background, no text.{style_rule}
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

REVIEW_FRAME = {
    "small": "Each image below will appear for about {dur:.1f} s, small (about a third of a phone screen's width),",
    "mixed": "Each image below will appear as a wide card above the speaker's head (about 60 % of a phone screen's width)\n"
             "for 2-3.5 s, or full screen for about 3 s when marked HERO,",
}
REVIEW_PROMPT = """{frame}
while the speaker says the quoted words.

STEP 1 - LOOK FIRST. For every image, before you consider what it was meant to show, write "seen": one plain sentence
of what is really in it - the main subject, HOW MANY of it (count them), the setting, the era or look, any lettering,
symbol or logo (say if letters are garbled), anything odd (extra fingers, a distorted face). Describe only the pixels.

STEP 2 - THEN JUDGE. Only now read what each image was meant to show and compare it with what you wrote in "seen" (listed in the order they appear on screen):
{items}
Judge strictly: does it show the IDEA at a glance at that size? Is it free of text or garbled letters, of deformed
hands or faces, of anything off-topic or confusing? Fit to the context counts as much as clarity: the image must show
what the sentence SAYS about the thing (the number, the place, the era, the action, the mood), not only the noun. A
generic picture of the noun that ignores what was said, or a number / era that does not match, scores 3 at most.
A picture that looks frightening, menacing or cold for a sympathetic subject (a patient, an illness, a disability, a
death) - a dark silhouette, glowing eyes, a faceless figure - scores 2 at most, even if it shows the idea.
SOUND-OFF TEST: from the picture alone, would a viewer who then hears the quoted words link them within a second? If
the link needs explaining, 3 at most.
SPECIFICITY TEST: a picture that would do for any other clip about the same noun (a generic brain, a generic pill, a
generic crowd) scores 3 at most; its better_prompt takes the thing from this episode's world and this sentence's
specifics (the place, the object at its scale, the gesture, the era).
WRONG FACTS: the wrong organ, tool, animal or place (lungs for a throat, a random building for a named landmark), or
a key detail that contradicts what is said, scores 2 at most — however pretty. Judge them against the quoted words
and the EPISODE FACTS when given, never against your own idea of what is plausible: a surprising scene the speaker
tells (a cage on a famous lawn) is a true scene, and the picture that shows it is right.
STOCK OR CLICHÉ: a picture that reads as AI stock on a science channel — """ + "; ".join(CLICHES) + """ — scores 3 at
most, and its better_prompt shows the concrete case or the thing at its real scale instead.
THE SET: the images are seen in a row. Compare them with each other: when one looks like an earlier one (same main
subject, same framing, same look), the later one scores 3 at most and its better_prompt shows another side of the
idea (the person, the object, the effect, another scale).
STEP 3 - THE LOOK. For each image, "look" 1-5, as a photo editor rates a still for a documentary channel: the
light (a real source with a direction and a quality, not flat, not a glow), the composition (one subject, air
around it, readable at the size it is shown), the coherence of palette and light with the other images of the
set, the artefacts (hands, faces, lettering, melted objects), the stock or AI-cliché feel, the legibility at its
size. 5 = a still a magazine would print, 4 = good, 3 = correct but flat, 2 or 1 = artefacts, stock or unreadable.
A face, when one shows, must be natural and in focus with normal eyes, teeth and hands;
a deformed, waxy or doubled face scores look 2 at most.
For each image, by "file": "seen", "score" 1-5 (5 = instantly clear and on point, 4 = good, 3 = acceptable, 2 or 1 =
weak, wrong or confusing), "look" 1-5, "problem" (a few words, empty if none) and "better_prompt": an English image
prompt that would fix it (one clear scene, one main subject, no text) - empty when the score is 4 or 5 AND the
look is 4 or 5. When the image's own prompt is given below as ART-DIRECTED, write better_prompt in that same
grammar, 80 to 120 words, in this order: subject and action, setting, composition for its frame, lens and point
of view, light (source, direction, quality), palette and grade, material and detail, mood - keep what worked,
change what failed, state only what IS in the frame."""
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"reviews": {"type": "array", "items": {
        "type": "object",
        "properties": {"file": {"type": "string"}, "seen": {"type": "string"}, "score": {"type": "integer"},
                       "look": {"type": "integer"}, "problem": {"type": "string"}, "better_prompt": {"type": "string"}},
        "required": ["file", "seen", "score", "look"]}}},
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
        if all(abs(m["t"] - k["t"]) >= gap and not same(m, k) for k in kept):
            kept.append(m)
        if len(kept) == n:
            break
    return sorted(kept, key=lambda m: m["t"])


# The "hero" of a "mixed" clip: the one image shown full screen (~3 s). Chosen
# here and not only by the planner, so a Gemini plan gets one too and a planner's
# pick that breaks the timing rules is overruled.
HERO_ROLE = {"example": 2.0, "consequence": 2.0, "concept": 0.0}
HERO_SHOT = {"wide": 1.5, "medium": 1.0, "close": 0.5, "macro": 0.0, "schematic": -1.0}
HERO_STYLE = {"diagram": -2.0, "drawing": -1.0, "neon": -1.0, "comic": -1.0, "3d": -0.5}
HERO_MIN_SCORE = 1.5   # a plain photo of a concept, close-up, just makes it; a schematic or a diagram never does


def hero_dur(m):
    """Time on screen of the hero: its sentence (``dur``) plus the crossfade, within HERO_DUR_MIN..MAX."""
    return round(min(HERO_DUR_MAX, max(HERO_DUR_MIN, float(m.get("dur") or 0) + HERO_FADE)), 2)


def hero_fits(m, duration, avoid, head=HEAD_FREE, block=()):
    """A hero never runs into the hook's seconds, the last TAIL_FREE s, within
    1.2 s of the punchline, or a ``block`` stretch (the source's own picture) —
    on its whole time on screen, not only its first frame."""
    t, d = m["t"], hero_dur(m)
    if t < head or t + d > duration - TAIL_FREE:
        return False
    return (all(t + d <= a - 1.2 or t >= a + 1.2 for a in avoid)
            and all(t + d <= a or t >= b for a, b in block))


def pick_hero(moments, duration, avoid, head=HEAD_FREE, block=()):
    """Index of the moment shown full screen, or None: a concrete scene (an example
    or a consequence, a wide or medium shot, a photographic style) that fits the
    timing rules. The planner's own "hero" counts for a lot, a moment in the second
    part of the clip (the payoff) a little; a tie goes to the later one. None when
    no moment reads well on a whole phone screen (a diagram, a schematic)."""
    best, best_score = None, 0.0
    for i, m in enumerate(moments):
        if not hero_fits(m, duration, avoid, head, block) or m.get("notion"):
            continue
        score = 1.0 + HERO_ROLE.get(m.get("role") or "", 0.0) + HERO_SHOT.get(m.get("shot") or "", 0.5)
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


def _sheet_with_bible(sheet):
    """The clip's style sheet with the episode's look laid over it (palette, light, camera): the editor keeps
    only the era and the mood of its clip. The sheet as it is without a bible."""
    import ai_brain
    look = (ai_brain.EPISODE_BIBLE or {}).get("look") or {}
    if not look:
        return sheet
    out = dict(sheet or {})
    for k_sheet, k_look in (("palette", "palette"), ("light", "light"), ("camera", "lens")):
        if look.get(k_look):
            out[k_sheet] = _short_field(re.sub(r"\s+", " ", look[k_look]).strip(" ."))
    if not out.get("mood") and look.get("mood"):
        out["mood"] = _short_field(look["mood"], 70)
    return out or None


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


def _parse_moments(data, words, n, avoid, gap=MIN_GAP, dur_range=None, tail=None, head=HEAD_FREE, block=()):
    """The planner's answer -> moments that land on a real spoken word, in
    the allowed window, spaced out. Anything that does not check out is
    dropped, whoever the planner was. ``dur_range``: (min, max) s on screen
    (the "mixed" layout's cards stay longer than the historical ones);
    ``tail``: seconds at the end of the clip no image may run into; ``head``:
    the first seconds left to the face (the hook's); ``block``: (from, to)
    stretches no image may start in or run into (the source's own picture)."""
    duration = words[-1]["end"]
    lo, hi = dur_range or (DUR_MIN, DUR_MAX)
    moments = []
    sheet = _clean_sheet((data or {}).get("style_sheet"))
    for m in (data or {}).get("moments") or []:
        try:
            near = float(m.get("time", 0))
        except (TypeError, ValueError):
            continue
        i = _find_anchor(words, m.get("anchor"), near)
        if i is None:
            continue
        n_tok = len(_tokens(m.get("anchor")))
        k = _key_index(words, i, n_tok)
        t = max(0.0, words[k]["start"] - KEY_LEAD)
        if not _allowed(t, duration, avoid, head, block):
            continue
        dur = _moment_dur(words, k, t, duration, lo, hi)
        if tail:
            dur = round(min(dur, duration - tail - t), 2)
            if dur < lo:
                continue                       # it would run into the last seconds: the face keeps them
        for a, _b in block:
            if t < a:
                dur = round(min(dur, a - DUR_NEXT_GAP - t), 2)   # it leaves before the source's picture comes up
        if dur < lo:
            continue
        moments.append({"t": t, "anchor": " ".join(w["text"] for w in words[i:i + n_tok]),
                        "key": words[k]["text"],
                        "query": str(m.get("search_query") or m.get("anchor"))[:60],
                        "prompt": str(m.get("image_prompt") or m.get("anchor"))[:PROMPT_MAX],
                        "idea": str(m.get("idea") or "")[:200],
                        "said": str(m.get("said") or "")[:200],
                        "subject": str(m.get("subject") or "")[:40],
                        "shot": m.get("shot") if m.get("shot") in SHOTS else None,
                        "style": m.get("style") if m.get("style") in STYLES else None,
                        "role": m.get("role") if m.get("role") in ("concept", "example", "consequence") else None,
                        "notion": str(m.get("notion") or "")[:80],
                        "real_photo": bool(m.get("real_photo")) and bool(str(m.get("search_query") or "").strip()),
                        "hero": bool(m.get("hero")),
                        "hero_why": re.sub(r"\s+", " ", str(m.get("hero_why") or "")).strip()[:200],
                        "dur": dur,
                        "sheet": sheet,
                        "score": 1.0})
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


def claude_json(prompt, schema, timeout=240, attach=None, stage=None, effort=None, model=None, system=None):
    """One Claude call through ai_brain (the job-wide Claude-first switch): a
    quota / session limit switches Claude off for the rest of the job.
    ``model``: the profile's model for the B-roll by default; ``system``: the
    editor's voice by default (the art director has its own)."""
    import ai_brain
    model = model or ai_brain.stage_model("broll")
    if stage:
        ai_brain.say(f"Claude · {model}", stage)
    try:
        return ai_brain.claude_json(prompt, schema, timeout=timeout, attach=attach, effort=effort, model=model,
                                    system=system or (CLAUDE_SYSTEM_VISION if attach else CLAUDE_SYSTEM))
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
        if not ai_brain._term_matches(g["term"], own):
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
                     dur_range=None, gap_min=0.0, tail=None, head=HEAD_FREE, block=()):
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
    recent = recent_subjects()
    pace_of = DENSITY_MIXED if hero else DENSITY      # the mixed layout has its own, selective pace
    common = dict(n=n, avoid=avoid_txt, sheets=", ".join(os.path.basename(p) for p in sheets or []) or "none",
                  frame=FRAME_TEXT["mixed" if hero else "small"],
                  style_rule=((STYLE_RULE_PREMIUM if hero else STYLE_RULE) if auto_style else ""),
                  mode_rule=MODE_RULES.get(mode, MODE_RULES["mixed"]),
                  title=title or "-",
                  hook=clip.get("viral_hook_text") or "-", before=before or "-", after=after or "-",
                  brief=brief or "(no brief for this video)", bible=_bible_block(), text=_numbered_text(words)[:6000],
                  grounding=GROUNDING_RULE, set_rule=SET_RULE, cliche_rule=CLICHE_RULE, specific_rule=SPECIFIC_RULE,
                  recent=(RECENT_RULE.format("; ".join(recent)) + "\n") if recent else "",
                  pace=pace_of[density]["pace"], names=pace_of[density]["names"],
                  gap=gap)
    prompt = CLAUDE_PLAN_PROMPT.format(lo=head, hi=duration - TAIL_FREE - SEG_DUR, **common)
    schema, attach, shots_dir = PLAN_SCHEMA, list(sheets or []), None
    if hero:
        prompt += "\n" + HERO_RULE
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
    moments = _parse_moments(data, words, n, avoid, gap, dur_range, tail, head, block)
    for m in moments:
        m["sheet"] = _sheet_with_bible(m.get("sheet"))
        if m.get("hero") and m.get("notion"):
            # The hero is THIS clip's picture, never the channel's usual picture of a notion: the editor's pick
            # stays the hero (pick_hero refuses a notion), made for this clip and not kept for the others.
            print(f"   🎯 Hero \"{m['anchor']}\" is also notion \"{m['notion']}\": made for this clip, not from the library.")
            m["notion"] = ""
    apply_notions(moments, ai_brain.EPISODE_BRIEF, f"{before} {clip_text} {after}")
    thesis = str((data or {}).get("thesis") or "")[:300]
    if thesis:
        print(f"   💡 Clip thesis: {thesis}")
    argument = re.sub(r"\s+", " ", str((data or {}).get("visual_argument") or "")).strip()[:300]
    if argument:
        print(f"   👁️ Visual argument: {argument}")
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
    for m in moments:
        m["thesis"] = thesis
        m["argument"] = argument
        m["hero_options"] = options
    return moments


# --- the art director (B-roll v2, profile-less: plus.BROLL["art_director"]) ---------------------------
# The editor (plan_with_claude) decides WHAT each picture shows and WHEN; a second
# call, the director of photography, writes the prompt the image model paints
# from — for the whole set at once, so every picture shares one light and one
# palette, in a fixed grammar the model reads best: subject and action, setting,
# composition for its frame, lens, light, palette, material, mood. 80-120 words,
# stated in the positive (at cfg 1.0 a negation does nothing).
ART_MIN_WORDS, ART_MAX_WORDS = 40, 220   # an answer outside this is not a prompt: the editor's draft stays
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
paint from, for EVERY picture of the set at once, so they look shot by one photographer on one day.

THE CHANNEL'S LOOK (every picture of every clip, it always wins): {house}
{family}{bible}THIS CLIP'S STYLE SHEET (the editor's; keep what agrees with the channel's look): {sheet}
THE CLIP: title "{title}"; thesis: {thesis}{argument}
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
5. LIGHT: its source, its direction and its quality (window light from the left, late sun from behind, one
   practical lamp, overcast sky...).
6. PALETTE AND GRADE: the channel's colours, said in the scene's own things (teal shadow on the wall, amber rim
   light on the hair...).
7. MATERIAL AND DETAIL: textures and surfaces, and the one small true detail that proves the place is real.
8. MOOD: two or three words.

RULES
- One series: the same direction and quality of light, the same palette and grade in every prompt of the set.
  Vary the shots (wide, medium, close, macro) so no two pictures look alike; the HERO is the widest and most
  cinematic frame of the set.
- THE HERO is the clip's poster: one unforgettable frame that proves the visual argument. Spend your best sentences
  on it: a real place, a real scale, a human presence or a telling object, depth, the light of the episode.
- Describe what IS in the frame, never what is not: the image model ignores negations ("no text", "without
  people" do nothing). Say "a bare plaster wall", not "no poster on the wall".
- Photographic, real-world vocabulary: a documentary still. The style note of a picture is the editor's hint;
  when it fights the channel's look, the channel's look wins (a microscopic subject becomes a macro photograph in
  real light, never a glowing illustration).
- Keep every fact the editor gives, the glossary's way of drawing a notion, and the subject of each picture.
- {cliche}
  When the editor's draft or a glossary line is one of these clichés, keep its subject and shoot it as a real
  thing at its true scale in a real place.
- Nothing written anywhere in the scene (signs, screens, pages and labels show plain surfaces).
- {faces} Nobody real and recognisable, ever.

Return JSON: {{"prompts": [{{"k": 0, "prompt": "..."}}, ...]}} with the "k" of every picture above."""
ART_SCHEMA = {
    "type": "object",
    "properties": {"prompts": {"type": "array", "items": {
        "type": "object",
        "properties": {"k": {"type": "integer"}, "prompt": {"type": "string"}},
        "required": ["k", "prompt"]}},
                   "family": {"type": "string", "enum": ["cinematic_photo", "editorial_photo", "scientific_dark", "archive"]}},
    "required": ["prompts"],
}

# --- style families (B-roll v2, "mixed" layout): one photographic recipe per clip --------------------
# In the mixed layout the eight STYLES above give way to four photographic
# families, each a crafted block (lens, film, light, grade) that follows every
# prompt of the clip. One family per clip (plus.BROLL["style_family"]: "auto" =
# the art director picks it, else its name); "neon" is gone from that layout:
# the invisible is a macro photograph in real light.
FAMILIES = {
    "cinematic_photo": ("Cinematic documentary still: 35 mm full-frame camera, Kodak Vision3 500T look, natural and "
                        "practical light with one soft key, teal shadows and amber highlights, fine film grain, shallow "
                        "depth of field, true skin tones, air around the subject."),
    "editorial_photo": ("Editorial magazine photograph: 50 mm lens, soft daylight from a window or an overcast sky, clean "
                        "neutral palette with a warm tint, fine grain, medium depth of field, honest and composed, the "
                        "still that runs full page in a Sunday magazine."),
    "scientific_dark": ("Scientific macro photograph in real light on a dark background: a lab bench or a microscope stage "
                        "lit by one small lamp, 100 mm macro lens, shallow focus on stained tissue, glass, metal or a "
                        "printed model, teal shadows and amber highlights, fine grain, a research institute's own "
                        "photographer."),
    "archive": ("Archive print from the era of the story: silver-gelatin black and white or faded Ektachrome colour, "
                "period lens and film grain, slight vignette, as found in a newspaper's archive, the time it shows "
                "unmistakable."),
}
FAMILY_DEFAULT = "cinematic_photo"
FAMILY_CHOICE = """THE STYLE FAMILY: choose ONE for the whole clip and return its name in "family":
- "cinematic_photo" (the default, when in doubt): the channel's usual still, for any present-day story;
- "editorial_photo": calm, human, daylight stories — a home, a street, a consultation, a meal, a conversation;
- "scientific_dark": ONLY when most pictures of the set are microscopic or laboratory subjects AND the glossary
  draws them as lab or microscope views;
- "archive": ONLY when the story happens in the past (the style sheet's era is not present day).
Every prompt of the set then obeys that family's lens, film, light and grade:
""" + "\n".join(f'- "{k}": {v}' for k, v in FAMILIES.items())
# The editor's per-picture style, in the mixed layout, is a tone the art director reads, not a look.
STYLE_TONE = {"photo": "a plain documentary moment", "cinematic": "a dramatic, dark or tense moment",
              "neon": "a microscopic or invisible subject: a real micrograph or lab photograph"}


def family_text(family):
    """The art director's family section: a fixed family, the choice, or nothing (historical layouts)."""
    if family is None:
        return ""
    if family in FAMILIES:
        return f"THE STYLE FAMILY of this clip (its lens, film, light and grade; every prompt obeys it): {FAMILIES[family]}\n"
    return FAMILY_CHOICE + "\n"



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


def _art_prompt(moments, clip, house, mixed=True, rise=False, auto_style=True, style="photo", clip_text="",
                family=None, faces="never"):
    """The art director's request for the whole set of one clip. ``family``: None (historical layouts: the
    STYLES are the notes), "auto" (the director chooses one) or a FAMILIES name (fixed)."""
    sheet = next((m.get("sheet") for m in moments if m.get("sheet")), None)
    sheet_txt = "; ".join(f"{k}: {v}" for k, v in (sheet or {}).items()) or "none"
    thesis = next((m.get("thesis") for m in moments if m.get("thesis")), "") or "-"
    argument = next((m.get("argument") for m in moments if m.get("argument")), "")
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
        lines.append(f"  the editor's draft: {m.get('prompt') or '-'}")
        if family is None:
            lines.append(f"  style note: {STYLES.get(m_style, STYLES['photo'])}")
        else:
            lines.append(f"  tone: {STYLE_TONE.get(m_style, STYLE_TONE['photo'])}")
    return ART_PROMPT.format(house=house or "cinematic documentary photograph", sheet=sheet_txt, cliche=CLICHE_RULE,
                             family=family_text(family), bible=_bible_block(),
                             title=clip.get("video_title_for_youtube_short") or "-", thesis=thesis,
                             argument=(f"; the visual argument (what the viewer must SEE to believe it, the hero's job): "
                                       f"{argument}") if argument else "",
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
    facts = {re.sub(r"[,.]", "", n) for n in _NUM_RE.findall(text)}
    for sentence in re.split(r"(?<=[.!?:;])\s+", text):
        for w in sentence.split(" ")[1:]:
            w = w.strip("()\"',.;:!?")
            if len(w) < 2 or w.lower() in _FACT_STOP:
                continue
            if (w[0].isupper() and len(w) >= 3 and w[1:].islower()) or (w.isupper() and w.isalpha()):
                facts.add(w.lower())
    return {f for f in facts if f}


def lost_facts(draft, prompt):
    """The facts of ``draft`` (facts_of) missing from ``prompt``: [] when every one is there (a crude plural
    is forgiven both ways)."""
    have = {t.rstrip("s") for t in re.findall(r"[a-z0-9']+", re.sub(r"(?<=\d)[,.](?=\d)", "", str(prompt or "").lower()))}
    return sorted(f for f in facts_of(draft) if f.rstrip("s") not in have)


def _apply_art(moments, data):
    """The art director's prompts onto the moments, by index: ``prompt`` becomes the director's (the editor's
    draft kept in ``prompt_editor``, ``art`` set), when it reads like a prompt AND keeps the editor's facts
    (lost_facts: a number, a place, a name the draft had — the one specific thing of the picture is not the
    director's to drop). Returns how many were taken."""
    taken = 0
    fam = (data or {}).get("family") if isinstance(data, dict) else None
    if fam in FAMILIES:
        for m in moments:
            m["family"] = fam
    for p in (data or {}).get("prompts") or []:
        try:
            k = int(p.get("k"))
        except (TypeError, ValueError, AttributeError):
            continue
        text = re.sub(r"\s+", " ", str(p.get("prompt") or "")).strip()
        if not 0 <= k < len(moments) or not ART_MIN_WORDS <= len(text.split()) <= ART_MAX_WORDS:
            continue
        m = moments[k]
        lost = lost_facts(m.get("prompt_editor") or m.get("prompt"), text)
        if lost:
            print(f"   ⚠️ Art direction #{k}: the director dropped {', '.join(lost)} — the editor's draft is kept "
                  f"for this picture.")
            continue
        if not m.get("art"):
            m["prompt_editor"] = m.get("prompt") or ""
        m["prompt"] = _cut_at_sentence(text, PROMPT_MAX)
        m["art"] = True
        taken += 1
    return taken


def direct_art(moments, clip, house, mixed=True, rise=False, auto_style=True, style="photo", clip_text="",
               family=None, faces="never"):
    """The second call of the brain: one prompt per picture of the set, in the channel's look. Runs on the
    brain's ``broll_art`` step (a Claude model, or Gemini). Any failure leaves the editor's prompts in place."""
    import ai_brain
    if not moments:
        return 0
    prompt = _art_prompt(moments, clip, house, mixed, rise, auto_style, style, clip_text, family, faces)
    try:
        if ai_brain.route("broll_art") == "gemini":
            ai_brain.say(f"Gemini · {TEXT_MODEL}", "B-roll: art direction of the set")
            data, _r = ai_brain.gemini_json([prompt], model=TEXT_MODEL)
        else:
            data = claude_json(prompt, ART_SCHEMA, timeout=300, effort=os.environ.get("CLAUDE_EFFORT_BROLL") or "high",
                               stage="B-roll: art direction of the set", model=ai_brain.stage_model("broll_art"),
                               system=ART_SYSTEM)
    except Exception as e:
        print(f"   ⚠️ B-roll art direction failed ({str(e)[:160]}) — the editor's prompts are used.")
        return 0
    taken = _apply_art(moments, data)
    words = [len(m["prompt"].split()) for m in moments if m.get("art")]
    print(f"   🎨 Art direction: {taken}/{len(moments)} prompt(s) written"
          + (f", {sum(words) // len(words)} words on average" if words else "")
          + (" — the others keep the editor's draft" if taken < len(moments) else ""))
    return taken


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
        lines.append("- AVOID (pictures the episode's director refused): " + "; ".join(bible["avoid"]))
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
        # Judged against the point of the clip, not only the word under it.
        prompt += (f"\nTHE CLIP'S POINT: {thesis}\nAn image that shows the word but does not help the viewer "
                   f"get that point scores 3 at most.")
    prompt += _review_facts(cands)
    prompt += _hero_test(cands)
    # Judged at 512 px (same names): the card is ~300 px wide on screen, and a
    # 1024 px image costs Claude ~4x the tokens for nothing it could not see.
    small_dir = tempfile.mkdtemp(prefix="review_")
    try:
        small = []
        for f in files:
            p = os.path.join(small_dir, os.path.basename(f))
            im = Image.open(f).convert("RGB")
            im.thumbnail((size, size))
            im.save(p, quality=88)
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
        lines.append(f'- file "{os.path.basename(c["file"])}": idea "{c["m"].get("idea") or c["m"]["prompt"]}"'
                     f'{" (" + "; ".join(tags) + ")" if tags else ""}; '
                     f'said: "{c["m"].get("said") or "..." + near + "..."}"'
                     + (f'; prompt (ART-DIRECTED): "{c["m"]["prompt"]}"' if c["m"].get("art") else ""))
    return lines


def review_with_gemini(cands, words):
    """The same check as review_with_claude, by Gemini (cheap vision): each
    image goes in labelled with its file name, at 512 px."""
    import ai_brain
    from google.genai import types
    thesis = next((c["m"].get("thesis") for c in cands if c["m"].get("thesis")), "")
    prompt = REVIEW_PROMPT.format(frame=_review_frame(cands), items="\n".join(_review_lines(cands, words)))
    if thesis:
        prompt += (f"\nTHE CLIP'S POINT: {thesis}\nAn image that shows the word but does not help the viewer "
                   f"get that point scores 3 at most.")
    prompt += _review_facts(cands)
    prompt += _hero_test(cands)
    prompt += '\nReturn only: {"reviews": [{"file": "...", "seen": "...", "score": 1-5, "look": 1-5, "problem": "...", "better_prompt": "..."}]}'
    parts = []
    for c in cands:
        im = Image.open(c["file"]).convert("RGB")
        im.thumbnail((512, 512))
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


def review_images(cands, words):
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
        for k, r in zip(rest, review_images([cands[k] for k in rest], words)):
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
    return review_with_claude(cands, words, model=ai_brain.stage_model("image_review"))


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
_HANDS_RE = re.compile(r"\b(hands?|fingers?|palms?|thumbs?|fists?|typing|writing|scrubbing|gripping|clutching)\b", re.I)
_CROWD_RE = re.compile(r"\b(crowd|crowds|people|soldiers|audience|students|athletes|team|teams|group of|patients|"
                       r"surgeons|protesters|workers|children|kids|troops|marching|army)\b", re.I)
_PERSON_RE = re.compile(r"\b(face|faces|portrait|man|woman|boy|girl|person|doctor|surgeon|patient|athlete|"
                        r"teenager|teen|child|scientist|neuroscientist|speaker|fighter|martial artist)\b", re.I)
_BRANDS = ("iphone", "ipad", "nike", "adidas", "coca-cola", "coke", "pepsi", "starbucks", "mcdonald", "tesla", "google",
           "facebook", "instagram", "tiktok", "youtube", "twitter", "amazon", "netflix", "walmart", "samsung",
           "microsoft", "android", "apple", "logo", "branded")
_BRAND_RE = re.compile(r"\b(" + "|".join(re.escape(b) for b in _BRANDS) + r")\b", re.I)
_GENERIC = {"iphone": "smartphone", "ipad": "tablet", "coca-cola": "cola bottle", "coke": "cola bottle",
            "pepsi": "cola bottle", "nike": "plain", "adidas": "plain"}
GUARD_MAX = 3


def guardrails(prompt, faces=False):
    """(prompt, extra): the prompt with brand names swapped for generic ones, and
    the positive sentences to add at its end for the pitfalls this prompt holds.
    ``faces``: a clear face is allowed on this picture (people stay anonymous:
    nobody real or recognisable)."""
    def generic(m):
        return _GENERIC.get(m.group(1).lower(), m.group(0))
    had_brand = bool(_BRAND_RE.search(prompt))
    prompt = _BRAND_RE.sub(generic, prompt)
    prompt = re.sub(r"\b([Aa])n (smartphone|plain|tablet|cola)\b", r"\1 \2", prompt)   # "An iPhone" -> "A smartphone"
    extra = []
    c = _COUNT_RE.search(prompt)
    if c:
        extra.append(f"Show exactly {_NUM_WORDS[c.group(1).lower()]} {c.group(2)}, clearly separate from each other "
                     "and easy to count.")
    elif _BIG_RE.search(prompt):
        extra.append("Show it as one large group seen as a whole, without trying to depict an exact number.")
    if _TEXT_RE.search(prompt):
        extra.append("Any screen, sign, page or label shows only plain colour, soft light or abstract shapes.")
    if had_brand:
        extra.append("A generic unbranded version with plain surfaces.")
    if _HANDS_RE.search(prompt):
        extra.append("Hands are seen from the side or partly out of frame, in a simple natural pose.")
    if _CROWD_RE.search(prompt):
        extra.append("The group is seen as a whole, the nearest faces natural and anonymous, nobody recognisable."
                     if faces else "The figures are seen from behind or at a distance, as simple silhouettes.")
    elif _PERSON_RE.search(prompt):
        extra.append("An anonymous person, nobody real or recognisable, the face natural, in focus and lit by the "
                     "scene's light." if faces else
                     "An anonymous person, face turned away, in shadow or small in the frame.")
    return prompt, " ".join(extra[:GUARD_MAX])


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


def _look_ok(c):
    look = c.get("look_score")
    return look is None or look >= (LOOK_HERO if c.get("layout") == "hero" else LOOK_CARD)


def _take_review(c, r):
    """The reviewer's answer onto a candidate: score, look_score (None when not given), problem, better_prompt."""
    c["score"] = int(r.get("score") or 3)
    look = r.get("look")
    c["look_score"] = int(look) if isinstance(look, (int, float)) and not isinstance(look, bool) and 1 <= int(look) <= 5 else None
    c["problem"] = str(r.get("problem") or "")[:300]
    c["better_prompt"] = re.sub(r"\s+", " ", str(r.get("better_prompt") or "")).strip()[:PROMPT_MAX]
    return c


def _needs_redo(c):
    return c["score"] <= 3 or not _look_ok(c)


def _better(c2, c):
    """The redo beats the first picture: a higher meaning score, or the same with a higher look."""
    return (c2["score"], c2.get("look_score") or 0) > (c["score"], c.get("look_score") or 0)


def _keep_meaningful(cands):
    """The candidates worth showing, in their order: every one scored KEEP_SCORE+ whose look passes
    (_look_ok), topped up with the best 3s (never below 3, look passing) up to KEEP_FLOOR."""
    good = [c for c in cands if c["score"] >= KEEP_SCORE and _look_ok(c)]
    if len(good) < KEEP_FLOOR:
        spare = sorted((c for c in cands if 3 <= c["score"] < KEEP_SCORE and _look_ok(c)), key=lambda c: -c["score"])
        good += spare[:KEEP_FLOOR - len(good)]
    return [c for c in cands if c in good]


NOTION_MIN_SCORE = 5   # kept and shown in EVERY later clip: only a picture the judge rates perfect

# The subjects of the channel's latest pictures, kept across jobs next to the notion memory: the editor is told
# them so a batch does not open on the same picture three times. Off with the notion memory (BROLL_NOTION_MEMORY=0).
RECENT_MAX = 40        # subjects kept
RECENT_SHOWN = 24      # the latest ones the editor is told
_RECENT_LOCK = __import__("threading").Lock()


def _recent_path():
    return os.path.join(NOTION_DIR, "_recent.json")


def recent_subjects(n=RECENT_SHOWN):
    """The subjects of the channel's latest B-roll pictures, oldest first, or []."""
    if os.environ.get("BROLL_NOTION_MEMORY", "1") == "0":
        return []
    try:
        with open(_recent_path(), encoding="utf-8") as f:
            data = json.load(f)
        return [str(e.get("subject")) for e in data if isinstance(e, dict) and e.get("subject")][-n:]
    except (OSError, ValueError):
        return []


def remember_subjects(items):
    """Keep the subjects of the pictures just made for a clip (RECENT_MAX at most, across jobs). Never raises."""
    if os.environ.get("BROLL_NOTION_MEMORY", "1") == "0":
        return 0
    subs = [re.sub(r"\s+", " ", str(it.get("subject") or "")).strip()[:40] for it in items
            if it.get("subject") and it.get("source") != "screen"]
    if not subs:
        return 0
    with _RECENT_LOCK:
        try:
            try:
                with open(_recent_path(), encoding="utf-8") as f:
                    data = [e for e in json.load(f) if isinstance(e, dict)]
            except (OSError, ValueError):
                data = []
            when = time.strftime("%Y-%m-%d %H:%M")
            data = (data + [{"subject": s, "at": when} for s in subs])[-RECENT_MAX:]
            os.makedirs(NOTION_DIR, exist_ok=True)
            with open(_recent_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=0)
        except OSError:
            return 0
    return len(subs)


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
    return (768, 1344)


# v2 (1-oct-2026): a notion keeps NOTION_VARIANTS pictures per house look (different shots), shown in turn; the
# file name carries the look, so a new house look makes the library again as the clips need it. The pictures
# made before carry no look ("legacy" in the library screen) and are not reused.
NOTION_VARIANTS = int(os.environ.get("BROLL_NOTION_VARIANTS") or 2)
NOTION_SHOTS = ("wide", "close", "macro")   # the shots the variants take, the editor's own first
_USES_LOCK = __import__("threading").Lock()


def look_key(house=""):
    """Six characters naming the house look a notion picture was made with."""
    h = re.sub(r"\s+", " ", str(house or "")).strip().lower()
    if not h:
        return "nolook"
    import hashlib
    return hashlib.sha1(h.encode()).hexdigest()[:6]


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


def notion_put(term, style, engine, layout, src, prompt="", score=None, look="nolook", shot=None, house="", family=None):
    """Keep ``src`` as the next picture of ``term`` for this look (NOTION_VARIANTS at most: the first good ones
    stay the channel's pictures). Never raises."""
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
                       "look": look, "variant": n, "shot": shot or "", "uses": 0, "house": house or "",
                       "family": family or ""}, f, ensure_ascii=False, indent=1)
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
            "house": meta.get("house") or "", "family": meta.get("family") or "",
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


def notion_regenerate(nid, prompt, engine=None, house=None, family=None):
    """Make the notion's picture again from ``prompt`` (edited by the user) on the
    chosen model and keep it as THE picture: the previous one is set aside so it
    can be restored. In the house look (``house``, else the one it was made with)
    and its family; a long prompt goes out as the art director's. No review.
    Raises ValueError / RuntimeError."""
    path = _notion_file(nid)
    entry = _notion_entry(path)
    house = entry["house"] if house is None else house
    family = entry["family"] if family is None else family
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
        local_image(prompt, entry["style"], new, engine=engine, size=_gen_size(entry["layout"]), house=house,
                    family=family if family in FAMILIES else None, art=len(prompt.split()) >= ART_MIN_WORDS)
        base = path[:-4]
        shutil.copy2(path, base + ".prev.jpg")
        if os.path.exists(base + ".json"):
            shutil.copy2(base + ".json", base + ".prev.json")
        shutil.move(new, path)
        meta = _notion_meta(path)
        meta.update(term=entry["term"], style=entry["style"], engine=entry["engine"], layout=entry["layout"],
                    prompt=prompt, score=None, made_with=engine, manual=True, saved=time.strftime("%Y-%m-%d %H:%M"),
                    house=house or "", family=family or "")
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


def _graph(engine, text, seed, width=768, height=1344, steps=None):
    """ComfyUI API graph for one image (768x1344 = 9:16 by default; the cards
    ask 1152x720, the hero 896x1600); node "7" is the PreviewImage (ComfyUI's
    temp folder, wiped on restart — not its gallery). ``steps``: sampler steps
    (the hero may ask more), else COMFYUI_ZIMAGE_STEPS (8).

    One engine: Z-Image Turbo (int8 model + fp8 Qwen3-4B encoder, 8 steps),
    ~12 s an image on an RTX 3060. The FLUX.1 schnell graph (25 s an image,
    never chosen) was removed on 1-oct-2026; ``engine`` stays in the signature
    because the notion library's file names carry it."""
    latent = {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}}
    out = {"6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["v", 0]}},
           "7": {"class_type": "PreviewImage", "inputs": {"images": ["6", 0]}},
           "4": latent}
    out.update({
        "u": {"class_type": "UNETLoader", "inputs": {
            "unet_name": os.environ.get("COMFYUI_ZIMAGE_MODEL") or "z_image_turbo_int8_convrot.safetensors",
            "weight_dtype": "default"}},
        "c": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": os.environ.get("COMFYUI_ZIMAGE_TEXT_ENCODER") or "qwen_3_4b_fp8_mixed.safetensors",
            "type": "lumina2", "device": "default"}},
        "v": {"class_type": "VAELoader", "inputs": {"vae_name": os.environ.get("COMFYUI_ZIMAGE_VAE") or "ae.safetensors"}},
        "m": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["u", 0], "shift": 3.0}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["c", 0]}},
        "3": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["2", 0]}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["m", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
            "seed": seed, "steps": int(steps or os.environ.get("COMFYUI_ZIMAGE_STEPS") or 8), "cfg": 1.0,
            "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0}},
    })
    return out


def _image_text(prompt, style, look="", house="", art=False, family=None, faces=False):
    """The full prompt sent to the image model: the scene (with its guardrails), the channel's house look
    (profile broll.house_look, the same sentence in every image of every clip), this clip's style sheet, the
    style's own description (or, in the mixed layout, the clip's style ``family``) and the common rules.
    ``art``: the scene is the art director's prompt, which already states the look, the frame and the light:
    only the guardrails, the family and the hard rules follow it."""
    prompt, guard = guardrails(prompt, faces) if os.environ.get("BROLL_GUARDRAILS", "1") != "0" else (prompt, "")
    fam = FAMILIES.get(family) if family else None
    if art:
        return " ".join(p for p in (prompt, guard, fam, ART_RULES) if p)
    house = re.sub(r"\s+", " ", str(house or "")).strip()
    if house and not house.endswith("."):
        house += "."
    return " ".join(p for p in (prompt, guard, house, look, fam or STYLES.get(style, STYLES["photo"]), COMMON_RULES) if p)


def local_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", house="", art=False,
                family=None, seed=None, steps=None, faces=False):
    """One 9:16 image from ComfyUI. Measured on an RTX 3060 (ComfyUI on
    PyTorch cu130 — the int8 kernels need it): Z-Image Turbo ~12 s per
    image, FLUX.1 schnell ~25 s; the first call of a job also loads the
    models from disk (~45 s in all). ``seed``: the one to use (kept in the
    item, so a picture can be made again at another size or step count),
    else a new one; ``steps``: the sampler steps, else the usual."""
    import random
    import uuid
    import httpx
    text = _image_text(prompt, style, look, house, art, family, faces)
    seed = random.randint(0, 2 ** 48) if seed is None else int(seed)
    graph = _graph(engine if engine in ENGINES else "zimage", text, seed, *size, steps=steps)
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
                 border="soft", look=None, label=None, grade="off", min_aspect=None):
    """PNG sequence of the rising card, drawn in a fixed canvas; the canvas
    itself moves up through the overlay's ``y`` expression. Returns
    (pattern, x, motion) where motion = (y_start, y_end, drift, canvas_h[,
    rise_s]) for the canvas centre.

    ``look="premium"`` (the "mixed" layout's cards): a landscape card with a
    3 % radius that fades in while rising CARD_RISE_PX over CARD_IN s (no
    travel from the edge of the screen), pushes in CARD_PUSH while it stays,
    and fades out over CARD_OUT s shrinking CARD_OUT_SHRINK. ``label``: a
    small-caps word drawn in its corner. ``grade``: the profile's colour grade
    (GRADES) in place of the historical touch-up, with its grain per frame."""
    prem = look == "premium"
    img = Image.open(src).convert("RGB")
    if grade in GRADES:
        img = _grade_colour(img, grade)
    else:
        img = ImageEnhance.Contrast(img).enhance(1.07)
        img = ImageEnhance.Color(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.15)
    grain = GRADES[grade]["grain"] if grade in GRADES else 0.0
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
        photo = big.crop((int(x0), int(y0), int(x0 + vw), int(y0 + vh))).resize((cw, ch), Image.BILINEAR)
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


# One grade for every picture of a clip (profile broll.grade), applied when the
# picture is cut in (so a restyle keeps it and the image review judges the raw
# picture): a touch less saturation, lifted blacks, warm highlights / cool
# shadows, and (cards) a fine grain. "cinematic" is the documentary-film look of
# the reference shorts; "clean" the same, barely there.
GRADES = {
    "cinematic": {"sat": 0.88, "contrast": 1.04, "lift": 10, "warm": 10, "cool": 10, "grain": 4.0},
    "clean": {"sat": 0.94, "contrast": 1.02, "lift": 4, "warm": 4, "cool": 4, "grain": 0.0},
}


def _grade_colour(img, name):
    """The colour part of a grade on a PIL RGB image (vignette and grain are drawn per frame by the renderers)."""
    g = GRADES.get(name)
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


def _hero_frames(src, folder, fps, dur, W, H, grade="off"):
    """PNG sequence (RGBA) of a full-screen "hero" picture, the way a cutaway is
    cut in a documentary: the image covers the frame (centre crop), pushes in
    slowly (1.00 -> HERO_PUSH, eased over its whole time on screen) and
    crossfades in and out over HERO_FADE s — the podcast stays sharp underneath,
    no blur. Every frame is resampled with LANCZOS straight from the source with
    a sub-pixel box, so the move is smooth (zoompan rounds its window to whole
    pixels and shimmers on a slow zoom). A soft vignette, a dark gradient at the
    bottom (the captions stay readable on a bright picture) and a fine film
    grain that changes every frame finish it. ``grade``: the profile's colour
    grade (GRADES) in place of the historical contrast / colour touch-up.
    Returns the frame pattern."""
    import numpy as np
    img = Image.open(src).convert("RGB")
    if grade in GRADES:
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
    for f in range(n):
        t = f / fps
        z = 1.0 + (HERO_PUSH - 1.0) * _smooth(t / dur)
        bw, bh = sw / z, sh / z
        x0, y0 = (iw - bw) / 2, (ih - bh) / 2
        frame = img.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + bw, y0 + bh))
        arr = np.asarray(frame, dtype=np.float32) * shade
        if noise is not None:
            # The same grain field moved around: new grain every frame for the price of a copy.
            arr += np.roll(noise, (int(rng.integers(0, H)), int(rng.integers(0, W))), axis=(0, 1))
        out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
        alpha = min(_smooth(t / HERO_FADE), _smooth((dur - t) / HERO_FADE))
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


class ComfyDown(RuntimeError):
    """The local GPU (ComfyUI) is off or stopped answering: B-roll images are
    made only there, so the whole job stops instead of shipping clips without
    them. A single picture that fails while ComfyUI is up is not this: it is
    retried once, then skipped (add_broll.make_image)."""


def add_broll(clip_path, out_path, clip, transcript, start, end, cfg, api_key=None, keep_dir=None, keep_prefix="",
              ground_hook=False):
    """Cut up to cfg["max"] (1-10) images into ``clip_path``. Returns a report dict
    ({items, credits, planner, sources}) or None when nothing was added.
    ``keep_dir``: keep each image there (``<keep_prefix>broll_<k>.jpg``, named
    in its item as ``image``) so a restyle can re-apply them."""
    import viral_fx
    # "manual" review: the images are kept next to the clip and listed, but
    # nothing is cut in until the user approves them (app.py .../broll/apply).
    manual = cfg.get("review") == "manual" and bool(keep_dir)
    # The picture the source itself showed (screen_inset): one of the cards, placed by the source, not planned.
    screen = screen_item(clip.get("screen_inset"), keep_dir)
    block = _block_of(screen)

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

    dur_range = (CARD_DUR_MIN, CARD_DUR_MAX) if mixed else None
    # One look for the whole chain (mixed): the house sentence in every prompt, one grade on every picture.
    house = str(cfg.get("house_look") or "").strip() if mixed else ""
    grade = cfg.get("grade") if mixed and cfg.get("grade") in GRADES else "off"
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

    def make_image(prompt, m_style, raw, query, used_urls, sheet=None, layout=None, art=False, family=None):
        """(path, "local", None) from ComfyUI, or (None, None, None) when this
        one picture could not be made: a second try with a new seed, then the
        picture is skipped and the clip goes on with the others (one refused
        prompt used to stop the whole job). Only a ComfyUI that stopped
        answering raises ComfyDown: images are made nowhere else."""
        size = _gen_size(layout if layout is not None else ("rise" if rise else "full"), hero_res)
        steps = HERO_STEPS if layout == "hero" and HERO_STEPS > 0 else None
        faces = face_mode == "always" or (face_mode == "hero" and layout == "hero")
        last = None
        for attempt in range(2):
            t0 = time.time()
            seed = random.randint(0, 2 ** 48)
            try:
                got = local_image(prompt, m_style, raw, engine=engine, size=size, look=look_text(sheet, m_style),
                                  house=house, art=art, family=family, seed=seed, steps=steps, faces=faces)
                seeds[got] = seed
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
                                               block=block)
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
                # One photographic series: whatever the planner picked outside photo / cinematic / neon is a photo.
                for m in moments:
                    if m.get("style") not in PREMIUM_STYLES:
                        m["style"] = "photo"
            # The code has the last word on the hero: the planner's pick counts, the timing rules win.
            k_hero = pick_hero(moments, words[-1]["end"], avoid, head, block)
            for i, m in enumerate(moments):
                m["hero"] = i == k_hero
            if k_hero is None:
                print("   ℹ️ B-roll: no moment of this clip reads well on a whole screen — small cards only.")
        # One style family for the clip (mixed): the profile's, or the art director's pick, else the default.
        family = None
        if mixed:
            family = cfg.get("style_family") if cfg.get("style_family") in FAMILIES else "auto"
        # The notion memory: a notion whose library is not complete gets a new picture this time, in the shot the
        # library lacks (the art director is told); a complete one is reused, its variants in turn.
        look = look_key(house)
        for m in moments:
            if m.get("notion"):
                want = notion_missing_shot(m["notion"], (m.get("style") or "photo") if auto_style else style, engine,
                                           item_layout(m), look, m.get("shot"))
                if want:
                    m["notion_shot"] = want
        if planner == "claude" and cfg.get("art_director"):
            # The second call: the prompts of the whole set, in the channel's look (the editor's drafts stay
            # when it fails).
            direct_art(moments, clip, house, mixed=mixed, rise=rise, auto_style=auto_style, style=style,
                       clip_text=" ".join(w["text"] for w in words), family=family, faces=face_mode)
        if mixed:
            if family == "auto":
                family = next((m.get("family") for m in moments if m.get("family") in FAMILIES), FAMILY_DEFAULT)
            for m in moments:
                m["family"] = family
            print(f"   🎞️ Style family: {family}")

        used_urls, cands = set(), []
        for k, m in enumerate(moments):
            m_style = (m.get("style") or "photo") if auto_style else style
            m_layout = item_layout(m)
            raw = os.path.join(tmp, f"broll_{k}.jpg")
            kept = (notion_get(m.get("notion"), m_style, engine, m_layout, raw, look)
                    if m.get("notion") and not m.get("notion_shot") else None)
            if kept:
                print(f"   ♻️ Notion \"{m['notion']}\": the channel's picture is reused (no image made, no review).")
                cands.append({"k": k, "m": m, "style": m_style, "file": kept, "source": "local", "credit": None,
                              "score": 5, "reused": True, "layout": m_layout})
                continue
            # A notion's picture is the channel's usual one, kept for other clips:
            # made without this clip's look.
            got, used, credit = make_image(m["prompt"], m_style, raw, m["query"], used_urls,
                                           None if m.get("notion") else m.get("sheet"), layout=m_layout,
                                           art=bool(m.get("art")), family=m.get("family"))
            takes = HERO_TAKES if m_layout == "hero" else 1
            if got:
                cands.append({"k": k, "m": m, "style": m_style, "file": got, "source": used, "credit": credit,
                              "layout": m_layout, "seed": seeds.get(got), **({"take": 1} if takes > 1 else {})})
                # The hero is made again with new seeds: the judge sees the takes together, the best one stays.
                for j in range(2, takes + 1):
                    raw_j = os.path.join(tmp, f"broll_{k}_t{j}.jpg")
                    got_j, used_j, credit_j = make_image(m["prompt"], m_style, raw_j, m["query"], used_urls,
                                                         None if m.get("notion") else m.get("sheet"), layout=m_layout,
                                                         art=bool(m.get("art")), family=m.get("family"))
                    if got_j:
                        cands.append({"k": k, "m": m, "style": m_style, "file": got_j, "source": used_j, "credit": credit_j,
                                      "layout": m_layout, "seed": seeds.get(got_j), "take": j})

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
                redone = 0
                for _round in range(max(REDO_CARD, REDO_HERO)):
                    # A weak picture is made again from the reviewer's better prompt: once for a card, twice for
                    # the hero. The better prompt of an art-directed picture is in the director's grammar and
                    # goes out as such; a short one is the editor's kind again.
                    todo = [c for c in checked if _needs_redo(c) and c.get("better_prompt")
                            and c.get("tries", 0) < (REDO_HERO if c["layout"] == "hero" else REDO_CARD)]
                    pairs = []
                    for c in todo:
                        c["tries"] = c.get("tries", 0) + 1
                        raw = os.path.join(tmp, f"broll_{c['k']}_v{c['tries'] + 1}.jpg")
                        art = bool(c["m"].get("art")) and len(c["better_prompt"].split()) >= ART_MIN_WORDS
                        got, used, credit = make_image(c["better_prompt"], c["style"], raw, c["m"]["query"],
                                                       used_urls, None if c["m"].get("notion") else c["m"].get("sheet"),
                                                       layout=c["layout"], art=art, family=c["m"].get("family"))
                        if got:
                            pairs.append((c, {**c, "file": got, "source": used, "credit": credit, "seed": seeds.get(got),
                                             "m": {**c["m"], "prompt": c["better_prompt"], "art": art}}))
                    if not pairs:
                        break
                    redone += len(pairs)
                    for (c, c2), r2 in zip(pairs, review_images([c2 for _, c2 in pairs], words)):
                        _take_review(c2, r2)
                        if _better(c2, c):
                            c.update(c2)
                kept = _keep_meaningful(cands)
                print(f"   🔎 B-roll review: scores {[c['score'] for c in cands]}, looks "
                      f"{[c.get('look_score') for c in cands]}"
                      f"{f', {redone} redone' if redone else ''}, {len(kept)}/{len(cands)} kept")
                for c in kept:
                    if c["m"].get("notion") and not c.get("reused") and c["score"] >= NOTION_MIN_SCORE:
                        if notion_put(c["m"]["notion"], c["style"], engine, c["layout"], c["file"], c["m"]["prompt"],
                                      c["score"], look=look, shot=c["m"].get("notion_shot") or c["m"].get("shot"),
                                      house=house, family=c["m"].get("family")):
                            print(f"   📚 Notion \"{c['m']['notion']}\": picture kept for the next clips "
                                  f"({c['m'].get('notion_shot') or c['m'].get('shot') or '-'} shot).")
                cands = kept
            except ComfyDown:
                raise
            except Exception as e:
                print(f"   ⚠️ B-roll review via Claude failed ({str(e)[:160]}) — images kept unchecked.")

        items, credits, sources = [], [], []
        for c in cands:
            m = c["m"]
            # A real photo (a place, a flag) is shown BIG: a small card shows a tower or a flag badly. Big
            # pictures cover the speaker, so they stay short.
            hero = mixed and c["layout"] == "hero"
            big = (not rise and not mixed) or (c["source"] == "free" and not mixed)
            dur = m.get("dur") or (SEG_DUR if big else RISE_DUR)
            if hero:
                dur = hero_dur(m)                          # its sentence plus the crossfades, 2.5-3.5 s
            elif _hold(cfg.get("hold")) and not mixed:
                dur = _hold(cfg.get("hold"))               # the user's own time on screen (a mixed card follows its sentence)
            elif big:
                dur = round(max(FULL_DUR_MIN, min(FULL_DUR_MAX, dur)), 2)
            item = {"t": round(m["t"], 2), "dur": dur, "anchor": m["anchor"],
                    "idea": m.get("idea") or "", "role": m.get("role"), "subject": m.get("subject") or "",
                    "query": m["query"], "prompt": m["prompt"],
                    "source": c["source"],
                    "style": c["style"] if c["source"] in ("local", "gemini") else "photo",
                    "layout": "hero" if hero else ("full" if big else ("card" if mixed else "rise")), "_img": c["file"]}
            if mixed:
                # The size the picture was made at: a manual redo asks for the same one.
                item["gen"] = list(_gen_size(c["layout"], hero_res))
                if m.get("family"):
                    item["family"] = m["family"]     # the clip's photographic recipe: a manual redo keeps it
                if grade != "off":
                    item["grade"] = grade            # applied when the picture is cut in, restyle included
                if hero and cfg.get("sfx"):
                    item["sfx"] = True               # the whoosh, on the hero only
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
                if not hero:
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
            sources.append(c["source"])
            if c["credit"]:
                credits.append(c["credit"])
        if not items:
            print("   ℹ️ B-roll: no image good enough for this clip's moments — clip left without.")
            return screen_only()
        if screen:
            # The source's own picture takes its place among the cards, at the second the source showed it.
            items.append(screen)
            sources.append("screen")
            items.sort(key=lambda it: float(it["t"]))
        if _hold(cfg.get("hold")) or mixed or screen:
            # A fixed time on screen (or a hero longer than its sentence): two pictures never overlap, the
            # first one leaves a little early
            for a, b in zip(items, items[1:]):
                a["dur"] = round(max(1.0, min(a["dur"], b["t"] - a["t"] - 0.25)), 2)
        if not manual:
            overlay_items(clip_path, out_path, items)
        remember_subjects(items)
        for it in items:
            it.pop("_img", None)
        duration = words[-1]["end"]
        covered = sum(float(it["dur"]) for it in items)
        print(f"   🖼️ B-roll {cfg.get('layout') or 'full'}: {len(items)} image(s)"
              + (f" ({sum(it['layout'] == 'hero' for it in items)} hero)" if mixed else "")
              + f", {covered:.1f} s of {duration:.0f} s covered ({100 * covered / max(duration, 1.0):.0f} %), "
              f"ComfyUI {gpu[0]:.0f} s" + (" (manual review: not cut in yet)" if manual else ""))
        return {"items": items, "credits": credits, "planner": planner, "sources": sources, "pending": manual}
    finally:
        if used_local:
            _comfy_leave()
        shutil.rmtree(tmp, ignore_errors=True)


def regenerate_image(prompt, style, out_path, query="", cfg=None, api_key=None, sheet=None, gen=None, art=False,
                     family=None, seed=None, steps=None):
    """One image again, from a new prompt / style (the manual review), on the
    local GPU. ``gen``: the (width, height) the first picture was made at (the
    item's "gen"), else the layout's usual size. ``art``: the item's prompt is
    the art director's (sent as is, when it still reads like one). Returns
    (path, source, credit); raises when nothing came."""
    cfg = cfg or {}
    style = style if style in STYLES else "photo"
    engine = "zimage"
    rise = cfg.get("layout") == "rise"
    try:
        size = (int(gen[0]), int(gen[1])) if gen else (RISE_GEN if rise else (768, 1344))
    except (TypeError, ValueError, IndexError):
        size = RISE_GEN if rise else (768, 1344)
    if not comfy_available():
        raise RuntimeError("ComfyUI is not reachable (start it in Pinokio)")
    # A hero or a wide card belongs to a "mixed" clip: it gets the house look like the first picture did.
    house = str(cfg.get("house_look") or "").strip() if cfg.get("layout") in ("hero", "card", "mixed") else ""
    try:
        art = bool(art) and len(str(prompt).split()) >= ART_MIN_WORDS
        mode = cfg.get("faces") if cfg.get("faces") in FACE_MODES else "never"
        faces = mode == "always" or (mode == "hero" and cfg.get("layout") == "hero")
        return local_image(prompt, style, out_path, engine=engine, size=size, look=look_text(sheet, style),
                           house=house, art=art, family=family if family in FAMILIES else None, seed=seed,
                           steps=steps, faces=faces), "local", None
    finally:
        comfy_release()


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
            dur = max(1.0, min(SCREEN_DUR_MAX if screen else 4.0, dur))
            grade = it.get("grade") if it.get("grade") in GRADES else "off"
            if hero:
                pattern = _hero_frames(src, folder, fps, dur, w, h, grade=grade)
                layers.append({"t": it["t"], "dur": dur, "rise": False, "hero": True, "pattern": pattern, "x": 0, "y": 0})
            elif rise:
                pattern, x, motion = _rise_frames(src, folder, fps, dur, w, h, int(it.get("size") or RISE_SIZE),
                                                  it.get("position") or "below", _free_y(it.get("y")),
                                                  it.get("enter") if it.get("enter") in ENTER_MODES else "rise",
                                                  it.get("zoom") if it.get("zoom") in ZOOM_LEVELS else "soft",
                                                  it.get("border") if it.get("border") in BORDERS else "soft",
                                                  look=it.get("look"), label=it.get("label"), grade=grade,
                                                  min_aspect=SCREEN_ASPECT_MIN if screen else None)
                layers.append({"t": it["t"], "dur": dur, "rise": True, "pattern": pattern, "x": x, "y": motion})
            else:
                pattern, x, y, _full = _card_frames(src, folder, fps, dur, w, h,
                                                    it.get("zoom") if it.get("zoom") in ZOOM_LEVELS else "soft",
                                                    it.get("border") if it.get("border") in BORDERS else "soft")
                layers.append({"t": it["t"], "dur": dur, "rise": False, "pattern": pattern, "x": x, "y": y})
        if not layers:
            raise RuntimeError("no B-roll image to cut in")
        big = [ly for ly in layers if not ly["rise"] and not ly.get("hero")]
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
        # The whoosh of a hero (item "sfx"): mixed into the clip's own track at SFX_GAIN_DB, which means
        # re-encoding the audio (AAC) in this pass only; without it the audio is copied as always.
        sfx_at = [float(it["t"]) for it in items if it.get("sfx") and it.get("layout") == "hero"
                  and any(ly.get("hero") and abs(ly["t"] - float(it["t"])) < 1e-6 for ly in layers)]
        audio_in, audio_graph = [], []
        if sfx_at and os.path.exists(SFX_PATH):
            for j, t in enumerate(sfx_at):
                audio_in += ["-i", SFX_PATH]
                ms = max(0, int(round((t - SFX_LEAD) * 1000)))
                audio_graph.append(f"[{1 + len(layers) + j}:a]adelay={ms}|{ms},volume={SFX_GAIN_DB:g}dB[sx{j}]")
            audio_graph.append(f"[0:a]{''.join(f'[sx{j}]' for j in range(len(sfx_at)))}"
                               f"amix=inputs={len(sfx_at) + 1}:duration=first:normalize=0[a]")

        def cut(with_sfx):
            if with_sfx:
                cmd = ["ffmpeg", "-y", "-v", "error", "-i", clip_path, *inputs, *audio_in,
                       "-filter_complex", ";".join(graph + audio_graph), "-map", "[v]", "-map", "[a]", *enc,
                       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path]
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
