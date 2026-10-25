# psyrip

Audio-Toolkit für Windows und Linux: **Music Converter**, **Batch Converter**, **CD Ripper** (Secure + AccurateRip,
MusicBrainz-Metadaten, große Cover), **ID-Tag-Editor**, **DSP-Effekte**, **Utilities** und ein **Control Center**.
Geschrieben in Python mit PySide6, mutagen und ffmpeg.

Die Oberfläche ist standardmäßig **Englisch**, **Deutsch** lässt sich unter *Einstellungen → Sprache* wählen
(wirksam nach einem Neustart).

## Start

```
pip install -r requirements.txt
python -m psyrip                 # Control Center
python -m psyrip convert a.flac  # Music Converter mit Dateien
python -m psyrip batch | rip | tags <Dateien> | utilities <Dateien>
python -m psyrip cli -infile a.wav -outfile a.flac -convert_to FLAC -set level=8
python -m pytest                 # Tests
PSYRIP_HW_TEST=1 python -m pytest tests/test_cd_hardware.py   # mit echter Audio-CD (PSYRIP_HW_EJECT=1: auch Lade auf/zu)
```

Beim Start aus dem Quellcode muss ffmpeg im `PATH` liegen, in `bin\ffmpeg.exe` oder im Control Center (Einstellungen) gesetzt werden.
Für alle Encoder wird eine ffmpeg-Version mit libmp3lame, libopus, libvorbis, libspeex benötigt (z. B. Gyan „full“).

## Linux

psyrip läuft auch unter Linux (getestet mit CachyOS/Arch, KDE Plasma auf Wayland, Python 3.14, PySide6 6.12).

```
sudo pacman -S ffmpeg python          # bzw. das Paket der eigenen Distribution
./start.sh                            # legt beim ersten Start .venv an und installiert requirements.txt
./start.sh rip                        # Argumente wie bei python -m psyrip
```

Unterschiede zu Windows:

- Einstellungen liegen in `~/.config/psyrip` (statt `%APPDATA%\psyrip`), Standard-Ausgabeordner ist der XDG-Musik-Ordner.
- CD-Laufwerke heißen `/dev/sr0`, `/dev/sr1` … Gelesen wird per SG_IO (READ TOC / READ CD). Der Benutzer braucht
  Lese-/Schreibrechte auf das Gerät (Gruppe `optical` oder die übliche uaccess-ACL der Desktop-Sitzung).
  Secure-Rip, Offset-Erkennung und AccurateRip wurden mit einer echten Disc getestet.
- „Desktop-Integration“ im Control Center legt statt der Explorer-Einträge einen Startmenü-Eintrag, „Öffnen mit“-Einträge
  und ein Dolphin-Kontextmenü (Untermenü „psyrip“) unter `~/.local/share` an.
- „Herunterfahren nach dem Rippen“ nutzt `shutdown -h +1` (abbrechen: `shutdown -c`), „Niedrige Priorität“ nutzt `nice`.
- Die Windows-EXE/den Installer (`build.bat`) gibt es nur unter Windows.

## Installer / EXE

`build.bat` erzeugt `dist\psyrip\psyrip.exe` (läuft ohne Python) **inklusive `bin\ffmpeg.exe`** (aus `FFMPEG_DIR` bzw. dem
ffmpeg im `PATH`, samt GPL-Lizenztext; ffprobe wird nicht gebraucht – stattdessen `ffmpeg -i`). Ungenutzte Qt-Teile (QML/Quick,
PDF, Netzwerk, Software-OpenGL) werden entfernt. Ist Inno Setup 6 installiert, entsteht zusätzlich
`installer_out\psyrip-setup-<Version>.exe`: Installation pro Benutzer ohne Admin-Rechte (oder für alle Benutzer), Startmenü-Eintrag,
optionales Desktop-Symbol, Deutsch oder Englisch. Wer im Setup Deutsch wählt, bekommt auch die App auf Deutsch. Die Deinstallation
entfernt die Explorer-Kontextmenü-Einträge wieder. Nach der Installation muss nichts nachinstalliert werden. Suchreihenfolge für
ffmpeg: Pfad aus den Einstellungen → mitgeliefertes `bin` → `PATH`.

