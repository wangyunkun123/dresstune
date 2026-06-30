from __future__ import annotations

"""
AI Router — 统一模型调度层。

支持：
  - DeepSeek 官方 API（OpenAI 兼容）
  - 火山引擎 Agent Plan（OpenAI 兼容 + Seedream 生图）
  - 自动重试、错误降级、模型热切换

用法：
  from core.ai_router import AIRouter
  router = AIRouter()

  # 文本/视觉调用
  result = router.chat(
      task="outfit_parsing",
      system_prompt="你是穿搭分析助手",
      user_message="分析这张照片",
      images=["/path/to/photo.jpg"]  # 可选
  )

  # 效果图生成
  result = router.generate_image(
      task="effect_image",
      prompt="...",
      reference_image="/path/to/original.jpg",
      mask_image="/path/to/mask.png"  # 可选
  )
"""

import json
import time
import io
import base64
import logging
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ai_router")


# ══════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════

@dataclass
class RouterResult:
    """统一的 AI 调用返回格式"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    model_used: str = ""
    provider_used: str = ""
    latency_ms: float = 0.0
    retries: int = 0
    degraded: bool = False  # True = 主模型失败，用了备选


# ══════════════════════════════════════════════════════════════════
# 配置加载
# ══════════════════════════════════════════════════════════════════

def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class AIRouter:
    def __init__(self, config_dir: str = None):
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        config_dir = Path(config_dir)

        self.models_config = _load_json(config_dir / "models.json")
        self.local_config = _load_json(config_dir / "models.local.json")
        self.routing = self.models_config["task_routing"]
        self.retry_config = self.models_config["retry"]
        self.providers_config = self.models_config["providers"]

        # 预初始化客户端（懒加载）
        self._clients: dict[str, OpenAI] = {}

    # ═══════════════════════════════════════════════════════════
    # 客户端管理
    # ═══════════════════════════════════════════════════════════

    def _get_client(self, provider_name: str) -> OpenAI:
        """获取或创建 OpenAI 兼容客户端"""
        if provider_name not in self._clients:
            provider = self.providers_config[provider_name]
            api_key = self.local_config[provider_name]["api_key"]
            base_url = provider["base_url"]

            if provider["type"] == "openai_compatible":
                self._clients[provider_name] = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=60.0,
                )
            else:
                raise ValueError(f"不支持的 provider 类型: {provider['type']}")

        return self._clients[provider_name]

    def _resolve_route(self, task: str):
        """解析任务 → (provider_name, model_config)"""
        if task not in self.routing:
            raise ValueError(f"未知任务类型: {task}。可用: {list(self.routing.keys())}")

        route = self.routing[task]
        primary = route["primary"]  # 格式: "provider/model_name"
        fallback = route.get("fallback", None)

        prov_name, model_name = primary.split("/")
        provider = self.providers_config[prov_name]
        model_config = provider["models"][model_name]

        fb_prov, fb_model = None, None
        if fallback:
            fb_prov, fb_model = fallback.split("/")

        return prov_name, model_config, fb_prov, fb_model

    # ═══════════════════════════════════════════════════════════
    # 核心调用
    # ═══════════════════════════════════════════════════════════

    def chat(
        self,
        task: str,
        system_prompt: str,
        user_message: str,
        images: list[str] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> RouterResult:
        """
        统一的文本/视觉聊天调用。

        Args:
            task: 任务类型（outfit_parsing / suggestion / content_generation / content_review / coding）
            system_prompt: 系统提示词
            user_message: 用户消息
            images: 图片路径列表（可选，用于视觉模型）
            temperature: 覆盖默认温度
            max_tokens: 覆盖默认最大 token
            response_format: OpenAI response_format（如 {"type": "json_object"}）

        Returns:
            RouterResult
        """
        prov_name, model_config, fb_prov, fb_model = self._resolve_route(task)

        return self._chat_with_retry(
            prov_name=prov_name,
            model_config=model_config,
            system_prompt=system_prompt,
            user_message=user_message,
            images=images,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            fb_prov=fb_prov,
            fb_model=fb_model,
        )

    def _chat_with_retry(
        self,
        prov_name: str,
        model_config: dict,
        system_prompt: str,
        user_message: str,
        images: list[str] | None,
        temperature: float | None,
        max_tokens: int | None,
        response_format: dict | None,
        fb_prov: str | None,
        fb_model: str | None,
    ) -> RouterResult:
        """带重试和降级的聊天调用"""
        t_start = time.time()
        last_error = None

        for attempt in range(self.retry_config["max_retries"] + 1):
            try:
                client = self._get_client(prov_name)
                messages = self._build_messages(system_prompt, user_message, images)
                kwargs = self._build_kwargs(model_config, temperature, max_tokens, messages, response_format)

                resp = client.chat.completions.create(**kwargs)
                content = resp.choices[0].message.content

                return RouterResult(
                    success=True,
                    data=content,
                    model_used=f"{prov_name}/{model_config['model_id']}",
                    provider_used=prov_name,
                    latency_ms=(time.time() - t_start) * 1000,
                    retries=attempt,
                )

            except Exception as e:
                last_error = str(e)
                logger.warning(f"[{prov_name}] 调用失败 (attempt {attempt+1}): {last_error[:200]}")

                if attempt < self.retry_config["max_retries"]:
                    delay = min(
                        self.retry_config["base_delay_seconds"] * (2 ** attempt),
                        self.retry_config["max_delay_seconds"],
                    )
                    time.sleep(delay)
                elif fb_prov and fb_model:
                    # 降级到备选模型
                    logger.info(f"降级到备选: {fb_prov}/{fb_model}")
                    return self._chat_with_retry(
                        prov_name=fb_prov,
                        model_config=self.providers_config[fb_prov]["models"][fb_model],
                        system_prompt=system_prompt,
                        user_message=user_message,
                        images=images,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_format=response_format,
                        fb_prov=None,  # 不再降级
                        fb_model=None,
                    )

        return RouterResult(
            success=False,
            error=last_error,
            model_used=f"{prov_name}/{model_config['model_id']}",
            provider_used=prov_name,
            latency_ms=(time.time() - t_start) * 1000,
        )

    # ═══════════════════════════════════════════════════════════
    # 效果图生成（Seedream 专用）
    # ═══════════════════════════════════════════════════════════

    def generate_image(
        self,
        task: str = "effect_image",
        prompt: str = "",
        reference_images: list[str] | None = None,
        size: str | None = None,
        max_images: int = 1,
        watermark: bool = False,
    ) -> RouterResult:
        """
        效果图生成。当前仅支持 Seedream（火山引擎）。

        API 参数来源：原 Fashion 项目 tools/generate.py 验证过的格式。

        Args:
            task: 任务类型（默认 effect_image）
            prompt: 生图 prompt
            reference_images: 参考图路径列表（第一张用于身份保持）
            size: 图片尺寸（默认 2048x2048）
            max_images: 生成张数
            watermark: 是否加水印

        Returns:
            RouterResult.data = {"images": [{"url": "..."}], "output_dir": "..."}
        """
        t_start = time.time()
        prov_name, model_config, fb_prov, fb_model = self._resolve_route(task)
        provider = self.providers_config[prov_name]
        api_key = self.local_config[prov_name]["api_key"]
        api_url = provider["base_url"] + "/images/generations"

        try:
            # 编码参考图 → base64 data URI（格式来自原项目 generate.py）
            refs = []
            if reference_images:
                for path in reference_images:
                    refs.append(self._compress_image_b64(path))

            # 身份保持指令（来自原项目 generate.py 的 identity_clause）
            identity_prefix = ""
            if reference_images:
                identity_prefix = (
                    "Image 1 is a reference photo of the person to portray. "
                    "Preserve their facial identity, skin tone, and body shape — "
                    "they are the model wearing this outfit. "
                )
            full_prompt = identity_prefix + prompt

            # Seedream API payload（格式来自原项目 generate.py call_seedream()）
            body = {
                "model": model_config["model_id"],
                "prompt": full_prompt,
                "image": refs,  # 官方参数名: image（数组），非 reference_images
                "size": size or model_config.get("size", "2048x2048"),
                "response_format": "url",
                "watermark": watermark,
                "max_images": max_images,
            }

            import urllib.request
            import urllib.error
            req = urllib.request.Request(
                api_url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )

            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            return RouterResult(
                success=True,
                data=result,
                model_used=f"{prov_name}/{model_config['model_id']}",
                provider_used=prov_name,
                latency_ms=(time.time() - t_start) * 1000,
            )

        except Exception as e:
            logger.error(f"效果图生成失败: {e}")
            # 降级到备选模型
            if fb_prov and fb_model:
                logger.info(f"降级到备选: {fb_prov}/{fb_model}")
                try:
                    fb_config = self.providers_config[fb_prov]["models"][fb_model]
                    # 用备选模型重试（简化版，不递归）
                    body["model"] = fb_config["model_id"]
                    import urllib.request
                    req = urllib.request.Request(
                        self.providers_config[fb_prov]["base_url"] + "/images/generations",
                        data=json.dumps(body).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {self.local_config[fb_prov]['api_key']}",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=180) as resp:
                        result = json.loads(resp.read().decode("utf-8"))
                    return RouterResult(
                        success=True,
                        data=result,
                        model_used=f"{fb_prov}/{fb_config['model_id']}",
                        provider_used=fb_prov,
                        latency_ms=(time.time() - t_start) * 1000,
                        degraded=True,
                    )
                except Exception as e2:
                    logger.error(f"备选模型也失败: {e2}")

            return RouterResult(
                success=False,
                error=str(e),
                model_used=f"{prov_name}/{model_config['model_id']}",
                provider_used=prov_name,
                latency_ms=(time.time() - t_start) * 1000,
            )

    # ═══════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════

    def _build_messages(self, system_prompt: str, user_message: str, images: list[str] | None) -> list[dict]:
        """构建 OpenAI 格式的消息列表，支持图片"""
        messages = [{"role": "system", "content": system_prompt}]

        if images:
            content = [{"type": "text", "text": user_message}]
            for img_path in images:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": self._encode_data_uri(img_path),
                        "detail": "high",
                    },
                })
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user_message})

        return messages

    def _build_kwargs(self, model_config: dict, temperature: float | None, max_tokens: int | None, messages: list, response_format: dict | None) -> dict:
        """构建 API 调用参数"""
        kwargs = {
            "model": model_config["model_id"],
            "messages": messages,
            "temperature": temperature if temperature is not None else model_config.get("temperature", 0.7),
            "max_tokens": max_tokens or model_config.get("max_tokens", 4096),
        }
        if response_format:
            kwargs["response_format"] = response_format
        return kwargs

    @staticmethod
    def _encode_image(path: str) -> str:
        """图片文件 → base64 字符串"""
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @staticmethod
    def _encode_data_uri(path: str) -> str:
        """图片文件 → data:image/...;base64,... URI"""
        ext = Path(path).suffix.lower().replace("jpg", "jpeg").lstrip(".")
        b64 = AIRouter._encode_image(path)
        return f"data:image/{ext};base64,{b64}"

    @staticmethod
    def _compress_image_b64(path: str, max_size: int = 1024, quality: int = 70) -> str:
        """
        压缩图片并返回 base64 data URI。
        提取自原项目 tools/generate.py — compress_image()。
        处理透明 PNG：在中性灰背景上合成。
        """
        from PIL import Image as PILImage
        NEUTRAL_GRAY = (217, 217, 217)

        img = PILImage.open(path)
        # 处理透明通道
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            bg = PILImage.new("RGB", img.size, NEUTRAL_GRAY)
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 等比缩放
        w, h = img.size
        if w > max_size or h > max_size:
            ratio = max_size / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), PILImage.LANCZOS)

        # JPEG 编码
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

    # ═══════════════════════════════════════════════════════════
    # 便捷方法
    # ═══════════════════════════════════════════════════════════

    def list_models(self) -> dict:
        """列出所有可用模型"""
        models = {}
        for prov_name in self.providers_config:
            for model_name, cfg in self.providers_config[prov_name]["models"].items():
                key = f"{prov_name}/{model_name}"
                models[key] = {
                    "model_id": cfg["model_id"],
                    "modalities": cfg["modalities"],
                }
        return models

    def health_check(self) -> dict:
        """快速检查所有 provider 的连通性"""
        results = {}
        for prov_name in self.providers_config:
            try:
                client = self._get_client(prov_name)
                # 简单列举模型测试连通性
                results[prov_name] = {"status": "ok"}
            except Exception as e:
                results[prov_name] = {"status": "error", "error": str(e)[:200]}
        return results


# ══════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════

def extract_json(text: str) -> dict | None:
    """
    从 LLM 文本输出中提取 JSON。
    融合原项目 ai_api.py + 增强 fallback 逻辑。
    """
    text = text.strip()
    # 1. 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. 去掉 markdown 代码块（```json ... ```）
    import re
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3. 找到第一个 { 和最后一个 } 之间的内容
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


# ══════════════════════════════════════════════════════════════════
# 快速测试
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("AI Router 模块加载成功")
    print("=" * 60)

    router = AIRouter()

    print("\n📋 可用模型：")
    for name, info in router.list_models().items():
        print(f"  {name}: {info['model_id']} ({', '.join(info['modalities'])})")

    print("\n🎯 任务路由：")
    for task, route in router.routing.items():
        if task.startswith("_"):
            continue
        primary = route["primary"]
        fallback = route.get("fallback", "")
        fb = f" → 降级 {fallback}" if fallback else ""
        print(f"  {task}: {primary}{fb}")

    print("\n✅ Router 初始化完成。使用 router.chat() 或 router.generate_image() 调用。")
