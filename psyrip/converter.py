"""Konvertierungs-Engine: Dateiliste → Naming → DSP-Kette → ffmpeg → Tags/Cover → Nach-Aktionen."""
from __future__ import annotations

from .i18n import tr
import datetime as _dt
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from . import analysis
from .dsp import REGISTRY, Job
from .encoders import ENCODERS, Encoder
from .naming import NamingContext, render
from .tags import read_art, read_info, read_tags, write_art, write_tags

# Namen im Tag-Dialekt -> Namen im Naming-Dialekt
_NAMING_MAP = {"albumartist": "album artist", "tracknumber": "track", "discnumber": "disc", "date": "year"}


@dataclass
class DspStep:
    name: str
    settings: dict = field(default_factory=dict)


@dataclass
class OutputSpec:
    mode: str = "source"            # source | folder | preserve | dynamic
    folder: str = ""
    naming: str = "[artist]\\[album]\\[track] [artist] - [title]"
    overwrite: bool = False


@dataclass
class ConvertSettings:
    encoder: str = "FLAC"
    enc_settings: dict = field(default_factory=dict)
    output: OutputSpec = field(default_factory=OutputSpec)
    dsp: list[DspStep] = field(default_factory=list)
    workers: int = max(1, (os.cpu_count() or 2) - 1)
    verify: bool = False
    low_priority: bool = False
    copy_tags: bool = True
    copy_art: bool = True


@dataclass
class Result:
    src: Path
    dst: Path | None = None
    status: str = "pending"         # ok | skipped | error | cancelled | pending
    message: str = ""


