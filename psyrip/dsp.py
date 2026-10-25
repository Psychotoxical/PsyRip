"""DSP-Effekte und Aktionen. Audioeffekte werden zu einem ffmpeg-Filtergraph zusammengesetzt."""
from __future__ import annotations

from .i18n import tr
import math
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import analysis, tagproc
from .tags import AudioInfo


@dataclass
class Field:
    key: str
    label: str
    kind: str = "str"              # str | int | float | bool | choice | path | text
    default: object = ""
    choices: list[tuple[str, str]] = field(default_factory=list)
    lo: float = -1e9
    hi: float = 1e9


@dataclass
class Job:
    src: Path
    dst: Path
    info: AudioInfo
    tags: dict[str, str]
    filters: list[str] = field(default_factory=list)
    skip: str | None = None        # Grund, warum übersprungen wird
    copy_only: bool = False
    bits: str | None = None        # "16" | "24" | "32" | "float"
    dither: bool = False
    channels: int | None = None
    rate: int | None = None
    threads: int | None = None
    throttle: float | None = None  # Echtzeitfaktor
    insert_front: list[Path] = field(default_factory=list)
    insert_end: list[Path] = field(default_factory=list)
    tag_override: dict[str, str] | None = None
    errors: list[str] = field(default_factory=list)
    post: list[Callable[["Job", bool], None]] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def length(self) -> float:
        return self.info.length


class DSP:
    name = ""
    category = "Effekt"
    fields: list[Field] = []

    def defaults(self) -> dict:
        return {f.key: f.default for f in self.fields}

    def prepare(self, job: Job, s: dict) -> None: ...
    def finish_batch(self, jobs: list[Job], s: dict) -> None: ...


REGISTRY: dict[str, DSP] = {}


def dsp(cls):
    inst = cls()
    REGISTRY[inst.name] = inst
    return cls


def _ms(v) -> float:
    return float(v) / 1000.0


# ---------------------------------------------------------------- Audioeffekte
@dsp
class BitDepth(DSP):
    name = "Bit Depth"
    fields = [Field("bits", tr("Bit-Tiefe"), "choice", "16", [("16 Bit", "16"), ("24 Bit", "24"), ("32 Bit", "32"), ("32 Bit Float", "float")]),
              Field("dither", tr("Dither (Dreieck) beim Reduzieren"), "bool", True)]

    def prepare(self, job, s):
        job.bits, job.dither = s["bits"], bool(s["dither"])


@dsp
class ChannelCount(DSP):
    name = "Channel Count"
    fields = [Field("channels", tr("Kanäle erzwingen (0 = Min/Max verwenden)"), "int", 2, lo=0, hi=8),
              Field("min", "Minimum", "int", 0, lo=0, hi=8), Field("max", "Maximum", "int", 0, lo=0, hi=8)]

    def prepare(self, job, s):
        if int(s["channels"]):
            job.channels = int(s["channels"])
            return
        ch = job.info.channels or 2
        lo, hi = int(s["min"]), int(s["max"])
        if lo and ch < lo:
            job.channels = lo
        elif hi and ch > hi:
            job.channels = hi


@dsp
class ChannelMapper(DSP):
    name = "Channel Mapper"
    fields = [Field("layout", tr("Ausgabe-Layout"), "str", "stereo"),
              Field("expr", tr("Zuordnung (pan-Syntax)"), "str", "c0=c0|c1=c1")]

    def prepare(self, job, s):
        job.filters.append(f"pan={s['layout']}|{s['expr']}")


@dsp
class Resample(DSP):
    name = "Resample"
    fields = [Field("rate", tr("Zielfrequenz (Hz, 0 = Min/Max verwenden)"), "int", 44100),
              Field("min", "Minimum (Hz)", "int", 0), Field("max", "Maximum (Hz)", "int", 0)]

    def prepare(self, job, s):
        sr = job.info.sample_rate or 44100
        if int(s["rate"]):
            job.rate = int(s["rate"])
        else:
            lo, hi = int(s["min"]) or 0, int(s["max"]) or 10**9
            job.rate = max(lo, min(hi, sr))


