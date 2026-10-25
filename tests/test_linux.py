"""Linux-Portierung: Pfade, Naming-Ordnertrenner, SG_IO-Laufwerk (simuliert), Desktop-Integration, GUI-Teile."""
import ctypes
import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from psyrip import analysis, cdrip, paths
from psyrip.converter import ConvertSettings, Converter, OutputSpec, _relative

linux_only = pytest.mark.skipif(os.name == "nt", reason="nur Linux/Unix")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ Naming → Pfad
@pytest.mark.parametrize("rel, want", [
    ("Artist\\Album\\01 Title.flac", ("Artist", "Album", "01 Title.flac")),
    ("Artist/Album/01 Title.flac", ("Artist", "Album", "01 Title.flac")),
    ("C:\\Music\\..\\x.mp3", ("Music", "x.mp3")),
    ("\\\\Artist\\\\.\\x.mp3", ("Artist", "x.mp3")),
    ("/home/user/Music/x.mp3", ("home", "user", "Music", "x.mp3")),
])
def test_relative_splits_on_both_separators(rel, want):
    assert _relative(rel).parts == want


def test_relative_empty():
    assert _relative("..\\.") == Path()


@pytest.fixture()
def sine(tmp_path):
    p = tmp_path / "src" / "in.flac"
    p.parent.mkdir()
    analysis.run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=1", str(p)], check=True)
    from psyrip.tags import write_tags
    write_tags(p, {"artist": "A", "album": "B", "title": "T", "tracknumber": "1"})
    return p


def test_preserve_mode_stays_inside_output_folder(sine, tmp_path):
    out = tmp_path / "out"
    s = ConvertSettings(encoder="FLAC", workers=1, output=OutputSpec("preserve", str(out)))
    r = Converter(s).run([sine])[0]
    assert r.status == "ok", r.message
    assert out in r.dst.parents and r.dst.exists()


@linux_only
def test_low_priority_uses_nice(sine, tmp_path, monkeypatch):
    calls = []
    real = os.setpriority
    monkeypatch.setattr(os, "setpriority", lambda which, pid, prio: (calls.append(prio), real(which, pid, prio)))
    s = ConvertSettings(encoder="FLAC", workers=1, low_priority=True, output=OutputSpec("folder", str(tmp_path / "o")))
    assert Converter(s).run([sine])[0].status == "ok"
    assert calls == [10]


@linux_only
def test_normal_priority_leaves_nice_alone(sine, tmp_path, monkeypatch):
    monkeypatch.setattr(os, "setpriority", lambda *a: pytest.fail("setpriority ohne low_priority"))
    s = ConvertSettings(encoder="FLAC", workers=1, output=OutputSpec("folder", str(tmp_path / "o")))
    assert Converter(s).run([sine])[0].status == "ok"


# ------------------------------------------------------------------ Pfade
@linux_only
def test_config_dir_follows_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert paths.config_dir() == tmp_path / "psyrip"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert paths.config_dir() == Path.home() / ".config" / "psyrip"


@linux_only
def test_i18n_reads_language_from_config_dir(tmp_path, monkeypatch):
    from psyrip import i18n
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert i18n._config_path() == tmp_path / "psyrip" / "config.json"


@linux_only
@pytest.mark.parametrize("line, want", [
    ('XDG_MUSIC_DIR="$HOME/Musik"', "{home}/Musik"),
    ('XDG_MUSIC_DIR="/data/music"', "/data/music"),
    ('XDG_MUSIC_DIR="$HOME/"', "{home}/Music"),         # auf $HOME gesetzt = deaktiviert → Standard
    ("# kein Eintrag", "{home}/Music"),
])
def test_music_folder_from_user_dirs(tmp_path, monkeypatch, line, want):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "user-dirs.dirs").write_text(f'XDG_DESKTOP_DIR="$HOME/Desktop"\n{line}\n', encoding="utf-8")
    assert paths.music_folder() == want.format(home=Path.home())


@linux_only
def test_music_folder_without_user_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert paths.music_folder() == str(Path.home() / "Music")


