"""Viral Clip Reworker: strip an existing hook from an uploaded clip and burn
your own hook + captions on top, with optional dubbing to another language.

Erasing (``erase_regions``) defaults to text_eraser.py's "smart" engine:
only the letters (+ outline / glow / banner) inside each region are removed,
and what was behind them is carried in from neighbouring frames along the
picture's motion; only what was never visible is reconstructed. CPU only, no
model. Honest limit: text parked for seconds on a talking mouth has no real
background to recover and comes out as a soft patch — truly invisible there
needs an AI video-inpainting model on a GPU. ``mode="legacy"`` keeps the old
whole-rectangle inpaint (faster, visibly smeared).

``text_eraser.detect_text_regions`` suggests the regions (captions for the
whole clip, a hook for its time span); ``preview_erase`` renders a short
before / after so the user sees the result before running the whole clip.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Callable, Optional

import cv2
import numpy as np
from pydantic import BaseModel

from ffmpeg_utils import video_encode_args, audio_encode_args, QUALITY_FAST


def ensure_playable(path: str) -> str:
    """Re-encode ``path`` to H.264 when OpenCV's ffmpeg backend can't decode
    it, so every downstream cv2.VideoCapture call in this module gets a file
    it can actually read.

    Some codecs (notably AV1 in a webm downloaded from TikTok/Reels/etc.)
    make OpenCV log "platform doesn't support hardware accelerated AV1
    decoding" and return zero frames forever, while container-metadata reads
    (width/height/duration) keep working fine — so probe_video sees a valid
    file, extract_preview_frame silently fails, and erase_regions produces an
    empty video that only blows up much later at the final ffmpeg mux with an
    opaque exit code. The system ffmpeg CLI decodes the same AV1 file in
    software without issue, so re-encoding through it is a reliable fix.
    Returns ``path`` unchanged when it's already readable.
    """
    cap = cv2.VideoCapture(path)
    try:
        ok, _ = cap.read()
    finally:
        cap.release()
    if ok:
        return path
    print(f"⚠️ [Rework] OpenCV can't decode {os.path.basename(path)} "
          f"(likely AV1) — re-encoding to H.264 before processing.")
    stem, _ext = os.path.splitext(path)
    compat_path = f"{stem}.compat.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", path,
         *video_encode_args(QUALITY_FAST), "-c:a", "aac", "-b:a", "192k",
         compat_path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    os.remove(path)
    return compat_path


def probe_video(path: str) -> dict:
    """Width, height, fps, duration — everything the upload step hands back
    for the frontend's box-drawing UI."""
    cap = cv2.VideoCapture(path)
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps else 0.0
    finally:
        cap.release()
    return {"width": width, "height": height, "fps": fps, "duration": duration}


def extract_preview_frame(video_path: str, out_path: str, at_seconds: float = 0.5) -> bool:
    """One JPEG frame for the frontend to draw the erase-box over."""
    cap = cv2.VideoCapture(video_path)
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, at_seconds * 1000.0)
        ok, frame = cap.read()
        if not ok:
            ok, frame = cap.read()  # very short clip: fall back to frame 0
        if not ok:
            return False
        return bool(cv2.imwrite(out_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85]))
    finally:
        cap.release()


def erase_regions(input_path: str, output_path: str, boxes: list, radius: Optional[int] = None,
                  on_progress: Optional[Callable[[float], None]] = None, mode: Optional[str] = None) -> None:
    """Erase burned-in captions / hooks inside ``boxes`` (box format: see
    erase_regions_legacy). ``mode`` "smart" (default, text_eraser: text-only
    mask + real background borrowed from neighbouring frames) or "legacy"
    (the old whole-rectangle inpaint, kept for comparison / fallback)."""
    mode = mode or os.environ.get("HOOK_REMOVAL_MODE", "smart")
    if mode == "legacy":
        return erase_regions_legacy(input_path, output_path, boxes, radius, on_progress)
    import text_eraser
    input_path = ensure_playable(input_path)
    info = probe_video(input_path)
    width, height = info["width"], info["height"]
    px_boxes = []
    for box in boxes:
        x = max(0, min(width - 1, int(box["x"] * width)))
        y = max(0, min(height - 1, int(box["y"] * height)))
        w = max(1, min(width - x, int(box["w"] * width)))
        h = max(1, min(height - y, int(box["h"] * height)))
        px_boxes.append({"rect": (x, y, w, h), "start": box.get("start"), "end": box.get("end")})
    text_eraser.erase(input_path, output_path, px_boxes, width, height, info["fps"], info["duration"],
                      video_encode_args(QUALITY_FAST), on_progress=on_progress)


