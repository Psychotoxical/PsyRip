"""ID-Tag-Lesen/-Schreiben (Mutagen) mit einheitlichen Feldnamen und Albumcover."""
from __future__ import annotations

from .i18n import tr
from dataclasses import dataclass
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover

STANDARD_FIELDS = ["artist", "album", "title", "albumartist", "tracknumber", "discnumber",
                   "genre", "date", "composer", "comment", "compilation"]
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".mp4", ".m4b", ".ogg", ".oga", ".opus", ".wav", ".aif", ".aiff",
             ".wv", ".ape", ".wma", ".mpc", ".spx", ".dsf", ".dff", ".aac"}


@dataclass
class AudioInfo:
    length: float = 0.0
    bitrate: int = 0
    sample_rate: int = 0
    channels: int = 0
    bits: int = 0
    codec: str = ""


def read_info(path: str | Path) -> AudioInfo:
    f = mutagen.File(str(path))
    if f is None or f.info is None:
        return AudioInfo()
    i = f.info
    rate = int(getattr(i, "sample_rate", 0) or 0)
    if not rate and type(f).__name__ == "OggOpus":
        rate = 48000                      # Opus wird immer mit 48 kHz dekodiert (mutagen liefert keine Rate)
    return AudioInfo(
        length=float(getattr(i, "length", 0) or 0),
        bitrate=int(getattr(i, "bitrate", 0) or 0),
        sample_rate=rate,
        channels=int(getattr(i, "channels", 0) or 0),
        bits=int(getattr(i, "bits_per_sample", 0) or 0),
        codec=type(f).__name__,
    )


def _easy_tags(f):
    """Einheitliche Textfelder für f.tags. WAV/AIFF/DSF liefern mutagen-seitig rohes ID3 (auch mit easy=True),
    dafür wird ein EasyID3 auf dieselben Frames gelegt (sonst würden Tags stillschweigend nicht geschrieben)."""
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3
    if isinstance(f.tags, ID3) and not isinstance(f.tags, EasyID3):
        e = EasyID3()
        e._EasyID3__id3 = f.tags
        return e
    return f.tags


def read_tags(path: str | Path) -> dict[str, str]:
    try:
        f = mutagen.File(str(path), easy=True)
    except Exception:
        return {}
    if f is None or f.tags is None:
        return {}
    out: dict[str, str] = {}
    tg = _easy_tags(f)
    for k in tg.keys():
        if k.lower() in ("metadata_block_picture", "coverart", "coverartmime"):      # eingebettete Bilder gehören nicht ins Textfeld
            continue
        v = tg[k]
        out[k.lower()] = "; ".join(str(x).replace("\x00", "; ") for x in v) if isinstance(v, list) else str(v).replace("\x00", "; ")
    return out


