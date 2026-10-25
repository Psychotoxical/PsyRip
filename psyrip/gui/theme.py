"""Modernes, flaches Design (Windows-11-Anmutung) mit hellem und dunklem Schema.

Die Stile liegen in einer QSS-Vorlage mit Farb-Token; Häkchen/Pfeile werden zur Laufzeit als PNG gezeichnet,
damit Checkboxen, Radiobuttons und Comboboxen auch ohne Bildressourcen modern aussehen.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QTableView,
                               QWidget)

LIGHT = dict(bg="#f4f5f7", surface="#ffffff", surface2="#f0f2f5", border="#dcdfe5", border_strong="#c3c8d1", text="#1b1f27",
             muted="#6a7280", accent="#2f6df6", accent_hover="#2559d1", accent_soft="#e6eeff", on_accent="#ffffff",
             sel="#2f6df6", sel_text="#ffffff", row_alt="#f1f4f9", grid="#e6e9ef", danger="#d33b3b", scroll="#c5cad3", scroll_hover="#a9afba")
DARK = dict(bg="#16181d", surface="#1f232b", surface2="#272c36", border="#323846", border_strong="#434b5c", text="#e8eaf0",
            muted="#9aa3b5", accent="#5b8cff", accent_hover="#7aa2ff", accent_soft="#26324f", on_accent="#0d1220",
            sel="#3a5bb8", sel_text="#ffffff", row_alt="#262c37", grid="#2d3340", danger="#ff6b6b", scroll="#3b4252", scroll_hover="#51596c")

_icon_dir = Path(tempfile.gettempdir()) / "psyrip_icons"


def _png(name: str, size: int, draw) -> str:
    _icon_dir.mkdir(exist_ok=True)
    path = _icon_dir / f"{name}.png"
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2, 2)
    draw(p, size)
    p.end()
    pm.save(str(path))
    return path.as_posix()


def _make_icons(c: dict) -> dict[str, str]:
    tag = c["bg"].strip("#")
    pen = lambda col, w: QPen(QColor(col), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)  # noqa: E731

    def check(p, s):
        p.setPen(pen("#ffffff", 2.0))
        p.drawPolyline([QPointF(s * .24, s * .54), QPointF(s * .43, s * .72), QPointF(s * .77, s * .30)])

    def dot(p, s):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(s / 2, s / 2), s * .2, s * .2)

    def down(p, s):
        p.setPen(pen(c["muted"], 1.6))
        p.drawPolyline([QPointF(s * .28, s * .4), QPointF(s * .5, s * .62), QPointF(s * .72, s * .4)])

    def up_(p, s):
        p.setPen(pen(c["muted"], 1.6))
        p.drawPolyline([QPointF(s * .28, s * .6), QPointF(s * .5, s * .38), QPointF(s * .72, s * .6)])

    import math

    def sun(p, s):
        col = QColor(c["muted"])
        p.setPen(pen(c["muted"], 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(s / 2, s / 2), s * .2, s * .2)
        for k in range(8):
            a = k * math.pi / 4
            p.drawLine(QPointF(s / 2 + math.cos(a) * s * .32, s / 2 + math.sin(a) * s * .32),
                       QPointF(s / 2 + math.cos(a) * s * .44, s / 2 + math.sin(a) * s * .44))
        del col

    def moon(p, s):
        from PySide6.QtGui import QPainterPath
        outer, inner = QPainterPath(), QPainterPath()
        outer.addEllipse(QPointF(s / 2, s / 2), s * .38, s * .38)
        inner.addEllipse(QPointF(s * .66, s * .38), s * .32, s * .32)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["muted"]))
        p.drawPath(outer.subtracted(inner))

    def half(p, s):
        from PySide6.QtCore import QRectF
        r = QRectF(s * .12, s * .12, s * .76, s * .76)
        p.setPen(pen(c["muted"], 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["muted"]))
        p.drawPie(r, 90 * 16, 180 * 16)                        # linke Hälfte gefüllt

    return {"check": _png(f"check_{tag}", 16, check), "dot": _png(f"dot_{tag}", 16, dot),
            "down": _png(f"down_{tag}", 16, down), "up": _png(f"up_{tag}", 16, up_),
            "mode_light": _png(f"sun_{tag}", 18, sun), "mode_dark": _png(f"moon_{tag}", 18, moon), "mode_auto": _png(f"half_{tag}", 18, half)}


_ICONS: dict[str, str] = {}


def mode_icon(mode: str):
    """Symbol (Sonne/Mond/Halbkreis) in der aktuellen Themenfarbe für den Umschalter."""
    from PySide6.QtGui import QIcon
    return QIcon(_ICONS.get(f"mode_{mode}", ""))


def build_qss(c: dict, icons: dict[str, str]) -> str:
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; color: {c['text']}; }}
QMainWindow, QDialog, QWidget#page {{ background: {c['bg']}; }}
QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border_strong']}; padding: 4px 6px; }}
QLabel {{ background: transparent; }}
QLabel#header {{ font-size: 20pt; font-weight: 600; padding: 2px 0 10px 0; }}
QLabel#sub {{ color: {c['muted']}; }}
QStatusBar {{ background: {c['surface']}; border-top: 1px solid {c['border']}; color: {c['muted']}; }}
QStatusBar QLabel {{ color: {c['muted']}; }}

QGroupBox {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; margin-top: 14px; padding: 12px 10px 10px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {c['muted']}; font-weight: 600; }}

QPushButton {{ background: {c['surface']}; border: 1px solid {c['border_strong']}; border-radius: 8px; padding: 6px 14px; min-height: 20px; }}
QPushButton:hover {{ background: {c['accent_soft']}; border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['border']}; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['surface2']}; border-color: {c['border']}; }}
QPushButton::menu-indicator {{ image: url({icons['down']}); width: 14px; subcontrol-position: right center; subcontrol-origin: padding; right: 6px; }}
QPushButton#primary {{ background: {c['accent']}; color: {c['on_accent']}; border: 1px solid {c['accent']}; font-weight: 600; padding: 8px 26px; }}
QPushButton#primary:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
QPushButton#primary:disabled {{ background: {c['border_strong']}; border-color: {c['border_strong']}; color: {c['surface']}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {c['surface']}; border: 1px solid {c['border_strong']}; border-radius: 8px; padding: 5px 8px;
    selection-background-color: {c['sel']}; selection-color: {c['sel_text']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {c['accent']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ background: {c['surface2']}; color: {c['muted']}; }}
QComboBox {{ padding-right: 28px; min-height: 20px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({icons['down']}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border_strong']}; border-radius: 8px; padding: 4px;
    selection-background-color: {c['accent_soft']}; selection-color: {c['text']}; outline: 0; }}
QSpinBox, QDoubleSpinBox {{ padding: 5px 26px 5px 10px; min-width: 76px; }}
/* Zell-Editor in Tabellen/Listen (Doppelklick): muss in die Zeilenhöhe passen – ohne den Innenabstand normaler Felder */
QAbstractItemView QLineEdit {{ border: 1px solid {c['accent']}; border-radius: 3px; padding: 0 5px; margin: 0; background: {c['surface']}; }}
QAbstractSpinBox QLineEdit {{ background: transparent; border: none; padding: 0; margin: 0; color: {c['text']}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: none;
    border-left: 1px solid {c['border']}; border-top-right-radius: 8px; background: transparent; margin-top: 1px; margin-right: 1px; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: none;
    border-left: 1px solid {c['border']}; border-bottom-right-radius: 8px; background: transparent; margin-bottom: 1px; margin-right: 1px; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {c['accent_soft']}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({icons['up']}); width: 12px; height: 12px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({icons['down']}); width: 12px; height: 12px; }}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 18px; height: 18px; border: 1.5px solid {c['border_strong']}; background: {c['surface']}; }}
QCheckBox::indicator {{ border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 10px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({icons['check']}); }}
QRadioButton::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({icons['dot']}); }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ background: {c['surface2']}; border-color: {c['border']}; }}

QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 10px; background: {c['surface']}; top: -1px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 8px 16px; margin-right: 2px; border: none; border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: {c['text']}; }}
QTabBar::tab:selected {{ color: {c['accent']}; border-bottom: 2px solid {c['accent']}; font-weight: 600; }}

QTableView, QTableWidget, QTreeView, QTreeWidget, QListView, QListWidget {{ background: {c['surface']}; alternate-background-color: {c['row_alt']};
    border: 1px solid {c['border']}; border-radius: 10px; gridline-color: transparent; outline: 0;
    selection-background-color: {c['accent_soft']}; selection-color: {c['text']}; }}
QTableView::item, QTreeView::item, QListView::item {{ padding: 5px 6px; border: none; border-bottom: 1px solid {c['grid']}; }}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{ border-bottom: 1px solid {c['accent_soft']}; }}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; }}
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover {{ background: {c['surface2']}; }}
QTableView QTableCornerButton::section {{ background: {c['surface']}; border: none; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {c['surface']}; color: {c['muted']}; border: none; border-bottom: 1px solid {c['border']};
    padding: 8px 8px; font-weight: 600; }}

QProgressBar {{ background: {c['surface2']}; border: none; border-radius: 8px; text-align: center; min-height: 16px; max-height: 16px; color: {c['text']}; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 8px; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle {{ background: {c['scroll']}; border-radius: 4px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {c['scroll_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}
QScrollArea {{ border: none; background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['border_strong']}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['accent_soft']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}

QGroupBox#plain {{ border: none; background: transparent; margin-top: 0; padding: 4px 2px; }}
QGroupBox#plain::title {{ height: 0; padding: 0; }}
QGroupBox#encoder {{ border: none; background: transparent; margin-top: 0; padding: 4px 2px; }}
QGroupBox#encoder::title {{ height: 0; padding: 0; }}
QLabel#artbox {{ background: {c['surface2']}; border: 1px dashed {c['border_strong']}; border-radius: 10px; color: {c['muted']}; }}
QFrame#card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 14px; }}
QFrame#card:hover {{ border-color: {c['accent']}; background: {c['accent_soft']}; }}
QLabel#cardIcon {{ font-family: "Segoe Fluent Icons", "Segoe MDL2 Assets"; font-size: 26pt; color: {c['accent']}; }}
QLabel#cardTitle {{ font-size: 13pt; font-weight: 600; }}
QLabel#cardText {{ color: {c['muted']}; }}
QWidget#side {{ background: {c['surface']}; border-right: 1px solid {c['border']}; }}
QPushButton#themeBtn {{ text-align: left; background: transparent; border: none; border-top: 1px solid {c['border']}; border-radius: 0;
    padding: 14px 20px; color: {c['muted']}; }}
QPushButton#themeBtn:hover {{ background: {c['surface2']}; color: {c['text']}; }}
QListWidget#nav {{ background: {c['surface']}; border: none; border-right: 1px solid {c['border']}; border-radius: 0; padding: 10px 6px; }}
QListWidget#nav::item {{ border: none; padding: 11px 14px; border-radius: 8px; margin: 2px 4px; color: {c['muted']}; }}
QListWidget#nav::item:selected {{ background: {c['accent_soft']}; color: {c['accent']}; font-weight: 600; }}
QListWidget#nav::item:hover {{ background: {c['surface2']}; }}
"""


