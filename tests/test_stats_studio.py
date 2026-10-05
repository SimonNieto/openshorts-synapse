"""stats_ingest.py on a YouTube Studio export (decision 7, 5-oct-2026): French and English CSVs built from the
23 shorts read in Studio on 4-oct (output/_stepup/studio/studio.json), joined to clips laid out like the real
jobs (titles, lengths, publish plan), "Stayed to watch" first, the opening-image A/B test."""
import asyncio
import io
import json
import os
import zipfile

import pytest

import stats_ingest as si

# id, title, published, Studio length, views, stayed (%), average view duration, average % viewed, and the clip
# the analyst found by hand ("local", the reference the join must find again).
STUDIO = [
    ("CeWu-DMt838", "Can a brain tumor make you a killer?", "2026-09-28", "0:52", 7646, 77.8, "0:45", 86.9, None),
    ("8fwsjVBQuMk", "The Dangerous Truth About Kratom", "2026-09-25", "1:23", 3934, 73.2, "1:01", 74.5, None),
    ("AijB6kk2gq0", "Is This The Most Intense Psychedelic Treatment?", "2026-09-20", "0:56", 2973, 65.8, "0:41",
     73.9, None),
    ("gDPFFxA5yPw", "Why Frustration is Essential for Learning", "2026-09-24", "1:02", 2881, 59.0, "0:34", 56.1, None),
    ("DPYOXHh1wuQ", "How Competing With Alex Honnold Broke Dean Potter", "2026-10-01", "0:30", 2607, 63.4, "0:18",
     61.1, "e9e44926_c10"),
    ("iiTNieJon3I", "Why Drive Is Better Than Discipline", "2026-09-22", "1:00", 2225, 68.5, "0:33", 56.0, None),
    ("Z_NtUqHgYpo", "Why Jiu-Jitsu is Superior for Self-Defense", "2026-09-22", "1:19", 1994, 68.6, "0:47", 59.7,
     None),
    ("PVgpQpHe_Rw", "Is Schizophrenia Just a Brain That Leaks DMT? Huberman Explains", "2026-09-29", "0:58", 1770,
     68.4, "0:34", 59.6, "88a7e7c1_c02"),
    ("Ybb0zPGUoJM", "Why Meth and Adderall Hit Your Brain the Same Way", "2026-09-29", "0:51", 1751, 59.1, "0:33",
     65.4, "88a7e7c1_c03"),
    ("-4W-qjEkPyE", "The Secret to Blunting Daily Stress", "2026-09-25", "1:30", 1619, 61.0, "0:49", 55.4, None),
    ("AfYZc_rxCgU", "Why Frustration Is the First Gate of Learning (Neuroscience)", "2026-09-30", "0:59", 1458, 53.3,
     "0:23", 39.6, "82509f9b_c01"),
    ("JkGpxlvy5XA", "Why Edibles Are Suddenly Causing Psychosis", "2026-09-24", "1:26", 1430, 69.7, "0:46", 53.6,
     None),
    ("PWF3m6IG67o", "Brain Surgery While Doing Math Problems", "2026-09-21", "1:00", 1400, 61.4, "0:32", 53.7, None),
    ("gQ8cV2WJ-D0", "Why Pure Drive Makes Discipline Unnecessary", "2026-10-02", "0:38", 1352, 55.0, "0:34", 91.3,
     "e9e44926_c07"),
    ("gRbV_tj_YEY", "Brain Tumor Patient Is Now Back Rolling Jiu-Jitsu 5 Days A Week", "2026-10-03", "0:24", 1351,
     None, "0:11", 49.7, "e9e44926_c04"),
    ("yelKw0tftoM", "Is It OCD Or Just Passion? Here's The Real Difference", "2026-10-02", "0:47", 1350, 55.6, "0:31",
     67.8, "e9e44926_c08"),
    ("YQ36UAqW66M", "MDMA Therapy Can Resolve PTSD in Just 4-6 Weeks", "2026-09-30", "0:23", 1289, 45.4, "0:16", 72.2,
     "88a7e7c1_c04"),
    ("1k26O5jZKFU", "A Stem Cell Shot Gave Him An Infection Doctors Had Never Seen", "2026-10-01", "1:03", 1284, 62.9,
     "0:33", 52.5, "e9e44926_c06"),
    ("oE5v5OBVxAU", "The Brain Tumor That Made a Murderer", "2026-09-17", "0:57", 1262, 47.7, "0:31", 55.8, None),
    ("V95zY9BmPnI", "He Saved Depressed Patients' Lives — Then Took His Own", "2026-09-30", "0:58", 1220, 51.4,
     "0:32", 55.8, "e9e44926_c09"),
    ("VZLjajivSrA", "He Watched His Friend Do Brain Surgery On An Awake Patient", "2026-10-02", "1:01", 1207, 59.5,
     "0:34", 55.8, "e9e44926_c01"),
    ("HdPGfq-MdZw", "Healing PTSD in Just 6 Weeks?", "2026-09-18", "0:52", 1166, 51.0, "0:38", 72.7, None),
    ("oy6pcLTlLco", "A Quarter Centimeter Decides If You Keep Your Hand Forever", "2026-10-03", "0:44", 1150, 54.8,
     "0:30", 69.4, "e9e44926_c05"),
]
LOCAL = {row[0]: row[8] for row in STUDIO if row[8]}

