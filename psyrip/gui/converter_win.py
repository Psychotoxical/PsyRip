"""Music Converter: Dateiliste, Encoder, Output To, DSP-Kette, Fortschritt, Profile."""
from __future__ import annotations

from ..i18n import tr
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
                               QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter, QTabWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import settings as cfgmod
from ..converter import ConvertSettings, Converter, Result
from ..tags import AUDIO_EXT, read_info
from .widgets import DspPanel, EncoderPanel, OutputPanel

COLS = [tr("Datei"), tr("Länge"), "kbps", "Status"]


class Worker(QObject):
    progress = Signal(int, float)
    result = Signal(int, object)
    finished = Signal(list)

    def __init__(self, settings: ConvertSettings, files: list[Path], tags_map=None, art_map=None):
        super().__init__()
        self.conv = Converter(settings, lambda i, f: self.progress.emit(i, f), lambda i, r: self.result.emit(i, r))
        self.conv.tags_map, self.conv.art_map = tags_map or {}, art_map or {}
        self.files = files

    def run(self):
        self.finished.emit(self.conv.run(self.files))


def collect_audio(paths: list[str], recursive: bool = True) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            out += sorted(f for f in it if f.is_file() and f.suffix.lower() in AUDIO_EXT)
        elif p.suffix.lower() in AUDIO_EXT:
            out.append(p)
    return out


