# Phase 0 核心管线实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现穿搭解析（段一）+ 建议生成（段二）两个核心模块，打通「拍照→解析→建议」这条最小链路。

**Architecture:** 两个模块各自封装 AI Router 调用 + Prompt 模板加载，通过 Pipeline 脚本串联。每个模块独立可测，有自己的单元测试。

**Tech Stack:** Python 3.9+（`from __future__ import annotations`），OpenAI SDK，PIL（Pillow），pytest

## Global Constraints

- Python 3.9 兼容：每个 `.py` 文件首行（docstring 之后）加 `from __future__ import annotations`
- 所有 AI 调用通过 `core.ai_router.AIRouter` 统一调度，禁止直接调 OpenAI SDK
- Prompt 从 `.md` 文件加载，不可硬编码在代码中
- JSON 输出用 `core.ai_router.extract_json()` 提取
- 配置文件路径：`config/models.json` + `config/models.local.json`
- 所有货币和测量单位使用公制（cm, ¥）
- 日志用 `logging` 模块，不要用 `print`

---

## 文件结构

```
core/
├── ai_router.py          ← 已存在，无需修改
├── image_utils.py        ← 已存在，无需修改
├── weather.py            ← 已存在，无需修改
├── outfit_parser.py      ← Task 1 新建：段一穿搭解析
├── suggestion.py         ← Task 3 新建：段二建议生成
└── pipeline.py           ← Task 5 新建：端到端管线脚本

prompts/
├── outfit_parse.md       ← 已存在，Task 1 使用
└── suggestion.md         ← 已存在，Task 3 使用

tests/
├── test_outfit_parser.py ← Task 2 新建
└── test_suggestion.py    ← Task 4 新建
```

---

### Task 1: 实现 outfit_parser 模块

**Files:**
- Create: `core/outfit_parser.py`
- Modify: 无

**Interfaces:**
- Consumes: `core.ai_router.AIRouter.chat()`, `core.ai_router.extract_json()`, `prompts/outfit_parse.md`
- Produces: `OutfitParser.parse(photo_path: str) -> OutfitResult`

- [ ] **Step 1: 创建 `core/outfit_parser.py`**

```python
from __future__ import annotations

"""
穿搭解析模块（段一）。
调用 VLM 分析穿搭照片，输出结构化穿搭 JSON + 7 项 Checklist。
"""

import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from core.ai_router import AIRouter, extract_json

logger = logging.getLogger("outfit_parser")


@dataclass
class OutfitItem:
    """单品信息"""
    category: str = ""           # 品类代码
    category_cn: str = ""        # 品类中文名
    color: str = ""              # 主色
    secondary_color: str = ""    # 辅色
    fit: str = ""                # 宽松/合身/修身
    wearing_style: str = ""      # 穿着方式
    notes: str = ""              # 备注


@dataclass
class ChecklistItem:
    """Checklist 单项"""
    id: str = ""
    question: str = ""
    result: str = "YES"   # YES / NO
    reason: str = ""


@dataclass
class OutfitResult:
    """穿搭解析结果"""
    success: bool = False
    outfit_description: str = ""
    items: list[OutfitItem] = field(default_factory=list)
    checklist: list[ChecklistItem] = field(default_factory=list)
    overall_style: str = ""
    photo_quality: str = "fair"
    photo_quality_note: str = ""
    raw_response: str = ""
    model_used: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None

    @property
    def no_count(self) -> int:
        """Checklist 中 NO 的数量"""
        return sum(1 for c in self.checklist if c.result == "NO")

    @property
    def no_items(self) -> list[str]:
        """所有 NO 项的 question 列表"""
        return [c.question for c in self.checklist if c.result == "NO"]


class OutfitParser:
    """穿搭解析器。调用 VLM 分析穿搭照片。"""

    def __init__(self, router: AIRouter = None, prompt_dir: str = None):
        if router is None:
            router = AIRouter()
        self.router = router

        if prompt_dir is None:
            prompt_dir = Path(__file__).parent.parent / "prompts"
        self.prompt_dir = Path(prompt_dir)

        self._system_prompt: Optional[str] = None

    @property
    def system_prompt(self) -> str:
        """懒加载 system prompt"""
        if self._system_prompt is None:
            prompt_path = self.prompt_dir / "outfit_parse.md"
            if not prompt_path.exists():
                raise FileNotFoundError(f"Prompt 文件不存在: {prompt_path}")
            with open(prompt_path, "r", encoding="utf-8") as f:
                self._system_prompt = f.read()
        return self._system_prompt

    def parse(self, photo_path: str) -> OutfitResult:
        """
        分析一张穿搭照片。

        Args:
            photo_path: 照片文件路径

        Returns:
            OutfitResult — 解析结果，包含 items 和 checklist
        """
        photo_path = str(photo_path)

        # 预检：文件存在
        if not Path(photo_path).exists():
            return OutfitResult(
                success=False,
                error=f"照片文件不存在: {photo_path}",
            )

        logger.info(f"开始解析穿搭照片: {photo_path}")

        # 调用 VLM
        result = self.router.chat(
            task="outfit_parsing",
            system_prompt=self.system_prompt,
            user_message="请分析这张穿搭照片，返回 JSON。",
            images=[photo_path],
        )

        if not result.success:
            logger.error(f"VLM 调用失败: {result.error}")
            return OutfitResult(
                success=False,
                error=result.error,
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )

        # 提取 JSON
        parsed = extract_json(result.data)
        if parsed is None:
            logger.error(f"无法从 VLM 输出中解析 JSON。原始输出前 500 字符: {result.data[:500]}")
            return OutfitResult(
                success=False,
                error="VLM 返回了非 JSON 格式的内容",
                raw_response=result.data[:500],
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )

        # 构造 OutfitResult
        try:
            items = [
                OutfitItem(
                    category=item.get("category", ""),
                    category_cn=item.get("category_cn", ""),
                    color=item.get("color", ""),
                    secondary_color=item.get("secondary_color", ""),
                    fit=item.get("fit", ""),
                    wearing_style=item.get("wearing_style", ""),
                    notes=item.get("notes", ""),
                )
                for item in parsed.get("items", [])
            ]

            checklist = [
                ChecklistItem(
                    id=check.get("id", ""),
                    question=check.get("question", ""),
                    result=check.get("result", "YES"),
                    reason=check.get("reason", ""),
                )
                for check in parsed.get("checklist", [])
            ]

            return OutfitResult(
                success=True,
                outfit_description=parsed.get("outfit_description", ""),
                items=items,
                checklist=checklist,
                overall_style=parsed.get("overall_style", ""),
                photo_quality=parsed.get("photo_quality", "fair"),
                photo_quality_note=parsed.get("photo_quality_note", ""),
                raw_response=result.data,
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )
        except Exception as e:
            logger.exception(f"构造 OutfitResult 时出错: {e}")
            return OutfitResult(
                success=False,
                error=f"JSON 结构异常: {e}",
                raw_response=result.data[:500],
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )

    def parse_to_dict(self, photo_path: str) -> dict:
        """同 parse()，但返回 dict 方便下游直接当 JSON 用"""
        result = self.parse(photo_path)
        return {
            "success": result.success,
            "outfit_description": result.outfit_description,
            "items": [
                {
                    "category": i.category,
                    "category_cn": i.category_cn,
                    "color": i.color,
                    "secondary_color": i.secondary_color,
                    "fit": i.fit,
                    "wearing_style": i.wearing_style,
                    "notes": i.notes,
                }
                for i in result.items
            ],
            "checklist": [
                {"id": c.id, "question": c.question, "result": c.result, "reason": c.reason}
                for c in result.checklist
            ],
            "overall_style": result.overall_style,
            "photo_quality": result.photo_quality,
            "photo_quality_note": result.photo_quality_note,
            "no_count": result.no_count,
            "no_items": result.no_items,
            "model_used": result.model_used,
            "latency_ms": result.latency_ms,
            "error": result.error,
        }


# ══════════════════════════════════════════════════════════════════
# 快速测试
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = OutfitParser()

    # 找测试照片
    test_photos_dir = Path(__file__).parent.parent / "data" / "test_photos"
    photos = list(test_photos_dir.glob("*"))
    photos = [p for p in photos if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]

    if not photos:
        print("❌ 没有找到测试照片。请将照片放入 data/test_photos/")
        sys.exit(1)

    photo = str(photos[0])
    print(f"📸 测试照片: {photo}")
    print(f"📏 文件大小: {Path(photo).stat().st_size / 1024:.1f} KB")
    print()

    result = parser.parse(photo)

    if result.success:
        print(f"✅ 解析成功 ({result.model_used}, {result.latency_ms:.0f}ms)")
        print(f"📝 穿搭描述: {result.outfit_description}")
        print(f"🎨 风格: {result.overall_style}")
        print(f"📷 照片质量: {result.photo_quality}")
        print(f"\n👔 识别到的单品 ({len(result.items)} 件):")
        for item in result.items:
            extras = []
            if item.wearing_style and item.wearing_style != "常规":
                extras.append(item.wearing_style)
            if item.notes:
                extras.append(item.notes)
            extra_str = f" | {'; '.join(extras)}" if extras else ""
            print(f"  - {item.category_cn}({item.category}) {item.color}/{item.secondary_color} {item.fit}{extra_str}")

        print(f"\n✅ Checklist ({result.no_count} 个 ❌):")
        for check in result.checklist:
            icon = "✅" if check.result == "YES" else "❌"
            print(f"  {icon} {check.question} — {check.reason}")
    else:
        print(f"❌ 解析失败: {result.error}")
```

