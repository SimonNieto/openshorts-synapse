"""The music bed under every clip (Clip Generator++, plus.AUDIO; 9-oct-2026, recette « références »).

What OptimalHealth does, measured on 9 of their hits (output/_stepup/etude2/mesures/rapport.md, the sound part): a soft,
constant music bed in 6 of 9 Shorts, about 14 dB under the voice (13 to 18 dB), its level steady from start to end
(no ducking they could measure), no whoosh nor any sound effect, the whole at -16.6 LUFS. Ours before: the voice
alone, a whoosh on the first drawing, about -14 LUFS.

So, per clip:
  * one track of the library (MUSIC_DIR/catalog.json), its mood read from the clip's subject (topic_bucket), never
    the same track for two clips in a row of a job (``plan``, done once before the clips are rendered in parallel);
  * looped or cut to the clip's length, faded in over 0.5 s and out over 1 s;
  * held ``music_db_under_voice`` dB under the voice, measured the way the study measured theirs: the voice = the
    median level of the speech frames (40 ms), the bed = the median of the 5th percentile of each 2 s window (the
    level between the syllables); one corrective pass on the real mix, a light ducking only if asked (``duck_db``);
  * then the whole normalised to ``target_lufs`` (two-pass loudnorm, linear, true peak -2 dBTP as ffmpeg_utils).

Only tracks the catalog marks ``"content_id": false`` with a licence are ever used: a track registered with Content ID
gets the Short claimed and blocked on YouTube. No usable track, no catalog, a failed mix: the clip stays as it was,
never a failed job.

The catalog's measured fields (duration, LUFS, BPM) are filled by ``python music_bed.py --catalog [MUSIC_DIR]``.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

import numpy as np

CATALOG = "catalog.json"
MUSIC_EXTENSIONS = (".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg")
# The house recipe's numbers when the job says nothing (plus.AUDIO overrides them through PLUS_AUDIO_JSON).
DEFAULTS = {"music": True, "music_db_under_voice": 14.0, "target_lufs": -16.6, "sfx": False,
            "fade_in": 0.5, "fade_out": 1.0, "duck_db": 0.0, "dir": None}
TRUE_PEAK = -2.0          # as ffmpeg_utils.LOUDNORM_FILTER: the AAC encoder adds inter-sample peaks on top
SR = 44100
FRAME, HOP = 0.04, 0.01   # the study's frames (m3_son.py): 40 ms, every 10 ms
FLOOR_WINDOW = 2.0        # the study's bed: 5th percentile of each 2 s window (m8b_reference.py)
SPEECH_BELOW_P90 = 20.0   # a frame within 20 dB of the 90th percentile of the voice-only clip is speech
CORRECT_ABOVE = 0.5       # dB: the real mix is measured once and the bed's gain corrected past this error
GAIN_RANGE = (-40.0, 6.0)
HANN_DB = 4.26            # a Hann frame's power is 10*log10(0.375) = -4.26 dB under the signal's RMS

MOODS = ("calm", "curious", "tense", "uplifting", "dark")
# The moods that suit a clip's subject (playbook.TOPIC_BUCKETS), best first. Science and health: soft, never epic.
TOPIC_MOODS = {
    "brain_danger": ("tense", "curious", "dark"),
    "substances": ("tense", "curious", "calm"),
    "psychosis_mental_illness": ("dark", "calm", "tense"),
    "crime_dark": ("dark", "tense"),
    "medical_mystery": ("curious", "tense", "calm"),
    "mind_psychology": ("curious", "calm"),
    "self_improvement": ("uplifting", "calm", "curious"),
    "science_other": ("curious", "calm", "uplifting"),
}
DEFAULT_MOODS = ("calm", "curious")


# --- settings ---------------------------------------------------------------------------------------------------

def config():
    """The job's audio settings (plus.AUDIO through PLUS_AUDIO_JSON), DEFAULTS filled in; None when the job has none
    (the classic Clip Generator: nothing changes)."""
    raw = os.environ.get("PLUS_AUDIO_JSON")
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(cfg, dict):
        return None
    return {**DEFAULTS, **cfg}


def music_dir(cfg=None):
    return (cfg or {}).get("dir") or os.environ.get("BACKGROUND_MUSIC_DIR") or "music"


def target_lufs(cfg=None):
    """The delivered loudness: the job's target_lufs, else -14 (ffmpeg_utils.LOUDNORM_FILTER)."""
    cfg = cfg if cfg is not None else config()
    try:
        return float((cfg or {}).get("target_lufs"))
    except (TypeError, ValueError):
        return -14.0


