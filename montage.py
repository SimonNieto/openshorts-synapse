"""Montage (Clip Generator++, 5-oct-2026): the clip is re-cut from the source
before anything else is done to it. Silences are tightened to a breath, the
passages the clip choice marked as removable (``clip["cut_out"]``) are taken
out, and the clip opens on the voice itself instead of a hush.

The user's decisions of 5-oct-2026 (« go pour tout »): silences tightened (2),
internal cuts (6), a dry cut to a tighter frame past 6 s without a change on
screen (4, punch_in.py) — and her reservation (9): « quand on coupe dans un
clip, ça ne doit PAS se voir » — no stutter, no jumping head. An invisible cut
or no cut. So every join is chosen, measured and, when it would show, hidden
or given up:

1. WHERE. The out and in points of a join are both picked inside the pause, on
   the source's frame grid, as the pair of frames whose head looks the most
   alike (optical flow over the head box found by MediaPipe).
2. HOW MUCH IT JUMPS. The 90th percentile of that flow, in pixels of the
   1080p source. Under JUMP_CLEAN nothing shows (the bench: the head moves
   less than a blink does). Different shots on both sides (the source's own
   camera cut, removed or kept) is a camera cut: nothing to hide either.
3. HIDDEN OR NOT CUT. Between JUMP_CLEAN and JUMP_HIDE the join needs a frame
   switch on its very frame (normal <-> tight, punch_in.schedule_hides): the
   jump becomes a change of camera. When no switch fits (another change too
   close) or above JUMP_HIDE, that pause is NOT cut.

The sound: a FADE-long fade out and in at every join (no click), one ffmpeg
pass over the source with every boundary half a frame between two frames of
the source, so picture and sound stay in step over any number of joins.

What comes out is an EDL in recut.py's format, stored by main.py in
``clip["recipe"]["segments"]``: every later step (reframe, reactions, motion,
B-roll, hook, captions) works on ``recut.virtual_transcript`` with start=0 and
end=the length of the re-cut clip, like an editor-recut clip.

The planning (``plan``) is pure and tested; reading the sound (``audio_levels``),
the frames (``FrameJudge``) and the shots (``shot_cuts``) is the I/O around it.
"""
import json
import math
import os
import re
import subprocess
import threading

# --- the recipe (plus.MONTAGE switches them; the numbers are here) ---------------------------------
SILENCE_MIN = 0.35   # s: a pause longer than this is tightened (son/rapport.md C2: 2.1 s of them per clip)
BREATH = 0.20        # s of a tightened pause that stays: a breath
BREATH_SLACK = 0.12  # the breath may grow by this much when it finds two frames that look more alike
BEAT = 0.50          # s kept before the punchline and before a short reply of the other speaker ("Whoa.")
SILENCE_DB = -20.0   # dB under the clip's speech level (its 95th percentile): silence (son: -35 dBFS, voice -15)
LEAD_IN = 0.06       # s of silence kept before the clip's first voice (Whisper opens up to 0.4 s early)
TAIL_MAX = 0.60      # s: a clip ending on more silence than this after its last voice...
TAIL_KEEP = 0.40     # ...keeps this much of it
MIN_GAIN = 0.10      # s: a cut that saves less is not worth a join
EDGE = 0.05          # s of silence kept on each side of a join at least: no clipped breath or consonant
FADE = 0.015         # s of fade out and in at every join: no click (10-20 ms)
VALLEY_DB = 6.0      # a passage edge with no real pause: a dip this close to the silence level will do
VALLEY_SPAN = 0.25   # s around a passage's first/last word where its edge is looked for
MIN_PIECE = 0.50     # s: no kept piece shorter than this between two joins (recut.MIN_SEGMENT_SECONDS)
# The jump at a join: the 90th percentile of the optical flow over the head (px of the 1080p source), or
# MAD_SCALE x the mean |difference| over what the vertical crop shows (a hand coming in), whichever is
# larger. Calibrated on job b8e46c24 (5-oct-2026, 22 joins of c02, c04, c07 looked at side by side at
# 390 px): the head of someone speaking moves 2-4 px from one frame to the next (p50), 3-12 px (p90); joins
# at 3.6-5 px are two identical pictures, 7-13 px a small visible drop or turn, 20-28 px a turned head.
JUMP_CLEAN = 6.0     # under: invisible as it is (within a speaking head's own frame-to-frame motion)
JUMP_HIDE = 22.0     # under: hidden by a frame switch on the join; over: the pause is kept
MAD_SCALE = 2.4      # a mean |diff| of 2.5 over the crop (8-bit) counts as a 6 px jump
WIDE_SLACK = 0.45    # s: when no clean pair is found, the breath may grow this much (a longer breath beats a jump)
CAMERA_DIFF = 22.0   # mean |diff| of 32x18 grey thumbnails (0-255): the two frames are two shots
MIN_SHOT = 0.60      # s: no join leaves a shot shorter than this on screen (a flash)
SHOT_FPS = 10        # shot boundary scan of the clip's source range
REGION_W = 640       # analysis width of the frames around a join
HOP = 0.01           # s: sound level resolution

# Words that make a passage untouchable: a cut must never remove or detach a negation (CHANTIER, decision 6).
NEGATIONS = {"not", "no", "never", "nothing", "nobody", "none", "neither", "nor", "without", "cannot",
             "nowhere", "hardly", "dont", "doesnt", "didnt", "isnt", "arent", "wasnt", "werent", "wont",
             "wouldnt", "shouldnt", "couldnt", "cant", "havent", "hasnt", "hadnt", "aint", "mustnt"}
