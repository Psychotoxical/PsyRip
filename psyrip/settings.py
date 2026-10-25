"""Persistente Einstellungen und Profile (JSON in %APPDATA%\\psyrip bzw. ~/.config/psyrip)."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict
from pathlib import Path

from .converter import ConvertSettings, DspStep, OutputSpec
from .paths import config_dir, music_folder

def output_folder(saved: str | None) -> str:
    """Gespeicherter Ausgabeordner, falls er noch existiert – sonst (auch bei "" = Standard) der Musik-Ordner."""
    return saved if saved and Path(saved).is_dir() else music_folder()


def portable_folder(folder: str) -> str:
    """Zum Speichern: Der Musik-Ordner wird als "" (Standard) abgelegt, damit die Konfiguration auf
    einem anderen Rechner/Benutzer auf dessen eigenen Musik-Ordner zeigt statt auf einen festen Pfad."""
    try:
        same = bool(folder) and Path(folder).resolve() == Path(music_folder()).resolve()
    except OSError:
        same = False
    return "" if same else folder


APPDATA = config_dir()
CONFIG = APPDATA / "config.json"
PROFILES = APPDATA / "profiles"

# rip_folder "" = Musik-Ordner des jeweiligen Benutzers (siehe output_folder/portable_folder)
DEFAULTS = {
    "ffmpeg": "", "tools": {}, "rip_profiles": {}, "discogs_token": "", "write_mb_tags": True, "cover_source": "auto", "cover_size": 1500, "itunes_country": "us", "internet": True, "workers": max(1, (os.cpu_count() or 2) - 1), "low_priority": False, "auto_read_disc": True,
    "rip_naming": "[IFVALUE]album artist,[album artist],[IFCOMP]Various Artists[][IF!COMP][artist][][]\\[album]\\[track] [artist] - [title]",
    "rip_folder": "", "rip_encoder": "FLAC", "rip_secure": True, "rip_passes": 2,
    "rip_rereads": 20, "rip_offset": 0, "last_drive": "", "language": "en", "theme": "auto", "hidden_encoders": [],
    "default_tag_fields": ["artist", "album", "title", "albumartist", "tracknumber", "discnumber", "genre", "date", "composer", "comment"],
}


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)            # tiefe Kopie: verschachtelte Einträge (tools, rip_profiles) dürfen DEFAULTS nicht verändern
    try:
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg: dict) -> None:
    APPDATA.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def update(cfg: dict | None = None, **changes) -> None:
    """Schreibt nur die genannten Schlüssel: Die Datei wird frisch gelesen, damit ein Fenster mit älterem
    Konfigurationsstand nicht überschreibt, was ein anderes Fenster inzwischen gespeichert hat."""
    if cfg is not None:
        cfg.update(changes)
    fresh = load()
    fresh.update(copy.deepcopy(changes))
    save(fresh)


def settings_to_dict(s: ConvertSettings) -> dict:
    return asdict(s)


def settings_from_dict(d: dict) -> ConvertSettings:
    d = dict(d)
    out = OutputSpec(**d.pop("output", {}))
    dsp = [DspStep(**x) for x in d.pop("dsp", [])]
    return ConvertSettings(output=out, dsp=dsp, **d)


def save_profile(name: str, s: ConvertSettings) -> None:
    PROFILES.mkdir(parents=True, exist_ok=True)
    (PROFILES / f"{name}.json").write_text(json.dumps(settings_to_dict(s), indent=2), encoding="utf-8")


def load_profile(name: str) -> ConvertSettings:
    return settings_from_dict(json.loads((PROFILES / f"{name}.json").read_text(encoding="utf-8")))


def list_profiles() -> list[str]:
    return sorted(p.stem for p in PROFILES.glob("*.json")) if PROFILES.exists() else []


def delete_profile(name: str) -> None:
    (PROFILES / f"{name}.json").unlink(missing_ok=True)
