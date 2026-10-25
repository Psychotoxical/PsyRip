import pytest

from psyrip import analysis, cdrip
from psyrip.converter import ConvertSettings, Converter, OutputSpec
from psyrip.encoders import ENCODERS
from psyrip.ripper import RipJob, build_tags, musicbrainz_tags
from psyrip.tags import read_tags

REL = {
    "id": "00372afe-dfa1-4ddd-b1dd-087c1c47acae", "title": "Lenny", "date": "2001-05-29", "country": "US", "status": "Official",
    "barcode": "724381123324", "asin": "B00005QCNW",
    "artist-credit": [{"name": "Lenny Kravitz", "joinphrase": "", "artist": {"id": "0ef3f425-9bd2-4216-9dd2-219d2fe90f1f"}}],
    "release-group": {"id": "f69a6eb0-e9df-3660-889f-05c9ff0033dc", "primary-type": "Album", "secondary-types": ["Compilation"],
                      "first-release-date": "2001-01-01"},
    "label-info": [{"catalog-number": "7243 8 11233 2 4", "label": {"name": "Virgin"}}],
    "media": [{"format": "CD", "discs": [{"id": "Gci7CgZbRoU45MsbonG5sDPMK_c-"}], "tracks": [
        {"id": "b7ca85d1-3b97-3f05-9bd9-bc53d3e01047", "title": "Battlefield of Love",
         "recording": {"id": "bbcb0e31-064e-4fe2-a285-3f311e00ec6c", "isrcs": ["USVI20100522"]}},
        {"id": "86393c80-60aa-3141-9336-aece840190c8", "title": "If I Could Fall in Love",
         "recording": {"id": "72cffbbc-5da2-417b-9378-5ec2ae9f4725", "isrcs": []}}]}],
}


def test_release_json_parsing():
    m = cdrip._mb_meta(REL, disc_id="Gci7CgZbRoU45MsbonG5sDPMK_c-")
    assert m.release_type == "album; compilation" and m.status == "official" and m.country == "US"
    assert m.label == "Virgin" and m.catalog == "7243 8 11233 2 4" and m.barcode == "724381123324" and m.media_format == "CD"
    assert m.original_date == "2001-01-01" and m.release_group_id.startswith("f69a6eb0")
    assert m.artist_ids == ["0ef3f425-9bd2-4216-9dd2-219d2fe90f1f"]
    assert m.track_info[0]["isrc"] == "USVI20100522" and m.track_info[1]["isrc"] == ""
    assert m.track_info[1]["artist_ids"] == m.artist_ids                      # Track ohne eigenen Credit erbt den Album-Artist


def test_build_tags_contains_mb_ids_per_track():
    m = cdrip._mb_meta(REL)
    t2 = musicbrainz_tags(m, 2)
    assert t2["musicbrainz_albumid"] == REL["id"] and t2["musicbrainz_trackid"].startswith("72cffbbc") and "isrc" not in t2
    from tests.test_cdrip import make_toc
    d = cdrip.parse_toc_bytes(make_toc([(0, 2, 0), (3, 40, 12)], (7, 0, 0)))
    job = RipJob("G", d, [1], m, {}, ConvertSettings(), cdrip.RipOptions())
    assert build_tags(job, 1)["releasetype"] == "album; compilation"
    job.write_mb_tags = False
    assert "musicbrainz_albumid" not in build_tags(job, 1)


@pytest.mark.parametrize("enc", [n for n, e in ENCODERS.items() if e.available and n not in ("Windows Media Audio", "Speex")])
def test_mb_tags_roundtrip_in_all_formats(tmp_path, enc):
    src = tmp_path / "in.flac"
    analysis.run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=1", str(src)], check=True)
    m = cdrip._mb_meta(REL)
    tags = {"artist": "A", "title": "T", **musicbrainz_tags(m, 1)}
    c = Converter(ConvertSettings(encoder=enc, workers=1, output=OutputSpec("folder", str(tmp_path / "o"))))
    c.tags_map[src] = tags
    r = c.run([src])[0]
    assert r.status == "ok", r.message
    got = read_tags(r.dst)
    for key in ("musicbrainz_albumid", "musicbrainz_releasegroupid", "musicbrainz_trackid", "musicbrainz_releasetrackid",
                "musicbrainz_albumartistid", "releasetype", "label", "barcode", "catalognumber", "isrc"):
        assert key in got, (enc, key, sorted(got))
    assert got["musicbrainz_albumid"] == REL["id"] and got["releasetype"] == "album; compilation"
