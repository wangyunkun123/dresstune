"""
三元反馈存储 — 😊更好 / 😐差不多 / 😕不如 的收集与查询。

Phase 5 MVP: JSONL 文件存储，无数据库依赖。

用法：
    from core.feedback_store import FeedbackStore, FeedbackEntry
    store = FeedbackStore()
    store.record(FeedbackEntry(user_id="u1", skill_id="french_tuck", feedback="better", ...))
    stats = store.get_skill_stats("french_tuck")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger("feedback_store")


@dataclass
class FeedbackEntry:
    user_id: str = ""
    skill_id: str = ""
    feedback: str = ""         # "better" | "same" | "worse"
    outfit_data: dict = field(default_factory=dict)
    user_context_snapshot: dict = field(default_factory=dict)
    match_score: int = 0
    timestamp: str = ""
    session_id: str = ""


class FeedbackStore:
    """反馈存储（JSONL 文件）"""

    def __init__(self, storage_path: str = None):
        if storage_path is None:
            storage_path = Path(__file__).parent.parent / "data" / "feedback" / "feedback.jsonl"
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: FeedbackEntry) -> None:
        """记录一条反馈"""
        if not entry.timestamp:
            entry.timestamp = datetime.now().isoformat()
        line = json.dumps(entry.__dict__, ensure_ascii=False)
        with open(self.storage_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        logger.debug(f"反馈记录: {entry.user_id} → {entry.skill_id} = {entry.feedback}")

    def _load_all(self) -> list[dict]:
        """加载全部反馈记录"""
        if not self.storage_path.exists():
            return []
        records = []
        with open(self.storage_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records

    def get_skill_stats(self, skill_id: str) -> dict:
        """获取某技巧的全局反馈统计"""
        records = [r for r in self._load_all() if r.get("skill_id") == skill_id]
        return self._compute_stats(records, skill_id)

    def get_user_stats(self, user_id: str) -> dict:
        """获取某用户的反馈统计"""
        records = [r for r in self._load_all() if r.get("user_id") == user_id]
        return self._compute_stats(records, user_id)

    def get_user_skill_feedback(self, user_id: str, skill_id: str) -> Optional[dict]:
        """获取某用户对某技巧的最近反馈"""
        records = [
            r for r in self._load_all()
            if r.get("user_id") == user_id and r.get("skill_id") == skill_id
        ]
        if not records:
            return None
        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return records[0]

    def get_user_series_stats(self, user_id: str, series: str, skills_data: list[dict] = None) -> dict:
        """获取某用户对某系列技巧的反馈统计"""
        # 找到该系列的所有 skill_id
        series_skills = set()
        if skills_data:
            for s in skills_data:
                if s.get("series") == series:
                    series_skills.add(s.get("skill_id"))

        records = [
            r for r in self._load_all()
            if r.get("user_id") == user_id and r.get("skill_id") in series_skills
        ]
        return self._compute_stats(records, user_id)

    def get_global_stats(self) -> dict:
        """获取全局反馈统计"""
        records = self._load_all()
        return self._compute_stats(records, "global")

    def get_flagged_skills(self, worse_threshold: float = 0.30, min_samples: int = 5) -> list[str]:
        """获取「不如」率超过阈值的技巧列表"""
        records = self._load_all()
        by_skill = {}
        for r in records:
            sid = r.get("skill_id", "")
            if sid not in by_skill:
                by_skill[sid] = []
            by_skill[sid].append(r)

        flagged = []
        for sid, recs in by_skill.items():
            if len(recs) < min_samples:
                continue
            worse = sum(1 for r in recs if r.get("feedback") == "worse")
            if worse / len(recs) > worse_threshold:
                flagged.append(sid)
        return flagged

    @staticmethod
    def _compute_stats(records: list[dict], entity_id: str) -> dict:
        n = len(records)
        if n == 0:
            return {"entity": entity_id, "total": 0, "better_rate": 0, "same_rate": 0, "worse_rate": 0, "flagged": False}

        better = sum(1 for r in records if r.get("feedback") == "better")
        same = sum(1 for r in records if r.get("feedback") == "same")
        worse = sum(1 for r in records if r.get("feedback") == "worse")

        return {
            "entity": entity_id,
            "total": n,
            "better_rate": round(better / n, 2),
            "same_rate": round(same / n, 2),
            "worse_rate": round(worse / n, 2),
            "flagged": worse / n > 0.30 and n >= 5,
        }
