"""Lot « Sélection » (5-oct-2026): the opening chosen among real sentence starts and weighed in the ranking,
the deterministic guards on the first seconds (pauses, capitals, words pointing back), the one-minute
ceiling, and the already-clipped check (off). No AI call, no token, no network."""
import json

import pytest

main = pytest.importorskip("main")
import ai_brain  # noqa: E402
import already_clipped  # noqa: E402
import gemini_worker as gw  # noqa: E402
import playbook  # noqa: E402

FILL = "it happens to people every day without them knowing. "      # 9 words = 4.5 s


def mk(text, step=0.5, length=0.4):
    return [{"w": w, "s": round(i * step, 3), "e": round(i * step + length, 3)} for i, w in enumerate(text.split())]


def first(words, word, after=0.0):
    return next(i for i, w in enumerate(words) if w["w"] == word and w["s"] >= after)


def gap_before(words, k, gap):
    """Shift word k and everything after it by ``gap`` s (a pause before word k)."""
    for w in words[k:]:
        w["s"] = round(w["s"] + gap, 3)
        w["e"] = round(w["e"] + gap, 3)
    return words


# --- sentence starts Whisper did not punctuate ------------------------------------------------------

class TestSentenceStarts:
    def test_a_capital_after_a_short_pause_opens_a_sentence(self):
        # JRE #2515-001: "...and a few others | Was interested in what they do" (0.63 s, no full stop).
        w = mk("we met him and a few others Was interested in what they do and it was clear was it not")
        k = first(w, "Was")
        assert not main._opens_sentence(w, k)                      # no pause: still one sentence
        gap_before(w, k, 0.3)
        assert main._capital_start(w, k) and main._opens_sentence(w, k)

    def test_names_acronyms_and_i_never_open_a_sentence_by_their_capital(self):
        w = mk("he used to work at OpenAI and then AI was there and I said Michelle was right openai")
        for word in ("AI", "I", "Michelle"):
            k = first(w, word)
            gap_before(w, k, 0.5)
            assert not main._capital_start(w, k), word
        # "OpenAI" is written in lower case elsewhere in this transcript: then it is a common word.
        k = first(w, "OpenAI")
        gap_before(w, k, 0.5)
        assert main._capital_start(w, k)

    def test_a_pause_inside_a_sentence_is_no_start(self):
        # JRE #2515-001: "...actually a part of a cell | that's in another being" (1.4 s pause).
        w = mk("it is actually a part of a cell that's in another being and so on " + FILL * 3)
        k = first(w, "that's")
        gap_before(w, k, 1.4)
        assert main._is_boundary(w, k - 1)                         # the pause still ends a clip there
        assert not main._opens_sentence(w, k)                      # ...but no clip opens on "that's in"
        w2 = mk("we did it all. " + "then nothing happened at all. " + FILL)
        assert main._opens_sentence(w2, first(w2, "then"))         # a full stop still opens anything

    @pytest.mark.parametrize("line", ["Because they can't patent it.", "Which is why nobody tests it.",
                                      "That's why they hate it.", "and that’s why it fails", "this is why"])
    def test_lines_that_point_back(self, line):
        assert main._OPENS_ON_BEFORE.match(line.lower()), line

    @pytest.mark.parametrize("line", ["Because of one tweet, I lost", "Whichever drug you take"])
    def test_lines_that_do_not(self, line):
        assert not main._OPENS_ON_BEFORE.match(line.lower()), line


# --- the marks the clip choice opens on ---------------------------------------------------------------

