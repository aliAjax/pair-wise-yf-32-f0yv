"""术前放行判断规则。

纯函数模块：只负责"能不能放行"的判断，不依赖存储和页面，
记录读写见 release_store.py，展示见 static/release.html。
"""
from __future__ import annotations

from datetime import datetime, timedelta

# 交叉配型复核有效期：提交后超过该时长仍未接受，复核视为超时
REVIEW_VALID_HOURS = 12
# 主刀可手术时段的最短长度（分钟），短于此视为时段不足
MIN_WINDOW_MINUTES = 60

RESULTS = {"pass", "fail"}


def evaluate_release(*, crossmatch_result: str | None, window_start: datetime | None, window_end: datetime | None,
                     submitted_at: datetime, organ_expires_at: datetime, now: datetime) -> tuple[str, list[dict[str, str]]]:
    """根据提交内容和器官剩余时间判断是否放行。

    返回 (decision, missing)：decision 为 "cleared" 或 "blocked"，
    missing 为缺项说明列表 [{"code": ..., "message": ...}]，可随记录保存、随响应返回。
    同一函数既用于提交时判断，也用于接受时按当前时刻复核（复核超时、时段流逝会在此暴露）。
    """
    missing: list[dict[str, str]] = []
    if not crossmatch_result:
        missing.append({"code": "crossmatch_missing", "message": "缺少交叉配型结果"})
    elif crossmatch_result not in RESULTS:
        missing.append({"code": "crossmatch_invalid", "message": "交叉配型结果取值无效，应为 pass 或 fail"})
    elif crossmatch_result == "fail":
        missing.append({"code": "crossmatch_failed", "message": "交叉配型不合格"})

    if window_start is None or window_end is None:
        missing.append({"code": "window_missing", "message": "缺少主刀可手术时段"})
    elif window_end <= window_start:
        missing.append({"code": "window_invalid", "message": "主刀可手术时段起止时间无效"})
    else:
        if window_end - window_start < timedelta(minutes=MIN_WINDOW_MINUTES):
            missing.append({"code": "window_too_short", "message": f"主刀可手术时段不足 {MIN_WINDOW_MINUTES} 分钟"})
        if window_end > organ_expires_at:
            missing.append({"code": "window_beyond_organ", "message": "器官剩余时间不足以覆盖主刀可手术时段"})
        if window_end <= now:
            missing.append({"code": "window_elapsed", "message": "主刀可手术时段已过去"})

    if submitted_at + timedelta(hours=REVIEW_VALID_HOURS) <= now:
        missing.append({"code": "review_expired", "message": "术前复核已超时，需要重新提交"})

    return ("blocked" if missing else "cleared"), missing
