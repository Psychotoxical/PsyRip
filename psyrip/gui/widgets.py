"""Wiederverwendbare Panels: Encoder-Auswahl, DSP-Kette, Ausgabe/Naming."""
from __future__ import annotations

from ..i18n import tr
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import dsp as dspmod
from ..converter import DspStep, OutputSpec, naming_context
from ..encoders import ENCODERS
from ..naming import DEFAULT_RIP_NAMING, render
from ..tags import AudioInfo


class FieldForm(QWidget):
    """Erzeugt ein Formular aus einer Liste dsp.Field / encoders.Option."""

    def __init__(self, fields, values: dict | None = None, parent=None):
        super().__init__(parent)
        self.fields, self.editors = fields, {}
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        values = values or {}
        for f in fields:
            kind = getattr(f, "kind", "str")
            cur = values.get(f.key, f.default)
            if kind == "choice":
                w = QComboBox()
                for label, val in f.choices:
                    w.addItem(label, val)
                i = w.findData(str(cur))
                w.setCurrentIndex(max(i, 0))
            elif kind == "bool":
                w = QCheckBox()
                w.setChecked(bool(cur))
            elif kind == "int":
                w = QSpinBox()
                w.setRange(int(max(f.lo, -2**31)), int(min(f.hi, 2**31 - 1)))
                w.setValue(int(cur or 0))
            elif kind == "float":
                w = QDoubleSpinBox()
                w.setDecimals(3)
                w.setRange(max(f.lo, -1e9), min(f.hi, 1e9))
                w.setValue(float(cur or 0))
            elif kind == "text":
                w = QPlainTextEdit(str(cur))
                w.setFixedHeight(64)
            elif kind == "path":
                w = QLineEdit(str(cur))
            else:
                w = QLineEdit(str(cur))
            self.editors[f.key] = w
            form.addRow(f.label, w)

    def values(self) -> dict:
        out = {}
        for f in self.fields:
            w, kind = self.editors[f.key], getattr(f, "kind", "str")
            if kind == "choice":
                out[f.key] = w.currentData()
            elif kind == "bool":
                out[f.key] = w.isChecked()
            elif kind in ("int", "float"):
                out[f.key] = w.value()
            elif kind == "text":
                out[f.key] = w.toPlainText()
            else:
                out[f.key] = w.text()
        return out


