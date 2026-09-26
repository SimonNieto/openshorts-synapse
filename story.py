"""Story Channel: faceless 2D stick-figure explainers ("Hidden Economics").

Two halves:

* ``generate_script`` (called in-process by app.py): one grounded research
  call (Gemini + Google Search) whose notes and sources feed one
  schema-enforced script call. Two Gemini calls per video, nothing else.
* ``render`` (run as a subprocess: ``python story.py render <spec.json>``, so
  the heavy CPU work and the per-job env such as AUTO_CAPTION_STYLE_JSON stay
  out of the API process): narration per scene (Kokoro, local and free; a
  silent track of the estimated length when Kokoro isn't installed yet),
  one image per scene, a slow camera move on each, concat, music, then the
  Clip Generator's own caption pass. The result is written as a normal
  project (``<title>_metadata.json`` + ``<title>_clip_1.mp4``), so History,
  the editor and Upload-Post scheduling all work on it unchanged.

Images come from ``STORY_IMAGE_PROVIDER``: only ``placeholder`` for now (the
recurring cast rasterised from story_characters/*.svg in the scene's pose,
plus the scene description), so the whole chain can be tested for free on a
machine without a GPU. Flux Kontext (fal.ai / local ComfyUI) plugs in at
``scene_image``.

Progress lines for app.py: ``STORY_PROGRESS <percent> <stage>``.
"""
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import wave
from typing import List

from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
CHAR_DIR = os.path.join(HERE, "story_characters")
FONT_DIR = os.path.join(HERE, "fonts")
MODELS_DIR = os.environ.get("KOKORO_MODELS_DIR") or os.path.join(HERE, "models", "kokoro")
KOKORO_MODEL = os.path.join(MODELS_DIR, "kokoro-v1.0.int8.onnx")
KOKORO_VOICES = os.path.join(MODELS_DIR, "voices-v1.0.bin")

FPS = 30
BG = (251, 250, 246)
INK = (21, 21, 21)

# The recurring cast. ``desc`` goes to the script prompt (and later to the
# image model); ``svg`` is the prefix of story_characters/<svg>_<pose>.svg.
CAST = {
    "casey": {"name": "Casey", "svg": "casey",
              "desc": "the everyday consumer who falls for the trap: round head, yellow baseball cap, "
                      "simple black stick-figure body"},
    "prof": {"name": "Prof. Margin", "svg": "prof",
             "desc": "the explainer who reveals how it really works: rounded-square head, round glasses, "
                     "red scarf, simple black stick-figure body"},
}

VOICES = ["am_michael", "af_heart", "af_bella", "am_fenrir", "bm_george", "bf_emma"]
EMOTION_POSE = {"shocked": "shocked", "angry": "shocked", "confused": "shocked",
                "explaining": "point", "happy": "point"}
CAMERAS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "static")


# --- Gemini with patience ------------------------------------------------------

def _primary_model() -> str:
    return os.environ.get("GEMINI_MODEL_THUMBNAIL") or "gemini-3.7-flash"


def _model_chain():
    """Primary first, then models with their own capacity: a "503 high demand"
    spike is per model, so switching usually gets through right away."""
    chain = [_primary_model(), os.environ.get("GEMINI_FALLBACK_MODEL") or "gemini-3.1-flash-lite",
             os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"]
    return list(dict.fromkeys(m for m in chain if m))


_OVERLOAD = ('503', 'UNAVAILABLE', 'overloaded', '429', 'RESOURCE_EXHAUSTED', '500', 'INTERNAL',
             'Deadline', 'high demand')


def gemini_call(api_key: str, contents, config=None, label: str = "Gemini"):
    """generate_content with backoff + model fallback. Each model gets 3
    tries (5 s, 15 s between); on an overload the next model takes over.
    Returns (response, model_used). Policy blocks are raised at once."""
    from google import genai
    import gemini_worker
    client = genai.Client(api_key=api_key)
    last = None
    for model in _model_chain():
        for attempt, wait in enumerate((5, 15, 0), start=1):
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=config)
                gemini_worker.raise_if_blocked(resp)
                return resp, model
            except gemini_worker.GeminiBlockedError:
                raise
            except Exception as e:
                last = e
                if not any(tok in str(e) for tok in _OVERLOAD):
                    raise
                print(f"⚠️ {label}: {model} busy (attempt {attempt}/3){f', retrying in {wait}s' if wait else ''}")
                if wait:
                    time.sleep(wait)
        print(f"🔁 {label}: switching from {model} to the next model")
    raise RuntimeError("Google's Gemini servers are overloaded right now (all models tried). "
                       "Try again in a few minutes.") from last


