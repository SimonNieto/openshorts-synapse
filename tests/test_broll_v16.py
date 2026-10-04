"""B-roll « ambiance » v16 (2-oct-2026): who is in the frame is declared (never read from the words), the hero's
second take is another composition, another idea is the art director's, the review sees the fx and judges inner
pictures, pairs and safety with their words, and Z-Image base can paint the hero and the register pictures. No
model is called."""
import os

import numpy as np
import pytest
from PIL import Image

import ai_brain
import broll
import plus
from test_broll import TEXT, _words


@pytest.fixture(autouse=True)
def _clear(monkeypatch, tmp_path):
    broll.FILTERS.clear()
    monkeypatch.setattr(broll, "NOTION_DIR", str(tmp_path / "notions"))
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")
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


LONG = ("A lone soldier walks across the cracked desert floor at dawn, canteen in hand, boots dusted red. The camp "
        "sits far behind him, three canvas tents and a cold fire pit. The frame is 9:16, the man in the upper-middle "
        "third, a blurred creosote bush close in the foreground, the lower third an empty dark plain. 35 mm lens at "
        "chest height, ten metres away. First sun from the right, low and warm, long soft shadows.")
ALT = ("The same soldier seen from far above at dawn, a small figure crossing the cracked red desert floor toward "
       "the camp, three canvas tents and a cold fire pit at the edge of the frame, long soft shadows from a low sun "
       "on the right, the lower third an empty dark plain, 24 mm lens from a high ridge, fine grain, quiet.")


class TestPeopleAreDeclared:
    def test_the_editor_and_the_director_declare_who_is_in_the_frame(self, monkeypatch):
        seen, moments = _plan(monkeypatch, {"moments": [_mo("soldiers", people="group"), _mo("desert", people="none")]})
        item = seen["schema"]["properties"]["moments"]["items"]
        assert item["properties"]["people"]["enum"] == list(broll.PEOPLE) and "people" in item["required"]
        assert broll.PEOPLE_RULE in seen["prompt"]
        assert [m["people"] for m in moments] == ["group", "none"]
        art = broll.ART_SCHEMA["properties"]["prompts"]["items"]
        assert art["properties"]["people"]["enum"] == list(broll.PEOPLE) and "people" in art["required"]
        broll._apply_art(moments, {"prompts": [{"k": 0, "prompt": LONG, "people": "one"}, {"k": 1, "prompt": LONG}]})
        assert moments[0]["people"] == "one" and moments[1]["people"] == "none"   # undeclared: the editor's stays

    def test_an_inner_picture_never_gets_a_person(self, monkeypatch):
        made = _job(monkeypatch, [{**_mo("soldiers", people="one", style="photo"),
                                   "mood": {"visibility": "inner"}}, _mo("desert", people="one")])
        texts = {m["out"]: m["text"] for m in made}
        inner = next(t for o, t in texts.items() if o.startswith("broll_0"))
        other = next(t for o, t in texts.items() if o.startswith("broll_1"))
        assert "anonymous person" not in inner.lower() and "face turned away" not in inner.lower()
        assert "face turned away" in other.lower() or "anonymous person" in other.lower()


def _job(monkeypatch, moments, cfg=None, review=None, art=None):
    """add_broll with the planner, ComfyUI and the review faked: the texts sent to the image model."""
    made = []
    words = _words(TEXT)

    def fake_local(prompt, style, out_path, engine="zimage", timeout=300, size=(768, 1344), look="", art=False,
                   seed=None, steps=None, faces=False, register=None, mood="", people=None, model="turbo", negative="",
                   body=False, drawing=""):
        Image.new("RGB", size, (60, 90, 120)).save(out_path, quality=80)
        made.append({"out": os.path.basename(out_path), "prompt": prompt, "model": model, "negative": negative,
                     "text": broll._image_text(prompt, style, look, art, faces, register, mood, people, body), "size": size,
                     "body": body})
        return out_path

    monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
    monkeypatch.setattr(broll, "claude_ready", lambda: True)
    monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
    monkeypatch.setattr(broll, "local_image", fake_local)
    monkeypatch.setattr(broll, "overlay_items", lambda *a, **k: None)
    monkeypatch.setattr(broll, "HERO_TAKES", 1)
    data = {"moments": moments}
    monkeypatch.setattr(broll, "plan_with_claude",
                        lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
    monkeypatch.setattr(broll, "review_images", review or (lambda cands, words_: [{"score": 5, "look": 5} for _ in cands]))
    if art:
        monkeypatch.setattr(broll, "direct_art", art)
    tr = {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in words]}]}
    base = {"planner": "claude", "layout": "mixed", "style": "auto", "art_director": bool(art)}
    broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1, {**base, **(cfg or {})})
    return made


