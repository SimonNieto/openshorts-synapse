"""The HQ render chain (profile fx.hq_chain): every layer of a clip's render
keeps its historical encoder args when the switch is off, and goes
near-lossless (only the delivered layer compresses) when it is on."""
import os
import tempfile

import pytest
from PIL import Image

import ffmpeg_utils as ffu
import plus

LEGACY = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"]


@pytest.fixture(autouse=True)
def _x264_only(monkeypatch):
    monkeypatch.setenv("FFMPEG_ENCODER", "x264")
    monkeypatch.delenv("PLUS_HQ_CHAIN", raising=False)


class TestLayerEncodeArgs:
    def test_off_by_default_returns_the_legacy_args_untouched(self):
        assert ffu.layer_encode_args(LEGACY) == LEGACY
        assert ffu.layer_encode_args(LEGACY, final=True) == LEGACY
        assert ffu.layer_encode_args(LEGACY) is not LEGACY

    def test_env_switch_makes_intermediate_layers_near_lossless(self, monkeypatch):
        monkeypatch.setenv("PLUS_HQ_CHAIN", "1")
        args = ffu.layer_encode_args(LEGACY)
        assert args[:2] == ["-c:v", "libx264"]
        assert args[args.index("-preset") + 1] == "fast"
        assert args[args.index("-crf") + 1] == str(ffu.HQ_CHAIN_CRF)
        assert ffu.HQ_CHAIN_CRF <= 14

    def test_the_delivered_layer_compresses_at_the_quality_tier(self, monkeypatch):
        monkeypatch.setenv("PLUS_HQ_CHAIN", "1")
        assert ffu.layer_encode_args(LEGACY, final=True) == ffu.video_encode_args(ffu.QUALITY)

    def test_the_context_wins_over_the_env_and_is_restored(self, monkeypatch):
        monkeypatch.setenv("PLUS_HQ_CHAIN", "1")
        with ffu.hq_chain(False):
            assert ffu.layer_encode_args(LEGACY) == LEGACY
        assert ffu.layer_encode_args(LEGACY) != LEGACY
        monkeypatch.delenv("PLUS_HQ_CHAIN")
        with ffu.hq_chain(True):
            assert ffu.layer_encode_args(LEGACY) != LEGACY
            with ffu.hq_chain(None):
                assert ffu.layer_encode_args(LEGACY) == LEGACY
        assert ffu.layer_encode_args(LEGACY) == LEGACY


class TestProfile:
    def test_on_for_every_job_since_the_house_recipe(self):
        # Was a profile switch (fx.hq_chain, off by default) until 1-oct-2026: now plus.FX, for every job,
        # whatever an old profile saved; the music bed that rode next to it is gone.
        assert plus.FX["hq_chain"] is True
        for profile in ({}, {"fx": {"hq_chain": False}}, {"music": {"enabled": True, "mood": "calm"}}):
            env = plus.job_env(profile)
            assert env["PLUS_HQ_CHAIN"] == "1" and "PLUS_MUSIC_ON" not in env
        assert "fx" not in plus.sanitize({"fx": {"hq_chain": False}})


def _codec_args(cmd):
    """The -c:v / -preset / -crf part of an ffmpeg command."""
    out = {}
    for flag in ("-c:v", "-preset", "-crf", "-cq"):
        if flag in cmd:
            out[flag] = cmd[cmd.index(flag) + 1]
    return out


class _Captured:
    def __init__(self):
        self.cmds = []

    def __call__(self, cmd, *a, **k):
        self.cmds.append(list(cmd))

        class R:
            returncode = 0
            stderr = ""
            stdout = ""
        return R()


