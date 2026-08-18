from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Store
from app.prospect_models import ProspectArchive
from app.rewe_audit_runtime import REWE_CONSENT_MARKERS, _has_archived_prospect, _validity_from_result


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

    assert _has_archived_prospect(db, store) is False

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
        pdf_bytes=b"%PDF-test",
    )
    db.add(archive)
    db.commit()

    assert _has_archived_prospect(db, store) is True