E9 = "e9e44926-73a8-41f0-a506-8f1143df2aab"
A88 = "88a7e7c1-ea12-4956-a6a6-0af717769671"
F82 = "82509f9b-657d-4fa8-8a61-96da3c4ff636"
B8 = "b8e46c24-7f5e-48cf-8adc-c2d2677a241e"
GONE_835 = "835c1c43-0d5a-4537-830f-f1d2c8919037"
GONE_3E0 = "3e0ea5b8-0000-4000-8000-000000000000"
HASHTAGS = " #joerogan #jre #podcast #ufc #super #clips #edits"

# (job, [(title in the app, end - start, YouTube day in the plan or None)]) — as in the real metadata.
JOBS = {
    E9: [("He Watched His Friend Do Brain Surgery On An Awake Patient", 60.0, "2026-10-02"),
         ("Patient Solves Math Problems During Live Brain Surgery", 57.0, "2026-10-01"),
         ("Paralyzed Patient's First Word Was Decoded By AI From His Brain", 57.1, None),
         ("Brain Tumor Patient Is Now Back Rolling Jiu-Jitsu 5 Days A Week", 23.9, "2026-10-03"),
         ("A Quarter Centimeter Decides If You Keep Your Hand Forever", 43.5, "2026-10-03"),
         ("A Stem Cell Shot Gave Him An Infection Doctors Had Never Seen", 62.6, "2026-10-01"),
         ("Why Pure Drive Makes Discipline Unnecessary", 37.4, "2026-10-02"),
         ("Is It OCD Or Just Passion? Here's The Real Difference", 46.8, "2026-10-02"),
         ("He Saved Depressed Patients' Lives — Then Took His Own", 57.8, "2026-09-30"),
         ("How Competing With Alex Honnold Broke Dean Potter", 29.1, "2026-10-01")],
    A88: [("Rick Rubin's Weirdest Recording Trick + His New JAY-Z Documentary", 52.9, "2026-09-29"),
          ("Is Schizophrenia Just a Brain That Leaks DMT? Huberman Explains", 57.0, "2026-09-29"),
          # retitled in Studio after publication: joined by its day + its length
          ("The Truth Behind 'Meth Strength' — And Why Adderall Is Similar", 49.9, "2026-09-29"),
          ("MDMA Therapy Can Resolve PTSD in Just 4-6 Weeks", 22.5, "2026-09-30"),
          ("Why the Most Brutal Psychedelic Might Be Legalized First", 50.0, None)],
    F82: [("Why Frustration Is the First Gate of Learning (Neuroscience)", 58.0, "2026-09-30")],
}
B8_TITLES = ["Is your ER doctor as impaired as a drunk?", "Do medical errors kill 251,000 a year?",
             "Should you get a full-body MRI?", "Are patients going rogue on their doctors?",
             "Is Big Pharma scared of microdosers?", "Should outdated experts retire?",
             "Can a dying doctor save his own life?", "Is it the needle that scares you?",
             "Why do surgeons hate whole-body scans?", "Can a cheap anesthetic fight cancer?",
             "Can AI escape onto the internet?", "Does a face-down phone still drain you?"]
B8_DAYS = ["2026-10-05", "2026-10-07", "2026-10-06", "2026-10-06", "2026-10-05", "2026-10-08", "2026-10-06",
           "2026-10-08", "2026-10-08", "2026-10-07", "2026-10-05", "2026-10-07"]
# projects deleted from the disk, still in the publish plan
GONE = [(GONE_835, 2, "Why Frustration is Essential for Learning" + HASHTAGS, "2026-09-24"),
        (GONE_835, 5, "Why Edibles Are Suddenly Causing Psychosis" + HASHTAGS, "2026-09-24"),
        (GONE_835, 4, "The Dangerous Truth About Kratom" + HASHTAGS, "2026-09-25"),
        (GONE_835, 3, "The Secret to Blunting Daily Stress" + HASHTAGS, "2026-09-25"),
        (GONE_3E0, 4, "Can a brain tumor make you a killer?", "2026-09-28")]


def _plan_entry(job, index, title, day, platform="youtube", **extra):
    return {"id": f"{job[:8]}-{index}-{platform}", "job_id": job, "clip_index": index, "title": title,
            "platform": platform, "date": day, "time": "12:00", "auto": True, "source": "upload-post",
            "profile": "default", **extra}


