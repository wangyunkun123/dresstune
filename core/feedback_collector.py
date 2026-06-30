"""
反馈收集器 — pipeline 集成入口。

用法：
    from core.feedback_collector import record_feedback
    record_feedback(user_id="u1", skill_id="french_tuck", feedback="better", ...)
"""

from __future__ import annotations

from core.feedback_store import FeedbackStore, FeedbackEntry

_store: FeedbackStore = None


def _get_store() -> FeedbackStore:
    global _store
    if _store is None:
        _store = FeedbackStore()
    return _store


def record_feedback(
    user_id: str,
    skill_id: str,
    feedback: str,
    outfit_data: dict = None,
    user_context: dict = None,
    match_score: int = 0,
    session_id: str = None,
) -> FeedbackEntry:
    """记录一条三元反馈"""
    entry = FeedbackEntry(
        user_id=user_id,
        skill_id=skill_id,
        feedback=feedback,
        outfit_data=outfit_data or {},
        user_context_snapshot=user_context or {},
        match_score=match_score,
        session_id=session_id or "",
    )
    _get_store().record(entry)
    return entry


def get_store() -> FeedbackStore:
    return _get_store()
