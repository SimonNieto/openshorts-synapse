"""B-roll v26 « dessin » (4-oct-2026): the production chain the user validated (broll_draw) — the editor's moments, ONE
call of the art director in the episode's style charter, ONE pass of a safety verifier, one render per moment, the
charter's suffix added word for word, no judge, no render loop, refused ideas rendered for the trace only. No model and
no GPU are called: the calls are faked."""
import os

import pytest

import broll
import broll_draw
import broll_ideas
import broll_spec
import broll_v20
import plus

WORDS = [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(
    "you can find videos of meth heads carrying refrigerators down the street. Then the tumor was out.".split())]
CLIP = {"video_title_for_youtube_short": "Meth strength", "viral_hook_text": "Is it real?"}


def _moment(t, hero=False):
    spec = {"kind": "scene", "subject": "a man carrying a fridge", "people": "one", "mood": {"gravity": "none"},
            "hero": hero}
    return {"t": t, "anchor": "carrying", "said": "", "dur": 2.5, "hero": hero, "spec": spec, "mood": {"x": 1}}


class Calls:
    def __init__(self, ideas, verdicts):
        self.ideas, self.verdicts, self.prompts = ideas, verdicts, []

    def __call__(self, prompt, schema, stage, model, effort=None, timeout=None):
        self.prompts.append((stage, model, prompt))
        if schema is broll_draw.DA_SCHEMA:
            return {"moments": [{"k": k, "idea": f"idea {k}", "picture": p} for k, p in enumerate(self.ideas)]}
        return {"moments": [{"k": k, "verdict": v, "reason": "a strap" if v == "refuse" else ""}
                            for k, v in enumerate(self.verdicts)]}


@pytest.fixture
def chain(monkeypatch, tmp_path):
    def setup(moments, ideas, verdicts, trace=True, dress=None):
        calls = Calls(ideas, verdicts)
        monkeypatch.setattr(broll_ideas, "_call", calls)
        # the dress check (5-oct-2026): everybody dressed unless the test says otherwise (dress(path) -> (bare, what))
        monkeypatch.setattr(broll_draw, "dress_check", lambda path, tmp: dress(path) if dress else (False, ""))
        monkeypatch.setattr(broll_ideas, "_lessons", lambda who: "")
        monkeypatch.setattr(broll, "_frame_sheets", lambda path, tmp: [])
        monkeypatch.setattr(broll_spec, "plan_specs", lambda *a, **kw: (list(moments), []))
        monkeypatch.setattr(broll_v20, "trace", lambda *a, **kw: None)
        monkeypatch.setenv("BROLL_TRACE", "1" if trace else "0")
        made = []

        def render(text, out, layout):
            made.append((text, os.path.basename(out), layout))
            open(out, "wb").write(b"jpg")
            return out, 42
        cands, out_moments = broll_draw.run(str(tmp_path / "job" / "c_clip_1.mp4"), CLIP, WORDS, None, 0, 50, 4, [],
                                            0.0, None, 0.0, (), None, str(tmp_path), render)
        return cands, out_moments, made, calls
    return setup


def test_production_runs_the_drawn_chain():
    assert plus.BROLL["chain"] == "dessin"


def test_the_charter_style_heads_the_prompt_word_for_word_and_the_hero_is_full_screen(chain):
    _text, suffix, _banc = broll_draw.charter()
    # 4-oct-2026: the whole scene drawn (setting included), the style first so the room is not photographed
    assert suffix.startswith("Editorial ink illustration of the entire scene, setting and background included")
    assert "Premium" not in suffix and "magazine" not in suffix, "words that call a title get drawn as one"
    cands, _m, made, calls = chain([_moment(2.0, hero=True), _moment(9.0)], ["A man under a fridge.", "A dish."],
                                   ["pass", "pass"])
    # a man in the picture: the code dresses him after the director's picture (5-oct-2026); the style stays first
    assert [(t, layout) for t, _f, layout in made] == [(f"{suffix} A man under a fridge. {broll_draw.DRESSED}", "hero"),
                                                        (f"{suffix} A dish.", "card")]
    assert [c["verdict"] for c in cands] == ["keep", "keep"] and cands[0]["layout"] == "hero"
    assert cands[0]["m"]["mood"] is None and cands[0]["m"]["inside_body"] is False     # its own palette, no grade
    assert [(s, m) for s, m, _p in calls.prompts] == [("broll_ideas", "opus"), ("broll_verify", "sonnet")]
    da = calls.prompts[0][2]
    assert "THE EPISODE'S STYLE CHARTER" in da and "YOUR PRINCIPLES" in da and "Meth strength" in da


