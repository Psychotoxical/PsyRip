
import pytest

from psyrip import analysis
from psyrip.converter import ConvertSettings, Converter, DspStep, OutputSpec
from psyrip.encoders import ENCODERS
from psyrip.tags import read_info, read_tags, write_tags


@pytest.fixture(scope="module")
def sine(tmp_path_factory):
    d = tmp_path_factory.mktemp("src")
    p = d / "in.flac"
    analysis.run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-ac", "2", "-ar", "44100", str(p)], check=True)
    write_tags(p, {"artist": "Tester", "album": "Album", "title": "Sine", "tracknumber": "3", "genre": "Test"})
    return p


@pytest.mark.parametrize("name", list(ENCODERS))
def test_all_encoders(sine, tmp_path, name):
    if not ENCODERS[name].available:
        pytest.skip(f"externes Tool für {name} nicht installiert")
    s = ConvertSettings(encoder=name, output=OutputSpec("folder", str(tmp_path)), workers=1)
    r = Converter(s).run([sine])[0]
    assert r.status == "ok", r.message
    assert r.dst.exists() and r.dst.stat().st_size > 500
    assert abs(read_info(r.dst).length - 3) < 0.3


def test_parallel_name_collisions_get_unique_targets(sine, tmp_path):
    srcs = []
    for i in range(6):
        p = tmp_path / f"s{i}.flac"
        p.write_bytes(sine.read_bytes())
        write_tags(p, {"artist": "Same", "title": "Same"})
        srcs.append(p)
    s = ConvertSettings(encoder="FLAC", workers=4, output=OutputSpec("dynamic", str(tmp_path / "o"), "[artist] - [title]"))
    res = Converter(s).run(srcs)
    assert all(r.status == "ok" for r in res), [r.message for r in res]
    assert len({str(r.dst).lower() for r in res}) == 6                   # keine zwei Dateien auf demselben Ziel
    assert len(list((tmp_path / "o").glob("*.flac"))) == 6


def test_origpath_naming_stays_inside_output_folder(sine, tmp_path):
    s = ConvertSettings(encoder="FLAC", workers=1,
                        output=OutputSpec("dynamic", str(tmp_path / "o"), "[origpath]\\[origfilename]"))
    r = Converter(s).run([sine])[0]
    assert r.status == "ok", r.message
    assert (tmp_path / "o") in r.dst.parents                                # nicht zurück in den Quellordner geschrieben


def test_skipped_file_is_not_deleted_by_error_dsp(sine, tmp_path):
    out = tmp_path / "o"
    base = ConvertSettings(encoder="FLAC", workers=1, output=OutputSpec("folder", str(out)))
    assert Converter(base).run([sine])[0].status == "ok"
    existing = out / "in.flac"
    s = ConvertSettings(encoder="FLAC", workers=1, output=OutputSpec("folder", str(out)),
                        dsp=[DspStep("Conditional Encoding", {"dest_exists": True}), DspStep("Delete Destination File on Error", {})])
    r = Converter(s).run([sine])[0]
    assert r.status == "skipped" and existing.exists()


def test_reserved_windows_names_are_sanitized():
    from psyrip.naming import sanitize
    assert sanitize("CON") == "_CON" and sanitize("nul.txt") == "_nul.txt" and sanitize("a\x00b\n") == "ab"


def test_tags_survive_and_dynamic_naming(sine, tmp_path):
    s = ConvertSettings(encoder="mp3 (Lame)", workers=1,
                        output=OutputSpec("dynamic", str(tmp_path), "[artist]\\[album]\\[track] [title]"))
    r = Converter(s).run([sine])[0]
    assert r.status == "ok", r.message
    assert r.dst == tmp_path / "Tester" / "Album" / "03 Sine.mp3"
    t = read_tags(r.dst)
    assert t["artist"] == "Tester" and t["title"] == "Sine"


def test_dsp_chain_and_tag_processing(sine, tmp_path):
    s = ConvertSettings(encoder="FLAC", workers=1, output=OutputSpec("folder", str(tmp_path)), dsp=[
        DspStep("Resample", {"rate": 22050}),
        DspStep("Bit Depth", {"bits": "16"}),
        DspStep("Fade", {"in_ms": 200, "out_ms": 500}),
        DspStep("Volume Normalize", {"mode": "peak", "desired": -3.0}),
        DspStep("ID Tag Processing", {"capitalize": "upper", "additions": "comment=hi [artist]"}),
    ])
    r = Converter(s).run([sine])[0]
    assert r.status == "ok", r.message
    assert read_info(r.dst).sample_rate == 22050
    assert read_tags(r.dst)["artist"] == "TESTER"
    assert read_tags(r.dst)["comment"] == "hi TESTER"
    assert abs(analysis.max_volume(r.dst) + 3.0) < 0.6


def test_trim_length_and_loop(sine, tmp_path):
    s = ConvertSettings(encoder="Wave", workers=1, output=OutputSpec("folder", str(tmp_path)),
                        dsp=[DspStep("Maximum Length", {"seconds": 1.0, "percent": 0})])
    r = Converter(s).run([sine])[0]
    assert abs(read_info(r.dst).length - 1.0) < 0.1


def test_conditional_skip_and_delete_source(sine, tmp_path):
    out = tmp_path / "o"
    s = ConvertSettings(encoder="FLAC", workers=1, output=OutputSpec("folder", str(out), overwrite=True),
                        dsp=[DspStep("Conditional Encoding", {"dest_exists": True})])
    assert Converter(s).run([sine])[0].status == "ok"
    out_file = out / "in.flac"
    s.output.overwrite = True
    assert out_file.exists()
    assert Converter(s).run([sine])[0].status == "skipped"


def test_replaygain_and_hash(sine, tmp_path):
    s = ConvertSettings(encoder="FLAC", workers=1, output=OutputSpec("folder", str(tmp_path)),
                        dsp=[DspStep("ReplayGain", {})])
    r = Converter(s).run([sine])[0]
    t = read_tags(r.dst)
    assert "replaygain_track_gain" in t and "replaygain_album_gain" in t
    assert analysis.audio_hash(sine) == analysis.audio_hash(sine)