# A short reply of the other speaker: the pause before it is a beat, kept long.
REPLIES = {"whoa", "wow", "really", "crazy", "jesus", "damn", "god", "yeah", "yes", "right", "exactly", "huh",
           "what", "no", "wild", "insane", "incredible", "amazing", "geez", "oh", "holy", "seriously"}


def config():
    """The recipe's montage switches (plus.MONTAGE, carried by PLUS_MONTAGE_JSON); {} when the montage is off."""
    raw = os.environ.get("PLUS_MONTAGE_JSON")
    if not raw:
        return {}
    try:
        cfg = json.loads(raw)
    except ValueError:
        return {}
    return cfg if isinstance(cfg, dict) and cfg.get("enabled") else {}


# --- text --------------------------------------------------------------------------------------

def _tok(word):
    return re.sub(r"[^a-z0-9']", "", str(word or "").lower().replace("’", "'"))


def tokens(text):
    return [t for t in (_tok(x) for x in str(text or "").split()) if t]


def is_negation(token):
    t = token.replace("'", "")
    return t in NEGATIONS or token.endswith("n't")


def _match_at(wt, i, toks):
    return wt[i:i + len(toks)] == toks


def find_span(words, text, lo, hi, after=None):
    """(i, j): indices of the first and last word of ``text`` among ``words`` ({"w","s","e"}), its first word
    starting in [lo, hi] (and at index > ``after`` when given). The whole text verbatim but for punctuation
    and case; else its first 4 words and as many words as the text has (Whisper and the model disagree on a
    word now and then). None when it is not there."""
    toks = tokens(text)
    if not toks:
        return None
    wt = [_tok(w["w"]) for w in words]
    first = -1 if after is None else after
    for need in (toks, toks[:4]):
        if len(need) < min(2, len(toks)):
            continue
        for i in range(first + 1, len(words) - len(need) + 1):
            if lo <= words[i]["s"] <= hi and _match_at(wt, i, need):
                return i, min(len(words) - 1, i + len(toks) - 1)
    return None


def find_last_span(words, text, lo, hi):
    """Like find_span, the LAST occurrence (the payoff is the last thing said)."""
    found, after = None, None
    while True:
        sp = find_span(words, text, lo, hi, after=after)
        if sp is None:
            return found
        found, after = sp, sp[0]


def find_passage(words, item, lo, hi):
    """(i, j) of a cut_out passage {"from": its first words, "to": its last words}: ``from`` verbatim with its
    first word in [lo, hi], then the first ``to`` verbatim after it, ending before ``hi``. None if not there."""
    toks_from, toks_to = tokens(item.get("from")), tokens(item.get("to"))
    if not toks_from or not toks_to:
        return None
    wt = [_tok(w["w"]) for w in words]
    for i in range(len(words) - len(toks_from) + 1):
        if not (lo <= words[i]["s"] <= hi) or not _match_at(wt, i, toks_from):
            continue
        for k in range(i, len(words) - len(toks_to) + 1):
            if words[k]["s"] > hi:
                break
            if _match_at(wt, k, toks_to) and k + len(toks_to) - 1 >= i + len(toks_from) - 1:
                j = k + len(toks_to) - 1
                if words[j]["e"] <= hi + 0.3:
                    return i, j
        return None
    return None


def _sentence_after(words, j):
    """Tokens of the sentence that starts after word ``j``."""
    out = []
    for w in words[j + 1:]:
        out.append(_tok(w["w"]))
        if re.search(r"[.!?]$", w["w"].strip()):
            break
        if len(out) > 8:
            break
    return [t for t in out if t]


def is_reply(words, k):
    """The words from index ``k`` are a short reply ("Whoa.", "That's crazy.", "Really?"): the pause before
    them is the other speaker's beat."""
    sent = []
    for w in words[k:]:
        sent.append(_tok(w["w"]))
        if re.search(r"[.!?]$", w["w"].strip()) or len(sent) > 5:
            break
    sent = [t for t in sent if t]
    if not sent or len(sent) > 4:
        return False
    return sent[0] in REPLIES or len(sent) <= 2 and any(t in REPLIES for t in sent)


# --- sound -------------------------------------------------------------------------------------