class TestMarkedText:
    def test_marks_sentence_starts_stepped_over_fillers_never_pointing_back(self):
        w = mk("So the brain lies. Also, the second thing was weird. Can you pull that up? "
               "You know, your liver pays for it. Then it was gone.")
        text = main.marked_text(w, 0.0, 100.0)
        assert text.startswith(f"So [{w[first(w, 'the')]['s']:.1f}] the brain lies.")   # "So" stepped over
        assert "[" not in text.split("the brain lies.")[1].split("the second thing")[0]   # "Also, the second thing"
        assert f"[{w[first(w, 'Can')]['s']:.1f}]" not in text                        # a request
        assert f"[{w[first(w, 'your')]['s']:.1f}] your liver" in text               # "You know," stepped over
        assert f"[{w[first(w, 'Then')]['s']:.1f}]" not in text                       # "Then" points back
        # The words themselves are all there, in order.
        assert text.replace("[", " [").split() and all(x["w"] in text for x in w)

    def test_only_the_window(self):
        w = mk("One. Two. Three. Four. Five.")
        text = main.marked_text(w, 1.0, 1.6)
        assert text == "[1.0] Three. [1.5] Four."

    def test_the_detail_prompt_reads_the_marks(self, monkeypatch):
        tr = {"language": "en", "segments": [{"start": 0, "end": 60, "text": "x", "words": [
            {"word": w["w"], "start": w["s"], "end": w["e"]} for w in mk("Your brain lies. " + FILL * 12)]}]}
        for k, v in {"SYNAPSE_PLAYBOOK": "1", "GEMINI_API_KEY": "test-key", "AI_BRAIN": "gemini",
                     "CLIP_MIN_SECONDS": "15", "CLIP_MAX_SECONDS": "60"}.items():
            monkeypatch.setenv(k, v)
        for name in ("NICHE_TOPICS", "AUDIO_SIGNALS", "CLIP_TARGET_MAX_SECONDS", "CLEAN_END", "LLM_BASE_URL"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", {"by": "test"})
        seen = {}

        def fake_stage(client, model_name, items, build_prompt, schema, key, costs, label):
            if label == "score":
                return [{"id": x["id"], "start": x["start"], "end": x["end"], "score": 80, "reason": "r"} for x in items]
            seen["prompt"] = build_prompt(items)
            return [{"start": 0.0, "end": 30.0, "source_window_id": items[0]["id"], "predicted_score": 80,
                     "video_description_for_tiktok": "", "video_description_for_instagram": "",
                     "video_title_for_youtube_short": "Does your brain lie to you?", "viral_hook_text": "Your brain lies",
                     "hook_line": "Your brain lies.", "punchline": "without them knowing.", "opening_score": 90}]
        monkeypatch.setattr(main, "_run_stage_split", fake_stage)
        out = main.get_viral_clips(tr, 61.0)
        assert "[0.0] Your brain lies." in seen["prompt"]
        assert "THE FIRST 5 SECONDS DECIDE" in seen["prompt"]
        clip = out["shorts"][0]
        assert clip["moment_score"] == 80 and clip["opening_score"] == 90
        assert clip["opening_flags"] == [] and clip["predicted_score"] == 85


# --- what the code checks on the final cut -----------------------------------------------------------

class TestCheckOpening:
    def clip(self, words, start_word, **kw):
        return {"start": words[first(words, start_word)]["s"] - 0.08, "end": 40.0,
                "video_title_for_youtube_short": kw.pop("title", "Can a pill hurt your liver?"),
                "viral_hook_text": kw.pop("hook", "Your liver pays for it"), **kw}

    def test_a_clean_opening(self):
        w = mk("Your liver pays for every pill you take. " + FILL * 6)
        c = self.clip(w, "Your")
        assert main.check_opening(c, w) == [] and c["opening_flags"] == []

    def test_mid_sentence(self):
        w = mk("and this is what every pill does to your liver over the years. " + FILL * 6)
        c = self.clip(w, "every")
        assert "mid_sentence" in main.check_opening(c, w)
        c2 = self.clip(w, "and", start_mid_sentence=True)
        assert "mid_sentence" in main.check_opening(c2, w)

    def test_points_back_and_request(self):
        w = mk("The liver. Because they can't patent it, your liver pays. " + FILL * 6)
        assert "points_back" in main.check_opening(self.clip(w, "Because"), w)
        w2 = mk("The liver. Can you pull that up for me, the liver study? " + FILL * 6)
        assert "request" in main.check_opening(self.clip(w2, "Can"), w2)

    def test_a_pronoun_nobody_met_unless_the_hook_names_the_person(self):
        w = mk("Ok. They have side effects on your liver. " + FILL * 6)
        assert "pronoun" in main.check_opening(self.clip(w, "They"), w)
        w2 = mk("Ok. He was dying and his liver failed. " + FILL * 6)
        assert "pronoun" in main.check_opening(self.clip(w2, "He", hook="Your liver can just stop"), w2)
        assert "pronoun" not in main.check_opening(self.clip(w2, "He", hook="A dying doctor tried one drug"), w2)

    def test_the_subject_said_late(self):
        w = mk("So listen to this one, it's wild and nobody saw it coming at all, but then the liver "
               "just stopped. " + FILL * 4)
        c = self.clip(w, "listen")
        assert "topic_late" in main.check_opening(c, w)
        c2 = self.clip(w, "listen", title="Can nobody see it coming?", hook="Nobody saw it coming")
        assert "topic_late" not in main.check_opening(c2, w)


# --- the ranking ----------------------------------------------------------------------------------------

class TestRank:
    def test_the_opening_weighs_half(self):
        c = {"predicted_score": 80, "opening_score": 40}
        assert main.rank_by_opening(c) == 60 and c["moment_score"] == 80
        # Idempotent: it starts again from the moment.
        assert main.rank_by_opening(c) == 60

    def test_no_opening_score_is_the_moment_alone(self):
        c = {"predicted_score": 80}
        assert main.rank_by_opening(c) == 80
        c["opening_flags"] = ["mid_sentence"]
        assert main.rank_by_opening(c) == round(0.5 * 80 + 0.5 * (80 - main.OPENING_PENALTY["mid_sentence"]))

    def test_flags_cost_the_opening_part_only(self):
        c = {"predicted_score": 80, "opening_score": 30, "opening_flags": ["request", "pronoun", "topic_late"]}
        assert main.rank_by_opening(c) == 40      # 0.5 x 80 + 0.5 x max(0, 30 - 31)

    def test_the_niche_cut_survives_a_new_ranking(self):
        c = {"predicted_score": 80, "opening_score": 60}
        main.rank_by_opening(c)                   # 70, right after the clip choice
        playbook.apply_niche([c], {"topics": ["substances"], "weight": 15.0, "only": False})
        assert c["predicted_score"] == 55 and c["predicted_score_raw"] == 70
        c["opening_flags"] = ["points_back"]
        main.rank_by_opening(c)                   # 0.5 x 80 + 0.5 x 45 = 62.5 -> 62, minus the 15 of the niche
        assert c["predicted_score_raw"] == 62 and c["predicted_score"] == 47

    def test_already_clipped_costs_points_never_the_clip(self):
        c = {"predicted_score": 80, "opening_score": 80, "already_clipped": {"channel": "Big"}}
        assert main.rank_by_opening(c) == 80 - already_clipped.PENALTY

    def test_garbage_is_harmless(self):
        assert main.rank_by_opening({"predicted_score": None}) is None
        c = {"predicted_score": "85", "opening_score": "nope"}
        assert main.rank_by_opening(c) == 85
        assert main.rank_by_opening({"predicted_score": 70, "opening_score": 250}) == 85

    def test_open_later_takes_the_new_openings_score(self):
        w = mk("Fluff here. " + "Your liver pays for every pill. " + FILL * 9 + "So it ends badly.")
        c = {"start": 0.0, "end": w[-1]["e"] + 0.2, "over_target": "payoff needs the length",
             "punchline": "So it ends badly.", "opening_score": 20, "opening_misses": ["tension"],
             "viral_hook_text": "x", "video_title_for_youtube_short": "t"}
        moved = main.shorten_to_target([c], w, 15, (25, 40), ask=lambda p: {"clips": [
            {"id": 0, "open_on": 1, "opening_score": 77, "viral_hook_text": ""}]})
        assert moved == 1 and c["opening_score"] == 77 and "opening_misses" not in c
        assert "opening_score" in gw.OPEN_LATER_SCHEMA["properties"]["clips"]["items"]["properties"]
        assert "names the subject and sets the tension" in " ".join(gw.OPEN_LATER_PROMPT.split())


# --- prompt, schema, stats -------------------------------------------------------------------------------

class TestPromptAndSchema:
    def test_prompt(self):
        flat = " ".join(gw.PLAYBOOK_DETAIL_ADDENDUM.split())
        assert "THE FIRST 5 SECONDS DECIDE" in flat and '"[<seconds>]" marks a sentence' in flat
        assert "`start` is its number" in flat and "`opening_score`: 0-100" in flat
        assert "`opening_misses`" in flat and "`predicted_score` rates the MOMENT itself" in flat
        for c in playbook.OPENING_CRITERIA:
            assert c in flat
        assert "loops into its own start" in flat and "THE CLIPS AS A SET" in flat
        # Still a preference, never a filter (her reserve), and every window is still worked through.
        assert "NEVER a reason to leave a good moment out" in flat
        assert "never a reason to leave out a strong moment" in flat
        assert "Work through EVERY candidate window" in " ".join(gw.DETAIL_PROMPT_TEMPLATE.split())
        assert '"kratom"' in gw.QUESTION_TITLE_ADDENDUM

    def test_schema(self):
        props = gw.DetailResponsePlaybook.model_json_schema()["$defs"]["DetailClipModelPlaybook"]["properties"]
        assert {"opening_score", "opening_misses"} <= set(props)
        clip = gw.DetailClipModelPlaybook.model_validate(
            {"start": 1, "end": 2, "source_window_id": "w", "predicted_score": 5, "video_description_for_tiktok": "",
             "video_description_for_instagram": "", "video_title_for_youtube_short": "", "viral_hook_text": ""})
        assert clip.opening_score is None and clip.opening_misses == []
        flat = json.dumps(ai_brain.json_schema(gw.DetailResponsePlaybook))
        assert "$ref" not in flat and "opening_misses" in flat

    def test_the_opening_reaches_the_stats(self, tmp_path):
        shorts = [{"start": 1.0, "end": 30.0, "video_title_for_youtube_short": "Can a tumor make you a killer?",
                   "video_description_for_tiktok": "a", "video_description_for_instagram": "b",
                   "predicted_score": 70, "moment_score": 80, "opening_score": 60,
                   "opening_misses": ["tension", "made_up"], "opening_flags": ["pronoun"]}]
        tokens = playbook.prepare(shorts, "x_Some Talk-001.mkv", {})
        assert shorts[0]["opening_misses"] == ["tension"]
        out = json.load(open(playbook.export_clip(shorts[0], str(tmp_path), "x_clip_1.mp4", tokens),
                             encoding="utf-8"))
        assert out["score"] == 70 and out["moment_score"] == 80 and out["opening_score"] == 60
        assert out["opening_misses"] == ["tension"] and out["opening_flags"] == ["pronoun"]
        assert out["already_clipped"] is None


# --- the real job: JRE #2553-004 (b8e46c24), the model's cached answer (test_recit_payoff's replay) --------

from test_recit_payoff import _clip, job_b8e46c24  # noqa: E402,F401


def test_job_b8e46c24_openings_weighed(job_b8e46c24):
    shorts, words, out = job_b8e46c24
    c02 = _clip(shorts, 749.3)          # "Can you put that into perplexity and see what leading cause of death?"
    assert "request" in c02["opening_flags"], c02["opening_flags"]
    assert c02["predicted_score"] < c02["moment_score"]
    for s in shorts:
        assert "moment_score" in s and isinstance(s["opening_flags"], list)
        if not s["opening_flags"]:
            assert s["predicted_score"] == s["moment_score"] or s.get("off_niche")
    assert "🎬 Openings:" in out
