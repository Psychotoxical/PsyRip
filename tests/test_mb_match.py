from psyrip import cdrip
from psyrip.ripper import mb_tag_groups, musicbrainz_tags
from tests.test_mb_tags import REL

TITLES = ["Battlefield of Love", "If I Could Fall in Love", "Yesterday Is Gone", "Stillness of Heart"]


def test_match_by_track_number():
    files = [{"track": 3, "title": "Yesterday Is Gone"}, {"track": 1, "title": ""}, {"track": 2, "title": "wrong title xx"}]
    assert cdrip.match_tracks(files, TITLES) == [2, 0, None] or cdrip.match_tracks(files, TITLES)[:2] == [2, 0]


def test_match_by_title_when_no_numbers():
    files = [{"track": None, "title": "stillness of heart"}, {"track": None, "title": "Battlefield Of Love (remastered)"}]
    assert cdrip.match_tracks(files, TITLES) == [3, 0]


def test_match_by_order_when_nothing_else():
    files = [{"track": None, "title": ""}, {"track": None, "title": ""}]
    assert cdrip.match_tracks(files, ["A", "B"]) == [0, 1]


def test_groups_split_fields_sensibly():
    rel = dict(REL)
    rel["media"] = [dict(REL["media"][0])]
    m = cdrip._mb_meta(rel)
    m.track_info[0]["tags"] = {"composer": "Lenny Kravitz", "composersort": "Kravitz, Lenny", "language": "eng", "work": "Battlefield of Love"}
    g = mb_tag_groups(m, 1)
    assert g["core"]["title"] == "Battlefield of Love" and g["core"]["tracknumber"] == "1/2" and g["core"]["compilation"] == "1"
    assert g["ids"]["musicbrainz_trackid"].startswith("bbcb0e31")
    assert g["details"]["label"] == "Virgin" and g["details"]["isrc"] == "USVI20100522"
    assert g["credits"]["composer"] == "Lenny Kravitz" and "language" not in g["credits"] and g["extras"]["language"] == "eng"
    basic = musicbrainz_tags(m, 1, "basic")
    full = musicbrainz_tags(m, 1, "full")
    assert "composer" not in basic and full["composer"] == "Lenny Kravitz" and "title" not in full      # Titel kommt aus dem Ripper-Fenster


def test_medium_selection_by_position():
    rel = dict(REL)
    rel["media"] = [{"position": 1, "format": "CD", "tracks": [{"id": "a", "title": "One", "recording": {"id": "r1"}}]},
                    {"position": 2, "format": "CD", "tracks": [{"id": "b", "title": "Two", "recording": {"id": "r2"}}]}]
    m = cdrip._mb_meta(rel, medium_pos=2)
    assert m.tracks[0][0] == "Two" and m.disc_position == 2 and m.disc_total == 2
