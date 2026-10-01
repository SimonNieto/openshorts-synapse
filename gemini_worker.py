import argparse
import json
import os
import sys
from typing import List, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types
from pydantic import BaseModel

from clip_selection import (clip_count_targets, clip_duration_bounds,
                            lookup_model_prices)

load_dotenv()


# --- Structured output schemas (passed as response_schema so the API
# --- guarantees the format instead of us repairing free-form JSON). ---

class ScoredWindowModel(BaseModel):
    id: str
    start: float
    end: float
    score: int
    reason: str


class ScoreResponse(BaseModel):
    windows: List[ScoredWindowModel]


class DetailClipModel(BaseModel):
    start: float
    end: float
    source_window_id: str
    predicted_score: int
    video_description_for_tiktok: str
    video_description_for_instagram: str
    video_title_for_youtube_short: str
    viral_hook_text: str
    # A content-niche guess for the whole SOURCE video, not just this clip —
    # asked per-clip only because the response schema has no other place to
    # put a video-level field; main.get_viral_clips picks the first non-empty
    # one across all returned clips and drops the field from what gets saved.
    content_niche: str = ""
    # Final-judge mode (a faster model pre-scored the windows): one sentence on
    # why this moment beat the others. Saved with the clip, never shown.
    why_chosen: str = ""


class DetailResponse(BaseModel):
    shorts: List[DetailClipModel]


# Clip Generator++ BETA ("selection v2"): same clip + the exact spoken lines
# the cut is built on, so main.py can start ON the hook sentence and end on
# the punchline instead of trusting Gemini's timestamps alone. Only used when
# SELECTION_V2=1; the classic schema above is untouched.
class DetailClipModelV2(DetailClipModel):
    hook_line: str = ""      # verbatim: the sentence the clip OPENS on
    punchline: str = ""      # verbatim: the strongest line / payoff


class DetailResponseV2(BaseModel):
    shorts: List[DetailClipModelV2]


# Clip Generator++ BETA "Synapse Cut playbook" (SYNAPSE_PLAYBOOK=1): the V2
# fields (hook_line drives the start, main.align_hook_and_punchline) + the
# topic family of the moment, for the channel's stats (playbook.py).
class DetailClipModelPlaybook(DetailClipModelV2):
    topic_bucket: str = ""


class DetailResponsePlaybook(BaseModel):
    shorts: List[DetailClipModelPlaybook]


DETAIL_V2_ADDENDUM = """
SELECTION V2 (strict):
- THE OPENING LINE IS THE HOOK: the clip starts EXACTLY on a sentence that works
  as a hook when heard cold — a bold claim, a confession, a surprising number, a
  "you" statement, or a question. Never on "so", "um", "yeah", "and", "I mean",
  "you know", a greeting, or the middle of a thought. Return that sentence
  VERBATIM (exact transcript words) in `hook_line`.
- END ON THE PUNCHLINE: the strongest line — the payoff, the verdict, the twist —
  is the last or nearly last thing said. Return it VERBATIM in `punchline`. Cut
  the trailing "yeah, anyway", laughter and follow-up chatter after it.
- WHAT TRAVELS: prefer moments about the viewer's own life (relationships, being
  single or alone, friends, confidence, discipline, money habits, how people
  think), or that EXPOSE how an everyday thing really works (apps, food, stores,
  jobs). Rank purely informational, medical or insider topics lower.
- A clip that needs no context, opens on its hook and closes on its punchline in
  15-35 s beats a longer, more complete one.
"""

# Clip Generator++ (profile: selection.clip_target -> CLIP_TARGET_MIN/MAX_SECONDS).
# "LENGTH IS A CEILING, NOT A TARGET" alone gave 11 clips of 37-59 s in a
# 15-60 band (JRE #2515): a range to aim for is what the model follows. The
# second block is added when the schema has `punchline` (selection v2 or the
# playbook): main.trim_to_target cuts an over-long clip right after it.
TARGET_LENGTH_ADDENDUM = """
TARGET LENGTH (strict, wins over the length rules above): aim for {lo:g}-{hi:g}
seconds. {min_secs:g}-{max_secs:g}s stays the hard limit, but a clip longer than
{hi:g}s is the exception: only when cutting it shorter would lose the payoff
itself. A moment that lands in {lo:g}-{hi:g}s and stops beats the same moment
with 20 more seconds of follow-up. Choose `start` and `end` for that length
from the beginning — do not pick a long passage and hope it gets trimmed.
The target also wins over STANDS ALONE and "start slightly before the hook":
when a moment runs long, open LATER, on a later sentence that still stands
alone, never earlier. One sentence of setup is all a cold viewer needs; the
payoff stays, the run-up goes. And {lo:g}s is a floor as much as {hi:g}s is a
ceiling: a clip under {lo:g}s has cut into its setup or its payoff, do not
go under it to be safe.
"""

