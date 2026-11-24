from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


class HandoverInput(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=80)
    idempotencyKey: str | None = Field(default=None, max_length=80)
    key: str | None = Field(default=None, max_length=80)
    receipt_key: str | None = Field(default=None, max_length=80)
    request_id: str | None = Field(default=None, max_length=80)
    receipt_no: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)
    comment: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def accept_key_aliases(self):
        self.idempotency_key = (
            self.idempotency_key
            or self.idempotencyKey
            or self.receipt_key
            or self.key
            or self.request_id
        )
        if not self.note and self.comment:
            self.note = self.comment
        return self

    @field_validator(
        "idempotency_key", "idempotencyKey", "key", "receipt_key", "request_id", "receipt_no"
    )
    @classmethod
    def normalize_key(cls, value):
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("note", "comment")
    @classmethod
    def normalize_note(cls, note):
        if note is None:
            return None
        note = note.strip()
        return note or None


class HandoverRequest(HandoverInput):
    run_id: int | None = Field(default=None, ge=1)
    run: int | None = Field(default=None, ge=1)
    batch_id: int | None = Field(default=None, ge=1)
    batchId: int | None = Field(default=None, ge=1)
    execution_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_run(self):
        self.run_id = self.run_id or self.run or self.batch_id or self.batchId or self.execution_id
        if self.run_id is None:
            raise ValueError("run_id 是必填项")
        return self


class AdjustmentItemEntry(BaseModel):
    id: int
    bill_id: int
    run_id: int
    voyage: str
    review_day: int
    current_delta_cents: int
    handed_before_cents: int
    amount_cents: int
    created_at: int

    @computed_field
    @property
    def voyage_id(self) -> str:
        return self.voyage

    @computed_field
    @property
    def voyage_code(self) -> str:
        return self.voyage

    @computed_field
    @property
    def net_delta_cents(self) -> int:
        return self.current_delta_cents

    @computed_field
    @property
    def handed_cumulative_cents(self) -> int:
        return self.handed_before_cents

    @computed_field
    @property
    def deducted_cumulative_cents(self) -> int:
        return self.handed_before_cents

    @computed_field
    @property
    def amount(self) -> int:
        return self.amount_cents

    @computed_field
    @property
    def adjustment_cents(self) -> int:
        return self.amount_cents


class AdjustmentBillEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    run_id: int
    receipt_no: str
    idempotency_key: str | None
    actor: str
    note: str | None
    review_day: int
    review_date: str
    total_amount_cents: int
    digest: str
    document: dict
    created_at: int
    items: list[AdjustmentItemEntry] = []

    # Compatibility aliases for clients using “bill” rather than “handover”.
    @computed_field
    @property
    def bill_no(self) -> str:
        return self.receipt_no

    @computed_field
    @property
    def handover_id(self) -> int:
        return self.id

    @computed_field
    @property
    def adjustment_id(self) -> int:
        return self.id

    @computed_field
    @property
    def total_cents(self) -> int:
        return self.total_amount_cents

    @computed_field
    @property
    def total(self) -> int:
        return self.total_amount_cents

    @computed_field
    @property
    def amount(self) -> int:
        return self.total_amount_cents

    @computed_field
    @property
    def receipt(self) -> str:
        return self.receipt_no

    @computed_field
    @property
    def lines(self) -> list[dict]:
        return self.document.get("调账明细", []) if isinstance(self.document, dict) else []

    @computed_field
    @property
    def entries(self) -> list[dict]:
        return self.lines

    @computed_field
    @property
    def records(self) -> list[AdjustmentItemEntry]:
        return self.items

    @computed_field
    @property
    def adjustments(self) -> list[AdjustmentItemEntry]:
        return self.items

    @computed_field
    @property
    def skipped(self) -> list[dict]:
        return self.document.get("暂缓航次", []) if isinstance(self.document, dict) else []

    @computed_field
    @property
    def snapshot(self) -> dict:
        return self.document

    @computed_field
    @property
    def status(self) -> str:
        return "handed_over"

    @computed_field
    @property
    def download_url(self) -> str:
        return f"/runs/{self.run_id}/handover/download"