def make_world(tmp_path, b8_extra=None):
    """output/<job>/<job>_Ep-00N_metadata.json for the four jobs + publish_schedule.json; -> (output, plan)."""
    output = tmp_path / "output"
    plan = []
    for job, clips in JOBS.items():
        shorts = []
        for i, (title, dur, day) in enumerate(clips):
            shorts.append({"start": 100.0, "end": 100.0 + dur, "video_title_for_youtube_short": title,
                           "predicted_score": 80, "broll": [{"t": 6.0, "dur": 3.0}],
                           **({"published": {"via": "upload-post", "at": 1790600000.0,
                                             "scheduled_for": f"{day}T12:00:00"}} if day else {})})
            if day:
                plan += [_plan_entry(job, i, title, day, "tiktok"), _plan_entry(job, i, title, day)]
        _write_job(output, job, shorts)
    shorts = []
    for i, title in enumerate(B8_TITLES):
        shorts.append({"start": 0.0, "end": 30.0 + i, "video_title_for_youtube_short": title,
                       "moment_id": f"m_b8_{i + 1:02d}", "topic_bucket": "medical_mystery" if i % 2 else "substances",
                       "hook_aligned": True, "predicted_score": 70 + i,
                       "copy_before_stepup": {"title": f"Old title number {i + 1} before the step up?"},
                       "broll": [{"t": 9.0, "dur": 3.0}],
                       "published": {"via": "upload-post", "at": 1791179171.0,
                                     "scheduled_for": f"{B8_DAYS[i]}T12:00:00"}})
        plan.append(_plan_entry(B8, i, title, B8_DAYS[i]))
    shorts[5]["title_check"] = {"retried": True, "before": "Are old-school doctors losing the information war?"}
    for i, extra in (b8_extra or {}).items():
        shorts[i].update(extra)
    _write_job(output, B8, shorts)
    for job, index, title, day in GONE:
        plan.append(_plan_entry(job, index, title, day))
    return str(output), plan


def _write_job(output, job, shorts):
    folder = output / job
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{job}_Joe Rogan Experience #2553 - Andrew Huberman-001_metadata.json").write_text(
        json.dumps({"shorts": shorts}), encoding="utf-8")


_FR_MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
_EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _secs(mss):
    m, s = mss.split(":")
    return int(m) * 60 + int(s)


def studio_csv(lang, rows=STUDIO):
    """The table YouTube Studio exports (Advanced mode > Content, Shorts, "Stayed to watch" and "Engaged views"
    added), in French (narrow no-break spaces for thousands, decimal commas, "28 sept. 2026") or English."""
    out = io.StringIO()
    if lang == "fr":
        out.write("Contenu,Titre de la vidéo,Heure de publication de la vidéo,Durée,Vues engagées,Vues,"
                  "Ont continué de regarder (%),Durée moyenne de visionnage,Pourcentage moyen regardé (%)\n")
        out.write('Total,,,,"28 000","44 531","62,1",0:00:34,"62,3"\n')
    else:
        out.write("Content,Video title,Video publish time,Duration,Engaged views,Views,Stayed to watch (%),"
                  "Average view duration,Average percentage viewed (%)\n")
        out.write('Total,,,,"28,000","44,531",62.1,0:00:34,62.3\n')
    for vid, title, pub, dur, views, stayed, avd, avp, _local in rows:
        y, m, d = (int(x) for x in pub.split("-"))
        engaged = views - 211
        title = '"' + title.replace('"', '""') + '"'
        if lang == "fr":
            num = lambda n: '"' + f"{n:,}".replace(",", " ") + '"'
            pct = lambda x: "" if x is None else '"' + f"{x:.1f}".replace(".", ",") + '"'
            out.write(f"{vid},{title},{d} {_FR_MONTHS[m - 1]} {y},{_secs(dur)},{num(engaged)},{num(views)},"
                      f"{pct(stayed)},0:{avd},{pct(avp)}\n")
        else:
            pct = lambda x: "" if x is None else f"{x:.2f}"
            out.write(f'{vid},{title},"{_EN_MONTHS[m - 1]} {d}, {y}",{_secs(dur)},"{engaged:,}","{views:,}",'
                      f"{pct(stayed)},0:{avd},{pct(avp)}\n")
    return out.getvalue()


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


@pytest.fixture
def world(tmp_path):
    output, plan = make_world(tmp_path)
    return output, plan, si.load_clips(output, plan)


class TestParsing:
    def test_numbers_dates_lengths(self):
        assert si.parse_number("7 646") == 7646 and si.parse_number("7\xa0646") == 7646
        assert si.parse_number("77,8") == 77.8 and si.parse_number("77,8 %") == 77.8
        assert si.parse_number("—") is None
        assert si.parse_date("Sep 28, 2026") == si.parse_date("28 sept. 2026") == "2026-09-28"
        assert si.parse_date("1 oct. 2026") == si.parse_date("October 1, 2026") == "2026-10-01"
        assert si.parse_date("2026-09-28T07:00:00Z") == si.parse_date("28/09/2026") == "2026-09-28"
        assert si.parse_date("9/28/2026") == "2026-09-28" and si.parse_date("") is None
        assert si.parse_date("Total") is None
        assert si.parse_duration("0:52") == 52 and si.parse_duration("1:23") == 83
        assert si.parse_duration("0:00:45") == 45 and si.parse_duration("52") == 52
        assert si.parse_duration("52 s") == 52 and si.parse_duration(None) is None

    def test_column_names_french_english_and_variants(self):
        cols = si._resolve_columns(["Contenu", "Titre de la vidéo", "Heure de publication de la vidéo", "Durée",
                                    "Vues engagées", "Vues", "Ont continué de regarder (%)",
                                    "Durée moyenne de visionnage", "Pourcentage moyen regardé (%)"])
        assert cols["video_id"] == "Contenu" and cols["stayed"] == "Ont continué de regarder (%)"
        assert cols["views"] == "Vues" and cols["engaged_views"] == "Vues engagées"
        assert cols["duration"] == "Durée" and cols["avg_view_duration"] == "Durée moyenne de visionnage"
        assert cols["published"] == "Heure de publication de la vidéo"
        # the older Studio name, and a renamed export
        assert si._resolve_columns(["Content", "Views", "Viewed (vs. swiped away) (%)"])["stayed"] == \
            "Viewed (vs. swiped away) (%)"
        assert si._resolve_columns(["Video", "Views", "Stayed to watch %", "title"])["stayed"] == "Stayed to watch %"