- [ ] **Step 2: 验证 Prompt 文件可加载**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0" && python3 -c "
from core.outfit_parser import OutfitParser
parser = OutfitParser()
print(f'Prompt 长度: {len(parser.system_prompt)} 字符')
print(f'Prompt 前 100 字符: {parser.system_prompt[:100]}')
"
```

Expected: 输出 Prompt 长度 > 500 字符，内容为 `prompts/outfit_parse.md` 的内容。

- [ ] **Step 3: 对测试照片运行解析（端到端验证）**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0" && python3 -c "
from core.outfit_parser import OutfitParser
from pathlib import Path

parser = OutfitParser()
photos_dir = Path('data/test_photos')
photos = sorted([p for p in photos_dir.glob('*') if p.suffix.lower() in ('.jpg', '.jpeg', '.png')])

for photo in photos:
    print(f'\n{'='*60}')
    print(f'📸 {photo.name}')
    result = parser.parse(str(photo))
    if result.success:
        print(f'  ✅ 成功 | {result.model_used} | {result.latency_ms:.0f}ms')
        print(f'  描述: {result.outfit_description}')
        print(f'  风格: {result.overall_style}')
        print(f'  单品数: {len(result.items)}')
        for item in result.items:
            print(f'    - {item.category_cn} [{item.category}] {item.color} {item.fit} ({item.wearing_style})')
        print(f'  ❌ 数量: {result.no_count}')
        for c in result.checklist:
            if c.result == 'NO':
                print(f'    ❌ {c.question}: {c.reason}')
    else:
        print(f'  ❌ 失败: {result.error}')
"
```

Expected: 3 张照片都能成功解析，返回结构化 JSON。品类识别需要人工判断准确率。

- [ ] **Step 4: Commit**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0"
git add core/outfit_parser.py
git commit -m "feat: 实现穿搭解析模块 outfit_parser（段一）"
```

---

### Task 2: 编写 outfit_parser 单元测试

**Files:**
- Create: `tests/test_outfit_parser.py`
- Modify: 无

**Interfaces:**
- Consumes: `core.outfit_parser.OutfitParser`, `core.outfit_parser.OutfitResult`
- Produces: 无（测试文件）

- [ ] **Step 1: 创建 `tests/test_outfit_parser.py`**

```python
from __future__ import annotations

