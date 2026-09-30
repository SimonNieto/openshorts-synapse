"""The channel's positive topic list (selection.niche_topics -> NICHE_TOPICS).

The playbook only listed what the channel stays off. On JRE #2515, 4 of the
11 clips were UFC recaps on a neuroscience channel: nothing said what the
channel is about, and topic_bucket had no place for a fight."""
import json

import pytest

import playbook

SYNAPSE = "brain_danger,substances,psychosis_mental_illness,mind_psychology,self_improvement,medical_mystery,crime_dark"
NICHE_VARS = ("NICHE_TOPICS", "NICHE_WEIGHT", "NICHE_ONLY", "NICHE_CONTEXT", "CLIP_COUNT_FLOOR")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in NICHE_VARS + ("SYNAPSE_PLAYBOOK",):
        monkeypatch.delenv(name, raising=False)


def _clips():
    return [{"start": 120.0, "topic_bucket": "substances", "predicted_score": 78},
            {"start": 848.0, "topic_bucket": "science_other", "predicted_score": 77},
            {"start": 1308.0, "topic_bucket": "sports_combat", "predicted_score": 82},
            {"start": 1400.0, "topic_bucket": "", "predicted_score": 70},
            {"start": 1500.0, "topic_bucket": "made_up", "predicted_score": 70}]


class TestSettings:
    def test_off_by_default(self):
        assert playbook.niche_settings() is None

    def test_reads_the_env(self, monkeypatch):
        monkeypatch.setenv("NICHE_TOPICS", SYNAPSE + ", not_a_bucket, other")
        s = playbook.niche_settings()
        assert s["topics"] == SYNAPSE.split(",") and s["weight"] == 15.0 and s["only"] is False
        monkeypatch.setenv("NICHE_WEIGHT", "25")
        monkeypatch.setenv("NICHE_ONLY", "1")
        monkeypatch.setenv("NICHE_CONTEXT", "The brain and the mind.")
        s = playbook.niche_settings()
        assert s["weight"] == 25.0 and s["only"] is True and s["context"] == "The brain and the mind."

    def test_only_unknown_topics_is_off(self, monkeypatch):
        monkeypatch.setenv("NICHE_TOPICS", "cooking, other")
        assert playbook.niche_settings() is None

    def test_sentence(self):
        s = {"topics": ["substances", "mind_psychology"], "context": "The brain and the mind."}
        line = playbook.niche_sentence(s)
        assert line.startswith("The brain and the mind — drugs, alcohol") and "how the mind works" in line
        assert playbook.niche_sentence({"topics": ["substances"], "context": ""}).startswith("drugs")

    def test_the_off_niche_buckets_exist(self):
        for bucket in ("sports_combat", "entertainment", "business_money", "other"):
            assert bucket in playbook.TOPIC_BUCKETS
        assert set(playbook.BUCKET_LABELS) == set(playbook.TOPIC_BUCKETS) - {"other"}


class TestApply:
    SETTINGS = {"topics": SYNAPSE.split(","), "weight": 15.0, "only": False}

    def test_weight_lowers_the_score_and_keeps_the_raw_one(self):
        kept, dropped = playbook.apply_niche(_clips(), self.SETTINGS)
        assert dropped == [] and len(kept) == 5
        on, science, ufc, empty, unknown = kept
        assert "off_niche" not in on and on["predicted_score"] == 78
        assert ufc["off_niche"] and ufc["predicted_score"] == 67 and ufc["predicted_score_raw"] == 82
        assert science["off_niche"], "science_other is not in this channel's list"
        assert empty["off_niche"] and unknown["off_niche"], "no bucket / an unknown one count as 'other'"

    def test_the_best_off_niche_clip_ranks_under_every_on_niche_clip_of_the_job(self):
        # JRE #2515: on-niche scores 72-83, the UFC clips 74-82.
        clips = ([{"topic_bucket": "substances", "predicted_score": s} for s in (72, 78, 83)]
                 + [{"topic_bucket": "sports_combat", "predicted_score": s} for s in (74, 82)])
        kept, _ = playbook.apply_niche(clips, self.SETTINGS)
        on = [c["predicted_score"] for c in kept if not c.get("off_niche")]
        off = [c["predicted_score"] for c in kept if c.get("off_niche")]
        assert max(off) < min(on)

    def test_applying_twice_does_not_subtract_twice(self):
        clips = _clips()
        playbook.apply_niche(clips, self.SETTINGS)
        playbook.apply_niche(clips, self.SETTINGS)
        assert clips[2]["predicted_score"] == 67

    def test_niche_only_drops_them(self):
        kept, dropped = playbook.apply_niche(_clips(), {**self.SETTINGS, "only": True})
        assert [c["start"] for c in kept] == [120.0]
        assert len(dropped) == 4 and all(c["off_niche"] for c in dropped)
        assert dropped[1]["predicted_score"] == 82, "a dropped clip keeps its score"

    def test_a_missing_score_does_not_raise(self):
        kept, _ = playbook.apply_niche([{"topic_bucket": "entertainment"}], self.SETTINGS)
        assert kept[0]["off_niche"] and "predicted_score" not in kept[0]

    def test_export_carries_the_flag_and_both_scores(self, tmp_path):
        clip = {"start": 0.0, "end": 30.0, "topic_bucket": "sports_combat", "predicted_score": 82}
        playbook.apply_niche([clip], self.SETTINGS)
        out = json.load(open(playbook.export_clip(clip, str(tmp_path), "x_clip_1.mp4", []), encoding="utf-8"))
        assert out["off_niche"] is True and out["score"] == 67 and out["score_raw"] == 82
        plain = {"start": 0.0, "end": 30.0, "predicted_score": 80}
        out = json.load(open(playbook.export_clip(plain, str(tmp_path), "y_clip_1.mp4", []), encoding="utf-8"))
        assert out["off_niche"] is False and out["score_raw"] == 80


