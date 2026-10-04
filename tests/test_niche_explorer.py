"""The « Niches » tab (niche_explorer, 4-oct-2026): links read right, YouTube read through a fake, the AI faked,
the colours the page shows can be trusted (no green right without grounds)."""
import pytest

import niche_explorer as ne


class TestParseRef:
    @pytest.mark.parametrize("text, want", [
        ("@joerogan", ("handle", "@joerogan")),
        ("https://www.youtube.com/@TheSynapseCut/videos", ("handle", "@TheSynapseCut")),
        ("youtube.com/channel/UCzQUP1qoWDoEbmsQxvdjxgQ", ("channel", "UCzQUP1qoWDoEbmsQxvdjxgQ")),
        ("https://www.youtube.com/watch?v=abc123XYZ_-&t=4s", ("video", "abc123XYZ_-")),
        ("https://youtu.be/abc123", ("video", "abc123")),
        ("https://www.youtube.com/shorts/xyz789", ("video", "xyz789")),
        ("https://www.youtube.com/user/PowerfulJRE", ("user", "PowerfulJRE")),
        ("https://www.youtube.com/c/JoeRogan", ("query", "JoeRogan")),
        ("Joe Rogan Experience", ("query", "Joe Rogan Experience")),
        ("", None),
    ])
    def test_links(self, text, want):
        assert ne.parse_ref(text) == want


def test_durations_and_numbers():
    assert ne._seconds("PT1H2M3S") == 3723 and ne._seconds("PT45S") == 45 and ne._seconds("") == 0
    vids = [{"published": f"2026-09-{d:02d}T10:00:00Z", "views": v, "seconds": s}
            for d, v, s in ((1, 100, 3600), (8, 300, 60), (15, 200, 7200))]
    assert ne.numbers(vids) == {"median_views": 200, "per_week": 1.0, "long_share": 0.67}
    assert ne.numbers([])["median_views"] is None


def test_evidence_quotes_only_the_channel_s_own_lines():
    card = {"description": "Weekly long conversations.\nFeel free to clip and repost with credit!\nMerch: shop.com"}
    vids = [{"title": "Ep 1", "description": "Sponsors...\nAll clips must link back; no full reuploads (copyright)."}]
    ev = ne.evidence(card, vids)
    assert [e["quote"] for e in ev] == ["Feel free to clip and repost with credit!",
                                        "All clips must link back; no full reuploads (copyright)."]
    assert ev[0]["where"] == "channel description" and ev[1]["where"].startswith("description of")
    assert ne.evidence({"description": "Science podcast."}, []) == []


class TestCleanRatings:
    def test_no_green_right_without_grounds(self):
        r = {"fit": "green", "rights": "green", "rights_basis": "said by the channel"}
        assert ne._clean(r, has_evidence=False)["rights"] == "orange", "said by the channel, but nothing quoted"
        assert ne._clean(r, has_evidence=True)["rights"] == "green"
        assert ne._clean({**r, "rights_basis": "known reputation"}, False)["rights"] == "green"
        assert ne._clean({**r, "rights_basis": "a hunch"}, True)["rights"] == "orange"

    def test_overall_from_the_two(self):
        assert ne._clean({"fit": "green", "rights": "green", "rights_basis": "known reputation"}, False)["overall"] == "green"
        assert ne._clean({"fit": "green", "rights": "orange"}, False)["overall"] == "orange"
        assert ne._clean({"fit": "red", "rights": "green", "rights_basis": "known reputation"}, False)["overall"] == "red"
        assert ne._clean({"fit": "purple", "rights": None}, False)["fit"] == "orange", "unknown colours: orange"


# --- a whole run against a fake YouTube and a fake AI -----------------------------------------------

def _chan(cid, title, handle, desc=""):
    return {"id": cid, "snippet": {"title": title, "customUrl": handle, "description": desc, "thumbnails": {}},
            "statistics": {"subscriberCount": "1000"}, "contentDetails": {"relatedPlaylists": {"uploads": f"UU{cid}"}}}


CHANNELS = {"MINE": _chan("MINE", "The Synapse Cut", "@thesynapsecut"),
            "JRE": _chan("JRE", "PowerfulJRE", "@joerogan"),
            "SCI": _chan("SCI", "Science Talks", "@scitalks", "Clips welcome: feel free to clip our episodes."),
            "MMA": _chan("MMA", "Fight Talk", "@fighttalk"),
            "GAME": _chan("GAME", "Gamer Pod", "@gamerpod")}
SEARCH = {"science podcast": ["SCI", "SCI", "JRE", "MINE"], "mma podcast": ["MMA", "SCI"], "gaming": ["GAME"]}


