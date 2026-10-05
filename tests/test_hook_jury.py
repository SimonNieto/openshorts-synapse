"""hook_jury.py: the C1 contract (files, staleness, fields), what the juror is shown (and NOT shown), the votes,
the ranking check and the calibration statistics. No model is called: hook_jury._ask and the frame extraction
are faked."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hook_jury as hj  # noqa: E402

JOB = "abcd1234-0000-4000-8000-000000000001"
BASE = f"{JOB}_Some Podcast #1 - Guest-001"


def _transcript():
    words = []
    t = 100.0
    for w in ("Also,", "they", "found", "the", "tumor.", "Then", "he", "went", "to", "the", "tower", "and",
              "everything", "changed.", "Nobody", "knew", "why."):
        words.append({"word": " " + w, "start": t, "end": t + 0.4})
        t += 0.5
    return {"language": "en", "segments": [{"start": 100.0, "end": t, "text": "", "words": words}]}


def make_job(tmp_path, shorts=None, files=()):
    out = tmp_path / "output"
    job = out / JOB
    job.mkdir(parents=True)
    shorts = shorts if shorts is not None else [{"start": 100.0, "end": 108.0,
                                                 "viral_hook_text": "A tumor changed him",
                                                 "auto_hook": {"text": "A tumor changed him"},
                                                 "video_title_for_youtube_short": "SECRET TITLE",
                                                 "predicted_score": 99}]
    (job / f"{BASE}_metadata.json").write_text(json.dumps({"shorts": shorts, "transcript": _transcript()}))
    for name in files:
        (job / name).write_bytes(b"mp4")
    return str(out), job


def fake_frames(monkeypatch):
    def extract(video, times, out_dir, width=hj.PHONE_WIDTH, prefix=""):
        os.makedirs(out_dir, exist_ok=True)
        paths = []
        for t in times:
            p = os.path.join(out_dir, f"{prefix}t{t:.1f}s.jpg")
            with open(p, "wb") as f:
                f.write(b"jpg")
            paths.append(p)
        return paths
    monkeypatch.setattr(hj, "extract_frames", extract)


def fake_ask(monkeypatch, scores=(60, 70, 65), truth=None, order=None):
    calls = []

    def ask(prompt, schema, attach=None, system=None):
        calls.append({"prompt": prompt, "schema": schema, "attach": list(attach or []), "system": system})
        if schema is hj.SOLO_SCHEMA:
            k = sum(1 for c in calls if c["schema"] is hj.SOLO_SCHEMA) - 1
            s = scores[k % len(scores)]
            return ({"topic_guess": "a tumor", "hook_read": "A tumor changed him", "stands_alone": k != 1,
                     "topic_named": True, "tension": False, "hook_matches_voice": None, "first_frame_clear": True,
                     "stop": ["yes", "maybe", "no"][k % 3], "feeling": f"feeling {k}", "score": s,
                     "verdict": f"verdict {s}", "fix": f"fix {s}"}, "sonnet",
                    {"seconds": 1.0, "input_tokens": 4000, "output_tokens": 200, "calls": 1})
        if schema is hj.TRUTH_SCHEMA:
            return (truth or {"hook_true": True, "hook_problem": None, "true_hook": None, "no_spoiler": True,
                              "better_start": None}, "sonnet",
                    {"seconds": 0.5, "input_tokens": 1000, "output_tokens": 40, "calls": 1})
        labels = [ln.split(":")[0] for ln in prompt.splitlines() if len(ln) > 2 and ln[1] == ":" and ln[0].isupper()]
        return ({"order": order or list(reversed(labels)), "why": "x"}, "sonnet",
                {"seconds": 1.0, "input_tokens": 5000, "output_tokens": 30, "calls": 1})
    monkeypatch.setattr(hj, "_ask", ask)
    return calls


# --- the rendered file -------------------------------------------------------------------------------------

def test_clip_video_path_prefers_the_file_the_metadata_points_to(tmp_path):
    shorts = [{"start": 0, "end": 5, "video_url": f"/videos/{JOB}/subtitled_1_hooked_1_{BASE}_clip_1.mp4"}]
    out, job = make_job(tmp_path, shorts, files=[f"subtitled_1_hooked_1_{BASE}_clip_1.mp4",
                                                 f"{BASE}_clip_1.mp4"])
    assert os.path.basename(hj.clip_video_path(out, JOB, 0)) == f"subtitled_1_hooked_1_{BASE}_clip_1.mp4"


def test_clip_video_path_falls_back_to_the_newest_derived_then_the_bare_clip(tmp_path):
    out, job = make_job(tmp_path, [{"start": 0, "end": 5}],
                        files=[f"{BASE}_clip_1.mp4", f"hooked_5_{BASE}_clip_1.mp4",
                               f"subtitled_9_hooked_5_{BASE}_clip_1.mp4"])
    os.utime(job / f"hooked_5_{BASE}_clip_1.mp4", (1000, 1000))
    os.utime(job / f"subtitled_9_hooked_5_{BASE}_clip_1.mp4", (2000, 2000))
    assert os.path.basename(hj.clip_video_path(out, JOB, 0)) == f"subtitled_9_hooked_5_{BASE}_clip_1.mp4"
    os.remove(job / f"hooked_5_{BASE}_clip_1.mp4")
    os.remove(job / f"subtitled_9_hooked_5_{BASE}_clip_1.mp4")
    assert os.path.basename(hj.clip_video_path(out, JOB, 0)) == f"{BASE}_clip_1.mp4"


def test_clip_video_path_none_without_a_final_render(tmp_path):
    out, _job = make_job(tmp_path, [{"start": 0, "end": 5}], files=[f"{BASE}_clip_1.pre_fx.mp4"])
    assert hj.clip_video_path(out, JOB, 0) is None
    assert hj.clip_video_path(out, JOB, 3) is None
    assert hj.clip_video_path(out, "nope", 0) is None


# --- what the viewer hears -----------------------------------------------------------------------------------

def test_words_follow_the_clip_start():
    words = hj.clip_words(_transcript(), {"start": 100.0, "end": 108.0})
    assert words[0]["w"] == "Also," and words[0]["s"] == 0.0
    assert hj.window_text(words, 0, 3) == "Also, they found the tumor. Then"
    assert hj.window_text(words, 3, 6).startswith("he went")


def test_words_of_a_recut_clip_follow_its_edl():
    short = {"start": 100.0, "end": 108.0, "recipe": {"segments": [{"start": 102.5, "end": 108.5}]}}
    words = hj.clip_words(_transcript(), short)
    assert words[0]["w"] == "Then" and words[0]["s"] == 0.0     # the montage cut "Also, they found the tumor."


def test_find_phrase_grounds_a_quote_or_returns_none():
    words = hj.clip_words(_transcript(), {"start": 100.0, "end": 108.0})
    assert hj.find_phrase(words, "Then he went to the") == 2.5
    assert hj.find_phrase(words, "he never said this") is None


# --- one clip ------------------------------------------------------------------------------------------------

def test_run_one_writes_the_c1_result(tmp_path, monkeypatch):
    out, job = make_job(tmp_path, files=[f"{BASE}_clip_1.mp4"])
    fake_frames(monkeypatch)
    calls = fake_ask(monkeypatch)
    r = hj.run_one(out, JOB, 0, votes=3)
    path = os.path.join(out, "_jury", "results", f"{JOB}_c01.json")
    assert json.load(open(path)) == r
    for key in ("job_id", "clip_index", "ref", "clip_file", "clip_mtime", "version", "model", "at", "score",
                "votes", "spread", "criteria", "hook_true", "verdict", "fix", "stop", "feeling", "score_solo",
                "rank_check"):
        assert key in r, key
    assert r["ref"] == "abcd1234_c01" and r["clip_index"] == 0 and r["version"] == hj.VERSION
    assert r["votes"] == [60, 70, 65] and r["score"] == 65 and r["spread"] == 10
    assert set(r["criteria"]) == set(hj.CRITERIA)
    assert r["criteria"]["stands_alone"] is True            # 2 votes of 3
    assert r["criteria"]["tension"] is False
    assert r["criteria"]["hook_matches_voice"] is None
    assert r["criteria"]["no_spoiler"] is True              # from the editor pass
    assert r["verdict"] == "verdict 65" and r["feeling"] == "feeling 2"     # the median juror's words
    assert r["stop"] in hj.STOPS
    assert r["cost"]["calls"] == 4 and r["cost"]["input_tokens"] == 13000
    assert len([c for c in calls if c["schema"] is hj.SOLO_SCHEMA]) == 3
    assert hj.load_result(out, JOB, 0) == r


def test_the_juror_is_blind(tmp_path, monkeypatch):
    out, _job = make_job(tmp_path, files=[f"{BASE}_clip_1.mp4"])
    fake_frames(monkeypatch)
    calls = fake_ask(monkeypatch)
    hj.run_one(out, JOB, 0, votes=1)
    solo = next(c for c in calls if c["schema"] is hj.SOLO_SCHEMA)
    p = solo["prompt"]
    assert "Also, they found the tumor. Then" in p and "A tumor changed him" in p
    assert "SECRET TITLE" not in p and "99" not in p and "Podcast" not in p and "Guest" not in p
    assert "stayed" not in p.lower() and "views" not in p.lower()
    assert len(solo["attach"]) == len(hj.FRAME_TIMES) and solo["system"] == hj.SYSTEM_VIEWER
    assert "everything changed" not in p                  # the viewer hears 0-6 s, not the end


def test_the_prompts_hold_principles_not_calibration_examples():
    text = " ".join([hj.VIEWER, hj.PRINCIPLES, hj.SOLO_TASK, hj.TRUTH_TASK, hj.RANK_TASK, hj.SYSTEM_VIEWER]).lower()
    for word in ("tumor", "kratom", "honnold", "potter", "mdma", "ptsd", "frustration", "discipline", "meth",
                 "schizophrenia", "ibogaine", "jiu", "rogan", "huberman", "perplexity", "emergency", "needle",
                 "scan", "doctor", "pharma"):
        assert not re.search(rf"\b{word}\b", text), word


def test_votes_are_different_questions_for_the_cache(tmp_path, monkeypatch):
    out, _job = make_job(tmp_path, files=[f"{BASE}_clip_1.mp4"])
    fake_frames(monkeypatch)
    calls = fake_ask(monkeypatch)
    hj.run_one(out, JOB, 0, votes=3)
    prompts = [c["prompt"] for c in calls if c["schema"] is hj.SOLO_SCHEMA]
    assert len(set(prompts)) == 3
    assert "Independent vote" not in prompts[0]            # vote 1 = the 1-vote question (cache shared)


def test_a_clip_is_judged_once(tmp_path, monkeypatch):
    """The user's rule: tokens are never spent twice on the same rendered clip."""
    out, _job = make_job(tmp_path, files=[f"{BASE}_clip_1.mp4"])
    fake_frames(monkeypatch)
    calls = fake_ask(monkeypatch)
    first = hj.run_one(out, JOB, 0, votes=1)
    n = len(calls)
    assert hj.run_one(out, JOB, 0, votes=1) == first
    assert hj.run_one(out, JOB, 0, votes=3) == first       # more votes asked: still the kept result
    monkeypatch.setattr(hj, "VERSION", "jury-v2")
    assert hj.run_one(out, JOB, 0) == first                # a new jury version does not re-judge either
    assert hj.run_many(out, [(JOB, 0)]) == [first]
    assert len(calls) == n
    hj.run_one(out, JOB, 0, votes=1, force=True)           # only an explicit force does
    assert len(calls) > n


