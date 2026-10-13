"""Motion in a ClipGen clip (v2c, validated by her 13-oct-2026): ONE director call, then code only, then the clip goes on.

``plan()`` runs before the B-roll (main.py), on the clip's own words (the montage's virtual transcript): the director
picks the moment and its relation (motion_director.decide: one AI call, checked and repaired by code, a keyword
fallback that is always valid), and the plan's sheet is written next to the clip. Its window is returned as a
``block`` so the B-roll plans around it.
v2c (motion bench, output/_broll_experts/motion, SPEC_V2 lots 1-3): the shot is cut AROUND THE FOCUS — the word the
one big change falls on (SPEC.focus, deduced by code from the decision: its own focus, else the word its mot_sens
names among the words that can carry the change, else the relation's default), placed at ≈ 60 % of the shot (band
40-75 %, tenue ≥ 1.8 s), in two passes (Whisper's times, then the heard ones). The grid follows the clip's real caption
style (SPEC.cap, from viral_fx.PRESETS[clip edit_style]).
``finish()`` runs after the B-roll: the renderer checks the plan by code (the phone's zones with the clip's caption
band, at most 3 texts, no overlap, the image full at 0.1 s, one amber, no text on a shape, pictos from the validated
library) and captures it; a refused plan is rebuilt once on the keyword fallback (no AI) and captured again. The result
is a full-screen video element for ``broll.overlay_items`` — the path the B-roll videos already take — with a 0.2 s
alpha fade in and out (``fondu``), so the captions are burned on top of it as on everything else. Anything that fails:
the clip is kept without motion, never retried. The recipe is frozen in plus.MOTION; the switch is the profile's
"motion" (off by default)."""
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess

import motion_director as dm

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "motion", "engine")
SHARED = "_motion_engine"                       # the engine's copy in the shared output volume (the renderer reads it)


def _engine_dir(output_root):
    """The engine's files in /app/output/_motion_engine/<version>/ (copied once per version of the files)."""
    files = sorted(f for f in os.listdir(ENGINE) if f.endswith((".html", ".js")))
    h = hashlib.sha1(b"".join(open(os.path.join(ENGINE, f), "rb").read() for f in files)).hexdigest()[:10]
    dst = os.path.join(output_root, SHARED, h)
    if not os.path.exists(os.path.join(dst, "motion.html")):
        os.makedirs(os.path.join(dst, "fonts"), exist_ok=True)
        for f in os.listdir(os.path.join(ENGINE, "fonts")):
            shutil.copy2(os.path.join(ENGINE, "fonts", f), os.path.join(dst, "fonts"))
        for f in files:                                 # motion.html last: its presence means the copy is complete
            if f != "motion.html":
                shutil.copy2(os.path.join(ENGINE, f), dst)
        shutil.copy2(os.path.join(ENGINE, "motion.html"), dst)
    return dst


