"""end_on_sentence (CLEAN_END=1) on transcripts Whisper left unpunctuated.

Half of JRE #2515 (Chase Hughes-001) came back without a single full stop, so
the search for one found nothing and a clip ended on "...he's also been into".
With the playbook a pause counts as the end of a sentence, and a cut that
still stops mid-thought is flagged."""
import pytest

main = pytest.importorskip("main")


def words(spec):
    """'a b c |0.9 d e' -> words 0.4 s long, 0.1 s apart, with a 0.9 s pause
    before 'd'."""
    out, t = [], 0.0
    for tok in spec.split():
        if tok.startswith("|"):
            t += float(tok[1:]) - 0.1
            continue
        out.append({"w": tok, "s": round(t, 2), "e": round(t + 0.4, 2)})
        t += 0.5
    return out


def end_after(ws, word_index):
    return ws[word_index]["e"] + 0.02


RUN = " ".join(f"w{i}" for i in range(40))            # 20 s, no full stop, no pause


def test_classic_mode_ignores_pauses_and_never_flags():
    ws = words(RUN + " |0.9 " + RUN)
    clip = {"start": 0.0, "end": end_after(ws, 43)}       # 4 words past the pause
    main.end_on_sentence(clip, ws, 15, 60)
    assert clip == {"start": 0.0, "end": end_after(ws, 43)}


def test_playbook_trims_back_to_a_pause():
    ws = words(RUN + " |0.9 " + RUN)
    clip = {"start": 0.0, "end": end_after(ws, 43)}
    main.end_on_sentence(clip, ws, 15, 60, pauses=True)
    assert clip["clean_end"] == "trimmed" and not clip.get("end_mid_sentence")
    assert ws[39]["e"] < clip["end"] < ws[40]["s"], "the cut sits inside the pause after w39"


def test_playbook_runs_on_to_the_next_pause():
    ws = words(RUN + " |0.9 " + RUN)
    clip = {"start": 0.0, "end": end_after(ws, 35)}       # the pause is 2 s ahead, nothing behind
    main.end_on_sentence(clip, ws, 15, 60, pauses=True)
    assert clip["clean_end"] == "extended"
    assert ws[39]["e"] < clip["end"] < ws[40]["s"]


def test_playbook_falls_back_to_a_breath():
    ws = words(RUN + " |0.4 " + RUN)                      # 0.4 s: a breath, not a pause
    clip = {"start": 0.0, "end": end_after(ws, 43)}
    main.end_on_sentence(clip, ws, 15, 60, pauses=True)
    assert clip["clean_end"] == "trimmed" and not clip.get("end_mid_sentence")
    assert ws[39]["e"] < clip["end"] < ws[40]["s"]


def test_a_full_stop_in_reach_beats_a_breath():
    ws = words(RUN + " end. a b c |0.4 d e f g")
    stop = next(i for i, w in enumerate(ws) if w["w"] == "end.")
    clip = {"start": 0.0, "end": end_after(ws, stop + 5)}  # after "d"
    main.end_on_sentence(clip, ws, 15, 60, pauses=True)
    assert clip["clean_end"] == "trimmed"
    assert ws[stop]["e"] < clip["end"] <= ws[stop + 1]["s"]


def test_playbook_flags_a_cut_with_nothing_in_reach():
    ws = words(RUN + " " + RUN)
    clip = {"start": 0.0, "end": end_after(ws, 50)}
    main.end_on_sentence(clip, ws, 15, 60, pauses=True)
    assert clip["end_mid_sentence"] is True and clip["end"] == end_after(ws, 50)
    assert "clean_end" not in clip


def test_a_clip_already_ending_on_a_pause_is_left_alone():
    ws = words(RUN + " |0.9 " + RUN)
    clip = {"start": 0.0, "end": ws[39]["e"] + 0.3}
    main.end_on_sentence(clip, ws, 15, 60, pauses=True)
    assert clip == {"start": 0.0, "end": ws[39]["e"] + 0.3}


def test_punctuated_cuts_are_the_same_in_both_modes():
    ws = words(RUN + " done. and then because " + RUN)
    for pauses in (False, True):
        clip = {"start": 0.0, "end": end_after(ws, 43)}       # after "because"
        main.end_on_sentence(clip, ws, 15, 60, pauses=pauses)
        assert clip["clean_end"] == "trimmed" and not clip.get("end_mid_sentence"), pauses
        assert ws[40]["e"] < clip["end"] <= ws[41]["s"], pauses


def test_the_flag_reaches_the_stats_json(tmp_path):
    import json
    import playbook
    path = playbook.export_clip({"start": 0.0, "end": 30.0, "end_mid_sentence": True}, str(tmp_path),
                                "x_clip_1.mp4", [])
    assert json.load(open(path, encoding="utf-8"))["end_mid_sentence"] is True