# Clip Generator++ (selection.clip_target, playbook): the clips still over
# the target after trim_to_target — every one of them ends on its payoff, so
# the only cut left is a later opening. One call for all of them
# (main.shorten_to_target), the model choosing among sentence starts that
# the code measured to land inside the target.
OPEN_LATER_PROMPT = """
These clips run longer than the target of {lo:g}-{hi:g} seconds and each one
ends on its payoff, so the only way to shorten one is to open it LATER. For
each clip you get its title, its payoff (the line it ends on), its current
on-screen hook and the sentences it could open on instead, each with the
seconds that would remain from there to the end (every candidate lands the
clip inside the target: choose for quality). Pick, per clip, the opening that:
- stands alone: a cold viewer who hears nothing before it still follows — no
  "that", "so anyway", no answer to a question nobody heard;
- hooks: a claim, a stake, a number, a question in the air; never a filler
  nor an aside;
- keeps the clip's point: the payoff must still land from there.
Return `open_on`, the number of the chosen candidate. If the current hook no
longer fits the new opening, write a new one in `viral_hook_text` (max
{hook_words} words, in {language}: a statement, concrete, understood cold, no
name, it teases the payoff and never tells it); else leave it "".

CLIPS_JSON:
{clips}

Return only: {{"clips": [{{"id": <clip id>, "open_on": <candidate number>, "viral_hook_text": ""}}]}}
"""

OPEN_LATER_SCHEMA = {
    "type": "object",
    "properties": {"clips": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "open_on": {"type": "integer"},
                       "viral_hook_text": {"type": "string"}},
        "required": ["id", "open_on"]}}},
    "required": ["clips"],
}


TARGET_PAYOFF_ADDENDUM = """- THE PAYOFF ENDS THE CLIP: return the payoff — the line the clip exists
  for — VERBATIM (exact transcript words) in `punchline`, and place `end` right
  after it. What follows it (agreement, laughter, a new thought) is cut.
"""

# Clip Generator++ (profile: selection.audio_signals -> AUDIO_SIGNALS=1): the
# scoring windows carry an `audio` object (audio_signals.window_features) and
# the scoring prompt this note on how to read it. ~25 tokens a window.
AUDIO_SIGNALS_ADDENDUM = """
AUDIO CUES: each window has an `audio` object measured on the sound itself,
which the transcript cannot show. Levels are relative to this episode's usual
speaking level (1.0).
- `loud`: the average level. `peak`: the loudest half second. `var`: how much
  the level moves (0.3 is a flat delivery, 0.6 and more a lively one).
- `wps`: words per second (this episode's usual rate is {wps:g}). Clearly
  faster means urgency or excitement.
- `react`: the level of what is heard BETWEEN the words — laughter, gasps,
  people talking over each other (0 = no gap). Above ~0.4 the room reacted.
- `pause`: the longest silence, in seconds. A long pause before a line is how
  a speaker sets up a punchline or a heavy statement.
Use them to confirm and to break ties: a window whose text reads strong AND
whose sound is lively (high `var`, `react` or `peak`) beats the same text
delivered flat. Never pick a window on its sound alone, and never mark down a
strong text because it is said calmly.
"""

FINAL_JUDGE_ADDENDUM = """
YOU ARE THE FINAL JUDGE: a faster model read the whole video and pre-scored
these windows (`prescore`, `prescore_reason` in each window). It is a first
sort, not a verdict — trust your own reading of the text over its score, and
leave out a window that does not hold a strong clip that stands alone, even if
it scored high. For every clip you keep, fill `why_chosen`: one sentence on why
this moment beats the others (the hook, the payoff, why a cold viewer stays).
"""

SERIES_TITLE_ADDENDUM = """
SERIES TITLES (strict): write `video_title_for_youtube_short` as a recognisable
series title, max 60 characters, in one of these shapes:
- "{name} On <topic of this moment>."
- "{name} Exposes <everyday thing>!"
- "{name}'s Brutal Take On <topic>"
then add 1-2 fitting emojis at the end. The topic names THIS moment, concretely.
"""

