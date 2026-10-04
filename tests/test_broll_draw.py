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
    def setup(moments, ideas, verdicts, trace=True):
        calls = Calls(ideas, verdicts)
        monkeypatch.setattr(broll_ideas, "_call", calls)
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


def test_the_charter_suffix_is_added_word_for_word_and_the_hero_is_full_screen(chain):
    _text, suffix, _banc = broll_draw.charter()
    assert suffix.startswith("Premium editorial illustration: bold confident ink linework")
    cands, _m, made, calls = chain([_moment(2.0, hero=True), _moment(9.0)], ["A man under a fridge.", "A dish."],
                                   ["pass", "pass"])
    assert [(t, layout) for t, _f, layout in made] == [(f"A man under a fridge. {suffix}", "hero"),
                                                        (f"A dish. {suffix}", "card")]
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
