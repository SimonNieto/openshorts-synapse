"""B-roll v21 « idées » (4-oct-2026): the round of ideas in text between the editor's moments and the rendering
(broll_ideas) — the channel's text (the skill), the three calls (art director, verifier, viewer) and their prompts, the
code's own refusal of an idea, the verifier's verdicts, the viewer's order with the face alone as the level zero, the
chosen idea becoming the moment's shot spec (the second one its alternative). No model is called: broll.claude_json is
replaced by a fake that answers by the schema object it is given (DA_SCHEMA / VERIFIER_SCHEMA / VIEWER_SCHEMA).
Rules of the end of v21: the hero is chosen AFTER the round among the ideas kept (hero_ok, the viewer's 4, the timing:
_pick_hero), an idea the verifier flags as weak is under the face unless the viewer gave it 5 (_above_face), and the
spec of an idea has two nets of the house (the inside of a body is drawn, nothing hangs near a death: _spec_of)."""
import inspect
import os
import re

import pytest

import ai_brain
import broll
import broll_ideas
import broll_spec
import shot_prompt

SENTENCES = ("I know of three clinical trials looking at MDMA.",
             "They have people move through their PTSD within four to six weeks total.",
             "So with two sessions of MDMA spaced apart about a month, the alarm is gone.",
             "That is how a ten year old wound looks when it heals.")


def _words(sentences, step=0.45, dur=0.4):
    out, t = [], 0.0
    for sentence in sentences:
        for w in sentence.split():
            out.append({"text": w, "start": round(t, 2), "end": round(t + dur, 2)})
            t += step
    return out


WORDS = _words(SENTENCES)                                # 49 words, 22 s
CLIP_TEXT = " ".join(w["text"] for w in WORDS)
CLIP = {"video_title_for_youtube_short": "MDMA Therapy Can Resolve PTSD in Just 4-6 Weeks",
        "viral_hook_text": "MDMA can resolve PTSD in just 4-6 weeks."}


def at(word):
    """The second a word of the clip starts."""
    return next(w["start"] for w in WORDS if re.sub(r"\W", "", w["text"]).lower() == word.lower())


# --- the editor's moments ------------------------------------------------------------------------------------------

def spec_(**kw):
    """A cleaned shot spec as broll_spec.plan_specs hands it to the round."""
    s = {"anchor": "move through", "time": 5.4, "said": SENTENCES[1], "worth": 4, "literal": "literal",
         "kind": "scene", "subject": "therapy room", "subject_words": "PTSD", "subject_b": "", "instrument": "",
         "count": "1", "state": "", "setting": "a clinic", "details": "", "people": "none", "person": "none",
         "shot": "medium", "death_near": False, "substance": False, "intake": False, "mood": {}, "hero": False,
         "role": "vehicle", "idea": "a trauma of years gone in weeks", "notion": "", "light": ""}
    s.update(kw)
    return s


def moment(t=5.4, anchor="move through", hero=False, alt=None, **spec):
    s = spec_(anchor=anchor, time=t, hero=hero, **spec)
    if alt:
        s["alt"] = alt
    return {"t": t, "anchor": anchor, "said": s["said"], "dur": 2.5, "hero": hero, "mood": {}, "spec": s,
            "clip_gravity": "none"}


# --- the art director's ideas -----------------------------------------------------------------------------------------
CAST = dict(title="The cast comes off", picture="A forearm just out of its cast, fingers opening on an examination table.",
            adds="healing in weeks, like a bone", reads="a cast removed: healed, and fast", kind="thing",
            subject="a forearm just out of its cast", count="1", state="fingers slowly opening",
            setting="an examination table by a window", details="two white cast shells open, pale skin",
            people="hands", person="anonymous", shot="close",
            light="soft window daylight from the left, late afternoon")
DINER = dict(title="Back to the door", picture="A man laughs with a friend in a diner booth, his back to the glass door.",
             adds="the alarm is gone", reads="a happy man at a diner", kind="scene",
             subject="a man laughing in a diner booth", count="1", state="laughing with a friend",
             setting="a diner at noon", details="coffee cups, a glass door behind him", people="group",
             person="anonymous", shot="medium", light="hard noon daylight through the window")
SCAR = dict(title="The old scar", picture="A healed scar across a weathered hand, a ring of pale skin around it.",
            adds="what stayed, and healed", reads="a scar that no longer hurts", kind="thing",
            subject="an old scar on a weathered hand", count="1", state="resting open on a table",
            setting="a wooden table", details="a pale ring of skin, a short white line", people="hands",
            person="anonymous", shot="macro", light="low evening light from the side")
SPEAKER = dict(CAST, title="A speaker", subject="Joe Rogan at the desk", picture="Joe Rogan at the desk, listening.")
DINER_HERO = dict(DINER, hero_ok=True)       # the director says this one could fill the whole phone screen (a real scene)
NO_HERO = "ideas: no hero"                   # the filter hit of a round whose ideas kept cannot fill the screen


# --- the fake model ------------------------------------------------------------------------------------------------------
def da(k, ideas, idea="a wound of the mind heals on a bone's calendar", role="vehicle", why=""):
    return {"k": k, "idea": idea, "role": role, "ideas": ideas, "no_picture_why": why}


def verdict(i, v="pass", reason="", details="", flaw="none"):
    return {"i": i, "verdict": v, "reason": reason, "details": details, "flaw": flaw}


def view(i, score=3, **kw):
    return {"i": i, "stops": "maybe", "feels": "", "link": "yes", "adds": "", "score": score, "flaw": "none",
            "unease": "", **kw}


def da_reply(*moments):
    return {"moments": list(moments)}


def verifier_reply(*moments):
    """``moments``: (k, [verdicts])."""
    return {"moments": [{"k": k, "ideas": list(vs)} for k, vs in moments]}


def viewer_reply(*moments):
    """``moments``: (k, [views], order)."""
    return {"moments": [{"k": k, "views": list(vs), "order": list(order)} for k, vs, order in moments]}


class Judges:
    """broll.claude_json, faked: answers by the schema object it is given and keeps every call as (judge, prompt,
    keywords). A reply is a dict or a function of the prompt; a judge with no reply answers nothing."""

    def __init__(self, da=None, verifier=None, viewer=None):
        self.replies = {"da": da, "verifier": verifier, "viewer": viewer}
        self.calls = []

    def __call__(self, prompt, schema, **kw):
        by_schema = {id(broll_ideas.DA_SCHEMA): "da", id(broll_ideas.VERIFIER_SCHEMA): "verifier",
                     id(broll_ideas.VIEWER_SCHEMA): "viewer"}
        judge = by_schema.get(id(schema))
        assert judge, "a call with a schema that is none of the three judges'"
        self.calls.append((judge, prompt, kw))
        reply = self.replies[judge]
        return (reply(prompt) if callable(reply) else reply) or {"moments": []}

    def judges(self):
        return [c[0] for c in self.calls]

    def prompt(self, judge):
        return next(c[1] for c in self.calls if c[0] == judge)

    def keywords(self, judge):
        return next(c[2] for c in self.calls if c[0] == judge)


def run_round(monkeypatch, moments, reserves=(), da=None, verifier=None, viewer=None, gravity="none", **timing):
    """``timing``: the keywords of the clip's timing rules (avoid, head, block) idea_round hands to the hero's choice."""
    judges = Judges(da, verifier, viewer)
    monkeypatch.setattr(broll, "claude_json", judges)
    return judges, broll_ideas.idea_round(list(moments), list(reserves), CLIP, WORDS, gravity, CLIP_TEXT, **timing)


def hero_round(monkeypatch, moments, ideas, scores, reserves=(), **timing):
    """A round with ONE idea a moment (the reserves come after the moments): ``ideas[k]`` is the director's idea of
    moment k, ``scores[k]`` the viewer's mark, the verifier passes every one. -> (moments, reserves) of the round."""
    n = len(moments) + len(reserves)
    _judges, out = run_round(
        monkeypatch, moments, reserves, da=da_reply(*(da(k, [dict(ideas[k])]) for k in range(n))),
        verifier=verifier_reply(*((k, [verdict(0)]) for k in range(n))),
        viewer=viewer_reply(*((k, [view(0, scores[k])], ["0", "face"]) for k in range(n))), **timing)
    return out


def spec_of(idea, gravity="none", **spec):
    """broll_ideas._spec_of: the editor's moment (its spec given ``spec``'s fields) with the render fields of ``idea``."""
    out, why = broll_ideas._spec_of(moment(**spec), idea, CLIP_TEXT, gravity)
    assert out and not why, why
    return out


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    broll.FILTERS.clear()
    del broll_ideas.LAST_IDEAS[:]
    monkeypatch.setattr(broll_ideas, "_CACHE", {})                    # skill_text keeps what it read
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    for stage in ("BROLL_IDEAS", "BROLL_VERIFY", "BROLL_VIEWER"):
        monkeypatch.delenv(f"BRAIN_{stage}", raising=False)
    monkeypatch.delenv("CLAUDE_EFFORT_BROLL_IDEAS", raising=False)
    yield
    broll.FILTERS.clear()
    del broll_ideas.LAST_IDEAS[:]