def gemini_json(api_key: str, contents, schema, label: str = "Gemini") -> dict:
    from google.genai import types
    resp, _ = gemini_call(api_key, contents, types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema), label)
    return json.loads(resp.text)


# --- script -----------------------------------------------------------------

class StoryScene(BaseModel):
    narration: str
    visual: str
    characters: List[str]
    emotion: str
    on_screen_text: str
    camera: str


class StoryScript(BaseModel):
    title: str
    hook: str
    youtube_title: str
    description: str
    hashtags: List[str]
    scenes: List[StoryScene]


SCRIPT_PROMPT = """You write scripts for a faceless YouTube Shorts channel, "Hidden Economics", that explains
the hidden economics of everyday things with simple 2D stick-figure cartoons.

Recurring cast (use ONLY these ids):
{cast}

Topic: {topic}
Target: about {seconds} seconds of narration (~{words} words in total), {min_scenes}-{max_scenes} scenes.

Research notes (facts you may use; do NOT invent numbers that are not supported here — if a figure
is not in the notes, describe it qualitatively):
{notes}

Rules:
- English. A single narrator voice tells the story; the characters act it on screen (no dialogue lines).
- Scene 1 is the hook: a surprising, concrete claim or question, under 12 words. No greetings, no "in this video".
- Structure: hook -> Casey falls into the everyday trap -> Prof. Margin reveals the mechanism (who profits,
  how, with 1-3 concrete numbers) -> twist or consequence -> one practical takeaway. The last line loops back to the hook.
- narration: 1-2 short spoken sentences per scene (5-22 words), written for the ear.
- visual: one sentence describing the drawing: which characters, pose/action, props, simple background.
  Flat 2D black line art on a white background, minimal color.
- on_screen_text: 0-4 words or a number to show big (e.g. "$1.50", "70% quit"), else "".
- emotion: one of neutral, shocked, explaining, happy, sad, confused, angry (main character of the scene).
- camera: one of zoom_in, zoom_out, pan_left, pan_right, static. Vary it.
- characters: the cast ids present in the scene (1 or 2).
- Also: title (internal), hook (the hook line), youtube_title (max 70 chars, curiosity + keyword),
  description (2-3 sentences, no hashtags), hashtags (5-8, without #).
- Original and factual. No financial advice, no promised returns.
"""

RESEARCH_PROMPT = """Research this topic for a 60-second explainer about the hidden economics of everyday things:
"{topic}"
Give 6-10 short, verifiable facts: who makes money and how, key numbers (with year and region), and one
surprising angle. Plain bullet points, each with its source name. Only facts you found."""


def _research(topic: str, api_key: str):
    """Grounded notes + sources. Best effort: ([], '') on any failure."""
    try:
        from google.genai import types
        resp, _ = gemini_call(api_key, RESEARCH_PROMPT.format(topic=topic),
                              types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
                              label="research")
        notes = (resp.text or "").strip()
        sources, seen = [], set()
        meta = getattr(resp.candidates[0], "grounding_metadata", None) if resp.candidates else None
        for chunk in (getattr(meta, "grounding_chunks", None) or []):
            web = getattr(chunk, "web", None)
            if web and getattr(web, "uri", None) and web.uri not in seen:
                seen.add(web.uri)
                sources.append({"title": getattr(web, "title", "") or "", "url": web.uri})
        return notes, sources
    except Exception as e:
        print(f"⚠️ Story research skipped ({type(e).__name__}: {str(e)[:160]})")
        return "", []


