"""Rip-Ablauf: Tracks lesen (Burst/Secure) → AccurateRip prüfen → Encoder/DSP/Naming über den Converter."""
from __future__ import annotations

from .i18n import tr
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import cdrip
from .converter import ConvertSettings, Converter


@dataclass
class TrackMeta:
    title: str = ""
    artist: str = ""


@dataclass
class RipJob:
    drive: str
    disc: cdrip.Disc
    tracks: list[int]                        # Tracknummern
    meta: cdrip.DiscMeta
    track_meta: dict[int, TrackMeta]
    settings: ConvertSettings                # Encoder, DSP, Output (dynamic)
    options: cdrip.RipOptions
    compilation: bool = False
    disc_number: int = 1
    disc_total: int = 1
    genre: str = ""
    year: str = ""
    album_artist: str = ""
    use_accuraterip: bool = True
    as_one: bool = False                     # gewählte Tracks als eine Datei rippen (Titel = Album)
    track_offset: int = 0                    # wird auf alle Track-Nummern addiert (Boxsets als ein Album)
    error_if_insecure: bool = False          # unsichere Tracks als Fehler markieren (→ "Delete/Move Destination on Error")
    error_if_inaccurate: bool = False        # Tracks ohne AccurateRip-Bestätigung als Fehler markieren
    cancel_on_insecure: bool = False         # gesamte Disc abbrechen, sobald ein Track unsicher ist
    write_mb_tags: bool = True               # MusicBrainz-IDs, Release-Typ, Label, Land, Barcode, ISRC … schreiben
    mb_detail: str = "full"                  # "basic" oder "full" (zusätzlich Credits, Werk, Genres, Sortierfelder …)


TAG_GROUPS = ("core", "ids", "details", "credits", "extras")


def mb_tag_groups(meta: cdrip.DiscMeta, n: int = 0) -> dict[str, dict[str, str]]:
    """Alle MusicBrainz-Felder, nach Gruppen sortiert: core (Titel, Artist, Album, Jahr, Nummern), ids, details (Typ, Label, Land,
    Barcode, ISRC …), credits (Komponist, Produzent, Mitwirkende, Werk …) und extras (Genres, Sprache, Sortierfelder, Totals)."""
    ids = {"musicbrainz_albumid": meta.mbid, "musicbrainz_releasegroupid": meta.release_group_id,
           "musicbrainz_albumartistid": "; ".join(meta.artist_ids)}
    details = {"releasetype": meta.release_type, "releasestatus": meta.status, "releasecountry": meta.country,
               "originaldate": meta.original_date, "label": meta.label, "catalognumber": meta.catalog, "barcode": meta.barcode,
               "asin": meta.asin, "media": meta.media_format, "musicbrainz_albumcomment": meta.album_tags.get("musicbrainz_albumcomment", "")}
    credits: dict[str, str] = {}
    extras = {k: v for k, v in meta.album_tags.items() if k != "musicbrainz_albumcomment"}
    core = {"album": meta.album, "albumartist": meta.artist, "date": meta.year, "discnumber": f"{meta.disc_position}/{meta.disc_total}"}
    if 0 < n <= len(meta.track_info):
        ti = meta.track_info[n - 1]
        title, artist = meta.tracks[n - 1] if n <= len(meta.tracks) else ("", "")
        core.update({"title": title, "artist": artist, "tracknumber": f"{n}/{len(meta.tracks)}"})
        ids.update({"musicbrainz_trackid": ti.get("recording_id", ""), "musicbrainz_releasetrackid": ti.get("track_id", ""),
                    "musicbrainz_artistid": "; ".join(ti.get("artist_ids", []))})
        details["isrc"] = ti.get("isrc", "")
        for k, v in ti.get("tags", {}).items():
            (extras if k in ("language", "artistsort", "artists", "comment") else credits)[k] = v
    if "compilation" in meta.release_type:
        core["compilation"] = "1"
    return {name: {k: v for k, v in d.items() if v} for name, d in
            (("core", core), ("ids", ids), ("details", details), ("credits", credits), ("extras", extras))}


