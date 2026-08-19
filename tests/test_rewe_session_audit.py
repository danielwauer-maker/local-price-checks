from types import SimpleNamespace

import fitz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Store
from app.prospect_models import ProspectArchive
from app.rewe_audit_runtime import (
    REWE_CONSENT_MARKERS,
    SNAPSHOT_VERSION,
    _archive_contains_consent,
    _archive_is_current_layout,
    _has_archived_prospect,
    _inject_base_href,
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


def _archive(store, *, pdf_url: str, text: str, sha: str = "0" * 64):
    return ProspectArchive(
        store_id=store.id,
        retailer="REWE",
        period_key="current",
        source_url=store.source_url,
        pdf_url=pdf_url,
        original_filename="test.pdf",
        local_path="/tmp/test.pdf",
        page_count=1,
        pdf_sha256=sha,
        pdf_bytes=_pdf_bytes(text),
    )


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


def test_rewe_base_href_is_injected_for_relative_assets():
    source = "https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/"
    result = _inject_base_href("<html><head></head><body><img src='/media/a.jpg'></body></html>", source)
    assert f'<base href="{source}">' in result
    assert result.index("<base") < result.index("</head>")


def test_rewe_session_fallback_accepts_clean_current_layout_archive():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    store = _store(db)

    assert _has_archived_prospect(db, store) is False
    assert _needs_session_archive(db, store) is True

    archive = _archive(
        store,
        pdf_url=f"web-snapshot://captured-session/v{SNAPSHOT_VERSION}/1/2026-08-19",
        text="REWE Angebote im Markt",
    )
    db.add(archive)
    db.commit()
    db.refresh(archive)

    assert _has_archived_prospect(db, store) is True
    assert _archive_is_current_layout(archive) is True
    assert _needs_session_archive(db, store) is False


def test_rewe_clean_old_layout_forces_one_refresh():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    store = _store(db)

    archive = _archive(
        store,
        pdf_url="web-snapshot://captured-session/1/2026-08-19",
        text="REWE Angebote im Markt",
        sha="2" * 64,
    )
    db.add(archive)
    db.commit()
    db.refresh(archive)

    assert _archive_contains_consent(archive) is False
    assert _archive_is_current_layout(archive) is False
    assert _needs_session_archive(db, store) is True


def test_rewe_archive_with_cookie_banner_forces_fresh_session_snapshot():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    store = _store(db)

    archive = _archive(
        store,
        pdf_url=f"web-snapshot://captured-session/v{SNAPSHOT_VERSION}/1/dirty",
        text="Optionale Cookies und Technologien erlauben? Nur notwendige erlauben",
        sha="1" * 64,
    )
    db.add(archive)
    db.commit()
    db.refresh(archive)

    assert _archive_contains_consent(archive) is True
    assert _needs_session_archive(db, store) is True
