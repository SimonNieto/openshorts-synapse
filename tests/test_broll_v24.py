"""B-roll v24 « on juge des images » (4-oct-2026, the bench only): the store of rendered pictures (broll_store: the
seed from the prompt, a picture never made twice, the dry run, the GPU cap) and the chain on pictures (broll_v24: the
director's and the verifier's prompts of v24, every idea that passed rendered, the mechanical check, the viewer's four
answers and ranking with the face alone, the hero made full screen, the verifier on the winning pictures and the next
one when it refuses). No model and no GPU are called: the calls are faked."""
import json
import os

import pytest

import broll
import broll_check
import broll_ideas
import broll_store
import broll_v20
import broll_v24


# --- the store ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(broll_store, "STORE_DIR", str(tmp_path / "store"))
    return tmp_path


def _maker(calls):
    from PIL import Image

    def make(text, out, size, seed, steps):
        calls.append((text, tuple(size), seed, steps))
        Image.new("RGB", (8, 8), (seed % 255, 10, 10)).save(out)
        return out
    return make


def _renderer(calls, log=None, **kw):
    return broll_store.renderer(_maker(calls), lambda layout: (1152, 720) if layout == "card" else (896, 1600),
                                lambda layout: 8, version="test", log=log, **kw)


class TestTheStore:
    def test_the_seed_comes_from_the_prompt(self):
        assert broll_store.seed_of("a fridge", "card") == broll_store.seed_of("a fridge", "card")
        assert broll_store.seed_of("a fridge", "card") != broll_store.seed_of("a fridge", "hero")
        assert broll_store.seed_of("a fridge", "card") != broll_store.seed_of("a fridge.", "card")
        assert 0 <= broll_store.seed_of("x") < 2 ** 48

    def test_the_key_holds_everything_the_picture_depends_on(self):
        k = broll_store.key("a", (1152, 720), 8, "turbo", 5)
        assert k == broll_store.key("a", [1152, 720], 8, "turbo", 5)
        for other in (("b", (1152, 720), 8, "turbo", 5), ("a", (720, 1152), 8, "turbo", 5),
                      ("a", (1152, 720), 9, "turbo", 5), ("a", (1152, 720), 8, "base", 5),
                      ("a", (1152, 720), 8, "turbo", 6)):
            assert broll_store.key(*other) != k

    def test_a_picture_is_made_once_then_read_back(self, store):
        calls, log = [], []
        render = _renderer(calls, log)
        got, seed = render("a fridge in an alley", str(store / "c0_0.jpg"), "card")
        assert got and seed == broll_store.seed_of("a fridge in an alley", "card") and len(calls) == 1
        k = broll_store.key("a fridge in an alley", (1152, 720), 8, "turbo", seed)
        assert broll_store.get(k) and broll_store.info(k)["prompt"] == "a fridge in an alley"
        assert broll_store.info(k)["version"] == "test" and broll_store.info(k)["seed"] == seed
        again, seed2 = render("a fridge in an alley", str(store / "other.jpg"), "card")
        assert again == str(store / "other.jpg") and os.path.exists(again) and seed2 == seed
        assert len(calls) == 1                                   # no GPU the second time
        assert [x["made"] for x in log] == [True, False] and [x["cached"] for x in log] == [False, True]
        assert render.spent[0] >= 0.0

    def test_a_dry_run_makes_nothing(self, store):
        calls, log = [], []
        render = _renderer(calls, log, dry=True)
        assert render("new prompt", str(store / "x.jpg"), "card") == (None, broll_store.seed_of("new prompt", "card"))
        assert calls == [] and log[0]["made"] is False and log[0]["cached"] is False and log[0]["capped"] is False

    def test_the_gpu_cap_stops_new_pictures_not_the_store(self, store):
        calls, log = [], []
        make = _renderer(calls)
        make("kept before", str(store / "a.jpg"), "card")
        render = _renderer(calls, log, gpu_cap=0.0)
        assert render("kept before", str(store / "b.jpg"), "card")[0]          # from the store: no GPU
        assert render("brand new", str(store / "c.jpg"), "card")[0] is None     # the cap is spent
        assert log[-1]["capped"] is True and len(calls) == 1


