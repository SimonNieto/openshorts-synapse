"""The one place that decides which model THINKS in a Clip Generator++ job.

Claude first — the user's own plan, through Claude Code (``claude -p`` with
CLAUDE_CODE_OAUTH_TOKEN from ``claude setup-token``) — and Gemini as the
fallback. When Claude answers with a quota / session limit, it is switched
off for the rest of this process (one job), so the job does not pay a failed
Claude call at every stage before falling back.

Every thinking stage logs one line starting with "🧠 [<model>]" (the
dashboard shows the latest one on the processing screen), so it is always
visible who is working.

Also here: the EPISODE BRIEF — one read of the whole transcript before any
clip is picked (who talks, the topic, a visual glossary of the key notions,
the stories told with their concrete details). Every detail must come with a
verbatim quote that is checked against the transcript; what cannot be found
is dropped, so an invented date or study never reaches an image.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from dotenv import load_dotenv

# The keys live in .env (not the container env): load it here too, so this
# module works whatever was imported first.
load_dotenv()

# Claude could not be used in this process (quota, auth...): the reason, or
# None. Expires after OFF_FOR seconds so the long-lived backend (regenerate
# copy...) goes back to Claude once the session limit has reset.
_OFF = None
_OFF_AT = 0.0
OFF_FOR = 30 * 60
# Tokens Claude used: the last call, and the running total of this process.
LAST_USAGE = None
USAGE = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
# The brief of the episode this job works on (set by main.py after the
# transcription, read by the clip stages and the B-roll planner).
EPISODE_BRIEF = None

SYSTEM = "You are a senior short-form video editor and analyst. You answer only with the requested JSON."
# The images travel INSIDE the request (each after a line with its file name):
# no Read tool, so no second turn re-reading the whole prompt (measured
# 28-sep-2026: 3,688 tokens through the Read tool, 830 inline, same question).
SYSTEM_VISION = ("You are a senior short-form video editor and analyst. The images are attached to the request, "
                 "in order, each right after its file name. Answer only with the requested JSON.")


def claude_ready():
    return bool(shutil.which("claude") and os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))


def claude_usable():
    """Set up, not switched to Gemini by the user (AI_BRAIN=gemini), and not
    switched off in this job by a quota / auth failure."""
    global _OFF
    if _OFF is not None and time.time() - _OFF_AT > OFF_FOR:
        _OFF = None
    return claude_ready() and _OFF is None and (os.environ.get("AI_BRAIN") or "claude").lower() != "gemini"


def claude_model():
    return os.environ.get("CLAUDE_MODEL") or "sonnet"


# Who does which stage, and with which model. The default ("balanced") is
# "Gemini reads, Claude decides": the volume work (reading the whole
# transcript, classifying frames, checking images, mechanical text) goes to
# Gemini — cheap per token; the judgment (cutting the clips, hooks, titles, the
# B-roll plan) stays on Claude. A Clip Generator++ profile sets every stage
# (plus.py -> BRAIN_<STAGE> env of the job): "gemini", or a Claude model —
# "haiku" (light, uses little of the plan), "sonnet", "opus". Every stage falls
# back to the other provider when its first choice fails.
STAGES = ("brief_score", "detail", "layout", "broll", "broll_art", "image_review", "hook", "text")
STAGE_DEFAULTS = {
    "brief_score": "gemini",    # brief + scoring pass: reads the whole transcript
    "detail": "sonnet",         # picks the clips, writes hooks / titles / descriptions
    "layout": "gemini",         # layout picker: frame classification
    "broll": "sonnet",          # B-roll plan (+ the hook of a screen clip)
    "broll_art": "sonnet",      # B-roll art direction: the prompt of every picture of a set, no image
    "image_review": "gemini",   # B-roll image check (the judge re-checks the doubtful ones)
    "hook": "sonnet",           # screen hook of a clip without Claude B-roll
    "text": "gemini",           # caption translation, copy regeneration
}
CLAUDE_MODELS = ("haiku", "sonnet", "opus")


def choice(stage_key, has_key=None, override=None):
    """"gemini" or the Claude model alias this stage runs on. ``has_key``:
    whether a Gemini key is at hand (default: GEMINI_API_KEY in the env; the
    backend gets it with the request instead) — without one, Claude."""
    if (os.environ.get("AI_BRAIN") or "").lower() == "gemini":
        return "gemini"
    v = (override or os.environ.get(f"BRAIN_{(stage_key or '').upper()}")
         or STAGE_DEFAULTS.get(stage_key) or "claude").lower().strip()
    if v not in ("gemini",) + CLAUDE_MODELS:
        v = claude_model()          # "claude" or anything unknown: the default Claude model
    if has_key is None:
        has_key = bool(os.environ.get("GEMINI_API_KEY"))
    if v == "gemini" and not has_key:
        return claude_model()
    return v


def route(stage_key, has_key=None, override=None):
    """"claude" or "gemini" for this stage."""
    return "gemini" if choice(stage_key, has_key, override) == "gemini" else "claude"


def stage_model(stage_key, override=None):
    """The Claude model this stage uses when Claude runs it (its own model, or
    the default one when the stage is Gemini's and Claude is the fallback)."""
    c = choice(stage_key, True, override)
    return claude_model() if c == "gemini" else c


def gemini_json(contents, model=None, tries=3):
    """One Gemini JSON call (text and/or image parts), with a short retry on
    transient errors. Returns (data, response); the answer is kept in
    ai_cache, so the same question is never paid twice (``response`` is None
    then)."""
    import ai_cache
    from google import genai
    from google.genai import types
    import gemini_worker
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("no GEMINI_API_KEY")
    model = model or os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
    cache_key = ai_cache.gemini_key(model, contents)
    cached = ai_cache.get_answer(cache_key)
    if cached is not None:
        print(f"   ♻️ Gemini: same question as before — answer reused, $0", flush=True)
        return cached, None
    client = genai.Client(api_key=key)
    last = None
    for attempt in range(tries):
        try:
            r = client.models.generate_content(
                model=model, contents=contents,
                config=types.GenerateContentConfig(response_mime_type="application/json"))
            gemini_worker.raise_if_blocked(r)
            data = json.loads(r.text or "{}")
            ai_cache.put_answer(cache_key, data)
            return data, r
        except gemini_worker.GeminiBlockedError:
            raise
        except Exception as e:
            last = e
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"Gemini failed: {last}")


