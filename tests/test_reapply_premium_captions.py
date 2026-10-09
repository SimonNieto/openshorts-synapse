"""A hook or an edit on a Clip Generator++ clip puts its own captions back (4-oct-2026): the edit style's (the house
Montserrat look) with the channel name, not the default caption profile."""
import json

import app as app_module
import main


def _job(tmp_path, monkeypatch, clip):
    job = tmp_path / "job1"
    job.mkdir()
    (job / "x_metadata.json").write_text(json.dumps({
        "transcript": {"segments": []}, "shorts": [clip],
        "source_video": "/app/downloads/b8e46c24-7f5e-48cf-8adc-c2d2677a241e_Joe Rogan Experience #2553 - Andrew Huberman-004.mkv",
        "plus_profile": {"id": "p1", "name": "Rogan", "niche": "Joe Rogan podcast"}}), encoding="utf-8")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(main, "viral_caption_clip",
                        lambda path, tr, s, e, style, watermark=None, clip=None, show=None: calls.append(("viral", style, watermark, show)) or "v.mp4")
    monkeypatch.setattr(main, "auto_caption_clip", lambda *a, **k: calls.append(("auto",)) or "a.mp4")
    import plus
    monkeypatch.setattr(plus, "get_profile", lambda pid: {"id": pid, "watermark": "@TheSynapseCut"})
    return calls


def test_a_plus_clip_gets_its_edit_style_captions_back(tmp_path, monkeypatch):
    calls = _job(tmp_path, monkeypatch, {"start": 1.0, "end": 30.0, "edit_style": "premium"})
    assert app_module._reapply_captions("job1", 0, "clip.mp4") == "v.mp4"
    # 9-oct-2026: the show for the one-word captions' « CREDIT: » line, the episode title's own wording first.
    assert calls == [("viral", "premium", "@TheSynapseCut", "Joe Rogan Experience")]


def test_a_clip_the_montage_re_cut_keeps_its_look_on_its_own_timeline(tmp_path, monkeypatch):
    # 5-oct-2026: a Clip Generator++ clip has a recipe (montage.py): the edit style's captions, from 0 to its length.
    seen = []
    calls = _job(tmp_path, monkeypatch, {"start": 1.0, "end": 30.0, "edit_style": "premium",
                                         "recipe": {"v": 1, "segments": [{"start": 1.0, "end": 10.0},
                                                                         {"start": 12.0, "end": 30.0}]}})
    monkeypatch.setattr(main, "viral_caption_clip",
                        lambda path, tr, s, e, style, watermark=None, clip=None, show=None: seen.append((s, e)) or "v.mp4")
    assert app_module._reapply_captions("job1", 0, "clip.mp4") == "v.mp4"
    assert seen == [(0.0, 27.0)] and calls == []


def test_a_classic_clip_keeps_the_default_captions(tmp_path, monkeypatch):
    calls = _job(tmp_path, monkeypatch, {"start": 1.0, "end": 30.0})
    assert app_module._reapply_captions("job1", 0, "clip.mp4") == "a.mp4"
    assert calls == [("auto",)]
