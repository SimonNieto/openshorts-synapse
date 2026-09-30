"""Audio cues for the scoring pass (audio_signals.py, AUDIO_SIGNALS=1).

The scoring read the transcript only. These are the few numbers per window
that say how the words were delivered; they must cost almost nothing and
never fail a job."""
import json
import shutil
import wave

import pytest

np = pytest.importorskip("numpy")
import audio_signals  # noqa: E402
import playbook  # noqa: E402


def _words(*spans):
    return [{"w": f"w{i}", "s": s, "e": e} for i, (s, e) in enumerate(spans)]


class TestWindowFeatures:
    def test_flat_speech_at_the_usual_level(self):
        rms = np.full(40, 1000.0)                          # 20 s, steady
        words = _words(*[(i * 0.5, i * 0.5 + 0.45) for i in range(40)])
        cues = audio_signals.window_features(rms, 1000.0, words, 0.0, 20.0)
        assert cues == {"loud": 1.0, "peak": 1.0, "var": 0.0, "wps": 2.0, "react": 0.0, "pause": 0.1}

    def test_a_lively_window_shows_in_var_and_peak(self):
        rms = np.array([500.0, 3000.0] * 20)
        cues = audio_signals.window_features(rms, 1000.0, [], 0.0, 20.0)
        assert cues["peak"] == 3.0 and cues["var"] > 0.6 and cues["loud"] == 1.75

    def test_sound_between_the_words_is_a_reaction(self):
        # words until 5 s, a 3 s gap where the room is loud (laughter), words again
        rms = np.full(40, 1000.0)
        rms[10:16] = 1500.0
        words = _words(*[(i * 0.5, i * 0.5 + 0.45) for i in range(10)], *[(8.0 + i * 0.5, 8.45 + i * 0.5) for i in range(10)])
        cues = audio_signals.window_features(rms, 1000.0, words, 0.0, 20.0)
        assert cues["react"] == 1.5 and cues["pause"] == 3.0
        quiet = rms.copy()
        quiet[10:16] = 20.0                                # the same gap, silent: a pause, no reaction
        cues = audio_signals.window_features(quiet, 1000.0, words, 0.0, 20.0)
        assert cues["react"] == 0.02 and cues["pause"] == 3.0

    def test_only_the_words_of_the_window_count(self):
        rms = np.full(200, 1000.0)
        words = _words(*[(i * 0.25, i * 0.25 + 0.2) for i in range(400)])     # 4 words a second
        assert audio_signals.window_features(rms, 1000.0, words, 30.0, 60.0)["wps"] == 4.0

    def test_nothing_to_measure(self):
        assert audio_signals.window_features(np.zeros(0), 1000.0, [], 0.0, 10.0) is None
        assert audio_signals.window_features(np.full(10, 5.0), 0.0, [], 0.0, 5.0) is None
        assert audio_signals.window_features(np.full(10, 5.0), 1.0, [], 900.0, 990.0) is None, "past the end"

    def test_speech_level_leaves_the_silences_out(self):
        rms = np.array([1000.0] * 50 + [5.0] * 50)
        assert audio_signals.speech_level(rms) == 1000.0
        assert audio_signals.speech_level(np.zeros(10)) == 0.0 and audio_signals.speech_level([]) == 0.0

    def test_a_window_costs_few_tokens(self):
        cues = {"loud": 1.12, "peak": 2.4, "var": 0.41, "wps": 2.9, "react": 0.85, "pause": 1.2}
        assert len(json.dumps({"audio": cues})) < 100, "about 25 tokens a window"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