# ====================================================================================================================
# the channel's text
# ====================================================================================================================
class TestSkillText:
    def test_the_principles_are_the_skill_without_its_front_matter(self):
        text = broll_ideas.skill_text("principes")
        raw = open(os.path.join(broll_ideas.SKILL_DIR, "SKILL.md"), encoding="utf-8").read()
        body = raw.split("---", 2)[2] if raw.startswith("---") else raw           # what follows the front matter
        assert text == body.strip() and not text.startswith("---")
        assert not re.search(r"^(name|description):", text, re.M)                 # no key of the front matter
        assert "La précision" in text
        assert text == broll_ideas.skill_text()                                    # "principes" is the default

    def test_the_calibration_is_calibrage_md(self):
        text = broll_ideas.skill_text("calibrage")
        raw = open(os.path.join(broll_ideas.SKILL_DIR, "calibrage.md"), encoding="utf-8").read()
        assert text == raw.strip() and "Ce qui rate" in text and "Les repères" in text

    def test_the_two_parts_are_two_files(self):
        principles, calibration = broll_ideas.skill_text("principes"), broll_ideas.skill_text("calibrage")
        assert "Ce qui rate" not in principles and "Les repères" not in principles
        assert "La précision" not in calibration

    def test_the_front_matter_is_cut_and_a_file_without_one_is_kept_whole(self, monkeypatch, tmp_path):
        (tmp_path / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n\n# Body\n\nthe principles\n---\nmore\n",
                                           encoding="utf-8")
        (tmp_path / "calibrage.md").write_text("  # Calibration\n\nabove\n\n---\n\nbelow  \n", encoding="utf-8")
        monkeypatch.setattr(broll_ideas, "SKILL_DIR", str(tmp_path))
        assert broll_ideas.skill_text("principes") == "# Body\n\nthe principles\n---\nmore"
        assert broll_ideas.skill_text("calibrage") == "# Calibration\n\nabove\n\n---\n\nbelow"

    def test_a_text_is_read_once(self, monkeypatch, tmp_path):
        (tmp_path / "SKILL.md").write_text("First text.", encoding="utf-8")
        monkeypatch.setattr(broll_ideas, "SKILL_DIR", str(tmp_path))
        assert broll_ideas.skill_text() == "First text."
        (tmp_path / "SKILL.md").write_text("Second text.", encoding="utf-8")
        assert broll_ideas.skill_text("principes") == "First text."

    def test_a_missing_file_gives_a_short_fallback_and_a_warning_once(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(broll_ideas, "SKILL_DIR", str(tmp_path / "nowhere"))
        assert broll_ideas.skill_text("principes") == broll_ideas._FALLBACK["principes"]
        assert broll_ideas.skill_text("calibrage") == broll_ideas._FALLBACK["calibrage"]
        assert capsys.readouterr().out.count("not found") == 2                    # one warning per part
        broll_ideas.skill_text("principes")
        broll_ideas.skill_text("calibrage")
        assert capsys.readouterr().out == ""                                      # not again
        fallback = broll_ideas._FALLBACK
        assert len(fallback["principes"].split()) < 250 and fallback["calibrage"] not in fallback["principes"]


# ====================================================================================================================
# the three prompts
# ====================================================================================================================
def full_round(monkeypatch, moments=None, gravity="none"):
    """A round that reaches the three judges (two ideas for the moment)."""
    return run_round(monkeypatch, moments or [moment()], da=da_reply(da(0, [dict(CAST), dict(DINER)])),
                     verifier=verifier_reply((0, [verdict(0), verdict(1)])),
                     viewer=viewer_reply((0, [view(0, 4), view(1, 2)], ["0", "face", "1"])), gravity=gravity)


class TestPrompts:
    def test_the_art_director_reads_the_principles_and_never_the_calibration(self, monkeypatch):
        judges, _out = full_round(monkeypatch)
        p = judges.prompt("da")
        assert broll_ideas.skill_text("principes") in p and "La précision" in p
        assert broll_ideas.skill_text("calibrage") not in p
        assert "Les repères" not in p and "Ce qui rate" not in p
        assert "calibration" not in p.lower() and "name: synapse-cut" not in p      # nor the front matter

    def test_the_verifier_and_the_viewer_read_both(self, monkeypatch):
        judges, _out = full_round(monkeypatch)
        for judge in ("verifier", "viewer"):
            p = judges.prompt(judge)
            assert broll_ideas.skill_text("principes") in p and broll_ideas.skill_text("calibrage") in p, judge
            assert "La précision" in p and "Ce qui rate" in p and "Les repères" in p, judge
            assert "name: synapse-cut" not in p, judge

    def test_each_call_has_its_stage_its_model_and_one_call_serves_the_whole_clip(self, monkeypatch):
        judges, _out = full_round(monkeypatch, [moment(), moment(10.8, anchor="two sessions")])
        assert judges.judges() == ["da", "verifier", "viewer"]                     # no call per moment
        da_kw, ver_kw, view_kw = (judges.keywords(j) for j in ("da", "verifier", "viewer"))
        assert (da_kw["stage"], da_kw["model"], da_kw["effort"]) == ("broll_ideas", "opus", "high")
        assert (ver_kw["stage"], ver_kw["model"]) == ("broll_verify", "sonnet")
        assert (view_kw["stage"], view_kw["model"]) == ("broll_viewer", "sonnet")

    def test_the_models_and_the_effort_can_be_set(self, monkeypatch):
        monkeypatch.setenv("BRAIN_BROLL_IDEAS", "Sonnet")
        monkeypatch.setenv("BRAIN_BROLL_VIEWER", "Opus")
        monkeypatch.setenv("CLAUDE_EFFORT_BROLL_IDEAS", "max")
        judges, _out = full_round(monkeypatch)
        assert judges.keywords("da")["model"] == "sonnet" and judges.keywords("da")["effort"] == "max"
        assert judges.keywords("viewer")["model"] == "opus" and judges.keywords("verifier")["model"] == "sonnet"

    def test_the_art_director_is_told_the_clip_and_who_is_never_pictured(self, monkeypatch):
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", {"speakers": [{"name": "Joe Rogan"}],
                                                       "glossary": [{"term": "Default mode network"},
                                                                    {"term": "Psilocybin"}]})
        judges, _out = full_round(monkeypatch)
        p = judges.prompt("da")
        assert 'title "MDMA Therapy Can Resolve PTSD in Just 4-6 Weeks"' in p
        assert 'hook "MDMA can resolve PTSD in just 4-6 weeks."' in p
        assert "Clip gravity: none" in p and "Never pictured: the speakers (joe, rogan)" in p
        assert "The episode's notions: Default mode network, Psilocybin." in p
        assert "already planned elsewhere in the clip: therapy room." in p
        assert "ENGLISH" in p and f"up to {broll_ideas.IDEAS_PER_MOMENT} ideas" in p
        assert '"anchor": optional' in p and '"light"' in p and "no_picture_why" in p

    def test_the_art_director_says_which_ideas_could_fill_the_screen(self, monkeypatch):
        # the hero is chosen among the ideas kept: only the director knows whether a picture has the depth for it
        judges, _out = full_round(monkeypatch)
        p = judges.prompt("da")
        assert '"hero_ok": true when this picture could fill the whole phone screen' in p
        assert "false for a small thing, a pair or a flat" in p
        for judge in ("verifier", "viewer"):
            assert "hero_ok" not in judges.prompt(judge), judge                       # a question for the director only

    def test_a_clip_that_tells_a_death_says_so_to_the_director_and_the_verifier(self, monkeypatch):
        judges, _out = full_round(monkeypatch, gravity="grave")
        assert "Clip gravity: grave — a death is the clip's SUBJECT: every picture is an absence" in judges.prompt("da")
        assert 'Clip gravity: grave ("grave" = a death is the clip\'s subject' in judges.prompt("verifier")
        # the director is told nothing hangs: the engine hung a whole dobok from a thread (the code strips it as well)
        assert "nothing hangs from a rope, a cord or a thread" in judges.prompt("da")
        judges, _out = full_round(monkeypatch, gravity="real")
        assert "nothing hangs" not in judges.prompt("da")

    def test_the_art_director_is_told_its_render_fields_are_drawn_literally(self, monkeypatch):
        # the engine draws a comparison as the thing ("almond-shaped" gave a real almond) and writes whatever a
        # screen, a label or a sign shows: the director names the thing itself, never a screen, a page or a chart
        judges, _out = full_round(monkeypatch)
        for prompt in (broll_ideas.DA_PROMPT, judges.prompt("da")):
            flat = " ".join(prompt.split())                  # the second phrase wraps across two lines in the source
            assert "never a comparison in them" in flat
            assert "never a screen, a display, a label, a page, a sign or a chart" in flat

    def test_the_viewer_knows_nothing_of_the_episode(self, monkeypatch):
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", {"speakers": [{"name": "Joe Rogan"}],
                                                       "glossary": [{"term": "Default mode network"}]})
        judges, _out = full_round(monkeypatch, gravity="grave")
        w = judges.prompt("viewer")
        for episode in (CLIP["video_title_for_youtube_short"], CLIP["viral_hook_text"], "Clip gravity", "rogan",
                        "Default mode network"):
            assert episode not in w, episode
        for episode in (CLIP["video_title_for_youtube_short"], "rogan"):          # the director and the verifier do
            assert episode in judges.prompt("da") and episode in judges.prompt("verifier")

    def test_the_art_director_sees_each_moment_with_its_words_and_its_flags(self, monkeypatch):
        moments = [moment(5.4, hero=True, death_near=True),
                   moment(10.8, anchor="two sessions", substance=True),
                   moment(15.3, anchor="alarm is gone", kind="vision", subject="a tunnel of light"),
                   moment(18.9, anchor="year", kind="body_inside", subject="a drawn brain")]
        judges, _out = run_round(monkeypatch, moments)
        p = judges.prompt("da")
        assert 'MOMENT k=0 at 5.4 s (full-screen hero), the thing named: "therapy room"' in p
        assert "[mentions a death: nothing may evoke it]" in p
        assert "[a drug or an intake is involved: never shown]" in p
        assert "[an experience: what is perceived]" in p and "[the inside of a body: drawn]" in p
        # the sentence spoken, the one before and the one after
        assert f'before: "{SENTENCES[0]}"' in p and f'SAID: "{SENTENCES[1]}"' in p and f'after: "{SENTENCES[2]}"' in p
        assert f'MOMENT k=3 at 18.9 s, the thing named: "a drawn brain" [the inside of a body: drawn]\n' \
               f'  before: "{SENTENCES[2]}"' in p
        assert "already planned elsewhere in the clip: therapy room, therapy room, a tunnel of light, a drawn brain." in p

    def test_the_verifier_sees_the_render_fields_and_the_viewer_only_the_pictures(self, monkeypatch):
        judges, _out = full_round(monkeypatch)
        v, w = judges.prompt("verifier"), judges.prompt("viewer")
        assert f'MOMENT k=0: before "{SENTENCES[0]}" / SAID "{SENTENCES[1]}"' in v
        assert f"[0] {CAST['picture']} (kind thing, people hands, light: {CAST['light']})" in v
        assert f"[1] {DINER['picture']} (kind scene, people group, light: {DINER['light']})" in v
        assert f'SENTENCE k=0: subtitle "{SENTENCES[1]}"; heard just before: "{SENTENCES[0]}"' in w
        assert f"[0] {CAST['picture']}\n" in w and f"[1] {DINER['picture']}" in w
        assert "kind thing" not in w and "light:" not in w and "people hands" not in w   # a viewer sees a picture only
        assert 'with "face" placed where the face alone' in w and "FACE ALONE" in w

    def test_a_refused_idea_is_in_no_judges_prompt_and_a_moment_without_ideas_is_not_listed(self, monkeypatch):
        judges, _out = run_round(monkeypatch, [moment(), moment(10.8, anchor="two sessions")],
                                 da=da_reply(da(0, [dict(CAST)]), da(1, [])),
                                 verifier=verifier_reply((0, [verdict(0)])),
                                 viewer=viewer_reply((0, [view(0)], ["0", "face"])))
        for judge in ("verifier", "viewer"):
            assert "k=0" in judges.prompt(judge) and "k=1" not in judges.prompt(judge), judge


# ====================================================================================================================
# the code's own check, the verifier, the viewer
# ====================================================================================================================
class TestTheCodeRefuses:
    def test_a_speaker_never_reaches_the_judges(self, monkeypatch):
        # person "real" cannot pass the schema (none / anonymous); a speaker named in the subject can: the code refuses
        monkeypatch.setattr(broll, "_speaker_words", lambda: {"rogan"})
        judges, (moments, _r) = run_round(
            monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST), dict(SPEAKER), dict(DINER)])),
            verifier=verifier_reply((0, [verdict(0), verdict(2)])),                      # it was never shown the [1]
            viewer=viewer_reply((0, [view(0, 3), view(2, 4)], ["1", "2", "face", "0"])))   # a judge naming it changes nothing
        v, w = judges.prompt("verifier"), judges.prompt("viewer")
        for p in (v, w):
            assert "Rogan" not in p and "[1]" not in p and "[0]" in p and "[2]" in p
        assert broll.FILTERS["ideas: a speaker of the video"] == 1
        # the best live idea above the face is chosen: "2" ("1" is no idea any more, "0" is after the face)
        assert moments[0]["spec"]["subject"] == DINER["subject"] and "alt" not in moments[0]["spec"]
        record = broll_ideas.LAST_IDEAS[0]
        assert [i["verdict"] for i in record["ideas"]] == ["pass", "refused by the code", "pass"]
        assert [i["above_face"] for i in record["ideas"]] == [False, False, True]
        assert record["chosen"] == 2

    def test_every_idea_refused_by_the_code_means_no_judge_is_called(self, monkeypatch):
        monkeypatch.setattr(broll, "_speaker_words", lambda: {"rogan"})
        judges, (moments, reserves) = run_round(monkeypatch, [moment()],
                                                da=da_reply(da(0, [dict(SPEAKER), dict(SPEAKER)])))
        assert judges.judges() == ["da"] and (moments, reserves) == ([], [])
        assert broll.FILTERS["ideas: a speaker of the video"] == 2
        assert broll.FILTERS["ideas: no idea above the face alone"] == 1
        assert broll_ideas.LAST_IDEAS[0]["chosen"] is None

    @pytest.mark.parametrize("flags,gravity,reason", [
        ({"death_near": True, "substance": True}, "none", "a death with a substance or an intake"),
        ({"death_near": True, "intake": True}, "real", "a death with a substance or an intake"),
        ({"substance": True}, "grave", "a substance in a clip about a death"),
        ({"intake": True}, "grave", "a substance in a clip about a death")])
    def test_a_death_with_a_substance_and_a_substance_in_a_grave_clip_have_no_idea(self, monkeypatch, flags, gravity,
                                                                                    reason):
        judges, (moments, _r) = run_round(monkeypatch, [moment(**flags)], gravity=gravity,
                                          da=da_reply(da(0, [dict(CAST), dict(DINER), dict(SCAR)])))
        assert broll.FILTERS[f"ideas: {reason}"] == 3 and moments == []
        assert judges.judges() == ["da"]

    @pytest.mark.parametrize("flags,gravity", [({"death_near": True}, "none"), ({"death_near": True}, "real"),
                                               ({"death_near": True}, "grave"), ({"substance": True}, "none"),
                                               ({"substance": True, "intake": True}, "real")])
    def test_a_death_in_passing_or_a_substance_alone_keeps_its_ideas(self, monkeypatch, flags, gravity):
        _judges, (moments, _r) = run_round(monkeypatch, [moment(**flags)], gravity=gravity,
                                           da=da_reply(da(0, [dict(CAST)])))
        # no refusal of any kind (the hero's own hit does not count: this idea is no scene for the whole screen)
        assert len(moments) == 1 and not [n for n in broll.FILTERS if n.startswith("ideas:") and n != NO_HERO]
        assert all(moments[0]["spec"][k] == v for k, v in flags.items())          # the flags travel with the spec

    def test_the_idea_is_fixed_like_a_spec(self, monkeypatch):
        vision = dict(CAST, kind="vision", subject="a tunnel of white light", people="one", person="anonymous")
        _j, (moments, _r) = run_round(monkeypatch, [moment()], da=da_reply(da(0, [vision])))
        assert moments[0]["spec"]["people"] == "none" and moments[0]["spec"]["person"] == "none"   # nobody in a vision
        assert set(broll.FILTERS) <= {NO_HERO}                                    # nothing refused, nothing to report
        # a clip about a death: nobody in the frame, whatever the idea says
        group = dict(DINER, kind="thing", subject="a coat on a hook")
        _j, (moments, _r) = run_round(monkeypatch, [moment(mood={"gravity": "real", "valence": "grim"})],
                                      gravity="grave", da=da_reply(da(0, [group])))
        spec = moments[0]["spec"]
        assert spec["people"] == "none" and spec["person"] == "none" and spec["mood"]["gravity"] == "grave"
        # the kind's own fields; the word caps
        long = dict(CAST, kind="instrument", instrument="scanning electron microscope with a long name", subject_b="x",
                    subject=" ".join(["petal"] * 12), light=" ".join(["lamp"] * 20))
        _j, (moments, _r) = run_round(monkeypatch, [moment()], da=da_reply(da(0, [long])))
        spec = moments[0]["spec"]
        assert len(spec["instrument"].split()) == 5 and spec["subject_b"] == "" and len(spec["subject"].split()) == 8
        assert len(spec["light"].split()) == 12


