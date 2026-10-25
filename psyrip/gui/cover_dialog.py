"""Cover-Auswahl aus dem Internet: Apple Music (iTunes) und MusicBrainz/Cover Art Archive nebeneinander."""
from __future__ import annotations

import io

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from .. import cdrip
from ..i18n import tr


def _dims(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
        return Image.open(io.BytesIO(data)).size
    except Exception:
        return (0, 0)


def cover_candidates(artist: str, album: str, size: int = 1500, country: str = "us", limit: int = 6) -> list[tuple[str, bytes]]:
    """Kandidaten aus beiden Quellen, größte Auflösung zuerst. Beschriftung enthält Quelle und Pixelmaße."""
    from ..tags import resize_art
    out: list[tuple[str, bytes, int]] = []
    seen: set[bytes] = set()

    def add(label: str, data: bytes | None):
        if not data or data in seen:
            return
        seen.add(data)
        try:
            data = resize_art(data, size)
        except Exception:
            pass
        w, h = _dims(data)
        out.append((f"{label}\n{w}×{h}", data, w * h))

    for hit in cdrip.itunes_search(artist, album, country, limit=limit):
        if hit["score"] >= 0.5:
            add(f"Apple Music: {hit['artist']} – {hit['album']} ({hit['year']})", cdrip.fetch_itunes_cover(hit["art"], size))
    for m in cdrip.musicbrainz_search(artist, album, limit=3):
        add(f"MusicBrainz: {m.artist} – {m.album} ({m.year})", cdrip.fetch_cover(m.mbid, size=size))
    out.sort(key=lambda x: -x[2])
    return [(label, data) for label, data, _ in out]


class CoverDialog(QDialog):
    def __init__(self, artist: str = "", album: str = "", parent=None, size: int = 1500, country: str = "us"):
        super().__init__(parent)
        self.setWindowTitle(tr("Cover aus dem Internet"))
        self.resize(720, 540)
        self.size_cap, self.country = size, country
        self.data: bytes | None = None
        self.cands: list[tuple[str, bytes]] = []
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.artist, self.album = QLineEdit(artist), QLineEdit(album)
        f.addRow("Artist", self.artist)
        f.addRow("Album", self.album)
        lay.addLayout(f)
        b = QPushButton(tr("Suchen"))
        b.clicked.connect(self.search)
        lay.addWidget(b)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(160, 160))
        self.list.setGridSize(QSize(200, 230))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(lambda *_: self._ok())
        lay.addWidget(self.list, 1)
        self.status = QLabel("")
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def search(self):
        self.status.setText(tr("Suche läuft… (MusicBrainz erlaubt 1 Anfrage pro Sekunde)"))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            self.cands = cover_candidates(self.artist.text().strip(), self.album.text().strip(), self.size_cap, self.country)
        finally:
            QApplication.restoreOverrideCursor()
        self.list.clear()
        for label, data in self.cands:
            pm = QPixmap()
            pm.loadFromData(data)
            self.list.addItem(QListWidgetItem(QIcon(pm), label))
        self.status.setText(tr("{0} Cover gefunden").format(len(self.cands)) if self.cands else tr("Keine Cover gefunden."))

    def _ok(self):
        r = self.list.currentRow()
        if r >= 0:
            self.data = self.cands[r][1]
            self.accept()
