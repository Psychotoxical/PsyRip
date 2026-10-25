"""Batch Converter: Ordnerbaum mit Häkchen, Typ-/Künstler-Filter, Liste mit Eigenschaften, Übergabe an den Converter."""
from __future__ import annotations

from ..i18n import tr
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem)

from ..tags import AUDIO_EXT, read_info, read_tags
from .converter_win import ConverterWindow


class FilterDialog(QDialog):
    def __init__(self, files: list[Path], types: set[str], artists: dict[str, bool], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filter")
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        self.types = QListWidget()
        for e in sorted({f.suffix.lower() for f in files}):
            it = QListWidgetItem(e)
            it.setCheckState(Qt.Checked if e in types else Qt.Unchecked)
            self.types.addItem(it)
        self.art = QListWidget()
        for a, on in sorted(artists.items()):
            it = QListWidgetItem(a or tr("(kein Künstler)"))
            it.setData(Qt.UserRole, a)
            it.setCheckState(Qt.Checked if on else Qt.Unchecked)
            self.art.addItem(it)
        tabs.addTab(self.types, tr("Dateitypen"))
        tabs.addTab(self.art, tr("Künstler"))
        lay.addWidget(tabs)
        row = QHBoxLayout()
        ex = QPushButton(tr("Alle ausschließen"))
        ex.clicked.connect(lambda: [self.art.item(i).setCheckState(Qt.Unchecked) for i in range(self.art.count())])
        inc = QPushButton(tr("Alle einschließen"))
        inc.clicked.connect(lambda: [self.art.item(i).setCheckState(Qt.Checked) for i in range(self.art.count())])
        ok = QPushButton("OK")
        ok.clicked.connect(self.accept)
        row.addWidget(ex)
        row.addWidget(inc)
        row.addStretch()
        row.addWidget(ok)
        lay.addLayout(row)

    def selected_types(self) -> set[str]:
        return {self.types.item(i).text() for i in range(self.types.count()) if self.types.item(i).checkState() == Qt.Checked}

    def selected_artists(self) -> dict[str, bool]:
        return {self.art.item(i).data(Qt.UserRole): self.art.item(i).checkState() == Qt.Checked for i in range(self.art.count())}


class BatchWindow(QMainWindow):
    def __init__(self, config: dict | None = None):
        super().__init__()
        self.cfg = config
        self.setWindowTitle("psyrip Batch Converter")
        self.resize(900, 640)
        root = QWidget(objectName="page")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)
        hdr = QLabel("Batch Converter")
        hdr.setObjectName("header")
        lay.addWidget(hdr)
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 4)
        b = QPushButton(tr("Ordner hinzufügen…"))
        b.clicked.connect(self.add_root)
        self.recursive = QCheckBox(tr("Unterordner einschließen"))
        self.recursive.setChecked(True)
        row.addWidget(b)
        row.addWidget(self.recursive)
        row.addStretch()
        lay.addLayout(row)
        self.tabs = QTabWidget()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Ordner / Datei")])
        self.tree.itemChanged.connect(self._changed)
        self.listing = QTableWidget(0, 6)
        self.listing.setHorizontalHeaderLabels([tr("Datei"), tr("Künstler"), "Album", "kbps", "Hz", "Bit"])
        self.listing.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.listing.setSortingEnabled(True)
        self.listing.setAlternatingRowColors(True)
        self.tabs.addTab(self.tree, tr("Auswahl"))
        self.tabs.addTab(self.listing, tr("Liste (Eigenschaften)"))
        lay.addWidget(self.tabs, 1)
        self.info = QLabel("")
        lay.addWidget(self.info)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 4, 0, 4)
        fb = QPushButton("Filter…")
        fb.clicked.connect(self.filter)
        lb = QPushButton(tr("Liste laden"))
        lb.clicked.connect(self.load_list)
        self.go = QPushButton("Convert  >>")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.convert)
        bar.addWidget(fb)
        bar.addWidget(lb)
        bar.addStretch()
        bar.addWidget(self.go)
        lay.addLayout(bar)
        self.types: set[str] = set(AUDIO_EXT)
        self.artists: dict[str, bool] = {}
        self._busy = False
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = Path(u.toLocalFile())
            self._add_path(p)

    def add_root(self):
        d = QFileDialog.getExistingDirectory(self, tr("Ordner"))
        if d:
            self._add_path(Path(d))

    def _add_path(self, p: Path):
        self._busy = True
        item = self._make(p)
        self.tree.addTopLevelItem(item)
        item.setExpanded(True)
        self._busy = False
        self._changed()

    def _make(self, p: Path) -> QTreeWidgetItem:
        it = QTreeWidgetItem([p.name or str(p)])
        it.setData(0, Qt.UserRole, str(p))
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
        it.setCheckState(0, Qt.Checked)
        if p.is_dir():
            try:
                for c in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                    if c.is_dir() and self.recursive.isChecked() or c.suffix.lower() in AUDIO_EXT:
                        child = self._make(c)
                        if c.is_dir() and child.childCount() == 0:
                            continue
                        it.addChild(child)
            except OSError:
                pass
        return it

    def _leaves(self, it: QTreeWidgetItem | None = None):
        items = [it] if it else [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        for x in items:
            if x.childCount() == 0:
                p = Path(x.data(0, Qt.UserRole))
                if p.is_file():
                    yield x, p
            for i in range(x.childCount()):
                yield from self._leaves(x.child(i))

    def selected_files(self) -> list[Path]:
        out = []
        for it, p in self._leaves():
            if it.checkState(0) != Qt.Checked or p.suffix.lower() not in self.types:
                continue
            if self.artists:
                a = read_tags(p).get("artist", "")
                if not self.artists.get(a, True):
                    continue
            out.append(p)
        return out

    def _changed(self, *_):
        if not self._busy:
            self.info.setText(tr("{0} Dateien ausgewählt").format(len(self.selected_files())))

    def filter(self):
        files = [p for _, p in self._leaves()]
        if not self.artists:
            self.artists = {read_tags(p).get("artist", ""): True for p in files}
        dlg = FilterDialog(files, self.types, self.artists, self)
        if dlg.exec():
            self.types, self.artists = dlg.selected_types(), dlg.selected_artists()
            self._changed()

    def load_list(self):
        files = self.selected_files()
        self.listing.setSortingEnabled(False)
        self.listing.setRowCount(0)
        for f in files:
            i, t = read_info(f), read_tags(f)
            r = self.listing.rowCount()
            self.listing.insertRow(r)
            for c, v in enumerate((str(f), t.get("artist", ""), t.get("album", ""), i.bitrate // 1000, i.sample_rate, i.bits)):
                it = QTableWidgetItem()
                it.setData(Qt.DisplayRole, v)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                if c == 0:
                    it.setCheckState(Qt.Checked)
                self.listing.setItem(r, c, it)
        self.listing.setSortingEnabled(True)
        self.tabs.setCurrentIndex(1)

    def convert(self):
        if self.tabs.currentIndex() == 1 and self.listing.rowCount():
            files = [Path(self.listing.item(r, 0).text()) for r in range(self.listing.rowCount())
                     if self.listing.item(r, 0).checkState() == Qt.Checked]
        else:
            files = self.selected_files()
        self.conv = ConverterWindow(files, self.cfg)
        self.conv.show()
