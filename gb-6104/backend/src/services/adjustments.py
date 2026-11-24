import json
from time import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from src.constants.job_state import JobState
from src.domain.handover import plan_handover, review_date
from src.models.adjustments import adjustment_bills, adjustment_items, voyage_handover_states
from src.models.runs import runs
from src.schemas.adjustments import AdjustmentBillEntry
from src.services import audit, reviews, runs as run_service
from src.utils.serial import canonical_json, content_digest


def _serialize_bill(row, items=None):
    if row is None:
        return None
    bill = dict(row)
    raw_document = bill.get("document")
    document = json.loads(raw_document) if isinstance(raw_document, str) else (raw_document or {})
    bill["document"] = document
    bill["items"] = [dict(item) for item in (items or [])]
    # Spread the Chinese business document so API and downloaded original bills
    # expose the same top-level fields used by the accounting workflow.
    return {**document, **bill}


def _items_for(db, bill_id):
    rows = db.execute(
        select(adjustment_items)
        .where(adjustment_items.c.bill_id == bill_id)
        .order_by(adjustment_items.c.id)
    ).mappings().all()
    return [dict(row) for row in rows]


def get(db, bill_id):
    row = db.execute(
        select(adjustment_bills).where(adjustment_bills.c.id == bill_id)
    ).mappings().first()
    if row is None:
        raise HTTPException(404, "港务调账单不存在")
    return _serialize_bill(row, _items_for(db, bill_id))


def find_by_idempotency_key(db, idempotency_key):
    if not idempotency_key:
        return None
    row = db.execute(
        select(adjustment_bills).where(adjustment_bills.c.idempotency_key == idempotency_key)
    ).mappings().first()
    return get(db, row["id"]) if row else None


def get_for_run(db, run_id):
    row = db.execute(
        select(adjustment_bills).where(adjustment_bills.c.run_id == run_id)
    ).mappings().first()
    if row is None:
        return None
    return _serialize_bill(row, _items_for(db, row["id"]))


def find_by_receipt(db, receipt_no):
    row = db.execute(
        select(adjustment_bills).where(adjustment_bills.c.receipt_no == receipt_no)
    ).mappings().first()
    return get(db, row["id"]) if row else None


def get_by_receipt(db, receipt_no):
    bill = find_by_receipt(db, receipt_no)
    if bill is None:
        raise HTTPException(404, "交接回执对应的调账单不存在")
    return bill


def list_entries(db, limit=100):
    rows = db.execute(
        select(adjustment_bills).order_by(adjustment_bills.c.id.desc()).limit(limit)
    ).mappings().all()
    return [_serialize_bill(row, _items_for(db, row["id"])) for row in rows]


def document_text(db, bill_id):
    return db.scalar(select(adjustment_bills.c.document).where(adjustment_bills.c.id == bill_id))


def original_payload(db, bill_id):
    """Stable superset used by receipt/original-bill downloads.

    The Chinese business document is spread to the top level while the English
    API fields and ledger items remain available for API clients.  All values
    come from the stored bill/items, never from the voyage's current cumulative
    state, so later batches cannot rewrite an already handed-over original.
    """
    bill = get(db, bill_id)
    document = bill.get("document") or {}
    payload = {
        **document,
        **bill,
        "bill_no": bill["receipt_no"],
        "receipt": bill["receipt_no"],
        "total_cents": bill["total_amount_cents"],
        "total": bill["total_amount_cents"],
        "amount": bill["total_amount_cents"],
        "status": "handed_over",
        "download_url": f"/runs/{bill['run_id']}/handover/download",
        "lines": document.get("调账明细", bill.get("items", [])),
        "skipped": document.get("暂缓航次", []),
        "snapshot": document,
    }
    return payload


def original_bytes(db, bill_id):
    payload = original_payload(db, bill_id)
    # Run through the same response schema so downloaded items carry the same
    # compatibility aliases as the JSON API.
    entry = AdjustmentBillEntry.model_validate(payload)
    return canonical_json(entry.model_dump())


def _ensure_voyage_states(db, voyages):
    """Create missing voyage locks before selecting them FOR UPDATE."""
    now = int(time())
    for voyage in sorted(set(voyages)):
        try:
            with db.begin_nested():
                db.execute(insert(voyage_handover_states).values(
                    voyage=voyage,
                    cumulative_amount_cents=0,
                    last_review_day=None,
                    last_review_date=None,
                    last_bill_id=None,
                    updated_at=now,
                ))
        except IntegrityError:
            # A concurrent transaction created the same voyage state.
            pass


