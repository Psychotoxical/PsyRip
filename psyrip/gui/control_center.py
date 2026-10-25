"""Control Center: Startfenster, Codec-/DSP-Übersicht, Internet, erweiterte Einstellungen, Explorer-Integration."""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

from PySide6.QtCore import QProcess, QSize, Qt

from ..i18n import LANGUAGES, language as i18n_language, set_language, tr
from PySide6.QtWidgets import (QHeaderView, QFrame, QStackedWidget, QApplication, QCheckBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QComboBox)

from .. import __version__, analysis, dsp as dspmod, encoders
from .. import settings as cfgmod
from ..encoders import DECODER_EXTS, ENCODERS
from . import theme
from .batch_win import BatchWindow
from .cdripper_win import CDRipperWindow
from .converter_win import ConverterWindow
from .utilities_win import UtilitiesWindow

VERB = "psyrip.convert"
EXTS = [".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aif", ".aiff", ".wv", ".ape", ".wma"]


def _cmd(arg: str) -> str:
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):                      # PyInstaller-EXE: psyrip.exe selbst aufrufen
        return f'"{exe}" {arg} "%1"'
    py = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
    return f'"{py}" -m psyrip {arg} "%1"'


def register_shell() -> None:
    for ext in EXTS:
        for verb, label, arg in ((VERB, "Convert To (psyrip)", "convert"), ("psyrip.tags", "Edit ID-Tags (psyrip)", "tags")):
            base = rf"Software\Classes\SystemFileAssociations\{ext}\shell\{verb}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, label)
                icon = Path(__file__).resolve().parent.parent / "assets" / "psyrip.ico"
                if icon.exists():
                    winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, str(icon))
                winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\command") as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _cmd(arg))


def unregister_shell() -> None:
    for ext in EXTS:
        for verb in (VERB, "psyrip.tags"):
            base = rf"Software\Classes\SystemFileAssociations\{ext}\shell\{verb}"
            for sub in (r"\command", ""):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + sub)
                except OSError:
                    pass


class Card(QFrame):
    """Klickbare Kachel mit Symbol, Titel und Beschreibung."""

    def __init__(self, glyph: str, title: str, text: str, on_click):
        super().__init__()
        self.setObjectName("card")
        self.on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(120)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(16)
        ic = QLabel(glyph)
        ic.setObjectName("cardIcon")
        ic.setFixedWidth(52)
        ic.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        col = QVBoxLayout()
        t = QLabel(title)
        t.setObjectName("cardTitle")
        d = QLabel(text)
        d.setObjectName("cardText")
        d.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(d)
        col.addStretch()
        row.addWidget(ic)
        row.addLayout(col, 1)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.on_click()


