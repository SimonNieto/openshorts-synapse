"""B-roll v20 « la fiche » (3-oct-2026): the whole chain on fakes — the editor's specs, the code's prompt, the blind
check and decide(), the hero's takes, the alternative, the reserve under the minimum. No model, no ComfyUI."""
import os

import pytest
from PIL import Image

import broll
import broll_check
import broll_spec
import broll_v20

SPEC = {"kind": "thing", "subject": "a glass of water", "subject_words": "water", "count": "1",
        "state": "standing still", "setting": "a kitchen table", "details": "clear glass, drops on the side",
        "people": "none", "person": "none", "shot": "medium", "literal": "literal",
        "mood": {}, "alt": {"kind": "thing", "subject": "a tap running", "subject_words": "water", "count": "1",
                            "state": "running", "setting": "a sink", "details": "steel tap", "people": "none",
                            "person": "none", "shot": "close", "literal": "literal", "mood": {}}}


def _m(t, hero=False, **spec):
    return {"t": t, "anchor": "water", "said": "a glass of water", "dur": 2.0, "hero": hero, "mood": {},
            "spec": {**SPEC, **spec}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    broll.FILTERS.clear()
    monkeypatch.setattr(broll, "_frame_sheets", lambda clip_path, tmp: [])
    monkeypatch.setattr(broll, "episode_drawing", lambda: "A gouache drawing.")
    yield
    broll.FILTERS.clear()


def _render(tmp_path, made):
    def render(text, out, layout):
        Image.new("RGB", (64, 64)).save(out)
        made.append((os.path.basename(out), layout, text))
        return out, len(made)
    return render


def _ok(subject="yes", links=True, look=4):
    return {"sees": "a glass", "links": links, "look": look,
            "answers": {"q_subject": subject, "q_count": "1", "q_people": "0", "q_text": "no",
                        "q_medium": "photograph", "q_unsafe": "no", "q_body_photo": "no"}}


def _run(monkeypatch, tmp_path, moments, reserves, verdicts):
    """``verdicts``: file basename -> check result (missing: a clean one)."""
    monkeypatch.setattr(broll_spec, "plan_specs", lambda *a, **k: (moments, reserves))
    monkeypatch.setattr(broll_check, "check", lambda cands, words, **k: {
        os.path.basename(c["file"]): verdicts.get(os.path.basename(c["file"]), _ok()) for c in cands})
    made = []
    kept, pictured = broll_v20.run("clip.mp4", {}, [], None, 0, 30, 4, [], 1.0, 2.0, 2.0, (), None, str(tmp_path),
                                   _render(tmp_path, made))
    return kept, pictured, made


def test_the_prompt_is_the_codes_and_a_clean_picture_is_kept(monkeypatch, tmp_path):
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {})
    assert len(kept) == 2 and all(c["verdict"] == "keep" for c in kept)
    assert made[0][2].index("glass of water") < 120                  # the subject opens the prompt
    assert kept[0]["m"]["prompt"] == made[0][2] and kept[0]["m"]["art"] is True


def test_the_hero_takes_then_the_best_stays(monkeypatch, tmp_path):
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0, hero=True), _m(12.0)], [],
                          {"broll_0.jpg": _ok(look=2)})
    assert [m[0] for m in made][:2] == ["broll_0.jpg", "broll_0_t2.jpg"] and made[0][1] == "hero"
    assert kept[0]["file"].endswith("broll_0_t2.jpg")


def test_a_wrong_subject_is_rendered_again_and_no_link_takes_the_alternative(monkeypatch, tmp_path):
    # only a vision that does not link is another idea (any other kind is kept, its subject being said)
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0, kind="vision")], [],
                          {"broll_0.jpg": _ok(subject="no"), "broll_1.jpg": _ok(links=False)})
    names = [m[0] for m in made]
    assert "broll_0_v2.jpg" in names and "broll_1_alt.jpg" in names
    alt = next(c for c in kept if c["k"] == 1)
    assert alt["m"]["spec"]["subject"] == "a tap running" and "tap running" in alt["m"]["prompt"]
    assert broll.FILTERS["check: no link"] == 1 and broll.FILTERS["check: wrong subject"] == 1


def test_a_non_vision_that_does_not_link_is_kept_without_an_alternative(monkeypatch, tmp_path):
    kept, _p, made = _run(monkeypatch, tmp_path, [_m(5.0), _m(12.0)], [], {"broll_1.jpg": _ok(links=False)})
    assert [m[0] for m in made] == ["broll_0.jpg", "broll_1.jpg"] and len(kept) == 2
    assert broll.FILTERS["check: no cold link (kept: its subject is said)"] == 1 and "check: no link" not in broll.FILTERS


def test_under_the_minimum_a_reserve_is_made(monkeypatch, tmp_path):
    unsafe = {**_ok(), "answers": {**_ok()["answers"], "q_unsafe": "yes"}}
    kept, pictured, made = _run(monkeypatch, tmp_path, [_m(5.0, alt=None), _m(12.0, alt=None)], [_m(20.0)],
                                {"broll_0.jpg": unsafe, "broll_1.jpg": unsafe})
    assert len(kept) == 1 and kept[0]["file"].endswith("broll_2r.jpg") and len(pictured) == 3
    assert broll.LAST_PICTURED[2]["t"] == 20.0 and broll.FILTERS["check: unsafe"] == 2


def test_a_picture_nobody_checked_is_not_kept(monkeypatch, tmp_path):
    monkeypatch.setattr(broll_spec, "plan_specs", lambda *a, **k: ([_m(5.0)], []))
    monkeypatch.setattr(broll_check, "check", lambda cands, words, **k: {})
    kept, _p = broll_v20.run("clip.mp4", {}, [], None, 0, 30, 4, [], 1.0, 2.0, 2.0, (), None, str(tmp_path),
                             _render(tmp_path, []))
    assert kept == [] and broll.FILTERS["check: not checked"] == 1


def test_add_broll_branches_on_the_chain():
    src = open(os.path.join(os.path.dirname(broll.__file__), "broll.py"), encoding="utf-8").read()
    assert 'cfg.get("chain") == "spec"' in src and "broll_v20.run(" in src and "raw=True" in src
