"""Recette « références » (9-oct-2026, RECETTE_REFERENCES.md §3-4): OptimalHealth's titles (one everyday thing,
4-8 words, Hidden / Really / Trick..., no name, no emoji, never "Big Pharma"), the moment about an everyday thing
weighed in the ranking (never a filter), and the first sentence that says the clip's thing within 3 s (no title on
screen any more), else the clip opens on the later sentence that does. No AI call, no token, no network."""
import pytest

main = pytest.importorskip("main")
import gemini_worker as gw  # noqa: E402
import playbook  # noqa: E402
import plus  # noqa: E402
import rework  # noqa: E402

FILL = "it happens to people every day without them knowing. "      # 9 words = 4.5 s


def mk(text, step=0.5, length=0.4):
    return [{"w": w, "s": round(i * step, 3), "e": round(i * step + length, 3)} for i, w in enumerate(text.split())]


def first(words, word, after=0.0):
    return next(i for i, w in enumerate(words) if w["w"] == word and w["s"] >= after)


@pytest.fixture
def references(monkeypatch):
    monkeypatch.setenv("TITLE_STYLE", "references")


# --- the style switch ------------------------------------------------------------------------------------------

class TestStyle:
    def test_the_house_recipe_says_references(self, monkeypatch):
        monkeypatch.delenv("TITLE_STYLE", raising=False)
        assert plus.SELECTION["title_style"] == "references" and playbook.title_style() == "references"
        monkeypatch.setenv("TITLE_STYLE", "question")
        assert playbook.title_style() == "question"
        monkeypatch.setenv("TITLE_STYLE", "nonsense")
        assert playbook.title_style() == "references"           # back to the house recipe

    def test_job_env(self):
        env = plus.job_env({"name": "Joe Rogan"})
        assert env["TITLE_STYLE"] == "references" and env["OPENING_SUBJECT_FIRST"] == "1"
        assert env["SELECTION_WEIGHTS"] and env["FACE_CHECK"] == "1"

    def test_every_place_that_writes_a_title_gets_the_style(self, monkeypatch):
        monkeypatch.setenv("SYNAPSE_PLAYBOOK", "1")
        monkeypatch.setenv("TITLE_VARIETY", "1")
        monkeypatch.setenv("TITLE_STYLE", "references")
        detail = main.playbook_detail_rules(60)
        assert gw.REFERENCES_TITLE_ADDENDUM in detail and gw.QUESTION_TITLE_ADDENDUM not in detail
        assert gw.REFERENCES_VARIETY_ADDENDUM in detail and gw.TITLE_VARIETY_ADDENDUM not in detail
        seen = {}
        monkeypatch.setattr(rework, "_generate_json_with_fallback",
                            lambda prompt, *a, **k: seen.setdefault("p", prompt) and {})
        rework.generate_clip_copy("melatonin is a hormone", "en", None, playbook=True)
        assert gw.REFERENCES_TITLE_ADDENDUM in seen["p"]
        monkeypatch.setenv("TITLE_STYLE", "question")
        assert gw.QUESTION_TITLE_ADDENDUM in main.playbook_detail_rules(60)


# --- the title prompt ------------------------------------------------------------------------------------------

class TestTitlePrompt:
    def test_the_rule_and_the_real_examples(self):
        flat = " ".join(gw.REFERENCES_TITLE_ADDENDUM.split())
        for must in ("4 to 8 words", "no emoji", "A question OR a statement", "ONE THING THE VIEWER KNOWS",
                     "The Hidden Problem With Melatonin", "The Eye Trick That Helps You Fall Asleep",
                     "What's Really In Your Shower Water?", "What Ibuprofen Really Does To Your Body",
                     "Hidden, Really, Actually, Trick, Fastest, Truth, Myth", "when it is TRUE of the clip",
                     "TRUE TO THE CLIP", "NO NAMES", "Big Pharma", "prescription drug", "suicide",
                     "educational or preventive", "NEVER REPHRASES THE TITLE"):
            assert must in flat, must
        # The closed-question rule is gone from this style.
        assert "MUST START WITH" not in flat and "FORBIDDEN" not in flat

    def test_the_detail_pass_asks_for_the_subject_and_the_everyday_thing(self):
        flat = " ".join(gw.PLAYBOOK_DETAIL_ADDENDUM.split())
        assert "NO TITLE ON SCREEN" in flat and "the first sentence heard IS the hook" in flat
        assert "within ~3 seconds" in flat and "open on the later mark where it is said" in flat
        assert "`subject_words`" in flat and "`everyday_thing`" in flat
        # A weight, never a filter (her reserve: « ne ferme pas la sélection »).
        assert "A PREFERENCE, never a filter" in flat and "`predicted_score` is NOT changed for it" in flat
        props = gw.DetailResponsePlaybook.model_json_schema()["$defs"]["DetailClipModelPlaybook"]["properties"]
        assert {"subject_words", "everyday_thing"} <= set(props)