class TestTheHerosSecondTake:
    def test_the_director_writes_another_composition_for_the_hero_only(self):
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "hero": True},
              {"t": 9.0, "anchor": "b", "prompt": "q", "subject": "t"}]
        broll._apply_art(ms, {"prompts": [{"k": 0, "prompt": LONG, "people": "one", "alt_prompt": ALT},
                                          {"k": 1, "prompt": LONG, "people": "none", "alt_prompt": ALT}]})
        assert ms[0]["prompt_alt"] == ALT and "prompt_alt" not in ms[1]
        assert '"alt_prompt": the same moment shot another way' in broll._art_prompt(ms, {})

    def test_take_two_paints_the_other_composition(self, monkeypatch):
        monkeypatch.setattr(broll, "HERO_TAKES", 2)

        def art(moments, clip, **kw):
            for m in moments:
                m.update(prompt=LONG, art=True, people="one", prompt_editor=m["prompt"])
                if m.get("hero"):
                    m["prompt_alt"] = ALT
            return len(moments)

        made = []
        words = _words(TEXT)

        def fake_local(prompt, style, out_path, size=(768, 1344), **kw):
            Image.new("RGB", size, (60, 90, 120)).save(out_path, quality=80)
            made.append((os.path.basename(out_path), prompt))
            return out_path

        monkeypatch.setattr(broll, "comfy_available", lambda timeout=3: True)
        monkeypatch.setattr(broll, "claude_ready", lambda: True)
        monkeypatch.setattr(broll, "_frame_sheets", lambda *a, **k: [])
        monkeypatch.setattr(broll, "local_image", fake_local)
        monkeypatch.setattr(broll, "overlay_items", lambda *a, **k: None)
        monkeypatch.setattr(broll, "direct_art", art)
        data = {"moments": [_mo("soldiers", hero=True, people="one"), _mo("desert", people="none")]}
        monkeypatch.setattr(broll, "plan_with_claude",
                            lambda clip, words_, n, avoid, *a, **k: broll._parse_moments(data, words_, n, avoid, 3.0, k.get("dur_range")))
        monkeypatch.setattr(broll, "review_images",
                            lambda cands, words_: [{"score": 5, "look": 5 if c.get("alt") else 4} for c in cands])
        tr = {"segments": [{"words": [{"word": " " + w["text"], "start": w["start"], "end": w["end"]} for w in words]}]}
        rep = broll.add_broll("clip.mp4", "out.mp4", {}, tr, 0.0, words[-1]["end"] + 1,
                              {"planner": "claude", "layout": "mixed", "style": "auto", "art_director": True})
        takes = dict(made)
        hero_k = next(o for o, _p in made if o.endswith("_t2.jpg"))[len("broll_"):-len("_t2.jpg")]
        assert takes[f"broll_{hero_k}_t2.jpg"] == ALT and takes[f"broll_{hero_k}.jpg"] == LONG
        hero = next(it for it in rep["items"] if it["layout"] == "hero")
        assert hero["alt"] is True and hero["prompt"] == ALT and hero["people"] == "one"


