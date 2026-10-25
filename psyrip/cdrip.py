"""CD-Ripper-Kern: TOC lesen, Burst-/Secure-Ripping über die Windows-IOCTL-Schnittstelle bzw. unter Linux
über SG_IO (SCSI-Befehle READ TOC / READ CD an /dev/srN), AccurateRip-Prüfsummen (v1/v2) samt Datenbankabfrage
und MusicBrainz-Metadaten.

Hinweis: Die Windows-Treiberschnittstelle (IOCTL_CDROM_RAW_READ) liefert keine C2-Fehlerzeiger; unter Linux werden
sie (noch) nicht angefordert, damit beide Plattformen gleich arbeiten.
Secure-Modus = Mehrfach-Lesen mit Mehrheitsentscheid je Sektor (wie der "Pass 1/2 + Re-Reads"-Ansatz,
ohne C2).
"""
from __future__ import annotations

from . import __version__
from .i18n import tr
import base64
import ctypes
import hashlib
import json
import os
import struct
import threading
import urllib.error
import urllib.request
import wave
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

SECTOR = 2352
FRAMES_PER_SECTOR = 588
IOCTL_CDROM_READ_TOC = 0x00024000
IOCTL_CDROM_RAW_READ = 0x0002403E
IOCTL_CDROM_SET_SPEED = 0x00024060
UA = f"psyrip/{__version__} (https://example.invalid/psyrip)"


# --------------------------------------------------------------------- TOC
@dataclass
class Track:
    number: int
    start: int            # LBA, nullbasiert
    end: int              # exklusiv
    audio: bool = True

    @property
    def sectors(self) -> int:
        return self.end - self.start

    @property
    def seconds(self) -> float:
        return self.sectors / 75


@dataclass
class Disc:
    tracks: list[Track]
    leadout: int
    drive: str = ""

    @property
    def audio_tracks(self) -> list[Track]:
        return [t for t in self.tracks if t.audio]


def _sha1_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha1(data).digest()).decode().replace("+", ".").replace("/", "_").replace("=", "-")