# --- the title checks ------------------------------------------------------------------------------------------

class TestTitleProblems:
    @pytest.mark.parametrize("title", ["The Hidden Problem With Melatonin", "The Eye Trick That Helps You Fall Asleep",
                                       "What's Really In Your Shower Water?", "What Ibuprofen Really Does To Your Body",
                                       "The Fastest Way To Calm Down", "Can Alzheimer's Actually Be Reversed?"])
    def test_their_titles_pass(self, references, title):
        assert playbook.title_problems(title) == []

    def test_what_fails(self, references):
        assert playbook.title_problems("Melatonin Lies")[0].startswith("2 words")
        assert "words" in playbook.title_problems("The Hidden Problem With The Melatonin Your Doctor Gave You")[0]
        assert "an emoji (none in this niche's titles)" in playbook.title_problems("The Hidden Problem With Melatonin 😳")
        assert any("held back" in p for p in playbook.title_problems("Is Big Pharma Scared Of You?"))
        assert any("held back" in p for p in playbook.title_problems("People Are Sharing Their Prescription Pills"))
        assert any("subject not named" in p for p in playbook.title_problems("The Truth About This Guy Now"))
        # The question style still checks its own rules.
        assert playbook.title_problems("The Hidden Problem With Melatonin", style="question")

    def test_a_name_is_still_caught(self, references):
        c = {"video_title_for_youtube_short": "What Huberman Really Thinks Of Melatonin"}
        assert playbook.check_title(c, ["huberman"]) and playbook.check_format(c)

    def test_the_set(self, references):
        rows = [("The Hidden Problem With Melatonin", 80), ("The Hidden Cost Of Coffee", 70),
                ("The Hidden Danger Of Ibuprofen", 60), ("What Your Phone Really Does To Focus", 75),
                ("Is Your Shower Water Really Clean?", 65), ("Can Lidocaine Actually Stop Cancer?", 72)]
        shorts = [{"video_title_for_youtube_short": t, "predicted_score": s} for t, s in rows]
        out = playbook.title_set_problems(shorts)
        # "hidden" three times: the lowest-scoring loses it; "really" twice and "actually" once are the formula.
        assert out == {2: {"issues": ["'hidden' is already in 2 other titles"], "avoid": ["hidden"]}}

    def test_the_retitle_prompt(self, references):
        p = playbook.retitle_prompt([{"id": 0, "title": "t"}], ["x"])
        assert "The Hidden Problem With Melatonin" in p and "Big Pharma" in p and "closed question" not in p


# --- the first sentence says the thing --------------------------------------------------------------------------

C11 = ("We had a gentleman the other day on. He used to work at OpenAI. "      # 14 words: the run-up (7 s)
       "They got like 1,200 different agents. 700 of them escaped. "          # "escaped" at 11.5 s
       + FILL * 4 + "So they tried hacking into the system.")


def _c11(**kw):
    w = mk(C11)
    c = {"start": 0.0, "end": w[-1]["e"] + 0.2, "subject_words": "escaped",
         "punchline": "So they tried hacking into the system.", "hook_line": "We had a gentleman the other day on."}
    c.update(kw)
    return w, c


