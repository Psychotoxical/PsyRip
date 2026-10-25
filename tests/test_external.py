import pytest

from psyrip import analysis, encoders
from psyrip.converter import ConvertSettings, Converter, OutputSpec
from psyrip.encoders import ENCODERS, Encoder, Option
from psyrip.tags import read_info, read_tags, write_tags


@pytest.fixture()
def fake_external():
    """ffmpeg dient als 'externes' Programm: liest WAV von stdin, schreibt die Zieldatei."""
    encoders.TOOL_PATHS["fakeenc"] = analysis.ffmpeg_path()
    ENCODERS["Fake External"] = Encoder(
        "Fake External", ".mp3", False, [], [Option("q", "Qualität", "choice", [("5", "5")], "5")],
        external=("fakeenc", '-hide_banner -loglevel error -f wav -i - -y "{out}"'), builder=lambda s: [], args_after=False)
    yield
    ENCODERS.pop("Fake External")
    encoders.TOOL_PATHS.pop("fakeenc")


def test_external_encoder_pipeline(tmp_path, fake_external):
    src = tmp_path / "in.flac"
    analysis.run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=2", "-ac", "2", str(src)], check=True)
    write_tags(src, {"artist": "X", "title": "Y"})
    s = ConvertSettings(encoder="Fake External", workers=1, output=OutputSpec("folder", str(tmp_path / "o")))
    r = Converter(s).run([src])[0]
    assert r.status == "ok", r.message
    assert abs(read_info(r.dst).length - 2) < 0.2
    assert read_tags(r.dst)["artist"] == "X"


def test_missing_tool_reports_clearly(tmp_path):
    src = tmp_path / "in.flac"
    analysis.run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=1", str(src)], check=True)
    encoders.TOOL_PATHS.pop("mac", None)
    if ENCODERS["Monkeys Audio"].available:
        pytest.skip("mac ist installiert")
    s = ConvertSettings(encoder="Monkeys Audio", workers=1, output=OutputSpec("folder", str(tmp_path / "o")))
    r = Converter(s).run([src])[0]
    assert r.status == "error" and "mac" in r.message


def test_m4b_native(tmp_path):
    src = tmp_path / "in.flac"
    analysis.run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=2", str(src)], check=True)
    s = ConvertSettings(encoder="m4b (Audio Book)", workers=1, output=OutputSpec("folder", str(tmp_path / "o")))
    r = Converter(s).run([src])[0]
    assert r.status == "ok", r.message
    assert r.dst.suffix == ".m4b"


def test_command_templates():
    exe = analysis.ffmpeg_path()          # existierende Datei als Platzhalter für die Tools
    for t in ("sox", "mac", "mppenc", "fdkaac"):
        encoders.TOOL_PATHS[t] = exe
    try:
        dsd = ENCODERS["DSD"].external_command({"mode": "5644800"}, "C:\\o\\x.dsf")
        assert dsd[1:] == ["-t", "wav", "-", "--no-glob", "-t", "dsf", "C:\\o\\x.dsf", "rate", "-v", "5644800", "sdm"]
        ape = ENCODERS["Monkeys Audio"].external_command({"c": "-c4000"}, "o.ape")
        assert ape[1:] == ["-", "o.ape", "-c4000"]
        aac = ENCODERS["m4a FDK (AAC)"].external_command({"mode": "-b 128000", "profile": "-p 2"}, "o.m4a")
        assert aac[1:] == ["-b", "128000", "-p", "2", "--ignorelength", "-S", "-o", "o.m4a", "-"]
        mpc = ENCODERS["Musepack"].external_command({"profile": "--quality 10"}, "o.mpc")
        assert mpc[1:] == ["--quality", "10", "--overwrite", "-", "o.mpc"]
    finally:
        for t in ("sox", "mac", "mppenc", "fdkaac"):
            encoders.TOOL_PATHS.pop(t, None)
