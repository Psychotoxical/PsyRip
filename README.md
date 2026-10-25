# psyrip

A Windows audio toolkit modelled on dBpoweramp: **Music Converter**, **Batch Converter**, **CD Ripper** (secure ripping + AccurateRip),
**ID Tag Editor**, **DSP effects**, **utility codecs** and a **Control Center**. Own implementation (Python, PySide6, mutagen, ffmpeg) –
no code or assets from the original.

The interface is **English by default**, **German** is available under *Settings → Language* (applied after a restart).
A German version of this document: [README.de.md](README.de.md).

## Run

```
pip install -r requirements.txt
python -m psyrip                 # Control Center
python -m psyrip convert a.flac  # Music Converter with files
python -m psyrip batch | rip | tags <files> | utilities <files>
python -m psyrip cli -infile a.wav -outfile a.flac -convert_to FLAC -set level=8
python -m pytest                 # tests
```

When running from source, ffmpeg must be on `PATH`, in `bin\ffmpeg.exe`, or set in the Control Center. A build with libmp3lame,
libopus, libvorbis and libspeex is required for all encoders (e.g. the Gyan “full” build).

## Installer / EXE

`build.bat` creates `dist\psyrip\psyrip.exe` (runs without Python) **including `bin\ffmpeg.exe`** (taken from `FFMPEG_DIR` or the ffmpeg
on `PATH`, plus its GPL licence text; ffprobe is not needed – `ffmpeg -i` is used instead). Unused Qt parts (QML/Quick, PDF,
network, software OpenGL) are removed. If Inno Setup 6 is installed it also builds
`installer_out\psyrip-setup-<version>.exe`: per-user install without admin rights (or for all users), Start-menu entry, optional
desktop icon, German or English. Choosing German in the setup sets the app language to German too. The uninstaller removes the
Explorer context-menu entries again. Nothing has to be installed afterwards. Lookup order for ffmpeg: path from the settings →
bundled `bin` → `PATH`.

## Language

* Default: English. Switch under *Settings → Language*; the change is fully applied after restarting psyrip (the dialog offers a restart).
* Stored in `%APPDATA%\psyrip\config.json` (`"language": "en" | "de"`); the environment variable `PSYRIP_LANG` overrides it.
* The source text in the code is German; `psyrip/translations.py` maps every string to English, `psyrip/i18n.py` provides `tr()`.
  `tests/test_i18n.py` makes sure every `tr()` key has an English entry and that placeholders match.

## Feature comparison (v0.3.0)

Source of the original’s behaviour: REA analysis of the installation (2025.02.07) plus the bundled help.

