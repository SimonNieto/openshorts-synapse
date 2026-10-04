"""Niches (4-oct-2026): the shows worth clipping for a channel, grouped by niche, each rated green / orange / red.

The owner gives her own channel (her niche, the starting point) and/or a link (a show such as Joe Rogan). The AI
reads them (each channel's description and its latest titles), names her niche and the niches running parallel to
the link (or to her channel without one), and writes one YouTube search per niche; the search finds the channels
behind those long videos; the AI then rates each channel twice for her:
- rights: may she clip it and earn money with the clips (green / orange / red);
- fit: does it follow her channel's niche.
YouTube has no "related channels" any more, hence the search.

The rights colour is only what can be shown: a sentence of the channel's own (its description, a video's
description) quoted as evidence, or a reputation the model is sure of, marked as such. Nothing found = orange,
never green. It is a lead, not a licence.

YouTube Data API (YOUTUBE_DATA_API_KEY, like viral_finder / niche_hashtags): a search costs 100 units of the
10 000 a day, the rest 1 unit a call; one run is about 450 units. A run is kept in output/_niches/ (asking the
same thing again spends no quota, unless ``refresh``).
"""
import hashlib
import json
import os
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import List
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import BaseModel

API = "https://www.googleapis.com/youtube/v3"
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "_niches")
NICHES = 4            # parallel niches, one YouTube search each (100 units each)
PER_NICHE = 5         # channels kept per niche
LATEST = 10           # latest uploads read per channel
LONG_SECONDS = 20 * 60
COLORS = ("green", "orange", "red")
RANK = {"green": 0, "orange": 1, "red": 2}


# --- reading YouTube ------------------------------------------------------------------------------

def parse_ref(text):
    """('channel' | 'handle' | 'user' | 'video' | 'query', value) for what the owner pasted."""
    text = (text or "").strip()
    if not text:
        return None
    if re.fullmatch(r"@[\w.\-]{2,}", text):
        return "handle", text
    if not re.match(r"^(https?://)?([\w-]+\.)*(youtube\.com|youtu\.be)\b", text, re.I):
        return "query", text
    url = urlparse(text if re.match(r"^https?://", text, re.I) else "https://" + text)
    host, path = url.netloc.lower(), url.path
    if host.endswith("youtu.be"):
        vid = path.strip("/").split("/")[0]
        return ("video", vid) if vid else None
    if path == "/watch":
        vid = (parse_qs(url.query).get("v") or [""])[0]
        return ("video", vid) if vid else None
    m = re.match(r"^/(shorts|live|embed)/([\w-]+)", path)
    if m:
        return "video", m.group(2)
    m = re.match(r"^/channel/(UC[\w-]+)", path)
    if m:
        return "channel", m.group(1)
    m = re.match(r"^/(@[^/]+)", path)
    if m:
        return "handle", m.group(1)
    m = re.match(r"^/(c|user)/([^/]+)", path)
    if m:
        return ("user" if m.group(1) == "user" else "query"), m.group(2)
    return None


def _get(client, path, key, **params):
    r = client.get(f"{API}/{path}", params={**params, "key": key})
    r.raise_for_status()
    return r.json()


def resolve(client, key, text):
    """The channel id behind a link, a handle, a video or a name (None when not found)."""
    ref = parse_ref(text)
    if not ref:
        return None
    kind, value = ref
    if kind == "channel":
        return value
    if kind == "video":
        items = _get(client, "videos", key, part="snippet", id=value).get("items") or []
        return items[0]["snippet"]["channelId"] if items else None
    if kind == "query":
        items = _get(client, "search", key, part="snippet", type="channel", q=value, maxResults=1).get("items") or []
        return items[0]["snippet"]["channelId"] if items else None
    by = {"forHandle": value} if kind == "handle" else {"forUsername": value}
    items = _get(client, "channels", key, part="id", **by).get("items") or []
    return items[0]["id"] if items else None


