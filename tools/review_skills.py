#!/usr/bin/env python3
"""CLI 技巧审查工具"""

import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.content_reviewer import ContentReviewer
from core.skill_matcher import SkillMatcher


def review_file(filepath):
    skill = json.loads(Path(filepath).read_text("utf-8"))
    reviewer = ContentReviewer()
    return reviewer.review_skill(skill)


def main():
    if len(sys.argv) < 2:
        print("用法: python tools/review_skills.py <path>")
        print("  python tools/review_skills.py knowledge/skills/french_tuck.json")
        print("  python tools/review_skills.py knowledge/skills/  # 批量")
        sys.exit(1)

    target = Path(sys.argv[1])

    if target.is_file():
        report = review_file(target)
        icon = "✅" if report.overall_verdict == "pass" else "⚠️" if report.overall_verdict == "flag" else "❌"
        print(f"{icon} {report.skill_id}: {report.overall_verdict}")
        print(f"   Scores: {report.scores}")
        for i in report.issues:
            print(f"   [{i.severity}] {i.category}: {i.description}")
        for s in report.strengths:
            print(f"   👍 {s}")

    elif target.is_dir():
        matcher = SkillMatcher(skills_dir=str(target))
        reviewer = ContentReviewer()
        result = reviewer.batch_review(matcher.skills)
        print(f"\n{'='*50}")
        print(f"批量审查: {result.passed} pass / {result.flagged} flag / {result.failed} fail")
        print(f"{'='*50}")
        for r in result.reports:
            icon = "✅" if r.overall_verdict == "pass" else "⚠️" if r.overall_verdict == "flag" else "❌"
            print(f"  {icon} {r.skill_id} [{r.overall_verdict}] — {r.strengths[:1] if r.strengths else '—'}")
        if result.failed > 0:
            print(f"\n❌ 需要修复 {result.failed} 个技巧")
        elif result.flagged > 0:
            print(f"\n⚠️ {result.flagged} 个技巧可改进")
        else:
            print(f"\n✅ 所有技巧通过审查")

    else:
        print(f"❌ 路径不存在: {target}")
        sys.exit(1)


if __name__ == "__main__":
    main()