def test_a_new_render_is_judged_again(tmp_path, monkeypatch):
    out, job = make_job(tmp_path, files=[f"{BASE}_clip_1.mp4"])
    fake_frames(monkeypatch)
    calls = fake_ask(monkeypatch)
    hj.run_one(out, JOB, 0, votes=1)
    n = len(calls)
    (job / f"subtitled_7_{BASE}_clip_1.mp4").write_bytes(b"new")
    r = hj.run_one(out, JOB, 0, votes=1)
    assert len(calls) > n and r["clip_file"] == f"subtitled_7_{BASE}_clip_1.mp4"


def test_a_changed_mp4_makes_the_result_stale(tmp_path, monkeypatch):
    out, job = make_job(tmp_path, files=[f"{BASE}_clip_1.mp4"])
    fake_frames(monkeypatch)
    fake_ask(monkeypatch)
    hj.run_one(out, JOB, 0, votes=1)
    os.utime(job / f"{BASE}_clip_1.mp4", (5000, 5000))
    assert hj.load_result(out, JOB, 0) is None
    os.utime(job / f"{BASE}_clip_1.mp4", None)
    hj.run_one(out, JOB, 0, votes=1)
    (job / f"subtitled_7_{BASE}_clip_1.mp4").write_bytes(b"new")   # a new render
    assert hj.load_result(out, JOB, 0) is None


