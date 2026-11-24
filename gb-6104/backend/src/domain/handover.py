from datetime import timedelta

from src.domain.contract_terms import ANCHOR_DAY


class HandoverRuleError(ValueError):
    """Base class for handover rules that must reject the whole bill."""


class StaleReviewError(HandoverRuleError):
    def __init__(self, voyage, review_day, last_review_day):
        self.voyage = voyage
        self.review_day = review_day
        self.last_review_day = last_review_day
        super().__init__(
            f"航次 {voyage} 的复核日为第 {review_day} 天，"
            f"早于上次交接使用的第 {last_review_day} 天；整张单退回，不留下部分入账"
        )


def review_date(review_day):
    if type(review_day) is not int or not 1 <= review_day <= 180:
        raise HandoverRuleError("复核日须为 1–180 的整数")
    return ANCHOR_DAY + timedelta(days=review_day - 1)


def deduct_cumulative(net_delta_cents, handed_cumulative_cents):
    """Return the incremental amount after deducting handed-over cumulative."""
    return int(net_delta_cents) - int(handed_cumulative_cents or 0)


def is_stale(review_day, last_review_day):
    return last_review_day is not None and int(review_day) < int(last_review_day)


def plan_handover(rows, review_day, prior_states=None):
    """Build adjustment lines from a fixed run result.

    ``prior_states`` is keyed by voyage and may contain
    ``cumulative_amount_cents`` and ``last_review_day``.  Rows whose net
    difference is ``None`` are suspended and are intentionally skipped.
    """
    if not isinstance(rows, list):
        raise HandoverRuleError("批次结果缺少航次明细")

    prior_states = prior_states or {}
    as_of = review_date(review_day).isoformat()
    lines = []
    skipped = []
    seen = set()

    for row in rows:
        if not isinstance(row, dict):
            raise HandoverRuleError("批次结果明细格式不正确")
        voyage = row.get("航次") or row.get("voyage") or row.get("voyage_code")
        if not isinstance(voyage, str) or not voyage:
            raise HandoverRuleError("批次结果缺少航次编号")

        net_delta = row.get("净差（分）")
        if net_delta is None:
            net_delta = row.get("net_delta_cents", row.get("delta_cents"))
        if net_delta is None:
            # Rows with no computable delta are suspended in the business model.
            net_delta = None
        if net_delta is None:
            skipped.append({
                "航次": voyage,
                "航段": row.get("航段"),
                "服务日": row.get("服务日"),
                "原因": row.get("复核条款") or "暂缓航次",
            })
            continue

        if type(net_delta) is not int:
            raise HandoverRuleError(f"航次 {voyage} 的净差不是整数")
        if voyage in seen:
            raise HandoverRuleError(f"航次 {voyage} 在同一批次中重复")
        seen.add(voyage)

        state = prior_states.get(voyage, {}) or {}
        if isinstance(state, int):
            state = {"cumulative_amount_cents": state}
        last_review_day = state.get("last_review_day")
        if is_stale(review_day, last_review_day):
            raise StaleReviewError(voyage, review_day, last_review_day)

        handed_before = int(
            state.get("cumulative_amount_cents", state.get("cumulative_amount", 0)) or 0
        )
        amount = deduct_cumulative(net_delta, handed_before)
        lines.append({
            "航次": voyage,
            "航段": row.get("航段"),
            "服务日": row.get("服务日"),
            "复核日": as_of,
            "本次净差（分）": net_delta,
            "已交接累计（分）": handed_before,
            "本次调账（分）": amount,
        })

    lines.sort(key=lambda item: item["航次"])
    total = sum(item["本次调账（分）"] for item in lines)
    return lines, skipped, total


# Chinese business name alias kept for callers that use the domain language.
plan_adjustment = plan_handover