def _register_keys() -> None:
    """Macht die Picard-kompatiblen MusicBrainz-Felder in ID3 (TXXX/TPUB) und MP4 (Freeform) über EasyTags schreibbar."""
    from mutagen.easyid3 import EasyID3
    from mutagen.easymp4 import EasyMP4Tags
    for key, desc in (("releasetype", "MusicBrainz Album Type"), ("releasestatus", "MusicBrainz Album Status")):
        EasyID3.RegisterTXXXKey(key, desc)
    EasyID3.RegisterTextKey("label", "TPUB")
    # Weitere Picard-Felder als TXXX-Frames (EasyID3 kennt sie nicht)
    for key, desc in (("musicbrainz_albumcomment", "MusicBrainz Album Comment"), ("script", "SCRIPT"), ("originalyear", "ORIGINALYEAR"),
                      ("totaltracks", "TOTALTRACKS"), ("totaldiscs", "TOTALDISCS"), ("artists", "ARTISTS"), ("engineer", "ENGINEER"),
                      ("mixer", "MIXER"), ("producer", "PRODUCER"), ("work", "WORK"), ("writer", "WRITER"), ("djmixer", "DJMIXER"),
                      ("remixer", "REMIXER")):
        if key not in EasyID3.valid_keys:
            EasyID3.RegisterTXXXKey(key, desc)
    if "comment" not in EasyID3.valid_keys:                  # Kommentar liegt im COMM-Frame; bisher wurde er in MP3 nie geschrieben
        from mutagen.id3 import COMM

        def _c_get(id3, key):
            return [t for f in id3.getall("COMM") for t in f.text]

        def _c_set(id3, key, value):
            id3.delall("COMM")
            id3.add(COMM(encoding=3, lang="eng", desc="", text=list(value)))

        EasyID3.RegisterKey("comment", _c_get, _c_set, lambda id3, key: id3.delall("COMM"))
    if "compilation" not in EasyMP4Tags.Get:                 # MP4: Compilation ist das Boolean-Atom "cpil", nicht ein Freeform-Feld
        EasyMP4Tags.RegisterKey("compilation", lambda t, k: ["1" if t.get("cpil") else "0"],
                                lambda t, k, v: t.__setitem__("cpil", str(v[0]).strip().lower() in ("1", "true", "yes")),
                                lambda t, k: t.pop("cpil", None))
    for key, desc in (("musicbrainz_albumcomment", "MusicBrainz Album Comment"), ("script", "SCRIPT"), ("language", "LANGUAGE"),
                      ("originalyear", "ORIGINALYEAR"), ("totaltracks", "TOTALTRACKS"), ("totaldiscs", "TOTALDISCS"),
                      ("discsubtitle", "DISCSUBTITLE"), ("artists", "ARTISTS"), ("engineer", "ENGINEER"), ("performer", "PERFORMER"),
                      ("mixer", "MIXER"), ("arranger", "ARRANGER"), ("producer", "PRODUCER"), ("work", "WORK"),
                      ("musicbrainz_workid", "MusicBrainz Work Id"), ("composer", "COMPOSER"), ("lyricist", "LYRICIST"),
                      ("writer", "WRITER"), ("conductor", "CONDUCTOR"), ("djmixer", "DJMIXER"), ("remixer", "REMIXER")):
        if key not in EasyMP4Tags.Get:
            EasyMP4Tags.RegisterFreeformKey(key, desc)
    for key, desc in (("musicbrainz_releasegroupid", "MusicBrainz Release Group Id"), ("musicbrainz_releasetrackid", "MusicBrainz Release Track Id"),
                      ("releasetype", "MusicBrainz Album Type"), ("releasestatus", "MusicBrainz Album Status"), ("originaldate", "originaldate"),
                      ("label", "LABEL"), ("catalognumber", "CATALOGNUMBER"), ("barcode", "BARCODE"), ("asin", "ASIN"),
                      ("media", "MEDIA"), ("isrc", "ISRC"), ("releasecountry", "MusicBrainz Album Release Country")):
        if key not in EasyMP4Tags.Get:
            EasyMP4Tags.RegisterFreeformKey(key, desc)


_register_keys()
MULTI_VALUE = {"releasetype", "musicbrainz_artistid", "musicbrainz_albumartistid", "genre", "composer", "lyricist", "writer", "conductor",
               "producer", "engineer", "mixer", "remixer", "djmixer", "arranger", "performer", "artists"}    # mehrere Werte (an "; " getrennt) als eigene Einträge


def write_tags(path: str | Path, tags: dict[str, str]) -> None:
    f = mutagen.File(str(path), easy=True)
    if f is None:
        raise ValueError(tr("Format nicht unterstützt: {0}").format(path))
    if f.tags is None:
        f.add_tags()
    tg = _easy_tags(f)
    for k, v in tags.items():
        if v == "" or v is None:
            if k in tg:
                del tg[k]
            continue
        try:
            tg[k] = [x.strip() for x in v.split(";") if x.strip()] if k in MULTI_VALUE else [v]
        except Exception:
            pass  # Feld in diesem Format nicht abbildbar
    f.save()


def read_art(path: str | Path) -> bytes | None:
    p = str(path)
    try:
        f = mutagen.File(p)
        if f is not None and type(f).__name__ in ("OggOpus", "OggVorbis", "OggFLAC", "OggSpeex"):
            import base64
            for b64 in f.get("metadata_block_picture", []):
                return Picture(base64.b64decode(b64)).data
            return None
        if isinstance(f, FLAC):
            return f.pictures[0].data if f.pictures else None
        if isinstance(f, MP4):
            c = f.tags.get("covr") if f.tags else None
            return bytes(c[0]) if c else None
        if type(f).__name__ == "ASF":
            for pic in f.get("WM/Picture", []):
                raw = bytes(pic.value)
                size = int.from_bytes(raw[1:5], "little")
                pos = 5
                for _ in range(2):                     # MIME und Beschreibung (UTF-16, nullterminiert)
                    while raw[pos:pos + 2] != b"\0\0":
                        pos += 2
                    pos += 2
                return raw[pos:pos + size]
            return None
        if f is not None and f.tags is not None:
            for k in f.tags.keys():
                if k.startswith("APIC"):
                    return f.tags[k].data
                if k.lower().startswith("cover art"):           # APEv2 (WavPack, Monkey's, Musepack)
                    raw = bytes(f.tags[k].value)
                    return raw.split(b"\0", 1)[1] if b"\0" in raw else raw
    except Exception:
        pass
    return None