def freedb_id(d: Disc) -> int:
    def dsum(n: int) -> int:
        return sum(int(c) for c in str(n))
    n = sum(dsum((t.start + 150) // 75) for t in d.tracks)
    total = (d.leadout + 150) // 75 - (d.tracks[0].start + 150) // 75
    return ((n % 255) << 24) | (total << 8) | len(d.tracks)


def musicbrainz_disc_id(d: Disc) -> str:
    first, last = d.tracks[0].number, d.tracks[-1].number
    s = f"{first:02X}{last:02X}{d.leadout + 150:08X}"
    offs = {t.number: t.start + 150 for t in d.tracks}
    s += "".join(f"{offs.get(i, 0):08X}" for i in range(1, 100))
    return _sha1_b64(s.encode("ascii"))


def accuraterip_ids(d: Disc) -> tuple[int, int, int]:
    id1 = id2 = 0
    for i, t in enumerate(d.tracks, 1):
        id1 += t.start
        id2 += max(t.start, 1) * i
    n = len(d.tracks)
    id1 += d.leadout
    id2 += max(d.leadout, 1) * (n + 1)
    return id1 & 0xFFFFFFFF, id2 & 0xFFFFFFFF, freedb_id(d)


def accuraterip_url(d: Disc) -> str:
    id1, id2, cddb = accuraterip_ids(d)
    return (f"http://www.accuraterip.com/accuraterip/{id1 & 0xF:x}/{(id1 >> 4) & 0xF:x}/{(id1 >> 8) & 0xF:x}/"
            f"dBAR-{len(d.tracks):03d}-{id1:08x}-{id2:08x}-{cddb:08x}.bin")


def parse_toc_bytes(buf: bytes, drive: str = "") -> Disc:
    first, last = buf[2], buf[3]
    ents = []
    for i in range(0, (len(buf) - 4) // 8):
        r = buf[4 + i * 8: 12 + i * 8]
        if len(r) < 8:
            break
        control, number, (_, m, s, f) = r[1] & 0x0F, r[2], r[4:8]
        ents.append((number, control, (m * 60 + s) * 75 + f - 150))
        if number == 0xAA:
            break
    tracks, leadout = [], 0
    real = [e for e in ents if e[0] != 0xAA and first <= e[0] <= last]
    for e in ents:
        if e[0] == 0xAA:
            leadout = e[2]
    for idx, (n, ctrl, lba) in enumerate(real):
        end = real[idx + 1][2] if idx + 1 < len(real) else leadout
        tracks.append(Track(n, lba, end, audio=not (ctrl & 0x04)))
    return Disc(tracks, leadout, drive)


# ------------------------------------------------------------------ Laufwerk
class _WinCDDrive:
    def __init__(self, letter: str):
        from ctypes import wintypes
        self.letter = letter.rstrip(":\\").upper()
        k = ctypes.windll.kernel32
        k.CreateFileW.restype = wintypes.HANDLE
        self.h = k.CreateFileW(f"\\\\.\\{self.letter}:", 0x80000000, 3, None, 3, 0, None)
        if self.h in (None, wintypes.HANDLE(-1).value, -1):
            raise OSError(tr("Laufwerk {0}: kann nicht geöffnet werden").format(self.letter))

    def close(self):
        if self.h:
            ctypes.windll.kernel32.CloseHandle(self.h)
            self.h = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _ioctl(self, code: int, inbuf: bytes | None, outsize: int) -> bytes:
        from ctypes import wintypes
        out = ctypes.create_string_buffer(outsize)
        ret = wintypes.DWORD(0)
        inb = ctypes.create_string_buffer(inbuf, len(inbuf)) if inbuf else None
        ok = ctypes.windll.kernel32.DeviceIoControl(self.h, code, inb, len(inbuf) if inbuf else 0, out, outsize, ctypes.byref(ret), None)
        if not ok:
            raise OSError(ctypes.get_last_error() or ctypes.windll.kernel32.GetLastError(), tr("DeviceIoControl fehlgeschlagen"))
        return out.raw[:ret.value]

    def read_toc(self) -> Disc:
        return parse_toc_bytes(self._ioctl(IOCTL_CDROM_READ_TOC, None, 804), self.letter)

    def set_max_speed(self) -> None:
        """IOCTL_CDROM_SET_SPEED auf Maximum (0xFFFF) – manche Laufwerke bleiben sonst im leisen Modus.
        Nicht jedes Laufwerk unterstützt das; ein Fehler ist harmlos."""
        try:
            self._ioctl(IOCTL_CDROM_SET_SPEED, struct.pack("<IHHI", 0, 0xFFFF, 0xFFFF, 0), 0)
        except OSError:
            pass

    def read_sectors(self, lba: int, count: int) -> bytes:
        """Rohes CD-DA: count*2352 Bytes; Sektoren < 0 oder >= Leadout liefern Stille."""
        return self._ioctl(IOCTL_CDROM_RAW_READ, struct.pack("<qLL", lba * 2048, count, 2), count * SECTOR)


def _win_list_cd_drives() -> list[str]:
    import string
    k = ctypes.windll.kernel32
    return [f"{c}:" for c in string.ascii_uppercase if k.GetDriveTypeW(f"{c}:\\") == 5]


class _SgIoHdr(ctypes.Structure):
    """struct sg_io_hdr aus <scsi/sg.h>."""
    _fields_ = [("interface_id", ctypes.c_int), ("dxfer_direction", ctypes.c_int), ("cmd_len", ctypes.c_ubyte),
                ("mx_sb_len", ctypes.c_ubyte), ("iovec_count", ctypes.c_ushort), ("dxfer_len", ctypes.c_uint),
                ("dxferp", ctypes.c_void_p), ("cmdp", ctypes.c_void_p), ("sbp", ctypes.c_void_p),
                ("timeout", ctypes.c_uint), ("flags", ctypes.c_uint), ("pack_id", ctypes.c_int), ("usr_ptr", ctypes.c_void_p),
                ("status", ctypes.c_ubyte), ("masked_status", ctypes.c_ubyte), ("msg_status", ctypes.c_ubyte),
                ("sb_len_wr", ctypes.c_ubyte), ("host_status", ctypes.c_ushort), ("driver_status", ctypes.c_ushort),
                ("resid", ctypes.c_int), ("duration", ctypes.c_uint), ("info", ctypes.c_uint)]


SG_IO = 0x2285
SG_DXFER_NONE, SG_DXFER_FROM_DEV = -1, -3
CDROMEJECT = 0x5309
LINUX_READ_MAX = 26                   # Sektoren je READ CD (~60 KB, unter jeder max_sectors_kb-Grenze)


class _LinuxCDDrive:
    """Linux: SCSI-Befehle per SG_IO an /dev/srN. Braucht Lese-/Schreibrechte auf das Gerät
    (Gruppe „optical“ oder die uaccess-ACL der angemeldeten Sitzung)."""

    def __init__(self, device: str):
        self.letter = device                                  # Gerätepfad, z. B. /dev/sr0
        try:                                                  # O_NONBLOCK: Öffnen klappt auch ohne Medium
            self.fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            try:
                self.fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as e:
                raise OSError(e.errno, tr("Laufwerk {0}: kann nicht geöffnet werden").format(device)) from e

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _scsi(self, cdb: bytes, outsize: int, timeout_ms: int = 30000) -> bytes:
        import fcntl
        cmd = ctypes.create_string_buffer(cdb, len(cdb))
        out = ctypes.create_string_buffer(max(outsize, 1))
        sense = ctypes.create_string_buffer(32)
        h = _SgIoHdr(interface_id=ord("S"), dxfer_direction=SG_DXFER_FROM_DEV if outsize else SG_DXFER_NONE,
                     cmd_len=len(cdb), mx_sb_len=len(sense), dxfer_len=outsize,
                     dxferp=ctypes.cast(out, ctypes.c_void_p) if outsize else None,
                     cmdp=ctypes.cast(cmd, ctypes.c_void_p), sbp=ctypes.cast(sense, ctypes.c_void_p), timeout=timeout_ms)
        fcntl.ioctl(self.fd, SG_IO, h)
        if h.status or h.host_status or h.driver_status or (h.info & 1):
            key = sense.raw[2] & 0x0F if h.sb_len_wr > 2 else 0
            asc = sense.raw[12] if h.sb_len_wr > 13 else 0
            ascq = sense.raw[13] if h.sb_len_wr > 13 else 0
            raise OSError(5, tr("SCSI-Befehl {0:02X} fehlgeschlagen (Sense {1:X}/{2:02X}/{3:02X})").format(cdb[0], key, asc, ascq))
        return out.raw[:outsize - h.resid]

    def read_toc(self) -> Disc:
        # READ TOC, Format 0, MSF-Adressen – gleiches Layout wie CDROM_TOC unter Windows
        return parse_toc_bytes(self._scsi(struct.pack(">BBBxxxBHx", 0x43, 0x02, 0, 0, 804), 804), self.letter)

    def set_max_speed(self) -> None:
        """SET CD SPEED auf Maximum (0xFFFF). Nicht jedes Laufwerk unterstützt das; ein Fehler ist harmlos."""
        try:
            self._scsi(struct.pack(">BBHHxxxxxx", 0xBB, 0, 0xFFFF, 0xFFFF), 0)
        except OSError:
            pass

    def read_sectors(self, lba: int, count: int) -> bytes:
        """Rohes CD-DA: count*2352 Bytes per READ CD (Sektortyp CD-DA, nur Nutzdaten)."""
        out = []
        for o in range(0, count, LINUX_READ_MAX):
            n = min(LINUX_READ_MAX, count - o)
            cdb = struct.pack(">BBiBHBBx", 0xBE, 0x04, lba + o, n >> 16, n & 0xFFFF, 0x10, 0)
            data = self._scsi(cdb, n * SECTOR)
            if len(data) != n * SECTOR:
                raise OSError(5, tr("Laufwerk lieferte zu wenig Daten"))
            out.append(data)
        return b"".join(out)

    def eject(self) -> None:
        import fcntl
        fcntl.ioctl(self.fd, CDROMEJECT)


def _linux_list_cd_drives() -> list[str]:
    import glob
    import re
    devs = glob.glob("/dev/sr[0-9]*")
    return sorted(devs, key=lambda d: int(re.sub(r"\D", "", d) or 0))


if os.name == "nt":
    CDDrive, list_cd_drives = _WinCDDrive, _win_list_cd_drives
else:
    CDDrive, list_cd_drives = _LinuxCDDrive, _linux_list_cd_drives


# --------------------------------------------------------------- Rippen
@dataclass
class RipOptions:
    secure: bool = True
    passes: int = 2
    max_rereads: int = 20
    chunk: int = 26
    sample_offset: int = 0            # Laufwerks-Offset in Samples (AccurateRip)
    cache_sectors: int = 512          # 1024 KB
    abort_after_unrecoverable: int = 0  # 0 = nie
    interpolate: bool = False
    overread: bool = False             # Lead-in/-out lesen (laufwerksabhängig)


@dataclass
class RipResult:
    track: int
    pcm_path: Path | None = None
    secure: bool = True
    bad_sectors: list[int] = field(default_factory=list)
    rereads: int = 0
    crc_v1: int = 0
    crc_v2: int = 0
    accurate: str = ""                # "Accurate (12)" | "Inaccurate" | "Not in database"
    cancelled: bool = False


OVERREAD = {"on": False}
SECURE_BLOCK = 20000                  # Sektoren je Lese-Block (~47 MB, ~4,4 min Audio)


def _safe_read(drive: CDDrive, lba: int, count: int, disc: Disc, failed: set[int] | None = None) -> bytes:
    """Wie _read_area, aber ein Lesefehler (OSError) bricht den Rip nicht ab: Block wird
    sektorweise wiederholt, nicht lesbare Sektoren werden als Stille geliefert und in `failed` gemerkt."""
    try:
        return _read_area(drive, lba, count, disc)
    except OSError:
        if failed is None:
            raise
    parts = []
    for s in range(lba, lba + count):
        try:
            parts.append(_read_area(drive, s, 1, disc))
        except OSError:
            failed.add(s)
            parts.append(b"\0" * SECTOR)
    return b"".join(parts)


def _read_area(drive: CDDrive, lba: int, count: int, disc: Disc) -> bytes:
    """Liest auch Bereiche außerhalb der Disc (Offset-Korrektur): dort Stille.
    Mit Overread wird versucht, ins Lead-in/-out zu lesen (nur wenige Laufwerke können das)."""
    out = b""
    if OVERREAD["on"] and (lba < 0 or lba + count > disc.leadout):
        parts = []
        for s in range(lba, lba + count):
            try:
                parts.append(drive.read_sectors(s, 1) if s >= -450 else b"\0" * SECTOR)
            except OSError:
                parts.append(b"\0" * SECTOR)
        return b"".join(parts)
    lo, hi = max(lba, 0), min(lba + count, disc.leadout)
    out += b"\0" * (SECTOR * max(0, lo - lba))
    if hi > lo:
        out += drive.read_sectors(lo, hi - lo)
    out += b"\0" * (SECTOR * max(0, (lba + count) - max(hi, lo)))
    return out


def _flush_cache(drive: CDDrive, lba: int, disc: Disc, sectors: int):
    far = lba + sectors + 100
    if far >= disc.leadout - 1:
        far = max(lba - sectors - 100, 0)
    try:
        drive.read_sectors(far, 1)
    except OSError:
        pass


def rip_range(drive: CDDrive, disc: Disc, start: int, count: int, opt: RipOptions,
              progress: Callable[[float], None] | None = None, cancel: threading.Event | None = None) -> tuple[bytes, list[int], int]:
    """Gibt (PCM, defekte Sektoren, Anzahl Re-Reads) zurück. Offset wird in Samples angewendet."""
    OVERREAD["on"] = opt.overread
    shift_sectors, shift_samples = divmod(opt.sample_offset, FRAMES_PER_SECTOR)
    first = start + shift_sectors
    extra = 1 if shift_samples else 0
    chunks, bad, rereads, done = [], [], 0, 0
    total = count + extra
    # Jeder Durchlauf liest einen großen Block am Stück (bis ~4 min Audio). Laufwerke drehen nur bei
    # durchgehendem Lesen hoch; kurze Blöcke mit Sprüngen dazwischen halten sie im leisen 4–6×-Modus.
    # Der Block ist viel größer als der Laufwerks-Cache, der zweite Durchlauf liest also nicht aus dem Cache.
    block = SECURE_BLOCK
    npass = 1 + max(opt.passes - 1, 1) if opt.secure else 1

    failed: set[int] = set()
    # Re-Read-Budget pro Track: sonst kostet ein zerkratzter Bereich (jeder Sektor bis zu max_rereads
    # Versuche mit Cache-Flush) Minuten bis Stunden. Ist es aufgebraucht, gibt es nur noch 2 Versuche je Sektor.
    budget = opt.max_rereads * 10

    def read_block(lba: int, n: int, pass_no: int) -> bytes:
        parts = []
        for o in range(0, n, opt.chunk):
            if cancel and cancel.is_set():
                break
            parts.append(_safe_read(drive, lba + o, min(opt.chunk, n - o), disc, failed))
            if progress:
                progress(min((done * npass + pass_no * n + o + opt.chunk) / (total * npass), 1.0))
        return b"".join(parts)

    while done < total:
        if cancel and cancel.is_set():
            break
        n = min(block, total - done)
        lba = first + done
        data = read_block(lba, n, 0)
        if opt.secure:
            reads = [data]
            for p in range(1, npass):
                if n < 4 * opt.cache_sectors:                # kurzer Block könnte noch im Cache liegen
                    _flush_cache(drive, lba, disc, opt.cache_sectors)
                reads.append(read_block(lba, n, p))
            if cancel and cancel.is_set():
                break
            if all(r == data for r in reads) and not any(lba <= f < lba + n for f in failed):
                chunks.append(data)                          # Normalfall: alle Durchläufe identisch
                done += n
                continue
            final = bytearray()
            for s in range(n):
                cand = [r[s * SECTOR:(s + 1) * SECTOR] for r in reads]
                cnt = Counter(cand)
                best, votes = cnt.most_common(1)[0]
                tries = 0
                while votes < 2 and tries < (opt.max_rereads if rereads < budget else 2):
                    if cancel and cancel.is_set():
                        break
                    _flush_cache(drive, lba, disc, opt.cache_sectors)
                    cand.append(_safe_read(drive, lba + s, 1, disc, failed))
                    cnt = Counter(cand)
                    best, votes = cnt.most_common(1)[0]
                    tries += 1
                    rereads += 1
                if (votes < 2 and len(set(cand)) > 1) or ((lba + s) in failed and best == b"\0" * SECTOR):
                    bad.append(lba + s)
                final += best
            if opt.abort_after_unrecoverable and len(bad) >= opt.abort_after_unrecoverable:
                chunks.append(bytes(final))
                break
            data = bytes(final)
        chunks.append(data)
        done += n
    if not opt.secure:
        bad = sorted(failed)
    pcm = b"".join(chunks)
    start_b = shift_samples * 4
    return pcm[start_b:start_b + count * SECTOR], bad, rereads


def save_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(pcm)


# ----------------------------------------------------------- AccurateRip
def accuraterip_crc(pcm: bytes, first_track: bool, last_track: bool) -> tuple[int, int]:
    """CRC v1 und v2 der Samples eines Tracks (32-Bit-Stereo-Frames)."""
    n = len(pcm) // 4
    skip_start = FRAMES_PER_SECTOR * 5 - 1 if first_track else 0
    skip_end = FRAMES_PER_SECTOR * 5 if last_track else 0
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        a = np.frombuffer(pcm[: n * 4], dtype="<u4").astype(np.uint64)[skip_start:n - skip_end]
        mult = np.arange(skip_start + 1, skip_start + 1 + len(a), dtype=np.uint64)
        p = a * mult
        crc1 = int(p.sum(dtype=np.uint64)) & 0xFFFFFFFF
        crc2 = int(((p & np.uint64(0xFFFFFFFF)) + (p >> np.uint64(32))).sum(dtype=np.uint64)) & 0xFFFFFFFF
        return crc1, crc2
    import array
    a = array.array("I")
    a.frombytes(pcm[: n * 4])
    crc1 = crc2 = 0
    for i in range(skip_start, n - skip_end):
        v = a[i]
        mult = i + 1
        crc1 = (crc1 + v * mult) & 0xFFFFFFFF
        p = v * mult
        crc2 = (crc2 + (p & 0xFFFFFFFF) + (p >> 32)) & 0xFFFFFFFF
    return crc1, crc2


def detect_offset(drive: "CDDrive", disc: Disc, entries, margin_sectors: int = 4,
                  progress: Callable[[float], None] | None = None, cancel: threading.Event | None = None) -> int | None:
    """Bestimmt den Laufwerks-Offset (Samples) per AccurateRip-Abgleich an einem mittleren Track."""
    audio = disc.audio_tracks
    if not entries or len(audio) < 3:
        return None
    mid = sorted(range(1, len(audio) - 1), key=lambda i: audio[i].sectors)[:3]
    opt = RipOptions(secure=False, chunk=26)
    for idx in mid:
        t, m = audio[idx], margin_sectors
        big, _, _ = rip_range(drive, disc, t.start - m, t.sectors + 2 * m, opt, progress, cancel)
        if cancel and cancel.is_set():
            return None
        want = {e[idx][1] for e in entries if idx < len(e)}
        n = t.sectors * FRAMES_PER_SECTOR
        for off in sorted(range(-m * FRAMES_PER_SECTOR, m * FRAMES_PER_SECTOR + 1), key=abs):
            s0 = (m * FRAMES_PER_SECTOR + off) * 4
            v1, v2 = accuraterip_crc(big[s0:s0 + n * 4], False, False)
            if v1 in want or v2 in want:
                return off
    return None


class AccurateRipUnavailable(OSError):
    """Server nicht erreichbar oder Fehler – nicht dasselbe wie „Disc nicht in der Datenbank“ (HTTP 404)."""


def fetch_accuraterip(d: Disc, timeout: float = 10.0) -> list[list[tuple[int, int, int]]] | None:
    """Liste von Einträgen, je Eintrag Liste (Confidence, CRC, CRC450) pro Track; None = nicht in DB (404).
    Netz-/Serverfehler lösen AccurateRipUnavailable aus."""
    try:
        req = urllib.request.Request(accuraterip_url(d), headers={"User-Agent": UA})
        data = urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise AccurateRipUnavailable(tr("AccurateRip-Server meldet HTTP {0}").format(e.code)) from e
    except (OSError, ValueError) as e:
        raise AccurateRipUnavailable(tr("AccurateRip nicht erreichbar: {0}").format(e)) from e
    entries, pos, n = [], 0, len(d.tracks)
    while pos + 13 <= len(data):
        cnt = data[pos]
        pos += 13
        entry = []
        for _ in range(cnt):
            conf, crc, crc450 = struct.unpack_from("<BII", data, pos)
            entry.append((conf, crc, crc450))
            pos += 9
        entries.append(entry)
    return entries


def verify_track(entries, index: int, crc1: int, crc2: int) -> str:
    if not entries:
        return "Not in database"
    best = [e[index][0] for e in entries if index < len(e) and e[index][1] in (crc1, crc2)]
    if best:
        return f"Accurate ({max(best)})"
    return "Inaccurate"


# -------------------------------------------------------------- Metadaten
@dataclass
class DiscMeta:
    album: str = ""
    artist: str = ""
    year: str = ""
    genre: str = ""
    tracks: list[tuple[str, str]] = field(default_factory=list)   # (Titel, Künstler)
    mbid: str = ""
    cover: bytes | None = None
    source: str = "MusicBrainz"
    cover_source: str = ""
    # --- MusicBrainz-Zusatzdaten (für die Tags im Picard-Stil) ---
    release_group_id: str = ""
    release_type: str = ""                 # z. B. "album" oder "album; compilation" (Primär- und Sekundärtypen)
    status: str = ""                       # official / promotion / bootleg …
    country: str = ""
    original_date: str = ""                # Erstveröffentlichung der Release Group
    label: str = ""
    catalog: str = ""
    barcode: str = ""
    asin: str = ""
    media_format: str = ""                 # CD, Vinyl …
    artist_ids: list[str] = field(default_factory=list)                  # Album-Artist-MBIDs
    track_info: list[dict] = field(default_factory=list)                 # je Track: track_id, recording_id, artist_ids, isrc, tags{…}
    album_tags: dict[str, str] = field(default_factory=dict)             # weitere Release-Felder (Sortierung, Sprache, Genres, Totals …)
    disc_position: int = 1                 # Nummer dieser CD innerhalb des Releases
    disc_total: int = 1
    genres: list[str] = field(default_factory=list)


MB_INC_BASIC = "artist-credits+recordings+release-groups+labels+isrcs"
MB_INC_FULL = ("artist-credits+recordings+release-groups+labels+isrcs+genres+tags+artist-rels+recording-rels+work-rels"
               "+recording-level-rels+work-level-rels")


def musicbrainz_lookup(d: Disc, timeout: float = 10.0, full: bool = True, max_full: int = 3) -> list[DiscMeta]:
    """Releases zur Disc. Mit full=True werden die ersten Treffer zusätzlich vollständig geladen (Credits, Werke, Genres …)."""
    import time
    url = f"https://musicbrainz.org/ws/2/discid/{musicbrainz_disc_id(d)}?inc={MB_INC_BASIC}&fmt=json"
    try:
        data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout).read())
    except Exception:
        return []
    out = []
    for i, rel in enumerate(data.get("releases", [])):
        meta = _mb_meta(rel, disc_id=data.get("id"))
        if full and i < max_full:
            time.sleep(1.0)                                  # MusicBrainz: max. 1 Anfrage/s
            fm = musicbrainz_release(rel["id"], len(meta.tracks) or None, timeout=30.0, disc_id=data.get("id"))
            meta = fm or meta
        out.append(meta)
    return out


def _get(url: str, timeout: float = 10.0, headers: dict | None = None) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})}), timeout=timeout).read()


