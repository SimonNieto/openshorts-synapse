"""broll_video: Pexels footage for the actions said (no network: the API, the files and Claude are simulated)."""
import json
import os

import pytest

import broll_video as bv


def video(vid, w=1080, h=1920, dur=8, slug="a-man-drinking-water", files=None, n_pics=15, tags=()):
    files = files if files is not None else [
        {"file_type": "video/mp4", "width": w // 2, "height": h // 2, "link": f"https://videos.pexels.com/{vid}_sd.mp4",
         "size": 1_000_000},
        {"file_type": "video/mp4", "width": w, "height": h, "link": f"https://videos.pexels.com/{vid}_hd.mp4",
         "size": 5_000_000},
        {"file_type": "video/mp4", "width": w * 2, "height": h * 2, "link": f"https://videos.pexels.com/{vid}_uhd.mp4",
         "size": 15_000_000}]
    return {"id": vid, "width": w, "height": h, "duration": dur, "url": f"https://www.pexels.com/video/{slug}-{vid}/",
            "image": f"https://images.pexels.com/videos/{vid}/x.jpeg", "tags": list(tags),
            "user": {"name": "Jane Doe", "url": "https://www.pexels.com/@jane"},
            "video_files": files,
            "video_pictures": [{"nr": i, "picture": f"https://images.pexels.com/videos/{vid}/pictures/preview-{i}.jpeg"}
                               for i in range(n_pics)]}