def naming_context(tags: dict[str, str], src: Path, enc: Encoder, info) -> NamingContext:
    t = {_NAMING_MAP.get(k, k): v for k, v in tags.items()}
    comp = str(tags.get("compilation", "")).strip().lower() in ("1", "true", "yes")
    try:
        disc = int(str(tags.get("discnumber", "1")).split("/")[0] or 1)
    except ValueError:
        disc = 1
    total = str(tags.get("discnumber", "")).split("/")
    multi_disc = disc > 1 or (len(total) > 1 and total[1].isdigit() and int(total[1]) > 1)
    return NamingContext(
        tags=t, origpath=str(src.parent), origfilename=src.stem, origdrive=(src.drive + "\\") if src.drive else src.anchor,
        extension=src.suffix.lstrip("."), compilation=comp, disc=max(disc, 2) if multi_disc else 1,
        source_date=_dt.datetime.fromtimestamp(src.stat().st_mtime) if src.exists() else None,
        extra={"k_bitrate": str(info.bitrate // 1000) if info.bitrate else "", "encoder": enc.name,
               "audio_quality": "Lossless" if enc.lossless else "Lossy"})


def _relative(rel: str | Path) -> Path:
    """Macht einen berechneten Pfad relativ zum Ausgabeordner: ohne Laufwerk/Wurzel und ohne '..'-Teile
    (sonst würde z. B. [origpath] den Ausgabeordner ersetzen und zurück in die Quelle schreiben)."""
    # Das Namensschema trennt Ordner mit "\\" – unter Linux/macOS ist das kein Pfadtrenner.
    parts = [x for x in str(rel).replace("\\", "/").split("/")
             if x and x not in ("..", ".") and not x.endswith(":")]
    return Path(*parts) if parts else Path()


def destination(src: Path, tags: dict, enc: Encoder, info, out: OutputSpec, taken: set[str] | None = None) -> Path:
    ext = enc.ext
    if out.mode == "source":
        dst = src.with_suffix(ext)
    elif out.mode == "folder":
        dst = Path(out.folder) / (src.stem + ext)
    elif out.mode == "preserve":
        dst = Path(out.folder) / _relative(src.parent) / (src.stem + ext)
    else:
        rel = render(out.naming, naming_context(tags, src, enc, info)) or src.stem
        dst = Path(out.folder) / _relative(rel + ext)
    if dst.resolve() == src.resolve():
        dst = dst.with_name(dst.stem + "_converted" + dst.suffix)

    def used(p: Path) -> bool:
        return (taken is not None and str(p).lower() in taken) or (not out.overwrite and p.exists())
    if used(dst):
        # Überschreiben erlaubt: nur Kollisionen innerhalb dieses Laufs vermeiden, sonst nummerieren
        n = 2
        while used(dst.with_name(f"{dst.stem} ({n}){dst.suffix}")):
            n += 1
        dst = dst.with_name(f"{dst.stem} ({n}){dst.suffix}")
    if taken is not None:
        taken.add(str(dst).lower())
    return dst


def _sample_fmt_args(job: Job, enc: Encoder) -> list[str]:
    if enc.name in ("Wave", "AIFF") or not job.bits:
        return []
    return {"16": ["-sample_fmt", "s16"], "24": ["-sample_fmt", "s32", "-bits_per_raw_sample", "24"],
            "32": ["-sample_fmt", "s32"], "float": ["-sample_fmt", "flt"]}.get(job.bits, [])


def build_command(job: Job, enc: Encoder, enc_settings: dict, tmp: Path) -> list[str]:
    settings = dict(enc_settings)
    if enc.name in ("Wave", "AIFF") and job.bits in ("16", "24", "32"):
        settings["bits"] = job.bits
    filters = list(job.filters)
    if job.dither and job.bits in ("16", "24"):
        filters.append("aresample=dither_method=triangular")
    cmd: list[str] = []
    inputs = [*job.insert_front, job.src, *job.insert_end]
    for p in inputs:
        cmd += ["-i", str(p)]
    main = len(job.insert_front)
    chain = ",".join(filters) if filters else "anull"
    if len(inputs) == 1:
        cmd += ["-af", chain]
    else:
        sr = job.rate or job.info.sample_rate or 44100
        layout = {1: "mono", 2: "stereo"}.get(job.channels or job.info.channels or 2, "stereo")
        norm = f"aformat=sample_rates={sr}:channel_layouts={layout}"
        parts = []
        for i in range(len(inputs)):
            parts.append(f"[{i}:a]{chain + ',' if i == main else ''}{norm}[a{i}]")
        graph = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(len(inputs))) + f"concat=n={len(inputs)}:v=0:a=1[out]"
        cmd += ["-filter_complex", graph, "-map", "[out]"]
    if len(inputs) == 1:
        cmd += ["-map", "0:a:0"]
    cmd += ["-vn", "-map_metadata", "-1"]
    if job.channels:
        cmd += ["-ac", str(job.channels)]
    if job.rate:
        cmd += ["-ar", str(job.rate)]
    if job.threads:
        cmd += ["-threads", str(job.threads)]
    if enc.external:
        codec = "pcm_s24le" if (job.bits in ("24", "32", "float") and enc.max_bits >= 24) else "pcm_s16le"
        return cmd + ["-c:a", codec, "-f", "wav", "-progress", "pipe:2", "-nostats", "-y", "pipe:1"]
    cmd += _sample_fmt_args(job, enc)
    cmd += enc.args(settings)
    cmd += ["-f", {".m4a": "ipod", ".m4b": "ipod", ".mp3": "mp3", ".flac": "flac", ".opus": "opus", ".ogg": "ogg", ".wav": "wav",
                   ".aif": "aiff", ".wv": "wv", ".wma": "asf", ".spx": "ogg"}.get(enc.ext, enc.ext.lstrip(".")),
            "-progress", "pipe:1", "-nostats", "-y", str(tmp)]
    return cmd