| Area | Original | psyrip |
|---|---|---|
| Music Converter: file list, drag & drop, encoder options, Output To (source folder / single folder / preserve path / dynamic), profiles, cores, priority | ✔ | ✔ |
| Dynamic naming incl. all programmable actions (`[IFCOMP]`, `[GRAB]`, `[SETLEN]`, `[SPLIT]`, …) and a naming editor | ✔ | ✔ (tested against the help’s examples) |
| Encoders: mp3 Lame, FLAC, AAC, ALAC, Opus, Vorbis, Wave, AIFF, WavPack, WMA, Speex, m4b | ✔ | ✔ (via ffmpeg) |
| Encoders: m4a FDK, Musepack, Monkey’s Audio, DSD (.dsf) | ✔ (bundled programs) | ✔ as external programs (`fdkaac`, `mppenc`, `mac`, `sox`; WAV on stdin, as in the original). The programs are not included: set their paths in the Control Center. Pipeline tested with a stand-in program; command lines only checked against the original’s templates, **not with the real tools** |
| Embedded cover art in every format (ID3, MP4, Vorbis comment pictures, ASF, APEv2) | ✔ | ✔ tested for all 12 ffmpeg-based encoders (embedded and still playable); Monkey’s/Musepack/DSD covers written the same way but **not tested** (no tool installed) |
| Cover download: Apple Music (iTunes Search API) and MusicBrainz/Cover Art Archive, selectable or “largest of both”, size cap 500–3000 px (never upscaled), Apple store country | – | ✔ e.g. Lenny Kravitz “Lenny”: Cover Art Archive has 600×600, Apple 1405×1401 |
| MusicBrainz tags written while ripping (Picard-compatible): release/release-group/artist/recording/track IDs, release type (album, single, EP, compilation, live …), status, country, original date, label, catalog number, barcode, ASIN, media, ISRC | – | ✔ tested on a real disc and round-tripped in all 12 ffmpeg-based formats |
| “Fetch from MusicBrainz” in the tag editor for existing files: search or release ID/URL, track matching (number/title/order), choose field groups (core, IDs, details, credits, extras), optional cover | – | ✔ tested on copies of real files |
| Full MusicBrainz detail while ripping: composer, lyricist, producer, engineer, mixer, arranger, performers with instruments, work + work ID, language, sort names, genres, totals, disc subtitle, disambiguation | – | ✔ tested on a real disc in mp3, m4a, Opus, FLAC |
| Verify written audio | ✔ | ✔ (lossless, without DSP) |
| DSP: resample, bit depth (+dither), channel count/mapper, fade, trim, grabber, max/min length, write silence, trim silence, high/low/band-pass, 10-band EQ, compressor, karaoke, loop, reverse, speed, volume normalize, ReplayGain (+apply), HDCD, de-emphasis, insert audio | ✔ | ✔ |
| DSP actions: ID tag processing, delete source, delete/move destination on error, Folder.jpg preserve, playlist writer, preserve attributes, run external, play sound, conditional encoding, CPU throttle, multi-CPU force, read/write metadata file | ✔ | ✔ (incl. XSLT via lxml, cover size/JPG/Folder.jpg handling, audio CRC/MD5 tag) |
| DSP: DirectX and VST plug-ins | ✔ | ✘ → replaced by “Custom ffmpeg Filter” (LADSPA/LV2 through ffmpeg) |
| Batch Converter: folder tree with check marks, filter (type/artist), property list, drag & drop | ✔ | ✔ |
| ID Tag Editor: multi-file editing with `<different>`, paging, cover (file/clipboard/Folder.jpg/internet), autocompletion | ✔ | ✔ (scanner ✘) |
| Utility codecs: Audio Info, Calculate Audio CRC, Arrange Audio, Tag From Filename, ID Tag Update, Length Split, Channel Split, Multi-Encoder, ReplayGain | ✔ | ✔ |
| CD Ripper: TOC, burst, secure (multi-pass, re-reads, cache flush), drive offset (auto-detect), AccurateRip v1/v2, Rip as One, profiles, track menu, abort rules, mark-as-error, eject/shutdown | ✔ | ✔ tested with a real disc (12/12 tracks secure and AccurateRip-confirmed); damaged discs untested |
| CD Ripper: metadata providers (MusicBrainz, GnuDB, Discogs with token), barcode, manual search incl. URL, review dialog, cover from the internet | ✔ (PerfectMeta, 5 providers) | ✔ MusicBrainz tested live; the GnuDB server was unreachable during testing (parser tested); Discogs untested without a token |
| CD Ripper: HTOA, lead-in/-out overread | ✔ | ✔ code present, **not tested on a suitable disc** |
| CD Ripper: C2 error pointers, “Defective by Design”, communication modes (SCSI/ASPI) | ✔ | ✘ (the Windows driver interface provides no C2) |
| Control Center: codec overview, internet switch, ffmpeg/theme/language/tag fields, Explorer context menu (HKCU) | ✔ | ✔ (property handler, thumbnails, popup info ✘ – need a native shell extension) |
| CLI (CoreConverter) | ✔ | ✔ `python -m psyrip cli` |

## Architecture

```
psyrip/
  naming.py     dynamic-naming parser/evaluator
  encoders.py   encoder registry → ffmpeg arguments / external tools
  dsp.py        DSP effects (filter graph) and actions (hooks before/after file and batch)
  converter.py  job pipeline, thread pool, progress, tags/cover, verify
  tags.py, tagproc.py   mutagen layer, tag rules
  analysis.py   loudness, peak, audio hash, ffprobe
  utilities.py  utility codecs
  cdrip.py, ripper.py   TOC/IOCTL, ripping, AccurateRip, metadata providers, rip session
  i18n.py, translations.py   language switching (English default, German)
  gui/          Control Center, converter, batch, tag editor, CD ripper, utilities, theme
tests/          pytest; tools/screenshots.py renders all windows as PNG
```