def audio_levels(src, t0, t1, sr=16000):
    """Sound level of [t0, t1] of ``src`` in dBFS, one value per HOP (20 ms window). [] when unreadable."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t0):.3f}", "-t", f"{t1 - t0:.3f}", "-i", src,
                          "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, timeout=600).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    hop, win = int(sr * HOP), int(sr * HOP) * 2
    n = (len(x) - win) // hop
    if n <= 0:
        return []
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop][:n]
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    return list(20.0 * np.log10(rms))


class Levels:
    """The sound of a stretch of the source: dB per HOP from ``t0``, its speech level and silence threshold."""

    def __init__(self, t0, db):
        self.t0 = float(t0)
        self.db = list(db)
        loud = sorted(self.db)
        self.speech = loud[int(0.95 * (len(loud) - 1))] if loud else 0.0
        self.threshold = self.speech + SILENCE_DB

    def at(self, t):
        i = int(round((t - self.t0) / HOP))
        return self.db[min(max(i, 0), len(self.db) - 1)] if self.db else 0.0

    def silent(self, t):
        return self.at(t) < self.threshold

    def runs(self, a, b, min_len=SILENCE_MIN, level=None):
        """Silences of at least ``min_len`` inside [a, b] (source seconds), as (start, end)."""
        thr = self.threshold if level is None else level
        out, i = [], max(0, int(math.ceil((a - self.t0) / HOP)))
        last = min(len(self.db), int((b - self.t0) / HOP))
        while i < last:
            if self.db[i] < thr:
                j = i
                while j < last and self.db[j] < thr:
                    j += 1
                if (j - i) * HOP >= min_len - 1e-9:
                    out.append((round(self.t0 + i * HOP, 3), round(self.t0 + j * HOP, 3)))
                i = j
            else:
                i += 1
        return out

    def voice_from(self, t, until, min_voiced=0.10):
        """First moment from ``t`` where the voice holds for ``min_voiced`` s, or None before ``until``."""
        need = max(1, int(round(min_voiced / HOP)))
        i = max(0, int(round((t - self.t0) / HOP)))
        end = min(len(self.db), int(round((until - self.t0) / HOP)))
        run = 0
        while i < end:
            run = run + 1 if self.db[i] >= self.threshold else 0
            if run >= need:
                return round(self.t0 + (i - need + 1) * HOP, 3)
            i += 1
        return None

    def voice_until(self, t, since, min_voiced=0.10):
        """Last moment before ``t`` (and after ``since``) where the voice held for ``min_voiced`` s, or None."""
        need = max(1, int(round(min_voiced / HOP)))
        i = min(len(self.db) - 1, int(round((t - self.t0) / HOP)))
        stop = max(0, int(round((since - self.t0) / HOP)))
        run = 0
        while i >= stop:
            run = run + 1 if self.db[i] >= self.threshold else 0
            if run >= need:
                return round(self.t0 + (i + need) * HOP, 3)
            i -= 1
        return None

    def valley(self, a, b):
        """(t, dB) of the quietest HOP in [a, b]."""
        i0 = max(0, int(round((a - self.t0) / HOP)))
        i1 = min(len(self.db), int(round((b - self.t0) / HOP)) + 1)
        if i1 <= i0:
            return a, 0.0
        k = min(range(i0, i1), key=lambda i: self.db[i])
        return round(self.t0 + k * HOP, 3), self.db[k]


# --- the frame grid --------------------------------------------------------------------------------

_STANDARD_RATES = (24000 / 1001, 24.0, 25.0, 30000 / 1001, 30.0, 50.0, 60000 / 1001, 60.0)


class Grid:
    """The source's frames: one every 1/fps from ``phase``. Every cut point sits half a frame between two
    frames, so ffmpeg's trim keeps whole frames and each piece's picture lasts exactly as long as its sound."""

    def __init__(self, fps, phase=0.0):
        self.fps = float(fps)
        self.period = 1.0 / self.fps
        self.phase = float(phase)

    def index(self, t):
        """Index of the frame shown at ``t``."""
        return int(math.floor((t - self.phase) * self.fps + 1e-6))

    def snap(self, t):
        """The mid-frame point nearest ``t``."""
        k = round((t - self.phase) * self.fps - 0.5)
        return round(self.phase + (k + 0.5) * self.period, 6)

    def points(self, a, b):
        """Mid-frame points inside [a, b]."""
        k0 = int(math.ceil((a - self.phase) * self.fps - 0.5 - 1e-9))
        k1 = int(math.floor((b - self.phase) * self.fps - 0.5 + 1e-9))
        return [round(self.phase + (k + 0.5) * self.period, 6) for k in range(k0, k1 + 1)]


def standard_rate(rate):
    """30000/1001 for a probed 29.97037: the probe averages, the frames sit on the standard rate."""
    best = min(_STANDARD_RATES, key=lambda r: abs(r - rate))
    return best if abs(best - rate) < 0.02 else rate


def probe_grid(src, near):
    """The frame grid of ``src`` around ``near`` s: its rate and the time of one real frame there."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate,avg_frame_rate", "-of", "csv=p=0", src],
                         capture_output=True, text=True, timeout=60).stdout.strip().split("\n")[0].split(",")
    rate = 0.0
    for r in out:
        try:
            num, den = r.split("/")
            if float(den):
                rate = float(num) / float(den)
                break
        except ValueError:
            continue
    fps = standard_rate(rate or 30.0)
    pts = subprocess.run(["ffprobe", "-v", "error", "-read_intervals", f"{max(0.0, near - 0.2):.3f}%+0.4",
                          "-select_streams", "v:0", "-show_entries", "frame=pts_time,best_effort_timestamp_time",
                          "-of", "csv=p=0", src], capture_output=True, text=True, timeout=60).stdout.split()
    phase = 0.0
    for line in pts:
        for v in line.split(","):
            try:
                phase = float(v)
                break
            except ValueError:
                continue
        else:
            continue
        break
    return Grid(fps, phase % (1.0 / fps))


# --- planning (pure) -------------------------------------------------------------------------------

def _overlaps(a, b, c, d):
    return a < d and c < b


def _swallows(words, a, b, removed=()):
    """A cut [a, b] that would leave a word with almost nothing of it (Whisper put it in what the sound says
    is a silence: it is said elsewhere, and its caption must not vanish). ``removed``: (i, j), the indices of
    the words the cut is meant to take out (a passage's)."""
    for k, w in enumerate(words):
        if removed and removed[0] <= k <= removed[1]:
            continue
        if w["e"] <= a or w["s"] >= b:
            continue
        kept = max(0.0, a - w["s"]) + max(0.0, w["e"] - b)
        if kept < min(0.06, max(0.0, w["e"] - w["s"]) * 0.5) or (w["e"] - w["s"] < 0.02 and a <= w["s"] <= b):
            return True
    return False


def rank(join):
    """0 invisible (clean or a camera cut), 1 to hide, 2 too big, 3 none."""
    if join is None:
        return 3
    if join.get("camera") or join["jump"] <= JUMP_CLEAN:
        return 0
    return 1 if join["jump"] <= JUMP_HIDE else 2