# Clip Generator++ BETA "Synapse Cut playbook" — every place that writes a
# title or an on-screen hook appends this (detail pass, hook grounding, the
# B-roll planner's hook, regenerate-copy). Measured on the channel: the same
# clip got 7,100 views as "Can a brain tumor make you a killer?" and 1,300
# as "The Brain Tumor That Made a Murderer"; titles with the guest's name
# ("Huberman Explains") did worse.
QUESTION_TITLE_ADDENDUM = """
SYNAPSE CUT PLAYBOOK — TITLE AND HOOK (strict, wins over any other title or hook rule above):
- `video_title_for_youtube_short` is ONE question a curious viewer would ask
  about this moment, max 60 characters, ending with "?". It names the concrete
  thing of the clip. Never a statement, never a label ("The Brain Tumor That
  Made a Murderer" is wrong).
- THE TITLE MUST START WITH Can, Is, Does, Are, Do, Will or Should — a closed
  question that creates a doubt: the viewer must guess yes or no and watch to
  find out:
  "Can X make you Y?", "Is X actually Y?", "Does X really Y?"
  ("Can a brain tumor make you a killer?", "Does cannabis really cause
  psychosis?", "Is frustration a sign you should quit?").
  "Why..." is allowed for at most 1 in 6 of the clips you return (none when you
  return fewer than 6): it is an open question, the closed ones are what the
  channel's numbers favour. "How..." and "What..." titles are FORBIDDEN.
- NAME THE SUBJECT: the title says what the clip is about in plain words —
  never "this show", "one show", "this guy", "he", "they". "How did this show
  sell out Madison Square Garden twice?" is wrong; "Can a small comedy show
  really sell out Madison Square Garden?" is right.
- THE QUESTION NEVER CONTAINS ITS OWN ANSWER: "Why does frustration mean your
  brain is learning?" gives the answer away (frustration = learning); "Is
  frustration a sign you should quit?" keeps it for the clip.
- NO NAMES in the title or the hook: not the guest, not the host, not the
  podcast, not any expert ("Huberman explains...", "Rogan on..." are wrong).
  Say "a neuroscientist" or "a doctor" only if the role IS the hook; usually
  say nothing. Names belong to the description only.
- SENSITIVE WORDS: never write "suicide", "suicidal", "kill myself/yourself",
  "self-harm", "cutting" or any other explicit word for suicide or self-injury in
  the title or the hook. Say it soberly instead ("his darkest moment", "when the
  pain gets too loud", "a mental health crisis").
- DRUGS (any substance, psychedelic, kratom, alcohol, medication): the angle is
  always educational or preventive — what it does to the brain or the body, the
  risk, what people don't know. Never make it sound fun or cool, never how to get,
  dose or use it. "Is kratom really as harmless as people think?" is right; "The
  high nobody talks about" is wrong.
- TRUE TO THE CLIP: the question is one this clip actually answers or explores.
  No fake claims, no promise the clip does not keep.
- `viral_hook_text` (the on-screen hook) NEVER REPHRASES THE TITLE: it adds what
  the title does not say — a stake, a tension or a promise. Max 8 words. Not a
  question (the title already is one). No name. Same sensitive-word and drug
  rules as the title. Title "Should men be afraid of testosterone therapy?" ->
  hook "Most doctors won't tell you this." (not "Should you be afraid of
  testosterone therapy?", which only repeats the title).
"""

# Clip Generator++ (profile: selection.title_variety -> TITLE_VARIETY=1, with
# the playbook): JRE #2515 (1-oct-2026) came back with "DMT" in 4 titles of 6
# and "really / truly / just / ever" in 4 of 6 — each title fine alone, the
# set reading like one short posted four times. Said to the model here;
# checked in code after the pass (playbook.title_set_problems).
TITLE_VARIETY_ADDENDUM = """
TITLES AS A SET (strict): the clips you return are posted one after the other
on the same channel. Read together, their titles must not look like one short
posted four times:
- the same key word (a substance, an organ, a condition, a thing) carries at
  most TWO titles; the other clips on that subject take another angle — the
  consequence, the person, the mechanism, the number, the risk;
- "really", "actually", "truly", "just", "ever" pad a question: at most ONE
  title of the batch uses one of them, a plain question is stronger;
- alternate the openers (Can / Is / Does / Are / Do / Will / Should) instead of
  starting every title the same way.
"""

# Clip Generator++ BETA "Synapse Cut playbook" — added to the SCORING prompt
# (brief + scoring pass) and to the clip choice: the channel stays off topics
# that divide its young, general audience, however well they would perform.
SAFETY_TOPICS_ADDENDUM = """
SYNAPSE CUT PLAYBOOK — OFF-LIMITS TOPICS (strict): leave out every moment CENTRED
on politics (parties, politicians, government, left vs right), abortion,
religion (faith, God, churches, religious debates), elections or voting, or guns
and weapons (gun laws, firearms, shootings) — even when it is divisive, funny or
likely to go viral. When scoring, give such a window 0-10 and do not pick it;
when choosing clips, never return one: pick another moment. A passing mention
inside a moment about the brain, psychology, substances or mental health is
fine — the moment itself must not be ABOUT these topics.
"""

# Clip Generator++ BETA "Synapse Cut playbook" + a niche (profile:
# selection.niche_topics). The playbook only said what the channel stays OFF;
# nothing said what it is ABOUT, and 4 of the 11 clips of JRE #2515 were UFC
# recaps on a neuroscience channel. {niche} is playbook.niche_sentence(),
# {policy} one of the two lines below (niche_only, or a score weight).
NICHE_SCORE_ADDENDUM = """
SYNAPSE CUT PLAYBOOK — THE CHANNEL'S NICHE: this channel is about {niche}.
Its viewers come for that and nothing else. Score a window by how strong a
moment it holds ON THAT NICHE. A window about anything else (sport results and
fight recaps, show business, comedy bits, money, tech, small talk) {policy}
A moment from another field counts only when its point IS the niche (what a
knockout does to the brain, how a champion's mind handles fear).
"""
NICHE_SCORE_ONLY = "gets 0-30 however entertaining it is, and is not picked."
NICHE_SCORE_WEIGHT = "loses about {weight:g} points, however entertaining it is."

