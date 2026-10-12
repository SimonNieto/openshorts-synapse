"""Who is on screen (12-oct-2026, audit of JRE #1109): the first picture is the one who speaks, a reaction shows
someone LISTENING (by the voice), never a moment of the clip itself, a pause ends a sentence in an unpunctuated
transcript, and a change of person is a dry cut. No AI call, no token."""
import os
import subprocess
import tempfile

import numpy as np
import pytest

montage = pytest.importorskip("montage")
import reactions as R  # noqa: E402
import reframe_v2  # noqa: E402


# --- the first picture ---------------------------------------------------------------------------------

class TestOpenHold:
    def test_a_flash_of_the_other_camera_is_covered(self):
        # c08: 0.63 s of Joe before the source cuts to Walker, who is speaking.
        segs = [{"start": 1974.8, "end": 1981.0}, {"start": 1981.1, "end": 1986.9}]
        assert montage.open_hold([0.63, 6.7], segs) == pytest.approx(0.67)
        assert montage.open_hold([1.2, 6.7], segs) is None          # a real first shot stays
        assert montage.open_hold([], segs) is None
        assert montage.open_hold([0.02, 3.0], segs) is None          # no cut there in fact (the very first frame)
        assert montage.open_hold([0.63], [{"start": 0.0, "end": 0.7}]) is None   # the cut is past the first piece

    def test_the_picture_is_held_the_sound_runs(self):
        segs = [{"start": 100.0, "end": 106.0}, {"start": 107.0, "end": 110.0}]
        cmd = " ".join(montage.cut_command("src.mp4", segs, "out.mp4", fps=60000 / 1001, hold=0.67))
        # 40 whole frames at 59.94 (0.667 s), the rate set on the link before tpad: the bench of 12-oct had the
        # picture 0.4 s ahead of the voice when tpad guessed the rate.
        assert ("trim=start=1.667333:end=7.000000,setpts=PTS-STARTPTS,fps=60000/1001,"
                "tpad=start_mode=clone:start=40[v0]") in cmd
        assert "[0:a]atrim=start=1.000000:end=7.000000" in cmd           # the sound from the very start
        assert "tpad" not in " ".join(montage.cut_command("src.mp4", segs, "out.mp4", fps=60000 / 1001))
        assert "tpad" not in " ".join(montage.cut_command("src.mp4", segs, "out.mp4", hold=0.67))  # no rate, no hold

    def test_the_report_says_it(self):
        assert "next shot's first frame" in montage.describe({"saved": 1.0, "joins": [], "open_hold": 0.67})


# --- reactions -----------------------------------------------------------------------------------------

SR = R.VOICE_SR


def _voice(freqs, seconds, seed):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    sig = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28)) / (k + 1) for k, f in enumerate(freqs))
    return (0.2 * sig + 0.01 * rng.standard_normal(len(t))).astype("float32")


LOW, HIGH = (140, 280, 420, 560), (1200, 1900, 2600, 3300)


def _talk(spans):
    """Words every 0.3 s over each span."""
    return [{"text": "w", "start": a + k * 0.3, "end": a + k * 0.3 + 0.25}
            for a, b in spans for k in range(int((b - a) / 0.3))]


class TestVoice:
    def setup_method(self):
        # 0-10 s person 0's voice (low), 10-20 s person 1's (high), 20-24 s low again.
        self.audio = np.concatenate([_voice(LOW, 10, 1), _voice(HIGH, 10, 2), _voice(LOW, 4, 3)])
        self.words = _talk([(0, 10), (10, 20), (20, 24)])

    def test_two_voices_are_told_apart(self):
        a = R.voice_print(self.audio, 0.0, 0, 9, self.words)
        b = R.voice_print(self.audio, 0.0, 10, 19, self.words)
        a2 = R.voice_print(self.audio, 0.0, 20, 24, self.words)
        assert R.voice_gap(a, a2) < 0.5 * R.voice_gap(a, b)

    def test_too_little_speech_gives_no_print(self):
        assert R.voice_print(self.audio, 0.0, 0, 0.4, self.words) is None
        assert R.voice_print(None, 0.0, 0, 9, self.words) is None

    def test_a_listener_is_someone_the_voice_is_not(self):
        shots = [{"start": 0, "end": 9, "speech": 1.0, "person": 0},
                 {"start": 10, "end": 19, "speech": 1.0, "person": 1}]
        for s in shots:
            s["voice"] = R.voice_print(self.audio, 0.0, s["start"], s["end"], self.words)
        voices = R.speaking_voices(shots)
        assert sorted(voices) == [0, 1]
        heard_low = R.voice_print(self.audio, 0.0, 20.5, 23.5, self.words)
        # Person 1 on screen while the low voice talks: a listener.
        assert R.heard_voice_is_other(heard_low, 1, voices)[0] is True
        # Person 0 on screen while their own voice talks: the speaker, never a "reaction" (Joe behind his mic).
        assert R.heard_voice_is_other(heard_low, 0, voices)[0] is False
        # Unknown: no voice heard, nobody else's voice, a person never seen speaking.
        assert R.heard_voice_is_other(None, 1, voices)[0] is None
        assert R.heard_voice_is_other(heard_low, 1, {1: voices[1]})[0] is None
        assert R.heard_voice_is_other(heard_low, 7, voices)[0] is None

    def test_short_shots_do_not_give_a_speaking_voice(self):
        shots = [{"start": 0, "end": 2.5, "speech": 1.0, "person": 0, "voice": np.zeros(40)},
                 {"start": 10, "end": 19, "speech": 0.3, "person": 1, "voice": np.zeros(40)}]
        assert R.speaking_voices(shots) == {}

    def test_people_by_look(self):
        rng = np.random.default_rng(0)
        joe, walker = rng.random(768).astype("float32"), rng.random(768).astype("float32") ** 6
        joe2 = (joe + 0.01 * rng.random(768)).astype("float32")
        shots = [{"look": joe}, {"look": walker}, {"look": joe2}, {"look": None}]
        assert R.people(shots) == 2
        assert [s["person"] for s in shots] == [0, 1, 0, None]


