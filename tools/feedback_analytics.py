#!/usr/bin/env python3
"""CLI 反馈分析工具"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.feedback_store import FeedbackStore
from core.skill_matcher import SkillMatcher


def main():
    store = FeedbackStore()
    flag = "--skill" in sys.argv or "--report" not in " ".join(sys.argv)

    if "--skill" in sys.argv:
        idx = sys.argv.index("--skill")
        skill_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if skill_id:
            stats = store.get_skill_stats(skill_id)
            print(f"技巧 {skill_id}:")
            print(f"  总反馈: {stats['total']}")
            print(f"  😊 更好: {stats['better_rate']:.0%}")
            print(f"  😐 差不多: {stats['same_rate']:.0%}")
            print(f"  😕 不如: {stats['worse_rate']:.0%}")
            print(f"  标记: {'🚨 需改进' if stats['flagged'] else '✅ 正常'}")
        return

    if "--flagged" in sys.argv:
        flagged = store.get_flagged_skills()
        if flagged:
            print(f"🚨 {len(flagged)} 个技巧「不如」率 >30%:")
            for sid in flagged:
                stats = store.get_skill_stats(sid)
                print(f"  {sid}: worse_rate={stats['worse_rate']:.0%} ({stats['total']}条反馈)")
        else:
            print("✅ 无标记技巧（可能反馈数据不足）")
        return

    if "--user" in sys.argv:
        idx = sys.argv.index("--user")
        user_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "test_user"
        stats = store.get_user_stats(user_id)
        print(f"用户 {user_id}:")
        print(f"  总反馈: {stats['total']}")
        print(f"  😊: {stats['better_rate']:.0%} 😐: {stats['same_rate']:.0%} 😕: {stats['worse_rate']:.0%}")
        return

    # 默认：全局报告
    stats = store.get_global_stats()
    print("📊 全局反馈报告")
    print(f"  总反馈: {stats['total']}")
    if stats['total'] > 0:
        print(f"  😊 更好: {stats['better_rate']:.0%} | 😐 差不多: {stats['same_rate']:.0%} | 😕 不如: {stats['worse_rate']:.0%}")
    else:
        print("  ⚠️ 暂无反馈数据")

    flagged = store.get_flagged_skills()
    if flagged:
        print(f"\n🚨 需关注的技巧: {len(flagged)} 个")
        for sid in flagged:
            s = store.get_skill_stats(sid)
            print(f"  {sid}: worse={s['worse_rate']:.0%} ({s['total']}条)")


if __name__ == "__main__":
    main()