NICHE_DETAIL_ADDENDUM = """
SYNAPSE CUT PLAYBOOK — THE CHANNEL'S NICHE: this channel is about {niche}.
- {policy}
  This overrides the HOW MANY rule above: returning fewer clips than asked, or
  skipping most windows, is right when the rest is off niche. Never pad with an
  off-niche clip.
- `topic_bucket` also accepts, for a moment outside the niche: sports_combat,
  entertainment, business_money, other. Label by what the clip is ABOUT, not
  by the angle that would make it fit: a fight recap is sports_combat even
  when the fighter shows grit; a comedian's career story is entertainment even
  when it mentions discipline.
"""
NICHE_DETAIL_ONLY = ("Return clips on that niche ONLY. A candidate window about anything else yields "
                     "NOTHING, however strong the moment.")
NICHE_DETAIL_WEIGHT = ("Strongly prefer clips on that niche. A moment outside it is returned only when "
                       "it is exceptional.")

# Detail pass only (with QUESTION_TITLE_ADDENDUM): the start is cut on
# hook_line (main.align_hook_and_punchline, without the V2 punchline end),
# the description gets a closing question (the credit line with the names is
# added in code, playbook.prepare), topic_bucket feeds the stats.
PLAYBOOK_DETAIL_ADDENDUM = """
SYNAPSE CUT PLAYBOOK — CUT, DESCRIPTIONS, TOPIC:
- THE OPENING LINE IS THE HOOK: the clip starts EXACTLY on a sentence that works
  when heard cold — a bold claim, a confession, a surprising fact, a "you"
  statement, or a question. Never on "so", "um", "yeah", "and", "I mean", "you
  know", a greeting, or the middle of a thought. Return that sentence VERBATIM
  (exact transcript words) in `hook_line`.
- `start` IS THE MOMENT `hook_line` BEGINS — never after it (a start placed after
  the hook opens the clip mid-sentence). If the clip then runs over
  {max_secs}s, end it earlier on a complete sentence; never start later to
  save time.
- DESCRIPTIONS (TikTok + Instagram): 1-2 sentences that tease the payoff
  without spoiling it, then ONE short question to the viewer that invites a
  comment ("Would you have noticed the signs?"), then 3-5 hashtags. Do not
  write a "clip from..." or credit line: it is added automatically. Names of
  the guest / host may appear in the description, never in the title.
- `topic_bucket`: exactly one of brain_danger, substances,
  psychosis_mental_illness, crime_dark, medical_mystery, mind_psychology,
  self_improvement, science_other.
"""

# regenerate-copy (rework.COPY_PROMPT) with the playbook on: same description
# shape as the detail pass.
PLAYBOOK_COPY_ADDENDUM = """
SYNAPSE CUT PLAYBOOK — DESCRIPTIONS: 1-2 sentences that tease the payoff, then
ONE short question to the viewer that invites a comment, then the hashtags. No
"clip from..." or credit line: it is added automatically.
"""


# Visual (no-transcript) clip selection: Gemini watches a silent video and
# picks moments from the imagery. Same output shape as DetailClipModel minus
# the transcript-only source_window_id.
class VisualClipModel(BaseModel):
    start: float
    end: float
    predicted_score: int
    video_description_for_tiktok: str
    video_description_for_instagram: str
    video_title_for_youtube_short: str
    viral_hook_text: str


class VisualResponse(BaseModel):
    shorts: List[VisualClipModel]


VISUAL_PROMPT_TEMPLATE = """
You are a senior short-form video editor. This video has NO speech/audio — judge
it purely by what you SEE. Watch the whole thing and pick the {min_clips}–{max_clips} MOST engaging
visual moments for TikTok / Reels / Shorts (action, reveals, transformations,
striking or funny shots, satisfying payoffs, dramatic movement).

TIME CONTRACT — STRICT:
- Timestamps in ABSOLUTE SECONDS from the start (usable with ffmpeg -ss/-to).
- Only numbers with up to 3 decimals (e.g. 0, 12.5, 47.250).
- 0 <= start < end <= {video_duration}.
- Each clip {min_secs:g} to {max_secs:g} seconds long. If the whole video is
  shorter than {min_secs:g}s, return one clip spanning the full video.
- Cut on visual scene changes, never mid-motion.

For each clip write catchy copy in {language} (a scroll-stopping hook, a TikTok
and an Instagram description, and a YouTube title ≤100 chars). Order clips best
to worst by how likely they are to stop a viewer scrolling.
"""


