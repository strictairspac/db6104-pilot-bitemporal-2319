from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import LONGTEXT

from .base import metadata

DocumentText = Text().with_variant(LONGTEXT(), "mysql")


adjustment_bills = Table(
    "adjustment_bills", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", ForeignKey("runs.id"), nullable=False, unique=True, index=True),
    Column("receipt_no", String(64), nullable=False, unique=True),
    Column("idempotency_key", String(80), nullable=True, unique=True),
    Column("actor", String(48), nullable=False),
    Column("note", String(500), nullable=True),
    Column("review_day", Integer, nullable=False),
    Column("review_date", String(10), nullable=False),
    Column("total_amount_cents", BigInteger, nullable=False),
    Column("digest", String(64), nullable=False),
    Column("document", DocumentText, nullable=False),
    Column("created_at", BigInteger, nullable=False),
)


adjustment_items = Table(
    "adjustment_items", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("bill_id", ForeignKey("adjustment_bills.id"), nullable=False, index=True),
    Column("run_id", ForeignKey("runs.id"), nullable=False, index=True),
    Column("voyage", String(64), nullable=False, index=True),
    Column("review_day", Integer, nullable=False),
    Column("current_delta_cents", BigInteger, nullable=False),
    Column("handed_before_cents", BigInteger, nullable=False),
    Column("amount_cents", BigInteger, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    UniqueConstraint("bill_id", "voyage", name="uq_adjustment_item_bill_voyage"),
    UniqueConstraint("run_id", "voyage", name="uq_adjustment_item_run_voyage"),
)


voyage_handover_states = Table(
    "voyage_handover_states", metadata,
    Column("voyage", String(64), primary_key=True),
    Column("cumulative_amount_cents", BigInteger, nullable=False, default=0),
    Column("last_review_day", Integer, nullable=True),
    Column("last_review_date", String(10), nullable=True),
    Column("last_bill_id", ForeignKey("adjustment_bills.id"), nullable=True),
    Column("updated_at", BigInteger, nullable=False),
)
