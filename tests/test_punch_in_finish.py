"""punch_in.finish: a join a drawing covers needs no tight frame (the drawing hides it), an uncovered one
gets its tight frame — which is why the drawings are not kept off the joins (montage.broll_block, 5-oct-2026)."""
import punch_in


def _finish(monkeypatch, broll):
    monkeypatch.setattr(punch_in, "_probe", lambda p: (1080, 1920, 29.97))
    monkeypatch.setattr(punch_in, "_clip_duration", lambda p: 30.0)
    monkeypatch.setattr(punch_in, "changes_on_screen", lambda p: [])
    monkeypatch.setattr(punch_in, "plan_tight", lambda *a, **k: [])
    monkeypatch.setattr(punch_in, "face_in", lambda *a, **k: None)
    monkeypatch.setattr(punch_in, "tight_box", lambda *a, **k: (900, 1600, 90, 160))
    cut = []
    monkeypatch.setattr(punch_in, "apply_tight", lambda src, out, windows: cut.extend(windows))
    report = {"hide_windows": [[10.0, 12.5], [20.0, 22.5]],
              "joins": [{"t": 10.0, "verdict": "hide"}, {"t": 20.0, "verdict": "hide"}]}
    got = punch_in.finish("c.mp4", "o.mp4", {"broll": broll}, montage_report=report, log=lambda *a: None)
    return [(w["a"], w["b"]) for w in got]


def test_a_drawing_over_the_join_replaces_its_tight_frame(monkeypatch):
    got = _finish(monkeypatch, [{"t": 9.0, "dur": 2.5}])          # covers the join at 10.0
    assert got == [(20.0, 22.5)], got


def test_an_uncovered_join_keeps_its_tight_frame_cut_short_by_a_later_drawing(monkeypatch):
    got = _finish(monkeypatch, [{"t": 11.0, "dur": 2.5}])          # starts after the join at 10.0
    assert (10.0, 11.0) in got and (20.0, 22.5) in got, got
