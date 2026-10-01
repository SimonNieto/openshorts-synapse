"""B-roll images for Clip Generator++ (beta).

2-4 cutaways per clip, ~1.6 s each, exactly when the speaker names something
concrete (the kratom plant, a brain scan, soldiers...), while the voice goes
on. They make the clip clearer, hold attention (something changes on screen)
and make it a real edit rather than a re-upload.

* Moments: one small Gemini text call per clip reads the clip's own words and
  quotes the spoken anchor; the anchor is found in the word timestamps, so the
  cut lands on the word. Without a key, or when the call fails, a local
  heuristic (the clip's topic words, numbers, long rare words) picks them.
* Images, by ``source``:
  - "gemini": Gemini Image on the user's key (billed per image; the free tier
    may refuse it — then "auto" moves on);
  - "free":   real photos from Openverse (WordPress Foundation's search over
    Wikimedia, Flickr...), licences that allow reuse and edits only: CC0,
    public domain, CC BY. CC BY needs a credit, collected in ``credits`` and
    added to the post's description at publish time;
  - "auto":   Gemini first, free photos for whatever it could not make;
  - "local":  generated on this machine's GPU by a ComfyUI server (e.g. the
    Pinokio one, FLUX.1 schnell): free and unlimited. ComfyUI down or
    failing -> free photos. After each clip the models are unloaded from
    VRAM so Whisper / NVENC in the container never fight it for the card.
* Render: a photo card (rounded, white edge, shadow) pops in over the
  podcast, which keeps playing blurred and dimmed behind it; a tall image
  (Gemini 9:16) takes the full frame. Slow push-in, fade out. It runs BEFORE the edit style, so the pristine copy the "viral style"
  button rebuilds from keeps its B-roll.
"""
import io
import json
import os
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
IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL") or "gemini-3.1-flash-image"
TEXT_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
OPENVERSE = "https://api.openverse.org/v1/images/"
# Wikimedia's user-agent policy: name the tool and a way to reach it.
UA = {"User-Agent": "OpenShorts-selfhost/1.0 (https://openshorts.app; b-roll images) httpx"}
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
HERO_RULE = """HERO IMAGE: one image of the set may be shown FULL SCREEN for about 3 s instead of small: the most VISUAL
moment of the clip — a concrete scene (an example, a consequence, a place, an action), shot wide or medium, never a
diagram, never in the hook's first seconds, never on the punchline. Mark it "hero": true (one at most) and make its
image_prompt a complete scene with depth (foreground, subject, background): it fills a phone screen."""
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

# Only added to the plan prompt when the profile's broll.real_photos is on.
REAL_PHOTO_RULE = """
REAL PHOTOS: only for a famous, identifiable PLACE or a FLAG - a landmark or monument (the CN Tower, the Eiffel Tower),
a famous building, a city skyline, a country, a natural wonder (the Grand Canyon), or a country's flag - add
"real_photo": true and "search_query": for a place, 2-4 English words naming it (the name of the place, nothing else);
for a flag, exactly "flag of <country>". Never for anything else: no object, tool, animal, plant, person, food, machine,
body part, idea, mechanism or scene with people or action (those are always generated). A place that is not
famous enough to be recognised at a glance stays generated. When unsure, leave it out."""

CLAUDE_SYSTEM = "You are a meticulous short-form video editor. You answer only with the requested JSON."
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
images. Each one shows small (about a third of the screen width, under the captions) while the voice goes on,
from the anchor word to the end of its sentence or clause (1.5-3 s): put the anchor where the thing is named, and
prefer a sentence the image can accompany to its end.

FIRST understand the clip inside its episode (the EPISODE BRIEF below: who talks, what the episode is about, the
visual glossary, the real stories told). Then write:
- "thesis": in one sentence, what the viewer must take away from THIS clip;
- "arc": setup -> claim -> payoff of the clip, in a few words each.
Also write "style_sheet": ONE visual direction for the whole set of images of this clip, so they look shot by the
same person on the same day, in plain words a few words long each: "palette" (the 2-4 dominant colours), "light"
(kind and direction of the light), "era" (the period the story is in, or "present day"), "camera" (lens, angle,
grain), "mood". Take them from the topic, the era and the tone of the stories, not from the words of one sentence.
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
Never: something already visible in the video (look at the frame sheets), a named real person,
a brand (use a generic equivalent), an abstraction nobody can draw. Aim for {n} images; return fewer only when the clip
truly has nothing concrete to show.

Frame sheets: {sheets} — thumbnails of the clip every 2.5 s, each stamped with its time. Look at them first.