def _heard(wav, words, dur):
    """Whisper starts a word inside the pause before it: snap it to the end of that silence (charter §2)."""
    log = subprocess.run(["ffmpeg", "-i", wav, "-af", "silencedetect=noise=-32dB:d=0.12", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    sil = list(zip(st, en + [dur] * (len(st) - len(en))))
    out = []
    for w in words:
        s, e, t = w["s"], w["e"], w["s"]
        for a, b in sil:
            if a - 0.02 <= s < b or (s < a and b - a >= 0.2 and b < e):
                t = b
                break
        out.append(round(min(t, s + .45), 3))
    return out


def _energy(wav):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", wav, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    hop = 16000 // 30
    rms = np.array([np.sqrt(np.mean(x[i:i + hop] ** 2) + 1e-12) for i in range(0, max(0, len(x) - hop), hop)])
    if not len(rms):
        return []
    e = np.clip((20 * np.log10(rms) + 45) / 30, 0, 1)
    return [round(float(v), 3) for v in np.convolve(e, np.ones(3) / 3, mode="same")]


# ---------------------------------------------------------------- v2c : the focus and the cut around it
# (motion bench run_motion.py, SPEC_V2 points 2-3, scénariste dramaturgie_v2 §2.2, §2.5, §4.2, §4.3). All by code, from
# the decision: no AI call.
# The roles that can carry the ONE big change of each relation, in order of preference. « x[-1] » = the last item of a
# list role, « x[*] » = any item.
FOCUS_ROLES = {"niveau": ["verbe"], "reference": ["reference"], "cause_effet": ["effet", "lien"], "contraste": ["bascule"],
               "etapes": ["etapes[-1]"], "trajet": ["etapes[-1]"], "boucle": ["emballement", "accent", "stations[-1]"],
               "blocage": ["bloqueur", "verbe"], "transformation": ["verbe", "b"], "chiffre": ["valeur"],
               "champ": ["retour", "mot"], "debat": ["bascule", "contre"], "question": ["question", "mots[*]"],
               "mots_cles": ["mots[-1]", "mots[*]"]}
# a gauge never moves before its verb: the focus is never said before this role
NOT_BEFORE = {"niveau": "verbe", "reference": "verbe", "contraste": "bascule", "cause_effet": "lien"}
# the cut: (name, pose before the first word, after the last word, tenue after the focus, shortest D, may drop roles).
# Order: the scénariste's values; then a shorter pose and tail (0.3 / 0.5 s: the tenue and the band stay); then the
# optional roles farthest from the focus are dropped; then the tenue may shrink to 1.2 s; then D to 3.5 s.
LEVELS = [("strict", .6, .9, 1.8, 4.0, False), ("pose_courte", .3, .5, 1.8, 4.0, False), ("pose_courte", .3, .5, 1.8, 4.0, True),
          ("tenue_courte", .3, .5, 1.2, 4.0, True), ("court", .3, .5, 1.2, dm.SHORTEST, True)]
BAND, TARGET, LONGEST = (.40, .75), .60, 6.0


def _items(roles, ref):
    """[(name, item)] for one role reference of FOCUS_ROLES."""
    name = ref.split("[")[0]
    v = roles.get(name)
    if ref.endswith("[-1]") or ref.endswith("[*]"):
        xs = [x for x in (v or []) if isinstance(x, dict) and isinstance(x.get("i"), int)] if isinstance(v, list) else []
        return [(name, x) for x in (xs[-1:] if ref.endswith("[-1]") else xs)]
    return [(name, v)] if isinstance(v, dict) and isinstance(v.get("i"), int) else []


def _eligible(rel, roles):
    refs = FOCUS_ROLES.get(rel, [])
    if rel == "champ":                      # the return is the frappe when it is said; else the narrowing
        refs = ["retour"] if _items(roles, "retour") else ["mot"]
    out = []
    for ref in refs:
        for nm, it in _items(roles, ref):
            if all(it is not o for _, o in out):
                out.append((nm, it))
    return out


def _match(mot_sens, it, words):
    """The word of a role that the director's mot_sens names (« opposite » inside « GOES OPPOSITE »), or None."""
    ms = set(dm._toks(mot_sens or ""))
    if not ms:
        return None
    i = it["i"]
    lab = dm._toks(it.get("label") or "") or dm._toks(words[i]["text"])
    if not ms & set(lab):
        return None
    for k in range(max(0, i - 1), min(len(words), i + len(lab) + 2)):
        if set(dm._toks(words[k]["text"])[:1]) & ms:
            return k
    return i


def focus_candidates(m, words):
    """The focus, in order: the decision's own « focus »; the word named by mot_sens among the words that can carry the
    change; the relation's default. Each candidate: (word index, role, source)."""
    rel, roles = m["relation"], m.get("roles") or {}
    elig, used = _eligible(rel, roles), dm.roles_used(rel, roles)
    out = []
    f = m.get("focus") or roles.get("focus")
    fi = f.get("i") if isinstance(f, dict) else f
    if isinstance(fi, int) and used and min(used) <= fi <= max(used) + 3:
        out.append((fi, "focus", "decision"))
    for nm, it in elig:
        k = _match(m.get("mot_sens"), it, words)
        if k is not None:
            out.append((k, nm, "mot_sens"))
    for nm, it in elig:
        out.append((it["i"], nm, "defaut"))
    nb = roles.get(NOT_BEFORE.get(rel, ""), None)
    if isinstance(nb, dict) and isinstance(nb.get("i"), int):
        out = [c for c in out if words[c[0]]["start"] >= words[nb["i"]]["start"] - 1e-6]
    seen, uniq = set(), []
    for c in out:
        if c[0] not in seen:
            seen.add(c[0]); uniq.append(c)
    return uniq


def _optional(rel, roles, iF, words):
    """The roles the cut may drop, farthest (in time) from the focus first (never the focus, never a required role)."""
    req, opt, lists = dm.RELATIONS[rel]
    tF = words[iF]["start"]
    far = lambda i: abs(words[i]["start"] - tF)
    cands = [(far(roles[k]["i"]), k, None) for k in opt if isinstance(roles.get(k), dict) and isinstance(roles[k].get("i"), int)
             and roles[k]["i"] != iF]
    for k, (lo, hi) in lists.items():
        xs = roles.get(k) or []
        if len(xs) > lo:
            cands += [(far(x["i"]), k, j) for j, x in enumerate(xs) if x["i"] != iF]
    return sorted(cands, key=lambda c: -c[0])


def _cut(words, used, iF, dur, lead, tail, hold, dmin):
    """D in [dmin, 6] and the focus's place p in the band 40-75 % (as close to 60 % as possible, then the shortest D),
    holding the pose before the first word, the tenue after the focus and the last word, inside HEAD and dur − TAIL."""
    tF = words[iF]["start"]
    a = min(words[i]["start"] for i in used); b = max(words[i]["end"] for i in used)
    av, ap = tF - a + lead, max(hold, b - tF + tail)
    lo_t0, hi_t1 = dm.HEAD, dur - dm.TAIL
    best, D = None, dmin
    while D <= LONGEST + 1e-9:
        plo = max(av / D, BAND[0], (tF + D - hi_t1) / D)
        phi = min(1 - ap / D, BAND[1], (tF - lo_t0) / D)
        if plo <= phi + 1e-9:
            p = min(max(TARGET, plo), phi)
            key = (round(abs(p - TARGET), 3), D)
            if best is None or key < best[0]:
                best = (key, D, p)
        D = round(D + .02, 2)
    if not best:
        return None
    _, D, p = best
    return {"t0": tF - p * D, "D": D, "p": p, "avant": round(av, 2), "apres": round(ap, 2)}


def decoupe(m, words, dur):
    """(roles, focus index, t0, D, log): the shot cut around the focus. Drops optional roles farthest from the focus
    before relaxing the tenue; never drops the focus; never calls the AI."""
    rel = m["relation"]
    cands = focus_candidates(m, words)
    if not cands:                                         # a sheet with no word that can strike: its last word played
        used = dm.roles_used(rel, m["roles"])
        cands = [(max(used), "dernier", "defaut")]
    for iF, role, src in cands:
        for lvl, lead, tail, hold, dmin, may_drop in LEVELS:
            roles, dropped = copy.deepcopy(m["roles"]), []
            if rel in ("etapes", "trajet") and src == "decision":          # « the focus becomes the last step shown »
                xs = roles.get("etapes") or []
                k = next((j for j, x in enumerate(xs) if x["i"] == iF), None)
                if k is not None and k >= 1:
                    roles["etapes"] = xs[:k + 1]
            while True:
                used = dm.roles_used(rel, roles)
                w = _cut(words, used + [iF], iF, dur, lead, tail, hold, dmin)
                if w:
                    log = {"focus_i": iF, "focus_mot": words[iF]["text"], "focus_role": role, "source": src, "niveau": lvl,
                           "retires": dropped, "part": round(w["p"], 3), "avant": w["avant"], "apres": w["apres"]}
                    return roles, iF, w["t0"], w["D"], log
                opt = _optional(rel, roles, iF, words) if may_drop else []
                if not opt:
                    break
                _, k, j = opt[0]
                if j is None:
                    dropped.append(f"{k}:{roles[k].get('label') or roles[k]['i']}"); roles.pop(k)
                else:
                    x = roles[k].pop(j); dropped.append(f"{k}:{x.get('label') or x['i']}")
    # nothing holds: the first candidate, the band and the bounds kept, and it is written in the sheet's log
    iF, role, src = cands[0]
    used = dm.roles_used(rel, m["roles"]) + [iF]
    tF = words[iF]["start"]
    av = tF - min(words[i]["start"] for i in used) + .3
    ap = max(1.2, max(words[i]["end"] for i in used) - tF + .5)
    D = min(LONGEST, dur - dm.TAIL - dm.HEAD)
    p = min(max(av / (av + ap), BAND[0]), BAND[1])
    t0 = min(max(dm.HEAD, tF - p * D), dur - dm.TAIL - D)
    log = {"focus_i": iF, "focus_mot": words[iF]["text"], "focus_role": role, "source": src, "niveau": "force",
           "retires": [], "part": round((tF - t0) / max(D, .01), 3), "note": "aucune fenêtre ne tient la pose et la tenue : fenêtre gardée"}
    return m["roles"], iF, t0, D, log


def _caption_band(clip, words, t0, D):
    """SPEC.cap (the grid follows the clip's real captions) and CAPCHUNKS (that style's caption blocks, in shot seconds)."""
    import viral_fx
    style = (clip or {}).get("edit_style")
    pr = viral_fx.PRESETS.get(style) if style else None
    if not pr:                                        # no edit style (auto captions): the one-word band, the engine's default
        return {"style": style or "auto", "y": 1114, "size": 133, "top": 1014, "bottom": 1214}, []
    cy, sz = pr.get("caption_y", 1114), pr.get("size", 133)
    cap = {"style": style, "y": cy, "size": sz, "top": round(cy - .75 * sz), "bottom": round(cy + .75 * sz)}
    groups = viral_fx.group_words([dict(w, k=k) for k, w in enumerate(words)], pr["max_words"], pr["max_chars"],
                                  one_word=bool(pr.get("one_word")))
    chunks = []
    for gi, g in enumerate(groups):
        e = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else g[-1]["end"] + .3
        e = min(e, g[-1]["end"] + .6)
        if e - t0 > -1 and g[0]["start"] - t0 < D + 1:
            chunks.append([round(g[0]["start"] - t0, 3), round(e - t0, 3), [w["k"] for w in g]])
    return cap, chunks


def write_sheet(m, words, dur, voice, base, avoid=(), clip=None, ident=""):
    """The plan's sheet (v2c): the shot cut AROUND THE FOCUS (≈ 60 % of the shot), the voice snapped, in two passes;
    None when it cannot be placed (too short, or across a window the montage keeps)."""
    used = dm.roles_used(m["relation"], m["roles"])
    if not used:
        return None
    roles, iF, t0, D, cut = decoupe(m, words, dur)
    wav = base + "voice.wav"
    for npass in range(2):
        # pass 1 cuts on Whisper's times; the voice snaps the starts later (up to 0.45 s): if the focus moved, pass 2
        # cuts again on the HEARD times, so the tenue and the place hold for what is heard
        D = round(D, 2)
        if D < dm.SHORTEST - .01 or any(t0 < e and t0 + D > s for s, e in avoid):
            return None
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-t", str(D), "-i", voice, "-vn", "-ac", "1",
                        "-ar", "48000", wav], check=True)
        win = [{"text": w["text"], "s": w["start"] - t0, "e": w["end"] - t0, "i": k} for k, w in enumerate(words)
               if -dm.PRE - .6 <= w["start"] - t0 < D]
        H = _heard(wav, win, D)
        hf = next((h for w, h in zip(win, H) if w["i"] == iF), None)
        if npass or hf is None or abs(t0 + hf - words[iF]["start"]) < .03:
            break
        heard_words = [dict(w) for w in words]
        for w, h in zip(win, H):
            heard_words[w["i"]]["start"] = t0 + h
        roles, iF, t0, D, cut = decoupe(m, heard_words, dur)
        cut["passe"] = "voix entendue"
    W = [{"i": w["i"], "w": w["text"], "t": t, "e": round(w["e"], 3)} for w, t in zip(win, H)]
    hw = next((w for w in W if w["i"] == iF), None)
    if hw:
        cut["part_entendue"] = round(hw["t"] / D, 3)
    cap, chunks = _caption_band(clip, words, t0, D)
    spec = {"id": ident or os.path.basename(base), "relation": m["relation"], "D": D, "roles": roles, "focus": {"i": iF},
            "decoupe": cut, "t0": round(t0, 3), "cap": cap, "anti_echo": False, "repli": bool(m.get("repli")),
            "phrase_spectateur": m.get("phrase_spectateur", ""), "mot_sens": m.get("mot_sens", ""), "why": m.get("why", "")}
    with open(base + "spec.js", "w", encoding="utf-8") as f:
        f.write("window.WORDS = " + json.dumps(W) + ";\nwindow.ENERGY = " + json.dumps(_energy(wav)) +
                ";\nwindow.CAPCHUNKS = " + json.dumps(chunks) + ";\nwindow.SPEC = " + json.dumps(spec, ensure_ascii=False) + ";\n")
    return {"t0": t0, "D": D, "decoupe": cut}


