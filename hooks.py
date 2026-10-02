import os
import re
import textwrap
import subprocess
import urllib.request
import uuid
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from ffmpeg_utils import video_encode_args, layer_encode_args, QUALITY, METADATA_SCRUB


def _truncate_bytes(text, max_bytes):
    """Trim to a byte budget without splitting a multi-byte character.

    Deliberately duplicated from main.truncate_bytes: this module stays free of
    main's heavy imports (cv2, mediapipe, torch) so it can be used standalone.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", "ignore")

FONT_URL = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSerif/NotoSerif-Bold.ttf"
FONT_DIR = "fonts"
FONT_PATH = os.path.join(FONT_DIR, "NotoSerif-Bold.ttf")

# Codepoint ranges NotoSerif has no glyphs for (would render as tofu boxes).
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # emoticons, symbols, transport, supplemental
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicators (flags)
    "\U00002B00-\U00002BFF"  # arrows, stars
    "\U0000FE0E\U0000FE0F"   # variation selectors
    "\U0000200D"             # zero-width joiner
    "\U000020E3"             # combining keycap
    "]+"
)

# Emoji-capable fonts, probed at runtime (Windows, WSL, Linux/Docker, macOS).
_EMOJI_FONT_CANDIDATES = [
    "C:\\Windows\\Fonts\\seguiemj.ttf",
    "/mnt/c/Windows/Fonts/seguiemj.ttf",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf",
    "/System/Library/Fonts/Apple Color Emoji.ttc",
]


# Bitmap strike sizes color-emoji fonts ship with. NotoColorEmoji (the font
# the Docker image installs) ONLY loads at its strike size — asking for an
# arbitrary size raises "invalid pixel size" — so glyphs are rendered at the
# native size and rescaled at draw time.
_EMOJI_BITMAP_SIZES = [109, 128, 136, 160, 96, 72, 64, 32]


def _load_emoji_font(font_size):
    """Return (font, native_size) for an emoji-capable font, or None.

    native_size == font_size for scalable fonts (Segoe UI Emoji); for
    fixed-bitmap fonts (NotoColorEmoji) it is the strike size the font
    actually loaded at, and the renderer scales glyphs down from it."""
    for path in _EMOJI_FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            return ImageFont.truetype(path, font_size), font_size
        except Exception:
            pass
        for native in _EMOJI_BITMAP_SIZES:
            try:
                return ImageFont.truetype(path, native), native
            except Exception:
                continue
    return None


def _split_emoji_runs(text):
    """Split text into (is_emoji, chunk) runs."""
    runs = []
    pos = 0
    for m in _EMOJI_RE.finditer(text):
        if m.start() > pos:
            runs.append((False, text[pos:m.start()]))
        runs.append((True, m.group()))
        pos = m.end()
    if pos < len(text):
        runs.append((False, text[pos:]))
    return runs


def _emoji_scale(font, emoji_font):
    """Draw-time scale factor from the emoji font's native size to the text
    size. 1.0 for scalable emoji fonts; < 1 for fixed-bitmap strikes."""
    efont, native = emoji_font
    target = getattr(font, "size", native)
    return target / float(native) if native else 1.0


def _measure_width(draw, text, font, emoji_font):
    """Pixel width of a line, measuring emoji runs with the emoji font.

    emoji_font is the (font, native_size) pair from _load_emoji_font, or None."""
    width = 0.0
    for is_emoji, chunk in _split_emoji_runs(text):
        if is_emoji and emoji_font:
            width += (draw.textlength(chunk, font=emoji_font[0])
                      * _emoji_scale(font, emoji_font))
        else:
            width += draw.textlength(chunk, font=font)
    return width


def _render_emoji_chunk(chunk, emoji_font, scale, fill):
    """Rasterize an emoji run at the font's native size, scaled to the text
    size. Returns an RGBA image ready to alpha-composite, or None."""
    efont, native = emoji_font
    probe = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    w = int(probe.textlength(chunk, font=efont))
    if w <= 0:
        return None
    # Emoji glyphs can overshoot the em box slightly; 1.3x covers it.
    tmp = Image.new('RGBA', (w, int(native * 1.3)), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    try:
        d.text((0, 0), chunk, font=efont, embedded_color=True)
    except TypeError:
        d.text((0, 0), chunk, font=efont, fill=fill)
    if scale == 1.0:
        return tmp
    return tmp.resize((max(int(w * scale), 1), max(int(tmp.height * scale), 1)),
                      Image.LANCZOS)


def _draw_mixed(img, draw, xy, text, font, emoji_font, fill, outline=None):
    """Draw a line onto img, rendering emoji runs with the emoji font (in
    color if supported, rescaled when the font is a fixed-size bitmap).
    outline: optional (color, px) stroke drawn under the text."""
    x, y = xy
    stroke_w = outline[1] if outline else 0
    stroke_fill = outline[0] if outline else None
    for is_emoji, chunk in _split_emoji_runs(text):
        if is_emoji and emoji_font:
            scale = _emoji_scale(font, emoji_font)
            rendered = _render_emoji_chunk(chunk, emoji_font, scale, fill)
            if rendered is not None:
                img.alpha_composite(rendered, (int(x), int(y)))
                x += draw.textlength(chunk, font=emoji_font[0]) * scale
        else:
            if stroke_w:
                draw.text((x, y), chunk, font=font, fill=fill,
                          stroke_width=stroke_w, stroke_fill=stroke_fill)
            else:
                draw.text((x, y), chunk, font=font, fill=fill)
            x += draw.textlength(chunk, font=font)


def _break_long_word(draw, word, font, emoji_font, max_width):
    """Character-level hard wrap for a single word wider than max_width."""
    pieces = []
    current = ""
    for ch in word:
        if current and _measure_width(draw, current + ch, font, emoji_font) > max_width:
            pieces.append(current)
            current = ch
        else:
            current += ch
    if current:
        pieces.append(current)
    return pieces

def download_font_if_needed():
    """Downloads a serif font for the hook text if not present."""
    if not os.path.exists(FONT_DIR):
        os.makedirs(FONT_DIR)
    if not os.path.exists(FONT_PATH):
        print(f"⬇️ Downloading font from {FONT_URL}...")
        try:
            # Add user agent to avoid 403s slightly
            req = urllib.request.Request(
                FONT_URL, 
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req) as response, open(FONT_PATH, 'wb') as out_file:
                out_file.write(response.read())
            print("✅ Font downloaded.")
        except Exception as e:
            print(f"❌ Failed to download font: {e}")

# Hook visual styles. Each maps to box fill (RGBA, alpha 0 = no box), text
# color, and an optional text outline (color, px) for box-less looks.
HOOK_STYLES = {
    # White card, black serif text (original look).
    "classic": {"box": (255, 255, 255, 240), "text": (0, 0, 0), "outline": None, "shadow": True},
    # Dark card, white text.
    "dark":    {"box": (18, 18, 20, 235),    "text": (255, 255, 255), "outline": None, "shadow": True},
    # Bright yellow card, black text (high-contrast TikTok look).
    "yellow":  {"box": (255, 214, 0, 245),   "text": (0, 0, 0), "outline": None, "shadow": True},
    # Red "breaking" card, white text.
    "red":     {"box": (220, 38, 38, 245),   "text": (255, 255, 255), "outline": None, "shadow": True},
    # No box: white text with a thick black outline (caption/MrBeast style).
    "outline": {"box": (0, 0, 0, 0),         "text": (255, 255, 255), "outline": ((0, 0, 0), 8), "shadow": False},
    # No box: yellow text with black outline.
    "outline_yellow": {"box": (0, 0, 0, 0),  "text": (255, 214, 0),   "outline": ((0, 0, 0), 8), "shadow": False},
    # Headline: big condensed caps (Anton), white + heavy outline, the 1-2
    # strongest words in yellow, one line whenever it fits. Rendered by
    # create_bold_hook_image and faded/slid in (add_hook_to_video).
    "bold":    {"box": (0, 0, 0, 0),         "text": (255, 255, 255), "outline": ((0, 0, 0), 10), "shadow": True},
    # Documentary line: a yellow eyebrow (the topic), a short rule, the hook in
    # sentence case with its payoff word in yellow, under a soft veil; the
    # eyebrow and the rule stay for the whole clip. create_docline_frames and
    # _add_docline_hook (H3 of the hook study, 2-oct-2026).
    "docline": {"box": (0, 0, 0, 0),         "text": (255, 255, 255), "outline": None, "shadow": True},
}

BOLD_FONT_CANDIDATES = [
    "/usr/local/share/fonts/openshorts/Anton-Regular.ttf",
    os.path.join(FONT_DIR, "Anton-Regular.ttf"),
]
BOLD_ACCENT = (255, 216, 77)   # the natural captions' accent yellow
_BOLD_STOP = {
    "THE", "A", "AN", "AND", "OR", "BUT", "OF", "TO", "IN", "ON", "AT", "FOR", "WITH", "IS", "ARE", "WAS",
    "IT", "IT'S", "ITS", "THIS", "THAT", "YOU", "YOUR", "I", "WE", "HE", "SHE", "THEY", "MY", "BE", "BY",
    "LE", "LA", "LES", "DE", "DU", "DES", "UN", "UNE", "ET", "EST", "CE", "QUI", "QUE", "POUR", "DANS",
    "WHY", "HOW", "WHAT", "NOT", "ISN'T", "DON'T", "CAN", "WILL", "JUST",
    "THINK", "KNOW", "REALLY", "ABOUT", "THAN", "EVERY", "THING", "THINGS", "ACTUALLY", "BEEN", "HAVE",
    "FROM", "INTO", "WHEN", "THEN", "THERE", "THEIR", "WOULD", "COULD", "SHOULD", "VERY", "MUCH",
}


def _bold_font_path():
    return next((p for p in BOLD_FONT_CANDIDATES if os.path.exists(p)), FONT_PATH)


def _accent_words(words):
    """Indexes of the 1-2 words to colour: the longest non-filler ones, the
    later one winning a tie (a hook puts its payoff last)."""
    scored = [(len(re.sub(r"[^\w]", "", w)), i) for i, w in enumerate(words)
              if re.sub(r"[^\w']", "", w) not in _BOLD_STOP and len(re.sub(r"[^\w]", "", w)) >= 4]
    scored.sort(reverse=True)
    return {i for _, i in scored[:2 if len(words) >= 5 else 1]}


def create_bold_hook_image(text, video_width, output_image_path, font_scale=1.0):
    """The "bold" hook as a transparent PNG: one line if it fits at >= ~8.5%
    of the frame width (big enough to read at a glance), else two balanced
    lines. Returns (path, w, h)."""
    text = re.sub(r"\s+", " ", _EMOJI_RE.sub("", text or "")).strip().upper()
    words = text.split() or [""]
    font_path = _bold_font_path()
    max_w = int(video_width * 0.92)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    def width(line_words, font):
        return probe.textlength(" ".join(line_words), font=font)

    lines, font = None, None
    hi = int(video_width * 0.115 * font_scale)
    for size in range(hi, int(video_width * 0.085) - 1, -2):
        f = ImageFont.truetype(font_path, size)
        if width(words, f) <= max_w:
            lines, font = [words], f
            break
    if lines is None:
        for size in range(int(video_width * 0.1 * font_scale), 20, -2):
            f = ImageFont.truetype(font_path, size)
            best = min(range(1, max(2, len(words))),
                       key=lambda k: max(width(words[:k], f), width(words[k:], f)))
            if max(width(words[:best], f), width(words[best:], f)) <= max_w or size <= 22:
                lines, font = [words[:best], words[best:]], f
                break
    lines = [l for l in lines if l]
    size = font.size
    accents = _accent_words(words)
    stroke = max(4, size // 9)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    gap = int(size * 0.08)
    pad = stroke * 3 + int(size * 0.3)
    w = int(max(width(l, font) for l in lines)) + 2 * pad
    h = len(lines) * line_h + (len(lines) - 1) * gap + 2 * pad

    # A soft dark cloud hugging the letters (not a box): keeps them readable
    # over a busy set — a yellow neon sign behind yellow words — without the
    # "template card" look.
    halo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    hd, sd, d = ImageDraw.Draw(halo), ImageDraw.Draw(shadow), ImageDraw.Draw(img)
    idx, y = 0, pad
    for line in lines:
        x = (w - width(line, font)) / 2
        for word in line:
            fill = BOLD_ACCENT if idx in accents else (255, 255, 255)
            hd.text((x, y), word, font=font, fill=(0, 0, 0, 150),
                    stroke_width=stroke * 3, stroke_fill=(0, 0, 0, 150))
            sd.text((x, y + size * 0.07), word, font=font, fill=(0, 0, 0, 170),
                    stroke_width=stroke, stroke_fill=(0, 0, 0, 170))
            d.text((x, y), word, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))
            x += probe.textlength(word + " ", font=font)
            idx += 1
        y += line_h + gap
    out = halo.filter(ImageFilter.GaussianBlur(max(6, size // 5)))
    out.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(3, size // 14))))
    out.alpha_composite(img)
    out.save(output_image_path)
    return output_image_path, w, h


def create_hook_image(text, target_width, output_image_path="hook_overlay.png", font_scale=1.0, style="classic"):
    """
    Generates a hook overlay image using pixel-based wrapping.
    target_width: The max width the box should occupy (e.g. 85% of video)
    style: one of HOOK_STYLES (classic/dark/yellow/red/outline/outline_yellow)
    """
    download_font_if_needed()

    look = HOOK_STYLES.get(style, HOOK_STYLES["classic"])
    box_fill = look["box"]
    text_fill = look["text"]
    outline = look["outline"]
    has_box = box_fill[3] > 0
    draw_shadow = look["shadow"]
    
    # Configuration
    padding_x = 30 # Balanced padding
    padding_y = 25 
    line_spacing = 20 # Increased spacing
    cornerradius = 20
    shadow_offset = (5, 5) 
    shadow_blur = 10
    
    # Font Size Calculation (approx 5% of width - tuned to match Noto Serif Bold metrics in browser)
    base_font_size = int(target_width * 0.05)
    font_size = int(base_font_size * font_scale)
    
    try:
        font = ImageFont.truetype(FONT_PATH, font_size)
    except Exception as e:
        print(f"⚠️ Warning: Could not load font {FONT_PATH}, using default. Error: {e}")
        font = ImageFont.load_default()

    # Emoji handling: render with an emoji-capable font if one exists,
    # otherwise strip emoji instead of drawing tofu boxes.
    emoji_font = None
    if _EMOJI_RE.search(text):
        emoji_font = _load_emoji_font(font_size)
        if emoji_font is None:
            text = _EMOJI_RE.sub("", text)
            text = re.sub(r"[ \t]{2,}", " ", text).strip()

    # Wrap text logic (Pixel-based)
    dummy_img = Image.new('RGBA', (1, 1))
    draw = ImageDraw.Draw(dummy_img)

    max_text_width = target_width - (2 * padding_x)

    # Handle manual newlines first
    paragraphs = text.split('\n')
    lines = []

    for p in paragraphs:
        if not p.strip():
            lines.append("")
            continue

        words = p.split()
        current_line = []

        for word in words:
            # Test if adding word fits
            test_line = ' '.join(current_line + [word])
            w = _measure_width(draw, test_line, font, emoji_font)

            if w <= max_text_width:
                current_line.append(word)
                continue

            # Word doesn't fit on the current line
            if current_line:
                lines.append(' '.join(current_line))
                current_line = []

            if _measure_width(draw, word, font, emoji_font) <= max_text_width:
                current_line = [word]
            else:
                # Single word wider than the box: hard-wrap it character-wise
                # so it can't get cut off at the edges.
                pieces = _break_long_word(draw, word, font, emoji_font, max_text_width)
                lines.extend(pieces[:-1])
                current_line = [pieces[-1]] if pieces else []

        if current_line:
            lines.append(' '.join(current_line))

    # Recalculate true width/height
    max_line_width = 0
    text_heights = []

    for line in lines:
        if not line:
            text_heights.append(font_size) # Use font size for empty line height
            continue

        w = _measure_width(draw, line, font, emoji_font)
        bbox = draw.textbbox((0, 0), line, font=font)
        h = bbox[3] - bbox[1]
        max_line_width = max(max_line_width, int(w))
        text_heights.append(h)
    
    # Box dimensions
    # We want the box to fit the text exactly + padding
    # Ensure min width for aesthetic reasons if text is short (at least 30% of target)
    box_width = max(max_line_width + (2 * padding_x), int(target_width * 0.3))
    
    # Total Text Height: sum(heights) + spacing * (n-1)
    if not text_heights:
         total_text_height = font_size
    else:
         total_text_height = sum(text_heights) + (len(text_heights) - 1) * line_spacing
         
    box_height = total_text_height + (2 * padding_y)
    
    # Create Final Image with Rounded Corners and Shadow
    # 1. Canvas for Shadow (larger than box)
    canvas_w = box_width + 40
    canvas_h = box_height + 40
    
    img = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 2. Draw Shadow (only for boxed styles)
    if draw_shadow and has_box:
        shadow_box = [
            (20 + shadow_offset[0], 20 + shadow_offset[1]),
            (20 + box_width + shadow_offset[0], 20 + box_height + shadow_offset[1])
        ]
        draw.rounded_rectangle(shadow_box, radius=cornerradius, fill=(0, 0, 0, 100))
        # 3. Blur Shadow
        img = img.filter(ImageFilter.GaussianBlur(5))

    # 4. Draw Box (sharper, on top of blurred shadow)
    draw_final = ImageDraw.Draw(img)

    if has_box:
        main_box = [
            (20, 20),
            (20 + box_width, 20 + box_height)
        ]
        draw_final.rounded_rectangle(main_box, radius=cornerradius, fill=box_fill)

    # 5. Draw Text
    current_y = 20 + padding_y - 2 # Minor visual adjustment
    for i, line in enumerate(lines):
        if not line:
            current_y += font_size + line_spacing
            continue

        line_w = _measure_width(draw_final, line, font, emoji_font)
        bbox = draw_final.textbbox((0, 0), line, font=font)
        line_h = text_heights[i] if i < len(text_heights) else bbox[3] - bbox[1]

        # Center X
        x = 20 + int(box_width - line_w) // 2

        # Draw text in the style's color (emoji runs use the emoji font)
        _draw_mixed(img, draw_final, (x, current_y), line, font, emoji_font,
                    fill=text_fill, outline=outline)

        current_y += line_h + line_spacing
        
    img.save(output_image_path)
    return output_image_path, canvas_w, canvas_h

def add_hook_to_video(video_path, text, output_path, position="top", font_scale=1.0, duration=None, style="classic",
                      category="", accent=None, quiet=()):
    """
    Overlays text hook onto video.
    position: 'top', 'center', 'bottom'
    font_scale: float multiplier (1.0 = default)
    style: hook look (see HOOK_STYLES)
    category, accent, quiet: the "docline" style only: the topic shown above
    the rule, the word(s) of the hook drawn in yellow (docline_accent), and
    the [(from, to)] seconds of the B-roll cards the eyebrow steps aside for.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video {video_path} not found")

    # 1. Probe video width to scale text properly
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', video_path]
        res = subprocess.check_output(cmd, timeout=60).decode().strip()
        # Takes first stream if multiple
        dims = res.split('\n')[0].split('x')
        video_width = int(dims[0])
        video_height = int(dims[1])
    except Exception as e:
        print(f"⚠️ FFprobe failed: {e}. Assuming 1080x1920")
        video_width = 1080
        video_height = 1920
        
    # 2. Generate Image
    # Box check: Don't let it be wider than 90% of screen
    target_box_width = int(video_width * 0.9)
    
    # Unique per invocation so parallel jobs can't overwrite each other's overlay.
    # The uuid alone guarantees that; the source name rides along only as a
    # debugging hint, so it is trimmed by BYTES (filesystems cap at 255 bytes,
    # and one Bengali or Arabic character costs three). Embedding it untrimmed
    # raised OSError 36 and killed the endpoint in prod on 26-jul-2026.
    stem = os.path.splitext(os.path.basename(video_path))[0]
    hook_filename = (f"temp_hook_{uuid.uuid4().hex[:8]}_"
                     f"{_truncate_bytes(stem, 80)}.png")
    
    try:
        if style == "bold":
            return _add_bold_hook(video_path, text, output_path, hook_filename, video_width, video_height,
                                  position, font_scale, duration)
        if style == "docline":
            return _add_docline_hook(video_path, text, output_path, video_width, video_height, duration,
                                     category=category, accent=accent, font_scale=font_scale, quiet=quiet)
        img_path, box_w, box_h = create_hook_image(text, target_box_width, hook_filename, font_scale=font_scale, style=style)
        
        # 3. Calculate Overlay Position
        overlay_x = (video_width - box_w) // 2
        
        if position == "center":
            overlay_y = (video_height - box_h) // 2
        elif position == "bottom":
             # Bottom 20% mark (approx)
             overlay_y = int(video_height * 0.70)
        else:
             # Top 20% mark
             overlay_y = int(video_height * 0.20)
        
        # 4. FFmpeg Command
        print(f"🎬 Overlaying hook: '{text}' at {overlay_x},{overlay_y}")
        
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', img_path,
            '-filter_complex', f"[0:v][1:v]overlay={overlay_x}:{overlay_y}"
                + (f":enable='between(t,0,{float(duration)})'" if duration else ""),
            '-c:a', 'copy',
            # The captions re-encode the hooked file: near-lossless under the HQ chain.
            *layer_encode_args(video_encode_args(QUALITY)),
            *METADATA_SCRUB,
            '-movflags', '+faststart',
            output_path
        ]
        
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
        print(f"✅ Hook added to {output_path}")
        return True

    except subprocess.TimeoutExpired:
        print("❌ FFmpeg hook overlay timed out after 1800s.")
        raise RuntimeError("FFmpeg hook overlay timed out after 1800s.")
    except subprocess.CalledProcessError as e:
        print(f"❌ FFmpeg Error: {e.stderr.decode() if e.stderr else 'Unknown'}")
        raise e
    except Exception as e:
        print(f"❌ Hook Gen Error: {e}")
        raise e
    finally:
        # Cleanup temp image
        if os.path.exists(hook_filename):
            os.remove(hook_filename)


