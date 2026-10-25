"""ffmpeg-basierte Analysen: Lautheit (EBU R128), Spitzenpegel, CRC/MD5 des dekodierten Audios."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_ffmpeg_override: str | None = None


def set_ffmpeg(path: str | None) -> None:
    global _ffmpeg_override
    _ffmpeg_override = path


def bundled_bin() -> list[Path]:
    """Mitgelieferter bin-Ordner: neben psyrip.exe (Installer/PyInstaller) bzw. im Projektordner."""
    out = []
    if getattr(sys, "frozen", False):
        out.append(Path(sys.executable).resolve().parent / "bin")
    out.append(Path(__file__).resolve().parent.parent / "bin")
    return out


def ffmpeg_path() -> str:
    """Reihenfolge: Pfad aus den Einstellungen → mitgeliefertes ffmpeg → PATH."""
    if _ffmpeg_override and Path(_ffmpeg_override).exists():
        return _ffmpeg_override
    for d in bundled_bin():
        if (d / "ffmpeg.exe").exists():
            return str(d / "ffmpeg.exe")
    found = shutil.which("ffmpeg")
    if not found:
        from .i18n import tr
        raise FileNotFoundError(tr("ffmpeg nicht gefunden – im Control Center den Pfad setzen oder ffmpeg in PATH legen."))
    return found


def run_ffmpeg(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run([ffmpeg_path(), "-hide_banner", "-nostdin", *args], capture_output=True,
                          creationflags=NO_WINDOW, **kw)


def loudness(path: str | Path, true_peak: bool = True) -> dict[str, float]:
    """Integrierte Lautheit (LUFS), LRA und True Peak (dBTP)."""
    p = run_ffmpeg(["-i", str(path), "-vn", "-af", "ebur128=peak=true" if true_peak else "ebur128", "-f", "null", "-"])
    err = p.stderr.decode("utf-8", "replace")
    tail = err[err.rfind("Summary:"):] if "Summary:" in err else err
    def grab(pat):
        m = re.search(pat, tail)
        return float(m.group(1)) if m else float("nan")
    return {"lufs": grab(r"I:\s+(-?[\d.]+)\s+LUFS"), "lra": grab(r"LRA:\s+(-?[\d.]+)\s+LU"),
            "true_peak": grab(r"Peak:\s+(-?[\d.]+)\s+dBFS")}


def max_volume(path: str | Path) -> float:
    """Höchster Pegel in dBFS (volumedetect)."""
    p = run_ffmpeg(["-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"max_volume:\s+(-?[\d.]+) dB", p.stderr.decode("utf-8", "replace"))
    return float(m.group(1)) if m else 0.0


def replaygain(path: str | Path, ref_lufs: float = -18.0) -> dict[str, str]:
    l = loudness(path)
    gain = ref_lufs - l["lufs"]
    peak_lin = 10 ** (l["true_peak"] / 20) if l["true_peak"] == l["true_peak"] else 1.0
    return {"replaygain_track_gain": f"{gain:+.2f} dB", "replaygain_track_peak": f"{peak_lin:.6f}",
            "replaygain_reference_loudness": f"{ref_lufs:.1f} LUFS"}


def audio_hash(path: str | Path, algo: str = "md5") -> str:
    """Hash des dekodierten PCM-Streams (ändert sich nicht bei Tag-Änderungen)."""
    name = {"md5": "MD5", "crc32": "CRC32", "sha256": "SHA256"}[algo]
    p = run_ffmpeg(["-i", str(path), "-vn", "-map", "0:a:0", "-f", "hash", "-hash", name, "-"])
    m = re.search(rf"{name}=([0-9a-fA-F]+)", p.stdout.decode("utf-8", "replace"))
    if not m:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[-400:])
    return m.group(1).lower()


def probe(path: str | Path) -> dict:
    """ffprobe-JSON; ohne ffprobe (der Installer liefert nur ffmpeg mit) Dauer und Format aus `ffmpeg -i`."""
    exe = Path(ffmpeg_path())
    probe_exe = exe.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not probe_exe.exists():
        found = shutil.which("ffprobe")
        if not found:
            return _probe_with_ffmpeg(path)
        probe_exe = Path(found)
    p = subprocess.run([str(probe_exe), "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, creationflags=NO_WINDOW)
    try:
        return json.loads(p.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return {}


def _probe_with_ffmpeg(path: str | Path) -> dict:
    p = run_ffmpeg(["-i", str(path)])                 # ohne Ausgabedatei: ffmpeg beendet sich nach der Analyse
    err = p.stderr.decode("utf-8", "replace")
    fmt: dict[str, str] = {}
    if m := re.search(r"Input #0, ([^,]+(?:,[^,\s]+)*), from", err):
        fmt["format_name"] = fmt["format_long_name"] = m.group(1)
    if m := re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err):
        fmt["duration"] = str(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)))
    return {"format": fmt} if fmt else {}


def crc32_file(path: str | Path) -> int:
    c = 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            c = zlib.crc32(chunk, c)
    return c & 0xFFFFFFFF