def _seconds(iso):
    """ISO 8601 duration (PT1H2M3S) in seconds."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def channels(client, key, ids):
    """{id: card} — title, handle, description, avatar, subscribers, uploads playlist."""
    out = {}
    ids = [i for i in dict.fromkeys(ids) if i]
    for b in range(0, len(ids), 50):
        data = _get(client, "channels", key, part="snippet,statistics,contentDetails", id=",".join(ids[b:b + 50]))
        for it in data.get("items") or []:
            sn, st = it.get("snippet") or {}, it.get("statistics") or {}
            thumbs = sn.get("thumbnails") or {}
            handle = sn.get("customUrl") or ""
            out[it["id"]] = {
                "id": it["id"], "title": sn.get("title", ""), "handle": handle,
                "url": f"https://www.youtube.com/{handle}" if handle.startswith("@")
                else f"https://www.youtube.com/channel/{it['id']}",
                "description": (sn.get("description") or "")[:2000],
                "avatar": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", ""),
                "country": sn.get("country") or "",
                "subscribers": None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount") or 0),
                "uploads": ((it.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") or "",
            }
    return out


def latest(client, key, uploads, n=LATEST):
    """The channel's latest uploads: title, views, seconds, date, description."""
    if not uploads:
        return []
    items = _get(client, "playlistItems", key, part="contentDetails", playlistId=uploads, maxResults=n).get("items")
    ids = [i for i in ((it.get("contentDetails") or {}).get("videoId") for it in items or []) if i]
    if not ids:
        return []
    out = []
    for v in _get(client, "videos", key, part="snippet,statistics,contentDetails", id=",".join(ids)).get("items") or []:
        sn = v.get("snippet") or {}
        out.append({"id": v["id"], "title": sn.get("title", ""), "published": sn.get("publishedAt", ""),
                    "views": int((v.get("statistics") or {}).get("viewCount") or 0),
                    "seconds": _seconds((v.get("contentDetails") or {}).get("duration")),
                    "description": (sn.get("description") or "")[:3000]})
    return out


