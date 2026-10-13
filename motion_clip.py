"""Motion in a ClipGen clip (13-oct-2026): ONE director call, then code only, then the clip goes on.

``plan()`` runs before the B-roll (main.py), on the clip's own words (the montage's virtual transcript): the director
picks the moment and its relation (motion_director.decide: one AI call, checked and repaired by code, a keyword
fallback that is always valid), and the plan's sheet is written next to the clip. Its window is returned as a
``block`` so the B-roll plans around it.
``finish()`` runs after the B-roll: the renderer checks the plan by code (the phone's zones, at most 3 texts, no
overlap) and captures it; a refused plan is rebuilt once on the keyword fallback (no AI) and captured again. The
result is a full-screen video element for ``broll.overlay_items`` — the path the B-roll videos already take — so the
captions are burned on top of it as on everything else. Anything that fails: the clip is kept without motion, never
retried. The recipe is frozen in plus.MOTION; the switch is the profile's "motion" (off by default)."""
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
        for f in files:
            shutil.copy2(os.path.join(ENGINE, f), dst)
        for f in os.listdir(os.path.join(ENGINE, "fonts")):
            shutil.copy2(os.path.join(ENGINE, "fonts", f), os.path.join(dst, "fonts"))
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


def write_sheet(m, words, dur, voice, base, avoid=()):
    """The plan's sheet: the shot cut on the words the relation plays; None when it cannot be placed."""
    used = dm.roles_used(m["relation"], m["roles"])
    if not used:
        return None
    a, b = min(used), max(used)
    lead = dm.LEADS.get(m["relation"], dm.LEAD)
    t0 = max(dm.HEAD, min(words[a]["start"] - lead, words[b]["end"] + dm.HOLD - dm.MAX_D))
    t1 = min(max(words[b]["end"] + dm.HOLD, t0 + dm.MIN_D), dur - dm.TAIL, t0 + dm.MAX_D)
    if t1 - t0 < dm.SHORTEST:
        t0 = max(dm.HEAD, t1 - dm.SHORTEST)
    if t1 - t0 < dm.SHORTEST - .01 or any(t0 < e and t1 > s for s, e in avoid):
        return None
    D = round(t1 - t0, 2)
    wav = base + "voice.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-t", str(D), "-i", voice, "-vn", "-ac", "1",
                    "-ar", "48000", wav], check=True)
    win = [{"text": w["text"], "s": w["start"] - t0, "e": w["end"] - t0, "i": k} for k, w in enumerate(words)
           if -dm.PRE - .6 <= w["start"] - t0 < D]
    W = [{"i": w["i"], "w": w["text"], "t": t, "e": round(w["e"], 3)} for w, t in zip(win, _heard(wav, win, D))]
    spec = {"relation": m["relation"], "D": D, "roles": m["roles"], "t0": round(t0, 3), "repli": bool(m.get("repli")),
            "phrase_spectateur": m.get("phrase_spectateur", ""), "mot_sens": m.get("mot_sens", "")}
    with open(base + "spec.js", "w", encoding="utf-8") as f:
        f.write("window.WORDS = " + json.dumps(W) + ";\nwindow.ENERGY = " + json.dumps(_energy(wav)) +
                ";\nwindow.SPEC = " + json.dumps(spec, ensure_ascii=False) + ";\n")
    return {"t0": t0, "D": D}


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
    win = write_sheet(m, words, dur, voice, base, avoid)
    if not win and not m.get("repli"):              # the moment cannot be placed: the safe sheet, from the same answer
        m = dm.fallback(m, words, dur)
        win = write_sheet(m, words, dur, voice, base, avoid)
    if not win:
        log("   🎞️ Motion: no window for a plan in this clip — clip without motion.")
        return None
    log(f"   🎞️ Motion: {m['relation']}{' (repli)' if m.get('repli') else ''} at {win['t0']:.1f}s for {win['D']:.1f}s — {m.get('phrase_spectateur', '')[:80]}")
    return Motion(decision=m, verif=rep, words=words, dur=dur, voice=voice, base=base, out_dir=out_dir, prefix=prefix,
                  cfg=cfg, avoid=avoid, block=((win["t0"], win["t0"] + win["D"]),), **win)


def _capture(mo, log):
    import requests
    eng = _engine_dir(mo.cfg.get("output_root", "/app/output"))
    to_renderer = lambda p: "/output/" + os.path.relpath(p, mo.cfg.get("output_root", "/app/output")).replace(os.sep, "/")
    page = to_renderer(os.path.join(eng, "motion.html")) + "#" + os.path.relpath(mo.base + "spec.js", eng).replace(os.sep, "/")
    url = os.environ.get("MOTION_RENDER_URL") or mo.cfg.get("render_url") or "http://renderer:3100/motion"
    r = requests.post(url, json={"page": page, "out": to_renderer(mo.base + "0.mp4"), "secs": mo.D,
                                 "fps": int(mo.cfg.get("fps", 30)), "tabs": int(mo.cfg.get("tabs", 3)),
                                 "still": to_renderer(mo.base + "0.jpg")}, timeout=int(mo.cfg.get("timeout", 150)))
    return r.json()


def finish(mo, log=print):
    """The code check and the capture; a refused plan is rebuilt once on the keyword fallback (no AI). Returns the
    B-roll element (a full-screen video) or None."""
    if not mo:
        return None
    ans = _capture(mo, log)
    mo.report = {"relation": mo.decision["relation"], "t": round(mo.t0, 2), "dur": mo.D, "check": ans.get("check"),
                 "phrase_spectateur": mo.decision.get("phrase_spectateur"), "repli": bool(mo.decision.get("repli"))}
    if not ans.get("ok") and ans.get("check") and not mo.decision.get("repli"):
        m = dm.fallback(mo.decision, mo.words, mo.dur)
        win = write_sheet(m, mo.words, mo.dur, mo.voice, mo.base, mo.avoid)
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
            "image": os.path.basename(jpg) if os.path.exists(jpg) else None, "modele": mo.decision["relation"],
            "phrase_spectateur": mo.decision.get("phrase_spectateur")}
