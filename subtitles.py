import os
import re
import subprocess
import sys

from PIL import ImageFont

from ffmpeg_utils import (video_encode_args, escape_filter_value, QUALITY,
                          METADATA_SCRUB)


# Font files backing each subtitle font-picker name, kept in sync with
# openshorts-fontmap.conf (the fontconfig aliases libass resolves at burn
# time) so PIL measures the SAME glyphs that actually get rendered. Used only
# by the "highlight-box" effect, which needs real word widths to size and
# position a background rectangle — every other effect lets libass wrap and
# center text itself and never measures anything.
_FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_LIBERATION_DIR = "/usr/share/fonts/truetype/liberation"
_FONT_FILE_MAP = {
    "anton": os.path.join(_FONTS_DIR, "Anton-Regular.ttf"),
    "impact": os.path.join(_FONTS_DIR, "Anton-Regular.ttf"),
    "verdana": os.path.join(_LIBERATION_DIR, "LiberationSans-Bold.ttf"),
    "arial": os.path.join(_LIBERATION_DIR, "LiberationSans-Bold.ttf"),
    "helvetica": os.path.join(_LIBERATION_DIR, "LiberationSans-Bold.ttf"),
    "georgia": os.path.join(_LIBERATION_DIR, "LiberationSerif-Bold.ttf"),
    "courier new": os.path.join(_LIBERATION_DIR, "LiberationMono-Bold.ttf"),
    # The dashboard's own mono face (its "readout" labels), converted from the
    # self-hosted woff2 (OFL): latin subset, every French accent included.
    "jetbrains mono": os.path.join(_FONTS_DIR, "JetBrainsMono-Medium.ttf"),
}
_PIL_FONT_CACHE = {}


def _resolve_font_file(font_name):
    path = _FONT_FILE_MAP.get(str(font_name or "").strip().lower())
    return path if path and os.path.exists(path) else _FONT_FILE_MAP["anton"]


def _get_pil_font(font_path, size_px):
    key = (font_path, int(size_px))
    font = _PIL_FONT_CACHE.get(key)
    if font is None:
        try:
            font = ImageFont.truetype(font_path, max(1, int(size_px)))
        except OSError:
            font = ImageFont.load_default()
        _PIL_FONT_CACHE[key] = font
    return font


def _measure_text_width(text, font_path, size_px):
    """Advance width of `text` in the same units as `size_px` (arbitrary but
    consistent — callers only need widths relative to each other and to the
    font size, never an absolute pixel count).

    Advance, not the ink bounding box: libass lays words out by advance, so
    measuring ink packed them tighter than the burn does and let neighbouring
    words collide. Falls back to a char-count estimate rather than raising —
    a wrong width misplaces a highlight box, an exception loses the clip's
    captions entirely."""
    try:
        return _get_pil_font(font_path, size_px).getlength(text)
    except Exception:
        return len(text) * size_px * 0.55


_STDIO_CONFIGURED = False

# Shared faster-whisper config so both transcription paths (this module and
# main.transcribe_video) behave identically. "small" is meaningfully better at
# German than "base" without being much slower on CPU.
DEFAULT_WHISPER_MODEL = "small"


def get_whisper_config():
    """Return the faster-whisper model config, overridable via env vars."""
    return {
        "model_size": os.environ.get("WHISPER_MODEL", DEFAULT_WHISPER_MODEL),
        "device": os.environ.get("WHISPER_DEVICE", "cpu"),
        "compute_type": os.environ.get("WHISPER_COMPUTE", "int8"),
    }


# Decode params shared by both transcription paths. condition_on_previous_text
# is off to avoid repetition/hallucination loops; vad_filter drops silence.
WHISPER_TRANSCRIBE_PARAMS = {
    "beam_size": 5,
    "vad_filter": True,
    "condition_on_previous_text": False,
    "word_timestamps": True,
}


