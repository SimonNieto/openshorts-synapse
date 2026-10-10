"""The music bed (music_bed.py, plus.AUDIO; 9-oct-2026, recette « références »): OptimalHealth's sound measured on 9
hits — a bed ~14 dB under the voice, no whoosh, -16.6 LUFS."""
import json
import os
import subprocess
import tempfile

import numpy as np
import pytest

import music_bed as mb
import plus


def _lib(folder, entries):
    for e in entries:
        open(os.path.join(folder, e["file"]), "wb").close()
    with open(os.path.join(folder, mb.CATALOG), "w", encoding="utf-8") as f:
        json.dump({"tracks": entries}, f)


def _track(name, mood, content_id=False, licence="Pixabay Content License"):
    return {"file": name, "title": name, "author": "a", "url": "u", "licence": licence,
            "content_id": content_id, "mood": mood}


# --- the recipe ---------------------------------------------------------------------------------------------------

def test_the_recipe_copies_their_sound():
    assert plus.AUDIO["music"] is True and plus.AUDIO["music_db_under_voice"] == 20
    assert plus.AUDIO["target_lufs"] == -16.6 and plus.AUDIO["sfx"] is False
    assert 0 < plus.AUDIO["duck_db"] <= 2, "light: their bed is steady within 2-3 dB"


def test_the_job_gets_the_settings_and_no_whoosh(monkeypatch):
    env = plus.job_env({"name": "t", "broll": {"enabled": True}})
    assert json.loads(env["PLUS_AUDIO_JSON"]) == plus.AUDIO
    assert json.loads(env["PLUS_BROLL_JSON"])["sfx"] is False
    monkeypatch.setitem(plus.AUDIO, "sfx", True)
    assert json.loads(plus.job_env({"name": "t", "broll": {"enabled": True}})["PLUS_BROLL_JSON"])["sfx"] is True


def test_config_reads_the_job_and_fills_the_defaults(monkeypatch):
    monkeypatch.delenv("PLUS_AUDIO_JSON", raising=False)
    assert mb.config() is None
    monkeypatch.setenv("PLUS_AUDIO_JSON", json.dumps({"music": False, "target_lufs": -16.6}))
    cfg = mb.config()
    assert cfg["music"] is False and cfg["fade_in"] == 0.5 and cfg["fade_out"] == 1.0
    monkeypatch.setenv("PLUS_AUDIO_JSON", "not json")
    assert mb.config() is None


def test_the_whoosh_and_any_layer_normalise_at_the_job_target(monkeypatch):
    monkeypatch.setenv("PLUS_AUDIO_JSON", json.dumps({"target_lufs": -16.6}))
    assert mb.loudnorm_filter() == "loudnorm=I=-16.6:TP=-2:LRA=11"
    monkeypatch.setenv("PLUS_AUDIO_JSON", json.dumps({"target_lufs": None}))
    assert mb.loudnorm_filter() == "loudnorm=I=-14:TP=-2:LRA=11"


# --- the library ----------------------------------------------------------------------------------------------------

def test_only_tracks_marked_without_content_id_and_with_a_licence_are_used(tmp_path):
    _lib(str(tmp_path), [_track("ok.mp3", "calm"), _track("cid.mp3", "calm", content_id=True),
                         _track("unknown.mp3", "calm", content_id=None), _track("nolic.mp3", "calm", licence="")])
    with open(tmp_path / mb.CATALOG, encoding="utf-8") as f:
        data = json.load(f)
    data["tracks"].append(_track("missing.mp3", "calm"))
    with open(tmp_path / mb.CATALOG, "w", encoding="utf-8") as f:
        json.dump(data, f)
    got = mb.tracks({"dir": str(tmp_path)})
    assert [t["file"] for t in got] == ["ok.mp3"] and got[0]["path"] == os.path.join(str(tmp_path), "ok.mp3")
    assert mb.tracks({"dir": str(tmp_path / "nowhere")}) == []


def test_never_the_same_track_twice_in_a_row_and_the_subject_picks_the_mood():
    lib = [{"file": f"{m}{k}.mp3", "mood": m} for m in ("calm", "tense", "uplifting") for k in (1, 2)]
    shorts = [{"topic_bucket": "brain_danger"}] * 5 + [{"topic_bucket": "self_improvement"}] * 3 + [{}] * 4
    picks = mb.plan(shorts, lib, seed="job")
    names = [p["file"] for p in picks]
    assert all(a != b for a, b in zip(names, names[1:]))
    assert all(n.startswith("tense") for n in names[:5])        # alternates between the two tense tracks
    assert all(n.startswith("uplifting") for n in names[5:8])
    assert all(n.startswith("calm") for n in names[8:])
    assert mb.plan(shorts, lib, seed="job") == picks, "a re-run picks the same"


