"""Whisper's invented speaker labels (transcript_clean), and the credit line
that must never name someone nobody said (playbook.credit_line spoken=)."""
import copy

import playbook
import transcript_clean as tc


def _seg(start, text):
    words, t = [], start
    for w in text.split():
        words.append({"word": " " + w, "start": round(t, 2), "end": round(t + 0.2, 2)})
        t += 0.25
    return {"start": start, "end": t, "text": " " + text, "words": words}


# The real case: JRE #2553 with Andrew Huberman, labels of another podcast's hosts.
JRE = {"text": "", "segments": [
    _seg(230.0, "Look at the guys at the gym."),
    _seg(233.8, "Trevor Burrus That's not TRT, really, right?"),
    _seg(235.3, "Aaron Powell That's not TRT."),
    _seg(235.9, "Trevor Burrus That's really they're just doing juice."),
    _seg(237.2, "Aaron Powell Yeah, they're just doing juice."),
    _seg(1441.2, "Trevor Burrus And you have to wade through 10 different articles"),
]}
TITLE = "Joe Rogan Experience #2553 - Andrew Huberman"


def test_labels_found_and_removed_everywhere():
    t = copy.deepcopy(JRE)
    t["text"] = " ".join(s["text"] for s in t["segments"])
    assert tc.find_labels(t["segments"], TITLE) == ["Trevor Burrus", "Aaron Powell"]
    removed = tc.strip_speaker_labels(t, TITLE)
    assert removed == {"Trevor Burrus": 3, "Aaron Powell": 2}
    seg = t["segments"][1]
    assert seg["text"].strip() == "That's not TRT, really, right?"
    assert [w["word"].strip() for w in seg["words"]][:2] == ["That's", "not"]
    assert seg["start"] == seg["words"][0]["start"], "the segment starts on its first real word"
    assert "Burrus" not in t["text"] and "Powell" not in t["text"]
    assert t["segments"][0]["text"].strip() == "Look at the guys at the gym."


def test_a_name_people_really_say_is_kept():
    segs = [_seg(0, "Rick Rubin Made the record in a house."),
            _seg(3, "Rick Rubin Told me that."),
            _seg(6, "I asked Rick Rubin about it.")]
    assert tc.find_labels(segs) == [], "said mid-sentence once: a real name, not a label"


def test_title_names_and_single_hits_are_kept():
    segs = [_seg(0, "Andrew Huberman Is here today."), _seg(2, "Andrew Huberman Thanks for coming.")]
    assert tc.find_labels(segs, TITLE) == []
    assert tc.find_labels([_seg(0, "Jane Doe Said hello.")]) == [], "one hit is not a pattern"
    assert tc.strip_speaker_labels({"segments": []}) == {}


def test_lowercase_sentence_after_a_name_is_not_a_label():
    segs = [_seg(0, "Joe Rogan said it twice."), _seg(2, "Joe Rogan said it again.")]
    assert tc.find_labels(segs) == []


def test_credit_names_only_guests_who_are_said():
    src = "b8e46c24-7f5e-48cf-8adc-c2d2677a241e_Joe Rogan Experience #2553 - Andrew Huberman-004.mkv"
    brief = {"speakers": [{"name": "Trevor Burrus"}, {"name": "Aaron Powell"}]}
    clean = "Look at the guys at the gym. That's not TRT."
    assert playbook.credit_line(src, brief, spoken=clean) == (
        "Clip from Joe Rogan Experience, Ep. 2553 - Andrew Huberman. All rights to the original creators.")
    said = "and then Powell told me"
    assert "with Aaron Powell" in playbook.credit_line(src, brief, spoken=said)
    # Without the transcript (older callers): unchanged behaviour.
    assert "with Trevor Burrus & Aaron Powell" in playbook.credit_line(src, brief)
