"""Rendert alle Fenster offscreen als PNG (Smoke-Test für die GUI)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtWidgets import QApplication  # noqa: E402

from psyrip import settings as cfgmod  # noqa: E402
from psyrip.gui import theme  # noqa: E402
from psyrip.gui.batch_win import BatchWindow  # noqa: E402
from psyrip.gui.cdripper_win import CDRipperWindow  # noqa: E402
from psyrip.gui.control_center import ControlCenter  # noqa: E402
from psyrip.gui.converter_win import ConverterWindow  # noqa: E402
from psyrip.gui.tag_editor import TagEditor  # noqa: E402
from psyrip.gui.utilities_win import UtilitiesWindow  # noqa: E402

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("shots")
out.mkdir(exist_ok=True, parents=True)
files = [Path(p) for p in sys.argv[2:]]
app = QApplication([])
cfg = cfgmod.load()
theme.apply(app, os.environ.get("PSYRIP_THEME", "light"))
wins = {"center": ControlCenter(), "converter": ConverterWindow(files, cfg), "batch": BatchWindow(cfg),
        "ripper": CDRipperWindow(cfg), "utilities": UtilitiesWindow(files, cfg)}
if files:
    wins["tags"] = TagEditor(files, cfg)
for n, w in wins.items():
    w.show()
    app.processEvents()
    w.grab().save(str(out / f"{n}.png"))
    print("ok", n)
