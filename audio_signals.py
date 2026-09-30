"""Audio cues for the scoring pass (AUDIO_SIGNALS=1, profile: selection.audio_signals).

The moment picker reads the transcript and nothing else: a line that made the
room laugh and the same line said flat are the same text. This measures, per
scoring window, what the sound adds — how loud and how lively the delivery is,
how fast people talk, what is heard BETWEEN the words (laughter, people
talking over each other) and the longest silence — and main.get_viral_clips
puts those few numbers in the windows' JSON with a note on how to read them
(gemini_worker.AUDIO_SIGNALS_ADDENDUM).

No model: one ffmpeg pass over the audio (8 kHz mono) and numpy, plus the
word timestamps Whisper already gave. Any failure returns nothing and the
scoring runs on the text alone.
"""
from __future__ import annotations

import subprocess
import threading

import numpy as np

RATE = 8000          # Hz: plenty for a loudness envelope
HOP = 0.5            # seconds per envelope value
MIN_GAP = 0.5        # a silence between two words this long can hold a reaction


def envelope(video_path, hop=HOP, timeout=900):
    """RMS of the source's audio every ``hop`` seconds, as a numpy array
    ([] when there is no audio or ffmpeg fails). Read as a stream: a
    three-hour source never sits in memory."""
    per_hop = max(1, int(RATE * hop))
    block = per_hop * 2 * 240                     # 2 bytes a sample, 2 minutes a read
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", video_path, "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    killer = threading.Timer(timeout, proc.kill)
    killer.start()
    out, rest = [], b""
    try:
        while True:
            data = proc.stdout.read(block)
            if not data:
                break
            data = rest + data
            usable = len(data) - len(data) % (per_hop * 2)
            rest = data[usable:]
            if usable:
                samples = np.frombuffer(data[:usable], dtype=np.int16).astype(np.float32)
                out.append(np.sqrt(np.mean(samples.reshape(-1, per_hop) ** 2, axis=1)))
    finally:
        killer.cancel()
        proc.stdout.close()
        proc.wait()
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


def speech_level(rms):
    """The episode's usual speaking level: the median of the envelope once
    the silences are left out (0.0 for an empty or silent track)."""
    rms = np.asarray(rms, dtype=np.float32)
    if rms.size == 0:
        return 0.0
    loud = rms[rms > 0.1 * float(np.percentile(rms, 95))]
    return float(np.median(loud)) if loud.size else 0.0


def window_features(rms, ref, words, start, end, hop=HOP):
    """The cues of one window, or None when it holds no sound to measure.
    ``words``: [{'w', 's', 'e'}] of the whole source, sorted. Levels are
    relative to ``ref`` (speech_level): 1.0 is the episode's usual level."""
    a, b = int(max(0.0, start) / hop), int(max(0.0, end) / hop) + 1
    seg = np.asarray(rms[a:b], dtype=np.float32)
    if seg.size == 0 or ref <= 0:
        return None
    inside = [w for w in words if w["s"] >= start and w["e"] <= end]
    mean = float(seg.mean())
    between, pause = [], 0.0
    for prev, nxt in zip(inside, inside[1:]):
        gap = nxt["s"] - prev["e"]
        pause = max(pause, gap)
        if gap >= MIN_GAP:
            i, j = int(np.ceil(prev["e"] / hop)), int(nxt["s"] / hop)   # the hops wholly inside the gap
            between.extend(float(x) for x in rms[i:j])
    return {
        "loud": round(mean / ref, 2),
        "peak": round(float(seg.max()) / ref, 1),
        "var": round(float(seg.std()) / mean, 2) if mean > 0 else 0.0,
        "wps": round(len(inside) / max(1e-6, end - start), 1),
        "react": round(float(np.mean(between)) / ref, 2) if between else 0.0,
        "pause": round(pause, 1),
    }


def for_windows(video_path, windows, words, hop=HOP):
    """({window id: cues}, the episode's median words per second) for the
    scoring windows. Raises when the audio cannot be read — the caller falls
    back to the text alone."""
    rms = envelope(video_path, hop)
    ref = speech_level(rms)
    if ref <= 0:
        raise RuntimeError("no audio level could be measured")
    out = {}
    for w in windows:
        cues = window_features(rms, ref, words, float(w["start"]), float(w["end"]), hop)
        if cues:
            out[w["id"]] = cues
    rates = sorted(c["wps"] for c in out.values())
    return out, (rates[len(rates) // 2] if rates else 0.0)
