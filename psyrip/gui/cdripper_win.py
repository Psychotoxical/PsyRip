"""CD Ripper: Laufwerk, TOC, MusicBrainz-Metadaten, Secure/Burst, AccurateRip-Anzeige, Encoder/DSP/Naming."""
from __future__ import annotations

from ..i18n import tr
import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
                               QMenu, QMessageBox, QProgressBar, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
                               QScrollArea, QVBoxLayout, QWidget, QFileDialog)

from .. import cdrip
from .. import settings as cfgmod
from ..converter import ConvertSettings
from ..ripper import RipJob, RipSession, TrackMeta
from .meta_dialog import ReviewDialog, SearchDialog
from .widgets import DspPanel, EncoderPanel, OutputPanel


class Bridge(QObject):
    status = Signal(int, str)
    progress = Signal(int, float)
    finished = Signal(object)
    meta = Signal(object)
    toc = Signal(object)
    offset = Signal(object)
    cover = Signal(object)
    error = Signal(str)
    info = Signal(str)
    crc = Signal(int, object)          # object: CRC-Werte ≥ 2^31 passen nicht in Qts int


class CDRipperWindow(QMainWindow):
    def __init__(self, config: dict | None = None):
        super().__init__()
        self.cfg = config or cfgmod.load()
        self.setWindowTitle("psyrip CD Ripper")
        self.resize(1100, 900)
        self.disc: cdrip.Disc | None = None
        self.meta = cdrip.DiscMeta()
        self.metas: list[cdrip.DiscMeta] = []
        self.session: RipSession | None = None
        self.br = Bridge()
        self.br.status.connect(self._status)
        self.br.progress.connect(self._progress)
        self.br.finished.connect(self._finished)
        self.br.meta.connect(self._got_meta)
        self.br.toc.connect(self._got_toc)
        self.br.offset.connect(self._got_offset)
        self.br.cover.connect(self._got_cover)
        self.br.error.connect(lambda m: QMessageBox.warning(self, "psyrip", m))
        self.br.info.connect(lambda m: self.statusBar().showMessage(m))
        self.br.crc.connect(lambda n, crc: self.table.item(self._row(n), 6).setText(f"{crc:08X}"))   # sofort je Track
        root = QWidget(objectName="page")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)
        hdr = QLabel("CD Ripper")
        hdr.setObjectName("header")
        lay.addWidget(hdr)

        top = QHBoxLayout()
        top.setContentsMargins(0, 4, 0, 4)
        self.drive = QComboBox()
        self.drive.addItems(cdrip.list_cd_drives())
        if self.cfg.get("last_drive") in [self.drive.itemText(i) for i in range(self.drive.count())]:
            self.drive.setCurrentText(self.cfg["last_drive"])
        rd = QPushButton(tr("Disc lesen"))
        rd.clicked.connect(lambda: self.read_disc())
        self.metabtn = QPushButton(tr("Metadaten laden"))
        self.metabtn.clicked.connect(self.lookup)
        self.reviewbtn = QPushButton(tr("Prüfen…"))
        self.reviewbtn.setToolTip(tr("Anbieter vergleichen (Alt+M)"))
        self.reviewbtn.setShortcut("Alt+M")
        self.reviewbtn.clicked.connect(self.review)
        self.searchbtn = QPushButton(tr("Manuell suchen…"))
        self.searchbtn.clicked.connect(self.manual_search)
        self.metacombo = QComboBox()
        self.metacombo.activated.connect(lambda i: self._apply_meta(self.metas[i]))
        top.addWidget(QLabel(tr("Laufwerk:")))
        top.addWidget(self.drive)
        top.addWidget(rd)
        top.addWidget(self.metabtn)
        top.addWidget(self.reviewbtn)
        top.addWidget(self.searchbtn)
        top.addWidget(self.metacombo, 1)
        lay.addLayout(top)

        mid = QHBoxLayout()
        mid.setContentsMargins(0, 4, 0, 4)
        self.coverlbl = QLabel(tr("kein Cover"))
        self.coverlbl.setFixedSize(130, 130)
        self.coverlbl.setAlignment(Qt.AlignCenter)
        self.coverlbl.setObjectName("artbox")
        cov = QVBoxLayout()
        cov.addWidget(self.coverlbl)
        cb = QPushButton("Cover…")
        cm = QMenu(self)
        cm.addAction(tr("Aus dem Internet…"), self._cover_net)
        cm.addAction(tr("Aus Datei…"), self._cover_file)
        cm.addAction(tr("Aus Zwischenablage"), self._cover_clip)
        cm.addAction(tr("Entfernen"), lambda: self._set_cover(None))
        cb.setMenu(cm)
        cov.addWidget(cb)
        mid.addLayout(cov)
        form = QFormLayout()
        self.album, self.artist, self.albumartist, self.year, self.genre = (QLineEdit() for _ in range(5))
        for w, hint in ((self.album, tr("Unbekanntes Album – bitte eintragen")), (self.artist, tr("Unbekannter Künstler – bitte eintragen")),
                        (self.albumartist, tr("leer = wie Künstler")), (self.year, tr("Jahr")), (self.genre, "Genre")):
            w.setPlaceholderText(hint)
        self.comp = QCheckBox("Compilation")
        self.disc_no, self.disc_total = QSpinBox(), QSpinBox()
        for s in (self.disc_no, self.disc_total):
            s.setRange(1, 99)
        dr = QHBoxLayout()
        dr.addWidget(self.disc_no)
        dr.addWidget(QLabel(tr("von")))
        dr.addWidget(self.disc_total)
        dr.addWidget(self.comp)
        dr.addStretch()
        form.addRow("Album", self.album)
        form.addRow("Artist", self.artist)
        form.addRow("Album Artist", self.albumartist)
        form.addRow(tr("Jahr / Genre"), self._pair(self.year, self.genre))
        self.release_type = QLineEdit()
        self.release_type.setPlaceholderText(tr("z. B. album, single, ep – mehrere mit ; trennen (compilation, live …)"))
        form.addRow(tr("Release-Typ"), self.release_type)
        self.mb_info = QLabel("")
        self.mb_info.setObjectName("sub")
        self.mb_info.setWordWrap(True)
        form.addRow("", self.mb_info)
        form.addRow("Disc", dr)
        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText(tr("optional – verbessert die Trefferquote (Barcode-Scanner möglich)"))
        form.addRow("Barcode", self.barcode)
        mid.addLayout(form, 1)
        lay.addLayout(mid)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Rip", "#", tr("Titel"), tr("Künstler"), tr("Länge"), "Status", "CRC"])
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setStretchLastSection(True)     # Tabelle füllt die ganze Breite
        self.table.setColumnWidth(2, 260)
        self.table.setColumnWidth(3, 180)
        self.table.setColumnWidth(5, 300)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._track_menu)
        self.track_offset = 0
        lay.addWidget(self.table, 1)

        tabs = QTabWidget()
        self.enc = EncoderPanel(self.cfg.get("hidden_encoders"))
        self.enc.set(self.cfg["rip_encoder"], {})
        self.out = OutputPanel(cfgmod.output_folder(self.cfg["rip_folder"]), self.cfg["rip_naming"])
        self.out.r_dynamic.setChecked(True)
        self.dsp = DspPanel()
        sec = QWidget()
        sl = QFormLayout(sec)
        self.secure = QCheckBox(tr("Secure (Fehler erkennen und beheben)"))
        self.secure.setChecked(bool(self.cfg["rip_secure"]))
        self.passes = QSpinBox()
        self.passes.setRange(1, 10)
        self.passes.setValue(int(self.cfg["rip_passes"]))
        self.rereads = QSpinBox()
        self.rereads.setRange(0, 700)
        self.rereads.setValue(int(self.cfg["rip_rereads"]))
        self.offset = QSpinBox()
        self.offset.setRange(-3000, 3000)
        self.offset.setValue(int(self.cfg["rip_offset"]))
        self.cache = QSpinBox()
        self.cache.setRange(0, 16384)
        self.cache.setValue(1024)
        self.cache.setSuffix(" KB")
        self.ar = QCheckBox(tr("AccurateRip verwenden"))
        self.ar.setChecked(bool(self.cfg["internet"]))
        sl.addRow(self.secure)
        sl.addRow(tr("Durchläufe (Passes)"), self.passes)
        sl.addRow(tr("Max. Re-Reads je Sektor"), self.rereads)
        ob = QPushButton(tr("Offset per AccurateRip erkennen (Disc muss in der Datenbank sein)"))
        ob.clicked.connect(self.detect_offset)
        sl.addRow(tr("Laufwerks-Offset (Samples)"), self.offset)
        sl.addRow(ob)
        sl.addRow(tr("Lese-Cache"), self.cache)
        self.mb_tags = QComboBox()
        for label, code in ((tr("Aus"), "off"), (tr("Grundlegend: IDs, Release-Typ, Label, Land, Barcode, ISRC"), "basic"),
                            (tr("Vollständig: zusätzlich Credits, Werk, Sprache, Genres, Sortierfelder"), "full")):
            self.mb_tags.addItem(label, code)
        self.mb_tags.setCurrentIndex(max(self.mb_tags.findData(self.cfg.get("mb_detail", "full")), 0))
        sl.addRow(tr("MusicBrainz-Tags"), self.mb_tags)
        self.as_one = QCheckBox(tr("Rip as One (gewählte Tracks als eine Datei)"))
        sl.addRow(self.as_one)
        sl.addRow(self.ar)
        self.overread = QCheckBox(tr("In Lead-in/Lead-out lesen (Overread; nur wenige Laufwerke)"))
        self.abort_n = QSpinBox()
        self.abort_n.setRange(0, 100000)
        self.abort_n.setSpecialValueText(tr("nie"))
        self.abort_n.setSuffix(tr(" unrettbare Sektoren"))
        self.err_insecure = QCheckBox(tr("Unsichere Tracks als Fehler markieren (für „Delete/Move Destination on Error“)"))
        self.err_inacc = QCheckBox(tr("Tracks ohne AccurateRip-Bestätigung als Fehler markieren"))
        self.cancel_insecure = QCheckBox(tr("Disc-Rip nach dem ersten unsicheren Track abbrechen"))
        self.after = QComboBox()
        self.after.addItem(tr("Nach dem Rippen: nichts"), "none")
        self.after.addItem(tr("Nach dem Rippen: Disc auswerfen"), "eject")
        self.after.addItem(tr("Nach dem Rippen: Disc auswerfen, wenn alles sicher"), "eject_secure")
        self.after.addItem(tr("Nach dem Rippen: Computer herunterfahren"), "shutdown")
        for w in (self.overread, self.err_insecure, self.err_inacc, self.cancel_insecure):
            sl.addRow(w)
        sl.addRow(tr("Rip abbrechen nach"), self.abort_n)
        sl.addRow(self.after)
        sl.addRow(QLabel(tr("Hinweis: Der Windows-Treiber meldet keine C2-Fehlerzeiger; Fehler werden per\nMehrfach-Lesen mit Mehrheitsentscheid erkannt.")))
        tabs.addTab(self.enc, "Encoder")
        tabs.addTab(self.out, tr("Pfad && Naming"))
        tabs.addTab(self.dsp, "DSP")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(sec)
        tabs.addTab(scroll, tr("Ripping-Optionen"))
        tabs.setMinimumHeight(270)
        lay.addWidget(tabs)
        self.table.setMinimumHeight(200)
        lay.setStretchFactor(self.table, 3)
        lay.setStretchFactor(tabs, 1)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 4, 0, 4)
        self.prog = QProgressBar()
        self.go = QPushButton("Rip")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.start)
        eject = QPushButton(tr("Auswerfen"))
        eject.clicked.connect(lambda: self._eject())
        self.profile = QComboBox()
        self.profile.setMinimumWidth(190)
        self._reload_profiles()
        self.profile.activated.connect(self._apply_profile)
        pb, pd = QPushButton(tr("Profil speichern")), QPushButton(tr("Löschen"))
        pb.clicked.connect(self._save_profile)
        pd.clicked.connect(self._del_profile)
        bar.addWidget(QLabel(tr("Profil:")))
        bar.addWidget(self.profile)
        bar.addWidget(pb)
        bar.addWidget(pd)
        bar.addWidget(self.prog, 1)
        bar.addWidget(eject)
        bar.addWidget(self.go)
        lay.addLayout(bar)
        self._restore()
        if self.drive.count() == 0:
            self.statusBar().showMessage(tr("Kein CD-Laufwerk gefunden."))
        elif self.cfg.get("auto_read_disc", True):
            # erst nach dem Anzeigen des Fensters; die Metadaten lädt _got_toc anschließend selbst
            QTimer.singleShot(0, lambda: self.read_disc(quiet=True))

    # ----------------------------------------------------------------- Profile
    def _profile_data(self) -> dict:
        out = self.out.spec()
        out.folder = cfgmod.portable_folder(out.folder)
        s = ConvertSettings(encoder=self.enc.encoder, enc_settings=self.enc.settings, output=out, dsp=self.dsp.steps(), workers=1)
        return {"convert": cfgmod.settings_to_dict(s), "secure": self.secure.isChecked(), "passes": self.passes.value(),
                "rereads": self.rereads.value(), "offset": self.offset.value(), "cache": self.cache.value(), "ar": self.ar.isChecked(),
                "overread": self.overread.isChecked(), "abort": self.abort_n.value(), "err_insecure": self.err_insecure.isChecked(),
                "err_inacc": self.err_inacc.isChecked(), "cancel_insecure": self.cancel_insecure.isChecked(), "after": self.after.currentData()}

    def _reload_profiles(self):
        self.profile.clear()
        self.profile.addItem(tr("[Aktuelle Einstellungen]"))
        self.profile.addItems(sorted(self.cfg.get("rip_profiles", {})))

    def _save_profile(self):
        name, ok = QInputDialog.getText(self, tr("Profil speichern"), "Name:")
        if ok and name.strip():
            profiles = {**cfgmod.load().get("rip_profiles", {}), name.strip(): self._profile_data()}
            cfgmod.update(self.cfg, rip_profiles=profiles)
            self._reload_profiles()
            self.profile.setCurrentText(name.strip())

    def _apply_profile(self, i: int):
        if i <= 0:
            return
        self._apply_data(self.cfg["rip_profiles"][self.profile.currentText()])

    def _remember(self):
        """Letzten Stand (Encoder, Naming, Ordner, DSP, Optionen, gewähltes Profil) für den nächsten Start sichern."""
        cfgmod.update(self.cfg, last_rip={**self._profile_data(), "profile": self.profile.currentText() if self.profile.currentIndex() > 0 else ""},
                      mb_detail=self.mb_tags.currentData(), last_drive=self.drive.currentText(), rip_offset=self.offset.value())

    def _restore(self):
        p = self.cfg.get("last_rip")
        if not p:
            return
        try:
            self._apply_data(p)
        except (KeyError, TypeError, ValueError):
            return                                               # alter/kaputter Stand: Standardwerte behalten
        if p.get("profile") and self.profile.findText(p["profile"]) > 0:
            self.profile.setCurrentText(p["profile"])

    def closeEvent(self, e):
        self._remember()
        super().closeEvent(e)

    def _apply_data(self, p: dict):
        s = cfgmod.settings_from_dict(p["convert"])
        self.enc.set(s.encoder, s.enc_settings)
        self.out.set(s.output)
        self.out.folder.setText(cfgmod.output_folder(s.output.folder))
        self.dsp.set_steps(s.dsp)
        self.secure.setChecked(p["secure"])
        self.passes.setValue(p["passes"])
        self.rereads.setValue(p["rereads"])
        self.cache.setValue(p["cache"])
        self.ar.setChecked(p["ar"])
        self.overread.setChecked(p["overread"])
        self.abort_n.setValue(p["abort"])
        self.err_insecure.setChecked(p["err_insecure"])
        self.err_inacc.setChecked(p["err_inacc"])
        self.cancel_insecure.setChecked(p["cancel_insecure"])
        self.after.setCurrentIndex(max(self.after.findData(p["after"]), 0))
        # Der Laufwerks-Offset gehört zum Laufwerk, nicht zum Profil – bleibt unverändert.

    def _del_profile(self):
        if self.profile.currentIndex() > 0:
            profiles = cfgmod.load().get("rip_profiles", {})
            profiles.pop(self.profile.currentText(), None)
            cfgmod.update(self.cfg, rip_profiles=profiles)
            self._reload_profiles()

    @staticmethod
    def _pair(a, b):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(a)
        h.addWidget(b)
        return w

    # ------------------------------------------------------------- Disc/Meta
    def read_disc(self, quiet: bool = False):
        """quiet: automatisches Einlesen beim Öffnen – ohne Disc nur ein Hinweis in der Statusleiste statt Fehlerfenster."""
        if not self.drive.currentText():
            return
        letter = self.drive.currentText()
        self.statusBar().showMessage(tr("Disc in {0} wird gelesen…").format(letter))

        def job():
            try:
                with cdrip.CDDrive(letter) as d:
                    self.br.toc.emit(d.read_toc())
            except Exception as e:
                if quiet:
                    self.br.info.emit(tr("Keine Audio-CD in {0} – Disc einlegen und „Disc lesen“ klicken.").format(letter))
                else:
                    self.br.error.emit(tr("Disc konnte nicht gelesen werden: {0}").format(e))
        threading.Thread(target=job, daemon=True).start()

    def _reset_meta(self):
        """Neue Disc: alle Album-Angaben der vorigen Disc löschen (sonst bleiben sie stehen, wenn nichts gefunden wird)."""
        self.meta = cdrip.DiscMeta()                   # verspätete Cover der alten Disc passen dann nicht mehr (_got_cover)
        self.metas = []
        self.metacombo.clear()
        for w in (self.album, self.artist, self.albumartist, self.year, self.genre, self.release_type):
            w.clear()
        self.mb_info.setText("")
        self.comp.setChecked(False)
        self.disc_no.setValue(1)
        self.disc_total.setValue(1)
        self._set_cover(None)

    def _got_toc(self, disc: cdrip.Disc):
        self.disc = disc
        self._reset_meta()
        self.table.setRowCount(0)
        htoa = cdrip.htoa_track(disc)
        for t in ([htoa] if htoa else []) + disc.audio_tracks:
            r = self.table.rowCount()
            self.table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setCheckState(Qt.Unchecked if t.number == 0 else Qt.Checked)   # HTOA standardmäßig nicht gerippt
            self.table.setItem(r, 0, chk)
            for c, v in enumerate((str(t.number), "Hidden Track One Audio" if t.number == 0 else f"Track {t.number:02d}", "",
                                   f"{int(t.seconds // 60)}:{int(t.seconds % 60):02d}", "", "")):
                it = QTableWidgetItem(v)
                if c in (0, 3, 4, 5):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c + 1, it)
        self.statusBar().showMessage(tr("{0} Audiotracks · MusicBrainz-ID {1}").format(len(disc.audio_tracks), cdrip.musicbrainz_disc_id(disc)))
        if self.cfg.get("internet", True):
            self.lookup()

    def lookup(self):
        if not self.disc:
            return
        disc, barcode, token = self.disc, self.barcode.text().strip(), self.cfg.get("discogs_token", "")
        self.statusBar().showMessage(tr("Metadaten werden abgefragt…"))

        def job():
            prov = cdrip.all_providers(disc, token, barcode)
            self.br.meta.emit((disc, [m for v in prov.values() for m in v]))
        threading.Thread(target=job, daemon=True).start()

    def _got_meta(self, result: tuple):
        disc, metas = result
        if disc is not self.disc:                      # verspätete Antwort für eine inzwischen gewechselte Disc
            return
        self.metas = metas
        self.metacombo.clear()
        for m in metas:
            self.metacombo.addItem(f"[{m.source}] {m.artist} – {m.album} ({m.year})")
        if metas:
            self._apply_meta(metas[0])
            srcs = sorted({m.source for m in metas})
            self.statusBar().showMessage(tr("{0} Treffer von {1} – „Prüfen…“ vergleicht die Anbieter.").format(len(metas), ', '.join(srcs)))
        else:
            self.statusBar().showMessage(tr("Keine Metadaten gefunden – „Manuell suchen…“ oder von Hand eintragen."))

    def review(self):
        if not self.metas or not self.disc:
            QMessageBox.information(self, "psyrip", tr("Keine Metadaten zum Vergleichen vorhanden."))
            return
        n = len(self.disc.audio_tracks)
        cur = cdrip.DiscMeta(self.album.text(), self.artist.text(), self.year.text(), self.genre.text(),
                             [(self.table.item(r, 2).text(), self.table.item(r, 3).text()) for r in range(self.table.rowCount())
                              if self.table.item(r, 1).text() != "0"][:n], self.meta.mbid, self.meta.cover)
        dlg = ReviewDialog(self.metas, cur, n, self)
        if dlg.exec():
            self._apply_meta(dlg.result_meta)

    def _set_cover(self, data: bytes | None):
        self.meta.cover = data
        pm = QPixmap()
        if data and pm.loadFromData(data):
            self.coverlbl.setPixmap(pm.scaled(126, 126, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.coverlbl.setPixmap(QPixmap())
            self.coverlbl.setText(tr("kein Cover"))

    def _cover_net(self):
        from .cover_dialog import CoverDialog
        d = CoverDialog(self.albumartist.text() or self.artist.text(), self.album.text(), self,
                        int(self.cfg.get("cover_size", 1500)), self.cfg.get("itunes_country", "us"))
        if d.exec() and d.data:
            self._set_cover(d.data)

    def _cover_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Cover", "", tr("Bilder (*.jpg *.jpeg *.png)"))
        if f:
            self._set_cover(Path(f).read_bytes())

    def _cover_clip(self):
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        img = QGuiApplication.clipboard().image()
        if not img.isNull():
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "JPG", 92)
            self._set_cover(bytes(ba))

    def manual_search(self):
        n = len(self.disc.audio_tracks) if self.disc else None
        dlg = SearchDialog(n, self.cfg.get("discogs_token", ""), self)
        dlg.artist.setText(self.artist.text())
        dlg.album.setText(self.album.text())
        dlg.barcode.setText(self.barcode.text())
        if dlg.exec() and dlg.result_meta:
            self.metas.insert(0, dlg.result_meta)
            self.metacombo.insertItem(0, f"[{dlg.result_meta.source}] {dlg.result_meta.artist} – {dlg.result_meta.album}")
            self._apply_meta(dlg.result_meta)

    def _fetch_cover_bg(self, m: cdrip.DiscMeta):
        """Cover im Hintergrund holen: Quelle, Größe und Apple-Land stehen in den Einstellungen."""
        c = self.cfg
        artist, album = m.artist, m.album

        def job():
            data, src = cdrip.best_cover(artist, album, m.mbid, c.get("cover_source", "auto"), int(c.get("cover_size", 1500)),
                                         c.get("itunes_country", "us"))
            if data:
                m.cover, m.cover_source = data, src
                self.br.cover.emit(m)
        self.statusBar().showMessage(tr("Cover wird geladen…"))
        threading.Thread(target=job, daemon=True).start()

    def _got_cover(self, m: cdrip.DiscMeta):
        if m is self.meta and m.cover:
            self._set_cover(m.cover)
            pm = QPixmap()
            pm.loadFromData(m.cover)
            self.statusBar().showMessage(tr("Cover: {0}, {1}×{2}").format(getattr(m, "cover_source", "?"), pm.width(), pm.height()))

    def _apply_meta(self, m: cdrip.DiscMeta):
        self.meta = m
        self.release_type.setText(m.release_type)
        self.comp.setChecked("compilation" in m.release_type)
        if m.source == "MusicBrainz":                                   # CD-Nummer und Genres aus dem Release übernehmen
            self.disc_total.setValue(max(m.disc_total, 1))
            self.disc_no.setValue(max(min(m.disc_position, self.disc_total.value()), 1))
            self.genre.setText("; ".join(m.genres[:3]) or m.genre)
        self.mb_info.setText(" · ".join(x for x in (m.label, m.catalog, m.country, m.media_format, m.status, m.barcode) if x)
                             + (f"\nMusicBrainz: {m.mbid}" if m.mbid else ""))
        if m.cover is None:
            self._set_cover(None)
            self._fetch_cover_bg(m)
        self.album.setText(m.album)
        self.artist.setText(m.artist)
        self.year.setText(m.year)
        if m.source != "MusicBrainz":
            self.genre.setText(m.genre)
        rows = [r for r in range(self.table.rowCount()) if self.table.item(r, 1).text() != "0"]    # HTOA hat nie Metadaten
        for r, (title, artist) in zip(rows, m.tracks):
            self.table.item(r, 2).setText(title)
            self.table.item(r, 3).setText(artist)
        pm = QPixmap()
        if m.cover and pm.loadFromData(m.cover):
            self.coverlbl.setPixmap(pm.scaled(126, 126, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def detect_offset(self):
        if not self.disc:
            QMessageBox.information(self, "psyrip", tr("Bitte zuerst die Disc lesen."))
            return
        disc, letter = self.disc, self.drive.currentText()
        self.statusBar().showMessage(tr("Offset wird bestimmt (liest einen Track, dauert ca. 30 s)…"))

        def job():
            try:
                entries = cdrip.fetch_accuraterip(disc)
                if not entries:
                    self.br.error.emit(tr("Disc nicht in AccurateRip – Offset kann so nicht bestimmt werden."))
                    return
                with cdrip.CDDrive(letter) as d:
                    off = cdrip.detect_offset(d, disc, entries, progress=lambda f: self.br.status.emit(-1, tr("Offset-Suche {0} %").format(int(f * 100))))
                self.br.offset.emit(off)
            except Exception as e:
                self.br.error.emit(tr("Offset-Erkennung fehlgeschlagen: {0}").format(e))
        threading.Thread(target=job, daemon=True).start()

    def _got_offset(self, off):
        if off is None:
            QMessageBox.information(self, "psyrip", tr("Kein passender Offset gefunden (Pressung evtl. abweichend)."))
        else:
            self.offset.setValue(off)
            self.statusBar().showMessage(tr("Laufwerks-Offset: {0:+d} Samples").format(off))

    # ----------------------------------------------------------------- Rippen
    def start(self):
        if self.session:
            self.session.cancel.set()
            return
        if not self.disc:
            QMessageBox.information(self, "psyrip", tr("Bitte zuerst die Disc lesen."))
            return
        sel = [int(self.table.item(r, 1).text()) for r in range(self.table.rowCount()) if self.table.item(r, 0).checkState() == Qt.Checked]
        if not sel:
            return
        if not self.album.text().strip() and not self.artist.text().strip() and QMessageBox.question(
                self, "psyrip", tr("Album und Künstler sind leer – trotzdem rippen?\n\nOrdner und Dateinamen entstehen aus diesen Angaben.")
        ) != QMessageBox.Yes:
            return
        self.meta.album, self.meta.artist = self.album.text(), self.artist.text()
        self.meta.release_type = self.release_type.text().strip()
        tm = {int(self.table.item(r, 1).text()): TrackMeta(self.table.item(r, 2).text(), self.table.item(r, 3).text()) for r in range(self.table.rowCount())}
        out = self.out.spec()
        out.mode = "dynamic"
        settings = ConvertSettings(encoder=self.enc.encoder, enc_settings=self.enc.settings, output=out, dsp=self.dsp.steps(), workers=1)
        opts = cdrip.RipOptions(secure=self.secure.isChecked(), passes=self.passes.value(), max_rereads=self.rereads.value(),
                                sample_offset=self.offset.value(), cache_sectors=self.cache.value() * 1024 // 2048,
                                overread=self.overread.isChecked(), abort_after_unrecoverable=self.abort_n.value())
        job = RipJob(self.drive.currentText(), self.disc, sel, self.meta, tm, settings, opts, self.comp.isChecked(), self.disc_no.value(),
                     self.disc_total.value(), self.genre.text(), self.year.text(), self.albumartist.text(), self.ar.isChecked(), self.as_one.isChecked(),
                     self.track_offset, self.err_insecure.isChecked(), self.err_inacc.isChecked(), self.cancel_insecure.isChecked(),
                     self.mb_tags.currentData() != "off", self.mb_tags.currentData() if self.mb_tags.currentData() != "off" else "basic")
        cfgmod.update(self.cfg, rip_encoder=self.enc.encoder, rip_folder=cfgmod.portable_folder(out.folder), rip_naming=out.naming,
                      rip_secure=opts.secure, rip_passes=opts.passes, rip_rereads=opts.max_rereads)
        self._remember()
        self.session = RipSession(job, self.br.status.emit, self.br.progress.emit, lambda n, r, o: self.br.crc.emit(n, r.crc_v1))
        self._tracks = sel
        self._frac = {n: 0.0 for n in sel}
        self.go.setText(tr("Abbrechen"))

        def run():
            try:
                res = self.session.run()
                self.session.write_log(Path(out.folder))
                self.br.finished.emit(res)
            except Exception as e:
                self.br.error.emit(str(e))
                self.br.finished.emit([])
        threading.Thread(target=run, daemon=True).start()

    def _row(self, n: int) -> int:
        return next(r for r in range(self.table.rowCount()) if self.table.item(r, 1).text() == str(n))

    def _status(self, n: int, text: str):
        if n >= 0:
            self.table.item(self._row(n), 5).setText(text)
        else:
            self.statusBar().showMessage(text)

    # ------------------------------------------------------------ Track-Menü
    def _track_menu(self, pos):
        if self.table.rowCount() == 0:
            return
        m = QMenu(self)
        m.addAction(tr("Ausgewählte Tracks rippen"), self._rip_selected)
        m.addSeparator()
        m.addAction(tr("Artist und Titel vertauschen (Compilation)"), self._swap_artist_title)
        m.addAction(tr("Artist aus Titeln erkennen („Artist - Titel“)"), self._detect_artists)
        m.addAction(tr("Track-Nummern-Offset…"), self._ask_offset)
        m.addSeparator()
        m.addAction(tr("Trackliste in die Zwischenablage"), self._copy_list)
        m.addAction(tr("Titel aus Zwischenablage einfügen"), self._paste_titles)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _selected_rows(self) -> list[int]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return rows or list(range(self.table.rowCount()))

    def _rip_selected(self):
        sel = set(self._selected_rows())
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(Qt.Checked if r in sel else Qt.Unchecked)
        self.start()

    def _swap_artist_title(self):
        for r in self._selected_rows():
            a, t = self.table.item(r, 3), self.table.item(r, 2)
            a_txt, t_txt = a.text(), t.text()
            a.setText(t_txt)
            t.setText(a_txt)

    def _detect_artists(self):
        for r in self._selected_rows():
            t = self.table.item(r, 2)
            if " - " in t.text() and not self.table.item(r, 3).text().strip():
                artist, title = t.text().split(" - ", 1)
                self.table.item(r, 3).setText(artist.strip())
                t.setText(title.strip())

    def _ask_offset(self):
        v, ok = QInputDialog.getInt(self, tr("Track-Nummern-Offset"), tr("Wird auf alle Track-Nummern addiert (z. B. 100 für CD 2):"), self.track_offset, 0, 9999)
        if ok:
            self.track_offset = v
            self.statusBar().showMessage(tr("Track-Nummern-Offset: +{0}").format(v))

    def _copy_list(self):
        QGuiApplication.clipboard().setText("\n".join(
            f"{self.table.item(r, 3).text()} - {self.table.item(r, 2).text()}" if self.table.item(r, 3).text() else self.table.item(r, 2).text()
            for r in range(self.table.rowCount())))

    def _paste_titles(self):
        lines = [l.strip() for l in QGuiApplication.clipboard().text().splitlines() if l.strip()]
        rows = [r for r in range(self.table.rowCount()) if self.table.item(r, 1).text() != "0"]
        for r, line in zip(rows, lines):
            if " - " in line:
                a, t = line.split(" - ", 1)
                self.table.item(r, 3).setText(a.strip())
                self.table.item(r, 2).setText(t.strip())
            else:
                self.table.item(r, 2).setText(line)

    def _progress(self, n: int, f: float):
        self._frac[n] = f
        self.prog.setValue(int(sum(self._frac.values()) / len(self._frac) * 100))

    def _finished(self, results: list):
        for r in results:
            if r.pcm_path is None and not r.cancelled:
                self.table.item(self._row(r.track), 6).setText(f"{r.crc_v1:08X}")
        self.session = None
        self.go.setText("Rip")
        bad = [r.track for r in results if not r.secure]
        self.statusBar().showMessage(tr("Fertig.") + (tr(" Unsichere Tracks: {0}").format(bad) if bad else tr(" Alle Tracks sicher gelesen.")))
        mode = self.after.currentData()
        if results and not any(r.cancelled for r in results):
            if mode == "eject" or (mode == "eject_secure" and not bad):
                self._eject()
            elif mode == "shutdown":
                import subprocess
                if os.name == "nt":
                    subprocess.run(["shutdown", "/s", "/t", "60", "/c", tr("psyrip: Rip abgeschlossen – Herunterfahren in 60 s (abbrechen: shutdown /a)")])
                else:                                       # systemd: Herunterfahren in 1 min, abbrechen mit shutdown -c
                    subprocess.run(["shutdown", "-h", "+1", tr("psyrip: Rip abgeschlossen – Herunterfahren in 1 min (abbrechen: shutdown -c)")])

    def _eject(self):
        if self.drive.currentText() and os.name != "nt":
            try:
                with cdrip.CDDrive(self.drive.currentText()) as d:
                    d.eject()
            except OSError as e:
                self.statusBar().showMessage(tr("Auswerfen fehlgeschlagen: {0}").format(e))
        elif self.drive.currentText():
            import ctypes
            ctypes.windll.winmm.mciSendStringW(f"open {self.drive.currentText()} type cdaudio alias cd", None, 0, None)
            ctypes.windll.winmm.mciSendStringW("set cd door open", None, 0, None)
            ctypes.windll.winmm.mciSendStringW("close cd", None, 0, None)