def resize_art(data: bytes, max_px: int = 0, max_kb: int = 0, force_jpg: bool = False) -> bytes:
    """Verkleinert Cover (längste Kante ≤ max_px), begrenzt die Dateigröße und wandelt optional PNG → JPG."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    is_png = im.format == "PNG"
    changed = False
    if max_px and max(im.size) > max_px:
        im.thumbnail((max_px, max_px), Image.LANCZOS)
        changed = True
    if (is_png and force_jpg) or (max_kb and len(data) > max_kb * 1024):
        changed = True
    if not changed:
        return data
    q = 92
    while True:
        buf = io.BytesIO()
        if is_png and not force_jpg and not max_kb:
            im.save(buf, "PNG")
            break
        im.convert("RGB").save(buf, "JPEG", quality=q)
        if not max_kb or buf.tell() <= max_kb * 1024 or q <= 40:
            break
        q -= 10
    return buf.getvalue()


def process_art(path: str | Path, max_px: int = 0, max_kb: int = 0, force_jpg: bool = False,
                export: bool = False, import_: bool = False) -> None:
    """Cover-Nachbearbeitung einer fertigen Datei (Größe, JPG-Zwang, Folder.jpg Export/Import)."""
    p = Path(path)
    folder = p.parent / "Folder.jpg"
    data = read_art(p)
    if import_ and folder.exists():
        data = folder.read_bytes()
    if data and (max_px or max_kb or force_jpg):
        data = resize_art(data, max_px, max_kb, force_jpg)
    if data is not None and (max_px or max_kb or force_jpg or import_):
        write_art(p, data)
    if export and data:
        folder.write_bytes(data)


def write_art(path: str | Path, data: bytes | None) -> None:
    p = str(path)
    mime = "image/png" if data and data[:4] == b"\x89PNG" else "image/jpeg"
    ext = Path(p).suffix.lower()
    if ext in (".ogg", ".oga", ".opus", ".spx"):
        import base64
        f = mutagen.File(p)
        if f is None:
            return
        if "metadata_block_picture" in f:
            del f["metadata_block_picture"]
        if data:
            pic = Picture()
            pic.type, pic.mime, pic.data = 3, mime, data
            f["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
        f.save()
    elif ext == ".flac":
        f = FLAC(p)
        f.clear_pictures()
        if data:
            pic = Picture()
            pic.type, pic.mime, pic.data = 3, mime, data
            f.add_picture(pic)
        f.save()
    elif ext in (".m4a", ".mp4", ".m4b"):
        f = MP4(p)
        if data:
            f["covr"] = [MP4Cover(data, MP4Cover.FORMAT_PNG if mime.endswith("png") else MP4Cover.FORMAT_JPEG)]
        elif "covr" in f:
            del f["covr"]
        f.save()
    elif ext == ".mp3":
        try:
            t = ID3(p)
        except ID3NoHeaderError:
            t = ID3()
        t.delall("APIC")
        if data:
            t.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        t.save(p)
    elif ext in (".wav", ".aif", ".aiff", ".dsf"):
        f = mutagen.File(p)                    # ID3-Chunk im Container (nicht ans Dateiende/-anfang schreiben!)
        if f is None:
            return
        if f.tags is None:
            f.add_tags()
        f.tags.delall("APIC")
        if data:
            f.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        f.save()
    elif ext in (".wv", ".ape", ".mpc"):
        from mutagen.apev2 import BINARY, APEValue
        f = mutagen.File(p)
        if f is None:
            return
        if f.tags is None:
            f.add_tags()
        for k in [k for k in f.tags.keys() if k.lower().startswith("cover art")]:
            del f.tags[k]
        if data:
            name = "cover.png" if mime.endswith("png") else "cover.jpg"
            f.tags["Cover Art (Front)"] = APEValue(name.encode() + b"\0" + data, BINARY)
        f.save()
    elif ext in (".wma", ".asf"):
        import struct
        from mutagen.asf import ASF, ASFByteArrayAttribute
        f = ASF(p)
        f.pop("WM/Picture", None)
        if data:
            blob = struct.pack("<bi", 3, len(data)) + mime.encode("utf-16-le") + b"\0\0" + b"\0\0" + data
            f["WM/Picture"] = [ASFByteArrayAttribute(blob)]
        f.save()
