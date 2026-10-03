"""B-roll v22 « leçons » (4-oct-2026): the chain learns from its own generations (broll_lessons). Every picture decided
after the render and every verdict of the channel's owner is a line of a journal. The code only PROPOSES what it finds in
the last days of it (proposées.md); what the art director, the verifier and the viewer read in their calls (broll_ideas)
is what the owner stands behind: her own verdicts (thumbs down for everyone, thumbs up for the judges) and the lines she
moved to validées.md.
  - the journal: record / recent / clear, where it lives, what switches it off, what it never does (raise);
  - the summary: the owner's verdicts first (from one occurrence), then the lines of validées.md, MAX_LINES at most,
    nothing when there is nothing to say, never a pattern of the checks and never a scene to copy;
  - the proposals: the patterns of the chain's own checks that reach MIN_COUNT, written to proposées.md by ``propose``
    (which summary() calls on the way) for the owner to validate; validées.md is made with a header, never rewritten;
  - where it meets the round of ideas: the block in the three prompts (what the owner liked: the judges only) and the
    flaw of the chosen idea (``idea_flaw``, which broll_v20 notes with the picture).
The check's score and decide()'s "under the face alone" are tested in test_broll_check, the lessons that broll_v20
records after each decision in test_broll_v20. No model is called (broll.claude_json is faked as in test_broll_ideas) and
tests/conftest.py turns the journal off for the whole suite: every test here turns it on again, in a temporary folder
(the autouse ``journal`` fixture also moves the two md files there)."""
import json
import os
import subprocess
import sys
import threading
import time

import pytest

import ai_brain
import broll
import broll_ideas
import broll_lessons as bl
from test_broll_ideas import CAST, DINER, da, da_reply, full_round, moment, run_round, verdict, verifier_reply, view, viewer_reply

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = 86400
HEADER = ("LESSONS OF THE LAST DAYS (the channel's owner's own verdicts and the rules she validated; principles, never "
          "scenes to copy):")
PROPOSED, VALIDATED = "proposées.md", "validées.md"      # the two files of the owner, in the journal's folder


@pytest.fixture(autouse=True)
def journal(monkeypatch, tmp_path):
    """The journal on (it is off for the suite), in a temporary folder that does not exist yet."""
    monkeypatch.setenv("BROLL_LESSONS", "1")
    monkeypatch.setattr(bl, "LESSONS_DIR", str(tmp_path / "journal"))
    return tmp_path / "journal"


@pytest.fixture
def ideas_state(monkeypatch):
    """What the round of ideas reads, as test_broll_ideas leaves it: nothing cached, no episode brief, default models."""
    broll.FILTERS.clear()
    del broll_ideas.LAST_IDEAS[:]
    monkeypatch.setattr(broll_ideas, "_CACHE", {})
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    for stage in ("BROLL_IDEAS", "BROLL_VERIFY", "BROLL_VIEWER"):
        monkeypatch.delenv(f"BRAIN_{stage}", raising=False)
    monkeypatch.delenv("CLAUDE_EFFORT_BROLL_IDEAS", raising=False)
    yield
    broll.FILTERS.clear()
    del broll_ideas.LAST_IDEAS[:]


# ---------------------------------------------------------------------------------------------------- the events

def ev(**kw):
    """An event of the chain's own checks: a drop unless said otherwise."""
    return {"source": "check", "verdict": "drop", **kw}


def drops(n, why, **kw):
    """``n`` pictures dropped for ``why``."""
    return [ev(why=why, **kw) for _ in range(n)]


def keeps(n, score, **kw):
    """``n`` pictures kept with the viewer's ``score``."""
    return [ev(verdict="keep", why="", score=score, **kw) for _ in range(n)]


def owner(verdict_, **kw):
    """A verdict of the channel's owner (the dashboard's thumbs)."""
    return {"source": "owner", "verdict": verdict_, **kw}


def put(*events):
    """Record events in the journal (a list stands for its events)."""
    for e in events:
        if isinstance(e, (list, tuple)):
            put(*e)
        else:
            assert bl.record(e), e


def aged(days, event):
    return {**event, "at": time.time() - days * DAY}


def write_raw(*lines):
    """Write the journal by hand (events as dicts, or text lines as they are), to give the events their own age."""
    os.makedirs(bl.LESSONS_DIR, exist_ok=True)
    with open(bl.path(), "w", encoding="utf-8") as f:
        for line in lines:
            for one in (line if isinstance(line, list) else [line]):
                f.write((one if isinstance(one, str) else json.dumps(one)) + "\n")


def raw_journal():
    with open(bl.path(), encoding="utf-8") as f:
        return f.read()


def bullets(for_who="director"):
    """The lines of the summary without their bullet; the shape is checked on the way: a header, then one "- " line each."""
    text = bl.summary(for_who)
    if not text:
        return []
    head, *rest = text.split("\n")
    assert head.startswith("LESSONS OF THE LAST DAYS (") and rest and all(l.startswith("- ") for l in rest), text
    return [line[2:] for line in rest]


def read_file(name):
    """One of the owner's two files, as text."""
    with open(os.path.join(bl.LESSONS_DIR, name), encoding="utf-8") as f:
        return f.read()