def test_a_mood_with_one_track_falls_back_to_another_rather_than_repeat():
    lib = [{"file": "tense.mp3", "mood": ["tense"]}, {"file": "calm.mp3", "mood": "calm"}]
    names = [p["file"] for p in mb.plan([{"topic_bucket": "crime_dark"}] * 4, lib)]
    assert names == ["tense.mp3", "calm.mp3", "tense.mp3", "calm.mp3"]
    assert [p["file"] for p in mb.plan([{}] * 3, [{"file": "only.mp3"}])] == ["only.mp3"] * 3
    assert mb.plan([{}, {}], []) == [None, None]


def test_plan_job_writes_each_clip_its_track(tmp_path):
    _lib(str(tmp_path), [_track("a.mp3", "calm"), _track("b.mp3", "curious")])
    shorts = [{"topic_bucket": "science_other"}, {"topic_bucket": "science_other"}, {}]
    assert mb.plan_job(shorts, {**mb.DEFAULTS, "dir": str(tmp_path)}, seed="x") == 3
    assert [c["music"]["file"] for c in shorts] == ["b.mp3", "a.mp3", "b.mp3"]
    assert set(shorts[0]["music"]) >= {"file", "path", "title", "author", "url", "licence"}
    off = [{}]
    assert mb.plan_job(off, {**mb.DEFAULTS, "music": False, "dir": str(tmp_path)}) == 0 and "music" not in off[0]
    assert mb.plan_job([{}], {**mb.DEFAULTS, "dir": str(tmp_path / "empty")}) == 0


# --- the measures (the study's way) -------------------------------------------------------------------------------

