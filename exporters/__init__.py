"""导出器工厂：按 platform + engine 构建对应导出器。

可用平台：deepseek / chatgpt / qwen / doubao / grok
可用引擎：http（纯 requests 重放）/ browser（Playwright 收割）

engine 选择规则：
  - deepseek / chatgpt：http（chatgpt 需 socks 代理 + curl_cffi 可选）
  - qwen / doubao / grok：browser（HttpOnly Cookie / ut 签名，纯 http 拿不到）
  显式指定 engine 可覆盖默认。
"""
from typing import Optional

from models import ExportConfig
from exporters.base import BaseExporter


def default_engine(platform: str) -> str:
    """各平台的默认引擎"""
    if platform in ("deepseek", "chatgpt"):
        return "http"
    return "browser"


def build_exporter(config: ExportConfig) -> BaseExporter:
    """按配置构建导出器"""
    platform = config.platform.lower()
    engine = (config.engine or default_engine(platform)).lower()

    if platform == "deepseek":
        from exporters.deepseek import DeepSeekHttpExporter
        return DeepSeekHttpExporter(config)
    if platform == "chatgpt":
        from exporters.chatgpt import ChatGPTHttpExporter
        return ChatGPTHttpExporter(config)
    if platform == "qwen":
        if engine == "browser":
            from exporters.qwen import QwenBrowserExporter
            return QwenBrowserExporter(config)
        from exporters.qwen_http import QwenHttpExporter
        return QwenHttpExporter(config)
    if platform == "doubao":
        from exporters.doubao import DoubaoBrowserExporter
        return DoubaoBrowserExporter(config)
    if platform == "grok":
        from exporters.grok import GrokBrowserExporter
        return GrokBrowserExporter(config)

    raise ValueError(
        f"未知平台: {platform}（可选: deepseek, chatgpt, qwen, doubao, grok）"
    )


__all__ = ["BaseExporter", "build_exporter", "default_engine"]