def preview_erase(input_path: str, output_path: str, boxes: list, at: float,
                  span: float = 3.0, mode: Optional[str] = None) -> None:
    """Side-by-side before | after of ``span`` seconds around ``at``, erased
    exactly like the real run (1 s of context on each side, so the smart
    engine has neighbouring frames to borrow from)."""
    input_path = ensure_playable(input_path)
    duration = probe_video(input_path)["duration"]
    span = max(1.0, min(span, duration))
    start = max(0.0, min(at - span / 2, duration - span))
    s0 = max(0.0, start - 1.0)
    s1 = min(duration, start + span + 1.0)
    stem = os.path.splitext(output_path)[0]
    snippet, erased = f"{stem}.snip.mp4", f"{stem}.erased.mp4"
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{s0:.3f}", "-i", input_path,
                        "-t", f"{s1 - s0:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                        snippet], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        shifted = [dict(b, start=None if b.get("start") is None else b["start"] - s0,
                        end=None if b.get("end") is None else b["end"] - s0) for b in boxes]
        erase_regions(snippet, erased, shifted, mode=mode)
        off = f"{start - s0:.3f}"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                        "-ss", off, "-i", snippet, "-ss", off, "-i", erased, "-t", f"{span:.3f}",
                        "-filter_complex", "[0:v]scale=-2:720[a];[1:v]scale=-2:720[b];[a][b]hstack=inputs=2[v]",
                        "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    finally:
        for leftover in (snippet, erased):
            if os.path.exists(leftover):
                os.remove(leftover)