def fetch_cover(mbid: str, timeout: float = 15.0, size: int = 500) -> bytes | None:
    """Cover Art Archive. Verfügbare Stufen: 250, 500, 1200 und das Original ("front"); größere liefert es nur, wenn hochgeladen."""
    steps = ["front-250"] if size <= 250 else ["front-500"] if size <= 500 else ["front-1200"] if size <= 1200 else ["front"]
    for step in steps + ["front-500"]:
        try:
            return _get(f"https://coverartarchive.org/release/{mbid}/{step}", timeout)
        except Exception:
            continue
    return None


# --- Apple Music / iTunes Search API (öffentlich, ohne Schlüssel) --------------------------
def _norm(s: str) -> str:
    import re
    s = re.sub(r"[\(\[].*?[\)\]]", " ", s.lower())               # "(Deluxe Edition)", "[Remastered]" ignorieren
    return re.sub(r"[^a-z0-9äöüß]+", " ", s).strip()


def _sim(a: str, b: str) -> float:
    import difflib
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def itunes_search(artist: str, album: str, country: str = "us", limit: int = 8, timeout: float = 15.0) -> list[dict]:
    """Treffer der iTunes-Suche: artist, album, year, art (URL der 100-px-Vorschau), score (Ähnlichkeit 0..1)."""
    term = urllib.request.quote(f"{artist} {album}".strip())
    try:
        data = json.loads(_get(f"https://itunes.apple.com/search?term={term}&entity=album&limit={limit}&country={country}", timeout))
    except Exception:
        return []
    out = []
    for r in data.get("results", []):
        if "artworkUrl100" not in r:
            continue
        score = 0.7 * _sim(album, r.get("collectionName", "")) + 0.3 * _sim(artist, r.get("artistName", "")) if (artist or album) else 0.0
        out.append({"artist": r.get("artistName", ""), "album": r.get("collectionName", ""), "year": (r.get("releaseDate") or "")[:4],
                    "art": r["artworkUrl100"], "score": score})
    return sorted(out, key=lambda x: -x["score"])


