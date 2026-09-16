from __future__ import annotations

from .models import Store

STORES = [
    ("REWE", "REWE:XL Hundertmark", "56269", "Dierdorf", "Königsberger Str. 20-22", 50.5474, 7.6506, True, "321019"),
    ("REWE", "REWE Dennis Weirich", "56587", "Straßenhaus", "Kirschbüchel 2", 50.5407, 7.5187, False, "1940425"),
    ("Netto Marken-Discount", "Netto Dierdorf", "56269", "Dierdorf", "Königsberger Str. 24", 50.5472, 7.6510, True, "6822"),
    ("Netto Marken-Discount", "Netto Oberhonnefeld-Gierend", "56587", "Oberhonnefeld-Gierend", "Über dem Stellweg 25", 50.5565, 7.5154, True, "2648"),
    ("ALDI SÜD", "ALDI SÜD Dierdorf", "56269", "Dierdorf", "Königsberger Str. 50", 50.5490, 7.6558, True, None),
    ("ALDI SÜD", "ALDI SÜD Oberhonnefeld-Gierend", "56587", "Oberhonnefeld-Gierend", "Über dem Stellweg 5", 50.5550, 7.5200, True, None),
    ("EDEKA", "EDEKA Fellenzer", "56305", "Puderbach", "Urbacher Str. 35", 50.6000, 7.6110, False, "071378"),
    (
        "Lidl",
        "Lidl Puderbach",
        "56305",
        "Puderbach",
        "Urbacherstraße L264",
        50.592225,
        7.608542,
        False,
        "lidl-puderbach-urbacherstr-l264",
    ),
]


def seed_stores(db):
    """Seed bootstrap stores without mutating established market identity.

    Static seed data is only authoritative when a store is first created. Once
    a store exists, operator/discovery workflows own its physical identity,
    including coordinates and external retailer IDs. Startup must therefore not
    overwrite those fields from this bootstrap list.

    Existing stores may still need one narrow compatibility repair for an old
    publication-state bug. ``published_at`` is durable proof that publication
    happened explicitly; only that lifecycle projection is repaired here.
    Manually suspended or inactive markets are never re-enabled.
    """
    # Local import avoids making the lightweight seed module responsible for
    # market-activation model registration during module import.
    from .market_activation import activation_state

    for retailer, name, pc, city, address, lat, lon, verified, external_id in STORES:
        store = db.query(Store).filter(Store.name == name).first()
        created = store is None
        if created:
            store = Store(
                retailer=retailer,
                name=name,
                postal_code=pc,
                city=city,
                address=address,
                latitude=lat,
                longitude=lon,
                external_id=external_id,
                benchmark_verified=verified,
            )
            db.add(store)
            db.flush()

        if not created:
            state = activation_state(db, store.id)
            was_explicitly_published = bool(
                state is not None
                and state.published_at is not None
                and not state.manually_suspended
                and store.active
            )
            if was_explicitly_published:
                store.benchmark_verified = True
                # A prior restart could have corrupted only the lifecycle/flag
                # projection while leaving the publication audit timestamp.
                # Restore the projection from that durable publication proof.
                state.lifecycle_status = "public"
                state.suspension_reason = None
                state.suspended_at = None

    db.commit()
