"""Putting a posted clip back in its project (app._mark_clip_published via=None)
must also clear the in-memory job, even when the mount refuses os.utime
(4-oct-2026: 12 clips came back on disk but stayed hidden in memory)."""
import json
import os

import app as app_module


def _job(tmp_path, monkeypatch):
    job = tmp_path / "job1"
    job.mkdir()
    stamp = {"via": "upload-post", "at": 1.0, "scheduled_for": "2026-10-05T08:00:00"}
    (job / "x_metadata.json").write_text(json.dumps({"shorts": [{"published": stamp}]}), encoding="utf-8")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setitem(app_module.jobs, "job1", {"result": {"clips": [{"published": dict(stamp)}]}})
    return job / "x_metadata.json"


def test_restore_clears_disk_and_memory(tmp_path, monkeypatch):
    meta = _job(tmp_path, monkeypatch)
    app_module._mark_clip_published("job1", 0, None)
    assert "published" not in json.loads(meta.read_text(encoding="utf-8"))["shorts"][0]
    assert "published" not in app_module.jobs["job1"]["result"]["clips"][0]


def test_a_refused_utime_no_longer_leaves_the_clip_hidden_in_memory(tmp_path, monkeypatch):
    meta = _job(tmp_path, monkeypatch)

    def refuse(*a, **k):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(os, "utime", refuse)
    app_module._mark_clip_published("job1", 0, None)
    assert "published" not in json.loads(meta.read_text(encoding="utf-8"))["shorts"][0]
    assert "published" not in app_module.jobs["job1"]["result"]["clips"][0]
