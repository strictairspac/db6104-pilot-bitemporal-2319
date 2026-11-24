from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.config.resources import engine
from src.constants.job_state import JobState
from src.controllers.access import identity, reviewer
from src.controllers.workbench import new_review
from src.schemas.reviews import ReviewEntry, ReviewInput
from src.schemas.runs import RunEntry
from src.services import adjustments, reviews, runs
from src.utils.serial import canonical_json

router = APIRouter(prefix="/runs", tags=["Execution"])


@router.get("", response_model=list[RunEntry], dependencies=[Depends(identity)])
def list_runs():
    with engine.connect() as db:
        return runs.list_entries(db)


@router.get("/{run_id}", response_model=RunEntry, dependencies=[Depends(identity)])
def run_detail(run_id: int):
    with engine.connect() as db:
        return runs.get(db, run_id)


@router.get("/{run_id}/review", response_model=ReviewEntry | None, dependencies=[Depends(identity)])
def review_detail(run_id: int):
    with engine.connect() as db:
        runs.get(db, run_id)
        return reviews.get(db, run_id)


@router.post("/{run_id}/review", response_model=ReviewEntry, status_code=201)
def sign(run_id: int, form: ReviewInput, user=Depends(reviewer)):
    return new_review(run_id, form, user)


@router.get("/{run_id}/export", dependencies=[Depends(identity)])
def export(
    run_id: int,
    kind: str | None = Query(default=None),
    document_type: str | None = Query(default=None, alias="type"),
):
    handover_kind = (kind or document_type or "").lower()
    if handover_kind in {"handover", "adjustment", "adjustment-bill", "receipt", "settlement"}:
        with engine.connect() as db:
            bill = adjustments.get_for_run(db, run_id)
            if bill is None:
                raise HTTPException(404, "该批次尚未交接")
            raw = adjustments.original_bytes(db, bill["id"])
        return Response(content=raw, media_type="application/json", headers={
            "Content-Disposition": f'attachment; filename="handover-{run_id}.json"',
        })

    with engine.connect() as db:
        run = runs.get(db, run_id)
        if run["status"] != JobState.DONE:
            raise HTTPException(409, "没有可导出的执行结果")
        run["review"] = reviews.get(db, run_id)
    return Response(canonical_json(run), media_type="application/json", headers={
        "Content-Disposition": f"attachment; filename=evidence-{run_id}.json",
    })