class FakeResp:
    def __init__(self, data=None, body=b""):
        self.data, self.body = data, body

    def raise_for_status(self):
        pass

    def json(self):
        return self.data

    def iter_content(self, n):
        yield self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        self.calls.append({"url": url, "params": params, "headers": headers})
        if url == bv.API:
            return FakeResp(self.pages.pop(0) if self.pages else {"videos": []})
        return FakeResp(body=b"jpgormp4")


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("BROLL_VIDEO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("PEXELS_API_KEY", "test-key-not-real")
    monkeypatch.delenv("PLUS_BROLL_JSON", raising=False)
    return tmp_path


def test_switch_on_in_this_branch_and_read_from_the_job(monkeypatch):
    import plus
    monkeypatch.delenv("PLUS_BROLL_JSON", raising=False)
    # references-v3 (the final bench of 9-oct-2026): on; production keeps it off until the user validates it
    assert plus.BROLL["video"] is True
    assert bv.enabled() is True
    monkeypatch.setenv("PLUS_BROLL_JSON", json.dumps({**plus.BROLL, "video": False}))
    assert bv.enabled() is False
    monkeypatch.setenv("PLUS_BROLL_JSON", json.dumps({**plus.BROLL, "video": True}))
    assert bv.enabled() is True
    assert bv.enabled({"video": False}) is False


def test_job_env_carries_the_switch():
    import plus
    env = plus.job_env({"name": "x", "broll": {"enabled": True}})
    assert json.loads(env["PLUS_BROLL_JSON"])["video"] is True


def test_action_or_object():
    assert bv.wants_video({"word": "x", "kind": "action"})
    assert not bv.wants_video({"word": "drinking", "kind": "object"})
    assert bv.guess_kind("drinking") == "action"
    assert bv.guess_kind("pouring,") == "action"
    assert bv.guess_kind("sleep") == "action"
    assert bv.guess_kind("melatonin") == "object"
    assert bv.guess_kind("morning") == "object"
    assert bv.guess_kind("something") == "object"


def test_crop_and_best_file():
    assert bv.crop_size(1920, 1080) == (607, 1080)
    assert bv.crop_size(1080, 1920) == (1080, 1920)
    # portrait: the smallest file that fills 1080x1920
    assert bv.best_file(video(1))["link"].endswith("_hd.mp4")
    # landscape 1080p: the crop is 607 px wide, under the HD floor; the 4K one fills it
    f = bv.best_file(video(2, 1920, 1080))
    assert f["link"].endswith("_uhd.mp4") and f["full"]
    # nothing big enough -> None; nothing over MAX_MB
    assert bv.best_file(video(3, 640, 360, files=[{"width": 640, "height": 360, "link": "https://videos.pexels.com/a",
                                                   "size": 10}])) is None
    huge = [{"width": 3840, "height": 2160, "link": "https://videos.pexels.com/b", "size": (bv.MAX_MB + 1) * 10 ** 6}]
    assert bv.best_file(video(4, 3840, 2160, files=huge)) is None


def test_candidate_rules():
    c = bv.candidate(video(10, slug="tired-man-rubbing-his-eyes"))
    assert c["title"] == "tired man rubbing his eyes"
    assert c["credit"] == {"author": "Jane Doe", "author_url": "https://www.pexels.com/@jane",
                           "page": "https://www.pexels.com/video/tired-man-rubbing-his-eyes-10/",
                           "license": bv.LICENSE, "video_id": 10}
    assert bv.candidate(video(11, dur=2)) is None            # too short
    assert bv.candidate(video(12, dur=20)) is None           # too long
    assert bv.candidate(video(13, slug="man-holding-a-gun")) is None
    assert bv.candidate(video(14, tags=["funeral"])) is None


def test_search_ranks_caches_and_hides_the_key():
    page = {"videos": [video(1, 1920, 1080, slug="landscape"), video(2, slug="portrait-light"),
                       video(3, dur=30), video(4, slug="portrait-b"), video(5, slug="portrait-c")]}
    s = FakeSession([page])
    got = bv.search("Man Drinking  Water", session=s)
    assert [c["id"] for c in got][:3] == [2, 4, 5] and got[-1]["id"] == 1 and 3 not in [c["id"] for c in got]
    call = s.calls[0]
    assert call["headers"] == {"Authorization": "test-key-not-real"}
    assert "test-key-not-real" not in json.dumps(call["params"]) and call["params"]["orientation"] == "portrait"
    # the same query is never asked twice; the key is in no file of the cache
    s2 = FakeSession([])
    assert [c["id"] for c in bv.search("man drinking water", session=s2)] == [c["id"] for c in got]
    assert s2.calls == []
    for root, _d, files in os.walk(bv.cache_dir()):
        for f in files:
            with open(os.path.join(root, f), "rb") as fh:
                assert b"test-key-not-real" not in fh.read()


def test_search_falls_back_to_any_orientation_and_blocks_words():
    s = FakeSession([{"videos": [video(1)]}, {"videos": [video(2, 3840, 2160), video(3)]}])
    got = bv.search("pouring water", session=s)
    assert len(s.calls) == 2 and "orientation" not in s.calls[1]["params"]
    assert {c["id"] for c in got} == {1, 2, 3}
    s = FakeSession([])
    assert bv.search("man with a gun", session=s) == [] and s.calls == []


def test_no_key_no_search(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY")
    monkeypatch.setattr(bv, "api_key", lambda: None)
    s = FakeSession([{"videos": [video(1)]}])
    assert bv.search("water", session=s) == [] and s.calls == []


def test_span_cuts_on_the_word_and_ends_with_the_clause():
    words = [(10.0, "they"), (10.4, "drink"), (10.8, "water"), (11.1, "all"), (11.3, "day."), (12.5, "Then")]
    assert bv.span(words, 10.4) == 1.5                      # clause ends at 11.9 -> 1.5 floor
    words = [(10.0, "drink"), (10.5, "a"), (11.0, "big"), (11.5, "glass"), (12.0, "of"), (12.2, "water,"), (13, "x")]
    assert bv.span(words, 10.0) == 2.8                      # to "water," + 0.4 + tail
    assert bv.span([(0, "running"), (1, "and"), (2, "running"), (3, "on")], 0) == 3.0   # capped
    assert bv.span(words, 10.0, clip_end=11.2) == 1.2       # never past the clip's end


def test_excerpt_start_is_centred_on_the_judged_frame():
    c = {"duration": 10, "frame_index": 7, "frame_of": 15}
    assert bv.excerpt_start(c, 2.0) == pytest.approx(4.0, abs=0.01)
    assert bv.excerpt_start({"duration": 10, "frame_index": 0, "frame_of": 15}, 2.0) == bv.EDGE
    assert bv.excerpt_start({"duration": 4, "frame_index": 14, "frame_of": 15}, 3.0) == pytest.approx(0.6)


def test_choose_one_call_per_clip(monkeypatch, tmp_path):
    calls = []

    def fake_ask(prompt, schema, attach, stage):
        calls.append((prompt, attach, stage))
        return {"moments": [{"k": 0, "pick": 1, "frame": "c", "why": "pours water"},
                            {"k": 1, "pick": -1, "frame": "a"}, {"k": 7, "pick": 0, "frame": "a"}]}
    monkeypatch.setattr(bv, "_ask", fake_ask)
    moments = [{"t": 1, "word": "pouring", "sentence": "pouring water", "query": "pouring water"},
               {"t": 5, "word": "running", "sentence": "go running", "query": "man running"}]
    cands = [[bv.candidate(video(1)), bv.candidate(video(2))], [bv.candidate(video(3))]]
    got = bv.choose(moments, cands, str(tmp_path / "j"), session=FakeSession([]))
    assert len(calls) == 1 and len(calls[0][1]) == 2 and calls[0][2] == "broll_video"
    assert got[0]["id"] == 2 and got[0]["frame_index"] == 11 and got[1] is None
    assert os.path.exists(calls[0][1][0])


def test_videos_for_clip_off_does_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("PLUS_BROLL_JSON", json.dumps({"video": False}))     # the job switched it off
    monkeypatch.setattr(bv, "plan_clip", lambda *a, **k: pytest.fail("must not search"))
    assert bv.videos_for_clip([{"t": 1, "word": "running", "kind": "action"}], [], 10, str(tmp_path)) == []


def test_videos_for_clip_places_actions_only(monkeypatch, tmp_path):
    monkeypatch.setenv("PLUS_BROLL_JSON", json.dumps({"video": True}))
    searched = []
    monkeypatch.setattr(bv, "search", lambda q, session=None: searched.append(q) or [bv.candidate(video(len(searched)))])
    monkeypatch.setattr(bv, "_ask", lambda p, s, a, st: {"moments": [{"k": 0, "pick": 0, "frame": "b"},
                                                                      {"k": 1, "pick": 0, "frame": "b"}]})
    cut = []
    monkeypatch.setattr(bv, "cut", lambda src, start, dur, out, fps=30: cut.append((src, start, dur)) or out)
    words = [(1.0, "drinking"), (1.5, "water."), (3.0, "a"), (3.2, "bottle"), (3.4, "and"), (5.6, "running.")]
    moments = [{"t": 1.0, "word": "drinking", "kind": "action", "query": "man drinking water"},
               {"t": 3.2, "word": "bottle", "kind": "object", "query": "bottle"},
               {"t": 5.6, "word": "running", "query": "man running"}]
    got = bv.videos_for_clip(moments, words, 8.0, str(tmp_path), session=FakeSession([]))
    assert searched == ["man drinking water", "man running"]
    assert [(p["t"], p["dur"]) for p in got] == [(1.0, 1.5), (5.6, 1.5)]
    assert got[0]["kind"] == "video" and got[0]["credit"]["author"] == "Jane Doe"
    # the file was fetched from the Pexels file host, once, into the cache
    files = os.listdir(os.path.join(bv.cache_dir(), "files"))
    assert files and all(f.endswith(".mp4") for f in files)


def test_download_is_cached_and_host_checked(tmp_path):
    c = bv.candidate(video(42))
    s = FakeSession([])
    p = bv.download(c, s)
    assert os.path.exists(p) and len(s.calls) == 1
    bv.download(c, s)
    assert len(s.calls) == 1
    c["file"] = {**c["file"], "link": "https://evil.example.com/x.mp4", "width": 1, "height": 2}
    with pytest.raises(ValueError):
        bv.download(c, s)


def test_cut_and_apply_commands():
    cmd = bv.cut_cmd("in.mp4", 2.5, 1.8, "out.mp4")
    assert cmd[cmd.index("-ss") + 1] == "2.500" and cmd[cmd.index("-t") + 1] == "1.800" and "-an" in cmd
    assert "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)'" in cmd[cmd.index("-vf") + 1]
    cmd = bv.apply_cmd("clip.mp4", [{"t": 1.0, "dur": 2.0, "path": "a.mp4"}, {"t": 6.24, "dur": 1.5, "path": "b.mp4"}],
                       "o.mp4")
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "between(t,1.000,3.000)" in fc and "between(t,6.240,7.740)" in fc and "setpts=PTS-STARTPTS+6.240/TB" in fc
    assert cmd[cmd.index("-map") + 1] == "[o2]"


def test_footage_moments_are_spaced():
    ms = [{"t": t, "word": "w", "kind": "action"} for t in (1.0, 3.0, 5.2, 6.0, 9.3)]
    assert [m["t"] for m in bv.spaced(ms, gap=4.0)] == [1.0, 5.2, 9.3]
    assert [m["t"] for m in bv.spaced(ms, gap=3.0)] == [1.0, 5.2, 9.3]
    assert [m["t"] for m in bv.spaced(ms, gap=2.0)] == [1.0, 3.0, 5.2, 9.3]


def test_spot_snaps_to_the_word(monkeypatch):
    monkeypatch.setattr(bv, "_ask", lambda p, s, a, st: {"moments": [
        {"t": 17.3, "word": "drive", "sentence": "let that person drive your car", "kind": "action",
         "query": "tired man driving at night"},
        {"t": 2.0, "word": "clock", "kind": "thing", "query": "wall clock"},
        {"t": 20.0, "word": "dying", "kind": "action", "query": "patient in hospital bed"}]})
    words = [(1.9, "the"), (2.1, "clock,"), (17.26, "drive"), (17.5, "your"), (20.0, "dying.")]
    got = bv.spot(words, "t")
    assert len(got) == 2                                    # never a picture on "dying"
    assert got[0] == {"t": 2.1, "word": "clock", "sentence": "", "kind": "object", "query": "wall clock"}
    assert got[1]["t"] == 17.26 and got[1]["kind"] == "action"


def test_black_and_white_footage_never_reaches_the_judge(monkeypatch, tmp_path):
    """10-oct-2026, clip 1: the « scientists » footage was black and white (its preview: saturation 0.000) and the judge
    took it. A candidate whose preview frames are all grey is dropped before the judge; the judge wants color footage."""
    import numpy as np
    from PIL import Image
    folder = os.path.join(bv.cache_dir(), "previews")
    os.makedirs(folder, exist_ok=True)
    grey, colour = bv.candidate(video(1)), bv.candidate(video(2))
    rng = np.random.default_rng(0)
    for c, tint in ((grey, None), (colour, (40, 120, 200))):
        for i, _url in bv.preview_frames(c):
            g = rng.integers(30, 220, (120, 90, 1)).astype(np.uint8)
            px = np.repeat(g, 3, -1) if tint is None else np.clip(g * 0.4 + np.array(tint), 0, 255).astype(np.uint8)
            Image.fromarray(px).save(os.path.join(folder, f"{c['id']}_{i}.jpg"))
    seen = []

    def fake_ask(prompt, schema, attach, stage):
        seen.append(prompt)
        return {"moments": [{"k": 0, "pick": 0, "frame": "b"}]}
    monkeypatch.setattr(bv, "_ask", fake_ask)
    moments = [{"t": 1, "word": "scientists", "sentence": "knowing scientists", "query": "scientist in a laboratory"}]
    got = bv.choose(moments, [[grey, colour]], str(tmp_path / "j"), session=FakeSession([]))
    assert got[0]["id"] == 2, "the grey one is gone: pick 0 is now the colour one"
    assert "color footage" in seen[0] and "black and white" in bv.JUDGE_PROMPT
    i0 = bv.preview_frames(grey)[0][0]
    p = os.path.join(folder, f"{grey['id']}_{i0}.jpg")
    assert bv.is_grey(p) is True and bv.is_grey(os.path.join(folder, f"{colour['id']}_{i0}.jpg")) is False
    # the dullest real colour shots of clips 1-2 (mean saturation 0.04-0.08) stay
    dull = tmp_path / "dull.jpg"
    Image.fromarray(np.clip(rng.integers(60, 120, (120, 90, 1)) + np.array([[[12, 6, 0]]]), 0, 255)
                    .astype(np.uint8)).save(dull)
    assert bv.saturation(str(dull))[0] > bv.GREY_SAT and bv.is_grey(str(dull)) is False
    assert bv.is_grey(str(tmp_path / "missing.jpg")) is None
