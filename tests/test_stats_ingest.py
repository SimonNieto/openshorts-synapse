"""stats_ingest.py: the playbook exports joined to a CSV of real views (legacy path; the YouTube Studio export
is tested in test_stats_studio.py)."""
import json

import pytest

import stats_ingest as si


def _export(tmp_path, job, n, **fields):
    data = {"moment_id": f"m_{job}{n}", "clip_file": f"{job}_Ep #1 - Guest-001_clip_{n}.mp4", "duration": 30.0,
            "topic_bucket": "substances", "title": f"Can thing {n} happen?", "hook_aligned": True, "score": 80,
            **fields}
    folder = tmp_path / "output" / job
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{job}_Ep #1 - Guest-001_clip_{n}_playbook.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def _csv(tmp_path, text, name="views.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


class TestParsing:
    def test_numbers(self):
        assert si.parse_number("7,100") == 7100 and si.parse_number("7 100") == 7100
        assert si.parse_number("7.100") == 7100 and si.parse_number("1,234,567") == 1234567
        assert si.parse_number("7.1K") == 7100 and si.parse_number("1.2 M") == 1200000
        assert si.parse_number("45,3 %") == 45.3 and si.parse_number("0.453") == 0.453
        assert si.parse_number("1300") == 1300 and si.parse_number("12.5") == 12.5
        for bad in ("", None, "n/a", "Total"):
            assert si.parse_number(bad) is None, bad

    def test_title_form(self):
        assert si.title_form("Can a brain tumor make you a killer?") == "Can"
        assert si.title_form("why do some people hear voices?") == "Why"
        assert si.title_form("The Brain Tumor That Made a Murderer") == "other"
        assert si.title_form("") == "other" and si.title_form(None) == "other"

    def test_duration_bucket(self):
        assert [si.duration_bucket(d) for d in (12, 20, 29.9, 37, 49, 58, 75)] == \
            ["< 20 s", "20-30 s", "20-30 s", "30-40 s", "40-50 s", "50-60 s", "60 s +"]
        assert si.duration_bucket(None) is None and si.duration_bucket(0) is None

    def test_file_key_walks_back_the_burned_layers(self):
        canonical = "abc_Ep #1 - Guest-001_clip_3.mp4"
        assert si.file_key(canonical) == si.file_key("subtitled_179_hooked_178_" + canonical)
        assert si.file_key("C:\\out\\job\\hooked_1_" + canonical) == si.file_key(canonical)


class TestMaths:
    def test_median(self):
        assert si.median([3, 1, 2]) == 2 and si.median([4, 1, 2, 3]) == 2.5 and si.median([]) is None

    def test_spearman(self):
        assert si.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
        assert si.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
        # ranks, not sizes: one viral clip does not decide it
        assert si.spearman([70, 75, 80, 85], [100, 200, 300, 900000]) == pytest.approx(1.0)
        assert si.spearman([1, 2], [1, 2]) is None, "two points say nothing"
        assert si.spearman([5, 5, 5], [1, 2, 3]) is None, "no spread in the score"

    def test_ties_share_a_rank(self):
        assert si._ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]