def erase_regions_legacy(input_path: str, output_path: str, boxes: list, radius: Optional[int] = None,
                         on_progress: Optional[Callable[[float], None]] = None) -> None:
    """Erase every rectangle in ``boxes`` from ``input_path`` via cv2.inpaint,
    muxing the original audio back in unchanged. Raises on an ffmpeg failure —
    same contract as ``ffmpeg_utils.cut_clip``, the caller decides how to
    degrade.

    Each box is a fractions-0-1 ``{x, y, w, h}`` dict, plus optional ``start``
    / ``end`` in seconds (source-clip time): a box with neither is active for
    the whole clip; one with either is only erased between them. A frame with
    no active box at its timestamp is passed through completely untouched —
    both correct (nothing to erase there) and faster (nothing to compute).

    Frames stream through a pipe into ffmpeg exactly like the main reframe
    pass (main.py's per-frame render loop): encode the silent video, extract
    audio separately, mux with a stream copy.
    """
    radius = radius or int(os.environ.get("HOOK_REMOVAL_INPAINT_RADIUS", "6"))
    # Safety net for jobs whose source predates ensure_playable being called
    # at upload time (or any other future caller that skips it): probe_video
    # below only reads container metadata and would look fine even on an
    # undecodable file, so this needs its own real test-read.
    input_path = ensure_playable(input_path)
    info = probe_video(input_path)
    width, height, fps = info["width"], info["height"], info["fps"]

    px_boxes = []
    for box in boxes:
        x = max(0, min(width - 1, int(box["x"] * width)))
        y = max(0, min(height - 1, int(box["y"] * height)))
        w = max(1, min(width - x, int(box["w"] * width)))
        h = max(1, min(height - y, int(box["h"] * height)))
        px_boxes.append({"rect": (x, y, w, h), "start": box.get("start"), "end": box.get("end")})

    # cv2.inpaint's cost scales with the size of the array it's given, not
    # just the masked pixels inside it — inpainting the FULL frame every
    # frame made a small caption bar on a 1080x1920/60fps clip take longer
    # than the rest of the pipeline combined (measured: ~0.6s/frame even
    # cropped to just the region — Telea's own cost on a real, lossily-encoded
    # frame, not something a bigger CPU fixes). Cropping to the UNION of every
    # box's rect (padded for real texture at the edges) cuts the processed
    # area down once, up front, regardless of which boxes are active on any
    # given frame; downscaling that crop before inpainting and back up after
    # cuts it further, measured ~0.035s/frame at 0.35x — worth it because the
    # erased area is already a best-effort reconstruction, not a pixel-exact
    # one, so a slightly softer patch there costs nothing real.
    pad = 40
    x0 = max(0, min(b["rect"][0] for b in px_boxes) - pad)
    y0 = max(0, min(b["rect"][1] for b in px_boxes) - pad)
    x1 = min(width, max(b["rect"][0] + b["rect"][2] for b in px_boxes) + pad)
    y1 = min(height, max(b["rect"][1] + b["rect"][3] for b in px_boxes) + pad)
    crop_w, crop_h = x1 - x0, y1 - y0

    inpaint_scale = float(os.environ.get("HOOK_REMOVAL_INPAINT_SCALE", "0.35"))
    small_w = max(1, int(crop_w * inpaint_scale))
    small_h = max(1, int(crop_h * inpaint_scale))
    scale_x, scale_y = small_w / crop_w, small_h / crop_h
    small_radius = max(1, int(radius * inpaint_scale))

    def mask_for(t: float):
        """Small-scale mask of every box active at time ``t``, or None if
        none are — the per-frame cost of this is negligible next to inpaint."""
        m = None
        for b in px_boxes:
            if b["start"] is not None and t < b["start"]:
                continue
            if b["end"] is not None and t > b["end"]:
                continue
            if m is None:
                m = np.zeros((small_h, small_w), dtype=np.uint8)
            bx, by, bw, bh = b["rect"]
            lx = int((bx - x0) * scale_x)
            ly = int((by - y0) * scale_y)
            lw = max(1, int(bw * scale_x))
            lh = max(1, int(bh * scale_y))
            m[ly:ly + lh, lx:lx + lw] = 255
        return m

    stem = os.path.splitext(output_path)[0]
    silent_path = f"{stem}.silent.mp4"
    audio_path = f"{stem}.audio.m4a"

    encoder = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-video_size", f"{width}x{height}", "-framerate", str(fps), "-i", "pipe:0",
         *video_encode_args(QUALITY_FAST), "-an", silent_path],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    total_frames = max(1, int(info["duration"] * fps))
    reader = cv2.VideoCapture(input_path)
    try:
        frame_idx = 0
        while True:
            ok, frame = reader.read()
            if not ok:
                break
            small_mask = mask_for(frame_idx / fps)
            if small_mask is not None:
                crop = frame[y0:y1, x0:x1]
                small_crop = cv2.resize(crop, (small_w, small_h), interpolation=cv2.INTER_AREA)
                small_inpainted = cv2.inpaint(small_crop, small_mask, small_radius, cv2.INPAINT_TELEA)
                frame[y0:y1, x0:x1] = cv2.resize(small_inpainted, (crop_w, crop_h), interpolation=cv2.INTER_LINEAR)
            encoder.stdin.write(frame.tobytes())
            frame_idx += 1
            # Every 10 frames: fine enough to feel live, cheap enough not to
            # matter next to the ~0.03s/frame this step now costs.
            if on_progress and frame_idx % 10 == 0:
                on_progress(min(1.0, frame_idx / total_frames))
        if on_progress:
            on_progress(1.0)
    finally:
        reader.release()
        encoder.stdin.close()
        encode_err = encoder.stderr.read()
        encoder.wait()

    if encoder.returncode != 0:
        for leftover in (silent_path, audio_path):
            if os.path.exists(leftover):
                os.remove(leftover)
        raise RuntimeError(f"hook removal encode failed: {(encode_err or b'').decode(errors='replace')[-800:]}")

    # Re-encode to AAC rather than -c:a copy: a webm upload's audio is
    # typically Opus, which the mp4/m4a muxer below refuses outright
    # ("codec not currently supported in container") — that failure used to
    # be silent (has_audio just goes False), so the final clip played back
    # with no sound at all instead of erroring.
    has_audio = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", input_path,
         "-vn", "-c:a", "aac", "-b:a", "192k", audio_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE).returncode == 0

    mux = ["ffmpeg", "-y", "-loglevel", "error", "-i", silent_path]
    if has_audio and os.path.exists(audio_path):
        mux += ["-i", audio_path]
    mux += ["-c", "copy", "-movflags", "+faststart", output_path]
    try:
        subprocess.run(mux, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    finally:
        for leftover in (silent_path, audio_path):
            if os.path.exists(leftover):
                os.remove(leftover)


def _generate_json_with_fallback(prompt: str, schema, api_key: str, model: Optional[str] = None) -> dict:
    """Shared retry/fallback policy for every text-only Gemini call in this
    module (clip copy, caption translation): 3 attempts on the primary model
    with backoff on transient errors, then one attempt on flash-lite before
    giving up. Pulled out once both generate_clip_copy and translate_transcript
    needed it — a caller hitting a quota/availability error on gemini-3.7-flash
    used to just fail outright.

    Defaults to GEMINI_MODEL_THUMBNAIL (gemini-3.7-flash), not GEMINI_MODEL
    (flash-lite): thumbnail.py already found flash-lite "visibly worse at
    creative titles" while being fine for closed-choice picks, and hook/copy/
    translation are that same kind of task, not a moment-scoring pass.

    Raises on a content-policy block (a different model won't fix that) or
    when both models are exhausted; returns the parsed JSON dict on success.
    """
    from google import genai
    from google.genai import types as genai_types
    import gemini_worker
    import time

    client = genai.Client(api_key=api_key)
    primary_model = model or os.environ.get("GEMINI_MODEL_THUMBNAIL") or "gemini-3.7-flash"
    config = genai_types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema)

    def _call(model_name, max_attempts):
        for attempt in range(1, max_attempts + 1):
            try:
                response = client.models.generate_content(
                    model=model_name, contents=[prompt], config=config)
                gemini_worker.raise_if_blocked(response)
                return json.loads(response.text) or {}
            except gemini_worker.GeminiBlockedError:
                raise
            except Exception as e:
                msg = str(e)
                transient = any(tok in msg for tok in (
                    '503', 'UNAVAILABLE', '429', 'RESOURCE_EXHAUSTED',
                    '500', 'INTERNAL', 'overloaded', 'Deadline', 'quota'))
                if attempt == max_attempts or not transient:
                    raise
                wait = 5 * (2 ** (attempt - 1))
                print(f"⚠️ Gemini transient error via {model_name} "
                      f"(attempt {attempt}/{max_attempts}), retrying in {wait}s: {msg[:150]}")
                time.sleep(wait)

    try:
        return _call(primary_model, max_attempts=3)
    except gemini_worker.GeminiBlockedError:
        raise
    except Exception as e:
        fallback_model = "gemini-3.1-flash-lite"
        if primary_model == fallback_model:
            raise
        print(f"⚠️ {primary_model} unavailable after retries ({e}) — falling back to {fallback_model}.")
        return _call(fallback_model, max_attempts=1)