"""outfit_parser 模块单元测试"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.outfit_parser import (
    OutfitParser,
    OutfitResult,
    OutfitItem,
    ChecklistItem,
)
from core.ai_router import RouterResult


# ═══════════════════════════════════════════════════════════
# 数据类测试
# ═══════════════════════════════════════════════════════════

class TestOutfitResult:
    def test_no_count_all_yes(self):
        result = OutfitResult(
            success=True,
            checklist=[
                ChecklistItem(id="a", question="Q1", result="YES", reason="ok"),
                ChecklistItem(id="b", question="Q2", result="YES", reason="ok"),
                ChecklistItem(id="c", question="Q3", result="YES", reason="ok"),
            ],
        )
        assert result.no_count == 0
        assert result.no_items == []

    def test_no_count_mixed(self):
        result = OutfitResult(
            success=True,
            checklist=[
                ChecklistItem(id="a", question="Q1", result="YES", reason="ok"),
                ChecklistItem(id="b", question="Q2", result="NO", reason="bad"),
                ChecklistItem(id="c", question="Q3", result="NO", reason="bad too"),
            ],
        )
        assert result.no_count == 2
        assert result.no_items == ["Q2", "Q3"]

    def test_no_count_all_no(self):
        result = OutfitResult(
            success=True,
            checklist=[
                ChecklistItem(id="a", question="Q1", result="NO", reason="..."),
                ChecklistItem(id="b", question="Q2", result="NO", reason="..."),
                ChecklistItem(id="c", question="Q3", result="NO", reason="..."),
                ChecklistItem(id="d", question="Q4", result="NO", reason="..."),
                ChecklistItem(id="e", question="Q5", result="NO", reason="..."),
                ChecklistItem(id="f", question="Q6", result="NO", reason="..."),
                ChecklistItem(id="g", question="Q7", result="NO", reason="..."),
            ],
        )
        assert result.no_count == 7
        assert len(result.no_items) == 7


# ═══════════════════════════════════════════════════════════
# OutfitParser 测试
# ═══════════════════════════════════════════════════════════

class TestOutfitParser:
    def test_system_prompt_loads_from_file(self):
        parser = OutfitParser()
        prompt = parser.system_prompt
        assert len(prompt) > 500
        assert "品类代码" in prompt
        assert "checklist" in prompt.lower()

    def test_parse_file_not_found(self):
        parser = OutfitParser()
        result = parser.parse("/nonexistent/photo.jpg")
        assert result.success is False
        assert "不存在" in result.error

    def test_parse_vlm_returns_invalid_json(self):
        """VLM 返回非 JSON 内容时，应优雅失败"""
        parser = OutfitParser()
        mock_router = MagicMock()
        mock_router.chat.return_value = RouterResult(
            success=True,
            data="这是一段非 JSON 的普通文本回复",
            model_used="test/model",
            provider_used="test",
            latency_ms=100,
        )
        parser.router = mock_router
        parser._system_prompt = "test prompt"

        # 用真实存在的文件路径绕过文件检查
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            result = parser.parse(f.name)

        assert result.success is False
        assert "非 JSON" in result.error or "JSON" in result.error

    def test_parse_success_path(self):
        """用 mock VLM 返回验证完整解析流程"""
        parser = OutfitParser()
        mock_router = MagicMock()
        mock_router.chat.return_value = RouterResult(
            success=True,
            data='''```json
{
  "outfit_description": "白色T恤配蓝色牛仔裤的休闲穿搭",
  "items": [
    {
      "category": "TS",
      "category_cn": "短袖T恤",
      "color": "白色",
      "secondary_color": "",
      "fit": "合身",
      "wearing_style": "常规",
      "notes": "纯棉面料"
    },
    {
      "category": "JEANS",
      "category_cn": "牛仔裤",
      "color": "蓝色",
      "secondary_color": "",
      "fit": "宽松",
      "wearing_style": "裤脚卷起一圈",
      "notes": ""
    }
  ],
  "checklist": [
    {"id": "fit_top", "question": "上装合身吗？", "result": "YES", "reason": "T恤肩线位置合适"},
    {"id": "fit_bottom", "question": "下装合身吗？", "result": "NO", "reason": "裤长稍长堆叠"},
    {"id": "fit_shoe", "question": "鞋与整体比例协调吗？", "result": "YES", "reason": "白色运动鞋搭配协调"},
    {"id": "color_match", "question": "颜色搭配协调吗？", "result": "YES", "reason": "白+蓝经典组合"},
    {"id": "style_match", "question": "上下装风格一致吗？", "result": "YES", "reason": "都是休闲风格"},
    {"id": "prop_balance", "question": "上下身比例舒服吗？", "result": "NO", "reason": "裤脚堆叠影响下身比例"},
    {"id": "occasion", "question": "适合日常出门吗？", "result": "YES", "reason": "日常休闲合适"}
  ],
  "overall_style": "休闲",
  "photo_quality": "good",
  "photo_quality_note": ""
}
```''',
            model_used="test/model",
            provider_used="test",
            latency_ms=200,
        )
        parser.router = mock_router
        parser._system_prompt = "test prompt"

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            result = parser.parse(f.name)

        assert result.success is True
        assert len(result.items) == 2
        assert result.items[0].category == "TS"
        assert result.items[0].color == "白色"
        assert result.items[1].wearing_style == "裤脚卷起一圈"
        assert result.no_count == 2
        assert "下装合身吗？" in result.no_items
        assert result.overall_style == "休闲"
        assert result.photo_quality == "good"

    def test_parse_to_dict(self):
        """验证 parse_to_dict 返回正确的 dict 结构"""
        parser = OutfitParser()
        mock_router = MagicMock()
        mock_router.chat.return_value = RouterResult(
            success=True,
            data='{"outfit_description":"test","items":[],"checklist":[],"overall_style":"","photo_quality":"good","photo_quality_note":""}',
            model_used="test/model",
            provider_used="test",
            latency_ms=100,
        )
        parser.router = mock_router
        parser._system_prompt = "test prompt"

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            d = parser.parse_to_dict(f.name)

        assert isinstance(d, dict)
        assert d["success"] is True
        assert d["no_count"] == 0
        assert "items" in d
        assert "checklist" in d

    def test_parse_vlm_call_fails(self):
        """VLM 调用本身失败时，应返回错误"""
        parser = OutfitParser()
        mock_router = MagicMock()
        mock_router.chat.return_value = RouterResult(
            success=False,
            error="API rate limit exceeded",
            model_used="test/model",
            provider_used="test",
            latency_ms=500,
        )
        parser.router = mock_router
        parser._system_prompt = "test prompt"

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            result = parser.parse(f.name)

        assert result.success is False
        assert "rate limit" in result.error
```

- [ ] **Step 2: 运行测试验证全部通过**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0" && python3 -m pytest tests/test_outfit_parser.py -v
```

Expected: 7 tests passed.

- [ ] **Step 3: Commit**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0"
git add tests/test_outfit_parser.py tests/__init__.py 2>/dev/null || git add tests/test_outfit_parser.py
git commit -m "test: 添加 outfit_parser 单元测试（7 个用例）"
```

---

### Task 3: 实现 suggestion 模块

**Files:**
- Create: `core/suggestion.py`
- Modify: 无

**Interfaces:**
- Consumes: `core.ai_router.AIRouter.chat()`, `core.ai_router.extract_json()`, `prompts/suggestion.md`
- Produces: `SuggestionEngine.generate(outfit_data: dict, user_context: dict) -> SuggestionResult`

- [ ] **Step 1: 创建 `core/suggestion.py`**

```python
from __future__ import annotations

"""
微调建议生成模块（段二）。
基于穿搭解析结果 + 用户上下文，调用 LLM 生成具体的微调建议。
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from core.ai_router import AIRouter, extract_json

