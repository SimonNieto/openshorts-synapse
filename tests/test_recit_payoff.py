"""Lot L4 « récit » (5-oct-2026, validated by the user): the payoff always in
the clip and the clip ending on it, the openings that point back or ask
someone in the room, the "threat" order of preference (never a filter), the
``moment_nature`` of a moment, and the ``cut_out`` passages handed to the
montage. No AI call, no token.

The last test replays the real job of JRE #2553-004 (b8e46c24) through
get_viral_clips with the model's cached answer, when the job is on this disk."""
import asyncio
import glob
import json
import os
from pathlib import Path

import pytest

main = pytest.importorskip("main")
import ai_brain  # noqa: E402
import gemini_worker as gw  # noqa: E402
import playbook  # noqa: E402

FILL = "it happens to people every day without them knowing. "      # 9 words = 4.5 s


def mk(text, step=0.5, length=0.4):
    return [{"w": w, "s": round(i * step, 3), "e": round(i * step + length, 3)} for i, w in enumerate(text.split())]


def first(words, word, after=0.0):
    return next(i for i, w in enumerate(words) if w["w"] == word and w["s"] >= after)


# --- openings -------------------------------------------------------------------------------------

class TestOpenings:
    def test_a_lone_also_is_stepped_over(self):
        # JRE #2553 c08: "Also, now people aren't afraid of needles."
        w = mk("I think that's going to happen. Also, now people aren't afraid of needles. " + FILL * 8)
        c = {"start": 3.0, "end": 40.0, "hook_line": "Also, now people aren't afraid of needles."}
        main.align_hook_and_punchline(c, w, 15, 60, punchline=False, playbook=True)
        k = first(w, "now")
        assert c["hook_aligned"] and c["start"] == round(w[k]["s"] - 0.08, 3), c
        assert c["hook_line"] == "now people aren't afraid of needles."
        assert "opens_on_before" not in c

    def test_a_hook_pointing_back_gives_way_to_the_next_sentence(self):
        w = mk("that was the first one. The second thing was they pushed my head back. "
               "Your brain can lie to you. " + FILL * 8)
        c = {"start": 5.0, "end": 45.0, "hook_line": "The second thing was they pushed my head back."}
        main.align_hook_and_punchline(c, w, 15, 60, punchline=False, playbook=True)
        assert c["start"] == round(w[first(w, "Your")]["s"] - 0.08, 3), c
        assert not c["hook_aligned"] and "opens_on_before" not in c

    def test_a_hook_pointing_back_with_nothing_after_is_kept_and_flagged(self):
        w = mk("that was the first one. The second thing was they pushed my head back and it hurt "
               + "word " * 40)
        c = {"start": 5.0, "end": 26.0, "hook_line": "The second thing was they pushed my head back"}
        main.align_hook_and_punchline(c, w, 15, 60, punchline=False, playbook=True)
        assert c["opens_on_before"] and c["hook_aligned"], c
        assert c["start"] == round(w[first(w, "The")]["s"] - 0.08, 3)

    def test_a_request_to_someone_in_the_room_is_flagged_not_moved(self):
        # JRE #2553 c02: what follows is the screen being read aloud.
        w = mk("Can you put that into perplexity and see what leading cause of death? So there's malpractice. "
               + FILL * 8)
        c = {"start": 0.0, "end": 40.0,
             "hook_line": "Can you put that into perplexity and see what leading cause of death?"}
        main.align_hook_and_punchline(c, w, 15, 60, punchline=False, playbook=True)
        assert c["opens_on_request"] and c["hook_aligned"] and c["start"] == 0.0, c
        for line in ("Jamie, pull that up.", "Pull that up for me.", "Could you google it?", "look it up"):
            assert main._OPENS_ON_REQUEST.match(line.lower()), line
        for line in ("Can you imagine that?", "You can pull it off.", "Put simply, it kills you."):
            assert not main._OPENS_ON_REQUEST.match(line.lower()), line

    def test_the_start_never_reaches_into_the_word_before(self):
        # JRE #2553 c03: "...the you know patients calling them" — Whisper's
        # timestamps touch, and 0.08 s before "patients" was inside "know".
        w = [{"w": "the", "s": 611.40, "e": 611.52}, {"w": "you", "s": 611.52, "e": 612.10},
             {"w": "know", "s": 612.10, "e": 612.18}, {"w": "patients", "s": 612.18, "e": 612.60}]
        w += [{"w": x, "s": 612.7 + i * 0.5, "e": 613.1 + i * 0.5} for i, x in enumerate((FILL * 8).split())]
        c = {"start": 612.0, "end": 650.0, "hook_line": "Patients it happens to people"}
        main.align_hook_and_punchline(c, w, 15, 60, punchline=False, playbook=True)
        assert c["start"] == 612.18, c
        assert main._start_at(w, 3) == 612.18 and main._start_at(mk("a b"), 1) == 0.42

    def test_an_orphan_know_is_a_filler(self):
        # c03 again, when the cut lands between "you" and "know".
        w = mk("we were told you know patients call them all day long " + FILL * 6)
        k = first(w, "know")
        assert main._playbook_filler(w, k) == 1 and main._playbook_filler(w, first(w, "you")) == 2
        w2 = mk("tell me what you. know your limits " + FILL)
        assert main._playbook_filler(w2, first(w2, "know")) == 0, "after a full stop 'know' opens a sentence"

    def test_open_later_offers_no_request_and_nothing_after_the_payoff_starts(self):
        text = " ".join(f"s{j} one two three four five six seven eight end." for j in range(1, 13))
        w = mk(text)
        w[60]["w"], w[61]["w"], w[62]["w"] = "pull", "that", "up"          # sentence 7: a request
        c = {"start": 0.0, "end": 60.0}
        assert [k for k, _, _ in main.open_later_candidates(c, w, 15, (25, 40))] == [50, 70]
        c["punchline"] = "s7 one two three four five six seven eight end."   # never said: no limit
        assert [k for k, _, _ in main.open_later_candidates(c, w, 15, (25, 40))] == [50, 70]
        c["punchline"] = "s8 one two three four five six seven eight end."
        assert [k for k, _, _ in main.open_later_candidates(c, w, 15, (25, 40))] == [50], \
            "a later opening never starts on or after the payoff"

    def test_the_hook_never_costs_the_payoff(self):
        # The hook is 13 s back: 72 s with the model's end. Before, the end
        # moved to the last sentence end under 60 s, before the payoff.
        payoff = "that is the scary part of it."
        w = mk("intro part of the talk here. your brain can lie to you. " + FILL * 12 + payoff + " " + FILL * 2)
        c = {"start": 17.0, "end": w[-1]["e"], "hook_line": "your brain can lie to you.", "punchline": payoff}
        main.align_hook_and_punchline(c, w, 15, 60, punchline=False, playbook=True)
        assert c["end"] >= w[first(w, "it.", after=60)]["e"], ("the payoff stays", c)
        assert not c["hook_aligned"] or c["end"] - c["start"] <= 60


