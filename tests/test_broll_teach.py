"""What the art director learns from the owner's verdicts (broll_teach, 4-oct-2026): a lesson per explained verdict,
checked before it applies (the whole set rewritten with it, drawn before / after through the production's own code),
applied exactly as checked; the kept ones reach the director when plus.BROLL["lessons"] is on."""
import json
import os

import pytest
from PIL import Image

import broll_draw
import broll_teach
import plus


def _verdict(out, pid, verdict="down", why="Seul le personnage est en dessin", change="mettre tout en dessin"):
    path = os.path.join(out, broll_teach.broll_gallery.FEEDBACK_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": pid, "verdict": verdict, "why": why, "change": change, "said": "come to a class",
                            "idea": "an invitation", "prompt": "only one drawn man on a mat"}) + "\n")


@pytest.fixture
def ask(monkeypatch):
    answers, prompts = [], []

    def fake(prompt, schema=None):
        prompts.append(prompt)
        return answers.pop(0)
    monkeypatch.setattr(broll_teach, "_ask", fake)
    return answers, prompts


@pytest.fixture
def pictures(monkeypatch):
    """The gallery's pictures: the critiqued one and four kept pictures of other clips."""
    pics = [{"id": "pic1", "said": "come to a class", "clip": "Jiu-jitsu", "layout": "hero", "seed": 7, "kept": True}]
    pics += [{"id": f"ref{i}", "said": f"sentence {i}", "clip": f"clip {i}", "layout": "hero" if i == 3 else "card",
              "seed": 100 + i, "kept": True} for i in range(5)]
    monkeypatch.setattr(broll_teach.broll_gallery, "_from_traces", lambda out: pics)
    monkeypatch.setattr(broll_teach.broll_gallery, "_from_bench", lambda out: [])
    return pics


class Director:
    """The art director and verifier, faked: remembers the lessons block of each call."""
    def __init__(self):
        self.blocks = []

    def __call__(self, sentences, taught=None):
        self.blocks.append(taught)
        tag = "after" if taught and "NEW" in taught else "before"
        ideas = [{"idea": "i", "picture": f"{tag} {s}"} for _t, _b, s in sentences]
        verdicts = [{"verdict": "refuse" if s == "sentence 4" else "pass", "reason": ""} for _t, _b, s in sentences]
        return ideas, verdicts, "STYLE."


def _render(made):
    def render(text, out, layout, seed):
        made.append((text, os.path.basename(out), layout, seed))
        Image.new("RGB", (90, 160) if layout == "hero" else (160, 90), (90, 90, 90)).save(out)
    return render


def _proposed(out, ask, text="Toute la scène est dessinée, décor compris."):
    answers, _ = ask
    _verdict(out, "pic1")
    answers.append({"lesson": text, "same_as": None})
    return broll_teach.propose(out, "pic1")


def test_a_verdict_becomes_a_proposed_lesson(tmp_path, ask):
    _answers, prompts = ask
    lesson = _proposed(str(tmp_path), ask)
    assert lesson["status"] == "proposed" and lesson["from"] == "pic1"
    assert "Seul le personnage est en dessin" in prompts[0] and "only one drawn man" in prompts[0]
    assert broll_teach.director_block(str(tmp_path)) == "", "a proposed lesson does not reach the director"


def test_nothing_applies_without_a_check(tmp_path, ask):
    out = str(tmp_path)
    lid = _proposed(out, ask)["id"]
    with pytest.raises(ValueError):
        broll_teach.update(out, lid, status="kept")
    with pytest.raises(ValueError):
        broll_teach.apply(out, lid)


def test_the_check_draws_before_and_after_then_applies_exactly_the_checked_set(tmp_path, ask, pictures):
    answers, _ = ask
    out = str(tmp_path)
    lid = _proposed(out, ask, "NEW rule.")["id"]
    director, made = Director(), []
    st = broll_teach.start_check(out, lid, direct=director, render=_render(made), background=False)
    assert st["state"] == "done", st
    assert st["merged"] == ["NEW rule."], "first lesson: the set is the lesson itself, no AI call"
    assert director.blocks[0] == "" and "- NEW rule." in director.blocks[1], "before: current set (none); after: new set"
    # the critiqued moment first, then 3 fixed references of other clips (a full screen among them), same seeds
    assert [r["said"] for r in st["rows"]] == ["come to a class", "sentence 3", "sentence 0", "sentence 1"]
    assert st["rows"][0]["own"] and not st["rows"][1]["own"]
    assert {(t.split(" ", 1)[1], seed) for t, _f, _l, seed in made} >= {("before come to a class", 7),
                                                                        ("after come to a class", 7)}
    assert all(t.startswith("STYLE. ") for t, *_ in made), "the production's picture_text: the style first"
    assert broll_teach.board_path(out, lid)
    refs = json.load(open(os.path.join(out, broll_teach.REFS_FILE), encoding="utf-8"))
    assert "pic1" not in [r["id"] for r in broll_teach.references(out, "pic1")] and len(refs) == 4

    broll_teach.apply(out, lid)
    assert [x["text"] for x in broll_teach.kept(out)] == ["NEW rule."]
    assert next(x for x in broll_teach.lessons(out) if x["id"] == lid)["status"] == "applied"
    assert "- NEW rule." in broll_teach.director_block(out)

    # a second lesson: the AI rewrites the whole set; applying replaces the kept set by the checked one
    _verdict(out, "pic1", why="trop de couleurs")
    answers.append({"lesson": "NEW palette.", "same_as": None})
    lid2 = broll_teach.propose(out, "pic1")["id"]
    answers.append({"lessons": ["NEW rule, the palette kept sober."], "summary": "fusionnées"})
    st2 = broll_teach.start_check(out, lid2, direct=Director(), render=_render([]), background=False)
    assert st2["merged"] == ["NEW rule, the palette kept sober."] and st2["summary"] == "fusionnées"
    broll_teach.apply(out, lid2)
    assert [x["text"] for x in broll_teach.kept(out)] == ["NEW rule, the palette kept sober."]
    assert [x["status"] for x in broll_teach.lessons(out) if x.get("from_check") == lid] == ["replaced"]