def generate_script(topic: str, api_key: str, seconds: int = 60, cast_ids=None, research: bool = True) -> dict:
    cast_ids = [c for c in (cast_ids or ["casey", "prof"]) if c in CAST] or ["casey", "prof"]
    notes, sources = _research(topic, api_key) if research else ("", [])
    words = int(seconds * 2.5)
    prompt = SCRIPT_PROMPT.format(
        cast="\n".join(f"- {cid}: {CAST[cid]['name']}, {CAST[cid]['desc']}" for cid in cast_ids),
        topic=topic, seconds=seconds, words=words,
        min_scenes=max(6, seconds // 6), max_scenes=max(8, seconds // 4),
        notes=notes or "(no research available: stay qualitative, no precise figures)")
    script = gemini_json(api_key, prompt, StoryScript, label="script")
    # Normalise what the schema can't enforce.
    for s in script.get("scenes", []):
        s["characters"] = [c for c in (s.get("characters") or []) if c in cast_ids][:2] or [cast_ids[0]]
        s["camera"] = s.get("camera") if s.get("camera") in CAMERAS else "zoom_in"
        s["on_screen_text"] = (s.get("on_screen_text") or "").strip()[:24]
    script["topic"] = topic
    script["sources"] = sources
    script["research_notes"] = notes
    script["cast"] = cast_ids
    return script


# --- inspiration: a channel (link or screenshot) → original topic ideas ------

class StoryIdea(BaseModel):
    topic: str
    angle: str
    why: str
    inspired_by: str


class StoryIdeas(BaseModel):
    patterns: List[str]
    ideas: List[StoryIdea]


IDEAS_PROMPT = """You help plan a faceless YouTube channel, "Hidden Economics", that explains the hidden
economics of everyday things (who profits, how, with real numbers) using two stick-figure characters:
Casey (the everyday consumer) and Prof. Margin (the explainer).

Here is inspiration from another channel{channel}. {source}

1. patterns: 4-6 short observations on what makes their best titles work (structure, promise, curiosity
   gap, wording) — ranked by views when views are given.
2. ideas: 10 ORIGINAL video topics for Hidden Economics that reuse those winning patterns in OUR niche.
   Never copy or lightly reword their titles or subjects; transpose the mechanism to everyday money topics.
   For each: topic (a clickable English title, max 70 chars), angle (one sentence: the hidden mechanism
   the video reveals), why (which pattern it borrows), inspired_by (the title of theirs it echoes).
{hint}"""


def fetch_channel_titles(url: str, limit: int = 60):
    """Recent uploads (title, views) of a YouTube channel, no API key needed."""
    import yt_dlp
    url = url.strip()
    if not url.startswith("http"):
        url = "https://www.youtube.com/" + (url if url.startswith("@") else "@" + url)
    if "/@" in url and not re.search(r"/(videos|shorts|streams)/?$", url):
        url = url.rstrip("/") + "/videos"
    with yt_dlp.YoutubeDL({"extract_flat": True, "playlistend": limit, "quiet": True,
                           "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    rows = [{"title": e.get("title"), "views": e.get("view_count")}
            for e in (info.get("entries") or []) if e and e.get("title")]
    return (info.get("channel") or info.get("uploader") or info.get("title") or ""), rows


def generate_ideas(api_key: str, titles=None, channel_name: str = "", image_bytes: bytes = None,
                   mime: str = "image/png", hint: str = "") -> dict:
    """One Gemini call: winning patterns of the channel + 10 original ideas."""
    from google.genai import types
    if titles:
        ranked = sorted(titles, key=lambda r: r.get("views") or 0, reverse=True)[:30]
        source = "Their recent videos, most viewed first:\n" + "\n".join(
            f"- {r['title']}" + (f" ({r['views']:,} views)" if r.get("views") else "") for r in ranked)
    else:
        source = "The attached screenshot shows their videos: read every title (and view count if visible)."
    prompt = IDEAS_PROMPT.format(
        channel=f' ("{channel_name}")' if channel_name else "", source=source,
        hint=f"\nExtra direction from the creator: {hint}" if hint else "")
    contents = [prompt]
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime or "image/png"))
    return gemini_json(api_key, contents, StoryIdeas, label="ideas")


# --- render helpers -----------------------------------------------------------