class ClipCopy(BaseModel):
    viral_hook_text: str
    video_title_for_youtube_short: str
    video_description_for_tiktok: str
    video_description_for_instagram: str


COPY_PROMPT = """You write the on-screen hook and social copy for a short-form video (TikTok/Reels/Shorts).

Transcript (language: {language}):
\"\"\"{transcript}\"\"\"

HOOK PLAYBOOK — pick the strongest fitting pattern for `viral_hook_text` (max 10 words):
- Open question: "Why does everyone get this wrong?"
- Hot take / controversy: "Stop doing this. Seriously."
- Number / fact shock: "97% of people miss this."
- Story loop: "This one email almost ruined me."
- POV / pattern interrupt: "POV: you finally understand it."
(These are English PATTERNS — always write the actual hook in the transcript's
own language.) 1-2 fitting emojis are welcome.

ABOUT THIS MOMENT, NOT THE VIDEO: name the concrete thing that happens in
this transcript — the claim, the number, the action, the name — not a vague
summary of the general topic. A line that could sit on any clip of any video
("check this out") is wrong. If nothing concrete stands out, quote the
transcript's strongest sentence instead of summarising it. This same rule
applies to the title and descriptions below, not just the hook.

COPY RULES — ALL fields MUST be written in the transcript's own language:
- `video_title_for_youtube_short`: max 100 chars — YouTube truncates well
  before that on mobile, so spend the budget on the curiosity hook first,
  no fake claims, THEN append the single best-fitting hashtag from the pool
  below (if one is given) as the last thing in the title, only if it still
  fits inside 100 chars without crowding out the hook. Skip it rather than
  truncate the hook to make room.
- `video_description_for_tiktok` / `video_description_for_instagram`: 1-2
  punchy sentences that tease the payoff without spoiling it, then 3-5
  topically relevant hashtags. No generic hashtag spam (#fyp, #viral alone
  are not "topically relevant"). The two descriptions may differ in tone but
  must both name the same concrete moment as the hook.
{hashtag_guidance}
Return JSON: {{"viral_hook_text": "<max 10 words>",
"video_title_for_youtube_short": "<max 100 chars, hook first, one hashtag at the end if it fits>",
"video_description_for_tiktok": "<1-2 sentences + hashtags>",
"video_description_for_instagram": "<1-2 sentences + hashtags>"}}"""

