"""Settlement service alias."""

from src.services.adjustments import (  # noqa: F401
    document_text,
    get,
    get_by_receipt,
    get_for_run,
    handover,
    list_entries,
)


def settle(db, run_id, data, actor, idempotency_key=None):
    return handover(db, run_id, data, actor, idempotency_key=idempotency_key)
