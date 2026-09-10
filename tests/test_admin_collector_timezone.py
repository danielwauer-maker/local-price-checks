from pathlib import Path


def test_collector_timestamps_are_rendered_as_berlin_local_time():
    template = Path("app/templates/admin_collector.html").read_text(encoding="utf-8")

    assert "timeZone: 'Europe/Berlin'" in template
    assert template.count('class="local-time"') == 2
    assert template.count('.isoformat() }}Z') == 2
    assert "<td>{{ r.started_at }}</td>" not in template
