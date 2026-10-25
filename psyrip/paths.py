"""Plattformabhängige Ordner: Konfiguration und Musik-Ordner (Windows bzw. Linux/XDG)."""
from __future__ import annotations

import os
import re
from pathlib import Path

WINDOWS = os.name == "nt"


def config_dir() -> Path:
    """Windows: %APPDATA%\\psyrip – Linux: $XDG_CONFIG_HOME/psyrip (Standard ~/.config/psyrip)."""
    if WINDOWS:
        return Path(os.environ.get("APPDATA", Path.home())) / "psyrip"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "psyrip"


def _xdg_user_dir(name: str) -> str | None:
    """Liest XDG_<NAME>_DIR aus ~/.config/user-dirs.dirs (z. B. lokalisiert „Musik“)."""
    f = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "user-dirs.dirs"
    try:
        m = re.search(rf'^XDG_{name}_DIR="([^"]*)"', f.read_text(encoding="utf-8"), re.M)
    except OSError:
        return None
    if not m:
        return None
    p = m.group(1).replace("$HOME", str(Path.home()))
    return p if p.rstrip("/") != str(Path.home()) else None    # auf $HOME gesetzt = Ordner deaktiviert


def music_folder() -> str:
    """Musik-Ordner des Benutzers (Windows: berücksichtigt Umleitungen, z. B. nach OneDrive; Linux: XDG)."""
    if WINDOWS:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 13, None, 0, buf) == 0 and buf.value:   # CSIDL_MYMUSIC
                return buf.value
        except (AttributeError, OSError):
            pass
    else:
        p = _xdg_user_dir("MUSIC")
        if p:
            return p
    return str(Path.home() / "Music")