def validate(*lines):
    """What the owner does by hand: write ``lines`` (as they are) to validées.md."""
    os.makedirs(bl.LESSONS_DIR, exist_ok=True)
    with open(os.path.join(bl.LESSONS_DIR, VALIDATED), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def proposal_file():
    """proposées.md as (its header, its lines): the header is everything before the first "- " bullet."""
    lines = read_file(PROPOSED).split("\n")
    first = next((i for i, line in enumerate(lines) if line.startswith("- ")), len(lines))
    return lines[:first], [line[2:] for line in lines[first:] if line.startswith("- ")]


def patterns():
    """The patterns the code finds in the journal as it is: the lines ``propose`` gives back, which must be the lines of
    proposées.md (checked on the way, as bullets() checks the shape of the summary)."""
    lines = bl.propose()
    assert proposal_file()[1] == lines
    return lines


def every_pattern(n):
    """The chain's own checks with each of the six kinds of pattern in them, ``n`` pictures each."""
    return [drops(n, "pulls attention away", kind="scene", flaw="stock"), drops(n, "text in it"),
            drops(n, "wrong subject", kind="thing"), drops(n, "unsafe"), keeps(n, 5, kind="vision")]


# one thumb down and one thumb up of the owner, and the lines the summary makes of them
DOWN = owner("down", note="a stock photo of a kitchen, nothing of the words")
UP = owner("up", subject="a forearm out of its cast", said="healed in weeks")
DOWN_LINE = "The channel's owner rejected a picture: a stock photo of a kitchen, nothing of the words."
UP_LINE = 'The channel\'s owner liked: a forearm out of its cast for "healed in weeks" — that level is the bar.'


def fresh(code, **env):
    """What a new interpreter prints for ``code`` with the environment given (None removes a variable)."""
    environ = dict(os.environ)
    for k, v in env.items():
        if v is None:
            environ.pop(k, None)
        else:
            environ[k] = v
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environ, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


# ======================================================================================================== the journal

class TestRecord:
    def test_an_event_is_one_json_line_with_its_time_and_the_folder_is_made(self, journal):
        before = time.time()
        assert not os.path.exists(journal)
        assert bl.record({"source": "check", "verdict": "drop", "why": "text in it", "subject": "une carafe d'eau, café"}) is True
        assert bl.record({"source": "owner", "verdict": "up"}) is True
        assert os.path.isdir(journal) and os.path.isfile(journal / ".keep")
        assert bl.path() == os.path.join(str(journal), "broll_lessons.jsonl")
        raw = raw_journal()
        assert raw.endswith("\n") and len(raw.splitlines()) == 2
        first, second = (json.loads(line) for line in raw.splitlines())
        assert abs(first["at"] - before) < 60 and abs(second["at"] - before) < 60
        assert {k: v for k, v in first.items() if k != "at"} == {"source": "check", "verdict": "drop", "why": "text in it",
                                                                 "subject": "une carafe d'eau, café"}
        assert {k: v for k, v in second.items() if k != "at"} == {"source": "owner", "verdict": "up"}
        assert "café" in raw and "\\u" not in raw                       # written as it is, not escaped

    def test_the_event_given_is_left_as_it_was(self):
        event = {"source": "check", "verdict": "keep"}
        assert bl.record(event) is True
        assert event == {"source": "check", "verdict": "keep"}          # the time goes to the line, not to the caller's dict

    def test_the_journal_is_appended_to_never_rewritten(self):
        for i in range(3):
            assert bl.record(ev(i=i))
        assert [e["i"] for e in bl.recent()] == [0, 1, 2]
        assert bl.record(ev(i=3)) and [e["i"] for e in bl.recent()] == [0, 1, 2, 3]

    def test_the_keep_file_that_protects_the_folder_is_made_once_and_left_alone(self, journal):
        bl.record(ev())
        keep = journal / ".keep"
        assert keep.read_text() == ""
        keep.write_text("mine")
        bl.record(ev())
        assert keep.read_text() == "mine"

    def test_BROLL_LESSONS_0_turns_the_journal_off_and_touches_nothing(self, monkeypatch, journal):
        monkeypatch.setenv("BROLL_LESSONS", "0")
        assert bl.record(ev(why="text in it")) is False
        assert not os.path.exists(journal)                              # not even the folder
        assert bl.recent() == [] and bl.summary() == ""
        monkeypatch.setenv("BROLL_LESSONS", "1")
        assert bl.record(ev()) is True
        monkeypatch.delenv("BROLL_LESSONS")                             # not set: on
        assert bl.record(ev()) is True
        assert len(bl.recent()) == 2

    def test_a_journal_that_cannot_be_written_gives_false_and_a_warning_never_an_error(self, monkeypatch, tmp_path, capsys):
        (tmp_path / "blocker").write_text("a file, not a folder")
        monkeypatch.setattr(bl, "LESSONS_DIR", str(tmp_path / "blocker" / "journal"))
        assert bl.record(ev()) is False
        assert "Lessons: not recorded" in capsys.readouterr().out
        assert bl.recent() == [] and bl.summary() == ""
        bl.clear()                                                      # nothing to remove: no error either

    def test_an_event_that_is_no_json_is_refused_and_the_journal_is_left_intact(self, capsys):
        assert bl.record(ev(i=1)) is True
        assert bl.record({"source": "check", "bad": object()}) is False
        assert "Lessons: not recorded" in capsys.readouterr().out
        assert [e["i"] for e in bl.recent()] == [1]

    def test_events_recorded_at_the_same_time_never_interleave(self):
        results = []

        def work(w):
            for i in range(25):
                results.append(bl.record(ev(w=w, i=i, why="x" * 200)))
        threads = [threading.Thread(target=work, args=(w,)) for w in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 200 and all(results)
        events = [json.loads(line) for line in raw_journal().splitlines()]
        assert len(events) == 200 and all(e["why"] == "x" * 200 for e in events)
        for w in range(8):
            assert [e["i"] for e in events if e["w"] == w] == list(range(25))      # each writer's own order is kept


class TestWhereTheJournalLives:
    def test_the_folder_is_BROLL_LESSONS_DIR_else_output_lessons(self, tmp_path):
        code = "import broll_lessons; print(broll_lessons.LESSONS_DIR)"
        assert fresh(code, BROLL_LESSONS_DIR=str(tmp_path)) == str(tmp_path)
        default = os.path.join(ROOT, "output", "_lessons")
        assert fresh(code, BROLL_LESSONS_DIR=None) == default
        assert fresh(code, BROLL_LESSONS_DIR="") == default


class TestRecent:
    def test_the_defaults_of_the_module(self):
        assert (bl.RECENT, bl.DAYS, bl.MIN_COUNT, bl.MAX_LINES) == (300, 14, 3, 8)

    def test_the_last_n_events_oldest_first(self):
        for i in range(6):
            bl.record(ev(i=i))
        assert [e["i"] for e in bl.recent(3)] == [3, 4, 5]
        assert [e["i"] for e in bl.recent()] == [0, 1, 2, 3, 4, 5]

    def test_only_the_last_three_hundred_lines_are_read_by_default(self):
        write_raw([aged(0, ev(i=i)) for i in range(305)])
        got = bl.recent()
        assert len(got) == bl.RECENT == 300 and got[0]["i"] == 5 and got[-1]["i"] == 304

    def test_events_older_than_the_days_given_are_left_out(self):
        write_raw(aged(20, ev(i=0)), aged(10, ev(i=1)), aged(1, ev(i=2)))
        assert [e["i"] for e in bl.recent()] == [1, 2]                  # two weeks by default
        assert [e["i"] for e in bl.recent(days=5)] == [2]
        assert [e["i"] for e in bl.recent(days=30)] == [0, 1, 2]

    def test_a_missing_journal_is_an_empty_one(self):
        assert not os.path.exists(bl.path()) and bl.recent() == []

    def test_blank_corrupt_and_non_object_lines_are_skipped(self):
        now = time.time()
        write_raw(json.dumps({"i": 0, "at": now}), "", "   ", "{not json", '{"i": 1, "at":', "[1, 2]", '"text"', "42",
                  "null", json.dumps({"i": 2, "at": now}))
        assert [e["i"] for e in bl.recent()] == [0, 2]


class TestClear:
    def test_clear_empties_the_journal_and_keeps_the_keep_file(self, journal):
        put(owner("down", note="too dark"))
        assert bl.summary() and os.path.exists(bl.path())
        bl.clear()
        assert not os.path.exists(bl.path()) and os.path.exists(journal / ".keep")
        assert bl.recent() == [] and bl.summary() == ""
        bl.clear()                                                      # nothing left: no error
        assert bl.record(ev()) and len(bl.recent()) == 1                # and it starts again

    def test_clear_leaves_the_owners_own_file_alone(self):
        validate("A rule she wrote.")
        put(owner("down", note="too dark"))
        assert len(bullets()) == 2
        bl.clear()
        assert bullets() == ["A rule she wrote."]                       # the journal is gone, not what she validated
        assert read_file(VALIDATED) == "A rule she wrote.\n"


# ======================================================================================================== the summary

class TestTheShapeOfTheSummary:
    def test_nothing_recorded_nothing_said(self):
        assert bl.summary() == "" and bl.summary("director") == "" and bl.summary("judges") == ""

    def test_the_block_is_a_header_and_one_bullet_per_line(self):
        put(owner("down", note="too dark"))
        text = bl.summary()
        assert text == HEADER + "\n- The channel's owner rejected a picture: too dark."
        assert text == bl.summary("director")                           # "director" is the default
        validate("Rule one.", "Rule two.")                              # a line of the owner's file is a bullet like the others
        assert bl.summary().split("\n") == [HEADER, "- The channel's owner rejected a picture: too dark.", "- Rule one.",
                                            "- Rule two."]

    def test_events_that_teach_nothing_give_an_empty_string_not_a_header(self):
        put(keeps(4, 3, kind="thing"), drops(2, "text in it"), ev(verdict="keep", why="", kind="scene"))
        assert bl.summary("judges") == ""

    def test_a_note_with_line_breaks_and_quotes_stays_one_bullet(self):
        put(owner("down", note='too "dark"\n\n- and a fake bullet\nLESSONS OF THE LAST DAYS'))
        assert bullets() == ["The channel's owner rejected a picture: too 'dark' - and a fake bullet LESSONS OF THE LAST DAYS."]

    def test_clean_flattens_the_white_space_and_the_double_quotes(self):
        assert bl._clean('a  "b"\n\tc ') == "a 'b' c" and bl._clean(None) == "" and bl._clean(12) == "12"


class TestTheOwnersVerdicts:
    def test_one_down_is_enough_the_note_is_the_lesson(self):
        put(owner("down", note="a stock photo of a kitchen, nothing of the words", subject="a kitchen", said="the alarm is gone"))
        assert bullets() == ["The channel's owner rejected a picture: a stock photo of a kitchen, nothing of the words."]
        assert bullets("judges") == bullets("director")

    def test_without_a_note_the_subject_and_the_words_are_the_lesson(self):
        put(owner("down", subject="a dark empty room", said="you fall asleep in minutes"))
        assert bullets() == ['The channel\'s owner rejected a picture: a dark empty room for "you fall asleep in minutes".']

    def test_the_words_are_cut_at_sixty_characters_and_quotes_and_line_breaks_are_flattened(self):
        put(owner("down", subject='a "red"\n  apple', said='"' + "w" * 100))
        assert bullets() == ["The channel's owner rejected a picture: a 'red' apple for \"'" + "w" * 59 + '".']

    def test_an_event_as_the_dashboard_records_it(self):
        # app.py's /broll/feedback: the owner's thumb with the fields of the picture it was given on
        put({"source": "owner", "verdict": "down", "note": "", "subject": "a kitchen at noon", "kind": "scene",
             "role": "vehicle", "said": "the alarm is gone", "title": "A kitchen", "job": "abc123", "clip": 2,
             "image": "broll_1.jpg", "clip_title": "PTSD"})
        assert bullets() == ['The channel\'s owner rejected a picture: a kitchen at noon for "the alarm is gone".']

    def test_only_the_last_four_downs_are_read(self):
        put([owner("down", note=f"reason {i}") for i in range(6)])
        assert sorted(b.split(": ")[1] for b in bullets()) == ["reason 2.", "reason 3.", "reason 4.", "reason 5."]

    def test_an_up_is_read_by_the_judges_only_and_the_last_three_count(self):
        put([owner("up", subject=f"liked {i}", said=f"words {i}") for i in range(5)])
        assert bullets("director") == [] and bl.summary() == ""
        assert sorted(bullets("judges")) == [f'The channel\'s owner liked: liked {i} for "words {i}" — that level is the bar.'
                                             for i in (2, 3, 4)]

    def test_what_the_owner_liked_is_cut_at_sixty_characters_too(self):
        put(owner("up", subject="a cast", said="w" * 100))
        assert bullets("judges") == ['The channel\'s owner liked: a cast for "' + "w" * 60 + '" — that level is the bar.']

    def test_an_up_without_a_subject_is_known_by_its_title(self):
        put(owner("up", title="The cast comes off", said="healed in weeks"))
        assert bullets("judges") == ['The channel\'s owner liked: The cast comes off for "healed in weeks" — that level is the bar.']

    def test_what_is_neither_a_down_nor_an_up_of_the_owner_is_no_lesson(self):
        put({"source": "somebody", "verdict": "down", "note": "n1"}, {"verdict": "down", "note": "n2"},
            owner("meh", note="n3"), owner("down-ish", note="n4"), owner("", note="n5"))
        assert bl.summary("judges") == ""

    def test_a_rejection_ranks_above_a_like_and_both_above_any_pattern(self):
        events = [owner("up", subject="a cast"), *drops(50, "pulls attention away", kind="scene"),
                  owner("down", note="too dark")]
        by_rank = {rank: line for rank, line in bl._lines(events, "judges")}
        assert sorted(by_rank, reverse=True) == [10 ** 6, 10 ** 6 - 1, 50]
        assert by_rank[10 ** 6].startswith("The channel's owner rejected")
        assert by_rank[10 ** 6 - 1].startswith("The channel's owner liked")
        assert by_rank[50].startswith("50 pictures of a scene")
        assert sorted(rank for rank, _line in bl._lines(events, "director")) == [50, 10 ** 6]      # no like for the director

    def test_a_rejection_comes_before_a_like_whatever_the_order_they_were_given_in(self):
        put(UP, owner("down", note="too dark"))
        assert bullets("judges") == ["The channel's owner rejected a picture: too dark.", UP_LINE]


class TestTheLinesTheOwnerValidated:
    """validées.md: the lines she moved there (or wrote there), one rule per line, are the other half of the summary."""

    def test_a_validated_line_enters_the_summary_for_the_director_and_the_judges(self):
        line = "Show the idea itself, with one or two true particular details."
        validate(line)
        assert bullets("director") == bullets("judges") == [line]
        assert bl.summary() == HEADER + "\n- " + line

    def test_comments_blank_lines_and_a_leading_dash_are_dealt_with(self):
        validate("# a note she left herself", "", "   ", "- A rule with its dash.", "A rule without one.", "#another note",
                 "  - An indented rule, with trailing spaces.  ", "Rule #2 stays whole.")
        assert bullets() == ["A rule with its dash.", "A rule without one.", "An indented rule, with trailing spaces.",
                             "Rule #2 stays whole."]

    def test_a_file_of_comments_and_blank_lines_is_no_lesson(self):
        validate("# one", "", "# two", "   ")
        assert bl.summary("judges") == ""

    def test_her_lines_come_after_her_verdicts_in_the_order_of_the_file(self):
        put(UP, owner("down", note="too dark"))
        validate("- First rule.", "- Second rule.")
        assert bullets("judges") == ["The channel's owner rejected a picture: too dark.", UP_LINE, "First rule.", "Second rule."]
        assert bullets("director") == ["The channel's owner rejected a picture: too dark.", "First rule.", "Second rule."]

    def test_a_validated_line_has_no_age_and_is_no_event_of_the_journal(self):
        write_raw([aged(40, ev(why="text in it")) for _ in range(5)], aged(40, owner("down", note="too old")))
        validate("A rule she validated long ago.")
        assert bullets() == ["A rule she validated long ago."]         # the old verdict is gone, her rule stays

    def test_the_cap_cuts_her_lines_before_her_verdicts(self):
        put([owner("down", note=f"reason {i}") for i in range(4)], [owner("up", subject=f"liked {i}") for i in range(3)])
        validate(*(f"Rule {i}." for i in range(5)))
        got = bullets("judges")                                         # 4 + 3 verdicts, one place left
        assert len(got) == bl.MAX_LINES == 8 and sum(b.startswith("The channel's owner") for b in got) == 7
        assert got[-1] == "Rule 0."
        got = bullets("director")                                       # 4 verdicts, the first four rules
        assert len(got) == 8 and sum(b.startswith("The channel's owner") for b in got) == 4
        assert got[4:] == ["Rule 0.", "Rule 1.", "Rule 2.", "Rule 3."]

    def test_without_a_verdict_the_first_eight_lines_of_the_file_are_all_there_is(self):
        validate(*(f"Rule {i}." for i in range(12)))
        assert bullets() == [f"Rule {i}." for i in range(8)]

    def test_a_file_that_cannot_be_read_says_nothing_and_costs_nothing(self, journal):
        put(owner("down", note="too dark"))
        os.makedirs(journal / VALIDATED)                                # a folder where her file should be
        assert bullets() == ["The channel's owner rejected a picture: too dark."]


class TestThePatternsStayOutOfTheSummary:
    """What the code finds in the journal is only PROPOSED (proposées.md): it never enters a call on its own."""

    def test_a_journal_of_patterns_alone_says_nothing(self):
        put(every_pattern(9))
        assert len(patterns()) == 6                                     # they are all found ...
        assert bl.summary("director") == "" and bl.summary("judges") == ""      # ... and none is said

    def test_no_pattern_line_is_in_the_summary_whatever_else_there_is_to_say(self):
        put(every_pattern(50), owner("down", note="too dark"), owner("up", subject="a cast"))
        validate("A rule she validated.")
        proposed = patterns()
        assert len(proposed) == 6
        for who, expected in (("director", 2), ("judges", 3)):
            got = bullets(who)
            assert len(got) == expected and got[-1] == "A rule she validated.", who
            assert not any(line in bl.summary(who) for line in proposed), who
            assert not any(words in bl.summary(who) for words in ("did not beat the face alone", "carried writing",
                                                                  "missed the subject", "refused for safety",
                                                                  "What worked", "flagged as")), who

    def test_the_lines_of_a_pattern_never_name_a_picture(self):
        # "principles, never scenes to copy": only the owner's own verdicts say what a picture was
        names = dict(subject="UNIQUE SUBJECT", title="UNIQUE TITLE", said="UNIQUE WORDS", clip_title="UNIQUE CLIP")
        put(drops(3, "pulls attention away", kind="scene", flaw="stock", **names), drops(3, "text in it", **names),
            drops(3, "wrong subject", kind="thing", **names), drops(3, "unsafe", **names), keeps(3, 5, kind="vision", **names))
        proposed = patterns()
        assert len(proposed) == 6                                       # all six patterns, the flaw one included
        assert not any(unique in line for line in proposed for unique in names.values())
        assert not any(unique in read_file(PROPOSED) for unique in names.values())


# ====================================================================================================== the proposals

class TestPropose:
    """``propose``: the patterns of the chain's own checks, written to proposées.md for the owner to read."""

    def test_the_file_is_a_header_of_comments_then_one_bullet_per_pattern_the_strongest_first(self, journal):
        put(drops(3, "text in it"), drops(5, "pulls attention away", kind="scene"))
        assert not os.path.exists(journal / PROPOSED)
        lines = bl.propose()
        assert len(lines) == 2 and lines[0].startswith("5 pictures of a scene") and lines[1].startswith("3 pictures carried")
        header, bulleted = proposal_file()
        assert bulleted == lines
        assert header and all(line.startswith("#") or not line.strip() for line in header)    # comments and blank lines
        assert header[0].startswith("#") and "validées.md" in "\n".join(header)               # and where a line becomes a rule
        assert read_file(PROPOSED).endswith("\n")

    def test_with_nothing_to_propose_the_file_is_its_header_alone(self):
        assert bl.propose() == []
        header, bulleted = proposal_file()
        assert header and bulleted == []

    def test_the_events_given_are_proposed_in_place_of_the_journal_none_means_the_journal(self):
        put(drops(3, "text in it"))                                     # the journal says one thing ...
        lines = bl.propose([ev(why="unsafe") for _ in range(4)])        # ... the events given another
        assert len(lines) == 1 and lines[0].startswith("4 pictures were refused for safety")
        assert proposal_file()[1] == lines
        assert bl.propose(None)[0].startswith("3 pictures carried writing")
        assert bl.propose([]) == [] and proposal_file()[1] == []        # no event given is no event, not the journal

    def test_the_owners_verdicts_are_no_proposal_and_the_proposals_do_not_depend_on_who_asked(self):
        put(drops(3, "text in it"), owner("down", note="too dark"), owner("up", subject="a cast"))
        assert bl.summary("director") and proposal_file()[1][0].startswith("3 pictures carried writing")
        director = proposal_file()
        assert bl.summary("judges") and proposal_file() == director
        assert len(director[1]) == 1 and "owner" not in director[1][0]

    def test_the_file_is_rewritten_each_time_never_added_to(self):
        put(drops(3, "text in it"))
        assert len(patterns()) == 1
        bl.clear()
        put(drops(4, "unsafe"))
        assert patterns()[0].startswith("4 pictures were refused") and "carried writing" not in read_file(PROPOSED)
        bl.clear()
        assert patterns() == []                                         # nothing any more: the header alone

    def test_the_folder_is_made_with_both_files_when_there_is_none(self, journal):
        assert not os.path.exists(journal)
        bl.propose()
        assert os.path.isfile(journal / PROPOSED) and os.path.isfile(journal / VALIDATED)

    def test_validees_md_is_made_with_a_header_when_missing_and_then_never_touched(self, journal):
        bl.propose()
        text = read_file(VALIDATED)
        assert text.startswith("#") and all(line.startswith("#") or not line.strip() for line in text.split("\n"))
        assert bl.summary() == ""                                       # the header is no lesson
        validate("- A rule she wrote.", "# and a note to herself")
        before = read_file(VALIDATED)
        put(drops(3, "text in it"), owner("down", note="too dark"))
        bl.propose()
        bl.summary("judges")
        bl.propose([ev(why="unsafe")] * 5)
        assert read_file(VALIDATED) == before                           # her file is hers

    def test_summary_proposes_on_the_way_even_when_it_has_nothing_to_say(self, journal):
        put(drops(3, "text in it"))
        assert bl.summary("judges") == ""
        assert os.path.isfile(journal / VALIDATED) and proposal_file()[1][0].startswith("3 pictures carried writing")
        put(drops(2, "text in it"), drops(4, "unsafe"))                 # more events: the next summary() refreshes the file
        bl.summary("director")
        assert [line.split(" ")[0] for line in proposal_file()[1]] == ["5", "4"]

    def test_summary_proposes_what_it_reads_not_what_is_too_old(self):
        write_raw([aged(15, ev(why="text in it")) for _ in range(5)], [aged(1, ev(why="unsafe")) for _ in range(3)])
        bl.summary()
        (line,) = proposal_file()[1]
        assert line.startswith("3 pictures were refused for safety")   # the five old ones are not read

    def test_a_folder_that_cannot_be_written_proposes_nothing_and_never_raises(self, monkeypatch, tmp_path, capsys):
        (tmp_path / "blocker").write_text("a file, not a folder")
        monkeypatch.setattr(bl, "LESSONS_DIR", str(tmp_path / "blocker" / "journal"))
        assert bl.propose([ev(why="text in it")] * 3) == []
        assert "Lessons: not proposed" in capsys.readouterr().out
        assert bl.summary() == "" and "Lessons: not proposed" in capsys.readouterr().out

    def test_events_that_are_no_events_are_refused_with_a_warning_not_an_error(self, capsys):
        assert bl.propose([None, "text"]) == []
        assert "Lessons: not proposed" in capsys.readouterr().out

    def test_a_proposal_that_fails_never_costs_the_summary_its_lines(self, journal, capsys):
        put(owner("down", note="too dark"))
        validate("A rule she wrote.")
        os.makedirs(journal / PROPOSED)                                 # a folder where the proposals should be written
        assert bullets() == ["The channel's owner rejected a picture: too dark.", "A rule she wrote."]
        assert "Lessons: not proposed" in capsys.readouterr().out


class TestThePatternsOfTheChecks:
    """What the code finds in the journal, as ``propose`` gives it back (and writes it to proposées.md): ``patterns()``."""

    def test_three_occurrences_make_a_line_two_do_not(self):
        put(drops(2, "pulls attention away", kind="scene"), drops(2, "text in it"), drops(2, "wrong subject", kind="thing"),
            drops(1, "unsafe"), drops(1, "body photo"), drops(2, "wrong count", flaw="setting"),
            keeps(2, 5, kind="thing"), keeps(2, 1, kind="vision"))
        assert patterns() == []
        put(drops(1, "text in it"))
        assert len(patterns()) == 1 and patterns()[0].startswith("3 pictures carried writing")

    # --- not beating the face alone (by kind)
    @pytest.mark.parametrize("why", ["pulls attention away", "contradicts the words", "under the face alone"])
    def test_each_reason_of_the_bucket_counts(self, why):
        put(drops(3, why, kind="thing"))
        (line,) = patterns()
        assert line.startswith("3 pictures of a thing did not beat the face alone lately") and "show the idea itself" in line

    def test_the_reasons_of_the_bucket_add_up_and_an_alt_verdict_counts_like_a_drop(self):
        put(ev(why="pulls attention away", kind="scene"), ev(verdict="alt", why="contradicts the words", kind="scene"),
            ev(verdict="alt", why="under the face alone", kind="scene"))
        (line,) = patterns()
        assert line.startswith("3 pictures of a scene did not beat the face alone lately")

    def test_a_kept_picture_scored_two_or_less_counts_with_the_dropped_ones(self):
        put(ev(why="under the face alone", kind="thing"), keeps(1, 2, kind="thing"), keeps(1, 1, kind="thing"))
        (line,) = patterns()
        assert line.startswith("3 pictures of a thing did not beat the face alone lately")

    def test_a_kept_picture_scored_three_or_not_scored_is_no_failure(self):
        put(keeps(5, 3, kind="thing"), keeps(5, None, kind="thing"), [ev(verdict="keep", score="1", kind="thing")] * 5)
        assert patterns() == []

    def test_the_kinds_are_counted_apart(self):
        put(drops(2, "pulls attention away", kind="thing"), drops(2, "pulls attention away", kind="scene"))
        assert patterns() == []
        put(drops(1, "pulls attention away", kind="thing"))
        (line,) = patterns()
        assert line.startswith("3 pictures of a thing ")

    @pytest.mark.parametrize("kind,words", [("thing", "a thing"), ("scene", "a scene"), ("vision", "what a person perceives"),
                                            ("instrument", "an instrument's image"),
                                            ("body_inside", "a drawing of the inside of a body"),
                                            ("pair", "two things side by side"), ("picture", "a picture")])
    def test_each_kind_has_its_words(self, kind, words):
        put(drops(3, "under the face alone", kind=kind))
        assert patterns()[0].startswith(f"3 pictures of {words} did not beat the face alone lately")
        bl.clear()
        put(drops(3, "wrong subject", kind=kind))
        assert patterns()[0].startswith(f"The engine missed the subject of 3 pictures of {words}:")

    @pytest.mark.parametrize("kind", [None, "", "weird", "photo", 7, ["thing"]])
    def test_a_missing_or_unknown_kind_is_a_picture(self, kind):
        put(drops(3, "under the face alone", kind=kind))
        assert patterns()[0].startswith("3 pictures of a picture did not beat the face alone lately")

    def test_a_kind_is_read_whatever_its_case_and_its_spaces(self):
        put(drops(1, "under the face alone", kind=" Scene "), drops(1, "under the face alone", kind="SCENE"),
            drops(1, "under the face alone", kind="scene"))
        assert patterns()[0].startswith("3 pictures of a scene did not beat")

    def test_a_drop_for_another_reason_is_no_pattern(self):
        put(*(drops(5, why, kind="scene") for why in ("wrong count", "wrong people", "wrong medium", "not a pair", "look",
                                                      "not checked")))
        assert patterns() == []

    def test_only_the_chains_own_checks_make_a_pattern(self):
        put([owner("drop", why="text in it") for _ in range(5)], [{"verdict": "drop", "why": "text in it"}] * 5)
        assert patterns() == []

    # --- the verifier's flaws on the ideas that were dropped
    @pytest.mark.parametrize("flaw,words", [("setting", "the setting instead of the idea"),
                                            ("object", "an object placed to tick the box"),
                                            ("stock", "a stock-photo look"), ("symbol", "a symbol to decode")])
    def test_a_flaw_of_the_verifier_on_dropped_ideas_is_a_pattern(self, flaw, words):
        put(drops(2, "wrong count", flaw=flaw), ev(verdict="alt", why="wrong count", flaw=flaw))
        (line,) = patterns()
        assert line.startswith(f"3 ideas flagged as {words} were dropped after the render") and "leave such ideas out" in line

    def test_two_flawed_ideas_are_no_pattern_and_the_flaws_are_counted_apart(self):
        put(drops(2, "wrong count", flaw="setting"), drops(2, "wrong count", flaw="object"))
        assert patterns() == []

    def test_the_other_flaws_the_kept_pictures_and_the_unflagged_are_no_pattern(self):
        put(*(drops(5, "wrong count", flaw=f) for f in ("figure", "none", "", None)), drops(5, "wrong count"),
            keeps(5, 3, flaw="setting"))
        assert patterns() == []

    # --- writing, the subject the engine missed, safety
    def test_pictures_that_carried_writing(self):
        put(drops(2, "text in it"), ev(verdict="alt", why="text in it"))
        (line,) = patterns()
        assert line.startswith("3 pictures carried writing") and "never a thing that bears text" in line

    def test_the_subject_the_engine_missed_is_counted_by_kind(self):
        put(drops(2, "wrong subject", kind="instrument"), ev(verdict="alt", why="wrong subject", kind="instrument"),
            drops(2, "wrong subject", kind="thing"))
        (line,) = patterns()
        assert line.startswith("The engine missed the subject of 3 pictures of an instrument's image:")
        assert "name the thing plainly" in line

    def test_pictures_refused_for_safety_count_together(self):
        put(drops(1, "unsafe"), ev(verdict="alt", why="unsafe"), drops(1, "body photo"))
        (line,) = patterns()
        assert line.startswith("3 pictures were refused for safety after the render") and "no gore" in line
        bl.clear()
        put(drops(2, "unsafe"), drops(1, "wrong count"))
        assert patterns() == []

    # --- what worked
    def test_what_worked_is_three_pictures_of_a_kind_scored_four_or_five(self):
        put(keeps(2, 4, kind="thing"), keeps(1, 5, kind="thing"))
        assert patterns() == ["What worked: 3 pictures of a thing scored 4 or 5 (the viewer understood more than he was told)."]

    def test_two_good_pictures_a_three_and_what_was_not_kept_are_no_success(self):
        put(keeps(2, 5, kind="thing"), keeps(5, 3, kind="scene"), drops(5, "wrong count", kind="vision", score=5),
            [ev(verdict="alt", why="wrong count", kind="vision", score=5)] * 5)
        assert patterns() == []

    def test_at_most_two_what_worked_lines_the_strongest_kinds(self):
        put(keeps(5, 5, kind="scene"), keeps(4, 4, kind="thing"), keeps(3, 5, kind="vision"))
        assert [b.split(" scored")[0] for b in patterns()] == ["What worked: 5 pictures of a scene",
                                                               "What worked: 4 pictures of a thing"]

    # --- the order, no cap
    def test_the_strongest_pattern_comes_first(self):
        put(drops(3, "text in it"), drops(7, "pulls attention away", kind="scene"), drops(5, "unsafe"))
        got = patterns()
        assert got[0].startswith("7 pictures of a scene") and got[1].startswith("5 pictures were refused")
        assert got[2].startswith("3 pictures carried writing")

    def test_every_pattern_is_proposed_none_is_cut_the_owner_reads_them_all(self):
        kinds = ["thing", "scene", "vision", "instrument", "body_inside", "pair"]
        put([drops(12 - i, "pulls attention away", kind=kind) for i, kind in enumerate(kinds)],          # 12 ... 7
            drops(6, "wrong count", flaw="setting"), drops(5, "wrong count", flaw="object"),
            drops(4, "wrong count", flaw="stock"), drops(3, "wrong count", flaw="symbol"))              # ten patterns
        got = patterns()
        assert len(got) == 10 > bl.MAX_LINES                            # the cap is the summary's, not the proposals'
        assert [b.split(" ")[0] for b in got] == ["12", "11", "10", "9", "8", "7", "6", "5", "4", "3"]
        assert any("a stock-photo look" in b for b in got) and any("a symbol to decode" in b for b in got)
        assert bl.summary() == ""                                       # and none of the ten reaches a call


class TestWhatIsRecent:
    def test_a_pattern_of_old_events_is_gone_and_so_is_an_old_verdict(self):
        write_raw([aged(15, ev(why="text in it")) for _ in range(5)], aged(15, owner("down", note="too dark")),
                  aged(15, owner("up", subject="a cast")))
        assert bl.summary("judges") == "" and patterns() == []

    def test_the_days_decide_which_events_count(self):
        write_raw([aged(13, ev(why="text in it")) for _ in range(3)])
        assert patterns()[0].startswith("3 pictures carried writing")
        write_raw([aged(13, ev(why="text in it")) for _ in range(2)], aged(15, ev(why="text in it")))
        assert patterns() == []                                         # two left, the third is too old

    def test_only_the_last_three_hundred_events_are_summed_up(self):
        neutral = [aged(0, ev(verdict="keep", why="", score=3)) for _ in range(bl.RECENT - 3)]
        write_raw([aged(0, ev(why="text in it")) for _ in range(3)], neutral)
        assert patterns()[0].startswith("3 pictures carried writing")    # exactly 300 lines: the three are the oldest read
        write_raw([aged(0, ev(why="text in it")) for _ in range(3)], neutral, aged(0, ev(verdict="keep", why="", score=3)))
        assert patterns() == []                                         # one more line: the first one slides out

    def test_an_owner_verdict_slides_out_with_the_three_hundred_lines_too(self):
        neutral = [aged(0, ev(verdict="keep", why="", score=3)) for _ in range(bl.RECENT - 1)]
        write_raw(aged(0, owner("down", note="too dark")), neutral)
        assert bullets() == ["The channel's owner rejected a picture: too dark."]     # the last of the 300 lines read
        write_raw(aged(0, owner("down", note="too dark")), neutral, aged(0, ev(verdict="keep", why="", score=3)))
        assert bullets() == []


# ======================================================================================== the round of ideas reads it

@pytest.mark.usefixtures("ideas_state")
class TestTheBlockInThePrompts:
    def test_the_lessons_helper_wraps_the_summary_in_blank_lines_and_says_nothing_for_nothing(self):
        assert broll_ideas._lessons("director") == "" and broll_ideas._lessons("judges") == ""
        put(DOWN, UP)
        assert broll_ideas._lessons("director") == "\n" + bl.summary("director") + "\n"
        assert broll_ideas._lessons("judges") == "\n" + bl.summary("judges") + "\n"

    def test_each_call_carries_the_block_and_only_the_judges_read_what_the_owner_liked(self, monkeypatch):
        put(DOWN, UP)
        judges, _out = full_round(monkeypatch)
        assert judges.judges() == ["da", "verifier", "viewer"]
        for judge in ("da", "verifier", "viewer"):
            assert HEADER in judges.prompt(judge) and DOWN_LINE in judges.prompt(judge), judge
        assert UP_LINE not in judges.prompt("da")                       # the director is told what to avoid
        assert UP_LINE in judges.prompt("verifier") and UP_LINE in judges.prompt("viewer")

    def test_the_director_asks_for_its_block_and_the_two_judges_for_theirs(self, monkeypatch):
        asked = []

        def summary(for_who="director"):
            asked.append(for_who)
            return f"LESSONS OF THE LAST DAYS ({for_who})\n- a line for the {for_who}"
        monkeypatch.setattr(bl, "summary", summary)
        judges, _out = full_round(monkeypatch)
        assert asked == ["director", "judges", "judges"]
        assert "a line for the director" in judges.prompt("da") and "for the judges" not in judges.prompt("da")
        for judge in ("verifier", "viewer"):
            assert "a line for the judges" in judges.prompt(judge) and "for the director" not in judges.prompt(judge)

    def test_the_block_sits_between_the_channels_text_and_the_clip(self, monkeypatch):
        put(DOWN)
        judges, _out = full_round(monkeypatch)
        block = "\n" + bl.summary("director") + "\n"                     # one blank line on each side of it
        principles, calibration = broll_ideas.skill_text("principes"), broll_ideas.skill_text("calibrage")
        assert f"{principles}\n{block}\nTHE CLIP: title" in judges.prompt("da")
        assert f"{calibration}\n{block}\nTHE CLIP: title" in judges.prompt("verifier")
        assert f"{calibration}\n{block}\nFor each sentence you get" in judges.prompt("viewer")

    def test_with_nothing_to_say_there_is_no_block_and_no_placeholder(self, monkeypatch):
        judges, _out = full_round(monkeypatch)
        principles, calibration = broll_ideas.skill_text("principes"), broll_ideas.skill_text("calibrage")
        for judge in ("da", "verifier", "viewer"):
            assert "LESSONS OF THE LAST DAYS" not in judges.prompt(judge) and "{lessons}" not in judges.prompt(judge), judge
        assert f"{principles}\n\nTHE CLIP: title" in judges.prompt("da")
        assert f"{calibration}\n\nTHE CLIP: title" in judges.prompt("verifier")
        assert f"{calibration}\n\nFor each sentence you get" in judges.prompt("viewer")

    def test_a_journal_of_things_that_teach_nothing_adds_no_block_either(self, monkeypatch):
        put(drops(2, "text in it"), keeps(3, 3))
        judges, _out = full_round(monkeypatch)
        assert not any("LESSONS OF THE LAST DAYS" in judges.prompt(j) for j in ("da", "verifier", "viewer"))

    def test_a_journal_of_patterns_alone_adds_no_block_either(self, monkeypatch):
        put(every_pattern(5))
        judges, _out = full_round(monkeypatch)
        assert len(bl.propose()) == 6                                   # the chain finds six patterns ...
        assert not any("LESSONS OF THE LAST DAYS" in judges.prompt(j) for j in ("da", "verifier", "viewer"))   # ... says none

    def test_a_validated_line_reaches_the_three_calls_and_no_pattern_does(self, monkeypatch):
        put(every_pattern(6))
        validate("Show the idea itself, never the setting around it.")
        proposed = bl.propose()
        assert len(proposed) == 6
        judges, _out = full_round(monkeypatch)
        for judge in ("da", "verifier", "viewer"):
            prompt = judges.prompt(judge)
            assert HEADER in prompt and "\n- Show the idea itself, never the setting around it.\n" in prompt, judge
            assert not any(line in prompt for line in proposed), judge

    def test_braces_and_percent_signs_of_a_note_do_not_break_a_prompt(self, monkeypatch):
        text = "a {chart} with {0} and {{x}} labels, 100% %s"
        put(owner("down", note=text))
        judges, (moments, _r) = full_round(monkeypatch)
        assert len(moments) == 1
        for judge in ("da", "verifier", "viewer"):
            assert f"rejected a picture: {text}." in judges.prompt(judge), judge

    def test_a_summary_that_fails_gives_an_empty_block_a_warning_and_the_round_goes_on(self, monkeypatch, capsys):
        def boom(for_who="director"):
            raise RuntimeError("journal unreadable")
        monkeypatch.setattr(bl, "summary", boom)
        judges, (moments, _r) = full_round(monkeypatch)
        assert judges.judges() == ["da", "verifier", "viewer"] and len(moments) == 1
        assert not any("LESSONS OF THE LAST DAYS" in judges.prompt(j) for j in ("da", "verifier", "viewer"))
        assert capsys.readouterr().out.count("Lessons: not read (journal unreadable)") == 3

    def test_the_block_changes_what_the_judges_read_and_nothing_else(self, monkeypatch):
        _j, (without, _r) = full_round(monkeypatch)
        put(DOWN, UP, drops(5, "pulls attention away", kind="scene"))
        _j, (with_lessons, _r) = full_round(monkeypatch)
        assert with_lessons == without and len(without) == 1

    def test_the_owners_thumbs_of_today_reach_the_next_calls(self, monkeypatch):
        judges, _out = full_round(monkeypatch)
        assert "owner rejected" not in judges.prompt("da")
        bl.record(owner("down", note="too dark, nothing to do with sleep"))     # a thumb down on the dashboard
        judges, _out = full_round(monkeypatch)
        assert "rejected a picture: too dark, nothing to do with sleep." in judges.prompt("da")


@pytest.mark.usefixtures("ideas_state")
class TestTheChosenIdeasFlaw:
    """The moment the round keeps carries ``idea_flaw``: the verifier's flaw of the idea chosen ("" when it gave none);
    broll_v20 notes it with the picture, so a lesson can say which kind of idea fails after the render."""

    def _round(self, monkeypatch, flaw, score, other=3):
        """Two ideas ranked "0" then "1" above the face; the first one flagged ``flaw`` by the verifier and scored
        ``score`` by the viewer. -> the moments of the round."""
        return run_round(
            monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST), dict(DINER)])),
            verifier=verifier_reply((0, [verdict(0, flaw=flaw), verdict(1)])),
            viewer=viewer_reply((0, [view(0, score), view(1, other)], ["0", "1", "face"])))[1][0]

    @pytest.mark.parametrize("flaw", list(broll_ideas.FLAWS))
    def test_the_moment_carries_the_verifiers_flaw_of_the_chosen_idea(self, monkeypatch, flaw):
        moments = self._round(monkeypatch, flaw, 5)                     # a 5 keeps even a flagged idea above the face
        assert moments[0]["spec"]["subject"] == CAST["subject"] and moments[0]["idea_flaw"] == flaw

    def test_it_is_the_flaw_of_the_idea_chosen_not_of_the_one_set_aside(self, monkeypatch):
        moments = self._round(monkeypatch, "stock", 4)                  # flagged and not a 5: under the face alone
        assert moments[0]["spec"]["subject"] == DINER["subject"] and moments[0]["idea_flaw"] == "none"

    def test_without_a_verdict_the_flaw_is_empty(self, monkeypatch):
        _j, (moments, _r) = run_round(monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST)])))   # no verifier, no viewer
        assert len(moments) == 1 and moments[0]["idea_flaw"] == ""

    def test_a_reserve_carries_it_too_and_the_editors_moments_are_left_alone(self, monkeypatch):
        first, spare = moment(), moment(15.3, anchor="alarm is gone")
        _j, (moments, reserves) = run_round(
            monkeypatch, [first], [spare], da=da_reply(da(0, [dict(CAST)]), da(1, [dict(DINER)])),
            verifier=verifier_reply((0, [verdict(0, flaw="symbol")]), (1, [verdict(0, flaw="figure")])),
            viewer=viewer_reply((0, [view(0, 5)], ["0", "face"]), (1, [view(0, 5)], ["0", "face"])))
        assert moments[0]["idea_flaw"] == "symbol" and reserves[0]["idea_flaw"] == "figure"
        assert "idea_flaw" not in first and "idea_flaw" not in spare