class TestReadViews:
    _EMPTY = {"video_id": None, "moment_id": None, "file": None, "title": None, "published": None, "duration": None,
              "views": None, "engaged_views": None, "avg_view_duration": None, "avg_pct_viewed": None,
              "stayed": None, "retention": None}

    def test_youtube_studio_style(self, tmp_path):
        path = _csv(tmp_path, "Content,Video title,Views,Average percentage viewed (%)\n"
                              "Total,,8400,61.2\n"
                              'abc,"Can thing 1 happen?","7,100",72.5\n'
                              "def,Can thing 2 happen?,1300,\n")
        rows, problem = si.read_views(path)
        assert problem == "" and len(rows) == 2, "Studio's Total line is not a video"
        assert rows[0] == {**self._EMPTY, "video_id": "abc", "title": "Can thing 1 happen?", "views": 7100.0,
                           "avg_pct_viewed": 72.5, "retention": 72.5}
        assert rows[1]["retention"] is None

    def test_french_headers_and_semicolons(self, tmp_path):
        path = _csv(tmp_path, "\ufeffFichier;Vues;Rétention\nclip_1.mp4;7 100;45,3\n")
        rows, problem = si.read_views(path)
        assert problem == "" and rows == [{**self._EMPTY, "file": "clip_1.mp4", "views": 7100.0,
                                           "avg_pct_viewed": 45.3, "retention": 45.3}]

    def test_says_what_is_missing(self, tmp_path):
        assert "no views column" in si.read_views(_csv(tmp_path, "title,likes\nx,3\n"))[1]
        assert "no video id (Content), moment_id, file or title column" in \
            si.read_views(_csv(tmp_path, "date,views\nx,3\n"))[1]


class TestJoinAndReport:
    def _setup(self, tmp_path):
        _export(tmp_path, "a", 1, topic_bucket="substances", duration=28.0, score=90)
        _export(tmp_path, "a", 2, topic_bucket="substances", duration=52.0, score=80,
                title="Why does thing 2 happen?", hook_aligned=False)
        _export(tmp_path, "b", 1, topic_bucket="sports_combat", duration=55.0, score=70, off_niche=True,
                hook_clear=False)
        _export(tmp_path, "b", 2, topic_bucket="mind_psychology", duration=35.0, score=60)   # never published
        return si.load_exports(str(tmp_path / "output"))

    def test_rows_match_by_id_file_or_title_and_platforms_add_up(self, tmp_path):
        exports = self._setup(tmp_path)
        assert len(exports) == 4
        rows = [{"moment_id": "m_a1", "file": None, "title": None, "views": 5000.0, "retention": 70.0},
                {"moment_id": "", "file": "subtitled_9_hooked_8_a_Ep #1 - Guest-001_clip_1.mp4", "title": None,
                 "views": 2100.0, "retention": 60.0},
                {"moment_id": None, "file": None, "title": "WHY does thing 2 happen?? 🧠 #brain", "views": 1300.0,
                 "retention": None},
                {"moment_id": None, "file": None, "title": "Someone else's video", "views": 99.0, "retention": None}]
        clips, unmatched = si.join(exports, rows)
        by = {c["moment_id"]: c for c in clips}
        assert by["m_a1"]["views"] == 7100.0 and by["m_a1"]["retention"] == 65.0
        assert by["m_a2"]["views"] == 1300.0 and by["m_a2"]["retention"] is None
        assert len(clips) == 2 and [r["title"] for r in unmatched] == ["Someone else's video"]

    def test_report(self, tmp_path):
        exports = self._setup(tmp_path)
        rows, _ = si.read_views(_csv(tmp_path, "moment_id,views\nm_a1,7100\nm_a2,1300\nm_b1,400\nm_zz,5\n"))
        report = si.build_report(exports, rows)
        assert report["clips"] == 3 and report["unmatched"] == 1 and report["exports"] == 4
        g = report["groups"]
        assert g["topic_bucket"][0] == {"key": "substances", "posts": 2, "median_views": 4200, "avg_views": 4200,
                                        "median_retention": None}
        assert g["topic_bucket"][1]["key"] == "sports_combat"
        assert {r["key"]: r["median_views"] for r in g["title_form"]} == {"Can": 3750, "Why": 1300}
        assert {r["key"]: r["posts"] for r in g["duration"]} == {"20-30 s": 1, "50-60 s": 2}
        assert {r["key"]: r["median_views"] for r in g["hook_aligned"]} == {"yes": 3750, "no": 1300}
        assert {r["key"] for r in g["off_niche"]} == {"yes"}, "only the exports that have the flag"
        assert report["score_vs_views"] == {"n": 3, "spearman": 1.0,
                                            "pearson_log_views": report["score_vs_views"]["pearson_log_views"]}
        assert report["posts"][0]["views"] == 7100.0
        text = si.format_report(report)
        assert "3 published clip(s) matched" in text and "by topic" in text and "by title shape" in text
        assert "Spearman +1.00" in text and "too few clips to trust it yet" in text

    def test_cli(self, tmp_path, capsys):
        self._setup(tmp_path)
        csv_path = _csv(tmp_path, "moment_id,views\nm_a1,7100\nm_a2,1300\nm_b1,400\n")
        out_json = tmp_path / "stats.json"
        assert si.main([csv_path, "--output", str(tmp_path / "output"), "--json", str(out_json)]) == 0
        assert "by length" in capsys.readouterr().out
        assert json.loads(out_json.read_text(encoding="utf-8"))["clips"] == 3
        assert si.main([csv_path, "--output", str(tmp_path / "empty")]) == 1
        assert "No *_playbook.json" in capsys.readouterr().out
        assert si.main([_csv(tmp_path, "title,likes\nx,1\n", "bad.csv"), "--output", str(tmp_path / "output")]) == 1


