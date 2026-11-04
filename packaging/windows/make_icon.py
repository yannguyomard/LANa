"""Fabrique LANa.ico (icône de LANa.exe) à partir de desktop/assets/logo.png : images PNG de 16 à 256 px.

Usage : python make_icon.py <logo.png> <sortie.ico>   (avec PySide6 disponible)
"""
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(image, size):
    scaled = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    scaled.save(buf, "PNG")
    buf.close()
    return bytes(data)


def main(src, out):
    QGuiApplication([])
    image = QImage(src)
    if image.isNull():
        sys.exit("Image illisible : %s" % src)
    images = [png_bytes(image, s) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for size, data in zip(SIZES, images):
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(out, "wb") as fh:
        fh.write(header + entries + b"".join(images))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