def _locked_prior_states(db, voyages):
    _ensure_voyage_states(db, voyages)
    states = {}
    # Always lock in voyage order to keep concurrent multi-voyage bills deadlock-free.
    for voyage in sorted(set(voyages)):
        row = db.execute(
            select(voyage_handover_states)
            .where(voyage_handover_states.c.voyage == voyage)
            .with_for_update()
        ).mappings().one()
        state = dict(row)
        # The ledger rows are the auditable source of “already handed over”.
        # The voyage lock above makes this read atomic with the subsequent insert.
        state["cumulative_amount_cents"] = db.scalar(
            select(func.coalesce(func.sum(adjustment_items.c.amount_cents), 0))
            .where(adjustment_items.c.voyage == voyage)
        )
        states[voyage] = state
    return states


def handover(db, run_id, data, actor, idempotency_key=None):
    """Create the one and only handover bill for a signed run.

    The caller owns the surrounding transaction.  A run row lock makes retries
    for the same run idempotent; voyage state locks serialize overlapping
    batches and make cumulative deduction / stale-date checks atomic.
    """
    key = idempotency_key or getattr(data, "idempotency_key", None)
    note = getattr(data, "note", None)

    # Serialize repeated POSTs for this exact batch before any business check.
    locked_id = db.execute(
        select(runs.c.id).where(runs.c.id == run_id).with_for_update()
    ).scalar_one_or_none()
    if locked_id is None:
        raise HTTPException(404, "执行批次不存在")

    if key:
        existing = find_by_idempotency_key(db, key)
        if existing is not None:
            if existing["run_id"] != run_id:
                raise HTTPException(409, "幂等键已经用于另一个批次的交接")
            return existing, False

    existing = get_for_run(db, run_id)
    if existing is not None:
        return existing, False

    run = run_service.get(db, run_id)
    if run["status"] != JobState.DONE:
        raise HTTPException(409, "批次执行成功并签核后才能交接")
    if reviews.get(db, run_id) is None:
        raise HTTPException(409, "批次尚未复核签核，不能生成港务调账单")

    result = run.get("result") or {}
    rows = result.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(409, "批次结果缺少调账明细，不能交接")

    review_day = run["parameter"]
    try:
        as_of = review_date(review_day).isoformat()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    adjustable_voyages = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        delta = row.get("净差（分）")
        if delta is None:
            delta = row.get("net_delta_cents", row.get("delta_cents"))
        if delta is not None:
            voyage = row.get("航次") or row.get("voyage") or row.get("voyage_code")
            if voyage:
                adjustable_voyages.append(voyage)
    prior_states = _locked_prior_states(db, adjustable_voyages)

    try:
        lines, skipped, total = plan_handover(rows, review_day, prior_states)
    except ValueError as exc:
        # StaleReviewError is included here.  Nothing has been inserted for the
        # bill yet, and the outer transaction rolls back even if it had.
        raise HTTPException(409, str(exc)) from exc

    now = int(time())
    supplied_receipt = getattr(data, "receipt_no", None)
    receipt_no = supplied_receipt or f"GA-{uuid4().hex[:16].upper()}"
    document = {
        "单据类型": "港务调账单",
        "调账单号": receipt_no,
        "交接回执": receipt_no,
        "批次编号": run_id,
        "资料编号": run["case_id"],
        "资料名称": run["case_title"],
        "复核日序号": review_day,
        "复核日": as_of,
        "交接人": actor,
        "交接时间": now,
        "调账明细": lines,
        "暂缓航次": skipped,
        "本次调账合计（分）": total,
    }
    raw_document = canonical_json(document).decode("utf-8")
    digest = content_digest(document)

    bill_id = db.execute(insert(adjustment_bills).values(
        run_id=run_id,
        receipt_no=receipt_no,
        idempotency_key=key,
        actor=actor,
        note=note,
        review_day=review_day,
        review_date=as_of,
        total_amount_cents=total,
        digest=digest,
        document=raw_document,
        created_at=now,
    )).inserted_primary_key[0]

    for line in lines:
        voyage = line["航次"]
        current_delta = line["本次净差（分）"]
        handed_before = line["已交接累计（分）"]
        amount = line["本次调账（分）"]
        db.execute(insert(adjustment_items).values(
            bill_id=bill_id,
            run_id=run_id,
            voyage=voyage,
            review_day=review_day,
            current_delta_cents=current_delta,
            handed_before_cents=handed_before,
            amount_cents=amount,
            created_at=now,
        ))
        db.execute(update(voyage_handover_states)
            .where(voyage_handover_states.c.voyage == voyage)
            .values(
                cumulative_amount_cents=voyage_handover_states.c.cumulative_amount_cents + amount,
                last_review_day=review_day,
                last_review_date=as_of,
                last_bill_id=bill_id,
                updated_at=now,
            ))

    audit.record(db, "handover", actor, "adjustment_bill", bill_id)
    return get(db, bill_id), True
