"""B-roll « vidéo » (9-oct-2026, recette références) — short real footage from Pexels for the ACTIONS said in a clip.

OptimalHealth and Clip Storm cut, on the word, to 1-3 s of stock footage that shows the thing said literally: a tired man
rubbing his eyes on "disregulated", tap water running into a glass on "water", a patient on a hospital bed on "injured".
This module does that part; the generated pictures (broll_draw) keep the OBJECTS.

    moment = {"t": 12.4, "word": "drinking", "sentence": "...", "kind": "action" | "object", "query": "man drinking water"}

  1. spot(words, title)           one Claude call per clip: the concrete things said, action or object, a stock query;
  2. wants_video(moment)          an ACTION or a moving scene -> footage; an object -> the generated picture;
  3. search(query)                Pexels video search (cached on disk per query): vertical or croppable to 9:16, HD,
                                  3-15 s, the smallest file that fills 1080x1920;
  4. choose(moments, ...)         ONE Claude call per clip on the preview frames (small jpgs, never the video): the
                                  candidate that shows the thing literally, no famous person, nothing evoking a death or
                                  its means, no gore, no text or logo on screen — or none;
  5. download / cut               the chosen file once (cache: never downloaded twice), an excerpt of 1.5-3 s, 9:16,
                                  1080x1920, no sound, starting exactly on the word (a hard cut);
  6. apply(clip, placements, out) the excerpts laid full screen over the clip.

Entry point for the integration: videos_for_clip(moments, words, clip_end, tmp) -> placements, each with its credit
(author, page, licence). Everything behind plus.BROLL["video"] (off by default). The Pexels key is read from the
environment (PEXELS_API_KEY, .env) and only ever travels in the request header: never in a URL, a log or a file."""
import hashlib
import json
import os
import re
import subprocess

API = "https://api.pexels.com/videos/search"
LICENSE = "Pexels License — free to use, no attribution required (https://www.pexels.com/license/)"
FILE_HOST = "videos.pexels.com"
PREVIEW_HOST = "images.pexels.com"

SRC_MIN, SRC_MAX = 3.0, 15.0      # s: the stock video's own length
SHOW_MIN, SHOW_MAX = 1.5, 3.0     # s: the excerpt on screen
SHOW_TAIL = 0.2                   # s kept after the last word of the clause
DUR_GIVEN_MIN = 1.0               # s: a moment whose time on screen the caller gives (broll_litteral) may be this short
OUT_W, OUT_H = 1080, 1920
CROP_MIN_W = 720                  # a 9:16 crop narrower than this is too soft once scaled to 1080 (HD floor)
MAX_MB = 20                       # never download a bigger file (a 1080x1920 file of 10 s weighs 3-11 MB; a 4K
                                  # landscape one 25+ MB, for the same 1080 px of width once cropped)
VIDEO_GAP = 3.0                   # s at least between two footage moments of a clip (the references: one every 3-5 s)
PER_PAGE = 15
CANDIDATES = 5                    # judged per moment (one row of the sheet each)
PREVIEW_FRAMES = 3                # preview frames per candidate on the sheet
TILE_W, TILE_H = 150, 266
EDGE = 0.4                        # s never taken at the very start / end of a stock video (fades, wobbles)
# Colour footage only (10-oct-2026, clip 1: the « scientists » footage was black and white — the judge let it pass):
# a candidate whose preview frames are all grey (mean HSV saturation under GREY_SAT and its 90th percentile under
# GREY_P90 — the « scientists » one: 0.000 / 0.000; the dullest colour shots of clips 1-2: 0.04-0.08 / 0.12-0.26) is
# dropped before the judge sees it, and the judge is told to want colour footage.
GREY_SAT, GREY_P90 = 0.03, 0.08