# --- cut_out ------------------------------------------------------------------------------------

def _clip_words():
    # c11 shaped: hook, an aside of the other speaker, the story, a hesitation, the payoff.
    text = ("He used to work at OpenAI and he was a whistleblower. I saw that episode announced. "
            "I have listened to it twice. They trained these agents to solve problems. "
            "And um I I mean they were scored on it. They tried hacking into the system. "
            "It's not going to cure anything, they said. They hacked the entire database. " + FILL * 2)
    return mk(text)


def _cut_clip(cut_out):
    w = _clip_words()
    return w, {"start": 0.0, "end": w[-1]["e"] + 0.05, "hook_aligned": True,
               "hook_line": "He used to work at OpenAI and he was a whistleblower.",
               "punchline": "They hacked the entire database.", "cut_out": cut_out}


class TestCutOut:
    def test_verbatim_passages_are_kept_in_the_interface_format(self):
        w, c = _cut_clip([
            {"first_words": "I saw that episode", "last_words": "listened to it twice.", "why": "aside"},
            {"first_words": "And um I I", "last_words": "I mean", "why": "Hesitation"},
        ])
        assert main.check_cut_out(c, w, 10) == (2, 0)
        assert c["cut_out"] == [{"from": "I saw that episode", "to": "listened to it twice.", "why": "aside"},
                                {"from": "And um I I", "to": "I mean", "why": "hesitation"}]
        assert all(set(x) == {"from", "to", "why"} for x in c["cut_out"])
        assert "cut_out_dropped" not in c

    def test_what_is_never_cut(self):
        w, c = _cut_clip([
            {"first_words": "It's not going to", "last_words": "they said.", "why": "digression"},
            {"first_words": "He used to work", "last_words": "a whistleblower.", "why": "digression"},
            {"first_words": "They hacked the", "last_words": "entire database.", "why": "digression"},
            {"first_words": "words nobody said", "last_words": "at all", "why": "aside"},
            {"first_words": "I saw that episode", "last_words": "announced.", "why": "small talk"},
            {"first_words": "They tried hacking", "last_words": "anything, they said.", "why": "screen reading"},
        ])
        kept, dropped = main.check_cut_out(c, w, 10)
        reasons = [d["reason"] for d in c["cut_out_dropped"]]
        assert kept == 0 and dropped == 6, c
        assert reasons[0] == "holds a negation or a nuance"
        assert reasons[1].startswith("first words not found in the clip after its opening sentence")
        assert reasons[2] == "touches the payoff"
        assert reasons[3].startswith("first words not found")
        assert reasons[4] == "unknown reason"
        assert reasons[5] == "holds a negation or a nuance" and c["cut_out_dropped"][5]["why"] == "screen_reading"

    def test_at_most_three_no_overlap_and_the_clip_keeps_its_minimum(self):
        w, c = _cut_clip([
            {"first_words": "I saw that", "last_words": "episode announced.", "why": "aside"},
            {"first_words": "I saw that", "last_words": "it twice.", "why": "aside"},
            {"first_words": "I have listened", "last_words": "it twice.", "why": "aside"},
            {"first_words": "They trained these", "last_words": "solve problems.", "why": "digression"},
            {"first_words": "And um I", "last_words": "I mean", "why": "hesitation"},
        ])
        main.check_cut_out(c, w, 10)
        assert [x["from"] for x in c["cut_out"]] == ["I saw that", "I have listened", "They trained these"]
        assert [d["reason"] for d in c["cut_out_dropped"]] == ["overlaps another passage", "more than 3"]
        w, c = _cut_clip([{"first_words": "I saw that", "last_words": "solve problems.", "why": "digression"}])
        main.check_cut_out(c, w, 40)
        assert c["cut_out"] == [] and "under 40s" in c["cut_out_dropped"][0]["reason"]

    def test_garbage_is_harmless(self):
        w, c = _cut_clip("not a list")
        assert main.check_cut_out(c, w, 10) == (0, 0) and c["cut_out"] == []
        w, c = _cut_clip([None, "x", {"why": "aside"}])
        assert main.check_cut_out(c, w, 10) == (0, 1) and c["cut_out"] == []


