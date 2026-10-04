"""What the art director learns from the owner's verdicts (broll_teach, 4-oct-2026): a lesson per explained verdict,
proposed until she keeps it; the kept ones reach the director only when plus.BROLL["lessons"] is on."""
import json
import os

import pytest

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

    def fake(prompt):
        prompts.append(prompt)
        return answers.pop(0)
    monkeypatch.setattr(broll_teach, "_ask", fake)
    return answers, prompts


def test_a_verdict_becomes_a_proposed_lesson_then_kept(tmp_path, ask):
    answers, prompts = ask
    out = str(tmp_path)
    _verdict(out, "pic1")
    answers.append({"lesson": "Toute la scène est dessinée, décor compris.", "same_as": None})
    lesson = broll_teach.propose(out, "pic1")
    assert lesson["status"] == "proposed" and lesson["from"] == "pic1"
    assert "Seul le personnage est en dessin" in prompts[0] and "only one drawn man" in prompts[0]
    assert broll_teach.director_block(out) == "", "a proposed lesson does not reach the director"
    broll_teach.update(out, lesson["id"], status="kept")
    block = broll_teach.director_block(out)
    assert "THE OWNER'S LESSONS" in block and "- Toute la scène est dessinée, décor compris." in block


def test_a_new_proposal_replaces_the_old_one_of_the_same_picture(tmp_path, ask):
    answers, _ = ask
    out = str(tmp_path)
    _verdict(out, "pic1")
    answers += [{"lesson": "Première.", "same_as": None}, {"lesson": "Seconde.", "same_as": None}]
    broll_teach.propose(out, "pic1")
    broll_teach.propose(out, "pic1")
    assert [x["text"] for x in broll_teach.lessons(out)] == ["Seconde."]


def test_the_same_lesson_twice_is_not_added(tmp_path, ask):
    answers, prompts = ask
    out = str(tmp_path)
    _verdict(out, "pic1")
    answers.append({"lesson": "Toute la scène est dessinée.", "same_as": None})
    broll_teach.update(out, broll_teach.propose(out, "pic1")["id"], status="kept")
    _verdict(out, "pic2", why="le décor est en photo")
    answers.append({"lesson": "Le décor aussi est dessiné.", "same_as": 1})
    same = broll_teach.propose(out, "pic2")
    assert same["status"] == "same" and same["text"] == "Toute la scène est dessinée."
    assert "1. Toute la scène est dessinée." in prompts[1]
    assert len(broll_teach.lessons(out)) == 1


def test_no_words_no_lesson(tmp_path, ask):
    out = str(tmp_path)
    _verdict(out, "pic1", why="", change=" ")
    with pytest.raises(ValueError):
        broll_teach.propose(out, "pic1")
    with pytest.raises(ValueError):
        broll_teach.propose(out, "unknown")


def test_update_rewrites_drops_and_refuses_unknowns(tmp_path, ask):
    answers, _ = ask
    out = str(tmp_path)
    _verdict(out, "pic1")
    answers.append({"lesson": "Brouillon.", "same_as": None})
    lid = broll_teach.propose(out, "pic1")["id"]
    assert broll_teach.update(out, lid, text="  Ma   version.  ")["text"] == "Ma version."
    assert broll_teach.update(out, lid, status="refused")["status"] == "refused"
    assert broll_teach.director_block(out) == ""
    with pytest.raises(ValueError):
        broll_teach.update(out, lid, status="maybe")
    with pytest.raises(ValueError):
        broll_teach.update(out, "nope", status="kept")
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
    assert "THE OWNER'S LESSONS" not in seen[0] and "BANC\n\nFor each sentence below" in seen[0], \
        "off: the call is word for word the one before the lessons"
    assert "BANC\n\nTHE OWNER'S LESSONS (...):\n- Tout dessiné.\n\nFor each sentence below" in seen[1]