# the core anatomy words of broll_ideas._BODY_RE, each of them alone in a subject
BODY_WORDS = ["muscle", "muscles", "tendon", "tendons", "nerve", "nerves", "nerve fibres", "organ", "organs", "tissue",
              "tissues", "brain", "brains", "neuron", "neurons", "synapse", "synapses", "synaptic", "artery", "arteries",
              "vein", "veins", "intestine", "intestines", "lung", "lungs", "skull", "cortex", "spinal cord", "blood vessel",
              "blood vessels", "receptor", "receptors", "vesicle", "vesicles", "neurotransmitter", "neurotransmitters",
              "dopamine", "serotonin", "molecule", "molecules"]
# a dobok hung from a thread: the engine drew one for a clip about a death (every field the net cleans has a word of it,
# an old one and a new one: hanging / hung / dangling / suspended, a loose / looped / rope belt)
HUNG = dict(CAST, subject="a white dobok hanging in the air", state="hanging loose, turning slowly",
            setting="a dojo with a loosened mat dangling",
            details="a jacket hung from a hook, a looped mat suspended above")


class TestTheBodyNet:
    """The inside of a body named in the words of an idea is drawn, whatever kind the director declared (a skinned arm
    with its muscles came out as a photograph): thing / scene / vision / instrument become "body_inside", nobody in the
    frame, no instrument. Core anatomy only: "cell", "heart" or "bone" alone are too often something else."""

    @pytest.mark.parametrize("word", BODY_WORDS)
    def test_core_anatomy_in_the_subject_is_drawn(self, word):
        s = spec_of(dict(CAST, subject=f"a close view of {word}"))                # a "thing" with hands, as declared
        assert (s["kind"], s["people"], s["person"], s["instrument"]) == ("body_inside", "none", "none", "")

    @pytest.mark.parametrize("kind", ["thing", "scene", "vision", "instrument"])
    @pytest.mark.parametrize("field", ["subject", "details", "state"])
    def test_every_kind_is_caught_in_each_of_the_three_fields(self, kind, field):
        idea = dict(CAST, kind=kind, instrument="fluorescence microscope" if kind == "instrument" else "")
        assert spec_of(idea)["kind"] == kind                                      # nothing of anatomy in the idea itself
        idea[field] = "a glowing synapse"
        s = spec_of(idea)
        assert (s["kind"], s["people"], s["person"], s["instrument"]) == ("body_inside", "none", "none", "")
        assert s[field] == "a glowing synapse"                                    # the words are the idea's own, kept

    def test_the_words_are_read_whatever_their_case_and_among_others(self):
        assert spec_of(dict(CAST, subject="A BRAIN and its Neurons"))["kind"] == "body_inside"
        assert spec_of(dict(CAST, details="long white nerves, a pale skin"))["kind"] == "body_inside"
        assert spec_of(dict(CAST, state="firing, a dopamine release"))["kind"] == "body_inside"

    @pytest.mark.parametrize("subject", ["a prison cell", "the heart of a busy city", "a broken bone in a cast",
                                         "a brainstorm", "an organic garden", "a veined leaf", "lunges at a gym"])
    def test_cell_heart_and_bone_alone_and_words_that_only_look_alike_are_no_anatomy(self, subject):
        s = spec_of(dict(CAST, subject=subject))
        assert (s["kind"], s["people"], s["person"]) == ("thing", "hands", "anonymous")      # as declared

    def test_only_the_subject_the_details_and_the_state_are_read(self):
        s = spec_of(dict(CAST, setting="a brain imaging lab", light="the glow of a brain scan screen"))
        assert s["kind"] == "thing" and s["setting"] == "a brain imaging lab"

    def test_a_drawn_inside_and_a_pair_are_left_as_they_are(self):
        drawn = spec_of(dict(CAST, kind="body_inside", subject="a drawn brain", people="one", person="anonymous"))
        assert drawn["kind"] == "body_inside" and drawn["people"] == "none" and drawn["person"] == "none"
        pair = spec_of(dict(CAST, kind="pair", subject="a human brain", subject_b="a chimpanzee brain"))
        assert pair["kind"] == "pair" and pair["subject"] == "a human brain" and pair["subject_b"] == "a chimpanzee brain"

    def test_the_net_reaches_the_moment_and_the_prompt_is_a_drawing(self, monkeypatch):
        arm = dict(CAST, title="The muscles of the arm", picture="A forearm, its muscles and tendons laid bare.",
                   subject="a forearm with its muscles laid bare", details="long red tendons, folded muscle fibres",
                   people="hands")
        _j, (moments, _r) = run_round(monkeypatch, [moment(people="group")], da=da_reply(da(0, [arm])))
        m = moments[0]
        assert m["inside_body"] is True and m["people"] == "none"                 # the moment follows the spec
        assert (m["spec"]["kind"], m["spec"]["people"], m["spec"]["person"]) == ("body_inside", "none", "none")
        text = shot_prompt.build_prompt(m["spec"], "card", "A gouache drawing.")
        assert text.startswith("A gouache drawing. It shows a single forearm with its muscles laid bare")
        assert "documentary photograph" not in text and "hands" not in text.replace("A gouache drawing.", "")


class TestTheHangNet:
    """In a clip about a death (gravity "grave"), or on a sentence that mentions one (death_near), nothing "hangs": the
    words hanging / hangs / hung / suspended / dangling / dangles, and what a thing hangs from or by (loose / loosened,
    cord(s), rope(s), string(s), thread(s), strap(s), loop(s) / looped, noose) are taken out of the idea's subject,
    state, details and setting (the engine hung a whole dobok from a thread, and kept the thread when only "hanging"
    was cut)."""
    CLEAN = {"subject": "a white dobok in the air", "state": "turning slowly", "setting": "a dojo with a mat",
             "details": "a jacket from a hook, a mat above"}
    OLD_WORDS = ["hanging", "hangs", "hung", "suspended", "dangling", "dangles"]
    NEW_WORDS = ["loose", "loosened", "string", "strings", "thread", "threads",
                 "loop", "loops", "looped", "noose"]
    IN_ANY_CASE = ["Hanging", "SUSPENDED", "Dangles", "Thread", "NOOSE", "Looped"]
    ANY_HANG_WORD = re.compile(r"\b(?:hanging|hangs|hung|suspended|dangling|dangles|loose|loosened|cords?|ropes?|"
                               r"strings?|threads?|straps?|loops?|looped|noose)\b", re.I)
    FOUR_FIELDS = ("subject", "state", "setting", "details")

    @staticmethod
    def field(name, text, gravity="grave", **spec):
        """What the net makes of ``text`` written in the field ``name`` of an idea."""
        return spec_of(dict(CAST, **{name: text}), gravity, **spec)[name]

    def test_in_a_grave_clip_the_four_fields_lose_the_words_and_nothing_else(self):
        s = spec_of(HUNG, "grave")
        assert {k: s[k] for k in self.CLEAN} == self.CLEAN

    @pytest.mark.parametrize("gravity", ["none", "real"])
    def test_a_sentence_that_mentions_a_death_is_cleaned_in_any_clip(self, gravity):
        s = spec_of(HUNG, gravity, death_near=True)
        assert {k: s[k] for k in self.CLEAN} == self.CLEAN and s["death_near"] is True

    @pytest.mark.parametrize("gravity", ["none", "real"])
    def test_in_any_other_clip_the_words_stay(self, gravity):
        s = spec_of(HUNG, gravity)
        assert {k: s[k] for k in self.CLEAN} == {k: HUNG[k] for k in self.CLEAN}
        s = spec_of(HUNG, gravity, death_near=False, substance=True)
        assert s["subject"] == HUNG["subject"] and s["state"] == HUNG["state"]

    @pytest.mark.parametrize("word", OLD_WORDS + NEW_WORDS + IN_ANY_CASE)
    def test_each_of_the_words_in_any_case(self, word):
        text = f"a white dobok {word} in the dojo"
        assert self.field("subject", text) == "a white dobok in the dojo"
        assert self.field("subject", text, "none") == text                       # in any other clip it stays

    @pytest.mark.parametrize("name", FOUR_FIELDS)
    @pytest.mark.parametrize("word", ["loosened", "strings", "noose", "thread"])
    def test_the_new_words_are_taken_out_of_each_of_the_four_fields(self, word, name):
        text = f"a white dobok {word} in the dojo"
        assert self.field(name, text) == "a white dobok in the dojo"
        assert self.field(name, text, "none", death_near=True) == "a white dobok in the dojo"
        assert self.field(name, text, "real") == text

    @pytest.mark.parametrize("state", ["hanging from a thread", "dangling by a thread", "suspended on a string",
                                       "held up by a loop", "tied in a loop", "a noose", "loose, then loosened"])
    def test_what_it_hangs_from_goes_with_it(self, state):
        # cutting "hanging" alone left "from a thread": the engine still hung the dobok from it
        assert not self.ANY_HANG_WORD.search(self.field("state", state)), state
        assert self.field("state", state, "real") == state

    @pytest.mark.parametrize("idea", [
        dict(CAST, subject="a coat on a hanger", state="a hangar door open", setting="a field with hungry crows",
             details="red suspenders, a hang glider"),
        # nor the words that only start or end like the new ones
        dict(CAST, subject="a corduroy jacket", state="a looping film reel", setting="a threadbare rug",
             details="a strapless dress, a loophole, a cordless lamp, a stringed instrument, loosely folded")])
    def test_words_that_only_look_like_them_are_not_touched(self, idea):
        s = spec_of(idea, "grave")
        assert {k: s[k] for k in self.FOUR_FIELDS} == {k: idea[k] for k in self.FOUR_FIELDS}

    @pytest.mark.parametrize("word", ["belt", "straps", "tie", "scarf", "cord", "rope", "cable", "tube", "laces",
                                      "stethoscope", "Belt"])
    def test_a_strap_like_thing_is_refused_outright_in_a_clip_about_a_death(self, word):
        # third bench: a taekwondo belt "coiled on a wall hook" came out hanging from the hook like a strap, in the
        # clip "He took his own life" — the engine cannot be trusted to keep it flat, so the idea is refused
        for field in ("subject", "details", "state", "subject_b", "details_b"):
            idea = dict(CAST, **{field: f"a white dobok with a {word} folded flat"})
            out, why = broll_ideas._spec_of(moment(), idea, CLIP_TEXT, "grave")
            assert out is None and why == "a strap-like thing in a clip about a death", (field, word)
            out, why = broll_ideas._spec_of(moment(death_near=True), idea, CLIP_TEXT, "none")
            assert out is None and why == "a strap-like thing in a clip about a death", (field, word)
            assert broll_ideas._spec_of(moment(), idea, CLIP_TEXT, "none")[0] is not None     # any other clip: fine

    def test_the_net_reaches_the_picture_prompt_of_a_grave_clip(self, monkeypatch):
        _j, (moments, _r) = run_round(monkeypatch, [moment()], gravity="grave", da=da_reply(da(0, [dict(HUNG)])))
        text = shot_prompt.build_prompt(moments[0]["spec"], "card")
        assert "a single white dobok in the air, turning slowly, in a dojo with a mat." in text
        assert "Visible details: a jacket from a hook, a mat above." in text
        assert not re.search(r"hang|hung|suspend|dangl", text, re.I) and not self.ANY_HANG_WORD.search(text)
        # the same idea in a clip that mentions no death is left alone
        _j, (moments, _r) = run_round(monkeypatch, [moment()], da=da_reply(da(0, [dict(HUNG)])))
        text = shot_prompt.build_prompt(moments[0]["spec"], "card")
        assert ("a single white dobok hanging in the air, hanging loose, turning slowly, "
                "in a dojo with a loosened mat dangling.") in text
        assert "Visible details: a jacket hung from a hook, a looped mat suspended above." in text


