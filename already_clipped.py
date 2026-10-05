"""Has a bigger channel already posted this moment as a Short? (5-oct-2026, lot Sélection)

The veille report (output/_stepup/veille/rapport.md, C4 and idea I2): the same passages of JRE #2553 were
already cut by bigger channels (KINGSTOIC, 69 k subscribers: « Why Drive Beats Discipline Every Time », the day
before; Huberman's own channel; Huberman Protocols), and her three reposted subjects all did 14-50 % worse the
second time. YouTube names "content uploaded many times by other creators" as reused content, and a viewer who
already saw the moment can answer "Not interested". So before a clip is ranked, one YouTube search per clip
looks for a Short with the same words, published in the last WINDOW_DAYS days by a channel of MIN_SUBSCRIBERS
or more. A match marks the clip ``already_clipped`` (who, when, the link) and main.rank_by_opening takes
PENALTY points off its score: a preference, never a filter — the clip stays, another angle on it may still win.

OFF (ENABLED = False) until the user switches it on; it also needs YOUTUBE_DATA_API_KEY. Cost: one search
(100 units of the 10 000 a day) + one channel read (1 unit) per clip, so ~1 200 units for a job of 12 clips
(the Niches tab spends ~450 a run). Never raises: a search problem must never cost the clip.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

ENABLED = False               # the switch (5-oct-2026: off, waits for the user's go)
MIN_SUBSCRIBERS = 50_000      # "a bigger channel" (veille I2)
WINDOW_DAYS = 30
MIN_SHARED_WORDS = 3          # significant words their title shares with our clip's words
PENALTY = 10                  # points off predicted_score (main.rank_by_opening)
MAX_RESULTS = 10
QUERY_WORDS = 8
API = "https://www.googleapis.com/youtube/v3"


def enabled() -> bool:
    return bool(ENABLED and (os.environ.get("YOUTUBE_DATA_API_KEY") or "").strip())


def _sig(text: str) -> list:
    import playbook
    out = []
    for w in re.findall(r"[a-zà-ÿ0-9']+", (text or "").lower()):
        w = re.sub(r"'s$", "", w).strip("'")
        if len(w) >= 3 and w not in playbook._HOOK_STOPWORDS and w not in out:
            out.append(w)
    return out


def query(clip: dict, show: str = "") -> str:
    """The search: the clip's most telling words (its opening line, then its payoff, then its title) and the
    show's name, as a viewer would type them."""
    words = []
    for field in ("hook_line", "punchline", "video_title_for_youtube_short"):
        for w in _sig(clip.get(field) or ""):
            if w not in words:
                words.append(w)
    q = " ".join(words[:QUERY_WORDS])
    return f"{q} {show}".strip() if show else q


def shared_words(clip: dict, title: str) -> list:
    """Significant words of a found video's title that our clip says or shows (stems of 5 letters)."""
    ours = set()
    for field in ("hook_line", "punchline", "video_title_for_youtube_short", "viral_hook_text"):
        ours |= {w[:5] for w in _sig(clip.get(field) or "")}
    return [w for w in _sig(title) if w[:5] in ours]


def _get(path: str, params: dict) -> dict:
    import httpx
    r = httpx.get(f"{API}/{path}", params={**params, "key": os.environ.get("YOUTUBE_DATA_API_KEY", "")},
                  timeout=20)
    r.raise_for_status()
    return r.json()


def check(shorts, show: str = "", fetch=None, now=None) -> int:
    """Mark the clips a bigger channel already posted (``already_clipped``). ``fetch(path, params) -> dict``
    replaces the YouTube Data API (tests). Returns how many clips were marked; 0 when switched off."""
    if fetch is None and not enabled():
        return 0
    fetch = fetch or _get
    now = now or datetime.now(timezone.utc)
    after = (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    marked = 0
    for c in shorts:
        try:
            q = query(c, show)
            if not q:
                continue
            found = fetch("search", {"part": "snippet", "q": q, "type": "video", "videoDuration": "short",
                                     "publishedAfter": after, "maxResults": MAX_RESULTS, "order": "relevance"})
            hits = []
            for it in (found or {}).get("items") or []:
                sn = it.get("snippet") or {}
                shared = shared_words(c, sn.get("title") or "")
                if len(shared) >= MIN_SHARED_WORDS:
                    hits.append((it, sn, shared))
            if not hits:
                continue
            ids = ",".join(sorted({sn.get("channelId") for _, sn, _ in hits if sn.get("channelId")}))
            subs = {}
            for ch in (fetch("channels", {"part": "statistics", "id": ids}) or {}).get("items") or []:
                try:
                    subs[ch.get("id")] = int((ch.get("statistics") or {}).get("subscriberCount") or 0)
                except (TypeError, ValueError):
                    continue
            big = [(it, sn, shared) for it, sn, shared in hits if subs.get(sn.get("channelId"), 0) >= MIN_SUBSCRIBERS]
            if not big:
                continue
            it, sn, shared = max(big, key=lambda h: (len(h[2]), subs.get(h[1].get("channelId"), 0)))
            vid = (it.get("id") or {}).get("videoId") or ""
            c["already_clipped"] = {"title": sn.get("title") or "", "channel": sn.get("channelTitle") or "",
                                    "subscribers": subs.get(sn.get("channelId"), 0),
                                    "published": sn.get("publishedAt") or "", "shared": shared,
                                    "url": f"https://www.youtube.com/shorts/{vid}" if vid else ""}
            marked += 1
        except Exception as e:  # never cost the clip
            print(f"   ⚠️ Already-clipped check skipped for the clip at {float(c.get('start', 0)):.0f}s "
                  f"({type(e).__name__}: {str(e)[:120]})")
    return marked