def progress(pct: int, stage: str):
    print(f"STORY_PROGRESS {int(pct)} {stage}", flush=True)


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{os.path.basename(cmd[0])} failed: {r.stderr[-600:]}")
    return r


def _write_wav(path: str, samples, sr: int):
    import numpy as np
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _wav_duration(path: str) -> float:
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


_kokoro = None


def kokoro_available() -> bool:
    try:
        import kokoro_onnx  # noqa: F401
    except ImportError:
        return False
    return os.path.exists(KOKORO_MODEL) and os.path.exists(KOKORO_VOICES)


def tts(text: str, voice: str, out_wav: str, speed: float = 1.0) -> float:
    """Narrate ``text`` into ``out_wav``; returns its duration. Without Kokoro,
    a silent track of the estimated spoken length keeps the chain testable."""
    global _kokoro
    import numpy as np
    if kokoro_available():
        if _kokoro is None:
            from kokoro_onnx import Kokoro
            _kokoro = Kokoro(KOKORO_MODEL, KOKORO_VOICES)
        samples, sr = _kokoro.create(text, voice=voice, speed=speed, lang="en-us" if not voice.startswith("b") else "en-gb")
        _write_wav(out_wav, samples, sr)
    else:
        sr = 24000
        dur = max(1.6, len(text.split()) / 2.6 + 0.3)
        _write_wav(out_wav, np.zeros(int(sr * dur), dtype="float32"), sr)
    return _wav_duration(out_wav)


def _font(name: str, size: int):
    from PIL import ImageFont
    for path in (os.path.join(FONT_DIR, name), f"/usr/share/fonts/truetype/liberation/{name}"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _character_png(slug: str, pose: str, width: int, tmp: str) -> str:
    """Rasterise the cast SVG crisply at ``width`` (without the sample price tag)."""
    src = os.path.join(CHAR_DIR, f"{CAST[slug]['svg']}_{pose}.svg")
    with open(src, encoding="utf-8") as f:
        svg = f.read()
    svg = re.sub(r'<g transform="rotate\(-6[^>]*>.*?</g>', "", svg, flags=re.S)
    svg = re.sub(r'<rect width="240" height="260" fill="#FBFAF6"/>', "", svg)
    svg = svg.replace('width="240" height="260"', f'width="{width}" height="{int(width * 260 / 240)}"', 1)
    svg_path = os.path.join(tmp, f"{slug}_{pose}_{width}.svg")
    png_path = svg_path[:-4] + ".png"
    if not os.path.exists(png_path):
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg)
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", svg_path, png_path])
    return png_path


