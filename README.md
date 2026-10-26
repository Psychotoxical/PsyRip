# psyrip

An audio toolkit for Windows and Linux: **Music Converter**, **Batch Converter**, **CD Ripper** (secure ripping + AccurateRip,
MusicBrainz metadata, large cover art), **ID Tag Editor**, **DSP effects**, **utilities** and a **Control Center**.
Written in Python with PySide6, mutagen and ffmpeg.

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
PSYRIP_HW_TEST=1 python -m pytest tests/test_cd_hardware.py   # with a real audio CD (PSYRIP_HW_EJECT=1: also open/close tray)
```

When running from source, ffmpeg must be on `PATH`, in `bin\ffmpeg.exe` (Linux: `bin/ffmpeg`), or set in the Control Center. A build with libmp3lame,
libopus, libvorbis and libspeex is required for all encoders (e.g. the Gyan “full” build).

## Linux

psyrip also runs on Linux – the same code as on Windows; platform differences are decided at runtime.
Tested on CachyOS/Arch, KDE Plasma on Wayland, Python 3.14, PySide6 6.12 and an LG BH10LS30.

### Arch / CachyOS: install the package

`packaging/arch/PKGBUILD` builds the current state of `main` on GitHub as a pacman package. It uses the distribution's Python
packages (`pyside6`, `python-mutagen`, `python-numpy`, `python-pillow`, `python-lxml`) and `ffmpeg`.

```
cd packaging/arch
makepkg -si                           # build and install (pacman pulls in missing dependencies)
psyrip                                # Control Center – or “psyrip” in the start menu
psyrip rip | convert <files> | tags <files> | cli …
```

The package provides the `psyrip` command, a start menu entry and the icon. It builds what is on GitHub – local changes only
after a push. The package version comes from `psyrip/__init__.py`; to install a new build with the same version on top, use
`makepkg -fsi`.

### Other distributions / from source

```
sudo pacman -S ffmpeg python          # or your distribution's packages
./start.sh                            # creates .venv on first run and installs requirements.txt
./start.sh rip                        # same arguments as python -m psyrip
```

### Differences from Windows

- Settings live in `~/.config/psyrip` (instead of `%APPDATA%\psyrip`); the default output folder is the XDG music folder.
- CD drives are `/dev/sr0`, `/dev/sr1` … psyrip sends SCSI commands to the drive via SG_IO (READ TOC, READ CD, SET CD SPEED).
  The user needs read/write access to the device (group `optical` or the usual uaccess ACL of the desktop session).
  The data read is byte-identical to `cd-paranoia`.
- Eject uses SCSI (ALLOW MEDIUM REMOVAL + START STOP UNIT) in the background – the kernel ioctl `CDROMEJECT` alone does not open
  the tray while another process holds the drive open. Opening takes a few seconds (the disc spins down).
- “Desktop integration” in the Control Center creates a start menu entry, “Open with” entries and a Dolphin context menu
  (submenu “psyrip”) under `~/.local/share` instead of the Explorer entries; “Remove entries” deletes them again.
- “Shut down after ripping” uses `shutdown -h +1` (cancel: `shutdown -c`), “Low priority” uses `nice`.
- The Control Center shows Unicode symbols instead of the Windows icon font (Segoe Fluent Icons).
- The Windows EXE/installer (`build.bat`) is Windows-only.

### Tests

`tests/test_linux.py` covers the Linux parts without hardware (including the drive with simulated SCSI responses).
`tests/test_cd_hardware.py` only runs with `PSYRIP_HW_TEST=1` and an audio CD in the drive: TOC, repeatable reads, comparison with
`cd-paranoia`, secure rip with AccurateRip confirmation; `PSYRIP_HW_EJECT=1` also opens and closes the tray.
`PSYRIP_HW_DRIVE=/dev/sr1` selects another drive.

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
* Stored in `%APPDATA%\psyrip\config.json` (Linux: `~/.config/psyrip/config.json`) (`"language": "en" | "de"`); the environment variable `PSYRIP_LANG` overrides it.
* The source text in the code is German; `psyrip/translations.py` maps every string to English, `psyrip/i18n.py` provides `tr()`.
  `tests/test_i18n.py` makes sure every `tr()` key has an English entry and that placeholders match.

## Features (v0.3.0)

✔ = available, ✘ = not available. The notes say how a feature was tested.

| Area | Status |
|---|---|
| Music Converter: file list, drag & drop, encoder options, output to source folder / single folder / preserved path / dynamic naming, profiles, cores, priority; last settings and profile are remembered | ✔ |
| Dynamic naming with programmable actions (`[IFCOMP]`, `[GRAB]`, `[SETLEN]`, `[SPLIT]`, …); editor with plain-language building blocks, ready-made templates and live preview | ✔ tested |
| Encoders: mp3 (LAME), FLAC, AAC, ALAC, Opus, Vorbis, Wave, AIFF, WavPack, WMA, Speex, m4b | ✔ via ffmpeg |
| Encoders: m4a FDK, Musepack, Monkey’s Audio, DSD (.dsf) | ✔ as external programs (`fdkaac`, `mppenc`, `mac`, `sox`; WAV on stdin). The programs are not included: set their paths in the Control Center. Pipeline tested with a stand-in program, **not with the real tools** |
| Embedded cover art in every format (ID3, MP4, Vorbis comment pictures, ASF, APEv2) | ✔ tested for all 12 ffmpeg-based encoders (embedded and still playable); Monkey’s/Musepack/DSD covers written the same way but **not tested** |
| Cover download: Apple Music (iTunes Search API) and MusicBrainz/Cover Art Archive, selectable or “largest of both”, size cap 500–3000 px (never upscaled), Apple store country | ✔ e.g. Lenny Kravitz “Lenny”: Cover Art Archive has 600×600, Apple 1405×1401 |
| MusicBrainz tags written while ripping (Picard-compatible): release/release-group/artist/recording/track IDs, release type (album, single, EP, compilation, live …), status, country, original date, label, catalog number, barcode, ASIN, media, ISRC | ✔ tested on a real disc and round-tripped in all 12 ffmpeg-based formats |
| Full MusicBrainz detail while ripping: composer, lyricist, producer, engineer, mixer, arranger, performers with instruments, work + work ID, language, sort names, genres, totals, disc subtitle, disambiguation | ✔ tested on a real disc in mp3, m4a, Opus, FLAC |
| “Fetch from MusicBrainz” in the tag editor for existing files: search or release ID/URL, track matching (number/title/order), choose field groups (core, IDs, details, credits, extras), optional cover | ✔ tested on copies of real files |
| Verify written audio | ✔ lossless, without DSP |
| DSP: resample, bit depth (+dither), channel count/mapper, fade, trim, grabber, max/min length, write silence, trim silence, high/low/band-pass, 10-band EQ, compressor, karaoke, loop, reverse, speed, volume normalize, ReplayGain (+apply), HDCD, de-emphasis, insert audio | ✔ |
| DSP actions: ID tag processing, delete source, delete/move destination on error, Folder.jpg preserve, playlist writer, preserve attributes, run external, play sound, conditional encoding, CPU throttle, multi-CPU force, read/write metadata file | ✔ incl. XSLT via lxml, cover size/JPG/Folder.jpg handling, audio CRC/MD5 tag |
| Plug-in effects: “Custom ffmpeg Filter” (any ffmpeg filter, LADSPA/LV2 through ffmpeg) | ✔ — DirectX/VST plug-ins ✘ |
| Batch Converter: folder tree with check marks, filter (type/artist), property list, drag & drop | ✔ |
| ID Tag Editor: multi-file editing with `<different>`, paging, cover (file/clipboard/Folder.jpg/internet), autocompletion | ✔ |
| Utilities: Audio Info, Calculate Audio CRC, Arrange Audio, Tag From Filename, ID Tag Update, Length Split, Channel Split, Multi-Encoder, ReplayGain | ✔ |
| CD Ripper: TOC, burst, secure (multi-pass, each pass read sequentially so the drive spins up, re-reads with a per-track budget), drive offset (auto-detect), AccurateRip v1/v2, Rip as One, profiles, track menu, abort rules, mark-as-error, eject/shutdown, read speed and CRC per track | ✔ tested with real discs (Windows: 12/12 tracks secure and AccurateRip-confirmed, secure rip ~12–15× on an LG BH10LS30; Linux: secure rip AccurateRip-confirmed, ~10× on the same drive model, offset auto-detected, eject tested); damaged discs untested |
| CD Ripper: disc is read and metadata loaded automatically when the ripper opens (can be turned off); fields are cleared for a new disc | ✔ |
| CD Ripper: metadata providers (MusicBrainz, GnuDB, Discogs with token), barcode, manual search incl. URL, review dialog, cover from the internet | ✔ MusicBrainz tested live; the GnuDB server was unreachable during testing (parser tested); Discogs untested without a token |
| CD Ripper: HTOA, lead-in/-out overread | ✔ code present, **not tested on a suitable disc** |
| CD Ripper: C2 error pointers | ✘ the Windows driver interface provides none; on Linux they could be requested via READ CD but are not (yet). Errors are detected by multi-pass majority vote |
| Control Center: codec overview, internet switch, ffmpeg/theme/language/tag fields, Explorer context menu (HKCU) or, on Linux, start menu, “Open with” and Dolphin menu | ✔ (property handler, thumbnails, popup info ✘ – would need a native shell extension) |
| Command line: `python -m psyrip cli` / `psyrip.exe cli` / `psyrip cli` (Linux package) | ✔ |

## Architecture

```
psyrip/
  naming.py     dynamic-naming parser/evaluator
  encoders.py   encoder registry → ffmpeg arguments / external tools
  dsp.py        DSP effects (filter graph) and actions (hooks before/after file and batch)
  converter.py  job pipeline, thread pool, progress, tags/cover, verify
  tags.py, tagproc.py   mutagen layer, tag rules
  analysis.py   loudness, peak, audio hash, probing (ffprobe or ffmpeg -i)
  utilities.py  utilities
  cdrip.py, ripper.py   TOC, drive access (Windows IOCTL / Linux SG_IO), ripping, AccurateRip, metadata providers, rip session
  paths.py      config and music folder per platform
  i18n.py, translations.py   language switching (English default, German)
  gui/          Control Center, converter, batch, tag editor, CD ripper, utilities, theme;
                shell_linux.py: desktop integration on Linux
tests/          pytest; tools/screenshots.py renders all windows as PNG
packaging/arch/ PKGBUILD for Arch/CachyOS
build.bat, installer/   Windows EXE and Inno Setup installer
start.bat, start.sh     run from source (Windows / Linux)
```