def say(who, stage):
    """The one-line status the dashboard shows while a job runs."""
    print(f"🧠 [{who}] {stage}", flush=True)


def _switch_off_if_limit(err):
    global _OFF, _OFF_AT
    msg = str(err).lower()
    if any(k in msg for k in ("limit", "quota", "credit", "not logged in", "authenticate", "401", "403",
                              "billing", "overloaded")):
        _OFF = str(err)[:160]
        _OFF_AT = time.time()
        print(f"🧠 Claude is off for the rest of this job ({_OFF}) — Gemini takes over.", flush=True)


def _inline_refs(schema):
    """Pydantic's JSON schema with every $ref expanded (a flat schema is what
    every structured-output validator accepts)."""
    defs = schema.get("$defs") or schema.get("definitions") or {}

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return walk(dict(defs.get(name, {})))
            return {k: walk(v) for k, v in node.items() if k not in ("$defs", "definitions", "title")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node
    return walk(schema)


def json_schema(schema):
    """A pydantic model class or a plain JSON schema dict -> a flat JSON schema."""
    if hasattr(schema, "model_json_schema"):
        return _inline_refs(schema.model_json_schema())
    return schema


# Claude's image budget: it resizes anything bigger to ~1.15 MP itself, so
# sending more only costs upload time.
_MAX_PIXELS = 1_150_000
_MAX_EDGE = 1568


def _image_block(path):
    """A base64 JPEG content block, pre-shrunk to what Claude would keep."""
    import base64
    import io
    from PIL import Image
    im = Image.open(path)
    im = im.convert("RGB")
    w, h = im.size
    scale = min(1.0, _MAX_EDGE / max(w, h), (_MAX_PIXELS / float(w * h)) ** 0.5)
    if scale < 0.999:
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(buf.getvalue()).decode()}}


