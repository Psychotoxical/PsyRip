"""Metadaten-Prüfung (ähnlich PerfectMeta-Review) und manuelle Suche."""
from __future__ import annotations

from ..i18n import tr
import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QListWidget,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .. import cdrip


class ReviewDialog(QDialog):
    """Spalten = Anbieter. Doppelklick auf eine Spaltenüberschrift übernimmt alles dieses Anbieters,
    Doppelklick auf eine Zelle nur diesen Wert. Unterschiede sind gelb markiert."""

    def __init__(self, cands: list[cdrip.DiscMeta], current: cdrip.DiscMeta, ntracks: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Metadaten prüfen"))
        self.resize(900, 520)
        self.cands = cands
        self.result_meta = copy.deepcopy(current)
        while len(self.result_meta.tracks) < ntracks:
            self.result_meta.tracks.append(("", ""))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Doppelklick auf Überschrift = ganzen Anbieter übernehmen · Doppelklick auf Zelle = einzelnen Wert übernehmen")))
        self.table = QTableWidget(ntracks + 3, len(cands) + 1)
        heads = [tr("Aktuell")] + [f"{c.source} {i}" + (f" ({c.year})" if c.year else "") for i, c in enumerate(cands, 1)]
        self.table.setHorizontalHeaderLabels(heads)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setVerticalHeaderLabels(["Album", "Artist", tr("Jahr")] + [f"Track {i + 1}" for i in range(ntracks)])
        self.table.horizontalHeader().setDefaultSectionSize(230)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().sectionDoubleClicked.connect(self.take_column)
        self.table.cellDoubleClicked.connect(self.take_cell)
        lay.addWidget(self.table, 1)
        self.ntracks = ntracks
        self._fill()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @staticmethod
    def _values(m: cdrip.DiscMeta, n: int) -> list[str]:
        tr = [f"{t} — {a}" if a and a != m.artist else t for t, a in (m.tracks + [("", "")] * n)[:n]]
        return [m.album, m.artist, m.year, *tr]

    def _fill(self):
        cols = [self._values(self.result_meta, self.ntracks)] + [self._values(c, self.ntracks) for c in self.cands]
        for ci, col in enumerate(cols):
            for ri, v in enumerate(col):
                it = QTableWidgetItem(v)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if ci > 0 and v != cols[0][ri]:
                    it.setBackground(QBrush(QColor("#fff3b0")))
                    it.setForeground(QBrush(QColor("#222")))
                self.table.setItem(ri, ci, it)

    def take_column(self, col: int):
        if col == 0:
            return
        c = self.cands[col - 1]
        cur = self.result_meta
        cur.album, cur.artist, cur.year = c.album, c.artist, c.year or cur.year
        cur.genre = c.genre or cur.genre
        cur.mbid, cur.cover = c.mbid or cur.mbid, c.cover or cur.cover
        cur.tracks = list(c.tracks)[:self.ntracks] + [("", "")] * max(0, self.ntracks - len(c.tracks))
        self._fill()

    def take_cell(self, row: int, col: int):
        if col == 0:
            return
        c, cur = self.cands[col - 1], self.result_meta
        if row == 0:
            cur.album = c.album
        elif row == 1:
            cur.artist = c.artist
        elif row == 2:
            cur.year = c.year
        elif row - 3 < len(c.tracks):
            cur.tracks[row - 3] = c.tracks[row - 3]
        self._fill()


class SearchDialog(QDialog):
    def __init__(self, ntracks: int, discogs_token: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Manuelle Metadaten-Suche"))
        self.resize(560, 420)
        self.ntracks, self.token = ntracks, discogs_token
        self.found: list[cdrip.DiscMeta] = []
        self.result_meta: cdrip.DiscMeta | None = None
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.artist, self.album, self.barcode, self.url = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.url.setPlaceholderText(tr("MusicBrainz- oder Discogs-Release-URL einfügen"))
        f.addRow("Artist", self.artist)
        f.addRow("Album", self.album)
        f.addRow("Barcode", self.barcode)
        f.addRow(tr("oder URL"), self.url)
        lay.addLayout(f)
        b = QPushButton(tr("Suchen"))
        b.clicked.connect(self.search)
        lay.addWidget(b)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self._accept())
        lay.addWidget(self.list, 1)
        self.status = QLabel("")
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def search(self):
        self.status.setText(tr("Suche läuft…"))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            res: list[cdrip.DiscMeta] = []
            if self.url.text().strip():
                m = cdrip.meta_from_url(self.url.text().strip(), self.token, self.ntracks)
                res = [m] if m else []
            else:
                a, al, bc = self.artist.text().strip(), self.album.text().strip(), self.barcode.text().strip()
                res = cdrip.musicbrainz_search(a, al, bc, self.ntracks)
                if self.token:
                    res += cdrip.discogs_search(self.token, a, al, bc, self.ntracks)
        finally:
            QApplication.restoreOverrideCursor()
        self.found = res
        self.list.clear()
        for m in res:
            self.list.addItem(tr("[{0}] {1} – {2} ({3}) · {4} Tracks").format(m.source, m.artist, m.album, m.year, len(m.tracks)))
        self.status.setText(tr("{0} Treffer").format(len(res)) if res else tr("Keine Treffer."))

    def _accept(self):
        r = self.list.currentRow()
        if r >= 0:
            self.result_meta = self.found[r]               # das Cover holt der Ripper danach gemäß Einstellungen
            self.accept()