def merge_continuation_words(words):
    """Merge faster-whisper continuation fragments into their base word.

    faster-whisper marks a word boundary with a LEADING SPACE on each token.
    Compound-word fragments (e.g. "-Kanal.", ".200") arrive WITHOUT a leading
    space and belong to the preceding word. Without merging, "YouTube" and
    "-Kanal." get space-joined into "YouTube -Kanal." or split across subtitle
    blocks. We concatenate such fragments onto the previous word and extend its
    end time. Normal words keep their leading space, so real word boundaries
    (e.g. "ich habe") are never glued together.

    Returns a new list; the input dicts are not mutated.
    """
    merged = []
    for word in words:
        text = word.get("word", "")
        if merged and isinstance(text, str) and text and not text.startswith(" "):
            prev = merged[-1]
            prev["word"] = f"{prev.get('word', '')}{text}"
            if word.get("end") is not None:
                prev["end"] = word["end"]
        else:
            merged.append(dict(word))
    return merged


def _configure_stdio():
    global _STDIO_CONFIGURED
    if _STDIO_CONFIGURED:
        return
    _STDIO_CONFIGURED = True
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if not stream or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _log(message):
    _configure_stdio()
    stream = sys.stdout
    text = str(message)
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        stream.write(safe_text + "\n")
    stream.flush()


def _escape_ffmpeg_filter_value(value):
    """Escape a path/value for use inside a quoted FFmpeg filter argument.

    NOTE: an apostrophe in the path cannot be made safe here. ffmpeg's
    filtergraph parser is not a shell — the shell idiom ``'\\''`` was tried on
    29-jul-2026 and is worse than doing nothing: it drops the apostrophe AND
    swallows the following option, so ``ass='…Earth'\\''s.ass':fontsdir='…'``
    resolved to a filename of "…Earths.ass:fontsdir=…" and failed to open.

    The only reliable answer is to keep apostrophes OUT of any path that is
    interpolated into a filter. Callers generate their own subtitle filenames,
    so they control this: use a neutral name (``subs_<i>_<ts>.ass``), never one
    derived from a video title.

    The implementation now lives in ffmpeg_utils so the reframe engine can use
    it too: it was building `sendcmd=f='<abs path>'` unescaped, which is the
    same bug this function was written for.
    """
    return escape_filter_value(value)


def _normalize_subtitle_word(value):
    return " ".join(str(value or "").split())


def transcribe_audio(video_path):
    """
    Transcribe audio from a video file via the configured ASR backend.
    Returns transcript in the same format as main.py for compatibility.
    """
    # Lazy import: transcribe_backends imports helpers from this module.
    from transcribe_backends import transcribe_media

    _log(f"🎙️  Transcribing audio from: {video_path}")
    transcript = transcribe_media(video_path)
    _log(f"✅ Transcription complete. Language: {transcript['language']}")
    return transcript


def generate_srt_from_video(video_path, output_path, max_chars=20, max_duration=2.0,
                            style="classic", **style_opts):
    """
    Transcribe a video and generate a subtitle file directly (SRT, or karaoke
    ASS when style="karaoke"). Used for dubbed videos without a transcript.
    """
    transcript = transcribe_audio(video_path)

    # Get video duration to use as clip_end
    import cv2
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps else 0
    cap.release()

    if style == "karaoke":
        return generate_ass(transcript, 0, duration, output_path, max_chars, max_duration, **style_opts)
    return generate_srt(transcript, 0, duration, output_path, max_chars, max_duration)