class _SpinBoxFix(QObject):
    """QSS-Padding erreicht das innere Textfeld der SpinBox nicht zuverlässig: Textrand per Code setzen."""

    @staticmethod
    def _owner(obj):
        """Das Zahlen-/Auswahlfeld, zu dem das Widget gehört (die SpinBox besitzt ein inneres Textfeld)."""
        w = obj
        for _ in range(3):
            if isinstance(w, (QAbstractSpinBox, QComboBox)):
                return w
            w = w.parent() if hasattr(w, "parent") else None
            if w is None:
                break
        return None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and isinstance(obj, QWidget):
            owner = self._owner(obj)
            if owner is not None and not (owner.hasFocus() or (owner.lineEdit() is not None and owner.lineEdit().hasFocus())):
                # Mausrad über einem nicht fokussierten Feld: Wert nicht ändern, stattdessen die Seite weiterscrollen
                p = owner.parent()
                while p is not None and not isinstance(p, QAbstractScrollArea):
                    p = p.parent()
                if p is not None:
                    QApplication.sendEvent(p.viewport(), event)
                return True
        if event.type() == QEvent.Polish:
            if isinstance(obj, (QAbstractSpinBox, QComboBox)):
                obj.setFocusPolicy(Qt.StrongFocus)            # Fokus nur per Klick/Tab, nicht durchs Darüberfahren/Scrollen
            if isinstance(obj, QAbstractSpinBox):
                le = obj.lineEdit()
                if le is not None:
                    le.setTextMargins(8, 0, 0, 0)
            elif isinstance(obj, QAbstractItemView) and obj.objectName() != "nav":
                parent = obj.parent()
                popup = parent is not None and "ComboBox" in parent.metaObject().className()
                if not popup:
                    obj.setAlternatingRowColors(True)       # überall abwechselnde Zeilen
                    if isinstance(obj, QTableView):
                        obj.setShowGrid(False)
        return False