# Filled into COPY_PROMPT when a real, researched hashtag pool exists for the
# channel's niche (niche_hashtags.research_hashtags) — picking FROM real tags
# beats letting the model invent plausible-looking ones from training data.
HASHTAG_POOL_GUIDANCE = """
REAL HASHTAGS FROM TOP-PERFORMING VIDEOS IN THIS CHANNEL'S NICHE (researched
from YouTube, not invented) — pick the 3-5 that best fit THIS specific clip's
topic, don't just paste the whole list: {hashtags}
"""


def generate_clip_copy(transcript_text: str, language: str, api_key: str, model: Optional[str] = None,
                        hashtag_pool: Optional[list] = None) -> dict:
    """One text-only Gemini call for the hook + title + descriptions a normal
    generated clip gets from main.py's DetailClipModel — no frames needed,
    unlike hook_grounding.py, since we already have the clip's own words.
    Returns a dict with all four ClipCopy fields; raises if even the
    flash-lite fallback (see _generate_json_with_fallback) fails, same as any
    other exception in the pipeline's try/except.

    ``hashtag_pool``: real hashtags researched from top Shorts in the
    channel's niche (niche_hashtags.py). When given, the model picks from
    these instead of inventing plausible-looking ones from training data.
    """
    hashtag_guidance = (
        HASHTAG_POOL_GUIDANCE.format(hashtags=" ".join(hashtag_pool))
        if hashtag_pool else "")
    prompt = COPY_PROMPT.format(language=language or "unknown", transcript=(transcript_text or "")[:4000],
                                 hashtag_guidance=hashtag_guidance)
    data = _generate_json_with_fallback(prompt, ClipCopy, api_key, model)
    return {
        "viral_hook_text": str(data.get("viral_hook_text") or "").strip(),
        "video_title_for_youtube_short": str(data.get("video_title_for_youtube_short") or "").strip()[:100],
        "video_description_for_tiktok": str(data.get("video_description_for_tiktok") or "").strip(),
        "video_description_for_instagram": str(data.get("video_description_for_instagram") or "").strip(),
    }


def transcript_text(transcript: dict) -> str:
    """Flat text of every segment, for the hook prompt."""
    segs = (transcript or {}).get("segments") or []
    return " ".join((s.get("text") or "").strip() for s in segs if s.get("text"))


