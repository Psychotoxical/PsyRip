"""Encoder-Registry: bildet jedes Format auf ffmpeg-Argumente ab; einige Formate laufen über externe CLI-Encoder."""
from __future__ import annotations

from .i18n import tr
from dataclasses import dataclass, field


@dataclass
class Option:
    key: str
    label: str
    kind: str                      # "choice" | "slider" | "check"
    choices: list[tuple[str, str]] = field(default_factory=list)  # (Anzeige, Wert)
    default: str = ""


@dataclass
class Encoder:
    name: str
    ext: str
    lossless: bool
    ffmpeg_codec: list[str]
    options: list[Option] = field(default_factory=list)
    container_args: list[str] = field(default_factory=list)
    supports_art: bool = True
    max_bits: int = 32
    builder: object = None         # callable(settings) -> list[str]
    external: tuple[str, str] | None = None   # (Programmname, CLI-Vorlage mit {out}); WAV kommt über stdin
    args_after: bool = False       # Builder-Argumente hinter die CLI-Vorlage setzen (SoX-Effekte)

    @property
    def tool(self) -> str | None:
        return find_tool(self.external[0]) if self.external else None

    @property
    def available(self) -> bool:
        return self.external is None or self.tool is not None

    def external_command(self, settings: dict[str, str], out: str) -> list[str]:
        import shlex
        exe = self.tool
        if not exe:
            raise FileNotFoundError(tr("Externes Tool '{0}' nicht gefunden – Pfad im Control Center unter „Externe Tools“ setzen oder das Programm in PATH legen.").format(self.external[0]))
        merged = {o.key: o.default for o in self.options}
        merged.update(settings or {})
        extra = [a for a in (self.builder(merged) if self.builder else [])]
        cli = shlex.split(self.external[1].replace("{out}", out), posix=False)
        cli = [c.strip('"') for c in cli]
        return [exe, *(cli + extra if self.args_after else extra + cli)]

    def args(self, settings: dict[str, str]) -> list[str]:
        merged = {o.key: o.default for o in self.options}
        merged.update(settings or {})
        extra = self.builder(merged) if self.builder else []
        return [*self.ffmpeg_codec, *extra, *self.container_args]


def _mp3(s):
    mode = s["mode"]
    if mode == "vbr":
        return ["-q:a", s["vbr"]]
    if mode == "abr":
        return ["-abr", "1", "-b:a", f"{s['bitrate']}k"]
    return ["-b:a", f"{s['bitrate']}k"]


def _aac(s):
    if s["mode"] == "vbr":
        return ["-vbr", s["vbr"]]
    return ["-b:a", f"{s['bitrate']}k"]


def _opus(s):
    return ["-b:a", f"{s['bitrate']}k", "-vbr", "on" if s["mode"] == "vbr" else "off"]


def _vorbis(s):
    return ["-q:a", s["quality"]]


def _flac(s):
    return ["-compression_level", s["level"]]


def _wav(s):
    return ["-c:a", f"pcm_s{s['bits']}le" if s["bits"] != "8" else "pcm_u8"]


def _aiff(s):
    return ["-c:a", f"pcm_s{s['bits']}be"]


def _wavpack(s):
    return ["-compression_level", s["level"]]


TOOL_PATHS: dict[str, str] = {}      # vom Control Center gesetzt: Programmname -> Pfad


def find_tool(name: str) -> str | None:
    import os
    import shutil
    from pathlib import Path
    p = TOOL_PATHS.get(name)
    if p and Path(p).exists():
        return p
    from .analysis import bundled_bin
    roots = [*bundled_bin(), Path(os.environ.get("APPDATA", ".")) / "psyrip" / "tools"]
    for r in roots:
        for cand in (r / name, r / f"{name}.exe"):
            if cand.exists():
                return str(cand)
    return shutil.which(name)


_BR = [(f"{b} kbps", str(b)) for b in (64, 96, 128, 160, 192, 224, 256, 320)]

ENCODERS: dict[str, Encoder] = {}


def _reg(e: Encoder):
    ENCODERS[e.name] = e


_reg(Encoder("mp3 (Lame)", ".mp3", False, ["-c:a", "libmp3lame"], [
    Option("mode", tr("Modus"), "choice", [("VBR", "vbr"), ("ABR", "abr"), ("CBR", "cbr")], "vbr"),
    Option("vbr", tr("VBR-Qualität (0 = best)"), "choice", [(f"V{i}", str(i)) for i in range(10)], "2"),
    Option("bitrate", "Bitrate", "choice", _BR, "192")], builder=_mp3, max_bits=16))
_reg(Encoder("FLAC", ".flac", True, ["-c:a", "flac"], [
    Option("level", tr("Kompression"), "choice", [(f"Level {i}", str(i)) for i in range(9)], "5")], builder=_flac))
_reg(Encoder("m4a AAC", ".m4a", False, ["-c:a", "aac"], [
    Option("mode", tr("Modus"), "choice", [("CBR", "cbr"), ("VBR", "vbr")], "cbr"),
    Option("vbr", tr("VBR-Qualität"), "choice", [(f"{i}", str(i)) for i in range(1, 6)], "4"),
    Option("bitrate", "Bitrate", "choice", _BR, "192")],
    container_args=["-movflags", "+faststart"], builder=_aac, max_bits=16))