# --- the prompts of v24 ------------------------------------------------------------------------------------------------
class TestThePrompts:
    def test_the_directors_two_rules_and_no_risk_field(self):
        flat = " ".join(broll_v24.DA_PROMPT_V24.split())
        assert "the picture shows it WHOLE, doing what the sentence says" in flat
        assert "a detail may sharpen it, never replace it" in flat
        assert "never the instrument that shows it nor the category it belongs to" in flat
        assert "its \"picture\" stands on its own, whole" in flat
        assert "WHAT THE ENGINE (Z-Image) DRAWS BADLY" in flat and "engine_risk" not in flat
        assert "a telescope frame" not in flat and "name what that image SHOWS, never the instrument" in flat
        assert '"picture_b" (the right half alone in plain words' in flat
        assert "<<" not in broll_v24.DA_PROMPT_V24

    def test_production_keeps_its_prompts(self):
        assert "TWO RULES" not in broll_ideas.DA_PROMPT and "Z-Image" not in broll_ideas.DA_PROMPT
        assert "nothing the sentence denies" not in broll_ideas.VERIFIER_PROMPT

    def test_the_verifier_knows_a_negation(self):
        flat = " ".join(broll_v24.VERIFIER_PROMPT_V24.split())
        assert "no figure of speech or set phrase taken literally; nothing the sentence denies" in flat

    def test_the_viewer_never_reads_the_director(self):
        p = broll_v24.CHOOSE_PROMPT
        assert "art director" not in p.lower() and "{moments}" in p and '"{face}"' in p
        for q in ("repeats", "stock", "setting", "contradicts", "full_screen"):
            assert f'"{q}"' in p


# --- the viewer's answer -----------------------------------------------------------------------------------------------
class TestTheViewersAnswer:
    def test_ranked_before_the_face_with_four_no(self):
        assert broll_v24.ranked_before_face(["c0_1.jpg", "C0_0.JPG", "face", "c0_2.jpg"],
                                            ["c0_0.jpg", "c0_1.jpg", "c0_2.jpg"]) == ["c0_1.jpg", "c0_0.jpg"]
        assert broll_v24.ranked_before_face(["face", "c0_0.jpg"], ["c0_0.jpg"]) == []
        assert broll_v24.ranked_before_face(["c0_9.jpg", "c0_0.jpg"], ["c0_0.jpg"]) == ["c0_0.jpg"]

    def test_one_yes_and_the_picture_is_out_whatever_its_rank(self):
        view = {"views": {"c0_0.jpg": {"flags": {"repeats": "yes", "stock": "no", "setting": "no", "contradicts": "no"}},
                          "c0_1.jpg": {"flags": {f: "no" for f in broll_v24.FLAWS4}}},
                "order": ["c0_0.jpg", "c0_1.jpg", "face"]}
        assert broll_v24.verdict_of(view, None) == ("c0_1.jpg", ["c0_1.jpg"])
        assert broll_v24.verdict_of({**view, "order": ["face", "c0_1.jpg"]}, None) == ("face", [])
        assert broll_v24.verdict_of({}, None) == ("face", [])


# --- the whole chain, faked --------------------------------------------------------------------------------------------
WORDS = [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(
    ("you can find these videos of meth heads carrying refrigerators down the street. "
     "It makes people think every idea is a good idea and everything is about them.").split())]
CLIP = {"video_title_for_youtube_short": "Meth strength", "viral_hook_text": "Meth strength is real?"}