@linux_only
def test_bundled_ffmpeg_without_exe_suffix(tmp_path, monkeypatch):
    ff = tmp_path / "ffmpeg"
    ff.write_text("#!/bin/sh\n")
    monkeypatch.setattr(analysis, "bundled_bin", lambda: [tmp_path])
    monkeypatch.setattr(analysis, "_ffmpeg_override", None)
    assert analysis.ffmpeg_path() == str(ff)


# ------------------------------------------------------------------ SG_IO-Laufwerk (simuliert)
class FakeSg:
    """Ersetzt _scsi: protokolliert CDBs und liefert passende Antworten."""

    def __init__(self, toc=b"", fail=(), short=False):
        self.cdbs, self.toc, self.fail, self.short = [], toc, set(fail), short

    def __call__(self, cdb, outsize, timeout_ms=30000):
        self.cdbs.append(bytes(cdb))
        if cdb[0] in self.fail:
            raise OSError(5, "simulierter SCSI-Fehler")
        if cdb[0] == 0x43:
            return self.toc[:outsize]
        if cdb[0] == 0xBE:
            lba, n = struct.unpack(">i", cdb[2:6])[0], int.from_bytes(cdb[6:9], "big")
            data = b"".join((lba + i).to_bytes(4, "big", signed=True) * (cdrip.SECTOR // 4) for i in range(n))
            return data[:-4] if self.short else data
        return b""


def _drive(fake):
    d = object.__new__(cdrip._LinuxCDDrive)
    d.letter, d.fd = "/dev/srX", None
    d._scsi = fake
    return d


def test_linux_read_toc_cdb_and_parse():
    from tests.test_cdrip import make_toc
    toc = make_toc([(0, 2, 0), (3, 40, 12)], (7, 0, 0))
    fake = FakeSg(toc=toc)
    disc = _drive(fake).read_toc()
    cdb = fake.cdbs[0]
    assert len(cdb) == 10 and cdb[0] == 0x43 and cdb[1] == 0x02 and cdb[2] == 0      # MSF, Format 0
    assert struct.unpack(">H", cdb[7:9])[0] == 804
    assert [t.number for t in disc.tracks] == [1, 2] and disc.drive == "/dev/srX"


def test_linux_read_sectors_splits_and_builds_read_cd():
    fake = FakeSg()
    data = _drive(fake).read_sectors(1000, 60)
    assert len(data) == 60 * cdrip.SECTOR
    assert [int.from_bytes(c[6:9], "big") for c in fake.cdbs] == [26, 26, 8]
    assert [struct.unpack(">i", c[2:6])[0] for c in fake.cdbs] == [1000, 1026, 1052]
    for c in fake.cdbs:
        assert len(c) == 12 and c[0] == 0xBE and c[1] == 0x04 and c[9] == 0x10 and c[10] == 0
    # Reihenfolge der Sektoren bleibt erhalten
    assert data[59 * cdrip.SECTOR:59 * cdrip.SECTOR + 4] == (1059).to_bytes(4, "big")


def test_linux_read_sectors_short_data_is_error():
    with pytest.raises(OSError):
        _drive(FakeSg(short=True)).read_sectors(0, 3)


def test_linux_read_error_feeds_safe_read():
    """Ein SCSI-Fehler kommt als OSError an – _safe_read macht daraus Stille + defekte Sektoren."""
    fake = FakeSg(fail={0xBE})
    failed = set()
    disc = cdrip.Disc([cdrip.Track(1, 0, 100)], 100)
    out = cdrip._safe_read(_drive(fake), 10, 3, disc, failed)
    assert out == b"\0" * 3 * cdrip.SECTOR and failed == {10, 11, 12}


def test_linux_set_max_speed_ignores_errors():
    fake = FakeSg(fail={0xBB})
    _drive(fake).set_max_speed()
    cdb = fake.cdbs[0]
    assert len(cdb) == 12 and cdb[0] == 0xBB and cdb[2:6] == b"\xff\xff\xff\xff"


def test_linux_eject_uses_scsi(monkeypatch):
    import fcntl
    monkeypatch.setattr(fcntl, "ioctl", lambda *a: pytest.fail("ioctl nicht nötig, wenn SCSI klappt"))
    fake = FakeSg()
    _drive(fake).eject()
    assert fake.cdbs == [bytes([0x1E, 0, 0, 0, 0, 0]), bytes([0x1B, 0, 0, 0, 0x02, 0])]


def test_linux_eject_falls_back_to_ioctl(monkeypatch):
    import fcntl
    calls = []
    monkeypatch.setattr(fcntl, "ioctl", lambda fd, req, *a: calls.append(req))
    _drive(FakeSg(fail={0x1E})).eject()
    assert calls == [cdrip.CDROM_LOCKDOOR, cdrip.CDROMEJECT]


@linux_only
def test_scsi_error_decodes_sense(monkeypatch):
    """_scsi selbst: Status/Sense aus sg_io_hdr auswerten (fcntl.ioctl simuliert den Kernel)."""
    import fcntl

    def ioctl(fd, req, h):
        assert req == cdrip.SG_IO and h.interface_id == ord("S")
        sense = bytes([0x70, 0, 0x03, 0, 0, 0, 0, 10, 0, 0, 0, 0, 0x11, 0x05]) + bytes(18)
        ctypes.memmove(h.sbp, sense, len(sense))
        h.status, h.sb_len_wr = 2, len(sense)              # CHECK CONDITION, Medium-Fehler 3/11/05
    monkeypatch.setattr(fcntl, "ioctl", ioctl)
    d = object.__new__(cdrip._LinuxCDDrive)
    d.fd = -1
    with pytest.raises(OSError, match="BE.*3/11/05"):
        d.read_sectors(0, 1)


@linux_only
def test_scsi_respects_resid(monkeypatch):
    import fcntl

    def ioctl(fd, req, h):
        ctypes.memmove(h.dxferp, b"\x00\x0a\x01\x01", 4)
        h.resid = h.dxfer_len - 4
    monkeypatch.setattr(fcntl, "ioctl", ioctl)
    d = object.__new__(cdrip._LinuxCDDrive)
    d.fd = -1
    assert d._scsi(b"\x43" + bytes(9), 804) == b"\x00\x0a\x01\x01"


@linux_only
def test_open_missing_device_raises_oserror():
    with pytest.raises(OSError):
        cdrip._LinuxCDDrive("/dev/psyrip-gibt-es-nicht")


@linux_only
def test_list_drives_sorted_numerically(monkeypatch):
    import glob
    monkeypatch.setattr(glob, "glob", lambda pat: ["/dev/sr10", "/dev/sr2", "/dev/sr0"])
    assert cdrip._linux_list_cd_drives() == ["/dev/sr0", "/dev/sr2", "/dev/sr10"]


@linux_only
def test_platform_dispatch():
    assert cdrip.CDDrive is cdrip._LinuxCDDrive and cdrip.list_cd_drives is cdrip._linux_list_cd_drives


def test_sg_io_hdr_layout():
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(cdrip._SgIoHdr) == 88          # x86_64/aarch64
    assert cdrip._SgIoHdr.dxferp.offset == 16


# ------------------------------------------------------------------ Desktop-Integration
@pytest.fixture()
def shell(tmp_path, monkeypatch):
    from psyrip.gui import shell_linux as s
    apps, menu = tmp_path / "applications", tmp_path / "kio" / "servicemenus" / "psyrip.desktop"
    monkeypatch.setattr(s, "APPS", apps)
    monkeypatch.setattr(s, "SERVICEMENU", menu)
    monkeypatch.setattr(s, "FILES", [apps / "psyrip.desktop", apps / "psyrip-convert.desktop", apps / "psyrip-tags.desktop", menu])
    monkeypatch.setattr(s, "_refresh", lambda: None)
    return s


def _desktop(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("["):
            k, v = line.split("=", 1)
            out.setdefault(k, v)
    return out


@linux_only
def test_register_and_unregister_shell(shell):
    shell.register_shell()
    assert all(f.exists() for f in shell.FILES)
    main = _desktop(shell.APPS / "psyrip.desktop")
    assert main["Type"] == "Application" and "-m psyrip" in main["Exec"] and "NoDisplay" not in main
    conv = _desktop(shell.APPS / "psyrip-convert.desktop")
    assert conv["Exec"].endswith("-m psyrip convert %F") and conv["NoDisplay"] == "true"
    assert "audio/flac" in conv["MimeType"].split(";") and Path(conv["Path"]).joinpath("psyrip").is_dir()
    assert Path(conv["Icon"]).is_file()
    menu = shell.SERVICEMENU.read_text(encoding="utf-8")
    assert "Type=Service" in menu and "Actions=convert;tags;" in menu and "psyrip tags" in menu
    assert os.access(shell.SERVICEMENU, os.X_OK)
    shell.unregister_shell()
    assert not any(f.exists() for f in shell.FILES)
    shell.unregister_shell()                                 # zweimal entfernen ist kein Fehler


@linux_only
def test_servicemenu_command_runs(shell, tmp_path):
    """Die Exec-Zeile des Dolphin-Menüs ist gültiges sh und reicht die Dateien als Argumente durch."""
    import shlex
    import subprocess
    shell.register_shell()
    line = next(l for l in shell.SERVICEMENU.read_text().splitlines() if l.startswith("Exec=") and " convert " in l)
    argv = shlex.split(line[5:].replace("%F", ""))
    argv[2] = argv[2].replace("-m psyrip convert", "-c 'import sys; print(sys.argv[1:])'")
    out = subprocess.run([*argv, "a b.flac", "c.mp3"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "['a b.flac', 'c.mp3']"


@linux_only
def test_control_center_dispatches_to_linux(monkeypatch, app):
    from psyrip.gui import control_center, shell_linux
    calls = []
    monkeypatch.setattr(shell_linux, "register_shell", lambda: calls.append("reg"))
    monkeypatch.setattr(shell_linux, "unregister_shell", lambda: calls.append("unreg"))
    control_center.register_shell()
    control_center.unregister_shell()
    assert calls == ["reg", "unreg"]


@linux_only
def test_no_windows_icon_glyphs_on_linux():
    from psyrip.gui.control_center import _GLYPHS, _glyph
    for g in _GLYPHS:
        assert not 0xE000 <= ord(_glyph(g)) <= 0xF8FF


# ------------------------------------------------------------------ GUI
@linux_only
def test_theme_without_winreg(app):
    from psyrip.gui import theme
    assert isinstance(theme.is_dark_system(), bool)
    theme.set_app_id()
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.desktopFileName() == "psyrip"


@pytest.fixture()
def ripper(app, monkeypatch, tmp_path):
    from psyrip import settings as cfgmod
    from psyrip.gui.cdripper_win import CDRipperWindow
    monkeypatch.setattr(cfgmod, "APPDATA", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(cfgmod, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(cdrip, "list_cd_drives", lambda: ["/dev/srX"])
    cfg = cfgmod.load()
    cfg["auto_read_disc"] = False
    return CDRipperWindow(cfg)


def _wait(app, cond, timeout=5.0):
    import time
    t = time.monotonic()
    while not cond() and time.monotonic() - t < timeout:
        app.processEvents()
        time.sleep(0.01)
    return cond()


@linux_only
def test_gui_eject_runs_in_background(ripper, app, monkeypatch):
    import threading
    started, release, done = threading.Event(), threading.Event(), []

    class Drive:
        def __init__(self, dev):
            assert dev == "/dev/srX"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def eject(self):
            started.set()
            release.wait(5)
            done.append(True)
    monkeypatch.setattr(cdrip, "CDDrive", Drive)
    ripper._eject()                                          # darf nicht blockieren, während das Laufwerk arbeitet
    assert started.wait(5) and not done
    release.set()
    assert _wait(app, lambda: done)


@linux_only
def test_gui_eject_error_shows_status(ripper, app, monkeypatch):
    def boom(dev):
        raise OSError(16, "Device or resource busy")
    monkeypatch.setattr(cdrip, "CDDrive", boom)
    ripper._eject()
    assert _wait(app, lambda: "busy" in ripper.statusBar().currentMessage())


@linux_only
def test_gui_shutdown_after_rip_uses_systemd_syntax(ripper, monkeypatch):
    import subprocess
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    ripper.after.setCurrentIndex(ripper.after.findData("shutdown"))
    ripper._finished([cdrip.RipResult(track=1, pcm_path=Path("x.wav"))])
    assert calls and calls[0][:3] == ["shutdown", "-h", "+1"]