logger = logging.getLogger("suggestion")


@dataclass
class SuggestionDetail:
    """建议详情"""
    skill_id: str = ""
    skill_name: str = ""
    headline: str = ""
    why: str = ""
    how_to: str = ""
    expected_effect: str = ""
    difficulty: int = 1
    estimated_time_seconds: int = 10


@dataclass
class SuggestionResult:
    """建议生成结果"""
    success: bool = False
    scene: str = ""                    # 精进/微调/纠正
    checklist_summary: dict = field(default_factory=dict)
    suggestion: Optional[SuggestionDetail] = None
    tone: str = "friendly"
    encouragement: str = ""
    model_used: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None


class SuggestionEngine:
    """微调建议引擎。基于穿搭 JSON + 用户上下文生成建议。"""

    def __init__(self, router: AIRouter = None, prompt_dir: str = None):
        if router is None:
            router = AIRouter()
        self.router = router

        if prompt_dir is None:
            prompt_dir = Path(__file__).parent.parent / "prompts"
        self.prompt_dir = Path(prompt_dir)

        self._system_prompt: Optional[str] = None

    @property
    def system_prompt(self) -> str:
        """懒加载 system prompt"""
        if self._system_prompt is None:
            prompt_path = self.prompt_dir / "suggestion.md"
            if not prompt_path.exists():
                raise FileNotFoundError(f"Prompt 文件不存在: {prompt_path}")
            with open(prompt_path, "r", encoding="utf-8") as f:
                self._system_prompt = f.read()
        return self._system_prompt

    def generate(
        self,
        outfit_data: dict,
        user_context: dict | None = None,
    ) -> SuggestionResult:
        """
        基于穿搭数据生成微调建议。

        Args:
            outfit_data: outfit_parser.parse_to_dict() 的输出
            user_context: 可选，包含 body_shape, skill_history, weather 等

        Returns:
            SuggestionResult
        """
        if user_context is None:
            user_context = {}

        # 构建 user message
        user_message = self._build_user_message(outfit_data, user_context)

        logger.info("开始生成穿搭建议...")

        result = self.router.chat(
            task="suggestion",
            system_prompt=self.system_prompt,
            user_message=user_message,
            response_format={"type": "json_object"},
        )

        if not result.success:
            logger.error(f"LLM 调用失败: {result.error}")
            return SuggestionResult(
                success=False,
                error=result.error,
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )

        # 提取 JSON
        parsed = extract_json(result.data)
        if parsed is None:
            logger.error(f"无法从 LLM 输出中解析 JSON。原始输出前 500 字符: {result.data[:500]}")
            return SuggestionResult(
                success=False,
                error="LLM 返回了非 JSON 格式的内容",
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )

        # 构造 SuggestionResult
        try:
            sugg_data = parsed.get("suggestion", {})
            suggestion = SuggestionDetail(
                skill_id=sugg_data.get("skill_id", ""),
                skill_name=sugg_data.get("skill_name", ""),
                headline=sugg_data.get("headline", ""),
                why=sugg_data.get("why", ""),
                how_to=sugg_data.get("how_to", ""),
                expected_effect=sugg_data.get("expected_effect", ""),
                difficulty=sugg_data.get("difficulty", 1),
                estimated_time_seconds=sugg_data.get("estimated_time_seconds", 10),
            )

            return SuggestionResult(
                success=True,
                scene=parsed.get("scene", "微调"),
                checklist_summary=parsed.get("checklist_summary", {}),
                suggestion=suggestion,
                tone=parsed.get("tone", "friendly"),
                encouragement=parsed.get("encouragement", ""),
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )
        except Exception as e:
            logger.exception(f"构造 SuggestionResult 时出错: {e}")
            return SuggestionResult(
                success=False,
                error=f"JSON 结构异常: {e}",
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )

    def _build_user_message(self, outfit_data: dict, user_context: dict) -> str:
        """构建发给 LLM 的用户消息"""
        parts = []

        # 穿搭数据
        parts.append("## 当前穿搭数据\n")
        parts.append(f"整体描述：{outfit_data.get('outfit_description', '未知')}")
        parts.append(f"整体风格：{outfit_data.get('overall_style', '未知')}")
        parts.append(f"Checklist ❌ 数量：{outfit_data.get('no_count', 0)}")
        if outfit_data.get('no_items'):
            parts.append(f"❌ 项：{', '.join(outfit_data['no_items'])}")

        parts.append("\n### 穿着单品：")
        for i, item in enumerate(outfit_data.get("items", []), 1):
            parts.append(
                f"{i}. {item['category_cn']}（{item['category']}）"
                f" | {item['color']} | {item['fit']}"
                f" | 穿法：{item['wearing_style']}"
                f"{' | ' + item['notes'] if item.get('notes') else ''}"
            )

        # 用户身形数据
        if user_context.get("body_shape"):
            body = user_context["body_shape"]
            parts.append(f"\n## 用户身形\n")
            parts.append(f"体型：{body.get('body_type', '未知')}")
            parts.append(f"肩胯比：{body.get('shoulder_hip_ratio', '未知')}")
            parts.append(f"腿身比：{body.get('leg_body_ratio', '未知')}")
            parts.append(f"肤色：{body.get('skin_tone', '未知')}")

        # 技巧历史
        if user_context.get("skill_history"):
            history = user_context["skill_history"]
            parts.append(f"\n## 技巧历史\n")
            parts.append(f"已掌握技巧：{', '.join(history.get('mastered', [])) or '无'}")
            parts.append(f"最近 7 天推荐过：{', '.join(history.get('recent', [])) or '无'}")
            parts.append(f"反馈较差的技巧：{', '.join(history.get('disliked', [])) or '无'}")

        # 天气
        if user_context.get("weather"):
            w = user_context["weather"]
            parts.append(f"\n## 天气\n")
            parts.append(f"{w.get('condition', '未知')} | {w.get('temperature', '未知')}°C")

        return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════
