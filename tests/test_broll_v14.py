"""B-roll « ambiance » v14 (2-oct-2026): a register is a style, the restraint of an experience lived as negative only,
an inner picture is what is perceived, a clip about a death is made of absences, the safety rule (editor, director and
a review verdict), the editor's flags (set phrase, negation, precise structure), the parallel as a bench option.
No model, no ComfyUI."""
import pytest
from PIL import Image

import ai_brain
import broll
import visual_mood

from test_broll import TEXT, _transcript, _words


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    broll.FILTERS.clear()
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setattr(broll, "HERO_TAKES", 1)
    monkeypatch.setattr(broll, "comfy_release", lambda full=False: None)
    yield
    broll.FILTERS.clear()


def _plan(monkeypatch, data=None, **kw):
    seen = {}
    monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt, schema=schema) or (data or {"moments": []}))
    return seen, broll.plan_with_claude({}, _words(TEXT), 4, [], hero=True, **kw)


def _at(word):
    return next(w for w in _words(TEXT) if w["text"] == word)


def _mo(word, worth=4, **extra):
    return {"anchor": word, "time": _at(word)["start"], "image_prompt": word, "subject": word, "worth": worth, **extra}


class TestRegisterIsAStyle:
    def test_the_bible_and_the_director_take_the_scene_from_the_sentence(self, monkeypatch):
        rules = ai_brain.bible_rules()
        assert "A REGISTER IS A STYLE, NEVER A SCENE" in rules and "never a scene, a place, a subject or a person" in rules
        assert "(40 to 80 words: the STYLE of ONE single picture only" in rules
        # v16: one picture's look, never a layout (the universe episode's register was "a side-by-side of two photos")
        assert "never a layout of several pictures: no pair" in " ".join(rules.split())
        assert "two pictures of one register never share a scene" in broll.REGISTER_TEXT
        assert "never the person seen" in broll.REGISTER_TEXT and "the look of one picture" in broll.REGISTER_TEXT


class TestRestraintByValence:
    def test_lived_as_negative_restrained_lived_as_positive_full_colours(self):
        neg = {"visibility": "inner", "gravity": "real", "valence": "uneasy"}
        pos = {"visibility": "inner", "gravity": "real", "valence": "elated"}
        assert visual_mood._restrained(neg) and not visual_mood._restrained(pos)
        assert "with restraint" in visual_mood.words(neg)["medium"] and "with restraint" not in visual_mood.words(pos)["medium"]
        # the grade: a healing lived as positive keeps the budget of a moment with no suffering
        free = visual_mood.grade({"valence": "elated"}, signature=0)
        heal = visual_mood.grade({"valence": "elated", "gravity": "real"}, signature=0)
        assert heal["sat"] == free["sat"] and heal["temp"] == free["temp"]
        assert "chroma" not in visual_mood.targets(pos) or visual_mood.targets(pos)["chroma"][1] > 32

    def test_the_register_line_follows_the_valence(self, monkeypatch):
        b = ai_brain._clean_bible({"world": ["x"], "registers": [
            {"name": "journey", "kind": "inner", "when": "x", "look": "A saturated folding light, oil-paint texture " * 3}]}, "claude")
        monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", b)
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "style": "journey",
               "mood": visual_mood.clean({"visibility": "inner", "gravity": "real", "valence": "elated"})}]
        assert broll.RESTRAINT_LINE not in broll._art_prompt(ms, {})
        ms[0]["mood"] = visual_mood.clean({"visibility": "inner", "gravity": "real", "valence": "grim"})
        assert broll.RESTRAINT_LINE in broll._art_prompt(ms, {})