def loudnorm_filter(cfg=None):
    """The one-pass loudnorm of a layer that re-encodes the clip's sound (broll's whoosh): at the job's target."""
    return f"loudnorm=I={target_lufs(cfg):g}:TP={TRUE_PEAK:g}:LRA=11"


# --- the library ------------------------------------------------------------------------------------------------

def load_catalog(folder):
    try:
        with open(os.path.join(folder, CATALOG), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    tracks = data.get("tracks") if isinstance(data, dict) else data
    return [t for t in (tracks or []) if isinstance(t, dict) and t.get("file")]


def usable(track, folder):
    """A track the job may use: its file is there, a licence is named, and the catalog says it is NOT registered with
    Content ID (strictly false: unknown is not good enough)."""
    return (track.get("content_id") is False and bool(str(track.get("licence") or "").strip())
            and os.path.isfile(os.path.join(folder, track["file"])))


def tracks(cfg=None):
    folder = music_dir(cfg)
    return [{**t, "path": os.path.join(folder, t["file"])} for t in load_catalog(folder) if usable(t, folder)]


def _moods(track):
    m = track.get("mood")
    return [m] if isinstance(m, str) else list(m or [])


def moods_for(clip):
    return TOPIC_MOODS.get(str((clip or {}).get("topic_bucket") or ""), DEFAULT_MOODS)


def _tie(seed, i, track):
    return hashlib.sha1(f"{seed}|{i}|{track['file']}".encode("utf-8")).hexdigest()


def plan(shorts, library, seed=""):
    """One track per clip, in the clips' order: the best mood for its subject, the least used so far in the job, never
    the previous clip's track (unless the library has one track only); ties broken by a hash of the job, so a re-run
    picks the same. Returns a list of tracks (None for every clip when the library is empty)."""
    picks, used, prev = [], {}, None
    for i, clip in enumerate(shorts):
        if not library:
            picks.append(None)
            continue
        wanted = moods_for(clip)
        pool = [t for t in library if t["file"] != (prev or {}).get("file")] or list(library)

        def rank(t):
            m = [wanted.index(x) for x in _moods(t) if x in wanted]
            return (min(m) if m else len(wanted), used.get(t["file"], 0), _tie(seed, i, t))
        pick = min(pool, key=rank)
        used[pick["file"]] = used.get(pick["file"], 0) + 1
        picks.append(pick)
        prev = pick
    return picks


# --- measures ---------------------------------------------------------------------------------------------------

def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def read_audio(path, start=0.0, duration=None, loop=False):
    """Mono float32 samples at SR (the study's way), from ``start`` for ``duration`` s, the file looped if asked."""
    cmd = ["ffmpeg", "-v", "error"]
    if loop:
        cmd += ["-stream_loop", "-1"]
    if start:
        cmd += ["-ss", f"{float(start):.3f}"]
    cmd += ["-i", path]
    if duration:
        cmd += ["-t", f"{float(duration):.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    return np.frombuffer(r.stdout, np.float32)


def frame_db(x, sr=SR):
    """Power (dB) of 40 ms Hann frames every 10 ms — the study's ``tot`` (m3_son.py), up to a constant."""
    n, h = int(FRAME * sr), int(HOP * sr)
    x = np.asarray(x, np.float64)
    if len(x) < n:
        return np.zeros(0)
    count = (len(x) - n) // h + 1
    idx = np.arange(n)[None, :] + h * np.arange(count)[:, None]
    w = np.hanning(n)
    return 10 * np.log10(((x[idx] * w) ** 2).sum(axis=1) / n + 1e-12)


def speech_mask(db):
    """The speech frames of a voice-only track: within SPEECH_BELOW_P90 dB of its 90th percentile."""
    if len(db) == 0:
        return np.zeros(0, bool)
    return db >= np.percentile(db, 90) - SPEECH_BELOW_P90


def voice_level(db, mask=None):
    if mask is None:
        mask = speech_mask(db)
    n = min(len(db), len(mask))      # an encoded copy may be a frame longer or shorter
    db, mask = db[:n], mask[:n]
    return float(np.median(db[mask])) if mask.any() else None


def floor_level(db):
    """The bed between the syllables: the median of the 5th percentile of each 2 s window (m8b_reference.py)."""
    per = int(round(FLOOR_WINDOW / HOP))
    wins = [np.percentile(db[a:a + per], 5) for a in range(0, len(db) - per + 1, per)]
    if not wins and len(db):
        wins = [np.percentile(db, 5)]
    return float(np.median(wins)) if wins else None


def gap_db(mix_db, mask):
    """Voice (speech frames) minus bed (2 s floors) of a mix, the study's ``ecart_voix_fond_db``."""
    v, f = voice_level(mix_db, mask), floor_level(mix_db)
    return None if v is None or f is None else v - f


def loudness(path):
    """Integrated loudness (LUFS) and true peak (dBTP) by ffmpeg ebur128."""
    r = subprocess.run(["ffmpeg", "-nostats", "-i", path, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    s = r.stderr[r.stderr.rfind("Summary:"):]
    i, p = re.search(r"I:\s+(-?[\d.]+|-inf)", s), re.search(r"Peak:\s+(-?[\d.]+|-inf)", s)
    to = lambda m: float(m.group(1)) if m and m.group(1) != "-inf" else None
    return {"lufs": to(i), "true_peak": to(p)}


def bpm(x, sr=SR):
    """An approximate tempo: the autocorrelation of the onset envelope between 60 and 180 BPM; None when nothing
    beats clearly (a pad)."""
    db = frame_db(x, sr)
    if len(db) < 400:
        return None
    onset = np.maximum(np.diff(db), 0)
    if onset.mean() < 0.05:          # dB per frame: nothing rises, nothing beats
        return None
    onset = onset - onset.mean()
    ac = np.correlate(onset, onset, "full")[len(onset) - 1:]
    if ac[0] <= 0:
        return None
    lo, hi = int(round(60 / 180 / HOP)), int(round(60 / 60 / HOP))
    lag = lo + int(np.argmax(ac[lo:hi + 1]))
    if ac[lag] / ac[0] < 0.1:
        return None
    return round(60 / (lag * HOP))


# --- the mix ----------------------------------------------------------------------------------------------------

def music_chain(duration, gain_db, fade_in=0.5, fade_out=1.0):
    """The bed's own filters: cut to the clip, 48 kHz stereo, its gain, the fades."""
    out_at = max(0.0, duration - fade_out)
    return (f"atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=48000:channel_layouts=stereo,volume={gain_db:.2f}dB,"
            f"afade=t=in:st=0:d={fade_in:g},afade=t=out:st={out_at:.3f}:d={fade_out:g}")


def duck_threshold(voice_db, duck_db):
    """sidechaincompress's threshold (linear) for a bed that gives way by about ``duck_db`` at the voice's median
    level: ratio 2, so the threshold sits 2 x duck_db under the voice's RMS (its Hann frame level + HANN_DB)."""
    return 10 ** ((voice_db + HANN_DB - 2 * float(duck_db)) / 20)


def mix_graph(duration, gain_db, cfg, duck=None, tail=""):
    """filter_complex: input 0 = the clip, input 1 = the track (looped, from its start point). ``tail`` is added after
    the sum (the loudnorm), the output is [a]."""
    voice = "[0:a]aformat=sample_rates=48000:channel_layouts=stereo"
    music = f"[1:a]{music_chain(duration, gain_db, cfg.get('fade_in', 0.5), cfg.get('fade_out', 1.0))}"
    if duck is not None and float(cfg.get("duck_db") or 0) > 0:
        # Light ducking: ratio 2, the threshold duck_db x 2 under the voice's median level, so the bed gives way by
        # about duck_db while someone speaks.
        graph = (f"{voice},asplit=2[v][sc];{music}[m];"
                 f"[m][sc]sidechaincompress=threshold={duck:.5f}:ratio=2:attack=50:release=400[md];"
                 f"[v][md]amix=inputs=2:duration=first:normalize=0{tail}[a]")
    else:
        graph = f"{voice}[v];{music}[m];[v][m]amix=inputs=2:duration=first:normalize=0{tail}[a]"
    return graph


def _inputs(clip_path, track_path, start):
    return ["-i", clip_path, "-stream_loop", "-1", *(["-ss", f"{start:.3f}"] if start else []), "-i", track_path]


def _render_mono(clip_path, track_path, start, graph):
    cmd = ["ffmpeg", "-v", "error", *_inputs(clip_path, track_path, start), "-filter_complex", graph,
           "-map", "[a]", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or b"").decode("utf-8", "replace").strip()[-300:])
    return np.frombuffer(r.stdout, np.float32)


def _loudnorm_measure(clip_path, track_path, start, graph):
    """First pass of the two-pass loudnorm: ``graph`` ends with a print_format=json loudnorm."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *_inputs(clip_path, track_path, start),
                        "-filter_complex", graph, "-map", "[a]", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr or "")
    return json.loads(m.group(0)) if m else None


def linear_loudnorm(target, measured):
    """Second pass of a two-pass loudnorm: one constant gain to ``target`` (linear=true)."""
    return (f"loudnorm=I={target:g}:TP={TRUE_PEAK:g}:LRA=11:measured_I={measured['input_i']}"
            f":measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}"
            f":measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}:linear=true")


def mix(clip_path, track, out_path, cfg):
    """Mix ``track`` (a catalog entry with its ``path``) under ``clip_path``'s own sound into ``out_path`` (video
    copied). Returns the report: the track, the voice and bed levels, the bed's gain, the measured gap, the LUFS."""
    cfg = {**DEFAULTS, **(cfg or {})}
    duration = probe_duration(clip_path)
    if not duration:
        raise RuntimeError("no duration")
    start = float(track.get("start") or 0.0)
    under = float(cfg["music_db_under_voice"])
    voice_db = frame_db(read_audio(clip_path))
    mask = speech_mask(voice_db)
    voice = voice_level(voice_db, mask)
    bed = floor_level(frame_db(read_audio(track["path"], start, duration, loop=True)))
    if voice is None or bed is None:
        raise RuntimeError("no voice or no music to measure")
    gain = float(np.clip(voice - under - bed, *GAIN_RANGE))
    duck = None
    if float(cfg.get("duck_db") or 0) > 0:
        duck = duck_threshold(voice, cfg["duck_db"])
    # One corrective pass: the real mix measured the study's way, the gain moved by the error.
    measured_gap = gap_db(frame_db(_render_mono(clip_path, track["path"], start,
                                                mix_graph(duration, gain, cfg, duck))), mask)
    if measured_gap is not None and abs(measured_gap - under) > CORRECT_ABOVE:
        gain = float(np.clip(gain + measured_gap - under, *GAIN_RANGE))
        measured_gap = gap_db(frame_db(_render_mono(clip_path, track["path"], start,
                                                    mix_graph(duration, gain, cfg, duck))), mask)
    normalize = os.environ.get("AUDIO_NORMALIZE", "1").strip() != "0" and cfg.get("target_lufs") is not None
    tail = ""
    if normalize:
        target = float(cfg["target_lufs"])
        measured = _loudnorm_measure(clip_path, track["path"], start, mix_graph(
            duration, gain, cfg, duck, f",loudnorm=I={target:g}:TP={TRUE_PEAK:g}:LRA=11:print_format=json"))
        tail = (f",{linear_loudnorm(target, measured)}" if measured
                else f",loudnorm=I={target:g}:TP={TRUE_PEAK:g}:LRA=11") + ",aresample=48000"
    cmd = ["ffmpeg", "-y", "-v", "error", *_inputs(clip_path, track["path"], start),
           "-filter_complex", mix_graph(duration, gain, cfg, duck, tail),
           "-map", "0:v?", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-movflags", "+faststart", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
        raise RuntimeError((r.stderr or "").strip()[-300:])
    return {"file": track["file"], "title": track.get("title"), "author": track.get("author"),
            "url": track.get("url"), "licence": track.get("licence"),
            "voice_db": round(voice, 1), "bed_db": round(bed, 1), "gain_db": round(gain, 2),
            "gap_db": None if measured_gap is None else round(measured_gap, 1),
            "duck_db": float(cfg.get("duck_db") or 0), **loudness(out_path)}


def normalize_only(clip_path, out_path, target):
    """No music, a target loudness: the clip's sound brought to ``target`` (two-pass, linear), the video copied."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", clip_path, "-vn",
                        "-af", f"loudnorm=I={target:g}:TP={TRUE_PEAK:g}:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr or "")
    af = (linear_loudnorm(target, json.loads(m.group(0))) if m
          else f"loudnorm=I={target:g}:TP={TRUE_PEAK:g}:LRA=11") + ",aresample=48000"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip_path, "-map", "0:v?", "-map", "0:a", "-c:v", "copy",
                        "-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out_path],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError((r.stderr or "").strip()[-300:])
    return loudness(out_path)


def apply(clip_path, clip, cfg):
    """The job's step (main._process_one_clip, after the watermark, before the pristine copy so a restyle keeps it):
    the planned track (clip["music"]) under the clip, in place, or only the target loudness when music is off.
    Returns the report (also kept in clip["audio"]), None when the clip is left as it was. Never raises."""
    if not cfg:
        return None
    tmp = f"{clip_path}.music_tmp.mp4"
    try:
        track = (clip or {}).get("music") if cfg.get("music") else None
        if track and os.path.isfile(track.get("path") or ""):
            rep = mix(clip_path, track, tmp, cfg)
            print(f"   🎵 Music: « {rep['title'] or rep['file']} » ({rep['author'] or '?'}) "
                  f"{rep['gap_db']} dB under the voice, {rep['lufs']} LUFS")
        elif cfg.get("target_lufs") is not None and os.environ.get("AUDIO_NORMALIZE", "1").strip() != "0":
            rep = {"file": None, **normalize_only(clip_path, tmp, float(cfg["target_lufs"]))}
        else:
            return None
        os.replace(tmp, clip_path)
        if clip is not None:
            clip["audio"] = rep
        return rep
    except Exception as e:
        print(f"   ⚠️ Music bed failed ({type(e).__name__}: {e}) — clip kept with its own sound.")
        if os.path.exists(tmp):
            os.remove(tmp)
        return None


def plan_job(shorts, cfg, seed=""):
    """Before the clips are rendered: each clip's track in clip["music"] (catalog fields + path). Returns how many
    clips got one."""
    if not cfg or not cfg.get("music"):
        return 0
    library = tracks(cfg)
    if not library:
        print(f"   🎵 Music on, but no usable track in {music_dir(cfg)}/{CATALOG} "
              f"(a licence and \"content_id\": false) — clips without music.")
        return 0
    n = 0
    for clip, t in zip(shorts, plan(shorts, library, seed)):
        if t:
            clip["music"] = {k: t.get(k) for k in ("file", "path", "title", "author", "url", "licence", "start")}
            n += 1
    return n


# --- the catalog's measured fields ------------------------------------------------------------------------------

def measure_track(path):
    x = read_audio(path)
    return {"duration": round(len(x) / SR, 1), "bpm": bpm(x), **{"lufs": loudness(path)["lufs"]}}


def build_catalog(folder):
    """Fill duration / LUFS / BPM of every catalog entry (the hand-written fields are kept); a music file not in the
    catalog yet is added with empty fields and "content_id": null — not usable until someone checks its page."""
    path = os.path.join(folder, CATALOG)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {"tracks": []}
    entries = data.setdefault("tracks", [])
    known = {e.get("file") for e in entries}
    for name in sorted(os.listdir(folder)):
        if os.path.splitext(name)[1].lower() in MUSIC_EXTENSIONS and name not in known:
            entries.append({"file": name, "title": "", "author": "", "url": "", "licence": "", "content_id": None,
                            "mood": []})
    for e in entries:
        p = os.path.join(folder, e["file"])
        if os.path.isfile(p):
            e.update(measure_track(p))
            print(f"{e['file']}: {e['duration']} s, {e['lufs']} LUFS, {e['bpm']} BPM")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--catalog":
        build_catalog(sys.argv[2] if len(sys.argv) > 2 else music_dir())
    else:
        print("usage: python music_bed.py --catalog [MUSIC_DIR]")