def _date(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def numbers(videos):
    """What the latest uploads say: median views, uploads a week, share of long videos (> 20 min)."""
    if not videos:
        return {"median_views": None, "per_week": None, "long_share": None}
    dates = sorted(d for d in (_date(v["published"]) for v in videos) if d)
    weeks = (dates[-1] - dates[0]).days / 7 if len(dates) > 1 else 0
    return {"median_views": int(statistics.median(v["views"] for v in videos)),
            "per_week": round((len(dates) - 1) / weeks, 1) if weeks > 0 else None,
            "long_share": round(sum(v["seconds"] >= LONG_SECONDS for v in videos) / len(videos), 2)}


_CLIP_WORDS = re.compile(r"\b(clips?|clipping|clippers?|re-?post\w*|re-?upload\w*|copyright\w*|fair use|permission|"
                         r"monetiz\w*|monetis\w*|content id|use (?:our|my|this) (?:content|videos?))\b", re.I)


def evidence(card, videos, limit=6):
    """The channel's own lines about clipping / reposting / copyright: the only grounds for a green."""
    found = []
    sources = [("channel description", card.get("description") or "")]
    sources += [(f"description of « {v['title'][:60]} »", v.get("description") or "") for v in videos[:5]]
    for where, text in sources:
        for line in re.split(r"[\r\n]+", text):
            line = line.strip()
            if 8 <= len(line) <= 300 and _CLIP_WORDS.search(line) and line not in (f["quote"] for f in found):
                found.append({"where": where, "quote": line})
                if len(found) >= limit:
                    return found
    return found


def search_niche(client, key, query, exclude):
    """Channels behind the long videos of a niche's search, the most often found first."""
    since = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = _get(client, "search", key, part="snippet", type="video", videoDuration="long", q=query,
                order="relevance", maxResults=25, publishedAfter=since)
    hits = {}
    for it in data.get("items") or []:
        cid = (it.get("snippet") or {}).get("channelId")
        if cid and cid not in exclude:
            hits[cid] = hits.get(cid, 0) + 1
    return [c for c, _ in sorted(hits.items(), key=lambda kv: -kv[1])]


# --- the AI ---------------------------------------------------------------------------------------

class Niche(BaseModel):
    name: str             # "long-form science podcasts"
    why: str              # why it runs parallel to the link / her channel
    fit: str              # green | orange | red: does it follow her channel's niche
    search: str           # the YouTube search that finds its long-form shows


class Understanding(BaseModel):
    niche: str            # HER channel's niche, in a few words
    summary: str          # two sentences: what her channel is about and for whom
    good_source: str      # what makes a show worth clipping for her
    niches: List[Niche]


class Rating(BaseModel):
    id: str
    fit: str              # green | orange | red
    fit_why: str
    rights: str           # green | orange | red: may she clip it and earn money with the clips
    rights_basis: str     # "said by the channel" | "known reputation" | "nothing found"
    rights_why: str
    summary: str


class Ratings(BaseModel):
    ratings: List[Rating]


def _brief(label, card, videos):
    nums = numbers(videos)
    titles = "\n".join(f"  - {v['title']} ({v['views']:,} views, {v['seconds'] // 60} min)" for v in videos)
    return (f"{label}: {card['title']} ({card['handle'] or card['id']}), "
            f"{card['subscribers'] if card['subscribers'] is not None else 'hidden'} subscribers, "
            f"median {nums['median_views']} views, {nums['per_week']} uploads a week, "
            f"{int((nums['long_share'] or 0) * 100)}% of videos over 20 min.\n"
            f"Description: {card['description'][:800]}\nLatest videos:\n{titles}\n")


UNDERSTAND_PROMPT = """You help the owner of a YouTube channel find long-form shows to clip into shorts for her channel.

{refs}
{profile}
1. niche: the niche of HER channel in a few words (without her channel: the niche of a channel that clips the
   link's show). summary: two sentences on what it is about and for whom.
2. good_source: what makes a show worth clipping for her (format, kind of guests and talk, topics).
3. niches: the {n} niches running parallel to {around} — the same category of long-form talk seen from other
   angles (for Joe Rogan: science podcasts, combat sports talk, comedians' podcasts, health and longevity...),
   not her niche again word for word. For each: name, why it runs parallel, fit (green = her viewers would want it,
   orange = some of it, red = another audience), and one YouTube search that finds its long-form shows (podcasts,
   interviews, long conversations — not clip channels), in plain words a viewer would type.
Write "summary", "good_source" and "why" in French; "search" in the language of the shows.

Answer in JSON: {{"niche": "...", "summary": "...", "good_source": "...",
"niches": [{{"name": "...", "why": "...", "fit": "...", "search": "..."}}, ...]}}"""

RATE_PROMPT = """You help the owner of a YouTube channel pick long-form shows to clip into shorts.

Her channel's niche: {niche}
{summary}
A good show to clip for her: {good_source}

Rate each channel below twice (green / orange / red):
- rights: may she clip it, repost the clips and earn money with them? ONLY from what can be shown:
  green = the channel itself says clips are welcome / runs a clipping programme (quote the evidence line), or a
  reputation you are sure of (say "known reputation" and what it is);
  red = it says it forbids reuploads or clips, claims the clips' revenue (Content ID), or is known to take clip
  channels down;
  orange = nothing found either way (the usual case) — never green without grounds.
  rights_basis: "said by the channel", "known reputation" or "nothing found".
- fit: does it follow her channel's niche? green = same niche and spirit, her viewers would want it; orange = close,
  some episodes fit; red = another niche, or not long-form talk worth clipping (a clip channel, music, gaming...).
summary: one sentence for her, in plain words (what it is, why it is or is not for her).
Keep every channel id as given. Write fit_why, rights_why and summary in French.

Channels:
{channels}
Answer in JSON: {{"ratings": [{{"id": "...", "fit": "...", "fit_why": "...", "rights": "...", "rights_basis": "...",
"rights_why": "...", "summary": "..."}}, ...]}}"""


def _ask(prompt, schema):
    import ai_brain
    import plus
    return ai_brain.claude_json(prompt, schema, model=plus.BRAIN["detail"], effort="medium", timeout=420)


def _color(v):
    v = str(v or "").lower()
    return v if v in COLORS else "orange"


def _clean(r, has_evidence):
    """A rating the page can trust: known colours, no green right without grounds, overall from the two."""
    fit, rights = _color(r.get("fit")), _color(r.get("rights"))
    basis = r.get("rights_basis") or "nothing found"
    if rights == "green" and (basis not in ("said by the channel", "known reputation")
                              or (basis == "said by the channel" and not has_evidence)):
        rights, basis = "orange", "nothing found"
    overall = "red" if "red" in (fit, rights) else "green" if fit == rights == "green" else "orange"
    return {"fit": fit, "fit_why": r.get("fit_why", ""), "rights": rights, "rights_basis": basis,
            "rights_why": r.get("rights_why", ""), "overall": overall, "summary": r.get("summary", "")}


def _profile_line():
    """The Synapse Cut profile's own words on the channel, while there is no channel questionnaire yet."""
    try:
        import playbook
        import plus
        profiles = plus.load_profiles()
        if not profiles:
            return ""
        p = plus.sanitize(profiles[0])
        topics = [playbook.HOOK_CATEGORY.get(t, t) for t in p["selection"]["niche_topics"]]
        bits = [f"She clips {p['show']}." if p["show"] else "",
                f"Her topics: {', '.join(topics)}." if topics else "",
                f"Her channel in one line: {p['selection']['niche_context']}." if p["selection"]["niche_context"] else ""]
        return " ".join(b for b in bits if b)
    except Exception:
        return ""


# --- one run --------------------------------------------------------------------------------------

def _key(mine, link):
    return hashlib.sha1(f"{(mine or '').strip().lower()}|{(link or '').strip().lower()}".encode()).hexdigest()[:16]


def history(n=12):
    """The latest runs kept (newest first): what was asked and when."""
    try:
        names = [f for f in os.listdir(STORE) if f.endswith(".json")]
    except FileNotFoundError:
        return []
    out = []
    for f in names:
        try:
            with open(os.path.join(STORE, f), encoding="utf-8") as fh:
                d = json.load(fh)
            out.append({**d["asked"], "niche": d["niche"]["niche"], "made_at": d.get("made_at", 0),
                        "green": sum(c["overall"] == "green" for n in d["niches"] for c in n["channels"])})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(out, key=lambda x: -x["made_at"])[:n]


def _path(mine, link):
    return os.path.join(STORE, f"{_key(mine, link)}.json")


def kept(mine, link):
    """The run kept for this question, or None."""
    try:
        with open(_path((mine or "").strip(), (link or "").strip()), encoding="utf-8") as f:
            return {**json.load(f), "cached": True}
    except (OSError, ValueError):
        return None


def explore(mine, link, api_key, refresh=False):
    """Her niche (``mine``: her channel), the niches parallel to ``link`` (a show) and their shows, rated."""
    mine, link = (mine or "").strip(), (link or "").strip()
    if not mine and not link:
        raise ValueError("Give your channel, a link, or both.")
    if not refresh and kept(mine, link):
        return kept(mine, link)
    path = _path(mine, link)
    with httpx.Client(timeout=20) as client:
        refs = {}
        for label, text in (("mine", mine), ("link", link)):
            if text:
                cid = resolve(client, api_key, text)
                if not cid:
                    raise LookupError(f"No YouTube channel found for « {text} ».")
                refs[label] = cid
        cards = channels(client, api_key, refs.values())
        uploads = {cid: latest(client, api_key, cards[cid]["uploads"]) for cid in refs.values() if cid in cards}
        text = "".join(_brief("Her channel" if label == "mine" else "The link (a show)", cards[cid], uploads[cid])
                       for label, cid in refs.items() if cid in cards)
        profile = _profile_line()
        und = _ask(UNDERSTAND_PROMPT.format(
            refs=text, n=NICHES, profile=f"What her clip profile says: {profile}\n" if profile else "",
            around="the link's show" if "link" in refs else "her channel"), Understanding)
        # one search per niche; a channel goes to the first niche that finds it (the link is rated on its own)
        taken, groups = {refs.get("mine"), refs.get("link")}, []
        for n in und["niches"][:NICHES]:
            ids = [c for c in search_niche(client, api_key, n["search"], taken) if c not in taken][:PER_NICHE]
            taken.update(ids)
            groups.append((n, ids))
        new = [c for _, ids in groups for c in ids if c not in cards]
        cards.update(channels(client, api_key, new))
        for _, ids in groups:
            for cid in ids:
                if cid in cards and cid not in uploads:
                    uploads[cid] = latest(client, api_key, cards[cid]["uploads"])
    found = ([refs["link"]] if refs.get("link") in cards else []) + [c for _, ids in groups for c in ids if c in cards]
    ev = {cid: evidence(cards[cid], uploads.get(cid) or []) for cid in found}
    rated = {}
    if found:
        blocks = []
        for cid in found:
            lines = "".join(f"    evidence ({e['where']}): « {e['quote']} »\n" for e in ev[cid]) \
                or "    evidence: none found\n"
            blocks.append(f"- id {cid}\n  " + _brief("Channel", cards[cid], uploads.get(cid) or []).replace("\n", "\n  ")
                          + "\n" + lines)
        out = _ask(RATE_PROMPT.format(niche=und["niche"], summary=und["summary"], good_source=und["good_source"],
                                      channels="\n".join(blocks)), Ratings)
        rated = {r["id"]: r for r in out["ratings"] if r.get("id") in ev}
    def card(cid):
        c = cards[cid]
        return {**{k: c[k] for k in ("id", "title", "handle", "url", "avatar", "subscribers", "country")},
                **numbers(uploads.get(cid) or []), "evidence": ev[cid], **_clean(rated[cid], bool(ev[cid]))}

    niches = []
    for n, ids in groups:
        chans = [card(cid) for cid in ids if cid in rated]
        chans.sort(key=lambda s: (RANK[s["overall"]], RANK[s["fit"]], -(s["median_views"] or 0)))
        niches.append({**n, "fit": _color(n.get("fit")), "channels": chans})
    niches.sort(key=lambda n: RANK[n["fit"]])
    result = {"asked": {"mine": mine, "link": link},
              "mine": {k: cards[refs["mine"]][k] for k in ("id", "title", "handle", "url", "avatar", "subscribers")}
              if refs.get("mine") in cards else None,
              "link": card(refs["link"]) if refs.get("link") in rated else None,
              "niche": {k: und[k] for k in ("niche", "summary", "good_source")},
              "niches": niches, "made_at": time.time()}
    os.makedirs(STORE, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    return {**result, "cached": False}