# Grounded rewrite of hook + title for a clip whose meaning lives on screen
# (SCREENCAST / WIDE / INSET stretches): the detail pass never saw a frame,
# so its hook summarises the topic instead of naming what is being shown.
class GroundedHook(BaseModel):
    on_screen: str
    viral_hook_text: str
    video_title_for_youtube_short: str


GROUNDED_HOOK_PROMPT = """
These frames come from ONE short clip (the whole clip, in order) and the
transcript below is exactly what is said during it. Most of this clip's
meaning is on the screen, not in the face.

1. `on_screen`: one line naming what is shown — the app, window, product,
   document, code, chart or on-screen text — as specifically as the frames
   allow (read visible titles and labels).
2. `viral_hook_text`: max 10 words, in TRANSCRIPT_LANGUAGE. It MUST mention
   the thing you named in `on_screen` (or the action being done to it: set
   up, connect, compare, fix, type) AND keep the strongest concrete fact of
   the clip: a number, a multiplier, a price, a name ("7x faster", "$136 a
   month", "3,400 stars") from the transcript or the current hook. Never a
   summary of the video's general topic, never a slogan that would fit any
   clip of this video, never drop a figure for a vaguer phrase.
3. `video_title_for_youtube_short`: max 100 chars, same rule, in
   TRANSCRIPT_LANGUAGE, no fake claims.

The current hook and title below were written WITHOUT seeing the frames and
are the kind of topic summary you must replace. Do not reuse their wording.

TRANSCRIPT_LANGUAGE: {language}
CURRENT_HOOK (to replace): {current_hook}
CURRENT_TITLE (to replace): {current_title}
TRANSCRIPT:
{transcript}

Return only:
{{"on_screen": "<one line>", "viral_hook_text": "<max 10 words>", "video_title_for_youtube_short": "<max 100 chars>"}}
"""


class LayoutChoice(BaseModel):
    layout: str
    confidence: float
    why: str


# Scored 94/92/96% over the 48-clip corpus against hand-checked labels, with
# 0-1 false positives out of the 28 clips that must not be touched. Do not
# reword casually: the wins come from the explicit "none is usually right"
# instruction and from naming the exact decorations (corner bugs, score
# counters, subtitles) that four earlier attempts kept mistaking for content.
LAYOUT_CHOICE_PROMPT = """
These frames are sampled at regular intervals from a single landscape video.
You are choosing how to re-frame that video into a vertical 9:16 clip.

Pick ONE layout:

- "none": crop to the speaker and fill the frame. This is the RIGHT answer for
  ordinary talking heads, interviews shot in close-up, b-roll, sport, action,
  music, and any footage whose meaning survives a centre crop. Corner logos,
  score bugs, subscriber counters, lower-thirds and burned-in subtitles do NOT
  change this: they are decoration, and losing them costs nothing.
- "screencast": keep the screen. ONLY when the video is built around a screen
  recording, slides, a spreadsheet, a chart or a map that the viewer must read
  to follow it. If you cannot read words or numbers off the screen that matter
  to the point being made, it is not this.
  (A "camera_inset" option was added here and removed on 31-jul-2026. Whether a
  webcam is composited into a corner of that screen is not something the model
  can see: on the five clips that have one it answered "screencast" every time,
  in both runs, while overall accuracy fell from 92% to 83-85%. camera_inset.py
  finds the same five geometrically with no false positives, so that question is
  answered downstream instead of being asked here.)
- "split": stack two people. ONLY when two people are visible IN THE SAME SHOT
  at the same time in most frames, talking to each other. Frames that alternate
  between one-person close-ups are NOT this, however many people appear.

"none" is by far the most common correct answer. Choose anything else only if
you would defend it to an editor. If you are unsure, answer "none".

confidence is 0..1. why is at most 12 words.
"""


class WideContentRangeModel(BaseModel):
    start: float
    end: float
    what: str
    width_fraction: float


class WideContentResponse(BaseModel):
    ranges: List[WideContentRangeModel]