# --- prompt, schema, stats -----------------------------------------------------------------------

class TestPromptAndSchema:
    def test_the_contradiction_is_gone(self):
        p = gw.PLAYBOOK_DETAIL_ADDENDUM
        assert "end it earlier" not in p and "never start later" not in p
        assert "NEVER end before the payoff" in p and "open on a later sentence" in p and "skip the moment" in p
        assert "`punchline` must lie between `start` and `end`" in p

    def test_threat_is_a_preference_never_a_filter(self):
        p = gw.PLAYBOOK_DETAIL_ADDENDUM
        assert "order of preference to RANK" in p and "NEVER a reason to leave a good moment out" in p
        assert p.index("threat that can reach the viewer") < p.index("viewer's own mind") < p.index("debate about")
        for n in playbook.MOMENT_NATURES[:-1]:
            assert n in p, n
        # The HOW MANY rule is untouched: every window is still worked through.
        flat = " ".join(gw.DETAIL_PROMPT_TEMPLATE.split())
        assert ("Work through EVERY candidate window" in flat
                and "a window that yields nothing should be the exception, not the norm" in flat)

    def test_opening_and_cut_out_rules(self):
        flat = " ".join(gw.PLAYBOOK_DETAIL_ADDENDUM.split())
        assert "a request to someone in the room" in flat and "pull that up" in flat
        assert "a question the viewer would ask" in flat and "points back at what came before" in flat
        assert "`cut_out`: 0 to 3 passages" in flat and "NEVER a negation or a nuance" in flat
        assert "never the payoff (`punchline`)" in flat and "never the opening sentence (`hook_line`)" in flat

    def test_schema(self):
        props = gw.DetailResponsePlaybook.model_json_schema()
        item = props["$defs"]["DetailClipModelPlaybook"]["properties"]
        assert {"moment_nature", "cut_out", "punchline", "hook_line"} <= set(item)
        cut = props["$defs"]["CutOutModel"]["properties"]
        assert set(cut) == {"first_words", "last_words", "why"}
        clip = gw.DetailClipModelPlaybook.model_validate(
            {"start": 1, "end": 2, "source_window_id": "w", "predicted_score": 5, "video_description_for_tiktok": "",
             "video_description_for_instagram": "", "video_title_for_youtube_short": "", "viral_hook_text": ""})
        assert clip.model_dump()["cut_out"] == [] and clip.moment_nature == ""
        # Claude's path inlines the nested model (ai_brain.json_schema).
        flat = json.dumps(ai_brain.json_schema(gw.DetailResponsePlaybook))
        assert "$ref" not in flat and "first_words" in flat

    def test_moment_nature_and_payoff_reach_the_stats(self, tmp_path):
        shorts = [{"start": 1.0, "end": 30.0, "video_title_for_youtube_short": "Can a tumor make you a killer?",
                   "video_description_for_tiktok": "a", "video_description_for_instagram": "b",
                   "moment_nature": "made_up"},
                  {"start": 40.0, "end": 70.0, "video_title_for_youtube_short": "Can stress rewire you?",
                   "video_description_for_tiktok": "a", "video_description_for_instagram": "b",
                   "moment_nature": "person_at_stake", "end_on_payoff": True}]
        tokens = playbook.prepare(shorts, "x_Some Talk-001.mkv", {})
        assert shorts[0]["moment_nature"] == "other" and shorts[1]["moment_nature"] == "person_at_stake"
        out = json.load(open(playbook.export_clip(shorts[1], str(tmp_path), "x_clip_2.mp4", tokens), encoding="utf-8"))
        assert out["moment_nature"] == "person_at_stake" and out["end_on_payoff"] is True
        assert out["payoff_outside"] == ""
        shorts[0]["payoff_outside"] = "said 35s after the end"
        out = json.load(open(playbook.export_clip(shorts[0], str(tmp_path), "x_clip_1.mp4", tokens), encoding="utf-8"))
        assert out["payoff_outside"] == "said 35s after the end" and out["moment_nature"] == "other"