def itunes_art_url(url100: str, size: int) -> str:
    import re
    return re.sub(r"/\d+x\d+bb", f"/{int(size)}x{int(size)}bb", url100)


def fetch_itunes_cover(art_url100: str, size: int = 1500, timeout: float = 20.0) -> bytes | None:
    """Apple liefert höchstens die Originalauflösung (nie hochgerechnet); größere Wünsche ergeben das Original."""
    for s in dict.fromkeys([size, 1500, 1000, 600]):
        try:
            return _get(itunes_art_url(art_url100, s), timeout)
        except Exception:
            continue
    return None


def _pixels(data: bytes | None) -> int:
    if not data:
        return 0
    try:
        import io
        from PIL import Image
        w, h = Image.open(io.BytesIO(data)).size
        return w * h
    except Exception:
        return 0


def best_cover(artist: str, album: str, mbid: str = "", source: str = "auto", size: int = 1500, country: str = "us",
               min_match: float = 0.75) -> tuple[bytes | None, str]:
    """Holt das Cover aus der gewählten Quelle. source: "caa", "apple" oder "auto" (größtes von beiden).
    Das Ergebnis wird auf `size` Pixel (längste Kante) begrenzt, aber nie hochskaliert. Rückgabe: (Bild, Quelle)."""
    from .tags import resize_art
    cands: list[tuple[bytes, str]] = []
    if source in ("apple", "auto") and (artist or album):
        hits = itunes_search(artist, album, country, limit=5)
        if hits and hits[0]["score"] >= min_match:
            d = fetch_itunes_cover(hits[0]["art"], size)
            if d:
                cands.append((d, "Apple Music"))
    if source in ("caa", "auto") or (source == "apple" and not cands):
        d = fetch_cover(mbid, size=size) if mbid else None
        if d:
            cands.append((d, "Cover Art Archive"))
    if not cands:
        return None, ""
    data, name = max(cands, key=lambda c: _pixels(c[0]))
    try:
        data = resize_art(data, size)
    except Exception:
        pass
    return data, name