@dsp
class Fade(DSP):
    name = "Fade"
    fields = [Field("in_ms", tr("Einblenden (ms)"), "int", 0), Field("out_ms", tr("Ausblenden (ms)"), "int", 6000)]

    def prepare(self, job, s):
        if int(s["in_ms"]):
            job.filters.append(f"afade=t=in:d={_ms(s['in_ms'])}")
        if int(s["out_ms"]) and job.length:
            d = _ms(s["out_ms"])
            job.filters.append(f"afade=t=out:st={max(job.length - d, 0):.3f}:d={d}")


@dsp
class Trim(DSP):
    name = "Trim"
    fields = [Field("start_ms", tr("Vom Anfang entfernen (ms)"), "int", 0), Field("end_ms", tr("Vom Ende entfernen (ms)"), "int", 0)]

    def prepare(self, job, s):
        st, en = _ms(s["start_ms"]), _ms(s["end_ms"])
        if st:
            job.filters.append(f"atrim=start={st},asetpts=PTS-STARTPTS")
        if en and job.length:
            job.filters.append(f"atrim=end={max(job.length - st - en, 0.001):.3f},asetpts=PTS-STARTPTS")


@dsp
class Grabber(DSP):
    name = "Grabber"
    fields = [Field("grab_ms", tr("Länge (ms)"), "int", 10000), Field("pos_ms", "Position (ms)", "int", 0),
              Field("from_end", tr("Position vom Ende"), "bool", False)]

    def prepare(self, job, s):
        start = _ms(s["pos_ms"])
        if s["from_end"]:
            start = max(job.length - start, 0)
        job.filters.append(f"atrim=start={start:.3f}:duration={_ms(s['grab_ms'])},asetpts=PTS-STARTPTS")


@dsp
class MaximumLength(DSP):
    name = "Maximum Length"
    fields = [Field("seconds", tr("Maximale Länge (s)"), "float", 30.0), Field("percent", tr("oder Prozent der Länge (0 = aus)"), "float", 0.0)]

    def prepare(self, job, s):
        lim = float(s["seconds"])
        if float(s["percent"]) and job.length:
            lim = min(lim, job.length * float(s["percent"]) / 100) if lim else job.length * float(s["percent"]) / 100
        if lim and (not job.length or job.length > lim):
            job.filters.append(f"atrim=end={lim:.3f}")


@dsp
class MinimumLength(DSP):
    name = "Minimum Length"
    fields = [Field("seconds", tr("Minimale Länge (s)"), "float", 10.0)]

    def prepare(self, job, s):
        job.filters.append(f"apad=whole_dur={float(s['seconds'])}")


@dsp
class WriteSilence(DSP):
    name = "Write Silence"
    fields = [Field("where", "Position", "choice", "start", [(tr("Anfang"), "start"), (tr("Ende"), "end")]),
              Field("ms", tr("Länge (ms)"), "int", 1000)]

    def prepare(self, job, s):
        if s["where"] == "start":
            job.filters.append(f"adelay={int(s['ms'])}:all=1")
        else:
            job.filters.append(f"apad=pad_dur={_ms(s['ms'])}")


@dsp
class TrimSilence(DSP):
    name = "Trim Silence"
    fields = [Field("thr", tr("Schwelle (dB)"), "float", -50.0), Field("start", tr("Am Anfang"), "bool", True), Field("end", tr("Am Ende"), "bool", True)]

    def prepare(self, job, s):
        rm = f"silenceremove=start_periods=1:start_threshold={s['thr']}dB:detection=peak"
        if s["start"]:
            job.filters.append(rm)
        if s["end"]:
            job.filters += ["areverse", rm, "areverse"]


@dsp
class Highpass(DSP):
    name = "Highpass"
    fields = [Field("freq", tr("Grenzfrequenz (Hz)"), "int", 20)]

    def prepare(self, job, s):
        job.filters.append(f"highpass=f={int(s['freq'])}")


@dsp
class Lowpass(DSP):
    name = "Lowpass"
    fields = [Field("freq", tr("Grenzfrequenz (Hz)"), "int", 40000)]

    def prepare(self, job, s):
        job.filters.append(f"lowpass=f={int(s['freq'])}")


@dsp
class Bandpass(DSP):
    name = "Bandpass Filter"
    fields = [Field("low", tr("Untere Frequenz (Hz)"), "int", 100), Field("high", tr("Obere Frequenz (Hz)"), "int", 8000)]

    def prepare(self, job, s):
        job.filters += [f"highpass=f={int(s['low'])}", f"lowpass=f={int(s['high'])}"]