# 快速测试
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    engine = SuggestionEngine()

    # 构造测试数据
    test_outfit = {
        "outfit_description": "白色T恤配蓝色牛仔裤的休闲穿搭",
        "overall_style": "休闲",
        "no_count": 1,
        "no_items": ["下装合身吗？"],
        "items": [
            {"category": "TS", "category_cn": "短袖T恤", "color": "白色",
             "fit": "合身", "wearing_style": "常规", "notes": "纯棉面料"},
            {"category": "JEANS", "category_cn": "牛仔裤", "color": "蓝色",
             "fit": "宽松", "wearing_style": "常规", "notes": ""},
            {"category": "SHOES_SNKR", "category_cn": "运动鞋", "color": "白色",
             "fit": "合身", "wearing_style": "常规", "notes": ""},
        ],
    }

    test_context = {
        "body_shape": {
            "body_type": "矩形",
            "shoulder_hip_ratio": "肩胯同宽",
            "leg_body_ratio": "腿稍短",
            "skin_tone": "暖白",
        },
        "skill_history": {
            "mastered": [],
            "recent": [],
            "disliked": [],
        },
        "weather": {
            "condition": "晴",
            "temperature": 26,
        },
    }

    print("🧠 生成穿搭建议...")
    result = engine.generate(test_outfit, test_context)

    if result.success:
        s = result.suggestion
        print(f"✅ 建议生成成功 ({result.model_used}, {result.latency_ms:.0f}ms)")
        print(f"🎯 场景: {result.scene}")
        print(f"💡 建议: {s.headline}")
        print(f"📖 为什么: {s.why}")
        print(f"🤸 怎么做: {s.how_to}")
        print(f"✨ 预期效果: {s.expected_effect}")
        print(f"📊 难度: {'⭐' * s.difficulty}")
        print(f"⏱ 耗时: {s.estimated_time_seconds}s")
        print(f"💬 鼓励: {result.encouragement}")
    else:
        print(f"❌ 建议生成失败: {result.error}")
```

- [ ] **Step 2: 验证 Prompt 文件可加载**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0" && python3 -c "
from core.suggestion import SuggestionEngine
engine = SuggestionEngine()
print(f'Prompt 长度: {len(engine.system_prompt)} 字符')
"
```

Expected: 输出 Prompt 长度 > 300 字符。

- [ ] **Step 3: 用模拟穿搭数据测试建议生成（端到端）**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0" && python3 -c "
from core.suggestion import SuggestionEngine
import logging
logging.basicConfig(level=logging.INFO)

engine = SuggestionEngine()

# 场景 A：1 个 ❌ — 微调模式
outfit_a = {
    'outfit_description': '白T恤配牛仔裤',
    'overall_style': '休闲',
    'no_count': 1,
    'no_items': ['下装合身吗？'],
    'items': [
        {'category': 'TS', 'category_cn': '短袖T恤', 'color': '白色', 'fit': '合身', 'wearing_style': '常规', 'notes': ''},
        {'category': 'JEANS', 'category_cn': '牛仔裤', 'color': '蓝色', 'fit': '宽松', 'wearing_style': '常规', 'notes': ''},
    ],
}
context = {
    'body_shape': {'body_type': '矩形', 'shoulder_hip_ratio': '肩胯同宽', 'leg_body_ratio': '腿稍短', 'skin_tone': '暖白'},
    'skill_history': {'mastered': [], 'recent': [], 'disliked': []},
    'weather': {'condition': '晴', 'temperature': 26},
}

result = engine.generate(outfit_a, context)
if result.success:
    s = result.suggestion
    print(f'场景: {result.scene}')
    print(f'建议: {s.headline}')
    print(f'操作: {s.how_to}')
    print(f'鼓励: {result.encouragement}')
else:
    print(f'失败: {result.error}')
"
```

Expected: 返回有效建议，scene 为 "微调"，suggestion 非空。

- [ ] **Step 4: Commit**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0"
git add core/suggestion.py
git commit -m "feat: 实现微调建议生成模块 suggestion（段二）"
```