def _label(img, text: str, cy: int):
    """The scene's big on-screen text (numbers, prices): drawn by us, not by
    the image model, which garbles digits."""
    from PIL import ImageDraw
    if not text:
        return
    d = ImageDraw.Draw(img)
    W = img.width
    size = 150
    while size > 60:
        font = _font("Anton-Regular.ttf", size)
        box = d.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= W - 200:
            break
        size -= 10
    tw, th = box[2] - box[0], box[3] - box[1]
    pad_x, pad_y = 44, 30
    x0, y0 = (W - tw) // 2 - pad_x, cy - th // 2 - pad_y
    d.rounded_rectangle([x0, y0, x0 + tw + 2 * pad_x, y0 + th + 2 * pad_y], radius=26,
                        fill=(255, 255, 255), outline=INK, width=9)
    d.text(((W - tw) // 2 - box[0], cy - th // 2 - box[1]), text, font=font, fill=INK)


def scene_image(scene: dict, index: int, total: int, size, tmp: str, out_png: str):
    """Placeholder provider: the cast in the scene's pose + what the real image
    will show. Same canvas and label layer a real provider will get."""
    from PIL import Image, ImageDraw
    W, H = size
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    pose = EMOTION_POSE.get(scene.get("emotion", "neutral"), "neutral")
    chars = scene.get("characters") or ["casey"]
    area_top, area_bottom = int(H * 0.30), int(H * 0.68)
    slot_w = W // len(chars)
    char_w = min(int(slot_w * (0.95 if len(chars) > 1 else 0.72)), int((area_bottom - area_top) * 240 / 260))
    for i, slug in enumerate(chars):
        # Explaining pose for Prof., the scene's emotion for Casey (or a lone character).
        p = "point" if (slug == "prof" and len(chars) > 1) else pose
        png = Image.open(_character_png(slug, p, char_w, tmp)).convert("RGBA")
        x = i * slot_w + (slot_w - png.width) // 2
        img.paste(png, (x, area_bottom - png.height), png)
    small = _font("LiberationSans-Regular.ttf", 34)
    d.text((48, 40), f"PLACEHOLDER · scene {index + 1}/{total} · {scene.get('camera', '')}", font=small, fill=(150, 150, 150))
    desc = _font("LiberationSans-Italic.ttf", 36)
    y = int(H * 0.87)
    for line in textwrap.wrap(scene.get("visual", ""), width=int(W / 19))[:4]:
        d.text((60, y), line, font=desc, fill=(120, 120, 120))
        y += 46
    _label(img, scene.get("on_screen_text", ""), int(H * 0.22))
    img.save(out_png)


def animate(png: str, seconds: float, camera: str, size, out_mp4: str):
    """A slow Ken-Burns move over one still (rendered at 2x for smooth motion)."""
    W, H = size
    frames = max(1, int(round(seconds * FPS)))
    n = frames
    if camera == "zoom_out":
        z, x, y = f"1.12-0.12*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif camera == "pan_left":
        z, x, y = "1.12", f"(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"
    elif camera == "pan_right":
        z, x, y = "1.12", f"(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"
    elif camera == "static":
        z, x, y = "1.0", "0", "0"
    else:  # zoom_in
        z, x, y = f"1.0+0.12*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    vf = (f"scale={W * 2}:{H * 2},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
          f"format=yuv420p")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", png, "-vf", vf, "-frames:v", str(frames),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), out_mp4])


def _synthetic_transcript(timeline):
    """Word timings spread over each scene's narration (used when the track is
    silent, so the captions pass still has something to show)."""
    segments = []
    for start, dur, text in timeline:
        words = text.split()
        if not words:
            continue
        weights = [len(w) + 2 for w in words]
        total = float(sum(weights))
        t = start
        items = []
        for w, wt in zip(words, weights):
            d = dur * wt / total
            items.append({"word": " " + w, "start": round(t, 3), "end": round(t + d, 3)})
            t += d
        segments.append({"start": start, "end": start + dur, "text": " " + text, "words": items})
    return {"language": "en", "segments": segments}


def _music_file():
    folder = os.environ.get("BACKGROUND_MUSIC_DIR") or "music"
    folder = folder if os.path.isabs(folder) else os.path.join(HERE, folder)
    try:
        files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith((".mp3", ".m4a", ".wav"))]
    except OSError:
        return None
    return random.choice(files) if files else None


def _safe_name(title: str) -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:60] or "story")