def _collect_word_blocks(transcript, clip_start, clip_end, max_chars=20, max_duration=2.0, max_words=None):
    """
    Flatten transcript words for a clip range and group them into short blocks
    suitable for vertical video. Returns a list of blocks; each block is a list
    of {'word', 'start', 'end'} dicts with times relative to the clip.

    Continuation fragments are merged defensively here too, because transcripts
    from old jobs on disk store unmerged tokens (the leading space is still
    present, so the boundary signal survives).
    """
    flat_words = []
    for segment in transcript.get('segments', []):
        flat_words.extend(segment.get('words', []))
    flat_words = merge_continuation_words(flat_words)

    words = []
    for word_info in flat_words:
        if word_info.get('end', 0) > clip_start and word_info.get('start', 0) < clip_end:
            cleaned_word = _normalize_subtitle_word(word_info.get('word', ''))
            if not cleaned_word:
                continue
            words.append({
                'word': cleaned_word,
                'start': max(0, word_info['start'] - clip_start),
                'end': max(0, word_info['end'] - clip_start),
            })

    blocks = []
    current_block = []
    block_start = None

    for word in words:
        if not current_block:
            current_block = [word]
            block_start = word['start']
            continue

        current_text_len = sum(len(w['word']) + 1 for w in current_block)
        duration = word['end'] - block_start
        too_many_words = max_words and len(current_block) >= max_words

        if current_text_len + len(word['word']) > max_chars or duration > max_duration or too_many_words:
            blocks.append(current_block)
            current_block = [word]
            block_start = word['start']
        else:
            current_block.append(word)

    if current_block:
        blocks.append(current_block)
    return blocks


def generate_srt(transcript, clip_start, clip_end, output_path, max_chars=20, max_duration=2.0):
    """
    Generates an SRT file from the transcript for a specific time range.
    Groups words into short lines suitable for vertical video.
    """
    blocks = _collect_word_blocks(transcript, clip_start, clip_end, max_chars, max_duration)
    if not blocks:
        return False

    srt_content = ""
    for index, block in enumerate(blocks, 1):
        text = " ".join(w['word'] for w in block).strip()
        srt_content += format_srt_block(index, block[0]['start'], block[-1]['end'], text)

    # Write UTF-8 with BOM so Windows/FFmpeg subtitle readers reliably detect Unicode text.
    with open(output_path, 'w', encoding='utf-8-sig') as f:
        f.write(srt_content)

    return True


# Vertical margin for burned captions, in PlayResY=288 units (so ~15% of the
# frame height). The old hardcoded 25 (8.7%) put captions underneath TikTok's
# and Reels' own bottom UI — the caption/username block and the music ticker —
# where they were partly covered on the platform even though the exported file
# looked fine.
SAFE_MARGIN_V = 43


# The caption look applied automatically to every generated clip. Chosen by
# rendering four candidates on a real clip and comparing them (25-jul-2026):
# white Anton uppercase with a yellow active word, heavy black outline, gentle
# pop. Yellow because it is the one colour that almost never occurs in footage,
# so the active word reads instantly on any background; the base text stays
# fully opaque (dimming it tested worse over bright scenes). This is a starting
# point, not a cage — the subtitle modal still overrides every field.
AUTO_CAPTION_STYLE = {
    "style": "karaoke",
    "alignment": "bottom",
    "font_name": "Anton",
    "font_size": 44,
    "font_color": "#FFFFFF",
    "highlight_color": "#FFE500",
    "border_color": "#000000",
    "border_width": 4,
    "effect": "pop",
    "base_opacity": 1.0,
    "uppercase": True,
    "max_chars": 16,
    "max_duration": 1.4,
}


