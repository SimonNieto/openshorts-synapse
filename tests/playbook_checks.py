"""Synapse Cut playbook (beta): prompts on/off, credit line, name check, hook-start alignment
without the V2 punchline, per-clip JSON, profile -> env. No AI call, no token.

Run: docker exec -w /app openshorts-backend python tests/playbook_checks.py"""
import json, os, sys, tempfile
# Run from anywhere: the repo root is importable and the working directory
# (main.py loads yolov8n.pt relative to it). tests/test_playbook.py runs this
# file in its own process: it patches module functions and env vars.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.pop("SYNAPSE_PLAYBOOK", None)
import gemini_worker as gw
import playbook
import plus
import rework

SRC = "386484dc-1336-48e8-a068-275ed76ae125_Joe Rogan Experience #2553 - Andrew Huberman-002.mkv"
BRIEF = {"speakers": [{"role": "host", "name": "unknown"}, {"role": "guest", "name": "Andrew Huberman"}]}

# --- prompt texts -----------------------------------------------------------------
t = gw.QUESTION_TITLE_ADDENDUM
for must in ("question", "NO NAMES", "suicide", "self-harm", "educational or preventive", "max 60"):
    assert must in t, must
assert "hook_line" in gw.PLAYBOOK_DETAIL_ADDENDUM and "topic_bucket" in gw.PLAYBOOK_DETAIL_ADDENDUM
assert "WHAT TRAVELS" not in gw.PLAYBOOK_DETAIL_ADDENDUM, "the playbook must not carry V2's topic preferences"
for must in ("MUST START WITH Can, Is, Does, Are, Do, Will or Should", "Can X make you Y?", "Is X actually Y?",
             "Does X really Y?", "1 in 6", "FORBIDDEN", "NAME THE SUBJECT", "OWN ANSWER"):
    assert must in t, must
assert "`start` IS THE MOMENT `hook_line` BEGINS" in gw.PLAYBOOK_DETAIL_ADDENDUM
assert "{max_secs}" in gw.PLAYBOOK_DETAIL_ADDENDUM, "main.py fills the max length in"
f = gw.DetailResponsePlaybook.model_json_schema()
item = f["$defs"]["DetailClipModelPlaybook"]["properties"]
assert {"hook_line", "topic_bucket", "video_title_for_youtube_short"} <= set(item)

# --- hook grounding / regenerate get the rule only when on ------------------------
import hook_grounding
hook_grounding.frames_at = lambda *a, **k: [b"jpg"]
tr = {"language": "en", "segments": [{"start": 0, "end": 3, "text": "hi", "words": [{"word": "hi", "start": 0, "end": 1}]}]}
clip = {"viral_hook_text": "x", "video_title_for_youtube_short": "y", "layout_ranges": []}
assert "SYNAPSE CUT" not in hook_grounding.request("c.mp4", clip, tr, 0, 30)[1]
os.environ["SYNAPSE_PLAYBOOK"] = "1"
assert "SYNAPSE CUT" in hook_grounding.request("c.mp4", clip, tr, 0, 30)[1]
os.environ.pop("SYNAPSE_PLAYBOOK")

seen = []
rework._generate_json_with_fallback = lambda prompt, *a, **k: seen.append(prompt) or {
    "viral_hook_text": "h", "video_title_for_youtube_short": "Can this happen?",
    "video_description_for_tiktok": "d", "video_description_for_instagram": "d"}
rework.generate_clip_copy("some words", "en", None)
rework.generate_clip_copy("some words", "en", None, playbook=True)
assert "SYNAPSE CUT" not in seen[0] and "SYNAPSE CUT" in seen[1] and "question to the viewer" in seen[1]