WIDE_CONTENT_PROMPT_TEMPLATE = """
You are preparing a landscape video to be re-framed to a vertical 9:16 crop.
The crop keeps a tall centre strip and THROWS AWAY the left and right sides.

List every time range where on-screen content would be cut by that, and for each
one report HOW MUCH OF THE FRAME WIDTH the content spans.

width_fraction is the single most important field. Measure the content's own
horizontal extent, from its left edge to its right edge, as a fraction of the
full frame width:
- a spreadsheet, slide, screen recording or map filling the picture: 0.9 - 1.0
- a chart or diagram beside a speaker: 0.4 - 0.7
- a lower-third or headline strip across the bottom: 0.6 - 0.9
- a logo, channel bug, score counter or subscriber count in a corner: 0.1 - 0.2
- subtitles centred at the bottom: 0.3 - 0.5

Report what you actually see. Do NOT inflate the number to make a range seem
worth reporting, and do NOT leave out corner graphics — report them with their
true small width_fraction. A range reported honestly at 0.15 is useful; the same
range reported at 0.9 makes the video worse.

COUNT a range when the frame shows:
- a screen recording, slide, spreadsheet, chart, graph or map
- headlines, labels, statistics or comparison tables burned into the picture
- a side-by-side or split-screen layout
- any diagram or product shot where the edges carry the meaning

DO NOT count an ordinary talking head, even against a busy background, and do
not count b-roll, landscapes, crowds or action footage with no graphics.

TIME CONTRACT — STRICT:
- ABSOLUTE SECONDS from the start, numbers only, up to 3 decimals.
- 0 <= start < end <= {video_duration}.
- Merge ranges that are less than 1 second apart.
- Return an EMPTY list if the video never shows such content. An empty list is
  the correct, expected answer for most talking-head and b-roll videos — do not
  invent ranges to seem useful.

For "what", name the content in three words or fewer (e.g. "stock chart",
"spreadsheet", "corner ticker").
"""


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if not stream or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _log(message: str) -> None:
    stream = sys.stdout
    text = str(message)
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        stream.write(safe_text + "\n")
    stream.flush()

SCORE_PROMPT_TEMPLATE = """
You are a senior short-form video strategist.
Select the MOST viral candidate windows from this batch.

Rules:
- Return only valid JSON.
- Choose up to 3 windows from this batch.
- `score` must be an integer from 0 to 100.
- THE 2-SECOND TEST is the main criterion: would the first 2 seconds of this
  moment force a cold viewer (no context) to keep watching? Windows that only
  work with prior context score low.
- Prefer windows with strong hooks, conflict, surprise, outrage, emotion,
  novelty, big numbers, or a clear payoff.
- Ignore weak filler, housekeeping, outros, rambling transitions, and
  low-signal padding unless there is an obvious hook or payoff.

TRANSCRIPT_LANGUAGE: {language}
VIDEO_DURATION_SECONDS: {video_duration}
WINDOWS_JSON:
{windows_json}

Return only:
{{
  "windows": [
    {{
      "id": "<window id>",
      "start": <number>,
      "end": <number>,
      "score": <integer 0-100>,
      "reason": "<very short reason>"
    }}
  ]
}}
"""

DETAIL_PROMPT_TEMPLATE = """
You are a senior short-form video editor and viral copywriter.
Choose the BEST short clips from these shortlisted candidate windows.

CLIP RULES:
- Return only valid JSON.
- Each clip must be {min_secs:g} to {max_secs:g} seconds long, in absolute seconds from the start of the source video.
- LENGTH IS A CEILING, NOT A TARGET: default to the shortest length that lands
  the moment cleanly. Only stretch toward {max_secs:g}s when the setup or
  payoff genuinely needs that extra room to keep its sense — a joke that
  lands at 22s stays at 22s. Never pad an already-complete moment just to
  use more of the allowed range.
- Stay within the candidate window boundaries.
- THE 2-SECOND RULE: the clip MUST open on its strongest moment. If the first
  2 seconds would not stop a cold viewer from scrolling, move the start or skip the clip.
- Start slightly before the hook and end slightly after the payoff when possible.
- Do not cut in the middle of a word or phrase.
- No generic intros/outros unless they are the hook.
- STANDS ALONE: the clip must make sense to someone who has seen nothing else.
  If it opens on a pronoun, a "that", a "so anyway", or an answer whose question
  was asked earlier, move the start back to where the idea begins or skip it.
  A brilliant moment that needs the previous five minutes is not a clip.
  Fix this by moving the START earlier, never by cutting the ending short: a
  clip that loses its payoff to gain context has traded down.
- HOW MANY: return {min_clips} to {max_clips} clips. Work through EVERY candidate
  window — they were already scored as the best moments in the video, so a window
  that yields nothing should be the exception, not the norm. Two or three clips
  from one window are fine when they are genuinely different moments. The rules
  above let you skip a weak clip; they are not a licence to return one clip and
  stop. Only fall short of {min_clips} when the material truly does not hold
  them, and never pad with a clip you would not publish yourself.
- DIVERSITY: never return two clips that make the same point, tell the same
  story, or land the same joke — even across different windows. Pick the
  stronger one and drop the other. Two clips on the same broad topic are fine
  as long as each lands its own moment.

HOOK PLAYBOOK — pick the strongest fitting pattern for `viral_hook_text` (max 10 words):
- Open question: "Why does everyone get this wrong?"
- Hot take / controversy: "Stop doing this. Seriously."
- Number / fact shock: "97% of people miss this."
- Story loop: "This one email almost ruined me."
- POV / pattern interrupt: "POV: you finally understand it."
(These are English PATTERNS — always write the actual hook in TRANSCRIPT_LANGUAGE.)
- ABOUT THIS MOMENT, NOT THE VIDEO: the hook and the title name the concrete
  thing that happens inside this clip — the tool being set up, the action,
  the number, the claim, the name. A line that could sit on any clip of this
  video ("I automated my clips with AI") is wrong. If nothing concrete can be
  named, quote the clip's strongest sentence instead of summarising the topic.

COPY RULES — ALL text fields (descriptions, title, hook) MUST be written in TRANSCRIPT_LANGUAGE ({language}):
- Descriptions (TikTok + Instagram): 1-2 punchy sentences that tease the payoff
  without spoiling it, then 3-5 topically relevant hashtags. No generic hashtag spam.
- `video_title_for_youtube_short`: max 100 chars, curiosity-driven, no fake claims.
- `predicted_score`: honest 0-100 estimate of viral potential.

NICHE: also guess `content_niche`, a short (2-6 word) description of this
channel's repost niche — the kind of thing a creator would type as their own
content category, e.g. "Joe Rogan podcast clips", "gym motivation", "cooking
hacks". Same guess on every clip (it describes the whole source video, not
this one moment) — used to research real hashtags for this channel later.

TRANSCRIPT_LANGUAGE: {language}
VIDEO_DURATION_SECONDS: {video_duration}
CANDIDATE_WINDOWS_JSON:
{windows_json}

Return only:
{{
  "shorts": [
    {{
      "start": <number>,
      "end": <number>,
      "source_window_id": "<window id>",
      "predicted_score": <integer 0-100>,
      "video_description_for_tiktok": "<description + hashtags>",
      "video_description_for_instagram": "<description + hashtags>",
      "video_title_for_youtube_short": "<title max 100 chars>",
      "viral_hook_text": "<short overlay max 10 words>",
      "content_niche": "<2-6 word niche guess for the whole video>"
    }}
  ]
}}
"""


