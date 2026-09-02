from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import settings
from .db import SessionLocal
from .scrape_health import scrape_health_rows, scrape_health_summary


ATTENTION_STATES = {"manual_required", "stale", "warning", "needs_test"}


def build_scrape_health_report(db) -> tuple[str, str, bool]:
    rows = scrape_health_rows(db, stale_after_hours=settings.stale_after_hours)
    summary = scrape_health_summary(db)
    attention = [row for row in rows if row.state in ATTENTION_STATES]
    subject_state = "Eingriff prüfen" if attention else "Alles in Ordnung"
    subject = f"Spareno Scrape-Status: {subject_state}"

    lines = [
        "Spareno – täglicher Scrape-Status",
        "",
        "Zusammenfassung:",
    ]
    for state in ("healthy", "warning", "stale", "manual_required", "needs_test", "waiting"):
        lines.append(f"- {state}: {summary.get(state, 0)}")

    lines.extend(["", "Märkte:"])
    for row in rows:
        latest = row.latest_run_at.isoformat(sep=" ", timespec="minutes") if row.latest_run_at else "noch kein Lauf"
        lines.append(
            f"- [{row.state}] {row.retailer} · {row.store_name} · letzter Lauf: {latest} · {row.action}"
        )

    if attention:
        lines.extend([
            "",
            "Mindestens ein aktiver/rolloutfähiger Markt benötigt Prüfung. "
            "Es wurde keine automatische Veröffentlichung und keine selbstständige Codeänderung vorgenommen.",
        ])
    else:
        lines.extend(["", "Alle aktuell überwachten rolloutfähigen Märkte sind innerhalb der definierten Health-Regeln unauffällig."])
    return subject, "\n".join(lines), bool(attention)


def _configured() -> bool:
    return bool(
        settings.scrape_health_email_enabled
        and settings.scrape_health_email_to
        and settings.smtp_host
        and settings.smtp_from
    )


def send_scrape_health_report() -> str:
    """Send the configured status mail without exposing credentials in logs."""
    if not _configured():
        return "disabled"

    db = SessionLocal()
    try:
        subject, body, attention = build_scrape_health_report(db)
    finally:
        db.close()

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = settings.scrape_health_email_to
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)
    return "sent_attention" if attention else "sent_healthy"