class DspDialog(QDialog):
    def __init__(self, name: str, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(name)
        d = dspmod.REGISTRY[name]
        lay = QVBoxLayout(self)
        if not d.fields:
            lay.addWidget(QLabel(tr("Dieser Effekt hat keine Einstellungen.")))
            self.form = None
        else:
            self.form = FieldForm(d.fields, {**d.defaults(), **settings})
            lay.addWidget(self.form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> dict:
        return self.form.values() if self.form else {}


class EncoderPanel(QGroupBox):
    changed = Signal()

    def __init__(self, hidden: list[str] | None = None, parent=None):
        super().__init__("", parent)
        self.setObjectName("encoder")
        lay = QVBoxLayout(self)
        self.combo = QComboBox()
        for n, e in ENCODERS.items():
            if n not in (hidden or []):
                self.combo.addItem(f"{n}  ({tr('verlustfrei') if e.lossless else tr('verlustbehaftet')})" + ("" if e.available else tr("  – Tool '{0}' fehlt").format(e.external[0])), n)
        self.holder = QVBoxLayout()
        lay.addWidget(self.combo)
        lay.addLayout(self.holder)
        self.form: FieldForm | None = None
        self._pending: dict = {}
        self.combo.currentIndexChanged.connect(self._rebuild)
        self._rebuild()

    def _rebuild(self):
        if self.form:
            self.holder.removeWidget(self.form)
            self.form.hide()
            self.form.setParent(None)
            self.form.deleteLater()
            self.form = None
        enc = ENCODERS[self.combo.currentData()]
        if enc.options:
            self.form = FieldForm(enc.options, self._pending)
            self.holder.addWidget(self.form)
            for w in self.form.editors.values():
                (w.currentIndexChanged if isinstance(w, QComboBox) else w.stateChanged if isinstance(w, QCheckBox) else w.textChanged).connect(lambda *_: self.changed.emit())
        self._pending = {}
        self.changed.emit()

    @property
    def encoder(self) -> str:
        return self.combo.currentData()

    @property
    def settings(self) -> dict:
        return self.form.values() if self.form else {}

    def set(self, name: str, settings: dict):
        self._pending = dict(settings)
        i = self.combo.findData(name)
        if i >= 0:
            if self.combo.currentIndex() == i:
                self._rebuild()
            else:
                self.combo.setCurrentIndex(i)


class DspPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.itemDoubleClicked.connect(self.edit)
        lay.addWidget(self.list, 1)
        col = QVBoxLayout()
        self.add_btn = QPushButton(tr("Hinzufügen ▾"))
        menu = QMenu(self)
        for cat, names in dspmod.list_by_category().items():
            sub = menu.addMenu({"Effekt": tr("Audio-Effekte"), "Aktion": tr("Aktionen")}.get(cat, cat))
            for n in names:
                sub.addAction(n, lambda n=n: self.add(n))
        self.add_btn.setMenu(menu)
        col.addWidget(self.add_btn)
        for text, fn in ((tr("Einstellungen…"), self.edit), (tr("Entfernen"), self.remove), (tr("▲ Hoch"), lambda: self.move(-1)), (tr("▼ Runter"), lambda: self.move(1))):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, fn=fn: fn())
            col.addWidget(b)
        col.addStretch()
        lay.addLayout(col)

    def add(self, name: str):
        d = dspmod.REGISTRY[name]
        settings = {}
        if d.fields:
            dlg = DspDialog(name, {}, self)
            if not dlg.exec():
                return
            settings = dlg.values()
        it = QListWidgetItem(name)
        it.setData(Qt.UserRole, settings)
        self.list.addItem(it)

    def edit(self, *_):
        it = self.list.currentItem()
        if not it:
            return
        dlg = DspDialog(it.text(), it.data(Qt.UserRole) or {}, self)
        if dlg.exec():
            it.setData(Qt.UserRole, dlg.values())

    def remove(self):
        r = self.list.currentRow()
        if r >= 0:
            self.list.takeItem(r)

    def move(self, d: int):
        r = self.list.currentRow()
        if 0 <= r + d < self.list.count() and r >= 0:
            it = self.list.takeItem(r)
            self.list.insertItem(r + d, it)
            self.list.setCurrentRow(r + d)

    def steps(self) -> list[DspStep]:
        return [DspStep(self.list.item(i).text(), self.list.item(i).data(Qt.UserRole) or {}) for i in range(self.list.count())]

    def set_steps(self, steps: list[DspStep]):
        self.list.clear()
        for s in steps:
            it = QListWidgetItem(s.name)
            it.setData(Qt.UserRole, s.settings)
            self.list.addItem(it)


_AA = "[IFVALUE]album artist,[album artist],[artist][]"     # Album-Künstler, sonst Künstler
_YEAR4 = "[GRAB]1,4,[year][]"                                 # nur das Jahr, auch wenn ein volles Datum getaggt ist

# (Gruppe, ersetzt das ganze Feld?, [(verständlicher Name, Code, feste Beispielangabe oder None = live berechnen)])
_ELEMENTS = [
    (tr("Fertige Vorlagen"), True, [
        (tr("Künstler \\ Album \\ Nr Künstler - Titel"), "[artist]\\[album]\\[track] [artist] - [title]", None),
        (tr("Album-Künstler - (Jahr) - Album \\ Nr - Künstler - Titel"), f"{_AA} - ({_YEAR4}) - [album]\\[track] - [artist] - [title]", None),
        (tr("Album-Künstler \\ (Jahr) Album \\ Nr - Titel"), f"{_AA}\\({_YEAR4}) [album]\\[track] - [title]", None),
        (tr("Album-Künstler \\ Album \\ Nr Titel"), f"{_AA}\\[album]\\[track] [title]", None),
        (tr("Genre \\ Künstler \\ Album \\ Nr Titel"), "[genre]\\[artist]\\[album]\\[track] [title]", None),
        (tr("Standard (Sampler unter „Various Artists“)"), DEFAULT_RIP_NAMING, None),
        (tr("Alles in einen Ordner: Künstler - Titel"), "[artist] - [title]", None),
    ]),
    (tr("Angaben aus den Tags"), False, [
        (tr("Künstler des Tracks"), "[artist]", None),
        (tr("Titel"), "[title]", None),
        (tr("Album"), "[album]", None),
        (tr("Album-Künstler"), "[album artist]", None),
        (tr("Album-Künstler, wenn leer: Künstler"), _AA, None),
        (tr("Tracknummer (zweistellig)"), "[track]", None),
        (tr("CD-Nummer"), "[disc]", None),
        (tr("Jahr (wie getaggt, evtl. volles Datum)"), "[year]", None),
        (tr("Jahr (nur die 4 Ziffern)"), _YEAR4, None),
        (tr("Genre"), "[genre]", None),
        (tr("Komponist"), "[composer]", None),
    ]),
    (tr("Trennzeichen"), False, [
        (tr("Neuer Unterordner"), "\\", tr("Ordner \\ Unterordner")),
        (tr("Bindestrich mit Leerzeichen"), " - ", "Madonna - Holiday"),
        (tr("Leerzeichen"), " ", "04 Holiday"),
        (tr("Punkt mit Leerzeichen"), ". ", "04. Holiday"),
        (tr("Klammer auf"), "(", "(1998"),
        (tr("Klammer zu"), ")", "1998)"),
    ]),
    (tr("Nur wenn …"), False, [
        (tr("Nur bei Samplern: „Various Artists“"), "[IFCOMP]Various Artists[]", None),
        (tr("Nur bei normalen Alben: Künstler"), "[IF!COMP][artist][]", None),
        (tr("Nur bei Mehrfach-CDs: „CD N“ als Unterordner"), "[IFMULTI]CD [disc]\\[]", None),
        (tr("Nur bei Einzel-CDs: Text"), "[IF!MULTI]Text[]", None),
        (tr("Wenn Tag vorhanden, dann A, sonst B"), "[IFVALUE]album artist,[album artist],[artist][]", None),
        (tr("Wenn Tag einen bestimmten Wert hat, dann Text"), "[IFEQUALS]genre,Pop,Pop music[]", None),
        (tr("Wenn Tag einen bestimmten Wert nicht hat, dann Text"), "[IF!EQUALS]genre,Pop,Other[]", None),
        (tr("Vergleich: wenn gleich, dann ja, sonst nein"), "[IF][artist],=,Madonna,yes,no[]", None),
    ]),
    (tr("Text umformen"), False, [
        (tr("In GROSSBUCHSTABEN"), "[UPPER][artist][]", None),
        (tr("In kleinbuchstaben"), "[LOWER][artist][]", None),
        (tr("Leerzeichen am Rand entfernen"), "[TRIM][artist][]", None),
        (tr("Nur die ersten N Zeichen"), "[GRAB]1,3,[album][]", None),
        (tr("Nur die letzten N Zeichen"), "[RIGHT]5,[album][]", None),
        (tr("Zeichen löschen (von, bis)"), "[DEL]1,4,[album][]", None),
        (tr("Auf höchstens N Zeichen kürzen"), "[MAXLENGTH]8,[album][]", None),
        (tr("Auf feste Länge auffüllen (Nr dreistellig)"), "[SETLEN]3,48,,[track][]", None),
        (tr("Text ersetzen (alt → neu)"), "[REPLACE] ,_,[album][]", None),
        (tr("Nur die ersten N Wörter"), "[WORD][album],2[]", None),
        (tr("Anfangsbuchstaben-Gruppe (z. B. m-p)"), "[GROUP]4,[artist][]", None),
        (tr("Teil eines Textes (an Zeichen getrennt)"), "[SPLIT] ,[album],2[]", None),
        (tr("Alle Werte eines Mehrfach-Tags"), "[MULTITAG]artist[]", None),
        (tr("Beliebiges Tag per Name"), "[tag]composer[]", None),
    ]),
    (tr("Quelldatei"), False, [
        (tr("Ordner der Quelldatei"), "[origpath]", None),
        (tr("Dateiname der Quelldatei (ohne Endung)"), "[origfilename]", None),
        (tr("Endung der Quelldatei"), "[extension]", None),
        (tr("Ordnername der Quelle, N-ter von vorn"), "[FRONTFOLDER]1[]", None),
        (tr("Ordnername der Quelle, N-ter von hinten"), "[BACKFOLDER]1[]", None),
        (tr("Quellpfad ohne ersten Ordner"), "[TRIMFIRSTFOLDER][origpath][]", None),
        (tr("Quellpfad ohne letzten Ordner"), "[TRIMLASTFOLDER][origpath][]", None),
        (tr("Änderungsdatum der Quelldatei"), "[source_date]yyyy-mm-dd[]", None),
        (tr("Bitrate der Quelle (kbit/s)"), "[k_bitrate]", None),
        (tr("Name des Ziel-Encoders"), "[encoder]", None),
        (tr("Verlustfrei oder verlustbehaftet"), "[audio_quality]", None),
    ]),
]


class NamingDialog(QDialog):
    """Editor für Dynamic Naming: Elemente einfügen, Beispiel live sehen."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Dynamic Naming bearbeiten"))
        self.resize(900, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Namensschema (Ordner und Dateiname, ohne Endung):")))
        self.edit = QLineEdit(text)
        lay.addWidget(self.edit)
        self.example = QLabel()
        self.example.setWordWrap(True)
        self.example.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.example)
        row = QHBoxLayout()
        self.groups = QListWidget()
        self.groups.addItems([g for g, _, _ in _ELEMENTS])
        self.groups.setMaximumWidth(190)
        self.items = QTreeWidget()
        self.items.setRootIsDecorated(False)
        self.items.setHeaderLabels([tr("Baustein"), tr("Ergebnis im Beispiel"), "Code"])
        self.items.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.items.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.items.header().setSectionResizeMode(2, QHeaderView.Interactive)
        self.items.header().setStretchLastSection(False)
        self.items.setColumnWidth(2, 160)
        self.groups.currentRowChanged.connect(self._fill)
        self.items.itemDoubleClicked.connect(self._use)
        row.addWidget(self.groups)
        row.addWidget(self.items, 1)
        lay.addLayout(row, 1)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setObjectName("sub")
        lay.addWidget(self.hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.edit.textChanged.connect(self._upd)
        self.groups.setCurrentRow(0)
        self._upd()

    @staticmethod
    def _ctx():
        from ..encoders import Encoder
        return naming_context({"artist": "Madonna", "album": "Ray of Light", "title": "Holiday", "tracknumber": "4", "discnumber": "1",
                               "genre": "Pop", "date": "1998-03-02", "composer": "Madonna"}, Path("C:/Music/Pop/holiday.flac"),
                              Encoder("FLAC", ".flac", True, []), AudioInfo(bitrate=900000))

    def _fill(self, i: int):
        _, replaces, entries = _ELEMENTS[max(i, 0)]
        self.items.clear()
        # Vorlagen: langes Ergebnis wichtiger als der Code (der steht im Tooltip)
        self.items.setColumnHidden(2, replaces)
        self.items.header().setSectionResizeMode(0, QHeaderView.Interactive if replaces else QHeaderView.ResizeToContents)
        if replaces:
            self.items.setColumnWidth(0, 330)
        ctx = self._ctx()
        sub = self.palette().placeholderText()
        for label, code, fixed in entries:
            try:
                ex = fixed if fixed is not None else render(code, ctx)
            except Exception:
                ex = ""
            if fixed is None and replaces:
                ex += ".flac"
            it = QTreeWidgetItem([label, ex or tr("(im Beispiel leer)"), code])
            it.setData(0, Qt.UserRole, code)
            it.setForeground(2, sub)
            for c, tip in enumerate((f"{label}\n{code}", ex, code)):
                it.setToolTip(c, tip)
            self.items.addTopLevelItem(it)
        self.hint.setText(tr("Doppelklick auf eine Vorlage ersetzt das ganze Schema.") if replaces else
                          tr("Doppelklick fügt den Baustein an der Cursorposition im Schema ein. Alles, was kein Baustein ist, "
                             "landet unverändert im Namen. Das Beispiel oben zeigt sofort das Ergebnis."))

    def _use(self, it: QTreeWidgetItem):
        code = it.data(0, Qt.UserRole)
        if _ELEMENTS[max(self.groups.currentRow(), 0)][1]:
            self.edit.setText(code)
        else:
            self.edit.insert(code)
        self.edit.setFocus()

    def _upd(self, *_):
        try:
            path = render(self.edit.text(), self._ctx()) + ".flac"
            folder, _, name = path.rpartition("\\")
            self.example.setText(tr("<b>Beispiel</b> (Madonna – Ray of Light, Track 4 „Holiday“, 1998):<br>"
                                    "Ordner: <b>{0}</b><br>Datei: <b>{1}</b>").format(escape(folder) or "–", escape(name)))
        except Exception as e:
            self.example.setText(tr("Fehler: {0}").format(escape(str(e))))

    def text(self) -> str:
        return self.edit.text()


class OutputPanel(QGroupBox):
    changed = Signal()

    def __init__(self, default_folder: str = "", default_naming: str = "[artist]\\[album]\\[track] [artist] - [title]", parent=None):
        super().__init__("", parent)
        self.setObjectName("plain")
        g = QGridLayout(self)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        self.r_source = QRadioButton(tr("Bestehender Quellordner"))
        self.r_folder = QRadioButton(tr("Einzelner Ordner"))
        self.r_preserve = QRadioButton(tr("Quellpfad beibehalten"))
        self.r_dynamic = QRadioButton(tr("Dynamisches Naming"))
        self.r_source.setChecked(True)
        for i, r in enumerate((self.r_source, self.r_folder, self.r_preserve, self.r_dynamic)):
            g.addWidget(r, i // 2, 1 + i % 2)
            r.toggled.connect(self._upd)
        self.folder = QLineEdit(default_folder)
        b = QPushButton("…")
        b.setFixedWidth(44)
        b.setStyleSheet("padding: 6px 0;")
        b.clicked.connect(self._browse)
        g.addWidget(QLabel(tr("Ordner:")), 2, 0)
        g.addWidget(self.folder, 2, 1, 1, 2)
        g.addWidget(b, 2, 3)
        self.naming = QLineEdit(default_naming)
        g.addWidget(QLabel("Naming:"), 3, 0)
        g.addWidget(self.naming, 3, 1, 1, 2)
        eb = QPushButton(tr("Bearbeiten…"))
        eb.clicked.connect(self._edit_naming)
        g.addWidget(eb, 3, 3)
        self.example = QLabel()
        self.example.setObjectName("sub")
        self.example.setWordWrap(True)
        g.addWidget(self.example, 4, 1, 1, 3)
        self.overwrite = QCheckBox(tr("Vorhandene Dateien überschreiben"))
        g.addWidget(self.overwrite, 5, 1, 1, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(2, 1)
        g.setRowStretch(6, 1)
        self.naming.textChanged.connect(self._upd)
        self.folder.textChanged.connect(self._upd)
        self._upd()

    def _edit_naming(self):
        dlg = NamingDialog(self.naming.text(), self)
        if dlg.exec():
            self.naming.setText(dlg.text())
            self.r_dynamic.setChecked(True)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("Ausgabeordner"), self.folder.text())
        if d:
            self.folder.setText(d)

    def _upd(self, *_):
        dyn = self.r_dynamic.isChecked()
        self.naming.setEnabled(dyn)
        self.folder.setEnabled(not self.r_source.isChecked())
        try:
            from ..encoders import Encoder
            e = Encoder("x", ".ext", False, [])
            ctx = naming_context({"artist": "Madonna", "album": "Ray of Light", "title": "Holiday", "albumartist": "", "tracknumber": "4",
                                  "discnumber": "1"}, Path("C:/Music/Pop/holiday.flac"), e, AudioInfo())
            self.example.setText(tr("Beispiel: ") + render(self.naming.text(), ctx) + ".ext" if dyn else "")
        except Exception as ex:
            self.example.setText(tr("Fehler im Naming: {0}").format(ex))
        self.changed.emit()

    def spec(self) -> OutputSpec:
        mode = "source" if self.r_source.isChecked() else "folder" if self.r_folder.isChecked() else "preserve" if self.r_preserve.isChecked() else "dynamic"
        return OutputSpec(mode, self.folder.text(), self.naming.text(), self.overwrite.isChecked())

    def set(self, o: OutputSpec):
        {"source": self.r_source, "folder": self.r_folder, "preserve": self.r_preserve, "dynamic": self.r_dynamic}[o.mode].setChecked(True)
        self.folder.setText(o.folder)
        self.naming.setText(o.naming)
        self.overwrite.setChecked(o.overwrite)
