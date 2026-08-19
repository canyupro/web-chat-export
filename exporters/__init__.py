"""导出器工厂：按 platform + engine 构建对应数据源（ChatProvider）。

可用平台：deepseek / chatgpt / qwen / doubao / grok
可用引擎：http（纯 requests 重放）/ browser（Playwright 收割）

engine 选择规则：
  - deepseek / chatgpt：http（chatgpt 需 socks 代理 + curl_cffi 可选）
  - qwen / doubao / grok：browser（HttpOnly Cookie / ut 签名，纯 http 拿不到）
  显式指定 engine 可覆盖默认。

build_exporter 是 build_provider 的向后兼容别名（返回对象类型完全相同，
只是概念上从「导出器」细化为「数据源」，导出能力已拆到 ExportPipeline）。
"""
from typing import Optional

from models import ExportConfig
from exporters.provider import ChatProvider


def default_engine(platform: str) -> str:
    """各平台的默认引擎"""
    if platform in ("deepseek", "chatgpt"):
        return "http"
    return "browser"


def build_provider(config: ExportConfig) -> ChatProvider:
    """按配置构建数据源（平台适配器）"""
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


# 向后兼容：旧工厂名返回相同对象（类名不变，test_factory 断言继续成立）
build_exporter = build_provider


__all__ = ["ChatProvider", "build_provider", "build_exporter", "default_engine"]
