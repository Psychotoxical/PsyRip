"""Einstiegspunkt:  python -m psyrip [center|convert|batch|rip|tags|utilities] [Dateien…]
                   python -m psyrip cli -infile X -outfile Y -convert_to FLAC [-dsp "Name:{json}"]"""
from __future__ import annotations

from .i18n import tr
import argparse
import json
import sys
from pathlib import Path


def run_cli(argv: list[str]) -> int:
    from . import settings as cfgmod
    from .converter import ConvertSettings, Converter, DspStep, OutputSpec
    from .encoders import ENCODERS
    from . import analysis
    p = argparse.ArgumentParser(prog="psyrip cli", description=tr("Kommandozeilen-Konvertierung (analog zu CoreConverter)."))
    p.add_argument("-infile", required=True)
    p.add_argument("-outfile", required=True)
    p.add_argument("-convert_to", required=True, choices=list(ENCODERS))
    p.add_argument("-set", action="append", default=[], metavar="KEY=VALUE", help=tr("Encoder-Option, z. B. -set level=8"))
    p.add_argument("-dsp", action="append", default=[], metavar='"Name:{json}"', help=tr("DSP-Effekt, z. B. -dsp \"Resample:{\\\"rate\\\":44100}\""))
    p.add_argument("-overwrite", action="store_true")
    a = p.parse_args(argv)
    cfg = cfgmod.load()
    if cfg["ffmpeg"]:
        analysis.set_ffmpeg(cfg["ffmpeg"])
    from . import encoders
    encoders.TOOL_PATHS.update({k: v for k, v in cfg["tools"].items() if v})
    out = Path(a.outfile)
    steps = []
    for d in a.dsp:
        name, _, js = d.partition(":")
        steps.append(DspStep(name, json.loads(js) if js else {}))
    s = ConvertSettings(encoder=a.convert_to, enc_settings=dict(kv.split("=", 1) for kv in a.set), dsp=steps, workers=1,
                        output=OutputSpec("folder", str(out.parent), overwrite=True))
    res = Converter(s).run([Path(a.infile)])[0]
    if res.status == "ok" and res.dst != out:
        out.parent.mkdir(parents=True, exist_ok=True)
        res.dst.replace(out)
    print(res.status, res.message)
    return 0 if res.status in ("ok", "skipped") else 1


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "cli":
        return run_cli(argv[1:])
    from PySide6.QtWidgets import QApplication
    from . import analysis
    from . import settings as cfgmod
    from .gui import theme
    cmd = argv[0] if argv and argv[0] in ("center", "convert", "batch", "rip", "tags", "utilities") else "center"
    files = [Path(a) for a in (argv[1:] if argv and argv[0] == cmd else argv) if Path(a).exists()]
    app = QApplication(sys.argv)
    from .i18n import install_qt_translator
    install_qt_translator(app)
    from .gui.theme import app_icon, set_app_id
    set_app_id()
    app.setWindowIcon(app_icon())
    cfg = cfgmod.load()
    if cfg["ffmpeg"]:
        analysis.set_ffmpeg(cfg["ffmpeg"])
    from . import encoders
    encoders.TOOL_PATHS.update({k: v for k, v in cfg["tools"].items() if v})
    theme.apply(app, cfg["theme"])
    if cmd == "convert":
        from .gui.converter_win import ConverterWindow
        win = ConverterWindow(files, cfg)
    elif cmd == "batch":
        from .gui.batch_win import BatchWindow
        win = BatchWindow(cfg)
    elif cmd == "rip":
        from .gui.cdripper_win import CDRipperWindow
        win = CDRipperWindow(cfg)
    elif cmd == "utilities":
        from .gui.utilities_win import UtilitiesWindow
        win = UtilitiesWindow(files, cfg)
    elif cmd == "tags":
        from .gui.tag_editor import TagEditor
        win = TagEditor(files, cfg)
    else:
        from .gui.control_center import ControlCenter
        win = ControlCenter()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