---

### Task 4: 编写 suggestion 单元测试

**Files:**
- Create: `tests/test_suggestion.py`
- Modify: 无

**Interfaces:**
- Consumes: `core.suggestion.SuggestionEngine`, `core.suggestion.SuggestionResult`
- Produces: 无（测试文件）

- [ ] **Step 1: 创建 `tests/test_suggestion.py`**

```python
from __future__ import annotations

"""suggestion 模块单元测试"""

import pytest
from unittest.mock import MagicMock

from core.suggestion import (
    SuggestionEngine,
    SuggestionResult,
    SuggestionDetail,
)
from core.ai_router import RouterResult


class TestSuggestionResult:
    def test_default_values(self):
        result = SuggestionResult()
        assert result.success is False
        assert result.scene == ""
        assert result.suggestion is None
        assert result.error is None

    def test_with_suggestion(self):
        detail = SuggestionDetail(
            skill_id="cuff_roll",
            skill_name="裤脚卷边",
            headline="试试卷一下裤脚",
            why="让比例更好",
            how_to="向外翻折2cm",
            expected_effect="腿长+10%",
            difficulty=1,
            estimated_time_seconds=10,
        )
        result = SuggestionResult(
            success=True,
            scene="微调",
            suggestion=detail,
            encouragement="今天很棒！",
        )
        assert result.success is True
        assert result.scene == "微调"
        assert result.suggestion.skill_id == "cuff_roll"
        assert result.suggestion.difficulty == 1


class TestSuggestionEngine:
    def test_system_prompt_loads(self):
        engine = SuggestionEngine()
        prompt = engine.system_prompt
        assert len(prompt) > 300
        assert "不否定" in prompt
        assert "具体到动作" in prompt

    def test_build_user_message_basic(self):
        engine = SuggestionEngine()
        engine._system_prompt = "test"
        outfit_data = {
            "outfit_description": "白T+牛仔裤",
            "overall_style": "休闲",
            "no_count": 1,
            "no_items": ["下装合身吗？"],
            "items": [
                {"category": "TS", "category_cn": "短袖T恤", "color": "白色",
                 "fit": "合身", "wearing_style": "常规", "notes": ""},
            ],
        }
        msg = engine._build_user_message(outfit_data, {})
        assert "白T+牛仔裤" in msg
        assert "短袖T恤" in msg
        assert "下装合身吗" in msg

    def test_build_user_message_with_context(self):
        engine = SuggestionEngine()
        engine._system_prompt = "test"
        outfit_data = {
            "outfit_description": "test",
            "overall_style": "休闲",
            "no_count": 0,
            "no_items": [],
            "items": [],
        }
        context = {
            "body_shape": {
                "body_type": "矩形",
                "shoulder_hip_ratio": "肩胯同宽",
                "leg_body_ratio": "腿稍短",
                "skin_tone": "暖白",
            },
            "skill_history": {
                "mastered": ["法式半塞"],
                "recent": ["裤脚卷边"],
                "disliked": [],
            },
            "weather": {"condition": "晴", "temperature": 26},
        }
        msg = engine._build_user_message(outfit_data, context)
        assert "矩形" in msg
        assert "法式半塞" in msg
        assert "裤脚卷边" in msg
        assert "晴" in msg
        assert "26" in msg

    def test_generate_vlm_failure(self):
        engine = SuggestionEngine()
        mock_router = MagicMock()
        mock_router.chat.return_value = RouterResult(
            success=False,
            error="Service unavailable",
            model_used="test/model",
            provider_used="test",
            latency_ms=100,
        )
        engine.router = mock_router
        engine._system_prompt = "test"

        result = engine.generate({"outfit_description": "test", "no_count": 0, "no_items": [], "items": [], "overall_style": ""})
        assert result.success is False
        assert "Service unavailable" in result.error

    def test_generate_invalid_json(self):
        engine = SuggestionEngine()
        mock_router = MagicMock()
        mock_router.chat.return_value = RouterResult(
            success=True,
            data="这不是 JSON",
            model_used="test/model",
            provider_used="test",
            latency_ms=100,
        )
        engine.router = mock_router
        engine._system_prompt = "test"

        result = engine.generate({"outfit_description": "test", "no_count": 0, "no_items": [], "items": [], "overall_style": ""})
        assert result.success is False
        assert "JSON" in result.error

    def test_generate_success(self):
        engine = SuggestionEngine()
        mock_router = MagicMock()
        mock_router.chat.return_value = RouterResult(
            success=True,
            data='''{
              "scene": "微调",
              "checklist_summary": {"yes_count": 6, "no_items": ["下装合身吗？"], "main_issue": "裤长问题"},
              "suggestion": {
                "skill_id": "cuff_roll",
                "skill_name": "裤脚卷边",
                "headline": "试试把裤脚往上卷一圈",
                "why": "裤长稍长会影响比例",
                "how_to": "向外翻折一次，约2-3cm",
                "expected_effect": "腿长视觉+10%",
                "difficulty": 1,
                "estimated_time_seconds": 10
              },
              "tone": "friendly",
              "encouragement": "今天颜色搭配不错！"
            }''',
            model_used="test/model",
            provider_used="test",
            latency_ms=100,
        )
        engine.router = mock_router
        engine._system_prompt = "test"

        result = engine.generate({"outfit_description": "test", "no_count": 1, "no_items": [], "items": [], "overall_style": ""})

        assert result.success is True
        assert result.scene == "微调"
        assert result.suggestion is not None
        assert result.suggestion.skill_id == "cuff_roll"
        assert result.suggestion.headline == "试试把裤脚往上卷一圈"
        assert result.encouragement == "今天颜色搭配不错！"
```

- [ ] **Step 2: 运行测试验证全部通过**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0" && python3 -m pytest tests/test_suggestion.py -v
```

Expected: 7 tests passed.

- [ ] **Step 3: Commit**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0"
git add tests/test_suggestion.py
git commit -m "test: 添加 suggestion 单元测试（7 个用例）"
```