def apply_variations(input_path: str, output_path: str, flip: bool = False,
                      speed: float = 1.0, zoom: float = 1.0, color_boost: float = 1.0) -> bool:
    """Re-encode with light, deliberately-imperfect visual/timing variation —
    a horizontal flip, a small speed nudge, a slight zoom-in crop, a
    saturation/contrast lift. Each one alone or combined changes the file's
    visual fingerprint (a platform's duplicate/recycled-content check is
    frame-hash-based, not semantic) without being visible to a viewer at the
    sizes involved here. Returns False (input left untouched) when nothing
    was actually requested, so callers can skip the copy.

    speed: 0.5-2.0 (ffmpeg atempo's own range; the useful range for this is
    narrow, ~0.95-1.05 — the recut needs to be undetectable, not dramatic).
    zoom: 1.0 = untouched, 1.15 = crop in 15% then scale back up to size.
    color_boost: 1.0 = untouched, saturation/contrast multiplier (1.2 = +20%).
    """
    if not flip and speed == 1.0 and zoom == 1.0 and color_boost == 1.0:
        return False

    vf = []
    if flip:
        vf.append("hflip")
    if zoom and zoom != 1.0:
        # Scale up then crop back to the original frame size: net effect is a
        # centered zoom-in with no letterboxing and no size change downstream.
        vf.append(f"scale=iw*{zoom}:ih*{zoom}")
        vf.append(f"crop=iw/{zoom}:ih/{zoom}")
    if color_boost and color_boost != 1.0:
        contrast = 1 + (color_boost - 1) * 0.5
        vf.append(f"eq=saturation={color_boost}:contrast={contrast}")
    if speed and speed != 1.0:
        vf.append(f"setpts=PTS/{speed}")

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", input_path]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    if speed and speed != 1.0:
        # atempo's own range is 0.5-2.0, comfortably wider than the values
        # this is meant to be used at.
        cmd += ["-af", f"atempo={speed}"]
    cmd += [*video_encode_args(QUALITY_FAST), "-c:a", "aac", "-b:a", "192k", output_path]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return True


class _Translations(BaseModel):
    translations: list[str]


TRANSLATE_PROMPT = """Translate each numbered line into {target_language}. Keep the
same tone and register (casual stays casual). Return exactly {count} lines,
same order, nothing added or dropped — a caption burn downstream matches them
back up by position, so a missing or extra line shifts every caption after it.

{numbered_lines}

Return JSON: {{"translations": ["<line 1 translation>", "<line 2 translation>", ...]}}"""


def translate_transcript(transcript: dict, target_language: str, api_key: str,
                          model: Optional[str] = None) -> dict:
    """Translate a transcript's TEXT ONLY for burning captions in a different
    language than the spoken audio (e.g. an English video, French captions) —
    distinct from translate.py's ElevenLabs dubbing, which replaces the voice
    itself. No word-for-word timing survives a translation (word order and
    count both change across languages), so each segment's translated words
    are spread evenly across that segment's own original [start, end] — the
    same approximation SubtitleModal.jsx already uses client-side when a user
    hand-edits caption text.

    Returns the transcript unchanged if there's nothing to translate or the
    call fails — a caption problem must never cost the user the clip.
    """
    segs = (transcript or {}).get("segments") or []
    texts = [(s.get("text") or "").strip() for s in segs]
    if not any(texts):
        return transcript

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    prompt = TRANSLATE_PROMPT.format(target_language=target_language, count=len(texts), numbered_lines=numbered)
    data = _generate_json_with_fallback(prompt, _Translations, api_key, model)
    translations = data.get("translations") or []
    if len(translations) != len(segs):
        raise ValueError(f"expected {len(segs)} translated lines, got {len(translations)}")

    new_segments = []
    for seg, translated in zip(segs, translations):
        words_text = (translated or "").split()
        start, end = float(seg.get("start", 0)), float(seg.get("end", 0))
        n = len(words_text)
        step = max(0.0, end - start) / n if n else 0.0
        words = [{"word": f" {w}", "start": start + i * step, "end": start + (i + 1) * step}
                 for i, w in enumerate(words_text)]
        new_segments.append({"start": start, "end": end, "text": translated, "words": words})

    return {**transcript, "language": target_language, "segments": new_segments}