# --- credit line -------------------------------------------------------------------
assert playbook.episode_title(SRC) == "Joe Rogan Experience #2553 - Andrew Huberman"
c = playbook.credit_line(SRC, BRIEF)
assert c == "Clip from Joe Rogan Experience, Ep. 2553 - Andrew Huberman. All rights to the original creators.", c
assert "#" not in c, "a '#2553' would be taken for a hashtag by the publisher"
c2 = playbook.credit_line(SRC, BRIEF, show="The Joe Rogan Experience")
assert c2.startswith("Clip from The Joe Rogan Experience, Ep. 2553 - Andrew Huberman."), c2
c3 = playbook.credit_line("x_Some Talk-001.mkv", {"speakers": [{"name": "Jane Doe"}]})
assert c3 == "Clip from x Some Talk, with Jane Doe. All rights to the original creators.", c3
body = playbook.with_credit("Tease. Would you notice? #brain", c)
assert body.split("\n")[0] == c and body.endswith("#brain")
assert playbook.with_credit(body, c) == body, "a second pass must not stack two credit lines"

# --- name check ----------------------------------------------------------------------
toks = playbook.name_tokens(SRC, BRIEF)
assert {"joe", "rogan", "andrew", "huberman"} <= set(toks), toks
assert "experience" not in toks
assert playbook.names_in("Huberman's take on sleep?", toks) == ["huberman"]
assert playbook.names_in("Can a brain tumor make you a killer?", toks) == []

# --- prepare + export ------------------------------------------------------------------
shorts = [{"start": 100.0, "end": 123.5, "video_title_for_youtube_short": "Huberman Explains Stress",
           "video_description_for_tiktok": "A. Why? #x", "video_description_for_instagram": "B. Why? #y",
           "topic_bucket": "made_up", "predicted_score": 81, "hook_line": "Stress rewires you.",
           "hook_aligned": True, "viral_hook_text": "Can stress rewire you?"}]
tokens = playbook.prepare(shorts, SRC, BRIEF)
s = shorts[0]
assert s["video_description_for_tiktok"].startswith("Clip from Joe Rogan Experience")
assert s["topic_bucket"] == "other" and s["title_has_name"] is True and s["moment_id"].startswith("m_")
assert s["moment_id"] == playbook.moment_id(SRC, 100.0, 123.5)
d = tempfile.mkdtemp()
p = playbook.export_clip(s, d, "ep_clip_1.mp4", tokens)
out = json.load(open(p, encoding="utf-8"))
for k in ("moment_id", "duration", "topic_bucket", "hook_sentence", "title", "title_has_name", "score"):
    assert k in out, k
assert out["duration"] == 23.5 and out["hook_sentence"] == "Stress rewires you." and out["score"] == 81
playbook.update_export(d, "ep_clip_1.mp4", {**s, "video_title_for_youtube_short": "Can stress rewire you?"}, tokens)
out = json.load(open(p, encoding="utf-8"))
assert out["title"] == "Can stress rewire you?" and out["title_has_name"] is False
# hook_sentence falls back to the first sentence heard when the cut was not aligned
tr2 = {"segments": [{"words": [{"word": w, "start": 100 + i * 0.3} for i, w in enumerate(
    "So this is it. Next one.".split())]}]}
assert playbook.hook_sentence({"start": 100.0}, tr2) == "So this is it."

# --- title format (no AI): the 4 titles of the Ron White-001 test all fail -------------------------
bad = {"How did this show sell out Madison Square Garden twice?": "starts with 'how'",
       "Why is one show compared to getting a sitcom deal?": "subject not named ('one show')",
       "What happens if you bomb before you're ready?": "starts with 'what'",
       "How could you tell who'd made it in comedy?": "starts with 'how'"}
for title, why in bad.items():
    probs = playbook.title_problems(title, why_slot=True)
    assert any(why in p for p in probs), (title, probs)
for title in ("Can a brain tumor make you a killer?", "Is kratom really as harmless as people think?",
              "Does cannabis really cause psychosis? 🧠", "Should you quit when learning gets hard?",
              "Are comedy clubs the new sitcom deal?", "Do cold showers really lower stress?",
              "Will a small comedy show sell out Madison Square Garden?"):
    assert playbook.title_problems(title) == [], (title, playbook.title_problems(title))
