"""lineup.py + the /api/lineup routes (5-oct-2026): the catalogue of every clip on disk, the category corrected by
hand (metadata.json's mtime kept), the variety rules and their alerts, the deterministic order proposal, the hook
jury in the background (hook_jury mocked: it is built apart) and the thumbnail (hostile ids refused)."""
import json
import os
import shutil
import subprocess
import sys
import threading
import types
from datetime import datetime, timezone

import pytest

import lineup

NOW = datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc).timestamp()
DAY = 86400
RETENTION = 8 * DAY

JOB_A = "aaaaaaaa-0000-4000-8000-000000000001"     # JRE #2553, piece 004
JOB_B = "bbbbbbbb-0000-4000-8000-000000000002"     # JRE #2553, piece 001: the same episode
JOB_C = "cccccccc-0000-4000-8000-000000000003"     # Lex Fridman #400
GONE = "dddddddd-0000-4000-8000-000000000004"      # in the plan, gone from the disk

C2_CLIP_KEYS = {"job_id", "clip_index", "ref", "title", "hook", "video_url", "thumb_url", "duration", "category",
                "category_label", "category_source", "show", "episode", "guest", "episode_key", "title_form",
                "moment_nature", "ai_score", "status", "slots", "published_at", "stats", "jury", "expires_in_days",
                "kept", "niche", "upload_profile"}


