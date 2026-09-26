"""术前放行判定规则。

本模块只做判断，不接触 HTTP 和数据库，时间由调用方解析后传入，
规则阈值、缺项代码和状态汇总都在这里单独维护。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# 分配提出后，接收医院必须完成术前复核提交的时限（分钟）
REVIEW_DEADLINE_MINUTES = 120
# 主刀最早可开台时刻距离器官过期必须保留的最短时间（分钟）
MIN_SURGERY_WINDOW_MINUTES = 60

MISSING_CROSSMATCH = "missing_crossmatch_result"
MISSING_SURGEON_SLOT = "missing_surgeon_slot"
CROSSMATCH_INCOMPATIBLE = "crossmatch_incompatible"
REVIEW_TIMEOUT = "review_timeout"
INSUFFICIENT_SURGERY_WINDOW = "insufficient_surgery_window"

REASON_MESSAGES: dict[str, str] = {
    MISSING_CROSSMATCH: "未提交交叉配型结果",
    MISSING_SURGEON_SLOT: "未提交主刀可手术时段",
    CROSSMATCH_INCOMPATIBLE: "交叉配型结果不合格",
    REVIEW_TIMEOUT: "术前复核超过规定时限",
    INSUFFICIENT_SURGERY_WINDOW: "主刀可手术时段距器官过期不足，来不及完成手术",
}

# 分配视图中的放行状态文案
STATUS_PENDING = "pending"                  # 待接收医院提交
STATUS_APPROVED = "approved"                # 已放行
STATUS_REJECTED = "rejected"                # 未通过（见原因/缺项）
STATUS_PENDING_BACKFILL = "pending_backfill"  # 旧分配无记录，待协调台补录

STATUS_LABELS: dict[str, str] = {
    STATUS_PENDING: "待提交",
    STATUS_APPROVED: "已放行",
    STATUS_REJECTED: "未通过",
    STATUS_PENDING_BACKFILL: "待补录",
}


@dataclass
class ClearanceSubmission:
    allocation_created_at: datetime
    expires_at: datetime
    submitted_at: datetime
    crossmatch_compatible: bool | None       # None 表示该项未提交
    surgeon_available_at: datetime | None    # None 表示该项未提交


def reason_label(code: str) -> str:
    return REASON_MESSAGES.get(code, code)


def evaluate(submission: ClearanceSubmission) -> dict[str, Any]:
    """按器官剩余时间判断术前放行是否通过，返回结论与全部缺项/不合格原因。"""
    reasons: list[str] = []

    # 1) 交叉配型结果：先查缺项，再查合格与否
    if submission.crossmatch_compatible is None:
        reasons.append(MISSING_CROSSMATCH)
    elif submission.crossmatch_compatible is False:
        reasons.append(CROSSMATCH_INCOMPATIBLE)

    # 2) 复核时限：提交时刻不得晚于分配提出后的复核期限
    review_deadline = submission.allocation_created_at + timedelta(minutes=REVIEW_DEADLINE_MINUTES)
    if submission.submitted_at > review_deadline:
        reasons.append(REVIEW_TIMEOUT)

    # 3) 手术时段：主刀开台时刻距器官过期必须留足最短窗口
    remaining_minutes: float | None = None
    if submission.surgeon_available_at is None:
        reasons.append(MISSING_SURGEON_SLOT)
    else:
        remaining_minutes = round((submission.expires_at - submission.surgeon_available_at).total_seconds() / 60, 1)
        if remaining_minutes < MIN_SURGERY_WINDOW_MINUTES:
            reasons.append(INSUFFICIENT_SURGERY_WINDOW)

    return {
        "decision": STATUS_APPROVED if not reasons else STATUS_REJECTED,
        "reasons": reasons,
        "reason_messages": [reason_label(code) for code in reasons],
        "review_deadline": review_deadline,
        "remaining_minutes": remaining_minutes,
        "limits": {
            "review_deadline_minutes": REVIEW_DEADLINE_MINUTES,
            "min_surgery_window_minutes": MIN_SURGERY_WINDOW_MINUTES,
        },
    }


def summarize(allocation_status: str, latest_record: dict[str, Any] | None) -> str:
    """汇总分配当前的放行状态；旧分配已有后续状态却没有记录时标出待补。"""
    if latest_record is None:
        return STATUS_PENDING if allocation_status == "proposed" else STATUS_PENDING_BACKFILL
    return str(latest_record["decision"])
