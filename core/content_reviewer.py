"""
技巧内容审查引擎 — 多模型互审，替代（暂缺的）造型师审核。

用法：
    from core.content_reviewer import ContentReviewer
    reviewer = ContentReviewer()
    result = reviewer.review_skill(skill_dict)

CLI:
    python tools/review_skills.py knowledge/skills/french_tuck.json
    python tools/review_skills.py knowledge/skills/  # 批量
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger("content_reviewer")


@dataclass
class ReviewIssue:
    severity: str = ""     # high / medium / low
    category: str = ""     # factual / consistency / safety / variant / missing
    location: str = ""
    description: str = ""
    suggestion: str = ""


@dataclass
class ReviewReport:
    skill_id: str = ""
    overall_verdict: str = ""  # pass / flag / fail
    scores: dict = field(default_factory=dict)
    issues: list[ReviewIssue] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    reviewer_model: str = ""


@dataclass
class BatchReviewResult:
    reports: list[ReviewReport] = field(default_factory=list)
    passed: int = 0
    flagged: int = 0
    failed: int = 0


class ContentReviewer:
    """
    离线审查引擎（不依赖 LLM API）。

    Phase 4 MVP: 规则化审查 + 结构验证，不调用 LLM。
    后续可扩展为真正的多模型互审（调用 router.chat）。
    """

    def __init__(self):
        self._reviewers = ["rule_based"]  # 后续扩展: "minimax-m3", "doubao-2.0-pro"

    def review_skill(self, skill: dict, knowledge: dict = None) -> ReviewReport:
        """审查单个技巧，返回 ReviewReport"""
        skill_id = skill.get("skill_id", "unknown")
        issues = []
        strengths = []
        scores = {}

        # 1. 结构完整性检查
        required = ["skill_id", "name", "stage", "difficulty", "steps", "why_it_works",
                     "applicable", "inapplicable", "common_mistakes"]
        missing = [f for f in required if f not in skill]
        if missing:
            issues.append(ReviewIssue(
                severity="high", category="missing", location="root",
                description=f"缺少必填字段: {', '.join(missing)}",
                suggestion="补充缺失字段"
            ))

        # 2. steps 至少 2 个
        steps = skill.get("steps", [])
        if len(steps) < 2:
            issues.append(ReviewIssue(
                severity="medium", category="missing", location="steps",
                description=f"只有 {len(steps)} 个步骤（建议≥3）",
                suggestion="将操作分解为更细的步骤"
            ))
        elif len(steps) >= 3:
            strengths.append("步骤≥3个，可操作性强")

        # 3. 检查 body_types 是否覆盖全部5种
        body_types = skill.get("applicable", {}).get("body_types", {})
        expected = {"梨形", "矩形", "倒三角", "苹果", "沙漏"}
        actual = set(body_types.keys())
        missing_bt = expected - actual
        if missing_bt:
            issues.append(ReviewIssue(
                severity="low", category="missing", location="applicable.body_types",
                description=f"缺少体型评分: {', '.join(missing_bt)}",
                suggestion="为缺失的体型补充评分和说明"
            ))

        # 4. 检查 style_variants 覆盖
        variants = skill.get("style_variants", {})
        if len(variants) < 3:
            issues.append(ReviewIssue(
                severity="low", category="missing", location="style_variants",
                description=f"只有 {len(variants)} 个风格变体（期望≥3）",
                suggestion="至少覆盖 clean_fit, city_boy, korean_light_mature"
            ))
        elif len(variants) >= 5:
            strengths.append(f"覆盖 {len(variants)} 个风格变体，全面")

        # 5. 检查 body_modifiers
        modifiers = skill.get("body_modifiers", {})
        if not modifiers:
            issues.append(ReviewIssue(
                severity="low", category="missing", location="body_modifiers",
                description="缺少身体修饰符定义",
                suggestion="至少为 1-2 个身体特征定义 modifier"
            ))

        # 6. 检查 common_mistakes 质量
        mistakes = skill.get("common_mistakes", [])
        has_correction = sum(1 for m in mistakes if "正确做法" in m)
        if len(mistakes) > 0 and has_correction < len(mistakes):
            issues.append(ReviewIssue(
                severity="low", category="consistency", location="common_mistakes",
                description="部分常见错误缺少'正确做法'",
                suggestion="每条错误都加上'→ 正确做法：...'"
            ))
        if has_correction == len(mistakes) and len(mistakes) > 0:
            strengths.append("所有常见错误都附了正确做法")

        # 7. 检查 steps 与 common_mistakes 一致性
        if "塞太紧" in str(mistakes) and "拉出" not in " ".join(steps):
            issues.append(ReviewIssue(
                severity="medium", category="consistency",
                location="steps vs common_mistakes",
                description="common_mistakes 警告'塞太紧'但 steps 没有拉出松量的步骤",
                suggestion="在 steps 中加入'拉出1cm松量'这一步"
            ))

        # 8. 检查是否标记了 techniques_inferred
        if skill.get("techniques_inferred"):
            issues.append(ReviewIssue(
                severity="low", category="missing",
                location="techniques_inferred",
                description="此技巧的 signature_techniques 是脚本推测的，需要人工精编",
                suggestion="至少为 top 3 风格方向手动编写专属执行方式"
            ))

        # 计算分数
        scores = {
            "completeness": 10 - min(5, len(issues)),
            "consistency": 10 if not any(i.category == "consistency" for i in issues) else 6,
            "variant_quality": min(10, len(variants) * 2),
            "actionability": 10 if len(steps) >= 3 else 6,
        }

        # 判定
        high_issues = [i for i in issues if i.severity == "high"]
        medium_issues = [i for i in issues if i.severity == "medium"]

        if high_issues:
            verdict = "fail"
        elif medium_issues:
            verdict = "flag"
        else:
            verdict = "pass"

        return ReviewReport(
            skill_id=skill_id,
            overall_verdict=verdict,
            scores=scores,
            issues=issues,
            strengths=strengths,
            reviewer_model="rule_based",
        )

    def batch_review(self, skills: list[dict]) -> BatchReviewResult:
        """批量审查"""
        reports = []
        passed = flagged = failed = 0
        for skill in skills:
            report = self.review_skill(skill)
            reports.append(report)
            if report.overall_verdict == "pass":
                passed += 1
            elif report.overall_verdict == "flag":
                flagged += 1
            else:
                failed += 1

        logger.info(f"批量审查完成: {passed} pass / {flagged} flag / {failed} fail")
        return BatchReviewResult(reports=reports, passed=passed, flagged=flagged, failed=failed)


# ══════════════════════════════════════════════════════════════════
# 快速测试
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from core.skill_matcher import SkillMatcher

    print("=" * 60)
    print("ContentReviewer — 自检")
    print("=" * 60)

    matcher = SkillMatcher()
    reviewer = ContentReviewer()
    result = reviewer.batch_review(matcher.skills)

    print(f"\n📊 批量审查结果: {result.passed} pass / {result.flagged} flag / {result.failed} fail")
    for r in result.reports:
        icon = "✅" if r.overall_verdict == "pass" else "⚠️" if r.overall_verdict == "flag" else "❌"
        issue_str = f" ({len(r.issues)} issues)" if r.issues else ""
        print(f"  {icon} {r.skill_id}: {r.overall_verdict}{issue_str}")
        if r.strengths:
            print(f"     👍 {', '.join(r.strengths[:2])}")
        for i in r.issues:
            print(f"     [{i.severity}] {i.category}: {i.description[:80]}")

    print("\n✅ ContentReviewer 自检完成。")
