"""Smart zooms, the way OptimalHealth and Clip Storm cut a talking head (plus.FX["zoom_style"] = "references").

What their Shorts do, read one frame a second (output/_stepup/etude2/references/zoom, 9-oct-2026): the size
of the head changes nearly every second. Two moves, nothing else (no shake, no rotation, no motion blur):

1. a DRY PUNCH-IN — the frame jumps to a tight one (x1.13-1.26, the decoding of 12 OptimalHealth Shorts,
   etude2/decodage/rapport.md) on a word that carries the line, and back (x0.83-0.88);
2. a SLOW PUSH between two punches (about 1.00 -> 1.06 over a 2-4 s stretch), so the picture is never frozen.

The user wants a « zoom intelligent » (9-oct-2026): not a metronome, the zoom follows what is said. So:

* IN (a dry cut to the tight frame) on a strong moment: a word said louder or higher than the words around it
  (the clip's own sound), a number, a shock or insistence word (really, never, crazy), an emotion word, the
  start of the clip's punchline (already chosen by the clip choice), every montage join that would show (the
  switch hides it, montage.py), and to RELAUNCH a stretch with no change on screen for RELAUNCH s (theirs:
  never ~7 s without a change);
* OUT (back to the wide frame) at the start of a new sentence after a pause, after TIGHT_MAX s at most, on the
  clip's last sentence (« on s'éloigne à la fin »), at a camera cut of the source, and before a full-screen
  picture when its time is known;
* a slow push on every stretch, wide or tight, restarting at each switch and after a picture;
* never two dry cuts within MIN_GAP s, never inside a word; the eyes stay on the same line (the zoom pivots
  on them); the face never leaves the frame (the punch shrinks when it would); a head that moves a lot gets
  a smaller punch.

No AI call: the words and their timings (the transcript), the clip's sound, the punchline the clip choice
already gave. The plan is pure (``plan``), the boxes are pure (``shot_boxes``); ``prosody`` reads the sound
and ``render_segment`` crops each frame from the SOURCE with a sub-pixel box (the integer crop of ffmpeg
steps and shimmers on a slow zoom), so the punch costs no second resampling.
"""
import json
import math
import os
import re
import subprocess

import numpy as np

# --- the recipe ----------------------------------------------------------------------------------
PUNCH = 1.20            # the tight frame on a 1080p source (OptimalHealth: x1.13-1.26)...
PUNCH_HI = 1.25         # ...from 1440p up
PUNCH_MIN = 1.12        # under this a punch does not read as one: the moment stays wide
TOTAL_MAX = 1.42        # the tightest crop of a 1080p source, against its full-height crop (2.5x upscale)...
TOTAL_MAX_HI = 1.70     # ...from 1440p up
SLOW_RATE = 0.02        # per second: the slow push (1.00 -> 1.06 over 3 s)...
SLOW_MAX = 0.10         # ...at most this much over one stretch (a 10 s stretch creeps 1.00 -> 1.10)
MIN_GAP = 1.2           # s between two dry cuts, never less (the user's rule)
TIGHT_MIN = 1.2         # s a tight frame lasts at least...
TIGHT_MAX = 3.0         # ...and at most (the punchline: PUNCH_HOLD)
PUNCH_HOLD = 4.0
RELAUNCH = 5.0          # s without any change on screen: a dry punch-in relaunches (theirs: 6 s, never ~7)
LAST_S = 6.0            # s: a last sentence starting this close to the end is said wide
CUT_GAP = 0.6           # s: no switch this close to a camera cut of the source (a double cut)
END_GAP = 0.8           # s: no switch this close to the clip's end...
START_GAP = 1.0         # ...nor to its start (the opening frame holds under the hook)
PAUSE = 0.30            # s of silence before a word: it opens a new idea
SCORE_MIN = 1.5         # a moment weaker than this is not punched (a pitch rise alone on a content word is 1.5+)
EMPH_DB = 3.0           # dB over the words around it: a word said louder
EMPH_PITCH = 0.15       # a voice this much higher than around it (over PITCH_JUMP: a misread pitch)
PITCH_JUMP = 0.80
MARGIN = 0.04           # of the output width/height kept free around the head
HEAD_W = 1.20           # head width over the face box width (framing.HEAD_W)
EYE = 0.12              # of the face box height above its centre: the eyes
MOVE_SOFT = (0.06, 0.30)  # head travel (of the crop width) over a stretch: from the first, the punch shrinks...
MOVE_KEEP = 0.45        # ...down to this share of itself at the second

NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                "twelve", "thirteen", "fifteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
                "ninety", "hundred", "hundreds", "thousand", "thousands", "million", "millions", "billion",
                "billions", "trillion", "percent", "half", "twice", "double", "triple", "tenfold", "first",
                "dozen", "dozens"}
SHOCK_WORDS = {"never", "always", "nobody", "nothing", "everyone", "everything", "every", "worst", "best", "most",
               "dangerous", "deadly", "toxic", "poison", "illegal", "secret", "lie", "lies", "lied", "lying", "fake",
               "wrong", "truth", "insane", "crazy", "terrible", "horrible", "huge", "massive", "enormous", "tiny",
               "impossible", "incredible", "unbelievable", "shocking", "disaster", "destroy", "destroys", "destroyed",
               "kill", "kills", "killing", "drunk", "addicted", "addiction", "cancer", "damage", "damaged", "brain",
               "zero", "only", "exactly", "literally", "absolutely", "completely", "totally", "dramatically",
               "massively", "radically", "fastest", "biggest", "strongest", "worse", "better", "must", "stop",
               "really", "seriously", "actually", "definitely",
               "warning", "problem", "danger", "risk", "free", "rich", "money", "die", "dies", "dying", "dead"}
EMOTION_WORDS = {"wow", "whoa", "woah", "haha", "hahaha", "laughs", "laughter", "laughing", "oh", "omg", "jesus",
                 "god", "holy", "damn", "shit", "fuck", "fucking", "wild", "amazing", "love", "hate", "scared",
                 "afraid", "terrified", "angry", "furious", "excited", "beautiful", "awful", "disgusting", "unreal"}


def style():
    """plus.FX["zoom_style"] as the job carries it (PLUS_FX_JSON): "references" or "fixed" (the default)."""
    try:
        fx = json.loads(os.environ.get("PLUS_FX_JSON") or "{}")
    except ValueError:
        return "fixed"
    return "references" if (fx or {}).get("zoom_style") == "references" else "fixed"


def configure():
    """plus.ZOOMS as the job carries it (PLUS_ZOOMS_JSON) over the numbers above."""
    global PUNCH, PUNCH_HI, SLOW_RATE, SLOW_MAX, MIN_GAP, RELAUNCH
    try:
        cfg = json.loads(os.environ.get("PLUS_ZOOMS_JSON") or "{}") or {}
    except ValueError:
        return
    PUNCH = float(cfg.get("punch", PUNCH))
    PUNCH_HI = float(cfg.get("punch_hi", PUNCH_HI))
    SLOW_RATE = float(cfg.get("slow_rate", SLOW_RATE))
    SLOW_MAX = float(cfg.get("slow_max", SLOW_MAX))
    MIN_GAP = float(cfg.get("min_gap", MIN_GAP))
    RELAUNCH = float(cfg.get("relaunch", RELAUNCH))


def punch_for(source_height):
    return (PUNCH_HI, TOTAL_MAX_HI) if source_height >= 1440 else (PUNCH, TOTAL_MAX)


# --- the cues: what main.py knows that the reframe does not -----------------------------------------

def cues_path(video):
    return video + ".zooms.json"