class TestReadStudio:
    @pytest.mark.parametrize("lang", ["fr", "en"])
    def test_the_23_shorts_french_and_english(self, tmp_path, lang):
        rows, problem = si.read_views(_write(tmp_path, f"studio_{lang}.csv", studio_csv(lang)))
        assert problem == "" and len(rows) == 23, "the Total line is left out"
        tumor = rows[0]
        assert tumor == {"video_id": "CeWu-DMt838", "moment_id": None, "file": None,
                         "title": "Can a brain tumor make you a killer?", "published": "2026-09-28",
                         "duration": 52.0, "views": 7646.0, "engaged_views": 7435.0, "avg_view_duration": 45.0,
                         "avg_pct_viewed": 86.9, "stayed": 77.8, "retention": 86.9}
        assert [r["stayed"] for r in rows] == [s[5] for s in STUDIO]
        assert rows[14]["stayed"] is None and rows[14]["views"] == 1351

    def test_french_and_english_read_the_same(self, tmp_path):
        fr, _ = si.read_views(_write(tmp_path, "fr.csv", studio_csv("fr")))
        en, _ = si.read_views(_write(tmp_path, "en.csv", studio_csv("en")))
        assert fr == en

    def test_semicolons_and_a_bom(self, tmp_path):
        text = "﻿" + studio_csv("fr").replace(",", ";").replace('"77;8"', '"77,8"')
        rows, problem = si.read_views(_write(tmp_path, "excel.csv", text))
        assert problem == "" and len(rows) == 23

    def test_the_zip_studio_downloads(self, tmp_path):
        path = tmp_path / "Contenu 2026-10-05.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("Données du graphique.csv", "Date,Vues\n2026-10-01,300\n")
            z.writestr("Totaux.csv", "Date,Vues\nTotal,44531\n")
            z.writestr("Données du tableau.csv", studio_csv("fr"))
        rows, problem = si.read_views(str(path))
        assert problem == "" and len(rows) == 23 and rows[0]["video_id"] == "CeWu-DMt838"
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"not a zip")
        assert si.read_views(str(bad))[1] == "not a readable ZIP file"

    def test_the_hand_made_studio_json(self, tmp_path):
        data = {"shorts": [{"id": s[0], "title": s[1], "pub": s[2], "dur": s[3], "views": s[4], "stayed": s[5],
                            "avd": s[6], "avp": s[7]} for s in STUDIO]}
        rows, problem = si.read_views(_write(tmp_path, "studio.json", json.dumps(data)))
        assert problem == "" and len(rows) == 23
        csv_rows, _ = si.read_views(_write(tmp_path, "en.csv", studio_csv("en")))
        keep = ("video_id", "title", "published", "duration", "views", "stayed", "avg_view_duration", "avg_pct_viewed")
        assert [{k: r[k] for k in keep} for r in rows] == [{k: r[k] for k in keep} for r in csv_rows]

    def test_latest_export(self, tmp_path):
        assert si.latest_export(str(tmp_path / "nowhere")) is None
        a = _write(tmp_path, "a.csv", "x")
        b = _write(tmp_path, "b.zip", "x")
        _write(tmp_path, "notes.txt", "x")
        os.utime(a, (1, 1))
        assert si.latest_export(str(tmp_path)) == b