class TestWhereReactionsGo:
    def test_never_a_moment_of_the_clip_itself(self):
        cands = [{"start": 452.66, "dur": 1.2}, {"start": 380.0, "dur": 1.2}, {"start": 499.5, "dur": 1.2}]
        own = [(430.0, 470.0), (471.0, 500.0)]
        assert [c["start"] for c in R.outside(cands, own)] == [380.0]

    def test_an_unpunctuated_transcript_still_has_sentence_ends(self):
        # c05 / c08 / c09 of JRE #1109: no full stop in the words, no reaction at all before.
        words = []
        t = 0.0
        for k in range(60):
            words.append({"text": "word", "start": t, "end": t + 0.25})
            t += 0.3 + (0.5 if k % 12 == 11 else 0.0)        # a 0.55 s pause every 12 words
        assert R.insertion_points(words, t, events=[])
        # A punctuated transcript keeps its full stops only.
        words[11]["text"] = "word."
        ends = R.insertion_points(words, t, max_n=5, events=[])
        assert all(abs(p - 0.08 - words[11]["end"]) < 1e-6 for p in ends)

    def test_a_reaction_is_a_dry_cut(self):
        assert R.REACT_DISSOLVE is False


# --- a change of person is a dry cut -------------------------------------------------------------------------

def _two_colours(path, first, second):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={first}:s=320x180:d=1:r=25",
                    "-f", "lavfi", "-i", f"color=c={second}:s=320x180:d=1:r=25",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-pix_fmt", "yuv420p", path],
                   check=True)


class TestDryCut:
    def test_same_person_or_not(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "v.mp4")
            _two_colours(p, "0x8a5a3c", "0x2a3f66")      # brown shirt, then denim
            assert reframe_v2.same_person(p, 0.5, 1.5, 0, 0, 100, 180, 320, 180) is False
            q = os.path.join(d, "w.mp4")
            _two_colours(q, "0x8a5a3c", "0x8b5b3d")      # the same, from another angle
            assert reframe_v2.same_person(q, 0.5, 1.5, 0, 50, 100, 180, 320, 180) is True
            assert reframe_v2.same_person(os.path.join(d, "none.mp4"), 0.5, 1.5, 0, 0, 100, 180, 320, 180) is False


class TestPausesFromTheSource:
    def test_the_montage_tightened_pauses_still_end_sentences(self):
        # Source: a 0.6 s pause after word 11; the montage left 0.12 s of it in the clip.
        words_abs = [{"text": "w", "start": 100 + k * 0.3 + (0.6 if k >= 12 else 0), "end": 100 + k * 0.3 + 0.25
                      + (0.6 if k >= 12 else 0)} for k in range(40)]
        segs = [{"start": 100.0, "end": 103.6}, {"start": 104.08, "end": 112.6}]
        import recut
        rel = [{"text": w["text"], "start": recut.source_to_clip(segs, w["start"]),
                "end": recut.source_to_clip(segs, w["start"]) + 0.25} for w in words_abs]
        assert max(rel[k + 1]["start"] - rel[k]["end"] for k in range(len(rel) - 1)) < R.PAUSE_END
        R.source_gaps(rel, words_abs, lambda t: recut.clip_to_source(segs, t))
        assert rel[11]["gap"] >= R.PAUSE_END and rel[3]["gap"] < R.PAUSE_END
        pts = R.insertion_points(rel, 11.0, events=[])
        assert pts and abs(pts[0] - 0.08 - rel[11]["end"]) < 1e-6


class TestHoldKeepsTheVoiceInStep:
    """A real cut (ffmpeg): after the held first picture, every frame is the source's at clip_to_source(t) —
    the bench of 12-oct-2026 had the picture 0.4 s ahead of the voice until the first join."""

    def test_frames_after_the_hold_are_on_time(self):
        import recut
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "src.mp4"), os.path.join(d, "out.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=60000/1001:d=10",
                            "-f", "lavfi", "-i", "sine=f=440:d=10", "-c:v", "libx264", "-g", "30", "-pix_fmt",
                            "yuv420p", "-c:a", "aac", "-shortest", src], check=True)
            segs = [{"start": 1.0, "end": 4.0}, {"start": 5.0, "end": 8.0}]
            fps = 60000 / 1001
            r = subprocess.run(montage.cut_command(src, segs, out, normalize=False, fps=fps, hold=0.67),
                               capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[-400:]

            def frame(path, t, accurate=True):
                cmd = (["ffmpeg", "-v", "error", "-i", path, "-ss", f"{t:.4f}"] if accurate
                       else ["ffmpeg", "-v", "error", "-ss", f"{t:.4f}", "-i", path])
                raw = subprocess.run(cmd + ["-frames:v", "1", "-vf", "scale=80:45,format=gray", "-f", "rawvideo",
                                            "-"], capture_output=True).stdout
                return np.frombuffer(raw, dtype=np.uint8).astype("float32")

            for t in (1.0, 2.2, 4.5):
                got = frame(out, t)
                on_time = float(np.mean(np.abs(got - frame(src, recut.clip_to_source(segs, t)))))
                early = float(np.mean(np.abs(got - frame(src, recut.clip_to_source(segs, t) + 0.4))))
                assert on_time < 2.0 and on_time < early / 3, (t, on_time, early)