class TestTheHeroOkOfTheSpec:
    @pytest.mark.parametrize("given,expect", [(True, True), (False, False), (None, False), ("true", False),
                                              ("yes", False), (1, False), ("", False)])
    def test_the_spec_carries_hero_ok_only_when_the_director_said_exactly_true(self, given, expect):
        assert spec_of(dict(CAST, hero_ok=given))["hero_ok"] is expect

    def test_an_idea_that_says_nothing_cannot_fill_the_screen_whatever_the_editor_marked(self):
        s = spec_of(dict(CAST), hero=True)
        assert s["hero_ok"] is False and s["hero"] is True                       # the editor's mark is another thing
        assert spec_of(dict(CAST, hero_ok=True), hero=False)["hero_ok"] is True

    def test_an_alternative_does_not_carry_it(self, monkeypatch):
        # the alternative is the second idea's render fields (broll_spec.ALT_FIELDS and the light): no hero_ok
        _j, (moments, _r) = run_round(
            monkeypatch, [moment()], da=da_reply(da(0, [dict(DINER_HERO), dict(CAST, hero_ok=True)])),
            verifier=verifier_reply((0, [verdict(0), verdict(1)])),
            viewer=viewer_reply((0, [view(0, 5), view(1, 4)], ["0", "1", "face"])))
        spec = moments[0]["spec"]
        assert spec["hero_ok"] is True and "hero_ok" not in spec["alt"] and "hero_ok" not in broll_spec.ALT_FIELDS


class TestTheVerifier:
    def _ideas(self):
        return da_reply(da(0, [dict(CAST), dict(DINER), dict(SCAR)]))

    def test_a_refusal_removes_the_idea(self, monkeypatch):
        judges, (moments, _r) = run_round(
            monkeypatch, [moment()], da=self._ideas(),
            verifier=verifier_reply((0, [verdict(0, "refuse", "a real person of the story"), verdict(1), verdict(2)])),
            viewer=viewer_reply((0, [view(1, 3), view(2, 4)], ["0", "2", "face", "1"])))
        assert CAST["picture"] not in judges.prompt("viewer")                    # the viewer never saw it
        assert broll.FILTERS["ideas: refused by the verifier"] == 1
        # the viewer ranked it first anyway: it is not live, so the best of the others above the face is chosen
        assert moments[0]["spec"]["subject"] == SCAR["subject"] and "alt" not in moments[0]["spec"]
        record = broll_ideas.LAST_IDEAS[0]
        assert record["chosen"] == 2 and record["ideas"][0]["verdict"] == "refuse"
        assert record["ideas"][0]["reason"] == "a real person of the story" and record["ideas"][0]["above_face"] is False

    def test_every_idea_refused_means_no_viewer_and_no_picture(self, monkeypatch):
        judges, (moments, reserves) = run_round(
            monkeypatch, [moment()], da=self._ideas(),
            verifier=verifier_reply((0, [verdict(0, "refuse"), verdict(1, "refuse"), verdict(2, "refuse")])))
        assert judges.judges() == ["da", "verifier"] and (moments, reserves) == ([], [])
        assert broll.FILTERS["ideas: refused by the verifier"] == 3
        assert broll.FILTERS["ideas: no idea above the face alone"] == 1

    def test_a_fix_replaces_the_details_of_the_spec(self, monkeypatch):
        fixed = 'two white cast shells open, "clean" pale skin,   fingers half open'
        # the flaw "object" is held against the idea unless the viewer gave it 5 (TestTheVerifiersFlaws): it did
        _j, (moments, _r) = run_round(
            monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST), dict(DINER)])),
            verifier=verifier_reply((0, [verdict(0, "fix", "white powder reads as a drug", details=fixed, flaw="object"),
                                         verdict(1)])),
            viewer=viewer_reply((0, [view(0, 5), view(1, 3)], ["0", "1", "face"])))
        spec = moments[0]["spec"]
        assert spec["details"] == "two white cast shells open, 'clean' pale skin, fingers half open"   # one line, no "
        assert spec["alt"]["details"] == DINER["details"]                        # the other idea keeps its own
        assert broll.FILTERS["ideas: fixed by the verifier (fixed)"] == 1
        record = broll_ideas.LAST_IDEAS[0]["ideas"][0]
        assert record["verdict"] == "fix" and record["reason"] == "white powder reads as a drug"
        assert record["flaw"] == "object"

    def test_a_fix_reaches_the_alternative_too(self, monkeypatch):
        _j, (moments, _r) = run_round(
            monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST), dict(DINER)])),
            verifier=verifier_reply((0, [verdict(0), verdict(1, "fix", "too dark", details="a bright noon street")])),
            viewer=viewer_reply((0, [view(0, 4), view(1, 3)], ["0", "1", "face"])))
        assert moments[0]["spec"]["details"] == CAST["details"]
        assert moments[0]["spec"]["alt"]["details"] == "a bright noon street"

    def test_a_fix_without_details_changes_nothing_and_a_flaw_is_no_refusal(self, monkeypatch):
        # a flaw is information, not a verdict: the viewer of the picture has the last word (5 keeps the idea)
        _j, (moments, _r) = run_round(
            monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST)])),
            verifier=verifier_reply((0, [verdict(0, "fix", "unclear", details="  ", flaw="stock")])),
            viewer=viewer_reply((0, [view(0, 5)], ["0", "face"])))
        assert moments[0]["spec"]["details"] == CAST["details"]
        assert "ideas: fixed by the verifier (fixed)" not in broll.FILTERS
        assert broll_ideas.LAST_IDEAS[0]["ideas"][0]["flaw"] == "stock" and broll_ideas.LAST_IDEAS[0]["chosen"] == 0

    def test_a_verdict_about_an_idea_that_does_not_exist_is_ignored(self, monkeypatch):
        _j, (moments, _r) = run_round(
            monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST)])),
            verifier=verifier_reply((0, [verdict(0), verdict(7, "refuse")]), (5, [verdict(0, "refuse")])),
            viewer=viewer_reply((0, [view(0)], ["0", "face"])))
        assert len(moments) == 1 and "ideas: refused by the verifier" not in broll.FILTERS

    def test_an_unknown_verdict_is_a_pass_and_an_unknown_flaw_none(self, monkeypatch):
        reply = {"moments": [{"k": 0, "ideas": [{"i": 0, "verdict": "maybe", "reason": "x" * 300, "flaw": "weird",
                                                 "details": "  plain   details "}, {"i": "1", "verdict": "refuse"}]},
                             {"k": "1", "ideas": [{"i": 0, "verdict": "refuse"}]}, "junk"]}
        monkeypatch.setattr(broll, "claude_json", Judges(verifier=reply))
        out = broll_ideas._verify([moment()], WORDS, CLIP, "none", {0: [dict(CAST)]})
        assert out == {(0, 0): {"verdict": "pass", "reason": "x" * 98, "details": "plain details", "flaw": "none"}}