class TestBaseModel:
    def test_the_graph_of_the_base_model(self):
        g = broll._graph("zimage", "A scene.", 7, 896, 1600, model="base", negative="blurry, a selfie")
        assert g["u"]["inputs"]["unet_name"] == broll.ZIMAGE_BASE_MODEL
        assert g["3"]["class_type"] == "CLIPTextEncode" and g["3"]["inputs"]["text"] == "blurry, a selfie"
        k = g["5"]["inputs"]
        assert k["cfg"] == broll.ZIMAGE_BASE_CFG == 4.0 and k["steps"] == broll.ZIMAGE_BASE_STEPS == 25
        t = broll._graph("zimage", "A scene.", 7, 1152, 720)
        assert t["3"]["class_type"] == "ConditioningZeroOut" and t["5"]["inputs"]["cfg"] == 1.0
        assert t["5"]["inputs"]["steps"] == 8 and t["u"]["inputs"]["unet_name"] == "z_image_turbo_int8_convrot.safetensors"

    def test_the_negative_prompt(self):
        reg = {"name": "voices", "cheap": "A ghostly figure whispering in a dark room."}
        neg = broll.base_negative(reg, inner=True)
        assert neg.startswith(broll.BASE_NEGATIVE) and "a selfie" in neg and "A ghostly figure whispering in a dark room" in neg
        assert "collage" not in broll.base_negative(pair=True) and "collage" in broll.base_negative()

    def test_only_the_hero_and_the_registers_when_asked(self, monkeypatch):
        bible = {"registers": [{"name": "trip", "kind": "inner", "look": "A field of colour.", "when": "x",
                                "cheap": "A neon spiral."}]}
        monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", bible)
        moments = [_mo("soldiers", hero=True, people="one"), _mo("drill", style="trip"), _mo("desert", people="none")]
        made = _job(monkeypatch, moments, cfg={"base_for": "hero,register"})
        by = {m["out"]: m for m in made}
        models = sorted((m["size"], m["model"]) for m in made)
        assert models.count(((896, 1600), "base")) == 1                # the hero
        assert sum(1 for m in made if m["model"] == "base") == 2      # + the register picture
        reg = next(m for m in made if m["model"] == "base" and m["size"] != (896, 1600))
        assert "A neon spiral" in reg["negative"] and "a selfie" in reg["negative"]
        assert sum(1 for m in made if m["model"] == "turbo") == 1     # the photo card
        assert all(m["model"] == "turbo" for m in _job(monkeypatch, moments))   # off unless asked
        assert by


class TestAnotherIdeaIsTheDirectors:
    def test_the_director_reads_what_was_tried_and_writes_another_picture(self, monkeypatch):
        seen = {}

        def fake_json(prompt, schema, **kw):
            seen.update(prompt=prompt, schema=schema, **kw)
            return {"prompts": [{"k": 0, "prompt": LONG + " No window.", "judge": "j", "fx": "double", "people": "none"}]}

        monkeypatch.setattr(broll, "claude_json", fake_json)
        monkeypatch.setenv("CLAUDE_EFFORT_BROLL_ART", "max")
        c = {"k": 0, "layout": "card", "m": {"t": 5.0, "anchor": "a", "prompt": "A crowd in a room.", "subject": "voices",
                                             "said": "voices in your head"},
             "history": [{"prompt": "A crowd in a room.", "seen": "twenty people in rows", "problem": "a literal crowd"}]}
        assert broll.another_idea([c], {}) == 1
        assert seen["prompt"].startswith(broll.ANOTHER_IDEA_TEXT)
        assert "TRIED AND FAILED: «A crowd in a room.» — seen: twenty people in rows — failed: a literal crowd" in seen["prompt"]
        assert seen["effort"] == "max" and seen["timeout"] == broll.ART_TIMEOUT
        assert c["new_prompt"] == LONG and c["new"]["people"] == "none" and c["new"]["fx"] == "double"   # in the positive


class TestTheReview:
    def test_the_double_is_drawn_into_the_still_it_judges(self, tmp_path):
        p = tmp_path / "broll_0.jpg"
        arr = np.zeros((200, 400, 3), np.uint8)
        arr[:, 180:220] = 255
        Image.fromarray(arr).save(p)
        plain = np.asarray(broll._review_still({"file": str(p), "m": {}}, 400), dtype=np.float32)
        double = np.asarray(broll._review_still({"file": str(p), "m": {"fx": "double"}}, 400), dtype=np.float32)
        assert np.abs(plain - double).mean() > 3.0

    def test_inner_pair_and_safety_with_the_words(self):
        text = " ".join(broll.REVIEW_PROMPT.split())
        assert "AN INNER PICTURE (marked INNER)" in text and "(a crowd for voices) — its sense is 2" in text
        assert "A PAIR (marked PAIR)" in text and "same scale, density and framing" in text
        line = broll._review_lines([{"file": "/x/broll_0.jpg", "layout": "card",
                                     "m": {"t": 1.0, "prompt": "p", "said": "s", "mood": {"visibility": "inner"}}}], [])[0]
        assert "INNER (what the person perceives)" in line