# --- auto-publish -------------------------------------------------------------------------------

def test_auto_publish_leaves_out_a_clip_whose_payoff_is_outside(tmp_path, monkeypatch):
    app = pytest.importorskip("app")
    job = tmp_path / "jobL4"
    job.mkdir()
    clips = []
    for i, (score, outside) in enumerate(((90, "said 35s after the end"), (80, ""), (70, ""))):
        (job / f"c{i}.mp4").write_bytes(b"x")
        clips.append({"video_url": f"/videos/jobL4/c{i}.mp4", "predicted_score": score,
                      **({"payoff_outside": outside} if outside else {})})
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setitem(app.jobs, "jobL4", {"logs": [], "result": {"clips": clips}, "auto_publish": {
        "upload_key": "k", "profile": "p", "timezone": "UTC", "count": 2, "platforms": ["tiktok"],
        "times": ["08:00"]}})
    sent = []

    async def occupied(*a, **k):
        return set()

    async def captions(*a, **k):
        return {"youtube_title": "t"}

    class Ok:
        status_code = 200
        text = ""

    monkeypatch.setattr(app, "_auto_publish_occupied", occupied)
    monkeypatch.setattr(app, "_build_post_captions", captions)
    monkeypatch.setattr(app, "_save_project_niche", lambda *a, **k: None)
    monkeypatch.setattr(app, "_next_free_slots", lambda n, *a: [f"2026-10-0{6 + i}T08:00" for i in range(n)])
    monkeypatch.setattr(app, "_upload_post_send", lambda key, prof, job_id, index, *a: sent.append(index) or Ok())
    monkeypatch.setattr(app, "_record_upload_post_in_plan", lambda *a, **k: None)
    monkeypatch.setattr(app, "_mark_clip_published", lambda *a, **k: None)
    asyncio.run(app._auto_publish_best("jobL4"))
    assert sent == [1, 2], "the best clip has its payoff outside: never sent"
    logs = app.jobs["jobL4"]["logs"]
    assert any("clip 1 left out" in line and "payoff is outside" in line for line in logs), logs


# --- the real job: JRE #2553-004 (b8e46c24), the model's cached answer ----------------------------

JOB = "b8e46c24-7f5e-48cf-8adc-c2d2677a241e"
ANSWER = "_ai_cache/answers/ae/aea44f14d1bf31952e92ea795b02727814e9b80e3709323ca1082aa7da608825.json"


def _bench():
    here = Path(__file__).resolve()
    for root in [Path(os.environ["OPENSHORTS_BENCH_OUTPUT"])] if os.environ.get("OPENSHORTS_BENCH_OUTPUT") else \
            [p / "output" for p in here.parents]:
        meta = glob.glob(str(root / JOB / "*_metadata.json"))
        if meta and (root / ANSWER).exists():
            return meta[0], root / ANSWER
    return None


