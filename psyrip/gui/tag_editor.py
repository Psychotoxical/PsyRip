"""ID-Tag-Editor: mehrere Dateien gleichzeitig (<different>), Einzelblättern, Cover aus Datei/Zwischenablage/Folder.jpg."""
from __future__ import annotations

from ..i18n import tr
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QScrollArea, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget, QCompleter)

from .. import settings as cfgmod
from ..tags import read_art, read_tags, write_art, write_tags

DIFF = "<different>"
LABELS = {"artist": "Artist", "album": "Album", "title": "Title", "albumartist": "Album Artist", "tracknumber": "Track",
          "discnumber": "Disc", "genre": "Genre", "date": "Year", "composer": "Composer", "comment": "Comment", "compilation": "Compilation"}


class TagEditor(QDialog):
    def __init__(self, files: list[Path], config: dict | None = None, parent=None):
        super().__init__(parent)
        self.cfg = config or cfgmod.load()
        self.files = files
        self.idx = -1                       # -1 = alle gemeinsam
        self.tags = {f: read_tags(f) for f in files}
        self.arts: dict[Path, bytes | None] = {f: read_art(f) for f in files}
        self.setWindowTitle(tr("psyrip ID-Tag-Editor"))
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.nav = QLabel()
        prev, nxt = QPushButton("<"), QPushButton(">")
        for b in (prev, nxt):
            b.setFixedWidth(40)
            b.setStyleSheet("padding: 6px 0;")
        prev.clicked.connect(lambda: self._go(-1))
        nxt.clicked.connect(lambda: self._go(1))
        top.addWidget(self.nav, 1)
        mbb = QPushButton(tr("Von MusicBrainz holen…"))
        mbb.setToolTip(tr("Tags, IDs, Album-Typ, Credits und Cover für diese Dateien von MusicBrainz laden"))
        mbb.clicked.connect(self._mb)
        top.addWidget(mbb)
        top.addWidget(prev)
        top.addWidget(nxt)
        lay.addLayout(top)
        mid = QHBoxLayout()
        self.form_w = QWidget()
        self.form = QFormLayout(self.form_w)
        scroll = QScrollArea()                                # mit MusicBrainz-Feldern wird die Liste lang
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form_w)
        mid.addWidget(scroll, 1)
        art_col = QVBoxLayout()
        self.art = QLabel()
        self.art.setFixedSize(180, 180)
        self.art.setAlignment(Qt.AlignCenter)
        self.art.setObjectName("artbox")
        art_col.addWidget(self.art)
        ab = QPushButton("…")
        m = QMenu(self)
        m.addAction(tr("Aus dem Internet…"), self._art_net)
        m.addAction(tr("Aus Datei laden"), self._art_file)
        m.addAction(tr("Aus Zwischenablage"), self._art_clip)
        m.addAction(tr("Folder.jpg importieren"), self._art_folder)
        m.addAction(tr("Als Folder.jpg exportieren"), self._art_export)
        m.addAction(tr("Entfernen"), lambda: self._set_art(None))
        ab.setMenu(m)
        art_col.addWidget(ab)
        art_col.addStretch()
        mid.addLayout(art_col)
        lay.addLayout(mid)
        row = QHBoxLayout()
        row.addStretch()
        ok, cancel = QPushButton(tr("Speichern")), QPushButton(tr("Abbrechen"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)
        self.edits: dict[str, QLineEdit] = {}
        self._pending_art: tuple[bool, bytes | None] = (False, None)
        self._build()
        self._show(-1)

    def _build(self):
        keys = list(self.cfg.get("default_tag_fields", []))
        for t in self.tags.values():
            keys += [k for k in t if k not in keys]
        known = sorted({v for t in self.tags.values() for k, v in t.items() if k == "artist"})
        for k in keys:
            e = QLineEdit()
            if k in ("artist", "albumartist", "composer") and known:
                e.setCompleter(QCompleter(known, e))
            self.edits[k] = e
            self.form.addRow(LABELS.get(k, k.title()), e)

    def _ensure_fields(self):
        """Neue Felder (z. B. aus MusicBrainz) als zusätzliche Zeilen anzeigen."""
        for t in self.tags.values():
            for k in t:
                if k not in self.edits:
                    e = QLineEdit()
                    self.edits[k] = e
                    self.form.addRow(LABELS.get(k, k), e)

    def _mb(self):
        from .mb_tag_dialog import MBTagDialog
        self._commit()
        dlg = MBTagDialog(self.files, self.tags, self.cfg, self)
        if not dlg.exec():
            return
        for p, t in dlg.result_tags.items():
            self.tags[p].update(t)
            if dlg.result_cover:
                self.arts[p] = dlg.result_cover
        self._ensure_fields()
        self._show(self.idx)

    def _go(self, d: int):
        self._commit()
        self._show(max(-1, min(self.idx + d, len(self.files) - 1)))

    def _show(self, i: int):
        self.idx = i
        self.nav.setText(tr("{0} Dateien (gemeinsam bearbeiten)").format(len(self.files)) if i < 0 else f"{self.files[i].name}  ({i + 1}/{len(self.files)})")
        pool = self.files if i < 0 else [self.files[i]]
        for k, e in self.edits.items():
            vals = {self.tags[f].get(k, "") for f in pool}
            e.setText(next(iter(vals)) if len(vals) == 1 else DIFF)
            e.setProperty("orig", e.text())
        arts = {self.arts[f] for f in pool}
        self._paint(next(iter(arts)) if len(arts) == 1 else None)

    def _commit(self):
        pool = self.files if self.idx < 0 else [self.files[self.idx]]
        for k, e in self.edits.items():
            if e.text() != e.property("orig") and e.text() != DIFF:
                for f in pool:
                    self.tags[f][k] = e.text()
        if self._pending_art[0]:
            for f in pool:
                self.arts[f] = self._pending_art[1]
            self._pending_art = (False, None)

    def _paint(self, data: bytes | None):
        pm = QPixmap()
        if data and pm.loadFromData(data):
            self.art.setPixmap(pm.scaled(176, 176, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.art.setToolTip(f"{pm.width()}×{pm.height()}")
        else:
            self.art.setPixmap(QPixmap())
            self.art.setText(tr("kein Cover") if not data else DIFF)

    def _set_art(self, data: bytes | None):
        self._pending_art = (True, data)
        self._paint(data)

    def _art_net(self):
        from .cover_dialog import CoverDialog
        t = self.tags[self.files[max(self.idx, 0)]]
        d = CoverDialog(t.get("albumartist") or t.get("artist", ""), t.get("album", ""), self,
                        int(self.cfg.get("cover_size", 1500)), self.cfg.get("itunes_country", "us"))
        if d.exec() and d.data:
            self._set_art(d.data)

    def _art_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Cover", "", tr("Bilder (*.jpg *.jpeg *.png)"))
        if f:
            self._set_art(Path(f).read_bytes())

    def _art_clip(self):
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            return
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "JPG", 92)
        self._set_art(bytes(ba))

    def _art_folder(self):
        p = self.files[max(self.idx, 0)].parent / "Folder.jpg"
        if p.exists():
            self._set_art(p.read_bytes())

    def _art_export(self):
        d = self.arts[self.files[max(self.idx, 0)]]
        if d:
            (self.files[max(self.idx, 0)].parent / "Folder.jpg").write_bytes(d)

    def save(self):
        self._commit()
        errs = []
        for f in self.files:
            try:
                write_tags(f, self.tags[f])
                write_art(f, self.arts[f])
            except Exception as e:
                errs.append(f"{f.name}: {e}")
        if errs:
            QMessageBox.warning(self, "psyrip", "\n".join(errs))
        else:
            self.accept()
