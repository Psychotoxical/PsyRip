"""Letzte Einstellungen (Naming, Ausgabeordner, Encoder, Profil) überleben einen Neustart."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from psyrip import settings as cfgmod


@pytest.fixture
def cfgdir(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "APPDATA", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(cfgmod, "PROFILES", tmp_path / "profiles")
    return tmp_path


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


NAMING = r"[IFVALUE]album artist,[album artist],[artist][] - ([GRAB]1,4,[year][]) - [album]\[track] - [artist] - [title]"


def test_missing_saved_folder_falls_back_to_music(cfgdir, app, tmp_path, monkeypatch):
    from psyrip import cdrip
    from psyrip.gui.cdripper_win import CDRipperWindow
    monkeypatch.setattr(cdrip, "list_cd_drives", lambda: [])
    assert cfgmod.output_folder(str(tmp_path)) == str(tmp_path)
    assert cfgmod.output_folder(str(tmp_path / "weg")) == cfgmod.music_folder()
    cfgmod.update(None, rip_folder=str(tmp_path / "weg"))
    w = CDRipperWindow(cfgmod.load())
    assert w.out.spec().folder == cfgmod.music_folder()
    w.close()
    # Musik-Ordner wird als "" gespeichert – auf einem anderen Rechner zeigt das auf dessen Musik-Ordner
    cfg = cfgmod.load()
    assert cfg["last_rip"]["convert"]["output"]["folder"] == ""
    assert cfgmod.portable_folder(cfgmod.music_folder()) == "" and cfgmod.portable_folder(str(tmp_path)) == str(tmp_path)


def test_update_keeps_keys_written_by_other_windows(cfgdir):
    stale = cfgmod.load()                         # z. B. Control Center, früh geladen
    cfgmod.update(None, last_rip={"x": 1})        # anderes Fenster speichert
    cfgmod.update(stale, theme="dark")            # Control Center speichert nur seinen Schlüssel
    cfg = cfgmod.load()
    assert cfg["theme"] == "dark" and cfg["last_rip"] == {"x": 1}


def test_converter_restores_last_state(cfgdir, app, tmp_path):
    from psyrip.gui.converter_win import ConverterWindow
    (tmp_path / "out").mkdir()
    w = ConverterWindow(None, cfgmod.load())
    w.enc.set("Opus", {})
    w.out.naming.setText(NAMING)
    w.out.folder.setText(str(tmp_path / "out"))
    w.out.r_dynamic.setChecked(True)
    cfgmod.save_profile("Mein Profil", w.current_settings())
    w._reload_profiles()
    w.profile.setCurrentText("Mein Profil")
    w.close()

    w2 = ConverterWindow(None, cfgmod.load())     # „Neustart“
    s = w2.current_settings()
    assert s.encoder == "Opus" and s.output.naming == NAMING and s.output.folder == str(tmp_path / "out")
    assert s.output.mode == "dynamic" and w2.profile.currentText() == "Mein Profil"
    w2.close()


@pytest.mark.parametrize("enabled", [True, False])
def test_ripper_reads_disc_on_open(cfgdir, app, monkeypatch, enabled):
    from psyrip import cdrip
    from psyrip.gui.cdripper_win import CDRipperWindow
    monkeypatch.setattr(cdrip, "list_cd_drives", lambda: ["Z:"])
    calls = []
    monkeypatch.setattr(CDRipperWindow, "read_disc", lambda self, quiet=False: calls.append(quiet))
    cfgmod.update(None, auto_read_disc=enabled)
    w = CDRipperWindow(cfgmod.load())
    app.processEvents()
    assert calls == ([True] if enabled else [])
    w.close()


def test_auto_read_without_disc_shows_hint_not_dialog(cfgdir, app, monkeypatch):
    import time
    from psyrip import cdrip
    from psyrip.gui.cdripper_win import CDRipperWindow, QMessageBox
    monkeypatch.setattr(cdrip, "list_cd_drives", lambda: ["Z:"])
    monkeypatch.setattr(cdrip, "CDDrive", lambda letter: (_ for _ in ()).throw(OSError("kein Medium")))
    boxes = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: boxes.append(a))
    w = CDRipperWindow(cfgmod.load())
    for _ in range(50):
        app.processEvents()
        if "Z:" in w.statusBar().currentMessage() and "…" not in w.statusBar().currentMessage():
            break
        time.sleep(0.02)
    assert not boxes and "Z:" in w.statusBar().currentMessage()
    w.close()


def test_new_disc_clears_previous_album_data(cfgdir, app, monkeypatch):
    from psyrip import cdrip
    from psyrip.gui.cdripper_win import CDRipperWindow
    monkeypatch.setattr(cdrip, "list_cd_drives", lambda: [])
    cfgmod.update(None, internet=False)
    w = CDRipperWindow(cfgmod.load())
    old = cdrip.Disc([cdrip.Track(1, 0, 20000)], 20000, "Z")
    w._got_toc(old)
    w._apply_meta(cdrip.DiscMeta("Sick of Being Human", "Scornage", "2004", "Metal", [("Society Kills", "Scornage")],
                                 cover=b"x", release_type="album"))
    w.barcode.setText("123")
    new = cdrip.Disc([cdrip.Track(1, 0, 30000), cdrip.Track(2, 30000, 50000)], 50000, "Z")
    w._got_toc(new)
    assert (w.album.text(), w.artist.text(), w.year.text(), w.genre.text(), w.release_type.text()) == ("", "", "", "", "")
    assert w.metacombo.count() == 0 and w.meta.cover is None and w.table.item(0, 2).text() == "Track 01"
    assert w.barcode.text() == "123"                    # gehört schon zur neuen Disc
    # verspätete Metadaten der alten Disc werden ignoriert
    w._got_meta((old, [cdrip.DiscMeta("Sick of Being Human", "Scornage")]))
    assert w.album.text() == ""
    w.close()


def test_ripper_restores_last_state(cfgdir, app, tmp_path, monkeypatch):
    from psyrip import cdrip
    monkeypatch.setattr(cdrip, "list_cd_drives", lambda: [])
    from psyrip.gui.cdripper_win import CDRipperWindow
    (tmp_path / "rips").mkdir()
    w = CDRipperWindow(cfgmod.load())
    w.enc.set("mp3 (Lame)", {})
    w.out.naming.setText(NAMING)
    w.out.folder.setText(str(tmp_path / "rips"))
    w.passes.setValue(3)
    w.close()

    w2 = CDRipperWindow(cfgmod.load())
    assert w2.enc.encoder == "mp3 (Lame)"
    assert w2.out.spec().naming == NAMING and w2.out.spec().folder == str(tmp_path / "rips")
    assert w2.passes.value() == 3
    w2.close()