# Never searched nor kept (the channel's rule: nothing that evokes a death or its means, no gore).
BLOCKED = re.compile(r"\b(dead|death|dying|die[sd]?|corpse|coffin|funeral|grave|cemetery|suicid\w*|overdose\w*|gun|"
                     r"pistol|rifle|weapon|knife|noose|blood\w*|gore|wound\w*|syringe|needle|"
                     r"pills?|morgue|autopsy|skull|skeleton)\b", re.I)

# The motion words that make a moment an action when spot() could not say (the rule: footage for what MOVES).
ACTION_WORDS = re.compile(r"\b(\w+ing|drink\w*|pour\w*|run|ran|walk\w*|sleep\w*|slept|breath\w*|driv\w*|drove|swim\w*|"
                          r"swam|eat\w*|ate|cook\w*|wash\w*|shower\w*|cry|cried|laugh\w*|yawn\w*|train\w*|work(ed|s)? out|"
                          r"exercis\w*|lift\w*|danc\w*|jump\w*|stretch\w*|scroll\w*|typ(e|ed|ing)|rub\w*|flow\w*|"
                          r"rain\w*|boil\w*|smok\w*|wak(e|es|ing)|woke)\b", re.I)


# --- the switch, the key -------------------------------------------------------------------------------------------

def enabled(cfg=None):
    """plus.BROLL["video"], as the job carries it (PLUS_BROLL_JSON) or the house recipe's own value."""
    if cfg is None:
        try:
            cfg = json.loads(os.environ.get("PLUS_BROLL_JSON") or "null")
        except ValueError:
            cfg = None
    if isinstance(cfg, dict) and "video" in cfg:
        return bool(cfg["video"])
    try:
        import plus
        return bool(plus.BROLL.get("video", False))
    except Exception:
        return False


def api_key():
    """The Pexels key (environment, then .env) or None. Never printed, never put in a URL."""
    key = os.environ.get("PEXELS_API_KEY")
    folder = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):             # the repo's .env, also from a worktree (.claude/worktrees/<name>/ -> the repo)
        if key:
            break
        try:
            from dotenv import dotenv_values
            key = dotenv_values(os.path.join(folder, ".env")).get("PEXELS_API_KEY")
        except Exception:
            key = None
        folder = os.path.dirname(folder)
    return (key or "").strip() or None


def cache_dir():
    d = os.environ.get("BROLL_VIDEO_CACHE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "output",
                                                            "_broll_video")
    os.makedirs(d, exist_ok=True)
    return d


# --- action or object ----------------------------------------------------------------------------------------------

NOT_ACTIONS = {"thing", "things", "something", "nothing", "anything", "everything", "morning", "evening", "ceiling",
               "king", "ring", "string", "building", "wedding", "meeting", "during", "spring", "sibling"}


def guess_kind(word, sentence=""):
    """"action" when the word names something that moves (a motion verb or an -ing form), else "object"."""
    w = re.sub(r"[^\w' -]", "", (word or "").lower()).strip()
    if w and w not in NOT_ACTIONS and ACTION_WORDS.search(w):
        return "action"
    return "object"


def wants_video(moment):
    """Footage for an ACTION or a moving scene; the generated picture for an object."""
    kind = (moment or {}).get("kind") or guess_kind((moment or {}).get("word", ""), (moment or {}).get("sentence", ""))
    return kind == "action"


# --- Pexels search -------------------------------------------------------------------------------------------------

def crop_size(w, h):
    """The 9:16 crop of a w x h frame (centred)."""
    if w * 16 > h * 9:
        return int(h * 9 / 16), h
    return w, int(w * 16 / 9)


