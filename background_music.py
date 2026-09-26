"""Optional background-music mixing (BACKGROUND_MUSIC=1).

Off by default: OpenShorts ships no music library, and licensing a track is
the user's call, not this pipeline's. Drop royalty-free tracks into
BACKGROUND_MUSIC_DIR (default "music" — already visible inside the backend
container via the existing ``.:/app`` bind mount, nothing to add there) and
set BACKGROUND_MUSIC=1; main.py then mixes a random track under each clip's
own audio, in place, right after the watermark burn so every derived file
(hook, captions) copies the mixed audio forward untouched.
"""
import glob
import os
import random
import subprocess

from ffmpeg_utils import LOUDNORM_FILTER

MUSIC_EXTENSIONS = (".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg")


def _pick_track(music_dir):
    tracks = [f for f in glob.glob(os.path.join(music_dir, "*"))
              if os.path.splitext(f)[1].lower() in MUSIC_EXTENSIONS]
    return random.choice(tracks) if tracks else None


def add_background_music(clip_path, music_dir=None, volume=None):
    """Mix a random track from ``music_dir`` under ``clip_path``'s own audio, in place.

    Returns True if music was mixed in, False if the clip was left untouched
    (no music folder, no tracks in it, or the mix failed) — never raises, so a
    missing or empty music folder just means no music instead of a failed job.
    """
    music_dir = music_dir or os.environ.get("BACKGROUND_MUSIC_DIR", "music")
    if volume is None:
        volume = float(os.environ.get("BACKGROUND_MUSIC_VOLUME", "0.12"))
    if not os.path.isdir(music_dir):
        return False
    track = _pick_track(music_dir)
    if not track:
        print(f"🎵 BACKGROUND_MUSIC=1 but no tracks found in {music_dir}/ — skipping.")
        return False

    # Music is scaled down and summed with the clip's own audio (normalize=0,
    # or amix would also quiet the speech). Re-normalized to the same -14 LUFS
    # target as every other delivered clip (ffmpeg_utils.LOUDNORM_FILTER) so
    # music-mixed and plain clips land at the same loudness.
    normalize = os.environ.get("AUDIO_NORMALIZE", "1").strip() != "0"
    mix = (f"[1:a]volume={volume}[music];"
           f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mixed]")
    filter_complex = f"{mix};[mixed]{LOUDNORM_FILTER}[a]" if normalize else f"{mix};[mixed]anull[a]"

    tmp_path = f"{clip_path}.music_tmp.mp4"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", clip_path,
        # Looped past the clip's length; "duration=first" in the mix trims it
        # back down, so a 20s track under a 60s clip still covers the whole thing.
        "-stream_loop", "-1", "-i", track,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        tmp_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(tmp_path) or os.path.getsize(tmp_path) < 1024:
        print(f"⚠️ Background music mix failed for {os.path.basename(clip_path)} "
              f"({(result.stderr or '').strip()[-300:]}) — leaving clip as-is.")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False

    os.replace(tmp_path, clip_path)
    print(f"🎵 Background music added: {os.path.basename(track)}")
    return True