def _strip_code_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_json_candidate(text: str) -> str:
    cleaned = _strip_code_fences(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start:end + 1]
    return cleaned


def _escape_invalid_unicode_escapes(text: str) -> str:
    chars = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] == "u":
            hex_digits = text[i + 2:i + 6]
            if len(hex_digits) < 4 or any(ch not in "0123456789abcdefABCDEF" for ch in hex_digits):
                chars.append("\\\\u")
                i += 2
                continue
        chars.append(text[i])
        i += 1
    return "".join(chars)


def _parse_json_response_text(text: str) -> dict:
    if not text:
        raise ValueError("Gemini returned an empty response body.")
    candidate = _extract_json_candidate(text).replace("\x00", "").strip()
    if not candidate:
        raise ValueError("Gemini response did not contain a JSON object.")
    parse_attempts = [candidate]
    sanitized_candidate = _escape_invalid_unicode_escapes(candidate)
    if sanitized_candidate != candidate:
        parse_attempts.append(sanitized_candidate)
    last_error: Optional[Exception] = None
    for parse_candidate in parse_attempts:
        try:
            return json.loads(parse_candidate)
        except json.JSONDecodeError as e:
            last_error = e
    raise ValueError(f"Failed to parse Gemini JSON response: {last_error}")


class GeminiBlockedError(ValueError):
    """The API refused the request for content-policy reasons.

    Deterministic: the same payload is rejected every time (verified in prod,
    23-jul-2026 — a stand-up video came back PROHIBITED_CONTENT in ~300ms on
    every attempt), and BLOCK_NONE safety settings do NOT lift it. Retrying is
    pointless, so callers must fail fast with a message that tells the user the
    video's content is the problem, not the service."""


_BLOCKED_FINISH_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST",
                           "SPII", "IMAGE_SAFETY", "RECITATION"}


def raise_if_blocked(response):
    """Raise GeminiBlockedError when the API refused to answer on policy grounds."""
    pf = getattr(response, "prompt_feedback", None)
    reason = getattr(pf, "block_reason", None)
    if reason:
        name = getattr(reason, "name", None) or str(reason)
        raise GeminiBlockedError(
            f"Gemini blocked this video's content ({name}). The AI provider's "
            "usage policies reject this material, so it can't be analyzed.")
    for c in (getattr(response, "candidates", None) or []):
        fr = getattr(c, "finish_reason", None)
        name = (getattr(fr, "name", None) or str(fr or "")).upper()
        if name in _BLOCKED_FINISH_REASONS:
            raise GeminiBlockedError(
                f"Gemini blocked its answer for this video ({name}). The AI "
                "provider's usage policies reject this material, so it can't be analyzed.")


def _get_response_text(response) -> str:
    try:
        text = response.text
        if text:
            return text
    except Exception:
        pass

    parts = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                parts.append(part_text)
    return "\n".join(parts).strip()