def test_a_check_goes_stale(tmp_path, ask, pictures):
    out = str(tmp_path)
    lid = _proposed(out, ask, "NEW rule.")["id"]
    broll_teach.start_check(out, lid, direct=Director(), render=_render([]), background=False)
    broll_teach.update(out, lid, text="NEW rule, rewritten by her.")
    assert broll_teach.check_state(out, lid)["stale"] is True
    with pytest.raises(ValueError):
        broll_teach.apply(out, lid)


def test_a_failed_check_says_why(tmp_path, ask, pictures):
    out = str(tmp_path)
    lid = _proposed(out, ask)["id"]

    def broken(sentences, taught=None):
        raise RuntimeError("Claude down")
    st = broll_teach.start_check(out, lid, direct=broken, render=_render([]), background=False)
    assert st["state"] == "error" and "Claude down" in st["error"]


def test_the_same_lesson_twice_is_not_added(tmp_path, ask, pictures):
    answers, prompts = ask
    out = str(tmp_path)
    lid = _proposed(out, ask, "NEW rule.")["id"]
    broll_teach.start_check(out, lid, direct=Director(), render=_render([]), background=False)
    broll_teach.apply(out, lid)
    _verdict(out, "pic2", why="le décor est en photo")
    answers.append({"lesson": "Le décor aussi est dessiné.", "same_as": 1})
    same = broll_teach.propose(out, "pic2")
    assert same["status"] == "same" and same["text"] == "NEW rule."
    assert "1. NEW rule." in prompts[-1]


def test_no_words_no_lesson(tmp_path, ask):
    out = str(tmp_path)
    _verdict(out, "pic1", why="", change=" ")
    with pytest.raises(ValueError):
        broll_teach.propose(out, "pic1")
    with pytest.raises(ValueError):
        broll_teach.propose(out, "unknown")


def test_update_rewrites_drops_and_refuses_unknowns(tmp_path, ask):
    out = str(tmp_path)
    lid = _proposed(out, ask)["id"]
    assert broll_teach.update(out, lid, text="  Ma   version.  ")["text"] == "Ma version."
    assert broll_teach.update(out, lid, status="refused")["status"] == "refused"
    with pytest.raises(ValueError):
        broll_teach.update(out, lid, status="maybe")
    with pytest.raises(ValueError):
        broll_teach.update(out, "nope", status="refused")
    with pytest.raises(ValueError):
        broll_teach.update(out, lid, text="   ")


def test_the_director_reads_them_only_when_switched_on(monkeypatch):
    assert plus.BROLL["lessons"] is True, "validated by the owner in prod on 4-oct-2026"
    assert broll_draw.DA_PROMPT.count("{lessons}") == 1
    assert "\n\n{lessons}For each sentence below" in broll_draw.DA_PROMPT
    seen = []
    monkeypatch.setattr(broll_draw, "charter", lambda: ("CHARTE", "SUFFIX", "BANC"))
    monkeypatch.setattr(broll_draw.broll_ideas, "skill_text", lambda part: "PRINCIPES")
    monkeypatch.setattr(broll_draw.broll_ideas, "_call", lambda prompt, *a, **k: seen.append(prompt) or {})
    monkeypatch.setattr(broll_teach, "director_block", lambda out: "THE OWNER'S LESSONS (...):\n- Tout dessiné.\n\n")
    broll_draw.direct_and_verify([("t", "b", "s")])
    broll_draw.direct_and_verify([("t", "b", "s")], lessons=True)
    broll_draw.direct_and_verify([("t", "b", "s")], taught="THE OWNER'S LESSONS (...):\n- Autre.\n\n")
    assert "THE OWNER'S LESSONS" not in seen[0] and "BANC\n\nFor each sentence below" in seen[0], \
        "off: the call is word for word the one before the lessons"
    assert "BANC\n\nTHE OWNER'S LESSONS (...):\n- Tout dessiné.\n\nFor each sentence below" in seen[1]
    assert "- Autre." in seen[2] and "Tout dessiné" not in seen[2], "a check compares the sets it is given"
    assert broll_draw.picture_text("STYLE.", "A man.") == "STYLE. A man."


def test_references_are_rebuilt_when_too_few(tmp_path, pictures):
    out = str(tmp_path)
    path = os.path.join(out, broll_teach.REFS_FILE)
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"id": "pic1", "said": "come to a class", "clip": "Jiu-jitsu", "layout": "hero", "seed": 7}], f)
    refs = broll_teach.references(out, "pic1")
    assert len(refs) == 3 and "pic1" not in [r["id"] for r in refs], "one clip only (the critiqued one): rebuilt"
