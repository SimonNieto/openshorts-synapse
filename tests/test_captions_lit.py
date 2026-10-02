"""The premium captions since 2-oct-2026: under the mouth of the premium
framing (66.4 % of the height) and the spoken word lit (viral_fx._lit_word).
What the ASS file says, on the real words of JRE #2515 clip 1."""
import re

import viral_fx

RAW = [("reality.", 0.0, 0.08), ("Have", 0.08, 0.3), ("you", 0.3, 0.42), ("ever", 0.42, 0.62), ("seen", 0.62, 0.8),
       ("the", 0.8, 0.94), ("comparison", 0.94, 1.34), ("between", 1.34, 1.82), ("the", 1.82, 2.48),
       ("universe", 2.48, 2.96), ("itself", 2.96, 3.48), ("and", 3.48, 4.1), ("human", 4.1, 4.9),
       ("neural", 4.9, 5.18), ("tissue?", 5.18, 5.54)]
WORDS = [{"text": t, "start": s, "end": e} for t, s, e in RAW]
TOPIC = viral_fx.topic_words("Does the universe actually look like a human brain cell?",
                             "The universe and a brain cell look identical")
ACCENT = viral_fx._ass_color("#FFD84D")


def _lines(ass, style):
    return [l for l in ass.splitlines() if l.startswith("Dialogue:") and f",{style},," in l]


def _text(line):
    return line.split(",", 9)[9]


def _blocks(line):
    """(override block, word) of every word of a lit caption line."""
    return re.findall(r"\{(\\c&HFFFFFF&[^}]*)\}([^{ ]+)", _text(line))


def _build(preset):
    return viral_fx.build_ass(WORDS, preset, watermark="@thesynapsecut", topic=TOPIC)


class TestPlace:
    def test_every_caption_sits_under_the_mouth(self):
        ass, groups = _build("premium")
        lines = _lines(ass, "Main")
        assert len(lines) == len(groups) > 3
        assert all("\\pos(540,1275)" in l for l in lines)
        assert 0.66 < 1275 / 1920 < 0.67

    def test_the_watermark_follows_the_caption(self):
        ass, _ = _build("premium")
        assert all("\\pos(540,1343)" in l for l in _lines(ass, "Mark"))


class TestLit:
    def test_each_word_lights_up_the_moment_it_is_said(self):
        ass, groups = _build("premium")
        for line, g in zip(_lines(ass, "Main"), groups):
            blocks = _blocks(line)
            assert [w for _, w in blocks] == [x["text"].upper() for x in g]
            for (blk, _), w in zip(blocks, g):
                t0, t1 = map(int, re.search(r"\\t\((\d+),(\d+),", blk).groups())
                assert abs(t0 - (w["start"] - g[0]["start"]) * 1000) <= 1
                assert t1 - t0 == viral_fx.LIT_RISE

    def test_a_word_waits_dimmed_edge_and_shadow_included_then_gets_the_style_back(self):
        ass, _ = _build("premium")
        for line in _lines(ass, "Main"):
            for blk, _ in _blocks(line):
                assert blk.startswith("\\c&HFFFFFF&\\1a&H94&\\3a&HC3&\\4a&HD4&\\t(")
                assert "\\1a&H00&\\3a&H70&\\4a&H99&" in blk.split("\\t(", 1)[1]
        # \alpha would leave the edge and the shadow solid once the word is lit.
        assert "\\alpha" not in ass

    def test_only_the_key_word_turns_to_the_accent_and_only_when_said(self):
        ass, _ = _build("premium")
        nat, _ = _build("natural")
        coloured = 0
        for line, nline in zip(_lines(ass, "Main"), _lines(nat, "Main")):
            words = _text(nline).split("}", 1)[1].split(" ")     # past the line's own override block
            nat_key = [i for i, w in enumerate(words) if ACCENT in w]
            blocks = _blocks(line)
            lit_key = [i for i, (blk, _) in enumerate(blocks) if ACCENT in blk]
            assert lit_key == nat_key
            for i in lit_key:
                assert blocks[i][0].index(ACCENT) > blocks[i][0].index("\\t(")   # reached, not set
            coloured += len(lit_key)
        assert coloured >= 2

    def test_natural_keeps_its_plain_fade(self):
        nat, _ = _build("natural")
        assert "\\t(" not in nat and "\\1a" not in nat
        assert all("\\pos(540,1180)" in l for l in _lines(nat, "Main"))

    def test_the_dimmed_alphas(self):
        assert [viral_fx._dimmed(a, viral_fx.LIT_DIM) for a in viral_fx.LIT_ALPHAS] == [0x94, 0xC3, 0xD4]
        assert all(viral_fx._dimmed(a, 1.0) == a for a in viral_fx.LIT_ALPHAS)
        assert all(viral_fx._dimmed(a, 0.0) == 255 for a in viral_fx.LIT_ALPHAS)


class TestCaptionsWaitForTheHook:
    """Since 2-oct-2026 the captions start once the hook has left the frame."""

    def test_the_docline_hook_is_gone_after_its_exit(self):
        import hooks
        hook = {"text": "The universe and a brain cell look identical", "style": "docline",
                "duration_seconds": 3.3}
        exit_len = max(hooks.DOCLINE["out"], *(a + b for a, b in (hooks.DOCLINE["rule_out"],
                                                                    hooks.DOCLINE["eyebrow_out"])))
        assert abs(hooks.hook_gone_at(hook) - (3.3 + exit_len)) < 1e-9
        assert abs(hooks.hook_gone_at(hook) - 3.85) < 1e-9

    def test_other_hooks_go_at_their_duration_and_none_waits_for_nothing(self):
        import hooks
        assert hooks.hook_gone_at({"text": "x", "style": "bold", "duration_seconds": 5}) == 5.0
        assert hooks.hook_gone_at({"text": "x", "style": "classic"}) == 0.0    # stays all clip
        assert hooks.hook_gone_at(None) == 0.0
        assert hooks.hook_gone_at({"text": " ", "style": "docline", "duration_seconds": 3.3}) == 0.0

    def test_no_caption_before_the_hook_is_gone(self):
        ass, groups = viral_fx.build_ass(WORDS, "premium", topic=TOPIC, after=3.85)
        starts = [l.split(",")[1] for l in _lines(ass, "Main")]
        assert starts and all(s >= "0:00:03.85" for s in starts)
        assert groups[0][0]["text"] == "human"              # the first word said after 3.85 s
        assert all(w["start"] >= 3.85 for g in groups for w in g)

    def test_without_a_hook_nothing_changes(self):
        assert viral_fx.build_ass(WORDS, "premium", topic=TOPIC, after=0.0) == \
            viral_fx.build_ass(WORDS, "premium", topic=TOPIC)