@pytest.fixture
def job_b8e46c24(monkeypatch, capsys):
    found = _bench()
    if not found:
        pytest.skip("the bench job b8e46c24 is not on this disk")
    meta = json.load(open(found[0], encoding="utf-8"))
    answer = json.load(open(found[1], encoding="utf-8"))["shorts"]
    # The house recipe ("standard" format, plus.job_env), no niche.
    for name in ("SELECTION_V2", "TITLE_SERIES", "NICHE_TOPICS", "NICHE_ONLY", "CLIP_COUNT_FLOOR", "HOOK_CHECK",
                 "AUDIO_SIGNALS", "LLM_BASE_URL", "TITLE_VARIETY", "CLIP_TARGET_MIN", "CLIP_TARGET_MAX"):
        monkeypatch.delenv(name, raising=False)
    for k, v in {"SYNAPSE_PLAYBOOK": "1", "CLEAN_END": "1", "CLIP_MIN_SECONDS": "15", "CLIP_MAX_SECONDS": "60",
                 "CLIP_TARGET_MIN_SECONDS": "25", "CLIP_TARGET_MAX_SECONDS": "40", "CLIP_DEDUPE_OVERLAP": "0.2",
                 "CLIP_DEDUPE_SECONDS": "8", "GEMINI_API_KEY": "test-key", "AI_BRAIN": "gemini"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", {"by": "test"})

    def fake_stage(client, model_name, items, build_prompt, schema, key, costs, label):
        if label == "score":
            return [{"id": w["id"], "start": w["start"], "end": w["end"], "score": 80, "reason": "r"} for w in items]
        return [dict(c) for c in answer]
    monkeypatch.setattr(main, "_run_stage_split", fake_stage)
    # The open-later pick (an AI call): the first candidate, so the replay stays token-free.
    monkeypatch.setattr(main, "_ask_open_later", lambda prompt: {"clips": [
        {"id": i, "open_on": 1, "viral_hook_text": ""} for i in range(len(answer))]})
    words = [{"w": w["word"], "s": w["start"], "e": w["end"]}
             for seg in meta["transcript"]["segments"] for w in seg.get("words", [])]
    result = main.get_viral_clips(meta["transcript"], words[-1]["e"] + 1.0)
    return result["shorts"], words, capsys.readouterr().out


def _payoff_end(words, clip):
    span = main._payoff_span(words, clip.get("punchline"), float(clip["start"]) - 0.05, float(clip["end"]) + 120)
    return words[span[1]]["e"] if span else None


def _clip(shorts, start):
    return next(s for s in shorts if abs(float(s["start"]) - start) < 15)


def test_job_b8e46c24_replayed(job_b8e46c24):
    shorts, words, out = job_b8e46c24
    assert len(shorts) == 12
    c09 = _clip(shorts, 368.6)
    assert 403.62 < c09["end"] < 404.1, ("c09 ends after its answer, not on 396.07", c09["end"])
    c11 = _clip(shorts, 1521.0)
    assert c11["payoff_outside"], c11
    tails = {}
    for s in shorts:
        if s.get("payoff_outside"):
            continue
        pe = _payoff_end(words, s)
        assert pe is not None and pe <= s["end"] + 0.05, s
        tails[round(s["start"])] = round(s["end"] - pe, 2)
        assert s["end"] - pe <= main.REACTION_MAX_SECONDS + 0.5, ("tail after the payoff", s["start"], s["end"] - pe)
        assert s["end"] - s["start"] >= 15
    assert len(tails) == 11
    c08 = _clip(shorts, 273.0)
    assert c08["start"] >= 273.44 and c08["hook_line"].startswith("now people"), "'Also,' is not heard"
    c03 = _clip(shorts, 612.1)
    assert c03["start"] >= 612.18, "the orphan 'know' is not heard"
    c02 = _clip(shorts, 749.3)
    assert c02.get("opens_on_request"), "the Perplexity request is flagged"
    c02_end = " ".join(w["w"] for w in words if c02["end"] - 2.5 <= w["s"] < c02["end"])
    assert "whoa" in c02_end.lower(), ("Joe's reaction after the payoff is kept (4 s)", c02_end)
    assert "PAYOFF IS OUTSIDE the clip" in out and "Payoff ending: 11/12" in out
