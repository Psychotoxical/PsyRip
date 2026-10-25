"""Zeichnet das psyrip-Symbol (Disc mit Klangwellen auf blauem Verlauf) und schreibt PNG + mehrgrößige ICO.

Aufruf:  python tools/make_icon.py        ->  psyrip/assets/psyrip.png, psyrip/assets/psyrip.ico
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,  # noqa: E402
                           QRadialGradient)

S = 1024


def draw() -> QImage:
    img = QImage(S, S, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)

    # Hintergrund: abgerundetes Quadrat mit Verlauf
    bg = QLinearGradient(0, 0, S, S)
    bg.setColorAt(0.0, QColor("#6f9bff"))
    bg.setColorAt(1.0, QColor("#2350d8"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(bg))
    p.drawRoundedRect(QRectF(24, 24, S - 48, S - 48), 230, 230)
    gloss = QLinearGradient(0, 0, 0, S * 0.55)
    gloss.setColorAt(0.0, QColor(255, 255, 255, 70))
    gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(gloss))
    p.drawRoundedRect(QRectF(24, 24, S - 48, S * 0.55), 230, 230)

    # Disc
    c = QPointF(S * 0.37, S * 0.5)
    r = S * 0.265
    disc = QConicalGradient(c, 30)
    for stop, col in ((0.0, "#ffffff"), (0.25, "#dfe8ff"), (0.5, "#ffffff"), (0.75, "#cfdcff"), (1.0, "#ffffff")):
        disc.setColorAt(stop, QColor(col))
    p.setBrush(QBrush(disc))
    p.drawEllipse(c, r, r)
    p.setBrush(QColor(47, 109, 246, 60))                      # innerer Ring (Spur)
    p.drawEllipse(c, r * 0.62, r * 0.62)
    p.setBrush(QBrush(disc))
    p.drawEllipse(c, r * 0.56, r * 0.56)
    hole = QRadialGradient(c, r * 0.2)
    hole.setColorAt(0.0, QColor("#2a56d9"))
    hole.setColorAt(1.0, QColor("#2350d8"))
    p.setBrush(QBrush(hole))
    p.drawEllipse(c, r * 0.17, r * 0.17)

    # Klangwellen rechts der Disc
    pen = QPen(QColor("#ffffff"), S * 0.055, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    for i, k in enumerate((1.28, 1.62, 1.96)):          # konzentrisch um die Disc, mit Abstand zum Rand
        path = QPainterPath()
        rr = r * k
        rect = QRectF(c.x() - rr, c.y() - rr, 2 * rr, 2 * rr)
        path.arcMoveTo(rect, 38)
        path.arcTo(rect, 38, -76)
        pen.setColor(QColor(255, 255, 255, 255 - i * 55))
        p.setPen(pen)
        p.drawPath(path)
    p.end()
    return img


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841
    out = Path(__file__).resolve().parent.parent / "psyrip" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    big = draw()
    big.scaled(256, 256, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).save(str(out / "psyrip.png"))
    from PIL import Image
    im = Image.open(out / "psyrip.png").convert("RGBA")
    big.save(str(out / "_big.png"))
    src = Image.open(out / "_big.png").convert("RGBA")
    src.save(out / "psyrip.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    (out / "_big.png").unlink()
    print("geschrieben:", out / "psyrip.png", out / "psyrip.ico", im.size)


if __name__ == "__main__":
    main()
