from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from redis.exceptions import RedisError
from src.config.resources import cache, engine
from src.services import adjustments, cases, runs, reviews


def new_case(data, user):
    with engine.begin() as db:
        return cases.create(db, data, user["username"])


def new_run(case_id, data, user):
    with engine.begin() as db:
        run = runs.enqueue(db, case_id, data.parameter, user["username"])
    try:
        cache.lpush("workbench:wake", str(run["id"]))
        cache.ltrim("workbench:wake", 0, 99)
    except RedisError:
        # The database holds the durable queue. The worker also polls it.
        pass
    return run


def new_review(run_id, data, user):
    with engine.begin() as db:
        return reviews.sign(db, run_id, data, user["username"])


def create_handover(run_id, data, user, idempotency_key=None):
    try:
        with engine.begin() as db:
            return adjustments.handover(
                db, run_id, data, user["username"], idempotency_key=idempotency_key
            )
    except IntegrityError:
        # Concurrent retries can lose a unique-key race.  Re-read in a fresh
        # transaction so the client receives the original bill instead of a 500.
        with engine.connect() as db:
            existing = adjustments.get_for_run(db, run_id)
            if existing is not None:
                return existing, False
            if idempotency_key or getattr(data, "idempotency_key", None):
                key = idempotency_key or data.idempotency_key
                keyed = adjustments.find_by_idempotency_key(db, key)
                if keyed is not None:
                    raise HTTPException(409, "幂等键已经用于另一个批次的交接")
            receipt_no = getattr(data, "receipt_no", None)
            if receipt_no:
                receipted = adjustments.find_by_receipt(db, receipt_no)
                if receipted is not None and receipted["run_id"] != run_id:
                    raise HTTPException(409, "交接回执编号已经用于另一个批次")
        raise