def _credit(parts) -> str:
    return "".join(c.get("name", "") + c.get("joinphrase", "") for c in parts or [])


def _artist_ids(credit) -> list[str]:
    return [c["artist"]["id"] for c in credit or [] if c.get("artist", {}).get("id")]


def _sort_names(credit) -> list[str]:
    return [c["artist"]["sort-name"] for c in credit or [] if c.get("artist", {}).get("sort-name")]


def _uniq(items) -> list[str]:
    return list(dict.fromkeys(x for x in items if x))


# Beziehungstypen (MusicBrainz) -> Tag-Name
_ROLE_TAGS = {"producer": "producer", "engineer": "engineer", "mix": "mixer", "remixer": "remixer", "mix-DJ": "djmixer",
              "conductor": "conductor", "composer": "composer", "lyricist": "lyricist", "writer": "writer", "orchestrator": "arranger"}
_PERFORMER_TYPES = ("vocal", "instrument", "performer", "performing orchestra")


def _credits_from_relations(recording: dict) -> dict[str, list[str]]:
    """Mitwirkende eines Recordings (inkl. Komponist/Texter des Werks) als {Tag: [Namen]}; *sort-Listen parallel."""
    out: dict[str, list[str]] = {}

    def add(tag: str, artist: dict):
        name = artist.get("name") or ""
        if not name:
            return
        out.setdefault(tag, []).append(name)
        out.setdefault(tag + "sort", []).append(artist.get("sort-name") or name)

    for r in recording.get("relations", []):
        t = r.get("type", "")
        artist = r.get("artist")
        if artist:
            if "arranger" in t:
                add("arranger", artist)
            elif t in _ROLE_TAGS:
                add(_ROLE_TAGS[t], artist)
            elif t in _PERFORMER_TYPES:
                attrs = [a for a in r.get("attributes", []) if a not in ("additional", "guest", "solo")]
                role = ", ".join(attrs) if attrs else ("vocals" if t == "vocal" else "")
                out.setdefault("performer", []).append(f"{artist['name']} ({role})" if role else artist["name"])
        work = r.get("work")
        if work:
            out.setdefault("work", []).append(work.get("title", ""))
            out.setdefault("musicbrainz_workid", []).append(work.get("id", ""))
            langs = work.get("languages") or ([work["language"]] if work.get("language") else [])
            if langs:
                out.setdefault("language", []).extend(langs)
            for wr in work.get("relations", []):
                wt, wa = wr.get("type", ""), wr.get("artist")
                if wa and "arranger" in wt:
                    add("arranger", wa)
                elif wa and wt in _ROLE_TAGS:
                    add(_ROLE_TAGS[wt], wa)
    return {k: _uniq(v) for k, v in out.items()}


