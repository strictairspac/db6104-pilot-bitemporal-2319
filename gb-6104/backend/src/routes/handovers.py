from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response

from src.config.resources import engine
from src.controllers.access import identity, reviewer
from src.controllers.workbench import create_handover
from src.schemas.adjustments import AdjustmentBillEntry, HandoverInput, HandoverRequest
from src.services import adjustments, runs

router = APIRouter(tags=["Port adjustment bills"])

def idempotency_header(
    standard: Annotated[str | None, Header(alias="Idempotency-Key", max_length=80)] = None,
    prefixed: Annotated[str | None, Header(alias="X-Idempotency-Key", max_length=80)] = None,
):
    return standard or prefixed


IdempotencyKey = Annotated[str | None, Depends(idempotency_header)]


def _download_response(raw_document, run_id, bill_id=None):
    if raw_document is None:
        raise HTTPException(404, "已交接原单不存在")
    content = raw_document if isinstance(raw_document, bytes) else str(raw_document).encode("utf-8")
    suffix = run_id if run_id is not None else (bill_id or "bill")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="handover-{suffix}.json"'},
    )


@router.get(
    "/runs/{run_id}/handover",
    response_model=AdjustmentBillEntry | None,
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/handovers",
    response_model=AdjustmentBillEntry | None,
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/handover-bill",
    response_model=AdjustmentBillEntry | None,
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/adjustment",
    response_model=AdjustmentBillEntry | None,
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/adjustments",
    response_model=AdjustmentBillEntry | None,
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/adjustment-bill",
    response_model=AdjustmentBillEntry | None,
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/settlement",
    response_model=AdjustmentBillEntry | None,
    dependencies=[Depends(identity)],
)
@router.get(
    "/reviews/{run_id}/handover",
    response_model=AdjustmentBillEntry | None,
    dependencies=[Depends(identity)],
)
@router.get(
    "/reviews/{run_id}/adjustment",
    response_model=AdjustmentBillEntry | None,
    dependencies=[Depends(identity)],
)
def run_handover_detail(run_id: int):
    with engine.connect() as db:
        runs.get(db, run_id)
        return adjustments.get_for_run(db, run_id)


