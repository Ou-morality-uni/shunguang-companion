"""Allowlisted diagnostics: never log exception text, request bodies or URLs."""

import logging

logger = logging.getLogger('shunguang')


def setup_logging():
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def report_error(operation: str, error: Exception):
    status = getattr(error, 'status_code', None)
    # Exception messages, traceback locals and SDK response objects may contain secrets.
    logger.warning(
        'operation=%s error_type=%s status=%s',
        operation,
        type(error).__name__,
        status if isinstance(status, int) else None,
    )
