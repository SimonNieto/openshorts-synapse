"""get_viral_clips end to end with the two AI stages stubbed: what the code
does to the model's clips (duplicates, cuts) once they come back."""
import pytest

# main pulls in cv2/torch/mediapipe at import time; skip where they are missing.
main = pytest.importorskip("main")
import ai_brain  # noqa: E402

SENTENCE = "it happens to people every day without them knowing."   # 9 words = 4.5 s


def make_transcript(seconds=600):
    """One word every 0.5 s, a full stop every 9 words, 30 s segments."""
    text = (SENTENCE + " ") * int(seconds / 4.5)
    words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(text.split())]
    segments = []
    for k in range(0, len(words), 60):
        chunk = words[k:k + 60]
        segments.append({"start": chunk[0]["start"], "end": chunk[-1]["end"],
                         "text": " ".join(w["word"] for w in chunk), "words": chunk})
    return {"language": "en", "segments": segments}


def clip(start, end, score=70, **extra):
    return {"start": start, "end": end, "source_window_id": "window_001", "predicted_score": score,
            "video_description_for_tiktok": "d", "video_description_for_instagram": "d",
            "video_title_for_youtube_short": "Can this happen?", "viral_hook_text": "h", **extra}


@pytest.fixture
def run(monkeypatch):
    """run(clips) -> the shorts get_viral_clips returns for those model clips.
    ``run.prompts`` collects the prompts built for each stage."""
    for name in ("SELECTION_V2", "TITLE_SERIES", "SYNAPSE_PLAYBOOK", "CLEAN_END", "CLIP_MIN_SECONDS",
                 "CLIP_MAX_SECONDS", "CLIP_TARGET_MIN", "CLIP_TARGET_MAX", "CLIP_DEDUPE_OVERLAP",
                 "CLIP_DEDUPE_SECONDS", "CLIP_TARGET_MIN_SECONDS", "CLIP_TARGET_MAX_SECONDS", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BRAIN", "gemini")
    # A brief is already there: the scoring pass runs on its own, stubbed below.
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", {"by": "test"})
    prompts = {"score": [], "detail": []}

    def _run(clips, duration=600):
        def fake_stage(client, model_name, items, build_prompt, schema, key, costs, label):
            prompts[label].append(build_prompt(items))
            if label == "score":
                return [{"id": w["id"], "start": w["start"], "end": w["end"], "score": 80, "reason": "r"}
                        for w in items]
            return [dict(c) for c in clips]
        monkeypatch.setattr(main, "_run_stage_split", fake_stage)
        result = main.get_viral_clips(make_transcript(duration), duration)
        return result["shorts"] if result else []

    _run.prompts = prompts
    return _run


OVERLAPPING = [clip(100.0, 140.0, 75), clip(130.0, 170.0, 73), clip(300.0, 330.0, 60)]


def test_overlapping_clips_are_kept_by_default(run):
    assert len(run(OVERLAPPING)) == 3


def test_dedupe_drops_the_weaker_of_two_overlapping_clips(run, monkeypatch, capsys):
    monkeypatch.setenv("CLIP_DEDUPE_OVERLAP", "0.2")
    shorts = run(OVERLAPPING)
    assert [round(s["start"]) for s in shorts] == [100, 300]
    assert "Duplicate dropped" in capsys.readouterr().out