def _genres_of(*sources) -> list[str]:
    best: dict[str, int] = {}
    for src in sources:
        for g in (src or {}).get("genres", []) or []:
            best[g["name"]] = max(best.get(g["name"], 0), g.get("count", 0))
    return [n.title() for n, _ in sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))]


def _mb_meta(rel: dict, ntracks: int | None = None, disc_id: str | None = None, medium_pos: int | None = None) -> DiscMeta:
    """Wandelt ein MusicBrainz-Release (JSON) in DiscMeta um – inkl. IDs, Release-Typ, Label, Land, Barcode, Credits, Genres …
    Die CD des Releases wird gewählt über: Disc-ID, sonst Position (medium_pos), sonst passende Track-Anzahl."""
    artist = _credit(rel.get("artist-credit"))
    media = rel.get("media") or [{}]
    medium = next((m for m in media if disc_id and any(dd.get("id") == disc_id for dd in m.get("discs", []))), None) \
        or next((m for m in media if medium_pos and m.get("position") == medium_pos), None) \
        or next((m for m in media if ntracks and len(m.get("tracks", [])) == ntracks), media[0])
    tracks, info = [], []
    for t in medium.get("tracks", []):
        rec = t.get("recording") or {}
        credit = t.get("artist-credit") or rec.get("artist-credit") or rel.get("artist-credit")
        tracks.append((t.get("title", ""), _credit(credit) or artist))
        tt: dict[str, str] = {}
        if _sort_names(credit):
            tt["artistsort"] = "; ".join(_uniq(_sort_names(credit)))
        names = _uniq(c.get("name") or c.get("artist", {}).get("name", "") for c in credit or [])
        if names:
            tt["artists"] = "; ".join(names)
        for k, v in _credits_from_relations(rec).items():
            if v and (not k.endswith("sort") or k == "composersort"):     # nur Standard-Sortierfelder (Composer Sort)
                tt[k] = "; ".join(v)
        if "language" not in tt and (rel.get("text-representation") or {}).get("language"):
            tt["language"] = rel["text-representation"]["language"]
        if rec.get("disambiguation"):
            tt["comment"] = rec["disambiguation"]
        info.append({"track_id": t.get("id", ""), "recording_id": rec.get("id", ""),
                     "artist_ids": _artist_ids(credit), "isrc": (rec.get("isrcs") or [""])[0], "tags": tt})
    rg = rel.get("release-group") or {}
    genres = _genres_of(rel, rg)
    kinds = [x for x in [rg.get("primary-type")] + list(rg.get("secondary-types") or []) if x]
    label_info = (rel.get("label-info") or [{}])[0]
    tr_ = rel.get("text-representation") or {}
    orig = rg.get("first-release-date") or ""
    album_tags = {
        "albumsort": rel.get("title", ""), "albumartistsort": "; ".join(_uniq(_sort_names(rel.get("artist-credit")))),
        "musicbrainz_albumcomment": rel.get("disambiguation") or "", "script": tr_.get("script") or "", "language": tr_.get("language") or "",
        "originalyear": orig[:4], "totaltracks": str(len(tracks)) if tracks else "", "totaldiscs": str(len(media)) if media else "",
        "discsubtitle": medium.get("title") or "", "genre": "; ".join(genres[:3]),
    }
    return DiscMeta(rel.get("title", ""), artist, (rel.get("date") or "")[:4], genres[0] if genres else "", tracks, rel.get("id", ""),
                    source="MusicBrainz", release_group_id=rg.get("id", ""), release_type="; ".join(k.lower() for k in kinds),
                    status=(rel.get("status") or "").lower(), country=rel.get("country") or "",
                    original_date=orig, label=(label_info.get("label") or {}).get("name", ""),
                    catalog=label_info.get("catalog-number") or "", barcode=rel.get("barcode") or "", asin=rel.get("asin") or "",
                    media_format=medium.get("format") or "", artist_ids=_artist_ids(rel.get("artist-credit")), track_info=info,
                    album_tags={k: v for k, v in album_tags.items() if v}, disc_position=int(medium.get("position") or 1),
                    disc_total=max(len(media), 1), genres=genres)