def best_file(video):
    """The smallest mp4 whose 9:16 crop fills 1080x1920; else the smallest whose crop is at least CROP_MIN_W wide;
    None when no file is good enough (or every good one is over MAX_MB)."""
    files = []
    for f in video.get("video_files") or []:
        if (f.get("file_type") or "video/mp4") != "video/mp4" or not f.get("link") or not f.get("width"):
            continue
        cw, ch = crop_size(int(f["width"]), int(f["height"]))
        size = int(f.get("size") or 0) or int(f["width"]) * int(f["height"]) * 4   # no size: a rough stand-in
        if size > MAX_MB * 1e6:
            continue
        files.append((cw, ch, size, f))
    full = [x for x in files if x[0] >= OUT_W and x[1] >= OUT_H]
    ok = full or [x for x in files if x[0] >= CROP_MIN_W]
    if not ok:
        return None
    cw, ch, size, f = min(ok, key=lambda x: x[2])
    return {"link": f["link"], "width": int(f["width"]), "height": int(f["height"]), "size": size,
            "fps": f.get("fps"), "full": bool(full)}


def title_of(video):
    """The page's title, read from its URL (…/video/a-man-rubbing-his-eyes-1234567/)."""
    m = re.search(r"/video/([^/]+?)-?\d*/?$", video.get("url") or "")
    return (m.group(1).replace("-", " ").strip() if m else "") or ""


def candidate(video):
    """One search hit, normalised, or None when it breaks a rule (length, quality, a blocked word in its title)."""
    try:
        dur = float(video.get("duration") or 0)
    except (TypeError, ValueError):
        return None
    if not SRC_MIN <= dur <= SRC_MAX:
        return None
    f = best_file(video)
    if not f:
        return None
    title = title_of(video)
    tags = " ".join(str(t) for t in video.get("tags") or [])
    if BLOCKED.search(f"{title} {tags}"):
        return None
    pics = sorted(video.get("video_pictures") or [], key=lambda p: p.get("nr", 0))
    user = video.get("user") or {}
    return {"id": video.get("id"), "title": title, "tags": tags, "duration": dur, "page": video.get("url"),
            "portrait": int(video.get("height") or 0) > int(video.get("width") or 0),
            "width": video.get("width"), "height": video.get("height"),
            "image": video.get("image"), "pictures": [p.get("picture") for p in pics if p.get("picture")],
            "file": f, "credit": {"author": user.get("name"), "author_url": user.get("url"), "page": video.get("url"),
                                  "license": LICENSE, "video_id": video.get("id")}}


def rank(cands):
    """Portrait first, a file that fills 1080x1920, then the lightest; Pexels' own relevance order breaks ties."""
    return sorted(cands, key=lambda c: (not c["portrait"], not c["file"]["full"], c["file"]["size"]))


def _get(params, key, session=None, timeout=20):
    import requests
    s = session or requests
    r = s.get(API, params=params, headers={"Authorization": key}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def search(query, key=None, session=None, folder=None):
    """Up to PER_PAGE usable candidates for ``query`` (portrait first; any orientation when portrait gives fewer than 3),
    ranked. The answers are kept on disk per query: the same search is never asked twice. [] on any failure."""
    query = re.sub(r"\s+", " ", query or "").strip().lower()
    if not query or BLOCKED.search(query):
        return []
    folder = folder or os.path.join(cache_dir(), "search")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, hashlib.sha1(query.encode("utf-8")).hexdigest()[:16] + ".json")
    raw = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = None
    if raw is None:
        key = key or api_key()
        if not key:
            print("   ⚠️ B-roll vidéo : pas de clé Pexels (PEXELS_API_KEY).")
            return []
        raw = {"query": query, "videos": []}
        try:
            for orientation in ("portrait", None):
                params = {"query": query, "per_page": PER_PAGE, "size": "medium"}
                if orientation:
                    params["orientation"] = orientation
                got = _get(params, key, session).get("videos") or []
                seen = {v.get("id") for v in raw["videos"]}
                raw["videos"] += [v for v in got if v.get("id") not in seen]
                if sum(1 for v in raw["videos"] if candidate(v)) >= 3:
                    break
        except Exception as e:      # the message never carries the key (it is in a header)
            print(f"   ⚠️ B-roll vidéo : recherche Pexels « {query} » impossible ({type(e).__name__}).")
            return []
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw, f)
    return rank([c for c in (candidate(v) for v in raw.get("videos") or []) if c])


# --- the judge on the preview frames -------------------------------------------------------------------------------