For each image give:
- "anchor": the exact 1-3 words as spoken where the image should land (verbatim from the transcript). The image
  pops up just before the most meaningful of these words (the noun that names the thing: "gallons" in "two gallons of
  water", not "two") is spoken, so choose words whose key word is the one that shows the thing;
- "time": the second the anchor is spoken (from the markers);
- "said": the sentence (about 8-15 words, verbatim) this image illustrates;
- "idea": one short sentence — what the viewer should get from this image;
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

CLIP TITLE: {title}
HOOK: {hook}
SAID JUST BEFORE THE CLIP (context only): {before}

TRANSCRIPT OF THE CLIP (seconds from the clip start):
{text}

SAID JUST AFTER THE CLIP (context only): {after}"""

REVIEW_PROMPT = """Each image below will appear for about {dur:.1f} s, small (about a third of a phone screen's width),
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
WRONG FACTS: the wrong organ, tool, animal or place (lungs for a throat, a random building for a named landmark), or
a key detail that contradicts what is said, scores 2 at most — however pretty.
THE SET: the images are seen in a row. Compare them with each other: when one looks like an earlier one (same main
subject, same framing, same look), the later one scores 3 at most and its better_prompt shows another side of the
idea (the person, the object, the effect, another scale).
For each image, by "file": "seen", "score" 1-5 (5 = instantly clear and on point, 4 = good, 3 = acceptable, 2 or 1 =
weak, wrong or confusing), "problem" (a few words, empty if none) and "better_prompt": an English image prompt that
would fix it (one clear scene, one main subject, no text) - empty when the score is 4 or 5."""
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"reviews": {"type": "array", "items": {
        "type": "object",
        "properties": {"file": {"type": "string"}, "seen": {"type": "string"}, "score": {"type": "integer"},
                       "problem": {"type": "string"}, "better_prompt": {"type": "string"}},
        "required": ["file", "seen", "score"]}}},
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


def _allowed(t, duration, avoid):
    return HEAD_FREE <= t <= duration - TAIL_FREE - SEG_DUR and all(abs(t - a) > 1.2 for a in avoid)


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


def hero_fits(m, duration, avoid):
    """A hero never runs into the hook's seconds, the last TAIL_FREE s, or within
    1.2 s of the punchline — on its whole time on screen, not only its first frame."""
    t, d = m["t"], hero_dur(m)
    if t < HEAD_FREE or t + d > duration - TAIL_FREE:
        return False
    return all(t + d <= a - 1.2 or t >= a + 1.2 for a in avoid)


def pick_hero(moments, duration, avoid):
    """Index of the moment shown full screen, or None: a concrete scene (an example
    or a consequence, a wide or medium shot, a photographic style) that fits the
    timing rules. The planner's own "hero" counts for a lot, a moment in the second
    part of the clip (the payoff) a little; a tie goes to the later one. None when
    no moment reads well on a whole phone screen (a diagram, a schematic)."""
    best, best_score = None, 0.0
    for i, m in enumerate(moments):
        if not hero_fits(m, duration, avoid) or m.get("notion"):
            continue
        score = 1.0 + HERO_ROLE.get(m.get("role") or "", 0.0) + HERO_SHOT.get(m.get("shot") or "", 0.5)
        score += HERO_STYLE.get(m.get("style") or "photo", 0.0)
        score += 3.0 if m.get("hero") else 0.0
        score += 1.0 if m.get("real_photo") else 0.0
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


def _plan_prompt(clip, words, n, avoid, auto_style):
    duration = words[-1]["end"]
    avoid_txt = (", and not within 1.2 s of " + ", ".join(f"{a:.1f}s" for a in avoid)) if avoid else ""
    title = clip.get("video_title_for_youtube_short") or ""
    return PLAN_PROMPT.format(n=n + 2, lo=HEAD_FREE, hi=duration - TAIL_FREE - SEG_DUR, avoid=avoid_txt,
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
        v = re.sub(r"\s+", " ", str(raw.get(k) or "")).strip(" .")[:70]
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


def _moment_dur(words, i, t, duration):
    """How long the image stays: from its word to the end of the sentence (or of
    the clause, once it has lasted DUR_MIN), so it goes away when the voice moves
    on to something else. Clamped to DUR_MIN..DUR_MAX and to the clip's end."""
    end = words[i]["end"]
    for j in range(i, len(words)):
        end = words[j]["end"]
        text = words[j]["text"]
        if end - t >= DUR_MAX:
            break
        if re.search(r"[.!?;:…]$", text) or (re.search(r",$", text) and end - t >= DUR_MIN):
            break
    dur = max(DUR_MIN, min(DUR_MAX, end - t + DUR_TAIL))
    return round(min(dur, max(DUR_MIN, duration - 1.0 - t)), 2)


def _parse_moments(data, words, n, avoid, gap=MIN_GAP):
    """The planner's answer -> moments that land on a real spoken word, in
    the allowed window, spaced out. Anything that does not check out is
    dropped, whoever the planner was."""
    duration = words[-1]["end"]
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
        if not _allowed(t, duration, avoid):
            continue
        moments.append({"t": t, "anchor": " ".join(w["text"] for w in words[i:i + n_tok]),
                        "key": words[k]["text"],
                        "query": str(m.get("search_query") or m.get("anchor"))[:60],
                        "prompt": str(m.get("image_prompt") or m.get("anchor"))[:400],
                        "idea": str(m.get("idea") or "")[:200],
                        "said": str(m.get("said") or "")[:200],
                        "subject": str(m.get("subject") or "")[:40],
                        "shot": m.get("shot") if m.get("shot") in SHOTS else None,
                        "style": m.get("style") if m.get("style") in STYLES else None,
                        "role": m.get("role") if m.get("role") in ("concept", "example", "consequence") else None,
                        "notion": str(m.get("notion") or "")[:80],
                        "real_photo": bool(m.get("real_photo")) and bool(str(m.get("search_query") or "").strip()),
                        "hero": bool(m.get("hero")),
                        "dur": _moment_dur(words, k, t, duration),
                        "sheet": sheet,
                        "score": 1.0})
    kept = _space(moments, n, gap)
    for a, b in zip(kept, kept[1:]):
        # never run into the next image
        a["dur"] = round(max(DUR_MIN, min(a["dur"], b["t"] - a["t"] - DUR_NEXT_GAP)), 2)
    return kept


def plan_with_gemini(clip, words, n, avoid, api_key, auto_style=False):
    from google import genai
    from google.genai import types
    prompt = _plan_prompt(clip, words, n, avoid, auto_style)
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
    return _parse_moments(data, words, n, avoid)


# --- Claude (the user's subscription, through Claude Code) -----------------------

def claude_ready():
    """Claude can think for this job (set up, not switched off by a quota)."""
    import ai_brain
    return ai_brain.claude_usable()


def claude_json(prompt, schema, timeout=240, attach=None, stage=None, effort=None, model=None):
    """One Claude call through ai_brain (the job-wide Claude-first switch): a
    quota / session limit switches Claude off for the rest of the job.
    ``model``: the profile's model for the B-roll by default."""
    import ai_brain
    model = model or ai_brain.stage_model("broll")
    if stage:
        ai_brain.say(f"Claude · {model}", stage)
    try:
        return ai_brain.claude_json(prompt, schema, timeout=timeout, attach=attach, effort=effort, model=model,
                                    system=CLAUDE_SYSTEM_VISION if attach else CLAUDE_SYSTEM)
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
        m["notion"] = g["term"]
        if norm(g["term"]) not in said_names:
            m["prompt"] = f"{m['prompt']} Draw {g['term']} the channel's usual way: {g['visual']}."[:700]
            print(f"   📚 Notion \"{g['term']}\" recognised by meaning — glossary picture added.")
    return moments


def plan_with_claude(clip, words, n, avoid, auto_style=False, transcript=None, start=0.0, end=None,
                     sheets=None, ground=None, mode="mixed", real_photos=False, density="normal", hero=False):
    """Claude reads the clip, the conversation around it and (``sheets``) what
    is on screen, and places images that carry the IDEA being said.
    ``ground``: hook_grounding.request()'s (frames, prompt) — the hook is
    rewritten from the screen in this same call instead of a second one.
    ``hero``: the "mixed" layout — it may name the one image worth the whole screen."""
    import ai_brain
    duration = words[-1]["end"]
    before, after = _context(transcript, start, end if end is not None else start + duration)
    avoid_txt = (", and not within 1.2 s of " + ", ".join(f"{a:.1f}s" for a in avoid)) if avoid else ""
    title = clip.get("video_title_for_youtube_short") or ""
    clip_text = " ".join(w["text"] for w in words)
    brief = ai_brain.brief_for_clip(ai_brain.EPISODE_BRIEF, f"{before} {clip_text} {after}", start,
                                    end if end is not None else start + duration)
    common = dict(n=n, avoid=avoid_txt, sheets=", ".join(os.path.basename(p) for p in sheets or []) or "none",
                  style_rule=STYLE_RULE if auto_style else "", mode_rule=MODE_RULES.get(mode, MODE_RULES["mixed"]),
                  title=title or "-",
                  hook=clip.get("viral_hook_text") or "-", before=before or "-", after=after or "-",
                  brief=brief or "(no brief for this video)", text=_numbered_text(words)[:6000],
                  grounding=GROUNDING_RULE, set_rule=SET_RULE, pace=DENSITY[density]["pace"], names=DENSITY[density]["names"],
                  gap=DENSITY[density]["gap"])
    prompt = CLAUDE_PLAN_PROMPT.format(lo=HEAD_FREE, hi=duration - TAIL_FREE - SEG_DUR, **common)
    if real_photos:
        prompt += "\n" + REAL_PHOTO_RULE
    schema, attach, shots_dir = PLAN_SCHEMA, list(sheets or []), None
    if hero:
        prompt += "\n" + HERO_RULE
        schema = json.loads(json.dumps(schema))
        schema["properties"]["moments"]["items"]["properties"]["hero"] = {"type": "boolean"}
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
    moments = _parse_moments(data, words, n, avoid, DENSITY[density]["gap"])
    apply_notions(moments, ai_brain.EPISODE_BRIEF, f"{before} {clip_text} {after}")
    thesis = str((data or {}).get("thesis") or "")[:300]
    if thesis:
        print(f"   💡 Clip thesis: {thesis}")
    cast = str(((data or {}).get("style_sheet") or {}).get("cast") or "")[:200]
    if cast:
        print(f"   🎭 Recurring subject: {cast}")
    subjects = [m.get("subject") for m in moments if m.get("subject")]
    if subjects:
        print(f"   🎞️ Sequence: {' -> '.join(subjects)}")
    for m in moments:
        m["thesis"] = thesis
    return moments


def review_with_claude(cands, words, model=None):
    """Claude looks at each made image and scores it against the idea it must
    carry (1-5), with a better prompt when it falls short."""
    thesis = next((c["m"].get("thesis") for c in cands if c["m"].get("thesis")), "")
    files = [c["file"] for c in cands]
    lines = _review_lines(cands, words)
    prompt = REVIEW_PROMPT.format(dur=RISE_DUR, items="\n".join(lines))
    if thesis:
        # Judged against the point of the clip, not only the word under it.
        prompt += (f"\nTHE CLIP'S POINT: {thesis}\nAn image that shows the word but does not help the viewer "
                   f"get that point scores 3 at most.")
    # Judged at 512 px (same names): the card is ~300 px wide on screen, and a
    # 1024 px image costs Claude ~4x the tokens for nothing it could not see.
    small_dir = tempfile.mkdtemp(prefix="review_")
    try:
        small = []
        for f in files:
            p = os.path.join(small_dir, os.path.basename(f))
            im = Image.open(f).convert("RGB")
            im.thumbnail((512, 512))
            im.save(p, quality=88)
            small.append(p)
        data = claude_json(prompt, REVIEW_SCHEMA, timeout=240, attach=small, stage="B-roll: checking each image",
                           model=model)
    finally:
        shutil.rmtree(small_dir, ignore_errors=True)
    by_file = {r.get("file"): r for r in (data or {}).get("reviews") or []}
    return [by_file.get(os.path.basename(f), {"score": 3}) for f in files]


def _review_lines(cands, words):
    lines = []
    for c in cands:
        near = " ".join(w["text"] for w in words if c["m"]["t"] - 4 <= w["start"] <= c["m"]["t"] + 4)
        tags = ([f"role: {c['m']['role']}"] if c["m"].get("role") else []) + \
               (["shown FULL SCREEN for ~3 s: judge it at that size"] if c["m"].get("hero") else [])
        lines.append(f'- file "{os.path.basename(c["file"])}": idea "{c["m"].get("idea") or c["m"]["prompt"]}"'
                     f'{" (" + "; ".join(tags) + ")" if tags else ""}; '
                     f'said: "{c["m"].get("said") or "..." + near + "..."}"')
    return lines


def review_with_gemini(cands, words):
    """The same check as review_with_claude, by Gemini (cheap vision): each
    image goes in labelled with its file name, at 512 px."""
    import ai_brain
    from google.genai import types
    thesis = next((c["m"].get("thesis") for c in cands if c["m"].get("thesis")), "")
    prompt = REVIEW_PROMPT.format(dur=RISE_DUR, items="\n".join(_review_lines(cands, words)))
    if thesis:
        prompt += (f"\nTHE CLIP'S POINT: {thesis}\nAn image that shows the word but does not help the viewer "
                   f"get that point scores 3 at most.")
    prompt += '\nReturn only: {"reviews": [{"file": "...", "seen": "...", "score": 1-5, "problem": "...", "better_prompt": "..."}]}'
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
    for the final say. A Claude model: it checks them all itself."""
    import ai_brain
    if not cands:
        return []
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

def gemini_image(prompt, style, api_key, out_path, aspect="9:16"):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)
    full = f"{prompt}\n\nStyle: {STYLES.get(style, STYLES['photo'])}\n{COMMON_RULES}"
    r = client.models.generate_content(
        model=IMAGE_MODEL, contents=[full],
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"],
                                           image_config=types.ImageConfig(aspect_ratio=aspect, image_size="1K")))
    for part in (r.parts or []):
        if part.inline_data is not None and part.inline_data.data:
            Image.open(io.BytesIO(part.inline_data.data)).convert("RGB").save(out_path, quality=92)
            return out_path
    cand = (r.candidates or [None])[0]
    raise RuntimeError(f"no image (finish_reason={getattr(cand, 'finish_reason', None)})")


# --- local GPU (ComfyUI) --------------------------------------------------------

def _comfy_url():
    return (os.environ.get("COMFYUI_URL") or "http://host.docker.internal:8188").rstrip("/")


def comfy_available(timeout=3):
    import httpx
    try:
        return httpx.get(f"{_comfy_url()}/system_stats", timeout=timeout).status_code == 200
    except Exception:
        return False


ENGINES = ("zimage", "flux")


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
                      r"license|dashboards?|spreadsheets?|prescriptions?|notes?|notebooks?)\b", re.I)
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


def guardrails(prompt):
    """(prompt, extra): the prompt with brand names swapped for generic ones, and
    the positive sentences to add at its end for the pitfalls this prompt holds."""
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
        extra.append("The figures are seen from behind or at a distance, as simple silhouettes.")
    elif _PERSON_RE.search(prompt):
        extra.append("An anonymous person, face turned away, in shadow or small in the frame.")
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


def _keep_meaningful(cands):
    """The candidates worth showing, in their order: every one scored KEEP_SCORE+,
    topped up with the best 3s (never below 3) up to KEEP_FLOOR."""
    good = [c for c in cands if c["score"] >= KEEP_SCORE]
    if len(good) < KEEP_FLOOR:
        spare = sorted((c for c in cands if 3 <= c["score"] < KEEP_SCORE), key=lambda c: -c["score"])
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
    return (768, 1344)


def _notion_path(term, style, engine, layout):
    import hashlib
    norm = re.sub(r"\W+", " ", str(term or "").lower()).strip()
    import unicodedata
    ascii_norm = unicodedata.normalize("NFKD", norm).encode("ascii", "ignore").decode()   # plain file / URL names
    slug = re.sub(r"\s+", "-", ascii_norm.strip())[:40] or "notion"
    h = hashlib.sha1(norm.encode()).hexdigest()[:6]
    return os.path.join(NOTION_DIR, f"{slug}-{h}__{style}__{engine}__{_shape(layout)}.jpg")


def notion_get(term, style, engine, layout, dest):
    """Copy the kept picture of ``term`` to ``dest`` and return ``dest``; None if none."""
    if os.environ.get("BROLL_NOTION_MEMORY", "1") == "0" or not term:
        return None
    src = _notion_path(term, style, engine, layout)
    if not os.path.exists(src):
        return None
    shutil.copy2(src, dest)
    return dest


def notion_put(term, style, engine, layout, src, prompt="", score=None):
    """Keep ``src`` as the picture of ``term`` unless one is already kept (the
    first good one stays the channel's picture). Never raises."""
    if os.environ.get("BROLL_NOTION_MEMORY", "1") == "0" or not term:
        return False
    try:
        dest = _notion_path(term, style, engine, layout)
        if os.path.exists(dest):
            return False
        os.makedirs(NOTION_DIR, exist_ok=True)
        shutil.copy2(src, dest)
        with open(dest[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump({"term": term, "style": style, "engine": engine, "layout": _layout_of(_shape(layout)),
                       "prompt": prompt, "score": score, "saved": time.strftime("%Y-%m-%d %H:%M")}, f,
                      ensure_ascii=False, indent=1)
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
    return {"id": stem, "term": meta.get("term") or parts[0],
            "style": meta.get("style") or (parts[1] if len(parts) > 1 else "photo"),
            "engine": meta.get("engine") or (parts[2] if len(parts) > 2 else "zimage"),
            "layout": meta.get("layout") or _layout_of(stem.rsplit("__", 1)[-1]),
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
    return sorted(out, key=lambda e: (e["term"].lower(), e["style"], e["layout"]))


def notion_regenerate(nid, prompt, engine=None):
    """Make the notion's picture again from ``prompt`` (edited by the user) on the
    chosen model and keep it as THE picture: the previous one is set aside so it
    can be restored. No clip look, no review. Raises ValueError / RuntimeError."""
    path = _notion_file(nid)
    entry = _notion_entry(path)
    prompt = re.sub(r"\s+", " ", str(prompt or "")).strip()[:700]
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
        local_image(prompt, entry["style"], new, engine=engine, size=_gen_size(entry["layout"]))
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


def _graph(engine, text, seed, width=768, height=1344):
    """ComfyUI API graph for one image (768x1344 = 9:16 by default; the
    "rise" layout asks 896x1152, 4:5); node "7" is the
    PreviewImage (ComfyUI's temp folder, wiped on restart — not its gallery).

    * zimage: Z-Image Turbo (int8 model + fp8 Qwen3-4B encoder, 8 steps) —
      fast, the default for clips;
    * flux:   FLUX.1 schnell fp8 all-in-one checkpoint (4 steps) — heavier,
      for when quality matters more than time."""
    latent = {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}}
    out = {"6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["v", 0]}},
           "7": {"class_type": "PreviewImage", "inputs": {"images": ["6", 0]}},
           "4": latent}
    if engine == "flux":
        out.update({
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {
                "ckpt_name": os.environ.get("COMFYUI_CHECKPOINT") or "flux1-schnell-fp8.safetensors"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
            "5": {"class_type": "KSampler", "inputs": {
                "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
                "seed": seed, "steps": int(os.environ.get("COMFYUI_FLUX_STEPS") or 4), "cfg": 1.0,
                "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        })
        out["6"]["inputs"]["vae"] = ["1", 2]
        return out
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
            "seed": seed, "steps": int(os.environ.get("COMFYUI_ZIMAGE_STEPS") or 8), "cfg": 1.0,
            "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0}},
    })
    return out


def local_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look=""):
    """One 9:16 image from ComfyUI. Measured on an RTX 3060 (ComfyUI on
    PyTorch cu130 — the int8 kernels need it): Z-Image Turbo ~12 s per
    image, FLUX.1 schnell ~25 s; the first call of a job also loads the
    models from disk (~45 s in all)."""
    import random
    import uuid
    import httpx
    prompt, guard = guardrails(prompt) if os.environ.get("BROLL_GUARDRAILS", "1") != "0" else (prompt, "")
    text = f"{prompt} {guard} {look} {STYLES.get(style, STYLES['photo'])} {COMMON_RULES}".replace("  ", " ")
    graph = _graph(engine if engine in ENGINES else "zimage", text, random.randint(0, 2 ** 48), *size)
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


def _wikimedia_thumb(url, width=1280):
    """upload.wikimedia.org original -> its cached 1280 px rendition (what
    Wikimedia asks tools to fetch; originals are throttled)."""
    m = re.match(r"(https://upload\.wikimedia\.org/wikipedia/commons)/(\w/\w\w)/([^/?#]+)$", url or "")
    if not m:
        return url
    base, path, name = m.groups()
    thumb = f"{base}/thumb/{path}/{name}/{width}px-{name}"
    return thumb + ".png" if name.lower().endswith((".svg", ".tif", ".tiff")) else thumb


# Titles that announce something that is not a clean photo of the thing.
_UGLY_TITLE = re.compile(
    r"\b(label(l)?ed|diagram|chart|graph|map|logo|screenshot|screen shot|poster|cover|comic|cartoon|"
    r"infographic|table|scan of|page|document|text|sign|flag of|coat of arms|stamp|advert|meme|collage|"
    r"engraving|etching|lithograph|woodcut|painting|caricature|illustration|drawing|print)\b|<", re.I)


def _looks_good(path, flat=False):
    """A photo worth showing: sharp, not too dark / washed out, sane shape.
    ``flat``: a flag (flat colours, few edges) only has to have a sane size and shape."""
    try:
        img = Image.open(path).convert("L")
    except Exception:
        return False
    w, h = img.size
    if w < (800 if flat else 900) or not 0.5 <= h / w <= 2.0:
        return False
    if flat:
        return True
    small = img.resize((512, max(1, int(512 * h / w))))
    mean = ImageStat.Stat(small).mean[0]
    if not 35 <= mean <= 232:   # a clean product shot on white is fine
        return False
    edges = small.filter(ImageFilter.FIND_EDGES)
    sharp = ImageStat.Stat(edges).var[0]
    contrast = ImageStat.Stat(small).stddev[0]
    # Colourfulness (Hasler & Süsstrunk): old engravings, sepia prints and
    # scans score < 12; a modern colour photo 20+.
    rgb = Image.open(path).convert("RGB").resize(small.size)
    r, g, b = [ImageStat.Stat(c) for c in rgb.split()]
    import math
    rg_mean, rg_std = r.mean[0] - g.mean[0], math.sqrt(abs(r.var[0] + g.var[0]))
    yb_mean = 0.5 * (r.mean[0] + g.mean[0]) - b.mean[0]
    yb_std = math.sqrt(abs(0.25 * (r.var[0] + g.var[0]) + b.var[0]))
    colourful = math.hypot(rg_std, yb_std) * 0.3 + 0.3 * math.hypot(rg_mean, yb_mean)
    return sharp >= 90 and contrast >= 28 and colourful >= 14


def query_variants(query):
    """"modern hospital hallway" -> [..., "hospital hallway", "hospital"...];
    brand-like capitalised words ("Pop-Tarts packaging") are dropped first."""
    q = re.sub(r"\s+", " ", (query or "").strip())
    out = [q]
    no_brand = " ".join(w for w in q.split() if not (w[:1].isupper() and not w.isupper()) or len(q.split()) == 1)
    if no_brand and no_brand != q:
        out.append(no_brand)
    words = (no_brand or q).split()
    # Shorter phrases, longest first: "emergency room doctors" -> "emergency
    # room", "room doctors", then the last word alone (the head noun — never
    # a leading adjective alone).
    for size in range(len(words) - 1, 1, -1):
        for k in range(len(words) - size + 1):
            out.append(" ".join(words[k:k + size]))
    if len(words) >= 2:
        out.append(words[-1])
    seen, uniq = set(), []
    for v in out:
        v = v.strip().lower()
        if v and v not in seen and len(v) >= 3:
            seen.add(v)
            uniq.append(v)
    return uniq[:6]


_FLAG_RE = re.compile(r"^\s*flag of\s+(.+?)\s*$", re.I)
# "Flag of France", "File:Flag of France (2024-present)": the plain national flag, not a pilot / naval /
# historical / stylised variant.
_UGLY_TITLE_NOFLAG = re.compile(_UGLY_TITLE.pattern.replace("flag of|", ""), re.I)


def _seen_from(title, want):
    """"Champ de Mars from the Eiffel Tower": a view FROM the place, not OF it."""
    m = re.search(r"\bfrom\b", (title or "").lower())
    return bool(m) and not (want & set(_stem(title[:m.start()]).split()))


def free_photo(query, out_path, used=None):
    """openverse_image over the query's variants, most specific first. A flag
    ("flag of X") is searched as is: no shorter variant ("flag" alone would
    bring back any flag)."""
    last = None
    variants = [re.sub(r"\s+", " ", query.strip().lower())] if _FLAG_RE.match(query or "") else query_variants(query)
    for v in variants:
        try:
            got = openverse_image(v, out_path, used)
            if v != (query or "").strip().lower():
                print(f"   🔎 free photo: {query!r} -> {v!r}")
            return got
        except Exception as e:
            last = e
            time.sleep(0.6)
    raise RuntimeError(f"no free photo for {query!r} ({last})")


def openverse_image(query, out_path, used=None):
    """Best reusable photo for ``query``: CC0 / public domain / CC BY only
    (reuse and edits allowed), big enough, and actually ABOUT the query —
    every word of it in the title or tags ("needle" must not bring back the
    Space Needle... unless the title is only that). ``used``: URLs already
    taken by this clip. Returns (path, credit or None)."""
    import httpx
    qt = _stem(query).split()
    want = set(qt)
    used = used if used is not None else set()
    fm = _FLAG_RE.match(query or "")
    flag_name = re.sub(r"\W+", " ", fm.group(1).lower()).strip() if fm else None

    def flag_title(x):
        t = re.sub(r"^file:", "", (x.get("title") or "").strip().lower())
        t = re.sub(r"\s*\([^)]*\)\s*$", "", t)                # "(2024-present)"
        return re.sub(r"\W+", " ", t).strip() == f"flag of {flag_name}"

    def relevance(x):
        words = set(_stem(" ".join([x.get("title") or ""] + [t.get("name", "") for t in (x.get("tags") or [])])).split())
        title = set(_stem(x.get("title") or "").split())
        extra = len(title - want)
        # A title that BEGINS with the place ("Grand Canyon National Park") is about it;
        # "Bighorn, Grand Canyon" is a sheep. A flag: the clean flat file (svg) first.
        toks = _stem(x.get("title") or "").split()
        starts = int(toks[:len(qt)] == qt)
        return (int(bool(flag_name) and (x.get("filetype") or "").lower() == "svg"), len(want & words), starts, -extra)

    with httpx.Client(timeout=20, headers=UA, follow_redirects=True) as http:
        r = http.get(OPENVERSE, params={"q": query, "license": "cc0,pdm,by", "page_size": 20,
                                        "mature": "false", "extension": "jpg,png,svg" if flag_name else "jpg,png",
                                        # Wikimedia Commons only: its licences are reviewed; Flickr's
                                        # are whatever the uploader claimed (a Peanuts strip "CC BY").
                                        "source": "wikimedia"})
        r.raise_for_status()
        min_w, min_h = (800, 500) if flag_name else (1000, 650)
        results = [x for x in r.json().get("results", [])
                   if (x.get("width") or 0) >= min_w and (x.get("height") or 0) >= min_h and x.get("url") not in used
                   and 0.5 <= (x.get("height") or 1) / (x.get("width") or 1) <= 2.0
                   and not (_UGLY_TITLE_NOFLAG if flag_name else _UGLY_TITLE).search(x.get("title") or "")
                   and relevance(x)[1] >= max(1, (len(want) + 1) // 2)
                   and (flag_title(x) if flag_name else not _seen_from(x.get("title"), want))]
        results.sort(key=relevance, reverse=True)
        for x in results[:6]:
            try:
                img = None
                for attempt in range(3):
                    img = http.get(_wikimedia_thumb(x["url"])
                                   if (x.get("width") or 0) > 1280 or x["url"].lower().endswith(".svg") else x["url"],
                                   timeout=30)
                    if img.status_code != 429:
                        break
                    time.sleep(2 + 3 * attempt)
                img.raise_for_status()
                Image.open(io.BytesIO(img.content)).convert("RGB").save(out_path, quality=92)
            except Exception:
                continue
            used.add(x.get("url"))
            if not _looks_good(out_path, flat=bool(flag_name)):
                continue
            lic = (x.get("license") or "").upper()
            credit = None
            if lic == "BY":
                credit = (f"\"{(x.get('title') or 'image')[:60]}\" by {(x.get('creator') or 'unknown')[:40]} "
                          f"(CC BY {x.get('license_version') or ''}".strip() + ")")
            return out_path, credit
    raise RuntimeError(f"no free photo for {query!r}")


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
}


def _border(name, edge_px, idx):
    """(edge width px, edge alpha, shadow alpha, shadow blur factor) for a border style; idx 0 = small card, 1 = big."""
    b = BORDERS.get(name) or BORDERS["soft"]
    w = 0 if not b["edge"] else max(2, int(round(edge_px * b["edge"])))
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
    else:
        band_top, band_bottom = cap_bottom + gap, int(H * PLATFORM_UI)
        ch_max = int(H * RISE_HARD_BOTTOM) - band_top
    pad = max(8, int(W * 0.016)) * 2
    wanted = int(W * max(18, min(60, int(size_pct))) / 100)
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


def _rise_frames(src, folder, fps, dur, W, H, size_pct, position="below", y_pct=None, enter="rise", zoom="soft",
                 border="soft"):
    """PNG sequence of the rising card, drawn in a fixed canvas; the canvas
    itself moves up through the overlay's ``y`` expression. Returns
    (pattern, x, motion) where motion = (y_start, y_end, drift, canvas_h)
    for the canvas centre."""
    img = Image.open(src).convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.07)
    img = ImageEnhance.Color(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.15)
    iw, ih = img.size
    cap_top, cap_bottom = _caption_band(H)
    shadow = max(8, int(W * 0.016))
    pad = shadow * 2
    aspect = min(max(ih / iw, 0.75), 1.25)
    box = _rise_box(cap_top, cap_bottom, position, size_pct, aspect, W, H, y_pct)
    cw, ch, y_end = box["cw"], box["ch"], box["y_end"]
    radius = int(cw * 0.07)
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
        zoom = _push_in(f, n, zmax)
        vw, vh = cw * zmax / zoom, ch * zmax / zoom
        x0, y0 = (big.width - vw) / 2, (big.height - vh) / 2
        photo = big.crop((int(x0), int(y0), int(x0 + vw), int(y0 + vh))).resize((cw, ch), Image.BILINEAR)
        unit = shade.copy()
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        card.paste(photo, (0, 0), mask)
        card.alpha_composite(rim)
        unit.alpha_composite(card, (pad, pad))
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
    # small, just outside the edge nearest to where it lands: the bottom one, or the top one for a card placed
    # in the upper half
    y_start = -ch * 0.3 / 2 if y_pct is not None and y_end < H / 2 else H + ch * 0.3 / 2
    if enter == "fade":
        y_start = y_end                                # it does not travel
    # No drift once it has landed: overlay positions snap to even pixels, so a
    # slow slide shows as little jumps (the slow push-in inside the photo,
    # drawn in the frames, is what keeps it alive).
    return os.path.join(folder, "c%03d.png"), (W - cvw) // 2, (y_start, y_end, 0, cvh)


def _hero_frames(src, folder, fps, dur, W, H):
    """PNG sequence (RGBA) of a full-screen "hero" picture, the way a cutaway is
    cut in a documentary: the image covers the frame (centre crop), pushes in
    slowly (1.00 -> HERO_PUSH, eased over its whole time on screen) and
    crossfades in and out over HERO_FADE s — the podcast stays sharp underneath,
    no blur. Every frame is resampled with LANCZOS straight from the source with
    a sub-pixel box, so the move is smooth (zoompan rounds its window to whole
    pixels and shimmers on a slow zoom). A soft vignette, a dark gradient at the
    bottom (the captions stay readable on a bright picture) and a fine film
    grain that changes every frame finish it. Returns the frame pattern."""
    import numpy as np
    img = Image.open(src).convert("RGB")
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


class ComfyDown(RuntimeError):
    """The local GPU (ComfyUI) is off or failed: B-roll images are made only
    there, so the whole job stops instead of shipping clips without them."""


def add_broll(clip_path, out_path, clip, transcript, start, end, cfg, api_key=None, keep_dir=None, keep_prefix="",
              ground_hook=False):
    """Cut up to cfg["max"] (1-10) images into ``clip_path``. Returns a report dict
    ({items, credits, planner, sources}) or None when nothing was added.
    ``keep_dir``: keep each image there (``<keep_prefix>broll_<k>.jpg``, named
    in its item as ``image``) so a restyle can re-apply them."""
    import viral_fx
    words = viral_fx.clip_words(transcript, start, end)
    if len(words) < 10:
        return None
    if not comfy_available():
        raise ComfyDown(f"ComfyUI not reachable at {_comfy_url()} (start it in Pinokio)")
    density = cfg.get("density") if cfg.get("density") in DENSITY else "normal"
    n = image_count(max(1, min(10, int(cfg.get("max") or 6))), density)
    auto_style = cfg.get("style") == "auto"
    style = cfg.get("style") if cfg.get("style") in STYLES else "photo"
    engine = cfg.get("engine") if cfg.get("engine") in ENGINES else "zimage"
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
        """Which family of picture this moment gets: hero / small card, or the profile's single layout."""
        if mixed:
            return "hero" if m.get("hero") else "rise"
        return "rise" if rise else "full"

    def make_image(prompt, m_style, raw, query, used_urls, sheet=None, layout=None):
        """(path, "local", None) from ComfyUI; raises ComfyDown when it fails."""
        try:
            return local_image(prompt, m_style, raw, engine=engine,
                               size=_gen_size(layout if layout is not None else ("rise" if rise else "full"), hero_res),
                               look=look_text(sheet, m_style)), "local", None
        except Exception as e:
            raise ComfyDown(f"ComfyUI image failed: {str(e)[:200]}") from e

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
                                               real_photos=bool(cfg.get("real_photos")), density=density,
                                               hero=mixed)
                    planner = "claude"
                    if not moments:
                        print("   ℹ️ B-roll: Claude found no moment where an image would add meaning — none added.")
                        return None
                except Exception as e:
                    print(f"   ⚠️ B-roll planning via Claude failed ({str(e)[:200]}) — Gemini instead.")
            else:
                print("   ⚠️ B-roll planner is Claude but it is not set up "
                      "(claude CLI / CLAUDE_CODE_OAUTH_TOKEN) — Gemini instead.")
        if not moments and api_key:
            try:
                import ai_brain
                ai_brain.say("Gemini — Claude unavailable", "B-roll: choosing the images")
                moments = plan_with_gemini(clip, words, n, avoid, api_key, auto_style)
                planner = "gemini"
            except Exception as e:
                print(f"   ⚠️ B-roll planning via Gemini failed ({e}) — local pick instead.")
        if not moments:
            # The local pick only knows words, not what they mean ("needle" ->
            # the Space Needle): no B-roll beats a wrong one.
            print("   ℹ️ B-roll skipped: moments need the Claude or Gemini planner (not set up or call failed).")
            return None
        if mixed:
            # The code has the last word on the hero: the planner's pick counts, the timing rules win.
            k_hero = pick_hero(moments, words[-1]["end"], avoid)
            for i, m in enumerate(moments):
                m["hero"] = i == k_hero
            if k_hero is None:
                print("   ℹ️ B-roll: no moment of this clip reads well on a whole screen — small cards only.")

        used_urls, cands = set(), []
        for k, m in enumerate(moments):
            m_style = (m.get("style") or "photo") if auto_style else style
            m_layout = item_layout(m)
            raw = os.path.join(tmp, f"broll_{k}.jpg")
            kept = notion_get(m.get("notion"), m_style, engine, m_layout, raw) if m.get("notion") else None
            if kept:
                print(f"   ♻️ Notion \"{m['notion']}\": the channel's picture is reused (no image made, no review).")
                cands.append({"k": k, "m": m, "style": m_style, "file": kept, "source": "local", "credit": None,
                              "score": 5, "reused": True, "layout": m_layout})
                continue
            if cfg.get("real_photos") and m.get("real_photo") and not m.get("notion"):
                try:
                    photo, credit = free_photo(m["query"], raw, used_urls)
                    print(f"   📷 Real photo for \"{m['query']}\"" + (f" (credit: {credit})" if credit else ""))
                    cands.append({"k": k, "m": m, "style": "photo", "file": photo, "source": "free", "credit": credit,
                                  "layout": m_layout})
                    continue
                except Exception as e:
                    print(f"   ℹ️ No real photo for \"{m['query']}\" ({str(e)[:80]}) — image generated instead.")
            # A notion's picture is the channel's usual one, kept for other clips:
            # made without this clip's look.
            got, used, credit = make_image(m["prompt"], m_style, raw, m["query"], used_urls,
                                           None if m.get("notion") else m.get("sheet"), layout=m_layout)
            if got:
                cands.append({"k": k, "m": m, "style": m_style, "file": got, "source": used, "credit": credit,
                              "layout": m_layout})

        # Claude checks every image against the idea it must carry; a weak
        # generated one is redone once from its better prompt, then dropped
        # if it is still not clear.
        if planner == "claude" and any(not c.get("reused") for c in cands):
            try:
                checked = [c for c in cands if not c.get("reused")]
                reviews = review_images(checked, words)
                redo = []
                for c, r in zip(checked, reviews):
                    c["score"] = int(r.get("score") or 3)
                    if c["score"] <= 3 and r.get("better_prompt"):
                        raw = os.path.join(tmp, f"broll_{c['k']}_v2.jpg")
                        got, used, credit = make_image(r["better_prompt"], c["style"], raw, c["m"]["query"],
                                                       used_urls, None if c["m"].get("notion") else c["m"].get("sheet"),
                                                       layout=c["layout"])
                        if got:
                            redo.append((c, {**c, "file": got, "source": used, "credit": credit,
                                             "m": {**c["m"], "prompt": r["better_prompt"]}}))
                if redo:
                    for (c, c2), r2 in zip(redo, review_images([c2 for _, c2 in redo], words)):
                        if int(r2.get("score") or 3) > c["score"]:
                            c.update(c2, score=int(r2.get("score") or 3))
                kept = _keep_meaningful(cands)
                print(f"   🔎 B-roll review: scores {[c['score'] for c in cands]}"
                      f"{f', {len(redo)} redone' if redo else ''}, {len(kept)}/{len(cands)} kept")
                for c in kept:
                    if c["m"].get("notion") and not c.get("reused") and c["score"] >= NOTION_MIN_SCORE:
                        if notion_put(c["m"]["notion"], c["style"], engine, c["layout"], c["file"], c["m"]["prompt"],
                                      c["score"]):
                            print(f"   📚 Notion \"{c['m']['notion']}\": picture kept for the next clips.")
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
            elif _hold(cfg.get("hold")):
                dur = _hold(cfg.get("hold"))               # the user's own time on screen
            elif big:
                dur = round(max(FULL_DUR_MIN, min(FULL_DUR_MAX, dur)), 2)
            item = {"t": round(m["t"], 2), "dur": dur, "anchor": m["anchor"],
                    "idea": m.get("idea") or "", "role": m.get("role"), "query": m["query"], "prompt": m["prompt"],
                    "source": c["source"],
                    "style": c["style"] if c["source"] in ("local", "gemini") else "photo",
                    "layout": "hero" if hero else ("full" if big else "rise"), "_img": c["file"]}
            if mixed:
                # The size the picture was made at: a manual redo asks for the same one.
                item["gen"] = list(_gen_size(c["layout"], hero_res))
            if m.get("sheet") and not m.get("notion"):
                item["sheet"] = m["sheet"]      # kept: a manual redo keeps the clip's look
            if m.get("notion"):
                item["notion"] = m["notion"]
                if c.get("reused"):
                    item["reused"] = True
            if c.get("score"):
                item["score"] = c["score"]
            item["zoom"] = cfg.get("zoom") if cfg.get("zoom") in ZOOM_LEVELS else "soft"
            item["border"] = cfg.get("border") if cfg.get("border") in BORDERS else "soft"
            if not big and not hero:
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
            return None
        if _hold(cfg.get("hold")) or mixed:
            # A fixed time on screen (or a hero longer than its sentence): two pictures never overlap, the
            # first one leaves a little early
            for a, b in zip(items, items[1:]):
                a["dur"] = round(max(1.0, min(a["dur"], b["t"] - a["t"] - 0.25)), 2)
        # "manual" review: the images are kept next to the clip and listed, but
        # nothing is cut in until the user approves them (app.py .../broll/apply).
        manual = cfg.get("review") == "manual" and bool(keep_dir)
        if not manual:
            overlay_items(clip_path, out_path, items)
        for it in items:
            it.pop("_img", None)
        return {"items": items, "credits": credits, "planner": planner, "sources": sources, "pending": manual}
    finally:
        if used_local:
            comfy_release()
        shutil.rmtree(tmp, ignore_errors=True)


def regenerate_image(prompt, style, out_path, query="", cfg=None, api_key=None, sheet=None, gen=None):
    """One image again, from a new prompt / style (the manual review), on the
    local GPU. ``gen``: the (width, height) the first picture was made at (the
    item's "gen"), else the layout's usual size. Returns (path, source, credit);
    raises when nothing came."""
    cfg = cfg or {}
    style = style if style in STYLES else "photo"
    engine = cfg.get("engine") if cfg.get("engine") in ENGINES else "zimage"
    rise = cfg.get("layout") == "rise"
    try:
        size = (int(gen[0]), int(gen[1])) if gen else (RISE_GEN if rise else (768, 1344))
    except (TypeError, ValueError, IndexError):
        size = RISE_GEN if rise else (768, 1344)
    if not comfy_available():
        raise RuntimeError("ComfyUI is not reachable (start it in Pinokio)")
    try:
        return local_image(prompt, style, out_path, engine=engine, size=size, look=look_text(sheet, style)), "local", None
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
            rise = it.get("layout") == "rise"
            hero = it.get("layout") == "hero"
            try:
                dur = float(it.get("dur") or (RISE_DUR if rise else SEG_DUR))
            except (TypeError, ValueError):
                dur = RISE_DUR if rise else SEG_DUR
            dur = max(1.0, min(4.0, dur))
            if hero:
                pattern = _hero_frames(src, folder, fps, dur, w, h)
                layers.append({"t": it["t"], "dur": dur, "rise": False, "hero": True, "pattern": pattern, "x": 0, "y": 0})
            elif rise:
                pattern, x, motion = _rise_frames(src, folder, fps, dur, w, h, int(it.get("size") or RISE_SIZE),
                                                  it.get("position") or "below", _free_y(it.get("y")),
                                                  it.get("enter") if it.get("enter") in ENTER_MODES else "rise",
                                                  it.get("zoom") if it.get("zoom") in ZOOM_LEVELS else "soft",
                                                  it.get("border") if it.get("border") in BORDERS else "soft")
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
                ys, ye, drift, cvh = ly["y"]
                # Canvas centre: eases up from under the frame (cubic), then
                # drifts up ``drift`` px while on screen (0: it stays put).
                y = (f"'{ys:.1f}+({ye:.1f}-{ys:.1f})*(1-pow(1-clip((t-{ly['t']:.3f})/{RISE_IN},0,1),3))"
                     f"-{drift}*clip((t-{ly['t']:.3f}-{RISE_IN})/{ly['dur'] - RISE_IN:.3f},0,1)-{cvh / 2:.1f}'")
                graph.append(f"{cur}[{k + 1}:v]overlay=x={ly['x']}:y={y}:eval=frame:eof_action=pass:"
                             f"enable='{win}'[b{k}]")
            else:
                graph.append(f"{cur}[{k + 1}:v]overlay={ly['x']}:{ly['y']}:eof_action=pass:enable='{win}'[b{k}]")
            cur = f"[b{k}]"
        graph[-1] = graph[-1][:graph[-1].rfind("[")] + "[v]"
        # An intermediate layer: the hook and the captions re-encode it (ffmpeg_utils.layer_encode_args).
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip_path, *inputs, "-filter_complex", ";".join(graph),
                        "-map", "[v]", "-map", "0:a?",
                        *layer_encode_args(["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"]),
                        "-c:a", "copy", "-movflags", "+faststart", out_path], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sources(api_key=None, style="photo", engine="zimage"):
    """For the profile editor's "test" button: does Claude (subscription)
    answer, does the local GPU (ComfyUI) answer, can Gemini make an image on
    this key, and do free photos come through? Never raises."""
    out = {"claude": None, "gemini": None, "free": None, "local": None}
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
                            os.path.join(tmp, "l.jpg"), engine=engine)
                out["local"] = f"ok ({time.time() - t0:.0f} s)"
            except Exception as e:
                out["local"] = "error: " + str(e)[:220]
            finally:
                comfy_release()
        else:
            out["local"] = "offline"
        if api_key:
            try:
                gemini_image("A close-up of fresh green kratom leaves on a wooden table.", style, api_key,
                             os.path.join(tmp, "g.jpg"))
                out["gemini"] = "ok"
            except Exception as e:
                msg = str(e)
                out["gemini"] = ("billing" if re.search(r"billing|quota|RESOURCE_EXHAUSTED|429|limit: 0", msg, re.I)
                                 else "error") + ": " + msg[:220]
        else:
            out["gemini"] = "no key"
        try:
            openverse_image("brain scan", os.path.join(tmp, "f.jpg"))
            out["free"] = "ok"
        except Exception as e:
            out["free"] = "error: " + str(e)[:220]
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