def _moment(t, subject="a man hauling a refrigerator", hero=False):
    spec = {"anchor": "carrying", "time": t, "said": "", "worth": 4, "literal": "literal", "kind": "scene",
            "subject": subject, "subject_words": "refrigerators", "subject_b": "", "instrument": "", "count": "1",
            "state": "", "setting": "an alley", "details": "", "people": "one", "person": "anonymous",
            "shot": "medium", "death_near": False, "substance": False, "intake": False, "mood": {}, "hero": hero,
            "role": "point", "idea": "", "notion": "", "light": ""}
    return {"t": t, "anchor": "carrying", "said": "", "dur": 2.5, "hero": hero, "mood": {}, "spec": spec,
            "clip_gravity": "none"}


def _idea(title, kind="scene", hero_ok=False, **kw):
    return {"title": title, "picture": f"{title}, plainly.", "adds": "", "reads": "", "kind": kind,
            "subject": title.lower(), "count": "1", "state": "moving", "setting": "an alley", "details": "dust",
            "people": "one", "person": "anonymous", "shot": "medium", "light": "noon daylight", "hero_ok": hero_ok, **kw}


class Fake:
    """Every call the chain makes, faked: the director, the verifier of the text, the mechanical check, the viewer on
    the pictures and the verifier on the pictures. Keeps them in ``calls``."""

    def __init__(self, ideas, refuse_text=(), mech_bad=(), views=None, post_refuse=(), full_screen="no"):
        self.ideas, self.refuse_text, self.mech_bad = ideas, set(refuse_text), set(mech_bad)
        self.views, self.post_refuse, self.full_screen = views or {}, set(post_refuse), full_screen
        self.calls = []

    def direct(self, moments, words, clip, gravity, shown=(), prompt=None):
        self.calls.append(("da", prompt))
        return {k: {"idea": "the idea", "role": "point", "ideas": list(v), "why": ""} for k, v in self.ideas.items()}

    def verify(self, moments, words, clip, gravity, ideas, prompt=None):
        self.calls.append(("verify", prompt))
        return {(k, i): {"verdict": "refuse" if (k, i) in self.refuse_text else "pass", "reason": "no", "details": "",
                         "flaw": "none"} for k, v in ideas.items() for i, x in enumerate(v) if x}

    def check(self, cands, words, model="sonnet"):
        self.calls.append(("mech", [os.path.basename(c["file"]) for c in cands], model))
        return {os.path.basename(c["file"]): {"sees": "x", "fits": "with", "links": True, "look": 4, "score": 3,
                                              "answers": {"q_subject": "no" if os.path.basename(c["file"]) in self.mech_bad
                                                          else "yes"}} for c in cands}

    def claude_json(self, prompt, schema, **kw):
        names = [os.path.basename(p) for p in kw.get("attach") or []]
        self.calls.append((kw.get("stage"), names, kw.get("reuse", True)))
        if schema is broll_v24.CHOOSE_SCHEMA:
            out = []
            for k, order in self.views.items():
                flags = order.get("flags") or {}
                out.append({"k": k, "order": order["order"], "full_screen": self.full_screen,
                            "views": [{"file": n, "sees": "x", **{f: ("yes" if f in flags.get(n, ()) else "no")
                                                                  for f in broll_v24.FLAWS4}}
                                      for n in names if n.startswith(f"c{k}_")]})
            return {"moments": out}
        if schema is broll_v24.POST_VERIFY_SCHEMA:
            return {"checks": [{"file": n, "sees": "x", "verdict": "refuse" if n in self.post_refuse else "pass",
                                "reason": "a strap" if n in self.post_refuse else ""} for n in names]}
        raise AssertionError("unexpected call")


def _questions(spec):
    return [{"id": "q_subject", "q": "Does the picture show it?", "expect": "yes"}]