def _fetch(url, path, host, session=None, timeout=20):
    """A small file from Pexels' own ``host`` (preview jpg / video mp4), kept: never fetched twice."""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    if not url or not re.match(rf"^https://{re.escape(host)}/", url):
        raise ValueError(f"not a {host} URL")
    import requests
    s = session or requests
    tmp = path + ".part"
    with s.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    os.replace(tmp, path)
    return path


def preview_frames(cand, n=PREVIEW_FRAMES):
    """``n`` preview pictures spread over the video (at ~20 %, 50 %, 80 %): (index in cand["pictures"], url)."""
    pics = cand.get("pictures") or ([cand["image"]] if cand.get("image") else [])
    if not pics:
        return []
    if len(pics) <= n:
        return list(enumerate(pics))
    idx = sorted({min(len(pics) - 1, int(round(p * (len(pics) - 1)))) for p in (0.2, 0.5, 0.8)[:n]})
    return [(i, pics[i]) for i in idx]


def saturation(path):
    """(mean, 90th percentile) of the HSV saturation of the picture at ``path``, 0..1."""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((256, 256))
    s = np.asarray(im.convert("HSV"), dtype=np.float32)[..., 1] / 255.0
    return float(s.mean()), float(np.percentile(s, 90))


def is_grey(path):
    """True when the picture at ``path`` is black and white (or nearly: GREY_SAT, GREY_P90); None when unreadable."""
    try:
        mean, p90 = saturation(path)
    except Exception:
        return None
    return mean < GREY_SAT and p90 < GREY_P90


def colour_only(cands, session=None, n=CANDIDATES):
    """The first ``n`` candidates whose preview frames are not all black and white (the frames the sheet shows, fetched
    once into the cache); a candidate whose frames cannot be read is kept (the judge sees it)."""
    folder = os.path.join(cache_dir(), "previews")
    os.makedirs(folder, exist_ok=True)
    out = []
    for c in cands or []:
        greys = []
        for i, url in preview_frames(c):
            p = os.path.join(folder, f"{c['id']}_{i}.jpg")
            try:
                _fetch(url, p, PREVIEW_HOST, session)
            except Exception:
                continue
            greys.append(is_grey(p))
        if greys and all(g is True for g in greys):
            print(f"   ⚫ B-roll vidéo : « {_q(c.get('title'), 8)} » écartée (noir et blanc).")
            continue
        out.append(c)
        if len(out) >= n:
            break
    return out