assert playbook.title_problems("Can he really do that?") and playbook.title_problems("Is this guy right?")
assert playbook.title_problems("Is kratom safe") == ["not a question"]
assert "characters" in playbook.title_problems("Can " + "a very long title " * 5 + "?")[0]
# 'Why': 1 in 6 — first one of a 6-clip batch allowed, a second one flagged, none in a batch under 6
batch = [{"video_title_for_youtube_short": t} for t in
         ("Why do some people hear voices?", "Why does sleep matter?", "Can stress rewire you?",
          "Is sleep a drug?", "Does fear shrink the brain?", "Can a habit rewire you?")]
playbook.assign_why_slots(batch)
assert [playbook.check_format(c) for c in batch] == [True, False, True, True, True, True], batch
assert "too many 'Why'" in batch[1]["title_format_issues"][0]
three = [{"video_title_for_youtube_short": t} for t in
         ("Why do some people hear voices?", "Can stress rewire you?", "Is sleep a drug?")]
playbook.assign_why_slots(three)
assert playbook.check_format(three[0]) is False, "no 'Why' slot under 6 clips"
solo = [{"video_title_for_youtube_short": "Why do some people hear voices?"}]
playbook.assign_why_slots(solo)
assert playbook.check_format(solo[0]) is False
# prepare() flags it, export writes it
sh = [{"start": 1.0, "end": 30.0, "video_title_for_youtube_short": "How did this show sell out?",
       "video_description_for_tiktok": "a", "video_description_for_instagram": "b"}]
tk = playbook.prepare(sh, SRC, BRIEF)
assert sh[0]["title_format_ok"] is False
d3 = tempfile.mkdtemp()
o = json.load(open(playbook.export_clip(sh[0], d3, "f_clip_1.mp4", tk), encoding="utf-8"))
assert o["title_format_ok"] is False and o["title_format_issues"], o

# --- profile -> env -----------------------------------------------------------------------
env = plus.job_env({"name": "t", "playbook_show": "The Joe Rogan #1 Experience"})
assert env["SYNAPSE_PLAYBOOK"] == "1" and env["PLAYBOOK_SHOW"] == "The Joe Rogan 1 Experience"
env = plus.job_env({"name": "t", "beta": {"playbook_show": "Old Block"}})
assert env["PLAYBOOK_SHOW"] == "Old Block", "the show's name of an old profile (beta block) still counts"
env = plus.job_env({"name": "t"})
assert env["SYNAPSE_PLAYBOOK"] == "1" and "PLAYBOOK_SHOW" not in env, "the playbook is the house recipe"

# --- start on the hook WITHOUT the V2 punchline end (main.py) ---------------------------------
import main
W = [{"w": w, "s": 10 + i * 0.5, "e": 10 + i * 0.5 + 0.4} for i, w in enumerate(
    ("so um anyway your brain can lie to you. it happens every day to everyone and "
     "nobody notices it at all until it is far too late for them. that is the scary part. yeah").split())]
base = {"start": 10.0, "end": 40.0, "hook_line": "your brain can lie to you.", "punchline": "that is the scary part."}
a = dict(base)
main.align_hook_and_punchline(a, W, 15, 60, punchline=False)
assert a["hook_aligned"] and a["start"] == round(W[3]["s"] - 0.08, 3), a
assert a["end"] == 40.0 and "punchline_time" not in a, "playbook alone must keep the end"
b = dict(base)
main.align_hook_and_punchline(b, W, 15, 60)
assert "punchline_time" in b, "v2 behaviour unchanged"

# --- playbook start: hook up to 15 s back, end moved earlier onto a sentence end ----------------
def mk(text):
    return [{"w": w, "s": i * 0.5, "e": i * 0.5 + 0.4} for i, w in enumerate(text.split())]