@router.post("/runs/{run_id}/handover", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/handovers", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/handover-bill", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/hand", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/transfer", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/settle", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/adjust", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/adjustment", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/adjustments", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/adjustment-bill", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/settlement", response_model=AdjustmentBillEntry)
@router.post("/reviews/{run_id}/handover", response_model=AdjustmentBillEntry)
@router.post("/reviews/{run_id}/adjustment", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/handover/retry", response_model=AdjustmentBillEntry)
@router.post("/runs/{run_id}/adjustment/retry", response_model=AdjustmentBillEntry)
def handover_run(
    run_id: int,
    response: Response,
    form: HandoverInput | None = Body(default=None),
    user=Depends(reviewer),
    idempotency_key: IdempotencyKey = None,
):
    bill, created = create_handover(run_id, form or HandoverInput(), user, idempotency_key)
    response.status_code = 201 if created else 200
    return bill


@router.get(
    "/runs/{run_id}/handover/download",
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/handovers/download",
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/handover-bill/download",
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/adjustment/download",
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/adjustments/download",
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/adjustment-bill/download",
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/settlement/download",
    dependencies=[Depends(identity)],
)
@router.get(
    "/runs/{run_id}/handover/receipt",
    dependencies=[Depends(identity)],
)
def download_run_handover(run_id: int):
    with engine.connect() as db:
        bill = adjustments.get_for_run(db, run_id)
        if bill is None:
            raise HTTPException(404, "该批次尚未交接")
        raw = adjustments.original_bytes(db, bill["id"])
    return _download_response(raw, run_id, bill["id"])


@router.get(
    "/handovers",
    response_model=list[AdjustmentBillEntry],
    dependencies=[Depends(identity)],
)
@router.get(
    "/adjustments",
    response_model=list[AdjustmentBillEntry],
    dependencies=[Depends(identity)],
)
@router.get(
    "/adjustment-bills",
    response_model=list[AdjustmentBillEntry],
    dependencies=[Depends(identity)],
)
@router.get(
    "/settlements",
    response_model=list[AdjustmentBillEntry],
    dependencies=[Depends(identity)],
)
def list_handovers():
    with engine.connect() as db:
        return adjustments.list_entries(db)


@router.post("/handovers", response_model=AdjustmentBillEntry)
@router.post("/adjustments", response_model=AdjustmentBillEntry)
@router.post("/adjustment-bills", response_model=AdjustmentBillEntry)
@router.post("/settlements", response_model=AdjustmentBillEntry)
def create_named_handover(
    response: Response,
    form: HandoverRequest,
    user=Depends(reviewer),
    idempotency_key: IdempotencyKey = None,
):
    bill, created = create_handover(form.run_id, form, user, idempotency_key)
    response.status_code = 201 if created else 200
    return bill


@router.post("/handovers/{bill_id}/retry", response_model=AdjustmentBillEntry)
@router.post("/adjustments/{bill_id}/retry", response_model=AdjustmentBillEntry)
@router.post("/adjustment-bills/{bill_id}/retry", response_model=AdjustmentBillEntry)
@router.post("/settlements/{bill_id}/retry", response_model=AdjustmentBillEntry)
def retry_named_handover(
    bill_id: int,
    response: Response,
    form: HandoverInput | None = Body(default=None),
    user=Depends(reviewer),
    idempotency_key: IdempotencyKey = None,
):
    with engine.connect() as db:
        bill = adjustments.get(db, bill_id)
        run_id = bill["run_id"]
    return handover_run(run_id, response, form, user, idempotency_key)


@router.get(
    "/handovers/{bill_id}",
    response_model=AdjustmentBillEntry,
    dependencies=[Depends(identity)],
)
@router.get(
    "/adjustments/{bill_id}",
    response_model=AdjustmentBillEntry,
    dependencies=[Depends(identity)],
)
@router.get(
    "/adjustment-bills/{bill_id}",
    response_model=AdjustmentBillEntry,
    dependencies=[Depends(identity)],
)
@router.get(
    "/settlements/{bill_id}",
    response_model=AdjustmentBillEntry,
    dependencies=[Depends(identity)],
)
def handover_detail(bill_id: int):
    with engine.connect() as db:
        return adjustments.get(db, bill_id)


@router.get("/handovers/{bill_id}/download", dependencies=[Depends(identity)])
@router.get("/handovers/{bill_id}/receipt", dependencies=[Depends(identity)])
@router.get("/adjustments/{bill_id}/download", dependencies=[Depends(identity)])
@router.get("/adjustments/{bill_id}/receipt", dependencies=[Depends(identity)])
@router.get("/adjustment-bills/{bill_id}/download", dependencies=[Depends(identity)])
@router.get("/settlements/{bill_id}/download", dependencies=[Depends(identity)])
def download_handover(bill_id: int):
    with engine.connect() as db:
        bill = adjustments.get(db, bill_id)
        raw = adjustments.original_bytes(db, bill_id)
        run_id = bill["run_id"]
    return _download_response(raw, run_id, bill_id)


@router.get(
    "/receipts/{receipt_no}",
    response_model=AdjustmentBillEntry,
    dependencies=[Depends(identity)],
)
def receipt_detail(receipt_no: str):
    with engine.connect() as db:
        return adjustments.get_by_receipt(db, receipt_no)


@router.get("/receipts/{receipt_no}/download", dependencies=[Depends(identity)])
def download_receipt(receipt_no: str):
    with engine.connect() as db:
        bill = adjustments.get_by_receipt(db, receipt_no)
        raw = adjustments.original_bytes(db, bill["id"])
        run_id = bill["run_id"]
    return _download_response(raw, run_id, bill["id"])