def _add_bold_hook(video_path, text, output_path, png_path, video_width, video_height,
                   position, font_scale, duration):
    """Burn the "bold" headline: fades in while sliding down ~2% in 0.2 s,
    fades out over the last 0.3 s of ``duration`` (or stays on the whole
    clip when no duration). Top sits at 12% of the height — above the face
    in a podcast framing, far from the captions at ~65%."""
    _, box_w, box_h = create_bold_hook_image(text, video_width, png_path, font_scale=font_scale)
    x = (video_width - box_w) // 2
    if position == "center":
        y = (video_height - box_h) // 2
    elif position == "bottom":
        y = int(video_height * 0.70)
    else:
        y = int(video_height * 0.12)
    slide = max(8, int(video_height * 0.02))
    chain = "[1:v]format=rgba,fade=t=in:st=0:d=0.2:alpha=1"
    inputs = ["-i", video_path]
    if duration:
        dur = max(0.8, float(duration))
        chain += f",fade=t=out:st={dur - 0.3:.2f}:d=0.3:alpha=1"
        inputs += ["-loop", "1", "-framerate", "30", "-t", f"{dur:.2f}", "-i", png_path]
        tail = "eof_action=pass"
    else:
        inputs += ["-loop", "1", "-framerate", "30", "-i", png_path]
        tail = "shortest=1"
    graph = (f"{chain}[h];[0:v][h]overlay=x={x}:y='{y}-{slide}*max(0,1-t/0.2)':{tail}[v]")
    print(f"🎬 Overlaying bold hook: '{text}' at {x},{y}")
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
           "-c:a", "copy", *layer_encode_args(video_encode_args(QUALITY)), *METADATA_SCRUB,
           "-movflags", "+faststart", output_path]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
    finally:
        if os.path.exists(png_path):
            os.remove(png_path)
    print(f"✅ Hook added to {output_path}")
    return True