def musicbrainz_tags(meta: cdrip.DiscMeta, n: int = 0, detail: str = "full") -> dict[str, str]:
    """Picard-kompatible Zusatz-Tags (ohne Titel/Artist/Album – die kommen aus dem Ripper-Fenster).
    detail: "basic" = IDs + Release-Details (Typ, Label, Land, Barcode, ISRC …); "full" zusätzlich Credits (Komponist, Produzent,
    Mitwirkende …), Werk, Sprache, Sortierfelder, Genres, Totals, Disc-Untertitel."""
    g = mb_tag_groups(meta, n)
    out = {**g["ids"], **g["details"]}
    if detail == "full":
        out.update(g["credits"])
        for k, v in g["extras"].items():
            out.setdefault(k, v)                                # Track-Werte (z. B. Sprache des Werks) haben Vorrang
    return out


def build_tags(job: RipJob, n: int) -> dict[str, str]:
    tm = job.track_meta.get(n, TrackMeta())
    default_title = "Hidden Track One Audio" if n == 0 else f"Track {n:02d}"
    tags = {"artist": tm.artist or job.meta.artist, "album": job.meta.album, "title": tm.title or default_title,
            "tracknumber": f"{n + job.track_offset}/{len(job.disc.audio_tracks) + job.track_offset}", "discnumber": f"{job.disc_number}/{job.disc_total}",
            "date": job.year or job.meta.year, "genre": job.genre or job.meta.genre,
            "compilation": "1" if job.compilation else ""}
    if job.write_mb_tags:
        for k, v in musicbrainz_tags(job.meta, n if not job.as_one else 0, job.mb_detail).items():
            tags.setdefault(k, v)                    # im Fenster bearbeitete Werte (Genre, Jahr, Künstler …) haben Vorrang
    if job.as_one:
        tags.update(title=job.meta.album or tags["title"], tracknumber="1/1")
    if job.album_artist or job.meta.artist:
        tags["albumartist"] = job.album_artist or job.meta.artist
    return {k: v for k, v in tags.items() if v}