class TestJoin:
    @pytest.mark.parametrize("lang", ["fr", "en"])
    def test_the_12_local_shorts_are_found_again(self, tmp_path, world, lang):
        _output, _plan, clips = world
        rows, _ = si.read_views(_write(tmp_path, "s.csv", studio_csv(lang)))
        links = si.link_studio(rows, clips)
        found = {r["video_id"]: c["ref"] for r, c, _how in links if c and c["local"]}
        assert found == LOCAL, "the same 12 clips as the analyst's hand-made mapping"
        how = {r["video_id"]: h for r, c, h in links if c}
        assert how["Ybb0zPGUoJM"] == "date+duration", "Meth/Adderall: retitled in Studio"
        assert sum(1 for h in how.values() if h == "title") == 16
        plan_only = sorted(c["ref"] for _r, c, _h in links if c and not c["local"])
        assert plan_only == ["3e0ea5b8_c05", "835c1c43_c03", "835c1c43_c04", "835c1c43_c05", "835c1c43_c06"]
        assert sum(1 for _r, c, _h in links if c is None) == 6, "published before the plan existed"

    def test_the_youtube_id_wins_over_everything(self, tmp_path):
        output, plan = make_world(tmp_path)
        for e in plan:
            if e["job_id"] == A88 and e["clip_index"] == 2 and e["platform"] == "youtube":
                e["youtube_id"] = "Ybb0zPGUoJM"
            if e["job_id"] == A88 and e["clip_index"] == 0 and e["platform"] == "youtube":
                e["youtube_id"] = "PVgpQpHe_Rw"     # a wrong id: the id is trusted over the title
        clips = si.load_clips(output, plan)
        rows, _ = si.read_views(_write(tmp_path, "s.csv", studio_csv("en")))
        links = {r["video_id"]: (c["ref"], h) for r, c, h in si.link_studio(rows, clips) if c}
        assert links["Ybb0zPGUoJM"] == ("88a7e7c1_c03", "youtube_id")
        assert links["PVgpQpHe_Rw"] == ("88a7e7c1_c01", "youtube_id")

    def test_old_titles_moment_id_and_file(self, tmp_path, world):
        _output, _plan, clips = world
        rows = [{"video_id": "x1", "title": "Old title number 3 before the step up?", "published": "2026-10-06"},
                {"video_id": "x2", "title": "Are old-school doctors losing the information war?"},
                {"video_id": "x3", "title": "Something else entirely", "moment_id": "m_b8_12"},
                {"video_id": "x4", "title": "Nope", "file": f"subtitled_1_hooked_2_{B8}_x_clip_9.mp4"}]
        for r in rows:
            r.setdefault("duration", None)
            r.setdefault("published", None)
        clips = [c if c["job_id"] != B8 or c["clip_index"] != 8 else {**c, "clip_file": f"{B8}_x_clip_9.mp4"}
                 for c in clips]
        links = [(c["ref"], h) for _r, c, h in si.link_studio(rows, clips)]
        assert links == [("b8e46c24_c03", "title"), ("b8e46c24_c06", "title"), ("b8e46c24_c12", "moment_id"),
                         ("b8e46c24_c09", "file")]

    def test_date_and_length_only_when_one_clip_fits(self, world):
        _output, _plan, clips = world
        row = {"video_id": "z", "title": "A title nobody knows", "published": "2026-09-29", "duration": 51.0}
        assert si.link_studio([row], clips)[0][1]["ref"] == "88a7e7c1_c03"
        assert si.link_studio([{**row, "duration": 52.5}], clips)[0][1]["ref"] == "88a7e7c1_c01", \
            "the length tells Rick Rubin (52.9 s) from Meth (49.9 s), both posted that day"
        assert si.link_studio([{**row, "duration": 55.0}], clips)[0][1] is None
        assert si.link_studio([{**row, "published": "2026-09-01"}], clips)[0][1] is None
        assert si.link_studio([{**row, "published": "2026-09-30"}], clips)[0][1]["ref"] == "88a7e7c1_c03", \
            "a day off: Studio's day can be the channel's time zone"
        twin = next(c for c in clips if c["ref"] == "88a7e7c1_c03")
        twin = {**twin, "job_id": "twin", "ref": "twin_c01", "duration": 50.5}
        assert si.link_studio([row], clips + [twin])[0][1] is None, "two clips fit: say nothing rather than guess"

    def test_a_title_is_not_given_twice_on_a_prefix(self, world):
        _output, _plan, clips = world
        rows = [{"video_id": "a", "title": "How Competing With Alex Honnold Broke Dean Potter", "published": None,
                 "duration": None},
                {"video_id": "b", "title": "How Competing With Alex Honnold", "published": None, "duration": None}]
        links = si.link_studio(rows, clips)
        assert links[0][1]["ref"] == "e9e44926_c10" and links[1][1] is None


class TestReport:
    def test_stayed_first(self, tmp_path, world):
        _output, _plan, clips = world
        rows, _ = si.read_views(_write(tmp_path, "s.csv", studio_csv("fr")))
        report = si.build_studio_report(rows, clips, as_of=si.date(2026, 10, 4))
        assert (report["rows"], report["linked_clip"], report["linked_plan"], report["unlinked"]) == (23, 12, 5, 6)
        assert report["how"] == {"title": 16, "date+duration": 1} and report["with_stayed"] == 22
        stayed = [p["stayed"] for p in report["posts"]]
        assert stayed[:3] == [77.8, 73.2, 69.7] and stayed[-1] is None, "sorted by stayed, the missing one last"
        assert report["stayed_vs_views"]["n"] == 22 and report["stayed_vs_views"]["spearman"] >= 0.7
        assert report["avg_pct_vs_views"]["spearman"] < 0.4, "% viewed says much less"
        g = report["groups"]
        assert [r["stayed_median"] for r in g["duration"]] == \
            sorted((r["stayed_median"] for r in g["duration"]), reverse=True)
        assert {r["key"]: (r["n"], r["few"]) for r in g["duration"]}["20-30 s"] == (2, True)
        assert g["opening_image"] == [{"key": "no", "n": 12, "n_stayed": 11, "stayed_median": 55.6,
                                       "stayed_mean": 57.2, "views_median": 1350, "engaged_median": 1140,
                                       "avg_pct_median": 60.4, "few": False}]
        assert g["title_form"][0]["key"] == "Can" and g["title_form"][0]["few"]
        assert g["topic_bucket"] == [] and g["moment_nature"] == [], "no published clip has them yet"
        text = si.format_studio_report(report)
        assert "12 reliés à un clip" in text and "Par durée" in text and "trop peu pour conclure" in text
        assert "Pas encore dans l'export : b8e46c24_c01, b8e46c24_c03" in text

    def test_topic_moment_nature_and_opening_groups(self, tmp_path):
        extra = {i: {"moment_nature": "threat" if i < 6 else "explanation"} for i in range(12)}
        output, plan = make_world(tmp_path, extra)
        clips = si.load_clips(output, plan)
        rows = [{"video_id": f"v{i}", "title": B8_TITLES[i], "published": B8_DAYS[i], "duration": 31.0 + i,
                 "views": 1300.0 + 100 * i, "engaged_views": None, "avg_pct_viewed": 60.0,
                 "stayed": 50.0 + i} for i in range(12)]
        report = si.build_studio_report(rows, clips, as_of=si.date(2026, 10, 12))
        g = report["groups"]
        assert {r["key"]: r["n"] for r in g["moment_nature"]} == {"threat": 6, "explanation": 6}
        assert g["moment_nature"][0]["key"] == "explanation", "the better median stayed first"
        assert {r["key"] for r in g["topic_bucket"]} == {"substances", "medical_mystery"}
        assert {r["key"]: r["n"] for r in g["opening_image"]} == {"yes": 6, "no": 6}


