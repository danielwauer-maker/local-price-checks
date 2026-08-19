from app import admin_collector_routes, rewe_audit_runtime, scheduler, web_collector


def test_rewe_runtime_install_patches_all_collector_entrypoints():
    rewe_audit_runtime.install()

    wrapped = web_collector.collect_store_from_web
    assert getattr(wrapped, "_lpc_rewe_session_patch", False) is True
    assert admin_collector_routes.collect_store_from_web is wrapped
    assert scheduler.collect_store_from_web is wrapped


def test_rewe_runtime_install_is_idempotent():
    rewe_audit_runtime.install()
    first = web_collector.collect_store_from_web

    rewe_audit_runtime.install()
    second = web_collector.collect_store_from_web

    assert second is first
    assert admin_collector_routes.collect_store_from_web is first
    assert scheduler.collect_store_from_web is first