def test_a_refused_idea_is_never_used_but_rendered_for_the_trace(chain):
    cands, _m, made, _calls = chain([_moment(2.0), _moment(9.0)], ["A fridge.", "A hanging rope."], ["pass", "refuse"])
    assert [c["k"] for c in cands] == [0]
    assert [f for _t, f, _l in made] == ["broll_0.jpg", "refused_1.jpg"]
    checks = {e["verdict"]: e for e in broll_v20.LAST_CHECKS}
    assert checks["refused"]["why"] == "a strap" and checks["refused"]["file"] == "refused_1.jpg"
    assert checks["keep"]["seed"] == 42


def test_without_the_trace_a_refused_idea_is_not_rendered(chain):
    _c, _m, made, _calls = chain([_moment(2.0)], ["A rope."], ["refuse"], trace=False)
    assert made == []


def test_no_judge_no_loop_one_render_per_moment(chain):
    _c, _m, made, calls = chain([_moment(2.0), _moment(9.0), _moment(15.0)], ["A.", "B.", "C."], ["pass"] * 3)
    assert len(made) == 3 and len(calls.prompts) == 2


def test_a_missing_charter_gives_no_picture_never_an_error(chain, monkeypatch):
    def missing():
        raise OSError("charte.md")
    monkeypatch.setattr(broll_draw, "charter", missing)
    cands, _m, made, _calls = chain([_moment(2.0)], ["A."], ["pass"])
    assert cands == [] and made == []


# --- dressed bodies (5-oct-2026, the user: « et pour ce qui est des corps presque nus ? faut faire quelque chose ») ---

# the three pictures of job b8e46c24 that came out bare (no prompt asked for it): a person is named in each
BARE_ON_B8E46C24 = (
    "A single woman lies on the scanner bed, a plum-sized round mass glows softly in her abdomen, cool light.",
    "Only one man lies under a white sheet on a steel table, cool blue light on the body.",
    "A single young woman flinches from a syringe held near her shoulder, her eyes wide.")


def test_a_person_in_the_picture_is_dressed_after_it_and_the_style_stays_first():
    _text, suffix, _banc = broll_draw.charter()
    # someone lying, the inside of a body: a patient in a closed gown (everyday clothes became a crop top or underwear)
    for picture in BARE_ON_B8E46C24[:2]:
        assert broll_draw.has_person(picture), picture
        assert broll_draw.picture_text(suffix, picture) == f"{suffix} {picture} {broll_draw.DRESSED_PATIENT}"
    # anyone else: everyday clothes (a gown moved a needle scene to a clinic and added people)
    for picture in BARE_ON_B8E46C24[2:] + ("Three identical desks, one person at each.", "He holds a key."):
        assert broll_draw.has_person(picture), picture
        assert broll_draw.picture_text(suffix, picture) == f"{suffix} {picture} {broll_draw.DRESSED}"
    for picture in ("A single tall glass jar of glowing warm liquid on a desk.", "A bare wooden table, a phone on it.",
                    "An armchair by a window."):
        assert not broll_draw.has_person(picture), picture
        assert broll_draw.picture_text(suffix, picture) == f"{suffix} {picture}"
    more = broll_draw.picture_text(suffix, "A man.", more=True)
    assert more == f"{suffix} A man. {broll_draw.DRESSED} {broll_draw.DRESSED_MORE}"
    # positive words only (the image model draws what it reads): what covers the body, never "no ..."
    for s in (broll_draw.DRESSED, broll_draw.DRESSED_PATIENT, broll_draw.DRESSED_MORE):
        assert " no " not in f" {s.lower()} " and "naked" not in s.lower() and "bare" not in s.lower()
    assert "everyday clothes" in broll_draw.DRESSED and "closed long-sleeved hospital gown" in broll_draw.DRESSED_PATIENT


