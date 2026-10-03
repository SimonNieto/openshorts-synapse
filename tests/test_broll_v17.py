"""B-roll « ambiance » v17 (3-oct-2026): a cold viewer — the picture and the words only — drops what does not read;
the inside of a body is drawn, never photographed; no drug in use; a known picture keeps its own medium. No model is
called."""
import os

import pytest
from PIL import Image

import ai_brain
import broll
from test_broll import TEXT, _words


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    broll.FILTERS.clear()
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    yield
    broll.FILTERS.clear()


def _cand(tmp_path, name="broll_0.jpg", layout="card", **m):
    p = tmp_path / name
    Image.new("RGB", (300, 200), (90, 90, 90)).save(p)
    return {"k": 0, "file": str(p), "layout": layout,
            "m": {"t": 5.0, "said": "if I had a tumor in my brain, would I have done it", "idea": "the tower story",
                  "prompt": "The UT Austin clock tower in 1966.", "judge": "the tower must be seen", **m}}


class TestTheColdViewer:
    def test_a_picture_it_does_not_link_is_not_kept(self, monkeypatch, tmp_path):
        c = _cand(tmp_path)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_review_images", lambda cands, words: [{"score": 5, "look": 5, "problem": ""}])
        monkeypatch.setattr(broll, "cold_read", lambda cands, words, model=None, size=512:
                            {"broll_0.jpg": {"sees": "a clock tower over a lawn", "links": False, "why": "needs the story"}})
        r = broll.review_images([c], [])[0]
        assert r["score"] == 2 and r["cold"] == {"sees": "a clock tower over a lawn", "links": False, "why": "needs the story"}
        assert r["problem"].startswith("a cold viewer does not link it (needs the story)")
        assert broll.FILTERS["cold read: no link"] == 1
        c2 = broll._take_review(dict(c), r)
        assert broll._keep_meaningful([c2]) == []
        monkeypatch.setenv("BROLL_COLD_READ", "0")
        assert broll.review_images([c], [])[0]["score"] == 5

    def test_a_repeat_of_an_earlier_picture_is_not_kept_but_two_takes_are(self, monkeypatch, tmp_path):
        a, b, t2 = _cand(tmp_path, "broll_0.jpg"), _cand(tmp_path, "broll_1.jpg"), _cand(tmp_path, "broll_0_t2.jpg")
        b["k"] = 1
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_review_images", lambda cands, words: [{"score": 5, "look": 5} for _ in cands])
        monkeypatch.setattr(broll, "cold_read", lambda cands, words, model=None, size=512: {
            "broll_0.jpg": {"sees": "a brain", "links": True}, "broll_1.jpg": {"sees": "a brain", "links": True,
                                                                               "repeats": "broll_0.jpg"},
            "broll_0_t2.jpg": {"sees": "a brain", "links": True, "repeats": "broll_0.jpg"}})
        out = broll.review_images([a, b, t2], [])
        assert [r["score"] for r in out] == [5, 2, 5] and out[1]["cold"]["repeats"] == "broll_0.jpg"
        assert broll.FILTERS["cold read: a repeat"] == 1
        # an abstract stand-in for a feeling does not link, and an inner picture is for what is seen
        assert "an object standing for a feeling or a chemistry does NOT link" in " ".join(broll.COLD_PROMPT.split())
        assert "AN INNER PICTURE IS FOR WHAT IS SEEN" in broll.EXPERIENCE_RULE

    def test_a_photo_of_a_body_inside_is_redrawn_and_an_absence_is_explained(self, monkeypatch, tmp_path):
        c = _cand(tmp_path)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_review_images", lambda cands, words: [{"score": 5, "look": 5}])
        monkeypatch.setattr(broll, "cold_read", lambda cands, words, model=None, size=512:
                            {"broll_0.jpg": {"sees": "surgeons over a patient", "links": True, "body_photo": True}})
        r = broll.review_images([c], [])[0]
        assert r["safe"] is False and broll.FILTERS["cold read: a photo of a body's inside"] == 1
        c2 = broll._take_review(dict(c), r)
        assert c2["m"]["inside_body"] is True and broll._wants_new_idea(c2) and "inside_body" not in c["m"]
        seen = {}
        absent = _cand(tmp_path, "broll_1.jpg", mood={"absence": True})
        monkeypatch.undo()                                  # the real cold_read, its prompt captured
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **kw: seen.update(prompt=prompt) or {"reads": []})
        broll.cold_read([absent], [])
        assert broll.COLD_ABSENCE in seen["prompt"]

    def test_it_sees_only_the_picture_and_the_words(self, monkeypatch, tmp_path):
        seen = {}

        def fake_json(prompt, schema, attach=None, **kw):
            seen.update(prompt=prompt, attach=attach, **kw)
            return {"reads": [{"file": "broll_0.jpg", "sees": "a tower", "links": True}]}

        monkeypatch.setattr(broll, "claude_json", fake_json)
        reads = broll.cold_read([_cand(tmp_path)], _words(TEXT), model="haiku")
        assert reads["broll_0.jpg"]["links"] is True
        p = seen["prompt"]
        assert 'heard "if I had a tumor in my brain, would I have done it"' in p and "You know NOTHING about this video" in p
        for hidden in ("the tower story", "UT Austin", "the tower must be seen"):     # no idea, no prompt, no judge line
            assert hidden not in p
        assert seen["model"] == "haiku" and len(seen["attach"]) == 1


class TestTheInsideOfABodyIsDrawn:
    def test_the_editor_declares_it_and_the_image_is_drawn(self, monkeypatch):
        seen = {}
        t = next(w for w in _words(TEXT) if w["text"] == "drill")["start"]
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt, schema=schema)
                            or {"moments": [{"anchor": "drill", "time": t, "image_prompt": "x", "worth": 4,
                                             "inside_body": True}]})
        moments = broll.plan_with_claude({}, _words(TEXT), 4, [], hero=True)
        item = seen["schema"]["properties"]["moments"]["items"]
        assert "inside_body" in item["required"] and broll.BODY_RULE in seen["prompt"]
        assert moments[0]["inside_body"] is True
        assert broll.BODY_LINE.format(drawing=broll.DRAWING_HOUSE) in broll._art_prompt(moments, {})
        text = broll._image_text("A brain lit from the side. " * 8, "photo", art=True, body=True)
        assert broll.DRAWING_HOUSE in text and broll.DRAWING_HOUSE not in broll._image_text("A brain.", "photo", art=True)

    def test_the_review_and_the_bible(self):
        review = " ".join(broll.REVIEW_PROMPT.split())
        assert "a PHOTOGRAPH of the inside of a body (an organ, a brain, tissue, blood, an open operation)" in review
        rules = " ".join(ai_brain.bible_rules().split())
        assert "the inside of a body (organs, tissue, an operation) is never a register: it is the episode's \"drawing\"" in rules
        assert "never a chart, a formula or a labelled diagram" in rules


class TestMore:
    def test_no_drug_in_use(self):
        assert "No drug being taken nor its gear in use" in " ".join(broll.SAFETY_RULE.split())
        assert "a drug being taken or its gear in use" in " ".join(broll.REVIEW_PROMPT.split())

    def test_a_known_picture_keeps_its_own_medium(self):
        assert "Its own medium and colours overrule a register's" in " ".join(broll.KNOWN_PICTURE_RULE.split())
        assert "the register's medium and palette" in broll.PAIR_LINE and "the register's medium and palette" in broll.ONE_LINE
        rules = " ".join(ai_brain.bible_rules().split())
        assert "a register for a KNOWN image the speaker refers to" in rules