def plan(start, end, words, levels, grid, *, hook_line=None, punchline=None, cut_out=(), judge=None,
         shot_cuts=(), silences=True, passages=True, log=print):
    """The re-cut of [start, end] (source seconds). ``words``: the source's words ({"w","s","e"}, sorted);
    ``levels``: a Levels covering the clip; ``grid``: the source's Grid; ``judge(left, right, keep, ok)``:
    the best join with its out point in ``left`` and its in point in ``right`` (FrameJudge), None when none
    is ``ok``; ``shot_cuts``: the source's camera cuts (source seconds).

    Returns {"start", "end", "removals": [...], "refused": [...]}: each removal {"a", "b" (the source cut
    out), "kind": "silence"|"passage", "why", "jump", "camera", "verdict": "clean"|"camera"|"hide"} — the
    "hide" ones still need a frame switch (punch_in.schedule_hides) or must be dropped (``drop``)."""
    # Every boundary on the frame grid (half a frame between two frames): each piece's picture then lasts
    # exactly as long as its sound, and the joins land on whole frames of the re-cut clip.
    start, end = grid.snap(float(start)), grid.snap(float(end))
    inside = [w for w in words if w["e"] > start and w["s"] < end]
    refused = []
    # --- the edges: the clip opens on the voice and does not trail off -------------------------
    first = next((w for w in inside if w["s"] >= start - 0.05), inside[0] if inside else None)
    if first is not None:
        onset = levels.voice_from(max(start, first["s"] - 0.35), min(end, first["e"] + 0.5))
        if onset is not None and onset - LEAD_IN > start + 0.03:
            # The sound says where the voice starts (Whisper opens the first word up to 0.4 s early);
            # never past the first word's end, should the sound be wrong.
            new = grid.snap(min(onset - LEAD_IN, first["e"] - 0.1))
            if new > start:
                start = new
    last = next((w for w in reversed(inside) if w["e"] <= end + 0.05), inside[-1] if inside else None)
    if last is not None:
        offset = levels.voice_until(end, max(start, last["s"] - 0.3))
        if offset is not None and end - offset > TAIL_MAX:
            end = grid.snap(offset + TAIL_KEEP)
    inside = [w for w in words if w["e"] > start and w["s"] < end]

    hook = find_span(inside, hook_line, start - 0.5, start + 6.0) if hook_line else None
    punch = find_last_span(inside, punchline, start, end) if punchline else None
    hook_span = (inside[hook[0]]["s"], inside[hook[1]]["e"]) if hook else None
    punch_span = (inside[punch[0]]["s"], inside[punch[1]]["e"]) if punch else None

    def ok_factory(removed=()):
        def ok(a, b):
            if b - a < MIN_GAIN - 1e-6 or _swallows(inside, a, b, removed):
                return False
            for c in shot_cuts:
                if a - MIN_SHOT < c < a or b < c < b + MIN_SHOT:
                    return False            # a flash of a shot on either side
            return True
        return ok

    def best_join(left, right, keep, ok, wide_max):
        """The judge's join; when it would show, a second look with a longer breath allowed."""
        first_ = judge(left, right, keep, ok) if judge else None
        if rank(first_) == 0 or wide_max <= keep[1] + 1e-6 or not judge:
            return first_
        second = judge(left, right, (keep[0], wide_max), ok)
        if rank(second) < rank(first_) or (second and first_ and rank(second) == rank(first_)
                                            and second["jump"] < first_["jump"] - 2.0):
            return second
        return first_

    removals = []
    # --- passages first (the clip choice's own cuts) --------------------------------------------
    for item in (cut_out if passages else ()) or ():
        if not isinstance(item, dict):
            continue
        label = f'"{item.get("from")}" … "{item.get("to")}"'
        span = find_passage(inside, item, start - 1.0, end)
        if span is None:
            refused.append({"kind": "passage", "what": label, "reason": "not_found"})
            continue
        i, j = span
        ws, we = inside[i]["s"], inside[j]["e"]
        if hook_span and _overlaps(ws, we, *hook_span):
            refused.append({"kind": "passage", "what": label, "reason": "hook"})
            continue
        if punch_span and _overlaps(ws, we, *punch_span):
            refused.append({"kind": "passage", "what": label, "reason": "punchline"})
            continue
        near = [_tok(inside[k]["w"]) for k in range(max(0, i - 1), min(len(inside), j + 2))]
        if any(is_negation(t) for t in near if t):
            refused.append({"kind": "passage", "what": label, "reason": "negation"})
            continue
        if i == 0 or j >= len(inside) - 1:
            refused.append({"kind": "passage", "what": label, "reason": "edge"})   # that is a new start/end
            continue
        left = _edge_region(levels, inside[i - 1]["e"], ws, before=True)
        right = _edge_region(levels, we, inside[j + 1]["s"], before=False)
        if left is None or right is None:
            refused.append({"kind": "passage", "what": label, "reason": "no_pause"})
            continue
        avail = (left[1] - left[0]) + (right[1] - right[0])
        keep = (min(BREATH, max(0.0, avail - 2 * EDGE)) * 0.5, BREATH + BREATH_SLACK)
        j_ = best_join(left, right, keep, ok_factory((i, j)), BREATH + WIDE_SLACK)
        if j_ is None:
            refused.append({"kind": "passage", "what": label, "reason": "no_join"})
            continue
        if rank(j_) >= 2:
            refused.append({"kind": "passage", "what": label, "reason": "jump", "jump": round(j_["jump"], 1)})
            continue
        if any(_overlaps(j_["a"], j_["b"], r["a"], r["b"]) for r in removals):
            refused.append({"kind": "passage", "what": label, "reason": "overlap"})
            continue
        removals.append({**j_, "kind": "passage", "why": item.get("why") or "", "what": label,
                         "region": (left[0], right[1])})

    # --- silences ----------------------------------------------------------------------------------
    if silences:
        for p0, p1 in levels.runs(start + 0.05, end - 0.05):
            if any(_overlaps(p0, p1, *r["region"]) for r in removals):
                continue                    # already inside a passage's edges
            length = p1 - p0
            nxt = next((k for k, w in enumerate(inside) if w["s"] >= p1 - 0.3), None)
            beat = False
            if punch_span and punch_span[0] - 0.6 <= p1 and p0 <= punch_span[1]:
                beat = True                 # before the payoff, or inside it ("…white coat. — No more.")
            elif nxt is not None and is_reply(inside, nxt):
                beat = True
            k = min(length, BEAT) if beat else BREATH
            if length - k < MIN_GAIN:
                continue
            keep = (k, k + BREATH_SLACK if not beat else min(length, k + 0.1))
            left = (p0, p1)
            j_ = best_join(left, left, keep, ok_factory(), min(length - MIN_GAIN, k + WIDE_SLACK))
            if j_ is None:
                refused.append({"kind": "silence", "what": f"{p0:.2f}-{p1:.2f}", "reason": "no_join"})
                continue
            removals.append({**j_, "kind": "silence", "why": "beat" if beat else "breath",
                             "what": f"{p0:.2f}-{p1:.2f}", "region": (p0, p1)})

    # --- verdicts ------------------------------------------------------------------------------
    kept = []
    for r in sorted(removals, key=lambda r: r["a"]):
        if r.get("camera"):
            r["verdict"] = "camera"
        elif rank(r) == 0:
            r["verdict"] = "clean"
        elif rank(r) == 1:
            r["verdict"] = "hide"
        else:
            refused.append({"kind": r["kind"], "what": r["what"], "reason": "jump", "jump": round(r["jump"], 1)})
            continue
        kept.append(r)
    # Never a piece shorter than MIN_PIECE between two joins (nor at the edges): the smaller saving goes.
    changed = True
    while changed:
        changed = False
        bounds = [start] + [x for r in kept for x in (r["a"], r["b"])] + [end]
        for n in range(len(kept) + 1):
            if bounds[2 * n + 1] - bounds[2 * n] < MIN_PIECE:
                cands = [kept[m] for m in (n - 1, n) if 0 <= m < len(kept)]
                worst = min(cands, key=lambda r: r["b"] - r["a"])
                kept.remove(worst)
                refused.append({"kind": worst["kind"], "what": worst["what"], "reason": "short_piece"})
                changed = True
                break
    return {"start": start, "end": end, "removals": kept, "refused": refused,
            "hook_span": hook_span, "punch_span": punch_span}