class TestOpenOnSubject:
    def test_opens_on_the_sentence_that_says_it(self):
        w, c = _c11()
        new = main.open_on_subject(c, w, 15)
        k = first(w, "700")
        assert new == main._start_at(w, k) == c["start"]
        assert c["hook_line"] == "700 of them escaped."
        assert c["subject_said_at"] == 1.5 and c["hook_aligned"]
        assert c["opening_moved_for_subject"]["said_at_before"] == 11.5
        assert c["opening_moved_for_subject"]["from"] == 0.0
        assert main.check_opening(c, w) == []

    def test_said_early_stays(self):
        w, c = _c11(subject_words="gentleman")
        assert main.open_on_subject(c, w, 15) is None and c["start"] == 0.0 and c["subject_said_at"] == 1.5

    def test_never_under_the_minimum(self):
        w, c = _c11()
        assert main.open_on_subject(c, w, 30) is None and c["start"] == 0.0
        assert "subject_late" in main.check_opening(c, w)

    def test_never_past_the_payoff(self):
        w, c = _c11(punchline="700 of them escaped.")
        assert main.open_on_subject(c, w, 5) is None

    def test_never_on_a_line_pointing_back(self):
        w = mk("We had a gentleman the other day on. That's when the agents escaped. " + FILL * 4 + "The end is here.")
        c = {"start": 0.0, "end": w[-1]["e"] + 0.2, "subject_words": "escaped", "punchline": "The end is here."}
        assert main.open_on_subject(c, w, 10) is None

    def test_said_late_in_a_long_first_sentence_stays(self):
        # JRE #2553 c10: "They used AI ... to find that women who had breast cancer surgery where lidocaine was
        # used..." — the first sentence says the thing (at 6.9 s); the next to name it comes after the finding.
        w = mk("They used AI and other tools to find that women who had surgery where lidocaine was used did "
               "better. " + FILL * 2 + "Now lidocaine is standard in good places. " + FILL * 2 + "That is the end.")
        c = {"start": 0.0, "end": w[-1]["e"] + 0.2, "subject_words": "lidocaine", "punchline": "That is the end."}
        assert main.open_on_subject(c, w, 10) is None and c["subject_said_at"] == 7.0
        assert "subject_late" in main.check_opening(c, w)

    def test_the_new_first_sentence_says_it(self):
        # A sentence start 2 s before the word, but the word is in the NEXT sentence: not that one.
        w = mk("We had a gentleman the other day on. Boxes. 700 of them escaped. " + FILL * 4 + "The end is here.")
        c = {"start": 0.0, "end": w[-1]["e"] + 0.2, "subject_words": "escaped", "punchline": "The end is here."}
        assert main.open_on_subject(c, w, 10) == main._start_at(w, first(w, "700"))

    def test_the_subject_is_matched_as_a_phrase(self):
        # Bench of 9-oct (c06): "people should retire" hit on the first "people" when any word counted.
        w = mk("I see these people on X and they are upset. " + FILL * 3 + "This is why people should retire.")
        c = {"start": 0.0, "end": w[-1]["e"] + 0.2, "subject_words": "people should retire"}
        # FILL says "people" too, never followed by "retire".
        assert main.subject_said_at(c, w) == w[first(w, "people", 19.0)]["s"] == 20.0
        # A thing written with a hyphen in the transcript or in the subject.
        w = mk("Ask the on-call physician how long he has been awake.")
        assert main.subject_said_at({"start": 0.0, "end": 9.0, "subject_words": "on call physician"}, w) == 1.0

    def test_never_past_the_first_mention(self):
        # The first mention is mid-sentence (no opening there): opening on a later mention would cut what the
        # clip says about the thing (bench c10: "now lidocaine is standard" 13.8 s later, past the finding).
        w = mk("We looked at the records. They found that in the old files of so many women lidocaine helped. " + FILL * 2
               + "Now lidocaine is standard in good places. " + FILL * 2 + "That is the end.")
        c = {"start": 0.0, "end": w[-1]["e"] + 0.2, "subject_words": "lidocaine", "punchline": "That is the end."}
        assert main.open_on_subject(c, w, 10) is None and c["subject_said_at"] == 8.0

    def test_never_heard_is_late(self):
        w, c = _c11(subject_words="dolphin")
        assert main.open_on_subject(c, w, 15) is None and c["subject_said_at"] is None
        assert "subject_late" in main.check_opening(c, w)

    def test_without_subject_words_the_old_topic_check(self):
        w, c = _c11(subject_words="", video_title_for_youtube_short="Dolphins", viral_hook_text="")
        assert main.open_on_subject(c, w, 15) is None
        assert "topic_late" in main.check_opening(c, w)