class TestCountFloor:
    def test_off_by_default_and_garbage(self, monkeypatch):
        from clip_selection import clip_count_floor
        assert clip_count_floor() is None
        for bad in ("x", "0", "-3"):
            monkeypatch.setenv("CLIP_COUNT_FLOOR", bad)
            assert clip_count_floor() is None
        monkeypatch.setenv("CLIP_COUNT_FLOOR", "2")
        assert clip_count_floor() == 2


# --- prompts and pipeline (need main) -------------------------------------------------

main = pytest.importorskip("main")
from test_selection_pipeline import clip, run  # noqa: E402,F401  (run is a fixture)


class TestPrompts:
    def test_no_niche_no_text(self, monkeypatch):
        import gemini_worker as gw
        assert main.playbook_niche_rules() == "" and main.playbook_niche_rules(detail=True) == ""
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        assert main.playbook_score_rules() == gw.SAFETY_TOPICS_ADDENDUM, "playbook without a niche: as before"
        assert "CHANNEL'S NICHE" not in main.playbook_detail_rules(60)

    def test_niche_needs_the_playbook(self, monkeypatch):
        monkeypatch.setenv("NICHE_TOPICS", SYNAPSE)
        assert main.playbook_score_rules() == "" and main.playbook_detail_rules(60) == ""

    def test_scoring_and_detail_prompts_say_what_the_channel_is_about(self, monkeypatch):
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        monkeypatch.setenv("NICHE_TOPICS", SYNAPSE)
        monkeypatch.setenv("NICHE_CONTEXT", "The brain and the mind")
        score, detail = main.playbook_score_rules(), main.playbook_detail_rules(60)
        for text in (score, detail):
            assert "this channel is about The brain and the mind — " in text
            assert "psychosis and mental illness" in text
            assert "{" not in text, "no unfilled placeholder"
        assert "loses about 15 points" in score and "Strongly prefer" in detail
        assert "sports_combat" in detail and "overrides the HOW MANY rule" in detail
        monkeypatch.setenv("NICHE_ONLY", "1")
        assert "gets 0-30" in main.playbook_score_rules()
        assert "on that niche ONLY" in main.playbook_detail_rules(60)


class TestPipeline:
    CLIPS = [clip(100.0, 130.0, 78, topic_bucket="substances", hook_line=""),
             clip(200.0, 230.0, 82, topic_bucket="sports_combat", hook_line=""),
             clip(300.0, 330.0, 80, topic_bucket="self_improvement", hook_line="")]

    def test_without_a_niche_every_clip_stays(self, run, monkeypatch):
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        shorts = run(self.CLIPS)
        assert len(shorts) == 3 and not any(s.get("off_niche") for s in shorts)
        assert "CHANNEL'S NICHE" not in run.prompts["score"][-1] + run.prompts["detail"][-1]

    def test_weight_keeps_the_clip_with_a_lower_score(self, run, monkeypatch, capsys):
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        monkeypatch.setenv("NICHE_TOPICS", SYNAPSE)
        shorts = run(self.CLIPS)
        assert [s["predicted_score"] for s in shorts] == [78, 67, 80]
        assert "CHANNEL'S NICHE" in run.prompts["score"][-1] and "CHANNEL'S NICHE" in run.prompts["detail"][-1]
        assert "Off-niche clip kept with -15 points" in capsys.readouterr().out

    def test_niche_only_drops_the_off_niche_clip(self, run, monkeypatch, capsys):
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        monkeypatch.setenv("NICHE_TOPICS", SYNAPSE)
        monkeypatch.setenv("NICHE_ONLY", "1")
        shorts = run(self.CLIPS)
        assert [s["topic_bucket"] for s in shorts] == ["substances", "self_improvement"]
        assert "Off-niche clip dropped: 200s [sports_combat]" in capsys.readouterr().out

    def test_a_source_entirely_off_niche_says_so(self, run, monkeypatch, capsys):
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        monkeypatch.setenv("NICHE_TOPICS", SYNAPSE)
        monkeypatch.setenv("NICHE_ONLY", "1")
        assert run([self.CLIPS[1]]) == []
        assert "Every clip the model returned was off niche" in capsys.readouterr().out

    def test_niche_without_the_playbook_changes_nothing(self, run, monkeypatch, capsys):
        run(self.CLIPS)
        off = (run.prompts["score"][-1], run.prompts["detail"][-1])
        monkeypatch.setenv("NICHE_TOPICS", SYNAPSE)
        monkeypatch.setenv("NICHE_ONLY", "1")
        shorts = run(self.CLIPS)
        assert len(shorts) == 3
        assert (run.prompts["score"][-1], run.prompts["detail"][-1]) == off
        assert "Niche topics ignored" in capsys.readouterr().out

    def test_count_floor_lowers_the_number_of_clips_asked_for(self, run, monkeypatch):
        run(self.CLIPS)
        assert "return 1 to" not in run.prompts["detail"][-1]
        monkeypatch.setenv("CLIP_COUNT_FLOOR", "1")
        run(self.CLIPS)
        assert "return 1 to" in run.prompts["detail"][-1]
