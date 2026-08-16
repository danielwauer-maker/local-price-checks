from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps
import zxingcpp

from .barcode import normalize_gtin, valid_gtin

MAX_IMAGE_BYTES = 8 * 1024 * 1024


class BarcodeImageError(ValueError):
    pass


def decode_gtin_image(data: bytes) -> str | None:
    if not data:
        raise BarcodeImageError("Leeres Bild.")
    if len(data) > MAX_IMAGE_BYTES:
        raise BarcodeImageError("Bild ist größer als 8 MB.")
    try:
        image = Image.open(BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image.thumbnail((2200, 2200))
        image = image.convert("RGB")
    except Exception as exc:
        raise BarcodeImageError("Bild konnte nicht gelesen werden.") from exc

    # read_barcodes is more tolerant than a single-code call when packaging
    # contains QR/DataMatrix alongside the retail EAN. We only accept a valid
    # GTIN after our own check-digit validation.
    try:
        results = zxingcpp.read_barcodes(image, try_rotate=True, try_downscale=True, try_invert=True)
    except Exception as exc:
        raise BarcodeImageError("Barcode-Erkennung ist fehlgeschlagen.") from exc

    for result in results:
        code = normalize_gtin(result.text or "")
        if valid_gtin(code):
            return code
    return None