class TestTheEditorsRules:
    def test_negated_is_not_it_does_not_matter(self):
        text = " ".join(broll.FLAGS_RULE.split())
        assert "never when he only says it does not matter" in text and "also on any other moment of the clip" in text

    def test_an_instrument_register_is_for_what_it_shows(self):
        assert "An INSTRUMENT register only for a sentence that speaks of what that" in broll.STYLE_RULE_REGISTERS
        assert "for an instrument, only the moments that speak of what it shows" in " ".join(ai_brain.bible_rules().split())


class TestV16b:
    """v16b: what the v16 bench showed — a clip that names deaths is not a clip about a death, the speakers are never
    drawn, the fact guard keeps what was said (not the editor's acronyms), an inner picture showing the person is
    dropped by the code, an art director that hangs gives way to Sonnet."""

    def test_a_clip_about_a_death_is_one_that_tells_it(self):
        text = " ".join(broll.SHEET_RULE_MOOD.split())
        assert '"grave" only when the clip TELLS someone\'s death' in text
        assert "a risk of death, a number of deaths or deaths named on the way are not" in text

    def test_the_speakers_are_never_a_picture(self, monkeypatch):
        assert "THE SPEAKERS themselves and their studio are never a picture" in " ".join(broll.SET_RULE.split())
        monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", {"speakers": [{"name": "Joe Rogan"}, {"name": "Chase Hughes"}]})
        draft = "Joe Rogan and Chase Hughes watch a screen at the UCSF studio in 1998."
        assert broll.lost_facts(draft, "Two men watch a screen.") == ["1998", "ucsf"]
        # only what the speaker said is a fact: the editor's own "MMA" may go, "UCSF" said in the clip stays
        assert broll.lost_facts("An MMA fighter at UCSF.", "A fighter in a cage.", spoken="he trained at UCSF") == ["ucsf"]
        assert broll.lost_facts("An MMA fighter.", "A fighter in a cage.", spoken="get your ass kicked") == []

    def test_an_inner_picture_showing_the_person_is_capped_by_the_code(self):
        assert "person_seen" in broll.REVIEW_SCHEMA["properties"]["reviews"]["items"]["properties"]
        inner = {"layout": "card", "m": {"prompt": "p", "mood": {"visibility": "inner"}}}
        c = broll._take_review(dict(inner), {"score": 4, "look": 4, "person_seen": True})
        assert c["score"] == 2 and broll.FILTERS["review: inner picture shows the person"] == 1
        photo = {"layout": "card", "m": {"prompt": "p", "mood": {"visibility": "eye"}}}
        assert broll._take_review(dict(photo), {"score": 4, "look": 4, "person_seen": True})["score"] == 4

    def test_a_hanging_art_director_gives_way_to_sonnet(self, monkeypatch):
        import subprocess
        calls = []

        def fake_json(prompt, schema, **kw):
            calls.append(kw["model"])
            if kw["model"] == "opus":
                raise subprocess.TimeoutExpired("claude", broll.ART_TIMEOUT)
            return {"prompts": []}

        monkeypatch.setattr(broll, "claude_json", fake_json)
        monkeypatch.setattr(ai_brain, "stage_model", lambda stage, override=None: "opus")
        assert broll._art_call("p", "B-roll: art direction of the set") == {"prompts": []}
        assert calls == ["opus", "sonnet"] and broll.FILTERS["art: too slow, sonnet instead"] == 1
        assert broll.ART_TIMEOUT == 240


class TestTheArtDirectorsThinking:
    def test_its_own_level_in_the_recipe(self, monkeypatch):
        p = plus.sanitize({"name": "x", "brain": {"preset": "custom", "stages": {"broll_art": "opus"},
                                                  "thinking_broll": "normal", "thinking_art": "max"}})
        env = plus.job_env(p)
        # 4-oct-2026: fixed in plus.BRAIN / BRAIN_EFFORT, the old profile choice is ignored
        assert env["BRAIN_BROLL_ART"] == "sonnet" and env["CLAUDE_EFFORT_BROLL_ART"] == "high"
        assert env["CLAUDE_EFFORT_BROLL"] == "medium"
        monkeypatch.setenv("CLAUDE_EFFORT_BROLL_ART", "max")
        assert broll.art_effort() == "max"
        monkeypatch.delenv("CLAUDE_EFFORT_BROLL_ART")
        monkeypatch.setenv("CLAUDE_EFFORT_BROLL", "medium")
        assert broll.art_effort() == "medium"