def sheet(cands, path, label="", session=None):
    """One jpg for a moment: a row per candidate (its number, PREVIEW_FRAMES frames a, b, c)."""
    from PIL import Image, ImageDraw, ImageFont
    folder = os.path.join(cache_dir(), "previews")
    os.makedirs(folder, exist_ok=True)
    rows = []
    for c in cands:
        frames = []
        for i, url in preview_frames(c):
            p = os.path.join(folder, f"{c['id']}_{i}.jpg")
            try:
                _fetch(url, p, PREVIEW_HOST, session)
                frames.append(Image.open(p).convert("RGB"))
            except Exception:
                frames.append(None)
        rows.append(frames)
    pad, head = 6, 28
    cols = PREVIEW_FRAMES
    W = pad + cols * (TILE_W + pad) + 34
    H = head + len(rows) * (TILE_H + pad) + pad
    img = Image.new("RGB", (W, H), (24, 24, 24))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    d.text((pad, 5), label[:60], fill=(255, 255, 255), font=font)
    for r, frames in enumerate(rows):
        y = head + r * (TILE_H + pad)
        d.text((pad, y + TILE_H // 2 - 10), str(r), fill=(255, 220, 0), font=font)
        for k, fr in enumerate(frames):
            x = 34 + k * (TILE_W + pad)
            if fr is None:
                continue
            fr = fr.copy()
            fr.thumbnail((TILE_W * 3, TILE_H * 3))
            # the 9:16 window the cut will keep, as the viewer will see it
            cw, ch = crop_size(*fr.size)
            left, top = (fr.size[0] - cw) // 2, (fr.size[1] - ch) // 2
            fr = fr.crop((left, top, left + cw, top + ch)).resize((TILE_W, TILE_H))
            img.paste(fr, (x, y))
            d.text((x + 4, y + 2), "abc"[k], fill=(255, 220, 0), font=font)
    img.save(path, quality=85)
    return path


JUDGE_PROMPT = """You pick stock footage for a podcast Short. On a word of the clip the speaker is cut away for 1.5-3 s to
real footage that shows THE THING SAID, literally, understood in a quarter of a second (a man rubbing his eyes for
"exhausted", tap water running into a glass for "water", a patient on a hospital bed for "injured").

One image per moment below (in order). Each row = one candidate video (its number on the left), three frames of it
(a, b, c, in time order), already cropped to the vertical window the viewer will see.
For each moment choose the ONE candidate that shows what the words say most literally and most clearly, or -1 when
none does. A candidate is NEVER chosen when it shows:
- a famous or recognisable real person (generic anonymous people are fine);
- anything that evokes a death or its means (weapon, rope, pills spilled, a body, a coffin, a grave, a hospital death);
- blood, a wound, gore, a needle going in;
- readable text, a caption, a watermark, a brand or a logo on screen;
- a sexualised or bare body;
- a toy, an animal, an object or a cartoon standing in for the person or the action said (never literal);
- black and white, sepia or washed-out footage: the channel shows COLOR footage only, vivid and natural.
Prefer real anonymous people doing exactly the action said, in a plain natural setting.
Also say which frame (a, b or c) is the best moment to cut to (it will be the middle of the excerpt).

{moments}
Return JSON: {{"moments": [{{"k": 0, "pick": 2, "frame": "b", "why": "a few words"}}]}}"""
JUDGE_SCHEMA = {"type": "object", "properties": {"moments": {"type": "array", "items": {
    "type": "object", "properties": {"k": {"type": "integer"}, "pick": {"type": "integer"},
                                     "frame": {"type": "string"}, "why": {"type": "string"}},
    "required": ["k", "pick", "frame"]}}}, "required": ["moments"]}


def _ask(prompt, schema, attach, stage):
    """One Claude call (vision), Sonnet at low effort, Haiku when Sonnet fails; None when nobody answered."""
    import broll
    model = os.environ.get("BRAIN_BROLL_VIDEO") or "sonnet"
    for m in dict.fromkeys((model, "haiku")):
        try:
            return broll.claude_json(prompt, schema, timeout=180, attach=attach, stage=stage, model=m, effort="low")
        except Exception as e:
            print(f"   ⚠️ B-roll vidéo : {stage} sur {m} sans réponse ({str(e)[:80]}).")
    return None


def _q(s, n=40):
    words = re.sub(r"\s+", " ", str(s or "")).replace('"', "'").strip().split(" ")
    return " ".join(words[:n])


def choose(moments, cands, folder, session=None):
    """``cands[k]`` = the candidates of ``moments[k]``. ONE judge call for the whole clip -> for each moment the chosen
    candidate (with "frame_index", "why") or None."""
    os.makedirs(folder, exist_ok=True)
    asked, sheets, lines = [], [], []
    cands = [colour_only(cs, session) for cs in cands]          # black-and-white footage never reaches the judge
    for k, (m, cs) in enumerate(zip(moments, cands)):
        cs = (cs or [])[:CANDIDATES]
        if not cs:
            continue
        path = os.path.join(folder, f"sheet_{k:02d}.jpg")
        sheet(cs, path, f"{k} · {m.get('word', '')}", session)
        sheets.append(path)
        titles = "; ".join(f"{i}: {_q(c['title'], 10)} ({c['duration']:.0f} s)" for i, c in enumerate(cs))
        lines.append(f'k={k} — word "{_q(m.get("word"), 4)}" in "{_q(m.get("sentence"))}"; looking for: '
                     f'"{_q(m.get("query"), 8)}", color footage\n  candidates (page titles): {titles}')
        asked.append(k)
    out = [None] * len(moments)
    if not asked:
        return out
    data = _ask(JUDGE_PROMPT.format(moments="\n".join(lines)), JUDGE_SCHEMA, sheets, "broll_video") or {}
    for r in data.get("moments") or []:
        k, pick = r.get("k"), r.get("pick")
        if not (isinstance(k, int) and k in asked and isinstance(pick, int)):
            continue
        cs = (cands[k] or [])[:CANDIDATES]
        if not 0 <= pick < len(cs):
            continue
        frames = preview_frames(cs[pick])
        f = {"a": 0, "b": 1, "c": 2}.get(str(r.get("frame") or "b").strip().lower()[:1], 1)
        f = min(f, len(frames) - 1) if frames else 0
        n_pics = max(1, len(cs[pick].get("pictures") or []))
        out[k] = {**cs[pick], "frame_index": frames[f][0] if frames else 0, "frame_of": n_pics,
                  "why": _q(r.get("why"), 20)}
    return out


# --- timing, download, cut -----------------------------------------------------------------------------------------

def span(words, t, clip_end=None):
    """How long the excerpt stays: from its word (``t``) to the end of the clause the word is in + SHOW_TAIL, within
    SHOW_MIN-SHOW_MAX, never past the clip's end. ``words`` = [(start, text)] or [{"start", "word"}]."""
    ws = []
    for w in words or []:
        s, txt = (w[0], w[1]) if isinstance(w, (list, tuple)) else (w.get("start"), w.get("word") or w.get("text"))
        ws.append((float(s), str(txt or "")))
    end = t + SHOW_MAX
    for i, (s, txt) in enumerate(ws):
        if s < t:
            continue
        if re.search(r"[.,!?;:]$", txt.strip()):
            nxt = ws[i + 1][0] if i + 1 < len(ws) else s + 0.4
            end = min(nxt, s + 0.4 + SHOW_TAIL)
            break
    dur = max(SHOW_MIN, min(SHOW_MAX, end - t))
    if clip_end is not None:
        dur = min(dur, max(0.0, clip_end - t))
    return round(dur, 2)


def excerpt_start(cand, dur):
    """Where in the stock video the excerpt starts: centred on the judge's frame, away from the very start and end."""
    d = float(cand.get("duration") or 0)
    n = max(1, int(cand.get("frame_of") or len(cand.get("pictures") or []) or 1))
    centre = (cand.get("frame_index", n // 2) + 0.5) / n * d
    lo, hi = EDGE, max(EDGE, d - dur - EDGE)
    return round(min(hi, max(lo, centre - dur / 2)), 2)


def download(cand, session=None):
    """The chosen file in the cache (files/<id>_<w>x<h>.mp4): downloaded once, never again."""
    f = cand["file"]
    folder = os.path.join(cache_dir(), "files")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{cand['id']}_{f['width']}x{f['height']}.mp4")
    return _fetch(f["link"], path, FILE_HOST, session, timeout=120)


def cut_cmd(src, start, dur, out, fps=30):
    vf = (f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale={OUT_W}:{OUT_H}:flags=lanczos,"
          f"fps={fps},setsar=1,format=yuv420p")
    return ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}", "-an",
            "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out]


def cut(src, start, dur, out, fps=30):
    """The excerpt: ``dur`` s from ``start``, centre-cropped to 9:16, 1080x1920, no sound."""
    subprocess.run(cut_cmd(src, start, dur, out, fps), check=True, capture_output=True)
    return out


def apply_cmd(clip, placements, out):
    """ffmpeg command laying every excerpt full screen over ``clip`` at [t, t+dur] (hard cut in and out); the clip's
    sound is kept as is."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", clip]
    for p in placements:
        cmd += ["-i", p["path"]]
    chains, last = [], "0:v"
    for i, p in enumerate(placements, 1):
        t0, t1 = p["t"], p["t"] + p["dur"]
        chains.append(f"[{i}:v]setpts=PTS-STARTPTS+{t0:.3f}/TB,scale={OUT_W}:{OUT_H}[v{i}]")
        chains.append(f"[{last}][v{i}]overlay=0:0:eof_action=pass:enable='between(t,{t0:.3f},{t1:.3f})'[o{i}]")
        last = f"o{i}"
    cmd += ["-filter_complex", ";".join(chains), "-map", f"[{last}]", "-map", "0:a?", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", out]
    return cmd


def apply(clip, placements, out):
    if not placements:
        return clip
    subprocess.run(apply_cmd(clip, placements, out), check=True, capture_output=True)
    return out


# --- spotting the moments ------------------------------------------------------------------------------------------

SPOT_PROMPT = """A podcast Short (title: "{title}"). Its words, each with its second: {words}

List the moments where the speaker names something CONCRETE a viewer could SEE, the thing said literally (never a
symbol, never a figure of speech taken at its word: "finger on the pulse", "a puddle of tears", "bright lights" for
famous people are figures, skip them): about one every 4-5 s at most, from the first seconds on.
For each: "t" (the second of its word, copied from the list), "word" (that word), "sentence" (the words around it),
"kind": "action" only when the WORDS THEMSELVES say something done or a scene that moves (they sleep all day, drive
your car, drinking water, she got a whole-body scan, he was taking drugs, a surgeon removed it); "object" for a
thing, a place or a person's role alone (a bottle, a pill, an organ, a clock, an emergency room, "a doctor"), and
"query": 2-5 plain English words to find that footage on a stock site, the action as said (sleeping in the daytime ->
"person sleeping daytime bedroom"), generic anonymous people only (never a named person), nothing that evokes a
death or its means, no gore.
Return JSON: {{"moments": [{{"t": 1.2, "word": "...", "sentence": "...", "kind": "action", "query": "..."}}]}}"""
SPOT_SCHEMA = {"type": "object", "properties": {"moments": {"type": "array", "items": {
    "type": "object", "properties": {"t": {"type": "number"}, "word": {"type": "string"},
                                     "sentence": {"type": "string"}, "kind": {"type": "string"},
                                     "query": {"type": "string"}},
    "required": ["t", "word", "kind", "query"]}}}, "required": ["moments"]}


def _bare(word):
    return re.sub(r"[^\w'-]", "", str(word or "")).lower()


def spot(words, title=""):
    """The concrete moments of a clip (one Claude call, text only), each snapped to the start of its word."""
    ws = [(float(w[0]), str(w[1])) if isinstance(w, (list, tuple)) else (float(w["start"]), str(w.get("word", "")))
          for w in words or []]
    if not ws:
        return []
    text = " ".join(f"{w}@{s:g}" for s, w in ws)
    data = _ask(SPOT_PROMPT.format(title=_q(title, 20), words=text), SPOT_SCHEMA, None, "broll_video_spot") or {}
    out = []
    for m in data.get("moments") or []:
        try:
            t = float(m.get("t"))
        except (TypeError, ValueError):
            continue
        # pile sur le mot: the start of the word itself (the one it names, within 2 s), else the nearest word
        said = _bare(m.get("word"))
        same = [x for x in ws if said and _bare(x[1]) == said and abs(x[0] - t) <= 2.0]
        s, w = min(same or ws, key=lambda x: abs(x[0] - t))
        if BLOCKED.search(f"{w} {m.get('word') or ''}"):      # never a picture ON "dying", "overdose"...
            continue
        kind = m.get("kind") if m.get("kind") in ("action", "object") else guess_kind(w)
        out.append({"t": s, "word": re.sub(r"[^\w'-]", "", w), "sentence": _q(m.get("sentence"), 30), "kind": kind,
                    "query": _q(m.get("query"), 6)})
    return sorted(out, key=lambda m: m["t"])


# --- the entry point -----------------------------------------------------------------------------------------------

def spaced(moments, gap=VIDEO_GAP):
    """The footage moments kept in time order, each at least ``gap`` s after the one before."""
    out = []
    for m in sorted(moments, key=lambda m: float(m["t"])):
        if not out or float(m["t"]) - float(out[-1]["t"]) >= gap:
            out.append(m)
    return out


def plan_clip(moments, tmp, session=None, gap=VIDEO_GAP):
    """Without downloading any video: for every ACTION moment its candidates and the judge's choice ->
    [{"moment", "choice" (or None), "candidates"}]."""
    acts = spaced([m for m in moments or [] if wants_video(m)], gap)
    cands = [search(m.get("query") or m.get("word") or "", session=session) for m in acts]
    picks = choose(acts, cands, os.path.join(tmp, "broll_video"), session) if acts else []
    return [{"moment": m, "choice": c, "candidates": cs[:CANDIDATES]} for m, c, cs in zip(acts, picks, cands)]


def videos_for_clip(moments, words, clip_end, tmp, cfg=None, session=None, fps=30, gap=VIDEO_GAP):
    """The integration's entry: ``moments`` = [{"t", "word", "sentence", "kind", "query"}] (spot() writes them; kind
    and query may be missing). Returns the placements for the ACTION moments that found footage:
    [{"t", "dur", "path", "word", "query", "credit", "kind": "video"}] — the other moments are left to the generated
    pictures. A moment may carry its own "dur" (the « littéral » chain placed it: kept, from DUR_GIVEN_MIN s) and a "key"
    (given back in its placement); ``gap``: the least time between two footage moments (0: the caller spaced them).
    [] when plus.BROLL["video"] is off, without a key, or on any failure."""
    if not enabled(cfg) or not api_key():
        return []
    out = []
    try:
        plan = plan_clip(moments, tmp, session, gap)
    except Exception as e:
        print(f"   ⚠️ B-roll vidéo : plan impossible ({type(e).__name__}).")
        return []
    folder = os.path.join(tmp, "broll_video")
    os.makedirs(folder, exist_ok=True)
    for p in plan:
        m, c = p["moment"], p["choice"]
        if not c:
            continue
        t = float(m["t"])
        # a moment placed by the caller (broll_litteral.schedule: its "dur") keeps its time on screen
        dur = (round(min(float(m["dur"]), SHOW_MAX + 0.5, max(0.0, clip_end - t) if clip_end is not None else 1e9), 2)
               if m.get("dur") else span(words, t, clip_end))
        if dur < (DUR_GIVEN_MIN if m.get("dur") else SHOW_MIN):
            continue
        if any(t < q["t"] + q["dur"] and q["t"] < t + dur for q in out):
            continue
        try:
            src = download(c, session)
            path = cut(src, excerpt_start(c, dur), dur, os.path.join(folder, f"v_{t:06.2f}_{c['id']}.mp4"), fps)
        except Exception as e:
            print(f"   ⚠️ B-roll vidéo : « {m.get('word')} » abandonné ({type(e).__name__}).")
            continue
        out.append({"t": t, "dur": dur, "path": path, "word": m.get("word"), "query": m.get("query"),
                    "credit": c["credit"], "kind": "video", **({"key": m["key"]} if m.get("key") else {})})
        print(f"   🎞️ B-roll vidéo : « {m.get('word')} » à {t:.2f} s, {dur:.1f} s — {c['title']} "
              f"(Pexels, {c['credit'].get('author')})")
    return out


def video_for(word, t, words, sentence="", query=None, kind=None, clip_end=None, tmp=".", cfg=None, session=None):
    """One concrete word said at ``t``: its placement (see videos_for_clip) or None (an object, nothing found, off)."""
    m = {"t": t, "word": word, "sentence": sentence, "kind": kind or guess_kind(word, sentence),
         "query": query or word}
    got = videos_for_clip([m], words, clip_end, tmp, cfg, session)
    return got[0] if got else None
