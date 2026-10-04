"""Speaker labels Whisper invents at the start of a segment.

Whisper learnt from podcast transcripts written "Name: text", so it sometimes
opens a segment with a full name nobody says: "Trevor Burrus That's not TRT,
really, right?" / "Aaron Powell That's not TRT." (the hosts of an unrelated
podcast, in JRE #2553 with Andrew Huberman). The episode brief then took them
for the host and the guest, and the credit line of every description of the
job read "with Trevor Burrus & Aaron Powell" (4-oct-2026).

A label is a "First Last" pair that opens a sentence (segment start, or after
. ! ?), is followed by a capitalised word, does so at least twice, and is never
said anywhere else. Names of the episode title are never touched. The label is
removed from the segment text, its words, and the full text.
"""
import re
from collections import Counter

_CAP = r"[A-Z][a-z]+(?:['’-][A-Za-z]+)?"
# "First Last" opening a sentence, then a capitalised word (the real sentence).
_LABEL_AT = re.compile(r"(?:^|(?<=[.!?])\s+)(" + _CAP + r" " + _CAP + r"):?\s+(?=[A-Z0-9])")


def find_labels(segments, keep: str = "") -> list:
    """The invented labels of a transcript, most frequent first."""
    texts = [(s.get("text") or "").strip() for s in segments or []]
    at_label = Counter(m.group(1) for t in texts for m in _LABEL_AT.finditer(t))
    keep_low = (keep or "").lower()
    full = "\n".join(texts)
    labels = []
    for name, n in at_label.most_common():
        if n < 2 or any(part.lower() in keep_low for part in name.split()):
            continue
        said = len(re.findall(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])", full))
        if said == n:  # every occurrence is a label: nobody says the name
            labels.append(name)
    return labels


def _drop_from_words(words, name):
    """Remove the label's two words wherever they open a sentence."""
    first, last = name.split(" ")
    out, i = [], 0
    while i < len(words):
        w0 = (words[i].get("word") or "").strip()
        w1 = (words[i + 1].get("word") or "").strip().rstrip(":") if i + 1 < len(words) else ""
        opens = i == 0 or (out and (out[-1].get("word") or "").strip()[-1:] in ".!?")
        if opens and w0 == first and w1 == last:
            i += 2
            continue
        out.append(words[i])
        i += 1
    return out


def strip_speaker_labels(transcript, keep: str = "") -> dict:
    """Clean ``transcript`` in place. Returns {label: times removed}."""
    if not transcript or not transcript.get("segments"):
        return {}
    labels = find_labels(transcript["segments"], keep)
    if not labels:
        return {}
    removed = Counter()
    for seg in transcript["segments"]:
        text = seg.get("text") or ""
        for name in labels:
            pat = re.compile(r"(^|(?<=[.!?]))(\s*)" + re.escape(name) + r":?\s+(?=[A-Z0-9])")
            text, n = pat.subn(r"\1\2", text)
            removed[name] += n
        seg["text"] = text
        if seg.get("words"):
            for name in labels:
                seg["words"] = _drop_from_words(seg["words"], name)
            if seg["words"]:
                seg["start"] = seg["words"][0].get("start", seg.get("start"))
    if transcript.get("text"):
        for name in labels:
            transcript["text"] = re.sub(r"(^|(?<=[.!?]))(\s*)" + re.escape(name) + r":?\s+(?=[A-Z0-9])",
                                        r"\1\2", transcript["text"])
    return dict(removed)
