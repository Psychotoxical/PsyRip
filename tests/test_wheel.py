import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QScrollArea, QSpinBox, QVBoxLayout, QWidget

from psyrip.gui import theme


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply(a, "light")
    return a


def wheel(widget, delta=-120):
    ev = QWheelEvent(QPointF(5, 5), widget.mapToGlobal(QPointF(5, 5)), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)
    return ev


def test_wheel_does_not_change_unfocused_fields_but_scrolls_page(app):
    page = QWidget()
    lay = QVBoxLayout(page)
    combo, spin, dspin = QComboBox(), QSpinBox(), QDoubleSpinBox()
    combo.addItems(["a", "b", "c"])
    spin.setRange(0, 100)
    spin.setValue(10)
    dspin.setValue(1.5)
    for w in (combo, spin, dspin):
        lay.addWidget(w)
    filler = QWidget()
    filler.setMinimumHeight(2000)
    lay.addWidget(filler)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(page)
    area.resize(300, 200)
    area.show()
    app.processEvents()
    for w in (combo, spin, dspin, spin.lineEdit()):
        w.clearFocus()                                                  # das erste Feld erhält sonst beim Anzeigen automatisch den Fokus
    area.setFocus()
    for w in (combo, spin, dspin, spin.lineEdit()):
        wheel(w)
    assert combo.currentIndex() == 0 and spin.value() == 10 and dspin.value() == 1.5
    assert area.verticalScrollBar().value() > 0                         # die Seite wurde stattdessen gescrollt
    assert combo.focusPolicy() == Qt.StrongFocus and spin.focusPolicy() == Qt.StrongFocus


def test_wheel_changes_value_when_field_has_focus(app):
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setValue(10)
    spin.show()
    spin.setFocus()
    app.processEvents()
    if not spin.hasFocus():
        pytest.skip("Fokus im Offscreen-Modus nicht verfügbar")
    wheel(spin, 120)
    assert spin.value() == 11
