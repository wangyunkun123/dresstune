"""
天气获取 — wttr.in 免费 API。
提取自原项目 tools/weather_advisor.py，精简为 Phase 0 所需。

用法：
  from core.weather import get_weather
  w = get_weather("Beijing")
  # w = {"temp": 28, "desc": "晴", "icon": "☀️", "season": "early_summer", ...}
"""

from __future__ import annotations

import json
import urllib.request


def get_weather(location: str = "Beijing") -> dict | None:
    """
    获取指定位置的当前天气 + 季节标签。

    Returns:
        {
            "temp": 28,           # 当前温度 °C
            "humidity": 50,       # 湿度 %
            "desc": "晴",         # 中文天气描述
            "icon": "☀️",         # emoji 图标
            "wind": 10,           # 风速 km/h
            "precip": 0.0,        # 降水量 mm
            "season": "early_summer",  # 季节标签（用于穿搭快照）
            "summary": "☀️ 晴 28°C 湿度50%"
        }
        或 None（获取失败）
    """
    url = f"https://wttr.in/{location}?format=j1&lang=zh"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DressTune/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    current = data.get("current_condition", [{}])[0]
    temp = int(current.get("temp_C", 25))
    humidity = int(current.get("humidity", 50))
    wind = int(current.get("windspeedKmph", 10))
    desc_en = current.get("weatherDesc", [{}])[0].get("value", "Clear")
    precip = float(current.get("precipMM", 0))

    desc_zh, icon = _translate_weather(desc_en)
    season = _get_season(temp)

    return {
        "temp": temp,
        "humidity": humidity,
        "wind": wind,
        "desc": desc_zh,
        "icon": icon,
        "precip": precip,
        "season": season,
        "summary": f"{icon} {desc_zh} {temp}°C 湿度{humidity}%",
    }


def _translate_weather(desc_en: str) -> tuple[str, str]:
    """英文天气描述 → (中文, emoji)"""
    weather_map = {
        "sunny": ("晴", "☀️"),
        "clear": ("晴", "☀️"),
        "partly cloudy": ("多云", "⛅"),
        "cloudy": ("阴", "☁️"),
        "overcast": ("阴", "☁️"),
        "mist": ("雾", "🌫️"),
        "fog": ("雾", "🌫️"),
        "rain": ("雨", "🌧️"),
        "light rain": ("小雨", "🌦️"),
        "moderate rain": ("中雨", "🌧️"),
        "heavy rain": ("大雨", "🌧️"),
        "thunderstorm": ("雷暴", "⛈️"),
        "snow": ("雪", "❄️"),
        "light snow": ("小雪", "🌨️"),
        "heavy snow": ("大雪", "❄️"),
        "sleet": ("雨夹雪", "🌨️"),
        "drizzle": ("毛毛雨", "🌦️"),
        "wind": ("大风", "💨"),
    }
    key = desc_en.lower().strip()
    if key in weather_map:
        return weather_map[key]
    for k, v in weather_map.items():
        if k in key:
            return v
    return (desc_en, "🌤️")


def _get_season(temp: int) -> str:
    """根据温度推断季节标签（产品设计文档 6.3 定义）"""
    # 简化版：只基于温度。实际使用时结合月份更准确。
    if temp <= 5:
        return "winter"
    elif temp <= 15:
        return "spring" if temp > 10 else "late_autumn"
    elif temp <= 22:
        return "spring"
    elif temp <= 28:
        return "early_summer"
    elif temp <= 35:
        return "peak_summer"
    else:
        return "peak_summer"