def _ass_time(seconds):
    """Format seconds as ASS timestamp H:MM:SS.cc (centiseconds)."""
    seconds = max(0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _hex_to_ass_inline_color(hex_color, fallback="FFFFFF"):
    """Convert #RRGGBB to the &HBBGGRR& form used by inline \\c override tags."""
    hex_digits = str(hex_color or "").lstrip('#')
    if not _HEX_COLOR_RE.match(hex_digits):
        hex_digits = fallback
    r = hex_digits[0:2]
    g = hex_digits[2:4]
    b = hex_digits[4:6]
    return f"&H{b}{g}{r}&".upper()


def _escape_ass_text(text):
    """Neutralize characters that would start ASS override blocks."""
    return str(text).replace('\\', '/').replace('{', '(').replace('}', ')')


def _dim_hex_color(hex_color, opacity, fallback="FFFFFF"):
    """Fully-opaque 'dimmed' variant of a color (scaled toward black).

    Dimming via alpha looks muddy in ASS: libass draws the outline as a
    filled shape UNDER the fill, so a semi-transparent white fill blends
    with its own black outline into dark grey. Scaling the RGB instead
    keeps the text crisp on every player."""
    hex_digits = str(hex_color or "").lstrip('#')
    if not _HEX_COLOR_RE.match(hex_digits):
        hex_digits = fallback
    # Gentle curve: even strong dimming stays a readable light silver, matching
    # the airy look of browser-alpha dimming over bright video.
    factor = 0.5 + 0.5 * _clamp_number(opacity, 0.05, 1.0, 1.0)
    r = min(255, round(int(hex_digits[0:2], 16) * factor))
    g = min(255, round(int(hex_digits[2:4], 16) * factor))
    b = min(255, round(int(hex_digits[4:6], 16) * factor))
    return f"{r:02X}{g:02X}{b:02X}"


def _emit_highlight_box_events(block, font_path, fontsize, play_res_x, play_res_y,
                                margin_v, uppercase, highlight_inline,
                                active_text_inline, dim_text_inline, glyph_unit):
    """Build the ASS events for one caption block under effect="highlight-box".

    ASS's opaque-background style (BorderStyle=3) applies to a whole line, not
    one word inside it, so the usual "libass auto-wraps/centers, we just drop
    inline override tags on the active word" approach (every other effect)
    can't produce a background scoped to a single word. This lays the block
    out manually instead: PIL measures each word's real rendered width (in
    the same font/size libass will burn with), which gives exact centers to
    \\pos() each word at, plus a filled \\p1 rectangle drawn behind the active
    one at the same anchor. This is why generate_ass declares PlayResX
    explicitly for this effect — \\pos() coordinates need a known coordinate
    space, whereas every other effect lets libass derive it from the real
    video and never positions anything itself.

    Split-seam repositioning (seam_prefix in generate_ass) is not supported
    here — a manually-laid-out line does not have a single alignment anchor
    to redirect the way an \\an5 override on flowing text does.

    Words that don't fit on one line wrap onto another (libass would do this
    on its own for the flowing-text effects; here WE own layout, so we have
    to reproduce it — without this a wide block just runs off both edges of
    the frame instead of wrapping).

    ``glyph_unit`` converts a glyph dimension into \\pos() coordinate units,
    and it is NOT 1: measured against real burns, libass sizes glyphs by
    video_width/PlayResY while it maps coordinates by video_height/PlayResY,
    so a width measured in font units covers only `video_width/video_height`
    as much of the coordinate space. Ignoring that drew every highlight box
    1.78x too wide on a 9:16 clip and pushed the last word off frame.
    """
    space_width = (_measure_text_width(" ", font_path, fontsize) or fontsize * 0.28) * glyph_unit
    words_display = []
    word_widths = []
    for w in block:
        text = _escape_ass_text(w['word'])
        text = text.upper() if uppercase else text
        words_display.append(text)
        word_widths.append(
            max(1.0, _measure_text_width(text, font_path, fontsize) * glyph_unit))

    # Leaves ~6% margin each side, matching the style's own MarginL/MarginR.
    available_width = play_res_x * 0.88
    lines = []  # list of (word_indices, line_width)
    current_idx, current_width = [], 0.0
    for i, w in enumerate(word_widths):
        added_width = w if not current_idx else current_width + space_width + w
        if current_idx and added_width > available_width:
            lines.append((current_idx, current_width))
            current_idx, current_width = [i], w
        else:
            current_idx.append(i)
            current_width = added_width
    if current_idx:
        lines.append((current_idx, current_width))

    # Every glyph dimension below is in coordinate units, not font units.
    em = fontsize * glyph_unit
    line_height = em * 1.35
    # Matches Alignment=2 + MarginV semantics: the LAST line sits with its
    # baseline area `margin_v` above the bottom edge; earlier lines stack
    # upward from there. em/2 is a rough half-height to get the vertical
    # CENTER an5 needs, not the baseline an2 would use.
    last_line_y = play_res_y - margin_v - em * 0.5

    centers = [0.0] * len(word_widths)
    line_y_of = [0.0] * len(word_widths)
    for line_no, (idx_list, line_width) in enumerate(lines):
        line_y = last_line_y - (len(lines) - 1 - line_no) * line_height
        cursor = play_res_x / 2.0 - line_width / 2.0
        for i in idx_list:
            centers[i] = cursor + word_widths[i] / 2.0
            line_y_of[i] = line_y
            cursor += word_widths[i] + space_width

    pad_x = em * 0.22
    pad_y = em * 0.30

    events = []
    for i, word in enumerate(block):
        ev_start = block[0]['start'] if i == 0 else word['start']
        ev_end = block[i + 1]['start'] if i < len(block) - 1 else block[-1]['end']
        if ev_end <= ev_start:
            continue
        start_ts, end_ts = _ass_time(ev_start), _ass_time(ev_end)
        line_center_y = line_y_of[i]

        rect_w = word_widths[i] + pad_x * 2
        rect_h = em + pad_y * 2
        events.append(
            f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,"
            f"{{\\an5\\pos({centers[i]:.1f},{line_center_y:.1f})"
            f"\\1c{highlight_inline}\\bord0\\shad0\\p1}}"
            f"m 0 0 l {rect_w:.1f} 0 l {rect_w:.1f} {rect_h:.1f} l 0 {rect_h:.1f}{{\\p0}}"
        )

        for j, text in enumerate(words_display):
            color_tag = (f"\\c{active_text_inline}\\bord0\\shad0" if j == i
                        else f"\\c{dim_text_inline}")
            events.append(
                f"Dialogue: 1,{start_ts},{end_ts},Default,,0,0,0,,"
                f"{{\\an5\\pos({centers[j]:.1f},{line_y_of[j]:.1f}){color_tag}}}{text}"
            )
    return events


def generate_ass(transcript, clip_start, clip_end, output_path,
                 max_chars=20, max_duration=2.0, alignment='bottom',
                 fontsize=16, font_name="Verdana", font_color="#FFFFFF",
                 border_color="#000000", border_width=2,
                 highlight_color="#FFD700", bg_color="#000000", bg_opacity=0.0,
                 effect="none", base_opacity=1.0, uppercase=False,
                 margin_v=SAFE_MARGIN_V, split_ranges=None, position_percent=None,
                 max_words=None, letter_spacing=0, aspect_ratio=9.0 / 16.0):
    """
    Generates a karaoke-style ASS file: each block is shown like the SRT path,
    but the currently spoken word is rendered in highlight_color (modern
    TikTok/CapCut caption look). One dialogue event per word, back to back, so
    the highlight moves with the audio without flicker.

    effect: "none" | "glow" (neon shine around the active word) |
            "pop" (active word scales up) | "box" (thick colored outline) |
            "highlight-box" (solid filled rectangle behind the active word —
            see _emit_highlight_box_events for why this one needs its own
            manual-layout code path instead of inline override tags).
    base_opacity: opacity of the non-active words — dimmed base text is the
    modern captioneer look (e.g. 0.4).
    position_percent: 0-100, how far UP from the bottom edge to place the
    caption, as a fraction of the frame height (0 = flush bottom, matching
    SAFE_MARGIN_V's own ~15%; 100 = flush top) — for a user dragging a slider
    to an exact spot rather than picking top/middle/bottom. Overrides
    ``alignment``/``margin_v`` entirely when given, but still renders through
    the same bottom-anchored (Alignment=2) style, just with MarginV computed
    from the percentage (of PlayResY=288) instead of a fixed preset.
    aspect_ratio: width/height of the clip (9/16 vertical, 1 square, 16/9
    horizontal). Only consulted by effect="highlight-box", to know PlayResX
    (declared explicitly for that effect so word positions can be computed in
    the same units libass will render with) — every other effect lets libass
    auto-derive PlayResX from the real video and never needs this value.
    """
    blocks = _collect_word_blocks(transcript, clip_start, clip_end, max_chars, max_duration, max_words)
    if not blocks:
        return False

    # Match the SRT burn path: PlayResY 288 keeps font sizes consistent.
    final_fontsize = int(_clamp_number(fontsize, 10, 200, 16) * 0.85)
    if final_fontsize < 10:
        final_fontsize = 10

    if position_percent is not None:
        ass_alignment = 2  # bottom-anchored; MarginV alone places it
        # Capped at 92 rather than 100 so a caption dragged to the very top
        # of the slider still has a sliver of margin instead of clipping
        # against frame 0.
        pct = _clamp_number(position_percent, 0, 92, 15)
        margin_v = int(round(pct / 100.0 * 288))
    else:
        align_map = {'top': 8, 'middle': 5, 'bottom': 2}
        ass_alignment = align_map.get(str(alignment).lower(), 2)

    # On a SPLIT scene the two speakers are stacked and the seam between the
    # halves (exactly mid-frame) is the one place the text covers nobody, so
    # every word event inside such a stretch is anchored there with an inline
    # \an5, per event rather than per style: a clip mixes stacked and single
    # shots, and the text moves with the cut. ``split_ranges`` is a list of
    # (start, end) in clip seconds (layout_ranges.split_ranges); the style's
    # own alignment still rules everywhere else. Only the ASS path can do
    # this: SRT burns carry one alignment for the whole file.
    seam_ranges = [(float(a), float(b)) for a, b in (split_ranges or [])]

    def seam_prefix(t):
        return "{\\an5}" if any(a <= t < b for a, b in seam_ranges) else ""

    safe_font = _sanitize_font_name(font_name)
    base_opacity = _clamp_number(base_opacity, 0.05, 1.0, 1.0)
    # Dim inactive words via a fully-opaque scaled color (NOT alpha — see
    # _dim_hex_color); the active word overrides the color inline.
    primary_colour = hex_to_ass_color(_dim_hex_color(font_color, base_opacity), 1.0)
    bg_opacity = _clamp_number(bg_opacity, 0.0, 1.0, 0.0)
    border_width = _clamp_number(border_width, 0, 10, 2)

    if bg_opacity > 0:
        border_style = 3
        outline_colour = hex_to_ass_color(bg_color, bg_opacity, fallback="000000")
        outline_width = 1
    else:
        border_style = 1
        outline_colour = hex_to_ass_color(border_color, 1.0, fallback="000000")
        # 0 must mean NO outline (the editor's Border slider goes down to
        # "None") — this used to floor at 1, so a burned clip always showed a
        # thin outline the live preview never did.
        outline_width = max(0, int(border_width))

    back_colour = hex_to_ass_color("#000000", 0.0)
    highlight_inline = _hex_to_ass_inline_color(highlight_color, fallback="FFD700")

    # Inline override tags for the active word; {\r} after it resets to the
    # (dimmed) style so the rest of the block stays untouched.
    if effect == "glow":
        glow_bord = max(3, int(outline_width) + 2)
        active_prefix = (f"{{\\c&HFFFFFF&\\3c{highlight_inline}"
                         f"\\bord{glow_bord}\\blur4}}")
    elif effect == "box":
        box_bord = max(4, int(outline_width) + 3)
        active_prefix = (f"{{\\c&HFFFFFF&\\3c{highlight_inline}"
                         f"\\bord{box_bord}\\blur0}}")
    elif effect == "pop":
        # Gentle pop. The old 75->112 range started the word so small that any
        # frame caught mid-animation read as a sizing bug rather than a beat.
        active_prefix = (f"{{\\c{highlight_inline}"
                         f"\\fscx90\\fscy90\\t(0,110,\\fscx108\\fscy108)}}")
    else:
        active_prefix = f"{{\\c{highlight_inline}}}"

    # PlayResX is normally left unset (libass derives it from the real video
    # AR). effect="highlight-box" needs it declared explicitly because it
    # computes \pos() coordinates itself in Python — every other effect
    # ignores this line.
    play_res_x = int(round(288 * _clamp_number(aspect_ratio, 0.2, 3.0, 9.0 / 16.0)))

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        "PlayResY: 288\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{safe_font},{final_fontsize},{primary_colour},{primary_colour},"
        f"{outline_colour},{back_colour},1,0,0,0,100,100,{_clamp_number(letter_spacing, -5, 20, 0)},0,{border_style},"
        f"{outline_width},0,{ass_alignment},10,10,{int(_clamp_number(margin_v, 0, 280, SAFE_MARGIN_V))},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events = []
    if effect == "highlight-box":
        font_path = _resolve_font_file(font_name)
        active_text_inline = _hex_to_ass_inline_color(border_color, fallback="000000")
        dim_text_inline = _hex_to_ass_inline_color(_dim_hex_color(font_color, base_opacity),
                                                   fallback="FFFFFF")
        safe_margin_v = int(_clamp_number(margin_v, 0, 280, SAFE_MARGIN_V))
        # Font units -> \pos() coordinate units. libass sizes glyphs off the
        # video WIDTH but maps coordinates off its HEIGHT, so the conversion
        # is the clip's aspect ratio (measured, see _emit_highlight_box_events).
        glyph_unit = _clamp_number(aspect_ratio, 0.2, 3.0, 9.0 / 16.0)
        for block in blocks:
            events.extend(_emit_highlight_box_events(
                block, font_path, final_fontsize, play_res_x, 288, safe_margin_v,
                uppercase, highlight_inline, active_text_inline, dim_text_inline,
                glyph_unit))
    else:
        for block in blocks:
            for i, word in enumerate(block):
                # Event runs until the next word starts (no flicker in gaps);
                # the last word holds until the block ends.
                ev_start = block[0]['start'] if i == 0 else word['start']
                ev_end = block[i + 1]['start'] if i < len(block) - 1 else block[-1]['end']
                if ev_end <= ev_start:
                    continue

                parts = []
                for j, other in enumerate(block):
                    text = _escape_ass_text(other['word'])
                    if uppercase:
                        text = text.upper()
                    if j == i:
                        parts.append(f"{active_prefix}{text}{{\\r}}")
                    else:
                        parts.append(text)

                events.append(
                    f"Dialogue: 0,{_ass_time(ev_start)},{_ass_time(ev_end)},Default,,0,0,0,,"
                    f"{seam_prefix(ev_start)}{' '.join(parts)}"
                )

    if not events:
        return False

    with open(output_path, 'w', encoding='utf-8-sig') as f:
        f.write(header + "\n".join(events) + "\n")

    return True

def format_srt_block(index, start, end, text):
    def format_time(seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
        
    return f"{index}\n{format_time(start)} --> {format_time(end)}\n{text}\n\n"

_HEX_COLOR_RE = re.compile(r'^[0-9A-Fa-f]{6}$')
_FONT_NAME_RE = re.compile(r'[^A-Za-z0-9 _-]')


def hex_to_ass_color(hex_color, opacity=1.0, fallback="FFFFFF"):
    """Convert #RRGGBB to ASS &HAABBGGRR format. opacity: 0.0=transparent, 1.0=opaque.

    Invalid hex (e.g. "#GGGGGG", None, wrong length) falls back to `fallback`
    instead of raising, so a bad color from the client can't 500 the request.
    """
    hex_digits = str(hex_color or "").lstrip('#')
    if not _HEX_COLOR_RE.match(hex_digits):
        hex_digits = fallback
    opacity = _clamp_number(opacity, 0.0, 1.0, 1.0)
    r = int(hex_digits[0:2], 16)
    g = int(hex_digits[2:4], 16)
    b = int(hex_digits[4:6], 16)
    alpha = round((1.0 - opacity) * 255)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _clamp_number(value, lo, hi, default):
    """Coerce value to float and clamp to [lo, hi]; use default if not numeric."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        num = float(default)
    return max(lo, min(hi, num))


def _sanitize_font_name(name):
    """Strip anything but [A-Za-z0-9 _-] so the font name can't inject extra
    ASS override fields (commas/braces/backslashes) into force_style."""
    cleaned = _FONT_NAME_RE.sub('', str(name or '')).strip()
    return cleaned or "Verdana"


def burn_subtitles(video_path, srt_path, output_path, alignment=2, fontsize=16,
                   font_name="Verdana", font_color="#FFFFFF",
                   border_color="#000000", border_width=2,
                   bg_color="#000000", bg_opacity=0.0):
    """
    Burns subtitles into the video using FFmpeg.
    Supports two modes:
    - Outline mode (bg_opacity=0): Text with colored outline/border
    - Box mode (bg_opacity>0): Text with semi-transparent background box
    """
    # Position mapping (ASS numpad-style alignment: 8=top-center,
    # 5=middle-center, 2=bottom-center — 6 and 10 used here before were
    # wrong: 6 is middle-RIGHT and 10 isn't a valid alignment at all).
    ass_alignment = 2
    align_lower = str(alignment).lower()
    if align_lower == 'top':
        ass_alignment = 8
    elif align_lower == 'middle':
        ass_alignment = 5
    elif align_lower == 'bottom':
        ass_alignment = 2

    # Font size scaling for ASS virtual resolution (PlayResY=288 default)
    # For vertical 1080x1920 video, we need larger text for readability
    final_fontsize = int(_clamp_number(fontsize, 10, 200, 16) * 0.85)
    if final_fontsize < 10:
        final_fontsize = 10

    safe_font_name = _sanitize_font_name(font_name)
    bg_opacity = _clamp_number(bg_opacity, 0.0, 1.0, 0.0)
    border_width = _clamp_number(border_width, 0, 10, 2)

    # Path handling for FFmpeg filter syntax
    safe_srt_path = _escape_ffmpeg_filter_value(srt_path)

    # Convert colors to ASS format and build style
    primary_colour = hex_to_ass_color(font_color, 1.0)

    if bg_opacity > 0:
        # Box mode: opaque background box
        border_style = 3
        outline_colour = hex_to_ass_color(bg_color, bg_opacity, fallback="000000")
        outline_width = 1
    else:
        # Outline mode: text border/outline. 0 must mean NO outline (see the
        # same fix in generate_ass).
        border_style = 1
        outline_colour = hex_to_ass_color(border_color, 1.0, fallback="000000")
        outline_width = max(0, int(border_width))

    back_colour = hex_to_ass_color("#000000", 0.0)

    style_string = (
        f"Alignment={ass_alignment},"
        f"Fontname={safe_font_name},"
        f"Fontsize={final_fontsize},"
        f"PrimaryColour={primary_colour},"
        f"OutlineColour={outline_colour},"
        f"BackColour={back_colour},"
        f"BorderStyle={border_style},"
        f"Outline={outline_width},"
        f"Shadow=0,"
        f"MarginV={SAFE_MARGIN_V},"
        f"Bold=1"
    )

    # Let libass see the fonts bundled with the app (e.g. Anton for Impact)
    # even when the system fontconfig has no cache for them.
    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    safe_fonts_dir = _escape_ffmpeg_filter_value(fonts_dir)

    # The first option is named explicitly (filename=) rather than positional:
    # ffmpeg 8's filtergraph parser rejects a quoted positional value that is
    # followed by more :name=value options ("No option name near ..."), while
    # the named form parses on every version back to 4.x.
    if str(srt_path).lower().endswith('.ass'):
        # ASS files (karaoke style) carry their own styles; force_style would
        # override the per-word color tags.
        vf = f"ass=filename='{safe_srt_path}':fontsdir='{safe_fonts_dir}'"
    else:
        vf = (f"subtitles=filename='{safe_srt_path}':fontsdir='{safe_fonts_dir}'"
              f":charenc=UTF-8:force_style='{style_string}'")

    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-vf', vf,
        '-c:a', 'copy',
        *video_encode_args(QUALITY),
        *METADATA_SCRUB,
        '-movflags', '+faststart',
        output_path
    ]

    _log(f"🎬 Burning subtitles: {' '.join(cmd)}")
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if result.returncode != 0:
        stderr_text = result.stderr.decode(errors='replace')
        _log(f"❌ FFmpeg Subtitle Error: {stderr_text}")
        raise Exception(f"FFmpeg failed: {stderr_text}")

    return True