def musicbrainz_release(mbid: str, ntracks: int | None = None, timeout: float = 30.0, disc_id: str | None = None,
                        medium_pos: int | None = None) -> DiscMeta | None:
    try:
        rel = json.loads(_get(f"https://musicbrainz.org/ws/2/release/{mbid}?inc={MB_INC_FULL}&fmt=json", timeout))
    except Exception:
        return None
    return _mb_meta(rel, ntracks, disc_id, medium_pos)


def match_tracks(files: list[dict], titles: list[str]) -> list[int | None]:
    """Ordnet Dateien den MusicBrainz-Tracks zu. files: [{"track": int|None, "title": str}] (Reihenfolge = Dateireihenfolge).
    Reihenfolge der Strategien: Tracknummer (bei passendem/fehlendem Titel), Titelähnlichkeit, zuletzt die Reihenfolge."""
    taken: set[int] = set()
    result: list[int | None] = [None] * len(files)
    for i, f in enumerate(files):                                   # 1. Tracknummer
        n = f.get("track")
        if n and 1 <= n <= len(titles) and (n - 1) not in taken and (not f.get("title") or _sim(f["title"], titles[n - 1]) >= 0.5):
            result[i] = n - 1
            taken.add(n - 1)
    for i, f in enumerate(files):                                   # 2. Titel
        if result[i] is None and f.get("title"):
            best = max((j for j in range(len(titles)) if j not in taken), key=lambda j: _sim(f["title"], titles[j]), default=None)
            if best is not None and _sim(f["title"], titles[best]) >= 0.6:
                result[i] = best
                taken.add(best)
    rest_files = [i for i, r in enumerate(result) if r is None]
    rest_tracks = [j for j in range(len(titles)) if j not in taken]
    if len(rest_files) == len(rest_tracks):                         # 3. gleiche Anzahl übrig: in Reihenfolge zuordnen
        for i, j in zip(rest_files, rest_tracks, strict=True):
            result[i] = j
    return result


def musicbrainz_search(artist: str = "", album: str = "", barcode: str = "", ntracks: int | None = None, limit: int = 5) -> list[DiscMeta]:
    import time
    q = " AND ".join(p for p in (f'artist:"{artist}"' if artist else "", f'release:"{album}"' if album else "",
                                  f"barcode:{barcode}" if barcode else "", f"tracks:{ntracks}" if ntracks and not barcode else "") if p)
    if not q:
        return []
    try:
        data = json.loads(_get("https://musicbrainz.org/ws/2/release/?query=" + urllib.request.quote(q) + f"&limit={limit}&fmt=json"))
    except Exception:
        return []
    out = []
    for r in data.get("releases", [])[:limit]:
        time.sleep(1.0)                       # MusicBrainz: max. 1 Anfrage/s
        m = musicbrainz_release(r["id"], ntracks)
        if m:
            out.append(m)
    return out


# --- GnuDB (CDDB-Protokoll über HTTP; Nachfolger von freedb) ----------------------------
def cddb_query_string(d: Disc) -> str:
    offs = " ".join(str(t.start + 150) for t in d.tracks)
    total = (d.leadout + 150) // 75
    return f"cddb query {freedb_id(d):08x} {len(d.tracks)} {offs} {total}"


def parse_cddb_read(text: str, ntracks: int) -> DiscMeta:
    kv: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            kv[k] = kv.get(k, "") + v
    dtitle = kv.get("DTITLE", "")
    artist, _, album = dtitle.partition(" / ")
    if not album:
        artist, album = "", dtitle
    tracks = []
    for i in range(ntracks):
        t = kv.get(f"TTITLE{i}", "")
        ta, sep, tt = t.partition(" / ")
        tracks.append((tt, ta) if sep else (t, artist))
    return DiscMeta(album.strip(), artist.strip(), kv.get("DYEAR", ""), kv.get("DGENRE", ""), tracks, source="GnuDB")