_EQ_BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


@dsp
class GraphicEQ(DSP):
    name = "Graphic Equalizer"
    fields = [Field(f"b{f}", f"{f} Hz (dB)", "float", 0.0, lo=-12, hi=12) for f in _EQ_BANDS]

    def prepare(self, job, s):
        for f in _EQ_BANDS:
            g = float(s[f"b{f}"])
            if g:
                job.filters.append(f"equalizer=f={f}:width_type=o:w=1:g={g}")


@dsp
class DynamicRangeCompression(DSP):
    name = "Dynamic Range Compression"
    fields = [Field("thr", tr("Schwelle (dB)"), "float", -18.0), Field("ratio", tr("Verhältnis"), "float", 4.0),
              Field("attack", "Attack (ms)", "float", 20.0), Field("release", "Release (ms)", "float", 600.0)]

    def prepare(self, job, s):
        thr = 10 ** (float(s["thr"]) / 20)
        job.filters.append(f"acompressor=threshold={thr:.5f}:ratio={s['ratio']}:attack={s['attack']}:release={s['release']}:knee=1")


@dsp
class Karaoke(DSP):
    name = "Karaoke (Voice, Instrument Removal)"
    fields = [Field("mode", tr("Entfernen"), "choice", "voice", [(tr("Gesang"), "voice"), (tr("Instrumente"), "instr")])]

    def prepare(self, job, s):
        job.filters.append("pan=stereo|c0=c0-c1|c1=c1-c0" if s["mode"] == "voice" else "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1")


@dsp
class Loop(DSP):
    name = "Loop"
    fields = [Field("times", tr("Wiederholungen (gesamt)"), "int", 2, lo=1),
              Field("to_length", tr("oder bis zur Länge (s, 0 = aus)"), "float", 0.0)]

    def prepare(self, job, s):
        if float(s["to_length"]) and job.length:
            n = max(int(math.ceil(float(s["to_length"]) / job.length)) - 1, 0)
            job.filters += [f"aloop=loop={n}:size=2147483647", f"atrim=end={float(s['to_length'])}"]
        else:
            job.filters.append(f"aloop=loop={int(s['times']) - 1}:size=2147483647")


@dsp
class Reverse(DSP):
    name = "Reverse"

    def prepare(self, job, s):
        job.filters.append("areverse")


@dsp
class Speed(DSP):
    name = "Speed up, Slow down"
    fields = [Field("factor", tr("Faktor"), "float", 1.0, lo=0.1, hi=10)]

    def prepare(self, job, s):
        sr = job.info.sample_rate or 44100
        job.filters += [f"asetrate={int(sr * float(s['factor']))}", f"aresample={sr}"]


@dsp
class Deemphasis(DSP):
    name = "Audio CD - De-emphasis"

    def prepare(self, job, s):
        job.filters.append("aemphasis=type=cd:mode=reproduction")


@dsp
class HDCD(DSP):
    name = "HDCD"
    fields = [Field("align", tr("20 Bit in oberen 24 Bit ausrichten"), "bool", True)]

    def prepare(self, job, s):
        job.filters.append("hdcd")
        job.bits = "24"


@dsp
class HiddenTrackSilence(DSP):
    name = "Audio CD - Hidden Track Silence Removal"
    fields = [Field("thr", tr("Schwelle (dB)"), "float", -60.0), Field("secs", tr("Mindestlänge der Stille (s)"), "float", 30.0)]

    def prepare(self, job, s):
        job.filters.append(f"silenceremove=stop_periods=-1:stop_duration={s['secs']}:stop_threshold={s['thr']}dB")


@dsp
class SilenceTrackDeletion(DSP):
    name = "Audio CD - Silence Track Deletion"
    fields = [Field("thr", tr("Schwelle (dB)"), "float", -70.0)]

    def prepare(self, job, s):
        if analysis.max_volume(job.src) < float(s["thr"]):
            job.skip = tr("Stille-Track")


@dsp
class RemoveGaps(DSP):
    name = "Audio CD - Remove Gaps"

    def prepare(self, job, s):
        job.extra["remove_gaps"] = True    # wird vom CD-Ripper mit Index-Infos ausgewertet