class Converter:
    def __init__(self, settings: ConvertSettings,
                 on_progress: Callable[[int, float], None] | None = None,
                 on_result: Callable[[int, Result], None] | None = None):
        self.s = settings
        self.on_progress = on_progress or (lambda i, f: None)
        self.on_result = on_result or (lambda i, r: None)
        self.cancel_event = threading.Event()
        self.tags_map: dict[Path, dict[str, str]] = {}   # Tags statt der aus der Datei gelesenen (z. B. beim CD-Ripping)
        self.art_map: dict[Path, bytes] = {}
        self.error_map: dict[Path, str] = {}              # Quelle -> Fehlertext (z. B. unsicherer Rip); löst "…on Error"-DSPs aus
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.RLock()
        self._taken: set[str] = set()                     # in diesem Lauf bereits vergebene Zieldateinamen

    # ------------------------------------------------------------------ API
    def cancel(self):
        self.cancel_event.set()
        with self._lock:
            for p in list(self._procs):
                try:
                    p.kill()
                except OSError:
                    pass

    def run(self, files: list[Path]) -> list[Result]:
        results = [Result(Path(f)) for f in files]
        jobs: dict[int, Job] = {}
        with ThreadPoolExecutor(max_workers=max(1, self.s.workers)) as pool:
            futs = [pool.submit(self._one, i, Path(f), results, jobs) for i, f in enumerate(files)]
            for f in futs:
                f.result()
        # Batch-Hooks (Playlist, Album-ReplayGain, Run External nach Batch, Sound)
        ordered = [jobs[i] for i in sorted(jobs)]
        for step in self.s.dsp:
            d = REGISTRY.get(step.name)
            if d:
                try:
                    d.finish_batch(ordered, {**d.defaults(), **step.settings})
                except Exception as e:  # Nach-Aktion darf Ergebnis nicht kippen
                    for r in results:
                        r.message = r.message or f"{step.name}: {e}"
        return results

    # ---------------------------------------------------------------- intern
    def _one(self, idx: int, src: Path, results: list[Result], jobs: dict[int, Job]):
        res = results[idx]
        if self.cancel_event.is_set():
            res.status = "cancelled"
            self.on_result(idx, res)
            return
        enc = ENCODERS[self.s.encoder]
        try:
            info = read_info(src)
            if not info.length:
                pr = analysis.probe(src).get("format", {})
                info.length = float(pr.get("duration", 0) or 0)
            tags = self.tags_map.get(src) or (read_tags(src) if self.s.copy_tags else {})
            job = Job(src=src, dst=Path(), info=info, tags=tags)
            with self._lock:                              # parallele Worker dürfen nie denselben Zielnamen wählen
                job.dst = destination(src, tags, enc, info, self.s.output, self._taken)
            job.extra["natural_dst"] = destination(src, tags, enc, info, replace(self.s.output, overwrite=True))
            res.dst = job.dst
            jobs[idx] = job
            for step in self.s.dsp:
                d = REGISTRY.get(step.name)
                if d is None:
                    raise KeyError(tr("Unbekannter DSP-Effekt: {0}").format(step.name))
                d.prepare(job, {**d.defaults(), **step.settings})
                if job.skip:
                    break
            if job.tag_override is not None and self.s.output.mode == "dynamic":
                with self._lock:
                    self._taken.discard(str(job.dst).lower())
                    job.dst = destination(src, job.tag_override, enc, info, self.s.output, self._taken)
                job.extra["natural_dst"] = destination(src, job.tag_override, enc, info, replace(self.s.output, overwrite=True))
                res.dst = job.dst
            if job.skip:
                res.status, res.message = "skipped", job.skip
            elif job.copy_only:
                job.dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, job.dst.with_suffix(src.suffix))
                res.status, res.message = "ok", tr("1:1 kopiert")
            else:
                self._encode(idx, job, enc, res)
            if src in self.error_map:
                job.errors.append(self.error_map[src])
            if res.status != "skipped":                   # übersprungene Dateien lösen keine "on Error"-Aktionen aus
                for hook in job.post:
                    hook(job, res.status == "ok")
            if job.errors and res.status == "ok":
                res.status, res.message = "error", "; ".join(job.errors)
        except Exception as e:
            res.status, res.message = "error", str(e)
            job = jobs.get(idx)
            if job:
                job.errors.append(str(e))
                for hook in job.post:
                    try:
                        hook(job, False)
                    except Exception:
                        pass
        self.on_progress(idx, 1.0)
        self.on_result(idx, res)

    def _lower_priority(self, proc: subprocess.Popen) -> None:
        """Linux/macOS: niedrige Priorität per nice (Windows nutzt BELOW_NORMAL_PRIORITY_CLASS beim Start)."""
        if self.s.low_priority and os.name != "nt":
            try:
                os.setpriority(os.PRIO_PROCESS, proc.pid, 10)
            except OSError:
                pass

    def _encode(self, idx: int, job: Job, enc: Encoder, res: Result):
        job.dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = job.dst.with_name(job.dst.stem + ".psyrip-tmp" + job.dst.suffix)
        cmd = [analysis.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", *build_command(job, enc, self.s.enc_settings, tmp)]
        flags = analysis.NO_WINDOW | (0x00004000 if self.s.low_priority and os.name == "nt" else 0)
        tool_cmd = enc.external_command({**self.s.enc_settings}, str(tmp)) if enc.external else None
        procs: list[subprocess.Popen] = []
        err_buf: list[str] = []
        t0, total = time.monotonic(), max(job.length, 0.001)

        def on_line(raw: bytes):
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("out_time_us="):
                try:
                    done = int(line.split("=")[1]) / 1e6
                except ValueError:
                    return
                self.on_progress(idx, min(done / total, 0.99))
                if job.throttle:
                    wait = done / job.throttle - (time.monotonic() - t0)
                    if wait > 0:
                        time.sleep(wait)
            elif line and "=" not in line.split(" ")[0]:
                err_buf.append(line)

        def pump(stream):
            for raw in stream:
                on_line(raw)

        ff = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        procs.append(ff)
        self._lower_priority(ff)
        threads = []
        if tool_cmd:
            tool = subprocess.Popen(tool_cmd, stdin=ff.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
            ff.stdout.close()
            procs.append(tool)
            self._lower_priority(tool)
            threads = [threading.Thread(target=pump, args=(ff.stderr,), daemon=True),
                       threading.Thread(target=lambda: err_buf.extend(l.decode("utf-8", "replace").strip() for l in tool.stderr if l.strip()), daemon=True)]
        else:
            threads = [threading.Thread(target=pump, args=(ff.stdout,), daemon=True),
                       threading.Thread(target=lambda: err_buf.extend(l.decode("utf-8", "replace").strip() for l in ff.stderr if l.strip()), daemon=True)]
        with self._lock:
            self._procs.update(procs)
        for th in threads:
            th.start()
        try:
            for p in procs:
                p.wait()
        finally:
            with self._lock:
                self._procs.difference_update(procs)
        for th in threads:
            th.join(timeout=2)
        if self.cancel_event.is_set():
            tmp.unlink(missing_ok=True)
            res.status = "cancelled"
            return
        if any(p.returncode != 0 for p in procs) or not tmp.exists():
            tmp.unlink(missing_ok=True)
            raise RuntimeError(("\n".join(err_buf) or tr("Encoder-Fehler")).strip()[-500:])
        os.replace(tmp, job.dst)
        tags = job.tag_override if job.tag_override is not None else job.tags
        if tags:
            try:
                write_tags(job.dst, tags)
            except Exception as e:
                job.errors.append(f"Tags: {e}")
        if self.s.copy_art and enc.supports_art:
            art = self.art_map.get(job.src) or read_art(job.src)
            if art:
                try:
                    write_art(job.dst, art)
                except Exception as e:
                    job.errors.append(f"Cover: {e}")
        if self.s.verify and enc.lossless and not job.filters and not job.rate and not job.channels:
            if analysis.audio_hash(job.src) != analysis.audio_hash(job.dst):
                job.errors.append(tr("Verifikation fehlgeschlagen (Audio weicht von der Quelle ab)"))
        res.status = "ok"
