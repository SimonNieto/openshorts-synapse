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
  - "auto":   Gemini first, free photos for whatever it could not make.
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

STYLES = {
    "photo": "Realistic documentary photograph, natural light, shallow depth of field, rich but true colours.",
    "neon": ("Clean scientific illustration on a deep navy background, glowing cyan and violet neon lines "
             "and soft light, minimal and elegant, like a science documentary graphic."),
    "drawing": "Simple flat 2D illustration, bold clean outlines, limited warm palette, friendly and clear.",
}
COMMON_RULES = ("Vertical 9:16 composition, one clear subject centred. No text, no letters, no numbers, "
                "no logos, no watermark. Never depict a real, identifiable person.")
IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL") or "gemini-3.1-flash-image"
TEXT_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
OPENVERSE = "https://api.openverse.org/v1/images/"
# Wikimedia's user-agent policy: name the tool and a way to reach it.
UA = {"User-Agent": "OpenShorts-selfhost/1.0 (https://openshorts.app; b-roll images) httpx"}
SEG_DUR = 1.6
HEAD_FREE = 4.3   # the hook's seconds stay on the speaker
TAIL_FREE = 2.0
MIN_GAP = 5.0

PLAN_PROMPT = """You are the editor of a short-form podcast clip. Pick up to {n} moments where a B-roll image
(1.6 s, full screen, while the voice continues) would make the clip clearer: when the speaker names
something CONCRETE and visual — an object, a plant, a substance, an organ, a place, an animal, a tool,
a group of people (soldiers, surgeons), an event. Never an abstract idea, never "he/she/they", never a
named real person, never a brand. Only moments between {lo:.1f}s and {hi:.1f}s{avoid}.

For each moment give:
- "anchor": the exact 1-3 words as spoken in the transcript (verbatim, same spelling);
- "time": the second the anchor is spoken (from the markers);
- "search_query": 1-3 plain English words to find a real photo of it on Wikimedia Commons: common nouns only,
  never a brand or product name, never a real person (e.g. "kratom leaves", "brain scan", "hospital corridor",
  "breakfast pastry" rather than a brand);
- "image_prompt": one English sentence describing the image to generate (subject, setting, light).

TRANSCRIPT (seconds from the clip start):
{text}

Return JSON: {{"moments": [{{"anchor": "...", "time": 12.3, "search_query": "...", "image_prompt": "..."}}]}}"""


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


def _space(moments, n):
    """At most ``n``, 5 s apart, never the same thing twice."""
    kept = []
    for m in sorted(moments, key=lambda m: -m.get("score", 1.0)):
        if all(abs(m["t"] - k["t"]) >= MIN_GAP and _stem(m["query"]) != _stem(k["query"]) for k in kept):
            kept.append(m)
        if len(kept) == n:
            break
    return sorted(kept, key=lambda m: m["t"])


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


def plan_with_gemini(clip, words, n, avoid, api_key):
    from google import genai
    from google.genai import types
    duration = words[-1]["end"]
    avoid_txt = (", and not within 1.2 s of " + ", ".join(f"{a:.1f}s" for a in avoid)) if avoid else ""
    prompt = PLAN_PROMPT.format(n=n + 2, lo=HEAD_FREE, hi=duration - TAIL_FREE - SEG_DUR, avoid=avoid_txt,
                                text=_numbered_text(words)[:6000])
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
    moments = []
    for m in data.get("moments") or []:
        try:
            near = float(m.get("time", 0))
        except (TypeError, ValueError):
            continue
        i = _find_anchor(words, m.get("anchor"), near)
        if i is None:
            continue
        t = max(0.0, words[i]["start"] - 0.08)
        if not _allowed(t, duration, avoid):
            continue
        moments.append({"t": t, "anchor": " ".join(w["text"] for w in words[i:i + len(_tokens(m.get("anchor")))]),
                        "query": str(m.get("search_query") or m.get("anchor"))[:60],
                        "prompt": str(m.get("image_prompt") or m.get("anchor"))[:400], "score": 1.0})
    return _space(moments, n)


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

def gemini_image(prompt, style, api_key, out_path):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)
    full = f"{prompt}\n\nStyle: {STYLES.get(style, STYLES['photo'])}\n{COMMON_RULES}"
    r = client.models.generate_content(
        model=IMAGE_MODEL, contents=[full],
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"],
                                           image_config=types.ImageConfig(aspect_ratio="9:16", image_size="1K")))
    for part in (r.parts or []):
        if part.inline_data is not None and part.inline_data.data:
            Image.open(io.BytesIO(part.inline_data.data)).convert("RGB").save(out_path, quality=92)
            return out_path
    cand = (r.candidates or [None])[0]
    raise RuntimeError(f"no image (finish_reason={getattr(cand, 'finish_reason', None)})")


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