class TestEnvelope:
    def _wav(self, path):
        t = np.arange(8000) / 8000.0
        tone = np.sin(2 * np.pi * 440 * t)
        samples = np.concatenate([tone * 20000, np.zeros(8000), tone * 5000]).astype(np.int16)
        with wave.open(str(path), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(8000)
            f.writeframes(samples.tobytes())

    def test_reads_a_real_file(self, tmp_path):
        path = tmp_path / "a.wav"
        self._wav(path)
        rms = audio_signals.envelope(str(path))
        assert len(rms) == 6, "3 s at one value every half second"
        assert rms[0] > 10000 and rms[2] < 100 and 2000 < rms[4] < 5000
        cues, rate = audio_signals.for_windows(str(path), [{"id": "window_001", "start": 0.0, "end": 3.0}],
                                               _words((0.0, 0.9), (2.0, 2.9)))
        assert set(cues["window_001"]) == {"loud", "peak", "var", "wps", "react", "pause"}
        assert cues["window_001"]["pause"] == 1.1 and rate == cues["window_001"]["wps"]

    def test_a_file_that_is_not_media_gives_nothing(self, tmp_path):
        bad = tmp_path / "bad.mp4"
        bad.write_text("not a video")
        assert len(audio_signals.envelope(str(bad))) == 0
        with pytest.raises(RuntimeError):
            audio_signals.for_windows(str(bad), [{"id": "w", "start": 0.0, "end": 3.0}], [])


def test_pause_before_the_clip_goes_to_the_stats_json(tmp_path):
    tr = {"segments": [{"words": [{"word": "before.", "start": 8.0, "end": 8.5},
                                  {"word": "Your", "start": 10.0, "end": 10.3},
                                  {"word": "brain.", "start": 10.3, "end": 10.8}]}]}
    assert playbook.pause_before({"start": 9.92}, tr) == 1.5
    assert playbook.pause_before({"start": 7.9}, tr) is None, "nothing said before it"
    assert playbook.pause_before({"start": 9.92}, None) is None
    out = json.load(open(playbook.export_clip({"start": 9.92, "end": 40.0}, str(tmp_path), "x_clip_1.mp4", [], tr),
                         encoding="utf-8"))
    assert out["pause_before"] == 1.5


# --- wiring in the scoring prompt (needs main) --------------------------------------------

main = pytest.importorskip("main")
from test_selection_pipeline import clip, run  # noqa: E402,F401  (run is a fixture)

CUES = {"loud": 1.1, "peak": 2.4, "var": 0.5, "wps": 2.0, "react": 0.8, "pause": 1.2}


class TestScoringPrompt:
    def _fake(self, monkeypatch, fail=False):
        calls = []

        def for_windows(video_path, windows, words):
            calls.append(video_path)
            if fail:
                raise RuntimeError("no audio stream")
            return {w["id"]: dict(CUES) for w in windows}, 2.0

        monkeypatch.setattr(audio_signals, "for_windows", for_windows)
        return calls

    def test_off_by_default_the_sound_is_not_even_read(self, run, monkeypatch):
        calls = self._fake(monkeypatch)
        run([clip(100.0, 130.0)], video_path="/x/source.mkv")
        assert calls == []
        assert '"audio"' not in run.prompts["score"][-1] and "AUDIO CUES" not in run.prompts["score"][-1]

    def test_on_the_scoring_windows_carry_the_cues_and_the_note(self, run, monkeypatch, capsys):
        run([clip(100.0, 130.0)], video_path="/x/source.mkv")
        off_score, off_detail = run.prompts["score"][-1], run.prompts["detail"][-1]
        calls = self._fake(monkeypatch)
        monkeypatch.setenv("AUDIO_SIGNALS", "1")
        run([clip(100.0, 130.0)], video_path="/x/source.mkv")
        score, detail = run.prompts["score"][-1], run.prompts["detail"][-1]
        assert calls == ["/x/source.mkv"]
        assert '"audio": {"loud": 1.1' in score and "AUDIO CUES" in score and "usual rate is 2" in score
        assert detail == off_detail, "the detail pass cuts on the words: no audio there"
        out = capsys.readouterr().out
        assert "Audio cues on" in out and "tokens more for the scoring pass" in out
        note = main.gemini_worker.AUDIO_SIGNALS_ADDENDUM.format(wps=2.0)
        assert len(score) - len(off_score) <= len(note) + 100 * score.count('"audio"'), \
            "the note once, then under 100 characters (about 25 tokens) a window"

    def test_a_failure_scores_on_the_text_alone(self, run, monkeypatch, capsys):
        run([clip(100.0, 130.0)], video_path="/x/source.mkv")
        off = run.prompts["score"][-1]
        self._fake(monkeypatch, fail=True)
        monkeypatch.setenv("AUDIO_SIGNALS", "1")
        shorts = run([clip(100.0, 130.0)], video_path="/x/source.mkv")
        assert len(shorts) == 1 and run.prompts["score"][-1] == off
        assert "Audio cues skipped (RuntimeError: no audio stream)" in capsys.readouterr().out

    def test_without_a_source_file_it_is_skipped(self, run, monkeypatch, capsys):
        calls = self._fake(monkeypatch)
        monkeypatch.setenv("AUDIO_SIGNALS", "1")
        assert len(run([clip(100.0, 130.0)])) == 1
        assert calls == [] and "no source file to listen to" in capsys.readouterr().out
