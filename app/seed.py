from __future__ import annotations

from .models import Store

STORES = [
    ("REWE", "REWE:XL Hundertmark", "56269", "Dierdorf", "Königsberger Str. 20-22", 50.5474, 7.6506, True, "321019"),
    ("REWE", "REWE Dennis Weirich", "56587", "Straßenhaus", "Kirschbüchel 2", 50.5407, 7.5187, False, "1940425"),
    ("Netto Marken-Discount", "Netto Dierdorf", "56269", "Dierdorf", "Königsberger Str. 24", 50.5472, 7.6510, True, None),
    ("Netto Marken-Discount", "Netto Oberhonnefeld-Gierend", "56587", "Oberhonnefeld-Gierend", "Über dem Stellweg 25", 50.5565, 7.5154, True, None),
    ("ALDI SÜD", "ALDI SÜD Dierdorf", "56269", "Dierdorf", "Königsberger Str. 50", 50.5490, 7.6558, True, None),
    ("ALDI SÜD", "ALDI SÜD Oberhonnefeld-Gierend", "56587", "Oberhonnefeld-Gierend", "Über dem Stellweg 5", 50.5550, 7.5200, True, None),
    ("EDEKA", "EDEKA Fellenzer", "56305", "Puderbach", "Urbacher Str. 35", 50.6000, 7.6110, False, "071378"),
    ("Lidl", "Lidl Puderbach", "56305", "Puderbach", "Urbacher Straße L264", 50.5980, 7.6150, False, None),
]


def seed_stores(db):
    for retailer, name, pc, city, address, lat, lon, verified, external_id in STORES:
        store = db.query(Store).filter(Store.name == name).first()
        if not store:
            store = Store(retailer=retailer, name=name, postal_code=pc, city=city, address=address)
            db.add(store)
        store.latitude = lat
        store.longitude = lon
        store.benchmark_verified = verified
        store.external_id = external_id
    db.commit()