class Motion:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def plan(clip, transcript, start, end, voice, out_dir, prefix, cfg, avoid=(), log=print):
    """One director call and the plan's sheet, on the clip's words in its own time (main.py's c_transcript, c_start,
    c_end; voice = the montage's output, before the music). Returns a Motion (with .block) or None."""
    import viral_fx
    dur = float(end) - float(start)
    words = [w for w in viral_fx.clip_words(transcript, start, end) if w["text"].strip()]
    if len(words) < 6:
        return None
    m, rep = dm.decide(clip.get("video_title_for_youtube_short") or "", words, dur,
                       model=cfg.get("model", "opus"), effort=cfg.get("effort", "high"))
    base = os.path.join(out_dir, prefix + "motion_")
    win = write_sheet(m, words, dur, voice, base, avoid, clip=clip, ident=prefix)
    if not win and not m.get("repli"):              # the moment cannot be placed: the safe sheet, from the same answer
        m = dm.fallback(m, words, dur)
        win = write_sheet(m, words, dur, voice, base, avoid, clip=clip, ident=prefix)
    if not win:
        log("   🎞️ Motion: no window for a plan in this clip — clip without motion.")
        return None
    cut = win.pop("decoupe", {}) or {}
    log(f"   🎞️ Motion: {m['relation']}{' (repli)' if m.get('repli') else ''} at {win['t0']:.1f}s for {win['D']:.1f}s, "
        f"strike on « {cut.get('focus_mot', '?')} » ({100 * cut.get('part_entendue', cut.get('part', 0)):.0f} %) — {m.get('phrase_spectateur', '')[:70]}")
    return Motion(decision=m, verif=rep, words=words, dur=dur, voice=voice, base=base, out_dir=out_dir, prefix=prefix,
                  cfg=cfg, avoid=avoid, clip=clip, cut=cut, block=((win["t0"], win["t0"] + win["D"]),), **win)


