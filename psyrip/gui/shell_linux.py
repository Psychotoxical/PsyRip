"""Desktop-Integration unter Linux (statt Explorer-Registry): Startmenü-Eintrag, „Öffnen mit“ für Audiodateien
und ein Dolphin-Kontextmenü (KDE-Servicemenü). Alles nur für den aktuellen Benutzer unter ~/.local/share."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

MIME = ["audio/mpeg", "audio/flac", "audio/x-flac", "audio/mp4", "audio/x-m4a", "audio/ogg", "audio/x-vorbis+ogg",
        "audio/opus", "audio/x-opus+ogg", "audio/wav", "audio/x-wav", "audio/x-aiff", "audio/x-wavpack", "audio/x-ape",
        "audio/x-ms-wma", "audio/x-musepack"]

_DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
APPS = _DATA / "applications"
SERVICEMENU = _DATA / "kio" / "servicemenus" / "psyrip.desktop"
FILES = [APPS / "psyrip.desktop", APPS / "psyrip-convert.desktop", APPS / "psyrip-tags.desktop", SERVICEMENU]

_ROOT = Path(__file__).resolve().parent.parent.parent
_ICON = Path(__file__).resolve().parent.parent / "assets" / "psyrip.png"


def _exec(arg: str = "") -> str:
    """Befehlszeile für Exec=: EXE (PyInstaller) oder der aktuelle Python-Interpreter mit -m psyrip."""
    if getattr(sys, "frozen", False):
        base = f'"{sys.executable}"'
    else:
        base = f'"{sys.executable}" -m psyrip'
    return f"{base} {arg}".rstrip()


def _entry(name: str, arg: str, files: bool, hidden: bool = False, comment: str = "") -> str:
    lines = ["[Desktop Entry]", "Type=Application", f"Name={name}", f"Exec={_exec(arg)}{' %F' if files else ''}",
             f"Icon={_ICON}", "Terminal=false", "Categories=AudioVideo;Audio;", "StartupWMClass=psyrip"]
    if not getattr(sys, "frozen", False):
        lines.append(f"Path={_ROOT}")                       # Start aus dem Quellcode: Projektordner als Arbeitsverzeichnis
    if comment:
        lines.append(f"Comment={comment}")
    if files:
        lines.append("MimeType=" + ";".join(MIME) + ";")
    if hidden:
        lines.append("NoDisplay=true")
    return "\n".join(lines) + "\n"


def _servicemenu() -> str:
    cd = f'cd "{_ROOT}" && ' if not getattr(sys, "frozen", False) else ""
    def action(key, label, arg):
        return [f"[Desktop Action {key}]", f"Name={label}", f"Icon={_ICON}", f"Exec=sh -c '{cd}exec {_exec(arg)} \"$@\"' psyrip %F", ""]
    return "\n".join(["[Desktop Entry]", "Type=Service", "MimeType=" + ";".join(MIME) + ";", "Actions=convert;tags;",
                      "X-KDE-Submenu=psyrip", "X-KDE-Priority=TopLevel", "",
                      *action("convert", "Convert To (psyrip)", "convert"), *action("tags", "Edit ID-Tags (psyrip)", "tags")])


def _refresh() -> None:
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(APPS)], capture_output=True)
    if shutil.which("kbuildsycoca6"):
        subprocess.run(["kbuildsycoca6"], capture_output=True)


def register_shell() -> None:
    APPS.mkdir(parents=True, exist_ok=True)
    SERVICEMENU.parent.mkdir(parents=True, exist_ok=True)
    (APPS / "psyrip.desktop").write_text(_entry("psyrip", "", False, comment="Audio-Toolkit"), encoding="utf-8")
    (APPS / "psyrip-convert.desktop").write_text(_entry("Convert To (psyrip)", "convert", True, hidden=True), encoding="utf-8")
    (APPS / "psyrip-tags.desktop").write_text(_entry("Edit ID-Tags (psyrip)", "tags", True, hidden=True), encoding="utf-8")
    SERVICEMENU.write_text(_servicemenu(), encoding="utf-8")
    SERVICEMENU.chmod(0o755)                                 # KDE führt Servicemenüs nur aus, wenn sie ausführbar sind
    _refresh()


def unregister_shell() -> None:
    for f in FILES:
        f.unlink(missing_ok=True)
    _refresh()