def _looks_good(path):
    """A photo worth showing: sharp, not too dark / washed out, sane shape."""
    try:
        img = Image.open(path).convert("L")
    except Exception:
        return False
    w, h = img.size
    if w < 900 or not 0.5 <= h / w <= 2.0:
        return False
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


def free_photo(query, out_path, used=None):
    """openverse_image over the query's variants, most specific first."""
    last = None
    for v in query_variants(query):
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
    want = set(_stem(query).split())
    used = used if used is not None else set()

    def relevance(x):
        words = set(_stem(" ".join([x.get("title") or ""] + [t.get("name", "") for t in (x.get("tags") or [])])).split())
        title = set(_stem(x.get("title") or "").split())
        extra = len(title - want)
        return (len(want & words), -extra)

    with httpx.Client(timeout=20, headers=UA, follow_redirects=True) as http:
        r = http.get(OPENVERSE, params={"q": query, "license": "cc0,pdm,by", "page_size": 20,
                                        "mature": "false", "extension": "jpg,png",
                                        # Wikimedia Commons only: its licences are reviewed; Flickr's
                                        # are whatever the uploader claimed (a Peanuts strip "CC BY").
                                        "source": "wikimedia"})
        r.raise_for_status()
        results = [x for x in r.json().get("results", [])
                   if (x.get("width") or 0) >= 1000 and (x.get("height") or 0) >= 650 and x.get("url") not in used
                   and 0.5 <= (x.get("height") or 1) / (x.get("width") or 1) <= 2.0
                   and not _UGLY_TITLE.search(x.get("title") or "")
                   and relevance(x)[0] >= max(1, (len(want) + 1) // 2)]
        results.sort(key=relevance, reverse=True)
        for x in results[:6]:
            try:
                img = None
                for attempt in range(3):
                    img = http.get(_wikimedia_thumb(x["url"]) if (x.get("width") or 0) > 1280 else x["url"],
                                   timeout=30)
                    if img.status_code != 429:
                        break
                    time.sleep(2 + 3 * attempt)
                img.raise_for_status()
                Image.open(io.BytesIO(img.content)).convert("RGB").save(out_path, quality=92)
            except Exception:
                continue
            used.add(x.get("url"))
            if not _looks_good(out_path):
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


def _card_frames(src, folder, fps, dur, W, H):
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
    rim = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    if edge:
        ImageDraw.Draw(rim).rounded_rectangle((0, 0, cw - 1, ch - 1), radius, outline=(255, 255, 255, 225),
                                              width=edge)
    shade = Image.new("RGBA", (cvw, cvh), (0, 0, 0, 0))
    if shadow:
        ImageDraw.Draw(shade).rounded_rectangle((pad, pad + shadow // 2, pad + cw, pad + ch + shadow // 2),
                                                radius, fill=(0, 0, 0, 175))
        shade = shade.filter(ImageFilter.GaussianBlur(shadow * 0.6))
    n = max(2, int(round(dur * fps)))
    for f in range(n):
        t = f / fps
        zoom = 1.0 + (zmax - 1.0) * f / (n - 1)          # 1.00 -> 1.08
        vw, vh = cw * zmax / zoom, ch * zmax / zoom      # view into ``big``
        x0, y0 = (big.width - vw) / 2, (big.height - vh) / 2
        photo = big.crop((int(x0), int(y0), int(x0 + vw), int(y0 + vh))).resize((cw, ch), Image.BILINEAR)
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        card.paste(photo, (0, 0), mask)
        card.alpha_composite(rim)
        frame = shade.copy()
        frame.alpha_composite(card, (pad, pad))
        pin, pout = _ease(t / 0.15), min(1.0, (dur - t) / 0.12)
        scale = 0.9 + 0.1 * pin
        if scale < 0.999:
            small = frame.resize((max(1, int(cvw * scale)), max(1, int(cvh * scale))), Image.BILINEAR)
            frame = Image.new("RGBA", (cvw, cvh), (0, 0, 0, 0))
            frame.alpha_composite(small, ((cvw - small.width) // 2, (cvh - small.height) // 2))
        alpha = min(pin, pout)
        if alpha < 0.999:
            frame.putalpha(frame.getchannel("A").point(lambda v, a=alpha: int(v * a)))
        frame.save(os.path.join(folder, f"c{f:03d}.png"), compress_level=1)
    x = (W - cvw) // 2
    y = (H - cvh) // 2 if full else max(int(H * 0.1), int(H * 0.40 - cvh / 2))
    return os.path.join(folder, "c%03d.png"), x, y, full


def add_broll(clip_path, out_path, clip, transcript, start, end, cfg, api_key=None):
    """Cut 2-4 images into ``clip_path``. Returns a report dict
    ({items, credits, planner, sources}) or None when nothing was added."""
    import viral_fx
    words = viral_fx.clip_words(transcript, start, end)
    if len(words) < 10:
        return None
    n = max(1, min(4, int(cfg.get("max") or 3)))
    style = cfg.get("style") if cfg.get("style") in STYLES else "photo"
    source = cfg.get("source") if cfg.get("source") in ("auto", "gemini", "free") else "auto"
    avoid = [float(clip["punchline_time"])] if clip.get("punchline_time") is not None else []
    planner = "local"
    moments = []
    if api_key:
        try:
            moments = plan_with_gemini(clip, words, n, avoid, api_key)
            planner = "gemini"
        except Exception as e:
            print(f"   ⚠️ B-roll planning via Gemini failed ({e}) — local pick instead.")
    if not moments:
        # The local pick only knows words, not what they mean ("needle" ->
        # the Space Needle): no B-roll beats a wrong one.
        print("   ℹ️ B-roll skipped: moments need the Gemini planner (key missing or call failed).")
        return None
    info = viral_fx._probe(clip_path)
    w, h, fps = info["w"], info["h"], int(round(info.get("fps") or 30))
    tmp = tempfile.mkdtemp(prefix="broll_")
    items, credits, sources, used_urls = [], [], [], set()
    gemini_ok = source in ("auto", "gemini") and bool(api_key)
    try:
        for k, m in enumerate(moments):
            raw = os.path.join(tmp, f"raw_{k}.jpg")
            got, credit, used = None, None, None
            if gemini_ok:
                try:
                    got, used = gemini_image(m["prompt"], style, api_key, raw), "gemini"
                except Exception as e:
                    print(f"   ⚠️ B-roll image via Gemini failed ({str(e)[:160]})"
                          f"{' — free photos for the rest.' if source == 'auto' else '.'}")
                    gemini_ok = False   # quota / billing: do not retry on every moment
            if got is None and source in ("auto", "free"):
                try:
                    got, credit = free_photo(m["query"], raw, used_urls)
                    used = "free"
                except Exception as e:
                    print(f"   ⚠️ No free photo for {m['query']!r} ({str(e)[:120]}).")
            if got is None:
                continue
            folder = os.path.join(tmp, f"card_{k}")
            os.makedirs(folder)
            pattern, x, y, full = _card_frames(got, folder, fps, SEG_DUR, w, h)
            items.append({"t": round(m["t"], 2), "dur": SEG_DUR, "anchor": m["anchor"], "query": m["query"],
                          "source": used, "layout": "full" if full else "card",
                          "_pattern": pattern, "_x": x, "_y": y})
            sources.append(used)
            if credit:
                credits.append(credit)
        if not items:
            print("   ℹ️ B-roll: no image good enough for this clip's moments — clip left without.")
            return None
        # Behind a card, the podcast keeps playing — blurred and dimmed, so
        # the photo reads as "in front of" the conversation.
        windows = "+".join(f"between(t,{it['t']:.3f},{it['t'] + it['dur']:.3f})" for it in items)
        graph = [f"[0:v]boxblur=22:2:enable='{windows}',"
                 f"eq=brightness=-0.10:saturation=0.8:enable='{windows}'[bg]"]
        inputs, cur = [], "[bg]"
        for k, it in enumerate(items):
            inputs += ["-itsoffset", f"{it['t']:.3f}", "-framerate", str(fps), "-i", it["_pattern"]]
            graph.append(f"{cur}[{k + 1}:v]overlay={it['_x']}:{it['_y']}:eof_action=pass:"
                         f"enable='between(t,{it['t']:.3f},{it['t'] + it['dur']:.3f})'[b{k}]")
            cur = f"[b{k}]"
        graph[-1] = graph[-1][:graph[-1].rfind("[")] + "[v]"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip_path, *inputs, "-filter_complex", ";".join(graph),
                        "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                        "-c:a", "copy", "-movflags", "+faststart", out_path], check=True)
        for it in items:
            for key in ("_pattern", "_x", "_y"):
                it.pop(key, None)
        return {"items": items, "credits": credits, "planner": planner, "sources": sources}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sources(api_key=None, style="photo"):
    """For the profile editor's "test" button: can Gemini make an image on
    this key, and do free photos come through? Never raises."""
    out = {"gemini": None, "free": None}
    tmp = tempfile.mkdtemp(prefix="broll_test_")
    try:
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