_reg(Encoder("Apple Lossless", ".m4a", True, ["-c:a", "alac"], container_args=["-movflags", "+faststart"]))
_reg(Encoder("Opus", ".opus", False, ["-c:a", "libopus"], [
    Option("mode", tr("Modus"), "choice", [("VBR", "vbr"), ("CBR", "cbr")], "vbr"),
    Option("bitrate", "Bitrate", "choice", [(f"{b} kbps", str(b)) for b in (32, 64, 96, 128, 160, 192, 256)], "128")],
    builder=_opus, max_bits=16))
_reg(Encoder("Ogg Vorbis", ".ogg", False, ["-c:a", "libvorbis"], [
    Option("quality", tr("Qualität"), "choice", [(f"q{i}", str(i)) for i in range(0, 11)], "5")], builder=_vorbis, max_bits=16))
_reg(Encoder("Wave", ".wav", True, [], [
    Option("bits", tr("Bit-Tiefe"), "choice", [("16", "16"), ("24", "24"), ("32", "32"), ("8", "8")], "16")],
    builder=_wav))
_reg(Encoder("AIFF", ".aif", True, [], [
    Option("bits", tr("Bit-Tiefe"), "choice", [("16", "16"), ("24", "24"), ("32", "32")], "16")], builder=_aiff))
_reg(Encoder("WavPack", ".wv", True, ["-c:a", "wavpack"], [
    Option("level", tr("Kompression"), "choice", [(f"Level {i}", str(i)) for i in range(0, 4)], "1")], builder=_wavpack))
_reg(Encoder("Windows Media Audio", ".wma", False, ["-c:a", "wmav2"], [
    Option("bitrate", "Bitrate", "choice", _BR, "192")],
    builder=lambda s: ["-b:a", f"{s['bitrate']}k"], max_bits=16))
_reg(Encoder("Speex", ".spx", False, ["-c:a", "libspeex"], [
    Option("bitrate", "Bitrate", "choice", [(f"{b} kbps", str(b)) for b in (8, 16, 24, 32, 44)], "24")],
    builder=lambda s: ["-b:a", f"{s['bitrate']}k"], max_bits=16))

_reg(Encoder("m4b (Audio Book)", ".m4b", False, ["-c:a", "aac"], [
    Option("bitrate", "Bitrate", "choice", [(f"{b} kbps", str(b)) for b in (32, 48, 64, 96, 128)], "64")],
    container_args=["-movflags", "+faststart"], builder=lambda s: ["-b:a", f"{s['bitrate']}k"], max_bits=16))

# --- Encoder, die als externes Programm (WAV über stdin) laufen ----------
_reg(Encoder("m4a FDK (AAC)", ".m4a", False, [], [
    Option("mode", tr("Qualität / Bitrate"), "choice", [("VBR 3 (~96 kbps)", "-m 3"), ("VBR 4 (~144 kbps)", "-m 4"), ("VBR 5 (~224 kbps)", "-m 5"),
                                                    ("CBR 128 kbps", "-b 128000"), ("CBR 192 kbps", "-b 192000"), ("CBR 256 kbps", "-b 256000")], "-m 4"),
    Option("profile", tr("Profil"), "choice", [("LC AAC", "-p 2"), ("HE AAC", "-p 5"), ("HE v2 AAC", "-p 29")], "-p 2")],
    external=("fdkaac", '--ignorelength -S -o "{out}" -'), builder=lambda s: [*s["mode"].split(), *s["profile"].split()], max_bits=24))
_reg(Encoder("Musepack", ".mpc", False, [], [
    Option("profile", tr("Profil"), "choice", [("Radio (~130 kbps)", "--radio"), ("Standard (~180 kbps)", "--standard"), ("Extreme (~210 kbps)", "--xtreme"),
                                           ("Insane (~240 kbps)", "--insane"), ("Quality 10 (~350 kbps)", "--quality 10")], "--standard")],
    external=("mppenc", '--overwrite - "{out}"'), builder=lambda s: s["profile"].split(), max_bits=16))
_reg(Encoder("Monkeys Audio", ".ape", True, [], [
    Option("c", tr("Kompression"), "choice", [("Fast", "-c1000"), ("Normal", "-c2000"), ("High", "-c3000"), ("Extra High", "-c4000"), ("Insane", "-c5000")], "-c3000")],
    external=("mac", '- "{out}"'), builder=lambda s: [s["c"]], args_after=True, max_bits=24))
_reg(Encoder("DSD", ".dsf", True, [], [
    Option("mode", tr("Modus"), "choice", [("DSD64", "2822400"), ("DSD128", "5644800"), ("DSD256", "11289600"), ("DSD512", "22579200")], "2822400")],
    external=("sox", '-t wav - --no-glob -t dsf "{out}"'), builder=lambda s: ["rate", "-v", s["mode"], "sdm"], args_after=True, max_bits=24))

DECODER_EXTS =sorted({".mp3", ".flac", ".m4a", ".mp4", ".m4b", ".ogg", ".oga", ".opus", ".wav", ".aif", ".aiff",
                       ".wv", ".ape", ".wma", ".mpc", ".spx", ".dsf", ".dff", ".aac", ".mp2", ".mp1", ".caf"})
