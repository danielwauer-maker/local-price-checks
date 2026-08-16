from io import BytesIO

from PIL import Image
import zxingcpp
from fastapi.testclient import TestClient

from app.barcode_image import decode_gtin_image
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import MasterProduct, ProductBarcode


def _ean_image(code="4006381333931") -> bytes:
    barcode = zxingcpp.create_barcode(code, zxingcpp.BarcodeFormat.EAN13)
    image = Image.fromarray(barcode.to_image(scale=5))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_decode_gtin_from_camera_image():
    assert decode_gtin_image(_ean_image()) == "4006381333931"


def test_camera_image_route_finds_linked_product():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    product = db.query(MasterProduct).filter_by(normalized_key="camera-ean-product").first()
    if not product:
        product = MasterProduct(name="Kamera EAN Produkt", normalized_key="camera-ean-product")
        db.add(product)
        db.flush()
    row = db.get(ProductBarcode, "4006381333931")
    if row:
        row.master_product_id = product.id
    else:
        db.add(ProductBarcode(barcode="4006381333931", master_product_id=product.id, source="test"))
    db.commit()
    db.close()

    client = TestClient(app)
    response = client.post(
        "/scanner/bild",
        files={"image": ("ean.png", _ean_image(), "image/png")},
    )
    assert response.status_code == 200
    assert "Kamera EAN Produkt" in response.text