class TestCallSites:
    """Each layer builds its ffmpeg command through layer_encode_args."""

    def test_broll_overlay_is_an_intermediate_layer(self, monkeypatch):
        import broll
        import viral_fx
        tmp = tempfile.mkdtemp(prefix="chain_")
        img = os.path.join(tmp, "pic.jpg")
        Image.new("RGB", (256, 256), (120, 60, 30)).save(img)
        monkeypatch.setattr(viral_fx, "_probe", lambda p: {"w": 216, "h": 384, "fps": 30, "duration": 5.0})
        monkeypatch.delenv("EDIT_STYLE", raising=False)
        cap = _Captured()
        monkeypatch.setattr(broll.subprocess, "run", cap)
        item = [{"t": 1.0, "dur": 1.2, "layout": "rise", "size": 28, "position": "below", "_img": img}]
        broll.overlay_items("clip.mp4", os.path.join(tmp, "o.mp4"), item)
        assert _codec_args(cap.cmds[-1]) == {"-c:v": "libx264", "-preset": "veryfast", "-crf": "19"}
        with ffu.hq_chain(True):
            broll.overlay_items("clip.mp4", os.path.join(tmp, "o.mp4"), item)
        assert _codec_args(cap.cmds[-1]) == {"-c:v": "libx264", "-preset": "fast", "-crf": str(ffu.HQ_CHAIN_CRF)}

    def test_motion_is_intermediate_and_captions_are_the_delivered_layer(self, monkeypatch):
        import viral_fx
        monkeypatch.setattr(viral_fx, "_probe", lambda p: {"w": 1080, "h": 1920, "fps": 30, "duration": 6.0})
        cap = _Captured()
        monkeypatch.setattr(viral_fx.subprocess, "run", cap)
        words = [{"text": w, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, w in enumerate("we gave the mice psilocybin and waited".split())]
        tmp = tempfile.mkdtemp(prefix="chain_")
        out = os.path.join(tmp, "o.mp4")
        viral_fx.apply_motion("clip.mp4", words, "natural", out, opts={})
        viral_fx.apply_captions("clip.mp4", words, "natural", out)
        assert [_codec_args(c) for c in cap.cmds] == [{"-c:v": "libx264", "-preset": "veryfast", "-crf": "19"}] * 2
        cap.cmds.clear()
        with ffu.hq_chain(True):
            viral_fx.apply_motion("clip.mp4", words, "natural", out, opts={})
            viral_fx.apply_captions("clip.mp4", words, "natural", out)
            viral_fx.apply("clip.mp4", words, "natural", out, opts={})
        motion, captions, both = (_codec_args(c) for c in cap.cmds)
        assert motion == {"-c:v": "libx264", "-preset": "fast", "-crf": str(ffu.HQ_CHAIN_CRF)}
        assert captions == both == _codec_args(ffu.video_encode_args(ffu.QUALITY))

    def test_reactions_segments_follow_the_chain(self):
        import reactions
        assert reactions._encode_args() == ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
        with ffu.hq_chain(True):
            assert _codec_args(reactions._encode_args()) == {"-c:v": "libx264", "-preset": "fast",
                                                             "-crf": str(ffu.HQ_CHAIN_CRF)}

    def test_the_hook_keeps_quality_off_and_goes_near_lossless_on(self, monkeypatch):
        import hooks
        tmp = tempfile.mkdtemp(prefix="chain_")
        src = os.path.join(tmp, "clip.mp4")
        open(src, "wb").close()
        monkeypatch.setattr(hooks.subprocess, "check_output", lambda *a, **k: b"1080x1920\n")
        cap = _Captured()
        monkeypatch.setattr(hooks.subprocess, "run", cap)
        hooks.add_hook_to_video(src, "People love excuses", os.path.join(tmp, "h.mp4"), style="bold", duration=3)
        assert _codec_args(cap.cmds[-1]) == _codec_args(ffu.video_encode_args(ffu.QUALITY))
        with ffu.hq_chain(True):
            hooks.add_hook_to_video(src, "People love excuses", os.path.join(tmp, "h.mp4"), style="bold", duration=3)
        assert _codec_args(cap.cmds[-1]) == {"-c:v": "libx264", "-preset": "fast", "-crf": str(ffu.HQ_CHAIN_CRF)}