@pytest.fixture
def chain(monkeypatch, store):
    def setup(fake, moments, gpu_cap=None):
        monkeypatch.setattr(broll_ideas, "_direct", fake.direct)
        monkeypatch.setattr(broll_ideas, "_verify", fake.verify)
        monkeypatch.setattr(broll_check, "check", fake.check)
        monkeypatch.setattr(broll_check, "_questions", _questions)
        monkeypatch.setattr(broll, "claude_json", fake.claude_json)
        monkeypatch.setattr(broll_ideas, "_lessons", lambda who: "")
        monkeypatch.setattr(broll_ideas, "_clip_lines", lambda clip, g: {"title": "t", "hook": "h", "gravity": g,
                                                                        "grave_line": "", "speakers": "the hosts",
                                                                        "brief": ""})
        monkeypatch.setattr(broll_v20, "_text", lambda spec, layout, prose=None: f"{layout}: {prose or spec['subject']}")
        calls = []
        render = _renderer(calls, gpu_cap=gpu_cap)
        tmp = store / "img"
        tmp.mkdir(exist_ok=True)
        res = broll_v24.run_moments(moments, CLIP, WORDS, "none", render, str(tmp), avoid=(), head=0.0, block=())
        return res, calls
    return setup


class TestTheChain:
    def test_every_idea_that_passed_is_made_and_the_viewer_chooses(self, chain):
        fake = Fake({0: [_idea("Man drags fridge"), _idea("Fridge alone"), _idea("Grip on enamel")]},
                    refuse_text={(0, 2)}, views={0: {"order": ["c0_1.jpg", "c0_0.jpg", "face"]}})
        res, calls = chain(fake, [_moment(5.0)])
        r = res["moments"][0]
        assert [c.get("file") and os.path.basename(c["file"]) for c in r["cands"]] == ["c0_0.jpg", "c0_1.jpg", None]
        assert r["cands"][2]["refused"] == "verifier: no" and len(calls) == 2           # the refused one is never made
        assert [c["prompt"] for c in r["cands"][:2]] == ["card: Man drags fridge, plainly.", "card: Fridge alone, plainly."]
        assert r["winner"] == "c0_1.jpg" and os.path.basename(r["final"]) == "c0_1.jpg" and r["final_layout"] == "card"
        assert r["cands"][1]["view"]["rank"] == 1 and r["cands"][0]["view"]["rank"] == 2
        assert ("da", broll_v24.DA_PROMPT_V24) in fake.calls and ("verify", broll_v24.VERIFIER_PROMPT_V24) in fake.calls
        assert res["gpu_cap"] == broll_v24.CAP_GPU_S and "tokens" in res and res["hero"] is None

    def test_a_picture_the_check_fails_never_reaches_the_viewer(self, chain):
        fake = Fake({0: [_idea("A"), _idea("B")]}, mech_bad={"c0_0.jpg"}, views={0: {"order": ["c0_1.jpg", "face"]}})
        res, _calls = chain(fake, [_moment(5.0)])
        r = res["moments"][0]
        assert r["cands"][0]["mech"]["why"] == "wrong subject" and r["cands"][1]["mech"]["why"] == ""
        choose = next(c for c in fake.calls if c[0] == "broll_choose")
        assert choose[1] == ["c0_1.jpg"]

    def test_the_face_alone_wins_when_the_viewer_says_so_or_finds_a_flaw(self, chain):
        fake = Fake({0: [_idea("A")], 1: [_idea("B")]},
                    views={0: {"order": ["face", "c0_0.jpg"]},
                           1: {"order": ["c1_0.jpg", "face"], "flags": {"c1_0.jpg": ("stock",)}}})
        res, _calls = chain(fake, [_moment(2.0), _moment(9.0)])
        assert [r["final"] for r in res["moments"]] == ["face", "face"]
        assert not any(c[0] == "broll_postverify" for c in fake.calls)            # nothing to verify

    def test_the_verifier_on_the_picture_hands_the_moment_to_the_next_one(self, chain):
        fake = Fake({0: [_idea("A"), _idea("B"), _idea("C")]}, post_refuse={"c0_0.jpg"},
                    views={0: {"order": ["c0_0.jpg", "c0_2.jpg", "face", "c0_1.jpg"]}})
        res, _calls = chain(fake, [_moment(5.0)])
        r = res["moments"][0]
        assert os.path.basename(r["final"]) == "c0_2.jpg"
        assert r["post"]["c0_0.jpg"]["verdict"] == "refuse" and r["post"]["c0_2.jpg"]["verdict"] == "pass"
        verifies = [c for c in fake.calls if c[0] == "broll_postverify"]
        assert [v[1] for v in verifies] == [["c0_0.jpg"], ["c0_2.jpg"]]

    def test_refused_twice_is_the_face(self, chain):
        fake = Fake({0: [_idea("A"), _idea("B")]}, post_refuse={"c0_0.jpg", "c0_1.jpg"},
                    views={0: {"order": ["c0_0.jpg", "c0_1.jpg", "face"]}})
        res, _calls = chain(fake, [_moment(5.0)])
        assert res["moments"][0]["final"] == "face"

    def test_the_hero_is_made_full_screen_from_the_winning_idea(self, chain):
        fake = Fake({0: [_idea("Wide alley scene", hero_ok=True)]}, full_screen="yes",
                    views={0: {"order": ["c0_0.jpg", "face"]}})
        res, calls = chain(fake, [_moment(8.0, hero=True)])
        r = res["moments"][0]
        assert res["hero"] == 0 and r["final_layout"] == "hero" and os.path.basename(r["final"]) == "h0_0.jpg"
        assert r["hero_render"]["prompt"] == "hero: Wide alley scene, plainly." and r["hero_render"]["mech"] == ""
        assert [c[1] for c in calls] == [(1152, 720), (896, 1600)]
        verify = next(c for c in fake.calls if c[0] == "broll_postverify")
        assert verify[1] == ["h0_0.jpg"]

    def test_no_hero_without_the_viewers_full_screen_or_the_directors_hero_ok(self, chain):
        for ideas, fs in (([_idea("A", hero_ok=True)], "no"), ([_idea("A", hero_ok=False)], "yes")):
            fake = Fake({0: ideas}, full_screen=fs, views={0: {"order": ["c0_0.jpg", "face"]}})
            res, calls = chain(fake, [_moment(8.0, hero=True)])
            assert res["hero"] is None and res["moments"][0]["final_layout"] == "card" and len(calls) <= 1

    def test_the_first_ideas_of_every_moment_are_made_first(self, chain):
        fake = Fake({0: [_idea("A0"), _idea("A1")], 1: [_idea("B0"), _idea("B1")]},
                    views={0: {"order": ["c0_0.jpg", "face"]}, 1: {"order": ["c1_0.jpg", "face"]}})
        _res, calls = chain(fake, [_moment(2.0), _moment(9.0)])
        assert [c[0] for c in calls] == ["card: A0, plainly.", "card: B0, plainly.", "card: A1, plainly.",
                                         "card: B1, plainly."]

    def test_a_spent_gpu_cap_makes_nothing_new(self, chain):
        fake = Fake({0: [_idea("A0"), _idea("A1")]}, views={0: {"order": ["c0_0.jpg", "face"]}})
        res, calls = chain(fake, [_moment(2.0)], gpu_cap=-1.0)
        assert calls == [] and all(c.get("file") is None for r in res["moments"] for c in r["cands"])
        assert res["moments"][0]["final"] == "face"

    def test_the_result_is_json(self, chain):
        fake = Fake({0: [_idea("A")]}, views={0: {"order": ["c0_0.jpg", "face"]}})
        res, _calls = chain(fake, [_moment(5.0)])
        json.dumps(res)
        assert broll_v20.PROSE is False                                    # put back after the clip
        assert "moment(s) with a picture" in broll_v24.summary_line(res)