# ---------------------------------------------------------------------------
# "docline": the documentary line (H3 of the hook study, 2-oct-2026).
#
# A small yellow eyebrow (the clip's topic), a short white rule that draws
# itself, then the hook in sentence case with its payoff word in yellow, all
# left-aligned under a soft dark veil that tames the studio's neon sign. At
# ``seconds`` the title fades out; the eyebrow, the rule and a lighter veil
# stay for the whole clip (the channel's mark, same place on every clip).
# Everything is drawn by PIL as a PNG sequence (the only clean way to animate
# letter-spacing with ffmpeg), then a static PNG for the rest of the clip.
# ---------------------------------------------------------------------------

import shutil
import tempfile

MONT_FONT_CANDIDATES = [
    "/usr/local/share/fonts/openshorts/Montserrat-ExtraBold.ttf",
    os.path.join(FONT_DIR, "Montserrat-ExtraBold.ttf"),
]

DOCLINE = {
    # Where it sits, as fractions of the frame: the top of the eyebrow, the
    # left margin, the right margin. The Shorts icons live above 10 %.
    "top": 0.11, "left": 0.06, "right": 0.10,
    # Sizes in px on a 1080-wide frame, scaled with the width.
    "eyebrow_px": 26, "eyebrow_tracking": 0.22, "eyebrow_gap": 10,
    "rule_px": 4, "rule_width": 0.30, "rule_gap": 18,
    # title_nice_scale: how far the title may shrink to break its two lines
    # on a clause or a phrase; title_min_scale: how far to fit in two lines.
    "title_px": 56, "title_leading": 1.22, "title_lines": 2,
    "title_nice_scale": 0.85, "title_min_scale": 0.7,
    "title_tracking_from": 0.25, "title_tracking_to": 0.01,
    # The veil: black at veil_alpha from the top edge down to the middle of
    # the title, easing out to nothing veil_tail (of the frame's height)
    # under it — the yellow neon sign of the JRE studio sits right behind
    # the title (2-oct-2026: a straight 55 % -> 0 gradient left ~25 % there).
    # rest_*: the lighter veil that stays under the eyebrow and the rule.
    "veil_alpha": 0.60, "veil_tail": 0.10, "rest_alpha": 0.30, "rest_tail": 0.05,
    # The timeline in seconds, (start, length) of each movement, and how long
    # the title takes to go.
    "eyebrow": (0.0, 0.15), "rule": (0.10, 0.35), "title": (0.25, 0.40), "out": 0.20,
    # A B-roll card above the head (broll.TOP_BAND, 9-30 % of the height)
    # would land on the eyebrow: it fades out quiet_lead s before the card,
    # over quiet_out s, and comes back over quiet_in s once the card is gone.
    "quiet_lead": 0.10, "quiet_out": 0.25, "quiet_in": 0.30,
    # The eyebrow (the topic), the rule and a light veil stayed for the whole
    # clip (H3); since 2-oct-2026 the channel wants them to leave with the
    # title. True brings the resting eyebrow back (the quiet windows apply).
    "keep_eyebrow": False,
    # Without it, the eyebrow leaves the way it came, a little after the
    # title (which goes at ``seconds`` over ``out``): the rule retracts to
    # the left, then the eyebrow and the veil fade — (start after
    # ``seconds``, length) in seconds, the entrance's lengths.
    "rule_out": (0.15, 0.35), "eyebrow_out": (0.40, 0.15),
    "fps": 30,
}
DOCLINE_ACCENT = BOLD_ACCENT   # the captions' yellow, one word per hook
DOCLINE_SECONDS = 3.3          # when the title leaves (the eyebrow stays)
# A word ending a clause: the title prefers to break its two lines there.
_SENSE_BREAK = re.compile(r"[,.;:!?…”’\"')]$")
# Words a phrase starts with (the second line may open on one) and words a
# line never ends on ("The universe and a" / "brain cell..." is the classic
# orphan; "The universe" / "and a brain cell..." is a phrase break).
_BREAK_BEFORE = {"a", "an", "the", "and", "or", "but", "so", "because", "if", "when", "while",
                 "that", "which", "who", "of", "to", "in", "on", "at", "for", "with", "from",
                 "into", "about", "by", "like", "than", "as", "after", "before", "without", "until"}