class RipSession:
    def __init__(self, job: RipJob, on_status: Callable[[int, str], None], on_progress: Callable[[int, float], None],
                 on_done: Callable[[int, cdrip.RipResult, object], None]):
        self.job, self.on_status, self.on_progress, self.on_done = job, on_status, on_progress, on_done
        self.cancel = threading.Event()
        self.log: list[str] = []
        self.dsts: list[Path] = []
        self._conv_errors: dict[Path, str] = {}

    def run(self) -> list[cdrip.RipResult]:
        """Rippt alle gewählten Tracks. Temp-Ordner und Encoder-Thread werden auch bei Fehlern/Abbruch aufgeräumt."""
        tmp = Path(tempfile.mkdtemp(prefix="psyrip_rip_"))
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            return self._run(tmp, pool)
        finally:
            pool.shutdown(wait=True)
            shutil.rmtree(tmp, ignore_errors=True)

    def _run(self, tmp: Path, pool: ThreadPoolExecutor) -> list[cdrip.RipResult]:
        j, results = self.job, []
        ar, ar_offline = None, False
        if j.use_accuraterip:
            self.on_status(-1, tr("AccurateRip-Abfrage…"))
            try:
                ar = cdrip.fetch_accuraterip(j.disc)
            except cdrip.AccurateRipUnavailable as e:
                ar_offline = True
                self.log.append(str(e))
                self.on_status(-1, str(e))
        pending = []
        audio = j.disc.audio_tracks
        with cdrip.CDDrive(j.drive) as drive:
            drive.set_max_speed()
            todo = [t for t in audio if t.number in j.tracks]
            htoa = cdrip.htoa_track(j.disc)
            if htoa and 0 in j.tracks:
                todo.insert(0, htoa)
            if j.as_one and todo:
                todo = [cdrip.Track(todo[0].number, todo[0].start, todo[-1].end)]
            for t in todo:
                if self.cancel.is_set():
                    break
                self.on_status(t.number, tr("Rippe…"))
                pcm, bad, rr = cdrip.rip_range(drive, j.disc, t.start, t.sectors, j.options,
                                               self._progress(t), self.cancel)
                res = cdrip.RipResult(t.number, secure=not bad, bad_sectors=bad, rereads=rr)
                if self.cancel.is_set():
                    res.cancelled = True
                    results.append(res)
                    break
                aborted = len(pcm) < t.sectors * cdrip.SECTOR
                if aborted:
                    res.secure = False
                res.crc_v1, res.crc_v2 = cdrip.accuraterip_crc(pcm, t is audio[0], t is audio[-1])
                if not j.as_one and t.number != 0 and not aborted and (ar is not None or j.use_accuraterip):
                    res.accurate = (tr("AccurateRip nicht erreichbar") if ar_offline
                                    else cdrip.verify_track(ar, audio.index(t), res.crc_v1, res.crc_v2))
                wav = tmp / f"track{t.number:02d}.wav"
                cdrip.save_wav(wav, pcm)
                res.pcm_path = wav
                status = (tr("Sicher") if res.secure else tr("UNSICHER ({0} Sektoren{1})").format(len(bad), tr(", abgebrochen") if aborted else "")) + (f" · {res.accurate}" if res.accurate else "")
                self._conv_errors[wav] = ""
                if not res.secure and j.error_if_insecure:
                    self._conv_errors[wav] = tr("Rip unsicher")
                elif res.accurate.startswith("Inaccurate") and j.error_if_inaccurate:
                    self._conv_errors[wav] = tr("AccurateRip: nicht übereinstimmend")
                if not res.secure and j.cancel_on_insecure:
                    self.cancel.set()
                self.log.append(tr("Track {0:02d}: {1}; Re-Reads: {2}; CRC v1 {3:08X} v2 {4:08X}").format(t.number, status, rr, res.crc_v1, res.crc_v2))
                self.on_status(t.number, tr("Encodiere… ") + status)
                results.append(res)
                pending.append(pool.submit(self._encode, t.number, wav, res, status))
        for f in pending:
            f.result()
        self._album_gain()
        return results

    def _progress(self, t: cdrip.Track) -> Callable[[float], None]:
        """Fortschritt plus Lesegeschwindigkeit (Vielfaches von 1×, 75 Sektoren/s) in der Statusspalte."""
        t0 = time.monotonic()

        def cb(f: float):
            self.on_progress(t.number, f)
            el = time.monotonic() - t0
            if el > 0.5:
                self.on_status(t.number, tr("Rippe… {0:.1f}×").format(f * t.sectors / 75 / el))
        return cb

    def _album_gain(self):
        """Jede Datei wird einzeln kodiert; der Album-Gain entsteht erst hier aus den Track-Gains."""
        from .tags import read_tags, write_tags
        rg = next((s for s in self.job.settings.dsp if s.name == "ReplayGain"), None)
        if not rg or not rg.settings.get("album", True) or len(self.dsts) < 2:
            return
        try:
            tags = [read_tags(p) for p in self.dsts]
            gains = [float(t["replaygain_track_gain"].split()[0]) for t in tags]
            peak = max(float(t["replaygain_track_peak"]) for t in tags)
            for p in self.dsts:
                write_tags(p, {"replaygain_album_gain": f"{sum(gains) / len(gains):+.2f} dB", "replaygain_album_peak": f"{peak:.6f}"})
        except (KeyError, ValueError, OSError) as e:
            self.log.append(tr("Album-Gain nicht gesetzt: {0}").format(e))

    def _encode(self, n: int, wav: Path, res: cdrip.RipResult, status: str):
        j = self.job
        conv = Converter(j.settings)
        conv.tags_map[wav] = build_tags(j, n)
        conv.art_map = {wav: j.meta.cover} if j.meta.cover else {}
        if self._conv_errors.get(wav):
            conv.error_map[wav] = self._conv_errors[wav]
        # Naming-Kontext: Dateiname der WAV hat keine Aussagekraft, Tags steuern alles
        out = conv.run([wav])[0]
        res.pcm_path = None
        wav.unlink(missing_ok=True)
        if out.status == "ok" and out.dst:
            self.dsts.append(out.dst)
        self.on_done(n, res, out)
        self.on_status(n, (tr("Fertig · ") if out.status == "ok" else f"{out.status}: {out.message} · ") + status)

    def write_log(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "psyrip_rip.log").write_text("\n".join(self.log), encoding="utf-8")