# --- the everyday thing: a weight, never a filter ---------------------------------------------------------------

WEIGHTS = '{"everyday": 5, "everyone": 6, "many": 2, "practical": 3, "two_voices": 4, "face_small": 20}'


class TestEveryday:
    def test_a_weight_with_the_switch(self, monkeypatch):
        c = {"predicted_score": 70, "opening_score": 70, "everyday_thing": "melatonin"}
        monkeypatch.delenv("SELECTION_WEIGHTS", raising=False)
        assert main.rank_by_opening(dict(c)) == 70
        monkeypatch.setenv("SELECTION_WEIGHTS", WEIGHTS)
        assert main.rank_by_opening(dict(c)) == 75
        assert main.rank_by_opening({**c, "everyday_thing": ""}) == 70
        assert main.rank_by_opening({**c, "everyday_said": False}) == 70

    def test_checked_in_the_words(self, monkeypatch):
        monkeypatch.setenv("SELECTION_WEIGHTS", WEIGHTS)
        w = mk("If you take melatonin every night here is what happens. " + FILL * 3)
        said = {"start": 0.0, "end": w[-1]["e"], "predicted_score": 60, "opening_score": 60,
                "everyday_thing": "melatonin"}
        not_said = {**said, "everyday_thing": "coffee"}
        main.rank_openings([said, not_said], w)
        assert said["everyday_said"] and said["selection_weights"] == {"everyday": 5}
        assert not not_said["everyday_said"] and "selection_weights" not in not_said


# --- who is concerned, two voices, the face: weights, never filters (decoding of OptimalHealth, 9-oct) ---------

class TestAudienceWeights:
    def test_the_points(self, monkeypatch):
        monkeypatch.setenv("SELECTION_WEIGHTS", WEIGHTS)
        base = {"predicted_score": 60, "opening_score": 60}
        rank = lambda **kw: main.rank_by_opening({**base, **kw})  # noqa: E731
        assert rank() == 60
        assert rank(audience_reach="everyone") == 66 and rank(audience_reach="many") == 62
        assert rank(audience_reach="few") == 60 and rank(audience_reach="nonsense") == 60
        # A practical tip counts on a thing many people share, not on a specialist topic.
        assert rank(audience_reach="everyone", practical=True) == 69 and rank(audience_reach="few", practical=True) == 60
        assert rank(two_voices=True) == 64
        # A small face weighs heavily against, still never drops the clip.
        assert rank(face_small=True) == 40
        c = {**base, "everyday_thing": "coffee", "audience_reach": "everyone", "practical": True, "two_voices": True}
        main.rank_by_opening(c)
        assert c["predicted_score"] == 78
        assert c["selection_weights"] == {"everyday": 5, "everyone": 6, "practical": 3, "two_voices": 4}

    def test_off_without_the_switch(self, monkeypatch):
        monkeypatch.delenv("SELECTION_WEIGHTS", raising=False)
        c = {"predicted_score": 60, "opening_score": 60, "audience_reach": "everyone", "two_voices": True,
             "face_small": True}
        assert main.rank_by_opening(c) == 60 and "selection_weights" not in c
        monkeypatch.setenv("SELECTION_WEIGHTS", "not json")
        assert main.selection_weights() == {k: 0.0 for k in main.SELECTION_WEIGHT_KEYS}

    def test_the_prompt_and_the_schema(self):
        flat = " ".join(gw.PLAYBOOK_DETAIL_ADDENDUM.split())
        for must in ("WHO IS CONCERNED", "`audience_reach`", '"everyone"', "`practical`", "TWO VOICES",
                     "`two_voices`", "opening ON that question is good", "THE END: stop dead",
                     "never on a question left without its answer"):
            assert must in flat, must
        assert flat.count("never a filter") >= 2 or "PREFERENCE weighed in code, never a filter" in flat
        props = gw.DetailResponsePlaybook.model_json_schema()["$defs"]["DetailClipModelPlaybook"]["properties"]
        assert {"audience_reach", "practical", "two_voices"} <= set(props)
        assert "THE TITLE ECHOES THE FIRST SENTENCE" in gw.REFERENCES_TITLE_ADDENDUM
        assert "The Fastest Way To Calm Down" in gw.REFERENCES_TITLE_ADDENDUM

    def test_the_house_recipe(self):
        env = plus.job_env({"name": "Joe Rogan"})
        assert env["FACE_CHECK"] == "1"
        import json
        assert json.loads(env["SELECTION_WEIGHTS"]) == plus.SELECTION["weights"]
        assert plus.SELECTION["weights"]["face_small"] > 0          # taken off (_weights_for), never a filter
        # OptimalHealth's length (their 48 last Shorts: quartiles 35 / 51 / 60 s), never over a minute; the
        # default for a new profile (the user, 9-oct-2026: « la durée faisant comme lui »).
        assert plus.CLIP_FORMATS["references"] == {"clip_min": 20, "clip_max": 60, "clip_target": [35, 58]}
        assert plus.sanitize({})["format"] == "references"
        assert env["CLIP_TARGET_MIN_SECONDS"] == "35"
        env = plus.job_env({"name": "x", "format": "references"})
        assert (env["CLIP_MIN_SECONDS"], env["CLIP_MAX_SECONDS"], env["CLIP_TARGET_MAX_SECONDS"]) == ("20", "60", "58")


