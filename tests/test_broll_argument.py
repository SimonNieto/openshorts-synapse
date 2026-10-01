"""The visual argument and the specificity test (B-roll v2, chantier K): the editor names the one thing the
viewer must see to believe the thesis and plans the set as a sequence that builds it; an image that would do for
any clip about the same noun is refused by the editor and marked down by the reviewer. No model is called."""
import pytest

import ai_brain
import broll


def _words(text, step=0.42, dur=0.4):
    out, t = [], 0.0
    for w in text.split():
        out.append({"text": w, "start": round(t, 2), "end": round(t + dur, 2)})
        t += step
    return out


TEXT = ("Well you know this is the setup for the story. In 1998 the soldiers were given two gallons of water, "
        "and then they marched all night long. It was brutal. Nobody spoke for hours but the drill went on and on "
        "until sunrise came and the camp woke up again and the sergeant finally smiled at them all. They never "
        "forgot that long night in the desert and the lesson it taught them about discipline.")


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(broll, "NOTION_DIR", str(tmp_path / "notions"))
    monkeypatch.setattr(broll, "HERO_TAKES", 1)   # the hero's takes have their own tests
    monkeypatch.setattr(ai_brain, "EPISODE_BRIEF", None)
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    monkeypatch.setenv("BROLL_NOTION_MEMORY", "0")


class TestTheEditor:
    def _plan(self, monkeypatch, data=None, **kw):
        seen = {}
        monkeypatch.setattr(broll, "claude_json", lambda prompt, schema, **k: seen.update(prompt=prompt, schema=schema) or (data or {"moments": []}))
        moments = broll.plan_with_claude({}, _words(TEXT), 4, [], hero=True, **kw)
        return seen, moments

    def test_the_editor_is_asked_for_the_argument_the_sequence_and_what_each_image_proves(self, monkeypatch):
        seen, _m = self._plan(monkeypatch)
        p = seen["prompt"]
        assert '"visual_argument": the ONE thing a viewer must SEE to believe the thesis' in p
        assert "documentary sequence that builds" in p and "no two images make the same point" in p
        assert '"idea": what this image PROVES or makes felt for the thesis' in p
        assert "SPECIFICITY TEST: if the same picture would do for any other clip about the same noun" in p
        assert p.index("NEVER THE AI CLICHÉ") < p.index("SPECIFICITY TEST") < p.index("Never: something already visible")
        assert seen["schema"]["properties"]["visual_argument"] == {"type": "string"}

    def test_the_argument_lands_on_every_moment(self, monkeypatch, capsys):
        words = _words(TEXT)
        idx = {w["text"]: i for i, w in enumerate(words)}
        data = {"thesis": "T", "visual_argument": "  A dented canteen,  all they had. ",
                "moments": [{"anchor": "soldiers", "time": words[idx["soldiers"]]["start"], "image_prompt": "x"},
                            {"anchor": "drill", "time": words[idx["drill"]]["start"], "image_prompt": "y"}]}
        _s, moments = self._plan(monkeypatch, data)
        assert len(moments) == 2 and all(m["argument"] == "A dented canteen, all they had." for m in moments)
        assert "Visual argument: A dented canteen" in capsys.readouterr().out
        _s, moments = self._plan(monkeypatch, {"moments": [{"anchor": "soldiers", "time": words[11]["start"], "image_prompt": "x"}]})
        assert moments[0]["argument"] == ""


class TestTheArtDirector:
    def test_the_director_hears_the_argument(self):
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "s", "hero": True, "thesis": "T", "argument": "A dented canteen."}]
        text = broll._art_prompt(ms, {"video_title_for_youtube_short": "Title"}, "h")
        assert 'THE CLIP: title "Title"; thesis: T; the visual argument (what the viewer must SEE to believe it, the hero\'s job): A dented canteen.' in text
        ms[0]["argument"] = ""
        assert 'thesis: T\n' in broll._art_prompt(ms, {"video_title_for_youtube_short": "Title"}, "h")


class TestTheReviewer:
    def test_the_reviewer_applies_the_specificity_test(self):
        text = broll.REVIEW_PROMPT.format(frame=broll._review_frame([{"layout": "card"}]), items="- x")
        assert "SPECIFICITY TEST: a picture that would do for any other clip about the same noun" in text
        assert text.index("SOUND-OFF TEST") < text.index("SPECIFICITY TEST") < text.index("WRONG FACTS")
