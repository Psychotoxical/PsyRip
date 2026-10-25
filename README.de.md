# psyrip

Windows-Toolkit für Audio nach dem Vorbild von dBpoweramp: **Music Converter**, **Batch Converter**,
**CD Ripper** (Secure + AccurateRip), **ID-Tag-Editor**, **DSP-Effekte**, **Utility Codecs** und ein
**Control Center**. Eigene Implementierung (Python, PySide6, mutagen, ffmpeg) – kein Code und keine Assets
des Originals.

## Start

```
pip install -r requirements.txt
python -m psyrip                 # Control Center
python -m psyrip convert a.flac  # Music Converter mit Dateien
python -m psyrip batch | rip | tags <Dateien> | utilities <Dateien>
python -m psyrip cli -infile a.wav -outfile a.flac -convert_to FLAC -set level=8
python -m pytest                 # Tests
```

Beim Start aus dem Quellcode muss ffmpeg im `PATH` liegen, in `bin\ffmpeg.exe` oder im Control Center (Einstellungen) gesetzt werden.
Für alle Encoder wird eine ffmpeg-Version mit libmp3lame, libopus, libvorbis, libspeex benötigt (z. B. Gyan „full“).

## Installer / EXE

`build.bat` erzeugt `dist\psyrip\psyrip.exe` (läuft ohne Python) **inklusive `bin\ffmpeg.exe`** (aus `FFMPEG_DIR` bzw. dem
ffmpeg im `PATH`, samt GPL-Lizenztext; ffprobe wird nicht gebraucht – stattdessen `ffmpeg -i`). Ungenutzte Qt-Teile (QML/Quick,
PDF, Netzwerk, Software-OpenGL) werden entfernt. Ist Inno Setup 6 installiert, entsteht zusätzlich
`installer_out\psyrip-setup-<Version>.exe`: Installation pro Benutzer ohne Admin-Rechte (oder für alle Benutzer), Startmenü-Eintrag,
optionales Desktop-Symbol, Deutsch oder Englisch. Wer im Setup Deutsch wählt, bekommt auch die App auf Deutsch. Die Deinstallation
entfernt die Explorer-Kontextmenü-Einträge wieder. Nach der Installation muss nichts nachinstalliert werden. Suchreihenfolge für
ffmpeg: Pfad aus den Einstellungen → mitgeliefertes `bin` → `PATH`.

## Funktionsvergleich (Stand v0.3.0)

Spalte „Beleg“ = woher die Funktion des Originals stammt (REA-Analyse der Installation, 2025.02.07, plus mitgelieferte Hilfe).