_spin_fix: _SpinBoxFix | None = None


def app_icon():
    """Anwendungssymbol (psyrip/assets/psyrip.ico bzw. .png); funktioniert auch in der PyInstaller-Variante."""
    from PySide6.QtGui import QIcon
    base = Path(__file__).resolve().parent.parent / "assets"
    ico = QIcon()
    for name in ("psyrip.ico", "psyrip.png"):
        if (base / name).exists():
            ico.addFile(str(base / name))
    return ico


def set_app_id() -> None:
    """Eigene AppUserModelID, damit die Taskleiste psyrip mit eigenem Symbol gruppiert (nicht unter python.exe)."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("psyrip.audio.toolkit")
    except Exception:
        pass


def is_dark_system() -> bool:
    """Windows-App-Farbmodus. Direkt aus der Registry gelesen: Qts colorScheme() ist direkt nach dem Start nicht immer verlässlich."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        pass
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


_mode = "auto"
_watching = False


def current_mode() -> str:
    return _mode


def _on_system_scheme_changed(*_):
    if _mode == "auto":                                   # nur im Automatik-Modus dem Windows-Wechsel folgen
        apply(QApplication.instance(), "auto")


def apply(app: QApplication, dark: bool | str = False) -> None:
    """dark: "auto" (folgt Windows, auch während des Betriebs), "light", "dark" oder True/False."""
    global _mode, _watching
    _mode = dark if isinstance(dark, str) else ("dark" if dark else "light")
    if not _watching:
        _watching = True
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(_on_system_scheme_changed)
        except Exception:
            pass
    if dark == "auto":
        dark = is_dark_system()
    elif isinstance(dark, str):
        dark = dark == "dark"
    c = DARK if dark else LIGHT
    app.setStyle("Fusion")
    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.WindowText, "text"), (QPalette.Base, "surface"), (QPalette.AlternateBase, "row_alt"),
                      (QPalette.Text, "text"), (QPalette.Button, "surface"), (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"),
                      (QPalette.HighlightedText, "on_accent"), (QPalette.ToolTipBase, "surface"), (QPalette.ToolTipText, "text"),
                      (QPalette.PlaceholderText, "muted")):
        pal.setColor(role, QColor(c[key]))
    app.setPalette(pal)
    fams = set(QFontDatabase.families())
    fam = "Segoe UI Variable Text" if "Segoe UI Variable Text" in fams else "Segoe UI"
    app.setFont(QFont(fam, 10))
    icons = _make_icons(c)
    _ICONS.clear()
    _ICONS.update(icons)
    app.setStyleSheet(build_qss(c, icons))
    global _spin_fix
    if _spin_fix is None:
        _spin_fix = _SpinBoxFix(app)
        app.installEventFilter(_spin_fix)
