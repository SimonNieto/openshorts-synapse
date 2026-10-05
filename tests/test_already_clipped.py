"""Lot « Sélection » (5-oct-2026): has a bigger channel already posted this moment as a Short?
(already_clipped.py, switched off). No network: a fake YouTube answers."""
import pytest

already_clipped = pytest.importorskip("already_clipped")


# --- already clipped by a bigger channel (off) ----------------------------------------------------------

class TestAlreadyClipped:
    CLIP = {"start": 10.0, "hook_line": "Discipline is overrated, drive is what keeps you going.",
            "punchline": "Drive beats discipline every time.", "video_title_for_youtube_short": "Is drive better "
            "than discipline?", "viral_hook_text": "Discipline fails, drive does not"}

    def fake(self, subs=69_100, title="Why Drive Beats Discipline Every Time | Joe Rogan"):
        calls = []

        def fetch(path, params):
            calls.append((path, params))
            if path == "search":
                return {"items": [{"id": {"videoId": "abc"}, "snippet": {
                    "title": title, "channelId": "UC1", "channelTitle": "KINGSTOIC",
                    "publishedAt": "2026-10-03T10:00:00Z"}}]}
            return {"items": [{"id": "UC1", "statistics": {"subscriberCount": str(subs)}}]}
        return fetch, calls

    def test_off_by_default_and_without_a_key(self, monkeypatch):
        assert already_clipped.ENABLED is False
        monkeypatch.setenv("YOUTUBE_DATA_API_KEY", "k")
        assert not already_clipped.enabled()
        c = dict(self.CLIP)
        assert already_clipped.check([c]) == 0 and "already_clipped" not in c
        monkeypatch.setattr(already_clipped, "ENABLED", True)
        monkeypatch.delenv("YOUTUBE_DATA_API_KEY")
        assert not already_clipped.enabled()

    def test_a_bigger_channel_with_the_same_words(self):
        fetch, calls = self.fake()
        c = dict(self.CLIP)
        assert already_clipped.check([c], "Joe Rogan", fetch=fetch) == 1
        assert c["already_clipped"]["channel"] == "KINGSTOIC" and c["already_clipped"]["subscribers"] == 69_100
        assert c["already_clipped"]["url"].endswith("/abc")
        search = calls[0][1]
        assert search["type"] == "video" and search["videoDuration"] == "short" and "rogan" in search["q"].lower()

    def test_a_small_channel_or_other_words_mark_nothing(self):
        for fetch, _ in (self.fake(subs=900), self.fake(title="Morning routine for focus")):
            c = dict(self.CLIP)
            assert already_clipped.check([c], fetch=fetch) == 0 and "already_clipped" not in c

    def test_never_raises(self):
        def boom(path, params):
            raise RuntimeError("quota")
        c = dict(self.CLIP)
        assert already_clipped.check([c], fetch=boom) == 0