def _edge_region(levels, prev_end, word_s, before):
    """Where a passage edge may fall between two words: the silence there (the pause before its first word
    or after its last one), else the quietest dip near the boundary if it is close to silence. None when the
    speech runs on (no clean place to cut)."""
    lo, hi = (min(prev_end, word_s) - VALLEY_SPAN, max(prev_end, word_s) + VALLEY_SPAN)
    runs = levels.runs(lo, hi, min_len=2 * EDGE + 0.02)
    if runs:
        target = word_s if before else prev_end
        return min(runs, key=lambda r: 0 if r[0] <= target <= r[1] else min(abs(r[0] - target), abs(r[1] - target)))
    t, db = levels.valley(lo, hi)
    if db <= levels.threshold + VALLEY_DB:
        return (t - EDGE - 0.02, t + EDGE + 0.02)
    return None


def timeline(start, end, removals):
    """(segments, joins) of a re-cut: the kept stretches of the source in order ({"start","end"}, source
    seconds, recut.py's EDL) and, for each removal in source order, the clip time of its join."""
    segs, joins, at, t = [], [], float(start), 0.0
    for r in sorted(removals, key=lambda r: r["a"]):
        segs.append({"start": round(at, 6), "end": round(r["a"], 6)})
        t += r["a"] - at
        joins.append((r, round(t, 4)))
        at = r["b"]
    segs.append({"start": round(at, 6), "end": round(float(end), 6)})
    return segs, joins


# --- frames (the judge) -------------------------------------------------------------------------

_FACE_LOCK = threading.Lock()
_FACE = None


def _face_box(rgb):
    """The biggest face of an RGB frame as (x, y, w, h) in its pixels, or None."""
    global _FACE
    import mediapipe as mp
    with _FACE_LOCK:
        if _FACE is None:
            _FACE = mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)
        res = _FACE.process(rgb)
    if not res.detections:
        return None
    H, W = rgb.shape[:2]
    best = max(res.detections, key=lambda d: d.location_data.relative_bounding_box.width
               * d.location_data.relative_bounding_box.height)
    b = best.location_data.relative_bounding_box
    return (b.xmin * W, b.ymin * H, b.width * W, b.height * H)


_SIZES = {}


def video_size(src):
    """(width, height) of ``src``'s picture (cached)."""
    if src not in _SIZES:
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height", "-of", "csv=p=0", src], capture_output=True, text=True,
                               timeout=60).stdout.strip().split("\n")[0].split(",")
        _SIZES[src] = (int(probe[0]), int(probe[1]))
    return _SIZES[src]