@dsp
class InsertAudio(DSP):
    name = "Insert Audio"
    fields = [Field("file", tr("Audiodatei"), "path", ""), Field("where", "Position", "choice", "front", [(tr("Anfang"), "front"), (tr("Ende"), "end")])]

    def prepare(self, job, s):
        if s["file"]:
            (job.insert_front if s["where"] == "front" else job.insert_end).append(Path(s["file"]))


@dsp
class CustomFilter(DSP):
    name = "Custom ffmpeg Filter"
    fields = [Field("filter", tr("ffmpeg -af Ausdruck"), "str", "")]

    def prepare(self, job, s):
        if s["filter"].strip():
            job.filters.append(s["filter"].strip())


# -------------------------------------------------------------- Lautstärke
@dsp
class VolumeNormalize(DSP):
    name = "Volume Normalize"
    fields = [Field("mode", tr("Methode"), "choice", "peak",
                    [("Peak to Peak", "peak"), ("ReplayGain", "rg"), ("EBU R128", "ebu"), (tr("Adaptiv (EBU)"), "adaptive"),
                     (tr("Feste Verstärkung"), "fixed"), (tr("Reduzieren falls darüber"), "reduce")]),
              Field("desired", tr("Gewünschter Pegel (dB / LUFS)"), "float", 0.0),
              Field("fixed", tr("Feste Verstärkung (dB)"), "float", 0.0),
              Field("max_amp", tr("Maximale Verstärkung (dB)"), "float", 30.0)]

    def prepare(self, job, s):
        m, des = s["mode"], float(s["desired"])
        if m == "adaptive":
            job.filters.append("dynaudnorm=f=500:g=15")
            return
        if m == "fixed":
            gain = float(s["fixed"])
        elif m in ("peak", "reduce"):
            gain = des - analysis.max_volume(job.src)
            if m == "reduce":
                gain = min(gain, 0.0)
        else:
            ref = -18.0 if m == "ebu" else -14.0
            l = analysis.loudness(job.src)["lufs"]
            gain = ref - l if l == l else 0.0
        gain = min(gain, float(s["max_amp"]))
        job.filters.append(f"volume={gain:.3f}dB")


@dsp
class ReplayGain(DSP):
    name = "ReplayGain"
    fields = [Field("ref", tr("Referenzlautheit (LUFS)"), "float", -18.0),
              Field("album", tr("Album-Gain berechnen"), "bool", True),
              Field("by_folder", tr("Album = gleicher Ordner (statt Album-Tag)"), "bool", False)]

    def prepare(self, job, s):
        def after(j: Job, ok: bool):
            if not ok:
                return
            j.extra["rg"] = analysis.replaygain(j.src, float(s["ref"]))
        job.post.append(after)

    def finish_batch(self, jobs, s):
        from .tags import write_tags
        done = [j for j in jobs if j.extra.get("rg") and j.dst.exists()]
        album: dict[str, list[Job]] = {}
        for j in done:
            key = str(j.src.parent) if s["by_folder"] else j.tags.get("album") or str(j.dst.parent)
            album.setdefault(key, []).append(j)
        for group in album.values():
            gains = [float(j.extra["rg"]["replaygain_track_gain"].split()[0]) for j in group]
            peaks = [float(j.extra["rg"]["replaygain_track_peak"]) for j in group]
            ag = f"{sum(gains) / len(gains):+.2f} dB"
            for j in group:
                t = dict(j.extra["rg"])
                if s["album"]:
                    t.update({"replaygain_album_gain": ag, "replaygain_album_peak": f"{max(peaks):.6f}"})
                try:
                    write_tags(j.dst, t)
                except Exception as e:
                    j.errors.append(tr("ReplayGain-Tag: {0}").format(e))


@dsp
class ReplayGainApply(DSP):
    name = "ReplayGain (Apply)"
    fields = [Field("mode", tr("Modus"), "choice", "track", [("Track", "track"), ("Album", "album")]),
              Field("preamp", "Preamp (dB)", "float", 0.0)]

    def prepare(self, job, s):
        key = f"replaygain_{s['mode']}_gain"
        val = job.tags.get(key, "")
        try:
            g = float(val.split()[0])
        except (ValueError, IndexError):
            return
        job.filters.append(f"volume={g + float(s['preamp']):.3f}dB")