def test_a_false_hook_comes_first_in_the_fix(tmp_path, monkeypatch):
    out, _job = make_job(tmp_path, files=[f"{BASE}_clip_1.mp4"])
    fake_frames(monkeypatch)
    fake_ask(monkeypatch, truth={"hook_true": False, "hook_problem": "The clip never says it changed him.",
                                 "true_hook": "Nobody knew why", "no_spoiler": True, "better_start": None})
    r = hj.run_one(out, JOB, 0, votes=1)
    assert r["hook_true"] is False
    assert "Nobody knew why" in r["fix"] and r["fix_viewer"] == "fix 60"


def test_a_better_start_is_proposed_only_when_said_in_the_clip(tmp_path, monkeypatch):
    out, _job = make_job(tmp_path, files=[f"{BASE}_clip_1.mp4"])
    fake_frames(monkeypatch)
    fake_ask(monkeypatch, scores=(50,), truth={"hook_true": True, "hook_problem": None, "true_hook": None,
                                               "no_spoiler": True, "better_start": "Then he went to the tower"})
    real = hj.combine_votes

    def not_alone(votes):
        panel = real(votes)
        panel["criteria"]["stands_alone"] = False
        return panel
    monkeypatch.setattr(hj, "combine_votes", not_alone)
    r = hj.run_one(out, JOB, 0, votes=1)
    assert r["fix"].startswith("Start at “Then he went to the tower") and r["better_start_at"] == 2.5
    words = hj.clip_words(_transcript(), {"start": 100, "end": 108})
    assert hj.clean_truth({"better_start": "words nobody said here"}, words)["better_start"] is None
    assert hj.clean_truth({"better_start": "Also, they found the"}, words)["better_start"] is None  # = the opening