class TestTheViewer:
    def _ideas(self):
        return da_reply(da(0, [dict(CAST), dict(DINER), dict(SCAR)]))

    def test_ideas_after_the_face_are_dropped_the_first_above_it_is_the_spec_the_second_the_alt(self, monkeypatch):
        editors_alt = {"subject": "the editor's own alternative"}
        # the chosen idea ("1") is one the director says can fill the screen: the moment is the hero (TestTheHero)
        judges, (moments, reserves) = run_round(
            monkeypatch, [moment(alt=editors_alt, hero=True)],
            da=da_reply(da(0, [dict(CAST), dict(DINER_HERO), dict(SCAR)])),
            verifier=verifier_reply((0, [verdict(0), verdict(1), verdict(2)])),
            viewer=viewer_reply((0, [view(0, 3), view(1, 5), view(2, 4)], ["1", "0", "face", "2"])))
        assert reserves == [] and len(moments) == 1
        m = moments[0]
        spec = m["spec"]
        # the best idea above the face is the spec: its render fields and its light ...
        assert spec["subject"] == DINER["subject"] and spec["kind"] == "scene" and spec["people"] == "group"
        assert spec["setting"] == DINER["setting"] and spec["details"] == DINER["details"] and spec["shot"] == "medium"
        assert spec["light"] == DINER["light"]
        # ... the second one the alternative (the render fields and the light), the third none, the editor's own gone
        assert set(spec["alt"]) == set(broll_spec.ALT_FIELDS) | {"light"}
        assert spec["alt"]["subject"] == CAST["subject"] and spec["alt"]["light"] == CAST["light"]
        assert spec["alt"]["people"] == "hands" and spec["alt"]["details"] == CAST["details"]
        assert SCAR["subject"] not in repr(spec) and "editor's own" not in repr(spec)
        # the spec keeps what the editor knew of the moment
        assert spec["anchor"] == "move through" and spec["time"] == at("move") and spec["worth"] == 4
        assert spec["subject_words"] == "PTSD" and spec["role"] == "vehicle" and spec["literal"] == "literal"
        assert spec["idea"] == "a trauma of years gone in weeks" and spec["hero"] is True      # spec["hero"]: the editor's mark
        assert spec["hero_ok"] is True                                            # what the director said of the idea
        # and the moment follows the spec
        assert m["query"] == m["subject"] == DINER["subject"] and m["people"] == "group" and m["inside_body"] is False
        assert m["idea_text"] == "a wound of the mind heals on a bone's calendar" and m["role"] == "vehicle"
        assert m["picture"] == DINER["picture"] and m["t"] == at("move") and m["hero"] is True
        record = broll_ideas.LAST_IDEAS[0]
        assert record["chosen"] == 1 and [i["above_face"] for i in record["ideas"]] == [True, True, False]
        assert [i["score"] for i in record["ideas"]] == [3, 5, 4]

    def test_a_single_idea_above_the_face_has_no_alternative(self, monkeypatch):
        _j, (moments, _r) = run_round(
            monkeypatch, [moment(alt={"subject": "the editor's own alternative"})], da=self._ideas(),
            verifier=verifier_reply((0, [verdict(0), verdict(1), verdict(2)])),
            viewer=viewer_reply((0, [view(0, 4), view(1, 4), view(2, 4)], ["0", "face", "1", "2"])))
        assert moments[0]["spec"]["subject"] == CAST["subject"] and "alt" not in moments[0]["spec"]

    def test_an_idea_ranked_under_the_face_alone_is_dropped_and_so_is_the_moment(self, monkeypatch):
        _j, (moments, reserves) = run_round(
            monkeypatch, [moment()], da=self._ideas(),
            verifier=verifier_reply((0, [verdict(0), verdict(1), verdict(2)])),
            viewer=viewer_reply((0, [view(0, 4), view(1, 3), view(2, 3)], ["face", "0", "1", "2"])))
        assert (moments, reserves) == ([], [])
        assert broll.FILTERS["ideas: no idea above the face alone"] == 1
        assert "ideas: no picture (the director)" not in broll.FILTERS
        record = broll_ideas.LAST_IDEAS[0]
        assert record["chosen"] is None and not any(i["above_face"] for i in record["ideas"])

    def test_the_moments_are_judged_one_by_one(self, monkeypatch):
        ms = [moment(), moment(10.8, anchor="two sessions")]
        _j, (moments, _r) = run_round(
            monkeypatch, ms, da=da_reply(da(0, [dict(CAST), dict(DINER)]), da(1, [dict(SCAR), dict(DINER)])),
            verifier=verifier_reply((0, [verdict(0), verdict(1)]), (1, [verdict(0), verdict(1)])),
            viewer=viewer_reply((0, [view(0), view(1)], ["face", "0", "1"]),
                                (1, [view(0), view(1)], ["1", "face", "0"])))
        assert [m["spec"]["subject"] for m in moments] == [DINER["subject"]]       # the first moment has no idea left
        assert moments[0]["anchor"] == "two sessions" and moments[0]["t"] == at("two")
        assert broll.FILTERS["ideas: no idea above the face alone"] == 1

    def test_a_viewer_with_no_answer_leaves_the_directors_order(self, monkeypatch):
        judges, (moments, _r) = run_round(monkeypatch, [moment()], da=self._ideas(),
                                          verifier=verifier_reply((0, [verdict(0), verdict(1), verdict(2)])))
        assert judges.judges() == ["da", "verifier", "viewer"]
        assert moments[0]["spec"]["subject"] == CAST["subject"] and moments[0]["spec"]["alt"]["subject"] == DINER["subject"]
        assert broll_ideas.LAST_IDEAS[0]["chosen"] == 0

    def test_an_idea_scored_under_three_is_under_the_face_whatever_its_rank(self, monkeypatch):
        # "no link, or a stock photo": the viewer may rank it above the face alone, the code does not follow
        assert broll_ideas.MIN_SCORE == 3
        _j, (moments, _r) = run_round(
            monkeypatch, [moment()], da=self._ideas(),
            verifier=verifier_reply((0, [verdict(0), verdict(1), verdict(2)])),
            viewer=viewer_reply((0, [view(0, 2), view(1, 4), view(2, 1)], ["0", "1", "2", "face"])))
        spec = moments[0]["spec"]
        assert spec["subject"] == DINER["subject"] and "alt" not in spec
        record = broll_ideas.LAST_IDEAS[0]
        assert record["chosen"] == 1 and [i["above_face"] for i in record["ideas"]] == [False, True, False]
        assert [i["score"] for i in record["ideas"]] == [2, 4, 1]

    def test_a_score_of_three_is_enough_and_the_next_one_above_the_face_is_the_alternative(self, monkeypatch):
        _j, (moments, _r) = run_round(
            monkeypatch, [moment()], da=self._ideas(),
            verifier=verifier_reply((0, [verdict(0), verdict(1), verdict(2)])),
            viewer=viewer_reply((0, [view(0, 3), view(1, 2), view(2, 3)], ["0", "1", "2", "face"])))
        spec = moments[0]["spec"]
        assert spec["subject"] == CAST["subject"] and spec["alt"]["subject"] == SCAR["subject"]     # "1" scored 2: skipped
        assert [i["above_face"] for i in broll_ideas.LAST_IDEAS[0]["ideas"]] == [True, False, True]

    def test_every_idea_scored_under_three_is_no_picture(self, monkeypatch):
        _j, (moments, reserves) = run_round(
            monkeypatch, [moment()], da=self._ideas(),
            verifier=verifier_reply((0, [verdict(0), verdict(1), verdict(2)])),
            viewer=viewer_reply((0, [view(0, 2), view(1, 1), view(2, 2)], ["0", "1", "2", "face"])))
        assert (moments, reserves) == ([], [])
        assert broll.FILTERS["ideas: no idea above the face alone"] == 1
        assert broll_ideas.LAST_IDEAS[0]["chosen"] is None

    def test_an_idea_the_viewer_did_not_score_is_not_held_against_it(self, monkeypatch):
        _j, (moments, _r) = run_round(
            monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST), dict(DINER)])),
            verifier=verifier_reply((0, [verdict(0), verdict(1)])),
            viewer=viewer_reply((0, [view(0, 4)], ["0", "1", "face"])))              # no view for the idea "1"
        assert moments[0]["spec"]["subject"] == CAST["subject"] and moments[0]["spec"]["alt"]["subject"] == DINER["subject"]

    def test_an_order_given_in_numbers_is_read_like_one_in_strings(self, monkeypatch):
        _j, (moments, _r) = run_round(monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST), dict(DINER)])),
                                      viewer=viewer_reply((0, [view(0), view(1)], [1, "face", 0])))
        assert moments[0]["spec"]["subject"] == DINER["subject"] and "alt" not in moments[0]["spec"]

    def test_the_viewers_marks_are_kept_for_the_board(self, monkeypatch):
        _j, _out = run_round(
            monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST), dict(DINER)])),
            verifier=verifier_reply((0, [verdict(0), verdict(1, flaw="stock")])),
            viewer=viewer_reply((0, [view(0, 4, stops="yes", feels="relief", link="yes", adds="weeks like a bone"),
                                     view(1, 2, stops="maybe", flaw="stock", unease="a stock photo")],
                                ["0", "face", "1"])))
        a, b = broll_ideas.LAST_IDEAS[0]["ideas"]
        assert (a["score"], a["stops"], a["link"], a["feels"], a["viewer_adds"]) == (4, "yes", "yes", "relief",
                                                                                       "weeks like a bone")
        assert (b["score"], b["unease"], b["flaw"], b["above_face"]) == (2, "a stock photo", "stock", False)


class TestTheVerifiersFlaws:
    """An idea the verifier flags as the setting instead of the idea, an object placed or a stock photo counts as under
    the face alone unless the viewer scored it 5 (the judges of the text were kinder to a therapy room than the viewer
    of the picture). The verifier's flaw only: the viewer's own flaw is information for the board."""

    def _round(self, monkeypatch, flaw, score, other=3, viewers_flaw="none"):
        """Two ideas, ranked "0" then "1" above the face; the first one flagged ``flaw`` by the verifier and scored
        ``score`` by the viewer. -> the moments of the round."""
        return run_round(
            monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST), dict(DINER)])),
            verifier=verifier_reply((0, [verdict(0, flaw=flaw), verdict(1)])),
            viewer=viewer_reply((0, [view(0, score, flaw=viewers_flaw), view(1, other)], ["0", "1", "face"])))[1][0]

    @pytest.mark.parametrize("flaw", ["setting", "object", "stock"])
    def test_a_weak_flaw_puts_the_idea_under_the_face(self, monkeypatch, flaw):
        assert broll_ideas.FLAW_SCORE == 5 and flaw in broll_ideas._WEAK_FLAWS
        # the viewer ranked the flagged idea first and scored it 4 (well above MIN_SCORE, but not 5): the code does not follow
        moments = self._round(monkeypatch, flaw, 4)
        spec = moments[0]["spec"]
        assert spec["subject"] == DINER["subject"] and "alt" not in spec          # the flagged idea is no alternative either
        record = broll_ideas.LAST_IDEAS[0]
        assert record["chosen"] == 1 and [i["above_face"] for i in record["ideas"]] == [False, True]
        assert [(i["flaw"], i["score"]) for i in record["ideas"]] == [(flaw, 4), ("none", 3)]

    @pytest.mark.parametrize("flaw", ["setting", "object", "stock"])
    def test_unless_the_viewer_gave_it_five(self, monkeypatch, flaw):
        spec = self._round(monkeypatch, flaw, 5)[0]["spec"]
        assert spec["subject"] == CAST["subject"] and spec["alt"]["subject"] == DINER["subject"]
        assert [i["above_face"] for i in broll_ideas.LAST_IDEAS[0]["ideas"]] == [True, True]

    @pytest.mark.parametrize("flaw", ["none", "figure", "symbol"])
    def test_the_other_flaws_are_no_reason(self, monkeypatch, flaw):
        spec = self._round(monkeypatch, flaw, 4)[0]["spec"]
        assert spec["subject"] == CAST["subject"] and spec["alt"]["subject"] == DINER["subject"]
        assert broll_ideas.LAST_IDEAS[0]["ideas"][0]["flaw"] == flaw

    def test_a_flagged_idea_alone_is_no_picture(self, monkeypatch):
        _j, (moments, reserves) = run_round(
            monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST)])),
            verifier=verifier_reply((0, [verdict(0, flaw="object")])),
            viewer=viewer_reply((0, [view(0, 4)], ["0", "face"])))
        assert (moments, reserves) == ([], [])
        assert broll.FILTERS["ideas: no idea above the face alone"] == 1 and NO_HERO not in broll.FILTERS
        assert broll_ideas.LAST_IDEAS[0]["chosen"] is None and broll_ideas.LAST_IDEAS[0]["ideas"][0]["flaw"] == "object"

    def test_only_the_verifiers_flaw_counts_not_the_viewers(self, monkeypatch):
        spec = self._round(monkeypatch, "none", 4, viewers_flaw="stock")[0]["spec"]
        assert spec["subject"] == CAST["subject"]
        assert broll_ideas.LAST_IDEAS[0]["ideas"][0]["flaw"] == "none"             # the board shows the verifier's

    def test_the_flaws_are_those_of_each_moment(self, monkeypatch):
        # the verifier flags the first idea of the first moment only: the second moment is untouched
        _j, (moments, _r) = run_round(
            monkeypatch, [moment(), moment(10.8, anchor="two sessions")],
            da=da_reply(da(0, [dict(CAST), dict(DINER)]), da(1, [dict(CAST), dict(DINER)])),
            verifier=verifier_reply((0, [verdict(0, flaw="stock"), verdict(1)]), (1, [verdict(0), verdict(1)])),
            viewer=viewer_reply((0, [view(0, 4), view(1, 3)], ["0", "1", "face"]),
                                (1, [view(0, 4), view(1, 3)], ["0", "1", "face"])))
        assert [m["spec"]["subject"] for m in moments] == [DINER["subject"], CAST["subject"]]