def render(spec_path: str):
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    script, out_dir = spec["script"], os.path.abspath(spec["output_dir"])
    voice = spec.get("voice") if spec.get("voice") in VOICES else VOICES[0]
    size = (1080, 1920)
    scenes = script.get("scenes") or []
    if not scenes:
        raise RuntimeError("The script has no scenes.")
    tmp = tempfile.mkdtemp(prefix="story_", dir=out_dir)
    t0 = time.time()

    real_voice = kokoro_available()
    print(f"🎙️ Narration: {'Kokoro · ' + voice if real_voice else 'SILENT placeholder (Kokoro not installed yet)'}")
    progress(3, "voice")
    timeline, wavs, t = [], [], 0.0
    pad = 0.25
    for i, s in enumerate(scenes):
        wav = os.path.join(tmp, f"voice_{i:02d}.wav")
        dur = tts(s["narration"], voice, wav) + pad
        timeline.append((t, dur, s["narration"]))
        wavs.append((wav, dur))
        t += dur
        progress(3 + 30 * (i + 1) / len(scenes), "voice")
    total = t
    print(f"   {len(scenes)} scenes · {total:.1f}s of narration")

    # One narration track, each scene padded to its slot.
    concat_in = []
    for wav, dur in wavs:
        concat_in += ["-i", wav]
    filters = "".join(f"[{i}:a]apad=whole_dur={dur:.3f}[a{i}];" for i, (_, dur) in enumerate(wavs))
    filters += "".join(f"[a{i}]" for i in range(len(wavs))) + f"concat=n={len(wavs)}:v=0:a=1[out]"
    narration = os.path.join(tmp, "narration.wav")
    _run(["ffmpeg", "-y", "-loglevel", "error", *concat_in, "-filter_complex", filters,
          "-map", "[out]", "-ar", "48000", narration])

    print("🖼️ Scene images (placeholder)")
    parts = []
    for i, (s, (start, dur, _)) in enumerate(zip(scenes, timeline)):
        png = os.path.join(tmp, f"scene_{i:02d}.png")
        scene_image(s, i, len(scenes), size, tmp, png)
        mp4 = os.path.join(tmp, f"scene_{i:02d}.mp4")
        animate(png, dur, s.get("camera", "zoom_in"), size, mp4)
        parts.append(mp4)
        progress(33 + 50 * (i + 1) / len(scenes), "images")

    listing = os.path.join(tmp, "parts.txt")
    with open(listing, "w") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    silent_video = os.path.join(tmp, "video.mp4")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", silent_video])
    progress(86, "mixing")

    base = _safe_name(script.get("youtube_title") or script.get("title") or "story")
    clip_name = f"{base}_clip_1.mp4"
    clip_path = os.path.join(out_dir, clip_name)
    music = _music_file() if spec.get("music", True) else None
    if music:
        fade_at = max(0.0, total - 2.0)
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent_video, "-i", narration,
              "-stream_loop", "-1", "-i", music, "-filter_complex",
              f"[2:a]volume={float(os.environ.get('BACKGROUND_MUSIC_VOLUME', '0.12')):.3f},"
              f"afade=t=out:st={fade_at:.2f}:d=2[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
              "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.3f}", clip_path])
        print(f"🎵 Music: {os.path.basename(music)}")
    else:
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent_video, "-i", narration,
              "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.3f}", clip_path])

    progress(90, "captions")
    transcript = None
    if real_voice:
        try:
            from transcribe_backends import transcribe_media
            transcript = transcribe_media(narration)
        except Exception as e:
            print(f"⚠️ Narration transcription failed ({e}); using script timings for captions.")
    if not transcript or not transcript.get("segments"):
        transcript = _synthetic_transcript(timeline)

    hashtags = " ".join("#" + h.lstrip("#").replace(" ", "") for h in script.get("hashtags", []))
    description = (script.get("description", "") + ("\n\n" + hashtags if hashtags else "")).strip()
    clip = {
        "start": 0.0, "end": round(total, 3),
        "video_title_for_youtube_short": script.get("youtube_title") or script.get("title") or "Story",
        "video_description_for_tiktok": description,
        "video_description_for_instagram": description,
        "viral_hook_text": script.get("hook", ""),
        "video_url": f"/videos/{spec['job_id']}/{clip_name}",
    }
    metadata = {
        "shorts": [clip], "transcript": transcript, "output_format": "vertical",
        "source_video": os.path.basename(narration), "niche": spec.get("niche") or None,
        "story": {**script, "voice": voice, "placeholder_images": True, "silent_voice": not real_voice},
    }
    meta_path = os.path.join(out_dir, f"{base}_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    try:
        sys.path.insert(0, HERE)
        import main as _main
        captioned = _main.auto_caption_clip(clip_path, transcript, 0.0, total, output_format="vertical")
    except Exception as e:
        print(f"⚠️ Captions skipped: {e}")
        captioned = None
    if captioned:
        clip["video_url"] = f"/videos/{spec['job_id']}/{os.path.basename(captioned)}"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"STORY_RESULT {json.dumps({'video_url': clip['video_url'], 'duration': round(total, 1)})}", flush=True)
    progress(100, "done")
    print(f"✅ Story rendered in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "render":
        try:
            render(sys.argv[2])
        except Exception as e:
            print(f"❌ Story render failed: {e}", flush=True)
            sys.exit(1)
    else:
        print("usage: python story.py render <spec.json>")
        sys.exit(2)