class TestInnerIsPerceived:
    def test_the_words_and_the_editor_rule(self, monkeypatch):
        w = visual_mood.words({"visibility": "inner"})["medium"]
        assert w.startswith("what the person perceives") and "never a face that looks pensive" in w
        # v16: what fills the frame, never the viewer ("first-person" made the image model draw a selfie)
        assert "painted as what fills the frame" in w and "never the viewer (no first-person" in w
        seen, _m = _plan(monkeypatch)
        text = " ".join(seen["prompt"].split())
        assert "never the person seen from outside nor a pensive face" in text
        assert 'no "first-person", "point of view" or "through his eyes" in a prompt' in text


class TestAClipAboutADeath:
    def test_the_editor_answers_the_clip_gravity(self, monkeypatch):
        seen, _m = _plan(monkeypatch)
        assert seen["schema"]["properties"]["clip_gravity"]["enum"] == ["none", "real", "grave"]
        assert "clip_gravity" in seen["schema"]["required"] and '"clip_gravity": what the clip AS A WHOLE is about' in seen["prompt"]
        data = {"clip_gravity": "grave", "moments": [_mo("soldiers")]}
        _seen, moments = _plan(monkeypatch, data)
        assert moments[0]["clip_gravity"] == "grave"

    def test_every_picture_becomes_an_absence_and_needs_the_directors_rewrite(self, monkeypatch, capsys):
        made, seen = [], {}

        def fake_image(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", **kw):
            Image.new("RGB", size, (90, 90, 90)).save(out_path, quality=80)
            made.append(kw.get("mood"))
            return out_path

        def fake_direct(moments, clip, **kw):
            seen["prompt"] = broll._art_prompt(moments, clip, **{k: v for k, v in kw.items() if k in ("mixed", "faces")})
            for m in moments:
                m["prompt_editor"], m["prompt"], m["art"] = m["prompt"], ("word " * 60).strip(), True
            return len(moments)

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "local_image", fake_image)
        monkeypatch.setattr(broll, "review_images", lambda cands, words: [{"score": 5} for _ in cands])
        monkeypatch.setattr(broll, "overlay_items", lambda *a, **k: None)
        monkeypatch.setattr(broll, "direct_art", fake_direct)
        tr = _transcript(TEXT)
        words = [{"text": w["word"].strip(), "start": w["start"], "end": w["end"]} for w in tr["segments"][0]["words"]]
        data = {"clip_gravity": "grave", "moments": [
            {**_mo("soldiers"), "mood": {"valence": "warm", "gravity": "none"}},
            {**_mo("sergeant"), "mood": {"valence": "neutral", "visibility": "inner"}}]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: [dict(m, clip_gravity="grave") for m in
                                                                     broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range"))])
        cfg = {"planner": "claude", "layout": "mixed", "style": "auto", "max": 4, "art_director": True}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert all(it["mood"]["gravity"] == "grave" and it["mood"]["absence"] for it in rep["items"])
        assert seen["prompt"].count("ABSENCE (the clip is about a death") == 2
        assert any(it["mood"].get("sober") for it in rep["items"])            # the inner one, made sober
        assert "an absence: the places and things the person left" in visual_mood.words(rep["items"][0]["mood"])["medium"]
        # without the director's rewrite, no absence picture goes out with the editor's draft
        broll.FILTERS.clear()
        monkeypatch.setattr(broll, "direct_art", lambda moments, clip, **kw: 0)
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, cfg)
        assert rep is None or not rep.get("items")
        assert broll.FILTERS["experience: sober picture not rewritten"] == 2


class TestSafety:
    def test_the_rule_reaches_the_editor_and_the_director(self, monkeypatch):
        seen, _m = _plan(monkeypatch)
        assert broll.SAFETY_RULE in seen["prompt"]
        assert "NOTHING THAT EVOKES AN OVERDOSE" in broll._art_prompt([{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s"}], {})

    def test_the_review_verdict_drops_and_never_redoes(self):
        assert "safe" in broll.REVIEW_SCHEMA["properties"]["reviews"]["items"]["properties"]
        assert '"safe" (true / false): false when the picture evokes an overdose' in broll.REVIEW_PROMPT
        c = broll._take_review({"layout": "card"}, {"score": 5, "look": 5, "safe": False, "better_prompt": "Same, brighter."})
        assert c["safe"] is False and broll._keep_meaningful([c]) == []
        # v15: an unsafe picture is never made again with the same idea — only another one (v16: the director's)
        assert broll._next_prompt(c) is None and broll._wants_new_idea(c)
        # v16: judged WITH its words — a container of a substance on a sentence about a death
        text = " ".join(broll.REVIEW_PROMPT.split())
        assert "Read it WITH ITS WORDS: on a sentence that tells of a death" in text
        assert "WITH ITS WORDS: on a sentence that tells of a death" in " ".join(broll.SAFETY_RULE.split())
        c = broll._take_review({"layout": "card"}, {"score": 5, "look": 5, "safe": False, "new_prompt": "From the review."})
        assert broll._next_prompt(c) is None               # v16: the review's other idea is not read any more
        c["new_prompt"] = "Another idea."                  # the art director's (another_idea)
        assert broll._next_prompt(c) == "Another idea."
        ok = broll._take_review({"layout": "card"}, {"score": 4, "look": 4})
        assert ok["safe"] is True and broll._keep_meaningful([ok]) == [ok]
        assert broll._better(ok, c)


class TestFlags:
    def test_a_flagged_moment_is_not_made(self, monkeypatch):
        data = {"moments": [_mo("soldiers", negated=True), _mo("marched", set_phrase=True),
                            _mo("sergeant", precise_structure=True), _mo("desert")]}
        seen, moments = _plan(monkeypatch, data)
        item = seen["schema"]["properties"]["moments"]["items"]
        assert all(f in item["required"] and item["properties"][f] == {"type": "boolean"} for f in broll.FLAGS)
        assert broll.FLAGS_RULE in seen["prompt"]
        assert [m["anchor"] for m in moments] == ["desert"]
        assert broll.FILTERS["editor: flagged negated"] == 1 and broll.FILTERS["editor: flagged set phrase"] == 1

    def test_in_the_fixed_moments_a_flag_is_a_skip_with_its_reason(self, monkeypatch):
        fixed = [{"anchor": w, "time": _at(w)["start"], "said": w} for w in ("soldiers", "desert")]
        _seen, moments = _plan(monkeypatch, {"moments": [_mo("soldiers", negated=True), _mo("desert")]}, fixed=fixed)
        assert [m["anchor"] for m in moments] == ["desert"]
        assert broll.LAST_SKIPS == [{"t": fixed[0]["time"], "anchor": "soldiers", "why": "flagged negated"}]


class TestParallel:
    def test_the_editor_says_one_or_pair_and_the_director_paints_it(self, monkeypatch):
        """v16 (the user's correction): side by side is fine when both halves share the structure compared."""
        seen, moments = _plan(monkeypatch, {"moments": [_mo("soldiers", parallel="pair"), _mo("desert", parallel="one")]})
        item = seen["schema"]["properties"]["moments"]["items"]
        assert item["properties"]["parallel"]["enum"] == ["none", "one", "pair"] and "parallel" in item["required"]
        prompt = " ".join(seen["prompt"].split())
        assert "A PARALLEL: when the speaker compares two things for a structure they share" in prompt
        assert "the real reference image of its own field" in prompt and "same scale, density and framing" in prompt
        assert "A KNOWN PICTURE" in prompt
        assert [m["parallel"] for m in moments] == ["pair", "one"]
        art = broll._art_prompt(moments, {})
        assert broll.PAIR_LINE in art and broll.ONE_LINE in art
        lines = broll._review_lines([{"file": "/x/broll_0.jpg", "layout": "card", "m": {**moments[0], "said": "x"}}], [])
        assert "PAIR (the two compared, side by side)" in lines[0]
        seen, moments = _plan(monkeypatch, {"moments": [_mo("soldiers")]})
        assert moments[0]["parallel"] is None and broll.PAIR_LINE not in broll._art_prompt(moments, {})
