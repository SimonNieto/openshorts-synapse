"""The B-roll gallery (broll_gallery, 4-oct-2026): the drawn pictures of the jobs' traces and of the drawn bench, kept or
refused, each once, with the owner's 👍 / 👎, why and what to change; the image route serves nothing outside them."""
import json
import os

import pytest

import broll_gallery as g


@pytest.fixture
def out(tmp_path):
    clip = tmp_path / "_broll_trace" / "2026-10-04_abcdef12" / "x_clip_1"
    clip.mkdir(parents=True)
    for name in ("broll_0.jpg", "refused_1.jpg"):
        (clip / name).write_bytes(b"jpg")
    (clip / "trace.json").write_text(json.dumps({"clip": "Meth strength", "pictures": [
        {"file": "broll_0.jpg", "said": "carrying fridges", "idea": "an absurd load", "prompt": "A man. STYLE",
         "seed": 1, "verdict": "keep", "kept": True, "layout": "hero"},
        {"file": "refused_1.jpg", "said": "a rope", "idea": "x", "prompt": "A rope. STYLE", "seed": 2,
         "verdict": "refused", "why": "a strap", "kept": False}]}), encoding="utf-8")
    bench = tmp_path / "_test_broll" / "short" / "style_da2" / "e9_clip3"
    (bench / "refused").mkdir(parents=True)
    (bench / "01_13s.jpg").write_bytes(b"jpg")
    (bench / "refused" / "02_17s.jpg").write_bytes(b"jpg")
    (bench / "prompts.json").write_text(json.dumps([
        {"file": "01_13s.jpg", "clip": "Patient", "sentence": "hello", "idea": "a voice", "prompt": "P1", "seed": 5},
        {"file": None, "refused_file": "refused/02_17s.jpg", "clip": "Patient", "sentence": "s", "idea": "i",
         "prompt": "P2", "seed": 6, "verifier": "refuse", "verifier_reason": "gore"}]), encoding="utf-8")
    final = tmp_path / "_test_broll" / "short" / "style_da2" / "e9_clip3_final"
    final.mkdir()
    (final / "01_13s.jpg").write_bytes(b"jpg")
    (final / "prompts.json").write_text(json.dumps([
        {"file": "01_13s.jpg", "clip": "Patient", "sentence": "hello", "idea": "a voice", "prompt": "P1", "seed": 5}]),
        encoding="utf-8")
    return str(tmp_path)


def test_every_picture_once_jobs_first_kept_and_refused(out):
    pics = g.pictures(out)
    assert [(p["source"], p["status"], p["said"]) for p in pics] == [
        ("job", "kept", "carrying fridges"), ("job", "refused", "a rope"), ("bench", "kept", "hello"),
        ("bench", "refused", "s")]                                    # the copy in *_final is not shown twice
    assert pics[1]["why"] == "a strap" and pics[3]["why"] == "gore" and pics[0]["layout"] == "hero"
    assert all(p["feedback"] is None for p in pics)


def test_the_image_route_serves_the_gallery_only(out):
    pid = g.pictures(out)[0]["id"]
    assert g.path_of(out, pid).endswith("broll_0.jpg")
    for rel in ("../secret.jpg", "_lessons/x.jpg", "_broll_trace/2026-10-04_abcdef12/x_clip_1/trace.json"):
        assert g.path_of(out, g._id(rel)) is None
    assert g.path_of(out, "%%%") is None


def test_a_verdict_with_why_and_change_and_the_last_one_wins(out):
    pid = g.pictures(out)[1]["id"]
    fb = g.record(out, pid, "down", why="on ne comprend pas", change="la corde, enlève-la")
    assert fb["verdict"] == "down" and fb["change"] == "la corde, enlève-la"
    g.record(out, pid, "up", why="finalement oui")
    assert g.pictures(out)[1]["feedback"]["verdict"] == "up"
    assert g.record(out, pid, "") is None and g.pictures(out)[1]["feedback"] is None     # cleared
    lines = open(os.path.join(out, g.FEEDBACK_FILE), encoding="utf-8").read().splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["said"] == "a rope"


def test_an_unknown_picture_or_verdict_is_refused(out):
    with pytest.raises(ValueError):
        g.record(out, g._id("_broll_trace/nope.jpg"), "up")
    with pytest.raises(ValueError):
        g.record(out, g.pictures(out)[0]["id"], "maybe")


def test_an_empty_output_is_an_empty_gallery(tmp_path):
    assert g.pictures(str(tmp_path)) == []
