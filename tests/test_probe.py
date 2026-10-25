"""Dauer/Format ohne ffprobe (der Installer liefert nur ffmpeg mit)."""
import shutil
import wave

import pytest

from psyrip import analysis

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg fehlt")


def test_probe_with_ffmpeg_only(tmp_path):
    p = tmp_path / "x.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\0\0\0\0" * 44100 * 3)          # 3 s Stille
    fmt = analysis._probe_with_ffmpeg(p)["format"]
    assert abs(float(fmt["duration"]) - 3.0) < 0.05
    assert fmt["format_name"] == "wav"