def ts(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


def short(title, bucket=None, score=None, **extra):
    s = {"video_title_for_youtube_short": title, "start": 10.0, "end": 40.5}
    if bucket:
        s["topic_bucket"] = bucket
    if score is not None:
        s["predicted_score"] = score
    s.update(extra)
    return s


def make_job(output, job_id, source, shorts, missing=(), keep=False, age_days=1.0):
    d = output / job_id
    d.mkdir(parents=True)
    base = f"{job_id}_{source}"
    for i, s in enumerate(shorts):
        name = f"subtitled_100_hooked_99_{base}_clip_{i + 1}.mp4"
        s.setdefault("video_url", f"/videos/{job_id}/{name}")
        if i not in missing:
            (d / name).write_bytes(b"\x00")
    meta = d / f"{base}_metadata.json"
    meta.write_text(json.dumps({"source_video": f"{base}.mkv", "shorts": shorts, "niche": "Joe Rogan podcast",
                                "niche_guess": "podcast", "upload_profile": "default"}), encoding="utf-8")
    if keep:
        (d / ".keep").write_text("")
    t = NOW - age_days * DAY
    os.utime(meta, (t, t))
    os.utime(d, (t, t))
    return d


def entry(job, i, platform, day, hhmm, posted=False, auto=True, title="A title?"):
    return {"id": f"{job[:4]}-{i}-{platform}-{day}", "job_id": job, "clip_index": i, "title": title,
            "platform": platform, "date": day, "time": hhmm, "posted": posted, "auto": auto,
            "source": "upload-post" if auto else None, "profile": "default"}


@pytest.fixture(autouse=True)
def no_jury(monkeypatch):
    """No hook_jury unless a test brings its fake one (the real module is another lot's), and the switch in its
    shipped position (on) unless a test turns it off."""
    monkeypatch.setitem(sys.modules, "hook_jury", None)
    monkeypatch.setattr(lineup, "JURY_ENABLED", True)


@pytest.fixture
def jury_off(monkeypatch):
    monkeypatch.setattr(lineup, "JURY_ENABLED", False)


def test_the_switch_ships_on():
    with open(lineup.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "\nJURY_ENABLED = True\n" in src, "switched on at the user's request (5-oct-2026)"


@pytest.fixture
def world(tmp_path):
    out = tmp_path / "output"
    make_job(out, JOB_A, "Joe Rogan Experience #2553 - Andrew Huberman-004", [
        short("Is your ER doctor as impaired as a drunk?", "medical_mystery", 78,
              auto_hook={"text": "3 a.m. ER? Ask this first."}, moment_nature="threat_to_you",
              published={"via": "upload-post", "at": ts("2026-10-05T07:46:00"), "scheduled_for": None}),
        short("Do medical errors kill 251,000 a year?", "medical_mystery", 82,
              published={"via": "upload-post", "at": ts("2026-10-04T20:00:00"), "scheduled_for": "2026-10-07T12:00:00"}),
        short("Should you get a full-body MRI?", "medical_mystery", 80),
        short("Are patients going rogue on their doctors?", "substances", 75, category_manual="mind_psychology"),
        short("A clip whose file is gone", "medical_mystery", 99),
        short("Can AI escape onto the internet?", "science_other", 83,
              published={"via": "upload-post", "at": ts("2026-10-04T20:00:00"), "scheduled_for": "2026-10-05T12:00:00"}),
    ], missing={4}, age_days=2)
    make_job(out, JOB_B, "Joe Rogan Experience #2553 - Andrew Huberman-001", [
        short("Why the Law Ignores Brain Tumors When Judging Guilt", None, 87,
              published={"via": "upload-post", "at": ts("2026-09-28T20:00:00"), "scheduled_for": "2026-09-29T08:00:00"}),
        short("The Mass Shooter's Diary Asked Doctors to Study His Brain", None, 90),
        short("He Watched His Friend Do Brain Surgery", None, 78),
    ], age_days=6)
    make_job(out, JOB_C, "Lex Fridman Podcast #400 - Elon Musk-001", [
        short("How do rockets land on their tail", "science_other", 70),
        short("Does sleep make you smarter?", "self_improvement", 88),
    ], keep=True, age_days=10)
    hidden = out / "_lineup"
    hidden.mkdir()
    (hidden / "x_metadata.json").write_text(json.dumps({"shorts": [short("hidden")]}), encoding="utf-8")
    schedule = [
        entry(JOB_A, 0, "youtube", "2026-10-05", "07:46", posted=True),
        entry(JOB_A, 1, "youtube", "2026-10-07", "12:00"),
        *[entry(JOB_A, 5, p, "2026-10-05", "12:00") for p in ("tiktok", "youtube", "instagram")],
        entry(JOB_B, 2, "youtube", "2026-10-02", "08:00"),             # put back by hand: no stamp
        entry(JOB_C, 0, "youtube", "2026-10-05", "20:00", auto=False),  # the manual checklist
        entry(GONE, 0, "youtube", "2026-10-06", "08:00", title="Is this clip gone? #jre"),
    ]
    return out, schedule


def view(world, **kw):
    out, schedule = world
    kw.setdefault("stats_dir", str(out.parent / "stats"))
    return lineup.build(str(out), schedule, retention_seconds=RETENTION, tz="UTC", clock=NOW, **kw)


def by_ref(v):
    return {c["ref"]: c for c in v["clips"]}


# --- names, forms ---------------------------------------------------------------------------------------------

class TestNames:
    def test_episode_from_the_source_name(self):
        info = lineup.episode_info(f"{JOB_A}_Joe Rogan Experience #2553 - Andrew Huberman-004.mkv", JOB_A)
        assert info == {"show": "Joe Rogan Experience", "episode": "#2553", "guest": "Andrew Huberman",
                        "episode_key": "jre-2553"}
        assert lineup.episode_info("Joe Rogan Experience #2553 - Andrew Huberman-001.mkv")["episode_key"] == \
            "jre-2553", "two pieces of one source are one episode"
        lex = lineup.episode_info("Lex Fridman Podcast #400 – Elon Musk.mp4")
        assert (lex["show"], lex["episode"], lex["guest"], lex["episode_key"]) == \
            ("Lex Fridman Podcast", "#400", "Elon Musk", "lfp-400")

    def test_no_number_and_no_name(self):
        info = lineup.episode_info("Huberman Lab: Dr. Andy Galpin.mp4")
        assert info["show"] == "Huberman Lab" and info["episode"] is None
        assert info["episode_key"] == "huberman-lab-dr-andy-galpin"
        assert lineup.episode_info("", "abcdef12-x")["episode_key"] == "job-abcdef12"

    def test_title_forms(self):
        assert lineup.title_form("Is your ER doctor as impaired as a drunk?") == "question"
        assert lineup.title_form("Do medical errors kill 251,000 a year? #jre") == "question"
        assert lineup.title_form("Why do surgeons hate whole-body scans?") == "why"
        assert lineup.title_form("How Competing With Alex Honnold Broke Dean Potter") == "how"
        assert lineup.title_form("The Truth Behind 'Meth Strength'") == "statement"
        assert lineup.title_form("Healing PTSD in Just 6 Weeks?") == "question"
        assert lineup.title_form("") is None


# --- the catalogue --------------------------------------------------------------------------------------------

class TestCatalog:
    def test_every_rendered_clip_published_included(self, world):
        v = view(world)
        refs = by_ref(v)
        assert len(v["clips"]) == 10, "A's clip 5 has no file; _lineup is no job"
        assert "aaaaaaaa_c05" not in refs and all(not r.startswith("_") for r in refs)
        assert all(C2_CLIP_KEYS <= set(c) for c in v["clips"])
        assert not any(k.startswith("_") for c in v["clips"] for k in c)
        a1 = refs["aaaaaaaa_c01"]
        assert a1["video_url"].startswith(f"/videos/{JOB_A}/subtitled_") and a1["video_url"].endswith("_clip_1.mp4")
        assert a1["thumb_url"] == f"/api/lineup/thumb/{JOB_A}/0"
        assert (a1["hook"], a1["duration"], a1["ai_score"], a1["moment_nature"]) == \
            ("3 a.m. ER? Ask this first.", 30.5, 78, "threat_to_you")
        assert (a1["niche"], a1["niche_guess"], a1["upload_profile"]) == ("Joe Rogan podcast", "podcast", "default")
        assert (a1["show"], a1["episode"], a1["guest"], a1["episode_key"]) == \
            ("Joe Rogan Experience", "#2553", "Andrew Huberman", "jre-2553")
        assert refs["bbbbbbbb_c01"]["episode_key"] == "jre-2553"
        assert refs["cccccccc_c01"]["title_form"] == "how" and refs["cccccccc_c02"]["title_form"] == "question"

    def test_categories_ai_manual_other(self, world):
        refs = by_ref(view(world))
        assert (refs["aaaaaaaa_c01"]["category"], refs["aaaaaaaa_c01"]["category_label"],
                refs["aaaaaaaa_c01"]["category_source"]) == ("medical_mystery", "Medicine", "ai")
        manual = refs["aaaaaaaa_c04"]
        assert (manual["category"], manual["category_label"], manual["category_source"], manual["ai_category"]) == \
            ("mind_psychology", "Psychology", "manual", "substances")
        assert (refs["bbbbbbbb_c02"]["category"], refs["bbbbbbbb_c02"]["category_label"]) == ("other", "Other")
        cats = {c["id"]: c for c in view(world)["categories"]}
        assert set(cats) == set(lineup.playbook.TOPIC_BUCKETS), "every bucket, for the correction menu"
        assert (cats["medical_mystery"]["count"], cats["other"]["count"], cats["science_other"]["count"],
                cats["brain_danger"]["count"]) == (3, 3, 2, 0)

    def test_states_from_the_plan_and_the_stamp(self, world):
        refs = by_ref(view(world))
        state = {r: c["status"] for r, c in refs.items()}
        assert state == {
            "aaaaaaaa_c01": "published",   # posted now, 07:46
            "aaaaaaaa_c02": "scheduled",   # Upload-Post, Wed 12:00
            "aaaaaaaa_c03": "available", "aaaaaaaa_c04": "available",
            "aaaaaaaa_c06": "published",   # Upload-Post, today 12:00: passed at 14:00
            "bbbbbbbb_c01": "published",   # its stamp only (no plan entry)
            "bbbbbbbb_c02": "available", "bbbbbbbb_c03": "available",   # c03: put back by hand
            "cccccccc_c01": "scheduled",   # manual checklist, not ticked
            "cccccccc_c02": "available",
        }
        assert refs["aaaaaaaa_c01"]["published_at"] == "2026-10-05T07:46:00"
        assert refs["aaaaaaaa_c06"]["slots"] == [{"date": "2026-10-05", "time": "12:00",
                                                  "platforms": ["instagram", "tiktok", "youtube"],
                                                  "status": "published"}], "one slot, its platforms grouped"
        assert refs["aaaaaaaa_c02"]["published_at"] is None
        assert refs["bbbbbbbb_c01"]["published_at"] == "2026-09-29T08:00:00"
        assert refs["bbbbbbbb_c03"]["slots"][0]["date"] == "2026-10-02", "its old slot kept for the record"
        assert refs["aaaaaaaa_c03"]["slots"] == [] and refs["aaaaaaaa_c03"]["published_at"] is None

    def test_expiry_and_keep(self, world):
        refs = by_ref(view(world))
        assert (refs["aaaaaaaa_c01"]["expires_in_days"], refs["aaaaaaaa_c01"]["kept"]) == (6.0, False)
        assert refs["bbbbbbbb_c01"]["expires_in_days"] == 2.0
        assert (refs["cccccccc_c01"]["expires_in_days"], refs["cccccccc_c01"]["kept"]) == (None, True)
        out, schedule = world
        no_clock = lineup.build(str(out), schedule, retention_seconds=None, tz="UTC", clock=NOW)
        assert by_ref(no_clock)["aaaaaaaa_c01"]["expires_in_days"] is None

    def test_nulls_never_guesses(self, world):
        v = view(world)
        assert all(c["stats"] is None and c["jury"] is None for c in v["clips"])
        assert v["stats_export"] is None and v["jury_calibration"] is None
        assert by_ref(v)["bbbbbbbb_c01"]["moment_nature"] is None
        assert v["jury_run"]["running"] is False

    def test_real_numbers_from_the_studio_export(self, world):
        out, _ = world
        stats = out.parent / "stats"
        stats.mkdir()
        (stats / "studio_20261005.csv").write_text(
            "Content,Video title,Video publish time,Duration,Views,Stayed to watch (%)\n"
            'Total,,,,"1,495",50.0\n'
            'abcdefghijk,"Is your ER doctor as impaired as a drunk?","Oct 5, 2026",31,495,35.2\n'
            'bcdefghijkl,"Something we never made","Oct 1, 2026",40,"1,000",64.8\n', encoding="utf-8")
        v = view(world)
        a1 = by_ref(v)["aaaaaaaa_c01"]
        assert a1["stats"]["stayed"] == 35.2 and a1["stats"]["views"] == 495 and a1["stats"]["as_of"]
        assert by_ref(v)["aaaaaaaa_c02"]["stats"] is None
        assert v["stats_export"]["file"] == "studio_20261005.csv" and v["stats_export"]["linked"] == 1

    def test_the_week(self, world):
        w = view(world)["week"]
        assert (w["from"], w["to"]) == ("2026-10-05", "2026-10-11")
        assert [(t["date"], t["time"], t["ref"], t["status"]) for t in w["timeline"]] == [
            ("2026-10-05", "07:46", "aaaaaaaa_c01", "published"),
            ("2026-10-05", "12:00", "aaaaaaaa_c06", "published"),
            ("2026-10-05", "20:00", "cccccccc_c01", "scheduled"),
            ("2026-10-06", "08:00", "dddddddd_c01", "scheduled"),
            ("2026-10-07", "12:00", "aaaaaaaa_c02", "scheduled"),
        ]
        gone = w["timeline"][3]
        assert gone["on_disk"] is False and gone["title"].startswith("Is this clip gone?")
        assert w["mix"] == {"category": {"medical_mystery": 2, "science_other": 2},
                            "episode": {"jre-2553": 3, "lfp-400": 1},
                            "title_form": {"question": 4, "how": 1}}
        assert w["episodes"] == {"jre-2553": "Joe Rogan Experience #2553", "lfp-400": "Lex Fridman Podcast #400"}
        assert [(a["kind"], a["refs"], a["date"]) for a in w["alerts"]] == [
            ("same_category_in_a_row", ["aaaaaaaa_c06", "cccccccc_c01"], "2026-10-05")]
        assert "2 Science clips in a row" in w["alerts"][0]["message"]

    def test_the_time_zone_moves_today(self, world):
        out, schedule = world
        late = datetime(2026, 10, 5, 23, 30, tzinfo=timezone.utc).timestamp()
        paris = lineup.build(str(out), schedule, tz="Europe/Paris", clock=late)
        assert paris["now"] == "2026-10-06T01:30:00" and paris["week"]["from"] == "2026-10-06"
        assert paris["timezone"] == "Europe/Paris"
        assert lineup.build(str(out), schedule, tz="Not/AZone", clock=late)["timezone"] == lineup.DEFAULT_TZ


# --- the category, by hand ------------------------------------------------------------------------------------

class TestCategory:
    def test_written_with_the_mtimes_kept(self, world):
        out, _ = world
        job = out / JOB_A
        meta = next(job.glob("*_metadata.json"))
        os.utime(meta, (1_000_000_000, 1_000_000_000))
        os.utime(job, (1_100_000_000, 1_100_000_000))
        assert lineup.set_category(str(out), JOB_A, 2, "brain_danger") == "brain_danger"
        assert json.loads(meta.read_text(encoding="utf-8"))["shorts"][2]["category_manual"] == "brain_danger"
        assert os.stat(meta).st_mtime == 1_000_000_000, "the project's date"
        assert os.stat(job).st_mtime == 1_100_000_000, "the folder's age, what the purge reads"
        c = by_ref(view(world))["aaaaaaaa_c03"]
        assert (c["category"], c["category_source"], c["ai_category"]) == ("brain_danger", "manual", "medical_mystery")
        assert lineup.set_category(str(out), JOB_A, 2, None) is None
        assert "category_manual" not in json.loads(meta.read_text(encoding="utf-8"))["shorts"][2]
        assert os.stat(meta).st_mtime == 1_000_000_000
        assert by_ref(view(world))["aaaaaaaa_c03"]["category_source"] == "ai"

    def test_a_refused_utime_still_saves(self, world, monkeypatch):
        out, _ = world

        def refuse(*a, **k):
            raise PermissionError(1, "Operation not permitted")
        monkeypatch.setattr(os, "utime", refuse)
        lineup.set_category(str(out), JOB_A, 0, "crime_dark")
        meta = next((out / JOB_A).glob("*_metadata.json"))
        assert json.loads(meta.read_text(encoding="utf-8"))["shorts"][0]["category_manual"] == "crime_dark"

    @pytest.mark.parametrize("job, index, category, status", [
        (JOB_A, 0, "not_a_bucket", 400), ("../etc", 0, "other", 400), ("_lineup", 0, "other", 400),
        ("eeeeeeee-0000-4000-8000-000000000009", 0, "other", 404), (JOB_A, 99, "other", 404),
        (JOB_A, -1, "other", 404)])
    def test_refused(self, world, job, index, category, status):
        out, _ = world
        with pytest.raises(lineup.LineupError) as e:
            lineup.set_category(str(out), job, index, category)
        assert e.value.status == status


# --- the rules ------------------------------------------------------------------------------------------------

def it(ref, day, hhmm, cat="other", ep="jre-2553", form="statement"):
    return {"ref": ref, "date": day, "time": hhmm, "status": "scheduled", "category": cat,
            "category_label": lineup.category_label(cat), "episode_key": ep,
            "episode_label": "Joe Rogan Experience #2553" if ep == "jre-2553" else ep, "title_form": form}


def kinds(alerts):
    return [a["kind"] for a in alerts]


class TestRules:
    def test_same_category_in_a_row(self):
        alerts, pen = lineup.evaluate([it("a", "2026-10-06", "08:00", "medical_mystery", ep="x"),
                                       it("b", "2026-10-06", "12:00", "medical_mystery", ep="y")])
        assert kinds(alerts) == ["same_category_in_a_row"] and alerts[0]["refs"] == ["a", "b"] and pen == 1
        assert alerts[0]["date"] == "2026-10-06" and alerts[0]["message"].startswith("2 Medicine clips in a row")
        alerts, _ = lineup.evaluate([it("a", "2026-10-06", "08:00", "medical_mystery", ep="x"),
                                     it("b", "2026-10-06", "12:00", "substances", ep="y"),
                                     it("c", "2026-10-06", "20:00", "medical_mystery", ep="z")])
        assert alerts == []
        run3 = [it(r, "2026-10-07", t, "medical_mystery", ep=r) for r, t in (("a", "08:00"), ("b", "12:00"),
                                                                              ("c", "20:00"))]
        alerts, pen = lineup.evaluate(list(reversed(run3)))
        assert len(alerts) == 1 and alerts[0]["refs"] == ["a", "b", "c"] and pen == 2, "one run, any input order"

    def test_other_is_no_topic_and_the_post_before_counts(self):
        alerts, _ = lineup.evaluate([it("a", "2026-10-06", "08:00", ep="x"), it("b", "2026-10-06", "12:00", ep="y")])
        assert alerts == [], "two unsorted clips say nothing"
        prev = it("p", "2026-10-04", "20:00", "crime_dark", ep="p")
        alerts, _ = lineup.evaluate([it("a", "2026-10-05", "08:00", "crime_dark", ep="x")], prev)
        assert kinds(alerts) == ["same_category_in_a_row"] and alerts[0]["refs"] == ["p", "a"]
        assert alerts[0]["date"] == "2026-10-05"

    def test_episode_per_day(self):
        two = [it("a", "2026-10-06", "08:00"), it("b", "2026-10-06", "12:00"), it("c", "2026-10-07", "08:00")]
        assert lineup.evaluate(two)[0] == []
        alerts, pen = lineup.evaluate(two + [it("d", "2026-10-06", "20:00")])
        assert kinds(alerts) == ["episode_per_day"] and alerts[0]["refs"] == ["a", "b", "d"] and pen == 1
        assert alerts[0]["message"] == "3 clips from Joe Rogan Experience #2553 on Tue 6 Oct: 2 a day at most."

    def test_shares_start_at_six(self):
        five = [it(f"m{k}", f"2026-10-0{5 + k}", "12:00", "medical_mystery" if k < 3 else "other", ep=f"e{k}")
                for k in range(5)]
        assert "category_share" not in kinds(lineup.evaluate(five)[0])
        six = five + [it("s", "2026-10-11", "12:00", "substances", ep="e9")]
        alerts, _ = lineup.evaluate(six)
        share = next(a for a in alerts if a["kind"] == "category_share")
        assert share["refs"] == ["m0", "m1", "m2"] and share["date"] is None
        assert share["message"] == "Medicine is 3 of 6 clips this week (50%): keep one topic under 35%."

    def test_share_limits(self):
        def week(n_cat, n_ep, n_q, n=12):
            # Medicine on every other post (never twice in a row), two posts a day.
            return [it(f"r{k:02d}", f"2026-10-{5 + k // 2:02d}", "08:00" if k % 2 == 0 else "20:00",
                       "medical_mystery" if k % 2 == 0 and k < 2 * n_cat else "other",
                       ep="jre-2553" if k < n_ep else f"e{k}", form="question" if k < n_q else "statement")
                    for k in range(n)]
        assert lineup.evaluate(week(4, 6, 7))[0] == [], "4/12 = 33 %, 6/12 = 50 %, 7/12 = 58 %: all fine"
        alerts, pen = lineup.evaluate(week(5, 7, 8))
        assert sorted(kinds(alerts)) == ["category_share", "episode_share", "title_form_share"]
        assert pen == 3, "one post over each limit"
        assert kinds(lineup.evaluate(week(1, 1, 7, n=10))[0]) == ["title_form_share"], "7/10 = 70 %"
        assert lineup.evaluate(week(1, 1, 7, n=10), total=12)[0] == [], "7 of the plan's final 12 = 58 %"

    def test_why_and_how_titles_ask_too(self):
        items = [it(f"r{k}", f"2026-10-{5 + k:02d}", "12:00", ep=f"e{k}", form=f)
                 for k, f in enumerate(("question", "why", "how", "question", "statement", "why"))]
        alerts, _ = lineup.evaluate(items)
        assert kinds(alerts) == ["title_form_share"] and len(alerts[0]["refs"]) == 5

    def test_the_week_of_5_october(self):
        """12 clips of one episode in 4 days, 3 a day, 6 Medicine, 12 questions: every rule speaks."""
        cats = ["medical_mystery", "substances", "science_other", "medical_mystery", "medical_mystery", "substances",
                "mind_psychology", "medical_mystery", "medical_mystery", "mind_psychology", "mind_psychology",
                "medical_mystery"]
        items = [it(f"b8e46c24_c{k + 1:02d}", f"2026-10-0{5 + k // 3}", ("08:00", "12:00", "20:00")[k % 3], c,
                    form="question") for k, c in enumerate(cats)]
        alerts, _ = lineup.evaluate(items)
        assert set(kinds(alerts)) == {"same_category_in_a_row", "episode_per_day", "category_share", "episode_share",
                                      "title_form_share"}
        assert sum(a["kind"] == "episode_per_day" for a in alerts) == 4
        assert "12 of 12 clips this week come from Joe Rogan Experience #2553 (100%)" in \
            next(a["message"] for a in alerts if a["kind"] == "episode_share")

    def test_rules_are_exposed(self, world):
        rules = view(world)["rules"]
        assert rules["category_share"]["max"] == lineup.MAX_CATEGORY_SHARE == 0.35
        assert rules["episode_per_day"]["max"] == 2 and rules["episode_share"]["max"] == 0.5
        assert rules["title_form_share"]["max"] == 0.6 and rules["category_share"]["min_clips"] == 6
        assert rules["advisory"] is True and all("why" in r for r in rules.values() if isinstance(r, dict))


# --- the plan -------------------------------------------------------------------------------------------------

@pytest.fixture
def small(tmp_path):
    """One Medicine post already Tuesday 08:00 (Huberman Lab #3); X: Medicine 90 (JRE #1), Y: Psychology 80
    (Lex #2), Z: Medicine 60 (JRE #1)."""
    out = tmp_path / "output"
    make_job(out, JOB_A, "Huberman Lab #3 - Guest", [
        short("Is it in your blood?", "medical_mystery", 70,
              published={"via": "upload-post", "at": NOW - DAY, "scheduled_for": "2026-10-06T08:00:00"})])
    make_job(out, JOB_B, "Joe Rogan Experience #1 - Someone", [
        short("Can a scan kill you?", "medical_mystery", 90), short("A doctor's mistake", "medical_mystery", 60)])
    make_job(out, JOB_C, "Lex Fridman Podcast #2 - Other", [short("Why do we forget?", "mind_psychology", 80)])
    return out, [entry(JOB_A, 0, "youtube", "2026-10-06", "08:00")]


def run_plan(world, clips, slots=None):
    out, schedule = world
    return lineup.plan(str(out), schedule, clips, slots, tz="UTC", clock=NOW)


X, Y, Z = [JOB_B, 0], [JOB_C, 0], [JOB_B, 1]
TUE = [{"date": "2026-10-06", "time": "12:00"}, {"date": "2026-10-06", "time": "20:00"}]


class TestPlan:
    def test_best_that_keeps_the_mix(self, small):
        p = run_plan(small, [X, Y], TUE)
        assert [(s["time"], s["ref"]) for s in p["plan"]] == [("12:00", "cccccccc_c01"), ("20:00", "bbbbbbbb_c01")]
        assert p["plan"][0]["why"] == ("Best that keeps the mix (AI score 80); bbbbbbbb_c01 would put 2 Medicine "
                                       "clips in a row")
        assert p["plan"][1]["why"] == "Best AI score left (90)"
        assert p["plan"][0]["job_id"] == JOB_C and p["plan"][0]["clip_index"] == 0
        assert p["alerts"] == [] and p["left_out"] == []

    def test_deterministic(self, small):
        first = run_plan(small, [X, Y, Z], TUE)
        assert run_plan(small, [Z, Y, X], list(reversed(TUE))) == first
        assert first["left_out"] == ["bbbbbbbb_c02"] and first["left_out_why"] == {"bbbbbbbb_c02": "no slot left"}

    @pytest.mark.parametrize("on", [True, False])
    def test_the_jury_score_comes_first_only_when_the_jury_is_on(self, small, monkeypatch, on):
        monkeypatch.setattr(lineup, "JURY_ENABLED", on)
        fake = types.ModuleType("hook_jury")
        fake.load_result = lambda o, j, i: {"score": 40} if j == JOB_B and i == 0 else (
            {"score": 70} if j == JOB_B and i == 1 else None)
        fake.load_calibration = lambda o: None
        monkeypatch.setitem(sys.modules, "hook_jury", fake)
        p = run_plan(small, [X, Z], [{"date": "2026-10-07", "time": "12:00"}])
        # Both are Medicine right after Tuesday's Medicine post: the clash is the same, the rank decides.
        if on:
            assert p["plan"][0]["ref"] == "bbbbbbbb_c02"
            assert p["plan"][0]["why"].startswith("Best jury score left (70), though it would put 2 Medicine")
        else:
            assert p["plan"][0]["ref"] == "bbbbbbbb_c01"
            assert p["plan"][0]["why"].startswith("Best AI score left (90), though it would put 2 Medicine")

    def test_the_real_stayed_comes_before_the_jury(self, small, monkeypatch):
        out, schedule = small
        stats = out.parent / "stats"
        stats.mkdir()
        (stats / "studio.csv").write_text(
            "Content,Video title,Video publish time,Duration,Views,Stayed to watch (%)\n"
            'abcdefghijk,"A doctor\'s mistake","Oct 1, 2026",30,900,71.5\n', encoding="utf-8")
        fake = types.ModuleType("hook_jury")
        fake.load_result = lambda o, j, i: {"score": 80} if (j, i) == (JOB_B, 0) else None
        fake.load_calibration = lambda o: None
        monkeypatch.setitem(sys.modules, "hook_jury", fake)
        v = lineup.build(str(out), schedule, stats_dir=str(stats), tz="UTC", clock=NOW)
        src = {c["ref"]: (c["rank_score"], c["rank_score_source"]) for c in v["clips"]}
        assert src == {"aaaaaaaa_c01": (70, "ai"), "bbbbbbbb_c01": (80, "jury"), "bbbbbbbb_c02": (71.5, "stayed"),
                       "cccccccc_c01": (80, "ai")}
        assert v["rules"]["ranking"]["by"] == ["stayed", "jury", "ai"]

    def test_a_slot_where_everything_clashes_is_left_free(self, small):
        out, schedule = small
        schedule = schedule + [entry(JOB_A, 0, "youtube", "2026-10-07", "08:00", auto=False),
                               entry(JOB_A, 0, "youtube", "2026-10-07", "12:00", auto=False)]
        p = lineup.plan(str(out), schedule, [Y], [{"date": "2026-10-07", "time": "20:00"},
                                                  {"date": "2026-10-08", "time": "08:00"}], tz="UTC", clock=NOW)
        assert p["plan"] == [{"date": "2026-10-08", "time": "08:00", "job_id": JOB_C, "clip_index": 0,
                              "ref": "cccccccc_c01", "why": "Best AI score left (80)"}] or p["plan"][0]["date"] == \
            "2026-10-07", "Y is from another episode: nothing to skip"
        # Two Huberman Lab posts on Wednesday: a third clip of that episode goes to Thursday instead.
        make_job(out, "eeeeeeee-0000-4000-8000-000000000005", "Huberman Lab #3 - Guest", [
            short("Should you fast?", "self_improvement", 95)])
        p = lineup.plan(str(out), schedule, [["eeeeeeee-0000-4000-8000-000000000005", 0]],
                        [{"date": "2026-10-07", "time": "20:00"}, {"date": "2026-10-08", "time": "08:00"}],
                        tz="UTC", clock=NOW)
        assert [(s["date"], s["time"]) for s in p["plan"]] == [("2026-10-08", "08:00")]
        assert p["skipped_slots"] == [{"date": "2026-10-07", "time": "20:00",
                                       "why": "left free: every clip left would clash here"}]

    def test_least_clash_when_nothing_fits(self, small):
        out, schedule = small
        p = lineup.plan(str(out), schedule, [X], [{"date": "2026-10-06", "time": "12:00"}], tz="UTC", clock=NOW)
        assert p["plan"][0]["ref"] == "bbbbbbbb_c01"
        assert p["plan"][0]["why"] == "Best AI score left (90), though it would put 2 Medicine clips in a row"
        assert kinds(p["alerts"]) == ["same_category_in_a_row"]

    def test_left_out_and_skipped(self, world):
        p = run_plan(world, [[JOB_A, 0], [JOB_A, 1], [JOB_A, 4], [GONE, 0], "junk", [JOB_A, 2]],
                     [{"date": "2026-10-05", "time": "12:00"}, {"date": "2026-10-05", "time": "20:00"},
                      {"date": "2026-10-06", "time": "08:00"}, {"date": "nope", "time": "8"},
                      {"date": "2026-10-09", "time": "12:00"}])
        assert p["left_out_why"] == {"aaaaaaaa_c01": "already published", "aaaaaaaa_c02": "already scheduled",
                                     "aaaaaaaa_c05": "not on disk", "dddddddd_c01": "not on disk"}
        assert [(s["date"], s["time"], s["why"]) for s in p["skipped_slots"]] == [
            ("2026-10-05", "12:00", "already passed"), ("2026-10-05", "20:00", "already taken"),
            ("2026-10-06", "08:00", "already taken"), ("nope", "8", "not a date and time")]
        assert [(s["date"], s["ref"]) for s in p["plan"]] == [("2026-10-09", "aaaaaaaa_c03")]

    def test_no_slots_given_takes_the_weeks_free_times(self, world):
        p = run_plan(world, [[JOB_A, 2], [JOB_C, 1]])
        assert [(s["date"], s["time"]) for s in p["plan"]] == [("2026-10-06", "12:00"), ("2026-10-06", "20:00")]

    def test_publishes_nothing(self, world):
        out, schedule = world
        before = json.dumps(schedule, sort_keys=True)
        files = sorted(str(p) + str(p.stat().st_mtime) for p in out.rglob("*") if p.is_file())
        run_plan(world, [[JOB_A, 2], [JOB_C, 1], [JOB_B, 1]])
        assert json.dumps(schedule, sort_keys=True) == before
        assert sorted(str(p) + str(p.stat().st_mtime) for p in out.rglob("*") if p.is_file()) == files


# --- the jury, mocked -----------------------------------------------------------------------------------------

def fake_jury(results=None, gate=None, raise_in_run=None):
    mod = types.ModuleType("hook_jury")
    results = results or {}
    mod.load_result = lambda o, j, i: results.get((j, i))
    mod.load_calibration = lambda o: {"version": "jury-v1", "n": 12, "spearman": 0.61, "reading": "moderate"}
    mod.calls = []

    def run_many(output_dir, clips, progress=None, force=False):
        mod.calls.append((output_dir, list(clips), force))
        if gate is not None:
            gate.wait(5)
        if raise_in_run:
            raise raise_in_run
        out = []
        for k, (j, i) in enumerate(clips):
            ref = lineup.clip_ref(j, i)
            out.append({"ref": ref, "error": "ffmpeg failed"} if k == 1 else {"ref": ref, "score": 60})
            if progress:
                progress(k + 1, len(clips), ref)
        return out

    mod.run_many = run_many
    mod.clip_video_path = lambda o, j, i: None
    return mod


class TestJuryOff:
    """The switch off: kept for when the jury must be stopped again."""

    def test_nothing_is_read_nor_run(self, world, monkeypatch, jury_off):
        out, _ = world
        mod = types.ModuleType("hook_jury")

        def boom(*a, **k):
            raise AssertionError("the jury is off: hook_jury must not be called")
        mod.load_result = mod.load_calibration = mod.run_many = mod.run_one = mod.clip_video_path = boom
        monkeypatch.setitem(sys.modules, "hook_jury", mod)
        assert lineup.JURY_ENABLED is False and lineup.jury_module() is None
        v = view(world)
        assert v["jury_enabled"] is False and v["jury_calibration"] is None
        assert all(c["jury"] is None for c in v["clips"])
        assert {c["rank_score_source"] for c in v["clips"]} == {"ai"}
        assert v["rules"]["ranking"]["by"] == ["stayed", "ai"] and v["rules"]["jury_enabled"] is False
        state = lineup.start_jury(str(out), [(JOB_A, 0)])
        assert state["disabled"] is True and state["running"] is False and state["total"] == 0
        assert v["jury_run"]["disabled"] is True


class TestJury:
    def test_on_says_so(self, world):
        v = view(world)
        assert v["jury_enabled"] is True and v["rules"]["ranking"]["by"] == ["stayed", "jury", "ai"]
        assert v["jury_run"]["disabled"] is False

    def test_results_and_calibration_pass_through(self, world, monkeypatch):
        result = {"job_id": JOB_A, "clip_index": 0, "ref": "aaaaaaaa_c01", "score": 72, "votes": [70, 72, 75],
                  "stop": "yes", "rank_check": {"wins": 3, "games": 4, "rank_score": 0.75}}
        monkeypatch.setitem(sys.modules, "hook_jury", fake_jury({(JOB_A, 0): result}))
        v = view(world)
        assert by_ref(v)["aaaaaaaa_c01"]["jury"] == result, "passed as it is, added fields included"
        assert (by_ref(v)["aaaaaaaa_c01"]["rank_score"], by_ref(v)["aaaaaaaa_c01"]["rank_score_source"]) == \
            (72, "jury")
        assert by_ref(v)["aaaaaaaa_c02"]["jury"] is None and by_ref(v)["aaaaaaaa_c02"]["rank_score_source"] == "ai"
        assert v["jury_calibration"]["spearman"] == 0.61

    def test_to_judge(self, world, monkeypatch):
        out, _ = world
        monkeypatch.setitem(sys.modules, "hook_jury", fake_jury({(JOB_A, 0): {"score": 50}}))
        todo = lineup.clips_to_judge(str(out))
        assert len(todo) == 9 and (JOB_A, 0) not in todo and (JOB_A, 4) not in todo, "published ones too"

    def test_one_run_at_a_time_in_the_background(self, world, monkeypatch):
        out, _ = world
        gate = threading.Event()
        mod = fake_jury(gate=gate)
        monkeypatch.setitem(sys.modules, "hook_jury", mod)
        state = lineup.start_jury(str(out), [(JOB_A, 0), (JOB_A, 1), (JOB_C, 1)])
        assert state["running"] is True and state["total"] == 3 and state["done"] == 0
        again = lineup.start_jury(str(out), [(JOB_A, 2)])
        assert again["already_running"] is True and again["total"] == 3
        gate.set()
        assert lineup.wait_jury(5)
        state = lineup.jury_state()
        assert (state["running"], state["done"], state["total"], state["current"]) == (False, 3, 3, None)
        assert state["errors"] == ["aaaaaaaa_c02: ffmpeg failed"] and state["finished_at"]
        assert mod.calls == [(str(out), [(JOB_A, 0), (JOB_A, 1), (JOB_C, 1)], False)]

    def test_a_note_is_never_asked_twice(self, world, monkeypatch):
        """The user's rule: one note per rendered mp4, ``force`` or not."""
        out, _ = world
        mod = fake_jury({(JOB_A, 0): {"score": 50}})
        monkeypatch.setitem(sys.modules, "hook_jury", mod)
        state = lineup.start_jury(str(out), [(JOB_A, 0), (JOB_A, 1), (JOB_A, 1)], force=True)
        assert state["total"] == 1 and state["already_judged"] == 1
        assert lineup.wait_jury(5)
        assert mod.calls == [(str(out), [(JOB_A, 1)], False)]
        mod.calls.clear()
        state = lineup.start_jury(str(out), [(JOB_A, 0)], force=True)
        assert (state["running"], state["total"], state["already_judged"]) == (False, 0, 1)
        assert lineup.wait_jury(5) and mod.calls == [], "nothing to judge: nothing runs"

    def test_a_crash_is_reported_not_raised(self, world, monkeypatch):
        out, _ = world
        monkeypatch.setitem(sys.modules, "hook_jury", fake_jury(raise_in_run=RuntimeError("no key")))
        lineup.start_jury(str(out), [(JOB_A, 0)])
        assert lineup.wait_jury(5)
        state = lineup.jury_state()
        assert state["running"] is False and state["errors"] == ["RuntimeError: no key"]

    def test_without_the_jury_module(self, world):
        out, _ = world
        with pytest.raises(lineup.LineupError) as e:
            lineup.start_jury(str(out), [(JOB_A, 0)])
        assert e.value.status == 503


# --- the thumbnail --------------------------------------------------------------------------------------------

class TestThumbnail:
    @pytest.mark.parametrize("job, index", [
        ("../etc", 0), ("..", 0), (".", 0), ("_lineup", 0), (".keep", 0), ("a/b", 0), ("a\\b", 0), ("", 0),
        ("x" * 80, 0), (JOB_A, -1), (JOB_A, 10_000), ("..%2F..%2Fetc", 0), (None, 0), (JOB_A, "0")])
    def test_hostile_ids_are_refused(self, world, job, index):
        out, _ = world
        with pytest.raises(lineup.LineupError):
            lineup.thumbnail(str(out), job, index)

    def test_nothing_outside_the_job(self, world, tmp_path):
        out, _ = world
        secret = tmp_path / "secret"
        secret.mkdir()
        (secret / "x_metadata.json").write_text(json.dumps({"shorts": [short("s", video_url="/videos/s/a.mp4")]}))
        (secret / "a.mp4").write_bytes(b"\x00")
        os.symlink(secret, out / "ffffffff-0000-4000-8000-000000000006")
        assert lineup.thumbnail(str(out), "ffffffff-0000-4000-8000-000000000006", 0) is None
        # A clip file that is a link out of its job folder is not read either.
        job = out / JOB_C
        target = next(job.glob("subtitled_*_clip_1.mp4"))
        target.unlink()
        os.symlink(secret / "a.mp4", target)
        assert lineup.thumbnail(str(out), JOB_C, 0) is None
        assert lineup.thumbnail(str(out), JOB_A, 4) is None, "its file is gone"
        assert lineup.thumbnail(str(out), "eeeeeeee-0000-4000-8000-000000000009", 0) is None

    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
    def test_a_still_at_one_and_a_half_seconds_cached(self, world, monkeypatch):
        out, _ = world
        mp4 = next((out / JOB_C).glob("subtitled_*_clip_2.mp4"))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc=duration=2:size=320x240:rate=10", "-pix_fmt", "yuv420p", str(mp4)], check=True)
        path = lineup.thumbnail(str(out), JOB_C, 1)
        assert path and path.startswith(str(out / "_lineup" / "thumbs"))
        with open(path, "rb") as f:
            assert f.read(2) == b"\xff\xd8"

        def no_ffmpeg(*a, **k):
            raise AssertionError("cached: ffmpeg is not run again")
        monkeypatch.setattr(lineup.subprocess, "run", no_ffmpeg)
        assert lineup.thumbnail(str(out), JOB_C, 1) == path
        monkeypatch.undo()
        monkeypatch.setitem(sys.modules, "hook_jury", None)
        os.utime(mp4, (NOW, NOW))                     # re-rendered: a new still, the old one dropped
        fresh = lineup.thumbnail(str(out), JOB_C, 1)
        assert fresh != path and os.path.exists(fresh) and not os.path.exists(path)

    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
    def test_a_short_clip_gives_its_first_frame(self, world):
        out, _ = world
        mp4 = next((out / JOB_C).glob("subtitled_*_clip_2.mp4"))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc=duration=0.5:size=320x240:rate=10", "-pix_fmt", "yuv420p", str(mp4)], check=True)
        assert lineup.thumbnail(str(out), JOB_C, 1)

    def test_not_a_video(self, world):
        out, _ = world
        if shutil.which("ffmpeg") is None:
            pytest.skip("needs ffmpeg")
        assert lineup.thumbnail(str(out), JOB_C, 1) is None, "a 1-byte file: no picture, no crash"
        assert not list((out / "_lineup" / "thumbs").glob("*.jpg"))


# --- no AI, ever ----------------------------------------------------------------------------------------------

class TestNoAI:
    """The user's rule (5-oct-2026): a clip's tokens are spent once, in the generator. The board, the plan and the
    category correction read what it wrote; they never call Claude, Gemini, a local LLM nor anything else."""

    def test_no_ai_module_in_the_source(self):
        with open(lineup.__file__, encoding="utf-8") as f:
            src = f.read()
        for name in ("ai_brain", "llm_backend", "gemini", "genai", "anthropic", "openai", "ai_cache", "claude"):
            assert not [line for line in src.splitlines()
                        if line.lstrip().startswith(("import ", "from ")) and name in line.lower()], name

    def test_board_plan_and_category_with_every_ai_call_raising(self, world, monkeypatch):
        import inspect

        def boom(*a, **k):
            raise AssertionError("an AI / network / process call from the line-up")
        for name in ("ai_brain", "llm_backend"):
            mod = pytest.importorskip(name)
            for attr, obj in list(vars(mod).items()):
                if inspect.isfunction(obj) and obj.__module__ == mod.__name__:
                    monkeypatch.setattr(mod, attr, boom)
        httpx = pytest.importorskip("httpx")
        monkeypatch.setattr(httpx.Client, "send", boom)
        monkeypatch.setattr(httpx.AsyncClient, "send", boom)
        monkeypatch.setattr(subprocess, "run", boom)
        monkeypatch.setattr(subprocess, "Popen", boom)
        jury = fake_jury({(JOB_A, 0): {"score": 64}})          # the board reads the notes, never judges
        jury.run_many = jury.run_one = boom
        monkeypatch.setitem(sys.modules, "hook_jury", jury)
        out, schedule = world
        v = view(world)
        assert len(v["clips"]) == 10 and by_ref(v)["bbbbbbbb_c02"]["category"] == "other", "no topic: Other"
        p = run_plan(world, [[JOB_A, 2], [JOB_C, 1], [JOB_B, 1]])
        assert len(p["plan"]) == 3
        lineup.set_category(str(out), JOB_B, 1, "crime_dark")
        assert by_ref(view(world))["bbbbbbbb_c02"]["category"] == "crime_dark"


# --- the routes -----------------------------------------------------------------------------------------------

class TestRoutes:
    def _client(self, world, monkeypatch):
        app = pytest.importorskip("app")
        out, schedule = world
        plan_file = out.parent / "publish_schedule.json"
        plan_file.write_text(json.dumps({"entries": schedule}), encoding="utf-8")
        monkeypatch.setattr(app, "OUTPUT_DIR", str(out))
        monkeypatch.setattr(app, "PUBLISH_SCHEDULE_FILE", str(plan_file))
        monkeypatch.setattr(app, "STUDIO_STATS_DIR", str(out.parent / "stats"))
        monkeypatch.setattr(app, "JOB_RETENTION_SECONDS", RETENTION)
        from starlette.testclient import TestClient
        return app, TestClient(app.app), plan_file

    def test_the_board(self, world, monkeypatch):
        _app, client, _ = self._client(world, monkeypatch)
        r = client.get("/api/lineup?tz=UTC")
        assert r.status_code == 200
        data = r.json()
        assert {"now", "clips", "categories", "week", "rules", "jury_calibration", "jury_run"} <= set(data)
        assert {"from", "to", "timeline", "mix", "alerts"} <= set(data["week"])
        assert len(data["clips"]) == 10 and all(C2_CLIP_KEYS <= set(c) for c in data["clips"])
        assert client.get("/api/lineup/jury/status").json()["running"] is False

    def test_category_route_keeps_the_mtime_and_the_memory(self, world, monkeypatch):
        app, client, _ = self._client(world, monkeypatch)
        out, _ = world
        meta = next((out / JOB_A).glob("*_metadata.json"))
        os.utime(meta, (1_000_000_000, 1_000_000_000))
        monkeypatch.setitem(app.jobs, JOB_A, {"result": {"clips": [{}, {}, {}]}})
        r = client.post("/api/lineup/category", json={"job_id": JOB_A, "clip_index": 2, "category": "crime_dark"})
        assert r.status_code == 200
        assert (r.json()["ref"], r.json()["category"], r.json()["category_source"]) == \
            ("aaaaaaaa_c03", "crime_dark", "manual")
        assert app.jobs[JOB_A]["result"]["clips"][2]["category_manual"] == "crime_dark"
        assert os.stat(meta).st_mtime == 1_000_000_000
        r = client.post("/api/lineup/category", json={"job_id": JOB_A, "clip_index": 2, "category": None})
        assert r.json()["category"] == "medical_mystery" and "category_manual" not in app.jobs[JOB_A]["result"]["clips"][2]
        assert client.post("/api/lineup/category", json={"job_id": JOB_A, "clip_index": 2,
                                                         "category": "nope"}).status_code == 400
        assert client.post("/api/lineup/category", json={"job_id": "../x", "clip_index": 2,
                                                         "category": None}).status_code == 400

    def test_plan_route_publishes_nothing(self, world, monkeypatch):
        _app, client, plan_file = self._client(world, monkeypatch)
        before = plan_file.read_text(encoding="utf-8")
        r = client.post("/api/lineup/plan", json={"clips": [[JOB_A, 2], [JOB_C, 1]],
                                                  "slots": [{"date": "2099-01-01", "time": "12:00"}], "tz": "UTC"})
        assert r.status_code == 200 and set(r.json()) >= {"plan", "alerts", "left_out"}
        assert len(r.json()["plan"]) == 1 and r.json()["left_out"]
        assert plan_file.read_text(encoding="utf-8") == before
        assert client.post("/api/lineup/plan", json={"clips": [["../x", 0]]}).status_code == 400

    def test_jury_routes_off(self, world, monkeypatch, jury_off):
        _app, client, _ = self._client(world, monkeypatch)
        mod = fake_jury()
        monkeypatch.setitem(sys.modules, "hook_jury", mod)
        r = client.post("/api/lineup/jury", json={"clips": None, "force": True})
        assert r.status_code == 200 and r.json()["disabled"] is True and r.json()["running"] is False
        assert mod.calls == [] and client.get("/api/lineup/jury/status").json()["disabled"] is True
        assert client.get("/api/lineup?tz=UTC").json()["jury_enabled"] is False

    def test_jury_routes(self, world, monkeypatch):
        _app, client, _ = self._client(world, monkeypatch)
        assert client.post("/api/lineup/jury", json={"clips": None}).status_code == 503
        mod = fake_jury({(JOB_A, 0): {"score": 50}})
        monkeypatch.setitem(sys.modules, "hook_jury", mod)
        r = client.post("/api/lineup/jury", json={"clips": None})
        assert r.status_code == 200 and r.json()["total"] == 9
        assert lineup.wait_jury(5)
        assert client.get("/api/lineup/jury/status").json()["done"] == 9
        assert client.post("/api/lineup/jury", json={"clips": [["a/b", 0]]}).status_code in (400, 422)

    @pytest.mark.parametrize("path", ["/api/lineup/thumb/..%2F..%2Fetc/0", "/api/lineup/thumb/_lineup/0",
                                      f"/api/lineup/thumb/{JOB_A}/-1", f"/api/lineup/thumb/{JOB_A}/4",
                                      "/api/lineup/thumb/%2e%2e/0"])
    def test_thumb_route_refuses(self, world, monkeypatch, path):
        _app, client, _ = self._client(world, monkeypatch)
        assert client.get(path).status_code in (400, 404, 422)

    def test_off_on_a_billed_box(self, world, monkeypatch):
        app, client, _ = self._client(world, monkeypatch)
        monkeypatch.setattr(app, "BILLING_ENABLED", True)
        for method, path, body in (("get", "/api/lineup", None), ("get", "/api/lineup/jury/status", None),
                                   ("post", "/api/lineup/category", {"job_id": JOB_A, "clip_index": 0}),
                                   ("post", "/api/lineup/plan", {"clips": []}),
                                   ("post", "/api/lineup/jury", {"clips": None}),
                                   ("get", f"/api/lineup/thumb/{JOB_A}/0", None)):
            r = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
            assert r.status_code == 404, path