## Funktionen (Stand v0.3.0)

✔ = vorhanden, ✘ = nicht vorhanden. Die Hinweise sagen, wie eine Funktion getestet wurde.

| Bereich | Stand |
|---|---|
| Music Converter: Dateiliste, Drag & Drop, Encoder-Optionen, Ausgabe in Quellordner / Einzelordner / Quellpfad / dynamisches Naming, Profile, Kerne, Priorität; letzte Einstellungen und Profil werden gemerkt | ✔ |
| Dynamisches Naming mit programmierbaren Aktionen (`[IFCOMP]`, `[GRAB]`, `[SETLEN]`, `[SPLIT]`, …); Editor mit verständlichen Bausteinen, fertigen Vorlagen und Live-Vorschau | ✔ getestet |
| Encoder: mp3 (LAME), FLAC, AAC, ALAC, Opus, Vorbis, Wave, AIFF, WavPack, WMA, Speex, m4b | ✔ über ffmpeg |
| Encoder: m4a FDK, Musepack, Monkey's Audio, DSD (.dsf) | ✔ als externe Programme (`fdkaac`, `mppenc`, `mac`, `sox`; WAV über stdin). Die Programme liegen nicht bei: Pfad im Control Center setzen. Pipeline mit einem Ersatzprogramm getestet, **nicht mit den echten Tools** |
| Eingebettete Cover in jedem Format (ID3, MP4, Vorbis-Comment-Bilder, ASF, APEv2) | ✔ für alle 12 ffmpeg-Encoder getestet (eingebettet und weiter abspielbar); Monkey's/Musepack/DSD gleich geschrieben, aber **nicht getestet** |
| Cover-Download: Apple Music (iTunes Search API) und MusicBrainz/Cover Art Archive, wählbar oder „größtes aus beiden“, Größengrenze 500–3000 px (nie hochgerechnet), Apple-Store-Land | ✔ z. B. Lenny Kravitz „Lenny“: Cover Art Archive 600×600, Apple 1405×1401 |
| MusicBrainz-Tags beim Rippen (Picard-kompatibel): Release-/Release-Group-/Künstler-/Recording-/Track-IDs, Release-Typ (Album, Single, EP, Compilation, Live …), Status, Land, Erstveröffentlichung, Label, Katalognummer, Barcode, ASIN, Medium, ISRC | ✔ mit echter Disc getestet, in allen 12 ffmpeg-Formaten geschrieben und zurückgelesen |
| Volle MusicBrainz-Details beim Rippen: Komponist, Texter, Produzent, Toningenieur, Mixer, Arrangeur, Musiker mit Instrumenten, Werk + Werk-ID, Sprache, Sortiernamen, Genres, Gesamtzahlen, Disc-Untertitel, Zusatzangaben | ✔ mit echter Disc in mp3, m4a, Opus, FLAC getestet |
| „Von MusicBrainz holen“ im Tag-Editor für vorhandene Dateien: Suche oder Release-ID/URL, Track-Zuordnung (Nummer/Titel/Reihenfolge), Feldgruppen wählbar (Kern, IDs, Details, Credits, Extras), optional Cover | ✔ an Kopien echter Dateien getestet |
| Geschriebenes Audio verifizieren | ✔ verlustfrei, ohne DSP |
| DSP: Resample, Bit-Tiefe (+Dither), Kanalzahl/Kanal-Mapper, Fade, Trim, Grabber, Max/Min-Länge, Stille schreiben, Stille entfernen, Hoch-/Tief-/Bandpass, 10-Band-EQ, Kompressor, Karaoke, Loop, Reverse, Speed, Lautstärke normalisieren, ReplayGain (+Anwenden), HDCD, De-Emphasis, Audio einfügen | ✔ |
| DSP-Aktionen: ID-Tag-Verarbeitung, Quelle löschen, Ziel bei Fehler löschen/verschieben, Folder.jpg erhalten, Playlist schreiben, Attribute erhalten, externes Programm, Ton abspielen, bedingtes Encoding, CPU-Drossel, Multi-CPU, Metadaten-Datei lesen/schreiben | ✔ inkl. XSLT über lxml, Cover-Größe/JPG/Folder.jpg, Audio-CRC/MD5-Tag |
| Plug-in-Effekte: „Custom ffmpeg Filter“ (beliebige ffmpeg-Filter, LADSPA/LV2 über ffmpeg) | ✔ — DirectX-/VST-Plug-ins ✘ |
| Batch Converter: Ordnerbaum mit Häkchen, Filter (Typ/Künstler), Liste mit Eigenschaften, Drag & Drop | ✔ |
| ID-Tag-Editor: Mehrfachbearbeitung mit `<different>`, Blättern, Cover (Datei/Zwischenablage/Folder.jpg/Internet), Autovervollständigung | ✔ |
| Utilities: Audio Info, Audio-CRC, Arrange Audio, Tags aus Dateinamen, ID-Tag-Update, Längen-Split, Kanal-Split, Multi-Encoder, ReplayGain | ✔ |
| CD Ripper: TOC, Burst, Secure (Mehrfachlesen, jeder Durchgang am Stück, damit das Laufwerk hochdreht; Re-Reads mit Budget pro Track), Laufwerks-Offset (Autoerkennung), AccurateRip v1/v2, Rip as One, Profile, Track-Menü, Abbruchregeln, „als Fehler markieren“, Auswerfen/Herunterfahren, Lesegeschwindigkeit und CRC je Track | ✔ mit echten Discs getestet (12/12 Tracks Secure und AccurateRip-bestätigt; Secure-Rip ca. 12–15× an einem LG BH10LS30); beschädigte Discs ungetestet |
| CD Ripper: Disc wird beim Öffnen automatisch gelesen und Metadaten geladen (abschaltbar); bei neuer Disc werden die Felder geleert | ✔ |
| CD Ripper: Metadaten-Anbieter (MusicBrainz, GnuDB, Discogs mit Token), Barcode, manuelle Suche inkl. URL, Review-Dialog, Cover aus dem Internet | ✔ MusicBrainz real getestet; GnuDB-Server war beim Test nicht erreichbar (Parser getestet); Discogs ohne Token nicht getestet |
| CD Ripper: HTOA, Lead-in/-out-Overread | ✔ Code vorhanden, **nicht an einer passenden Disc getestet** |
| CD Ripper: C2-Fehlerzeiger | ✘ die Windows-Treiberschnittstelle liefert keine; Fehler werden per Mehrfachlesen mit Mehrheitsentscheid erkannt |
| Control Center: Codec-Übersicht, Internet-Schalter, ffmpeg/Design/Sprache/Tag-Felder, Explorer-Kontextmenü (HKCU) | ✔ (Property-Handler, Thumbnails, Popup-Infos ✘ – bräuchten eine native Shell-Erweiterung) |
| Kommandozeile: `python -m psyrip cli` / `psyrip.exe cli` | ✔ |

## Architektur

```
psyrip/
  naming.py     Dynamic-Naming-Parser/-Auswerter
  encoders.py   Encoder-Registry → ffmpeg-Argumente
  dsp.py        DSP-Effekte (Filtergraph) und Aktionen (Hooks vor/nach Datei und Batch)
  converter.py  Job-Pipeline, Thread-Pool, Fortschritt, Tags/Cover, Verify
  tags.py, tagproc.py   Mutagen-Schicht, Tag-Regeln
  analysis.py   Lautheit, Peak, Audio-Hash, Analyse (ffprobe oder ffmpeg -i)
  utilities.py  Utilities
  cdrip.py, ripper.py   TOC/IOCTL, Rippen, AccurateRip, Metadaten-Anbieter, Rip-Ablauf
  i18n.py, translations.py   Sprachumschaltung (Englisch Standard, Deutsch)
  gui/          Control Center, Converter, Batch, Tag-Editor, CD Ripper, Utilities, Theme
tests/          pytest; tools/screenshots.py rendert alle Fenster als PNG
```
