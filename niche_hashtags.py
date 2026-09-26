"""Research real hashtags from top-performing YouTube Shorts in a channel's
niche via the YouTube Data API v3, instead of having Gemini invent
plausible-looking ones from training data alone.

Cached per niche on disk (30 days) since a niche's hashtag pool barely moves
day to day and search.list is quota-metered (100 units/query on a 10k/day
free tier — cheap, but not free enough to spend on every clip).
"""
import json
import os
import re
import time
from typing import List, Optional

import httpx

CACHE_FILE = "hashtag_research.json"
CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days

# Noise every niche's search results carry regardless of topic — dropped so
# the pool stays specific to the niche instead of "#shorts #fyp #viral".
GENERIC_TAGS = {
    'shorts', 'short', 'fyp', 'foryou', 'foryoupage', 'viral', 'viralvideo',
    'trending', 'reels', 'reel', 'youtubeshorts', 'ytshorts',
}

HASHTAG_RE = re.compile(r'#(\w{2,30})', re.UNICODE)


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def cached_hashtags(niche: str) -> Optional[List[str]]:
    """The cached hashtag pool for this niche, or None if missing/stale."""
    entry = _load_cache().get((niche or "").strip().lower())
    if entry and time.time() - entry.get('researched_at', 0) < CACHE_TTL_SECONDS:
        return entry.get('hashtags')
    return None


def research_hashtags(niche: str, api_key: str) -> List[str]:
    """Search YouTube Shorts for this niche and rank the hashtags that
    actually show up in their titles/descriptions by frequency. Raises on an
    API error (bad key, quota exhausted) — same contract as any other
    network call in this codebase; the caller decides how to degrade.
    """
    niche = (niche or "").strip()
    if not niche:
        raise ValueError("niche is required")

    counts: dict = {}
    with httpx.Client(timeout=15) as client:
        for q in (f"{niche} shorts", f"{niche} #shorts"):
            resp = client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet", "type": "video", "videoDuration": "short",
                    "maxResults": 25, "order": "viewCount", "q": q, "key": api_key,
                })
            resp.raise_for_status()
            for item in resp.json().get('items', []):
                snippet = item.get('snippet', {})
                text = f"{snippet.get('title', '')} {snippet.get('description', '')}"
                for tag in HASHTAG_RE.findall(text):
                    tag = tag.lower()
                    # Episode numbers and timestamps get swept up by the
                    # regex too ("#1141", "#39") — never real hashtags.
                    if tag in GENERIC_TAGS or tag.isdigit():
                        continue
                    counts[tag] = counts.get(tag, 0) + 1

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    hashtags = [f"#{tag}" for tag, _ in ranked[:30]]

    cache = _load_cache()
    cache[niche.lower()] = {"hashtags": hashtags, "researched_at": time.time(), "niche": niche}
    _save_cache(cache)
    return hashtags


def get_or_research(niche: str, api_key: str) -> List[str]:
    """Cached pool if fresh, else research it now (and cache the result)."""
    return cached_hashtags(niche) or research_hashtags(niche, api_key)