def decode(src, t0, t1, width=REGION_W):
    """RGB frames of [t0, t1) of ``src`` at ``width`` px, and the source width."""
    import numpy as np
    sw, sh = video_size(src)
    h = int(round(sh * width / sw / 2) * 2)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t0):.4f}", "-t", f"{t1 - t0:.4f}", "-i", src,
                          "-an", "-vf", f"scale={width}:{h}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, timeout=600).stdout
    size = width * h * 3
    frames = [np.frombuffer(raw[i * size:(i + 1) * size], dtype=np.uint8).reshape(h, width, 3)
              for i in range(len(raw) // size)]
    return frames, sw


def head_region(box, w, h):
    """Head and shoulders around a face box (x, y, w, h), inside a w x h frame: what a jump shows on."""
    if box is None:
        return (int(w * 0.25), 0, int(w * 0.5), h)
    x, y, bw, bh = box
    x0, x1 = max(0, int(x - 0.6 * bw)), min(w, int(x + 1.6 * bw))
    y0, y1 = max(0, int(y - 0.7 * bh)), min(h, int(y + 1.9 * bh))
    return (x0, y0, max(8, x1 - x0), max(8, y1 - y0))


def crop_region(box, w, h):
    """What the vertical clip will show around the face: a 9:16 band of the frame's height (a hand or a
    paper coming in there shows as much as the head does)."""
    cw = min(w, int(round(h * 9 / 16)))
    cx = (box[0] + box[2] / 2.0) if box else w / 2.0
    return (int(min(max(cx - cw / 2.0, 0), w - cw)), 0, cw, h)


def jump_px(f_a, f_b, region, scale):
    """How far the head jumps between two frames: the 90th percentile of the optical flow over ``region``,
    in source pixels (``scale`` = source width / analysis width)."""
    import cv2
    import numpy as np
    x, y, w, h = region
    a = cv2.cvtColor(f_a[y:y + h, x:x + w], cv2.COLOR_RGB2GRAY)
    b = cv2.cvtColor(f_b[y:y + h, x:x + w], cv2.COLOR_RGB2GRAY)
    k = 160.0 / max(w, h)
    if k < 1.0:
        a = cv2.resize(a, (max(8, int(w * k)), max(8, int(h * k))), interpolation=cv2.INTER_AREA)
        b = cv2.resize(b, (max(8, int(w * k)), max(8, int(h * k))), interpolation=cv2.INTER_AREA)
    else:
        k = 1.0
    flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
    return float(np.percentile(mag, 90)) / k * scale


def _thumb(f):
    import cv2
    return cv2.resize(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), (32, 18), interpolation=cv2.INTER_AREA).astype("float32")


def thumb_diff(f_a, f_b):
    import numpy as np
    return float(np.mean(np.abs(_thumb(f_a) - _thumb(f_b))))


def _mad(f_a, f_b, region):
    import cv2
    import numpy as np
    x, y, w, h = region
    a = cv2.resize(f_a[y:y + h, x:x + w], (48, 48), interpolation=cv2.INTER_AREA).astype("float32")
    b = cv2.resize(f_b[y:y + h, x:x + w], (48, 48), interpolation=cv2.INTER_AREA).astype("float32")
    return float(np.mean(np.abs(a - b)))


def candidate_pairs(grid, left, right, keep, ok=None):
    """Every (out, in) pair of a join on the frame grid: the out point in ``left``, the in point in
    ``right``, EDGE of silence at least on each side, the silence kept around the join ((out - left start)
    + (right end - in)) within ``keep``, and ``ok(out, in)``."""
    outs = [p for p in grid.points(left[0] + EDGE, left[1]) if p - left[0] <= keep[1] + 1e-6]
    ins = [p for p in grid.points(right[0], right[1] - EDGE) if right[1] - p <= keep[1] + 1e-6]
    return [(a, b) for a in outs for b in ins
            if b > a and keep[0] - 1e-6 <= (a - left[0]) + (right[1] - b) <= keep[1] + 1e-6
            and (ok is None or ok(a, b))]


class FrameJudge:
    """Picks the best pair of frames for a join (see ``plan``'s ``judge``) by looking at the source."""

    def __init__(self, src, grid, width=REGION_W):
        self.src, self.grid, self.width = src, grid, width
        self.looked = []        # (out frame, in frame, measures) of every join chosen: the bench's boards

    def _frames(self, a, b):
        # From a mid-frame point: frame i of the list is the source frame at t0 + (i + 0.5) / fps.
        t0 = self.grid.snap(a - 2 * self.grid.period)
        frames, sw = decode(self.src, t0, b + 2 * self.grid.period, self.width)
        return t0, frames, sw

    def __call__(self, left, right, keep, ok):
        g = self.grid
        pairs = candidate_pairs(g, left, right, keep, ok)
        if not pairs:
            return None
        outs, ins = [a for a, _ in pairs], [b for _, b in pairs]
        same = right[0] - left[1] < 1.0
        if same:
            t0, frames, sw = self._frames(min(outs), max(ins))
            t0r, frames_r = t0, frames
        else:
            t0, frames, sw = self._frames(min(outs), max(outs))
            t0r, frames_r, _ = self._frames(min(ins), max(ins))

        def frame_out(a):        # the last frame kept before the join
            i = int(round((a - t0) * g.fps - 1.0))
            return frames[min(max(i, 0), len(frames) - 1)] if frames else None

        def frame_in(b):         # the first frame after it
            i = int(round((b - t0r) * g.fps))
            return frames_r[min(max(i, 0), len(frames_r) - 1)] if frames_r else None

        if not frames or not frames_r:
            return None
        h, w = frames[0].shape[:2]
        scale = sw / float(w)
        box = _face_box(frame_out(pairs[0][0])) or _face_box(frame_in(pairs[0][1]))
        head = head_region(box, w, h)
        view = crop_region(box, w, h)
        # A cheap look at every pair, the optical flow on the closest ones.
        scored = sorted(((_mad(frame_out(a), frame_in(b), view), a, b) for a, b in pairs))[:10]
        best = None
        for mad, a, b in scored:
            fa, fb = frame_out(a), frame_in(b)
            camera = thumb_diff(fa, fb) > CAMERA_DIFF
            flow = 0.0 if camera else jump_px(fa, fb, head, scale)
            jump = 0.0 if camera else max(flow, MAD_SCALE * mad)
            kept = (a - left[0]) + (right[1] - b)
            rank = 0 if camera or jump <= JUMP_CLEAN else 1 if jump <= JUMP_HIDE else 2
            key = (rank, kept + 0.01 * jump) if rank == 0 else (rank, jump)
            if best is None or key < best[0]:
                best = (key, {"a": a, "b": b, "jump": round(jump, 2), "flow": round(flow, 2), "mad": round(mad, 2),
                              "camera": camera, "kept": round(kept, 3), "face": box is not None}, fa, fb)
        self.looked.append((best[2], best[3], best[1]))
        return best[1]


def shot_cuts(src, t0, t1, fps=SHOT_FPS):
    """The source's camera cuts in [t0, t1] (s), from grey thumbnails at ``fps``."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t0):.3f}", "-t", f"{t1 - t0:.3f}", "-i", src,
                          "-an", "-vf", f"fps={fps},scale=32:18:flags=area,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, timeout=600).stdout
    n = len(raw) // (32 * 18)
    th = [np.frombuffer(raw[i * 576:(i + 1) * 576], dtype=np.uint8).astype("float32") for i in range(n)]
    return [round(t0 + i / fps, 2) for i in range(1, n) if float(np.mean(np.abs(th[i] - th[i - 1]))) > CAMERA_DIFF]


# --- the cut -----------------------------------------------------------------------------------

def _rate(fps):
    """ffmpeg's spelling of a frame rate (30000/1001, not 29.97003)."""
    for num, den in ((24000, 1001), (30000, 1001), (60000, 1001)):
        if abs(fps - num / den) < 1e-4:
            return f"{num}/{den}"
    return f"{fps:.6f}".rstrip("0").rstrip(".")


def cut_command(src, segments, out, fade=FADE, normalize=True, video_args=None, fps=None):
    """One ffmpeg pass: every segment of ``src`` (source seconds, on the frame grid) back to back, a ``fade``
    fade in and out on each piece's sound (no click), loudness normalised like every cut (ffmpeg_utils).
    ``fps``: the source's rate, written as the output's constant rate (the frames already sit on it; the
    reframe reads its scene times from it)."""
    from ffmpeg_utils import LOUDNORM_FILTER, METADATA_SCRUB, QUALITY_FAST, video_encode_args
    t0 = max(0.0, min(s["start"] for s in segments) - 1.0)
    parts, labels = [], []
    for k, s in enumerate(segments):
        a, b = s["start"] - t0, s["end"] - t0
        d = b - a
        f = min(fade, d / 4)
        parts.append(f"[0:v]trim=start={a:.6f}:end={b:.6f},setpts=PTS-STARTPTS[v{k}]")
        parts.append(f"[0:a]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:st=0:d={f:.4f},afade=t=out:st={max(0.0, d - f):.6f}:d={f:.4f}[a{k}]")
        labels.append(f"[v{k}][a{k}]")
    audio_tail = f",{LOUDNORM_FILTER}" if normalize else ""
    parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=1[v][ca]")
    parts.append(f"[ca]aresample=48000{audio_tail},aresample=48000[a]")
    return ["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.6f}", "-i", src,
            "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
            *(["-r", _rate(fps)] if fps else []),
            *(video_args or video_encode_args(QUALITY_FAST)), "-c:a", "aac", *METADATA_SCRUB,
            "-movflags", "+faststart", out]


def cut(src, segments, out, fps=None):
    """Write the re-cut clip. Raises with ffmpeg's own words when it fails."""
    normalize = os.environ.get("AUDIO_NORMALIZE", "1").strip() != "0"
    r = subprocess.run(cut_command(src, segments, out, normalize=normalize, fps=fps), capture_output=True,
                       text=True, errors="replace", timeout=1800)
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 1024:
        raise RuntimeError(f"montage cut failed: {(r.stderr or '')[-600:]}")
    return out


# --- the whole thing, for main.py ------------------------------------------------------------------

def settle(plan_, shots=(), hide=True):
    """Give every join to hide its tight frame (punch_in.schedule_hides), dropping the ones that cannot
    get one — each drop moves the joins after it, so it is scheduled again until it holds.
    Returns (segments, joins [(removal, clip t)], hide windows, camera events in clip time)."""
    import punch_in
    import recut
    while True:
        segs, joins = timeline(plan_["start"], plan_["end"], plan_["removals"])
        duration = recut.total_duration(segs)
        cams = sorted({round(t, 3) for r, t in joins if r["verdict"] == "camera"}
                      | {round(c, 3) for c in (recut.source_to_clip(segs, s) for s in shots) if c is not None})
        events = [(c, c) for c in cams]
        todo = [(r, t) for r, t in joins if r["verdict"] == "hide"]
        if not hide:
            windows, refused = [], list(range(len(todo)))
        else:
            windows, refused = punch_in.schedule_hides([t for _, t in todo], duration, events)
        if not refused:
            return segs, joins, windows, events
        for n in refused:
            r = todo[n][0]
            plan_["removals"].remove(r)
            plan_["refused"].append({"kind": r["kind"], "what": r["what"], "reason": "spacing" if hide else "hide_off",
                                     "jump": round(r["jump"], 1)})


def prepare(src, clip, transcript, start, end, cfg=None, log=print):
    """Plan the re-cut of a clip (source seconds [start, end]). Returns the report main.py stores, or None
    when nothing is worth changing. Report: {"segments" (the EDL), "duration", "saved", "joins" [{"t",
    "kind", "why", "verdict", "jump", "kept", "src"}], "hide_windows" [(a, b)] (tight frames the finish
    must cut in), "camera_cuts" [t] (clip seconds), "refused" [...], "punch" (start, end) in clip seconds,
    "start"/"end" (the covering source range), "fps"}."""
    import recut
    cfg = cfg if cfg is not None else config()
    words = recut.transcript_words(transcript)
    if not words:
        return None
    grid = probe_grid(src, start)
    levels = Levels(start - 1.0, audio_levels(src, max(0.0, start - 1.0), end + 1.0))
    if not levels.db:
        return None
    shots = shot_cuts(src, max(0.0, start - 1.0), end + 1.0)
    judge = FrameJudge(src, grid)
    p = plan(start, end, words, levels, grid, hook_line=clip.get("hook_line"), punchline=clip.get("punchline"),
             cut_out=clip.get("cut_out") or (), judge=judge, shot_cuts=shots,
             silences=cfg.get("silences", True), passages=cfg.get("cut_out", True), log=log)
    segs, joins, windows, events = settle(p, shots, hide=cfg.get("hide_joins", True))
    duration = recut.total_duration(segs)
    punch = None
    if p.get("punch_span"):
        a = recut.source_to_clip(segs, p["punch_span"][0])
        b = recut.source_to_clip(segs, p["punch_span"][1] - 1e-3)
        if a is not None and b is not None:
            punch = (round(a, 3), round(b, 3))
    report = {
        "v": 1,
        "segments": segs,
        "start": segs[0]["start"], "end": segs[-1]["end"],
        "duration": duration,
        "saved": round((float(end) - float(start)) - duration, 2),
        "joins": [{"t": t, "kind": r["kind"], "why": r["why"], "verdict": r["verdict"], "jump": r["jump"],
                   "kept": r["kept"], "src": [round(r["a"], 3), round(r["b"], 3)]} for r, t in joins],
        "hide_windows": [list(w) for w in windows],
        "camera_cuts": [a for a, _ in events],
        "refused": p["refused"],
        "punch": punch,
        "fps": grid.fps,
    }
    if len(segs) == 1 and abs(report["saved"]) < 0.05:
        return None
    return report


def apply(src, clip, transcript, start, end, out_path, cfg=None, log=print):
    """main.py's montage step: plan the re-cut of [start, end], write it to ``out_path``, and record it in
    the clip: ``clip["recipe"]`` (the EDL, recut.py's format, read back by the editor and the API),
    ``clip["montage"]`` (the report), ``clip["start"]/["end"]`` (the source range it covers) and a
    ``punchline_time`` moved onto the new timeline. Returns the report plus "transcript" (the virtual one,
    clip seconds), or None — nothing written, nothing changed — when there is nothing to tighten or when
    anything fails (the clip is then cut as it always was)."""
    import recut
    try:
        report = prepare(src, clip, transcript, start, end, cfg, log)
        if not report:
            log("   ✂️ Montage: nothing to tighten — the clip is cut as it is.")
            return None
        cut(src, report["segments"], out_path, fps=report["fps"])
    except Exception as e:
        log(f"   ⚠️ Montage failed ({type(e).__name__}: {e}) — the clip is cut as it is.")
        return None
    segs = report["segments"]
    old_start = float(start)
    clip["recipe"] = {"v": 1, "segments": segs,
                      # The canonical file IS the first segment from t=0 on: the editor's fast path may cut
                      # inside it (recut.rebase_segments), never across a join.
                      "canonical_range": dict(segs[0])}
    if clip.get("punchline_time") is not None:
        moved = recut.source_to_clip(segs, old_start + float(clip["punchline_time"]))
        if moved is None:
            clip.pop("punchline_time", None)
        else:
            clip["punchline_time"] = round(moved, 2)
    clip["start"], clip["end"] = round(report["start"], 3), round(report["end"], 3)
    clip["montage"] = {k: v for k, v in report.items() if k not in ("segments", "fps")}
    log(f"   ✂️ Montage: {float(end) - old_start:.1f}s -> {report['duration']:.1f}s ({describe(report)})")
    return {**report, "transcript": recut.virtual_transcript(transcript, segs)}


def inset_on_clip(found, report):
    """screen_inset.detect's answer for the covering range [report start, end] (its t0/t1 in seconds from
    that start) moved onto the re-cut clip: t0/t1 in clip seconds, src_t0/src_t1 the source seconds. None
    when the cut left the picture out."""
    import recut
    if not found:
        return None
    a = float(report["start"]) + float(found["t0"])
    b = float(report["start"]) + float(found["t1"])
    spans = recut.source_range_to_clip(report["segments"], a, b)
    if not spans:
        return None
    return {**found, "t0": round(spans[0][0], 2), "t1": round(spans[-1][1], 2),
            "src_t0": round(a, 2), "src_t1": round(b, 2)}


def broll_block(clip, report=None, margin=0.3):
    """(from, to) clip seconds no picture may cover (broll.add_broll's ``block``: none starts inside, one
    starting before is shortened to leave first): the reactions (the image study found two hidden under
    the hero) and the tight frames hiding the joins."""
    out = []
    for r in clip.get("reactions") or []:
        a = float(r["at"])
        out.append((round(a - margin, 2), round(a + float(r.get("dur") or 1.2) + margin, 2)))
    for a, b in (report or {}).get("hide_windows") or []:
        out.append((round(a - margin, 2), round(b + margin, 2)))
    return out


def describe(report):
    """One log line."""
    j = report.get("joins") or []
    kinds = {}
    for x in j:
        kinds[x["verdict"]] = kinds.get(x["verdict"], 0) + 1
    ref = report.get("refused") or []
    bits = [f"{report.get('saved', 0):.1f} s saved", f"{len(j)} join(s)"]
    if kinds:
        bits.append(", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    if ref:
        reasons = {}
        for x in ref:
            reasons[x["reason"]] = reasons.get(x["reason"], 0) + 1
        bits.append("refused: " + ", ".join(f"{n} {k}" for k, n in sorted(reasons.items())))
    return "; ".join(bits)