| Bereich | Original | psyrip |
|---|---|---|
| Music Converter: Dateiliste, Drag & Drop, Encoder-Optionen, Output To (Quellordner / Einzelordner / Quellpfad / Dynamic), Profile, Kerne, Priorität | ✔ | ✔ |
| Dynamic Naming inkl. aller programmierbaren Aktionen (`[IFCOMP]`, `[GRAB]`, `[SETLEN]`, `[SPLIT]`, …) | ✔ | ✔ (`psyrip/naming.py`, getestet gegen die Beispiele der Hilfe) |
| Encoder: mp3 Lame, FLAC, AAC, ALAC, Opus, Vorbis, Wave, AIFF, WavPack, WMA, Speex | ✔ | ✔ (via ffmpeg) |
| Encoder: m4b | ✔ | ✔ (nativ, ffmpeg) |
| Encoder: m4a FDK, Musepack, Monkey's Audio, DSD (.dsf) | ✔ (mitgelieferte Programme) | ✔ als externe Programme (`fdkaac`, `mppenc`, `mac`, `sox`; WAV über stdin wie im Original). Die Programme liegen nicht bei: Pfad im Control Center setzen. Pipeline mit einem Ersatzprogramm getestet, Kommandozeilen nur gegen die Vorlagen des Originals geprüft, **nicht mit den echten Tools** |
| Verify Written Audio | ✔ | ✔ (verlustfrei, ohne DSP) |
| DSP: Resample, Bit Depth (+Dither), Channel Count/Mapper, Fade, Trim, Grabber, Max/Min Length, Write Silence, Trim Silence, Hi/Low/Bandpass, 10-Band-EQ, Kompressor, Karaoke, Loop, Reverse, Speed, Volume Normalize (Peak/RG/EBU/Adaptiv/Fest/Reduce), ReplayGain (+Apply), HDCD, De-emphasis, Insert Audio | ✔ | ✔ |
| DSP-Aktionen: ID Tag Processing, Delete Source, Delete/Move Dest on Error, Folder.jpg Preserve, Playlist Writer, Preserve Attributes, Run External, Play Sound, Conditional Encoding, CPU Throttle, Multi-CPU Force, Read/Write Metadata File | ✔ | ✔ (inkl. XSLT über lxml, Cover-Größe/JPG-Zwang/Folder.jpg, Audio-CRC/MD5-Tag, Loop auf Länge, Kanal-Min/Max, Bedingungen nach Bit-Tiefe/Samplerate) |
| DSP: DirectX- und VST-Plug-ins | ✔ | ✘ → ersetzt durch „Custom ffmpeg Filter“ (LADSPA/LV2 über ffmpeg möglich) |
| Batch Converter: Ordnerbaum mit Häkchen, Filter (Typ/Künstler), Liste mit Eigenschaften, Drag & Drop | ✔ | ✔ |
| ID-Tag-Editor: Mehrfachbearbeitung mit `<different>`, Blättern, Cover (Datei/Zwischenablage/Folder.jpg), Autovervollständigung | ✔ | ✔ (Cover aus dem Internet via Cover Art Archive; Scanner ✘) |
| Utility Codecs: Audio Info, Calculate Audio CRC, Arrange Audio, Tag From Filename, ID Tag Update, Length Split, Channel Split, Multi-Encoder, ReplayGain | ✔ | ✔ |
| CD Ripper: TOC, Burst, Secure (Mehrfachlesen, Re-Reads, Cache-Flush), Laufwerks-Offset, AccurateRip v1/v2 + DB-Abfrage, MusicBrainz + Cover, Rip-Log, Auswerfen | ✔ | ✔ getestet mit echter Disc (12/12 Tracks Secure, AccurateRip-bestätigt; Offset-Erkennung per AccurateRip); beschädigte Discs ungetestet |
| CD Ripper: Offset-Autoerkennung, Rip as One, Profile, Track-Menü (Swap, Artist aus Titeln, Nummern-Offset, Clipboard), Abbruchregeln, „als Fehler markieren“ (→ Delete/Move on Error), Auswerfen/Herunterfahren nach dem Rip | ✔ | ✔ (Offset, Rip as One, 12/12 Tracks real getestet) |
| CD Ripper: Metadaten-Anbieter (MusicBrainz, GnuDB, Discogs mit Token), Barcode, manuelle Suche inkl. URL, Review-Dialog, Cover aus dem Internet | ✔ (PerfectMeta: 5 Anbieter; GD3/SonataDB nicht öffentlich) | ✔ MusicBrainz real getestet; GnuDB-Server war beim Test nicht erreichbar (Parser getestet); Discogs ohne Token nicht getestet |
| CD Ripper: HTOA, Lead-in/-out-Overread | ✔ | ✔ Code vorhanden, **nicht an einer passenden Disc getestet** (Testdisc hat kein HTOA) |
| CD Ripper: C2-Fehlerzeiger, „Defective by Design“, Kommunikationsmodi (SCSI/ASPI) | ✔ | ✘ (Windows-Treiberschnittstelle liefert kein C2) |
| Control Center: Codec-Übersicht, Internet-Schalter, ffmpeg/Design/Tag-Felder, Explorer-Kontextmenü (HKCU) | ✔ | ✔ (Property-Handler, Thumbnails, Popup-Infos ✘ – brauchen native Shell-Erweiterung) |
| CLI (CoreConverter) | ✔ | ✔ `python -m psyrip cli` |

## Architektur

```
psyrip/
  naming.py     Dynamic-Naming-Parser/-Auswerter
  encoders.py   Encoder-Registry → ffmpeg-Argumente
  dsp.py        DSP-Effekte (Filtergraph) und Aktionen (Hooks vor/nach Datei und Batch)
  converter.py  Job-Pipeline, Thread-Pool, Fortschritt, Tags/Cover, Verify
  tags.py, tagproc.py   Mutagen-Schicht, Tag-Regeln
  analysis.py   Lautheit, Peak, Audio-Hash, ffprobe
  utilities.py  Utility Codecs
  cdrip.py, ripper.py   TOC/IOCTL, Rippen, AccurateRip, MusicBrainz, Rip-Ablauf
  gui/          Control Center, Converter, Batch, Tag-Editor, CD Ripper, Utilities
tests/          pytest (47 Tests); tools/screenshots.py rendert alle Fenster als PNG
```