class ConverterWindow(QMainWindow):
    def __init__(self, files: list[Path] | None = None, config: dict | None = None):
        super().__init__()
        self.cfg = config or cfgmod.load()
        self.setWindowTitle("psyrip Music Converter")
        self.resize(980, 640)
        self.setAcceptDrops(True)
        self.files: list[Path] = []
        self.thread: QThread | None = None
        root = QWidget(objectName="page")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)
        hdr = QLabel("Music Converter")
        hdr.setObjectName("header")
        lay.addWidget(hdr)
        body = QSplitter(Qt.Horizontal)
        lay.addWidget(body, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 330)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        ll.addWidget(self.table, 1)
        row = QHBoxLayout()
        for t, f in ((tr("Dateien…"), self.add_files), (tr("Ordner…"), self.add_folder), (tr("Entfernen"), self.remove_sel), (tr("Leeren"), self.clear)):
            b = QPushButton(t)
            b.clicked.connect(f)
            row.addWidget(b)
        row.addStretch()
        ll.addLayout(row)
        body.addWidget(left)

        right = QTabWidget()
        self.enc = EncoderPanel(self.cfg.get("hidden_encoders"))
        self.out = OutputPanel(cfgmod.music_folder())
        self.dsp = DspPanel()
        right.addTab(self.enc, "Encoding")
        right.addTab(self.out, tr("Ausgabe"))
        right.addTab(self.dsp, tr("DSP-Effekte / Aktionen"))
        body.addWidget(right)
        body.setSizes([520, 440])

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 4, 0, 4)
        self.profile = QComboBox()
        self.profile.setMinimumWidth(200)
        self._reload_profiles()
        self.profile.activated.connect(self._load_profile)
        sb, db = QPushButton(tr("Profil speichern")), QPushButton(tr("Löschen"))
        sb.clicked.connect(self._save_profile)
        db.clicked.connect(self._del_profile)
        bar.addWidget(QLabel(tr("Profil:")))
        bar.addWidget(self.profile)
        bar.addWidget(sb)
        bar.addWidget(db)
        bar.addSpacing(16)
        bar.addWidget(QLabel(tr("Kerne:")))
        self.workers = QSpinBox()
        self.workers.setRange(1, 64)
        self.workers.setValue(int(self.cfg["workers"]))
        bar.addWidget(self.workers)
        self.low = QCheckBox(tr("Niedrige Priorität"))
        self.low.setChecked(bool(self.cfg["low_priority"]))
        self.verify = QCheckBox(tr("Verifizieren"))
        bar.addWidget(self.low)
        bar.addWidget(self.verify)
        bar.addStretch()
        self.progress = QProgressBar()
        self.progress.setFixedWidth(220)
        bar.addWidget(self.progress)
        self.go = QPushButton("Convert  >>")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.start)
        bar.addWidget(self.go)
        lay.addLayout(bar)
        self._restore()
        self.statusBar().showMessage(tr("Dateien hierher ziehen oder hinzufügen."))
        if files:
            self.add(files)

    # ---------------------------------------------------------- Dateiliste
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add(collect_audio([u.toLocalFile() for u in e.mimeData().urls()]))

    def add_files(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Audiodateien"), "", "Audio (" + " ".join("*" + x for x in sorted(AUDIO_EXT)) + ")")
        self.add([Path(f) for f in fs])

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("Ordner"))
        if d:
            self.add(collect_audio([d]))

    def add(self, files: list[Path]):
        for f in files:
            if f in self.files:
                continue
            self.files.append(f)
            i = self.table.rowCount()
            self.table.insertRow(i)
            info = read_info(f)
            for c, v in enumerate((str(f), f"{int(info.length // 60)}:{int(info.length % 60):02d}", str(info.bitrate // 1000), "")):
                self.table.setItem(i, c, QTableWidgetItem(v))
        self.statusBar().showMessage(tr("{0} Dateien").format(len(self.files)))

    def remove_sel(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
            del self.files[r]

    def clear(self):
        self.table.setRowCount(0)
        self.files.clear()

    # --------------------------------------------------------------- Profile
    def current_settings(self) -> ConvertSettings:
        return ConvertSettings(encoder=self.enc.encoder, enc_settings=self.enc.settings, output=self.out.spec(), dsp=self.dsp.steps(),
                               workers=self.workers.value(), verify=self.verify.isChecked(), low_priority=self.low.isChecked())

    def _portable_settings(self) -> ConvertSettings:
        """Wie current_settings, aber der Musik-Ordner als "" (Standard) – siehe settings.portable_folder."""
        s = self.current_settings()
        s.output.folder = cfgmod.portable_folder(s.output.folder)
        return s

    def _reload_profiles(self):
        self.profile.clear()
        self.profile.addItem(tr("[Aktuelle Einstellungen]"))
        self.profile.addItems(cfgmod.list_profiles())

    def _save_profile(self):
        name, ok = QInputDialog.getText(self, tr("Profil speichern"), "Name:")
        if ok and name.strip():
            cfgmod.save_profile(name.strip(), self._portable_settings())
            self._reload_profiles()
            self.profile.setCurrentText(name.strip())

    def _load_profile(self, i: int):
        if i <= 0:
            return
        self._apply(cfgmod.load_profile(self.profile.currentText()))

    def _remember(self):
        """Letzten Stand (Encoder, Ausgabe/Naming/Ordner, DSP, gewähltes Profil) für den nächsten Start sichern."""
        cfgmod.update(self.cfg, last_convert={"settings": cfgmod.settings_to_dict(self._portable_settings()),
                                              "profile": self.profile.currentText() if self.profile.currentIndex() > 0 else ""})

    def _restore(self):
        last = self.cfg.get("last_convert")
        if not last:
            return
        try:
            self._apply(cfgmod.settings_from_dict(last["settings"]))
        except (KeyError, TypeError, ValueError):
            return                                               # alter/kaputter Stand: Standardwerte behalten
        if last.get("profile") and self.profile.findText(last["profile"]) > 0:
            self.profile.setCurrentText(last["profile"])

    def closeEvent(self, e):
        self._remember()
        super().closeEvent(e)

    def _apply(self, s: ConvertSettings):
        self.enc.set(s.encoder, s.enc_settings)
        self.out.set(s.output)
        self.out.folder.setText(cfgmod.output_folder(s.output.folder))
        self.dsp.set_steps(s.dsp)
        self.workers.setValue(s.workers)
        self.verify.setChecked(s.verify)
        self.low.setChecked(s.low_priority)

    def _del_profile(self):
        if self.profile.currentIndex() > 0:
            cfgmod.delete_profile(self.profile.currentText())
            self._reload_profiles()

    # ------------------------------------------------------------ Ausführen
    def start(self, *_, tags_map=None, art_map=None):
        if self.thread:
            self.worker.conv.cancel()
            return
        if not self.files:
            QMessageBox.information(self, "psyrip", tr("Keine Dateien ausgewählt."))
            return
        s = self.current_settings()
        if s.output.mode in ("folder", "preserve", "dynamic") and not s.output.folder:
            QMessageBox.warning(self, "psyrip", tr("Bitte einen Ausgabeordner angeben."))
            return
        self._remember()
        self._done = 0
        self._frac = [0.0] * len(self.files)
        self.progress.setValue(0)
        self.go.setText(tr("Abbrechen"))
        self.thread = QThread(self)
        self.worker = Worker(s, list(self.files), tags_map, art_map)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.result.connect(self._on_result)
        self.worker.finished.connect(self._on_finished)
        self.thread.start()

    def _on_progress(self, i: int, f: float):
        self._frac[i] = f
        self.progress.setValue(int(sum(self._frac) / len(self._frac) * 100))
        if self.table.item(i, 3) and f < 1.0:
            self.table.item(i, 3).setText(f"{int(f * 100)} %")

    def _on_result(self, i: int, r: Result):
        txt = {"ok": tr("Fertig"), "skipped": tr("Übersprungen"), "error": tr("Fehler"), "cancelled": tr("Abgebrochen")}.get(r.status, r.status)
        it = self.table.item(i, 3)
        it.setText(f"{txt}{': ' + r.message if r.message else ''}")
        it.setToolTip(r.message)
        if r.status == "error":
            it.setForeground(Qt.red)

    def _on_finished(self, results: list):
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.go.setText("Convert  >>")
        ok = sum(r.status == "ok" for r in results)
        err = sum(r.status == "error" for r in results)
        self.statusBar().showMessage(tr("{0} konvertiert, {1} Fehler, {2} übersprungen/abgebrochen").format(ok, err, len(results) - ok - err))
        self.progress.setValue(100)
        self.results = results
