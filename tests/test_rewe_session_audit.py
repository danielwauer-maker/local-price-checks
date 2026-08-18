from types import SimpleNamespace

import fitz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Store
from app.prospect_models import ProspectArchive
from app.rewe_audit_runtime import (
    REWE_CONSENT_MARKERS,
    _archive_contains_consent,
    _has_archived_prospect,
    _needs_session_archive,
    _validity_from_result,
)


def _pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    payload = doc.tobytes()
    doc.close()
    return payload


def _store(db):
    store = Store(
        name="REWE:XL Hundertmark",
        retailer="REWE",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        active=True,
        source_url="https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
        external_id="321019",
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def test_rewe_session_audit_uses_offer_validity():
    result = {
        "offers": [
            SimpleNamespace(valid_from="17.08.2026", valid_to="22.08.2026"),
            SimpleNamespace(valid_from="17.08.2026", valid_to="22.08.2026"),
        ]
    }
    valid_from, valid_to = _validity_from_result(result)
    assert valid_from.isoformat() == "2026-08-17"
    assert valid_to.isoformat() == "2026-08-22"


def test_rewe_session_audit_accepts_iso_dates():
    result = {"offers": [SimpleNamespace(valid_from="2026-08-17", valid_to="2026-08-22")]}
    valid_from, valid_to = _validity_from_result(result)
    assert valid_from.isoformat() == "2026-08-17"
    assert valid_to.isoformat() == "2026-08-22"


def test_rewe_current_cookie_banner_headline_is_a_cleanup_marker():
    assert "optionale cookies und technologien erlauben" in REWE_CONSENT_MARKERS
    assert "nur notwendige erlauben" in REWE_CONSENT_MARKERS


def test_rewe_session_fallback_checks_immutable_archive_not_current_pointer():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    store = _store(db)

    assert _has_archived_prospect(db, store) is False
    assert _needs_session_archive(db, store) is True

    archive = ProspectArchive(
        store_id=store.id,
        retailer="REWE",
        period_key="current",
        source_url=store.source_url,
        pdf_url="web-snapshot://captured-session/test",
        original_filename="test.pdf",
        local_path="/tmp/test.pdf",
        page_count=1,
        pdf_sha256="0" * 64,
        pdf_bytes=_pdf_bytes("REWE Angebote im Markt"),
    )
    db.add(archive)
    db.commit()

    assert _has_archived_prospect(db, store) is True
    assert _needs_session_archive(db, store) is False


def test_rewe_archive_with_cookie_banner_forces_fresh_session_snapshot():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    store = _store(db)

    archive = ProspectArchive(
        store_id=store.id,
        retailer="REWE",
        period_key="current",
        source_url=store.source_url,
        pdf_url="web-snapshot://captured-session/dirty",
        original_filename="dirty.pdf",
        local_path="/tmp/dirty.pdf",
        page_count=1,
        pdf_sha256="1" * 64,
        pdf_bytes=_pdf_bytes("Optionale Cookies und Technologien erlauben? Nur notwendige erlauben"),
    )
    db.add(archive)
    db.commit()
    db.refresh(archive)

    assert _archive_contains_consent(archive) is True
    assert _needs_session_archive(db, store) is True