# --------------------------------------------------------------- Aktionen
@dsp
class IDTagProcessing(DSP):
    name = "ID Tag Processing"
    category = "Aktion"
    fields = [Field("map", tr("Map (quelle>ziel, je Zeile)"), "text", ""),
              Field("delete_mode", tr("Löschen"), "choice", "none", [(tr("Nichts"), "none"), (tr("Alle"), "all"), (tr("Alle außer"), "except"), (tr("Einzelne"), "single")]),
              Field("delete_names", tr("Tags (; getrennt)"), "str", ""),
              Field("capitalize", tr("Groß-/Kleinschreibung"), "choice", "none",
                    [(tr("Unverändert"), "none"), (tr("GROSS"), "upper"), ("klein", "lower"), ("Smart", "smart"), (tr("Erster Buchstabe"), "first")]),
              Field("rules", tr("Regeln (SET x=y IF a=b)"), "text", ""),
              Field("replace", tr("Ersetzen (alt=>neu, [nocase])"), "text", ""),
              Field("multi_artist_to_semicolon", tr("Mehrere Künstler zu 'A; B'"), "bool", False),
              Field("feat_to_title", tr("2. Künstler nach '(feat. …)' im Titel"), "bool", False),
              Field("drop_year_month_day", tr("Monat & Tag aus Jahr entfernen"), "bool", False),
              Field("drop_track_count", tr("Track-Anzahl entfernen (4/12 → 4)"), "bool", False),
              Field("drop_disc_count", tr("Disc-Anzahl entfernen"), "bool", False),
              Field("additions", tr("Hinzufügen (tag=wert)"), "text", ""),
              Field("max_art_px", tr("Max. Cover-Größe (px, 0 = unverändert)"), "int", 0),
              Field("max_art_kb", tr("Max. Cover-Dateigröße (KB, 0 = unbegrenzt)"), "int", 0),
              Field("force_jpg", tr("Eingebettetes Cover immer als JPG"), "bool", False),
              Field("export_art", tr("Cover als Folder.jpg exportieren"), "bool", False),
              Field("import_art", tr("Cover aus Folder.jpg importieren"), "bool", False),
              Field("audio_hash", tr("CRC32/MD5 des Audios als Tag schreiben"), "bool", False)]

    def prepare(self, job, s):
        job.tag_override = tagproc.process(job.tag_override if job.tag_override is not None else job.tags, s)
        if any(s[k] for k in ("max_art_px", "max_art_kb", "force_jpg", "export_art", "import_art", "audio_hash")):
            def after(j: Job, ok: bool):
                if not ok or not j.dst.exists():
                    return
                from .tags import process_art, write_tags
                process_art(j.dst, int(s["max_art_px"]), int(s["max_art_kb"]), bool(s["force_jpg"]), bool(s["export_art"]), bool(s["import_art"]))
                if s["audio_hash"]:
                    write_tags(j.dst, {"audio_crc32": analysis.audio_hash(j.dst, "crc32"), "audio_md5": analysis.audio_hash(j.dst, "md5")})
            job.post.append(after)


@dsp
class DeleteSource(DSP):
    name = "Delete Source File"
    category = "Aktion"
    fields = [Field("empty_folders", tr("Leere Ordner entfernen"), "bool", False)]

    def prepare(self, job, s):
        def after(j: Job, ok: bool):
            if ok and not j.errors and j.src != j.dst:
                j.src.unlink(missing_ok=True)
                if s["empty_folders"]:
                    p = j.src.parent
                    while p.exists() and not any(p.iterdir()) and p.parent != p:
                        p.rmdir()
                        p = p.parent
        job.post.append(after)


@dsp
class DeleteDestOnError(DSP):
    name = "Delete Destination File on Error"
    category = "Aktion"

    def prepare(self, job, s):
        job.post.append(lambda j, ok: (not ok or j.errors) and j.dst.unlink(missing_ok=True))


@dsp
class MoveDestOnError(DSP):
    name = "Move Destination File on Error"
    category = "Aktion"
    fields = [Field("folder", tr("Zielordner"), "path", "")]

    def prepare(self, job, s):
        def after(j: Job, ok: bool):
            if (not ok or j.errors) and j.dst.exists() and s["folder"]:
                Path(s["folder"]).mkdir(parents=True, exist_ok=True)
                shutil.move(str(j.dst), str(Path(s["folder"]) / j.dst.name))
        job.post.append(after)