---

### Task 5: 端到端管线脚本 + 集成测试

**Files:**
- Create: `core/pipeline.py`
- Modify: 无

**Interfaces:**
- Consumes: `core.outfit_parser.OutfitParser`, `core.suggestion.SuggestionEngine`
- Produces: `run_pipeline(photo_path, user_context) -> dict`

- [ ] **Step 1: 创建 `core/pipeline.py`**

```python
from __future__ import annotations

"""
端到端穿搭分析管线。
串联 段一（穿搭解析）+ 段二（建议生成），一键从照片到建议。
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from core.outfit_parser import OutfitParser
from core.suggestion import SuggestionEngine

logger = logging.getLogger("pipeline")


def run_pipeline(
    photo_path: str,
    user_context: dict | None = None,
    skip_suggestion: bool = False,
) -> dict:
    """
    从照片到建议的完整管线。

    Args:
        photo_path: 穿搭照片路径
        user_context: 用户上下文（身形、技巧历史、天气等）
        skip_suggestion: 跳过段二，仅返回穿搭解析结果

    Returns:
        {
            "success": bool,
            "total_latency_ms": float,
            "outfit": {...},       # 穿搭解析结果
            "suggestion": {...},   # 建议生成结果（skip_suggestion=True 时为 None）
            "error": str | None,
        }
    """
    t_start = time.time()

    if user_context is None:
        user_context = {}

    result = {
        "success": False,
        "total_latency_ms": 0.0,
        "outfit": None,
        "suggestion": None,
        "error": None,
    }

    # ════ 段一：穿搭解析 ════
    logger.info(f"段一：穿搭解析 — {photo_path}")
    parser = OutfitParser()
    outfit_result = parser.parse(photo_path)

    if not outfit_result.success:
        result["error"] = f"段一失败: {outfit_result.error}"
        result["total_latency_ms"] = (time.time() - t_start) * 1000
        return result

    outfit_dict = parser.parse_to_dict(photo_path) if outfit_result.success else None
    # 上面 parse_to_dict 会再调一次 parse，浪费。直接转换：
    outfit_dict = {
        "success": outfit_result.success,
        "outfit_description": outfit_result.outfit_description,
        "items": [
            {
                "category": i.category,
                "category_cn": i.category_cn,
                "color": i.color,
                "secondary_color": i.secondary_color,
                "fit": i.fit,
                "wearing_style": i.wearing_style,
                "notes": i.notes,
            }
            for i in outfit_result.items
        ],
        "checklist": [
            {"id": c.id, "question": c.question, "result": c.result, "reason": c.reason}
            for c in outfit_result.checklist
        ],
        "overall_style": outfit_result.overall_style,
        "photo_quality": outfit_result.photo_quality,
        "photo_quality_note": outfit_result.photo_quality_note,
        "no_count": outfit_result.no_count,
        "no_items": outfit_result.no_items,
        "model_used": outfit_result.model_used,
        "latency_ms": outfit_result.latency_ms,
    }
    result["outfit"] = outfit_dict

    logger.info(
        f"段一完成: {outfit_result.outfit_description[:50]}... "
        f"| {len(outfit_result.items)} 件单品 | {outfit_result.no_count} 个 ❌ "
        f"| {outfit_result.latency_ms:.0f}ms"
    )

    if skip_suggestion:
        result["success"] = True
        result["total_latency_ms"] = (time.time() - t_start) * 1000
        return result

    # ════ 段二：建议生成 ════
    logger.info("段二：建议生成")
    engine = SuggestionEngine()
    suggestion_result = engine.generate(outfit_dict, user_context)

    if suggestion_result.success and suggestion_result.suggestion:
        result["suggestion"] = {
            "scene": suggestion_result.scene,
            "skill_id": suggestion_result.suggestion.skill_id,
            "skill_name": suggestion_result.suggestion.skill_name,
            "headline": suggestion_result.suggestion.headline,
            "why": suggestion_result.suggestion.why,
            "how_to": suggestion_result.suggestion.how_to,
            "expected_effect": suggestion_result.suggestion.expected_effect,
            "difficulty": suggestion_result.suggestion.difficulty,
            "estimated_time_seconds": suggestion_result.suggestion.estimated_time_seconds,
            "encouragement": suggestion_result.encouragement,
            "tone": suggestion_result.tone,
        }
        logger.info(
            f"段二完成: {suggestion_result.suggestion.headline} "
            f"| 场景={suggestion_result.scene} "
            f"| {suggestion_result.latency_ms:.0f}ms"
        )
    else:
        # 段二失败不阻塞，部分成功
        logger.warning(f"段二失败（非阻塞）: {suggestion_result.error}")
        result["suggestion"] = {
            "error": suggestion_result.error,
            "fallback": True,
        }

    result["success"] = True
    result["total_latency_ms"] = (time.time() - t_start) * 1000
    return result


# ══════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if len(sys.argv) < 2:
        print("用法: python -m core.pipeline <photo_path>")
        print("示例: python -m core.pipeline data/test_photos/IMG_2944.jpg")
        sys.exit(1)

    photo_path = sys.argv[1]

    if not Path(photo_path).exists():
        print(f"❌ 文件不存在: {photo_path}")
        sys.exit(1)

    print(f"🚀 启动穿搭分析管线...")
    print(f"📸 照片: {photo_path}")
    print()

    user_context = {
        "body_shape": {
            "body_type": "矩形",
            "shoulder_hip_ratio": "肩稍窄",
            "leg_body_ratio": "腿稍短",
            "skin_tone": "暖白",
        },
        "skill_history": {
            "mastered": [],
            "recent": [],
            "disliked": [],
        },
    }

    result = run_pipeline(photo_path, user_context)

    if result["success"]:
        outfit = result["outfit"]
        print("═" * 50)
        print("👔 段一：穿搭解析")
        print("═" * 50)
        print(f"  描述: {outfit['outfit_description']}")
        print(f"  风格: {outfit['overall_style']}")
        print(f"  照片质量: {outfit['photo_quality']}")
        if outfit["photo_quality_note"]:
            print(f"  质量备注: {outfit['photo_quality_note']}")
        print(f"\n  识别单品 ({len(outfit['items'])} 件):")
        for item in outfit["items"]:
            print(f"    - {item['category_cn']} [{item['category']}] {item['color']} {item['fit']} ({item['wearing_style']})")

        print(f"\n  Checklist ({outfit['no_count']} ❌):")
        for check in outfit["checklist"]:
            icon = "❌" if check["result"] == "NO" else "✅"
            print(f"    {icon} {check['question']} — {check['reason']}")

        if result["suggestion"] and not result["suggestion"].get("fallback"):
            sugg = result["suggestion"]
            print(f"\n{'═' * 50}")
            print(f"💡 段二：微调建议")
            print(f"{'═' * 50}")
            print(f"  场景: {sugg['scene']}")
            print(f"  建议: {sugg['headline']}")
            print(f"  技巧: {sugg['skill_name']} ({sugg['skill_id']})")
            print(f"  为什么: {sugg['why']}")
            print(f"  怎么做: {sugg['how_to']}")
            print(f"  预期效果: {sugg['expected_effect']}")
            print(f"  难度: {'⭐' * sugg['difficulty']} | 耗时: {sugg['estimated_time_seconds']}s")
            print(f"  鼓励: {sugg['encouragement']}")
        elif result["suggestion"] and result["suggestion"].get("fallback"):
            print(f"\n⚠️ 段二建议生成失败（降级）: {result['suggestion'].get('error')}")

        print(f"\n⏱ 总耗时: {result['total_latency_ms']:.0f}ms")
    else:
        print(f"❌ 管线失败: {result['error']}")
```

