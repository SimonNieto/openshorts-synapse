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
        "plus_profile": {"id": "p1", "name": "Rogan"}}), encoding="utf-8")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(main, "viral_caption_clip",
                        lambda path, tr, s, e, style, watermark=None, clip=None: calls.append(("viral", style, watermark)) or "v.mp4")
    monkeypatch.setattr(main, "auto_caption_clip", lambda *a, **k: calls.append(("auto",)) or "a.mp4")
    import plus
    monkeypatch.setattr(plus, "get_profile", lambda pid: {"id": pid, "watermark": "@TheSynapseCut"})
    return calls


def test_a_plus_clip_gets_its_edit_style_captions_back(tmp_path, monkeypatch):
    calls = _job(tmp_path, monkeypatch, {"start": 1.0, "end": 30.0, "edit_style": "premium"})
    assert app_module._reapply_captions("job1", 0, "clip.mp4") == "v.mp4"
    assert calls == [("viral", "premium", "@TheSynapseCut")]


def test_a_classic_clip_keeps_the_default_captions(tmp_path, monkeypatch):
    calls = _job(tmp_path, monkeypatch, {"start": 1.0, "end": 30.0})
    assert app_module._reapply_captions("job1", 0, "clip.mp4") == "a.mp4"
    assert calls == [("auto",)]