class TestOpeningAB:
    def test_how_an_opening_is_known(self):
        assert si.opening_image({"opening_image": {"dur": 1.2}}) is True
        assert si.opening_image({"broll": [{"t": 0.0, "dur": 1.2}]}) is True
        assert si.opening_image({"broll": [{"t": 4.0, "role": "opening"}]}) is True
        assert si.opening_image({"broll": [{"t": 4.56, "dur": 2.2}]}) is False
        # the 6 clips of the 5-8 oct test, posed by hand on 4-oct before the field existed
        assert [n for n in range(1, 13) if si.opening_image({}, None, B8, n - 1)] == [1, 3, 8, 10, 11, 12]
        assert si.opening_image({}, None, E9, 0) is False
        assert si.opening_image({}, {}, B8, 0) is False, "openings={} turns the A/B record off"

    def _ab_rows(self, stayed_with, stayed_without):
        rows = []
        with_n = iter(stayed_with)
        without_n = iter(stayed_without)
        for i in range(12):
            stayed = next(with_n) if i + 1 in si.AB_OPENING_TEST["clips"] else next(without_n)
            if stayed is not None:
                rows.append({"video_id": f"v{i}", "title": B8_TITLES[i], "published": B8_DAYS[i],
                             "duration": 31.0 + i, "views": 1300.0, "stayed": stayed})
        return rows

    def test_six_against_six(self, world):
        _output, _plan, clips = world
        rows = [{"video_id": s[0], "title": s[1], "published": s[2], "duration": None, "views": s[4],
                 "stayed": s[5]} for s in STUDIO]
        rows += self._ab_rows([70, 66, 64, 68, 72, 65], [55, 58, 52, 60, 57, 54])
        ab = si.build_studio_report(rows, clips, as_of=si.date(2026, 10, 12))["ab_opening"]
        assert ab["with"]["n"] == ab["without"]["n"] == 6, "control: the same job, not the older shorts"
        assert ab["with"]["refs"] == ["b8e46c24_c11", "b8e46c24_c01", "b8e46c24_c10", "b8e46c24_c03",
                                      "b8e46c24_c12", "b8e46c24_c08"]
        assert ab["gap"] == pytest.approx(11.5, abs=0.05)
        assert ab["p_value"] == pytest.approx(2 / 924, abs=1e-3), "exact: only 2 splits of 924 are that extreme"
        assert ab["verdict"] == "signal" and ab["pending"] == []
        text = si.format_ab(ab)
        assert "pas une preuve" in text and "6 contre 6" in text

    def test_a_small_gap_is_called_chance(self, world):
        _output, _plan, clips = world
        rows = self._ab_rows([60, 55, 58, 62, 54, 57], [59, 56, 61, 53, 58, 55])
        ab = si.build_studio_report(rows, clips, as_of=si.date(2026, 10, 12))["ab_opening"]
        assert ab["verdict"] == "chance" and ab["p_value"] > 0.5
        assert "Compatible avec le hasard" in si.format_ab(ab)

    def test_too_few_young_and_pending(self, world):
        _output, _plan, clips = world
        rows = self._ab_rows([70, 66, None, None, None, None], [55, 58, 52, None, None, None])
        ab = si.build_studio_report(rows, clips, as_of=si.date(2026, 10, 6))["ab_opening"]
        assert ab["verdict"] == "too_few" and ab["with"]["n"] == 2
        assert ab["pending"] == ["b8e46c24_c08", "b8e46c24_c10", "b8e46c24_c11", "b8e46c24_c12"]
        assert ab["with"]["young"] == 2, "c01 and c03 were published less than 2 days before the export"
        text = si.format_ab(ab)
        assert "trop peu de shorts" in text and "moins de 2 jours" in text
        assert si.ab_opening([], clips)["verdict"] == "no_data"

    def test_permutation_p(self):
        assert si.permutation_p([1, 2, 3], [1, 2, 3]) == 1.0
        assert si.permutation_p([10, 11, 12], [1, 2, 3]) == pytest.approx(2 / 20)
        assert si.permutation_p([], [1]) is None
        big = si.permutation_p(list(range(20)), list(range(2, 22)), limit=500)   # C(40, 20) splits: sampled
        assert 0 < big < 1 and big == si.permutation_p(list(range(20)), list(range(2, 22)), limit=500)

    def test_mark_opening_keeps_the_date(self, tmp_path):
        output, plan = make_world(tmp_path)
        meta = next((tmp_path / "output" / E9).glob("*_metadata.json"))
        os.utime(meta, (1_700_000_000, 1_700_000_000))
        assert si.mark_opening(output, "e9e44926", [2, 4]) == ["e9e44926_c02", "e9e44926_c04"]
        assert os.path.getmtime(meta) == 1_700_000_000
        shorts = json.loads(meta.read_text(encoding="utf-8"))["shorts"]
        assert shorts[1]["opening_image"]["dur"] == si.OPENING_SECONDS and "opening_image" not in shorts[0]
        clips = {c["ref"]: c for c in si.load_clips(output, plan, openings={})}
        assert clips["e9e44926_c02"]["opening_image"] and not clips["b8e46c24_c01"]["opening_image"]
        with pytest.raises(ValueError):
            si.mark_opening(output, "e9e44926", [11])
        with pytest.raises(ValueError):
            si.mark_opening(output, "", [1])           # several jobs match


