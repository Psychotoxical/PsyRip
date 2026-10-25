from psyrip import cdrip
from tests.test_cdrip import make_toc

CDDB = """# xmcd
DISCID=a50e1a0d
DTITLE=Lenny Kravitz / Lenny
DYEAR=2001
DGENRE=Rock
TTITLE0=Battlefield of Love
TTITLE1=Various / Guest Song
TTITLE2=Long ti
TTITLE2=tle
EXTD=
PLAYORDER=
"""


def test_parse_cddb():
    m = cdrip.parse_cddb_read(CDDB, 3)
    assert (m.album, m.artist, m.year, m.genre) == ("Lenny", "Lenny Kravitz", "2001", "Rock")
    assert m.tracks == [("Battlefield of Love", "Lenny Kravitz"), ("Guest Song", "Various"), ("Long title", "Lenny Kravitz")]


def test_cddb_query_string_and_htoa():
    d = cdrip.parse_toc_bytes(make_toc([(0, 2, 0), (3, 40, 12)], (7, 0, 0)))
    q = cdrip.cddb_query_string(d)
    assert q.startswith(f"cddb query {cdrip.freedb_id(d):08x} 2 150 ")
    assert cdrip.htoa_track(d) is None
    d2 = cdrip.parse_toc_bytes(make_toc([(0, 5, 0), (3, 40, 12)], (7, 0, 0)))
    h = cdrip.htoa_track(d2)
    assert h is not None and h.number == 0 and h.end == d2.tracks[0].start


def test_meta_from_url_offline_paths():
    assert cdrip.meta_from_url("https://example.com/x") is None
    assert cdrip.meta_from_url("https://www.discogs.com/release/123-x", "") is None   # ohne Token keine Abfrage