def _parse_json_text(text):
    """The JSON object in a plain-text answer (tolerates a ``` fence or a
    stray sentence around it). Raises ValueError when there is none."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except ValueError:
        i, j = s.find("{"), s.rfind("}")
        if i < 0 or j <= i:
            raise ValueError("no JSON object in the answer")
        return json.loads(s[i:j + 1])


def _check(data, schema, model_cls=None):
    """Raise ValueError when ``data`` does not have the shape asked for."""
    if not isinstance(data, dict):
        raise ValueError("answer is not a JSON object")
    missing = [k for k in (schema.get("required") or []) if k not in data]
    if missing:
        raise ValueError(f"answer misses {missing}")
    if model_cls is not None:
        try:
            model_cls.model_validate(data)
        except Exception as e:
            raise ValueError(f"answer does not validate: {str(e)[:160]}")


def _claude_run(prompt, schema, attach, system, model, effort, timeout, strict):
    """One ``claude -p`` process. Plain mode: the schema is written in the
    prompt and Claude answers in ONE turn (the --json-schema tool costs a
    second turn and a cache write of the whole prompt: 4,748 vs 4,021 tokens
    read on the same 3k prompt). ``strict``: the --json-schema tool, used only
    when a plain answer did not parse."""
    global LAST_USAGE
    text = prompt
    if not strict:
        text += ("\n\nAnswer with ONE JSON object and nothing else (no markdown fence, no comment), "
                 "following this JSON schema:\n" + json.dumps(schema, separators=(",", ":"), ensure_ascii=False))
    content = []
    for path in attach or []:
        content += [{"type": "text", "text": f'Image "{os.path.basename(path)}":'}, _image_block(path)]
    content.append({"type": "text", "text": text})
    msg = {"type": "user", "message": {"role": "user", "content": content}}

    work = tempfile.mkdtemp(prefix="claude_")
    env = {**os.environ, "CLAUDE_CONFIG_DIR": os.path.join(work, "cfg"), "DISABLE_AUTOUPDATER": "1",
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    # Haiku takes no --effort flag, so nothing bounded its hidden reasoning:
    # its image checks wrote 4-8k tokens for a JSON of ~300 (measured in a job
    # log, 29-sep-2026). Cap it; AI_HAIKU_THINKING=<tokens> to allow some again.
    if model == "haiku":
        env["MAX_THINKING_TOKENS"] = os.environ.get("AI_HAIKU_THINKING", "0")
    # An API key would outrank the subscription token (and bill the API).
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(k, None)
    cmd = ["claude", "-p", "--model", model,
           "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--system-prompt", system, "--tools", "",
           "--no-session-persistence", "--disable-slash-commands", "--max-turns", "4" if strict else "2"]
    if effort:
        cmd[4:4] = ["--effort", effort]
    if strict:
        cmd += ["--json-schema", json.dumps(schema)]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, input=json.dumps(msg) + "\n", capture_output=True, text=True, encoding="utf-8",
                           timeout=timeout, cwd=work, env=env)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out = None
    for line in (r.stdout or "").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "result":
            out = ev
    if out is None:
        raise RuntimeError(f"claude exited {r.returncode}: {(r.stderr or r.stdout)[-300:]}")
    if out.get("is_error"):
        raise RuntimeError(f"claude: {str(out.get('result') or out.get('subtype') or r.stderr)[:300]}")
    u = out.get("usage") or {}
    tin = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                           "cache_read_input_tokens"))
    tout = int(u.get("output_tokens") or 0)
    think_out = int((u.get("output_tokens_details") or {}).get("thinking_tokens") or 0)
    LAST_USAGE = {"input_tokens": tin, "output_tokens": tout}
    USAGE["calls"] += 1
    USAGE["input_tokens"] += tin
    USAGE["output_tokens"] += tout
    cached = int(u.get("cache_read_input_tokens") or 0)
    print(f"   🧠 Claude {model}: {tin:,} tokens read (of which {cached:,} from cache), {tout:,} written"
          f"{f' ({think_out:,} of them hidden thinking)' if think_out else ''}, "
          f"{time.time() - t0:.0f}s "
          f"(job so far: {USAGE['input_tokens'] + USAGE['output_tokens']:,} in {USAGE['calls']} calls)",
          flush=True)
    if strict and out.get("structured_output") is not None:
        return out["structured_output"]
    return _parse_json_text(out.get("result"))


def claude_json(prompt, schema, timeout=300, attach=None, system=None, effort=None, model=None, reuse=True):
    """One headless Claude Code call, JSON checked against ``schema`` (a
    pydantic model or a JSON schema dict). Runs in a throwaway config dir and
    working dir, so neither the project's CLAUDE.md nor anyone's settings leak
    into it; no tool at all. ``attach``: image files, sent inside the request.
    ``model``: a Claude alias (default CLAUDE_MODEL / sonnet); Haiku gets no
    effort flag. ``reuse=False``: never read the remembered answer (a
    "regenerate" click wants a new one); the new answer is still kept."""
    global LAST_USAGE
    if not claude_ready():
        raise RuntimeError("Claude not set up (claude CLI or CLAUDE_CODE_OAUTH_TOKEN missing)")
    import ai_cache
    model = model or claude_model()
    effort = None if model == "haiku" else (effort or os.environ.get("CLAUDE_EFFORT") or "medium")
    system = system or (SYSTEM_VISION if attach else SYSTEM)
    model_cls = schema if hasattr(schema, "model_validate") else None
    schema = json_schema(schema)
    # Same question already answered (a re-run of this video, a restyle...):
    # read it back instead of paying for it again.
    cache_key = ai_cache.answer_key(model, effort, system, schema, prompt, attach)
    cached_answer = ai_cache.get_answer(cache_key) if reuse else None
    if cached_answer is not None:
        LAST_USAGE = {"input_tokens": 0, "output_tokens": 0}
        print(f"   ♻️ Claude: same question as before — answer reused, 0 tokens "
              f"({ai_cache.HITS['answers']} reused in this job)", flush=True)
        return cached_answer
    try:
        data = _claude_run(prompt, schema, attach, system, model, effort, timeout, strict=False)
        _check(data, schema, model_cls)
    except ValueError as e:
        # Rare: the plain answer did not parse / validate — ask again with the
        # strict structured-output tool.
        print(f"   ⚠️ Claude's answer was not clean JSON ({str(e)[:120]}) — asking again, strict.", flush=True)
        data = _claude_run(prompt, schema, attach, system, model, effort, timeout, strict=True)
        _check(data, schema, model_cls)
    ai_cache.put_answer(cache_key, data)
    return data


def think(stage, prompt, schema, fallback=None, attach=None, timeout=300, effort=None, system=None,
          route_key=None, has_key=None, brain=None, reuse=True):
    """The stage's first choice, then the other provider. Returns (data, who).
    ``fallback()`` is the stage's Gemini call; ``route_key`` a STAGES key
    (Claude, default model, when None); ``brain`` overrides the stage's choice
    (the backend passes the project profile's). ``schema`` may be a pydantic
    model: Claude's answer is then validated with it, exactly like Gemini's."""
    model = stage_model(route_key, brain) if route_key else claude_model()
    if fallback is not None and route(route_key, has_key, brain) == "gemini":
        say("Gemini", stage)
        try:
            return fallback(), "gemini"
        except Exception as e:
            print(f"   ⚠️ Gemini failed on '{stage}' ({str(e)[:200]})"
                  f"{' — Claude takes it.' if claude_usable() else ''}", flush=True)
            if not claude_usable():
                raise
        say(f"Claude · {model} — Gemini failed on this step", stage)
        data = claude_json(prompt, schema, timeout=timeout, attach=attach, system=system, effort=effort, model=model,
                           reuse=reuse)
        if hasattr(schema, "model_validate"):
            data = schema.model_validate(data).model_dump()
        return data, "claude"
    if claude_usable():
        say(f"Claude · {model}", stage)
        try:
            data = claude_json(prompt, schema, timeout=timeout, attach=attach, system=system, effort=effort,
                               model=model, reuse=reuse)
            if hasattr(schema, "model_validate"):
                data = schema.model_validate(data).model_dump()
            return data, "claude"
        except Exception as e:
            print(f"   ⚠️ Claude failed on '{stage}' ({str(e)[:200]})", flush=True)
            _switch_off_if_limit(e)
            if fallback is None:
                raise
            say("Gemini — Claude failed on this step", stage)
            return fallback(), "gemini"
    if fallback is None:
        raise RuntimeError(f"no model available for '{stage}' (Claude not usable, no fallback)")
    say("Gemini" if (os.environ.get("AI_BRAIN") or "").lower() == "gemini" else "Gemini — Claude unavailable",
        stage)
    return fallback(), "gemini"


def think_frames(stage, prompt, schema, frames, fallback=None, timeout=300, route_key=None):
    """``think`` for a vision stage: ``frames`` are JPEG bytes (in order),
    sent inside the Claude request."""
    tmp = tempfile.mkdtemp(prefix="frames_")
    try:
        paths = []
        for i, b in enumerate(frames):
            p = os.path.join(tmp, f"frame_{i + 1:02d}.jpg")
            with open(p, "wb") as f:
                f.write(b)
            paths.append(p)
        names = ", ".join(os.path.basename(p) for p in paths)
        full = (f"The {len(paths)} images are the video frames, in order: {names}. "
                f"Look at every one of them before answering.\n\n{prompt}")
        return think(stage, full, schema, fallback=fallback, attach=paths, timeout=timeout, route_key=route_key)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- episode brief ------------------------------------------------------------------

BRIEF_RULES = """You prepare the editors of a clip channel. Read this WHOLE podcast / video transcript once and
write the brief they will use to cut clips and to choose the images that illustrate them.

- "speakers": who talks — name if it is said, role (host / guest), what they are expert in;
- "topic": one sentence — what the whole episode is about;
- "themes": the 4-10 big themes, in order of importance;
- "glossary": the 5-20 key notions a viewer must picture to follow (a brain network, a drug, a device, a
  technique, a place...). For each: "term" (as said in the transcript), "meaning" (one plain sentence) and
  "visual" (ONE concrete picture that shows it at a glance on a phone, always the same way — this is how the
  channel will draw it every time: a real object, instrument, place or gesture at its true scale, as a
  documentary photographer would shoot it — never a symbol: no glowing brain, no neon neurons, no light bulb,
  no floating interface, no pills on white);
- "stories": the concrete stories and examples told (an event, a case, an experiment, an anecdote): a
  one-line "summary", the "details" that make it specific (place, year, people or kind of people, study,
  numbers — only what is SAID), and "quote": 8-20 words copied EXACTLY from the transcript where it is told;
- "tone": a few words (e.g. "science, calm, funny asides").

Never invent: a detail that is not in the transcript must not appear. Quotes must be verbatim."""

# Without B-roll nothing reads the glossary nor the stories — the biggest part
# of the brief's OUTPUT (the dearest tokens): the short brief skips them.
BRIEF_RULES_LITE = """You prepare the editors of a clip channel. Read this WHOLE podcast / video transcript once and
write the short brief they will use to judge and name what they cut:

- "speakers": who talks — name if it is said, role (host / guest), what they are expert in;
- "topic": one sentence — what the whole episode is about;
- "themes": the 4-10 big themes, in order of importance;
- "tone": a few words (e.g. "science, calm, funny asides").

Never invent: nothing that is not in the transcript."""

BRIEF_PROMPT = BRIEF_RULES + """

TRANSCRIPT ([mm:ss] markers):
{text}"""


def brief_full():
    """The full brief (glossary + stories) only feeds the B-roll planner."""
    return bool(os.environ.get("PLUS_BROLL_JSON")) or os.environ.get("BRIEF_FULL") == "1"

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "speakers": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "role": {"type": "string"}, "expertise": {"type": "string"}},
            "required": ["role"]}},
        "topic": {"type": "string"},
        "themes": {"type": "array", "items": {"type": "string"}},
        "glossary": {"type": "array", "items": {"type": "object", "properties": {
            "term": {"type": "string"}, "meaning": {"type": "string"}, "visual": {"type": "string"}},
            "required": ["term", "meaning", "visual"]}},
        "stories": {"type": "array", "items": {"type": "object", "properties": {
            "summary": {"type": "string"}, "details": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["summary", "quote"]}},
        "tone": {"type": "string"},
    },
    "required": ["topic", "themes", "glossary", "stories"],
}
BRIEF_SCHEMA_LITE = {
    "type": "object",
    "properties": {k: v for k, v in BRIEF_SCHEMA["properties"].items() if k not in ("glossary", "stories")},
    "required": ["topic", "themes"],
}


def _toks(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _words(transcript):
    return [w for s in (transcript or {}).get("segments", []) or [] for w in s.get("words") or []]


def _marked_text(words, every=30.0):
    out, last = [], -every
    for w in words:
        if w["start"] - last >= every:
            m = int(w["start"])
            out.append(f"\n[{m // 60:02d}:{m % 60:02d}]")
            last = w["start"]
        out.append((w.get("word") or "").strip())
    return " ".join(out).strip()


def _locate(quote, words, toks_flat, pos_of):
    """Start time of ``quote`` in the transcript, or None when it is not
    there (8 consecutive words of it must match)."""
    q = _toks(quote)
    if len(q) < 4:
        return None
    for k in range(0, max(1, len(q) - 7), 3):
        probe = " " + " ".join(q[k:k + 8]) + " "
        i = toks_flat.find(probe)
        if i >= 0:
            return pos_of(i)
    return None


def episode_brief(transcript, api_key=None):
    """The brief (dict, with each kept story's time ``t``), or None."""
    words = _words(transcript)
    if len(words) < 200:
        return None
    text = _marked_text(words)
    if len(text) > 400_000:          # ~70k words: keep the start and the end of a very long source
        text = text[:300_000] + "\n[...]\n" + text[-100_000:]
    full = brief_full()
    prompt = f"{BRIEF_RULES if full else BRIEF_RULES_LITE}\n\nTRANSCRIPT ([mm:ss] markers):\n{text}"

    def gemini():
        if api_key and not os.environ.get("GEMINI_API_KEY"):
            os.environ["GEMINI_API_KEY"] = api_key
        model = os.environ.get("GEMINI_MODEL_BRIEF") or os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
        return gemini_json([prompt], model=model)[0]

    try:
        data, who = think("reading the whole episode (brief)", prompt, BRIEF_SCHEMA if full else BRIEF_SCHEMA_LITE,
                          fallback=gemini, timeout=900, route_key="brief_score")
    except Exception as e:
        print(f"   ⚠️ Episode brief failed ({str(e)[:160]}) — clips are planned without it.", flush=True)
        return None
    return _ground_brief(data, words, who)


def brief_and_scores(transcript, score_prompt, score_item_schema):
    """The brief AND the scoring pass in ONE Claude call, so the whole
    transcript is read once instead of twice. ``score_prompt`` is the scoring
    prompt over every window (it carries the transcript, as windows).
    Routed to Gemini (ROUTES["brief_score"]: reading a long text is cheap
    there), Claude when Gemini fails. Returns (brief, scored_windows, cost),
    or None when both fail — the caller then runs the two stages separately."""
    words = _words(transcript)
    if len(words) < 200 or len(score_prompt) > 400_000:
        return None
    full = brief_full()
    schema = json.loads(json.dumps(BRIEF_SCHEMA if full else BRIEF_SCHEMA_LITE))
    schema["properties"]["windows"] = {"type": "array", "items": json_schema(score_item_schema)}
    schema["required"] = schema["required"] + ["windows"]
    keys = "speakers, topic, themes, glossary, stories, tone" if full else "speakers, topic, themes, tone"
    prompt = (f"TWO TASKS on the same transcript (given once, as the windows below). Answer both in one JSON.\n\n"
              f"TASK 1 — THE EPISODE BRIEF (fields {keys}). The "
              f"transcript is the concatenation of the windows' text, in order.\n"
              f"{BRIEF_RULES if full else BRIEF_RULES_LITE}\n\n"
              f"TASK 2 — SCORING THE WINDOWS (field windows).\n{score_prompt}\n\n"
              f"OUTPUT: ONE JSON object with the keys {keys} (task 1) and windows (task 2).")
    stage = "reading the whole episode once (brief + scoring)"
    order = ["gemini", "claude"] if route("brief_score") == "gemini" else ["claude", "gemini"]
    for who in order:
        try:
            if who == "gemini":
                if not os.environ.get("GEMINI_API_KEY"):
                    continue
                model = os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
                say(f"Gemini · {model}", stage)
                data, resp = gemini_json([prompt], model=model)
                wins = [score_item_schema.model_validate(w).model_dump() if hasattr(score_item_schema, "model_validate")
                        else w for w in data.get("windows") or []]
                if not wins or not data.get("topic"):
                    raise RuntimeError("answer without windows or topic")
                import gemini_worker
                cost = (gemini_worker._calculate_cost_analysis(resp, model) if resp is not None
                        else {"input_tokens": 0, "output_tokens": 0, "total_cost": 0.0, "model": f"{model} (reused)"})
            else:
                if not claude_usable():
                    continue
                model = stage_model("brief_score")
                say(f"Claude · {model}", stage)
                data = claude_json(prompt, schema, timeout=900, model=model,
                                   effort=os.environ.get("CLAUDE_EFFORT_SCORE") or "low")
                wins = list(data.get("windows") or [])
                u = LAST_USAGE or {}
                cost = {"input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0),
                        "total_cost": 0.0, "model": f"claude-{model} (subscription)"}
            return _ground_brief(data, words, who), wins, cost
        except Exception as e:
            print(f"   ⚠️ Brief + scoring by {who} failed ({str(e)[:160]}).", flush=True)
            if who == "claude":
                _switch_off_if_limit(e)
    print("   ⚠️ Brief + scoring in one call failed — running them separately.", flush=True)
    return None


def _ground_brief(data, words, who):
    """Every story must be found in the transcript by its quote; the brief
    becomes EPISODE_BRIEF."""
    global EPISODE_BRIEF
    # Grounding: every story must be found in the transcript by its quote.
    flat = [t for w in words for t in _toks(w.get("word"))]
    toks_flat = " " + " ".join(flat) + " "
    tok_time = []
    for w in words:
        tok_time += [w["start"]] * len(_toks(w.get("word")))

    def pos_of(char_i):
        n = toks_flat[:char_i + 1].count(" ") - 1
        return tok_time[max(0, min(n, len(tok_time) - 1))] if tok_time else None

    stories = []
    for s in data.get("stories") or []:
        t = _locate(s.get("quote"), words, toks_flat, pos_of)
        if t is not None:
            stories.append({**s, "t": round(float(t), 1)})
    said = set(flat)
    glossary = [g for g in data.get("glossary") or [] if any(tok in said for tok in _toks(g.get("term"))[:3])]
    brief = {"speakers": data.get("speakers") or [], "topic": data.get("topic") or "",
             "themes": data.get("themes") or [], "glossary": glossary, "stories": stories,
             "tone": data.get("tone") or "", "by": who}
    dropped = len(data.get("stories") or []) - len(stories)
    print(f"   📖 Episode brief ({who}): {brief['topic'][:120]} — {len(glossary)} notions, {len(stories)} stories"
          f"{f' ({dropped} unverifiable dropped)' if dropped else ''}", flush=True)
    EPISODE_BRIEF = brief
    return brief


def episode_context(brief=None):
    """Who talks and what the episode is about, for the clip-selection
    prompts ("" without a brief)."""
    brief = brief or EPISODE_BRIEF
    if not brief:
        return ""
    sp = "; ".join(f"{s.get('name') or '?'} ({s.get('role')}{', ' + s['expertise'] if s.get('expertise') else ''})"
                   for s in brief.get("speakers") or [])
    lines = ["", "EPISODE CONTEXT (from a read of the whole episode — use it to judge what a cold viewer "
                 "understands, and to name people and notions correctly in the copy):"]
    if sp:
        lines.append(f"- Speakers: {sp}")
    if brief.get("topic"):
        lines.append(f"- Topic: {brief['topic']}")
    if brief.get("themes"):
        lines.append("- Themes: " + "; ".join(brief["themes"][:10]))
    if brief.get("tone"):
        lines.append(f"- Tone: {brief['tone']}")
    return "\n".join(lines) + "\n"


_BRIEF_STOP = set("""a an the of to in on at by for with from and or but so as is are was were be been it its this
that these those he she they we you i me him her them us my your his their our there here then than very just not no
some any all one two three what when where which who whom how why do does did have has had will would can could about
into over than also because really like know think going get got say said""".split())


def _stem_tok(w):
    """Crude stem (plural / -ing) so "neurons" matches "neuron"; both sides use it."""
    for suf, rep in (("ies", "y"), ("ing", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)] + rep
    return w


def _content(text):
    return {_stem_tok(t) for t in _toks(text) if len(t) > 2 and t not in _BRIEF_STOP}


def _term_matches(term, said):
    """How many words of a glossary term the clip says, and whether that is enough:
    one word for a one-word term (or a distinctive 7+ letter word of a two-word
    term), two words for anything longer — "network" alone must not bring
    "default mode network"."""
    toks = [t for t in _toks(term) if len(t) > 2 and t not in _BRIEF_STOP]
    if not toks:
        return 0
    hit = [t for t in toks if _stem_tok(t) in said]
    need = 1 if len(toks) == 1 else (1 if len(toks) == 2 and any(len(t) >= 7 for t in hit) else 2)
    need = min(need, len(toks))
    return len(hit) if len(hit) >= need else 0


def glossary_split(brief, clip_words_text):
    """(notions the clip says in words, the other notions of the episode): the
    first get their full visual in the clip's brief, the second are only listed
    by name and meaning so the planner can spot one said in other words."""
    said = _content(clip_words_text)
    scored = [(_term_matches(g.get("term"), said), g) for g in (brief or {}).get("glossary") or []]
    matched = [g for n, g in sorted((x for x in scored if x[0]), key=lambda x: -x[0])]
    rest = [g for n, g in scored if not n]
    return matched, rest


OTHER_NOTIONS_MAX = 15


def brief_for_clip(brief, clip_words_text, start, end):
    """The part of the brief that concerns one clip, as prompt text."""
    if not brief:
        return ""
    said = _content(clip_words_text)
    lines = []
    sp = "; ".join(f"{s.get('name') or '?'} ({s.get('role')}{', ' + s['expertise'] if s.get('expertise') else ''})"
                   for s in brief.get("speakers") or [])
    if sp:
        lines.append(f"SPEAKERS: {sp}")
    if brief.get("topic"):
        lines.append(f"EPISODE TOPIC: {brief['topic']}")
    if brief.get("themes"):
        lines.append("THEMES: " + "; ".join(brief["themes"][:10]))
    if brief.get("tone"):
        lines.append(f"TONE: {brief['tone']}")
    gl, rest = glossary_split(brief, clip_words_text)
    if gl:
        lines.append("VISUAL GLOSSARY (draw these notions this way, every time):")
        lines += [f"- {g['term']}: {g['meaning']} -> {g['visual']}" for g in gl[:12]]
    if rest:
        lines.append("OTHER NOTIONS OF THIS EPISODE (only their name and meaning: if an image of this clip really "
                     "is simply the usual picture of one of them, even when the speaker says it in other words, give its name in "
                     "\"notion\"):")
        lines += [f"- {g['term']}: {str(g.get('meaning') or '')[:70]}" for g in rest[:OTHER_NOTIONS_MAX]]
    # Stories: the ones told around the clip (4 min before .. 1 min after), plus
    # any told earlier / later in the episode that the clip clearly refers back
    # to (it shares at least two distinctive words with the story).
    picked = []
    for s_ in brief.get("stories") or []:
        t = s_.get("t")
        if t is None:
            continue
        near = start - 240 <= t <= end + 60
        overlap = len(said & _content(f"{s_.get('summary') or ''} {s_.get('details') or ''} {s_.get('quote') or ''}"))
        if near or overlap >= 2:
            dist = 0 if start <= t <= end else min(abs(t - start), abs(t - end))
            picked.append((0 if near else 1, -overlap if not near else dist, s_))
    picked.sort(key=lambda x: (x[0], x[1]))
    st = sorted((p[2] for p in picked[:6]), key=lambda x: x["t"])
    if st:
        lines.append("STORIES TOLD AROUND THIS CLIP (real details, use them):")
        lines += [f"- {s['summary']} — {s.get('details') or ''}" for s in st]
    return "\n".join(lines)


# --- the episode's visual bible (B-roll v2, 1-oct-2026) ------------------------------------
# One read of the brief and the transcript per episode, by the art director's
# model: the concrete WORLD the pictures are taken from, the episode's MOOD (the
# levels of visual_mood, B-roll « ambiance » 2-oct-2026: one vote in every
# clip's base mood, never a look laid over the clips), recurring MOTIFS,
# pictures to AVOID, the REGISTERS of what a camera cannot shoot, and a hero
# concept per story. Every clip's editor and art director read it; kept in the
# job's metadata (episode_bible) and remembered by ai_cache.
EPISODE_BIBLE = None
BIBLE_RULES = """You are the director of photography of a documentary channel, preparing ONE episode's visual bible
before its clips are cut. You have the episode brief and the transcript. Write, in English, concrete and specific
to THIS episode (nothing generic that would fit any episode):
- "world": 8 to 15 concrete things the pictures can be taken from, as said or clearly implied in the episode: real
  places with their time of day, objects and instruments at their true scale, kinds of people and what they wear
  or do, materials and textures. Each a short phrase. Never a symbol, a glowing brain, a neon neuron, a light bulb,
  a floating interface.
- "mood": how the episode as a whole is lived and told, one level per question (each level defined below), and
  "why" (one line, from what it is about and how it is told):
{mood_levels}
- "motifs": 3 to 5 recurring visual motifs the clips can return to, each a real thing of the episode in its life
  (people and things in use, places with their people) with when to use it, in one line — never an allegory (no
  doorway for a threshold, no hand reaching into the dark, no lone figure before the vastness).
- "avoid": 0 to 6 pictures that would state a FALSE FACT about this episode (the wrong way it was done, the wrong
  place, era or instrument), one line each — never a matter of taste or style: that is the registers' job.
- "registers": the episode's own way of showing each KIND of thing it talks about that a camera cannot shoot as
  it is — what only an instrument sees, an abstraction (a mechanism, a quantity, a law), an inner experience lived
  by someone — ONE register per kind, 0 to 6 in all, and nothing for what a camera can photograph. EVERY inner
  experience the episode names — something taken or practised for its effect on the mind, a state lived from
  inside — gets its own register, even when it is named in passing. A REGISTER IS A STYLE, NEVER A SCENE: the
  scene of each picture comes from its own sentence. For each: "kind" (instrument, model or inner), "name" (one
  lower-case word naming that kind of thing), "when" (which moments of the episode call for it, one line), "look"
  (40 to 80 words: the STYLE only — the medium, the palette, the light, the texture, the kind of geometry and scale
  it uses, how strange, saturated, vast or exact it is — from how that kind of thing is known to look and how the
  speaker tells it; an inner register is the experience as it is perceived from inside, as impossible, saturated or
  strange as it is lived; never a scene, a place, a subject or a person, never the room it happens in nor its
  medical version, never a symbol), "judge" (one sentence: what a good picture of this register is),
  "cheap" (one line: the version that would look cheap or generic, to stay away from).
- "heroes": for each story or big theme of the brief, ONE picture that would make a cold viewer stop on a phone
  (full screen, one second): "story" (its name), "picture" (one sentence: a real scene of the story — place, subject,
  action, light — never an allegory of its idea), "why" (what the viewer sees). 6 to 12 of them.
Never invent a fact: a place, a year, a person must be in the transcript or the brief."""
REGISTER_KINDS = ("instrument", "model", "inner")   # visual_mood's visibility levels past "eye"
BIBLE_MOOD_AXES = ("valence", "intensity", "era", "gravity", "distance")
BIBLE_SCHEMA = {
    "type": "object",
    "properties": {
        "world": {"type": "array", "items": {"type": "string"}},
        "mood": {"type": "object", "properties": {"why": {"type": "string"}}},
        "motifs": {"type": "array", "items": {"type": "string"}},
        "avoid": {"type": "array", "items": {"type": "string"}},
        "heroes": {"type": "array", "items": {"type": "object", "properties": {
            "story": {"type": "string"}, "picture": {"type": "string"}, "why": {"type": "string"}},
            "required": ["story", "picture"]}},
        "registers": {"type": "array", "items": {"type": "object", "properties": {
            **{k: {"type": "string"} for k in ("name", "when", "look", "judge", "cheap")},
            "kind": {"type": "string", "enum": list(REGISTER_KINDS)}}, "required": ["name", "kind", "look"]}},
    },
    "required": ["world", "mood", "motifs", "avoid", "heroes"],
}


def _bible_schema():
    """BIBLE_SCHEMA with the mood's levels as enums (visual_mood: the same anchored levels as a picture's)."""
    import json as _json
    import visual_mood
    schema = _json.loads(_json.dumps(BIBLE_SCHEMA))
    props = schema["properties"]["mood"]["properties"]
    for axis in BIBLE_MOOD_AXES:
        props[axis] = {"type": "string", "enum": list(visual_mood.LEVELS[axis])}
    schema["properties"]["mood"]["required"] = list(BIBLE_MOOD_AXES)
    return schema


def bible_rules():
    """BIBLE_RULES with the mood's levels written out."""
    import visual_mood
    return BIBLE_RULES.replace("{mood_levels}", visual_mood.levels_text(BIBLE_MOOD_AXES, indent="    "))
REGISTER_MAX = 6
REGISTER_RESERVED = ("photo", "cinematic", "neon", "drawing", "vintage", "3d", "comic", "diagram")


def brief_text(brief):
    """The whole brief as prompt text (the bible reads all of it)."""
    if not brief:
        return ""
    lines = []
    sp = "; ".join(f"{s.get('name') or '?'} ({s.get('role')}{', ' + s['expertise'] if s.get('expertise') else ''})"
                   for s in brief.get("speakers") or [])
    if sp:
        lines.append(f"SPEAKERS: {sp}")
    if brief.get("topic"):
        lines.append(f"TOPIC: {brief['topic']}")
    if brief.get("themes"):
        lines.append("THEMES: " + "; ".join(brief["themes"][:12]))
    if brief.get("tone"):
        lines.append(f"TONE: {brief['tone']}")
    if brief.get("glossary"):
        lines.append("GLOSSARY:")
        lines += [f"- {g.get('term')}: {g.get('meaning')} -> {g.get('visual')}" for g in brief["glossary"][:20]]
    if brief.get("stories"):
        lines.append("STORIES:")
        lines += [f"- {s.get('summary')} — {s.get('details') or ''}" for s in brief["stories"][:20]]
    return "\n".join(lines)


def _strs(v, n, width=160):
    return [re.sub(r"\s+", " ", str(x)).strip()[:width] for x in (v if isinstance(v, list) else []) if str(x).strip()][:n]


def _clean_bible(data, who):
    """The model's answer -> the bible kept (short strings, bounded lists), or None when it has no world."""
    if not isinstance(data, dict):
        return None
    import visual_mood
    mood_raw = data.get("mood") if isinstance(data.get("mood"), dict) else {}
    mood = {a: str(mood_raw.get(a) or "").strip().lower() for a in BIBLE_MOOD_AXES}
    mood = {a: v for a, v in mood.items() if v in visual_mood.LEVELS[a]}
    if mood and str(mood_raw.get("why") or "").strip():
        mood["why"] = re.sub(r"\s+", " ", str(mood_raw["why"])).strip()[:200]
    heroes = []
    for h in data.get("heroes") if isinstance(data.get("heroes"), list) else []:
        if isinstance(h, dict) and str(h.get("picture") or "").strip():
            heroes.append({k: re.sub(r"\s+", " ", str(h.get(k) or "")).strip()[:300] for k in ("story", "picture", "why")})
    regs, seen_names = [], set()
    for r in data.get("registers") if isinstance(data.get("registers"), list) else []:
        if not isinstance(r, dict):
            continue
        name = re.sub(r"[^a-z]", "", str(r.get("name") or "").lower())[:16]
        look_r = re.sub(r"\s+", " ", str(r.get("look") or "")).strip()[:900]
        if not name or name in REGISTER_RESERVED or name in seen_names or len(look_r.split()) < 12:
            continue
        seen_names.add(name)
        kind = str(r.get("kind") or "").strip().lower()
        regs.append({"name": name, "look": look_r, **({"kind": kind} if kind in REGISTER_KINDS else {}),
                     **{k: re.sub(r"\s+", " ", str(r.get(k) or "")).strip()[:300] for k in ("when", "judge", "cheap")}})
    bible = {"world": _strs(data.get("world"), 15), "mood": mood, "motifs": _strs(data.get("motifs"), 5, 200),
             "avoid": _strs(data.get("avoid"), 8), "heroes": heroes[:12], "registers": regs[:REGISTER_MAX], "by": who}
    return bible if bible["world"] else None


def episode_bible(brief, transcript=None):
    """The episode's visual bible (dict) or None; becomes EPISODE_BIBLE. One
    call on the ``broll_art`` step (the art director's model), high effort,
    remembered by ai_cache for the next run of the same source."""
    global EPISODE_BIBLE
    if not brief:
        return None
    words = _words(transcript) if transcript else []
    text = _marked_text(words) if words else ""
    if len(text) > 60_000:
        text = text[:45_000] + "\n[...]\n" + text[-15_000:]
    prompt = bible_rules() + "\n\nEPISODE BRIEF:\n" + brief_text(brief)
    if text:
        prompt += "\n\nTRANSCRIPT ([mm:ss] markers):\n" + text

    def gemini():
        model = os.environ.get("GEMINI_MODEL_BRIEF") or os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
        return gemini_json([prompt], model=model)[0]

    try:
        data, who = think("the episode's visual bible (B-roll)", prompt, _bible_schema(), fallback=gemini, timeout=600,
                          route_key="broll_art", effort="high")
    except Exception as e:
        print(f"   ⚠️ Episode visual bible failed ({str(e)[:160]}) — the clips are planned without it.", flush=True)
        return None
    bible = _clean_bible(data, who)
    if bible:
        import visual_mood
        print(f"   🎨 Episode visual bible ({who}): {len(bible['world'])} things of its world, mood « "
              f"{visual_mood.describe(bible['mood']) or '-'} »{(' (' + bible['mood']['why'] + ')') if bible['mood'].get('why') else ''}, "
              f"{len(bible['motifs'])} motifs, {len(bible['heroes'])} hero ideas", flush=True)
    else:
        print("   ⚠️ Episode visual bible: nothing usable in the answer — the clips are planned without it.", flush=True)
    EPISODE_BIBLE = bible
    return bible


def bible_text(bible=None, heroes=12):
    """The bible as prompt text for a clip's editor and art director ("" without one)."""
    bible = bible or EPISODE_BIBLE
    if not bible:
        return ""
    lines = ["EPISODE VISUAL BIBLE (one read of the whole episode — the pictures come from this world and wear this look):"]
    if bible.get("world"):
        lines.append("WORLD: " + "; ".join(bible["world"]))
    if bible.get("motifs"):
        lines.append("MOTIFS: " + " | ".join(bible["motifs"]))
    if bible.get("registers"):
        lines.append("REGISTERS (how this episode shows what a camera cannot shoot — the editor names one in \"style\", the "
                     "director paints it, the channel's photo look does not apply to it):")
        lines += [f"- \"{r['name']}\"" + (f" ({r['kind']})" if r.get("kind") else "") + f" — when: {r.get('when') or '-'} | look: {r['look']}"
                  + (f" | judge: {r['judge']}" if r.get("judge") else "") + (f" | cheap: {r['cheap']}" if r.get("cheap") else "")
                  for r in bible["registers"]]
    if bible.get("avoid"):
        lines.append("WRONG FACTS (never show): " + "; ".join(bible["avoid"]))
    if bible.get("heroes") and heroes:
        lines.append("HERO IDEAS (one picture per story, for the full-screen hero):")
        lines += [f"- {h.get('story')}: {h.get('picture')}" + (f" ({h['why']})" if h.get("why") else "")
                  for h in bible["heroes"][:heroes]]
    return "\n".join(lines)
