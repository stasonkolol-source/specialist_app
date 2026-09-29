"""Картинки для тестов media: фото с EXIF и GPS, заголовок PNG-бомбы."""

import io
import struct
import zlib

from PIL import ExifTags, Image

GPS: dict[int, object] = {
    ExifTags.GPS.GPSLatitudeRef: "N",
    ExifTags.GPS.GPSLatitude: (44.0, 49.0, 12.0),
    ExifTags.GPS.GPSLongitudeRef: "E",
    ExifTags.GPS.GPSLongitude: (20.0, 27.0, 36.0),
}


def exif(orientation: int = 1) -> Image.Exif:
    tags = Image.Exif()
    tags[ExifTags.Base.Make] = "Phone"
    tags[ExifTags.Base.Orientation] = orientation
    tags.get_ifd(ExifTags.IFD.GPSInfo).update(GPS)
    return tags


def photo(fmt: str, size: tuple[int, int] = (2000, 1500), **save: object) -> bytes:
    image = Image.new("RGB", size, (200, 120, 40))
    for x in range(0, size[0], 50):  # полосы: у варианта есть что сжимать
        image.paste((30, 60, 90), (x, 0, x + 10, size[1]))
    out = io.BytesIO()
    image.save(out, fmt, **save)
    return out.getvalue()


def png_header_only(width: int, height: int) -> bytes:
    """PNG с огромными размерами в IHDR и без данных: так выглядит decompression bomb."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")