def write_cues(video, words, joins=(), punch=None, pictures=()):
    """Next to the cut clip, for reframe_v2: its words in clip seconds ({"text", "start", "end"}), the montage
    joins to hide (clip seconds), the punchline (start, end) and the full-screen pictures [(a, b)] if known."""
    with open(cues_path(video), "w", encoding="utf-8") as f:
        json.dump({"words": [{"text": w["text"], "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)}
                             for w in words or []],
                   "joins": [round(float(t), 4) for t in joins or ()],
                   "punch": list(punch) if punch else None,
                   "pictures": [[round(float(a), 3), round(float(b), 3)] for a, b in pictures or ()]}, f)


def mark_applied(video, switches):
    """The reframe rendered the zooms: the plan goes into the cues for main.py (clip["zooms"])."""
    cues = read_cues(video)
    if cues is None:
        return
    cues["applied"] = [{k: s[k] for k in ("t", "to", "why", "word", "hidden") if k in s} for s in switches]
    with open(cues_path(video), "w", encoding="utf-8") as f:
        json.dump(cues, f)


def read_cues(video):
    try:
        with open(cues_path(video), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# --- the sound: how loud and how high each word is said ----------------------------------------------

def _audio(video, rate=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                         capture_output=True, timeout=600).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def frame_features(samples, rate=16000, hop=0.01, win=0.04):
    """Per 10 ms: loudness (dBFS) and pitch (Hz, 0 when unvoiced) by autocorrelation over 40 ms."""
    h, n = int(hop * rate), int(win * rate)
    count = max(0, (len(samples) - n) // h + 1)
    db = np.full(count, -90.0, dtype=np.float32)
    f0 = np.zeros(count, dtype=np.float32)
    lo, hi = int(rate / 320), int(rate / 70)
    window = np.hanning(n).astype(np.float32)
    for k in range(count):
        x = samples[k * h:k * h + n]
        rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
        db[k] = 20 * math.log10(rms)
        if db[k] < -40:
            continue
        y = (x - x.mean()) * window
        spec = np.fft.rfft(y, 2 * n)
        ac = np.fft.irfft(spec * np.conj(spec))[:n]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        top = float(seg.max())
        if top / ac[0] <= 0.45:
            continue
        # The shortest period whose peak is nearly as strong as the strongest: no octave error (a period
        # counted twice reads as a voice an octave lower, half a period as one an octave higher).
        for j in range(1, len(seg) - 1):
            if seg[j] >= 0.9 * top and seg[j] >= seg[j - 1] and seg[j] >= seg[j + 1]:
                f0[k] = rate / float(lo + j)
                break
    return db, f0


def prosody(video, words, rate=16000):
    """[(dB, pitch Hz or None)] per word: the loudest tenth of the word, the median of its voiced pitch."""
    if not words:
        return []
    db, f0 = frame_features(_audio(video, rate), rate)
    return word_prosody(db, f0, words)


def word_prosody(db, f0, words, hop=0.01):
    out = []
    for w in words:
        a, b = int(float(w["start"]) / hop), max(int(float(w["start"]) / hop) + 1, int(float(w["end"]) / hop))
        d = db[a:b]
        p = f0[a:b]
        p = p[p > 0]
        out.append((float(np.percentile(d, 90)) if len(d) else -90.0, float(np.median(p)) if len(p) >= 3 else None))
    return out


# --- the plan: where the dry cuts fall, and why -------------------------------------------------------

def _bare(text):
    return re.sub(r"[^\w%$']", "", str(text or "").lower()).strip("'")


def _opens_idea(words, i):
    """Word ``i`` starts a sentence after a pause (or the previous one closed a sentence)."""
    if i == 0:
        return True
    prev = words[i - 1]
    return (float(words[i]["start"]) - float(prev["end"]) >= PAUSE
            or bool(re.search(r"[.!?]$", str(prev["text"]).strip())))


def moments(words, pros=None, punch=None):
    """Strong moments: [{"i", "t", "score", "why", "word"}] — a word louder or higher than its neighbours (a
    content word), a number, a shock word, an emotion word, the punchline's first word."""
    from viral_fx import keyword_score
    pros = pros or [(None, None)] * len(words)
    out = []
    for i, w in enumerate(words):
        b = _bare(w["text"])
        if not b:
            continue
        score, why = 0.0, []
        ks = keyword_score(w["text"])
        if re.search(r"\d", b) or b in NUMBER_WORDS:
            score += 3.0
            why.append("chiffre")
        if b in SHOCK_WORDS:
            score += 2.5
            why.append("mot-choc")
        if b in EMOTION_WORDS:
            score += 2.5
            why.append("émotion")
        db, hz = pros[i] if i < len(pros) else (None, None)
        content = ks > 0 or bool(why)
        if db is not None and content:
            t = float(w["start"])
            near = [pros[k][0] for k, x in enumerate(words) if k != i and abs(float(x["start"]) - t) <= 3.0
                    and k < len(pros) and pros[k][0] is not None and pros[k][0] > -60]
            if len(near) >= 4:
                rise = db - float(np.median(near))
                if rise >= EMPH_DB:
                    score += 1.0 + min(1.5, (rise - EMPH_DB) * 0.4)
                    why.append(f"appuyé +{rise:.0f} dB")
            pitches = [pros[k][1] for k, x in enumerate(words) if k != i and abs(float(x["start"]) - t) <= 3.0
                       and k < len(pros) and pros[k][1]]
            if hz and len(pitches) >= 4:
                up = hz / float(np.median(pitches)) - 1.0
                if EMPH_PITCH <= up <= PITCH_JUMP:
                    score += 1.5
                    why.append(f"voix +{up * 100:.0f} %")
        if punch and abs(float(w["start"]) - float(punch[0])) < 0.25:
            score += 5.0
            why.insert(0, "chute")
        if not why:
            continue
        score += 0.5 * ks
        out.append({"i": i, "t": float(w["start"]), "score": round(score, 2), "why": ", ".join(why),
                    "word": str(w["text"]).strip()})
    return out


def _free(t, words):
    """No word is being said at ``t`` (a word's own start is free: the cut lands on it)."""
    return not any(float(w["start"]) + 0.02 < t < float(w["end"]) - 0.02 for w in words)


def plan(duration, words, pros=None, joins=(), cuts=(), punch=None, pictures=()):
    """The dry cuts of a clip: [{"t", "to": "tight"|"wide", "why", "word"}] in clip seconds, sorted.

    ``joins``: montage joins to hide (a switch on each, whichever way); ``cuts``: the source's camera cuts (the
    frame goes back wide there, no switch within CUT_GAP); ``punch``: the punchline (start, end); ``pictures``:
    full-screen pictures [(a, b)] (wide before each, no punch under one)."""
    words = [w for w in words or [] if float(w["end"]) > float(w["start"]) - 1e-6]
    joins = sorted(float(t) for t in joins or ())
    cuts = sorted(float(t) for t in cuts or ())
    pictures = sorted((float(a), float(b)) for a, b in pictures or ())
    cands = sorted(moments(words, pros, punch), key=lambda m: m["t"])
    opens = [i for i in range(len(words)) if _opens_idea(words, i)]
    open_set = set(opens)
    by_word = {m["i"]: m for m in cands}
    from viral_fx import keyword_score
    # The clip's last sentence, when it starts in its last LAST_S s: the frame goes wide there and stays (« on
    # s'éloigne à la fin »), unless the punchline is what opens it.
    last_open = None
    if opens and float(words[opens[-1]]["start"]) >= duration - LAST_S and opens[-1] > 0:
        last_open = float(words[opens[-1]]["start"])
        if punch and abs(last_open - float(punch[0])) < 0.25:
            last_open = None
    out = []
    tight, since, t_in, hold = False, -1e9, None, TIGHT_MAX

    def near_cut(t):
        return any(abs(t - c) < CUT_GAP for c in cuts)

    def under_picture(t, pad=0.0):
        return any(a - pad <= t < b for a, b in pictures)

    edges = [x for ab in pictures for x in ab]

    def ok(t, last):
        return (t - last >= MIN_GAP - 1e-6 and START_GAP <= t <= duration - END_GAP and not near_cut(t)
                and _free(t, words)
                and not any(abs(t - j) < MIN_GAP - 1e-6 for j in joins)
                and not any(abs(t - x) < MIN_GAP - 1e-6 for x in edges))

    # The events in time order: joins (forced), camera cuts (back wide), pictures (back wide before), moments.
    t = 0.0
    j_iter = list(joins)
    while True:
        nxt_join = next((j for j in j_iter if j > t + 1e-6), None)
        nxt_cut = next((c for c in cuts if c > t + 1e-6), None)
        if tight:
            # Back wide: a new idea after TIGHT_MIN, at most after ``hold``; a camera cut or a picture first.
            lim = t_in + hold
            pic = next((a for a, _ in pictures if a > t_in), None)
            back = None
            for i in opens:
                s = float(words[i]["start"])
                if t_in + TIGHT_MIN <= s <= lim and ok(s, since):
                    back = (s, "nouvelle phrase", str(words[i]["text"]).strip())
                    break
            if back is None:
                # No new idea in time: the word boundary nearest the end of the hold, a gap first.
                best = None
                for k, w in enumerate(words):
                    s = float(w["start"])
                    if t_in + TIGHT_MIN <= s <= lim + 0.6 and ok(s, since):
                        gap = s - float(words[k - 1]["end"]) if k else 1.0
                        cost = abs(s - (t_in + min(hold, TIGHT_MAX) - 0.3)) - min(gap, 0.3)
                        if best is None or cost < best[0]:
                            best = (cost, s, str(w["text"]).strip())
                if best:
                    back = (best[1], "fin du plan serré", best[2])
            events = []
            if back:
                events.append(back)
            if pic is not None and pic - since >= 0.3:
                # Before the picture comes: wide (the cut lands under the picture's own cut, never a flash).
                events.append((pic, "image plein écran", ""))
            if nxt_cut is not None:
                events.append((nxt_cut, "coupe caméra", ""))
            if nxt_join is not None and nxt_join - since >= 0.3:
                events.append((nxt_join, "raccord caché", ""))
            if last_open and last_open > t + 1e-6 and ok(last_open, since):
                events.append((last_open, "dernière phrase", str(words[opens[-1]]["text"]).strip()))
            if not events:
                break
            tb, why, word = min(events, key=lambda e: e[0])
            if why in ("image plein écran", "coupe caméra"):
                # The frame goes wide under the picture or with the source's own cut: not a cut of ours.
                out.append({"t": round(tb, 3), "to": "wide", "why": why, "word": word, "hidden": True})
                tight, t = False, tb
                if why == "coupe caméra":
                    since = tb
                continue
            out.append({"t": round(tb, 3), "to": "wide", "why": why, "word": word})
            tight, since, t = False, tb, tb
            if why == "raccord caché":
                j_iter.remove(tb)
            continue
        # Wide: the strongest moment of the next stretch (a stronger one within 0.8 s wins), or a forced join.
        pick = None
        for m in cands:
            if m["t"] <= t + 1e-6 or m["score"] < SCORE_MIN or not ok(m["t"], since):
                continue
            if under_picture(m["t"], pad=TIGHT_MIN):
                continue
            if last_open and m["t"] >= last_open - TIGHT_MIN and not m["why"].startswith("chute"):
                continue
            if nxt_join is not None and m["t"] > nxt_join - 1e-6:
                break
            if pick is None:
                pick = m
            elif m["t"] - pick["t"] <= 0.8 and m["score"] > pick["score"]:
                pick = m
            elif m["t"] - pick["t"] > 0.8:
                break
        # A stretch with no change on screen for RELAUNCH s (no dry cut, no camera cut, no picture coming or
        # going): a dry punch-in relaunches it on the best word around (OptimalHealth, rule 11: never ~7 s
        # without a change), a strong word first, a sentence start next.
        horizon = min(pick["t"] if pick else duration, nxt_join if nxt_join is not None else duration)
        changes = sorted({max(since, 0.0), *[x for x in edges if since < x < horizon],
                          *[c for c in cuts if since < c < horizon]}) + [horizon]
        relaunch = None
        for r0, r1 in zip(changes, changes[1:]):
            if r1 - r0 <= RELAUNCH or under_picture(r0 + 0.01):
                continue
            best = None
            for k, w in enumerate(words):
                s_ = float(w["start"])
                if not (r0 + RELAUNCH - 1.0 <= s_ <= r0 + RELAUNCH + 1.5) or s_ <= t + 1e-6 or s_ >= r1 - MIN_GAP:
                    continue
                if not ok(s_, since) or under_picture(s_, pad=TIGHT_MIN) or (last_open and s_ >= last_open):
                    continue
                if re.search(r"[.!?,]$", str(w["text"]).strip()):
                    continue                 # never on the word that closes a phrase
                m = by_word.get(k)
                score = (m["score"] if m else keyword_score(w["text"])) + (0.5 if k in open_set else 0.0)
                score -= 0.3 * abs(s_ - (r0 + RELAUNCH))
                if best is None or score > best[0]:
                    best = (score, s_, str(w["text"]).strip(), m["why"] if m else "")
            if best and (pick is None or pick["t"] > r0 + RELAUNCH + 1.5):
                relaunch = best          # (a strong moment in the window does the relaunch itself)
            break
        if relaunch:
            why = "relance" + (f" ({relaunch[3]})" if relaunch[3] else "")
            out.append({"t": round(relaunch[1], 3), "to": "tight", "why": why, "word": relaunch[2]})
            tight, since, t_in, t, hold = True, relaunch[1], relaunch[1], relaunch[1], TIGHT_MAX
            continue
        if nxt_join is not None and (pick is None or nxt_join <= pick["t"]):
            out.append({"t": round(nxt_join, 3), "to": "tight", "why": "raccord caché", "word": ""})
            tight, since, t_in, t, hold = True, nxt_join, nxt_join, nxt_join, TIGHT_MAX
            j_iter.remove(nxt_join)
            continue
        if pick is None:
            break
        out.append({"t": round(pick["t"], 3), "to": "tight", "why": pick["why"], "word": pick["word"],
                    "score": pick["score"]})
        hold = PUNCH_HOLD if pick["why"].startswith("chute") else TIGHT_MAX
        if pick["why"].startswith("chute") and punch:
            hold = min(PUNCH_HOLD, max(TIGHT_MIN, float(punch[1]) - pick["t"]))
        tight, since, t_in, t = True, pick["t"], pick["t"], pick["t"]
    return out


def frame_index(t, fps):
    """The first frame shown at or after ``t`` (half a frame early on the clock, punch_in.tight_graph's rule)."""
    return max(0, int(math.ceil(t * fps - 0.5)))


def frame_states(n, fps, switches, cuts=(), restarts=()):
    """Per frame: tight (bool) and the frame where its stretch began (the slow push restarts there: a switch,
    a camera cut, or a ``restarts`` time — a full-screen picture's end, the reset hidden under it)."""
    tight = np.zeros(n, dtype=bool)
    start = np.zeros(n, dtype=int)
    marks = sorted([(frame_index(s["t"], fps), s["to"] == "tight") for s in switches]
                   + [(frame_index(c, fps), None) for c in list(cuts) + list(restarts)])
    state, origin, k = False, 0, 0
    for f in range(n):
        while k < len(marks) and marks[k][0] <= f:
            if marks[k][1] is not None:
                state = marks[k][1]
            origin = marks[k][0]
            k += 1
        tight[f], start[f] = state, origin
    return tight, start


# --- the boxes: one sub-pixel crop per frame ------------------------------------------------------------

def _runs(tight, start, a, b):
    """[(s, e, tight)] stretches of frames [a, b) with one state and one slow push."""
    out, s = [], a
    for f in range(a + 1, b + 1):
        if f == b or tight[f] != tight[s] or start[f] != start[s]:
            out.append((s, f, bool(tight[s])))
            s = f
    return out


def _u_range(lo_edge, hi_edge, z, m):
    """Pivots (fraction of the base box) that keep [lo_edge, hi_edge] inside [m, 1 - m] at zoom ``z``."""
    if z <= 1.0 + 1e-9:
        return 0.0, 1.0
    return (hi_edge * z - (1.0 - m)) / (z - 1.0), (lo_edge * z - m) / (z - 1.0)


def shot_boxes(base, heads, tight, start, fps, crop_h, orig_h, report=None):
    """Float boxes (x, y, w, h) per frame of one shot, from its premium framing ``base`` [(w, h, x, y)] and its
    tracked head per frame (``heads``: (cx, cy, w, h, yaw) or None, source px); ``tight``/``start``: this
    shot's slice of frame_states. Zoom = (punch on tight stretches) x (slow push), about the eyes."""
    import framing
    n = len(base)
    obs = framing.fill(heads)
    punch, total_max = punch_for(orig_h)
    out = [None] * n
    for s, e, is_tight in _runs(tight, start, 0, n):
        L = (e - s) / fps
        z_end = 1.0 + min(SLOW_MAX, SLOW_RATE * L)
        bw, bh = float(base[s][0]), float(base[s][1])
        base_zoom = crop_h / bh
        p = 1.0
        info = {"frame": s, "tight": is_tight}
        if obs is not None:
            seg = obs[s:e]
            bx = np.array([b[2] for b in base[s:e]], dtype=float)
            by = np.array([b[3] for b in base[s:e]], dtype=float)
            cx, cy, fw, fh = seg[:, 0], seg[:, 1], seg[:, 2], seg[:, 3]
            hw = HEAD_W * fw
            left = float(np.percentile((cx - hw / 2 - bx) / bw, 3))
            right = float(np.percentile((cx + hw / 2 - bx) / bw, 97))
            top = float(np.percentile((cy - 0.6 * fh - by) / bh, 3))       # the brow line and the forehead
            chin = float(np.percentile((cy + 0.6 * fh - by) / bh, 97))
            u = float(np.median((cx - bx) / bw))
            v = float(np.median((cy - EYE * fh - by) / bh))
            travel = float(np.percentile(cx, 97) - np.percentile(cx, 3)) / bw
            if is_tight:
                p = min(punch, total_max / (base_zoom * z_end))
                soft = min(1.0, max(0.0, (travel - MOVE_SOFT[0]) / (MOVE_SOFT[1] - MOVE_SOFT[0])))
                p = 1.0 + (p - 1.0) * (1.0 - (1.0 - MOVE_KEEP) * soft)      # a head on the move: a smaller punch
            fit = (1.0 - 2 * MARGIN) / max(1e-6, right - left)               # the head's width must fit
            fit_v = (1.0 - 2 * MARGIN) / max(1e-6, chin - top)
            zmax = min(p * z_end, fit, fit_v)
            if is_tight:
                p = max(1.0, zmax / z_end)
                if p < PUNCH_MIN:
                    p = max(1.0, min(PUNCH_MIN, fit / z_end, fit_v / z_end))
            else:
                z_end = max(1.0, min(z_end, zmax))
            z = p * z_end
            ulo, uhi = _u_range(left, right, z, MARGIN)
            vlo, vhi = _u_range(top, chin, z, MARGIN)
            u = min(max(u, ulo), uhi) if ulo <= uhi else (ulo + uhi) / 2
            v = min(max(v, vlo), vhi) if vlo <= vhi else (vlo + vhi) / 2
            info.update({"travel": round(travel, 3), "fit": round(min(fit, fit_v), 3),
                         # crown to chin (framing.HEAD_ABOVE / HEAD_BELOW), of the screen's height, unzoomed
                         "head": round(float(np.median(fh)) * 1.6 / bh, 3)})
        else:
            u, v = 0.5, 0.40
            if is_tight:
                p = min(punch, total_max / (base_zoom * z_end))
        u, v = min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0)
        m = e - s
        for k in range(m):
            z = p * (1.0 + (z_end - 1.0) * (k / max(1, m - 1)))
            w0, h0, x0, y0 = (float(c) for c in base[s + k])
            w, h = w0 / z, h0 / z
            out[s + k] = (x0 + u * (w0 - w), y0 + v * (h0 - h), w, h)
        info.update({"punch": round(p, 3), "slow": round(z_end, 3), "u": round(u, 3), "v": round(v, 3)})
        if report is not None:
            report.append(info)
    return out


# --- the render: decode the source, crop each frame sub-pixel, encode --------------------------------------

def _rate(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate,color_space,color_primaries,color_transfer,color_range",
                          "-of", "json", video], capture_output=True, text=True, timeout=60).stdout
    try:
        st = json.loads(out)["streams"][0]
    except (ValueError, KeyError, IndexError):
        st = {}
    return st


def affine(box, out_w, out_h):
    """warpAffine matrices (dst -> src) for the luma plane and the 4:2:0 chroma planes (MPEG-2 siting:
    chroma co-sited with even luma columns, centred between two luma rows)."""
    x0, y0, w, h = box
    sx, sy = w / out_w, h / out_h
    ox, oy = x0 + 0.5 * sx - 0.5, y0 + 0.5 * sy - 0.5
    luma = np.array([[sx, 0.0, ox], [0.0, sy, oy]], dtype=np.float64)
    chroma = np.array([[sx, 0.0, ox / 2.0], [0.0, sy, (0.5 * sy + oy - 0.5) / 2.0]], dtype=np.float64)
    return luma, chroma


def render_segment(input_video, ss, dur, boxes, out_w, out_h, out_path, encode_args, graph="[0:v]setsar=1[v]",
                   extra_in=()):
    """One TRACK scene: ``boxes`` (x, y, w, h) per frame in source pixels, each frame cropped from the source
    (Lanczos, sub-pixel) to out_w x out_h; ``graph``/``extra_in``: the encoder's filtergraph on input 0 (the
    cropped frames) and its extra inputs (the soft cut's last frame)."""
    import cv2
    st = _rate(input_video)
    rate = st.get("r_frame_rate") or "30/1"
    W, H = _size(input_video)
    # A source larger than the tightest crop needs: decoded smaller first (area), so every warp is an upscale.
    min_h = min(b[3] for b in boxes)
    k = min(1.0, out_h / max(1.0, min_h))
    dw, dh = W, H
    vf = []
    if k < 0.98:
        dw, dh = int(round(W * k / 2)) * 2, int(round(H * k / 2)) * 2
        vf = ["-vf", f"scale={dw}:{dh}:flags=area"]
    kx, ky = dw / float(W), dh / float(H)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{ss:.4f}", "-t", f"{dur:.4f}", "-i", input_video, "-an",
                            *vf, "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    tags = []
    for opt, key in (("-color_primaries", "color_primaries"), ("-color_trc", "color_transfer"),
                     ("-colorspace", "color_space")):
        if st.get(key) and st[key] not in ("unknown", "reserved"):
            tags += [opt, st[key]]
    log = open(out_path + ".log", "w")
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "yuv420p",
                            "-s", f"{out_w}x{out_h}", "-framerate", rate, *tags, "-i", "-", *extra_in,
                            "-filter_complex", graph, "-map", "[v]", *encode_args, "-an", out_path],
                           stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
    ysz, csz = dw * dh, (dw // 2) * (dh // 2)
    frame_bytes = ysz + 2 * csz
    flags = cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP
    i = 0
    try:
        while True:
            buf = dec.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            a = np.frombuffer(buf, dtype=np.uint8)
            y = a[:ysz].reshape(dh, dw)
            u = a[ysz:ysz + csz].reshape(dh // 2, dw // 2)
            v = a[ysz + csz:].reshape(dh // 2, dw // 2)
            x0, y0, w, h = boxes[min(i, len(boxes) - 1)]
            ml, mc = affine((x0 * kx, y0 * ky, w * kx, h * ky), out_w, out_h)
            oy = cv2.warpAffine(y, ml, (out_w, out_h), flags=flags, borderMode=cv2.BORDER_REPLICATE)
            ou = cv2.warpAffine(u, mc, (out_w // 2, out_h // 2), flags=flags, borderMode=cv2.BORDER_REPLICATE)
            ov = cv2.warpAffine(v, mc, (out_w // 2, out_h // 2), flags=flags, borderMode=cv2.BORDER_REPLICATE)
            enc.stdin.write(oy.tobytes())
            enc.stdin.write(ou.tobytes())
            enc.stdin.write(ov.tobytes())
            i += 1
    finally:
        try:
            enc.stdin.close()
        except OSError:
            pass
        dec.stdout.close()
        dec.wait(timeout=600)
        code = enc.wait(timeout=1800)
        log.close()
    err = open(out_path + ".log").read()
    os.remove(out_path + ".log")
    if code != 0 or i == 0:
        raise RuntimeError(f"zoom render failed ({i} frames, ffmpeg {code}): {err[-400:]}")
    return i


def _size(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", video], capture_output=True, text=True, timeout=60).stdout
    w, h = out.strip().split("\n")[0].split(",")[:2]
    return int(w), int(h)


# --- the whole clip, for reframe_v2 ---------------------------------------------------------------------

def clip_boxes(input_video, n, fps, premium, heads, scene_boundaries, crop_h, orig_h, log=print):
    """Per premium TRACK shot (``premium``: start frame -> framing boxes), its zoom boxes; and the plan.
    Returns ({start frame: [(x, y, w, h)]}, plan) — ({}, []) when the cues are missing (no words: nothing to
    zoom on, the clip keeps its fixed framing)."""
    configure()
    cues = read_cues(input_video) or {}
    words = cues.get("words") or []
    if not words or not premium:
        return {}, []
    try:
        pros = prosody(input_video, words)
    except Exception as e:
        log(f"   ⚠️ Zooms: the sound could not be read ({type(e).__name__}: {e}) — words only.")
        pros = None
    cuts = [s / fps for s, _ in scene_boundaries[1:]]
    sw = plan(n / fps, words, pros, joins=cues.get("joins") or (), cuts=cuts, punch=cues.get("punch"),
              pictures=cues.get("pictures") or ())
    tight, start = frame_states(n, fps, sw, cuts, restarts=[b for _, b in cues.get("pictures") or ()])
    out, report = {}, []
    for s_f, base in premium.items():
        e_f = min(n, s_f + len(base))
        if e_f <= s_f:
            continue
        out[s_f] = shot_boxes(base[:e_f - s_f], heads[s_f:e_f], tight[s_f:e_f], start[s_f:e_f], fps, crop_h,
                              orig_h, report)
    seen = [s for s in sw if not s.get("hidden")]
    ins = [s for s in seen if s["to"] == "tight"]
    log(f"   🔎 Smart zooms: {len(ins)} punch-in(s), {len(seen) - len(ins)} back wide, slow push between — "
        + ", ".join(f"{s['t']:.1f}s {s['to']} ({s['why']}{': ' + s['word'] if s['word'] else ''})" for s in seen))
    heads_wide = [r["head"] for r in report if "head" in r and not r["tight"]]
    heads_tight = [r["head"] * r["punch"] for r in report if "head" in r and r["tight"]]
    if heads_wide or heads_tight:
        # OptimalHealth's hits: the head ~26 % of the screen's height (22-31 %), its flops 12 %.
        log(f"   🔎 Head height on screen: wide {np.median(heads_wide or [0]) * 100:.0f} %, "
            f"tight {np.median(heads_tight or [0]) * 100:.0f} % (crown to chin)")
    return out, sw
