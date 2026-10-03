"""B-roll v19 (3-oct-2026): the inside of a body is drawn in ONE drawing per episode (the bible's "drawing", else the
house's), with its picture's light and palette and no camera word; a figure of speech is a thing that does not exist in
the clip's story; the bench fails a clip under the minimum. No model is called."""
import pytest

import ai_brain
import broll
import broll_bench
import visual_mood

D = ("Painted in opaque water-based colour with a fine dry brush: thin warm outlines where two forms meet, volumes "
     "modelled in three soft values, a faint tooth of paper in the flat areas, forms simplified to their readable "
     "masses, colour laid in muted washes close to the true colours, the whole frame painted edge to edge.")
LONG = "A human brain seen from above, its two halves and their folds, resting on a plain surface. " * 3


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    broll.FILTERS.clear()
    monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", None)
    monkeypatch.delenv("BROLL_DRAWING", raising=False)
    yield
    broll.FILTERS.clear()


class TestOneDrawingPerEpisode:
    def test_the_bible_writes_it_in_the_positive_or_it_is_refused(self):
        rules = " ".join(ai_brain.bible_rules().split())
        assert '"drawing": the ONE way this episode draws what is never photographed' in rules
        assert "drawing" in ai_brain.BIBLE_SCHEMA["required"]
        assert ai_brain._clean_drawing(D) == (D, "")
        assert ai_brain._clean_drawing(D + " Never a cartoon.") == (D, "")       # the negation goes
        assert ai_brain._clean_drawing("A soft cartoon look. " + D) == ("", "names cartoon")
        assert ai_brain._clean_drawing("Pencil lines.") == ("", "2 words")
        assert ai_brain._clean_drawing(broll.DRAWING_HOUSE) == (broll.DRAWING_HOUSE, "")

    def test_every_drawn_picture_gets_the_same_drawing(self, monkeypatch):
        assert broll.DRAWING_HOUSE in broll._image_text(LONG, "photo", art=True, body=True)      # no bible: the house's
        monkeypatch.setattr(ai_brain, "EPISODE_BIBLE", {"drawing": D})
        a = broll._image_text(LONG, "photo", art=True, body=True)
        b = broll._image_text(LONG.replace("brain", "nerve"), "photo", art=True, body=True)
        assert D in a and D in b and D not in broll._image_text(LONG, "photo", art=True)
        monkeypatch.setenv("BROLL_DRAWING", "house")
        assert broll.episode_drawing() == broll.DRAWING_HOUSE
        for text in (broll.BODY_RULE, broll.BODY_LINE, broll.REVIEW_PROMPT):
            assert "animated film" not in " ".join(text.split())

    def test_it_keeps_its_light_and_palette_and_drops_the_camera(self):
        m = visual_mood.clean({"valence": "grim", "intensity": "charged"})
        line = visual_mood.art_line(m, drawn=True)
        assert "medium:" not in line and "lens:" not in line and "light:" in line and "palette:" in line
        assert "photograph" not in visual_mood.sentence(m, drawn=True)
        assert visual_mood.sentence(m).startswith("A documentary photograph")
        ms = [{"t": 5.0, "anchor": "a", "prompt": "p", "subject": "brain", "inside_body": True, "mood": m}]
        art = broll._art_prompt(ms, {})
        assert broll.BODY_LINE.format(drawing=broll.DRAWING_HOUSE) in art and "lens:" not in art.split("- #0 ")[1]


class TestFiguresAndTheMinimum:
    def test_a_figure_of_speech_does_not_exist_in_the_story(self):
        text = " ".join(broll.FLAGS_RULE.split())
        assert "does not exist in the story the clip tells" in text and "read the sentence before" in text

    def test_the_bench_has_a_minimum(self):
        assert broll_bench.MIN_PER_CLIP == 2