def test_run_many_carries_on_after_an_error(tmp_path, monkeypatch):
    out, _job = make_job(tmp_path, files=[f"{BASE}_clip_1.mp4"])
    fake_frames(monkeypatch)
    fake_ask(monkeypatch)
    seen = []
    res = hj.run_many(out, [(JOB, 5), (JOB, 0)], progress=lambda d, t, r: seen.append((d, t, r)), votes=1)
    assert "error" in res[0] and res[0]["ref"] == "abcd1234_c06"
    assert res[1]["score"] == 60
    assert seen == [(1, 2, "abcd1234_c06"), (2, 2, "abcd1234_c01")]


def test_combine_votes_majority_and_ties():
    votes = [hj.clean_vote({"score": s, "stands_alone": v, "stop": st}) for s, v, st in
             ((40, True, "no"), (80, False, "yes"), (55, None, "maybe"))]
    panel = hj.combine_votes(votes)
    assert panel["score"] == 55 and panel["spread"] == 40
    assert panel["criteria"]["stands_alone"] is None
    assert panel["stop"] == "maybe"
    assert hj.clean_vote({"score": "140", "stop": "YES"})["score"] == 100
    assert hj.clean_vote({"score": "x"})["score"] is None


def test_load_calibration(tmp_path):
    out = tmp_path / "output"
    assert hj.load_calibration(str(out)) is None
    (out / "_jury").mkdir(parents=True)
    (out / "_jury" / "calibration.json").write_text(json.dumps({"n": 21, "reading": "moderate"}))
    assert hj.load_calibration(str(out))["n"] == 21


