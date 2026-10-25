import io

import pytest
from PIL import Image

from psyrip import analysis
from psyrip.converter import ConvertSettings, Converter, DspStep, OutputSpec
from psyrip.tags import read_art, read_info, read_tags, resize_art, write_art, write_tags


@pytest.fixture()
def flac(tmp_path):
    p = tmp_path / "in.flac"
    analysis.run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=2", "-ac", "1", str(p)], check=True)
    write_tags(p, {"artist": "A", "title": "T", "album": "Al"})
    im = Image.new("RGB", (1200, 1200), (200, 30, 30))
    b = io.BytesIO()
    im.save(b, "PNG")
    write_art(p, b.getvalue())
    return p


def run(flac, tmp_path, *dsps, enc="FLAC"):
    s = ConvertSettings(encoder=enc, workers=1, output=OutputSpec("folder", str(tmp_path / "o")), dsp=list(dsps))
    return Converter(s).run([flac])[0]


def test_resize_art_png_to_jpg_and_px():
    b = io.BytesIO()
    Image.new("RGB", (1000, 500), "blue").save(b, "PNG")
    out = resize_art(b.getvalue(), 400, 0, True)
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG" and max(im.size) == 400


def test_id_tag_processing_art_and_hash(flac, tmp_path):
    r = run(flac, tmp_path, DspStep("ID Tag Processing", {"max_art_px": 300, "force_jpg": True, "export_art": True, "audio_hash": True}))
    assert r.status == "ok", r.message
    art = Image.open(io.BytesIO(read_art(r.dst)))
    assert art.format == "JPEG" and max(art.size) == 300
    assert (r.dst.parent / "Folder.jpg").exists()
    assert len(read_tags(r.dst)["audio_md5"]) == 32


def test_loop_to_length_and_channel_min(flac, tmp_path):
    r = run(flac, tmp_path, DspStep("Loop", {"to_length": 5.0}), DspStep("Channel Count", {"channels": 0, "min": 2}))
    assert r.status == "ok", r.message
    info = read_info(r.dst)
    assert abs(info.length - 5.0) < 0.2 and info.channels == 2


def test_conditional_copy_by_rate(flac, tmp_path):
    r = run(flac, tmp_path, DspStep("Conditional Encoding", {"dest_exists": False, "rate_le": 48000, "action": "skip"}))
    assert r.status == "skipped"


from psyrip.encoders import ENCODERS  # noqa: E402


@pytest.mark.parametrize("enc", [n for n, e in ENCODERS.items() if e.available])
def test_cover_survives_conversion(flac, tmp_path, enc):
    assert ENCODERS[enc].supports_art
    r = run(flac, tmp_path, enc=enc)
    assert r.status == "ok", r.message
    art = read_art(r.dst)
    assert art and Image.open(io.BytesIO(art)).size == (1200, 1200)


def test_opus_sample_rate_reported(flac, tmp_path):
    r = run(flac, tmp_path, enc="Opus")
    assert read_info(r.dst).sample_rate == 48000


def test_error_map_triggers_delete_on_error(flac, tmp_path):
    s = ConvertSettings(encoder="FLAC", workers=1, output=OutputSpec("folder", str(tmp_path / "o")),
                        dsp=[DspStep("Delete Destination File on Error", {})])
    c = Converter(s)
    c.error_map[flac] = "Rip unsicher"
    r = c.run([flac])[0]
    assert r.status == "error" and "unsicher" in r.message
    assert not r.dst.exists()


def test_build_tags_offset_and_htoa():
    from psyrip import cdrip
    from psyrip.ripper import RipJob, build_tags
    from tests.test_cdrip import make_toc
    d = cdrip.parse_toc_bytes(make_toc([(0, 5, 0), (3, 40, 12)], (7, 0, 0)))
    job = RipJob("G", d, [0], cdrip.DiscMeta("Alb", "Art"), {}, ConvertSettings(), cdrip.RipOptions(), track_offset=100)
    t = build_tags(job, 0)
    assert t["title"] == "Hidden Track One Audio" and t["tracknumber"].startswith("100/")


def test_metadata_file_xslt_roundtrip(flac, tmp_path):
    xsl = tmp_path / "t.xsl"
    xsl.write_text('<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"><xsl:output method="text"/>'
                   '<xsl:template match="/"><xsl:for-each select="//tag"><xsl:value-of select="@name"/>=<xsl:value-of select="."/>;</xsl:for-each></xsl:template></xsl:stylesheet>')
    r = run(flac, tmp_path, DspStep("Write Metadata File", {"xslt": str(xsl), "ext": ".txt"}))
    assert "artist=A;" in r.dst.with_suffix(".txt").read_text()
    r2 = run(flac, tmp_path, DspStep("Write Metadata File", {}))
    assert r2.dst.with_suffix(".xml").exists()