def _calculate_cost_analysis(response, model_name: str) -> Optional[dict]:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return None
    prices = lookup_model_prices(model_name)
    price_estimated = prices is None
    if prices is None:
        # Unknown model: conservative estimate so the UI shows something sane.
        prices = (0.50, 3.00)
    input_price_per_million, output_price_per_million = prices
    prompt_tokens = usage.prompt_token_count or 0
    output_tokens = usage.candidates_token_count or 0
    # Thinking tokens bill at the output rate even though they are invisible.
    thinking_tokens = getattr(usage, "thoughts_token_count", 0) or 0
    input_cost = (prompt_tokens / 1_000_000) * input_price_per_million
    output_cost = ((output_tokens + thinking_tokens) / 1_000_000) * output_price_per_million
    total_cost = input_cost + output_cost
    return {
        "input_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": thinking_tokens,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": total_cost,
        "model": model_name,
        "price_estimated": price_estimated,
    }


def _thinking_config_from_env(model_name: str):
    """GEMINI_THINKING_SCORE: off (default) | low | high | <token budget>.

    Applied only to the scoring stage. Gemini 3 models take thinking_level,
    Gemini 2.5 takes thinking_budget; returns None (= model default) if the
    setting is off or the SDK rejects the config."""
    raw = (os.getenv("GEMINI_THINKING_SCORE") or "off").strip().lower()
    if raw in ("", "off", "0", "none", "false"):
        return None
    try:
        if raw.isdigit():
            return genai_types.ThinkingConfig(thinking_budget=int(raw))
        if raw in ("low", "high"):
            if model_name.startswith("gemini-3"):
                return genai_types.ThinkingConfig(thinking_level=raw)
            return genai_types.ThinkingConfig(thinking_budget=2048 if raw == "low" else 8192)
    except Exception as e:
        _log(f"⚠️ Ignoring GEMINI_THINKING_SCORE={raw!r}: {e}")
    return None


def _config_for_strategy(strategy: str, mode: str, model_name: str) -> genai_types.GenerateContentConfig:
    # The detail stage writes creative copy (hooks/descriptions) — it gets a
    # high temperature; timestamps are validated and word-snapped afterwards.
    # The score stage stays precise. Fallback strategies get conservative.
    creative = mode == "detail"
    kwargs = {
        "response_mime_type": "application/json",
        "candidate_count": 1,
    }
    if strategy == "strict-json":
        kwargs["temperature"] = 0.7 if creative else 0.1
    elif strategy == "json-text-recovery":
        kwargs["temperature"] = 0.2 if creative else 0.0
    else:  # structured-schema: schema-enforced output, primary strategy
        kwargs["temperature"] = 0.9 if creative else 0.2
        kwargs["response_schema"] = DetailResponse if mode == "detail" else ScoreResponse
        if mode == "score":
            thinking = _thinking_config_from_env(model_name)
            if thinking is not None:
                kwargs["thinking_config"] = thinking
    return genai_types.GenerateContentConfig(**kwargs)


def main() -> int:
    _configure_stdio()

    parser = argparse.ArgumentParser(description="Run a single Gemini request for clip scoring/detailing.")
    parser.add_argument("--mode", choices=["score", "detail"], required=True)
    parser.add_argument("--input", dest="input_path", required=True)
    parser.add_argument("--output", dest="output_path", required=True)
    parser.add_argument("--strategy", default="structured-schema")
    parser.add_argument("--model", default="gemini-2.5-flash")
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Missing GEMINI_API_KEY.")

    with open(args.input_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    model_name = args.model
    client = genai.Client(api_key=api_key)
    config = _config_for_strategy(args.strategy, args.mode, model_name)
    language = str(payload.get("language") or "unknown")

    template = SCORE_PROMPT_TEMPLATE if args.mode == "score" else DETAIL_PROMPT_TEMPLATE
    fmt = {
        "video_duration": payload["video_duration"],
        "language": language,
        "windows_json": json.dumps(payload["windows"], ensure_ascii=False),
    }
    if args.mode != "score":
        # Score mode receives every window, not a shortlist, so a count target
        # derived from it would be meaningless — and the score template has no
        # placeholder for one anyway.
        fmt["min_clips"], fmt["max_clips"] = clip_count_targets(len(payload.get("windows") or []))
        fmt["min_secs"], fmt["max_secs"] = clip_duration_bounds()
    prompt = template.format(**fmt)

    _log(f"🤖 Gemini worker request: mode={args.mode} strategy={args.strategy} model={model_name} items={len(payload.get('windows', []))}")
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=config,
    )

    raw_text = _get_response_text(response)
    # With response_schema the SDK returns an already-validated object; fall
    # back to the text-repair path only when that is unavailable.
    parsed_obj = getattr(response, "parsed", None)
    if parsed_obj is not None:
        parsed = parsed_obj.model_dump() if hasattr(parsed_obj, "model_dump") else parsed_obj
    else:
        parsed = _parse_json_response_text(raw_text)
    result = {
        "mode": args.mode,
        "payload": parsed,
        "cost_analysis": _calculate_cost_analysis(response, model_name),
        "raw_text": raw_text,
    }
    with open(args.output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    _log(f"✅ Gemini worker success: mode={args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
