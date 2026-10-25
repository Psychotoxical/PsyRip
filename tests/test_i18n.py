import ast
import glob
import re

import pytest

from psyrip import i18n
from psyrip.translations import EN


@pytest.fixture(autouse=True)
def restore_language():
    old = i18n._lang
    yield
    i18n._lang = old


def used_keys():
    keys = set()
    for p in glob.glob("psyrip/**/*.py", recursive=True):
        if p.endswith(("translations.py", "i18n.py")):
            continue
        for n in ast.walk(ast.parse(open(p, encoding="utf-8").read())):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "tr" and n.args and isinstance(n.args[0], ast.Constant):
                keys.add((p, n.args[0].value))
    return keys


def test_every_tr_key_has_english_entry():
    missing = [(p, k) for p, k in used_keys() if k not in EN]
    assert not missing, missing


def test_placeholders_match():
    pat = re.compile(r"\{\d+[^}]*\}")
    bad = [k for k, v in EN.items() if sorted(pat.findall(k)) != sorted(pat.findall(v))]
    assert not bad, bad


def test_language_switch():
    i18n.set_language("en")
    assert i18n.tr("Speichern") == "Save"
    assert i18n.tr("{0} Dateien").format(3) == "{0} files".format(3)
    i18n.set_language("de")
    assert i18n.tr("Speichern") == "Speichern"
    i18n.set_language("xx")                      # unbekannt -> Englisch
    assert i18n.language() == "en"


def test_no_german_left_in_english_catalog():
    german = re.compile(r"[äöüß]|\b(Datei|Fehler|nicht|werden|für|oder)\b")
    bad = [v for v in EN.values() if german.search(v)]
    assert not bad, bad


def test_english_ui_strings_in_core(monkeypatch):
    i18n.set_language("en")
    from psyrip.encoders import ENCODERS
    enc = ENCODERS["mp3 (Lame)"]
    assert enc.options[0].label == "Mode"