class TestTheHero:
    """The one moment shown full screen is chosen AFTER the round, among the ideas kept: the director says the idea can
    fill the screen (hero_ok), the viewer gave it HERO_MIN (4) or more, broll.hero_fits passes (the clip's timing
    rules) and the moment is no notion's picture. The viewer's score decides, +1 when the editor had marked the moment,
    +0.5 after 35 % of the clip. Every other moment is a card, a reserve is never the hero, none: "ideas: no hero"."""

    def test_an_idea_that_can_fill_the_screen_and_scored_four_is_the_hero(self, monkeypatch):
        assert broll_ideas.HERO_MIN == 4
        moments, _r = hero_round(monkeypatch, [moment()], [DINER_HERO], [4])          # the editor marked nothing
        assert moments[0]["hero"] is True and moments[0]["spec"]["hero_ok"] is True
        assert NO_HERO not in broll.FILTERS

    @pytest.mark.parametrize("hero_ok", [None, False])
    def test_the_editors_mark_is_no_longer_enough(self, monkeypatch, capsys, hero_ok):
        idea = dict(DINER) if hero_ok is None else dict(DINER, hero_ok=hero_ok)
        moments, _r = hero_round(monkeypatch, [moment(hero=True)], [idea], [5])
        assert len(moments) == 1 and moments[0]["hero"] is False                  # a card, whatever the editor marked
        assert broll.FILTERS[NO_HERO] == 1 and "No idea kept can fill the whole screen" in capsys.readouterr().out
        assert broll_ideas.LAST_IDEAS[0]["hero"] is True                          # the record keeps the editor's mark

    def test_the_viewer_must_give_four_or_more(self, monkeypatch):
        moments, _r = hero_round(monkeypatch, [moment()], [DINER_HERO], [3])         # 3: above the face, no hero
        assert len(moments) == 1 and moments[0]["hero"] is False and broll.FILTERS[NO_HERO] == 1
        broll.FILTERS.clear()
        moments, _r = hero_round(monkeypatch, [moment()], [DINER_HERO], [5])
        assert moments[0]["hero"] is True and NO_HERO not in broll.FILTERS

    def test_a_viewer_with_no_answer_makes_no_hero(self, monkeypatch):
        _j, (moments, _r) = run_round(monkeypatch, [moment(hero=True)], da=da_reply(da(0, [dict(DINER_HERO)])))
        assert len(moments) == 1 and moments[0]["hero"] is False and broll.FILTERS[NO_HERO] == 1
        assert moments[0]["viewer_score"] is None

    @pytest.mark.parametrize("marks,scores,hero", [
        ((False, False), (4, 5), 1),       # 4 against 5
        ((False, False), (5, 4), 0),       # 5 against 4
        ((True, False), (4, 4), 0),        # the editor's mark is worth 1: 5 against 4
        ((False, True), (4, 4), 1)])       # whichever moment it marked
    def test_the_viewers_score_decides_and_the_editors_mark_is_a_bonus(self, monkeypatch, marks, scores, hero):
        ms = [moment(5.4, hero=marks[0]), moment(6.3, anchor="their", hero=marks[1])]   # both in the first third
        moments, _r = hero_round(monkeypatch, ms, [DINER_HERO, DINER_HERO], list(scores))
        assert [m["hero"] for m in moments] == [i == hero for i in range(2)]        # one hero, the other a card
        assert NO_HERO not in broll.FILTERS

    @pytest.mark.parametrize("mark,hero", [(False, 1), (True, 0)])
    def test_the_second_part_of_the_clip_is_a_half_point_bonus(self, monkeypatch, mark, hero):
        # 22 s: after 7.7 s is the payoff. 4 + 0.5 against 4 (the later one wins) or against 4 + 1 (the marked one)
        ms = [moment(5.4, hero=mark), moment(10.8, anchor="two sessions")]
        moments, _r = hero_round(monkeypatch, ms, [DINER_HERO, DINER_HERO], [4, 4])
        assert [m["hero"] for m in moments] == [i == hero for i in range(2)]

    def test_only_ideas_that_can_fill_the_screen_compete(self, monkeypatch):
        ms = [moment(), moment(10.8, anchor="two sessions"), moment(15.3, anchor="alarm is gone")]
        moments, _r = hero_round(monkeypatch, ms, [DINER_HERO, DINER, DINER_HERO], [4, 5, 4])
        assert [m["hero"] for m in moments] == [False, False, True]                # the 5 of the second is no hero_ok
        assert [m["viewer_score"] for m in moments] == [4, 5, 4]

    def test_a_notion_is_never_the_hero(self, monkeypatch):
        notion = moment()
        notion["notion"] = "Default mode network"                                  # its picture is the notion's usual one
        moments, _r = hero_round(monkeypatch, [notion, moment(10.8, anchor="two sessions")],
                                 [DINER_HERO, DINER_HERO], [5, 4])
        assert [m["hero"] for m in moments] == [False, True] and moments[0]["notion"] == "Default mode network"

    def test_a_reserve_is_never_the_hero(self, monkeypatch):
        reserve = moment(15.3, anchor="alarm is gone", hero=True)
        moments, reserves = hero_round(monkeypatch, [moment()], [CAST, DINER_HERO], [4, 5], reserves=[reserve])
        assert [m["hero"] for m in moments] == [False] and [m["hero"] for m in reserves] == [False]
        assert broll.FILTERS[NO_HERO] == 1                                         # the moments had none to offer

    def test_no_moment_left_is_no_hero_hit(self, monkeypatch):
        _j, (moments, reserves) = run_round(
            monkeypatch, [moment()], [moment(15.3, anchor="alarm is gone")],
            da=da_reply(da(0, []), da(1, [dict(DINER_HERO)])), verifier=verifier_reply((1, [verdict(0)])),
            viewer=viewer_reply((1, [view(0, 5)], ["0", "face"])))
        assert moments == [] and len(reserves) == 1 and reserves[0]["hero"] is False
        assert NO_HERO not in broll.FILTERS

    @pytest.mark.parametrize("timing,fits", [
        ({}, True),
        ({"avoid": [5.0]}, False),               # the hero (5.4 to 8.25 s) would run into the punchline at 5.0 s
        ({"avoid": [15.0]}, True),
        ({"head": 6.0}, False),                  # the hook's seconds stay on the speaker
        ({"head": 5.0}, True),
        ({"block": ((6.0, 9.0),)}, False),       # the source's own picture is on screen
        ({"block": ((9.0, 12.0),)}, True)])
    def test_the_clips_timing_rules_say_who_may_be_the_hero(self, monkeypatch, timing, fits):
        moments, _r = hero_round(monkeypatch, [moment()], [DINER_HERO], [5], **timing)
        assert len(moments) == 1 and moments[0]["hero"] is fits
        assert broll.FILTERS[NO_HERO] == (0 if fits else 1)

    def test_the_last_seconds_of_the_clip_stay_on_the_face(self, monkeypatch):
        late = moment(18.9, anchor="year")                                         # 18.9 + 2.85 s > 22 - 2 s
        moments, _r = hero_round(monkeypatch, [late], [DINER_HERO], [5])
        assert moments[0]["hero"] is False and broll.FILTERS[NO_HERO] == 1

    def test_the_timing_rules_that_do_not_fit_hand_the_hero_to_the_next_idea(self, monkeypatch):
        ms = [moment(), moment(10.8, anchor="two sessions")]
        moments, _r = hero_round(monkeypatch, ms, [DINER_HERO, DINER_HERO], [5, 4], avoid=[5.0])
        assert [m["hero"] for m in moments] == [False, True] and NO_HERO not in broll.FILTERS

    def test_hero_fits_is_asked_with_the_clips_duration_and_timing_rules(self, monkeypatch):
        asked = []

        def fits(m, duration, avoid, head, block):
            asked.append((m["anchor"], duration, avoid, head, block))
            return True
        monkeypatch.setattr(broll, "hero_fits", fits)
        avoid, block = [3.0], ((12.0, 13.0),)
        ms = [moment(), moment(10.8, anchor="two sessions")]
        hero_round(monkeypatch, ms, [DINER_HERO, DINER_HERO], [4, 4], avoid=avoid, head=2.5, block=block)
        assert asked == [("move through", 22.0, avoid, 2.5, block), ("two sessions", 22.0, avoid, 2.5, block)]
        assert asked[0][2] is avoid and asked[0][4] is block                       # the very objects the caller gave
        del asked[:]
        hero_round(monkeypatch, ms, [DINER_HERO, DINER_HERO], [4, 4])              # without them: no rule at all
        assert [a[1:] for a in asked] == [(22.0, (), 0.0, ())] * 2

    def test_the_round_takes_the_timing_rules_as_keywords(self):
        params = inspect.signature(broll_ideas.idea_round).parameters
        assert list(params) == ["moments", "reserves", "clip", "words", "gravity", "clip_text", "avoid", "head", "block"]
        assert [params[k].default for k in ("avoid", "head", "block")] == [(), 0.0, ()]

    def test_the_hero_flag_follows_the_round_not_the_input(self, monkeypatch):
        first, second = moment(hero=True), moment(10.8, anchor="two sessions")
        moments, _r = hero_round(monkeypatch, [first, second], [CAST, DINER_HERO], [5, 4])
        assert [m["hero"] for m in moments] == [False, True]
        assert first["hero"] is True and second["hero"] is False                   # the editor's own moments are untouched


class TestTheDirector:
    def test_an_empty_list_is_no_picture_and_nothing_goes_to_the_judges(self, monkeypatch):
        why = "the sentence shows nothing a camera could film"
        judges, (moments, reserves) = run_round(monkeypatch, [moment()], da=da_reply(da(0, [], why=why)))
        assert (moments, reserves) == ([], []) and judges.judges() == ["da"]
        assert broll.FILTERS["ideas: no picture (the director)"] == 1
        assert "ideas: no idea above the face alone" not in broll.FILTERS
        record = broll_ideas.LAST_IDEAS[0]
        assert record["chosen"] is None and record["why"] == why and record["ideas"] == []

    def test_a_moment_the_director_left_out_has_no_picture_either(self, monkeypatch):
        _j, (moments, _r) = run_round(
            monkeypatch, [moment(), moment(10.8, anchor="two sessions")], da=da_reply(da(1, [dict(CAST)])),
            verifier=verifier_reply((1, [verdict(0)])), viewer=viewer_reply((1, [view(0)], ["0", "face"])))
        assert [m["anchor"] for m in moments] == ["two sessions"]
        assert broll.FILTERS["ideas: no idea above the face alone"] == 1
        assert [r["chosen"] for r in broll_ideas.LAST_IDEAS] == [None, 0]

    def test_at_most_three_ideas_are_kept_and_an_unknown_role_is_the_point(self, monkeypatch):
        ideas = [dict(CAST), dict(DINER), dict(SCAR), dict(CAST, title="a fourth"), dict(CAST, title="a fifth")]
        judges, _out = run_round(monkeypatch, [moment()], da=da_reply(da(0, ["junk", *ideas], role="weird")))
        assert [i["title"] for i in broll_ideas.LAST_IDEAS[0]["ideas"]] == [CAST["title"], DINER["title"], SCAR["title"]]
        assert broll_ideas.LAST_IDEAS[0]["role"] == "point"

    def test_an_idea_without_its_render_fields_keeps_the_editors(self, monkeypatch):
        bare = {"title": "Bare", "picture": "A forearm on a table.", "adds": "", "reads": "", "subject": "a bare forearm",
                "light": "daylight from a window"}
        _j, (moments, _r) = run_round(monkeypatch, [moment(shot="wide", setting="a clinic")],
                                      da=da_reply(da(0, [bare])))
        spec = moments[0]["spec"]
        assert spec["subject"] == "a bare forearm" and spec["shot"] == "wide" and spec["setting"] == "a clinic"
        assert spec["kind"] == "scene" and spec["light"] == "daylight from a window"

    def test_the_roles_and_the_ideas_of_the_round_replace_the_editors_in_the_moment(self, monkeypatch):
        _j, (moments, _r) = run_round(monkeypatch, [moment(role="point")],
                                      da=da_reply(da(0, [dict(CAST)], idea="what the director read", role="vehicle")))
        assert moments[0]["role"] == "vehicle" and moments[0]["idea_text"] == "what the director read"
        assert moments[0]["spec"]["role"] == "point"                              # the spec keeps the editor's own


class TestTheAnchor:
    def _chosen(self, monkeypatch, anchor, **kw):
        ms = [moment(**kw)]
        _j, (moments, _r) = run_round(monkeypatch, ms, da=da_reply(da(0, [dict(CAST, anchor=anchor)])))
        return ms[0], moments[0]

    def test_an_anchor_of_spoken_words_moves_the_moment(self, monkeypatch):
        before, after = self._chosen(monkeypatch, "PTSD")
        assert after["anchor"] == "PTSD" and after["t"] == at("PTSD") and before["t"] == 5.4   # the input is left alone
        # the words of the next sentence, within 8 s
        _b, after = self._chosen(monkeypatch, "two sessions")
        assert after["anchor"] == "two sessions" and after["t"] == at("two")
        assert after["spec"]["subject"] == CAST["subject"]

    def test_an_anchor_not_spoken_or_too_far_leaves_the_moment_where_it_is(self, monkeypatch):
        for anchor in ("banana smoothie", "alarm is gone", ""):                    # unspoken / 9.9 s away / none
            _b, after = self._chosen(monkeypatch, anchor)
            assert after["anchor"] == "move through" and after["t"] == 5.4, anchor

    def test_an_anchor_not_said_in_a_row_lands_on_one_of_its_spoken_words(self, monkeypatch):
        _b, after = self._chosen(monkeypatch, "weeks and days")
        assert after["anchor"] == "weeks" and after["t"] == at("weeks")