def _speech_like(seconds=12.0, voice=0.3, bed=0.3 / 10 ** (14 / 20), sr=mb.SR, seed=1):
    """Syllables of noise (0.15 s on, 0.1 s off) over a steady bed: the voice-to-bed gap is 14 dB."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    on = ((t % 0.25) < 0.15).astype(np.float32)
    v = rng.standard_normal(len(t)).astype(np.float32) * voice * on
    b = (np.sin(2 * np.pi * 220 * t) * bed * np.sqrt(2)).astype(np.float32)
    return v, b


def test_the_gap_is_measured_like_the_study():
    v, b = _speech_like()
    mask = mb.speech_mask(mb.frame_db(v))
    gap = mb.gap_db(mb.frame_db(v + b), mask)
    assert gap == pytest.approx(14.0, abs=1.5)
    assert mb.floor_level(mb.frame_db(b)) == pytest.approx(20 * np.log10(0.3 / 10 ** (14 / 20)) - 4.26, abs=0.5)


def test_bpm_of_a_click_track():
    sr = mb.SR
    x = np.zeros(sr * 20, np.float32)
    for k in np.arange(0, 20, 0.5):                    # 120 BPM
        x[int(k * sr):int(k * sr) + 400] = 0.8
    assert mb.bpm(x) == pytest.approx(120, abs=3)
    assert mb.bpm(np.sin(2 * np.pi * 220 * np.arange(sr * 10) / sr).astype(np.float32)) is None


# --- the graph ------------------------------------------------------------------------------------------------------

def test_the_bed_is_cut_to_the_clip_with_its_fades():
    g = mb.music_chain(40.0, -3.25)
    assert "atrim=0:40.000" in g and "volume=-3.25dB" in g
    assert "afade=t=in:st=0:d=0.5" in g and "afade=t=out:st=39.000:d=1" in g


def test_the_mix_sums_without_lowering_the_voice_and_ducks_only_when_asked():
    plain = mb.mix_graph(30.0, 0.0, mb.DEFAULTS)
    assert "amix=inputs=2:duration=first:normalize=0[a]" in plain and "sidechaincompress" not in plain
    ducked = mb.mix_graph(30.0, 0.0, {**mb.DEFAULTS, "duck_db": 1.5}, mb.duck_threshold(-20.0, 1.5), ",loudnorm=I=-16.6")
    assert "sidechaincompress=threshold=" in ducked and ":ratio=2:" in ducked
    assert ducked.endswith("normalize=0,loudnorm=I=-16.6[a]")
    assert mb.duck_threshold(-20.0, 1.5) == pytest.approx(10 ** ((-20.0 + 4.26 - 3.0) / 20))


def test_the_second_loudnorm_pass_is_linear():
    s = mb.linear_loudnorm(-16.6, {"input_i": "-14.2", "input_tp": "-3.1", "input_lra": "5.0",
                                   "input_thresh": "-24.5", "target_offset": "0.1"})
    assert s.startswith("loudnorm=I=-16.6:TP=-2:LRA=11:measured_I=-14.2") and s.endswith(":linear=true")


# --- the step in the job ------------------------------------------------------------------------------------------

def test_apply_never_breaks_a_clip(monkeypatch, tmp_path):
    clip_path = tmp_path / "c.mp4"
    clip_path.write_bytes(b"x" * 2048)
    track = tmp_path / "t.mp3"
    track.write_bytes(b"y")
    assert mb.apply(str(clip_path), {}, None) is None

    def boom(*a, **k):
        raise RuntimeError("ffmpeg said no")
    monkeypatch.setattr(mb, "mix", boom)
    clip = {"music": {"file": "t.mp3", "path": str(track)}}
    assert mb.apply(str(clip_path), clip, mb.DEFAULTS) is None
    assert clip_path.read_bytes() == b"x" * 2048 and "audio" not in clip
    assert not os.path.exists(f"{clip_path}.music_tmp.mp4")


def test_music_off_still_brings_the_clip_to_the_target(monkeypatch, tmp_path):
    clip_path = tmp_path / "c.mp4"
    clip_path.write_bytes(b"x")
    seen = {}

    def norm(src, out, target):
        seen["target"] = target
        open(out, "wb").write(b"n")
        return {"lufs": target, "true_peak": -3.0}
    monkeypatch.setattr(mb, "normalize_only", norm)
    clip = {"music": {"file": "t.mp3", "path": "/nowhere"}}
    rep = mb.apply(str(clip_path), clip, {**mb.DEFAULTS, "music": False})
    assert seen["target"] == -16.6 and rep["file"] is None and clip["audio"] == rep and clip_path.read_bytes() == b"n"
    # everything off: the clip is not touched
    assert mb.apply(str(clip_path), {}, {**mb.DEFAULTS, "music": False, "target_lufs": None}) is None


def test_main_mixes_before_the_pristine_copy_and_plans_before_the_pool():
    src = open(os.path.join(os.path.dirname(mb.__file__), "main.py"), encoding="utf-8").read()
    step = src.index("music_bed.apply(clip_final_path, clip, audio_cfg)")
    assert src.index("apply_watermark(clip_final_path)") < step < src.index('".pre_fx.mp4"')
    assert src.index("music_bed.plan_job(shorts, audio_cfg") < src.index("ThreadPoolExecutor(max_workers=min(clip_workers")


# --- one real mix (ffmpeg, no download: the voice and the music are made here) ----------------------------------

def test_a_real_mix_lands_14_db_under_the_voice_at_minus_16_6_lufs(tmp_path):
    clip = str(tmp_path / "clip.mp4")
    pad = str(tmp_path / "pad.wav")
    # a "voice": pink-noise syllables (0.15 s on / 0.1 s off) at a speaking level, over a black picture
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=64x64:d=12:r=10",
                    "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.25:d=12:r=44100",
                    "-filter_complex", "[1:a]volume='lt(mod(t,0.25),0.15)':eval=frame[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac", "-shortest", clip], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc=0.2*sin(2*PI*220*t)+0.1*sin(2*PI*330*t):s=44100:d=5", pad], check=True)
    out = str(tmp_path / "out.mp4")
    rep = mb.mix(clip, {"file": "pad.wav", "path": pad}, out, {**mb.DEFAULTS, "duck_db": 1.5})
    assert rep["gap_db"] == pytest.approx(14.0, abs=1.0)
    assert rep["lufs"] == pytest.approx(-16.6, abs=0.6) and rep["true_peak"] <= -1.0
    assert mb.probe_duration(out) == pytest.approx(mb.probe_duration(clip), abs=0.15)   # looped under all 12 s


def test_the_library_is_found_from_the_app_and_from_a_worktree(monkeypatch, tmp_path):
    import os
    monkeypatch.delenv("BACKGROUND_MUSIC_DIR", raising=False)
    # given explicitly: as is
    assert mb.music_dir({"dir": "/x/music"}) == "/x/music"
    monkeypatch.setenv("BACKGROUND_MUSIC_DIR", "/y/music")
    assert mb.music_dir() == "/y/music"
    monkeypatch.delenv("BACKGROUND_MUSIC_DIR")
    # the app runs from its folder: ./music with its catalog
    app = tmp_path / "app"
    (app / "music").mkdir(parents=True)
    (app / "music" / mb.CATALOG).write_text("{}")
    monkeypatch.chdir(app)
    assert mb.music_dir() == str(app / "music")
    # from a worktree without a catalog of its own: the code's own folder, then its parents (the repo's library)
    wt = app / ".claude" / "worktrees" / "x"
    (wt / "music").mkdir(parents=True)
    monkeypatch.chdir(wt)
    monkeypatch.setattr(mb, "__file__", str(wt / "music_bed.py"))
    assert mb.music_dir() == str(app / "music")
    assert os.path.isfile(os.path.join(mb.music_dir(), mb.CATALOG))