@dsp
class FolderJpgPreserve(DSP):
    name = "Folder.jpg Preserve"
    category = "Aktion"
    fields = [Field("patterns", tr("Dateien (; getrennt)"), "str", "folder.jpg;cover.jpg"), Field("move", tr("Verschieben statt kopieren"), "bool", False)]

    def prepare(self, job, s):
        def after(j: Job, ok: bool):
            if not ok:
                return
            for pat in str(s["patterns"]).split(";"):
                for f in j.src.parent.glob(pat.strip()):
                    target = j.dst.parent / f.name
                    if f.is_file() and not target.exists():
                        (shutil.move if s["move"] else shutil.copy2)(str(f), str(target))
        job.post.append(after)


@dsp
class PlaylistWriter(DSP):
    name = "Playlist Writer"
    category = "Aktion"
    fields = [Field("format", "Format", "choice", "m3u8", [("m3u", "m3u"), ("m3u8 (Unicode)", "m3u8"), ("pls", "pls")]),
              Field("name", tr("Dateiname"), "str", "playlist"), Field("folder", tr("Ordner (leer = Zielordner)"), "path", "")]

    def finish_batch(self, jobs, s):
        files = [j for j in jobs if j.dst.exists() and not j.errors]
        if not files:
            return
        folder = Path(s["folder"]) if s["folder"] else files[0].dst.parent
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / f"{s['name']}.{s['format']}"
        if s["format"] == "pls":
            lines = ["[playlist]"]
            for i, j in enumerate(files, 1):
                lines += [f"File{i}={j.dst}", f"Title{i}={j.tags.get('artist', '')} - {j.tags.get('title', '')}", f"Length{i}={int(j.length)}"]
            lines += [f"NumberOfEntries={len(files)}", "Version=2"]
        else:
            lines = ["#EXTM3U"]
            for j in files:
                lines += [f"#EXTINF:{int(j.length)},{j.tags.get('artist', '')} - {j.tags.get('title', '')}", str(j.dst)]
        out.write_text("\n".join(lines) + "\n", encoding="utf-8" if s["format"] != "m3u" else "mbcs")


@dsp
class PreserveAttributes(DSP):
    name = "Preserve Source Attributes"
    category = "Aktion"

    def prepare(self, job, s):
        def after(j: Job, ok: bool):
            if ok and j.dst.exists():
                st = j.src.stat() if j.src.exists() else None
                if st:
                    os.utime(j.dst, (st.st_atime, st.st_mtime))
        job.post.append(after)


@dsp
class RunExternal(DSP):
    name = "Run External"
    category = "Aktion"
    fields = [Field("program", tr("Programm"), "path", ""), Field("args", tr("Argumente ([infile], [outfile])"), "str", '"[outfile]"'),
              Field("when", tr("Zeitpunkt"), "choice", "after", [(tr("Vor der Konvertierung"), "before"), (tr("Nach der Konvertierung"), "after"), (tr("Nach dem Batch"), "batch")])]

    def _run(self, s, j: Job | None):
        a = str(s["args"])
        if j:
            a = a.replace("[infile]", str(j.src)).replace("[outfile]", str(j.dst))
        subprocess.run(f'"{s["program"]}" {a}', shell=True)

    def prepare(self, job, s):
        if not s["program"]:
            return
        if s["when"] == "before":
            self._run(s, job)
        elif s["when"] == "after":
            job.post.append(lambda j, ok: ok and self._run(s, j))

    def finish_batch(self, jobs, s):
        if s["program"] and s["when"] == "batch":
            self._run(s, None)


@dsp
class PlaySound(DSP):
    name = "Play Sound After Conversion"
    category = "Aktion"
    fields = [Field("ok_sound", tr("Sound (Erfolg)"), "path", ""), Field("err_sound", tr("Sound (Fehler)"), "path", ""),
              Field("only_error", tr("Nur bei Fehlern"), "bool", False)]

    def finish_batch(self, jobs, s):
        import winsound
        err = any(j.errors for j in jobs)
        f = s["err_sound"] if err else ("" if s["only_error"] else s["ok_sound"])
        if f:
            winsound.PlaySound(f, winsound.SND_FILENAME | winsound.SND_ASYNC)
        elif not (s["only_error"] and not err):
            winsound.MessageBeep()