class TestYoutubeId:
    def test_from_upload_post_answers(self):
        assert si.youtube_id({"platform": "youtube", "post_url": "https://www.youtube.com/shorts/CeWu-DMt838"}) \
            == "CeWu-DMt838"
        assert si.youtube_id({"url": "https://youtube.com/watch?feature=x&v=8fwsjVBQuMk"}) == "8fwsjVBQuMk"
        assert si.youtube_id({"results": {"youtube": {"success": True, "video_id": "AijB6kk2gq0"}}}) == "AijB6kk2gq0"
        assert si.youtube_id({"platform": "youtube", "platform_post_id": "gDPFFxA5yPw"}) == "gDPFFxA5yPw"
        assert si.youtube_id([{"platform": "tiktok", "post_url": "https://tiktok.com/@a/video/1"},
                              {"share_url": "https://youtu.be/DPYOXHh1wuQ"}]) == "DPYOXHh1wuQ"
        assert si.youtube_id({"platform": "tiktok", "platform_post_id": "73519846201"}) == ""
        assert si.youtube_id({"success": True, "request_id": "a1b2c3"}) == ""
        assert si.youtube_id(None) == ""


class TestCli:
    def test_report_ab_and_mark(self, tmp_path, capsys):
        output, plan = make_world(tmp_path)
        schedule = _write(tmp_path, "publish_schedule.json", json.dumps({"entries": plan}))
        path = _write(tmp_path, "Table data.csv", studio_csv("en"))
        common = ["--output", output, "--schedule", schedule, "--as-of", "2026-10-04"]
        assert si.main([path, *common, "--json", str(tmp_path / "r.json")]) == 0
        out = capsys.readouterr().out
        assert "23 shorts dans l'export" in out and "12 reliés" in out and "88a7e7c1_c03 ?" in out
        assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["linked_clip"] == 12
        assert si.main(["ab", path, *common]) == 0
        assert "pas encore de chiffres" in capsys.readouterr().out
        assert si.main(["ab", path, *common, "--opening", "e9e44926:10,6,1"]) == 0
        out = capsys.readouterr().out
        assert "avec ouverture : 3 short(s)" in out and "e9e44926_c10 63,4 %" in out
        assert si.main(["mark-opening", "e9e44926", "1,2", "--output", output]) == 0
        assert "e9e44926_c01, e9e44926_c02" in capsys.readouterr().out
        assert si.main([_write(tmp_path, "bad.csv", "Content,likes\na,1\n"), *common]) == 1