def gnudb_lookup(d: Disc, timeout: float = 10.0) -> list[DiscMeta]:
    base = "http://gnudb.gnudb.org/~cddb/cddb.cgi"
    import getpass
    import socket
    hello = f"&hello={urllib.request.quote(getpass.getuser())}+{urllib.request.quote(socket.gethostname())}+psyrip+0.1&proto=6"
    try:
        r = _get(f"{base}?cmd={urllib.request.quote(cddb_query_string(d)).replace('%20', '+')}{hello}", timeout).decode("utf-8", "replace").splitlines()
        if not r:
            return []
        code = r[0][:3]
        if code == "200":
            matches = [r[0][4:]]
        elif code in ("210", "211"):
            matches = [l for l in r[1:] if l.strip() and l.strip() != "."]
        else:
            return []
        out = []
        for m in matches[:3]:
            genre, discid = m.split()[:2]
            txt = _get(f"{base}?cmd=cddb+read+{genre}+{discid}{hello}", timeout).decode("utf-8", "replace")
            meta = parse_cddb_read(txt, len(d.tracks))
            meta.genre = meta.genre or genre.title()
            out.append(meta)
        return out
    except Exception:
        return []


# --- Discogs (Token nötig: https://www.discogs.com/settings/developers) ----------------
def _discogs(path: str, token: str, timeout: float = 10.0) -> dict:
    sep = "&" if "?" in path else "?"
    return json.loads(_get(f"https://api.discogs.com/{path}{sep}token={token}", timeout))


def discogs_release(release_id: int | str, token: str, ntracks: int | None = None) -> DiscMeta | None:
    import re
    try:
        r = _discogs(f"releases/{release_id}", token)
    except Exception:
        return None
    clean = lambda n: re.sub(r"\s*\(\d+\)$", "", n)
    artist = ", ".join(clean(a["name"]) for a in r.get("artists", []))
    tracks = [(t.get("title", ""), ", ".join(clean(a["name"]) for a in t.get("artists", [])) or artist)
              for t in r.get("tracklist", []) if t.get("type_", "track") == "track"]
    cover = None
    imgs = r.get("images") or []
    if imgs:
        try:
            cover = _get(imgs[0]["uri"], headers={"Authorization": f"Discogs token={token}"})
        except Exception:
            cover = None
    return DiscMeta(r.get("title", ""), artist, str(r.get("year", "")), (r.get("genres") or [""])[0], tracks, cover=cover, source="Discogs")


def discogs_search(token: str, artist: str = "", album: str = "", barcode: str = "", ntracks: int | None = None, limit: int = 3) -> list[DiscMeta]:
    if not token:
        return []
    q = f"barcode={urllib.request.quote(barcode)}" if barcode else f"artist={urllib.request.quote(artist)}&release_title={urllib.request.quote(album)}"
    try:
        res = _discogs(f"database/search?type=release&{q}&per_page={limit}", token).get("results", [])
    except Exception:
        return []
    out = [discogs_release(r["id"], token, ntracks) for r in res[:limit]]
    return [m for m in out if m and (not ntracks or len(m.tracks) == ntracks)]


def meta_from_url(url: str, discogs_token: str = "", ntracks: int | None = None) -> DiscMeta | None:
    import re
    m = re.search(r"musicbrainz\.org/release/([0-9a-f-]{36})", url)
    if m:
        return musicbrainz_release(m.group(1), ntracks)
    m = re.search(r"discogs\.com/.*release/(\d+)", url)
    if m and discogs_token:
        return discogs_release(m.group(1), discogs_token, ntracks)
    return None


def all_providers(d: Disc, discogs_token: str = "", barcode: str = "", timeout: float = 12.0) -> dict[str, list[DiscMeta]]:
    """Fragt alle Anbieter parallel ab (analog zu PerfectMeta)."""
    from concurrent.futures import ThreadPoolExecutor
    n = len(d.audio_tracks)
    jobs = {"MusicBrainz": lambda: musicbrainz_lookup(d) or (musicbrainz_search(barcode=barcode, ntracks=n) if barcode else []),
            "GnuDB": lambda: gnudb_lookup(d)}
    if discogs_token and barcode:
        jobs["Discogs"] = lambda: discogs_search(discogs_token, barcode=barcode, ntracks=n)
    from concurrent.futures import wait
    pool = ThreadPoolExecutor(max_workers=len(jobs))
    futs = {k: pool.submit(v) for k, v in jobs.items()}
    wait(futs.values(), timeout=timeout)                 # langsame Anbieter blockieren die anderen nicht
    out = {k: (f.result() if f.done() and not f.exception() else []) for k, f in futs.items()}
    pool.shutdown(wait=False, cancel_futures=True)
    for m in out.get("MusicBrainz", []):
        m.source = "MusicBrainz"
    return {k: dedupe(v) for k, v in out.items() if v}


def dedupe(metas: list[DiscMeta]) -> list[DiscMeta]:
    """Entfernt Treffer mit identischem Inhalt (z. B. mehrere MusicBrainz-Releases derselben Disc)."""
    seen, out = set(), []
    for m in metas:
        key = (m.album.strip().lower(), m.artist.strip().lower(), m.year, tuple((t.strip().lower(), a.strip().lower()) for t, a in m.tracks))
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def htoa_track(d: Disc, min_sectors: int = 75) -> Track | None:
    """Verstecktes Audio vor Track 1 (HTOA), falls Track 1 nicht am Anfang der Disc beginnt."""
    first = d.tracks[0]
    return Track(0, 0, first.start) if first.start >= min_sectors else None
