"""Utility-Codecs: Audio Info, Calculate Audio CRC, Arrange Audio, Tag From Filename,
Length Split, Channel Split, Multi-Encoder, ID Tag Update."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import analysis, tagproc
from .converter import ConvertSettings, Converter, _relative, naming_context
from .dsp import Job
from .encoders import ENCODERS
from .naming import render
from .tags import read_art, read_info, read_tags, write_art, write_tags


# ------------------------------------------------------------------ Audio Info
def audio_info(files: list[Path], extensive: bool = True, table: bool = False) -> str:
    rows: list[dict[str, str]] = []
    for f in files:
        i, t = read_info(f), read_tags(f)
        row = {"File": str(f), "Codec": i.codec, "Length": f"{i.length:.2f}", "Bitrate kbps": str(i.bitrate // 1000),
               "Sample rate": str(i.sample_rate), "Channels": str(i.channels), "Bits": str(i.bits), "Size": str(f.stat().st_size)}
        row.update({k.title(): v for k, v in t.items()})
        if extensive:
            fmt = analysis.probe(f).get("format", {})
            row["Format"] = str(fmt.get("format_long_name", ""))
        rows.append(row)
    if table:
        cols = list(dict.fromkeys(k for r in rows for k in r))
        return "\n".join(["\t".join(cols)] + ["\t".join(r.get(c, "") for c in cols) for r in rows])
    return "\n\n".join("\n".join(f"{k}: {v}" for k, v in r.items()) for r in rows)


# ------------------------------------------------------------------ Audio CRC
def audio_crc(files: list[Path], algos=("crc32", "md5")) -> dict[str, dict[str, str]]:
    return {str(f): {a: analysis.audio_hash(f, a) for a in algos} for f in files}


# ---------------------------------------------------------------- Arrange Audio
_ART_NAMES = ["folder.jpg", "cover.jpg", "coverart.jpg", "album.jpg", "artwork.jpg"]


def arrange_audio(files: list[Path], root: Path, arrangement: str, overwrite: bool = False,
                  arrange_art: bool = True, remove_empty: bool = True, dry_run: bool = False) -> list[tuple[Path, Path]]:
    class _E:  # Minimaler Encoder-Ersatz für den Naming-Kontext
        name, lossless = "", False
    moves: list[tuple[Path, Path]] = []
    for f in files:
        info, tags = read_info(f), read_tags(f)
        rel = render(arrangement, naming_context(tags, f, _E, info))
        dst = root / _relative(rel + f.suffix)
        if dst == f:
            continue
        if dst.exists() and not overwrite:
            continue
        moves.append((f, dst))
        if dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dst))
        if arrange_art:
            for n in [*_ART_NAMES, f.stem + ".jpg"]:
                a = f.parent / n
                if a.exists() and not (dst.parent / n).exists():
                    shutil.copy2(a, dst.parent / n)
        if remove_empty:
            p = f.parent
            while p.exists() and not any(p.iterdir()) and p != root and p.parent != p:
                p.rmdir()
                p = p.parent
    return moves


# --------------------------------------------------------------- Tag From Filename
def pattern_to_regex(pattern: str) -> re.Pattern:
    pattern = pattern.replace("[[", "\x00").replace("]]", "\x01")
    out, seen, pos = "", set(), 0
    for m in re.finditer(r"\[([^\]]+)\]", pattern):
        out += re.escape(pattern[pos:m.start()]).replace("\\\x00", "\x00")
        name = re.sub(r"\W", "_", m.group(1).lower())
        out += f"(?P={name})" if name in seen else f"(?P<{name}>[^\\\\]+?)"
        seen.add(name)
        pos = m.end()
    out += re.escape(pattern[pos:])
    out = out.replace("\x00", r"\[").replace("\x01", r"\]").replace("\\\\", r"\\")
    return re.compile(out + r"$", re.I)


def tag_from_filename(path: Path, pattern: str, drop_existing: bool = False, write: bool = True) -> dict[str, str]:
    full = str(path.with_suffix("")).replace("/", "\\")
    m = pattern_to_regex(pattern.replace("/", "\\")).search(full)
    if not m:
        return {}
    keys = {"track": "tracknumber", "album artist": "albumartist", "albumartist": "albumartist", "disc": "discnumber", "year": "date"}
    found = {keys.get(k.replace("_", " "), k.replace("_", " ")): v.strip() for k, v in m.groupdict().items()}
    if write:
        if drop_existing:
            try:
                import mutagen
                f = mutagen.File(str(path))
                if f is not None and f.tags is not None:
                    f.delete()
            except Exception:
                pass
        write_tags(path, found)
    return found


# ------------------------------------------------------------------ ID Tag Update
def id_tag_update(files: list[Path], settings: dict) -> None:
    for f in files:
        t = tagproc.process(read_tags(f), settings)
        art = read_art(f)
        try:
            import mutagen
            m = mutagen.File(str(f))
            if m is not None and m.tags is not None:
                m.delete()
        except Exception:
            pass
        write_tags(f, t)
        if art:
            write_art(f, art)
        if any(settings.get(k) for k in ("max_art_px", "max_art_kb", "force_jpg", "export_art", "import_art")):
            from .tags import process_art
            process_art(f, int(settings.get("max_art_px", 0)), int(settings.get("max_art_kb", 0)), bool(settings.get("force_jpg")),
                        bool(settings.get("export_art")), bool(settings.get("import_art")))


# --------------------------------------------------------------- Length / Channel Split
def _encode_segment(src: Path, dst: Path, enc_name: str, enc_settings: dict, filters: list[str], tags: dict) -> None:
    from .converter import build_command
    enc = ENCODERS[enc_name]
    job = Job(src=src, dst=dst, info=read_info(src), tags=tags, filters=filters)
    tmp = dst.with_name(dst.stem + ".psyrip-tmp" + dst.suffix)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [analysis.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", *build_command(job, enc, enc_settings, tmp)]
    p = subprocess.run(cmd, capture_output=True, creationflags=analysis.NO_WINDOW)
    if p.returncode:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[-400:])
    tmp.replace(dst)
    if tags:
        write_tags(dst, tags)


def length_split(src: Path, out_dir: Path, every_s: float, go_back_s: float = 0.0,
                 encoder: str = "FLAC", enc_settings: dict | None = None) -> list[Path]:
    total = read_info(src).length
    tags, outs, i, start = read_tags(src), [], 1, 0.0
    ext = ENCODERS[encoder].ext
    while start < total - 0.05:
        s0 = max(start - (go_back_s if i > 1 else 0), 0)
        dur = (start + every_s) - s0
        dst = out_dir / f"{src.stem}-{i:03d}{ext}"
        _encode_segment(src, dst, encoder, enc_settings or {}, [f"atrim=start={s0:.3f}:duration={dur:.3f}", "asetpts=PTS-STARTPTS"], tags)
        outs.append(dst)
        start += every_s
        i += 1
    return outs


_CH_NAMES = {1: ["Center"], 2: ["Left", "Right"], 6: ["Left", "Right", "Center", "LFE", "Back Left", "Back Right"]}


def channel_split(src: Path, out_dir: Path, encoder: str = "FLAC", enc_settings: dict | None = None,
                  descriptive: bool = False) -> list[Path]:
    info = read_info(src)
    names = _CH_NAMES.get(info.channels, [])
    outs = []
    for c in range(info.channels):
        label = names[c] if descriptive and c < len(names) else f"Ch{c + 1}"
        dst = out_dir / f"{src.stem}_{label}{ENCODERS[encoder].ext}"
        _encode_segment(src, dst, encoder, enc_settings or {}, [f"pan=mono|c0=c{c}"], read_tags(src))
        outs.append(dst)
    return outs


# ------------------------------------------------------------------- Multi-Encoder
def multi_encode(files: list[Path], configs: list[ConvertSettings], on_progress=None) -> list[list]:
    """Kodiert dieselben Quellen mit mehreren Encoder-Konfigurationen."""
    out = []
    for cfg in configs:
        out.append(Converter(cfg, on_progress=on_progress).run(files))
    return out
