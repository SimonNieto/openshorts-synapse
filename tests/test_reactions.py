"""Reactions in the holes of a clip (5-oct-2026, the image study's ideas 1 and 4): up to three, spaced from
every other change, never the same listener second twice in a job."""
import punch_in
import reactions


def _sentences(n, every=2.5):
    """n sentences, one every ``every`` s, each ending on a strong word."""
    words = []
    for k in range(n):
        t = 0.5 + k * every
        words.append({"text": "Something", "start": t, "end": t + 0.6})
        words.append({"text": "remarkable.", "start": t + 0.6, "end": t + 1.4})
    return words


class TestInsertionPoints:
    def test_with_the_montage_up_to_three_in_the_holes(self, monkeypatch):
        monkeypatch.setattr(reactions, "SMOOTH", True)
        pts = reactions.insertion_points(_sentences(16), 40.0, events=[])
        assert 1 <= len(pts) <= reactions.SMOOTH_MAX_N
        assert len(pts) == 3
        assert all(b - a >= reactions.SMOOTH_GAP - 1e-6 for a, b in zip(pts, pts[1:]))

    def test_never_close_to_another_change(self, monkeypatch):
        monkeypatch.setattr(reactions, "SMOOTH", True)
        events = [(10.0, 12.5), (22.0, 22.0)]
        pts = reactions.insertion_points(_sentences(16), 40.0, events=events)
        for p in pts:
            assert punch_in.spaced(p, p + reactions.REACT_LEN, events)

    def test_without_the_montage_nothing_changes(self, monkeypatch):
        monkeypatch.setattr(reactions, "SMOOTH", True)
        assert len(reactions.insertion_points(_sentences(16), 40.0)) == 2


class TestOneJob:
    def test_a_listener_moment_taken_once_is_never_taken_again(self):
        reactions.reset_job()
        used = [(671.0, 672.2)]
        assert reactions._overlaps_used({"start": 671.5, "dur": 1.2}, used)
        assert reactions._overlaps_used({"start": 670.0, "dur": 1.2}, used)
        assert not reactions._overlaps_used({"start": 672.2, "dur": 1.2}, used)
        assert reactions._JOB_USED == []