def test_a_bare_body_is_drawn_again_dressed_with_another_seed(chain):
    answers = iter([(True, "woman in underwear"), (False, "")])
    cands, _m, made, _calls = chain([_moment(2.0)], ["A woman in a scanner."], ["pass"],
                                    dress=lambda path: next(answers))
    assert [f for _t, f, _l in made] == ["broll_0.jpg", "broll_0_dressed.jpg"]
    assert made[1][0].endswith(broll_draw.DRESSED_MORE)
    (c,) = cands
    assert os.path.basename(c["file"]) == "broll_0_dressed.jpg" and c["m"]["prompt"].endswith(broll_draw.DRESSED_MORE)
    trace = {e["file"]: e for e in broll_v20.LAST_CHECKS}
    assert trace["broll_0.jpg"]["verdict"] == "refused" and "bare body: woman in underwear" in trace["broll_0.jpg"]["why"]
    assert trace["broll_0_dressed.jpg"]["verdict"] == "keep" and trace["broll_0_dressed.jpg"]["dress"].startswith("ok")


def test_bare_twice_means_no_picture(chain):
    cands, _m, made, _calls = chain([_moment(2.0), _moment(9.0)], ["A man under a sheet.", "A dish."], ["pass"] * 2,
                                    dress=lambda path: (True, "bare chest") if "broll_0" in path else (False, ""))
    assert [c["k"] for c in cands] == [1] and len(made) == 3
    refused = [e for e in broll_v20.LAST_CHECKS if e["verdict"] == "refused"]
    assert [e["file"] for e in refused] == ["broll_0.jpg", "broll_0_dressed.jpg"]
    assert "bare body again" in refused[1]["why"]


def test_no_answer_keeps_a_picture_only_when_it_names_nobody(chain):
    cands, _m, made, _calls = chain([_moment(2.0), _moment(9.0)], ["A woman at a desk.", "A dish."], ["pass"] * 2,
                                    dress=lambda path: (None, "no answer"))
    assert [c["k"] for c in cands] == [1] and len(made) == 2, "nothing to redraw when the check cannot answer"
    assert [e["why"] for e in broll_v20.LAST_CHECKS if e["verdict"] == "refused"] == ["dress not checked (no answer)"]


def test_the_dress_check_is_one_small_yes_no_question(monkeypatch, tmp_path):
    from PIL import Image
    src = str(tmp_path / "broll_0.jpg")
    Image.new("RGB", (896, 1600), (90, 60, 30)).save(src)
    seen = []

    def fake(prompt, schema, timeout=240, attach=None, stage=None, model=None, **kw):
        seen.append((model, stage, [Image.open(p).size for p in attach], schema))
        if model == "sonnet" and len(seen) == 1:
            raise RuntimeError("timeout")
        return {"bare": True, "what": "man, bare chest"}
    monkeypatch.setattr(broll, "claude_json", fake)
    monkeypatch.delenv("BRAIN_BROLL_DRESS", raising=False)
    assert broll_draw.dress_check(src, str(tmp_path)) == (True, "man, bare chest")
    # Sonnet (no false alarm on the 37 drawings of job b8e46c24), Haiku when Sonnet fails
    assert [(m, s) for m, s, _z, _sc in seen] == [("sonnet", "broll_dress"), ("haiku", "broll_dress")]
    assert all(max(z[0]) <= broll_draw.DRESS_PX for _m, _s, z, _sc in seen)
    assert set(seen[0][3]["properties"]) == {"bare", "what"}
    monkeypatch.setattr(broll, "claude_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert broll_draw.dress_check(src, str(tmp_path)) == (None, "no answer")
    for word in ("underwear", "swimsuit", "sheet", "chest", "belly", "back", "shoulders", "scrubs", "hospital gown"):
        assert word in broll_draw.DRESS_PROMPT