class TestPlusStatsEndpoint:
    """/api/plus/stats: the Studio part needs no Upload-Post key; the YouTube ids Upload-Post reports are kept
    in the publish plan; the dashboard's import saves the export."""

    def _app(self, tmp_path, monkeypatch, plan):
        app = pytest.importorskip("app")
        schedule = tmp_path / "publish_schedule.json"
        schedule.write_text(json.dumps({"entries": plan}), encoding="utf-8")
        monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path / "output"))
        monkeypatch.setattr(app, "PUBLISH_SCHEDULE_FILE", str(schedule))
        monkeypatch.setattr(app, "STUDIO_STATS_DIR", str(tmp_path / "stats"))
        return app, schedule

    def test_studio_without_upload_post(self, tmp_path, monkeypatch):
        _output, plan = make_world(tmp_path)
        app, _ = self._app(tmp_path, monkeypatch, plan)

        async def no_key(request, body_key=None):
            return None, None

        monkeypatch.setattr(app, "resolve_upload_post", no_key)
        with pytest.raises(app.HTTPException) as e:
            asyncio.run(app.plus_stats(request=None, users="", days=60))
        assert e.value.status_code == 400, "nothing to show yet"
        (tmp_path / "stats").mkdir()
        (tmp_path / "stats" / "studio_20261004.csv").write_text(studio_csv("fr"), encoding="utf-8")
        data = asyncio.run(app.plus_stats(request=None, users="", days=60))
        s = data["studio"]
        assert data["total_posts"] == 0 and s["file"] == "studio_20261004.csv"
        assert (s["rows"], s["linked_clip"], s["linked_plan"]) == (23, 12, 5)
        assert s["posts"][0]["stayed"] == 77.8 and s["groups"]["opening_image"][0]["key"] == "no"
        assert s["ab_opening"]["verdict"] == "no_data" and len(s["ab_opening"]["pending"]) == 6

    def test_youtube_ids_from_upload_post_are_kept_and_used(self, tmp_path, monkeypatch):
        _output, plan = make_world(tmp_path)
        app, schedule = self._app(tmp_path, monkeypatch, plan)
        (tmp_path / "stats").mkdir()
        (tmp_path / "stats" / "studio.csv").write_text(studio_csv("en"), encoding="utf-8")

        async def fake_key(request, body_key=None):
            return "key", None

        async def fake_get(api_key, url, params):
            return {"posts": [
                {"platform": "youtube", "external_id": f"openshorts:{A88}:2", "title": "x", "views": 1700,
                 "post_url": "https://www.youtube.com/shorts/Ybb0zPGUoJM"},
                {"platform": "tiktok", "external_id": f"openshorts:{A88}:2", "title": "x", "views": 30,
                 "post_url": "https://www.tiktok.com/@a/video/1"},
            ]}

        monkeypatch.setattr(app, "resolve_upload_post", fake_key)
        monkeypatch.setattr(app, "_upload_post_get", fake_get)
        data = asyncio.run(app.plus_stats(request=None, users="default", days=60))
        saved = json.loads(schedule.read_text())["entries"]
        mine = [e for e in saved if e["job_id"] == A88 and e["clip_index"] == 2]
        assert {e["platform"]: e.get("youtube_id") for e in mine} == {"tiktok": None, "youtube": "Ybb0zPGUoJM"}
        meth = next(p for p in data["studio"]["posts"] if p["video_id"] == "Ybb0zPGUoJM")
        assert (meth["ref"], meth["how"]) == ("88a7e7c1_c03", "youtube_id")
        assert data["total_posts"] == 1

    def test_upload_post_down_still_shows_studio(self, tmp_path, monkeypatch):
        _output, plan = make_world(tmp_path)
        app, _ = self._app(tmp_path, monkeypatch, plan)
        (tmp_path / "stats").mkdir()
        (tmp_path / "stats" / "studio.csv").write_text(studio_csv("en"), encoding="utf-8")

        async def fake_key(request, body_key=None):
            return "key", None

        async def down(api_key, url, params):
            raise app.HTTPException(status_code=502, detail="Vendor API Error: down")

        monkeypatch.setattr(app, "resolve_upload_post", fake_key)
        monkeypatch.setattr(app, "_upload_post_get", down)
        data = asyncio.run(app.plus_stats(request=None, users="default", days=60))
        assert data["studio"]["linked_clip"] == 12 and "down" in data["upload_post_error"]

    def test_import_endpoint(self, tmp_path, monkeypatch):
        _output, plan = make_world(tmp_path)
        app, _ = self._app(tmp_path, monkeypatch, plan)
        from starlette.testclient import TestClient
        client = TestClient(app.app)
        r = client.post("/api/plus/stats/studio",
                        files={"file": ("Table data.csv", studio_csv("fr").encode("utf-8"), "text/csv")})
        assert r.status_code == 200 and r.json()["rows"] == 23 and r.json()["with_stayed"] == 22
        assert len(os.listdir(tmp_path / "stats")) == 1
        r = client.post("/api/plus/stats/studio", files={"file": ("notes.csv", b"a,b\n1,2\n", "text/csv")})
        assert r.status_code == 400 and "Could not read this export" in r.json()["detail"]
        r = client.post("/api/plus/stats/studio", files={"file": ("video.mp4", b"x", "video/mp4")})
        assert r.status_code == 400
        assert len(os.listdir(tmp_path / "stats")) == 1, "a refused file is not kept"

    def test_the_plan_keeps_upload_posts_answer(self, tmp_path, monkeypatch):
        _output, plan = make_world(tmp_path)
        app, schedule = self._app(tmp_path, monkeypatch, [])
        req = app.SocialPostRequest(job_id=B8, clip_index=0, platforms=["tiktok", "youtube"], scheduled_date=None,
                                    timezone="Europe/Paris")
        app._record_upload_post_in_plan(req, {"video_url": "/videos/x.mp4"}, "T", "default",
                                        {"success": True, "request_id": "req-42",
                                         "results": {"youtube": {"url": "https://youtu.be/CeWu-DMt838"}}})
        app._record_upload_post_in_plan(req, {"video_url": "/videos/x.mp4"}, "T", "default", None)
        entries = json.loads(schedule.read_text())["entries"]
        assert [(e["platform"], e.get("upload_post_id"), e.get("youtube_id")) for e in entries] == [
            ("tiktok", "req-42", None), ("youtube", "req-42", "CeWu-DMt838"),
            ("tiktok", None, None), ("youtube", None, None)]