class TestFaceCheck:
    def test_small_faces_are_flagged(self, monkeypatch, tmp_path):
        import numpy as np
        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        shares = iter([0.30, 0.10, 0.08, 0.12, 0.0])
        frame = np.zeros((1000, 1920, 3), dtype=np.uint8)

        class Cap:
            def __init__(self, *_):
                pass

            def set(self, *_):
                pass

            def read(self):
                return True, frame

            def release(self):
                pass

        monkeypatch.setattr(main.cv2, "VideoCapture", Cap)
        monkeypatch.setattr(main, "detect_face_candidates",
                            lambda f: [{"box": [0, 0, 10, round(next(shares) * 1000)]}])
        clips = [{"start": 0.0, "end": 30.0}]
        main.check_faces(clips, str(video))
        assert clips[0]["face_share"] == 0.1 and clips[0]["face_small"] is True
        shares = iter([0.30, 0.26, 0.22, 0.10, 0.28])
        main.check_faces(clips, str(video))
        assert clips[0]["face_share"] == 0.26 and clips[0]["face_small"] is False

    def test_a_profile_falls_back_on_the_person(self, monkeypatch, tmp_path):
        # JRE #2553 c02: Joe side-on reading a screen — no face found, YOLO finds him; a screen alone does not count.
        import numpy as np
        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        frame = np.zeros((1000, 1920, 3), dtype=np.uint8)
        persons = iter([[0, 0, 10, 400], None, [0, 0, 10, 300], None, [0, 0, 10, 350]])

        class Cap:
            def __init__(self, *_):
                pass

            set = lambda *a: None  # noqa: E731

            def read(self):
                return True, frame

            def release(self):
                pass

        monkeypatch.setattr(main.cv2, "VideoCapture", Cap)
        monkeypatch.setattr(main, "detect_face_candidates", lambda f: [])
        monkeypatch.setattr(main, "detect_person_yolo", lambda f: next(persons))
        clips = [{"start": 0.0, "end": 30.0}]
        main.check_faces(clips, str(video))
        assert clips[0]["face_share"] == 0.21 and clips[0]["face_small"] is False

    def test_no_video_no_check(self):
        clips = [{"start": 0.0, "end": 30.0}]
        main.check_faces(clips, None)
        main.check_faces(clips, "/nope.mp4")
        assert "face_small" not in clips[0]
