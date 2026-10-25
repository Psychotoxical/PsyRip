"""Utility-Codecs als Fenster: Audio Info, Audio CRC, Arrange Audio, Tag From Filename, ID Tag Update,
Length Split, Channel Split, Multi-Encoder, ReplayGain."""
from __future__ import annotations

from ..i18n import tr
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QStackedWidget, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt

from .. import settings as cfgmod
from .. import utilities as U
from ..converter import ConvertSettings, OutputSpec
from ..encoders import ENCODERS
from ..tags import AUDIO_EXT
from .converter_win import collect_audio
from .widgets import EncoderPanel, FieldForm
from .. import dsp as dspmod

UTILS = ["Audio Info", "Calculate Audio CRC", "Arrange Audio", "Tag From Filename", "ID Tag Update",
         "Length Split", "Channel Split", "Multi-Encoder", "ReplayGain"]


class UtilitiesWindow(QMainWindow):
    def __init__(self, files: list[Path] | None = None, config: dict | None = None):
        super().__init__()
        self.cfg = config or cfgmod.load()
        self.setWindowTitle("psyrip Utilities")
        self.resize(960, 640)
        self.setAcceptDrops(True)
        root = QWidget(objectName="page")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)
        hdr = QLabel("Utility Codecs")
        hdr.setObjectName("header")
        lay.addWidget(hdr)
        sp = QSplitter(Qt.Horizontal)
        lay.addWidget(sp, 1)
        left = QWidget()
        ll = QVBoxLayout(left)
        self.files = QListWidget()
        self.files.setSelectionMode(QListWidget.ExtendedSelection)
        ll.addWidget(self.files, 1)
        r = QHBoxLayout()
        for t, f in ((tr("Dateien…"), self._add_files), (tr("Ordner…"), self._add_dir), (tr("Entfernen"), self._rm), (tr("Leeren"), self.files.clear)):
            b = QPushButton(t)
            b.clicked.connect(f)
            r.addWidget(b)
        ll.addLayout(r)
        sp.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.which = QComboBox()
        self.which.addItems(UTILS)
        rl.addWidget(self.which)
        self.stack = QStackedWidget()
        rl.addWidget(self.stack, 1)
        self._build_pages()
        self.which.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.run_btn = QPushButton(tr("Ausführen"))
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.run)
        rl.addWidget(self.run_btn)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(220)
        rl.addWidget(self.log, 2)
        sp.addWidget(right)
        sp.setSizes([380, 580])
        if files:
            self._add(files)

    def _page(self, widget_builder):
        w = QWidget()
        f = QFormLayout(w)
        widget_builder(f)
        self.stack.addWidget(w)
        return w

    def _build_pages(self):
        def info(f):
            self.i_ext, self.i_tab = QCheckBox(tr("Erweiterte Informationen")), QCheckBox(tr("Tab-getrennte Tabelle (für Excel)"))
            self.i_ext.setChecked(True)
            f.addRow(self.i_ext)
            f.addRow(self.i_tab)
        self._page(info)

        def crc(f):
            self.c_crc, self.c_md5, self.c_sha = QCheckBox("CRC32"), QCheckBox("MD5"), QCheckBox("SHA-256")
            self.c_crc.setChecked(True)
            self.c_md5.setChecked(True)
            for c in (self.c_crc, self.c_md5, self.c_sha):
                f.addRow(c)
        self._page(crc)

        def arr(f):
            self.a_root = QLineEdit(str(Path.home() / "Music"))
            self.a_pat = QLineEdit("[artist]\\[album]\\[track] [artist] - [title]")
            self.a_over, self.a_art, self.a_empty, self.a_dry = QCheckBox(tr("Vorhandene überschreiben")), QCheckBox(tr("Externes Cover mitnehmen")), QCheckBox(tr("Leere Quellordner entfernen")), QCheckBox(tr("Testlauf (nichts verschieben)"))
            self.a_art.setChecked(True)
            self.a_empty.setChecked(True)
            self.a_dry.setChecked(True)
            f.addRow(tr("Stammordner"), self.a_root)
            f.addRow(tr("Anordnung"), self.a_pat)
            for c in (self.a_over, self.a_art, self.a_empty, self.a_dry):
                f.addRow(c)
        self._page(arr)

        def tff(f):
            self.t_pat = QLineEdit("[track] [artist] - [title]")
            self.t_drop = QCheckBox(tr("Vorhandene Tags zuvor löschen"))
            f.addRow(tr("Tag-Erkennung"), self.t_pat)
            f.addRow(self.t_drop)
        self._page(tff)

        def upd(f):
            d = dspmod.REGISTRY["ID Tag Processing"]
            self.u_form = FieldForm(d.fields, d.defaults())
            f.addRow(self.u_form)
        self._page(upd)

        def ls(f):
            self.l_enc = QComboBox()
            self.l_enc.addItems(ENCODERS)
            self.l_len, self.l_back = QDoubleSpinBox(), QDoubleSpinBox()
            self.l_len.setRange(1, 36000)
            self.l_len.setValue(60)
            self.l_back.setRange(0, 600)
            self.l_out = QLineEdit(str(Path.home() / "Music" / "split"))
            f.addRow("Encoder", self.l_enc)
            f.addRow(tr("Teilen alle (s)"), self.l_len)
            f.addRow(tr("Zurückspringen (s)"), self.l_back)
            f.addRow(tr("Ausgabeordner"), self.l_out)
        self._page(ls)

        def cs(f):
            self.s_enc = QComboBox()
            self.s_enc.addItems(ENCODERS)
            self.s_desc = QCheckBox(tr("Beschreibende Namen (Left, Right, …)"))
            self.s_out = QLineEdit(str(Path.home() / "Music" / "split"))
            f.addRow("Encoder", self.s_enc)
            f.addRow(self.s_desc)
            f.addRow(tr("Ausgabeordner"), self.s_out)
        self._page(cs)

        def me(f):
            self.m_list = QListWidget()
            self.m_items: list[tuple[str, dict]] = []
            self.m_panel = EncoderPanel()
            add = QPushButton(tr("Encoder hinzufügen"))
            add.clicked.connect(self._m_add)
            self.m_out = QLineEdit(str(Path.home() / "Music" / "multi"))
            f.addRow(self.m_panel)
            f.addRow(add)
            f.addRow(self.m_list)
            f.addRow(tr("Ausgabeordner (je Encoder Unterordner)"), self.m_out)
        self._page(me)

        def rg(f):
            self.r_ref = QDoubleSpinBox()
            self.r_ref.setRange(-30, 0)
            self.r_ref.setValue(-18)
            self.r_album = QCheckBox(tr("Album-Gain berechnen"))
            self.r_album.setChecked(True)
            f.addRow(tr("Referenz (LUFS)"), self.r_ref)
            f.addRow(self.r_album)
        self._page(rg)

    def _m_add(self):
        self.m_items.append((self.m_panel.encoder, self.m_panel.settings))
        self.m_list.addItem(f"{self.m_panel.encoder} {self.m_panel.settings}")

    # --------------------------------------------------------- Dateiliste
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._add(collect_audio([u.toLocalFile() for u in e.mimeData().urls()]))

    def _add_files(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Audiodateien"), "", "Audio (" + " ".join("*" + x for x in sorted(AUDIO_EXT)) + ")")
        self._add([Path(f) for f in fs])

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("Ordner"))
        if d:
            self._add(collect_audio([d]))

    def _add(self, fs):
        have = {self.files.item(i).text() for i in range(self.files.count())}
        for f in fs:
            if str(f) not in have:
                self.files.addItem(str(f))

    def _rm(self):
        for it in self.files.selectedItems():
            self.files.takeItem(self.files.row(it))

    def _paths(self) -> list[Path]:
        return [Path(self.files.item(i).text()) for i in range(self.files.count())]

    # ---------------------------------------------------------- Ausführen
    def run(self):
        files, which = self._paths(), self.which.currentText()
        if not files:
            QMessageBox.information(self, "psyrip", tr("Keine Dateien ausgewählt."))
            return
        self.log.clear()
        try:
            out = self._dispatch(which, files)
        except Exception as e:
            out = tr("Fehler: {0}").format(e)
        self.log.setPlainText(out)

    def _dispatch(self, which: str, files: list[Path]) -> str:
        if which == "Audio Info":
            return U.audio_info(files, self.i_ext.isChecked(), self.i_tab.isChecked())
        if which == "Calculate Audio CRC":
            algos = [a for a, c in (("crc32", self.c_crc), ("md5", self.c_md5), ("sha256", self.c_sha)) if c.isChecked()]
            return "\n".join(f"{f}\n   " + "  ".join(f"{k}={v}" for k, v in h.items()) for f, h in U.audio_crc(files, algos).items())
        if which == "Arrange Audio":
            mv = U.arrange_audio(files, Path(self.a_root.text()), self.a_pat.text(), self.a_over.isChecked(), self.a_art.isChecked(),
                                 self.a_empty.isChecked(), self.a_dry.isChecked())
            return (tr("[Testlauf]\n") if self.a_dry.isChecked() else "") + "\n".join(f"{a}\n  → {b}" for a, b in mv) or tr("Nichts zu tun.")
        if which == "Tag From Filename":
            lines = []
            for f in files:
                t = U.tag_from_filename(f, self.t_pat.text(), self.t_drop.isChecked())
                lines.append(f"{f.name}: {t or tr('kein Treffer')}")
            return "\n".join(lines)
        if which == "ID Tag Update":
            U.id_tag_update(files, self.u_form.values())
            return tr("{0} Dateien aktualisiert.").format(len(files))
        if which == "Length Split":
            n = 0
            for f in files:
                n += len(U.length_split(f, Path(self.l_out.text()), self.l_len.value(), self.l_back.value(), self.l_enc.currentText()))
            return tr("{0} Teile geschrieben nach {1}").format(n, self.l_out.text())
        if which == "Channel Split":
            n = 0
            for f in files:
                n += len(U.channel_split(f, Path(self.s_out.text()), self.s_enc.currentText(), None, self.s_desc.isChecked()))
            return tr("{0} Kanaldateien geschrieben nach {1}").format(n, self.s_out.text())
        if which == "Multi-Encoder":
            if not self.m_items:
                return tr("Bitte mindestens einen Encoder hinzufügen.")
            cfgs = [ConvertSettings(encoder=e, enc_settings=s, output=OutputSpec("folder", str(Path(self.m_out.text()) / e)), workers=2) for e, s in self.m_items]
            res = U.multi_encode(files, cfgs)
            return "\n".join(f"{c.encoder}: " + ", ".join(f"{r.src.name}={r.status}" for r in rs) for c, rs in zip(cfgs, res))
        if which == "ReplayGain":
            from ..analysis import replaygain as rg
            from ..tags import write_tags
            gains = {}
            for f in files:
                gains[f] = rg(f, self.r_ref.value())
            if self.r_album.isChecked():
                ag = sum(float(g["replaygain_track_gain"].split()[0]) for g in gains.values()) / len(gains)
                ap = max(float(g["replaygain_track_peak"]) for g in gains.values())
                for g in gains.values():
                    g.update({"replaygain_album_gain": f"{ag:+.2f} dB", "replaygain_album_peak": f"{ap:.6f}"})
            for f, g in gains.items():
                write_tags(f, g)
            return "\n".join(f"{f.name}: {g['replaygain_track_gain']}" for f, g in gains.items())
        return ""