_NO_END = _BREAK_BEFORE | {"my", "your", "his", "her", "its", "our", "their", "very", "just", "not", "no"}


def _mont_font(size):
    """Montserrat ExtraBold (the captions' face) at ``size`` px; Anton when
    the font file is missing, so a hook is never lost to a font."""
    path = next((p for p in MONT_FONT_CANDIDATES if os.path.exists(p)), None)
    return ImageFont.truetype(path or _bold_font_path(), max(8, int(size)))


def _tracked_width(font, text, tracking):
    """Width of ``text`` drawn glyph by glyph with ``tracking`` px added
    after each glyph but the last."""
    if not text:
        return 0.0
    return sum(font.getlength(ch) for ch in text) + tracking * (len(text) - 1)


def _draw_tracked(draw, xy, text, font, fill, tracking):
    """Draw ``text`` glyph by glyph (letter-spacing is not a PIL feature).
    Returns the x after the last glyph."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + tracking
    return x


def _bare_word(word):
    return re.sub(r"[^\w'’]", "", word).lower()


def docline_accent(text, accent=None):
    """Indexes of the words drawn in yellow: the brain's ``accent`` (one or
    two words copied from the hook) when they are in the text, else the
    first number, else the last long non-filler word. Never two choices."""
    words = (text or "").split()
    bare = [_bare_word(w) for w in words]
    target = [t for t in (_bare_word(w) for w in str(accent or "").split()) if t]
    if target:
        n = len(target)
        for i in range(len(bare) - n + 1):
            if bare[i:i + n] == target:
                return set(range(i, i + n))
    for i, w in enumerate(bare):
        if re.search(r"\d", w):
            return {i}
    long_ones = [i for i, w in enumerate(bare) if len(w) >= 4 and w.upper() not in _BOLD_STOP]
    return {long_ones[-1]} if long_ones else set()


def docline_break(words, width, max_w):
    """The best place to break ``words`` into two lines that both fit
    ``max_w`` (``width``: words -> px). Returns (tier, k), line 2 starting
    at words[k], or None when no split fits. Tiers, best first:
    1 after a clause ("He asked “am I dead?”" / "39 times."),
    2 before a phrase ("The universe" / "and a brain cell..."),
    3 anywhere a line does not end on "a", "and", "of"...,
    4 anywhere. Tiers 1 to 3 keep some balance (the short line at least 30 %
    of the long one); within a tier the most balanced split wins."""
    best = None
    for k in range(1, len(words)):
        a, b = width(words[:k]), width(words[k:])
        if max(a, b) > max_w:
            continue
        balanced = min(a, b) / max(a, b, 1.0) >= 0.3
        last, first = _bare_word(words[k - 1]), _bare_word(words[k])
        if balanced and _SENSE_BREAK.search(words[k - 1]):
            tier = 1
        elif balanced and last not in _NO_END and first in _BREAK_BEFORE:
            tier = 2
        elif balanced and last not in _NO_END:
            tier = 3
        else:
            tier = 4
        key = (tier, max(a, b))
        if best is None or key < best[0]:
            best = (key, k)
    return (best[0][0], best[1]) if best else None


def docline_layout(text, video_width, cfg=None):
    """Lay the title out: one line when it fits, else two lines broken where
    they read best (docline_break). The size is title_px; it may shrink to
    title_nice_scale when that buys a single line or a clause / phrase break
    the full size does not have, and down to title_min_scale to fit two
    lines at all (the brain keeps hooks short; words are never dropped: past
    the minimum the lines just wrap). Returns (lines, font, tracking_px)."""
    c = {**DOCLINE, **(cfg or {})}
    words = re.sub(r"\s+", " ", _EMOJI_RE.sub("", text or "")).strip().split() or [""]
    scale = video_width / 1080.0
    max_w = video_width * (1 - c["left"] - c["right"])
    base = int(round(c["title_px"] * scale))
    nice = int(base * c["title_nice_scale"])
    smallest = int(base * c["title_min_scale"])

    def at(size):
        """(tier, lines, font, tracking) at ``size``; tier 0 = one line;
        None when the title needs more than two lines."""
        font = _mont_font(size)
        tracking = size * c["title_tracking_to"]

        def width(ws):
            return _tracked_width(font, " ".join(ws), tracking)
        if width(words) <= max_w or c["title_lines"] < 2:
            return 0, [words], font, tracking
        split = docline_break(words, width, max_w)
        if split is None:
            return None
        tier, k = split
        return tier, [words[:k], words[k:]], font, tracking

    first = None
    size = base
    while size >= smallest:
        laid = at(size)
        if laid:
            if laid[0] <= 2:
                return laid[1:]
            first = first or laid
            if size <= nice:
                break
        size -= 2
    if first:
        return first[1:]
    # Too long even at the smallest size: wrap greedily, nothing dropped.
    font = _mont_font(smallest)
    tracking = smallest * c["title_tracking_to"]
    lines, line = [], []
    for w in words:
        if line and _tracked_width(font, " ".join(line + [w]), tracking) > max_w:
            lines.append(line)
            line = [w]
        else:
            line.append(w)
    return lines + [line] if line else lines, font, tracking


def _ramp(t, start, length):
    """0 before ``start``, 1 after ``start + length``, linear between."""
    if length <= 0:
        return 1.0 if t >= start else 0.0
    return min(1.0, max(0.0, (t - start) / length))


def _ease_out(f):
    return 1 - (1 - f) ** 3


def _scale_alpha(layer, k):
    """A copy of the RGBA ``layer`` with its alpha multiplied by ``k``."""
    if k >= 1.0:
        return layer.copy()
    r, g, b, a = layer.split()
    return Image.merge("RGBA", (r, g, b, a.point(lambda v: int(v * k))))


def _veil_alpha(width, canvas_h, full_to, gone_at, alpha):
    """Alpha (mode L) of a black veil: ``alpha`` from the top edge down to
    ``full_to``, easing out (smoothstep) to nothing at ``gone_at``."""
    rows = []
    for y in range(canvas_h):
        if y <= full_to:
            f = 1.0
        elif y >= gone_at:
            f = 0.0
        else:
            u = (y - full_to) / float(gone_at - full_to)
            f = 1.0 - u * u * (3 - 2 * u)
        rows.append(int(round(255 * alpha * f)))
    column = Image.new("L", (1, canvas_h))
    column.putdata(rows)
    return column.resize((width, canvas_h), Image.NEAREST)


def create_docline_frames(text, category, video_width, video_height, out_dir,
                          accent=None, seconds=DOCLINE_SECONDS, cfg=None, quiet=(), total=None):
    """Draw the documentary line as a timeline of PNG states in ``out_dir``:
    the entrance, the hold and the title's exit (0 to seconds + out), then
    the resting eyebrow and rule to the end of the clip (``total`` s, plus a
    second), fading out for each ``quiet`` window [(from, to)] — the B-roll
    cards drawn above the head, right where the eyebrow sits — and back in
    after it. Every state is the top band of the picture (video_width x band
    height) to overlay at 0,0, written once however long it lasts.

    Returns {"segments": [[png, seconds], ...], "rest", "height",
    "title_end", "lines", "accent"}."""
    c = {**DOCLINE, **(cfg or {})}
    fps = int(c["fps"])
    scale = video_width / 1080.0
    text = re.sub(r"\s+", " ", _EMOJI_RE.sub("", text or "")).strip()
    category = re.sub(r"\s+", " ", _EMOJI_RE.sub("", category or "")).strip().upper()
    lines, font, _tracking_to = docline_layout(text, video_width, c)
    words = [w for line in lines for w in line]
    accents = docline_accent(" ".join(words), accent)

    left = int(video_width * c["left"])
    y = int(video_height * c["top"])
    eyebrow_font = _mont_font(c["eyebrow_px"] * scale)
    eyebrow_h = sum(eyebrow_font.getmetrics())
    eyebrow_tracking = eyebrow_font.size * c["eyebrow_tracking"]
    rule_y = y + (eyebrow_h + int(c["eyebrow_gap"] * scale) if category else 0)
    rule_h = max(2, int(round(c["rule_px"] * scale)))
    rule_w = int(video_width * c["rule_width"])
    title_y = rule_y + rule_h + int(c["rule_gap"] * scale)
    pitch = int(round(font.size * c["title_leading"]))
    ascent, descent = font.getmetrics()
    bottom = title_y + (len(lines) - 1) * pitch + ascent + descent
    veil_gone = bottom + int(video_height * c["veil_tail"])
    canvas_h = veil_gone + 1
    size = (video_width, canvas_h)

    # The veil behind the title, and the lighter one that stays.
    veil_title = _veil_alpha(video_width, canvas_h, (title_y + bottom) // 2, veil_gone, c["veil_alpha"])
    rule_bottom = rule_y + rule_h
    veil_rest = _veil_alpha(video_width, canvas_h, rule_bottom,
                            rule_bottom + int(video_height * c["rest_tail"]), c["rest_alpha"])
    black = Image.new("L", size, 0)

    eyebrow = Image.new("RGBA", size, (0, 0, 0, 0))
    if category:
        _draw_tracked(ImageDraw.Draw(eyebrow), (left, y), category, eyebrow_font,
                      DOCLINE_ACCENT, eyebrow_tracking)

    title_cache = {}

    def title_layer(f):
        """The title at progress ``f`` of its entrance: the tracking closes
        from title_tracking_from to title_tracking_to (eased); the alpha is
        the caller's."""
        key = round(f, 3)
        if key in title_cache:
            return title_cache[key]
        tr = font.size * (c["title_tracking_from"]
                          + (c["title_tracking_to"] - c["title_tracking_from"]) * _ease_out(f))
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        # A soft shadow under the letters (the look has no outline).
        shadow = Image.new("RGBA", size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        idx = 0
        for li, line in enumerate(lines):
            x, ly = left, title_y + li * pitch
            for wi, word in enumerate(line):
                fill = DOCLINE_ACCENT if idx in accents else (255, 255, 255)
                _draw_tracked(sd, (x, ly + int(3 * scale)), word, font, (0, 0, 0, 230), tr)
                x = _draw_tracked(d, (x, ly), word, font, fill, tr)
                if wi < len(line) - 1:
                    x += font.getlength(" ") + tr
                idx += 1
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, int(5 * scale))))
        shadow.alpha_composite(layer)
        title_cache[key] = shadow
        return shadow

    def compose(e, r, ti, g, ro=0.0, eo=0.0):
        """One frame: e = eyebrow and veil in, r = rule drawn, ti = title in,
        g = title out (its veil turning into the resting one), then, without
        keep_eyebrow, the entrance played backwards a little after the title:
        ro = rule retracting to the left, eo = eyebrow and veil fading."""
        alpha = Image.blend(veil_title, veil_rest, g) if g > 0 else veil_title
        stay = e * (1.0 - eo)                               # what is left of the eyebrow and the veil
        if stay < 1:
            alpha = alpha.point(lambda v: int(v * stay))
        frame = Image.merge("RGBA", (black, black, black, alpha))
        if category and stay > 0:
            frame.alpha_composite(_scale_alpha(eyebrow, stay))
        drawn = _ease_out(r) if ro <= 0 else _ease_out(1.0 - ro)   # the draw, mirrored
        if r > 0 and drawn > 0:
            w = max(1, int(rule_w * drawn))
            ImageDraw.Draw(frame).rectangle([left, rule_y, left + w, rule_y + rule_h - 1],
                                            fill=(255, 255, 255, int(255 * e)))
        if ti > 0 and g < 1:
            frame.alpha_composite(_scale_alpha(title_layer(ti), (ti ** 2) * (1 - g)))
        return frame

    os.makedirs(out_dir, exist_ok=True)
    pngs = {}
    segments = []

    def png_for(key, draw):
        """The PNG of state ``key``, drawn (by ``draw()``) the first time only."""
        if key not in pngs:
            path = os.path.join(out_dir, f"s_{len(pngs):04d}.png")
            draw().save(path)
            pngs[key] = path
        return pngs[key]

    def push(path, dur):
        if segments and segments[-1][0] == path:
            segments[-1][1] += dur
        else:
            segments.append([path, dur])

    # The entrance, the hold and the title's exit, frame by frame.
    step = 1.0 / fps
    keep = bool(c["keep_eyebrow"])
    secs = float(seconds)
    exit_len = c["out"] if keep else max(c["out"], *(a + b for a, b in (c["rule_out"], c["eyebrow_out"])))
    count = int(round((secs + exit_len) * fps)) + 1
    for k in range(count):
        t = k * step
        state = (round(_ramp(t, *c["eyebrow"]), 3), round(_ramp(t, *c["rule"]), 3),
                 round(_ramp(t, *c["title"]), 3), round(_ramp(t, secs, c["out"]), 3),
                 0.0 if keep else round(_ramp(t, secs + c["rule_out"][0], c["rule_out"][1]), 3),
                 0.0 if keep else round(_ramp(t, secs + c["eyebrow_out"][0], c["eyebrow_out"][1]), 3))
        push(png_for(state, lambda s=state: compose(*s)), step)
    title_end = count * step

    # Then what stays (the kept eyebrow and rule, out of the way of every card; else nothing).
    done = 0.0 if keep else 1.0
    rest_img = compose(1.0, 1.0, 1.0, 1.0, done, done)
    rest = png_for((1.0, 1.0, 1.0, 1.0, done, done), lambda: rest_img)   # the exit's last state, already drawn

    def rest_at(k):
        """The resting layer at opacity ``k`` (0-1)."""
        k = round(max(0.0, min(1.0, k)), 2)
        return rest if k >= 1.0 else png_for(("rest", k), lambda: _scale_alpha(rest_img, k))

    end = (float(total) if total else title_end + 3600.0) + 1.0   # never shorter than the clip
    spans = []                                                     # [fade-out start, fade-in start]
    for a, b in sorted((float(a), float(b)) for a, b in (quiet or ()) if float(b) > float(a)):
        s = max(title_end, a - c["quiet_lead"])
        if b <= s or s >= end:
            continue
        if spans and s <= spans[-1][1] + c["quiet_in"]:
            spans[-1][1] = max(spans[-1][1], b)                    # two cards close together: stay hidden
        else:
            spans.append([s, b])
    t = title_end
    for s, b in spans:
        if s > t:
            push(rest, s - t)
            t = s
        n = max(1, int(round(c["quiet_out"] * fps)))
        for j in range(1, n + 1):
            push(rest_at(1 - j / n), step)
        t += n * step
        if b > t:
            push(rest_at(0.0), b - t)
            t = b
        n = max(1, int(round(c["quiet_in"] * fps)))
        for j in range(1, n + 1):
            push(rest_at(j / n), step)
        t += n * step
    if end > t:
        push(rest, end - t)
    return {"segments": segments, "rest": rest, "height": canvas_h, "title_end": title_end,
            "lines": [" ".join(l) for l in lines], "accent": sorted(words[i] for i in accents)}