@dsp
class ConditionalEncoding(DSP):
    name = "Conditional Encoding"
    category = "Aktion"
    fields = [Field("dest_exists", tr("Überspringen, wenn Ziel existiert"), "bool", True),
              Field("extensions", tr("Quell-Erweiterungen (; getrennt)"), "str", ""),
              Field("min_bitrate", tr("Quell-Bitrate ≤ (kbps, 0 = aus)"), "int", 0),
              Field("bits_le", tr("Quell-Bit-Tiefe ≤ (0 = aus)"), "int", 0),
              Field("rate_le", tr("Quell-Samplerate ≤ (Hz, 0 = aus)"), "int", 0),
              Field("action", tr("Aktion bei Treffer"), "choice", "copy", [(tr("1:1 kopieren"), "copy"), (tr("Überspringen"), "skip")])]

    def prepare(self, job, s):
        if s["dest_exists"] and Path(job.extra.get("natural_dst", job.dst)).exists():
            job.skip = tr("Ziel existiert")
            return
        exts = {e.strip().lower().lstrip(".") for e in str(s["extensions"]).split(";") if e.strip()}
        hit = job.src.suffix.lower().lstrip(".") in exts if exts else False
        if int(s["min_bitrate"]) and job.info.bitrate and job.info.bitrate / 1000 <= int(s["min_bitrate"]):
            hit = True
        if int(s["bits_le"]) and job.info.bits and job.info.bits <= int(s["bits_le"]):
            hit = True
        if int(s["rate_le"]) and job.info.sample_rate and job.info.sample_rate <= int(s["rate_le"]):
            hit = True
        if hit:
            if s["action"] == "copy":
                job.copy_only = True
            else:
                job.skip = tr("Bedingung erfüllt")


@dsp
class CPUThrottle(DSP):
    name = "CPU Throttle"
    category = "Aktion"
    fields = [Field("speed", tr("Max. Geschwindigkeit (x Echtzeit)"), "float", 12.0, lo=0.5)]

    def prepare(self, job, s):
        job.throttle = float(s["speed"])


@dsp
class MultiCPUForce(DSP):
    name = "Multi-CPU Force"
    category = "Aktion"
    fields = [Field("cpus", tr("Anzahl CPUs"), "int", 1, lo=1)]

    def prepare(self, job, s):
        job.threads = int(s["cpus"])


@dsp
class WriteMetadataFile(DSP):
    name = "Write Metadata File"
    category = "Aktion"
    fields = [Field("xslt", tr("XSLT-Vorlage (leer = Standard-XML)"), "path", ""),
              Field("ext", tr("Dateiendung der Ausgabe"), "str", ".xml")]

    def prepare(self, job, s):
        def after(j: Job, ok: bool):
            if not ok:
                return
            from xml.sax.saxutils import escape
            tags = j.tag_override if j.tag_override is not None else j.tags
            body = "".join(f'  <tag name="{escape(k)}">{escape(v)}</tag>\n' for k, v in tags.items())
            xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<dBpoweramp><IDTags>\n{body}</IDTags></dBpoweramp>\n'
            out = j.dst.with_suffix(s["ext"] or ".xml")
            if s["xslt"]:
                from lxml import etree
                res = etree.XSLT(etree.parse(s["xslt"]))(etree.fromstring(xml.encode("utf-8")))
                out.write_bytes(bytes(res))
            else:
                out.write_text(xml, encoding="utf-8")
        job.post.append(after)


@dsp
class ReadMetadataFile(DSP):
    name = "Read metadata file"
    category = "Aktion"
    fields = [Field("xslt", tr("XSLT-Vorlage (leer = Standard-XML)"), "path", "")]

    def prepare(self, job, s):
        x = job.src.with_suffix(".xml")
        if not x.exists():
            return
        from lxml import etree
        doc = etree.parse(str(x))
        if s["xslt"]:
            doc = etree.XSLT(etree.parse(s["xslt"]))(doc)
        t = dict(job.tag_override if job.tag_override is not None else job.tags)
        for el in doc.getroot().iter():
            if isinstance(el.tag, str) and el.tag not in ("IDTags", "dBpoweramp") and el.text and el.text.strip():
                t[(el.get("name") or el.tag).lower()] = el.text.strip()
        job.tag_override = t


def list_by_category() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for n, d in REGISTRY.items():
        out.setdefault(d.category, []).append(n)
    return {k: sorted(v) for k, v in out.items()}
