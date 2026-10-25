import struct

from psyrip import cdrip


def make_toc(starts_msf, leadout_msf, ctrl=0x00):
    ents = b""
    for n, (m, s, f) in enumerate(starts_msf, 1):
        ents += bytes([0, 0x10 | ctrl, n, 0, 0, m, s, f])
    ents += bytes([0, 0x10, 0xAA, 0, 0, *leadout_msf])
    body = bytes([1, len(starts_msf)]) + ents
    return struct.pack(">H", len(body)) + body


def test_toc_parse_and_ids():
    toc = make_toc([(0, 2, 0), (3, 40, 12), (7, 21, 45)], (11, 5, 30))
    d = cdrip.parse_toc_bytes(toc, "G")
    assert [t.number for t in d.tracks] == [1, 2, 3]
    assert d.tracks[0].start == 0
    assert d.tracks[1].start == (3 * 60 + 40) * 75 + 12 - 150
    assert d.tracks[-1].end == d.leadout == (11 * 60 + 5) * 75 + 30 - 150
    fid = cdrip.freedb_id(d)
    assert fid & 0xFF == 3
    mb = cdrip.musicbrainz_disc_id(d)
    assert len(mb) == 28 and mb.endswith("-")
    id1, id2, cddb = cdrip.accuraterip_ids(d)
    assert cddb == fid
    assert cdrip.accuraterip_url(d).endswith(f"dBAR-003-{id1:08x}-{id2:08x}-{cddb:08x}.bin")


def test_data_track_flagged():
    toc = make_toc([(0, 2, 0)], (3, 0, 0), ctrl=0x04)
    assert not cdrip.parse_toc_bytes(toc).tracks[0].audio


def test_accuraterip_crc_edges():
    pcm = struct.pack("<II", 1, 2) * (588 * 12)
    v1, v2 = cdrip.accuraterip_crc(pcm, True, True)
    v1b, v2b = cdrip.accuraterip_crc(pcm, False, False)
    assert v1 != v1b            # Anfang/Ende wird bei erstem/letztem Track ausgelassen
    assert cdrip.verify_track(None, 0, v1, v2) == "Not in database"
    assert cdrip.verify_track([[(5, v1, 0)]], 0, v1, v2) == "Accurate (5)"
    assert cdrip.verify_track([[(5, 1234, 0)]], 0, v1, v2) == "Inaccurate"