def docline_quiet(broll_items):
    """The [(from, to)] seconds of the B-roll cards drawn above the head
    (broll items of layout "card"): the eyebrow steps aside for them."""
    out = []
    for it in broll_items or []:
        if not isinstance(it, dict) or it.get("layout") != "card":
            continue
        try:
            t = float(it["t"])
            out.append((t, t + float(it.get("dur") or 0.0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def docline_frame_at(made, t):
    """The PNG of ``made`` (create_docline_frames) on screen at ``t`` s."""
    acc = 0.0
    for path, dur in made["segments"]:
        if t < acc + dur - 1e-9:
            return path
        acc += dur
    return made["segments"][-1][0]


def write_docline_concat(made, path):
    """The timeline as an ffconcat script next to its PNGs (relative names).
    The last file is listed twice: the concat demuxer ignores the duration of
    the last entry otherwise."""
    rows = ["ffconcat version 1.0"]
    for png, dur in made["segments"]:
        rows += [f"file '{os.path.basename(png)}'", f"duration {dur:.6f}"]
    rows.append(f"file '{os.path.basename(made['segments'][-1][0])}'")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    return path


def docline_graph():
    """The hook layer (input 1, the concat timeline, a second longer than the
    clip) over the video; the output stops with the picture."""
    return "[1:v]format=rgba[h];[0:v][h]overlay=0:0:shortest=1[v]"


def _video_seconds(video_path):
    try:
        out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                       "-of", "csv=p=0", video_path], timeout=60).decode().strip()
        return float(out.splitlines()[0])
    except Exception:
        return None


def _add_docline_hook(video_path, text, output_path, video_width, video_height, duration,
                      category="", accent=None, font_scale=1.0, quiet=()):
    """Burn the documentary line (see DOCLINE). ``duration``: when the title
    leaves; the eyebrow and the rule stay to the end of the clip, except
    during the ``quiet`` windows (the B-roll cards above the head).
    ``font_scale``: the editor's S / M / L, on the title only."""
    seconds = max(1.0, float(duration or DOCLINE_SECONDS))
    cfg = {"title_px": DOCLINE["title_px"] * float(font_scale or 1.0)}
    work = tempfile.mkdtemp(prefix="docline_", dir=os.path.dirname(os.path.abspath(output_path)))
    try:
        made = create_docline_frames(text, category, video_width, video_height, work, accent=accent,
                                     seconds=seconds, cfg=cfg, quiet=quiet, total=_video_seconds(video_path))
        concat = write_docline_concat(made, os.path.join(work, "timeline.ffconcat"))
        print(f"🎬 Overlaying documentary line: {made['lines']} (accent {made['accent']}, "
              f"topic '{category or '-'}', title leaves at {seconds:g}s, "
              f"{len(quiet or ())} card(s) to step aside for)")
        cmd = ["ffmpeg", "-y", "-i", video_path, "-f", "concat", "-safe", "0", "-i", concat,
               "-filter_complex", docline_graph(), "-map", "[v]", "-map", "0:a?",
               "-c:a", "copy", *layer_encode_args(video_encode_args(QUALITY)), *METADATA_SCRUB,
               "-movflags", "+faststart", output_path]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"✅ Hook added to {output_path}")
    return True
