"""Metadaten für bestehende Dateien von MusicBrainz holen (Tag-Editor): Release suchen, Tracks zuordnen, Feldgruppen wählen."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .. import cdrip
from ..i18n import tr
from ..ripper import mb_tag_groups

GROUP_LABELS = {"core": "Titel, Artist, Album, Jahr, Nummern", "ids": "MusicBrainz-IDs", "details": "Release-Typ, Label, Land, Barcode, ISRC",
                "credits": "Credits (Komponist, Produzent, Mitwirkende, Werk)", "extras": "Genres, Sprache, Sortierfelder, Totals"}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _track_no(tags: dict[str, str]) -> int | None:
    try:
        return int(tags.get("tracknumber", "").split("/")[0])
    except ValueError:
        return None


class MBTagDialog(QDialog):
    """Ergebnis: self.result_tags {Pfad: Tags}, self.result_cover (bytes|None)."""

    def __init__(self, files: list[Path], tags: dict[Path, dict[str, str]], cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Von MusicBrainz holen"))
        self.resize(900, 640)
        self.files, self.tags, self.cfg = files, tags, cfg
        self.meta: cdrip.DiscMeta | None = None
        self.found: list[cdrip.DiscMeta] = []
        self.result_tags: dict[Path, dict[str, str]] = {}
        self.result_cover: bytes | None = None
        self.combos: list[QComboBox] = []
        first = tags[files[0]]
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.artist = QLineEdit(first.get("albumartist") or first.get("artist", ""))
        self.album = QLineEdit(first.get("album", ""))
        self.barcode = QLineEdit(first.get("barcode", ""))
        self.mbid = QLineEdit(first.get("musicbrainz_albumid", ""))
        self.mbid.setPlaceholderText(tr("MusicBrainz-Release-ID oder -URL (genauester Weg)"))
        f.addRow("Artist", self.artist)
        f.addRow("Album", self.album)
        f.addRow("Barcode", self.barcode)
        f.addRow("MBID / URL", self.mbid)
        lay.addLayout(f)
        b = QPushButton(tr("Suchen"))
        b.clicked.connect(self.search)
        lay.addWidget(b)
        self.list = QListWidget()
        self.list.setMaximumHeight(130)
        self.list.currentRowChanged.connect(self._choose)
        lay.addWidget(self.list)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("Datei"), tr("Track in Datei"), tr("→ MusicBrainz-Track")])
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setColumnWidth(0, 330)
        self.table.setColumnWidth(1, 120)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        box = QGroupBox(tr("Welche Felder übernehmen?"))
        h = QHBoxLayout(box)
        self.checks: dict[str, QCheckBox] = {}
        for g in ("core", "ids", "details", "credits", "extras"):
            c = QCheckBox(tr(GROUP_LABELS[g]))
            c.setChecked(True)
            self.checks[g] = c
            h.addWidget(c)
        lay.addWidget(box)
        self.cover = QCheckBox(tr("Cover laden (Quelle und Größe laut Einstellungen)"))
        lay.addWidget(self.cover)
        self.status = QLabel("")
        self.status.setObjectName("sub")
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._fill_files()
        if self.mbid.text().strip():                         # Dateien kennen ihr Release schon: direkt laden
            self.search()

    # ------------------------------------------------------------------ Suche
    def _fill_files(self):
        self.table.setRowCount(len(self.files))
        for r, p in enumerate(self.files):
            t = self.tags[p]
            self.table.setItem(r, 0, QTableWidgetItem(p.name))
            self.table.setItem(r, 1, QTableWidgetItem(f"{t.get('tracknumber', '?')}  {t.get('title', '')}"))

    def search(self):
        self.status.setText(tr("Suche läuft… (MusicBrainz erlaubt 1 Anfrage pro Sekunde)"))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            n = len(self.files)
            pos = None
            try:
                pos = int(self.tags[self.files[0]].get("discnumber", "").split("/")[0])
            except ValueError:
                pass
            m = _UUID.search(self.mbid.text().lower())
            if m:
                one = cdrip.musicbrainz_release(m.group(0), n, medium_pos=pos)
                res = [one] if one else []
            else:
                res = cdrip.musicbrainz_search(self.artist.text().strip(), self.album.text().strip(), self.barcode.text().strip(), None, limit=5)
        finally:
            QApplication.restoreOverrideCursor()
        self.found = res
        self.list.clear()
        for r in res:
            self.list.addItem(f"{r.artist} – {r.album} ({r.year}) · {r.country} · {r.label} · {len(r.tracks)} Tracks · {r.release_type}")
        self.status.setText(tr("{0} Treffer").format(len(res)) if res else tr("Keine Treffer."))
        if res:
            self.list.setCurrentRow(0)

    def _choose(self, row: int):
        if row < 0 or row >= len(self.found):
            return
        self.meta = self.found[row]
        info = [{"track": _track_no(self.tags[p]), "title": self.tags[p].get("title", "")} for p in self.files]
        titles = [t for t, _ in self.meta.tracks]
        match = cdrip.match_tracks(info, titles)
        self.combos.clear()
        for r, idx in enumerate(match):
            cb = QComboBox()
            cb.addItem(tr("(nicht zuordnen)"), None)
            for j, (title, artist) in enumerate(self.meta.tracks):
                cb.addItem(f"{j + 1:02d}  {title}", j)
            cb.setCurrentIndex(0 if idx is None else idx + 1)
            self.table.setCellWidget(r, 2, cb)
            self.combos.append(cb)

    # ----------------------------------------------------------------- Übernehmen
    def _apply(self):
        if not self.meta:
            return
        groups = [g for g, c in self.checks.items() if c.isChecked()]
        for p, cb in zip(self.files, self.combos, strict=True):
            j = cb.currentData()
            if j is None:
                continue
            g = mb_tag_groups(self.meta, j + 1)
            out: dict[str, str] = {}
            for name in groups:
                out.update(g[name])
            self.result_tags[p] = out
        if self.cover.isChecked():
            c = self.cfg
            self.result_cover, _ = cdrip.best_cover(self.meta.artist, self.meta.album, self.meta.mbid, c.get("cover_source", "auto"),
                                                    int(c.get("cover_size", 1500)), c.get("itunes_country", "us"))
        self.accept()
