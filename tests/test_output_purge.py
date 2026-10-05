"""What the app deletes on its own (5-oct-2026).

- On a self-hosted box, nothing any more (app.AUTO_PURGE off): the user deletes old projects herself from the app.
  cleanup_jobs keeps only its in-memory housekeeping.
- With AUTO_PURGE (the billed cloud, or AUTO_PURGE=1), the sweeps run as before — but on job folders only: until
  then they took every folder of output/ older than JOB_RETENTION_SECONDS without a .keep — _ai_cache (answers
  already paid for), _jury (the hook notes), _lineup, _stepup… included."""
import json
import os
import time

import pytest

import app as app_module

DAY = 86400
JOB = "b8e46c24-7f5e-48cf-8adc-c2d2677a241e"
OTHER_JOB = "e9e44926-73a8-41f0-a506-8f1143df2aab"
STORES = ("_ai_cache", "_jury", "_lineup", "_stepup", "_test_broll", "_broll_trace", "__pycache__", ".hidden")


def _folder(root, name, age_days, size=10, keep=False):
    d = root / name
    d.mkdir()
    (d / "data.bin").write_bytes(b"\x00" * size)
    if keep:
        (d / ".keep").write_text("")
    t = time.time() - age_days * DAY
    os.utime(d, (t, t))
    return d


@pytest.fixture
def output(tmp_path, monkeypatch):
    out = tmp_path / "output"
    out.mkdir()
    thumbs = out / "thumbnails"
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(out))
    monkeypatch.setattr(app_module, "THUMBNAILS_DIR", str(thumbs))
    monkeypatch.setattr(app_module, "JOB_RETENTION_SECONDS", 8 * DAY)
    return out


def test_self_hosted_ships_without_automatic_deletion():
    assert app_module.BILLING_ENABLED is False and app_module.AUTO_PURGE is False


@pytest.fixture
def box(output, tmp_path, monkeypatch):
    """An old job, a store, a young job whose retained source is old, an old upload, an expired agent upload
    slot, and the size caps recorded instead of run."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(uploads))
    monkeypatch.setattr(app_module, "SOURCE_RETENTION_SECONDS", 1 * DAY)
    old = _folder(output, JOB, age_days=30)
    store = _folder(output, "_ai_cache", age_days=30)
    young = _folder(output, OTHER_JOB, age_days=2)
    (young / "x_metadata.json").write_text(json.dumps({"source_video": "source.mp4", "shorts": []}))
    source = young / "source.mp4"
    source.write_bytes(b"\x00")
    t = time.time() - 3 * DAY
    os.utime(source, (t, t))
    os.utime(young, (time.time() - 2 * DAY,) * 2)
    upload = uploads / "old_upload.mp4"
    upload.write_bytes(b"\x00")
    os.utime(upload, (time.time() - 30 * DAY,) * 2)
    slot_file = uploads / "agent_slot.mp4"
    slot_file.write_bytes(b"\x00")
    monkeypatch.setitem(app_module.pending_uploads, "slot1",
                        {"created": time.time() - app_module.UPLOAD_TTL_SECONDS - 10, "path": str(slot_file)})
    caps = []
    monkeypatch.setattr(app_module, "_enforce_output_size_cap", lambda: caps.append("output"))
    monkeypatch.setattr(app_module, "_enforce_uploads_size_cap", lambda: caps.append("uploads"))
    return {"old": old, "store": store, "source": source, "upload": upload, "slot_file": slot_file, "caps": caps}


def test_off_nothing_is_deleted(box, monkeypatch):
    monkeypatch.setattr(app_module, "AUTO_PURGE", False)
    app_module._cleanup_pass(time.time())
    for name in ("old", "store", "source", "upload", "slot_file"):
        assert box[name].exists(), f"{name} deleted with AUTO_PURGE off"
    assert box["caps"] == [], "no size cap trim"
    assert "slot1" not in app_module.pending_uploads, "the in-memory housekeeping still runs"


def test_on_the_sweeps_run_as_before(box, monkeypatch):
    monkeypatch.setattr(app_module, "AUTO_PURGE", True)
    app_module._cleanup_pass(time.time())
    assert not box["old"].exists() and not box["source"].exists() and not box["upload"].exists()
    assert not box["slot_file"].exists() and "slot1" not in app_module.pending_uploads
    assert box["caps"] == ["output", "uploads"]
    assert box["store"].exists(), "never a store, even on"


def test_which_folders_are_jobs(output):
    assert app_module._is_job_folder(JOB) and app_module._is_job_folder("u2515ins-0000-4000-8000-000000002515")
    for name in STORES + ("thumbnails", ""):
        assert not app_module._is_job_folder(name), name


def test_the_age_sweep_spares_the_stores(output, monkeypatch):
    for name in STORES:
        _folder(output, name, age_days=30)
    _folder(output, "thumbnails", age_days=30)
    old = _folder(output, JOB, age_days=30)
    kept = _folder(output, OTHER_JOB, age_days=30, keep=True)
    young = _folder(output, "aaaaaaaa-0000-4000-8000-000000000001", age_days=2)
    monkeypatch.setitem(app_module.jobs, JOB, {"status": "completed"})
    assert app_module._purge_old_jobs(time.time()) == [JOB]
    assert not old.exists() and JOB not in app_module.jobs
    assert kept.exists() and young.exists() and (output / "thumbnails").exists()
    for name in STORES:
        assert (output / name / "data.bin").exists(), f"{name} must survive the age sweep"


def test_the_size_cap_spares_the_stores(output, monkeypatch):
    monkeypatch.setattr(app_module, "OUTPUT_MAX_GB", 1)
    big_store = _folder(output, "_ai_cache", age_days=60, size=600)
    old = _folder(output, JOB, age_days=20, size=600)
    newer = _folder(output, OTHER_JOB, age_days=1, size=100)
    monkeypatch.setattr(app_module, "_dir_size",
                        lambda p: sum(f.stat().st_size for f in __import__("pathlib").Path(p).rglob("*")
                                      if f.is_file()) * 1024 ** 2)   # 1 byte here = 1 MB for the cap
    app_module._enforce_output_size_cap()
    assert big_store.exists(), "the oldest folder is a store, not a job: never trimmed"
    assert not old.exists(), "the oldest job goes first"
    assert newer.exists(), "back under the cap: the trim stops"