# --- the ranking check ---------------------------------------------------------------------------------------

def test_make_groups_gives_every_clip_its_rounds():
    ids = [f"c{i}" for i in range(10)]
    groups = hj.make_groups(ids, rounds=3, size=4, seed=1)
    for g in groups:
        assert 3 <= len(g) <= 4 and len(set(g)) == len(g)
    for i in ids:
        assert sum(i in g for g in groups) >= 3


def test_pairwise_table_and_clean_order():
    table = hj.pairwise_table([["a", "b", "c"], ["b", "a"]])
    assert table["a"] == {"wins": 2, "games": 3, "rank_score": 67}
    assert table["c"]["rank_score"] == 0
    assert hj.clean_order(["c", "Z", "a", "c"], ["A", "B", "C"]) == ["C", "A", "B"]


def test_final_score_modes():
    assert hj.final_score(60, None, "ranked") == 60
    assert hj.final_score(60, {"rank_score": 80}, "ranked") == 80
    assert hj.final_score(60, {"rank_score": 80}, "blend") == 70
    assert hj.final_score(60, {"rank_score": 80}, "solo") == 60


# --- statistics ----------------------------------------------------------------------------------------------

def test_spearman_p_and_reading():
    xs = list(range(10))
    assert hj.spearman_p(xs, xs) < 0.01
    assert hj.spearman_p(xs, [3, 9, 1, 7, 0, 5, 8, 2, 6, 4]) > 0.2
    assert hj.reading(7, 0.9, 0.001) == "too_few"
    assert hj.reading(20, 0.65, 0.01) == "strong"
    assert hj.reading(20, 0.45, 0.10) == "moderate"
    assert hj.reading(20, 0.45, 0.30) == "weak"
    assert hj.reading(20, -0.7, 0.001) == "weak"


def test_calibrate_end_to_end_on_fake_data(tmp_path, monkeypatch):
    out = tmp_path / "output"
    pub = out / "_jury" / "published"
    pub.mkdir(parents=True)
    shorts, videos = [], []
    for i in range(9):
        vid = f"vid{i:08d}xx"[:11]
        (pub / f"{vid}.mp4").write_bytes(b"mp4")
        stayed = 40 + 4 * i
        shorts.append({"id": vid, "titre": f"t{i}", "pub": "2026-09-20", "vues": 1000, "restent_pct": stayed,
                       "local_tag": None})
        videos.append({"id": vid, "pub": "2026-09-20T03:00:00-07:00"})
        r = {"video_id": vid, "ref": vid, "score": 30 + 5 * i, "score_solo": 30 + 5 * i, "votes": [30 + 5 * i] * 3,
             "spread": 0, "verdict": "v", "rank_check": {"wins": i, "games": 9, "rank_score": int(100 * i / 9)}}
        hj._write_json(hj._published_result_path(str(out), vid), r)
    young = "young000000"
    (pub / f"{young}.mp4").write_bytes(b"mp4")
    shorts.append({"id": young, "titre": "y", "pub": "2026-10-04", "vues": 900, "restent_pct": 50, "local_tag": None})
    videos.append({"id": young, "pub": "2026-10-04T03:00:00-07:00"})
    d = out / "_stepup" / "donnees"
    d.mkdir(parents=True)
    (d / "shorts_23.json").write_text(json.dumps(shorts))
    (d / "studio_raw.json").write_text(json.dumps({"videos": videos}))
    cal = hj.calibrate(str(out), app_root=str(tmp_path))
    assert cal["n"] == 9 and cal["spearman"] == 1.0 and cal["reading"] == "strong"
    assert cal["spearman_solo"] == 1.0 and cal["spearman_ranked"] == 1.0
    assert any(e["ref"] == young and "48" in e["why"] for e in cal["excluded"])
    assert {"ref", "score", "stayed"} <= set(cal["rows"][0])
    assert hj.load_calibration(str(out))["n"] == 9
