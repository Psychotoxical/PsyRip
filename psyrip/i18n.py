"""Sprachumschaltung. Englisch ist die Standardsprache, Deutsch die zweite Sprache.

Im Quelltext steht der deutsche Text; ``tr()`` liefert ihn unverändert (Deutsch) oder den englischen Katalogeintrag.
Die Sprache steht in ``%APPDATA%\\psyrip\\config.json`` bzw. ``~/.config/psyrip/config.json`` ("language": "en" | "de"); ``PSYRIP_LANG`` überschreibt sie.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .translations import EN

LANGUAGES = {"en": "English", "de": "Deutsch"}
_lang: str | None = None


def _config_path() -> Path:
    from .paths import config_dir
    return config_dir() / "config.json"


def language() -> str:
    global _lang
    if _lang is None:
        code = os.environ.get("PSYRIP_LANG", "")
        if code not in LANGUAGES:
            try:
                code = json.loads(_config_path().read_text(encoding="utf-8")).get("language", "en")
            except (OSError, ValueError):
                code = "en"
        _lang = code if code in LANGUAGES else "en"
    return _lang


def set_language(code: str) -> None:
    global _lang
    _lang = code if code in LANGUAGES else "en"


def tr(text: str) -> str:
    """Übersetzt einen (deutschen) Quelltext in die aktive Sprache."""
    if language() == "de":
        return text
    return EN.get(text, text)


def install_qt_translator(app) -> None:
    """Lädt bei Deutsch die Qt-eigenen Übersetzungen (Standard-Buttons, Datei-Dialoge)."""
    if language() != "de":
        return
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    for name in ("qtbase", "qt"):
        t = QTranslator(app)
        if t.load(QLocale("de"), name, "_", path):
            app.installTranslator(t)
