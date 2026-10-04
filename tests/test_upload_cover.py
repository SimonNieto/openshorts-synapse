"""The cover of a posted clip (4-oct-2026): the frame with the hook on screen, on TikTok and Instagram Reels
(YouTube does not let an API set a Short's thumbnail)."""
import app as app_module


class _Client:
    sent = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, data=None, files=None):
        _Client.sent.append(data)
        return None


def test_the_hook_frame_is_the_cover(tmp_path, monkeypatch):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake")
    monkeypatch.setattr(app_module.httpx, "Client", _Client)
    monkeypatch.setattr(app_module, "_job_language", lambda job_id: None)
    captions = {"youtube_title": "T", "youtube_description": "D", "tiktok": "tt", "instagram": "ig"}
    app_module._upload_post_send("KEY", "me", "job", 1, str(clip), ["tiktok", "instagram", "youtube"], captions,
                                 None, None)
    data = _Client.sent[-1]
    assert data["cover_timestamp"] == data["thumb_offset"] == "1500"
    assert 650 < app_module.UPLOAD_POST_COVER_MS < 3300, "inside the hook's title (in by 0.65 s, out at 3.3 s)"
    assert "thumbnail" not in data and "thumbnail_url" not in data
    app_module._upload_post_send("KEY", "me", "job", 1, str(clip), ["youtube"], captions, None, None)
    assert "cover_timestamp" not in _Client.sent[-1] and "thumb_offset" not in _Client.sent[-1]