class TestReserves:
    def test_a_reserve_is_judged_with_the_moments_and_stays_a_reserve(self, monkeypatch):
        moments = [moment(5.4), moment(10.8, anchor="two sessions")]
        reserves = [moment(15.3, anchor="alarm is gone"), moment(18.9, anchor="year")]
        judges, (out_moments, out_reserves) = run_round(
            monkeypatch, moments, reserves,
            da=da_reply(da(0, [dict(CAST)]), da(1, [dict(SCAR)]), da(2, [dict(DINER)]), da(3, [dict(CAST)])),
            verifier=verifier_reply((0, [verdict(0)]), (1, [verdict(0)]), (2, [verdict(0)]), (3, [verdict(0)])),
            viewer=viewer_reply((0, [view(0)], ["0", "face"]), (1, [view(0)], ["face", "0"]),
                                (2, [view(0)], ["0", "face"]), (3, [view(0)], ["face", "0"])))
        assert judges.judges() == ["da", "verifier", "viewer"]                     # one call each, reserves included
        assert "MOMENT k=2" in judges.prompt("da") and "MOMENT k=3" in judges.prompt("da")
        assert [m["spec"]["subject"] for m in out_moments] == [CAST["subject"]]
        assert [m["spec"]["subject"] for m in out_reserves] == [DINER["subject"]]
        assert out_reserves[0]["anchor"] == "alarm is gone" and "alt" not in out_reserves[0]["spec"]
        records = broll_ideas.LAST_IDEAS
        assert [r["k"] for r in records] == [0, 1, 2, 3]
        assert [r["reserve"] for r in records] == [False, False, True, True]
        assert [r["chosen"] for r in records] == [0, None, 0, None]
        assert broll.FILTERS["ideas: no idea above the face alone"] == 2

    def test_a_reserve_may_survive_its_moments(self, monkeypatch):
        _j, (out_moments, out_reserves) = run_round(
            monkeypatch, [moment()], [moment(15.3, anchor="alarm is gone")],
            da=da_reply(da(0, []), da(1, [dict(DINER)])),
            verifier=verifier_reply((1, [verdict(0)])), viewer=viewer_reply((1, [view(0)], ["0", "face"])))
        assert out_moments == [] and [m["spec"]["subject"] for m in out_reserves] == [DINER["subject"]]

    def test_the_round_leaves_the_editors_moments_as_they_were(self, monkeypatch):
        first, spare = moment(), moment(15.3, anchor="alarm is gone")
        before = (repr(first), repr(spare))
        run_round(monkeypatch, [first], [spare], da=da_reply(da(0, [dict(CAST)]), da(1, [dict(DINER)])),
                  verifier=verifier_reply((0, [verdict(0)]), (1, [verdict(0)])),
                  viewer=viewer_reply((0, [view(0)], ["0", "face"]), (1, [view(0)], ["0", "face"])))
        assert (repr(first), repr(spare)) == before and first["spec"]["subject"] == "therapy room"


class TestLastIdeas:
    def test_one_record_per_moment_with_the_chosen_idea(self, monkeypatch):
        ms = [moment(hero=True), moment(10.8, anchor="two sessions")]
        _j, _out = run_round(
            monkeypatch, ms, [moment(15.3, anchor="alarm is gone")],
            da=da_reply(da(0, [dict(CAST), dict(DINER)], idea="the first"), da(1, [dict(SCAR)], idea="the second", role="point"),
                        da(2, [dict(SCAR)], idea="the third")),
            verifier=verifier_reply((0, [verdict(0), verdict(1, "refuse", "a stock photo", flaw="stock")]),
                                    (1, [verdict(0)]), (2, [verdict(0)])),
            viewer=viewer_reply((0, [view(0, 5)], ["0", "face"]), (1, [view(0, 4)], ["face", "0"]),
                                (2, [view(0, 4)], ["0", "face"])))
        records = broll_ideas.LAST_IDEAS
        assert [r["k"] for r in records] == [0, 1, 2] and [r["chosen"] for r in records] == [0, None, 0]
        assert [r["reserve"] for r in records] == [False, False, True]
        assert [r["idea"] for r in records] == ["the first", "the second", "the third"]
        assert [r["role"] for r in records] == ["vehicle", "point", "vehicle"]
        assert [r["hero"] for r in records] == [True, False, False]
        assert all(set(r) == {"k", "anchor", "t", "said", "idea", "role", "why", "hero", "reserve", "ideas", "chosen"}
                   for r in records)
        assert records[0]["anchor"] == "move through" and records[0]["said"] == SENTENCES[1]
        first = records[0]["ideas"]
        assert set(first[0]) == {"i", "title", "picture", "adds", "verdict", "reason", "flaw", "score", "stops", "link",
                                 "feels", "viewer_adds", "unease", "above_face"}
        assert [(i["title"], i["verdict"], i["flaw"]) for i in first] == [
            (CAST["title"], "pass", "none"), (DINER["title"], "refuse", "stock")]
        assert [i["above_face"] for i in first] == [True, False]

    def test_each_round_starts_a_new_record(self, monkeypatch):
        for _ in range(2):
            run_round(monkeypatch, [moment()], da=da_reply(da(0, [dict(CAST)])),
                      verifier=verifier_reply((0, [verdict(0)])), viewer=viewer_reply((0, [view(0)], ["0", "face"])))
        assert len(broll_ideas.LAST_IDEAS) == 1

    def test_nothing_to_judge_calls_nothing(self, monkeypatch):
        judges = Judges()
        monkeypatch.setattr(broll, "claude_json", judges)
        moments, reserves = [], []
        got = broll_ideas.idea_round(moments, reserves, CLIP, WORDS, "none", CLIP_TEXT)
        assert got[0] is moments and got[1] is reserves and judges.calls == [] and broll_ideas.LAST_IDEAS == []


