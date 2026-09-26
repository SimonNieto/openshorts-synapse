"""Find the most-viewed YouTube Shorts (or regular videos) in a niche via the
YouTube Data API, so a repost/clipping channel has a ready list of source
material to watch and pick from instead of hunting for it by hand. Shares the
same YOUTUBE_DATA_API_KEY as niche_hashtags.py.
"""
from typing import Dict, List

import httpx

# The API's own videoDuration buckets: "short" (<4min) is what YouTube calls
# a Short; "medium"/"long" together are everything else ("regular videos" in
# the UI). There is no single enum value for "not short", and the API takes
# only one videoDuration per call, so covering both buckets means two calls.
_VIDEO_DURATIONS = ("medium", "long")


def _search_duration(client: httpx.Client, niche: str, api_key: str,
                     duration: str, max_results: int, video_type: str) -> List[Dict]:
    search_resp = client.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part": "snippet", "type": "video", "videoDuration": duration,
            "maxResults": min(max(max_results, 1), 50), "order": "viewCount",
            "q": niche, "key": api_key,
        })
    search_resp.raise_for_status()
    items = search_resp.json().get('items', [])
    video_ids = [it['id']['videoId'] for it in items if it.get('id', {}).get('videoId')]
    if not video_ids:
        return []

    # search.list doesn't carry view counts — a second call against
    # videos.list is the only way to get real statistics per video.
    stats_resp = client.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "statistics,snippet", "id": ",".join(video_ids), "key": api_key})
    stats_resp.raise_for_status()
    stats_by_id = {v['id']: v for v in stats_resp.json().get('items', [])}

    results = []
    for it in items:
        vid = it.get('id', {}).get('videoId')
        stat = stats_by_id.get(vid)
        if not stat:
            continue
        snippet = stat.get('snippet', {})
        thumbs = snippet.get('thumbnails', {})
        thumb = thumbs.get('medium') or thumbs.get('default') or {}
        results.append({
            "videoId": vid,
            "title": snippet.get('title', ''),
            "channelTitle": snippet.get('channelTitle', ''),
            "viewCount": int(stat.get('statistics', {}).get('viewCount', 0) or 0),
            "publishedAt": snippet.get('publishedAt', ''),
            "thumbnailUrl": thumb.get('url', ''),
            "videoType": video_type,
            "url": (f"https://www.youtube.com/shorts/{vid}" if video_type == "short"
                   else f"https://www.youtube.com/watch?v={vid}"),
        })
    return results


def find_viral_shorts(niche: str, api_key: str, max_results: int = 20,
                      include_shorts: bool = True, include_videos: bool = False) -> List[Dict]:
    """Search for ``niche``, ranked by real view count. Raises on an API
    error (bad key, quota exhausted) — same contract as niche_hashtags.py.

    include_shorts / include_videos gate the two source categories (YouTube
    Shorts vs. regular-length videos) independently — both on is the old
    "shorts only" default plus regular videos merged in; both off falls back
    to shorts so the search never silently returns nothing.
    """
    niche = (niche or "").strip()
    if not niche:
        raise ValueError("niche is required")
    if not include_shorts and not include_videos:
        include_shorts = True

    results: List[Dict] = []
    with httpx.Client(timeout=15) as client:
        if include_shorts:
            results.extend(_search_duration(client, niche, api_key, "short", max_results, "short"))
        if include_videos:
            for duration in _VIDEO_DURATIONS:
                results.extend(_search_duration(client, niche, api_key, duration, max_results, "video"))

    # Merge can duplicate a video across duration buckets; last-view-count-seen
    # wins (they're all the same live stat, just from different calls).
    by_id = {r['videoId']: r for r in results}
    merged = list(by_id.values())
    merged.sort(key=lambda r: r['viewCount'], reverse=True)
    return merged[:max_results]