class ControlCenter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = cfgmod.load()
        if self.cfg["ffmpeg"]:
            analysis.set_ffmpeg(self.cfg["ffmpeg"])
        encoders.TOOL_PATHS.update({k: v for k, v in self.cfg["tools"].items() if v})
        self.setWindowTitle("psyrip Control Center")
        self.resize(1020, 660)
        self.wins: list[QWidget] = []
        root = QWidget(objectName="page")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        side = QWidget(objectName="side")
        side.setFixedWidth(210)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)
        self.nav = QListWidget(objectName="nav")
        self.nav.setFocusPolicy(Qt.NoFocus)
        sv.addWidget(self.nav, 1)
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("themeBtn")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.clicked.connect(self._cycle_theme)
        sv.addWidget(self.theme_btn)
        self._update_theme_btn()
        lay.addWidget(side)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        pages = [("", tr("Start"), self._launcher()), ("", tr("Audio-Codecs"), self._codecs()),
                 ("", tr("Einstellungen"), self._settings()), ("", tr("Windows-Integration"), self._integration())]
        for glyph, name, page in pages:
            it = QListWidgetItem(f"{glyph}   {name}")
            it.setData(Qt.UserRole + 1, glyph)
            self.nav.addItem(it)
            self.stack.addWidget(self._page(name, page))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.statusBar().showMessage(self._ffmpeg_status())

    _THEMES = (("auto", "Automatisch"), ("light", "Hell"), ("dark", "Dunkel"))

    def _update_theme_btn(self):
        mode = self.cfg.get("theme", "auto")
        label = next(t[1] for t in self._THEMES if t[0] == mode)
        self.theme_btn.setIcon(theme.mode_icon(mode))
        self.theme_btn.setIconSize(QSize(18, 18))
        self.theme_btn.setText(f"  {tr(label)}")
        self.theme_btn.setToolTip(tr("Design wechseln: Automatisch → Hell → Dunkel") + "\n" + tr("Automatisch (wie Windows)") + " / "
                                  + tr("Hell") + " / " + tr("Dunkel"))

    def _cycle_theme(self):
        order = [t[0] for t in self._THEMES]
        mode = order[(order.index(self.cfg.get("theme", "auto")) + 1) % len(order)]
        cfgmod.update(self.cfg, theme=mode)
        theme.apply(QApplication.instance(), mode)
        self._update_theme_btn()
        if hasattr(self, "theme"):                           # Auswahlfeld in den Einstellungen mitführen
            self.theme.setCurrentIndex(max(self.theme.findData(mode), 0))

    def _page(self, title: str, body: QWidget) -> QWidget:
        w = QWidget(objectName="page")
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 22, 28, 18)
        v.setSpacing(6)
        h = QLabel(title)
        h.setObjectName("header")
        v.addWidget(h)
        if title == tr("Start"):
            s = QLabel(tr("Audio konvertieren, rippen und taggen  ·  Version {0}").format(__version__))
            s.setObjectName("sub")
            v.addWidget(s)
        v.addWidget(body, 1)
        return w

    def _ffmpeg_status(self) -> str:
        try:
            return f"ffmpeg: {analysis.ffmpeg_path()}"
        except FileNotFoundError as e:
            return str(e)

    def _launcher(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 14, 0, 0)
        g.setSpacing(16)
        items = [("", "Music Converter", tr("Dateien konvertieren mit DSP-Effekten und dynamischen Dateinamen"), lambda: self._open(ConverterWindow(None, self.cfg))),
                 ("", "CD Ripper", tr("Audio-CDs sicher rippen, AccurateRip-Prüfung, Metadaten und Cover"), lambda: self._open(CDRipperWindow(self.cfg))),
                 ("", "Batch Converter", tr("Ganze Ordner samt Unterordnern mit einem Klick umwandeln"), lambda: self._open(BatchWindow(self.cfg))),
                 ("", "ID-Tag-Editor", tr("Tags und Cover mehrerer Dateien gemeinsam bearbeiten"), self._tags),
                 ("", "Utility Codecs", tr("Audio Info, CRC, Arrange, Split, ReplayGain und mehr"), lambda: self._open(UtilitiesWindow(None, self.cfg)))]
        for i, (glyph, t, d, f) in enumerate(items):
            g.addWidget(Card(glyph, t, d, f), i // 2, i % 2)
        g.setRowStretch(3, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        return w

    def _open(self, win: QWidget):
        win.show()
        self.wins.append(win)

    def _tags(self):
        from ..tags import AUDIO_EXT
        from .tag_editor import TagEditor
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Dateien"), "", "Audio (" + " ".join("*" + e for e in sorted(AUDIO_EXT)) + ")")
        if fs:
            TagEditor([Path(f) for f in fs], self.cfg, self).exec()

    def _codecs(self) -> QWidget:
        t = QTableWidget(0, 4)
        t.setHorizontalHeaderLabels(["Encoder", tr("Erweiterung"), tr("Typ"), tr("Cover-Unterstützung")])
        t.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for n, e in ENCODERS.items():
            r = t.rowCount()
            t.insertRow(r)
            for c, v in enumerate((n, e.ext, tr("verlustfrei") if e.lossless else tr("verlustbehaftet"), tr("ja") if e.supports_art else tr("nein"))):
                t.setItem(r, c, QTableWidgetItem(v))
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        t.setShowGrid(False)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.verticalHeader().hide()
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(t, 2)
        v.addWidget(QLabel("Decoder: " + " ".join(DECODER_EXTS)))
        dl = QLabel(tr("DSP / Aktionen: ") + ", ".join(sum(dspmod.list_by_category().values(), [])))
        dl.setWordWrap(True)
        v.addWidget(dl)
        return w

    def _settings(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.ff = QLineEdit(self.cfg["ffmpeg"])
        fb = QPushButton("…")
        fb.clicked.connect(lambda: self.ff.setText(QFileDialog.getOpenFileName(self, "ffmpeg.exe", "", "ffmpeg (ffmpeg.exe)")[0] or self.ff.text()))
        row = QHBoxLayout()
        row.addWidget(self.ff)
        row.addWidget(fb)
        f.addRow(tr("ffmpeg-Pfad (leer = automatisch)"), row)
        self.tool_edits: dict[str, QLineEdit] = {}
        for tool, what in (("fdkaac", "m4a FDK (AAC)"), ("mppenc", "Musepack"), ("mac", "Monkey's Audio"), ("sox", "DSD")):
            e = QLineEdit(self.cfg["tools"].get(tool, ""))
            e.setPlaceholderText(encoders.find_tool(tool) or tr("nicht gefunden"))
            b = QPushButton("…")
            b.clicked.connect(lambda _=False, e=e, t=tool: e.setText(QFileDialog.getOpenFileName(self, t, "", tr("Programm (*.exe)"))[0] or e.text()))
            r = QHBoxLayout()
            r.addWidget(e)
            r.addWidget(b)
            self.tool_edits[tool] = e
            f.addRow(tr("Externes Tool {0} ({1})").format(tool, what), r)
        self.discogs = QLineEdit(self.cfg.get("discogs_token", ""))
        self.discogs.setPlaceholderText(tr("optional – Token von discogs.com/settings/developers"))
        f.addRow("Discogs-Token", self.discogs)
        self.net = QCheckBox(tr("Internetzugriff erlauben (AccurateRip, Metadaten)"))
        self.net.setChecked(bool(self.cfg["internet"]))
        self.workers = QSpinBox()
        self.workers.setRange(1, 64)
        self.workers.setValue(int(self.cfg["workers"]))
        self.cover_source = QComboBox()
        for label, code in ((tr("Automatisch – größtes Cover aus beiden Quellen"), "auto"), (tr("Apple Music (iTunes)"), "apple"),
                            (tr("MusicBrainz (Cover Art Archive)"), "caa")):
            self.cover_source.addItem(label, code)
        self.cover_source.setCurrentIndex(max(self.cover_source.findData(self.cfg.get("cover_source", "auto")), 0))
        self.cover_size = QComboBox()
        for px in (500, 1000, 1500, 2000, 3000):
            self.cover_size.addItem(f"{px} × {px}", px)
        self.cover_size.setCurrentIndex(max(self.cover_size.findData(int(self.cfg.get("cover_size", 1500))), 0))
        self.itunes_country = QLineEdit(self.cfg.get("itunes_country", "us"))
        self.itunes_country.setMaxLength(2)
        self.itunes_country.setFixedWidth(60)
        f.addRow(tr("Cover-Quelle"), self.cover_source)
        f.addRow(tr("Maximale Cover-Größe"), self.cover_size)
        f.addRow(tr("Apple-Store-Land (2 Buchstaben)"), self.itunes_country)
        self.lang = QComboBox()
        for code, label in LANGUAGES.items():
            self.lang.addItem(label, code)
        self.lang.setCurrentIndex(max(self.lang.findData(i18n_language()), 0))
        f.addRow("Sprache / Language" if i18n_language() == "de" else "Language", self.lang)
        self.theme = QComboBox()
        for label, code in ((tr("Automatisch (wie Windows)"), "auto"), (tr("Hell"), "light"), (tr("Dunkel"), "dark")):
            self.theme.addItem(label, code)
        self.theme.setCurrentIndex(max(self.theme.findData(self.cfg["theme"]), 0))
        self.fields = QLineEdit(", ".join(self.cfg["default_tag_fields"]))
        self.hidden = QListWidget()
        for n in ENCODERS:
            it = QListWidgetItem(n)
            it.setCheckState(Qt.Checked if n in self.cfg["hidden_encoders"] else Qt.Unchecked)
            self.hidden.addItem(it)
        self.hidden.setMaximumHeight(120)
        f.addRow(self.net)
        self.auto_read = QCheckBox(tr("CD beim Öffnen des Rippers automatisch einlesen und Metadaten laden"))
        self.auto_read.setChecked(bool(self.cfg.get("auto_read_disc", True)))
        f.addRow(self.auto_read)
        f.addRow(tr("Standard-Kerne"), self.workers)
        f.addRow(tr("Design"), self.theme)
        f.addRow(tr("Standard-Tag-Felder"), self.fields)
        f.addRow(tr("Encoder ausblenden"), self.hidden)
        b = QPushButton(tr("Speichern"))
        b.setObjectName("primary")
        b.clicked.connect(self._save)
        f.addRow(b)
        return w

    def _save(self):
        tools = {k: e.text().strip() for k, e in self.tool_edits.items() if e.text().strip()}
        encoders.TOOL_PATHS.clear()
        encoders.TOOL_PATHS.update(tools)
        cfgmod.update(self.cfg, tools=tools, cover_source=self.cover_source.currentData(), cover_size=self.cover_size.currentData(),
                      itunes_country=(self.itunes_country.text().strip().lower() or "us"), discogs_token=self.discogs.text().strip(), ffmpeg=self.ff.text().strip(), internet=self.net.isChecked(), auto_read_disc=self.auto_read.isChecked(), workers=self.workers.value(), theme=self.theme.currentData(),
                      default_tag_fields=[x.strip() for x in self.fields.text().split(",") if x.strip()],
                      hidden_encoders=[self.hidden.item(i).text() for i in range(self.hidden.count()) if self.hidden.item(i).checkState() == Qt.Checked])
        analysis.set_ffmpeg(self.cfg["ffmpeg"] or None)
        theme.apply(QApplication.instance(), self.cfg["theme"])
        new_lang = self.lang.currentData()
        if new_lang != i18n_language():
            cfgmod.update(self.cfg, language=new_lang)
            set_language(new_lang)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle("psyrip")
            box.setText(tr("Die Sprache wird nach einem Neustart von psyrip vollständig übernommen."))
            restart = box.addButton(tr("Jetzt neu starten"), QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Close)
            box.exec()
            if box.clickedButton() is restart:
                self._restart()
        self.statusBar().showMessage(tr("Gespeichert. ") + self._ffmpeg_status())

    def _restart(self):
        """Startet psyrip neu (EXE oder `python -m psyrip`) und beendet die aktuelle Instanz."""
        if getattr(sys, "frozen", False):
            QProcess.startDetached(sys.executable, [])
        else:
            QProcess.startDetached(sys.executable, ["-m", "psyrip"])
        QApplication.quit()

    def _integration(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(tr("Fügt dem Explorer-Kontextmenü (nur für den aktuellen Benutzer, Registry HKCU) die Einträge\n"
                           "„Convert To (psyrip)“ und „Edit ID-Tags (psyrip)“ für Audiodateien hinzu.\n"
                           "Unter Windows 11 erscheinen sie unter „Weitere Optionen anzeigen“.")))
        a, r = QPushButton(tr("Einträge installieren")), QPushButton(tr("Einträge entfernen"))
        a.clicked.connect(lambda: (register_shell(), self.statusBar().showMessage(tr("Kontextmenü installiert."))))
        r.clicked.connect(lambda: (unregister_shell(), self.statusBar().showMessage(tr("Kontextmenü entfernt."))))
        v.addWidget(a)
        v.addWidget(r)
        v.addStretch()
        return w