FILL = "it happens to people every day without them knowing. "
P = mk("this is the intro part of the talk. your brain can lie to you. " + FILL * 30)
hook_s = P[8]["s"]                                        # "your" at 4.0 s
c = {"start": 17.0, "end": 75.0, "hook_line": "your brain can lie to you."}   # hook 13 s before the start
main.align_hook_and_punchline(c, P, 15, 60, punchline=False, playbook=True)
assert c["hook_aligned"] and c["start"] == round(hook_s - 0.08, 3), c
assert c["end"] - c["start"] <= 60 and c.get("end_fit_for_hook"), c
last = max(i for i, w in enumerate(P) if w["e"] <= c["end"])
assert P[last]["w"].endswith("."), "the moved end must land on a sentence end"
assert not c.get("start_mid_sentence")

# 20 s lookback (Ron White-001 clip 3 had its hook 16.0 s before the start): 18 s is found, 21 s is not
assert main.PLAYBOOK_HOOK_LOOKBACK == 20.0
c = {"start": hook_s + 18.0, "end": hook_s + 55.0, "hook_line": "your brain can lie to you."}
main.align_hook_and_punchline(c, P, 15, 60, punchline=False, playbook=True)
assert c["hook_aligned"] and c["start"] == round(hook_s - 0.08, 3), c
c = {"start": hook_s + 21.0, "end": hook_s + 55.0, "hook_line": "your brain can lie to you."}
main.align_hook_and_punchline(c, P, 15, 60, punchline=False, playbook=True)
assert c["hook_aligned"] is False, c

# the hook fits without touching the end
c = {"start": 9.0, "end": 40.0, "hook_line": "your brain can lie to you."}
main.align_hook_and_punchline(c, P, 15, 60, punchline=False, playbook=True)
assert c["hook_aligned"] and c["end"] == 40.0 and not c.get("end_fit_for_hook"), c

# no usable hook_line, cut mid-sentence: back to the start of that sentence
c = {"start": 21.2, "end": 50.0, "hook_line": "words that are not in the transcript"}
assert not main._opens_sentence(P, next(i for i, w in enumerate(P) if w["s"] >= 21.15)), "setup: cut mid-sentence"
main.align_hook_and_punchline(c, P, 15, 60, punchline=False, playbook=True)
k = next(i for i, w in enumerate(P) if w["s"] >= c["start"] - 0.05)
assert c["hook_aligned"] is False and not c.get("start_mid_sentence"), c
assert c["start"] < 21.2 and main._opens_sentence(P, k), (c, P[k])

# impossible (one long unpunctuated run, no pause): flagged, never silent
R = mk("word " * 200)
c = {"start": 40.2, "end": 70.0, "hook_line": ""}
main.align_hook_and_punchline(c, R, 15, 60, punchline=False, playbook=True)
assert c["hook_aligned"] is False and c["start_mid_sentence"] is True, c
impossible = c
# fillers: "I mean" is skipped as a pair, the "I" of "I wish" is never cut off
Q = mk("that was it. I wish I had been told this in the third grade. " + FILL * 8)
c = {"start": 1.4, "end": 40.0, "hook_line": "I wish I had been told this in the third grade."}
main.align_hook_and_punchline(c, Q, 15, 60, punchline=False, playbook=True)
assert c["start"] == round(Q[3]["s"] - 0.08, 3), ("must open on 'I wish'", c)
Q = mk("that was it. I mean, the entire book says it. " + FILL * 8)
c = {"start": 1.4, "end": 40.0, "hook_line": "I mean, the entire book says it."}
main.align_hook_and_punchline(c, Q, 15, 60, punchline=False, playbook=True)
assert c["start"] == round(Q[5]["s"] - 0.08, 3), ("'I mean,' skipped as a pair", c)

d2 = tempfile.mkdtemp()
out = json.load(open(playbook.export_clip({**impossible, "moment_id": "m_x"}, d2, "x_clip_1.mp4", []),
                     encoding="utf-8"))
