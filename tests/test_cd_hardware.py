"""Tests mit echtem Laufwerk und eingelegter Audio-CD. Laufen nur auf Wunsch:

    PSYRIP_HW_TEST=1 python -m pytest tests/test_cd_hardware.py      # Lesen, Secure, AccurateRip
    PSYRIP_HW_EJECT=1 …                                             # zusätzlich Lade öffnen (und wieder schließen)
PSYRIP_HW_DRIVE wählt das Laufwerk (Standard: das erste gefundene)."""
import os
import shutil
import subprocess
import time

import pytest

from psyrip import cdrip

pytestmark = pytest.mark.skipif(not os.environ.get("PSYRIP_HW_TEST"), reason="Hardware-Test: PSYRIP_HW_TEST=1 setzen")


@pytest.fixture(scope="module")
def dev():
    drives = cdrip.list_cd_drives()
    d = os.environ.get("PSYRIP_HW_DRIVE") or (drives[0] if drives else None)
    if not d:
        pytest.skip("kein CD-Laufwerk")
    return d


@pytest.fixture(scope="module")
def disc(dev):
    try:
        with cdrip.CDDrive(dev) as d:
            disc = d.read_toc()
    except OSError as e:
        pytest.skip(f"keine lesbare Disc: {e}")
    if len(disc.audio_tracks) < 1:
        pytest.skip("keine Audio-Tracks")
    return disc


def test_toc_plausible(disc):
    assert disc.tracks[0].start >= 0
    assert all(a.end == b.start for a, b in zip(disc.tracks, disc.tracks[1:]))
    assert disc.tracks[-1].end == disc.leadout and disc.leadout < 100 * 60 * 75
    assert len(cdrip.musicbrainz_disc_id(disc)) == 28


def test_reads_are_repeatable(dev, disc):
    t = disc.audio_tracks[0]
    lba = t.start + min(500, t.sectors // 2)
    with cdrip.CDDrive(dev) as d:
        d.set_max_speed()
        a = d.read_sectors(lba, 100)
        cdrip._flush_cache(d, lba, disc, 2048)
        b = d.read_sectors(lba, 100)
    assert len(a) == 100 * cdrip.SECTOR and a == b and any(a)


@pytest.mark.skipif(not shutil.which("cd-paranoia"), reason="cd-paranoia nicht installiert")
def test_matches_cd_paranoia(dev, disc, tmp_path):
    t = disc.audio_tracks[0]
    rel = min(1000, t.sectors - 300)
    span = f"{t.number}[00:{rel // 75:02d}.{rel % 75:02d}]-{t.number}[00:{(rel + 259) // 75:02d}.{(rel + 259) % 75:02d}]"
    ref = tmp_path / "ref.raw"
    subprocess.run(["cd-paranoia", "-q", "-Z", "-r", "-d", dev, span, str(ref)], check=True, timeout=120)
    with cdrip.CDDrive(dev) as d:
        ours = d.read_sectors(t.start + rel, 260)
    assert ref.read_bytes() == ours


def test_secure_rip_accuraterip(dev, disc):
    try:
        entries = cdrip.fetch_accuraterip(disc)
    except cdrip.AccurateRipUnavailable as e:
        pytest.skip(f"AccurateRip nicht erreichbar: {e}")
    if not entries:
        pytest.skip("Disc nicht in der AccurateRip-Datenbank")
    audio = disc.audio_tracks
    with cdrip.CDDrive(dev) as d:
        d.set_max_speed()
        off = cdrip.detect_offset(d, disc, entries)
        assert off is not None, "Offset nicht erkannt"
        idx = min(range(1, max(len(audio) - 1, 2)), key=lambda i: audio[i].sectors)   # kürzester mittlerer Track
        t = audio[idx]
        pcm, bad, _ = cdrip.rip_range(d, disc, t.start, t.sectors, cdrip.RipOptions(secure=True, sample_offset=off))
    assert bad == []
    v1, v2 = cdrip.accuraterip_crc(pcm, idx == 0, idx == len(audio) - 1)
    assert cdrip.verify_track(entries, idx, v1, v2).startswith("Accurate")


def _status(dev):
    import fcntl
    fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    try:
        return fcntl.ioctl(fd, 0x5326, 0)                # CDROM_DRIVE_STATUS
    finally:
        os.close(fd)


@pytest.mark.skipif(os.name == "nt" or not os.environ.get("PSYRIP_HW_EJECT"), reason="PSYRIP_HW_EJECT=1 setzen (öffnet die Lade)")
def test_eject_opens_tray_and_closes_again(dev, disc):
    import fcntl
    with cdrip.CDDrive(dev) as d:
        d.read_toc()
        d.eject()
    assert _status(dev) == 2                             # CDS_TRAY_OPEN
    fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, 0x5319)                          # CDROMCLOSETRAY
    finally:
        os.close(fd)
    t = time.monotonic()
    while _status(dev) != 4 and time.monotonic() - t < 30:   # CDS_DISC_OK
        time.sleep(0.5)
    assert _status(dev) == 4