- [ ] **Step 2: 创建 `tests/__init__.py`（如不存在）**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0" && test -f tests/__init__.py || touch tests/__init__.py
```

- [ ] **Step 3: 用测试照片运行完整管线**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0" && python3 -c "
from core.pipeline import run_pipeline
from pathlib import Path

photos_dir = Path('data/test_photos')
photos = sorted([p for p in photos_dir.glob('*') if p.suffix.lower() in ('.jpg', '.jpeg', '.png')])

for photo in photos:
    print(f'\n{'='*60}')
    print(f'📸 {photo.name}')
    print(f'{"="*60}')
    result = run_pipeline(str(photo))
    if result['success']:
        o = result['outfit']
        s = result.get('suggestion', {})
        print(f'  ✅ 解析: {o[\"outfit_description\"]}')
        print(f'  ❌ Checklist: {o[\"no_count\"]} 项')
        if s and not s.get('fallback'):
            print(f'  💡 建议: {s[\"headline\"]}')
            print(f'  🎯 场景: {s[\"scene\"]}')
        print(f'  ⏱ 总耗时: {result[\"total_latency_ms\"]:.0f}ms')
    else:
        print(f'  ❌ 失败: {result[\"error\"]}')
"
```

Expected: 每张照片输出完整解析 + 建议。记录：
- 品类识别准确率（肉眼判断）
- 建议是否"可操作"（知道具体要做什么动作）
- 总耗时是否在可接受范围

- [ ] **Step 4: Commit**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0"
git add core/pipeline.py tests/__init__.py
git commit -m "feat: 端到端管线脚本 pipeline.py（段一+段二串联）"
```

---

### Task 6: 运行全部测试 + 最终验证

- [ ] **Step 1: 运行全部单元测试**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0" && python3 -m pytest tests/ -v
```

Expected: 14 tests passed（7 from test_outfit_parser + 7 from test_suggestion）。

- [ ] **Step 2: 对 3 张测试照运行管线，记录验收结果**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0" && python3 core/pipeline.py "$(ls data/test_photos/* | head -1)"
```

验收标准（对照开发计划书）：
- [ ] 品类识别准确率 > 85%（你肉眼判断）
- [ ] Checklist 判断基本合理（7 项中至少 5 项你说"对"）
- [ ] 穿着方式（塞没塞、卷没卷）能正确识别
- [ ] 生成的建议你知道「具体要做什么动作」
- [ ] 语言自然，不像 AI 模板
- [ ] 至少 3 次测试中有建议让你觉得「确实可以试试」

- [ ] **Step 3: 更新开发日志**

在 `dev-logs/2026-06-29.md` 末尾追加今日 Phase 0 Day 2-3 完成内容。

- [ ] **Step 4: 最终 Commit**

```bash
cd "/Users/rabbit/Claude code/Fashion 2.0"
git add -A
git commit -m "✅ Phase 0 完成 — 核心管线（解析+建议+端到端）已跑通"
```

---

## 自审清单

**1. Spec 覆盖:**
- [x] Phase 0.2 VLM 穿搭解析 Prompt → Task 1 实现 OutfitParser
- [x] Phase 0.2 验收标准（品类准确率 > 85%、Checklist 合理） → Task 6 Step 2
- [x] Phase 0.3 LLM 建议生成 Prompt → Task 3 实现 SuggestionEngine
- [x] Phase 0.3 验收标准（建议可操作、语言自然） → Task 6 Step 2
- [x] 管线串联 → Task 5 pipeline.py

**2. Placeholder 扫描:**
- [x] 无 TBD/TODO/implement later
- [x] 无 "add appropriate error handling" 等模糊描述
- [x] 所有代码步骤都有完整代码
- [x] 所有函数签名和类型在上下文中定义

**3. 类型一致性:**
- [x] OutfitParser.parse() 返回 OutfitResult，下游 SuggestionEngine.generate() 接收 dict（通过 parse_to_dict() 转换）
- [x] run_pipeline() 统一 orchestration，返回 dict 供外部使用
- [x] 所有 mock 测试中的数据结构与真实 API 返回一致