assert out["hook_aligned"] is False and out["start_mid_sentence"] is True

# --- off-limits topics: in the scoring AND the clip-choice prompts, playbook only ------------------
import inspect
for word in ("politics", "abortion", "religion", "elections", "guns"):
    assert word in gw.SAFETY_TOPICS_ADDENDUM, word
os.environ.pop("SYNAPSE_PLAYBOOK", None)
assert main.playbook_score_rules() == "" and main.playbook_detail_rules(60) == "", "off = prompts unchanged"
os.environ["SYNAPSE_PLAYBOOK"] = "1"
assert gw.SAFETY_TOPICS_ADDENDUM in main.playbook_score_rules()
detail = main.playbook_detail_rules(60)
assert gw.SAFETY_TOPICS_ADDENDUM in detail and gw.QUESTION_TITLE_ADDENDUM in detail
assert "{max_secs}" not in detail and "60s" in detail
os.environ.pop("SYNAPSE_PLAYBOOK")
src = inspect.getsource(main.get_viral_clips)
assert "+ playbook_score_rules() +" in src, "the scoring prompt (both paths) must carry the block"
assert "prompt += playbook_detail_rules(max_secs)" in src, "the clip-choice prompt must carry the block"

# --- on-screen hook: never the title again ------------------------------------------------------------
for must in ("NEVER REPHRASES THE TITLE", "Max 8 words", "Not a", "question", "No name",
             "Most doctors won't tell you this."):
    assert must in gw.QUESTION_TITLE_ADDENDUM, must
# the 4 hooks of the Ron White-002 test all repeat their title
for title, hook in (("Should men be afraid of testosterone therapy as they age?",
                     "Should you be afraid of testosterone therapy?"),
                    ("Can elite athletes really master golf that fast?",
                     "Can elite athletes really pick up golf overnight?"),
                    ("Is the most offensive comedian actually just doing satire?",
                     "Is the most offensive comedy just satire?"),
                    ("Is late-term abortion as common as people fear?",
                     "Is late-term abortion as common as people think?")):
    c = {"video_title_for_youtube_short": title, "viral_hook_text": hook}
    assert playbook.check_hook(c) is True, (hook, c["hook_title_overlap"])
c = {"video_title_for_youtube_short": "Should men be afraid of testosterone therapy?",
     "viral_hook_text": "Most doctors won't tell you this."}
assert playbook.check_hook(c) is False and c["hook_title_overlap"] == 0.0, c
assert playbook.hook_overlap("Can a brain tumor make you a killer?", "") == 0.0
# 50 % or more is a repeat (Huberman-003 clip 1: cortisol, morning, fix = 3 of 6 words)
c = {"video_title_for_youtube_short": "Why does raising cortisol in the morning fix your sleep?",
     "viral_hook_text": "Raise cortisol in the morning, fix everything else."}
assert playbook.check_hook(c) is True and c["hook_title_overlap"] == 0.5, c
c = {"video_title_for_youtube_short": "Why does frustration mean your brain is learning?",
     "viral_hook_text": "Frustration is the first gate of learning opening."}
assert playbook.check_hook(c) is False and c["hook_title_overlap"] == 0.4, c
# prepare() flags it, export writes it
sh = [{"start": 5.0, "end": 30.0, "video_title_for_youtube_short": "Can stress rewire your brain?",
       "viral_hook_text": "Stress can rewire your brain.", "video_description_for_tiktok": "a",
       "video_description_for_instagram": "b"}]
tk = playbook.prepare(sh, SRC, BRIEF)
assert sh[0]["hook_repeats_title"] is True
o = json.load(open(playbook.export_clip(sh[0], tempfile.mkdtemp(), "h_clip_1.mp4", tk), encoding="utf-8"))
assert o["hook_repeats_title"] is True and o["hook_title_overlap"] == 1.0, o

print("test_playbook OK")