class TestPlusStatsEndpoint:
    """/api/plus/stats (Upload-Post's live views) groups by what the playbook
    recorded too, with the same helpers."""

    def test_playbook_groups_and_score_correlation(self, tmp_path, monkeypatch):
        import asyncio
        app = pytest.importorskip("app")
        job = tmp_path / "job1"
        job.mkdir()
        shorts = [
            {"start": 0, "end": 30, "predicted_score": 90, "topic_bucket": "substances", "hook_aligned": True,
             "video_title_for_youtube_short": "Can kratom hurt you?"},
            {"start": 0, "end": 50, "predicted_score": 80, "topic_bucket": "substances", "hook_aligned": False,
             "video_title_for_youtube_short": "Why does sleep matter?"},
            {"start": 0, "end": 55, "predicted_score": 70, "topic_bucket": "sports_combat", "hook_aligned": True,
             "video_title_for_youtube_short": "Is this the greatest fight?"},
        ]
        (job / "x_metadata.json").write_text(json.dumps({"shorts": shorts, "plus_profile": {"name": "p"}}),
                                             encoding="utf-8")
        monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(app, "_load_schedule", lambda: [])

        async def fake_key(request, body_key=None):
            return "key", None

        async def fake_get(api_key, url, params):
            return {"posts": [
                {"platform": "youtube", "external_id": "openshorts:job1:0", "title": "a", "views": 7100},
                {"platform": "tiktok", "external_id": "openshorts:job1:0", "title": "a", "views": 900},
                {"platform": "youtube", "external_id": "openshorts:job1:1", "title": "b", "views": 1300},
                {"platform": "youtube", "external_id": "openshorts:job1:2", "title": "c", "views": 400},
                {"platform": "youtube", "external_id": "", "title": "someone else's", "views": 5},
            ]}

        monkeypatch.setattr(app, "resolve_upload_post", fake_key)
        monkeypatch.setattr(app, "_upload_post_get", fake_get)
        data = asyncio.run(app.plus_stats(request=None, users="acct", days=60))
        g = data["groups"]
        assert data["total_posts"] == 3 and data["unmatched"] == 1
        assert {r["key"]: (r["posts"], r["avg_views"], r["median_views"]) for r in g["topic"]} == \
            {"substances": (2, 4650, 4650), "sports_combat": (1, 400, 400)}
        assert {r["key"]: r["avg_views"] for r in g["title_form"]} == {"Can": 8000, "Why": 1300, "Is": 400}
        assert {r["key"]: r["posts"] for r in g["hook_aligned"]} == {"yes": 2, "no": 1}
        assert data["score_vs_views"]["n"] == 3 and data["score_vs_views"]["spearman"] == 1.0
        assert "median_views" in g["duration"][0], "the older groups get the median too"
