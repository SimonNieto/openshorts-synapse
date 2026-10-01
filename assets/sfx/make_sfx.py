"""Make the B-roll sound effects (Clip Generator++ profile broll.sfx) from scratch,
so they are ours and free of any licence: run once, commit the .wav.

    python assets/sfx/make_sfx.py

* whoosh_soft.wav — 0.55 s of band-passed noise whose centre rises from ~300 Hz
  to ~1.8 kHz under a sine envelope: a soft air movement, the sound a full-screen
  picture makes when it arrives. Peak -6 dBFS; broll.overlay_items mixes it at
  SFX_GAIN_DB (-18 dB) under the voice.
"""
import os
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 48000


def _bandpass_sweep(x, f_lo, f_hi, q=1.6):
    """A biquad band-pass whose centre frequency glides from f_lo to f_hi over the signal."""
    n = len(x)
    y = np.zeros(n)
    x1 = x2 = y1 = y2 = 0.0
    for i in range(n):
        f = f_lo * (f_hi / f_lo) ** (i / n)
        w0 = 2 * np.pi * f / SR
        alpha = np.sin(w0) / (2 * q)
        b0, b1, b2 = alpha, 0.0, -alpha
        a0, a1, a2 = 1 + alpha, -2 * np.cos(w0), 1 - alpha
        y0 = (b0 * x[i] + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2) / a0
        x2, x1 = x1, x[i]
        y2, y1 = y1, y0
        y[i] = y0
    return y


def whoosh(duration=0.55, seed=3):
    n = int(SR * duration)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 1.0, n)
    y = _bandpass_sweep(noise, 300.0, 1800.0)
    env = np.sin(np.pi * t / duration) ** 1.4 * (0.55 + 0.45 * (1 - t / duration))
    y *= env
    y /= max(1e-9, np.max(np.abs(y)))
    return y * 10 ** (-6 / 20)


def write_wav(path, y):
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    out = os.path.join(HERE, "whoosh_soft.wav")
    write_wav(out, whoosh())
    print(f"wrote {out} ({os.path.getsize(out) // 1024} KB)")