# ====================================================================================================================
# the helpers, the schemas, the whole thing
# ====================================================================================================================
class TestHelpers:
    def test_above_face(self):
        above = broll_ideas._above_face
        assert above(["0", "face", "1"], ["0", "1"]) == ["0"]
        assert above(["1", "0", "face", "2"], ["0", "1", "2"]) == ["1", "0"]
        assert above(["face", "0", "1"], ["0", "1"]) == []
        assert above(["1", "0", "1", "face"], ["0", "1"]) == ["1", "0"]               # once each
        assert above(["2", "0", "face"], ["0", "1"]) == ["0"]                         # an id that is not live is no idea
        assert above(["1", "0"], ["0", "1"]) == ["1", "0"]                            # no face listed: all those listed
        assert above(["0"], ["0", "1"]) == ["0"] and above([], ["0"]) == []

    def test_an_idea_scored_under_the_minimum_counts_as_under_the_face(self):
        above = broll_ideas._above_face
        views = {0: {"score": 2}, 1: {"score": 3}, 2: {"score": 5}}
        assert above(["0", "1", "2", "face"], ["0", "1", "2"], views) == ["1", "2"]
        assert above(["2", "0", "1"], ["0", "1", "2"], views) == ["2", "1"]            # no face listed: the same rule
        assert above(["0"], ["0"], {0: {"score": broll_ideas.MIN_SCORE - 1}}) == []
        # an idea the viewer did not score (no view, no score) is not held against it
        assert above(["0", "1"], ["0", "1"], {0: {"score": 4}}) == ["0", "1"]
        assert above(["0", "1"], ["0", "1"], {0: {"score": 0}, 1: {}}) == ["0", "1"]
        assert above(["0"], ["0"], None) == ["0"] and above(["0"], ["0"], {}) == ["0"]

    def test_an_idea_flagged_as_weak_by_the_verifier_counts_as_under_the_face_unless_scored_five(self):
        above = broll_ideas._above_face
        assert broll_ideas.FLAW_SCORE == 5 and broll_ideas._WEAK_FLAWS == ("setting", "object", "stock")
        views = {0: {"score": 4}, 1: {"score": 5}, 2: {"score": 3}}
        order, ids = ["0", "1", "2", "face"], ["0", "1", "2"]
        assert above(order, ids, views) == above(order, ids, views, None) == above(order, ids, views, {}) == ["0", "1", "2"]
        for flaw in ("setting", "object", "stock"):
            # the flaw is held against a 4 and a 3, never against a 5 (the flaws are keyed by the idea's number)
            assert above(order, ids, views, {0: flaw, 1: flaw, 2: flaw}) == ["1"], flaw
            assert above(order, ids, views, {0: flaw}) == ["1", "2"], flaw
            assert above(["1", "0", "face"], ["0", "1"], views, {1: flaw}) == ["1", "0"], flaw
            assert above(["0", "face"], ["0"], {0: {"score": broll_ideas.FLAW_SCORE - 1}}, {0: flaw}) == [], flaw
            assert above(["0", "face"], ["0"], {0: {"score": broll_ideas.FLAW_SCORE}}, {0: flaw}) == ["0"], flaw
        for flaw in ("none", "figure", "symbol", None):                         # the others are no reason
            assert above(order, ids, views, {0: flaw, 1: flaw, 2: flaw}) == ["0", "1", "2"], flaw
        # the minimum still applies on its own, and an idea nobody scored has no 5 to its name
        assert above(["0", "1", "face"], ["0", "1"], {0: {"score": 2}, 1: {"score": 4}}, {1: "figure"}) == ["1"]
        assert above(["0", "face"], ["0"], None, {0: "object"}) == [] and above(["0", "face"], ["0"], {}, {0: "stock"}) == []

    def test_sentences_end_on_a_stop_or_after_seven_seconds(self):
        assert [text for _a, _b, text in broll_ideas._sentences(WORDS)] == list(SENTENCES)
        assert broll_ideas._sentences([]) == []
        run_on = _words(("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                         "sixteen seventeen eighteen",))
        parts = broll_ideas._sentences(run_on)
        assert len(parts) == 2 and parts[0][2].endswith("sixteen") and parts[1][2] == "seventeen eighteen"
        assert parts[1][1] == run_on[-1]["end"]

    def test_around_gives_the_sentence_the_one_before_and_the_one_after(self):
        assert broll_ideas._around(WORDS, at("move")) == (SENTENCES[1], SENTENCES[0], SENTENCES[2])
        assert broll_ideas._around(WORDS, 0.5) == (SENTENCES[0], "", SENTENCES[1])
        assert broll_ideas._around(WORDS, at("year")) == (SENTENCES[3], SENTENCES[2], "")
        assert broll_ideas._around([], 3.0) == ("", "", "")

    def test_q_makes_a_text_fit_a_prompt_line(self):
        assert broll_ideas._q('  a "quoted"\n   line ', 5) == "a 'quoted' line"
        assert broll_ideas._q("x" * 500, 3) == "x" * 21 and broll_ideas._q(None) == ""

    def test_a_model_other_than_sonnet_that_fails_is_tried_again_on_sonnet(self, monkeypatch):
        calls = []

        def fake(prompt, schema, **kw):
            calls.append(kw["model"])
            if kw["model"] != "sonnet":
                raise RuntimeError("timeout")
            return {"moments": [{"k": 0}]}
        monkeypatch.setattr(broll, "claude_json", fake)
        out = broll_ideas._call("prompt", broll_ideas.DA_SCHEMA, "broll_ideas", "opus", effort="high")
        assert out == {"moments": [{"k": 0}]} and calls == ["opus", "sonnet"]

    def test_a_sonnet_that_fails_is_not_tried_again_and_nothing_answered_is_empty(self, monkeypatch):
        calls = []

        def fail(prompt, schema, **kw):
            calls.append(kw["model"])
            raise RuntimeError("quota")
        monkeypatch.setattr(broll, "claude_json", fail)
        with pytest.raises(RuntimeError):
            broll_ideas._call("prompt", broll_ideas.VIEWER_SCHEMA, "broll_viewer", "sonnet")
        assert calls == ["sonnet"]
        monkeypatch.setattr(broll, "claude_json", lambda *a, **k: None)
        assert broll_ideas._call("prompt", broll_ideas.VIEWER_SCHEMA, "broll_viewer", "sonnet") == {}


def candidate(t=5.4, ok=True, score=4, mark=False, notion=""):
    """(moment, spec, viewer's score) of one idea kept, as _pick_hero reads it. ``ok``: the spec's hero_ok."""
    return {"t": t, "dur": 2.5, "hero": mark, "notion": notion}, {"hero_ok": ok}, score


def pick(*candidates, words=WORDS, avoid=(), head=0.0, block=()):
    """broll_ideas._pick_hero over ``candidates`` (an index of them, or None)."""
    return broll_ideas._pick_hero([c[0] for c in candidates], lambda i: (candidates[i][1], candidates[i][2]), words,
                                  avoid, head, block)


class TestPickHero:
    """The hero among the ideas kept, on its own (the clip is 22 s: its payoff half starts at 7.7 s; a hero of 2.5 s
    of sentence stays 2.85 s on screen)."""

    def test_nothing_that_qualifies_is_no_hero(self):
        assert pick() is None
        assert pick(candidate(ok=False, score=5)) is None                        # the director did not say it could
        assert pick(candidate(ok=None, score=5)) is None
        assert pick(candidate(score=3)) is None and pick(candidate(score=0)) is None   # the viewer gave less than 4
        assert pick(candidate(score=5, notion="Default mode network")) is None      # the usual picture of a notion
        m = candidate()[0]
        assert broll_ideas._pick_hero([m], lambda i: (None, 5), WORDS, (), 0.0, ()) is None     # no spec
        assert broll_ideas._pick_hero([m], lambda i: ({"kind": "scene"}, 5), WORDS, (), 0.0, ()) is None   # no hero_ok

    def test_four_is_enough_and_the_answer_is_the_index_among_the_moments_given(self):
        assert broll_ideas.HERO_MIN == 4
        assert pick(candidate(score=4)) == 0 and pick(candidate(score=5)) == 0
        assert pick(candidate(ok=False), candidate(10.8, score=4), candidate(15.3, ok=False)) == 1
        assert pick(candidate(score=3), candidate(10.8, score=3), candidate(15.3, score=4)) == 2

    def test_the_viewers_score_decides_the_editors_mark_and_the_payoff_are_bonuses(self):
        early, other = 5.4, 6.3                                                   # both before 7.7 s: no payoff bonus
        assert pick(candidate(early, score=4), candidate(other, score=5)) == 1       # 4 against 5
        assert pick(candidate(early, score=5), candidate(other, score=4)) == 0       # 5 against 4
        assert pick(candidate(early, score=4), candidate(other, score=4, mark=True)) == 1     # 4 against 4 + 1
        assert pick(candidate(early, score=4, mark=True), candidate(other, score=4)) == 0     # 4 + 1 against 4
        assert pick(candidate(early, score=4), candidate(10.8, score=4)) == 1        # 4 against 4 + 0.5 (after 35 %)
        assert pick(candidate(early, score=4, mark=True), candidate(10.8, score=4)) == 0      # 5 against 4.5
        assert pick(candidate(early, score=5), candidate(10.8, score=4, mark=True)) == 1      # 5 against 5.5: they add up
        assert pick(candidate(early, score=5), candidate(10.8, score=4)) == 0        # 5 against 4.5
        assert pick(candidate(early, score=4, mark=True), candidate(10.8, score=5)) == 1      # 5 against 5.5
        assert pick(candidate(early, score=4), candidate(other, score=4)) == 0       # a tie keeps the first

    def test_the_payoff_is_a_share_of_the_clips_own_length(self):
        long_clip = [{"text": "x", "start": 0.0, "end": 40.0}]                   # 35 % of it: 14 s
        a, b = candidate(10.8, score=4), candidate(15.3, score=4)
        assert pick(a, b, words=WORDS) == 0                                       # both after 7.7 s: the same bonus
        assert pick(a, b, words=long_clip) == 1                                   # only the second after 14 s

    def test_the_timing_rules_of_the_clip_apply_to_every_candidate(self):
        a, b = candidate(5.4, score=5), candidate(10.8, score=4)
        assert pick(a, b) == 0
        assert pick(a, b, avoid=[5.0]) == 1                                       # the first runs into the punchline
        assert pick(a, b, head=6.0) == 1                                          # ... or into the hook's seconds
        assert pick(a, b, block=((6.0, 9.0),)) == 1                               # ... or into the source's own picture
        assert pick(a, b, avoid=[5.0], head=6.0, block=((9.0, 14.0),)) is None    # and the second one runs into the block
        assert pick(candidate(18.9, score=5)) is None                             # the last 2 s stay on the face
        assert pick(a, b, words=[]) is None                                       # no words: no length, no hero

    def test_hero_fits_gets_the_moment_the_duration_and_the_rules_as_given(self, monkeypatch):
        asked = []
        monkeypatch.setattr(broll, "hero_fits", lambda *args: asked.append(args) or True)
        c = candidate()
        avoid, block = [3.0], ((12.0, 13.0),)
        assert pick(c, avoid=avoid, head=2.5, block=block) == 0
        assert asked == [(c[0], 22.0, avoid, 2.5, block)] and asked[0][0] is c[0]
        monkeypatch.setattr(broll, "hero_fits", lambda *args: False)
        assert pick(c) is None                                                    # whatever the rest says


class TestSchemas:
    def test_the_art_directors_schema(self):
        item = broll_ideas.DA_SCHEMA["properties"]["moments"]["items"]
        assert item["required"] == ["k", "idea", "role", "ideas"]
        assert item["properties"]["role"]["enum"] == ["point", "vehicle"] == list(broll_spec.ROLES) == list(broll_ideas.ROLES)
        idea = item["properties"]["ideas"]["items"]
        props = idea["properties"]
        assert props["person"]["enum"] == ["none", "anonymous"]                   # a real person cannot pass the schema
        assert props["kind"]["enum"] == list(broll_spec.KINDS) and props["count"]["enum"] == list(broll_spec.COUNTS)
        assert props["people"]["enum"] == list(broll_spec.PEOPLE) and props["shot"]["enum"] == list(broll_spec.SHOTS)
        assert set(idea["required"]) == {"title", "picture", "adds", "reads", "kind", "subject", "count", "state",
                                         "setting", "details", "people", "person", "shot", "light"}
        optional = {"anchor", "subject_b", "instrument", "hero_ok"}
        assert optional <= set(props) and not optional & set(idea["required"])
        assert props["hero_ok"] == {"type": "boolean"}                            # can this idea fill the whole screen
        assert "hero_ok" not in broll_ideas._IDEA_FIELDS                          # not a render field: the spec carries it
        assert set(broll_ideas._IDEA_FIELDS) <= set(props) and "light" in broll_ideas._IDEA_FIELDS
        assert broll_ideas.IDEAS_PER_MOMENT == 3 and set(broll_ideas.DA_SCHEMA["required"]) == {"moments"}

    def test_the_verifiers_schema(self):
        item = broll_ideas.VERIFIER_SCHEMA["properties"]["moments"]["items"]
        verdict_ = item["properties"]["ideas"]["items"]
        assert item["required"] == ["k", "ideas"] and verdict_["required"] == ["i", "verdict", "reason", "flaw"]
        assert verdict_["properties"]["verdict"]["enum"] == ["pass", "fix", "refuse"] == list(broll_ideas.VERDICTS)
        assert verdict_["properties"]["flaw"]["enum"] == ["none", "setting", "object", "figure", "symbol", "stock"]
        assert "details" in verdict_["properties"] and "details" not in verdict_["required"]

    def test_the_viewers_schema(self):
        item = broll_ideas.VIEWER_SCHEMA["properties"]["moments"]["items"]
        view_ = item["properties"]["views"]["items"]
        assert item["required"] == ["k", "views", "order"] and item["properties"]["order"]["items"] == {"type": "string"}
        assert view_["required"] == ["i", "stops", "feels", "link", "adds", "score", "flaw"]
        assert view_["properties"]["stops"]["enum"] == ["yes", "maybe", "no"]
        assert view_["properties"]["link"]["enum"] == ["yes", "blurry", "no"]
        assert view_["properties"]["score"] == {"type": "integer", "minimum": 1, "maximum": 5}
        assert broll_ideas.FACE == "face"

    def test_the_prompts_name_the_face_the_ideas_and_the_json_they_ask_for(self):
        assert '"{face}"' in broll_ideas.VIEWER_PROMPT and "FACE ALONE" in broll_ideas.VIEWER_PROMPT
        assert '"order": ["0", "{face}", "1"]' in broll_ideas.VIEWER_PROMPT
        assert '"no_picture_why"' in broll_ideas.DA_PROMPT and "EMPTY list means" in broll_ideas.DA_PROMPT
        assert '"hero_ok": true when' in broll_ideas.DA_PROMPT
        assert '"verdict": "pass"' in broll_ideas.VERIFIER_PROMPT
        for template in (broll_ideas.DA_PROMPT, broll_ideas.VERIFIER_PROMPT, broll_ideas.VIEWER_PROMPT):
            assert "ENGLISH" in template and "{principes}" in template and "{moments}" in template
        assert "{calibrage}" not in broll_ideas.DA_PROMPT                             # the director never reads it
        assert "{calibrage}" in broll_ideas.VERIFIER_PROMPT and "{calibrage}" in broll_ideas.VIEWER_PROMPT


def test_the_whole_round_on_one_moment_down_to_the_image_prompt(monkeypatch):
    """The dry run of the bench: a real-person idea the verifier catches, a fix, the viewer's order with the face."""
    whitman = dict(CAST, title="A real one", picture="Charles Whitman at a desk.", subject="Charles Whitman at a desk",
                   kind="scene", people="one", person="anonymous", light="lamp light")
    m = moment(hero=True, substance=True)
    # the forearm is the idea the director says could fill the screen, the viewer gives it 4: the moment stays the hero
    judges, (moments, reserves) = run_round(
        monkeypatch, [m], da=da_reply(da(0, [dict(CAST, hero_ok=True), dict(DINER), whitman])),
        verifier=verifier_reply((0, [verdict(0, "fix", "white powder reads as a drug",
                                             details="two white cast shells open, clean pale skin, fingers half open"),
                                     verdict(1, flaw="stock"), verdict(2, "refuse", "a real person of the story")])),
        viewer=viewer_reply((0, [view(0, 4, stops="yes", link="yes"), view(1, 2, flaw="stock", link="blurry")],
                            ["0", "face", "1"])))
    assert "[2] Charles Whitman at a desk." in judges.prompt("verifier")           # the verifier's catch
    assert "Charles Whitman" not in judges.prompt("viewer")
    assert reserves == [] and len(moments) == 1
    spec = moments[0]["spec"]
    assert spec["subject"].startswith("a forearm") and "alt" not in spec
    assert spec["details"] == "two white cast shells open, clean pale skin, fingers half open"
    assert spec["light"] == CAST["light"] and spec["substance"] is True              # the editor's flag travels
    text = shot_prompt.build_prompt(spec, "hero", "")
    assert "forearm" in text[:120] and "Soft window daylight from the left, late afternoon." in text
    assert "clean pale skin" in text and not shot_prompt.NEGATION.search(text)
    assert dict(broll.FILTERS) == {"ideas: fixed by the verifier (fixed)": 1, "ideas: refused by the verifier": 1}
    record = broll_ideas.LAST_IDEAS[0]
    assert [(i["title"], i["verdict"], i["score"], i["above_face"]) for i in record["ideas"]] == [
        ("The cast comes off", "fix", 4, True), ("Back to the door", "pass", 2, False), ("A real one", "refuse", None, False)]
    # the moment is still a moment: where, how long, hero
    assert moments[0]["t"] == m["t"] and moments[0]["dur"] == 2.5 and moments[0]["hero"] is True
