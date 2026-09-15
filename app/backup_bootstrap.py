from __future__ import annotations

import sys

from .backup_service import BackupError, perform_pending_restore


def main() -> int:
    try:
        result = perform_pending_restore()
    except BackupError as exc:
        print(f"Spareno pending restore failed safely: {exc}", file=sys.stderr)
        return 0
    except Exception as exc:  # pragma: no cover - startup safety net
        print(f"Spareno pending restore failed unexpectedly: {exc}", file=sys.stderr)
        return 0

    if result:
        print(
            "Spareno pending restore processed: "
            f"status={result.get('status')} backup={result.get('backup_name')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