class FakeYouTube:
    def __init__(self):
        self.calls = []

    def get(self, path, key, **p):
        self.calls.append(path)
        if path == "channels" and "forHandle" in p:
            cid = {"@thesynapsecut": "MINE", "@joerogan": "JRE"}.get(p["forHandle"].lower())
            return {"items": [{"id": cid}] if cid else []}
        if path == "channels":
            return {"items": [CHANNELS[i] for i in p["id"].split(",") if i in CHANNELS]}
        if path == "playlistItems":
            return {"items": [{"contentDetails": {"videoId": p["playlistId"][2:] + "_v"}}]}
        if path == "videos":
            return {"items": [{"id": i, "snippet": {"title": f"{i} episode", "publishedAt": "2026-09-01T00:00:00Z",
                                                   "description": ""},
                               "statistics": {"viewCount": "5000"}, "contentDetails": {"duration": "PT2H"}}
                              for i in p["id"].split(",")]}
        if path == "search":
            return {"items": [{"snippet": {"channelId": c}} for c in SEARCH.get(p["q"], [])]}
        raise AssertionError(path)


@pytest.fixture
def run(monkeypatch, tmp_path):
    yt = FakeYouTube()
    monkeypatch.setattr(ne, "STORE", str(tmp_path))
    monkeypatch.setattr(ne, "_get", lambda client, path, key, **p: yt.get(path, key, **p))
    monkeypatch.setattr(ne, "_profile_line", lambda: "")
    asked = []

    def ask(prompt, schema):
        asked.append(prompt)
        if schema is ne.Understanding:
            return {"niche": "podcasts cerveau", "summary": "s", "good_source": "g", "niches": [
                {"name": "Science", "why": "w", "fit": "green", "search": "science podcast"},
                {"name": "Combat", "why": "w", "fit": "orange", "search": "mma podcast"},
                {"name": "Gaming", "why": "w", "fit": "red", "search": "gaming"}]}
        return {"ratings": [
            {"id": "JRE", "fit": "green", "fit_why": "", "rights": "orange", "rights_basis": "nothing found",
             "rights_why": "", "summary": ""},
            {"id": "SCI", "fit": "green", "fit_why": "", "rights": "green", "rights_basis": "said by the channel",
             "rights_why": "", "summary": ""},
            {"id": "MMA", "fit": "orange", "fit_why": "", "rights": "green", "rights_basis": "said by the channel",
             "rights_why": "", "summary": ""},
            {"id": "GAME", "fit": "red", "fit_why": "", "rights": "orange", "rights_basis": "nothing found",
             "rights_why": "", "summary": ""},
            {"id": "NOT_ASKED", "fit": "green", "rights": "green", "rights_basis": "known reputation"}]}

    monkeypatch.setattr(ne, "_ask", ask)
    return yt, asked


def test_a_run(run):
    yt, asked = run
    out = ne.explore("@TheSynapseCut", "@joerogan", "KEY")
    assert out["mine"]["title"] == "The Synapse Cut" and out["cached"] is False
    assert out["link"]["id"] == "JRE" and out["link"]["fit"] == "green", "the link is rated on its own"
    names = [n["name"] for n in out["niches"]]
    assert names == ["Science", "Combat", "Gaming"], "the niches that fit first"
    by = {n["name"]: [c["id"] for c in n["channels"]] for n in out["niches"]}
    assert by == {"Science": ["SCI"], "Combat": ["MMA"], "Gaming": ["GAME"]}, \
        "her channel and the link never come back as a source; a channel goes to the first niche that finds it"
    sci = out["niches"][0]["channels"][0]
    assert sci["rights"] == "green" and sci["overall"] == "green" and sci["evidence"][0]["quote"].startswith("Clips welcome")
    mma = out["niches"][1]["channels"][0]
    assert mma["rights"] == "orange", "« said by the channel » with nothing quoted is not a green"
    assert out["niches"][2]["channels"][0]["overall"] == "red"
    assert yt.calls.count("search") == 3 and len(asked) == 2
    assert "Her channel: The Synapse Cut" in asked[0] and "The link (a show): PowerfulJRE" in asked[0]


def test_a_run_is_kept_and_costs_nothing_the_second_time(run):
    yt, asked = run
    first = ne.explore("@TheSynapseCut", "@joerogan", "KEY")
    n_calls = len(yt.calls)
    again = ne.explore("@thesynapsecut ", "@JoeRogan", "KEY")
    assert again["cached"] is True and len(yt.calls) == n_calls and len(asked) == 2
    assert again["niches"] == first["niches"]
    assert ne.history()[0]["link"] == "@joerogan" and ne.history()[0]["green"] == 1
    ne.explore("@TheSynapseCut", "@joerogan", "KEY", refresh=True)
    assert len(yt.calls) > n_calls, "refresh asks YouTube again"


def test_nothing_given_or_not_found(run):
    with pytest.raises(ValueError):
        ne.explore("", " ", "KEY")
    with pytest.raises(LookupError):
        ne.explore("@nobody", "", "KEY")