def _capture(mo, log):
    import requests
    eng = _engine_dir(mo.cfg.get("output_root", "/app/output"))
    to_renderer = lambda p: "/output/" + os.path.relpath(p, mo.cfg.get("output_root", "/app/output")).replace(os.sep, "/")
    page = to_renderer(os.path.join(eng, "motion.html")) + "#" + os.path.relpath(mo.base + "spec.js", eng).replace(os.sep, "/")
    url = os.environ.get("MOTION_RENDER_URL") or mo.cfg.get("render_url") or "http://renderer:3100/motion"
    r = requests.post(url, json={"page": page, "out": to_renderer(mo.base + "0.mp4"), "secs": mo.D,
                                 "fps": int(mo.cfg.get("fps", 30)), "tabs": int(mo.cfg.get("tabs", 1)),
                                 "still": to_renderer(mo.base + "0.jpg")}, timeout=int(mo.cfg.get("timeout", 150)))
    return r.json()


def finish(mo, log=print):
    """The code check and the capture; a refused plan is rebuilt once on the keyword fallback (no AI). Returns the
    B-roll element (a full-screen video with its 0.2 s fade) or None."""
    if not mo:
        return None
    ans = _capture(mo, log)
    mo.report = {"relation": mo.decision["relation"], "t": round(mo.t0, 2), "dur": mo.D, "check": ans.get("check"),
                 "phrase_spectateur": mo.decision.get("phrase_spectateur"), "repli": bool(mo.decision.get("repli")),
                 "frappe": mo.cut.get("focus_mot"), "part": mo.cut.get("part_entendue", mo.cut.get("part"))}
    if not ans.get("ok") and ans.get("check") and not mo.decision.get("repli"):
        m = dm.fallback(mo.decision, mo.words, mo.dur)
        win = write_sheet(m, mo.words, mo.dur, mo.voice, mo.base, mo.avoid, clip=mo.clip, ident=mo.prefix)
        b0, b1 = mo.block[0]                            # the B-roll planned around this window: the safe plan stays inside it
        if win and win["t0"] >= b0 - .01 and win["t0"] + win["D"] <= b1 + .01:
            mo.decision, mo.t0, mo.D = m, win["t0"], win["D"]
            ans = _capture(mo, log)
            mo.report.update({"filet": "contrôle du code refusé : repli sur les mots-clés", "relation": "mots_cles",
                              "check_apres": ans.get("check")})
    if not ans.get("ok"):
        log(f"   ⚠️ Motion refused ({ans.get('check') or ans.get('error')}) — clip without motion.")
        return None
    mp4, jpg = mo.base + "0.mp4", mo.base + "0.jpg"
    if not os.path.exists(mp4):
        return None
    log(f"   🎞️ Motion placed: {os.path.basename(mp4)} ({ans.get('seconds', 0):.0f}s of capture)")
    return {"t": round(mo.t0, 3), "dur": mo.D, "layout": "hero", "source": "motion", "video": os.path.basename(mp4),
            "fondu": float(mo.cfg.get("fondu", .2)),
            "image": os.path.basename(jpg) if os.path.exists(jpg) else None, "modele": mo.decision["relation"],
            "phrase_spectateur": mo.decision.get("phrase_spectateur")}
