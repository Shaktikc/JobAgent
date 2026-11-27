"""Console-script entry point (Task 33).

Installs crash logging **before** importing :mod:`src.main`, so even an
import-time crash leaves a bundle under ``data/crash_logs/``. ``src.main:main``
keeps working for existing callers.
"""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    try:
        from src.tools.crash_logs import install_crash_logging, record_exception
    except Exception:  # noqa: BLE001 - crash logging is optional; run as before
        install_crash_logging = record_exception = None

    if install_crash_logging is not None:
        install_crash_logging()
    try:
        from src.main import main as app_main
    except Exception as exc:
        if record_exception is not None:
            record_exception(exc, kind="import_error", exit_code=1)
        raise
    return app_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
