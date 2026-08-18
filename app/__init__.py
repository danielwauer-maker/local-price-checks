"""Local Price Checks application package."""

# REWE can block a second browser navigation even though the collector's first
# browser session succeeded. Install the compatibility wrapper early so every
# caller of `collect_store_from_web` can archive that already captured session.
from .rewe_audit_runtime import install as _install_rewe_audit_runtime

_install_rewe_audit_runtime()
