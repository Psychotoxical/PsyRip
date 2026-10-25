
import pytest

from psyrip import analysis, utilities
from psyrip.converter import ConvertSettings, OutputSpec
from psyrip.tags import read_info, read_tags, write_tags


@pytest.fixture()
def mp3(tmp_path):
    p = tmp_path / "in.mp3"
    analysis.run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=5", "-ac", "2", str(p)], check=True)
    write_tags(p, {"artist": "Blur", "album": "Parklife", "title": "Girls & Boys", "tracknumber": "2"})
    return p


def test_audio_info_and_crc(mp3):
    assert "Blur" in utilities.audio_info([mp3])
    assert "\t" in utilities.audio_info([mp3], table=True)
    c = utilities.audio_crc([mp3])[str(mp3)]
    assert len(c["md5"]) == 32 and len(c["crc32"]) == 8


def test_arrange(mp3, tmp_path):
    root = tmp_path / "lib"
    moves = utilities.arrange_audio([mp3], root, "[artist]\\[album]\\[track] [title]")
    assert moves and (root / "Blur" / "Parklife" / "02 Girls & Boys.mp3").exists()
    assert not mp3.exists()


def test_tag_from_filename(tmp_path):
    p = tmp_path / "4 Madonna - Holiday.mp3"
    analysis.run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=1", str(p)], check=True)
    t = utilities.tag_from_filename(p, "[track] [artist] - [title]")
    assert t == {"tracknumber": "4", "artist": "Madonna", "title": "Holiday"}
    assert read_tags(p)["artist"] == "Madonna"


def test_length_and_channel_split(mp3, tmp_path):
    outs = utilities.length_split(mp3, tmp_path / "s", 2.0, encoder="FLAC")
    assert len(outs) == 3 and abs(read_info(outs[0]).length - 2.0) < 0.1
    ch = utilities.channel_split(mp3, tmp_path / "c", "FLAC", descriptive=True)
    assert [c.name for c in ch] == ["in_Left.flac", "in_Right.flac"]
    assert read_info(ch[0]).channels == 1


def test_multi_encoder(mp3, tmp_path):
    cfgs = [ConvertSettings(encoder=e, output=OutputSpec("folder", str(tmp_path / e)), workers=1) for e in ("FLAC", "Opus")]
    res = utilities.multi_encode([mp3], cfgs)
    assert all(r[0].status == "ok" for r in res)
